from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.lock_update import update_project_module_lock
from hocuspocus.hocusscript.project import ProjectError, verify_project_lock
from hocuspocus.hocusscript.resolved_modules import ModuleResolutionError, ResolvedModuleLimits
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

    def test_stale_manifest_or_catalog_repairs_from_sources_not_old_records(self) -> None:
        from hocuspocus.hocusscript import project as project_module

        for drift in ("manifest", "catalog"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _updatable_project(root)
                lock = root / "pins/hocus.lock.json"
                payload = json.loads(lock.read_text("utf-8"))
                forged_digest = "sha256:" + "f" * 64
                payload["modules"][0]["contentDigest"] = forged_digest
                lock.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                expected = project_module._canonical_lock_file_digest(lock)

                if drift == "manifest":
                    manifest = root / "hocus.project.toml"
                    text = manifest.read_text("utf-8")
                    original = 'module_directories = ["modules-a", "modules-b"]'
                    self.assertIn(original, text)
                    manifest.write_text(
                        text.replace(original, 'module_directories = ["modules-b", "modules-a"]'),
                        encoding="utf-8",
                    )
                else:
                    catalog = root / "catalog/catalog.json"
                    catalog.write_bytes(catalog.read_bytes() + b" ")

                repaired = update_project_module_lock(
                    root, ["src/main.hocus"], allow_write=True,
                    expected_lock_digest=expected,
                )
                self.assertEqual(repaired.previous_lock_digest, expected)
                self.assertFalse(repaired.diff_available)
                self.assertNotIn(forged_digest, {item.content_digest for item in repaired.modules})
                self.assertEqual(verify_project_lock(root).lock_digest, repaired.lock_digest)

    def test_metadata_drift_after_source_recheck_aborts_before_publication(self) -> None:
        from hocuspocus.hocusscript import lock_update as lock_update_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            lock = root / "pins/hocus.lock.json"
            original_lock = lock.read_bytes()
            digest = verify_project_lock(root).lock_digest
            original_derive = lock_update_module._derive_under_lease

            def derive_then_drift(*args, **kwargs):
                records, entries, envelopes, recheck = original_derive(*args, **kwargs)

                def recheck_then_mutate_catalog():
                    recheck()
                    catalog = root / "catalog/catalog.json"
                    catalog.write_bytes(catalog.read_bytes() + b" ")

                return records, entries, envelopes, recheck_then_mutate_catalog

            with patch(
                "hocuspocus.hocusscript.lock_update._derive_under_lease",
                new=derive_then_drift,
            ):
                with self.assertRaises(ProjectError) as changed:
                    update_project_module_lock(
                        root, ["src/main.hocus"], allow_write=True,
                        expected_lock_digest=digest,
                    )
            self.assertEqual(changed.exception.code, "HOCUS453")
            self.assertEqual(lock.read_bytes(), original_lock)

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

    def test_module_file_limit_counts_visiting_ancestors_before_overread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            lock = root / "pins/hocus.lock.json"
            original = lock.read_bytes()
            digest = verify_project_lock(root).lock_digest
            with self.assertRaises(ModuleResolutionError) as rejected:
                update_project_module_lock(
                    root,
                    ["src/main.hocus"],
                    allow_write=True,
                    expected_lock_digest=digest,
                    limits=ResolvedModuleLimits(module_files=1),
                )
            self.assertEqual(rejected.exception.code, "HOCUS464")
            self.assertEqual(lock.read_bytes(), original)

    def test_nested_external_alias_fails_closed_without_external_path_resolution(self) -> None:
        from hocuspocus.hocusscript import lock_update as lock_update_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _updatable_project(root)
            lock = root / "pins/hocus.lock.json"
            original_lock = lock.read_bytes()
            digest = verify_project_lock(root).lock_digest
            nested = root / "modules-b/root.hocus"
            nested.write_bytes(
                b'hocus 0.2; import { Remote } from "@studio/remote.hocus"; '
                b'module Root() exports () {}'
            )
            real_canonical = lock_update_module._canonical_file
            resolved_candidates: list[Path] = []

            def record_canonical(path, *args, **kwargs):
                resolved_candidates.append(Path(path))
                return real_canonical(path, *args, **kwargs)

            with patch(
                "hocuspocus.hocusscript.lock_update._canonical_file",
                new=record_canonical,
            ):
                with self.assertRaises(ProjectError) as blocked:
                    update_project_module_lock(
                        root, ["src/main.hocus"], allow_write=True,
                        expected_lock_digest=digest,
                    )
            self.assertEqual(blocked.exception.code, "HOCUS460")
            self.assertTrue(resolved_candidates)
            self.assertTrue(all(
                path.resolve(strict=False).is_relative_to(root.resolve())
                for path in resolved_candidates
            ))
            self.assertEqual(lock.read_bytes(), original_lock)

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

    def test_cancellation_and_publish_failure_cleanup_lease_and_temporary_files(self) -> None:
        for mode in ("cancel", "replace"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _updatable_project(root)
                lock = root / "pins/hocus.lock.json"
                original = lock.read_bytes()
                digest = verify_project_lock(root).lock_digest
                if mode == "cancel":
                    calls = 0

                    def cancel_under_lease():
                        nonlocal calls
                        calls += 1
                        return calls >= 2

                    context = self.assertRaises(ModuleResolutionError)
                    callback = cancel_under_lease
                else:
                    context = self.assertRaises(ProjectError)
                    patcher = patch(
                        "hocuspocus.hocusscript.project.os.replace",
                        side_effect=OSError("replace failed"),
                    )
                    callback = None

                with context:
                    if mode == "cancel":
                        update_project_module_lock(
                            root, ["src/main.hocus"], allow_write=True,
                            expected_lock_digest=digest, cancelled=callback,
                        )
                    else:
                        with patcher:
                            update_project_module_lock(
                                root, ["src/main.hocus"], allow_write=True,
                                expected_lock_digest=digest,
                            )
                self.assertEqual(lock.read_bytes(), original)
                self.assertFalse((root / "pins/.hocus.lock.json.update-lease").exists())
                self.assertEqual(list((root / "pins").glob(".hocus.lock.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
