"""``hocuspocus`` CLI. Every test passes ``--prefs <tmp>``: never touch the real pref dir."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hocuspocus import cli
from hocuspocus.version import __version__

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_houdini(tmp_path, monkeypatch):
    """No HFS, isolated state dir, no inherited pref dir."""
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOUDINI_USER_PREF_DIR", raising=False)
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: None)


def test_install_dev_writes_valid_package_json(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    assert cli.main(["install-houdini", "--prefs", str(prefs), "--dev"]) == 0
    target = prefs / "packages" / "hocuspocus.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    python_dir = cli.package_python_dir(data)
    assert python_dir is not None
    assert (python_dir / "hocuspocus" / "bridge").is_dir()
    assert python_dir.resolve() == cli.checkout_root().resolve() / "src"
    out = capsys.readouterr().out
    assert "Restart Houdini" in out and str(target) in out
    assert not (prefs / "hocuspocus").exists()  # --dev copies nothing


def test_install_copies_package_and_is_idempotent(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    stale = prefs / "hocuspocus" / "0.9.0"
    stale.mkdir(parents=True)
    for _ in range(2):
        assert cli.main(["install-houdini", "--prefs", str(prefs)]) == 0
    copied = prefs / "hocuspocus" / __version__ / "python" / "hocuspocus"
    assert (copied / "host").is_dir() and (copied / "tools" / "catalog.py").is_file()
    assert not list(copied.rglob("__pycache__"))
    assert not stale.exists()
    data = json.loads((prefs / "packages" / "hocuspocus.json").read_text(encoding="utf-8"))
    assert cli.package_python_dir(data) == Path(str(copied.parent).replace("\\", "/"))
    env = {k: v for entry in data["env"] for k, v in entry.items()}
    assert env["HOCUSPOCUS_VERSION"] == __version__


def test_inline_template_has_hpath_when_payload(tmp_path):
    text, used = cli.render_package_json(tmp_path / "py", tmp_path / "payload", template=None)
    data = json.loads(text)
    assert used == "inline"
    assert data["hpath"].endswith("/payload")
    assert data["env"][1]["PYTHONPATH"]["method"] == "prepend"
    assert "\\" not in text


def test_template_file_is_rendered(tmp_path):
    tpl = tmp_path / "hocuspocus.json.template"
    tpl.write_text(
        '{"load_package_once": true, "env": [{"PYTHONPATH": {"value": "{{PYTHON_DIR}}", "method": "prepend"}},'
        ' {"OTHER": "$HFS"}], "hpath": "{{PAYLOAD_DIR}}"}'
    )
    text, used = cli.render_package_json(tmp_path / "py", tmp_path / "pl", template=tpl)
    data = json.loads(text)
    assert used == str(tpl)
    assert data["env"][0] == {"HOCUSPOCUS_VERSION": __version__}
    assert data["env"][1]["PYTHONPATH"]["value"].endswith("/py")
    assert {"OTHER": "$HFS"} in data["env"]
    assert data["hpath"].endswith("/pl") and data["load_package_once"] is True


def test_real_template_renders(tmp_path):
    tpl = cli.template_source()
    if tpl is None:
        pytest.skip("houdini/hocuspocus.json.template not present")
    text, used = cli.render_package_json(tmp_path / "py", tmp_path / "pl", template=tpl)
    assert used == str(tpl)
    assert "{{" not in text
    assert cli.package_python_dir(json.loads(text)) == tmp_path / "py"


def test_broken_template_falls_back_to_inline(tmp_path):
    tpl = tmp_path / "hocuspocus.json.template"
    tpl.write_text("{not json")
    _text, used = cli.render_package_json(tmp_path / "py", None, template=tpl)
    assert used == "inline"


def test_uninstall(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    cli.main(["install-houdini", "--prefs", str(prefs)])
    assert cli.main(["uninstall-houdini", "--prefs", str(prefs)]) == 0
    assert not (prefs / "packages" / "hocuspocus.json").exists()
    assert not (prefs / "hocuspocus").exists()
    assert cli.main(["uninstall-houdini", "--prefs", str(prefs)]) == 0
    assert "nothing to remove" in capsys.readouterr().out


def test_pref_dir_resolution_order(tmp_path, monkeypatch):
    env = {"HOUDINI_USER_PREF_DIR": str(tmp_path / "from_env")}
    assert cli.resolve_pref_dir(str(tmp_path / "flag"), environ=env).source == "--prefs"
    assert cli.resolve_pref_dir(None, environ=env).path == tmp_path / "from_env"
    # __HVER__ placeholders are not a usable path
    assert (
        cli.resolve_pref_dir(None, environ={"HOUDINI_USER_PREF_DIR": "x/houdini__HVER__"}).source
        != "HOUDINI_USER_PREF_DIR"
    )
    # hython is asked before the platform default
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: tmp_path / "hfs")
    asked = cli.resolve_pref_dir(
        None, environ={}, hython_query=lambda hfs: str(tmp_path / "houdini22.0")
    )
    assert asked.path == tmp_path / "houdini22.0" and asked.source.startswith("hython")
    fallback = cli.resolve_pref_dir(
        None, environ={"USERPROFILE": str(tmp_path)}, hython_query=lambda hfs: None
    )
    assert fallback.source == "platform default"


def test_platform_default_matches_the_bridge_order(tmp_path, monkeypatch):
    """install-houdini and the bridge probe the same default pref dirs, in the same order."""
    from hocuspocus.bridge.config import default_pref_dirs

    env = {"USERPROFILE": str(tmp_path)}
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    first, *rest = default_pref_dirs(env)
    assert cli.platform_default_pref_dir(env) == first  # nothing exists: the first one
    for later in rest:
        later.mkdir(parents=True)
        assert cli.platform_default_pref_dir(env) == later  # the first that exists
    first.mkdir(parents=True)
    assert cli.platform_default_pref_dir(env) == first


def test_install_prints_the_user_scope_snippet(tmp_path, capsys):
    assert cli.main(["install-houdini", "--prefs", str(tmp_path / "prefs")]) == 0
    assert "claude mcp add -s user hocuspocus -- hocuspocus-mcp" in capsys.readouterr().out


def test_doctor_with_no_houdini(tmp_path, capsys):
    rc = cli.main(["doctor", "--prefs", str(tmp_path / "prefs")])
    out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL] Houdini install" in out
    assert "[FAIL] package JSON" in out
    assert "[warn] live instances" in out
    assert "claude mcp add -s user hocuspocus -- hocuspocus-mcp" in out
    assert "[mcp_servers.hocuspocus]" in out


def test_doctor_after_install_checks_package(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    cli.main(["install-houdini", "--prefs", str(prefs)])
    capsys.readouterr()
    cli.main(["doctor", "--prefs", str(prefs)])
    out = capsys.readouterr().out
    assert "[ok]   package JSON" in out
    assert f"[ok]   host/bridge version: {__version__}" in out


def test_client_config(capsys):
    assert cli.main(["client-config", "claude"]) == 0
    assert "claude mcp add -s user hocuspocus -- hocuspocus-mcp" in capsys.readouterr().out
    assert cli.main(["client-config", "codex"]) == 0
    assert 'command = "hocuspocus-mcp"' in capsys.readouterr().out


def test_version(capsys):
    assert cli.main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_docs_tools_to_file(tmp_path, capsys):
    target = tmp_path / "tools.md"
    rc = cli.main(["docs", "tools", "--output", str(target)])
    out = capsys.readouterr().out
    if rc == 1:
        assert "not available" in out
    else:
        assert target.read_text(encoding="utf-8").strip()


# -- hocuspocus launch -------------------------------------------------------------------


class _Proc:
    pid = 9001

    def poll(self):
        return None


def _fake_launcher(tmp_path, *, register=True):
    from hocuspocus.bridge import launch
    from hocuspocus.bridge.instances import Instance

    hfs = tmp_path / "hfs"
    (hfs / "bin").mkdir(parents=True)
    (hfs / "bin" / f"hython{launch.EXE}").write_text("")
    (hfs / "bin" / f"houdinifx{launch.EXE}").write_text("")
    spawned = []
    live = []

    def spawner(argv, env, cwd, log_path):
        spawned.append((argv, env))
        if register:
            live.append(
                Instance(pid=9001, port=52000, token="secret", started="2026-10-12T12:00:00Z")
            )
        return _Proc()

    t = [0.0]
    launcher = launch.Launcher(
        str(hfs),
        spawner=spawner,
        scan=lambda: list(live),
        sleep=lambda s: t.__setitem__(0, t[0] + 1),
        clock=lambda: t[0],
        environ={},
        python_dir=lambda environ: (tmp_path / "pkg", "test"),
        owned=False,
    )
    return launcher, spawned


def test_launch_prints_the_registry_entry(tmp_path, monkeypatch, capsys):
    launcher, spawned = _fake_launcher(tmp_path)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--headless", "--wait", "30"]) == 0
    captured = capsys.readouterr()
    entry = json.loads(captured.out)
    assert entry["pid"] == 9001 and entry["port"] == 52000 and entry["mode"] == "headless"
    assert "token" not in entry and "secret" not in captured.out
    assert "houdini_connect" in captured.err
    argv, env = spawned[0]
    assert argv[1:3] == ["-m", "hocuspocus.host"]
    assert "HOCUSPOCUS_LAUNCHED_BY" not in env  # no MCP server owns it


def test_launch_gui_with_hip(tmp_path, monkeypatch, capsys):
    hip = tmp_path / "shot.hip"
    hip.write_text("")
    launcher, spawned = _fake_launcher(tmp_path)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--hip", str(hip)]) == 0
    argv, _env = spawned[0]
    assert Path(argv[0]).stem == "houdinifx" and argv[1] == str(hip.resolve())
    assert json.loads(capsys.readouterr().out)["mode"] == "gui"


def test_launch_wait_zero_returns_at_once(tmp_path, monkeypatch, capsys):
    launcher, _spawned = _fake_launcher(tmp_path, register=False)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--headless", "--wait", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["pid"] == 9001


def test_launch_failure_exits_1_with_hint(tmp_path, monkeypatch, capsys):
    launcher, _spawned = _fake_launcher(tmp_path, register=False)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--headless", "--wait", "3"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "did not register within 3s" in captured.err and "hint:" in captured.err
