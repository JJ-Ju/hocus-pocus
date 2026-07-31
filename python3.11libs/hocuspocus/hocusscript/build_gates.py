"""Canonical HS8 build reports and packaging/publish gate receipts."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .asset_contract_validation import AssetContractReport
from .build_comparison import normalize_comparison_report
from .build_metrics import BuildMetrics, PlatformBudget, evaluate_platform_budget
from .build_provenance import (
    BuildProvenanceManifest,
    canonical_digest,
)


BUILD_REPORT_SCHEMA = "hocuspocus://schemas/build-report/v1"
PUBLISH_GATE_SCHEMA = "hocuspocus://schemas/publish-gate-receipt/v1"
MAX_BUILD_REPORT_BYTES = 8 * 1024 * 1024

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PORTABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REVIEWER_ID = re.compile(
    r"^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
    r"hprincipal_[0-9a-f]{32}|"
    r"sha256:[0-9a-f]{64})$"
)
_NOT_OBSERVED_REASONS = {
    "host_api_unavailable",
    "texture_resolution_unavailable",
    "runtime_camera_model_unavailable",
    "required_input_unavailable",
    "not_applicable",
}
_CHECKS = (
    "contract", "artistOverrides", "provenance", "outputs", "budget",
    "deterministic", "numeric", "visual", "visualVersionReview",
)
_COMPARISON_KINDS = {
    "deterministic": "deterministic_rebuild_comparison",
    "numeric": "numeric_baseline_comparison",
    "visual": "visual_baseline_comparison",
}


class BuildGateError(ValueError):
    """Typed malformed-report or gate-receipt failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class BuildReport:
    """Authenticated numeric and regression evidence for one sealed build."""

    _payload_json: str
    report_digest: str

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(self._payload_json))

    def to_json(self, *, pretty: bool = False) -> str:
        if not pretty:
            return self._payload_json
        return json.dumps(
            self.to_dict(), ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True,
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Any) -> BuildReport:
        payload = _normalize_report(value)
        return cls(_canonical_json(payload), payload["reportDigest"])


@dataclass(frozen=True, slots=True)
class GateReceipt:
    """Deterministic packaging or publish decision bound to exact evidence."""

    _payload_json: str
    receipt_digest: str

    @property
    def passed(self) -> bool:
        return self.to_dict()["decision"] == "pass"

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(self._payload_json))

    @classmethod
    def from_dict(cls, value: Any) -> GateReceipt:
        payload = _normalize_receipt(value)
        return cls(_canonical_json(payload), payload["receiptDigest"])


def create_build_report(
    *,
    provenance: BuildProvenanceManifest,
    contract_report: AssetContractReport,
    artist_override_evidence: Mapping[str, Any],
    visual_version_review_evidence: Mapping[str, Any] | None,
    metrics: BuildMetrics,
    budget: PlatformBudget,
    deterministic_comparison: Mapping[str, Any] | None = None,
    numeric_comparison: Mapping[str, Any] | None = None,
    visual_comparison: Mapping[str, Any] | None = None,
) -> BuildReport:
    """Combine exact provenance, production metrics, and optional baselines."""

    if not isinstance(provenance, BuildProvenanceManifest):
        raise _invalid("Build report provenance must be a sealed manifest.")
    if not isinstance(contract_report, AssetContractReport):
        raise _invalid("Build report requires a typed asset contract report.")
    if not isinstance(metrics, BuildMetrics) or not isinstance(budget, PlatformBudget):
        raise _invalid("Build report requires typed metrics and platform budget.")
    override_evidence = _artist_override_evidence(artist_override_evidence)
    contract_payload = _contract_report(contract_report.to_dict())
    provenance_payload = provenance.to_dict()
    target = provenance_payload["targetPlatform"]
    comparisons = {
        "deterministic": _comparison(
            deterministic_comparison, "deterministic",
        ),
        "numeric": _comparison(numeric_comparison, "numeric"),
        "visual": _comparison(visual_comparison, "visual"),
    }
    review_evidence = _optional_visual_version_review_evidence(
        visual_version_review_evidence,
    )
    if review_evidence is not None:
        _bind_visual_version_review(
            review_evidence,
            provenance_payload=provenance_payload,
            comparisons=comparisons,
        )
    unsigned = {
        "$schema": BUILD_REPORT_SCHEMA,
        "kind": "hocus_build_report",
        "schemaVersion": 1,
        "assetUri": provenance_payload["assetUri"],
        "targetPlatform": target,
        "provenanceManifestDigest": provenance.manifest_digest,
        "buildIdentity": provenance.build_identity,
        "outputSetDigest": provenance.output_set_digest,
        "outputCount": len(provenance_payload["outputs"]),
        "contractReport": contract_payload,
        "contractReportDigest": contract_report.digest,
        "contractPassed": contract_report.valid,
        "artistOverrideEvidence": override_evidence,
        "artistOverrideEvidenceDigest": canonical_digest(override_evidence),
        "visualVersionReviewEvidence": review_evidence,
        "visualVersionReviewEvidenceDigest": canonical_digest(review_evidence),
        "metrics": metrics.to_dict(),
        "budget": budget.to_dict(),
        "budgetEvaluation": evaluate_platform_budget(
            metrics, budget, target_platform=target,
        ),
        "comparisons": comparisons,
    }
    unsigned["reportDigest"] = canonical_digest(unsigned)
    return BuildReport.from_dict(unsigned)


