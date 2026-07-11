from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    BundleValidationError,
    CompiledBundle,
    ProjectContext,
    ProjectError,
    compile_path,
    decode_compiled_bundle,
)
from hocuspocus.hocusscript.cli import _atomic_write, main
from test_hocusscript_parser import VALID_SOURCE


class HocusScriptProjectTests(unittest.TestCase):
    def test_native_file_compile_uses_stable_project_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "city-environment"\nsource_directories = ["hocus"]\n',
                encoding="utf-8",
            )
            source = root / "hocus" / "rocks.hocus"
            source.parent.mkdir()
            source.write_text(VALID_SOURCE, encoding="utf-8")

            result = compile_path("hocus/rocks.hocus", project_directory=root)

            self.assertTrue(result.valid)
            self.assertEqual(result.source_uri, "hocus-project://city-environment/hocus/rocks.hocus")
            self.assertEqual(result.project_uid, "city-environment")
            self.assertEqual(result.source_kind, "project_file")
            self.assertTrue(result.project_manifest_digest.startswith("sha256:"))

    def test_project_relocation_preserves_bundle_identity(self) -> None:
        bundles = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "hocus.project.toml").write_text(
                    'schema_version = 1\n[project]\nuid = "portable-city"\n',
                    encoding="utf-8",
                )
                (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
                bundles.append(CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root)))
        self.assertEqual(bundles[0].digest, bundles[1].digest)
        self.assertEqual(bundles[0].to_json(), bundles[1].to_json())

    def test_bundle_payload_cannot_be_mutated_after_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text('schema_version = 1\n[project]\nuid = "immutable"\n', encoding="utf-8")
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            bundle = CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root))
            digest = bundle.digest
            detached = bundle.payload
            detached["kind"] = "tampered"
            self.assertEqual(bundle.digest, digest)
            self.assertEqual(bundle.to_dict()["kind"], "hocus_compiled_bundle")

    def test_external_bundle_round_trip_checks_digest_and_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text('schema_version = 1\n[project]\nuid = "validated"\n', encoding="utf-8")
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            bundle = CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root))
            self.assertEqual(bundle.payload["requiredCapabilities"], ["edit_scene", "run_code"])
            self.assertEqual(bundle.payload["sourceMaps"]["entrySourceUri"], "hocus-project://validated/demo.hocus")
            decoded = decode_compiled_bundle(bundle.to_dict())
            self.assertEqual(decoded.digest, bundle.digest)
            self.assertEqual(decoded.to_json(), bundle.to_json())

    def test_external_bundle_rejects_tampered_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text('schema_version = 1\n[project]\nuid = "tamper-test"\n', encoding="utf-8")
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            payload = CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root)).to_dict()
            payload["graphSpec"]["name"] = "tampered"
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, "HOCUS505")

    def test_external_bundle_rejects_invalid_graph_even_with_recomputed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text('schema_version = 1\n[project]\nuid = "invalid-graph"\n', encoding="utf-8")
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            payload = CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root)).to_dict()
            payload["graphSpec"]["name"] = 42
            unsigned = dict(payload)
            del unsigned["bundleDigest"]
            canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            payload["bundleDigest"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, "HOCUS520")

    def test_external_bundle_rejects_nonfinite_numbers_before_digest(self) -> None:
        with self.assertRaises(BundleValidationError) as captured:
            decode_compiled_bundle({"value": float("nan")})
        self.assertEqual(captured.exception.code, "HOCUS519")

    def test_manifest_symlink_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(project_temp)
            outside = Path(outside_temp) / "manifest.toml"
            outside.write_text('schema_version = 1\n[project]\nuid = "outside"\n', encoding="utf-8")
            try:
                (root / "hocus.project.toml").symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation is unavailable on this host.")
            with self.assertRaises(ProjectError) as captured:
                ProjectContext.load(root)
            self.assertEqual(captured.exception.code, "HOCUS419")

    def test_manifest_free_check_is_preview_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            result = compile_path("demo.hocus", project_directory=root)
            bundle = CompiledBundle.from_result(result)
            self.assertEqual(result.source_uri, "hocus-workspace:///demo.hocus")
            self.assertFalse(bundle.payload["portable"])

    def test_source_must_stay_in_project_and_source_directories(self) -> None:
        with tempfile.TemporaryDirectory() as project_temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(project_temp)
            outside = Path(outside_temp) / "escape.hocus"
            outside.write_text(VALID_SOURCE, encoding="utf-8")
            with self.assertRaises(ProjectError) as captured:
                compile_path(outside, project_directory=root)
            self.assertEqual(captured.exception.code, "HOCUS411")

    def test_invalid_manifest_uid_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "Not Portable"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ProjectError) as captured:
                ProjectContext.load(root)
            self.assertEqual(captured.exception.code, "HOCUS406")

    def test_invalid_utf8_source_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "invalid.hocus").write_bytes(b"\xff")
            with self.assertRaises(ProjectError) as captured:
                compile_path("invalid.hocus", project_directory=root)
            self.assertEqual(captured.exception.code, "HOCUS416")

    def test_cli_check_and_compile_use_native_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "cli-project"\n',
                encoding="utf-8",
            )
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                check_code = main(["check", "demo.hocus", "--project", str(root), "--json"])
            self.assertEqual(check_code, 0, errors.getvalue())
            self.assertEqual(json.loads(output.getvalue())["sourceKind"], "project_file")

            output = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                compile_code = main(["compile", "demo.hocus", "--project", str(root)])
            self.assertEqual(compile_code, 0, errors.getvalue())
            bundle_payload = json.loads(output.getvalue())
            self.assertEqual(bundle_payload["kind"], "hocus_compiled_bundle")
            schema = json.loads((ROOT / "docs" / "schemas" / "compiled-bundle-v0.1.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(schema["$id"], bundle_payload["$schema"])
            self.assertTrue(set(schema["required"]).issubset(bundle_payload))

    def test_cli_format_write_updates_the_native_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "demo.hocus"
            source.write_text('hocus 0.1; graph demo { target "/obj/geo1"; }', encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main(["format", "demo.hocus", "--project", str(root), "--write"])
            self.assertEqual(code, 0)
            self.assertIn("graph demo {\n", source.read_text(encoding="utf-8"))

    def test_atomic_write_rejects_a_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "demo.hocus"
            source.write_text("before", encoding="utf-8")
            expected = "sha256:" + hashlib.sha256(b"before").hexdigest()
            source.write_text("artist change", encoding="utf-8")
            with self.assertRaises(ProjectError) as captured:
                _atomic_write(source, "formatted", expected_digest=expected)
            self.assertEqual(captured.exception.code, "HOCUS418")
            self.assertEqual(source.read_text(encoding="utf-8"), "artist change")


if __name__ == "__main__":
    unittest.main()
