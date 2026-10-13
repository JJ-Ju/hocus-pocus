"""HTTP server + dispatcher on plain CPython: fake tools, fake undo groups, no hou."""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import socket
import threading
import time

import pytest

from hocuspocus.host.config import HostConfig
from hocuspocus.host.dispatch import Dispatcher, error_envelope, ok_envelope
from hocuspocus.host.executor import MainThreadExecutor
from hocuspocus.host.runtime import CallJobManager
from hocuspocus.host.server import (
    REQUEST_TIMEOUT_S,
    HostApp,
    HostHTTPServer,
    bearer_ok,
    host_allowed,
    origin_allowed,
    serve_in_thread,
)
from hocuspocus.host.tools.registry import HostContext, HostTool, SceneState
from hocuspocus.host.undo import UndoHistory
from hocuspocus.tools.errors import ToolError

TOKEN = "secret-token"


class InlineExecutor:
    backend = "headless"

    def run(self, fn, timeout_s):
        return fn()


def _tools():
    def echo(args, ctx):
        return {"echo": args}

    def mutate(args, ctx):
        return {"changed": True}

    def fail(args, ctx):
        raise ToolError(
            "node_not_found", "No node at /obj/x.", hint="Check the path.", candidates=["/obj/geo1"]
        )

    def crash(args, ctx):
        raise RuntimeError("kaboom")

    def gui_only(args, ctx):
        return {}

    def maybe(args, ctx):
        if args.get("dry_run"):
            return {"would": True, "_changed": False}
        return {"did": True, "_changed": True}

    def liar(args, ctx):
        return {"did": True}

    def starts_job(args, ctx):
        job = ctx.jobs.start("starts_job", lambda job_ctx: job_ctx.set_progress(1, 4, "a"))
        job.done_event.wait(5)
        return {"job_id": job.id}

    tools = {
        "echo_ro": HostTool("echo_ro", echo, read_only=True),
        "mutate": HostTool("mutate", mutate, read_only=False),
        "fail": HostTool("fail", fail, read_only=True),
        "crash": HostTool("crash", crash, read_only=True),
        "maybe": HostTool("maybe", maybe, read_only=False),
        "liar": HostTool("liar", liar, read_only=False),
        "hostonly": HostTool("hostonly", echo, read_only=False, main_thread=False, scene=False),
        "pdg": HostTool("pdg", echo, read_only=True, main_thread=False, scene=False),
        "geo_info": HostTool("geo_info", echo, read_only=True),
        "geo_read": HostTool("geo_read", echo, read_only=True),
        "starts_job": HostTool(
            "starts_job", starts_job, read_only=True, main_thread=False, scene=False
        ),
    }
    return tools


@pytest.fixture
def stack():
    groups = []

    @contextlib.contextmanager
    def fake_group(label):
        groups.append(label)
        yield

    config = HostConfig()
    ctx = HostContext(
        config=config,
        executor=InlineExecutor(),
        logger=logging.getLogger("test"),
        scene=SceneState(generation=7),
        jobs=CallJobManager(InlineExecutor()),
        undo=UndoHistory(),
    )
    tools = _tools()
    dispatcher = Dispatcher(
        ctx, tools.get, undo_group=fake_group, known_tool=lambda n: n == "node_create"
    )
    shutdowns = []
    app = HostApp(
        token=TOKEN,
        call=dispatcher.call,
        health=lambda: {
            "ok": True,
            "pid": 1,
            "houdini": "22.0.466",
            "generation": ctx.scene.generation,
        },
        job=ctx.jobs.result,
        shutdown=lambda: shutdowns.append(1),
        call_jobs=ctx.jobs.for_call,
    )
    server = HostHTTPServer(app, port=0)
    thread = serve_in_thread(server, poll_interval=0.01)
    yield {
        "server": server,
        "ctx": ctx,
        "groups": groups,
        "shutdowns": shutdowns,
        "dispatcher": dispatcher,
    }
    server.shutdown()
    server.server_close()
    thread.join(5)


