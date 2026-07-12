from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from test_hocusscript_external_roots import (
    _digest,
    _inspect,
    _library_manifest,
    _write_library,
    _write_project,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional developer dependency
    Draft202012Validator = None


SCHEMA_PATH = ROOT / "docs" / "schemas" / "external-module-roots-inspection-v1.schema.json"


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class ExternalModuleRootsInspectionSchemaTests(unittest.TestCase):
    def _validator(self) -> Draft202012Validator:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            schema["$id"],
            "hocuspocus://schemas/external-module-roots-inspection/v1",
        )
        return Draft202012Validator(schema)

    def test_real_portable_result_validates_and_digest_is_exact(self) -> None:
        validator = self._validator()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "approved-library"
            raw = _library_manifest(
                "studio-library", "1.2.3-beta.1+build.7",
                ("materials/noise.hocus", "tools/main.hocus"),
            )
            _write_library(library, raw)
            _write_project(project, ((
                "studio", "studio-library", "1.2.3-beta.1+build.7", _digest(raw),
            ),))
            result = _inspect(project, {"studio": library})
            payload = result.to_dict()
            validator.validate(payload)
            unsigned = dict(payload)
            declared = unsigned.pop("inspectionDigest")
            canonical = json.dumps(
                unsigned, ensure_ascii=False, separators=(",", ":"),
                sort_keys=True, allow_nan=False,
            ).encode("utf-8")
            expected = "sha256:" + hashlib.sha256(
                b"hocus-external-module-roots-inspection-v1\0" + canonical
            ).hexdigest()
            self.assertEqual(declared, expected)
            rendered = json.dumps(payload, sort_keys=True)
            self.assertNotIn(str(project), rendered)
            self.assertNotIn(str(library), rendered)

    def test_schema_rejects_host_paths_bad_pins_and_nonportable_entries(self) -> None:
        validator = self._validator()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, library = base / "project", base / "library"
            raw = _library_manifest("library", "1.0.0")
            _write_library(library, raw)
            _write_project(project, (("studio", "library", "1.0.0", _digest(raw)),))
            payload = _inspect(project, {"studio": library}).to_dict()

        mutations = []
        extra = copy.deepcopy(payload)
        extra["libraries"][0]["nativeRoot"] = "C:/secret/library"
        mutations.append(extra)
        bad_digest = copy.deepcopy(payload)
        bad_digest["catalogFingerprint"] = "sha256:" + "A" * 64
        mutations.append(bad_digest)
        bad_alias = copy.deepcopy(payload)
        bad_alias["libraries"][0]["alias"] = "Studio_Root"
        mutations.append(bad_alias)
        absolute = copy.deepcopy(payload)
        absolute["libraries"][0]["entryModules"] = ["/absolute/main.hocus"]
        mutations.append(absolute)
        traversal = copy.deepcopy(payload)
        traversal["libraries"][0]["entryModules"] = ["../escape.hocus"]
        mutations.append(traversal)
        device = copy.deepcopy(payload)
        device["libraries"][0]["entryModules"] = ["CON.hocus"]
        mutations.append(device)
        unknown = copy.deepcopy(payload)
        unknown["kind"] = "hocus-external-roots-v2"
        mutations.append(unknown)
        empty = copy.deepcopy(payload)
        empty["libraries"] = []
        mutations.append(empty)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertTrue(list(validator.iter_errors(mutation)))


if __name__ == "__main__":
    unittest.main()
