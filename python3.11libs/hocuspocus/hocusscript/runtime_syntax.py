"""Source-faithful language-0.4 managed spare and animation declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .diagnostics import SourceSpan


@dataclass(frozen=True, slots=True)
class RuntimeProperty:
    name: str
    value: Any
    span: SourceSpan
    name_span: SourceSpan


@dataclass(frozen=True, slots=True)
class SpareParameterDecl:
    name: str
    explicit_id: str
    properties: tuple[RuntimeProperty, ...]
    span: SourceSpan
    name_span: SourceSpan
    explicit_id_span: SourceSpan


@dataclass(frozen=True, slots=True)
class AnimationDecl:
    parm_name: str
    explicit_id: str
    properties: tuple[RuntimeProperty, ...]
    span: SourceSpan
    parm_name_span: SourceSpan
    explicit_id_span: SourceSpan

