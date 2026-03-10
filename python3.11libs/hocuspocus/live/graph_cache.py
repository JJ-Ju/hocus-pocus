"""Revision-aware in-memory scene graph cache."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable


class LiveSceneGraphCache:
    def __init__(self, logger: logging.Logger):
        self._logger = logger.getChild("live.graph")
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._revision = -1
        self._built_at = 0.0
        self._refresh_count = 0
        self._last_build_ms = 0.0

    def get_or_refresh(
        self,
        *,
        revision: int,
        builder: Callable[[], dict[str, Any]],
        max_age_seconds: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            is_fresh = True
            if max_age_seconds is not None and self._snapshot is not None:
                is_fresh = (time.time() - self._built_at) <= max_age_seconds
            if self._snapshot is not None and self._revision == revision and is_fresh:
                return self._snapshot

        started = time.time()
        snapshot = builder()
        duration_ms = (time.time() - started) * 1000.0
        with self._lock:
            self._snapshot = snapshot
            self._revision = revision
            self._built_at = time.time()
            self._refresh_count += 1
            self._last_build_ms = duration_ms
        self._logger.info(
            "scene graph refreshed revision=%s nodes=%s parms=%s edges=%s buildMs=%.2f",
            revision,
            snapshot.get("stats", {}).get("nodeCount"),
            snapshot.get("stats", {}).get("parmCount"),
            snapshot.get("stats", {}).get("edgeCount"),
            duration_ms,
        )
        return snapshot

    def stats(self) -> dict[str, Any]:
        with self._lock:
            node_count = 0
            parm_count = 0
            edge_count = 0
            if self._snapshot is not None:
                stats = self._snapshot.get("stats", {})
                node_count = int(stats.get("nodeCount", 0))
                parm_count = int(stats.get("parmCount", 0))
                edge_count = int(stats.get("edgeCount", 0))
            return {
                "cached": self._snapshot is not None,
                "revision": self._revision if self._snapshot is not None else None,
                "builtAt": self._built_at if self._snapshot is not None else None,
                "refreshCount": self._refresh_count,
                "lastBuildMs": self._last_build_ms,
                "nodeCount": node_count,
                "parmCount": parm_count,
                "edgeCount": edge_count,
            }
