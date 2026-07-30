"""Shared guarded-pipeline helpers for the installed HS7 acceptance extension."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import hou  # type: ignore

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.hocusscript.control_artifact import (
    ControlArtifactError,
    _compile_control_bundle,
)
from hocuspocus.hocusscript.control_expander import expand_control_graph
from hocuspocus.hocusscript.control_resolver import ControlResolverLimits
from hocuspocus.live.context import RequestContext
from smoke_hocusscript_h5 import (
    _apply_success,
    _preview_artifact,
    _rollback_gate,
)


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def compile_value_bundle(
    source: str,
    *,
    label: str,
    catalog: Any,
) -> dict[str, Any]:
    """Compile one source-authored language-0.4 graph against exact catalog v2."""

    if catalog.catalog_version != 2:
        raise RuntimeError("HS7 rich acceptance requires exact catalog v2.")
    uri = f"hocus-project://hs7-installed/{label}.hocus"
    graph = expand_control_graph(source.encode("utf-8"), uri, {}, {})
    project_uid = "hs7-installed"
    resolved = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v3",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 3,
        "languageVersion": "0.4",
        "projectUid": project_uid,
        "entrySourceUri": uri,
        "projectManifestDigest": digest_text(project_uid + ":manifest"),
        "projectLockDigest": digest_text(project_uid + ":lock"),
        "resolverPolicyDigest": digest_text(project_uid + ":resolver"),
        "limits": ControlResolverLimits().to_dict(),
        "modules": [],
    }
    try:
        return _compile_control_bundle(
            graph,
            resolved,
            entry_source_digest=digest_text(source),
            catalog=catalog,
            catalog_content_digest=digest_text(catalog.to_json()),
            catalog_fingerprint=catalog.fingerprint,
            admitted_required_capabilities=("edit_scene",),
        ).to_dict()
    except ControlArtifactError as exc:
        raise RuntimeError(
            f"HS7 source bundle {label!r} failed {exc.code}: "
            f"{exc.message}; details={exc.details!r}"
        ) from exc


def preview_plan_apply(
    operations: Any,
    bundle: dict[str, Any],
    *,
    label: str,
    context: RequestContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prove deterministic preview, immutable plan, guarded apply, and replay."""

    first = operations.document_preview_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    second = operations.document_preview_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    first_artifact = _preview_artifact(operations, first)
    second_artifact = _preview_artifact(operations, second)
    if (
        not first.get("valid")
        or not first.get("readyForPlan")
        or first_artifact["candidatePlan"]["planHash"]
        != second_artifact["candidatePlan"]["planHash"]
        or first_artifact["diff"] != second_artifact["diff"]
    ):
        raise RuntimeError(
            f"HS7 preview is invalid or nondeterministic: {label}; "
            f"first={first!r}; second={second!r}"
        )
    applied = _apply_success(operations, bundle, label, context)
    return {
        "previewId": (first.get("artifact") or {}).get("previewId"),
        "previewPlanHash": first_artifact["candidatePlan"]["planHash"],
        "planId": applied["planId"],
        "planHash": applied["planHash"],
        "applyCommitId": applied["applyCommitId"],
        "operationCount": applied["operationCount"],
    }, first_artifact["document"]


def apply_reconcile(
    operations: Any,
    bundle: dict[str, Any],
    *,
    label: str,
    context: RequestContext,
) -> dict[str, Any]:
    receipt = _apply_success(operations, bundle, label, context)
    return {
        "planId": receipt["planId"],
        "planHash": receipt["planHash"],
        "applyCommitId": receipt["applyCommitId"],
        "operationCount": receipt["operationCount"],
    }


