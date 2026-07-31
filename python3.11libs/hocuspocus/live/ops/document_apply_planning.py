"""Structural planning helpers for document apply."""

from __future__ import annotations

from typing import Any


def structural_context(
    operations: Any,
    baseline: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    before = operations._document_nodes_by_uid(baseline)
    after = operations._document_nodes_by_uid(target)
    before_paths = operations._document_node_uid_by_path(baseline)
    after_paths = operations._document_node_uid_by_path(target)
    root_path = str(target.get("rootPath", "")).strip()
    root_uid = after_paths.get(root_path) or before_paths.get(root_path)
    shared = set(before) & set(after)
    changed = {
        uid
        for uid in shared
        if any(
            before[uid].get(key) != after[uid].get(key)
            for key in ("path", "name", "parentPath", "typeName")
        )
    }
    replacements = {
        uid
        for uid in shared
        if uid != root_uid
        and before[uid].get("typeName") != after[uid].get("typeName")
    }
    replacement_paths = [
        str(before[uid].get("path", "")).strip() for uid in replacements
    ]
    recreated = {
        uid
        for uid in shared
        if uid not in replacements
        and any(
            operations._document_path_is_within(
                str(before[uid].get("path", "")).strip(), prefix
            )
            and str(before[uid].get("path", "")).strip() != prefix
            for prefix in replacement_paths
        )
    }
    created = (
        {uid for uid in after if uid not in before} | replacements | recreated
    ) - ({root_uid} if root_uid else set())
    return {
        "before": before,
        "after": after,
        "beforePaths": before_paths,
        "afterPaths": after_paths,
        "rootPath": root_path,
        "rootUid": root_uid,
        "shared": shared,
        "changed": changed,
        "replacements": replacements,
        "replacementPaths": replacement_paths,
        "created": created,
    }


def structural_moves(
    operations: Any,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    renamed: list[dict[str, Any]] = []
    reparented: list[dict[str, Any]] = []
    before, after = context["before"], context["after"]
    for uid in sorted(
        context["shared"],
        key=lambda item: str(before[item].get("path", "")).count("/"),
    ):
        if (
            uid == context["rootUid"]
            or uid in context["created"]
            or uid in context["replacements"]
            or operations._document_path_change_inherited_only(
                uid,
                before,
                after,
                context["beforePaths"],
                context["afterPaths"],
                context["changed"],
            )
        ):
            continue
        before_node, after_node = before[uid], after[uid]
        before_path = str(before_node.get("path", "")).strip()
        after_path = str(after_node.get("path", "")).strip()
        before_parent = context["beforePaths"].get(
            str(before_node.get("parentPath", "")).strip()
        )
        after_parent = context["afterPaths"].get(
            str(after_node.get("parentPath", "")).strip()
        )
        target_name = (
            str(after_node.get("name", "")).strip()
            or after_path.rsplit("/", 1)[-1]
        )
        common = {
            "uid": uid,
            "currentPath": before_path,
            "targetPath": after_path,
            "targetName": target_name,
        }
        if before_parent != after_parent:
            reparented.append(
                {
                    **common,
                    "targetParentPath": str(
                        after_node.get("parentPath", "")
                    ).strip(),
                }
            )
        elif (
            before_path != after_path
            or str(before_node.get("name", "")).strip() != target_name
        ):
            renamed.append(common)
    return renamed, reparented
