from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    CatalogValidationError,
    CarrierContractError,
    CompiledBundle,
    ControlResolverLimits,
    ExternalNodeBinding,
    ResolvedModuleLimits,
    ResolvedModuleUnit,
    SnapshotCatalogProvider,
    check_source,
    compile_source,
    complete_source,
    decode_catalog_snapshot,
    decode_control_bundle_envelope,
    decode_control_expansion_map_envelope,
    decode_control_graph_spec_envelope,
    decode_control_resolved_module_set_envelope,
    expand_control_graph,
    expand_module_graph,
    export_network_document,
    format_source,
    format_syntax,
    graph_spec_from_dict,
    lower_bundle_to_document,
    parse_syntax,
    require_carrier_contract,
    resolve_graph,
)
from hocuspocus.hocusscript._document_bundle_boundary import (
    _DecodedDocumentBundle,
    _DocumentBundleBoundaryError,
    _decode_document_bundle_content,
)
from hocuspocus.hocusscript.document_bundle_lowering import (
    _lower_decoded_document_bundle_to_document,
)
from hocuspocus.hocusscript.document_bundle_semantics import (
    _FreshDocumentSemanticError,
    _resolve_decoded_document_bundle_semantics,
)
from hocuspocus.hocusscript.document_lowering import DocumentLoweringError
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    MenuItem,
    OperatorDefinition,
    ParameterDefinition,
)
from hocuspocus.hocusscript.control_artifact import _compile_control_bundle
from hocuspocus.hocusscript.lexer import Lexer
from hocuspocus.hocusscript.native_artifact import (
    NativeArtifactError,
    publish_text_artifact,
)
from hocuspocus.hocusscript.module_semantic import _semantic_payload_with_origins
from hocuspocus.hocusscript.parser import Parser
from tests.hocusscript_h5_helpers import (
    _assert_adopted_external_lifecycle,
    _assert_forged_document_stacks_rejected,
    _retained_control_stack,
    _tampered_control_bundle,
)
from tests.hocusscript_export_helpers import assert_managed_export_symbol_identity
from tests.hocusscript_hs7_helpers import assert_catalog_tuple_namespace_rejected

FIXTURES = ROOT / "tests" / "fixtures" / "hocusscript"
ENTRY_URI = "hocus-project://city/assets/rocks.hocus"
MODULE_URI = "hocus-project://city/modules/noise.hocus"

def _digest(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _without_source_locations(value):
    if isinstance(value, dict):
        return {
            key: _without_source_locations(item)
            for key, item in value.items()
            if key not in {"span", "bodySpan", "offsetMap", "fieldSpans"}
        }
    if isinstance(value, list):
        return [_without_source_locations(item) for item in value]
    return value


def _provider() -> FakeCatalogProvider:
    geometry = ConnectorDefinition(
        0, "geometry", "Geometry", data_types=("geometry",), categories=("Sop",)
    )
    points = ConnectorDefinition(
        1, "points", "Points", data_types=("geometry",), categories=("Sop",)
    )
    source_input = ConnectorDefinition(
        0, "source", "Source", data_types=("geometry",), categories=("Sop",)
    )
    return FakeCatalogProvider.create(
        categories=(CategoryDefinition("Sop", "SOP", "sop"),),
        operators=(
            OperatorDefinition(
                "acme::source::1.0",
                "source",
                "acme",
                "1.0",
                "Sop",
                ("studio_source",),
                DefinitionSource("builtin"),
                (
                    ParameterDefinition(
                        "scale",
                        "Scale",
                        "float",
                        3,
                        ("sx", "sy", "sz"),
                        (1.0, 1.0, 1.0),
                    ),
                    ParameterDefinition(
                        "mode",
                        "Mode",
                        "menu",
                        1,
                        (),
                        "fast",
                        menu=(
                            MenuItem("fast", "Fast"),
                            MenuItem("quality", "Quality"),
                        ),
                    ),
                ),
                (),
                (geometry, points),
            ),
            OperatorDefinition(
                "sink",
                "sink",
                None,
                None,
                "Sop",
                (),
                DefinitionSource("builtin"),
                (
                    ParameterDefinition(
                        "snippet",
                        "Snippet",
                        "code",
                        1,
                        (),
                        "",
                        code_surface="vex",
                    ),
                ),
                (source_input,),
                (geometry,),
            ),
        ),
        version="21.0",
        build="21.0.123",
        platform="windows-x86_64",
    )


def _authoring_source(*, mode: str = "merge") -> str:
    ownership = '  ownership "studio.environment.rocks";\n' if mode == "reconcile" else ""
    return f'''hocus 0.1;
graph rocks {{
  target "/obj/geo1";
  category Sop;
  mode {mode};
{ownership}  node source @id("asset.source-01"): "acme::source::1.0" {{
    sx = 2;
    mode = "quality";
  }}
  node sink @id("asset.sink-01"): sink {{
    input[0] = source.output[1];
    snippet = vex`@P *= 2;`;
  }}
  display = sink;
  render = sink;
  output = sink;
  layout = auto;
}}
'''


def _compiled_bundle(*, mode: str = "merge") -> CompiledBundle:
    provider = _provider()
    result = compile_source(
        _authoring_source(mode=mode),
        "assets/rocks.hocus",
        source_uri=ENTRY_URI,
    )
    assert result.valid and result.graph_spec is not None
    result.semantic_result = resolve_graph(result.graph_spec, provider)
    assert result.semantic_result.valid
    result.source_kind = "project_file"
    result.project_uid = "city"
    result.project_manifest_digest = _digest("manifest")
    result.project_lock_digest = _digest("lock")
    result.catalog_fingerprint = provider.catalog.fingerprint
    result.catalog_content_digest = _digest(provider.catalog.to_json())
    return CompiledBundle.from_result(result)


def _control_bundle() -> dict:
    source = '''hocus 0.3;
graph control_asset {
  target "/obj/control_asset";
  category Sop;
  if choice @id("choice") (true) outputs (result: node_output) {
    for series @id("series") (i in range(2)) carry (value: int = 0) {
      node detailed @id("detailed"): "acme::source::1.0" { sx = iter.i; }
      yield value = iter.i;
    }
    node selected @id("selected"): "acme::source::1.0" { mode = "quality"; }
    yield result = selected.output[0];
  } else {
    node fallback @id("fallback"): "acme::source::1.0" {}
    yield result = fallback.output[0];
  }
  node sink_node @id("sink"): sink {
    input[0] = choice.result;
  }
  output = sink_node;
}
'''
    graph = expand_control_graph(source.encode("utf-8"), ENTRY_URI, {}, {})
    provider = _provider()
    limits = ControlResolverLimits().to_dict()
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v2",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 2,
        "languageVersion": "0.3",
        "projectUid": "city",
        "entrySourceUri": ENTRY_URI,
        "projectManifestDigest": _digest("control-manifest"),
        "projectLockDigest": _digest("control-lock"),
        "resolverPolicyDigest": _digest("control-policy"),
        "limits": limits,
        "modules": [],
    }
    return _compile_control_bundle(
        graph,
        resolved,
        entry_source_digest=_digest(source),
        catalog=provider,
        catalog_content_digest=_digest(provider.catalog.to_json()),
        catalog_fingerprint=provider.catalog.fingerprint,
        admitted_required_capabilities=("edit_scene",),
    ).to_dict()


