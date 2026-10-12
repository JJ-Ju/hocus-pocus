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
    monkeypatch.setattr(bc, "default_pref_dirs", lambda environ=None: [tmp_path / "default"])
    return {"HOCUSPOCUS_STATE_DIR": str(tmp_path / "state")}


def test_defaults_without_file_or_env(env):
    config = BridgeConfig.load(env)
    assert config == BridgeConfig()
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


def test_from_env_ignores_files(tmp_path, env):
    (tmp_path / "hocuspocus.toml").write_text(TOML, encoding="utf-8")
    env["HOUDINI_USER_PREF_DIR"] = str(tmp_path)
    assert BridgeConfig.from_env(env).profile == "core"
