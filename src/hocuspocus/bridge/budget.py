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
  cursor can be rewritten to resume right after the last row kept (BIBLE §4.1):

  - a cursor naming the last row (:data:`ROW_CURSORS`): ``events``' ``next_since``
    (``<pid>:<seq>``) becomes the last kept event's seq, with ``more: true`` (review 22
    finding 1: the host's cursor skipped every trimmed event); ``node_find``'s
    ``after:<path>`` and ``network_describe``'s ``after:<name>`` name the last kept row;
  - an integer offset: ``next_cursor`` becomes ``offset + rows kept``.

  Any other cursor (``problems``' scan cursor, a page whose rows are not a list) leaves
  the page whole with ``over_budget: true``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..tools.budget import dumps, size, truncate

__all__ = ["Image", "apply_budget", "dumps", "extract_images", "size"]

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


ROW_CURSORS: dict[str, tuple[str, str, str, str]] = {
    "events": ("next_since", "events", "seq", ""),
    "node_find": ("next_cursor", "nodes", "path", "after:"),
    "network_describe": ("next_cursor", "nodes", "name", "after:"),
}
"""Tools whose cursor names the last row of a page, as ``tool: (cursor key, rows key, row
field, cursor prefix)``. A trimmed page's cursor is rebuilt from the last row kept."""


def _offset(cursor: Any) -> int | None:
    if cursor in (None, ""):
        return 0
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
    """``(page, kept)``: the most leading rows of ``result[key]`` that fit (at least one),
    with the page's cursor set by ``cursor_for(page, rows kept)``."""
    rows = result[key]
    work = dict(result)
    work["truncated"] = True
    lo, hi, kept = 1, len(rows), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        work[key] = rows[:mid]
        cursor_for(work, mid)
        if size(work) <= max_bytes:
            kept, lo = mid, mid + 1
        else:
            hi = mid - 1
    work[key] = rows[:kept]
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


def _apply_row_cursor(
    result: dict[str, Any], max_bytes: int, spec: tuple[str, str, str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cursor_key, rows_key, field, prefix = spec
    rows = result.get(rows_key)
    if (
        not isinstance(rows, list)
        or not rows
        or not all(isinstance(row, dict) and field in row for row in rows)
    ):
        return _whole(result, max_bytes)
    host_next = result.get(cursor_key)
    if cursor_key == "next_since":
        # The bridge has already written it as <pid>:<seq> (tag_events); keep the pid.
        pid = str(host_next).rpartition(":")[0] if isinstance(host_next, str) else ""

        def cursor_for(work: dict[str, Any], kept: int) -> None:
            seq = rows[kept - 1][field]
            work[cursor_key] = f"{pid}:{seq}" if pid else seq
            work["more"] = True

    else:

        def cursor_for(work: dict[str, Any], kept: int) -> None:
            work[cursor_key] = f"{prefix}{rows[kept - 1][field]}"

    work, kept = _leading_rows(result, rows_key, max_bytes, cursor_for)
    return _finish(result, work, kept, rows_key, cursor_key, max_bytes)


def _apply_paged(
    result: dict[str, Any], max_bytes: int, args: dict[str, Any], tool: str = ""
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec = ROW_CURSORS.get(tool)
    if spec is not None:
        return _apply_row_cursor(result, max_bytes, spec)
    start = result.get("start")
    offset = (
        start  # geo_read pages from `start` as well as from `cursor`
        if isinstance(start, int) and not isinstance(start, bool) and start >= 0
        else _offset(args.get("cursor"))
    )
    host_next = result.get("next_cursor")
    lists = [key for key, value in result.items() if isinstance(value, list) and value]
    if offset is None or (host_next is not None and _offset(host_next) is None) or not lists:
        return _whole(result, max_bytes)  # an opaque cursor cannot be rewritten
    key = max(lists, key=lambda k: size(result[k]))
    base = offset

    def cursor_for(work: dict[str, Any], kept: int) -> None:
        work["next_cursor"] = str(base + kept)

    work, kept = _leading_rows(result, key, max_bytes, cursor_for)
    return _finish(result, work, kept, key, "next_cursor", max_bytes)


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
    arguments, ``tool`` picks the cursor style from :data:`ROW_CURSORS`): its rows are then
    never dropped without a cursor that returns them. Returns ``(result, cuts)``; ``cuts``
    is empty when nothing was removed. The input is not modified.
    """
    if max_bytes <= 0 or size(result) <= max_bytes:
        return result, []
    if pageable:
        return _apply_paged(result, max_bytes, args or {}, tool)
    return truncate(result, max_bytes)
