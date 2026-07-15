from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (  # noqa: E402
    CONTROL_BUNDLE_VERSION,
    CONTROL_CARRIER_CONTRACT,
    CONTROL_COMPILER_VERSION,
    CONTROL_EXPANSION_MAP_VERSION,
    CONTROL_GRAPH_SPEC_VERSION,
    CONTROL_LANGUAGE_VERSION,
    CONTROL_MODULE_MANIFEST_VERSION,
    CONTROL_PROJECT_LOCK_VERSION,
    CONTROL_PROJECT_MANIFEST_VERSION,
    CONTROL_RESOLVED_MODULE_SET_VERSION,
    STATIC_CARRIER_CONTRACT,
    CarrierContractError,
    compile_source,
    decode_control_bundle_envelope,
    decode_control_expansion_map_envelope,
    decode_control_graph_spec_envelope,
    decode_control_resolved_module_set_envelope,
    require_carrier_contract,
)
from hocuspocus.hocusscript.bundle import BundleValidationError, decode_compiled_bundle  # noqa: E402
from test_hocusscript_module_ir import _future_bundle, _rehash  # noqa: E402


SCHEMA_NAMES = (
    "hocus-project-v4.schema.json",
    "hocus-lock-v4.schema.json",
    "hocus-module-v2.schema.json",
    "resolved-module-set-v2.schema.json",
    "expansion-map-v2.schema.json",
    "graph-spec-v0.4.schema.json",
    "compiled-bundle-v0.4.schema.json",
)


def _control_bundle(*, populated: bool = True) -> dict:
    payload = copy.deepcopy(_future_bundle(populated=populated))
    payload.update({
        "$schema": "hocuspocus://schemas/compiled-bundle/v0.4",
        "bundleVersion": "0.4",
        "compilerVersion": "0.5.0",
        "graphSpecVersion": "0.4",
        "languageVersion": "0.3",
    })
    graph = payload["graphSpec"]
    graph.update({
        "$schema": "hocuspocus://schemas/graph-spec/v0.4",
        "graphSpecVersion": "0.4",
        "languageVersion": "0.3",
    })
    expansion = graph["expansionMap"]
    expansion.update({
        "$schema": "hocuspocus://schemas/expansion-map/v2",
        "schemaVersion": 2,
        "graphSpecVersion": "0.4",
        "controlStacks": [],
    })
    for mapping in expansion["mappings"]:
        mapping["controlStackId"] = None
    if expansion["mappings"]:
        from test_hocusscript_module_ir import _digest

        primary_span = expansion["mappings"][0]["primarySpan"]
        control_frames = [{
            "kind": "if",
            "controlSymbol": "choice",
            "durableSeed": "lod-choice",
            "declarationSpan": primary_span,
            "selectionSpan": primary_span,
            "yieldSpans": [primary_span],
            "branch": "then",
        }]
        control_stack_id = _digest({
            "domain": "hocus-control-stack-v1",
            "frames": control_frames,
        })
        expansion["controlStacks"] = [{
            "controlStackId": control_stack_id,
            "frames": control_frames,
        }]
        expansion["mappings"][0]["controlStackId"] = control_stack_id
    from test_hocusscript_module_ir import _digest
    for mapping in expansion["mappings"]:
        mapping["originId"] = _digest({
            key: mapping[key] for key in sorted(mapping) if key != "originId"
        })
    resolved = payload["resolvedModuleSet"]
    resolved.update({
        "$schema": "hocuspocus://schemas/resolved-module-set/v2",
        "schemaVersion": 2,
        "languageVersion": "0.3",
    })
    resolved["limits"].update({
        "perFoldIterations": 4096,
        "aggregateIterations": 100000,
    })
    for module in resolved["modules"]:
        module["languageVersion"] = "0.3"
    payload["sourceMaps"].update({
        "format": "graph-spec-expansion-v2",
        "expansionMapVersion": 2,
    })
    # The expansion-map content changed, so its independent digest must change too.
    payload["sourceMaps"]["expansionMapDigest"] = _digest(expansion)
    _rehash(payload)
    return payload


def _project_manifest() -> dict:
    return {
        "schema_version": 4,
        "project": {
            "uid": "control-project",
            "source_directories": ["src"],
            "module_directories": ["modules"],
        },
        "language": {"version": "0.3"},
        "lock": {"policy": "required", "path": "pins/hocus.lock.json"},
        "catalog": {"path": "catalog/catalog.json"},
    }


