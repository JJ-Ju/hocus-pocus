"""The parsed request (:class:`LookSpec`) and what :func:`~.run.prepare` resolves for it
(:class:`Prepared`). Argument parsing has no ``hou``; :func:`resolve_target` runs on the
main thread.

``look``'s ``target`` decides the kind:

* omitted: the display (``/obj``, or the
  ``/stage`` display LOP when ``/obj`` displays nothing): ``obj`` or ``lop``;
* ``/obj``, an object, or a ROP in ``/out``: ``obj``. An object is framed (``fit_used:
  target``); a ROP lends its camera and its Karma samples (``final``);
* a SOP: ``sop``, framed on it and shown alone: the scene that renders gets a temporary
  object merging the SOP in world space, and the ROP draws only that object (a SOP inside
  a subnet or a locked asset, in a hidden object or outside ``/obj`` alike; no flag of the
  user's moves);
* a LOP, a LOP network (its display LOP) or a ROP in a LOP network (the LOP it renders):
  ``lop``;
* a Cop node or a COP network (its display node): ``cop``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hocuspocus.tools.errors import ToolError

QUALITIES = ("draft", "lit", "final")
LOOK_SOURCES = ("auto", "viewer")
FITS = ("all", "selected", "none")
KINDS = ("obj", "sop", "lop", "cop")
DEFAULT_RESOLUTION = (1024, 768)


def parse_resolution(value: Any) -> tuple[int, int]:
    """``[width, height]`` integers from 16 to 8192, default 1024x768."""
    if value is None:
        return DEFAULT_RESOLUTION
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 16 for v in value)
    ):
        raise ToolError("invalid_argument", "'resolution' must be [width, height] integers >= 16.")
    if max(value) > 8192:
        raise ToolError("invalid_argument", "'resolution' is capped at 8192 per side.")
    return int(value[0]), int(value[1])


def parse_frame(value: Any) -> float | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
        raise ToolError("invalid_argument", "'frame' must be a number.")
    return value


@dataclass
class Prepared:
    """A request resolved on the main thread, ready for a backend."""

    target: dict[str, Any]
    """:func:`~.framing.capture_target`'s dict (``scene``, ``camera`` or ``lop`` and
    ``camera_prim``), or ``{scene: cop, cop}``; plus ``focus``/``display``/``note``."""
    frame: float
    res: tuple[int, int]
    out_file: str
    extra_path: Any = None
    capture: dict[str, Any] = field(default_factory=dict)
    """The capture spec the viewport ROP and Karma backends build (camera, ROP parms)."""
    info: dict[str, Any] = field(default_factory=dict)
    """Result keys known before rendering (``scene``, ``camera_used``, ``fit_used``)."""
    tmp_dir: str | None = None
    snapshot: dict[str, Any] | None = None
    """Headless: the scene snapshot the child renders (:func:`~.child.snapshot_scene`)."""
    samples: int | None = None
    """Karma's samples when Karma is the chosen renderer; None for the crash fallback."""
    deadline: float = 0.0
    held: dict[str, Any] = field(default_factory=dict)
    """Notes a backend keeps across a hand-over to the next one (``held["notes"]``)."""

    def remaining(self) -> float:
        """Seconds left of the call's timeout (at least 1)."""
        return max(1.0, self.deadline - time.monotonic())


@dataclass
class LookSpec:
    """One look: ``look``'s arguments."""

    target: str | None = None
    kind: str | None = None
    """``obj``, ``sop``, ``lop`` or ``cop``, resolved from the target (main thread)."""
    camera: Any = None
    frame: Any = None
    res: tuple[int, int] = DEFAULT_RESOLUTION
    resolution_given: bool = False
    fit: str = "all"
    fit_given: bool = False
    quality: str = "draft"
    source: str = "auto"
    """``auto`` or ``viewer``."""
    path: Any = None
    """``output``: the file the picture is also saved to (:func:`parse_output`)."""
    jpeg_quality: int | None = None
    """The JPEG quality of a ``.jpg`` ``output`` (:func:`parse_jpeg_quality`)."""
    rop_samples: int | None = None
    """Samples per pixel of a ROP target (``final``)."""
    prepared: Prepared | None = None

    def parsed(self) -> dict[str, Any]:
        """The keys :func:`~.image.capture_targets` reads."""
        return {"frame": self.frame, "path": self.path}


