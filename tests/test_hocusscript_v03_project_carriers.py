from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (  # noqa: E402
    ModuleManifest,
    ProjectContext,
    ProjectError,
    compile_path,
    decode_module_manifest,
    update_project_lock,
    verify_project_lock,
)
from hocuspocus.hocusscript.catalog import decode_catalog_snapshot  # noqa: E402
from hocuspocus.hocusscript.cli import main  # noqa: E402
from hocuspocus.hocusscript.project import (  # noqa: E402
    LOCK_SCHEMA_URI_V4,
    PROJECT_SCHEMA_URI_V4,
)


DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)
DIGEST_C = "sha256:" + ("c" * 64)


def _manifest(*, schema_version: int = 4, language_version: str = "0.3") -> str:
    return f'''schema_version = {schema_version}
[project]
uid = "control-project"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "{language_version}"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
'''


def _module_record(*, language_version: str = "0.3") -> dict:
    return {
        "moduleUri": "hocus-project://control-project/tools/repeat.hocus",
        "projectUid": "control-project",
        "libraryUid": None,
        "libraryVersion": None,
        "moduleManifestDigest": None,
        "languageVersion": language_version,
        "sourcePath": "tools/repeat.hocus",
        "contentDigest": DIGEST_A,
        "interfaceDigest": DIGEST_B,
        "transitiveDigest": DIGEST_C,
        "dependencies": [],
        "externalAlias": None,
    }


