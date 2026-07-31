"""Exclusive, bounded output publication for HS8 evidence."""

from __future__ import annotations

from pathlib import Path


class OutputGuardError(RuntimeError):
    """An evidence output could not be published without clobbering."""


def copy_exclusive(source: Path, target: Path, *, max_bytes: int) -> int:
    original_size = _validated_source_size(source, target, max_bytes)
    created = False
    total = 0
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            created = True
            total = _copy_bounded(reader, writer, max_bytes)
        if total != original_size:
            raise OutputGuardError("Evidence source changed during publication.")
    except FileExistsError as exc:
        raise OutputGuardError("Evidence output already exists.") from exc
    except Exception:
        if created:
            _remove_partial(target)
        raise
    return total


def copy_exclusive_or_identical(
    source: Path,
    target: Path,
    *,
    max_bytes: int,
) -> int:
    """Publish once, or accept an already-published byte-identical output."""

    try:
        return copy_exclusive(source, target, max_bytes=max_bytes)
    except OutputGuardError:
        source_size = _validated_source_size(source, target, max_bytes)
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_size != source_size
            or not _same_bytes(source, target)
        ):
            raise
        return source_size


def _validated_source_size(source: Path, target: Path, max_bytes: int) -> int:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise OutputGuardError("Output byte limit is invalid.")
    if source.is_symlink() or not source.is_file():
        raise OutputGuardError("Evidence source must be a regular file.")
    original_size = source.stat().st_size
    if original_size > max_bytes:
        raise OutputGuardError("Evidence source exceeds its byte limit.")
    if not target.parent.is_dir():
        raise OutputGuardError("Evidence output parent is missing.")
    return original_size


def _copy_bounded(reader: object, writer: object, maximum: int) -> int:
    total = 0
    while True:
        chunk = reader.read(min(1024 * 1024, maximum - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise OutputGuardError("Evidence source grew beyond its byte limit.")
        writer.write(chunk)
    return total


def _remove_partial(target: Path) -> None:
    try:
        target.unlink()
    except OSError:
        pass


def _same_bytes(left: Path, right: Path) -> bool:
    with left.open("rb") as left_reader, right.open("rb") as right_reader:
        while True:
            left_chunk = left_reader.read(1024 * 1024)
            right_chunk = right_reader.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


__all__ = [
    "OutputGuardError",
    "copy_exclusive",
    "copy_exclusive_or_identical",
]
