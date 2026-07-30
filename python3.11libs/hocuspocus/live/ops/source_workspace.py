"""Live MCP tool surface for approved HocusScript source workspaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hocuspocus.core.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError
from hocuspocus.core.mcp_types import ToolDefinition, ToolRegistry
from hocuspocus.core.policy import OBSERVE, PATH_POLICY_ERROR, POLICY_DENIED_ERROR
from hocuspocus.hocusscript.project_services import (
    SourceServiceError,
    SourceWorkspaceService,
)
from hocuspocus.hocusscript.project_service_support import (
    APPLY_RESPONSE_SUMMARY,
    EXPORT_RESPONSE_SUMMARY,
    LOCK_RESPONSE_SUMMARY,
    source_tool_response,
)

from ..context import RequestContext


class SourceWorkspaceOperationsMixin:
    """Register and dispatch the exact seven-operation H6 source surface."""

    _source_workspace_authority: Any
    _source_workspace_factory: Any
    _source_workspace_service: SourceWorkspaceService | None

    def bind_source_workspace(
        self,
        authority: Any,
        *,
        workspace_factory: Any = None,
    ) -> None:
        """Inject the host-owned authority and optional descriptor-safe factory."""

        self._source_workspace_authority = authority
        self._source_workspace_factory = workspace_factory
        self._source_workspace_service = None

    def register_source_tools(self, registry: ToolRegistry) -> None:
        for definition in _source_tool_definitions(self):
            registry.register(definition)

    def source_project_describe(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "project.describe",
            "Authorized project metadata",
            context,
            arguments,
            lambda service: service.describe(context, arguments.get("projectId")),
        )

    def source_file_search(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "file.search",
            "Bounded source search",
            context,
            arguments,
            lambda service: service.search(context, arguments),
        )

    def source_file_read(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "file.read",
            "Authorized source content",
            context,
            arguments,
            lambda service: service.read(context, arguments),
        )

    def source_file_apply_patch(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "file.apply_patch",
            APPLY_RESPONSE_SUMMARY,
            context,
            arguments,
            lambda service: service.apply_patch(context, arguments),
        )

    def source_file_write_export(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "file.write_export",
            EXPORT_RESPONSE_SUMMARY,
            context,
            arguments,
            lambda service: service.write_export(context, arguments),
        )

    def source_project_build(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "project.build",
            LOCK_RESPONSE_SUMMARY,
            context,
            arguments,
            lambda service: service.build(context, arguments),
        )

    def source_project_navigate(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        return self._source_call(
            "project.navigate",
            "Native project navigation result",
            context,
            arguments,
            lambda service: service.navigate(context, arguments),
        )

    def _source_call(
        self,
        event: str,
        summary: str,
        context: RequestContext,
        arguments: Mapping[str, Any],
        callback: Any,
    ) -> dict[str, Any]:
        context.raise_if_cancelled()
        service = self._get_source_workspace_service()
        project_id = arguments.get("projectId")
        if not isinstance(project_id, str):
            project_id = None
        committed = _committed_source_call(event, arguments)
        try:
            service.require_session(context)
            service.rate(context, event, project_id)
            payload = callback(service)
            if not committed:
                payload = service.prepare_tool_response(
                    summary, payload, code=_response_error_code(event),
                )
        except SourceServiceError as exc:
            service.audit(
                context,
                event,
                project_id,
                success=False,
                code=exc.code,
                arguments=arguments,
            )
            raise _source_rpc_error(exc) from exc
        service.audit(
            context,
            event,
            project_id,
            success=True,
            arguments=arguments,
            result=payload,
            terminal=committed,
        )
        if not committed:
            context.raise_if_cancelled()
        return source_tool_response(summary, payload)

    def _get_source_workspace_service(self) -> SourceWorkspaceService:
        service = getattr(self, "_source_workspace_service", None)
        if service is not None:
            return service
        authority = getattr(self, "_source_workspace_authority", None) or getattr(
            self, "_workspace_authority", None,
        )
        if authority is None:
            raise SourceServiceError(
                "HOCUS821", "Source workspace authority is not configured."
            )
        service = SourceWorkspaceService(
            authority,
            getattr(self, "_source_workspace_factory", None),
        )
        self._source_workspace_service = service
        return service


def _source_rpc_error(exc: SourceServiceError) -> JsonRpcError:
    if exc.code in {"HOCUS821", "HOCUS822", "HOCUS823", "HOCUS824", "HOCUS825"}:
        rpc_code = POLICY_DENIED_ERROR
        family = "policy"
    elif exc.code == "HOCUS826":
        rpc_code = PATH_POLICY_ERROR
        family = "policy"
    elif exc.code == "HOCUS828":
        rpc_code = INTERNAL_ERROR
        family = "runtime"
    else:
        rpc_code = INVALID_PARAMS
        family = "validation"
    details = exc.details if isinstance(exc.details, Mapping) else {}
    return JsonRpcError(
        rpc_code,
        exc.message,
        {"hocusCode": exc.code, **details},
        family=family,
        retryable=False,
    )


def _committed_source_call(event: str, arguments: Mapping[str, Any]) -> bool:
    return event in {"file.apply_patch", "file.write_export"} or (
        event == "project.build" and arguments.get("action") == "lock_update"
    )


def _response_error_code(event: str) -> str:
    if event == "project.build":
        return "HOCUS830"
    if event == "project.navigate":
        return "HOCUS831"
    if event == "file.write_export":
        return "HOCUS829"
    return "HOCUS825"


def _source_tool_definitions(owner: SourceWorkspaceOperationsMixin) -> tuple[ToolDefinition, ...]:
    common = {
        "projectId": {"type": "string", "minLength": 1, "maxLength": 256},
        "authorityProjectionDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    }
    read_annotations = {"readOnlyHint": True, "idempotentHint": True}
    write_annotations = {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
    }
    return (
        _tool(
            "source.project.describe", "Describe Source Projects",
            "List only projects currently authorized to this connection, or describe one opaque project id. Physical roots are never returned.",
            _schema({"projectId": common["projectId"]}),
            read_annotations, (OBSERVE,), owner.source_project_describe,
            "Authorized project identities, language/manifest status, relative directories, aliases, grants, and authority digest.",
        ),
        _tool(
            "source.file.search", "Search Source Files",
            "Run a bounded filename/glob or UTF-8 text search over authorized authored project files.",
            _schema({
                **common,
                "glob": {"type": "string", "maxLength": 4096},
                "query": {"type": "string", "maxLength": 4096},
                "caseSensitive": {"type": "boolean", "default": False},
                "cursor": {"type": "string", "maxLength": 4096},
                "scope": {
                    "type": "string",
                    "enum": ["project", "external"],
                    "default": "project",
                },
                "externalAlias": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            }, ("projectId",)),
            read_annotations, (OBSERVE,), owner.source_file_search,
            "Project-relative search matches with portable identities and bounded counts.",
        ),
        _tool(
            "source.file.read", "Read Source Files",
            "Read one or a bounded batch of exact authored files through the approved project workspace.",
            _schema({
                **common,
                "paths": _paths_schema(64),
                "scope": {
                    "type": "string",
                    "enum": ["project", "external"],
                    "default": "project",
                },
                "externalAlias": {"type": "string", "minLength": 1, "maxLength": 64},
            }, ("projectId", "paths")),
            read_annotations, (OBSERVE,), owner.source_file_read,
            "UTF-8 source content, exact raw digests, and project-relative file identities.",
        ),
        _tool(
            "source.file.apply_patch", "Apply Source Patch",
            "Exclusively create or exact-digest patch one authored .hocus file or validated project manifest. Generated artifacts and blind overwrite are rejected.",
            _schema({
                **common,
                "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                "mode": {"type": "string", "enum": ["create", "patch"]},
                "expectedDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                "content": {"type": "string"},
                "unifiedDiff": {"type": "string"},
            }, ("projectId", "path", "mode")),
            write_annotations, (OBSERVE,), owner.source_file_apply_patch,
            "Atomic edit receipt with the new raw digest and project-relative identity.",
        ),
        _tool(
            "source.file.write_export", "Write Exported Source",
            "Validate, recompile, and publish a bounded document.export_source handoff through the authorized source workspace.",
            _schema({
                **common,
                "destination": {
                    "type": "string", "minLength": 1, "maxLength": 4096,
                },
                "handoff": {"type": "object"},
                "expectedDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            }, ("projectId", "destination", "handoff")),
            write_annotations, (OBSERVE,), owner.source_file_write_export,
            "Authenticated publication receipt, portable source URI, and exact source digest.",
        ),
        _tool(
            "source.project.build", "Build Source Project",
            "Run exactly one native format, check, compile, or explicit generated-lock update action without introducing a second resolver.",
            _schema({
                **common,
                "action": {"type": "string", "enum": ["format", "check", "compile", "lock_update"]},
                "sourcePath": {"type": "string", "minLength": 1, "maxLength": 4096},
                "entryPath": {"type": "string", "minLength": 1, "maxLength": 4096},
                "entryPaths": _paths_schema(4096),
                "writeIntent": {
                    "type": "string",
                    "enum": ["update_generated_lock"],
                },
                "expectedLockState": {
                    "type": "string",
                    "enum": ["absent", "present"],
                },
                "expectedLockDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            }, ("projectId", "action")),
            {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "sourceGrantByAction": {
                    "format": "source_read",
                    "check": "source_read",
                    "compile": "source_read",
                    "lock_update": "generated_lock",
                },
            },
            (OBSERVE,), owner.source_project_build,
            "Portable diagnostics, format/check receipt, compiled flat Bundle 0.2, module Bundle 0.3, control Bundle 0.4, value Bundle 0.5, or explicit create/exact-digest lock-update receipt.",
        ),
        _tool(
            "source.project.navigate", "Navigate Source Project",
            "Run native completion or go-to-definition over a saved file or supplied dirty source buffer.",
            _schema({
                **common,
                "operation": {"type": "string", "enum": ["completion", "definition"]},
                "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                "offset": {"type": "integer", "minimum": 0, "maximum": 2097152},
                "source": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            }, ("projectId", "operation", "path", "offset")),
            read_annotations, (OBSERVE,), owner.source_project_navigate,
            "Typed completion or definition results with portable URIs, source digests, spans, and lock state.",
        ),
    )


def _tool(
    name: str,
    title: str,
    description: str,
    schema: dict[str, Any],
    annotations: dict[str, Any],
    capabilities: tuple[str, ...],
    handler: Any,
    output: str,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        title=title,
        description=description,
        input_schema=schema,
        annotations=annotations,
        required_capabilities=capabilities,
        handler=handler,
        output_summary=output,
        execution_hint="Use opaque projectId selectors from source.project.describe; never send host paths.",
        failure_notes=[
            "HOCUS821-831 are typed source-boundary failures.",
            "Revocation, expiry, stale authority, stale digests, and path-policy failures fail closed.",
        ],
        examples=[],
    )


def _schema(
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        result["required"] = list(required)
    return result


def _paths_schema(maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": maximum,
        "items": {"type": "string", "minLength": 1, "maxLength": 4096},
    }
