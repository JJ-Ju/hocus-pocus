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
    CompiledBundle,
    CatalogValidationError,
    ResolvedModuleUnit,
    SnapshotCatalogProvider,
    check_source,
    compile_source,
    complete_source,
    decode_catalog_snapshot,
    expand_module_graph,
    export_network_document,
    format_source,
    format_syntax,
    graph_spec_from_dict,
    lower_bundle_to_document,
    parse_syntax,
    resolve_graph,
)
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    MenuItem,
    OperatorDefinition,
    ParameterDefinition,
)
from hocuspocus.hocusscript.native_artifact import (
    NativeArtifactError,
    publish_text_artifact,
)


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

    def test_compiled_graph_lowers_and_exports_back_to_equivalent_source(self) -> None:
        provider = _provider()
        baseline = _baseline()
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
        self.assertTrue(resolve_graph(recompiled.graph_spec, provider).valid)

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
