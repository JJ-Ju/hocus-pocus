"""What a look looks at and through: the target (``/obj``, a stage, a SOP), the camera
(an OBJ camera, a LOP camera, a camera prim, or one framed on the bounding box) and the
capture spec the viewport ROP backends build in the host or the child (BIBLE §4.7)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..tools._diag import require_node
from . import child
from .base import INTERNAL_KEY, TEMPORARY_CAMERA, mark_internal

VIEW_DIRECTION = (0.62, 0.45, 0.85)
"""Camera offset direction for fit framing: a three-quarter view from front-right-above."""

LIGHT_PARMS = ("light_type", "light_intensity", "light_enable")
CAMERA_CANDIDATES = 10
CAPTURE_CAMERA_PRIM = "/hocuspocus_capture_cam"
"""Prim path of the camera LOP a framed stage capture adds (only in the capture's copy)."""


def _is_light(node: Any) -> bool:
    try:
        base = node.type().nameComponents()[2].lower()
    except Exception:
        base = ""
    return "light" in base or any(node.parm(name) is not None for name in LIGHT_PARMS)


def _is_obj_camera(node: Any) -> bool:
    import hou

    return isinstance(node, hou.ObjNode) and node.parm("focal") is not None and not _is_light(node)


def _is_lop_camera(node: Any) -> bool:
    import hou

    return (
        isinstance(node, hou.LopNode)
        and node.parm("primpath") is not None
        and node.type().nameComponents()[2] == "camera"
    )


def scene_cameras(stage: Any = None) -> list[str]:
    """Candidates for ``camera``: OBJ cameras, LOP camera nodes and, given a stage, its
    camera prims (at most :data:`CAMERA_CANDIDATES`). Main thread."""
    import hou

    found: list[str] = []
    with contextlib.suppress(Exception):
        for node in hou.node("/obj").allSubChildren(recurse_in_locked_nodes=False):
            if not node.userData(INTERNAL_KEY) and _is_obj_camera(node):
                found.append(node.path())
    with contextlib.suppress(Exception):
        for node_type in hou.lopNodeTypeCategory().nodeTypes().values():
            if node_type.nameComponents()[2] == "camera":
                found.extend(n.path() for n in node_type.instances())
    if stage is not None:
        with contextlib.suppress(Exception):
            from pxr import UsdGeom

            for prim in stage.Traverse():
                if prim.IsA(UsdGeom.Camera):
                    found.append(str(prim.GetPath()))
                    if len(found) >= 2 * CAMERA_CANDIDATES:
                        break
    return found[:CAMERA_CANDIDATES]


def _no_camera(message: str, stage: Any = None) -> ToolError:
    cameras = scene_cameras(stage)
    hint = (
        f"Cameras here: {', '.join(cameras)}."
        if cameras
        else "This scene has no camera; omit camera to frame the scene automatically."
    )
    return ToolError(
        "invalid_argument",
        message,
        hint=hint + " A LOP camera node, or a camera prim with a LOP target, shows the stage.",
        candidates=cameras,
    )


def _obj_camera(path: Any) -> Any:
    """The OBJ camera at ``path``; lights and other nodes are refused with the scene's
    cameras as candidates (review 15 papercuts 1 and 10)."""
    import hou

    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", "'camera' must be a camera node path.")
    node = require_node(path, field="camera")
    if _is_obj_camera(node):
        return node
    if isinstance(node, hou.ObjNode) and _is_light(node):
        raise _no_camera(f"{node.path()} ({node.type().name()}) is a light, not a camera.")
    raise _no_camera(f"{node.path()} ({node.type().name()}) is not a camera.")


def _stage_display() -> Any:
    """The display LOP of /stage, or None."""
    import hou

    with contextlib.suppress(Exception):
        display = hou.node("/stage").displayNode()
        if isinstance(display, hou.LopNode):
            return display
    return None


def _lop_with_prim(node: Any, prim: str) -> Any:
    """The LOP to render for a camera LOP: its network's display node when that stage has
    the camera prim (the lit, shaded scene the user sees), else the camera LOP itself."""
    with contextlib.suppress(Exception):
        display = node.parent().displayNode()
        if display is not None and display != node and display.stage().GetPrimAtPath(prim):
            return display
    return node


def capture_target(camera: Any, lop_path: Any) -> dict[str, Any]:
    """What a capture looks at: ``{scene: "obj", camera}`` (an OBJ camera node or None) or
    ``{scene: "stage", lop, camera_prim}`` (a camera prim path or None). Main thread.

    A LOP camera node or a camera prim path means the stage; without camera or lop_path,
    /obj unless it displays nothing and /stage has a display LOP (review 13 papercut 3)."""
    import hou

    from ..tools.usd import cooked_stage, resolve_lop

    lop = resolve_lop(lop_path) if lop_path is not None else None
    if camera is None:
        if lop is None and not _displayed_objects():
            lop = _stage_display()
        if lop is not None:
            return {"scene": "stage", "lop": lop, "camera_prim": None}
        return {"scene": "obj", "camera": None}
    if not isinstance(camera, str) or not camera.strip():
        raise ToolError("invalid_argument", "'camera' must be a camera node or prim path.")
    node = hou.node(camera) if camera.startswith("/") else None
    if node is None:
        source = lop if lop is not None else _stage_display()
        if source is not None and camera.startswith("/"):
            from pxr import UsdGeom

            stage = cooked_stage(source)
            prim = stage.GetPrimAtPath(camera)
            if prim and prim.IsA(UsdGeom.Camera):
                return {"scene": "stage", "lop": source, "camera_prim": camera}
            if lop is not None:
                raise _no_camera(f"No camera prim {camera!r} on the stage of {lop.path()}.", stage)
        require_node(camera, field="camera")  # node_not_found with candidates
    if _is_lop_camera(node):
        prim = node.parm("primpath").eval()
        return {
            "scene": "stage",
            "lop": lop if lop is not None else _lop_with_prim(node, prim),
            "camera_prim": prim,
        }
    if lop is not None and _is_obj_camera(node):
        raise _no_camera(
            f"{node.path()} is an OBJ camera, and the target {lop.path()} is a stage.",
            cooked_stage(lop),
        )
    return {"scene": "obj", "camera": _obj_camera(camera)}


def _stage_bbox(lop: Any) -> tuple[list[float], list[float]] | None:
    """World bounds of the LOP's stage (default and render purposes), or None."""
    import hou

    from ..tools.usd import cooked_stage, stage_bbox

    stage = cooked_stage(lop)
    box = stage_bbox(stage, [stage.GetPseudoRoot()], hou.frame())
    return None if box is None else (box["min"], box["max"])


def _world_bbox(obj: Any, sop: Any) -> tuple[list[float], list[float]] | None:
    import hou

    from ..tools._diag import refresh_stale

    try:
        refresh_stale(sop)  # §5.18: stale errors upstream would fail the cook
        geo = sop.geometry()
    except hou.OperationFailed:
        return None
    if geo is None or int(geo.intrinsicValue("pointcount")) == 0:
        return None
    bbox = geo.boundingBox()
    if not bbox.isValid():
        return None
    lo, hi = bbox.minvec(), bbox.maxvec()
    xform = obj.worldTransform() if obj is not None else hou.hmath.identityTransform()
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                p = hou.Vector3(x, y, z) * xform
                for i in range(3):
                    mins[i] = min(mins[i], p[i])
                    maxs[i] = max(maxs[i], p[i])
    return mins, maxs


def _owning_obj(node: Any) -> Any:
    import hou

    parent = node.parent()
    while parent is not None and not isinstance(parent, hou.ObjNode):
        parent = parent.parent()
    return parent


def _displayed_objects() -> list[Any]:
    import hou

    objs = []
    for node in hou.node("/obj").allSubChildren(recurse_in_locked_nodes=False):
        if not isinstance(node, hou.ObjNode) or node.userData(INTERNAL_KEY):
            continue
        try:
            if not node.isObjectDisplayed():
                continue
        except Exception:
            continue
        display = node.displayNode()
        if isinstance(display, hou.SopNode):
            objs.append((node, display))
    return objs


def _fit_bbox(fit: str) -> tuple[tuple[list[float], list[float]] | None, str]:
    import hou

    pairs: list[tuple[Any, Any]] = []
    used = fit
    if fit == "selected":
        for node in hou.selectedNodes():
            if isinstance(node, hou.ObjNode) and isinstance(node.displayNode(), hou.SopNode):
                pairs.append((node, node.displayNode()))
            elif isinstance(node, hou.SopNode):
                pairs.append((_owning_obj(node), node))
        if not pairs:
            used = "all"
    if not pairs:
        pairs = _displayed_objects()
    return pairs_bbox(pairs), used


def pairs_bbox(pairs: list[tuple[Any, Any]]) -> tuple[list[float], list[float]] | None:
    """World bounds of ``(object, SOP)`` pairs, or None when none has points."""
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    found = False
    for obj, sop in pairs:
        box = _world_bbox(obj, sop)
        if box is None:
            continue
        found = True
        for i in range(3):
            mins[i] = min(mins[i], box[0][i])
            maxs[i] = max(maxs[i], box[1][i])
    return (mins, maxs) if found else None


CAMERA_LENS = (50.0, 41.4214)
"""``focal`` and ``aperture`` of a new OBJ camera in 22.0 (the cam type's template group
does not list them; they are added when the node is created)."""


def _framing(bbox: tuple[list[float], list[float]] | None, res: tuple[int, int]) -> dict[str, Any]:
    """Camera world transform, near and far that frame ``bbox`` from :data:`VIEW_DIRECTION`,
    as close as fits all 8 corners, for a default-lens camera."""
    import math

    import hou

    if bbox is None:
        bbox = ([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
    lo, hi = bbox
    center = hou.Vector3([(lo[i] + hi[i]) / 2 for i in range(3)])
    radius = max(0.5 * math.dist(lo, hi), 1e-3)
    focal, aperture = CAMERA_LENS
    tan_h = aperture / (2 * focal)
    tan_v = tan_h * res[1] / res[0]
    back = hou.Vector3(VIEW_DIRECTION).normalized()  # camera +Z (it looks down -Z)
    right = hou.Vector3(0, 1, 0).cross(back).normalized()
    up = back.cross(right)
    distance = 0.0
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                offset = hou.Vector3(x, y, z) - center
                toward = offset.dot(back)
                distance = max(
                    distance,
                    toward + abs(offset.dot(right)) / tan_h,
                    toward + abs(offset.dot(up)) / tan_v,
                )
    distance = max(distance * 1.08, radius * 0.1, 1e-3)
    eye = center + back * distance
    rotate = hou.hmath.buildRotateLookAt(eye, center, hou.Vector3(0, 1, 0))
    xform = rotate * hou.hmath.buildTranslate(eye)
    return {
        "camera_xform": list(xform.asTuple()),
        "near": max(min(0.01, distance * 0.001), (distance - radius) * 0.5, 1e-4),
        "far": max(10000.0, (distance + radius) * 2),
    }


_last_framing: dict[str, Any] = {}
"""The last automatic framing and the scene generation it was made in; ``fit: none``
reuses it (no camera is kept in the scene) until a new scene is cleared, loaded or
merged."""


def _capture_spec(
    target: dict[str, Any],
    res: tuple[int, int],
    fit: str,
    out_file: str,
    generation: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """What to build for one capture, and the ``camera_used``/``fit_used``/``scene`` to
    report. Main thread."""
    import hou

    rop_parms = {"trange": 0, "tres": 1, "res1": res[0], "res2": res[1], "picture": out_file}
    stage = target["scene"] == "stage"
    info: dict[str, Any] = {"scene": target["scene"]}
    if stage:
        info["lop_path"] = target["lop"].path()
        if target["camera_prim"] is not None:
            spec = {
                "lop": target["lop"].path(),
                "camera_prim": target["camera_prim"],
                "rop_parms": rop_parms,
            }
            return spec, {**info, "camera_used": target["camera_prim"], "fit_used": "none"}
    elif target["camera"] is not None:
        path = target["camera"].path()
        return (
            {"camera": path, "rop_parms": rop_parms},
            {**info, "camera_used": path, "fit_used": "none"},
        )
    fit_used = "none"
    key = (generation, info.get("lop_path"))
    if _last_framing.get("key") != key:
        _last_framing.clear()  # framed in another scene, or another stage
    framing = _last_framing.get("framing")
    if fit != "none" or framing is None:
        if stage:  # a stage has no node selection to fit: everything
            bbox, fit_used = _stage_bbox(target["lop"]), "all"
        elif fit == "target" and target.get("focus"):  # look: an OBJ or SOP target
            bbox, fit_used = pairs_bbox(target["focus"]), "target"
            if bbox is None:
                bbox, fit_used = _fit_bbox("all")
        else:
            bbox, fit_used = _fit_bbox(fit if fit != "none" else "all")
        framing = _framing(bbox, res)
        _last_framing.update(framing=framing, key=key)
    if stage:
        xform = hou.Matrix4(framing["camera_xform"])
        t = xform.extractTranslates("srt")
        r = xform.extractRotates("srt", "xyz")
        focal, aperture = CAMERA_LENS
        camera_parms = {
            "primpath": CAPTURE_CAMERA_PRIM,
            "tx": t[0],
            "ty": t[1],
            "tz": t[2],
            "rx": r[0],
            "ry": r[1],
            "rz": r[2],
            "focalLength": focal,
            "aperture": "set",
            "horizontalAperture": aperture,
            "verticalAperture": aperture * res[1] / res[0],
            "clippingRange1": framing["near"],
            "clippingRange2": framing["far"],
        }
        spec = {
            "lop": target["lop"].path(),
            "camera_prim": None,
            "camera_parms": camera_parms,
            "rop_parms": rop_parms,
        }
        return spec, {**info, "camera_used": TEMPORARY_CAMERA, "fit_used": fit_used}
    camera_parms = {
        "resx": res[0],
        "resy": res[1],
        "near": framing["near"],
        "far": framing["far"],
    }
    return (
        {
            "camera": None,
            "camera_xform": framing["camera_xform"],
            "camera_parms": camera_parms,
            "rop_parms": rop_parms,
        },
        {**info, "camera_used": TEMPORARY_CAMERA, "fit_used": fit_used},
    )


@contextlib.contextmanager
def temporary_capture_nodes(spec: dict[str, Any]) -> Iterator[Any]:
    """Create the capture camera (unless the spec names one) and the spec's viewport ROP
    (``rop_type``) in the live scene for an in-process render, outside undo, and delete
    them afterwards, restoring the selection; a look at a SOP also makes the temporary
    object that shows it alone (``isolate_target`` in :data:`~.child._BUILD_CAPTURE`).
    Yields the ROP. Main thread."""
    import hou

    from ..tools.events import muted

    selected = hou.selectedNodes()
    created: list[Any] = []
    namespace: dict[str, Any] = {}
    exec(child._BUILD_CAPTURE, namespace)  # the same builder the child hython runs
    try:
        with hou.undos.disabler(), muted():
            try:
                rop = namespace["build_capture"](hou, spec, created)
            finally:
                for node in created:
                    mark_internal(node)
        yield rop
    finally:
        with hou.undos.disabler(), muted():
            for node in reversed(created):
                with contextlib.suppress(Exception):
                    node.destroy()
            with contextlib.suppress(Exception):
                hou.clearAllSelected()
                for node in selected:
                    node.setSelected(True)


def rop_lop_source(lop_path: Any) -> tuple[Any, str | None]:
    """For a ROP inside a LOP network (``usdrender_rop``, ``usd_rop``), which has no output
    stage, the LOP it renders (``loppath``, else its input) and a note; any other value
    unchanged. A ROP LOP with neither is left for :func:`resolve_lop` to refuse (review 23
    P2-10). Main thread."""
    import hou

    if not isinstance(lop_path, str) or not lop_path.strip().startswith("/"):
        return lop_path, None
    node = hou.node(lop_path.strip())
    if (
        not isinstance(node, hou.RopNode)
        or isinstance(node, hou.LopNode)
        or node.type().category() != hou.lopNodeTypeCategory()
    ):
        return lop_path, None
    source = None
    with contextlib.suppress(Exception):
        source = _usd_source_lop(node)
    if source is None:
        return lop_path, None
    return source.path(), (
        f"Captured {source.path()}, the LOP {node.path()} renders: a ROP has no output stage."
    )


def _usd_source_lop(rop: Any) -> Any:
    """The LOP whose stage a USD render ROP renders: ``loppath``, else its first input."""
    import hou

    path = rop.parm("loppath").eval().strip() if rop.parm("loppath") is not None else ""
    node = rop.node(path) if path else None
    if node is None and not path:
        inputs = [n for n in rop.inputs() if n is not None]
        node = inputs[0] if inputs else None
    if node is not None and not isinstance(node, hou.LopNode):
        display = getattr(node, "displayNode", lambda: None)()
        node = display if isinstance(display, hou.LopNode) else None
    return node


_LIGHT_TYPES_EXTRA = frozenset({"ambient"})


def scene_has_lights() -> bool:
    """Whether any light object or LOP light exists (``NodeType.instances()``, no walk)."""
    import hou

    for category in (hou.objNodeTypeCategory(), hou.lopNodeTypeCategory()):
        for node_type in category.nodeTypes().values():
            try:
                base = node_type.nameComponents()[2].lower()
                if (base.endswith("light") or base in _LIGHT_TYPES_EXTRA) and node_type.instances():
                    return True
            except Exception:
                continue
    return False