def _module_bundle(*, external: bool = False) -> dict:
    external_source = (
        '  existing upstream = "/obj/module_asset/upstream";\n'
        '  node external_sink @id("external-sink"): sink { '
        "input[0] = upstream.output[0]; }\n"
        if external else ""
    )
    source = '''hocus 0.2;
import { Noise } from "../modules/noise.hocus";
graph module_asset {
  target "/obj/module_asset";
  category Sop;
  use noise @id("noise-instance") = Noise();
  node sink_node @id("module-sink"): sink { input[0] = noise.result; }
''' + external_source + '''\
  output = sink_node;
}
'''
    module_source = '''hocus 0.2;
module Noise() exports (result: node_output) {
  node source @id("module-source"): "acme::source::1.0" {}
  export result = source.output[0];
}
'''
    syntax = parse_syntax(source, ENTRY_URI)
    declaration = syntax.imports[0]
    resolved_import = _ResolvedImport(
        declaration.specifier,
        declaration.imported_name,
        declaration.local_name,
        MODULE_URI,
        declaration.span,
    )
    module_digest = _digest(module_source)
    graph = expand_module_graph(
        entry_source=source.encode("utf-8"),
        entry_uri=ENTRY_URI,
        entry_imports={"Noise": resolved_import},
        modules={
            MODULE_URI: ResolvedModuleUnit(
                MODULE_URI,
                module_digest,
                parse_syntax(module_source, MODULE_URI),
                {},
            ),
        },
    )
    provider = _provider()
    semantic = _semantic_payload_with_origins(
        resolve_graph(graph, provider),
        graph.expansion_map.mappings,
    )
    manifest_digest, lock_digest = _digest("module-manifest"), _digest("module-lock")
    interface_digest = _digest("noise-interface")
    transitive_digest = _digest(json.dumps(
        {
            "domain": "hocus-module-transitive-v1",
            "uri": MODULE_URI,
            "sourceDigest": module_digest,
            "interfaceDigest": interface_digest,
            "dependencies": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ))
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v1",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 1,
        "languageVersion": "0.2",
        "projectUid": "city",
        "entrySourceUri": ENTRY_URI,
        "projectManifestDigest": manifest_digest,
        "projectLockDigest": lock_digest,
        "resolverPolicyDigest": _digest("module-policy"),
        "limits": ResolvedModuleLimits().to_dict(),
        "modules": [{
            "uri": MODULE_URI,
            "moduleName": "Noise",
            "relativePath": "modules/noise.hocus",
            "origin": "project",
            "ownerUid": "city",
            "alias": None,
            "version": None,
            "moduleManifestDigest": None,
            "sourceDigest": module_digest,
            "interfaceDigest": interface_digest,
            "transitiveDigest": transitive_digest,
            "dependencies": [],
            "languageVersion": "0.2",
        }],
    }
    graph_payload = graph.to_dict()
    expansion_json = json.dumps(
        graph_payload["expansionMap"],
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = {
        "$schema": "hocuspocus://schemas/compiled-bundle/v0.3",
        "kind": "hocus_compiled_bundle",
        "bundleVersion": "0.3",
        "compilerVersion": "0.4.0",
        "graphSpecVersion": "0.3",
        "languageVersion": "0.2",
        "portable": True,
        "projectUid": "city",
        "projectManifestDigest": manifest_digest,
        "projectLockDigest": lock_digest,
        "entrySource": {
            "uri": ENTRY_URI,
            "digest": _digest(source),
            "kind": "project_file",
        },
        "dependencies": [{
            "uri": MODULE_URI,
            "digest": module_digest,
            "kind": "module",
        }],
        "catalogConstraints": {
            "schemaVersion": 1,
            "fingerprint": provider.catalog.fingerprint,
            "contentDigest": _digest(provider.catalog.to_json()),
        },
        "requiredCapabilities": semantic["requiredCapabilities"],
        "sourceMaps": {
            "format": "graph-spec-expansion-v1",
            "entrySourceUri": ENTRY_URI,
            "embeddedInGraphSpec": True,
            "expansionMapVersion": 1,
            "expansionMapDigest": _digest(expansion_json),
        },
        "graphSpec": graph_payload,
        "semanticResolution": semantic,
        "resolvedModuleSet": resolved,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {**payload, "bundleDigest": _digest(encoded)}


def _assert_fresh_document_semantics(
    test: unittest.TestCase,
    module_carrier: dict,
    control_carrier: dict,
) -> None:
    provider = _provider()
    for carrier in (module_carrier, control_carrier):
        with test.subTest(fresh_semantics=carrier["bundleVersion"]):
            authenticated = _decode_document_bundle_content(carrier)
            fresh = _resolve_decoded_document_bundle_semantics(
                authenticated, provider,
            )
            test.assertEqual(fresh.graph.to_dict(), carrier["graphSpec"])
            test.assertEqual(
                fresh.required_capabilities,
                tuple(carrier["requiredCapabilities"]),
            )

    checkpoints = 0

    def cancel_during_resolution() -> None:
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 4:
            raise RuntimeError("cancel fresh semantics")

    with test.assertRaisesRegex(RuntimeError, "cancel fresh semantics"):
        _resolve_decoded_document_bundle_semantics(
            _decode_document_bundle_content(control_carrier),
            provider,
            checkpoint=cancel_during_resolution,
        )
    test.assertEqual(checkpoints, 4)

    drift_provider = FakeCatalogProvider.create(
        categories=provider.catalog.categories,
        operators=provider.catalog.operators,
        packages=provider.catalog.packages,
        version="21.1",
        build="21.1.1",
        platform="windows-x86_64",
    )
    with test.assertRaises(_FreshDocumentSemanticError) as catalog_drift:
        _resolve_decoded_document_bundle_semantics(
            _decode_document_bundle_content(module_carrier),
            drift_provider,
        )
    test.assertEqual(catalog_drift.exception.field, "catalogFingerprint")

    selection_drifts = (
        (
            ("semanticResolution", "operatorSelections", 0, "qualifiedName"),
            "other::operator::1.0",
            "operatorSelections",
        ),
        (
            ("semanticResolution", "parameterSelections", 0, "parameterToken"),
            "other_parameter",
            "parameterSelections",
        ),
        (
            ("semanticResolution", "connectionSelections", 0, "inputName"),
            "other_input",
            "connectionSelections",
        ),
    )
    for path, value, field in selection_drifts:
        with test.subTest(fresh_selection_drift=field):
            drifted = _tampered_control_bundle(control_carrier, path, value)
            with test.assertRaises(_FreshDocumentSemanticError) as selection_drift:
                _resolve_decoded_document_bundle_semantics(
                    _decode_document_bundle_content(drifted),
                    provider,
                )
            test.assertEqual(selection_drift.exception.field, field)

    deferred = _module_bundle(external=True)
    authenticated_deferred = _decode_document_bundle_content(deferred)
    unresolved = _resolve_decoded_document_bundle_semantics(
        authenticated_deferred, provider,
    )
    test.assertFalse(unresolved.semantic_result.ready_for_document_lowering)
    live_binding = {
        "upstream": ExternalNodeBinding(
            "acme::source::1.0",
            provider.catalog.fingerprint,
            "Sop",
        ),
    }
    resolved = _resolve_decoded_document_bundle_semantics(
        authenticated_deferred,
        provider,
        external_bindings=live_binding,
    )
    test.assertTrue(resolved.semantic_result.ready_for_document_lowering)

    semantic_drifts = (
        (
            ("semanticResolution", "deferredChecks", 0, "message"),
            "forged deferred check",
            "deferredChecks",
        ),
        (
            ("semanticResolution", "diagnostics", 0, "message"),
            "forged deferred diagnostic",
            "diagnostics",
        ),
    )
    for path, value, field in semantic_drifts:
        with test.subTest(fresh_semantic_drift=field):
            drifted = _tampered_control_bundle(deferred, path, value)
            with test.assertRaises(_FreshDocumentSemanticError) as rejected:
                _resolve_decoded_document_bundle_semantics(
                    _decode_document_bundle_content(drifted),
                    provider,
                )
            test.assertEqual(rejected.exception.field, field)


def _document_node(uid: str, name: str, *, root: bool = False) -> dict:
    path = "/obj/geo1" if root else f"/obj/geo1/{name}"
    return {
        "uid": uid,
        "name": name,
        "typeName": "geo" if root else "null",
        "category": "Sop",
        "path": path,
        "parentPath": "/obj" if root else "/obj/geo1",
        "isNetwork": root,
        "position": [0.0, 0.0],
        "flags": {
            "display": False,
            "render": False,
            "bypass": False,
            "template": False,
        },
        "metadata": {},
    }


def _baseline() -> dict:
    return {
        "$schema": "hocuspocus://schemas/network-document/v1",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 7,
        "baselineLiveRevision": 19,
        "lastSyncedLiveRevision": 19,
        "rootPath": "/obj/geo1",
        "category": "Sop",
        "metadata": {"artist": "kept"},
        "nodes": [
            _document_node("root-stable", "geo1", root=True),
            _document_node("artist-node", "artist"),
        ],
        "ports": [],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


@dataclass(frozen=True)
class _ResolvedImport:
    specifier: str
    imported_name: str
    local_name: str
    target_uri: str
    span: object


class HocusScriptAuthoringScenarios(unittest.TestCase):
    def test_v01_source_compiles_formats_and_matches_the_authoring_golden(self) -> None:
        source_path = FIXTURES / "v0.1" / "all_features.hocus"
        source = source_path.read_text(encoding="utf-8")
        expected = json.loads(
            (FIXTURES / "v0.1" / "all_features.graph.json").read_text(encoding="utf-8")
        )

        compiled = compile_source(
            source,
            source_path.name,
            source_uri="hocus-fixture:///v0.1/all_features.hocus",
        )
        self.assertTrue(compiled.valid, [item.to_dict() for item in compiled.diagnostics])
        self.assertEqual(
            _without_source_locations(compiled.graph_spec.to_dict()),
            expected,
        )

        formatted = format_source(
            _authoring_source().replace("\n", " "),
            source_path.name,
        )
        self.assertTrue(formatted.valid)
        self.assertTrue(formatted.changed)
        second = format_source(formatted.formatted_source, source_path.name)
        self.assertFalse(second.changed)
        self.assertEqual(second.formatted_source, formatted.formatted_source)

    def test_authoring_errors_are_actionable_and_do_not_crash_the_compiler(self) -> None:
        cases = (
            (
                'hocus 0.1; graph demo { target "/obj/geo1" }',
                "HOCUS245",
            ),
            (
                'hocus 0.1; graph demo { target "/obj/geo1"; '
                'node x: "null" {} node x: "null" {} }',
                "HOCUS306",
            ),
            (
                'hocus 0.1; graph demo { target "/obj/geo1"; '
                'node x @id("bad/id"): "null" {} }',
                "HOCUS321",
            ),
            ("import os;", "HOCUS204"),
            ("\ud800", "HOCUS010"),
        )
        for source, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = compile_source(source, "broken.hocus")
                self.assertFalse(result.valid)
                self.assertIn(expected_code, {item.code for item in result.diagnostics})
                self.assertIsNone(result.formatted_source)

        malformed_control = '''hocus 0.3;
graph demo {
  target "/obj/demo";
  if broken @id() (true) outputs (result: node_output) {
    node nested: "null" {}
    yield result = nested.output[0];
  }
  node after: "null" {}
}
'''
        parser = Parser(Lexer(malformed_control, "broken-control.hocus").tokenize())
        recovered = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS316"])
        self.assertIn(
            "after",
            {getattr(item, "symbol", None) for item in recovered.graph.statements},
        )

        bundle = _control_bundle()
        graph, resolved = bundle["graphSpec"], bundle["resolvedModuleSet"]
        self.assertEqual(decode_control_bundle_envelope(bundle), bundle)
        self.assertEqual(decode_control_graph_spec_envelope(graph), graph)
        self.assertEqual(decode_control_expansion_map_envelope(graph["expansionMap"]), graph["expansionMap"])
        self.assertEqual(decode_control_resolved_module_set_envelope(resolved), resolved)

        extra_capability = copy.deepcopy(bundle)
        extra_capability["semanticResolution"]["requiredCapabilities"] = ["edit_scene", "run_code"]
        with self.assertRaises(CarrierContractError) as capability_drift:
            decode_control_bundle_envelope(
                _tampered_control_bundle(
                    bundle,
                    ("semanticResolution", "requiredCapabilities"),
                    ["edit_scene", "run_code"],
                )
            )
        self.assertEqual(capability_drift.exception.code, "HOCUS494")
        extra_capability = _tampered_control_bundle(
            extra_capability, ("requiredCapabilities",), ["edit_scene", "run_code"],
        )
        self.assertEqual(decode_control_bundle_envelope(extra_capability), extra_capability)

        parm_node = next(
            index for index, node in enumerate(bundle["graphSpec"]["nodes"]) if node["parms"]
        )
        literal_value = bundle["graphSpec"]["nodes"][parm_node]["parms"][0]["value"]
        code_value = {
            "kind": "code", "language": "vex", "body": "@P *= 2;",
            "span": literal_value["span"],
        }
        missing_capability = _tampered_control_bundle(
            bundle, ("graphSpec", "nodes", parm_node, "parms", 0, "value"), code_value,
        )
        with self.assertRaises(CarrierContractError) as missing:
            decode_control_bundle_envelope(missing_capability)
        self.assertEqual(missing.exception.code, "HOCUS494")
        self.assertEqual(missing.exception.details["missing"], ["run_code"])

        undeclared_uri = "hocus-project://other/ghost.hocus"
        provenance_paths = (
            ("graphSpec", "span", "sourceUri"),
            ("graphSpec", "nodes", 0, "span", "sourceUri"),
            ("graphSpec", "nodes", parm_node, "parms", 0, "value", "span", "sourceUri"),
            ("graphSpec", "fieldSpans", "target", "sourceUri"),
        )
        for path in provenance_paths:
            with self.subTest(undeclared_span=path):
                with self.assertRaises(CarrierContractError) as undeclared:
                    decode_control_bundle_envelope(
                        _tampered_control_bundle(bundle, path, undeclared_uri)
                    )
                self.assertEqual(undeclared.exception.code, "HOCUS494")
                self.assertEqual(undeclared.exception.details["sourceUri"], undeclared_uri)

        tampering = (
            (("languageVersion",), "0.2", "HOCUS494"),
            (("resolvedModuleSet", "schemaVersion"), 1, "HOCUS493"),
            (("graphSpec", "nodes", 0, "typeName"), 7, "HOCUS491"),
            (("graphSpec", "expansionMap", "schemaVersion"), 1, "HOCUS492"),
            (("sourceMaps", "expansionMapVersion"), 1, "HOCUS494"),
        )
        for path, value, code in tampering:
            with self.subTest(path=path):
                with self.assertRaises(CarrierContractError) as captured:
                    decode_control_bundle_envelope(
                        _tampered_control_bundle(bundle, path, value)
                    )
                self.assertEqual(captured.exception.code, code)

        with self.assertRaises(CarrierContractError) as noncanonical:
            decode_control_bundle_envelope(json.dumps(bundle, indent=2))
        self.assertEqual(noncanonical.exception.code, "HOCUS494")
        with self.assertRaises(CarrierContractError) as mixed:
            require_carrier_contract(
                language_version="0.2",
                compiler_version="0.5.0",
                graph_spec_version="0.4",
                expansion_map_version=2,
                resolved_module_set_version=2,
                project_manifest_version=2,
                project_lock_version=2,
                module_manifest_version=2,
                bundle_version="0.4",
            )
        self.assertEqual(mixed.exception.code, "HOCUS490")

        carriers = (_module_bundle(), bundle)
        for carrier in carriers:
            with self.subTest(document_bundle=carrier["bundleVersion"]):
                normalized = _decode_document_bundle_content(carrier)
                self.assertEqual(normalized.to_dict(), carrier)
                self.assertEqual(normalized.version, carrier["bundleVersion"])
                self.assertEqual(normalized.digest, carrier["bundleDigest"])
                self.assertEqual(
                    normalized.source_location_classification,
                    "authenticated_carrier_hint",
                )
                with self.assertRaises(ValueError):
                    _DecodedDocumentBundle(
                        normalized.version,
                        "sha256:" + "0" * 64,
                        normalized._payload_json,
                    )
                forged_type = type(
                    "ForgedDecodedDocumentBundle",
                    (_DecodedDocumentBundle,),
                    {"payload": property(lambda self: {})},
                )
                with self.assertRaises(TypeError):
                    _lower_decoded_document_bundle_to_document(
                        forged_type(
                            normalized.version,
                            normalized.digest,
                            normalized._payload_json,
                        ),
                        {},
                    )

        unsupported = _compiled_bundle().to_dict()
        for version in ("0.1", "0.2"):
            with self.subTest(unsupported_document_bundle=version):
                rejected = {**unsupported, "bundleVersion": version}
                with self.assertRaises(_DocumentBundleBoundaryError) as captured:
                    _decode_document_bundle_content(rejected)
                self.assertEqual(captured.exception.code, "HOCUS700")

        mixed_carrier = _tampered_control_bundle(
            bundle, ("graphSpecVersion",), "0.3",
        )
        with self.assertRaises(_DocumentBundleBoundaryError) as mixed_bundle:
            _decode_document_bundle_content(mixed_carrier)
        self.assertEqual(mixed_bundle.exception.code, "HOCUS700")
        self.assertEqual(mixed_bundle.exception.details["causeCode"], "HOCUS494")

        module_bundle = _module_bundle()
        for hostile_path in ("CON.hocus", "cafe\u0301.hocus"):
            hostile_uri = f"hocus-project://city/{hostile_path}"
            with self.subTest(nonportable_bundle_uri=hostile_uri):
                hostile = _tampered_control_bundle(
                    module_bundle, ("entrySource", "uri"), hostile_uri,
                )
                with self.assertRaises(_DocumentBundleBoundaryError) as rejected:
                    _decode_document_bundle_content(hostile)
                self.assertEqual(rejected.exception.code, "HOCUS700")
                self.assertEqual(rejected.exception.details["causeCode"], "HOCUS510")

        _assert_fresh_document_semantics(
            self,
            _module_bundle(),
            extra_capability,
        )

    def test_v02_module_can_be_formatted_and_expanded_into_a_graph(self) -> None:
        module_source = '''hocus 0.2;
module Noise(source: node_output, scale: float = 1.0) exports (result: node_output) {
  node noise @id("noise-node"): "mountain" {
    input[0] = param.source;
    height = param.scale;
  }
  export result = noise.output[0];
}
'''
        graph_source = '''hocus 0.2;
import { Noise as StudioNoise } from "modules/noise.hocus";
graph asset {
  target "/obj/asset";
  category Sop;
  node source: "box" {}
  use noise @id("asset-noise") = StudioNoise(source = source.output[0], scale = 2.0);
  node result: "null" { input[0] = noise.result; }
  output = result;
}
'''
        parsed = parse_syntax(graph_source, ENTRY_URI)
        declaration = parsed.imports[0]
        resolved = _ResolvedImport(
            declaration.specifier,
            declaration.imported_name,
            declaration.local_name,
            MODULE_URI,
            declaration.span,
        )
        module = ResolvedModuleUnit(
            MODULE_URI,
            _digest(module_source),
            parse_syntax(module_source, MODULE_URI),
            {},
        )

        expanded = expand_module_graph(
            entry_source=graph_source.encode("utf-8"),
            entry_uri=ENTRY_URI,
            entry_imports={"StudioNoise": resolved},
            modules={MODULE_URI: module},
        )
        self.assertEqual(expanded.graph_spec_version, "0.3")
        self.assertEqual(len(expanded.nodes), 3)
        self.assertEqual(
            graph_spec_from_dict(expanded.to_dict()).to_dict(),
            expanded.to_dict(),
        )
        formatted = format_syntax(parse_syntax(module_source, MODULE_URI))
        self.assertEqual(
            format_syntax(parse_syntax(formatted, MODULE_URI)),
            formatted,
        )

    def test_catalog_drives_semantic_checks_and_editor_completions(self) -> None:
        provider = _provider()
        compiled = compile_source(_authoring_source(), "rocks.hocus")
        self.assertTrue(compiled.valid)
        semantic = resolve_graph(compiled.graph_spec, provider)
        self.assertTrue(semantic.valid, [item.to_dict() for item in semantic.diagnostics])
        self.assertEqual(
            [item.qualified_name for item in semantic.operator_selections],
            ["acme::source::1.0", "sink"],
        )
        self.assertEqual(semantic.required_capabilities, ("edit_scene", "run_code"))

        missing = check_source(
            _authoring_source().replace('"acme::source::1.0"', '"missing::source"'),
            "rocks.hocus",
            catalog=provider,
        )
        self.assertIn("HOCUS624", {item.code for item in missing.diagnostics})

        type_source = 'hocus 0.1; graph demo { category Sop; node source: "ac'
        types = complete_source(type_source, len(type_source), provider)
        self.assertEqual(types.context, "node_type")
        self.assertEqual([item.label for item in types.items], ["acme::source::1.0"])

        menu_source = (
            'hocus 0.1; graph demo { category Sop; '
            'node source: "acme::source::1.0" { mode = "qua'
        )
        menu = complete_source(menu_source, len(menu_source), provider)
        self.assertEqual(menu.context, "menu_value")
        self.assertEqual([item.label for item in menu.items], ["quality"])

    def test_catalog_snapshot_round_trips_and_rejects_tampering(self) -> None:
        snapshot = _provider().get_catalog()
        decoded = SnapshotCatalogProvider.decode(snapshot.to_json()).get_catalog()
        self.assertEqual(decoded, snapshot)
        self.assertEqual(decoded.fingerprint, snapshot.fingerprint)

        payload = snapshot.to_dict()
        payload["houdini"]["build"] = "tampered"
        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot(payload)
        self.assertEqual(captured.exception.code, "catalog.fingerprint_mismatch")

        assert_catalog_tuple_namespace_rejected(self, snapshot)

    def test_compiled_graph_lowers_and_exports_back_to_equivalent_source(self) -> None:
        provider = _provider()
        baseline = _baseline()
        _assert_adopted_external_lifecycle(
            self, provider, copy.deepcopy(baseline), ENTRY_URI
        )
        preview = lower_bundle_to_document(_compiled_bundle(mode="reconcile"), baseline)
        self.assertTrue(preview.valid, preview.diagnostics)
        self.assertEqual(preview.document["metadata"]["artist"], "kept")
        self.assertIn("artist-node", {item["uid"] for item in preview.document["nodes"]})
        self.assertEqual(
            {item["name"] for item in preview.document["nodes"]},
            {"geo1", "artist", "source", "sink"},
        )
        self.assertIn(
            "set_output",
            {item["action"] for item in preview.candidate_plan["operations"]},
        )
        self.assertFalse(preview.to_dict()["readyForApply"])

        retained = copy.deepcopy(preview.document)
        managed_source = next(node for node in retained["nodes"] if node["name"] == "source")
        managed_source["flags"]["bypass"] = True
        retained["parameterBindings"].append({
            "uid": f"binding:{managed_source['uid']}:artist_value",
            "nodeUid": managed_source["uid"], "parmName": "artist_value",
            "valueMode": "literal", "value": 9, "metadata": {"artist": True},
        })
        repeated_reconcile = lower_bundle_to_document(_compiled_bundle(mode="reconcile"), retained)
        self.assertTrue(repeated_reconcile.valid, repeated_reconcile.diagnostics)
        repeated_source = next(
            node for node in repeated_reconcile.document["nodes"] if node["uid"] == managed_source["uid"]
        )
        self.assertTrue(repeated_source["flags"]["bypass"])
        retained_parms = {
            item["parmName"] for item in repeated_reconcile.document["parameterBindings"]
            if item["nodeUid"] == managed_source["uid"]
        }
        self.assertIn("artist_value", retained_parms)
        self.assertNotIn(
            managed_source["uid"],
            {
                item["entityUid"]
                for item in repeated_reconcile.candidate_plan["operations"]
                if item["action"] in {"create_node", "delete_node"}
            },
        )
        live_document = copy.deepcopy(preview.document)
        live_document["nodes"] = [
            item for item in live_document["nodes"] if item["uid"] != "artist-node"
        ]
        for node in live_document["nodes"]:
            node["metadata"]["identityMode"] = "persistent_user_data"
        exported = export_network_document(
            live_document,
            graph_name="exported_rocks",
            catalog=provider,
        )
        self.assertTrue(exported.valid, [item.to_dict() for item in exported.diagnostics])
        self.assertIn('node source @id("asset.source-01"):', exported.source)
        self.assertIn("input[0] = source.output[1];", exported.source)

        recompiled = compile_source(exported.source, "exported.hocus")
        self.assertTrue(
            recompiled.valid,
            [item.to_dict() for item in recompiled.diagnostics],
        )
        self.assertTrue(
            resolve_graph(recompiled.graph_spec, provider).valid
            and assert_managed_export_symbol_identity(
                self, live_document, provider,
            )
        )
        control_carrier = _tampered_control_bundle(
            _control_bundle(),
            ("semanticResolution", "requiredCapabilities"),
            ["edit_scene", "run_code"],
        )
        control_carrier = _tampered_control_bundle(
            control_carrier,
            ("requiredCapabilities",),
            ["edit_scene", "run_code"],
        )
        for carrier in (_module_bundle(), control_carrier):
            baseline = _baseline()
            target = carrier["graphSpec"]["target"]
            baseline["documentId"] = f"network:{target}"
            baseline["rootPath"] = target
            baseline["nodes"] = baseline["nodes"][:1]
            baseline["nodes"][0].update({
                "uid": "authenticated-root",
                "name": target.rsplit("/", 1)[-1],
                "path": target,
                "parentPath": target.rsplit("/", 1)[0],
            })
            authenticated = _decode_document_bundle_content(carrier)
            lowered = _lower_decoded_document_bundle_to_document(
                authenticated, baseline,
            )
            self.assertTrue(lowered.valid, lowered.diagnostics)
            generated = [
                node for node in lowered.document["nodes"]
                if node["uid"] != "authenticated-root"
            ]
            explicit_ids = {
                node["explicitId"] for node in carrier["graphSpec"]["nodes"]
            }
            generated_ids = {node["uid"] for node in generated}
            self.assertEqual(generated_ids, explicit_ids)
            repeated = _lower_decoded_document_bundle_to_document(
                authenticated, baseline,
            )
            self.assertEqual(
                generated_ids,
                {
                    node["uid"] for node in repeated.document["nodes"]
                    if node["uid"] != "authenticated-root"
                },
            )
            for node in generated:
                source = lowered.source_maps["entities"][node["uid"]]
                self.assertEqual(source["sourceUri"], source["span"]["sourceUri"])
                self.assertTrue(source["originId"].startswith("sha256:"))
            tables = lowered.document["metadata"]["hocusExpansion"]
            _assert_forged_document_stacks_rejected(
                self, lowered, authenticated,
            )
            if carrier["bundleVersion"] == "0.3":
                dependency_uri = carrier["dependencies"][0]["uri"]
                module_stack_ids = {
                    stack["stackId"] for stack in tables["moduleStacks"]
                }
                module_sources = [
                    lowered.source_maps["entities"][uid]
                    for uid in generated_ids
                    if lowered.source_maps["entities"][uid]["sourceUri"] == dependency_uri
                ]
                self.assertTrue(module_sources)
                self.assertTrue(
                    {source["stackId"] for source in module_sources}
                    <= module_stack_ids
                )
            else:
                nested = next(
                    stack for stack in tables["controlStacks"]
                    if len(stack["frames"]) == 2
                )
                self.assertEqual(nested["frames"][0]["branch"], "then")
                self.assertIn(nested["frames"][1]["iterationIndex"], {0, 1})
                self.assertIn(
                    nested["controlStackId"],
                    {
                        item["controlStackId"]
                        for item in lowered.source_maps["entities"].values()
                    },
                )
                self.assertIn(
                    "run_code", lowered.candidate_plan["requiredCapabilities"],
                )
                baseline_with_retained = copy.deepcopy(lowered.document)
                retained_node = copy.deepcopy(generated[0])
                retained_node["uid"] = "retained-other-control-node"
                retained_node["name"] = "retained_other"
                retained_node["path"] = f"{target}/retained_other"
                retained_node["metadata"]["hocus"]["graphName"] = "other_graph"
                prior_stack = _retained_control_stack(
                    tables["controlStacks"][0]
                )
                retained_node["metadata"]["hocus"]["controlStackId"] = prior_stack[
                    "controlStackId"
                ]
                baseline_with_retained["nodes"].append(retained_node)
                retained_tables = baseline_with_retained["metadata"]["hocusExpansion"]
                retained_tables["controlStacks"].append(prior_stack)
                retained_tables["controlStacks"].sort(key=lambda item: item["controlStackId"])
                composed = _lower_decoded_document_bundle_to_document(
                    authenticated, baseline_with_retained,
                )
                composed_ids = {
                    item["controlStackId"]
                    for item in composed.document["metadata"]["hocusExpansion"][
                        "controlStacks"
                    ]
                }
                self.assertIn(prior_stack["controlStackId"], composed_ids)
                self.assertIn(retained_node["uid"], {item["uid"] for item in composed.document["nodes"]})

                provenance_revision = _tampered_control_bundle(
                    carrier,
                    ("entrySource", "digest"),
                    _digest("recompiled-control-source"),
                )
                provenance_update = _lower_decoded_document_bundle_to_document(
                    _decode_document_bundle_content(provenance_revision),
                    lowered.document,
                )
                self.assertTrue(provenance_update.valid)
                self.assertTrue({
                    item["entityUid"]
                    for item in provenance_update.candidate_plan["operations"]
                    if item["action"] == "update_node_provenance"
                } >= generated_ids)
                forged_identity = copy.deepcopy(lowered.document)
                forged_node = next(
                    item for item in forged_identity["nodes"]
                    if isinstance((item.get("metadata") or {}).get("hocus"), dict)
                )
                forged_node["metadata"]["hocus"]["projectUid"] = "other-project"
                blocked = _lower_decoded_document_bundle_to_document(
                    authenticated, forged_identity,
                )
                self.assertFalse(blocked.valid)
                self.assertIn("HOCUS706", {item["code"] for item in blocked.diagnostics})

                conflicting = copy.deepcopy(lowered.document)
                referenced = next(
                    node["metadata"]["hocus"]["controlStackId"]
                    for node in conflicting["nodes"]
                    if isinstance((node.get("metadata") or {}).get("hocus"), dict)
                    and node["metadata"]["hocus"].get("controlStackId") is not None
                )
                conflict_stack = next(
                    item
                    for item in conflicting["metadata"]["hocusExpansion"][
                        "controlStacks"
                    ]
                    if item["controlStackId"] == referenced
                )
                conflict_stack["frames"][0]["durableSeed"] += "-conflict"
                with self.assertRaises(DocumentLoweringError) as conflict:
                    _lower_decoded_document_bundle_to_document(
                        authenticated, conflicting,
                    )
                self.assertEqual(conflict.exception.code, "HOCUS710")
            with self.assertRaises(ValueError):
                lower_bundle_to_document(carrier, baseline)

    def test_export_fails_closed_when_managed_state_cannot_be_represented(self) -> None:
        document = lower_bundle_to_document(
            _compiled_bundle(mode="reconcile"),
            _baseline(),
        ).document
        managed = next(item for item in document["nodes"] if item["name"] == "source")
        managed["flags"]["bypass"] = True

        result = export_network_document(document, catalog=_provider())
        self.assertFalse(result.valid)
        self.assertIsNone(result.source)
        self.assertIn("HOCUS805", {item.code for item in result.diagnostics})

    def test_native_artifact_publication_requires_explicit_replace_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "asset.hocus"
            receipt = publish_text_artifact(
                destination,
                "before",
                max_bytes=4096,
            )
            self.assertEqual(receipt.content_digest, _digest(b"before"))
            self.assertFalse(receipt.replaced)

            with self.assertRaises(NativeArtifactError) as conflict:
                publish_text_artifact(destination, "unsafe", max_bytes=4096)
            self.assertEqual(conflict.exception.code, "HOCUS491")
            self.assertEqual(destination.read_text(encoding="utf-8"), "before")

            os.chmod(destination, 0o640)
            original_mode = stat.S_IMODE(destination.stat().st_mode)
            replaced = publish_text_artifact(
                destination,
                "after",
                expected_digest=_digest(b"before"),
                max_bytes=4096,
            )
            self.assertTrue(replaced.replaced)
            self.assertEqual(destination.read_text(encoding="utf-8"), "after")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), original_mode)


if __name__ == "__main__":
    unittest.main()
