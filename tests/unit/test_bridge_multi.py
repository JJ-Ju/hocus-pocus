"""Several Houdinis at once (review 19): a sticky pin, ambiguity refusals, the instance on
every result, jobs routed to their instance, events cursors per instance and named rows.
Uses the real catalogue with a fake HostClient per port."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.server import Bridge

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


GUI = Instance(
    pid=3084,
    port=51000,
    token="t-gui",
    houdini="22.0.466",
    ui=True,
    hip="C:/work/city_work.hip",
    started="2026-10-12T10:00:00Z",
    label="houdinifx",
)
WORKER = Instance(
    pid=61900,
    port=51001,
    token="t-worker",
    houdini="22.0.466",
    ui=False,
    hip="C:/work/city_work.hip",
    started="2026-10-12T11:00:00Z",
    label="hython",
)
WORKER2 = Instance(
    pid=61996,
    port=51002,
    token="t-worker2",
    ui=False,
    started="2026-10-12T12:00:00Z",
    label="hython",
)


class Host:
    """One fake host: answers /health, calls and job snapshots."""

    def __init__(self, inst: Instance) -> None:
        self.inst = inst
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replies: dict[str, Any] = {}
        self.health_extra: dict[str, Any] = {}

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {
            "ok": True,
            "hp": 1,
            "pid": self.inst.pid,
            "houdini": "22.0.466",
            "generation": 1,
            "host_version": "2.0.0",
            **self.health_extra,
        }

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append((tool, dict(args or {})))
        reply = self.replies.get(tool)
        if callable(reply):
            return reply(args)
        if reply is not None:
            return reply
        if tool == "houdini_status":
            return True, {"hip": {"path": self.inst.hip}}, {}
        return True, {"echo": tool, "pid": self.inst.pid}, {"scene_generation": 1}

    def job(self, job_id, timeout_s=10.0):
        return self.call("job", {"action": "status", "job_id": job_id}, timeout_s)

    def call_jobs(self, request_id, timeout_s=5.0):
        return []

    def quit(self, on_unsaved="fail", timeout_s=70.0):
        return True, {"quitting": True, "pid": self.inst.pid, "saved": False}, {}


def make(*instances: Instance, config: BridgeConfig | None = None):
    live = list(instances)
    hosts = {inst.port: Host(inst) for inst in (GUI, WORKER, WORKER2, *instances)}

    def factory(port, token):
        return hosts[port]

    bridge = Bridge(
        config or BridgeConfig(profile="full"),
        client_factory=factory,
        scan=lambda: list(live),
    )
    bridge.exit_grace_s = 0.0
    return bridge, hosts, live


def data(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def host_of(hosts, inst: Instance) -> Host:
    return hosts[inst.port]


# -- 1. a pinned instance is never silently replaced (review 19 papercut 1) -------------------


def test_dead_pin_is_instance_lost_on_every_call_and_never_switches():
    bridge, hosts, live = make(GUI, WORKER)
    assert not bridge.call_tool("houdini_connect", {"pid": WORKER.pid}).is_error
    live.remove(WORKER)  # the worker is killed mid-render
    for tool, args in (
        ("parm_set", {"items": [{"path": "/out/gl_two/res", "value": [1920, 1080]}]}),
        ("inspect", {"what": "node", "target": "/obj"}),
        ("time", {}),
    ):
        result = bridge.call_tool(tool, args)
        assert result.is_error, tool
        error = data(result)
        assert error["code"] == "instance_lost"
        assert error["retryable"] is False
        assert "61900" in error["message"] and "hython" in error["message"]
        assert error["candidates"] == [
            {"pid": 3084, "label": "houdinifx", "ui": True, "hip": "C:/work/city_work.hip"}
        ]
        assert "houdini_connect {pid}" in error["hint"]
        assert "hip: 'C:/work/city_work.hip'" in error["hint"]  # reopen its last save
    assert host_of(hosts, GUI).calls == []  # nothing reached the GUI


def test_status_reports_the_lost_pin_and_connects_nothing():
    bridge, _hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    status = data(bridge.call_tool("houdini_status", {}))
    assert status["connected"] is None
    assert status["lost"] == {"pid": 61900, "label": "hython"}
    assert [row.get("selected", False) for row in status["instances"]] == [False]
    assert any("61900" in w and "houdini_connect" in w for w in status["warnings"])


def test_lost_pin_clears_only_on_an_explicit_connect():
    bridge, hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    live.append(WORKER2)  # a new worker does not take over either
    assert (
        data(bridge.call_tool("inspect", {"what": "node", "target": "/obj"}))["code"]
        == "instance_lost"
    )
    connected = data(bridge.call_tool("houdini_connect", {"pid": GUI.pid}))
    assert connected["connected"]["pid"] == GUI.pid
    result = bridge.call_tool("inspect", {"what": "node", "target": "/obj"})
    assert not result.is_error and data(result)["pid"] == GUI.pid


def test_connect_without_arguments_clears_a_lost_pin():
    bridge, _hosts, live = make(WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live[:] = [GUI]
    assert (
        data(bridge.call_tool("inspect", {"what": "node", "target": "/obj"}))["code"]
        == "instance_lost"
    )
    assert data(bridge.call_tool("houdini_connect", {}))["connected"]["pid"] == GUI.pid
    assert not bridge.call_tool("inspect", {"what": "node", "target": "/obj"}).is_error


def test_lost_pin_with_nothing_running_is_still_instance_lost():
    bridge, _hosts, live = make(WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.clear()
    error = data(bridge.call_tool("inspect", {"what": "node", "target": "/obj"}))
    assert error["code"] == "instance_lost" and "candidates" not in error
    assert "none is running" in error["message"]


def test_quit_of_a_lost_pin_is_instance_lost():
    bridge, _hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    error = data(bridge.call_tool("houdini_connect", {"quit": True}))
    assert error["code"] == "instance_lost"


# -- 2. several instances and no pin (review 19 papercut 2) ----------------------------------


def test_mutating_call_refuses_when_ambiguous_and_names_the_calls():
    bridge, hosts, _live = make(GUI, WORKER)
    result = bridge.call_tool("edit", {"ops": [{"op": "delete", "paths": ["/obj/geo1"]}]})
    assert result.is_error
    error = data(result)
    assert error["code"] == "ambiguous_instance" and error["retryable"] is False
    assert [c["pid"] for c in error["candidates"]] == [3084, 61900]  # GUI first
    assert 'houdini_connect {"pid": 3084}' in error["hint"]
    assert 'houdini_connect {"pid": 61900}' in error["hint"]
    assert host_of(hosts, GUI).calls == [] and host_of(hosts, WORKER).calls == []


def test_reads_go_to_the_gui_and_say_so():
    """The GUI is preferred over a newer headless worker, and the guess is visible."""
    bridge, hosts, _live = make(GUI, WORKER)
    result = bridge.call_tool("time", {})
    assert not result.is_error
    body = data(result)
    assert body["pid"] == GUI.pid
    assert body["_instance"]["pid"] == GUI.pid and body["_instance"]["ui"] is True
    assert "none is pinned" in body["_instance"]["warning"]
    assert result.meta["instance"] == {"pid": GUI.pid, "label": "houdinifx", "role": "editor"}
    assert host_of(hosts, WORKER).calls == []


@pytest.mark.parametrize(
    ("tool", "args", "refused"),
    [
        ("time", {}, False),
        ("time", {"frame": 12}, True),
        ("edit", {"ops": [{"op": "select", "paths": ["/obj/geo1"]}]}, True),
        ("edit", {"ops": [{"op": "delete", "paths": ["/obj/geo1"]}], "dry_run": True}, True),
        ("job", {"action": "list"}, False),
        ("job", {"action": "status", "job_id": "abc"}, False),
        ("job", {"action": "cancel", "job_id": "abc"}, True),
        ("undo", {"action": "history"}, False),
        ("undo", {"action": "undo"}, True),
        ("look", {}, False),
        ("cook", {"paths": ["/obj/geo1"]}, True),
        ("render", {"rop_path": "/out/gl"}, True),
        ("houdini_python", {"code": "1"}, True),
        ("inspect", {"what": "parms", "target": "/obj/geo1/tx"}, False),
        ("search", {"kind": "types", "query": "scatter"}, False),
        ("hda", {"action": "list"}, False),
        ("pdg", {"action": "status", "top_path": "/tasks/topnet1"}, False),
        ("pdg", {"action": "cook", "top_path": "/tasks/topnet1"}, True),
    ],
)
def test_which_calls_count_as_changing_a_scene(tool, args, refused):
    bridge, _hosts, _live = make(GUI, WORKER)
    result = bridge.call_tool(tool, args)
    code = data(result).get("code") if result.is_error else None
    assert (code == "ambiguous_instance") is refused, data(result)


def test_pinned_instance_takes_mutations_without_the_warning():
    bridge, hosts, _live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    result = bridge.call_tool("edit", {"ops": [{"op": "delete", "paths": ["/obj/geo1"]}]})
    assert not result.is_error
    assert "_instance" not in data(result)
    assert result.meta["instance"] == {"pid": WORKER.pid, "label": "hython", "role": "worker"}
    assert host_of(hosts, WORKER).calls[-1][0] == "edit"


def test_single_instance_is_never_ambiguous():
    bridge, _hosts, _live = make(WORKER)
    result = bridge.call_tool("edit", {"ops": [{"op": "delete", "paths": ["/obj/geo1"]}]})
    assert not result.is_error and "_instance" not in data(result)
    assert result.meta["instance"]["pid"] == WORKER.pid


def test_host_errors_carry_the_instance_too():
    bridge, hosts, _live = make(WORKER)
    host_of(hosts, WORKER).replies["inspect"] = (
        False,
        {"code": "node_not_found", "message": "No node at /obj/x."},
        {},
    )
    result = bridge.call_tool("inspect", {"what": "node", "target": "/obj/x"})
    assert result.is_error and result.meta["instance"]["pid"] == WORKER.pid


def test_status_and_connect_carry_the_instance_and_select_the_gui():
    bridge, _hosts, _live = make(GUI, WORKER)
    result = bridge.call_tool("houdini_status", {})
    status = data(result)
    assert status["connected"]["pid"] == GUI.pid
    assert {row["pid"]: row.get("selected", False) for row in status["instances"]} == {
        3084: True,
        61900: False,
    }
    assert any("ambiguous_instance" in w for w in status["warnings"])
    assert result.meta["instance"]["pid"] == GUI.pid
    connected = bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    assert connected.meta["instance"] == {"pid": WORKER.pid, "label": "hython"}  # bridge-local


# -- 3. jobs go to the Houdini that started them (review 19 papercut 3) -----------------------


def _worker_with_job(hosts):
    worker = host_of(hosts, WORKER)
    worker.replies["render"] = (
        True,
        {"job_id": "61900-9c3e6f7ca53e", "state": "running", "tool": "render"},
        {},
    )
    worker.replies["job"] = lambda args: (
        (True, {"jobs": [{"job_id": "61900-9c3e6f7ca53e", "state": "running"}]}, {})
        if args.get("action") == "list"
        else (
            True,
            {
                "job_id": args["job_id"],
                "state": "running",
                "current": 29,
                "total": 240,
                "message": "frame 29",
            },
            {},
        )
    )
    return worker


def test_job_calls_follow_the_pid_in_the_job_id():
    bridge, hosts, _live = make(GUI, WORKER)
    worker = _worker_with_job(hosts)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    started = data(bridge.call_tool("render", {"rop_path": "/out/gl_two", "wait_s": 0}))
    bridge.call_tool("houdini_connect", {"pid": GUI.pid})  # back to the GUI
    result = bridge.call_tool("job", {"action": "status", "job_id": started["job_id"]})
    assert not result.is_error
    assert data(result)["current"] == 29
    assert result.meta["instance"]["pid"] == WORKER.pid
    assert worker.calls[-1] == ("job", {"action": "status", "job_id": "61900-9c3e6f7ca53e"})
    assert all(call[0] != "job" for call in host_of(hosts, GUI).calls)


def test_job_routing_ignores_ambiguity_and_a_lost_pin():
    bridge, hosts, live = make(GUI, WORKER, WORKER2)
    _worker_with_job(hosts)
    bridge.call_tool("houdini_connect", {"pid": WORKER2.pid})
    live.remove(WORKER2)  # the pin is lost, but the job's own Houdini is alive
    result = bridge.call_tool("job", {"action": "cancel", "job_id": "61900-9c3e6f7ca53e"})
    assert not result.is_error and result.meta["instance"]["pid"] == WORKER.pid


def test_job_of_an_exited_houdini_is_instance_lost_with_its_last_status():
    bridge, hosts, live = make(GUI, WORKER)
    _worker_with_job(hosts)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    bridge.call_tool("render", {"rop_path": "/out/gl_two", "wait_s": 0})
    bridge.call_tool("job", {"action": "status", "job_id": "61900-9c3e6f7ca53e"})
    bridge.call_tool("houdini_connect", {"pid": GUI.pid})
    live.remove(WORKER)  # killed at frame 29
    error = data(bridge.call_tool("job", {"action": "status", "job_id": "61900-9c3e6f7ca53e"}))
    assert error["code"] == "instance_lost" and error["retryable"] is False
    assert "pid 61900 (hython)" in error["message"] and "29/240" in error["message"]
    assert error["detail"]["last_status"]["state"] == "running"
    assert error["candidates"][0]["pid"] == GUI.pid
    assert all(call[0] != "job" for call in host_of(hosts, GUI).calls)


def test_bare_job_id_goes_to_the_selected_instance():
    bridge, hosts, _live = make(GUI, WORKER)
    _worker_with_job(hosts)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    result = bridge.call_tool("job", {"action": "status", "job_id": "9c3e6f7ca53e"})
    assert result.meta["instance"]["pid"] == WORKER.pid


def test_job_list_is_the_selected_instance_and_all_aggregates():
    bridge, hosts, _live = make(GUI, WORKER)
    _worker_with_job(hosts)
    host_of(hosts, GUI).replies["job"] = (True, {"jobs": []}, {})
    selected = data(bridge.call_tool("job", {"action": "list"}))  # unpinned read: the GUI
    assert selected["jobs"] == [] and selected["_instance"]["pid"] == GUI.pid
    every = data(bridge.call_tool("job", {"action": "list", "all": True}))
    [row] = every["jobs"]  # the agent sees the ledger id (BIBLE §3.8)
    assert row["job_id"].startswith("j") and row["state"] == "running" and row["pid"] == 61900
    assert bridge.ledger.to_host(row["job_id"]) == (61900, "61900-9c3e6f7ca53e")
    assert every["instances"] == [
        {"pid": 3084, "label": "houdinifx", "jobs": 0, "running": 0},
        {"pid": 61900, "label": "hython", "jobs": 1, "running": 1},
    ]
    # the host never sees the bridge-only argument
    assert all("all" not in args for tool, args in host_of(hosts, GUI).calls if tool == "job")


# -- 4. instance rows: busy, jobs_running, name, selected (review 19 papercuts 4, 9) ----------


def test_rows_show_busy_jobs_running_and_selected():
    bridge, hosts, _live = make(GUI, WORKER)
    host_of(hosts, WORKER).health_extra = {"busy": True, "jobs_running": 1}
    host_of(hosts, GUI).health_extra = {"busy": False, "jobs_running": 0}
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    rows = {row["pid"]: row for row in data(bridge.call_tool("houdini_status", {}))["instances"]}
    assert rows[61900]["busy"] is True and rows[61900]["jobs_running"] == 1
    assert rows[61900]["selected"] is True and "selected" not in rows[3084]
    # 2.0 M4: false and zero are left out
    assert "busy" not in rows[3084] and "jobs_running" not in rows[3084]


def test_unreachable_row_says_so():
    from hocuspocus.tools.errors import ToolError

    bridge, hosts, _live = make(GUI, WORKER)

    def refuse(timeout_s=5.0):
        raise ToolError("houdini_offline", "refused", detail={"reason": "unreachable"})

    host_of(hosts, WORKER).health = refuse
    rows = {row["pid"]: row for row in data(bridge.call_tool("houdini_status", {}))["instances"]}
    assert rows[61900]["unreachable"] == "houdini_offline" and "busy" not in rows[61900]


def _registered(tmp_path, inst: Instance) -> Instance:
    from dataclasses import replace

    entry = tmp_path / f"{inst.pid}.json"
    entry.write_text(json.dumps({"pid": inst.pid, "port": inst.port, "token": inst.token}))
    return replace(inst, file=entry)


def test_connect_names_an_instance_and_selects_it_by_name(tmp_path):
    from dataclasses import replace

    gui, worker = _registered(tmp_path, GUI), _registered(tmp_path, WORKER)
    bridge, _hosts, live = make(gui, worker)
    out = data(bridge.call_tool("houdini_connect", {"pid": worker.pid, "name": "worker"}))
    assert out["connected"]["name"] == "worker"
    assert json.loads(worker.file.read_text())["name"] == "worker"  # in the registry entry
    live[:] = [gui, replace(worker, name="worker")]  # what the next scan reads
    bridge.call_tool("houdini_connect", {"pid": gui.pid})
    result = bridge.call_tool("houdini_connect", {"name": "worker"})
    assert data(result)["connected"]["pid"] == worker.pid
    assert result.meta["instance"]["pid"] == worker.pid
    rows = data(bridge.call_tool("houdini_status", {}))["instances"]
    assert {row["pid"]: row.get("name") for row in rows} == {3084: None, 61900: "worker"}
    forwarded = bridge.call_tool("inspect", {"what": "node", "target": "/obj"})
    assert forwarded.meta["instance"] == {
        "pid": 61900,
        "label": "hython",
        "name": "worker",
        "role": "worker",
    }


def test_a_name_moves_from_the_instance_that_had_it(tmp_path):
    from dataclasses import replace

    gui, worker = _registered(tmp_path, GUI), _registered(tmp_path, WORKER)
    bridge, _hosts, live = make(gui, worker)
    bridge.call_tool("houdini_connect", {"pid": worker.pid, "name": "main"})
    live[:] = [gui, replace(worker, name="main")]
    bridge.call_tool("houdini_connect", {"pid": gui.pid, "name": "main"})
    assert "name" not in json.loads(worker.file.read_text())
    assert json.loads(gui.file.read_text())["name"] == "main"


def test_unknown_name_lists_candidates():
    bridge, _hosts, _live = make(GUI, WORKER)
    error = data(bridge.call_tool("houdini_connect", {"name": "editor"}))
    assert error["code"] == "houdini_offline" and error["retryable"] is False
    assert [c["pid"] for c in error["candidates"]] == [3084, 61900]


def test_connect_to_a_dead_pid_is_not_retryable_and_labels_candidates():
    bridge, _hosts, _live = make(GUI, WORKER2)
    error = data(bridge.call_tool("houdini_connect", {"pid": 61900}))
    assert error["code"] == "houdini_offline" and error["retryable"] is False
    assert error["candidates"] == [
        {"pid": 3084, "label": "houdinifx", "ui": True, "hip": "C:/work/city_work.hip"},
        {"pid": 61996, "label": "hython", "ui": False, "hip": ""},
    ]
    assert "3084 (houdinifx, GUI, city_work.hip)" in error["message"]


# -- 5. events cursors carry their instance (review 19 papercut 8) ---------------------------


def _events_host(host: Host, last: int) -> None:
    def reply(args):
        since = args.get("since", 0)
        out = {"events": [], "next_since": max(since, last), "dropped": 0}
        if since > last:
            out = {"reset": True, "events": [], "next_since": last, "dropped": 0}
        return True, out, {}

    host.replies["events"] = reply


def test_next_since_is_tagged_with_the_pid_and_round_trips():
    bridge, hosts, _live = make(GUI)
    _events_host(host_of(hosts, GUI), last=9)
    first = data(bridge.call_tool("events", {}))
    assert first["next_since"] == "3084:9"
    again = data(bridge.call_tool("events", {"since": first["next_since"]}))
    assert "reset" not in again
    assert host_of(hosts, GUI).calls[-1] == ("events", {"since": 9})


def test_cursor_from_another_instance_resets_with_a_note():
    bridge, hosts, _live = make(GUI, WORKER)
    _events_host(host_of(hosts, WORKER), last=4)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    out = data(bridge.call_tool("events", {"since": "3084:9"}))
    assert out["reset"] is True and "pid 3084" in out["note"] and "61900" in out["note"]
    assert out["next_since"] == "61900:4"
    assert host_of(hosts, WORKER).calls[-1] == ("events", {"since": 0})


def test_bare_seq_still_works_and_bad_cursors_are_invalid():
    bridge, hosts, _live = make(GUI)
    _events_host(host_of(hosts, GUI), last=3)
    assert data(bridge.call_tool("events", {"since": 2}))["next_since"] == "3084:3"
    error = data(bridge.call_tool("events", {"since": "yesterday"}))
    assert error["code"] == "invalid_argument" and "next_since" in error["message"]


# -- 6. the guide, the tool reference and the prompts (review 19 papercuts 5, 6, 7, 10) -------


def test_guide_is_instructions_and_recipes_under_8_kb():
    from hocuspocus.bridge.instructions import GUIDE_MAX_BYTES, guide_text

    guide = guide_text()
    assert len(guide.encode("utf-8")) <= GUIDE_MAX_BYTES == 8192
    assert "## Tools" not in guide and "## houdini_status" not in guide
    for needle in (
        "### Two Houdinis",
        "ambiguous_instance",
        "instance_lost",
        "<pid>-<id>",
        "<pid>:<seq>",
        "### Copernicus",
        "/img",
        "copnet",
        "rop_image",
        "render {rop_path",
        "op:/img/",
        "spare_parms",
        "hocuspocus://tools",
        "### Flipbook frames",
    ):
        assert needle in guide, needle
    # 1.4: the guide recommends the Flipbook ROP, never the OpenGL ROP it replaces.
    assert "Driver/flipbook" in guide and "deprecate" in guide
    assert "opengl_rop" not in guide and 'type: "opengl"' not in guide


def test_v2_guide_is_under_6_5_kb_and_warns_about_gui_dialogs():
    """spec-2.0 §7 M4: the 2.0 guide fits 6.5 KB with every recipe, and carries the GUI
    modal-dialog paragraph (docs/parity.md G5)."""
    from hocuspocus.bridge.instructions import GUIDE_2X_MAX_BYTES, guide_text

    guide = guide_text()
    assert len(guide.encode("utf-8")) <= GUIDE_2X_MAX_BYTES == 6656
    for heading in (
        "### Build, check and look",
        "### Two Houdinis",
        "### Copernicus",
        "### Flipbook frames",
        "### Add a spare parm",
        "### GUI sessions: never open a dialog",
    ):
        assert heading in guide, heading
    assert "hou.ui" in guide and "houdini_busy" in guide and "busy: true" in guide


def test_tools_resource_is_the_reference_for_the_profile():
    from hocuspocus.bridge import resources as bridge_resources

    bridge, _hosts, _live = make(GUI, config=BridgeConfig(profile="core"))
    listed = {str(r.uri) for r in bridge_resources.list_resources()}
    assert "hocuspocus://tools" in listed
    text = bridge_resources.read(bridge, "hocuspocus://tools").contents[0].text
    assert "## houdini_status" in text and "## look" in text
    assert "## viewport_capture" not in text  # removed in 2.1
    assert "## events" not in text  # a full-profile tool
    full, _h, _l = make(GUI)
    assert "## events" in bridge_resources.read(full, "hocuspocus://tools").contents[0].text


def test_instructions_mention_pinning_and_the_tool_reference():
    from hocuspocus.bridge.instructions import INSTRUCTIONS

    assert "houdini_connect {pid}" in INSTRUCTIONS and "ambiguous_instance" in INSTRUCTIONS
    assert "instance_lost" in INSTRUCTIONS and "hocuspocus://tools" in INSTRUCTIONS
    assert len(INSTRUCTIONS.split()) <= 400


def _prompt(name, args=None):
    from hocuspocus.bridge.server import get_prompt

    return get_prompt(name, args).messages[0].content.text


def test_inspect_scene_reads_the_outline_and_asks_to_pin():
    text = _prompt("inspect_scene", {"root": "/obj"})
    assert "houdini://outline" in text and 'what: "outline"' in text
    assert 'inspect {what: "problems", target: "/obj"}' in text
    assert "houdini_connect {pid}" in text and "depth 2" not in text


def test_build_sop_chain_frames_the_result():
    text = _prompt("build_sop_chain", {"description": "a torus"})
    assert 'look {"target": <the geo object>}' in text
    assert "Then cook the display node" not in text


def test_turntable_checks_display_isolates_and_leaves_the_playbar():
    text = _prompt("turntable_preview", {"path": "/obj/building_gen"})
    assert "display flag" in text and "{display: true}" in text
    assert "block the view" in text
    assert "resolution: [resx, resy]" in text
    assert "Do not change the playbar range in a GUI session" in text
    assert "Set the playbar range" not in text


def test_debug_red_node_drops_the_mandatory_cook_and_names_spare_parms():
    text = _prompt("debug_red_node", {"path": "/obj/geo1/wrangle1"})
    assert "then cook" not in text and "spare_parms" in text


def test_look_fit_has_no_schema_default():
    from hocuspocus.tools.catalog import get

    spec = get("look")
    assert "default" not in spec.input_schema["properties"]["fit"]


# -- a job id whose pid was never ours is job_not_found (review 21 papercut 3, 22 #7) -------


@pytest.mark.parametrize("job_id", ["999-deadbeef", "123-abc"])
def test_made_up_job_id_is_job_not_found_not_a_dead_houdini(job_id):
    bridge, hosts, _live = make(GUI, WORKER)
    error = data(bridge.call_tool("job", {"action": "status", "job_id": job_id}))
    assert error["code"] == "job_not_found" and error["retryable"] is False
    assert (
        "exited" not in error["message"] and "not a Houdini this server knows" in error["message"]
    )
    assert 'job {action: "list", all: true}' in error["hint"]
    assert all(call[0] != "job" for host in hosts.values() for call in host.calls)


def test_job_of_a_pid_seen_in_the_registry_is_still_instance_lost():
    bridge, hosts, live = make(GUI, WORKER)
    bridge.call_tool(
        "inspect", {"what": "node", "target": "/obj"}
    )  # the bridge sees both instances
    live.remove(WORKER)
    error = data(bridge.call_tool("job", {"action": "status", "job_id": "61900-0000abcd"}))
    assert error["code"] == "instance_lost" and "pid 61900" in error["message"]


def test_job_of_a_launched_houdini_is_instance_lost_from_a_fresh_bridge(tmp_path):
    from hocuspocus.bridge.instances import LaunchLog

    log = LaunchLog(tmp_path / "launches")
    log.record(WORKER, mode="headless", outlives_server=False)
    bridge, _hosts, live = make(GUI)
    bridge.launches = log
    error = data(bridge.call_tool("job", {"action": "status", "job_id": "61900-9c3e6f7ca53e"}))
    assert error["code"] == "instance_lost"
