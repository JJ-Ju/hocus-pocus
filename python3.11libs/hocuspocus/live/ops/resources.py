"""Resource reads and dynamic resource templates."""

from __future__ import annotations

from ..context import RequestContext


class ResourceOperationsMixin:
    def read_session_info(self, context: RequestContext) -> dict[str, object]:
        data = self._call_live(self._session_info_impl, context)
        data["grantedCapabilities"] = sorted(set(context.permissions))
        return self._resource_response(
            "houdini://session/info",
            data,
        )

    def read_session_health(self, context: RequestContext) -> dict[str, object]:
        data = {
            "dispatcherMode": self._dispatcher.mode,
            "auth": {
                "tokenMode": self._settings.token_mode,
                "tokenEnabled": self._settings.token_mode != "disabled",
                "authRequired": self._settings.token_mode != "disabled",
            },
            "policy": {
                "effectivePolicy": self._settings.effective_policy_payload(),
                "availableProfiles": self._settings.available_policy_profiles_payload(),
                "grantedCapabilities": sorted(set(context.permissions)),
            },
            "settings": {
                "host": self._settings.host,
                "port": self._settings.port,
                "tokenMode": self._settings.token_mode,
            },
            "monitor": self._monitor.snapshot(),
            "graph": self._graph.stats(),
            "graphStore": self._graph_store.stats(),
            "activeOperations": self._dispatcher.operations_snapshot(limit=20),
            "recentTasks": self._tasks.snapshots(limit=20),
        }
        return self._resource_response("houdini://session/health", data)

    def read_session_policy(self, context: RequestContext) -> dict[str, object]:
        return self._resource_response(
            "houdini://session/policy",
            {
                "effectivePolicy": self._settings.effective_policy_payload(),
                "availableProfiles": self._settings.available_policy_profiles_payload(),
                "grantedCapabilities": sorted(set(context.permissions)),
            },
        )

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
        resolvers = (
            self._read_document_dynamic_resource,
            self._read_product_dynamic_resource,
            self._read_graph_dynamic_resource,
            self._read_task_or_node_dynamic_resource,
        )
        for resolver in resolvers:
            payload = resolver(uri, context)
            if payload is not None:
                return payload
        return None

    def _read_document_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        exact = {
            "houdini://documents/scene": self.read_document_scene,
            "houdini://documents/schema/network-document/v1": self.read_document_schema,
            "houdini://documents/schema/network-document/v2": self.read_document_schema_v2,
        }
        reader = exact.get(uri)
        if reader is not None:
            return reader(context)
        prefixes = (
            ("houdini://documents/checkouts/", self.read_document_checkout),
            ("houdini://documents/diagnostics/", self.read_document_diagnostics),
            ("houdini://documents/previews/", self.read_document_preview),
            ("houdini://documents/plans/", self.read_apply_plan),
        )
        for prefix, dynamic_reader in prefixes:
            identifier = uri.removeprefix(prefix).strip("/") if uri.startswith(prefix) else ""
            if identifier:
                return dynamic_reader(identifier, context)
        prefix = "houdini://documents/network/"
        if uri.startswith(prefix):
            raw = uri.removeprefix(prefix).strip("/")
            node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}") if raw else None
            if node_path is not None:
                return self.read_document_network(node_path, context)
        return None

    def _read_product_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        exact = {
            "houdini://graph/scene": self.read_graph_scene,
            "houdini://graph/index": self.read_graph_index,
            "houdini://dependencies/scene": self.read_scene_dependencies,
            "houdini://caches/topology": self.read_cache_topology,
            "houdini://packages/preview": self.read_package_preview,
            "houdini://scene/events": self.read_scene_events,
        }
        reader = exact.get(uri)
        if reader is not None:
            return reader(context)
        prefixed = (
            ("houdini://usd/stage/", self.read_usd_stage_summary),
            ("houdini://pdg/graph/", self.read_pdg_graph_state),
            ("houdini://renders/graph/", self.read_render_graph),
        )
        for prefix, dynamic_reader in prefixed:
            raw = uri.removeprefix(prefix).strip("/") if uri.startswith(prefix) else ""
            node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}") if raw else None
            if node_path is not None:
                return dynamic_reader(node_path, context)
        return None

    def _read_graph_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        routes = (
            ("houdini://graph/subgraph/", self._graph_subgraph_payload),
            ("houdini://graph/dependencies/", self._graph_dependency_payload),
            ("houdini://graph/references/", self._graph_reference_payload),
        )
        for prefix, payload_builder in routes:
            raw = uri.removeprefix(prefix).strip("/") if uri.startswith(prefix) else ""
            node_path = self._dynamic_node_uri_to_path(f"houdini://nodes/{raw}") if raw else None
            if node_path is not None:
                return self._resource_response(
                    uri,
                    self._call_live(
                        lambda node_path=node_path, payload_builder=payload_builder: payload_builder(
                            self._graph_snapshot(), node_path
                        ),
                        context,
                    ),
                )
        return None

    def _read_task_or_node_dynamic_resource(
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
        node_routes = (
            ("/geometry-summary", self._node_geometry_resource_impl),
            ("/parms", self._node_parms_resource_impl),
            (None, self._node_resource_impl),
        )
        for suffix, payload_builder in node_routes:
            node_path = self._dynamic_node_uri_to_path(uri, suffix) if suffix else self._dynamic_node_uri_to_path(uri)
            if node_path is not None:
                return self._resource_response(
                    uri,
                    self._call_live(
                        lambda node_path=node_path, payload_builder=payload_builder: payload_builder(node_path),
                        context,
                    ),
                )
        return None

    def resource_templates_payload(self) -> list[dict[str, object]]:
        return [
            {
                "uriTemplate": "houdini://documents/scene",
                "name": "Scene Document",
                "description": "Read the scene manifest over root document-capable Houdini networks.",
                "mimeType": "application/json",
                "payloadSummary": "Scene document with root network document links plus hip and graph metadata.",
                "examples": [
                    {
                        "description": "Read the scene manifest before choosing a network document to edit.",
                        "uri": "houdini://documents/scene",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/network/{path}",
                "name": "Network Document",
                "description": "Read a canonical network document for a Houdini network or subnetwork path. `{path}` uses the same slash-separated or percent-encoded path rules as node resources.",
                "mimeType": "application/json",
                "payloadSummary": "Canonical network document with nodes, edges, parameter bindings, code blobs, and diagnostics.",
                "examples": [
                    {
                        "description": "Read a SOP network document for a geometry object.",
                        "uri": "houdini://documents/network/obj/geo1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/schema/network-document/v1",
                "name": "Network Document Schema v1",
                "description": "Read the locked machine-readable schema for the first-wave network document contract.",
                "mimeType": "application/json",
                "payloadSummary": "JSON Schema for `hocuspocus://schemas/network-document/v1`.",
                "examples": [
                    {
                        "description": "Inspect the locked schema before generating or editing a network document.",
                        "uri": "houdini://documents/schema/network-document/v1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/schema/network-document/v2",
                "name": "Network Document Schema v2",
                "description": "Read the strict typed-value network document contract.",
                "mimeType": "application/json",
                "payloadSummary": "JSON Schema for `hocuspocus://schemas/network-document/v2`.",
                "examples": [{
                    "description": "Inspect the typed-value document schema.",
                    "uri": "houdini://documents/schema/network-document/v2",
                }],
            },
            {
                "uriTemplate": "houdini://documents/checkouts/{checkout_id}",
                "name": "Checkout Document",
                "description": "Read the current working document stored for a checkout created by `document.checkout`.",
                "mimeType": "application/json",
                "payloadSummary": "Working network document payload for a checkout id.",
                "examples": [
                    {
                        "description": "Read the working document for a checkout after editing it offline.",
                        "uri": "houdini://documents/checkouts/01234567-89ab-cdef-0123-456789abcdef",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/diagnostics/{checkout_id}",
                "name": "Checkout Diagnostics",
                "description": "Read the latest validation or apply diagnostics stored for a checkout.",
                "mimeType": "application/json",
                "payloadSummary": "Diagnostic report payload for a checkout id.",
                "examples": [
                    {
                        "description": "Read validation diagnostics for a checkout after calling `document.validate`.",
                        "uri": "houdini://documents/diagnostics/01234567-89ab-cdef-0123-456789abcdef",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/previews/{preview_id}",
                "name": "HocusScript Document Preview",
                "description": "Read a content-addressed HS3 document preview artifact produced by `document.preview_bundle`.",
                "mimeType": "application/json",
                "payloadSummary": "Canonical document, diff, destructive summary, preview-only candidate plan, provenance, source maps, and diagnostics.",
                "examples": [
                    {
                        "description": "Read a large preview artifact by the URI returned from document.preview_bundle.",
                        "uri": "houdini://documents/previews/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://documents/plans/{plan_id}",
                "name": "Immutable HocusScript Apply Plan",
                "description": "Read a stored, integrity-checked HS4 apply plan by the URI returned from document.plan_bundle.",
                "mimeType": "application/json",
                "payloadSummary": "Versioned apply plan envelope, guards, normalized operations, inverse plan, and expiry without the confirmation secret.",
                "examples": [{"description": "Inspect a stored plan before guarded apply.", "uri": "houdini://documents/plans/01234567-89ab-cdef-0123-456789abcdef"}],
            },
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
                "uriTemplate": "houdini://usd/stage/{path}",
                "name": "USD Stage Summary",
                "description": "Read a composed USD stage summary for a LOP node path. `{path}` uses the same slash-separated or percent-encoded path rules as node resources.",
                "mimeType": "application/json",
                "payloadSummary": "Composed USD stage summary including layers, default prim, prim count, and prim-path sample.",
                "examples": [
                    {
                        "description": "Inspect a Solaris stage at a LOP output node.",
                        "uri": "houdini://usd/stage/stage/layerbreak1",
                    }
                ],
            },
            {
                "uriTemplate": "houdini://pdg/graph/{path}",
                "name": "PDG Graph State",
                "description": "Read graph summary plus work-item state for a TOP network path. `{path}` uses the same slash-separated or percent-encoded path rules as node resources.",
                "mimeType": "application/json",
                "payloadSummary": "PDG graph summary with work-item states for the TOP network.",
                "examples": [
                    {
                        "description": "Inspect a TOP network graph state resource.",
                        "uri": "houdini://pdg/graph/tasks/topnet1",
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
