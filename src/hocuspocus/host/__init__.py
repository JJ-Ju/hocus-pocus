"""The host: runs inside Houdini. Stdlib only; ``hou`` is imported lazily. See docs/BIBLE.md §3.2.

Public API (all idempotent, none raises into Houdini)::

    hocuspocus.host.start(config=None, **overrides) -> dict   # status
    hocuspocus.host.stop() -> dict
    hocuspocus.host.status() -> dict
    hocuspocus.host.autostart() -> dict   # what uiready.py calls; honours autostart=false
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import HostConfig
    from .runtime import Host

__all__ = ["autostart", "current", "start", "status", "stop"]

log = logging.getLogger("hocuspocus.host")

_LOCK = threading.RLock()
_HOST: Host | None = None
_LAST_ERROR: str | None = None


def _ui_message(message: str, *, warning: bool = False) -> None:
    try:
        import hou

        if hou.isUIAvailable():
            severity = hou.severityType.Warning if warning else hou.severityType.Message
            hou.ui.setStatusMessage(message, severity=severity)
    except Exception:
        pass


def current() -> Host | None:
    return _HOST


def start(config: HostConfig | None = None, **overrides: Any) -> dict[str, Any]:
    """Start the host if it is not running and return :func:`status`. Never raises."""
    global _HOST, _LAST_ERROR
    with _LOCK:
        if _HOST is not None and _HOST.running:
            return status()
        host = None
        try:
            from .config import load_config
            from .runtime import Host

            if config is None:
                config = load_config(**overrides)
            elif overrides:
                config = config.with_overrides(**overrides)
            host = Host(config)
            host.start()
        except Exception as exc:
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
            log.exception("HocusPocus host failed to start")
            if host is not None:
                try:
                    host.stop()
                except Exception:
                    log.debug("cleanup after failed start raised", exc_info=True)
            _ui_message(
                f"HocusPocus failed to start: {_LAST_ERROR} (see the host log)", warning=True
            )
            _HOST = None
            return status()
        _HOST = host
        _LAST_ERROR = None
        if host.ui:
            _ui_message(f"HocusPocus listening on 127.0.0.1:{host.port}")
        return status()


def stop() -> dict[str, Any]:
    """Stop the host (not Houdini). Never raises."""
    global _HOST
    with _LOCK:
        host = _HOST
        _HOST = None
        if host is not None:
            try:
                host.stop()
            except Exception:
                log.exception("HocusPocus host failed to stop cleanly")
            if host.ui:
                _ui_message("HocusPocus stopped")
        return status()


def status() -> dict[str, Any]:
    host = _HOST
    if host is None:
        data: dict[str, Any] = {"running": False}
        if _LAST_ERROR:
            data["error"] = _LAST_ERROR
        return data
    return host.status()


def autostart() -> dict[str, Any]:
    """GUI autostart entry point (``uiready.py``). Honours ``autostart = false``."""
    try:
        from .config import load_config

        config = load_config()
        if not config.autostart:
            log.info("HocusPocus autostart disabled by configuration")
            return status()
        return start(config)
    except Exception:
        log.exception("HocusPocus autostart failed")
        return status()