def create_packaging_gate_receipt(report: BuildReport) -> GateReceipt:
    """Require contract, overrides, deterministic, numeric, and budget evidence."""

    return _create_gate_receipt(
        report,
        gate="packaging",
        required=_CHECKS[:-2],
        upstream=None,
    )


def create_publish_gate_receipt(
    report: BuildReport,
    packaging_receipt: GateReceipt,
) -> GateReceipt:
    """Require package, visual comparison, and explicit version review passes."""

    if not isinstance(packaging_receipt, GateReceipt):
        raise _invalid("Publish gate requires a packaging gate receipt.")
    package = packaging_receipt.to_dict()
    if (
        package["gate"] != "packaging"
        or package["reportDigest"] != report.report_digest
    ):
        raise BuildGateError(
            "HOCUS988", "Publish gate packaging receipt does not bind this report."
        )
    return _create_gate_receipt(
        report,
        gate="publish",
        required=tuple(_CHECKS),
        upstream=packaging_receipt,
    )


def decode_gate_receipt_pair(
    report_value: BuildReport | Mapping[str, Any],
    packaging_value: GateReceipt | Mapping[str, Any],
    publish_value: GateReceipt | Mapping[str, Any],
) -> tuple[BuildReport, GateReceipt, GateReceipt]:
    """Strictly decode and cross-bind both receipts to one build report."""

    report = (
        report_value
        if isinstance(report_value, BuildReport)
        else BuildReport.from_dict(report_value)
    )
    packaging = (
        packaging_value
        if isinstance(packaging_value, GateReceipt)
        else GateReceipt.from_dict(packaging_value)
    )
    publish = (
        publish_value
        if isinstance(publish_value, GateReceipt)
        else GateReceipt.from_dict(publish_value)
    )
    expected_packaging = create_packaging_gate_receipt(report)
    expected_publish = create_publish_gate_receipt(report, expected_packaging)
    if (
        packaging.to_dict() != expected_packaging.to_dict()
        or publish.to_dict() != expected_publish.to_dict()
    ):
        raise BuildGateError(
            "HOCUS989",
            "Gate receipts do not exactly bind the supplied build report.",
        )
    return report, packaging, publish


