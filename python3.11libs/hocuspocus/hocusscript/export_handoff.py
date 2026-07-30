"""Authenticated document-export publication through a guarded workspace."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any

from .catalog import SnapshotCatalogProvider
from .compiler import compile_source
from .project import ProjectContext
from .project_services import MAX_PAYLOAD_BYTES, SourceServiceError, WorkspaceHandle
from .semantic import CatalogConstraint, resolve_graph


@dataclass(frozen=True, slots=True)
class PreparedExportHandoff:
    workspace_write: Any
    result: Mapping[str, Any]


def prepare_export_handoff(
    handoff: Any,
    *,
    destination: str,
    project: ProjectContext,
    workspace: WorkspaceHandle,
    expected_digest: Any = None,
    max_bytes: int = MAX_PAYLOAD_BYTES,
) -> PreparedExportHandoff:
    """Validate an export and prepare its exact CAS write and response."""

    payload = _unwrap_handoff(handoff)
    encoded = _canonical_json(payload).encode("utf-8")
    if len(encoded) > max_bytes:
        raise SourceServiceError("HOCUS826", "Export handoff exceeds its byte limit.")
    source, provenance, source_digest = _validate_payload(payload)
    _validate_project_lane(project)
    _validate_project_identity(project, provenance)
    resolved = project.resolve_source_destination(destination)
    relative = resolved.relative_to(project.root).as_posix()
    source_uri = project.source_uri_for_resolved(resolved)
    compiled = _compile(source, resolved.name, source_uri)
    _validate_catalog(project, provenance, compiled)
    digest = _optional_digest(expected_digest)
    prepared = workspace._prepare_publish(
        relative,
        source,
        expected_digest=digest,
        create=digest is None,
    )
    result = _receipt_dict(prepared.receipt)
    result.update(
        {
            "stage": "source_export_publish",
            "valid": True,
            "relativePath": relative,
            "sourceUri": source_uri,
            "sourceDigest": source_digest,
        }
    )
    return PreparedExportHandoff(prepared, result)


def commit_export_handoff(
    prepared: PreparedExportHandoff,
    *,
    workspace: WorkspaceHandle,
) -> dict[str, Any]:
    """Commit a fully validated export and return its preflighted result."""

    if not isinstance(prepared, PreparedExportHandoff):
        raise SourceServiceError("HOCUS829", "Prepared export handoff is invalid.")
    workspace._commit_prepared(prepared.workspace_write)
    return dict(prepared.result)


def publish_export_handoff(
    handoff: Any,
    *,
    destination: str,
    project: ProjectContext,
    workspace: WorkspaceHandle,
    expected_digest: Any = None,
    before_publish: Callable[[], None] | None = None,
    publication_guard: Callable[[], AbstractContextManager[Any]] | None = None,
    max_bytes: int = MAX_PAYLOAD_BYTES,
) -> dict[str, Any]:
    """Validate, recompile, and atomically publish one source-export handoff."""

    prepared = prepare_export_handoff(
        handoff,
        destination=destination,
        project=project,
        workspace=workspace,
        expected_digest=expected_digest,
        max_bytes=max_bytes,
    )
    guard = publication_guard() if publication_guard is not None else nullcontext()
    with guard:
        if before_publish is not None:
            before_publish()
        return commit_export_handoff(prepared, workspace=workspace)


def _unwrap_handoff(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceServiceError(
            "HOCUS829", "Export handoff must be a JSON object."
        )
    structured = value.get("structuredContent")
    payload = structured if isinstance(structured, Mapping) else value
    if (
        payload.get("stage") != "source_export"
        or payload.get("exportVersion") != "1.0"
        or payload.get("languageVersion") != "0.1"
        or payload.get("valid") is not True
    ):
        raise SourceServiceError(
            "HOCUS829", "Export handoff is not a successful source_export result."
        )
    return payload


def _validate_payload(
    payload: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], str]:
    source = payload.get("source")
    provenance = payload.get("provenance")
    if (
        type(source) is not str
        or not isinstance(provenance, Mapping)
        or provenance.get("format") != "hocus-export-provenance-v0.1"
    ):
        raise SourceServiceError(
            "HOCUS829", "Export handoff is missing authenticated source provenance."
        )
    actual = "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
    declared = provenance.get("sourceDigest")
    if declared != actual:
        raise SourceServiceError(
            "HOCUS829",
            "Export source digest does not match its provenance.",
            details={"expected": declared, "actual": actual},
        )
    return source, provenance, actual


def _validate_project_lane(project: ProjectContext) -> None:
    if (
        project.language_version != "0.1"
        or project.manifest_version not in {1, 2}
    ):
        raise SourceServiceError(
            "HOCUS829",
            "Normalized language-0.1 export requires an exact flat 0.1 project lane.",
        )


def _validate_project_identity(
    project: ProjectContext,
    provenance: Mapping[str, Any],
) -> None:
    entities = provenance.get("entities")
    project_uids: set[str] = set()
    if isinstance(entities, Mapping):
        for record in entities.values():
            hocus = record.get("hocus") if isinstance(record, Mapping) else None
            uid = hocus.get("projectUid") if isinstance(hocus, Mapping) else None
            if isinstance(uid, str):
                project_uids.add(uid)
    if len(project_uids) > 1 or (project_uids and project.uid not in project_uids):
        raise SourceServiceError(
            "HOCUS829",
            "Export provenance does not match the selected project.",
            details={
                "exportProjectUids": sorted(project_uids),
                "projectUid": project.uid,
            },
        )


def _compile(source: str, source_name: str, source_uri: str) -> Any:
    compiled = compile_source(source, source_name, source_uri=source_uri, strict=True)
    if compiled.valid and compiled.graph_spec is not None:
        return compiled
    raise SourceServiceError(
        "HOCUS829",
        "Exported source did not pass native recompilation.",
        details={"diagnostics": [item.to_dict() for item in compiled.diagnostics]},
    )


def _validate_catalog(
    project: ProjectContext,
    provenance: Mapping[str, Any],
    compiled: Any,
) -> None:
    fingerprint = provenance.get("catalogFingerprint")
    if (
        not isinstance(fingerprint, str)
        or project.catalog is None
        or project.catalog_fingerprint != fingerprint
    ):
        raise SourceServiceError(
            "HOCUS829",
            "Export catalog fingerprint does not match the selected project.",
            details={
                "export": fingerprint,
                "project": project.catalog_fingerprint,
            },
        )
    semantic = resolve_graph(
        compiled.graph_spec,
        SnapshotCatalogProvider(project.catalog),
        constraint=CatalogConstraint(fingerprint),
    )
    if not semantic.valid or not semantic.ready_for_document_lowering:
        raise SourceServiceError(
            "HOCUS829",
            "Exported source failed exact-catalog semantic validation.",
            details={
                "diagnostics": [
                    item.to_dict() for item in semantic.diagnostics
                ],
            },
        )


def _optional_digest(value: Any) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise SourceServiceError(
            "HOCUS821", "expectedDigest must be an exact SHA-256 digest."
        )
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise SourceServiceError(
            "HOCUS821", "expectedDigest must be an exact SHA-256 digest."
        ) from exc
    return value


def _receipt_dict(value: Any) -> dict[str, Any]:
    serializer = getattr(value, "client_payload", None)
    if callable(serializer):
        value = serializer()
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise SourceServiceError(
            "HOCUS828", "Workspace publication returned an invalid receipt."
        )
    return dict(value)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SourceServiceError(
            "HOCUS829", "Export handoff must be bounded canonical JSON data."
        ) from exc
