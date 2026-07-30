"""Connection- and authority-bound cursors for H6 source services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from .project_service_support import SourceServiceError


class SourceCursorMixin:
    _cursor_key: bytes

    def _resource_cursor(
        self,
        context: Any,
        cursor: str | None,
        digest: str,
    ) -> int:
        if cursor is None:
            return 0
        try:
            encoded, signature = cursor.split(".", 1)
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(self._cursor_key, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SourceServiceError("HOCUS821", "Resource cursor is invalid.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("principal") != getattr(context, "principal_id", None)
            or payload.get("session") != getattr(context, "session_id", None)
            or payload.get("resourceDigest") != digest
            or type(payload.get("expiresAt")) not in {int, float}
            or payload["expiresAt"] < time.time()
            or type(payload.get("offset")) is not int
            or not 0 <= payload["offset"] <= 64 * 1001
        ):
            raise SourceServiceError(
                "HOCUS824", "Resource cursor authority is stale."
            )
        return payload["offset"]

    def _encode_resource_cursor(
        self,
        context: Any,
        offset: int,
        digest: str,
    ) -> str:
        payload = {
            "version": 1,
            "principal": getattr(context, "principal_id", None),
            "session": getattr(context, "session_id", None),
            "offset": offset,
            "resourceDigest": digest,
            "expiresAt": time.time() + 300.0,
        }
        return self._encode_cursor(payload)

    def _decode_search_cursor(
        self,
        context: Any,
        session: Any,
        cursor: str | None,
        **selection: Any,
    ) -> int:
        if cursor is None:
            return 0
        payload = self._decode_cursor(cursor, "Search")
        expected = self._search_cursor_payload(
            context, session, payload.get("offset"), **selection,
        )
        if (
            type(payload.get("expiresAt")) not in {int, float}
            or payload["expiresAt"] < time.time()
            or any(payload.get(key) != value for key, value in expected.items())
        ):
            raise SourceServiceError("HOCUS824", "Search cursor authority is stale.")
        return payload["offset"]

    def _encode_search_cursor(
        self,
        context: Any,
        session: Any,
        offset: int,
        **selection: Any,
    ) -> str:
        payload = {
            **self._search_cursor_payload(
                context, session, offset, **selection,
            ),
            "expiresAt": time.time() + 300.0,
        }
        return self._encode_cursor(payload)

    @staticmethod
    def _search_cursor_payload(
        context: Any,
        session: Any,
        offset: Any,
        **selection: Any,
    ) -> dict[str, Any]:
        if type(offset) is not int or not 0 <= offset <= 1000:
            raise SourceServiceError("HOCUS821", "Search cursor offset is invalid.")
        return {
            "version": 1,
            "kind": "search",
            "principal": getattr(context, "principal_id", None),
            "session": getattr(context, "session_id", None),
            "projectId": session.record.project_id,
            "authorityProjectionDigest": session.record.projection_digest,
            "grantGeneration": session.record.generation,
            "offset": offset,
            "selectionDigest": _selection_digest(selection),
        }

    def _decode_cursor(self, cursor: str, label: str) -> dict[str, Any]:
        try:
            encoded, signature = cursor.split(".", 1)
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(self._cursor_key, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SourceServiceError(
                "HOCUS821", f"{label} cursor is invalid."
            ) from exc
        if not isinstance(payload, dict):
            raise SourceServiceError("HOCUS821", f"{label} cursor is invalid.")
        return payload

    def _encode_cursor(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        signature = hmac.new(self._cursor_key, raw, hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"


def _selection_digest(selection: dict[str, Any]) -> str:
    raw = json.dumps(
        selection,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


__all__ = ["SourceCursorMixin"]
