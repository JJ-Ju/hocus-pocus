"""Per-process host identity and generation-scoping contract."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator
from uuid import uuid4


class HostIdentity:
    """Identity pair brokers use to distinguish restarts and replacements."""

    def __init__(self) -> None:
        self._instance_id = str(uuid4())
        self._generation = 1
        self._condition = threading.Condition()
        self._active_leases = 0
        self._advancing = False
        self._waiting_advances = 0

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    @contextmanager
    def dispatch_lease(self) -> Iterator[None]:
        with self._condition:
            while self._advancing or self._waiting_advances:
                self._condition.wait()
            self._active_leases += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_leases -= 1
                if self._active_leases == 0:
                    self._condition.notify_all()

    def advance_exclusive(self, transition: Callable[[], None]) -> int:
        with self._condition:
            self._waiting_advances += 1
            try:
                while self._advancing:
                    self._condition.wait()
            finally:
                self._waiting_advances -= 1
            self._advancing = True
            try:
                while self._active_leases:
                    self._condition.wait()
                transition()
                self._generation += 1
                return self._generation
            finally:
                self._advancing = False
                self._condition.notify_all()

    def payload(self) -> dict[str, object]:
        return {
            "hostInstanceId": self.instance_id,
            "hostGeneration": self.generation,
            "generationScope": {
                "sessions": True,
                "checkouts": True,
                "liveResources": True,
                "durableApplyPlans": False,
                "durableRecovery": False,
            },
            "brokerSessionResume": {
                "header": "HocusPocus-Broker-Session-Id",
                "principalBound": True,
                "clientInfoBound": True,
                "finiteExpiry": True,
                "sessionGrantsRetained": True,
            },
            "mutationReplaySupported": False,
        }

    def headers(self) -> tuple[tuple[str, str], ...]:
        return (
            ("HocusPocus-Host-Instance-Id", self.instance_id),
            ("HocusPocus-Host-Generation", str(self.generation)),
        )


__all__ = ["HostIdentity"]
