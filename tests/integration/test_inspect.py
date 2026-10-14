"""``inspect`` (spec-2.0 §2.3) against real Houdini: each ``what`` returns its 1.4 read's
result byte for byte, plus only ``what``, ``target`` and ``etag``; the etag is stable while
nothing changes and moves when the addressed node does."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import pytest

hou = pytest.importorskip("hou")

ETAG = re.compile(r"^\d+:\d+:[0-9a-f]{16}$")
ADDED = ("what", "target", "etag")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _same(client, what: str, target: Any, options: dict[str, Any], tool: str, args) -> dict:
    """``inspect`` returns ``tool``'s result plus only what/target/etag, in that order."""
    old = client.ok(tool, args)
    call = {"what": what, **({} if target is None else {"target": target}), **options}
    new = client.ok("inspect", call)
    assert list(new)[:3] == list(ADDED), list(new)
    assert new["what"] == what
    assert ETAG.match(new["etag"]), new["etag"]
    rest = {k: v for k, v in new.items() if k not in ADDED}
    assert _bytes(rest) == _bytes(old), (what, set(rest) ^ set(old))
    return new


def _geo():
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box", "box1")
    box.parm("sizex").set(2.0)
    xform = geo.createNode("xform", "xform1")
    xform.setFirstInput(box)
    xform.parm("ty").set(1.5)
    xform.setDisplayFlag(True)
    xform.setRenderFlag(True)
    return geo, box, xform


# -- one test per what ------------------------------------------------------------------------


def test_node_is_node_info(v2_client):
    _net, box, _ = _geo()
    new = _same(v2_client, "node", box.path(), {}, "node_info", {"paths": [box.path()]})
    assert new["target"] == box.path() and new["nodes"][0]["path"] == box.path()
    args = {"include": ["flags", "children"], "include_defaults": True}
    paths = ["/obj/geo1", box.path()]
    many = _same(v2_client, "node", None, {"paths": paths, **args}, "node_info",
                 {"paths": paths, **args})  # fmt: skip
    assert many["target"] == paths


def test_parms_is_parm_get(v2_client):
    _net, box, _ = _geo()
    options = {"frame": 1, "include": ["template"]}
    new = _same(v2_client, "parms", f"{box.path()}/size", options, "parm_get",
                {"paths": [f"{box.path()}/size"], **options})  # fmt: skip
    assert new["parms"][0]["value"] == [2.0, 1.0, 1.0]
    paths = [f"{box.path()}/sizex", f"{box.path()}/t"]
    _same(v2_client, "parms", None, {"paths": paths}, "parm_get", {"paths": paths})


def test_parms_on_a_node_reads_its_non_default_tuples(v2_client):
    _net, box, xform = _geo()
    non_default = _same(v2_client, "parms", box.path(), {}, "parm_get",
                        {"paths": [f"{box.path()}/size"]})  # fmt: skip
    assert [row["name"] for row in non_default["parms"]] == ["size"]
    globbed = v2_client.ok("inspect", {"what": "parms", "target": xform.path(), "parms": "t|r"})
    assert [row["tuple"] for row in globbed["parms"]] == ["t", "r"]
    everything = v2_client.ok(
        "inspect", {"what": "parms", "target": box.path(), "include_defaults": True}
    )
    names = [row.get("tuple", row["name"]) for row in everything["parms"]]
    assert {"size", "t", "type"} <= set(names) and len(names) > 5
    nothing = hou.node("/obj").createNode("null", "plain")
    empty = v2_client.ok("inspect", {"what": "parms", "target": nothing.path()})
    assert empty["parms"] == []
    error = v2_client.error(
        "inspect", {"what": "parms", "target": f"{box.path()}/size", "parms": "s*"}
    )
    assert error["code"] == "invalid_argument" and "target is a node" in error["message"]


def test_network_is_network_describe_data(v2_client):
    geo, _box, _ = _geo()
    options = {"depth": 1, "include_positions": True}
    new = _same(v2_client, "network", geo.path(), options, "network_describe",
                {"root": geo.path(), "format": "data", **options})  # fmt: skip
    assert new["target"] == geo.path()


def test_outline_is_network_describe_outline(v2_client):
    _geo()
    new = _same(v2_client, "outline", None, {}, "network_describe",
                {"root": "/", "format": "outline"})  # fmt: skip
    assert new["target"] == "/"
    _same(v2_client, "outline", "/obj", {"depth": 3}, "network_describe",
          {"root": "/obj", "format": "outline", "depth": 3})  # fmt: skip


