"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import copy
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError



class DocumentSnapshotOperationsMixin:
    def _document_live_network_payload(self, snapshot: dict[str, Any], root_path: str) -> dict[str, Any]:
        subgraph = self._graph_subgraph_payload(snapshot, root_path)
        nodes: list[dict[str, Any]] = []
        node_paths: set[str] = set()
        node_uid_by_path: dict[str, str] = {}
        paths_by_node_uid: dict[str, list[str]] = {}
        hocus_by_node_uid: dict[str, dict[str, Any]] = {}
        for node in subgraph.get("nodes", []):
            path = str(node.get("path", "")).strip()
            if not path:
                continue
            node_paths.add(path)
            node_uid, identity_mode = self._document_live_node_identity(path)
            paths_by_node_uid.setdefault(node_uid, []).append(path)
            live_node = self._safe_value(lambda path=path: self._require_hou().node(path), None)
            metadata = {
                "graphPath": path,
                "childCount": node.get("childCount", 0),
                "identityMode": identity_mode,
                "inputs": copy.deepcopy(node.get("inputs", [])),
                "displayNodePath": node.get("displayNodePath"),
                "renderNodePath": node.get("renderNodePath"),
                "outputNodePath": node.get("outputNodePath"),
                "outputNodePaths": copy.deepcopy(node.get("outputNodePaths", [])),
                "materialPath": node.get("materialPath"),
                "fileOutputs": copy.deepcopy(node.get("fileOutputs", [])),
            }
            if path == root_path:
                metadata["isDocumentRoot"] = True
            if live_node is not None:
                hocus_provenance = self._document_live_node_provenance(live_node, node_uid, identity_mode)
                if hocus_provenance is not None:
                    metadata["hocus"] = hocus_provenance
                    hocus_by_node_uid[node_uid] = hocus_provenance
            payload = {
                "uid": node_uid,
                "name": node.get("name"),
                "typeName": node.get("typeName"),
                "category": node.get("category"),
                "path": path,
                "parentPath": node.get("parentPath"),
                "isNetwork": bool(node.get("isNetwork", False)),
                "position": node.get("position"),
                "flags": {
                    "display": bool((node.get("flags") or {}).get("display", False)),
                    "render": bool((node.get("flags") or {}).get("render", False)),
                    "bypass": bool((node.get("flags") or {}).get("bypass", False)),
                    "template": bool((node.get("flags") or {}).get("template", False)),
                },
                "metadata": metadata,
            }
            if bool(node.get("isNetwork", False)) and path != root_path:
                payload["subnetworkDocumentId"] = f"network:{path}"
            nodes.append(payload)
            node_uid_by_path[path] = node_uid

        code_blobs: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []

        def derived_hocus(node_uid: str, entity_kind: str) -> dict[str, Any] | None:
            node_hocus = hocus_by_node_uid.get(node_uid)
            if not isinstance(node_hocus, dict):
                return None
            return {
                key: copy.deepcopy(value)
                for key, value in node_hocus.items()
                if key in {
                    "ownership", "projectUid", "sourceUri", "sourceDigest", "bundleDigest",
                    "compilerVersion", "graphName", "symbol",
                }
            } | {"entityKind": entity_kind}

        for parm in subgraph.get("parms", []):
            node_uid = node_uid_by_path.get(str(parm.get("nodePath", "")).strip(), self._document_node_uid(str(parm.get("nodePath", "")).strip()))
            code_blob = self._document_code_blob_for_parm(parm, node_uid)
            code_blob_uid = None
            if code_blob is not None:
                code_blobs.append(code_blob)
                code_blob_uid = code_blob["uid"]
            binding = self._document_binding_for_parm(parm, node_uid, code_blob_uid)
            manifest = hocus_by_node_uid.get(node_uid, {}).get("managedFields")
            managed_parameters = manifest.get("parameters", []) if isinstance(manifest, dict) else []
            if str(binding.get("parmName", "")) in managed_parameters:
                binding_hocus = derived_hocus(node_uid, "parameter_binding")
                if binding_hocus is not None:
                    binding["metadata"]["hocus"] = binding_hocus
                    if code_blob is not None:
                        code_blob["metadata"]["hocus"] = derived_hocus(node_uid, "code_blob")
            bindings.append(binding)

        edges: list[dict[str, Any]] = []
        ports_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
        for dest_path in sorted(node_paths):
            for connection in self._document_live_input_connections(dest_path):
                source_path = connection["sourcePath"]
                if source_path not in node_paths:
                    continue
                source_endpoint: dict[str, Any] = {
                    "nodeUid": node_uid_by_path[source_path],
                    "portIndex": connection["outputIndex"],
                }
                dest_endpoint: dict[str, Any] = {
                    "nodeUid": node_uid_by_path[dest_path],
                    "portIndex": connection["inputIndex"],
                }
                if connection.get("outputName") is not None:
                    source_endpoint["portName"] = str(connection["outputName"])
                if connection.get("inputName") is not None:
                    dest_endpoint["portName"] = str(connection["inputName"])
                edge = {
                        "uid": f"edge:data:{node_uid_by_path[dest_path]}:{connection['inputIndex']}",
                        "kind": "data",
                        "from": source_endpoint,
                        "to": dest_endpoint,
                        "metadata": {
                            "sourcePath": source_path,
                            "destPath": dest_path,
                            "connectionOrder": connection["connectionOrder"],
                        },
                    }
                dest_uid = node_uid_by_path[dest_path]
                manifest = hocus_by_node_uid.get(dest_uid, {}).get("managedFields")
                managed_inputs = manifest.get("inputs", []) if isinstance(manifest, dict) else []
                if connection["inputIndex"] in managed_inputs:
                    edge_hocus = derived_hocus(dest_uid, "edge")
                    if edge_hocus is not None:
                        edge["metadata"]["hocus"] = edge_hocus
                edges.append(edge)
                for direction, node_uid, index, name in (
                    ("output", node_uid_by_path[source_path], connection["outputIndex"], connection.get("outputName")),
                    ("input", node_uid_by_path[dest_path], connection["inputIndex"], connection.get("inputName")),
                ):
                    key = (node_uid, direction, index)
                    ports_by_key[key] = {
                        "uid": self._document_port_uid(node_uid, direction, index),
                        "nodeUid": node_uid,
                        "direction": direction,
                        "name": str(name or ""),
                        "index": index,
                        "kind": "data",
                        "metadata": {},
                    }

        root_snapshot = next(
            (item for item in subgraph.get("nodes", []) if str(item.get("path", "")).strip() == root_path),
            None,
        )
        output_path = str(
            (root_snapshot or {}).get("outputNodePath")
            or (root_snapshot or {}).get("displayNodePath")
            or ""
        ).strip()
        if output_path in node_uid_by_path:
            root_uid = node_uid_by_path[root_path]
            output_uid = node_uid_by_path[output_path]
            output_edge = {
                "uid": f"edge:output:{root_uid}",
                "kind": "output_flag",
                "from": {"nodeUid": output_uid},
                "to": {"nodeUid": root_uid},
                "metadata": {"sourcePath": output_path, "destPath": root_path},
            }
            manifest = hocus_by_node_uid.get(output_uid, {}).get("managedFields")
            managed_flags = manifest.get("flags", {}) if isinstance(manifest, dict) else {}
            if managed_flags.get("output") is True:
                output_hocus = derived_hocus(output_uid, "output_flag")
                if output_hocus is not None:
                    output_edge["metadata"]["hocus"] = output_hocus
            edges.append(output_edge)

        identity_diagnostics = [
            {
                "severity": "error",
                "code": "node.uid.live_duplicate",
                "message": f"Persistent node uid is present on multiple live nodes: {uid}",
                "entityUid": uid,
                "details": {"paths": sorted(paths)},
            }
            for uid, paths in sorted(paths_by_node_uid.items())
            if uid and len(paths) > 1
        ]

        document = {
            "$schema": self._NETWORK_DOCUMENT_SCHEMA_URI,
            "kind": "network_document",
            "documentId": f"network:{root_path}",
            "documentRevision": int(snapshot.get("revision") or 0),
            "baselineLiveRevision": int(snapshot.get("revision") or 0),
            "lastSyncedLiveRevision": int(snapshot.get("revision") or 0),
            "rootPath": root_path,
            "category": next((node.get("category") for node in subgraph.get("nodes", []) if node.get("path") == root_path), None) or "Unknown",
            "metadata": {
                "graphRevision": snapshot.get("revision"),
                "graphStats": subgraph.get("stats", {}),
                "identityMode": "persistent_user_data",
            },
            "nodes": sorted(nodes, key=lambda item: item["path"]),
            "ports": sorted(ports_by_key.values(), key=lambda item: item["uid"]),
            "edges": sorted(edges, key=lambda item: item["uid"]),
            "parameterBindings": sorted(bindings, key=lambda item: item["uid"]),
            "codeBlobs": sorted(code_blobs, key=lambda item: item["uid"]),
            "diagnostics": identity_diagnostics,
        }
        document["diagnostics"] = self._document_clean_diagnostics(
            document["diagnostics"] + self._document_validate_network_document(document)
        )
        return document

    def _document_live_scene_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        scene_summary = self._scene_summary_impl()
        root_networks: list[dict[str, Any]] = []
        for path in sorted(snapshot.get("topLevelPaths", [])):
            node = next((item for item in snapshot.get("nodes", []) if item.get("path") == path), None)
            if node is None or not bool(node.get("isNetwork", False)):
                continue
            encoded = path.strip("/")
            root_networks.append(
                {
                    "documentId": f"network:{path}",
                    "path": path,
                    "uri": f"houdini://documents/network/{encoded}",
                    "category": node.get("category"),
                    "typeName": node.get("typeName"),
                }
            )
        return {
            "$schema": self._SCENE_DOCUMENT_SCHEMA_URI,
            "kind": "scene_document",
            "documentId": "scene:/",
            "documentRevision": int(snapshot.get("revision") or 0),
            "rootNetworks": root_networks,
            "metadata": {
                "graphRevision": snapshot.get("revision"),
                "graphStats": snapshot.get("stats", {}),
                "hipFilePath": scene_summary.get("hipFilePath"),
                "hipDirty": scene_summary.get("hipDirty"),
                "selection": scene_summary.get("selection"),
            },
        }

    def _document_top_level_network_paths(self, snapshot: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        for path in sorted(snapshot.get("topLevelPaths", [])):
            node = next((item for item in snapshot.get("nodes", []) if item.get("path") == path), None)
            if node is None or not bool(node.get("isNetwork", False)):
                continue
            paths.append(path)
        return paths

    def _document_sync_scene_scope(self, *, force: bool = False, sync_root_networks: bool = False) -> dict[str, Any]:
        live_revision = int(self._monitor.snapshot()["revision"])
        existing = self._graph_store.get_document_by_id("scene:/")
        if existing is not None and not force and not sync_root_networks and not self._graph_store.sync_needed("scene:/", live_revision=live_revision):
            return existing
        snapshot = self._graph_snapshot()
        if force or existing is None or self._graph_store.sync_needed("scene:/", live_revision=live_revision):
            scene_document = self._document_live_scene_payload(snapshot)
            event_name = self._graph_store.last_scope_event(None) or "sync"
            stored_scene = self._graph_store.upsert_document_from_live(
                scene_document,
                live_revision=live_revision,
                source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
            )
        else:
            stored_scene = existing
        if sync_root_networks:
            for path in self._document_top_level_network_paths(snapshot):
                if force or self._graph_store.sync_needed(path, live_revision=live_revision):
                    network_document = self._document_live_network_payload(snapshot, path)
                    event_name = self._graph_store.last_scope_event(path) or "sync"
                    self._graph_store.upsert_document_from_live(
                        network_document,
                        live_revision=live_revision,
                        source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
                    )
                    self._monitor.clear_scope_dirty(path)
        self._monitor.clear_scope_dirty("scene:/")
        return stored_scene

    def _document_current_network_payload(self, root_path: str, *, force_sync: bool = False) -> dict[str, Any]:
        live_revision = int(self._monitor.snapshot()["revision"])
        existing = self._graph_store.get_document_by_root_path(root_path)
        if existing is not None and not force_sync and not self._graph_store.sync_needed(root_path, live_revision=live_revision):
            return existing
        snapshot = self._graph_snapshot()
        live_document = self._document_live_network_payload(snapshot, root_path)
        event_name = self._graph_store.last_scope_event(root_path) or "sync"
        stored = self._graph_store.upsert_document_from_live(
            live_document,
            live_revision=live_revision,
            source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
        )
        self._monitor.clear_scope_dirty(root_path)
        return stored

    def _document_checkout_target(self, arguments: dict[str, Any]) -> dict[str, Any]:
        checkout_id = str(arguments.get("checkout_id", "")).strip()
        supplied_document = arguments.get("document")
        if checkout_id:
            if supplied_document is not None:
                if not isinstance(supplied_document, dict):
                    raise JsonRpcError(INVALID_PARAMS, "document must be an object.")
                snapshot = self._documents.update_working_document(checkout_id, supplied_document)
                if snapshot is None:
                    raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
            working = self._documents.working_document(checkout_id)
            if working is None:
                raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
            return {
                "checkoutId": checkout_id,
                "document": working,
                "baseline": self._documents.baseline_document(checkout_id),
            }
        if supplied_document is None or not isinstance(supplied_document, dict):
            raise JsonRpcError(INVALID_PARAMS, "Provide either checkout_id or document.")
        return {"checkoutId": None, "document": supplied_document, "baseline": None}
