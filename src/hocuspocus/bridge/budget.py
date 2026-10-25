"""Response shaping: image extraction and the byte budget. See docs/BIBLE.md §3.3 rule 7, §4.1.

* Images: any ``{"image": {"png_base64": ...}}`` inside a result becomes MCP image content;
  the base64 is removed from the structured result (the rest of the image dict stays).
  Images are exempt from the byte cap.
* Budget: when the compact JSON of a result exceeds ``max_bytes``, list payloads are cut
  at item boundaries (largest first) and ``truncated: true`` is set. Details of what was
  cut go to ``_meta``.
* Paged results (a tool that takes ``cursor``, or ``since`` for ``events``) are never cut
  in a way that loses rows: the host pages by the budget itself (the bridge sends
  ``max_response_bytes``). If a page still overflows, its rows are cut only when the
  cursor can be rewritten to resume right after the last row kept (BIBLE §4.1). Which
  cursor a call has depends on the tool and its arguments (:func:`paged_mode`). Until 2.1
  the table was keyed by the 1.4 tool names (``node_find``, ``network_describe``), which
  no 2.x call carries, so only ``events`` was ever trimmed and the other pages came back
  whole with ``over_budget``:

  - a cursor naming the last row (:data:`ROW_CURSORS`): ``events`` and ``inspect what:
    events`` (``next_since``, ``<pid>:<seq>``, becomes the last kept event's seq, with
    ``more: true``; review 22 finding 1), ``search kind: nodes`` (the last kept row's
    ``path``, bare in the compact form and ``after:<path>`` with ``detail: full``: the
    form the host answered in), ``inspect what: outline`` (``after:<name>``, the row's
    ``name`` or its path's last segment) and ``inspect what: network`` (``after:<name>``;
    its ``data`` is a dict of rows keyed by node name, cut in key order);
  - an integer offset: ``next_cursor`` becomes ``offset + rows kept`` (``search kind:
    types`` writes it as ``t:<offset>``).

  Any other cursor (``problems``' scan cursor, a page whose rows cannot be named) leaves
  the page whole with ``over_budget: true``, and so does a call with no cursor to rewrite
  (``inspect`` of a node, parms or a type). A trimmed ``network`` or ``outline`` page has
  its ``node_count`` (and ``bytes``) recomputed for the rows kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..tools.budget import dumps, size, truncate

__all__ = ["Image", "apply_budget", "dumps", "extract_images", "paged_mode", "size"]

TRUNCATION_META_KEY = "hocuspocus/truncation"


@dataclass(frozen=True, slots=True)
class Image:
    data: str
    mime_type: str = "image/png"


def extract_images(result: Any) -> tuple[Any, list[Image]]:
    """Return ``(result_without_base64, images)``; the input is not modified."""
    images: list[Image] = []

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, value in node.items():
                if (
                    key == "image"
                    and isinstance(value, dict)
                    and isinstance(value.get("png_base64"), str)
                ):
                    images.append(
                        Image(value["png_base64"], str(value.get("mime_type") or "image/png"))
                    )
                    rest = {k: walk(v) for k, v in value.items() if k != "png_base64"}
                    rest["attached"] = True
                    out[key] = rest
                else:
                    out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(result), images


@dataclass(frozen=True, slots=True)
class RowCursor:
    """A cursor that names the last row of a page.

    ``rows_key`` is the result key of the rows: a list of dicts, or, when ``name_of`` is
    ``None``, a dict of rows whose keys name them. ``name_of(row)`` is what the cursor
    names for a row; ``cursor_key`` is the result key it is written to and ``prefix`` the
    text before the name. ``recount`` says the page carries ``node_count`` and ``bytes``
    for its rows."""

    cursor_key: str
    rows_key: str
    name_of: Callable[[dict[str, Any]], Any] | None
    prefix: str = ""
    recount: bool = False


@dataclass(frozen=True, slots=True)
class OffsetCursor:
    """An integer-offset cursor, written as ``prefix`` and the offset; ``rows_key`` names
    the rows (else the largest list is cut)."""

    prefix: str = ""
    rows_key: str | None = None


def _field(name: str) -> Callable[[dict[str, Any]], Any]:
    return lambda row: row.get(name)


def _outline_name(row: dict[str, Any]) -> Any:
    """An outline row's node name: ``name``, which the host's projection leaves out when it
    is the last segment of ``path``."""
    name = row.get("name")
    if name is None and isinstance(row.get("path"), str):
        name = row["path"].rsplit("/", 1)[-1]
    return name or None


EVENTS = RowCursor("next_since", "events", _field("seq"))
NODES = RowCursor("next_cursor", "nodes", _field("path"))
OUTLINE = RowCursor("next_cursor", "nodes", _outline_name, "after:", recount=True)
NETWORK = RowCursor("next_cursor", "data", None, "after:", recount=True)
TYPES = OffsetCursor("t:", "results")

Mode = tuple[str, str | None, str | None]

ROW_CURSORS: dict[Mode, RowCursor] = {
    ("events", None, None): EVENTS,
    ("inspect", "what", "events"): EVENTS,
    ("search", "kind", "nodes"): NODES,
    ("inspect", "what", "outline"): OUTLINE,
    ("inspect", "what", "network"): NETWORK,
}
"""Row cursors by ``(tool, argument, value)``: the tool, and, where one tool has several
modes, the argument that picks the mode and its value. A trimmed page's cursor is rebuilt
from the last row kept (:func:`paged_mode` looks a call up)."""

OFFSET_CURSORS: dict[Mode, OffsetCursor] = {
    ("search", "kind", "types"): TYPES,
}
"""Offset cursors that are prefixed or name their rows, by the same keys. Any other
cursor-taking call has a plain offset (``inspect what: geo`` with ``rows``, ``stage``, a
list read)."""

NO_CURSOR = frozenset({"node", "parms", "image", "type", "jobs", "guide", "tool"})
"""``inspect`` modes with nothing to resume from: ``inspect`` has a ``cursor`` argument for
the other modes, but these reads take none, so an oversized one is sent whole."""


def paged_mode(tool: str, args: dict[str, Any]) -> RowCursor | OffsetCursor | None:
    """The cursor style of a call to ``tool`` with ``args``; ``None`` when there is no
    cursor to resume from, so its page can only be sent whole."""
    for table in (ROW_CURSORS, OFFSET_CURSORS):
        for (name, arg, value), mode in table.items():
            if name == tool and (arg is None or args.get(arg) == value):
                return mode
    if tool == "search":
        return None  # a kind this version does not page
    if tool == "inspect":
        what = args.get("what")
        if what in NO_CURSOR or (what == "geo" and args.get("rows") is not True):
            return None
    return OffsetCursor()


def _offset(cursor: Any, prefix: str = "") -> int | None:
    if cursor in (None, ""):
        return 0
    if prefix:
        if not (isinstance(cursor, str) and cursor.startswith(prefix)):
            return None
        cursor = cursor[len(prefix) :]
    if isinstance(cursor, str) and cursor.isdigit():
        return int(cursor)
    if isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0:
        return cursor
    return None


def _whole(result: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The page unchanged, marked ``over_budget``: dropping rows would skip them for good."""
    work = dict(result)
    work["over_budget"] = True
    return work, [{"over_budget": True, "bytes": size(result), "max_bytes": max_bytes}]


