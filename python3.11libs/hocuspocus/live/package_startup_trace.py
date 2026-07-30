"""Strict parser for Houdini's pre-startup package verbose trace."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable


TRACE_ENVIRONMENT = "HOCUSPOCUS_HS8_PACKAGE_TRACE"
TRACE_AUTHORITY = "HOUDINI_PACKAGE_VERBOSE=1"
MAX_TRACE_BYTES = 4 * 1024 * 1024
MAX_TRACE_PACKAGES = 4096
_START = "= = = Houdini Package log = = ="
_END = "= = = = = = = = = = = = = = = ="
_EVENT = re.compile(r"^(Loading|Processing|Processing load once):\s+(.+?)\s*$")
_SECTION = re.compile(r"^(Loaded|Disabled) Packages \((\d+)\):$")


class PackageStartupTraceError(RuntimeError):
    """The captured startup trace is absent, malformed, or incomplete."""


def load_package_startup_trace(
    value: str | bytes | Path | None = None,
    *,
    expand: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Load and parse one bounded authoritative startup trace."""

    selected = value
    if selected is None:
        raw_path = os.environ.get(TRACE_ENVIRONMENT)
        if not raw_path:
            raise PackageStartupTraceError(
                "Authoritative Houdini package startup trace is unavailable."
            )
        selected = Path(raw_path)
    if isinstance(selected, Path):
        try:
            if selected.is_symlink() or not selected.is_file():
                raise PackageStartupTraceError(
                    "Houdini package startup trace is not a regular file."
                )
            size = selected.stat().st_size
            if not 0 < size <= MAX_TRACE_BYTES:
                raise PackageStartupTraceError(
                    "Houdini package startup trace exceeds its byte limit."
                )
            selected = selected.read_bytes()
        except OSError as exc:
            raise PackageStartupTraceError(
                "Houdini package startup trace cannot be read."
            ) from exc
    if isinstance(selected, str):
        try:
            encoded = selected.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PackageStartupTraceError(
                "Houdini package startup trace is not strict UTF-8."
            ) from exc
    elif isinstance(selected, bytes):
        encoded = selected
    else:
        raise PackageStartupTraceError(
            "Houdini package startup trace carrier is invalid."
        )
    if not 0 < len(encoded) <= MAX_TRACE_BYTES:
        raise PackageStartupTraceError(
            "Houdini package startup trace exceeds its byte limit."
        )
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageStartupTraceError(
            "Houdini package startup trace is not strict UTF-8."
        ) from exc
    return _parse_trace(text, expand or (lambda item: item))


def _parse_trace(text: str, expand: Callable[[str], str]) -> dict[str, Any]:
    start = text.find(_START)
    end = text.find(_END, start + len(_START))
    if start < 0 or end < 0 or text.find(_START, start + 1) >= 0:
        raise PackageStartupTraceError(
            "Houdini package startup trace has no unique complete log."
        )
    events, summaries, expected = _scan_lines(
        text[start:end].splitlines()[1:], expand,
    )
    return _validated_trace(events, summaries, expected)


def _scan_lines(
    lines: list[str],
    expand: Callable[[str], str],
) -> tuple[list[dict[str, Any]], dict[str, list[Path]], dict[str, int]]:
    events: list[dict[str, Any]] = []
    summaries: dict[str, list[Path]] = {"loaded": [], "disabled": []}
    expected: dict[str, int] = {}
    section: str | None = None
    in_loading_info = False
    for raw in lines:
        stripped = raw.strip()
        if stripped == "Loading Info:":
            in_loading_info = True
            section = None
            continue
        match = _EVENT.fullmatch(stripped)
        if match and not in_loading_info:
            kind = {
                "Loading": "discovered",
                "Processing": "processed",
                "Processing load once": "load_once",
            }[match.group(1)]
            events.append({
                "rank": len(events),
                "kind": kind,
                "path": _trace_path(match.group(2), expand),
            })
            continue
        heading = _SECTION.fullmatch(stripped)
        if in_loading_info and heading:
            section = heading.group(1).lower()
            expected[section] = int(heading.group(2))
            continue
        if in_loading_info and section and raw.startswith((" ", "\t")) and stripped:
            summaries[section].append(_trace_path(stripped, expand))
    return events, summaries, expected


