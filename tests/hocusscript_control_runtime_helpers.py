from __future__ import annotations

import copy
import hashlib
import logging
from contextlib import contextmanager
from pathlib import Path

from hocuspocus.core.settings import ServerSettings
from hocuspocus.hocusscript import (
    CompiledBundle,
    ControlResolverLimits,
    compile_source,
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
from hocuspocus.hocusscript.control_artifact import _compile_control_bundle
from hocuspocus.hocusscript.control_expander import expand_control_graph
from hocuspocus.hocusscript.control_semantic import ControlExpansionLimits
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from tests.test_hocusscript_authoring_scenarios import _provider as _h5_provider


ROOT = Path(__file__).resolve().parents[1]
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


def _h5_plan_bundle() -> dict:
    source = '''hocus 0.3;
graph control_plan {
  target "/obj/control_plan";
  category Sop;
  if choice @id("choice") (true) outputs (result: node_output) {
    node selected @id("selected"): "acme::source::1.0" {}
    yield result = selected.output[0];
  } else {
    node fallback @id("fallback"): "acme::source::1.0" {}
    yield result = fallback.output[0];
  }
  node sink_node @id("sink"): sink { input[0] = choice.result; }
  display = sink_node;
  render = sink_node;
  output = sink_node;
}
'''
    graph = expand_control_graph(source.encode("utf-8"), SOURCE_URI, {}, {})
    provider = _h5_provider()
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v2",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 2,
        "languageVersion": "0.3",
        "projectUid": "city",
        "entrySourceUri": SOURCE_URI,
        "projectManifestDigest": _digest("control-plan-manifest"),
        "projectLockDigest": _digest("control-plan-lock"),
        "resolverPolicyDigest": _digest("control-plan-policy"),
        "limits": ControlResolverLimits().to_dict(),
        "modules": [],
    }
    return _compile_control_bundle(
        graph,
        resolved,
        entry_source_digest=_digest(source),
        catalog=provider,
        catalog_content_digest=_digest(provider.catalog.to_json()),
        catalog_fingerprint=provider.catalog.fingerprint,
        admitted_required_capabilities=("edit_scene", "run_code"),
    ).to_dict()


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
        self.global_revision = 19
        self.sync_calls = 0
        self.mutate_on_sync_call = None
        self.cancel_context = None
        self.cancel_on_sync_call = None
        self.cancel_on_plan_build = None
        self.plan_build_calls = 0

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_current_network_payload(self, root_path: str, **_kwargs):
        self.asserted_root_path = root_path
        if _kwargs.get("force_sync"):
            self.sync_calls += 1
            self.baseline["lastSyncedLiveRevision"] = self.global_revision
            if self.sync_calls == self.mutate_on_sync_call:
                self.baseline["metadata"]["artistMutation"] = True
            if self.sync_calls == self.cancel_on_sync_call:
                self.cancel_context.cancel()
        return copy.deepcopy(self.baseline)

    def _document_preview_live_catalog(self, _graph_spec_version=None):
        self.catalog_request = _graph_spec_version
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
        return True


class _Hou:
    def __init__(self, owner):
        self.undos = _Undos(owner)


class _PlanOperations(_PreviewOperations):
    decode_calls = 0

    def __init__(self, database: Path):
        self._dispatcher = _Dispatcher()
        self._settings = ServerSettings(enable_exec_tools=True)
        self._graph_store = LiveGraphStore(logging.getLogger("test.plan"), database)
        self._documents = LiveDocumentService(logging.getLogger("test.plan"), self._graph_store)
        self._monitor = _Monitor()
        self.baseline = _baseline()
        self.catalog = _catalog_provider().catalog
        self.global_revision = 19
        self.sync_calls = 0
        self.mutate_on_sync_call = None
        self.cancel_context = None
        self.cancel_on_sync_call = None
        self.cancel_on_plan_build = None
        self.plan_build_calls = 0
        self._hou = _Hou(self)
        self.target_document = None
        self.fail_execution = False

    def _require_hou(self):
        return self._hou

    @classmethod
    def _document_decode_preview_bundle(cls, bundle_value):
        cls.decode_calls += 1
        return super()._document_decode_preview_bundle(bundle_value)

    def _document_plan_bundle_impl(self, arguments, context):
        result = super()._document_plan_bundle_impl(arguments, context)
        stored = self._documents.apply_plan(result["planId"], expected_hash=result["planHash"])
        self.target_document = copy.deepcopy(stored["targetDocument"])
        return result

    def _document_build_apply_plan(self, *arguments, **keywords):
        result = super()._document_build_apply_plan(*arguments, **keywords)
        self.plan_build_calls += 1
        if self.cancel_on_plan_build == self.plan_build_calls:
            self.cancel_context.cancel()
        return result

    def _document_preflight_apply_plan(self, plan, _baseline, target=None):
        # Live template behavior is covered by runtime_mutation_integrity.
        return copy.deepcopy(plan), copy.deepcopy(target)

    def _document_execute_apply_plan(
        self, plan, baseline, *, checkpoint=None, executed=None,
    ):
        if checkpoint:
            checkpoint()
        self.baseline = copy.deepcopy(self.target_document)
        if self.fail_execution:
            self.fail_execution = False
            raise RuntimeError("injected execution failure")
        result = {
            "type": "fake_apply", "summary": copy.deepcopy(plan.get("summary", {})),
        }
        if executed is not None:
            executed.append(result)
            return executed
        return [result]


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


def _identity_symbols(
    *,
    control_symbol: str = "choice",
    branch: str = "true",
    iterator: str = "i",
    node_symbol: str = "piece",
    count: int = 2,
) -> list[str]:
    graph = _expand(
        f'''
  if {control_symbol} @id("branch-id") ({branch}) outputs (value: int) {{
    for series @id("fold-id") ({iterator} in range({count})) carry (value: int = 0) {{
      node {node_symbol} @id("node-id"): "null" {{ index = iter.{iterator}; }}
      yield value = iter.{iterator};
    }}
    yield value = series.value;
  }} else {{
    node fallback @id("node-id"): "null" {{ index = 0; }}
    yield value = 0;
  }}
'''
    )
    return [node["symbol"] for node in graph["nodes"]]
