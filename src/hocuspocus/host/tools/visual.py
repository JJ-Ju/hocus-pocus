"""Visual feedback: ``viewport_capture`` and ``render``. See docs/BIBLE.md §4.7 and §8.

Images go back as ``{"image": {"png_base64", "mime_type"}}`` (the bridge turns that into
MCP image content) and are also written under ``<state_dir>/captures``.

**Captures render through the Flipbook ROP** (1.4). Houdini 22 deprecates the OpenGL ROP
(``Driver/opengl``) for the Flipbook ROP (``Driver/flipbook``), which has the same output,
resolution, camera and LOP-source parms. viewport_capture's ROP source tries, in order, the
Flipbook ROP, the OpenGL ROP and a temporary Karma CPU ROP (:func:`capture_chain`); each
step that fails says why in ``notes`` and ``source_used`` names the one that ran.

**Headless viewport renders run in a child hython.** In hython 22.0.466 the second
``RopNode.render()`` of any OpenGL ROP in a process segfaults inside the Vulkan viewport
renderer (``GR_FillAttributesVK`` / ``RV_ShaderVariableSet``), whatever the node, frame,
output or geometry; one multi-frame ``render()`` call is fine. The Flipbook ROP renders
the same ROP again in-process (other frames, cameras, resolutions, geometry), but once a
Flipbook ROP that has rendered is deleted (``destroy()`` or ``hip_new``), the next Flipbook
render in that hython segfaults at the same place (``RV_ShaderVariableSet::create``), and
a capture's temporary ROP is always deleted. So headless, the host snapshots the scene
(``saveChildrenToFile`` per manager: no hip save, no event side effects) and renders
Flipbook and OpenGL ROPs in a short-lived ``hython`` (about 3 s per call). In a GUI session
both render in-process (a temporary Flipbook ROP created, rendered and deleted four times,
then again after ``hipFile.clear()``, did not crash in houdinifx 22.0.466). Every other ROP
type renders in-process, frame by frame, through the main-thread executor.

**An OpenGL child that renders a stage runs single-threaded** (``HOUDINI_MAXTHREADS=1``,
review 16 N1). Headless, the Vulkan device is created lazily by the first code that draws;
for a stage of more than a few thousand polygons the OpenGL ROP's LOP source updates the
meshes in parallel, so the device is created on a TBB worker while other workers wait on
it, and hython segfaults in the driver (``RV_Instance::initializeDevice`` under
``GR_PrimPacked::updateInstanceGeometry``; exit 139, also in a fresh hython that loads the
hip itself). One thread creates the device on the rendering thread. The Flipbook ROP does
not have this crash (review 16's city stage rendered multi-threaded in 5 of 5 fresh
hythons), so its children keep every thread. If a stage capture's child still crashes,
the next ROP of the chain renders it, and Karma, in the host, last
(``source_used: "karma"``).
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
from ._diag import a_or_an, require_node
from .geo import frame_num, num
from .hip import _norm, check_allowed, resolve_path
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
SOURCES = ("auto", "viewer", "flipbook_rop", "opengl_rop")
"""``opengl_rop`` is the 1.3 name of ``flipbook_rop``: both run :func:`capture_chain`."""
CAPTURE_ROPS = ("flipbook", "opengl")
"""The viewport ROP types viewport_capture tries, in order, before Karma (1.4)."""
ROP_SOURCE_USED = {"flipbook": "flipbook_rop", "opengl": "opengl_rop", "karma": "karma"}
ROP_LABELS = {"flipbook": "Flipbook ROP", "opengl": "OpenGL ROP", "karma": "Karma"}
VIEWPORT_ROP_TYPES = frozenset(CAPTURE_ROPS)
"""ROP types whose headless renders go through a child hython (module docstring)."""
FITS = ("all", "selected", "none")
OUTPUT_PARMS = (
    "picture",  # flipbook, opengl, karma
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
IMAGE_PARMS = ("picture", "vm_picture", "copoutput", "outputimage")
"""Output parms that name an image; other ROPs (geometry, USD, Alembic) get no note about
a missing thumbnail."""
CHILD_TIMEOUT_S = 600.0
CRASH_LOG_CHARS = 600
"""An error carries at most this much of a crashed child's log (review 16 N1)."""
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
"""A render result lists at most this many outputs; above it, ``outputs_summary`` and
``outputs_sample``, in the direct result and in ``job result`` alike (review 20 N5)."""
OUTPUTS_SAMPLE_ENDS = 2
"""``outputs_sample`` is this many outputs from each end of the sequence."""
MISSING_LISTED = 20
"""``missing`` lists at most this many paths; ``outputs_summary.missing_count`` counts all."""
DARK_MEAN = 8.0
"""A thumbnail whose mean luminance (0..255), measured on the flattened image the agent
receives, is below this is reported as nearly black."""
NO_LIGHTS_NOTE = (
    "Scene has no lights; a Flipbook or OpenGL ROP render relies on the ROP's headlight "
    "setting and other renderers may render black."
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


def _mark_internal(node: Any) -> None:
    with contextlib.suppress(Exception):
        node.setUserData(INTERNAL_KEY, "1")


def _flatten(im: Any) -> Any:
    """``im`` as RGB, with any alpha composited onto :data:`BACKGROUND`."""
    from PIL import Image

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, BACKGROUND)
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return im.convert("RGB")


def flatten_png_in_place(path: str) -> None:
    """Rewrite a capture PNG without alpha, on the inline image's grey (review 12): the
    OpenGL ROP has no background-colour parm and writes a transparent background, which
    most image viewers show as white. Captures only; render outputs are never touched."""
    from PIL import Image

    with Image.open(path) as im:
        im.load()
        if im.mode == "RGB":
            return
        flat = _flatten(im)
    flat.save(path, format="PNG")


