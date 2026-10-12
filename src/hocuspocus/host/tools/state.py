"""State tools: ``undo``, ``time``, ``selection`` and ``job``. See docs/BIBLE.md §4.7, §7.

All four register with ``scene=False`` so the dispatcher opens no undo group, does not
mark the scene dirty and does not apply the blanket read-only refusal; each tool decides
those itself, because the dispatcher's per-call treatment is wrong for them:

* ``undo`` must call ``hou.undos.performUndo()``, which Houdini refuses inside an open
  undo group ("Cannot undo within an undo group", verified on 22.0.466).
* ``time`` and ``selection`` read when called without arguments; an undo group, an
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

from hocuspocus.tools.errors import ToolError, read_only_error

from ..undo import LABEL_PREFIX, hou_undo_group, make_label
from .nodes import bad_arg, get_node
from .registry import HostContext, tool
from .session import scene_dirty

HISTORY_LIMIT = 20


def _refuse_if_read_only(ctx: HostContext, what: str) -> None:
    if ctx.config.read_only:
        raise read_only_error(what)


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
    return {
        "next_undo": undo_labels[0] if undo_labels else None,
        "next_redo": redo_labels[0] if redo_labels else None,
        "undo_count": len(undo_labels),
        "redo_count": len(redo_labels),
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
        return {
            "history": _labels(hou.undos.undoLabels)[:HISTORY_LIMIT],
            "redo": _labels(hou.undos.redoLabels)[:HISTORY_LIMIT],
            "enabled": bool(hou.undos.areEnabled()),
            "note": f"Newest first. Labels starting with {LABEL_PREFIX.strip()!r} are "
            "HocusPocus calls; the rest are the user's or Houdini's own steps.",
        }
    steps = args.get("steps", 1)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise bad_arg(f"steps must be an integer >= 1; got {steps!r}.")
    _refuse_if_read_only(ctx, action.capitalize())
    labels_fn = hou.undos.undoLabels if action == "undo" else hou.undos.redoLabels
    perform = hou.undos.performUndo if action == "undo" else hou.undos.performRedo
    performed: list[str] = []
    for _ in range(steps):
        pending = _labels(labels_fn)
        if not pending:
            break
        try:
            done = perform()
        except hou.Error as exc:
            text = exc.instanceMessage() if hasattr(exc, "instanceMessage") else str(exc)
            raise ToolError(
                "internal",
                f"Houdini refused to {action} {pending[0]!r}: {text}",
                hou_exception=f"hou.{type(exc).__name__}: {text}",
                hint="Inspect the scene before retrying; detail lists the steps already done.",
                detail={"performed": performed},
            ) from exc
        if done is False:
            break
        performed.append(pending[0])
    if performed:
        ctx.scene.mark_dirty()
    result: dict[str, Any] = {"performed": performed}
    if len(performed) < steps:
        result["note"] = f"{len(performed)} of {steps} step(s) performed: nothing more to {action}."
    result.update(_undo_state(ctx))
    return result


# -- time -------------------------------------------------------------------------------


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise bad_arg(f"'{field}' must be a number; got {value!r}.")
    return float(value)


def _num_out(value: float) -> float | int:
    value = float(value)
    return int(value) if value.is_integer() else round(value, 6)


def time_block() -> dict[str, Any]:
    import hou

    return {
        "frame": _num_out(hou.frame()),
        "fps": _num_out(hou.fps()),
        "range": [_num_out(v) for v in hou.playbar.frameRange()],
        "playback_range": [_num_out(v) for v in hou.playbar.playbackRange()],
    }


@tool("time", scene=False)
def time_(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    frame = args.get("frame")
    frame_range = args.get("range")
    fps = args.get("fps")
    if frame is not None:
        frame = _number(frame, "frame")
    if fps is not None:
        fps = _number(fps, "fps")
        if fps <= 0:
            raise bad_arg(f"'fps' must be greater than 0; got {fps:g}.")
    if frame_range is not None:
        if not isinstance(frame_range, list | tuple) or len(frame_range) != 2:
            raise bad_arg(
                f"'range' must be [start, end]; got {frame_range!r}.",
                hint="Pass two frame numbers, e.g. range: [1, 120].",
            )
        start, end = (_number(v, "range") for v in frame_range)
        if end < start:
            raise bad_arg(
                f"'range' end ({end:g}) is before its start ({start:g}).",
                hint="Pass [start, end] with start <= end.",
            )
        frame_range = (start, end)
    changes_settings = fps is not None or frame_range is not None
    if changes_settings:
        _refuse_if_read_only(ctx, "Changing the frame range or fps")
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
    return time_block()


# -- selection --------------------------------------------------------------------------


@tool("selection", scene=False)
def selection(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    paths = args.get("paths")
    if paths is None:
        return {"selected": [n.path() for n in hou.selectedNodes()]}
    if not isinstance(paths, list):
        raise bad_arg("'paths' must be a list of node paths (an empty list clears).")
    nodes: list[Any] = []
    for index, path in enumerate(paths):
        node = get_node(path, field=f"paths[{index}]")
        if node not in nodes:
            nodes.append(node)
    label = make_label("selection", {"paths": paths} if paths else {"undo_label": "clear"})
    # Houdini records each selection change as an undo entry; make the call one step.
    with hou_undo_group(label):
        hou.clearAllSelected()
        for node in nodes:
            node.setSelected(True, clear_all_selected=False)
    ctx.undo.record(label, "selection")
    return {"selected": [n.path() for n in hou.selectedNodes()]}


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
