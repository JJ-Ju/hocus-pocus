"""Strict detached visual-review ingestion for private HS8 release runners."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping


MAX_REVIEW_BYTES = 16 * 1024
REQUEST_RELATIVE_PATH = "scripts/fixtures/hs8/visual-review-request.json"
BASELINE_RELATIVE_PATH = "scripts/fixtures/hs8/baseline-contact-sheet.png"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ASSET_URI = re.compile(r"^hocus-asset://[a-z0-9][a-z0-9._/-]{0,255}$")
_REVIEWER = re.compile(
    r"^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
    r"hprincipal_[0-9a-f]{32}|sha256:[0-9a-f]{64})$"
)
_SHARED_FIELDS = (
    "assetUri",
    "candidateProvenanceManifestDigest",
    "candidateOutputSetDigest",
    "visualComparisonDigest",
    "candidateVersionId",
    "reviewPolicyId",
)


class VisualReviewError(ValueError):
    """Detached approval is missing, malformed, unsafe, or mismatched."""


def select_detached_visual_review(
    path: Path | None,
    *,
    trust_policy: Path | None,
    installed_root: Path,
    source_root: Path,
    mode: str,
) -> dict[str, str] | None:
    """Enforce mode semantics before ingesting an external approval."""

    if mode == "technical":
        if path is not None or trust_policy is not None:
            raise VisualReviewError(
                "Technical mode does not accept visual approval authority."
            )
        return None
    if mode != "release" or path is None or trust_policy is None:
        raise VisualReviewError(
            "Release mode requires --visual-review and --trust-policy."
        )
    return load_detached_visual_review(
        path,
        trust_policy=trust_policy,
        installed_root=installed_root,
        forbidden_roots=(source_root, installed_root),
    )


def load_detached_visual_review(
    path: Path,
    *,
    trust_policy: Path,
    installed_root: Path,
    forbidden_roots: Iterable[Path],
) -> dict[str, str]:
    """Read and bind one external approval to the installed frozen request."""

    selected = _external_file(path, forbidden_roots)
    authority = _authority_module(installed_root)
    request_path = installed_root.resolve(strict=True) / REQUEST_RELATIVE_PATH
    try:
        request = authority.normalize_visual_review_request(
            _read_json(request_path, "Visual review request")
        )
    except authority.ReleaseAuthorityError as exc:
        raise VisualReviewError(str(exc)) from exc
    baseline_path = installed_root.resolve(strict=True) / BASELINE_RELATIVE_PATH
    if (
        not baseline_path.is_file()
        or baseline_path.stat().st_size > 32 * 1024 * 1024
        or _digest(baseline_path.read_bytes()) != request["baselineDigest"]
    ):
        raise VisualReviewError(
            "Visual review request does not bind the installed baseline."
        )
    policy_path = _external_file(trust_policy, forbidden_roots)
    approval = _read_json(selected, "Signed visual approval")
    policy = _read_json(policy_path, "Visual-review trust policy")
    payload = approval.get("payload")
    review = _review(
        payload.get("reviewEvidence")
        if isinstance(payload, Mapping) else None
    )
    for field in _SHARED_FIELDS:
        if review[field] != request[field]:
            raise VisualReviewError(
                f"Detached visual review mismatches request field {field}."
            )
    try:
        verified = authority.verify_visual_approval(
            approval,
            policy,
            request,
            review,
        )
    except authority.ReleaseAuthorityError as exc:
        raise VisualReviewError(str(exc)) from exc
    if verified["visualApproved"] is not True:
        raise VisualReviewError("Signed visual review is not approved.")
    content = _canonical_json(review)
    approval_content = _canonical_json(approval)
    return {
        "content": content,
        "digest": _digest(content.encode("utf-8")),
        "approvalContent": approval_content,
        "approvalDigest": verified["artifactDigest"],
        "trustPolicyContent": _canonical_json(policy),
        "requestDigest": _digest(_canonical_json(request).encode("utf-8")),
    }


def _authority_module(installed_root: Path) -> ModuleType:
    path = (
        installed_root.resolve(strict=True)
        / "python3.11libs"
        / "hocuspocus"
        / "hocusscript"
        / "release_authority.py"
    )
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_installed_release_authority", path,
    )
    if spec is None or spec.loader is None:
        raise VisualReviewError("Installed release-authority verifier is absent.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        raise VisualReviewError(
            "Installed release-authority verifier is unavailable."
        ) from exc
    return module


def _external_file(path: Path, forbidden_roots: Iterable[Path]) -> Path:
    expanded = path.expanduser()
    try:
        if expanded.is_symlink():
            raise VisualReviewError("Detached visual review cannot be a symlink.")
        selected = expanded.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VisualReviewError("Detached visual review is unavailable.") from exc
    if (
        selected.is_symlink()
        or not selected.is_file()
        or selected.stat().st_size > MAX_REVIEW_BYTES
    ):
        raise VisualReviewError("Detached visual review is missing or unbounded.")
    for root in forbidden_roots:
        resolved = root.resolve(strict=True)
        if selected == resolved or resolved in selected.parents:
            raise VisualReviewError(
                "Detached visual review must remain outside source and install roots."
            )
    return selected


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_REVIEW_BYTES:
            raise VisualReviewError(f"{label} is missing or unbounded.")
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualReviewError(f"{label} is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise VisualReviewError(f"{label} must be a JSON object.")
    return value


def _review(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "kind",
        "reviewVersion",
        *_SHARED_FIELDS,
        "reviewerPrincipalId",
        "decision",
        "notesDigest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VisualReviewError("Detached visual review has an invalid envelope.")
    if (
        value["kind"] != "hocus_visual_version_review_evidence"
        or value["reviewVersion"] != 1
        or value["decision"] != "approved"
        or not isinstance(value["reviewerPrincipalId"], str)
        or _REVIEWER.fullmatch(value["reviewerPrincipalId"]) is None
    ):
        raise VisualReviewError("Detached visual review identity is invalid.")
    _shared(value)
    notes = value["notesDigest"]
    if notes is not None:
        _digest_value(notes, "notesDigest")
    return dict(value)


def _shared(value: Mapping[str, Any]) -> None:
    if (
        not isinstance(value["assetUri"], str)
        or _ASSET_URI.fullmatch(value["assetUri"]) is None
    ):
        raise VisualReviewError("Visual review assetUri is invalid.")
    for field in (
        "candidateProvenanceManifestDigest",
        "candidateOutputSetDigest",
        "visualComparisonDigest",
    ):
        _digest_value(value[field], field)
    for field in ("candidateVersionId", "reviewPolicyId"):
        if not isinstance(value[field], str) or _ID.fullmatch(value[field]) is None:
            raise VisualReviewError(f"Visual review {field} is invalid.")


def _digest_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise VisualReviewError(f"Visual review {label} is invalid.")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise VisualReviewError(f"Duplicate visual review field: {key}.")
        value[key] = item
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise VisualReviewError("Visual review must contain finite JSON.") from exc


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = [
    "MAX_REVIEW_BYTES",
    "BASELINE_RELATIVE_PATH",
    "REQUEST_RELATIVE_PATH",
    "VisualReviewError",
    "load_detached_visual_review",
    "select_detached_visual_review",
]
