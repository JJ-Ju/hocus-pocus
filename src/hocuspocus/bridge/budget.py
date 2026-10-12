"""Response shaping: image extraction and the byte budget. See docs/BIBLE.md §3.3 rule 7, §4.1.

* Images: any ``{"image": {"png_base64": ...}}`` inside a result becomes MCP image content;
  the base64 is removed from the structured result (the rest of the image dict stays).
  Images are exempt from the byte cap.
* Budget: when the compact JSON of a result exceeds ``max_bytes``, list payloads are cut
  at item boundaries (largest first) and ``truncated: true`` is set. Details of what was
  cut go to ``_meta``.
* Paged results (a tool that takes ``cursor``) are never cut in a way that loses rows: the
  host pages by the budget itself (the bridge sends ``max_response_bytes``). If a page
  still overflows, its largest list is cut only when the cursor is an integer offset, and
  ``next_cursor`` becomes ``offset + rows kept``; any other cursor leaves the page whole
  with ``over_budget: true`` (BIBLE §4.1).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

TRUNCATION_META_KEY = "hocuspocus/truncation"
STRING_KEEP_CHARS = 2_000


def dumps(obj: Any) -> str:
    """Compact JSON, the form used for the text block and for measuring."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


def size(obj: Any) -> int:
    return len(dumps(obj).encode("utf-8"))


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


@dataclass(slots=True)
class _Slot:
    """A truncatable list or string reachable from the root through dict keys / list indices."""

    parent: Any
    key: Any
    path: str
    kind: str  # "list" | "str"


def _collect(node: Any, path: str, out: list[_Slot]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, list):
                out.append(_Slot(node, key, child, "list"))
            elif isinstance(value, str) and len(value) > STRING_KEEP_CHARS:
                out.append(_Slot(node, key, child, "str"))
            _collect(value, child, out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            child = f"{path}[{i}]"
            if isinstance(value, list):
                out.append(_Slot(node, i, child, "list"))
            elif isinstance(value, str) and len(value) > STRING_KEEP_CHARS:
                out.append(_Slot(node, i, child, "str"))
            _collect(value, child, out)


def _offset(cursor: Any) -> int | None:
    if cursor in (None, ""):
        return 0
    if isinstance(cursor, str) and cursor.isdigit():
        return int(cursor)
    if isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0:
        return cursor
    return None


def _apply_paged(
    result: dict[str, Any], max_bytes: int, args: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    offset = _offset(args.get("cursor"))
    host_next = result.get("next_cursor")
    lists = [key for key, value in result.items() if isinstance(value, list) and value]
    if offset is None or (host_next is not None and _offset(host_next) is None) or not lists:
        # An opaque cursor cannot be rewritten: dropping rows would skip them for good.
        work = dict(result)
        work["over_budget"] = True
        return work, [{"over_budget": True, "bytes": size(result), "max_bytes": max_bytes}]
    key = max(lists, key=lambda k: size(result[k]))
    rows = result[key]
    work = dict(result)
    work["truncated"] = True
    lo, hi, kept = 1, len(rows), 1
    while lo <= hi:  # the most leading rows that fit, at least one
        mid = (lo + hi) // 2
        work[key] = rows[:mid]
        work["next_cursor"] = str(offset + mid)
        if size(work) <= max_bytes:
            kept, lo = mid, mid + 1
        else:
            hi = mid - 1
    if kept >= len(rows):
        work = dict(result)  # the rows are not what overflows; never drop them
        work["over_budget"] = True
        return work, [{"over_budget": True, "bytes": size(result), "max_bytes": max_bytes}]
    work[key] = rows[:kept]
    work["next_cursor"] = str(offset + kept)
    if size(work) > max_bytes:
        work["over_budget"] = True
    cut = {"path": key, "kept": kept, "total": len(rows), "next_cursor": work["next_cursor"]}
    return work, [cut]


def apply_budget(
    result: dict[str, Any],
    max_bytes: int,
    args: dict[str, Any] | None = None,
    *,
    pageable: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fit ``result`` into ``max_bytes`` of compact JSON.

    ``pageable`` says the tool takes ``cursor`` (``args`` are the call's arguments): its
    rows are then never dropped without a ``next_cursor`` that returns them. Returns
    ``(result, cuts)``; ``cuts`` is empty when nothing was removed. The input is not
    modified.
    """
    if max_bytes <= 0 or size(result) <= max_bytes:
        return result, []
    if pageable:
        return _apply_paged(result, max_bytes, args or {})
    work = copy.deepcopy(result)
    work["truncated"] = True
    cuts: list[dict[str, Any]] = []

    # Lists first (cut at item boundaries), then oversized strings, each largest-first.
    cut_strings: set[str] = set()
    for kind in ("list", "str"):
        while size(work) > max_bytes:
            slots = [
                s
                for s in _gather(work)
                if s.kind == kind and _cuttable(s) and s.path not in cut_strings
            ]
            if not slots:
                break
            slot = max(slots, key=lambda s: size(s.parent[s.key]))
            over = size(work) - max_bytes
            cuts.append(_cut(slot, over))
            if kind == "str":
                cut_strings.add(slot.path)
    return work, cuts


def _gather(root: dict[str, Any]) -> list[_Slot]:
    slots: list[_Slot] = []
    _collect(root, "", slots)
    return slots


def _cuttable(slot: _Slot) -> bool:
    value = slot.parent[slot.key]
    if slot.kind == "list":
        return len(value) > 0
    return len(value) > STRING_KEEP_CHARS // 4


def _cut(slot: _Slot, over: int) -> dict[str, Any]:
    value = slot.parent[slot.key]
    if slot.kind == "list":
        total = len(value)
        # Largest keep count whose removal frees at least `over` bytes (binary search).
        lo, hi = 0, total - 1
        current = size(value)
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            freed = current - size(value[:mid])
            if freed >= over:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        kept = best
        slot.parent[slot.key] = value[:kept]
        return {"path": slot.path, "kept": kept, "total": total}
    total_chars = len(value)
    keep = max(STRING_KEEP_CHARS // 4, total_chars - over - 64)
    slot.parent[slot.key] = value[:keep] + f"…[truncated {total_chars - keep} chars]"
    return {"path": slot.path, "kept_chars": keep, "total_chars": total_chars}
