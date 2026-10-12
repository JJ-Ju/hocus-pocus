"""Loopback HTTP client for the host RPC (``/hp/v1``). Stdlib only. See docs/BIBLE.md §3.4.

The client never retries. It distinguishes failures that happened *before* the request
reached the host (``houdini_offline``: safe to repeat after connecting) from failures
*after* the request was sent (``delivery_unknown``: the call may have run).
"""

from __future__ import annotations

import http.client
import json
import socket
import uuid
from typing import Any

from ..tools import catalog
from ..tools.errors import ToolError

API_PREFIX = f"/hp/v{catalog.HP_RPC_VERSION}"
CONNECT_TIMEOUT_S = 3.0
RESPONSE_GRACE_S = 15.0
"""Extra seconds the bridge waits beyond the call's own ``timeout_s`` before giving up."""

OFFLINE_HINT = (
    "call houdini_connect with launch to start one; to keep Houdini alive across sessions, "
    "start it with `hocuspocus launch` and attach by pid"
)
REINSTALL_HINT = "run `hocuspocus install-houdini` and restart Houdini"
DELIVERY_HINT = (
    "The call may or may not have run in Houdini. Inspect state (houdini_status, node_info, "
    "undo history) before repeating it; never blindly repeat a mutation."
)


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class HostClient:
    """Talks to one host instance at ``127.0.0.1:<port>`` with its bearer token."""

    def __init__(
        self,
        port: int,
        token: str,
        *,
        host: str = "127.0.0.1",
        connect_timeout_s: float = CONNECT_TIMEOUT_S,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.token = token
        self.connect_timeout_s = connect_timeout_s

    # -- transport ---------------------------------------------------------------------

    def _connect(self) -> http.client.HTTPConnection:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout_s)
        try:
            conn.connect()
        except (TimeoutError, OSError) as exc:
            conn.close()
            raise ToolError(
                "houdini_offline",
                f"No HocusPocus host is listening on {self.host}:{self.port} ({exc.__class__.__name__}).",
                hint=OFFLINE_HINT,
            ) from exc
        return conn

    def _request(
        self,
        method: str,
        route: str,
        body: Any = None,
        *,
        auth: bool = True,
        read_timeout_s: float = 10.0,
    ) -> tuple[int, Any]:
        """Send one request; returns ``(status, parsed_json_or_text)``."""
        conn = self._connect()
        headers = {"Accept": "application/json", "Host": f"{self.host}:{self.port}"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = None
        if body is not None:
            payload = _json_dumps(body)
            headers["Content-Type"] = "application/json"
        try:
            if conn.sock is not None:
                conn.sock.settimeout(read_timeout_s)
            conn.request(method, API_PREFIX + route, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            status = response.status
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            # The connection was up, so the bytes may have reached the host.
            raise ToolError(
                "delivery_unknown",
                f"The request to Houdini (port {self.port}) was sent but no complete response "
                f"arrived ({exc.__class__.__name__}: {exc}).",
                hint=DELIVERY_HINT,
            ) from exc
        finally:
            conn.close()
        text = raw.decode("utf-8", errors="replace")
        try:
            return status, json.loads(text) if text else None
        except ValueError:
            return status, text

    def _check_status(self, status: int, data: Any) -> None:
        if status == 200:
            return
        if status in (401, 403):
            raise ToolError(
                "houdini_offline",
                f"The Houdini host on port {self.port} rejected the bridge's credentials (HTTP {status}); "
                "its registry entry is stale or belongs to another process.",
                hint="call houdini_status, then houdini_connect to attach to a live instance",
            )
        if status == 404:
            raise ToolError(
                "version_mismatch",
                f"The process on port {self.port} does not serve {API_PREFIX} (HTTP 404).",
                hint=REINSTALL_HINT,
            )
        detail = data if isinstance(data, dict | str) else None
        raise ToolError(
            "internal",
            f"The Houdini host answered HTTP {status}.",
            hint="check the host log under the HocusPocus state dir (logs/host-<pid>.log)",
            detail=detail,
        )

    # -- API ---------------------------------------------------------------------------

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        """``GET /hp/v1/health``; raises ``version_mismatch`` if the host speaks another ``hp``."""
        status, data = self._request("GET", "/health", auth=False, read_timeout_s=timeout_s)
        self._check_status(status, data)
        if not isinstance(data, dict):
            raise ToolError(
                "internal", "The host's /health answer was not a JSON object.", detail=data
            )
        hp = data.get("hp", catalog.HP_RPC_VERSION)
        if hp != catalog.HP_RPC_VERSION:
            raise ToolError(
                "version_mismatch",
                f"The Houdini host speaks hp/v{hp}; this bridge speaks hp/v{catalog.HP_RPC_VERSION}.",
                hint=REINSTALL_HINT,
                detail={"host_hp": hp, "bridge_hp": catalog.HP_RPC_VERSION},
            )
        return data

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None,
        timeout_s: float,
        request_id: str | None = None,
        max_response_bytes: int | None = None,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """``POST /hp/v1/call`` once. Returns ``(ok, result_or_error, meta)``.

        ``max_response_bytes`` tells the host the client's budget, so paged tools stop a
        page there and set ``next_cursor`` to the first row not returned."""
        body: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "timeout_s": timeout_s,
            "request_id": request_id or uuid.uuid4().hex,
        }
        if max_response_bytes:
            body["max_response_bytes"] = int(max_response_bytes)
        status, data = self._request(
            "POST", "/call", body, read_timeout_s=float(timeout_s) + RESPONSE_GRACE_S
        )
        self._check_status(status, data)
        return _parse_envelope(data)

    def job(
        self, job_id: str, timeout_s: float = 10.0
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        status, data = self._request("GET", f"/jobs/{job_id}", read_timeout_s=timeout_s)
        self._check_status(status, data)
        return _parse_envelope(data)

    def call_jobs(self, request_id: str, timeout_s: float = 5.0) -> list[dict[str, Any]]:
        """``GET /hp/v1/calls/{request_id}/jobs``: snapshots of the jobs a call started."""
        status, data = self._request("GET", f"/calls/{request_id}/jobs", read_timeout_s=timeout_s)
        self._check_status(status, data)
        ok, result, _meta = _parse_envelope(data)
        jobs = result.get("jobs") if ok else None
        return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []

    def shutdown(self, timeout_s: float = 5.0) -> None:
        status, data = self._request("POST", "/shutdown", {}, read_timeout_s=timeout_s)
        self._check_status(status, data)


def _parse_envelope(data: Any) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    if not isinstance(data, dict) or "ok" not in data:
        raise ToolError(
            "internal",
            "The Houdini host returned a malformed envelope (expected {ok, result|error, _meta}).",
            detail=data if isinstance(data, dict | str) else None,
        )
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    if data["ok"]:
        result = data.get("result")
        if not isinstance(result, dict):
            result = {"result": result}
        return True, result, meta
    error = data.get("error")
    if not isinstance(error, dict):
        error = {"code": "internal", "message": str(error)}
    return False, error, meta


def is_port_open(port: int, host: str = "127.0.0.1", timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False
