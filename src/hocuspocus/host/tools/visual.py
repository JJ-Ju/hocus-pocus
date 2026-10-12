"""Visual feedback: ``viewport_capture`` and ``render``. See docs/BIBLE.md §4.7 and §8.

Images go back as ``{"image": {"png_base64", "mime_type"}}`` (the bridge turns that into
MCP image content) and are also written under ``<state_dir>/captures``.

**Headless OpenGL renders run in a child hython.** In hython 22.0.466 the second
``RopNode.render()`` of any OpenGL ROP in a process segfaults inside the Vulkan viewport
renderer (``GR_FillAttributesVK`` / ``RV_ShaderVariableSet``), whatever the node, frame,
output or geometry; one multi-frame ``render()`` call is fine. So headless, the host
snapshots the scene (``saveChildrenToFile`` per manager: no hip save, no event side
effects) and renders it in a short-lived ``hython`` (about 3 s per call). In a GUI session
OpenGL ROPs render in-process. Every other ROP type renders in-process, frame by frame,
through the main-thread executor.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.paths import captures_dir, ensure_private_dir

from .geo import _not_found, num
from .hip import check_allowed, resolve_path
from .registry import HostContext, tool

CAPTURE_ROP = "/out/hocuspocus_capture"
CAPTURE_CAM = "/obj/hocuspocus_capture_cam"
INTERNAL_KEY = "hocuspocus:internal"
IMAGE_MAX_SIDE = 1024
THUMB_MAX_SIDE = 512
BACKGROUND = (64, 64, 64)
"""Alpha is composited onto mid grey so silhouettes read on light and dark clients."""
VIEW_DIRECTION = (0.62, 0.45, 0.85)
"""Camera offset direction for fit framing: a three-quarter view from front-right-above."""
SOURCES = ("auto", "viewer", "opengl_rop")
FITS = ("all", "selected", "none")
OUTPUT_PARMS = (
    "picture",  # opengl, karma
    "vm_picture",  # mantra (ifd)
    "sopoutput",  # geometry
    "copoutput",  # comp
    "lopoutput",  # usd
    "outputimage",  # usdrender
    "filename",  # alembic, fbx
    "file",
    "output",
)
MPLAY_OUTPUTS = {"ip", "md", "imdisplay"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga"}
CONVERT_EXTS = {".exr", ".pic", ".rat", ".hdr", ".dpx", ".cin", ".sgi", ".rgb"}
CHILD_TIMEOUT_S = 600.0
FRAME_TIMEOUT_S = 24 * 3600.0
JOB_POLL_S = 0.1


# -- small helpers ------------------------------------------------------------------


def _captures(ctx: HostContext) -> Path:
    base = Path(ctx.config.state_dir) / "captures" if ctx.config.state_dir else captures_dir()
    return ensure_private_dir(base)


def _stamp() -> str:
    now = time.time()
    return (
        time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int(now * 1e6) % 1_000_000:06d}"
    )


def _hython() -> str:
    import hou

    hfs = os.environ.get("HFS") or hou.text.expandString("$HFS")
    exe = "hython.exe" if sys.platform == "win32" else "hython"
    return os.path.join(hfs, "bin", exe)


def _fwd(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _mark_internal(node: Any) -> None:
    with contextlib.suppress(Exception):
        node.setUserData(INTERNAL_KEY, "1")


def encode_png(path: str, max_side: int, *, hfs: str | None = None) -> dict[str, Any]:
    """Load an image file, flatten alpha onto grey, downscale, return the image dict.

    Formats PIL cannot read (EXR, .pic, ...) are converted with ``$HFS/bin/iconvert``.
    """
    from PIL import Image

    source = path
    tmp_dir = None
    try:
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
            tmp_dir = tempfile.mkdtemp(prefix="hp-thumb-")
            source = os.path.join(tmp_dir, "thumb.png")
            exe = os.path.join(
                hfs or os.environ.get("HFS", ""),
                "bin",
                "iconvert.exe" if sys.platform == "win32" else "iconvert",
            )
            proc = subprocess.run(
                [exe, path, source],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode != 0 or not os.path.isfile(source):
                raise ToolError(
                    "internal",
                    f"iconvert could not convert {path} to PNG.",
                    hou_exception=f"iconvert exit {proc.returncode}",
                    detail={"stderr": (proc.stderr or proc.stdout)[-2000:]},
                )
        with Image.open(source) as im:
            im.load()
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                flat = Image.new("RGB", rgba.size, BACKGROUND)
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = im.convert("RGB")
            if max(flat.size) > max_side:
                flat.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            flat.save(buf, format="PNG", optimize=True)
            return {
                "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "mime_type": "image/png",
                "width": flat.size[0],
                "height": flat.size[1],
            }
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# -- isolated (child hython) rendering ---------------------------------------------

_CHILD_SCRIPT = r"""
import json, sys

