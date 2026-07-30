"""Offline verification for externally authorized HS8 release artifacts.

Digests identify evidence; they never grant authority. Authority comes only
from Ed25519 signatures verified against a separately supplied trust policy
and caller-supplied expected release bindings.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


TRUST_POLICY_SCHEMA = "hocuspocus://schemas/hs8-release-trust-policy/v1"
CLEAN_IMAGE_SCHEMA = (
    "hocuspocus://schemas/hs8-external-clean-image-attestation/v1"
)
FINAL_DECISION_SCHEMA = (
    "hocuspocus://schemas/hs8-final-release-decision/v1"
)
VISUAL_APPROVAL_SCHEMA = (
    "hocuspocus://schemas/hs8-signed-visual-approval/v1"
)
CANONICALIZATION = "RFC8785"
ALGORITHM = "Ed25519"
MAX_DOCUMENT_BYTES = 256 * 1024
CLEAN_BINDING_FIELDS = (
    "candidateDigest",
    "sourceSnapshotDigest",
    "installedPayloadManifestDigest",
    "runtimeDigest",
    "environmentReceiptDigest",
    "dependencySetDigest",
    "technicalQualificationReceiptDigest",
)
FINAL_BINDING_FIELDS = (
    *CLEAN_BINDING_FIELDS,
    "visualApprovalDigest",
)
_CANDIDATE_FINAL_BINDING_PATHS = {
    "sourceSnapshotDigest": ("source", "sourceArchiveDigest"),
    "dependencySetDigest": ("execution", "dependencySetDigest"),
    "installedPayloadManifestDigest": (
        "installedCandidate",
        "installManifestDigest",
    ),
    "runtimeDigest": ("installedCandidate", "runtimeDigest"),
    "technicalQualificationReceiptDigest": (
        "evidence",
        "technicalQualificationReceiptDigest",
    ),
}
VISUAL_REVIEW_FIELDS = (
    "kind",
    "reviewVersion",
    "assetUri",
    "candidateProvenanceManifestDigest",
    "candidateOutputSetDigest",
    "visualComparisonDigest",
    "candidateVersionId",
    "reviewPolicyId",
    "reviewerPrincipalId",
    "decision",
    "notesDigest",
)
VISUAL_REQUEST_FIELDS = (
    "$schema",
    "kind",
    "reviewVersion",
    "assetUri",
    "candidateProvenanceManifestDigest",
    "candidateOutputSetDigest",
    "visualComparisonDigest",
    "candidateVersionId",
    "reviewPolicyId",
    "baselineFile",
    "baselineDigest",
    "decision",
)
VISUAL_SHARED_FIELDS = (
    "assetUri",
    "candidateProvenanceManifestDigest",
    "candidateOutputSetDigest",
    "visualComparisonDigest",
    "candidateVersionId",
    "reviewPolicyId",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_ASSET_URI = re.compile(r"^hocus-asset://[a-z0-9][a-z0-9._/-]{0,255}$")
_PORTABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REVIEWER = re.compile(
    r"^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
    r"hprincipal_[0-9a-f]{32}|sha256:[0-9a-f]{64})$"
)
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


class ReleaseAuthorityError(ValueError):
    """Malformed, mismatched, expired, or unauthenticated release evidence."""


def decode_json_document(content: bytes | str, *, label: str) -> dict[str, Any]:
    """Decode one bounded JSON object while rejecting duplicate object keys."""

    encoded = content.encode("utf-8") if isinstance(content, str) else content
    if not isinstance(encoded, bytes) or len(encoded) > MAX_DOCUMENT_BYTES:
        raise ReleaseAuthorityError(f"{label} is missing or unbounded.")
    try:
        text = encoded.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseAuthorityError(f"{label} is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ReleaseAuthorityError(f"{label} must be a JSON object.")
    _assert_canonical_domain(value, label)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 bytes for the deliberately scalar-only ASCII profile."""

    _assert_canonical_domain(value, "Canonical JSON value")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReleaseAuthorityError("Value cannot be canonicalized.") from exc


def policy_digest(policy: Mapping[str, Any]) -> str:
    """Identify an exact trust policy without treating its digest as authority."""

    normalized = _normalize_policy(policy)
    return _digest(canonical_json_bytes(normalized))


