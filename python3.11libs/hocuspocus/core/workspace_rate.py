"""Small in-process rate and concurrency hooks for H6 workspace operations."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class WorkspaceRateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class _Window:
    duration: float
    events: deque[float]


_RESOURCE_SCOPE = object()
_DENIAL_SCOPE = object()
_PRUNE_BUDGET = 64
_MAX_RATE_BUCKETS = 65_536
_RateKey = tuple[object, ...]
_RateRequirement = tuple[_RateKey, int, float]


class WorkspaceRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._windows: OrderedDict[_RateKey, _Window] = OrderedDict()
        self._active_builds: dict[tuple[str, str], int] = {}
        self._active_session_builds: dict[str, int] = {}

    def require(
        self,
        key: _RateKey,
        *,
        limit: int,
        window_seconds: float,
    ) -> None:
        self.require_many(((key, limit, window_seconds),))

    def require_scoped(
        self,
        principal_id: str,
        session_id: str,
        project_id: str | None,
        *,
        total_limit: int,
        category: str | None = None,
        category_limit: int | None = None,
        denied: bool = False,
        window_seconds: float,
    ) -> None:
        scope = (
            _DENIAL_SCOPE
            if denied
            else _RESOURCE_SCOPE if project_id is None else project_id
        )
        requirements: list[_RateRequirement] = [
            ((principal_id, session_id, scope, "total"), total_limit, window_seconds)
        ]
        if category is not None and category_limit is not None:
            requirements.append(
                (
                    (principal_id, session_id, scope, category),
                    category_limit,
                    window_seconds,
                )
            )
        self.require_many(tuple(requirements))

    def require_many(self, requirements: tuple[_RateRequirement, ...]) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            pending: list[tuple[_RateKey, _Window]] = []
            new_keys: set[_RateKey] = set()
            for key, limit, duration in requirements:
                if limit < 1 or duration <= 0:
                    raise ValueError("Rate limits and durations must be positive.")
                window = self._windows.get(key)
                if window is not None:
                    if window.duration != duration:
                        window = _Window(duration, deque(window.events))
                    _prune_window(window, now)
                    if not window.events:
                        self._windows.pop(key, None)
                        window = None
                if window is None:
                    window = _Window(duration, deque())
                if len(window.events) >= limit:
                    raise WorkspaceRateError(
                        "HOCUS919", "Workspace request rate limit exceeded."
                    )
                pending.append((key, window))
                if key not in self._windows:
                    new_keys.add(key)
            if len(self._windows) + len(new_keys) > _MAX_RATE_BUCKETS:
                raise WorkspaceRateError(
                    "HOCUS919", "Workspace request rate limit exceeded."
                )
            for key, window in pending:
                window.events.append(now)
                self._windows[key] = window
                self._windows.move_to_end(key)

    def _prune(self, now: float) -> None:
        for _ in range(min(len(self._windows), _PRUNE_BUDGET)):
            key, window = self._windows.popitem(last=False)
            _prune_window(window, now)
            if window.events:
                self._windows[key] = window

    @contextmanager
    def build_slot(
        self,
        session_id: str,
        project_id: str,
        *,
        per_project: int = 1,
        per_session: int = 2,
    ) -> Iterator[None]:
        key = (session_id, project_id)
        self._enter_build(key, session_id, per_project, per_session)
        try:
            yield
        finally:
            self._leave_build(key, session_id)

    def _enter_build(
        self,
        key: tuple[str, str],
        session_id: str,
        per_project: int,
        per_session: int,
    ) -> None:
        with self._lock:
            project_count = self._active_builds.get(key, 0)
            session_count = self._active_session_builds.get(session_id, 0)
            if project_count >= per_project or session_count >= per_session:
                raise WorkspaceRateError(
                    "HOCUS920", "Workspace build concurrency limit exceeded."
                )
            self._active_builds[key] = project_count + 1
            self._active_session_builds[session_id] = session_count + 1

    def _leave_build(self, key: tuple[str, str], session_id: str) -> None:
        with self._lock:
            _decrement(self._active_builds, key)
            _decrement(self._active_session_builds, session_id)


def _decrement(mapping, key) -> None:
    value = mapping.get(key, 0) - 1
    if value <= 0:
        mapping.pop(key, None)
    else:
        mapping[key] = value


def _prune_window(window: _Window, now: float) -> None:
    cutoff = now - window.duration
    while window.events and window.events[0] <= cutoff:
        window.events.popleft()


__all__ = ["WorkspaceRateError", "WorkspaceRateLimiter"]
