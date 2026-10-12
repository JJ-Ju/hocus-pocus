"""The running host: wires config, executor, tools, HTTP server, registry and hip events.

Use the module-level API in ``hocuspocus.host`` (``start``/``stop``/``status``); this
class is the implementation behind it. See docs/BIBLE.md §3.2 and §3.6.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools import catalog, paths
from hocuspocus.version import __version__

from .config import HostConfig
from .dispatch import Dispatcher
from .executor import MainThreadExecutor
from .jobs import JobManager
from .registry import InstanceRegistry, new_token, prune_stale
from .server import HostApp, HostHTTPServer, serve_in_thread
from .tools import registry as tool_registry
from .tools.registry import HostContext, SceneState
from .undo import UndoHistory, hou_undo_group

LOGGER_NAME = "hocuspocus"
LOG_MAX_BYTES = 5 * 1024 * 1024
SUPPORTED_MAJOR_MINOR = (22, 0)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def setup_logging(config: HostConfig, logs_dir: Path, pid: int) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(config.log_level).upper(), logging.INFO))
    logger.propagate = False
    log_path = logs_dir / f"host-{pid}.log"
    for handler in list(logger.handlers):
        if getattr(handler, "_hocuspocus_file", None) == str(log_path):
            return logger
    try:
        paths.ensure_private_dir(logs_dir)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=LOG_MAX_BYTES, backupCount=2, encoding="utf-8", delay=True
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._hocuspocus_file = str(log_path)  # type: ignore[attr-defined]
        logger.addHandler(handler)
    except OSError as exc:  # pragma: no cover - unwritable state dir
        logger.addHandler(logging.StreamHandler(sys.stderr))
        logger.warning("cannot open host log %s: %s", log_path, exc)
    return logger


class Host:
    def __init__(self, config: HostConfig, *, executor: MainThreadExecutor | None = None) -> None:
        self.config = config
        self.pid = os.getpid()
        self.state_dir = Path(config.state_dir) if config.state_dir else paths.state_dir()
        self.logger = logging.getLogger(f"{LOGGER_NAME}.host")
        self.executor = executor or MainThreadExecutor()
        self.scene = SceneState()
        self.undo = UndoHistory()
        self.jobs = JobManager(self.executor, default_timeout_s=config.default_timeout_s)
        self.registry = InstanceRegistry(self.state_dir / "instances", self.pid)
        self.shutdown_event = threading.Event()
        self.server: HostHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.ctx: HostContext | None = None
        self.token = ""
        self.houdini_version = ""
        self.ui = False
        self.started = ""
        self.label = ""
        self._hip_callback_installed = False
        self._stopped = False
        self._atexit_registered = False

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        import hou

        setup_logging(self.config, self.state_dir / "logs", self.pid)
        self.ui = bool(hou.isUIAvailable())
        self.houdini_version = hou.applicationVersionString()
        version = tuple(hou.applicationVersion()[:2])
        if version < SUPPORTED_MAJOR_MINOR:
            self.logger.warning(
                "Houdini %s is older than the supported 22.0; expect failures", self.houdini_version
            )
        self.label = self.config.label or Path(sys.executable).stem.lower()
        self.started = _utc_now()
        self.executor.start()

        tools = tool_registry.load_all()
        tool_registry.validate(self.logger)
        self.ctx = HostContext(
            config=self.config,
            executor=self.executor,
            logger=self.logger,
            scene=self.scene,
            jobs=self.jobs,
            undo=self.undo,
            ui=self.ui,
            pid=self.pid,
            started=self.started,
            label=self.label,
        )
        dispatcher = Dispatcher(
            self.ctx,
            tool_registry.get,
            undo_group=hou_undo_group,
            known_tool=lambda name: catalog.get(name) is not None,
        )
        self.token = new_token()
        app = HostApp(
            token=self.token,
            call=dispatcher.call,
            health=self.health,
            job=self.jobs.result,
            shutdown=self.request_shutdown,
            meta=self.meta,
        )
        self.server = HostHTTPServer(app, "127.0.0.1", int(self.config.port))
        self.ctx.port = self.server.port
        self.thread = serve_in_thread(self.server)

        self.scene.mark_clean()
        hou.hipFile.addEventCallback(self._on_hip_event)
        self._hip_callback_installed = True

        removed = prune_stale(self.registry.directory)
        if removed:
            self.logger.info("pruned %d stale registry entries", len(removed))
        self.registry.write(
            {
                "port": self.server.port,
                "token": self.token,
                "houdini": self.houdini_version,
                "ui": self.ui,
                "hip": hou.hipFile.path(),
                "started": self.started,
                "generation": self.scene.generation,
                "label": self.label,
            }
        )
        if not self._atexit_registered:
            atexit.register(self._atexit)
            self._atexit_registered = True
        self.logger.info(
            "host %s listening on 127.0.0.1:%d (pid %d, %s, %d tools, Houdini %s)",
            __version__,
            self.server.port,
            self.pid,
            "gui" if self.ui else "headless",
            len(tools),
            self.houdini_version,
        )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.shutdown_event.set()
        if self._hip_callback_installed:
            try:
                import hou

                hou.hipFile.removeEventCallback(self._on_hip_event)
            except Exception:
                self.logger.debug("removeEventCallback failed", exc_info=True)
            self._hip_callback_installed = False
        self.registry.remove()
        server = self.server
        if server is not None:
            if self.thread is not None and self.thread is not threading.current_thread():
                server.shutdown()
            server.server_close()
        self.jobs.cancel_all()
        self.executor.stop()
        if self._atexit_registered:
            with contextlib.suppress(Exception):
                atexit.unregister(self._atexit)
            self._atexit_registered = False
        self.logger.info("host stopped")

    def _atexit(self) -> None:
        with contextlib.suppress(Exception):
            self.stop()

    def request_shutdown(self) -> None:
        """``POST /hp/v1/shutdown``: stop the host (not Houdini) on the main thread."""
        self.logger.info("shutdown requested over HTTP")
        self.shutdown_event.set()
        from . import stop as module_stop

        self.executor.post(module_stop)

    # -- state -------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self.server.port if self.server is not None else 0

    @property
    def running(self) -> bool:
        return self.server is not None and not self._stopped

    def meta(self) -> dict[str, Any]:
        return {"scene_generation": self.scene.generation, "undo_label": None, "elapsed_ms": 0}

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "hp": catalog.HP_RPC_VERSION,
            "pid": self.pid,
            "houdini": self.houdini_version,
            "generation": self.scene.generation,
            "ui": self.ui,
            "host_version": __version__,
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "pid": self.pid,
            "port": self.port,
            "ui": self.ui,
            "houdini": self.houdini_version,
            "label": self.label,
            "started": self.started,
            "backend": self.executor.backend,
            "scene_generation": self.scene.generation,
            "token_file": str(self.registry.path),
            "host_version": __version__,
            "read_only": bool(self.config.read_only),
            "allow_python": bool(self.config.allow_python),
        }

    # -- hip events --------------------------------------------------------------

    def _on_hip_event(self, event_type: Any) -> None:
        try:
            self._handle_hip_event(event_type)
        except Exception:
            self.logger.exception("hip event handler failed for %s", event_type)

    def _handle_hip_event(self, event_type: Any) -> None:
        import hou

        events = hou.hipFileEventType
        if event_type == events.BeforeQuit:
            self.logger.info("Houdini is quitting")
            self.registry.remove()
            self.stop()
            return
        changed = False
        if event_type == events.AfterClear:
            # A load clears first; count the load once (on AfterLoad).
            if not hou.hipFile.isLoadingHipFile():
                self.scene.bump()
                changed = True
            self.scene.mark_clean()
        elif event_type == events.AfterLoad:
            self.scene.bump()
            self.scene.mark_clean()
            changed = True
        elif event_type == events.AfterMerge:
            self.scene.bump()
            self.scene.mark_dirty()
            changed = True
        elif event_type == events.AfterSave:
            self.scene.mark_clean()
            changed = True
        if changed and not self._stopped:
            try:
                self.registry.update(hip=hou.hipFile.path(), generation=self.scene.generation)
            except OSError as exc:
                self.logger.warning("cannot update registry entry: %s", exc)
