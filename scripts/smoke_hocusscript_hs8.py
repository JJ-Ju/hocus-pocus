"""Installed Houdini acceptance for the HS8 production rock-family slice.

This mutates only a disposable untitled scene and a temporary output directory.
HocusScript apply must remain zero-cook; the harness then explicitly authorizes
the SOP and LOP fixture outputs to cook before read-only production observation.

Usage:
    "C:\\Program Files\\Side Effects Software\\Houdini 22.0.368\\bin\\hython.exe" ^
        scripts\\smoke_hocusscript_hs8.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hou  # type: ignore

from hocuspocus.core import paths as core_paths
from hocuspocus.hocusscript.asset_contract_validation import validate_asset_contract
from hocuspocus.hocusscript.build_comparison import (
    VisualComparison,
    compare_visual_baseline,
)
from hocuspocus.hocusscript.build_metrics import BuildMetrics, PlatformBudget
from hocuspocus.hocusscript.build_provenance import canonical_digest
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.package_search_provenance import (
    collect_effective_package_search,
    verify_effective_package_search,
)
from hocuspocus.live.ops.production import ProductionOperationsMixin
from hocuspocus.live.ops.validation import ValidationOperationsMixin
from hocuspocus.live.ops.viewport import ViewportOperationsMixin
from hocuspocus.live.production_observation import ProductionFixtureObserver
from hocuspocus.live.production_usd_observation import (
    observe_production_usda,
    project_asset_contract_observation,
)
from smoke_hocusscript_h5 import _H5SmokeOperations
from smoke_hocusscript_hs7_acceptance_support import (
    compile_value_bundle,
    preview_plan_apply,
    projection_differences,
    save_reopen,
)
from smoke_hocusscript_hs8_support import (
    MATERIAL,
    MATERIAL_SOURCE,
    FIXTURE_FILES,
    FIXTURE_ROOT,
    ROCK_SOURCE,
    ROCK_RECONCILE_SOURCE,
    SOP_OUTPUT,
    SOP_ROOT,
    USD_OUTPUT,
    USD_SOURCE,
    add_artist_override,
    artist_override,
    comparison_projection,
    build_manifest,
    cook_fixture,
    export_usd,
    fixture_contract,
    process_peak_working_set_bytes,
    render_contact_sheet,
    write_report,
)
from hs8_install_manifest import audit_loaded_modules, verify_manifest
from hs8_output_guard import (
    OutputGuardError,
    copy_exclusive,
    copy_exclusive_or_identical,
)

MAX_DIAGNOSTIC_USD_BYTES = 64 * 1024 * 1024


PAYLOAD_ROOT = Path(__file__).resolve().parents[1]


class _HS8Operations(
    ProductionOperationsMixin,
    ViewportOperationsMixin,
    ValidationOperationsMixin,
    _H5SmokeOperations,
):
    pass


def _progress(stage: str) -> None:
    print(f"HS8_STAGE {stage}", file=sys.stderr, flush=True)


def _digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _installed_alignment(
    provider: LiveHoudiniCatalogProvider,
    catalog: Any,
) -> dict[str, Any]:
    configured = str(hou.getenv("HOCUSPOCUS_ROOT") or "").strip()
    if not configured:
        raise RuntimeError("HOCUSPOCUS_ROOT is absent from the Houdini package environment.")
    installed_root = Path(configured).resolve()
    if PAYLOAD_ROOT != installed_root:
        raise RuntimeError("HS8 harness is not running from the installed payload.")
    if core_paths.package_root().resolve() != installed_root:
        raise RuntimeError("HocusPocus runtime package root does not match HOCUSPOCUS_ROOT.")
    manifest = verify_manifest(installed_root)
    selected = {
        name: module
        for name, module in sys.modules.items()
        if (
            module is not None
            and (
                name == "hocuspocus"
                or name.startswith("hocuspocus.")
                or name.startswith("smoke_hocusscript_")
                or name == "hs8_install_manifest"
                or name == "hs8_output_guard"
            )
        )
    }
    receipts = audit_loaded_modules(installed_root, selected, manifest)
    package_search = collect_effective_package_search(
        hou,
        provider,
        catalog,
        installed_root=installed_root,
        install_manifest=manifest,
    )
    verify_effective_package_search(
        package_search,
        hou,
        provider,
        catalog,
        installed_root=installed_root,
        install_manifest=manifest,
    )
    fixture_receipts = []
    for name, filename in sorted(FIXTURE_FILES.items()):
        installed_path = (FIXTURE_ROOT / filename).resolve()
        installed_digest = _digest_file(installed_path)
        fixture_receipts.append({
            "name": name,
            "relativePath": f"scripts/fixtures/hs8/{filename}",
            "digest": installed_digest,
        })
    return {
        "houdiniVersion": hou.applicationVersionString(),
        "installedRoot": str(installed_root),
        "installManifestDigest": manifest["manifestDigest"],
        "packageSearch": package_search,
        "modules": receipts,
        "fixtures": fixture_receipts,
    }


def _prepare_roots(operations: Any) -> None:
    if hou.node(SOP_ROOT) is not None:
        raise RuntimeError(f"Refusing to reuse HS8 fixture root {SOP_ROOT}.")
    obj = hou.node("/obj")
    if obj is None:
        raise RuntimeError("Houdini /obj root is unavailable.")
    root = obj.createNode(
        "geo", SOP_ROOT.rsplit("/", 1)[-1],
        run_init_scripts=False, load_contents=False,
    )
    operations._document_stamp_live_node_uid(root.path(), "node:hs8:root:sop")
    operations._document_stamp_live_node_uid("/mat", "node:hs8:root:mat")
    operations._document_stamp_live_node_uid("/stage", "node:hs8:root:lop")
    operations._monitor.mark_dirty("hs8.roots.created")


def _apply_sources(
    operations: Any,
    catalog: Any,
    context: RequestContext,
    *,
    apply_scope: str,
) -> dict[str, Any]:
    result = {}
    for label, source in (
        ("material", MATERIAL_SOURCE),
        ("rock-family", ROCK_SOURCE),
        ("usd", USD_SOURCE),
    ):
        bundle = compile_value_bundle(source, label=f"hs8-{label}", catalog=catalog)
        receipt, _candidate = preview_plan_apply(
            operations, bundle, label=f"hs8-{apply_scope}-{label}", context=context,
        )
        result[label] = {
            **receipt,
            "bundleDigest": bundle["bundleDigest"],
        }
    return result


def _observer() -> ProductionFixtureObserver:
    return ProductionFixtureObserver(
        hou,
        authorized_roots=(SOP_ROOT, MATERIAL, USD_OUTPUT),
    )


def _reconcile_rock(
    operations: Any,
    catalog: Any,
    context: RequestContext,
    *,
    apply_scope: str,
) -> dict[str, Any]:
    bundle = compile_value_bundle(
        ROCK_RECONCILE_SOURCE,
        label="hs8-rock-family-reconcile",
        catalog=catalog,
    )
    receipt, _candidate = preview_plan_apply(
        operations,
        bundle,
        label=f"hs8-{apply_scope}-rock-family-reconcile",
        context=context,
    )
    return {**receipt, "bundleDigest": bundle["bundleDigest"]}


def _observe(observer: ProductionFixtureObserver) -> dict[str, Any]:
    return observer.observe(
        asset_id="hs8-rock-family",
        geometry_paths=(SOP_ROOT + "/family_prototype",),
        usd_paths=(USD_OUTPUT,),
    )


def _observe_export(
    observer: ProductionFixtureObserver,
    usd_path: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    observation = _observe(observer)
    final_usd = observe_production_usda(usd_path, contract=contract)
    observation["finalUsd"] = final_usd
    observation["assetContractObservation"] = project_asset_contract_observation(
        observation["assetContractObservation"],
        final_usd,
    )
    return observation


def _visual_evidence(
    operations: Any,
    root: Path,
    context: RequestContext,
) -> dict[str, Any]:
    camera = operations.scene_create_turntable_camera(
        {
            "target_path": SOP_ROOT,
            "frame_range": [1, 48],
            "camera_name": "hs8_turntable",
            "distance_multiplier": 2.2,
            "activate_viewport_camera": hou.isUIAvailable(),
        },
        context,
    )["structuredContent"]
    contact_sheet = render_contact_sheet(root / "hs8-contact-sheet.png")
    if not hou.isUIAvailable():
        return {
            "turntableCamera": camera,
            "viewportCapture": {"supported": False, "mode": "headless"},
            "contactSheet": contact_sheet,
        }
    captures = []
    for frame in (1, 13, 25, 37):
        hou.setFrame(frame)
        path = root / f"turntable_{frame:04d}.png"
        capture = operations.viewport_capture(
            {"path": str(path)}, context,
        )["structuredContent"]
        captures.append({
            "frame": frame,
            "name": path.name,
            "digest": _digest_file(path),
            "viewport": capture["viewport"],
        })
    return {
        "turntableCamera": camera,
        "viewportCapture": {"supported": True, "frames": captures},
        "contactSheet": contact_sheet,
    }


def _validate_product(observation: dict[str, Any]) -> None:
    final_usd = observation["finalUsd"]
    if final_usd["defaultPrim"] != "/World":
        raise RuntimeError("HS8 final USD did not author /World as defaultPrim.")
    if final_usd["publishArc"] != "inline":
        raise RuntimeError("HS8 flattened publish root is not self-contained.")
    if final_usd["materialSlots"] != ["hs8_rock_material"]:
        raise RuntimeError(
            f"HS8 final material binding drifted: {final_usd['materialSlots']!r}"
        )
    binding_roles = {
        (item["role"], item["name"])
        for item in final_usd["primBindings"]
    }
    if binding_roles != {
        ("render", "lod0"),
        ("render", "lod1"),
        ("collision", "collision"),
    }:
        raise RuntimeError(
            f"HS8 final USD delivery prims are incomplete: {binding_roles!r}"
        )
    if final_usd["instancing"]["instanceCount"] != 3:
        raise RuntimeError(
            f"HS8 final USD is not a three-instance family: {final_usd['instancing']!r}"
        )


def _validate_contract_observation(
    contract: dict[str, Any],
    observation: dict[str, Any],
) -> Any:
    facts = observation["assetContractObservation"]
    if facts["dependencies"] != contract["dependencies"]:
        raise RuntimeError(
            "HS8 observed dependencies do not match the predeclared contract: "
            f"{facts['dependencies']!r}"
        )
    report = validate_asset_contract(contract, facts)
    if not report.valid:
        raise RuntimeError(
            f"HS8 strict asset contract failed: {report.to_dict()!r}"
        )
    return report


@dataclass(frozen=True, slots=True)
class _QualificationInputs:
    contract: dict[str, Any]
    rebuilt: dict[str, Any]
    baseline_provenance: Any
    candidate_provenance: Any
    metrics: BuildMetrics
    budget: PlatformBudget
    numeric_baseline: dict[str, int | float]
    numeric_candidate: dict[str, int | float]
    numeric_tolerances: dict[str, int | float]
    rebuilt_visual: dict[str, Any]
    artist_before: dict[str, Any]
    artist_after_reconcile: dict[str, Any]


def _bootstrap_baseline_if_requested(
    source: Path,
) -> None:
    if os.environ.get("HOCUSPOCUS_HS8_BOOTSTRAP_BASELINE") == "1":
        target_root = _review_fixture_root()
        target = target_root / "baseline-contact-sheet.png"
        try:
            copy_exclusive(
                source, target, max_bytes=MAX_DIAGNOSTIC_USD_BYTES,
            )
        except OutputGuardError as exc:
            raise RuntimeError(
                f"HS8 bootstrap baseline publication failed: {exc}"
            ) from exc


def _preserve_usd_diagnostics(
    first: Path,
    rebuilt: Path,
) -> None:
    configured = os.environ.get(
        "HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", "",
    )
    if not configured:
        return
    if _qualification_mode() != "technical":
        raise RuntimeError("HS8 diagnostic output is technical-mode only.")
    root = Path(configured).resolve()
    if not root.is_dir():
        raise RuntimeError("HS8 diagnostic output root is not a directory.")
    for name, source in (
        ("first-rock-family.usda", first),
        ("rebuilt-rock-family.usda", rebuilt),
    ):
        source = source.resolve()
        if not source.is_file():
            raise RuntimeError("HS8 diagnostic USDA source is missing.")
        if source.stat().st_size > MAX_DIAGNOSTIC_USD_BYTES:
            raise RuntimeError("HS8 diagnostic USDA exceeds its byte limit.")
        target = (root / name).resolve()
        if target.parent != root:
            raise RuntimeError("HS8 diagnostic USDA target escapes its root.")
        try:
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
        except FileExistsError as exc:
            raise RuntimeError(
                "HS8 diagnostic USDA target already exists."
            ) from exc


def _preserve_failed_usd_diagnostics(operation_root: Path) -> None:
    configured = os.environ.get(
        "HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", "",
    )
    if not configured:
        return
    root = Path(configured).resolve()
    if not root.is_dir():
        raise RuntimeError("HS8 diagnostic output root is not a directory.")
    for source_name, target_name in (
        ("hs8-rock-family.usda", "first-rock-family.usda"),
        ("hs8-rock-family-reopened.usda", "reopened-rock-family.usda"),
        ("hs8-rock-family-rebuilt.usda", "rebuilt-rock-family.usda"),
    ):
        source = operation_root / source_name
        if not source.is_file():
            continue
        try:
            copy_exclusive_or_identical(
                source,
                root / target_name,
                max_bytes=MAX_DIAGNOSTIC_USD_BYTES,
            )
        except OutputGuardError as exc:
            raise RuntimeError(
                f"HS8 failure USDA preservation failed: {exc}",
            ) from exc


def _record_failure_evidence_diagnostic(error: BaseException) -> dict[str, Any]:
    diagnostic = {
        "kind": "hocus_hs8_failure_evidence_diagnostic",
        "code": "HS8_DIAGNOSTIC_PRESERVATION_FAILED",
        "errorType": type(error).__name__,
        "retained": False,
    }
    configured = os.environ.get(
        "HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", "",
    )
    if not configured:
        return diagnostic
    try:
        root = Path(configured).resolve()
        if not root.is_dir():
            return diagnostic
        target = (root / "failure-evidence-diagnostic.json").resolve()
        if target.parent != root:
            return diagnostic
        payload = json.dumps(
            {key: value for key, value in diagnostic.items() if key != "retained"},
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ).encode("ascii") + b"\n"
        if target.is_file() and not target.is_symlink():
            if target.read_bytes() == payload:
                diagnostic["retained"] = True
                return diagnostic
            return diagnostic
        with target.open("xb") as handle:
            handle.write(payload)
        diagnostic["retained"] = True
    except (OSError, ValueError):
        pass
    return diagnostic


def _review_fixture_root() -> Path:
    if os.environ.get("HOCUSPOCUS_HS8_BOOTSTRAP_BASELINE") != "1":
        return FIXTURE_ROOT
    configured = os.environ.get("HOCUSPOCUS_HS8_BOOTSTRAP_OUTPUT_ROOT", "")
    if not configured:
        raise RuntimeError("HS8 bootstrap output root is not configured.")
    root = Path(configured).resolve()
    if not root.is_dir():
        raise RuntimeError("HS8 bootstrap output root is not a directory.")
    return root


def _qualification_mode() -> str:
    mode = os.environ.get("HOCUSPOCUS_HS8_QUALIFICATION_MODE", "technical")
    if mode not in {"technical", "release"}:
        raise RuntimeError("HS8 qualification mode is invalid.")
    return mode


def _detached_visual_review(mode: str) -> dict[str, Any] | None:
    content = os.environ.get("HOCUSPOCUS_HS8_VISUAL_REVIEW_CONTENT")
    digest = os.environ.get("HOCUSPOCUS_HS8_VISUAL_REVIEW_DIGEST")
    if mode == "technical":
        if content is not None or digest is not None:
            raise RuntimeError("HS8 technical mode rejects visual approval.")
        return None
    if content is None or digest is None:
        raise RuntimeError("HS8 release requires detached visual approval.")
    if len(content.encode("utf-8")) > 16 * 1024:
        raise RuntimeError("HS8 detached visual approval is unbounded.")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("HS8 detached visual approval is invalid JSON.") from exc
    if not isinstance(payload, dict) or canonical_digest(payload) != digest:
        raise RuntimeError("HS8 detached visual approval digest is invalid.")
    return payload


def _attested_qualification(
    operations: Any,
    context: RequestContext,
    inputs: _QualificationInputs,
) -> dict[str, Any]:
    artist_before_digest = canonical_digest(inputs.artist_before)
    artist_after_digest = canonical_digest(inputs.artist_after_reconcile)
    qualification_mode = _qualification_mode()
    review_root = _review_fixture_root()
    baseline_path = review_root / "baseline-contact-sheet.png"
    candidate_digest = inputs.rebuilt_visual["digest"]
    if qualification_mode == "release":
        if not baseline_path.is_file():
            raise RuntimeError("HS8 visual baseline is missing.")
        baseline_digest = _digest_file(baseline_path)
    else:
        baseline_digest = candidate_digest
    visual_comparison = VisualComparison(
        output_uri="hocus-output://hs8.fixture/contact-sheet.png",
        baseline_digest=baseline_digest,
        candidate_digest=candidate_digest,
        algorithm="exact-png-sha256",
        difference=0.0 if baseline_digest == candidate_digest else 1.0,
        maximum_difference=0.0,
    )
    artist_evidence = {
        "kind": "artist_override_evidence",
        "protectedRegionCount": 2,
        "beforeDigest": artist_before_digest,
        "afterDigest": artist_after_digest,
        "passed": artist_before_digest == artist_after_digest,
    }
    review_bindings = {
        "assetUri": inputs.candidate_provenance.to_dict()["assetUri"],
        "candidateProvenanceManifestDigest": inputs.candidate_provenance.manifest_digest,
        "candidateOutputSetDigest": inputs.candidate_provenance.output_set_digest,
        "visualComparisonDigest": canonical_digest(
            compare_visual_baseline((visual_comparison,)),
        ),
    }
    if os.environ.get("HOCUSPOCUS_HS8_BOOTSTRAP_BASELINE") == "1":
        (review_root / "visual-review-request.json").write_text(
            json.dumps(
                {
                    "$schema": (
                        "hocuspocus://schemas/visual-review-request/v1"
                    ),
                    "kind": "hocus_visual_version_review_request",
                    "reviewVersion": 1,
                    **review_bindings,
                    "candidateVersionId": "hs8-rock-family-v1",
                    "reviewPolicyId": "hs8-installed-visual-review-v1",
                    "baselineFile": "baseline-contact-sheet.png",
                    "baselineDigest": candidate_digest,
                    "decision": "review_pending",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
    visual_review_evidence = _detached_visual_review(qualification_mode)
    visual_payload = visual_comparison.to_dict()
    visual_payload.pop("passed")
    evidence = {
        "contract": inputs.contract,
        "observation": inputs.rebuilt["assetContractObservation"],
        "baselineProvenance": inputs.baseline_provenance.to_dict(),
        "candidateProvenance": inputs.candidate_provenance.to_dict(),
        "metrics": inputs.metrics.to_dict(),
        "budget": inputs.budget.to_dict(),
        "numericBaseline": inputs.numeric_baseline,
        "numericCandidate": inputs.numeric_candidate,
        "numericTolerances": inputs.numeric_tolerances,
        "visualComparisons": [visual_payload],
        "artistOverrideEvidence": artist_evidence,
        "visualVersionReviewEvidence": visual_review_evidence,
    }
    payload = operations.production_asset_qualify(
        evidence, context,
    )["structuredContent"]
    packaging_passed = payload["packagingGate"]["decision"] == "pass"
    release_shaped = (
        qualification_mode == "release"
        and not payload["readyForPublish"]
        and payload["publishGate"]["decision"] == "pass"
        and payload["authority"] == {
            "mode": "content_only",
            "attestationDigest": None,
        }
    )
    review_pending = (
        visual_review_evidence is None
        and not payload["readyForPublish"]
        and payload["authority"]["mode"] == "content_only"
    )
    if not packaging_passed or not (release_shaped or review_pending):
        raise RuntimeError("HS8 production qualification rejected publish.")
    return payload


def _run(temporary_root: Path) -> dict[str, Any]:
    _progress("installed-alignment")
    provider = LiveHoudiniCatalogProvider(hou, catalog_version=2)
    catalog = provider.get_catalog()
    operation_root = temporary_root / "operations"
    operation_root.mkdir(parents=True, exist_ok=True)
    operations = _HS8Operations(catalog, operation_root)
    qualification_mode = _qualification_mode()
    context = RequestContext(
        caller_id="hs8-installed-production",
        permissions=("observe", "edit_scene", "write_files"),
        timeout_seconds=300.0,
        metadata={
            "policy_revision": "hs8-installed-v1",
        },
        principal_id="hocus-principal://hs8-installed-runner",
        session_id="hs8-installed-production-session",
    )
    contract = fixture_contract()
    predeclared_contract_digest = canonical_digest(contract)
    _progress("hocus-apply")
    _prepare_roots(operations)
    observer = _observer()
    apply = _apply_sources(
        operations, catalog, context, apply_scope="initial",
    )
    pre_cook_counts = {
        node.path(): int(node.cookCount())
        for root in (hou.node(SOP_ROOT), hou.node(USD_OUTPUT))
        if root is not None
        for node in (root, *root.allSubChildren())
    }
    if any(pre_cook_counts.values()):
        raise RuntimeError(f"HS8 HocusScript apply executed a cook: {pre_cook_counts!r}")
    artist_before = add_artist_override()
    reconcile = _reconcile_rock(
        operations, catalog, context, apply_scope="initial",
    )
    artist_after_reconcile = artist_override()
    if artist_after_reconcile != artist_before:
        raise RuntimeError("HS8 source reconcile erased an artist-owned override.")
    _progress("authorized-cook-observe")
    first_cook = cook_fixture((SOP_OUTPUT, USD_OUTPUT))
    usd_path = operation_root / "hs8-rock-family.usda"
    usd_export = export_usd(usd_path)
    first = _observe_export(observer, usd_path, contract)
    first_peak_working_set = process_peak_working_set_bytes()
    _validate_product(first)
    _progress(
        "measured-contract-facts "
        + json.dumps({
            "bounds": first["assetContractObservation"]["geometry"]["bounds"],
            "uvSets": first["assetContractObservation"]["surface"]["uvSets"],
            "lods": first["assetContractObservation"]["delivery"]["lods"],
        }, sort_keys=True, separators=(",", ":"))
    )
    contract_report = _validate_contract_observation(contract, first)
    visual = _visual_evidence(operations, operation_root, context)
    first_projection = comparison_projection(first)
    _progress("save-reopen")
    hip_path = operation_root / "hs8-production-fixture.hip"
    save_reopen(operations, hip_path, context)
    if artist_override() != artist_before:
        raise RuntimeError("HS8 save/reopen changed the artist-owned override.")
    reopened_cook = cook_fixture((SOP_OUTPUT, USD_OUTPUT))
    reopened_usd = operation_root / "hs8-rock-family-reopened.usda"
    export_usd(reopened_usd)
    reopened = _observe_export(observer, reopened_usd, contract)
    _validate_product(reopened)
    if comparison_projection(reopened) != first_projection:
        raise RuntimeError(
            "HS8 production projection changed across save/reopen: "
            f"{projection_differences(first_projection, comparison_projection(reopened))!r}"
        )
    if reopened["deterministicDigest"] != first["deterministicDigest"]:
        raise RuntimeError("HS8 observation digest changed across save/reopen.")
    _progress("clean-rebuild")
    operations.scene_new({}, context)
    operations._monitor.mark_dirty("hs8.clean.rebuild")
    _prepare_roots(operations)
    rebuilt_apply = _apply_sources(
        operations, catalog, context, apply_scope="rebuild",
    )
    rebuilt_apply["rock-family-reconcile"] = _reconcile_rock(
        operations, catalog, context, apply_scope="rebuild",
    )
    rebuilt_cook = cook_fixture((SOP_OUTPUT, USD_OUTPUT))
    rebuilt_usd = operation_root / "hs8-rock-family-rebuilt.usda"
    export_usd(rebuilt_usd)
    rebuilt = _observe_export(observer, rebuilt_usd, contract)
    rebuilt_peak_working_set = process_peak_working_set_bytes()
    _validate_product(rebuilt)
    if comparison_projection(rebuilt) != first_projection:
        raise RuntimeError(
            "HS8 clean rebuild is nondeterministic: "
            f"{projection_differences(first_projection, comparison_projection(rebuilt))!r}"
        )
    if rebuilt["deterministicDigest"] != first["deterministicDigest"]:
        raise RuntimeError("HS8 observation digest changed across clean rebuild.")
    if canonical_digest(contract) != predeclared_contract_digest:
        raise RuntimeError("HS8 predeclared contract mutated after fixture cook.")
    rebuilt_visual = render_contact_sheet(
        operation_root / "hs8-contact-sheet-rebuilt.png",
    )
    first_visual = visual["contactSheet"]
    if rebuilt_visual["digest"] != first_visual["digest"]:
        raise RuntimeError("HS8 deterministic contact sheet changed on clean rebuild.")
    _bootstrap_baseline_if_requested(
        operation_root / rebuilt_visual["name"],
    )
    baseline_outputs = {
        "rock-family.usda": usd_path.read_bytes(),
        "numeric-report.json": json.dumps(
            first_projection, sort_keys=True, separators=(",", ":"),
        ).encode(),
        "contact-sheet.png": (
            operation_root / first_visual["name"]
        ).read_bytes(),
    }
    candidate_outputs = {
        "rock-family.usda": rebuilt_usd.read_bytes(),
        "numeric-report.json": json.dumps(
            comparison_projection(rebuilt), sort_keys=True, separators=(",", ":"),
        ).encode(),
        "contact-sheet.png": (
            operation_root / rebuilt_visual["name"]
        ).read_bytes(),
    }
    total_output_bytes = sum(
        len(value)
        for outputs in (baseline_outputs, candidate_outputs)
        for value in outputs.values()
    )
    if total_output_bytes > 2 * MAX_DIAGNOSTIC_USD_BYTES:
        raise RuntimeError("HS8 aggregate production outputs exceed their byte limit.")
    _preserve_usd_diagnostics(usd_path, rebuilt_usd)
    alignment = _installed_alignment(provider, catalog)
    baseline_provenance = build_manifest(
        observation=first["assetContractObservation"],
        dependency_measurements=[
            *(
                item for item in first["dependencies"]
                if item["kind"] == "hda"
            ),
            *first["finalUsd"]["assetDependencies"],
        ],
        catalog=catalog,
        installed_modules=alignment["modules"],
        package_search_receipt=alignment["packageSearch"],
        outputs=baseline_outputs,
    )
    candidate_provenance = build_manifest(
        observation=rebuilt["assetContractObservation"],
        dependency_measurements=[
            *(
                item for item in rebuilt["dependencies"]
                if item["kind"] == "hda"
            ),
            *rebuilt["finalUsd"]["assetDependencies"],
        ],
        catalog=catalog,
        installed_modules=alignment["modules"],
        package_search_receipt=alignment["packageSearch"],
        outputs=candidate_outputs,
    )
    baseline_metrics = BuildMetrics(
        cook_duration_ms=first_cook["elapsedMs"],
        peak_memory_bytes=first_peak_working_set,
        polygon_count=first["finalUsd"]["renderPolygons"],
        texture_count=first["finalUsd"]["textureCount"],
        texture_bytes=first["finalUsd"]["textureBytes"],
        output_bytes=sum(len(value) for value in baseline_outputs.values()),
        cook_error_count=first_cook["errorCount"],
        cook_warning_count=first_cook["warningCount"],
    )
    metrics = BuildMetrics(
        cook_duration_ms=rebuilt_cook["elapsedMs"],
        peak_memory_bytes=rebuilt_peak_working_set,
        polygon_count=rebuilt["finalUsd"]["renderPolygons"],
        texture_count=rebuilt["finalUsd"]["textureCount"],
        texture_bytes=rebuilt["finalUsd"]["textureBytes"],
        output_bytes=sum(len(value) for value in candidate_outputs.values()),
        cook_error_count=rebuilt_cook["errorCount"],
        cook_warning_count=rebuilt_cook["warningCount"],
    )
    budget = PlatformBudget(
        target_platform="houdini",
        max_cook_duration_ms=60_000.0,
        max_peak_memory_bytes=2 * 1024 * 1024 * 1024,
        max_polygon_count=100_000,
        max_texture_count=0,
        max_texture_bytes=0,
        max_output_bytes=64 * 1024 * 1024,
    )
    numeric_baseline = baseline_metrics.to_dict()
    numeric_candidate = metrics.to_dict()
    numeric_tolerances = {
        key: 60_000.0 if key == "cookDurationMs" else 0
        for key in numeric_baseline
    }
    numeric_tolerances["peakMemoryBytes"] = 256 * 1024 * 1024
    qualification_payload = _attested_qualification(
        operations,
        context,
        _QualificationInputs(
            contract=contract,
            rebuilt=rebuilt,
            baseline_provenance=baseline_provenance,
            candidate_provenance=candidate_provenance,
            metrics=metrics,
            budget=budget,
            numeric_baseline=numeric_baseline,
            numeric_candidate=numeric_candidate,
            numeric_tolerances=numeric_tolerances,
            rebuilt_visual=rebuilt_visual,
            artist_before=artist_before,
            artist_after_reconcile=artist_after_reconcile,
        ),
    )
    report = {
        "accepted": True,
        "fixture": "procedural-environment-rock-family",
        "installedAlignment": alignment,
        "apply": apply,
        "artistOverride": {
            "beforeReconcile": artist_before,
            "afterReconcile": artist_after_reconcile,
            "preserved": True,
        },
        "authorizedCooks": {
            "first": first_cook,
            "reopened": reopened_cook,
            "rebuilt": rebuilt_cook,
            "unintendedCookCount": 0,
        },
        "observation": first,
        "usdExport": usd_export,
        "visualEvidence": visual,
        "saveReopen": {
            "hipFile": hip_path.name,
            "projectionMatch": True,
            "observationDigest": reopened["deterministicDigest"],
        },
        "cleanRebuild": {
            "projectionMatch": True,
            "apply": rebuilt_apply,
            "observationDigest": rebuilt["deterministicDigest"],
        },
        "productionQualification": qualification_payload,
        "readyForPublish": qualification_payload["readyForPublish"],
        "reviewStatus": (
            "approved"
            if qualification_mode == "release"
            else "review_pending"
        ),
        "contractDigest": contract_report.contract_digest,
        "buildManifestDigest": candidate_provenance.manifest_digest,
        "packageReceiptDigest": qualification_payload["packagingGate"]["receiptDigest"],
        "publishReceiptDigest": qualification_payload["publishGate"]["receiptDigest"],
        "reconcileApply": reconcile,
    }
    report_path = operation_root / "hs8-production-report.json"
    report["reportInput"] = write_report(report_path, report)
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            "HS8 installed acceptance requires Houdini 22.0.368, got "
            f"{hou.applicationVersionString()}."
        )
    temporary = tempfile.TemporaryDirectory(prefix="hocuspocus-hs8-")
    operation_root = Path(temporary.name).resolve()
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        result = _run(operation_root)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        evidence_diagnostic = None
        try:
            _preserve_failed_usd_diagnostics(operation_root / "operations")
        except Exception as evidence_exc:
            evidence_diagnostic = _record_failure_evidence_diagnostic(
                evidence_exc,
            )
        failure = {
            "accepted": False,
            "errorType": type(exc).__name__,
            "message": str(exc),
        }
        if evidence_diagnostic is not None:
            failure["failureEvidenceDiagnostic"] = evidence_diagnostic
        print(json.dumps(
            failure, ensure_ascii=False, indent=2, sort_keys=True,
        ))
        return 1
    finally:
        try:
            hou.hipFile.clear(suppress_save_prompt=True)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
