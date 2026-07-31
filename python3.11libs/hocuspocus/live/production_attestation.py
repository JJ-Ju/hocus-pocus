"""Direct host-context authority for HS8 production evidence.

There is no caller-supplied attestation carrier. When an MCP request already
has production-review authority, this module binds the exact evidence to that
authenticated host context during the qualification call itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any, Mapping

from hocuspocus.core.policy import REVIEW_PRODUCTION
from hocuspocus.hocusscript.build_provenance import canonical_digest
from hocuspocus.hocusscript.production_pipeline import (
    PRODUCTION_EVIDENCE_FIELDS,
    production_evidence_digest,
    production_qualification_authority_digest,
)

from .context import RequestContext


ATTESTATION_KIND = "hocus_host_context_attestation"
ATTESTATION_VERSION = 1
_PORTABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REVIEWER_ID = re.compile(
    r"^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
    r"hprincipal_[0-9a-f]{32}|"
    r"sha256:[0-9a-f]{64})$"
)
_REVIEW_FIELDS = {
    "kind", "reviewVersion", "assetUri",
    "candidateProvenanceManifestDigest", "candidateOutputSetDigest",
    "visualComparisonDigest", "candidateVersionId", "reviewPolicyId",
    "reviewerPrincipalId", "decision", "notesDigest",
}


class ProductionAttestationError(ValueError):
    """Typed rejection at the host evidence-authority boundary."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code = "HOCUS991"
        self.details: dict[str, Any] = {}


class ProductionEvidenceAttestor:
    """Create an opaque digest for an authorized, in-context host decision."""

    def __init__(self) -> None:
        self.__secret = secrets.token_bytes(32)

    def attest(
        self,
        evidence: Mapping[str, Any],
        context: RequestContext,
        qualification: Mapping[str, Any],
    ) -> str:
        """Authorize and attest exact evidence in the current host request."""

        _authorize_visual_version_review(evidence, context)
        body = {
            "kind": ATTESTATION_KIND,
            "attestationVersion": ATTESTATION_VERSION,
            "evidenceDigest": production_evidence_digest(evidence),
            "contextDigest": _context_digest(context),
            "qualificationContentDigest": (
                production_qualification_authority_digest(qualification)
            ),
        }
        mac = hmac.new(
            self.__secret,
            _canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return canonical_digest({**body, "mac": "hmac-sha256:" + mac})

    def verify(
        self,
        evidence: Mapping[str, Any],
        context: RequestContext,
        qualification: Mapping[str, Any],
        attestation_digest: str,
    ) -> bool:
        """Verify an opaque digest against exact evidence and host context."""

        if not isinstance(attestation_digest, str):
            return False
        expected = self.attest(evidence, context, qualification)
        return hmac.compare_digest(expected, attestation_digest)


def _context_digest(context: RequestContext) -> str:
    if not isinstance(context, RequestContext):
        raise ProductionAttestationError("Host attestation requires a request context.")
    principal = _bounded(context.principal_id, "principal")
    session = _bounded(context.session_id, "session")
    caller = _bounded(context.caller_id, "caller")
    if not isinstance(context.permissions, (tuple, list)) or len(context.permissions) > 64:
        raise ProductionAttestationError("Host policy permission set is too large.")
    permissions = sorted({
        _bounded(permission, "permission", maximum=128)
        for permission in context.permissions
    })
    if not isinstance(context.metadata, dict):
        raise ProductionAttestationError("Host policy metadata is invalid.")
    revision = _bounded(
        context.metadata.get("policy_revision", "runtime"),
        "policy revision",
        maximum=128,
    )
    review_policy = _bounded(
        context.metadata.get("production_review_policy_id"),
        "production review policy",
        maximum=128,
    )
    return canonical_digest({
        "principalId": principal,
        "sessionId": session,
        "callerId": caller,
        "permissions": permissions,
        "policyRevision": revision,
        "productionReviewPolicyId": review_policy,
    })


def _authorize_visual_version_review(
    evidence: Mapping[str, Any],
    context: RequestContext,
) -> None:
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != set(PRODUCTION_EVIDENCE_FIELDS)
    ):
        raise ProductionAttestationError(
            "Host attestation requires the exact production evidence envelope."
        )
    review = evidence.get("visualVersionReviewEvidence")
    if not isinstance(review, Mapping) or set(review) != _REVIEW_FIELDS:
        raise ProductionAttestationError(
            "Host attestation requires explicit visual version review evidence."
        )
    if not isinstance(context, RequestContext) or not isinstance(
        context.metadata, dict,
    ):
        raise ProductionAttestationError(
            "Host attestation requires authenticated review context."
        )
    if REVIEW_PRODUCTION not in context.permissions:
        raise ProductionAttestationError(
            "Host attestation requires production-review authority."
        )
    reviewer = _bounded(review.get("reviewerPrincipalId"), "reviewer principal")
    principal = _bounded(context.principal_id, "principal")
    review_policy = _bounded(review.get("reviewPolicyId"), "review policy")
    authorized_policy = _bounded(
        context.metadata.get("production_review_policy_id"),
        "production review policy",
        maximum=128,
    )
    if (
        _REVIEWER_ID.fullmatch(reviewer) is None
        or _REVIEWER_ID.fullmatch(principal) is None
        or _PORTABLE_ID.fullmatch(review_policy) is None
        or _PORTABLE_ID.fullmatch(authorized_policy) is None
        or reviewer != principal
        or review_policy != authorized_policy
        or review.get("decision") != "approved"
    ):
        raise ProductionAttestationError(
            "Visual version review principal, policy, or decision is not host-authorized."
        )


def _bounded(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ProductionAttestationError(
            f"Host attestation {label} identity is invalid."
        )
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ProductionAttestationError(
            "Host evidence attestation contains invalid JSON."
        ) from exc


__all__ = [
    "ATTESTATION_KIND",
    "ATTESTATION_VERSION",
    "ProductionAttestationError",
    "ProductionEvidenceAttestor",
]
