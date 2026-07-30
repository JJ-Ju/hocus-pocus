"""Runtime facade joining workspace registry, sessions, grants, audit, and limits."""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from hocuspocus.live.context import RequestContext

from .settings import ServerSettings
from .source_audit import WorkspaceAuditLogger
from .workspace_grants import (
    SOURCE_READ,
    WorkspaceGrant,
    WorkspaceGrantError,
    WorkspaceGrantStore,
    WorkspaceSession,
)
from .workspace_rate import WorkspaceRateLimiter
from .workspace_registry import (
    AuthorizedWorkspace,
    WorkspaceProject,
    WorkspaceRegistry,
    WorkspaceRegistryError,
)


class WorkspaceAuthorityError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class WorkspaceAuthority:
    def __init__(self, settings: ServerSettings, logger: logging.Logger):
        self.settings = settings
        self.registry = WorkspaceRegistry()
        self._lifecycle_lock = threading.Lock()
        self._write_authority_lock = threading.RLock()
        self._closed = False
        self._generation_lock = threading.Lock()
        self._resource_generations: dict[str, int] = {}
        self._configured_project_ids: set[str] = set()
        self._configured_projects: list[tuple[dict[str, Any], str]] = []
        self.audit_logger = WorkspaceAuditLogger(
            logger,
            events_per_project=settings.workspace_audit_events_per_project,
        )
        self.grants = WorkspaceGrantStore(
            session_ttl_seconds=settings.workspace_session_ttl_seconds,
            session_grant_ttl_seconds=settings.workspace_session_grant_ttl_seconds,
            persistent_grant_ttl_seconds=settings.workspace_persistent_grant_ttl_seconds,
            on_change=self.invalidate,
        )
        self.rate = WorkspaceRateLimiter()
        self._register_configured_projects(settings.source_projects)

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def close(self) -> None:
        with self._write_authority_lock:
            with self._lifecycle_lock:
                if self._closed:
                    return
                self.audit_logger.close()
                self._closed = True

    def apply_configured_grants(self, principal_id: str) -> None:
        for value, project_id in self._configured_projects:
            configured_grants = value.get("grants")
            if not configured_grants:
                self.grants.revoke(
                    project_id,
                    principal_id=principal_id,
                    persistent=True,
                )
                continue
            self.host_grant(
                project_id,
                principal_id=principal_id,
                grants=tuple(configured_grants),
                external_roots=value.get("external_roots"),
                persistent=True,
                expires_in_seconds=value.get("grant_expires_in_seconds"),
                until_revoked=value.get("grant_until_revoked", False),
            )

    def issue_session(
        self, principal_id: str, client_info: dict[str, Any] | None = None
    ) -> WorkspaceSession:
        with self._write_authority_lock:
            session = self.grants.issue_session(principal_id, client_info)
        self.audit(
            event="session.issue",
            project_id=None,
            principal_id=principal_id,
            session_id=session.session_id,
            success=True,
        )
        return session

    def context_session(self, context: RequestContext) -> WorkspaceSession | None:
        return self.session(
            context.session_id,
            principal_id=context.principal_id,
        )

    def session(
        self,
        session_id: str | None,
        *,
        principal_id: str | None = None,
        touch: bool = True,
    ) -> WorkspaceSession | None:
        with self._write_authority_lock:
            return self.grants.session(
                session_id,
                principal_id=principal_id,
                touch=touch,
            )

    def list_projects(self, context: RequestContext) -> tuple[dict[str, Any], ...]:
        with self._write_authority_lock:
            session = self.context_session(context)
            if session is None:
                return ()
            projects = self.grants.list_authorized(session.session_id, self.registry)
        return projects[: self.settings.workspace_projects_per_session]

    def authorize(
        self,
        context: RequestContext,
        project_id: str,
        required_grant: str,
        authority_projection_digest: str | None = None,
        *,
        external_alias: str | None = None,
    ) -> AuthorizedWorkspace:
        with self._write_authority_lock:
            session = self.context_session(context)
            if session is None:
                self._deny(
                    context, project_id, "HOCUS821", "Workspace session is unavailable."
                )
            try:
                project = self.registry.require_current(project_id)
                if (
                    authority_projection_digest is not None
                    and not secrets.compare_digest(
                        authority_projection_digest, project.projection.digest
                    )
                ):
                    raise WorkspaceAuthorityError(
                        "HOCUS824",
                        "The requested authority projection is stale.",
                        {"projectId": project_id},
                    )
                assert session is not None
                authorized = self.grants.require(
                    session.session_id,
                    project,
                    required_grant,
                    external_alias=external_alias,
                )
            except WorkspaceRegistryError as exc:
                code = "HOCUS824" if exc.code == "HOCUS904" else "HOCUS822"
                self._deny(context, project_id, code, exc.message)
            except WorkspaceGrantError as exc:
                code = "HOCUS825" if external_alias is not None else "HOCUS823"
                if exc.code in {"HOCUS910", "HOCUS912"}:
                    code = "HOCUS821" if exc.code == "HOCUS910" else "HOCUS824"
                self._deny(context, project_id, code, exc.message)
            except WorkspaceAuthorityError:
                raise
            generation = self._combined_generation(project_id, authorized.generation)
            return replace(authorized, generation=generation)

    @contextmanager
    def write_lease(
        self,
        context: RequestContext,
        project_id: str,
        required_grant: str,
        authority_projection_digest: str,
    ) -> Iterator[AuthorizedWorkspace]:
        """Linearize final write admission with grant and project revocation."""

        with self._write_authority_lock:
            if context.is_cancelled():
                raise WorkspaceAuthorityError(
                    "HOCUS825",
                    "Source write was cancelled before publication.",
                    {"projectId": project_id},
                )
            yield self.authorize(
                context,
                project_id,
                required_grant,
                authority_projection_digest,
            )

    def register_project(
        self,
        root: str,
        *,
        label: str | None = None,
        reapprove: bool = False,
    ) -> WorkspaceProject:
        with self._write_authority_lock:
            existing = self.registry.find_by_root(root)
            if (
                reapprove
                and existing is not None
                and existing.project_id in self._configured_project_ids
            ):
                raise WorkspaceAuthorityError(
                    "HOCUS826",
                    "Configured project approval can only change through host configuration and restart.",
                    {"projectId": existing.project_id},
                )
            project = self.registry.register(root, label=label, reapprove=reapprove)
        self.audit(
            event="project.reapprove" if reapprove else "project.register",
            project_id=project.project_id,
            principal_id="host-ui",
            session_id=None,
            success=True,
            details={"digest": project.projection.digest},
        )
        self.invalidate(project.project_id, "registration")
        return project

    def remove_project(self, project_id: str) -> WorkspaceProject:
        with self._write_authority_lock:
            if project_id in self._configured_project_ids:
                raise WorkspaceAuthorityError(
                    "HOCUS826",
                    "Configured projects can only be removed through host configuration and restart.",
                    {"projectId": project_id},
                )
            project = self.registry.remove(project_id)
            self.grants.revoke_project_all(project_id)
        self.audit(
            event="project.remove",
            project_id=project_id,
            principal_id="host-ui",
            session_id=None,
            success=True,
        )
        self.invalidate(project_id, "removal")
        return project

    def accept_current_manifest_identity(
        self,
        project_id: str,
        expected_projection_digest: str,
    ) -> WorkspaceProject:
        with self._write_authority_lock:
            try:
                project = self.registry.accept_current_manifest_identity(
                    project_id,
                    expected_projection_digest,
                )
            except WorkspaceRegistryError as exc:
                raise WorkspaceAuthorityError(
                    "HOCUS824",
                    exc.message,
                    {"projectId": project_id},
                ) from exc
        self.audit(
            event="project.manifest.publish",
            project_id=project_id,
            principal_id="host-runtime",
            session_id=None,
            success=True,
            details={"digest": expected_projection_digest},
        )
        self.invalidate(project_id, "manifest_publication")
        return project

    def manifest_refresh_failed(
        self,
        project_id: str,
        context: RequestContext,
        error: Exception,
    ) -> None:
        """Revoke stale authority without exposing or re-raising housekeeping data."""

        with self._write_authority_lock:
            try:
                self.grants.revoke_project_all(project_id)
            except Exception:
                pass
            try:
                self.invalidate(project_id, "manifest_refresh_failure")
            except Exception:
                pass
            try:
                self.audit(
                    event="project.manifest.refresh_failed",
                    project_id=project_id,
                    context=context,
                    success=False,
                    details={
                        "errorCode": "HOCUS824",
                        "errorType": type(error).__name__,
                    },
                )
            except Exception:
                pass

    def host_grant(
        self,
        project_id: str,
        *,
        principal_id: str,
        session_id: str | None = None,
        grants: tuple[str, ...] = (SOURCE_READ,),
        external_roots: dict[str, str] | None = None,
        persistent: bool = False,
        expires_in_seconds: float | None = None,
        until_revoked: bool = False,
    ) -> WorkspaceGrant:
        with self._write_authority_lock:
            project = self.registry.require_current(project_id)
            grant = self.grants.grant(
                project,
                principal_id=principal_id,
                session_id=session_id,
                grants=grants,
                external_roots=external_roots,
                persistent=persistent,
                expires_in_seconds=expires_in_seconds,
                until_revoked=until_revoked,
            )
        self.audit(
            event="grant.approve",
            project_id=project_id,
            principal_id=principal_id,
            session_id=session_id,
            success=True,
            details={
                "grants": list(grant.grants),
                "grantGeneration": grant.generation,
            },
        )
        return grant

    def host_revoke(
        self,
        project_id: str,
        *,
        principal_id: str,
        session_id: str | None = None,
        persistent: bool | None = None,
    ) -> bool:
        with self._write_authority_lock:
            removed = self.grants.revoke(
                project_id,
                principal_id=principal_id,
                session_id=session_id,
                persistent=persistent,
            )
        self.audit(
            event="grant.revoke",
            project_id=project_id,
            principal_id=principal_id,
            session_id=session_id,
            success=removed,
        )
        return removed

    def revoke_session(self, session_id: str) -> bool:
        with self._write_authority_lock:
            return self.grants.revoke_session(session_id)

    def invalidate(self, project_id: str, reason: str = "change") -> int:
        with self._generation_lock:
            generation = self._resource_generations.get(project_id, 0) + 1
            self._resource_generations[project_id] = generation
        self.audit(
            event="resource.invalidate",
            project_id=project_id,
            principal_id="host-runtime",
            session_id=None,
            success=True,
            details={"action": reason, "grantGeneration": generation},
        )
        return generation

    def audit(
        self,
        *,
        event: str,
        project_id: str | None,
        success: bool,
        context: RequestContext | None = None,
        principal_id: str | None = None,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        resolved_principal = principal_id or (
            context.principal_id if context is not None else "host-runtime"
        )
        resolved_session = (
            context.session_id if context is not None and session_id is None else session_id
        )
        self.audit_logger.record(
            event=event,
            project_id=project_id,
            principal_id=resolved_principal,
            session_id=resolved_session,
            success=success,
            details=details,
        )

    def host_snapshot(self) -> dict[str, Any]:
        with self._write_authority_lock:
            projects = self.registry.host_snapshot()
            for project in projects:
                project["configOwned"] = (
                    project.get("projectId") in self._configured_project_ids
                )
            return {
                "projects": projects,
                **self.grants.host_snapshot(),
                "recentAudit": self.audit_logger.recent(limit=100),
            }

    def _register_configured_projects(self, projects: list[dict[str, Any]]) -> None:
        for value in projects:
            project = self.registry.register(
                value["root"],
                label=value.get("label"),
                project_id=value.get("project_id"),
                reapprove=True,
                allow_repoint=True,
            )
            if project.project_id in self._configured_project_ids:
                raise WorkspaceAuthorityError(
                    "HOCUS826",
                    "A configured project may only be declared once.",
                    {"projectId": project.project_id},
                )
            self._configured_project_ids.add(project.project_id)
            self._configured_projects.append((value, project.project_id))

    def _combined_generation(self, project_id: str, grant_generation: int) -> int:
        with self._generation_lock:
            resource_generation = self._resource_generations.get(project_id, 0)
        return grant_generation * 1_000_000 + resource_generation

    def _deny(
        self,
        context: RequestContext,
        project_id: str,
        code: str,
        message: str,
    ) -> None:
        self.audit(
            event="authority.deny",
            project_id=project_id,
            principal_id=context.principal_id,
            session_id=context.session_id,
            success=False,
            details={"errorCode": code},
        )
        raise WorkspaceAuthorityError(code, message, {"projectId": project_id})


__all__ = ["WorkspaceAuthority", "WorkspaceAuthorityError"]
