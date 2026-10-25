"""A cancelled render child takes the processes it started with it (BIBLE D74: under a
Karma ROP the child hython's own child is husk, which ``Popen.kill`` alone leaves
rendering)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from hocuspocus.host.look.child import child_process_kwargs, kill_tree

pytestmark = pytest.mark.unit

GRANDCHILD = """
import sys, time
from pathlib import Path
beat = Path(sys.argv[1])
while True:
    beat.write_text(str(time.time()))
    time.sleep(0.05)
"""

CHILD = """
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
time.sleep(60)
"""


def _beats(path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.05)
    return False


def test_kill_tree_stops_the_grandchild(tmp_path):
    beat = tmp_path / "beat.txt"
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD, GRANDCHILD, str(beat)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **child_process_kwargs(),
    )
    try:
        assert _beats(beat), "the grandchild never started"
        kill_tree(proc)
        proc.wait(10)
        time.sleep(0.5)  # a grandchild still alive would write again within 50 ms
        before = beat.read_text()
        time.sleep(0.5)
        assert beat.read_text() == before, "the grandchild kept running"
    finally:
        proc.kill()


def test_child_process_kwargs_per_platform():
    kwargs = child_process_kwargs()
    if sys.platform == "win32":
        assert set(kwargs) == {"creationflags"}
    else:
        assert kwargs == {"start_new_session": True}
