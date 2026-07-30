"""Reusable assertions for the cohesive HS8 qualification surface."""

from __future__ import annotations

import ast
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hocuspocus.core.policy import (
    REVIEW_PRODUCTION,
    capability_set_from_settings,
)
from hocuspocus.core.server import HocusPocusRuntime
from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.hocusscript.build_comparison import (
    VisualComparison,
    compare_visual_baseline,
)
from hocuspocus.hocusscript.build_metrics import BuildMetrics, PlatformBudget
from hocuspocus.hocusscript.build_provenance import canonical_digest
from hocuspocus.hocusscript.production_pipeline import (
    ProductionQualificationError,
    decode_production_qualification,
    qualify_production_asset,
    qualify_production_asset_content,
)
from hocuspocus.hocusscript.port_selectors import connector_evidence_name
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.production import ProductionOperationsMixin
from hocuspocus.live.production_observation import ProductionFixtureObserver
from hocuspocus.live.production_usd_observation import (
    ProductionUsdObservationError,
    observe_production_usda,
    project_asset_contract_observation,
)
from tests.hocusscript_hs8_asset_contract_helpers import _contract, _observation
from tests.hocusscript_hs8_build_helpers import _digest, _manifest
from tests.hocusscript_hs8_clean_process_helpers import (
    assert_hs8_clean_process_orchestrator,
)
from tests.hocusscript_hs8_release_authority_helpers import (
    assert_hs8_external_release_authority,
)
from tests.hocusscript_hs8_package_search_helpers import (
    assert_hs8_package_search_provenance,
)
from tests.hocusscript_hs8_release_candidate_helpers import (
    assert_hs8_release_candidate_manifest,
)
from tests.hocusscript_hs8_usd_helpers import (
    assert_native_over_prototype_truth,
    assert_point_instancer_truth,
    assert_reopened_stage_authority,
    assert_required_intrinsic_truth,
    assert_right_handed_export_truth,
    assert_transformed_and_static_usd_truth,
    assert_usd_dependency_truth,
    author_tetra_mesh,
)


ROOT = Path(__file__).resolve().parents[1]
HS8_MAIN = ROOT / "scripts" / "smoke_hocusscript_hs8.py"
HS8_SUPPORT = ROOT / "scripts" / "smoke_hocusscript_hs8_support.py"
BUILD_SCRIPT = ROOT / "scripts" / "build.ps1"
HS8_OBSERVER = ROOT / "python3.11libs" / "hocuspocus" / "live" / "production_observation.py"
HS8_ROCK_FIXTURES = (
    ROOT / "scripts" / "fixtures" / "hs8" / "rock-family.hocus",
    ROOT / "scripts" / "fixtures" / "hs8" / "rock-family-reconcile.hocus",
)


class _ProductionTools(OperationBaseMixin, ProductionOperationsMixin):
    pass


def assert_hs8_integrated_qualification(testcase: Any) -> None:
    baseline = _manifest(b"stable-output")
    candidate = _manifest(b"stable-output")
    metrics = _metrics()
    budget = _budget()
    visual = _visual()
    artist = _artist()
    qualification = qualify_production_asset(
        contract_content=_contract(),
        observation_content=_observation(),
        baseline_provenance=baseline,
        candidate_provenance=candidate,
        metrics=metrics,
        budget=budget,
        **_numeric_evidence(metrics),
        visual_comparisons=(visual,),
        artist_override_evidence=artist,
        visual_version_review_evidence=_review(candidate, visual),
    )
    testcase.assertFalse(qualification.ready_for_packaging)
    testcase.assertFalse(qualification.ready_for_publish)
    payload = qualification.to_dict()
    testcase.assertEqual(payload["publishGate"]["decision"], "pass")
    testcase.assertEqual(payload["authority"], {
        "mode": "content_only", "attestationDigest": None,
    })
    testcase.assertEqual(
        payload["qualificationDigest"], qualification.qualification_digest,
    )
    testcase.assertEqual(
        qualification.to_json(),
        qualify_production_asset_content(
            _content(baseline, candidate, metrics, budget, visual, artist),
        ).to_json(),
    )
    content_without_review = _content(
        baseline, candidate, metrics, budget, visual, artist,
    )
    content_without_review["visualVersionReviewEvidence"] = None
    without_review = qualify_production_asset_content(content_without_review)
    testcase.assertFalse(without_review.ready_for_packaging)
    testcase.assertEqual(
        without_review.to_dict()["publishGate"]["decision"], "fail",
    )
    missing_review = dict(content_without_review)
    missing_review.pop("visualVersionReviewEvidence")
    with testcase.assertRaises(ProductionQualificationError):
        qualify_production_asset_content(missing_review)
    _assert_publish_requires_visual(testcase, baseline, candidate, metrics, budget)
    _assert_evidence_cross_bindings(
        testcase, baseline, candidate, metrics, budget, visual, artist,
    )
    _assert_mcp_surface(testcase, payload)
    _assert_installed_harness_contract(testcase)
    _assert_output_representation_measurements(testcase)
    _assert_reopened_usda_truth(testcase)
    assert_hs8_clean_process_orchestrator(testcase)
    assert_hs8_package_search_provenance(testcase)
    assert_hs8_external_release_authority(testcase)
    assert_hs8_release_candidate_manifest(testcase)


