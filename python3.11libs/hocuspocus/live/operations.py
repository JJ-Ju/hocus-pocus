"""Live Houdini-backed tools and resources."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.mcp_types import (
    ResourceDefinition,
    ResourceRegistry,
    ToolDefinition,
    ToolRegistry,
)
from hocuspocus.core.policy import EDIT_SCENE, OBSERVE, WRITE_FILES, ensure_path_allowed
from hocuspocus.core.settings import ServerSettings
from hocuspocus.version import __version__

from .context import RequestContext
from .dispatcher import LiveCommandDispatcher
from .monitor import SceneEventMonitor

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore


class LiveOperations:
    def __init__(
        self,
        dispatcher: LiveCommandDispatcher,
        monitor: SceneEventMonitor,
        settings: ServerSettings,
        logger: logging.Logger,
    ):
        self._dispatcher = dispatcher
        self._monitor = monitor
        self._settings = settings
        self._logger = logger.getChild("live.operations")

    def register(self, tools: ToolRegistry, resources: ResourceRegistry) -> None:
        tool_specs = [
            ("session.info", "Session Info", "Return server, host, and Houdini session information.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_info),
            ("session.list_operations", "List Operations", "List recent dispatcher operations and their state.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_list_operations),
            ("session.cancel_operation", "Cancel Operation", "Request cancellation for a queued or running operation.", {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"]}, {"destructiveHint": True}, self.session_cancel_operation),
            ("scene.get_summary", "Scene Summary", "Return a compact summary of the current hip session.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_get_summary),
            ("scene.new", "New Scene", "Clear the current hip and start a new scene.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_new),
            ("scene.open_hip", "Open Hip", "Load a hip file into the current session.", {"type": "object", "properties": {"path": {"type": "string"}, "suppress_save_prompt": {"type": "boolean", "default": True}, "ignore_load_warnings": {"type": "boolean", "default": False}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_open_hip),
            ("scene.merge_hip", "Merge Hip", "Merge a hip file into the current scene.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_merge_hip),
            ("scene.save_hip", "Save Hip", "Save the current hip file or save as a new path.", {"type": "object", "properties": {"path": {"type": "string"}, "save_to_recent_files": {"type": "boolean", "default": True}}}, {"destructiveHint": True}, self.scene_save_hip),
            ("scene.undo", "Undo", "Undo the last Houdini operation.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_undo),
            ("scene.redo", "Redo", "Redo the last undone Houdini operation.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_redo),
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
            ("viewport.get_state", "Get Viewport State", "Return information about the current scene viewer viewport.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.viewport_get_state),
            ("camera.get_active", "Get Active Camera", "Return the active viewport camera or indicate that the viewport is using a perspective view.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.camera_get_active),
            ("viewport.capture", "Capture Viewport", "Capture the current viewport to an image file.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.viewport_capture),
            ("snapshot.capture_viewport", "Capture Viewport Snapshot", "Capture a viewport snapshot to an image file.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.snapshot_capture_viewport),
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

    def _call_live(self, callback: Any, context: RequestContext) -> dict[str, Any]:
        return self._dispatcher.call(callback, context)

    def _require_hou(self) -> Any:
        if hou is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                "This tool requires a Houdini session with the hou module available.",
            )
        return hou

    def _require_ui(self) -> Any:
        hou_module = self._require_hou()
        if not hou_module.isUIAvailable():
            raise JsonRpcError(
                INVALID_PARAMS,
                "This tool requires a Houdini UI session.",
            )
        return hou_module

    @staticmethod
    def _tool_response(summary: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": summary}],
            "structuredContent": payload,
            "isError": False,
        }

    @staticmethod
    def _resource_response(uri: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(payload, ensure_ascii=True),
                }
            ]
        }

    @staticmethod
    def _safe_value(getter: Any, default: Any = None) -> Any:
        try:
            return getter()
        except Exception:
            return default

    def _safe_method_value(
        self,
        obj: Any,
        method_name: str,
        default: Any = None,
    ) -> Any:
        method = getattr(obj, method_name, None)
        if method is None:
            return default
        return self._safe_value(method, default)

    def _node_flags(self, node: Any) -> dict[str, Any]:
        return {
            "bypass": self._safe_method_value(node, "isBypassed", False),
            "display": self._safe_method_value(node, "isDisplayFlagSet", None),
            "render": self._safe_method_value(node, "isRenderFlagSet", None),
            "template": self._safe_method_value(node, "isTemplateFlagSet", None),
        }

    def _parm_summary(self, parm: Any) -> dict[str, Any]:
        return {
            "name": parm.name(),
            "path": parm.path(),
            "nodePath": self._safe_value(lambda: parm.node().path(), None),
            "label": self._safe_value(lambda: parm.parmTemplate().label(), parm.name()),
            "rawValue": self._safe_value(parm.rawValue, None),
            "value": self._safe_value(parm.eval, None),
            "expression": self._safe_value(parm.expression, None),
        }

    def _node_summary(self, node: Any, *, include_parms: bool = False) -> dict[str, Any]:
        display_node = self._safe_method_value(node, "displayNode", None)
        render_node = self._safe_method_value(node, "renderNode", None)
        output_node = self._safe_method_value(node, "outputNode", None)
        payload = {
            "path": node.path(),
            "name": node.name(),
            "typeName": self._safe_value(lambda: node.type().name(), None),
            "category": self._safe_value(lambda: node.type().category().name(), None),
            "parentPath": self._safe_value(lambda: node.parent().path(), None),
            "isNetwork": self._safe_value(node.isNetwork, False),
            "position": self._safe_value(
                lambda: [float(node.position()[0]), float(node.position()[1])],
                None,
            ),
            "flags": self._node_flags(node),
            "inputs": [
                input_node.path() if input_node is not None else None
                for input_node in self._safe_value(node.inputs, []) or []
            ],
            "childCount": len(self._safe_value(node.children, []) or []),
            "displayNodePath": display_node.path() if display_node is not None else None,
            "renderNodePath": render_node.path() if render_node is not None else None,
            "outputNodePath": output_node.path() if output_node is not None else None,
        }
        if include_parms:
            payload["parms"] = [self._parm_summary(parm) for parm in node.parms()]
        return payload

    def _require_node_by_path(self, node_path: str, *, label: str = "path") -> Any:
        hou_module = self._require_hou()
        node_path = str(node_path).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, f"{label} is required")
        node = hou_module.node(node_path)
        if node is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Node not found: {node_path}",
                {
                    "path": node_path,
                    "expectedFormat": "/obj/geo1 or /obj/geo1/node1",
                },
            )
        return node

    def _require_parm_by_path(self, parm_path: str) -> Any:
        hou_module = self._require_hou()
        parm_path = str(parm_path).strip()
        if not parm_path:
            raise JsonRpcError(INVALID_PARAMS, "parm_path is required")
        parm = hou_module.parm(parm_path)
        if parm is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Parameter not found: {parm_path}",
                {
                    "parmPath": parm_path,
                    "expectedFormat": "/obj/geo1/tx or /obj/geo1/node1/parm",
                },
            )
        return parm

    def _current_scene_viewer(self, hou_module: Any) -> Any:
        desktop = hou_module.ui.curDesktop()
        scene_viewer = desktop.paneTabOfType(hou_module.paneTabType.SceneViewer)
        if scene_viewer is None:
            raise JsonRpcError(INVALID_PARAMS, "No Scene Viewer pane is available.")
        return scene_viewer

    def _resolve_nodes_argument(self, arguments: dict[str, Any]) -> list[str]:
        paths = arguments.get("paths")
        path = arguments.get("path")
        resolved: list[str] = []
        if isinstance(paths, list):
            resolved.extend(str(item) for item in paths)
        if path:
            resolved.append(str(path))
        if not resolved:
            raise JsonRpcError(INVALID_PARAMS, "A path or paths argument is required.")
        return resolved

    @staticmethod
    def _tool_capabilities(name: str) -> tuple[str, ...]:
        capability_map = {
            "session.info": (OBSERVE,),
            "session.list_operations": (OBSERVE,),
            "session.cancel_operation": (OBSERVE,),
            "scene.get_summary": (OBSERVE,),
            "scene.new": (EDIT_SCENE,),
            "scene.open_hip": (EDIT_SCENE,),
            "scene.merge_hip": (EDIT_SCENE,),
            "scene.save_hip": (EDIT_SCENE, WRITE_FILES),
            "scene.undo": (EDIT_SCENE,),
            "scene.redo": (EDIT_SCENE,),
            "node.list": (OBSERVE,),
            "node.get": (OBSERVE,),
            "node.create": (EDIT_SCENE,),
            "node.delete": (EDIT_SCENE,),
            "node.rename": (EDIT_SCENE,),
            "node.connect": (EDIT_SCENE,),
            "node.disconnect": (EDIT_SCENE,),
            "node.move": (EDIT_SCENE,),
            "node.layout": (EDIT_SCENE,),
            "node.set_flags": (EDIT_SCENE,),
            "parm.list": (OBSERVE,),
            "parm.get": (OBSERVE,),
            "parm.set": (EDIT_SCENE,),
            "parm.set_expression": (EDIT_SCENE,),
            "parm.press_button": (EDIT_SCENE,),
            "parm.revert_to_default": (EDIT_SCENE,),
            "selection.get": (OBSERVE,),
            "selection.set": (EDIT_SCENE,),
            "playbar.get_state": (OBSERVE,),
            "playbar.set_frame": (EDIT_SCENE,),
            "viewport.get_state": (OBSERVE,),
            "camera.get_active": (OBSERVE,),
            "viewport.capture": (OBSERVE, WRITE_FILES),
            "snapshot.capture_viewport": (OBSERVE, WRITE_FILES),
        }
        return capability_map.get(name, (OBSERVE,))

    @staticmethod
    def _conventions_payload() -> dict[str, Any]:
        return {
            "coordinateSystem": {
                "upAxis": "Y",
                "groundPlane": "XZ",
                "leftRightAxis": "X",
                "depthAxis": "Z",
            },
            "modelingNotes": [
                "Use Y for height/elevation when placing or scaling geometry.",
                "Use X for left-right placement and Z for front-back/depth placement.",
                "To rest objects on the ground plane, offset them upward on Y by half their height.",
                "This server's example geometry treats positive Z as the front-facing direction.",
            ],
            "snapshotNotes": [
                "viewport.capture and snapshot.capture_viewport capture the current Houdini viewport to an image path.",
                "camera.get_active reports whether the viewport is looking through a camera or a perspective view.",
            ],
        }

    @staticmethod
    def _dynamic_node_uri_to_path(uri: str, suffix: str = "") -> str | None:
        prefix = "houdini://nodes/"
        if not uri.startswith(prefix):
            return None
        raw = uri[len(prefix):]
        if suffix:
            if not raw.endswith(suffix):
                return None
            raw = raw[: -len(suffix)]
        raw = raw.strip("/")
        decoded = unquote(raw)
        if decoded.startswith("/"):
            return decoded
        if not decoded:
            return None
        return "/" + decoded

    def _geometry_summary_for_node(self, node: Any) -> dict[str, Any]:
        target = node
        display_node = self._safe_method_value(node, "displayNode", None)
        if display_node is not None:
            target = display_node
        geometry = self._safe_method_value(target, "geometry", None)
        if geometry is None:
            raise JsonRpcError(INVALID_PARAMS, f"Node has no accessible geometry: {node.path()}")
        bbox = geometry.boundingBox()
        return {
            "nodePath": node.path(),
            "geometryNodePath": target.path(),
            "pointCount": geometry.intrinsicValue("pointcount"),
            "primitiveCount": geometry.intrinsicValue("primitivecount"),
            "vertexCount": geometry.intrinsicValue("vertexcount"),
            "bboxMin": [bbox.minvec()[0], bbox.minvec()[1], bbox.minvec()[2]],
            "bboxMax": [bbox.maxvec()[0], bbox.maxvec()[1], bbox.maxvec()[2]],
            "primitiveGroups": [group.name() for group in geometry.primGroups()],
            "pointGroups": [group.name() for group in geometry.pointGroups()],
            "vertexAttributes": [attrib.name() for attrib in geometry.vertexAttribs()],
            "pointAttributes": [attrib.name() for attrib in geometry.pointAttribs()],
            "primitiveAttributes": [attrib.name() for attrib in geometry.primAttribs()],
        }

    def _session_info_impl(self) -> dict[str, Any]:
        hou_module = hou
        if hou_module is None:
            return {
                "serverVersion": __version__,
                "houdiniAvailable": False,
                "uiAvailable": False,
                "applicationVersion": None,
                "hipFile": None,
                "sceneRevision": self._monitor.snapshot()["revision"],
                "activeOperations": self._dispatcher.operations_snapshot(limit=20),
                "conventions": self._conventions_payload(),
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
            "activeOperations": self._dispatcher.operations_snapshot(limit=20),
            "conventions": self._conventions_payload(),
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

    def _scene_summary_impl(self) -> dict[str, Any]:
        hou_module = hou
        if hou_module is None:
            return {
                "hipFile": None,
                "selectedNodes": [],
                "currentFrame": None,
                "fps": None,
                "conventions": self._conventions_payload(),
            }

        selected = []
        try:
            selected = [node.path() for node in hou_module.selectedNodes()]
        except Exception:
            self._logger.debug("failed to read selected nodes", exc_info=True)

        return {
            "hipFile": hou_module.hipFile.path(),
            "hipDirty": hou_module.hipFile.hasUnsavedChanges(),
            "selectedNodes": selected,
            "currentFrame": hou_module.frame(),
            "fps": hou_module.fps(),
            "sceneRevision": self._monitor.snapshot()["revision"],
            "conventions": self._conventions_payload(),
        }

    def scene_get_summary(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(self._scene_summary_impl, context)
        return self._tool_response("Returned a compact summary of the current scene.", data)

    def _scene_new_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        hou_module.hipFile.clear(suppress_save_prompt=True)
        return self._scene_summary_impl()

    def scene_new(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(self._scene_new_impl, context)
        return self._tool_response("Started a new scene.", data)

    def _scene_open_hip_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise JsonRpcError(INVALID_PARAMS, "path is required")
        suppress_save_prompt = bool(arguments.get("suppress_save_prompt", True))
        ignore_load_warnings = bool(arguments.get("ignore_load_warnings", False))
        hou_module.hipFile.load(
            path,
            suppress_save_prompt=suppress_save_prompt,
            ignore_load_warnings=ignore_load_warnings,
        )
        return self._scene_summary_impl()

    def scene_open_hip(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._scene_open_hip_impl(arguments), context)
        return self._tool_response(f"Opened hip file {data['hipFile']}.", data)

    def _scene_merge_hip_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        merge_path = str(arguments.get("path", "")).strip()
        if not merge_path:
            raise JsonRpcError(INVALID_PARAMS, "path is required")
        hou_module.hipFile.merge(merge_path)
        return self._scene_summary_impl()

    def scene_merge_hip(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._scene_merge_hip_impl(arguments), context)
        return self._tool_response(f"Merged hip file {arguments['path']}.", data)

    def _node_list_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        recursive = bool(arguments.get("recursive", False))
        max_items = int(arguments.get("max_items", 200))
        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")
        nodes = list(parent.allSubChildren()) if recursive else list(parent.children())
        nodes = nodes[:max_items]
        return {
            "parentPath": parent.path(),
            "recursive": recursive,
            "count": len(nodes),
            "nodes": [self._node_summary(node) for node in nodes],
        }

    def node_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_list_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} nodes.", data)

    def _node_get_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        include_parms = bool(arguments.get("include_parms", False))
        return self._node_summary(node, include_parms=include_parms)

    def node_get(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_get_impl(arguments), context)
        return self._tool_response(f"Returned node data for {data['path']}.", data)

    def _node_create_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        node_type_name = arguments.get("node_type_name")
        if not node_type_name:
            raise JsonRpcError(INVALID_PARAMS, "node_type_name is required")
        node_name = arguments.get("node_name")
        run_init_scripts = bool(arguments.get("run_init_scripts", True))
        load_contents = bool(arguments.get("load_contents", True))

        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")

        with hou_module.undos.group(f"HocusPocus: create {node_type_name}"):
            node = parent.createNode(
                str(node_type_name),
                node_name=node_name,
                run_init_scripts=run_init_scripts,
                load_contents=load_contents,
            )
            node.setUserData("hpmcp.created_by", "hocuspocus")
            node.setUserData("hpmcp.operation_id", "tool:node.create")
            try:
                parent.layoutChildren(items=(node,))
            except Exception:
                self._logger.debug("failed to layout node", exc_info=True)

        return self._node_summary(node)

    def node_create(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_create_impl(arguments), context)
        return self._tool_response(f"Created node {data['path']}.", data)

    def _node_delete_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        paths = self._resolve_nodes_argument(arguments)
        deleted: list[str] = []
        with hou_module.undos.group("HocusPocus: delete nodes"):
            for path in paths:
                node = self._require_node_by_path(path)
                deleted.append(node.path())
                node.destroy()
        return {"deletedPaths": deleted, "count": len(deleted)}

    def node_delete(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_delete_impl(arguments), context)
        return self._tool_response(f"Deleted {data['count']} nodes.", data)

    def _node_rename_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        new_name = str(arguments.get("new_name", "")).strip()
        unique_name = bool(arguments.get("unique_name", False))
        if not path or not new_name:
            raise JsonRpcError(INVALID_PARAMS, "path and new_name are required")
        node = self._require_node_by_path(path)
        with hou_module.undos.group("HocusPocus: rename node"):
            node.setName(new_name, unique_name=unique_name)
        return self._node_summary(node)

    def node_rename(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_rename_impl(arguments), context)
        return self._tool_response(f"Renamed node to {data['path']}.", data)

    def _node_connect_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        source_path = str(arguments.get("source_node_path", "")).strip()
        dest_path = str(arguments.get("dest_node_path", "")).strip()
        if not source_path or not dest_path:
            raise JsonRpcError(INVALID_PARAMS, "source_node_path and dest_node_path are required")
        dest_input_index = int(arguments.get("dest_input_index", 0))
        source_output_index = int(arguments.get("source_output_index", 0))
        source = self._require_node_by_path(source_path, label="source_node_path")
        dest = self._require_node_by_path(dest_path, label="dest_node_path")
        with hou_module.undos.group("HocusPocus: connect nodes"):
            dest.setInput(dest_input_index, source, output_index=source_output_index)
        return self._node_summary(dest)

    def node_connect(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_connect_impl(arguments), context)
        return self._tool_response(
            f"Connected node {arguments['source_node_path']} to {arguments['dest_node_path']}.",
            data,
        )

    def _node_disconnect_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        input_index = arguments.get("input_index")
        with hou_module.undos.group("HocusPocus: disconnect node"):
            if input_index is None:
                for index, _ in enumerate(node.inputs()):
                    node.setInput(index, None)
            else:
                node.setInput(int(input_index), None)
        return self._node_summary(node)

    def node_disconnect(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_disconnect_impl(arguments), context)
        return self._tool_response(f"Disconnected inputs on {data['path']}.", data)

    def _node_move_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        x = float(arguments.get("x"))
        y = float(arguments.get("y"))
        with hou_module.undos.group("HocusPocus: move node"):
            node.setPosition(hou_module.Vector2((x, y)))
        return self._node_summary(node)

    def node_move(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_move_impl(arguments), context)
        return self._tool_response(f"Moved node {data['path']}.", data)

    def _node_layout_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")
        child_paths = [str(item) for item in arguments.get("child_paths", [])]
        if child_paths:
            items = []
            for child_path in child_paths:
                child = hou_module.node(child_path)
                if child is None:
                    raise JsonRpcError(INVALID_PARAMS, f"Node not found: {child_path}")
                items.append(child)
            parent.layoutChildren(items=tuple(items))
        else:
            parent.layoutChildren()
        return self._node_list_impl({"parent_path": parent_path, "recursive": False, "max_items": 500})

    def node_layout(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_layout_impl(arguments), context)
        return self._tool_response(f"Laid out nodes under {data['parentPath']}.", data)

    def _node_set_flags_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        with hou_module.undos.group("HocusPocus: set node flags"):
            if "bypass" in arguments:
                node.bypass(bool(arguments["bypass"]))
            if "display" in arguments:
                self._safe_value(lambda: node.setDisplayFlag(bool(arguments["display"])))
            if "render" in arguments:
                self._safe_value(lambda: node.setRenderFlag(bool(arguments["render"])))
            if "template" in arguments:
                self._safe_value(lambda: node.setTemplateFlag(bool(arguments["template"])))
        return self._node_summary(node)

    def node_set_flags(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_set_flags_impl(arguments), context)
        return self._tool_response(f"Updated flags on {data['path']}.", data)

    def _parm_list_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        node = self._require_node_by_path(node_path, label="node_path")
        parms = [self._parm_summary(parm) for parm in node.parms()]
        return {"nodePath": node.path(), "count": len(parms), "parms": parms}

    def parm_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_list_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} parameters.", data)

    def _parm_get_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        return self._parm_summary(parm)

    def parm_get(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_get_impl(arguments), context)
        return self._tool_response(f"Returned parameter {data['path']}.", data)

    def _parm_set_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = arguments.get("parm_path")
        if not parm_path:
            raise JsonRpcError(INVALID_PARAMS, "parm_path is required")
        parm = self._require_parm_by_path(str(parm_path))
        value = arguments.get("value")
        with hou_module.undos.group(f"HocusPocus: set {parm_path}"):
            parm.set(value)
        return self._parm_summary(parm)

    def parm_set(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_set_impl(arguments), context)
        return self._tool_response(f"Set parameter {data['path']}.", data)

    def _parm_set_expression_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        expression = str(arguments.get("expression", "")).strip()
        language_name = str(arguments.get("language", "hscript")).strip().lower()
        if not parm_path or not expression:
            raise JsonRpcError(INVALID_PARAMS, "parm_path and expression are required")
        parm = self._require_parm_by_path(parm_path)
        language = (
            hou_module.exprLanguage.Python
            if language_name == "python"
            else hou_module.exprLanguage.Hscript
        )
        with hou_module.undos.group(f"HocusPocus: set expression {parm_path}"):
            parm.setExpression(expression, language=language)
        return self._parm_summary(parm)

    def parm_set_expression(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_set_expression_impl(arguments), context)
        return self._tool_response(f"Set expression on {data['path']}.", data)

    def _parm_press_button_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        with hou_module.undos.group(f"HocusPocus: press {parm_path}"):
            parm.pressButton()
        return self._parm_summary(parm)

    def parm_press_button(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_press_button_impl(arguments), context)
        return self._tool_response(f"Pressed button parameter {data['path']}.", data)

    def _parm_revert_to_default_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        with hou_module.undos.group(f"HocusPocus: revert {parm_path}"):
            parm.revertToDefaults()
        return self._parm_summary(parm)

    def parm_revert_to_default(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_revert_to_default_impl(arguments), context)
        return self._tool_response(f"Reverted parameter {data['path']} to default.", data)

    def _scene_save_hip_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = arguments.get("path")
        save_to_recent = bool(arguments.get("save_to_recent_files", True))
        with hou_module.undos.disabler():
            if path:
                resolved = str(ensure_path_allowed(path, self._settings))
                hou_module.hipFile.save(
                    file_name=resolved,
                    save_to_recent_files=save_to_recent,
                )
            else:
                current_path = hou_module.hipFile.path()
                if current_path:
                    ensure_path_allowed(current_path, self._settings)
                hou_module.hipFile.save(save_to_recent_files=save_to_recent)
                resolved = hou_module.hipFile.path()
        return {
            "path": resolved,
            "hipDirty": hou_module.hipFile.hasUnsavedChanges(),
        }

    def scene_save_hip(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._scene_save_hip_impl(arguments), context)
        return self._tool_response(f"Saved hip file to {data['path']}.", data)

    def _scene_undo_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        hou_module.undos.undo()
        return self._scene_summary_impl()

    def scene_undo(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(self._scene_undo_impl, context)
        return self._tool_response("Undid the last Houdini operation.", data)

    def _scene_redo_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        hou_module.undos.redo()
        return self._scene_summary_impl()

    def scene_redo(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(self._scene_redo_impl, context)
        return self._tool_response("Redid the last Houdini operation.", data)

    def _selection_get_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        return {"selectedNodes": [node.path() for node in hou_module.selectedNodes()]}

    def selection_get(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(self._selection_get_impl, context)
        return self._tool_response("Returned current node selection.", data)

    def _selection_set_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        paths = [str(item) for item in arguments.get("paths", [])]
        clear_existing = bool(arguments.get("clear_existing", True))
        if clear_existing:
            hou_module.clearAllSelected()
        selected: list[str] = []
        for path in paths:
            node = self._require_node_by_path(path)
            node.setSelected(True, clear_all_selected=False)
            selected.append(node.path())
        return {"selectedNodes": selected}

    def selection_set(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._selection_set_impl(arguments), context)
        return self._tool_response("Updated node selection.", data)

    def _playbar_state_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        return {
            "currentFrame": hou_module.frame(),
            "fps": hou_module.fps(),
            "timelineRange": list(hou_module.playbar.timelineRange()),
            "playbackRange": list(hou_module.playbar.playbackRange()),
        }

    def playbar_get_state(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(self._playbar_state_impl, context)
        return self._tool_response("Returned playbar state.", data)

    def _playbar_set_frame_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        frame = float(arguments.get("frame"))
        hou_module.setFrame(frame)
        return self._playbar_state_impl()

    def playbar_set_frame(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._playbar_set_frame_impl(arguments), context)
        return self._tool_response(f"Set current frame to {data['currentFrame']}.", data)

    def _viewport_state_impl(self) -> dict[str, Any]:
        hou_module = self._require_ui()
        scene_viewer = self._current_scene_viewer(hou_module)
        viewport = scene_viewer.curViewport()
        camera = self._safe_value(viewport.camera, None)
        return {
            "sceneViewer": scene_viewer.name(),
            "viewport": viewport.name(),
            "cameraPath": camera.path() if camera is not None else None,
        }

    def viewport_get_state(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(self._viewport_state_impl, context)
        return self._tool_response("Returned viewport state.", data)

    def _camera_get_active_impl(self) -> dict[str, Any]:
        hou_module = self._require_ui()
        scene_viewer = self._current_scene_viewer(hou_module)
        viewport = scene_viewer.curViewport()
        camera = self._safe_value(viewport.camera, None)
        return {
            "sceneViewer": scene_viewer.name(),
            "viewport": viewport.name(),
            "cameraPath": camera.path() if camera is not None else None,
            "viewMode": "camera" if camera is not None else "perspective",
        }

    def camera_get_active(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(self._camera_get_active_impl, context)
        return self._tool_response("Returned active camera information.", data)

    def _viewport_capture_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_ui()
        output_path = str(arguments.get("path", "")).strip()
        if not output_path:
            raise JsonRpcError(INVALID_PARAMS, "path is required")
        output_path = str(ensure_path_allowed(output_path, self._settings))
        scene_viewer = self._current_scene_viewer(hou_module)
        viewport = scene_viewer.curViewport()
        viewport.saveViewToImage(output_path)
        return {"path": output_path, "viewport": viewport.name()}

    def viewport_capture(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._viewport_capture_impl(arguments), context)
        return self._tool_response(f"Captured viewport to {data['path']}.", data)

    def snapshot_capture_viewport(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self.viewport_capture(arguments, context)

    def read_session_info(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/info",
            self._call_live(self._session_info_impl, context),
        )

    def read_session_health(self, context: RequestContext) -> dict[str, Any]:
        data = {
            "dispatcherMode": self._dispatcher.mode,
            "settings": {
                "host": self._settings.host,
                "port": self._settings.port,
                "tokenMode": self._settings.token_mode,
            },
            "monitor": self._monitor.snapshot(),
            "activeOperations": self._dispatcher.operations_snapshot(limit=20),
        }
        return self._resource_response("houdini://session/health", data)

    def read_session_conventions(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/conventions",
            self._conventions_payload(),
        )

    def read_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, Any] | None:
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

    @staticmethod
    def resource_templates_payload() -> list[dict[str, Any]]:
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
                "description": "Read point/primitive counts, bbox, and group summaries for a node with geometry.",
                "mimeType": "application/json",
            },
        ]

    def _node_resource_impl(self, node_path: str) -> dict[str, Any]:
        node = self._require_node_by_path(node_path)
        return self._node_summary(node, include_parms=False)

    def _node_parms_resource_impl(self, node_path: str) -> dict[str, Any]:
        return self._parm_list_impl({"node_path": node_path})

    def _node_geometry_resource_impl(self, node_path: str) -> dict[str, Any]:
        node = self._require_node_by_path(node_path)
        return self._geometry_summary_for_node(node)

    def read_scene_summary(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/scene-summary",
            self._call_live(self._scene_summary_impl, context),
        )

    def read_selection(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/selection",
            self._call_live(self._selection_get_impl, context),
        )

    def read_playbar(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/playbar",
            self._call_live(self._playbar_state_impl, context),
        )

    def read_operations(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://session/operations",
            {"operations": self._dispatcher.operations_snapshot(limit=100)},
        )
