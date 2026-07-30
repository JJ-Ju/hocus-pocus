"""Strict RC1 evidence-set identity used by immutable release candidates."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .release_authority import canonical_json_bytes

SCHEMA = "hocuspocus://schemas/rc1-evidence-set/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT = re.compile(r"^(?:git-sha1:[0-9a-f]{40}|git-sha256:[0-9a-f]{64})$")
_RECEIPTS = {
    "performance": "hocus_performance_benchmark_receipt",
    "compatibility": "hocus_compatibility_matrix_receipt",
    "graphStore": "hocus_graph_store_upgrade_receipt",
    "packageSearch": "hocus_effective_package_search_provenance",
}


class ReleaseEvidenceError(ValueError):
    """Malformed, stale, or cross-candidate RC1 evidence."""


def create_rc1_evidence_set(
    candidate: Mapping[str, Any],
    receipts: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_candidate = _candidate(candidate)
    normalized_receipts = _receipts(receipts)
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_rc1_evidence_set",
        "schemaVersion": 1,
        "candidate": normalized_candidate,
        "receipts": normalized_receipts,
        "installedPayloadManifestDigest": normalized_receipts[
            "packageSearch"
        ]["installedPayloadManifestDigest"],
        "runtimeDigest": normalized_receipts["packageSearch"]["runtimeDigest"],
    }
    return {**unsigned, "evidenceSetDigest": _digest(unsigned)}


def verify_rc1_evidence_set(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "$schema",
        "kind",
        "schemaVersion",
        "candidate",
        "receipts",
        "installedPayloadManifestDigest",
        "runtimeDigest",
        "evidenceSetDigest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseEvidenceError("RC1 evidence set has an invalid envelope.")
    if (
        value["$schema"] != SCHEMA
        or value["kind"] != "hocus_rc1_evidence_set"
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise ReleaseEvidenceError("RC1 evidence-set identity is invalid.")
    candidate = _candidate(value["candidate"])
    receipts = _receipts(value["receipts"])
    if value["installedPayloadManifestDigest"] != receipts[
        "packageSearch"
    ]["installedPayloadManifestDigest"]:
        raise ReleaseEvidenceError("RC1 installed-payload identity is inconsistent.")
    if value["runtimeDigest"] != receipts["packageSearch"]["runtimeDigest"]:
        raise ReleaseEvidenceError("RC1 runtime identity is inconsistent.")
    unsigned = {key: item for key, item in value.items() if key != "evidenceSetDigest"}
    if value["evidenceSetDigest"] != _digest(unsigned):
        raise ReleaseEvidenceError("RC1 evidence-set digest does not match its content.")
    return dict(value) | {"candidate": candidate, "receipts": receipts}


def _candidate(value: Any) -> dict[str, Any]:
    fields = {
        "commitDigest",
        "treeDigest",
        "workspaceSnapshotDigest",
        "fileCount",
        "clean",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseEvidenceError("RC1 candidate identity is invalid.")
    if (
        not isinstance(value["commitDigest"], str)
        or _GIT.fullmatch(value["commitDigest"]) is None
        or not isinstance(value["treeDigest"], str)
        or _GIT.fullmatch(value["treeDigest"]) is None
        or not isinstance(value["workspaceSnapshotDigest"], str)
        or _DIGEST.fullmatch(value["workspaceSnapshotDigest"]) is None
        or type(value["fileCount"]) is not int
        or value["fileCount"] < 1
        or value["clean"] is not True
        or value["commitDigest"].split(":", 1)[0]
        != value["treeDigest"].split(":", 1)[0]
    ):
        raise ReleaseEvidenceError("RC1 requires a clean exact commit/tree snapshot.")
    return dict(value)


def _receipts(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or set(value) != set(_RECEIPTS):
        raise ReleaseEvidenceError("RC1 receipt set is incomplete.")
    return {
        name: _receipt(value[name], kind)
        for name, kind in _RECEIPTS.items()
    }


def _receipt(value: Any, kind: str) -> dict[str, str]:
    fields = {
        "schema",
        "kind",
        "receiptDigest",
        "fileDigest",
    }
    if kind == _RECEIPTS["packageSearch"]:
        fields.update({"installedPayloadManifestDigest", "runtimeDigest"})
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseEvidenceError(f"RC1 {kind} receipt identity is invalid.")
    for field in fields - {"schema", "kind"}:
        if not isinstance(value[field], str) or _DIGEST.fullmatch(value[field]) is None:
            raise ReleaseEvidenceError(f"RC1 {kind} {field} is invalid.")
    expected_schema = (
        "hocuspocus://schemas/effective-package-search-provenance/v1"
        if kind == _RECEIPTS["packageSearch"]
        else "hocuspocus://schemas/internal-release-evidence/v1"
    )
    if value["kind"] != kind or value["schema"] != expected_schema:
        raise ReleaseEvidenceError(f"RC1 {kind} carrier identity is invalid.")
    return dict(value)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "ReleaseEvidenceError",
    "SCHEMA",
    "create_rc1_evidence_set",
    "verify_rc1_evidence_set",
]