def rollback_injection(
    operations: Any,
    bundle: dict[str, Any],
    *,
    root_path: str,
    context: RequestContext,
    projection: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Inject a mid-executor failure and prove the full document projection returns."""

    before = projection(
        operations._document_current_network_payload(
            root_path, force_sync=True
        )
    )
    receipt = _rollback_gate(
        operations, bundle, root_path, context,
    )
    after = projection(
        operations._document_current_network_payload(
            root_path, force_sync=True
        )
    )
    if after != before:
        raise RuntimeError(
            f"HS7 rollback changed the managed projection for {root_path}."
        )
    return receipt


def export_recompile(
    operations: Any,
    *,
    root_path: str,
    graph_name: str,
    catalog: Any,
    context: RequestContext,
) -> tuple[dict[str, Any], str]:
    exported = operations.document_export_source(
        {"root_path": root_path, "graph_name": graph_name},
        context,
    )["structuredContent"]
    source = exported.get("source")
    if (
        not exported.get("valid")
        or exported.get("languageVersion") != "0.4"
        or not isinstance(source, str)
        or not source.startswith("hocus 0.4;")
    ):
        raise RuntimeError(
            f"HS7 language-0.4 export failed for {root_path}: "
            f"{exported.get('diagnostics')!r}"
        )
    bundle = compile_value_bundle(
        source, label=f"{graph_name}-export", catalog=catalog,
    )
    return bundle, source


def expect_preview_rejection(
    operations: Any,
    bundle: dict[str, Any],
    *,
    codes: set[str],
    context: RequestContext,
) -> list[str]:
    result = operations.document_preview_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    actual = {
        str(item.get("code"))
        for item in result.get("diagnostics", [])
        if isinstance(item, dict)
    }
    if result.get("valid") or not codes <= actual:
        raise RuntimeError(
            "HS7 preview did not fail closed with the expected diagnostics: "
            f"expected={sorted(codes)!r}, actual={sorted(actual)!r}"
        )
    return sorted(actual)


def save_reopen(
    operations: Any,
    hip_path: Path,
    context: RequestContext,
) -> None:
    operations.scene_save_hip(
        {"path": str(hip_path), "save_to_recent_files": False}, context,
    )
    operations.scene_new({}, context)
    operations._monitor.mark_dirty("hs7.ext.scene.new")
    operations.scene_open_hip(
        {
            "path": str(hip_path),
            "suppress_save_prompt": True,
            "ignore_load_warnings": False,
        },
        context,
    )
    operations._monitor.mark_dirty("hs7.ext.scene.reopen")


def document_projection(
    document: dict[str, Any],
    *,
    collections: tuple[str, ...],
) -> dict[str, Any]:
    """Canonicalize only user-visible managed topology and value collections."""

    result: dict[str, Any] = {}
    for name in collections:
        values = []
        for item in document.get(name, []):
            if not isinstance(item, dict):
                continue
            if name == "parameterBindings":
                metadata = item.get("metadata")
                hocus = (
                    metadata.get("hocus")
                    if isinstance(metadata, dict) else None
                )
                if (
                    not isinstance(hocus, dict)
                    or hocus.get("entityKind") != "parameter_binding"
                ):
                    continue
            if str(item.get("uid", "")).startswith("artist:"):
                continue
            carried = copy.deepcopy(item)
            carried.pop("metadata", None)
            # Optional catalog resolution provenance has no observable live HOM
            # counterpart and is intentionally outside document diff equivalence.
            carried.pop("definitionRef", None)
            values.append(carried)
        result[name] = sorted(
            values,
            key=lambda item: (
                str(item.get("uid", "")),
                json.dumps(item, sort_keys=True, ensure_ascii=False),
            ),
        )
    return result


def projection_differences(
    before: Any, after: Any, *, limit: int = 64,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if len(differences) >= limit or left == right:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{path}/{key}"
                if key not in left or key not in right:
                    differences.append({
                        "path": child,
                        "before": left.get(key, "<absent>"),
                        "after": right.get(key, "<absent>"),
                    })
                else:
                    walk(left[key], right[key], child)
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                differences.append({
                    "path": path + "/length",
                    "before": len(left), "after": len(right),
                })
            for index, (first, second) in enumerate(zip(left, right)):
                walk(first, second, f"{path}/{index}")
            return
        differences.append({"path": path, "before": left, "after": right})

    walk(before, after, "")
    return differences


def assert_zero_cooks(root_paths: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for root_path in root_paths:
        root = hou.node(root_path)
        if root is None:
            raise RuntimeError(f"HS7 acceptance root disappeared: {root_path}.")
        for node in root.children():
            count = node.cookCount()
            counts[node.path()] = count
    if any(value != 0 for value in counts.values()):
        raise RuntimeError(f"HS7 acceptance executed a cook: {counts!r}")
    return dict(sorted(counts.items()))


def expect_jsonrpc(code: str, callback: Callable[[], Any]) -> JsonRpcError:
    try:
        callback()
    except JsonRpcError as exc:
        if (exc.data or {}).get("diagnosticCode") == code:
            return exc
        raise
    raise RuntimeError(f"Expected {code}, but the HS7 operation succeeded.")
