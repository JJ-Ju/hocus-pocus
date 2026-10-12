"""``houdini_python``: the escape hatch. See docs/BIBLE.md §4.7, §9 and decision D7.

Python runs with ``exec`` in a fresh namespace with ``hou`` bound, on the main thread,
inside the dispatcher's undo group. ``stdout``/``stderr`` are captured; the value of a
trailing expression (or, when there is none or it is ``None``, a variable named
``result``) is returned JSON-serialised, with a ``repr`` fallback for anything JSON cannot
hold. ``language: hscript`` runs ``hou.hscript``. Output is capped at
``max_response_bytes``.

Failures (1.1 contract):

* An uncaught exception in the user's code (``SyntaxError``, ``SystemExit`` and
  ``KeyboardInterrupt`` included; none of them may take the host down) fails the call
  with ``python_exception``: ``message`` is ``"<type>: <text>"`` and ``detail`` carries
  ``stdout``, ``stderr`` and ``traceback``. Raising through the undo group rolls back the
  code's scene changes.
* A deadline: a ``sys.settrace`` hook raises :class:`PythonTimeout` inside the user's
  code shortly before the call's ``timeout_s``, so a ``while True:`` cannot wedge Houdini.
  It is reported as ``houdini_busy`` with ``detail.started: true`` and ``stopped: true``.
  C calls (``time.sleep``, a long cook) cannot be interrupted; the executor's own timeout
  still answers for those. Code that catches the timeout and keeps looping is not stopped
  again (CPython drops a trace hook that raised).
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import sys
import time
import traceback
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..budget import truncate
from ..dispatch import call_timeout
from .registry import HostContext, tool

FILENAME = "<houdini_python>"
DEADLINE_MARGIN_S = 1.0
"""How long before ``timeout_s`` the deadline fires (at most 10% of it), so the stopped
call can still roll back and answer before the executor gives up on it."""


class PythonTimeout(TimeoutError):
    """Raised inside the user's code once houdini_python's deadline has passed."""


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """JSON-compatible copy of ``value``; unknown objects become their ``repr``."""
    if _depth > 50:
        return repr(value)
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v, _depth + 1) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _compile(code: str) -> tuple[Any, Any]:
    """Split ``code`` into a body and an optional trailing expression."""
    tree = ast.parse(code, FILENAME, "exec")
    tail = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = tree.body.pop()
        tail = compile(ast.Expression(last.value), FILENAME, "eval")
    body = compile(tree, FILENAME, "exec")
    return body, tail


def _user_traceback(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    # Drop our own frames above the user's code.
    user = [f for f in frames if f.filename == FILENAME]
    lines = ["Traceback (most recent call last):\n"]
    lines += traceback.format_list(user or frames)
    lines += traceback.format_exception_only(type(exc), exc)
    return "".join(lines)


def deadline_for(timeout_s: float | None, started: float) -> float | None:
    """The monotonic time at which the user's code is stopped, or ``None`` for no limit."""
    if timeout_s is None or timeout_s <= 0:
        return None
    margin = min(DEADLINE_MARGIN_S, 0.1 * timeout_s)
    return started + timeout_s - margin


@contextlib.contextmanager
def _deadline(deadline: float | None, timeout_s: float | None) -> Any:
    """Install a trace hook that raises :class:`PythonTimeout` once ``deadline`` passes."""
    if deadline is None:
        yield
        return

    def check(frame: Any, event: str, arg: Any) -> Any:
        if time.monotonic() >= deadline:
            raise PythonTimeout(f"houdini_python was stopped after timeout_s={timeout_s:g}s")
        return check

    previous = sys.gettrace()
    sys.settrace(check)
    try:
        yield
    finally:
        sys.settrace(previous)


def _exception_name(exc: BaseException) -> str:
    module = type(exc).__module__
    return type(exc).__name__ if module == "builtins" else f"{module}.{type(exc).__name__}"


