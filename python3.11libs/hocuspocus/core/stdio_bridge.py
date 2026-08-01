"""Persistent stdio broker for the embedded Houdini HTTP MCP host."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from hocuspocus.version import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_PROTOCOL_VERSIONS,
    __version__,
)
from .delivery import (
    delivery_error_response as _delivery_error_response,
    host_generation_changed as _host_generation_changed,
    prepare_operation_request as _prepare_operation_request,
    typed_error_payload as _typed_error_payload,
)
from .stdio_runtime import (
    MAX_MESSAGE_BYTES as _MAX_MESSAGE_BYTES,
    WORKER_SHUTDOWN_SECONDS as _WORKER_SHUTDOWN_SECONDS,
    BridgeInputError as _BridgeInputError,
    BrokerWorkers as _BrokerWorkers,
    ProtocolWriter as _ProtocolWriter,
    read_message as _read_message,
)

_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_CACHE_ENTRIES = 32
_CACHE_BYTES = 4 * 1024 * 1024
_RECONNECT_DELAY_SECONDS = 0.5
_WATCHER_INTERVAL_SECONDS = 0.5
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.0
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_DEFAULT_STARTUP_WAIT_SECONDS = 1.0
_MIN_TIMEOUT_SECONDS = 0.1
_MAX_TIMEOUT_SECONDS = 30.0
_CACHEABLE_METHODS = {
    "initialize",
    "tools/list",
}
_AUTH_REFRESH_METHODS = {
    "initialize",
    "ping",
    "resources/list",
    "resources/templates/list",
    "tools/list",
}
_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = len(_DIGEST_PREFIX) + 64


class _TransportFailure(Exception):
    pass


class _HttpFailure(Exception):
    def __init__(
        self,
        status: int,
        *,
        payload: Any = None,
        host_instance_id: str | None = None,
        host_generation: str | None = None,
    ):
        super().__init__(status)
        self.status = status
        self.payload = payload
        self.host_instance_id = host_instance_id
        self.host_generation = host_generation


class _CredentialChanged(Exception):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class _BrokerCredential:
    secret: str = field(repr=False)
    config_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.secret, str) or not all(
            map(_valid_digest, (self.config_digest, self.manifest_digest))
        ):
            raise ValueError("Invalid broker credential authority.")


def _valid_digest(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != _DIGEST_LENGTH:
        return False
    return value.startswith(_DIGEST_PREFIX) and all(
        character in "0123456789abcdef" for character in value[7:]
    )


@dataclass(frozen=True, slots=True)
class _UpstreamResponse:
    payload: Any
    session_id: str | None = None
    broker_session_id: str | None = None
    host_instance_id: str | None = None
    host_generation: str | None = None


@dataclass(frozen=True, slots=True)
class _RecoveryResult:
    succeeded: bool
    error: Any = None


class _DiscoveryCache:
    def __init__(
        self,
        *,
        max_entries: int = _CACHE_ENTRIES,
        max_bytes: int = _CACHE_BYTES,
    ):
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[int, Any]] = OrderedDict()
        self._bytes = 0

    @staticmethod
    def key(message: dict[str, Any]) -> str | None:
        method = message.get("method")
        if method not in _CACHEABLE_METHODS:
            return None
        params = message.get("params", {})
        try:
            encoded = json.dumps(
                params,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return None
        return f"{method}:{hashlib.sha256(encoded).hexdigest()}"

    def get(self, message: dict[str, Any]) -> Any | None:
        key = self.key(message)
        if key is None or key not in self._entries:
            return None
        size, payload = self._entries.pop(key)
        self._entries[key] = (size, payload)
        return _response_for_request(copy.deepcopy(payload), message)

    def put(self, message: dict[str, Any], response: Any) -> None:
        key = self.key(message)
        if key is None or not _response_succeeded(response):
            return
        try:
            size = len(
                json.dumps(
                    response,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return
        if size > self._max_bytes:
            return
        prior = self._entries.pop(key, None)
        if prior is not None:
            self._bytes -= prior[0]
        self._entries[key] = (size, copy.deepcopy(response))
        self._bytes += size
        while (
            len(self._entries) > self._max_entries
            or self._bytes > self._max_bytes
        ):
            _, (removed_size, _) = self._entries.popitem(last=False)
            self._bytes -= removed_size

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = 0


def _bounded_timeout(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    if not (parsed > 0):
        return default
    return min(max(parsed, _MIN_TIMEOUT_SECONDS), _MAX_TIMEOUT_SECONDS)


def _request_target(url: str) -> tuple[type[http.client.HTTPConnection], str, int, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise _TransportFailure() from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _TransportFailure()
    connection_type: type[http.client.HTTPConnection]
    if parsed.scheme == "https":
        connection_type = http.client.HTTPSConnection
    else:
        connection_type = http.client.HTTPConnection
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    return connection_type, parsed.hostname, port, target


def _proxy_headers(
    *,
    body_length: int,
    token: str,
    payload: Any,
    session_id: str | None,
    protocol_version: str | None,
    broker_session_id: str | None,
    host_instance_id: str | None,
    host_generation: str | None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(body_length),
    }
    optional_headers = (
        ("Authorization", f"Bearer {token}" if token else None),
        ("Mcp-Session-Id", session_id),
        ("MCP-Protocol-Version", protocol_version),
        (
            "HocusPocus-Broker-Session-Id",
            broker_session_id
            if _payload_has_method(payload, "initialize")
            else None,
        ),
        (
            "HocusPocus-Host-Instance-Id",
            host_instance_id
            if not _payload_has_method(payload, "initialize")
            else None,
        ),
        (
            "HocusPocus-Host-Generation",
            host_generation
            if not _payload_has_method(payload, "initialize")
            else None,
        ),
    )
    headers.update(
        {
            name: value
            for name, value in optional_headers
            if isinstance(value, str) and value
        }
    )
    return headers


def _read_upstream_response(
    connection: http.client.HTTPConnection,
) -> _UpstreamResponse:
    response = connection.getresponse()
    response_session = response.getheader("Mcp-Session-Id")
    response_broker_session = response.getheader("HocusPocus-Broker-Session-Id")
    response_host = response.getheader("HocusPocus-Host-Instance-Id")
    response_generation = response.getheader("HocusPocus-Host-Generation")
    content = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(content) > _MAX_RESPONSE_BYTES:
        raise _TransportFailure()
    parsed_payload = _decode_upstream_payload(content)
    if response.status >= 400:
        raise _HttpFailure(
            response.status,
            payload=parsed_payload,
            host_instance_id=response_host,
            host_generation=response_generation,
        )
    return _UpstreamResponse(
        parsed_payload,
        session_id=response_session,
        broker_session_id=response_broker_session,
        host_instance_id=response_host,
        host_generation=response_generation,
    )


def _decode_upstream_payload(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _TransportFailure() from exc


def _proxy(
    url: str,
    token: str,
    payload: Any,
    *,
    session_id: str | None = None,
    protocol_version: str | None = None,
    broker_session_id: str | None = None,
    host_instance_id: str | None = None,
    host_generation: str | None = None,
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS,
    request_timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> _UpstreamResponse:
    connection_type, host, port, target = _request_target(url)
    try:
        body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _TransportFailure() from exc
    if len(body) > _MAX_MESSAGE_BYTES:
        raise _TransportFailure()
    headers = _proxy_headers(
        body_length=len(body),
        token=token,
        payload=payload,
        session_id=session_id,
        protocol_version=protocol_version,
        broker_session_id=broker_session_id,
        host_instance_id=host_instance_id,
        host_generation=host_generation,
    )

    connection = connection_type(host, port, timeout=connect_timeout)
    try:
        connection.connect()
        if connection.sock is not None:
            connection.sock.settimeout(request_timeout)
        connection.request("POST", target, body=body, headers=headers)
        return _read_upstream_response(connection)
    except _HttpFailure:
        raise
    except Exception as exc:
        raise _TransportFailure() from exc
    finally:
        connection.close()


def _payload_has_method(payload: Any, method: str) -> bool:
    rows = payload if isinstance(payload, list) else [payload]
    return any(isinstance(row, dict) and row.get("method") == method for row in rows)


def _auth_refresh_safe(payload: Any) -> bool:
    rows = payload if isinstance(payload, list) else [payload]
    return bool(rows) and all(
        isinstance(row, dict) and row.get("method") in _AUTH_REFRESH_METHODS
        for row in rows
    )


def _response_succeeded(response: Any) -> bool:
    return isinstance(response, dict) and "result" in response and "error" not in response


def _response_for_request(response: Any, request: dict[str, Any]) -> Any:
    if isinstance(response, dict):
        response["id"] = request.get("id")
    return response


def _offline_initialize_response(
    request: dict[str, Any],
    protocol_version: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {
            "protocolVersion": protocol_version,
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"listChanged": True, "subscribe": False},
                "logging": {},
            },
            "hostOnline": False,
        },
    }


def _initialize_protocol(request: dict[str, Any]) -> str | None:
    params = request.get("params", {})
    if not isinstance(params, dict):
        return None
    requested = str(params.get("protocolVersion", "") or "").strip()
    if requested and requested not in SUPPORTED_PROTOCOL_VERSIONS:
        return None
    return requested or PROTOCOL_VERSION


def _resume_reinitialize_allowed(failure: _HttpFailure) -> bool:
    payload = failure.payload
    if failure.status != 409 or not isinstance(payload, dict):
        return False
    error = payload.get("error")
    data = error.get("data") if isinstance(error, dict) else None
    return (
        isinstance(data, dict)
        and data.get("kind") == "broker_session_resume_rejected"
        and data.get("reinitializeWithoutResume") is True
    )


def _http_error_response(request_id: Any, status: int) -> dict[str, Any]:
    auth_failure = status in {401, 403}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32001 if auth_failure else -32099,
            "message": "Houdini host authorization failed." if auth_failure else "Houdini host rejected the request.",
            "data": {
                "hocusCode": "HOCUS999",
                "kind": "auth" if auth_failure else "upstream_rejected",
                "retryable": False,
                "httpStatus": status,
            },
        },
    }


ProxyCallable = Callable[..., _UpstreamResponse]


class StdioBroker:
    """One durable client session mapped onto replaceable Houdini host sessions."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        proxy: ProxyCallable = _proxy,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
        startup_wait_seconds: float = _DEFAULT_STARTUP_WAIT_SECONDS,
        credential: _BrokerCredential | None = None,
        credential_provider: Callable[[], _BrokerCredential] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        notify: Callable[[Any], None] | None = None,
    ):
        self._url = url
        self._credential = credential
        self._token = credential.secret if credential is not None else token
        self._credential_provider = credential_provider
        self._proxy = proxy
        self._connect_timeout = min(
            max(connect_timeout, _MIN_TIMEOUT_SECONDS),
            _MAX_TIMEOUT_SECONDS,
        )
        self._request_timeout = min(
            max(request_timeout, _MIN_TIMEOUT_SECONDS),
            _MAX_TIMEOUT_SECONDS,
        )
        self._startup_wait = min(
            max(startup_wait_seconds, _MIN_TIMEOUT_SECONDS),
            _MAX_TIMEOUT_SECONDS,
        )
        self._clock = clock
        self._sleep = sleep
        self._notify = notify
        self._state_lock = threading.RLock()
        self._credential_lock = threading.Lock()
        self._recovery_lock = threading.Lock()
        self._watcher_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._initialize_event = threading.Event()
        self._watcher: threading.Thread | None = None
        self._logical_session_id: str | None = None
        self._upstream_session_id: str | None = None
        self._host_instance_id: str | None = None
        self._host_generation: str | None = None
        self._initialize_request: dict[str, Any] | None = None
        self._protocol_version: str | None = None
        self._client_initialized = False
        self._ever_connected = False
        self._session_authority_replaced = False
        self._authority_epoch = 0
        self._credential_epoch = 0
        self._session_credential_epoch = -1
        identity = ((credential.config_digest, credential.manifest_digest)
                    if credential is not None else None)
        self._credential_history = {identity} if identity is not None else set()
        self._online = False
        self._next_reconnect_at = 0.0
        self._cache = _DiscoveryCache()
        self._read_only_tools: set[str] = set()

    @property
    def host_generation(self) -> str | None:
        return self._host_generation

    @property
    def host_instance_id(self) -> str | None:
        return self._host_instance_id

    @property
    def upstream_session_id(self) -> str | None:
        return self._upstream_session_id

    @property
    def session_authority_replaced(self) -> bool:
        return self._session_authority_replaced

    def _post_with_epoch(
        self,
        payload: Any,
        *,
        allow_credential_refresh: bool = True,
    ) -> tuple[_UpstreamResponse, int]:
        with self._state_lock:
            epoch = self._authority_epoch
            credential_epoch = self._credential_epoch
            credential = self._credential
            session_id = self._upstream_session_id
            protocol_version = self._protocol_version
            broker_session_id = self._logical_session_id
            host_instance_id = self._host_instance_id
            host_generation = self._host_generation
            token = self._token
        def send(selected_token: str) -> _UpstreamResponse:
            return self._proxy(
                self._url,
                selected_token,
                payload,
                session_id=session_id,
                protocol_version=protocol_version,
                broker_session_id=broker_session_id,
                host_instance_id=host_instance_id,
                host_generation=host_generation,
                connect_timeout=self._connect_timeout,
                request_timeout=self._request_timeout,
            )
        try:
            return send(token), epoch
        except _HttpFailure as exc:
            if allow_credential_refresh and self._refresh_auth_credential(
                payload,
                exc.status,
                credential,
                credential_epoch,
            ):
                raise _CredentialChanged() from exc
            exc.broker_epoch = epoch
            raise
        except (_HttpFailure, _TransportFailure) as exc:
            exc.broker_epoch = epoch
            raise

    def _refresh_auth_credential(
        self,
        payload: Any,
        status: int,
        failed: _BrokerCredential | None,
        failed_epoch: int,
    ) -> bool:
        if (
            status != 401
            or self._credential_provider is None
            or not _auth_refresh_safe(payload)
            or failed is None
        ):
            return False
        with self._credential_lock:
            if self._credential_already_changed(failed, failed_epoch):
                return True
            try:
                refreshed = self._credential_provider()
            except Exception:
                return False
            if not isinstance(refreshed, _BrokerCredential):
                return False
            return self._admit_refreshed_credential(
                failed,
                failed_epoch,
                refreshed,
            )

    def _credential_already_changed(
        self, failed: _BrokerCredential, failed_epoch: int
    ) -> bool:
        with self._state_lock:
            current = self._credential
            changed = self._credential_epoch != failed_epoch
            return changed and current is not None and current != failed

    def _admit_refreshed_credential(
        self,
        failed: _BrokerCredential,
        failed_epoch: int,
        refreshed: _BrokerCredential,
    ) -> bool:
        identity = (refreshed.config_digest, refreshed.manifest_digest)
        with self._state_lock:
            if self._credential_epoch != failed_epoch or self._credential != failed:
                return self._credential_already_changed(failed, failed_epoch)
            if refreshed == failed or identity in self._credential_history:
                return False
            self._credential = refreshed
            self._token = refreshed.secret
            self._credential_epoch += 1
            self._credential_history.add(identity)
            self._authority_epoch += 1
            self._session_credential_epoch = -1
            self._online = False
            self._upstream_session_id = None
            self._next_reconnect_at = 0.0
            self._cache.clear()
            return True

    def _post(
        self,
        payload: Any,
        *,
        allow_credential_refresh: bool = True,
    ) -> _UpstreamResponse:
        return self._post_with_epoch(
            payload, allow_credential_refresh=allow_credential_refresh
        )[0]

    def _current_epoch(self) -> int:
        with self._state_lock:
            return self._authority_epoch

    def _mark_offline(self, epoch: int | None = None) -> bool:
        with self._state_lock:
            if epoch is not None and epoch != self._authority_epoch:
                return False
            self._online = False
            self._upstream_session_id = None
            self._next_reconnect_at = self._clock() + _RECONNECT_DELAY_SECONDS
            self._authority_epoch += 1
            return True

    def _observe_response(
        self,
        request: dict[str, Any],
        response: _UpstreamResponse,
        epoch: int,
    ) -> bool:
        with self._state_lock:
            if epoch != self._authority_epoch:
                return False
            method = request.get("method")
            if response.host_instance_id:
                self._host_instance_id = response.host_instance_id
            if response.host_generation:
                self._host_generation = response.host_generation
            if method == "initialize" and _response_succeeded(response.payload):
                if (
                    not response.session_id
                    or response.broker_session_id != response.session_id
                ):
                    self._mark_offline(epoch)
                    return False
                if (
                    self._logical_session_id is not None
                    and response.broker_session_id != self._logical_session_id
                ):
                    self._mark_offline(epoch)
                    return False
                self._initialize_request = copy.deepcopy(request)
                self._upstream_session_id = response.session_id
                self._logical_session_id = response.broker_session_id
                result = response.payload.get("result", {})
                version = result.get("protocolVersion") if isinstance(result, dict) else None
                self._protocol_version = str(version) if version else None
                self._ever_connected = True
                self._session_credential_epoch = self._credential_epoch
                self._authority_epoch += 1
            if method == "notifications/initialized":
                self._client_initialized = True
            self._online = True
            if response.payload is not None:
                self._cache.put(request, response.payload)
            if method == "tools/list" and _response_succeeded(response.payload):
                tools = response.payload.get("result", {}).get("tools", [])
                self._read_only_tools = {
                    item["name"] for item in tools
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                    and isinstance(item.get("annotations"), dict)
                    and item["annotations"].get("readOnlyHint") is True
                }
            return True

    def _post_recovery_initialize(
        self,
        request: dict[str, Any],
        *,
        allow_credential_refresh: bool,
    ) -> tuple[_UpstreamResponse, int]:
        try:
            return self._post_with_epoch(
                request,
                allow_credential_refresh=allow_credential_refresh,
            )
        except _HttpFailure as exc:
            with self._state_lock:
                had_resume_id = self._logical_session_id is not None
            if not had_resume_id or not _resume_reinitialize_allowed(exc):
                raise
            with self._state_lock:
                if exc.host_instance_id:
                    self._host_instance_id = exc.host_instance_id
                if exc.host_generation:
                    self._host_generation = exc.host_generation
                self._logical_session_id = None
                self._upstream_session_id = None
                self._session_authority_replaced = True
                self._authority_epoch += 1
                fresh_epoch = self._authority_epoch
            response, response_epoch = self._post_with_epoch(
                request,
                allow_credential_refresh=allow_credential_refresh,
            )
            if response_epoch != fresh_epoch:
                failure = _TransportFailure()
                failure.broker_epoch = fresh_epoch
                raise failure
            return response, response_epoch

    def _recover_locked(
        self,
        *,
        allow_credential_refresh: bool = True,
    ) -> _RecoveryResult:
        with self._state_lock:
            if (
                self._online
                and self._upstream_session_id is not None
                and self._session_credential_epoch == self._credential_epoch
            ):
                return _RecoveryResult(True)
            if self._initialize_request is None:
                return _RecoveryResult(False)
            if self._clock() < self._next_reconnect_at:
                return _RecoveryResult(False)
            request = copy.deepcopy(self._initialize_request)
            request["id"] = f"broker-reinitialize-{secrets.token_hex(8)}"
            self._upstream_session_id = None
            self._authority_epoch += 1
        try:
            response, epoch = self._post_recovery_initialize(
                request,
                allow_credential_refresh=allow_credential_refresh,
            )
        except _CredentialChanged:
            return self._retry_credential_recovery(allow_credential_refresh)
        except _HttpFailure as exc:
            failure_epoch = getattr(
                exc,
                "broker_epoch",
                self._current_epoch(),
            )
            self._mark_offline(failure_epoch)
            return _RecoveryResult(False, exc.payload)
        except _TransportFailure as exc:
            failure_epoch = getattr(
                exc,
                "broker_epoch",
                self._current_epoch(),
            )
            self._mark_offline(failure_epoch)
            return _RecoveryResult(False)
        if not _response_succeeded(response.payload):
            self._mark_offline(epoch)
            return _RecoveryResult(False, response.payload)
        if not self._observe_response(request, response, epoch):
            return _RecoveryResult(False)
        with self._state_lock:
            client_initialized = self._client_initialized
        if not client_initialized:
            return _RecoveryResult(True)
        return self._finish_recovery_notification(allow_credential_refresh)

    def _retry_credential_recovery(self, allowed: bool) -> _RecoveryResult:
        if not allowed:
            return _RecoveryResult(False)
        return self._recover_locked(allow_credential_refresh=False)

    def _finish_recovery_notification(self, allow_refresh: bool) -> _RecoveryResult:
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        notification_epoch = self._current_epoch()
        try:
            self._post(
                notification,
                allow_credential_refresh=allow_refresh,
            )
        except _CredentialChanged:
            return self._retry_credential_recovery(allow_refresh)
        except _HttpFailure as exc:
            failure_epoch = getattr(exc, "broker_epoch", notification_epoch)
            self._mark_offline(failure_epoch)
            return _RecoveryResult(False, exc.payload)
        except _TransportFailure as exc:
            failure_epoch = getattr(exc, "broker_epoch", notification_epoch)
            self._mark_offline(failure_epoch)
            return _RecoveryResult(False)
        return _RecoveryResult(True)

    def _recover(self) -> _RecoveryResult:
        with self._recovery_lock:
            return self._recover_locked()

    def _recover_changed_generation(
        self, failure: _HttpFailure
    ) -> _RecoveryResult:
        with self._state_lock:
            self._host_instance_id = failure.host_instance_id
            self._host_generation = failure.host_generation
            self._online = False
            self._upstream_session_id = None
            self._next_reconnect_at = 0.0
            self._authority_epoch += 1
        return self._recover()

    def _cached_or_error(self, request: dict[str, Any]) -> Any:
        with self._state_lock:
            cached = self._cache.get(request)
            host_generation = self._host_generation
            if cached is not None:
                return cached
            if request.get("id") is None:
                return None
            return _delivery_error_response(
                request,
                kind="host_offline",
                host_instance_id=self._host_instance_id,
                host_generation=host_generation,
            )

    def _handle_http_failure(
        self,
        request: dict[str, Any],
        failure: _HttpFailure,
        *,
        allow_generation_retry: bool,
        epoch: int,
    ) -> Any:
        with self._state_lock:
            epoch_is_current = epoch == self._authority_epoch
            guarded = (
                self._host_instance_id is not None
                or self._host_generation is not None
            )
        if (
            failure.status == 401
            and self._credential_provider is not None
            and not _auth_refresh_safe(request)
        ):
            self._mark_offline(epoch)
            with self._state_lock:
                self._next_reconnect_at = 0.0
            self._recover()
        generation_changed = (
            epoch_is_current
            and _host_generation_changed(failure.status, failure.payload)
            and guarded
        )
        read_only_retry = (
            allow_generation_retry
            and (
                request.get("method") != "tools/call"
                or request.get("params", {}).get("name") in self._read_only_tools
            )
        )
        if generation_changed:
            recovery = self._recover_changed_generation(failure)
        else:
            recovery = None
        if recovery is not None and read_only_retry:
            if recovery.succeeded:
                return self._forward(request, allow_generation_retry=False)
            if recovery.error is not None:
                return _response_for_request(copy.deepcopy(recovery.error), request)
            return self._cached_or_error(request)
        if _typed_error_payload(failure.payload):
            return _response_for_request(copy.deepcopy(failure.payload), request)
        if failure.status >= 500:
            self._mark_offline(epoch)
            if request.get("method") in _CACHEABLE_METHODS:
                return self._cached_or_error(request)
            return self._delivery_failure(request)
        if request.get("id") is None:
            return None
        if isinstance(failure.payload, dict):
            return _response_for_request(copy.deepcopy(failure.payload), request)
        return _http_error_response(request.get("id"), failure.status)

    def _delivery_failure(self, request: dict[str, Any]) -> Any:
        if request.get("id") is None:
            return None
        kind = (
            "ambiguous_delivery"
            if request.get("method") == "tools/call"
            else "host_offline"
        )
        with self._state_lock:
            host_generation = self._host_generation
            host_instance_id = self._host_instance_id
        return _delivery_error_response(
            request,
            kind=kind,
            host_instance_id=host_instance_id,
            host_generation=host_generation,
        )

    def _wait_for_initial_host(self) -> _RecoveryResult:
        deadline = self._clock() + self._startup_wait
        while not self._stop_event.is_set():
            recovery = self._recover()
            if recovery.succeeded or recovery.error is not None:
                return recovery
            remaining = deadline - self._clock()
            if remaining <= 0:
                return _RecoveryResult(False)
            with self._state_lock:
                until_retry = max(
                    0.0,
                    self._next_reconnect_at - self._clock(),
                )
            self._sleep(min(remaining, max(0.01, until_retry)))
        return _RecoveryResult(False)

    def _prime_tool_catalogue(self) -> bool:
        request = {
            "jsonrpc": "2.0",
            "id": f"broker-tools-{secrets.token_hex(8)}",
            "method": "tools/list",
            "params": {},
        }
        response = self._forward(request)
        return (
            isinstance(response, dict)
            and isinstance(response.get("result"), dict)
            and isinstance(response["result"].get("tools"), list)
        )

    def _emit_list_changed(self) -> None:
        if self._notify is None:
            return
        for method in (
            "notifications/tools/list_changed",
            "notifications/resources/list_changed",
        ):
            try:
                self._notify(
                    {"jsonrpc": "2.0", "method": method, "params": {}}
                )
            except Exception:
                return

    def _watch_for_host(self) -> None:
        while not self._stop_event.wait(_WATCHER_INTERVAL_SECONDS):
            recovery = self._recover()
            if recovery.error is not None:
                return
            if recovery.succeeded and self._prime_tool_catalogue():
                self._emit_list_changed()
                return

    def _start_host_watcher(self) -> None:
        with self._watcher_lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            self._watcher = threading.Thread(
                target=self._watch_for_host,
                name="HocusPocusHostWatcher",
                daemon=True,
            )
            self._watcher.start()

    def close(self) -> None:
        self._stop_event.set()
        with self._watcher_lock:
            watcher = self._watcher
        if watcher is not None:
            watcher.join(timeout=_WORKER_SHUTDOWN_SECONDS)

    def _cold_start_tools_list(self, request: dict[str, Any]) -> Any:
        recovery = self._wait_for_initial_host()
        if recovery.error is not None:
            return _response_for_request(copy.deepcopy(recovery.error), request)
        if recovery.succeeded:
            return self._forward(request)
        self._start_host_watcher()
        return self._cached_or_error(request)

    def _forward(
        self,
        request: dict[str, Any],
        *,
        allow_generation_retry: bool = True,
        allow_credential_retry: bool = True,
    ) -> Any:
        try:
            response, epoch = self._post_with_epoch(
                request,
                allow_credential_refresh=allow_credential_retry,
            )
        except _CredentialChanged:
            if not allow_credential_retry:
                return _http_error_response(request.get("id"), 401)
            recovery = self._recover()
            if recovery.error is not None:
                return _response_for_request(copy.deepcopy(recovery.error), request)
            if not recovery.succeeded or request.get("method") == "initialize":
                return self._cached_or_error(request)
            return self._forward(
                request,
                allow_generation_retry=allow_generation_retry,
                allow_credential_retry=False,
            )
        except _HttpFailure as exc:
            epoch = getattr(exc, "broker_epoch", self._current_epoch())
            return self._handle_http_failure(
                request,
                exc,
                allow_generation_retry=allow_generation_retry,
                epoch=epoch,
            )
        except _TransportFailure as exc:
            epoch = getattr(exc, "broker_epoch", self._current_epoch())
            self._mark_offline(epoch)
            if request.get("method") in _CACHEABLE_METHODS:
                return self._cached_or_error(request)
            return self._delivery_failure(request)
        if not self._observe_response(request, response, epoch):
            if request.get("method") == "tools/call":
                return self._delivery_failure(request)
            return self._cached_or_error(request)
        return response.payload

    def _handle_one(self, request: Any) -> Any:
        if not isinstance(request, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        request = _prepare_operation_request(request)
        method = request.get("method")
        if method != "initialize":
            with self._state_lock:
                has_initialize = self._initialize_request is not None
            if not has_initialize:
                self._initialize_event.wait(timeout=self._startup_wait)
        if method == "notifications/initialized":
            with self._state_lock:
                self._client_initialized = True
        if method == "initialize":
            protocol_version = _initialize_protocol(request)
            if protocol_version is None:
                self._initialize_event.set()
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32602,
                        "message": "Unsupported protocol version.",
                    },
                }
            with self._state_lock:
                self._initialize_request = copy.deepcopy(request)
                self._protocol_version = protocol_version
            offline_response = _offline_initialize_response(
                request,
                protocol_version,
            )
            with self._state_lock:
                self._cache.put(request, offline_response)
            try:
                return self._forward(request)
            finally:
                self._initialize_event.set()
        with self._state_lock:
            online = self._online
            has_initialize = self._initialize_request is not None
            cold_start = not self._ever_connected
        if (
            method == "tools/list"
            and not online
            and has_initialize
            and cold_start
        ):
            return self._cold_start_tools_list(request)
        if not online and has_initialize:
            recovery = self._recover()
            if recovery.error is not None:
                return _response_for_request(copy.deepcopy(recovery.error), request)
        with self._state_lock:
            online = self._online
        if not online:
            return self._cached_or_error(request)
        return self._forward(request)

    def handle(self, payload: Any) -> Any:
        if not isinstance(payload, list):
            return self._handle_one(payload)
        if not payload:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        responses = []
        for request in payload:
            response = self._handle_one(request)
            if response is not None:
                responses.append(response)
        return responses