def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        spec = json.load(fh)
    import hou
    for key, value in spec["env"].items():
        if value:
            hou.putenv(key, value)
    for lib in spec["hdas"]:
        try:
            hou.hda.installFile(lib)
        except Exception:
            pass
    for manager, path in spec["files"].items():
        node = hou.node(manager)
        if node is not None:
            node.loadChildrenFromFile(path, ignore_load_warnings=True)
    hou.setFps(spec["fps"])
    hou.playbar.setFrameRange(spec["range"][0], spec["range"][1])
    hou.setFrame(spec["frame"])
    rop = hou.node(spec["rop"])
    result = {"errors": [], "warnings": []}
    if rop is None:
        result["errors"].append("ROP %s missing in the snapshot" % spec["rop"])
    else:
        for name, value in spec.get("parms", {}).items():
            rop.parm(name).set(value)
        try:
            rop.render(frame_range=tuple(spec["frames"]), verbose=False)
        except hou.OperationFailed as exc:
            result["errors"].append(str(exc).strip())
        result["errors"] += [str(e) for e in rop.errors()]
        result["warnings"] += [str(w) for w in rop.warnings()]
    sys.stdout.write("HPRESULT " + json.dumps(result) + "\n")
    sys.stdout.flush()

main()
"""


def snapshot_scene(tmp_dir: str) -> dict[str, Any]:
    """Write the live scene's nodes to ``tmp_dir`` without touching the hip file. Main thread."""
    import hou

    files: dict[str, str] = {}
    for manager in hou.node("/").children():
        children = manager.children()
        if not children:
            continue
        target = os.path.join(tmp_dir, f"{manager.name()}.cpio")
        manager.saveChildrenToFile(children, (), target)
        files[manager.path()] = _fwd(target)
    hfs = os.path.normcase(os.path.abspath(hou.text.expandString("$HFS")))
    hdas = []
    for lib in hou.hda.loadedFiles():
        if lib == "Embedded":
            continue
        if os.path.normcase(os.path.abspath(lib)).startswith(hfs):
            continue
        hdas.append(lib)
    start, end = hou.playbar.frameRange()
    return {
        "files": files,
        "hdas": hdas,
        "env": {k: hou.getenv(k) or "" for k in ("HIP", "HIPFILE", "HIPNAME", "JOB")},
        "fps": hou.fps(),
        "range": [start, end],
        "frame": hou.frame(),
        "hfs": hou.text.expandString("$HFS"),
        "hython": _hython(),
    }


