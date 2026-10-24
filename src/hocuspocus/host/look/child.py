"""The scene snapshot and the child hython that renders it headless (BIBLE §8).

In hython 22.0.466 the second ``RopNode.render()`` of any OpenGL ROP in a process
segfaults inside the Vulkan viewport renderer (``GR_FillAttributesVK`` /
``RV_ShaderVariableSet``), whatever the node, frame, output or geometry; one multi-frame
``render()`` call is fine. The Flipbook ROP renders the same ROP again in-process (other
frames, cameras, resolutions, geometry), but once a Flipbook ROP that has rendered is
deleted (``destroy()`` or ``hip_new``), the next Flipbook render in that hython segfaults
at the same place (``RV_ShaderVariableSet::create``), and a capture's temporary ROP is
always deleted. So headless, the host snapshots the scene (:func:`snapshot_scene`; what it
carries is the contract in :mod:`.base`) and renders Flipbook and OpenGL ROPs in a child
``hython``: a fresh :class:`ChildRender` per call (about 3 s), or the kept child of
:mod:`.flipbook` for a Flipbook capture (about 0.3 s).

**An OpenGL child that renders a stage runs single-threaded** (``HOUDINI_MAXTHREADS=1``,
review 16 N1). Headless, the Vulkan device is created lazily by the first code that draws;
for a stage of more than a few thousand polygons the OpenGL ROP's LOP source updates the
meshes in parallel, so the device is created on a TBB worker while other workers wait on
it, and hython segfaults in the driver (``RV_Instance::initializeDevice`` under
``GR_PrimPacked::updateInstanceGeometry``; exit 139, also in a fresh hython that loads the
hip itself). One thread creates the device on the rendering thread. The Flipbook ROP does
not have this crash (review 16's city stage rendered multi-threaded in 5 of 5 fresh
hythons), so its children keep every thread.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools.budget import utf8_tail
from hocuspocus.tools.errors import ToolError

from ..tools.hip import _norm
from .base import INTERNAL_KEY

CHILD_TIMEOUT_S = 600.0
CRASH_LOG_CHARS = 600
"""An error carries at most this much of a crashed child's log (review 16 N1)."""
NOT_CARRIED_VARS = frozenset(
    {"HIP", "HIPFILE", "HIPNAME", "JOB", "ACTIVETAKE", "E", "PI", "EYE", "POSE", "status"}
)
"""Global hscript variables the child does not get from ``set -s``: the hip/job ones go
through the environment, the rest are Houdini's own."""
JOB_POLL_S = 0.1


def _hython() -> str:
    import hou

    hfs = os.environ.get("HFS") or hou.text.expandString("$HFS")
    exe = "hython.exe" if sys.platform == "win32" else "hython"
    return os.path.join(hfs, "bin", exe)


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


def isolate_target(hou, capture, created):
    # look at a SOP: its geometry alone (review 26 P1 #3). A temporary object merges it in
    # world space (an Object Merge reads a SOP anywhere: inside a subnet or a locked
    # asset, outside /obj) and the ROP draws only that object. Returns its path, or None.
    target = capture.get("isolate")
    if not target:
        return None
    obj = hou.node("/obj").createNode("geo")
    created.append(obj)
    obj.setName("hocuspocus_look_target", unique_name=True)
    for child in obj.children():
        child.destroy()
    merge = obj.createNode("object_merge", "target")
    merge.parm("objpath1").set(target["sop"])
    merge.parm("xformtype").set(1)  # into this object: the source object's transform
    merge.setDisplayFlag(True)
    merge.setRenderFlag(True)
    material = target.get("material")
    if material and obj.parm("shop_materialpath") is not None:
        obj.parm("shop_materialpath").set(material)
    return obj.path()


def show_only(rop, isolated):
    # The viewport ROP draws every object, or only the isolated one.
    parm = rop.parm("vobjects")
    if parm is not None:
        parm.set(isolated or "*")


def build_capture(hou, capture, created):
    # viewport_capture's camera and viewport ROP (rop_type: flipbook or opengl, the same
    # parms). Every node made is appended to created.
    isolated = isolate_target(hou, capture, created)
    rop = hou.node("/out").createNode(capture.get("rop_type") or "flipbook")
    created.append(rop)
    for name, value in capture["rop_parms"].items():
        rop.parm(name).set(value)
    show_only(rop, isolated)
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
def load_scene(hou, spec, notes):
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


def clear_scene(hou, keep):
    # A kept child's next scene: every node goes but its own capture ROPs. Never
    # hipFile.clear(): it deletes them, and a Flipbook ROP that rendered and was deleted
    # crashes the next Flipbook render in the process.
    for manager in hou.node("/").children():
        for node in manager.children():
            if node.path() not in keep:
                try:
                    node.destroy()
                except Exception:
                    pass


def reuse_capture(hou, capture, rop):
    # The kept ROP looks through the new capture's camera (built in the new scene).
    for name, value in capture["rop_parms"].items():
        rop.parm(name).set(value)
    show_only(rop, isolate_target(hou, capture, []))
    lop, camera = capture_camera(hou, capture, [])
    if lop is not None:
        rop.parm("opsource").set(1)
        rop.parm("loppath").set(lop)
        rop.parm("cameraprim").set(camera)
    else:
        rop.parm("opsource").set(0)
        rop.parm("camera").set(camera)
    return rop


