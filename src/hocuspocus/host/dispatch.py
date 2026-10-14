"""Tool dispatch and the ``hp/v1`` response envelope. See docs/BIBLE.md §3.4.

Pure logic: no ``hou`` import here. The undo-group factory and tool lookup are injected
so the dispatcher is unit-testable on plain CPython.
"""

from __future__ import annotations

import contextlib
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from typing import Any

from hocuspocus.tools.catalog import in_profile, profile_of
from hocuspocus.tools.errors import ToolError

from .tools.registry import HostContext, HostTool
from .undo import UndoGroupFactory, make_label

NOT_IMPLEMENTED_HINT = "not implemented in this host version"

ROLLED_BACK_KEY = "rolled_back"
"""A mutating tool that raises a :class:`ToolError` whose ``detail`` has
``"rolled_back": None`` asks the dispatcher to fill in what its undo group really did
(review 10 section 1.7). The same value is left in ``ctx.extras["rolled_back"]`` after
every failed mutating call (None when no group was opened)."""

CHANGED_KEY = "_changed"
"""A tool result may carry ``"_changed": False`` to say the call changed nothing (for
example a ``dry_run``): the dispatcher then skips the undo-label record and dirty
marking, reports ``undo_label: null``, and allows the call in read-only mode when its
args had ``dry_run: true``. The key is always stripped from the result."""


_CALL = threading.local()


def call_timeout(default: float | None = None) -> float | None:
    """The running call's effective timeout (``args.timeout_s``, else the request's
    ``timeout_s``, else the config default), for tools that wait on jobs off the main
    thread. Set on the thread that runs the tool; ``default`` outside a call."""
    value = getattr(_CALL, "timeout_s", None)
    return default if value is None else value


def current_request_id() -> str | None:
    """The running call's ``request_id`` from the ``/hp/v1/call`` envelope, if any. Jobs
    started during the call are filed under it, so the bridge can follow their progress
    while it waits for the response (``GET /hp/v1/calls/{request_id}/jobs``, BIBLE §7)."""
    return getattr(_CALL, "request_id", None)


def _pop_changed(result: Any) -> bool | None:
    if isinstance(result, dict) and CHANGED_KEY in result:
        return bool(result.pop(CHANGED_KEY))
    return None


def _read_only_error(tool: str) -> ToolError:
    return ToolError(
        "read_only",
        f"{tool} changes the scene, and the host is in read-only mode.",
        hint="Set read_only = false in hocuspocus.toml (or HOCUSPOCUS_READ_ONLY=0) and restart the host.",
    )


def _report_rollback(error: ToolError, outcome: Any, ctx: HostContext) -> None:
    rolled_back = getattr(outcome, "rolled_back", None)
    ctx.extras[ROLLED_BACK_KEY] = rolled_back
    detail = error.detail
    if isinstance(detail, dict) and ROLLED_BACK_KEY in detail and detail[ROLLED_BACK_KEY] is None:
        detail[ROLLED_BACK_KEY] = rolled_back


def _note_rolled_back(outcome: Any, ctx: HostContext) -> None:
    """Tell the undo history that a rollback left this call on the redo stack, so
    ``undo {action: redo}`` will not re-apply it (review 21 papercut 2)."""
    redo_after = getattr(outcome, "redo_after", None)
    undo = getattr(ctx, "undo", None)
    if redo_after and undo is not None and hasattr(undo, "rolled_back"):
        undo.rolled_back(tuple(redo_after))


def make_meta(
    ctx: HostContext,
    *,
    undo_label: str | None,
    started: float,
    timing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "scene_generation": ctx.scene.generation,
        "undo_label": undo_label,
        "elapsed_ms": int(round((time.perf_counter() - started) * 1000)),
    }
    if timing is not None:
        meta["timing"] = timing_block(timing)
    return meta


def timing_block(timing: dict[str, Any]) -> dict[str, Any]:
    """``_meta.timing`` (review 22 finding 2): ``main_thread_ms``, the time the tool ran
    on Houdini's main thread (0 for tools that run off it), and ``queue_ms``, the wait
    for the main thread before that."""
    work = timing.get("work_s")
    out: dict[str, Any] = {
        "main_thread_ms": round(work * 1000, 1) if work is not None and timing.get("main") else 0
    }
    waited = timing.get("waited_s")
    if timing.get("main") and work is not None and waited is not None:
        out["queue_ms"] = round(max(0.0, waited - work) * 1000, 1)
    return out


