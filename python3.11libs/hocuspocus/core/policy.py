"""Capability and filesystem policy helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .jsonrpc import JsonRpcError
from .settings import ServerSettings

OBSERVE = "observe"
EDIT_SCENE = "edit_scene"
WRITE_FILES = "write_files"
RUN_CODE = "run_code"
LAUNCH_PROCESSES = "launch_processes"
USE_NETWORK = "use_network"
SUBMIT_FARM_JOBS = "submit_farm_jobs"


def capability_set_from_settings(settings: ServerSettings) -> tuple[str, ...]:
    capabilities = {OBSERVE}
    if not settings.read_only and settings.allow_scene_edit:
        capabilities.add(EDIT_SCENE)
    if not settings.read_only and settings.allow_file_write:
        capabilities.add(WRITE_FILES)
    if settings.enable_exec_tools:
        capabilities.add(RUN_CODE)
    return tuple(sorted(capabilities))


def require_capabilities(
    granted: Iterable[str],
    required: Iterable[str],
) -> None:
    granted_set = set(granted)
    missing = [item for item in required if item not in granted_set]
    if missing:
        raise JsonRpcError(
            -32010,
            "Permission denied.",
            {"missingCapabilities": missing},
        )


def ensure_path_allowed(path: str | Path, settings: ServerSettings) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not settings.allow_file_write or settings.read_only:
        raise JsonRpcError(
            -32010,
            "File writes are disabled by server policy.",
            {"path": str(resolved)},
        )

    if not settings.approved_roots:
        return resolved

    approved = [
        Path(root).expanduser().resolve(strict=False)
        for root in settings.approved_roots
    ]
    for root in approved:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise JsonRpcError(
        -32011,
        "Path is outside approved roots.",
        {
            "path": str(resolved),
            "approvedRoots": [str(root) for root in approved],
        },
    )
