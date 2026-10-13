"""Loopback HTTP listener for the ``hp/v1`` RPC. Stdlib only. See docs/BIBLE.md §3.2, §3.4.

Routes::

    GET  /hp/v1/health      no auth, no hou call
    POST /hp/v1/call        {tool, args, timeout_s, request_id} -> envelope
    GET  /hp/v1/jobs/{id}   job status (and result once done)
    GET  /hp/v1/calls/{request_id}/jobs   snapshots of the jobs a call started (progress)
    POST /hp/v1/shutdown    stop the host (not Houdini)
    POST /hp/v1/quit        {on_unsaved} -> quit Houdini after the unsaved check

Every route rejects a non-loopback ``Origin`` or ``Host`` with 403 (the ``Host`` check
closes DNS rebinding, which sends same-origin GETs with no ``Origin``). Idle connections
time out after :data:`REQUEST_TIMEOUT_S`. All routes except health need
``Authorization: Bearer <token>`` (401 otherwise). Bodies are capped at 4 MB (413).
Once authenticated, tool outcomes are always HTTP 200 with ``ok`` true/false.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from hocuspocus.tools.errors import ToolError

from .dispatch import error_envelope

API_PREFIX = "/hp/v1"
MAX_BODY_BYTES = 4 * 1024 * 1024
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
REQUEST_TIMEOUT_S = 60
"""Socket timeout per connection: an idle keep-alive or slow client cannot hold a handler
thread for ever (review 10 section 1.8)."""

log = logging.getLogger("hocuspocus.host.server")


def origin_allowed(origin: str | None) -> bool:
    """An absent ``Origin`` is allowed; a present one must name a loopback host."""
    if origin is None:
        return True
    try:
        host = urlsplit(origin.strip()).hostname
    except ValueError:
        return False
    return host is not None and (host in LOOPBACK_HOSTS or host.endswith(".localhost"))


def host_allowed(host_header: str | None) -> bool:
    """An absent ``Host`` (HTTP/1.0) is allowed; a present one must name a loopback host."""
    if host_header is None:
        return True
    try:
        host = urlsplit("//" + host_header.strip()).hostname
    except ValueError:
        return False
    return host is not None and (host in LOOPBACK_HOSTS or host.endswith(".localhost"))


def bearer_ok(header: str | None, token: str) -> bool:
    if not header or not token:
        return False
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(value.strip().encode("utf-8"), token.encode("utf-8"))


class HostApp:
    """What the HTTP layer needs from the host. Kept small so tests can fake it."""

    def __init__(
        self,
        *,
        token: str,
        call: Callable[[Any, Any, Any], dict[str, Any]],
        health: Callable[[], dict[str, Any]],
        job: Callable[[str], dict[str, Any]] | None = None,
        shutdown: Callable[[], None] | None = None,
        meta: Callable[[], dict[str, Any]] | None = None,
        call_jobs: Callable[[str], list[dict[str, Any]]] | None = None,
        quit: Callable[[dict[str, Any]], tuple[dict[str, Any], Callable[[], None] | None]]
        | None = None,
    ) -> None:
        self.token = token
        self.call = call
        self.quit = quit
        """``POST /hp/v1/quit``: returns the envelope and, when it agreed to quit, the
        function that quits (run after the response is sent)."""
        self.health = health
        self.job = job
        self.call_jobs = call_jobs
        self.shutdown = shutdown
        self.meta = meta or (lambda: {"scene_generation": 0, "undo_label": None, "elapsed_ms": 0})


class HostHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, app: HostApp, host: str = "127.0.0.1", port: int = 0) -> None:
        self.app = app
        super().__init__((host, port), _Handler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class _Handler(BaseHTTPRequestHandler):
    server: HostHTTPServer
    server_version = "HocusPocusHost/1"
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_S

    # -- plumbing ---------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=repr).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _transport_error(self, status: HTTPStatus, message: str) -> None:
        self.close_connection = True
        self._send_json(
            status,
            {
                "ok": False,
                "error": {"code": "transport", "status": int(status), "message": message},
            },
        )

    def _guard(self, *, auth: bool) -> bool:
        if not origin_allowed(self.headers.get("Origin")):
            self._transport_error(HTTPStatus.FORBIDDEN, "Origin is not loopback.")
            return False
        if not host_allowed(self.headers.get("Host")):
            self._transport_error(HTTPStatus.FORBIDDEN, "Host is not loopback.")
            return False
        if auth and not bearer_ok(self.headers.get("Authorization"), self.server.app.token):
            self._transport_error(HTTPStatus.UNAUTHORIZED, "Missing or invalid bearer token.")
            return False
        return True

    def _read_json(self) -> Any:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._transport_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required.")
            return _NO_BODY
        try:
            length = int(length_header)
        except ValueError:
            self._transport_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.")
            return _NO_BODY
        if length < 0 or length > MAX_BODY_BYTES:
            self._transport_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"Request body exceeds {MAX_BODY_BYTES} bytes."
            )
            return _NO_BODY
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._transport_error(HTTPStatus.BAD_REQUEST, f"Body is not valid JSON: {exc}")
            return _NO_BODY

    # -- routes -----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = urlsplit(self.path).path.rstrip("/")
        if path == f"{API_PREFIX}/health":
            if self._guard(auth=False):
                self._send_json(HTTPStatus.OK, self.server.app.health())
            return
        if path.startswith(f"{API_PREFIX}/jobs/"):
            if not self._guard(auth=True):
                return
            job_id = path[len(f"{API_PREFIX}/jobs/") :]
            self._send_json(HTTPStatus.OK, self._job(job_id))
            return
        if path.startswith(f"{API_PREFIX}/calls/") and path.endswith("/jobs"):
            if not self._guard(auth=True):
                return
            request_id = path[len(f"{API_PREFIX}/calls/") : -len("/jobs")]
            call_jobs = self.server.app.call_jobs
            jobs = call_jobs(request_id) if call_jobs is not None and request_id else []
            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "result": {"jobs": jobs}, "_meta": self.server.app.meta()},
            )
            return
        if self._guard(auth=False):
            self._transport_error(HTTPStatus.NOT_FOUND, f"No route {path}.")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path = urlsplit(self.path).path.rstrip("/")
        if path not in (f"{API_PREFIX}/call", f"{API_PREFIX}/shutdown", f"{API_PREFIX}/quit"):
            if self._guard(auth=False):
                self._transport_error(HTTPStatus.NOT_FOUND, f"No route {path}.")
            return
        if not self._guard(auth=True):
            return
        body = self._read_json()
        if body is _NO_BODY:
            return
        if path.endswith("/shutdown"):
            self._send_json(HTTPStatus.OK, {"ok": True, "result": {"stopping": True}})
            shutdown = self.server.app.shutdown
            if shutdown is not None:
                threading.Thread(target=shutdown, name="hocuspocus-shutdown", daemon=True).start()
            return
        if path.endswith("/quit"):
            quit_ = self.server.app.quit
            if quit_ is None:
                self._transport_error(HTTPStatus.NOT_FOUND, f"No route {path}.")
                return
            envelope, after = quit_(body if isinstance(body, dict) else {})
            self.close_connection = True
            self._send_json(HTTPStatus.OK, envelope)
            if after is not None:
                threading.Thread(target=after, name="hocuspocus-quit", daemon=True).start()
            return
        if not isinstance(body, dict):
            self._send_json(
                HTTPStatus.OK,
                error_envelope(
                    ToolError("invalid_argument", "Request body must be a JSON object."),
                    self.server.app.meta(),
                ),
            )
            return
        started = time.perf_counter()
        # The bridge sends its byte budget; paged tools stop a page there (BIBLE §4.1).
        budget = (
            {"max_response_bytes": body["max_response_bytes"]}
            if "max_response_bytes" in body
            else {}
        )
        if isinstance(body.get("request_id"), str):
            budget["request_id"] = body["request_id"]
        envelope = self.server.app.call(
            body.get("tool"), body.get("args"), body.get("timeout_s"), **budget
        )
        log.debug(
            "call %s request_id=%s ok=%s %.1f ms",
            body.get("tool"),
            body.get("request_id"),
            envelope.get("ok"),
            (time.perf_counter() - started) * 1000,
        )
        self._send_json(HTTPStatus.OK, envelope)

    def _job(self, job_id: str) -> dict[str, Any]:
        job = self.server.app.job
        if job is None:
            return error_envelope(
                ToolError("job_not_found", "Jobs are not available."), self.server.app.meta()
            )
        try:
            return {"ok": True, "result": job(job_id), "_meta": self.server.app.meta()}
        except ToolError as exc:
            return error_envelope(exc, self.server.app.meta())


_NO_BODY = object()


def serve_in_thread(server: HostHTTPServer, poll_interval: float = 0.2) -> threading.Thread:
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": poll_interval},
        name=f"hocuspocus-http-{server.port}",
        daemon=True,
    )
    thread.start()
    return thread
