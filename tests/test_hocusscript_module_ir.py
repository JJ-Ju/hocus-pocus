from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

import hocuspocus.hocusscript.bundle as bundle_module
from hocuspocus.hocusscript import (
    BundleValidationError,
    decode_compiled_bundle,
    graph_spec_from_dict,
    compile_source,
)
from test_hocusscript_document_lowering import _bundle


def _digest(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _transitive_digest(module: dict, modules: dict[str, dict]) -> str:
    return _digest({
        "domain": "hocus-module-transitive-v1",
        "uri": module["uri"],
        "sourceDigest": module["sourceDigest"],
        "interfaceDigest": module["interfaceDigest"],
        "dependencies": [
            {"uri": uri, "transitiveDigest": modules[uri]["transitiveDigest"]}
            for uri in module["dependencies"]
        ],
    })


def _stack_digest(frames: list[dict]) -> str:
    return _digest({"domain": "hocus-expansion-stack-v1", "frames": frames})


def _rehash(payload: dict) -> None:
    unsigned = copy.deepcopy(payload)
    unsigned.pop("bundleDigest", None)
    payload["bundleDigest"] = _digest(unsigned)


def _rehash_expansion(payload: dict) -> None:
    payload["sourceMaps"]["expansionMapDigest"] = _digest(payload["graphSpec"]["expansionMap"])
    _rehash(payload)


def _span(uri: str) -> dict:
    return {
        "sourceUri": uri,
        "start": {"offset": 0, "line": 1, "column": 1},
        "end": {"offset": 1, "line": 1, "column": 2},
    }


def _future_bundle(*, populated: bool = False) -> dict:
    payload = _bundle().to_dict()
    entry_uri = payload["entrySource"]["uri"]
    payload.update({
        "$schema": "hocuspocus://schemas/compiled-bundle/v0.3",
        "bundleVersion": "0.3",
        "compilerVersion": "0.4.0",
        "graphSpecVersion": "0.3",
        "languageVersion": "0.2",
        "resolvedModuleSet": {
            "$schema": "hocuspocus://schemas/resolved-module-set/v1",
            "kind": "hocus_resolved_module_set",
            "schemaVersion": 1,
            "languageVersion": "0.2",
            "projectUid": payload["projectUid"],
            "entrySourceUri": entry_uri,
            "projectManifestDigest": payload["projectManifestDigest"],
            "projectLockDigest": payload["projectLockDigest"],
            "resolverPolicyDigest": _digest("resolver-policy"),
            "limits": {
                "sourceBytesPerFile": 1_048_576,
                "aggregateSourceBytes": 8_388_608,
                "moduleFiles": 4096,
                "importDepth": 64,
                "instanceDepth": 64,
                "instances": 4096,
                "parametersPerModule": 256,
                "exportsPerModule": 256,
                "expandedNodes": 10_000,
                "aggregateCodeBytes": 4_194_304,
                "sourceMapEntries": 100_000,
                "diagnostics": 500,
            },
            "modules": [],
        },
    })
    graph = payload["graphSpec"]
    graph.update({
        "$schema": "hocuspocus://schemas/graph-spec/v0.3",
        "graphSpecVersion": "0.3",
        "languageVersion": "0.2",
        "expansionMap": {
            "$schema": "hocuspocus://schemas/expansion-map/v1",
            "kind": "hocus_expansion_map",
            "schemaVersion": 1,
            "graphSpecVersion": "0.3",
            "entrySourceUri": entry_uri,
            "stacks": [],
            "mappings": [],
        },
    })
    if populated:
        module_uri = "hocus-project://city/modules/source.hocus"
        source_digest = _digest("module-source")
        payload["dependencies"] = [{"uri": module_uri, "digest": source_digest, "kind": "module"}]
        module = {
            "uri": module_uri,
            "moduleName": "Source",
            "relativePath": "modules/source.hocus",
            "origin": "project",
            "ownerUid": "city",
            "alias": None,
            "version": None,
            "moduleManifestDigest": None,
            "sourceDigest": source_digest,
            "interfaceDigest": _digest("module-interface"),
            "transitiveDigest": "",
            "dependencies": [],
            "languageVersion": "0.2",
        }
        module["transitiveDigest"] = _transitive_digest(module, {})
        payload["resolvedModuleSet"]["modules"] = [module]
        frames = [{
            "moduleUri": module_uri,
            "sourceDigest": source_digest,
            "moduleName": "Source",
            "instanceSymbol": "source_module",
            "instanceIdPath": ["terrain.source"],
            "importSpan": _span(entry_uri),
            "useSpan": _span(entry_uri),
        }]
        mapping = {
            "generatedPointer": "/nodes/0",
            "originKind": "definition",
            "primarySpan": _span(module_uri),
            "relatedOrigins": [{"role": "instance", "span": _span(entry_uri)}],
            "stackId": _stack_digest(frames),
        }
        mapping["originId"] = _digest(mapping)
        graph["expansionMap"]["stacks"] = [{"stackId": _stack_digest(frames), "frames": frames}]
    required_pointers = {""}
    required_pointers.update(f"/externalNodes/{i}" for i, _ in enumerate(graph["externalNodes"]))
    for node_index, node in enumerate(graph["nodes"]):
        prefix = f"/nodes/{node_index}"
        required_pointers.add(prefix)
        required_pointers.update(f"{prefix}/inputs/{i}" for i, _ in enumerate(node["inputs"]))
        required_pointers.update(f"{prefix}/parms/{i}" for i, _ in enumerate(node["parms"]))
    required_pointers.update(f"/{key}" for key in ("display", "render", "output", "layout") if graph[key] is not None)
    mappings = []
    for pointer in sorted(required_pointers):
        uses_module = populated and pointer == "/nodes/0"
        mapping = {
            "generatedPointer": pointer,
            "originKind": "definition",
            "primarySpan": _span(module_uri if uses_module else entry_uri),
            "relatedOrigins": [],
            "stackId": _stack_digest(frames) if uses_module else None,
        }
        mapping["originId"] = _digest(mapping)
        mappings.append(mapping)
    graph["expansionMap"]["mappings"] = mappings
    expansion_map = graph["expansionMap"]
    payload["sourceMaps"] = {
        "format": "graph-spec-expansion-v1",
        "entrySourceUri": entry_uri,
        "embeddedInGraphSpec": True,
        "expansionMapVersion": 1,
        "expansionMapDigest": _digest(expansion_map),
    }
    _rehash(payload)
    return payload


class HocusScriptModuleIrTests(unittest.TestCase):
    def test_module_and_stack_digest_vectors_are_stable(self) -> None:
        payload = _future_bundle(populated=True)
        self.assertEqual(
            payload["resolvedModuleSet"]["modules"][0]["transitiveDigest"],
            "sha256:ed48754448236c665f664186744cd6be3817c1e12c1004fe1bdf14bfa75ad94d",
        )
        self.assertEqual(
            payload["graphSpec"]["expansionMap"]["stacks"][0]["stackId"],
            "sha256:617671bb1a15b2940bb5a89f15c14f6b15d42784c45eb91ae651122856bfe682",
        )

    def test_hs6_schemas_share_strict_semver_20_with_build_metadata(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        schemas = {
            name: json.loads((ROOT / "docs" / "schemas" / name).read_text("utf-8"))
            for name in (
                "hocus-project-v3.schema.json", "hocus-module-v1.schema.json",
                "hocus-lock-v3.schema.json", "resolved-module-set-v1.schema.json",
                "compiled-bundle-v0.3.schema.json",
            )
        }
        version_contracts = (
            schemas["hocus-project-v3.schema.json"]["$defs"]["semanticVersion"],
            schemas["hocus-module-v1.schema.json"]["properties"]["library"]["properties"]["version"],
            schemas["hocus-lock-v3.schema.json"]["$defs"]["module"]["properties"]["libraryVersion"]["oneOf"][0],
            schemas["resolved-module-set-v1.schema.json"]["$defs"]["semanticVersion"],
            schemas["compiled-bundle-v0.3.schema.json"]["$defs"]["semanticVersion"],
        )
        valid = ("0.0.0", "1.2.3", "1.2.3-alpha.1", "1.2.3+build.5", "1.2.3-alpha.1+build.5")
        invalid = ("1.2", "01.2.3", "1.02.3", "1.2.03", "1.2.3-01", "1.2.3-alpha..1", "1.2.3+build..5", "latest")
        for contract in version_contracts:
            validator = Draft202012Validator(contract)
            for version in valid:
                self.assertFalse(list(validator.iter_errors(version)), version)
            for version in invalid:
                self.assertTrue(list(validator.iter_errors(version)), version)

    def test_current_compiler_does_not_enable_language_02(self) -> None:
        result = compile_source('hocus 0.2; graph future { target "/obj/geo1"; }', "future.hocus")
        self.assertFalse(result.valid)
        self.assertIn("HOCUS102", {item.code for item in result.diagnostics})

    def test_empty_and_populated_v03_scaffolds_cross_trust_boundary(self) -> None:
        for populated in (False, True):
            with self.subTest(populated=populated):
                payload = _future_bundle(populated=populated)
                decoded = decode_compiled_bundle(payload)
                self.assertEqual(decoded.payload["bundleVersion"], "0.3")
                graph = graph_spec_from_dict(decoded.payload["graphSpec"])
                self.assertEqual(graph.to_dict(), decoded.payload["graphSpec"])

    def test_v03_rejects_version_drift_and_unlocked_expansion_frames(self) -> None:
        cases = []
        mixed = _future_bundle()
        mixed["compilerVersion"] = "0.3.0"
        cases.append((mixed, "HOCUS507"))
        bad_language = _future_bundle()
        bad_language["languageVersion"] = "0.1"
        bad_language["graphSpec"]["languageVersion"] = "0.1"
        cases.append((bad_language, "HOCUS507"))
        unlocked = _future_bundle(populated=True)
        unlocked["graphSpec"]["expansionMap"]["stacks"][0]["frames"][0]["moduleUri"] = (
            "hocus-project://city/modules/missing.hocus"
        )
        cases.append((unlocked, "HOCUS520"))
        for payload, code in cases:
            _rehash(payload)
            with self.subTest(code=code), self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, code)

    def test_v03_rejects_module_and_expansion_digest_drift(self) -> None:
        module_drift = _future_bundle(populated=True)
        module_drift["resolvedModuleSet"]["modules"][0]["sourceDigest"] = _digest("wrong")
        _rehash(module_drift)
        with self.assertRaises(BundleValidationError) as captured:
            decode_compiled_bundle(module_drift)
        self.assertEqual(captured.exception.code, "HOCUS512")

        map_drift = _future_bundle(populated=True)
        map_drift["sourceMaps"]["expansionMapDigest"] = _digest("wrong")
        _rehash(map_drift)
        with self.assertRaises(BundleValidationError) as captured:
            decode_compiled_bundle(map_drift)
        self.assertEqual(captured.exception.code, "HOCUS517")

    def test_v03_rejects_forged_resolver_and_module_provenance(self) -> None:
        cases = []
        envelope = _future_bundle(populated=True)
        envelope["resolvedModuleSet"]["projectUid"] = "forged"
        cases.append(envelope)

        owner = _future_bundle(populated=True)
        owner["resolvedModuleSet"]["modules"][0]["ownerUid"] = "forged"
        cases.append(owner)

        alias = _future_bundle(populated=True)
        module = alias["resolvedModuleSet"]["modules"][0]
        old_uri = module["uri"]
        module.update({
            "uri": "hocus-module://library/modules/source.hocus",
            "origin": "external_library",
            "ownerUid": "library",
            "alias": "Bad_Alias",
            "version": "latest",
            "moduleManifestDigest": _digest("module-manifest"),
        })
        module["transitiveDigest"] = _transitive_digest(module, {})
        alias["dependencies"][0]["uri"] = module["uri"]
        stack = alias["graphSpec"]["expansionMap"]["stacks"][0]
        stack["frames"][0]["moduleUri"] = module["uri"]
        stack["stackId"] = _stack_digest(stack["frames"])
        for mapping in alias["graphSpec"]["expansionMap"]["mappings"]:
            if mapping["stackId"] is not None:
                mapping["stackId"] = stack["stackId"]
                unsigned = {key: value for key, value in mapping.items() if key != "originId"}
                mapping["originId"] = _digest(unsigned)
            if mapping["primarySpan"]["sourceUri"] == old_uri:
                mapping["primarySpan"]["sourceUri"] = module["uri"]
                unsigned = {key: value for key, value in mapping.items() if key != "originId"}
                mapping["originId"] = _digest(unsigned)
        _rehash_expansion(alias)
        cases.append(alias)

        for payload in cases:
            _rehash(payload)
            with self.subTest(payload=payload["resolvedModuleSet"]), self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, "HOCUS512")

    def test_v03_rejects_cycles_and_transitive_digest_forgery(self) -> None:
        cycle = _future_bundle(populated=True)
        module = cycle["resolvedModuleSet"]["modules"][0]
        module["dependencies"] = [module["uri"]]
        _rehash(cycle)
        with self.assertRaises(BundleValidationError) as captured:
            decode_compiled_bundle(cycle)
        self.assertEqual(captured.exception.code, "HOCUS512")

        forged = _future_bundle(populated=True)
        forged["resolvedModuleSet"]["modules"][0]["transitiveDigest"] = _digest("forged")
        _rehash(forged)
        with self.assertRaises(BundleValidationError) as captured:
            decode_compiled_bundle(forged)
        self.assertEqual(captured.exception.code, "HOCUS512")

    def test_v03_rejects_noncanonical_or_incomplete_expansion_maps(self) -> None:
        legacy_stack = _future_bundle(populated=True)
        stack = legacy_stack["graphSpec"]["expansionMap"]["stacks"][0]
        stack["stackId"] = _digest(stack["frames"])
        for mapping in legacy_stack["graphSpec"]["expansionMap"]["mappings"]:
            if mapping["stackId"] is not None:
                mapping["stackId"] = stack["stackId"]
                unsigned = {key: value for key, value in mapping.items() if key != "originId"}
                mapping["originId"] = _digest(unsigned)
        _rehash_expansion(legacy_stack)

        unreferenced = _future_bundle(populated=True)
        frames = copy.deepcopy(unreferenced["graphSpec"]["expansionMap"]["stacks"][0]["frames"])
        frames[0]["instanceSymbol"] = "unused"
        stack_id = _stack_digest(frames)
        unreferenced["graphSpec"]["expansionMap"]["stacks"].append({"stackId": stack_id, "frames": frames})
        unreferenced["graphSpec"]["expansionMap"]["stacks"].sort(key=lambda item: item["stackId"])
        _rehash_expansion(unreferenced)

        missing = _future_bundle()
        missing["graphSpec"]["expansionMap"]["mappings"].pop()
        _rehash_expansion(missing)

        bad_pointer = _future_bundle()
        mapping = bad_pointer["graphSpec"]["expansionMap"]["mappings"][0]
        mapping["generatedPointer"] = "/nodes/~2"
        unsigned = {key: value for key, value in mapping.items() if key != "originId"}
        mapping["originId"] = _digest(unsigned)
        bad_pointer["graphSpec"]["expansionMap"]["mappings"].sort(key=lambda item: item["generatedPointer"])
        _rehash_expansion(bad_pointer)

        for payload in (legacy_stack, unreferenced, missing, bad_pointer):
            with self.subTest(), self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(payload)
            self.assertEqual(captured.exception.code, "HOCUS520")

    def test_graphspec_and_expansion_map_cross_schema_validation(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema/referencing not installed")
        names = (
            "expansion-map-v1.schema.json",
            "graph-spec-v0.3.schema.json",
            "resolved-module-set-v1.schema.json",
            "compiled-bundle-v0.3.schema.json",
        )
        schemas = [json.loads((ROOT / "docs" / "schemas" / name).read_text("utf-8")) for name in names]
        registry = Registry().with_resources(
            [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
        )
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
        Draft202012Validator(schemas[1], registry=registry).validate(_future_bundle()["graphSpec"])
        Draft202012Validator(schemas[3], registry=registry).validate(_future_bundle(populated=True))

    def test_bundle_limits_are_version_specific(self) -> None:
        current = _bundle().to_dict()
        future = _future_bundle()
        with mock.patch.object(bundle_module, "MAX_BUNDLE_VALUES", 1):
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(current)
            self.assertEqual(captured.exception.code, "HOCUS519")
            self.assertEqual(decode_compiled_bundle(future).payload["bundleVersion"], "0.3")
        with mock.patch.object(bundle_module, "MAX_MODULE_BUNDLE_VALUES", 1):
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(future)
            self.assertEqual(captured.exception.code, "HOCUS519")
        with mock.patch.object(bundle_module, "MAX_BUNDLE_BYTES", 1):
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(current)
            self.assertEqual(captured.exception.code, "HOCUS504")
            self.assertEqual(decode_compiled_bundle(future).payload["bundleVersion"], "0.3")
        with mock.patch.object(bundle_module, "MAX_MODULE_BUNDLE_BYTES", 1):
            with self.assertRaises(BundleValidationError) as captured:
                decode_compiled_bundle(future)
            self.assertEqual(captured.exception.code, "HOCUS504")


if __name__ == "__main__":
    unittest.main()
