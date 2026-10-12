"""End to end: official MCP client → ``hocuspocus-mcp`` (stdio) → ``hython -m hocuspocus.host``.

Skips cleanly when hython is absent or the host package is not importable yet.
Never uses port 37219; the host binds an ephemeral port and registers into an
isolated state dir; hython runs from a neutral cwd (BIBLE §10.1, §11).
"""

from __future__ import annotations

import json
import os
import signal
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
    work = tmp_path / "work"
    for d in (state, prefs, cwd):
        d.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_WORK_DIR": str(work),
            # Houdini ignores HOUDINI_USER_PREF_DIR without the __HVER__ token.
            "HOUDINI_USER_PREF_DIR": (prefs / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
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


def _json(result) -> dict:
    """A tool result's JSON from its text block (``result_content = "text"``, the default)."""
    return json.loads(result.content[0].text)


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
    # result_content = "text": the JSON travels once, and no outputSchema is declared.
    assert status.structured_content is None
    assert all(tool.output_schema is None for tool in tools)
    connected = _json(status)["connected"]
    assert connected["pid"] == proc.pid
    # Review 07 papercut 3: the untitled scene lives in the work dir, not the state dir.
    work = (tmp_path / "work").as_posix()
    assert connected["env"]["HIP"] == work
    assert connected["env"]["JOB"] == work
    assert connected["hip"]["path"] == f"{work}/untitled.hip"
    assert connected["hip"]["note"] == "$HIP is the launch directory until you hip_save."
    assert not connected["hip"]["path"].startswith(state.as_posix())


def test_bridge_launch_starts_in_the_work_dir(hython, tmp_path):
    """houdini_connect {launch: headless} through the real launcher: $HIP and $JOB of the
    untitled scene are HOCUSPOCUS_WORK_DIR (review 07 papercut 3). Then that Houdini is
    killed: the next call names it and says its unsaved changes are lost (papercut 8)."""
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    state = tmp_path / "state"
    work = tmp_path / "work"
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_WORK_DIR": str(work),
            "HOCUSPOCUS_HFS": str(hython.parent.parent),
            "HOUDINI_USER_PREF_DIR": (tmp_path / "prefs" / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
    )

    async def run():
        async with Client(params, read_timeout_seconds=180) as client:
            launched = await client.call_tool(
                "houdini_connect", {"launch": {"mode": "headless", "wait_s": 150}}
            )
            status = await client.call_tool("houdini_status", {})
            pid = _json(status)["connected"]["pid"]
            os.kill(pid, signal.SIGTERM)  # the hython this test launched
            for _ in range(100):
                if not any((state / "instances").glob(f"{pid}.json")):
                    break
                await anyio.sleep(0.1)
            await anyio.sleep(0.5)
            offline = await client.call_tool("node_find", {"root": "/obj"})
            return launched, status, offline

    launched, status, offline = None, None, None
    try:
        launched, status, offline = anyio.run(run)
        assert launched.is_error is False, launched.content
        block = _json(launched)["launched"]
        assert isinstance(block["outlives_server"], bool) and block["note"]
        connected = _json(status)["connected"]
        (row,) = [i for i in _json(status)["instances"] if i["selected"]]
        assert isinstance(row["launched_by"], int) and row["launched_by"] != connected["pid"]
        assert connected["env"]["HIP"] == work.as_posix()
        assert connected["env"]["JOB"] == work.as_posix()
        assert connected["hip"]["path"] == f"{work.as_posix()}/untitled.hip"
        assert "note" in connected["hip"]
        error = _json(offline)
        assert offline.is_error is True and error["code"] == "houdini_offline", error
        assert f"pid {connected['pid']}" in error["message"], error
        assert "lost" in error["message"] and error["retryable"] is False
    finally:
        # Stop only the hython this test launched (found through its own state dir).
        from hocuspocus.bridge.client import HostClient

        for entry in (state / "instances").glob("*.json"):
            info = json.loads(entry.read_text(encoding="utf-8"))
            try:
                HostClient(info["port"], info["token"]).shutdown()
            except Exception:  # noqa: BLE001 - fall back to killing that pid
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(info["pid"])]
                    if sys.platform == "win32"
                    else ["kill", "-9", str(info["pid"])],
                    capture_output=True,
                    check=False,
                )


def _stop(pid: int, entry: Path) -> None:
    """Stop a hython this test launched: over HTTP when it still answers, else by pid."""
    from hocuspocus.bridge.client import HostClient

    try:
        info = json.loads(entry.read_text(encoding="utf-8"))
        HostClient(info["port"], info["token"]).shutdown()
        return
    except Exception:  # noqa: BLE001 - fall back to killing that pid
        pass
    subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)]
        if sys.platform == "win32"
        else ["kill", "-9", str(pid)],
        capture_output=True,
        check=False,
    )


def test_a_later_bridge_names_the_server_that_launched_houdini(hython, tmp_path):
    """Review 11 B1: bridge 1 launches a headless Houdini and exits; once that Houdini is
    gone, bridge 2's houdini_offline names it and bridge 1's pid, with the keep-alive hint."""
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    state = tmp_path / "state"
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_WORK_DIR": str(tmp_path / "work"),
            "HOCUSPOCUS_HFS": str(hython.parent.parent),
            "HOUDINI_USER_PREF_DIR": (tmp_path / "prefs" / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
    )

    async def launch():
        async with Client(params, read_timeout_seconds=180) as client:
            return await client.call_tool(
                "houdini_connect", {"launch": {"mode": "headless", "wait_s": 150}}
            )

    async def later_call():
        async with Client(params, read_timeout_seconds=60) as client:
            return await client.call_tool("node_find", {"root": "/obj"})

    pid = None
    try:
        launched = anyio.run(launch)
        assert launched.is_error is False, launched.content
        pid = _json(launched)["launched"]["pid"]
        entry = state / "instances" / f"{pid}.json"
        if entry.is_file():  # it outlived bridge 1 here: the registry names bridge 1
            launcher = json.loads(entry.read_text(encoding="utf-8"))["launched_by"]
            assert isinstance(launcher, int) and launcher != pid
            _stop(pid, entry)
        from hocuspocus.bridge.instances import pid_alive

        for _ in range(100):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
        offline = anyio.run(later_call)
        error = _json(offline)
        assert offline.is_error is True and error["code"] == "houdini_offline", error
        assert (
            f"Houdini pid {pid}" in error["message"]
            and "HocusPocus server (pid" in error["message"]
        )
        assert "keep one MCP session open" in error["hint"]
        assert error["detail"]["pid"] == pid and isinstance(error["detail"]["launched_by"], int)
    finally:
        if pid is not None:
            _stop(pid, state / "instances" / f"{pid}.json")