def test_geo_is_geo_info_and_rows_is_geo_read(v2_client):
    geo, _box, xform = _geo()
    summary = _same(v2_client, "geo", geo.path(), {"attributes": "names"}, "geo_info",
                    {"path": geo.path(), "attributes": "names"})  # fmt: skip
    assert summary["path"] == xform.path() and summary["point_count"] == 8
    options = {"attribs": ["P"], "count": 3, "stats": True}
    rows = _same(v2_client, "geo", xform.path(), {"rows": True, **options}, "geo_read",
                 {"path": xform.path(), **options})  # fmt: skip
    assert rows["columns"][0].startswith("P") or rows["columns"]
    assert len(rows["rows"]) == 3
    error = v2_client.error("inspect", {"what": "geo", "target": xform.path(), "count": 3})
    assert error["code"] == "invalid_argument" and "rows: true" in error["hint"]


def test_image_is_geo_info_on_a_cop(v2_client):
    net = hou.node("/img").createNode("copnet", "citymap")
    color = net.createNode("constant", "color")
    color.setDisplayFlag(True)
    new = _same(v2_client, "image", color.path(), {}, "geo_info", {"path": color.path()})
    assert new["kind"] == "image"
    _same(v2_client, "image", net.path(), {}, "geo_info", {"path": net.path()})
    _net, box, _ = _geo()
    error = v2_client.error("inspect", {"what": "image", "target": box.path()})
    assert error["code"] == "invalid_argument" and "what: geo" in error["hint"]


def test_stage_is_usd_stage(v2_client):
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    out = stage.createNode("null", "OUT")
    out.setInput(0, sphere)
    out.setDisplayFlag(True)
    options = {"prim": "/", "depth": 2, "include": ["xform"]}
    new = _same(v2_client, "stage", out.path(), options, "usd_stage",
                {"lop_path": out.path(), **options})  # fmt: skip
    assert [p["path"] for p in new["prims"]] == ["/sphere1"]


