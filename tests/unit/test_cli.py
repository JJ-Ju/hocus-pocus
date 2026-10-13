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
    """No HFS, isolated state dir, no inherited pref dir, and a fake home: install-houdini
    also writes into every existing default pref dir, which must never be the real one."""
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOUDINI_USER_PREF_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fakehome"))
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path / "fakehome"))
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
    # Houdini expands __HVER__; so does install-houdini
    hver = cli.resolve_pref_dir(None, environ={"HOUDINI_USER_PREF_DIR": "x/houdini__HVER__"})
    assert hver.source == "HOUDINI_USER_PREF_DIR" and hver.path == Path("x/houdini22.0")
    # hython is asked before the platform default
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: tmp_path / "hfs")
    home = {"USERPROFILE": str(tmp_path / "nohome"), "HOME": str(tmp_path / "nohome")}
    asked = cli.resolve_pref_dir(
        None, environ=home, hython_query=lambda hfs, env: str(tmp_path / "houdini22.0")
    )
    assert asked.path == tmp_path / "houdini22.0" and asked.source.startswith("hython")
    fallback = cli.resolve_pref_dir(None, environ=home, hython_query=lambda hfs, env: None)
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


def test_doctor_warns_about_a_literal_hver_folder(tmp_path, capsys, monkeypatch):
    """Review 13/16: a toml in a literal houdini__HVER__ folder is never read."""
    prefs = tmp_path / "houdini22.0"
    cli.main(["install-houdini", "--prefs", str(prefs)])
    literal = tmp_path / "houdini__HVER__"
    literal.mkdir()
    (literal / "hocuspocus.toml").write_text('profile = "full"')
    monkeypatch.setenv("HOUDINI_USER_PREF_DIR", str(literal))
    capsys.readouterr()
    cli.main(["doctor", "--prefs", str(prefs)])
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if "literal __HVER__ folder" in x)
    assert line.startswith("[warn]") and str(literal) in line and str(prefs) in line
    assert "move hocuspocus.toml there" in line
    assert out.count("literal __HVER__ folder") == 1  # the env path is the same folder
    literal.rename(tmp_path / "elsewhere")
    cli.main(["doctor", "--prefs", str(prefs)])
    assert "literal __HVER__" not in capsys.readouterr().out


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
    cwds = []

    def spawner(argv, env, cwd, log_path):
        spawned.append((argv, env))
        cwds.append(Path(cwd))
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
    launcher.test_cwds = cwds
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


def test_launch_starts_houdini_in_the_current_directory(tmp_path, monkeypatch, capsys):
    """Review 12: $HIP after `hocuspocus launch` is where the command ran, not home."""
    shot = tmp_path / "shot"
    shot.mkdir()
    monkeypatch.chdir(shot)
    monkeypatch.setenv("HOCUSPOCUS_WORK_DIR", str(tmp_path / "bridge_rule"))
    launcher, spawned = _fake_launcher(tmp_path)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--headless", "--wait", "30"]) == 0
    argv, _env = spawned[0]
    assert launcher.test_cwds[0] == shot.resolve()
    assert argv[-2:] == ["--work-dir", str(shot.resolve())]
    assert "$HIP" in capsys.readouterr().err


def test_launch_work_dir_option(tmp_path, monkeypatch, capsys):
    work = tmp_path / "jobs" / "shot010"
    launcher, _spawned = _fake_launcher(tmp_path)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--work-dir", str(work), "--wait", "30"]) == 0
    assert launcher.test_cwds[0] == work.resolve() and work.is_dir()


