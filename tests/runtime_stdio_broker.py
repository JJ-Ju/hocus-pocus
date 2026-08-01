from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from typing import Any
from unittest import mock

from hocuspocus.core.stdio_bridge import (
    StdioBroker,
    _BrokerCredential,
    _HttpFailure,
    _TransportFailure,
    _UpstreamResponse,
    _bounded_timeout,
    _proxy_headers,
)
from hocuspocus.core.settings import load_settings
from hocuspocus.core.stdio_runtime import (
    BrokerWorkers as _BrokerWorkers,
    InboundMessage as _InboundMessage,
    ProtocolWriter as _ProtocolWriter,
    read_message as _read_message,
    write_message as _write_message,
)
from tests.runtime_delivery_revision import assert_delivery_revision_contract


ROOT = Path(__file__).resolve().parents[1]


class _Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class _Host:
    def __init__(self):
        self.instance = "host-a"
        self.generation = "generation-1"
        self.session_id = "hws_" + "a" * 24
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.fail_next_tool = False
        self.offline = False
        self.guard_change_to: tuple[str, str] | None = None
        self.reject_resume_once = False

    def __call__(self, _url, _token, payload, **kwargs):
        request = dict(payload)
        self.calls.append((request, dict(kwargs)))
        if self.offline:
            raise _TransportFailure()
        method = request.get("method")
        if method == "initialize":
            if kwargs.get("broker_session_id") and self.reject_resume_once:
                self.reject_resume_once = False
                self.session_id = "hws_" + "b" * 24
                raise _HttpFailure(
                    409,
                    payload={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32002,
                            "message": "Broker session could not be resumed.",
                            "data": {
                                "hocusCode": "HOCUS910",
                                "kind": "broker_session_resume_rejected",
                                "reinitializeWithoutResume": True,
                            },
                        },
                    },
                    host_instance_id=self.instance,
                    host_generation=self.generation,
                )
            return _UpstreamResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "serverInfo": {"name": "test", "version": "1"},
                        "capabilities": {},
                    },
                },
                session_id=self.session_id,
                broker_session_id=self.session_id,
                host_instance_id=self.instance,
                host_generation=self.generation,
            )
        if self.guard_change_to is not None:
            changed_instance, changed_generation = self.guard_change_to
            self.guard_change_to = None
            self.instance = changed_instance
            self.generation = changed_generation
            raise _HttpFailure(
                409,
                payload={
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32099,
                        "message": "Host generation changed.",
                        "data": {
                            "hocusCode": "HOCUS999",
                            "kind": "host_generation_changed",
                        },
                    },
                },
                host_instance_id=changed_instance,
                host_generation=changed_generation,
            )
        if method == "notifications/initialized":
            return _UpstreamResponse(
                None,
                host_instance_id=self.instance,
                host_generation=self.generation,
            )
        if method == "tools/list":
            return self._result(request, {"tools": [{
                "name": "node.get", "annotations": {"readOnlyHint": True},
            }]})
        if method == "resources/list":
            return self._result(
                request,
                {"resources": [{"uri": "houdini://scene/summary"}]},
            )
        if method == "resources/templates/list":
            return self._result(request, {"resourceTemplates": []})
        if method == "tools/call" and self.fail_next_tool:
            self.fail_next_tool = False
            raise _TransportFailure()
        return self._result(request, {"ok": True})

    def _result(self, request, result):
        return _UpstreamResponse(
            {"jsonrpc": "2.0", "id": request.get("id"), "result": result},
            host_instance_id=self.instance,
            host_generation=self.generation,
        )


class _RotatingAuthHost(_Host):
    def __init__(self, expected_token: str):
        super().__init__()
        self.expected_token = expected_token
        self.tokens: list[str] = []

    def __call__(self, url, token, payload, **kwargs):
        self.tokens.append(token)
        if token != self.expected_token:
            raise _HttpFailure(401)
        return super().__call__(url, token, payload, **kwargs)


class _LateCredentialHost(_RotatingAuthHost):
    def __init__(self, expected_token: str):
        super().__init__(expected_token)
        self.block_next = False
        self.late_started = threading.Event()
        self.release_late = threading.Event()

    def __call__(self, url, token, payload, **kwargs):
        if not self.block_next or token != self.expected_token:
            return super().__call__(url, token, payload, **kwargs)
        self.block_next = False
        response = super().__call__(url, token, payload, **kwargs)
        self.late_started.set()
        self.release_late.wait(timeout=3)
        return response


