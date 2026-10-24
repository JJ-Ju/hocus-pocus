"""State tools: ``undo``, ``time`` and ``job``, and the selection helpers the ``edit``
``select`` op uses. See docs/BIBLE.md §4.7, §7.

All three register with ``scene=False`` so the dispatcher opens no undo group, does not
mark the scene dirty and does not apply the blanket read-only refusal; each tool decides
those itself, because the dispatcher's per-call treatment is wrong for them:

* ``undo`` must call ``hou.undos.performUndo()``, which Houdini refuses inside an open
  undo group ("Cannot undo within an undo group", verified on 22.0.466).
* ``time`` reads when called without arguments; an undo group, an
  undo-history entry and a dirty flag for a read would be noise. ``hou.setFrame``,
  ``hou.playbar.setFrameRange`` and ``hou.setFps`` are not undoable at all (a group around
  them records nothing).

Read-only mode refuses ``undo``/``redo`` and changes to the frame range or fps (saved
scene settings). Setting the current frame or the selection is view state and is allowed.

``job`` reads and cancels host-side jobs. It never touches ``hou``, so it skips the
main-thread executor.
"""

from __future__ import annotations

from typing import Any

from hocuspocus.tools.errors import ToolError

from ..undo import LABEL_PREFIX
from ._common import bad_arg, hou_exception_text, hou_message, number, refuse_if_read_only
from .registry import HostContext, tool
from .session import scene_dirty, time_block, viewport_note

HISTORY_LIMIT = 20


def _labels(fn: Any) -> list[str]:
    try:
        return [str(label) for label in fn()]
    except Exception:  # pragma: no cover - undo disabled or unavailable
        return []


# -- undo -------------------------------------------------------------------------------


UNDO_ACTIONS = ("undo", "redo", "history")


def _undo_state(ctx: HostContext) -> dict[str, Any]:
    import hou

    undo_labels = _labels(hou.undos.undoLabels)
    redo_labels = _labels(hou.undos.redoLabels)
    # Review 21 papercut 2: a call that failed and was rolled back is not redoable.
    skip = ctx.undo.rolled_back_in(redo_labels)
    redoable = [label for i, label in enumerate(redo_labels) if i not in skip]
    next_redo = redo_labels[0] if redo_labels and 0 not in skip else None
    return {
        "next_undo": undo_labels[0] if undo_labels else None,
        "next_redo": next_redo,
        "undo_count": len(undo_labels),
        "redo_count": len(redoable),
        "dirty": scene_dirty(ctx),
        "scene_generation": ctx.scene.generation,
    }


