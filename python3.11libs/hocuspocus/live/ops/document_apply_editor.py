"""Plan and execute network-editor entity changes inside document apply."""

from __future__ import annotations

from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_editor_entities import (
    DocumentEditorEntityError,
    editor_entities_from_document,
    plan_editor_entities,
)

from .document_editor_entities import (
    EditorEntityLiveApplyError,
    apply_live_editor_entity_plan,
)


class DocumentApplyEditorOperationsMixin:
    """Bridge pure editor plans to the existing guarded Houdini transaction."""

    def _document_plan_editor_entities(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        mode: str,
    ) -> dict[str, Any] | None:
        node_uids = {
            str(item.get("uid", "")).strip()
            for document in (baseline, target)
            for item in document.get("nodes", [])
            if isinstance(item, dict) and str(item.get("uid", "")).strip()
        }
        try:
            before = editor_entities_from_document(
                baseline, node_uids=node_uids,
            )
            after = editor_entities_from_document(
                target, node_uids=node_uids,
            )
            plan = plan_editor_entities(
                before,
                after,
                mode=mode,
                reconcile_ownerships=self._document_reconcile_ownerships(
                    target
                ),
                node_uids=node_uids,
            )
        except DocumentEditorEntityError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Editor entity plan is invalid: {exc}",
                {"diagnosticCode": "HOCUS936", **exc.details},
            ) from exc
        if not plan["operations"]:
            return None
        return {
            "rootPath": str(target.get("rootPath", "")).strip(),
            "plan": plan,
        }

    def _document_execute_editor_entities(
        self,
        editor_change: dict[str, Any] | None,
        state: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> list[dict[str, Any]]:
        if not isinstance(editor_change, dict):
            return []
        checkpoint()
        root_path = str(editor_change.get("rootPath", "")).strip()
        root = self._require_node_by_path(root_path)
        node_by_uid = {}
        for uid, fallback_path in state.get("uidToPath", {}).items():
            path = self._document_apply_state_current_path(
                state, str(uid), str(fallback_path)
            )
            node = self._safe_value(
                lambda path=path: self._require_hou().node(path), None
            )
            if node is not None:
                node_by_uid[str(uid)] = node
        receipt = self._document_live_editor_receipt(root_path)
        prior_names = (
            receipt["liveIdentities"] if receipt is not None else {}
        )
        hou_module = self._require_hou()
        display_comment = self._safe_value(
            lambda: hou_module.nodeFlag.DisplayComment, None
        )
        try:
            result = apply_live_editor_entity_plan(
                root,
                editor_change["plan"],
                node_by_uid=node_by_uid,
                live_name_by_uid=prior_names,
                display_comment_flag=display_comment,
                checkpoint=checkpoint,
            )
        except EditorEntityLiveApplyError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Editor entity mutation failed.",
                {
                    "diagnosticCode": "HOCUS936",
                    "rolledBack": exc.rolled_back,
                    "rollbackError": exc.rollback_error,
                },
            ) from exc
        executed.extend(
            {
                "type": f"editor_entity_{item['action']}",
                "uid": item["uid"],
                "kind": item["kind"],
            }
            for item in result["executed"]
        )
        return result["liveIdentities"]
