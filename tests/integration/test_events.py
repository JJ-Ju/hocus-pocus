"""events: the host's ring buffer of hip and node events (bible §4.7)."""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")

from hocuspocus.host.tools import events as ev  # noqa: E402


def _since() -> int:
    return ev.LOG.last_seq


def _read(client, since: int, **kw) -> list[dict]:
    result = client.ok("events", {"since": since, **kw})
    assert result["dropped"] == 0
    return result["events"]


def _settle(client) -> None:
    """Run queued main-thread work (the deferred watch of user-created nodes)."""
    while client.host.executor.pump_once(0.0):
        pass


def _kinds(events: list[dict]) -> list[tuple[str, str]]:
    return [(e["kind"], e["path"]) for e in events]


def test_node_lifecycle_events(client):
    since = _since()
    geo = hou.node("/obj").createNode("geo", "user_geo")  # watched once created
    _settle(client)
    geo.setName("renamed")
    geo.parm("tx").set(1.5)
    geo.setDisplayFlag(False)
    null = hou.node("/obj").createNode("null", "src")
    geo.setInput(0, null)
    geo.destroy()

    result = client.ok("events", {"since": since})
    events = result["events"]
    assert result["next_since"] == events[-1]["seq"]
    assert [e["seq"] for e in events] == list(range(since + 1, since + 1 + len(events)))
    assert _kinds(events) == [
        ("ChildCreated", "/obj/user_geo"),
        ("NameChanged", "/obj/renamed"),
        ("ParmTupleChanged", "/obj/renamed"),
        ("FlagChanged", "/obj/renamed"),
        ("ChildCreated", "/obj/src"),
        ("InputRewired", "/obj/renamed"),
        ("BeingDeleted", "/obj/renamed"),
        ("ChildDeleted", "/obj/renamed"),
    ]
    assert events[0]["detail"] == {"type": "geo"}
    assert events[1]["detail"] == {"old_name": "user_geo"}
    assert events[2]["detail"] == {"parm": "t"}
    assert events[5]["detail"] == {"input": 0}
    assert all(e["time"].endswith("Z") for e in events)


def test_parm_bursts_coalesce(client):
    geo = hou.node("/obj").createNode("geo", "g")
    _settle(client)
    since = _since()
    geo.parmTuple("r").set((10, 20, 30))  # one event per component
    geo.parm("tx").set(1)
    events = _read(client, since)
    assert _kinds(events) == [("ParmTupleChanged", "/obj/g"), ("ParmTupleChanged", "/obj/g")]
    assert events[0]["detail"] == {"parm": "r", "count": 3}
    assert events[1]["detail"] == {"parm": "t"}
    time.sleep(ev.COALESCE_S + 0.05)
    geo.parm("ry").set(5)
    later = _read(client, events[-1]["seq"])
    assert len(later) == 1 and later[0]["detail"] == {"parm": "r"}


def test_watch_node_inside_network(client):
    geo = hou.node("/obj").createNode("geo", "g")
    _settle(client)
    since = _since()
    box = geo.createNode("box")  # the geo is watched, so its children appear
    assert ev.watch_node(box) is True
    assert ev.watch_node(box) is True  # idempotent
    box.parm("sizex").set(3)
    events = _read(client, since)
    assert _kinds(events) == [
        ("ChildCreated", "/obj/g/box1"),
        ("ParmTupleChanged", "/obj/g/box1"),
    ]
    assert events[1]["detail"] == {"parm": "size"}


def test_unwatched_nodes_are_quiet(client):
    geo = hou.node("/obj").createNode("geo", "g")
    _settle(client)
    box = geo.createNode("box")
    since = _since()
    box.parm("sizex").set(2)  # box1 was never watched (only /obj's children are by default)
    assert _read(client, since) == []


def test_creation_scripts_are_not_recorded(client):
    since = _since()
    hou.node("/obj").createNode("hlight::2.0", "key")  # sets ~100 parms, builds ~40 nodes
    hou.node("/stage").createNode("sphere", "s")
    hou.node("/tasks").createNode("topnet", "t")
    _settle(client)
    assert _kinds(_read(client, since)) == [
        ("ChildCreated", "/obj/key"),
        ("ChildCreated", "/stage/s"),
        ("ChildCreated", "/tasks/t"),
    ]
    since = _since()
    hou.parm("/obj/key/light_intensity").set(2)
    hou.node("/stage/s").setName("ball")
    assert _kinds(_read(client, since)) == [
        ("ParmTupleChanged", "/obj/key"),
        ("NameChanged", "/stage/ball"),
    ]


