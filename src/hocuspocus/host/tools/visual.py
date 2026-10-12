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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.paths import captures_dir, ensure_private_dir

from ..dispatch import call_timeout
from .geo import _not_found, num
from .hip import check_allowed, resolve_path
from .registry import HostContext, tool
from .session import scene_dirty

TEMPORARY_CAMERA = "temporary"
"""``camera_used`` when the camera was built for one capture and deleted afterwards."""
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
CAPTURES_KEEP = 50
"""``<state_dir>/captures`` keeps the newest this many files."""
NOT_CARRIED_VARS = frozenset(
    {"HIP", "HIPFILE", "HIPNAME", "JOB", "ACTIVETAKE", "E", "PI", "EYE", "POSE", "status"}
)
"""Global hscript variables the child does not get from ``set -s``: the hip/job ones go
through the environment, the rest are Houdini's own."""
FRAME_TIMEOUT_S = 24 * 3600.0
JOB_POLL_S = 0.1
INLINE_OUTPUTS = 5
"""A render result lists at most this many outputs; above it, ``outputs_summary`` only."""
DARK_MEAN = 8.0
"""A thumbnail whose mean luminance (0..255) is below this is reported as nearly black."""
NO_LIGHTS_NOTE = (
    "Scene has no lights; an OpenGL render relies on the ROP's headlight setting and other "
    "renderers may render black."
)


# -- small helpers ------------------------------------------------------------------


def _captures(ctx: HostContext) -> Path:
    base = Path(ctx.config.state_dir) / "captures" if ctx.config.state_dir else captures_dir()
    return ensure_private_dir(base)


def prune_captures(directory: Path, keep: int = CAPTURES_KEEP) -> int:
    """Delete all but the newest ``keep`` files in ``directory``. Returns how many went."""
    try:
        files = [p for p in directory.iterdir() if p.is_file()]
    except OSError:
        return 0
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in files[keep:]:
        with contextlib.suppress(OSError):
            path.unlink()
            removed += 1
    return removed


def run_with_fallback(executor: Any, fn: Any, timeout_s: float) -> str | None:
    """Run ``fn`` on the main thread; if that fails (busy, timeout), queue it with
    ``post`` instead. Never raises, so a caller's own error is not replaced. Returns a
    note when ``fn`` did not run synchronously."""
    try:
        executor.run(fn, timeout_s)
        return None
    except Exception as exc:
        first = f"{type(exc).__name__}: {exc}"
    try:
        executor.post(fn)
    except Exception as exc:
        return f"{first}; queueing a retry also failed ({type(exc).__name__}: {exc})"
    return f"{first}; a retry was queued for the main thread"


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


def encode_png(
    path: str, max_side: int, *, hfs: str | None = None, measure: bool = False
) -> dict[str, Any]:
    """Load an image file, flatten alpha onto grey, downscale, return the image dict.

    Formats PIL cannot read (EXR, .pic, ...) are converted with ``$HFS/bin/iconvert``.
    ``measure`` adds ``mean_luma``: the mean luminance (0..255) of the colour channels
    before alpha is flattened, so an empty render over transparency reads as black.
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
            mean_luma = None
            if measure:
                from PIL import ImageStat

                mean_luma = float(ImageStat.Stat(im.convert("RGB").convert("L")).mean[0])
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
            out = {
                "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "mime_type": "image/png",
                "width": flat.size[0],
                "height": flat.size[1],
            }
            if mean_luma is not None:
                out["mean_luma"] = mean_luma
            return out
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# -- isolated (child hython) rendering ---------------------------------------------

_CHILD_SCRIPT = r"""
import json, sys

def build_capture(hou, capture):
    # viewport_capture's camera and ROP, created in the child scene only.
    camera = capture.get("camera")
    if camera is None:
        cam = hou.node("/obj").createNode("cam")
        cam.setDisplayFlag(False)
        for name, value in capture["camera_parms"].items():
            cam.parm(name).set(value)
        cam.setWorldTransform(hou.Matrix4(capture["camera_xform"]))
        camera = cam.path()
    rop = hou.node("/out").createNode("opengl")
    for name, value in capture["rop_parms"].items():
        rop.parm(name).set(value)
    rop.parm("camera").set(camera)
    return rop.path()