def signed_artifact_digest(artifact: Mapping[str, Any]) -> str:
    """Identify the complete signed artifact, including all signatures."""

    return _digest(canonical_json_bytes(dict(artifact)))


def normalize_visual_review_request(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Strict-decode the exact frozen visual-review request contract."""

    if not isinstance(value, Mapping) or set(value) != set(VISUAL_REQUEST_FIELDS):
        raise ReleaseAuthorityError("Visual review request has invalid fields.")
    if (
        value["$schema"]
        != "hocuspocus://schemas/visual-review-request/v1"
        or value["kind"] != "hocus_visual_version_review_request"
        or type(value["reviewVersion"]) is not int
        or value["reviewVersion"] != 1
        or value["baselineFile"] != "baseline-contact-sheet.png"
        or value["decision"] != "review_pending"
    ):
        raise ReleaseAuthorityError("Visual review request identity is invalid.")
    _visual_shared(value, "Visual review request")
    _digest_value(value["baselineDigest"], "Visual review baselineDigest")
    return dict(value)


def verify_release_candidate_review_binding(
    release_candidate_manifest: Mapping[str, Any],
    expected_candidate_inputs: Mapping[str, Any],
    rc1_evidence_set: Mapping[str, Any],
    expected_review_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a strict review request to one independently verified candidate."""

    request = normalize_visual_review_request(expected_review_request)
    try:
        from .release_candidate import (
            ReleaseCandidateError,
            verify_release_candidate_manifest,
        )
    except ImportError as exc:
        raise ReleaseAuthorityError(
            "Release-candidate verifier is unavailable."
        ) from exc
    try:
        verified = verify_release_candidate_manifest(
            release_candidate_manifest,
            expected_candidate_inputs,
            rc1_evidence_set,
        )
    except ReleaseCandidateError as exc:
        raise ReleaseAuthorityError(
            "Release-candidate manifest verification failed."
        ) from exc
    request_digest = _digest(canonical_json_bytes(request))
    manifest_request_digest = release_candidate_manifest["inputs"][
        "releaseAssets"
    ]["reviewRequestDigest"]
    if manifest_request_digest != request_digest:
        raise ReleaseAuthorityError(
            "Visual review request is not bound by the verified candidate."
        )
    return {
        **verified,
        "reviewRequestDigest": request_digest,
    }


def signature_message(artifact: Mapping[str, Any]) -> bytes:
    """Return the domain-separated unsigned envelope bytes signers must sign."""

    fields = {"$schema", "kind", "schemaVersion", "payload", "signatures"}
    if not isinstance(artifact, Mapping) or set(artifact) != fields:
        raise ReleaseAuthorityError("Signed artifact has an invalid envelope.")
    unsigned = {
        "$schema": artifact["$schema"],
        "kind": artifact["kind"],
        "schemaVersion": artifact["schemaVersion"],
        "payload": artifact["payload"],
    }
    return b"HocusPocus-HS8-Release-Authority-v1\x00" + canonical_json_bytes(
        unsigned
    )


def verify_clean_image_attestation(
    artifact: Mapping[str, Any],
    trust_policy: Mapping[str, Any],
    expected_clean_bindings: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Authenticate clean-image authority for one exact external candidate."""

    policy = _normalize_policy(trust_policy)
    expected = _normalize_bindings(
        expected_clean_bindings,
        CLEAN_BINDING_FIELDS,
        "Expected clean-image bindings",
    )
    normalized = _normalize_clean_image(artifact)
    current = _utc_now(now)
    _verify_common_payload(
        normalized["payload"],
        policy,
        expected,
        CLEAN_BINDING_FIELDS,
        current,
    )
    signers = _verify_role_signatures(
        normalized,
        policy["roles"]["cleanImageAttestor"],
        current,
    )
    return {
        "verified": True,
        "cleanImageCertified": True,
        "releaseAuthorized": False,
        "artifactDigest": signed_artifact_digest(normalized),
        "signerKeyIds": [item["keyId"] for item in signers],
        "signerPrincipalIds": [item["principalId"] for item in signers],
    }


def verify_visual_approval(
    artifact: Mapping[str, Any],
    trust_policy: Mapping[str, Any],
    expected_review_request: Mapping[str, Any],
    expected_review_evidence: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Authenticate one exact visual approval against request and evidence."""

    policy = _normalize_policy(trust_policy)
    request = normalize_visual_review_request(expected_review_request)
    request_digest = _digest(canonical_json_bytes(request))
    evidence = _normalize_visual_review_evidence(expected_review_evidence)
    _verify_visual_request_evidence(request, evidence)
    normalized = _normalize_visual_approval(artifact)
    payload = normalized["payload"]
    current = _utc_now(now)
    _verify_common_authority(payload, policy, current)
    if (
        payload["reviewRequestDigest"] != request_digest
        or payload["reviewEvidence"] != evidence
        or payload["reviewEvidenceDigest"]
        != _digest(canonical_json_bytes(evidence))
    ):
        raise ReleaseAuthorityError(
            "Visual approval does not bind the exact review request and evidence."
        )
    signers = _verify_role_signatures(
        normalized,
        policy["roles"]["visualReviewer"],
        current,
    )
    signer_principals = {item["principalId"] for item in signers}
    if evidence["reviewerPrincipalId"] not in signer_principals:
        raise ReleaseAuthorityError(
            "Visual approval reviewer is not a verified signer principal."
        )
    return {
        "verified": True,
        "visualApproved": evidence["decision"] == "approved",
        "releaseAuthorized": False,
        "artifactDigest": signed_artifact_digest(normalized),
        "reviewRequestDigest": request_digest,
        "reviewEvidenceDigest": payload["reviewEvidenceDigest"],
        "reviewEvidence": evidence,
        "issuedAt": payload["issuedAt"],
        "signerKeyIds": [item["keyId"] for item in signers],
        "signerPrincipalIds": [item["principalId"] for item in signers],
    }


def verify_final_release_decision(
    clean_image_attestation: Mapping[str, Any],
    visual_approval: Mapping[str, Any],
    final_decision: Mapping[str, Any],
    trust_policy: Mapping[str, Any],
    expected_final_bindings: Mapping[str, Any],
    *,
    expected_review_request: Mapping[str, Any],
    expected_review_evidence: Mapping[str, Any],
    release_candidate_manifest: Mapping[str, Any],
    expected_candidate_inputs: Mapping[str, Any],
    rc1_evidence_set: Mapping[str, Any],
    expected_release_channel: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify both external roles and return the only release-authority result."""

    policy = _normalize_policy(trust_policy)
    expected_final = _normalize_bindings(
        expected_final_bindings,
        FINAL_BINDING_FIELDS,
        "Expected final bindings",
    )
    expected_clean = {
        field: expected_final[field] for field in CLEAN_BINDING_FIELDS
    }
    candidate = verify_release_candidate_review_binding(
        release_candidate_manifest,
        expected_candidate_inputs,
        rc1_evidence_set,
        expected_review_request,
    )
    _verify_candidate_final_bindings(
        expected_final,
        release_candidate_manifest,
        candidate["manifestDigest"],
    )
    current = _utc_now(now)
    clean = _normalize_clean_image(clean_image_attestation)
    _verify_common_payload(
        clean["payload"],
        policy,
        expected_clean,
        CLEAN_BINDING_FIELDS,
        current,
    )
    clean_signers = _verify_role_signatures(
        clean,
        policy["roles"]["cleanImageAttestor"],
        current,
    )
    visual = _normalize_visual_approval(visual_approval)
    visual_result = verify_visual_approval(
        visual,
        policy,
        expected_review_request,
        expected_review_evidence,
        now=current,
    )
    visual_digest = signed_artifact_digest(visual)
    if expected_final["visualApprovalDigest"] != visual_digest:
        raise ReleaseAuthorityError(
            "Expected final bindings do not identify the signed visual approval."
        )
    decision = _normalize_final_decision(final_decision)
    _verify_common_payload(
        decision["payload"],
        policy,
        expected_final,
        FINAL_BINDING_FIELDS,
        current,
    )
    final_base = {
        field: decision["payload"]["bindings"][field]
        for field in CLEAN_BINDING_FIELDS
    }
    if final_base != dict(clean["payload"]["bindings"]):
        raise ReleaseAuthorityError(
            "Final decision candidate bindings differ from clean-image evidence."
        )
    clean_digest = signed_artifact_digest(clean)
    if decision["payload"]["cleanImageAttestationDigest"] != clean_digest:
        raise ReleaseAuthorityError(
            "Final decision does not bind the exact clean-image attestation."
        )
    clean_issued = _timestamp(clean["payload"]["issuedAt"], "Clean issuedAt")
    visual_issued = _timestamp(visual["payload"]["issuedAt"], "Visual issuedAt")
    decision_issued = _timestamp(
        decision["payload"]["issuedAt"], "Decision issuedAt",
    )
    if not clean_issued <= visual_issued <= decision_issued:
        raise ReleaseAuthorityError(
            "Release authority chronology must be clean-image, visual, decision."
        )
    _identifier(expected_release_channel, "Expected release channel")
    if decision["payload"]["releaseChannel"] != expected_release_channel:
        raise ReleaseAuthorityError("Final decision release channel mismatches.")
    release_signers = _verify_role_signatures(
        decision,
        policy["roles"]["releaseDecisionAuthority"],
        current,
    )
    visual_signers = [
        key
        for key in policy["roles"]["visualReviewer"]["keys"]
        if key["keyId"] in visual_result["signerKeyIds"]
    ]
    _verify_separation(clean_signers, visual_signers, release_signers, policy)
    approved = decision["payload"]["decision"] == "approved"
    return {
        "verified": True,
        "cleanImageCertified": True,
        "releaseAuthorized": approved,
        "decision": decision["payload"]["decision"],
        "cleanImageAttestationDigest": clean_digest,
        "visualApprovalDigest": visual_digest,
        "finalDecisionDigest": signed_artifact_digest(decision),
        "cleanImageSignerPrincipalIds": [
            item["principalId"] for item in clean_signers
        ],
        "releaseSignerPrincipalIds": [
            item["principalId"] for item in release_signers
        ],
        "visualReviewerPrincipalIds": visual_result["signerPrincipalIds"],
    }


def _verify_candidate_final_bindings(
    final_bindings: Mapping[str, str],
    release_candidate_manifest: Mapping[str, Any],
    candidate_digest: str,
) -> None:
    """Require every duplicated final identity to project from the candidate."""

    candidate_inputs = release_candidate_manifest["inputs"]
    projected = {"candidateDigest": candidate_digest}
    for field, (section, candidate_field) in (
        _CANDIDATE_FINAL_BINDING_PATHS.items()
    ):
        projected[field] = candidate_inputs[section][candidate_field]
    mismatched = [
        field
        for field, candidate_value in projected.items()
        if final_bindings[field] != candidate_value
    ]
    if mismatched:
        raise ReleaseAuthorityError(
            "Final bindings differ from the verified release candidate: "
            + ", ".join(sorted(mismatched))
            + "."
        )


def _normalize_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "$schema",
        "kind",
        "schemaVersion",
        "policyId",
        "requireDistinctPrincipals",
        "roles",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseAuthorityError("Trust policy has an invalid envelope.")
    if (
        value["$schema"] != TRUST_POLICY_SCHEMA
        or value["kind"] != "hocus_hs8_release_trust_policy"
        or isinstance(value["schemaVersion"], bool)
        or value["schemaVersion"] != 1
        or value["requireDistinctPrincipals"] is not True
    ):
        raise ReleaseAuthorityError("Trust policy identity is invalid.")
    _identifier(value["policyId"], "Trust policy ID")
    roles = value["roles"]
    expected_roles = {
        "cleanImageAttestor",
        "releaseDecisionAuthority",
        "visualReviewer",
    }
    if not isinstance(roles, Mapping) or set(roles) != expected_roles:
        raise ReleaseAuthorityError("Trust policy roles are invalid.")
    normalized_roles = {
        role: _normalize_role(roles[role], role)
        for role in sorted(expected_roles)
    }
    principal_sets = [
        _role_principals(normalized_roles[role])
        for role in sorted(expected_roles)
    ]
    if any(
        left & right
        for index, left in enumerate(principal_sets)
        for right in principal_sets[index + 1:]
    ):
        raise ReleaseAuthorityError(
            "Trust policy roles must use distinct principals."
        )
    public_keys = [
        _base64url(key["publicKey"], 32, "Signer public key")
        for role in normalized_roles.values()
        for key in role["keys"]
    ]
    if len(public_keys) != len(set(public_keys)):
        raise ReleaseAuthorityError(
            "Trust policy Ed25519 public keys must be globally unique."
        )
    return {
        "$schema": TRUST_POLICY_SCHEMA,
        "kind": "hocus_hs8_release_trust_policy",
        "schemaVersion": 1,
        "policyId": value["policyId"],
        "requireDistinctPrincipals": True,
        "roles": normalized_roles,
    }


def _normalize_role(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "minimumSignatures",
        "keys",
    }:
        raise ReleaseAuthorityError(f"Trust policy role {label} is invalid.")
    minimum = value["minimumSignatures"]
    keys = value["keys"]
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 1
        or minimum > 8
        or not isinstance(keys, list)
        or not 1 <= len(keys) <= 8
        or minimum > len(keys)
    ):
        raise ReleaseAuthorityError(f"Trust policy role {label} is unbounded.")
    normalized = [_normalize_key(item, label) for item in keys]
    key_ids = [item["keyId"] for item in normalized]
    if key_ids != sorted(set(key_ids)):
        raise ReleaseAuthorityError(
            f"Trust policy role {label} keys must be uniquely sorted."
        )
    principals = [item["principalId"] for item in normalized]
    if len(principals) != len(set(principals)):
        raise ReleaseAuthorityError(
            f"Trust policy role {label} principals must be unique."
        )
    return {"minimumSignatures": minimum, "keys": normalized}


def _normalize_key(value: Any, role: str) -> dict[str, Any]:
    fields = {
        "keyId",
        "principalId",
        "algorithm",
        "publicKey",
        "notBefore",
        "notAfter",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseAuthorityError(f"Trust policy key for {role} is invalid.")
    _identifier(value["keyId"], "Signer key ID")
    _identifier(value["principalId"], "Signer principal ID")
    if value["algorithm"] != ALGORITHM:
        raise ReleaseAuthorityError("Only Ed25519 signer keys are accepted.")
    _base64url(value["publicKey"], 32, "Signer public key")
    before = _timestamp(value["notBefore"], "Signer notBefore")
    after = _timestamp(value["notAfter"], "Signer notAfter")
    if before >= after:
        raise ReleaseAuthorityError("Signer key validity window is invalid.")
    return dict(value)


def _normalize_clean_image(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_artifact(
        value,
        schema=CLEAN_IMAGE_SCHEMA,
        kind="hocus_hs8_external_clean_image_attestation",
    )
    payload = normalized["payload"]
    expected = {
        "authorityRole",
        "canonicalization",
        "trustPolicy",
        "bindings",
        "isolationBoundary",
        "ephemeral",
        "result",
        "issuedAt",
        "expiresAt",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ReleaseAuthorityError("Clean-image payload has invalid fields.")
    if (
        payload["authorityRole"] != "clean_image_attestor"
        or payload["canonicalization"] != CANONICALIZATION
        or payload["isolationBoundary"] != "clean_image_or_vm"
        or payload["ephemeral"] is not True
        or payload["result"] != "passed"
    ):
        raise ReleaseAuthorityError("Clean-image statement is invalid.")
    _normalize_payload_common(payload, CLEAN_BINDING_FIELDS)
    return normalized


def _normalize_final_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_artifact(
        value,
        schema=FINAL_DECISION_SCHEMA,
        kind="hocus_hs8_final_release_decision",
    )
    payload = normalized["payload"]
    expected = {
        "authorityRole",
        "canonicalization",
        "trustPolicy",
        "bindings",
        "cleanImageAttestationDigest",
        "releaseChannel",
        "decision",
        "issuedAt",
        "expiresAt",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ReleaseAuthorityError("Final decision payload has invalid fields.")
    if (
        payload["authorityRole"] != "release_decision_authority"
        or payload["canonicalization"] != CANONICALIZATION
        or payload["decision"] not in {"approved", "rejected"}
    ):
        raise ReleaseAuthorityError("Final release statement is invalid.")
    _digest_value(
        payload["cleanImageAttestationDigest"],
        "Clean-image attestation digest",
    )
    _identifier(payload["releaseChannel"], "Release channel")
    _normalize_payload_common(payload, FINAL_BINDING_FIELDS)
    return normalized


def _normalize_visual_approval(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_artifact(
        value,
        schema=VISUAL_APPROVAL_SCHEMA,
        kind="hocus_hs8_signed_visual_approval",
    )
    payload = normalized["payload"]
    expected = {
        "authorityRole",
        "canonicalization",
        "trustPolicy",
        "reviewRequestDigest",
        "reviewEvidenceDigest",
        "reviewEvidence",
        "issuedAt",
        "expiresAt",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ReleaseAuthorityError("Visual approval payload has invalid fields.")
    if (
        payload["authorityRole"] != "visual_reviewer"
        or payload["canonicalization"] != CANONICALIZATION
    ):
        raise ReleaseAuthorityError("Visual approval statement is invalid.")
    _digest_value(payload["reviewRequestDigest"], "Review request digest")
    _digest_value(payload["reviewEvidenceDigest"], "Review evidence digest")
    evidence = _normalize_visual_review_evidence(payload["reviewEvidence"])
    if payload["reviewEvidenceDigest"] != _digest(canonical_json_bytes(evidence)):
        raise ReleaseAuthorityError("Visual approval evidence digest is invalid.")
    normalized["payload"] = dict(payload)
    normalized["payload"]["reviewEvidence"] = evidence
    _normalize_payload_authority(payload)
    return normalized


def _normalize_visual_review_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(VISUAL_REVIEW_FIELDS):
        raise ReleaseAuthorityError("Visual review evidence has invalid fields.")
    if (
        value["kind"] != "hocus_visual_version_review_evidence"
        or value["reviewVersion"] != 1
        or isinstance(value["reviewVersion"], bool)
        or value["decision"] != "approved"
    ):
        raise ReleaseAuthorityError("Visual review evidence is not an approval.")
    _visual_shared(value, "Visual review")
    if (
        not isinstance(value["reviewerPrincipalId"], str)
        or _REVIEWER.fullmatch(value["reviewerPrincipalId"]) is None
    ):
        raise ReleaseAuthorityError("Visual review reviewerPrincipalId is invalid.")
    notes = value["notesDigest"]
    if notes is not None:
        _digest_value(notes, "Visual review notesDigest")
    return dict(value)


def _visual_shared(value: Mapping[str, Any], label: str) -> None:
    if (
        not isinstance(value["assetUri"], str)
        or _ASSET_URI.fullmatch(value["assetUri"]) is None
    ):
        raise ReleaseAuthorityError(f"{label} assetUri is invalid.")
    for field in (
        "candidateProvenanceManifestDigest",
        "candidateOutputSetDigest",
        "visualComparisonDigest",
    ):
        _digest_value(value[field], f"{label} {field}")
    for field in ("candidateVersionId", "reviewPolicyId"):
        if (
            not isinstance(value[field], str)
            or _PORTABLE_ID.fullmatch(value[field]) is None
        ):
            raise ReleaseAuthorityError(f"{label} {field} is invalid.")


def _verify_visual_request_evidence(
    request: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    mismatched = [
        field
        for field in VISUAL_SHARED_FIELDS
        if request[field] != evidence[field]
    ]
    if mismatched:
        raise ReleaseAuthorityError(
            "Visual review evidence differs from request field "
            + mismatched[0]
            + "."
        )


def _normalize_artifact(
    value: Mapping[str, Any],
    *,
    schema: str,
    kind: str,
) -> dict[str, Any]:
    fields = {"$schema", "kind", "schemaVersion", "payload", "signatures"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseAuthorityError("Signed artifact has an invalid envelope.")
    if (
        value["$schema"] != schema
        or value["kind"] != kind
        or isinstance(value["schemaVersion"], bool)
        or value["schemaVersion"] != 1
    ):
        raise ReleaseAuthorityError("Signed artifact identity is invalid.")
    signatures = value["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 8:
        raise ReleaseAuthorityError("Signed artifact signatures are unbounded.")
    normalized_signatures = [_normalize_signature(item) for item in signatures]
    key_ids = [item["keyId"] for item in normalized_signatures]
    if key_ids != sorted(set(key_ids)):
        raise ReleaseAuthorityError(
            "Signed artifact signatures must be uniquely sorted."
        )
    normalized = dict(value)
    normalized["payload"] = dict(value["payload"]) if isinstance(
        value["payload"], Mapping
    ) else value["payload"]
    normalized["signatures"] = normalized_signatures
    _assert_canonical_domain(normalized, "Signed artifact")
    return normalized


def _normalize_signature(value: Any) -> dict[str, Any]:
    fields = {"keyId", "algorithm", "signature"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseAuthorityError("Signature record has invalid fields.")
    _identifier(value["keyId"], "Signature key ID")
    if value["algorithm"] != ALGORITHM:
        raise ReleaseAuthorityError("Only Ed25519 signatures are accepted.")
    _base64url(value["signature"], 64, "Ed25519 signature")
    return dict(value)


def _normalize_payload_common(
    payload: Mapping[str, Any],
    binding_fields: Sequence[str],
) -> None:
    _normalize_payload_authority(payload)
    _normalize_bindings(
        payload["bindings"],
        binding_fields,
        "Artifact bindings",
    )


def _normalize_payload_authority(payload: Mapping[str, Any]) -> None:
    policy = payload["trustPolicy"]
    if not isinstance(policy, Mapping) or set(policy) != {
        "policyId",
        "policyDigest",
    }:
        raise ReleaseAuthorityError("Artifact trust-policy binding is invalid.")
    _identifier(policy["policyId"], "Artifact trust policy ID")
    _digest_value(policy["policyDigest"], "Artifact trust policy digest")
    issued = _timestamp(payload["issuedAt"], "Artifact issuedAt")
    expires = _timestamp(payload["expiresAt"], "Artifact expiresAt")
    if issued >= expires:
        raise ReleaseAuthorityError("Artifact validity window is invalid.")


def _normalize_bindings(
    value: Any,
    fields: Sequence[str],
    label: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ReleaseAuthorityError(f"{label} has invalid fields.")
    normalized = {}
    for field in fields:
        _digest_value(value[field], f"{label}.{field}")
        normalized[field] = value[field]
    return normalized


def _verify_common_payload(
    payload: Mapping[str, Any],
    policy: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
    binding_fields: Sequence[str],
    now: datetime,
) -> None:
    _verify_common_authority(payload, policy, now)
    actual_bindings = _normalize_bindings(
        payload["bindings"],
        binding_fields,
        "Artifact bindings",
    )
    if actual_bindings != dict(expected_bindings):
        raise ReleaseAuthorityError(
            "Artifact does not bind the independently expected release identity."
        )


def _verify_common_authority(
    payload: Mapping[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> None:
    binding = payload["trustPolicy"]
    if (
        binding["policyId"] != policy["policyId"]
        or binding["policyDigest"] != policy_digest(policy)
    ):
        raise ReleaseAuthorityError(
            "Artifact does not bind the supplied external trust policy."
        )
    issued = _timestamp(payload["issuedAt"], "Artifact issuedAt")
    expires = _timestamp(payload["expiresAt"], "Artifact expiresAt")
    if now < issued or now > expires:
        raise ReleaseAuthorityError("Signed artifact is not currently valid.")


def _verify_role_signatures(
    artifact: Mapping[str, Any],
    role: Mapping[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    keys = {item["keyId"]: item for item in role["keys"]}
    verified = []
    verified_material: set[bytes] = set()
    message = signature_message(artifact)
    issued = _timestamp(artifact["payload"]["issuedAt"], "Artifact issuedAt")
    for signature in artifact["signatures"]:
        key = keys.get(signature["keyId"])
        if key is None:
            raise ReleaseAuthorityError("Signature key is not trusted for this role.")
        _verify_key_time(key, issued, now)
        _verify_ed25519(key["publicKey"], signature["signature"], message)
        verified.append(key)
        verified_material.add(
            _base64url(key["publicKey"], 32, "Signer public key")
        )
    if len(verified_material) < role["minimumSignatures"]:
        raise ReleaseAuthorityError("Role signature threshold was not satisfied.")
    return verified


def _verify_key_time(
    key: Mapping[str, Any],
    issued: datetime,
    now: datetime,
) -> None:
    before = _timestamp(key["notBefore"], "Signer notBefore")
    after = _timestamp(key["notAfter"], "Signer notAfter")
    if issued < before or issued > after:
        raise ReleaseAuthorityError(
            "Signer key was not trusted at artifact issuance."
        )
    if now < before or now > after:
        raise ReleaseAuthorityError("Signer key is not currently trusted.")


def _verify_ed25519(public: str, signature: str, message: bytes) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise ReleaseAuthorityError(
            "Ed25519 verification requires the cryptography package."
        ) from exc
    try:
        key = Ed25519PublicKey.from_public_bytes(
            _base64url(public, 32, "Signer public key")
        )
        key.verify(_base64url(signature, 64, "Ed25519 signature"), message)
    except (InvalidSignature, ValueError) as exc:
        raise ReleaseAuthorityError("Ed25519 signature verification failed.") from exc


def _verify_separation(
    clean_signers: Sequence[Mapping[str, Any]],
    visual_signers: Sequence[Mapping[str, Any]],
    release_signers: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> None:
    if policy["requireDistinctPrincipals"] is not True:
        raise ReleaseAuthorityError("Signer separation policy is not enabled.")
    clean = {item["principalId"] for item in clean_signers}
    visual = {item["principalId"] for item in visual_signers}
    release = {item["principalId"] for item in release_signers}
    if clean & visual or clean & release or visual & release:
        raise ReleaseAuthorityError(
            "Clean-image, visual, and release roles require distinct principals."
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseAuthorityError(f"Duplicate JSON field is forbidden: {key}.")
        result[key] = value
    return result


def _assert_canonical_domain(value: Any, label: str) -> None:
    if isinstance(value, float):
        raise ReleaseAuthorityError(f"{label} contains a forbidden JSON value.")
    if value is None:
        return
    if isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, str):
        if not value.isascii():
            raise ReleaseAuthorityError(f"{label} must use ASCII strings.")
        return
    if isinstance(value, list):
        for item in value:
            _assert_canonical_domain(item, label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                raise ReleaseAuthorityError(f"{label} has an invalid JSON key.")
            _assert_canonical_domain(item, label)
        return
    raise ReleaseAuthorityError(f"{label} contains a non-JSON value.")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ReleaseAuthorityError(f"{label} is invalid.")
    return value


def _digest_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ReleaseAuthorityError(f"{label} is invalid.")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise ReleaseAuthorityError(f"{label} is invalid.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ReleaseAuthorityError(f"{label} is invalid.") from exc


def _base64url(value: Any, size: int, label: str) -> bytes:
    if not isinstance(value, str) or "=" in value:
        raise ReleaseAuthorityError(f"{label} is invalid.")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ReleaseAuthorityError(f"{label} is invalid.") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if len(decoded) != size or canonical != value:
        raise ReleaseAuthorityError(f"{label} is invalid.")
    return decoded


def _utc_now(value: datetime | None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if current.tzinfo is None:
        raise ReleaseAuthorityError("Verification time must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _role_principals(role: Mapping[str, Any]) -> set[str]:
    return {item["principalId"] for item in role["keys"]}


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "ALGORITHM",
    "CANONICALIZATION",
    "CLEAN_BINDING_FIELDS",
    "CLEAN_IMAGE_SCHEMA",
    "FINAL_BINDING_FIELDS",
    "FINAL_DECISION_SCHEMA",
    "ReleaseAuthorityError",
    "TRUST_POLICY_SCHEMA",
    "VISUAL_APPROVAL_SCHEMA",
    "VISUAL_REVIEW_FIELDS",
    "VISUAL_REQUEST_FIELDS",
    "VISUAL_SHARED_FIELDS",
    "canonical_json_bytes",
    "decode_json_document",
    "normalize_visual_review_request",
    "policy_digest",
    "signature_message",
    "signed_artifact_digest",
    "verify_clean_image_attestation",
    "verify_final_release_decision",
    "verify_release_candidate_review_binding",
    "verify_visual_approval",
]
