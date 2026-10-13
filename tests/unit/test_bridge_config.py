"""Bridge configuration: one hocuspocus.toml for host and bridge, env wins (BIBLE §3.7)."""

from __future__ import annotations

import json

import pytest

from hocuspocus import cli
from hocuspocus.bridge import config as bc
from hocuspocus.bridge.config import BridgeConfig

pytestmark = pytest.mark.unit

TOML = 'profile = "full"\nmax_response_bytes = 32768\ndefault_timeout_s = 45\nhfs = "C:/hfs"\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An environment with an isolated state dir and no inherited pref dir."""
    monkeypatch.setattr(bc, "default_pref_dirs", lambda *a, **k: [tmp_path / "default"])
    return {"HOCUSPOCUS_STATE_DIR": str(tmp_path / "state")}


def test_defaults_without_file_or_env(env):
    config = BridgeConfig.load(env)
    assert config == BridgeConfig()
    assert config.result_content == "text"
    assert config.config_file == ""


def test_reads_toml_from_houdini_user_pref_dir(tmp_path, env):
    prefs = tmp_path / "houdini22.0"
    prefs.mkdir()
    (prefs / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    # Houdini's __HVER__ token is expanded the way Houdini 22.0 expands it.
    env["HOUDINI_USER_PREF_DIR"] = str(tmp_path / "houdini__HVER__")
    config = BridgeConfig.load(env)
    assert config.profile == "full"
    assert config.max_response_bytes == 32768
    assert config.default_timeout_s == 45.0
    assert config.hfs == "C:/hfs"
    assert config.config_file == str(prefs / "hocuspocus.toml")


def test_env_overrides_file(tmp_path, env):
    (tmp_path / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    env.update(
        {
            "HOUDINI_USER_PREF_DIR": str(tmp_path),
            "HOCUSPOCUS_PROFILE": "core",
            "HOCUSPOCUS_MAX_RESPONSE_BYTES": "20000",
        }
    )
    config = BridgeConfig.load(env)
    assert config.profile == "core"
    assert config.max_response_bytes == 20000
    assert config.default_timeout_s == 45.0  # from the file


def test_bad_values_fall_back_to_defaults(tmp_path, env):
    (tmp_path / "hocuspocus.toml").write_text(
        'profile = "huge"\nmax_response_bytes = -1\ndefault_timeout_s = true\n', encoding="utf-8"
    )
    env["HOUDINI_USER_PREF_DIR"] = str(tmp_path)
    config = BridgeConfig.load(env)
    assert (config.profile, config.max_response_bytes, config.default_timeout_s) == (
        "core",
        bc.DEFAULT_MAX_RESPONSE_BYTES,
        bc.DEFAULT_TIMEOUT_S,
    )


def test_install_json_locates_prefs(tmp_path, env, monkeypatch, capsys):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", env["HOCUSPOCUS_STATE_DIR"])
    monkeypatch.delenv("HOUDINI_USER_PREF_DIR", raising=False)
    monkeypatch.setattr(cli, "_detect_hfs", lambda explicit: None)
    prefs = tmp_path / "prefs"
    assert cli.main(["install-houdini", "--prefs", str(prefs), "--dev"]) == 0
    record = json.loads((tmp_path / "state" / "install.json").read_text(encoding="utf-8"))
    assert record["prefs"] == str(prefs.resolve()).replace("\\", "/")
    (prefs / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    assert BridgeConfig.load(env).profile == "full"
    # Uninstalling forgets the record.
    assert cli.main(["uninstall-houdini", "--prefs", str(prefs)]) == 0
    assert not (tmp_path / "state" / "install.json").exists()
    assert BridgeConfig.load(env).profile == "core"


def test_resolved_pref_dir_without_toml_is_authoritative(tmp_path, env, monkeypatch):
    """A pref dir from env with no toml means defaults, even if a default location has one."""
    default = tmp_path / "default"
    default.mkdir()
    (default / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    assert BridgeConfig.load(env).profile == "full"  # probed default location
    env["HOUDINI_USER_PREF_DIR"] = str(tmp_path / "empty")
    assert BridgeConfig.load(env).profile == "core"


def test_recorded_pref_dirs_first_with_a_toml_wins(tmp_path, env):
    """1.2.1: the toml is read from the first recorded pref dir that has one, then the
    default locations; a recorded dir without a toml no longer hides the others."""
    first, second = tmp_path / "home" / "houdini22.0", tmp_path / "docs" / "houdini22.0"
    for d in (first, second):
        d.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    (state / "install.json").write_text(
        json.dumps({"prefs": str(first), "pref_dirs": [str(first), str(second)]}),
        encoding="utf-8",
    )
    assert bc.installed_pref_dirs(state) == [first, second]
    assert bc.installed_pref_dir(state) == first
    default = tmp_path / "default"
    default.mkdir()
    (default / "hocuspocus.toml").write_text('profile = "full"\n', encoding="utf-8")
    assert bc.pref_dir_candidates(env) == [first, second, default]
    assert BridgeConfig.load(env).config_file == str(default / "hocuspocus.toml")
    (second / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    assert BridgeConfig.load(env).config_file == str(second / "hocuspocus.toml")
    (first / "hocuspocus.toml").write_text('profile = "core"\n', encoding="utf-8")
    assert BridgeConfig.load(env).config_file == str(first / "hocuspocus.toml")


def test_pre_121_install_json_still_read(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "install.json").write_text(json.dumps({"prefs": "C:/p/houdini22.0"}))
    assert bc.installed_pref_dirs(state) == [bc.Path("C:/p/houdini22.0")]


def test_windows_default_pref_dirs_cover_home_and_documents(tmp_path):
    env = {"USERPROFILE": str(tmp_path / "user"), "HOME": str(tmp_path / "home")}
    assert bc.default_pref_dirs(env, major_minor="22.5", platform="win32") == [
        tmp_path / "user" / "houdini22.5",
        tmp_path / "user" / "Documents" / "houdini22.5",
        tmp_path / "home" / "houdini22.5",
        tmp_path / "home" / "Documents" / "houdini22.5",
    ]
    same = {"USERPROFILE": str(tmp_path), "HOME": str(tmp_path)}
    assert len(bc.default_pref_dirs(same, platform="win32")) == 2  # deduplicated


def test_from_env_ignores_files(tmp_path, env):
    (tmp_path / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    env["HOUDINI_USER_PREF_DIR"] = str(tmp_path)
    assert BridgeConfig.from_env(env).profile == "core"


def test_result_content_from_file_and_env(tmp_path):
    prefs = tmp_path / "prefs"
    prefs.mkdir()
    (prefs / "hocuspocus.toml").write_text('result_content = "both"\n', encoding="utf-8")
    env = {"HOUDINI_USER_PREF_DIR": str(prefs)}
    assert BridgeConfig.load(env).result_content == "both"
    env["HOCUSPOCUS_RESULT_CONTENT"] = "Structured"
    assert BridgeConfig.load(env).result_content == "structured"
    env["HOCUSPOCUS_RESULT_CONTENT"] = "json"
    assert BridgeConfig.load(env).result_content == "text"  # invalid: the default


def test_host_ignores_the_bridge_only_result_content_key(tmp_path, caplog):
    from hocuspocus.host.config import load_config

    (tmp_path / "hocuspocus.toml").write_text('result_content = "both"\n', encoding="utf-8")
    with caplog.at_level("WARNING"):
        load_config(tmp_path, environ={})
    assert "result_content" not in caplog.text
