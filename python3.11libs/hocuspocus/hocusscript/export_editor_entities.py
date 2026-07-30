"""Canonical network-document-v2 editor-entity source export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .document_editor_entities import (
    DocumentEditorEntityError,
    editor_entities_from_document,
)


def render_editor_entities(
    document: Mapping[str, Any],
    symbols_by_uid: Mapping[str, str],
    ownership: str | None,
) -> tuple[list[str], list[str]]:
    if document.get("$schema") != "hocuspocus://schemas/network-document/v2":
        return [], []
    try:
        all_entities = editor_entities_from_document(
            document, node_uids=symbols_by_uid,
        )
    except DocumentEditorEntityError as exc:
        return [], [str(exc)]
    managed = [
        item for item in all_entities
        if _ownership(item) == ownership and ownership is not None
    ]
    managed_uids = {str(item["uid"]) for item in managed}
    if managed_uids & set(symbols_by_uid):
        return [], ["editor entity UID collides with an exported node UID"]
    errors = _validate_export_refs(managed, managed_uids, symbols_by_uid)
    if errors:
        return [], errors
    lines: list[str] = []
    kinds = {str(item["uid"]): str(item["kind"]) for item in managed}
    for entity in sorted(managed, key=lambda item: (item["kind"], item["uid"])):
        lines.extend(("", *_render_entity(entity, symbols_by_uid, kinds)))
    return lines, []


def _render_entity(
    entity: Mapping[str, Any],
    symbols_by_uid: Mapping[str, str],
    kinds: Mapping[str, str],
) -> list[str]:
    kind = str(entity["kind"])
    lines = [f"  {kind} @id({_scalar(entity['uid'])}) {{"]
    fields = _entity_fields(entity, symbols_by_uid, kinds)
    lines.extend(f"    {name} = {value};" for name, value in fields)
    lines.append("  }")
    return lines


def _entity_fields(
    entity: Mapping[str, Any],
    symbols: Mapping[str, str],
    kinds: Mapping[str, str],
) -> list[tuple[str, str]]:
    kind = entity["kind"]
    if kind == "network_box":
        fields = [
            ("label", _scalar(entity["label"])),
            ("position", _array(entity["position"])),
            ("size", _array(entity["size"])),
            ("items", _refs(entity["itemUids"], symbols, kinds)),
        ]
        if entity["color"] is not None:
            fields.insert(3, ("color", _array(entity["color"])))
        return fields
    if kind == "sticky_note":
        fields = [
            ("text", _scalar(entity["text"])),
            ("position", _array(entity["position"])),
            ("size", _array(entity["size"])),
            ("text_size", _scalar(entity["textSize"])),
            ("background", _scalar(entity["drawBackground"])),
            ("minimized", _scalar(entity["minimized"])),
        ]
        if entity["color"] is not None:
            fields.insert(3, ("color", _array(entity["color"])))
        return fields
    if kind == "node_comment":
        return [
            ("node", _ref(entity["nodeUid"], symbols, kinds)),
            ("text", _scalar(entity["text"])),
            ("visible", _scalar(entity["visible"])),
        ]
    if kind == "network_dot":
        fields = [
            ("position", _array(entity["position"])),
            ("pinned", _scalar(entity["pinned"])),
        ]
        if entity["input"] is not None:
            source = _ref(entity["input"]["itemUid"], symbols, kinds)
            fields.append(
                ("input", f"{source}.output[{entity['input']['outputIndex']}]")
            )
        destinations = ", ".join(
            f"{_ref(item['nodeUid'], symbols, kinds)}"
            f".input[{item['inputIndex']}]"
            for item in entity["outputs"]
        )
        fields.append(("outputs", f"[{destinations}]"))
        return fields
    fields = [
        ("kind", _scalar(entity["constraintKind"])),
        ("items", _refs(entity["itemUids"], symbols, kinds)),
    ]
    for name, key in (
        ("anchor", "anchorUid"), ("offset", "offset"),
        ("spacing", "spacing"),
    ):
        value = entity[key]
        if value is not None:
            fields.append((
                name,
                _ref(value, symbols, kinds)
                if name == "anchor" else (
                    _array(value) if name == "offset" else _scalar(value)
                ),
            ))
    fields.extend([
        ("padding", _array(entity["padding"])),
        ("priority", _scalar(entity["priority"])),
    ])
    return fields


def _validate_export_refs(
    entities: list[dict[str, Any]],
    managed_uids: set[str],
    symbols: Mapping[str, str],
) -> list[str]:
    errors = []
    for entity in entities:
        refs = list(entity.get("itemUids", []))
        for key in ("nodeUid", "anchorUid"):
            if entity.get(key) is not None:
                refs.append(entity[key])
        if entity.get("input") is not None:
            refs.append(entity["input"]["itemUid"])
        refs.extend(item["nodeUid"] for item in entity.get("outputs", []))
        for uid in refs:
            if uid not in symbols and uid not in managed_uids:
                errors.append(
                    f"managed editor entity {entity['uid']} references "
                    f"an unexportable artist item"
                )
    return errors


def _ref(
    uid: str, symbols: Mapping[str, str], kinds: Mapping[str, str],
) -> str:
    if uid in symbols:
        return f"node {symbols[uid]}"
    keyword = {
        "network_box": "box", "sticky_note": "sticky",
        "network_dot": "dot",
    }[kinds[uid]]
    return f"{keyword} {_scalar(uid)}"


def _refs(
    values: list[str],
    symbols: Mapping[str, str],
    kinds: Mapping[str, str],
) -> str:
    return "[" + ", ".join(_ref(uid, symbols, kinds) for uid in values) + "]"


def _ownership(entity: Mapping[str, Any]) -> str | None:
    metadata = entity.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    value = hocus.get("ownership") if isinstance(hocus, dict) else None
    return value if isinstance(value, str) and value else None


def _array(value: Any) -> str:
    if value is None:
        return "null"
    return "[" + ", ".join(_scalar(item) for item in value) + "]"


def _scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
