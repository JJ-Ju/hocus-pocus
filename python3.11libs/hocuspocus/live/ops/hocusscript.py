"""Preview-only MCP operations for HocusScript source."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript import compile_source

from ..context import RequestContext


class HocusScriptOperationsMixin:
    _GRAPH_SPEC_SCHEMA_RESOURCE_URI = "houdini://documents/schema/graph-spec/v0.1"

    def document_compile_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        del context
        source = arguments.get("source")
        source_name = arguments.get("source_name", "<mcp-source>")
        strict = arguments.get("strict", True)
        if not isinstance(source, str):
            raise JsonRpcError(INVALID_PARAMS, "source must be a string.")
        if not isinstance(source_name, str) or not source_name.strip():
            raise JsonRpcError(INVALID_PARAMS, "source_name must be a non-empty string when provided.")
        if len(source_name) > 1024:
            raise JsonRpcError(INVALID_PARAMS, "source_name must not exceed 1024 characters.")
        if not isinstance(strict, bool):
            raise JsonRpcError(INVALID_PARAMS, "strict must be a boolean when provided.")
        result = compile_source(source, source_name.strip(), strict=strict).to_dict()
        if result["valid"]:
            summary = "Compiled HocusScript through the structural preview stage without mutating Houdini."
        else:
            summary = f"HocusScript structural compilation reported {result['diagnosticCount']} diagnostic(s)."
        return self._tool_response(summary, result)

    def read_graph_spec_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        path = core_paths.package_root() / "docs" / "schemas" / "graph-spec-v0.1.schema.json"
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return self._resource_response(self._GRAPH_SPEC_SCHEMA_RESOURCE_URI, payload)
