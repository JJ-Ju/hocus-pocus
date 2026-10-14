"""The 2.0 profiles and ``compat_1x`` (spec-2.0 §2, §7 M3, §8; BIBLE §3.5) everywhere a
profile is read: the catalogue, the migration hints, the bridge's config, listing and
refusals, and the host's config and enforcement."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.host.config import HostConfig, load_config
from hocuspocus.host.dispatch import Dispatcher, profile_error
from hocuspocus.tools import catalog, migration
from hocuspocus.tools.catalog import TOOLS, ToolSpec, for_profile, get

pytestmark = pytest.mark.unit

# The 1.4 full catalogue in 1.4 order (BIBLE §4.2-§4.7 as of 1.4.0): what compat_1x lists.
TOOLS_1_4 = [
    "houdini_status", "houdini_connect",
    "hip_new", "hip_open", "hip_save", "hip_merge",
    "node_find", "node_info", "node_create", "node_delete", "node_edit", "node_copy",
    "node_connect", "node_layout", "network_describe", "network_build",
    "parm_get", "parm_set",
    "cook", "problems", "geo_info", "geo_read",
    "viewport_capture", "render", "houdini_python", "node_type_search", "node_type_info",
    "undo", "time", "selection", "job",
    "hda", "usd_stage", "pdg", "events",
]  # fmt: skip
# The 1.4 tools 2.0 removes from its profiles (spec-2.0 §2.4, §8). parm_get is the
# eighteenth: 35 1.4 tools minus the 17 that 2.0's full keeps.
REMOVED = {
    "viewport_capture", "node_info", "node_find", "network_describe", "geo_info", "geo_read",
    "usd_stage", "node_type_info", "node_type_search", "problems", "node_delete", "node_edit",
    "node_copy", "node_connect", "node_layout", "network_build", "selection", "parm_get",
}  # fmt: skip
NEW_IN_2 = {"inspect", "search", "edit", "look"}


def _names(profile: str) -> list[str]:
    return [spec.name for spec in for_profile(profile)]


def _status_profile_enum(tools: tuple[ToolSpec, ...]) -> list[str]:
    status = next(spec for spec in tools if spec.name == "houdini_status")
    return status.output_schema["properties"]["profile"]["enum"]


# -- the catalogue ----------------------------------------------------------------------------


def test_profile_sizes_and_nesting() -> None:
    sizes = {profile: len(_names(profile)) for profile in catalog.PROFILES}
    assert sizes == {"minimal": 10, "core": 18, "full": 21, "compat_1x": 35}
    assert set(_names("minimal")) < set(_names("core")) < set(_names("full"))
    assert catalog.DEFAULT_PROFILE == "core"


def test_compat_1x_is_the_1_4_full_catalogue_with_1_4_schemas() -> None:
    assert _names("compat_1x") == TOOLS_1_4
    for spec in for_profile("compat_1x"):
        assert spec is get(spec.name), spec.name  # no v2_extra merged in
    assert _status_profile_enum(for_profile("compat_1x")) == ["minimal", "core", "full"]
    assert "on" not in get("cook").input_schema["properties"]
    core_cook = next(spec for spec in for_profile("core") if spec.name == "cook")
    assert "on" in core_cook.input_schema["properties"]


def test_the_2x_profiles_drop_exactly_the_removed_tools() -> None:
    assert set(TOOLS_1_4) - set(_names("full")) == REMOVED
    assert set(_names("full")) - set(TOOLS_1_4) == NEW_IN_2
    assert {spec.name for spec in TOOLS if spec.profiles == ("compat_1x",)} == REMOVED
    for spec in TOOLS:
        assert ("compat_1x" in spec.profiles) is (spec.name in TOOLS_1_4), spec.name


def test_every_removed_tool_has_a_migration_hint() -> None:
    assert set(migration.REPLACEMENTS) == REMOVED
    assert list(migration.REPLACEMENTS) == [n for n in TOOLS_1_4 if n in REMOVED]
    for name, use in migration.REPLACEMENTS.items():
        assert use.split()[0] in NEW_IN_2, name
        assert use.split()[0] in _names("minimal"), name  # every replacement is everywhere
        hint = migration.hint(name)
        assert hint.startswith(f"In 2.0 use {use}.") and 'profile = "compat_1x"' in hint
    assert migration.replacement("viewport_capture").startswith("look")
    assert migration.replacement("node_find") == "search kind: nodes"
    assert migration.replacement("node_type_search") == "search kind: types"
    assert migration.replacement("node_connect") == "edit op: connect"
    assert migration.replacement("usd_stage") == "inspect what: stage"
    assert migration.hint("cook") is None and migration.replacement("inspect") is None


def test_v2_is_an_alias_of_full() -> None:
    assert for_profile("v2") is for_profile("full")
    assert catalog.normalize("V2") == "full" and catalog.normalize(" compat_1x ") == "compat_1x"
    assert catalog.normalize("") == "core" and catalog.normalize("v3") is None


# -- the bridge -------------------------------------------------------------------------------


def test_bridge_profile_default_alias_and_toml(tmp_path, monkeypatch) -> None:
    from hocuspocus.bridge import config as bc

    assert BridgeConfig().profile == "core"
    monkeypatch.setattr(bc, "default_pref_dirs", lambda *a, **k: [tmp_path / "default"])
    prefs = tmp_path / "houdini22.0"
    prefs.mkdir()
    env = {
        "HOCUSPOCUS_STATE_DIR": str(tmp_path / "state"),
        "HOUDINI_USER_PREF_DIR": str(tmp_path / "houdini__HVER__"),
    }
    assert BridgeConfig.load(env).profile == "core"  # no toml: the default
    toml = prefs / "hocuspocus.toml"
    toml.write_text('profile = "compat_1x"\n', encoding="utf-8")
    assert BridgeConfig.load(env).profile == "compat_1x"
    toml.write_text('profile = "v2"\n', encoding="utf-8")
    assert BridgeConfig.load(env).profile == "full"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "V2"}).profile == "full"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "minimal"}).profile == "minimal"
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "v3"}).profile == "core"


def test_bridge_lists_its_profile_and_reports_it() -> None:
    from hocuspocus.bridge.local_tools import LOCAL_TOOLS
    from hocuspocus.bridge.server import Bridge

    for profile in ("minimal", "core", "full"):
        bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
        assert bridge.tools == for_profile(profile) and bridge.v2
        status = LOCAL_TOOLS["houdini_status"](bridge, {})
        assert status["profile"] == profile and "compat_1x" not in status
        assert status["profile"] in _status_profile_enum(bridge.tools)
    alias = Bridge(BridgeConfig(profile="v2"), scan=lambda: [])
    assert alias.config.profile == "full" and alias.tools == for_profile("full")
    compat = Bridge(BridgeConfig(profile="compat_1x"), scan=lambda: [])
    assert [tool.name for tool in compat.list_tools()] == TOOLS_1_4 and not compat.v2
    status = LOCAL_TOOLS["houdini_status"](compat, {})
    assert status["profile"] == "full" and status["compat_1x"] is True
    assert status["profile"] in _status_profile_enum(compat.tools)  # the 1.4 schema holds


def _text(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("profile", ["minimal", "core", "full"])
def test_a_2x_bridge_answers_a_removed_tool_with_its_replacement(profile) -> None:
    from mcp.shared.exceptions import MCPError

    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
    for name in sorted(REMOVED):
        result = bridge.call_tool(name, {"paths": ["/obj"]})
        assert result.is_error, name
        error = _text(result)
        assert error["code"] == "invalid_argument", name
        assert error["message"] == (
            f"{name} is a 1.4 tool that the 2.0 {profile} profile does not serve."
        )
        assert error["hint"] == migration.hint(name)
    with pytest.raises(MCPError):  # any other unknown name is still a protocol error
        bridge.call_tool("node_infos", {})


def test_a_compat_1x_bridge_sends_its_profile_to_the_host(monkeypatch) -> None:
    from hocuspocus.bridge.client import HostClient
    from hocuspocus.bridge.instances import Instance
    from hocuspocus.bridge.server import Bridge

    inst = Instance(pid=3084, port=50000, token="t", houdini="22.0.466", ui=False,
                    started="2026-10-14T10:00:00Z", label="hython")  # fmt: skip
    sent: list[dict[str, Any]] = []

    def fake_request(self, method, path, body=None, read_timeout_s=None):
        sent.append(dict(body or {}))
        return 200, {"ok": True, "result": {"nodes": []}, "_meta": {}}

    monkeypatch.setattr(HostClient, "_request", fake_request)
    monkeypatch.setattr(HostClient, "_check_status", lambda self, status, data: None)
    for profile in ("compat_1x", "core"):
        bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [inst])
        client = bridge.client_for(inst)
        assert client.profile == profile
        client.call("node_info", {"paths": ["/obj"]}, 5.0)
        assert sent[-1]["profile"] == profile and sent[-1]["tool"] == "node_info"


# -- the host ---------------------------------------------------------------------------------


def test_host_config_reads_compat_1x_and_the_v2_alias(tmp_path) -> None:
    assert HostConfig().profile == "core"
    (tmp_path / "hocuspocus.toml").write_text('profile = "compat_1x"\n', encoding="utf-8")
    assert load_config(pref_dir=str(tmp_path), environ={}).profile == "compat_1x"
    assert load_config(environ={"HOCUSPOCUS_PROFILE": "v2"}).profile == "full"
    assert HostConfig().with_overrides(profile="v2").profile == "full"
    assert HostConfig().with_overrides(profile="v3").profile == "core"  # logged, ignored


def test_host_refusals_name_the_profile_or_the_replacement() -> None:
    pdg, cook, node_info = get("pdg"), get("cook"), get("node_info")
    error = profile_error(pdg, "core")
    assert error.message == (
        "pdg is a full-profile tool, and this Houdini's host runs the core profile."
    )
    assert 'profile = "full" in hocuspocus.toml' in error.hint
    assert "HOCUSPOCUS_PROFILE=full" in error.hint and '(or "full")' not in error.hint
    assert 'profile = "core" (or "full")' in profile_error(cook, "minimal").hint
    for profile in ("minimal", "core", "full", "v2"):
        error = profile_error(node_info, profile)
        assert error.code == "invalid_argument", profile
        assert "1.4 tool" in error.message and error.hint == migration.hint("node_info")
        assert profile_error(node_info, profile, "compat_1x") is None
        assert profile_error(pdg, profile, "compat_1x") is None
    assert profile_error(node_info, "compat_1x") is None
    assert profile_error(get("edit"), "compat_1x") is None  # a compat host runs 2.0 tools too
    assert profile_error(pdg, "full") is None and profile_error(pdg, "v2") is None


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


def test_the_dispatcher_applies_the_request_profile() -> None:
    spec = get("geo_read")
    for profile in ("minimal", "core", "full"):
        dispatcher = Dispatcher(_Ctx(profile), lambda name: _Impl(spec, name="geo_read"))
        refused = dispatcher.call("geo_read", {})
        assert refused["ok"] is False, profile
        assert "inspect what: geo" in refused["error"]["hint"]
        assert dispatcher.call("geo_read", {}, profile="compat_1x")["ok"] is True
        assert dispatcher.call("geo_read", {}, profile="bogus")["ok"] is False
    dispatcher = Dispatcher(_Ctx("compat_1x"), lambda name: _Impl(spec, name="geo_read"))
    assert dispatcher.call("geo_read", {})["ok"] is True


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
        BridgeConfig(profile="full"),
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
