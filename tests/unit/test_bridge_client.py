"""HostClient against a tiny stdlib fake host (BIBLE §3.4)."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hocuspocus.bridge.client import HostClient
from hocuspocus.tools import catalog
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

TOKEN = "secret-token"


class FakeHost:
    """Scriptable ``/hp/v1`` server on an ephemeral loopback port."""

    def __init__(self) -> None:
        self.health = {
            "ok": True,
            "hp": catalog.HP_RPC_VERSION,
            "pid": 4242,
            "houdini": "22.0.466",
            "generation": 1,
        }
        self.reply: dict | None = {
            "ok": True,
            "result": {"value": 1},
            "_meta": {"scene_generation": 3},
        }
        self.drop_after_read = False
        self.status = 200
        self.requests: list[dict] = []
        host = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                if self.path == "/hp/v1/health":
                    self._send(200, host.health)
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                host.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
                )
                if host.drop_after_read:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, {"error": "unauthorized"})
                    return
                self._send(host.status, host.reply)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FakeHost:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_host():
    with FakeHost() as host:
        yield host


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_ok(fake_host):
    assert HostClient(fake_host.port, TOKEN).health()["pid"] == 4242


def test_call_ok_returns_result_and_meta(fake_host):
    ok, result, meta = HostClient(fake_host.port, TOKEN).call(
        "node_info", {"paths": ["/obj"]}, 5, "rid-1"
    )
    assert ok is True
    assert result == {"value": 1}
    assert meta == {"scene_generation": 3}
    sent = fake_host.requests[-1]
    assert sent["path"] == "/hp/v1/call"
    assert sent["auth"] == f"Bearer {TOKEN}"
    assert sent["body"] == {
        "tool": "node_info",
        "args": {"paths": ["/obj"]},
        "timeout_s": 5,
        "request_id": "rid-1",
    }


def test_call_error_envelope(fake_host):
    fake_host.reply = {
        "ok": False,
        "error": {"code": "parm_not_found", "message": "No parm 'size'", "candidates": ["sizex"]},
        "_meta": {"scene_generation": 3},
    }
    ok, error, meta = HostClient(fake_host.port, TOKEN).call("parm_get", {}, 5)
    assert ok is False
    assert error["code"] == "parm_not_found"
    assert error["candidates"] == ["sizex"]
    assert meta["scene_generation"] == 3


def test_call_401_is_offline_not_delivery_unknown(fake_host):
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, "wrong").call("node_info", {}, 5)
    assert info.value.code == "houdini_offline"
    assert "401" in info.value.message


def test_http_500_is_internal(fake_host):
    fake_host.status = 500
    fake_host.reply = {"error": "boom"}
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, TOKEN).call("node_info", {}, 5)
    assert info.value.code == "internal"


def test_malformed_envelope_is_internal(fake_host):
    fake_host.reply = {"something": "else"}
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, TOKEN).call("node_info", {}, 5)
    assert info.value.code == "internal"


def test_connection_refused_is_offline():
    port = _free_port()
    with pytest.raises(ToolError) as info:
        HostClient(port, TOKEN).call("node_info", {}, 5)
    assert info.value.code == "houdini_offline"
    assert info.value.hint and "houdini_connect" in info.value.hint


def test_drop_after_send_is_delivery_unknown(fake_host):
    fake_host.drop_after_read = True
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, TOKEN).call("node_delete", {"paths": ["/obj/a"]}, 5)
    assert info.value.code == "delivery_unknown"
    assert len(fake_host.requests) == 1  # exactly one attempt


def test_version_mismatch_on_health(fake_host):
    fake_host.health = dict(fake_host.health, hp=catalog.HP_RPC_VERSION + 1)
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, TOKEN).health()
    assert info.value.code == "version_mismatch"
    assert "install-houdini" in (info.value.hint or "")


def test_unknown_route_is_version_mismatch(fake_host):
    with pytest.raises(ToolError) as info:
        HostClient(fake_host.port, TOKEN).job("abc")
    # The fake answers 404 for GET routes it does not know, as an older/newer host would.
    assert info.value.code == "version_mismatch"
