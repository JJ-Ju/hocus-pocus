"""The Karma backend: a temporary Karma CPU ROP rendered in the host (review 16 N1).

For a stage it is a ``karmarendersettings`` LOP and a ``usdrender_rop`` after the captured
LOP; for ``/obj`` a ``/out`` ``karma`` ROP. Karma has no second-render crash and husk is
its own process, so it renders in-process, GUI and headless alike, on the live scene (no
snapshot). Every node it makes is deleted afterwards, outside undo and events, and the
selection is put back. ``viewport_capture`` runs it only when the viewport ROP children
crashed (:data:`KARMA_SAMPLES` samples per pixel); ``look`` also runs it for ``quality:
lit`` without lights (:data:`LIT_SAMPLES`) and for ``quality: final`` (the target ROP's
samples, else :data:`FINAL_SAMPLES`).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import BARE, hint_tool

from ..tools.hip import _norm
from . import child
from .base import Backend, Env, LookResult, failure, log_tail, mark_internal, on_main

KARMA_SAMPLES = 2
"""Pixel samples of the Karma fallback: a quick look, not a final frame."""
LIT_SAMPLES = 2
"""``look quality: lit`` in a scene without lights: Karma at this many samples."""
FINAL_SAMPLES = 32
"""``look quality: final`` when the target is not a ROP with its own samples."""


def _karma_nodes(
    spec: dict[str, Any],
    res: tuple[int, int],
    out_file: str,
    logs: list[str],
    created: list[Any],
    samples: int = KARMA_SAMPLES,
) -> Any:
    """Build the temporary camera (when framed) and Karma ROP for one capture: for a stage
    a karmarendersettings LOP and a usdrender_rop LOP after the captured LOP, for /obj a
    /out karma ROP. Every node made is appended to ``created``. Returns the ROP. Main
    thread, outside undo."""
    import hou

    namespace: dict[str, Any] = {}
    exec(child._BUILD_CAPTURE, namespace)
    try:
        isolated = namespace["isolate_target"](hou, spec, created)  # a look at a SOP
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
                ("samplesperpixel", samples),
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
                "samplesperpixel": samples,
                # 22.0's Karma ROP renders at resolutionx/y (1280x720 by default) whatever
                # the camera or the override parms say (review 26 P1 #5: a 640x480 look came
                # back 1024x576); the override parms are kept for builds that read them.
                "resolutionx": res[0],
                "resolutiony": res[1],
                "override_camerares": 1,
                "res_fraction": "specific",
                "res_overridex": res[0],
                "res_overridey": res[1],
                "picture": out_file,
            }
            if isolated:
                values["candobjects"] = isolated
                values["objects"] = ""
        values["trange"] = 0
        for name, value in values.items():
            parm = rop.parm(name)
            if parm is not None:
                parm.set(value)
        return rop
    finally:
        for node in created:
            mark_internal(node)


def capture_with_karma(
    spec: dict[str, Any],
    frame: float,
    res: tuple[int, int],
    out_file: str,
    samples: int = KARMA_SAMPLES,
    *,
    label: str = "The Karma fallback",
) -> None:
    """Render one capture frame with a temporary Karma CPU ROP in the host (review 16 N1):
    the fallback when the viewport ROP children crashed, and ``look``'s lit and final
    renderer. Karma has no second-render crash, so its ROP renders in-process (husk is its
    own process). Deletes every node it made, outside undo and events, and puts the
    selection back. Raises ``cook_failed`` with the end of the
    husk log. Main thread."""
    import hou

    from ..tools.events import muted

    selected = hou.selectedNodes()
    log_dir = tempfile.mkdtemp(prefix="hp-husk-")
    logs = [_norm(os.path.join(log_dir, f)) for f in ("err.log", "out.log")]
    created: list[Any] = []
    errors: list[str] = []
    try:
        with hou.undos.disabler(), muted():
            rop = _karma_nodes(spec, res, out_file, logs, created, samples)
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
        message, detail = failure(f"{label} did not produce an image", errors)
        if tail:
            detail["log_tail"] = tail
        render = hint_tool("render", rop_path=BARE)
        raise ToolError(
            "cook_failed",
            message,
            hint=f"Check that the scene cooks ({hint_tool('problems')} lists errors)"
            + (f", or render a Karma ROP with {render}." if render else "."),
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


class KarmaBackend(Backend):
    """A temporary Karma CPU ROP in the host: ``look``'s lit (no lights) and final
    renderer, and the last step of the viewport ROP chain after a crash."""

    name = "karma"

    def can_run(self, spec: Any, env: Env) -> tuple[bool, str]:
        if spec.kind == "cop":
            return False, "a Cop node is an image already"
        return True, ""

    def render(self, spec: Any, ctx: Any) -> LookResult:
        job = spec.prepared
        if job.samples is None:  # the fallback after a crash: the 1.4 call, as it was
            on_main(
                ctx,
                lambda: capture_with_karma(job.capture, job.frame, job.res, job.out_file),
                job.remaining(),
            )
            return LookResult()
        on_main(
            ctx,
            lambda: capture_with_karma(
                job.capture, job.frame, job.res, job.out_file, job.samples, label="Karma"
            ),
            job.remaining(),
        )
        return LookResult(info={"samples": job.samples})


KARMA = KarmaBackend()
