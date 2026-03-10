"""Scene, selection, playbar, and turntable helpers."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext
from .base import hou


class SceneOperationsMixin:
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

    def _scene_save_hip_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = arguments.get("path")
        save_to_recent = bool(arguments.get("save_to_recent_files", True))
        from hocuspocus.core.policy import ensure_path_allowed

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

    def _scene_create_turntable_camera_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        target_path = str(arguments.get("target_path", "")).strip()
        frame_range = arguments.get("frame_range", [1, 240])
        camera_name = str(arguments.get("camera_name", "turntable_cam")).strip() or "turntable_cam"
        distance_multiplier = float(arguments.get("distance_multiplier", 2.5))

        center = [0.0, 0.0, 0.0]
        radius = 4.0
        if target_path:
            target_node = self._require_node_by_path(target_path, label="target_path")
            try:
                geo_summary = self._geometry_summary_for_node(target_node)
                bbox_min = geo_summary["bboxMin"]
                bbox_max = geo_summary["bboxMax"]
                center = [
                    (bbox_min[0] + bbox_max[0]) / 2.0,
                    (bbox_min[1] + bbox_max[1]) / 2.0,
                    (bbox_min[2] + bbox_max[2]) / 2.0,
                ]
                extents = [
                    bbox_max[0] - bbox_min[0],
                    bbox_max[1] - bbox_min[1],
                    bbox_max[2] - bbox_min[2],
                ]
                radius = max(max(extents), 1.0) * distance_multiplier
            except JsonRpcError:
                pass

        frame_values = self._frame_sequence(frame_range, default_frame=float(hou_module.frame()))
        start_frame = frame_values[0]
        end_frame = frame_values[-1]

        obj = self._require_node_by_path("/obj")
        with hou_module.undos.group("HocusPocus: create turntable camera"):
            target = obj.createNode("null", node_name=f"{camera_name}_target")
            rig = obj.createNode("null", node_name=f"{camera_name}_rig")
            camera = obj.createNode("cam", node_name=camera_name)
            target.parmTuple("t").set(center)
            rig.parmTuple("t").set(center)
            camera.setInput(0, rig)
            camera.parmTuple("t").set((0.0, radius * 0.35, radius))
            lookat = camera.parm("lookatpath")
            if lookat is not None:
                lookat.set(target.path())
            if frame_values:
                angle_parm = rig.parm("ry")
                if angle_parm is not None:
                    angle_parm.deleteAllKeyframes()
                    key_start = hou_module.Keyframe()
                    key_start.setFrame(start_frame)
                    key_start.setValue(0.0)
                    angle_parm.setKeyframe(key_start)
                    key_end = hou_module.Keyframe()
                    key_end.setFrame(end_frame)
                    key_end.setValue(360.0)
                    angle_parm.setKeyframe(key_end)
            obj.layoutChildren(items=(target, rig, camera))

        return {
            "camera": self._node_summary(camera),
            "rig": self._node_summary(rig),
            "target": self._node_summary(target),
            "frameRange": [start_frame, end_frame],
        }

    def scene_create_turntable_camera(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._scene_create_turntable_camera_impl(arguments), context)
        return self._tool_response(f"Created turntable camera {data['camera']['path']}.", data)