class ChildRender:
    """One child hython rendering a snapshot. Off the main thread after :meth:`start`."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        tmp_dir: str,
        rop: str,
        frames: list[float],
        parms: dict[str, Any] | None = None,
    ) -> None:
        self.tmp_dir = tmp_dir
        self.spec = dict(snapshot, rop=rop, frames=list(frames), parms=parms or {})
        self.proc: subprocess.Popen[bytes] | None = None
        self.log_path = os.path.join(tmp_dir, "child.log")

    def start(self) -> None:
        script = os.path.join(self.tmp_dir, "render_child.py")
        spec_path = os.path.join(self.tmp_dir, "spec.json")
        Path(script).write_text(_CHILD_SCRIPT, encoding="utf-8")
        Path(spec_path).write_text(json.dumps(self.spec), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with open(self.log_path, "wb") as log:
            self.proc = subprocess.Popen(
                [self.spec["hython"], script, spec_path],
                cwd=self.tmp_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.kill()
            with contextlib.suppress(Exception):
                self.proc.wait(10)

    def wait(
        self, *, timeout_s: float, cancelled: Any = None, on_poll: Any = None
    ) -> dict[str, Any]:
        assert self.proc is not None
        deadline = time.monotonic() + timeout_s
        while self.proc.poll() is None:
            if cancelled is not None and cancelled():
                self.kill()
                raise ToolError("cancelled", "The render was cancelled.")
            if time.monotonic() > deadline:
                self.kill()
                raise ToolError(
                    "internal",
                    f"The render process did not finish within {timeout_s:g}s and was killed.",
                    hou_exception="render process timeout",
                    detail={"log": self._log_tail()},
                )
            if on_poll is not None:
                on_poll()
            time.sleep(JOB_POLL_S)
        log = self._log_tail(20_000)
        marker = next(
            (line for line in reversed(log.splitlines()) if line.startswith("HPRESULT ")), None
        )
        if self.proc.returncode != 0 or marker is None:
            licence = "licen" in log.lower()
            raise ToolError(
                "internal",
                f"The render process exited with code {self.proc.returncode}.",
                hint=(
                    "No Houdini licence was available for the render process; retry shortly."
                    if licence
                    else "See detail.log for the render process output."
                ),
                hou_exception=f"render process exit {self.proc.returncode}",
                detail={"log": log[-4000:]},
            )
        return json.loads(marker[len("HPRESULT ") :])

    def _log_tail(self, limit: int = 4000) -> str:
        try:
            data = Path(self.log_path).read_bytes()
        except OSError:
            return ""
        return data[-limit:].decode("utf-8", "replace")


def render_isolated(
    rop: str,
    frames: list[float],
    parms: dict[str, Any] | None = None,
    *,
    timeout_s: float = CHILD_TIMEOUT_S,
) -> dict[str, Any]:
    """Snapshot and render synchronously in a child hython. Main thread (snapshot)."""
    tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
    try:
        child = ChildRender(snapshot_scene(tmp_dir), tmp_dir, rop, frames, parms)
        child.start()
        try:
            return child.wait(timeout_s=timeout_s)
        finally:
            child.kill()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def needs_isolation(rop_node: Any, ctx: HostContext) -> bool:
    return not ctx.ui and rop_node.type().name().split("::")[0] == "opengl"


# -- viewport_capture ---------------------------------------------------------------


def _resolution(value: Any) -> tuple[int, int]:
    if value is None:
        return 1024, 768
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 16 for v in value)
    ):
        raise ToolError("invalid_argument", "'resolution' must be [width, height] integers >= 16.")
    if max(value) > 8192:
        raise ToolError("invalid_argument", "'resolution' is capped at 8192 per side.")
    return int(value[0]), int(value[1])


def _camera_node(path: Any) -> Any:
    import hou

    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", "'camera' must be a camera node path.")
    node = hou.node(path.strip())
    if node is None:
        raise _not_found(path.strip())
    if not isinstance(node, hou.ObjNode) or node.parm("focal") is None:
        raise ToolError(
            "invalid_argument",
            f"{node.path()} ({node.type().name()}) is not a camera.",
            hint="Pass an OBJ camera such as /obj/cam1, or omit camera to frame the scene automatically.",
        )
    return node


def _world_bbox(obj: Any, sop: Any) -> tuple[list[float], list[float]] | None:
    import hou

    try:
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
        if not isinstance(node, hou.ObjNode) or node.path() == CAPTURE_CAM:
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
    return ((mins, maxs) if found else None), used


def _frame_camera(
    cam: Any, bbox: tuple[list[float], list[float]] | None, res: tuple[int, int]
) -> None:
    """Aim ``cam`` at ``bbox`` from :data:`VIEW_DIRECTION`, as close as fits all 8 corners."""
    import math

    import hou

    if bbox is None:
        bbox = ([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
    lo, hi = bbox
    center = hou.Vector3([(lo[i] + hi[i]) / 2 for i in range(3)])
    radius = max(0.5 * math.dist(lo, hi), 1e-3)
    focal = cam.evalParm("focal")
    aperture = cam.evalParm("aperture")
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
    cam.setWorldTransform(rotate * hou.hmath.buildTranslate(eye))
    cam.parm("near").set(max(min(0.01, distance * 0.001), (distance - radius) * 0.5, 1e-4))
    cam.parm("far").set(max(10000.0, (distance + radius) * 2))


def _ensure_capture_camera() -> tuple[Any, bool]:
    import hou

    cam = hou.node(CAPTURE_CAM)
    if cam is not None and cam.type().name() != "cam":
        raise ToolError(
            "name_collision",
            f"{CAPTURE_CAM} exists and is not a camera.",
            hint="Rename or delete it; viewport_capture reserves that name for its framing camera.",
        )
    created = cam is None
    if created:
        cam = hou.node("/obj").createNode("cam", CAPTURE_CAM.rsplit("/", 1)[1])
        cam.setDisplayFlag(False)
        with contextlib.suppress(Exception):
            cam.moveToGoodPosition()
        cam.setComment("HocusPocus viewport_capture camera (safe to delete)")
        _mark_internal(cam)
    return cam, created


def _ensure_capture_rop() -> Any:
    import hou

    rop = hou.node(CAPTURE_ROP)
    if rop is not None and rop.type().name() != "opengl":
        raise ToolError(
            "name_collision",
            f"{CAPTURE_ROP} exists and is not an OpenGL ROP.",
            hint="Rename or delete it; viewport_capture reserves that name.",
        )
    if rop is None:
        rop = hou.node("/out").createNode("opengl", CAPTURE_ROP.rsplit("/", 1)[1])
        with contextlib.suppress(Exception):
            rop.moveToGoodPosition()
        rop.setComment("HocusPocus viewport_capture ROP (safe to delete)")
        _mark_internal(rop)
    return rop


def _capture_opengl(
    ctx: HostContext, camera: Any, frame: float, res: tuple[int, int], fit: str, out_file: str
) -> dict[str, Any]:
    import hou

    fit_used = "none"
    if camera is not None:
        cam = _camera_node(camera)
    else:
        cam, created = _ensure_capture_camera()
        cam.parm("resx").set(res[0])
        cam.parm("resy").set(res[1])
        if fit != "none" or created:
            bbox, fit_used = _fit_bbox(fit if fit != "none" else "all")
            _frame_camera(cam, bbox, res)
    rop = _ensure_capture_rop()
    rop.parm("camera").set(cam.path())
    rop.parm("trange").set(0)
    rop.parm("tres").set(1)
    rop.parm("res1").set(res[0])
    rop.parm("res2").set(res[1])
    rop.parm("picture").set(out_file)
    if needs_isolation(rop, ctx):
        outcome = render_isolated(rop.path(), [frame, frame, 1])
        errors = outcome.get("errors") or []
    else:
        errors = []
        try:
            rop.render(frame_range=(frame, frame), verbose=False)
        except hou.OperationFailed as exc:
            errors.append(str(exc).strip())
        errors += [str(e) for e in rop.errors()]
    if errors or not os.path.isfile(out_file):
        raise ToolError(
            "cook_failed",
            f"The OpenGL ROP did not produce an image: {errors[0] if errors else 'no output file'}",
            hint="Check that the scene cooks (problems tool) and that a GPU is available.",
            detail={"errors": errors, "rop": rop.path()},
        )
    return {"camera_used": cam.path(), "fit_used": fit_used}


def _scene_viewer() -> Any:
    import hou

    try:
        return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    except Exception:
        return None


def _capture_viewer(
    viewer: Any, camera: Any, frame: float, res: tuple[int, int], out_file: str
) -> dict[str, Any]:
    viewport = viewer.curViewport()
    previous = viewport.camera()
    cam = _camera_node(camera) if camera is not None else None
    if cam is not None:
        viewport.setCamera(cam)
    try:
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((frame, frame))
        settings.outputToMPlay(False)
        settings.output(out_file)
        settings.useResolution(True)
        settings.resolution(res)
        viewer.flipbook(viewport, settings, open_dialog=False)
    finally:
        if cam is not None:
            if previous is not None:
                viewport.setCamera(previous)
            else:
                viewport.useDefaultCamera()
    if not os.path.isfile(out_file):
        raise ToolError(
            "internal",
            "The Scene Viewer flipbook did not write an image.",
            hou_exception="flipbook produced no file",
            hint="Retry with source 'opengl_rop'.",
        )
    used = viewport.camera()
    return {
        "camera_used": cam.path() if cam is not None else (used.path() if used else "viewport"),
        "fit_used": "none",
    }


@tool("viewport_capture")
def viewport_capture(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    source = args.get("source", "auto") or "auto"
    if source not in SOURCES:
        raise ToolError("invalid_argument", f"'source' must be one of {', '.join(SOURCES)}.")
    fit = args.get("fit", "all") or "all"
    if fit not in FITS:
        raise ToolError("invalid_argument", f"'fit' must be one of {', '.join(FITS)}.")
    res = _resolution(args.get("resolution"))
    frame = args.get("frame")
    if frame is not None and (isinstance(frame, bool) or not isinstance(frame, int | float)):
        raise ToolError("invalid_argument", "'frame' must be a number.")
    frame = float(hou.frame() if frame is None else frame)
    camera = args.get("camera")
    extra_path = args.get("path")
    if extra_path is not None:
        extra_path = resolve_path(extra_path)
        check_allowed(extra_path, ctx)

    viewer = None
    if source == "viewer":
        if not ctx.ui:
            raise ToolError(
                "ui_required",
                "source 'viewer' captures the GUI Scene Viewer, and this Houdini is headless.",
                hint="Use source 'opengl_rop' (or 'auto'), which renders headless.",
            )
        viewer = _scene_viewer()
        if viewer is None:
            raise ToolError(
                "invalid_value",
                "No Scene Viewer pane is open.",
                hint="Open a Scene Viewer, or use source 'opengl_rop'.",
            )
    elif source == "auto" and ctx.ui:
        viewer = _scene_viewer()

    out_file = _fwd(_captures(ctx) / f"capture_{_stamp()}.png")
    if viewer is not None:
        info = _capture_viewer(viewer, camera, frame, res, out_file)
        info["source_used"] = "viewer"
    else:
        info = _capture_opengl(ctx, camera, frame, res, fit, out_file)
        info["source_used"] = "opengl_rop"
    image = encode_png(out_file, IMAGE_MAX_SIDE)
    result: dict[str, Any] = {
        "image": image,
        "path": out_file,
        "width": image["width"],
        "height": image["height"],
        "rendered": list(res),
        "frame": num(frame),
        **info,
    }
    if extra_path is not None:
        Path(extra_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_file, extra_path)
        result["also_written"] = extra_path
    return result


# -- render ---------------------------------------------------------------------------


def _frames(value: Any) -> list[float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list | tuple)
        or len(value) not in (2, 3)
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        raise ToolError("invalid_argument", "'frames' must be [start, end] or [start, end, inc].")
    start, end = float(value[0]), float(value[1])
    inc = float(value[2]) if len(value) == 3 else 1.0
    if inc <= 0:
        raise ToolError("invalid_argument", "The frame increment must be > 0.")
    if end < start:
        raise ToolError("invalid_argument", "'frames' end must be >= start.")
    if (end - start) / inc > 100_000:
        raise ToolError("invalid_argument", "'frames' covers more than 100000 frames.")
    return [start, end, inc]


def _frame_list(frames: list[float]) -> list[float]:
    start, end, inc = frames
    out = []
    i = 0
    while True:
        f = start + i * inc
        if f > end + 1e-6:
            break
        out.append(f)
        i += 1
    return out


def _output_parm(rop: Any) -> Any:
    for name in OUTPUT_PARMS:
        parm = rop.parm(name)
        if parm is not None:
            return parm
    return None


def _prepare_render(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Validate on the main thread and compute the expected output files."""
    import hou

    rop_path = args.get("rop_path")
    if not isinstance(rop_path, str) or not rop_path.strip():
        raise ToolError("invalid_argument", "'rop_path' must be a ROP node path.")
    rop = hou.node(rop_path.strip())
    if rop is None:
        raise _not_found(rop_path.strip())
    if not callable(getattr(rop, "render", None)):
        raise ToolError(
            "invalid_argument",
            f"{rop.path()} ({rop.type().name()}) is not a render node.",
            hint="Pass a ROP such as /out/karma1 or /out/opengl1.",
        )
    frames = _frames(args.get("frames"))
    if frames is None:
        frames = [hou.frame(), hou.frame(), 1.0]
    output = args.get("output")
    parm = _output_parm(rop)
    if output is not None:
        if not isinstance(output, str) or not output.strip():
            raise ToolError("invalid_argument", "'output' must be a non-empty path.")
        if parm is None:
            raise ToolError(
                "invalid_argument",
                f"{rop.path()} ({rop.type().name()}) has no output parm to override.",
                hint="Set the ROP's output parm with parm_set, then render without output.",
            )
        output = output.strip()
        check_allowed(resolve_path(output), ctx)
    expected: list[str] = []
    for f in _frame_list(frames):
        if output is not None:
            expected.append(hou.text.expandStringAtFrame(output, f))
        elif parm is not None:
            expected.append(parm.evalAtFrame(f))
    if parm is not None and any(p.strip() in MPLAY_OUTPUTS for p in expected):
        raise ToolError(
            "invalid_value",
            f"{rop.path()} renders to MPlay ({parm.name()} = {expected[0]!r}), which needs a GUI.",
            hint="Pass output with a file path such as $HIP/render/$OS.$F4.png.",
        )
    return {
        "rop": rop.path(),
        "type": rop.type().name(),
        "frames": frames,
        "frame_list": _frame_list(frames),
        "parm": parm.name() if parm is not None else None,
        "output": output,
        "expected": [_fwd(p) for p in expected],
        "isolate": needs_isolation(rop, ctx),
        "hfs": hou.text.expandString("$HFS"),
    }


