"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import copy
import time
from typing import Any, Callable
from uuid import uuid4

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class DocumentApplyOperationsMixin:
    def _document_apply_state(self, baseline: dict[str, Any]) -> dict[str, Any]:
        return {
            "uidToPath": {
                str(node.get("uid", "")).strip(): str(node.get("path", "")).strip()
                for node in baseline.get("nodes", [])
                if isinstance(node, dict) and str(node.get("uid", "")).strip() and str(node.get("path", "")).strip()
            }
        }

    @staticmethod
    def _document_apply_state_current_path(state: dict[str, Any], uid: str, fallback_path: str | None = None) -> str | None:
        return str((state.get("uidToPath", {}) or {}).get(uid) or fallback_path or "").strip() or None

    def _document_apply_state_register(self, state: dict[str, Any], uid: str, path: str) -> None:
        uid = str(uid or "").strip()
        path = str(path or "").strip()
        if uid and path:
            state.setdefault("uidToPath", {})[uid] = path

    def _document_apply_state_remove_prefix(self, state: dict[str, Any], path_prefix: str) -> None:
        prefix = str(path_prefix or "").strip()
        if not prefix:
            return
        uid_to_path = state.setdefault("uidToPath", {})
        for uid, path in list(uid_to_path.items()):
            if path == prefix or path.startswith(f"{prefix}/"):
                uid_to_path.pop(uid, None)

    def _document_apply_state_replace_prefix(self, state: dict[str, Any], old_prefix: str, new_prefix: str) -> None:
        old_prefix = str(old_prefix or "").strip()
        new_prefix = str(new_prefix or "").strip()
        if not old_prefix or not new_prefix or old_prefix == new_prefix:
            return
        uid_to_path = state.setdefault("uidToPath", {})
        for uid, path in list(uid_to_path.items()):
            if path == old_prefix:
                uid_to_path[uid] = new_prefix
            elif path.startswith(f"{old_prefix}/"):
                uid_to_path[uid] = f"{new_prefix}{path[len(old_prefix):]}"

    def _document_create_live_node(self, node: dict[str, Any]) -> dict[str, Any]:
        target_path = str(node.get("path", "")).strip()
        parent_path = str(node.get("parentPath", "")).strip()
        if not target_path or not parent_path:
            raise JsonRpcError(INVALID_PARAMS, "Document create operations require both path and parentPath.")
        node_name = str(node.get("name", "")).strip() or target_path.rsplit("/", 1)[-1]
        created = self._node_create_impl(
            {
                "parent_path": parent_path,
                "node_type_name": node.get("typeName"),
                "node_name": node_name,
            }
        )
        if created.get("path") != target_path:
            created = self._node_rename_impl({"path": created["path"], "new_name": node_name, "unique_name": False})
        self._document_stamp_live_node_metadata(str(created.get("path", "")).strip(), node)
        return created

    def _document_reparent_live_node(
        self,
        *,
        path: str,
        new_parent_path: str,
        new_name: str,
    ) -> dict[str, Any]:
        hou_module = self._require_hou()
        node = self._require_node_by_path(path)
        parent = self._require_node_by_path(new_parent_path, label="new_parent_path")
        mover = getattr(hou_module, "moveNodesTo", None)
        moved_node = None
        if callable(mover):
            moved = mover((node,), parent)
            if moved:
                moved_node = moved[0]
        if moved_node is None:
            copier = getattr(hou_module, "copyNodesTo", None)
            if not callable(copier):
                raise JsonRpcError(INVALID_PARAMS, "This Houdini session does not expose a node reparent helper.")
            copied = copier((node,), parent)
            if copied:
                moved_node = copied[0]
            if moved_node is None:
                raise JsonRpcError(INVALID_PARAMS, f"Failed to reparent node {path} to {new_parent_path}.")
            node.destroy()
        desired_name = str(new_name or "").strip()
        if desired_name and moved_node.name() != desired_name:
            moved_node.setName(desired_name, unique_name=False)
        return self._node_summary(moved_node)

    def _document_move_live_node(self, path: str, position: list[float]) -> None:
        """Set an authored document position without mutating global grid bookkeeping."""
        node = self._require_node_by_path(path)
        hou_module = self._require_hou()
        node.setPosition(hou_module.Vector2((float(position[0]), float(position[1]))))

    def _document_binding_parm_path(self, state: dict[str, Any], entry: dict[str, Any]) -> str:
        node_uid = str(entry.get("nodeUid", "")).strip()
        parm_name = str(entry.get("parmName", "")).strip()
        node_path = self._document_apply_state_current_path(state, node_uid, str(entry.get("nodePath", "")).strip())
        if not node_path or not parm_name:
            raise JsonRpcError(INVALID_PARAMS, "Could not resolve the live parm target for a document apply operation.")
        return f"{node_path}/{parm_name}"

    @staticmethod
    def _document_entity_ownership(entity: dict[str, Any]) -> str | None:
        metadata = entity.get("metadata")
        hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
        ownership = hocus.get("ownership") if isinstance(hocus, dict) else None
        normalized = str(ownership or "").strip()
        return normalized or None

    def _document_reconcile_ownerships(self, document: dict[str, Any]) -> set[str]:
        metadata = document.get("metadata")
        preview = metadata.get("hocusPreview") if isinstance(metadata, dict) else None
        preview_ownership = preview.get("ownership") if isinstance(preview, dict) else None
        explicit_ownership = metadata.get("reconcileOwnership") if isinstance(metadata, dict) else None
        requested = {
            str(value).strip()
            for value in (preview_ownership, explicit_ownership)
            if str(value or "").strip()
        }
        return requested if len(requested) == 1 else set()

    def _document_plan_connection_changes(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        mode: str,
        target_nodes_by_uid: dict[str, dict[str, Any]],
        create_uids: set[str],
        structural_changed_uids: set[str],
    ) -> list[dict[str, Any]]:
        baseline_inputs = self._document_data_connection_map(baseline)
        target_inputs = self._document_data_connection_map(target)
        force_connection_dest_uids = {
            dest_uid
            for dest_uid, desired in target_inputs.items()
            if dest_uid in create_uids
            or dest_uid in structural_changed_uids
            or any(
                connection.get("sourceUid") in structural_changed_uids
                for connection in desired.values()
                if connection.get("sourceUid")
            )
        }
        connection_changes: list[dict[str, Any]] = []
        if mode == "reconcile":
            dest_uids = sorted(target_nodes_by_uid, key=lambda item: str(target_nodes_by_uid[item].get("path", "")))
        else:
            dest_uids = sorted(target_inputs, key=lambda item: str(target_nodes_by_uid.get(item, {}).get("path", "")))
        for dest_uid in dest_uids:
            current = baseline_inputs.get(dest_uid, {})
            desired = target_inputs.get(dest_uid, {})
            if mode == "merge":
                for index, connection in sorted(desired.items()):
                    if dest_uid in force_connection_dest_uids or current.get(index) != connection:
                        source_uid = connection.get("sourceUid")
                        connection_changes.append(
                            {
                                "destUid": dest_uid,
                                "destPath": str(target_nodes_by_uid.get(dest_uid, {}).get("path", "")).strip(),
                                "inputIndex": index,
                                "sourceUid": source_uid,
                                "sourcePath": str(target_nodes_by_uid.get(source_uid, {}).get("path", "")).strip() if source_uid else None,
                                **{key: connection.get(key) for key in ("sourceOutputIndex", "sourceOutputName", "destInputName", "connectionOrder")},
                            }
                        )
                continue
            max_index = max(list(current.keys()) + list(desired.keys()), default=-1)
            for index in range(max_index + 1):
                if dest_uid in force_connection_dest_uids or current.get(index) != desired.get(index):
                    connection = desired.get(index)
                    source_uid = connection.get("sourceUid") if connection else None
                    connection_changes.append(
                        {
                            "destUid": dest_uid,
                            "destPath": str(target_nodes_by_uid.get(dest_uid, {}).get("path", "")).strip(),
                            "inputIndex": index,
                            "sourceUid": source_uid,
                            "sourcePath": str(target_nodes_by_uid.get(source_uid, {}).get("path", "")).strip() if source_uid else None,
                            **(
                                {key: connection.get(key) for key in ("sourceOutputIndex", "sourceOutputName", "destInputName", "connectionOrder")}
                                if connection
                                else {"sourceOutputIndex": 0, "sourceOutputName": None, "destInputName": None, "connectionOrder": index}
                            ),
                        }
                    )

        return connection_changes

    def _document_plan_binding_changes(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        target_nodes_by_uid: dict[str, dict[str, Any]],
        baseline_nodes_by_uid: dict[str, dict[str, Any]],
        create_uids: set[str],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        baseline_code_blobs = self._document_code_blobs_by_uid(baseline)
        baseline_bindings = self._document_bindings_by_key(baseline)
        target_bindings = self._document_bindings_by_key(target)
        code_blobs = self._document_code_blobs_by_uid(target)
        parameter_resets: list[dict[str, Any]] = []
        parameter_assignments: list[dict[str, Any]] = []
        expression_updates: list[dict[str, Any]] = []
        code_blob_installs: list[dict[str, Any]] = []
        forced_binding_uids = set(create_uids)

        identity_updates = [
            {
                "uid": uid,
                "path": str(target_node.get("path", "")).strip(),
                "metadata": copy.deepcopy(target_node.get("metadata", {})),
            }
            for uid, target_node in sorted(target_nodes_by_uid.items())
            if uid in baseline_nodes_by_uid
            and str(((target_node.get("metadata") or {}).get("hocus") or {}).get("entityKind", "")) == "adopted_node"
            and (
                str((baseline_nodes_by_uid[uid].get("metadata") or {}).get("identityMode", "")) != "persistent_user_data"
                or (baseline_nodes_by_uid[uid].get("metadata") or {}).get("hocus")
                != (target_node.get("metadata") or {}).get("hocus")
            )
        ]
        identity_clears = [
            {
                "uid": uid,
                "path": str(target_node.get("path", "")).strip(),
            }
            for uid, target_node in sorted(target_nodes_by_uid.items())
            if uid in baseline_nodes_by_uid
            and isinstance((baseline_nodes_by_uid[uid].get("metadata") or {}).get("hocus"), dict)
            and not isinstance((target_node.get("metadata") or {}).get("hocus"), dict)
        ]

        def _binding_sort_key(item: tuple[tuple[str, str], dict[str, Any]]) -> tuple[str, str]:
            node_uid, parm_name = item[0]
            return (str(target_nodes_by_uid.get(node_uid, {}).get("path", "")), parm_name)

        for key, binding in sorted(target_bindings.items(), key=_binding_sort_key):
            node_uid, parm_name = key
            node_payload = target_nodes_by_uid.get(node_uid)
            if node_payload is None:
                continue
            force_install = node_uid in forced_binding_uids
            entry = {
                "bindingUid": str(binding.get("uid", "")).strip(),
                "nodeUid": node_uid,
                "nodePath": str(node_payload.get("path", "")).strip(),
                "parmName": parm_name,
                "metadata": copy.deepcopy(binding.get("metadata", {})) if isinstance(binding.get("metadata"), dict) else {},
            }
            value_mode = str(binding.get("valueMode", "")).strip()
            binding_unchanged = baseline_bindings.get(key) == binding
            if value_mode == "code_reference":
                code_blob_uid = str(binding.get("codeBlobUid", "")).strip()
                blob = code_blobs.get(code_blob_uid, {})
                blob_changed = baseline_code_blobs.get(code_blob_uid) != blob
                if not force_install and binding_unchanged and not blob_changed:
                    continue
                language = self._document_normalize_language(blob.get("language"))
                code_blob_installs.append(
                    {
                        **entry,
                        "codeBlobUid": code_blob_uid,
                        "language": language,
                        "adapter": self._document_code_adapter_for(node_payload.get("typeName"), parm_name, language),
                        "body": blob.get("body", ""),
                    }
                )
                continue
            if not force_install and binding_unchanged:
                continue
            if value_mode == "literal":
                parameter_assignments.append({**entry, "value": binding.get("value")})
                continue
            if value_mode == "expression":
                expression_updates.append(
                    {
                        **entry,
                        "expression": binding.get("expression"),
                        "expressionLanguage": self._document_normalize_language(binding.get("expressionLanguage") or "hscript"),
                    }
                )
                continue
            if value_mode == "channel_reference":
                expression = str(binding.get("expression") or "").strip()
                language = self._document_normalize_language(binding.get("expressionLanguage") or "hscript")
                if not expression:
                    expression, language = self._document_compile_channel_reference(binding.get("channelReference"), entry["metadata"])
                expression_updates.append(
                    {
                        **entry,
                        "expression": expression,
                        "expressionLanguage": language,
                        "channelReference": binding.get("channelReference"),
                    }
                )
                continue

        # Parameter bindings are sparse authored intent in every apply mode.
        # Omission means preserve live/default state; a future explicit reset
        # value form may populate parameterResets without overloading omission.

        return (
            parameter_assignments,
            expression_updates,
            code_blob_installs,
            identity_updates,
            identity_clears,
            parameter_resets,
        )

    def _document_build_apply_plan(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        baseline_nodes_by_uid = self._document_nodes_by_uid(baseline)
        target_nodes_by_uid = self._document_nodes_by_uid(target)
        baseline_path_to_uid = self._document_node_uid_by_path(baseline)
        target_path_to_uid = self._document_node_uid_by_path(target)
        root_path = str(target.get("rootPath", "")).strip()
        root_uid = target_path_to_uid.get(root_path) or baseline_path_to_uid.get(root_path)
        intersection_uids = set(baseline_nodes_by_uid) & set(target_nodes_by_uid)
        structural_changed_uids = {
            uid
            for uid in intersection_uids
            if any(
                baseline_nodes_by_uid[uid].get(key) != target_nodes_by_uid[uid].get(key)
                for key in ("path", "name", "parentPath", "typeName")
            )
        }
        replace_root_uids = {
            uid
            for uid in intersection_uids
            if uid != root_uid and baseline_nodes_by_uid[uid].get("typeName") != target_nodes_by_uid[uid].get("typeName")
        }
        replace_before_paths = [str(baseline_nodes_by_uid[uid].get("path", "")).strip() for uid in replace_root_uids]
        recreated_descendant_uids = {
            uid
            for uid in intersection_uids
            if uid not in replace_root_uids
            and any(
                self._document_path_is_within(str(baseline_nodes_by_uid[uid].get("path", "")).strip(), prefix)
                and str(baseline_nodes_by_uid[uid].get("path", "")).strip() != prefix
                for prefix in replace_before_paths
            )
        }
        create_uids = ({uid for uid in target_nodes_by_uid if uid not in baseline_nodes_by_uid} | replace_root_uids | recreated_descendant_uids) - ({root_uid} if root_uid else set())
        target_created_nodes = [
            copy.deepcopy(target_nodes_by_uid[uid])
            for uid in create_uids
            if uid in target_nodes_by_uid and str(target_nodes_by_uid[uid].get("path", "")).strip() != root_path
        ]
        create_networks = sorted(
            [node for node in target_created_nodes if bool(node.get("isNetwork", False))],
            key=lambda item: str(item.get("path", "")).count("/"),
        )
        create_leaf_nodes = sorted(
            [node for node in target_created_nodes if not bool(node.get("isNetwork", False))],
            key=lambda item: str(item.get("path", "")).count("/"),
        )

        rename_nodes: list[dict[str, Any]] = []
        reparent_nodes: list[dict[str, Any]] = []
        for uid in sorted(intersection_uids, key=lambda item: str(baseline_nodes_by_uid[item].get("path", "")).count("/")):
            if uid == root_uid or uid in create_uids or uid in replace_root_uids:
                continue
            before_node = baseline_nodes_by_uid[uid]
            after_node = target_nodes_by_uid[uid]
            if self._document_path_change_inherited_only(
                uid,
                baseline_nodes_by_uid,
                target_nodes_by_uid,
                baseline_path_to_uid,
                target_path_to_uid,
                structural_changed_uids,
            ):
                continue
            before_path = str(before_node.get("path", "")).strip()
            after_path = str(after_node.get("path", "")).strip()
            before_parent_uid = baseline_path_to_uid.get(str(before_node.get("parentPath", "")).strip())
            after_parent_uid = target_path_to_uid.get(str(after_node.get("parentPath", "")).strip())
            target_name = str(after_node.get("name", "")).strip() or after_path.rsplit("/", 1)[-1]
            if before_parent_uid != after_parent_uid:
                reparent_nodes.append(
                    {
                        "uid": uid,
                        "currentPath": before_path,
                        "targetPath": after_path,
                        "targetParentPath": str(after_node.get("parentPath", "")).strip(),
                        "targetName": target_name,
                    }
                )
                continue
            if before_path != after_path or str(before_node.get("name", "")).strip() != target_name:
                rename_nodes.append(
                    {
                        "uid": uid,
                        "currentPath": before_path,
                        "targetPath": after_path,
                        "targetName": target_name,
                    }
                )

        connection_changes = self._document_plan_connection_changes(
            baseline,
            target,
            mode,
            target_nodes_by_uid,
            create_uids,
            structural_changed_uids,
        )
        (
            parameter_assignments,
            expression_updates,
            code_blob_installs,
            identity_updates,
            identity_clears,
            parameter_resets,
        ) = self._document_plan_binding_changes(
            baseline,
            target,
            target_nodes_by_uid,
            baseline_nodes_by_uid,
            create_uids,
        )

        node_updates: list[dict[str, Any]] = []
        for uid, target_node in sorted(target_nodes_by_uid.items(), key=lambda item: str(item[1].get("path", ""))):
            if str(target_node.get("path", "")).strip() == root_path:
                continue
            baseline_node = baseline_nodes_by_uid.get(uid)
            force_update = uid in create_uids
            flags = copy.deepcopy(target_node.get("flags", {}))
            position = copy.deepcopy(target_node.get("position"))
            if force_update:
                if flags or position is not None:
                    node_updates.append({"uid": uid, "path": target_node.get("path"), "flags": flags, "position": position})
                continue
            if baseline_node is not None:
                update: dict[str, Any] = {"uid": uid, "path": target_node.get("path")}
                if baseline_node.get("flags") != target_node.get("flags"):
                    update["flags"] = flags
                if baseline_node.get("position") != target_node.get("position"):
                    update["position"] = position
                if len(update) > 2:
                    node_updates.append(update)

        def output_source_uid(document: dict[str, Any]) -> str | None:
            for edge in document.get("edges", []):
                if not isinstance(edge, dict) or edge.get("kind") != "output_flag":
                    continue
                destination = edge.get("to") if isinstance(edge.get("to"), dict) else {}
                if destination.get("nodeUid") == root_uid:
                    source = edge.get("from") if isinstance(edge.get("from"), dict) else {}
                    return str(source.get("nodeUid", "")).strip() or None
            return None

        baseline_output_uid = output_source_uid(baseline)
        target_output_uid = output_source_uid(target)
        target_display_uids = sorted(
            uid for uid, node in target_nodes_by_uid.items()
            if uid != root_uid and bool((node.get("flags") or {}).get("display", False))
        )
        output_guard = {
            "sourceUid": target_output_uid,
            "targetDisplayUids": target_display_uids,
        }
        output_change = None
        if baseline_output_uid != target_output_uid:
            output_change = {
                "rootUid": root_uid,
                "rootPath": root_path,
                "beforeSourceUid": baseline_output_uid,
                "sourceUid": target_output_uid,
                "sourcePath": (
                    str(target_nodes_by_uid.get(target_output_uid, {}).get("path", "")).strip()
                    if target_output_uid
                    else None
                ),
                "targetDisplayUids": target_display_uids,
            }

        replace_nodes = [
            {
                "uid": uid,
                "currentPath": str(baseline_nodes_by_uid[uid].get("path", "")).strip(),
                "target": copy.deepcopy(target_nodes_by_uid[uid]),
            }
            for uid in sorted(replace_root_uids, key=lambda item: str(baseline_nodes_by_uid[item].get("path", "")).count("/"), reverse=True)
        ]
        delete_nodes: list[dict[str, Any]] = []
        protected_delete_nodes: list[dict[str, Any]] = []
        if mode == "reconcile":
            omitted_candidates = [
                {"uid": uid, "currentPath": str(node.get("path", "")).strip()}
                for uid, node in baseline_nodes_by_uid.items()
                if uid != root_uid
                and uid not in target_nodes_by_uid
                and not any(
                    self._document_path_is_within(str(node.get("path", "")).strip(), prefix)
                    and str(node.get("path", "")).strip() != prefix
                    for prefix in replace_before_paths
                )
            ]
            reconcile_ownerships = self._document_reconcile_ownerships(target)
            delete_candidates = [
                item
                for item in omitted_candidates
                if self._document_entity_ownership(baseline_nodes_by_uid[item["uid"]]) in reconcile_ownerships
            ]
            protected_delete_nodes = [item for item in omitted_candidates if item not in delete_candidates]
            pruned_delete_paths = self._document_prune_descendant_paths([item["currentPath"] for item in delete_candidates])
            delete_nodes = [next(item for item in delete_candidates if item["currentPath"] == path) for path in pruned_delete_paths]

        return {
            "networkFamily": self._document_network_family(root_path, target.get("category")),
            "rootNodeGuard": (
                {
                    "uid": root_uid,
                    "path": root_path,
                    "flags": copy.deepcopy(target_nodes_by_uid[root_uid].get("flags", {})),
                }
                if root_uid in target_nodes_by_uid and any(update.get("flags") for update in node_updates)
                else None
            ),
            "replaceNodes": replace_nodes,
            "createNetworkContainers": create_networks,
            "createNodes": create_leaf_nodes,
            "renameNodes": rename_nodes,
            "reparentNodes": reparent_nodes,
            "connectionChanges": connection_changes,
            "parameterResets": parameter_resets,
            "parameterAssignments": parameter_assignments,
            "expressionUpdates": expression_updates,
            "codeBlobInstalls": code_blob_installs,
            "identityUpdates": identity_updates,
            "identityClears": identity_clears,
            "nodeUpdates": node_updates,
            "outputGuard": output_guard,
            "outputChange": output_change,
            "deleteNodes": delete_nodes,
            "protectedDeleteNodes": protected_delete_nodes,
            "summary": {
                "replaceNodeCount": len(replace_nodes),
                "createNetworkContainerCount": len(create_networks),
                "createNodeCount": len(create_leaf_nodes),
                "renameNodeCount": len(rename_nodes),
                "reparentNodeCount": len(reparent_nodes),
                "connectionChangeCount": len(connection_changes),
                "parameterResetCount": len(parameter_resets),
                "parameterAssignmentCount": len(parameter_assignments),
                "expressionUpdateCount": len(expression_updates),
                "codeBlobInstallCount": len(code_blob_installs),
                "identityUpdateCount": len(identity_updates),
                "identityClearCount": len(identity_clears),
                "nodeUpdateCount": len(node_updates),
                "outputChangeCount": 1 if output_change is not None else 0,
                "deleteNodeCount": len(delete_nodes),
                "protectedDeleteNodeCount": len(protected_delete_nodes),
            },
        }

    def _document_execute_identity_changes(
        self,
        plan: dict[str, Any],
        state: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        for update in plan.get("identityUpdates", []):
            checkpoint()
            current_path = self._document_apply_state_current_path(
                state,
                str(update.get("uid", "")).strip(),
                str(update.get("path", "")).strip(),
            )
            if not current_path:
                continue
            self._document_stamp_live_node_metadata(current_path, update)
            executed.append({"type": "stamp_node_uid", "uid": update.get("uid"), "path": current_path})
        for update in plan.get("identityClears", []):
            checkpoint()
            current_path = self._document_apply_state_current_path(
                state, str(update.get("uid", "")).strip(), str(update.get("path", "")).strip()
            )
            if not current_path:
                continue
            self._document_clear_live_node_metadata(current_path)
            executed.append({"type": "clear_node_identity", "uid": update.get("uid"), "path": current_path})

    def _document_execute_node_updates(
        self,
        updates: list[dict[str, Any]],
        state: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        for update in updates:
            checkpoint()
            current_path = self._document_apply_state_current_path(
                state,
                str(update.get("uid", "")).strip(),
                str(update.get("path", "")).strip(),
            )
            if not current_path:
                continue
            flags = update.get("flags") or {}
            if flags:
                self._node_set_flags_impl(
                    {
                        "path": current_path,
                        "bypass": bool(flags.get("bypass", False)),
                        "display": bool(flags.get("display", False)),
                        "render": bool(flags.get("render", False)),
                        "template": bool(flags.get("template", False)),
                    }
                )
                executed.append({"type": "set_flags", "uid": update.get("uid"), "path": current_path})
            position = update.get("position")
            if isinstance(position, list) and len(position) == 2:
                self._document_move_live_node(current_path, position)
                executed.append({"type": "move_node", "uid": update.get("uid"), "path": current_path})

    def _document_execute_apply_plan(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> list[dict[str, Any]]:
        state = self._document_apply_state(baseline)
        executed: list[dict[str, Any]] = []

        def check_cancelled() -> None:
            if checkpoint is not None:
                checkpoint()

        self._document_execute_identity_changes(plan, state, executed, check_cancelled)

        for operation in plan.get("replaceNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if current_path:
                self._node_delete_impl({"path": current_path, "ignore_missing": True})
                self._document_apply_state_remove_prefix(state, current_path)
                executed.append({"type": "replace_delete_node", "uid": operation.get("uid"), "path": current_path})
            created = self._document_create_live_node(operation.get("target", {}))
            self._document_apply_state_register(state, str(operation.get("uid", "")).strip(), str(created.get("path", "")).strip())
            executed.append({"type": "replace_create_node", "uid": operation.get("uid"), "path": created.get("path"), "nodeTypeName": created.get("typeName")})

        for group_name in ("createNetworkContainers", "createNodes"):
            for node in plan.get(group_name, []):
                check_cancelled()
                created = self._document_create_live_node(node)
                self._document_apply_state_register(state, str(node.get("uid", "")).strip(), str(created.get("path", "")).strip())
                executed.append({"type": "create_node", "uid": node.get("uid"), "path": created.get("path"), "nodeTypeName": created.get("typeName")})

        for operation in plan.get("renameNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            renamed = self._node_rename_impl({"path": current_path, "new_name": operation.get("targetName"), "unique_name": False})
            new_path = str(renamed.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current_path, new_path)
            executed.append({"type": "rename_node", "uid": operation.get("uid"), "fromPath": current_path, "path": new_path})

        for operation in plan.get("reparentNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            moved = self._document_reparent_live_node(
                path=current_path,
                new_parent_path=str(operation.get("targetParentPath", "")).strip(),
                new_name=str(operation.get("targetName", "")).strip(),
            )
            new_path = str(moved.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current_path, new_path)
            executed.append(
                {
                    "type": "reparent_node",
                    "uid": operation.get("uid"),
                    "fromPath": current_path,
                    "path": new_path,
                    "targetParentPath": operation.get("targetParentPath"),
                }
            )

        for change in plan.get("connectionChanges", []):
            check_cancelled()
            dest_path = self._document_apply_state_current_path(
                state,
                str(change.get("destUid", "")).strip(),
                str(change.get("destPath", "")).strip(),
            )
            if not dest_path:
                continue
            source_path = self._document_apply_state_current_path(
                state,
                str(change.get("sourceUid", "")).strip(),
                str(change.get("sourcePath", "")).strip() if change.get("sourcePath") else None,
            )
            if source_path:
                self._node_connect_impl(
                    {
                        "source_node_path": source_path,
                        "dest_node_path": dest_path,
                        "dest_input_index": change["inputIndex"],
                        "source_output_index": change.get("sourceOutputIndex", 0),
                    }
                )
                executed.append(
                    {
                        "type": "connect",
                        "sourceUid": change.get("sourceUid"),
                        "sourcePath": source_path,
                        "destUid": change.get("destUid"),
                        "destPath": dest_path,
                        "inputIndex": change["inputIndex"],
                        "inputName": change.get("destInputName"),
                        "outputIndex": change.get("sourceOutputIndex", 0),
                        "outputName": change.get("sourceOutputName"),
                        "connectionOrder": change.get("connectionOrder"),
                    }
                )
            else:
                self._node_disconnect_impl({"path": dest_path, "input_index": change["inputIndex"]})
                executed.append({"type": "disconnect", "destUid": change.get("destUid"), "destPath": dest_path, "inputIndex": change["inputIndex"]})

        for reset in plan.get("parameterResets", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, reset)
            self._parm_revert_to_default_impl({"parm_path": parm_path})
            executed.append({"type": "revert_parm", "bindingUid": reset.get("bindingUid"), "parmPath": parm_path})

        assignments = [
            {"parm_path": self._document_binding_parm_path(state, update), "value": update.get("value")}
            for update in plan.get("parameterAssignments", [])
        ]
        if assignments:
            check_cancelled()
            self._parm_set_many_impl({"assignments": assignments})
            executed.append({"type": "set_many_parms", "count": len(assignments)})

        for update in plan.get("expressionUpdates", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, update)
            self._parm_set_expression_impl(
                {
                    "parm_path": parm_path,
                    "expression": update["expression"],
                    "language": update.get("expressionLanguage", "hscript"),
                }
            )
            executed.append({"type": "set_expression", "bindingUid": update.get("bindingUid"), "parmPath": parm_path})

        for update in plan.get("codeBlobInstalls", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, update)
            self._parm_set_impl({"parm_path": parm_path, "value": update.get("body")})
            executed.append(
                {
                    "type": "install_code_blob",
                    "bindingUid": update.get("bindingUid"),
                    "codeBlobUid": update.get("codeBlobUid"),
                    "parmPath": parm_path,
                    "language": update.get("language"),
                    "adapter": update.get("adapter"),
                }
            )

        self._document_execute_node_updates(
            plan.get("nodeUpdates", []),
            state,
            executed,
            check_cancelled,
        )

        output_change = plan.get("outputChange")
        if isinstance(output_change, dict):
            check_cancelled()
            source_uid = str(output_change.get("sourceUid", "")).strip()
            source_path = self._document_apply_state_current_path(
                state, source_uid, output_change.get("sourcePath")
            ) if source_uid else None
            if source_path:
                self._node_set_flags_impl({"path": source_path, "display": True})
                executed.append({
                    "type": "set_output", "rootPath": output_change.get("rootPath"),
                    "sourceUid": source_uid, "sourcePath": source_path,
                })
            else:
                executed.append({"type": "clear_output", "rootPath": output_change.get("rootPath")})

        root_guard = plan.get("rootNodeGuard")
        if isinstance(root_guard, dict) and root_guard.get("path"):
            check_cancelled()
            flags = root_guard.get("flags") or {}
            self._node_set_flags_impl(
                {
                    "path": root_guard["path"],
                    "bypass": bool(flags.get("bypass", False)),
                    "display": bool(flags.get("display", False)),
                    "render": bool(flags.get("render", False)),
                    "template": bool(flags.get("template", False)),
                }
            )
            executed.append({"type": "restore_root_flags", "uid": root_guard.get("uid"), "path": root_guard["path"]})

        for operation in plan.get("deleteNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            self._node_delete_impl({"path": current_path, "ignore_missing": True})
            self._document_apply_state_remove_prefix(state, current_path)
            executed.append({"type": "delete_node", "uid": operation.get("uid"), "path": current_path})
        check_cancelled()
        return executed

    def _document_apply_impl(
        self,
        arguments: dict[str, Any],
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        target_document = payload["document"]
        metadata = target_document.get("metadata")
        has_hocus_entities = any(
            isinstance(item, dict)
            and (
                isinstance((item.get("metadata") or {}).get("hocus"), dict)
                or str(item.get("uid", "")).startswith(("hocus-", "binding:hocus-", "code:hocus-"))
                or str(item.get("nodeUid", "")).startswith("hocus-")
                or str((item.get("from") or {}).get("nodeUid", "")).startswith("hocus-")
                or str((item.get("to") or {}).get("nodeUid", "")).startswith("hocus-")
            )
            for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs")
            for item in target_document.get(field, [])
        )
        if (
            isinstance(metadata, dict) and isinstance(metadata.get("hocusPreview"), dict)
        ) or has_hocus_entities:
            raise JsonRpcError(
                INVALID_PARAMS,
                "HocusScript-generated documents must be applied through document.plan_bundle and document.apply_plan.",
                {"diagnosticCode": "HOCUS758"},
            )
        diagnostics = self._document_validate_network_document(target_document)
        checkout_id = payload["checkoutId"]
        if checkout_id:
            self._documents.set_diagnostics(checkout_id, diagnostics)
        blocking = [item for item in diagnostics if item.get("severity") == "error"]
        if blocking:
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": str(arguments.get("mode", "reconcile")).strip() or "reconcile",
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "valid": False,
            }

        mode = str(arguments.get("mode", "reconcile")).strip() or "reconcile"
        if mode not in {"reconcile", "merge", "validate_only"}:
            raise JsonRpcError(INVALID_PARAMS, "mode must be reconcile, merge, or validate_only.")
        root_path = str(target_document.get("rootPath", "")).strip()
        if not root_path:
            raise JsonRpcError(INVALID_PARAMS, "target document must include rootPath.")
        assert_not_quarantined = getattr(self, "_hocus_assert_not_quarantined", None)
        if callable(assert_not_quarantined):
            assert_not_quarantined(root_path)
        baseline_document = self._document_current_network_payload(root_path)
        expected_revision = arguments.get("expected_document_revision", target_document.get("documentRevision"))
        if expected_revision is not None and int(expected_revision) != int(baseline_document.get("documentRevision", -1)):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Document revision mismatch.",
                {
                    "expectedDocumentRevision": int(expected_revision),
                    "currentDocumentRevision": int(baseline_document.get("documentRevision", -1)),
                    "rootPath": root_path,
                },
            )
        compile_started = time.time()
        diff = self._document_diff_payload(baseline_document, target_document)
        plan = self._document_build_apply_plan(baseline_document, target_document, mode=mode)
        if plan.get("codeBlobInstalls") and context is not None:
            from hocuspocus.core.policy import RUN_CODE, require_capabilities
            require_capabilities(context.permissions, (RUN_CODE,))
        compile_ms = round((time.time() - compile_started) * 1000.0, 3)
        if mode == "reconcile" and plan.get("protectedDeleteNodes"):
            protected = plan["protectedDeleteNodes"]
            diagnostics = diagnostics + [
                {
                    "severity": "error",
                    "code": "reconcile.delete_unowned",
                    "message": "Reconcile cannot delete nodes outside the target document's explicit ownership namespace.",
                    "path": root_path,
                    "details": {
                        "protectedNodeCount": len(protected),
                        "protectedNodes": protected,
                    },
                }
            ]
            diagnostics = self._document_clean_diagnostics(diagnostics)
            if checkout_id:
                self._documents.set_diagnostics(checkout_id, diagnostics)
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": mode,
                "valid": False,
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "targetDocumentRevision": target_document.get("documentRevision"),
                "diff": diff,
                "plan": plan,
                "timingsMs": {"compile": compile_ms, "execute": 0.0, "verify": 0.0, "rollback": 0.0},
            }
        if mode == "validate_only":
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": mode,
                "valid": True,
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "targetDocumentRevision": target_document.get("documentRevision"),
                "diff": diff,
                "plan": plan,
                "timingsMs": {"compile": compile_ms, "execute": 0.0, "verify": 0.0, "rollback": 0.0},
            }

        hou_module = self._require_hou()
        label = str(arguments.get("label", f"document apply {root_path}")).strip() or f"document apply {root_path}"
        apply_commit_id = str(uuid4())
        executed: list[dict[str, Any]] = []
        refreshed: dict[str, Any] | None = None
        verification: dict[str, Any] | None = None
        verified = False
        rolled_back = False
        execute_ms = 0.0
        verify_ms = 0.0
        rollback_ms = 0.0
        error_payload: dict[str, Any] | None = None
        try:
            execute_started = time.time()
            with hou_module.undos.group(f"HocusPocus: {label}"):
                executed = self._document_execute_apply_plan(plan, baseline_document)
            execute_ms = round((time.time() - execute_started) * 1000.0, 3)
            self._monitor.mark_dirty("tool:document.apply", scope_path=root_path)
            verify_started = time.time()
            refreshed = self._document_current_network_payload(root_path, force_sync=True)
            verification = self._document_verification_diff_payload(target_document, refreshed)
            verify_ms = round((time.time() - verify_started) * 1000.0, 3)
            verified = self._document_diff_is_clean(verification)
            if not verified:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Live apply verification mismatch.",
                    {"rootPath": root_path, "verificationSummary": verification.get("summary")},
                )
        except Exception as exc:
            error_payload = {"type": exc.__class__.__name__, "message": str(exc)}
            rollback_started = time.time()
            try:
                hou_module.undos.undo()
                rolled_back = True
            except Exception as rollback_exc:
                error_payload["rollbackError"] = str(rollback_exc)
            rollback_ms = round((time.time() - rollback_started) * 1000.0, 3)
            self._monitor.mark_dirty("tool:document.apply.rollback", scope_path=root_path)
            refreshed = self._document_current_network_payload(root_path, force_sync=True)
            failure_diagnostics = diagnostics + [
                {
                    "severity": "error",
                    "code": "apply.execution_failed",
                    "message": str(exc),
                    "path": root_path,
                    "details": {"rolledBack": rolled_back},
                }
            ]
            if checkout_id:
                self._documents.set_diagnostics(checkout_id, failure_diagnostics)
            if hasattr(self._graph_store, "record_apply_result"):
                self._graph_store.record_apply_result(
                    apply_commit_id=apply_commit_id,
                    document_id=str((refreshed or target_document).get("documentId")),
                    root_path=root_path,
                    baseline_document_revision=int(baseline_document.get("documentRevision", 0)),
                    applied_document_revision=int((refreshed or {}).get("documentRevision", 0)) if refreshed is not None else None,
                    mode=mode,
                    verified=False,
                    summary={
                        "verification": (verification or diff).get("summary"),
                        "plan": plan.get("summary"),
                        "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
                        "rolledBack": rolled_back,
                    },
                    operations=executed,
                    diagnostics=failure_diagnostics,
                    error=error_payload,
                )
            return {
                "checkoutId": checkout_id,
                "applyCommitId": apply_commit_id,
                "applied": False,
                "mode": mode,
                "valid": True,
                "diagnostics": failure_diagnostics,
                "diagnosticCount": len(failure_diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "appliedDocumentRevision": (refreshed or {}).get("documentRevision") if refreshed is not None else None,
                "diff": diff,
                "plan": plan,
                "executedOperations": executed,
                "verification": verification,
                "verified": False,
                "rolledBack": rolled_back,
                "error": error_payload,
                "document": refreshed,
                "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
            }
        if checkout_id:
            self._documents.replace_with_applied_document(checkout_id, refreshed or target_document)
        if hasattr(self._graph_store, "record_apply_result"):
            self._graph_store.record_apply_result(
                apply_commit_id=apply_commit_id,
                document_id=str((refreshed or target_document).get("documentId")),
                root_path=root_path,
                baseline_document_revision=int(baseline_document.get("documentRevision", 0)),
                applied_document_revision=int((refreshed or target_document).get("documentRevision", 0)),
                mode=mode,
                verified=verified,
                summary={
                    "verification": (verification or {}).get("summary"),
                    "plan": plan.get("summary"),
                    "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
                    "rolledBack": False,
                },
                operations=executed,
                diagnostics=diagnostics,
                error=None,
            )
        return {
            "checkoutId": checkout_id,
            "applyCommitId": apply_commit_id,
            "applied": True,
            "mode": mode,
            "valid": True,
            "diagnostics": diagnostics,
            "diagnosticCount": len(diagnostics),
            "baselineDocumentRevision": baseline_document.get("documentRevision"),
            "appliedDocumentRevision": refreshed.get("documentRevision"),
            "diff": diff,
            "plan": plan,
            "executedOperations": executed,
            "verification": verification,
            "verified": verified,
            "rolledBack": False,
            "document": refreshed,
            "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
        }

    def document_apply(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_apply_impl(arguments, context), context)
        if not data.get("valid", False):
            return self._tool_response(f"Document apply blocked by {data['diagnosticCount']} diagnostic(s).", data)
        if data.get("error"):
            if data.get("rolledBack", False):
                return self._tool_response("Document apply failed and the live scene was rolled back to the previous state.", data)
            return self._tool_response("Document apply failed before verification completed.", data)
        if not data.get("applied", False):
            return self._tool_response("Computed a validate-only document apply plan.", data)
        if data.get("verified", False):
            return self._tool_response("Applied document changes and verified the resulting network document.", data)
        return self._tool_response("Applied document changes, but verification reported residual differences.", data)
