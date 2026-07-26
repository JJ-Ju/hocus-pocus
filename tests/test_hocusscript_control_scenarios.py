from __future__ import annotations

import copy
import hashlib
import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.core.settings import ServerSettings
from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    format_syntax,
    parse_syntax,
    resolve_graph,
)
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    OperatorDefinition,
    ParameterDefinition,
)
from hocuspocus.hocusscript.control_expander import expand_control_graph
from hocuspocus.hocusscript.control_semantic import ControlExpansionLimits, validate_control_program
from hocuspocus.hocusscript.expander import ModuleExpansionError
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from hocuspocus.live.operations import LiveOperations


SOURCE_URI = "hocus-project://city/assets/rocks.hocus"


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _catalog_provider() -> FakeCatalogProvider:
    geometry_out = ConnectorDefinition(0, "geometry", "Geometry", data_types=("geometry",))
    points_out = ConnectorDefinition(1, "points", "Points", data_types=("geometry",))
    geometry_in = ConnectorDefinition(0, "source", "Source", data_types=("geometry",))
    return FakeCatalogProvider.create(
        categories=(CategoryDefinition("Sop", "SOP", "sop"),),
        operators=(
            OperatorDefinition(
                "acme::source::1.0",
                "source",
                "acme",
                "1.0",
                "Sop",
                (),
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
                ),
                (),
                (geometry_out, points_out),
            ),
            OperatorDefinition(
                "sink",
                "sink",
                None,
                None,
                "Sop",
                (),
                DefinitionSource("builtin"),
                (),
                (geometry_in,),
                (geometry_out,),
            ),
        ),
    )


def _bundle() -> CompiledBundle:
    source = '''hocus 0.1;
graph rocks {
  target "/obj/geo1";
  category Sop;
  mode merge;
  node source @id("rock-source"): "acme::source::1.0" { sx = 2; }
  node sink @id("rock-sink"): sink { input[0] = source.output[1]; }
  display = sink;
  render = sink;
  output = sink;
}
'''
    provider = _catalog_provider()
    result = compile_source(source, "assets/rocks.hocus", source_uri=SOURCE_URI)
    assert result.valid and result.graph_spec is not None
    result.semantic_result = resolve_graph(result.graph_spec, provider)
    assert result.semantic_result.valid
    result.source_uri = SOURCE_URI
    result.source_kind = "project_file"
    result.project_uid = "city"
    result.project_manifest_digest = _digest("manifest")
    result.project_lock_digest = _digest("lock")
    result.catalog_fingerprint = provider.catalog.fingerprint
    result.catalog_content_digest = _digest(provider.catalog.to_json())
    return CompiledBundle.from_result(result)


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
        "metadata": {},
        "nodes": [
            {
                "uid": "root-stable",
                "name": "geo1",
                "typeName": "geo",
                "category": "Sop",
                "path": "/obj/geo1",
                "parentPath": "/obj",
                "isNetwork": True,
                "position": [0.0, 0.0],
                "flags": {
                    "display": False,
                    "render": False,
                    "bypass": False,
                    "template": False,
                },
                "metadata": {},
            }
        ],
        "ports": [],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


class _Dispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _EditorOperations(OperationBaseMixin, HocusScriptOperationsMixin):
    pass


class _PreviewOperations(OperationBaseMixin, DocumentOperationsMixin, HocusScriptOperationsMixin):
    def __init__(self, *, catalog=None):
        self._dispatcher = _Dispatcher()
        self._documents = LiveDocumentService(logging.getLogger("test.preview"))
        self.baseline = _baseline()
        self.catalog = catalog or _catalog_provider().catalog

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_current_network_payload(self, root_path: str, **_kwargs):
        self.asserted_root_path = root_path
        return copy.deepcopy(self.baseline)

    def _document_preview_live_catalog(self):
        return self.catalog


class _Monitor:
    def mark_dirty(self, *_args, **_kwargs):
        return 1


class _Undos:
    def __init__(self, owner):
        self.owner = owner
        self.snapshot = None
        self.label = None

    @contextmanager
    def group(self, label):
        self.snapshot = copy.deepcopy(self.owner.baseline)
        self.label = label
        yield

    def undoLabels(self):
        return (self.label,) if self.label else ()

    def performUndo(self):
        self.owner.baseline = copy.deepcopy(self.snapshot)
        self.snapshot = None
        self.label = None


