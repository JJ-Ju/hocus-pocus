"""One cohesive HS8 production qualification pipeline.

This module composes the strict asset, provenance, regression, budget, and
publish contracts.  It performs no filesystem, Houdini, clock, or network I/O.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .asset_contract_validation import validate_asset_contract
from .build_comparison import (
    MAX_VISUAL_COMPARISONS,
    VisualComparison,
    compare_numeric_baseline,
    compare_repeated_builds,
    compare_visual_baseline,
)
from .build_gates import (
    create_build_report,
    create_packaging_gate_receipt,
    create_publish_gate_receipt,
    decode_gate_receipt_pair,
)
from .build_metrics import BuildMetrics, PlatformBudget
from .build_provenance import BuildProvenanceManifest, canonical_digest


PRODUCTION_QUALIFICATION_SCHEMA = (
    "hocuspocus://schemas/production-qualification/v1"
)
MAX_PRODUCTION_QUALIFICATION_BYTES = 16 * 1024 * 1024
PRODUCTION_EVIDENCE_FIELDS = frozenset({
    "contract",
    "observation",
    "baselineProvenance",
    "candidateProvenance",
    "metrics",
    "budget",
    "numericBaseline",
    "numericCandidate",
    "numericTolerances",
    "visualComparisons",
    "artistOverrideEvidence",
    "visualVersionReviewEvidence",
})
_QUALIFICATION_FIELDS = {
    "$schema",
    "kind",
    "schemaVersion",
    "assetUri",
    "contractReport",
    "buildReport",
    "packagingGate",
    "publishGate",
    "readyForPackaging",
    "readyForPublish",
    "authority",
    "qualificationDigest",
}
_DIGEST_PREFIX = "sha256:"
QualificationAttestationVerifier = Callable[[str, Mapping[str, Any]], bool]


class ProductionQualificationError(ValueError):
    """Typed failure at the complete HS8 qualification boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ProductionQualification:
    """Canonical evidence returned by one complete production decision."""

    _payload_json: str
    qualification_digest: str

    @property
    def ready_for_packaging(self) -> bool:
        return self.to_dict()["readyForPackaging"]

    @property
    def ready_for_publish(self) -> bool:
        return self.to_dict()["readyForPublish"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(self._payload_json))

    def to_json(self, *, pretty: bool = False) -> str:
        if not pretty:
            return self._payload_json
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Any) -> ProductionQualification:
        """Strictly decode an advisory qualification receipt.

        Host-attested readiness is deliberately not portable. Call
        ``decode_production_qualification`` with a trusted host verifier at the
        live authority boundary when decoding an authoritative response.
        """

        payload = _normalize_qualification(value, attestation_verifier=None)
        encoded = _canonical_json(payload)
        return cls(
            _payload_json=encoded,
            qualification_digest=payload["qualificationDigest"],
        )


