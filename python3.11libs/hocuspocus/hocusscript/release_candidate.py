"""Strict, offline identity contract for one immutable release candidate.

This module does not inspect Git, discover dependencies, sign evidence, or
grant release authority. Every identity is supplied explicitly by an operator.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .release_authority import canonical_json_bytes
from .release_evidence import (
    ReleaseEvidenceError,
    verify_rc1_evidence_set,
)


SCHEMA = "hocuspocus://schemas/release-candidate-manifest/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_DIGEST = re.compile(
    r"^(?:git-sha1:[0-9a-f]{40}|git-sha256:[0-9a-f]{64})$"
)
_SECTIONS = {
    "source": (
        "commitDigest",
        "treeDigest",
        "sourceArchiveDigest",
    ),
    "execution": (
        "runnerSetDigest",
        "dependencySetDigest",
    ),
    "releaseAssets": (
        "fixtureSetDigest",
        "baselineSetDigest",
        "reviewRequestDigest",
        "schemaSetDigest",
    ),
    "installedCandidate": (
        "installManifestDigest",
        "activePointerDigest",
        "runtimeDigest",
    ),
    "evidence": (
        "technicalQualificationReceiptDigest",
        "packageProvenanceReceiptDigest",
        "rc1EvidenceDigest",
    ),
}


class ReleaseCandidateError(ValueError):
    """Malformed, stale, or mismatched immutable-candidate evidence."""


def normalize_release_candidate_inputs(
    value: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Reject discovery, defaults, extras, and malformed operator identities."""

    if not isinstance(value, Mapping) or set(value) != set(_SECTIONS):
        raise ReleaseCandidateError(
            "Release-candidate inputs have an invalid envelope."
        )
    normalized = {}
    for section, fields in _SECTIONS.items():
        item = value[section]
        if not isinstance(item, Mapping) or set(item) != set(fields):
            raise ReleaseCandidateError(
                f"Release-candidate input section {section} is invalid."
            )
        normalized[section] = {
            field: _identity(field, item[field])
            for field in fields
        }
    return normalized


def create_release_candidate_manifest(
    inputs: Mapping[str, Any],
    rc1_evidence_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a deterministic manifest from only explicit operator inputs."""

    normalized = normalize_release_candidate_inputs(inputs)
    _verify_rc1_bindings(normalized, rc1_evidence_set)
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_release_candidate_manifest",
        "schemaVersion": 1,
        "inputs": normalized,
    }
    return {
        **unsigned,
        "manifestDigest": _canonical_digest(unsigned),
    }


def verify_release_candidate_manifest(
    manifest: Mapping[str, Any],
    expected_inputs: Mapping[str, Any],
    rc1_evidence_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify canonical identity and exact independently retained RC2 inputs."""

    fields = {"$schema", "kind", "schemaVersion", "inputs", "manifestDigest"}
    if not isinstance(manifest, Mapping) or set(manifest) != fields:
        raise ReleaseCandidateError(
            "Release-candidate manifest has an invalid envelope."
        )
    if (
        manifest["$schema"] != SCHEMA
        or manifest["kind"] != "hocus_release_candidate_manifest"
        or isinstance(manifest["schemaVersion"], bool)
        or manifest["schemaVersion"] != 1
    ):
        raise ReleaseCandidateError(
            "Release-candidate manifest identity is invalid."
        )
    actual = normalize_release_candidate_inputs(manifest["inputs"])
    expected = normalize_release_candidate_inputs(expected_inputs)
    _verify_rc1_bindings(actual, rc1_evidence_set)
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_release_candidate_manifest",
        "schemaVersion": 1,
        "inputs": actual,
    }
    digest = _canonical_digest(unsigned)
    if manifest["manifestDigest"] != digest:
        raise ReleaseCandidateError(
            "Release-candidate manifest digest does not match its content."
        )
    if actual != expected:
        raise ReleaseCandidateError(
            "Release-candidate manifest differs from expected RC2 inputs."
        )
    return {
        "verified": True,
        "immutableCandidateIdentified": True,
        "releaseAuthorized": False,
        "manifestDigest": digest,
    }


def _verify_rc1_bindings(
    inputs: Mapping[str, Mapping[str, str]],
    rc1_evidence_set: Mapping[str, Any],
) -> None:
    try:
        evidence = verify_rc1_evidence_set(rc1_evidence_set)
    except ReleaseEvidenceError as exc:
        raise ReleaseCandidateError("RC1 evidence set is invalid.") from exc
    candidate = evidence["candidate"]
    package = evidence["receipts"]["packageSearch"]
    checks = (
        (
            inputs["evidence"]["rc1EvidenceDigest"],
            evidence["evidenceSetDigest"],
            "RC1 evidence-set",
        ),
        (
            inputs["source"]["commitDigest"],
            candidate["commitDigest"],
            "RC1 commit",
        ),
        (
            inputs["source"]["treeDigest"],
            candidate["treeDigest"],
            "RC1 tree",
        ),
        (
            inputs["evidence"]["packageProvenanceReceiptDigest"],
            package["receiptDigest"],
            "package-provenance receipt",
        ),
        (
            inputs["installedCandidate"]["installManifestDigest"],
            evidence["installedPayloadManifestDigest"],
            "installed payload manifest",
        ),
        (
            inputs["installedCandidate"]["runtimeDigest"],
            evidence["runtimeDigest"],
            "installed runtime",
        ),
    )
    for supplied, bound, label in checks:
        if supplied != bound:
            raise ReleaseCandidateError(
                f"Release-candidate {label} identity differs from RC1 evidence."
            )


def _identity(field: str, value: Any) -> str:
    pattern = _GIT_DIGEST if field in {"commitDigest", "treeDigest"} else _DIGEST
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ReleaseCandidateError(
            f"Release-candidate identity {field} is invalid."
        )
    return value


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "ReleaseCandidateError",
    "SCHEMA",
    "create_release_candidate_manifest",
    "normalize_release_candidate_inputs",
    "verify_release_candidate_manifest",
]