def _request(server, method, path, body=None, *, token=TOKEN, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    send = {"Content-Type": "application/json"}
    if token:
        send["Authorization"] = f"Bearer {token}"
    send.update(headers or {})
    data = (
        body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    )
    conn.request(method, path, body=data, headers=send)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, json.loads(raw) if raw else None


def test_server_binds_loopback_ephemeral_without_reuse(stack):
    server = stack["server"]
    assert server.server_address[0] == "127.0.0.1"
    assert server.port > 0
    assert HostHTTPServer.allow_reuse_address is False


def test_health_without_auth(stack):
    status, body = _request(stack["server"], "GET", "/hp/v1/health", token=None)
    assert status == 200 and body["ok"] is True and body["generation"] == 7


@pytest.mark.parametrize("token", [None, "nope"])
def test_call_needs_bearer(stack, token):
    status, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "echo_ro"}, token=token
    )
    assert status == 401
    assert body["ok"] is False


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://127.0.0.1.evil.example"])
def test_bad_origin_403(stack, origin):
    status, _ = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "echo_ro"}, headers={"Origin": origin}
    )
    assert status == 403


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "http://127.0.0.1", "http://[::1]:8080"]
)
def test_loopback_origin_ok(stack, origin):
    status, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "echo_ro"}, headers={"Origin": origin}
    )
    assert status == 200 and body["ok"] is True


def test_ok_envelope_shape(stack):
    status, body = _request(
        stack["server"],
        "POST",
        "/hp/v1/call",
        {"tool": "echo_ro", "args": {"a": 1}, "request_id": "r1"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["result"] == {"echo": {"a": 1}}
    assert set(body) == {"ok", "result", "_meta"}
    assert set(body["_meta"]) == {"scene_generation", "undo_label", "elapsed_ms"}
    assert body["_meta"]["scene_generation"] == 7
    assert body["_meta"]["undo_label"] is None
    assert stack["groups"] == []


def test_tool_error_envelope(stack):
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "fail"})
    assert body["ok"] is False
    assert set(body) == {"ok", "error", "_meta"}
    assert body["error"] == {
        "code": "node_not_found",
        "message": "No node at /obj/x.",
        "retryable": False,
        "hint": "Check the path.",
        "candidates": ["/obj/geo1"],
    }


def test_unexpected_exception_is_internal_with_traceback(stack):
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "crash"})
    error = body["error"]
    assert error["code"] == "internal"
    assert "RuntimeError: kaboom" in error["hou_exception"]
    assert "kaboom" in error["detail"]["traceback"]


def test_unknown_and_unimplemented_tools(stack):
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "nope"})
    assert body["error"]["code"] == "invalid_argument"
    assert body["error"]["hint"] == "not implemented in this host version"
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "node_create"})
    assert body["error"]["code"] == "invalid_argument"
    assert "not available" in body["error"]["message"]


@pytest.mark.parametrize(
    "payload", [{"args": {}}, {"tool": 5}, {"tool": "echo_ro", "args": [1]}, [1, 2]]
)
def test_malformed_requests_are_invalid_argument(stack, payload):
    status, body = _request(stack["server"], "POST", "/hp/v1/call", payload)
    assert status == 200
    assert body["error"]["code"] == "invalid_argument"


def test_bad_json_is_400(stack):
    status, body = _request(stack["server"], "POST", "/hp/v1/call", b"{not json")
    assert status == 400


def test_body_cap_413(stack):
    server = stack["server"]
    with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
        sock.sendall(
            (
                "POST /hp/v1/call HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Authorization: Bearer {TOKEN}\r\nContent-Length: {5 * 1024 * 1024}\r\n\r\n"
            ).encode()
        )
        data = sock.recv(4096).decode()
    assert data.startswith("HTTP/1.1 413")


def test_unknown_route_404(stack):
    assert _request(stack["server"], "GET", "/elsewhere")[0] == 404
    assert _request(stack["server"], "POST", "/hp/v1/other", {})[0] == 404


def test_mutating_tool_gets_one_undo_group_and_dirties(stack):
    _, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "mutate", "args": {"paths": ["/obj/geo1"]}}
    )
    assert body["ok"] is True
    assert body["_meta"]["undo_label"] == "HocusPocus: mutate /obj/geo1"
    assert stack["groups"] == ["HocusPocus: mutate /obj/geo1"]
    assert stack["ctx"].undo.labels() == ["HocusPocus: mutate /obj/geo1"]
    assert stack["ctx"].scene.dirty is True


