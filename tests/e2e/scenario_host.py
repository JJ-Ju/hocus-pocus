"""The e2e scenarios' headless host and MCP call recorder (no tests here).

``hython`` finds a hython (``HOUDINI_HYTHON`` or the detected install); ``headless_host``
starts ``hython -m hocuspocus.host`` from a neutral cwd with isolated state and pref dirs
on an ephemeral port (never 37219) and stops only that process; :class:`Recorder` calls
tools through the official MCP client and counts calls and response bytes. In 1.4 and 2.0
they lived in ``test_scenario_authoring.py``, whose 1.4 scenario ran under ``compat_1x``;
2.1 removed that profile and the scenario (``test_scenario_authoring_v2.py`` is the build
with the 2.0 tools).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REGISTER_TIMEOUT_S = 180.0


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


@pytest.fixture(scope="module")
def hython() -> Path:
    path = _find_hython()
    if path is None or not path.is_file():
        pytest.skip("hython not found (set HOUDINI_HYTHON or HFS)")
    return path


@pytest.fixture
def headless_host(hython: Path, tmp_path: Path):
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
            "HOCUSPOCUS_WORK_DIR": str(tmp_path / "work"),
            # Houdini ignores HOUDINI_USER_PREF_DIR without the __HVER__ token.
            "HOUDINI_USER_PREF_DIR": (prefs / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    log_path = tmp_path / "hython.log"
    log = open(log_path, "wb")  # noqa: SIM115 - closed in teardown
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
                    f"hython exited ({proc.returncode}):\n" + log_path.read_text(errors="replace")
                )
            if time.monotonic() > deadline:
                pytest.fail("headless host did not register in time")
            time.sleep(0.25)
        info = json.loads(entry.read_text(encoding="utf-8"))
        assert info["port"] != 37219
        yield proc, state
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


class Recorder:
    """Calls tools through the MCP client and keeps the call count and response bytes."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls: list[tuple[str, int, bool]] = []

    async def call(self, name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        result = await self.client.call_tool(name, args)
        size = sum(
            len(getattr(c, "text", "").encode("utf-8")) + len(getattr(c, "data", "") or "")
            for c in result.content
        )
        self.calls.append((name, size, bool(result.is_error)))
        payload = result.structured_content
        if payload is None:  # fall back to the text block (same JSON)
            payload = json.loads(result.content[0].text)
        return bool(result.is_error), payload

    async def ok(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        is_error, payload = await self.call(name, args)
        assert not is_error, f"{name} {args} failed: {payload}"
        return payload

    async def error(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        is_error, payload = await self.call(name, args)
        assert is_error, f"{name} {args} unexpectedly succeeded: {payload}"
        assert payload.get("code"), payload
        return payload

    @property
    def total_bytes(self) -> int:
        return sum(size for _name, size, _err in self.calls)

    def report(self) -> str:
        lines = [
            f"  {i + 1:2d}. {n:<18} {s:6d} B{' (isError)' if e else ''}"
            for i, (n, s, e) in enumerate(self.calls)
        ]
        return "\n".join(lines)