def ok_envelope(result: Any, meta: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "result": result, "_meta": meta}


def error_envelope(error: ToolError, meta: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "error": error.to_dict(), "_meta": meta}


def _exception_message(exc: BaseException) -> str:
    instance_message = getattr(exc, "instanceMessage", None)
    if callable(instance_message):
        try:
            text = instance_message()
            if text:
                return str(text).strip()
        except Exception:
            pass
    return str(exc).strip() or type(exc).__name__


def tool_error_from_exception(exc: BaseException) -> ToolError:
    """Map any exception to a :class:`ToolError` (``internal`` unless it already is one)."""
    if isinstance(exc, ToolError):
        return exc
    message = _exception_message(exc)
    module = type(exc).__module__
    qualified = (
        type(exc).__name__
        if module in ("builtins", "__main__")
        else f"{module}.{type(exc).__name__}"
    )
    tb = getattr(exc, "hp_traceback", None) or "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return ToolError(
        "internal",
        f"{qualified}: {message}",
        hint="This is unexpected; the traceback is in detail. Inspect the scene before retrying a mutation.",
        hou_exception=f"{qualified}: {message}",
        detail={"traceback": tb},
    )


class Dispatcher:
    """Run one tool call and produce the ``hp/v1`` envelope."""

    def __init__(
        self,
        ctx: HostContext,
        lookup: Callable[[str], HostTool | None],
        *,
        undo_group: UndoGroupFactory | None = None,
        known_tool: Callable[[str], bool] | None = None,
    ) -> None:
        self.ctx = ctx
        self.lookup = lookup
        self.undo_group = undo_group or (lambda label: contextlib.nullcontext())
        self.known_tool = known_tool or (lambda name: False)

    def effective_timeout(self, args: Mapping[str, Any], timeout_s: Any) -> float:
        for candidate in (args.get("timeout_s") if isinstance(args, Mapping) else None, timeout_s):
            if (
                isinstance(candidate, int | float)
                and not isinstance(candidate, bool)
                and candidate > 0
            ):
                return float(candidate)
        return float(self.ctx.config.default_timeout_s)

    def response_budget(self, max_response_bytes: Any) -> int:
        if (
            isinstance(max_response_bytes, int)
            and not isinstance(max_response_bytes, bool)
            and max_response_bytes > 0
        ):
            return max_response_bytes
        return int(getattr(self.ctx.config, "max_response_bytes", 16384))

    def call(
        self,
        tool: Any,
        args: Any,
        timeout_s: Any = None,
        max_response_bytes: Any = None,
        request_id: Any = None,
    ) -> dict[str, Any]:
        """Run ``tool``. ``max_response_bytes`` (from the request envelope; the config
        value when absent) is exposed to the tool as ``ctx.extras["max_response_bytes"]``
        so paged tools can cap rows to the client's budget. ``request_id`` (also from the
        envelope) is what :func:`current_request_id` returns while the tool runs."""
        started = time.perf_counter()
        undo_label: str | None = None
        timing: dict[str, Any] = {}
        try:
            if not isinstance(tool, str) or not tool:
                raise ToolError(
                    "invalid_argument", "Request field 'tool' must be a non-empty string."
                )
            if args is None:
                args = {}
            if not isinstance(args, dict):
                raise ToolError("invalid_argument", "Request field 'args' must be an object.")
            impl = self.lookup(tool)
            if impl is None:
                if self.known_tool(tool):
                    raise ToolError(
                        "invalid_argument",
                        f"Tool {tool!r} is not available on this host.",
                        hint=NOT_IMPLEMENTED_HINT,
                    )
                raise ToolError(
                    "invalid_argument",
                    f"Unknown tool {tool!r}.",
                    hint=NOT_IMPLEMENTED_HINT,
                )
            spec = impl.spec
            host_profile = getattr(self.ctx.config, "profile", "full")
            if spec is not None and not in_profile(spec, host_profile):
                needed = profile_of(spec)
                raise ToolError(
                    "invalid_argument",
                    f"{tool} is a {needed}-profile tool, and this Houdini's host runs the "
                    f"{host_profile} profile.",
                    hint=f'Set profile = "{needed}" (or "full") in hocuspocus.toml (host and '
                    f"bridge read it) or HOCUSPOCUS_PROFILE={needed} in Houdini's environment, "
                    "and restart Houdini.",
                )
            if not impl.headless_ok and not self.ctx.ui:
                raise ToolError(
                    "ui_required",
                    f"{tool} needs a GUI Houdini session.",
                    hint="Connect to a GUI Houdini (houdini_connect), or use the headless alternative.",
                )
            mutating = impl.mutating
            # A dry run may proceed in read-only mode, without an undo group, provided the
            # tool then reports ``_changed: false`` (checked below).
            read_only_dry_run = (
                mutating and self.ctx.config.read_only and args.get("dry_run") is True
            )
            if mutating and self.ctx.config.read_only and not read_only_dry_run:
                raise _read_only_error(tool)
            if mutating and not read_only_dry_run:
                undo_label = make_label(tool, args)
            effective = self.effective_timeout(args, timeout_s)
            work = self._work(
                impl,
                args,
                undo_label,
                self.response_budget(max_response_bytes),
                effective,
                request_id if isinstance(request_id, str) and request_id else None,
                timing,
            )
            timing["main"] = impl.main_thread
            sent = time.perf_counter()
            try:
                result = self.ctx.executor.run(work, effective) if impl.main_thread else work()
            finally:
                timing["waited_s"] = time.perf_counter() - sent
            changed = _pop_changed(result)
            if read_only_dry_run and changed is not False:
                raise _read_only_error(tool)
            if changed is False:
                undo_label = None
            return ok_envelope(
                result,
                make_meta(self.ctx, undo_label=undo_label, started=started, timing=timing),
            )
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            error = tool_error_from_exception(exc)
            if error.code == "internal":
                self.ctx.logger.error("tool %s failed: %s", tool, error.message, exc_info=exc)
            return error_envelope(
                error, make_meta(self.ctx, undo_label=undo_label, started=started, timing=timing)
            )

    def _work(
        self,
        impl: HostTool,
        args: dict[str, Any],
        undo_label: str | None,
        budget: int,
        timeout_s: float,
        request_id: str | None = None,
        timing: dict[str, Any] | None = None,
    ) -> Callable[[], Any]:
        ctx = self.ctx

        def run() -> Any:
            # Set here, not in call(): main-thread work runs one call at a time, so the
            # value cannot be overwritten by a concurrent request while the tool runs.
            ctx.extras["max_response_bytes"] = budget
            _CALL.timeout_s = timeout_s
            _CALL.request_id = request_id
            began = time.perf_counter()
            try:
                return run_tool()
            finally:
                _CALL.timeout_s = None
                _CALL.request_id = None
                if timing is not None:
                    timing["work_s"] = time.perf_counter() - began

        def run_tool() -> Any:
            if undo_label is None:
                return impl.fn(args, ctx)
            clean_events = ctx.scene.clean_events
            ctx.extras[ROLLED_BACK_KEY] = None
            outcome = None
            try:
                with self.undo_group(undo_label) as outcome:
                    result = impl.fn(args, ctx)
            except ToolError as exc:
                _report_rollback(exc, outcome, ctx)
                _note_rolled_back(outcome, ctx)
                raise
            except Exception:
                _note_rolled_back(outcome, ctx)
                raise
            # A tool that says it changed nothing (a dry run) records no label and does
            # not dirty the scene.
            if not (isinstance(result, dict) and result.get(CHANGED_KEY) is False):
                ctx.undo.record(undo_label, impl.name)
                # A successful mutation dirties the scene unless it saved/loaded/cleared it.
                if ctx.scene.clean_events == clean_events:
                    ctx.scene.mark_dirty()
            if isinstance(result, dict) and "dirty" not in result:
                # Review 07 papercut 9: the agent sees the dirty flag without houdini_status.
                from .tools.session import scene_dirty

                result["dirty"] = scene_dirty(ctx)
            return result

        return run
