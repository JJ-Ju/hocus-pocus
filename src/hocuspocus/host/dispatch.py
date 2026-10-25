"""Tool dispatch and the ``hp/v1`` response envelope. See docs/BIBLE.md §3.4.

Pure logic: no ``hou`` import here. The undo-group factory and tool lookup are injected
so the dispatcher is unit-testable on plain CPython.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from typing import Any

from hocuspocus.tools import migration
from hocuspocus.tools.catalog import ToolSpec, in_profile, profile_of
from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.profiles import normalize

from . import modal
from .executor import MainThreadMeter, Pending, metering
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


AFTER_KEY = "_after"
"""A main-thread tool's result may carry ``"_after": fn``: once the main-thread work is
over (its undo group closed, the scene marked dirty), the dispatcher pops it and returns
``fn(result, remaining_s)``, called on the request's thread with the seconds left of the
call's timeout. ``edit`` cooks its nodes this way, as a job the call waits on for a while
(BIBLE D58): a long cook can then no longer make an applied edit's result time out. ``fn``
must not raise; the key is always stripped."""

AFTER_MARGIN_S = 2.0
"""Seconds of the call's timeout kept back from an ``_after`` step for the response."""


_CALL = threading.local()


def call_timeout(default: float | None = None) -> float | None:
    """The running call's effective timeout (``args.timeout_s``, else the request's
    ``timeout_s``, else the config default), for tools that wait on jobs off the main
    thread. Set on the thread that runs the tool; ``default`` outside a call."""
    value = getattr(_CALL, "timeout_s", None)
    return default if value is None else value


def current_tool() -> str | None:
    """The name of the tool the running call is answering, for hints that point at its
    reference (``inspect {what: "tool", target}``, 2.1); set on the thread that runs it."""
    return getattr(_CALL, "tool", None)


def current_request_id() -> str | None:
    """The running call's ``request_id`` from the ``/hp/v1/call`` envelope, if any. Jobs
    started during the call are filed under it, so the bridge can follow their progress
    while it waits for the response (``GET /hp/v1/calls/{request_id}/jobs``, BIBLE §7)."""
    return getattr(_CALL, "request_id", None)


def _off_main_thread(executor: Any) -> bool:
    on_main = getattr(executor, "on_main_thread", None)
    return bool(callable(on_main) and not on_main())


def after_allowed() -> bool:
    """Whether the running call may hand work to an :data:`AFTER_KEY` step that waits on
    main-thread jobs: true when the call came from another thread than Houdini's main
    one (an HTTP request), false for an inline call (a GUI shell, in-process tests) or
    outside a call."""
    return bool(getattr(_CALL, "after_ok", False))


def _pop_changed(result: Any) -> bool | None:
    if isinstance(result, dict) and CHANGED_KEY in result:
        return bool(result.pop(CHANGED_KEY))
    return None


