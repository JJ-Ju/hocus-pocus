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
POLICY_DENIED_ERROR = -32010
PATH_POLICY_ERROR = -32011


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
            POLICY_DENIED_ERROR,
            "Permission denied.",
            {"missingCapabilities": missing},
            family="policy",
            retryable=False,
        )


def ensure_path_allowed(path: str | Path, settings: ServerSettings) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not settings.allow_file_write or settings.read_only:
        raise JsonRpcError(
            POLICY_DENIED_ERROR,
            "File writes are disabled by server policy.",
            {"path": str(resolved)},
            family="policy",
            retryable=False,
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
        PATH_POLICY_ERROR,
        "Path is outside approved roots.",
        {
            "path": str(resolved),
            "approvedRoots": [str(root) for root in approved],
        },
        family="policy",
        retryable=False,
    )
