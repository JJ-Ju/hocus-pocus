"""Focused reusable assertions for the pure HS8 build foundation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hocuspocus.hocusscript.asset_contract_validation import AssetContractReport
from hocuspocus.hocusscript.build_comparison import (
    VisualComparison,
    compare_numeric_baseline,
    compare_repeated_builds,
    compare_visual_baseline,
)
from hocuspocus.hocusscript.build_gates import (
    BuildGateError,
    BuildReport,
    GateReceipt,
    create_build_report,
    create_packaging_gate_receipt,
    create_publish_gate_receipt,
    decode_gate_receipt_pair,
)
from hocuspocus.hocusscript.build_metrics import BuildMetrics, PlatformBudget
from hocuspocus.hocusscript.build_provenance import (
    BuildProvenanceError,
    BuildProvenanceManifest,
    _components_from_measured_dependencies,
    canonical_digest,
    component_from_content,
    create_build_provenance,
)


def assert_hs8_build_foundation(testcase) -> None:
    """Exercise deterministic identity, baselines, budgets, and both gates."""

    manifest = _manifest(b"stable-output")
    repeated = _manifest(b"stable-output")
    changed = _manifest(b"changed-output")
    testcase.assertEqual(manifest.to_json(), repeated.to_json())
    testcase.assertIn(
        "hocus-input://studio/effective-package-search.json",
        {item["uri"] for item in manifest.to_dict()["inputs"]},
    )
    testcase.assertTrue(compare_repeated_builds(manifest, repeated)["passed"])
    testcase.assertFalse(compare_repeated_builds(manifest, changed)["passed"])
    _assert_measured_dependency_binding(testcase)

    numeric = compare_numeric_baseline(
        {"bounds.x": 10.0, "uv.coverage": 0.95},
        {"bounds.x": 10.001, "uv.coverage": 0.951},
        {"bounds.x": 0.01, "uv.coverage": 0.01},
    )
    visual = compare_visual_baseline((
        VisualComparison(
            "hocus-output://studio/tree/contact-sheet.png",
            _digest(b"pixels"),
            _digest(b"pixels"),
            "pixel-rmse-v1",
            0.0,
            0.001,
        ),
    ))
    metrics = BuildMetrics(
        cook_duration_ms=1250.0,
        peak_memory_bytes=256_000_000,
        polygon_count=125_000,
        texture_count=4,
        texture_bytes=64_000_000,
        output_bytes=80_000_000,
    )
    budget = PlatformBudget(
        target_platform="windows-x86_64",
        max_cook_duration_ms=2000.0,
        max_peak_memory_bytes=512_000_000,
        max_polygon_count=150_000,
        max_texture_count=8,
        max_texture_bytes=128_000_000,
        max_output_bytes=100_000_000,
    )
    contract = _contract_report()
    report = create_build_report(
        provenance=manifest,
        contract_report=contract,
        artist_override_evidence={
            "kind": "artist_override_evidence",
            "protectedRegionCount": 2,
            "beforeDigest": _digest(b"artist-regions"),
            "afterDigest": _digest(b"artist-regions"),
            "passed": True,
        },
        visual_version_review_evidence=_review(manifest, visual),
        metrics=metrics,
        budget=budget,
        deterministic_comparison=compare_repeated_builds(manifest, repeated),
        numeric_comparison=numeric,
        visual_comparison=visual,
    )
    package = create_packaging_gate_receipt(report)
    publish = create_publish_gate_receipt(report, package)
    testcase.assertTrue(package.passed)
    testcase.assertTrue(publish.passed)
    _assert_review_is_publish_only(
        testcase, report, manifest, contract, metrics, budget,
    )
    testcase.assertEqual(
        BuildReport.from_dict(report.to_dict()).report_digest,
        report.report_digest,
    )
    testcase.assertEqual(
        GateReceipt.from_dict(publish.to_dict()).receipt_digest,
        publish.receipt_digest,
    )
    decoded_report, decoded_package, decoded_publish = decode_gate_receipt_pair(
        report.to_dict(), package.to_dict(), publish.to_dict(),
    )
    testcase.assertEqual(decoded_report.report_digest, report.report_digest)
    testcase.assertEqual(decoded_package.receipt_digest, package.receipt_digest)
    testcase.assertEqual(decoded_publish.receipt_digest, publish.receipt_digest)
    rebound = publish.to_dict()
    rebound["upstreamReceiptDigest"] = _digest(b"other-package")
    rebound["receiptDigest"] = canonical_digest({
        key: value for key, value in rebound.items() if key != "receiptDigest"
    })
    with testcase.assertRaises(BuildGateError):
        decode_gate_receipt_pair(report.to_dict(), package.to_dict(), rebound)
    _assert_tamper_rejected(testcase, manifest, report)
    _assert_schemas(testcase, manifest, report, publish)


def _assert_measured_dependency_binding(testcase) -> None:
    hda_digest = _digest(b"hda-definition")
    input_digest = _digest(b"texture")
    dependencies = [
        {
            "kind": "hda", "id": "studio.rock", "version": "2.1.0",
            "digest": hda_digest,
        },
        {
            "kind": "texture", "id": "studio.rock.albedo", "version": "1.0.0",
            "digest": input_digest,
        },
    ]
    measurements = [
        {**dependencies[0], "byteLength": 14, "nodePath": "/obj/rock"},
        {**dependencies[1], "byteLength": 7, "roles": ["texture"]},
    ]
    hdas, inputs = _components_from_measured_dependencies(
        dependencies=dependencies,
        measurements=measurements,
        uri_authority="hs8.fixture",
    )
    testcase.assertEqual(hdas[0].byte_length, 14)
    testcase.assertEqual(inputs[0].byte_length, 7)
    for hostile in (
        measurements[:1],
        [{**measurements[0], "byteLength": True}, measurements[1]],
        [
            *measurements,
            {**measurements[0], "byteLength": 15},
        ],
    ):
        with testcase.assertRaises(BuildProvenanceError):
            _components_from_measured_dependencies(
                dependencies=dependencies,
                measurements=hostile,
                uri_authority="hs8.fixture",
            )


def _manifest(
    output: bytes,
    *,
    contact_sheet: bytes = b"pixels",
) -> BuildProvenanceManifest:
    return create_build_provenance(
        asset_uri="hocus-asset://studio/tree",
        target_platform="windows-x86_64",
        recipe=component_from_content(
            "recipe", "hocus-recipe://studio/tree/build.json", b"recipe",
        ),
        sources=(
            component_from_content(
                "source", "hocus-project://studio/tree.hocus", b"hocus-source",
            ),
        ),
        compiler=component_from_content(
            "compiler", "hocus-compiler://studio/hocusscript",
            b"compiler-package", version="0.6.0",
        ),
        catalog=component_from_content(
            "catalog", "hocus-catalog://studio/h21.json",
            b"catalog", fingerprint=_digest(b"catalog-semantics"),
        ),
        modules=(
            component_from_content(
                "module", "hocus-module://studio/rocks/rock.hocus", b"module",
                version="1.0.0",
            ),
        ),
        hdas=(
            component_from_content(
                "hda", "hocus-hda://studio/rock-generator", b"hda-definition",
                version="2.1.0",
            ),
        ),
        inputs=(
            component_from_content(
                "input", "hocus-input://studio/reference-mesh", b"mesh",
            ),
            component_from_content(
                "input",
                "hocus-input://studio/effective-package-search.json",
                b'{"kind":"hocus_effective_package_search_provenance"}',
                version="1",
            ),
        ),
        outputs=(
            component_from_content(
                "output", "hocus-output://studio/tree/tree.bgeo.sc", output,
                role="geometry", media_type="application/vnd.houdini.bgeo",
            ),
            component_from_content(
                "output",
                "hocus-output://studio/tree/contact-sheet.png",
                contact_sheet,
                role="visual-review",
                media_type="image/png",
            ),
        ),
    )


def _assert_tamper_rejected(testcase, manifest, report) -> None:
    damaged_manifest = manifest.to_dict()
    damaged_manifest["outputs"][0]["byteLength"] += 1
    with testcase.assertRaises(BuildProvenanceError) as caught:
        BuildProvenanceManifest.from_dict(damaged_manifest)
    testcase.assertEqual(caught.exception.code, "HOCUS982")

    damaged_report = report.to_dict()
    damaged_report["artistOverrideEvidence"]["afterDigest"] = _digest(b"erased")
    with testcase.assertRaises(BuildGateError):
        BuildReport.from_dict(damaged_report)

    payload = report.to_dict()
    rebound = report.to_dict()
    rebound["visualVersionReviewEvidence"][
        "candidateOutputSetDigest"
    ] = _digest(b"other-output-set")
    rebound["visualVersionReviewEvidenceDigest"] = canonical_digest(
        rebound["visualVersionReviewEvidence"],
    )
    rebound["reportDigest"] = canonical_digest({
        key: value for key, value in rebound.items() if key != "reportDigest"
    })
    with testcase.assertRaises(BuildGateError) as caught:
        BuildReport.from_dict(rebound)
    testcase.assertEqual(caught.exception.code, "HOCUS989")
    raw_notes = report.to_dict()
    raw_notes["visualVersionReviewEvidence"][
        "notesDigest"
    ] = "Looks good to publish"
    raw_notes["visualVersionReviewEvidenceDigest"] = canonical_digest(
        raw_notes["visualVersionReviewEvidence"],
    )
    raw_notes["reportDigest"] = canonical_digest({
        key: value for key, value in raw_notes.items() if key != "reportDigest"
    })
    with testcase.assertRaises(BuildGateError):
        BuildReport.from_dict(raw_notes)

    forged_contract = AssetContractReport(
        contract_digest=_digest(b"contract"),
        observation_digest=_digest(b"observation"),
        valid=True,
        diagnostics=(),
        coverage={"notObserved": []},
        digest=_digest(b"forged-report"),
    )
    with testcase.assertRaises(BuildGateError) as caught:
        create_build_report(
            provenance=manifest,
            contract_report=forged_contract,
            artist_override_evidence=payload["artistOverrideEvidence"],
            visual_version_review_evidence=payload[
                "visualVersionReviewEvidence"
            ],
            metrics=BuildMetrics.from_dict(payload["metrics"]),
            budget=PlatformBudget.from_dict(payload["budget"]),
            deterministic_comparison=payload["comparisons"]["deterministic"],
            numeric_comparison=payload["comparisons"]["numeric"],
            visual_comparison=payload["comparisons"]["visual"],
        )
    testcase.assertEqual(caught.exception.code, "HOCUS989")


def _assert_review_is_publish_only(
    testcase,
    report,
    manifest,
    contract,
    metrics,
    budget,
) -> None:
    payload = report.to_dict()
    rejected = dict(payload["visualVersionReviewEvidence"])
    rejected["decision"] = "rejected"
    for review_evidence in (None, rejected):
        blocked_report = create_build_report(
            provenance=manifest,
            contract_report=contract,
            artist_override_evidence=payload["artistOverrideEvidence"],
            visual_version_review_evidence=review_evidence,
            metrics=metrics,
            budget=budget,
            deterministic_comparison=payload["comparisons"]["deterministic"],
            numeric_comparison=payload["comparisons"]["numeric"],
            visual_comparison=payload["comparisons"]["visual"],
        )
        package = create_packaging_gate_receipt(blocked_report)
        publish = create_publish_gate_receipt(blocked_report, package)
        testcase.assertTrue(package.passed)
        testcase.assertFalse(publish.passed)
        testcase.assertNotIn(
            "visualVersionReview",
            [check["id"] for check in package.to_dict()["checks"]],
        )
        testcase.assertEqual(
            publish.to_dict()["checks"][-1],
            {
                "id": "visualVersionReview",
                "passed": False,
                "evidenceDigest": blocked_report.to_dict()[
                    "visualVersionReviewEvidenceDigest"
                ],
            },
        )


def _review(
    manifest: BuildProvenanceManifest,
    visual: dict,
) -> dict:
    return {
        "kind": "hocus_visual_version_review_evidence",
        "reviewVersion": 1,
        "assetUri": manifest.to_dict()["assetUri"],
        "candidateProvenanceManifestDigest": manifest.manifest_digest,
        "candidateOutputSetDigest": manifest.output_set_digest,
        "visualComparisonDigest": canonical_digest(visual),
        "candidateVersionId": "tree-v1",
        "reviewPolicyId": "studio-visual-review-v1",
        "reviewerPrincipalId": "hocus-principal://studio-art-lead",
        "decision": "approved",
        "notesDigest": None,
    }


def _assert_schemas(testcase, manifest, report, receipt) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    root = Path(__file__).resolve().parents[1] / "docs" / "schemas"
    cases = (
        ("build-provenance-manifest-v1.schema.json", manifest.to_dict()),
        ("build-report-v1.schema.json", report.to_dict()),
        ("publish-gate-receipt-v1.schema.json", receipt.to_dict()),
    )
    for name, payload in cases:
        schema = json.loads((root / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(payload)
        testcase.assertEqual(schema["$id"], payload["$schema"])


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _contract_report() -> AssetContractReport:
    body = {
        "kind": "hocus_asset_contract_report",
        "reportVersion": 1,
        "contractDigest": _digest(b"contract"),
        "observationDigest": _digest(b"observation"),
        "valid": True,
        "diagnostics": [],
        "coverage": {"notObserved": []},
    }
    encoded = json.dumps(
        body, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return AssetContractReport(
        contract_digest=body["contractDigest"],
        observation_digest=body["observationDigest"],
        valid=True,
        diagnostics=(),
        coverage={"notObserved": []},
        digest=_digest(encoded),
    )


__all__ = ["assert_hs8_build_foundation"]
