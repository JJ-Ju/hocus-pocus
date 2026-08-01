"""Bounded framing, synchronized output, and worker lanes for stdio MCP."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_HEADER_COUNT = 32
WORKER_SHUTDOWN_SECONDS = 2.0
_WORKER_COUNT = 4
_WORK_QUEUE_SIZE = 64
_CONTROL_QUEUE_SIZE = 64
_CONTROL_METHODS = {
    "notifications/cancelled",
    "notifications/initialized",
}


class BridgeInputError(Exception):
    def __init__(self, message: str, framing: str = "newline"):
        super().__init__(message)
        self.framing = framing


@dataclass(frozen=True, slots=True)
class InboundMessage:
    payload: Any
    framing: str


def _parse_json(raw: bytes, framing: str) -> InboundMessage:
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise BridgeInputError("Invalid or oversized MCP message.", framing)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeInputError("Invalid JSON.", framing) from exc
    return InboundMessage(payload, framing)


def _read_content_length_message(
    source: BinaryIO,
    first: bytes,
) -> InboundMessage:
    headers: dict[str, str] = {}
    header_bytes = len(first)
    line = first
    for _ in range(MAX_HEADER_COUNT):
        try:
            name, value = line.decode("ascii").split(":", 1)
        except (UnicodeDecodeError, ValueError) as exc:
            raise BridgeInputError("Invalid MCP framing header.", "content-length") from exc
        headers[name.strip().lower()] = value.strip()
        line = source.readline(MAX_HEADER_BYTES + 1)
        header_bytes += len(line)
        if header_bytes > MAX_HEADER_BYTES:
            raise BridgeInputError("MCP framing headers are oversized.", "content-length")
        if line in {b"\r\n", b"\n"}:
            break
        if not line:
            raise BridgeInputError("Incomplete MCP framing headers.", "content-length")
    else:
        raise BridgeInputError("Too many MCP framing headers.", "content-length")

    raw_length = headers.get("content-length", "")
    if not raw_length.isascii() or not raw_length.isdigit():
        raise BridgeInputError("Invalid Content-Length.", "content-length")
    content_length = int(raw_length)
    if content_length <= 0 or content_length > MAX_MESSAGE_BYTES:
        raise BridgeInputError("Invalid or oversized Content-Length.", "content-length")
    body = source.read(content_length)
    if len(body) != content_length:
        raise BridgeInputError("Incomplete MCP message.", "content-length")
    return _parse_json(body, "content-length")


def read_message(stream: BinaryIO | None = None) -> InboundMessage | None:
    source = stream or sys.stdin.buffer
    first = source.readline(MAX_MESSAGE_BYTES + 1)
    while first in {b"\r\n", b"\n"}:
        first = source.readline(MAX_MESSAGE_BYTES + 1)
    if not first:
        return None
    if len(first) > MAX_MESSAGE_BYTES:
        raise BridgeInputError("MCP message exceeds the transport limit.")
    if first.lower().startswith(b"content-length:"):
        return _read_content_length_message(source, first)
    return _parse_json(first.rstrip(b"\r\n"), "newline")


def write_message(
    payload: Any,
    framing: str = "newline",
    stream: BinaryIO | None = None,
) -> None:
    target = stream or sys.stdout.buffer
    body = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if framing == "content-length":
        target.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        target.write(body)
    else:
        target.write(body + b"\n")
    target.flush()


def _internal_error_response(payload: Any) -> Any:
    rows = payload if isinstance(payload, list) else [payload]
    responses = [
        {
            "jsonrpc": "2.0",
            "id": row.get("id") if isinstance(row, dict) else None,
            "error": {
                "code": -32603,
                "message": "Broker request failed.",
                "data": {"retryable": False},
            },
        }
        for row in rows
        if not isinstance(row, dict) or row.get("id") is not None
    ]
    if isinstance(payload, list):
        return responses
    return responses[0] if responses else None


def _busy_response(payload: Any) -> Any:
    rows = payload if isinstance(payload, list) else [payload]
    responses = [
        {
            "jsonrpc": "2.0",
            "id": row.get("id"),
            "error": {
                "code": -32099,
                "message": "HocusPocus broker is busy.",
                "data": {
                    "hocusCode": "HOCUS999",
                    "kind": "broker_busy",
                    "retryable": True,
                },
            },
        }
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    ]
    if isinstance(payload, list):
        return responses
    return responses[0] if responses else None


def _is_control_payload(payload: Any) -> bool:
    rows = payload if isinstance(payload, list) else [payload]
    return bool(rows) and all(
        isinstance(row, dict) and row.get("method") in _CONTROL_METHODS
        for row in rows
    )


class ProtocolWriter:
    def __init__(self, stream: BinaryIO | None = None):
        self._stream = stream or sys.stdout.buffer
        self._lock = threading.Lock()
        self._framing = "newline"
        self._closed = False

    def set_framing(self, framing: str) -> None:
        with self._lock:
            self._framing = framing

    def write(self, payload: Any, framing: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            write_message(payload, framing or self._framing, self._stream)

    def notify(self, payload: Any) -> None:
        self.write(payload)

    def close(self) -> None:
        with self._lock:
            self._closed = True


@dataclass(frozen=True, slots=True)
class _WorkItem:
    payload: Any
    framing: str


class BrokerWorkers:
    def __init__(
        self,
        handler: Callable[[Any], Any],
        close_handler: Callable[[], None],
        writer: ProtocolWriter,
        *,
        worker_count: int = _WORKER_COUNT,
        queue_size: int = _WORK_QUEUE_SIZE,
    ):
        self._handler = handler
        self._close_handler = close_handler
        self._writer = writer
        self._queue: queue.Queue[_WorkItem | None] = queue.Queue(maxsize=queue_size)
        self._control_queue: queue.Queue[_WorkItem | None] = queue.Queue(
            maxsize=_CONTROL_QUEUE_SIZE
        )
        self._threads = [
            threading.Thread(
                target=self._work,
                args=(self._queue,),
                name=f"HocusPocusBrokerWorker-{index}",
                daemon=True,
            )
            for index in range(worker_count)
        ]
        self._control_thread = threading.Thread(
            target=self._work,
            args=(self._control_queue,),
            name="HocusPocusBrokerControl",
            daemon=True,
        )
        for thread in self._threads:
            thread.start()
        self._control_thread.start()

    def submit(self, inbound: InboundMessage) -> None:
        self._writer.set_framing(inbound.framing)
        item = _WorkItem(inbound.payload, inbound.framing)
        if _is_control_payload(inbound.payload):
            self._control_queue.put(item)
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            response = _busy_response(inbound.payload)
            if response is not None:
                self._writer.write(response, inbound.framing)

    def _work(self, work_queue: queue.Queue[_WorkItem | None]) -> None:
        while True:
            item = work_queue.get()
            try:
                if item is None:
                    return
                try:
                    response = self._handler(item.payload)
                except Exception:
                    response = _internal_error_response(item.payload)
                if response is not None:
                    self._writer.write(response, item.framing)
            finally:
                work_queue.task_done()

    def close(self) -> None:
        self._close_handler()
        for _ in self._threads:
            try:
                self._queue.put(None, timeout=0.05)
            except queue.Full:
                break
        try:
            self._control_queue.put(None, timeout=0.05)
        except queue.Full:
            pass
        deadline = time.monotonic() + WORKER_SHUTDOWN_SECONDS
        for thread in [*self._threads, self._control_thread]:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._writer.close()
