"""Filesystem locations shared by host and bridge. Stdlib only. See docs/BIBLE.md §3.2.

``HOCUSPOCUS_STATE_DIR`` overrides everything (tests use it for isolation).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("HOCUSPOCUS_STATE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "HocusPocus"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "hocuspocus"


def instances_dir() -> Path:
    return state_dir() / "instances"


def logs_dir() -> Path:
    return state_dir() / "logs"


def captures_dir() -> Path:
    return state_dir() / "captures"


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (and parents) readable only by the current user where the OS allows."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path
