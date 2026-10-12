"""``houdini_python``: the escape hatch. See docs/BIBLE.md §4.7 and decision D7.

Python runs with ``exec`` in a fresh namespace with ``hou`` bound, on the main thread,
inside the dispatcher's undo group. ``stdout``/``stderr`` are captured; the value of a
trailing expression (or, when there is none or it is ``None``, a variable named
``result``) is returned JSON-serialised, with a ``repr`` fallback for anything JSON cannot
hold. An exception in the user's code (``SystemExit`` and ``KeyboardInterrupt``
included) is a successful call whose result carries ``exception`` and ``ok: false``. ``language: hscript`` runs
``hou.hscript``. Output is capped at ``max_response_bytes``.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import traceback
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..budget import truncate
from .registry import HostContext, tool

FILENAME = "<houdini_python>"


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


def run_python(code: str) -> dict[str, Any]:
    import hou

    stdout, stderr = io.StringIO(), io.StringIO()
    namespace: dict[str, Any] = {
        "hou": hou,
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
        payload["ok"] = False
        return payload
    value: Any = None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            exec(body, namespace)
            value = eval(tail, namespace) if tail is not None else None
            if value is None:
                value = namespace.get("result")
        # The user's exception is data, not a tool failure. sys.exit() and a raised
        # KeyboardInterrupt are caught too: they must never take the host down.
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            module = type(exc).__module__
            name = type(exc).__name__ if module == "builtins" else f"{module}.{type(exc).__name__}"
            message = str(exc)
            instance_message = getattr(exc, "instanceMessage", None)
            if callable(instance_message):
                with contextlib.suppress(Exception):
                    message = str(instance_message()) or message
            payload["exception"] = {
                "type": name,
                "message": message,
                "traceback": _user_traceback(exc),
            }
    payload["stdout"] = stdout.getvalue()
    payload["stderr"] = stderr.getvalue()
    payload["result"] = to_jsonable(value)
    if "exception" in payload:
        payload["ok"] = False
    return payload


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
    if language == "python":
        payload = run_python(code)
    elif language == "hscript":
        payload = run_hscript(code)
    else:
        raise ToolError("invalid_argument", "language must be 'python' or 'hscript'.")
    return truncate(payload, int(ctx.config.max_response_bytes))
