from __future__ import annotations

import unittest
from types import SimpleNamespace

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.mcp_types import ToolRegistry
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.node_types import NodeTypeOperationsMixin
from tests.runtime_stdio_broker import assert_stdio_broker_contract


class _NodeTypeTools(OperationBaseMixin, NodeTypeOperationsMixin):
    pass


class _ParmType:
    @staticmethod
    def name():
        return "String"


class _BaseParm:
    def __init__(self, name: str):
        self._name = name

    def name(self):
        return self._name

    def label(self):
        return self._name

    @staticmethod
    def type():
        return _ParmType()

    @staticmethod
    def numComponents():
        return 1

    @staticmethod
    def menuItems():
        return ()

    @staticmethod
    def menuLabels():
        return ()


class _ValueParm(_BaseParm):
    @staticmethod
    def defaultValue():
        return ("kept",)


class _ThrowingParm(_BaseParm):
    @staticmethod
    def defaultValue():
        raise RuntimeError("optional metadata unavailable")


class _FolderParm:
    pass


def _assert_optional_parm_metadata(test: unittest.TestCase) -> None:
    parm_entries = (_BaseParm("label"), _ThrowingParm("button"), _ValueParm("value"))
    node_type = SimpleNamespace(
        parmTemplateGroup=lambda: SimpleNamespace(entries=lambda: parm_entries),
    )
    operations = _NodeTypeTools()
    operations._require_hou = lambda: SimpleNamespace(FolderParmTemplate=_FolderParm)
    records = operations._parm_template_records(node_type)
    test.assertNotIn("default", records[0])
    test.assertNotIn("default", records[1])
    test.assertEqual(records[2]["default"], ["kept"])


def _assert_compatibility_resolution(test: unittest.TestCase) -> None:
    operations = _NodeTypeTools()
    operations._node_types_list_impl = lambda _arguments: {
        "count": 1,
        "totalCount": 1,
        "offset": 0,
        "limit": 40,
        "hasMore": False,
        "items": [{"typeName": "attribwrangle", "tags": ["attribute", "vex"]}],
    }
    exact = operations._node_types_list_compatible_impl({"task": "vex"})
    test.assertEqual((exact["resolvedTask"], exact["resolutionKind"]), ("vex", "exact_task"))
    intent = operations._node_types_list_compatible_impl(
        {"intent": "I need to write a VEX wrangle"}
    )
    test.assertEqual((intent["resolvedTask"], intent["resolutionKind"]), ("vex", "intent_alias"))
    test.assertEqual(intent["matchedTerms"], ["vex", "wrangle"])
    with test.assertRaises(JsonRpcError) as ambiguous:
        operations._node_types_list_compatible_impl(
            {"intent": "Copy and instance geometry"}
        )
    test.assertEqual(
        [item["task"] for item in ambiguous.exception.data["candidates"]],
        ["copying", "instancing"],
    )
    with test.assertRaises(JsonRpcError):
        operations._node_types_list_compatible_impl(
            {"task": "vex", "intent": "write a wrangle"}
        )


def _assert_stable_catalog_selectors(test: unittest.TestCase) -> None:
    operations = _NodeTypeTools()
    record = {
        "typeName": "polybevel::3.0",
        "label": "PolyBevel",
        "aliases": ["poly bevel"],
        "tags": ["cleanup"],
    }
    test.assertTrue(operations._node_type_query_matches("poly bevel", record))
    test.assertTrue(operations._node_type_query_matches("polybevel", record))
    parms = [
        {"name": "pieceattrib"},
        {"name": "pack"},
        {"name": "group"},
    ]
    selected = operations._select_key_parms("copytopoints", parms)
    test.assertEqual([item["name"] for item in selected[:2]], ["pack", "pieceattrib"])


def assert_node_type_discovery_contract(
    test: unittest.TestCase,
    tools: ToolRegistry,
) -> None:
    compatible = tools.get("node_types.list_compatible")
    test.assertIsNotNone(compatible)
    schema = compatible.input_schema
    task_enum = schema["properties"]["task"]["enum"]
    test.assertEqual(set(task_enum), set(NodeTypeOperationsMixin._COMPATIBILITY_TASKS))
    test.assertEqual(len(task_enum), len(set(task_enum)))
    test.assertEqual(schema["oneOf"], [{"required": ["task"]}, {"required": ["intent"]}])
    _assert_optional_parm_metadata(test)
    _assert_compatibility_resolution(test)
    _assert_stable_catalog_selectors(test)
    assert_stdio_broker_contract(test)
