"""Response budgeting. Stdlib only. See docs/BIBLE.md §4.1 (default 16 KB).

:func:`truncate` shrinks a JSON-able payload to ``max_bytes`` of compact UTF-8 JSON by
trimming lists at item boundaries (largest list first), then shortening the longest
strings, and marks the result ``truncated: true``. The input is never modified.
"""

from __future__ import annotations

import json
from typing import Any

STRING_MARKER = "…[truncated {n} chars]"


def encoded_size(payload: Any) -> int:
    return len(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=repr).encode("utf-8")
    )


def _copy(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=repr))


def _walk(node: Any, kind: type, found: list[tuple[Any, Any]], parent: Any = None, key: Any = None):
    if isinstance(node, kind) and parent is not None:
        found.append((parent, key))
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, kind, found, node, k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, kind, found, node, i)


def truncate(payload: Any, max_bytes: int) -> Any:
    """Return ``payload`` unchanged if it fits, else a trimmed copy marked ``truncated``.

    ``truncated: true`` is set on the top-level object (when it is a dict). Lists keep
    their leading items; strings keep their prefix plus a marker saying how much was cut.
    """
    if encoded_size(payload) <= max_bytes:
        return payload
    data = _copy(payload)
    if isinstance(data, dict):
        data["truncated"] = True

    # Phase 1: trim lists, largest first, at item boundaries.
    exhausted: set[int] = set()
    while encoded_size(data) > max_bytes:
        lists: list[tuple[Any, Any]] = []
        _walk(data, list, lists)
        candidates = [
            (encoded_size(p[k]), p, k) for p, k in lists if p[k] and id(p[k]) not in exhausted
        ]
        if not candidates:
            break
        _, parent, key = max(candidates, key=lambda c: c[0])
        items = parent[key]
        lo, hi = 0, len(items) - 1  # keep count in [lo, hi]
        original = list(items)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            parent[key] = original[:mid]
            if encoded_size(data) <= max_bytes:
                lo = mid
            else:
                hi = mid - 1
        parent[key] = original[:lo]
        if not parent[key]:
            exhausted.add(id(parent[key]))
        elif encoded_size(data) <= max_bytes:
            break
        else:
            exhausted.add(id(parent[key]))

    # Phase 2: shorten the longest strings.
    while encoded_size(data) > max_bytes:
        strings: list[tuple[Any, Any]] = []
        _walk(data, str, strings)
        if not strings:
            break
        parent, key = max(strings, key=lambda pk: len(pk[0][pk[1]]))
        text: str = parent[key]
        excess = encoded_size(data) - max_bytes
        marker_len = len(STRING_MARKER.format(n=len(text))) + 4
        keep = len(text) - excess - marker_len
        if keep <= 0 and len(text) <= marker_len:
            break  # nothing meaningful left to cut
        keep = max(0, keep)
        # Multi-byte characters may make the first cut insufficient; the loop repeats.
        parent[key] = text[:keep] + STRING_MARKER.format(n=len(text) - keep)
    return data
