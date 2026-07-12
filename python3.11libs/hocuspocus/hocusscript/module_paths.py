"""Shared lexical rules for portable HocusScript module paths."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _portable_segments(value: str) -> bool:
    return all(
        part == unicodedata.normalize("NFC", part)
        and not part.endswith((" ", "."))
        and not any(ord(character) < 32 or ord(character) == 127 for character in part)
        and part.split(".", 1)[0].casefold() not in _WINDOWS_RESERVED
        for part in value.split("/")
    )


def is_relative_hocus_path(value: Any) -> bool:
    """Return whether value is a normalized relative `.hocus` storage path."""
    return (
        isinstance(value, str) and bool(value) and len(value) <= 1024
        and value == value.strip() and value.endswith(".hocus")
        and not value.startswith(("/", "\\")) and "\\" not in value and ":" not in value
        and "?" not in value and "#" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and _portable_segments(value)
    )


def is_literal_import_specifier(value: Any) -> bool:
    """Return whether value is a canonical portable 0.2 import specifier.

    Percent escapes are deliberately excluded: import specifiers name decoded
    portable path segments, while canonical module URIs own percent encoding.
    """
    if (
        not isinstance(value, str) or not value or len(value) > 1024
        or value != value.strip() or not value.endswith(".hocus")
        or value.startswith(("/", "\\")) or "\\" in value or ":" in value
        or "?" in value or "#" in value or "//" in value or "%" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    if value.startswith("@"):
        alias, separator, tail = value[1:].partition("/")
        return bool(separator and ALIAS_PATTERN.fullmatch(alias) and is_relative_hocus_path(tail))
    parts = value.split("/")
    if value.startswith(("./", "../")):
        while parts and parts[0] in {".", ".."}:
            parts.pop(0)
        return bool(parts) and all(part not in {"", ".", ".."} for part in parts) and _portable_segments("/".join(parts))
    return all(part not in {"", ".", ".."} for part in parts) and _portable_segments(value)