def _render_result(plan: dict[str, Any], thumbnail: bool) -> dict[str, Any]:
    outputs = [p for p in plan["expected"] if os.path.isfile(p)]
    missing = [p for p in plan["expected"] if not os.path.isfile(p)]
    result: dict[str, Any] = {
        "rop_path": plan["rop"],
        "frames": [num(v) for v in plan["frames"]],
        "outputs": outputs,
    }
    if missing:
        result["missing"] = missing[:20]
    if thumbnail and outputs:
        last = outputs[-1]
        ext = os.path.splitext(last)[1].lower()
        if ext in IMAGE_EXTS or ext in CONVERT_EXTS:
            try:
                image = encode_png(last, THUMB_MAX_SIDE, hfs=plan["hfs"])
                result["thumbnail"] = {
                    "path": last,
                    "width": image["width"],
                    "height": image["height"],
                    "image": image,
                }
            except Exception as exc:  # a thumbnail is a nicety; never fail the render
                result["thumbnail_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _render_job(plan: dict[str, Any], ctx: HostContext, thumbnail: bool) -> Any:
    import hou

    frame_list = plan["frame_list"]

    def run_isolated(job: Any) -> dict[str, Any]:
        tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
        try:
            snapshot = job.run_main(lambda: snapshot_scene(tmp_dir))
            parms = {plan["parm"]: plan["output"]} if plan["output"] is not None else {}
            child = ChildRender(snapshot, tmp_dir, plan["rop"], plan["frames"], parms)
            child.start()

            def poll() -> None:
                done = sum(1 for p in plan["expected"] if os.path.isfile(p))
                if plan["expected"]:
                    job.progress(
                        done / len(plan["expected"]), f"{done}/{len(plan['expected'])} frames"
                    )

            job.progress(0.0, f"rendering {len(frame_list)} frame(s) in a child hython")
            try:
                outcome = child.wait(
                    timeout_s=FRAME_TIMEOUT_S, cancelled=lambda: job.cancelled, on_poll=poll
                )
            finally:
                child.kill()
            if outcome.get("errors"):
                raise ToolError(
                    "cook_failed",
                    f"{plan['rop']} failed to render: {outcome['errors'][0]}",
                    detail={"errors": outcome["errors"], "warnings": outcome.get("warnings", [])},
                )
            job.progress(1.0, "done")
            return _render_result(plan, thumbnail)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_in_process(job: Any) -> dict[str, Any]:
        saved: dict[str, Any] = {}

        def apply_override() -> None:
            parm = hou.node(plan["rop"]).parm(plan["parm"])
            saved["raw"] = parm.unexpandedString()
            saved["keys"] = parm.keyframes()
            with hou.undos.disabler():
                if saved["keys"]:
                    parm.deleteAllKeyframes()
                parm.set(plan["output"])

        def restore() -> None:
            node = hou.node(plan["rop"])
            if node is None:
                return
            parm = node.parm(plan["parm"])
            with hou.undos.disabler():
                parm.set(saved["raw"])
                if saved["keys"]:
                    parm.setKeyframes(saved["keys"])

        def render_frame(frame: float) -> list[str]:
            node = hou.node(plan["rop"])
            if node is None:
                return [f"{plan['rop']} was deleted during the render."]
            errors: list[str] = []
            try:
                node.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in node.errors()]
            return errors

        if plan["output"] is not None:
            job.run_main(apply_override)
        try:
            total = len(frame_list)
            for i, frame in enumerate(frame_list):
                job.progress(i / total, f"frame {num(frame)} ({i + 1}/{total})")
                errors = job.run_main(lambda f=frame: render_frame(f), timeout_s=FRAME_TIMEOUT_S)
                if errors:
                    raise ToolError(
                        "cook_failed",
                        f"{plan['rop']} failed to render frame {num(frame)}: {errors[0]}",
                        detail={"errors": errors, "frame": frame},
                    )
            job.progress(1.0, "done")
        finally:
            if "raw" in saved:
                ctx.executor.run(restore, 60.0)
        return _render_result(plan, thumbnail)

    return run_isolated if plan["isolate"] else run_in_process


