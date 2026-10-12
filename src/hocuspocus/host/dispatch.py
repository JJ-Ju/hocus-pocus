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

from hocuspocus.tools.errors import ToolError

from .tools.registry import HostContext, HostTool
from .undo import UndoGroupFactory, make_label

NOT_IMPLEMENTED_HINT = "not implemented in this host version"

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


def make_meta(ctx: HostContext, *, undo_label: str | None, started: float) -> dict[str, Any]:
    return {
        "scene_generation": ctx.scene.generation,
        "undo_label": undo_label,
        "elapsed_ms": int(round((time.perf_counter() - started) * 1000)),
    }


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
        self, tool: Any, args: Any, timeout_s: Any = None, max_response_bytes: Any = None
    ) -> dict[str, Any]:
        """Run ``tool``. ``max_response_bytes`` (from the request envelope; the config
        value when absent) is exposed to the tool as ``ctx.extras["max_response_bytes"]``
        so paged tools can cap rows to the client's budget."""
        started = time.perf_counter()
        undo_label: str | None = None
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
                impl, args, undo_label, self.response_budget(max_response_bytes), effective
            )
            result = self.ctx.executor.run(work, effective) if impl.main_thread else work()
            changed = _pop_changed(result)
            if read_only_dry_run and changed is not False:
                raise _read_only_error(tool)
            if changed is False:
                undo_label = None
            return ok_envelope(result, make_meta(self.ctx, undo_label=undo_label, started=started))
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            error = tool_error_from_exception(exc)
            if error.code == "internal":
                self.ctx.logger.error("tool %s failed: %s", tool, error.message, exc_info=exc)
            return error_envelope(
                error, make_meta(self.ctx, undo_label=undo_label, started=started)
            )

    def _work(
        self,
        impl: HostTool,
        args: dict[str, Any],
        undo_label: str | None,
        budget: int,
        timeout_s: float,
    ) -> Callable[[], Any]:
        ctx = self.ctx

        def run() -> Any:
            # Set here, not in call(): main-thread work runs one call at a time, so the
            # value cannot be overwritten by a concurrent request while the tool runs.
            ctx.extras["max_response_bytes"] = budget
            _CALL.timeout_s = timeout_s
            try:
                return run_tool()
            finally:
                _CALL.timeout_s = None

        def run_tool() -> Any:
            if undo_label is None:
                return impl.fn(args, ctx)
            clean_events = ctx.scene.clean_events
            with self.undo_group(undo_label):
                result = impl.fn(args, ctx)
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
