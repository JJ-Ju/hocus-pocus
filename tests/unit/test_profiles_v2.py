"""The ``v2`` profile (spec-2.0 §2, §7 M1): ``full`` plus the 2.0 tools, everywhere a
profile is read: the catalogue, the bridge's config and listing, and the host's config
and enforcement (BIBLE §3.5, §3.7)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.host.config import HostConfig, load_config
from hocuspocus.host.dispatch import Dispatcher
from hocuspocus.tools import catalog
from hocuspocus.tools.catalog import TOOLS, ToolSpec, for_profile, in_profile, profile_of

pytestmark = pytest.mark.unit


def _status_profile_enum(tools: tuple[ToolSpec, ...]) -> list[str]:
    status = next(spec for spec in tools if spec.name == "houdini_status")
    return status.output_schema["properties"]["profile"]["enum"]


def test_v2_lists_every_tool_in_catalogue_order() -> None:
    assert catalog.PROFILES[-1] == "v2"
    assert [spec.name for spec in for_profile("v2")] == [spec.name for spec in TOOLS]
    full = {spec.name for spec in for_profile("full")}
    v2_only = [spec.name for spec in TOOLS if spec.name not in full]
    assert v2_only == [spec.name for spec in TOOLS if spec.profile == "v2"]
    for spec in TOOLS:
        assert in_profile(spec, "v2"), spec.name
        assert in_profile(spec, "full") is (spec.profile != "v2"), spec.name


def test_a_v2_spec_is_outside_every_1x_profile() -> None:
    spec = ToolSpec(name="probe", description="", input_schema={}, profile="v2")
    assert profile_of(spec) == "v2"
    assert [p for p in catalog.PROFILES if in_profile(spec, p)] == ["v2"]
    assert in_profile(spec, "bogus") is False  # unknown reads as core


def test_houdini_status_names_v2_only_in_the_v2_listing() -> None:
    """The 1.x listings keep the 1.4 bytes (goldens); a v2 bridge reports profile "v2",
    so its houdini_status output schema must allow it."""
    for profile in ("minimal", "core", "full"):
        assert _status_profile_enum(for_profile(profile)) == ["minimal", "core", "full"]
    assert _status_profile_enum(TOOLS) == ["minimal", "core", "full"]
    assert _status_profile_enum(for_profile("v2")) == ["minimal", "core", "full", "v2"]
    unpatched = [spec for spec in for_profile("v2") if spec.name != "houdini_status"]
    assert all(spec is catalog.get(spec.name) for spec in unpatched)


def test_bridge_reads_v2_from_toml_and_env(tmp_path, monkeypatch) -> None:
    from hocuspocus.bridge import config as bc

    monkeypatch.setattr(bc, "default_pref_dirs", lambda *a, **k: [tmp_path / "default"])
    prefs = tmp_path / "houdini22.0"
    prefs.mkdir()
    (prefs / "hocuspocus.toml").write_text('profile = "v2"\n', encoding="utf-8")
    env = {
        "HOCUSPOCUS_STATE_DIR": str(tmp_path / "state"),
        "HOUDINI_USER_PREF_DIR": str(tmp_path / "houdini__HVER__"),
    }
    assert BridgeConfig.load(env).profile == "v2"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "V2"}).profile == "v2"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "full"}).profile == "full"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "v3"}).profile == "core"


def test_bridge_lists_the_v2_profile_and_reports_it() -> None:
    from hocuspocus.bridge.local_tools import LOCAL_TOOLS
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile="v2"), scan=lambda: [])
    assert [tool.name for tool in bridge.list_tools()] == [spec.name for spec in TOOLS]
    assert bridge.tools == for_profile("v2")
    status = LOCAL_TOOLS["houdini_status"](bridge, {})
    assert status["profile"] == "v2"
    assert status["profile"] in _status_profile_enum(bridge.tools)
    both = Bridge(BridgeConfig(profile="v2", result_content="both"), scan=lambda: [])
    listed = {tool.name: tool for tool in both.list_tools()}
    schema = listed["houdini_status"].output_schema
    assert json.dumps(schema["properties"]["profile"]) == (
        '{"type": "string", "enum": ["minimal", "core", "full", "v2"]}'
    )


def test_host_config_accepts_v2(tmp_path) -> None:
    (tmp_path / "hocuspocus.toml").write_text('profile = "v2"\n', encoding="utf-8")
    assert load_config(pref_dir=str(tmp_path), environ={}).profile == "v2"
    assert load_config(environ={"HOCUSPOCUS_PROFILE": "v2"}).profile == "v2"
    assert HostConfig().with_overrides(profile="v2").profile == "v2"
    assert HostConfig().with_overrides(profile="v3").profile == "core"  # logged, ignored


@dataclass
class _Impl:
    spec: ToolSpec
    name: str = "probe"
    mutating: bool = False
    headless_ok: bool = True
    main_thread: bool = False
    scene: bool = True

    def fn(self, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"answered": True}


class _Ctx:
    def __init__(self, profile: str) -> None:
        from hocuspocus.host.tools.registry import SceneState

        self.config = HostConfig(profile=profile)
        self.scene = SceneState()
        self.extras: dict[str, Any] = {}
        self.logger = logging.getLogger("test")
        self.ui = False


def test_host_refuses_v2_tools_below_v2_and_names_the_profile() -> None:
    spec = ToolSpec(name="probe", description="", input_schema={}, profile="v2")
    for profile in ("minimal", "core", "full"):
        dispatcher = Dispatcher(_Ctx(profile), lambda name: _Impl(spec))
        envelope = dispatcher.call("probe", {})
        assert envelope["ok"] is False, profile
        error = envelope["error"]
        assert error["code"] == "invalid_argument"
        assert (
            f"v2-profile tool, and this Houdini's host runs the {profile} profile"
            in (error["message"])
        )
        assert 'profile = "v2" in hocuspocus.toml' in error["hint"]
        assert "HOCUSPOCUS_PROFILE=v2" in error["hint"] and '"full"' not in error["hint"]
    dispatcher = Dispatcher(_Ctx("v2"), lambda name: _Impl(spec))
    assert dispatcher.call("probe", {}) == {
        "ok": True,
        "result": {"answered": True},
        "_meta": dispatcher.call("probe", {})["_meta"],
    }


# -- the 2.0 tools through the bridge -------------------------------------------------------


class _Host:
    """A fake host answering ``inspect`` the way the real one does for events and jobs."""

    def __init__(self, inst: Any) -> None:
        self.inst = inst
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": self.inst.pid, "houdini": "22.0.466",
                "generation": 1, "host_version": "1.4.0"}  # fmt: skip

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append((tool, dict(args or {})))
        if args.get("what") == "events":
            body = {"events": [], "next_since": max(args.get("since", 0), 9), "dropped": 0}
        else:
            body = {"jobs": []}
        return True, {"what": args.get("what"), "target": None, "etag": "e", **body}, {}

    def job(self, job_id, timeout_s=10.0):
        return self.call("job", {"action": "status", "job_id": job_id}, timeout_s)

    def call_jobs(self, request_id, timeout_s=5.0):
        return []


def _v2_bridge(tmp_path, monkeypatch, *pids: int):
    from hocuspocus.bridge.instances import Instance
    from hocuspocus.bridge.server import Bridge

    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    live = [
        Instance(
            pid=pid,
            port=50000 + i,
            token=f"t{i}",
            houdini="22.0.466",
            ui=False,
            started="2026-10-14T10:00:00Z",
            label="hython",
        )  # fmt: skip
        for i, pid in enumerate(pids)
    ]
    hosts = {inst.port: _Host(inst) for inst in live}
    bridge = Bridge(
        BridgeConfig(profile="v2"),
        client_factory=lambda port, token: hosts[port],
        scan=lambda: list(live),
    )
    bridge.exit_grace_s = 0.0
    return bridge, hosts, live


def _data(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def test_inspect_events_cursor_is_tagged_like_events(tmp_path, monkeypatch) -> None:
    """spec-2.0 §2.3: inspect what: events is events, so next_since is '<pid>:<seq>' and
    round-trips, and a cursor of another Houdini reads from the start with a note."""
    bridge, hosts, live = _v2_bridge(tmp_path, monkeypatch, 3084)
    first = _data(bridge.call_tool("inspect", {"what": "events"}))
    assert first["next_since"] == "3084:9" and first["what"] == "events"
    _data(bridge.call_tool("inspect", {"what": "events", "since": first["next_since"]}))
    host = hosts[live[0].port]
    assert host.calls[-1] == ("inspect", {"what": "events", "since": 9})
    other = _data(bridge.call_tool("inspect", {"what": "events", "since": "61900:4"}))
    assert other["reset"] is True and "pid 61900" in other["note"]
    assert host.calls[-1] == ("inspect", {"what": "events", "since": 0})
    error = _data(bridge.call_tool("inspect", {"what": "events", "since": "soon"}))
    assert error["code"] == "invalid_argument" and "next_since" in error["message"]


def test_inspect_jobs_routes_a_job_id_to_its_houdini(tmp_path, monkeypatch) -> None:
    bridge, hosts, live = _v2_bridge(tmp_path, monkeypatch, 3084, 61900)
    bridge.call_tool("houdini_connect", {"pid": 3084})
    _data(bridge.call_tool("inspect", {"what": "jobs", "job_id": "61900-9c3e"}))
    assert hosts[live[1].port].calls[-1] == ("inspect", {"what": "jobs", "job_id": "61900-9c3e"})
    assert not any(tool == "inspect" for tool, _ in hosts[live[0].port].calls)
    _data(bridge.call_tool("inspect", {"what": "jobs"}))  # a list goes to the pinned one
    assert hosts[live[0].port].calls[-1] == ("inspect", {"what": "jobs"})
