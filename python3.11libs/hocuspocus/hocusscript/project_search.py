"""Bounded project/external search composition for H6 source services."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .project_service_support import client_payload, portable_payload


def search_workspace(
    workspace: Any,
    *,
    glob: str | None,
    query: str | None,
    case_sensitive: bool,
    include_manifest: bool,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    maximum = min(offset + limit + 1, 1000)
    if query is not None:
        values = workspace.search(
            query,
            case_sensitive=case_sensitive,
            include_manifest=include_manifest,
            max_results=maximum,
        )
        rows = [client_payload(item) for item in values]
        if glob is not None:
            rows = [
                item for item in rows
                if _glob_matches(str(item.get("path", "")), glob, case_sensitive)
            ]
    else:
        values = workspace.enumerate_files(
            include_manifest=include_manifest,
            include_generated=False,
            max_files=1000,
        )
        rows = [
            {
                **client_payload(item),
                "line": 0,
                "column": 0,
                "preview": "",
            }
            for item in values
            if glob is not None
            and _glob_matches(
                str(client_payload(item).get("path", "")),
                glob,
                case_sensitive,
            )
        ]
    selected = rows[offset: offset + limit]
    result: dict[str, Any] = {
        "matches": portable_payload(selected),
        "matchCount": len(selected),
    }
    if len(rows) > offset + limit:
        result["_nextOffset"] = offset + limit
    return result


def _glob_matches(path: str, pattern: str, case_sensitive: bool) -> bool:
    authored_path = path if case_sensitive else path.casefold()
    authored_pattern = pattern if case_sensitive else pattern.casefold()
    return PurePosixPath(authored_path).match(authored_pattern)