class _BlockingHost(_Host):
    def __init__(self):
        super().__init__()
        self.tool_started = threading.Event()
        self.all_tools_started = threading.Event()
        self.release_tool = threading.Event()
        self.cancelled = threading.Event()
        self.pinged = threading.Event()
        self._started_count = 0
        self._started_lock = threading.Lock()

    def __call__(self, _url, _token, payload, **kwargs):
        method = payload.get("method")
        if method == "tools/call":
            self.calls.append((dict(payload), dict(kwargs)))
            self.tool_started.set()
            with self._started_lock:
                self._started_count += 1
                if self._started_count >= 4:
                    self.all_tools_started.set()
            if not self.release_tool.wait(timeout=3):
                raise _TransportFailure()
            return self._result(payload, {"toolFinished": True})
        if method == "notifications/cancelled":
            self.calls.append((dict(payload), dict(kwargs)))
            self.cancelled.set()
            return _UpstreamResponse(
                None,
                host_instance_id=self.instance,
                host_generation=self.generation,
            )
        if method == "ping":
            self.calls.append((dict(payload), dict(kwargs)))
            self.pinged.set()
            return self._result(payload, {})
        return super().__call__(_url, _token, payload, **kwargs)


class _Capture:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = bytearray()

    def write(self, value):
        with self._lock:
            self._data.extend(value)
        return len(value)

    @staticmethod
    def flush():
        return None

    def payloads(self):
        with self._lock:
            lines = bytes(self._data).splitlines()
        return [json.loads(line) for line in lines if line]


class _EpochHost(_Host):
    def __init__(self):
        super().__init__()
        self.old_started = threading.Barrier(3)
        self.release_old = threading.Event()

    def __call__(self, _url, _token, payload, **kwargs):
        name = payload.get("params", {}).get("name")
        if payload.get("method") == "tools/call" and name in {
            "old_fail",
            "old_success",
        }:
            old_instance = self.instance
            old_generation = self.generation
            self.calls.append((dict(payload), dict(kwargs)))
            self.old_started.wait(timeout=3)
            if not self.release_old.wait(timeout=3):
                raise _TransportFailure()
            if name == "old_fail":
                raise _TransportFailure()
            return _UpstreamResponse(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {"old": True},
                },
                host_instance_id=old_instance,
                host_generation=old_generation,
            )
        return super().__call__(_url, _token, payload, **kwargs)