def encode_png(
    path: str, max_side: int, *, hfs: str | None = None, measure: bool = False
) -> dict[str, Any]:
    """Load an image file, flatten alpha onto grey, downscale, return the image dict.

    Formats PIL cannot read (EXR, .pic, ...) are converted with ``$HFS/bin/iconvert``.
    ``measure`` adds ``mean_luma``: the mean luminance (0..255) of the returned image,
    after alpha is flattened onto grey (review 20 N1: measured on the raw RGBA, the
    transparent pixels of a sparse OpenGL frame counted as black), and, for an image with
    alpha, ``coverage``: the fraction of its pixels with alpha above 0.
    """
    from PIL import Image

    source = path
    tmp_dir = None

    def convert() -> str:
        nonlocal tmp_dir
        tmp_dir = tmp_dir or tempfile.mkdtemp(prefix="hp-thumb-")
        target = os.path.join(tmp_dir, "thumb.png")
        exe = os.path.join(
            hfs or os.environ.get("HFS", ""),
            "bin",
            "iconvert.exe" if sys.platform == "win32" else "iconvert",
        )
        proc = subprocess.run(
            [exe, path, target],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or not os.path.isfile(target):
            raise ToolError(
                "internal",
                f"iconvert could not convert {path} to PNG.",
                hou_exception=f"iconvert exit {proc.returncode}",
                detail={"stderr": (proc.stderr or proc.stdout)[-2000:]},
            )
        return target

    try:
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
            source = convert()
        try:
            opened = Image.open(source)
        except Exception:
            if source != path:
                raise
            # A TIFF PIL cannot read (float or 16-bit Copernicus output; review 18): let
            # iconvert make a PNG of it.
            source = convert()
            opened = Image.open(source)
        with opened as im:
            im.load()
            coverage = None
            if measure and (
                im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            ):
                alpha = im.convert("RGBA").getchannel("A")
                total = alpha.size[0] * alpha.size[1]
                coverage = (total - alpha.histogram()[0]) / float(total or 1)
            flat = _flatten(im)
            if max(flat.size) > max_side:
                flat.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            mean_luma = None
            if measure:
                from PIL import ImageStat

                mean_luma = float(ImageStat.Stat(flat.convert("L")).mean[0])
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
            if coverage is not None:
                out["coverage"] = coverage
            return out
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# -- isolated (child hython) rendering ---------------------------------------------

_BUILD_CAPTURE = r"""
def capture_camera(hou, capture, created):
    # The camera a capture looks through: (lop, camera prim) for a stage, (None, OBJ camera
    # path) for /obj. A framed camera is built (a camera LOP after the LOP for a stage).
    lop = capture.get("lop")
    if lop is not None:
        prim = capture.get("camera_prim")
        if prim is None:
            src = hou.node(lop)
            cam = src.parent().createNode("camera")
            created.append(cam)
            cam.setInput(0, src)
            for name, value in capture["camera_parms"].items():
                cam.parm(name).set(value)
            lop, prim = cam.path(), cam.parm("primpath").eval()
        return lop, prim
    camera = capture.get("camera")
    if camera is None:
        cam = hou.node("/obj").createNode("cam")
        created.append(cam)
        cam.setDisplayFlag(False)
        for name, value in capture["camera_parms"].items():
            cam.parm(name).set(value)
        cam.setWorldTransform(hou.Matrix4(capture["camera_xform"]))
        camera = cam.path()
    return None, camera


def build_capture(hou, capture, created):
    # viewport_capture's camera and viewport ROP (rop_type: flipbook or opengl, the same
    # parms). Every node made is appended to created.
    rop = hou.node("/out").createNode(capture.get("rop_type") or "flipbook")
    created.append(rop)
    for name, value in capture["rop_parms"].items():
        rop.parm(name).set(value)
    lop, camera = capture_camera(hou, capture, created)
    if lop is not None:
        # A stage: the ROP reads the LOP through the camera prim.
        rop.parm("opsource").set(1)
        rop.parm("loppath").set(lop)
        rop.parm("cameraprim").set(camera)
    else:
        rop.parm("camera").set(camera)
    return rop
"""
"""The capture camera and ROP builder, run in the child hython (headless) and in-process
(GUI) alike."""

_CHILD_SCRIPT = (
    r"""
import json, sys
"""
    + _BUILD_CAPTURE
    + r"""
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
        spec["rop"] = build_capture(hou, capture, []).path()
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
)


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
        files[manager.path()] = _norm(target)
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


def crash_summary(log: str, limit: int = CRASH_LOG_CHARS) -> str:
    """The useful part of a child's output, at most ``limit`` characters. For a Houdini
    crash report: the lines before the traceback (``Fatal error: Segmentation fault``) and
    the crashing thread's frames as bare symbols; the idle ``OTHER THREAD`` stacks are
    dropped. Otherwise the end of the output. No ``hou``."""
    if "-- TRACEBACK BEGIN --" not in log:
        return log[-limit:]
    head, _, rest = log.partition("-- TRACEBACK BEGIN --")
    keep = [line.strip() for line in head.splitlines() if line.strip()][-3:]
    thread = False
    for line in rest.splitlines():
        line = line.strip()
        if line.startswith("CURRENT THREAD"):
            thread = True
            keep.append(line)
            continue
        if line.startswith(("OTHER THREAD", "-- TRACEBACK END")):
            thread = False
            continue
        if thread and line:
            symbol = line[line.find("[") + 1 : line.find("]")] if "[" in line else ""
            module = os.path.basename(line.rsplit(" ", 1)[-1].replace("\\", "/"))
            keep.append(f"{symbol} ({module})" if symbol else module)
    out = "\n".join(keep)
    return out if len(out) <= limit else out[: limit - 3] + "..."


class ChildRender:
    """One child hython rendering a snapshot. Off the main thread after :meth:`start`."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        tmp_dir: str,
        rop: str,
        frames: list[float],
        parms: dict[str, Any] | None = None,
        *,
        single_thread: bool = False,
    ) -> None:
        self.tmp_dir = tmp_dir
        self.spec = dict(snapshot, rop=rop, frames=list(frames), parms=parms or {})
        capture = snapshot.get("capture") or {}
        self.single_thread = single_thread or bool(
            capture.get("lop") and capture.get("rop_type") == "opengl"
        )
        """An OpenGL ROP rendering a stage: see the module docstring (review 16 N1)."""
        self.proc: subprocess.Popen[bytes] | None = None
        self.log_path = os.path.join(tmp_dir, "child.log")

    def start(self) -> None:
        script = os.path.join(self.tmp_dir, "render_child.py")
        spec_path = os.path.join(self.tmp_dir, "spec.json")
        Path(script).write_text(_CHILD_SCRIPT, encoding="utf-8")
        Path(spec_path).write_text(json.dumps(self.spec), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.single_thread:
            env["HOUDINI_MAXTHREADS"] = "1"
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
                    detail={"log": crash_summary(self._log_tail())},
                )
            if on_poll is not None:
                on_poll()
            time.sleep(JOB_POLL_S)
        log = self._log_tail(200_000)
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
                detail={"log": crash_summary(log), "exit_code": self.proc.returncode},
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


def rop_core_type(rop_node: Any) -> str:
    return rop_node.type().name().split("::")[0]


def needs_isolation(rop_node: Any, ctx: HostContext) -> bool:
    """Headless Flipbook and OpenGL ROPs render in a child hython (module docstring)."""
    return not ctx.ui and rop_core_type(rop_node) in VIEWPORT_ROP_TYPES


# -- Copernicus images (review 18) ----------------------------------------------------

CHANNEL_NAMES = {1: ("mono",), 2: ("u", "v"), 3: ("r", "g", "b"), 4: ("r", "g", "b", "a")}
COP_ROP_CANDIDATES = 10
NON_IMAGE_OUTPUTS = ("Geometry", "VDB")


def is_cop_node(node: Any) -> bool:
    """A Copernicus node (category ``Cop``)."""
    import hou

    return isinstance(node, hou.CopNode)


def is_cop_network(node: Any) -> bool:
    """A network whose children are Copernicus nodes (``/img/<copnet>``, a SOP copnet)."""
    import hou

    try:
        return node.childTypeCategory() == hou.copNodeTypeCategory()
    except Exception:
        return False


def cop_display(net: Any) -> Any:
    """The display-flagged Cop node in a COP network, or None."""
    for child in net.children():
        with contextlib.suppress(Exception):
            if child.isDisplayFlagSet():
                return child
    return None


def cop_image_node(node: Any) -> Any:
    """``node`` when it is a Cop node, a COP network's display node, else None."""
    if is_cop_node(node):
        return node
    if is_cop_network(node):
        return cop_display(node)
    return None


def cop_rop_candidates(node: Any) -> list[str]:
    """The ``rop_image`` nodes in the COP network holding ``node`` (or ``node`` itself
    when it is the network), which ``render`` can render."""
    net = node if is_cop_network(node) else node.parent()
    out = []
    for child in net.children() if net is not None else ():
        with contextlib.suppress(Exception):
            if child.type().nameComponents()[2] == "rop_image":
                out.append(child.path())
    return out[:COP_ROP_CANDIDATES]


def cop_hint(node: Any) -> str:
    """Where a COP node's pixels come from: viewport_capture cop_path for a look, a
    rop_image for files (review 18 papercuts 1 and 2)."""
    net = node if is_cop_network(node) else node.parent()
    where = net.path() if net is not None else "the COP network"
    return (
        f"viewport_capture {{cop_path: {node.path()}}} returns the image; to write files, "
        f"render a Cop rop_image inside {where} (coppath = the node)."
    )


def _rect(rect: Any) -> list[Any]:
    """``[xmin, ymin, xmax, ymax]`` of a ``hou.BoundingRect``."""
    return [num(v, 6) for v in (*rect.min(), *rect.max())]


def _channel_stats(layer: Any, count: int) -> dict[str, Any]:
    names = CHANNEL_NAMES.get(count) or tuple(f"c{i}" for i in range(count))
    stats: dict[str, Any] = {}
    for index, name in enumerate(names):
        with contextlib.suppress(Exception):
            stats[name] = {
                "min": num(layer.computeMin(index), 6),
                "max": num(layer.computeMax(index), 6),
                "mean": num(layer.computeAverage(index), 6),
            }
    return stats


def image_summary(node: Any, frame: float | None = None, *, stats: bool = True) -> dict[str, Any]:
    """What a Cop node's first output holds (review 18 papercut 3): ``{output, layer_type,
    resolution, data_window, pixel_scale, storage, border, constant?, channels: {name:
    {min, max, mean}}}`` from ``CopNode.layer()``; other outputs are named in
    ``other_outputs``. A non-image output (geometry, VDB) has only its type. Main thread."""
    names = list(node.outputNames())
    types = list(node.outputDataTypes())
    out: dict[str, Any] = {"output": names[0] if names else None}
    out["layer_type"] = types[0] if types else None
    layer = node.layer(0) if frame is None else node.layerAtFrame(float(frame), 0)
    if layer is not None:
        out["resolution"] = list(layer.bufferResolution())
        out["data_window"] = _rect(layer.dataWindow())
        out["pixel_scale"] = [num(v, 6) for v in layer.pixelScale()]
        with contextlib.suppress(Exception):
            out["storage"] = layer.storageType().name().lower()
            out["border"] = layer.border().name().lower()
        with contextlib.suppress(Exception):
            if layer.isConstant():
                out["constant"] = True
        if stats:
            out["channels"] = _channel_stats(layer, int(layer.channelCount()))
    others = [
        {"name": name, "layer_type": types[i] if i < len(types) else None}
        for i, name in enumerate(names)
        if i > 0
    ]
    if others:
        out["other_outputs"] = others
    return out


def _cop_target(path: Any) -> Any:
    """The Cop node ``cop_path`` names (a COP network means its display node). Main
    thread."""
    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", "'cop_path' must be a Cop node path.")
    node = require_node(path, field="cop_path")
    target = cop_image_node(node)
    if target is not None:
        return target
    if is_cop_network(node):
        raise ToolError(
            "invalid_argument",
            f"{node.path()} has no display node to capture.",
            hint="Pass a Cop node inside it, or set a display flag.",
            candidates=[c.path() for c in node.children()][:10],
        )
    raise ToolError(
        "invalid_argument",
        f"{node.path()} is {a_or_an(node.type().category().name())} node, not a Cop "
        "(Copernicus) node.",
        hint="Pass a node inside a COP network, such as /img/comp1/blend1; camera or "
        "lop_path capture /obj and stages.",
    )


def capture_cop(ctx: HostContext, parsed: dict[str, Any]) -> dict[str, Any]:
    """Render a Cop node through a temporary ``rop_image`` in its network to a PNG under
    the captures dir and return it like any capture (review 18 papercut 1). The ROP is made
    outside undo and events and deleted afterwards; about 0.2 s. Main thread."""
    import hou

    from .events import muted

    node = _cop_target(parsed["cop_path"])
    frame, extra_path, out_file = _capture_targets(parsed, ctx)
    types = list(node.outputDataTypes())
    if types and types[0] in NON_IMAGE_OUTPUTS:
        raise ToolError(
            "invalid_argument",
            f"{node.path()} outputs {types[0]}, not an image layer.",
            hint="geo_info reads it; capture an image node instead.",
        )
    was_dirty = scene_dirty(ctx)
    errors: list[str] = []
    with hou.undos.disabler(), muted():
        rop = node.parent().createNode("rop_image", "__hocuspocus_capture__")
        try:
            _mark_internal(rop)
            for name, value in (("coppath", node.path()), ("copoutput", out_file), ("trange", 0)):
                rop.parm(name).set(value)
            try:
                rop.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
        finally:
            with contextlib.suppress(Exception):
                rop.destroy()
    if errors or not os.path.isfile(out_file):
        message, detail = failure(f"{node.path()} did not render an image", errors)
        raise ToolError(
            "cook_failed",
            message,
            hint="Check the node's errors with problems, then capture again.",
            detail=detail or None,
        )
    layer = image_summary(node, frame, stats=False)
    info: dict[str, Any] = {
        "scene": "cop",
        "cop_path": node.path(),
        "source_used": "rop_image",
        "layer": {k: layer[k] for k in ("layer_type", "resolution", "data_window") if k in layer},
    }
    if "other_outputs" in layer:
        info["layer"]["other_outputs"] = [o["name"] for o in layer["other_outputs"]]
    notes = []
    if parsed.get("resolution_given"):
        notes.append("resolution is ignored with cop_path: the image is the COP's own size.")
    if not was_dirty and scene_dirty(ctx):
        notes.append(
            "Houdini marks the hip modified when the temporary rop_image is created, although "
            "it was deleted and nothing else changed."
        )
    if notes:
        info["notes"] = notes
    size = tuple(layer.get("resolution") or (0, 0))
    return _finish_capture(out_file, size, frame, info, extra_path)


def _cop_networks() -> list[str]:
    """COP networks under /img, with their display nodes, for the capture note."""
    import hou

    found = []
    img = hou.node("/img")
    for net in img.children() if img is not None else ():
        if is_cop_network(net) and not net.userData(INTERNAL_KEY):
            display = cop_display(net)
            found.append(net.path() + (f" (display {display.path()})" if display else ""))
    return found[:3]


def _refuse_cop_as(field: str, value: Any) -> None:
    """A Cop node passed as camera or lop_path: say cop_path (review 18 papercut 1)."""
    import hou

    if not isinstance(value, str) or not value.startswith("/"):
        return
    node = hou.node(value)
    if node is not None and (is_cop_node(node) or is_cop_network(node)):
        what = "network" if is_cop_network(node) else "node"
        raise ToolError(
            "invalid_argument",
            f"{node.path()} is a Copernicus {what}, not a "
            f"{'camera' if field == 'camera' else 'LOP'}.",
            hint=f"Pass cop_path {node.path()} to capture its image.",
        )


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
        hint=hint + " A LOP camera node, or a camera prim with lop_path, captures the stage.",
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

    from .usd import cooked_stage, resolve_lop

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
            f"{node.path()} is an OBJ camera, and lop_path captures a stage.", cooked_stage(lop)
        )
    return {"scene": "obj", "camera": _obj_camera(camera)}