def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        spec = json.load(fh)
    import hou
    notes = []
    for key, value in spec["env"].items():
        if value:
            hou.putenv(key, value)
    # fps first, keeping keys and range where they are: loading at the default 24 fps and
    # calling setFps afterwards would retime the loaded keys.
    hou.setFps(spec["fps"], False, False, True)
    for line in spec.get("hscript_vars", []):
        out, err = hou.hscript(line)
        if err.strip():
            notes.append("hscript variable not carried: %s (%s)" % (line, err.strip()))
    if spec.get("session_source"):
        try:
            hou.setSessionModuleSource(spec["session_source"])
        except Exception as exc:
            notes.append("hou.session not carried: %s: %s" % (type(exc).__name__, exc))
    for lib in spec["hdas"]:
        try:
            hou.hda.installFile(lib)
        except Exception:
            pass
    for manager, path in spec["files"].items():
        node = hou.node(manager)
        if node is not None:
            node.loadChildrenFromFile(path, ignore_load_warnings=True)
    hou.playbar.setFrameRange(spec["range"][0], spec["range"][1])
    hou.setFrame(spec["frame"])
    capture = spec.get("capture")
    if capture:
        spec["rop"] = build_capture(hou, capture)
    rop = hou.node(spec["rop"])
    result = {"errors": [], "warnings": [], "notes": notes}
    if rop is None:
        result["errors"].append("ROP %s missing in the snapshot" % spec["rop"])
    else:
        for name, value in spec.get("parms", {}).items():
            parm = rop.parm(name)
            parm.deleteAllKeyframes()  # set() on a keyed or expression parm would not stick
            parm.set(value)
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
    hscript_vars = []
    for line in hou.hscript("set -s")[0].splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[:2] == ["set", "-g"] and parts[2] not in NOT_CARRIED_VARS:
            hscript_vars.append(line)
    notes = []
    with contextlib.suppress(Exception):
        if hou.takes.currentTake() != hou.takes.rootTake():
            notes.append(
                f"The headless render uses the root take; take "
                f"{hou.takes.currentTake().name()!r} is not carried."
            )
    return {
        "files": files,
        "hdas": hdas,
        "env": {k: hou.getenv(k) or "" for k in ("HIP", "HIPFILE", "HIPNAME", "JOB")},
        "hscript_vars": hscript_vars,
        "session_source": hou.sessionModuleSource(),
        "notes": notes,
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
        outcome = json.loads(marker[len("HPRESULT ") :])
        notes = list(self.spec.get("notes") or []) + list(outcome.get("notes") or [])
        outcome["notes"] = notes
        return outcome

    def _log_tail(self, limit: int = 4000) -> str:
        try:
            data = Path(self.log_path).read_bytes()
        except OSError:
            return ""
        return data[-limit:].decode("utf-8", "replace")


def render_isolated(
    rop: str | None,
    frames: list[float],
    parms: dict[str, Any] | None = None,
    *,
    capture: dict[str, Any] | None = None,
    timeout_s: float = CHILD_TIMEOUT_S,
) -> dict[str, Any]:
    """Snapshot and render synchronously in a child hython. Main thread (snapshot).

    With ``capture`` the child builds viewport_capture's camera and ROP in its own scene
    (``rop`` is then None), so the live scene gains no nodes.
    """
    tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
    try:
        snapshot = snapshot_scene(tmp_dir)
        if capture is not None:
            snapshot["capture"] = capture
        child = ChildRender(snapshot, tmp_dir, rop or "", frames, parms)
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

    from ._diag import refresh_stale

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
    camera: Any, res: tuple[int, int], fit: str, out_file: str, generation: int | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """What to build for one capture, and the ``camera_used``/``fit_used`` to report."""
    rop_parms = {"trange": 0, "tres": 1, "res1": res[0], "res2": res[1], "picture": out_file}
    if camera is not None:
        cam = _camera_node(camera)
        return (
            {"camera": cam.path(), "rop_parms": rop_parms},
            {"camera_used": cam.path(), "fit_used": "none"},
        )
    fit_used = "none"
    if _last_framing.get("generation") != generation:
        _last_framing.clear()  # framed in another scene
    framing = _last_framing.get("framing")
    if fit != "none" or framing is None:
        bbox, fit_used = _fit_bbox(fit if fit != "none" else "all")
        framing = _framing(bbox, res)
        _last_framing.update(framing=framing, generation=generation)
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
        {"camera_used": TEMPORARY_CAMERA, "fit_used": fit_used},
    )