def _request(request_id: int, method: str, params: dict | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _assert_framing_and_bounds(test: unittest.TestCase) -> None:
    payload = _request(1, "ping")
    newline = io.BytesIO(json.dumps(payload).encode() + b"\n")
    test.assertEqual(_read_message(newline).payload, payload)

    encoded = json.dumps(payload).encode()
    framed = io.BytesIO(
        f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded
    )
    inbound = _read_message(framed)
    test.assertEqual((inbound.payload, inbound.framing), (payload, "content-length"))
    output = io.BytesIO()
    _write_message(payload, "newline", output)
    test.assertEqual(json.loads(output.getvalue()), payload)
    test.assertEqual(_bounded_timeout("-1", 3.0), 3.0)
    test.assertEqual(_bounded_timeout("999", 3.0), 30.0)
    init_headers = _proxy_headers(
        body_length=2,
        token="token",
        payload=_request(2, "initialize"),
        session_id=None,
        protocol_version="2025-06-18",
        broker_session_id=None,
        host_instance_id="not-sent",
        host_generation="not-sent",
    )
    test.assertNotIn("HocusPocus-Broker-Session-Id", init_headers)
    test.assertNotIn("HocusPocus-Host-Instance-Id", init_headers)
    guard_headers = _proxy_headers(
        body_length=2,
        token="token",
        payload=_request(3, "tools/list"),
        session_id="upstream",
        protocol_version="2025-06-18",
        broker_session_id="not-sent",
        host_instance_id="host-a",
        host_generation="generation-1",
    )
    test.assertEqual(
        (
            guard_headers["HocusPocus-Host-Instance-Id"],
            guard_headers["HocusPocus-Host-Generation"],
        ),
        ("host-a", "generation-1"),
    )


def _assert_restart_and_ambiguity(test: unittest.TestCase) -> None:
    host = _Host()
    clock = _Clock()
    broker = StdioBroker(
        "http://host.invalid/mcp",
        "secret",
        proxy=host,
        clock=clock,
    )
    initialize = _request(
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    )
    test.assertIn("result", broker.handle(initialize))
    broker.handle(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
    )
    listed = broker.handle(_request(2, "tools/list"))
    test.assertEqual(listed["result"]["tools"][0]["name"], "node.get")
    initialize_broker_ids = [
        kwargs["broker_session_id"]
        for request, kwargs in host.calls
        if request.get("method") == "initialize"
    ]
    test.assertEqual(initialize_broker_ids, [None])

    host.fail_next_tool = True
    call = _request(3, "tools/call", {"name": "node.get", "arguments": {}})
    ambiguous = broker.handle(call)
    error = ambiguous["error"]
    test.assertEqual(error["code"], -32099)
    test.assertEqual(error["data"]["kind"], "ambiguous_delivery")
    test.assertEqual(error["data"]["toolName"], "node.get")
    operation_id = error["data"]["operationId"]
    test.assertRegex(operation_id, r"^op:[0-9a-f]{32}$")
    test.assertEqual(error["data"]["commitState"], "unknown")
    test.assertEqual(
        error["data"]["reconciliation"],
        {
            "tool": "session.get_operation",
            "arguments": {"operation_id": operation_id},
            "replaysMutation": False,
        },
    )
    failed_attempt = next(
        request for request, _ in reversed(host.calls)
        if request.get("method") == "tools/call"
    )
    test.assertEqual(failed_attempt["params"]["_operation_id"], operation_id)
    tool_attempts = sum(
        request.get("method") == "tools/call" for request, _ in host.calls
    )
    cached = broker.handle(_request(4, "tools/list"))
    test.assertEqual(cached["id"], 4)
    test.assertEqual(
        sum(request.get("method") == "tools/call" for request, _ in host.calls),
        tool_attempts,
    )

    clock.value += 1.0
    host.instance = "host-b"
    host.generation = "generation-2"
    resources = broker.handle(_request(5, "resources/list"))
    test.assertEqual(resources["result"]["resources"][0]["uri"], "houdini://scene/summary")
    test.assertEqual(broker.upstream_session_id, host.session_id)
    last_request, last_kwargs = host.calls[-1]
    test.assertEqual(last_request["method"], "resources/list")
    test.assertEqual(last_kwargs["session_id"], host.session_id)
    test.assertEqual(last_kwargs["host_instance_id"], "host-b")
    test.assertEqual(last_kwargs["host_generation"], "generation-2")

    host.guard_change_to = ("host-b", "generation-3")
    guarded = broker.handle(_request(6, "tools/call", {"name": "node.get"}))
    test.assertTrue(guarded["result"]["ok"])
    test.assertEqual(broker.host_instance_id, "host-b")
    test.assertEqual(broker.host_generation, "generation-3")
    test.assertEqual(broker.upstream_session_id, host.session_id)
    test.assertEqual(
        [(
            kwargs["host_instance_id"],
            kwargs["host_generation"],
        )
            for request, kwargs in host.calls
            if request.get("id") == 6
        ],
        [("host-b", "generation-2"), ("host-b", "generation-3")],
    )
    test.assertEqual(
        [
            kwargs["broker_session_id"]
            for request, kwargs in host.calls
            if request.get("method") == "initialize"
        ],
        [None, host.session_id, host.session_id],
    )
    host.guard_change_to = ("host-b", "generation-4")
    mutation = broker.handle(_request(61, "tools/call", {"name": "node.create"}))
    test.assertEqual(mutation["error"]["data"]["kind"], "host_generation_changed")
    test.assertEqual(
        sum(
            request.get("id") == 61
            for request, _kwargs in host.calls
        ),
        1,
    )
    test.assertEqual(broker.host_generation, "generation-4")
    test.assertIn(
        "result", broker.handle(_request(62, "tools/call", {"name": "node.create"}))
    )
    host.offline = True
    cached_after_failure = broker.handle(_request(7, "tools/list"))
    test.assertEqual(cached_after_failure["id"], 7)
    test.assertEqual(
        cached_after_failure["result"]["tools"][0]["name"],
        "node.get",
    )
    resources_offline = broker.handle(_request(8, "resources/list"))
    test.assertEqual(
        resources_offline["error"]["data"]["kind"],
        "host_offline",
    )


def _assert_offline_startup(test: unittest.TestCase) -> None:
    host = _Host()
    host.offline = True
    clock = _Clock()
    broker = StdioBroker(
        "http://host.invalid/mcp",
        "secret",
        proxy=host,
        clock=clock,
    )
    initialize = _request(
        20,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "offline-client", "version": "1"},
        },
    )
    response = broker.handle(initialize)
    test.assertFalse(response["result"]["hostOnline"])
    broker.handle(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
    )
    host.offline = False
    clock.value += 1.0
    listed = broker.handle(_request(21, "tools/list"))
    test.assertEqual(listed["result"]["tools"][0]["name"], "node.get")
    test.assertEqual(broker.upstream_session_id, host.session_id)
    test.assertEqual(
        [
            kwargs["broker_session_id"]
            for request, kwargs in host.calls
            if request.get("method") == "initialize"
        ],
        [None, None],
    )


