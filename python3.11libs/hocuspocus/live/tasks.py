"""Background task registry for long-running Houdini work."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from .context import OperationCancelledError, RequestContext
from .dispatcher import LiveCommandDispatcher

TaskRunner = Callable[["TaskController"], dict[str, Any]]


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TaskLogEntry:
    timestamp: float
    level: str
    message: str


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    task_type: str
    title: str
    caller_id: str
    permissions: tuple[str, ...]
    metadata: dict[str, Any]
    state: TaskState
    created_at: float
    progress: float = 0.0
    progress_message: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    active_operation_id: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    logs: list[TaskLogEntry] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)


class TaskController:
    def __init__(self, manager: "LiveTaskManager", task_id: str):
        self._manager = manager
        self.task_id = task_id

    def log(self, message: str, *, level: str = "info") -> None:
        self._manager._append_log(self.task_id, level, message)

    def set_progress(self, value: float, message: str | None = None) -> None:
        self._manager._set_progress(self.task_id, value, message)

    def is_cancelled(self) -> bool:
        record = self._manager._record(self.task_id)
        return record.cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OperationCancelledError(f"Task {self.task_id} was cancelled.")

    def run_live(
        self,
        callback: Callable[[], Any],
        *,
        operation_label: str,
        timeout_seconds: float = 600.0,
    ) -> Any:
        record = self._manager._record(self.task_id)
        self.raise_if_cancelled()
        operation_id = f"task:{self.task_id}:{operation_label}"
        context = RequestContext(
            caller_id=record.caller_id,
            permissions=record.permissions,
            timeout_seconds=timeout_seconds,
            metadata={
                "method": f"task.{record.task_type}",
                "taskId": self.task_id,
            },
            operation_id=operation_id,
            cancel_event=record.cancel_event,
        )
        self._manager._set_active_operation(self.task_id, operation_id)
        try:
            return self._manager._dispatcher.call(callback, context)
        finally:
            self._manager._clear_active_operation(self.task_id, operation_id)


class LiveTaskManager:
    def __init__(self, dispatcher: LiveCommandDispatcher, logger: logging.Logger):
        self._dispatcher = dispatcher
        self._logger = logger.getChild("live.tasks")
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._threads: dict[str, threading.Thread] = {}

    def submit(
        self,
        *,
        task_type: str,
        title: str,
        caller_id: str,
        permissions: tuple[str, ...],
        metadata: dict[str, Any] | None,
        runner: TaskRunner,
    ) -> dict[str, Any]:
        task_id = uuid4().hex
        created_at = time.time()
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            title=title,
            caller_id=caller_id,
            permissions=permissions,
            metadata=dict(metadata or {}),
            state=TaskState.QUEUED,
            created_at=created_at,
        )
        with self._lock:
            self._tasks[task_id] = record
            self._prune_history_locked()

        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, runner),
            name=f"HocusPocusTask-{task_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._threads[task_id] = thread
        thread.start()
        return self.snapshot(task_id) or {"taskId": task_id}

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return False
            record.cancel_requested = True
            record.cancel_event.set()
            operation_id = record.active_operation_id
        if operation_id:
            self._dispatcher.cancel(operation_id)
        self._append_log(task_id, "warning", "Cancellation requested.")
        return True

    def snapshot(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            return self._payload(record)

    def snapshots(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(
                self._tasks.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return [self._payload(record) for record in ordered[:limit]]

    def log_payload(self, task_id: str, *, limit: int = 200) -> dict[str, Any] | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            entries = [
                {
                    "timestamp": entry.timestamp,
                    "level": entry.level,
                    "message": entry.message,
                }
                for entry in record.logs[-limit:]
            ]
            return {
                "taskId": task_id,
                "count": len(entries),
                "entries": entries,
            }

    def _run_task(self, task_id: str, runner: TaskRunner) -> None:
        controller = TaskController(self, task_id)
        with self._lock:
            record = self._tasks[task_id]
            record.state = TaskState.RUNNING
            record.started_at = time.time()
            record.progress = max(record.progress, 1.0)
        controller.log(f"Task started: {record.title}")

        try:
            result = runner(controller)
            controller.raise_if_cancelled()
        except OperationCancelledError as exc:
            with self._lock:
                record = self._tasks[task_id]
                record.state = TaskState.CANCELLED
                record.finished_at = time.time()
                record.error = {"message": str(exc)}
                record.progress_message = "Cancelled"
            controller.log(str(exc), level="warning")
        except Exception as exc:
            with self._lock:
                record = self._tasks[task_id]
                record.state = TaskState.FAILED
                record.finished_at = time.time()
                record.error = {"message": str(exc)}
                record.progress_message = "Failed"
            controller.log(str(exc), level="error")
            self._logger.exception("task %s failed", task_id)
        else:
            with self._lock:
                record = self._tasks[task_id]
                record.state = TaskState.SUCCEEDED
                record.finished_at = time.time()
                record.result = result
                record.progress = 100.0
                if not record.progress_message:
                    record.progress_message = "Completed"
            controller.log("Task completed successfully.")
        finally:
            with self._lock:
                self._threads.pop(task_id, None)

    def _record(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise OperationCancelledError(f"Task {task_id} no longer exists.")
            return record

    def _append_log(self, task_id: str, level: str, message: str) -> None:
        timestamp = time.time()
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.logs.append(
                TaskLogEntry(timestamp=timestamp, level=level, message=message)
            )
            if len(record.logs) > 200:
                record.logs = record.logs[-200:]

    def _set_progress(self, task_id: str, value: float, message: str | None) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.progress = max(0.0, min(100.0, float(value)))
            if message is not None:
                record.progress_message = message

    def _set_active_operation(self, task_id: str, operation_id: str) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is not None:
                record.active_operation_id = operation_id

    def _clear_active_operation(self, task_id: str, operation_id: str) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is not None and record.active_operation_id == operation_id:
                record.active_operation_id = None

    def _prune_history_locked(self) -> None:
        if len(self._tasks) <= 200:
            return
        completed = [
            key
            for key, value in sorted(
                self._tasks.items(),
                key=lambda item: item[1].created_at,
            )
            if value.state in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED}
        ]
        while len(self._tasks) > 200 and completed:
            key = completed.pop(0)
            self._tasks.pop(key, None)
            self._threads.pop(key, None)

    @staticmethod
    def _payload(record: TaskRecord) -> dict[str, Any]:
        return {
            "taskId": record.task_id,
            "taskType": record.task_type,
            "title": record.title,
            "callerId": record.caller_id,
            "state": record.state.value,
            "progress": record.progress,
            "progressMessage": record.progress_message,
            "createdAt": record.created_at,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
            "cancelRequested": record.cancel_requested,
            "activeOperationId": record.active_operation_id,
            "metadata": record.metadata,
            "result": record.result,
            "error": record.error,
        }
