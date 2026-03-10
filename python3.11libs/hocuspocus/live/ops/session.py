"""Session and task listing operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.version import __version__

from ..context import RequestContext
from .base import hou


class SessionOperationsMixin:
    def _session_info_impl(self) -> dict[str, Any]:
        policy = {
            "effectivePolicy": self._settings.effective_policy_payload(),
            "availableProfiles": self._settings.available_policy_profiles_payload(),
        }
        hou_module = hou
        if hou_module is None:
            return {
                "serverVersion": __version__,
                "houdiniAvailable": False,
                "uiAvailable": False,
                "applicationVersion": None,
                "hipFile": None,
                "sceneRevision": self._monitor.snapshot()["revision"],
                "graph": self._graph.stats(),
                "activeOperations": self._dispatcher.operations_snapshot(limit=20),
                "recentTasks": self._tasks.snapshots(limit=10),
                "conventions": self._conventions_payload(),
                "policy": policy,
            }

        hip_path = None
        is_dirty = None
        try:
            hip_path = hou_module.hipFile.path()
            is_dirty = hou_module.hipFile.hasUnsavedChanges()
        except Exception:
            self._logger.debug("failed to read hip state", exc_info=True)

        return {
            "serverVersion": __version__,
            "houdiniAvailable": True,
            "uiAvailable": bool(hou_module.isUIAvailable()),
            "applicationVersion": list(hou_module.applicationVersion()),
            "hipFile": hip_path,
            "hipDirty": is_dirty,
            "sceneRevision": self._monitor.snapshot()["revision"],
            "graph": self._graph.stats(),
            "activeOperations": self._dispatcher.operations_snapshot(limit=20),
            "recentTasks": self._tasks.snapshots(limit=10),
            "conventions": self._conventions_payload(),
            "policy": policy,
        }

    def session_info(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(self._session_info_impl, context)
        return self._tool_response("Returned current Houdini session information.", data)

    def session_list_operations(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        limit = int(arguments.get("limit", 50))
        data = {"operations": self._dispatcher.operations_snapshot(limit=limit)}
        return self._tool_response("Returned recent dispatcher operations.", data)

    def session_cancel_operation(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        operation_id = str(arguments.get("operation_id", "")).strip()
        if not operation_id:
            from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

            raise JsonRpcError(INVALID_PARAMS, "operation_id is required")
        cancelled = self._dispatcher.cancel(operation_id)
        data = {
            "operationId": operation_id,
            "cancelled": cancelled,
            "operation": self._dispatcher.operation_snapshot(operation_id),
        }
        return self._tool_response(
            f"Cancellation requested for operation {operation_id}.",
            data,
        )

    def task_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        limit = int(arguments.get("limit", 50))
        tasks = self._tasks.snapshots(limit=limit)
        data = {
            "count": len(tasks),
            "tasks": tasks,
        }
        return self._tool_response("Returned recent task records.", data)

    def task_cancel(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

        task_id = str(arguments.get("task_id", "")).strip()
        if not task_id:
            raise JsonRpcError(INVALID_PARAMS, "task_id is required")
        cancelled = self._tasks.cancel(task_id)
        data = {
            "taskId": task_id,
            "cancelled": cancelled,
            "task": self._tasks.snapshot(task_id),
        }
        return self._tool_response(f"Cancellation requested for task {task_id}.", data)
