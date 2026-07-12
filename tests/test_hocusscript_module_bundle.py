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

from hocuspocus.hocusscript.bundle import (
    BundleValidationError, _bundle_from_module_semantic, decode_compiled_bundle,
)
from hocuspocus.hocusscript.document_lowering import (
    DocumentLoweringError, lower_bundle_to_document,
)
from hocuspocus.hocusscript.module_semantic import (
    compile_project_module_bundle, compile_project_module_semantic,
)
from test_hocusscript_resolver import _valid_project


def _digest(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rehash(payload: dict) -> None:
    unsigned = copy.deepcopy(payload)
    unsigned.pop("bundleDigest", None)
    payload["bundleDigest"] = _digest(unsigned)


def _prepare_project(root: Path) -> None:
    _valid_project(root)
    (root / "src/main.hocus").write_bytes(
        b'hocus 0.2; import { Root } from "root.hocus"; graph Main { '
        b'target "/obj/geo1"; category Sop; node n: "sop::null" {} }'
    )


def _semantic_project(root: Path):
    _prepare_project(root)
    return compile_project_module_semantic(root, "src/main.hocus")


def _schema_validator():
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return None
    schema_names = (
        "resolved-module-set-v1.schema.json", "graph-spec-v0.3.schema.json",
        "expansion-map-v1.schema.json", "compiled-bundle-v0.3.schema.json",
    )
    schemas = [
        json.loads((ROOT / "docs/schemas" / name).read_text("utf-8"))
        for name in schema_names
    ]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    Draft202012Validator.check_schema(schemas[-1])
    return Draft202012Validator(schemas[-1], registry=registry)


class ModuleSemanticBundleTests(unittest.TestCase):
    def test_real_factory_is_deterministic_portable_and_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_root, second_root = Path(first_dir), Path(second_dir)
            _prepare_project(first_root)
            _prepare_project(second_root)
            one = compile_project_module_bundle(first_root, "src/main.hocus")
            two = compile_project_module_bundle(second_root, "src/main.hocus")
            self.assertEqual(one.to_dict(), two.to_dict())
            self.assertEqual(one.digest, two.digest)
            payload = one.to_dict()
            self.assertEqual(payload["bundleVersion"], "0.3")
            expected_dependencies = [
                {"uri": item["uri"], "digest": item["sourceDigest"], "kind": "module"}
                for item in payload["resolvedModuleSet"]["modules"]
            ]
            self.assertEqual(payload["dependencies"], expected_dependencies)
            self.assertEqual(
                payload["sourceMaps"]["expansionMapDigest"],
                _digest(payload["graphSpec"]["expansionMap"]),
            )
            self.assertEqual(
                payload["requiredCapabilities"],
                payload["semanticResolution"]["requiredCapabilities"],
            )
            self.assertEqual(decode_compiled_bundle(payload).to_dict(), payload)
            validator = _schema_validator()
            if validator is not None:
                validator.validate(payload)

    def test_factory_rejects_untrusted_or_invalid_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = _semantic_project(Path(temporary))
            with self.assertRaises(TypeError):
                _bundle_from_module_semantic(result.to_dict())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            (root / "src/main.hocus").write_bytes(
                b'hocus 0.2; graph Main { target "/obj/geo1"; category Sop; '
                b'node n: not_in_catalog {} }'
            )
            with self.assertRaises(ValueError):
                compile_project_module_bundle(root, "src/main.hocus")

    def test_document_lowering_remains_explicitly_disabled_for_bundle_v03(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            bundle = compile_project_module_bundle(root, "src/main.hocus")
        with self.assertRaises(DocumentLoweringError) as blocked:
            lower_bundle_to_document(bundle, {})
        self.assertEqual(blocked.exception.code, "HOCUS700")

    def test_decoder_rejects_cross_contract_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            payload = compile_project_module_bundle(root, "src/main.hocus").to_dict()
        cases: dict[str, dict] = {}

        catalog = copy.deepcopy(payload)
        catalog["catalogConstraints"]["fingerprint"] = _digest("other catalog")
        cases["catalog"] = catalog

        graph = copy.deepcopy(payload)
        graph["graphSpec"]["nodes"][0]["symbol"] = "changed"
        cases["graph"] = graph

        resolved = copy.deepcopy(payload)
        resolved["resolvedModuleSet"]["modules"][0]["sourceDigest"] = _digest("other source")
        cases["resolved-set"] = resolved

        selection = copy.deepcopy(payload)
        selection["semanticResolution"]["operatorSelections"][0]["nodeSymbol"] = "changed"
        cases["selection"] = selection

        for name, candidate in cases.items():
            with self.subTest(name=name):
                _rehash(candidate)
                with self.assertRaises(BundleValidationError):
                    decode_compiled_bundle(candidate)

    def test_diagnostic_provenance_uses_exact_or_longest_enclosing_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            payload = compile_project_module_bundle(root, "src/main.hocus").to_dict()
        mapping = next(
            item for item in payload["graphSpec"]["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0"
        )
        diagnostic = {
            "severity": "info", "code": "HOCUS699", "phase": "semantic",
            "message": "Provenance test.", "jsonPointer": "/nodes/0/typeName",
            "originId": mapping["originId"], "stackId": mapping["stackId"],
            "related": [], "notes": [], "fixes": [], "details": {},
            "expansionStack": [], "entityUid": None, "houdiniPath": None,
            "sourceUri": mapping["primarySpan"]["sourceUri"],
            "span": {
                "start": mapping["primarySpan"]["start"],
                "end": mapping["primarySpan"]["end"],
            },
        }
        payload["semanticResolution"]["diagnostics"].append(diagnostic)
        _rehash(payload)
        decode_compiled_bundle(payload)
        validator = _schema_validator()
        if validator is not None:
            validator.validate(payload)

        for field, value in (
            ("originId", None), ("stackId", _digest("forged stack")),
        ):
            candidate = copy.deepcopy(payload)
            candidate["semanticResolution"]["diagnostics"][0][field] = value
            _rehash(candidate)
            with self.subTest(field=field), self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(candidate)
            self.assertEqual(captured.exception.code, "HOCUS521")

        missing = copy.deepcopy(payload)
        del missing["semanticResolution"]["diagnostics"][0]["originId"]
        _rehash(missing)
        with self.assertRaises(BundleValidationError):
            decode_compiled_bundle(missing)

    def test_diagnostic_locations_reject_host_and_live_or_duplicated_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            payload = compile_project_module_bundle(root, "src/main.hocus").to_dict()
        mapping = next(
            item for item in payload["graphSpec"]["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0"
        )
        primary = mapping["primarySpan"]
        diagnostic = {
            "severity": "info", "code": "HOCUS699", "phase": "semantic",
            "message": "Portable source test.", "jsonPointer": "/nodes/0/typeName",
            "originId": mapping["originId"], "stackId": mapping["stackId"],
            "sourceUri": primary["sourceUri"],
            "span": {"start": primary["start"], "end": primary["end"]},
            "related": [], "notes": [], "fixes": [], "details": {},
            "expansionStack": [], "entityUid": None, "houdiniPath": None,
        }
        hostile = {
            "host-source": ("sourceUri", "C:/studio/secret.hocus"),
            "empty-span": ("span", {}),
            "out-of-origin": ("span", {
                "start": primary["start"],
                "end": {**primary["end"], "offset": primary["end"]["offset"] + 1},
            }),
            "wrong-position": ("span", {
                "start": {**primary["start"], "column": primary["start"]["column"] + 1},
                "end": primary["end"],
            }),
            "houdini-path": ("houdiniPath", "/obj/secret"),
            "entity": ("entityUid", "node-uid"),
            "related": ("related", [{"role": "definition"}]),
            "frames": ("expansionStack", [{"moduleUri": "host"}]),
        }
        for name, (field, value) in hostile.items():
            candidate = copy.deepcopy(payload)
            forged = copy.deepcopy(diagnostic)
            forged[field] = value
            candidate["semanticResolution"]["diagnostics"].append(forged)
            _rehash(candidate)
            with self.subTest(name=name), self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(candidate)
            self.assertEqual(captured.exception.code, "HOCUS521")

        unlocated = copy.deepcopy(payload)
        unlocated["semanticResolution"]["diagnostics"].append({
            **{key: value for key, value in diagnostic.items() if key not in {"sourceUri", "span"}},
            "jsonPointer": None, "originId": None, "stackId": None,
        })
        _rehash(unlocated)
        decode_compiled_bundle(unlocated)
        leaked = copy.deepcopy(unlocated)
        leaked["semanticResolution"]["diagnostics"][0]["sourceUri"] = primary["sourceUri"]
        leaked["semanticResolution"]["diagnostics"][0]["span"] = {
            "start": primary["start"], "end": primary["end"],
        }
        _rehash(leaked)
        with self.assertRaises(BundleValidationError):
            decode_compiled_bundle(leaked)


if __name__ == "__main__":
    unittest.main()
