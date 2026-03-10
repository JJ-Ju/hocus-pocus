"""JSON-RPC helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(slots=True)
class JsonRpcError(Exception):
    code: int
    message: str
    data: Any = None
    family: str | None = None
    retryable: bool | None = None

    def _normalized_family(self) -> str:
        if self.family:
            return self.family
        if self.code == PARSE_ERROR:
            return "request"
        if self.code == INVALID_REQUEST:
            return "request"
        if self.code == METHOD_NOT_FOUND:
            return "unsupported"
        if self.code == INVALID_PARAMS:
            return "validation"
        if self.code in {-32001}:
            return "auth"
        if self.code in {-32010, -32011}:
            return "policy"
        if self.code == -32800:
            return "cancelled"
        return "runtime"

    def _normalized_retryable(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return self._normalized_family() in {"runtime"}

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
        }
        data: dict[str, Any] = {}
        if isinstance(self.data, dict):
            data.update(self.data)
        elif self.data is not None:
            data["details"] = self.data
        data.setdefault("errorFamily", self._normalized_family())
        data.setdefault("retryable", self._normalized_retryable())
        payload["data"] = data
        return payload


def success_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def error_response(request_id: Any, error: JsonRpcError) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error.to_payload(),
    }