def _metrics() -> BuildMetrics:
    return BuildMetrics(
        cook_duration_ms=1250.0,
        peak_memory_bytes=256_000_000,
        polygon_count=125_000,
        texture_count=4,
        texture_bytes=64_000_000,
        output_bytes=80_000_000,
    )


def _budget() -> PlatformBudget:
    return PlatformBudget(
        target_platform="windows-x86_64",
        max_cook_duration_ms=2000.0,
        max_peak_memory_bytes=512_000_000,
        max_polygon_count=150_000,
        max_texture_count=8,
        max_texture_bytes=128_000_000,
        max_output_bytes=100_000_000,
    )


def _numeric_evidence(metrics: BuildMetrics) -> dict[str, dict[str, int | float]]:
    values = metrics.to_dict()
    return {
        "numeric_baseline": dict(values),
        "numeric_candidate": dict(values),
        "numeric_tolerances": {key: 0 for key in values},
    }


def _visual(*, difference: float = 0.0) -> VisualComparison:
    return VisualComparison(
        "hocus-output://studio/tree/contact-sheet.png",
        _digest(b"pixels"),
        _digest(b"pixels") if difference == 0 else _digest(b"changed"),
        "pixel-rmse-v1",
        difference,
        0.001,
    )


def _artist() -> dict[str, Any]:
    digest = _digest(b"artist-regions")
    return {
        "kind": "artist_override_evidence",
        "protectedRegionCount": 2,
        "beforeDigest": digest,
        "afterDigest": digest,
        "passed": True,
    }


def _review(
    candidate: Any,
    visual: VisualComparison,
    *,
    decision: str = "approved",
) -> dict[str, Any]:
    return {
        "kind": "hocus_visual_version_review_evidence",
        "reviewVersion": 1,
        "assetUri": candidate.to_dict()["assetUri"],
        "candidateProvenanceManifestDigest": candidate.manifest_digest,
        "candidateOutputSetDigest": candidate.output_set_digest,
        "visualComparisonDigest": canonical_digest(
            compare_visual_baseline((visual,)),
        ),
        "candidateVersionId": "tree-v1",
        "reviewPolicyId": "studio-visual-review-v1",
        "reviewerPrincipalId": "hocus-principal://studio-art-lead",
        "decision": decision,
        "notesDigest": None,
    }


def _content(
    baseline: Any,
    candidate: Any,
    metrics: BuildMetrics,
    budget: PlatformBudget,
    visual: VisualComparison,
    artist: dict[str, Any],
) -> dict[str, Any]:
    visual_payload = visual.to_dict()
    visual_payload.pop("passed")
    return {
        "contract": _contract(),
        "observation": _observation(),
        "baselineProvenance": baseline.to_dict(),
        "candidateProvenance": candidate.to_dict(),
        "metrics": metrics.to_dict(),
        "budget": budget.to_dict(),
        "numericBaseline": dict(metrics.to_dict()),
        "numericCandidate": dict(metrics.to_dict()),
        "numericTolerances": {
            key: 0 for key in metrics.to_dict()
        },
        "visualComparisons": [visual_payload],
        "artistOverrideEvidence": artist,
        "visualVersionReviewEvidence": _review(candidate, visual),
    }


def _assert_publish_requires_visual(
    testcase: Any,
    baseline: Any,
    candidate: Any,
    metrics: BuildMetrics,
    budget: PlatformBudget,
) -> None:
    failed_visual = _visual(difference=0.1)
    failed_baseline = _manifest(
        b"stable-output", contact_sheet=b"changed",
    )
    failed_candidate = _manifest(
        b"stable-output", contact_sheet=b"changed",
    )
    blocked = qualify_production_asset(
        contract_content=_contract(),
        observation_content=_observation(),
        baseline_provenance=failed_baseline,
        candidate_provenance=failed_candidate,
        metrics=metrics,
        budget=budget,
        **_numeric_evidence(metrics),
        visual_comparisons=(failed_visual,),
        artist_override_evidence=_artist(),
        visual_version_review_evidence=_review(
            failed_candidate, failed_visual,
        ),
    )
    testcase.assertFalse(blocked.ready_for_packaging)
    testcase.assertFalse(blocked.ready_for_publish)
    visual = _visual()
    for review_evidence in (
        None,
        _review(candidate, visual, decision="rejected"),
    ):
        review_blocked = qualify_production_asset(
            contract_content=_contract(),
            observation_content=_observation(),
            baseline_provenance=baseline,
            candidate_provenance=candidate,
            metrics=metrics,
            budget=budget,
            **_numeric_evidence(metrics),
            visual_comparisons=(visual,),
            artist_override_evidence=_artist(),
            visual_version_review_evidence=review_evidence,
        )
        testcase.assertFalse(review_blocked.ready_for_packaging)
        testcase.assertEqual(
            review_blocked.to_dict()["publishGate"]["decision"], "fail",
        )


