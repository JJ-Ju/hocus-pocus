"""Linux and macOS paths and process launch, with ``sys.platform`` faked where the code
reads it (docs/redesign/review/27-portability.md). Nothing is launched and no real pref
dir or state dir is touched: every location is under ``tmp_path``."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from hocuspocus import cli
from hocuspocus.bridge import config as bridge_config
from hocuspocus.bridge import launch
from hocuspocus.tools import paths

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOUDINI_USER_PREF_DIR", raising=False)
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: None)


# -- state dir ---------------------------------------------------------------------------


def test_state_dir_per_platform(tmp_path, monkeypatch):
    monkeypatch.delenv("HOCUSPOCUS_STATE_DIR")
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert paths.state_dir() == tmp_path / "home" / ".local" / "state" / "hocuspocus"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert paths.state_dir() == tmp_path / "xdg" / "hocuspocus"
    monkeypatch.setattr(paths.sys, "platform", "darwin")  # macOS follows XDG too (BIBLE §3.2)
    assert paths.state_dir() == tmp_path / "xdg" / "hocuspocus"
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.state_dir() == tmp_path / "local" / "HocusPocus"
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "override"))
    assert paths.state_dir() == tmp_path / "override"


def test_private_dir_is_chmod_0700_off_windows(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths.os, "chmod", lambda path, mode: calls.append((Path(path), mode)))
    target = paths.ensure_private_dir(tmp_path / "a" / "instances")
    assert target.is_dir()
    assert calls == [(tmp_path / "a" / "instances", 0o700)]
    calls.clear()
    monkeypatch.setattr(paths.sys, "platform", "win32")  # the per-user profile ACL applies
    paths.ensure_private_dir(tmp_path / "b")
    assert calls == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_private_dir_mode_is_real_on_posix(tmp_path):
    target = paths.ensure_private_dir(tmp_path / "state" / "logs")
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


# -- pref dirs -----------------------------------------------------------------------------


def test_default_pref_dirs_linux_and_macos(tmp_path):
    env = {"HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "ignored")}
    assert bridge_config.default_pref_dirs(env, platform="linux") == [
        tmp_path / "home" / "houdini22.0"
    ]
    assert bridge_config.default_pref_dirs(env, platform="darwin") == [
        tmp_path / "home" / "Library" / "Preferences" / "houdini" / "22.0"
    ]
    # No Documents variant and no %USERPROFILE% off Windows.
    assert bridge_config.default_pref_dirs(env, major_minor="22.5", platform="linux") == [
        tmp_path / "home" / "houdini22.5"
    ]


def test_install_houdini_on_macos_writes_the_library_pref_dir(tmp_path):
    home = tmp_path / "home"
    prefs = home / "Library" / "Preferences" / "houdini" / "22.0"
    prefs.mkdir(parents=True)
    env = {"HOME": str(home)}
    lines: list[str] = []
    rc = cli.install_houdini(None, dev=True, environ=env, platform="darwin", out=lines.append)
    assert rc == 0
    assert (prefs / "packages" / cli.PACKAGE_JSON_NAME).is_file()
    assert not (home / "houdini22.0").exists()
    assert any("from default location" in line for line in lines)


def test_pref_dir_candidates_linux_ask_hython_once_and_expand_hver(tmp_path, monkeypatch):
    """Off Windows there is no second "without HOME" hython query; a macOS-style answer
    (``.../houdini/22.0``) still yields the major.minor for ``__HVER__``."""
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: tmp_path / "hfs")
    asked: list[dict] = []
    answer = tmp_path / "home" / "Library" / "Preferences" / "houdini" / "22.5"

    def query(hfs, env):
        asked.append(dict(env))
        return str(answer)

    env = {"HOME": str(tmp_path / "home"), "HOUDINI_USER_PREF_DIR": str(tmp_path / "p__HVER__")}
    found = cli.pref_dir_candidates(None, environ=env, hython_query=query, platform="darwin")
    assert len(asked) == 1
    assert found[0].path == tmp_path / "p22.5"
    assert found[1].path == answer


# -- Houdini install and launch --------------------------------------------------------------


def test_candidate_install_globs_per_platform(monkeypatch):
    monkeypatch.setattr(launch.sys, "platform", "linux")
    assert launch._candidate_globs() == [("/opt/hfs22.*", "")]
    monkeypatch.setattr(launch.sys, "platform", "darwin")
    assert launch._candidate_globs() == [
        (
            "/Applications/Houdini/Houdini22.*",
            "Frameworks/Houdini.framework/Versions/Current/Resources",
        )
    ]


def _fake_install(hfs: Path, names: tuple[str, ...]) -> Path:
    (hfs / "bin").mkdir(parents=True)
    for name in names:
        (hfs / "bin" / name).write_text("")
    return hfs


def test_detect_hfs_finds_a_macos_framework_install(tmp_path, monkeypatch):
    apps = tmp_path / "Applications" / "Houdini"
    suffix = "Frameworks/Houdini.framework/Versions/Current/Resources"
    for version in ("Houdini22.0.368", "Houdini22.0.466"):
        _fake_install(apps / version / suffix, ("hython", "houdinifx"))
    monkeypatch.setattr(launch, "EXE", "")
    monkeypatch.setattr(launch.sys, "platform", "darwin")
    real_glob = launch.glob.glob
    monkeypatch.setattr(
        launch.glob,
        "glob",
        lambda pattern: real_glob(pattern.replace("/Applications/Houdini", str(apps))),
    )
    hfs = launch.detect_hfs(None, {})
    assert hfs == apps / "Houdini22.0.466" / suffix
    assert launch.hython_path(hfs) == hfs / "bin" / "hython"
    assert launch.gui_executable(hfs) == hfs / "bin" / "houdinifx"


def test_detect_hfs_prefers_the_full_linux_version(tmp_path, monkeypatch):
    """/opt/hfs22.0 is often a link to /opt/hfs22.0.466; the longest version wins."""
    opt = tmp_path / "opt"
    for name in ("hfs22.0", "hfs22.0.466"):
        _fake_install(opt / name, ("hython", "houdini"))
    monkeypatch.setattr(launch, "EXE", "")
    monkeypatch.setattr(launch.sys, "platform", "linux")
    real_glob = launch.glob.glob
    monkeypatch.setattr(
        launch.glob, "glob", lambda pattern: real_glob(pattern.replace("/opt", str(opt)))
    )
    hfs = launch.detect_hfs(None, {})
    assert hfs == opt / "hfs22.0.466"
    assert launch.gui_executable(hfs) == hfs / "bin" / "houdini"  # no houdinifx: Core


def test_posix_spawn_starts_a_new_session_without_windows_flags(tmp_path, monkeypatch):
    seen: dict = {}

    class FakePopen:
        pid = 4242

        def __init__(self, argv, **kwargs):
            seen.update(kwargs, argv=argv)

        def poll(self):
            return None

    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setattr(launch.subprocess, "Popen", FakePopen)
    proc = launch.default_spawner(["hython"], {"A": "1"}, tmp_path, tmp_path / "logs" / "l.log")
    assert seen["start_new_session"] is True
    assert "creationflags" not in seen
    assert seen["stdin"] is launch.subprocess.DEVNULL and seen["close_fds"] is True
    assert proc.hp_breakaway is False
    assert launch.child_outlives_server(proc) is True  # its own session


def test_headless_pythonpath_uses_the_platform_separator(tmp_path, monkeypatch):
    hfs = _fake_install(tmp_path / "hfs", (f"hython{launch.EXE}",))
    launcher = launch.Launcher(
        str(hfs),
        environ={"PYTHONPATH": "existing"},
        python_dir=lambda environ: (tmp_path / "hostpkg", "test"),
    )
    _argv, env, _cwd, _log = launcher.build("headless", None)
    assert env["PYTHONPATH"] == str(tmp_path / "hostpkg") + os.pathsep + "existing"


def test_headless_host_stops_cleanly_on_hangup_where_there_is_one(monkeypatch):
    """A terminal closing sends SIGHUP on Linux and macOS: the host must shut down as for
    SIGTERM (registry entry removed), not die with its entry left behind."""
    import signal

    from hocuspocus.host import __main__ as host_main

    installed: list[int] = []
    monkeypatch.setattr(host_main.signal, "signal", lambda sig, fn: installed.append(sig))
    names = host_main.install_signal_handlers(lambda *_: None)
    assert "SIGHUP" in host_main.SHUTDOWN_SIGNALS
    expected = [n for n in host_main.SHUTDOWN_SIGNALS if hasattr(signal, n)]
    assert names == expected
    assert installed == [getattr(signal, n) for n in expected]
    assert ("SIGHUP" in names) == (sys.platform != "win32")


def test_package_json_paths_are_forward_slashes(tmp_path):
    text, _used = cli.render_package_json(Path("C:\\x\\python"), Path("C:\\x\\houdini"))
    assert "\\\\" not in text
    assert '"C:/x/python"' in text and '"hpath": "C:/x/houdini"' in text
