"""The Flipbook backend: a temporary Flipbook ROP (``Driver/flipbook``, 1.4: Houdini 22
deprecates the OpenGL ROP for it), and the viewport ROP backend :mod:`.opengl` shares.

In a GUI session the camera and ROP are made in the live scene, rendered and deleted on
the main thread (a temporary Flipbook ROP created, rendered and deleted four times, then
again after ``hipFile.clear()``, did not crash in houdinifx 22.0.466; about 0.3 s).
Headless they exist only in a child hython's copy of the scene (:mod:`.child`), and a
Flipbook capture goes to the **kept capture child** (:class:`WarmCapture`, review 22
finding 6): a fresh child per capture cost 2.9-3.7 s, 69 % of a soak's tool time. Each
capture pushes a fresh snapshot; the child deletes its previous scene but never its own
Flipbook ROP, and re-renders that ROP (about 0.3 s). The policy, in
:func:`render_capture_child`: the first headless Flipbook capture starts the child; it is
replaced when the child script, the hython or an installed HDA library changes
(:func:`warm_key`), when it exited, after :data:`WARM_MAX_USES` captures or when it has
been idle nearly :data:`WARM_IDLE_S`; it exits by itself after :data:`WARM_IDLE_S` idle (it
holds a licence) or on stdin EOF (the host went away). A capture while it is busy and
every non-Flipbook capture use a fresh child. A crash of a kept child that had already
rendered retries that capture in a fresh child with :data:`WARM_CRASH_NOTE` and turns kept
children off for the rest of the process; a crash of a new kept child is a crash (the
chain moves on, :func:`~.select.run_capture_chain`). Set :data:`WARM_CAPTURES` to False
(inside the host) to send every capture to a fresh child.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..tools.session import scene_dirty
from . import child as child_mod
from .base import Backend, Env, LookResult, add_notes, check_capture_output, on_main
from .child import ChildRender, crash_summary, exit_error
from .framing import temporary_capture_nodes

WARM_CAPTURES = True
"""Headless Flipbook captures render in a kept child hython (:class:`WarmCapture`)."""
WARM_IDLE_S = 120.0
"""A kept capture child exits after this long without a capture (it holds a licence)."""
WARM_MAX_USES = 200
"""A kept capture child is replaced after this many captures."""
_warm: dict[str, Any] = {"child": None, "disabled": None}
"""``child``: the kept :class:`WarmCapture`; ``disabled``: why kept children are off in
this process (one crashed where a fresh child did not)."""
_warm_lock = threading.Lock()


def warm_key(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    """What a kept child cannot change between captures: the hython, the child script and
    the HDA libraries it installed (with their mtimes, so ``hda save`` restarts it). The
    scene itself is pushed with every capture. No ``hou``."""
    libs = []
    for lib in snapshot.get("hdas") or []:
        try:
            libs.append((lib, os.path.getmtime(lib)))
        except OSError:
            libs.append((lib, None))
    return (snapshot.get("hython"), child_mod._CHILD_SCRIPT, tuple(libs))


class WarmCapture:
    """A capture child hython kept between headless Flipbook captures (review 22 finding 6:
    a fresh child cost 2.9-3.7 s per capture, 69 % of a soak's tool time). Each capture
    sends a fresh scene snapshot; the child deletes its previous scene, keeping only its
    own Flipbook ROP, loads the snapshot and renders that ROP again: re-rendering one
    Flipbook ROP is safe in-process, deleting one that rendered is not (module docstring).
    It exits on stdin EOF (the host went away) or after :data:`WARM_IDLE_S` idle. Results
    are ``HPRESULT`` lines in its log, matched by request id. Off the main thread."""

    def __init__(self, key: tuple[Any, ...], hython: str) -> None:
        self.key = key
        self.hython = hython
        self.dir = tempfile.mkdtemp(prefix="hp-warm-")
        self.log_path = os.path.join(self.dir, "child.log")
        self.proc: subprocess.Popen[bytes] | None = None
        self.uses = 0
        self.last_used = time.monotonic()

    def usable(self, key: tuple[Any, ...]) -> bool:
        return (
            self.proc is not None
            and self.proc.poll() is None
            and self.key == key
            and self.uses < WARM_MAX_USES
            and time.monotonic() - self.last_used < WARM_IDLE_S - 10.0
        )

    def request(self, spec: dict[str, Any], tmp_dir: str, timeout_s: float) -> dict[str, Any]:
        """Render one capture spec and return its outcome, as :meth:`ChildRender.wait`."""
        request = f"{os.getpid()}-{self.uses}-{time.monotonic_ns()}"
        spec = dict(spec, serve=True, idle_s=WARM_IDLE_S, request=request)
        spec_path = os.path.join(tmp_dir, f"warm-{self.uses}.json")
        Path(spec_path).write_text(json.dumps(spec), encoding="utf-8")
        offset = 0
        if self.proc is None:
            script = os.path.join(self.dir, "render_child.py")
            Path(script).write_text(child_mod._CHILD_SCRIPT, encoding="utf-8")
            with open(self.log_path, "wb") as log:
                self.proc = subprocess.Popen(
                    [self.hython, script, spec_path],
                    cwd=self.dir,
                    env=child_mod._child_env(),
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        else:
            with contextlib.suppress(OSError):
                offset = os.path.getsize(self.log_path)
            assert self.proc.stdin is not None
            # It may have exited: then its exit code is reported below.
            with contextlib.suppress(OSError):
                self.proc.stdin.write((spec_path + "\n").encode("utf-8"))
                self.proc.stdin.flush()
        self.uses += 1
        try:
            outcome = self._wait(request, offset, timeout_s)
        finally:
            self.last_used = time.monotonic()
        outcome["notes"] = list(spec.get("notes") or []) + list(outcome.get("notes") or [])
        return outcome

    def _read(self, offset: int) -> str:
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(offset)
                return fh.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _wait(self, request: str, offset: int, timeout_s: float) -> dict[str, Any]:
        assert self.proc is not None
        deadline = time.monotonic() + timeout_s
        marker = f'"request": "{request}"'

        def result(log: str) -> dict[str, Any] | None:
            for line in log.splitlines():
                if line.startswith("HPRESULT ") and marker in line:
                    return json.loads(line[len("HPRESULT ") :])
            return None

        while True:
            exited = self.proc.poll() is not None
            log = self._read(offset)
            found = result(log)
            if found is not None:
                return found
            if exited:
                raise exit_error(self.proc.returncode, log[-200_000:])
            if time.monotonic() > deadline:
                self.close()
                raise ToolError(
                    "internal",
                    f"The render process did not finish within {timeout_s:g}s and was killed.",
                    hou_exception="render process timeout",
                    detail={"log": crash_summary(log[-4000:])},
                )
            time.sleep(0.02)

    def close(self) -> None:
        if self.proc is not None:
            with contextlib.suppress(Exception):
                if self.proc.stdin is not None:
                    self.proc.stdin.close()
            if self.proc.poll() is None:
                with contextlib.suppress(Exception):
                    self.proc.kill()
            with contextlib.suppress(Exception):
                self.proc.wait(10)
        shutil.rmtree(self.dir, ignore_errors=True)


def close_warm_capture() -> None:
    """Stop the kept capture child, if any (host exit, tests)."""
    with _warm_lock:
        child = _warm["child"]
        _warm["child"] = None
    if child is not None:
        child.close()


atexit.register(close_warm_capture)

WARM_CRASH_NOTE = (
    "The kept capture process crashed, so this capture used a fresh one; later captures "
    "in this Houdini start a fresh process each time."
)


def render_capture_child(
    snapshot: dict[str, Any], tmp_dir: str, frame: float, timeout_s: float
) -> dict[str, Any]:
    """Render one viewport_capture snapshot (``snapshot["capture"]``) in a child hython.
    A headless Flipbook capture goes to the kept :class:`WarmCapture`, started on first use
    and replaced when :func:`warm_key` changes or it died, idled or aged out. Anything else
    goes to a fresh :class:`ChildRender`: another ROP type, a capture while the kept child
    is busy, and every capture after a kept child that had already rendered crashed (that
    capture is retried once in a fresh child, with a note). A fresh kept child's crash is a
    crash, as before. Off the main thread."""
    frames = [frame, frame, 1]
    capture = snapshot.get("capture") or {}

    def cold() -> dict[str, Any]:
        child = ChildRender(snapshot, tmp_dir, "", frames)
        child.start()
        try:
            return child.wait(timeout_s=timeout_s)
        finally:
            child.kill()

    if (
        not WARM_CAPTURES
        or _warm["disabled"]
        or capture.get("rop_type", "flipbook") != "flipbook"
        or not _warm_lock.acquire(blocking=False)
    ):
        return cold()
    try:
        key = warm_key(snapshot)
        child = _warm["child"]
        if child is not None and not child.usable(key):
            child.close()
            child = _warm["child"] = None
        fresh = child is None
        if child is None:
            child = _warm["child"] = WarmCapture(key, snapshot["hython"])
        spec = dict(snapshot, rop="", frames=frames, parms={})
        try:
            return child.request(spec, tmp_dir, timeout_s)
        except ToolError as exc:
            child.close()
            _warm["child"] = None
            if fresh or not child_mod.child_crashed(exc):
                raise
            _warm["disabled"] = exc.message
        outcome = cold()
        outcome["notes"] = [*outcome.get("notes", []), WARM_CRASH_NOTE]
        return outcome
    finally:
        _warm_lock.release()


DIRTY_NOTE = (
    "Houdini marks the hip modified when the temporary capture camera and ROP are "
    "created, although both were deleted and nothing else changed."
)


class ViewportRopBackend(Backend):
    """A temporary viewport ROP (:attr:`name`) looking through the capture camera:
    in-process on the main thread in a GUI session, in a child hython headless (the kept
    child for the Flipbook ROP). Writes ``spec.prepared.out_file`` or raises
    ``cook_failed`` (no image) or a child crash (:func:`~.child.exit_error`)."""

    name = "flipbook"
    """Also the ROP type (``Driver/<name>``)."""

    def can_run(self, spec: Any, env: Env) -> tuple[bool, str]:
        if spec.kind == "cop":
            return False, "a Cop node renders through rop_image"
        if self.name not in env.rops:
            return False, f"this Houdini has no {self.name} ROP type"
        return True, ""

    def render(self, spec: Any, ctx: Any) -> LookResult:
        job = spec.prepared
        capture = dict(job.capture, rop_type=self.name)
        if not ctx.ui:
            # Headless: the child hython builds camera and ROP in its own copy of the scene.
            if job.snapshot is None:
                job.snapshot = on_main(
                    ctx, lambda: child_mod.snapshot_scene(job.tmp_dir), job.remaining()
                )
            snapshot = dict(job.snapshot, capture=capture)
            outcome = render_capture_child(snapshot, job.tmp_dir, job.frame, job.remaining())
            check_capture_output(outcome.get("errors") or [], job.out_file, self.name)
            return LookResult(notes=list(outcome.get("notes") or []))
        return on_main(ctx, lambda: self._in_process(capture, job, ctx), job.remaining())

    def _in_process(self, capture: dict[str, Any], job: Any, ctx: Any) -> LookResult:
        """GUI: create, render and delete the ROP on the main thread. Main thread."""
        import hou

        was_dirty = scene_dirty(ctx)
        errors: list[str] = []
        with temporary_capture_nodes(capture) as rop:
            try:
                rop.render(frame_range=(job.frame, job.frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
        if not was_dirty and scene_dirty(ctx):
            # Kept on the request, so it survives this ROP handing over to the next.
            add_notes(job.held, DIRTY_NOTE)
        check_capture_output(errors, job.out_file, self.name)
        return LookResult()


class FlipbookBackend(ViewportRopBackend):
    """The Flipbook ROP: the first viewport ROP of every chain."""

    name = "flipbook"


FLIPBOOK = FlipbookBackend()
