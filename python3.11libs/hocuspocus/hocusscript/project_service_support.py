"""Portable validation and serialization helpers for H6 project services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

MAX_READ_FILES = 16
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
APPLY_RESPONSE_SUMMARY = "Digest-guarded source edit"
EXPORT_RESPONSE_SUMMARY = "Authenticated export publication"
LOCK_RESPONSE_SUMMARY = "Native project build result"


class SourceServiceError(RuntimeError):
    """Portable typed failure for the source workspace boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = portable_details(details)


class PreparedSourceResponse(dict[str, Any]):
    """Inner payload backed by the exact serialized public MCP response."""

    __slots__ = ("_serialized",)

    def __init__(self, response: Mapping[str, Any], serialized: bytes) -> None:
        structured = response.get("structuredContent")
        if not isinstance(structured, Mapping):
            raise TypeError("Prepared source response requires structured content.")
        super().__init__(structured)
        self._serialized = serialized

    @property
    def serialized_size(self) -> int:
        return len(self._serialized)

    def tool_result(self) -> dict[str, Any]:
        result = json.loads(self._serialized)
        if not isinstance(result, dict):  # pragma: no cover - construction invariant
            raise TypeError("Prepared source response is malformed.")
        return result


def build_source_tool_response(
    summary: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the one public result shape used by source MCP tools."""

    return {
        "content": [{"type": "text", "text": summary}],
        "structuredContent": dict(payload),
        "isError": False,
    }


def prepare_source_tool_response(
    summary: str,
    payload: Mapping[str, Any],
    *,
    maximum: int,
    code: str,
) -> PreparedSourceResponse:
    """Freeze and size-check the exact public result before mutation."""

    try:
        serialized = json.dumps(
            build_source_tool_response(summary, payload),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        response = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise SourceServiceError(code, "Source response is not serializable.") from exc
    if len(serialized) > maximum:
        raise SourceServiceError(
            code,
            "Source response exceeds its configured byte limit.",
            details={"actualBytes": len(serialized), "limitBytes": maximum},
        )
    return PreparedSourceResponse(response, serialized)


def ensure_source_payload(
    payload: Mapping[str, Any],
    *,
    maximum: int,
    code: str,
) -> None:
    """Size-check a non-tool resource payload."""

    try:
        size = len(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise SourceServiceError(code, "Source response is not serializable.") from exc
    if size > maximum:
        raise SourceServiceError(
            code,
            "Source response exceeds its configured byte limit.",
            details={"actualBytes": size, "limitBytes": maximum},
        )


def source_response_limit(authority: Any) -> int:
    return configured_limit(
        authority, "workspace_payload_bytes",
        MAX_PAYLOAD_BYTES, 8 * 1024 * 1024,
    )


def source_tool_response(
    summary: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a prepared result verbatim, or build the same public shape."""

    if isinstance(payload, PreparedSourceResponse):
        return payload.tool_result()
    return build_source_tool_response(summary, payload)


def record_project_id(record: Any) -> str | None:
    if isinstance(record, Mapping):
        value = record.get("projectId")
        return value if isinstance(value, str) else None
    value = getattr(record, "project_id", None)
    return value if isinstance(value, str) else None


def recheck_descriptions(
    authority: Any,
    context: Any,
    projects: Sequence[Mapping[str, Any]],
) -> None:
    current = {
        record_project_id(item): item.get("authorityProjectionDigest")
        for item in authority.list_projects(context)
        if isinstance(item, Mapping)
    }
    for project in projects:
        project_id = project.get("projectId")
        if current.get(project_id) != project.get("authorityProjectionDigest"):
            raise SourceServiceError(
                "HOCUS824", "Project authority changed during description."
            )


def project_resource(
    project_id: str,
    projection_digest: Any,
    grant_generation: Any = None,
) -> dict[str, Any]:
    return {
        "uri": f"hocus-source://{project_id}",
        "name": f"HocusScript project {project_id}",
        "description": "Current authorized HocusScript project metadata.",
        "mimeType": "application/json",
        "_meta": {
            "authorityProjectionDigest": projection_digest,
            "grantGeneration": grant_generation,
            "readOnly": True,
        },
    }


def file_resource(
    project_id: str,
    projection_digest: Any,
    file: Mapping[str, Any],
) -> dict[str, Any]:
    relative = file.get("path")
    digest = file.get("rawDigest")
    if not isinstance(relative, str) or not isinstance(digest, str):
        raise SourceServiceError(
            "HOCUS825", "Workspace enumeration returned malformed file metadata."
        )
    return {
        "uri": f"hocus-source://{project_id}/{quote(relative, safe='/-._~')}",
        "name": relative,
        "description": "Authorized HocusScript authored file.",
        "mimeType": (
            "application/toml"
            if relative.casefold() == "hocus.project.toml"
            else "text/x-hocusscript"
        ),
        "size": file.get("byteLength"),
        "_meta": {
            "rawDigest": digest,
            "authorityProjectionDigest": projection_digest,
            "readOnly": True,
        },
    }


def portable_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        blocked = {
            "approvedRoot", "approved_root", "physicalPath", "physicalRoot",
            "projectDirectory", "rootPath", "nativeSourcePath", "path", "root",
            "rootIdentityDigest", "externalRootIdentities",
        }
        return {
            str(key): portable_details(item)
            for key, item in value.items()
            if str(key) not in blocked
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [portable_details(item) for item in value]
    if isinstance(value, Path):
        return value.name
    return value


def mapped_error(
    exc: Exception,
    fallback: str,
    message: str,
) -> SourceServiceError:
    if isinstance(exc, SourceServiceError):
        return exc
    authored = getattr(exc, "code", None)
    code = (
        authored
        if isinstance(authored, str) and authored.startswith("HOCUS82")
        else fallback
    )
    details = getattr(exc, "details", None)
    return SourceServiceError(code, message, details=details)


def required_text(value: Any, field: str) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise SourceServiceError(
            "HOCUS821", f"{field} must be bounded non-empty text."
        )
    return value


def optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field)


def required_digest(value: Any, field: str) -> str:
    text = required_text(value, field)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise SourceServiceError(
            "HOCUS821", f"{field} must be an exact SHA-256 digest."
        )
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise SourceServiceError(
            "HOCUS821", f"{field} must be an exact SHA-256 digest."
        ) from exc
    return text


def lock_update_expectation(
    request: Mapping[str, Any],
) -> tuple[bool, str | None]:
    state = request.get("expectedLockState")
    if state == "absent":
        if request.get("expectedLockDigest") is not None:
            raise SourceServiceError(
                "HOCUS821",
                "A missing-lock update cannot carry expectedLockDigest.",
            )
        return True, None
    if state == "present":
        return False, required_digest(
            request.get("expectedLockDigest"), "expectedLockDigest",
        )
    raise SourceServiceError(
        "HOCUS821",
        "lock_update requires expectedLockState=absent or present.",
    )


def generated_publication_authority(
    workspace: Any,
    relative_path: str,
    *,
    create: bool,
) -> str | None:
    try:
        current = workspace.generated_digest(relative_path)
    except Exception as exc:
        if (
            create
            and getattr(exc, "code", None) == "HOCUS825"
            and getattr(exc, "message", None) == "Workspace file does not exist."
        ):
            return None
        raise
    if create:
        raise SourceServiceError(
            "HOCUS826",
            "Generated lock already exists; use exact-digest replacement.",
        )
    return current


def bounded_int(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SourceServiceError(
            "HOCUS821", f"Integer must be between {minimum} and {maximum}."
        )
    return value


def path_batch(
    value: Any,
    maximum: int = MAX_READ_FILES,
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= maximum
    ):
        raise SourceServiceError(
            "HOCUS821", f"Path list must contain 1 to {maximum} entries."
        )
    return tuple(required_text(item, "path") for item in value)


def configured_limit(
    authority: Any,
    name: str,
    default: int,
    ceiling: int,
) -> int:
    settings = getattr(authority, "settings", None)
    value = getattr(settings, name, default)
    if type(value) is not int or not 1 <= value <= ceiling:
        raise SourceServiceError(
            "HOCUS821", f"Configured {name} limit is invalid."
        )
    return value


def check_payload(
    value: Any,
    maximum: int = MAX_PAYLOAD_BYTES,
) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise SourceServiceError(
            "HOCUS821", "Request content must be JSON-compatible."
        ) from exc
    if size > maximum:
        raise SourceServiceError("HOCUS825", "Source request exceeds its byte limit.")


def rate_category(event: str) -> tuple[str | None, str | None, int]:
    if event == "file.search":
        return "search", "workspace_rate_search_per_minute", 30
    if event in {"file.apply_patch", "file.write_export"}:
        return "write", "workspace_rate_write_per_minute", 20
    if event == "project.build":
        return "build", "workspace_rate_build_per_minute", 6
    return None, None, 0


def source_uri(
    project_id: str,
    relative_path: str,
    *,
    external_alias: str | None = None,
    external_aliases: Sequence[Sequence[Any]] = (),
) -> str:
    encoded = quote(relative_path, safe="/-._~")
    if external_alias is None:
        return f"hocus-source://{project_id}/{encoded}"
    for record in external_aliases:
        if (
            len(record) >= 2
            and record[0] == external_alias
            and isinstance(record[1], str)
        ):
            return f"hocus-module://{record[1]}/{encoded}"
    raise SourceServiceError(
        "HOCUS823", "External source alias is not present in the authority projection."
    )


def client_payload(value: Any) -> Any:
    converter = getattr(value, "client_payload", None)
    if callable(converter):
        return converter()
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return converter()
    return value


def portable_payload(value: Any) -> Any:
    value = client_payload(value)
    if isinstance(value, Mapping):
        return {
            str(key): portable_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [portable_payload(item) for item in value]
    if isinstance(value, Path):
        raise SourceServiceError(
            "HOCUS830", "Source result attempted to expose a native path."
        )
    return value


def portable_result(value: Any, *, project_id: str) -> dict[str, Any]:
    value = client_payload(value)
    if isinstance(value, Mapping):
        result = portable_payload(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = {"items": portable_payload(value)}
    else:
        raise SourceServiceError(
            "HOCUS830", "Source service returned an invalid result."
        )
    result.setdefault("projectId", project_id)
    return result


def reject_native_paths(value: Any, roots: Sequence[str | Path]) -> None:
    """Fail closed if a native callback retained a temporary absolute path."""

    forbidden = tuple(
        str(Path(root)).replace("\\", "/").rstrip("/").casefold()
        for root in roots
        if str(root)
    )
    pending: list[Any] = [client_payload(value)]
    inspected = 0
    while pending:
        item = pending.pop()
        inspected += 1
        if inspected > 100_000:
            raise SourceServiceError(
                "HOCUS830", "Source result exceeds its portable traversal bound."
            )
        if isinstance(item, Mapping):
            pending.extend(item.values())
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray),
        ):
            pending.extend(item)
        elif isinstance(item, Path):
            raise SourceServiceError(
                "HOCUS830", "Source result attempted to expose a native path."
            )
        elif isinstance(item, str):
            normalized = item.replace("\\", "/").casefold()
            if any(
                normalized == root or normalized.startswith(root + "/")
                for root in forbidden
            ):
                raise SourceServiceError(
                    "HOCUS830", "Source result attempted to expose a native path."
                )


def audit_details(
    event: str,
    *,
    arguments: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
    grant_generation: int | None,
    error_code: str | None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "action": event,
        "argumentDigest": _json_digest(arguments or {}),
    }
    if error_code is not None:
        details["errorCode"] = error_code
    if grant_generation is not None:
        details["grantGeneration"] = grant_generation
    relative = _relative_argument(arguments or {})
    if relative is not None:
        details["relativePath"] = relative
    external = (arguments or {}).get("externalAlias")
    if isinstance(external, str):
        details["externalAlias"] = external
    if result is not None:
        count = _result_count(result)
        if count is not None:
            details["resultCount"] = count
        digest = _result_digest(result)
        if digest is not None:
            details["resultingDigest"] = digest
    return details


def audit_grant_generation(
    authority: Any,
    context: Any,
    project_id: str | None,
) -> int | None:
    if project_id is None:
        return None
    for item in authority.list_projects(context):
        if isinstance(item, Mapping) and item.get("projectId") == project_id:
            value = item.get("grantGeneration")
            return value if type(value) is int else None
    return None


def _json_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = b"<invalid>"
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _relative_argument(arguments: Mapping[str, Any]) -> str | None:
    for key in ("path", "destination", "sourcePath", "entryPath"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    for key in ("paths", "entryPaths"):
        value = arguments.get(key)
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
            and len(value) == 1
            and isinstance(value[0], str)
        ):
            return value[0]
    return None


def _result_count(result: Mapping[str, Any]) -> int | None:
    for key in ("projectCount", "matchCount", "fileCount"):
        value = result.get(key)
        if type(value) is int:
            return value
    resources = result.get("resources")
    if isinstance(resources, list):
        return len(resources)
    return None


def _result_digest(result: Mapping[str, Any]) -> str | None:
    digests: set[str] = set()
    pending: list[Any] = [result]
    while pending and len(digests) <= 1024:
        value = pending.pop()
        if isinstance(value, Mapping):
            for key, item in value.items():
                if (
                    key in {"rawDigest", "sourceDigest", "bundleDigest", "lockDigest"}
                    and isinstance(item, str)
                    and item.startswith("sha256:")
                ):
                    digests.add(item)
                elif isinstance(item, (Mapping, list, tuple)):
                    pending.append(item)
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    if not digests:
        return None
    if len(digests) == 1:
        return next(iter(digests))
    return _json_digest(sorted(digests))
