"""Stable broker-to-host operation identity and delivery errors."""

from __future__ import annotations

import copy
import re
import secrets
from typing import Any


_OPERATION_ID = re.compile(r"op:[0-9a-f]{32}")


def prepare_operation_request(request: dict[str, Any]) -> dict[str, Any]:
    """Copy a tool request and attach one identity retained across retries."""
    if request.get("method") != "tools/call":
        return request
    prepared = copy.deepcopy(request)
    params = prepared.get("params")
    if not isinstance(params, dict):
        return prepared
    operation_id = params.get("_operation_id")
    if not isinstance(operation_id, str) or _OPERATION_ID.fullmatch(operation_id) is None:
        params["_operation_id"] = f"op:{secrets.token_hex(16)}"
    return prepared


def operation_fields(request: dict[str, Any]) -> tuple[str | None, str | None]:
    params = request.get("params")
    if not isinstance(params, dict):
        return None, None
    operation_id = params.get("_operation_id")
    tool_name = params.get("name")
    return (
        operation_id if isinstance(operation_id, str) else None,
        tool_name if isinstance(tool_name, str) else None,
    )


def delivery_error_response(
    request: dict[str, Any],
    *,
    kind: str,
    host_instance_id: str | None,
    host_generation: str | None,
) -> dict[str, Any]:
    ambiguous = kind == "ambiguous_delivery"
    operation_id, tool_name = operation_fields(request)
    data: dict[str, Any] = {
        "hocusCode": "HOCUS999",
        "kind": kind,
        "retryable": not ambiguous,
        "hostInstanceId": host_instance_id,
        "hostGeneration": host_generation,
        "operationId": operation_id,
        "toolName": tool_name,
        "deliveryStage": "response_unknown" if ambiguous else "not_delivered",
        "commitState": "unknown" if ambiguous else "not_committed",
        "mayHaveCrossedCommitBoundary": ambiguous,
    }
    if ambiguous and operation_id:
        data["reconciliation"] = {
            "tool": "session.get_operation",
            "arguments": {"operation_id": operation_id},
            "replaysMutation": False,
        }
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "error": {
            "code": -32099,
            "message": (
                "Houdini host delivery is ambiguous."
                if ambiguous
                else "Houdini host is offline."
            ),
            "data": data,
        },
    }


def typed_error_payload(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        return False
    error = value.get("error")
    return (
        isinstance(error, dict)
        and type(error.get("code")) is int
        and isinstance(error.get("message"), str)
        and isinstance(error.get("data", {}), dict)
    )


def host_generation_changed(status: int, payload: Any) -> bool:
    if status != 409 or not isinstance(payload, dict):
        return False
    error = payload.get("error")
    data = error.get("data") if isinstance(error, dict) else None
    return (
        isinstance(data, dict)
        and data.get("hocusCode") == "HOCUS999"
        and data.get("kind") == "host_generation_changed"
    )


__all__ = [
    "delivery_error_response",
    "host_generation_changed",
    "operation_fields",
    "prepare_operation_request",
    "typed_error_payload",
]
