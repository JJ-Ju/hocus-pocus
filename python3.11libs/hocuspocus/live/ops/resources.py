"""Resource reads and dynamic resource templates."""

from __future__ import annotations

from ..context import RequestContext


class ResourceOperationsMixin:
    def read_session_info(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/info",
            self._call_live(self._session_info_impl, context),
        )

    def read_session_health(self, context: RequestContext) -> dict[str, object]:
        data = {
            "dispatcherMode": self._dispatcher.mode,
            "settings": {
                "host": self._settings.host,
                "port": self._settings.port,
                "tokenMode": self._settings.token_mode,
            },
            "monitor": self._monitor.snapshot(),
            "activeOperations": self._dispatcher.operations_snapshot(limit=20),
            "recentTasks": self._tasks.snapshots(limit=20),
        }
        return self._resource_response("houdini://session/health", data)

    def read_session_conventions(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/conventions",
            self._conventions_payload(),
        )

    def read_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        task_log_id = self._dynamic_task_id(uri, "/log")
        if task_log_id is not None:
            payload = self._tasks.log_payload(task_log_id)
            if payload is not None:
                return self._resource_response(uri, payload)

        task_id = self._dynamic_task_id(uri)
        if task_id is not None:
            payload = self._tasks.snapshot(task_id)
            if payload is not None:
                return self._resource_response(uri, payload)

        geometry_path = self._dynamic_node_uri_to_path(uri, "/geometry-summary")
        if geometry_path is not None:
            return self._resource_response(
                uri,
                self._call_live(
                    lambda: self._node_geometry_resource_impl(geometry_path),
                    context,
                ),
            )

        parms_path = self._dynamic_node_uri_to_path(uri, "/parms")
        if parms_path is not None:
            return self._resource_response(
                uri,
                self._call_live(
                    lambda: self._node_parms_resource_impl(parms_path),
                    context,
                ),
            )

        node_path = self._dynamic_node_uri_to_path(uri)
        if node_path is not None:
            return self._resource_response(
                uri,
                self._call_live(
                    lambda: self._node_resource_impl(node_path),
                    context,
                ),
            )
        return None

    def resource_templates_payload(self) -> list[dict[str, object]]:
        return [
            {
                "uriTemplate": "houdini://nodes/{path}",
                "name": "Node Resource",
                "description": "Read summary information for a node. Path may be slash-separated or percent-encoded.",
                "mimeType": "application/json",
            },
            {
                "uriTemplate": "houdini://nodes/{path}/parms",
                "name": "Node Parm Resource",
                "description": "Read parameter summaries for a node.",
                "mimeType": "application/json",
            },
            {
                "uriTemplate": "houdini://nodes/{path}/geometry-summary",
                "name": "Node Geometry Summary",
                "description": "Read point/primitive counts, bbox, group, and material summaries for a node with geometry.",
                "mimeType": "application/json",
            },
            {
                "uriTemplate": "houdini://tasks/{task_id}",
                "name": "Task Resource",
                "description": "Read task state, progress, result, and failure details for a submitted task.",
                "mimeType": "application/json",
            },
            {
                "uriTemplate": "houdini://tasks/{task_id}/log",
                "name": "Task Log Resource",
                "description": "Read recent log lines for a submitted task.",
                "mimeType": "application/json",
            },
        ]

    def _node_resource_impl(self, node_path: str) -> dict[str, object]:
        node = self._require_node_by_path(node_path)
        return self._node_summary(node, include_parms=False)

    def _node_parms_resource_impl(self, node_path: str) -> dict[str, object]:
        return self._parm_list_impl({"node_path": node_path})

    def _node_geometry_resource_impl(self, node_path: str) -> dict[str, object]:
        node = self._require_node_by_path(node_path)
        return self._geometry_summary_for_node(node)

    def read_scene_summary(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/scene-summary",
            self._call_live(self._scene_summary_impl, context),
        )

    def read_selection(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/selection",
            self._call_live(self._selection_get_impl, context),
        )

    def read_playbar(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/playbar",
            self._call_live(self._playbar_state_impl, context),
        )

    def read_operations(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/operations",
            {"operations": self._dispatcher.operations_snapshot(limit=100)},
        )

    def read_tasks_recent(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://tasks/recent",
            {"tasks": self._tasks.snapshots(limit=100)},
        )
