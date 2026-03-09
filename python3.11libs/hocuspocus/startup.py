"""Public server lifecycle entry points."""

from __future__ import annotations

from threading import Lock
from typing import Any

from .core.logging_utils import configure_logging
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
            }
        return _runtime.status(include_secret=True)
