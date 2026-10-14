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