def test_read_only_config_blocks_mutations(stack):
    stack["ctx"].config.read_only = True
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "mutate"})
    assert body["error"]["code"] == "read_only"
    assert stack["groups"] == []
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "echo_ro"})
    assert body["ok"] is True
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "hostonly"})
    assert body["ok"] is True  # host-state tools (job) are not scene mutations


def test_changed_false_skips_dirty_and_undo(stack):
    _, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "maybe", "args": {"dry_run": True}}
    )
    assert body["ok"] is True
    assert body["result"] == {"would": True, "dirty": False}  # marker stripped
    assert body["_meta"]["undo_label"] is None
    assert stack["ctx"].undo.labels() == []
    assert stack["ctx"].scene.dirty is False
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "maybe", "args": {}})
    assert "_changed" not in body["result"]
    assert body["_meta"]["undo_label"] == "HocusPocus: maybe"
    assert stack["ctx"].scene.dirty is True


def test_read_only_allows_dry_run_that_reports_unchanged(stack):
    stack["ctx"].config.read_only = True
    _, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "maybe", "args": {"dry_run": True}}
    )
    assert body["ok"] is True
    assert body["result"]["would"] is True
    assert stack["groups"] == []
    _, body = _request(stack["server"], "POST", "/hp/v1/call", {"tool": "maybe", "args": {}})
    assert body["error"]["code"] == "read_only"
    # A tool that ignores dry_run and does not report _changed: false is still refused.
    _, body = _request(
        stack["server"], "POST", "/hp/v1/call", {"tool": "liar", "args": {"dry_run": True}}
    )
    assert body["error"]["code"] == "read_only"
    assert stack["ctx"].scene.dirty is False


def test_max_response_bytes_reaches_tools(stack):
    d = stack["dispatcher"]
    seen = []
    d.lookup = lambda name: HostTool(
        "peek", lambda a, c: seen.append(c.extras["max_response_bytes"]) or {}, read_only=True
    )
    d.call("peek", {}, None, 4096)
    d.call("peek", {}, None)
    d.call("peek", {}, None, "junk")
    assert seen == [4096, 16384, 16384]


def test_call_timeout_is_visible_to_off_thread_tools(stack):
    from hocuspocus.host.dispatch import call_timeout

    d = stack["dispatcher"]
    seen = []
    d.lookup = lambda name: HostTool(
        "peek",
        lambda a, c: seen.append(call_timeout()) or {},
        read_only=True,
        main_thread=False,
    )
    d.call("peek", {}, 7)
    d.call("peek", {"timeout_s": 90}, 7)
    d.call("peek", {}, None)
    assert seen == [7.0, 90.0, 30.0]
    assert call_timeout(5) == 5  # outside a call


def test_houdini_busy_through_real_executor(stack):
    executor = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    executor.start()
    stack["ctx"].executor = executor
    status_box = {}

    def worker():
        status_box["resp"] = _request(
            stack["server"], "POST", "/hp/v1/call", {"tool": "echo_ro", "timeout_s": 0.2}
        )

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(5)  # nobody pumps the main thread
    status, body = status_box["resp"]
    assert status == 200
    assert body["error"]["code"] == "houdini_busy"
    assert body["error"]["retryable"] is True
    executor.stop()


def test_args_timeout_wins_over_request_timeout(stack):
    d = stack["dispatcher"]
    assert d.effective_timeout({"timeout_s": 90}, 30) == 90
    assert d.effective_timeout({}, 5) == 5
    assert d.effective_timeout({}, None) == 30
    assert d.effective_timeout({}, -1) == 30


def test_job_route(stack):
    _, body = _request(stack["server"], "GET", "/hp/v1/jobs/abc")
    assert body["ok"] is False and body["error"]["code"] == "job_not_found"
    job = stack["ctx"].jobs.start("render", lambda ctx: {"frames": 3})
    job.done_event.wait(5)
    _, body = _request(stack["server"], "GET", f"/hp/v1/jobs/{job.id}")
    assert body["ok"] is True
    assert body["result"]["state"] == "done"
    assert body["result"]["result"] == {"frames": 3}
    assert _request(stack["server"], "GET", f"/hp/v1/jobs/{job.id}", token=None)[0] == 401


