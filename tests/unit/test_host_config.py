from __future__ import annotations

import logging

from hocuspocus.host.config import HostConfig, load_config


def test_defaults_match_bible(tmp_path):
    config = load_config(tmp_path, environ={})
    assert config.autostart is True
    assert config.allow_python is True
    assert config.read_only is False
    assert config.approved_roots == []
    assert config.max_response_bytes == 16384
    assert config.default_timeout_s == 30
    assert config.job_threshold_s == 10
    assert config.profile == "core"
    assert config.log_level == "INFO"
    assert config.hfs == ""
    assert config.port == 0
    assert config.pref_dir == str(tmp_path)


def test_file_then_env_then_kwargs(tmp_path):
    (tmp_path / "hocuspocus.toml").write_text(
        'read_only = true\nallow_python = false\nmax_response_bytes = 4096\nprofile = "full"\n'
        'approved_roots = ["C:/proj"]\ndefault_timeout_s = 5\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path, environ={})
    assert config.read_only is True
    assert config.allow_python is False
    assert config.max_response_bytes == 4096
    assert config.profile == "full"
    assert config.approved_roots == ["C:/proj"]
    assert config.default_timeout_s == 5.0

    env = {
        "HOCUSPOCUS_READ_ONLY": "0",
        "HOCUSPOCUS_MAX_RESPONSE_BYTES": "8192",
        "HOCUSPOCUS_LOG_LEVEL": "debug",
    }
    config = load_config(tmp_path, environ=env)
    assert config.read_only is False
    assert config.max_response_bytes == 8192
    assert config.log_level == "DEBUG"
    assert config.allow_python is False  # file value survives

    config = load_config(tmp_path, environ=env, read_only=True, port=4567)
    assert config.read_only is True
    assert config.port == 4567


def test_env_list_uses_pathsep(tmp_path):
    import os

    config = load_config(tmp_path, environ={"HOCUSPOCUS_APPROVED_ROOTS": f"/a{os.pathsep}/b"})
    assert config.approved_roots == ["/a", "/b"]


def test_unknown_and_bad_values_warn(tmp_path, caplog):
    (tmp_path / "hocuspocus.toml").write_text(
        'mystery = 1\nread_only = "yes"\nprofile = "huge"\nmax_response_bytes = 10\n',
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="hocuspocus.host.config"):
        config = load_config(tmp_path, environ={"HOCUSPOCUS_ALLOW_PYTHON": "maybe"})
    assert config == HostConfig(pref_dir=str(tmp_path))
    text = caplog.text
    assert "mystery" in text
    assert "read_only" in text
    assert "profile" in text
    assert "max_response_bytes" in text
    assert "allow_python" in text


def test_broken_toml_is_ignored(tmp_path, caplog):
    (tmp_path / "hocuspocus.toml").write_text("this is = = not toml", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        config = load_config(tmp_path, environ={})
    assert config.read_only is False
    assert "cannot read" in caplog.text


def test_hocuspocus_table_is_accepted(tmp_path):
    (tmp_path / "hocuspocus.toml").write_text("[hocuspocus]\nread_only = true\n", encoding="utf-8")
    assert load_config(tmp_path, environ={}).read_only is True


def test_unexpanded_hver_pref_dir_is_not_used(monkeypatch, tmp_path):
    monkeypatch.setenv("HOUDINI_USER_PREF_DIR", str(tmp_path / "houdini__HVER__"))
    assert load_config(environ={}).pref_dir == ""
    monkeypatch.setenv("HOUDINI_USER_PREF_DIR", str(tmp_path))
    assert load_config(environ={}).pref_dir == str(tmp_path)


def test_with_overrides():
    assert HostConfig().with_overrides(read_only=True, nonsense=1).read_only is True