def _assert_watcher_and_resume_replacement(test: unittest.TestCase) -> None:
    host = _Host()
    host.offline = True
    notifications: list[dict] = []
    broker = StdioBroker(
        "http://host.invalid/mcp",
        "secret",
        proxy=host,
        startup_wait_seconds=0.1,
        notify=notifications.append,
    )
    initialize = _request(
        30,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "watch-client", "version": "1"},
        },
    )
    offline_init = broker.handle(initialize)
    test.assertTrue(offline_init["result"]["capabilities"]["tools"]["listChanged"])
    first_list = broker.handle(_request(31, "tools/list"))
    test.assertEqual(first_list["error"]["data"]["kind"], "host_offline")
    host.offline = False
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not notifications:
        time.sleep(0.02)
    test.assertEqual(
        sum(
            item.get("method") == "notifications/tools/list_changed"
            for item in notifications
        ),
        1,
    )
    relisted = broker.handle(_request(32, "tools/list"))
    test.assertEqual(relisted["result"]["tools"][0]["name"], "node.get")
    broker.close()

    host = _Host()
    clock = _Clock()
    broker = StdioBroker(
        "http://host.invalid/mcp",
        "secret",
        proxy=host,
        clock=clock,
    )
    broker.handle(initialize)
    host.offline = True
    broker.handle(_request(33, "ping"))
    host.offline = False
    host.reject_resume_once = True
    clock.value += 1
    result = broker.handle(
        _request(34, "tools/call", {"name": "node.get"})
    )
    test.assertTrue(result["result"]["ok"])
    test.assertTrue(broker.session_authority_replaced)
    test.assertEqual(broker.upstream_session_id, "hws_" + "b" * 24)
    test.assertEqual(
        [
            kwargs["broker_session_id"]
            for request, kwargs in host.calls
            if request.get("method") == "initialize"
        ],
        [None, "hws_" + "a" * 24, None],
    )
    test.assertEqual(
        sum(request.get("id") == 34 for request, _ in host.calls),
        1,
    )


