from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import ProjectError, decode_module_manifest


VALID = '''schema_version = 1
entry_modules = ["geometry/build.hocus", "materials/surface.hocus"]
[library]
uid = "studio-library"
version = "1.2.3-beta.1+build.5"
[language]
version = "0.2"
'''


class HocusScriptModuleManifestTests(unittest.TestCase):
    def test_manifest_decodes_deterministically_without_resolving_paths(self) -> None:
        first = decode_module_manifest(VALID)
        second = decode_module_manifest(VALID.encode("utf-8"))
        self.assertEqual(first, second)
        self.assertEqual(first.library_uid, "studio-library")
        self.assertEqual(first.language_version, "0.2")
        self.assertEqual(first.entry_modules, ("geometry/build.hocus", "materials/surface.hocus"))
        self.assertTrue(first.manifest_digest.startswith("sha256:"))

    def test_unknown_fields_paths_duplicates_order_and_versions_are_rejected(self) -> None:
        payload = decode_module_manifest(VALID).to_dict()
        invalid = []
        unknown = json.loads(json.dumps(payload)); unknown["path"] = "C:/library"; invalid.append(unknown)
        traversal = json.loads(json.dumps(payload)); traversal["entry_modules"] = ["../escape.hocus"]; invalid.append(traversal)
        absolute = json.loads(json.dumps(payload)); absolute["entry_modules"] = ["/escape.hocus"]; invalid.append(absolute)
        duplicate = json.loads(json.dumps(payload)); duplicate["entry_modules"] = ["A.hocus", "a.hocus"]; invalid.append(duplicate)
        unsorted = json.loads(json.dumps(payload)); unsorted["entry_modules"] = ["z.hocus", "a.hocus"]; invalid.append(unsorted)
        old_language = json.loads(json.dumps(payload)); old_language["language"]["version"] = "0.1"; invalid.append(old_language)
        bad_version = json.loads(json.dumps(payload)); bad_version["library"]["version"] = "latest"; invalid.append(bad_version)
        numeric_prerelease = json.loads(json.dumps(payload)); numeric_prerelease["library"]["version"] = "1.0.0-01"; invalid.append(numeric_prerelease)
        empty_prerelease = json.loads(json.dumps(payload)); empty_prerelease["library"]["version"] = "1.0.0-a..b"; invalid.append(empty_prerelease)
        reserved = json.loads(json.dumps(payload)); reserved["entry_modules"] = ["CON.hocus"]; invalid.append(reserved)
        trailing_dot = json.loads(json.dumps(payload)); trailing_dot["entry_modules"] = ["folder./a.hocus"]; invalid.append(trailing_dot)
        empty = json.loads(json.dumps(payload)); empty["entry_modules"] = []; invalid.append(empty)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ProjectError) as rejected:
                decode_module_manifest(item)
            self.assertEqual(rejected.exception.code, "HOCUS457")
        with self.assertRaises(TypeError):
            decode_module_manifest(10_000_000)  # type: ignore[arg-type]

    def test_schema_matches_runtime_contract(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        schema = json.loads(
            (ROOT / "docs" / "schemas" / "hocus-module-v1.schema.json").read_text("utf-8")
        )
        Draft202012Validator.check_schema(schema)
        payload = decode_module_manifest(VALID).to_dict()
        Draft202012Validator(schema).validate(payload)
        payload["entry_modules"] = ["../escape.hocus"]
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(payload)))


if __name__ == "__main__":
    unittest.main()