class _Hou:
    def __init__(self, owner):
        self.undos = _Undos(owner)


class _PlanOperations(_PreviewOperations):
    def __init__(self, database: Path):
        self._dispatcher = _Dispatcher()
        self._settings = ServerSettings(enable_exec_tools=True)
        self._graph_store = LiveGraphStore(logging.getLogger("test.plan"), database)
        self._documents = LiveDocumentService(logging.getLogger("test.plan"), self._graph_store)
        self._monitor = _Monitor()
        self.baseline = _baseline()
        self.catalog = _catalog_provider().catalog
        self._hou = _Hou(self)
        self.target_document = None
        self.fail_execution = False

    def _require_hou(self):
        return self._hou

    def _document_plan_bundle_impl(self, arguments, context):
        result = super()._document_plan_bundle_impl(arguments, context)
        stored = self._documents.apply_plan(result["planId"], expected_hash=result["planHash"])
        self.target_document = copy.deepcopy(stored["targetDocument"])
        return result

    def _document_execute_apply_plan(self, plan, baseline, *, checkpoint=None):
        if checkpoint:
            checkpoint()
        self.baseline = copy.deepcopy(self.target_document)
        if self.fail_execution:
            self.fail_execution = False
            raise RuntimeError("injected execution failure")
        return [{"type": "fake_apply", "summary": copy.deepcopy(plan.get("summary", {}))}]


def _apply_arguments(plan: dict, key: str) -> dict:
    return {
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "expectedDocumentRevision": plan["baseline"]["documentRevision"],
        "expectedLiveRevision": plan["baseline"]["liveRevision"],
        "confirmationToken": plan.get("confirmationToken"),
        "idempotencyKey": key,
    }


def _expand(body: str, *, limits=None, cancellation=None):
    source = f'''hocus 0.3;
graph ControlGraph {{
  target = "/obj";
{body}
}}
'''
    return expand_control_graph(
        source.encode(),
        "hocus-project://controls/main.hocus",
        {},
        {},
        limits=limits or ControlExpansionLimits(),
        cancellation=cancellation,
    )