def _create_gate_receipt(
    report: BuildReport,
    *,
    gate: str,
    required: tuple[str, ...],
    upstream: GateReceipt | None,
) -> GateReceipt:
    if not isinstance(report, BuildReport):
        raise _invalid("Gate receipt requires a typed build report.")
    payload = report.to_dict()
    available = {
        "contract": payload["contractPassed"],
        "artistOverrides": payload["artistOverrideEvidence"]["passed"],
        "provenance": True,
        "outputs": payload["outputCount"] > 0,
        "budget": payload["budgetEvaluation"]["passed"],
        "visualVersionReview": (
            payload["visualVersionReviewEvidence"] is not None
            and payload["visualVersionReviewEvidence"]["decision"] == "approved"
        ),
        **{
            name: (
                payload["comparisons"][name] is not None
                and payload["comparisons"][name]["passed"]
            )
            for name in _COMPARISON_KINDS
        },
    }
    checks = [
        {
            "id": name,
            "passed": available[name],
            "evidenceDigest": _evidence_digest(payload, name),
        }
        for name in required
    ]
    upstream_digest = upstream.receipt_digest if upstream is not None else None
    upstream_passed = upstream is None or upstream.passed
    unsigned = {
        "$schema": PUBLISH_GATE_SCHEMA,
        "kind": "hocus_gate_receipt",
        "schemaVersion": 1,
        "gate": gate,
        "reportDigest": report.report_digest,
        "upstreamReceiptDigest": upstream_digest,
        "upstreamDecision": (
            "pass" if upstream is not None and upstream.passed
            else "fail" if upstream is not None
            else None
        ),
        "checks": checks,
        "decision": (
            "pass" if upstream_passed and all(item["passed"] for item in checks)
            else "fail"
        ),
    }
    unsigned["receiptDigest"] = canonical_digest(unsigned)
    return GateReceipt.from_dict(unsigned)


def _evidence_digest(payload: dict[str, Any], name: str) -> str:
    if name == "provenance":
        return payload["provenanceManifestDigest"]
    if name == "contract":
        return payload["contractReportDigest"]
    if name == "artistOverrides":
        return payload["artistOverrideEvidenceDigest"]
    if name == "outputs":
        return payload["outputSetDigest"]
    if name == "budget":
        return canonical_digest(payload["budgetEvaluation"])
    if name == "visualVersionReview":
        return payload["visualVersionReviewEvidenceDigest"]
    comparison = payload["comparisons"][name]
    return canonical_digest(comparison) if comparison is not None else canonical_digest(None)


def _normalize_report(value: Any) -> dict[str, Any]:
    fields = {
        "$schema", "kind", "schemaVersion", "assetUri", "targetPlatform",
        "provenanceManifestDigest", "buildIdentity", "outputSetDigest", "outputCount",
        "contractReport", "contractReportDigest", "contractPassed",
        "artistOverrideEvidence", "artistOverrideEvidenceDigest",
        "visualVersionReviewEvidence", "visualVersionReviewEvidenceDigest",
        "metrics", "budget", "budgetEvaluation", "comparisons", "reportDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Build report has an invalid envelope.")
    if (
        value["$schema"] != BUILD_REPORT_SCHEMA
        or value["kind"] != "hocus_build_report"
        or value["schemaVersion"] != 1
        or not isinstance(value["assetUri"], str)
        or not value["assetUri"].startswith("hocus-asset://")
        or type(value["outputCount"]) is not int
        or not 0 <= value["outputCount"] <= 4096
    ):
        raise _invalid("Build report identity is invalid.")
    for field in (
        "provenanceManifestDigest", "buildIdentity", "outputSetDigest",
        "contractReportDigest", "artistOverrideEvidenceDigest",
        "visualVersionReviewEvidenceDigest", "reportDigest",
    ):
        if not isinstance(value[field], str) or _DIGEST.fullmatch(value[field]) is None:
            raise _invalid(f"Build report {field} is invalid.")
    contract = _contract_report(value["contractReport"])
    if (
        contract["reportDigest"] != value["contractReportDigest"]
        or type(value["contractPassed"]) is not bool
        or contract["valid"] != value["contractPassed"]
    ):
        raise _invalid("Build report asset contract evidence is invalid.")
    override_evidence = _artist_override_evidence(value["artistOverrideEvidence"])
    if canonical_digest(override_evidence) != value["artistOverrideEvidenceDigest"]:
        raise BuildGateError(
            "HOCUS989", "Artist override evidence digest does not match its content."
        )
    _normalize_review_report_evidence(value)
    metrics = BuildMetrics.from_dict(value["metrics"])
    budget = PlatformBudget.from_dict(value["budget"])
    evaluation = evaluate_platform_budget(
        metrics, budget, target_platform=value["targetPlatform"],
    )
    if value["budgetEvaluation"] != evaluation:
        raise BuildGateError("HOCUS989", "Build report budget evidence is inconsistent.")
    if not isinstance(value["comparisons"], dict) or set(value["comparisons"]) != set(
        _COMPARISON_KINDS,
    ):
        raise _invalid("Build report comparisons have an invalid envelope.")
    for name in _COMPARISON_KINDS:
        _comparison(value["comparisons"][name], name)
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "reportDigest"}
    if value["reportDigest"] != canonical_digest(unsigned):
        raise BuildGateError("HOCUS989", "Build report digest does not match its content.")
    normalized = copy.deepcopy(value)
    if len(_canonical_json(normalized).encode("utf-8")) > MAX_BUILD_REPORT_BYTES:
        raise BuildGateError("HOCUS987", "Build report exceeds its byte limit.")
    return normalized