@contextlib.contextmanager
def temporary_capture_nodes(spec: dict[str, Any]) -> Iterator[Any]:
    """Create the capture camera (unless the spec names one) and OpenGL ROP in the live
    scene for an in-process render, outside undo, and delete them afterwards, restoring
    the selection. Yields the ROP. Main thread."""
    import hou

    from .events import muted

    selected = hou.selectedNodes()
    created: list[Any] = []
    try:
        with hou.undos.disabler(), muted():
            camera = spec.get("camera")
            if camera is None:
                cam = hou.node("/obj").createNode("cam")
                created.append(cam)
                _mark_internal(cam)
                cam.setDisplayFlag(False)
                for name, value in spec["camera_parms"].items():
                    cam.parm(name).set(value)
                cam.setWorldTransform(hou.Matrix4(spec["camera_xform"]))
                camera = cam.path()
            rop = hou.node("/out").createNode("opengl")
            created.append(rop)
            _mark_internal(rop)
            for name, value in spec["rop_parms"].items():
                rop.parm(name).set(value)
            rop.parm("camera").set(camera)
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


def _capture_opengl(
    ctx: HostContext, camera: Any, frame: float, res: tuple[int, int], fit: str, out_file: str
) -> dict[str, Any]:
    import hou

    spec, info = _capture_spec(camera, res, fit, out_file, ctx.scene.generation)
    errors: list[str] = []
    if not ctx.ui:
        # Headless: the child hython builds camera and ROP in its own copy of the scene.
        outcome = render_isolated(None, [frame, frame, 1], capture=spec)
        errors = outcome.get("errors") or []
        if outcome.get("notes"):
            info["notes"] = outcome["notes"]
    else:
        was_dirty = scene_dirty(ctx)
        with temporary_capture_nodes(spec) as rop:
            try:
                rop.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
        if not was_dirty and scene_dirty(ctx):
            info["notes"] = [
                "Houdini marks the hip modified when the temporary capture camera and ROP are "
                "created, although both were deleted and nothing else changed."
            ]
    _check_capture_output(errors, out_file)
    return info


def _check_capture_output(errors: list[str], out_file: str) -> None:
    if errors or not os.path.isfile(out_file):
        raise ToolError(
            "cook_failed",
            f"The OpenGL ROP did not produce an image: {errors[0] if errors else 'no output file'}",
            hint="Check that the scene cooks (problems tool) and that a GPU is available.",
            detail={"errors": errors},
        )


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


def _capture_args(args: dict[str, Any]) -> dict[str, Any]:
    """Validate viewport_capture's arguments without touching ``hou``."""
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
    extra_path = args.get("path")
    if extra_path is not None and (
        not isinstance(extra_path, str) or not extra_path.strip().lower().endswith(".png")
    ):
        raise ToolError(
            "invalid_argument",
            "'path' must be a .png file: the capture is always a PNG.",
            hint="Use a path ending in .png, or render with a ROP for other formats.",
        )
    return {
        "source": source,
        "fit": fit,
        "res": res,
        "frame": frame,
        "camera": args.get("camera"),
        "path": extra_path,
    }