def _assert_evidence_cross_bindings(
    testcase: Any,
    baseline: Any,
    candidate: Any,
    metrics: BuildMetrics,
    budget: PlatformBudget,
    visual: VisualComparison,
    artist: dict[str, Any],
) -> None:
    content = _content(
        baseline, candidate, metrics, budget, visual, artist,
    )
    mismatched_digest = copy.deepcopy(content)
    mismatched_digest["visualComparisons"][0][
        "candidateDigest"
    ] = _digest(b"not-the-candidate-output")
    with testcase.assertRaises(ProductionQualificationError):
        qualify_production_asset_content(mismatched_digest)
    extra_output = copy.deepcopy(content)
    extra_output["visualComparisons"][0][
        "outputUri"
    ] = "hocus-output://studio/tree/untracked-contact-sheet.png"
    with testcase.assertRaises(ProductionQualificationError):
        qualify_production_asset_content(extra_output)
    numeric_drift = copy.deepcopy(content)
    numeric_drift["numericCandidate"]["polygonCount"] += 1
    with testcase.assertRaises(ProductionQualificationError):
        qualify_production_asset_content(numeric_drift)
    incomplete_baseline = copy.deepcopy(content)
    incomplete_baseline["numericBaseline"].pop("cookDurationMs")
    with testcase.assertRaises(ProductionQualificationError):
        qualify_production_asset_content(incomplete_baseline)


