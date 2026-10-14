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
    assert events[2]["detail"] == {"parm": "t", "components": ["tx"]}
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
    assert events[0]["detail"] == {"parm": "r", "components": ["rx", "ry", "rz"]}
    assert events[1]["detail"] == {"parm": "t", "components": ["tx"]}
    time.sleep(ev.COALESCE_S + 0.05)
    geo.parm("ry").set(5)
    later = _read(client, events[-1]["seq"])
    assert len(later) == 1 and later[0]["detail"] == {"parm": "r", "components": ["ry"]}
    geo.parm("scale").set(2)  # a one-component tuple names no components
    assert _read(client, later[-1]["seq"])[0]["detail"] == {"parm": "scale"}


def test_keyed_components_are_named(client):
    """Review 16 papercut 9: a key on ry plus a set of rx read as {parm: r, count: 3}."""
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "keyed"}]})
    since = _since()
    client.ok(
        "parm_set", {"items": [{"path": "/obj/keyed/ry", "keyframe": {"frame": 10, "value": 45}}]}
    )
    events = _read(client, since)
    assert _kinds(events) == [("ParmTupleChanged", "/obj/keyed")]
    assert events[0]["detail"] == {"parm": "r", "components": ["ry"], "keyed": ["ry"]}
    assert events[0]["origin"] == "agent"
    since = events[-1]["seq"]
    time.sleep(ev.COALESCE_S + 0.05)  # a burst within COALESCE_S joins the last event
    # One call keying ry again and setting rx coalesces into the union of components.
    client.ok(
        "parm_set",
        {
            "items": [
                {"path": "/obj/keyed/ry", "keyframe": {"frame": 20, "value": 90}},
                {"path": "/obj/keyed/rx", "value": 15},
            ]
        },
    )
    events = _read(client, since)
    assert _kinds(events) == [("ParmTupleChanged", "/obj/keyed")]
    assert events[0]["detail"] == {"parm": "r", "components": ["rx", "ry"], "keyed": ["ry"]}


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
    assert events[1]["detail"] == {"parm": "size", "components": ["sizex"]}


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


# -- 1.2: origin, batches, flags, spare parms, HDAs, PDG, wider watch ---------------------


def test_origin_tells_agent_from_user(client):
    since = _since()
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "agent_geo"}]})
    hou.node("/obj").createNode("geo", "user_geo")
    events = _read(client, since)
    origins = {e["path"]: e["origin"] for e in events if e["kind"] == "ChildCreated"}
    assert origins == {"/obj/agent_geo": "agent", "/obj/user_geo": "other"}


def test_children_created_in_the_same_batch_as_their_parent(client):
    """Review 14 papercut 6: CONTROLS and the topnet children had no ChildCreated."""
    since = _since()
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "bldg"},
                {"parent": "/obj/bldg", "type": "null", "name": "CONTROLS"},
                {"parent": "/obj", "type": "topnet", "name": "topnet1"},
                {"parent": "/obj/topnet1", "type": "genericgenerator", "name": "gen"},
            ]
        },
    )
    created = [e["path"] for e in _read(client, since) if e["kind"] == "ChildCreated"]
    assert created == ["/obj/bldg", "/obj/bldg/CONTROLS", "/obj/topnet1", "/obj/topnet1/gen"]


def test_flag_changed_names_the_flag(client):
    geo = hou.node("/obj").createNode("geo", "g")
    _settle(client)
    since = _since()
    geo.setDisplayFlag(False)
    [event] = _read(client, since)
    assert event["kind"] == "FlagChanged" and event["detail"] == {"flags": {"display": False}}


def test_spare_parm_edit_is_one_spare_parms_changed(client):
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "null", "name": "CONTROLS"}]})
    since = _since()
    client.ok(
        "node_edit",
        {
            "items": [
                {
                    "path": "/obj/CONTROLS",
                    "spare_parms": {"add": [{"name": "seed", "type": "int", "default": 1}]},
                }
            ]
        },
    )
    assert _kinds(_read(client, since)) == [("SpareParmsChanged", "/obj/CONTROLS")]
    since = _since()
    hou.parm("/obj/CONTROLS/seed").set(7)  # a value edit after it is still reported
    assert _kinds(_read(client, since)) == [("ParmTupleChanged", "/obj/CONTROLS")]


def test_rolled_back_batch_records_nothing(client):
    """Review 13 papercut 9: a failed node_create left created/deleted pairs behind."""
    since = _since()
    error = client.error(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "a"},
                {"parent": "/obj/a", "type": "box", "name": "b"},
                {"parent": "/obj/a", "type": "no_such_type"},
            ]
        },
    )
    assert error["detail"]["rolled_back"] is True
    assert _read(client, since) == []