def qualify_production_asset(
    *,
    contract_content: Mapping[str, Any] | str | bytes,
    observation_content: Mapping[str, Any] | str | bytes,
    baseline_provenance: BuildProvenanceManifest,
    candidate_provenance: BuildProvenanceManifest,
    metrics: BuildMetrics,
    budget: PlatformBudget,
    numeric_baseline: Mapping[str, int | float],
    numeric_candidate: Mapping[str, int | float],
    numeric_tolerances: Mapping[str, int | float],
    visual_comparisons: Iterable[VisualComparison],
    artist_override_evidence: Mapping[str, Any],
    visual_version_review_evidence: Mapping[str, Any] | None,
) -> ProductionQualification:
    """Run every required HS8 gate and bind the results into one receipt."""

    if not isinstance(
        baseline_provenance, BuildProvenanceManifest,
    ) or not isinstance(candidate_provenance, BuildProvenanceManifest):
        raise _invalid("Production qualification requires sealed build provenance.")
    contract_report = validate_asset_contract(
        contract_content,
        observation_content,
    )
    deterministic = compare_repeated_builds(
        baseline_provenance,
        candidate_provenance,
    )
    _validate_numeric_evidence(
        metrics,
        numeric_baseline,
        numeric_candidate,
        numeric_tolerances,
    )
    numeric = compare_numeric_baseline(
        numeric_baseline,
        numeric_candidate,
        numeric_tolerances,
    )
    visual = compare_visual_baseline(visual_comparisons)
    _bind_visual_comparisons(candidate_provenance, visual)
    report = create_build_report(
        provenance=candidate_provenance,
        contract_report=contract_report,
        artist_override_evidence=artist_override_evidence,
        visual_version_review_evidence=visual_version_review_evidence,
        metrics=metrics,
        budget=budget,
        deterministic_comparison=deterministic,
        numeric_comparison=numeric,
        visual_comparison=visual,
    )
    packaging = create_packaging_gate_receipt(report)
    publish = create_publish_gate_receipt(report, packaging)
    unsigned = {
        "$schema": PRODUCTION_QUALIFICATION_SCHEMA,
        "kind": "hocus_production_qualification",
        "schemaVersion": 1,
        "assetUri": candidate_provenance.to_dict()["assetUri"],
        "contractReport": contract_report.to_dict(),
        "buildReport": report.to_dict(),
        "packagingGate": packaging.to_dict(),
        "publishGate": publish.to_dict(),
        # Gate decisions are technical facts. Readiness is reserved for a host
        # authority decision at the live MCP boundary.
        "readyForPackaging": False,
        "readyForPublish": False,
        "authority": {
            "mode": "content_only",
            "attestationDigest": None,
        },
    }
    unsigned["qualificationDigest"] = canonical_digest(unsigned)
    return ProductionQualification.from_dict(unsigned)


def qualify_production_asset_content(
    content: Mapping[str, Any],
) -> ProductionQualification:
    """Decode one JSON-ready CI/MCP envelope and run complete qualification."""

    if not isinstance(content, Mapping) or set(content) != PRODUCTION_EVIDENCE_FIELDS:
        raise _invalid("Production qualification input has an invalid envelope.")
    comparisons = content["visualComparisons"]
    if (
        not isinstance(comparisons, list)
        or not comparisons
        or len(comparisons) > MAX_VISUAL_COMPARISONS
    ):
        raise _invalid("visualComparisons must be an array.")
    return qualify_production_asset(
        contract_content=content["contract"],
        observation_content=content["observation"],
        baseline_provenance=BuildProvenanceManifest.from_dict(
            content["baselineProvenance"],
        ),
        candidate_provenance=BuildProvenanceManifest.from_dict(
            content["candidateProvenance"],
        ),
        metrics=BuildMetrics.from_dict(content["metrics"]),
        budget=PlatformBudget.from_dict(content["budget"]),
        numeric_baseline=_numeric_mapping(
            content["numericBaseline"], "numericBaseline",
        ),
        numeric_candidate=_numeric_mapping(
            content["numericCandidate"], "numericCandidate",
        ),
        numeric_tolerances=_numeric_mapping(
            content["numericTolerances"], "numericTolerances",
        ),
        visual_comparisons=tuple(
            _visual_comparison(item) for item in comparisons
        ),
        artist_override_evidence=_mapping(
            content["artistOverrideEvidence"], "artistOverrideEvidence",
        ),
        visual_version_review_evidence=_optional_mapping(
            content["visualVersionReviewEvidence"],
            "visualVersionReviewEvidence",
        ),
    )


def production_evidence_digest(content: Mapping[str, Any]) -> str:
    """Digest the exact bounded evidence envelope before host attestation."""
    if not isinstance(content, Mapping) or set(content) != PRODUCTION_EVIDENCE_FIELDS:
        raise _invalid("Production evidence has an invalid envelope.")
    encoded = _canonical_json(content)
    if len(encoded.encode("utf-8")) > MAX_PRODUCTION_QUALIFICATION_BYTES:
        raise ProductionQualificationError(
            "HOCUS990",
            "Production evidence exceeds its byte limit.",
            details={"maxBytes": MAX_PRODUCTION_QUALIFICATION_BYTES},
        )
    return canonical_digest(json.loads(encoded))