def _assert_worker_control_lane(test: unittest.TestCase) -> None:
    host = _BlockingHost()
    broker = StdioBroker("http://host.invalid/mcp", "secret", proxy=host)
    broker.handle(
        _request(
            40,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "worker-client", "version": "1"},
            },
        )
    )
    capture = _Capture()
    writer = _ProtocolWriter(capture)
    workers = _BrokerWorkers(
        broker.handle,
        broker.close,
        writer,
        worker_count=4,
        queue_size=8,
    )
    workers.submit(
        _InboundMessage(
            _request(41, "tools/call", {"name": "blocking-41"}),
            "newline",
        )
    )
    test.assertTrue(host.tool_started.wait(timeout=2))
    workers.submit(_InboundMessage(_request(45, "ping"), "newline"))
    test.assertTrue(host.pinged.wait(timeout=1))
    for request_id in range(42, 45):
        workers.submit(
            _InboundMessage(
                _request(
                    request_id,
                    "tools/call",
                    {"name": f"blocking-{request_id}"},
                ),
                "newline",
            )
        )
    test.assertTrue(host.all_tools_started.wait(timeout=2))
    workers.submit(
        _InboundMessage(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 41},
            },
            "newline",
        )
    )
    test.assertTrue(host.cancelled.wait(timeout=1))
    host.release_tool.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if {item.get("id") for item in capture.payloads()} >= set(range(41, 46)):
            break
        time.sleep(0.01)
    workers.close()
    test.assertEqual(
        {item.get("id") for item in capture.payloads()},
        set(range(41, 46)),
    )

    host = _BlockingHost()
    broker = StdioBroker("http://host.invalid/mcp", "secret", proxy=host)
    broker.handle(
        _request(
            46,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "batch-client", "version": "1"},
            },
        )
    )
    capture = _Capture()
    workers = _BrokerWorkers(
        broker.handle,
        broker.close,
        _ProtocolWriter(capture),
        worker_count=1,
        queue_size=2,
    )
    workers.submit(
        _InboundMessage(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                _request(47, "tools/call", {"name": "blocking-batch"}),
            ],
            "newline",
        )
    )
    test.assertTrue(host.tool_started.wait(timeout=2))
    workers.submit(
        _InboundMessage(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 47},
            },
            "newline",
        )
    )
    cancellation_reached = host.cancelled.wait(timeout=0.5)
    host.release_tool.set()
    workers.close()
    test.assertTrue(cancellation_reached)
    payloads = capture.payloads()
    test.assertEqual(len(payloads), 1)
    test.assertEqual(
        [item.get("id") for item in payloads[0]],
        [47],
    )


def _assert_late_epoch_results_do_not_regress(test: unittest.TestCase) -> None:
    host = _EpochHost()
    broker = StdioBroker("http://host.invalid/mcp", "secret", proxy=host)
    broker.handle(
        _request(
            50,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "epoch-client", "version": "1"},
            },
        )
    )
    results: dict[int, dict] = {}

    def call_old(request_id, name):
        results[request_id] = broker.handle(
            _request(request_id, "tools/call", {"name": name})
        )

    first = threading.Thread(target=call_old, args=(51, "old_fail"))
    second = threading.Thread(target=call_old, args=(52, "old_success"))
    first.start()
    second.start()
    host.old_started.wait(timeout=3)
    host.guard_change_to = ("host-b", "generation-2")
    current = broker.handle(_request(53, "ping"))
    test.assertIn("result", current)
    host.release_old.set()
    first.join(timeout=2)
    second.join(timeout=2)
    test.assertEqual(results[51]["error"]["data"]["kind"], "ambiguous_delivery")
    test.assertEqual(results[52]["error"]["data"]["kind"], "ambiguous_delivery")
    test.assertEqual(
        (broker.host_instance_id, broker.host_generation),
        ("host-b", "generation-2"),
    )
    test.assertIn("result", broker.handle(_request(54, "ping")))


def _credential(secret: str, marker: str) -> _BrokerCredential:
    return _BrokerCredential(
        secret,
        "sha256:" + marker * 64,
        "sha256:" + marker * 64,
    )


def _assert_auth_refresh_is_read_safe(test: unittest.TestCase) -> None:
    stale = _credential("stale" * 8, "0")
    first = _credential("a" * 32, "1")
    second = _credential("b" * 32, "2")
    host = _RotatingAuthHost(first.secret)
    selected = [first]
    provider_calls: list[_BrokerCredential] = []

    def provider():
        provider_calls.append(selected[0])
        return selected[0]

    broker = StdioBroker(
        "http://host.invalid/mcp",
        stale.secret,
        proxy=host,
        credential=stale,
        credential_provider=provider,
    )
    initialized = broker.handle(_request(60, "initialize", {
        "protocolVersion": "2025-06-18",
        "clientInfo": {"name": "auth-client", "version": "1"},
    }))
    test.assertIn("result", initialized)
    test.assertEqual(host.tokens[:2], [stale.secret, first.secret])
    host.expected_token = second.secret
    selected[0] = second
    rejected = broker.handle(_request(61, "tools/call", {"name": "node.get"}))
    test.assertEqual(rejected["error"]["data"]["kind"], "auth")
    test.assertEqual(len(provider_calls), 2)
    test.assertIn("result", broker.handle(_request(62, "tools/list")))
    test.assertEqual(len(provider_calls), 2)
    test.assertIn(
        "result",
        broker.handle(_request(63, "tools/call", {"name": "node.get"})),
    )