def test_tool_internal_set_and_restore_are_not_recorded(client, work_dir):
    """render sets and restores the ROP's output parm with undo disabled."""
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "g"},
                {"parent": "/obj/g", "type": "box", "name": "box"},
                {
                    "parent": "/out",
                    "type": "geometry",
                    "name": "geo_out",
                    "parms": {"soppath": "/obj/g/box"},
                },
            ]
        },
    )
    since = _since()
    out = (work_dir / "box.bgeo.sc").as_posix()
    client.ok("render", {"rop_path": "/out/geo_out", "output": out, "thumbnail": False})
    events = [e for e in _read(client, since) if e["path"] == "/out/geo_out"]
    assert events == [], events


def test_hda_rebuild_is_one_event(client, work_dir):
    """Review 15 papercut 2: ~150 ChildDeleted/BeingDeleted of asset internals."""
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "g"},
                {"parent": "/obj/g", "type": "subnet", "name": "rock"},
                {"parent": "/obj/g/rock", "type": "box", "name": "b"},
                {"parent": "/obj/g/rock", "type": "sphere", "name": "s"},
            ]
        },
    )
    since = _since()
    library = (work_dir / "rock.hda").as_posix()
    client.ok(
        "hda",
        {
            "action": "create",
            "path": "/obj/g/rock",
            "name": "hptest::evrock::1.0",
            "library_path": library,
        },
    )
    [created] = _read(client, since)
    assert created["kind"] == "hda_contents_rebuilt" and created["path"] == "/obj/g/rock"
    assert created["origin"] == "agent" and created["detail"]["events"] > 0
    client.ok("node_create", {"items": [{"parent": "/obj/g/rock", "type": "null", "name": "x"}]})
    since = _since()
    client.ok("hda", {"action": "match", "path": "/obj/g/rock"})  # drops the edit
    assert _kinds(_read(client, since)) == [("hda_contents_rebuilt", "/obj/g/rock")]
    since = _since()
    hou.node("/obj/g/rock").setName("rock2")  # the asset node is watched again
    assert _kinds(_read(client, since)) == [("NameChanged", "/obj/g/rock2")]


def test_topnet_save_noise_is_dropped(client, work_dir):
    hou.node("/obj").createNode("topnet", "topnet1").createNode("genericgenerator")
    _settle(client)
    since = _since()
    hou.hipFile.save((work_dir / "tops.hip").as_posix())
    assert [e["kind"] for e in _read(client, since)] == ["AfterSave"]


def test_nodes_read_by_the_agent_are_watched(client, work_dir):
    """Review 15 papercut 3: renaming /obj/sky (loaded with the hip) went unreported."""
    hou.node("/obj").createNode("geo", "sky")
    hou.node("/obj").createNode("cam", "cam1")
    path = (work_dir / "loaded.hip").as_posix()
    hou.hipFile.save(path)
    hou.hipFile.load(path, suppress_save_prompt=True, ignore_load_warnings=True)
    _settle(client)
    since = _since()
    hou.node("/obj/sky").setName("sky_unseen")  # nothing has read it yet
    assert _read(client, since) == []
    hou.node("/obj/sky_unseen").setName("sky")
    client.ok("network_describe", {"root": "/obj", "format": "outline"})
    client.ok("node_info", {"paths": ["/obj/cam1"]})
    since = _since()
    hou.node("/obj/sky").setName("sky_env")
    hou.parm("/obj/cam1/focal").set(85)
    events = _read(client, since)
    assert _kinds(events) == [("NameChanged", "/obj/sky_env"), ("ParmTupleChanged", "/obj/cam1")]
    assert events[0]["detail"] == {"old_name": "sky"} and events[0]["origin"] == "other"


def test_pdg_cooks_are_recorded(client):
    net = hou.node("/obj").createNode("topnet", "topnet1")
    gen = net.createNode("genericgenerator", "gen")
    gen.parm("itemcount").set(2)
    script = net.createNode("pythonscript", "script")
    script.setInput(0, gen)
    script.parm("pdg_cooktype").set(1)
    script.parm("script").set("if work_item.index == 1:\n    raise RuntimeError('boom')\n")
    _settle(client)
    since = _since()
    client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    pdg = [e for e in _read(client, since) if e["kind"] == "pdg"]
    assert [e["detail"]["event"] for e in pdg] == ["cook_start", "work_item_failed", "cook_done"]
    assert all(e["origin"] == "agent" for e in pdg)
    assert pdg[0]["path"] == script.path()
    assert pdg[1]["path"] == script.path() and "boom" in pdg[1]["detail"]["error"]
    assert pdg[2]["detail"]["ok"] is False and pdg[2]["detail"]["states"]["cooked_fail"] == 1


