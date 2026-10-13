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
            "host_version": "1.3.0",
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
        ("node_info", {"paths": ["/obj"]}),
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
    assert host_of(hosts, GUI).calls == []  # nothing reached the GUI


def test_status_reports_the_lost_pin_and_connects_nothing():
    bridge, _hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    status = data(bridge.call_tool("houdini_status", {}))
    assert status["connected"] is None
    assert status["lost"] == {"pid": 61900, "label": "hython"}
    assert [row["selected"] for row in status["instances"]] == [False]
    assert any("61900" in w and "houdini_connect" in w for w in status["warnings"])


def test_lost_pin_clears_only_on_an_explicit_connect():
    bridge, hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    live.append(WORKER2)  # a new worker does not take over either
    assert data(bridge.call_tool("node_info", {"paths": ["/obj"]}))["code"] == "instance_lost"
    connected = data(bridge.call_tool("houdini_connect", {"pid": GUI.pid}))
    assert connected["connected"]["pid"] == GUI.pid
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert not result.is_error and data(result)["pid"] == GUI.pid


def test_connect_without_arguments_clears_a_lost_pin():
    bridge, _hosts, live = make(WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live[:] = [GUI]
    assert data(bridge.call_tool("node_info", {"paths": ["/obj"]}))["code"] == "instance_lost"
    assert data(bridge.call_tool("houdini_connect", {}))["connected"]["pid"] == GUI.pid
    assert not bridge.call_tool("node_info", {"paths": ["/obj"]}).is_error


def test_lost_pin_with_nothing_running_is_still_instance_lost():
    bridge, _hosts, live = make(WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.clear()
    error = data(bridge.call_tool("node_info", {"paths": ["/obj"]}))
    assert error["code"] == "instance_lost" and "candidates" not in error
    assert "none is running" in error["message"]


def test_quit_of_a_lost_pin_is_instance_lost():
    bridge, _hosts, live = make(GUI, WORKER)
    bridge.call_tool("houdini_connect", {"pid": WORKER.pid})
    live.remove(WORKER)
    error = data(bridge.call_tool("houdini_connect", {"quit": True}))
    assert error["code"] == "instance_lost"