def parse_look_args(args: dict[str, Any]) -> LookSpec:
    """Validate ``look``'s arguments without touching ``hou``. ``on`` is the bridge's
    (it routes the call) and is ignored here."""
    quality = args.get("quality", "draft") or "draft"
    if quality not in QUALITIES:
        raise ToolError("invalid_argument", f"'quality' must be one of {', '.join(QUALITIES)}.")
    source = args.get("source", "auto") or "auto"
    if source not in LOOK_SOURCES:
        raise ToolError("invalid_argument", f"'source' must be one of {', '.join(LOOK_SOURCES)}.")
    fit = args.get("fit")
    if fit is not None and fit not in FITS:
        raise ToolError("invalid_argument", f"'fit' must be one of {', '.join(FITS)}.")
    target = args.get("target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise ToolError("invalid_argument", "'target' must be a node path.")
    camera = args.get("camera")
    if camera is not None and (not isinstance(camera, str) or not camera.strip()):
        raise ToolError("invalid_argument", "'camera' must be a camera node or prim path.")
    output = parse_output(args.get("output"))
    jpeg_quality = parse_jpeg_quality(args.get("jpeg_quality"), output)
    return LookSpec(
        jpeg_quality=jpeg_quality,
        target=target.strip() if target else None,
        camera=camera,
        frame=parse_frame(args.get("frame")),
        res=parse_resolution(args.get("resolution")),
        resolution_given=args.get("resolution") is not None,
        fit=fit or "all",
        fit_given=fit is not None,
        quality=quality,
        source=source,
        path=output,
    )


OUTPUT_EXTS = (".png", ".jpg", ".jpeg")
JPEG_EXTS = (".jpg", ".jpeg")


def parse_jpeg_quality(value: Any, output: str | None) -> int | None:
    """``look``'s ``jpeg_quality`` (2.1, D86): 1-100 for a ``.jpg``/``.jpeg`` ``output``
    (default :data:`~.image.JPEG_QUALITY`); without such an output it is refused, since
    it would change nothing."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ToolError("invalid_argument", "'jpeg_quality' must be an integer from 1 to 100.")
    if output is None or not output.lower().endswith(JPEG_EXTS):
        raise ToolError(
            "invalid_argument",
            "'jpeg_quality' applies to an output ending in .jpg or .jpeg.",
            hint="Pass output: <file>.jpg with it, or leave it out.",
        )
    return value


def parse_output(value: Any) -> str | None:
    """``look``'s ``output``: a file path ending in .png, .jpg or .jpeg (2.1, review 26
    P1 #3). ``$HIP``-style variables and ``~`` are expanded, and ``approved_roots``
    checked, on the main thread (:func:`~.image.capture_targets`)."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolError("invalid_argument", "'output' must be a file path.")
    if not value.strip().lower().endswith(OUTPUT_EXTS):
        from hocuspocus.tools.migration import hint_tool

        render = hint_tool("render")
        raise ToolError(
            "invalid_argument",
            f"'output' must end in .png or .jpg (got {value.strip()!r}).",
            hint=f"{render} writes other formats (EXR, TIFF) from a ROP." if render else None,
        )
    return value.strip()


# -- target resolution (main thread) ---------------------------------------------------

STAGE_NOTE = (
    "The scene also has a stage ({lop} is displayed in /stage); pass it as target to look at it."
)
COP_NOTE = "The scene also has COP networks ({nets}); pass a Cop node as target to look at one."
NOT_LOOKABLE = (
    "Pass an object, SOP, LOP or Cop node, a LOP or COP network, or a ROP; omit target for "
    "the display."
)


ISOLATED_NOTE = "Showed {sop} alone; target its object to see it in the scene."
VIEWER_SOP_NOTE = (
    "The Scene Viewer shows the scene as the user sees it; omit source to see {sop} alone."
)


def _object_material(obj: Any) -> str | None:
    """The object-level material of ``obj`` as an absolute path, for the temporary object
    a SOP look renders through (prim-level materials travel with the geometry)."""
    try:
        value = obj.parm("shop_materialpath").eval().strip()
        material = obj.node(value) if value else None
        return material.path() if material is not None else None
    except Exception:
        return None


def _obj_target(spec: LookSpec, note: str | None = None) -> dict[str, Any]:
    """``/obj``, through ``camera`` (an OBJ camera) or framed."""
    from .framing import capture_target

    if spec.camera is None:
        target: dict[str, Any] = {"scene": "obj", "camera": None}
    else:
        target = capture_target(spec.camera, None)
        if target["scene"] != "obj":
            raise ToolError(
                "invalid_argument",
                f"{spec.target} is in /obj, and camera {spec.camera} looks at a stage.",
                hint="Pass an OBJ camera, or the LOP as target.",
            )
    if note:
        target["note"] = note
    return target


def _rop_target(spec: LookSpec, rop: Any) -> dict[str, Any]:
    """A ROP in ``/out``: ``/obj`` through its camera (unless ``camera`` is given), and its
    samples for ``final``."""
    import hou

    from .framing import _is_obj_camera

    with_parm = rop.parm("samplesperpixel")
    if with_parm is not None:
        try:
            spec.rop_samples = max(1, int(with_parm.eval()))
        except Exception:
            spec.rop_samples = None
    note = None
    if spec.camera is None and rop.parm("camera") is not None:
        cam = hou.node(rop.parm("camera").eval() or "")
        if cam is not None and _is_obj_camera(cam):
            spec.camera = cam.path()
            note = f"Looked through {cam.path()}, the camera of {rop.path()}."
    return _obj_target(spec, note)


def _lop_target(spec: LookSpec, node: Any) -> dict[str, Any]:
    from .framing import capture_target, rop_lop_source

    lop_path, note = rop_lop_source(node.path())
    if note:
        for name in ("samplesperpixel",):
            parm = node.parm(name)
            if parm is not None:
                spec.rop_samples = max(1, int(parm.eval()))
        override = node.parm("override_camera")
        if spec.camera is None and override is not None and override.eval().strip():
            spec.camera = override.eval().strip()
    elif node.parm("samplesperpixel") is not None:  # a Karma LOP
        spec.rop_samples = max(1, int(node.parm("samplesperpixel").eval()))
    target = capture_target(spec.camera, lop_path)
    if note:
        target["note"] = note
    return target


def resolve_target(spec: LookSpec) -> dict[str, Any]:
    """Resolve ``look``'s ``target`` (and ``camera``) into a capture target and set
    ``spec.kind``; through an OBJ camera, fit the resolution to it
    (:func:`camera_resolution`). Main thread."""
    target = _resolve_target(spec)
    camera_resolution(spec, target)
    return target


def _join_note(target: dict[str, Any], note: str) -> None:
    target["note"] = f"{target['note']} {note}" if target.get("note") else note


ASPECT_TOLERANCE = 0.01


def camera_resolution(spec: LookSpec, target: dict[str, Any]) -> None:
    """Through an OBJ camera (``camera``, or a ROP target's), a look without
    ``resolution`` takes the camera's aspect at :data:`DEFAULT_RESOLUTION`'s long side
    (1920x1080 looks at 1024x576); an explicit ``resolution`` of another aspect is
    honoured with a note (review 26 P1 #5). Main thread."""
    camera = target.get("camera") if target.get("scene") == "obj" else None
    if camera is None:
        return
    try:
        resx, resy = int(camera.parm("resx").eval()), int(camera.parm("resy").eval())
    except Exception:
        return
    if resx < 1 or resy < 1:
        return
    if not spec.resolution_given:
        scale = max(DEFAULT_RESOLUTION) / max(resx, resy)
        spec.res = (max(16, round(resx * scale)), max(16, round(resy * scale)))
        return
    width, height = spec.res
    if abs(resx / resy - width / height) > ASPECT_TOLERANCE * (resx / resy):
        _join_note(
            target,
            f"{camera.path()} is {resx}x{resy}; the image is {width}x{height} as asked, so it "
            "frames more or less than the camera does (omit resolution to match it).",
        )


def _resolve_target(spec: LookSpec) -> dict[str, Any]:
    import hou

    from ..tools._diag import require_node
    from .cop import _cop_networks, cop_display, is_cop_network, is_cop_node
    from .framing import (
        _is_light,
        _is_lop_camera,
        _is_obj_camera,
        _owning_obj,
        _stage_display,
        capture_target,
    )

    if spec.target is None:
        target = capture_target(spec.camera, None)
        spec.kind = "lop" if target["scene"] == "stage" else "obj"
        if target["scene"] == "obj" and spec.camera is None:
            display = _stage_display()
            notes = [STAGE_NOTE.format(lop=display.path())] if display is not None else []
            nets = _cop_networks()
            if nets:
                notes.append(COP_NOTE.format(nets=", ".join(nets)))
            if notes:
                target["note"] = " ".join(notes)
        return target
    node = require_node(spec.target, field="target")
    if is_cop_node(node) or is_cop_network(node):
        image = node if is_cop_node(node) else cop_display(node)
        if image is None:
            raise ToolError(
                "invalid_argument",
                f"{node.path()} has no display node to look at.",
                hint="Pass a Cop node inside it, or set a display flag.",
                candidates=[c.path() for c in node.children()][:10],
            )
        if spec.camera is not None:
            raise ToolError(
                "invalid_argument",
                "A Cop node is an image: camera does not apply.",
                hint="Omit camera.",
            )
        spec.kind = "cop"
        return {"scene": "cop", "cop": image.path()}
    category = node.type().category()
    if category == hou.lopNodeTypeCategory() or isinstance(node, hou.LopNetwork):
        spec.kind = "lop"
        return _lop_target(spec, node)
    try:
        lop_children = node.childTypeCategory() == hou.lopNodeTypeCategory()
    except Exception:
        lop_children = False
    if lop_children:
        spec.kind = "lop"
        return _lop_target(spec, node)
    if isinstance(node, hou.RopNode) and category == hou.ropNodeTypeCategory():
        spec.kind = "obj"
        return _rop_target(spec, node)
    if node.path() == "/obj":
        spec.kind = "obj"
        return _obj_target(spec)
    if isinstance(node, hou.ObjNode):
        if _is_obj_camera(node) or _is_lop_camera(node) or _is_light(node):
            what = "camera" if _is_obj_camera(node) else "light"
            raise ToolError(
                "invalid_argument",
                f"{node.path()} is a {what}; target is what to look at.",
                hint=f"Pass camera {node.path()}." if what == "camera" else NOT_LOOKABLE,
            )
        spec.kind = "obj"
        target = _obj_target(spec)
        display = node.displayNode() if hasattr(node, "displayNode") else None
        if isinstance(display, hou.SopNode):
            target["focus"] = [(node, display)]
        return target
    if isinstance(node, hou.SopNode):
        # Review 26 P1 #3: a SOP is shown alone, wherever it is (inside a subnet or a
        # locked asset, in a hidden object, outside /obj), through a temporary object
        # that merges it in world space (``isolate_target`` in child._BUILD_CAPTURE).
        spec.kind = "sop"
        owner = _owning_obj(node)
        target = _obj_target(spec)
        target["focus"] = [(owner, node)]
        target["isolate"] = {"sop": node.path(), "material": _object_material(owner)}
        return target
    raise ToolError(
        "invalid_argument",
        f"{node.path()} ({node.type().name()}) is not something look can show.",
        hint=NOT_LOOKABLE,
    )
