"""Run the HS3 bundle-preview smoke test in hython without altering an existing scene.

Usage:
    hython scripts/smoke_hocusscript_preview.py
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / "python3.11libs"
sys.path.insert(0, str(PYTHON_LIBS))

# Houdini startup may preload the installed package. Prefer this checkout for
# submodules while retaining the already-running top-level package instance.
import hocuspocus
import hocuspocus.live
import hocuspocus.live.ops

source_package = str(PYTHON_LIBS / "hocuspocus")
source_live = str(PYTHON_LIBS / "hocuspocus" / "live")
source_ops = str(PYTHON_LIBS / "hocuspocus" / "live" / "ops")
if source_package not in hocuspocus.__path__:
    hocuspocus.__path__.insert(0, source_package)
if source_live not in hocuspocus.live.__path__:
    hocuspocus.live.__path__.insert(0, source_live)
if source_ops not in hocuspocus.live.ops.__path__:
    hocuspocus.live.ops.__path__.insert(0, source_ops)

import hou  # type: ignore

from hocuspocus.hocusscript import CompiledBundle, compile_source, resolve_graph
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class _SmokeOperations(OperationBaseMixin, DocumentOperationsMixin, HocusScriptOperationsMixin):
    def __init__(self, snapshot, root_path, catalog):
        self._snapshot = snapshot
        self._root_path = root_path
        self._catalog = catalog
        self._documents = LiveDocumentService(logging.getLogger("hocus.preview.smoke"))

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_current_network_payload(self, root_path: str, **_kwargs):
        if root_path != self._root_path:
            raise AssertionError(f"unexpected preview target {root_path}")
        return self._document_live_network_payload(self._snapshot, root_path)

    def _graph_subgraph_payload(self, snapshot, root_path):
        if root_path != self._root_path:
            raise AssertionError(f"unexpected subgraph target {root_path}")
        return snapshot

    def _document_preview_live_catalog(self):
        return self._catalog


def main() -> int:
    target_path = "/obj/hocus_preview_smoke"
    if hou.node(target_path) is not None:
        raise RuntimeError(f"Refusing to reuse or delete existing node {target_path}")
    root = hou.node("/obj").createNode("geo", node_name="hocus_preview_smoke")
    try:
        for child in tuple(root.children()):
            child.destroy()
        live = root.createNode("null", node_name="live")
        artist = root.createNode("null", node_name="artist")
        artist.setInput(0, live, 0)
        artist.setDisplayFlag(True)
        catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
        provisional = _SmokeOperations({}, target_path, catalog)
        provenance_span = {
            "sourceUri": "hocus-project://live-preview/previous.hocus",
            "start": {"line": 1, "column": 1, "offset": 0},
            "end": {"line": 1, "column": 2, "offset": 1},
        }
        provisional._document_stamp_live_node_metadata(live.path(), {
            "uid": "live-preview-external",
            "metadata": {"hocus": {
                "version": 1,
                "entityKind": "node",
                "projectUid": "live-preview",
                "sourceUri": "hocus-project://live-preview/previous.hocus",
                "sourceDigest": _digest("previous-source"),
                "bundleDigest": _digest("previous-bundle"),
                "compilerVersion": "0.2.0",
                "languageVersion": "0.1",
                "graphName": "previous",
                "symbol": "live",
                "ownership": "studio.preview",
                "jsonPointer": "/nodes/0",
                "span": provenance_span,
            }},
        })
        source = f'''hocus 0.1;
graph live_preview {{
  target "{target_path}";
  category Sop;
  mode merge;
  ownership "studio.preview";
  adopt live = "{live.path()}";
  node output: "null" {{ input[0] = live; }}
  display = output;
  render = output;
  output = output;
  layout = auto;
}}
'''
        source_uri = "hocus-project://live-preview/smoke.hocus"
        result = compile_source(source, "smoke.hocus", source_uri=source_uri)
        if not result.valid or result.graph_spec is None:
            raise RuntimeError(f"structural compile failed: {result.to_dict()['diagnostics']}")
        semantic = resolve_graph(result.graph_spec, catalog)
        if not semantic.valid or semantic.ready_for_document_lowering:
            raise RuntimeError(f"expected a valid deferred external result: {semantic.to_dict()!r}")
        result.semantic_result = semantic
        result.source_kind = "project_file"
        result.project_uid = "live-preview"
        result.project_manifest_digest = _digest("live-preview-manifest")
        result.project_lock_digest = _digest("live-preview-lock")
        result.catalog_fingerprint = catalog.fingerprint
        result.catalog_content_digest = _digest(catalog.to_json())
        bundle = CompiledBundle.from_result(result)

        operations = _SmokeOperations({}, target_path, catalog)
        snapshot = {
            "revision": 1,
            "stats": {},
            "nodes": [operations._node_summary(node) for node in (root, live, artist)],
            "parms": [],
            "edges": [],
        }
        operations._snapshot = snapshot
        before = {
            "children": tuple((child.path(), tuple(item.path() if item is not None else None for item in child.inputs())) for child in root.children()),
            "userData": {node.path(): dict(node.userDataDict()) for node in (root, live, artist)},
            "positions": {node.path(): tuple(float(value) for value in node.position()) for node in (root, live, artist)},
            "flags": {node.path(): (node.isDisplayFlagSet(), node.isRenderFlagSet()) for node in (live, artist)},
            "hipDirty": hou.hipFile.hasUnsavedChanges(),
        }
        payload = operations._document_preview_bundle_impl(bundle.to_dict())
        after = {
            "children": tuple((child.path(), tuple(item.path() if item is not None else None for item in child.inputs())) for child in root.children()),
            "userData": {node.path(): dict(node.userDataDict()) for node in (root, live, artist)},
            "positions": {node.path(): tuple(float(value) for value in node.position()) for node in (root, live, artist)},
            "flags": {node.path(): (node.isDisplayFlagSet(), node.isRenderFlagSet()) for node in (live, artist)},
            "hipDirty": hou.hipFile.hasUnsavedChanges(),
        }
        if before != after:
            raise RuntimeError(f"preview mutated Houdini state: before={before!r} after={after!r}")
        if not payload["valid"] or not payload["readyForPlan"] or payload["readyForApply"]:
            raise RuntimeError(f"unexpected preview gates: {payload!r}")
        preview_nodes = {item["uid"]: item for item in payload["preview"]["document"]["nodes"]}
        if "live-preview-external" not in preview_nodes:
            raise RuntimeError("persistent external UID/provenance was not recovered by the live importer")
        data_edges = [item for item in payload["preview"]["document"]["edges"] if item["kind"] == "data"]
        if len(data_edges) < 2:
            raise RuntimeError(f"expected imported and authored SOP connections: {data_edges!r}")
        print(
            "HS3 live preview smoke passed",
            f"catalog={catalog.fingerprint}",
            f"plan={payload['preview']['candidatePlan']['planHash']}",
            f"operations={payload['summary']['operationCount']}",
            "houdiniMutation=false",
        )
        return 0
    finally:
        if root is not None:
            root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
