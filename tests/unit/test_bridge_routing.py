"""Roles and ``on`` routing (spec-2.0 §2.1, §2.5, §3): the pure decisions in
``bridge/routing.py``, the ``v2_extra`` overlays that add ``on`` and ``role`` to the v2
listing only, and the bridge with fake hosts: ``on`` beside a pin, roles on
``houdini_connect``/``houdini_status``, ``recent``, and opaque ledger job ids."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hocuspocus.bridge import routing
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.ledger import Ledger, is_ledger_id
from hocuspocus.bridge.server import Bridge
from hocuspocus.tools import catalog
from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.spec._helpers import ARGUMENT_DESCRIPTION_MAX_WORDS

pytestmark = pytest.mark.unit

GUI = Instance(
    pid=3084, port=51000, token="t-gui", ui=True, hip="C:/work/city.hip",
    started="2026-10-12T10:00:00Z", label="houdinifx",
)  # fmt: skip
W1 = Instance(
    pid=61900, port=51001, token="t-w1", ui=False, hip="C:/work/w1.hip",
    started="2026-10-12T11:00:00Z", label="hython",
)  # fmt: skip
W2 = Instance(
    pid=61996, port=51002, token="t-w2", ui=False, hip="C:/work/w2.hip",
    started="2026-10-12T12:00:00Z", label="hython", name="farm",
)  # fmt: skip


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


# -- pure decisions ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kind", "parsed"),
    [
        (61900, "pid", 61900),
        ("61900", "pid", 61900),
        ("worker", "role", "worker"),
        ("editor", "role", "editor"),
        (" farm ", "name", "farm"),
    ],
)
def test_parse_on(value, kind, parsed):
    target = routing.parse_on(value)
    assert (target.kind, target.value) == (kind, parsed)


@pytest.mark.parametrize("value", [0, -3, "", "  ", True, None, 1.5, ["worker"]])
def test_parse_on_rejects(value):
    with pytest.raises(ToolError) as info:
        routing.parse_on(value)
    assert info.value.code == "invalid_argument"


def _role(inst: Instance) -> str:
    return "editor" if inst.ui else "worker"


def test_least_busy_orders_by_jobs_then_busy_then_preference():
    loads = {GUI.pid: (0, False), W1.pid: (2, False), W2.pid: (0, True)}
    order = routing.order_by_load([GUI, W1, W2], lambda i: loads[i.pid])
    assert [i.pid for i in order] == [GUI.pid, W2.pid, W1.pid]
    loads[W2.pid] = (0, False)  # tie: newest first among workers
    assert routing.order_by_load([W1, W2], lambda i: loads[i.pid])[0] is W2
    unknown = routing.order_by_load([W1, W2], lambda i: None if i is W2 else (5, True))
    assert unknown[0] is W1  # unknown load goes last


def test_pick_by_role_pid_and_name():
    live = [GUI, W1, W2]
    loads = {GUI.pid: (0, False), W1.pid: (0, False), W2.pid: (1, False)}

    def pick(target):
        return routing.pick(target, live, role_of=_role, load=lambda i: loads[i.pid])

    assert pick(routing.Target("role", "worker")) is W1
    assert pick(routing.Target("role", "editor")) is GUI
    assert pick(routing.Target("pid", W2.pid)) is W2
    assert pick(routing.Target("name", "farm")) is W2


def test_pick_errors():
    live = [GUI]
    with pytest.raises(ToolError) as info:
        routing.pick(routing.Target("role", "worker"), live, role_of=_role, load=lambda i: None)
    error = info.value
    assert error.code == "houdini_offline" and error.retryable is False
    assert error.candidates == [{**GUI.candidate(), "role": "editor"}]
    assert "role: 'worker'" in error.hint
    gone = {"pid": W1.pid, "label": "hython", "hip": "C:/work/w1.hip"}
    with pytest.raises(ToolError) as info:
        routing.pick(
            routing.Target("pid", W1.pid),
            live,
            role_of=_role,
            load=lambda i: None,
            remembered=lambda t: gone,
            tool="render",
        )
    assert info.value.code == "instance_lost" and "61900" in info.value.message
    assert "render" in info.value.message and info.value.detail["hip"] == "C:/work/w1.hip"
    with pytest.raises(ToolError) as info:
        routing.pick(routing.Target("name", "nobody"), live, role_of=_role, load=lambda i: None)
    assert info.value.code == "houdini_offline" and info.value.candidates == [GUI.candidate()]


def test_rewrite_job_ids():
    ids = {"1-a": "jaaaaa", "1-b": "jbbbbb"}
    payload = {
        "job_id": "1-a",
        "jobs": [{"job_id": "1-b"}, {"job_id": "9-z"}, "junk"],
        "detail": {"job_id": "1-a", "last_status": {"job_id": "1-b", "state": "running"}},
    }
    out = routing.rewrite_job_ids(payload, ids.get)
    assert out["job_id"] == "jaaaaa"
    assert out["jobs"] == [{"job_id": "jbbbbb"}, {"job_id": "9-z"}, "junk"]
    assert out["detail"] == {
        "job_id": "jaaaaa",
        "last_status": {"job_id": "jbbbbb", "state": "running"},
    }
    assert payload["job_id"] == "1-a"  # a copy
    assert routing.rewrite_job_ids([1], ids.get) == [1]


# -- the v2 overlays --------------------------------------------------------------------------


def _props(spec) -> dict[str, Any]:
    return spec.input_schema.get("properties") or {}


def test_on_and_role_are_listed_by_the_2x_profiles_only():
    v2 = {spec.name: spec for spec in catalog.for_profile("full")}
    for profile in ("compat_1x",):
        for spec in catalog.for_profile(profile):
            assert "on" not in _props(spec) and "role" not in _props(spec), (profile, spec.name)
    for name in ("cook", "render", "job"):
        assert _props(v2[name])["on"] == {
            "type": ["integer", "string"],
            "description": "Instance to run on: pid, name or role.",
        }
        assert list(_props(v2[name]))[-1] == "on"  # 1.x keys keep their order
    assert _props(v2["houdini_connect"])["role"]["enum"] == ["editor", "worker"]
    out = v2["houdini_status"].output_schema["properties"]
    assert out["instances"]["items"]["properties"]["role"]["enum"] == ["editor", "worker"]
    assert out["recent"]["type"] == "array"
    for name in routing.ROUTABLE & set(v2):
        assert "on" in _props(v2[name]) and " on " in f" {v2[name].notes} ", name


def test_overlay_arguments_follow_the_catalogue_rules():
    for spec in catalog.for_profile("full"):
        added = (spec.v2_extra.get("input") or {}).get("properties") or {}
        for name, schema in added.items():
            words = len(str(schema.get("description", "")).split())
            assert words <= ARGUMENT_DESCRIPTION_MAX_WORDS, (spec.name, name)
            assert name in spec.notes or f"{{{name}}}" in spec.notes, (spec.name, name)
        assert spec.input_schema.get("additionalProperties") is False, spec.name


def test_merge_keeps_the_base_untouched():
    base = catalog.get("cook")
    merged = catalog.v2_spec(base)
    assert "on" in merged.input_schema["properties"] and "on" not in base.input_schema["properties"]
    assert catalog.v2_spec(catalog.get("hip_save")) is catalog.get("hip_save")


# -- the bridge -------------------------------------------------------------------------------


class Host:
    def __init__(self, inst: Instance) -> None:
        self.inst = inst
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.load: dict[str, Any] = {"jobs_running": 0, "busy": False}
        self.jobs: dict[str, dict[str, Any]] = {}

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": self.inst.pid, **self.load}

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append((tool, dict(args or {})))
        if tool in ("render", "cook"):
            job_id = f"{self.inst.pid}-{len(self.jobs):012x}"
            self.jobs[job_id] = {"job_id": job_id, "tool": tool, "state": "running"}
            return True, dict(self.jobs[job_id]), {}
        if tool == "job":
            action = args.get("action")
            if action == "list":
                return True, {"jobs": list(self.jobs.values())}, {}
            job = self.jobs.get(args.get("job_id"))
            if job is None:
                return False, {"code": "job_not_found", "message": "no"}, {}
            if action == "result":
                return True, {**job, "result": {"outputs": ["x.bgeo"]}}, {}
            return True, dict(job), {}
        if tool == "houdini_status":
            return True, {"hip": {"path": self.inst.hip}}, {}
        return True, {"echo": tool}, {}

    def job(self, job_id, timeout_s=10.0):
        return self.call("job", {"action": "status", "job_id": job_id}, timeout_s)

    def call_jobs(self, request_id, timeout_s=5.0):
        return []

    def quit(self, on_unsaved="fail", timeout_s=70.0):
        return True, {"quitting": True, "pid": self.inst.pid, "hip": self.inst.hip}, {}


def make(*live_instances: Instance, profile: str = "full", ledger: Ledger | None = None):
    live = list(live_instances)
    hosts = {inst.port: Host(inst) for inst in (GUI, W1, W2)}
    bridge = Bridge(
        BridgeConfig(profile=profile),
        client_factory=lambda port, token: hosts[port],
        scan=lambda: list(live),
        ledger=ledger,
    )
    bridge.exit_grace_s = 0.0
    return bridge, hosts, live


def data(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def test_on_worker_runs_beside_the_pinned_editor():
    bridge, hosts, _live = make(GUI, W1, W2)
    hosts[W2.port].load = {"jobs_running": 1, "busy": False}
    assert not bridge.call_tool("houdini_connect", {"pid": GUI.pid}).is_error
    result = bridge.call_tool("render", {"rop_path": "/out/geo", "on": "worker"})
    assert not result.is_error, data(result)
    assert result.meta["instance"] == {"pid": W1.pid, "label": "hython", "role": "worker"}
    job_id = data(result)["job_id"]
    assert is_ledger_id(job_id)  # opaque in v2
    assert hosts[W1.port].calls[-1] == ("render", {"rop_path": "/out/geo"})  # on stripped
    assert bridge.preferred_pid == GUI.pid  # the pin did not move
    status = bridge.call_tool("job", {"action": "status", "job_id": job_id})
    assert not status.is_error and data(status)["job_id"] == job_id
    tool, args = hosts[W1.port].calls[-1]
    assert tool == "job" and args["job_id"].startswith(f"{W1.pid}-")  # mapped back
    assert bridge.ledger.job(job_id)["pid"] == W1.pid
    listed = data(bridge.call_tool("job", {"action": "list", "on": W1.pid}))
    assert [row["job_id"] for row in listed["jobs"]] == [job_id]
    edit = bridge.call_tool("inspect", {"what": "node", "target": "/obj"})
    assert edit.meta["instance"]["pid"] == GUI.pid  # everything else: the pin


def test_on_is_explicit_so_no_ambiguity_refusal():
    bridge, hosts, _live = make(GUI, W1)
    refused = bridge.call_tool("cook", {"paths": ["/obj/g/OUT"]})
    assert data(refused)["code"] == "ambiguous_instance"
    ok = bridge.call_tool("cook", {"paths": ["/obj/g/OUT"], "on": "farm-less", "wait_s": 0})
    assert data(ok)["code"] == "houdini_offline"  # no such name
    ok = bridge.call_tool("cook", {"paths": ["/obj/g/OUT"], "on": GUI.pid})
    assert not ok.is_error and ok.meta["instance"]["role"] == "editor"
    assert "_instance" not in data(ok)


def test_on_a_remembered_dead_instance_is_instance_lost():
    bridge, _hosts, live = make(GUI, W1, W2)
    bridge.call_tool("houdini_connect", {"pid": GUI.pid})
    live.remove(W2)
    error = data(bridge.call_tool("render", {"rop_path": "/out/geo", "on": "farm"}))
    assert error["code"] == "instance_lost" and str(W2.pid) in error["message"]
    error = data(bridge.call_tool("render", {"rop_path": "/out/geo", "on": W2.pid}))
    assert error["code"] == "instance_lost"
    error = data(bridge.call_tool("render", {"rop_path": "/out/geo", "on": 4242}))
    assert error["code"] == "houdini_offline"


def test_compat_1x_has_no_on_and_keeps_host_job_ids():
    bridge, _hosts, _live = make(W1, profile="compat_1x")
    error = data(bridge.call_tool("render", {"rop_path": "/out/geo", "on": "worker"}))
    assert error["code"] == "invalid_argument"
    result = data(bridge.call_tool("render", {"rop_path": "/out/geo"}))
    assert result["job_id"].startswith(f"{W1.pid}-")
    ledger_id = bridge.ledger.ledger_id(result["job_id"])
    status = data(bridge.call_tool("job", {"action": "status", "job_id": ledger_id}))
    assert status["job_id"] == result["job_id"]  # a ledger id is accepted everywhere
    assert "role" not in bridge.call_tool("node_info", {"paths": ["/"]}).meta["instance"]


def test_unknown_ledger_id_is_job_not_found():
    bridge, _hosts, _live = make(W1)
    error = data(bridge.call_tool("job", {"action": "status", "job_id": "jabcde"}))
    assert error["code"] == "job_not_found" and "jabcde" in error["message"]


def test_dead_instance_job_status_and_result_from_the_ledger():
    bridge, _hosts, live = make(W1)
    job_id = data(bridge.call_tool("render", {"rop_path": "/out/geo"}))["job_id"]
    bridge.call_tool("job", {"action": "status", "job_id": job_id})
    live.clear()
    lost = data(bridge.call_tool("job", {"action": "status", "job_id": job_id}))
    assert lost["code"] == "instance_lost" and job_id in lost["message"]
    assert lost["detail"]["job_id"] == job_id and lost["detail"]["last_status"]["state"]
    assert lost["detail"]["last_status"]["job_id"] == job_id
    # A result fetched before the exit is kept.
    host_id = bridge.ledger.to_host(job_id)[1]
    bridge.ledger.record_job(W1.pid, {"job_id": host_id, "state": "done"})
    bridge.ledger.store_result(host_id, {"outputs": ["x.bgeo"]})
    kept = data(bridge.call_tool("job", {"action": "result", "job_id": job_id}))
    assert kept["result"] == {"outputs": ["x.bgeo"]} and "ledger kept" in kept["note"]
    assert kept["job_id"] == job_id


def test_progress_poll_maps_a_ledger_id():
    bridge, hosts, _live = make(W1)
    job_id = data(bridge.call_tool("render", {"rop_path": "/out/geo"}))["job_id"]
    hosts[W1.port].jobs[bridge.ledger.to_host(job_id)[1]].update(current=4, total=9)
    bridge._inflight["req"] = W1
    snap = bridge.progress_snapshot("job", {"action": "status", "job_id": job_id}, "req")
    assert snap["current"] == 4 and snap["total"] == 9


def test_connect_by_role_pins_the_least_busy_worker():
    bridge, hosts, _live = make(GUI, W1, W2)
    hosts[W1.port].load = {"jobs_running": 2, "busy": False}
    out = bridge.call_tool("houdini_connect", {"role": "worker"})
    assert data(out)["connected"]["pid"] == W2.pid and data(out)["connected"]["role"] == "worker"
    assert bridge.preferred_pid == W2.pid
    assert data(bridge.call_tool("houdini_connect", {"role": "editor"}))["connected"]["pid"] == (
        GUI.pid
    )
    error = data(bridge.call_tool("houdini_connect", {"role": "boss"}))
    assert error["code"] == "invalid_argument"
    error = data(bridge.call_tool("houdini_connect", {"role": "worker", "quit": True}))
    assert error["code"] == "invalid_argument"


def test_connect_sets_roles_that_status_reports():
    bridge, _hosts, live = make(GUI, W1)
    out = data(bridge.call_tool("houdini_connect", {"pid": W1.pid, "role": "editor"}))
    assert out["connected"]["role"] == "editor"
    status = data(bridge.call_tool("houdini_status", {}))
    roles = {row["pid"]: row["role"] for row in status["instances"]}
    assert roles == {GUI.pid: "editor", W1.pid: "editor"}
    error = data(bridge.call_tool("houdini_connect", {"role": "worker"}))
    assert error["code"] == "houdini_offline" and {c["role"] for c in error["candidates"]} == {
        "editor"
    }
    data(bridge.call_tool("houdini_connect", {"pid": W1.pid, "name": "sim", "role": "worker"}))
    assert bridge.ledger.find_name("sim")["role"] == "worker"
    live.append(W2)
    named = data(bridge.call_tool("houdini_connect", {"name": "farm", "role": "editor"}))
    assert named["connected"]["pid"] == W2.pid and named["connected"]["role"] == "editor"


def test_recent_lists_quit_and_dead_instances_outside_compat_1x_only(tmp_path):
    ledger = Ledger.at(tmp_path / "state")
    bridge, _hosts, live = make(GUI, W1, W2, ledger=ledger)
    bridge.call_tool("houdini_connect", {"pid": W1.pid})
    quit_ = data(bridge.call_tool("houdini_connect", {"quit": True, "pid": W1.pid}))
    assert quit_["quit"] is True
    live.remove(W1)
    live.remove(W2)  # W2 dies on its own
    status = data(bridge.call_tool("houdini_status", {}))
    recent = {row["pid"]: row for row in status["recent"]}
    assert set(recent) == {W1.pid, W2.pid}
    assert recent[W1.pid]["hip"] == "C:/work/w1.hip" and recent[W1.pid]["role"] == "worker"
    assert recent[W2.pid]["name"] == "farm" and recent[W2.pid]["alive"] is False
    assert [row["pid"] for row in status["instances"]] == [GUI.pid]
    full, _h, _l = make(GUI, profile="compat_1x", ledger=ledger)
    status = data(full.call_tool("houdini_status", {}))
    assert "recent" not in status and "role" not in status["instances"][0]
    assert "role" not in (status["connected"] or {})
