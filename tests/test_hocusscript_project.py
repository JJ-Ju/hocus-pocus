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
from hocuspocus.hocusscript.project import MAX_MANIFEST_BYTES
from test_hocusscript_parser import VALID_SOURCE


class HocusScriptProjectTests(unittest.TestCase):
    @staticmethod
    def _write_lock(root: Path, manifest_bytes: bytes, *, uid: str = "locked-project", **overrides) -> dict:
        payload = {
            "$schema": "hocuspocus://schemas/hocus-lock/v1",
            "kind": "hocus_project_lock",
            "schemaVersion": 1,
            "projectUid": uid,
            "manifestDigest": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
            "languageVersion": "0.1",
            "catalog": None,
            "modules": [],
        }
        payload.update(overrides)
        (root / "hocus.lock.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    @staticmethod
    def _rehash_bundle(payload: dict) -> None:
        unsigned = dict(payload)
        unsigned.pop("bundleDigest", None)
        canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        payload["bundleDigest"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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

    def test_same_uid_with_different_manifest_content_has_distinct_bundle_identity(self) -> None:
        bundles = []
        for name in ("First", "Second"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "hocus.project.toml").write_text(
                    f'schema_version = 1\n[project]\nuid = "shared-uid"\nname = "{name}"\n',
                    encoding="utf-8",
                )
                (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
                bundles.append(CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root)))
        self.assertNotEqual(bundles[0].digest, bundles[1].digest)
        self.assertNotEqual(bundles[0].payload["projectManifestDigest"], bundles[1].payload["projectManifestDigest"])

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
            self._rehash_bundle(payload)
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, "HOCUS520")

    def test_external_bundle_rejects_invalid_code_language_and_offset_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_text('schema_version = 1\n[project]\nuid = "code-map"\n', encoding="utf-8")
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            original = CompiledBundle.from_result(compile_path("demo.hocus", project_directory=root)).to_dict()

            invalid_language = json.loads(json.dumps(original))
            invalid_language["graphSpec"]["nodes"][1]["parms"][0]["value"]["language"] = "javascript"
            self._rehash_bundle(invalid_language)
            with self.assertRaises(BundleValidationError) as language_error:
                decode_compiled_bundle(invalid_language)
            self.assertEqual(language_error.exception.code, "HOCUS520")

            invalid_map = json.loads(json.dumps(original))
            code = invalid_map["graphSpec"]["nodes"][1]["parms"][0]["value"]
            code["offsetMap"]["checkpoints"][1]["sourceOffset"] = code["offsetMap"]["checkpoints"][0]["sourceOffset"]
            self._rehash_bundle(invalid_map)
            with self.assertRaises(BundleValidationError) as map_error:
                decode_compiled_bundle(invalid_map)
            self.assertEqual(map_error.exception.code, "HOCUS520")

            foreign_span = json.loads(json.dumps(original))
            foreign_span["graphSpec"]["span"]["sourceUri"] = "hocus-project://other/foreign.hocus"
            self._rehash_bundle(foreign_span)
            with self.assertRaises(BundleValidationError) as span_error:
                decode_compiled_bundle(foreign_span)
            self.assertEqual(span_error.exception.code, "HOCUS520")

            inverted_span = json.loads(json.dumps(original))
            inverted_span["graphSpec"]["span"]["end"]["offset"] = 0
            self._rehash_bundle(inverted_span)
            with self.assertRaises(BundleValidationError) as inverted_error:
                decode_compiled_bundle(inverted_span)
            self.assertEqual(inverted_error.exception.code, "HOCUS520")

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

    def test_manifest_v1_defaults_and_required_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n[language]\nversion = "0.1"\n[lock]\npolicy = "required"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            with self.assertRaises(ProjectError) as missing:
                ProjectContext.load(root)
            self.assertEqual(missing.exception.code, "HOCUS426")
            self._write_lock(root, manifest)
            context = ProjectContext.load(root)
            self.assertEqual(context.language_version, "0.1")
            self.assertEqual(context.lock_policy, "required")
            self.assertTrue(context.lock_digest.startswith("sha256:"))

    def test_lock_digest_is_canonical_across_json_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            payload = self._write_lock(root, manifest)
            pretty_digest = ProjectContext.load(root).lock_digest
            (root / "hocus.lock.json").write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
            compact_digest = ProjectContext.load(root).lock_digest
            self.assertEqual(pretty_digest, compact_digest)

    def test_stale_lock_blocks_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")
            self._write_lock(root, manifest, manifestDigest="sha256:" + ("0" * 64))
            with self.assertRaises(ProjectError) as captured:
                compile_path("demo.hocus", project_directory=root)
            self.assertEqual(captured.exception.code, "HOCUS424")

            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                format_code = main(["format", "demo.hocus", "--project", str(root)])
            self.assertEqual(format_code, 0, errors.getvalue())
            self.assertIn("graph rocks", output.getvalue())

            preview_result = compile_path("demo.hocus", project_directory=root, validate_lock=False)
            preview_bundle = CompiledBundle.from_result(preview_result)
            self.assertFalse(preview_bundle.payload["portable"])
            self.assertEqual(preview_bundle.payload["entrySource"]["kind"], "workspace_file")
            self.assertTrue(preview_bundle.payload["entrySource"]["uri"].startswith("hocus-workspace:///"))

    def test_lock_rejects_duplicate_keys_and_reserved_resolution_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
            duplicate = (
                '{"$schema":"hocuspocus://schemas/hocus-lock/v1","kind":"hocus_project_lock",'
                '"schemaVersion":1,"projectUid":"locked-project","projectUid":"duplicate",'
                f'"manifestDigest":"{digest}","languageVersion":"0.1","catalog":null,"modules":[]}}'
            )
            (root / "hocus.lock.json").write_text(duplicate, encoding="utf-8")
            with self.assertRaises(ProjectError) as captured:
                ProjectContext.load(root)
            self.assertEqual(captured.exception.code, "HOCUS422")
            self._write_lock(root, manifest, catalog={"fingerprint": "sha256:" + ("0" * 64)})
            with self.assertRaises(ProjectError) as reserved:
                ProjectContext.load(root)
            self.assertEqual(reserved.exception.code, "HOCUS425")

    def test_lock_without_manifest_and_lock_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project_temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(project_temp)
            outside = Path(outside_temp) / "hocus.lock.json"
            outside.write_text("{}", encoding="utf-8")
            try:
                (root / "hocus.lock.json").symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation is unavailable on this host.")
            with self.assertRaises(ProjectError) as no_manifest:
                ProjectContext.load(root)
            self.assertEqual(no_manifest.exception.code, "HOCUS423")
            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            with self.assertRaises(ProjectError) as escaped:
                ProjectContext.load(root)
            self.assertEqual(escaped.exception.code, "HOCUS419")

    def test_manifest_rejects_unknown_and_nonportable_source_directories(self) -> None:
        invalid_manifests = [
            'schema_version = 1\nunknown = true\n[project]\nuid = "portable"\n',
            'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["../escape"]\n',
            'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["C:/escape"]\n',
            'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["//server/share"]\n',
            "schema_version = 1\n[project]\nuid = \"portable\"\nsource_directories = ['\\\\?\\C:\\escape']\n",
            'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["Assets", "assets"]\n',
            'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["missing"]\n',
        ]
        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "hocus.project.toml").write_text(manifest, encoding="utf-8")
                with self.assertRaises(ProjectError):
                    ProjectContext.load(root)

    def test_manifest_and_lock_wrong_types_return_typed_errors(self) -> None:
        malformed_manifests = [
            'schema_version = true\n[project]\nuid = "typed"\n',
            'schema_version = 1\n[project]\nuid = "typed"\n[language]\nversion = ["0.1"]\n',
            'schema_version = 1\n[project]\nuid = "typed"\n[lock]\npolicy = ["required"]\n',
        ]
        for manifest in malformed_manifests:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "hocus.project.toml").write_text(manifest, encoding="utf-8")
                with self.assertRaises(ProjectError):
                    ProjectContext.load(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = b'schema_version = 1\n[project]\nuid = "typed"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            self._write_lock(root, manifest, uid="typed", schemaVersion=True)
            with self.assertRaises(ProjectError) as schema_error:
                ProjectContext.load(root)
            self.assertEqual(schema_error.exception.code, "HOCUS422")
            self._write_lock(root, manifest, uid="typed", languageVersion=["0.1"])
            with self.assertRaises(ProjectError) as language_error:
                ProjectContext.load(root)
            self.assertEqual(language_error.exception.code, "HOCUS422")

    def test_configured_source_directory_symlink_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(project_temp)
            outside = Path(outside_temp)
            try:
                (root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Directory symlink creation is unavailable on this host.")
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["linked"]\n',
                encoding="utf-8",
            )
            with self.assertRaises(ProjectError) as captured:
                ProjectContext.load(root)
            self.assertEqual(captured.exception.code, "HOCUS409")

    def test_portable_source_directory_schema_matches_runtime_space_and_dot_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "my assets").mkdir()
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "portable"\nsource_directories = ["my assets"]\n',
                encoding="utf-8",
            )
            context = ProjectContext.load(root)
            self.assertEqual(context.source_directories, ((root / "my assets").resolve(),))

    def test_manifest_and_lock_size_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "hocus.project.toml").write_bytes(b"x" * (MAX_MANIFEST_BYTES + 1))
            with self.assertRaises(ProjectError) as manifest_error:
                ProjectContext.load(root)
            self.assertEqual(manifest_error.exception.code, "HOCUS403")

            manifest = b'schema_version = 1\n[project]\nuid = "locked-project"\n'
            (root / "hocus.project.toml").write_bytes(manifest)
            (root / "hocus.lock.json").write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
            with self.assertRaises(ProjectError) as lock_error:
                ProjectContext.load(root)
            self.assertEqual(lock_error.exception.code, "HOCUS410")

    def test_project_and_lock_schemas_are_valid_draft_2020_12(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        for name in ("hocus-project-v1.schema.json", "hocus-lock-v1.schema.json"):
            schema = json.loads((ROOT / "docs" / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].startswith("hocuspocus://schemas/"))
            if Draft202012Validator is not None:
                Draft202012Validator.check_schema(schema)

        if Draft202012Validator is not None:
            project_schema = json.loads((ROOT / "docs" / "schemas" / "hocus-project-v1.schema.json").read_text(encoding="utf-8"))
            validator = Draft202012Validator(project_schema)
            validator.validate({"schema_version": 1, "project": {"uid": "valid", "source_directories": ["."]}})
            validator.validate({"schema_version": 1, "project": {"uid": "valid", "source_directories": ["my assets"]}})
            for source_directory in ("../escape", "a/./b", "C:/escape", "//server/share", "back\\slash", " spaced "):
                errors = list(
                    validator.iter_errors(
                        {"schema_version": 1, "project": {"uid": "valid", "source_directories": [source_directory]}}
                    )
                )
                self.assertTrue(errors, source_directory)

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

    def test_oversized_native_source_is_rejected_before_decode(self) -> None:
        from hocuspocus.hocusscript.compiler import MAX_SOURCE_BYTES

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "large.hocus").write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
            with self.assertRaises(ProjectError) as captured:
                compile_path("large.hocus", project_directory=root)
            self.assertEqual(captured.exception.code, "HOCUS001")

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
