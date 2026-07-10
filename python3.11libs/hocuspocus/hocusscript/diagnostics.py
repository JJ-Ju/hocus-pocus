"""Source locations and diagnostics for HocusScript."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourcePosition:
    offset: int
    line: int
    column: int

    def to_dict(self) -> dict[str, int]:
        return {"offset": self.offset, "line": self.line, "column": self.column}


@dataclass(frozen=True, slots=True)
class SourceSpan:
    source_name: str
    start: SourcePosition
    end: SourcePosition

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceUri": self.source_name,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


@dataclass(slots=True)
class Diagnostic:
    severity: str
    code: str
    phase: str
    message: str
    span: SourceSpan | None = None
    related: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fixes: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "phase": self.phase,
            "message": self.message,
            "related": self.related,
            "notes": self.notes,
            "fixes": self.fixes,
            "details": self.details,
            "expansionStack": [],
            "jsonPointer": None,
            "entityUid": None,
            "houdiniPath": None,
        }
        if self.span is not None:
            payload["sourceUri"] = self.span.source_name
            payload["span"] = {
                "start": self.span.start.to_dict(),
                "end": self.span.end.to_dict(),
            }
        return payload


class HocusSourceError(Exception):
    """Internal short-circuit carrying a structured source diagnostic."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def sort_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        diagnostics,
        key=lambda item: (
            item.span.source_name if item.span is not None else "",
            item.span.start.offset if item.span is not None else -1,
            severity_order.get(item.severity, 99),
            item.code,
        ),
    )
