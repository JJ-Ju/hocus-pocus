from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.hocusscript.project import ProjectError, verify_project_lock
from test_hocusscript_mixed_lock_update import _publish
from test_hocusscript_module_lock_plan import _fixture

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional developer dependency
    Draft202012Validator = None


SCHEMA_PATH = ROOT / "docs/schemas/mixed-module-lock-update-v1.schema.json"


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class MixedModuleLockUpdateSchemaTests(unittest.TestCase):
    def _validator(self) -> Draft202012Validator:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            schema["$id"],
            "hocuspocus://schemas/mixed-module-lock-update/v1",
        )
        return Draft202012Validator(schema)

    def _published(self):
        self.temporary = tempfile.TemporaryDirectory()
        roots = _fixture(Path(self.temporary.name))
        result = _publish(*roots)
        return roots, result

    def tearDown(self) -> None:
        temporary = getattr(self, "temporary", None)
        if temporary is not None:
            temporary.cleanup()
            del self.temporary

    def test_real_changed_and_unchanged_receipts_validate_and_are_portable(self) -> None:
        validator = self._validator()
        roots, changed = self._published()
        changed_payload = changed.to_dict()
        validator.validate(changed_payload)
        self.assertEqual(changed_payload["lockDigest"], verify_project_lock(roots[0]).lock_digest)
        self.assertTrue(changed_payload["changed"])
        self.assertTrue(changed_payload["diff"]["available"])

        unchanged = _publish(*roots, expected=changed.lock_digest)
        unchanged_payload = unchanged.to_dict()
        validator.validate(unchanged_payload)
        self.assertFalse(unchanged_payload["changed"])
        self.assertEqual(unchanged_payload["diff"], {
            "available": True,
            "addedUris": [],
            "removedUris": [],
            "changedUris": [],
        })
        rendered = json.dumps(changed_payload, sort_keys=True) + repr(changed)
        for root in roots:
            self.assertNotIn(str(root), rendered)

        with self.assertRaises(ProjectError):
            replace(changed, added_uris=())

    def test_schema_rejects_host_paths_bad_uris_provenance_and_diff_mutations(self) -> None:
        validator = self._validator()
        roots, result = self._published()
        payload = result.to_dict()
        local_index = next(
            index for index, item in enumerate(payload["modules"])
            if item["externalAlias"] is None
        )
        external_index = next(
            index for index, item in enumerate(payload["modules"])
            if item["externalAlias"] is not None
        )
        mutations: list[tuple[str, dict]] = []

        def mutate(name: str, callback) -> None:
            candidate = copy.deepcopy(payload)
            callback(candidate)
            mutations.append((name, candidate))

        mutate(
            "native root field",
            lambda item: item.__setitem__("nativeProjectRoot", str(roots[0])),
        )
        mutate(
            "absolute catalog path",
            lambda item: item.__setitem__("catalogPath", "C:/secret/catalog.json"),
        )
        mutate(
            "catalog traversal",
            lambda item: item.__setitem__("catalogPath", "../catalog.json"),
        )
        mutate(
            "source host path",
            lambda item: item["modules"][local_index].__setitem__(
                "sourcePath", "C:/secret/local.hocus"
            ),
        )
        mutate(
            "unknown kind",
            lambda item: item.__setitem__("kind", "hocus-mixed-module-lock-update-v2"),
        )
        mutate(
            "uppercase digest",
            lambda item: item.__setitem__("lockDigest", "sha256:" + "A" * 64),
        )
        mutate(
            "external entry uri",
            lambda item: item["entries"][0].__setitem__(
                "entryUri", "hocus-module://alpha-library/main.hocus"
            ),
        )
        mutate(
            "encoded unreserved entry uri",
            lambda item: item["entries"][0].__setitem__(
                "entryUri", "hocus-project://external-root-project/src/%6Dain.hocus"
            ),
        )
        mutate(
            "local library provenance",
            lambda item: item["modules"][local_index].__setitem__(
                "libraryUid", "alpha-library"
            ),
        )
        mutate(
            "external project provenance",
            lambda item: item["modules"][external_index].__setitem__(
                "projectUid", "external-root-project"
            ),
        )
        mutate(
            "external missing manifest pin",
            lambda item: item["modules"][external_index].__setitem__(
                "moduleManifestDigest", None
            ),
        )
        mutate(
            "host dependency",
            lambda item: item["modules"][external_index].__setitem__(
                "dependencies", ["C:/secret/module.hocus"]
            ),
        )
        mutate(
            "diff unavailable",
            lambda item: item["diff"].__setitem__("available", False),
        )
        mutate(
            "duplicate diff uri",
            lambda item: item["diff"].__setitem__(
                "addedUris", [item["diff"]["addedUris"][0]] * 2
            ),
        )
        mutate(
            "unchanged with additions",
            lambda item: item.__setitem__("changed", False),
        )
        mutate(
            "changed with empty diff",
            lambda item: (
                item["diff"].__setitem__("addedUris", []),
                item["diff"].__setitem__("removedUris", []),
                item["diff"].__setitem__("changedUris", []),
            ),
        )

        for name, candidate in mutations:
            with self.subTest(name=name):
                self.assertTrue(list(validator.iter_errors(candidate)), name)


if __name__ == "__main__":
    unittest.main()
