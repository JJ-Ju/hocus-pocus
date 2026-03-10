"""Request context objects."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


class OperationCancelledError(RuntimeError):
    """Raised when a live operation is cancelled."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = dict(payload or {})


@dataclass(slots=True)
class RequestContext:
    caller_id: str = "unknown"
    permissions: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelledError(f"Operation {self.operation_id} was cancelled.")
