"""Static semantic checks for language-0.4 tagged parameter values."""

from __future__ import annotations

from typing import Any, Callable

from .diagnostics import SourceSpan
from .expander import ModuleExpansionError
from .syntax import (
    ChannelReferenceValue,
    ExpressionValue,
    MultiparmValue,
    QuantityValue,
    RampValue,
    RawPathValue,
    ResetValue,
    TaggedValueExpr,
)


def validate_tagged_value(
    value: TaggedValueExpr,
    scope: Any,
    state: Any,
    validate_value_shape: Callable[..., None],
) -> None:
    state.claim_value(value.span)
    payload = value.payload
    if isinstance(payload, ResetValue):
        return
    if isinstance(payload, ExpressionValue):
        _validate_expression_value(payload, value.span, state)
        return
    if isinstance(payload, ChannelReferenceValue):
        if payload.node_symbol not in scope.nodes:
            raise ModuleExpansionError(
                "HOCUS471",
                f"Unknown structural channel node: {payload.node_symbol}.",
                payload.node_span,
            )
        return
    if isinstance(payload, RawPathValue):
        if len(payload.raw.encode("utf-8")) > 8192:
            raise ModuleExpansionError(
                "HOCUS464", "Raw path exceeds the 8192-byte limit.", value.span
            )
        return
    if isinstance(payload, QuantityValue):
        return
    if isinstance(payload, RampValue):
        for point in payload.points:
            validate_value_shape(point.value, state, depth=1)
        return
    if isinstance(payload, MultiparmValue):
        _validate_multiparm_value(
            payload, scope, state, validate_value_shape
        )
        return
    raise ModuleExpansionError(
        "HOCUS474", "Unsupported tagged parameter value.", value.span
    )


def _validate_expression_value(
    payload: ExpressionValue, span: SourceSpan, state: Any,
) -> None:
    encoded = payload.body.encode("utf-8")
    if not encoded or len(encoded) > 1024 * 1024:
        raise ModuleExpansionError(
            "HOCUS474", "Expression text must be non-empty and at most 1 MiB.",
            span,
        )
    state.code_bytes += len(encoded)
    if state.code_bytes > state.limits.aggregate_code_bytes:
        raise ModuleExpansionError(
            "HOCUS464",
            "Expression and code text exceeds the 4 MiB aggregate limit.",
            span,
        )


def _validate_multiparm_value(
    payload: MultiparmValue,
    scope: Any,
    state: Any,
    validate_value_shape: Callable[..., None],
) -> None:
    for instance in payload.instances:
        for item_field in instance.fields:
            field_value = item_field.value
            if isinstance(field_value, TaggedValueExpr) and field_value.tag in {
                "multiparm", "ramp", "reset",
            }:
                raise ModuleExpansionError(
                    "HOCUS474",
                    "Nested ramp, multiparm, and reset values are unsupported.",
                    field_value.span,
                )
            if isinstance(field_value, TaggedValueExpr):
                validate_tagged_value(
                    field_value, scope, state, validate_value_shape
                )
            else:
                validate_value_shape(field_value, state, depth=1)
