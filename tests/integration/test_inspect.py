"""``inspect`` (spec-2.0 §2.3) against real Houdini: each ``what`` returns its 1.4 read's
result plus only ``etag`` (``node`` and ``outline`` with their 2.0 trims, M4) with
``detail: full``, and by default the compact projection (spec-2.0 M4 "read shapes":
defaults and empties left out); the etag is stable while nothing changes and moves when
the addressed node does."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import pytest

hou = pytest.importorskip("hou")

from hocuspocus.host import resources as host_resources  # noqa: E402

ETAG = re.compile(r"^\d+:\d+:[0-9a-f]{16}$")
ADDED = ("etag",)
PROJECTED = frozenset({"node", "parms", "outline", "geo", "problems", "type"})
"""The reads with a compact shape; ``detail: full`` gives their 1.4 shape."""


def _bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _trimmed(what: str, old: dict[str, Any], wiring: bool = False) -> dict[str, Any]:
    """The 1.4 result with inspect's 2.0 trims (spec-2.0 §7 M4): node rows without
    session_id; outline without format, and rows without a name that is the path's last
    segment, errors at 0, or (unless wiring) inputs."""
    out = json.loads(json.dumps(old))
    if what == "node":
        for row in out["nodes"]:
            row.pop("session_id", None)
    elif what == "outline":
        out.pop("format", None)

        def trim(rows: list[dict[str, Any]]) -> None:
            for row in rows:
                if row.get("name") == row["path"].rsplit("/", 1)[-1]:
                    del row["name"]
                if row.get("errors") == 0:
                    del row["errors"]
                if not wiring:
                    row.pop("inputs", None)
                trim(row.get("children", []))

        trim(out["nodes"])
    return out


def _same(client, what: str, target: Any, options: dict[str, Any], tool: str, args) -> dict:
    """``inspect`` with ``detail: full`` returns ``tool``'s result (trimmed for 2.0) plus
    only the etag, first; returns the default (compact) result of the same call."""
    old = client.ok(tool, args)
    call = {"what": what, **({} if target is None else {"target": target}), **options}
    full = {"detail": "full"} if what in PROJECTED and what != "type" else {}
    new = client.ok("inspect", {**call, **full})
    assert list(new)[: len(ADDED)] == list(ADDED), list(new)
    assert "what" not in new and "target" not in new, list(new)
    assert ETAG.match(new["etag"]), new["etag"]
    rest = {k: v for k, v in new.items() if k not in ADDED}
    expected = _trimmed(what, old, options.get("wiring", False))
    assert _bytes(rest) == _bytes(expected), (what, set(rest) ^ set(expected))
    if not full:
        return new
    compact = client.ok("inspect", call)
    assert ETAG.match(compact["etag"]) and "what" not in compact, list(compact)
    assert len(_bytes(compact)) <= len(_bytes(new)), (what, compact, new)
    return compact


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
    assert new["nodes"][0]["path"] == box.path() and "session_id" not in new["nodes"][0]
    args = {"include": ["flags", "children"], "include_defaults": True}
    paths = ["/obj/geo1", box.path()]
    many = _same(v2_client, "node", None, {"paths": paths, **args}, "node_info",
                 {"paths": paths, **args})  # fmt: skip
    assert [row["path"] for row in many["nodes"]] == paths
    for row in many["nodes"]:  # no 1.4 extras the call did not ask for
        assert not {"session_id", "hda", "position", "comment"} & set(row), row


def test_parms_is_parm_get(v2_client):
    _net, box, _ = _geo()
    options = {"frame": 1, "include": ["template"]}
    new = _same(v2_client, "parms", f"{box.path()}/size", options, "parm_get",
                {"paths": [f"{box.path()}/size"], **options})  # fmt: skip
    size = new["parms"][f"{box.path()}/size"]
    assert size["value"] == [2.0, 1.0, 1.0] and "template" in size, size
    paths = [f"{box.path()}/sizex", f"{box.path()}/t"]
    plain = _same(v2_client, "parms", None, {"paths": paths}, "parm_get", {"paths": paths})
    assert plain["parms"] == {paths[0]: 2.0, paths[1]: [0.0, 0.0, 0.0]}, plain


def test_parms_on_a_node_reads_its_non_default_tuples(v2_client):
    _net, box, xform = _geo()
    non_default = _same(v2_client, "parms", box.path(), {}, "parm_get",
                        {"paths": [f"{box.path()}/size"]})  # fmt: skip
    assert non_default["parms"] == {"size": [2.0, 1.0, 1.0]}, non_default
    globbed = v2_client.ok("inspect", {"what": "parms", "target": xform.path(), "parms": "t|r"})
    assert list(globbed["parms"]) == ["t", "r"]
    full = v2_client.ok(
        "inspect", {"what": "parms", "target": xform.path(), "parms": "t|r", "detail": "full"}
    )
    assert [row["tuple"] for row in full["parms"]] == ["t", "r"]
    everything = v2_client.ok(
        "inspect", {"what": "parms", "target": box.path(), "include_defaults": True}
    )
    assert {"size", "t", "type"} <= set(everything["parms"]) and len(everything["parms"]) > 5
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
    assert new["root"] == geo.path()


def test_outline_is_network_describe_outline(v2_client):
    _geo()
    new = _same(v2_client, "outline", None, {}, "network_describe",
                {"root": "/", "format": "outline"})  # fmt: skip
    assert new["root"] == "/" and "format" not in new
    deep = _same(v2_client, "outline", "/obj", {"depth": 3}, "network_describe",
                 {"root": "/obj", "format": "outline", "depth": 3})  # fmt: skip
    (geo,) = deep["nodes"]
    assert geo == {
        "path": "/obj/geo1",
        "type": "geo",
        "display": "/obj/geo1/xform1",
        "flags": ["display"],
        "children": [
            {"path": "/obj/geo1/box1", "type": "box"},
            {"path": "/obj/geo1/xform1", "type": "xform", "flags": ["display", "render"]},
        ],
    }, geo  # fmt: skip  (children_count: children lists both)
    shallow = v2_client.ok("inspect", {"what": "outline", "target": "/obj", "depth": 1})
    assert shallow["nodes"][0]["children_count"] == 2, shallow  # not listed: counted
    wired = _same(v2_client, "outline", "/obj", {"depth": 3, "wiring": True},
                  "network_describe", {"root": "/obj", "format": "outline", "depth": 3})  # fmt: skip
    assert wired["nodes"][0]["children"][1]["inputs"] == ["/obj/geo1/box1"]
    error = v2_client.error("inspect", {"what": "outline", "wiring": "yes"})
    assert error["code"] == "invalid_argument"


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
    assert new["root"] == "/"
    assert any(row.get("path") == bad.path() for row in new["problems"]), new
    _same(v2_client, "problems", geo.path(), {"include_warnings": False}, "problems",
          {"root": geo.path(), "include_warnings": False})  # fmt: skip


def test_type_is_node_type_info(v2_client):
    options = {"parms": "*seed*", "detail": "full"}  # node_type_info's full shape: unchanged
    _same(v2_client, "type", "Sop/scatter", options, "node_type_info",
          {"type": "Sop/scatter", **options})  # fmt: skip
    old = v2_client.ok("node_type_info", {"type": "Sop/scatter", "parms": "*seed*"})
    new = v2_client.ok("inspect", {"what": "type", "target": "Sop/scatter", "parms": "*seed*"})
    assert new["name"] == "scatter" or new["name"].startswith("scatter::"), new["name"]
    assert new["parms"] == old["parms"] and new["parm_columns"] == old["parm_columns"]
    assert old["is_current_version"] is True and "is_current_version" not in new
    assert old["detail"] == "compact" and not {"detail", "hint", "inputs_count"} & set(new)
    assert old["outputs"] == [{"index": 0, "name": "output1", "label": "Output 1"}]
    assert "outputs" not in new  # only the default output
    rest = {k: v for k, v in old.items()
            if k not in ("detail", "hint", "inputs_count", "is_current_version", "outputs")}  # fmt: skip
    assert {k: v for k, v in new.items() if k != "etag"} == rest
    copy = v2_client.ok("inspect", {"what": "type", "target": "Sop/copytopoints",
                                    "include_parms": False})  # fmt: skip
    assert copy["inputs"] == ["Geometry to Copy", "Target Points to Copy to"], copy
    folders = v2_client.ok("inspect", {"what": "type", "target": "box", "category": "Sop",
                                       "detail": "folders"})  # fmt: skip
    assert folders["folders"] and "hint" in folders  # folders keeps its own hint
    again = v2_client.ok("inspect", {"what": "type", "target": "Sop/scatter", "parms": "*seed*"})
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
    assert isinstance(new["jobs"], list)
    started = host.jobs.start("cook", lambda job: {"done": True}, label="probe")
    deadline = time.monotonic() + 5
    while host.jobs.status(started.id)["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    status = _same(v2_client, "jobs", None, {"job_id": started.id}, "job",
                   {"action": "status", "job_id": started.id})  # fmt: skip
    assert status["job_id"] == started.id
    missing = v2_client.error("inspect", {"what": "jobs", "job_id": "1-nope"})
    assert missing["code"] == "job_not_found"


# -- compact shapes (spec-2.0 M4 "read shapes") -------------------------------------------


def test_node_compact_shape(v2_client):
    """node rows: Category/type, the flags that are on, positional inputs, parms as
    {name: value} with a row only where more than the value matters, no empty errors or
    cooked cook_state; detail: full is the 1.4 row."""
    geo, box, xform = _geo()
    xform.parm("ry").setExpression("$F*3")
    merge = geo.createNode("copytopoints", "copy1")
    merge.setInput(1, xform)
    xform.cook(force=True)
    call = {"what": "node", "paths": [xform.path(), merge.path()],
            "include": ["flags", "inputs", "parms", "errors"]}  # fmt: skip
    rows = v2_client.ok("inspect", call)["nodes"]
    assert rows[0] == {
        "path": xform.path(), "type": "Sop/xform", "flags": ["display", "render"],
        "inputs": [box.path()],
        "parms": {"t": [0.0, 1.5, 0.0], "r": {"value": [0.0, 3.0, 0.0],
                                            "expressions": {"ry": "$F*3"}}},
    }, rows[0]  # fmt: skip
    assert rows[1]["inputs"] == [None, xform.path()], rows[1]
    assert rows[1]["cook_state"] == "not_cooked" and "flags" not in rows[1], rows[1]
    full = v2_client.ok("inspect", {**call, "detail": "full"})["nodes"]
    assert full[0]["type"]["name"] == "xform" and full[0]["errors"] == []
    assert full[1]["inputs"][1]["from"] == {"path": xform.path(), "output": 0}
    assert full[0]["parms"][1]["name"] == "r" and full[0]["parms"][1]["is_default"] is False
    outputs = v2_client.ok("inspect", {"what": "node", "target": box.path(),
                                       "include": ["outputs"]})  # fmt: skip
    assert outputs["nodes"][0]["outputs"] == [[xform.path()]], outputs


def test_parms_compact_rows_keep_what_matters(v2_client):
    _net, box, xform = _geo()
    xform.parm("ry").setExpression("$F*3")
    xform.parm("rx").setExpression("hou.frame()", hou.exprLanguage.Python)
    xform.parm("tz").lock(True)
    got = v2_client.ok("inspect", {"what": "parms", "paths": [
        f"{xform.path()}/ry", f"{xform.path()}/rx", f"{xform.path()}/tz",
        f"{xform.path()}/xOrd"]})["parms"]  # fmt: skip
    assert got[f"{xform.path()}/ry"] == {"value": 3.0, "expression": "$F*3"}, got
    assert got[f"{xform.path()}/rx"]["language"] == "python", got
    assert got[f"{xform.path()}/tz"] == {"value": 0.0, "locked": True}, got
    order = got[f"{xform.path()}/xOrd"]
    assert isinstance(order, dict) and order.get("type") == "menu", order


def test_geo_compact_summary(v2_client):
    _net, box, xform = _geo()
    group = xform.parent().createNode("groupcreate", "tops")
    group.setFirstInput(xform)
    group.parm("groupname").set("tops")
    color = xform.parent().createNode("color", "paint")
    color.setFirstInput(group)
    color.setDisplayFlag(True)
    old = v2_client.ok("geo_info", {"path": color.path()})
    new = v2_client.ok("inspect", {"what": "geo", "target": color.path()})
    assert new["attributes"]["point"]["P"] == "float3:position", new["attributes"]
    cd = {**new["attributes"].get("point", {}), **new["attributes"].get("prim", {})}["Cd"]
    assert cd == "float3:color", new["attributes"]
    assert "vertex" not in new["attributes"] and "detail" not in new["attributes"]
    assert new["groups"] == {"prim": {"tops": old["groups"]["prim"][0]["count"]}}, new
    assert set(new["bbox"]) == {"min", "max", "size"}
    for key in ("path", "point_count", "prim_count", "vertex_count", "prim_types"):
        assert new[key] == old[key], key
    full = v2_client.ok("inspect", {"what": "geo", "target": color.path(), "detail": "full"})
    assert full["groups"] == old["groups"] and full["bbox"] == old["bbox"]
    plain = v2_client.ok("inspect", {"what": "geo", "target": box.path()})
    assert "groups" not in plain


def test_problems_compact(v2_client):
    _geo()
    old = v2_client.ok("problems", {"root": "/obj"})
    new = v2_client.ok("inspect", {"what": "problems", "target": "/obj"})
    assert new["problems"] == [] and old["counts"] == {} and "counts" not in new
    assert "nodes_with_problems" not in new and new["total"] == 0
    error = v2_client.error("inspect", {"what": "problems", "detail": "folders"})
    assert error["code"] == "invalid_argument" and "detail" in error["message"]
    error = v2_client.error("inspect", {"what": "network", "target": "/obj", "detail": "full"})
    assert error["code"] == "invalid_argument" and "does not take detail" in error["message"]


# -- etag ---------------------------------------------------------------------------------


def test_etag_is_the_body_digest_and_moves_with_the_answer(v2_client, host):
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
    box.bypass(True)  # a flag the body reports
    after_flag = v2_client.ok("inspect", call)["etag"]
    assert after_flag != after_parm
    box.bypass(False)
    # Another option set, another etag.
    other = v2_client.ok("inspect", {**call, "include": ["flags"]})["etag"]
    assert other != v2_client.ok("inspect", call)["etag"]
    # The etag is the digest of the body: what the answer does not show leaves it alone.
    net = {"what": "outline", "target": "/obj/geo1"}
    before_net = v2_client.ok("inspect", net)
    sibling = v2_client.ok("inspect", {"what": "node", "target": box.path()})["etag"]
    xform.parm("tx").set(4.0)  # the outline shows no parms
    assert v2_client.ok("inspect", net)["etag"] == before_net["etag"]
    assert v2_client.ok("inspect", {"what": "node", "target": box.path()})["etag"] == sibling
    hou.node("/obj/geo1").createNode("null", "extra")  # the outline shows children
    assert v2_client.ok("inspect", net)["etag"] != before_net["etag"]
    body = {k: v for k, v in before_net.items() if k != "etag"}
    assert before_net["etag"] == host_resources.content_etag(host.scene.generation, body)
    # Geometry: a recook that changes nothing keeps the etag; an upstream edit moves it.
    geo_call = {"what": "geo", "target": xform.path()}
    geo_first = v2_client.ok("inspect", geo_call)["etag"]
    xform.cook(force=True)
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


def test_a_full_host_refuses_the_1x_reads_with_their_inspect_what(client):
    """spec-2.0 §8: node_info on a 2.0 profile names inspect what: node."""
    assert "nodes" in client.ok("inspect", {"what": "outline"})
    error = client.error("node_info", {"paths": ["/obj"]})
    assert error["code"] == "invalid_argument" and "1.4 tool" in error["message"]
    assert error["hint"].startswith("In 2.0 use inspect what: node.")