def test_problems_is_problems(v2_client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    bad = geo.createNode("attribwrangle", "bad")
    bad.parm("snippet").set("this is not vex;")
    bad.setDisplayFlag(True)
    options = {"cook_uncooked": True}
    v2_client.ok("problems", options)  # the first scan cooks; both reads below see the result
    new = _same(v2_client, "problems", None, options, "problems", options)
    assert new["target"] == "/"
    assert any(row.get("path") == bad.path() for row in new["problems"]), new
    _same(v2_client, "problems", geo.path(), {"include_warnings": False}, "problems",
          {"root": geo.path(), "include_warnings": False})  # fmt: skip


def test_type_is_node_type_info(v2_client):
    options = {"parms": "*seed*"}
    new = _same(v2_client, "type", "Sop/scatter", options, "node_type_info",
                {"type": "Sop/scatter", **options})  # fmt: skip
    assert new["target"] == "Sop/scatter"
    _same(v2_client, "type", "box", {"category": "Sop", "detail": "folders"}, "node_type_info",
          {"type": "box", "category": "Sop", "detail": "folders"})  # fmt: skip
    again = v2_client.ok("inspect", {"what": "type", "target": "Sop/scatter", **options})
    assert again["etag"] == new["etag"]


def test_events_is_events(v2_client):
    from hocuspocus.host.tools.events import LOG

    # Recorded through the log itself: another test stops a second in-process host, which
    # removes the process's Houdini callbacks (test_host_lifecycle), so hou-side edits may
    # record nothing in a full run.
    _net, box, _ = _geo()
    LOG.record("NameChanged", box.path(), {"old_name": "box0"})
    LOG.record("NameChanged", box.path(), {"old_name": "box00"})
    first = _same(v2_client, "events", None, {"since": 0, "limit": 2}, "events",
                  {"since": 0, "limit": 2})  # fmt: skip
    assert len(first["events"]) == 2
    new = _same(v2_client, "events", None, {"since": 0, "limit": 1000}, "events",
                {"since": 0, "limit": 1000})  # fmt: skip
    assert new["target"] is None
    cursor = new["next_since"]
    while True:  # pages end at the response budget: read to the end of the ring buffer
        later = v2_client.ok("inspect", {"what": "events", "since": cursor})
        if not later["events"]:
            break
        cursor = later["next_since"]
    same = v2_client.ok("inspect", {"what": "events", "since": cursor})
    assert same["etag"] == later["etag"]
    LOG.record("NameChanged", box.path(), {"old_name": "box000"})
    moved = v2_client.ok("inspect", {"what": "events", "since": cursor})
    assert moved["etag"] != later["etag"] and moved["events"]


def test_jobs_is_job_list_and_status(v2_client, host):
    new = _same(v2_client, "jobs", None, {}, "job", {"action": "list"})
    assert new["target"] is None and isinstance(new["jobs"], list)
    started = host.jobs.start("cook", lambda job: {"done": True}, label="probe")
    deadline = time.monotonic() + 5
    while host.jobs.status(started.id)["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    status = _same(v2_client, "jobs", None, {"job_id": started.id}, "job",
                   {"action": "status", "job_id": started.id})  # fmt: skip
    assert status["job_id"] == started.id
    missing = v2_client.error("inspect", {"what": "jobs", "job_id": "1-nope"})
    assert missing["code"] == "job_not_found"


# -- etag ---------------------------------------------------------------------------------


def test_etag_is_stable_and_moves_with_the_node(v2_client, host):
    _net, box, xform = _geo()
    call = {"what": "node", "target": box.path()}
    first = v2_client.ok("inspect", call)["etag"]
    pid, generation, digest = first.split(":")
    assert int(pid) == os.getpid()  # the in-process host
    assert int(generation) == host.scene.generation
    assert v2_client.ok("inspect", call)["etag"] == first  # nothing changed
    v2_client.ok("parm_set", {"items": [{"path": f"{box.path()}/sizey", "value": 3}]})
    after_parm = v2_client.ok("inspect", call)["etag"]
    assert after_parm != first
    box.bypass(True)  # a flag: modificationTime does not move, the flags part does
    after_flag = v2_client.ok("inspect", call)["etag"]
    assert after_flag != after_parm
    box.bypass(False)
    # Another option set, another etag.
    other = v2_client.ok("inspect", {**call, "include": ["flags"]})["etag"]
    assert other != v2_client.ok("inspect", call)["etag"]
    # A change below a network moves the network's etag, not a sibling's node etag.
    net = {"what": "outline", "target": "/obj/geo1"}
    before_net = v2_client.ok("inspect", net)["etag"]
    sibling = v2_client.ok("inspect", {"what": "node", "target": box.path()})["etag"]
    xform.parm("tx").set(4.0)
    assert v2_client.ok("inspect", net)["etag"] != before_net
    assert v2_client.ok("inspect", {"what": "node", "target": box.path()})["etag"] == sibling
    # Geometry: an upstream edit recooks the read node, so its cookCount moves.
    geo_call = {"what": "geo", "target": xform.path()}
    geo_first = v2_client.ok("inspect", geo_call)["etag"]
    assert v2_client.ok("inspect", geo_call)["etag"] == geo_first
    box.parm("sizez").set(5.0)
    assert v2_client.ok("inspect", geo_call)["etag"] != geo_first
    # A hip clear bumps scene_generation.
    hou.hipFile.clear(suppress_save_prompt=True)
    _geo()
    assert v2_client.ok("inspect", call)["etag"].split(":")[1] != generation


# -- errors and the profile ---------------------------------------------------------------


def test_inspect_errors_name_the_options(v2_client):
    _net, box, _ = _geo()
    error = v2_client.error("inspect", {"what": "node", "target": box.path(), "depth": 2})
    assert error["code"] == "invalid_argument" and "does not take depth" in error["message"]
    assert "include" in error["hint"]
    error = v2_client.error("inspect", {"what": "noodle", "target": box.path()})
    assert error["code"] == "invalid_argument" and "node" in error["candidates"]
    error = v2_client.error("inspect", {"what": "events", "target": box.path()})
    assert error["code"] == "invalid_argument" and "no target" in error["message"]
    error = v2_client.error("inspect", {"what": "geo"})
    assert error["code"] == "invalid_argument" and "needs target" in error["message"]
    error = v2_client.error("inspect", {"what": "node", "target": "/obj/nope"})
    assert error["code"] == "node_not_found"


def test_a_full_host_refuses_inspect(client):
    error = client.error("inspect", {"what": "outline"})
    assert error["code"] == "invalid_argument" and "v2-profile" in error["message"]
    assert 'profile = "v2"' in error["hint"]