def _assert_mcp_surface(testcase: Any, expected: dict[str, Any]) -> None:
    operations = _ProductionTools()
    tools = ToolRegistry()
    resources = ResourceRegistry()
    operations.register_production_surface(tools, resources)
    testcase.assertEqual(set(tools.tools), {"production.asset.qualify"})
    testcase.assertEqual(len(resources.resources), 10)
    definition = tools.get("production.asset.qualify")
    testcase.assertIsNotNone(definition)
    testcase.assertTrue(definition.annotations["readOnlyHint"])
    testcase.assertFalse(definition.annotations["idempotentHint"])
    testcase.assertNotIn("hostAttestation", definition.input_schema["properties"])
    testcase.assertFalse(
        definition.input_schema["properties"]["observation"][
            "additionalProperties"
        ]
    )
    testcase.assertEqual(
        definition.input_schema["properties"]["metrics"]["properties"][
            "polygonCount"
        ]["type"],
        "integer",
    )
    evidence = _content(
        _manifest(b"stable-output"),
        _manifest(b"stable-output"),
        _metrics(),
        _budget(),
        _visual(),
        _artist(),
    )
    context = RequestContext(
        caller_id="hs8-test",
        principal_id="hocus-principal://studio-art-lead",
        session_id="session-hs8",
        permissions=("observe",),
        metadata={
            "policy_revision": "studio-policy-v1",
            "production_review_policy_id": "studio-visual-review-v1",
        },
    )
    review_context = copy.copy(context)
    review_context.permissions = ("observe", REVIEW_PRODUCTION)
    advisory = definition.handler(evidence, context)["structuredContent"]
    testcase.assertFalse(advisory["readyForPackaging"])
    testcase.assertFalse(advisory["readyForPublish"])
    testcase.assertEqual(advisory["authority"], {
        "mode": "content_only", "attestationDigest": None,
    })
    testcase.assertEqual(advisory["publishGate"]["decision"], "pass")
    testcase.assertEqual(advisory["qualificationDigest"], expected["qualificationDigest"])
    _assert_public_qualification_digest(testcase, advisory)
    testcase.assertEqual(
        decode_production_qualification(advisory).to_dict(),
        advisory,
    )
    _assert_server_review_authority(testcase, definition, operations, evidence)

    absent_review = copy.deepcopy(evidence)
    absent_review["visualVersionReviewEvidence"] = None
    pending = definition.handler(absent_review, review_context)["structuredContent"]
    testcase.assertEqual(pending["authority"], advisory["authority"])
    testcase.assertFalse(pending["readyForPublish"])
    wrong_reviewer = copy.deepcopy(evidence)
    wrong_reviewer["visualVersionReviewEvidence"][
        "reviewerPrincipalId"
    ] = "hocus-principal://another-reviewer"
    wrong = definition.handler(wrong_reviewer, review_context)["structuredContent"]
    testcase.assertEqual(wrong["authority"], advisory["authority"])
    testcase.assertFalse(wrong["readyForPublish"])
    wrong_policy_context = copy.copy(review_context)
    wrong_policy_context.metadata = dict(review_context.metadata)
    wrong_policy_context.metadata[
        "production_review_policy_id"
    ] = "untrusted-review-policy-v1"
    testcase.assertEqual(
        definition.handler(evidence, wrong_policy_context)["structuredContent"][
            "authority"
        ],
        advisory["authority"],
    )
    missing_policy_context = copy.copy(review_context)
    missing_policy_context.metadata = {
        "policy_revision": review_context.metadata["policy_revision"],
    }
    testcase.assertEqual(
        definition.handler(evidence, missing_policy_context)["structuredContent"][
            "authority"
        ],
        advisory["authority"],
    )

    with testcase.assertRaises(JsonRpcError):
        definition.handler({**evidence, "hostAttestation": {}}, review_context)
    repeated = definition.handler(evidence, review_context)["structuredContent"]
    testcase.assertEqual(repeated["authority"], advisory["authority"])
    testcase.assertFalse(repeated["readyForPackaging"])
    testcase.assertFalse(repeated["readyForPublish"])
    schema_authoritative = copy.deepcopy(advisory)
    schema_authoritative["authority"] = {
        "mode": "host_attested",
        "attestationDigest": "sha256:" + "0" * 64,
    }
    schema_authoritative["readyForPackaging"] = True
    schema_authoritative["readyForPublish"] = True
    schema_authoritative["qualificationDigest"] = canonical_digest({
        key: value
        for key, value in schema_authoritative.items()
        if key != "qualificationDigest"
    })
    with testcase.assertRaises(ProductionQualificationError):
        decode_production_qualification(schema_authoritative)
    contradictory = copy.deepcopy(advisory)
    contradictory["readyForPackaging"] = True
    contradictory["qualificationDigest"] = canonical_digest({
        key: value
        for key, value in contradictory.items()
        if key != "qualificationDigest"
    })
    with testcase.assertRaises(ProductionQualificationError):
        decode_production_qualification(contradictory)
    extra_field = copy.deepcopy(schema_authoritative)
    extra_field["authority"]["scope"] = "publishing"
    extra_field["qualificationDigest"] = canonical_digest({
        key: value for key, value in extra_field.items()
        if key != "qualificationDigest"
    })
    with testcase.assertRaises(ProductionQualificationError):
        decode_production_qualification(extra_field)
    schema_payloads: dict[str, dict[str, Any]] = {}
    for resource in resources.resources.values():
        response = resource.reader(
            RequestContext(caller_id="hs8-schema", permissions=("observe",)),
        )
        schema = json.loads(response["contents"][0]["text"])
        testcase.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        schema_payloads[schema["$id"]] = schema
    for legacy_uri, canonical_uri in (
        (
            "houdini://production/schema/asset-contract/v1",
            "hocuspocus://schemas/asset-contract/v1",
        ),
        (
            "houdini://production/schema/build-provenance/v1",
            "hocuspocus://schemas/build-provenance-manifest/v1",
        ),
        (
            "houdini://production/schema/build-report/v1",
            "hocuspocus://schemas/build-report/v1",
        ),
        (
            "houdini://production/schema/publish-gate/v1",
            "hocuspocus://schemas/publish-gate-receipt/v1",
        ),
        (
            "houdini://production/schema/qualification/v1",
            "hocuspocus://schemas/production-qualification/v1",
        ),
    ):
        legacy = resources.get(legacy_uri).reader(context)
        canonical = resources.get(canonical_uri).reader(context)
        testcase.assertEqual(
            json.loads(legacy["contents"][0]["text"]),
            json.loads(canonical["contents"][0]["text"]),
        )
    _assert_authority_json_schemas(
        testcase,
        definition.input_schema,
        schema_payloads,
        evidence,
        advisory,
        schema_authoritative,
    )


def _assert_server_review_authority(
    testcase: Any,
    definition: Any,
    operations: _ProductionTools,
    evidence: dict[str, Any],
) -> None:
    default_settings = ServerSettings()
    testcase.assertFalse(default_settings.allow_production_review)
    testcase.assertNotIn(
        REVIEW_PRODUCTION,
        capability_set_from_settings(default_settings),
    )
    default_context = _server_context(
        default_settings,
        principal_id="hprincipal_" + "a" * 32,
        session_id="hs8-default-review-session",
    )
    denied = definition.handler(evidence, default_context)["structuredContent"]
    testcase.assertEqual(denied["authority"]["mode"], "content_only")
    testcase.assertFalse(denied["readyForPublish"])
    testcase.assertFalse(denied["readyForPackaging"])
    config = (ROOT / "config" / "default.toml").read_text(encoding="utf-8")
    testcase.assertIn("allow_production_review = false", config)

    enabled_settings = ServerSettings(
        allow_production_review=True,
        production_review_policy_id="studio-visual-review-v1",
    )
    principal = "hprincipal_" + "b" * 32
    enabled_context = _server_context(
        enabled_settings,
        principal_id=principal,
        session_id="hs8-enabled-review-session",
    )
    testcase.assertIn(REVIEW_PRODUCTION, enabled_context.permissions)
    testcase.assertEqual(
        enabled_context.metadata["production_review_policy_id"],
        "studio-visual-review-v1",
    )
    authorized_evidence = copy.deepcopy(evidence)
    authorized_evidence["visualVersionReviewEvidence"][
        "reviewerPrincipalId"
    ] = principal
    advisory = definition.handler(
        authorized_evidence, enabled_context,
    )["structuredContent"]
    testcase.assertEqual(advisory["authority"]["mode"], "content_only")
    testcase.assertIsNone(advisory["authority"]["attestationDigest"])
    testcase.assertFalse(advisory["readyForPackaging"])
    testcase.assertFalse(advisory["readyForPublish"])
    testcase.assertIsInstance(operations, _ProductionTools)


