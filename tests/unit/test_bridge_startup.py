"""Why a GUI launch did not register (D60, bridge/startup.py, host autostart records).

The launcher is driven with a fake spawner, registry, clock and window probe (nothing is
started); the titles are the ones houdinifx 22.0.466 shows (bridge/startup.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_bridge_launch import Harness, fake_hfs, make_launcher

import hocuspocus.host as host
from hocuspocus.bridge import startup
from hocuspocus.tools import paths
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

SPLASH = "houdinifx"
MAIN = "untitled.hip - Houdini Indie Limited-Commercial 22.0.466 - Py3.13"
MESSAGE = "Houdini"  # a hou.ui.displayMessage window


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOCUSPOCUS_WORK_DIR", raising=False)
    monkeypatch.delenv("HOCUSPOCUS_AUTOSTART", raising=False)
    monkeypatch.setenv("HOUDINI_USER_PREF_DIR", str(tmp_path / "prefs" / "houdini22.0"))


def _windows(timeline):
    """A probe answering ``timeline``: ``[(from_poll, titles), ...]``, by poll count."""
    calls = [0]

    def probe(pid):
        calls[0] += 1
        titles: list[str] = []
        for start, shown in timeline:
            if calls[0] >= start:
                titles = shown
        return titles

    return probe


def _record(pid: int, **fields) -> Path:
    directory = paths.startup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{pid}.json"
    path.write_text(json.dumps({"pid": pid, "time": 0, **fields}), encoding="utf-8")
    return path


def _launch(tmp_path, harness, wait_s=90.0, window_probe=None, step=0.5):
    launcher = make_launcher(
        fake_hfs(tmp_path / "hfs"),
        harness,
        clock_step=step,
        gui_probe=lambda pid: None,
        window_probe=window_probe,
    )
    with pytest.raises(ToolError) as info:
        launcher.launch("gui", None, wait_s=wait_s)
    return info.value, launcher.test_clock[0]


def test_a_failed_host_start_ends_the_wait_at_once(tmp_path):
    _record(9001, phase="failed", error="OSError: [WinError 10048] port in use", log="h.log")
    error, waited = _launch(tmp_path, Harness(register=False))
    assert waited <= 1.0
    assert error.code == "houdini_offline" and error.retryable is False
    assert "its HocusPocus host failed to start: OSError: [WinError 10048]" in error.message
    assert "still open" in error.message
    assert error.detail["reason"] == "host_failed" and error.detail["log"] == "h.log"
    assert "h.log" in error.hint


def test_autostart_false_ends_the_wait_at_once(tmp_path):
    _record(9001, phase="disabled")
    error, waited = _launch(tmp_path, Harness(register=False))
    assert waited <= 1.0
    assert error.detail["reason"] == "autostart_disabled"
    assert "autostart = false" in error.message


def test_a_startup_dialog_before_the_main_window_ends_the_wait(tmp_path):
    probe = _windows([(1, [SPLASH]), (5, [MESSAGE])])
    harness = Harness(register=False)
    error, waited = _launch(tmp_path, harness, window_probe=probe)
    assert startup.DIALOG_GRACE_S <= waited < startup.DIALOG_GRACE_S + 5
    assert error.detail["reason"] == "dialog" and error.detail["windows"] == [MESSAGE]
    assert "waiting on a window titled 'Houdini'" in error.message
    assert "ask the user" in error.hint
    assert harness.procs[0].terminated is False  # someone may still answer it


def test_a_licensed_start_never_misfires(tmp_path):
    """Splash for 30 s (a slow start), then the main window, then the host registers."""
    probe = _windows([(1, [SPLASH]), (60, [MAIN, SPLASH]), (61, [MAIN])])
    harness = Harness()
    harness_polls = {"n": 0}
    scan = harness.scan

    def slow_scan():
        harness_polls["n"] += 1
        return scan() if harness_polls["n"] > 62 else []

    harness.scan = slow_scan
    launcher = make_launcher(
        fake_hfs(tmp_path / "hfs"),
        harness,
        clock_step=0.5,
        gui_probe=lambda pid: None,
        window_probe=probe,
    )
    launcher.scan = slow_scan
    assert launcher.launch("gui", None, wait_s=90).instance.pid == 9001


def test_a_dialog_with_the_main_window_up_is_named_only_at_the_deadline(tmp_path):
    probe = _windows([(1, [SPLASH]), (3, [MAIN]), (5, [MAIN, "Load Warnings"])])
    error, waited = _launch(tmp_path, Harness(register=False), wait_s=30, window_probe=probe)
    assert waited >= 30
    assert error.detail["reason"] == "dialog"
    assert "did not register within 30s" in error.message
    assert "'Load Warnings'" in error.message


def test_the_main_window_without_an_autostart_names_the_package(tmp_path):
    probe = _windows([(1, [SPLASH]), (3, [MAIN])])
    error, _ = _launch(tmp_path, Harness(register=False), wait_s=20, window_probe=probe)
    assert error.detail["reason"] == "no_autostart"
    assert "never ran its autostart (uiready.py)" in error.message
    assert "install-houdini" in error.hint


def test_a_host_that_began_starting_names_its_log(tmp_path):
    _record(9001, phase="starting", log="C:/state/logs/host-9001.log")
    error, _ = _launch(tmp_path, Harness(register=False), wait_s=10)
    assert error.detail["reason"] == "host_starting"
    assert "began starting and has not finished" in error.message
    assert "host-9001.log" in error.hint


def test_without_windows_the_timeout_reads_as_before(tmp_path):
    error, _ = _launch(tmp_path, Harness(register=False), wait_s=5)
    assert "did not register within 5s" in error.message
    assert "It may still be starting" in error.message
    assert "licence" in error.hint


def test_another_pids_record_is_not_read(tmp_path):
    _record(4242, phase="failed", error="not mine")
    error, waited = _launch(tmp_path, Harness(register=False), wait_s=5)
    assert waited >= 5 and "not mine" not in error.message


def test_headless_launches_read_no_record(tmp_path):
    _record(9001, phase="failed", error="ignored")
    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), Harness())
    assert launcher.launch("headless", None, wait_s=30).instance.pid == 9001


def test_the_record_lives_under_the_launch_environments_state_dir(tmp_path):
    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), Harness())
    launcher.environ = {"HOCUSPOCUS_STATE_DIR": str(tmp_path / "other")}
    assert launcher.startup_records() == tmp_path / "other" / "startup"


def test_classify_keeps_the_splash_apart_from_a_message_window():
    assert startup.classify([SPLASH], "houdinifx") == (None, [])
    assert startup.classify([MESSAGE], "houdinifx") == (None, [MESSAGE])
    assert startup.classify([MAIN, SPLASH], "houdinifx") == (MAIN, [])
    assert startup.classify(["untitled.hip - Houdini FX 22.0.466"], "houdinifx")[0]


# -- the host side: hocuspocus.host.autostart --------------------------------------------


def test_autostart_records_a_failed_start(monkeypatch):
    monkeypatch.setattr(host, "start", lambda config: {"running": False, "error": "boom"})
    host.autostart()
    record = json.loads((paths.startup_dir() / f"{_pid()}.json").read_text(encoding="utf-8"))
    assert record["phase"] == "failed" and record["error"] == "boom"
    assert record["log"].endswith(f"host-{_pid()}.log")


def test_autostart_deletes_the_record_once_the_host_runs(monkeypatch):
    seen = []

    def start(config):
        seen.append(json.loads((paths.startup_dir() / f"{_pid()}.json").read_text()))
        return {"running": True}

    monkeypatch.setattr(host, "start", start)
    host.autostart()
    assert seen[0]["phase"] == "starting"
    assert not (paths.startup_dir() / f"{_pid()}.json").exists()


def test_autostart_false_is_recorded(monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_AUTOSTART", "false")
    monkeypatch.setattr(host, "start", lambda config: pytest.fail("must not start"))
    host.autostart()
    record = json.loads((paths.startup_dir() / f"{_pid()}.json").read_text(encoding="utf-8"))
    assert record["phase"] == "disabled"


def test_autostart_prunes_the_records_of_exited_houdinis(monkeypatch):
    stale = _record(999_999_99, phase="failed", error="old")
    monkeypatch.setattr(host, "start", lambda config: {"running": True})
    host.autostart()
    assert not stale.exists()


def _pid() -> int:
    import os

    return os.getpid()
