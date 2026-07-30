"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import copy
import json
from typing import Any

from hocuspocus.hocusscript.document_editor_entities import (
    DocumentEditorEntityError,
    diff_editor_entities,
    editor_entities_from_document,
)

from ..context import RequestContext


class DocumentDiffOperationsMixin:
    _BINDING_VALUE_FIELDS = {
        "valueMode", "value", "menuToken", "expression",
        "expressionLanguage", "channelReference", "pathKind", "raw",
        "magnitude", "unit", "dimension", "canonicalMagnitude",
        "canonicalUnit", "rampKind", "points", "basis", "instances",
        "instanceStart", "fieldContract", "codeBlobUid",
    }

    @staticmethod
    def _document_nodes_by_path(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("path")): node
            for node in document.get("nodes", [])
            if isinstance(node, dict) and str(node.get("path", "")).startswith("/")
        }

    @staticmethod
    def _document_node_uid_by_path(document: dict[str, Any]) -> dict[str, str]:
        return {
            str(node.get("path")): str(node.get("uid"))
            for node in document.get("nodes", [])
            if isinstance(node, dict) and str(node.get("path", "")).startswith("/") and str(node.get("uid", "")).strip()
        }

    @staticmethod
    def _document_bindings_by_key(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        bindings: dict[tuple[str, str], dict[str, Any]] = {}
        for binding in document.get("parameterBindings", []):
            if not isinstance(binding, dict):
                continue
            key = (str(binding.get("nodeUid", "")).strip(), str(binding.get("parmName", "")).strip())
            bindings[key] = binding
        return bindings

    @staticmethod
    def _document_code_blobs_by_uid(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(blob.get("uid")): blob
            for blob in document.get("codeBlobs", [])
            if isinstance(blob, dict) and str(blob.get("uid", "")).strip()
        }

    @staticmethod
    def _document_path_is_within(path: str, root_path: str) -> bool:
        if path == root_path:
            return True
        return bool(root_path) and path.startswith(f"{root_path}/")

    @staticmethod
    def _document_prune_descendant_paths(paths: list[str]) -> list[str]:
        roots: list[str] = []
        for path in sorted({str(item).strip() for item in paths if str(item).strip()}, key=lambda item: item.count("/")):
            if any(path == root or path.startswith(f"{root}/") for root in roots):
                continue
            roots.append(path)
        return sorted(roots, key=lambda item: item.count("/"), reverse=True)

    @staticmethod
    def _document_data_edge_uid_map(document: dict[str, Any]) -> dict[str, dict[int, str | None]]:
        inputs: dict[str, dict[int, str | None]] = {}
        for edge in document.get("edges", []):
            if not isinstance(edge, dict) or str(edge.get("kind")) != "data":
                continue
            source_uid = str((edge.get("from") or {}).get("nodeUid", "")).strip()
            dest_uid = str((edge.get("to") or {}).get("nodeUid", "")).strip()
            dest_index = int((edge.get("to") or {}).get("portIndex", 0))
            if not dest_uid:
                continue
            inputs.setdefault(dest_uid, {})[dest_index] = source_uid or None
        return inputs

    @staticmethod
    def _document_data_connection_map(document: dict[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
        connections: dict[str, dict[int, dict[str, Any]]] = {}
        for edge in document.get("edges", []):
            if not isinstance(edge, dict) or str(edge.get("kind")) != "data":
                continue
            source = edge.get("from") or {}
            dest = edge.get("to") or {}
            dest_uid = str(dest.get("nodeUid", "")).strip()
            if not dest_uid:
                continue
            dest_index = int(dest.get("portIndex", 0))
            connections.setdefault(dest_uid, {})[dest_index] = {
                "sourceUid": str(source.get("nodeUid", "")).strip() or None,
                "sourceOutputIndex": int(source.get("portIndex", 0)),
                "sourceOutputName": source.get("portName"),
                "destInputName": dest.get("portName"),
                "connectionOrder": int((edge.get("metadata") or {}).get("connectionOrder", dest_index)),
            }
        return connections

    def _document_data_edge_map(self, document: dict[str, Any]) -> dict[str, dict[int, str | None]]:
        node_uid_to_path = {
            str(node.get("uid", "")).strip(): str(node.get("path", "")).strip()
            for node in document.get("nodes", [])
            if isinstance(node, dict)
        }
        inputs: dict[str, dict[int, str | None]] = {}
        for dest_uid, slots in self._document_data_edge_uid_map(document).items():
            dest_path = node_uid_to_path.get(dest_uid)
            if not dest_path:
                continue
            for dest_index, source_uid in slots.items():
                inputs.setdefault(dest_path, {})[dest_index] = node_uid_to_path.get(source_uid) if source_uid else None
        return inputs

    def _document_path_change_inherited_only(
        self,
        uid: str,
        before_nodes_by_uid: dict[str, dict[str, Any]],
        after_nodes_by_uid: dict[str, dict[str, Any]],
        before_path_to_uid: dict[str, str],
        after_path_to_uid: dict[str, str],
        structural_changed_uids: set[str],
    ) -> bool:
        before_node = before_nodes_by_uid.get(uid)
        after_node = after_nodes_by_uid.get(uid)
        if before_node is None or after_node is None:
            return False
        if str(before_node.get("name", "")).strip() != str(after_node.get("name", "")).strip():
            return False
        before_parent_uid = before_path_to_uid.get(str(before_node.get("parentPath", "")).strip())
        after_parent_uid = after_path_to_uid.get(str(after_node.get("parentPath", "")).strip())
        if not before_parent_uid or before_parent_uid != after_parent_uid:
            return False
        if before_parent_uid not in structural_changed_uids:
            return False
        before_parent = before_nodes_by_uid.get(before_parent_uid)
        after_parent = after_nodes_by_uid.get(after_parent_uid)
        if before_parent is None or after_parent is None:
            return False
        before_path = str(before_node.get("path", "")).strip()
        after_path = str(after_node.get("path", "")).strip()
        before_parent_path = str(before_parent.get("path", "")).strip()
        after_parent_path = str(after_parent.get("path", "")).strip()
        if not self._document_path_is_within(before_path, before_parent_path) or not self._document_path_is_within(after_path, after_parent_path):
            return False
        return before_path[len(before_parent_path):] == after_path[len(after_parent_path):]

    @staticmethod
    def _document_diff_is_clean(diff: dict[str, Any]) -> bool:
        summary = diff.get("summary") if isinstance(diff, dict) else {}
        if not isinstance(summary, dict):
            return False
        for key, value in summary.items():
            if key.endswith("Count") and int(value or 0) != 0:
                return False
        return True

    @staticmethod
    def _document_changed_nodes(
        before_nodes: dict[str, dict[str, Any]],
        after_nodes: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        changed: list[dict[str, Any]] = []
        renamed = reparented = retyped = 0
        shared = sorted(
            set(before_nodes) & set(after_nodes),
            key=lambda uid: str(after_nodes[uid].get("path", "")),
        )
        for uid in shared:
            before, after = before_nodes[uid], after_nodes[uid]
            changes = {
                key: {"before": before.get(key), "after": after.get(key)}
                for key in (
                    "path", "name", "typeName", "parentPath", "position", "flags",
                    "subnetworkDocumentId",
                )
                if before.get(key) != after.get(key)
            }
            if not changes:
                continue
            renamed += int("name" in changes or ("path" in changes and "parentPath" not in changes))
            reparented += int("parentPath" in changes)
            retyped += int("typeName" in changes)
            changed.append(
                {
                    "uid": uid,
                    "beforePath": before.get("path"),
                    "afterPath": after.get("path"),
                    "changes": changes,
                }
            )
        return changed, renamed, reparented, retyped

    @staticmethod
    def _document_changed_bindings(
        before: dict[tuple[str, str], dict[str, Any]],
        after: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            before_item, after_item = before.get(key), after.get(key)
            if before_item is None:
                changed.append({"changeType": "created", "after": after_item})
            elif after_item is None:
                changed.append({"changeType": "deleted", "before": before_item})
            else:
                before_state = DocumentDiffOperationsMixin._document_binding_value_state(
                    before_item
                )
                after_state = DocumentDiffOperationsMixin._document_binding_value_state(
                    after_item
                )
                fields = sorted(set(before_state) | set(after_state))
                changes = {
                    field: {
                        "before": before_state.get(field),
                        "after": after_state.get(field),
                    }
                    for field in fields
                    if before_state.get(field) != after_state.get(field)
                }
                if changes:
                    changed.append(
                        {
                            "changeType": "updated",
                            "bindingUid": after_item.get("uid"),
                            "changes": changes,
                        }
                    )
        return changed

    @classmethod
    def _document_binding_value_state(
        cls, binding: dict[str, Any],
    ) -> dict[str, Any]:
        state = {
            field: copy.deepcopy(binding[field])
            for field in cls._BINDING_VALUE_FIELDS
            if field in binding
        }
        metadata = binding.get("metadata")
        selection = (
            metadata.get("parameterSelection")
            if isinstance(metadata, dict) else None
        )
        if isinstance(selection, dict):
            state["parameterSelection"] = copy.deepcopy(selection)
        return state

    @staticmethod
    def _document_changed_code_blobs(
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        for uid in sorted(set(before) | set(after)):
            before_item, after_item = before.get(uid), after.get(uid)
            if before_item is None:
                changed.append({"changeType": "created", "after": after_item})
            elif after_item is None:
                changed.append({"changeType": "deleted", "before": before_item})
            else:
                changes = {
                    field: {"before": before_item.get(field), "after": after_item.get(field)}
                    for field in ("language", "target", "body")
                    if before_item.get(field) != after_item.get(field)
                }
                if changes:
                    changed.append(
                        {"changeType": "updated", "codeBlobUid": uid, "changes": changes}
                    )
        return changed

    @staticmethod
    def _document_changed_runtime_entities(
        before: Any,
        after: Any,
    ) -> list[dict[str, Any]]:
        before_by_uid = {
            str(item.get("uid")): item
            for item in before
            if isinstance(item, dict) and str(item.get("uid", "")).strip()
        } if isinstance(before, list) else {}
        after_by_uid = {
            str(item.get("uid")): item
            for item in after
            if isinstance(item, dict) and str(item.get("uid", "")).strip()
        } if isinstance(after, list) else {}
        changed: list[dict[str, Any]] = []
        for uid in sorted(set(before_by_uid) | set(after_by_uid)):
            old, new = before_by_uid.get(uid), after_by_uid.get(uid)
            if old == new:
                continue
            changed.append({
                "changeType": (
                    "created" if old is None
                    else "deleted" if new is None
                    else "updated"
                ),
                "uid": uid,
                "before": copy.deepcopy(old),
                "after": copy.deepcopy(new),
            })
        return changed

    @staticmethod
    def _document_editor_diff_projection(
        document: dict[str, Any],
    ) -> dict[str, Any]:
        projected = copy.deepcopy(document)
        for collection in (
            "networkBoxes", "stickyNotes", "nodeComments", "networkDots",
            "layoutConstraints",
        ):
            for entity in projected.get(collection, []):
                metadata = (
                    entity.get("metadata")
                    if isinstance(entity, dict) else None
                )
                if isinstance(metadata, dict):
                    metadata.pop("liveName", None)
        return projected

    def _document_diff_payload(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_nodes = self._document_nodes_by_uid(before)
        after_nodes = self._document_nodes_by_uid(after)
        before_bindings = self._document_bindings_by_key(before)
        after_bindings = self._document_bindings_by_key(after)
        before_code_blobs = self._document_code_blobs_by_uid(before)
        after_code_blobs = self._document_code_blobs_by_uid(after)
        before_edges = {json.dumps(edge, sort_keys=True): edge for edge in before.get("edges", []) if isinstance(edge, dict)}
        after_edges = {json.dumps(edge, sort_keys=True): edge for edge in after.get("edges", []) if isinstance(edge, dict)}

        created_nodes = sorted(
            [after_nodes[uid] for uid in set(after_nodes) - set(before_nodes)],
            key=lambda item: str(item.get("path", "")),
        )
        deleted_nodes = sorted(
            [before_nodes[uid] for uid in set(before_nodes) - set(after_nodes)],
            key=lambda item: str(item.get("path", "")),
        )
        changed_nodes, renamed_node_count, reparented_node_count, retyped_node_count = (
            self._document_changed_nodes(before_nodes, after_nodes)
        )
        changed_bindings = self._document_changed_bindings(before_bindings, after_bindings)

        created_edges = [after_edges[key] for key in sorted(set(after_edges) - set(before_edges))]
        deleted_edges = [before_edges[key] for key in sorted(set(before_edges) - set(after_edges))]
        changed_code_blobs = self._document_changed_code_blobs(
            before_code_blobs, after_code_blobs
        )
        changed_spares = self._document_changed_runtime_entities(
            before.get("spareParameters", []),
            after.get("spareParameters", []),
        )
        changed_animations = self._document_changed_runtime_entities(
            before.get("animations", []), after.get("animations", []),
        )
        try:
            editor_diff = diff_editor_entities(
                editor_entities_from_document(
                    self._document_editor_diff_projection(before)
                ),
                editor_entities_from_document(
                    self._document_editor_diff_projection(after)
                ),
            )
        except DocumentEditorEntityError:
            editor_diff = {
                "summary": {
                    "createdCount": 0,
                    "changedCount": 1,
                    "deletedCount": 0,
                },
                "created": [],
                "changed": [{"uid": None, "kind": "invalid"}],
                "deleted": [],
            }
        return {
            "summary": {
                "createdNodeCount": len(created_nodes),
                "deletedNodeCount": len(deleted_nodes),
                "changedNodeCount": len(changed_nodes),
                "renamedNodeCount": renamed_node_count,
                "reparentedNodeCount": reparented_node_count,
                "retypedNodeCount": retyped_node_count,
                "changedBindingCount": len(changed_bindings),
                "changedCodeBlobCount": len(changed_code_blobs),
                "changedSpareParameterCount": len(changed_spares),
                "changedAnimationCount": len(changed_animations),
                "createdEdgeCount": len(created_edges),
                "deletedEdgeCount": len(deleted_edges),
                "createdEditorEntityCount": editor_diff[
                    "summary"
                ]["createdCount"],
                "changedEditorEntityCount": editor_diff[
                    "summary"
                ]["changedCount"],
                "deletedEditorEntityCount": editor_diff[
                    "summary"
                ]["deletedCount"],
            },
            "createdNodes": created_nodes,
            "deletedNodes": deleted_nodes,
            "changedNodes": changed_nodes,
            "changedParameterBindings": changed_bindings,
            "changedCodeBlobs": changed_code_blobs,
            "changedSpareParameters": changed_spares,
            "changedAnimations": changed_animations,
            "createdEdges": created_edges,
            "deletedEdges": deleted_edges,
            "editorEntities": editor_diff,
        }

    @staticmethod
    def _document_project_unmanaged_positions(
        authored_nodes: dict[str, dict[str, Any]],
        projected_live: dict[str, Any],
    ) -> None:
        for node in projected_live.get("nodes", []):
            expected = authored_nodes.get(str(node.get("uid", "")))
            if expected is not None and expected.get("position") is None:
                node["position"] = None

    def _document_project_verified_resets(
        self,
        projected_authored: dict[str, Any],
        projected_live: dict[str, Any],
    ) -> None:
        live_bindings = self._document_bindings_by_key(projected_live)
        for binding in projected_authored.get("parameterBindings", []):
            if (
                not isinstance(binding, dict)
                or binding.get("valueMode") != "reset"
            ):
                continue
            key = (
                str(binding.get("nodeUid", "")).strip(),
                str(binding.get("parmName", "")).strip(),
            )
            observed = live_bindings.get(key)
            metadata = (
                observed.get("metadata")
                if isinstance(observed, dict) else None
            )
            if (
                isinstance(metadata, dict)
                and metadata.get("isAtDefault") is True
            ):
                binding.clear()
                binding.update(copy.deepcopy(observed))

    @staticmethod
    def _document_project_runtime_contract(
        authored: dict[str, Any],
        projected_authored: dict[str, Any],
        live: dict[str, Any],
        projected_live: dict[str, Any],
    ) -> None:
        for collection in ("spareParameters", "animations"):
            authored_uids = {
                str(item.get("uid", "")).strip()
                for item in authored.get(collection, [])
                if isinstance(item, dict)
            }
            projected_live[collection] = [
                item for item in live.get(collection, [])
                if isinstance(item, dict)
                and str(item.get("uid", "")).strip() in authored_uids
            ]
            if collection not in projected_authored:
                projected_authored[collection] = []

    def _document_verification_diff_payload(self, authored: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
        """Compare live state only against parameter values authored by the source.

        Network documents imported from Houdini contain every observed parameter,
        while a lowered source document intentionally contains only authored
        bindings. Unauthored live/default values are therefore outside the
        verification contract and must not appear as residual changes.
        """
        authored_keys = set(self._document_bindings_by_key(authored))
        authored_code_blob_uids = {
            str(binding.get("codeBlobUid", "")).strip()
            for binding in authored.get("parameterBindings", [])
            if isinstance(binding, dict) and str(binding.get("codeBlobUid", "")).strip()
        }
        projected_authored = copy.deepcopy(authored)
        projected_live = copy.deepcopy(live)
        projected_live["parameterBindings"] = [
            binding
            for binding in live.get("parameterBindings", [])
            if isinstance(binding, dict)
            and (str(binding.get("nodeUid", "")).strip(), str(binding.get("parmName", "")).strip()) in authored_keys
        ]
        projected_live["codeBlobs"] = [
            blob
            for blob in live.get("codeBlobs", [])
            if isinstance(blob, dict) and str(blob.get("uid", "")).strip() in authored_code_blob_uids
        ]
        self._document_project_runtime_contract(
            authored, projected_authored, live, projected_live
        )
        self._document_project_verified_resets(
            projected_authored, projected_live
        )
        authored_nodes = self._document_nodes_by_uid(authored)
        self._document_project_unmanaged_positions(
            authored_nodes, projected_live
        )

        def edge_contract(edge: dict[str, Any], template: dict[str, Any] | None = None) -> dict[str, Any]:
            reference = template or edge
            result: dict[str, Any] = {
                "uid": edge.get("uid"),
                "kind": edge.get("kind"),
                "from": {},
                "to": {},
                "metadata": {},
            }
            for endpoint_name in ("from", "to"):
                actual = edge.get(endpoint_name) if isinstance(edge.get(endpoint_name), dict) else {}
                expected = reference.get(endpoint_name) if isinstance(reference.get(endpoint_name), dict) else {}
                endpoint = result[endpoint_name]
                for field in ("nodeUid", "portIndex"):
                    if field in expected:
                        endpoint[field] = actual.get(field)
                if "portName" in expected:
                    endpoint["portName"] = actual.get("portName")
            expected_metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
            if "connectionOrder" in expected_metadata:
                actual_metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
                result["metadata"]["connectionOrder"] = actual_metadata.get("connectionOrder")
            return result

        authored_edges = {
            str(edge.get("uid", "")): edge
            for edge in authored.get("edges", [])
            if isinstance(edge, dict) and str(edge.get("uid", ""))
        }
        projected_authored["edges"] = [edge_contract(edge) for edge in authored_edges.values()]
        projected_live["edges"] = [
            edge_contract(edge, authored_edges.get(str(edge.get("uid", ""))))
            for edge in live.get("edges", [])
            if isinstance(edge, dict)
        ]
        diff = self._document_diff_payload(projected_authored, projected_live)
        expected_expansion = self._document_expansion_from_metadata(authored)
        actual_expansion = self._document_expansion_from_metadata(live)
        expansion_changed = expected_expansion != actual_expansion
        diff["summary"]["changedDocumentMetadataCount"] = int(expansion_changed)
        diff["changedDocumentMetadata"] = (
            {
                "hocusExpansion": {
                    "before": copy.deepcopy(expected_expansion),
                    "after": copy.deepcopy(actual_expansion),
                }
            }
            if expansion_changed
            else {}
        )
        live_nodes = self._document_nodes_by_uid(live)
        provenance_fields = (
            "version", "entityKind", "projectUid", "sourceUri", "sourceDigest",
            "bundleDigest", "compilerVersion", "languageVersion", "graphName",
            "symbol", "ownership", "jsonPointer", "span", "originId",
            "originKind", "relatedOrigins", "stackId", "controlStackId",
            "managedFields",
        )
        changed_by_uid = {item.get("uid"): item for item in diff["changedNodes"]}
        for uid, expected_node in authored_nodes.items():
            expected_metadata = expected_node.get("metadata") if isinstance(expected_node.get("metadata"), dict) else {}
            expected_hocus = expected_metadata.get("hocus") if isinstance(expected_metadata.get("hocus"), dict) else None
            actual_node = live_nodes.get(uid, {})
            actual_metadata = actual_node.get("metadata") if isinstance(actual_node.get("metadata"), dict) else {}
            actual_hocus = actual_metadata.get("hocus") if isinstance(actual_metadata.get("hocus"), dict) else None
            if expected_hocus is None and actual_hocus is None:
                continue
            expected_contract = (
                {field: copy.deepcopy(expected_hocus.get(field)) for field in provenance_fields}
                if expected_hocus is not None else None
            )
            actual_contract = (
                {field: copy.deepcopy(actual_hocus.get(field)) for field in provenance_fields}
                if actual_hocus is not None else None
            )
            if expected_contract == actual_contract:
                continue
            change = {"before": expected_contract, "after": actual_contract}
            existing = changed_by_uid.get(uid)
            if existing is None:
                existing = {
                    "uid": uid,
                    "beforePath": expected_node.get("path"),
                    "afterPath": actual_node.get("path"),
                    "changes": {},
                }
                diff["changedNodes"].append(existing)
                changed_by_uid[uid] = existing
            existing["changes"]["hocusProvenance"] = change
        diff["changedNodes"].sort(key=lambda item: str(item.get("afterPath", "")))
        diff["summary"]["changedNodeCount"] = len(diff["changedNodes"])
        return diff

    def _document_diff_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        document = payload["document"]
        baseline = payload["baseline"]
        if baseline is None:
            root_path = str(document.get("rootPath", "")).strip()
            if document.get("kind") == "network_document" and root_path:
                baseline = self._document_current_network_payload(root_path)
            else:
                baseline = {}
        diff = self._document_diff_payload(baseline, document)
        return {
            "checkoutId": payload["checkoutId"],
            "documentId": document.get("documentId"),
            "rootPath": document.get("rootPath"),
            "baselineDocumentRevision": baseline.get("documentRevision"),
            "targetDocumentRevision": document.get("documentRevision"),
            "diff": diff,
        }

    def document_diff(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_diff_impl(arguments), context)
        return self._tool_response("Computed a document diff.", data)

    def _document_query_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip()
        if root_path:
            document = self._document_current_network_payload(root_path)
            document_revision = document.get("documentRevision")
        else:
            scene = self._document_sync_scene_scope(sync_root_networks=True)
            document_revision = scene.get("documentRevision")
        store_result = self._graph_store.query_nodes(arguments)
        matches: list[dict[str, Any]] = []
        for node in store_result.get("matches", []):
            path = str(node.get("path", "")).strip()
            if not path:
                continue
            node_root_path = str(node.get("rootPath", "")).strip() or path
            encoded_root = node_root_path.strip("/")
            matches.append(
                {
                    "node": {
                        **node,
                        "uid": str(node.get("uid", "")).strip() or self._document_node_uid(path),
                    },
                    "rootPath": node_root_path,
                    "documentUri": f"houdini://documents/network/{encoded_root}" if encoded_root else "houdini://documents/network/%2F",
                }
            )
        return {
            "count": len(matches),
            "documentRevision": document_revision,
            "matches": matches,
        }

    def document_query(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_query_impl(arguments), context)
        return self._tool_response(f"Matched {data['count']} document graph node(s).", data)
