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
            "graph": self._graph.stats(),
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
        if uri == "houdini://graph/scene":
            return self.read_graph_scene(context)
        if uri == "houdini://graph/index":
            return self.read_graph_index(context)
        if uri == "houdini://dependencies/scene":
            return self.read_scene_dependencies(context)
        if uri == "houdini://caches/topology":
            return self.read_cache_topology(context)
        if uri == "houdini://packages/preview":
            return self.read_package_preview(context)
        if uri == "houdini://scene/events":
            return self.read_scene_events(context)
        if uri.startswith("houdini://renders/graph/"):
            raw = uri[len("houdini://renders/graph/") :].strip("/")
            if raw:
                node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}")
                if node_path is not None:
                    return self.read_render_graph(node_path, context)
        if uri.startswith("houdini://graph/subgraph/"):
            raw = uri[len("houdini://graph/subgraph/") :].strip("/")
            if raw:
                root_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}")
                if root_path is not None:
                    return self._resource_response(
                        uri,
                        self._call_live(
                            lambda root_path=root_path: self._graph_subgraph_payload(self._graph_snapshot(), root_path),
                            context,
                        ),
                    )
        if uri.startswith("houdini://graph/dependencies/"):
            raw = uri[len("houdini://graph/dependencies/") :].strip("/")
            if raw:
                node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}")
                if node_path is not None:
                    return self._resource_response(
                        uri,
                        self._call_live(
                            lambda node_path=node_path: self._graph_dependency_payload(self._graph_snapshot(), node_path),
                            context,
                        ),
                    )
        if uri.startswith("houdini://graph/references/"):
            raw = uri[len("houdini://graph/references/") :].strip("/")
            if raw:
                node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}")
                if node_path is not None:
                    return self._resource_response(
                        uri,
                        self._call_live(
                            lambda node_path=node_path: self._graph_reference_payload(self._graph_snapshot(), node_path),
                            context,
                        ),
                    )

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
                "uriTemplate": "houdini://graph/scene",
                "name": "Scene Graph Snapshot",
                "description": "Read the indexed whole-scene graph snapshot, including nodes, parms, edges, material assignments, and parameter references.",
                "mimeType": "application/json",
                "payloadSummary": "Whole-scene graph snapshot with normalized nodes, parameter summaries, graph edges, and graph stats.",
                "examples": [
                    {
                        "description": "Load the current indexed scene graph in one read.",
                        "uri": "houdini://graph/scene",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://graph/index",
                "name": "Scene Graph Index",
                "description": "Read cache and revision metadata for the in-memory indexed scene graph.",
                "mimeType": "application/json",
                "payloadSummary": "Graph-cache stats such as revision, node count, parm count, edge count, and last refresh timing.",
                "examples": [
                    {
                        "description": "Inspect graph-cache health and size.",
                        "uri": "houdini://graph/index",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://dependencies/scene",
                "name": "Scene Dependencies",
                "description": "Read the current whole-scene dependency scan across file parms, USD references, cache paths, and output paths.",
                "mimeType": "application/json",
                "payloadSummary": "Whole-scene dependency list with classification, missing-file flags, and path-policy results.",
                "examples": [
                    {
                        "description": "Read the current dependency scan for packaging or repath planning.",
                        "uri": "houdini://dependencies/scene",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://caches/topology",
                "name": "Cache Topology",
                "description": "Read the current cache-node topology summary for common cache-oriented nodes.",
                "mimeType": "application/json",
                "payloadSummary": "Cache-node list with file paths, existing outputs, and read/write cache mode.",
                "examples": [
                    {
                        "description": "Inspect scene caches before packaging or publish steps.",
                        "uri": "houdini://caches/topology",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://packages/preview",
                "name": "Scene Package Preview",
                "description": "Read a package preview for the current whole scene using the default package-preview rules.",
                "mimeType": "application/json",
                "payloadSummary": "Collected and skipped package entries plus dependency-summary counts for packaging decisions.",
                "examples": [
                    {
                        "description": "Inspect what would be packaged before writing a zip or directory package.",
                        "uri": "houdini://packages/preview",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://scene/events",
                "name": "Scene Events",
                "description": "Read recent scene-monitor events as a lightweight event feed over the current HTTP transport.",
                "mimeType": "application/json",
                "payloadSummary": "Recent event entries with sequence numbers, revisions, event names, and timestamps.",
                "examples": [
                    {
                        "description": "Read recent live scene events.",
                        "uri": "houdini://scene/events",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://graph/subgraph/{path}",
                "name": "Subgraph Snapshot",
                "description": "Read a subgraph snapshot rooted at a Houdini path. `{path}` uses the same slash-separated or percent-encoded path rules as node resources.",
                "mimeType": "application/json",
                "payloadSummary": "Rooted subgraph snapshot with descendant nodes, parm summaries, and internal edges.",
                "examples": [
                    {
                        "description": "Read the full SOP subgraph under a geometry object.",
                        "uri": "houdini://graph/subgraph/obj/geo1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://graph/dependencies/{path}",
                "name": "Node Dependencies",
                "description": "Read structural and parameter-reference edges touching a specific node path.",
                "mimeType": "application/json",
                "payloadSummary": "Node summary plus incoming, outgoing, material, and parameter-reference edges related to the node.",
                "examples": [
                    {
                        "description": "Inspect dependencies for an output SOP.",
                        "uri": "houdini://graph/dependencies/obj/geo1/OUT",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://graph/references/{path}",
                "name": "Node Parm References",
                "description": "Read parameter-expression references owned by a node.",
                "mimeType": "application/json",
                "payloadSummary": "Parameter summaries for parms on the node that reference other parameters or absolute parm paths.",
                "examples": [
                    {
                        "description": "Inspect parameter references for a rig controller.",
                        "uri": "houdini://graph/references/obj/geo1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://renders/graph/{path}",
                "name": "Render Graph",
                "description": "Read a render-graph inspection payload rooted at a specific ROP node path. `{path}` uses the same slash-separated or percent-encoded path rules as node resources.",
                "mimeType": "application/json",
                "payloadSummary": "ROP-chain nodes, edges, output paths, frame-range parms, and node-reference summaries.",
                "examples": [
                    {
                        "description": "Inspect the graph driving a render node.",
                        "uri": "houdini://renders/graph/out/geo_rop1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://nodes/{path}",
                "name": "Node Resource",
                "description": "Read a normalized node summary by Houdini path. `{path}` may be slash-separated like `obj/geo1` or percent-encoded like `%2Fobj%2Fgeo1`.",
                "mimeType": "application/json",
                "payloadSummary": "Single normalized node summary with flags, wiring, parent path, and display or render node pointers when relevant.",
                "examples": [
                    {
                        "description": "Read an object node by slash-separated path.",
                        "uri": "houdini://nodes/obj/geo1",
                    },
                    {
                        "description": "Read a SOP node by percent-encoded absolute path.",
                        "uri": "houdini://nodes/%2Fobj%2Fgeo1%2FOUT",
                    },
                ],
            },
            {
                "uriTemplate": "houdini://nodes/{path}/parms",
                "name": "Node Parm Resource",
                "description": "Read normalized parameter summaries for a node. Use the same `{path}` encoding rules as the base node resource.",
                "mimeType": "application/json",
                "payloadSummary": "Parameter list payload with one normalized parameter summary per parm on the resolved node.",
                "examples": [
                    {
                        "description": "Read all parameters for a display node.",
                        "uri": "houdini://nodes/obj/geo1/OUT/parms",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://nodes/{path}/geometry-summary",
                "name": "Node Geometry Summary",
                "description": "Read point, primitive, bbox, group, attribute, and material summaries for a node with cooked geometry. The resource follows display-node resolution when applicable.",
                "mimeType": "application/json",
                "payloadSummary": "Geometry facts for the resolved node, including counts, bbox, group names, attributes, and discovered material paths.",
                "examples": [
                    {
                        "description": "Inspect cooked geometry facts for an output SOP.",
                        "uri": "houdini://nodes/obj/geo1/OUT/geometry-summary",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://tasks/{task_id}",
                "name": "Task Resource",
                "description": "Read task state, progress, result, and failure details for a submitted long-running task such as a cook or render.",
                "mimeType": "application/json",
                "payloadSummary": "Single task snapshot with id, state, progress, timing, result, and error information.",
                "examples": [
                    {
                        "description": "Poll a running cook or render task.",
                        "uri": "houdini://tasks/0123456789abcdef",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://tasks/{task_id}/log",
                "name": "Task Log Resource",
                "description": "Read recent log lines for a submitted task. Use this alongside the task resource when polling cooks and renders.",
                "mimeType": "application/json",
                "payloadSummary": "Task log payload with recent timestamped log lines emitted by the task runner.",
                "examples": [
                    {
                        "description": "Fetch the task log while polling a render.",
                        "uri": "houdini://tasks/0123456789abcdef/log",
                    }
                ],
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
