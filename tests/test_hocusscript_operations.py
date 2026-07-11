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
        schema_resource = resources.get("houdini://documents/schema/graph-spec/v0.1")
        self.assertIsNotNone(schema_resource)
        response = schema_resource.reader(RequestContext())
        schema = json.loads(response["contents"][0]["text"])
        self.assertEqual(schema["$id"], "hocuspocus://schemas/graph-spec/v0.1")
        for uri, schema_id in (
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
