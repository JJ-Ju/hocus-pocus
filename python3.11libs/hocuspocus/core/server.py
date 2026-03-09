"""Minimal MCP-compatible HTTP runtime."""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.dispatcher import LiveCommandDispatcher
from hocuspocus.live.monitor import SceneEventMonitor
from hocuspocus.live.operations import LiveOperations
from hocuspocus.version import PROTOCOL_VERSION, SERVER_NAME, __version__

from .jsonrpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    error_response,
    success_response,
)
from .mcp_types import ResourceRegistry, ToolRegistry
from .settings import ServerSettings


def _json_dumps(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    server_version = "HocusPocusMCP/0.1"
    protocol_version = "HTTP/1.0"

    def _runtime(self) -> "HocusPocusRuntime":
        return self.server.runtime  # type: ignore[attr-defined]

    def _logger(self) -> logging.Logger:
        return self._runtime().logger.getChild("http")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == self._runtime().settings.normalized_health_route:
            body = _json_dumps(self._runtime().health_payload())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != self._runtime().settings.normalized_mcp_route:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not self._runtime().authorize(self.headers.get("Authorization", "")):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._write_json(
                HTTPStatus.OK,
                error_response(None, JsonRpcError(PARSE_ERROR, "Invalid JSON", str(exc))),
            )
            return

        response = self._runtime().handle_request(payload)
        if response is None:
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self._write_json(HTTPStatus.OK, response)

    def _write_json(self, status: HTTPStatus, payload: Any) -> None:
        body = _json_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        self._logger().info("%s - %s", self.address_string(), format % args)


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class HocusPocusRuntime:
    def __init__(self, settings: ServerSettings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger.getChild("runtime")
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self.dispatcher = LiveCommandDispatcher(logger)
        self.monitor = SceneEventMonitor(logger)
        self.operations = LiveOperations(self.dispatcher, self.monitor, settings, logger)
        self.operations.register(self.tools, self.resources)
        self._token = settings.resolved_token()
        self._server: RuntimeHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            self.dispatcher.start()
            self.monitor.start()
            self._server = RuntimeHTTPServer(
                (self.settings.host, self.settings.port),
                RuntimeRequestHandler,
            )
            self._server.runtime = self  # type: ignore[attr-defined]
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="HocusPocusHTTP",
                daemon=True,
            )
            self._server_thread.start()
            self._running = True
            self.logger.info(
                "server started on %s with dispatcher mode=%s",
                self.settings.mcp_url,
                self.dispatcher.mode,
            )

    def stop(self) -> None:
        with self._state_lock:
            if not self._running:
                return
            assert self._server is not None
            self._server.shutdown()
            self._server.server_close()
            if self._server_thread is not None:
                self._server_thread.join(timeout=2.0)
            self.monitor.stop()
            self.dispatcher.stop()
            self._server = None
            self._server_thread = None
            self._running = False
            self.logger.info("server stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "host": self.settings.host,
            "port": self.settings.port,
            "mcpUrl": self.settings.mcp_url,
            "healthUrl": self.settings.health_url,
            "tokenEnabled": self.settings.token_mode != "disabled",
            "token": self._token if self.settings.token_mode != "disabled" else "",
            "dispatcherMode": self.dispatcher.mode,
            "activeOperations": self.dispatcher.operations_snapshot(limit=20),
            "monitor": self.monitor.snapshot(),
        }

    def health_payload(self) -> dict[str, Any]:
        payload = self.status()
        payload["protocolVersion"] = PROTOCOL_VERSION
        payload["serverVersion"] = __version__
        return payload

    def authorize(self, header_value: str) -> bool:
        if self.settings.token_mode == "disabled":
            return True
        expected = f"Bearer {self._token}"
        return header_value == expected

    def handle_request(self, payload: Any) -> Any:
        if isinstance(payload, list):
            responses = [self._handle_single(item) for item in payload]
            return [item for item in responses if item is not None]
        return self._handle_single(payload)

    def _handle_single(self, payload: Any) -> dict[str, Any] | None:
        request_id = None
        try:
            if not isinstance(payload, dict):
                raise JsonRpcError(INVALID_REQUEST, "Request must be an object.")
            if payload.get("jsonrpc") != JSONRPC_VERSION:
                raise JsonRpcError(INVALID_REQUEST, "jsonrpc must be 2.0")

            request_id = payload.get("id")
            method = payload.get("method")
            if not isinstance(method, str):
                raise JsonRpcError(INVALID_REQUEST, "method must be a string")

            params = payload.get("params", {})
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise JsonRpcError(INVALID_PARAMS, "params must be an object")

            if request_id is None and method.startswith("notifications/"):
                self._dispatch_method(method, params, request_id)
                return None

            result = self._dispatch_method(method, params, request_id)
            if request_id is None:
                return None
            return success_response(request_id, result)
        except JsonRpcError as exc:
            return error_response(request_id, exc)
        except OperationCancelledError as exc:
            return error_response(
                request_id,
                JsonRpcError(-32800, "Request cancelled", str(exc)),
            )
        except Exception as exc:
            self.logger.exception("unhandled request failure")
            return error_response(
                request_id,
                JsonRpcError(INTERNAL_ERROR, "Internal server error", str(exc)),
            )

    def _build_context(
        self,
        method: str,
        request_id: Any,
        params: dict[str, Any],
    ) -> RequestContext:
        metadata = {
            "method": method,
            "requestId": request_id,
        }
        caller = str(params.get("_caller", "mcp-client"))
        timeout_seconds = float(
            params.get("_timeout_seconds", self.settings.request_timeout_seconds)
        )
        operation_id = str(
            params.get("_operation_id", f"{method}:{request_id}")
            if request_id is not None
            else params.get("_operation_id", "")
        ).strip()
        if not operation_id:
            operation_id = RequestContext().operation_id
        return RequestContext(
            caller_id=caller,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
            operation_id=operation_id,
        )

    def _dispatch_method(self, method: str, params: dict[str, Any], request_id: Any) -> Any:
        context = self._build_context(method, request_id, params)

        if method == "initialize":
            return self._initialize_payload()
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools.list_payload()}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str):
                raise JsonRpcError(INVALID_PARAMS, "Tool call requires a string name.")
            if not isinstance(arguments, dict):
                raise JsonRpcError(INVALID_PARAMS, "Tool arguments must be an object.")
            tool = self.tools.get(name)
            if tool is None:
                raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown tool: {name}")
            return tool.handler(arguments, context)
        if method == "resources/list":
            return {"resources": self.resources.list_payload()}
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str):
                raise JsonRpcError(INVALID_PARAMS, "Resource read requires a string uri.")
            resource = self.resources.get(uri)
            if resource is None:
                raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown resource: {uri}")
            return resource.reader(context)
        if method == "notifications/cancelled":
            request_id_value = params.get("requestId")
            operation_id_value = params.get("operationId")
            cancelled = False
            if request_id_value is not None:
                cancelled = self.dispatcher.cancel_by_request_id(str(request_id_value))
            if not cancelled and operation_id_value is not None:
                cancelled = self.dispatcher.cancel(str(operation_id_value))
            self.logger.info(
                "received cancellation notification requestId=%s operationId=%s cancelled=%s",
                request_id_value,
                operation_id_value,
                cancelled,
            )
            return None
        if method == "notifications/initialized":
            self.logger.info("client initialized")
            return None

        raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown method: {method}")

    def _initialize_payload(self) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": __version__,
            },
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "logging": {},
            },
        }