def _stage_bbox(lop: Any) -> tuple[list[float], list[float]] | None:
    """World bounds of the LOP's stage (default and render purposes), or None."""
    import hou

    from .usd import cooked_stage, stage_bbox

    stage = cooked_stage(lop)
    box = stage_bbox(stage, [stage.GetPseudoRoot()], hou.frame())
    return None if box is None else (box["min"], box["max"])


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
    (``rop_type``) in the live scene for an in-process render, outside undo, and delete them afterwards, restoring
    the selection. Yields the ROP. Main thread."""
    import hou

    from .events import muted

    selected = hou.selectedNodes()
    created: list[Any] = []
    namespace: dict[str, Any] = {}
    exec(_BUILD_CAPTURE, namespace)  # the same builder the child hython runs
    try:
        with hou.undos.disabler(), muted():
            try:
                rop = namespace["build_capture"](hou, spec, created)
            finally:
                for node in created:
                    _mark_internal(node)
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


def capture_chain(available: Any) -> list[str]:
    """The renderers a ROP-source capture tries, in order: the Flipbook ROP, the OpenGL ROP
    (each when this Houdini has the type) and Karma last. No ``hou``."""
    have = set(available)
    return [t for t in CAPTURE_ROPS if t in have] + ["karma"]


def available_capture_rops() -> list[str]:
    """The :data:`CAPTURE_ROPS` this Houdini has (22.0 has both; older builds lack the
    Flipbook ROP). Main thread."""
    import hou

    category = hou.ropNodeTypeCategory()
    return [t for t in CAPTURE_ROPS if hou.nodeType(category, t) is not None]


def fallback_note(failures: list[tuple[str, str]], used: str) -> str | None:
    """Why a capture used a later renderer of :func:`capture_chain`: one note naming each
    ROP that did not render and why (``failures``: ``(rop type, reason)``)."""
    if not failures:
        return None
    why = "; ".join(f"the {ROP_LABELS[t]} {reason}" for t, reason in failures)
    if used == "karma":
        return karma_note(why)
    return f"Rendered with the {ROP_LABELS[used]} because {why}."


def run_capture_chain(
    chain: list[str],
    *,
    stage: bool,
    source: str,
    render_rop: Any,
    render_karma: Any,
) -> tuple[str, dict[str, Any], list[str]]:
    """Render one capture with the first renderer of ``chain`` that works. ``render_rop``
    (a ROP type) returns the render outcome or raises; a crashed child moves on to the next
    renderer, any other error is raised. Karma runs only after a crash or skip. Returns
    ``(renderer, outcome, notes)``. Headless, a stage whose child crashed once is not sent
    to that ROP again in this process when ``source`` is ``auto`` (each crash costs
    seconds)."""
    failures: list[tuple[str, str]] = []
    crash: ToolError | None = None
    for renderer in chain:
        if renderer == "karma":
            if not failures:
                break  # nothing crashed: the last ROP's error was raised already
            karma_after_crash(render_karma, crash)
            return "karma", {}, [n for n in (fallback_note(failures, "karma"),) if n]
        if stage and source == "auto" and renderer in _stage_crashed:
            failures.append(
                (renderer, "was skipped (it crashed a stage capture earlier in this session)")
            )
            continue
        try:
            outcome = render_rop(renderer)
        except ToolError as exc:
            if not child_crashed(exc):
                raise
            crash = exc
            if stage:
                _stage_crashed[renderer] = exc.message
            failures.append((renderer, f"crashed its render process ({exc.message})"))
            continue
        return renderer, outcome, [n for n in (fallback_note(failures, renderer),) if n]
    raise ToolError("internal", "No renderer could capture the scene.")


def _capture_rop(
    ctx: HostContext,
    target: dict[str, Any],
    frame: float,
    res: tuple[int, int],
    fit: str,
    out_file: str,
    source: str = "auto",
) -> dict[str, Any]:
    """The ROP source on the main thread: in a child hython headless, in-process in the GUI.
    Sets ``source_used``. Main thread."""
    import hou

    spec, info = _capture_spec(target, res, fit, out_file, ctx.scene.generation)
    chain = capture_chain(available_capture_rops())
    if not ctx.ui:
        # Headless: the child hython builds camera and ROP in its own copy of the scene.
        def render_rop(rop_type: str) -> dict[str, Any]:
            outcome = render_isolated(
                None, [frame, frame, 1], capture=dict(spec, rop_type=rop_type)
            )
            _check_capture_output(outcome.get("errors") or [], out_file, rop_type)
            return outcome

        used, outcome, notes = run_capture_chain(
            chain,
            stage=spec.get("lop") is not None,
            source=source,
            render_rop=render_rop,
            render_karma=lambda: capture_with_karma(spec, frame, res, out_file),
        )
        info["source_used"] = ROP_SOURCE_USED[used]
        _add_notes(info, *(outcome.get("notes") or []), *notes)
        return info
    # GUI: in-process. A ROP that renders no image hands over to the next viewport ROP; a
    # crash here would take Houdini down, so there is no crash fallback (and no Karma).
    failures: list[tuple[str, str]] = []
    rops = [t for t in chain if t != "karma"]
    for i, rop_type in enumerate(rops):
        was_dirty = scene_dirty(ctx)
        errors: list[str] = []
        with temporary_capture_nodes(dict(spec, rop_type=rop_type)) as rop:
            try:
                rop.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
        if not was_dirty and scene_dirty(ctx):
            _add_notes(
                info,
                "Houdini marks the hip modified when the temporary capture camera and ROP are "
                "created, although both were deleted and nothing else changed.",
            )
        try:
            _check_capture_output(errors, out_file, rop_type)
        except ToolError as exc:
            if i == len(rops) - 1:
                raise
            failures.append((rop_type, f"produced no image ({exc.message})"))
            continue
        info["source_used"] = ROP_SOURCE_USED[rop_type]
        _add_notes(info, fallback_note(failures, rop_type))
        return info
    raise ToolError("internal", "This Houdini has neither a Flipbook ROP nor an OpenGL ROP.")


GENERIC_FAILURE = "The attempted operation failed."
ERROR_PREFIXES = ("Error:", "Warning:")


def error_lines(errors: list[str]) -> list[str]:
    """The distinct lines of a ROP's errors, in order: ``hou.OperationFailed`` text and
    ``node.errors()`` repeat each other (review 16 N7: a husk failure said the same thing
    three times). Drops the generic "The attempted operation failed." and the
    ``Error:`` prefixes. No ``hou``."""
    out: list[str] = []
    seen: set[str] = set()
    for error in errors:
        for line in str(error).splitlines():
            line = line.strip()
            for prefix in ERROR_PREFIXES:
                if line.startswith(prefix):
                    line = line[len(prefix) :].strip()
            if not line or line == GENERIC_FAILURE or line in seen:
                continue
            seen.add(line)
            out.append(line)
    if not out and errors:
        out.append(GENERIC_FAILURE)
    return out


def failure(message: str, errors: list[str]) -> tuple[str, dict[str, Any]]:
    """``message: <first error line>`` and a detail with the other lines only."""
    lines = error_lines(errors)
    detail: dict[str, Any] = {}
    if len(lines) > 1:
        detail["errors"] = lines[1:]
    return f"{message}: {lines[0] if lines else 'no output file'}", detail


def _check_capture_output(errors: list[str], out_file: str, rop_type: str = "flipbook") -> None:
    if errors or not os.path.isfile(out_file):
        message, detail = failure(f"The {ROP_LABELS[rop_type]} did not produce an image", errors)
        raise ToolError(
            "cook_failed",
            message,
            hint="Check that the scene cooks (problems tool) and that a GPU is available.",
            detail=detail or None,
        )


KARMA_SAMPLES = 2
"""Pixel samples of the Karma fallback: a quick look, not a final frame."""
_stage_crashed: dict[str, str] = {}
"""ROP type -> crash message, set when a headless stage capture's child of that ROP crashed
in this process: later stage captures with source auto skip that ROP (each crash costs
seconds)."""


def child_crashed(exc: ToolError) -> bool:
    """Whether a child render failed by crashing (not a licence refusal, a timeout or a
    cancel), so another renderer may succeed where a viewport ROP did not."""
    return (
        exc.code == "internal"
        and str(exc.hou_exception or "").startswith("render process exit")
        and "licen" not in str(exc.hint or "").lower()
    )


def _karma_nodes(
    spec: dict[str, Any], res: tuple[int, int], out_file: str, logs: list[str], created: list[Any]
) -> Any:
    """Build the temporary camera (when framed) and Karma ROP for one capture: for a stage
    a karmarendersettings LOP and a usdrender_rop LOP after the captured LOP, for /obj a
    /out karma ROP. Every node made is appended to ``created``. Returns the ROP. Main
    thread, outside undo."""
    import hou

    namespace: dict[str, Any] = {}
    exec(_BUILD_CAPTURE, namespace)
    try:
        lop, camera = namespace["capture_camera"](hou, spec, created)
        values: dict[str, Any]
        if lop is not None:
            src = hou.node(lop)
            settings = src.parent().createNode("karmarendersettings")
            created.append(settings)
            settings.setInput(0, src)
            for name, value in (
                ("camera", camera),
                ("engine", "cpu"),
                ("samplesperpixel", KARMA_SAMPLES),
                ("picture", out_file),
            ):
                settings.parm(name).set(value)
            rop = src.parent().createNode("usdrender_rop")
            created.append(rop)
            rop.setInput(0, settings)
            values = {
                "renderer": "BRAY_HdKarma",
                "override_camera": camera,
                "override_res": "specific",
                "res_user1": res[0],
                "res_user2": res[1],
                "outputimage": out_file,
                "husk_log": 1,
                "husk_stdout": logs[1],
                "husk_stderr": logs[0],
            }
            if settings.parm("primpath") is not None:
                values["rendersettings"] = settings.parm("primpath").eval()
        else:
            rop = hou.node("/out").createNode("karma")
            created.append(rop)
            values = {
                "camera": camera,
                "engine": "cpu",
                "samplesperpixel": KARMA_SAMPLES,
                "override_camerares": 1,
                "res_fraction": "specific",
                "res_overridex": res[0],
                "res_overridey": res[1],
                "picture": out_file,
            }
        values["trange"] = 0
        for name, value in values.items():
            parm = rop.parm(name)
            if parm is not None:
                parm.set(value)
        return rop
    finally:
        for node in created:
            _mark_internal(node)


def capture_with_karma(
    spec: dict[str, Any], frame: float, res: tuple[int, int], out_file: str
) -> None:
    """Render one capture frame with a temporary Karma CPU ROP in the host (review 16 N1):
    the fallback when the viewport ROP children crashed. Karma has no second-render crash, so its
    ROP renders in-process (husk is its own process). Deletes every node it made, outside
    undo and events, and puts the selection back. Raises ``cook_failed`` with the end of
    the husk log. Main thread."""
    import hou

    from .events import muted

    selected = hou.selectedNodes()
    log_dir = tempfile.mkdtemp(prefix="hp-husk-")
    logs = [_norm(os.path.join(log_dir, f)) for f in ("err.log", "out.log")]
    created: list[Any] = []
    errors: list[str] = []
    try:
        with hou.undos.disabler(), muted():
            rop = _karma_nodes(spec, res, out_file, logs, created)
            try:
                rop.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
    finally:
        with hou.undos.disabler(), muted():
            for node in reversed(created):
                with contextlib.suppress(Exception):
                    node.destroy()
            with contextlib.suppress(Exception):
                hou.clearAllSelected()
                for node in selected:
                    node.setSelected(True)
        tail = log_tail(logs, 8)
        shutil.rmtree(log_dir, ignore_errors=True)
    if errors or not os.path.isfile(out_file):
        message, detail = failure("The Karma fallback did not produce an image", errors)
        if tail:
            detail["log_tail"] = tail
        raise ToolError(
            "cook_failed",
            message,
            hint="Check that the scene cooks (problems tool), or render a Karma ROP with render.",
            detail=detail,
        )


def karma_after_crash(run: Any, crash: ToolError | None) -> None:
    """Run the Karma fallback; if it fails after a viewport ROP child crashed, say both,
    with the crashed child's short log as ``detail.opengl_log`` (the 1.3 name, kept)."""
    try:
        run()
    except ToolError as exc:
        if crash is None:
            raise
        detail = dict(exc.detail or {}) if isinstance(exc.detail, dict) else {}
        detail["opengl_log"] = (crash.detail or {}).get("log", "")
        raise ToolError(
            exc.code,
            f"The viewport ROP render process crashed ({crash.message}) and the Karma "
            f"fallback failed: {exc.message}",
            hint=exc.hint,
            detail=detail,
        ) from exc