def _write_project(
    root: Path,
    *,
    manifest: str | None = None,
    lock_schema_version: int = 4,
    lock_language_version: str = "0.3",
    module_language_version: str = "0.3",
) -> bytes:
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    manifest_raw = (manifest or _manifest()).encode("utf-8")
    (root / "hocus.project.toml").write_bytes(manifest_raw)
    catalog_path = root / "catalog" / "catalog.json"
    shutil.copyfile(
        ROOT / "tests" / "fixtures" / "hocusscript" / "catalog" / "catalog-v1.json",
        catalog_path,
    )
    catalog_raw = catalog_path.read_bytes()
    catalog = decode_catalog_snapshot(catalog_raw)
    lock = {
        "$schema": f"hocuspocus://schemas/hocus-lock/v{lock_schema_version}",
        "kind": "hocus_project_lock",
        "schemaVersion": lock_schema_version,
        "projectUid": "control-project",
        "manifestDigest": "sha256:" + hashlib.sha256(manifest_raw).hexdigest(),
        "languageVersion": lock_language_version,
        "catalog": {
            "schemaVersion": 1,
            "path": "catalog/catalog.json",
            "contentDigest": "sha256:" + hashlib.sha256(catalog_raw).hexdigest(),
            "fingerprint": catalog.fingerprint,
        },
        "modules": [_module_record(language_version=module_language_version)],
    }
    (root / "pins" / "hocus.lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_raw


def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = main(arguments)
    return code, output.getvalue(), errors.getvalue()


class HocusScriptV03ProjectCarrierTests(unittest.TestCase):
    def test_v4_project_and_lock_decode_without_enabling_consumers(self) -> None:
        self.assertEqual(PROJECT_SCHEMA_URI_V4, "hocuspocus://schemas/hocus-project/v4")
        self.assertEqual(LOCK_SCHEMA_URI_V4, "hocuspocus://schemas/hocus-lock/v4")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)

            context = ProjectContext.load(root)

            self.assertEqual(context.manifest_version, 4)
            self.assertEqual(context.language_version, "0.3")
            self.assertEqual(len(context.locked_modules), 1)
            self.assertEqual(context.locked_modules[0].language_version, "0.3")
            self.assertIsNotNone(context.lock_digest)

    def test_project_lock_versions_and_languages_are_exactly_paired(self) -> None:
        invalid_manifests = (
            _manifest(schema_version=3, language_version="0.3"),
            _manifest(schema_version=4, language_version="0.2"),
        )
        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest[:40]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_project(root, manifest=manifest)
                with self.assertRaises(ProjectError) as rejected:
                    ProjectContext.load(root, validate_lock=False)
                self.assertEqual(rejected.exception.code, "HOCUS421")

        lock_mismatches = (
            {"lock_schema_version": 3},
            {"lock_language_version": "0.2"},
            {"module_language_version": "0.2"},
        )
        for overrides in lock_mismatches:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_project(root, **overrides)
                with self.assertRaises(ProjectError) as rejected:
                    ProjectContext.load(root)
                self.assertIn(rejected.exception.code, {"HOCUS422", "HOCUS451"})

    def test_module_manifest_v1_v2_retain_their_schema_and_language_pair(self) -> None:
        def payload(schema_version: int, language_version: str) -> dict:
            return {
                "schema_version": schema_version,
                "library": {"uid": "studio-library", "version": "1.2.3"},
                "language": {"version": language_version},
                "entry_modules": ["tools/repeat.hocus"],
            }

        legacy = decode_module_manifest(payload(1, "0.2"))
        control = decode_module_manifest(payload(2, "0.3"))
        self.assertEqual((legacy.schema_version, legacy.language_version), (1, "0.2"))
        self.assertEqual((control.schema_version, control.language_version), (2, "0.3"))
        self.assertEqual(legacy.to_dict(), payload(1, "0.2"))
        self.assertEqual(control.to_dict(), payload(2, "0.3"))
        constructed_legacy = ModuleManifest(
            "studio-library",
            "1.2.3",
            "0.2",
            ("tools/repeat.hocus",),
            DIGEST_A,
        )
        self.assertEqual(constructed_legacy.schema_version, 1)
        self.assertEqual(constructed_legacy.to_dict(), payload(1, "0.2"))
        for mixed in (payload(1, "0.3"), payload(2, "0.2")):
            with self.subTest(mixed=mixed), self.assertRaises(ProjectError) as rejected:
                decode_module_manifest(mixed)
            self.assertEqual(rejected.exception.code, "HOCUS457")

    def test_v4_writer_verify_and_compile_gates_close_before_lock_access_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            lock_path = root / "pins" / "hocus.lock.json"
            sentinel = b"not-a-lock-and-must-not-change"
            lock_path.write_bytes(sentinel)
            (root / "src" / "main.hocus").write_text("hocus 0.3;", encoding="utf-8")

            with patch(
                "hocuspocus.hocusscript.project._load_lock",
                side_effect=AssertionError("closed v4 consumers must not decode the lock"),
            ):
                with self.assertRaises(ProjectError) as compiled:
                    compile_path("src/main.hocus", project_directory=root)
                self.assertEqual(compiled.exception.code, "HOCUS456")

                with self.assertRaises(ProjectError) as verified:
                    verify_project_lock(root)
                self.assertEqual(verified.exception.code, "HOCUS452")

                with self.assertRaises(ProjectError) as written:
                    update_project_lock(root, [], allow_write=True)
                self.assertEqual(written.exception.code, "HOCUS452")

            self.assertEqual(lock_path.read_bytes(), sentinel)
            self.assertFalse((root / "pins" / ".hocus.lock.json.update-lease").exists())

    def test_v4_cli_check_format_and_compile_are_observationally_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            source_path = root / "src" / "main.hocus"
            source_bytes = b"hocus 0.3; graph Main {}\n"
            source_path.write_bytes(source_bytes)
            output_path = root / "must-not-exist.json"

            for command in ("check", "format", "compile"):
                arguments = [command, "src/main.hocus", "--project", str(root)]
                if command == "compile":
                    arguments.extend(["--output", str(output_path)])
                with self.subTest(command=command):
                    code, output, errors = _run_cli(arguments)
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertIn("HOCUS456", errors)

            self.assertEqual(source_path.read_bytes(), source_bytes)
            self.assertFalse(output_path.exists())

    def test_v4_write_export_is_gated_before_handoff_read_or_destination_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root)
            destination = root / "src" / "must-not-exist.hocus"
            missing_handoff = root / "must-not-be-read.json"

            code, output, errors = _run_cli([
                "write-export",
                str(missing_handoff),
                "src/must-not-exist.hocus",
                "--project",
                str(root),
            ])

            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("HOCUS456", errors)
            self.assertNotIn("HOCUS441", errors)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
