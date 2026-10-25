"""``edit`` 2.1 (review 26 P2): the material, unload and export flags and MaterialX
signature menus (D60)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


# -- flags and signature menus (P2 friction 7 and 8) ---------------------------------------


def test_material_flag_and_rollback(client):
    result = client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "create",
                    "id": "m",
                    "parent": "/mat",
                    "type": "subnet",
                    "flags": {"material": True},
                },
                {"op": "create", "id": "n", "parent": "/mat", "type": "subnet"},
                {"op": "node", "path": "$n", "flags": {"material": True}},
            ]
        },
    )
    assert hou.node(result["ids"]["m"]).isMaterialFlagSet()
    n = hou.node(result["ids"]["n"])
    assert n.isMaterialFlagSet()
    client.error(
        "edit",
        {
            "ops": [
                {"op": "node", "path": n.path(), "flags": {"material": False}},
                {"op": "set", "path": f"{n.path()}/nope", "value": 1},
            ]
        },
    )
    assert n.isMaterialFlagSet()  # compensated
    geo = hou.node("/obj").createNode("geo", "g")
    box = geo.createNode("box")
    error = client.error(
        "edit", {"ops": [{"op": "node", "path": box.path(), "flags": {"material": True}}]}
    )
    assert error["code"] == "invalid_argument" and "unload" in error["hint"]
    client.ok("edit", {"ops": [{"op": "node", "path": box.path(), "flags": {"unload": True}}]})
    assert box.isUnloadFlagSet()


def test_mtlx_signature_menu_lists_the_definitions_signatures(client):
    node = hou.node("/mat").createNode("mtlxgeompropvalue", "g")
    client.ok(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "vector3"}]}
    )
    assert node.parm("signature").eval() == "vector3"
    client.ok(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "Color 4"}]}
    )
    assert node.parm("signature").eval() == "color4"  # a label resolves to its token
    error = client.error(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "vec3"}]}
    )
    assert error["code"] == "invalid_value"
    assert {"vector3", "boolean", "default"} <= set(error["candidates"])
