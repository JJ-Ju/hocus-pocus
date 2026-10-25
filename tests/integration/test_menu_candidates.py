"""A value that is not in a menu gets candidates ranked by similarity (BIBLE D72; review
26 P3 #11: ``parmtype: volume`` on a ``subnetconnector`` listed 20 of 44 items and not
``atmosphere``, the Volume shader)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def _connector():
    mat = hou.node("/obj").createNode("matnet", "mat")
    sub = mat.createNode("subnet", "shader")
    return sub.createNode("subnetconnector", "out_volume")


def test_a_label_word_finds_the_token_in_a_long_menu(client):
    node = _connector()
    error = client.error(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/parmtype", "value": "volume"}]}
    )
    assert error["code"] == "invalid_value", error
    assert error["candidates"][0] == "atmosphere"
    assert len(error["candidates"]) == len(node.parm("parmtype").menuItems())
    assert error["hint"].startswith("Use a token or label: atmosphere (Volume (shader))")


def test_a_misspelt_token_ranks_first_in_parm_set(client):
    box = hou.node("/obj").createNode("geo").createNode("box")
    error = client.error(
        "parm_set", {"items": [{"path": f"{box.path()}/type", "value": "polymsh"}]}
    )
    assert error["code"] == "invalid_value"
    assert error["candidates"][0] == "polymesh", error
