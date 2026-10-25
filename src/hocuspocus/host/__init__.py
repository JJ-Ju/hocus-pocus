"""The host: runs inside Houdini. Stdlib only; ``hou`` is imported lazily. See docs/BIBLE.md §3.2.

Public API (all idempotent, none raises into Houdini)::

    hocuspocus.host.start(config=None, **overrides) -> dict   # status
    hocuspocus.host.stop() -> dict
    hocuspocus.host.status() -> dict
    hocuspocus.host.autostart() -> dict   # what uiready.py calls; honours autostart=false
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path
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


def _startup_record(state_dir: str | None) -> Path:
    from hocuspocus.tools import paths

    return paths.startup_dir(Path(state_dir) if state_dir else None) / f"{os.getpid()}.json"


def _write_startup(record: Path, phase: str, **fields: Any) -> None:
    """Say how far this GUI host's start got (D60: a launch waiting for it reads this and
    tells the agent why it never registered). Never raises."""
    try:
        from .registry import _write_private_atomic, prune_stale

        prune_stale(record.parent)  # the records of Houdinis that have exited
        data = {"pid": os.getpid(), "phase": phase, "time": time.time(), **fields}
        _write_private_atomic(record, json.dumps(data, indent=1))
    except Exception:
        log.debug("cannot write the startup record %s", record, exc_info=True)


def autostart() -> dict[str, Any]:
    """GUI autostart entry point (``uiready.py``). Honours ``autostart = false``.

    Writes ``<state_dir>/startup/<pid>.json`` (D60): ``starting`` before the host starts,
    ``failed`` (with the error and the host log) or ``disabled`` when it does not, and
    deletes it once the host runs."""
    record = _startup_record(None)
    try:
        from .config import load_config

        config = load_config()
        record = _startup_record(config.state_dir)
        if not config.autostart:
            log.info("HocusPocus autostart disabled by configuration")
            _write_startup(record, "disabled")
            return status()
        _write_startup(record, "starting")
        result = start(config)
    except Exception as exc:
        log.exception("HocusPocus autostart failed")
        _write_startup(record, "failed", error=f"{type(exc).__name__}: {exc}")
        return status()
    if result.get("running"):
        with contextlib.suppress(OSError):
            record.unlink()
    else:
        log_path = record.parent.parent / "logs" / f"host-{os.getpid()}.log"
        _write_startup(
            record,
            "failed",
            error=result.get("error") or "the host did not start",
            log=str(log_path),
        )
    return result
