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

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            payload["data"] = self.data
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
