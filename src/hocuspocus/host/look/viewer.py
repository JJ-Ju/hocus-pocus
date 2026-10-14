"""The viewer backend: one frame of the GUI Scene Viewer's flipbook, what the user sees
(HUD, guides, the viewer's network context). GUI only, never a stage. A ``camera`` or an
explicit ``fit`` changes the view only for the grab; the view and the camera the viewport
looked through are put back afterwards (review 15 papercuts 1 and 5)."""

from __future__ import annotations

import os
from typing import Any

from hocuspocus.tools.errors import ToolError

from .base import Backend, Env, LookResult


def _scene_viewer() -> Any:
    import hou

    try:
        return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    except Exception:
        return None


def _viewer_context_note(viewer: Any, target: dict[str, Any]) -> tuple[str | None, str | None]:
    """The viewer's network context, and a note when it is not the captured scene's
    (inside an object other objects draw ghosted or hidden; review 15 papercut 7)."""
    try:
        pwd = viewer.pwd()
        context = pwd.path() if pwd is not None else None
    except Exception:
        return None, None
    if context is None:
        return None, None
    wanted = "/obj" if target["scene"] == "obj" else target["lop"].parent().path()
    if context == wanted:
        return context, None
    return context, (
        f"The viewer shows {context}, not {wanted}: it draws that network's context (other "
        "objects ghosted or hidden). source flipbook_rop renders the whole scene."
    )


def _capture_viewer(
    viewer: Any,
    target: dict[str, Any],
    frame: float,
    res: tuple[int, int],
    out_file: str,
    fit: str | None = None,
) -> dict[str, Any]:
    """Flipbook one frame of the Scene Viewer. A ``camera`` or an explicit ``fit`` changes
    the view only for the grab: the view (and the camera the viewport looked through) is
    saved first and put back afterwards (review 15 papercuts 1 and 5)."""
    import hou

    viewport = viewer.curViewport()
    previous = viewport.camera()
    saved_view = viewport.defaultCamera().stash()
    cam = target.get("camera")
    fit_used = "none"
    changed = cam is not None or fit in ("all", "selected")
    try:
        if cam is not None:
            viewport.setCamera(cam)
        elif fit in ("all", "selected"):
            if previous is not None:
                viewport.useDefaultCamera()  # frame the free view, never move a camera node
            if fit == "selected" and hou.selectedNodes():
                viewport.frameSelected()
                fit_used = "selected"
            else:
                viewport.frameAll()
                fit_used = "all"
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((frame, frame))
        settings.outputToMPlay(False)
        settings.output(out_file)
        settings.useResolution(True)
        settings.resolution(res)
        viewer.flipbook(viewport, settings, open_dialog=False)
    finally:
        if changed:
            viewport.useDefaultCamera()
            viewport.setDefaultCamera(saved_view)
            if previous is not None:
                viewport.setCamera(previous)
    if not os.path.isfile(out_file):
        raise ToolError(
            "internal",
            "The Scene Viewer flipbook did not write an image.",
            hou_exception="flipbook produced no file",
            hint="Retry with source 'flipbook_rop'.",
        )
    info: dict[str, Any] = {
        "scene": target["scene"],
        "camera_used": (
            cam.path()
            if cam is not None
            else (previous.path() if previous is not None and fit_used == "none" else "viewport")
        ),
        "fit_used": fit_used,
    }
    context, note = _viewer_context_note(viewer, target)
    if context is not None:
        info["context"] = context
    if note:
        info["notes"] = [note]
    return info


class ViewerBackend(Backend):
    """The Scene Viewer grab. Runs on the main thread (the GUI path is one main-thread
    call)."""

    name = "viewer"

    def can_run(self, spec: Any, env: Env) -> tuple[bool, str]:
        if not env.ui:
            return False, "this Houdini is headless"
        if spec.kind in ("lop", "cop"):
            return False, "a stage or a COP renders through a ROP"
        if not env.viewer:
            return False, "no Scene Viewer pane is open"
        return True, ""

    def render(self, spec: Any, ctx: Any) -> LookResult:
        job = spec.prepared
        viewer = _scene_viewer()
        if viewer is None:
            raise ToolError(
                "invalid_value",
                "No Scene Viewer pane is open.",
                hint="Open a Scene Viewer, or use source 'flipbook_rop'.",
            )
        fit = spec.fit if spec.fit_given else None
        info = _capture_viewer(viewer, job.target, job.frame, job.res, job.out_file, fit)
        return LookResult(info=info, notes=info.pop("notes", []))


VIEWER = ViewerBackend()
