from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.project import (
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    update_project_lock,
)
from hocuspocus.hocusscript.resolver import resolve_project_module_dag


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _library_manifest(
    uid: str,
    version: str,
    entries: tuple[str, ...] = ("modules/main.hocus",),
    *,
    language: str = "0.2",
) -> bytes:
    quoted = ", ".join(json.dumps(item) for item in entries)
    return (
        "schema_version = 1\n"
        f"entry_modules = [{quoted}]\n"
        "[library]\n"
        f'uid = "{uid}"\n'
        f'version = "{version}"\n'
        "[language]\n"
        f'version = "{language}"\n'
    ).encode("utf-8")


def _write_library(root: Path, raw: bytes) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hocus.module.toml").write_bytes(raw)


def _write_project(
    root: Path,
    aliases: tuple[tuple[str, str, str, str | None], ...],
) -> None:
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "tests" / "fixtures" / "hocusscript" / "catalog" / "catalog-v1.json",
        root / "catalog" / "catalog.json",
    )
    tables = "".join(
        f'''[external_aliases.{alias}]
library_uid = "{uid}"
version = "{version}"
''' + (
            f'module_manifest_digest = "{manifest_digest}"\n'
            if manifest_digest is not None else ""
        )
        for alias, uid, version, manifest_digest in aliases
    )
    (root / "hocus.project.toml").write_text(
        '''schema_version = 3
[project]
uid = "external-root-project"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "0.2"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
''' + tables,
        encoding="utf-8",
    )
    update_project_lock(root, [], allow_write=True)


def _inspect(project: Path, roots: dict[str, Path], *, cancelled=None):
    from hocuspocus.hocusscript.external_roots import inspect_external_module_roots
    return inspect_external_module_roots(project, roots, cancelled=cancelled)