@tool("render", main_thread=False, scene=False)
def render(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Runs on the request thread so it can wait for its job; ``hou`` only via the executor."""
    if ctx.config.read_only:
        raise ToolError(
            "read_only",
            "render writes files and changes ROP state, and the host is in read-only mode.",
            hint="Set read_only = false in hocuspocus.toml (or HOCUSPOCUS_READ_ONLY=0) and restart the host.",
        )
    wait_s = args.get("wait_s", 20)
    if wait_s is None:
        wait_s = 20
    if isinstance(wait_s, bool) or not isinstance(wait_s, int | float) or wait_s < 0:
        raise ToolError("invalid_argument", "'wait_s' must be a number >= 0.")
    thumbnail = args.get("thumbnail", True)
    if not isinstance(thumbnail, bool):
        raise ToolError("invalid_argument", "'thumbnail' must be a boolean.")
    plan = ctx.executor.run(lambda: _prepare_render(args, ctx), ctx.config.default_timeout_s)
    job = ctx.jobs.start("render", _render_job(plan, ctx, thumbnail), label=plan["rop"])
    job.done_event.wait(float(wait_s))
    if job.state == "done":
        result = dict(job.result)
        result["job_id"] = job.id
        return result
    if job.state in ("failed", "cancelled") and job.error:
        raise ToolError.from_dict(job.error)
    status = job.status()
    status["hint"] = "Poll with job {action: 'status' | 'result', job_id}."
    return status
