"""The bridge compares the host's ``host_version`` with its own on attach and launch
(docs/parity.md G7): a GUI Houdini runs the host its package points at, which can be
older than the bridge. A different ``host_version`` is a warning; a different ``hp`` RPC
version stays the ``version_mismatch`` error. Fake hosts, no Houdini."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hocuspocus.bridge import local_tools, resources
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.launch import LaunchResult
from hocuspocus.bridge.server import Bridge
from hocuspocus.version import __version__

pytestmark = pytest.mark.unit

OLD = "1.3.0"
assert __version__ != OLD

GUI = Instance(pid=4100, port=52100, token="t", houdini="22.0.466", ui=True, label="houdinifx")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


class Host:
    def __init__(self, host_version: str, hp: int = 1) -> None:
        self.host_version = host_version
        self.hp = hp

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        if self.hp != 1:  # what HostClient.health raises for another hp
            from hocuspocus.tools.errors import ToolError

            raise ToolError(
                "version_mismatch",
                f"The Houdini host speaks hp/v{self.hp}; this bridge speaks hp/v1.",
                detail={"host_hp": self.hp, "bridge_hp": 1},
            )
        return {
            "ok": True,
            "hp": 1,
            "pid": GUI.pid,
            "houdini": "22.0.466",
            "generation": 1,
            "host_version": self.host_version,
            "busy": False,
            "jobs_running": 0,
        }

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        if tool == "houdini_status":
            return True, {"hip": {"path": "C:/x.hip"}, "host_version": self.host_version}, {}
        return True, {"echo": tool}, {}


class Launcher:
    def launch(self, mode: str, hip: Any = None, wait_s: float = 90.0) -> LaunchResult:
        return LaunchResult(instance=GUI, mode=mode, argv=("houdinifx",), log=None)


def _bridge(host: Host) -> Bridge:
    return Bridge(
        BridgeConfig(profile="core"),
        client_factory=lambda port, token: host,
        scan=lambda: [GUI],
        launcher=Launcher(),  # type: ignore[arg-type]
    )


def _out(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def test_version_warning_only_for_a_different_host_version() -> None:
    assert local_tools.version_warning(__version__) is None
    assert local_tools.version_warning(None) is None
    assert local_tools.version_warning("") is None
    warning = local_tools.version_warning(OLD)
    assert warning and warning.startswith("version_mismatch:")
    assert OLD in warning and __version__ in warning
    assert "install-houdini" in warning


@pytest.mark.parametrize("args", [{"pid": GUI.pid}, {}, {"launch": {"mode": "gui"}}])
def test_connect_warns_on_an_older_host(args) -> None:
    result = _bridge(Host(OLD)).call_tool("houdini_connect", args)
    out = _out(result)
    assert result.is_error is False, out
    assert out["connected"]["host_version"] == OLD
    assert any(w.startswith("version_mismatch:") for w in out["warnings"]), out


@pytest.mark.parametrize("args", [{"pid": GUI.pid}, {"launch": {"mode": "gui"}}])
def test_connect_is_quiet_on_a_matching_host(args) -> None:
    out = _out(_bridge(Host(__version__)).call_tool("houdini_connect", args))
    # A host_version equal to the bridge's is left out (2.1, D66).
    assert "host_version" not in out["connected"]
    assert not any("version_mismatch" in w for w in out.get("warnings", []))


def test_another_hp_is_an_error_not_a_warning() -> None:
    result = _bridge(Host(OLD, hp=2)).call_tool("houdini_connect", {"pid": GUI.pid})
    out = _out(result)
    assert result.is_error is True
    assert out["code"] == "version_mismatch"


def test_status_rows_carry_host_version_and_warn() -> None:
    status = _out(_bridge(Host(OLD)).call_tool("houdini_status", {}))
    # The connected row leaves host_version to connected (2.1, D66) ...
    assert status["connected"]["host_version"] == OLD
    assert "host_version" not in status["instances"][0]
    assert any(w.startswith("version_mismatch:") for w in status["warnings"])
    whole = _bridge(Host(OLD))
    rows = json.loads(resources.read(whole, "houdini://instances").contents[0].text)
    assert rows["instances"][0]["host_version"] == OLD  # ... houdini://instances keeps it
    matched = _out(_bridge(Host(__version__)).call_tool("houdini_status", {}))
    # ... and one equal to the bridge's is left out everywhere.
    assert "host_version" not in matched["connected"]
    assert "host_version" not in matched["instances"][0]
    assert not any("version_mismatch" in w for w in matched.get("warnings", []))