def karma_note(reason: str) -> str:
    return (
        f"Rendered with a temporary Karma CPU ROP ({KARMA_SAMPLES} samples per pixel) "
        f"because {reason}."
    )


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
    lop_path = args.get("lop_path")
    if lop_path is not None and (not isinstance(lop_path, str) or not lop_path.strip()):
        raise ToolError("invalid_argument", "'lop_path' must be a LOP node path.")
    cop_path = args.get("cop_path")
    if cop_path is not None and (
        args.get("camera") is not None or lop_path is not None or source == "viewer"
    ):
        raise ToolError(
            "invalid_argument",
            "cop_path captures a COP image; it cannot be combined with camera, lop_path or "
            "source viewer.",
        )
    return {
        "cop_path": cop_path,
        "resolution_given": args.get("resolution") is not None,
        "source": source,
        "fit": fit,
        "fit_given": args.get("fit") is not None,
        "res": res,
        "frame": frame,
        "camera": args.get("camera"),
        "lop_path": lop_path,
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
    out_file = _norm(_captures(ctx) / f"capture_{_stamp()}.png")
    return frame, extra_path, out_file


def _finish_capture(
    out_file: str, res: tuple[int, int], frame: float, info: dict[str, Any], extra_path: Any
) -> dict[str, Any]:
    """Flatten the capture onto the inline image's grey, encode it and copy it to
    ``path``. No ``hou``."""
    flatten_png_in_place(out_file)
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


COP_NOTE = "The scene also has COP networks ({nets}); pass cop_path (a Cop node) to capture one."
STAGE_NOTE = (
    "The scene also has a stage ({lop} is displayed in /stage); pass lop_path (or a LOP "
    "camera) to capture it."
)


def _resolve_capture(parsed: dict[str, Any]) -> dict[str, Any]:
    """The capture target plus a note when /obj was captured but /stage has a display
    LOP. Main thread."""
    _refuse_cop_as("camera", parsed["camera"])
    _refuse_cop_as("lop_path", parsed["lop_path"])
    target = capture_target(parsed["camera"], parsed["lop_path"])
    if target["scene"] == "obj" and parsed["camera"] is None:
        display = _stage_display()
        notes = [STAGE_NOTE.format(lop=display.path())] if display is not None else []
        nets = _cop_networks()
        if nets:
            notes.append(COP_NOTE.format(nets=", ".join(nets)))
        if notes:
            target["note"] = " ".join(notes)
    return target


def _add_notes(info: dict[str, Any], *notes: Any) -> None:
    merged = [*info.get("notes", []), *(n for n in notes if n)]
    if merged:
        info["notes"] = merged


def _capture_main(parsed: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """The whole capture on the main thread: the GUI path (viewer or in-process viewport
    ROP), and headless when called inline on the main thread."""
    source, res = parsed["source"], parsed["res"]
    target = _resolve_capture(parsed)
    frame, extra_path, out_file = _capture_targets(parsed, ctx)
    viewer = None
    if source == "viewer":
        if target["scene"] == "stage":
            raise ToolError(
                "invalid_argument",
                "source 'viewer' captures the Scene Viewer as it is; a stage capture (a LOP "
                "camera or lop_path) renders through a Flipbook ROP.",
                hint="Use source 'flipbook_rop' or 'auto'.",
            )
        viewer = _scene_viewer()
        if viewer is None:
            raise ToolError(
                "invalid_value",
                "No Scene Viewer pane is open.",
                hint="Open a Scene Viewer, or use source 'flipbook_rop'.",
            )
    elif source == "auto" and ctx.ui and target["scene"] == "obj" and target["camera"] is None:
        # With a camera, auto renders through the ROP: fast in the GUI, and it leaves the
        # user's view alone (review 15 papercut 1).
        viewer = _scene_viewer()
    if viewer is not None:
        fit = parsed["fit"] if parsed["fit_given"] else None
        info = _capture_viewer(viewer, target, frame, res, out_file, fit)
        info["source_used"] = "viewer"
    else:
        info = _capture_rop(ctx, target, frame, res, parsed["fit"], out_file, source)
    _add_notes(info, target.get("note"))
    return _finish_capture(out_file, res, frame, info, extra_path)


def _capture_headless(parsed: dict[str, Any], ctx: HostContext, timeout_s: float) -> dict[str, Any]:
    """Headless, off the main thread: snapshot in one short main-thread step, then wait
    for the child hython here so the main thread stays free."""
    deadline = time.monotonic() + timeout_s
    res = parsed["res"]
    tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
    try:

        def prepare() -> dict[str, Any]:
            target = _resolve_capture(parsed)
            frame, extra_path, out_file = _capture_targets(parsed, ctx)
            spec, info = _capture_spec(target, res, parsed["fit"], out_file, ctx.scene.generation)
            _add_notes(info, target.get("note"))
            snapshot = snapshot_scene(tmp_dir)
            snapshot["capture"] = spec
            return {
                "chain": capture_chain(available_capture_rops()),
                "frame": frame,
                "extra_path": extra_path,
                "out_file": out_file,
                "info": info,
                "snapshot": snapshot,
            }

        prep = ctx.executor.run(prepare, timeout_s)
        frame = prep["frame"]
        spec = prep["snapshot"]["capture"]

        def render_rop(rop_type: str) -> dict[str, Any]:
            snapshot = dict(prep["snapshot"], capture=dict(spec, rop_type=rop_type))
            child = ChildRender(snapshot, tmp_dir, "", [frame, frame, 1])
            child.start()
            try:
                outcome = child.wait(timeout_s=max(1.0, deadline - time.monotonic()))
            finally:
                child.kill()
            _check_capture_output(outcome.get("errors") or [], prep["out_file"], rop_type)
            return outcome

        def render_karma() -> None:
            ctx.executor.run(
                lambda: capture_with_karma(spec, frame, res, prep["out_file"]),
                max(1.0, deadline - time.monotonic()),
            )

        used, outcome, notes = run_capture_chain(
            prep["chain"],
            stage=spec.get("lop") is not None,
            source=parsed["source"],
            render_rop=render_rop,
            render_karma=render_karma,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    info = dict(prep["info"], source_used=ROP_SOURCE_USED[used])
    _add_notes(info, *(outcome.get("notes") or []), *notes)
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
            hint="Use source 'flipbook_rop' (or 'auto'), which renders headless.",
        )
    timeout_s = float(call_timeout(None) or ctx.config.default_timeout_s)
    if parsed["cop_path"] is not None:
        if ctx.executor.on_main_thread():
            return capture_cop(ctx, parsed)
        return ctx.executor.run(lambda: capture_cop(ctx, parsed), timeout_s)
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


def is_usd_render_rop(rop: Any) -> bool:
    """A USD render ROP (``Lop/usdrender_rop``, ``Driver/usdrender``, Karma's wrappers):
    husk renders the stage; ``lopoutput`` is only its intermediate USD file."""
    return rop.parm("outputimage") is not None and rop.parm("lopoutput") is not None


def _output_parm(rop: Any) -> Any:
    if is_usd_render_rop(rop):
        return rop.parm("outputimage")  # never lopoutput (review 13 papercut 2)
    for name in OUTPUT_PARMS:
        parm = rop.parm(name)
        if parm is not None:
            return parm
    return None


# -- writer SOPs: File Cache, ROP SOPs (review 17 P0-1, P0-2, P1-3) --------------------

SAVE_BUTTON = "execute"
"""The save button of a File Cache and of every ROP (``Save to Disk``, ``Render``)."""
SIDE_EFFECT_CAP = 10
WRITTEN_SLACK_S = 2.0
"""A file counts as written by a press when its mtime is at most this much older than
the press (file systems round mtimes)."""


def writer_rop(node: Any) -> Any:
    """The ROP that writes ``node``'s files: the node itself when it is a ROP (a /out
    driver, a SOP-level ``rop_geometry``/``rop_alembic``, a Cop ``rop_image``), or the
    ROP inside a SOP whose ``execute`` button saves through one, such as
    ``filecache::2.0`` (its ``render`` child, else the first ROP inside it). None for any
    other node. Main thread."""
    import hou

    if isinstance(node, hou.RopNode):
        return node
    if not isinstance(node, hou.SopNode):
        return None
    button = node.parm(SAVE_BUTTON)
    try:
        if button is None or button.parmTemplate().type() != hou.parmTemplateType.Button:
            return None
    except Exception:
        return None
    inner = node.node("render")
    if isinstance(inner, hou.RopNode):
        return inner
    try:
        children = node.allSubChildren(recurse_in_locked_nodes=True)
    except Exception:
        children = ()
    return next((c for c in children if isinstance(c, hou.RopNode)), None)


def rop_frame_range(rop: Any) -> list[float] | None:
    """``[start, end, inc]`` from the ROP's own Valid Frame Range, or None when it renders
    the current frame only (``trange`` 0) or has no range. Main thread."""
    trange = rop.parm("trange")
    if trange is None:
        return None
    try:
        if not int(trange.eval()):
            return None
        start, end = (float(rop.parm(n).eval()) for n in ("f1", "f2"))
        inc = float(rop.parm("f3").eval()) if rop.parm("f3") is not None else 1.0
    except Exception:
        return None
    if inc <= 0 or end < start:
        return None
    return [start, end, inc]


def expected_outputs(rop: Any, frames: list[float]) -> list[str]:
    """The files ``rop`` writes for ``frames`` (``[start, end, inc]``), from its output
    parm; MPlay and empty outputs are left out. Main thread."""
    parm = _output_parm(rop)
    if parm is None:
        return []
    out = []
    for frame in _frame_list(frames):
        value = parm.evalAtFrame(frame).strip()
        if value and value not in MPLAY_OUTPUTS:
            out.append(_norm(value))
    return out


def outputs_summary(outputs: list[str], missing: list[str]) -> dict[str, Any]:
    """``{count, first, last, pattern, missing_count}`` for a file sequence. No ``hou``."""
    summary: dict[str, Any] = {"count": len(outputs)}
    if outputs:
        summary["first"] = outputs[0]
        summary["last"] = outputs[-1]
        summary["pattern"] = output_pattern(outputs[0], outputs[-1])
    summary["missing_count"] = len(missing)
    return summary


def _top_parm_values(node: Any) -> dict[str, Any]:
    """Raw values of ``node``'s value parms (not buttons, folders or labels; menus as
    tokens), to report what a button press changed. Main thread."""
    import hou

    skip = (
        hou.parmTemplateType.Button,
        hou.parmTemplateType.Folder,
        hou.parmTemplateType.FolderSet,
        hou.parmTemplateType.Label,
        hou.parmTemplateType.Separator,
    )
    values: dict[str, Any] = {}
    for parm in node.parms():
        try:
            kind = parm.parmTemplate().type()
            if parm.isMultiParmParent():
                values[parm.name()] = parm.eval()  # the instance count
                continue
            if kind in skip:
                continue
            if kind == hou.parmTemplateType.Menu:
                values[parm.name()] = parm.evalAsString()  # the token, not the index
                continue
            try:
                values[parm.name()] = parm.unexpandedString()
            except Exception:
                values[parm.name()] = parm.eval()
        except Exception:
            continue
    return values


def changed_parms(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """``{name: [old, new]}`` for parms whose raw value changed, at most
    :data:`SIDE_EFFECT_CAP`. No ``hou``."""
    changes = {
        name: [before[name], value]
        for name, value in after.items()
        if name in before and before[name] != value
    }
    return dict(list(changes.items())[:SIDE_EFFECT_CAP])


def press_button(node: Any, parm: Any) -> dict[str, Any]:
    """Press a button (or run a menu's callback) and report it: ``{pressed: true,
    side_effects?}``, plus ``outputs_summary`` for the save button of a writer (a File
    Cache's Save to Disk, a ROP's Render): the files its output parm names over the
    writer's frame range are checked afterwards, and a press that left any of them
    unwritten fails with ``cook_failed`` listing them (review 17 P0-2: a failed save
    reported success). Main thread."""
    import hou

    rop = writer_rop(node) if parm.name() == SAVE_BUTTON else None
    expected: list[str] = []
    if rop is not None:
        frames = rop_frame_range(rop) or [hou.frame(), hou.frame(), 1.0]
        try:
            expected = expected_outputs(rop, frames)
        except Exception:
            expected = []
    before = _top_parm_values(node)
    started = time.time()
    parm.pressButton()
    out: dict[str, Any] = {"pressed": True}
    changes = changed_parms(before, _top_parm_values(node))
    if changes:
        out["side_effects"] = changes
    if not expected:
        return out
    written, missing = [], []
    for path in expected:
        try:
            fresh = os.path.getmtime(path) >= started - WRITTEN_SLACK_S
        except OSError:
            fresh = False
        (written if fresh else missing).append(path)
    if missing:
        errors: list[str] = []
        with contextlib.suppress(Exception):
            errors = error_lines([str(e) for e in rop.errors()])
        detail: dict[str, Any] = {
            "missing": missing[:MISSING_LISTED],
            "missing_count": len(missing),
        }
        if errors:
            detail["errors"] = errors[:5]
        raise ToolError(
            "cook_failed",
            f"{node.path()} {parm.name()} wrote {len(written)} of {len(expected)} files"
            + (f": {errors[0]}" if errors else "."),
            hint="Check that the output directory is writable and the input cooks, then press "
            "again; render runs the same save as a job with progress and cancel.",
            detail=detail,
        )
    out["outputs_summary"] = outputs_summary(written, missing)
    return out


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


def _render_settings_prim(stage: Any, rop: Any) -> Any:
    """The RenderSettings prim husk uses: the ROP's ``rendersettings``, else the stage's
    ``renderSettingsPrimPath``, else the first one under /Render (then anywhere)."""
    from pxr import Usd, UsdRender

    path = ""
    if rop.parm("rendersettings") is not None:
        path = rop.parm("rendersettings").eval().strip()
    if path:
        prim = stage.GetPrimAtPath(path)
        return prim if prim and prim.IsA(UsdRender.Settings) else None
    with contextlib.suppress(Exception):
        settings = UsdRender.Settings.GetStageRenderSettings(stage)
        if settings:
            return settings.GetPrim()
    render = stage.GetPrimAtPath("/Render")
    ranges = [Usd.PrimRange(render)] if render else []
    ranges.append(stage.Traverse())
    for prims in ranges:
        for prim in prims:
            if prim.IsA(UsdRender.Settings):
                return prim
    return None


def usd_render_outputs(rop: Any, frames: list[float]) -> tuple[list[str], str | None]:
    """Image files a USD render ROP writes when ``outputimage`` is empty: the
    ``productName`` of every RenderProduct of its render settings, per frame (review 13
    papercut 1). Returns ``(paths, note)``; the note says why nothing resolved. Main thread."""
    from pxr import Usd, UsdRender

    lop = _usd_source_lop(rop)
    if lop is None:
        return [], (
            f"{rop.path()} has no LOP to render (loppath or an input), so its output image "
            "is unknown; set outputimage, or wire the render settings LOP into it."
        )
    stages: dict[float, Any] = {}

    def stage_at(frame: float | None) -> Any:
        key = -1e30 if frame is None else frame
        if key not in stages:
            stages[key] = lop.stage() if frame is None else lop.stage(frame=frame)
        return stages[key]

    try:
        stage = stage_at(None)
        settings = _render_settings_prim(stage, rop) if stage is not None else None
    except Exception:
        stage = settings = None
    if settings is None:
        return [], (
            f"No output image resolved for {rop.path()}: outputimage is empty and "
            f"{lop.path()}'s stage has no render settings prim with a RenderProduct; set "
            "outputimage, or picture on the render settings LOP."
        )
    targets = UsdRender.Settings(settings).GetProductsRel().GetForwardedTargets()
    paths: list[str] = []
    for frame in frames:
        for target in targets:
            attr = UsdRender.Product(stage.GetPrimAtPath(target)).GetProductNameAttr()
            if not attr:
                continue
            samples = attr.GetTimeSamples()
            current = attr
            if samples and not samples[0] <= frame <= samples[-1]:
                # Sampled over the playbar only: cook the stage at that frame.
                with contextlib.suppress(Exception):
                    current = stage_at(frame).GetPrimAtPath(target).GetAttribute("productName")
            value = current.Get(Usd.TimeCode(frame)) if current else None
            if value:
                paths.append(str(value))
    if not paths:
        return [], (
            f"No output image resolved for {rop.path()}: outputimage is empty and the "
            f"RenderProduct productName under {settings.GetPath()} is empty; set outputimage, "
            "or picture on the render settings LOP."
        )
    return paths, None


def _not_a_render_node(node: Any) -> ToolError:
    if is_cop_node(node) or is_cop_network(node):
        return ToolError(
            "invalid_argument",
            f"{node.path()} ({node.type().name()}) is not a render node.",
            hint=cop_hint(node),
            candidates=cop_rop_candidates(node),
        )
    return ToolError(
        "invalid_argument",
        f"{node.path()} ({node.type().name()}) is not a render node.",
        hint="Pass a ROP such as /out/karma1 or /out/flipbook1, or a writer SOP such as a "
        "File Cache or rop_geometry.",
    )


def job_snapshot(job: Any) -> dict[str, Any]:
    """The job's status as ``job status`` would show it, best effort (``{}`` when the
    job context does not expose it). No ``hou``."""
    inner = getattr(job, "_job", None)
    with contextlib.suppress(Exception):
        if inner is not None:
            return dict(inner.status())
    return {}


def cancelled_with_partial(job: Any, partial: dict[str, Any], done: str) -> ToolError:
    """The ``cancelled`` error a job raises when it stops early, with ``detail:
    {last_status, partial}`` so ``job result`` keeps what was done before the cancel
    (review 17 P1-6). No ``hou``."""
    status = job_snapshot(job)
    if status:
        status["state"] = "cancelled"  # the snapshot was taken while it ran (review 20 N7)
    job_id = status.get("job_id")
    name = f"Job {job_id}" if job_id else "The job"
    return ToolError(
        "cancelled",
        f"{name} was cancelled after {done}.",
        detail={"last_status": status, "partial": partial},
    )


def _render_partial(plan: dict[str, Any]) -> tuple[dict[str, Any], str]:
    outputs = [p for p in plan["expected"] if os.path.isfile(p)]
    missing = [p for p in plan["expected"] if not os.path.isfile(p)]
    total = len(plan["expected"]) or len(plan["frame_list"])
    return {"outputs_summary": outputs_summary(outputs, missing)}, (
        f"{len(outputs)} of {total} output files"
    )


SAVE_SIDE_EFFECTS = ("hardenBaseName", "enableLoadFromDisk")
"""What a File Cache's Save to Disk does after its ROP rendered (its PythonModule's
``saveToDisk``): harden the base name, turn on Load from Disk."""


def _writer_side_effects(owner_path: str) -> dict[str, list[Any]]:
    """After a writer SOP rendered through its inner ROP, do what its own save button
    does next (a File Cache turns on Load from Disk and reloads) as one undo step, and
    return the parms that changed. Main thread."""
    import hou

    from ..undo import hou_undo_group, make_label

    node = hou.node(owner_path)
    if node is None:
        return {}
    before = _top_parm_values(node)
    try:
        module = node.hdaModule()
    except Exception:
        return {}
    steps = [getattr(module, name, None) for name in SAVE_SIDE_EFFECTS]
    if not any(callable(step) for step in steps):
        return {}
    with hou_undo_group(make_label("render", {"rop_path": owner_path})):
        for step in steps:
            if callable(step):
                with contextlib.suppress(Exception):
                    step(node)
        reload = node.parm("reload")
        if reload is not None:
            with contextlib.suppress(Exception):
                reload.pressButton()
    return changed_parms(before, _top_parm_values(node))


def _writer_output_hint(owner: Any) -> str:
    """How to change the output of a writer SOP that renders through its inner ROP, in
    ``parm_set`` terms: a File Cache's ``filemethod`` by its menu token (review 20 N4: the
    hint said ``filemethod 1``, an index ``parm_set`` does not take)."""
    method, file_parm = owner.parm("filemethod"), owner.parm("file")
    explicit = None
    with contextlib.suppress(Exception):
        if method is not None and "explicit" in method.menuItems():
            explicit = "explicit"
    if explicit and file_parm is not None:
        return (
            f'Set the output with parm_set on {owner.path()} (filemethod: "{explicit}", then '
            "file: the path), then render without output."
        )
    return "Set the node's own output parm with parm_set, then render without output."


def _prepare_render(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Validate on the main thread and compute the expected output files."""
    import hou

    rop_path = args.get("rop_path")
    if not isinstance(rop_path, str) or not rop_path.strip():
        raise ToolError("invalid_argument", "'rop_path' must be a ROP node path.")
    owner = require_node(rop_path, field="rop_path")
    rop = owner if callable(getattr(owner, "render", None)) else writer_rop(owner)
    if rop is None:
        raise _not_a_render_node(owner)
    # A writer SOP (File Cache, rop_geometry SOP) renders its own frame range by default;
    # a File Cache renders through the ROP inside it (review 17 P1-3).
    writer = rop is not owner or owner.type().category().name() == "Sop"
    frames = _frames(args.get("frames"))
    if frames is None:
        frames = (rop_frame_range(rop) if writer else None) or [hou.frame(), hou.frame(), 1.0]
    output = args.get("output")
    parm = _output_parm(rop)
    usd = is_usd_render_rop(rop)
    if output is not None:
        if not isinstance(output, str) or not output.strip():
            raise ToolError("invalid_argument", "'output' must be a non-empty path.")
        if rop is not owner:
            raise ToolError(
                "invalid_argument",
                f"{owner.path()} ({owner.type().name()}) writes through the ROP inside it, "
                "whose output cannot be overridden.",
                hint=_writer_output_hint(owner),
            )
        if parm is None:
            raise ToolError(
                "invalid_argument",
                f"{rop.path()} ({rop.type().name()}) has no output parm to override.",
                hint="Set the ROP's output parm with parm_set, then render without output.",
            )
        output = output.strip()
        check_allowed(resolve_path(output), ctx)
    expected: list[str] = []
    note = None
    if output is None and usd and not parm.evalAtFrame(frames[0]).strip():
        expected, note = usd_render_outputs(rop, _frame_list(frames))
    else:
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
        full = _norm(path)
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
        "owner": owner.path() if rop is not owner else None,
        "type": rop.type().name(),
        "core_type": rop_core_type(rop),
        "frames": frames,
        "frame_list": _frame_list(frames),
        "parm": parm.name() if parm is not None else None,
        "image_rop": usd or (parm is not None and parm.name() in IMAGE_PARMS),
        "output": output,
        "expected": [_norm(p) for p in expected],
        "usd": usd,
        "note": note,
        "isolate": needs_isolation(rop, ctx),
        "stage_source": rop.parm("opsource") is not None and rop.parm("opsource").eval() == 1,
        "hfs": hou.text.expandString("$HFS"),
        # A COP image needs no lights (review 18 papercut 7).
        "lights": (parm is not None and parm.name() == "copoutput") or scene_has_lights(),
    }


def outputs_listing(outputs: list[str], missing: list[str]) -> dict[str, Any]:
    """``outputs`` when there are at most :data:`INLINE_OUTPUTS`, else ``outputs_summary``
    plus ``outputs_sample`` (the first and last :data:`OUTPUTS_SAMPLE_ENDS`); ``missing``
    up to :data:`MISSING_LISTED`. A 48-frame render's ``job result`` was 8 KB of paths
    (review 20 N5). No ``hou``."""
    out: dict[str, Any] = {}
    if len(outputs) > INLINE_OUTPUTS:
        out["outputs_summary"] = outputs_summary(outputs, missing)
        out["outputs_sample"] = outputs[:OUTPUTS_SAMPLE_ENDS] + outputs[-OUTPUTS_SAMPLE_ENDS:]
    else:
        out["outputs"] = outputs
    if missing:
        out["missing"] = missing[:MISSING_LISTED]
    return out


def thumbnail_note(mean_luma: float | None, coverage: float | None) -> str | None:
    """The note on how a render thumbnail looks, from :func:`encode_png`'s ``measure``:
    a fully transparent image is empty; an opaque or mostly opaque one whose flattened
    mean is under :data:`DARK_MEAN` is nearly black. A sparse subject on a transparent
    background is neither (review 20 N1). No ``hou``."""
    if coverage is not None and coverage <= 0.0:
        return (
            "The thumbnail is empty (every pixel is transparent): check camera framing and "
            "which objects are displayed."
        )
    if mean_luma is not None and mean_luma < DARK_MEAN:
        return (
            f"The thumbnail is nearly black (mean luminance {mean_luma:.1f}/255): check "
            "lights, camera framing and exposure."
        )
    return None


def _render_result(plan: dict[str, Any], thumbnail: bool) -> dict[str, Any]:
    outputs = [p for p in plan["expected"] if os.path.isfile(p)]
    missing = [p for p in plan["expected"] if not os.path.isfile(p)]
    result: dict[str, Any] = {
        "rop_path": plan.get("owner") or plan["rop"],
        "frames": [frame_num(v) for v in plan["frames"]],
    }
    result.update(outputs_listing(outputs, missing))
    notes: list[str] = []
    if plan.get("owner"):
        notes.append(f"{plan['owner']} rendered through its ROP {plan['rop']}.")
    images = [
        p for p in plan["expected"] if os.path.splitext(p)[1].lower() in IMAGE_EXTS | CONVERT_EXTS
    ]
    if images and not plan.get("lights", True):
        notes.append(NO_LIGHTS_NOTE)
    if plan.get("note") and not outputs:
        notes.append(plan["note"])
    if notes:
        result["notes"] = notes
    if thumbnail and outputs:
        last = outputs[-1]
        ext = os.path.splitext(last)[1].lower()
        if ext not in IMAGE_EXTS | CONVERT_EXTS and plan.get("image_rop"):
            # Review 16 N4: say why there is no thumbnail.
            notes.append(
                f"No thumbnail: {ext or 'a file without an extension'} is not an image "
                "format the thumbnail reads (" + ", ".join(sorted(IMAGE_EXTS | CONVERT_EXTS)) + ")."
            )
            result["notes"] = notes
        elif ext in IMAGE_EXTS or ext in CONVERT_EXTS:
            try:
                image = encode_png(last, THUMB_MAX_SIDE, hfs=plan["hfs"], measure=True)
                look = thumbnail_note(image.pop("mean_luma", None), image.pop("coverage", None))
                if look:
                    notes.append(look)
                    result["notes"] = notes
                result["thumbnail"] = {
                    "path": last,
                    "width": image["width"],
                    "height": image["height"],
                    "image": image,
                }
            except Exception as exc:  # a thumbnail is a nicety; never fail the render
                reason = exc.message if isinstance(exc, ToolError) else f"{type(exc).__name__}"
                notes.append(
                    f"No thumbnail: {os.path.basename(last)} could not be read ({reason})."
                )
                result["notes"] = notes
    return result


LOG_TAIL_LINES = 20


def log_tail(paths: list[str], lines: int = LOG_TAIL_LINES) -> list[str]:
    """At most ``lines`` non-empty lines from the ends of the given log files, earlier
    files first (husk's stderr before its stdout). No ``hou``."""
    out: list[str] = []
    for path in paths:
        if len(out) >= lines:
            break
        if not path or not os.path.isfile(path):
            continue
        with contextlib.suppress(OSError):
            data = Path(path).read_bytes()[-20_000:].decode("utf-8", "replace")
            found = [line.rstrip() for line in data.splitlines() if line.strip()]
            out.extend(found[-(lines - len(out)) :])
    return out


def _render_job(plan: dict[str, Any], ctx: HostContext, thumbnail: bool) -> Any:
    import hou

    frame_list = plan["frame_list"]

    def run_isolated(job: Any) -> dict[str, Any]:
        tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
        try:
            snapshot = job.run_main(lambda: snapshot_scene(tmp_dir))
            parms = {plan["parm"]: plan["output"]} if plan["output"] is not None else {}
            child = ChildRender(
                snapshot,
                tmp_dir,
                plan["rop"],
                plan["frames"],
                parms,
                # An OpenGL ROP on a stage (review 16 N1); the Flipbook ROP keeps its threads.
                single_thread=plan.get("stage_source", False) and plan["core_type"] == "opengl",
            )
            child.start()

            def poll() -> None:
                done = sum(1 for p in plan["expected"] if os.path.isfile(p))
                if plan["expected"]:
                    total = len(plan["expected"])
                    job.set_progress(done, total, f"{done}/{total} frames done")

            job.progress(0.0, f"rendering {len(frame_list)} frame(s) in a child hython")
            try:
                outcome = child.wait(
                    timeout_s=FRAME_TIMEOUT_S, cancelled=lambda: job.cancelled, on_poll=poll
                )
            except ToolError as exc:
                if exc.code != "cancelled":
                    raise
                partial, done = _render_partial(plan)
                raise cancelled_with_partial(job, partial, done) from exc
            finally:
                child.kill()
            if outcome.get("errors"):
                message, detail = failure(f"{plan['rop']} failed to render", outcome["errors"])
                warnings = error_lines(outcome.get("warnings") or [])
                if warnings:
                    detail["warnings"] = warnings
                raise ToolError("cook_failed", message, detail=detail or None)
            job.progress(1.0, "done")
            result = _render_result(plan, thumbnail)
            if outcome.get("notes"):
                result["notes"] = [*outcome["notes"], *result.get("notes", [])]
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_in_process(job: Any) -> dict[str, Any]:
        saved: dict[str, tuple[Any, Any]] = {}
        notes: list[str] = []
        side_effects: dict[str, list[Any]] = {}
        logs: list[str] = []
        log_dir: list[str] = []

        def temporary_parms(node: Any) -> dict[str, Any]:
            """The output override and, on USD render ROPs, husk logs to read on failure."""
            parms: dict[str, Any] = {}
            if plan["output"] is not None:
                parms[plan["parm"]] = plan["output"]
            names = ("husk_log", "husk_stdout", "husk_stderr")
            if plan.get("usd") and all(node.parm(n) is not None for n in names):
                if node.parm("husk_log").eval():
                    logs.extend(node.parm(n).eval() for n in names[1:])
                else:
                    log_dir.append(tempfile.mkdtemp(prefix="hp-husk-"))
                    out, err = (_norm(os.path.join(log_dir[0], f)) for f in ("out.log", "err.log"))
                    parms.update(husk_log=1, husk_stdout=out, husk_stderr=err)
                    logs.extend((err, out))
            return parms

        def apply_override() -> None:
            from .events import muted

            node = hou.node(plan["rop"])
            with hou.undos.disabler(), muted():
                for name, value in temporary_parms(node).items():
                    parm = node.parm(name)
                    string = parm.parmTemplate().type() == hou.parmTemplateType.String
                    keys = parm.keyframes()
                    saved[name] = (parm.unexpandedString() if string else parm.eval(), keys)
                    if keys:
                        parm.deleteAllKeyframes()
                    parm.set(value)

        def restore() -> None:
            from .events import muted

            node = hou.node(plan["rop"])
            if node is None:
                return
            with hou.undos.disabler(), muted():
                for name, (raw, keys) in saved.items():
                    parm = node.parm(name)
                    parm.set(raw)
                    if keys:
                        parm.setKeyframes(keys)

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

        try:
            job.run_main(apply_override)
            total = len(frame_list)
            for i, frame in enumerate(frame_list):
                # The count is current, the frames finished (review 20 N7).
                job.set_progress(
                    i, total, f"{i}/{total} frames done, rendering frame {frame_num(frame)}"
                )
                try:
                    errors = job.run_main(
                        lambda f=frame: render_frame(f), timeout_s=FRAME_TIMEOUT_S
                    )
                except ToolError as exc:
                    if exc.code != "cancelled":
                        raise
                    partial, done = _render_partial(plan)
                    raise cancelled_with_partial(job, partial, done) from exc
                if errors:
                    message, detail = failure(
                        f"{plan['rop']} failed to render frame {frame_num(frame)}", errors
                    )
                    detail["frame"] = frame_num(frame)
                    hint = None
                    tail = log_tail(logs)
                    if tail:
                        detail["log_tail"] = tail
                        hint = "husk failed; detail.log_tail has the end of its log."
                    raise ToolError(
                        "cook_failed",
                        message,
                        hint=hint,
                        detail=detail,
                    )
            job.set_progress(total, total, "done")
            if plan.get("owner"):
                effects = job.run_main(lambda: _writer_side_effects(plan["owner"]))
                if effects:
                    side_effects.update(effects)
                    ctx.scene.mark_dirty()
        finally:
            if saved:
                # Never raises: a render error stays the error the caller sees.
                note = run_with_fallback(ctx.executor, restore, 60.0)
                if note:
                    names = ", ".join(saved)
                    notes.append(f"Restoring {plan['rop']} {names} failed: {note}.")
            for folder in log_dir:
                shutil.rmtree(folder, ignore_errors=True)
        result = _render_result(plan, thumbnail)
        if side_effects:
            result["side_effects"] = side_effects
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
        return result
    if job.state in ("failed", "cancelled") and job.error:
        raise ToolError.from_dict(job.error)
    status = job.status()
    status["hint"] = "Poll with job {action: 'status' | 'result', job_id}."
    return status