def _assert_auth_refresh_is_serialized(test: unittest.TestCase) -> None:
    first = _credential("a" * 32, "3")
    second = _credential("b" * 32, "4")
    third = _credential("c" * 32, "5")
    host = _LateCredentialHost(first.secret)
    selected = [second]
    provider_started = threading.Event()
    provider_release = threading.Event()
    provider_calls = []

    def provider():
        provider_calls.append(selected[0])
        provider_started.set()
        provider_release.wait(timeout=3)
        return selected[0]

    broker = StdioBroker(
        "http://host.invalid/mcp",
        first.secret,
        proxy=host,
        credential=first,
        credential_provider=provider,
    )
    test.assertIn("result", broker.handle(_request(70, "initialize", {
        "protocolVersion": "2025-06-18",
        "clientInfo": {"name": "auth-race", "version": "1"},
    })))
    host.expected_token = second.secret
    host.instance = "host-second"
    results: dict[int, dict[str, Any]] = {}

    def list_tools(request_id: int) -> None:
        results[request_id] = broker.handle(_request(request_id, "tools/list"))

    threads = [threading.Thread(target=list_tools, args=(request_id,))
               for request_id in (71, 72)]
    for thread in threads:
        thread.start()
    test.assertTrue(provider_started.wait(timeout=2))
    provider_release.set()
    for thread in threads:
        thread.join(timeout=3)
    test.assertEqual(len(provider_calls), 1)
    test.assertTrue(all("result" in result for result in results.values()))
    valid_initializes = [
        request for request, _kwargs in host.calls
        if request.get("method") == "initialize"
    ]
    test.assertEqual(len(valid_initializes), 2)

    host.block_next = True
    late = threading.Thread(target=list_tools, args=(73,))
    late.start()
    test.assertTrue(host.late_started.wait(timeout=2))
    selected[0] = third
    host.expected_token = third.secret
    host.instance = "host-third"
    test.assertIn("result", broker.handle(_request(74, "tools/list")))
    host.release_late.set()
    late.join(timeout=3)
    test.assertEqual(broker.host_instance_id, "host-third")
    test.assertIn("result", results[73])

    selected[0] = first
    host.expected_token = first.secret
    regressed = broker.handle(_request(75, "tools/list"))
    test.assertEqual(regressed["error"]["data"]["kind"], "auth")
    host.expected_token = third.secret
    test.assertIn("result", broker.handle(_request(76, "tools/list")))


def _launcher_module():
    path = ROOT / "scripts" / "hocuspocus-mcp-stdio.py"
    spec = importlib.util.spec_from_file_location("hocuspocus_launcher_auth", path)
    if spec is None or spec.loader is None:
        raise AssertionError("HocusPocus launcher could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_auth_config(root: Path, mode: str, token: str) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "default.toml").write_text(
        f'token_mode = "{mode}"\ntoken = "{token}"\n',
        encoding="utf-8",
    )


