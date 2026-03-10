"""Public server lifecycle entry points."""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

from .core.logging_utils import configure_logging
from .core import paths
from .core.server import HocusPocusRuntime
from .core.settings import load_settings
from .version import __version__

_runtime_lock = Lock()
_runtime: HocusPocusRuntime | None = None


def start_server(config_path: str | None = None) -> dict[str, Any]:
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            return _runtime.status()

        settings = load_settings(config_path=config_path)
        logger = configure_logging(settings.log_level)
        runtime = HocusPocusRuntime(settings, logger)
        runtime.start()
        _runtime = runtime
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
            return {
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
        return _runtime.status(include_secret=True)


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
    }
