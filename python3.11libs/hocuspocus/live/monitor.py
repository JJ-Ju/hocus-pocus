"""Scene event monitoring for live Houdini sessions."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore


class SceneEventMonitor:
    def __init__(self, logger: logging.Logger):
        self._logger = logger.getChild("live.monitor")
        self._lock = threading.Lock()
        self._revision = 0
        self._event_sequence = 0
        self._last_event = "startup"
        self._last_event_time = time.time()
        self._recent_events: list[dict[str, Any]] = []
        self._callbacks_installed = False
        self._hip_callback_installed = False
        self._playbar_callback_installed = False
        self._selection_callback_installed = False
        self._playbar_retry_registered = False

    def start(self) -> None:
        if hou is None:
            self._logger.info("hou not available; scene callbacks disabled")
            return

        installed_any = False
        try:
            hou.hipFile.addEventCallback(self._on_hip_event)
            self._hip_callback_installed = True
            installed_any = True
        except Exception:
            self._logger.exception("failed to install hip callbacks")

        if self._install_playbar_callback():
            installed_any = True
        elif hou.isUIAvailable():
            self._schedule_playbar_retry()

        if hou.isUIAvailable():
            try:
                hou.ui.addSelectionCallback(self._on_selection_event)
                self._selection_callback_installed = True
                installed_any = True
            except Exception:
                self._logger.warning("selection callbacks unavailable in this context", exc_info=True)

        self._callbacks_installed = installed_any
        if installed_any:
            self._logger.info(
                "scene callbacks installed hip=%s playbar=%s selection=%s",
                self._hip_callback_installed,
                self._playbar_callback_installed,
                self._selection_callback_installed,
            )
        else:
            self._logger.warning("no scene callbacks could be installed")

    def stop(self) -> None:
        if hou is None or not self._callbacks_installed:
            return

        if self._hip_callback_installed:
            try:
                hou.hipFile.removeEventCallback(self._on_hip_event)
            except Exception:
                self._logger.debug("hip callback removal failed", exc_info=True)

        if self._playbar_callback_installed:
            try:
                hou.playbar.removeEventCallback(self._on_playbar_event)
            except Exception:
                self._logger.debug("playbar callback removal failed", exc_info=True)

        if self._playbar_retry_registered and hou.isUIAvailable():
            try:
                hou.ui.removeEventLoopCallback(self._retry_playbar_callback_install)
            except Exception:
                self._logger.debug("playbar retry callback removal failed", exc_info=True)

        if self._selection_callback_installed and hou.isUIAvailable():
            try:
                hou.ui.removeSelectionCallback(self._on_selection_event)
            except Exception:
                self._logger.debug("selection callback removal failed", exc_info=True)

        self._callbacks_installed = False
        self._hip_callback_installed = False
        self._playbar_callback_installed = False
        self._selection_callback_installed = False
        self._playbar_retry_registered = False

    def _bump(self, event_name: str) -> None:
        with self._lock:
            self._revision += 1
            self._event_sequence += 1
            self._last_event = event_name
            self._last_event_time = time.time()
            self._recent_events.append(
                {
                    "sequence": self._event_sequence,
                    "revision": self._revision,
                    "event": event_name,
                    "timestamp": self._last_event_time,
                }
            )
            if len(self._recent_events) > 500:
                self._recent_events = self._recent_events[-500:]

    def mark_dirty(self, event_name: str) -> None:
        self._bump(event_name)

    def _on_hip_event(self, event_type: Any) -> None:
        self._bump(f"hip:{event_type}")

    def _on_playbar_event(self, event_type: Any) -> None:
        self._bump(f"playbar:{event_type}")

    def _on_selection_event(self, selection: Any) -> None:
        self._bump("selection:changed")

    def _install_playbar_callback(self) -> bool:
        if hou is None or self._playbar_callback_installed:
            return self._playbar_callback_installed
        try:
            hou.playbar.addEventCallback(self._on_playbar_event)
            self._playbar_callback_installed = True
            self._logger.info("playbar callbacks installed")
            return True
        except hou.NotAvailable:  # type: ignore[attr-defined]
            self._logger.info("playbar callbacks not ready yet; deferring registration")
            return False
        except Exception:
            self._logger.warning("playbar callbacks unavailable in this context", exc_info=True)
            return False

    def _schedule_playbar_retry(self) -> None:
        if hou is None or self._playbar_retry_registered or self._playbar_callback_installed:
            return
        try:
            hou.ui.addEventLoopCallback(self._retry_playbar_callback_install)
            self._playbar_retry_registered = True
        except Exception:
            self._logger.debug("unable to schedule playbar retry callback", exc_info=True)

    def _retry_playbar_callback_install(self) -> None:
        if hou is None:
            return
        if self._install_playbar_callback():
            self._callbacks_installed = True
            if self._playbar_retry_registered:
                try:
                    hou.ui.removeEventLoopCallback(self._retry_playbar_callback_install)
                except Exception:
                    self._logger.debug("playbar retry callback removal failed", exc_info=True)
                self._playbar_retry_registered = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "revision": self._revision,
                "eventSequence": self._event_sequence,
                "lastEvent": self._last_event,
                "lastEventTime": self._last_event_time,
                "callbacksInstalled": self._callbacks_installed,
                "hipCallbackInstalled": self._hip_callback_installed,
                "playbarCallbackInstalled": self._playbar_callback_installed,
                "playbarRetryRegistered": self._playbar_retry_registered,
                "selectionCallbackInstalled": self._selection_callback_installed,
            }

    def recent_events(
        self,
        *,
        limit: int = 100,
        after_sequence: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            events = list(self._recent_events)
            if after_sequence is not None:
                events = [item for item in events if item["sequence"] > after_sequence]
            if limit > 0:
                events = events[-limit:]
            return {
                "count": len(events),
                "latestSequence": self._event_sequence,
                "events": events,
            }