def _run_after(after: Callable[..., Any], result: Any, remaining: float, ctx: Any) -> Any:
    """:data:`AFTER_KEY`'s step. Its failure never fails a call whose work is done: the
    result goes back as the main-thread work left it, with a note."""
    try:
        return after(result, remaining)
    except Exception as exc:
        ctx.logger.error("after-step failed: %s", exc, exc_info=exc)
        if isinstance(result, dict):
            result.setdefault("notes", []).append(
                f"The call's work is done, but its follow-up step failed: {exc}"
            )
        return result


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
    on Houdini's main thread, and ``queue_ms``, the wait for the main thread before that.
    A tool that runs off the main thread reports the sum of the main-thread steps run on
    its behalf, its jobs' steps finished within its wait included (review 24 N5), or
    ``0`` with ``off_main_thread: true`` when it ran none."""
    metered = timing.get("metered")
    if metered is not None:
        if not metered["steps"]:
            return {"main_thread_ms": 0, "off_main_thread": True}
        return {
            "main_thread_ms": round(metered["main_s"] * 1000, 1),
            "queue_ms": round(metered["queue_s"] * 1000, 1),
        }
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


def log_call(logger: Any, tool: Any, envelope: dict[str, Any]) -> None:
    """One INFO line per call in the host log (review 22 finding 4: a 616-call soak left
    137 B of log): ``call <tool> <elapsed> ms main <main_thread_ms> ms ok|<code> pid
    <pid>``; the formatter adds the timestamp. Never raises."""
    with contextlib.suppress(Exception):
        meta = envelope.get("_meta") or {}
        timing = meta.get("timing") or {}
        status = "ok" if envelope.get("ok") else (envelope.get("error") or {}).get("code")
        logger.info(
            "call %s %s ms main %s ms %s pid %d",
            tool if isinstance(tool, str) and tool else "?",
            meta.get("elapsed_ms"),
            timing.get("main_thread_ms", 0),
            status or "internal",
            os.getpid(),
        )


def hint_profile(host_profile: Any, client_profile: Any = None) -> str:
    """The profile a call's hints and messages name tools for (review 25 papercut 1): the
    bridge's, from the envelope, when it names one, else the host's own."""
    if isinstance(client_profile, str) and normalize(client_profile):
        return normalize(client_profile) or "core"
    return normalize(host_profile) or "core"


def profile_error(spec: ToolSpec, host_profile: str) -> ToolError | None:
    """Why a host on ``host_profile`` refuses ``spec``, or ``None`` when it runs it
    (spec-2.0 §2; BIBLE §3.2, §3.5): a tool outside the host's profile names the profile
    that lists it. (A removed 1.4 tool has no spec; :meth:`Dispatcher._call` answers it
    from :mod:`hocuspocus.tools.migration` before looking anything up.)"""
    effective = normalize(host_profile) or "core"
    if in_profile(spec, effective):
        return None
    needed = profile_of(spec)
    # full is the largest 2.0 profile; for the others "full" also lists the tool.
    wider = "" if needed == "full" else ' (or "full")'
    return ToolError(
        "invalid_argument",
        f"{spec.name} is a {needed}-profile tool, and this Houdini's host runs the "
        f"{effective} profile.",
        hint=f'Set profile = "{needed}"{wider} in hocuspocus.toml (host and bridge read it) '
        f"or HOCUSPOCUS_PROFILE={needed} in Houdini's environment, and restart Houdini.",
    )


def run_refusing_dialogs(impl: HostTool, args: dict[str, Any], ctx: HostContext) -> Any:
    """Run the tool, failing it with ``ui_required`` when it reached a modal ``hou.ui``
    stub (GUI only, docs/parity.md G5, :mod:`hocuspocus.host.modal`), also when the stub's
    exception was swallowed (a parm callback, a creation script) or turned into another
    error (``houdini_python``'s ``python_exception``). Raised here, inside the call's undo
    group, so the call rolls back. A call that loaded or cleared the scene (a hip load
    script) succeeds with a warning instead: the file is loaded."""
    with modal.collecting() as refused:
        generation = ctx.scene.generation
        try:
            result = impl.fn(args, ctx)
        except Exception as exc:
            if refused:
                raise modal.refused_error(impl.name, refused, exc, mutating=impl.mutating) from exc
            raise
        if not refused:
            return result
        if ctx.scene.generation != generation and isinstance(result, dict):
            warnings = result.get("warnings")
            if not isinstance(warnings, list):
                warnings = result["warnings"] = []
            warnings.append(modal.load_warning(refused))
            return result
        raise modal.refused_error(impl.name, refused, None, mutating=impl.mutating)


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

    def _adopt_after(self, effective: float) -> float | None:
        """How long a main-thread call waits before a long step it marked (a press,
        :func:`~hocuspocus.host.executor.mark_long_step`) goes on as a job:
        ``job_threshold_s`` within the call's timeout, as cook and render wait (BIBLE §7,
        D70). ``None`` where no job can follow it (no job manager, an executor without
        :meth:`run_adoptable`)."""
        executor = getattr(self.ctx, "executor", None)
        if getattr(self.ctx, "jobs", None) is None or not callable(
            getattr(executor, "run_adoptable", None)
        ):
            return None
        threshold = getattr(self.ctx.config, "job_threshold_s", None)
        if not isinstance(threshold, int | float) or isinstance(threshold, bool):
            return None
        return max(0.0, min(float(threshold), effective))

    def _follow(self, pending: Pending, tool: str, effective: float) -> dict[str, Any]:
        """Turn a call that is still in a long step past its wait into a job (BIBLE D70):
        the job waits for the main-thread work, runs what the dispatcher runs after it
        (:data:`AFTER_KEY`), and its result is the call's result, or its error the call's
        error. A press cannot be interrupted, so the job cannot be cancelled."""
        ctx = self.ctx
        step = pending.long_step or tool

        def follow(job: Any) -> Any:
            while not pending.wait(0.5):
                job.progress(None, f"{tool}: running {pending.long_step or step}")
            try:
                result = pending.outcome()
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt | SystemExit) and not isinstance(
                    exc, ToolError
                ):
                    raise
                raise tool_error_from_exception(exc) from exc
            after = result.pop(AFTER_KEY, None) if isinstance(result, dict) else None
            _pop_changed(result)
            if callable(after):
                result = _run_after(after, result, max(effective, AFTER_MARGIN_S), ctx)
            return result

        job = ctx.jobs.start(tool, follow, label=step, cancellable=False)
        pending.job_id = job.id
        job.message = job.message or f"{tool}: running {step}"
        waited = getattr(ctx.config, "job_threshold_s", effective)
        return {
            "job_id": job.id,
            "state": "running",
            "running": step,
            "message": (
                f"{step} is still running after {min(float(waited), effective):g} s and goes "
                "on as a job: job {action: result, job_id} returns this call's result when "
                "it ends. It runs on Houdini's main thread, so other calls that need it "
                "answer houdini_busy until then."
            ),
        }

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
        profile: Any = None,
    ) -> dict[str, Any]:
        """Run ``tool``. ``max_response_bytes`` (from the request envelope; the config
        value when absent) is exposed to the tool as ``ctx.extras["max_response_bytes"]``
        so paged tools can cap rows to the client's budget. ``request_id`` (also from the
        envelope) is what :func:`current_request_id` returns while the tool runs.
        ``profile`` (also from the envelope) is the bridge's: hints and messages name the
        tools it serves (:func:`hint_profile`); which tools run is the host's own profile
        (:func:`profile_error`). Every call writes one line to the host log
        (:func:`log_call`)."""
        envelope = self._call(tool, args, timeout_s, max_response_bytes, request_id, profile)
        log_call(self.ctx.logger, tool, envelope)
        return envelope

    def _call(
        self,
        tool: Any,
        args: Any,
        timeout_s: Any,
        max_response_bytes: Any,
        request_id: Any,
        profile: Any = None,
    ) -> dict[str, Any]:
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
            if migration.replacement(tool):
                # A 1.4 tool 2.1 removed (with compat_1x): name its replacement (BIBLE §3.2).
                raise migration.removed_error(
                    tool, hint_profile(getattr(self.ctx.config, "profile", "full"), profile)
                )
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
            if spec is not None:
                refused = profile_error(spec, getattr(self.ctx.config, "profile", "full"))
                if refused is not None:
                    raise refused
            # No whole tool is GUI-only (docs/parity.md G6): the GUI-only argument value
            # (look source: viewer) answers ui_required itself.
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
                hint_profile(getattr(self.ctx.config, "profile", "full"), profile),
                # An after-step can wait on main-thread jobs only off the main thread.
                after_ok=_off_main_thread(getattr(self.ctx, "executor", None)),
            )
            timing["main"] = impl.main_thread
            sent = time.perf_counter()
            if impl.main_thread:
                adopt_after = self._adopt_after(effective)
                try:
                    if adopt_after is None:
                        result = self.ctx.executor.run(work, effective)
                    else:
                        result = self.ctx.executor.run_adoptable(work, effective, adopt_after)
                finally:
                    timing["waited_s"] = time.perf_counter() - sent
                if isinstance(result, Pending):
                    timing.setdefault("work_s", timing["waited_s"])
                    return ok_envelope(
                        self._follow(result, impl.name, effective),
                        make_meta(self.ctx, undo_label=undo_label, started=started, timing=timing),
                    )
            else:
                meter = MainThreadMeter()
                try:
                    with metering(meter):
                        result = work()
                finally:
                    timing["metered"] = meter.close()
            after = result.pop(AFTER_KEY, None) if isinstance(result, dict) else None
            changed = _pop_changed(result)
            if read_only_dry_run and changed is not False:
                raise _read_only_error(tool)
            if callable(after):
                remaining = effective - (time.perf_counter() - started) - AFTER_MARGIN_S
                result = _run_after(after, result, max(0.0, remaining), self.ctx)
            if changed is False:
                undo_label = None
            return ok_envelope(
                result,
                make_meta(self.ctx, undo_label=undo_label, started=started, timing=timing),
            )
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit) and not isinstance(exc, ToolError):
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
        profile: str = "full",
        after_ok: bool = False,
    ) -> Callable[[], Any]:
        ctx = self.ctx

        def run() -> Any:
            # Set here, not in call(): main-thread work runs one call at a time, so the
            # value cannot be overwritten by a concurrent request while the tool runs.
            ctx.extras["max_response_bytes"] = budget
            _CALL.timeout_s = timeout_s
            _CALL.request_id = request_id
            _CALL.tool = impl.name
            _CALL.after_ok = after_ok
            began = time.perf_counter()
            try:
                with migration.using_profile(profile):
                    return run_tool()
            finally:
                _CALL.timeout_s = None
                _CALL.request_id = None
                _CALL.tool = None
                _CALL.after_ok = False
                if timing is not None:
                    timing["work_s"] = time.perf_counter() - began

        def run_tool() -> Any:
            if undo_label is None:
                return run_refusing_dialogs(impl, args, ctx)
            clean_events = ctx.scene.clean_events
            ctx.extras[ROLLED_BACK_KEY] = None
            outcome = None
            try:
                with self.undo_group(undo_label) as outcome:
                    result = run_refusing_dialogs(impl, args, ctx)
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
