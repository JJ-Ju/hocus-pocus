"""Portable manifest and generated-lock status for an authorized project."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .project import ExternalLibraryAlias, ProjectError
from .project_lock_validation import (
    _validate_lock_contents,
    _validate_lock_envelope,
    _validate_lock_identity,
)
from .project_service_support import SourceServiceError, client_payload

_MAX_LOCK_VALUES = 100_000


def enrich_project_description(
    metadata: Mapping[str, Any],
    *,
    record: Any,
    workspace: Any,
) -> dict[str, Any]:
    result = dict(metadata)
    result["manifestStatus"] = "current"
    projection = getattr(record, "projection", None)
    lock_path = getattr(projection, "lock_path", None)
    if not isinstance(lock_path, str):
        raise SourceServiceError(
            "HOCUS822", "Authorized project lock identity is unavailable."
        )
    manifest = client_payload(workspace.read("hocus.project.toml"))
    try:
        lock = client_payload(workspace.read_generated(lock_path))
    except Exception as exc:
        if getattr(exc, "code", None) == "HOCUS825":
            result["lockStatus"] = (
                "missing"
                if str(exc) == "Workspace file does not exist."
                else "invalid"
            )
            return result
        raise
    if not isinstance(manifest, Mapping) or not isinstance(lock, Mapping):
        raise SourceServiceError("HOCUS825", "Workspace metadata receipt is malformed.")
    raw_digest = lock.get("rawDigest")
    content = lock.get("content")
    manifest_digest = manifest.get("rawDigest")
    if isinstance(raw_digest, str):
        result["lockRawDigest"] = raw_digest
    if not isinstance(content, str) or not isinstance(manifest_digest, str):
        result["lockStatus"] = "invalid"
        return result
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
        _validate_json_bound(payload)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["lockStatus"] = "invalid"
        return result
    result["lockDigest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    result["lockStatus"] = _validated_lock_status(
        payload,
        projection=projection,
        manifest_digest=manifest_digest,
    )
    return result


def _validated_lock_status(
    payload: Any,
    *,
    projection: Any,
    manifest_digest: str,
) -> str:
    try:
        lock_version = _validate_lock_envelope(
            payload, projection.manifest_version,
        )
        _validate_lock_identity(
            payload,
            lock_version,
            projection.project_uid,
            manifest_digest,
            projection.language_version,
        )
        aliases = tuple(
            ExternalLibraryAlias(*record)
            for record in projection.external_aliases
        )
        _validate_lock_contents(
            payload,
            lock_version,
            projection.project_uid,
            projection.catalog_path,
            aliases,
        )
    except (AttributeError, TypeError, ProjectError) as exc:
        return "stale" if getattr(exc, "code", None) == "HOCUS424" else "invalid"
    return "current"


def _validate_json_bound(value: Any) -> None:
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > _MAX_LOCK_VALUES:
            raise ValueError("lock metadata exceeds bound")
        if isinstance(item, Mapping):
            if any(type(key) is not str for key in item):
                raise ValueError("lock metadata key is invalid")
            pending.extend(item.values())
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray),
        ):
            pending.extend(item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise ValueError("lock metadata value is invalid")


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("lock metadata contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"lock metadata constant is invalid: {value}")


__all__ = ["enrich_project_description"]
