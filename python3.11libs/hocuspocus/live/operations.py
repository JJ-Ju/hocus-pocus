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
from .monitor import SceneEventMonitor
from .ops.base import OperationBaseMixin
from .ops.high_level import HighLevelOperationsMixin
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
    TaskExecutionOperationsMixin,
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
        self._logger = logger.getChild("live.operations")

    def register(self, tools: ToolRegistry, resources: ResourceRegistry) -> None:
        tool_specs = [
            ("session.info", "Session Info", "Return server, host, and Houdini session information.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_info),
            ("session.list_operations", "List Operations", "List recent dispatcher operations and their state.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_list_operations),
            ("session.cancel_operation", "Cancel Operation", "Request cancellation for a queued or running operation.", {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"]}, {"destructiveHint": True}, self.session_cancel_operation),
            ("task.list", "List Tasks", "List recent long-running task records.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.task_list),
            ("task.cancel", "Cancel Task", "Request cancellation for a running or queued task.", {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}, {"destructiveHint": True}, self.task_cancel),
            ("scene.get_summary", "Scene Summary", "Return a compact summary of the current hip session.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_get_summary),
            ("scene.new", "New Scene", "Clear the current hip and start a new scene.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_new),
            ("scene.open_hip", "Open Hip", "Load a hip file into the current session.", {"type": "object", "properties": {"path": {"type": "string"}, "suppress_save_prompt": {"type": "boolean", "default": True}, "ignore_load_warnings": {"type": "boolean", "default": False}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_open_hip),
            ("scene.merge_hip", "Merge Hip", "Merge a hip file into the current scene.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_merge_hip),
            ("scene.save_hip", "Save Hip", "Save the current hip file or save as a new path.", {"type": "object", "properties": {"path": {"type": "string"}, "save_to_recent_files": {"type": "boolean", "default": True}}}, {"destructiveHint": True}, self.scene_save_hip),
            ("scene.undo", "Undo", "Undo the last Houdini operation.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_undo),
            ("scene.redo", "Redo", "Redo the last undone Houdini operation.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_redo),
            ("scene.create_turntable_camera", "Create Turntable Camera", "Create a target, rig, and camera suitable for a simple turntable animation.", {"type": "object", "properties": {"target_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "camera_name": {"type": "string", "default": "turntable_cam"}, "distance_multiplier": {"type": "number", "default": 2.5}}}, {"destructiveHint": True}, self.scene_create_turntable_camera),
            ("node.list", "List Nodes", "List child nodes under a parent network.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "recursive": {"type": "boolean", "default": False}, "max_items": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.node_list),
            ("node.get", "Get Node", "Return summary information for a node.", {"type": "object", "properties": {"path": {"type": "string"}, "include_parms": {"type": "boolean", "default": False}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.node_get),
            ("node.create", "Create Node", "Create a node under a given parent network path.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "node_type_name": {"type": "string"}, "node_name": {"type": "string"}, "run_init_scripts": {"type": "boolean", "default": True}, "load_contents": {"type": "boolean", "default": True}}, "required": ["node_type_name"]}, {"destructiveHint": True}, self.node_create),
            ("node.delete", "Delete Node", "Delete one or more nodes.", {"type": "object", "properties": {"path": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}}}, {"destructiveHint": True}, self.node_delete),
            ("node.rename", "Rename Node", "Rename a node.", {"type": "object", "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}, "unique_name": {"type": "boolean", "default": False}}, "required": ["path", "new_name"]}, {"destructiveHint": True}, self.node_rename),
            ("node.connect", "Connect Nodes", "Connect a source node to a destination node input.", {"type": "object", "properties": {"source_node_path": {"type": "string"}, "dest_node_path": {"type": "string"}, "dest_input_index": {"type": "integer", "default": 0}, "source_output_index": {"type": "integer", "default": 0}}, "required": ["source_node_path", "dest_node_path"]}, {"destructiveHint": True}, self.node_connect),
            ("node.disconnect", "Disconnect Node", "Disconnect one input or all inputs from a node.", {"type": "object", "properties": {"path": {"type": "string"}, "input_index": {"type": "integer"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_disconnect),
            ("node.move", "Move Node", "Set a node position in network editor space.", {"type": "object", "properties": {"path": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["path", "x", "y"]}, {"destructiveHint": True}, self.node_move),
            ("node.layout", "Layout Nodes", "Auto-layout child nodes inside a network.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "child_paths": {"type": "array", "items": {"type": "string"}}}}, {"destructiveHint": True}, self.node_layout),
            ("node.set_flags", "Set Node Flags", "Set common node flags such as bypass, display, and render.", {"type": "object", "properties": {"path": {"type": "string"}, "bypass": {"type": "boolean"}, "display": {"type": "boolean"}, "render": {"type": "boolean"}, "template": {"type": "boolean"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_set_flags),
            ("graph.batch_edit", "Batch Graph Edit", "Apply a grouped set of create/connect/parm/flag/layout operations with referenceable results.", {"type": "object", "properties": {"label": {"type": "string"}, "operations": {"type": "array", "items": {"type": "object"}}}, "required": ["operations"]}, {"destructiveHint": True}, self.graph_batch_edit),
            ("parm.list", "List Parameters", "List parameters on a node.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_list),
            ("parm.get", "Get Parameter", "Return metadata and value information for a parameter.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_get),
            ("parm.set", "Set Parameter", "Set a parameter value on a Houdini node.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "value": {}}, "required": ["parm_path", "value"]}, {"destructiveHint": True}, self.parm_set),
            ("parm.set_expression", "Set Parameter Expression", "Set an expression on a parameter.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "expression": {"type": "string"}, "language": {"type": "string", "default": "hscript"}}, "required": ["parm_path", "expression"]}, {"destructiveHint": True}, self.parm_set_expression),
            ("parm.press_button", "Press Button", "Press a button parameter.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_press_button),
            ("parm.revert_to_default", "Revert Parameter", "Revert a parameter to its default value.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_revert_to_default),
            ("selection.get", "Get Selection", "Return the currently selected nodes.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.selection_get),
            ("selection.set", "Set Selection", "Set the selected node paths.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "clear_existing": {"type": "boolean", "default": True}}, "required": ["paths"]}, {"destructiveHint": True}, self.selection_set),
            ("playbar.get_state", "Get Playbar State", "Return playbar frame and range information.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.playbar_get_state),
            ("playbar.set_frame", "Set Frame", "Set the current frame.", {"type": "object", "properties": {"frame": {"type": "number"}}, "required": ["frame"]}, {"destructiveHint": True}, self.playbar_set_frame),
            ("cook.node", "Cook Node", "Launch a non-blocking cook task for a Houdini node.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "force": {"type": "boolean", "default": False}}, "required": ["node_path"]}, {"destructiveHint": True}, self.cook_node),
            ("render.rop", "Render ROP", "Launch a non-blocking render task for a ROP node.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "ignore_inputs": {"type": "boolean", "default": False}, "verbose": {"type": "boolean", "default": True}}, "required": ["node_path"]}, {"destructiveHint": True}, self.render_rop),
            ("geometry.get_summary", "Geometry Summary", "Return bbox, counts, groups, and materials for a node with geometry.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.geometry_get_summary),
            ("model.create_house_blockout", "Create House Blockout", "Create a simple house blockout network under an object Geometry node.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "node_name": {"type": "string", "default": "house_blockout1"}}}, {"destructiveHint": True}, self.model_create_house_blockout),
            ("viewport.get_state", "Get Viewport State", "Return information about the current scene viewer viewport.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.viewport_get_state),
            ("camera.get_active", "Get Active Camera", "Return the active viewport camera or indicate that the viewport is using a perspective view.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.camera_get_active),
            ("viewport.capture", "Capture Viewport", "Capture the current viewport to an image file.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.viewport_capture),
            ("snapshot.capture_viewport", "Capture Viewport Snapshot", "Capture a viewport snapshot to an explicit or managed image file.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.snapshot_capture_viewport),
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
                )
            )

        resource_specs = [
            ("houdini://session/info", "Session Info", "Current session metadata and server state.", self.read_session_info),
            ("houdini://session/health", "Session Health", "Current dispatcher and monitor status.", self.read_session_health),
            ("houdini://session/conventions", "Session Conventions", "Houdini coordinate-system and snapshot conventions for this server.", self.read_session_conventions),
            ("houdini://session/scene-summary", "Scene Summary", "Current scene summary.", self.read_scene_summary),
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
                )
            )
