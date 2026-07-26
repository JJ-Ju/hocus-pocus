"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.core import paths as core_paths

from ..context import RequestContext


class HocusScriptResourceOperationsMixin:
    def read_apply_plan(self, plan_id: str, context: RequestContext) -> dict[str, Any] | None:
        del context
        payload = self._hocus_service_call(lambda: self._documents.apply_plan_resource(plan_id))
        if payload is None:
            return None
        return self._resource_response(f"houdini://documents/plans/{plan_id}", payload)

    def read_graph_spec_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema("graph-spec-v0.2.schema.json", self._GRAPH_SPEC_SCHEMA_RESOURCE_URI)

    def read_legacy_graph_spec_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "graph-spec-v0.1.schema.json", self._LEGACY_GRAPH_SPEC_SCHEMA_RESOURCE_URI
        )

    def read_module_graph_spec_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "graph-spec-v0.3.schema.json", self._MODULE_GRAPH_SPEC_SCHEMA_RESOURCE_URI
        )

    def read_expansion_map_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "expansion-map-v1.schema.json", self._EXPANSION_MAP_SCHEMA_RESOURCE_URI
        )

    def read_resolved_module_set_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "resolved-module-set-v1.schema.json", self._RESOLVED_MODULE_SET_SCHEMA_RESOURCE_URI
        )

    def _read_hocusscript_schema(self, filename: str, uri: str) -> dict[str, Any]:
        path = core_paths.package_root() / "docs" / "schemas" / filename
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return self._resource_response(uri, payload)

    def read_preview_bundle_input_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-preview-bundle-input-v1.schema.json",
            self._PREVIEW_INPUT_SCHEMA_RESOURCE_URI,
        )

    def read_format_source_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-format-source-output-v1.schema.json",
            self._FORMAT_OUTPUT_SCHEMA_RESOURCE_URI,
        )

    def read_complete_source_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-complete-source-output-v1.schema.json",
            self._COMPLETE_OUTPUT_SCHEMA_RESOURCE_URI,
        )

    def read_export_source_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-export-source-output-v1.schema.json",
            self._EXPORT_OUTPUT_SCHEMA_RESOURCE_URI,
        )

    def read_preview_bundle_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-preview-bundle-output-v1.schema.json",
            self._PREVIEW_OUTPUT_SCHEMA_RESOURCE_URI,
        )

    def read_plan_bundle_input_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema("document-plan-bundle-input-v1.schema.json", self._PLAN_INPUT_SCHEMA_RESOURCE_URI)

    def read_plan_bundle_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema("document-plan-bundle-output-v1.schema.json", self._PLAN_OUTPUT_SCHEMA_RESOURCE_URI)

    def read_apply_plan_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema("hocus-apply-plan-v1.schema.json", self._APPLY_PLAN_SCHEMA_RESOURCE_URI)

    def read_apply_plan_input_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema("document-apply-plan-input-v1.schema.json", self._APPLY_INPUT_SCHEMA_RESOURCE_URI)

    def read_document_preview(self, preview_id: str, context: RequestContext) -> dict[str, Any] | None:
        del context
        payload = self._documents.preview_artifact(preview_id)
        if payload is None:
            return None
        return self._resource_response(f"houdini://documents/previews/{preview_id}", payload)
