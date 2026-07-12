from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from hocuspocus.live.operations import LiveOperations


class _Operations(OperationBaseMixin, HocusScriptOperationsMixin):
    pass


class HocusScriptOperationsTests(unittest.TestCase):
    def test_compile_tool_is_preview_only(self) -> None:
        response = _Operations().document_compile_source(
            {
                "source_name": "demo.hocus",
                "source": 'hocus 0.1; graph demo { target "/obj/geo1"; }',
            },
            RequestContext(),
        )
        self.assertFalse(response["isError"])
        payload = response["structuredContent"]
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["readyForApply"])
        self.assertEqual(payload["sourceName"], "demo.hocus")

    def test_compile_tool_validates_argument_types(self) -> None:
        with self.assertRaises(JsonRpcError) as captured:
            _Operations().document_compile_source({"source": 12}, RequestContext())
        self.assertEqual(captured.exception.code, -32602)

    def test_compile_tool_rejects_response_amplifying_source_name(self) -> None:
        with self.assertRaises(JsonRpcError):
            _Operations().document_compile_source(
                {"source": 'hocus 0.1; graph demo { target "/obj/geo1"; }', "source_name": "x" * 1025},
                RequestContext(),
            )

    def test_format_tool_is_content_only_and_fail_closed(self) -> None:
        operations = _Operations()
        valid = operations.document_format_source(
            {"source": 'hocus 0.1; graph demo { target "/obj/geo1"; }'},
            RequestContext(),
        )["structuredContent"]
        self.assertTrue(valid["valid"])
        self.assertTrue(valid["changed"])
        self.assertIn("graph demo {\n", valid["formattedSource"])
        invalid = operations.document_format_source(
            {"source": "hocus 0.1; graph demo {"}, RequestContext()
        )["structuredContent"]
        self.assertFalse(invalid["valid"])
        self.assertIsNone(invalid["formattedSource"])

    def test_editor_tools_reject_multibyte_sources_over_the_utf8_byte_limit(self) -> None:
        source = "é" * 600_000
        operations = _Operations()
        with self.assertRaises(JsonRpcError) as formatted:
            operations.document_format_source({"source": source}, RequestContext())
        self.assertEqual(formatted.exception.code, -32602)
        self.assertIn("UTF-8 bytes", formatted.exception.message)
        with self.assertRaises(JsonRpcError) as completed:
            operations.document_complete_source(
                {"source": source, "offset": len(source)}, RequestContext()
            )
        self.assertEqual(completed.exception.code, -32602)
        self.assertIn("UTF-8 bytes", completed.exception.message)

    def test_editor_tools_translate_invalid_unicode_to_invalid_params(self) -> None:
        operations = _Operations()
        with self.assertRaises(JsonRpcError) as formatted:
            operations.document_format_source({"source": "\ud800"}, RequestContext())
        self.assertEqual(formatted.exception.code, -32602)
        with self.assertRaises(JsonRpcError) as completed:
            operations.document_complete_source(
                {"source": "\ud800", "offset": 1}, RequestContext()
            )
        self.assertEqual(completed.exception.code, -32602)

    def test_production_registry_and_capabilities_include_hocusscript_previews(self) -> None:
        self.assertIn(HocusScriptOperationsMixin, LiveOperations.__mro__)
        operations = LiveOperations.__new__(LiveOperations)
        tools = ToolRegistry()
        resources = ResourceRegistry()
        operations.register(tools, resources)
        tool = tools.get("document.compile_source")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.required_capabilities, ("observe",))
        self.assertTrue(tool.listed)
        preview_tool = tools.get("document.preview_bundle")
        self.assertIsNotNone(preview_tool)
        self.assertEqual(preview_tool.required_capabilities, ("observe",))
        self.assertTrue(preview_tool.annotations["readOnlyHint"])
        for tool_name in (
            "document.format_source",
            "document.complete_source",
            "document.export_source",
        ):
            editor_tool = tools.get(tool_name)
            self.assertIsNotNone(editor_tool)
            self.assertEqual(editor_tool.required_capabilities, ("observe",))
            self.assertTrue(editor_tool.annotations["readOnlyHint"])
            self.assertNotIn("project_directory", editor_tool.input_schema.get("properties", {}))
        schema_resource = resources.get("houdini://documents/schema/graph-spec/v0.2")
        self.assertIsNotNone(schema_resource)
        response = schema_resource.reader(RequestContext())
        schema = json.loads(response["contents"][0]["text"])
        self.assertEqual(schema["$id"], "hocuspocus://schemas/graph-spec/v0.2")
        legacy_resource = resources.get("houdini://documents/schema/graph-spec/v0.1")
        self.assertIsNotNone(legacy_resource)
        legacy_schema = json.loads(legacy_resource.reader(RequestContext())["contents"][0]["text"])
        self.assertEqual(legacy_schema["$id"], "hocuspocus://schemas/graph-spec/v0.1")
        for uri, schema_id in (
            (
                "houdini://documents/schema/format-source-output/v1",
                "hocuspocus://schemas/document-format-source-output/v1",
            ),
            (
                "houdini://documents/schema/complete-source-output/v1",
                "hocuspocus://schemas/document-complete-source-output/v1",
            ),
            (
                "houdini://documents/schema/export-source-output/v1",
                "hocuspocus://schemas/document-export-source-output/v1",
            ),
            (
                "houdini://documents/schema/preview-bundle-input/v1",
                "hocuspocus://schemas/document-preview-bundle-input/v1",
            ),
            (
                "houdini://documents/schema/preview-bundle-output/v1",
                "hocuspocus://schemas/document-preview-bundle-output/v1",
            ),
        ):
            resource = resources.get(uri)
            self.assertIsNotNone(resource)
            payload = json.loads(resource.reader(RequestContext())["contents"][0]["text"])
            self.assertEqual(payload["$id"], schema_id)


if __name__ == "__main__":
    unittest.main()
