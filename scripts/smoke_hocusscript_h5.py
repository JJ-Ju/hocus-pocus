"""Qualify installed H5 Bundle 0.3/0.4 workflows in disposable Houdini state.
This script must run from the repository under Houdini 22.0.368 ``hython``
after a clean package install and a Houdini restart.  It deliberately imports
only the installed HocusPocus package, performs no cooks, and destroys its
temporary scene and files before exit.

Usage:
    "C:\\Program Files\\Side Effects Software\\Houdini 22.0.368\\bin\\hython.exe" ^
        scripts\\smoke_hocusscript_h5.py
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

import hou  # type: ignore
from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.core.settings import ServerSettings
from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    lower_bundle_to_document,
    resolve_graph,
)
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_cache import LiveSceneGraphCache
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.operations import LiveOperations
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.graph import GraphOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from hocuspocus.live.ops.node import NodeOperationsMixin
from hocuspocus.live.ops.parm import ParmOperationsMixin
from hocuspocus.live.ops.scene import SceneOperationsMixin
from smoke_hocusscript_h5_support import (
    apply_checkpoint_count,
    build_acceptance_bundles,
    durable_pruning_gate,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "module_v03": "/obj/h5e_module_v03",
    "control_local_v04": "/obj/h5e_control_local_v04",
    "control_mixed_v04": "/obj/h5e_control_mixed_v04",
}
ROLLBACK_TARGET = "/obj/h5e_control_rollback_v04"
RECOVERY_TARGET = "/obj/h5e_control_recovery_v04"
ALL_TARGETS = (*TARGETS.values(), ROLLBACK_TARGET, RECOVERY_TARGET)
SCHEMA_RESOURCES = {
    "houdini://documents/schema/graph-spec/v0.4":
        "hocuspocus://schemas/graph-spec/v0.4",
    "houdini://documents/schema/expansion-map/v2":
        "hocuspocus://schemas/expansion-map/v2",
    "houdini://documents/schema/resolved-module-set/v2":
        "hocuspocus://schemas/resolved-module-set/v2",
    "houdini://documents/schema/compiled-bundle/v0.4":
        "hocuspocus://schemas/compiled-bundle/v0.4",
}
CRITICAL_MODULES = (
    "hocuspocus.hocusscript._control_ast_validation",
    "hocuspocus.hocusscript.bundle",
    "hocuspocus.hocusscript.bundle_semantic_validation",
    "hocuspocus.hocusscript.contracts",
    "hocuspocus.hocusscript._document_bundle_boundary",
    "hocuspocus.hocusscript.document_bundle_lowering",
    "hocuspocus.hocusscript.document_bundle_semantics",
    "hocuspocus.hocusscript.document_live_names",
    "hocuspocus.hocusscript.document_lowering",
    "hocuspocus.hocusscript.document_provenance",
    "hocuspocus.hocusscript.document_reconcile",
    "hocuspocus.hocusscript.control_semantic",
    "hocuspocus.hocusscript.external_roots",
    "hocuspocus.hocusscript.exporter",
    "hocuspocus.hocusscript.semantic",
    "hocuspocus.live.operations",
    "hocuspocus.live.document_service",
    "hocuspocus.live.graph_store",
    "hocuspocus.live.graph_store_documents",
    "hocuspocus.live.graph_store_sqlite",
    "hocuspocus.live.graph_store_live_revisions",
    "hocuspocus.live.graph_store_plans",
    "hocuspocus.live.ops.document",
    "hocuspocus.live.ops.document_apply",
    "hocuspocus.live.ops.document_apply_managed",
    "hocuspocus.live.ops.document_apply_planning",
    "hocuspocus.live.ops.document_diff",
    "hocuspocus.live.ops.document_entity_provenance",
    "hocuspocus.live.ops.document_expansion_provenance",
    "hocuspocus.live.ops.document_metadata",
    "hocuspocus.live.ops.document_snapshot",
    "hocuspocus.live.ops.document_validation",
    "hocuspocus.live.ops.graph",
    "hocuspocus.live.ops.hocusscript",
    "hocuspocus.live.ops.hocusscript_apply",
    "hocuspocus.live.ops.hocusscript_recovery",
    "hocuspocus.live.ops.hocusscript_resources",
    "hocuspocus.live.ops.parm",
)
COOK_OBSERVATIONS = {"nodeChecks": 0, "cookCount": 0}
def _progress(stage: str) -> None:
    print(f"H5E_STAGE {stage}", file=sys.stderr, flush=True)

class _Dispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()
class _Monitor:
    def __init__(self) -> None:
        self.revision = 1
    def snapshot(self) -> dict[str, int]:
        return {"revision": self.revision}

    def mark_dirty(self, *_args, **_kwargs) -> int:
        self.revision += 1
        return self.revision

    @staticmethod
    def clear_scope_dirty(_scope) -> None:
        return None


class _H5SmokeOperations(
    OperationBaseMixin,
    GraphOperationsMixin,
    DocumentOperationsMixin,
    HocusScriptOperationsMixin,
    NodeOperationsMixin,
    ParmOperationsMixin,
    SceneOperationsMixin,
):
    def __init__(self, catalog, temporary_root: Path):
        logger = logging.getLogger("hocus.h5.installed-smoke")
        self._catalog = catalog
        self._dispatcher = _Dispatcher()
        self._monitor = _Monitor()
        self._settings = ServerSettings(
            policy_profile="local-dev",
            approved_roots=[str(temporary_root)],
        )
        self._logger = logger
        self._graph = LiveSceneGraphCache(logger)
        self._graph_store = LiveGraphStore(logger, temporary_root / "graph.sqlite3")
        self._documents = LiveDocumentService(logger, self._graph_store)
        self._h5_failure_checkpoint = None

    def _document_schema_path(self) -> Path:
        return core_paths.package_root() / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_preview_live_catalog(self, _graph_spec_version=None):
        return self._catalog

    def _document_execute_apply_plan(self, plan, baseline, *, checkpoint=None):
        failure_at = self._h5_failure_checkpoint
        if failure_at is None:
            return super()._document_execute_apply_plan(
                plan, baseline, checkpoint=checkpoint
            )
        self._h5_failure_checkpoint = None
        count = 0

        def injected_checkpoint():
            nonlocal count
            if checkpoint is not None:
                checkpoint()
            count += 1
            if count == failure_at:
                raise RuntimeError(
                    f"injected H5E executor failure at checkpoint {failure_at}"
                )

        return super()._document_execute_apply_plan(
            plan, baseline, checkpoint=injected_checkpoint
        )

def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())

def _assert_installed_alignment() -> dict[str, Any]:
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            f"H5E requires Houdini 22.0.368, got {hou.applicationVersionString()}."
        )
    if (
        not (REPOSITORY_ROOT / ".git").exists()
        or not (REPOSITORY_ROOT / "python3.11libs").is_dir()
    ):
        raise RuntimeError(
            "Run H5E from the repository script, not from an installed copy."
        )
    configured_root = str(hou.getenv("HOCUSPOCUS_ROOT") or "").strip()
    if not configured_root:
        raise RuntimeError("HOCUSPOCUS_ROOT is absent from the installed package environment.")
    installed_root = Path(configured_root).resolve()
    if REPOSITORY_ROOT == installed_root or installed_root in REPOSITORY_ROOT.parents:
        raise RuntimeError("Repository and installed package roots must be distinct.")
    package_root = core_paths.package_root().resolve()
    if package_root != installed_root:
        raise RuntimeError(
            f"Installed package root mismatch: expected {installed_root}, got {package_root}."
        )
    records = {}
    for module_name in CRITICAL_MODULES:
        module = importlib.import_module(module_name)
        installed_path = Path(inspect.getfile(module)).resolve()
        try:
            relative_path = installed_path.relative_to(installed_root)
        except ValueError as exc:
            raise RuntimeError(
                f"{module_name} was not imported from the installed package: {installed_path}"
            ) from exc
        repository_path = REPOSITORY_ROOT / relative_path
        if not repository_path.is_file():
            raise RuntimeError(f"Repository counterpart is absent: {repository_path}")
        installed_hash = _sha256_file(installed_path)
        repository_hash = _sha256_file(repository_path)
        if installed_hash != repository_hash:
            raise RuntimeError(
                f"Installed module is stale: {module_name} "
                f"installed={installed_hash} repository={repository_hash}"
            )
        records[module_name] = {
            "relativePath": relative_path.as_posix(),
            "sha256": installed_hash,
        }
    return {
        "houdini": hou.applicationVersionString(),
        "installedRoot": str(installed_root),
        "modules": records,
    }


def _create_targets() -> None:
    parent = hou.node("/obj")
    if parent is None:
        raise RuntimeError("The /obj network is unavailable.")
    for path in ALL_TARGETS:
        if hou.node(path) is not None:
            raise RuntimeError(f"Refusing to reuse or delete existing smoke target {path}.")
        parent.createNode(
            "geo",
            node_name=path.rsplit("/", 1)[-1],
            run_init_scripts=False,
            load_contents=False,
        )

def _live_signature(root_path: str, *, root_cook_baseline: int = 0) -> str:
    root = hou.node(root_path)
    if root is None:
        raise RuntimeError(f"Missing live target {root_path}.")
    nodes = (root, *tuple(root.allSubChildren()))
    payload = []
    for node in nodes:
        cook_count = int(node.cookCount())
        expected_count = root_cook_baseline if node is root else 0
        COOK_OBSERVATIONS["nodeChecks"] += 1
        COOK_OBSERVATIONS["cookCount"] += abs(cook_count - expected_count)
        if cook_count != expected_count:
            raise RuntimeError(
                f"H5E observed {cook_count} cooks on {node.path()}; "
                f"expected {expected_count}."
            )
        payload.append({
            "path": node.path(),
            "type": node.type().name(),
            "inputs": [
                item.path() if item is not None else None
                for item in node.inputs()
            ],
            "flags": {
                "display": _optional_flag(node, "isDisplayFlagSet"),
                "render": _optional_flag(node, "isRenderFlagSet"),
                "bypass": _optional_flag(node, "isBypassed"),
                "template": _optional_flag(node, "isTemplateFlagSet"),
            },
            "userData": dict(node.userDataDict()),
        })
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _optional_flag(node, method_name: str) -> bool | None:
    method = getattr(node, method_name, None)
    return bool(method()) if callable(method) else None


def _preview_artifact(operations: _H5SmokeOperations, payload: dict[str, Any]) -> dict[str, Any]:
    artifact = payload.get("preview")
    if isinstance(artifact, dict):
        return artifact
    reference = payload.get("artifact") or {}
    stored = operations._documents.preview_artifact(str(reference.get("previewId", "")))
    if not isinstance(stored, dict):
        raise RuntimeError("Preview artifact was not returned inline or retained.")
    return stored


def _preview_twice(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    target_path: str,
    context: RequestContext,
) -> dict[str, Any]:
    before = _live_signature(target_path)
    _progress(f"preview-call:first:{target_path}")
    first = operations.document_preview_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    _progress(f"preview-call:second:{target_path}")
    second = operations.document_preview_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    _progress(f"preview-call:complete:{target_path}")
    if before != _live_signature(target_path):
        raise RuntimeError(f"Preview mutated Houdini state for {target_path}.")
    first_artifact = _preview_artifact(operations, first)
    second_artifact = _preview_artifact(operations, second)
    if (
        not first.get("valid")
        or not first.get("readyForPlan")
        or first_artifact["candidatePlan"]["planHash"]
        != second_artifact["candidatePlan"]["planHash"]
        or first_artifact["diff"] != second_artifact["diff"]
    ):
        raise RuntimeError(f"Preview was invalid or nondeterministic for {target_path}.")
    return first_artifact


def _catalog_drift_gate(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    target_path: str,
    temporary_root: Path,
    context: RequestContext,
) -> dict[str, str]:
    plan = _plan(operations, bundle, context)
    before = _live_signature(target_path)
    original = operations._catalog
    hda_path = temporary_root / "h5e_catalog_drift.hda"
    parent = hou.node("/obj")
    if parent is None:
        raise RuntimeError("The /obj network is unavailable.")
    source = parent.createNode(
        "subnet",
        node_name="h5e_catalog_drift_source",
        run_init_scripts=False,
    )
    asset = None
    try:
        asset = source.createDigitalAsset(
            name="h5e::catalog_drift::1.0",
            hda_file_name=str(hda_path),
            description="H5E disposable catalog drift",
            min_num_inputs=0,
            max_num_inputs=0,
        )
        drifted = LiveHoudiniCatalogProvider(hou).get_catalog()
        if drifted.fingerprint == original.fingerprint:
            raise RuntimeError("Disposable HDA did not change the live catalog fingerprint.")
        operations._catalog = drifted
        failure = _expect_error(
            "HOCUS752",
            lambda: operations.document_apply_plan(
                _apply_arguments(plan, "h5e-catalog-drift"), context
            ),
        )
    finally:
        operations._catalog = original
        if asset is not None:
            asset.destroy()
        elif source is not None:
            source.destroy()
        if hda_path.exists():
            hou.hda.uninstallFile(str(hda_path))
        operations.document_discard_plan(
            {"planId": plan["planId"], "planHash": plan["planHash"]}, context
        )
    restored = LiveHoudiniCatalogProvider(hou).get_catalog()
    details = failure.data or {}
    if (
        before != _live_signature(target_path)
        or restored.fingerprint != original.fingerprint
        or details.get("expectedCatalogFingerprint") != original.fingerprint
        or details.get("liveCatalogFingerprint") != drifted.fingerprint
    ):
        raise RuntimeError(
            "Catalog drift did not fail closed, report exact pins, and restore exactly."
        )
    return {
        "diagnosticCode": "HOCUS752",
        "expectedFingerprint": original.fingerprint,
        "liveFingerprint": drifted.fingerprint,
        "restoredFingerprint": restored.fingerprint,
    }


def _apply_arguments(plan: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "expectedDocumentRevision": plan["baseline"]["documentRevision"],
        "expectedLiveRevision": plan["baseline"]["liveRevision"],
        "confirmationToken": plan.get("confirmationToken"),
        "idempotencyKey": key,
    }


def _plan(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    result = operations.document_plan_bundle(
        {"bundle": bundle}, context
    )["structuredContent"]
    if not result.get("readyForApply"):
        raise RuntimeError(f"Bundle did not produce an immutable apply plan: {result!r}")
    return result


def _expect_error(code: str, callback) -> JsonRpcError:
    try:
        callback()
    except JsonRpcError as exc:
        if (exc.data or {}).get("diagnosticCode") != code:
            raise
        return exc
    raise RuntimeError(f"Expected {code}, but the operation succeeded.")


def _stale_plan_gate(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    target_path: str,
    context: RequestContext,
) -> str:
    plan = _plan(operations, bundle, context)
    root = hou.node(target_path)
    drift = root.createNode(
        "null", node_name="artist_stale_plan", run_init_scripts=False
    )
    operations._monitor.mark_dirty("h5e.stale", scope_path=target_path)
    before_apply = _live_signature(target_path)
    _expect_error(
        "HOCUS753",
        lambda: operations.document_apply_plan(
            _apply_arguments(plan, "h5e-stale-plan"), context
        ),
    )
    if before_apply != _live_signature(target_path):
        raise RuntimeError("Stale-plan rejection changed live Houdini state.")
    operations.document_discard_plan(
        {"planId": plan["planId"], "planHash": plan["planHash"]}, context
    )
    drift.destroy()
    operations._monitor.mark_dirty("h5e.stale.cleanup", scope_path=target_path)
    operations._document_current_network_payload(target_path, force_sync=True)
    return plan["planHash"]


def _rollback_gate(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any], target_path: str, context: RequestContext, *,
    root_cook_baseline: int = 0,
) -> dict[str, Any]:
    plan = _plan(operations, bundle, context)
    stored = operations._hocus_load_apply_plan(plan["planId"], plan["planHash"])
    checkpoint_count = apply_checkpoint_count(stored["executionPlan"])
    if checkpoint_count < 3:
        raise RuntimeError("H5E rollback plan has no meaningful mid-executor checkpoint.")
    failure_checkpoint = max(2, checkpoint_count // 2)
    before = _live_signature(target_path, root_cook_baseline=root_cook_baseline)
    operations._h5_failure_checkpoint = failure_checkpoint
    try:
        failure = _expect_error(
            "HOCUS755",
            lambda: operations.document_apply_plan(
                _apply_arguments(plan, f"h5e-injected-rollback-{plan['planId']}"), context
            ),
        )
    finally:
        operations._h5_failure_checkpoint = None
    details = (failure.data or {}).get("failure") or {}
    message = str(details.get("message", ""))
    checkpoint_observed = (
        f"checkpoint {failure_checkpoint}" in message
        or (
            "Editor entity mutation failed" in message
            and "HOCUS936" in message
        )
    )
    after = _live_signature(
        target_path, root_cook_baseline=root_cook_baseline
    )
    if (
        not details.get("rolledBack")
        or not checkpoint_observed
        or before != after
    ):
        raise RuntimeError(f"Injected apply failure did not restore {target_path}.")
    return {
        "planHash": plan["planHash"],
        "injectedCheckpoint": failure_checkpoint,
        "totalCheckpoints": checkpoint_count,
    }
def _apply_success(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    label: str,
    context: RequestContext,
) -> dict[str, Any]:
    plan = _plan(operations, bundle, context)
    arguments = _apply_arguments(plan, f"h5e-success-{label}")
    applied = operations.document_apply_plan(
        arguments, context
    )["structuredContent"]
    replay = operations.document_apply_plan(
        arguments, context
    )["structuredContent"]
    if (
        not applied.get("applied")
        or not applied.get("verified")
        or applied.get("idempotentReplay")
        or not replay.get("idempotentReplay")
    ):
        raise RuntimeError(f"Guarded apply/replay failed for {label}.")
    return {
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "applyCommitId": applied["applyCommitId"],
        "operationCount": len(applied["executedOperations"]),
    }


def _apply_distinct_update(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    prior_bundle: dict[str, Any],
    *,
    label: str,
    target_path: str,
    require_external: bool,
    context: RequestContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if bundle["bundleDigest"] == prior_bundle["bundleDigest"]:
        raise RuntimeError(f"{label} did not produce a distinct Bundle 0.4.")
    before = _live_signature(target_path)
    plan = _plan(operations, bundle, context)
    applied = operations.document_apply_plan(
        _apply_arguments(plan, f"h5e-distinct-{label}"),
        context,
    )["structuredContent"]
    after = _live_signature(target_path)
    if (
        not applied.get("applied")
        or not applied.get("verified")
        or applied.get("idempotentReplay")
        or before == after
    ):
        raise RuntimeError(f"{label} was not a new realized apply.")
    document = operations._document_current_network_payload(
        target_path, force_sync=True
    )
    _assert_portable_provenance(
        document,
        require_module=True,
        require_control=True,
        require_external=require_external,
    )
    return {
        "priorBundleDigest": prior_bundle["bundleDigest"],
        "bundleDigest": bundle["bundleDigest"],
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "applyCommitId": applied["applyCommitId"],
        "idempotentReplay": False,
    }, document


def _pending_target_recovery_gate(
    operations: _H5SmokeOperations,
    bundle: dict[str, Any],
    target_path: str,
    temporary_root: Path,
    context: RequestContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_response = _plan(operations, bundle, context)
    stored = operations._hocus_load_apply_plan(
        plan_response["planId"], plan_response["planHash"]
    )
    baseline = operations._document_current_network_payload(
        target_path, force_sync=True
    )
    idempotency_key = "h5e-pending-target-recovery"
    _, commit_id = operations._hocus_reserve_apply_commit(
        stored, baseline, idempotency_key
    )
    with hou.undos.group(f"H5E pending recovery {plan_response['planId']}"):
        operations._document_execute_apply_plan(
            stored["executionPlan"],
            baseline,
            checkpoint=context.raise_if_cancelled,
        )
    operations._monitor.mark_dirty("h5e.pending-recovery", scope_path=target_path)
    realized = operations._document_current_network_payload(
        target_path, force_sync=True
    )
    verification = operations._document_verification_diff_payload(
        stored["targetDocument"], realized
    )
    if not operations._document_diff_is_clean(verification):
        raise RuntimeError("Pending recovery fixture did not realize its target.")
    reopened = _H5SmokeOperations(operations._catalog, temporary_root)
    recovery = reopened.document_recover_scope(
        {"rootPath": target_path}, context
    )["structuredContent"]
    recovered = next(
        (
            item
            for item in recovery["recoveredCommits"]
            if item["applyCommitId"] == commit_id
        ),
        None,
    )
    before_replay = _live_signature(target_path)
    replay = reopened.document_apply_plan(
        _apply_arguments(plan_response, idempotency_key),
        context,
    )["structuredContent"]
    if (
        not isinstance(recovered, dict)
        or recovered.get("state") != "committed"
        or not replay.get("applied")
        or not replay.get("verified")
        or not replay.get("recovered")
        or not replay.get("idempotentReplay")
        or replay.get("applyCommitId") != commit_id
        or before_replay != _live_signature(target_path)
    ):
        raise RuntimeError("Recovered pending commit did not replay durably.")
    return {
        "planId": plan_response["planId"],
        "planHash": plan_response["planHash"],
        "applyCommitId": commit_id,
        "classification": recovered["classification"],
        "idempotentReplay": True,
        "storeReopened": True,
    }, stored


def _assert_portable_provenance(
    document: dict[str, Any],
    *,
    require_module: bool,
    require_control: bool,
    require_external: bool,
) -> None:
    rendered = json.dumps(document, ensure_ascii=False, sort_keys=True)
    if str(Path(tempfile.gettempdir()).resolve()) in rendered:
        raise RuntimeError("A force-synced document leaked a temporary native path.")
    expansion = (document.get("metadata") or {}).get("hocusExpansion")
    if not isinstance(expansion, dict):
        raise RuntimeError("Force-synced document lost H5 expansion provenance.")
    module_stacks = expansion.get("moduleStacks") or []
    control_stacks = expansion.get("controlStacks") or []
    if require_module and not module_stacks:
        raise RuntimeError("Force-synced document lost module expansion stacks.")
    if require_control and not control_stacks:
        raise RuntimeError("Force-synced document lost control expansion stacks.")
    module_ids = {item["stackId"] for item in module_stacks}
    control_ids = {item["controlStackId"] for item in control_stacks}
    generated = [
        node for node in document["nodes"]
        if node["path"] != document["rootPath"]
    ]
    if not generated:
        raise RuntimeError("Applied document contains no generated nodes.")
    for node in generated:
        hocus = (node.get("metadata") or {}).get("hocus")
        if not isinstance(hocus, dict):
            raise RuntimeError(f"Generated node lost provenance: {node['uid']}")
        if not str(hocus.get("sourceUri", "")).startswith(
            ("hocus-project://", "hocus-module://")
        ):
            raise RuntimeError(f"Generated node has a nonportable source URI: {hocus!r}")
        if require_control and not str(hocus.get("originId", "")).startswith("sha256:"):
            raise RuntimeError(f"Generated control node lost its origin: {hocus!r}")
    envelopes = _provenance_envelopes(document)
    _assert_expansion_refs(envelopes, module_ids, control_ids)
    if require_external and not any(
        str(hocus.get("sourceUri", "")).startswith(
            "hocus-module://h5e-control-library/"
        )
        for hocus in envelopes
    ):
        raise RuntimeError("Mixed-project provenance lost its external module URI.")


def _provenance_envelopes(document: dict[str, Any]) -> list[dict[str, Any]]:
    envelopes = []
    for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs"):
        for item in document.get(field, []):
            hocus = (item.get("metadata") or {}).get("hocus")
            if isinstance(hocus, dict):
                envelopes.append(hocus)
    return envelopes


def _assert_expansion_refs(
    envelopes: list[dict[str, Any]],
    module_ids: set[str],
    control_ids: set[str],
) -> None:
    for hocus in envelopes:
        if hocus.get("stackId") not in (None, *module_ids):
            raise RuntimeError(f"Entity references an unknown module stack: {hocus!r}")
        if hocus.get("controlStackId") not in (None, *control_ids):
            raise RuntimeError(f"Entity references an unknown control stack: {hocus!r}")


def _expansion_reference_signature(document: dict[str, Any]) -> list[tuple[Any, ...]]:
    return sorted(
        [
            (
            hocus.get("sourceUri"),
            hocus.get("originId"),
            hocus.get("stackId"),
            hocus.get("controlStackId"),
            )
            for hocus in _provenance_envelopes(document)
        ],
        key=repr,
    )


def _document_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "rootPath": document["rootPath"],
        "nodes": sorted(
            (
                node["uid"],
                node["name"],
                node["typeName"],
                node["category"],
                node["flags"]["display"],
                node["flags"]["render"],
                copy.deepcopy((node.get("metadata") or {}).get("hocus")),
            )
            for node in document["nodes"]
        ),
        "edges": sorted(
            (
                edge["uid"],
                edge["kind"],
                copy.deepcopy(edge["from"]),
                copy.deepcopy(edge["to"]),
                copy.deepcopy((edge.get("metadata") or {}).get("hocus")),
            )
            for edge in document["edges"]
        ),
        "nonNodeProvenance": {
            field: sorted(
                (
                    item["uid"],
                    copy.deepcopy((item.get("metadata") or {}).get("hocus")),
                )
                for item in document[field]
            )
            for field in ("ports", "parameterBindings", "codeBlobs")
        },
        "hocusExpansion": copy.deepcopy(
            (document.get("metadata") or {}).get("hocusExpansion")
        ),
    }


def _save_reload(
    operations: _H5SmokeOperations,
    hip_path: Path,
    documents: dict[str, dict[str, Any]],
    context: RequestContext,
) -> dict[str, dict[str, Any]]:
    operations.scene_save_hip(
        {"path": str(hip_path), "save_to_recent_files": False}, context
    )
    operations.scene_new({}, context)
    operations._monitor.mark_dirty("h5e.scene.new")
    if any(hou.node(path) is not None for path in ALL_TARGETS):
        raise RuntimeError("Disposable H5E targets survived scene.new.")
    operations.scene_open_hip(
        {
            "path": str(hip_path),
            "suppress_save_prompt": True,
            "ignore_load_warnings": False,
        },
        context,
    )
    operations._monitor.mark_dirty("h5e.scene.reload")
    reloaded = {}
    for label, path in TARGETS.items():
        document = operations._document_current_network_payload(
            path, force_sync=True
        )
        if _document_projection(document) != _document_projection(documents[label]):
            raise RuntimeError(f"Save/reload changed document semantics or provenance: {label}")
        reloaded[label] = document
    return reloaded


def _clean_baseline(document: dict[str, Any]) -> dict[str, Any]:
    root = next(
        node for node in document["nodes"]
        if node["path"] == document["rootPath"]
    )
    return {
        "$schema": document["$schema"],
        "kind": "network_document",
        "documentId": document["documentId"],
        "documentRevision": document["documentRevision"],
        "baselineLiveRevision": document["baselineLiveRevision"],
        "lastSyncedLiveRevision": document["lastSyncedLiveRevision"],
        "rootPath": document["rootPath"],
        "category": document["category"],
        "metadata": {},
        "nodes": [copy.deepcopy(root)],
        "ports": [],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


def _endpoint(value: dict[str, Any]) -> tuple[Any, ...]:
    return value.get("nodeUid"), value.get("portIndex")


def _semantic_projection(document: dict[str, Any]) -> dict[str, Any]:
    nodes = [
        node for node in document["nodes"]
        if node["path"] != document["rootPath"]
    ]
    return {
        "nodes": sorted(
            (
                node["uid"],
                node["name"],
                node["typeName"],
                node["category"],
                bool(node["flags"]["display"]),
                bool(node["flags"]["render"]),
            )
            for node in nodes
        ),
        "edges": sorted(
            (
                edge["kind"],
                _endpoint(edge["from"]),
                _endpoint(edge["to"]),
            )
            for edge in document["edges"]
            if edge["kind"] in {"data", "output_flag"}
        ),
    }


def _flat_export_bundle(source: str, source_uri: str, project_uid: str, catalog):
    compiled = compile_source(source, "exported.hocus", source_uri=source_uri)
    if not compiled.valid or compiled.graph_spec is None:
        raise RuntimeError(
            f"Flat export did not compile: {compiled.to_dict()['diagnostics']}"
        )
    semantic = resolve_graph(compiled.graph_spec, catalog)
    if not semantic.valid or not semantic.ready_for_document_lowering:
        raise RuntimeError(f"Flat export failed semantic resolution: {semantic.to_dict()!r}")
    compiled.semantic_result = semantic
    compiled.source_kind = "project_file"
    compiled.project_uid = project_uid
    compiled.project_manifest_digest = _sha256_bytes(f"{project_uid}:manifest".encode())
    compiled.project_lock_digest = _sha256_bytes(f"{project_uid}:lock".encode())
    compiled.catalog_fingerprint = catalog.fingerprint
    compiled.catalog_content_digest = _sha256_bytes(catalog.to_json().encode())
    return CompiledBundle.from_result(compiled)


def _export_recompile(
    operations: _H5SmokeOperations,
    label: str,
    document: dict[str, Any],
    catalog,
    context: RequestContext,
) -> dict[str, Any]:
    exported = operations.document_export_source(
        {"root_path": document["rootPath"], "graph_name": f"h5e_{label}"},
        context,
    )["structuredContent"]
    source = exported.get("source")
    if not exported.get("valid") or not isinstance(source, str):
        raise RuntimeError(f"Flat export failed for {label}: {exported.get('diagnostics')}")
    is_v2 = document.get("$schema") == (
        "hocuspocus://schemas/network-document/v2"
    )
    expected_language = "0.4" if is_v2 else "0.1"
    if (
        not source.startswith(f"hocus {expected_language};")
        or "\nimport " in source
        or "\nif " in source
        or "\nfor " in source
    ):
        raise RuntimeError("Export claimed or retained authored module/control structure.")
    bundle = _flat_export_bundle(
        source,
        f"hocus-project://h5e-flat-{label.replace('_', '-')}/exported.hocus",
        f"h5e-flat-{label.replace('_', '-')}",
        catalog,
    )
    lowered = lower_bundle_to_document(bundle, _clean_baseline(document))
    if not lowered.valid or lowered.candidate_plan is None:
        raise RuntimeError(f"Flat export did not lower for {label}: {lowered.to_dict()!r}")
    expected = _semantic_projection(document)
    actual = _semantic_projection(lowered.document)
    if expected != actual:
        raise RuntimeError(
            "Flat export/recompile semantic projection changed: "
            + json.dumps({"expected": expected, "actual": actual}, sort_keys=True)
        )
    return {
        "sourceDigest": exported["provenance"]["sourceDigest"],
        "nodeCount": len(expected["nodes"]),
        "edgeCount": len(expected["edges"]),
        "normalizedLanguageVersion": expected_language,
        "reconstructedAuthoredStructure": False,
    }

def _read_schema_resources(context: RequestContext) -> dict[str, str]:
    tools, resources = ToolRegistry(), ResourceRegistry()
    LiveOperations.__new__(LiveOperations).register(tools, resources)
    result = {}
    for uri, schema_id in SCHEMA_RESOURCES.items():
        definition = resources.get(uri)
        if (
            definition is None
            or not definition.payload_summary
            or not definition.examples
        ):
            raise RuntimeError(f"Installed schema resource is not fully registered: {uri}")
        content = definition.reader(context)["contents"][0]
        payload = json.loads(content["text"])
        if content["uri"] != uri or payload.get("$id") != schema_id:
            raise RuntimeError(f"Installed schema resource mismatch: {uri}")
        result[uri] = schema_id
    return result


def _assert_disposable_scene() -> None:
    if Path(hou.hipFile.path()).name.casefold() != "untitled.hip":
        raise RuntimeError("H5E requires a cleared disposable hython scene.")
    if any(hou.node(path) is not None for path in ALL_TARGETS):
        raise RuntimeError("H5E target names already exist in the current scene.")


def _run_installed_h5e(temporary_root: Path) -> dict[str, Any]:
    _progress("alignment")
    alignment = _assert_installed_alignment()
    _assert_disposable_scene()
    _progress("catalog")
    catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
    _progress("compile-bundles")
    bundles, variants = build_acceptance_bundles(
        temporary_root / "projects",
        catalog,
        TARGETS,
        rollback_target=ROLLBACK_TARGET,
        recovery_target=RECOVERY_TARGET,
    )
    _progress("create-targets")
    _create_targets()
    operations = _H5SmokeOperations(catalog, temporary_root)
    for label, target_path in TARGETS.items():
        operations._document_stamp_live_node_uid(
            target_path, f"node:h5e-root:{label}"
        )
    operations._document_stamp_live_node_uid(
        ROLLBACK_TARGET, "node:h5e-root:control_rollback_v04"
    )
    operations._document_stamp_live_node_uid(
        RECOVERY_TARGET, "node:h5e-root:control_recovery_v04"
    )
    operations._monitor.mark_dirty("h5e.targets.created")
    context = RequestContext(
        caller_id="h5e-installed-smoke",
        permissions=("observe", "edit_scene", "write_files"),
        timeout_seconds=300.0,
    )
    resources = _read_schema_resources(context)

    previews = {}
    for label, bundle in bundles.items():
        _progress(f"preview:{label}")
        previews[label] = _preview_twice(
            operations, bundle, TARGETS[label], context
        )["candidatePlan"]["planHash"]
    _progress("catalog-drift")
    catalog_drift = _catalog_drift_gate(
        operations,
        bundles["control_local_v04"],
        TARGETS["control_local_v04"],
        temporary_root,
        context,
    )

    _progress("rollback")
    rollback_plan = _rollback_gate(
        operations,
        variants["rollback"],
        ROLLBACK_TARGET,
        context,
    )

    applies = {}
    documents = {}
    for label, bundle in bundles.items():
        _progress(f"apply:{label}")
        applies[label] = _apply_success(operations, bundle, label, context)
        document = operations._document_current_network_payload(
            TARGETS[label], force_sync=True
        )
        _assert_portable_provenance(
            document,
            require_module=True,
            require_control=label != "module_v03",
            require_external=label == "control_mixed_v04",
        )
        documents[label] = document

    updates = {}
    _progress("second-merge")
    updates["secondMerge"], documents["control_local_v04"] = (
        _apply_distinct_update(
            operations,
            variants["second_merge"],
            bundles["control_local_v04"],
            label="second-merge",
            target_path=TARGETS["control_local_v04"],
            require_external=False,
            context=context,
        )
    )
    _progress("second-reconcile")
    updates["secondReconcile"], documents["control_mixed_v04"] = (
        _apply_distinct_update(
            operations,
            variants["second_reconcile"],
            bundles["control_mixed_v04"],
            label="second-reconcile",
            target_path=TARGETS["control_mixed_v04"],
            require_external=True,
            context=context,
        )
    )
    _progress("recovery")
    recovery, recovery_plan = _pending_target_recovery_gate(
        operations,
        variants["recovery"],
        RECOVERY_TARGET,
        temporary_root,
        context,
    )
    expansion_refs = {
        label: _expansion_reference_signature(document)
        for label, document in documents.items()
    }
    _progress("stale-plan")
    stale_plan = _stale_plan_gate(
        operations,
        bundles["control_local_v04"],
        TARGETS["control_local_v04"],
        context,
    )
    hip_path = temporary_root / "h5e-installed-acceptance.hip"
    _progress("save-reload")
    reloaded = _save_reload(operations, hip_path, documents, context)
    for label, document in reloaded.items():
        _assert_portable_provenance(
            document,
            require_module=True,
            require_control=label != "module_v03",
            require_external=label == "control_mixed_v04",
        )
        if _expansion_reference_signature(document) != expansion_refs[label]:
            raise RuntimeError(f"Save/reopen changed expansion references: {label}")
    _progress("export")
    exports = {
        label: _export_recompile(
            operations, label, document, catalog, context
        )
        for label, document in reloaded.items()
    }
    _progress("pruning")
    pruning = durable_pruning_gate(
        operations,
        recovery_plan,
        temporary_root,
    )
    for target_path in TARGETS.values():
        _live_signature(target_path)
    return {
        "status": "passed",
        "alignment": alignment,
        "catalog": {
            "fingerprint": catalog.fingerprint,
            "operatorCount": len(catalog.operators),
        },
        "resources": resources,
        "bundleVersions": {
            label: bundle["bundleVersion"] for label, bundle in bundles.items()
        },
        "applyModes": {
            label: bundle["graphSpec"]["mode"] for label, bundle in bundles.items()
        },
        "previewPlanHashes": previews,
        "catalogDriftRejected": catalog_drift,
        "stalePlanRejected": {"diagnosticCode": "HOCUS753", "planHash": stale_plan},
        "rollback": {
            "diagnosticCode": "HOCUS755",
            **rollback_plan,
            "rolledBack": True,
        },
        "applies": applies,
        "distinctUpdates": updates,
        "pendingTargetRecovery": recovery,
        "durablePruning": pruning,
        "saveReload": {
            "hipPath": str(hip_path),
            "verifiedTargets": sorted(TARGETS.values()),
            "provenanceRetained": True,
            "expansionReferenceCounts": {
                label: len(references)
                for label, references in expansion_refs.items()
            },
        },
        "exports": exports,
        "cookExecuted": COOK_OBSERVATIONS["cookCount"] != 0,
        "cookObservationCount": COOK_OBSERVATIONS["nodeChecks"],
    }


def main() -> int:
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            f"H5E requires Houdini 22.0.368, got {hou.applicationVersionString()}."
        )
    logging.basicConfig(level=logging.INFO)
    temporary = tempfile.TemporaryDirectory(prefix="hocuspocus-h5e-")
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        result = _run_installed_h5e(Path(temporary.name).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        try:
            hou.hipFile.clear(suppress_save_prompt=True)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
