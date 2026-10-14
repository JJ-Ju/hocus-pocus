"""The backend contract and the helpers every backend shares. No ``hou`` at import.

A :class:`Backend` makes one picture of a prepared request (:class:`~.spec.LookSpec`
after :func:`~.run.prepare`). :func:`~.select.plan` asks each backend's :meth:`can_run`
which ones may run for a request and orders them into a chain; :mod:`.run` calls
:meth:`Backend.render` along that chain until one writes the image.

**What a headless render sees (the snapshot contract, parity gap G8).** In a GUI session
every backend renders the live scene in-process. Headless, the Flipbook and OpenGL
backends (and ``render`` of a user's Flipbook or OpenGL ROP) render in a child hython,
because a second viewport render in one hython can crash it (BIBLE §8); the child gets a
*snapshot* (:func:`~.child.snapshot_scene`), which carries:

* every node under each manager (``/obj``, ``/stage``, ``/out``, ``/img``, ...), written
  with ``saveChildrenToFile``: parms, keys, expressions, flags, locked SOP data, and the
  contents of unlocked assets; no hip save, no event side effects;
* the asset libraries loaded from outside ``$HFS`` (the file names; the child installs
  them); ``Embedded`` definitions are not in that list, but the ``.cpio`` carries them
  and the child renders their instances (``tests/integration/test_parity_headless.py``);
* ``$HIP``, ``$HIPFILE``, ``$HIPNAME`` and ``$JOB``, the global hscript variables
  (``set -g``) and the ``hou.session`` source;
* the fps, the playbar range and the frame (the look's ``frame`` is rendered).

It does not carry the current take (a note says so; the child renders the root take),
in-memory simulation caches (the child re-cooks a DOP network up to the frame: slow, and
it can time out; a note names every DOP network standing past its start frame,
:func:`~.child.cached_simulations`), variables set with ``hou.putenv`` other than the
four above, or anything held only by a Python object in the host. Karma and
``rop_image`` always render in the host, on the live scene, headless too.

Observed while testing that (22.0.466): when a SOP network's display and render flags
are on different nodes, the child's Flipbook draws the render-flag node, where the GUI
viewport shows the display-flag one.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

TEMPORARY_CAMERA = "temporary"
"""``camera_used`` when the camera was built for one capture and deleted afterwards."""
INTERNAL_KEY = "hocuspocus:internal"
"""User data key marking HocusPocus's own temporary nodes."""
ROP_LABELS = {"flipbook": "Flipbook ROP", "opengl": "OpenGL ROP", "karma": "Karma"}
ROP_SOURCE_USED = {"flipbook": "flipbook_rop", "opengl": "opengl_rop", "karma": "karma"}
"""``viewport_capture``'s ``source_used`` for each ROP backend (1.4 names)."""


@dataclass(frozen=True)
class Env:
    """What a backend's :meth:`Backend.can_run` may consult: facts about this Houdini
    and scene, gathered on the main thread before the plan. Plain data, so the policy
    is testable without Houdini."""

    ui: bool = False
    """A GUI session (``houdinifx``), not hython."""
    rops: frozenset[str] = frozenset({"flipbook", "opengl"})
    """The viewport ROP types this Houdini has (22.0 has both)."""
    viewer: bool = False
    """A Scene Viewer pane is open (GUI only)."""
    lights: bool = False
    """The scene has a light object or LOP light."""


@dataclass
class LookResult:
    """What one backend run adds to the prepared request's ``info``: result keys
    (``scene``, ``camera_used``, ``fit_used``, ``context`` for the viewer) and notes."""

    info: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Backend:
    """One way of making the picture. Subclasses set :attr:`name` and implement both
    methods. :meth:`render` runs on the main thread in a GUI session and when the call
    itself is on it; headless it runs off the main thread, so a backend that needs
    ``hou`` goes through :func:`on_main` and one that waits on a child process does not
    hold the main thread. It writes ``spec.prepared.out_file`` or raises a
    :class:`ToolError`: ``cook_failed`` when the renderer produced no image, an
    ``internal`` error from :func:`~.child.exit_error` when its process crashed (the
    chain moves on to the next backend headless; see :func:`~.select.run_capture_chain`).
    """

    name: str = ""
    """The backend's name in ``backend_used`` and ``chain``."""

    def can_run(self, spec: Any, env: Env) -> tuple[bool, str]:
        """Whether this backend can render ``spec`` here, and why not. No ``hou``."""
        raise NotImplementedError

    def render(self, spec: Any, ctx: Any) -> LookResult:
        """Render the prepared request to ``spec.prepared.out_file``."""
        raise NotImplementedError


def on_main(ctx: Any, fn: Callable[[], Any], timeout_s: float) -> Any:
    """``fn()`` on Houdini's main thread: inline when already there, else through the
    executor."""
    if ctx.executor.on_main_thread():
        return fn()
    return ctx.executor.run(fn, timeout_s)


def mark_internal(node: Any) -> None:
    """Mark a temporary node so scans (cameras, COP networks) skip it."""
    with contextlib.suppress(Exception):
        node.setUserData(INTERNAL_KEY, "1")


def add_notes(info: dict[str, Any], *notes: Any) -> None:
    """Append the non-empty ``notes`` to ``info["notes"]`` (created only when needed)."""
    merged = [*info.get("notes", []), *(n for n in notes if n)]
    if merged:
        info["notes"] = merged


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


def check_capture_output(errors: list[str], out_file: str, rop_type: str = "flipbook") -> None:
    """Raise ``cook_failed`` when a viewport ROP reported errors or wrote no image."""
    if errors or not os.path.isfile(out_file):
        message, detail = failure(f"The {ROP_LABELS[rop_type]} did not produce an image", errors)
        raise ToolError(
            "cook_failed",
            message,
            hint=f"Check that the scene cooks ({hint_tool('problems')} lists errors) and "
            "that a GPU is available.",
            detail=detail or None,
        )


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
