"""Shared helpers for live operation mixins."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import EDIT_SCENE, OBSERVE, WRITE_FILES, ensure_path_allowed

from ..context import RequestContext

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore


class OperationBaseMixin:
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
        output_nodes = self._safe_method_value(node, "outputNodes", []) or []
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
            "outputNodePaths": [item.path() for item in output_nodes if item is not None],
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
            "task.list": (OBSERVE,),
            "task.cancel": (OBSERVE,),
            "scene.get_summary": (OBSERVE,),
            "scene.new": (EDIT_SCENE,),
            "scene.open_hip": (EDIT_SCENE,),
            "scene.merge_hip": (EDIT_SCENE,),
            "scene.save_hip": (EDIT_SCENE, WRITE_FILES),
            "scene.undo": (EDIT_SCENE,),
            "scene.redo": (EDIT_SCENE,),
            "scene.create_turntable_camera": (EDIT_SCENE,),
            "hda.list_libraries": (OBSERVE,),
            "hda.list_definitions": (OBSERVE,),
            "hda.get_definition": (OBSERVE,),
            "hda.get_instance": (OBSERVE,),
            "hda.get_interface": (OBSERVE,),
            "hda.install_library": (EDIT_SCENE, WRITE_FILES),
            "hda.uninstall_library": (EDIT_SCENE,),
            "hda.reload_library": (EDIT_SCENE,),
            "hda.create_from_subnet": (EDIT_SCENE, WRITE_FILES),
            "hda.promote_parm": (EDIT_SCENE,),
            "hda.set_definition_version": (EDIT_SCENE,),
            "dependency.scan_scene": (OBSERVE,),
            "dependency.repath": (EDIT_SCENE,),
            "cache.get_topology": (OBSERVE,),
            "package.preview_scene": (OBSERVE,),
            "package.create_scene_package": (WRITE_FILES,),
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
            "graph.query": (OBSERVE,),
            "graph.find_upstream": (OBSERVE,),
            "graph.find_downstream": (OBSERVE,),
            "graph.find_by_type": (OBSERVE,),
            "graph.find_by_flag": (OBSERVE,),
            "graph.batch_edit": (EDIT_SCENE,),
            "scene.diff": (OBSERVE,),
            "graph.diff_subgraph": (OBSERVE,),
            "graph.plan_edit": (OBSERVE,),
            "graph.apply_patch": (EDIT_SCENE,),
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
            "pdg.list_graphs": (OBSERVE,),
            "pdg.cook": (EDIT_SCENE,),
            "pdg.get_workitems": (OBSERVE,),
            "pdg.cancel": (EDIT_SCENE,),
            "pdg.get_results": (OBSERVE,),
            "cook.node": (EDIT_SCENE,),
            "render.rop": (EDIT_SCENE, WRITE_FILES),
            "export.alembic": (EDIT_SCENE, WRITE_FILES),
            "export.usd": (EDIT_SCENE, WRITE_FILES),
            "lop.create_node": (EDIT_SCENE,),
            "usd.assign_material": (EDIT_SCENE,),
            "usd.set_variant": (EDIT_SCENE,),
            "usd.add_reference": (EDIT_SCENE,),
            "usd.create_layer_break": (EDIT_SCENE,),
            "geometry.get_summary": (OBSERVE,),
            "material.create": (EDIT_SCENE,),
            "material.update": (EDIT_SCENE,),
            "material.assign": (EDIT_SCENE,),
            "model.create_house_blockout": (EDIT_SCENE,),
            "render.inspect_graph": (OBSERVE,),
            "render.inspect_outputs": (OBSERVE,),
            "render.preflight": (OBSERVE,),
            "lookdev.create_three_point_light_rig": (EDIT_SCENE,),
            "scene.validate": (OBSERVE,),
            "graph.check_errors": (OBSERVE,),
            "parm.find_broken_refs": (OBSERVE,),
            "scene.events_recent": (OBSERVE,),
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
                "snapshot.capture_viewport can write to a managed server snapshot path when no path is provided.",
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

    @staticmethod
    def _dynamic_task_id(uri: str, suffix: str = "") -> str | None:
        prefix = "houdini://tasks/"
        if not uri.startswith(prefix):
            return None
        raw = uri[len(prefix):].strip("/")
        normalized_suffix = suffix.strip("/")
        if normalized_suffix:
            if not raw.endswith(normalized_suffix):
                return None
            raw = raw[: -len(normalized_suffix)].strip("/")
        return raw or None

    @staticmethod
    def _frame_sequence(
        frame_range: Any,
        *,
        default_frame: float,
    ) -> list[float]:
        if not frame_range:
            return [float(default_frame)]
        if not isinstance(frame_range, (list, tuple)) or len(frame_range) not in {2, 3}:
            raise JsonRpcError(
                INVALID_PARAMS,
                "frame_range must be [start, end] or [start, end, step].",
            )
        start = float(frame_range[0])
        end = float(frame_range[1])
        step = float(frame_range[2]) if len(frame_range) == 3 else 1.0
        if step <= 0:
            raise JsonRpcError(INVALID_PARAMS, "frame_range step must be greater than 0.")
        frames: list[float] = []
        current = start
        epsilon = step * 0.001
        while current <= end + epsilon:
            frames.append(round(current, 6))
            current += step
        return frames

    def _node_file_parm_paths(self, node: Any) -> list[str]:
        candidates = [
            "sopoutput",
            "picture",
            "vm_picture",
            "copoutput",
            "lopoutput",
            "output",
            "filename",
        ]
        values: list[str] = []
        for parm_name in candidates:
            parm = self._safe_value(lambda parm_name=parm_name: node.parm(parm_name), None)
            if parm is None:
                continue
            raw = self._safe_value(parm.unexpandedString, None) or self._safe_value(parm.evalAsString, None)
            if not raw:
                continue
            value = str(raw).strip()
            if value and value not in values:
                values.append(value)
        return values

    def _validate_render_output_paths(self, node: Any) -> list[str]:
        hou_module = self._require_hou()
        validated: list[str] = []
        for value in self._node_file_parm_paths(node):
            expanded = self._safe_value(lambda value=value: hou_module.expandString(value), value)
            validated.append(str(ensure_path_allowed(expanded, self._settings)))
        return validated

    def _existing_render_outputs_for_frame(self, node: Any, frame: float) -> list[str]:
        hou_module = self._require_hou()
        existing: list[str] = []
        for value in self._node_file_parm_paths(node):
            expanded = self._safe_value(
                lambda value=value, frame=frame: hou_module.expandStringAtFrame(value, frame),
                value,
            )
            if not expanded:
                continue
            validated = ensure_path_allowed(str(expanded), self._settings)
            if validated.exists():
                existing.append(str(validated))
        return existing

    def _material_paths_from_geometry(self, geometry: Any) -> list[str]:
        material_paths: list[str] = []
        attrib = self._safe_value(lambda: geometry.findPrimAttrib("shop_materialpath"), None)
        if attrib is None:
            return material_paths
        for prim in geometry.prims():
            value = self._safe_value(lambda prim=prim: prim.attribValue(attrib), None)
            if isinstance(value, str) and value and value not in material_paths:
                material_paths.append(value)
        return material_paths

    def _material_owner_for_node(self, node: Any) -> Any | None:
        current = node
        while current is not None:
            parm = self._safe_value(lambda current=current: current.parm("shop_materialpath"), None)
            if parm is not None:
                return current
            current = self._safe_value(current.parent, None)
        return None

    def _material_path_for_node(self, node: Any) -> str | None:
        owner = self._material_owner_for_node(node)
        if owner is None:
            return None
        parm = owner.parm("shop_materialpath")
        if parm is None:
            return None
        value = self._safe_value(parm.evalAsString, None)
        if not value:
            return None
        return str(value)

    def _material_summary(self, node: Any) -> dict[str, Any]:
        payload = self._node_summary(node, include_parms=False)
        payload["materialPath"] = node.path()
        payload["baseColor"] = self._safe_value(lambda: list(node.parmTuple("basecolor").eval()), None)
        payload["roughness"] = self._safe_value(lambda: node.parm("rough").eval(), None)
        payload["metallic"] = self._safe_value(lambda: node.parm("metallic").eval(), None)
        payload["emissionColor"] = self._safe_value(lambda: list(node.parmTuple("emitcolor").eval()), None)
        payload["emissionIntensity"] = self._safe_value(lambda: node.parm("emitint").eval(), None)
        payload["opacity"] = self._safe_value(lambda: node.parm("opac").eval(), None)
        return payload

    def _material_apply_properties(self, node: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        applied: list[str] = []
        skipped: list[str] = []

        def set_tuple(parm_name: str, values: Any, expected: int) -> None:
            parm_tuple = self._safe_value(lambda: node.parmTuple(parm_name), None)
            if parm_tuple is None:
                skipped.append(parm_name)
                return
            if not isinstance(values, (list, tuple)) or len(values) != expected:
                raise JsonRpcError(INVALID_PARAMS, f"{parm_name} must be a {expected}-item array.")
            parm_tuple.set(tuple(float(item) for item in values))
            applied.append(parm_name)

        def set_scalar(parm_name: str, value: Any) -> None:
            parm = self._safe_value(lambda: node.parm(parm_name), None)
            if parm is None:
                skipped.append(parm_name)
                return
            parm.set(value)
            applied.append(parm_name)

        if "base_color" in arguments:
            set_tuple("basecolor", arguments["base_color"], 3)
        if "roughness" in arguments:
            set_scalar("rough", float(arguments["roughness"]))
        if "metallic" in arguments:
            set_scalar("metallic", float(arguments["metallic"]))
        if "emission_color" in arguments:
            set_tuple("emitcolor", arguments["emission_color"], 3)
        if "emission_intensity" in arguments:
            set_scalar("emitint", float(arguments["emission_intensity"]))
        if "opacity" in arguments:
            set_scalar("opac", float(arguments["opacity"]))

        return {"appliedProperties": applied, "skippedProperties": skipped}

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
            "materialPaths": sorted({
                *self._material_paths_from_geometry(geometry),
                *([self._material_path_for_node(node)] if self._material_path_for_node(node) else []),
            }),
            "objectMaterialPath": self._material_path_for_node(node),
        }

    def _managed_snapshot_path(self, stem: str = "viewport") -> Path:
        timestamp_ms = int(time.time() * 1000)
        suffix = uuid4().hex[:8]
        return core_paths.snapshot_dir() / f"{stem}_{timestamp_ms}_{suffix}.png"

    def _managed_export_path(self, stem: str, suffix: str) -> Path:
        timestamp_ms = int(time.time() * 1000)
        unique = uuid4().hex[:8]
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return core_paths.export_dir() / f"{stem}_{timestamp_ms}_{unique}{normalized_suffix}"