def _leading_rows(
    result: dict[str, Any],
    key: str,
    max_bytes: int,
    cursor_for: Callable[[dict[str, Any], int], None],
) -> tuple[dict[str, Any], int]:
    """``(page, kept)``: the most leading rows of ``result[key]`` (a list, or a dict of
    rows in key order) that fit (at least one), with the page's cursor set by
    ``cursor_for(page, rows kept)``."""
    rows = result[key]
    items = list(rows.items()) if isinstance(rows, dict) else rows

    def head(n: int) -> Any:
        return dict(items[:n]) if isinstance(rows, dict) else items[:n]

    work = dict(result)
    work["truncated"] = True
    lo, hi, kept = 1, len(items), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        work[key] = head(mid)
        cursor_for(work, mid)
        if size(work) <= max_bytes:
            kept, lo = mid, mid + 1
        else:
            hi = mid - 1
    work[key] = head(kept)
    cursor_for(work, kept)
    return work, kept


def _finish(
    result: dict[str, Any],
    work: dict[str, Any],
    kept: int,
    key: str,
    cursor_key: str,
    max_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total = len(result[key])
    if kept >= total:
        return _whole(result, max_bytes)  # the rows are not what overflows; never drop them
    if size(work) > max_bytes:
        work["over_budget"] = True
    return work, [{"path": key, "kept": kept, "total": total, cursor_key: work[cursor_key]}]


def _count_nodes(rows: Any) -> int:
    """The nodes in ``rows`` (a list or a dict of rows) and in the ``children`` they list."""
    entries = list(rows.values()) if isinstance(rows, dict) else rows
    if not isinstance(entries, list):
        return 0
    return sum(1 + (_count_nodes(r.get("children")) if isinstance(r, dict) else 0) for r in entries)


def _row_names(rows: Any, spec: RowCursor) -> list[Any] | None:
    """What the cursor names for each row, in order; ``None`` when a row has no name, so
    a cut could not resume right after it."""
    if spec.name_of is None:
        if not isinstance(rows, dict) or not rows:
            return None
        names: list[Any] = list(rows)
        return names if all(isinstance(n, str) and n for n in names) else None
    if not isinstance(rows, list) or not rows:
        return None
    names = [spec.name_of(row) if isinstance(row, dict) else None for row in rows]
    return None if any(n is None for n in names) else names


def _apply_row_cursor(
    result: dict[str, Any], max_bytes: int, spec: RowCursor, args: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key, cursor_key = spec.rows_key, spec.cursor_key
    names = _row_names(result.get(key), spec)
    if names is None:
        return _whole(result, max_bytes)
    host_next = result.get(cursor_key)
    prefix = spec.prefix
    pid = ""
    if cursor_key == "next_since":
        # The bridge has already written it as <pid>:<seq> (tag_events); keep the pid.
        pid = str(host_next).rpartition(":")[0] if isinstance(host_next, str) else ""
    elif spec is NODES:
        # The compact page names the last path bare, ``detail: full`` as ``after:<path>``;
        # the host takes either, so answer in the form it used (else by ``detail``).
        if isinstance(host_next, str):
            prefix = "after:" if host_next.startswith("after:") else ""
        else:
            prefix = "after:" if args.get("detail") == "full" else ""

    def cursor_for(work: dict[str, Any], kept: int) -> None:
        name = names[kept - 1]
        if cursor_key == "next_since":
            work[cursor_key] = f"{pid}:{name}" if pid else name
            work["more"] = True
        else:
            work[cursor_key] = f"{prefix}{name}"
        if spec.recount:  # describe what the page now holds, not what the host built
            if "node_count" in work:
                work["node_count"] = _count_nodes(work[key])
            if "bytes" in work:
                work["bytes"] = size(work[key])

    work, kept = _leading_rows(result, key, max_bytes, cursor_for)
    return _finish(result, work, kept, key, cursor_key, max_bytes)


def _apply_offset(
    result: dict[str, Any], max_bytes: int, args: dict[str, Any], spec: OffsetCursor
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    start = result.get("start")
    offset = (
        start  # geo_read pages from `start` as well as from `cursor`
        if isinstance(start, int) and not isinstance(start, bool) and start >= 0
        else _offset(args.get("cursor"), spec.prefix)
    )
    host_next = result.get("next_cursor")
    if spec.rows_key is not None:
        rows = result.get(spec.rows_key)
        lists = [spec.rows_key] if isinstance(rows, list) and rows else []
    else:
        lists = [key for key, value in result.items() if isinstance(value, list) and value]
    if (
        offset is None
        or (host_next is not None and _offset(host_next, spec.prefix) is None)
        or not lists
    ):
        return _whole(result, max_bytes)  # an opaque cursor cannot be rewritten
    key = max(lists, key=lambda k: size(result[k]))
    base = offset

    def cursor_for(work: dict[str, Any], kept: int) -> None:
        work["next_cursor"] = f"{spec.prefix}{base + kept}"

    work, kept = _leading_rows(result, key, max_bytes, cursor_for)
    return _finish(result, work, kept, key, "next_cursor", max_bytes)


def _apply_paged(
    result: dict[str, Any], max_bytes: int, args: dict[str, Any], tool: str = ""
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    mode = paged_mode(tool, args)
    if mode is None:
        return _whole(result, max_bytes)
    if isinstance(mode, RowCursor):
        return _apply_row_cursor(result, max_bytes, mode, args)
    return _apply_offset(result, max_bytes, args, mode)


def apply_budget(
    result: dict[str, Any],
    max_bytes: int,
    args: dict[str, Any] | None = None,
    *,
    pageable: bool = False,
    tool: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fit ``result`` into ``max_bytes`` of compact JSON.

    ``pageable`` says the tool pages with ``cursor`` or ``since`` (``args`` are the call's
    arguments; ``tool`` and ``args`` together pick the cursor style, :func:`paged_mode`):
    its rows are then never dropped without a cursor that returns them. Returns
    ``(result, cuts)``; ``cuts`` is empty when nothing was removed. The input is not
    modified.
    """
    if max_bytes <= 0 or size(result) <= max_bytes:
        return result, []
    if pageable:
        return _apply_paged(result, max_bytes, args or {}, tool)
    return truncate(result, max_bytes)
