"""Prospective manifest validation for guarded workspace patching."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .project import ProjectContext
from .project_service_support import SourceServiceError
from .workspace_patch import apply_unified_patch


def validate_manifest_patch(
    workspace: Any,
    authority_record: Any,
    relative_path: str,
    patch: str,
    expected_digest: str,
) -> None:
    """Reject invalid or authority-widening project manifest patches before write."""

    if relative_path.casefold() != "hocus.project.toml":
        return
    receipt = workspace.read(relative_path)
    current = receipt.client_payload()
    if current.get("rawDigest") != expected_digest:
        raise SourceServiceError(
            "HOCUS826", "Workspace manifest digest conflict."
        )
    content = current.get("content")
    if not isinstance(content, str):
        raise SourceServiceError("HOCUS827", "Workspace manifest read is malformed.")
    try:
        prospective = apply_unified_patch(
            content.encode("utf-8"), patch, relative_path,
        ).content
        with workspace.native_snapshot(
            include_external_roots={},
            writable_generated=False,
        ) as snapshot:
            snapshot.recheck()
            _replace_snapshot_manifest(snapshot.root, prospective)
            context = ProjectContext.load(snapshot.root, validate_lock=False)
            projection = _projection_digest(context)
    except SourceServiceError:
        raise
    except Exception as exc:
        raise SourceServiceError(
            "HOCUS827", "Prospective project manifest is invalid."
        ) from exc
    approved = getattr(authority_record, "projection_digest", None)
    if projection != approved:
        raise SourceServiceError(
            "HOCUS824",
            "Manifest changes project authority and requires host-user reapproval.",
            details={
                "approvedProjectionDigest": approved,
                "prospectiveProjectionDigest": projection,
            },
        )


def _replace_snapshot_manifest(root: Path, content: bytes) -> None:
    destination = root / "hocus.project.toml"
    try:
        destination.chmod(0o600)
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0),
        )
        try:
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise OSError("short manifest write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SourceServiceError(
            "HOCUS828", "Prospective manifest validation failed."
        ) from exc


def _projection_digest(context: ProjectContext) -> str:
    root = context.root
    source_paths = [_relative(root, item) for item in context.source_directories]
    module_paths = [_relative(root, item) for item in context.module_directories]
    aliases = [
        item.to_dict()
        for item in sorted(context.external_aliases, key=lambda value: value.alias)
    ]
    unsigned = {
        "projectUid": context.uid,
        "manifestVersion": context.manifest_version,
        "languageVersion": context.language_version,
        "lockPolicy": context.lock_policy,
        "sourceDirectories": source_paths,
        "moduleDirectories": module_paths,
        "externalAliases": aliases,
        "lockPath": (
            _relative(root, context.lock_path)
            if context.lock_path is not None
            else "hocus.lock.json"
        ),
        "catalogPath": (
            _relative(root, context.catalog_path)
            if context.catalog_path is not None
            else None
        ),
    }
    encoded = json.dumps(
        unsigned,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _relative(root: Path, value: Path) -> str:
    try:
        return value.relative_to(root).as_posix()
    except ValueError as exc:
        raise SourceServiceError(
            "HOCUS827", "Prospective manifest contains an escaping path."
        ) from exc
