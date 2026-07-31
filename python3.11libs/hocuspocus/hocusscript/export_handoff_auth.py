"""Ephemeral runtime authentication for document-to-source handoffs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

from .project_service_support import SourceServiceError

_TOKEN_VERSION = 1
_TOKEN_TTL_SECONDS = 300
_MAX_TOKEN_BYTES = 2048
_TOKEN_FIELD = "handoffToken"


def issue_export_token(
    handoff: Mapping[str, Any],
    *,
    key: bytes,
    principal_id: str,
    session_id: str | None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return an additive signed export result for this exact MCP connection."""

    if not session_id:
        return dict(handoff)
    payload = _payload(handoff)
    issued = int(time.time() if now is None else now)
    claims = {
        "v": _TOKEN_VERSION,
        "d": _payload_digest(payload),
        "p": principal_id,
        "s": session_id,
        "e": issued + _TOKEN_TTL_SECONDS,
    }
    encoded = _encode_json(claims)
    signature = hmac.new(key, b"hocus-export-handoff-v1\0" + encoded, hashlib.sha256)
    result = dict(handoff)
    result[_TOKEN_FIELD] = (
        base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature.digest()).decode("ascii").rstrip("=")
    )
    return result


def verify_export_token(
    handoff: Any,
    *,
    key: bytes,
    principal_id: str,
    session_id: str | None,
    now: float | None = None,
) -> None:
    """Reject unsigned, altered, expired, or cross-connection handoffs."""

    payload = _payload(handoff)
    token = payload.get(_TOKEN_FIELD)
    if not isinstance(token, str) or not 1 <= len(token) <= _MAX_TOKEN_BYTES:
        _reject()
    try:
        encoded_text, signature_text = token.split(".", 1)
        encoded = _decode(encoded_text)
        signature = _decode(signature_text)
        claims = json.loads(encoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        _reject()
    expected = hmac.new(
        key, b"hocus-export-handoff-v1\0" + encoded, hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        _reject()
    current = int(time.time() if now is None else now)
    unsigned = dict(payload)
    unsigned.pop(_TOKEN_FIELD, None)
    if (
        not isinstance(claims, Mapping)
        or claims.get("v") != _TOKEN_VERSION
        or claims.get("p") != principal_id
        or claims.get("s") != session_id
        or type(claims.get("e")) is not int
        or not current <= claims["e"] <= current + _TOKEN_TTL_SECONDS
        or claims.get("d") != _payload_digest(unsigned)
    ):
        _reject()


def _payload(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _reject()
    structured = value.get("structuredContent")
    return structured if isinstance(structured, Mapping) else value


def _payload_digest(payload: Mapping[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop(_TOKEN_FIELD, None)
    return "sha256:" + hashlib.sha256(_encode_json(unsigned)).hexdigest()


def _encode_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SourceServiceError(
            "HOCUS829", "Export handoff is not bounded canonical JSON data."
        ) from exc


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _reject() -> None:
    raise SourceServiceError(
        "HOCUS829", "Export handoff authentication is invalid or expired."
    )


__all__ = ["issue_export_token", "verify_export_token"]
