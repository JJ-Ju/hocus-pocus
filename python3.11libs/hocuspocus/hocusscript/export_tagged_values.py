"""Canonical network-document-v2 tagged values for HocusScript 0.4."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .document_value_validation import (
    DocumentValueValidationError,
    validate_v2_binding,
)


class ParameterValueExportError(ValueError):
    """Raised when a managed v2 binding cannot be represented exactly."""


def render_parameter_value(
    binding: dict[str, Any],
    *,
    node_uids: set[str],
    symbols_by_uid: Mapping[str, str],
) -> str:
    """Render one authenticated v2 value using canonical 0.4 syntax."""

    try:
        validate_v2_binding(binding, node_uids)
    except DocumentValueValidationError as exc:
        raise ParameterValueExportError(str(exc)) from exc
    mode = binding["valueMode"]
    if mode == "literal":
        return _json(binding["value"])
    if mode == "menu_token":
        return _json(binding["menuToken"])
    if mode == "reset":
        return "reset()"
    if mode == "expression":
        return (
            "expression("
            + str(binding["expressionLanguage"])
            + "`"
            + _code_body(binding["expression"])
            + "`)"
        )
    if mode == "channel_reference":
        return _channel(binding["channelReference"], symbols_by_uid)
    if mode == "raw_path":
        return (
            f"raw_path({binding['pathKind']}, "
            f"{_json(binding['raw'])})"
        )
    if mode == "quantity":
        return (
            f"quantity({_json(binding['magnitude'])}, "
            f"{_json(binding['unit'])})"
        )
    if mode == "ramp":
        points = ", ".join(
            f"[{_json(item['position'])}, {_json(item['value'])}]"
            for item in binding["points"]
        )
        basis = ", ".join(_json(item) for item in binding["basis"])
        return f"ramp(points = [{points}], basis = [{basis}])"
    if mode == "multiparm":
        field_order = [
            item["name"] for item in binding["fieldContract"]
        ]
        instances = ", ".join(
            _multiparm_instance(item, field_order, symbols_by_uid)
            for item in binding["instances"]
        )
        return f"multiparm(instances = [{instances}])"
    raise ParameterValueExportError(
        f"Binding mode {mode!r} does not use the tagged-value renderer."
    )


def _multiparm_instance(
    value: dict[str, Any],
    field_order: list[str],
    symbols_by_uid: Mapping[str, str],
) -> str:
    values = {
        item["name"]: item["value"] for item in value["fields"]
    }
    fields = " ".join(
        f"{name} = {_nested_value(values[name], symbols_by_uid)};"
        for name in field_order
    )
    return f"instance({_json(value['instanceId'])}, {{ {fields} }})"


def _nested_value(
    value: dict[str, Any],
    symbols_by_uid: Mapping[str, str],
) -> str:
    kind = value["kind"]
    if kind == "literal":
        return _json(value["value"])
    if kind == "expression":
        return (
            f"expression({value['language']}`"
            f"{_code_body(value['body'])}`)"
        )
    if kind == "channel_reference":
        return _channel(value, symbols_by_uid)
    if kind == "raw_path":
        return f"raw_path({value['pathKind']}, {_json(value['raw'])})"
    raise ParameterValueExportError(
        f"Nested multiparm mode {kind!r} cannot be represented."
    )


def _channel(
    value: Mapping[str, Any],
    symbols_by_uid: Mapping[str, str],
) -> str:
    symbol = symbols_by_uid.get(str(value["nodeUid"]))
    if symbol is None:
        raise ParameterValueExportError(
            "Structural channel target is not an exported managed node."
        )
    return f"channel({symbol}, {value['parmName']})"


def _code_body(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("`", "\\`")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