def _input_error_response() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": -32700,
            "message": "Invalid JSON-RPC input.",
            "data": {"retryable": False},
        },
    }


def main(
    *,
    token: str | None = None,
    credential: _BrokerCredential | None = None,
    credential_provider: Callable[[], _BrokerCredential] | None = None,
) -> int:
    url = os.environ.get("HOCUSPOCUS_HTTP_URL", "http://127.0.0.1:37219/hocuspocus/mcp")
    if token is None:
        token = os.environ.get("HOCUSPOCUS_TOKEN", "")
    connect_timeout = _bounded_timeout(
        os.environ.get("HOCUSPOCUS_CONNECT_TIMEOUT_SECONDS"), _DEFAULT_CONNECT_TIMEOUT_SECONDS
    )
    request_timeout = _bounded_timeout(
        os.environ.get("HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS"), _DEFAULT_REQUEST_TIMEOUT_SECONDS
    )
    startup_wait = _bounded_timeout(
        os.environ.get("HOCUSPOCUS_STARTUP_WAIT_SECONDS"), _DEFAULT_STARTUP_WAIT_SECONDS
    )
    writer = _ProtocolWriter()
    broker = StdioBroker(
        url,
        token,
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
        startup_wait_seconds=startup_wait,
        credential=credential,
        credential_provider=credential_provider,
        notify=writer.notify,
    )
    workers = _BrokerWorkers(broker.handle, broker.close, writer)
    try:
        while True:
            try:
                inbound = _read_message()
            except _BridgeInputError as exc:
                writer.write(_input_error_response(), exc.framing)
                continue
            if inbound is None:
                return 0
            workers.submit(inbound)
    finally:
        workers.close()


if __name__ == "__main__":
    raise SystemExit(main())