class HocusScriptControlScenarios(unittest.TestCase):
    def test_mcp_editor_surface_compiles_and_formats_without_scene_access(self) -> None:
        operations = _EditorOperations()
        compiled = operations.document_compile_source(
            {
                "source_name": "demo.hocus",
                "source": 'hocus 0.1; graph demo { target "/obj/geo1"; }',
            },
            RequestContext(),
        )["structuredContent"]
        formatted = operations.document_format_source(
            {"source": 'hocus 0.1; graph demo { target "/obj/geo1"; }'},
            RequestContext(),
        )["structuredContent"]

        self.assertTrue(compiled["valid"])
        self.assertFalse(compiled["readyForApply"])
        self.assertTrue(formatted["valid"])
        self.assertIn("graph demo {\n", formatted["formattedSource"])

        tools, resources = ToolRegistry(), ResourceRegistry()
        LiveOperations.__new__(LiveOperations).register(tools, resources)
        for name in ("document.compile_source", "document.format_source", "document.preview_bundle"):
            definition = tools.get(name)
            self.assertIsNotNone(definition)
            self.assertEqual(definition.required_capabilities, ("observe",))
            self.assertTrue(definition.annotations["readOnlyHint"])

    def test_preview_produces_a_read_only_plan_and_rejects_catalog_drift(self) -> None:
        operations = _PreviewOperations()
        payload = operations.document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]

        self.assertTrue(payload["valid"])
        self.assertTrue(payload["readyForPlan"])
        self.assertFalse(payload["readyForApply"])
        self.assertEqual(operations.asserted_root_path, "/obj/geo1")
        self.assertTrue(payload["preview"]["candidatePlan"]["operations"])

        empty_catalog = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"),),
            operators=(),
        ).catalog
        blocked = _PreviewOperations(catalog=empty_catalog).document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertFalse(blocked["valid"])
        self.assertFalse(blocked["readyForPlan"])
        self.assertEqual(blocked["diagnostics"][0]["code"], "HOCUS720")

    def test_plan_apply_is_guarded_durable_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "graph.sqlite3")
            context = RequestContext(permissions=("edit_scene", "run_code"))
            plan = operations.document_plan_bundle(
                {"bundle": _bundle().to_dict()}, context
            )["structuredContent"]

            before = copy.deepcopy(operations.baseline)
            invalid = _apply_arguments(plan, "invalid-token")
            invalid["planHash"] = "sha256:" + "0" * 64
            with self.assertRaises(JsonRpcError):
                operations.document_apply_plan(invalid, context)
            self.assertEqual(operations.baseline, before)

            arguments = _apply_arguments(plan, "apply-rocks")
            first = operations.document_apply_plan(arguments, context)["structuredContent"]
            replay = operations.document_apply_plan(arguments, context)["structuredContent"]
            self.assertTrue(first["applied"])
            self.assertTrue(first["verified"])
            self.assertFalse(first["idempotentReplay"])
            self.assertTrue(replay["idempotentReplay"])

    def test_failed_apply_rolls_back_the_scene_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "graph.sqlite3")
            context = RequestContext(permissions=("edit_scene", "run_code"))
            plan = operations.document_plan_bundle(
                {"bundle": _bundle().to_dict()}, context
            )["structuredContent"]
            before = copy.deepcopy(operations.baseline)
            operations.fail_execution = True

            with self.assertRaises(JsonRpcError) as captured:
                operations.document_apply_plan(_apply_arguments(plan, "failed-apply"), context)

            self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS755")
            self.assertTrue(captured.exception.data["failure"]["rolledBack"])
            self.assertEqual(operations.baseline, before)

    def test_controls_parse_and_format_as_stable_source(self) -> None:
        source = '''hocus 0.3;
module Repeat(flag: bool = true, count: int = 2) exports (out: int) {
  for series @id("series") (i in range(param.count)) carry (out: int = 0) {
    if choice @id("choice") (param.flag) outputs (out: int) {
      yield out = iter.i;
    } else {
      yield out = carry.out;
    }
    yield out = choice.out;
  }
  export out = series.out;
}
'''
        formatted = format_syntax(parse_syntax(source, "repeat.hocus"))
        self.assertEqual(format_syntax(parse_syntax(formatted, "repeat.hocus")), formatted)
        self.assertIn('for series @id("series")', formatted)
        self.assertIn('if choice @id("choice")', formatted)

        legacy = compile_source(source, "repeat.hocus")
        self.assertFalse(legacy.valid)
        self.assertEqual(legacy.diagnostics[0].code, "HOCUS102")

    def test_semantics_validate_the_whole_control_program(self) -> None:
        valid = '''hocus 0.3;
graph G {
  target "/obj/g";
  if choice @id("choice") (true) outputs (out: int) {
    yield out = 1;
  } else {
    yield out = 2;
  }
  node result: "null" { value = choice.out; }
}
'''
        self.assertIsNone(validate_control_program(parse_syntax(valid, "valid.hocus"), {}, {}))

        invalid = valid.replace("yield out = 2;", 'node broken: "null" { value = missing.value; } yield out = 2;')
        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(parse_syntax(invalid, "invalid.hocus"), {}, {})
        self.assertEqual(captured.exception.code, "HOCUS471")

    def test_expansion_executes_if_and_for_into_a_canonical_graph(self) -> None:
        graph = _expand(
            '''
  if choice @id("choice") (true) outputs (value: int) {
    yield value = 7;
  } else {
    yield value = 9;
  }
  for series @id("series") (i in range(3)) carry (value: int = choice.value) {
    node step @id("step"): "null" { index = iter.i; previous = carry.value; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
'''
        )

        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(
            [node["parms"][0]["value"]["value"] for node in graph["nodes"][:3]],
            [0, 1, 2],
        )
        self.assertEqual(graph["nodes"][-1]["parms"][0]["value"]["value"], 2)
        self.assertTrue(graph["expansionMap"]["mappings"])
        self.assertTrue(graph["expansionMap"]["controlStacks"])

    def test_expansion_stops_at_public_limits_or_cancellation(self) -> None:
        body = '''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
'''
        with self.assertRaises(ModuleExpansionError) as limited:
            _expand(body, limits=ControlExpansionLimits(aggregate_iterations=2))
        self.assertEqual(limited.exception.code, "HOCUS464")

        with self.assertRaises(ModuleExpansionError) as cancelled:
            _expand(body, cancellation=lambda: True)
        self.assertEqual(cancelled.exception.code, "HOCUS499")


if __name__ == "__main__":
    unittest.main()
