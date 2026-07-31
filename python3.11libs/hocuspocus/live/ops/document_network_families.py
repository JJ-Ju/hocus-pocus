"""Fail-closed policy and live classification for network documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NetworkFamilyPolicy:
    family: str
    structural_indexed_apply: bool
    output_strategy: str


_POLICIES = {
    family: NetworkFamilyPolicy(
        family,
        family in {"sop", "mat", "lop", "top"},
        "sop_display" if family == "sop" else "none",
    )
    for family in (
        "sop", "mat", "lop", "top", "object", "rop", "dop", "cop", "chop",
        "generic",
    )
}

_CATEGORY_FAMILIES = {
    "sop": "sop",
    "vop": "mat",
    "shop": "mat",
    "mat": "mat",
    "lop": "lop",
    "top": "top",
    "object": "object",
    "obj": "object",
    "driver": "rop",
    "rop": "rop",
    "dop": "dop",
    "cop": "cop",
    "cop2": "cop",
    "chop": "chop",
}


def network_family_policy(family: Any) -> NetworkFamilyPolicy:
    return _POLICIES.get(str(family or "").strip().lower(), _POLICIES["generic"])


def _category_name(value: Any) -> str:
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if callable(name):
        try:
            value = name()
        except Exception:
            return ""
    return str(value or "").strip()


def _family_from_category(category: Any) -> str | None:
    return _CATEGORY_FAMILIES.get(_category_name(category).lower())


def _safe_category(node: Any, method_name: str) -> Any:
    method = getattr(node, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _node_type_category(node: Any) -> Any:
    node_type = _safe_category(node, "type")
    return _safe_category(node_type, "category") if node_type is not None else None


def _path_family(root_path: str) -> str | None:
    root = str(root_path or "").strip()
    if root == "/obj":
        return "object"
    if root.startswith("/obj/"):
        return "sop"
    for prefix, family in (
        ("/mat", "mat"),
        ("/stage", "lop"),
        ("/tasks", "top"),
        ("/out", "rop"),
        ("/img", "cop"),
        ("/ch", "chop"),
    ):
        if root == prefix or root.startswith(prefix + "/"):
            return family
    return None


def resolve_network_family(
    hou_module: Any,
    root_path: str,
    category: Any = None,
) -> str:
    """Resolve a container by its live child category before portable fallbacks."""
    node = None
    resolver = getattr(hou_module, "node", None) if hou_module is not None else None
    if callable(resolver):
        try:
            node = resolver(str(root_path or "").strip())
        except Exception:
            node = None
    if node is not None:
        child_family = _family_from_category(
            _safe_category(node, "childTypeCategory")
        )
        if child_family is not None:
            return child_family
    authored_family = _family_from_category(category)
    if authored_family is not None and authored_family != "object":
        return authored_family
    path_family = _path_family(root_path)
    if path_family is not None:
        return path_family
    if authored_family is not None:
        return authored_family
    live_family = _family_from_category(_node_type_category(node))
    return live_family or "generic"


def connection_mismatch(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, Any] | None:
    """Return bounded exact connector drift, including names when authored."""
    comparisons = (
        ("sourcePath", "sourcePath"),
        ("inputIndex", "inputIndex"),
        ("sourceOutputIndex", "outputIndex"),
    )
    mismatches = {
        expected_name: {
            "expected": expected.get(expected_name),
            "actual": observed.get(observed_name),
        }
        for expected_name, observed_name in comparisons
        if expected.get(expected_name) != observed.get(observed_name)
    }
    for expected_name, observed_name in (
        ("sourceOutputName", "outputName"),
        ("destInputName", "inputName"),
    ):
        value = expected.get(expected_name)
        if isinstance(value, str) and value and value != observed.get(observed_name):
            mismatches[expected_name] = {
                "expected": value,
                "actual": observed.get(observed_name),
            }
    return mismatches or None
