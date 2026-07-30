"""Strict, bounded single-file unified patches for HocusScript workspaces."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

MAX_PATCH_BYTES = 2 * 1024 * 1024
MAX_PATCH_OPERATIONS = 256
_HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>0|[1-9][0-9]*)(?:,(?P<old_count>0|[1-9][0-9]*))? "
    r"\+(?P<new_start>0|[1-9][0-9]*)(?:,(?P<new_count>0|[1-9][0-9]*))? @@$"
)
_NO_NEWLINE = r"\ No newline at end of file"


class WorkspacePatchError(ValueError):
    """Typed failure raised by the workspace patch engine."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code = "HOCUS827"
        self.message = message
        self.details: dict[str, object] = {}


@dataclass(frozen=True, slots=True)
class _TextLine:
    text: str
    terminated: bool


@dataclass(frozen=True, slots=True)
class _PatchLine:
    kind: str
    text: str
    old_terminated: bool = True
    new_terminated: bool = True


@dataclass(frozen=True, slots=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[_PatchLine, ...]


@dataclass(frozen=True, slots=True)
class PatchResult:
    """Raw patch result, suitable for guarded workspace publication."""

    content: bytes
    raw_digest: str
    byte_length: int
    newline_style: str
    hunks_applied: int


def apply_unified_patch(
    original: bytes | None,
    patch: str | bytes,
    relative_path: str,
    *,
    max_operations: int = MAX_PATCH_OPERATIONS,
) -> PatchResult:
    """Apply one exact-path unified diff without fuzzy matching or renames."""

    if not isinstance(relative_path, str) or not relative_path:
        raise WorkspacePatchError("Patch target is malformed.")
    if not isinstance(max_operations, int) or not 1 <= max_operations <= MAX_PATCH_OPERATIONS:
        raise WorkspacePatchError("Patch operation bound is malformed.")
    patch_raw = patch.encode("utf-8") if isinstance(patch, str) else patch
    if not isinstance(patch_raw, bytes) or len(patch_raw) > MAX_PATCH_BYTES:
        raise WorkspacePatchError("Patch exceeds the bounded input size.")
    patch_text, patch_newline = _decode_text(patch_raw, "Patch")
    source_text, source_newline = _decode_text(original or b"", "Patch source")
    source_lines = _logical_lines(source_text)
    patch_lines = _logical_lines(patch_text)
    hunks = _parse_patch(
        patch_lines,
        relative_path,
        creating=original is None,
        max_operations=max_operations,
    )
    output_lines = _apply_hunks(source_lines, hunks)
    newline = source_newline if source_newline != "none" else patch_newline
    if newline == "none":
        newline = "lf"
    content = _encode_lines(output_lines, newline)
    return PatchResult(
        content=content,
        raw_digest=_raw_digest(content),
        byte_length=len(content),
        newline_style=_newline_style(content),
        hunks_applied=len(hunks),
    )


def _decode_text(raw: bytes, label: str) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise WorkspacePatchError(f"{label} cannot contain a UTF-8 byte-order mark.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspacePatchError(f"{label} must be strict UTF-8.") from exc
    if "\x00" in text:
        raise WorkspacePatchError(f"{label} cannot contain NUL characters.")
    return text, _newline_style(raw)


def _newline_style(raw: bytes) -> str:
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\r" in without_crlf:
        raise WorkspacePatchError("Text contains an unsupported lone carriage return.")
    has_crlf = b"\r\n" in raw
    has_lf = b"\n" in without_crlf
    if has_crlf and has_lf:
        raise WorkspacePatchError("Text cannot mix LF and CRLF newlines.")
    if has_crlf:
        return "crlf"
    if has_lf:
        return "lf"
    return "none"


def _logical_lines(text: str) -> list[_TextLine]:
    if not text:
        return []
    output: list[_TextLine] = []
    for row in text.splitlines(keepends=True):
        terminated = row.endswith("\n")
        body = row[:-1] if terminated else row
        if body.endswith("\r"):
            body = body[:-1]
        output.append(_TextLine(body, terminated))
    return output


def _parse_patch(
    rows: list[_TextLine],
    relative_path: str,
    *,
    creating: bool,
    max_operations: int,
) -> tuple[_Hunk, ...]:
    if len(rows) < 3 or not rows[0].text.startswith("--- ") or not rows[1].text.startswith("+++ "):
        raise WorkspacePatchError("Patch must begin with exact old and new file headers.")
    _validate_headers(rows[0].text[4:], rows[1].text[4:], relative_path, creating)
    hunks: list[_Hunk] = []
    index = 2
    operations = 0
    while index < len(rows):
        header = _parse_hunk_header(rows[index].text)
        lines, index = _parse_hunk_lines(rows, index + 1)
        operations += len(lines)
        if operations > max_operations:
            raise WorkspacePatchError("Patch exceeds the operation limit.")
        hunk = _Hunk(*header, tuple(lines))
        _validate_hunk_counts(hunk)
        hunks.append(hunk)
    if not hunks:
        raise WorkspacePatchError("Patch must contain at least one hunk.")
    return tuple(hunks)


def _validate_headers(old_path: str, new_path: str, target: str, creating: bool) -> None:
    expected = f"a/{target}"
    if new_path != f"b/{target}":
        raise WorkspacePatchError("Patch new-file header does not match the exact target.")
    if creating:
        if old_path != "/dev/null":
            raise WorkspacePatchError("Create patch must use /dev/null as its old-file header.")
        return
    if old_path != expected:
        raise WorkspacePatchError("Patch old-file header does not match the exact target.")


def _parse_hunk_header(value: str) -> tuple[int, int, int, int]:
    match = _HUNK_HEADER.fullmatch(value)
    if match is None:
        raise WorkspacePatchError("Patch contains a malformed hunk header.")
    old_count = int(match.group("old_count") or "1")
    new_count = int(match.group("new_count") or "1")
    return int(match.group("old_start")), old_count, int(match.group("new_start")), new_count


def _parse_hunk_lines(
    rows: list[_TextLine],
    index: int,
) -> tuple[list[_PatchLine], int]:
    output: list[_PatchLine] = []
    while index < len(rows) and not rows[index].text.startswith("@@ "):
        row = rows[index].text
        if row == _NO_NEWLINE:
            _mark_no_newline(output)
        elif row and row[0] in {" ", "+", "-"}:
            output.append(_PatchLine(row[0], row[1:]))
        else:
            raise WorkspacePatchError("Patch contains an unsupported or malformed row.")
        index += 1
    return output, index


def _mark_no_newline(lines: list[_PatchLine]) -> None:
    if not lines:
        raise WorkspacePatchError("No-newline marker has no preceding patch row.")
    previous = lines[-1]
    if previous.kind == "-":
        lines[-1] = replace(previous, old_terminated=False)
    elif previous.kind == "+":
        lines[-1] = replace(previous, new_terminated=False)
    else:
        lines[-1] = replace(previous, old_terminated=False, new_terminated=False)


def _validate_hunk_counts(hunk: _Hunk) -> None:
    old_count = sum(line.kind != "+" for line in hunk.lines)
    new_count = sum(line.kind != "-" for line in hunk.lines)
    if old_count != hunk.old_count or new_count != hunk.new_count:
        raise WorkspacePatchError("Patch hunk counts do not match its body.")
    if hunk.old_count == 0 and hunk.old_start != 0:
        raise WorkspacePatchError("Empty old hunk must start at zero.")
    if hunk.new_count == 0 and hunk.new_start != 0:
        raise WorkspacePatchError("Empty new hunk must start at zero.")


def _apply_hunks(source: list[_TextLine], hunks: tuple[_Hunk, ...]) -> list[_TextLine]:
    output: list[_TextLine] = []
    source_cursor = 0
    for hunk in hunks:
        old_index = _hunk_index(hunk.old_start, hunk.old_count)
        new_index = _hunk_index(hunk.new_start, hunk.new_count)
        if old_index < source_cursor or old_index > len(source):
            raise WorkspacePatchError("Patch hunks overlap or address source outside the file.")
        output.extend(source[source_cursor:old_index])
        if len(output) != new_index:
            raise WorkspacePatchError("Patch new-file positions are inconsistent.")
        source_cursor = _apply_hunk_body(source, source_cursor=old_index, output=output, hunk=hunk)
    output.extend(source[source_cursor:])
    return output


def _hunk_index(start: int, count: int) -> int:
    return start - 1 if count else start


def _apply_hunk_body(
    source: list[_TextLine],
    *,
    source_cursor: int,
    output: list[_TextLine],
    hunk: _Hunk,
) -> int:
    for patch_line in hunk.lines:
        if patch_line.kind == "+":
            output.append(_TextLine(patch_line.text, patch_line.new_terminated))
            continue
        expected = _TextLine(patch_line.text, patch_line.old_terminated)
        if source_cursor >= len(source) or source[source_cursor] != expected:
            raise WorkspacePatchError("Patch context does not exactly match the source.")
        source_cursor += 1
        if patch_line.kind == " ":
            output.append(_TextLine(patch_line.text, patch_line.new_terminated))
    return source_cursor


def _encode_lines(lines: list[_TextLine], newline_style: str) -> bytes:
    newline = "\r\n" if newline_style == "crlf" else "\n"
    text = "".join(line.text + (newline if line.terminated else "") for line in lines)
    return text.encode("utf-8")


def _raw_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "MAX_PATCH_BYTES",
    "MAX_PATCH_OPERATIONS",
    "PatchResult",
    "WorkspacePatchError",
    "apply_unified_patch",
]
