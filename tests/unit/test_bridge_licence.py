"""Licence detection and the doctor's licence line, on real Houdini 22.0.466 output
(``fixtures/licence``). Nothing here runs a SideFX tool: runners are injected."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from hocuspocus.bridge import licence

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "licence"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_log_excerpt_reads_hythons_refusal():
    excerpt = licence.log_excerpt(fixture("hython-no-licence.log"))
    assert excerpt == (
        "No licenses could be found to run this application. "
        "Please check for a valid license server host"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Unable to Acquire a License\n",
        "warning: something\r\nNo licences could be found for houdinifx\r\n",
        "Your license has expired.\n",
    ],
)
def test_log_excerpt_other_licence_wordings(text):
    assert licence.log_excerpt(text)


@pytest.mark.parametrize(
    "text", ["", "Traceback (most recent call last):\nImportError: no hou\n", "licensed under MIT"]
)
def test_log_excerpt_ignores_other_failures(text):
    assert licence.log_excerpt(text) is None


def test_read_log_tail_is_lenient(tmp_path):
    assert licence.read_log_tail(None) == ""
    assert licence.read_log_tail(tmp_path / "missing.log") == ""
    log = tmp_path / "a.log"
    log.write_bytes(b"x" * 10_000 + b"\xffNo licenses could be found to run this application.\n")
    tail = licence.read_log_tail(log)
    assert len(tail) <= licence.LOG_TAIL_BYTES and licence.log_excerpt(tail)


def test_launch_error_shape():
    error = licence.launch_error(
        pid=5, mode="headless", argv=["hython"], log="l.log", exit_code=3, excerpt="No licenses"
    )
    data = error.to_dict()
    assert data["code"] == "houdini_offline" and data["retryable"] is False
    assert data["message"] == 'Houdini (pid 5) could not get a licence: "No licenses".'
    assert data["detail"] == {
        "reason": "licence",
        "pid": 5,
        "mode": "headless",
        "exit_code": 3,
        "log_excerpt": "No licenses",
        "log": "l.log",
        "argv": ["hython"],
    }


def test_parse_sesictrl_diagnostic_logged_out():
    state = licence.LicenceState()
    licence.parse_sesictrl_diagnostic(fixture("sesictrl-diagnostic-logged-out.txt"), state)
    assert state.logged_in is False
    assert state.login_based is False
    assert state.installed == 0
    assert state.license_server == "http://localhost:1715 (HOSTNAME)"
    assert state.connected_to == "https://www.sidefx.com/license/sesinetd"
    assert state.used == "None"


def test_parse_hserver():
    state = licence.LicenceState()
    licence.parse_hserver(fixture("hserver-l.txt"), state)
    assert state.connected_to == "https://www.sidefx.com/license/sesinetd"
    assert state.used == "None"


def test_installed_licences_are_counted():
    text = fixture("sesictrl-diagnostic-logged-out.txt").replace(
        "Installed licenses:\n===================\n\n",
        "Installed licenses:\n===================\n"
        "  1 Houdini-FX 22.0 ... (example line)\n  2 Render 22.0 ... (example line)\n",
    )
    state = licence.LicenceState()
    licence.parse_sesictrl_diagnostic(text, state)
    assert state.installed == 2
    assert licence.verdict(_answered(state))[0] == "ok"


def _answered(state: licence.LicenceState) -> licence.LicenceState:
    state.tools = ["sesictrl"]
    return state


def _fake_hfs(tmp_path: Path, *names: str) -> Path:
    exe = ".exe" if sys.platform == "win32" else ""
    (tmp_path / "bin").mkdir(parents=True)
    for name in names:
        (tmp_path / "bin" / f"{name}{exe}").write_text("")
    return tmp_path


def test_licence_state_runs_the_tools_next_to_the_install(tmp_path):
    hfs = _fake_hfs(tmp_path, "sesictrl", "hserver")
    asked = []

    def runner(argv):
        asked.append([Path(argv[0]).stem, *argv[1:]])
        return fixture("sesictrl-diagnostic-logged-out.txt")

    state = licence.licence_state(hfs, runner)
    assert asked == [["sesictrl", "diagnostic"]]  # the diagnostic embeds hserver -l
    assert state.tools == ["sesictrl"] and state.logged_in is False
    level, text = licence.verdict(state)
    assert level == "warn"
    assert "not signed in to SideFX" in text and "no installed licences" in text
    assert "hkey" in text and "sesictrl login" in text and "install-houdini" not in text


def test_licence_state_falls_back_to_hserver(tmp_path):
    hfs = _fake_hfs(tmp_path, "sesictrl", "hserver")

    def runner(argv):
        return fixture("hserver-l.txt") if Path(argv[0]).stem == "hserver" else None

    state = licence.licence_state(hfs, runner)
    assert state.tools == ["hserver"]
    assert state.connected_to == "https://www.sidefx.com/license/sesinetd"
    assert licence.verdict(state)[0] == "warn"  # sidefx.com and nothing says signed in


def test_missing_tools_are_info_not_failure(tmp_path):
    hfs = _fake_hfs(tmp_path)
    state = licence.licence_state(hfs, lambda argv: pytest.fail("must not run"))
    assert state.tools == []
    assert licence.verdict(state)[0] == "info"


def test_signed_in_is_ok():
    text = fixture("sesictrl-diagnostic-logged-out.txt").replace(
        "Logged In:                                   No",
        "Logged In:                                   Yes",
    )
    state = licence.LicenceState()
    licence.parse_sesictrl_diagnostic(text, state)
    assert licence.verdict(_answered(state)) == (
        "ok",
        "signed in to SideFX (login-based licensing) (via sesictrl)",
    )


def test_a_studio_licence_server_is_info():
    text = fixture("hserver-l.txt").replace(
        "Connected To:\thttps://www.sidefx.com/license/sesinetd", "Connected To:\tlicserver01"
    )
    state = licence.LicenceState(tools=["hserver"])
    licence.parse_hserver(text, state)
    level, line = licence.verdict(state)
    assert level == "info" and "licserver01" in line


def test_gui_signal_never_raises_for_a_pid_that_is_not_running():
    assert licence.gui_signal(2**31 - 7) is None


def test_gui_signal_survives_a_broken_platform_probe(monkeypatch):
    def boom(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(licence, "_win_window_title", boom)
    monkeypatch.setattr(licence, "_win_child", boom)
    monkeypatch.setattr(licence, "_posix_child", boom)
    assert licence.gui_signal(os.getpid()) is None


# -- doctor and hocuspocus launch ------------------------------------------------------


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from hocuspocus import cli

    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOUDINI_USER_PREF_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fakehome"))
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path / "fakehome"))
    hfs = _fake_hfs(tmp_path / "Houdini 22.0.466", "sesictrl")
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: hfs)
    return cli, hfs


def test_doctor_reports_a_missing_licence_as_a_warning(isolated, tmp_path, monkeypatch, capsys):
    cli, hfs = isolated

    def run_hython(hfs, code, timeout_s, *, environ=None, failure=None):
        if failure is not None:
            failure.append(fixture("hython-no-licence.log"))
        return None

    monkeypatch.setattr(cli, "run_hython", run_hython)
    monkeypatch.setattr(
        cli,
        "licence_state",
        lambda h: licence.licence_state(
            h, lambda argv: fixture("sesictrl-diagnostic-logged-out.txt")
        ),
    )
    cli.main(["doctor", "--prefs", str(tmp_path / "prefs")])
    out = capsys.readouterr().out
    version = next(x for x in out.splitlines() if "Houdini version" in x)
    assert version.startswith("[warn]") and "could not get a licence" in version
    assert "No licenses could be found" in version
    line = next(x for x in out.splitlines() if x.split("]", 1)[-1].strip().startswith("licence"))
    assert line.startswith("[warn]") and "not signed in to SideFX" in line
    assert "[FAIL] licence" not in out


def test_doctor_without_licence_tools_does_not_fail(isolated, tmp_path, monkeypatch, capsys):
    cli, _hfs = isolated
    monkeypatch.setattr(cli, "run_hython", lambda *a, **k: "22.0.466")
    monkeypatch.setattr(cli, "licence_state", lambda h: licence.LicenceState())
    cli.main(["doctor", "--prefs", str(tmp_path / "prefs")])
    out = capsys.readouterr().out
    assert "[--]   licence: sesictrl and hserver were not found" in out


def test_doctor_survives_a_broken_licence_probe(isolated, tmp_path, monkeypatch, capsys):
    cli, _hfs = isolated
    monkeypatch.setattr(cli, "run_hython", lambda *a, **k: "22.0.466")

    def boom(h):
        raise RuntimeError("parse error")

    monkeypatch.setattr(cli, "licence_state", boom)
    cli.main(["doctor", "--prefs", str(tmp_path / "prefs")])
    assert "[--]   licence: not checked (parse error)" in capsys.readouterr().out


def test_hocuspocus_launch_fails_with_the_licence_message(isolated, tmp_path, monkeypatch, capsys):
    cli, hfs = isolated
    from hocuspocus.bridge import launch

    class Proc:
        pid = 31337

        def poll(self):
            return 3

    def spawner(argv, env, cwd, log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes((FIXTURES / "hython-no-licence.log").read_bytes())
        return Proc()

    launcher = launch.Launcher(
        str(hfs.parent / "hfs-unused"),
        spawner=spawner,
        scan=lambda: [],
        sleep=lambda s: None,
        environ={"HOCUSPOCUS_HFS": str(hfs)},
        python_dir=lambda environ: (tmp_path / "pkg", "test"),
        owned=False,
        gui_probe=None,
    )
    (hfs / "bin" / f"hython{launch.EXE}").write_text("")
    monkeypatch.setattr(cli, "_launcher", lambda h: launcher)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["launch", "--headless", "--wait", "30"]) == 1
    err = capsys.readouterr().err
    assert "error: Houdini (pid 31337) could not get a licence" in err
    assert "No licenses could be found to run this application." in err
    assert "hint: sign in to SideFX in the License Administrator (hkey)" in err
    assert "install-houdini" not in err
