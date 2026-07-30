"""Pure authenticated expansion provenance for network-document lowering."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import (
    CarrierContractError,
    _validate_control_stack,
    _validate_module_stack,
)

DOCUMENT_EXPANSION_FORMAT = "document-expansion-provenance-v0.1"
MAX_DOCUMENT_EXPANSION_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_EXPANSION_STACKS = 4096
MAX_DOCUMENT_EXPANSION_FRAMES = 64
_MAX_DOCUMENT_FOLD_ITERATIONS = 4096
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENTITY_COLLECTIONS = ("nodes", "ports", "edges", "parameterBindings", "codeBlobs")


class DocumentProvenanceError(ValueError):
    """Malformed or unrepresentable durable document provenance."""


def normalize_expansion_tables(value: Any) -> dict[str, Any]:
    """Return one bounded canonical copy of a durable expansion table."""

    if (
        not isinstance(value, dict)
        or set(value) != {"format", "moduleStacks", "controlStacks"}
        or value.get("format") != DOCUMENT_EXPANSION_FORMAT
    ):
        raise DocumentProvenanceError("Document expansion provenance has an invalid envelope.")
    module = _normalize_stacks(
        value.get("moduleStacks"), "stackId", _validate_module_stack_record,
    )
    control = _normalize_stacks(
        value.get("controlStacks"),
        "controlStackId",
        _validate_control_stack_record,
    )
    normalized = {
        "format": DOCUMENT_EXPANSION_FORMAT,
        "moduleStacks": module,
        "controlStacks": control,
    }
    if _encoded_size({"version": 1, "hocusExpansion": normalized}) > MAX_DOCUMENT_EXPANSION_BYTES:
        raise DocumentProvenanceError("Document expansion provenance exceeds its durable byte limit.")
    return normalized


def compose_expansion_tables(
    document: dict[str, Any],
    baseline_tables: Any,
    incoming_tables: Any,
) -> dict[str, Any] | None:
    """Compose exactly the interned stacks referenced by the final document."""

    baseline = (
        normalize_expansion_tables(baseline_tables)
        if baseline_tables is not None else None
    )
    incoming = (
        normalize_expansion_tables(incoming_tables)
        if incoming_tables is not None else None
    )
    module_refs, control_refs = expansion_references(document)
    if not module_refs and not control_refs:
        return None
    result = {
        "format": DOCUMENT_EXPANSION_FORMAT,
        "moduleStacks": _select_referenced_stacks(
            module_refs, baseline, incoming, "moduleStacks", "stackId",
        ),
        "controlStacks": _select_referenced_stacks(
            control_refs, baseline, incoming, "controlStacks", "controlStackId",
        ),
    }
    return normalize_expansion_tables(result)


def expansion_references(
    document: dict[str, Any],
) -> tuple[set[str], set[str]]:
    """Collect typed stack references from every persistent document entity."""

    module: set[str] = set()
    control: set[str] = set()
    for field in _ENTITY_COLLECTIONS:
        for entity in document.get(field, []):
            metadata = entity.get("metadata") if isinstance(entity, dict) else None
            hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
            if not isinstance(hocus, dict):
                continue
            _take_reference(hocus, "stackId", module)
            _take_reference(hocus, "controlStackId", control)
    return module, control


def validate_expansion_references(document: dict[str, Any]) -> None:
    """Require every entity reference to resolve through the document root."""

    metadata = document.get("metadata")
    tables = metadata.get("hocusExpansion") if isinstance(metadata, dict) else None
    module_refs, control_refs = expansion_references(document)
    if tables is None:
        if module_refs or control_refs:
            raise DocumentProvenanceError(
                "Document entities reference expansion stacks without a root table."
            )
        return
    normalized = normalize_expansion_tables(tables)
    module_ids = {item["stackId"] for item in normalized["moduleStacks"]}
    control_ids = {
        item["controlStackId"] for item in normalized["controlStacks"]
    }
    missing_module = sorted(module_refs - module_ids)
    missing_control = sorted(control_refs - control_ids)
    if missing_module or missing_control:
        raise DocumentProvenanceError(
            "Document expansion provenance has dangling entity references."
        )


def _normalize_stacks(
    value: Any,
    identity_key: str,
    validator: Callable[[dict[str, Any], int], None],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_DOCUMENT_EXPANSION_STACKS:
        raise DocumentProvenanceError("Document expansion stack count is invalid.")
    normalized: list[dict[str, Any]] = []
    identities: list[str] = []
    for index, stack in enumerate(value):
        if not isinstance(stack, dict) or set(stack) != {identity_key, "frames"}:
            raise DocumentProvenanceError("Document expansion stack shape is invalid.")
        identity, frames = stack[identity_key], stack["frames"]
        if (
            not isinstance(identity, str)
            or _DIGEST.fullmatch(identity) is None
            or not isinstance(frames, list)
            or not 1 <= len(frames) <= MAX_DOCUMENT_EXPANSION_FRAMES
            or any(
                not isinstance(frame, dict) or not frame or len(frame) > 24
                for frame in frames
            )
        ):
            raise DocumentProvenanceError("Document expansion stack content is invalid.")
        candidate = copy.deepcopy(stack)
        _canonical_json(candidate)
        try:
            validator(candidate, index)
        except CarrierContractError as exc:
            raise DocumentProvenanceError(
                f"Document expansion stack authentication failed: {exc}"
            ) from exc
        identities.append(identity)
        normalized.append(candidate)
    if identities != sorted(set(identities)):
        raise DocumentProvenanceError(
            "Document expansion stack identities must be uniquely sorted."
        )
    return normalized


def _validate_module_stack_record(stack: dict[str, Any], index: int) -> None:
    _validate_module_stack(
        stack, index, MAX_DOCUMENT_EXPANSION_FRAMES, set(),
    )


def _validate_control_stack_record(stack: dict[str, Any], index: int) -> None:
    _validate_control_stack(
        stack,
        index,
        MAX_DOCUMENT_EXPANSION_FRAMES,
        _MAX_DOCUMENT_FOLD_ITERATIONS,
        set(),
    )


def _take_reference(
    hocus: dict[str, Any], field: str, result: set[str],
) -> None:
    value = hocus.get(field)
    if value is None:
        return
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DocumentProvenanceError(f"Document entity {field} is invalid.")
    result.add(value)


def _select_referenced_stacks(
    references: set[str],
    baseline: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    collection: str,
    identity_key: str,
) -> list[dict[str, Any]]:
    sources: list[dict[str, dict[str, Any]]] = []
    for tables in (baseline, incoming):
        if tables is not None:
            sources.append({item[identity_key]: item for item in tables[collection]})
    selected: list[dict[str, Any]] = []
    for identity in sorted(references):
        candidates = [source[identity] for source in sources if identity in source]
        if not candidates:
            raise DocumentProvenanceError(
                f"Document entity references unknown {identity_key} {identity}."
            )
        canonical = _canonical_json(candidates[0])
        if any(_canonical_json(item) != canonical for item in candidates[1:]):
            raise DocumentProvenanceError(
                f"Document expansion {identity_key} content conflicts for {identity}."
            )
        selected.append(copy.deepcopy(candidates[-1]))
    return selected


def _encoded_size(value: Any) -> int:
    return len(_canonical_json(value).encode("utf-8"))


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise DocumentProvenanceError(
            "Document expansion provenance is not canonical JSON."
        ) from exc


@dataclass(frozen=True, slots=True)
class DocumentProvenanceIndex:
    """Index one authenticated expansion map without duplicating stack tables."""

    _mappings: dict[str, dict[str, Any]]
    _module_stacks: dict[str, dict[str, Any]]
    _control_stacks: dict[str, dict[str, Any]]

    @classmethod
    def from_graph(cls, graph: dict[str, Any]) -> DocumentProvenanceIndex | None:
        expansion = graph.get("expansionMap")
        if not isinstance(expansion, dict):
            return None
        return cls(
            {item["generatedPointer"]: item for item in expansion["mappings"]},
            {item["stackId"]: item for item in expansion["stacks"]},
            {
                item["controlStackId"]: item
                for item in expansion.get("controlStacks", [])
            },
        )

    def tables(self) -> dict[str, Any]:
        """Return each interned authenticated stack exactly once."""

        return {
            "format": DOCUMENT_EXPANSION_FORMAT,
            "moduleStacks": [
                copy.deepcopy(self._module_stacks[key])
                for key in sorted(self._module_stacks)
            ],
            "controlStacks": [
                copy.deepcopy(self._control_stacks[key])
                for key in sorted(self._control_stacks)
            ],
        }

    def entity(
        self,
        pointer: str,
        fallback_span: Any,
        fallback_source_uri: str,
    ) -> dict[str, Any]:
        """Resolve the exact or longest enclosing generated-pointer mapping."""

        mapping = self._enclosing_mapping(pointer)
        if mapping is None:
            return {
                "sourceUri": fallback_source_uri,
                "jsonPointer": pointer,
                "span": copy.deepcopy(fallback_span),
            }
        primary = copy.deepcopy(mapping["primarySpan"])
        return {
            "sourceUri": primary["sourceUri"],
            "jsonPointer": pointer,
            "span": primary,
            "originId": mapping["originId"],
            "originKind": mapping["originKind"],
            "relatedOrigins": copy.deepcopy(mapping["relatedOrigins"]),
            "stackId": mapping["stackId"],
            "controlStackId": mapping.get("controlStackId"),
        }

    def _enclosing_mapping(self, pointer: str) -> dict[str, Any] | None:
        candidate = self._mappings.get(pointer)
        if candidate is not None:
            return candidate
        cursor = pointer
        while cursor:
            cursor = cursor.rpartition("/")[0]
            candidate = self._mappings.get(cursor)
            if candidate is not None:
                return candidate
        return self._mappings.get("")


def entity_metadata(
    payload: dict[str, Any],
    bundle_digest: str,
    graph: dict[str, Any],
    symbol: str,
    pointer: str,
    span: Any,
    ownership: str | None,
    provenance: DocumentProvenanceIndex | None,
    *,
    entity_kind: str,
) -> dict[str, Any]:
    source = entity_source_map(payload, pointer, span, provenance)
    hocus = {
        "version": 1,
        "entityKind": entity_kind,
        "projectUid": payload["projectUid"],
        "sourceUri": source["sourceUri"],
        "sourceDigest": _source_digest(payload, source["sourceUri"]),
        "bundleDigest": bundle_digest,
        "compilerVersion": payload["compilerVersion"],
        "languageVersion": payload["languageVersion"],
        "graphName": graph["name"],
        "symbol": symbol,
        "ownership": ownership,
        "jsonPointer": pointer,
        "span": copy.deepcopy(source["span"]),
    }
    for key in (
        "originId",
        "originKind",
        "relatedOrigins",
        "stackId",
        "controlStackId",
    ):
        if key in source:
            hocus[key] = copy.deepcopy(source[key])
    return {"hocus": hocus}


def entity_source_map(
    payload: dict[str, Any],
    pointer: str,
    span: Any,
    provenance: DocumentProvenanceIndex | None,
) -> dict[str, Any]:
    entry_uri = payload["entrySource"]["uri"]
    if provenance is None:
        return {
            "sourceUri": entry_uri,
            "jsonPointer": pointer,
            "span": copy.deepcopy(span),
        }
    return provenance.entity(pointer, span, entry_uri)


def _source_digest(payload: dict[str, Any], source_uri: str) -> str:
    sources = (payload["entrySource"], *payload["dependencies"])
    return next(item["digest"] for item in sources if item["uri"] == source_uri)


def managed_explicit_rename_candidate(
    previous: dict[str, Any],
    payload: dict[str, Any],
    graph: dict[str, Any],
    ownership: str | None,
    authored_symbol: str,
    *,
    allow_symbol_change: bool,
) -> bool:
    """Prove an explicit-ID node is prior managed state, never adoption."""

    metadata = previous.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    if not isinstance(hocus, dict):
        return False
    required_strings = (
        "sourceUri",
        "sourceDigest",
        "bundleDigest",
        "compilerVersion",
        "languageVersion",
        "graphName",
        "symbol",
        "jsonPointer",
    )
    if any(
        not isinstance(hocus.get(key), str) or not hocus.get(key)
        for key in required_strings
    ):
        return False
    if not isinstance(hocus.get("span"), dict):
        return False
    if not str(hocus["sourceDigest"]).startswith("sha256:"):
        return False
    if not str(hocus["bundleDigest"]).startswith("sha256:"):
        return False
    managed_fields = hocus.get("managedFields")
    if (
        not isinstance(managed_fields, dict)
        or managed_fields.get("nodeUid") != previous.get("uid")
    ):
        return False
    return (
        hocus.get("entityKind") == "node"
        and hocus.get("projectUid") == payload.get("projectUid")
        and hocus.get("graphName") == graph.get("name")
        and hocus.get("ownership") == ownership
        and (allow_symbol_change or hocus.get("symbol") == authored_symbol)
        and str(hocus.get("jsonPointer", "")).startswith("/nodes/")
    )
