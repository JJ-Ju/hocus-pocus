"""Dynamic read-only resources for approved HocusScript source projects."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from hocuspocus.hocusscript.project_services import SourceServiceError

from ..context import RequestContext


class SourceResourceOperationsMixin:
    """Resolve hocus-source URIs through the same per-request authority as tools."""

    def read_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        source = self._read_source_dynamic_resource(uri, context)
        if source is not None:
            return source
        return super().read_dynamic_resource(uri, context)

    def list_workspace_resources(
        self,
        context: RequestContext,
        cursor: str | None,
    ) -> dict[str, Any]:
        service = self._get_source_workspace_service()
        if not service.has_valid_session(context):
            return {"resources": []}
        try:
            service.rate(context, "resource.list", None)
            result = service.list_resources(context, cursor)
            service.ensure_response(result)
        except SourceServiceError as exc:
            service.audit(
                context,
                "resource.list",
                None,
                success=False,
                code=exc.code,
                arguments={"cursor": cursor},
            )
            from .source_workspace import _source_rpc_error

            raise _source_rpc_error(exc) from exc
        service.audit(
            context,
            "resource.list",
            None,
            success=True,
            arguments={"cursor": cursor},
            result=result,
        )
        return result

    def _read_source_dynamic_resource(
        self,
        uri: str,
        context: RequestContext,
    ) -> dict[str, object] | None:
        service = None
        project_id = None
        relative_path = None
        try:
            parsed = _parse_source_uri(uri)
            if parsed is None:
                return None
            project_id, relative_path = parsed
            context.raise_if_cancelled()
            service = self._get_source_workspace_service()
            service.require_session(context)
            service.rate(context, "resource.read", project_id)
            payload = service.resource(
                context, project_id, relative_path,
            )
            service.ensure_response(payload)
        except SourceServiceError as exc:
            if service is not None:
                service.audit(
                    context,
                    "resource.read",
                    project_id,
                    success=False,
                    code=exc.code,
                    arguments={"uri": uri, "path": relative_path},
                )
            from .source_workspace import _source_rpc_error

            raise _source_rpc_error(exc) from exc
        service.audit(
            context,
            "resource.read",
            project_id,
            success=True,
            arguments={"uri": uri, "path": relative_path},
            result=payload,
        )
        context.raise_if_cancelled()
        if relative_path is not None:
            return _source_file_response(uri, relative_path, payload)
        return self._resource_response(uri, payload)

    def resource_templates_payload(self) -> list[dict[str, object]]:
        inherited = list(super().resource_templates_payload())
        return [*_source_resource_templates(), *inherited]


def _parse_source_uri(uri: str) -> tuple[str, str | None] | None:
    prefix = "hocus-source://"
    if not uri.startswith(prefix):
        return None
    authored = uri.removeprefix(prefix)
    project_id, separator, raw_path = authored.partition("/")
    if (
        not project_id
        or len(project_id) > 256
        or any(character in project_id for character in "\\?#%")
    ):
        raise SourceServiceError("HOCUS821", "Invalid hocus-source project URI.")
    if not separator:
        return project_id, None
    if not raw_path or "\\" in raw_path:
        raise SourceServiceError("HOCUS821", "Invalid hocus-source file URI.")
    try:
        relative = unquote(raw_path, errors="strict")
    except UnicodeError as exc:
        raise SourceServiceError("HOCUS821", "Invalid hocus-source URI encoding.") from exc
    if (
        not relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or quote(relative, safe="/-._~") != raw_path
    ):
        raise SourceServiceError("HOCUS821", "Invalid hocus-source relative path.")
    return project_id, relative


def _source_resource_templates() -> tuple[dict[str, object], ...]:
    return (
        {
            "uriTemplate": "hocus-source://{projectId}",
            "name": "HocusScript Project",
            "description": "Read current authorized metadata for one opaque project id. The host root is never returned.",
            "mimeType": "application/json",
            "payloadSummary": "Portable project identity, language and manifest status, grants, relative directories, aliases, and authority digest.",
            "examples": [],
        },
        {
            "uriTemplate": "hocus-source://{projectId}/{relativePath}",
            "name": "HocusScript Source File",
            "description": "Read one currently authorized authored source file by canonical project-relative path.",
            "mimeType": "text/x-hocusscript",
            "payloadSummary": "UTF-8 source content, exact raw digest, and portable project-relative identity.",
            "examples": [],
        },
    )


def _source_file_response(
    uri: str,
    relative_path: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    content = payload.get("content")
    digest = payload.get("rawDigest")
    if not isinstance(content, str) or not isinstance(digest, str):
        raise SourceServiceError(
            "HOCUS825", "Source resource payload is malformed."
        )
    mime_type = (
        "application/toml"
        if relative_path.casefold() == "hocus.project.toml"
        else "text/x-hocusscript"
    )
    return {
        "contents": [{
            "uri": uri,
            "mimeType": mime_type,
            "text": content,
            "_meta": {"rawDigest": digest},
        }]
    }
