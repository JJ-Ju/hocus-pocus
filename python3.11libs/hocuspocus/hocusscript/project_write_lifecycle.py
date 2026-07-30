"""Private linearizable publication admission for H6 source writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .project_service_support import SourceServiceError


@dataclass(frozen=True, slots=True)
class PreparedWorkspaceWrite:
    owner: object
    path: str
    kind: Any
    raw: bytes
    expected_digest: str | None
    create: bool
    receipt: Any


def require_manifest_refresh(authority: Any) -> Any:
    callback = getattr(authority, "accept_current_manifest_identity", None)
    if not callable(callback):
        raise SourceServiceError(
            "HOCUS824",
            "Manifest identity refresh requires host reapproval.",
        )
    return callback


def finish_manifest_refresh(
    authority: Any,
    context: Any,
    record: Any,
    callback: Any,
) -> None:
    try:
        callback(record.project_id, record.projection_digest)
    except Exception as exc:
        failed = getattr(authority, "manifest_refresh_failed", None)
        if callable(failed):
            try:
                failed(record.project_id, context, exc)
            except Exception:
                pass


def postcommit_housekeeping_failed(
    authority: Any,
    context: Any,
    project_id: str,
    error: Exception,
) -> None:
    """Revoke stale authority without changing a confirmed commit result."""

    failed = getattr(authority, "manifest_refresh_failed", None)
    if callable(failed):
        try:
            failed(project_id, context, error)
        except Exception:
            pass


@contextmanager
def write_authority_lease(
    authority: Any,
    context: Any,
    record: Any,
    grant: str,
) -> Iterator[None]:
    """Hold host write authority across the final recheck and publication."""

    lease = getattr(authority, "write_lease", None)
    if not callable(lease):
        raise SourceServiceError(
            "HOCUS823",
            "Linearizable source-write authority is unavailable.",
        )
    with lease(
        context,
        record.project_id,
        grant,
        record.projection_digest,
    ):
        yield


__all__ = [
    "PreparedWorkspaceWrite",
    "finish_manifest_refresh",
    "postcommit_housekeeping_failed",
    "require_manifest_refresh",
    "write_authority_lease",
]
