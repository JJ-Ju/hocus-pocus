"""Deterministic HS8 rebuild, numeric, and visual baseline comparison."""

from __future__ import annotations

import math
import copy
import re
from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable, Mapping

from .build_provenance import BuildProvenanceManifest


MAX_BASELINE_METRICS = 1024
MAX_VISUAL_COMPARISONS = 1024

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_METRIC = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_ALGORITHM = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_OUTPUT_URI = re.compile(
    r"^hocus-output://[a-z0-9][a-z0-9.-]{0,127}/"
    r"(?!/)(?!\.{1,2}(?:/|$))(?!.*?/\.{1,2}(?:/|$))"
    r"(?!.*//)(?!.*[?#\\:])[^/]+(?:/[^/]+)*$"
)


class BuildComparisonError(ValueError):
    """Typed malformed-comparison failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class VisualComparison:
    """Content-bound visual difference measured by an explicit algorithm."""

    output_uri: str
    baseline_digest: str
    candidate_digest: str
    algorithm: str
    difference: float
    maximum_difference: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.output_uri, str)
            or not self.output_uri.startswith("hocus-output://")
            or not 1 <= len(self.output_uri.encode("utf-8")) <= 8192
        ):
            raise _invalid("Visual comparison output URI is invalid.")
        if any(
            not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            for value in (self.baseline_digest, self.candidate_digest)
        ):
            raise _invalid("Visual comparison digests are invalid.")
        if not isinstance(self.algorithm, str) or _ALGORITHM.fullmatch(self.algorithm) is None:
            raise _invalid("Visual comparison algorithm is invalid.")
        _non_negative_float(self.difference, "difference")
        _non_negative_float(self.maximum_difference, "maximum_difference")
        if self.baseline_digest == self.candidate_digest and self.difference != 0:
            raise _invalid("Identical visual content digests must have zero difference.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "outputUri": self.output_uri,
            "baselineDigest": self.baseline_digest,
            "candidateDigest": self.candidate_digest,
            "algorithm": self.algorithm,
            "difference": self.difference,
            "maximumDifference": self.maximum_difference,
            "passed": self.difference <= self.maximum_difference,
        }


def compare_repeated_builds(
    baseline: BuildProvenanceManifest,
    candidate: BuildProvenanceManifest,
) -> dict[str, Any]:
    """Compare two sealed builds without machine paths or timestamps."""

    if not isinstance(baseline, BuildProvenanceManifest) or not isinstance(
        candidate, BuildProvenanceManifest,
    ):
        raise _invalid("Repeated-build comparison requires provenance manifests.")
    baseline_payload = baseline.to_dict()
    candidate_payload = candidate.to_dict()
    baseline_outputs = _output_map(baseline_payload["outputs"])
    candidate_outputs = _output_map(candidate_payload["outputs"])
    rows = []
    for uri in sorted(set(baseline_outputs) | set(candidate_outputs)):
        before = baseline_outputs.get(uri)
        after = candidate_outputs.get(uri)
        rows.append({
            "outputUri": uri,
            "baselineDigest": before["contentDigest"] if before else None,
            "candidateDigest": after["contentDigest"] if after else None,
            "status": (
                "missing" if after is None
                else "added" if before is None
                else "match" if before == after
                else "changed"
            ),
        })
    input_match = baseline.build_identity == candidate.build_identity
    output_match = baseline.output_set_digest == candidate.output_set_digest
    return {
        "kind": "deterministic_rebuild_comparison",
        "baselineManifestDigest": baseline.manifest_digest,
        "candidateManifestDigest": candidate.manifest_digest,
        "buildIdentityMatches": input_match,
        "outputSetMatches": output_match,
        "passed": input_match and output_match,
        "outputs": rows,
    }


def compare_numeric_baseline(
    baseline: Mapping[str, int | float],
    candidate: Mapping[str, int | float],
    absolute_tolerances: Mapping[str, int | float],
) -> dict[str, Any]:
    """Compare identical bounded metric sets under explicit absolute tolerances."""

    keys = _metric_keys(baseline, candidate, absolute_tolerances)
    checks = []
    for name in keys:
        expected = _number(baseline[name], f"baseline.{name}")
        actual = _number(candidate[name], f"candidate.{name}")
        tolerance = _number(absolute_tolerances[name], f"tolerance.{name}")
        if tolerance < 0:
            raise _invalid("Numeric tolerances must be non-negative.")
        difference = abs(actual - expected)
        checks.append({
            "metric": name,
            "baseline": expected,
            "candidate": actual,
            "absoluteDifference": difference,
            "absoluteTolerance": tolerance,
            "passed": difference <= tolerance,
        })
    return {
        "kind": "numeric_baseline_comparison",
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def compare_visual_baseline(
    comparisons: Iterable[VisualComparison],
) -> dict[str, Any]:
    """Aggregate externally measured, content-bound visual comparisons."""

    try:
        items = tuple(islice(iter(comparisons), MAX_VISUAL_COMPARISONS + 1))
    except TypeError as exc:
        raise _invalid("Visual comparisons must be iterable.") from exc
    if not items or len(items) > MAX_VISUAL_COMPARISONS:
        raise BuildComparisonError(
            "HOCUS986", "Visual comparison count is outside its bounded range."
        )
    if any(not isinstance(item, VisualComparison) for item in items):
        raise _invalid("Visual comparison entries must be typed values.")
    ordered = sorted(items, key=lambda item: item.output_uri)
    if len({item.output_uri for item in ordered}) != len(ordered):
        raise _invalid("Visual comparison output URIs must be unique.")
    checks = [item.to_dict() for item in ordered]
    return {
        "kind": "visual_baseline_comparison",
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def normalize_comparison_report(
    value: Mapping[str, Any],
    expected: str,
) -> dict[str, Any]:
    """Strict-normalize one comparison result at a report trust boundary."""

    if expected == "deterministic":
        return _normalize_rebuild(value)
    if expected == "numeric":
        return _normalize_numeric(value)
    if expected == "visual":
        return _normalize_visual(value)
    raise _invalid("Comparison kind is unsupported.")


def _normalize_rebuild(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "kind", "baselineManifestDigest", "candidateManifestDigest",
        "buildIdentityMatches", "outputSetMatches", "passed", "outputs",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Deterministic comparison has an invalid envelope.")
    if (
        value["kind"] != "deterministic_rebuild_comparison"
        or any(
            not isinstance(value[field], str) or _DIGEST.fullmatch(value[field]) is None
            for field in ("baselineManifestDigest", "candidateManifestDigest")
        )
        or any(
            type(value[field]) is not bool
            for field in ("buildIdentityMatches", "outputSetMatches", "passed")
        )
        or value["passed"] != (
            value["buildIdentityMatches"] and value["outputSetMatches"]
        )
    ):
        raise _invalid("Deterministic comparison identity is inconsistent.")
    outputs = value["outputs"]
    if not isinstance(outputs, list) or len(outputs) > 4096:
        raise BuildComparisonError("HOCUS986", "Rebuild output comparison is too large.")
    normalized = [_normalize_output_row(item) for item in outputs]
    if normalized != sorted(normalized, key=lambda item: item["outputUri"]):
        raise _invalid("Rebuild output comparisons must be URI-sorted.")
    if len({item["outputUri"] for item in normalized}) != len(normalized):
        raise _invalid("Rebuild output comparison URIs must be unique.")
    result = dict(value)
    result["outputs"] = normalized
    return copy.deepcopy(result)


def _normalize_output_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "outputUri", "baselineDigest", "candidateDigest", "status",
    }:
        raise _invalid("Rebuild output comparison row is invalid.")
    before, after = value["baselineDigest"], value["candidateDigest"]
    if (
        not isinstance(value["outputUri"], str)
        or _OUTPUT_URI.fullmatch(value["outputUri"]) is None
        or any(
            item is not None
            and (not isinstance(item, str) or _DIGEST.fullmatch(item) is None)
            for item in (before, after)
        )
    ):
        raise _invalid("Rebuild output comparison row identity is invalid.")
    expected = (
        "missing" if after is None
        else "added" if before is None
        else "match" if before == after
        else "changed"
    )
    if value["status"] != expected:
        raise _invalid("Rebuild output comparison status is inconsistent.")
    return dict(value)


def _normalize_numeric(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "passed", "checks"}:
        raise _invalid("Numeric comparison has an invalid envelope.")
    checks = value["checks"]
    if (
        value["kind"] != "numeric_baseline_comparison"
        or type(value["passed"]) is not bool
        or not isinstance(checks, list)
        or not 1 <= len(checks) <= MAX_BASELINE_METRICS
    ):
        raise _invalid("Numeric comparison is invalid.")
    normalized = [_normalize_numeric_check(item) for item in checks]
    _require_sorted_unique(normalized, "metric", "Numeric comparison")
    if value["passed"] != all(item["passed"] for item in normalized):
        raise _invalid("Numeric comparison decision is inconsistent.")
    return {"kind": value["kind"], "passed": value["passed"], "checks": normalized}


def _normalize_numeric_check(value: Any) -> dict[str, Any]:
    fields = {
        "metric", "baseline", "candidate", "absoluteDifference",
        "absoluteTolerance", "passed",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Numeric comparison check is invalid.")
    if not isinstance(value["metric"], str) or _METRIC.fullmatch(value["metric"]) is None:
        raise _invalid("Numeric comparison metric is invalid.")
    baseline = _number(value["baseline"], "baseline")
    candidate = _number(value["candidate"], "candidate")
    difference = _number(value["absoluteDifference"], "absoluteDifference")
    tolerance = _number(value["absoluteTolerance"], "absoluteTolerance")
    if (
        difference < 0
        or tolerance < 0
        or difference != abs(candidate - baseline)
        or type(value["passed"]) is not bool
        or value["passed"] != (difference <= tolerance)
    ):
        raise _invalid("Numeric comparison check is inconsistent.")
    return dict(value)


def _normalize_visual(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "passed", "checks"}:
        raise _invalid("Visual comparison has an invalid envelope.")
    checks = value["checks"]
    if (
        value["kind"] != "visual_baseline_comparison"
        or type(value["passed"]) is not bool
        or not isinstance(checks, list)
        or not 1 <= len(checks) <= MAX_VISUAL_COMPARISONS
    ):
        raise _invalid("Visual comparison is invalid.")
    normalized = [_normalize_visual_check(item) for item in checks]
    _require_sorted_unique(normalized, "outputUri", "Visual comparison")
    if value["passed"] != all(item["passed"] for item in normalized):
        raise _invalid("Visual comparison decision is inconsistent.")
    return {"kind": value["kind"], "passed": value["passed"], "checks": normalized}


def _normalize_visual_check(value: Any) -> dict[str, Any]:
    fields = {
        "outputUri", "baselineDigest", "candidateDigest", "algorithm",
        "difference", "maximumDifference", "passed",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Visual comparison check is invalid.")
    evidence = VisualComparison(
        output_uri=value["outputUri"],
        baseline_digest=value["baselineDigest"],
        candidate_digest=value["candidateDigest"],
        algorithm=value["algorithm"],
        difference=value["difference"],
        maximum_difference=value["maximumDifference"],
    ).to_dict()
    if value != evidence:
        raise _invalid("Visual comparison check is inconsistent.")
    return dict(value)


def _require_sorted_unique(values: list[dict[str, Any]], field: str, label: str) -> None:
    names = [item[field] for item in values]
    if names != sorted(names) or len(set(names)) != len(names):
        raise _invalid(f"{label} entries must be sorted and unique.")


def _output_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["uri"]: item for item in items}


def _metric_keys(*values: Mapping[str, int | float]) -> list[str]:
    if any(not isinstance(value, Mapping) for value in values):
        raise _invalid("Numeric baseline inputs must be mappings.")
    keys = set(values[0])
    if not keys or len(keys) > MAX_BASELINE_METRICS:
        raise BuildComparisonError(
            "HOCUS986", "Numeric baseline metric count is outside its bounded range."
        )
    if any(set(value) != keys for value in values[1:]):
        raise _invalid("Numeric baseline metric and tolerance keys must match exactly.")
    if any(not isinstance(key, str) or _METRIC.fullmatch(key) is None for key in keys):
        raise _invalid("Numeric baseline metric name is invalid.")
    return sorted(keys)


def _number(value: Any, label: str) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or abs(value) > 1e300
    ):
        raise _invalid(f"{label} must be a finite bounded number.")
    return value


def _non_negative_float(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1e300
    ):
        raise _invalid(f"Visual {label} must be finite and non-negative.")


def _invalid(message: str) -> BuildComparisonError:
    return BuildComparisonError("HOCUS985", message)


__all__ = [
    "BuildComparisonError",
    "VisualComparison",
    "compare_numeric_baseline",
    "compare_repeated_builds",
    "compare_visual_baseline",
    "normalize_comparison_report",
]
