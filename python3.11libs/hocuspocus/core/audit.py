"""Audit logging for tool calls."""

from __future__ import annotations

import json
import logging
import threading
import time
from hashlib import sha256
from typing import Any

from .paths import audit_log_path


class AuditLogger:
    def __init__(self, logger: logging.Logger):
        self._logger = logger.getChild("audit")
        self._lock = threading.Lock()
        self._path = audit_log_path()

    def log_tool_call(
        self,
        *,
        operation_id: str,
        caller_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "timestamp": time.time(),
            "operationId": operation_id,
            "callerId": caller_id,
            "toolName": tool_name,
            "success": success,
            "argumentsHash": sha256(
                json.dumps(arguments, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
            "resultSummary": _result_summary(result),
            "error": error,
        }
        line = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        self._logger.debug("audit logged for %s", tool_name)


def _result_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return None
    summary: dict[str, Any] = {}
    for key in ("path", "paths", "deletedPaths", "selectedNodes", "parmPath", "hipFile"):
        if key in structured:
            summary[key] = structured[key]
    return summary or {"keys": sorted(structured.keys())[:10]}
