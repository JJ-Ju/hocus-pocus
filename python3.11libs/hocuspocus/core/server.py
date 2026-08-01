"""Minimal MCP-compatible HTTP runtime."""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.dispatcher import LiveCommandDispatcher
from hocuspocus.live.monitor import SceneEventMonitor
from hocuspocus.live.operations import LiveOperations
from hocuspocus.live.tasks import LiveTaskManager
from hocuspocus.version import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_PROTOCOL_VERSIONS,
    __version__,
)

from .audit import AuditLogger
from .host_identity import HostIdentity
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
from .operation_execution import execute_tool_call
from .operation_history import OperationHistory, new_operation_id, valid_operation_id
from .policy import capability_set_from_settings
from .settings import ServerSettings
from .workspace_authority import WorkspaceAuthority
from .workspace_grants import WorkspaceGrantError, principal_from_bearer

_MAX_MCP_REQUEST_BYTES = 8 * 1024 * 1024


def _json_dumps(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    server_version = "HocusPocusMCP/0.1"
    protocol_version = "HTTP/1.1"

    def _runtime(self) -> "HocusPocusRuntime":
        return self.server.runtime  # type: ignore[attr-defined]

    def _logger(self) -> logging.Logger:
        return self._runtime().logger.getChild("http")

    def end_headers(self) -> None:
        for name, value in self._runtime().host_identity.headers():
            self.send_header(name, value)
        broker_session_id = getattr(
            self, "_response_broker_session_id", None
        )
        if broker_session_id:
            self.send_header(
                "HocusPocus-Broker-Session-Id",
                broker_session_id,
            )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == self._runtime().settings.normalized_mcp_route:
            if not self._runtime().authorize(self.headers.get("Authorization", "")):
                self._write_plain(
                    HTTPStatus.UNAUTHORIZED,
                    "Unauthorized.\n",
                )
                return
            if not self._runtime().origin_allowed(self.headers.get("Origin")):
                self._write_plain(
                    HTTPStatus.FORBIDDEN,
                    "Origin not allowed.\n",
                )
                return
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
            self.end_headers()
            return
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
        self._response_session_id: str | None = None
        self._response_broker_session_id: str | None = None
        if self.path != self._runtime().settings.normalized_mcp_route:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not self._runtime().origin_allowed(self.headers.get("Origin")):
            self._write_plain(HTTPStatus.FORBIDDEN, "Origin not allowed.\n")
            return

        authorization = self.headers.get("Authorization", "")
        if not self._runtime().authorize(authorization):
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                error_response(
                    None,
                    JsonRpcError(
                        -32001,
                        "Unauthorized.",
                        {"authRequired": True},
                        family="auth",
                        retryable=False,
                    ),
                ),
            )
            return
        principal_id = self._runtime().principal_for_authorization(authorization)

        payload = self._read_request_payload()
        if payload is None:
            return

        protocol_error = self._runtime().validate_protocol_header(self.headers, payload)
        if protocol_error is not None:
            self._write_plain(HTTPStatus.BAD_REQUEST, protocol_error + "\n")
            return

        with self._runtime().host_identity.dispatch_lease():
            self._dispatch_admitted_payload(payload, principal_id)

    def _dispatch_admitted_payload(
        self, payload: Any, principal_id: str
    ) -> None:
        if self._reject_host_generation_mismatch():
            return
        admission = self._admit_request_session(payload, principal_id)
        if admission is None:
            return
        session_id, issued_session_id, resumed = admission
        response = self._runtime().handle_request(
            payload,
            principal_id=principal_id,
            session_id=session_id,
        )
        self._finalize_issued_session(
            issued_session_id,
            resumed,
            response,
        )
        if response is not None:
            self._write_json(HTTPStatus.OK, response)
            return
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        self.end_headers()

    def _finalize_issued_session(
        self, issued_session_id: str | None, resumed: bool, response: Any
    ) -> None:
        if issued_session_id is None:
            return
        if self._runtime().initialize_succeeded(response):
            self._response_session_id = issued_session_id
            self._response_broker_session_id = issued_session_id
        elif resumed:
            self._runtime().unbind_session(issued_session_id)
        else:
            self._runtime().revoke_session(issued_session_id)

    def _admit_request_session(
        self,
        payload: Any,
        principal_id: str,
    ) -> tuple[str | None, str | None, bool] | None:
        session_id = self.headers.get("Mcp-Session-Id")
        if self._runtime().payload_initializes(payload):
            resume_id = self.headers.get(
                "HocusPocus-Broker-Session-Id"
            )
            try:
                issued = self._runtime().issue_session(
                    principal_id,
                    self._runtime().client_info_from_payload(payload),
                    resume_session_id=resume_id,
                )
            except JsonRpcError as exc:
                self._write_json(
                    HTTPStatus.CONFLICT,
                    error_response(None, exc),
                )
                return None
            return issued.session_id, issued.session_id, resume_id is not None
        if session_id and not self._runtime().session_is_current(
            session_id,
            principal_id,
        ):
            self._write_json(
                HTTPStatus.NOT_FOUND,
                error_response(
                    None,
                    self._runtime().stale_session_error(session_id),
                ),
            )
            return None
        return session_id, None, False

    def _reject_host_generation_mismatch(self) -> bool:
        expected_host = self.headers.get(
            "HocusPocus-Host-Instance-Id"
        )
        expected_generation = self.headers.get(
            "HocusPocus-Host-Generation"
        )
        identity = self._runtime().host_identity
        mismatched = (
            bool(expected_host)
            and expected_host != identity.instance_id
        ) or (
            bool(expected_generation)
            and expected_generation != str(identity.generation)
        )
        if not mismatched:
            return False
        self._write_json(
            HTTPStatus.CONFLICT,
            error_response(
                None,
                self._runtime().host_generation_changed_error(),
            ),
        )
        return True

    def _read_request_payload(self) -> Any | None:
        content_length = self._content_length()
        if content_length is None:
            return None
        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length:
            self._write_plain(HTTPStatus.BAD_REQUEST, "Incomplete request body.\n")
            return None
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._write_json(
                HTTPStatus.OK,
                error_response(None, JsonRpcError(PARSE_ERROR, "Invalid JSON", str(exc))),
            )
            return None
        if (
            self._runtime().payload_uses_source_workspace(payload)
            and content_length > self._runtime().settings.workspace_payload_bytes
        ):
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                error_response(
                    None,
                    JsonRpcError(
                        INVALID_REQUEST,
                        "Source workspace request exceeds its configured payload limit.",
                        {
                            "hocusCode": "HOCUS830",
                            "limitBytes": self._runtime().settings.workspace_payload_bytes,
                        },
                        family="validation",
                        retryable=False,
                    ),
                ),
            )
            return None
        return payload

    def _content_length(self) -> int | None:
        transfer_encoding = str(self.headers.get("Transfer-Encoding", "") or "").strip()
        if transfer_encoding:
            self._write_plain(
                HTTPStatus.BAD_REQUEST,
                "Transfer-Encoding is unsupported; use bounded Content-Length.\n",
            )
            return None
        values = self.headers.get_all("Content-Length", [])
        raw = values[0] if len(values) == 1 else None
        if (
            not isinstance(raw, str)
            or not raw
            or not raw.isascii()
            or not raw.isdigit()
        ):
            self._write_plain(
                HTTPStatus.LENGTH_REQUIRED,
                "A non-negative Content-Length is required.\n",
            )
            return None
        length = int(raw)
        if length > _MAX_MCP_REQUEST_BYTES:
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                error_response(
                    None,
                    JsonRpcError(
                        INVALID_REQUEST,
                        "MCP request exceeds the transport payload limit.",
                        {
                            "hocusCode": "HOCUS830",
                            "limitBytes": _MAX_MCP_REQUEST_BYTES,
                        },
                        family="validation",
                        retryable=False,
                    ),
                ),
            )
            return None
        return length

    def _write_json(self, status: HTTPStatus, payload: Any) -> None:
        body = _json_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        response_session = getattr(self, "_response_session_id", None)
        if response_session is not None:
            self.send_header("Mcp-Session-Id", response_session)
        self.end_headers()
        self.wfile.write(body)

    def _write_plain(self, status: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
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
        self.host_identity = HostIdentity()
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self.dispatcher = LiveCommandDispatcher(logger)
        self.monitor = SceneEventMonitor(logger)
        self.dispatcher.set_monitor(self.monitor)
        self.operation_history = OperationHistory(
            host_instance_id=self.host_identity.instance_id,
            host_generation=self.host_identity.generation,
        )
        self.tasks = LiveTaskManager(self.dispatcher, logger)
        self._token = settings.resolved_token()
        self.workspace_authority = WorkspaceAuthority(settings, logger)
        self.workspace_authority.apply_configured_grants(self.host_principal_id)
        self.workspace_rate = self.workspace_authority.rate
        self.operations = LiveOperations(
            self.dispatcher,
            self.monitor,
            self.tasks,
            settings,
            logger,
        )
        self.operations._workspace_authority = self.workspace_authority
        self.operations._workspace_rate = self.workspace_rate
        self.operations._operation_history = self.operation_history
        self.operations._runtime = self
        self.operations.register(self.tools, self.resources)
        self.audit = AuditLogger(logger)
        self._default_capabilities = capability_set_from_settings(settings)
        self._server: RuntimeHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._host_scope_lock = threading.Lock()
        self._session_generations: dict[str, int] = {}
        self._generation_checkout_ids: set[str] = set()
        self._ever_started = False
        self._running = False

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            if self._ever_started:
                self._advance_host_generation()
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
            self._ever_started = True
            self.logger.info(
                "server %s started on %s with dispatcher mode=%s",
                __version__,
                self.settings.mcp_url,
                self.dispatcher.mode,
            )

    def stop(self) -> None:
        self._stop(close_authority=True)

    def _stop(self, *, close_authority: bool) -> None:
        with self._state_lock:
            if self._running:
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
            if close_authority:
                self.workspace_authority.close()
                self.operation_history.close()

    def restart(self) -> None:
        self._stop(close_authority=False)
        self.start()

    def status(self, *, include_secret: bool = False, include_sensitive: bool = True) -> dict[str, Any]:
        payload = {
            "serverVersion": __version__,
            "hostInstanceId": self.host_identity.instance_id,
            "hostGeneration": self.host_identity.generation,
            "running": self._running,
            "host": self.settings.host,
            "port": self.settings.port,
            "mcpUrl": self.settings.mcp_url,
            "healthUrl": self.settings.health_url,
            "tokenEnabled": self.settings.token_mode != "disabled",
            "authRequired": self.settings.token_mode != "disabled",
            "policyProfile": self.settings.policy_profile,
            "policyProfileSource": self.settings.policy_profile_source,
            "effectivePolicy": self.settings.effective_policy_payload(),
            "availablePolicyProfiles": self.settings.available_policy_profiles_payload(),
        }
        if include_secret and self.settings.token_mode != "disabled":
            payload["token"] = self._token
        if include_sensitive:
            payload["dispatcherMode"] = self.dispatcher.mode
            payload["activeOperations"] = self.dispatcher.operations_snapshot(limit=20)
            payload["activeTasks"] = self.tasks.snapshots(limit=20)
            payload["monitor"] = self.monitor.snapshot()
            payload["capabilities"] = list(self._default_capabilities)
            payload["readOnly"] = self.settings.read_only
        return payload

    def health_payload(self) -> dict[str, Any]:
        payload = self.status(include_secret=False, include_sensitive=False)
        payload["protocolVersion"] = PROTOCOL_VERSION
        payload["hostIdentity"] = self.host_identity.payload()
        return payload

    def authorize(self, header_value: str) -> bool:
        if self.settings.token_mode == "disabled":
            return True
        expected = f"Bearer {self._token}"
        return header_value == expected

    def principal_for_authorization(self, header_value: str) -> str:
        try:
            return principal_from_bearer(
                header_value,
                token_mode=self.settings.token_mode,
            )
        except WorkspaceGrantError as exc:
            raise JsonRpcError(
                -32001,
                "Unauthorized.",
                {"authRequired": True},
                family="auth",
                retryable=False,
            ) from exc

    @property
    def host_principal_id(self) -> str:
        header = ""
        if self.settings.token_mode != "disabled":
            header = f"Bearer {self._token}"
        return self.principal_for_authorization(header)

    def workspace_snapshot(self) -> dict[str, Any]:
        return self.workspace_authority.host_snapshot()

    def register_workspace_project(
        self,
        root: str,
        *,
        label: str | None = None,
        reapprove: bool = False,
    ) -> dict[str, Any]:
        project = self.workspace_authority.register_project(
            root,
            label=label,
            reapprove=reapprove,
        )
        return project.host_payload()

    def remove_workspace_project(self, project_id: str) -> dict[str, Any]:
        return self.workspace_authority.remove_project(project_id).host_payload()

    def grant_workspace_project(
        self,
        project_id: str,
        *,
        session_id: str | None = None,
        grants: tuple[str, ...],
        external_roots: dict[str, str] | None = None,
        persistent: bool = False,
        expires_in_seconds: float | None = None,
        until_revoked: bool = False,
    ) -> dict[str, Any]:
        principal_id = self.host_principal_id
        if session_id is not None:
            session = self.workspace_authority.session(session_id, touch=False)
            if session is None:
                raise ValueError("Selected MCP session is no longer active.")
            principal_id = session.principal_id
        grant = self.workspace_authority.host_grant(
            project_id,
            principal_id=principal_id,
            session_id=session_id,
            grants=grants,
            external_roots=external_roots,
            persistent=persistent,
            expires_in_seconds=expires_in_seconds,
            until_revoked=until_revoked,
        )
        return grant.host_payload(include_roots=True)

    def revoke_workspace_project(
        self,
        project_id: str,
        *,
        session_id: str | None = None,
        persistent: bool | None = None,
    ) -> bool:
        principal_id = self.host_principal_id
        if session_id is not None:
            session = self.workspace_authority.session(session_id, touch=False)
            if session is not None:
                principal_id = session.principal_id
        return self.workspace_authority.host_revoke(
            project_id,
            principal_id=principal_id,
            session_id=session_id,
            persistent=persistent,
        )

    def issue_session(
        self,
        principal_id: str,
        client_info: dict[str, Any] | None = None,
        *,
        resume_session_id: str | None = None,
    ):
        try:
            if resume_session_id is None:
                session = self.workspace_authority.issue_session(
                    principal_id, client_info
                )
            else:
                session = self.workspace_authority.resume_session(
                    resume_session_id,
                    principal_id,
                    client_info,
                )
        except WorkspaceGrantError as exc:
            raise JsonRpcError(
                -32002,
                "Broker session could not be resumed.",
                {
                    "hocusCode": exc.code,
                    "kind": "broker_session_resume_rejected",
                    "hostInstanceId": self.host_identity.instance_id,
                    "hostGeneration": self.host_identity.generation,
                    "reinitializeWithoutResume": True,
                },
                family="auth",
                retryable=True,
            ) from exc
        generation = self.host_identity.generation
        with self._host_scope_lock:
            self._session_generations[session.session_id] = generation
        return session

    def revoke_session(self, session_id: str) -> None:
        self.unbind_session(session_id)
        self.workspace_authority.revoke_session(session_id)

    def unbind_session(self, session_id: str) -> None:
        with self._host_scope_lock:
            self._session_generations.pop(session_id, None)

    def session_is_current(
        self, session_id: str, principal_id: str
    ) -> bool:
        with self._host_scope_lock:
            generation = self._session_generations.get(session_id)
        if generation != self.host_identity.generation:
            return False
        return self.workspace_authority.session(
            session_id,
            principal_id=principal_id,
        ) is not None

    def stale_session_error(self, session_id: str) -> JsonRpcError:
        return JsonRpcError(
            -32002,
            "MCP session belongs to a replaced host generation; initialize "
            "a new session.",
            {
                "hocusCode": "HOCUS999",
                "kind": "host_session_stale",
                "sessionId": session_id,
                "hostInstanceId": self.host_identity.instance_id,
                "hostGeneration": self.host_identity.generation,
                "mutationReplaySupported": False,
            },
            family="auth",
            retryable=True,
        )

    def host_generation_changed_error(self) -> JsonRpcError:
        return JsonRpcError(
            -32009,
            "Connected Houdini host generation changed before request "
            "dispatch.",
            {
                "hocusCode": "HOCUS999",
                "kind": "host_generation_changed",
                "hostInstanceId": self.host_identity.instance_id,
                "hostGeneration": self.host_identity.generation,
                "mutationReplaySupported": False,
            },
            family="runtime",
            retryable=True,
        )

    def _advance_host_generation(self) -> None:
        def transition() -> None:
            with self._host_scope_lock:
                self._session_generations.clear()
                self._generation_checkout_ids.clear()

        generation = self.host_identity.advance_exclusive(transition)
        self.operation_history.advance_host(
            self.host_identity.instance_id, generation
        )

    def list_authorized_projects(
        self, context: RequestContext
    ) -> tuple[dict[str, Any], ...]:
        return self.workspace_authority.list_projects(context)

    def authorize_workspace(
        self,
        context: RequestContext,
        project_id: str,
        required_grant: str,
        authority_projection_digest: str | None = None,
        *,
        external_alias: str | None = None,
    ):
        return self.workspace_authority.authorize(
            context,
            project_id,
            required_grant,
            authority_projection_digest,
            external_alias=external_alias,
        )

    @staticmethod
    def payload_initializes(payload: Any) -> bool:
        if isinstance(payload, dict):
            return payload.get("method") == "initialize"
        if isinstance(payload, list):
            return any(
                isinstance(item, dict) and item.get("method") == "initialize"
                for item in payload
            )
        return False

    @staticmethod
    def payload_uses_source_workspace(payload: Any) -> bool:
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            method = row.get("method")
            params = row.get("params")
            if method == "tools/call" and isinstance(params, dict):
                if str(params.get("name", "")).startswith("source."):
                    return True
            if method == "resources/read" and isinstance(params, dict):
                if str(params.get("uri", "")).startswith("hocus-source://"):
                    return True
        return False

    @staticmethod
    def client_info_from_payload(payload: Any) -> dict[str, Any]:
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict) or row.get("method") != "initialize":
                continue
            params = row.get("params")
            if isinstance(params, dict) and isinstance(params.get("clientInfo"), dict):
                return dict(params["clientInfo"])
        return {}

    @staticmethod
    def initialize_succeeded(response: Any) -> bool:
        rows = response if isinstance(response, list) else [response]
        return any(
            isinstance(row, dict)
            and isinstance(row.get("result"), dict)
            and isinstance(row["result"].get("serverInfo"), dict)
            for row in rows
        )

    def origin_allowed(self, origin_header: str | None) -> bool:
        if not origin_header:
            return True
        try:
            parsed = urlparse(origin_header)
        except Exception:
            return False
        hostname = (parsed.hostname or "").lower()
        allowed_hosts = {
            "127.0.0.1",
            "localhost",
            self.settings.host.lower(),
        }
        return hostname in allowed_hosts

    def validate_protocol_header(self, headers: Any, payload: Any) -> str | None:
        protocol_header = str(headers.get("MCP-Protocol-Version", "") or "").strip()
        if isinstance(payload, dict):
            method = payload.get("method")
            if method == "initialize":
                if protocol_header and protocol_header not in SUPPORTED_PROTOCOL_VERSIONS:
                    return "Unsupported MCP-Protocol-Version header."
                return None
        if not protocol_header:
            return None
        if protocol_header not in SUPPORTED_PROTOCOL_VERSIONS:
            return "Unsupported MCP-Protocol-Version header."
        return None

    def handle_request(
        self,
        payload: Any,
        *,
        principal_id: str = "local-runtime",
        session_id: str | None = None,
    ) -> Any:
        if isinstance(payload, list):
            responses = [
                self._handle_single(
                    item,
                    principal_id=principal_id,
                    session_id=session_id,
                )
                for item in payload
            ]
            return [item for item in responses if item is not None]
        return self._handle_single(
            payload,
            principal_id=principal_id,
            session_id=session_id,
        )

    def _handle_single(
        self,
        payload: Any,
        *,
        principal_id: str,
        session_id: str | None,
    ) -> dict[str, Any] | None:
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
                self._dispatch_method(
                    method,
                    params,
                    request_id,
                    principal_id=principal_id,
                    session_id=session_id,
                )
                return None

            result = self._dispatch_method(
                method,
                params,
                request_id,
                principal_id=principal_id,
                session_id=session_id,
            )
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
        *,
        principal_id: str,
        session_id: str | None,
    ) -> RequestContext:
        metadata = {
            "method": method,
            "requestId": request_id,
            "production_review_policy_id": (
                self.settings.production_review_policy_id
            ),
        }
        identity = getattr(self, "host_identity", None)
        if identity is not None:
            metadata["hostInstanceId"] = identity.instance_id
            metadata["hostGeneration"] = identity.generation
        timeout_seconds = float(
            params.get("_timeout_seconds", self.settings.request_timeout_seconds)
        )
        supplied_operation_id = params.get("_operation_id")
        if supplied_operation_id is not None and not valid_operation_id(
            supplied_operation_id
        ):
            raise JsonRpcError(
                INVALID_PARAMS, "Broker operation identity is invalid.",
                family="validation", retryable=False,
            )
        operation_id = supplied_operation_id or new_operation_id()
        return RequestContext(
            caller_id=principal_id,
            permissions=self._default_capabilities,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
            operation_id=operation_id,
            principal_id=principal_id,
            session_id=self._current_context_session(
                session_id,
                principal_id,
            ),
        )

    def _current_context_session(
        self,
        session_id: str | None,
        principal_id: str,
    ) -> str | None:
        generations = getattr(self, "_session_generations", None)
        if generations is not None and not self.session_is_current(
            str(session_id or ""),
            principal_id,
        ):
            return None
        session = self.workspace_authority.session(
            session_id,
            principal_id=principal_id,
        )
        return session_id if session is not None else None

    def _dispatch_method(
        self,
        method: str,
        params: dict[str, Any],
        request_id: Any,
        *,
        principal_id: str,
        session_id: str | None,
    ) -> Any:
        context = self._build_context(
            method,
            request_id,
            params,
            principal_id=principal_id,
            session_id=session_id,
        )
        static_handlers = {
            "initialize": lambda: self._initialize_payload(params),
            "ping": lambda: {},
            "tools/list": lambda: {"tools": self.tools.list_payload()},
            "resources/list": lambda: self._resources_list(params, context),
            "resources/templates/list": lambda: {
                "resourceTemplates": self.operations.resource_templates_payload()
            },
        }
        handler = static_handlers.get(method)
        if handler is not None:
            return handler()
        if method == "tools/call":
            return self._dispatch_tool_call(params, context)
        if method == "resources/read":
            return self._dispatch_resource_read(params, context)
        if method == "notifications/cancelled":
            return self._dispatch_cancellation(params)
        if method == "notifications/initialized":
            self.logger.info("client initialized")
            return None
        raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown method: {method}")

    def _resources_list(
        self,
        params: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise JsonRpcError(INVALID_PARAMS, "Resource cursor must be a string.")
        resources = [] if cursor else self.resources.list_payload()
        workspace_list = getattr(self.operations, "list_workspace_resources", None)
        if not callable(workspace_list):
            return {"resources": resources}
        workspace_payload = workspace_list(context, cursor)
        if not isinstance(workspace_payload, dict) or not isinstance(
            workspace_payload.get("resources"), list
        ):
            raise JsonRpcError(INTERNAL_ERROR, "Workspace resource listing failed.")
        resources.extend(workspace_payload["resources"])
        result: dict[str, Any] = {"resources": resources}
        next_cursor = workspace_payload.get("nextCursor")
        if isinstance(next_cursor, str) and next_cursor:
            result["nextCursor"] = next_cursor
        return result

    def _dispatch_tool_call(self, params: dict[str, Any], context: RequestContext) -> Any:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str):
            raise JsonRpcError(INVALID_PARAMS, "Tool call requires a string name.")
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "Tool arguments must be an object.")
        self._require_current_checkout(arguments)
        tool = self.tools.get(name)
        if tool is None:
            raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown tool: {name}")
        context.metadata["toolName"] = name
        return self._call_tool(tool, arguments, context)

    def _dispatch_resource_read(self, params: dict[str, Any], context: RequestContext) -> Any:
        uri = params.get("uri")
        if not isinstance(uri, str):
            raise JsonRpcError(INVALID_PARAMS, "Resource read requires a string uri.")
        checkout_id = self._checkout_id_from_resource_uri(uri)
        if checkout_id is not None:
            self._require_generation_checkout(checkout_id)
        resource = self.resources.get(uri)
        if resource is not None:
            return resource.reader(context)
        dynamic = self.operations.read_dynamic_resource(uri, context)
        if dynamic is not None:
            return dynamic
        raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown resource: {uri}")

    def _dispatch_cancellation(self, params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        operation_id = params.get("operationId")
        cancelled = (
            request_id is not None
            and self.dispatcher.cancel_by_request_id(str(request_id))
        )
        if not cancelled and operation_id is not None:
            cancelled = self.dispatcher.cancel(str(operation_id))
        self.logger.info(
            "received cancellation notification requestId=%s operationId=%s cancelled=%s",
            request_id,
            operation_id,
            cancelled,
        )

    def _call_tool(
        self,
        tool: Any,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return execute_tool_call(self, tool, arguments, context)

    def _require_current_checkout(self, arguments: dict[str, Any]) -> None:
        checkout_id = arguments.get("checkout_id")
        if checkout_id is None:
            return
        self._require_generation_checkout(str(checkout_id).strip())

    def _require_generation_checkout(self, checkout_id: str) -> None:
        with self._host_scope_lock:
            current = checkout_id in self._generation_checkout_ids
        if current:
            return
        raise JsonRpcError(
            INVALID_PARAMS,
            "Document checkout was not issued by the current Houdini host "
            "generation; create a new checkout.",
            {
                "checkoutId": checkout_id,
                "hostInstanceId": self.host_identity.instance_id,
                "hostGeneration": self.host_identity.generation,
                "mutationReplaySupported": False,
            },
            family="runtime",
            retryable=True,
        )

    def _track_generation_checkout(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        payload = result.get("structuredContent", result)
        checkout_id = (
            str(payload.get("checkoutId", "")).strip()
            if isinstance(payload, dict)
            else ""
        )
        with self._host_scope_lock:
            if (
                tool_name == "document.discard_checkout"
                and checkout_id
            ):
                self._generation_checkout_ids.discard(checkout_id)
            elif tool_name in {
                "document.checkout",
                "object.create_geometry",
            } and checkout_id:
                self._generation_checkout_ids.add(checkout_id)

    @staticmethod
    def _checkout_id_from_resource_uri(uri: str) -> str | None:
        prefixes = (
            "houdini://documents/checkouts/",
            "houdini://documents/diagnostics/",
        )
        for prefix in prefixes:
            if uri.startswith(prefix):
                return uri[len(prefix) :]
        return None

    @staticmethod
    def _should_bump_graph_revision(tool_name: str) -> bool:
        prefixes = (
            "node.",
            "parm.",
            "material.",
            "hda.",
            "dependency.",
            "lop.",
            "usd.",
            "lookdev.",
        )
        if tool_name.startswith(prefixes):
            return True
        return tool_name in {
            "scene.new",
            "scene.open_hip",
            "scene.merge_hip",
            "scene.undo",
            "scene.redo",
            "scene.create_turntable_camera",
            "graph.batch_edit",
            "graph.apply_patch",
            "model.create_house_blockout",
        }

    def _initialize_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        requested_version = str(params.get("protocolVersion", "") or "").strip()
        negotiated_version = PROTOCOL_VERSION
        if requested_version:
            if requested_version not in SUPPORTED_PROTOCOL_VERSIONS:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Unsupported protocol version.",
                    {
                        "requestedProtocolVersion": requested_version,
                        "supportedProtocolVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
                    },
                    family="request",
                    retryable=False,
                )
            negotiated_version = requested_version
        return {
            "protocolVersion": negotiated_version,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": __version__,
                "hostInstanceId": self.host_identity.instance_id,
                "hostGeneration": self.host_identity.generation,
            },
            "hostIdentity": self.host_identity.payload(),
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "logging": {},
            },
        }
