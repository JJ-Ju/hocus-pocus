"""Canonical network-document-v2 source export for managed runtime entities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .document_runtime_contract import (
    DocumentRuntimeContractError,
    validate_runtime_contract,
)


def render_runtime_entities(
    document: Mapping[str, Any],
    symbols_by_uid: Mapping[str, str],
    ownership: str | None,
) -> tuple[dict[str, list[str]], set[tuple[str, str]], list[str]]:
    if document.get("$schema") != "hocuspocus://schemas/network-document/v2":
        return {}, set(), []
    try:
        validate_runtime_contract(dict(document), set(symbols_by_uid))
    except DocumentRuntimeContractError as exc:
        return {}, set(), [str(exc)]
    selected_spares = [
        item for item in document.get("spareParameters", [])
        if _ownership(item) == ownership and ownership is not None
    ]
    selected_animations = [
        item for item in document.get("animations", [])
        if _ownership(item) == ownership and ownership is not None
    ]
    lines: dict[str, list[str]] = {}
    for spare in sorted(selected_spares, key=lambda item: item["uid"]):
        node_uid = str(spare["nodeUid"])
        if node_uid not in symbols_by_uid:
            return {}, set(), ["managed spare targets an unexported node"]
        lines.setdefault(node_uid, []).extend(_render_spare(spare))
    targets: set[tuple[str, str]] = set()
    try:
        for animation in sorted(selected_animations, key=lambda item: item["uid"]):
            node_uid = str(animation["nodeUid"])
            if node_uid not in symbols_by_uid:
                return {}, set(), ["managed animation targets an unexported node"]
            lines.setdefault(node_uid, []).extend(_render_animation(animation))
            targets.add((node_uid, str(animation["parmName"])))
    except DocumentRuntimeContractError as exc:
        return {}, set(), [str(exc)]
    return lines, targets, []


def _render_spare(item: Mapping[str, Any]) -> list[str]:
    properties = (
        ("label", item["label"]),
        ("type", item["type"]),
        ("tuple_size", item["tupleSize"]),
        ("default", item["default"]),
        (
            "menu_items",
            [
                [entry["token"], entry["label"]]
                for entry in item["menuItems"]
            ],
        ),
    )
    return _block("spare", item["name"], item["uid"], properties)


def _render_animation(item: Mapping[str, Any]) -> list[str]:
    keys = [_render_key(key) for key in item["keys"]]
    properties = (
        ("value_type", item["valueType"]),
        ("value", item["value"]),
        ("authored_fps", item["authoredFps"]),
        ("display_fps", item["displayFps"]),
        (
            "extrapolation",
            [item["extrapolation"]["before"], item["extrapolation"]["after"]],
        ),
        ("keys", keys),
    )
    return _block("animate", item["parmName"], item["uid"], properties)


def _render_key(key: Mapping[str, Any]) -> list[Any]:
    result = [key["timeSeconds"], key["value"], key["interpolation"]]
    tangent_fields = (
        "slope", "accel", "slopeAuto", "accelAuto",
        "slopeTied", "accelTied", "slopeUsed", "accelUsed",
    )
    present = [field in key for field in tangent_fields]
    if any(present):
        if present == [True, True, *([False] * 6)]:
            result.extend(key[field] for field in tangent_fields[:2])
        elif all(present):
            result.extend(key[field] for field in tangent_fields)
        else:
            raise DocumentRuntimeContractError(
                "Export requires a complete authored tangent tuple."
            )
    return result


def _block(
    kind: str, name: Any, uid: Any, properties: Any,
) -> list[str]:
    lines = [
        f"    {kind} {name} @id({_scalar(uid)}) {{",
    ]
    lines.extend(
        f"      {field} = {_scalar(value)};" for field, value in properties
    )
    lines.append("    }")
    return lines


def _ownership(item: Mapping[str, Any]) -> Any:
    metadata = item.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    return hocus.get("ownership") if isinstance(hocus, dict) else None


def _scalar(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(", ", ": "),
        allow_nan=False,
    )