def _normalize_review_report_evidence(value: Mapping[str, Any]) -> None:
    review_evidence = _optional_visual_version_review_evidence(
        value["visualVersionReviewEvidence"],
    )
    if (
        canonical_digest(review_evidence)
        != value["visualVersionReviewEvidenceDigest"]
    ):
        raise BuildGateError(
            "HOCUS989",
            "Visual version review evidence digest does not match its content.",
        )
    if review_evidence is not None:
        _bind_visual_version_review(
            review_evidence,
            provenance_payload={
                "assetUri": value["assetUri"],
                "manifestDigest": value["provenanceManifestDigest"],
                "outputSetDigest": value["outputSetDigest"],
            },
            comparisons=value["comparisons"],
        )


def _normalize_receipt(value: Any) -> dict[str, Any]:
    fields = {
        "$schema", "kind", "schemaVersion", "gate", "reportDigest",
        "upstreamReceiptDigest", "upstreamDecision", "checks", "decision",
        "receiptDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Gate receipt has an invalid envelope.")
    if (
        value["$schema"] != PUBLISH_GATE_SCHEMA
        or value["kind"] != "hocus_gate_receipt"
        or value["schemaVersion"] != 1
        or value["gate"] not in {"packaging", "publish"}
        or value["decision"] not in {"pass", "fail"}
    ):
        raise _invalid("Gate receipt identity is invalid.")
    digests = (value["reportDigest"], value["receiptDigest"])
    upstream = value["upstreamReceiptDigest"]
    upstream_decision = value["upstreamDecision"]
    if any(not isinstance(item, str) or _DIGEST.fullmatch(item) is None for item in digests):
        raise _invalid("Gate receipt digest is invalid.")
    if upstream is not None and (
        not isinstance(upstream, str) or _DIGEST.fullmatch(upstream) is None
    ):
        raise _invalid("Gate receipt upstream digest is invalid.")
    checks = value["checks"]
    expected_check_ids = (
        _CHECKS[:-2] if value["gate"] == "packaging" else _CHECKS
    )
    if (
        not isinstance(checks, list)
        or [item.get("id") for item in checks if isinstance(item, dict)]
        != list(expected_check_ids)
    ):
        raise _invalid("Gate receipt checks are invalid.")
    for item in checks:
        if (
            set(item) != {"id", "passed", "evidenceDigest"}
            or type(item["passed"]) is not bool
            or not isinstance(item["evidenceDigest"], str)
            or _DIGEST.fullmatch(item["evidenceDigest"]) is None
        ):
            raise _invalid("Gate receipt check is invalid.")
    expected = (
        "pass"
        if upstream_decision != "fail" and all(item["passed"] for item in checks)
        else "fail"
    )
    if value["decision"] != expected:
        raise BuildGateError("HOCUS989", "Gate receipt decision is inconsistent.")
    if value["gate"] == "packaging" and (
        upstream is not None or upstream_decision is not None
    ):
        raise _invalid("Packaging gate cannot declare an upstream receipt.")
    if value["gate"] == "publish" and (
        upstream is None or upstream_decision not in {"pass", "fail"}
    ):
        raise _invalid("Publish gate requires an upstream receipt.")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "receiptDigest"}
    if value["receiptDigest"] != canonical_digest(unsigned):
        raise BuildGateError("HOCUS989", "Gate receipt digest does not match its content.")
    return copy.deepcopy(value)