def decode_production_qualification(
    value: Any,
    *,
    attestation_verifier: QualificationAttestationVerifier | None = None,
) -> ProductionQualification:
    """Strictly decode a qualification with explicit host-authority verification.

    Persisted and transported content-only receipts need no verifier. A
    host-attested receipt is accepted only when a trusted live host supplies a
    verifier for the opaque attestation digest.
    """

    payload = _normalize_qualification(
        value,
        attestation_verifier=attestation_verifier,
    )
    encoded = _canonical_json(payload)
    return ProductionQualification(
        _payload_json=encoded,
        qualification_digest=payload["qualificationDigest"],
    )


def _normalize_qualification(
    value: Any,
    *,
    attestation_verifier: QualificationAttestationVerifier | None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _QUALIFICATION_FIELDS:
        raise _invalid("Production qualification has an invalid envelope.")
    _validate_qualification_identity(value)
    report, packaging, publish = decode_gate_receipt_pair(
        value["buildReport"],
        value["packagingGate"],
        value["publishGate"],
    )
    _validate_qualification_bindings(value, report, packaging, publish)
    _validate_qualification_authority(
        value,
        packaging,
        publish,
        attestation_verifier=attestation_verifier,
    )
    if not _is_digest(value["qualificationDigest"]):
        raise _invalid("Production qualification digest is invalid.")
    unsigned = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key != "qualificationDigest"
    }
    if value["qualificationDigest"] != canonical_digest(unsigned):
        raise _invalid("Production qualification digest does not match its content.")
    normalized = copy.deepcopy(value)
    encoded = _canonical_json(normalized)
    if len(encoded.encode("utf-8")) > MAX_PRODUCTION_QUALIFICATION_BYTES:
        raise ProductionQualificationError(
            "HOCUS990",
            "Production qualification exceeds its byte limit.",
            details={"maxBytes": MAX_PRODUCTION_QUALIFICATION_BYTES},
        )
    return normalized


def _validate_qualification_identity(value: Mapping[str, Any]) -> None:
    if (
        value["$schema"] != PRODUCTION_QUALIFICATION_SCHEMA
        or value["kind"] != "hocus_production_qualification"
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(value["assetUri"], str)
        or not value["assetUri"].startswith("hocus-asset://")
        or len(value["assetUri"].encode("utf-8")) > 8192
        or type(value["readyForPackaging"]) is not bool
        or type(value["readyForPublish"]) is not bool
    ):
        raise _invalid("Production qualification identity is invalid.")


def _validate_qualification_bindings(
    value: Mapping[str, Any],
    report: Any,
    packaging: Any,
    publish: Any,
) -> None:
    report_payload = report.to_dict()
    packaging_payload = packaging.to_dict()
    publish_payload = publish.to_dict()
    if (
        value["assetUri"] != report_payload["assetUri"]
        or value["contractReport"] != report_payload["contractReport"]
        or packaging_payload["gate"] != "packaging"
        or publish_payload["gate"] != "publish"
        or packaging_payload["reportDigest"] != report.report_digest
        or publish_payload["reportDigest"] != report.report_digest
        or publish_payload["upstreamReceiptDigest"] != packaging.receipt_digest
        or publish_payload["upstreamDecision"] != packaging_payload["decision"]
    ):
        raise _invalid("Production qualification evidence is not cross-bound.")


