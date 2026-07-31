"""Bounded entity validation for pure document lowering baselines."""

from __future__ import annotations

import copy
from typing import Any

from .document_value_validation import (
    DocumentValueValidationError,
    validate_v2_binding,
)


class DocumentBaselineEntityError(ValueError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


def document_diff(
    before: dict[str, Any],
    after: dict[str, Any],
    specs: tuple[tuple[str, str, str], ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    summary: dict[str, int] = {}
    total = 0
    for label, singular, field in specs:
        old = {item["uid"]: item for item in before.get(field, [])}
        new = {item["uid"]: item for item in after.get(field, [])}
        created = [copy.deepcopy(new[uid]) for uid in sorted(set(new) - set(old))]
        deleted = [copy.deepcopy(old[uid]) for uid in sorted(set(old) - set(new))]
        changed = [
            {"uid": uid, "before": copy.deepcopy(old[uid]), "after": copy.deepcopy(new[uid])}
            for uid in sorted(set(old) & set(new))
            if _operational_entity(old[uid]) != _operational_entity(new[uid])
        ]
        result[f"created{label}"] = created
        result[f"deleted{label}"] = deleted
        result[f"changed{label}"] = changed
        summary[f"created{singular}Count"] = len(created)
        summary[f"deleted{singular}Count"] = len(deleted)
        summary[f"changed{singular}Count"] = len(changed)
        total += len(created) + len(deleted) + len(changed)
    summary["totalChangeCount"] = total
    return {
        "summary": summary,
        **{key: result[key] for key in sorted(result)},
    }


def destructive_summary(diff: dict[str, Any], adopted_uids: set[str]) -> dict[str, Any]:
    deleted_nodes = diff["deletedNodes"]
    editor_labels = ("NetworkBoxes", "StickyNotes", "NodeComments", "NetworkDots", "LayoutConstraints")
    deleted_editor = sum(len(diff[f"deleted{label}"]) for label in editor_labels)
    changed_editor = sum(len(diff[f"changed{label}"]) for label in editor_labels)
    runtime_changes = (
        diff["deletedSpareParameters"] + diff["changedSpareParameters"]
        + diff["deletedAnimations"] + diff["changedAnimations"]
    )
    retyped = [item["uid"] for item in diff["changedNodes"]
               if item["before"].get("typeName") != item["after"].get("typeName")]
    displaced_display = [
        item["uid"] for item in diff["changedNodes"]
        if bool((item["before"].get("flags") or {}).get("display"))
        and not bool((item["after"].get("flags") or {}).get("display"))
    ]
    displaced_render = [
        item["uid"] for item in diff["changedNodes"]
        if bool((item["before"].get("flags") or {}).get("render"))
        and not bool((item["after"].get("flags") or {}).get("render"))
    ]
    return {
        "destructive": bool(deleted_nodes or diff["deletedParameterBindings"] or diff["deletedCodeBlobs"]
                            or diff["deletedEdges"] or adopted_uids or retyped
                            or deleted_editor or changed_editor or runtime_changes),
        "deletedNodeCount": len(deleted_nodes),
        "deletedParameterBindingCount": len(diff["deletedParameterBindings"]),
        "deletedCodeBlobCount": len(diff["deletedCodeBlobs"]),
        "disconnectedEdgeCount": len(diff["deletedEdges"]),
        "adoptedNodeCount": len(adopted_uids),
        "ownershipTransfer": bool(adopted_uids),
        "replacedNodeCount": len(retyped),
        "deletedEditorEntityCount": deleted_editor,
        "changedEditorEntityCount": changed_editor,
        "removedSpareParameterCount": len(diff["deletedSpareParameters"]),
        "updatedSpareParameterCount": len(diff["changedSpareParameters"]),
        "clearedAnimationCount": len(diff["deletedAnimations"]),
        "updatedAnimationCount": len(diff["changedAnimations"]),
        "displacedDisplayNodeCount": len(displaced_display),
        "displacedRenderNodeCount": len(displaced_render),
        "deletedNodeUids": sorted(item["uid"] for item in deleted_nodes),
        "adoptedNodeUids": sorted(adopted_uids),
        "replacedNodeUids": sorted(retyped),
        "displacedDisplayNodeUids": sorted(displaced_display),
        "displacedRenderNodeUids": sorted(displaced_render),
    }


def _operational_entity(entity: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(entity)
    result.pop("metadata", None)
    result.pop("definitionRef", None)
    return result


def validate_baseline_entities(
    result: dict[str, Any], *, schema_v1: str, schema_v2: str,
) -> None:
    node_uids = _nodes(result["nodes"])
    _ports(result["ports"], node_uids)
    _edges(result["edges"], node_uids)
    binding_uids = _bindings(
        result["parameterBindings"], node_uids, result["$schema"],
        schema_v1, schema_v2,
    )
    _code(result["codeBlobs"], node_uids, binding_uids)


def _nodes(nodes: list[dict[str, Any]]) -> set[str]:
    required = {
        "uid", "name", "typeName", "category", "path", "parentPath",
        "isNetwork", "flags", "metadata",
    }
    uids: set[str] = set()
    paths: set[str] = set()
    for node in nodes:
        uid = node.get("uid") if isinstance(node, dict) else None
        path = node.get("path") if isinstance(node, dict) else None
        flags = node.get("flags") if isinstance(node, dict) else None
        if (
            not isinstance(node, dict)
            or not required.issubset(node)
            or not isinstance(uid, str)
            or not isinstance(path, str)
            or not path.startswith("/")
            or uid in uids
            or path in paths
            or not isinstance(flags, dict)
            or set(flags) != {"display", "render", "bypass", "template"}
            or any(type(value) is not bool for value in flags.values())
        ):
            raise DocumentBaselineEntityError(
                "Baseline contains a malformed or duplicate node.",
                uid=uid,
            )
        uids.add(uid)
        paths.add(path)
    return uids


def _ports(ports: list[dict[str, Any]], node_uids: set[str]) -> None:
    for port in ports:
        if (
            not isinstance(port, dict)
            or port.get("nodeUid") not in node_uids
            or port.get("direction") not in {"input", "output"}
        ):
            raise DocumentBaselineEntityError(
                "Baseline contains a dangling or malformed port.",
                uid=port.get("uid") if isinstance(port, dict) else None,
            )


def _edges(edges: list[dict[str, Any]], node_uids: set[str]) -> None:
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or edge.get("from", {}).get("nodeUid") not in node_uids
            or edge.get("to", {}).get("nodeUid") not in node_uids
        ):
            raise DocumentBaselineEntityError(
                "Baseline contains a dangling edge.",
                uid=edge.get("uid") if isinstance(edge, dict) else None,
            )


def _bindings(
    bindings: list[dict[str, Any]],
    node_uids: set[str],
    schema_uri: str,
    schema_v1: str,
    schema_v2: str,
) -> set[str]:
    uids: set[str] = set()
    for binding in bindings:
        uid = binding.get("uid") if isinstance(binding, dict) else None
        if not isinstance(uid, str) or not uid or uid in uids:
            raise DocumentBaselineEntityError(
                "Baseline binding identity is malformed.", uid=uid
            )
        uids.add(uid)
        if schema_uri == schema_v2:
            try:
                validate_v2_binding(binding, node_uids)
            except DocumentValueValidationError as exc:
                raise DocumentBaselineEntityError(
                    f"Baseline contains a malformed v2 binding: {exc}",
                    uid=uid,
                ) from exc
        elif (
            schema_uri != schema_v1
            or binding.get("nodeUid") not in node_uids
            or binding.get("valueMode") not in {
                "literal", "expression", "channel_reference",
                "code_reference",
            }
            or (
                binding.get("valueMode") == "literal"
                and isinstance(binding.get("value"), (list, dict))
            )
        ):
            raise DocumentBaselineEntityError(
                "Baseline contains a malformed v1 binding.", uid=uid
            )
    return uids


def _code(
    blobs: list[dict[str, Any]],
    node_uids: set[str],
    binding_uids: set[str],
) -> None:
    for blob in blobs:
        target = blob.get("target", {}) if isinstance(blob, dict) else {}
        if (
            target.get("nodeUid") not in node_uids
            or (
                target.get("bindingUid") is not None
                and target.get("bindingUid") not in binding_uids
            )
        ):
            raise DocumentBaselineEntityError(
                "Baseline contains a dangling code blob.",
                uid=blob.get("uid") if isinstance(blob, dict) else None,
            )