def _assert_installed_credentials_are_authoritative(test: unittest.TestCase) -> None:
    launcher = _launcher_module()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        configured = "c" * 32
        rotated = "d" * 32
        _write_auth_config(root, "generated", configured)
        active = [root]
        manifest_digest = "sha256:" + "f" * 64
        pointer_authority = object()
        captured = []
        bridge = types.ModuleType("hocuspocus.core.stdio_bridge")

        def pointer(_launcher):
            content = (root / "config" / "default.toml").read_bytes()
            config_digest = "sha256:" + hashlib.sha256(content).hexdigest()
            return root, pointer_authority, config_digest, manifest_digest

        def broker_main(*, token=None, credential=None, credential_provider=None):
            captured.append((token, credential, credential_provider))
            return 0

        bridge._BrokerCredential = _BrokerCredential
        bridge.main = broker_main
        snapshot = launcher._InstallSnapshot(
            {"manifestDigest": manifest_digest},
            {},
            b"{}",
        )
        launcher._active_root = lambda _path: (active[0], True)
        launcher._verify_install = lambda *_args: snapshot
        launcher._pointer_authority = pointer
        launcher._reject_preloaded_runtime = lambda: None
        launcher._audit_loaded_runtime = lambda *_args: (
            {"manifestDigest": manifest_digest},
            [],
        )
        launcher._write_runtime_attestation = lambda *_args: None
        original_path = list(sys.path)
        try:
            with (
                mock.patch.dict(
                    sys.modules,
                    {"hocuspocus.core.stdio_bridge": bridge},
                ),
                mock.patch.dict(
                    os.environ,
                    {"HOCUSPOCUS_TOKEN": "stale" * 8},
                ),
            ):
                test.assertEqual(launcher.main(), 0)
                test.assertIsNone(captured[-1][0])
                test.assertEqual(captured[-1][1].secret, configured)
                os.environ.pop("HOCUSPOCUS_TOKEN", None)
                test.assertEqual(launcher.main(), 0)
                test.assertEqual(captured[-1][1].secret, configured)
                _write_auth_config(root, "generated", rotated)
                refreshed = captured[-1][2]()
                test.assertEqual(refreshed.secret, rotated)
                test.assertNotEqual(
                    refreshed.config_digest,
                    captured[-1][1].config_digest,
                )
                test.assertEqual(refreshed.manifest_digest, manifest_digest)
                _write_auth_config(root, "disabled", "")
                test.assertEqual(launcher.main(), 0)
                test.assertEqual(captured[-1][1].secret, "")
                _write_auth_config(root, "invalid", configured)
                with mock.patch("sys.stderr", io.StringIO()):
                    test.assertEqual(launcher.main(), 1)
        finally:
            sys.path[:] = original_path
        config = root / "host.toml"
        _write_auth_config(root, "generated", configured)
        (root / "config" / "default.toml").replace(config)
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("HOCUSPOCUS_TOKEN", None)
            os.environ.pop("HOCUSPOCUS_TOKEN_MODE", None)
        settings = load_settings(config)
        test.assertEqual((settings.token_mode, settings.token), ("generated", configured))

        disabled = root / "disabled.toml"
        disabled.write_text(
            'token_mode = "disabled"\ntoken = ""\n',
            encoding="utf-8",
        )
        with mock.patch.dict(
            os.environ,
            {
                "HOCUSPOCUS_TOKEN": "e" * 32,
                "HOCUSPOCUS_TOKEN_MODE": "generated",
            },
        ):
            disabled_settings = load_settings(disabled)
        test.assertEqual(
            (disabled_settings.token_mode, disabled_settings.token),
            ("disabled", ""),
        )
        source_config = root / "source.toml"
        source_config.write_text(
            'token_mode = "generated"\ntoken = ""\n',
            encoding="utf-8",
        )
        with mock.patch.dict(
            os.environ,
            {
                "HOCUSPOCUS_TOKEN": "s" * 32,
                "HOCUSPOCUS_TOKEN_MODE": "static",
            },
        ):
            source_settings = load_settings(source_config)
        test.assertEqual(
            (source_settings.token_mode, source_settings.token),
            ("static", "s" * 32),
        )
        with mock.patch.dict(
            os.environ,
            {
                "HOCUSPOCUS_TOKEN": "e" * 32,
                "HOCUSPOCUS_TOKEN_MODE": "disabled",
            },
        ):
            stale_settings = load_settings(config)
        test.assertEqual(
            (stale_settings.token_mode, stale_settings.token),
            ("generated", configured),
        )
        token_only = root / "token-only.toml"
        token_only.write_text(f'token = "{configured}"\n', encoding="utf-8")
        with mock.patch.dict(
            os.environ,
            {
                "HOCUSPOCUS_TOKEN": "e" * 32,
                "HOCUSPOCUS_TOKEN_MODE": "disabled",
            },
        ):
            token_only_settings = load_settings(token_only)
        test.assertEqual(
            (token_only_settings.token_mode, token_only_settings.token),
            ("generated", configured),
        )


def assert_stdio_broker_contract(test: unittest.TestCase) -> None:
    assert_delivery_revision_contract(test)
    _assert_framing_and_bounds(test)
    _assert_restart_and_ambiguity(test)
    _assert_offline_startup(test)
    _assert_watcher_and_resume_replacement(test)
    _assert_worker_control_lane(test)
    _assert_late_epoch_results_do_not_regress(test)
    _assert_auth_refresh_is_read_safe(test)
    _assert_auth_refresh_is_serialized(test)
    _assert_installed_credentials_are_authoritative(test)
