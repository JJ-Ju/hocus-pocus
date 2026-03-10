"""Main-thread dispatch and serialization helpers for Houdini work."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import CancelledError, Future, TimeoutError
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from typing import Any, Callable

from hocuspocus.core.jsonrpc import JsonRpcError

from .context import OperationCancelledError, RequestContext

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore

try:
    import hdefereval  # type: ignore
except ImportError:  # pragma: no cover - exercised outside graphical Houdini
    hdefereval = None  # type: ignore


class DispatchMode(str, Enum):
    UI_CALLBACK = "ui_callback"
    SYNCHRONOUS = "synchronous"


class OperationState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class QueuedCommand:
    callback: Callable[[], Any]
    context: RequestContext
    future: Future[Any]
    enqueued_at: float


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    method: str
    caller_id: str
    state: OperationState
    enqueued_at: float
    started_at: float | None = None
    finished_at: float | None = None
    request_id: str | None = None
    error: str | None = None
    cancel_requested: bool = False


class LiveCommandDispatcher:
    def __init__(self, logger: logging.Logger):
        self._logger = logger.getChild("live.dispatcher")
        self._queue: Queue[QueuedCommand | None] = Queue()
        self._execution_lock = threading.RLock()
        self._schedule_lock = threading.Lock()
        self._operations_lock = threading.Lock()
        self._pump_scheduled = False
        self._started = False
        self._mode = self._detect_mode()
        self._operations: dict[str, OperationRecord] = {}
        self._contexts: dict[str, RequestContext] = {}
        self._worker_thread: threading.Thread | None = None
        self._worker_stop = threading.Event()

    @staticmethod
    def _detect_mode() -> DispatchMode:
        if hou is not None:
            try:
                if hou.isUIAvailable():
                    return DispatchMode.UI_CALLBACK
            except Exception:
                pass
        return DispatchMode.SYNCHRONOUS

    @property
    def mode(self) -> str:
        return self._mode.value

    def start(self) -> None:
        self._started = True
        if self._mode == DispatchMode.SYNCHRONOUS and self._worker_thread is None:
            self._worker_stop.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="HocusPocusLiveWorker",
                daemon=True,
            )
            self._worker_thread.start()
        self._logger.info("dispatcher started in %s mode", self._mode.value)

    def stop(self) -> None:
        self._started = False
        if self._mode == DispatchMode.SYNCHRONOUS and self._worker_thread is not None:
            self._worker_stop.set()
            self._queue.put(None)
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None
        self._logger.info("dispatcher stopped")

    def submit(self, callback: Callable[[], Any], context: RequestContext) -> Future[Any]:
        future: Future[Any] = Future()
        command = QueuedCommand(
            callback=callback,
            context=context,
            future=future,
            enqueued_at=time.time(),
        )
        self._record_new_operation(context, command.enqueued_at)

        if self._mode == DispatchMode.UI_CALLBACK:
            self._submit_ui_command(command)
            return future

        self._queue.put(command)
        return future

    def call(self, callback: Callable[[], Any], context: RequestContext) -> Any:
        future = self.submit(callback, context)
        try:
            return future.result(timeout=context.timeout_seconds)
        except TimeoutError:
            self.cancel(context.operation_id)
            raise
        except CancelledError as exc:
            raise OperationCancelledError(
                f"Operation {context.operation_id} was cancelled."
            ) from exc

    def cancel(self, operation_id: str) -> bool:
        with self._operations_lock:
            record = self._operations.get(operation_id)
        if record is None:
            return False

        context = self._contexts.get(operation_id)
        if context is not None:
            context.cancel()
        self._logger.info("cancellation requested for %s", operation_id)

        command = self._find_queued_command(operation_id)
        if command is not None:
            command.context.cancel()
            if command.future.cancel():
                self._finish_operation(operation_id, OperationState.CANCELLED)
                return True

        self._set_state(operation_id, OperationState.CANCELLING)
        self._mark_cancel_requested(operation_id)
        return True

    def cancel_by_request_id(self, request_id: str) -> bool:
        with self._operations_lock:
            for operation_id, record in self._operations.items():
                if record.request_id == request_id and record.state in {
                    OperationState.QUEUED,
                    OperationState.RUNNING,
                    OperationState.CANCELLING,
                }:
                    return self.cancel(operation_id)
        return False

    def operations_snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._operations_lock:
            ordered = sorted(
                self._operations.values(),
                key=lambda item: item.enqueued_at,
                reverse=True,
            )
            snapshot = ordered[:limit]
            return [self._record_payload(record) for record in snapshot]

    def operation_snapshot(self, operation_id: str) -> dict[str, Any] | None:
        with self._operations_lock:
            record = self._operations.get(operation_id)
            if record is None:
                return None
            return self._record_payload(record)

    def _schedule_pump(self) -> None:
        if hou is None:
            return
        with self._schedule_lock:
            if self._pump_scheduled:
                return
            self._pump_scheduled = True
        hou.ui.postEventCallback(self._drain_queue)

    def _drain_queue(self) -> None:
        with self._schedule_lock:
            self._pump_scheduled = False

        while True:
            try:
                command = self._queue.get_nowait()
            except Empty:
                break
            if command is None:
                break
            self._execute(command)

        if not self._queue.empty():
            self._schedule_pump()

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            command = self._queue.get()
            if command is None:
                break
            self._execute(command)

    def _submit_ui_command(self, command: QueuedCommand) -> None:
        worker = threading.Thread(
            target=self._run_ui_command,
            args=(command,),
            name=f"HocusPocusUI:{command.context.operation_id}",
            daemon=True,
        )
        worker.start()

    def _run_ui_command(self, command: QueuedCommand) -> None:
        if command.future.cancelled() or command.context.is_cancelled():
            self._finish_operation(command.context.operation_id, OperationState.CANCELLED)
            command.future.cancel()
            return

        if hdefereval is None or hou is None:
            self._execute(command)
            return

        try:
            hdefereval.executeInMainThreadWithResult(self._execute, command)
        except Exception as exc:
            if not command.future.done():
                self._finish_operation(
                    command.context.operation_id,
                    OperationState.FAILED,
                    error=str(exc),
                )
                command.future.set_exception(exc)

    def _execute(self, command: QueuedCommand) -> None:
        if command.future.cancelled() or command.context.is_cancelled():
            self._finish_operation(command.context.operation_id, OperationState.CANCELLED)
            return
        started_at = time.time()
        self._start_operation(command.context.operation_id, started_at)
        try:
            with self._execution_lock:
                wait_time = time.time() - command.enqueued_at
                if wait_time > 0.25:
                    self._logger.warning(
                        "operation %s waited %.3fs before execution",
                        command.context.operation_id,
                        wait_time,
                    )
                command.context.raise_if_cancelled()
                result = command.callback()
        except OperationCancelledError as exc:
            self._finish_operation(
                command.context.operation_id,
                OperationState.CANCELLED,
                error=str(exc),
            )
            command.future.set_exception(exc)
            return
        except JsonRpcError as exc:
            self._finish_operation(
                command.context.operation_id,
                OperationState.FAILED,
                error=str(exc),
            )
            command.future.set_exception(exc)
            self._logger.info(
                "operation %s failed with request error: %s",
                command.context.operation_id,
                exc,
            )
            return
        except Exception as exc:
            self._finish_operation(
                command.context.operation_id,
                OperationState.FAILED,
                error=str(exc),
            )
            command.future.set_exception(exc)
            self._logger.exception("operation %s failed", command.context.operation_id)
            return

        elapsed = time.time() - started_at
        if elapsed > 0.25:
            self._logger.warning(
                "operation %s executed in %.3fs",
                command.context.operation_id,
                elapsed,
            )
        self._finish_operation(command.context.operation_id, OperationState.SUCCEEDED)
        command.future.set_result(result)

    def _record_new_operation(self, context: RequestContext, enqueued_at: float) -> None:
        request_id = context.metadata.get("requestId")
        record = OperationRecord(
            operation_id=context.operation_id,
            method=str(context.metadata.get("method", "unknown")),
            caller_id=context.caller_id,
            state=OperationState.QUEUED,
            enqueued_at=enqueued_at,
            request_id=str(request_id) if request_id is not None else None,
        )
        with self._operations_lock:
            self._operations[context.operation_id] = record
            self._contexts[context.operation_id] = context
            self._prune_history_locked()

    def _start_operation(self, operation_id: str, started_at: float) -> None:
        with self._operations_lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            record.state = OperationState.RUNNING
            record.started_at = started_at

    def _finish_operation(
        self,
        operation_id: str,
        state: OperationState,
        *,
        error: str | None = None,
    ) -> None:
        with self._operations_lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            record.state = state
            record.finished_at = time.time()
            record.error = error
            if state in {
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.CANCELLED,
            }:
                self._contexts.pop(operation_id, None)

    def _set_state(self, operation_id: str, state: OperationState) -> None:
        with self._operations_lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            record.state = state

    def _mark_cancel_requested(self, operation_id: str) -> None:
        with self._operations_lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            record.cancel_requested = True

    def _find_queued_command(self, operation_id: str) -> QueuedCommand | None:
        with self._queue.mutex:
            for command in list(self._queue.queue):
                if command.context.operation_id == operation_id:
                    return command
        return None

    def _prune_history_locked(self) -> None:
        if len(self._operations) <= 200:
            return
        completed = [
            key
            for key, value in sorted(
                self._operations.items(),
                key=lambda item: item[1].enqueued_at,
            )
            if value.state
            in {
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.CANCELLED,
            }
        ]
        while len(self._operations) > 200 and completed:
            self._operations.pop(completed.pop(0), None)

    @staticmethod
    def _record_payload(record: OperationRecord) -> dict[str, Any]:
        return {
            "operationId": record.operation_id,
            "requestId": record.request_id,
            "method": record.method,
            "callerId": record.caller_id,
            "state": record.state.value,
            "cancelRequested": record.cancel_requested,
            "enqueuedAt": record.enqueued_at,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
            "error": record.error,
        }
