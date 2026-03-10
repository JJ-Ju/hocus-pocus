"""Filesystem path helpers."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore


def package_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _houdini_pref_dir() -> Path | None:
    if hou is not None:
        try:
            pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR")
            if pref_dir:
                return Path(pref_dir)
        except Exception:
            return None
    pref_dir = os.environ.get("HOUDINI_USER_PREF_DIR")
    if pref_dir:
        return Path(pref_dir)
    return None


def state_root() -> Path:
    return _houdini_pref_dir() or package_root() / ".hocuspocus"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return package_root() / "config" / "default.toml"


def log_dir() -> Path:
    return ensure_directory(state_root() / "hocuspocus" / "logs")


def runtime_dir() -> Path:
    return ensure_directory(state_root() / "hocuspocus" / "runtime")


def output_dir() -> Path:
    return ensure_directory(state_root() / "hocuspocus" / "output")


def export_dir() -> Path:
    return ensure_directory(output_dir() / "exports")


def snapshot_dir() -> Path:
    return ensure_directory(output_dir() / "snapshots")


def package_dir() -> Path:
    return ensure_directory(output_dir() / "packages")


def runtime_token_path() -> Path:
    return runtime_dir() / "token.txt"


def audit_log_path() -> Path:
    return runtime_dir() / "audit.jsonl"


def server_log_path() -> Path:
    return log_dir() / "server.log"