def _capture_targets(parsed: dict[str, Any], ctx: HostContext) -> tuple[float, Any, str]:
    """Frame, checked extra path and capture file for one capture. Main thread."""
    import hou

    frame = float(hou.frame() if parsed["frame"] is None else parsed["frame"])
    extra_path = parsed["path"]
    if extra_path is not None:
        extra_path = resolve_path(extra_path)
        check_allowed(extra_path, ctx)
    out_file = _fwd(_captures(ctx) / f"capture_{_stamp()}.png")
    return frame, extra_path, out_file


def _finish_capture(
    out_file: str, res: tuple[int, int], frame: float, info: dict[str, Any], extra_path: Any
) -> dict[str, Any]:
    """Encode the capture and copy it to ``path``. No ``hou``."""
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
    prune_captures(Path(out_file).parent)
    return result


def _capture_main(parsed: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """The whole capture on the main thread: the GUI path (viewer or in-process OpenGL
    ROP), and headless when called inline on the main thread."""
    source, camera, res = parsed["source"], parsed["camera"], parsed["res"]
    frame, extra_path, out_file = _capture_targets(parsed, ctx)
    viewer = None
    if source == "viewer":
        viewer = _scene_viewer()
        if viewer is None:
            raise ToolError(
                "invalid_value",
                "No Scene Viewer pane is open.",
                hint="Open a Scene Viewer, or use source 'opengl_rop'.",
            )
    elif source == "auto" and ctx.ui:
        viewer = _scene_viewer()
    if viewer is not None:
        info = _capture_viewer(viewer, camera, frame, res, out_file)
        info["source_used"] = "viewer"
    else:
        info = _capture_opengl(ctx, camera, frame, res, parsed["fit"], out_file)
        info["source_used"] = "opengl_rop"
    return _finish_capture(out_file, res, frame, info, extra_path)


def _capture_headless(parsed: dict[str, Any], ctx: HostContext, timeout_s: float) -> dict[str, Any]:
    """Headless, off the main thread: snapshot in one short main-thread step, then wait
    for the child hython here so the main thread stays free."""
    deadline = time.monotonic() + timeout_s
    res = parsed["res"]
    tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
    try:

        def prepare() -> dict[str, Any]:
            frame, extra_path, out_file = _capture_targets(parsed, ctx)
            spec, info = _capture_spec(
                parsed["camera"], res, parsed["fit"], out_file, ctx.scene.generation
            )
            snapshot = snapshot_scene(tmp_dir)
            snapshot["capture"] = spec
            return {
                "frame": frame,
                "extra_path": extra_path,
                "out_file": out_file,
                "info": info,
                "snapshot": snapshot,
            }

        prep = ctx.executor.run(prepare, timeout_s)
        frame = prep["frame"]
        child = ChildRender(prep["snapshot"], tmp_dir, "", [frame, frame, 1])
        child.start()
        try:
            outcome = child.wait(timeout_s=max(1.0, deadline - time.monotonic()))
        finally:
            child.kill()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _check_capture_output(outcome.get("errors") or [], prep["out_file"])
    info = dict(prep["info"], source_used="opengl_rop")
    if outcome.get("notes"):
        info["notes"] = outcome["notes"]
    return _finish_capture(prep["out_file"], res, frame, info, prep["extra_path"])


@tool("viewport_capture", scene=False, main_thread=False)
def viewport_capture(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Off the main thread so a headless capture does not hold it while the child hython
    renders; the GUI path runs as one main-thread call, as before."""
    parsed = _capture_args(args)
    if parsed["source"] == "viewer" and not ctx.ui:
        raise ToolError(
            "ui_required",
            "source 'viewer' captures the GUI Scene Viewer, and this Houdini is headless.",
            hint="Use source 'opengl_rop' (or 'auto'), which renders headless.",
        )
    timeout_s = float(call_timeout(None) or ctx.config.default_timeout_s)
    if ctx.executor.on_main_thread():
        return _capture_main(parsed, ctx)
    if ctx.ui:
        return ctx.executor.run(lambda: _capture_main(parsed, ctx), timeout_s)
    return _capture_headless(parsed, ctx, timeout_s)


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


def output_pattern(first: str, last: str) -> str:
    """``render/s.####.png`` from the first and last outputs: the digit run that differs
    becomes ``#`` per digit of the first. Falls back to ``first … last``."""
    if first == last:
        return first
    prefix = len(os.path.commonprefix([first, last]))
    suffix = len(os.path.commonprefix([first[::-1], last[::-1]]))
    suffix = min(suffix, len(first) - prefix, len(last) - prefix)
    start, end = prefix, len(first) - suffix
    while start > 0 and first[start - 1].isdigit():
        start -= 1
    while end < len(first) and first[end].isdigit():
        end += 1
    run = first[start:end]
    if not run.isdigit():
        return f"{first} … {last}"
    return first[:start] + "#" * len(run) + first[end:]


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
    # Every file the render will write, not only an override (one check per directory).
    checked: set[str] = set()
    for path in expected:
        if not path.strip() or path.strip() in MPLAY_OUTPUTS:
            continue
        full = _fwd(os.path.abspath(path))
        folder = os.path.dirname(full)
        if folder not in checked:
            checked.add(folder)
            check_allowed(full, ctx)
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
        "lights": scene_has_lights(),
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
    if len(outputs) > INLINE_OUTPUTS:
        result["outputs_summary"] = {
            "count": len(outputs),
            "first": outputs[0],
            "last": outputs[-1],
            "pattern": output_pattern(outputs[0], outputs[-1]),
            "missing_count": len(missing),
        }
    notes: list[str] = []
    images = [
        p for p in plan["expected"] if os.path.splitext(p)[1].lower() in IMAGE_EXTS | CONVERT_EXTS
    ]
    if images and not plan.get("lights", True):
        notes.append(NO_LIGHTS_NOTE)
    if notes:
        result["notes"] = notes
    if thumbnail and outputs:
        last = outputs[-1]
        ext = os.path.splitext(last)[1].lower()
        if ext in IMAGE_EXTS or ext in CONVERT_EXTS:
            try:
                image = encode_png(last, THUMB_MAX_SIDE, hfs=plan["hfs"], measure=True)
                mean = image.pop("mean_luma", None)
                if mean is not None and mean < DARK_MEAN:
                    notes.append(
                        f"The thumbnail is nearly black (mean luminance {mean:.1f}/255): check "
                        "lights, camera framing and exposure."
                    )
                    result["notes"] = notes
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
            result = _render_result(plan, thumbnail)
            if outcome.get("notes"):
                result["notes"] = [*outcome["notes"], *result.get("notes", [])]
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_in_process(job: Any) -> dict[str, Any]:
        saved: dict[str, Any] = {}
        notes: list[str] = []

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
                # Never raises: a render error stays the error the caller sees.
                note = run_with_fallback(ctx.executor, restore, 60.0)
                if note:
                    notes.append(f"Restoring {plan['rop']} {plan['parm']} failed: {note}.")
        result = _render_result(plan, thumbnail)
        if notes:
            result["notes"] = [*notes, *result.get("notes", [])]
        return result

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
    # An explicit wait_s is the caller's own threshold; without one, job_threshold_s
    # decides as for cook and pdg (BIBLE §7).
    wait_s = args.get("wait_s")
    if wait_s is None:
        wait_s = float(ctx.config.job_threshold_s)
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
        result["state"] = "done"
        if "outputs_summary" in result:
            # The full list stays on the job (review 11 B6).
            result.pop("outputs", None)
            result["hint"] = "job {action: result, job_id} lists every output."
        return result
    if job.state in ("failed", "cancelled") and job.error:
        raise ToolError.from_dict(job.error)
    status = job.status()
    status["hint"] = "Poll with job {action: 'status' | 'result', job_id}."
    return status
