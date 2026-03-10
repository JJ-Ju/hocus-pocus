"""Viewport, camera, snapshot, and geometry summary operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class ViewportOperationsMixin:
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
        managed = False
        if not output_path:
            output_path = str(self._managed_snapshot_path())
            managed = True
        else:
            output_path = str(ensure_path_allowed(output_path, self._settings))
        scene_viewer = self._current_scene_viewer(hou_module)
        viewport = scene_viewer.curViewport()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        flipbook_settings = scene_viewer.flipbookSettings().stash()
        current_frame = hou_module.frame()
        flipbook_settings.frameRange((current_frame, current_frame))
        flipbook_settings.outputToMPlay(False)
        flipbook_settings.output(output_path)
        flipbook_settings.useResolution(False)
        scene_viewer.flipbook(viewport, flipbook_settings, open_dialog=False)
        return {"path": output_path, "viewport": viewport.name(), "managedPath": managed}

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
        data = self._call_live(lambda: self._viewport_capture_impl(arguments), context)
        if data["managedPath"]:
            return self._tool_response(f"Captured viewport to managed snapshot {data['path']}.", data)
        return self._tool_response(f"Captured viewport to {data['path']}.", data)

    def _geometry_get_summary_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        node = self._require_node_by_path(node_path, label="node_path")
        return self._geometry_summary_for_node(node)

    def geometry_get_summary(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._geometry_get_summary_impl(arguments), context)
        return self._tool_response(f"Returned geometry summary for {data['nodePath']}.", data)