def test_invalid_arguments(client):
    assert client.error("events", {"since": -1})["code"] == "invalid_argument"
    assert client.error("events", {"limit": 0})["code"] == "invalid_argument"
    assert client.error("events", {"since": "3"})["code"] == "invalid_argument"


@pytest.mark.parametrize("tool", ["hip_open", "hip_merge"])
def test_failed_hip_load_does_not_silence_events(client, work_dir, tool, monkeypatch):
    client.ok("events", {})
    source = work_dir / "source.hip"
    client.ok("hip_save", {"path": str(source).replace("\\", "/")})

    def dies_after_before_event(*args, **kwargs):
        # What a load that fails after BeforeLoad/BeforeMerge looks like to the hooks:
        # the Before event fired, the After event never comes.
        ev._HOOKS.hip_busy = True
        raise hou.OperationFailed("simulated load failure")

    attr = "load" if tool == "hip_open" else "merge"
    try:
        monkeypatch.setattr(hou.hipFile, attr, dies_after_before_event)
    except (AttributeError, TypeError):
        pytest.skip("hou.hipFile cannot be patched in this build")
    args = {"path": str(source).replace("\\", "/")}
    if tool == "hip_open":
        args["on_unsaved"] = "discard"
    assert client.error(tool, args)["code"] == "invalid_value"
    monkeypatch.undo()
    assert ev._HOOKS.hip_busy is False
    since = _since()
    hou.node("/obj").createNode("geo", "after_failure")
    _settle(client)
    assert ("ChildCreated", "/obj/after_failure") in _kinds(_read(client, since))


def test_top_level_children_are_reported_once(client):
    """Review 16 N2: after network_describe of /stage (which watches /stage itself), every
    top-level ChildCreated was reported twice: by the manager callback and by /stage's
    own node callback. Nested children were reported once."""
    client.ok("network_describe", {"root": "/stage", "format": "outline"})
    client.ok("network_describe", {"root": "/obj", "format": "outline"})
    since = _since()
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/stage", "type": "materiallibrary", "name": "matlib"},
                {"parent": "/stage/matlib", "type": "mtlxstandard_surface", "name": "concrete"},
                {"parent": "/stage", "type": "camera", "name": "cam_main"},
            ]
        },
    )
    hou.node("/stage").createNode("null", "user_null")
    hou.node("/obj").createNode("geo", "user_geo")
    _settle(client)
    hou.node("/stage/user_null").destroy()
    created = [e["path"] for e in _read(client, since) if e["kind"].startswith("Child")]
    assert created == [
        "/stage/matlib",
        "/stage/matlib/concrete",
        "/stage/cam_main",
        "/stage/user_null",
        "/obj/user_geo",
        "/stage/user_null",
    ]


def test_repeated_child_events_are_dropped():
    log = ev.EventLog()
    log.record("ChildCreated", "/stage/a")
    log.record("ChildCreated", "/stage/a")  # the same creation seen by a second callback
    log.record("ChildCreated", "/stage/b")
    log.record("ChildDeleted", "/stage/a")
    log.record("ChildCreated", "/stage/a")  # created again after the delete: a new event
    kinds = [(e["kind"], e["path"]) for e in log.read(0, 10)["events"]]
    assert kinds == [
        ("ChildCreated", "/stage/a"),
        ("ChildCreated", "/stage/b"),
        ("ChildDeleted", "/stage/a"),
        ("ChildCreated", "/stage/a"),
    ]


def test_events_pages_end_at_the_response_budget_and_skip_nothing(client):
    """Review 22 finding 1: a page cut by the byte budget resumes at the next event."""
    since = _since()
    for i in range(60):
        ev.LOG.record("ParmTupleChanged", f"/obj/budget_geo{i}", {"parm": "t"}, origin="agent")
    seen: list[int] = []
    cursor = since
    for _ in range(60):
        body = {
            "tool": "events",
            "args": {"since": cursor, "limit": 1000},
            "max_response_bytes": 2048,
        }
        page = client.request("POST", "/hp/v1/call", body).body["result"]
        seen += [e["seq"] for e in page["events"]]
        if not page.get("more"):
            break
        assert page["next_since"] == page["events"][-1]["seq"]
        cursor = page["next_since"]
    assert seen == list(range(since + 1, since + 61))