def render(hou, spec, kept):
    notes = []
    if kept:
        clear_scene(hou, set(rop.path() for rop in kept.values()))
    load_scene(hou, spec, notes)
    capture = spec.get("capture")
    if capture:
        rop_type = capture.get("rop_type") or "flipbook"
        if rop_type in kept:
            rop = reuse_capture(hou, capture, kept[rop_type])
        else:
            rop = build_capture(hou, capture, [])
            if spec.get("serve"):
                rop.setName("hocuspocus_capture_" + rop_type, unique_name=True)
                kept[rop_type] = rop
        spec["rop"] = rop.path()
    rop = hou.node(spec["rop"])
    result = {"errors": [], "warnings": [], "notes": notes, "request": spec.get("request")}
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
    return result


def requests(idle_s):
    # Spec paths, one per stdin line, until EOF (the host went away) or idle_s without one.
    import queue, threading

    lines = queue.Queue()

    def read():
        for line in sys.stdin:
            lines.put(line.strip())
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            path = lines.get(timeout=idle_s)
        except queue.Empty:
            return
        if not path:
            return
        yield path


def emit(result):
    sys.stdout.write("HPRESULT " + json.dumps(result) + "\n")
    sys.stdout.flush()


def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        spec = json.load(fh)
    import hou
    kept = {}
    emit(render(hou, spec, kept))
    if not spec.get("serve"):
        return
    # A kept capture child (warm captures): render each further request in this process.
    for path in requests(spec.get("idle_s") or 120):
        with open(path, encoding="utf-8") as fh:
            emit(render(hou, json.load(fh), kept))

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
    with contextlib.suppress(Exception):
        note = simulation_cache_note(cached_simulations())
        if note:
            notes.append(note)
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


SIM_NOTE_CAP = 3


def cached_simulations() -> list[dict[str, Any]]:
    """``{path, frame, start}`` for every DOP network (an object or SOP ``dopnet``, also the
    ones inside solver SOPs) whose simulation stands past its start frame: it holds
    simulated frames in memory, which the snapshot cannot carry (docs/parity.md G8).
    Main thread."""
    import hou

    out = []
    for category in (hou.objNodeTypeCategory(), hou.sopNodeTypeCategory()):
        node_type = hou.nodeType(category, "dopnet")
        if node_type is None:
            continue
        for net in node_type.instances():
            with contextlib.suppress(Exception):
                if net.userData(INTERNAL_KEY):
                    continue
                start_parm = net.parm("startframe")
                start = float(start_parm.eval()) if start_parm is not None else 1.0
                frame = float(hou.timeToFrame(net.simulation().time()))
                if frame > start + 1e-6:
                    out.append({"path": net.path(), "frame": frame, "start": start})
    return out


def simulation_cache_note(sims: list[dict[str, Any]]) -> str | None:
    """The note for :func:`cached_simulations`, or None. No ``hou``."""
    if not sims:
        return None

    def num(value: float) -> str:
        return f"{value:g}"

    shown = ", ".join(
        f"{s['path']} (frames {num(s['start'])}-{num(s['frame'])})" for s in sims[:SIM_NOTE_CAP]
    )
    more = f" and {len(sims) - SIM_NOTE_CAP} more" if len(sims) > SIM_NOTE_CAP else ""
    return (
        f"The headless render gets a snapshot of the scene, not the simulation frames held in "
        f"memory by {shown}{more}: its child hython re-simulates them up to the frame "
        "(slow; it can time out). Cache the simulation to disk (a File Cache SOP) to look at "
        "it quickly, or look from a GUI session, which renders the live scene."
    )


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


def exit_error(code: int | None, log: str) -> ToolError:
    """The error for a render process that exited without a result: a crash, or a licence
    refusal (retry). No ``hou``."""
    licence = "licen" in log.lower()
    return ToolError(
        "internal",
        f"The render process exited with code {code}.",
        hint=(
            "No Houdini licence was available for the render process; retry shortly."
            if licence
            else "See detail.log for the render process output."
        ),
        hou_exception=f"render process exit {code}",
        detail={"log": crash_summary(log), "exit_code": code},
    )


def _child_env(single_thread: bool = False) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if single_thread:
        env["HOUDINI_MAXTHREADS"] = "1"
    return env


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
        with open(self.log_path, "wb") as log:
            self.proc = subprocess.Popen(
                [self.spec["hython"], script, spec_path],
                cwd=self.tmp_dir,
                env=_child_env(self.single_thread),
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
            raise exit_error(self.proc.returncode, log)
        outcome = json.loads(marker[len("HPRESULT ") :])
        notes = list(self.spec.get("notes") or []) + list(outcome.get("notes") or [])
        outcome["notes"] = notes
        return outcome

    def _log_tail(self, limit: int = 4000) -> str:
        try:
            data = Path(self.log_path).read_bytes()
        except OSError:
            return ""
        return utf8_tail(data[-limit:])


def child_crashed(exc: ToolError) -> bool:
    """Whether a child render failed by crashing (not a licence refusal, a timeout or a
    cancel), so another renderer may succeed where a viewport ROP did not."""
    return (
        exc.code == "internal"
        and str(exc.hou_exception or "").startswith("render process exit")
        and "licen" not in str(exc.hint or "").lower()
    )
