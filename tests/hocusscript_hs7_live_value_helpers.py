from __future__ import annotations

from types import SimpleNamespace

from hocuspocus.live.catalog_provider import (
    _multiparm_value_contract,
    _parameter,
    _parameters,
)
from hocuspocus.live.ops.document_typed_apply import (
    _apply_multiparm,
    _apply_ramp,
)
from hocuspocus.live.ops.document_typed_receipts import (
    DocumentTypedReceiptOperationsMixin,
)
from hocuspocus.live.ops.document_snapshot import (
    DocumentSnapshotOperationsMixin,
)


def assert_h21_ramp_adapter_surface(testcase) -> None:
    class RampParmTemplate:
        name = lambda self: "color"
        label = lambda self: "Color"
        type = lambda self: SimpleNamespace(name=lambda: "Float")
        parmType = lambda self: SimpleNamespace(name=lambda: "Color")
        numComponents = lambda self: 1
        defaultValue = lambda self: None
        parmTemplates = lambda self: (SimpleNamespace(),)

    parameter = _parameter(RampParmTemplate(), "test", 2)
    testcase.assertEqual(parameter.value_type, "ramp")
    testcase.assertEqual(parameter.value_contract["rampKind"], "color")
    group = SimpleNamespace(entries=lambda: (RampParmTemplate(),))
    node_type = SimpleNamespace(
        name=lambda: "test", parmTemplateGroup=lambda: group,
    )
    leaves = _parameters(node_type, 2)
    testcase.assertEqual([item.value_type for item in leaves], ["ramp"])
    captured = {}

    class Ramp:
        def __init__(self, bases, positions, values):
            captured.update(bases=bases, positions=positions, values=values)

    parm = SimpleNamespace(set=lambda value: captured.update(ramp=value))
    hou = SimpleNamespace(
        rampBasis=SimpleNamespace(Linear="linear"), Ramp=Ramp,
    )
    operations = SimpleNamespace(
        _require_hou=lambda: hou,
        _require_parm_by_path=lambda _path: parm,
    )
    _apply_ramp(operations, "/obj/g/color", {
        "rampKind": "color", "basis": ["linear", "linear"],
        "points": [
            {"position": 0.0, "value": [0.1, 0.2, 0.3]},
            {"position": 1.0, "value": [0.4, 0.5, 0.6]},
        ],
    })
    testcase.assertEqual(
        captured["values"], ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
    )
    live_ramp = {
        "keys": [0.10000000149011612],
        "values": [SimpleNamespace(
            rgb=lambda: (
                0.10000000149011612,
                0.800000011920929,
                0.20000000298023224,
            )
        )],
    }

    class ReceiptProbe(DocumentTypedReceiptOperationsMixin):
        @staticmethod
        def _safe_value(callback, default):
            try:
                return callback()
            except Exception:
                return default

        @staticmethod
        def _require_hou():
            ramp = SimpleNamespace(
                keys=lambda: live_ramp["keys"],
                values=lambda: live_ramp["values"],
                basis=lambda: ["linear"],
            )
            return SimpleNamespace(
                parm=lambda _path: SimpleNamespace(evalAsRamp=lambda: ramp),
                rampBasis=SimpleNamespace(Linear="linear"),
            )

    testcase.assertTrue(ReceiptProbe()._document_live_ramp_matches(
        {
            "basis": ["linear"],
            "points": [{
                "position": 0.1,
                "value": [0.1, 0.8, 0.2],
            }],
        },
        {"path": "/obj/g/color"},
    ))
    testcase.assertIsNone(ReceiptProbe._document_ramp_float32(1e300))
    _assert_multiparm_instance_surface(testcase)


