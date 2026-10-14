"""The response byte budget, shared by host and bridge. Stdlib only. See docs/BIBLE.md §4.1.

:func:`truncate` fits a JSON-able payload into ``max_bytes`` of compact UTF-8 JSON: it
trims lists at item boundaries (largest first), then shortens the longest strings with a
marker saying how much was cut, and sets ``truncated: true`` on a top-level object. It
returns the trimmed copy and what it cut, so the bridge can report the cuts in ``_meta``.
The input is never modified. The host uses it for ``houdini_python`` output; the bridge
for results that are not paged (paged results never lose rows: ``bridge/budget.py``).
"""

from __future__ import annotations

import codecs
import json
from typing import Any

STRING_MARKER = "…[truncated {n} chars]"
MIN_STRING_CHARS = 64
"""Strings are never shortened below this many characters."""


def utf8_head(data: bytes) -> str:
    """``data``, a prefix of UTF-8 text cut at any byte, decoded without the partial
    character the cut left at its end (review 25 papercut 8: a ``read(n)`` of a help file
    ended in U+FFFD once decoded with ``replace``)."""
    # Not final: an incomplete last sequence is held back instead of decoded as U+FFFD.
    return codecs.getincrementaldecoder("utf-8")("replace").decode(data, final=False)


def utf8_tail(data: bytes) -> str:
    """``data``, a suffix of UTF-8 text cut at any byte (the end of a log), decoded without
    the partial character the cut left at its start."""
    start = 0
    while start < min(3, len(data)) and data[start] & 0xC0 == 0x80:
        start += 1
    return data[start:].decode("utf-8", "replace")


def clip(text: str, limit: int, mark: str = "…") -> str:
    """``text`` cut to at most ``limit`` characters, on a character boundary (never inside
    a surrogate pair), ending in ``mark`` when cut."""
    if len(text) <= limit:
        return text
    cut = max(0, limit - len(mark))
    if cut and 0xD800 <= ord(text[cut - 1]) <= 0xDBFF:
        cut -= 1
    return text[:cut].rstrip() + mark


def dumps(obj: Any) -> str:
    """Compact JSON, the form of the text block and of every size measurement."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


def size(obj: Any) -> int:
    return len(dumps(obj).encode("utf-8"))


def _slots(node: Any, path: str, kind: type, out: list[tuple[Any, Any, str]]) -> None:
    """``(parent, key, path)`` of every ``kind`` value below ``node``."""
    items = (
        node.items()
        if isinstance(node, dict)
        else enumerate(node)
        if isinstance(node, list)
        else ()
    )
    for key, value in items:
        child = (
            (f"{path}.{key}" if path else str(key)) if isinstance(node, dict) else f"{path}[{key}]"
        )
        if isinstance(value, kind):
            out.append((node, key, child))
        _slots(value, child, kind, out)


def _cut_list(data: Any, parent: Any, key: Any, max_bytes: int) -> int:
    """Keep the most leading items of ``parent[key]`` that let ``data`` fit (0..n-1)."""
    items = parent[key]
    lo, hi = 0, len(items) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        parent[key] = items[:mid]
        if size(data) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    parent[key] = items[:lo]
    return lo


def truncate(payload: Any, max_bytes: int) -> tuple[Any, list[dict[str, Any]]]:
    """Return ``(payload, [])`` when it fits, else ``(trimmed_copy, cuts)``.

    Each cut is ``{path, kept, total}`` for a list or ``{path, kept_chars, total_chars}``
    for a string; ``path`` uses dots and ``[i]`` (``attributes.point``, ``rows[3].text``).
    """
    if max_bytes <= 0 or size(payload) <= max_bytes:
        return payload, []
    data = json.loads(dumps(payload))  # a deep, JSON-only copy (unknown objects as str)
    if isinstance(data, dict):
        data["truncated"] = True
    cuts: list[dict[str, Any]] = []

    done: set[int] = set()
    while size(data) > max_bytes:  # lists, largest first, at item boundaries
        lists: list[tuple[Any, Any, str]] = []
        _slots(data, "", list, lists)
        lists = [s for s in lists if s[0][s[1]] and id(s[0][s[1]]) not in done]
        if not lists:
            break
        parent, key, path = max(lists, key=lambda s: size(s[0][s[1]]))
        total = len(parent[key])
        kept = _cut_list(data, parent, key, max_bytes)
        done.add(id(parent[key]))
        cuts.append({"path": path, "kept": kept, "total": total})

    shortened: set[str] = set()
    while size(data) > max_bytes:  # then the longest strings
        strings: list[tuple[Any, Any, str]] = []
        _slots(data, "", str, strings)
        strings = [
            s for s in strings if len(s[0][s[1]]) > MIN_STRING_CHARS and s[2] not in shortened
        ]
        if not strings:
            break
        parent, key, path = max(strings, key=lambda s: len(s[0][s[1]]))
        text: str = parent[key]
        total_chars = len(text)
        lo, hi = MIN_STRING_CHARS, total_chars - 1
        while lo < hi:  # the longest prefix (plus marker) that fits
            mid = (lo + hi + 1) // 2
            parent[key] = text[:mid] + STRING_MARKER.format(n=total_chars - mid)
            if size(data) <= max_bytes:
                lo = mid
            else:
                hi = mid - 1
        parent[key] = text[:lo] + STRING_MARKER.format(n=total_chars - lo)
        shortened.add(path)
        cuts.append({"path": path, "kept_chars": lo, "total_chars": total_chars})
    return data, cuts
