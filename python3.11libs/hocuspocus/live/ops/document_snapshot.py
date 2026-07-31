"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import copy
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_editor_entities import (
    editor_entities_to_document,
)
from .document_editor_entities import snapshot_live_editor_entities
from .document_network_families import network_family_policy
from .document_runtime_contract import snapshot_runtime_contract


def _prune_runtime_binding_observations(
    document: dict[str, Any],
    targets: set[tuple[str, str]],
) -> None:
    """Remove redundant live parm observations covered by runtime entities."""

    removed = [
        item for item in document.get("parameterBindings", [])
        if isinstance(item, dict)
        and (item.get("nodeUid"), item.get("parmName")) in targets
    ]
    document["parameterBindings"] = [
        item for item in document.get("parameterBindings", [])
        if not (
            isinstance(item, dict)
            and (item.get("nodeUid"), item.get("parmName")) in targets
        )
    ]
    removed_code_uids = {
        item.get("codeBlobUid") for item in removed
        if isinstance(item.get("codeBlobUid"), str)
    }
    retained_code_uids = {
        item.get("codeBlobUid")
        for item in document["parameterBindings"]
        if isinstance(item, dict)
        and isinstance(item.get("codeBlobUid"), str)
    }
    orphaned = removed_code_uids - retained_code_uids
    document["codeBlobs"] = [
        item for item in document.get("codeBlobs", [])
        if not (
            isinstance(item, dict) and item.get("uid") in orphaned
        )
    ]