class ExternalModuleRootsTests(unittest.TestCase):
    def test_relocation_order_pins_and_host_path_absence_without_source_reads(self) -> None:
        payloads = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            physical_roots: list[Path] = []
            for base_text in (first, second):
                base = Path(base_text)
                project = base / "project"
                alpha = base / "approved-alpha"
                beta = base / "approved-beta"
                alpha_raw = _library_manifest("alpha-library", "1.2.3")
                beta_raw = _library_manifest("beta-library", "2.0.0", ("entry.hocus",))
                _write_library(alpha, alpha_raw)
                _write_library(beta, beta_raw)
                # Listed source files intentionally do not exist: inspection is manifest-only.
                _write_project(project, (
                    ("alpha", "alpha-library", "1.2.3", _digest(alpha_raw)),
                    ("beta", "beta-library", "2.0.0", _digest(beta_raw)),
                ))
                result = _inspect(project, {"beta": beta, "alpha": alpha})
                self.assertEqual([item.alias for item in result.libraries], ["alpha", "beta"])
                self.assertEqual(result.libraries[0].entry_modules, ("modules/main.hocus",))
                self.assertEqual(result.libraries[1].entry_modules, ("entry.hocus",))
                payload = result.to_dict()
                self.assertEqual(payload["projectUid"], "external-root-project")
                self.assertTrue(payload["inspectionDigest"].startswith("sha256:"))
                payloads.append(payload)
                physical_roots.extend((project, alpha, beta))
                rendered = json.dumps(payload, sort_keys=True) + repr(result)
                for path in physical_roots:
                    self.assertNotIn(str(path), rendered)
            self.assertEqual(payloads[0], payloads[1])

    def test_requires_exact_alias_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = base / "project", base / "alpha", base / "beta"
            alpha_raw = _library_manifest("alpha-library", "1.0.0")
            beta_raw = _library_manifest("beta-library", "1.0.0")
            _write_library(alpha, alpha_raw)
            _write_library(beta, beta_raw)
            _write_project(project, (
                ("alpha", "alpha-library", "1.0.0", _digest(alpha_raw)),
                ("beta", "beta-library", "1.0.0", _digest(beta_raw)),
            ))
            for roots in (
                {"alpha": alpha},
                {"alpha": alpha, "beta": beta, "extra": beta},
                {"alpha": alpha, "wrong": beta},
            ):
                with self.subTest(roots=tuple(roots)), self.assertRaises(ProjectError) as rejected:
                    _inspect(project, roots)
                self.assertEqual(rejected.exception.code, "HOCUS458")

    def test_unpinned_manifest_is_inspectable_but_not_resolution_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", None),))
            result = _inspect(project, {"studio": library})
            self.assertEqual(result.libraries[0].module_manifest_digest, _digest(raw))

            from hocuspocus.hocusscript.external_roots import _validate_external_module_roots
            session = _validate_external_module_roots(project, {"studio": library})
            with self.assertRaises(ProjectError) as unpinned:
                session.root_for_alias("studio")
            self.assertEqual(unpinned.exception.code, "HOCUS458")

    def test_hostile_pathlike_and_lexically_forbidden_roots_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))

            class HostilePath:
                def __fspath__(self):
                    raise RuntimeError("secret-host-path")

            hostile_values = (
                HostilePath(),
                "~/.hocus-library",
                "bad\x00root",
                r"\\server\share\library",
                r"\\?\C:\secret\library",
                r"\\.\C:\secret\library",
            )
            for value in hostile_values:
                with self.subTest(value=type(value).__name__), self.assertRaises(ProjectError) as rejected:
                    _inspect(project, {"studio": value})
                rendered = json.dumps(rejected.exception.to_dict()) + str(rejected.exception)
                self.assertEqual(rejected.exception.code, "HOCUS458")
                self.assertNotIn("secret-host-path", rendered)
                self.assertNotIn(str(library), rendered)

    def test_rejects_relative_project_overlapping_and_reparse_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
            cases = (
                Path("relative-library"),
                project,
                project / "modules",
                library / "hocus.module.toml",
                base / "missing-library",
            )
            for candidate in cases:
                with self.subTest(candidate=candidate), self.assertRaises(ProjectError) as rejected:
                    _inspect(project, {"studio": candidate})
                self.assertEqual(rejected.exception.code, "HOCUS458")

            link = base / "library-link"
            try:
                link.symlink_to(library, target_is_directory=True)
            except OSError:
                return
            with self.assertRaises(ProjectError) as reparse:
                _inspect(project, {"studio": link})
            self.assertEqual(reparse.exception.code, "HOCUS458")

    def test_rejects_overlapping_approved_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            parent, child = base / "libraries", base / "libraries" / "child"
            parent_raw = _library_manifest("parent-library", "1.0.0")
            child_raw = _library_manifest("child-library", "1.0.0")
            _write_library(parent, parent_raw)
            _write_library(child, child_raw)
            _write_project(project, (
                ("parent", "parent-library", "1.0.0", _digest(parent_raw)),
                ("child", "child-library", "1.0.0", _digest(child_raw)),
            ))
            with self.assertRaises(ProjectError) as overlap:
                _inspect(project, {"parent": parent, "child": child})
            self.assertEqual(overlap.exception.code, "HOCUS458")

    def test_manifest_decode_identity_language_entry_and_digest_conflicts_fail(self) -> None:
        cases = (
            (b"not = [valid", "library", "1.0.0", None, "HOCUS457"),
            (_library_manifest("wrong-library", "1.0.0"), "library", "1.0.0", None, "HOCUS458"),
            (_library_manifest("library", "2.0.0"), "library", "1.0.0", None, "HOCUS458"),
            (_library_manifest("library", "1.0.0", language="0.1"), "library", "1.0.0", None, "HOCUS457"),
            (_library_manifest("library", "1.0.0", ("../escape.hocus",)), "library", "1.0.0", None, "HOCUS457"),
            (_library_manifest("library", "1.0.0"), "library", "1.0.0", "sha256:" + "0" * 64, "HOCUS458"),
        )
        for raw, uid, version, expected_override, code in cases:
            with self.subTest(code=code, raw=raw[:30]), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                project, library = base / "project", base / "library"
                _write_library(library, raw)
                expected = expected_override or _digest(raw)
                _write_project(project, (("studio", uid, version, expected),))
                with self.assertRaises(ProjectError) as rejected:
                    _inspect(project, {"studio": library})
                self.assertEqual(rejected.exception.code, code)

    def test_manifest_file_shape_size_reparse_and_same_byte_identity_fail_closed(self) -> None:
        raw = _library_manifest("library", "1.0.0")
        for shape in ("missing", "directory", "oversized", "invalid_utf8"):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                project, library = base / "project", base / "library"
                library.mkdir()
                manifest = library / "hocus.module.toml"
                if shape == "directory":
                    manifest.mkdir()
                elif shape == "oversized":
                    manifest.write_bytes(b"x" * (256 * 1024 + 1))
                elif shape == "invalid_utf8":
                    manifest.write_bytes(b"\xff\xfe")
                _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
                with self.assertRaises(ProjectError):
                    _inspect(project, {"studio": library})

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library, target = base / "project", base / "library", base / "manifest-target.toml"
            library.mkdir()
            target.write_bytes(raw)
            try:
                (library / "hocus.module.toml").symlink_to(target)
            except OSError:
                pass
            else:
                _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
                with self.assertRaises(ProjectError) as reparse:
                    _inspect(project, {"studio": library})
                self.assertEqual(reparse.exception.code, "HOCUS458")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
            from hocuspocus.hocusscript import external_roots as roots_module
            original = roots_module._read_module_manifest
            calls = 0

            def replace_same_bytes(*args, **kwargs):
                nonlocal calls
                result = original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    manifest = library / "hocus.module.toml"
                    replacement = library / "replacement.toml"
                    replacement.write_bytes(raw)
                    replacement.replace(manifest)
                return result

            with patch.object(roots_module, "_read_module_manifest", side_effect=replace_same_bytes):
                with self.assertRaises(ProjectError) as replaced:
                    _inspect(project, {"studio": library})
            self.assertEqual(replaced.exception.code, "HOCUS458")

    def test_duplicate_library_uid_and_invalid_cancellation_callback_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, first, second = base / "project", base / "first", base / "second"
            raw = _library_manifest("shared-library", "1.0.0")
            _write_library(first, raw)
            _write_library(second, raw)
            _write_project(project, (
                ("first", "shared-library", "1.0.0", _digest(raw)),
                ("second", "shared-library", "1.0.0", _digest(raw)),
            ))
            with self.assertRaises(ProjectError) as duplicate:
                _inspect(project, {"first": first, "second": second})
            self.assertEqual(duplicate.exception.code, "HOCUS458")

            for callback in (lambda: "yes", lambda: (_ for _ in ()).throw(RuntimeError("secret"))):
                with self.assertRaises(ProjectError) as cancelled:
                    _inspect(project, {"first": first, "second": second}, cancelled=callback)
                self.assertEqual(cancelled.exception.code, "HOCUS465")
                self.assertNotIn("secret", json.dumps(cancelled.exception.to_dict()))

    def test_lock_conflict_drift_and_cancellation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))

            context = ProjectContext.load(project)
            conflicting = ModuleLockRecord(
                "hocus-module://library/modules/main.hocus",
                None,
                "library",
                "1.0.0",
                "sha256:" + "0" * 64,
                "0.2",
                "modules/main.hocus",
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
                (),
                "studio",
            )
            with patch(
                "hocuspocus.hocusscript.external_roots.ProjectContext.load",
                return_value=replace(context, locked_modules=(conflicting,)),
            ), self.assertRaises(ProjectError) as lock_conflict:
                _inspect(project, {"studio": library})
            self.assertEqual(lock_conflict.exception.code, "HOCUS458")

            with patch(
                "hocuspocus.hocusscript.external_roots.ProjectContext.load",
                side_effect=AssertionError("project read must not run"),
            ), self.assertRaises(ProjectError) as cancelled:
                _inspect(project, {"studio": library}, cancelled=lambda: True)
            self.assertEqual(cancelled.exception.code, "HOCUS465")

            from hocuspocus.hocusscript import external_roots as roots_module
            original = roots_module._read_bounded_stable
            calls = 0

            def drift(path, *args, **kwargs):
                nonlocal calls
                result = original(path, *args, **kwargs)
                calls += 1
                if calls == 1:
                    Path(path).write_bytes(result + b"\n")
                return result

            with patch.object(roots_module, "_read_bounded_stable", side_effect=drift):
                with self.assertRaises(ProjectError) as changed:
                    _inspect(project, {"studio": library})
            self.assertEqual(changed.exception.code, "HOCUS458")

            lock = project / "pins" / "hocus.lock.json"
            payload = json.loads(lock.read_text("utf-8"))
            payload["projectUid"] = "other-project"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ProjectError):
                _inspect(project, {"studio": library})

    def test_inspection_does_not_enable_existing_external_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
            (project / "src" / "main.hocus").write_text(
                'hocus 0.2; import { Main } from "@studio/modules/main.hocus"; '
                'graph MainGraph { target "/obj/main"; }',
                encoding="utf-8",
            )
            _inspect(project, {"studio": library})
            with self.assertRaises(ProjectError) as disabled:
                resolve_project_module_dag(project, "src/main.hocus")
            self.assertIn(disabled.exception.code, {"HOCUS460", "HOCUS462"})


if __name__ == "__main__":
    unittest.main()
