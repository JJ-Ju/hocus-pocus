"""Project source services composed from native APIs and injected authority."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .control_lock_update import update_project_control_lock
from .control_mixed_lock_update import update_project_mixed_control_lock
from .control_mixed_project_editor import (
    complete_mixed_control_path,
    complete_mixed_control_project_source,
    definition_mixed_control_path,
    definition_mixed_control_project_source,
)
from .control_project_editor import (
    complete_control_path,
    complete_control_project_source,
    definition_control_path,
    definition_control_project_source,
)
from .lock_update import update_project_module_lock
from .mixed_lock_update import update_project_mixed_module_lock
from .mixed_project_editor import (
    complete_mixed_path,
    complete_mixed_project_source,
    definition_mixed_path,
    definition_mixed_project_source,
)
from .module_format import format_project_module_path
from .export_handoff_auth import issue_export_token, verify_export_token
from .project import ProjectContext
from .project_build import check_project as _check_project
from .project_build import compile_project as _compile_project
from .project_description import enrich_project_description
from .project_editor import (
    complete_path,
    complete_project_source,
    definition_path,
    definition_project_source,
)
from .project_service_cursors import SourceCursorMixin
from .project_service_support import (
    APPLY_RESPONSE_SUMMARY,
    EXPORT_RESPONSE_SUMMARY,
    LOCK_RESPONSE_SUMMARY,
    PreparedSourceResponse,
    SourceServiceError,
    audit_details as _audit_details,
    audit_grant_generation as _audit_grant_generation,
    bounded_int as _bounded_int,
    check_payload as _check_payload,
    client_payload as _client_payload,
    configured_limit as _configured_limit,
    ensure_source_payload as _ensure_source_payload,
    file_resource as _file_resource,
    generated_publication_authority as _generated_publication_authority,
    lock_update_expectation as _lock_update_expectation,
    mapped_error as _mapped_error,
    optional_text as _optional_text,
    path_batch as _path_batch,
    portable_details as _portable_details,
    portable_result as _portable_result,
    prepare_source_tool_response as _prepare_source_tool_response,
    project_resource as _project_resource,
    rate_category as _rate_category,
    recheck_descriptions as _recheck_descriptions,
    reject_native_paths as _reject_native_paths,
    record_project_id as _record_project_id,
    required_digest as _required_digest,
    required_text as _required_text,
    source_response_limit as _source_response_limit,
    source_uri as _source_uri,
)
from .project_search import search_workspace as _search_workspace
from .project_write_lifecycle import (
    finish_manifest_refresh as _finish_manifest_refresh,
    postcommit_housekeeping_failed as _postcommit_housekeeping_failed,
    require_manifest_refresh as _require_manifest_refresh,
    write_authority_lease as _write_authority_lease,
)

SOURCE_READ, SOURCE_WRITE = "source_read", "source_write"
GENERATED_LOCK_UPDATE, EXTERNAL_ROOT_READ = "generated_lock", "external_read"
MAX_SEARCH_MATCHES = 200
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_RESOURCE_PAGE = 200


@runtime_checkable
class AuthorizedProject(Protocol):
    """Private authority record retained inside the server process."""

    project_id: str
    approved_root: str | Path
    root_identity_digest: str
    projection_digest: str
    generation: int
    projection: Any
    grants: Sequence[str]
    external_roots: Sequence[tuple[str, str | Path]]
    external_root_identities: Sequence[tuple[str, str]]


@runtime_checkable
class SourceAuthority(Protocol):
    """Required H6A registry/grant adapter."""

    def list_projects(self, context: Any) -> Sequence[AuthorizedProject]:
        """Return only project records currently authorized to this caller."""

    def authorize(
        self,
        context: Any,
        project_id: str,
        required_grant: str,
        authority_projection_digest: str | None = None,
        *,
        external_alias: str | None = None,
    ) -> AuthorizedProject:
        """Recheck one current project grant and return its private record."""


@runtime_checkable
class WorkspaceHandle(Protocol):
    """Descriptor-safe H6B handle used for all authored-file access."""

    def inspect(self) -> Mapping[str, Any]: ...

    def enumerate_files(
        self,
        *,
        include_manifest: bool = True,
        include_generated: bool = False,
        max_files: int,
    ) -> Any: ...

    def search(
        self,
        query: str,
        *,
        case_sensitive: bool,
        include_manifest: bool = True,
        max_results: int,
    ) -> Any: ...

    def glob(
        self,
        pattern: str,
        *,
        cursor: str | None,
        limit: int,
        case_sensitive: bool,
        include_generated: bool,
    ) -> Any: ...

    def read(self, relative_path: str) -> Any: ...

    def create(self, relative_path: str, content: str) -> Any: ...

    def apply_patch(
        self,
        relative_path: str,
        unified_diff: str,
        *,
        expected_digest: str,
        max_operations: int,
    ) -> Any: ...

    def publish(
        self,
        relative_path: str,
        content: str,
        *,
        expected_digest: str | None,
        create: bool = False,
        allowed_kinds: Any = None,
    ) -> Any: ...

    def close(self) -> None: ...

    def generated_digest(self, relative_path: str) -> str: ...

    def native_snapshot(
        self,
        *,
        include_external_roots: Mapping[str, str | Path],
        writable_generated: bool = False,
    ) -> AbstractContextManager[Any]: ...


@runtime_checkable
class WorkspaceFactory(Protocol):
    """H6B WorkspaceIO-compatible factory."""

    @classmethod
    def open_project(
        cls,
        approved_root: Any,
        *,
        source_directories: Sequence[str] | None = None,
        module_directories: Sequence[str] | None = None,
        lock_path: str | None = None,
        catalog_path: str | None = None,
        writable: bool = False,
    ) -> WorkspaceHandle: ...


@dataclass(frozen=True, slots=True)
class _ProjectSession:
    record: AuthorizedProject
    workspace: WorkspaceHandle
    external_roots: Mapping[str, str | Path]


class SourceWorkspaceService(SourceCursorMixin):
    """The seven-operation source service behind the live MCP mixin."""

    def __init__(
        self,
        authority: SourceAuthority,
        workspace_factory: type[WorkspaceFactory] | None = None,
    ) -> None:
        self._authority = authority
        self._workspace_factory = workspace_factory or _default_workspace_factory()
        self._cursor_key = secrets.token_bytes(32)
        self._handoff_key = secrets.token_bytes(32)

    def rate(self, context: Any, event: str, project_id: str | None) -> None:
        limiter = getattr(self._authority, "rate", None)
        if limiter is None:
            return
        principal_id = str(getattr(context, "principal_id", "unknown"))
        session_id = str(getattr(context, "session_id", "none"))
        try:
            authorized = {_record_project_id(item) for item in self._authority.list_projects(context)} if project_id is not None else set()
            denied = project_id is not None and project_id not in authorized
            total = _configured_limit(self._authority, "workspace_rate_total_per_minute", 120, 120)
            category, setting, ceiling = _rate_category(event)
            category_limit = None
            if category is not None and setting is not None:
                category_limit = _configured_limit(self._authority, setting, ceiling, ceiling)
            limiter.require_scoped(
                principal_id,
                session_id,
                project_id,
                total_limit=total,
                category=category,
                category_limit=category_limit,
                denied=denied,
                window_seconds=60.0,
            )
        except Exception as exc:
            raise SourceServiceError(
                "HOCUS825", "Source request rate limit exceeded."
            ) from exc

    def has_valid_session(self, context: Any) -> bool:
        session_id = getattr(context, "session_id", None)
        if not isinstance(session_id, str) or not session_id:
            return False
        checker = getattr(self._authority, "context_session", None)
        return not callable(checker) or checker(context) is not None

    def require_session(self, context: Any) -> None:
        if not self.has_valid_session(context):
            raise SourceServiceError(
                "HOCUS821", "Workspace session is unavailable."
            )

    def issue_export_handoff(
        self,
        context: Any,
        handoff: Mapping[str, Any],
    ) -> dict[str, Any]:
        return issue_export_token(
            handoff,
            key=self._handoff_key,
            principal_id=str(getattr(context, "principal_id", "unknown")),
            session_id=getattr(context, "session_id", None),
        )

    def verify_export_handoff(self, context: Any, handoff: Any) -> None:
        verify_export_token(
            handoff,
            key=self._handoff_key,
            principal_id=str(getattr(context, "principal_id", "unknown")),
            session_id=getattr(context, "session_id", None),
        )

    def ensure_response(
        self, payload: Mapping[str, Any], *, code: str = "HOCUS825",
    ) -> None:
        _ensure_source_payload(
            payload, maximum=_source_response_limit(self._authority), code=code,
        )

    def prepare_tool_response(
        self, summary: str, payload: Mapping[str, Any], *, code: str,
    ) -> PreparedSourceResponse:
        return _prepare_source_tool_response(
            summary, payload,
            maximum=_source_response_limit(self._authority), code=code,
        )

    def audit(
        self,
        context: Any,
        event: str,
        project_id: str | None,
        *,
        success: bool,
        code: str | None = None,
        arguments: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        terminal: bool = False,
    ) -> None:
        callback = getattr(self._authority, "audit", None)
        if callback is None:
            return
        try:
            generation = _audit_grant_generation(
                self._authority, context, project_id,
            )
            details = _audit_details(
                event,
                arguments=arguments,
                result=result,
                grant_generation=generation,
                error_code=code,
            )
            callback(
                event=f"source.{event}",
                project_id=project_id,
                principal_id=str(getattr(context, "principal_id", "unknown")),
                session_id=getattr(context, "session_id", None),
                success=success,
                details=details,
            )
        except Exception as exc:
            if not terminal or project_id is None:
                raise
            _postcommit_housekeeping_failed(
                self._authority, context, project_id, exc,
            )

    @contextmanager
    def build_slot(self, context: Any, project_id: str):
        limiter = getattr(self._authority, "rate", None)
        if limiter is None:
            yield
            return
        settings = getattr(self._authority, "settings", None)
        per_project = getattr(settings, "workspace_builds_per_project", 1)
        per_session = getattr(settings, "workspace_builds_per_session", 2)
        session_id = str(getattr(context, "session_id", "none"))
        slot = ExitStack()
        try:
            slot.enter_context(limiter.build_slot(
                session_id,
                project_id,
                per_project=per_project,
                per_session=per_session,
            ))
        except SourceServiceError:
            raise
        except Exception as exc:
            raise SourceServiceError(
                "HOCUS825", "Source build concurrency limit exceeded."
            ) from exc
        with slot:
            yield

    def list_resources(self, context: Any, cursor: str | None) -> dict[str, Any]:
        resources = self._workspace_resources(context)
        digest = hashlib.sha256(
            json.dumps(resources, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        offset = self._resource_cursor(context, cursor, digest)
        selected = resources[offset: offset + MAX_RESOURCE_PAGE]
        result: dict[str, Any] = {"resources": selected}
        if len(resources) > offset + MAX_RESOURCE_PAGE:
            result["nextCursor"] = self._encode_resource_cursor(
                context, offset + MAX_RESOURCE_PAGE, digest,
            )
        return result

    def describe(self, context: Any, project_id: str | None = None) -> dict[str, Any]:
        self.require_session(context)
        try:
            records = self._authority.list_projects(context)
            selected = [
                record for record in records
                if project_id is None or _record_project_id(record) == project_id
            ]
            if project_id is not None and not selected:
                raise SourceServiceError(
                    "HOCUS822", "Project is not authorized for this connection."
                )
            projects = [
                self._describe_authorized(context, record)
                for record in selected
            ]
            _recheck_descriptions(self._authority, context, projects)
            return {"projects": projects, "projectCount": len(projects)}
        except SourceServiceError:
            raise
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS822", "Project description was denied.") from exc

    def search(self, context: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        maximum = _configured_limit(
            self._authority, "workspace_search_limit", MAX_SEARCH_MATCHES, 1000,
        )
        limit = _bounded_int(request.get("limit", maximum), 1, maximum)
        session, scope = self._read_session(context, request)
        glob = _optional_text(request.get("glob"), "glob")
        query = _optional_text(request.get("query"), "query")
        cursor = _optional_text(request.get("cursor"), "cursor")
        external_alias = _optional_text(
            request.get("externalAlias"), "externalAlias",
        )
        case_sensitive = request.get("caseSensitive", False)
        if type(case_sensitive) is not bool:
            raise SourceServiceError("HOCUS821", "caseSensitive must be boolean.")
        if glob is None and query is None:
            raise SourceServiceError("HOCUS821", "Search requires glob or query.")
        try:
            offset = self._decode_search_cursor(
                context,
                session,
                cursor,
                scope=scope,
                glob=glob,
                query=query,
                case_sensitive=case_sensitive,
                external_alias=external_alias,
            )
            result = _search_workspace(
                session.workspace,
                glob=glob,
                query=query,
                case_sensitive=case_sensitive,
                include_manifest=scope == "project",
                offset=offset,
                limit=limit,
            )
            aliases = getattr(session.record.projection, "external_aliases", ())
            for match in result.get("matches", ()):
                if isinstance(match, dict) and isinstance(match.get("path"), str):
                    match["uri"] = _source_uri(
                        session.record.project_id,
                        match["path"],
                        external_alias=external_alias if scope == "external" else None,
                        external_aliases=aliases,
                    )
            self._reauthorize(
                session,
                context,
                EXTERNAL_ROOT_READ if scope == "external" else SOURCE_READ,
                external_alias=external_alias,
            )
            next_offset = result.pop("_nextOffset", None)
            if isinstance(next_offset, int):
                result["nextCursor"] = self._encode_search_cursor(
                    context,
                    session,
                    next_offset,
                    scope=scope,
                    glob=glob,
                    query=query,
                    case_sensitive=case_sensitive,
                    external_alias=external_alias,
                )
            return {
                **result,
                "projectId": session.record.project_id,
                "scope": scope,
            }
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS824", "Source search failed.") from exc
        finally:
            session.workspace.close()

    def read(self, context: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        maximum = _configured_limit(
            self._authority, "workspace_read_batch_limit", 16, 64,
        )
        paths = _path_batch(request.get("paths"), maximum)
        session, scope = self._read_session(context, request)
        try:
            if scope == "external" and any(
                path.casefold() == "hocus.module.toml" for path in paths
            ):
                raise SourceServiceError(
                    "HOCUS823", "External module manifests are not public source files."
                )
            files = [_client_payload(session.workspace.read(path)) for path in paths]
            aliases = getattr(session.record.projection, "external_aliases", ())
            external_alias = request.get("externalAlias")
            for file in files:
                if isinstance(file, dict) and isinstance(file.get("path"), str):
                    file["uri"] = _source_uri(
                        session.record.project_id,
                        file["path"],
                        external_alias=external_alias if scope == "external" else None,
                        external_aliases=aliases,
                    )
                    file["mediaType"] = (
                        "application/toml"
                        if file["path"].casefold() == "hocus.project.toml"
                        else "text/x-hocusscript"
                    )
            self._reauthorize(
                session,
                context,
                EXTERNAL_ROOT_READ if scope == "external" else SOURCE_READ,
                external_alias=external_alias,
            )
            return {
                "projectId": session.record.project_id,
                "scope": scope,
                "files": files,
                "fileCount": len(files),
            }
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS824", "Source read failed.") from exc
        finally:
            session.workspace.close()

    def apply_patch(self, context: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        from .project_manifest_guard import validate_manifest_patch

        session = self._session(context, request, SOURCE_WRITE, writable=True)
        relative = _required_text(request.get("path"), "path")
        mode = _required_text(request.get("mode"), "mode")
        payload_limit = _configured_limit(
            self._authority, "workspace_payload_bytes", MAX_PAYLOAD_BYTES, 8 * 1024 * 1024,
        )
        try:
            if mode == "create":
                content = request.get("content")
                if type(content) is not str or any(
                    request.get(field) is not None
                    for field in ("expectedDigest", "unifiedDiff")
                ):
                    raise SourceServiceError(
                        "HOCUS821",
                        "Create mode requires content and no digest or unified diff.",
                )
                _check_payload(content, payload_limit)
                prepared = session.workspace._prepare_create(relative, content)
            elif mode == "patch":
                digest = _required_digest(
                    request.get("expectedDigest"), "expectedDigest",
                )
                patch = _required_text(request.get("unifiedDiff"), "unifiedDiff")
                _check_payload(patch, payload_limit)
                validate_manifest_patch(
                    session.workspace,
                    session.record,
                    relative,
                    patch,
                    digest,
                )
                prepared = session.workspace._prepare_patch(
                    relative,
                    patch,
                    expected_digest=digest,
                    max_operations=_configured_limit(
                        self._authority,
                        "workspace_patch_operation_limit",
                        64,
                        256,
                    ),
                )
            else:
                raise SourceServiceError("HOCUS821", "Patch mode is unsupported.")
            response = _portable_result(
                prepared.receipt, project_id=session.record.project_id,
            )
            response = self.prepare_tool_response(
                APPLY_RESPONSE_SUMMARY, response, code="HOCUS825",
            )
            manifest = relative.casefold() == "hocus.project.toml"
            accept = _require_manifest_refresh(self._authority) if manifest else None
            with _write_authority_lease(
                self._authority, context, session.record, SOURCE_WRITE,
            ):
                session.workspace._commit_prepared(prepared)
                if accept is not None:
                    _finish_manifest_refresh(
                        self._authority, context, session.record, accept,
                    )
            if not manifest:
                self._invalidate(context, session.record.project_id, (relative,))
            return response
        except SourceServiceError:
            raise
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS827", "Source patch was rejected.") from exc
        finally:
            session.workspace.close()

    def write_export(
        self,
        context: Any,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        from .export_handoff import commit_export_handoff, prepare_export_handoff

        session = self._session(context, request, SOURCE_WRITE, writable=True)
        try:
            self.verify_export_handoff(context, request.get("handoff"))
            with _native_snapshot(session) as snapshot:
                root = _snapshot_root(snapshot)
                project = ProjectContext.load(root, validate_lock=True)
                prepared = prepare_export_handoff(
                    request.get("handoff"),
                    destination=_required_text(
                        request.get("destination"), "destination",
                    ),
                    project=project,
                    workspace=session.workspace,
                    expected_digest=request.get("expectedDigest"),
                    max_bytes=_configured_limit(
                        self._authority,
                        "workspace_payload_bytes",
                        MAX_PAYLOAD_BYTES,
                        8 * 1024 * 1024,
                    ),
                )
                response = _portable_result(
                    prepared.result, project_id=session.record.project_id,
                )
                _reject_native_paths(
                    response, (root, *_snapshot_external_roots(snapshot).values()),
                )
                response = self.prepare_tool_response(
                    EXPORT_RESPONSE_SUMMARY, response, code="HOCUS829",
                )
                relative = str(prepared.result["relativePath"])
                with _write_authority_lease(
                    self._authority, context, session.record, SOURCE_WRITE,
                ):
                    _snapshot_recheck(snapshot)
                    snapshot.close()
                    commit_export_handoff(prepared, workspace=session.workspace)
            self._invalidate(context, session.record.project_id, (relative,))
            return response
        except SourceServiceError:
            raise
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS829", "Export handoff was rejected.") from exc
        finally:
            session.workspace.close()

    def build(self, context: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        action = _required_text(request.get("action"), "action")
        lock_create = (
            _lock_update_expectation(request)[0]
            if action == "lock_update"
            else False
        )
        grant = GENERATED_LOCK_UPDATE if action == "lock_update" else SOURCE_READ
        session = self._session(
            context, request, grant, writable=action == "lock_update",
        )
        try:
            with self.build_slot(context, session.record.project_id):
                with _native_snapshot(
                    session, writable_generated=action == "lock_update",
                ) as snapshot:
                    root = _snapshot_root(snapshot)
                    project = ProjectContext.load(
                        root,
                        validate_lock=action != "format" and not lock_create,
                    )
                    roots = _snapshot_external_roots(snapshot)
                    result = self._run_build(
                        session, project, roots, snapshot, action, request, context,
                    )
                    if action != "lock_update":
                        _reject_native_paths(result, (root, *roots.values()))
                        _snapshot_recheck(snapshot)
                        self._reauthorize(session, context, grant)
            if action == "lock_update":
                self._invalidate(context, session.record.project_id)
                return result
            return _portable_result(result, project_id=session.record.project_id)
        except SourceServiceError:
            raise
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS830", "Project build failed.") from exc
        finally:
            session.workspace.close()

    def navigate(self, context: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        session = self._session(context, request, SOURCE_READ)
        try:
            with _native_snapshot(session) as snapshot:
                root = _snapshot_root(snapshot)
                project = ProjectContext.load(
                    root, validate_lock=True,
                )
                roots = _snapshot_external_roots(snapshot)
                result = self._run_navigation(
                    project,
                    roots,
                    request,
                    context,
                )
                _reject_native_paths(result, (root, *roots.values()))
                _snapshot_recheck(snapshot)
                self._reauthorize(session, context, SOURCE_READ)
            return _portable_result(result, project_id=session.record.project_id)
        except SourceServiceError:
            raise
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS831", "Project navigation failed.") from exc
        finally:
            session.workspace.close()

    def resource(self, context: Any, project_id: str, relative_path: str | None) -> dict[str, Any]:
        request: dict[str, Any] = {"projectId": project_id}
        if relative_path is None:
            described = self.describe(context, project_id)
            return described["projects"][0]
        request["paths"] = [relative_path]
        return self.read(context, request)["files"][0]

    def _session(
        self,
        context: Any,
        request: Mapping[str, Any],
        grant: str,
        *,
        writable: bool = False,
    ) -> _ProjectSession:
        project_id = _required_text(request.get("projectId"), "projectId")
        projection = request.get("authorityProjectionDigest")
        if projection is not None:
            projection = _required_digest(projection, "authorityProjectionDigest")
        try:
            record = self._authority.authorize(
                context,
                project_id,
                grant,
                projection,
            )
            workspace = self._workspace_factory.open_project(
                record,
                writable=writable,
            )
            roots = (
                dict(record.external_roots)
                if EXTERNAL_ROOT_READ in record.grants
                else {}
            )
            return _ProjectSession(record, workspace, roots)
        except Exception as exc:
            raise _mapped_error(exc, "HOCUS822", "Project access was denied.") from exc

    def _read_session(
        self,
        context: Any,
        request: Mapping[str, Any],
    ) -> tuple[_ProjectSession, str]:
        scope = _optional_text(request.get("scope"), "scope") or "project"
        if scope == "project":
            if request.get("externalAlias") is not None:
                raise SourceServiceError(
                    "HOCUS821", "Project scope cannot carry externalAlias."
                )
            return self._session(context, request, SOURCE_READ), scope
        if scope != "external":
            raise SourceServiceError("HOCUS821", "Source scope is unsupported.")
        alias = _required_text(request.get("externalAlias"), "externalAlias")
        project_id = _required_text(request.get("projectId"), "projectId")
        projection = request.get("authorityProjectionDigest")
        if projection is not None:
            projection = _required_digest(projection, "authorityProjectionDigest")
        try:
            record = self._authority.authorize(
                context,
                project_id,
                EXTERNAL_ROOT_READ,
                projection,
                external_alias=alias,
            )
            roots = dict(record.external_roots)
            root = roots.get(alias)
            if root is None:
                raise SourceServiceError(
                    "HOCUS825", "External alias is not approved for this connection."
                )
            opener = getattr(self._workspace_factory, "open_external", None)
            if not callable(opener):
                raise SourceServiceError(
                    "HOCUS825", "External source workspace is unavailable."
                )
            identity = dict(record.external_root_identities).get(alias)
            if identity is None:
                raise SourceServiceError(
                    "HOCUS824", "External root identity binding is unavailable."
                )
            workspace = opener(root, expected_identity=identity)
            return _ProjectSession(record, workspace, roots), scope
        except Exception as exc:
            raise _mapped_error(
                exc, "HOCUS825", "External source access was denied."
            ) from exc

    def _describe_record(self, record: AuthorizedProject) -> dict[str, Any]:
        if isinstance(record, Mapping):
            return _portable_details(record)
        metadata = getattr(record, "public_metadata", None)
        if not isinstance(metadata, Mapping):
            raise SourceServiceError(
                "HOCUS822", "Authorized project metadata is unavailable."
            )
        return _portable_details(metadata)

    def _describe_authorized(
        self,
        context: Any,
        public: Mapping[str, Any],
    ) -> dict[str, Any]:
        project_id = _record_project_id(public)
        if project_id is None:
            raise SourceServiceError("HOCUS822", "Project identity is malformed.")
        request: dict[str, Any] = {"projectId": project_id}
        projection = public.get("authorityProjectionDigest")
        if isinstance(projection, str):
            request["authorityProjectionDigest"] = projection
        session = self._session(context, request, SOURCE_READ)
        try:
            metadata = self._describe_record(session.record)
            enriched = enrich_project_description(
                metadata,
                record=session.record,
                workspace=session.workspace,
            )
            self._reauthorize(session, context, SOURCE_READ)
            return enriched
        finally:
            session.workspace.close()

    def _run_build(
        self,
        session: _ProjectSession,
        project: ProjectContext,
        roots: Mapping[str, str | Path],
        snapshot: Any,
        action: str,
        request: Mapping[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        if action not in {"format", "check", "compile", "lock_update"}:
            raise SourceServiceError("HOCUS821", "Unsupported project build action.")
        if action == "lock_update":
            return self._lock_update(
                session, project, roots, snapshot, request, context,
            )
        source_path = request.get("sourcePath")
        entry_path = request.get("entryPath")
        if action == "format":
            source_path = _required_text(source_path, "sourcePath")
            return format_project_module_path(
                project.root, source_path, cancelled=context.is_cancelled,
            ).to_dict()
        entry = _required_text(entry_path, "entryPath")
        mixed = bool(roots)
        if action == "check":
            result = _check_project(
                project, entry, roots, mixed, context.is_cancelled,
            )
            return result.to_dict()
        bundle = _compile_project(
            project, entry, roots, mixed, context.is_cancelled,
        )
        return {"stage": "compile", "valid": True, "bundle": bundle.to_dict()}

    def _lock_update(
        self,
        session: _ProjectSession,
        project: ProjectContext,
        roots: Mapping[str, str | Path],
        snapshot: Any,
        request: Mapping[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        if request.get("writeIntent") != "update_generated_lock":
            raise SourceServiceError(
                "HOCUS821",
                "lock_update requires writeIntent=update_generated_lock.",
            )
        expected_aliases = {
            item[0]
            for item in getattr(session.record.projection, "external_aliases", ())
        }
        if set(roots) != expected_aliases:
            raise SourceServiceError(
                "HOCUS830",
                "Lock update requires the complete approved external alias mapping.",
            )
        entries = _path_batch(
            request.get("entryPaths"),
            _configured_limit(
                self._authority, "workspace_enumeration_limit", 1000, 4096,
            ),
        )
        create, expected = _lock_update_expectation(request)
        if project.lock_path is None:
            raise SourceServiceError(
                "HOCUS830", "Project has no generated lock path."
            )
        relative = project.lock_path.relative_to(project.root).as_posix()
        raw_expected = _generated_publication_authority(
            session.workspace, relative, create=create,
        )
        if project.manifest_version in {4, 5}:
            function = (
                update_project_mixed_control_lock if roots else update_project_control_lock
            )
        else:
            function = update_project_mixed_module_lock if roots else update_project_module_lock
        kwargs: dict[str, Any] = {
            "allow_write": True,
            "expected_lock_digest": expected,
            "cancelled": context.is_cancelled,
        }
        if roots:
            result = function(project.root, entries, roots, **kwargs)
        else:
            result = function(project.root, entries, **kwargs)
        content = _snapshot_generated(snapshot, relative)
        prepared = session.workspace._prepare_publish(
            relative,
            content,
            expected_digest=raw_expected,
            create=create,
            allowed_kinds=_generated_lock_kinds(),
        )
        output = {
            "stage": "lock_update",
            "valid": True,
            "derivation": result.to_dict(),
            "publication": _client_payload(prepared.receipt),
        }
        response = _portable_result(output, project_id=session.record.project_id)
        _reject_native_paths(response, (project.root, *roots.values()))
        response = self.prepare_tool_response(
            LOCK_RESPONSE_SUMMARY, response, code="HOCUS830",
        )
        with _write_authority_lease(
            self._authority, context, session.record, GENERATED_LOCK_UPDATE,
        ):
            _snapshot_recheck(snapshot)
            snapshot.close()
            session.workspace._commit_prepared(prepared)
        return response

    def _run_navigation(
        self,
        project: ProjectContext,
        roots: Mapping[str, str | Path],
        request: Mapping[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        operation = _required_text(request.get("operation"), "operation")
        if operation not in {"completion", "definition"}:
            raise SourceServiceError("HOCUS821", "Navigation operation is unsupported.")
        path = _required_text(request.get("path"), "path")
        offset = _bounded_int(request.get("offset"), 0, MAX_PAYLOAD_BYTES)
        source = request.get("source")
        if source is not None and type(source) is not str:
            raise SourceServiceError("HOCUS821", "Dirty source must be text.")
        if source is not None:
            _check_payload(
                source,
                _configured_limit(
                    self._authority,
                    "workspace_payload_bytes",
                    MAX_PAYLOAD_BYTES,
                    8 * 1024 * 1024,
                ),
            )
        limit = _bounded_int(request.get("limit", 200), 1, 1000)
        result = _navigate_project(
            project,
            path,
            offset,
            operation,
            source,
            roots,
            limit,
            context.is_cancelled,
        )
        return result.to_dict()

    def _reauthorize(
        self,
        session: _ProjectSession,
        context: Any,
        grant: str,
        *,
        external_alias: str | None = None,
    ) -> None:
        self._authority.authorize(
            context,
            session.record.project_id,
            grant,
            session.record.projection_digest,
            external_alias=external_alias,
        )

    def _invalidate(
        self,
        context: Any,
        project_id: str,
        paths: Sequence[str] = (),
    ) -> None:
        callback = getattr(self._authority, "invalidate", None)
        try:
            if callback is not None:
                callback(project_id, "source_write")
        except Exception as exc:
            _postcommit_housekeeping_failed(
                self._authority, context, project_id, exc,
            )
    def _workspace_resources(self, context: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        remaining = _configured_limit(
            self._authority, "workspace_enumeration_limit", 1000, 4096,
        )
        for public in self._authority.list_projects(context):
            project_id = _record_project_id(public)
            if project_id is None:
                continue
            projection = (
                public.get("authorityProjectionDigest")
                if isinstance(public, Mapping)
                else None
            )
            request = {"projectId": project_id}
            if isinstance(projection, str):
                request["authorityProjectionDigest"] = projection
            session = self._session(context, request, SOURCE_READ)
            try:
                generation = (
                    public.get("grantGeneration")
                    if isinstance(public, Mapping)
                    else None
                )
                output.append(
                    _project_resource(project_id, projection, generation)
                )
                cursor = None
                while remaining > 0:
                    page = session.workspace.glob(
                        "*",
                        cursor=cursor,
                        limit=min(remaining, 500),
                        case_sensitive=True,
                        include_generated=False,
                    )
                    files = getattr(page, "files", ())
                    output.extend(
                        _file_resource(project_id, projection, _client_payload(item))
                        for item in files
                    )
                    remaining -= len(files)
                    cursor = getattr(page, "next_cursor", None)
                    if cursor is None:
                        break
                self._reauthorize(session, context, SOURCE_READ)
            finally:
                session.workspace.close()
            if remaining <= 0:
                break
        return sorted(output, key=lambda item: str(item["uri"]))

def _default_workspace_factory() -> type[WorkspaceFactory]:
    try:
        from .workspace_io import WorkspaceIO
    except ImportError as exc:
        raise SourceServiceError(
            "HOCUS822", "Descriptor-safe source workspace is unavailable."
        ) from exc
    return WorkspaceIO


def _native_snapshot(
    session: _ProjectSession,
    *,
    writable_generated: bool = False,
) -> AbstractContextManager[Any]:
    builder = getattr(session.workspace, "native_snapshot", None)
    if not callable(builder):
        raise SourceServiceError(
            "HOCUS830",
            "Handle-authenticated native project snapshots are unavailable.",
        )
    return builder(
        include_external_roots=session.external_roots,
        writable_generated=writable_generated,
    )


def _snapshot_root(snapshot: Any) -> Path:
    root = getattr(snapshot, "root", None)
    if not isinstance(root, Path):
        raise SourceServiceError("HOCUS830", "Native project snapshot is malformed.")
    return root


def _snapshot_external_roots(snapshot: Any) -> Mapping[str, Path]:
    roots = getattr(snapshot, "external_roots", {})
    if not isinstance(roots, Mapping) or any(
        not isinstance(alias, str) or not isinstance(root, Path)
        for alias, root in roots.items()
    ):
        raise SourceServiceError(
            "HOCUS830", "Native external-root snapshot is malformed."
        )
    return roots


def _snapshot_recheck(snapshot: Any) -> None:
    callback = getattr(snapshot, "recheck", None)
    if not callable(callback):
        raise SourceServiceError("HOCUS830", "Native snapshot cannot be rechecked.")
    callback()


def _snapshot_generated(snapshot: Any, relative_path: str) -> bytes:
    callback = getattr(snapshot, "read_generated", None)
    if not callable(callback):
        raise SourceServiceError(
            "HOCUS830", "Native snapshot cannot return generated output."
        )
    value = callback(relative_path)
    if not isinstance(value, bytes):
        raise SourceServiceError(
            "HOCUS830", "Native generated output is malformed."
        )
    return value


def _generated_lock_kinds() -> tuple[Any, ...]:
    try:
        from .workspace_io import WorkspaceFileKind
    except ImportError as exc:
        raise SourceServiceError(
            "HOCUS830", "Generated lock publication policy is unavailable."
        ) from exc
    return (WorkspaceFileKind.GENERATED_LOCK,)


def _navigate_project(project, path, offset, operation, source, roots, limit, cancelled):
    control = project.manifest_version in {4, 5}
    mixed = bool(roots)
    if operation == "completion":
        local = complete_control_path if control else complete_path
        dirty = complete_control_project_source if control else complete_project_source
        mixed_saved = complete_mixed_control_path if control else complete_mixed_path
        mixed_dirty = (
            complete_mixed_control_project_source if control
            else complete_mixed_project_source
        )
        extra = {"limit": limit, "cancelled": cancelled}
    else:
        local = definition_control_path if control else definition_path
        dirty = definition_control_project_source if control else definition_project_source
        mixed_saved = definition_mixed_control_path if control else definition_mixed_path
        mixed_dirty = (
            definition_mixed_control_project_source if control
            else definition_mixed_project_source
        )
        extra = {"cancelled": cancelled}
    if mixed:
        extra["module_roots"] = roots
        function = mixed_saved if source is None else mixed_dirty
    else:
        function = local if source is None else dirty
    if source is None:
        return function(project.root, path, offset, **extra)
    return function(project.root, path, source, offset, **extra)
