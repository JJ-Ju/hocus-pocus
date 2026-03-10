"""Live Houdini-backed tools and resources."""

from __future__ import annotations

import logging

from hocuspocus.core.mcp_types import (
    ResourceDefinition,
    ResourceRegistry,
    ToolDefinition,
    ToolRegistry,
)
from hocuspocus.core.settings import ServerSettings

from .dispatcher import LiveCommandDispatcher
from .graph_cache import LiveSceneGraphCache
from .monitor import SceneEventMonitor
from .ops.base import OperationBaseMixin
from .ops.export import ExportOperationsMixin
from .ops.graph import GraphOperationsMixin
from .ops.high_level import HighLevelOperationsMixin
from .ops.material import MaterialOperationsMixin
from .ops.node import NodeOperationsMixin
from .ops.parm import ParmOperationsMixin
from .ops.resources import ResourceOperationsMixin
from .ops.scene import SceneOperationsMixin
from .ops.session import SessionOperationsMixin
from .ops.tasks_ops import TaskExecutionOperationsMixin
from .ops.viewport import ViewportOperationsMixin
from .tasks import LiveTaskManager


class LiveOperations(
    OperationBaseMixin,
    SessionOperationsMixin,
    SceneOperationsMixin,
    NodeOperationsMixin,
    ParmOperationsMixin,
    MaterialOperationsMixin,
    TaskExecutionOperationsMixin,
    ExportOperationsMixin,
    GraphOperationsMixin,
    ViewportOperationsMixin,
    HighLevelOperationsMixin,
    ResourceOperationsMixin,
):
    def __init__(
        self,
        dispatcher: LiveCommandDispatcher,
        monitor: SceneEventMonitor,
        tasks: LiveTaskManager,
        settings: ServerSettings,
        logger: logging.Logger,
    ):
        self._dispatcher = dispatcher
        self._monitor = monitor
        self._tasks = tasks
        self._settings = settings
        self._graph = LiveSceneGraphCache(logger)
        self._logger = logger.getChild("live.operations")

    def register(self, tools: ToolRegistry, resources: ResourceRegistry) -> None:
        tool_specs = [
            ("session.info", "Session Info", "Return Houdini session state, server version, active operations, recent tasks, and orientation conventions. Use this as the top-level status read before mutating the scene.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_info),
            ("session.list_operations", "List Operations", "List recent live dispatcher operations, including request ids, states, and cancellation flags. This reflects request-scoped work rather than long-running task records.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_list_operations),
            ("session.cancel_operation", "Cancel Operation", "Request cancellation for a queued or running dispatcher operation by operation id. Prefer `task.cancel` for long-running cook or render tasks.", {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"]}, {"destructiveHint": True}, self.session_cancel_operation),
            ("task.list", "List Tasks", "List recent non-blocking task records such as cooks and renders. Use this to discover task ids for follow-up polling or cancellation.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.task_list),
            ("task.cancel", "Cancel Task", "Request cancellation for a queued or running long-running task by task id. Cancelled render tasks may leave partial output files on disk.", {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}, {"destructiveHint": True}, self.task_cancel),
            ("scene.get_summary", "Scene Summary", "Return a compact scene summary with hip path, dirty state, frame information, selection, and orientation conventions. Use this for a quick read before planning scene edits.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_get_summary),
            ("scene.new", "New Scene", "Start a new empty Houdini scene in the current session. This mutates the current session immediately and clears existing scene content.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_new),
            ("scene.open_hip", "Open Hip", "Load a hip file into the current Houdini session. This replaces the current scene and is destructive unless the scene is already disposable.", {"type": "object", "properties": {"path": {"type": "string"}, "suppress_save_prompt": {"type": "boolean", "default": True}, "ignore_load_warnings": {"type": "boolean", "default": False}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_open_hip),
            ("scene.merge_hip", "Merge Hip", "Merge a hip file into the current scene without replacing the session. Use this when you want incoming content added on top of the current graph.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_merge_hip),
            ("scene.save_hip", "Save Hip", "Save the current scene to the existing hip path or to a new explicit path. Output paths are validated against server write policy and approved roots before saving.", {"type": "object", "properties": {"path": {"type": "string"}, "save_to_recent_files": {"type": "boolean", "default": True}}}, {"destructiveHint": True}, self.scene_save_hip),
            ("scene.undo", "Undo", "Undo the last Houdini operation in the current session. This affects the live undo stack immediately.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_undo),
            ("scene.redo", "Redo", "Redo the last undone Houdini operation in the current session. This affects the live undo stack immediately.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_redo),
            ("scene.create_turntable_camera", "Create Turntable Camera", "Create a target null, rig null, and camera for a simple orbit shot under `/obj`. If `target_path` resolves to geometry, the orbit distance is derived from that geometry's bounds.", {"type": "object", "properties": {"target_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "camera_name": {"type": "string", "default": "turntable_cam"}, "distance_multiplier": {"type": "number", "default": 2.5}}}, {"destructiveHint": True}, self.scene_create_turntable_camera),
            ("node.list", "List Nodes", "List child nodes under a network path, optionally recursively. Use this for graph discovery when you know the parent network but not the child names.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "recursive": {"type": "boolean", "default": False}, "max_items": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.node_list),
            ("node.get", "Get Node", "Return summary information for a single node, including flags, inputs, display/render/output node pointers, and optionally parameter summaries. This is the primary structured node read tool.", {"type": "object", "properties": {"path": {"type": "string"}, "include_parms": {"type": "boolean", "default": False}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.node_get),
            ("node.create", "Create Node", "Create a Houdini node under a parent network and return the created node summary. The result includes the final resolved node path, which may differ from the requested name if Houdini renames it.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "node_type_name": {"type": "string"}, "node_name": {"type": "string"}, "run_init_scripts": {"type": "boolean", "default": True}, "load_contents": {"type": "boolean", "default": True}}, "required": ["node_type_name"]}, {"destructiveHint": True}, self.node_create),
            ("node.delete", "Delete Node", "Delete one or more nodes by explicit path. Provide either `path` or `paths`; set `ignore_missing = true` for idempotent cleanup behavior.", {"type": "object", "properties": {"path": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "ignore_missing": {"type": "boolean", "default": False}}}, {"destructiveHint": True}, self.node_delete),
            ("node.rename", "Rename Node", "Rename a node and return the updated node summary. Use `unique_name` when the requested name may already exist under the same parent.", {"type": "object", "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}, "unique_name": {"type": "boolean", "default": False}}, "required": ["path", "new_name"]}, {"destructiveHint": True}, self.node_rename),
            ("node.connect", "Connect Nodes", "Connect a source node output to a destination node input and return the destination node summary. This mutates only the destination input slot you specify.", {"type": "object", "properties": {"source_node_path": {"type": "string"}, "dest_node_path": {"type": "string"}, "dest_input_index": {"type": "integer", "default": 0}, "source_output_index": {"type": "integer", "default": 0}}, "required": ["source_node_path", "dest_node_path"]}, {"destructiveHint": True}, self.node_connect),
            ("node.disconnect", "Disconnect Node", "Disconnect one input or all inputs from a node and return the updated node summary. If `input_index` is omitted, all current inputs are cleared.", {"type": "object", "properties": {"path": {"type": "string"}, "input_index": {"type": "integer"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_disconnect),
            ("node.move", "Move Node", "Move a node in network-editor space by setting its graph position. This changes the node tile position, not the 3D transform.", {"type": "object", "properties": {"path": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["path", "x", "y"]}, {"destructiveHint": True}, self.node_move),
            ("node.layout", "Layout Nodes", "Auto-layout child nodes under a network and return the resulting child listing. If `child_paths` is omitted, all child nodes under the parent are laid out.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "child_paths": {"type": "array", "items": {"type": "string"}}}}, {"destructiveHint": True}, self.node_layout),
            ("node.set_flags", "Set Node Flags", "Set common node flags such as bypass, display, render, and template, then return the updated node summary. Flag support depends on the underlying Houdini node type.", {"type": "object", "properties": {"path": {"type": "string"}, "bypass": {"type": "boolean"}, "display": {"type": "boolean"}, "render": {"type": "boolean"}, "template": {"type": "boolean"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_set_flags),
            ("graph.query", "Query Graph", "Query the indexed scene graph by path prefix, root path, node type, category, flag, name fragment, or material assignment. This is the main structured graph search tool for agents.", {"type": "object", "properties": {"root_path": {"type": "string"}, "path_prefix": {"type": "string"}, "node_type_name": {"type": "string"}, "category": {"type": "string"}, "name_contains": {"type": "string"}, "material_path": {"type": "string"}, "flag_name": {"type": "string"}, "flag_value": {"type": "boolean"}, "limit": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_query),
            ("graph.find_upstream", "Find Upstream", "Traverse upstream structural input edges from a starting node path using the indexed scene graph. Use this to understand what feeds a node.", {"type": "object", "properties": {"path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_upstream),
            ("graph.find_downstream", "Find Downstream", "Traverse downstream structural input edges from a starting node path using the indexed scene graph. Use this to understand what a node drives.", {"type": "object", "properties": {"path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_downstream),
            ("graph.find_by_type", "Find Nodes By Type", "Return indexed graph nodes that match a Houdini node type name, optionally under a root path.", {"type": "object", "properties": {"node_type_name": {"type": "string"}, "root_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["node_type_name"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_by_type),
            ("graph.find_by_flag", "Find Nodes By Flag", "Return indexed graph nodes that match a named Houdini flag such as `display`, `render`, `bypass`, or `template`.", {"type": "object", "properties": {"flag_name": {"type": "string"}, "flag_value": {"type": "boolean", "default": True}, "root_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["flag_name"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_by_flag),
            ("graph.batch_edit", "Batch Graph Edit", "Apply a grouped set of node, parm, flag, move, connect, and layout operations in one live request and one undo block. Later operations may reference earlier results via `$ref:<id>` and `$ref:<id>/suffix`; set `transactional = true` to roll back the whole batch on failure.", {"type": "object", "properties": {"label": {"type": "string"}, "transactional": {"type": "boolean", "default": False}, "operations": {"type": "array", "items": {"type": "object"}}}, "required": ["operations"]}, {"destructiveHint": True}, self.graph_batch_edit),
            ("scene.diff", "Diff Scene Graph", "Diff the current indexed scene graph against a previously captured baseline graph snapshot. Use this to compare before and after states outside the live undo stack.", {"type": "object", "properties": {"baseline": {"type": "object"}}, "required": ["baseline"]}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_diff),
            ("graph.diff_subgraph", "Diff Subgraph", "Diff a current rooted subgraph against a previously captured baseline subgraph snapshot.", {"type": "object", "properties": {"root_path": {"type": "string"}, "baseline": {"type": "object"}}, "required": ["root_path", "baseline"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_diff_subgraph),
            ("graph.plan_edit", "Plan Graph Edit", "Simulate a grouped graph patch against the current indexed scene graph and return the predicted diff without mutating Houdini. This uses the same operation shapes as `graph.batch_edit`.", {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object"}}}, "required": ["operations"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_plan_edit),
            ("graph.apply_patch", "Apply Graph Patch", "Apply a graph patch using the current batch-edit execution path. Set `dry_run = true` to return only the predicted plan and diff.", {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object"}}, "patch": {"type": "object"}, "transactional": {"type": "boolean", "default": True}, "dry_run": {"type": "boolean", "default": False}, "label": {"type": "string"}}, "required": []}, {"destructiveHint": True}, self.graph_apply_patch),
            ("parm.list", "List Parameters", "List all parameters on a node and return normalized parameter summaries. Use this when you know the node path but not the parm names.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_list),
            ("parm.get", "Get Parameter", "Return metadata and value information for a single parameter path. This is the primary structured parameter read tool.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_get),
            ("parm.set", "Set Parameter", "Set a parameter value and return the updated parameter summary. This works for standard value assignment, not expression assignment.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "value": {}}, "required": ["parm_path", "value"]}, {"destructiveHint": True}, self.parm_set),
            ("parm.set_expression", "Set Parameter Expression", "Set an HScript or Python expression on a parameter and return the updated parameter summary. Use `language = python` to force Python expression mode.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "expression": {"type": "string"}, "language": {"type": "string", "default": "hscript"}}, "required": ["parm_path", "expression"]}, {"destructiveHint": True}, self.parm_set_expression),
            ("parm.press_button", "Press Button", "Press a button parameter and return the resulting parameter summary. Use this for operator actions implemented as button parms.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_press_button),
            ("parm.revert_to_default", "Revert Parameter", "Revert a parameter to its default value and return the updated parameter summary. This is useful for clearing previous edits or expressions.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_revert_to_default),
            ("material.create", "Create Material", "Create a material node, defaulting to a Principled Shader under `/mat`, and optionally apply common lookdev properties such as base color, roughness, and metallic. This is the quickest way to create a usable material without manually building the network.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/mat"}, "material_type_name": {"type": "string"}, "node_name": {"type": "string"}, "base_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "roughness": {"type": "number"}, "metallic": {"type": "number"}, "emission_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "emission_intensity": {"type": "number"}, "opacity": {"type": "number"}}}, {"destructiveHint": True}, self.material_create),
            ("material.update", "Update Material", "Update common lookdev properties on an existing material node and return the updated material summary. Unsupported properties are reported as skipped rather than causing a silent partial write.", {"type": "object", "properties": {"material_path": {"type": "string"}, "base_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "roughness": {"type": "number"}, "metallic": {"type": "number"}, "emission_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "emission_intensity": {"type": "number"}, "opacity": {"type": "number"}}, "required": ["material_path"]}, {"destructiveHint": True}, self.material_update),
            ("material.assign", "Assign Material", "Assign a material to a target node by resolving the nearest owner with a `shop_materialpath` parameter. For SOP targets inside a geometry object, this assigns at the object-material level and returns the affected owner node.", {"type": "object", "properties": {"target_node_path": {"type": "string"}, "material_path": {"type": "string"}}, "required": ["target_node_path", "material_path"]}, {"destructiveHint": True}, self.material_assign),
            ("selection.get", "Get Selection", "Return the currently selected node paths in the live Houdini session. This reads scene state only and does not affect the selection.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.selection_get),
            ("selection.set", "Set Selection", "Set the selected node paths in the live Houdini session. If `clear_existing` is true, the previous node selection is cleared first.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "clear_existing": {"type": "boolean", "default": True}}, "required": ["paths"]}, {"destructiveHint": True}, self.selection_set),
            ("playbar.get_state", "Get Playbar State", "Return current frame, FPS, and playbar ranges from the live Houdini session. This is useful for frame-aware task planning.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.playbar_get_state),
            ("playbar.set_frame", "Set Frame", "Set the current Houdini frame and return the updated playbar state. This mutates the live session time.", {"type": "object", "properties": {"frame": {"type": "number"}}, "required": ["frame"]}, {"destructiveHint": True}, self.playbar_set_frame),
            ("cook.node", "Cook Node", "Start a non-blocking cook task for a Houdini node and return a task handle immediately. Poll `houdini://tasks/{task_id}` and `houdini://tasks/{task_id}/log` for progress and result data.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "force": {"type": "boolean", "default": False}}, "required": ["node_path"]}, {"destructiveHint": True}, self.cook_node),
            ("render.rop", "Render ROP", "Start a non-blocking render task for a ROP node and return a task handle immediately. Output paths are validated against server write policy before the render starts.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "ignore_inputs": {"type": "boolean", "default": False}, "verbose": {"type": "boolean", "default": True}}, "required": ["node_path"]}, {"destructiveHint": True}, self.render_rop),
            ("export.alembic", "Export Alembic", "Start a non-blocking Alembic export task for a SOP node or a geometry object with a display SOP. If `path` is omitted, HocusPocus writes to a managed export path under its output directory.", {"type": "object", "properties": {"source_node_path": {"type": "string"}, "path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "root_path": {"type": "string", "default": "/obj"}}, "required": ["source_node_path"]}, {"destructiveHint": True}, self.export_alembic),
            ("export.usd", "Export USD", "Start a non-blocking USD export task for a LOP node. If `path` is omitted, HocusPocus writes to a managed export path under its output directory.", {"type": "object", "properties": {"node_path": {"type": "string"}, "path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}}, "required": ["node_path"]}, {"destructiveHint": True}, self.export_usd),
            ("geometry.get_summary", "Geometry Summary", "Return geometry facts for a node with cooked geometry, including counts, bbox, groups, attributes, and discovered material paths. This is the fastest geometry-level reasoning tool for agents.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.geometry_get_summary),
            ("model.create_house_blockout", "Create House Blockout", "Create a simple house blockout network under an object Geometry node and return the house and output node summaries. This is a proof-point high-level modeling macro rather than a general-purpose builder.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "node_name": {"type": "string", "default": "house_blockout1"}}}, {"destructiveHint": True}, self.model_create_house_blockout),
            ("viewport.get_state", "Get Viewport State", "Return scene viewer, viewport, and current camera information for the active viewport. Use this before snapshot or camera-sensitive operations.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.viewport_get_state),
            ("camera.get_active", "Get Active Camera", "Return the active viewport camera path, or indicate that the viewport is in perspective mode. This is a read-only camera-context check for snapshot and turntable workflows.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.camera_get_active),
            ("viewport.capture", "Capture Viewport", "Capture the current scene viewer viewport to an image file. If `path` is omitted, HocusPocus writes to a managed snapshot path and returns it.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.viewport_capture),
            ("snapshot.capture_viewport", "Capture Viewport Snapshot", "Capture the current scene viewer viewport to an explicit path or a managed snapshot path. Managed snapshots are written under the server snapshot output directory and returned in the result.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.snapshot_capture_viewport),
        ]
        for name, title, description, input_schema, annotations, handler in tool_specs:
            tools.register(
                ToolDefinition(
                    name=name,
                    title=title,
                    description=description,
                    input_schema=input_schema,
                    annotations=annotations,
                    required_capabilities=self._tool_capabilities(name),
                    handler=handler,
                    output_summary=self._tool_output_summary(name),
                    execution_hint=self._tool_execution_hint(name),
                    examples=self._tool_examples(name),
                )
            )

        resource_specs = [
            ("houdini://session/info", "Session Info", "Current session metadata and server state.", self.read_session_info),
            ("houdini://session/health", "Session Health", "Current dispatcher and monitor status.", self.read_session_health),
            ("houdini://session/conventions", "Session Conventions", "Houdini coordinate-system and snapshot conventions for this server.", self.read_session_conventions),
            ("houdini://session/scene-summary", "Scene Summary", "Current scene summary.", self.read_scene_summary),
            ("houdini://graph/scene", "Scene Graph", "Indexed whole-scene graph snapshot.", self.read_graph_scene),
            ("houdini://graph/index", "Graph Index", "Indexed scene-graph cache metadata and revision state.", self.read_graph_index),
            ("houdini://session/selection", "Selection", "Current node selection.", self.read_selection),
            ("houdini://session/playbar", "Playbar", "Current playbar state.", self.read_playbar),
            ("houdini://session/operations", "Operations", "Recent dispatcher operations and cancellation state.", self.read_operations),
            ("houdini://tasks/recent", "Recent Tasks", "Recent task records and progress state.", self.read_tasks_recent),
        ]
        for uri, name, description, reader in resource_specs:
            resources.register(
                ResourceDefinition(
                    uri=uri,
                    name=name,
                    description=description,
                    mime_type="application/json",
                    reader=reader,
                    payload_summary=self._resource_payload_summary(uri),
                    examples=self._resource_examples(uri),
                )
            )

    @staticmethod
    def _tool_output_summary(name: str) -> str:
        summaries = {
            "session.info": "Structured session status with version, hip state, active operations, recent tasks, and conventions.",
            "task.list": "List of task records with ids, states, progress, and metadata.",
            "task.cancel": "Task cancellation acknowledgement plus the latest known task snapshot.",
            "node.get": "Single normalized node summary, optionally including parameter summaries.",
            "node.create": "Created node summary with final resolved path and flag state.",
            "node.delete": "Counts plus separate deleted and skipped path arrays.",
            "graph.query": "List of indexed graph nodes that match structural filters.",
            "graph.find_upstream": "Traversal result with the starting node, upstream nodes, and traversed edges.",
            "graph.find_downstream": "Traversal result with the starting node, downstream nodes, and traversed edges.",
            "graph.find_by_type": "List of indexed graph nodes that match a type name.",
            "graph.find_by_flag": "List of indexed graph nodes that match a flag value.",
            "graph.batch_edit": "Batch result with refs, per-step results, and failure metadata when the batch errors.",
            "scene.diff": "Graph diff between a baseline scene snapshot and the current scene graph.",
            "graph.diff_subgraph": "Graph diff between a baseline subgraph snapshot and the current rooted subgraph.",
            "graph.plan_edit": "Predicted graph diff, planned refs, and simulated results for a patch without mutation.",
            "graph.apply_patch": "Predicted plan plus actual batch execution result and post-apply revision.",
            "parm.get": "Single normalized parameter summary including raw value, evaluated value, and expression.",
            "material.create": "Created material summary plus applied and skipped material property names.",
            "material.update": "Updated material summary plus applied and skipped material property names.",
            "material.assign": "Assignment result with target node, assignment owner node, material summary, and geometry summary when available.",
            "cook.node": "Immediate task handle for a non-blocking cook plus task resource URIs.",
            "render.rop": "Immediate task handle for a non-blocking render plus task resource URIs.",
            "export.alembic": "Immediate task handle for a non-blocking Alembic export plus task resource URIs.",
            "export.usd": "Immediate task handle for a non-blocking USD export plus task resource URIs.",
            "geometry.get_summary": "Geometry counts, bbox, groups, attributes, discovered material paths, and object-level material path when present.",
            "scene.create_turntable_camera": "Camera, rig, and target node summaries plus the animated frame range.",
            "snapshot.capture_viewport": "Viewport image path, viewport name, and whether the output path was managed by the server.",
            "model.create_house_blockout": "House object summary, output node summary, and named refs for created subnodes.",
        }
        return summaries.get(name, "")

    @staticmethod
    def _tool_execution_hint(name: str) -> str:
        if name in {"cook.node", "render.rop", "export.alembic", "export.usd"}:
            return "non_blocking_task"
        return "blocking"

    @staticmethod
    def _tool_examples(name: str) -> list[dict[str, object]]:
        examples = {
            "graph.batch_edit": [
                {
                    "description": "Create and wire a small SOP chain with transactional rollback.",
                    "arguments": {
                        "transactional": True,
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "batch_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                            {"type": "create_node", "id": "out", "parent_path": "$ref:geo", "node_type_name": "null", "node_name": "OUT"},
                            {"type": "connect", "source_node_path": "$ref:box", "dest_node_path": "$ref:out"},
                            {"type": "set_flags", "path": "$ref:out", "display": True, "render": True},
                        ],
                    },
                }
            ],
            "graph.query": [
                {
                    "description": "Find display-flagged null nodes under a geometry object.",
                    "arguments": {"root_path": "/obj/geo1", "node_type_name": "null", "flag_name": "display", "flag_value": True},
                }
            ],
            "graph.plan_edit": [
                {
                    "description": "Preview a simple SOP chain before applying it.",
                    "arguments": {
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "planned_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                            {"type": "create_node", "id": "out", "parent_path": "$ref:geo", "node_type_name": "null", "node_name": "OUT"},
                            {"type": "connect", "source_node_path": "$ref:box", "dest_node_path": "$ref:out"},
                        ],
                    },
                }
            ],
            "graph.apply_patch": [
                {
                    "description": "Apply a transactional graph patch after previewing it.",
                    "arguments": {
                        "transactional": True,
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "patched_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                        ],
                    },
                }
            ],
            "cook.node": [
                {
                    "description": "Cook a displayable SOP output over a single frame.",
                    "arguments": {"node_path": "/obj/geo1/OUT", "frame_range": [1, 1], "force": True},
                }
            ],
            "render.rop": [
                {
                    "description": "Render a Geometry ROP over a frame range.",
                    "arguments": {"node_path": "/out/geo_rop1", "frame_range": [1, 24], "ignore_inputs": False, "verbose": True},
                }
            ],
            "export.alembic": [
                {
                    "description": "Export a SOP output to Alembic using a managed export path.",
                    "arguments": {"source_node_path": "/obj/geo1/OUT", "frame_range": [1, 24]},
                }
            ],
            "export.usd": [
                {
                    "description": "Export a LOP node to USD using a managed export path.",
                    "arguments": {"node_path": "/stage/usd_rop_source1", "frame_range": [1, 24]},
                }
            ],
            "material.create": [
                {
                    "description": "Create a principled material with a warm base color.",
                    "arguments": {"node_name": "wall_mat", "base_color": [0.8, 0.7, 0.6], "roughness": 0.45},
                }
            ],
            "material.assign": [
                {
                    "description": "Assign a material to a geometry object or SOP-owned object material parm.",
                    "arguments": {"target_node_path": "/obj/geo1/OUT", "material_path": "/mat/wall_mat"},
                }
            ],
            "snapshot.capture_viewport": [
                {
                    "description": "Capture the current viewport to a managed output path.",
                    "arguments": {},
                }
            ],
            "scene.create_turntable_camera": [
                {
                    "description": "Create a turntable rig around a displayable SOP output.",
                    "arguments": {"target_path": "/obj/geo1/OUT", "camera_name": "turntable_cam", "frame_range": [1, 120]},
                }
            ],
            "model.create_house_blockout": [
                {
                    "description": "Create a simple house blockout under `/obj`.",
                    "arguments": {"parent_path": "/obj", "node_name": "house_blockout1"},
                }
            ],
        }
        return examples.get(name, [])

    @staticmethod
    def _resource_payload_summary(uri: str) -> str:
        summaries = {
            "houdini://session/info": "Session-wide status payload with version, active operations, recent tasks, and conventions.",
            "houdini://session/health": "Dispatcher, monitor, and recent-task health snapshot.",
            "houdini://session/conventions": "Coordinate-system and snapshot behavior notes for agent planning.",
            "houdini://session/scene-summary": "Compact scene summary with hip state, frame, and selection.",
            "houdini://graph/scene": "Whole-scene graph snapshot with indexed nodes, parms, edges, and material assignments.",
            "houdini://graph/index": "Graph-cache metadata including revision, counts, and refresh timing.",
            "houdini://session/selection": "Current selected node paths.",
            "houdini://session/playbar": "Current frame, FPS, and playbar ranges.",
            "houdini://session/operations": "Recent request-scoped operation records.",
            "houdini://tasks/recent": "Recent task records for cooks, renders, and other long-running work.",
        }
        return summaries.get(uri, "")

    @staticmethod
    def _resource_examples(uri: str) -> list[dict[str, object]]:
        examples = {
            "houdini://tasks/recent": [
                {"description": "Inspect recent cook and render task state after launching non-blocking work."}
            ],
            "houdini://session/info": [
                {"description": "Read top-level session state before planning graph edits or viewport captures."}
            ],
            "houdini://graph/scene": [
                {"description": "Load the current indexed scene graph as a single resource snapshot."}
            ],
        }
        return examples.get(uri, [])
