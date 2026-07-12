from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.lock_update import update_project_module_lock
from hocuspocus.hocusscript.project import ProjectError, verify_project_lock
from hocuspocus.hocusscript.resolved_modules import ModuleResolutionError
from test_hocusscript_resolver import _valid_project


def _updatable_project(root: Path) -> None:
    _valid_project(root)
    (root / "src/main.hocus").write_bytes(
        b'hocus 0.2; import { Root } from "root.hocus"; '
        b'graph Main { target "/obj/main"; }'
    )


class DerivedModuleLockUpdateTests(unittest.TestCase):
    def test_default_denies_without_io_and_stale_digest_preserves_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            lock = root / "pins/hocus.lock.json"
            before = lock.read_bytes()
            with self.assertRaises(ProjectError) as denied:
                update_project_module_lock(root, ["src/main.hocus"])
            self.assertEqual(denied.exception.code, "HOCUS455")
            with self.assertRaises(ProjectError) as stale:
                update_project_module_lock(
                    root, ["src/main.hocus"], allow_write=True,
                    expected_lock_digest="sha256:" + "f" * 64,
                )
            self.assertEqual(stale.exception.code, "HOCUS453")
            self.assertEqual(lock.read_bytes(), before)

    def test_create_union_and_repeat_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            (root / "src/other.hocus").write_bytes(
                b'hocus 0.2; import { Leaf } from "leaf.hocus"; '
                b'graph Other { target "/obj/other"; }'
            )
            lock = root / "pins/hocus.lock.json"
            lock.unlink()
            created = update_project_module_lock(
                root, ["src/other.hocus", "src/main.hocus"], allow_write=True,
            )
            self.assertTrue(created.changed)
            self.assertEqual(len(created.entries), 2)
            self.assertEqual(len(created.modules), 2)
            first_bytes = lock.read_bytes()
            repeated = update_project_module_lock(
                root, ["src/main.hocus", "src/other.hocus"], allow_write=True,
                expected_lock_digest=created.lock_digest,
            )
            self.assertFalse(repeated.changed)
            self.assertEqual(repeated.lock_digest, created.lock_digest)
            self.assertEqual(lock.read_bytes(), first_bytes)

    def test_changed_source_and_resolution_winner_abort_before_write(self) -> None:
        for mode in ("source", "shadow"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _updatable_project(root)
                lock = root / "pins/hocus.lock.json"
                original_lock = lock.read_bytes()
                digest = verify_project_lock(root).lock_digest
                from hocuspocus.hocusscript import project as project_module
                atomic = project_module._atomic_write_lock

                def race(path, content, **kwargs):
                    if mode == "source":
                        (root / "modules-b/root.hocus").write_bytes(
                            b"hocus 0.2; module Root() exports () {}"
                        )
                    else:
                        (root / "modules-a/root.hocus").write_bytes(
                            b"hocus 0.2; module Root() exports () {}"
                        )
                    return atomic(path, content, **kwargs)

                with patch("hocuspocus.hocusscript.project._atomic_write_lock", new=race):
                    with self.assertRaises((ProjectError, ModuleResolutionError)):
                        update_project_module_lock(
                            root, ["src/main.hocus"], allow_write=True,
                            expected_lock_digest=digest,
                        )
                self.assertEqual(lock.read_bytes(), original_lock)

    def test_cycle_and_invalid_expansion_leave_old_lock_unchanged(self) -> None:
        for invalid in ("cycle", "expansion"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _updatable_project(root)
                lock = root / "pins/hocus.lock.json"
                original = lock.read_bytes()
                digest = verify_project_lock(root).lock_digest
                if invalid == "cycle":
                    (root / "modules-b/leaf.hocus").write_bytes(
                        b'hocus 0.2; import { Root } from "./root.hocus"; module Leaf() exports () {}'
                    )
                else:
                    (root / "src/main.hocus").write_bytes(
                        b'hocus 0.2; import { Root } from "root.hocus"; '
                        b'graph Main { target "/obj/main"; use bad @id("bad") = Root(extra = 1); }'
                    )
                with self.assertRaises(Exception):
                    update_project_module_lock(
                        root, ["src/main.hocus"], allow_write=True,
                        expected_lock_digest=digest,
                    )
                self.assertEqual(lock.read_bytes(), original)

    def test_portable_entry_alias_and_hostile_iterable_are_typed_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            (root / "src/A.hocus").write_bytes(b"hocus 0.2; graph A {}")
            (root / "src/a.hocus").write_bytes(b"hocus 0.2; graph B {}")
            lock = root / "pins/hocus.lock.json"
            original = lock.read_bytes()
            with self.assertRaises(ProjectError):
                update_project_module_lock(
                    root, ["src/A.hocus", "src/a.hocus"], allow_write=True,
                    expected_lock_digest=verify_project_lock(root).lock_digest,
                )
            def hostile():
                yield "src/main.hocus"
                raise RuntimeError("secret")
            with self.assertRaises(ProjectError) as captured:
                update_project_module_lock(
                    root, hostile(), allow_write=True,
                    expected_lock_digest=verify_project_lock(root).lock_digest,
                )
            self.assertNotIn("secret", captured.exception.message)
            self.assertEqual(lock.read_bytes(), original)

    def test_atomic_replace_failure_preserves_existing_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            lock = root / "pins/hocus.lock.json"
            original = lock.read_bytes()
            digest = verify_project_lock(root).lock_digest
            with patch("hocuspocus.hocusscript.project.os.replace",
                       side_effect=OSError("replace failed")):
                with self.assertRaises(ProjectError) as failed:
                    update_project_module_lock(
                        root, ["src/main.hocus"], allow_write=True,
                        expected_lock_digest=digest,
                    )
            self.assertEqual(failed.exception.code, "HOCUS454")
            self.assertEqual(lock.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
