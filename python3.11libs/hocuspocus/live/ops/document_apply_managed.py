"""Managed-field planning helpers for document apply."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from hocuspocus.hocusscript.document_reconcile import validated_managed_fields


_IDENTITY_FIELDS = (
    "entityKind",
    "projectUid",
    "graphName",
    "ownership",
)


def _hocus(entity: dict[str, Any]) -> dict[str, Any] | None:
    metadata = entity.get("metadata")
    value = metadata.get("hocus") if isinstance(metadata, dict) else None
    return value if isinstance(value, dict) else None


def _managed_manifest(
    node: dict[str, Any] | None,
    ownerships: set[str],
) -> dict[str, Any] | None:
    value = _hocus(node or {})
    ownership = str(value.get("ownership") or "").strip() if value else ""
    if ownership not in ownerships:
        return None
    uid = (node or {}).get("uid")
    return (
        validated_managed_fields(node or {}, uid)
        if isinstance(uid, str) else None
    )


def _reconcile_ownerships(document: dict[str, Any]) -> set[str]:
    metadata = document.get("metadata")
    preview = metadata.get("hocusPreview") if isinstance(metadata, dict) else None
    values = (
        preview.get("ownership") if isinstance(preview, dict) else None,
        metadata.get("reconcileOwnership") if isinstance(metadata, dict) else None,
    )
    requested = {
        str(value).strip() for value in values if str(value or "").strip()
    }
    return requested if len(requested) == 1 else set()


def plan_connection_changes(
    operations: Any,
    baseline: dict[str, Any],
    target: dict[str, Any],
    mode: str,
    target_nodes_by_uid: dict[str, dict[str, Any]],
    create_uids: set[str],
    structural_changed_uids: set[str],
) -> list[dict[str, Any]]:
    current_inputs = operations._document_data_connection_map(baseline)
    target_inputs = operations._document_data_connection_map(target)
    ownerships = _reconcile_ownerships(target) if mode == "reconcile" else set()
    forced = {
        dest_uid
        for dest_uid, desired in target_inputs.items()
        if dest_uid in create_uids
        or dest_uid in structural_changed_uids
        or any(
            connection.get("sourceUid") in structural_changed_uids
            for connection in desired.values()
            if connection.get("sourceUid")
        )
    }
    baseline_nodes = operations._document_nodes_by_uid(baseline)
    changes: list[dict[str, Any]] = []
    for dest_uid in sorted(
        target_nodes_by_uid,
        key=lambda item: str(target_nodes_by_uid[item].get("path", "")),
    ):
        current = current_inputs.get(dest_uid, {})
        desired = target_inputs.get(dest_uid, {})
        managed = _managed_manifest(baseline_nodes.get(dest_uid), ownerships)
        prior_managed = set(managed.get("inputs", [])) if managed else set()
        indices = (
            set(desired)
            if mode == "merge"
            else set(desired) | prior_managed
        )
        for index in sorted(indices):
            connection = desired.get(index)
            if (
                dest_uid not in forced
                and current.get(index) == connection
            ):
                continue
            if connection is None and index not in prior_managed:
                continue
            source_uid = connection.get("sourceUid") if connection else None
            changes.append({
                "destUid": dest_uid,
                "destPath": str(
                    target_nodes_by_uid.get(dest_uid, {}).get("path", "")
                ).strip(),
                "inputIndex": index,
                "sourceUid": source_uid,
                "sourcePath": (
                    str(
                        target_nodes_by_uid.get(source_uid, {}).get("path", "")
                    ).strip()
                    if source_uid else None
                ),
                **(
                    {
                        key: connection.get(key)
                        for key in (
                            "sourceOutputIndex",
                            "sourceOutputName",
                            "destInputName",
                            "connectionOrder",
                        )
                    }
                    if connection else {
                        "sourceOutputIndex": 0,
                        "sourceOutputName": None,
                        "destInputName": None,
                        "connectionOrder": index,
                    }
                ),
            })
    return changes


def _identity_changes(
    target_nodes: dict[str, dict[str, Any]],
    baseline_nodes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updates = [
        {
            "uid": uid,
            "path": str(node.get("path", "")).strip(),
            "metadata": copy.deepcopy(node.get("metadata", {})),
        }
        for uid, node in sorted(target_nodes.items())
        if uid in baseline_nodes
        and _hocus(node) is not None
        and (
            str((baseline_nodes[uid].get("metadata") or {}).get(
                "identityMode", ""
            )) != "persistent_user_data"
            or _hocus(baseline_nodes[uid]) != _hocus(node)
        )
    ]
    clears = [
        {"uid": uid, "path": str(node.get("path", "")).strip()}
        for uid, node in sorted(target_nodes.items())
        if uid in baseline_nodes
        and _hocus(baseline_nodes[uid]) is not None
        and _hocus(node) is None
    ]
    return updates, clears


def _binding_entry(
    key: tuple[str, str],
    binding: dict[str, Any],
    target_nodes: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    node_uid, parm_name = key
    node = target_nodes.get(node_uid)
    if node is None:
        return None
    return {
        "bindingUid": str(binding.get("uid", "")).strip(),
        "nodeUid": node_uid,
        "nodePath": str(node.get("path", "")).strip(),
        "parmName": parm_name,
        "metadata": copy.deepcopy(binding.get("metadata", {}))
        if isinstance(binding.get("metadata"), dict) else {},
    }


def _planned_resets(
    baseline_bindings: dict[tuple[str, str], dict[str, Any]],
    target_bindings: dict[tuple[str, str], dict[str, Any]],
    baseline_nodes: dict[str, dict[str, Any]],
    target_nodes: dict[str, dict[str, Any]],
    ownerships: set[str],
) -> list[dict[str, Any]]:
    resets: list[dict[str, Any]] = []
    for key in sorted(set(baseline_bindings) - set(target_bindings)):
        node_uid, parm_name = key
        manifest = _managed_manifest(baseline_nodes.get(node_uid), ownerships)
        if (
            node_uid not in target_nodes
            or manifest is None
            or parm_name not in manifest.get("parameters", [])
        ):
            continue
        reset = _binding_entry(key, baseline_bindings[key], target_nodes)
        if reset is not None:
            resets.append(reset)
    return resets


@dataclass(slots=True)
class _BindingChanges:
    assignments: list[dict[str, Any]] = field(default_factory=list)
    expressions: list[dict[str, Any]] = field(default_factory=list)
    installs: list[dict[str, Any]] = field(default_factory=list)
    typed_updates: list[dict[str, Any]] = field(default_factory=list)


def _append_target_binding(
    operations: Any,
    key: tuple[str, str],
    binding: dict[str, Any],
    update: dict[str, Any],
    *,
    target_nodes: dict[str, dict[str, Any]],
    blobs: dict[str, dict[str, Any]],
    baseline_blob: dict[str, Any] | None,
    force: bool,
    unchanged: bool,
    changes: _BindingChanges,
) -> None:
    mode_name = str(binding.get("valueMode", "")).strip()
    if mode_name == "reset":
        if force or not unchanged:
            changes.typed_updates.append({
                **update, "valueMode": "reset", "explicit": True,
            })
        return
    if mode_name == "code_reference":
        _append_code_install(
            operations, key, binding, update, target_nodes, blobs,
            baseline_blob, force, unchanged, changes,
        )
        return
    if not force and unchanged:
        return
    if mode_name in {"literal", "menu_token", "raw_path", "quantity"}:
        _append_assignment(mode_name, binding, update, changes)
    elif mode_name in {"expression", "channel_reference"}:
        _append_expression(
            operations, mode_name, binding, update, target_nodes, changes
        )
    elif mode_name in {"ramp", "multiparm"}:
        changes.typed_updates.append({
            **update,
            "valueMode": mode_name,
            "typedBinding": copy.deepcopy(binding),
        })


def _append_code_install(
    operations: Any,
    key: tuple[str, str],
    binding: dict[str, Any],
    update: dict[str, Any],
    target_nodes: dict[str, dict[str, Any]],
    blobs: dict[str, dict[str, Any]],
    baseline_blob: dict[str, Any] | None,
    force: bool,
    unchanged: bool,
    changes: _BindingChanges,
) -> None:
    blob_uid = str(binding.get("codeBlobUid", "")).strip()
    blob = blobs.get(blob_uid, {})
    if not force and unchanged and baseline_blob == blob:
        return
    language = operations._document_normalize_language(blob.get("language"))
    changes.installs.append({
        **update,
        "codeBlobUid": blob_uid,
        "language": language,
        "adapter": operations._document_code_adapter_for(
            target_nodes[key[0]].get("typeName"), key[1], language,
        ),
        "body": blob.get("body", ""),
    })


def _append_assignment(
    mode_name: str,
    binding: dict[str, Any],
    update: dict[str, Any],
    changes: _BindingChanges,
) -> None:
    assigned = {
        "literal": binding.get("value"),
        "menu_token": binding.get("menuToken"),
        "raw_path": binding.get("raw"),
        "quantity": binding.get("canonicalMagnitude"),
    }[mode_name]
    changes.assignments.append({
        **update,
        "value": assigned,
        "valueMode": mode_name,
        "typedBinding": copy.deepcopy(binding),
    })


def _append_expression(
    operations: Any,
    mode_name: str,
    binding: dict[str, Any],
    update: dict[str, Any],
    target_nodes: dict[str, dict[str, Any]],
    changes: _BindingChanges,
) -> None:
    expression = binding.get("expression")
    language = operations._document_normalize_language(
        binding.get("expressionLanguage") or "hscript"
    )
    if mode_name == "channel_reference" and not str(expression or "").strip():
        reference = binding.get("channelReference")
        reference_uid = (
            reference.get("nodeUid") if isinstance(reference, dict) else None
        )
        reference_parm = (
            reference.get("parmName") if isinstance(reference, dict) else None
        )
        reference_path = str(
            target_nodes.get(reference_uid, {}).get("path", "")
        ).strip()
        if not reference_path or not isinstance(reference_parm, str):
            return
        expression, language = operations._document_compile_channel_reference(
            f"{reference_path}/{reference_parm}", update["metadata"]
        )
    changes.expressions.append({
        **update,
        "expression": expression,
        "expressionLanguage": language,
        **(
            {"channelReference": binding.get("channelReference")}
            if mode_name == "channel_reference" else {}
        ),
    })


def plan_binding_changes(
    operations: Any,
    baseline: dict[str, Any],
    target: dict[str, Any],
    mode: str,
    target_nodes: dict[str, dict[str, Any]],
    baseline_nodes: dict[str, dict[str, Any]],
    create_uids: set[str],
) -> tuple[list[dict[str, Any]], ...]:
    baseline_blobs = operations._document_code_blobs_by_uid(baseline)
    baseline_bindings = operations._document_bindings_by_key(baseline)
    target_bindings = operations._document_bindings_by_key(target)
    blobs = operations._document_code_blobs_by_uid(target)
    changes = _BindingChanges()
    ownerships = _reconcile_ownerships(target) if mode == "reconcile" else set()
    identity_updates, identity_clears = _identity_changes(
        target_nodes, baseline_nodes
    )

    for key in sorted(
        target_bindings,
        key=lambda item: (str(target_nodes.get(item[0], {}).get("path", "")), item[1]),
    ):
        binding = target_bindings[key]
        update = _binding_entry(key, binding, target_nodes)
        if update is None:
            continue
        force = key[0] in create_uids
        unchanged = baseline_bindings.get(key) == binding
        _append_target_binding(
            operations,
            key,
            binding,
            update,
            target_nodes=target_nodes,
            blobs=blobs,
            baseline_blob=baseline_blobs.get(
                str(binding.get("codeBlobUid", "")).strip()
            ),
            force=force,
            unchanged=unchanged,
            changes=changes,
        )

    resets = _planned_resets(
        baseline_bindings, target_bindings, baseline_nodes, target_nodes,
        ownerships,
    )
    resets.extend(
        {
            key: item[key]
            for key in ("bindingUid", "nodeUid", "nodePath", "parmName", "metadata")
        }
        for item in changes.typed_updates
        if item["valueMode"] == "reset"
    )
    typed_updates = [
        item for item in changes.typed_updates if item["valueMode"] != "reset"
    ]

    return (
        changes.assignments,
        changes.expressions,
        changes.installs,
        identity_updates,
        identity_clears,
        resets,
        typed_updates,
    )


def identity_update_mismatches(
    candidate: dict[str, Any],
    execution_plan: dict[str, Any],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    actions = {
        (item.get("action"), item.get("entityUid"))
        for item in candidate.get("operations", [])
        if isinstance(item, dict)
        and item.get("action") in {"adopt_node", "update_node_provenance"}
    }
    baseline_nodes = {
        item.get("uid"): item
        for item in baseline.get("nodes", [])
        if isinstance(item, dict)
    }
    expected: set[tuple[str, Any]] = set()
    mismatches: list[dict[str, Any]] = []
    for update in execution_plan.get("identityUpdates", []):
        uid = update.get("uid")
        before = _hocus(baseline_nodes.get(uid, {}))
        after = _hocus(update)
        if after is None:
            mismatches.append({"uid": uid, "reason": "missing_target_provenance"})
            continue
        action = "adopt_node" if before is None else "update_node_provenance"
        if before is not None and any(
            before.get(field) != after.get(field) for field in _IDENTITY_FIELDS
        ):
            mismatches.append({"uid": uid, "reason": "identity_transition"})
            continue
        expected.add((action, uid))
    for action, uid in sorted(actions ^ expected, key=lambda item: str(item)):
        mismatches.append({
            "uid": uid,
            "action": action,
            "reason": "candidate_execution_mismatch",
        })
    return mismatches