def _assert_multiparm_instance_surface(testcase) -> None:
    class Field:
        name = lambda self: "count#"
        type = lambda self: SimpleNamespace(name=lambda: "Int")
        numComponents = lambda self: 1

    class Multiparm:
        parmTemplates = lambda self: (Field(),)
        tags = lambda self: {"multistartoffset": "7"}

    contract = _multiparm_value_contract(Multiparm())
    testcase.assertEqual(contract["instanceStart"], 7)

    class ConflictingMultiparm(Multiparm):
        multiParmStartOffset = lambda self: 8

    testcase.assertIsNone(_multiparm_value_contract(ConflictingMultiparm()))
    calls = []

    class RootParm:
        eval = lambda self: 1
        multiParmStartOffset = lambda self: 7
        multiParmInstancesCount = lambda self: testcase.fail(
            "flattened child count must not be used"
        )
        removeMultiParmInstance = lambda self, index: calls.append(
            ("remove", index)
        )
        insertMultiParmInstance = lambda self, index: calls.append(
            ("insert", index)
        )

    operations = SimpleNamespace(
        _require_parm_by_path=lambda _path: RootParm(),
        _parm_set_impl=lambda arguments: calls.append(
            ("set", arguments["parm_path"], arguments["value"])
        ),
    )
    binding = {
        "instanceStart": 7,
        "fieldContract": [{
            "name": "count", "tokenTemplate": "count#",
            "valueType": "int", "tupleSize": 1, "elementType": None,
        }],
        "instances": [
            {"instanceId": "a", "fields": [{
                "name": "count", "value": {"kind": "literal", "value": 2},
            }]},
            {"instanceId": "b", "fields": [{
                "name": "count", "value": {"kind": "literal", "value": 3},
            }]},
        ],
    }
    _apply_multiparm(operations, "/obj/g/items", binding, {})
    testcase.assertEqual(calls[:3], [
        ("remove", 0), ("insert", 0), ("insert", 1),
    ])
    testcase.assertEqual(
        [item[1] for item in calls if item[0] == "set"],
        ["/obj/g/count7", "/obj/g/count8"],
    )

    child_values = {
        "/obj/g/count7": SimpleNamespace(eval=lambda: 2),
        "/obj/g/count8": SimpleNamespace(eval=lambda: 3),
    }

    class ReceiptProbe(DocumentTypedReceiptOperationsMixin):
        @staticmethod
        def _safe_value(callback, default):
            try:
                return callback()
            except Exception:
                return default

        @staticmethod
        def _require_hou():
            root = SimpleNamespace(
                eval=lambda: 2, multiParmStartOffset=lambda: 7,
                multiParmInstancesCount=lambda: testcase.fail(
                    "flattened child count must not be used"
                ),
            )
            return SimpleNamespace(parm=lambda path: (
                root if path == "/obj/g/items" else child_values.get(path)
            ))

    receipt_probe = ReceiptProbe()
    receipt = {**binding, "valueMode": "multiparm"}
    testcase.assertTrue(receipt_probe._document_live_multiparm_matches(
        receipt, {"path": "/obj/g/items"}, {}
    ))
    testcase.assertFalse(receipt_probe._document_live_multiparm_matches(
        {**receipt, "instanceStart": 8},
        {"path": "/obj/g/items"},
        {},
    ))
    _assert_composite_children_are_opaque(testcase)


def _assert_composite_children_are_opaque(testcase) -> None:
    artist_value = {"value": "preserve"}
    parent = SimpleNamespace(path=lambda: "/obj/g/items")
    child = SimpleNamespace(
        parentMultiParm=lambda: parent,
        eval=lambda: artist_value["value"],
    )
    ordinary = SimpleNamespace(parentMultiParm=lambda: None)

    class SnapshotProbe(DocumentSnapshotOperationsMixin):
        @staticmethod
        def _safe_value(callback, default):
            try:
                return callback()
            except Exception:
                return default

        @staticmethod
        def _require_hou():
            return SimpleNamespace(parm=lambda path: (
                child if path.endswith("/item1") else ordinary
            ))

    probe = SnapshotProbe()
    testcase.assertTrue(
        probe._document_live_parm_is_composite_child(
            {"path": "/obj/g/item1"}
        )
    )
    testcase.assertFalse(
        probe._document_live_parm_is_composite_child(
            {"path": "/obj/g/ordinary"}
        )
    )
    testcase.assertEqual(child.eval(), "preserve")
