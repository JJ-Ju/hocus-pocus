"""Shared pytest configuration. See docs/BIBLE.md §11.

* Finds ``hython`` via ``HOUDINI_HYTHON``, ``$HFS/bin``, or the newest installed
  Houdini 22.x, and exposes it as the ``hython`` fixture.
* Marks tests by directory (``unit``, ``houdini``, ``e2e``) and skips ``houdini``/``e2e``
  tests when no hython is available, so contributors without a licence get green.
* Keeps ``slow`` tests (visual child renders, stage captures, Karma, PDG cooks, 1M-point
  geometry, deliberate timeouts) out of a default run: ``--runslow`` adds them and
  ``-m slow`` runs only them (BIBLE §11).
"""

from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_EXE = ".exe" if sys.platform == "win32" else ""


def _version_key(path: str) -> tuple[int, ...]:
    match = re.search(r"(?:Houdini ?|hfs)(\d+(?:\.\d+)*)", path)
    return tuple(int(x) for x in match.group(1).split(".")) if match else ()


def find_hython() -> Path | None:
    """Locate hython: ``HOUDINI_HYTHON``, then ``$HFS/bin``, then the newest Houdini 22.x."""
    explicit = os.environ.get("HOUDINI_HYTHON")
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    hfs = os.environ.get("HFS")
    if hfs:
        candidate = Path(hfs) / "bin" / f"hython{_EXE}"
        if candidate.is_file():
            return candidate
    if sys.platform == "win32":
        bases = [os.environ.get("PROGRAMFILES", r"C:\Program Files")]
        patterns = [
            os.path.join(b, "Side Effects Software", "Houdini 22.*", "bin", "hython.exe")
            for b in bases
        ]
    elif sys.platform == "darwin":
        patterns = [
            "/Applications/Houdini/Houdini22.*/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        ]
    else:
        patterns = ["/opt/hfs22.*/bin/hython"]
    found = [p for pattern in patterns for p in glob.glob(pattern)]
    if not found:
        return None
    return Path(max(found, key=_version_key))


HYTHON = find_hython()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="also run tests marked slow (deselected by default; -m slow runs only them)",
    )


def pytest_configure(config: pytest.Config) -> None:
    for line in (
        "unit: pure-Python tests, no Houdini",
        "houdini: needs hython (run with `hython -m pytest tests/integration`)",
        "e2e: spawns hython and the stdio bridge",
        "slow: over ~1.5 s (renders, captures, PDG cooks); run with --runslow or -m slow",
    ):
        config.addinivalue_line("markers", line)


def _wants_slow(config: pytest.Config) -> bool:
    """``--runslow``, or a ``-m`` expression that names ``slow`` (``-m slow``,
    ``-m "not slow"``), which then decides on its own."""
    return bool(config.getoption("--runslow")) or "slow" in (config.option.markexpr or "")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _wants_slow(config):
        slow = [item for item in items if "slow" in item.keywords]
        if slow:
            config.hook.pytest_deselected(items=slow)
            items[:] = [item for item in items if "slow" not in item.keywords]
    skip = pytest.mark.skip(reason="hython not found (set HOUDINI_HYTHON or HFS)")
    for item in items:
        parts = Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in parts:
            item.add_marker(pytest.mark.houdini)
        elif "e2e" in parts:
            item.add_marker(pytest.mark.e2e)
        if HYTHON is None and ("houdini" in item.keywords or "e2e" in item.keywords):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def hython() -> Path:
    if HYTHON is None:
        pytest.skip("hython not found (set HOUDINI_HYTHON or HFS)")
    return HYTHON
