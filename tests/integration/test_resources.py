"""``GET /hp/v2/resource`` (spec-2.0 §2.7, §4) against real Houdini: every template's body
is byte for byte the ``inspect`` (or ``search``, ``houdini_status``) result for the same
options, its etag is that result's etag (the digest of the body), ``If-None-Match`` answers
``not_modified``, also across a change that leaves the body alone (a ``look``), and the
etag moves when the node does."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import pytest

hou = pytest.importorskip("hou")

from hocuspocus.host import resources as host_resources  # noqa: E402

ETAG = re.compile(r"^\d+:\d+:[0-9a-f]{16}$")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _stable(payload):
    """Drop fields that legitimately differ between two consecutive reads (memory figures)."""
    if isinstance(payload, dict):
        return {k: _stable(v) for k, v in payload.items() if k not in {"memory", "elapsed_ms"}}
    if isinstance(payload, list):
        return [_stable(v) for v in payload]
    return payload


def _read(client, uri: str, if_none_match: str | None = None) -> dict[str, Any]:
    headers = {"If-None-Match": if_none_match} if if_none_match else None
    response = client.request("GET", f"/hp/v2/resource?uri={quote(uri, safe='')}", headers=headers)
    assert response.status == 200, response.body
    envelope = response.body
    assert envelope["ok"] is True, envelope
    assert envelope["_meta"]["etag"] == envelope["result"]["etag"]
    assert isinstance(envelope["_meta"]["events_seq"], int)
    return envelope["result"]


def _scene() -> None:
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box", "box1")
    box.parm("sizex").set(2.0)
    xform = geo.createNode("xform", "xform1")
    xform.setFirstInput(box)
    xform.setDisplayFlag(True)
    net = hou.node("/img").createNode("copnet", "net")
    net.createNode("constant", "color").setDisplayFlag(True)
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    out = stage.createNode("null", "OUT")
    out.setInput(0, sphere)
    out.setDisplayFlag(True)


CASES = [
    "houdini://node/obj/geo1/box1",
    "houdini://node/%2Fobj%2Fgeo1%2Fbox1?include=flags,inputs&include_defaults=false",
    "houdini://node/obj/geo1/box1?parms=size*",
    "houdini://outline",
    "houdini://outline?root=/obj&depth=3",
    "houdini://network/obj/geo1?depth=1",
    "houdini://network/obj?format=outline",
    "houdini://geo/obj/geo1/xform1",
    "houdini://geo/obj/geo1/xform1?class=point&attribs=P&count=4&stats=true",
    "houdini://image/img/net/color",
    "houdini://stage/stage/OUT?prim=/&summary=true",
    "houdini://type/Sop/scatter?detail=folders",
    "houdini://types?q=scatter&category=Sop&limit=3",
    "houdini://problems?root=/obj",
    "houdini://events?since=0&limit=5",
    "houdini://jobs",
    "houdini://status",
]


@pytest.mark.parametrize("uri", CASES)
def test_resource_is_its_tool_call(v2_client, uri):
    _scene()
    route = host_resources.parse(uri)
    v2_client.ok(route.tool, dict(route.args))  # first reads cook; both reads below see it
    resource = _read(v2_client, uri)
    tool = v2_client.ok(route.tool, dict(route.args))
    assert _bytes(_stable(resource["body"])) == _bytes(_stable(tool)), uri
    if route.tool == "inspect":
        assert resource["etag"] == tool["etag"]
    assert ETAG.match(resource["etag"]), resource["etag"]
    same = _read(v2_client, uri, f'"{resource["etag"]}"')
    assert same == {"uri": uri, "etag": resource["etag"], "not_modified": True}


def test_resources_share_the_compact_projections(v2_client):
    """spec-2.0 M4 "read shapes": a resource is its inspect (or search) call, so its body
    is the compact projection too; inspect with detail: full gives the 1.4 shape."""
    _scene()
    node = _read(v2_client, "houdini://node/obj/geo1/xform1")["body"]
    (row,) = node["nodes"]
    assert row["type"] == "Sop/xform" and row["inputs"] == ["/obj/geo1/box1"], row
    assert row["flags"] == ["display", "render"] or row["flags"] == ["display"], row
    assert "session_id" not in row and "errors" not in row, row
    parms = _read(v2_client, "houdini://node/obj/geo1/box1?parms=size*")["body"]
    assert parms["parms"] == {"size": [2.0, 1.0, 1.0]}, parms
    geo = _read(v2_client, "houdini://geo/obj/geo1/xform1")["body"]
    assert geo["attributes"] == {"point": {"P": "float3:position"}}, geo["attributes"]
    assert "groups" not in geo and "center" not in geo["bbox"], geo
    outline = _read(v2_client, "houdini://outline?root=/obj&depth=3")["body"]
    assert "children_count" not in outline["nodes"][0], outline
    types = _read(v2_client, "houdini://types?q=scatter&category=Sop&limit=3")["body"]
    assert "kind" not in types and types["common"]["category"] == "Sop", types
    assert all("category" not in r and "version" not in r for r in types["results"]), types


def test_node_etag_moves_with_a_parm(v2_client):
    _scene()
    uri = "houdini://node/obj/geo1/box1"
    first = _read(v2_client, uri)
    v2_client.ok("parm_set", {"items": [{"path": "/obj/geo1/box1/sizey", "value": 3.0}]})
    moved = _read(v2_client, uri, first["etag"])
    assert "not_modified" not in moved and moved["etag"] != first["etag"]
    assert _read(v2_client, uri, moved["etag"])["not_modified"] is True


SOAK_READS = (
    "houdini://geo/obj/geo1/xform1",
    "houdini://node/obj/geo1/xform1",
    "houdini://outline?root=/obj",
    "houdini://problems?root=/obj",
    "houdini://status",
)


@pytest.mark.slow
def test_identical_reads_around_a_look_are_not_modified(v2_client):
    """The soak's pattern (review 22): read, do something unrelated that recooks (a look
    renders the displayed geometry), read again with the etag. The bodies did not change,
    so the second reads are not_modified: the etag digests the body, not cook counts."""
    _scene()
    first = {uri: _read(v2_client, uri) for uri in SOAK_READS}
    looked = v2_client.ok("look", {"target": "/obj/geo1", "resolution": [64, 48]})
    assert looked["backend_used"]
    for uri, read in first.items():
        again = _read(v2_client, uri, read["etag"])
        assert again == {"uri": uri, "etag": read["etag"], "not_modified": True}, (uri, again)
    v2_client.ok("parm_set", {"items": [{"path": "/obj/geo1/xform1/ty", "value": 2.0}]})
    moved = _read(v2_client, "houdini://geo/obj/geo1/xform1", first[SOAK_READS[0]]["etag"])
    assert "not_modified" not in moved and moved["body"]["bbox"]["max"][1] > 0.5


def test_resource_errors(v2_client):
    unknown = v2_client.request("GET", "/hp/v2/resource?uri=" + quote("houdini://nope", safe=""))
    assert unknown.body["ok"] is False and unknown.body["error"]["code"] == "invalid_argument"
    bridge_only = v2_client.request(
        "GET", "/hp/v2/resource?uri=" + quote("houdini://instances", safe="")
    )
    assert "bridge" in bridge_only.body["error"]["message"]
    missing = v2_client.request(
        "GET", "/hp/v2/resource?uri=" + quote("houdini://node/obj/nope", safe="")
    )
    assert missing.body["ok"] is False
    unauthorized = v2_client.request(
        "GET", "/hp/v2/resource?uri=" + quote("houdini://jobs", safe=""), token=False
    )
    assert unauthorized.status == 401
