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
        self._node_callbacks_installed = False
        self._playbar_retry_registered = False
        self._scene_dirty_revision = 0
        self._dirty_scopes: dict[str, int] = {}
        self._listeners: list[Any] = []
        self._observed_nodes: dict[int, Any] = {}

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

        if self._install_node_callbacks():
            installed_any = True

        self._callbacks_installed = installed_any
        if installed_any:
            self._logger.info(
                "scene callbacks installed hip=%s playbar=%s selection=%s nodes=%s",
                self._hip_callback_installed,
                self._playbar_callback_installed,
                self._selection_callback_installed,
                self._node_callbacks_installed,
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

        for node in list(self._observed_nodes.values()):
            try:
                node.removeEventCallback(self._on_node_event)
            except Exception:
                self._logger.debug("node callback removal failed", exc_info=True)
        self._observed_nodes.clear()

        self._callbacks_installed = False
        self._hip_callback_installed = False
        self._playbar_callback_installed = False
        self._selection_callback_installed = False
        self._node_callbacks_installed = False
        self._playbar_retry_registered = False

    def add_listener(self, listener: Any) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Any) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not listener]

    def _bump(self, event_name: str, scope_path: str | None = None) -> None:
        payload: dict[str, Any]
        with self._lock:
            self._revision += 1
            self._event_sequence += 1
            self._last_event = event_name
            self._last_event_time = time.time()
            normalized_scope = str(scope_path).strip() if scope_path else None
            if normalized_scope:
                self._dirty_scopes[normalized_scope] = self._revision
            else:
                self._scene_dirty_revision = self._revision
            payload = {
                "sequence": self._event_sequence,
                "revision": self._revision,
                "event": event_name,
                "timestamp": self._last_event_time,
                "scopePath": normalized_scope,
            }
            self._recent_events.append(
                payload
            )
            if len(self._recent_events) > 500:
                self._recent_events = self._recent_events[-500:]
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(dict(payload))
            except Exception:
                self._logger.debug("monitor listener failed", exc_info=True)

    def mark_dirty(self, event_name: str, scope_path: str | None = None) -> None:
        self._bump(event_name, scope_path=scope_path)

    def clear_scope_dirty(self, scope_path: str) -> None:
        normalized = str(scope_path).strip()
        if not normalized:
            return
        with self._lock:
            self._dirty_scopes.pop(normalized, None)

    def _on_hip_event(self, event_type: Any) -> None:
        self._bump(f"hip:{event_type}")

    def _on_playbar_event(self, event_type: Any) -> None:
        self._bump(f"playbar:{event_type}")

    def _on_selection_event(self, selection: Any) -> None:
        self._bump("selection:changed")

    @staticmethod
    def _node_scope_path(node: Any) -> str | None:
        try:
            path = str(node.path()).strip()
        except Exception:
            return None
        parts = [part for part in path.split("/") if part]
        if not parts:
            return None
        if parts[0] == "obj" and len(parts) >= 2:
            return "/obj/" + parts[1]
        if parts[0] in {"mat", "stage", "tasks", "out", "ch", "img"}:
            return "/" + parts[0]
        return "/" + parts[0]

    @staticmethod
    def _node_key(node: Any) -> int:
        try:
            return int(node.sessionId())
        except Exception:
            return id(node)

    @staticmethod
    def _node_event_types() -> tuple[Any, ...]:
        if hou is None:
            return ()
        names = (
            "AppearanceChanged",
            "BeingDeleted",
            "ChildCreated",
            "ChildDeleted",
            "ChildReordered",
            "CustomDataChanged",
            "FlagChanged",
            "IndirectInputCreated",
            "IndirectInputDeleted",
            "IndirectInputRewired",
            "InputRewired",
            "NameChanged",
            "ParmTupleAnimated",
            "ParmTupleChanged",
            "ParmTupleChannelChanged",
            "PositionChanged",
            "SpareParmTemplatesChanged",
        )
        event_type = getattr(hou, "nodeEventType", None)
        return tuple(value for name in names if (value := getattr(event_type, name, None)) is not None)

    def _observe_node(self, node: Any) -> None:
        key = self._node_key(node)
        if key in self._observed_nodes:
            return
        event_types = self._node_event_types()
        if not event_types:
            return
        try:
            node.addEventCallback(event_types, self._on_node_event)
        except Exception:
            self._logger.debug("unable to observe node events", exc_info=True)
            return
        self._observed_nodes[key] = node

    def _observe_subtree(self, node: Any) -> None:
        self._observe_node(node)
        try:
            descendants = node.allSubChildren()
        except Exception:
            descendants = ()
        for descendant in descendants:
            self._observe_node(descendant)

    def _install_node_callbacks(self) -> bool:
        if hou is None or self._node_callbacks_installed:
            return self._node_callbacks_installed
        try:
            root = hou.node("/")
            if root is None:
                return False
            self._observe_subtree(root)
            self._node_callbacks_installed = bool(self._observed_nodes)
            if self._node_callbacks_installed:
                self._logger.info("node callbacks installed count=%s", len(self._observed_nodes))
            return self._node_callbacks_installed
        except Exception:
            self._logger.warning("node callbacks unavailable in this context", exc_info=True)
            return False

    def _on_node_event(self, node: Any, event_type: Any, **kwargs: Any) -> None:
        event_name = str(event_type)
        try:
            event_name = str(event_type.name())
        except Exception:
            pass
        if event_name.endswith("ChildCreated"):
            child = kwargs.get("child_node") or kwargs.get("child")
            if child is not None:
                self._observe_subtree(child)
        scope_path = self._node_scope_path(node)
        self._bump(f"node:{event_name}", scope_path=scope_path)
        if event_name.endswith("BeingDeleted"):
            self._observed_nodes.pop(self._node_key(node), None)

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
                "nodeCallbacksInstalled": self._node_callbacks_installed,
                "observedNodeCount": len(self._observed_nodes),
                "sceneDirtyRevision": self._scene_dirty_revision,
                "dirtyScopeCount": len(self._dirty_scopes),
                "dirtyScopes": dict(self._dirty_scopes),
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
