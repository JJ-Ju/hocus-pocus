"""Pure GraphSpec-0.5 tagged-value to network-document-v2 lowering."""

from __future__ import annotations

import copy
from typing import Any, Mapping


class DocumentValueLoweringError(ValueError):
    """Raised when authenticated typed-value evidence cannot be lowered."""


def lower_value_binding(
    value: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    generated_by_symbol: Mapping[str, Mapping[str, Any]],
    external_by_symbol: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the closed v2 value payload for one parameter binding."""

    kind = value.get("kind")
    if kind == "literal":
        if selection.get("valueType") == "menu":
            return {"valueMode": "menu_token", "menuToken": value.get("value")}
        return {"valueMode": "literal", "value": copy.deepcopy(value.get("value"))}
    if kind == "code":
        raise DocumentValueLoweringError("Code values use the code-blob lane.")
    adapter = selection.get("valueAdapter")
    if not isinstance(adapter, Mapping) or adapter.get("kind") != kind:
        raise DocumentValueLoweringError(
            "Tagged value lacks matching authenticated catalog adapter evidence."
        )
    return _lower_tagged_binding(
        value,
        adapter,
        generated_by_symbol=generated_by_symbol,
        external_by_symbol=external_by_symbol,
    )


def _lower_tagged_binding(
    value: Mapping[str, Any],
    adapter: Mapping[str, Any],
    *,
    generated_by_symbol: Mapping[str, Mapping[str, Any]],
    external_by_symbol: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    kind = value["kind"]
    if kind == "reset":
        return {"valueMode": "reset"}
    if kind == "expression":
        return {
            "valueMode": "expression",
            "expression": value["body"],
            "expressionLanguage": value["language"],
        }
    if kind == "channel_reference":
        target = (
            generated_by_symbol.get(str(value["nodeSymbol"]))
            or external_by_symbol.get(str(value["nodeSymbol"]))
        )
        node_uid = target.get("uid") if isinstance(target, Mapping) else None
        if not isinstance(node_uid, str) or not node_uid:
            raise DocumentValueLoweringError(
                "Structural channel reference target is unavailable during lowering."
            )
        return {
            "valueMode": "channel_reference",
            "channelReference": {
                "nodeUid": node_uid,
                "parmName": value["parmName"],
            },
        }
    if kind == "raw_path":
        return {
            "valueMode": "raw_path",
            "pathKind": value["pathKind"],
            "raw": value["raw"],
        }
    if kind == "quantity":
        return {
            "valueMode": "quantity",
            "magnitude": value["magnitude"],
            "unit": value["unit"],
            "dimension": adapter["dimension"],
            "canonicalMagnitude": adapter["canonicalMagnitude"],
            "canonicalUnit": adapter["canonicalUnit"],
        }
    if kind == "ramp":
        return {
            "valueMode": "ramp",
            "rampKind": adapter["rampKind"],
            "points": [
                {
                    "position": point["position"],
                    "value": _literal_value(point["value"]),
                }
                for point in value["points"]
            ],
            "basis": list(value["basis"]),
        }
    if kind == "multiparm":
        return {
            "valueMode": "multiparm",
            "instanceStart": adapter["instanceStart"],
            "instances": [
                {
                    "instanceId": instance["instanceId"],
                    "fields": [
                        {
                            "name": field["name"],
                            "value": _nested_value(
                                field["value"],
                                generated_by_symbol,
                                external_by_symbol,
                            ),
                        }
                        for field in instance["fields"]
                    ],
                }
                for instance in value["instances"]
            ],
            "fieldContract": copy.deepcopy(adapter["fields"]),
        }
    raise DocumentValueLoweringError(f"Unsupported GraphSpec value kind: {kind!r}.")


def _nested_value(
    value: Mapping[str, Any],
    generated_by_symbol: Mapping[str, Mapping[str, Any]],
    external_by_symbol: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    kind = value.get("kind")
    if kind == "literal":
        return {"kind": kind, "value": _literal_value(value)}
    if kind == "expression":
        return {
            "kind": "expression",
            "language": value["language"],
            "body": value["body"],
        }
    if kind == "channel_reference":
        target = (
            generated_by_symbol.get(str(value["nodeSymbol"]))
            or external_by_symbol.get(str(value["nodeSymbol"]))
        )
        node_uid = target.get("uid") if isinstance(target, Mapping) else None
        if not isinstance(node_uid, str) or not node_uid:
            raise DocumentValueLoweringError(
                "Nested channel reference target is unavailable during lowering."
            )
        return {
            "kind": "channel_reference",
            "nodeUid": node_uid,
            "parmName": value["parmName"],
        }
    if kind == "raw_path":
        return {
            "kind": "raw_path",
            "pathKind": value["pathKind"],
            "raw": value["raw"],
        }
    raise DocumentValueLoweringError(
        "Unsupported nested multiparm value reached document lowering."
    )


def _literal_value(value: Mapping[str, Any]) -> Any:
    if value.get("kind") == "literal":
        return copy.deepcopy(value.get("value"))
    if value.get("kind") == "array":
        return [_literal_value(item) for item in value.get("items", [])]
    raise DocumentValueLoweringError("Expected a literal graph value.")