def _server_context(
    settings: ServerSettings,
    *,
    principal_id: str,
    session_id: str,
) -> RequestContext:
    runtime = object.__new__(HocusPocusRuntime)
    runtime.settings = settings
    runtime._default_capabilities = capability_set_from_settings(settings)
    runtime.workspace_authority = SimpleNamespace(
        session=lambda *_args, **_kwargs: SimpleNamespace(),
    )
    return runtime._build_context(
        "tools/call",
        "hs8-review",
        {},
        principal_id=principal_id,
        session_id=session_id,
    )


def _assert_public_qualification_digest(
    testcase: Any,
    payload: dict[str, Any],
) -> None:
    unsigned = copy.deepcopy(payload)
    digest = unsigned.pop("qualificationDigest")
    testcase.assertEqual(digest, canonical_digest(unsigned))


def _assert_authority_json_schemas(
    testcase: Any,
    input_schema: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    advisory: dict[str, Any],
    authoritative: dict[str, Any],
) -> None:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        return
    registry = Registry().with_resources(
        (uri, Resource.from_contents(schema))
        for uri, schema in schemas.items()
    )
    input_validator = jsonschema.Draft202012Validator(
        input_schema,
        registry=registry,
    )
    input_validator.validate(evidence)
    malformed = copy.deepcopy(evidence)
    malformed["metrics"]["polygonCount"] = 1.5
    testcase.assertFalse(input_validator.is_valid(malformed))
    testcase.assertFalse(input_validator.is_valid({
        **evidence,
        "observation": {},
    }))
    testcase.assertFalse(input_validator.is_valid({
        **evidence,
        "hostAttestation": {},
    }))
    qualification_schema = schemas[
        "hocuspocus://schemas/production-qualification/v1"
    ]
    qualification_validator = jsonschema.Draft202012Validator(
        qualification_schema,
        registry=registry,
    )
    qualification_validator.validate(advisory)
    qualification_validator.validate(authoritative)
    impossible = copy.deepcopy(advisory)
    impossible["readyForPackaging"] = True
    testcase.assertFalse(qualification_validator.is_valid(impossible))
    missing_attestation = copy.deepcopy(authoritative)
    missing_attestation["authority"]["attestationDigest"] = None
    testcase.assertFalse(qualification_validator.is_valid(missing_attestation))


def _assert_installed_harness_contract(testcase: Any) -> None:
    for path in (HS8_MAIN, HS8_SUPPORT):
        source = path.read_text(encoding="utf-8")
        testcase.assertLessEqual(len(source.splitlines()), 1200)
        compile(source, str(path), "exec")
        tree = ast.parse(source, filename=str(path))
        testcase.assertFalse(_adds_repository_python_path(tree))
    main = HS8_MAIN.read_text(encoding="utf-8")
    testcase.assertIn("ProductionFixtureObserver", main)
    testcase.assertIn("production_asset_qualify", main)
    testcase.assertNotIn("_issue_production_evidence_attestation", main)
    testcase.assertNotIn('"hostAttestation"', main)
    testcase.assertIn("readyForPublish", main)
    testcase.assertIn("clean-rebuild", main)
    testcase.assertIn("artist-owned override", main)
    transaction = (
        BUILD_SCRIPT.parent / "build_transaction.ps1"
    ).read_text(encoding="utf-8")
    testcase.assertIn(".HocusPocus.candidate.", transaction)
    testcase.assertIn("Move-Item -LiteralPath $candidate", transaction)
    testcase.assertIn("HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", main)
    testcase.assertIn("MAX_DIAGNOSTIC_USD_BYTES", main)
    testcase.assertIn("copy_exclusive_or_identical", main)
    testcase.assertIn("failureEvidenceDiagnostic", main)
    testcase.assertNotIn("exc = RuntimeError(", main)
    support = HS8_SUPPORT.read_text(encoding="utf-8")
    support_tree = ast.parse(support, filename=str(HS8_SUPPORT))
    key_assignment = next(
        node for node in support_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "TRANSIENT_HOUDINI_CUSTOM_DATA_KEYS"
            for target in node.targets
        )
    )
    testcase.assertIsInstance(key_assignment.value, ast.Call)
    key_values = key_assignment.value.args[0]
    testcase.assertIsInstance(key_values, ast.Set)
    testcase.assertEqual(
        {ast.literal_eval(element) for element in key_values.elts},
        {
            "HoudiniCreatorNode",
            "HoudiniDataId",
            "HoudiniEditorNodes",
            "HoudiniPrimEditorNodes",
            "HoudiniVolumeFilePaths",
        },
    )
    testcase.assertIn("_remove_transient_houdini_custom_data(flattened)", support)
    testcase.assertIn("spec.customData = retained", support)
    testcase.assertIn("for property_spec in tuple(prim_spec.properties):", support)
    testcase.assertIn("_transient_houdini_property(property_spec)", support)
    testcase.assertIn('str(property_spec.name) != "info:sourceAsset"', support)
    testcase.assertNotIn("byte_length=0", support)
    testcase.assertIn("_components_from_measured_dependencies(", support)
    main = HS8_MAIN.read_text(encoding="utf-8")
    testcase.assertIn('first["finalUsd"]["assetDependencies"]', main)
    testcase.assertIn('rebuilt["finalUsd"]["assetDependencies"]', main)


