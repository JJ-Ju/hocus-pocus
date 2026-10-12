"""Helpers shared by the node, network, parm, state, hda, usd and events tools.

One implementation each (review 10 §4): argument parsing, Houdini exception text, node
lookup, offset paging with the response byte budget, and the read-only refusal. Node
lookup stays in ``_diag.require_node``; it is re-exported here so tool modules import
from one place.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from hocuspocus.tools.errors import ToolError, read_only_error

from ._diag import require_node

__all__ = [
    "ARG_HINT",
    "DEFAULT_LIMIT",
    "ROW_ENVELOPE_BYTES",
    "arg_bool",
    "arg_list",
    "bad_arg",
    "compact_size",
    "get_node",
    "hou_exception_text",
    "hou_message",
    "int_arg",
    "number",
    "page",
    "read_only_error",
    "refuse_if_read_only",
    "require_node",
    "response_budget",
]

ARG_HINT = "Check the argument against the tool's schema (docs/tools.md)."
DEFAULT_LIMIT = 50
DEFAULT_RESPONSE_BYTES = 16384
ROW_ENVELOPE_BYTES = 256
"""Room left in the budget for a paged result's non-row fields and the bridge's wrapping."""
CURSOR_HINT = "Pass next_cursor from the previous page unchanged, or omit cursor."


# -- errors -----------------------------------------------------------------------------


def bad_arg(message: str, **kw: Any) -> ToolError:
    """An ``invalid_argument`` error; every error carries a hint (docs/BIBLE.md §1.5)."""
    kw.setdefault("hint", ARG_HINT)
    return ToolError("invalid_argument", message, **kw)


def hou_message(exc: BaseException) -> str:
    """Houdini's own text for ``exc`` (``instanceMessage()``), on one line."""
    getter = getattr(exc, "instanceMessage", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            text = str(getter()).strip()
            if text:
                return " ".join(text.split())
    return str(exc).strip() or type(exc).__name__


def hou_exception_text(exc: BaseException) -> str:
    """``hou.OperationFailed: <message>``: the ``hou_exception`` field of an error."""
    module = type(exc).__module__
    prefix = "" if module in ("builtins", "__main__") else f"{module}."
    return f"{prefix}{type(exc).__name__}: {hou_message(exc)}"


def refuse_if_read_only(ctx: Any, what: str) -> None:
    """Raise the one ``read_only`` refusal when the host is in read-only mode."""
    if ctx.config.read_only:
        raise read_only_error(what)


# -- arguments --------------------------------------------------------------------------


def arg_bool(args: dict[str, Any], key: str, default: bool) -> bool:
    value = args.get(key, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise bad_arg(f"'{key}' must be a boolean.")
    return value


def arg_list(args: dict[str, Any], key: str, *, required: bool = True) -> list[Any]:
    value = args.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        raise bad_arg(f"'{key}' must be a non-empty array.")
    return value


def int_arg(
    args: dict[str, Any], key: str, default: int, low: int = 0, high: int | None = None
) -> int:
    """An integer argument in ``[low, high]``; ``default`` when absent or null."""
    value = args.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise bad_arg(f"'{key}' must be an integer >= {low}.")
    if high is not None and value > high:
        raise bad_arg(f"'{key}' must be at most {high}.")
    return value


def number(value: Any, field: str) -> float:
    """A JSON number (not a boolean) as float."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise bad_arg(f"'{field}' must be a number; got {value!r}.")
    return float(value)


# -- nodes ------------------------------------------------------------------------------


def get_node(path: Any, *, field: str = "path", relative_to: Any = None) -> Any:
    """``require_node`` (the one ``node_not_found`` with candidates), plus paths relative
    to ``relative_to`` (wiring sources name siblings)."""
    if not isinstance(path, str) or not path:
        raise bad_arg(f"'{field}' must be a non-empty node path.")
    if not path.startswith("/") and relative_to is not None:
        node = relative_to.node(path)
        if node is not None:
            return node
        path = f"{relative_to.path().rstrip('/')}/{path}"
    elif not path.startswith("/"):
        raise bad_arg(
            f"'{field}' must be an absolute node path like /obj/geo1; got {path!r}.",
            hint="Node paths start with '/'.",
        )
    return require_node(path, field=field)


# -- paging -----------------------------------------------------------------------------


def response_budget(ctx: Any) -> int:
    """The caller's byte budget for one result (BIBLE §4.1; default 16 KB)."""
    for value in (
        (getattr(ctx, "extras", None) or {}).get("max_response_bytes"),
        getattr(getattr(ctx, "config", None), "max_response_bytes", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return DEFAULT_RESPONSE_BYTES


def compact_size(value: Any) -> int:
    """Bytes of ``value`` as compact UTF-8 JSON (what the wire carries)."""
    return len(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    )


def parse_limit(limit: Any) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise bad_arg("'limit' must be an integer between 1 and 1000.")
    return limit


def parse_offset(cursor: Any) -> int:
    """An offset cursor (``"50"``); 0 when absent."""
    if cursor in (None, ""):
        return 0
    try:
        start = int(str(cursor))
    except ValueError:
        start = -1
    if start < 0:
        raise bad_arg(f"Invalid cursor {cursor!r}.", hint=CURSOR_HINT)
    return start


def page(
    rows: list[Any], limit: Any, cursor: Any, *, budget: int | None = None
) -> tuple[list[Any], str | None]:
    """One page of ``rows`` from an offset cursor: at most ``limit`` rows and, with
    ``budget``, at most that many bytes (at least one row). ``next_cursor`` is the offset
    of the first row not returned, so a budget cut never loses rows (BIBLE §4.1)."""
    size = parse_limit(limit)
    start = parse_offset(cursor)
    chunk = rows[start : start + size]
    if budget is not None:
        used = ROW_ENVELOPE_BYTES
        for kept, row in enumerate(chunk):
            used += compact_size(row) + 1
            if kept and used > budget:
                chunk = chunk[:kept]
                break
    end = start + len(chunk)
    return chunk, (str(end) if end < len(rows) else None)