def test_shutdown_route(stack):
    status, body = _request(stack["server"], "POST", "/hp/v1/shutdown", {})
    assert status == 200 and body["result"]["stopping"] is True
    deadline = time.monotonic() + 5
    while not stack["shutdowns"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stack["shutdowns"] == [1]
    assert _request(stack["server"], "POST", "/hp/v1/shutdown", {}, token=None)[0] == 401


def test_envelope_helpers():
    meta = {"scene_generation": 1, "undo_label": None, "elapsed_ms": 0}
    assert ok_envelope({"x": 1}, meta) == {"ok": True, "result": {"x": 1}, "_meta": meta}
    err = error_envelope(ToolError("read_only", "no"), meta)
    assert err == {
        "ok": False,
        "error": {"code": "read_only", "message": "no", "retryable": False},
        "_meta": meta,
    }


def test_origin_and_bearer_helpers():
    assert origin_allowed(None)
    assert origin_allowed("http://foo.localhost:1")
    assert not origin_allowed("https://example.com")
    assert bearer_ok("Bearer abc", "abc")
    assert bearer_ok("bearer abc", "abc")
    assert not bearer_ok("Basic abc", "abc")
    assert not bearer_ok("Bearer abd", "abc")
    assert not bearer_ok(None, "abc")
    assert not bearer_ok("Bearer ", "")


# -- progress: the jobs a call started (BIBLE §7) ------------------------------------------


def test_jobs_are_filed_under_the_request_that_started_them(stack):
    server = stack["server"]
    body = {"tool": "starts_job", "args": {}, "request_id": "req-1"}
    status, envelope = _request(server, "POST", "/hp/v1/call", body)
    assert status == 200 and envelope["ok"] is True, envelope
    job_id = envelope["result"]["job_id"]
    status, listed = _request(server, "GET", "/hp/v1/calls/req-1/jobs")
    assert status == 200 and listed["ok"] is True
    (snapshot,) = listed["result"]["jobs"]
    assert snapshot["job_id"] == job_id
    assert snapshot["current"] == 4 and snapshot["total"] == 4  # done: counts complete
    _status, other = _request(server, "GET", "/hp/v1/calls/req-2/jobs")
    assert other["result"]["jobs"] == []
    status, _ = _request(server, "GET", "/hp/v1/calls/req-1/jobs", token=None)
    assert status == 401


def test_a_call_without_request_id_files_nothing(stack):
    server = stack["server"]
    _request(server, "POST", "/hp/v1/call", {"tool": "starts_job", "args": {}})
    assert stack["ctx"].jobs._by_call == {}


# -- review 10 section 1.8 and host profile enforcement ------------------------------------


def test_host_header_must_be_loopback(stack):
    server = stack["server"]
    for good in (None, "127.0.0.1:1234", "localhost", "[::1]:80", "app.localhost:9"):
        assert host_allowed(good), good
    for bad in ("evil.example:80", "10.0.0.1", "127.0.0.1.nip.io", ""):
        assert not host_allowed(bad), bad
    status, body = _request(server, "GET", "/hp/v1/health", headers={"Host": "evil.example"})
    assert status == 403 and "Host" in body["error"]["message"]
    status, _ = _request(server, "GET", "/hp/v1/health")
    assert status == 200


def test_idle_connections_time_out():
    from hocuspocus.host.server import _Handler

    assert _Handler.timeout == REQUEST_TIMEOUT_S == 60


def test_a_core_host_refuses_full_profile_tools(stack):
    dispatcher, ctx = stack["dispatcher"], stack["ctx"]
    assert ctx.config.profile == "core"
    error = dispatcher.call("pdg", {})["error"]
    assert error["code"] == "invalid_argument" and "full-profile" in error["message"]
    assert 'profile = "full"' in error["hint"]
    ctx.config.profile = "full"
    assert dispatcher.call("pdg", {})["ok"] is True


def test_a_minimal_host_refuses_tools_outside_minimal(stack):
    """1.3 (BIBLE §3.7): the host honours minimal as it honours core."""
    dispatcher, ctx = stack["dispatcher"], stack["ctx"]
    ctx.config.profile = "minimal"
    assert dispatcher.call("geo_info", {})["ok"] is True
    error = dispatcher.call("geo_read", {})["error"]
    assert error["code"] == "invalid_argument"
    assert "core-profile" in error["message"] and "minimal profile" in error["message"]
    assert 'profile = "core"' in error["hint"]
    assert "full-profile" in dispatcher.call("pdg", {})["error"]["message"]