def _assert_output_representation_measurements(testcase: Any) -> None:
    testcase.assertIsNone(connector_evidence_name(
        SimpleNamespace(index=None, name="variadic"), 0,
    ))
    testcase.assertEqual(connector_evidence_name(
        SimpleNamespace(index=0, name="geometry"), 0,
    ), "geometry")
    testcase.assertIsNone(connector_evidence_name(
        SimpleNamespace(index=0, name="variadic"), 5,
    ))
    observer = ProductionFixtureObserver(
        SimpleNamespace(), authorized_roots=("/obj/hs8_rock_family",),
    )
    assert_required_intrinsic_truth(testcase, observer)
    disconnected = _FakeGeometry(
        primitives=(
            _FakePrimitive(0, "Polygon", (0, 1, 2)),
            _FakePrimitive(1, "Polygon", (3, 4, 5)),
        ),
    )
    report, instance_count = observer._contract_instancing(disconnected)
    testcase.assertEqual(report, {
        "used": False, "uniqueMeshes": 0, "unpackedInstances": 0,
    })
    testcase.assertEqual(instance_count, 0)

    packed = _FakeGeometry(primitives=(
        _FakePrimitive(0, "PackedGeometry", (), geometry_id=91),
        _FakePrimitive(1, "PackedGeometry", (), geometry_id=91),
    ))
    report, instance_count = observer._contract_instancing(packed)
    testcase.assertEqual(report, {
        "used": True, "uniqueMeshes": 1, "unpackedInstances": 0,
    })
    testcase.assertEqual(instance_count, 2)

    explicit = _FakeGeometry(
        points=(
            _FakePoint(0, {"instancepath": "/obj/rock"}),
            _FakePoint(1, {"instancepath": "/obj/rock"}),
        ),
        point_attributes=("instancepath",),
    )
    report, instance_count = observer._contract_instancing(explicit)
    testcase.assertEqual(report, {
        "used": True, "uniqueMeshes": 1, "unpackedInstances": 2,
    })
    testcase.assertEqual(instance_count, 2)

    lod0 = _FakePrimitive(0, "Polygon", (0, 1, 2, 3))
    lod1 = _FakePrimitive(1, "Polygon", (4, 5, 6))
    lods = observer._contract_lods(_FakeGeometry(
        primitives=(lod0, lod1),
        groups={"lod0": (lod0,), "lod1": (lod1,)},
    ))
    testcase.assertEqual(lods, [
        {
            "name": "lod0",
            "triangles": 2,
            "vertices": 4,
            "relativeTriangleReduction": {
                "status": "measured", "value": 0.0,
            },
        },
        {
            "name": "lod1",
            "triangles": 1,
            "vertices": 3,
            "relativeTriangleReduction": {
                "status": "measured", "value": 0.5,
            },
        },
    ])
    observer_source = HS8_OBSERVER.read_text(encoding="utf-8")
    testcase.assertNotIn('parent.node("family_copies")', observer_source)
    for path in HS8_ROCK_FIXTURES:
        source = path.read_text(encoding="utf-8")
        testcase.assertIn(
            'family_instance_source @id("hs8.family.instance.source"): "pack"',
            source,
        )
        testcase.assertIn(
            "input[0] = family_prototype.output[0];",
            source,
        )
        testcase.assertIn(
            'family_prototype @id("hs8.family.prototype"): "merge"',
            source,
        )
        testcase.assertIn("input[0] = lod0_material.output[0];", source)
        testcase.assertIn("input[1] = lod1_material.output[0];", source)
        testcase.assertIn("input[2] = collision_path.output[0];", source)
        testcase.assertNotIn("delivered_family", source)
        testcase.assertIn("input[0] = family_instances.output[0];", source)


