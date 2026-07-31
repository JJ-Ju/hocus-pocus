"""Public server lifecycle entry points."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import re
import sys
from threading import Lock
from typing import Any, TYPE_CHECKING

from .core.logging_utils import configure_logging
from .core import paths
from .core.settings import load_settings
from .version import __version__

if TYPE_CHECKING:
    from .core.server import HocusPocusRuntime

SUPPORTED_HOUDINI_VERSION = "22.0.368"
RUNTIME_ADMISSION_CODE = "HOCUS998"
_VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,8}$")
_runtime_lock = Lock()
_runtime: HocusPocusRuntime | None = None
_startup_failure: dict[str, str] | None = None


class RuntimeAdmissionError(RuntimeError):
    """The host or Python loader cannot run the governed installed payload."""

    code = RUNTIME_ADMISSION_CODE

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "kind": "runtime_admission",
            "reason": self.reason,
            "message": str(self),
        }


def start_server(config_path: str | None = None) -> dict[str, Any]:
    global _runtime, _startup_failure
    with _runtime_lock:
        if _runtime is not None:
            return _runtime.status()

        try:
            _require_runtime_admission()
        except RuntimeAdmissionError as exc:
            _startup_failure = exc.to_payload()
            raise
        from .core.server import HocusPocusRuntime

        settings = load_settings(config_path=config_path)
        logger = configure_logging(settings.log_level)
        runtime = HocusPocusRuntime(settings, logger)
        runtime.start()
        _runtime = runtime
        _startup_failure = None
        logger.getChild("startup").info("HocusPocus MCP %s is running.", __version__)
        return runtime.status(include_secret=True)


def stop_server() -> dict[str, Any]:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            return {"running": False}
        runtime = _runtime
        _runtime = None
        runtime.stop()
        return {"running": False}


def restart_server(config_path: str | None = None) -> dict[str, Any]:
    stop_server()
    return start_server(config_path=config_path)


def server_status() -> dict[str, Any]:
    with _runtime_lock:
        if _runtime is None:
            settings = load_settings()
            payload = {
                "serverVersion": __version__,
                "running": False,
                "host": settings.host,
                "port": settings.port,
                "mcpUrl": settings.mcp_url,
                "healthUrl": settings.health_url,
                "tokenEnabled": settings.token_mode != "disabled",
                "policyProfile": settings.policy_profile,
                "policyProfileSource": settings.policy_profile_source,
                "effectivePolicy": settings.effective_policy_payload(),
                "availablePolicyProfiles": settings.available_policy_profiles_payload(),
            }
            if _startup_failure is not None:
                payload["startupFailure"] = dict(_startup_failure)
            return payload
        return _runtime.status(include_secret=True)


def _require_runtime_admission() -> None:
    actual = _houdini_version()
    if actual != SUPPORTED_HOUDINI_VERSION:
        raise RuntimeAdmissionError(
            "unsupported_houdini",
            "HocusPocus requires Houdini "
            f"{SUPPORTED_HOUDINI_VERSION}; the active host is {actual}.",
        )
    if sys.pycache_prefix is not None or not sys.dont_write_bytecode:
        raise RuntimeAdmissionError(
            "ungoverned_bytecode",
            "HocusPocus requires installed Python bytecode caching to be disabled.",
        )
    for name, module in tuple(sys.modules.items()):
        if not _governed_module_name(name) or module is None:
            continue
        cached = getattr(module, "__cached__", None)
        if cached and _cached_file_exists(cached):
            raise RuntimeAdmissionError(
                "ungoverned_bytecode",
                "HocusPocus detected an ungoverned loaded Python bytecode artifact.",
            )


def _houdini_version() -> str:
    try:
        import hou  # type: ignore

        value = hou.applicationVersionString()
    except Exception:
        return "unavailable"
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        return "unavailable"
    return value


def _governed_module_name(name: Any) -> bool:
    return isinstance(name, str) and (
        name == "hocuspocus"
        or name.startswith("hocuspocus.")
        or name.startswith("smoke_hocusscript_")
        or name in {"hs8_install_manifest", "hs8_output_guard"}
    )


def _cached_file_exists(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\0" in value:
        return True
    try:
        return Path(value).is_file()
    except OSError:
        return True


def panel_snapshot(
    *,
    task_limit: int = 10,
    event_limit: int = 20,
    log_line_limit: int = 40,
) -> dict[str, Any]:
    status = server_status()
    tasks: list[dict[str, Any]] = []
    events: dict[str, Any] = {"count": 0, "latestSequence": 0, "events": []}
    logs: list[str] = []
    with _runtime_lock:
        runtime = _runtime
        if runtime is not None:
            tasks = runtime.tasks.snapshots(limit=task_limit)
            events = runtime.monitor.recent_events(limit=event_limit)
    log_path = paths.server_log_path()
    if log_path.exists():
        lines = deque(maxlen=log_line_limit)
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines.append(line.rstrip())
        logs = list(lines)
    return {
        "status": status,
        "tasks": tasks,
        "events": events,
        "logs": logs,
        "workspaces": workspace_snapshot(),
    }


def workspace_snapshot() -> dict[str, Any]:
    with _runtime_lock:
        runtime = _runtime
        if runtime is None:
            return {"projects": [], "sessions": [], "grants": [], "recentAudit": []}
        return runtime.workspace_snapshot()


def register_workspace_project(
    project_directory: str,
    *,
    label: str | None = None,
    reapprove: bool = False,
) -> dict[str, Any]:
    runtime = _running_runtime()
    return runtime.register_workspace_project(
        project_directory,
        label=label,
        reapprove=reapprove,
    )


def remove_workspace_project(project_id: str) -> dict[str, Any]:
    return _running_runtime().remove_workspace_project(project_id)


def grant_workspace_project(
    project_id: str,
    *,
    session_id: str | None = None,
    grants: tuple[str, ...] = ("source_read",),
    external_roots: dict[str, str] | None = None,
    persistent: bool = False,
    expires_in_seconds: float | None = None,
    until_revoked: bool = False,
) -> dict[str, Any]:
    return _running_runtime().grant_workspace_project(
        project_id,
        session_id=session_id,
        grants=grants,
        external_roots=external_roots,
        persistent=persistent,
        expires_in_seconds=expires_in_seconds,
        until_revoked=until_revoked,
    )


def revoke_workspace_project(
    project_id: str,
    *,
    session_id: str | None = None,
    persistent: bool | None = None,
) -> bool:
    return _running_runtime().revoke_workspace_project(
        project_id,
        session_id=session_id,
        persistent=persistent,
    )


def _running_runtime() -> HocusPocusRuntime:
    with _runtime_lock:
        runtime = _runtime
    if runtime is None:
        start_server()
        with _runtime_lock:
            runtime = _runtime
    if runtime is None:
        raise RuntimeError("HocusPocus server could not be started.")
    return runtime