def _comparison(value: Mapping[str, Any] | None, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    normalized = normalize_comparison_report(value, name)
    if len(_canonical_json(normalized).encode("utf-8")) > MAX_BUILD_REPORT_BYTES:
        raise BuildGateError("HOCUS987", f"{name} comparison is too large.")
    return normalized


def _artist_override_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "kind", "protectedRegionCount", "beforeDigest", "afterDigest", "passed",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Artist override evidence has an invalid envelope.")
    before, after = value["beforeDigest"], value["afterDigest"]
    if (
        value["kind"] != "artist_override_evidence"
        or type(value["protectedRegionCount"]) is not int
        or not 0 <= value["protectedRegionCount"] <= 1_000_000
        or type(value["passed"]) is not bool
        or any(
            not isinstance(item, str) or _DIGEST.fullmatch(item) is None
            for item in (before, after)
        )
        or value["passed"] != (before == after)
    ):
        raise _invalid("Artist override evidence is invalid or inconsistent.")
    return dict(value)


def _optional_visual_version_review_evidence(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    fields = {
        "kind", "reviewVersion", "assetUri",
        "candidateProvenanceManifestDigest", "candidateOutputSetDigest",
        "visualComparisonDigest", "candidateVersionId", "reviewPolicyId",
        "reviewerPrincipalId", "decision", "notesDigest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Visual version review evidence has an invalid envelope.")
    digest_fields = (
        "candidateProvenanceManifestDigest",
        "candidateOutputSetDigest",
        "visualComparisonDigest",
    )
    notes_digest = value["notesDigest"]
    if (
        value["kind"] != "hocus_visual_version_review_evidence"
        or type(value["reviewVersion"]) is not int
        or value["reviewVersion"] != 1
        or not isinstance(value["assetUri"], str)
        or not value["assetUri"].startswith("hocus-asset://")
        or len(value["assetUri"].encode("utf-8")) > 8192
        or any(
            not isinstance(value[field], str)
            or _DIGEST.fullmatch(value[field]) is None
            for field in digest_fields
        )
        or not isinstance(value["candidateVersionId"], str)
        or _PORTABLE_ID.fullmatch(value["candidateVersionId"]) is None
        or not isinstance(value["reviewPolicyId"], str)
        or _PORTABLE_ID.fullmatch(value["reviewPolicyId"]) is None
        or not isinstance(value["reviewerPrincipalId"], str)
        or _REVIEWER_ID.fullmatch(value["reviewerPrincipalId"]) is None
        or not isinstance(value["decision"], str)
        or value["decision"] not in {"approved", "rejected"}
        or (
            notes_digest is not None
            and (
                not isinstance(notes_digest, str)
                or _DIGEST.fullmatch(notes_digest) is None
            )
        )
    ):
        raise _invalid("Visual version review evidence is invalid.")
    return dict(value)


def _bind_visual_version_review(
    evidence: Mapping[str, Any],
    *,
    provenance_payload: Mapping[str, Any],
    comparisons: Mapping[str, Any],
) -> None:
    visual = comparisons.get("visual")
    expected = {
        "assetUri": provenance_payload["assetUri"],
        "candidateProvenanceManifestDigest": provenance_payload["manifestDigest"],
        "candidateOutputSetDigest": provenance_payload["outputSetDigest"],
        "visualComparisonDigest": canonical_digest(visual),
    }
    if any(evidence[field] != value for field, value in expected.items()):
        raise BuildGateError(
            "HOCUS989",
            "Visual version review evidence does not bind this candidate build.",
        )


def _contract_report(value: Any) -> dict[str, Any]:
    fields = {
        "kind", "reportVersion", "contractDigest", "observationDigest",
        "valid", "diagnostics", "coverage", "reportDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Asset contract report has an invalid envelope.")
    if (
        value["kind"] != "hocus_asset_contract_report"
        or value["reportVersion"] != 1
        or type(value["valid"]) is not bool
        or any(
            not isinstance(value[field], str) or _DIGEST.fullmatch(value[field]) is None
            for field in ("contractDigest", "observationDigest", "reportDigest")
        )
        or not isinstance(value["diagnostics"], list)
        or len(value["diagnostics"]) > 4096
    ):
        raise _invalid("Asset contract report identity is invalid.")
    diagnostics = [_contract_diagnostic(item) for item in value["diagnostics"]]
    _contract_coverage(value["coverage"])
    ordered = sorted(
        diagnostics,
        key=lambda item: (item["jsonPointer"], item["code"], item["message"]),
    )
    if diagnostics != ordered or value["valid"] != (not diagnostics):
        raise _invalid("Asset contract report decision or diagnostic order is inconsistent.")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "reportDigest"}
    if canonical_digest(unsigned) != value["reportDigest"]:
        raise BuildGateError(
            "HOCUS989", "Asset contract report digest does not match its content."
        )
    return copy.deepcopy(value)


def _contract_coverage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"notObserved"}:
        raise _invalid("Asset contract coverage has an invalid envelope.")
    items = value["notObserved"]
    if not isinstance(items, list) or len(items) > 4096:
        raise _invalid("Asset contract coverage is invalid or unbounded.")
    normalized = []
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"jsonPointer", "reasonCode", "required"}
            or not isinstance(item["jsonPointer"], str)
            or not item["jsonPointer"].startswith("/")
            or len(item["jsonPointer"].encode("utf-8")) > 8192
            or not isinstance(item["reasonCode"], str)
            or item["reasonCode"] not in _NOT_OBSERVED_REASONS
            or type(item["required"]) is not bool
        ):
            raise _invalid("Asset contract coverage item is invalid.")
        normalized.append(dict(item))
    ordered = sorted(
        normalized,
        key=lambda item: (item["jsonPointer"], item["reasonCode"]),
    )
    if normalized != ordered or len({
        (item["jsonPointer"], item["reasonCode"]) for item in normalized
    }) != len(normalized):
        raise _invalid("Asset contract coverage must be sorted and unique.")
    return {"notObserved": normalized}