def run_python(
    code: str, *, timeout_s: float | None = None, hou_module: Any = None
) -> dict[str, Any]:
    """Run ``code``; returns ``{stdout, stderr, result, elapsed_s}`` plus ``exception``
    when it raised. ``timeout_s`` arms the deadline (:func:`deadline_for`);
    ``hou_module`` replaces ``hou`` (unit tests run without Houdini)."""
    if hou_module is None:
        import hou as hou_module

    started = time.monotonic()
    stdout, stderr = io.StringIO(), io.StringIO()
    namespace: dict[str, Any] = {
        "hou": hou_module,
        "__name__": "__houdini_python__",
        "__builtins__": __builtins__,
    }
    payload: dict[str, Any] = {"stdout": "", "stderr": "", "result": None}
    try:
        body, tail = _compile(code)
    except SyntaxError as exc:
        payload["exception"] = {
            "type": "SyntaxError",
            "message": str(exc),
            "traceback": "".join(traceback.format_exception_only(type(exc), exc)),
        }
        return payload
    value: Any = None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            with _deadline(deadline_for(timeout_s, started), timeout_s):
                exec(body, namespace)
                value = eval(tail, namespace) if tail is not None else None
            if value is None:
                value = namespace.get("result")
        # sys.exit() and a raised KeyboardInterrupt are caught too: they must never take
        # the host down.
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            message = str(exc)
            instance_message = getattr(exc, "instanceMessage", None)
            if callable(instance_message):
                with contextlib.suppress(Exception):
                    message = str(instance_message()) or message
            payload["exception"] = {
                "type": _exception_name(exc),
                "message": message,
                "traceback": _user_traceback(exc),
                "timeout": isinstance(exc, PythonTimeout),
            }
    payload["stdout"] = stdout.getvalue()
    payload["stderr"] = stderr.getvalue()
    payload["result"] = to_jsonable(value)
    payload["elapsed_s"] = round(time.monotonic() - started, 3)
    return payload


def exception_error(payload: dict[str, Any], timeout_s: float | None, budget: int) -> ToolError:
    """The ``python_exception`` (or, past the deadline, ``houdini_busy``) error."""
    exc = payload["exception"]
    detail = truncate(
        {
            "stdout": payload["stdout"],
            "stderr": payload["stderr"],
            "traceback": exc["traceback"],
            # The dispatcher replaces this with what the undo group really did.
            "rolled_back": True,
        },
        max(1024, budget - 1024),
    )
    detail.pop("truncated", None)
    if exc.get("timeout"):
        return ToolError(
            "houdini_busy",
            f"houdini_python ran past timeout_s ({timeout_s:g}s) and was stopped after "
            f"{payload.get('elapsed_s', 0):g}s; its scene changes were rolled back.",
            hint="The code did not finish: raise timeout_s for long work, make it finish "
            "sooner, or split it into several calls. Houdini is free again.",
            retryable=False,
            detail={**detail, "started": True, "stopped": True, "timeout_s": timeout_s},
        )
    message = f"{exc['type']}: {exc['message']}" if exc["message"] else exc["type"]
    if exc["type"] == "SystemExit":
        hint = (
            "Do not call exit() or sys.exit(): set a variable named result (or end with an "
            "expression) to return a value. The call's scene changes were rolled back."
        )
    else:
        hint = (
            "The code raised, so its scene changes were rolled back (the call is one undo "
            "step). Fix the code from detail.traceback and run it again; print() output is "
            "in detail.stdout."
        )
    return ToolError("python_exception", message, hint=hint, detail=detail)


def run_hscript(code: str) -> dict[str, Any]:
    import hou

    out, err = hou.hscript(code)
    return {"stdout": out, "stderr": err, "result": None}


@tool("houdini_python")
def houdini_python(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    if not ctx.config.allow_python:
        raise ToolError(
            "python_disabled",
            "houdini_python is disabled by configuration.",
            hint="Set allow_python = true in hocuspocus.toml (or HOCUSPOCUS_ALLOW_PYTHON=1) and restart the host.",
        )
    code = args.get("code")
    if not isinstance(code, str):
        raise ToolError("invalid_argument", "'code' must be a string.")
    language = args.get("language", "python")
    budget = int(ctx.extras.get("max_response_bytes") or ctx.config.max_response_bytes)
    if language == "python":
        timeout_s = call_timeout()
        payload = run_python(code, timeout_s=timeout_s)
        if "exception" in payload:
            raise exception_error(payload, timeout_s, budget)
        payload.pop("elapsed_s", None)
    elif language == "hscript":
        payload = run_hscript(code)
    else:
        raise ToolError("invalid_argument", "language must be 'python' or 'hscript'.")
    return truncate(payload, budget)