def _assert_reopened_usda_truth(testcase: Any) -> None:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    assert_right_handed_export_truth(
        testcase, Gf=Gf, Sdf=Sdf, Usd=Usd, UsdGeom=UsdGeom,
    )
    contract = json.loads(
        (ROOT / "scripts" / "fixtures" / "hs8" / "asset-contract.json").read_text(
            encoding="utf-8",
        )
    )
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "asset.usda"
        stage = Usd.Stage.CreateNew(str(path))
        world = UsdGeom.Xform.Define(stage, "/World").GetPrim()
        Usd.ModelAPI(world).SetKind("assembly")
        stage.SetDefaultPrim(world)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        stage.GetRootLayer().customLayerData = {
            "hocuspocus": {
                "forwardAxis": "-Z",
                "pivotMode": "origin",
            },
        }
        UsdGeom.Xform.Define(stage, "/World/RockFamily")
        UsdGeom.Xform.Define(
            stage,
            "/World/RockFamily/Prototypes/Rock",
        )
        flattened_prototype = UsdGeom.Xform.Define(
            stage,
            "/Flattened_Prototype_1",
        ).GetPrim()
        prototype_mesh = UsdGeom.Mesh.Define(
            stage,
            "/Flattened_Prototype_1/Geometry",
        )
        author_tetra_mesh(
            prototype_mesh,
            Gf=Gf, Sdf=Sdf, UsdGeom=UsdGeom, surface=True,
        )
        material = UsdShade.Material.Define(
            stage,
            "/World/Looks/hs8_rock_material",
        )
        UsdShade.MaterialBindingAPI.Apply(
            prototype_mesh.GetPrim(),
        ).Bind(material)
        for binding in contract["usd"]["primBindings"]:
            mesh = UsdGeom.Mesh.Define(stage, binding["primPath"])
            author_tetra_mesh(
                mesh, Gf=Gf, Sdf=Sdf, UsdGeom=UsdGeom, surface=True,
            )
            mesh.CreatePurposeAttr(binding["purpose"])
            mesh.CreateVisibilityAttr(binding["visibility"])
            if binding["materialPrimPath"] is not None:
                UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
        for index in range(3):
            instance = stage.DefinePrim(
                f"/World/RockFamily/Instances/rock_{index}",
                "Xform",
            )
            instance.GetReferences().AddInternalReference(
                flattened_prototype.GetPath()
            )
            instance.SetInstanceable(True)
            UsdGeom.Xformable(instance).AddTranslateOp().Set(
                Gf.Vec3d(index * 2.0, 0.0, 0.0)
            )
        stage.GetRootLayer().Save()
        del stage

        observed = observe_production_usda(path, contract=contract)
        testcase.assertEqual(observed["defaultPrim"], "/World")
        testcase.assertEqual(observed["publishArc"], "inline")
        testcase.assertEqual(observed["space"], {
            "metersPerUnit": 1.0,
            "upAxis": "Y",
            "forwardAxis": "-Z",
            "handedness": "right",
        })
        testcase.assertEqual(observed["pivot"], {
            "mode": "origin",
            "position": [0.0, 0.0, 0.0],
        })
        testcase.assertEqual(observed["materialSlots"], ["hs8_rock_material"])
        testcase.assertEqual(observed["instancing"]["instanceCount"], 3)
        testcase.assertEqual(
            observed["instancing"]["prototypePrimPath"],
            "/Flattened_Prototype_1",
        )
        testcase.assertEqual(
            observed["instancing"]["representation"],
            "native_instance",
        )
        testcase.assertEqual(observed["instancing"]["renderedInstanceCount"], 3)
        testcase.assertEqual(observed["instancing"]["uniqueMeshes"], 2)
        testcase.assertEqual(observed["instancing"]["unpackedInstances"], 1)
        testcase.assertEqual(observed["renderPolygons"], 16)
        testcase.assertEqual(observed["renderVertices"], 16)
        testcase.assertEqual(observed["bounds"], {
            "minimum": [0.0, 0.0, 0.0],
            "maximum": [5.0, 1.0, 1.0],
        })
        testcase.assertEqual(observed["textureBytes"], 0)
        testcase.assertTrue(observed["normals"]["consistent"])
        testcase.assertTrue(observed["tangents"]["orthogonal"])
        testcase.assertEqual(observed["uvSets"][0]["usdNames"], ["st"])
        projected = project_asset_contract_observation(_observation(), observed)
        testcase.assertEqual(
            projected["geometry"]["normals"]["maxUnitLengthError"],
            observed["normals"]["maxUnitLengthError"],
        )
        testcase.assertEqual(
            projected["surface"]["uvSets"][0]["texelDensity"],
            observed["uvSets"][0]["texelDensity"],
        )
        assert_transformed_and_static_usd_truth(
            testcase,
            path=path,
            contract=contract,
            baseline=observed,
            Gf=Gf,
            Usd=Usd,
            UsdGeom=UsdGeom,
        )

        missing = copy.deepcopy(contract)
        missing["usd"]["primBindings"][0]["primPath"] = (
            "/World/RockFamily/Prototype/Missing"
        )
        with testcase.assertRaises(ProductionUsdObservationError):
            observe_production_usda(path, contract=missing)
        hidden = Path(temporary) / "parent-hidden.usda"
        hidden.write_bytes(path.read_bytes())
        hidden_stage = Usd.Stage.Open(str(hidden))
        hidden_parent = UsdGeom.Imageable(
            hidden_stage.GetPrimAtPath(
                "/World/RockFamily",
            )
        )
        hidden_parent.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
        hidden_stage.GetRootLayer().Save()
        del hidden_stage
        hidden_observation = observe_production_usda(hidden, contract=contract)
        hidden_lod0 = next(
            item for item in hidden_observation["primBindings"]
            if item["name"] == "lod0"
        )
        testcase.assertEqual(hidden_lod0["visibility"], "inherited")
        testcase.assertEqual(
            hidden_observation["instancing"]["renderedInstanceCount"], 0,
        )
        testcase.assertEqual(hidden_observation["renderPolygons"], 0)
        assert_point_instancer_truth(
            testcase, Gf=Gf, Sdf=Sdf, Usd=Usd, UsdGeom=UsdGeom,
        )
        assert_native_over_prototype_truth(
            testcase, Gf=Gf, Sdf=Sdf, Usd=Usd, UsdGeom=UsdGeom,
        )
        assert_reopened_stage_authority(
            testcase,
            path=path,
            contract=contract,
            baseline=observed,
            Gf=Gf,
            Sdf=Sdf,
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
        for property_name in ("normals", "primvars:tangentu", "primvars:st"):
            hostile = Path(temporary) / (
                "missing-" + property_name.replace(":", "-") + ".usda"
            )
            hostile.write_bytes(path.read_bytes())
            hostile_stage = Usd.Stage.Open(str(hostile))
            hostile_prim = hostile_stage.GetPrimAtPath(
                contract["usd"]["primBindings"][1]["primPath"]
            )
            hostile_prim.RemoveProperty(property_name)
            hostile_stage.GetRootLayer().Save()
            del hostile_stage
            with testcase.assertRaises(ProductionUsdObservationError):
                observe_production_usda(hostile, contract=contract)
        assert_usd_dependency_truth(
            testcase, path, contract, Sdf=Sdf, Usd=Usd, UsdGeom=UsdGeom)


class _FakeAttribute:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class _FakePoint:
    def __init__(self, number: int, values: dict[str, str] | None = None):
        self._number = number
        self._values = values or {}

    def number(self) -> int:
        return self._number

    def stringAttribValue(self, attribute: _FakeAttribute) -> str:
        return self._values.get(attribute.name(), "")


class _FakeVertex:
    def __init__(self, point: _FakePoint):
        self._point = point

    def point(self) -> _FakePoint:
        return self._point


class _FakePrimitiveType:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class _FakePrimitive:
    def __init__(
        self,
        number: int,
        type_name: str,
        points: tuple[int, ...],
        *,
        geometry_id: int | None = None,
    ):
        self._number = number
        self._type = _FakePrimitiveType(type_name)
        self._vertices = tuple(
            _FakeVertex(_FakePoint(point)) for point in points
        )
        self._geometry_id = geometry_id

    def number(self) -> int:
        return self._number

    def type(self) -> _FakePrimitiveType:
        return self._type

    def vertices(self) -> tuple[_FakeVertex, ...]:
        return self._vertices

    def intrinsicValue(self, name: str) -> int:
        if name != "geometryid" or self._geometry_id is None:
            raise ValueError(name)
        return self._geometry_id


class _FakeGroup:
    def __init__(self, name: str, primitives: tuple[_FakePrimitive, ...]):
        self._name = name
        self._primitives = primitives

    def name(self) -> str:
        return self._name

    def prims(self) -> tuple[_FakePrimitive, ...]:
        return self._primitives


class _FakeGeometry:
    def __init__(
        self,
        *,
        primitives: tuple[_FakePrimitive, ...] = (),
        points: tuple[_FakePoint, ...] = (),
        point_attributes: tuple[str, ...] = (),
        groups: dict[str, tuple[_FakePrimitive, ...]] | None = None,
    ):
        self._primitives = primitives
        self._points = points
        self._point_attributes = tuple(
            _FakeAttribute(name) for name in point_attributes
        )
        self._groups = tuple(
            _FakeGroup(name, values)
            for name, values in (groups or {}).items()
        )

    def prims(self) -> tuple[_FakePrimitive, ...]:
        return self._primitives

    def points(self) -> tuple[_FakePoint, ...]:
        return self._points

    def pointAttribs(self) -> tuple[_FakeAttribute, ...]:
        return self._point_attributes

    def primGroups(self) -> tuple[_FakeGroup, ...]:
        return self._groups


def _adds_repository_python_path(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            node.func.attr in {"append", "insert"}
            and isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "sys"
            and owner.attr == "path"
        ):
            return True
    return False


__all__ = ["assert_hs8_integrated_qualification"]