def _validate_qualification_authority(
    value: Mapping[str, Any],
    packaging: Any,
    publish: Any,
    *,
    attestation_verifier: QualificationAttestationVerifier | None,
) -> None:
    packaging_payload = packaging.to_dict()
    publish_payload = publish.to_dict()
    authority = value["authority"]
    if (
        not isinstance(authority, dict)
        or set(authority) != {"mode", "attestationDigest"}
        or authority["mode"] not in {"content_only", "host_attested"}
    ):
        raise _invalid("Production qualification authority is invalid.")
    attestation = authority["attestationDigest"]
    if authority["mode"] == "content_only":
        if (
            attestation is not None
            or value["readyForPackaging"]
            or value["readyForPublish"]
        ):
            raise _invalid("Content-only qualification cannot declare readiness.")
    else:
        if not _is_digest(attestation):
            raise _invalid("Host-attested qualification requires an attestation digest.")
        authenticated = False
        if attestation_verifier is not None:
            try:
                authenticated = attestation_verifier(attestation, value) is True
            except Exception:
                authenticated = False
        if not authenticated:
            raise _invalid(
                "Host-attested qualification requires trusted host verification."
            )
        expected_packaging = packaging_payload["decision"] == "pass"
        expected_publish = expected_packaging and publish_payload["decision"] == "pass"
        if (
            value["readyForPackaging"] != expected_packaging
            or value["readyForPublish"] != expected_publish
        ):
            raise _invalid("Host-attested qualification readiness is inconsistent.")

    if value["readyForPublish"] and not value["readyForPackaging"]:
        raise _invalid("Publish readiness requires packaging readiness.")


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_DIGEST_PREFIX)
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def production_qualification_authority_digest(value: Any) -> str:
    """Digest exact authoritative content without circular receipt digests."""

    if not isinstance(value, Mapping) or set(value) != _QUALIFICATION_FIELDS:
        raise _invalid("Production authority content has an invalid envelope.")
    authority = value.get("authority")
    if (
        not isinstance(authority, Mapping)
        or set(authority) != {"mode", "attestationDigest"}
        or authority.get("mode") != "host_attested"
    ):
        raise _invalid("Production authority content is not host-attested.")
    projection = copy.deepcopy(dict(value))
    projection.pop("qualificationDigest")
    projection["authority"] = {
        "mode": "host_attested",
        # The opaque attestation is the digest of a MAC that includes this
        # projection, so it must not recursively include itself.
        "attestationDigest": None,
    }
    return canonical_digest(projection)


def _visual_comparison(value: Any) -> VisualComparison:
    fields = {
        "outputUri",
        "baselineDigest",
        "candidateDigest",
        "algorithm",
        "difference",
        "maximumDifference",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Visual comparison input has an invalid envelope.")
    return VisualComparison(
        output_uri=value["outputUri"],
        baseline_digest=value["baselineDigest"],
        candidate_digest=value["candidateDigest"],
        algorithm=value["algorithm"],
        difference=value["difference"],
        maximum_difference=value["maximumDifference"],
    )


def _bind_visual_comparisons(
    candidate: BuildProvenanceManifest,
    comparison: Mapping[str, Any],
) -> None:
    outputs = {
        item["uri"]: item["contentDigest"]
        for item in candidate.to_dict()["outputs"]
    }
    for row in comparison["checks"]:
        if (
            row["outputUri"] not in outputs
            or outputs[row["outputUri"]] != row["candidateDigest"]
        ):
            raise _invalid(
                "Visual comparison does not bind a candidate provenance output."
            )


def _validate_numeric_evidence(
    metrics: BuildMetrics,
    baseline: Mapping[str, int | float],
    candidate: Mapping[str, int | float],
    tolerances: Mapping[str, int | float],
) -> None:
    canonical = metrics.to_dict()
    expected_fields = set(canonical)
    if (
        not all(
            isinstance(value, Mapping)
            and set(value) == expected_fields
            for value in (baseline, candidate, tolerances)
        )
        or dict(candidate) != canonical
    ):
        raise _invalid(
            "Numeric evidence must exactly mirror the canonical build metrics."
        )


def _numeric_mapping(value: Any, label: str) -> Mapping[str, int | float]:
    mapping = _mapping(value, label)
    return mapping


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object.")
    return value


def _optional_mapping(
    value: Any,
    label: str,
) -> Mapping[str, Any] | None:
    return None if value is None else _mapping(value, label)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("Production qualification must contain finite JSON data.") from exc


def _invalid(message: str) -> ProductionQualificationError:
    return ProductionQualificationError("HOCUS990", message)


__all__ = [
    "MAX_PRODUCTION_QUALIFICATION_BYTES",
    "PRODUCTION_EVIDENCE_FIELDS",
    "PRODUCTION_QUALIFICATION_SCHEMA",
    "ProductionQualification",
    "ProductionQualificationError",
    "qualify_production_asset",
    "qualify_production_asset_content",
    "decode_production_qualification",
    "production_evidence_digest",
    "production_qualification_authority_digest",
]