def _project_lock() -> dict:
    bundle = _control_bundle(populated=False)
    return {
        "$schema": "hocuspocus://schemas/hocus-lock/v4",
        "kind": "hocus_project_lock",
        "schemaVersion": 4,
        "projectUid": bundle["projectUid"],
        "manifestDigest": bundle["projectManifestDigest"],
        "languageVersion": "0.3",
        "catalog": {
            "schemaVersion": 1,
            "path": "catalog/catalog.json",
            "contentDigest": bundle["catalogConstraints"]["contentDigest"],
            "fingerprint": bundle["catalogConstraints"]["fingerprint"],
        },
        "modules": [],
    }


class HocusScriptV03CarrierTests(unittest.TestCase):
    def test_compatibility_rows_are_exact_disjoint_and_control_dispatch_is_closed(self) -> None:
        self.assertEqual(
            (
                STATIC_CARRIER_CONTRACT.language_version,
                STATIC_CARRIER_CONTRACT.compiler_version,
                STATIC_CARRIER_CONTRACT.graph_spec_version,
                STATIC_CARRIER_CONTRACT.expansion_map_version,
                STATIC_CARRIER_CONTRACT.resolved_module_set_version,
                STATIC_CARRIER_CONTRACT.project_manifest_version,
                STATIC_CARRIER_CONTRACT.project_lock_version,
                STATIC_CARRIER_CONTRACT.module_manifest_version,
                STATIC_CARRIER_CONTRACT.bundle_version,
            ),
            ("0.2", "0.4.0", "0.3", 1, 1, 3, 3, 1, "0.3"),
        )
        self.assertEqual(
            (
                CONTROL_LANGUAGE_VERSION,
                CONTROL_COMPILER_VERSION,
                CONTROL_GRAPH_SPEC_VERSION,
                CONTROL_EXPANSION_MAP_VERSION,
                CONTROL_RESOLVED_MODULE_SET_VERSION,
                CONTROL_PROJECT_MANIFEST_VERSION,
                CONTROL_PROJECT_LOCK_VERSION,
                CONTROL_MODULE_MANIFEST_VERSION,
                CONTROL_BUNDLE_VERSION,
            ),
            ("0.3", "0.5.0", "0.4", 2, 2, 4, 4, 2, "0.4"),
        )
        self.assertFalse(CONTROL_CARRIER_CONTRACT.dispatch_enabled)
        self.assertEqual(
            require_carrier_contract(
                language_version="0.3", compiler_version="0.5.0",
                graph_spec_version="0.4", expansion_map_version=2,
                resolved_module_set_version=2, project_manifest_version=4,
                project_lock_version=4, module_manifest_version=2,
                bundle_version="0.4",
            ),
            CONTROL_CARRIER_CONTRACT,
        )
        with self.assertRaises(CarrierContractError):
            require_carrier_contract(
                language_version="0.3", compiler_version="0.4.0",
                graph_spec_version="0.4", expansion_map_version=2,
                resolved_module_set_version=2, project_manifest_version=4,
                project_lock_version=4, module_manifest_version=2,
                bundle_version="0.4",
            )

    def test_all_new_schemas_meta_validate_and_accept_exact_samples(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema/referencing is not installed")
        schemas = {
            name: json.loads((ROOT / "docs" / "schemas" / name).read_text("utf-8"))
            for name in SCHEMA_NAMES
        }
        self.assertEqual(len({value["$id"] for value in schemas.values()}), len(SCHEMA_NAMES))
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        bundle = _control_bundle()
        samples = {
            "hocus-project-v4.schema.json": _project_manifest(),
            "hocus-lock-v4.schema.json": _project_lock(),
            "hocus-module-v2.schema.json": {
                "schema_version": 2,
                "library": {"uid": "studio-library", "version": "1.2.3"},
                "language": {"version": "0.3"},
                "entry_modules": ["tools/repeat.hocus"],
            },
            "resolved-module-set-v2.schema.json": bundle["resolvedModuleSet"],
            "expansion-map-v2.schema.json": bundle["graphSpec"]["expansionMap"],
            "graph-spec-v0.4.schema.json": bundle["graphSpec"],
            "compiled-bundle-v0.4.schema.json": bundle,
        }
        for name, sample in samples.items():
            with self.subTest(name=name):
                Draft202012Validator(schemas[name], registry=registry).validate(sample)

    def test_old_and_new_schemas_are_cross_version_disjoint(self) -> None:
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema/referencing is not installed")
        names = (*SCHEMA_NAMES, "resolved-module-set-v1.schema.json", "expansion-map-v1.schema.json",
                 "graph-spec-v0.3.schema.json", "compiled-bundle-v0.3.schema.json")
        schemas = {
            name: json.loads((ROOT / "docs" / "schemas" / name).read_text("utf-8"))
            for name in names
        }
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
        old, new = _future_bundle(), _control_bundle()
        for old_name, new_name, old_value, new_value in (
            ("resolved-module-set-v1.schema.json", "resolved-module-set-v2.schema.json", old["resolvedModuleSet"], new["resolvedModuleSet"]),
            ("expansion-map-v1.schema.json", "expansion-map-v2.schema.json", old["graphSpec"]["expansionMap"], new["graphSpec"]["expansionMap"]),
            ("graph-spec-v0.3.schema.json", "graph-spec-v0.4.schema.json", old["graphSpec"], new["graphSpec"]),
            ("compiled-bundle-v0.3.schema.json", "compiled-bundle-v0.4.schema.json", old, new),
        ):
            with self.subTest(old=old_name, new=new_name):
                self.assertTrue(list(Draft202012Validator(schemas[old_name], registry=registry).iter_errors(new_value)))
                self.assertTrue(list(Draft202012Validator(schemas[new_name], registry=registry).iter_errors(old_value)))

    def test_strict_control_decoders_accept_exact_carriers_and_reject_mixed_or_tampered_data(self) -> None:
        bundle = _control_bundle()
        self.assertEqual(decode_control_bundle_envelope(bundle), bundle)
        self.assertEqual(decode_control_graph_spec_envelope(bundle["graphSpec"]), bundle["graphSpec"])
        self.assertEqual(
            decode_control_expansion_map_envelope(bundle["graphSpec"]["expansionMap"]),
            bundle["graphSpec"]["expansionMap"],
        )
        self.assertEqual(
            decode_control_resolved_module_set_envelope(bundle["resolvedModuleSet"]),
            bundle["resolvedModuleSet"],
        )
        cases = []
        mixed = copy.deepcopy(bundle)
        mixed["compilerVersion"] = "0.4.0"
        _rehash(mixed)
        cases.append(mixed)
        nested = copy.deepcopy(bundle)
        nested["graphSpec"]["expansionMap"]["schemaVersion"] = 1
        _rehash(nested)
        cases.append(nested)
        forged = copy.deepcopy(bundle)
        forged["resolvedModuleSet"]["limits"]["aggregateIterations"] = True
        _rehash(forged)
        cases.append(forged)
        underdeclared = copy.deepcopy(bundle)
        underdeclared["resolvedModuleSet"]["limits"]["sourceMapEntries"] = 1
        _rehash(underdeclared)
        cases.append(underdeclared)
        digest = copy.deepcopy(bundle)
        digest["bundleDigest"] = "sha256:" + ("0" * 64)
        cases.append(digest)
        for candidate in cases:
            with self.subTest(candidate=candidate.get("compilerVersion")), self.assertRaises(CarrierContractError):
                decode_control_bundle_envelope(candidate)

    def test_duplicate_json_keys_nonfinite_values_and_unregistered_live_resources_are_rejected(self) -> None:
        with self.assertRaises(CarrierContractError):
            decode_control_expansion_map_envelope('{"$schema":1,"$schema":2}')
        with self.assertRaises(CarrierContractError):
            decode_control_graph_spec_envelope('{"x":' + ('1' * 5_000) + '}')
        with self.assertRaises(CarrierContractError):
            decode_control_graph_spec_envelope(
                '{"x":' + ('[' * 2_000) + '0' + (']' * 2_000) + '}'
            )
        invalid = _control_bundle()["resolvedModuleSet"]
        invalid["limits"]["aggregateIterations"] = float("nan")
        with self.assertRaises(CarrierContractError):
            decode_control_resolved_module_set_envelope(invalid)
        live_sources = "\n".join(
            (ROOT / path).read_text("utf-8")
            for path in (
                "python3.11libs/hocuspocus/live/ops/hocusscript.py",
                "python3.11libs/hocuspocus/live/operations.py",
            )
        )
        for uri in (
            "graph-spec/v0.4", "expansion-map/v2", "resolved-module-set/v2",
            "hocus-project/v4", "hocus-lock/v4", "compiled-bundle/v0.4",
        ):
            self.assertNotIn(uri, live_sources)

    def test_control_provenance_and_resolved_digests_are_authenticated(self) -> None:
        from test_hocusscript_module_ir import _digest

        expansion = copy.deepcopy(_control_bundle()["graphSpec"]["expansionMap"])
        expansion["mappings"][0]["generatedPointer"] = "/nodes/~2"
        expansion["mappings"][0]["originId"] = _digest({
            key: expansion["mappings"][0][key]
            for key in sorted(expansion["mappings"][0])
            if key != "originId"
        })
        with self.assertRaises(CarrierContractError):
            decode_control_expansion_map_envelope(expansion)

        expansion = copy.deepcopy(_control_bundle()["graphSpec"]["expansionMap"])
        forged_stack_id = "sha256:" + ("f" * 64)
        expansion["controlStacks"][0]["controlStackId"] = forged_stack_id
        expansion["mappings"][0]["controlStackId"] = forged_stack_id
        expansion["mappings"][0]["originId"] = _digest({
            key: expansion["mappings"][0][key]
            for key in sorted(expansion["mappings"][0])
            if key != "originId"
        })
        with self.assertRaises(CarrierContractError):
            decode_control_expansion_map_envelope(expansion)

        resolved = copy.deepcopy(_control_bundle()["resolvedModuleSet"])
        resolved["modules"][0]["transitiveDigest"] = "sha256:" + ("f" * 64)
        with self.assertRaises(CarrierContractError):
            decode_control_resolved_module_set_envelope(resolved)

    def test_semantic_envelope_canonical_uris_and_cross_carrier_provenance_are_strict(self) -> None:
        from test_hocusscript_module_ir import _digest

        semantic = _control_bundle()
        semantic["requiredCapabilities"] = []
        semantic["semanticResolution"] = {}
        _rehash(semantic)
        with self.assertRaises(CarrierContractError):
            decode_control_bundle_envelope(semantic)

        resolved = copy.deepcopy(_control_bundle()["resolvedModuleSet"])
        resolved["entrySourceUri"] = "hocus-project://city/../escape.hocus"
        with self.assertRaises(CarrierContractError):
            decode_control_resolved_module_set_envelope(resolved)

        resolved = copy.deepcopy(_control_bundle()["resolvedModuleSet"])
        resolved["modules"][0]["uri"] = "hocus-project://other/modules/source.hocus"
        with self.assertRaises(CarrierContractError):
            decode_control_resolved_module_set_envelope(resolved)

        bundle = _control_bundle()
        frame = bundle["graphSpec"]["expansionMap"]["stacks"][0]["frames"][0]
        frame["sourceDigest"] = "sha256:" + ("f" * 64)
        stack = bundle["graphSpec"]["expansionMap"]["stacks"][0]
        old_stack_id = stack["stackId"]
        stack["stackId"] = _digest({
            "domain": "hocus-expansion-stack-v1",
            "frames": stack["frames"],
        })
        for mapping in bundle["graphSpec"]["expansionMap"]["mappings"]:
            if mapping["stackId"] == old_stack_id:
                mapping["stackId"] = stack["stackId"]
                mapping["originId"] = _digest({
                    key: mapping[key] for key in sorted(mapping) if key != "originId"
                })
        bundle["sourceMaps"]["expansionMapDigest"] = _digest(
            bundle["graphSpec"]["expansionMap"]
        )
        _rehash(bundle)
        with self.assertRaises(CarrierContractError):
            decode_control_bundle_envelope(bundle)

    def test_declared_instance_budgets_and_malformed_graph_values_fail_typed(self) -> None:
        from test_hocusscript_module_ir import _digest

        bundle = _control_bundle()
        stack = bundle["graphSpec"]["expansionMap"]["stacks"][0]
        old_stack_id = stack["stackId"]
        nested = copy.deepcopy(stack["frames"][0])
        nested["instanceSymbol"] = "nested"
        nested["instanceIdPath"] = ["terrain.source", "terrain.nested"]
        stack["frames"].append(nested)
        stack["stackId"] = _digest({
            "domain": "hocus-expansion-stack-v1",
            "frames": stack["frames"],
        })
        for mapping in bundle["graphSpec"]["expansionMap"]["mappings"]:
            if mapping["stackId"] == old_stack_id:
                mapping["stackId"] = stack["stackId"]
                mapping["originId"] = _digest({
                    key: mapping[key] for key in sorted(mapping) if key != "originId"
                })
        bundle["resolvedModuleSet"]["limits"]["instances"] = 1
        bundle["sourceMaps"]["expansionMapDigest"] = _digest(
            bundle["graphSpec"]["expansionMap"]
        )
        _rehash(bundle)
        with self.assertRaises(CarrierContractError):
            decode_control_bundle_envelope(bundle)

        malformed = _control_bundle()
        malformed["graphSpec"]["nodes"][0]["parms"] = [1]
        _rehash(malformed)
        with self.assertRaises(CarrierContractError):
            decode_control_bundle_envelope(malformed)

    def test_existing_compiler_and_bundle_decoder_remain_closed_to_language_03(self) -> None:
        source = "hocus 0.3; graph G {}"
        result = compile_source(source, "closed.hocus")
        self.assertFalse(result.valid)
        self.assertEqual([item.code for item in result.diagnostics], ["HOCUS102"])
        with self.assertRaises(BundleValidationError):
            decode_compiled_bundle(_control_bundle())


if __name__ == "__main__":
    unittest.main()