def test_agent_created_nodes(client):
    since = _since()
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "terrain"}]})
    events = _read(client, since)
    assert ("ChildCreated", "/obj/terrain") in _kinds(events)
    since = _since()
    client.ok("node_edit", {"items": [{"path": "/obj/terrain", "name": "land"}]})
    assert ("NameChanged", "/obj/land") in _kinds(_read(client, since))


def test_agent_touched_nodes_are_watched(client):
    """node_create/network_build/node_copy watch what they make (bible §4.7), so later
    changes to nested nodes, which no context-manager callback sees, are reported."""
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "g"}]})
    client.ok("node_create", {"items": [{"parent": "/obj/g", "type": "box", "name": "b"}]})
    since = _since()
    client.ok("parm_set", {"items": [{"path": "/obj/g/b/size", "value": [2, 2, 2]}]})
    events = _read(client, since)
    assert _kinds(events) == [("ParmTupleChanged", "/obj/g/b")]
    assert events[0]["detail"]["parm"] == "size"

    client.ok(
        "network_build",
        {"parent": "/obj/g", "data": {"s": {"type": "sphere"}}, "layout": False},
    )
    client.ok("node_copy", {"paths": ["/obj/g/b"], "to_parent": "/obj/g", "names": ["b2"]})
    since = _since()
    hou.parm("/obj/g/s/radx").set(3)
    hou.parm("/obj/g/b2/sizex").set(4)
    assert _kinds(_read(client, since)) == [
        ("ParmTupleChanged", "/obj/g/s"),
        ("ParmTupleChanged", "/obj/g/b2"),
    ]


def test_hip_save_clear_load(client, work_dir):
    hou.node("/obj").createNode("geo", "g")
    path = (work_dir / "events.hip").as_posix()
    since = _since()
    hou.hipFile.save(path)
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hipFile.load(path, suppress_save_prompt=True, ignore_load_warnings=True)
    events = _read(client, since)
    kinds = [e["kind"] for e in events]
    # No node noise while the scene is cleared or loaded; the load's inner clear is hidden.
    assert kinds == ["AfterSave", "BeforeClear", "AfterClear", "BeforeLoad", "AfterLoad"]
    assert events[0]["path"] == path
    assert events[-1]["path"] == path
    # Node events resume after the load.
    since = events[-1]["seq"]
    hou.node("/obj").createNode("null", "after")
    assert _kinds(_read(client, since)) == [("ChildCreated", "/obj/after")]


def test_hip_merge_is_one_event(client, work_dir):
    hou.node("/obj").createNode("geo", "g")
    path = (work_dir / "merge.hip").as_posix()
    hou.hipFile.save(path)
    since = _since()
    hou.hipFile.merge(path)
    events = _read(client, since)
    assert [e["kind"] for e in events] == ["AfterMerge"]


def test_hip_tools_are_recorded(client, work_dir):
    path = (work_dir / "tool.hip").as_posix()
    since = _since()
    client.ok("hip_save", {"path": path})
    kinds = [e["kind"] for e in _read(client, since)]
    assert kinds == ["AfterSave"]


def test_paging_and_limit(client):
    since = _since()
    for i in range(5):
        hou.node("/obj").createNode("null", f"n{i}")
    first = client.ok("events", {"since": since, "limit": 2})
    assert len(first["events"]) == 2 and first["more"] is True
    second = client.ok("events", {"since": first["next_since"], "limit": 10})
    assert len(second["events"]) == 3 and "more" not in second
    assert [e["path"] for e in first["events"] + second["events"]] == [
        f"/obj/n{i}" for i in range(5)
    ]
    empty = client.ok("events", {"since": second["next_since"]})
    assert empty["events"] == [] and empty["next_since"] == second["next_since"]


def test_since_beyond_last_means_restart(client):
    hou.node("/obj").createNode("null", "x")
    result = client.ok("events", {"since": ev.LOG.last_seq + 1000, "limit": 1})
    assert result["reset"] is True
    assert result["events"][0]["seq"] >= 1


def test_ring_buffer_drops_oldest():
    log = ev.EventLog(size=3)
    for i in range(5):
        log.record("ChildCreated", f"/obj/n{i}")
    result = log.read(0, 10)
    assert [e["seq"] for e in result["events"]] == [3, 4, 5]
    assert result["dropped"] == 2
    assert log.read(3, 10)["dropped"] == 0


def test_invalid_arguments(client):
    assert client.error("events", {"since": -1})["code"] == "invalid_argument"
    assert client.error("events", {"limit": 0})["code"] == "invalid_argument"
    assert client.error("events", {"since": "3"})["code"] == "invalid_argument"