def _contract_diagnostic(value: Any) -> dict[str, Any]:
    fields = {"severity", "code", "message", "jsonPointer", "expected", "actual"}
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Asset contract diagnostic has an invalid envelope.")
    if (
        value["severity"] != "error"
        or not isinstance(value["code"], str)
        or re.fullmatch(r"HOCUS9[0-9]{2}", value["code"]) is None
        or not isinstance(value["message"], str)
        or not 1 <= len(value["message"].encode("utf-8")) <= 4096
        or not isinstance(value["jsonPointer"], str)
        or len(value["jsonPointer"].encode("utf-8")) > 8192
    ):
        raise _invalid("Asset contract diagnostic is invalid.")
    _canonical_json({"expected": value["expected"], "actual": value["actual"]})
    return copy.deepcopy(value)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("Build gate payload must be finite JSON data.") from exc


def _invalid(message: str) -> BuildGateError:
    return BuildGateError("HOCUS987", message)


__all__ = [
    "BUILD_REPORT_SCHEMA",
    "PUBLISH_GATE_SCHEMA",
    "BuildGateError",
    "BuildReport",
    "GateReceipt",
    "create_build_report",
    "create_packaging_gate_receipt",
    "create_publish_gate_receipt",
    "decode_gate_receipt_pair",
]