@tool("undo", scene=False)
def undo(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    action = args.get("action")
    if action not in UNDO_ACTIONS:
        raise bad_arg(f"action must be one of {', '.join(UNDO_ACTIONS)}; got {action!r}.")
    if action == "history":
        undo_labels = _labels(hou.undos.undoLabels)
        redo_labels = _labels(hou.undos.redoLabels)
        skip = ctx.undo.rolled_back_in(redo_labels)
        redoable = [label for i, label in enumerate(redo_labels) if i not in skip]
        out: dict[str, Any] = {
            "history": undo_labels[:HISTORY_LIMIT],
            "total": len(undo_labels),
            "redo": redoable[:HISTORY_LIMIT],
            "redo_total": len(redoable),
            "enabled": bool(hou.undos.areEnabled()),
            "note": f"Newest first, at most {HISTORY_LIMIT}; total and redo_total count them "
            f"all (review 22 finding 9). Labels starting with {LABEL_PREFIX.strip()!r} are "
            "HocusPocus calls; the rest are the user's or Houdini's own steps. hip_open and "
            "hip_new clear the history.",
        }
        if skip:
            out["rolled_back"] = [redo_labels[i] for i in sorted(skip)]
            out["note"] += (
                " rolled_back: calls that failed and were undone; Houdini keeps them on its "
                "redo stack, and redo stops before them."
            )
        return out
    steps = args.get("steps", 1)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise bad_arg(f"steps must be an integer >= 1; got {steps!r}.")
    include_user = args.get("include_user_steps", False)
    if not isinstance(include_user, bool):
        raise bad_arg("include_user_steps must be a boolean.")
    refuse_if_read_only(ctx, action.capitalize())
    labels_fn = hou.undos.undoLabels if action == "undo" else hou.undos.redoLabels
    perform = hou.undos.performUndo if action == "undo" else hou.undos.performRedo
    performed: list[str] = []
    user_steps: list[str] = []
    skipped: list[str] = []
    blocked_by: str | None = None
    for _ in range(steps):
        pending = _labels(labels_fn)
        if not pending:
            break
        if action == "redo" and 0 in ctx.undo.rolled_back_in(pending):
            # Review 21 papercut 2: this entry is a call that failed and was rolled back;
            # redoing it would re-apply what raised. It is the oldest redo entry (the
            # failed call's own changes had cleared the stack), so nothing lies past it.
            skipped.append(pending[0])
            break
        if not pending[0].startswith(LABEL_PREFIX):
            # Review 15 papercut 4: a step that is not HocusPocus's is the user's (or
            # Houdini's); crossing it needs consent.
            if not include_user:
                blocked_by = pending[0]
                break
            user_steps.append(pending[0])
        try:
            done = perform()
        except hou.Error as exc:
            raise ToolError(
                "internal",
                f"Houdini refused to {action} {pending[0]!r}: {hou_message(exc)}",
                hou_exception=hou_exception_text(exc),
                hint="Inspect the scene before retrying; detail lists the steps already done.",
                detail={"performed": performed},
            ) from exc
        if done is False:
            break
        performed.append(pending[0])
    if performed:
        ctx.scene.mark_dirty()
    result: dict[str, Any] = {"performed": performed}
    if user_steps:
        result["user_steps"] = user_steps
    if skipped:
        result["skipped"] = skipped
        result["note"] = (
            f"{len(performed)} of {steps} step(s) performed: {skipped[0]!r} is a call that "
            "failed and was rolled back, so it is not redone. Repeat the call itself (fixed) "
            "to apply it."
        )
    elif blocked_by is not None:
        result["blocked_by"] = blocked_by
        result["note"] = (
            f"{len(performed)} of {steps} step(s) performed: stopped before {blocked_by!r}, "
            f"which is not a HocusPocus step (the user's or Houdini's). Pass "
            f"include_user_steps: true to {action} it too."
        )
    elif len(performed) < steps:
        result["note"] = f"{len(performed)} of {steps} step(s) performed: nothing more to {action}."
    result.update(_undo_state(ctx))
    return result


# -- time -------------------------------------------------------------------------------


@tool("time", scene=False)
def time_(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    frame = args.get("frame")
    frame_range = args.get("range")
    fps = args.get("fps")
    if frame is not None:
        frame = number(frame, "frame")
    if fps is not None:
        fps = number(fps, "fps")
        if fps <= 0:
            raise bad_arg(f"'fps' must be greater than 0; got {fps:g}.")
    if frame_range is not None:
        if not isinstance(frame_range, list | tuple) or len(frame_range) != 2:
            raise bad_arg(
                f"'range' must be [start, end]; got {frame_range!r}.",
                hint="Pass two frame numbers, e.g. range: [1, 120].",
            )
        start, end = (number(v, "range") for v in frame_range)
        if end < start:
            raise bad_arg(
                f"'range' end ({end:g}) is before its start ({start:g}).",
                hint="Pass [start, end] with start <= end.",
            )
        frame_range = (start, end)
    changes_settings = fps is not None or frame_range is not None
    if changes_settings:
        refuse_if_read_only(ctx, "Changing the frame range or fps")
    # Order matters: setFps rescales the frame range, so fps first, then the range, then
    # the current frame.
    if fps is not None and fps != hou.fps():
        # modify_frame_count=False, preserve_frame_start=True: keep the range in frames
        # (Houdini's default keeps its duration in seconds and stretches the end frame).
        hou.setFps(fps, False, False, True)
    if frame_range is not None:
        hou.playbar.setFrameRange(*frame_range)
        hou.playbar.setPlaybackRange(*frame_range)
    if frame is not None:
        hou.setFrame(frame)
    if changes_settings:
        ctx.scene.mark_dirty()
    out = time_block()
    note = viewport_note(ctx, "time") if frame is not None else None
    if note:
        out["notes"] = [note]
    return out


# -- selection --------------------------------------------------------------------------


def _context_panes() -> list[Any]:
    """GUI: every Scene Viewer and Network Editor that is not pinned. Empty headless
    (there are no panes)."""
    import hou

    if not hou.isUIAvailable():
        return []
    kinds = (hou.paneTabType.SceneViewer, hou.paneTabType.NetworkEditor)
    out = []
    for tab in hou.ui.paneTabs():
        try:
            if tab.type() in kinds and not tab.isPin():
                out.append(tab)
        except Exception:  # a pane closing under us
            continue
    return out


def select_nodes(nodes: list[Any]) -> list[str]:
    """Select exactly ``nodes``; return the panes the selection takes into another
    network (``context_changed``, docs/parity.md G3). Main thread.

    In the GUI, selecting makes the last node current, and on the next idle tick every
    unpinned Scene Viewer and Network Editor follows it into its network (the next
    viewer ``look`` then shows that network with the rest
    ghosted). Putting a pane back is not possible without losing the selection: Houdini
    couples them, and ``setPwd`` selects a node of the pane's network instead (verified
    on 22.0.466, the Scene Viewer alone too). So the selection wins and the result names
    the panes that will move, as ``<pane name> (<network>)``. Headless: no panes."""
    import hou

    hou.clearAllSelected()
    for node in nodes:
        node.setSelected(True, clear_all_selected=False)
    if not nodes:
        return []
    try:
        target = nodes[-1].parent()
    except Exception:
        return []
    if target is None:
        return []
    moved: list[str] = []
    for tab in _context_panes():
        try:
            if tab.pwd().path() != target.path():
                moved.append(f"{tab.name()} ({target.path()})")
        except Exception:
            continue
    return moved


def context_changed_note() -> str:
    """Why the panes followed the selection, naming the viewer capture the call's profile
    serves."""
    from hocuspocus.tools.migration import hint_tool

    return (
        "Houdini takes the Scene Viewer and Network Editor listed in context_changed into "
        "the selection's network on its next idle tick (putting them back would change the "
        f"selection). {hint_tool('viewport_capture', source='viewer')} then shows that "
        "network; the default sources are not affected."
    )


# -- job --------------------------------------------------------------------------------


JOB_ACTIONS = ("status", "result", "cancel", "list")


@tool("job", main_thread=False, scene=False)
def job(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    action = args.get("action")
    if action not in JOB_ACTIONS:
        raise ToolError("invalid_argument", f"action must be one of {', '.join(JOB_ACTIONS)}.")
    if action == "list":
        return {"jobs": ctx.jobs.list()}
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ToolError("invalid_argument", f"job_id is required for action {action!r}.")
    if action == "status":
        return ctx.jobs.status(job_id)
    if action == "cancel":
        return ctx.jobs.cancel(job_id)
    data = ctx.jobs.result(job_id)
    if data["state"] in ("failed", "cancelled") and data.get("error"):
        raise ToolError.from_dict(data["error"])
    return data