class DocumentSnapshotOperationsMixin:
    @staticmethod
    def _document_derived_hocus(
        hocus_by_node_uid: dict[str, dict[str, Any]],
        hocus_by_entity_uid: dict[str, dict[str, Any]],
        node_uid: str,
        entity_uid: str,
        entity_kind: str,
    ) -> dict[str, Any] | None:
        node_hocus = hocus_by_node_uid.get(node_uid)
        entity_hocus = hocus_by_entity_uid.get(entity_uid)
        if not isinstance(node_hocus, dict) or not isinstance(entity_hocus, dict):
            return None
        identity_fields = {
            "ownership", "projectUid", "bundleDigest", "compilerVersion",
            "languageVersion", "graphName", "symbol",
        }
        if (
            entity_hocus.get("entityKind") != entity_kind
            or any(
                entity_hocus.get(field) != node_hocus.get(field)
                for field in identity_fields
            )
        ):
            return None
        return copy.deepcopy(entity_hocus)

    def _document_live_node_payload(
        self, node: dict[str, Any], root_path: str
    ) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        path = str(node.get("path", "")).strip()
        node_uid, identity_mode = self._document_live_node_identity(path)
        live_node = self._safe_value(lambda: self._require_hou().node(path), None)
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
        provenance = (
            self._document_live_node_provenance(live_node, node_uid, identity_mode)
            if live_node is not None
            else None
        )
        if provenance is not None:
            metadata["hocus"] = provenance
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
                name: bool((node.get("flags") or {}).get(name, False))
                for name in ("display", "render", "bypass", "template")
            },
            "metadata": metadata,
        }
        if bool(node.get("isNetwork", False)) and path != root_path:
            payload["subnetworkDocumentId"] = f"network:{path}"
        return payload, node_uid, provenance

    def _document_live_bindings_payload(
        self,
        parms: list[dict[str, Any]],
        node_uid_by_path: dict[str, str],
        hocus_by_node_uid: dict[str, dict[str, Any]],
        hocus_by_entity_uid: dict[str, dict[str, Any]],
        typed_receipts: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        code_blobs: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        for parm in parms:
            if self._document_live_parm_is_composite_child(parm):
                continue
            node_path = str(parm.get("nodePath", "")).strip()
            node_uid = node_uid_by_path.get(
                node_path, self._document_node_uid(node_path)
            )
            code_blob = self._document_code_blob_for_parm(parm, node_uid)
            if code_blob is not None:
                code_blobs.append(code_blob)
            binding = self._document_binding_for_parm(
                parm, node_uid, code_blob["uid"] if code_blob is not None else None
            )
            manifest = hocus_by_node_uid.get(node_uid, {}).get("managedFields")
            managed = manifest.get("parameters", []) if isinstance(manifest, dict) else []
            if str(binding.get("parmName", "")) in managed:
                hocus = self._document_derived_hocus(
                    hocus_by_node_uid,
                    hocus_by_entity_uid,
                    node_uid,
                    binding["uid"],
                    "parameter_binding",
                )
                if hocus is not None:
                    binding["metadata"]["hocus"] = hocus
                    if code_blob is not None:
                        code_hocus = self._document_derived_hocus(
                            hocus_by_node_uid,
                            hocus_by_entity_uid,
                            node_uid,
                            code_blob["uid"],
                            "code_blob",
                        )
                        if code_hocus is not None:
                            code_blob["metadata"]["hocus"] = code_hocus
            binding = self._document_restore_typed_binding(
                binding,
                parm,
                typed_receipts.get(binding["uid"]),
                node_uid_by_path,
            )
            bindings.append(binding)
        return code_blobs, bindings

    def _document_live_parm_is_composite_child(
        self, parm: dict[str, Any],
    ) -> bool:
        live = self._safe_value(
            lambda: self._require_hou().parm(parm["path"]), None
        )
        parent = self._safe_value(lambda: live.parentMultiParm(), None)
        return parent is not None

    def _document_live_edges_payload(
        self,
        node_paths: set[str],
        node_uid_by_path: dict[str, str],
        hocus_by_node_uid: dict[str, dict[str, Any]],
        hocus_by_entity_uid: dict[str, dict[str, Any]],
        ignored_input_item_names: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]]:
        edges: list[dict[str, Any]] = []
        ports: dict[tuple[str, str, int], dict[str, Any]] = {}
        for dest_path in sorted(node_paths):
            for connection in self._document_live_input_connections(
                dest_path,
                ignored_input_item_names=ignored_input_item_names,
            ):
                source_path = connection["sourcePath"]
                if source_path not in node_paths:
                    continue
                source_uid, dest_uid = (
                    node_uid_by_path[source_path],
                    node_uid_by_path[dest_path],
                )
                source = {"nodeUid": source_uid, "portIndex": connection["outputIndex"]}
                dest = {"nodeUid": dest_uid, "portIndex": connection["inputIndex"]}
                if connection.get("outputName") is not None:
                    source["portName"] = str(connection["outputName"])
                if connection.get("inputName") is not None:
                    dest["portName"] = str(connection["inputName"])
                edge = {
                    "uid": f"edge:data:{dest_uid}:{connection['inputIndex']}",
                    "kind": "data",
                    "from": source,
                    "to": dest,
                    "metadata": {
                        "sourcePath": source_path,
                        "destPath": dest_path,
                        "connectionOrder": connection["connectionOrder"],
                    },
                }
                manifest = hocus_by_node_uid.get(dest_uid, {}).get("managedFields")
                managed = manifest.get("inputs", []) if isinstance(manifest, dict) else []
                if connection["inputIndex"] in managed:
                    hocus = self._document_derived_hocus(
                        hocus_by_node_uid,
                        hocus_by_entity_uid,
                        dest_uid,
                        edge["uid"],
                        "edge",
                    )
                    if hocus is not None:
                        edge["metadata"]["hocus"] = hocus
                edges.append(edge)
                for direction, node_uid, index, name in (
                    ("output", source_uid, connection["outputIndex"], connection.get("outputName")),
                    ("input", dest_uid, connection["inputIndex"], connection.get("inputName")),
                ):
                    port_uid = self._document_port_uid(node_uid, direction, index)
                    port = {
                        "uid": self._document_port_uid(node_uid, direction, index),
                        "nodeUid": node_uid,
                        "direction": direction,
                        "name": str(name or ""),
                        "index": index,
                        "kind": "data",
                        "metadata": {},
                    }
                    port_hocus = self._document_derived_hocus(
                        hocus_by_node_uid,
                        hocus_by_entity_uid,
                        dest_uid,
                        port_uid,
                        "port",
                    )
                    if port_hocus is not None:
                        port["metadata"]["hocus"] = port_hocus
                    previous = ports.get((node_uid, direction, index))
                    if (
                        previous is not None
                        and "hocus" in previous.get("metadata", {})
                        and "hocus" not in port["metadata"]
                    ):
                        port["metadata"]["hocus"] = previous["metadata"]["hocus"]
                    ports[(node_uid, direction, index)] = port
        return edges, ports

    def _document_live_network_payload(self, snapshot: dict[str, Any], root_path: str) -> dict[str, Any]:
        subgraph = self._graph_subgraph_payload(snapshot, root_path)
        nodes: list[dict[str, Any]] = []
        node_paths: set[str] = set()
        node_uid_by_path: dict[str, str] = {}
        paths_by_node_uid: dict[str, list[str]] = {}
        hocus_by_node_uid: dict[str, dict[str, Any]] = {}
        hocus_by_entity_uid = self._document_live_entity_provenance(root_path)
        for node in subgraph.get("nodes", []):
            path = str(node.get("path", "")).strip()
            if not path:
                continue
            node_paths.add(path)
            payload, node_uid, provenance = self._document_live_node_payload(
                node, root_path
            )
            paths_by_node_uid.setdefault(node_uid, []).append(path)
            if provenance is not None:
                hocus_by_node_uid[node_uid] = provenance
            nodes.append(payload)
            node_uid_by_path[path] = node_uid

        typed_receipt_table = self._document_live_typed_receipt_table(root_path)
        typed_receipts = (
            {
                item["uid"]: item
                for item in typed_receipt_table["bindings"]
            }
            if typed_receipt_table is not None else {}
        )
        editor_receipt = self._document_live_editor_receipt(root_path)
        managed_dot_names = {
            value["liveName"]
            for value in (
                editor_receipt.get("liveIdentities", {}).values()
                if isinstance(editor_receipt, dict) else ()
            )
            if value.get("kind") == "network_dot"
        }
        code_blobs, bindings = self._document_live_bindings_payload(
            subgraph.get("parms", []),
            node_uid_by_path,
            hocus_by_node_uid,
            hocus_by_entity_uid,
            typed_receipts,
        )
        edges, ports_by_key = self._document_live_edges_payload(
            node_paths,
            node_uid_by_path,
            hocus_by_node_uid,
            hocus_by_entity_uid,
            managed_dot_names,
        )

        root_snapshot = next(
            (item for item in subgraph.get("nodes", []) if str(item.get("path", "")).strip() == root_path),
            None,
        )
        root_category = (root_snapshot or {}).get("category")
        family = self._document_network_family(root_path, root_category)
        output_path = ""
        if network_family_policy(family).output_strategy == "sop_display":
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
                output_hocus = self._document_derived_hocus(
                    hocus_by_node_uid,
                    hocus_by_entity_uid,
                    output_uid,
                    output_edge["uid"],
                    "output_flag",
                )
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
            "$schema": (
                self._NETWORK_DOCUMENT_SCHEMA_URI_V2
                if (
                    editor_receipt
                    or (
                        typed_receipt_table is not None
                        and typed_receipt_table.get(
                            "documentSchema",
                            self._NETWORK_DOCUMENT_SCHEMA_URI_V2,
                        ) == self._NETWORK_DOCUMENT_SCHEMA_URI_V2
                    )
                )
                else self._NETWORK_DOCUMENT_SCHEMA_URI
            ),
            "kind": "network_document",
            "documentId": f"network:{root_path}",
            "documentRevision": int(snapshot.get("revision") or 0),
            "baselineLiveRevision": int(snapshot.get("revision") or 0),
            "lastSyncedLiveRevision": int(snapshot.get("revision") or 0),
            "rootPath": root_path,
            "category": root_category or "Unknown",
            "metadata": {
                "graphRevision": snapshot.get("revision"),
                "graphStats": subgraph.get("stats", {}),
                "identityMode": "persistent_user_data",
                "networkFamily": family,
            },
            "nodes": sorted(nodes, key=lambda item: item["path"]),
            "ports": sorted(ports_by_key.values(), key=lambda item: item["uid"]),
            "edges": sorted(edges, key=lambda item: item["uid"]),
            "parameterBindings": sorted(bindings, key=lambda item: item["uid"]),
            "codeBlobs": sorted(code_blobs, key=lambda item: item["uid"]),
            "diagnostics": identity_diagnostics,
        }
        if editor_receipt is not None:
            root = self._safe_value(
                lambda: self._require_hou().node(root_path), None
            )
            if root is not None:
                identities = {
                    (value["kind"], value["liveName"]): uid
                    for uid, value in editor_receipt[
                        "liveIdentities"
                    ].items()
                }
                hou_module = self._require_hou()
                display_comment = self._safe_value(
                    lambda: hou_module.nodeFlag.DisplayComment, None
                )
                editor_entities = snapshot_live_editor_entities(
                    root,
                    node_uid_by_path=node_uid_by_path,
                    identity_by_live_name=identities,
                    provenance_by_uid=editor_receipt["provenance"],
                    layout_constraints=editor_receipt["layoutConstraints"],
                    display_comment_flag=display_comment,
                )
                document.update(editor_entities_to_document(editor_entities))
        (
            spare_parameters,
            animations,
            runtime_diagnostics,
            runtime_binding_targets,
        ) = (
            snapshot_runtime_contract(self, document)
        )
        _prune_runtime_binding_observations(
            document, runtime_binding_targets
        )
        if spare_parameters or animations or runtime_diagnostics:
            document["$schema"] = self._NETWORK_DOCUMENT_SCHEMA_URI_V2
            document["spareParameters"] = spare_parameters
            document["animations"] = animations
            document["diagnostics"].extend(runtime_diagnostics)
        expansion = self._document_live_expansion_provenance(root_path)
        if expansion is not None:
            document["metadata"]["hocusExpansion"] = expansion
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
