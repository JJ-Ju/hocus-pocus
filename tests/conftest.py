"""Shared pytest configuration. See docs/BIBLE.md §11.

* Finds ``hython`` via ``HOUDINI_HYTHON``, ``$HFS/bin``, or the newest installed
  Houdini 22.x, and exposes it as the ``hython`` fixture.
* Marks tests by directory (``unit``, ``houdini``, ``e2e``) and skips ``houdini``/``e2e``
  tests when no hython is available, so contributors without a licence get green.
* Keeps ``slow`` tests (visual child renders, stage captures, Karma, PDG cooks, 1M-point
  geometry, deliberate timeouts) out of a default run: ``--runslow`` adds them and
  ``-m slow`` runs only them (BIBLE §11).
* Keeps the ``workload`` tier (``tests/workloads``, spec-2.0 §5.2: minutes of scripted
  evaluation workloads against one headless host) out of every run unless
  ``--runworkloads`` is given or a ``-m`` expression names ``workload``. It has two
  tiers, the 1.4 workloads (``tests/workloads/test_*.py``, ``1x``) and the same five on
  the 2.0 tools (``tests/workloads/v2``, ``v2``); ``--workloads v2|1x|all`` (default
  ``all``) selects.
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
    parser.addoption(
        "--runworkloads",
        action="store_true",
        default=False,
        help="run the workloads tier (tests/workloads, marker workload; deselected by default)",
    )
    parser.addoption(
        "--workloads",
        choices=("all", "v2", "1x"),
        default="all",
        help="workloads: the tier to run, v2 (tests/workloads/v2), 1x (the 1.4 workloads) or all",
    )
    parser.addoption(
        "--update-budgets",
        action="store_true",
        default=False,
        help="workloads: rewrite the tiers' budgets.json from this run instead of checking it",
    )


def pytest_configure(config: pytest.Config) -> None:
    for line in (
        "unit: pure-Python tests, no Houdini",
        "houdini: needs hython (run with `hython -m pytest tests/integration`)",
        "e2e: spawns hython and the stdio bridge",
        "slow: over ~1.5 s (renders, captures, PDG cooks); run with --runslow or -m slow",
        "workload: an evaluation workload (tests/workloads); run with --runworkloads",
    ):
        config.addinivalue_line("markers", line)


def _wants_slow(config: pytest.Config) -> bool:
    """``--runslow``, or a ``-m`` expression that names ``slow`` (``-m slow``,
    ``-m "not slow"``), which then decides on its own."""
    return bool(config.getoption("--runslow")) or "slow" in (config.option.markexpr or "")


def _wants_workloads(config: pytest.Config) -> bool:
    """``--runworkloads``, or a ``-m`` expression that names ``workload``."""
    return bool(config.getoption("--runworkloads")) or "workload" in (config.option.markexpr or "")


def _workload_tier(item: pytest.Item) -> str | None:
    """``v2``, ``1x`` or (not a workload) ``None``."""
    parts = Path(str(item.fspath)).parts
    if "workloads" not in parts:
        return None
    return "v2" if "v2" in parts[parts.index("workloads") :] else "1x"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "workloads" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.workload)
    if not _wants_workloads(config):
        heavy = [item for item in items if "workload" in item.keywords]
        if heavy:
            config.hook.pytest_deselected(items=heavy)
            items[:] = [item for item in items if "workload" not in item.keywords]
    tier = config.getoption("--workloads")
    if tier != "all":
        other = [item for item in items if _workload_tier(item) not in (None, tier)]
        if other:
            config.hook.pytest_deselected(items=other)
            items[:] = [item for item in items if item not in other]
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
        if HYTHON is None and (
            "houdini" in item.keywords or "e2e" in item.keywords or "workload" in item.keywords
        ):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def hython() -> Path:
    if HYTHON is None:
        pytest.skip("hython not found (set HOUDINI_HYTHON or HFS)")
    return HYTHON
