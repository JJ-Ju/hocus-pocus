"""Shared invariants and catalog lookup for authored port selectors."""

from __future__ import annotations

from typing import Any, Iterable


def selector_is_valid(index: Any, name: Any, language_version: str) -> bool:
    """Return whether exactly one selector is valid for the language lane."""

    if index is not None:
        return type(index) is int and index >= 0 and name is None
    return (
        language_version == "0.4"
        and type(name) is str
        and 0 < len(name) <= 256
    )


def require_selector(
    index: Any, name: Any, language_version: str, error: Exception,
) -> None:
    if not selector_is_valid(index, name, language_version):
        raise error


def fixed_named_connector(connectors: Iterable[Any], name: str) -> Any | None:
    """Resolve an exact name only when the whole namespace is fixed and unique."""

    items = tuple(connectors)
    names = [item.name for item in items]
    indexes = [item.index for item in items]
    fixed = all(
        type(item.name) is str
        and item.name
        and type(item.index) is int
        and item.index >= 0
        and item.cardinality in {"one", "optional"}
        for item in items
    )
    if not fixed or len(names) != len(set(names)) or len(indexes) != len(set(indexes)):
        return None
    matches = [item for item in items if item.name == name]
    return matches[0] if len(matches) == 1 else None


def resolved_connector_index(authored_index: int | None, connector: Any) -> int:
    resolved = authored_index if authored_index is not None else connector.index
    if type(resolved) is not int or resolved < 0:
        raise AssertionError("resolved connector lacks an authoritative index")
    return resolved


def connector_for_index(connectors: Iterable[Any], index: int) -> Any | None:
    for connector in connectors:
        if connector.index == index:
            return connector
    variadic = [
        item for item in connectors
        if item.index is not None
        and item.index <= index
        and item.cardinality == "many"
    ]
    if variadic:
        return max(variadic, key=lambda item: item.index or 0)
    return next(
        (
            item for item in connectors
            if item.index is None and item.cardinality == "many"
        ),
        None,
    )


def connector_evidence_name(connector: Any, resolved_index: int) -> str | None:
    """Return only a fixed host-verifiable connector name."""

    return connector.name if connector.index == resolved_index else None


def connector_indexes(connectors: Iterable[Any]) -> list[int]:
    return sorted(item.index for item in connectors if item.index is not None)
