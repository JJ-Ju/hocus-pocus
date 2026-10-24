"""The profiles (spec-2.0 §2, §7 M3; BIBLE §3.5, §3.7, §13, D46) everywhere a profile is
read: the catalogue, the migration hints, the bridge's config, listing and refusals, and
the host's config and enforcement. 2.1 removed ``compat_1x`` and the ``v2`` alias: a
removed 1.4 tool answers with its replacement, and a removed profile name in the config
is read as ``full`` with a warning."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.host.config import HostConfig, load_config
from hocuspocus.host.dispatch import Dispatcher, profile_error
from hocuspocus.tools import catalog, migration, profiles
from hocuspocus.tools.catalog import TOOLS, ToolSpec, for_profile, get

pytestmark = pytest.mark.unit

# The 1.4 full catalogue in 1.4 order (BIBLE Appendix A; what compat_1x listed in 2.0.x).
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
# The 1.4 tools 2.0 replaced (spec-2.0 §2.4, §8) and 2.1 removed. parm_get is the
# eighteenth: 35 1.4 tools minus the 17 that full keeps.
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
    assert catalog.PROFILES == ("minimal", "core", "full")
    sizes = {profile: len(_names(profile)) for profile in catalog.PROFILES}
    assert sizes == {"minimal": 10, "core": 19, "full": 21}
    assert set(_names("minimal")) < set(_names("core")) < set(_names("full"))
    assert catalog.DEFAULT_PROFILE == "core"


def test_the_removed_1x_tools_have_no_spec() -> None:
    assert set(TOOLS_1_4) - set(_names("full")) == REMOVED
    assert set(_names("full")) - set(TOOLS_1_4) == NEW_IN_2
    assert not REMOVED & {spec.name for spec in TOOLS}
    assert all(get(name) is None for name in REMOVED)
    assert _status_profile_enum(TOOLS) == ["minimal", "core", "full"]
    # The 2.0 arguments of the 1.4 tools are part of their specs now (no v2_extra).
    assert "on" in get("cook").input_schema["properties"]
    assert "role" in get("houdini_connect").input_schema["properties"]


def test_every_removed_tool_has_a_migration_hint() -> None:
    assert set(migration.REPLACEMENTS) == REMOVED
    assert list(migration.REPLACEMENTS) == [n for n in TOOLS_1_4 if n in REMOVED]
    for name, use in migration.REPLACEMENTS.items():
        assert use.split()[0] in NEW_IN_2, name
        assert use.split()[0] in _names("minimal"), name  # every replacement is everywhere
        hint = migration.hint(name)
        assert hint.startswith(f"Use {use}.") and "docs/migration-2.0.md" in hint, name
        assert "compat_1x" not in hint and "HOCUSPOCUS_PROFILE" not in hint, name
    assert migration.replacement("viewport_capture").startswith("look")
    assert migration.replacement("node_find") == "search kind: nodes"
    assert migration.replacement("node_type_search") == "search kind: types"
    assert migration.replacement("node_connect") == "edit op: connect"
    assert migration.replacement("usd_stage") == "inspect what: stage"
    assert migration.hint("cook") is None and migration.replacement("inspect") is None
    # selection's read names houdini_python only where the profile serves it.
    assert "houdini_python" in migration.hint("selection", "core")
    assert "houdini_python" not in migration.hint("selection", "minimal")


def test_removed_profile_names_read_as_full_with_a_warning() -> None:
    """BIBLE D46: compat_1x and v2 are not profiles any more; the config readers turn them
    into full and say why. Any other unknown name is no profile at all."""
    assert catalog.normalize(" Full ") == "full" and catalog.normalize("") == "core"
    for raw in ("compat_1x", " COMPAT_1X ", "v2", "V2"):
        assert catalog.normalize(raw) is None, raw
        resolved, warning = profiles.resolve(raw)
        name = raw.strip().lower()
        assert resolved == "full", raw
        assert f'profile = "{name}"' in warning and "removed in HocusPocus 2.1" in warning
        assert 'using "full"' in warning and "docs/migration-2.0.md" in warning
    assert profiles.resolve("core") == ("core", None)
    assert profiles.resolve("v3") == (None, None)
    assert profiles.removed_warning("full") is None


# -- the bridge -------------------------------------------------------------------------------


def test_bridge_profile_default_removed_names_and_toml(tmp_path, monkeypatch, caplog) -> None:
    from hocuspocus.bridge import config as bc

    assert BridgeConfig().profile == "core" and BridgeConfig().profile_warning == ""
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
    with caplog.at_level(logging.WARNING, logger="hocuspocus.bridge.config"):
        config = BridgeConfig.load(env)
    assert config.profile == "full" and "compat_1x" in config.profile_warning
    assert any("compat_1x" in r.getMessage() for r in caplog.records)  # logged, too
    toml.write_text('profile = "v2"\n', encoding="utf-8")
    config = BridgeConfig.load(env)
    assert config.profile == "full" and '"v2"' in config.profile_warning
    assert BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "V2"}).profile == "full"
    minimal = BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "minimal"})
    assert minimal.profile == "minimal" and minimal.profile_warning == ""
    unknown = BridgeConfig.load({**env, "HOCUSPOCUS_PROFILE": "v3"})
    assert unknown.profile == "core" and unknown.profile_warning == ""


def test_bridge_lists_its_profile_and_reports_it() -> None:
    from hocuspocus.bridge.local_tools import LOCAL_TOOLS
    from hocuspocus.bridge.server import Bridge

    for profile in ("minimal", "core", "full"):
        bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
        assert bridge.tools == for_profile(profile)
        status = LOCAL_TOOLS["houdini_status"](bridge, {})
        assert status["profile"] == profile and "compat_1x" not in status
        assert not any("removed in HocusPocus 2.1" in w for w in status.get("warnings", []))
        assert status["profile"] in _status_profile_enum(bridge.tools)
    for removed in ("compat_1x", "v2"):
        # A config built by hand (not through load) is resolved by the bridge itself.
        bridge = Bridge(BridgeConfig(profile=removed), scan=lambda: [])
        assert bridge.config.profile == "full" and bridge.tools == for_profile("full")
        assert [tool.name for tool in bridge.list_tools()] == _names("full")
        status = LOCAL_TOOLS["houdini_status"](bridge, {})
        assert status["profile"] == "full" and "compat_1x" not in status
        warning = next(w for w in status["warnings"] if "removed in HocusPocus 2.1" in w)
        assert f'profile = "{removed}"' in warning and 'using "full"' in warning


def _text(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("profile", ["minimal", "core", "full", "compat_1x"])
def test_a_bridge_answers_a_removed_tool_with_its_replacement(profile) -> None:
    from mcp.shared.exceptions import MCPError

    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
    served = bridge.config.profile  # compat_1x reads as full
    for name in sorted(REMOVED):
        result = bridge.call_tool(name, {"paths": ["/obj"]})
        assert result.is_error, name
        error = _text(result)
        assert error["code"] == "invalid_argument", name
        assert error["message"] == f"{name} is a 1.4 tool; HocusPocus 2.1 removed it."
        assert error["hint"] == migration.hint(name, served)
        assert error["detail"]["replacement"] == migration.REPLACEMENTS[name]
    with pytest.raises(MCPError):  # any other unknown name is still a protocol error
        bridge.call_tool("node_infos", {})


def test_a_bridge_sends_its_profile_to_the_host(monkeypatch) -> None:
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
    for profile, expected in (("minimal", "minimal"), ("core", "core"), ("compat_1x", "full")):
        bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [inst])
        client = bridge.client_for(inst)
        assert client.profile == expected
        client.call("inspect", {"what": "node", "target": "/obj"}, 5.0)
        assert sent[-1]["profile"] == expected and sent[-1]["tool"] == "inspect"


# -- the host ---------------------------------------------------------------------------------


def test_host_config_reads_a_removed_profile_as_full(tmp_path, caplog) -> None:
    assert HostConfig().profile == "core"
    (tmp_path / "hocuspocus.toml").write_text('profile = "compat_1x"\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="hocuspocus.host.config"):
        assert load_config(pref_dir=str(tmp_path), environ={}).profile == "full"
    warned = [r.getMessage() for r in caplog.records if "compat_1x" in r.getMessage()]
    assert warned and "removed in HocusPocus 2.1" in warned[0]
    assert str(tmp_path / "hocuspocus.toml") in warned[0]  # names the file it came from
    assert load_config(environ={"HOCUSPOCUS_PROFILE": "v2"}).profile == "full"
    assert HostConfig().with_overrides(profile="v2").profile == "full"
    assert HostConfig().with_overrides(profile="v3").profile == "core"  # logged, ignored


def test_host_refusals_name_the_profile() -> None:
    pdg, cook = get("pdg"), get("cook")
    error = profile_error(pdg, "core")
    assert error.message == (
        "pdg is a full-profile tool, and this Houdini's host runs the core profile."
    )
    assert 'profile = "full" in hocuspocus.toml' in error.hint
    assert "HOCUSPOCUS_PROFILE=full" in error.hint and '(or "full")' not in error.hint
    assert 'profile = "core" (or "full")' in profile_error(cook, "minimal").hint
    assert profile_error(pdg, "full") is None
    assert profile_error(get("edit"), "minimal") is None


@dataclass
class _Impl:
    spec: ToolSpec | None
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


def test_the_dispatcher_refuses_a_removed_tool_whatever_the_request_profile() -> None:
    """A 2.0.x compat_1x bridge sent profile: compat_1x to widen the host's profile; since
    2.1 nothing widens it, and a removed name is refused before any lookup."""
    for profile in ("minimal", "core", "full"):
        dispatcher = Dispatcher(_Ctx(profile), lambda name: _Impl(None, name=name))
        for envelope in (None, "compat_1x", "full", "bogus"):
            refused = dispatcher.call("geo_read", {}, profile=envelope)
            assert refused["ok"] is False, (profile, envelope)
            assert refused["error"]["code"] == "invalid_argument"
            assert "inspect what: geo" in refused["error"]["hint"]
        assert dispatcher.call("probe", {})["ok"] is True  # anything else is looked up


# -- the 2.0 tools through the bridge -------------------------------------------------------


class _Host:
    """A fake host answering ``inspect`` the way the real one does for events and jobs."""

    def __init__(self, inst: Any) -> None:
        self.inst = inst
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": self.inst.pid, "houdini": "22.0.466",
                "generation": 1, "host_version": "2.0.0"}  # fmt: skip

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