def _validated_trace(
    events: list[dict[str, Any]],
    summaries: dict[str, list[Path]],
    expected: dict[str, int],
) -> dict[str, Any]:
    if set(expected) != {"loaded", "disabled"}:
        raise PackageStartupTraceError(
            "Houdini package startup trace omits its loaded/disabled summary."
        )
    for name, paths in summaries.items():
        if expected[name] != len(paths) or len(paths) > MAX_TRACE_PACKAGES:
            raise PackageStartupTraceError(
                f"Houdini package startup trace {name} count is inconsistent."
            )
        if len({_path_key(item) for item in paths}) != len(paths):
            raise PackageStartupTraceError(
                f"Houdini package startup trace repeats a {name} package."
            )
    loaded = {_path_key(item) for item in summaries["loaded"]}
    disabled = {_path_key(item) for item in summaries["disabled"]}
    if loaded.intersection(disabled):
        raise PackageStartupTraceError(
            "Houdini package startup trace marks a package loaded and disabled."
        )
    discovered = [item for item in events if item["kind"] == "discovered"]
    processed = [item for item in events if item["kind"] == "processed"]
    if not discovered or not processed:
        raise PackageStartupTraceError(
            "Houdini package startup trace lacks authoritative processing events."
        )
    discovered_keys = [_path_key(item["path"]) for item in discovered]
    processed_keys = [_path_key(item["path"]) for item in processed]
    if len(set(discovered_keys)) != len(discovered_keys):
        raise PackageStartupTraceError(
            "Houdini package startup trace repeats a discovery event."
        )
    if len(set(processed_keys)) != len(processed_keys):
        raise PackageStartupTraceError(
            "Houdini package startup trace repeats a processing event."
        )
    if set(processed_keys) != loaded:
        raise PackageStartupTraceError(
            "Houdini processed-package order disagrees with its loaded summary."
        )
    if not loaded.union(disabled).issubset(set(discovered_keys)):
        raise PackageStartupTraceError(
            "Houdini package summary contains an undiscovered package."
        )
    skipped = [
        item["path"] for item in discovered
        if _path_key(item["path"]) not in loaded.union(disabled)
    ]
    if len(events) > MAX_TRACE_PACKAGES * 3:
        raise PackageStartupTraceError(
            "Houdini package startup trace event count exceeds its limit."
        )
    return {
        "authority": TRACE_AUTHORITY,
        "events": events,
        "loaded": tuple(summaries["loaded"]),
        "disabled": tuple(summaries["disabled"]),
        "skipped": tuple(skipped),
        "processed": tuple(item["path"] for item in processed),
    }


def _trace_path(value: str, expand: Callable[[str], str]) -> Path:
    expanded = expand(value)
    if not isinstance(expanded, str) or not expanded or "\0" in expanded:
        raise PackageStartupTraceError(
            "Houdini package startup trace contains an invalid path."
        )
    try:
        path = Path(expanded).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PackageStartupTraceError(
            "Houdini package startup trace contains an invalid path."
        ) from exc
    if path.suffix.casefold() != ".json":
        raise PackageStartupTraceError(
            "Houdini package startup trace contains a non-JSON package."
        )
    return path


def _path_key(value: Path) -> str:
    return str(value).replace("\\", "/").casefold()


__all__ = [
    "MAX_TRACE_BYTES",
    "PackageStartupTraceError",
    "TRACE_AUTHORITY",
    "TRACE_ENVIRONMENT",
    "load_package_startup_trace",
]