def test_launch_help_documents_the_work_dir(capsys):
    with pytest.raises(SystemExit):
        cli.main(["launch", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "--work-dir" in text and "$HIP" in text and "current directory" in text


def test_launch_gui_with_hip(tmp_path, monkeypatch, capsys):
    hip = tmp_path / "shot.hip"
    hip.write_text("")
    launcher, spawned = _fake_launcher(tmp_path)
    monkeypatch.setattr(cli, "_launcher", lambda hfs: launcher)
    assert cli.main(["launch", "--hip", str(hip)]) == 0
    argv, _env = spawned[0]
    assert Path(argv[0]).stem == "houdinifx" and argv[1] == str(hip.resolve())
    captured = capsys.readouterr()
    assert json.loads(captured.out)["mode"] == "gui"
    # Review 16 N6: a loaded hip is not "the untitled scene".
    assert "untitled" not in captured.err and str(hip.resolve()) in captured.err


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


# -- review 10 section 1.11 and 1.4 ---------------------------------------------------------


def test_install_dev_removes_copied_installs(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    assert cli.main(["install-houdini", "--prefs", str(prefs)]) == 0
    assert (prefs / "hocuspocus" / __version__).is_dir()
    assert cli.main(["install-houdini", "--prefs", str(prefs), "--dev"]) == 0
    assert cli.copied_installs(prefs) == []
    assert "removed copied install" in capsys.readouterr().out


def test_uninstall_reports_a_locked_install(tmp_path, monkeypatch, capsys):
    prefs = tmp_path / "prefs"
    cli.main(["install-houdini", "--prefs", str(prefs)])

    def locked(path, *args, **kwargs):
        raise PermissionError(13, "in use", str(path))

    monkeypatch.setattr(cli.shutil, "rmtree", locked)
    assert cli.main(["uninstall-houdini", "--prefs", str(prefs)]) == 1
    assert "close Houdini" in capsys.readouterr().out


def test_doctor_flags_leftover_copies(tmp_path, capsys):
    prefs = tmp_path / "prefs"
    cli.main(["install-houdini", "--prefs", str(prefs), "--dev"])
    (prefs / "hocuspocus" / "0.9.0" / "python").mkdir(parents=True)
    cli.main(["doctor", "--prefs", str(prefs)])
    out = capsys.readouterr().out
    assert "[warn] copied installs" in out and "0.9.0" in out


def test_doctor_removes_an_entry_whose_port_refuses(tmp_path, capsys):
    import os
    import socket

    from hocuspocus.tools import paths

    with socket.socket() as sock:  # a port nothing listens on once closed
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    entry = paths.instances_dir() / f"{os.getpid()}.json"  # a live pid: this process
    entry.parent.mkdir(parents=True)
    entry.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": "t"}))
    cli.main(["doctor", "--prefs", str(tmp_path / "prefs")])
    out = capsys.readouterr().out
    assert "removed the stale registry entry" in out
    assert not entry.exists()


# -- 1.2.1: every pref dir Houdini may use ------------------------------------------------


def _windows_machine(tmp_path, *, docs=True, home=True):
    """A fake Windows profile: ``%USERPROFILE%/Documents/houdini22.0`` (Houdini from the
    Start menu, no HOME) and ``%HOME%/houdini22.0`` (Houdini from Git Bash)."""
    profile = tmp_path / "fakehome"
    docs_dir, home_dir = profile / "Documents" / "houdini22.0", profile / "houdini22.0"
    if docs:
        docs_dir.mkdir(parents=True)
    if home:
        home_dir.mkdir(parents=True)
    return {"USERPROFILE": str(profile), "HOME": str(profile)}, home_dir, docs_dir


def _hython_like_houdini(home_dir, docs_dir, asked=None):
    """hython's ``homeHoudiniDirectory()``: ``%HOME%/houdini22.0`` when HOME is set."""

    def query(hfs, env):
        if asked is not None:
            asked.append("HOME" in env)
        return str(home_dir if "HOME" in env else docs_dir)

    return query


@pytest.fixture
def fake_hfs(tmp_path, monkeypatch):
    hfs = tmp_path / "Houdini 22.0.466"
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: hfs)
    return hfs


def test_home_changes_hythons_answer_and_both_are_candidates(tmp_path, fake_hfs):
    env, home_dir, docs_dir = _windows_machine(tmp_path)
    asked = []
    cands = cli.pref_dir_candidates(
        None,
        environ=env,
        hython_query=_hython_like_houdini(home_dir, docs_dir, asked),
        platform="win32",
    )
    assert asked == [True, False]  # once as is, once without HOME
    assert [c.path for c in cands] == [home_dir, docs_dir]
    assert cands[0].source.startswith("hython (") and "default location" in cands[0].source
    assert cands[1].source.startswith("hython without HOME")
    # Without HOME in the environment there is nothing to remove: one query.
    asked.clear()
    no_home = {"USERPROFILE": env["USERPROFILE"]}
    cli.pref_dir_candidates(
        None,
        environ=no_home,
        hython_query=_hython_like_houdini(home_dir, docs_dir, asked),
        platform="win32",
    )
    assert asked == [False]


def test_install_writes_into_both_existing_pref_dirs(tmp_path, fake_hfs):
    env, home_dir, docs_dir = _windows_machine(tmp_path)
    lines = []
    rc = cli.install_houdini(
        None,
        dev=False,
        environ=env,
        hython_query=_hython_like_houdini(home_dir, docs_dir),
        platform="win32",
        out=lines.append,
    )
    assert rc == 0
    for prefs in (home_dir, docs_dir):
        target = prefs / "packages" / "hocuspocus.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        python_dir = cli.package_python_dir(data)
        assert python_dir == Path(
            str(prefs / "hocuspocus" / __version__ / "python").replace("\\", "/")
        )
        assert (python_dir / "hocuspocus" / "version.py").is_file()
        assert any(line.startswith("wrote ") and str(target) in line for line in lines)
    record = json.loads((tmp_path / "state" / "install.json").read_text(encoding="utf-8"))
    posix = [str(p.resolve()).replace("\\", "/") for p in (home_dir, docs_dir)]
    assert record["pref_dirs"] == posix and record["prefs"] == posix[0]


def test_install_with_only_one_existing_creates_no_other(tmp_path, fake_hfs):
    env, home_dir, docs_dir = _windows_machine(tmp_path, home=False)
    lines = []
    rc = cli.install_houdini(
        None,
        dev=True,
        environ=env,
        hython_query=_hython_like_houdini(home_dir, docs_dir),
        platform="win32",
        out=lines.append,
    )
    assert rc == 0
    assert (docs_dir / "packages" / "hocuspocus.json").is_file()
    assert not home_dir.exists()  # hython named it, but Houdini never created it
    assert any(str(home_dir) in line and "skipped" in line for line in lines)
    record = json.loads((tmp_path / "state" / "install.json").read_text(encoding="utf-8"))
    assert record["pref_dirs"] == [str(docs_dir.resolve()).replace("\\", "/")]


def test_install_prefs_flag_is_created_and_existing_defaults_also_get_it(tmp_path):
    env, home_dir, docs_dir = _windows_machine(tmp_path, home=False)
    flag = tmp_path / "custom" / "houdini22.0"
    rc = cli.install_houdini(
        str(flag), dev=True, environ=env, platform="win32", out=lambda line: None
    )
    assert rc == 0
    assert (flag / "packages" / "hocuspocus.json").is_file()
    assert (docs_dir / "packages" / "hocuspocus.json").is_file()
    assert not home_dir.exists()
    record = json.loads((tmp_path / "state" / "install.json").read_text(encoding="utf-8"))
    assert record["prefs"] == str(flag.resolve()).replace("\\", "/")
    assert len(record["pref_dirs"]) == 2


def test_candidates_dedupe_by_real_path(tmp_path, fake_hfs):
    env, home_dir, docs_dir = _windows_machine(tmp_path, docs=False)
    spelled = str(home_dir / ".." / "houdini22.0")
    cands = cli.pref_dir_candidates(
        spelled,
        environ={**env, "HOUDINI_USER_PREF_DIR": str(home_dir)},
        hython_query=lambda hfs, e: str(home_dir),
        platform="win32",
    )
    assert len(cands) == 1
    assert cands[0].source.startswith("--prefs, HOUDINI_USER_PREF_DIR, hython")


def test_uninstall_removes_every_recorded_pref_dir(tmp_path, fake_hfs):
    env, home_dir, docs_dir = _windows_machine(tmp_path)
    query = _hython_like_houdini(home_dir, docs_dir)
    cli.install_houdini(
        None, dev=False, environ=env, hython_query=query, platform="win32", out=lambda x: None
    )
    lines = []
    # Even when this shell only finds one of them, the record names both.
    rc = cli.uninstall_houdini(
        None,
        environ={"USERPROFILE": env["USERPROFILE"]},
        hython_query=lambda hfs, e: str(docs_dir),
        platform="win32",
        out=lines.append,
    )
    assert rc == 0
    for prefs in (home_dir, docs_dir):
        assert not (prefs / "packages" / "hocuspocus.json").exists()
        assert not (prefs / "hocuspocus").exists()
        assert prefs.is_dir()  # the pref dirs themselves stay
    assert not (tmp_path / "state" / "install.json").exists()
    assert "Restart Houdini" in lines[-1]


def test_doctor_warns_when_pref_dirs_disagree(tmp_path, fake_hfs, monkeypatch):
    env, home_dir, docs_dir = _windows_machine(tmp_path)
    query = _hython_like_houdini(home_dir, docs_dir)
    monkeypatch.setattr(cli, "run_hython", lambda *a, **k: "22.0.466")
    # A 1.2.0-style install: only the pref dir hython reported from this shell.
    cli.install(home_dir, dev=True, out=lambda x: None)
    lines = []
    args = cli.build_parser().parse_args(["doctor"])
    cli.doctor(args, lines.append, environ=env, hython_query=query, platform="win32")
    out = "\n".join(lines)
    assert f"[ok]   pref dir: {home_dir}" in out
    assert f"[--]   pref dir: {docs_dir}" in out and "no package JSON" in out
    warning = next(x for x in lines if "pref dirs disagree" in x)
    assert warning.startswith("[warn]") and str(docs_dir) in warning
    assert "`hocuspocus install-houdini --dev`" in warning
    # After installing into both, they agree.
    cli.install_houdini(
        None, dev=True, environ=env, hython_query=query, platform="win32", out=lambda x: None
    )
    lines.clear()
    cli.doctor(args, lines.append, environ=env, hython_query=query, platform="win32")
    assert not any("disagree" in x for x in lines)
    assert sum(x.startswith("[ok]   pref dir:") for x in lines) == 2


def test_doctor_flags_a_stale_copy_in_another_pref_dir(tmp_path, fake_hfs, monkeypatch):
    env, home_dir, docs_dir = _windows_machine(tmp_path)
    query = _hython_like_houdini(home_dir, docs_dir)
    monkeypatch.setattr(cli, "run_hython", lambda *a, **k: "22.0.466")
    cli.install_houdini(
        None, dev=False, environ=env, hython_query=query, platform="win32", out=lambda x: None
    )
    version_py = docs_dir / "hocuspocus" / __version__ / "python" / "hocuspocus" / "version.py"
    version_py.write_text('__version__ = "0.9.0"\n', encoding="utf-8")
    lines = []
    args = cli.build_parser().parse_args(["doctor"])
    cli.doctor(args, lines.append, environ=env, hython_query=query, platform="win32")
    assert any("pref dirs disagree" in x and str(docs_dir) in x for x in lines)
    assert any("has 0.9.0" in x for x in lines)
    assert not any("install-houdini --dev" in x for x in lines)
