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

from hocuspocus.hocusscript.module_lock_plan_result import _prospective_lock_payload
from test_hocusscript_module_lock_plan import _fixture, _plan

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional developer dependency
    Draft202012Validator = None


SCHEMA_PATH = ROOT / "docs" / "schemas" / "module-lock-plan-v1.schema.json"


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class ModuleLockPlanSchemaTests(unittest.TestCase):
    def _validator(self) -> Draft202012Validator:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["$id"], "hocuspocus://schemas/module-lock-plan/v1")
        return Draft202012Validator(schema)

    def _real_payload(self) -> tuple[dict, object, tuple[Path, Path, Path]]:
        self.temporary = tempfile.TemporaryDirectory()
        roots = _fixture(Path(self.temporary.name))
        result = _plan(*roots)
        return result.to_dict(), result, roots

    def tearDown(self) -> None:
        temporary = getattr(self, "temporary", None)
        if temporary is not None:
            temporary.cleanup()
            del self.temporary

    def test_real_result_validates_and_digests_are_exact(self) -> None:
        validator = self._validator()
        payload, result, roots = self._real_payload()
        validator.validate(payload)

        unsigned = dict(payload)
        declared_plan = unsigned.pop("planDigest")
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(
            declared_plan,
            "sha256:" + hashlib.sha256(b"hocus-module-lock-plan-v1\0" + canonical).hexdigest(),
        )

        prospective = _prospective_lock_payload(result)
        lock_canonical = json.dumps(
            prospective,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(
            payload["prospectiveLockDigest"],
            "sha256:" + hashlib.sha256(lock_canonical).hexdigest(),
        )
        rendered = json.dumps(payload, sort_keys=True)
        for root in roots:
            self.assertNotIn(str(root), rendered)

    def test_schema_rejects_host_paths_bad_uris_provenance_and_diff_shapes(self) -> None:
        validator = self._validator()
        payload, _, roots = self._real_payload()
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

        mutate("top-level native path", lambda item: item.__setitem__("nativeProjectRoot", str(roots[0])))
        mutate("absolute catalog", lambda item: item.__setitem__("catalogPath", "C:/secret/catalog.json"))
        mutate("traversal catalog", lambda item: item.__setitem__("catalogPath", "../catalog.json"))
        mutate(
            "control character source path",
            lambda item: item["modules"][0].__setitem__("sourcePath", "bad\tname.hocus"),
        )
        mutate("wrong kind", lambda item: item.__setitem__("kind", "hocus-module-lock-plan-v2"))
        mutate("uppercase digest", lambda item: item.__setitem__("planDigest", "sha256:" + "A" * 64))
        mutate(
            "external entry uri",
            lambda item: item["entries"][0].__setitem__(
                "entryUri", "hocus-module://alpha-library/main.hocus"
            ),
        )
        mutate(
            "encoded unreserved uri",
            lambda item: item["entries"][0].__setitem__(
                "entryUri", "hocus-project://external-root-project/src/%6Dain.hocus"
            ),
        )
        mutate(
            "lowercase escape uri",
            lambda item: item["entries"][0].__setitem__(
                "entryUri", "hocus-project://external-root-project/src/%c3%a9.hocus"
            ),
        )
        mutate(
            "local external provenance",
            lambda item: item["modules"][local_index].__setitem__("libraryUid", "alpha-library"),
        )
        mutate(
            "external project provenance",
            lambda item: item["modules"][external_index].__setitem__("projectUid", "external-root-project"),
        )
        mutate(
            "external missing manifest pin",
            lambda item: item["modules"][external_index].__setitem__("moduleManifestDigest", None),
        )
        mutate(
            "host dependency",
            lambda item: item["modules"][external_index].__setitem__(
                "dependencies", ["C:/secret/module.hocus"]
            ),
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
