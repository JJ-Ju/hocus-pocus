"""End to end: official MCP client → ``hocuspocus-mcp`` (stdio) → ``hython -m hocuspocus.host``.

Skips cleanly when hython is absent or the host package is not importable yet.
Never uses port 37219; the host binds an ephemeral port and registers into an
isolated state dir; hython runs from a neutral cwd (BIBLE §10.1, §11).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SRC = Path(__file__).resolve().parents[2] / "src"
REGISTER_TIMEOUT_S = 120.0


def _find_hython() -> Path | None:
    exe = "hython.exe" if sys.platform == "win32" else "hython"
    explicit = os.environ.get("HOUDINI_HYTHON")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    sys.path.insert(0, str(SRC))
    try:
        from hocuspocus.bridge.launch import detect_hfs
    finally:
        sys.path.remove(str(SRC))
    hfs = detect_hfs(None)
    return hfs / "bin" / exe if hfs else None


def _host_importable() -> bool:
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, "-c", "import hocuspocus.host.__main__"],
        env=env,
        capture_output=True,
        cwd=tempfile.gettempdir(),
        timeout=60,
    )
    return proc.returncode == 0


@pytest.fixture(scope="module")
def hython() -> Path:
    path = _find_hython()
    if path is None or not path.is_file():
        pytest.skip("hython not found (set HOUDINI_HYTHON or HFS)")
    if not _host_importable():
        pytest.skip("hocuspocus.host.__main__ is not importable yet")
    return path


@pytest.fixture
def headless_host(hython, tmp_path):
    state = tmp_path / "state"
    prefs = tmp_path / "prefs"
    cwd = tmp_path / "cwd"
    for d in (state, prefs, cwd):
        d.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOUDINI_USER_PREF_DIR": str(prefs),
        }
    )
    log = open(tmp_path / "hython.log", "wb")  # noqa: SIM115 - closed in teardown
    proc = subprocess.Popen(
        [str(hython), "-m", "hocuspocus.host", "--port", "0", "--state-dir", str(state)],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    entry = state / "instances" / f"{proc.pid}.json"
    deadline = time.monotonic() + REGISTER_TIMEOUT_S
    try:
        while not entry.is_file():
            if proc.poll() is not None:
                log.flush()
                pytest.fail(
                    f"hython exited ({proc.returncode}):\n"
                    + (tmp_path / "hython.log").read_text(errors="replace")
                )
            if time.monotonic() > deadline:
                pytest.fail("headless host did not register in time")
            time.sleep(0.25)
        info = json.loads(entry.read_text(encoding="utf-8"))
        assert info["port"] != 37219
        yield proc, state, info
    finally:
        try:
            from hocuspocus.bridge.client import HostClient

            info = json.loads(entry.read_text(encoding="utf-8")) if entry.is_file() else None
            if info and proc.poll() is None:
                HostClient(info["port"], info["token"]).shutdown()
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001 - fall through to a hard stop of *our* process
            proc.kill()
            proc.wait(timeout=30)
        log.close()


def test_stdio_roundtrip(headless_host, tmp_path):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    proc, state, _info = headless_host
    env = dict(os.environ)
    env.update({"HOCUSPOCUS_STATE_DIR": str(state), "PYTHONPATH": str(SRC)})
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hocuspocus.bridge"],
        env=env,
        cwd=str(tmp_path),
    )

    async def run():
        async with Client(params, read_timeout_seconds=120) as client:
            instructions = client.instructions
            tools = (await client.list_tools()).tools
            status = await client.call_tool("houdini_status", {})
            return instructions, tools, status

    instructions, tools, status = anyio.run(run)
    assert instructions and "Houdini" in instructions
    assert tools, "tools/list is empty"
    assert status.is_error is False, status.content
    assert status.structured_content["connected"]["pid"] == proc.pid
