"""Compatibility HocusScript compile surface with capability preflight."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import capability_projection
from hocuspocus.hocusscript import compile_source
from hocuspocus.hocusscript.bundle_graph_validation import required_capabilities

from ..context import RequestContext


class HocusScriptEditorCompileOperationsMixin:
    def document_compile_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        source = arguments.get("source")
        source_name = arguments.get("source_name", "<mcp-source>")
        strict = arguments.get("strict", True)
        if not isinstance(source, str):
            raise JsonRpcError(INVALID_PARAMS, "source must be a string.")
        if not isinstance(source_name, str) or not source_name.strip():
            raise JsonRpcError(
                INVALID_PARAMS, "source_name must be a non-empty string when provided.",
            )
        if len(source_name) > 1024:
            raise JsonRpcError(
                INVALID_PARAMS, "source_name must not exceed 1024 characters.",
            )
        if not isinstance(strict, bool):
            raise JsonRpcError(INVALID_PARAMS, "strict must be a boolean when provided.")
        result = compile_source(source, source_name.strip(), strict=strict).to_dict()
        graph_spec = result.get("graphSpec")
        required = (
            required_capabilities(graph_spec) if isinstance(graph_spec, dict) else []
        )
        result.update(capability_projection(context.permissions, required))
        result.update({
            "lane": "structural_compatibility",
            "supportedLanguageVersions": ["0.1"],
            "applyable": False,
            "nextActions": [
                "Compile a project entry with source.project.build action=compile.",
                "Pass that exact Bundle to document.preview_bundle.",
                "Create an immutable plan with document.plan_bundle.",
                "Apply the retained plan with document.apply_plan.",
            ],
        })
        summary = (
            "Compiled HocusScript through the structural preview stage without mutating Houdini."
            if result["valid"]
            else f"HocusScript structural compilation reported {result['diagnosticCount']} diagnostic(s)."
        )
        return self._tool_response(summary, result)
