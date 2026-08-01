"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import copy
import time
from typing import Any, Callable
from uuid import uuid4

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from ..context import RequestContext
from .document_apply_planning import structural_context, structural_moves
from .document_apply_editor import DocumentApplyEditorOperationsMixin
from .document_mutation_integrity import DocumentMutationIntegrityMixin
from .document_apply_managed import (
    plan_binding_changes,
    plan_connection_changes,
)
from .document_runtime_contract import (
    execute_runtime_bindings,
    plan_runtime_changes,
    runtime_plan_summary,
)
from .document_network_families import (
    connection_mismatch,
    network_family_policy,
)

class DocumentApplyOperationsMixin(
    DocumentMutationIntegrityMixin,
    DocumentApplyEditorOperationsMixin,
):
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
                "exact_type_name": True,
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
        return plan_connection_changes(
            self, baseline, target, mode, target_nodes_by_uid, create_uids,
            structural_changed_uids,
        )

    def _document_plan_binding_changes(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        mode: str,
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
        return plan_binding_changes(
            self, baseline, target, mode, target_nodes_by_uid,
            baseline_nodes_by_uid, create_uids,
        )

    @staticmethod
    def _document_plan_node_updates(context: dict[str, Any]) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        for uid, target_node in sorted(
            context["after"].items(), key=lambda item: str(item[1].get("path", ""))
        ):
            if str(target_node.get("path", "")).strip() == context["rootPath"]:
                continue
            baseline_node = context["before"].get(uid)
            flags = copy.deepcopy(target_node.get("flags", {}))
            position = copy.deepcopy(target_node.get("position"))
            if uid in context["created"]:
                if flags or position is not None:
                    updates.append(
                        {"uid": uid, "path": target_node.get("path"), "flags": flags, "position": position}
                    )
                continue
            if baseline_node is None:
                continue
            update: dict[str, Any] = {"uid": uid, "path": target_node.get("path")}
            if baseline_node.get("flags") != target_node.get("flags"):
                update["flags"] = flags
            if baseline_node.get("position") != target_node.get("position"):
                update["position"] = position
            if len(update) > 2:
                updates.append(update)
        return updates

    def _document_plan_deletions(
        self, mode: str, target: dict[str, Any], context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if mode != "reconcile":
            return [], []
        omitted = [
            {"uid": uid, "currentPath": str(node.get("path", "")).strip()}
            for uid, node in context["before"].items()
            if uid != context["rootUid"]
            and uid not in context["after"]
            and not any(
                self._document_path_is_within(str(node.get("path", "")).strip(), prefix)
                and str(node.get("path", "")).strip() != prefix
                for prefix in context["replacementPaths"]
            )
        ]
        ownerships = self._document_reconcile_ownerships(target)
        candidates = [
            item for item in omitted
            if self._document_entity_ownership(context["before"][item["uid"]]) in ownerships
        ]
        protected = [item for item in omitted if item not in candidates]
        paths = self._document_prune_descendant_paths(
            [item["currentPath"] for item in candidates]
        )
        return [
            next(item for item in candidates if item["currentPath"] == path)
            for path in paths
        ], protected

    def _document_build_apply_plan(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        structural = structural_context(self, baseline, target)
        baseline_nodes_by_uid = structural["before"]
        target_nodes_by_uid = structural["after"]
        root_path, root_uid = structural["rootPath"], structural["rootUid"]
        network_family = self._document_network_family(
            root_path, target.get("category")
        )
        create_uids = structural["created"]
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

        rename_nodes, reparent_nodes = structural_moves(self, structural)

        connection_changes = self._document_plan_connection_changes(
            baseline,
            target,
            mode,
            target_nodes_by_uid,
            create_uids,
            structural["changed"],
        )
        (
            parameter_assignments,
            expression_updates,
            code_blob_installs,
            identity_updates,
            identity_clears,
            parameter_resets,
            typed_value_updates,
        ) = self._document_plan_binding_changes(
            baseline,
            target,
            mode,
            target_nodes_by_uid,
            baseline_nodes_by_uid,
            create_uids,
        )

        node_updates = self._document_plan_node_updates(structural)
        root_provenance_change = self._document_plan_root_expansion_provenance(
            baseline, target
        )
        root_entity_provenance_change = (
            self._document_plan_root_entity_provenance(baseline, target)
        )
        root_typed_binding_change = self._document_plan_root_typed_receipt(
            baseline, target
        )
        editor_entity_change = self._document_plan_editor_entities(
            baseline, target, mode
        )
        root_editor_entity_change = self._document_plan_root_editor_receipt(
            baseline, target
        )
        runtime_changes = plan_runtime_changes(
            baseline,
            target,
            mode=mode,
            target_nodes=target_nodes_by_uid,
            create_uids=create_uids,
        )
        output_guard, output_change = self._document_plan_output(
            baseline, target, structural, network_family
        )

        replace_nodes = [
            {
                "uid": uid,
                "currentPath": str(baseline_nodes_by_uid[uid].get("path", "")).strip(),
                "target": copy.deepcopy(target_nodes_by_uid[uid]),
            }
            for uid in sorted(structural["replacements"], key=lambda item: str(baseline_nodes_by_uid[item].get("path", "")).count("/"), reverse=True)
        ]
        delete_nodes, protected_delete_nodes = self._document_plan_deletions(
            mode, target, structural
        )

        return {
            "networkFamily": network_family,
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
            "typedValueUpdates": typed_value_updates,
            "expressionUpdates": expression_updates,
            "codeBlobInstalls": code_blob_installs,
            "identityUpdates": identity_updates,
            "identityClears": identity_clears,
            "nodeUpdates": node_updates,
            "rootProvenanceChange": root_provenance_change,
            "rootEntityProvenanceChange": root_entity_provenance_change,
            "rootTypedBindingChange": root_typed_binding_change,
            "editorEntityChange": editor_entity_change,
            "rootEditorEntityChange": root_editor_entity_change,
            **runtime_changes,
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
                "typedValueUpdateCount": len(typed_value_updates),
                "expressionUpdateCount": len(expression_updates),
                "codeBlobInstallCount": len(code_blob_installs),
                "identityUpdateCount": len(identity_updates),
                "identityClearCount": len(identity_clears),
                "nodeUpdateCount": len(node_updates),
                "rootProvenanceChangeCount": int(root_provenance_change is not None),
                "rootEntityProvenanceChangeCount": int(
                    root_entity_provenance_change is not None
                ),
                "rootTypedBindingChangeCount": int(
                    root_typed_binding_change is not None
                ),
                "editorEntityChangeCount": (
                    len(editor_entity_change["plan"]["operations"])
                    if editor_entity_change is not None else 0
                ),
                "rootEditorEntityChangeCount": int(
                    root_editor_entity_change is not None
                ),
                **runtime_plan_summary(runtime_changes),
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

    def _document_execute_creates(
        self, plan, state, executed, checkpoint
    ) -> None:
        for operation in plan.get("replaceNodes", []):
            checkpoint()
            uid = str(operation.get("uid", "")).strip()
            current = self._document_apply_state_current_path(
                state, uid, str(operation.get("currentPath", "")).strip()
            )
            if current:
                self._node_delete_impl({"path": current, "ignore_missing": True})
                self._document_apply_state_remove_prefix(state, current)
                executed.append(
                    {"type": "replace_delete_node", "uid": operation.get("uid"), "path": current}
                )
            created = self._document_create_live_node(operation.get("target", {}))
            self._document_apply_state_register(
                state, uid, str(created.get("path", "")).strip()
            )
            executed.append(
                {
                    "type": "replace_create_node", "uid": operation.get("uid"),
                    "path": created.get("path"), "nodeTypeName": created.get("typeName"),
                }
            )
        for group_name in ("createNetworkContainers", "createNodes"):
            for node in plan.get(group_name, []):
                checkpoint()
                created = self._document_create_live_node(node)
                self._document_apply_state_register(
                    state,
                    str(node.get("uid", "")).strip(),
                    str(created.get("path", "")).strip(),
                )
                executed.append(
                    {
                        "type": "create_node", "uid": node.get("uid"),
                        "path": created.get("path"), "nodeTypeName": created.get("typeName"),
                    }
                )

    def _document_execute_moves(self, plan, state, executed, checkpoint) -> None:
        for operation in plan.get("renameNodes", []):
            checkpoint()
            current = self._document_apply_state_current_path(
                state,
                str(operation.get("uid", "")).strip(),
                str(operation.get("currentPath", "")).strip(),
            )
            if not current:
                continue
            renamed = self._node_rename_impl(
                {
                    "path": current,
                    "new_name": operation.get("targetName"),
                    "unique_name": False,
                }
            )
            new_path = str(renamed.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current, new_path)
            executed.append(
                {
                    "type": "rename_node", "uid": operation.get("uid"),
                    "fromPath": current, "path": new_path,
                }
            )
        for operation in plan.get("reparentNodes", []):
            checkpoint()
            current = self._document_apply_state_current_path(
                state,
                str(operation.get("uid", "")).strip(),
                str(operation.get("currentPath", "")).strip(),
            )
            if not current:
                continue
            moved = self._document_reparent_live_node(
                path=current,
                new_parent_path=str(operation.get("targetParentPath", "")).strip(),
                new_name=str(operation.get("targetName", "")).strip(),
            )
            new_path = str(moved.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current, new_path)
            executed.append(
                {
                    "type": "reparent_node", "uid": operation.get("uid"),
                    "fromPath": current, "path": new_path,
                    "targetParentPath": operation.get("targetParentPath"),
                }
            )

    def _document_execute_connections(self, plan, state, executed, checkpoint) -> None:
        for change in plan.get("connectionChanges", []):
            checkpoint()
            dest = self._document_apply_state_current_path(
                state,
                str(change.get("destUid", "")).strip(),
                str(change.get("destPath", "")).strip(),
            )
            if not dest:
                continue
            source = self._document_apply_state_current_path(
                state,
                str(change.get("sourceUid", "")).strip(),
                str(change.get("sourcePath", "")).strip()
                if change.get("sourcePath") else None,
            )
            if source:
                self._node_connect_impl(
                    {
                        "source_node_path": source, "dest_node_path": dest,
                        "dest_input_index": change["inputIndex"],
                        "source_output_index": change.get("sourceOutputIndex", 0),
                    }
                )
                observed = next(
                    (
                        item
                        for item in self._document_live_input_connections(dest)
                        if item.get("inputIndex") == change["inputIndex"]
                    ),
                    {},
                )
                mismatch = connection_mismatch(
                    {**change, "sourcePath": source}, observed
                )
                if mismatch:
                    raise JsonRpcError(
                        INVALID_PARAMS,
                        "Live connection metadata does not match the indexed document contract.",
                        {
                            "destPath": dest,
                            "inputIndex": change["inputIndex"],
                            "mismatches": mismatch,
                        },
                    )
                executed.append(
                    {
                        "type": "connect", "sourceUid": change.get("sourceUid"),
                        "sourcePath": source, "destUid": change.get("destUid"),
                        "destPath": dest, "inputIndex": change["inputIndex"],
                        "inputName": change.get("destInputName"),
                        "outputIndex": change.get("sourceOutputIndex", 0),
                        "outputName": change.get("sourceOutputName"),
                        "connectionOrder": change.get("connectionOrder"),
                    }
                )
            else:
                self._node_disconnect_impl(
                    {"path": dest, "input_index": change["inputIndex"]}
                )
                executed.append(
                    {
                        "type": "disconnect", "destUid": change.get("destUid"),
                        "destPath": dest, "inputIndex": change["inputIndex"],
                    }
                )

    def _document_execute_finalizers(self, plan, state, executed, checkpoint) -> None:
        output = plan.get("outputChange")
        if isinstance(output, dict):
            network_family = plan.get("networkFamily")
            if (
                network_family is not None
                and network_family_policy(network_family).output_strategy != "sop_display"
            ):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Only SOP documents may execute display-output finalizers.",
                )
            checkpoint()
            source_uid = str(output.get("sourceUid", "")).strip()
            source = (
                self._document_apply_state_current_path(
                    state, source_uid, output.get("sourcePath")
                )
                if source_uid else None
            )
            if source:
                self._node_set_flags_impl({"path": source, "display": True})
                executed.append(
                    {
                        "type": "set_output", "rootPath": output.get("rootPath"),
                        "sourceUid": source_uid, "sourcePath": source,
                    }
                )
            else:
                before_uid = str(output.get("beforeSourceUid", "")).strip()
                before = self._document_apply_state_current_path(
                    state, before_uid
                ) if before_uid else None
                if before:
                    self._node_set_flags_impl({"path": before, "display": False})
                executed.append({
                    "type": "clear_output",
                    "rootPath": output.get("rootPath"),
                    "previousSourceUid": before_uid or None,
                    "previousSourcePath": before,
                })
        guard = plan.get("rootNodeGuard")
        if isinstance(guard, dict) and guard.get("path"):
            checkpoint()
            flags = guard.get("flags") or {}
            self._node_set_flags_impl(
                {
                    "path": guard["path"],
                    "bypass": bool(flags.get("bypass", False)),
                    "display": bool(flags.get("display", False)),
                    "render": bool(flags.get("render", False)),
                    "template": bool(flags.get("template", False)),
                }
            )
            executed.append(
                {"type": "restore_root_flags", "uid": guard.get("uid"), "path": guard["path"]}
            )
        for operation in plan.get("deleteNodes", []):
            checkpoint()
            current = self._document_apply_state_current_path(
                state,
                str(operation.get("uid", "")).strip(),
                str(operation.get("currentPath", "")).strip(),
            )
            if current:
                self._node_delete_impl({"path": current, "ignore_missing": True})
                self._document_apply_state_remove_prefix(state, current)
                executed.append(
                    {"type": "delete_node", "uid": operation.get("uid"), "path": current}
                )

    def _document_execute_apply_plan(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        *,
        checkpoint: Callable[[], None] | None = None,
        executed: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        state = self._document_apply_state(baseline)
        executed = executed if executed is not None else []

        def check_cancelled() -> None:
            if checkpoint is not None:
                checkpoint()

        self._document_execute_identity_changes(plan, state, executed, check_cancelled)
        self._document_execute_creates(plan, state, executed, check_cancelled)
        self._document_execute_moves(plan, state, executed, check_cancelled)
        self._document_execute_connections(plan, state, executed, check_cancelled)
        execute_runtime_bindings(
            self, plan, state, executed, check_cancelled
        )
        self._document_execute_node_updates(
            plan.get("nodeUpdates", []),
            state,
            executed,
            check_cancelled,
        )
        editor_identities = self._document_execute_editor_entities(
            plan.get("editorEntityChange"),
            state,
            executed,
            check_cancelled,
        )
        self._document_execute_root_editor_receipt(
            plan.get("rootEditorEntityChange"),
            editor_identities,
            executed,
            check_cancelled,
        )
        self._document_execute_root_expansion_provenance(
            plan, executed, check_cancelled
        )
        self._document_execute_root_entity_provenance(
            plan, executed, check_cancelled
        )
        self._document_execute_root_typed_receipt(
            plan, executed, check_cancelled
        )
        self._document_execute_finalizers(plan, state, executed, check_cancelled)
        check_cancelled()
        return executed

    @staticmethod
    def _document_assert_direct_apply_allowed(target: dict[str, Any]) -> None:
        metadata = target.get("metadata")
        has_hocus_entities = any(
            isinstance(item, dict)
            and (
                isinstance((item.get("metadata") or {}).get("hocus"), dict)
                or str(item.get("uid", "")).startswith(
                    ("hocus-", "binding:hocus-", "code:hocus-")
                )
                or str(item.get("nodeUid", "")).startswith("hocus-")
                or str((item.get("from") or {}).get("nodeUid", "")).startswith("hocus-")
                or str((item.get("to") or {}).get("nodeUid", "")).startswith("hocus-")
            )
            for field in (
                "nodes", "ports", "edges", "parameterBindings", "codeBlobs",
                "networkBoxes", "stickyNotes", "nodeComments", "networkDots",
                "layoutConstraints", "spareParameters", "animations",
            )
            for item in target.get(field, [])
        )
        if target.get("$schema") == (
            "hocuspocus://schemas/network-document/v2"
        ) or (
            isinstance(metadata, dict)
            and isinstance(metadata.get("hocusPreview"), dict)
        ) or has_hocus_entities:
            raise JsonRpcError(
                INVALID_PARAMS,
                "HocusScript-generated documents must be applied through document.plan_bundle and document.apply_plan.",
                {"diagnosticCode": "HOCUS758"},
            )

    @staticmethod
    def _document_assert_expected_revision(
        arguments: dict[str, Any],
        target: dict[str, Any],
        baseline: dict[str, Any],
        root_path: str,
    ) -> None:
        expected = arguments.get(
            "expected_document_revision", target.get("documentRevision")
        )
        if expected is not None and int(expected) != int(
            baseline.get("documentRevision", -1)
        ):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Document revision mismatch.",
                {
                    "expectedDocumentRevision": int(expected),
                    "currentDocumentRevision": int(
                        baseline.get("documentRevision", -1)
                    ),
                    "rootPath": root_path,
                },
            )

    def _document_apply_planning_result(
        self,
        *,
        mode: str,
        plan: dict[str, Any],
        diagnostics: list[dict[str, Any]],
        checkout_id: str | None,
        baseline: dict[str, Any],
        target: dict[str, Any],
        diff: dict[str, Any],
        compile_ms: float,
    ) -> dict[str, Any] | None:
        if mode in {"reconcile", "validate_only"} and plan.get("protectedDeleteNodes"):
            protected = plan["protectedDeleteNodes"]
            diagnostics = self._document_clean_diagnostics(
                diagnostics
                + [
                    {
                        "severity": "error",
                        "code": "reconcile.delete_unowned",
                        "message": "Reconcile cannot delete nodes outside the target document's explicit ownership namespace.",
                        "path": str(target.get("rootPath", "")).strip(),
                        "details": {
                            "protectedNodeCount": len(protected),
                            "protectedNodes": protected,
                        },
                    }
                ]
            )
            if checkout_id:
                self._documents.set_diagnostics(checkout_id, diagnostics)
            valid = False
        elif mode == "validate_only":
            valid = True
        else:
            return None
        return {
            "checkoutId": checkout_id,
            "applied": False,
            "mode": mode,
            "valid": valid,
            "diagnostics": diagnostics,
            "diagnosticCount": len(diagnostics),
            "baselineDocumentRevision": baseline.get("documentRevision"),
            "targetDocumentRevision": target.get("documentRevision"),
            "diff": diff,
            "plan": plan,
            "timingsMs": {
                "compile": compile_ms, "execute": 0.0, "verify": 0.0, "rollback": 0.0
            },
        }

    @staticmethod
    def _document_require_code_capability(
        plan: dict[str, Any], context: RequestContext | None
    ) -> None:
        if not plan.get("codeBlobInstalls") or context is None:
            return
        from hocuspocus.core.policy import RUN_CODE, require_capabilities
        require_capabilities(context.permissions, (RUN_CODE,))

    @staticmethod
    def _document_apply_mode_root(
        arguments: dict[str, Any], target: dict[str, Any]
    ) -> tuple[str, str]:
        mode = str(arguments.get("mode", "reconcile")).strip() or "reconcile"
        if mode not in {"reconcile", "merge", "validate_only"}:
            raise JsonRpcError(
                INVALID_PARAMS, "mode must be reconcile, merge, or validate_only."
            )
        root_path = str(target.get("rootPath", "")).strip()
        if not root_path:
            raise JsonRpcError(
                INVALID_PARAMS, "target document must include rootPath."
            )
        return mode, root_path

    def _document_apply_impl(
        self,
        arguments: dict[str, Any],
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        target_document = payload["document"]
        self._document_assert_direct_apply_allowed(target_document)
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

        mode, root_path = self._document_apply_mode_root(arguments, target_document)
        assert_not_quarantined = getattr(self, "_hocus_assert_not_quarantined", None)
        if callable(assert_not_quarantined):
            assert_not_quarantined(root_path)
        baseline_document = self._document_current_network_payload(root_path)
        self._document_assert_expected_revision(
            arguments, target_document, baseline_document, root_path
        )
        compile_started = time.time()
        diff = self._document_diff_payload(baseline_document, target_document)
        plan = self._document_build_apply_plan(baseline_document, target_document, mode="reconcile" if mode == "validate_only" else mode)
        self._document_require_code_capability(plan, context)
        compile_ms = round((time.time() - compile_started) * 1000.0, 3)
        planning_result = self._document_apply_planning_result(
            mode=mode,
            plan=plan,
            diagnostics=diagnostics,
            checkout_id=checkout_id,
            baseline=baseline_document,
            target=target_document,
            diff=diff,
            compile_ms=compile_ms,
        )
        if planning_result is not None:
            return planning_result

        plan, target_document, inverse_plan = self._document_prepare_direct_apply(
            plan, baseline_document, target_document
        )
        hou_module = self._require_hou()
        label = str(arguments.get("label", f"document apply {root_path}")).strip() or f"document apply {root_path}"
        undo_label = f"HocusPocus: {label}"
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
            with hou_module.undos.group(undo_label):
                self._document_execute_apply_plan(
                    plan, baseline_document, executed=executed
                )
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
            (
                rolled_back,
                rollback_error,
                rollback_verification,
                refreshed,
                rollback_executed,
            ) = self._document_rollback_direct_apply(
                root_path=root_path,
                baseline=baseline_document,
                undo_label=undo_label,
                inverse_plan=inverse_plan,
                forward_target=target_document,
            )
            error_payload["rollbackError"] = rollback_error
            rollback_ms = round((time.time() - rollback_started) * 1000.0, 3)
            failure_diagnostics = diagnostics + [
                {
                    "severity": "error",
                    "code": "apply.execution_failed",
                    "message": str(exc),
                    "path": root_path,
                    "details": {
                        "rolledBack": rolled_back,
                        "diagnosticCode": "HOCUS755" if rolled_back else "HOCUS756",
                    },
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
                        "rollbackVerification": (
                            rollback_verification or {}
                        ).get("summary"),
                        "plan": plan.get("summary"),
                        "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
                        "rolledBack": rolled_back,
                    },
                    operations=executed,
                    diagnostics=failure_diagnostics,
                    error=error_payload,
                )
            failure = {
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
                "rollbackVerification": rollback_verification,
                "rollbackExecutedOperations": rollback_executed,
                "verified": False,
                "rolledBack": rolled_back,
                "state": "aborted" if rolled_back else "partial_or_unknown",
                "diagnosticCode": "HOCUS755" if rolled_back else "HOCUS756",
                "error": error_payload,
                "document": refreshed,
                "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
            }
            if not rolled_back:
                self._document_quarantine_direct_apply(
                    root_path, apply_commit_id, str(exc)
                )
            self._document_raise_apply_failure(
                failure=failure, rolled_back=rolled_back
            )
            raise AssertionError("document apply failure must raise")
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
