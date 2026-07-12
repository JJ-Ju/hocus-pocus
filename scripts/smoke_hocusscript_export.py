"""Exercise HS5 live SOP export and semantic round-trip in disposable hython state.

Usage:
    hython scripts/smoke_hocusscript_export.py

The live document importer intentionally observes every Houdini parameter.  HocusScript
0.1 export, however, only claims authored fields. This smoke calls the registered live
endpoint against the force-synced network document; the endpoint itself records default
and artist-owned state as preserved rather than mutating the input document.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / "python3.11libs"
sys.path.insert(0, str(PYTHON_LIBS))

# Houdini startup can preload an installed HocusPocus package.  Keep the top-level
# package instance, but force every implementation surface used here to this checkout.
import hocuspocus
import hocuspocus.live
import hocuspocus.live.ops

for package, source in (
    (hocuspocus, PYTHON_LIBS / "hocuspocus"),
    (hocuspocus.live, PYTHON_LIBS / "hocuspocus" / "live"),
    (hocuspocus.live.ops, PYTHON_LIBS / "hocuspocus" / "live" / "ops"),
):
    source_text = str(source)
    if source_text not in package.__path__:
        package.__path__.insert(0, source_text)

for module_name in tuple(sys.modules):
    if module_name.startswith("hocuspocus.hocusscript") or module_name in {
        "hocuspocus.live.catalog_provider",
        "hocuspocus.live.context",
        "hocuspocus.live.document_service",
        "hocuspocus.live.ops.base",
        "hocuspocus.live.ops.document",
        "hocuspocus.live.ops.graph",
        "hocuspocus.live.ops.hocusscript",
    }:
        sys.modules.pop(module_name, None)

import hou  # type: ignore

from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    lower_bundle_to_document,
    resolve_graph,
)
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_cache import LiveSceneGraphCache
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.graph import GraphOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin


TARGET_PATH = "/obj/hocus_export_smoke"
GRAPH_NAME = "hocus_export_smoke"
PROJECT_UID = "hocus-export-smoke"
SOURCE_URI = "hocus-project://hocus-export-smoke/smoke.hocus"


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Dispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _Monitor:
    def __init__(self):
        self.revision = 1

    def snapshot(self):
        return {"revision": self.revision}

    def clear_scope_dirty(self, _scope):
        return None


class _MemoryGraphStore:
    def __init__(self):
        self.document = None

    def get_document_by_root_path(self, _root_path):
        return copy.deepcopy(self.document)

    def sync_needed(self, _root_path, *, live_revision):
        return True

    def last_scope_event(self, _root_path):
        return "sync"

    def upsert_document_from_live(self, document, **_kwargs):
        self.document = copy.deepcopy(document)
        return copy.deepcopy(document)


class _ExportSmokeOperations(OperationBaseMixin, GraphOperationsMixin, DocumentOperationsMixin, HocusScriptOperationsMixin):
    def __init__(self, root_path: str):
        self._root_path = root_path
        self._dispatcher = _Dispatcher()
        logger = logging.getLogger("hocus.export.smoke")
        self._monitor = _Monitor()
        self._graph = LiveSceneGraphCache(logger)
        self._graph_store = _MemoryGraphStore()
        self._documents = LiveDocumentService(logger)
        self._catalog = None

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _graph_subgraph_payload(self, snapshot: dict[str, Any], root_path: str) -> dict[str, Any]:
        if root_path != self._root_path:
            raise AssertionError(f"unexpected export target {root_path}")
        return super()._graph_subgraph_payload(snapshot, root_path)

    def _document_preview_live_catalog(self):
        # Production may cache the immutable catalog above this method. Keep this
        # smoke focused on endpoint/document integrity rather than extracting the
        # same complete Houdini catalog once per repeatability assertion.
        if self._catalog is None:
            self._catalog = super()._document_preview_live_catalog()
        return self._catalog


def _call_export_endpoint(operations: _ExportSmokeOperations) -> dict[str, Any]:
    return operations.document_export_source(
        {"root_path": TARGET_PATH, "graph_name": GRAPH_NAME}, RequestContext()
    )["structuredContent"]


def _clean_baseline(document: dict[str, Any]) -> dict[str, Any]:
    root = next(node for node in document["nodes"] if node["path"] == TARGET_PATH)
    return {
        "$schema": document["$schema"],
        "kind": "network_document",
        "documentId": document["documentId"],
        "documentRevision": document["documentRevision"],
        "baselineLiveRevision": document["baselineLiveRevision"],
        "lastSyncedLiveRevision": document["lastSyncedLiveRevision"],
        "rootPath": TARGET_PATH,
        "category": document["category"],
        "metadata": {},
        "nodes": [copy.deepcopy(root)],
        "ports": [],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


def _endpoint(value: dict[str, Any]) -> tuple[Any, ...]:
    # HOM's input1/output1 labels are UI metadata and are not stable catalog connector
    # identities.  Node identity plus the exact indexed port is the DSL wiring contract.
    return (value.get("nodeUid"), value.get("portIndex"))


def _semantic_projection(document: dict[str, Any], preserved_uids: set[str] | None = None) -> dict[str, Any]:
    """Normalize only source-representable node, connection, and output semantics."""

    nodes = [node for node in document["nodes"] if node["path"] != TARGET_PATH]
    return {
        "nodes": sorted(
            (
                node["uid"],
                node["name"],
                node["typeName"],
                node["category"],
                bool(node["flags"]["display"]),
                bool(node["flags"]["render"]),
                bool(node["flags"]["bypass"]),
                bool(node["flags"]["template"]),
            )
            for node in nodes
        ),
        "edges": sorted(
            (edge["kind"], edge["uid"], _endpoint(edge["from"]), _endpoint(edge["to"]))
            for edge in document["edges"]
            if edge["kind"] in {"data", "output_flag"}
        ),
        "bindings": sorted(
            (binding["nodeUid"], binding["parmName"], binding["valueMode"], binding.get("value"))
            for binding in document["parameterBindings"]
            if binding["uid"] not in (preserved_uids or set())
        ),
    }


def _portable_bundle(source: str, catalog) -> CompiledBundle:
    result = compile_source(source, "smoke.hocus", source_uri=SOURCE_URI)
    if not result.valid or result.graph_spec is None:
        raise RuntimeError(f"exported source failed structural compile: {result.to_dict()['diagnostics']}")
    semantic = resolve_graph(result.graph_spec, catalog)
    if not semantic.valid or not semantic.ready_for_document_lowering:
        raise RuntimeError(f"exported source failed live-catalog resolution: {semantic.to_dict()!r}")
    result.semantic_result = semantic
    result.source_kind = "project_file"
    result.project_uid = PROJECT_UID
    result.project_manifest_digest = _digest("hocus-export-smoke-manifest")
    result.project_lock_digest = _digest("hocus-export-smoke-lock")
    result.catalog_fingerprint = catalog.fingerprint
    result.catalog_content_digest = _digest(catalog.to_json())
    return CompiledBundle.from_result(result)


def main() -> int:
    print("HS5 endpoint smoke: creating disposable live network", flush=True)
    if hou.node(TARGET_PATH) is not None:
        raise RuntimeError(f"Refusing to reuse or delete existing node {TARGET_PATH}")
    root = None
    try:
        root = hou.node("/obj").createNode("geo", node_name="hocus_export_smoke")
        for child in tuple(root.children()):
            child.destroy()

        source = root.createNode("box", node_name="source")
        output = root.createNode("null", node_name="output")
        output.setInput(0, source, 0)
        source.setDisplayFlag(False)
        source.setRenderFlag(False)
        output.setDisplayFlag(True)
        output.setRenderFlag(True)

        operations = _ExportSmokeOperations(TARGET_PATH)
        for node, uid in (
            (root, "smoke.root-01"),
            (source, "smoke.source-01"),
            (output, "smoke.output-01"),
        ):
            operations._document_stamp_live_node_uid(node.path(), uid)

        print("HS5 endpoint smoke: reading exact live catalog", flush=True)
        catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
        operations._catalog = catalog

        print("HS5 endpoint smoke: calling document.export_source twice", flush=True)
        first = _call_export_endpoint(operations)
        second = _call_export_endpoint(operations)
        live_document = copy.deepcopy(operations._graph_store.document)
        if not first["valid"] or first["source"] is None:
            raise RuntimeError(f"supported live export blocked: {first['diagnostics']}")
        if first != second or first["source"].encode("utf-8") != second["source"].encode("utf-8"):
            raise RuntimeError("repeat export was not byte-deterministic")

        print("HS5 endpoint smoke: recompiling exported source", flush=True)
        bundle = _portable_bundle(first["source"], catalog)
        preview = lower_bundle_to_document(bundle, _clean_baseline(live_document))
        if not preview.valid or preview.candidate_plan is None:
            raise RuntimeError(f"exported source failed document lowering: {preview.to_dict()!r}")
        preserved_uids = {item["uid"] for item in first["provenance"]["preservedState"] if "uid" in item}
        expected = _semantic_projection(live_document, preserved_uids)
        actual = _semantic_projection(preview.document)
        if actual != expected:
            raise RuntimeError(
                "export/recompile semantic projection mismatch:\n"
                + json.dumps({"expected": expected, "actual": actual}, indent=2, sort_keys=True)
            )

        # Exercise fail-closed behavior from actual live state, not a synthetic JSON edit.
        source.bypass(True)
        operations._monitor.revision += 1
        print("HS5 endpoint smoke: verifying fail-closed bypass", flush=True)
        blocked = _call_export_endpoint(operations)
        if blocked["source"] is not None or blocked["valid"]:
            raise RuntimeError("bypassed live node produced source instead of blocking")
        blocker_codes = {item["code"] for item in blocked["diagnostics"]}
        if "HOCUS805" not in blocker_codes:
            raise RuntimeError(f"unsupported bypass did not produce HOCUS805: {sorted(blocker_codes)}")

        print(
            "HS5 live export smoke passed",
            f"houdini={hou.applicationVersionString()}",
            f"catalog={catalog.fingerprint}",
            f"sourceDigest={first['provenance']['sourceDigest']}",
            f"nodes={len(expected['nodes'])}",
            f"edges={len(expected['edges'])}",
            "repeatExport=byte-identical",
            "semanticEquivalence=true",
            "unsupportedBypass=blocked:HOCUS805",
            "filesystemWrites=false",
        )
        return 0
    finally:
        disposable = hou.node(TARGET_PATH)
        if root is not None and disposable is root:
            disposable.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
