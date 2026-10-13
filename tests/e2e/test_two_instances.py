"""End to end with two headless Houdinis (review 19): both started with `hocuspocus launch
--headless` into one isolated state dir, driven through one `hocuspocus-mcp` session.

Covers the ambiguity refusal, a pin and a name, jobs routed by the pid in their id, events
cursors per instance, and a pinned Houdini that is killed: instance_lost, never a switch.
Only the two hythons this test starts are stopped (over HTTP, else by pid). Never uses
port 37219; hython runs from its own work dir with an isolated pref dir (BIBLE §11).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SRC = Path(__file__).resolve().parents[2] / "src"
LAUNCH_WAIT_S = 150


def _json(result) -> dict:
    return json.loads(result.content[0].text)


def _env(tmp_path: Path, hython: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(tmp_path / "state"),
            "HOCUSPOCUS_HFS": str(hython.parent.parent),
            "HOCUSPOCUS_PROFILE": "full",
            # Houdini ignores HOUDINI_USER_PREF_DIR without the __HVER__ token.
            "HOUDINI_USER_PREF_DIR": (tmp_path / "prefs" / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _launch(env: dict[str, str], work: Path) -> int:
    """`hocuspocus launch --headless`: returns the pid of the hython it started."""
    work.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hocuspocus.cli",
            "launch",
            "--headless",
            "--work-dir",
            str(work),
            "--wait",
            str(LAUNCH_WAIT_S),
        ],
        env=env,
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=LAUNCH_WAIT_S + 30,
    )
    assert proc.returncode == 0, proc.stderr
    entry = json.loads(proc.stdout.strip().splitlines()[-1])
    assert entry["port"] != 37219
    return int(entry["pid"])


def _stop(state: Path, pids: list[int]) -> None:
    """Stop the hythons this test started: over HTTP when they answer, else by pid."""
    from hocuspocus.bridge.client import HostClient
    from hocuspocus.host.registry import pid_alive

    for pid in pids:
        entry = state / "instances" / f"{pid}.json"
        try:
            info = json.loads(entry.read_text(encoding="utf-8"))
            HostClient(info["port"], info["token"]).shutdown()
        except Exception:  # noqa: BLE001 - fall back to killing that pid
            pass
    deadline = time.monotonic() + 30
    while any(pid_alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.2)
    for pid in pids:
        if pid_alive(pid):
            _kill(pid)


def _kill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)]
        if sys.platform == "win32"
        else ["kill", "-9", str(pid)],
        capture_output=True,
        check=False,
    )


def test_two_headless_instances_pin_route_and_lose(hython, tmp_path):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    from hocuspocus.host.registry import pid_alive

    env = _env(tmp_path, hython)
    state = tmp_path / "state"
    pids: list[int] = []
    try:
        pids.append(_launch(env, tmp_path / "w1"))
        time.sleep(1.1)  # registry `started` has one-second resolution: keep the order
        pids.append(_launch(env, tmp_path / "w2"))
        first, second = pids
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
        )

        async def run() -> dict[str, object]:
            out: dict[str, object] = {}
            async with Client(params, read_timeout_seconds=180) as client:

                async def call(tool: str, args: dict) -> object:
                    return await client.call_tool(tool, args)

                out["status"] = await call("houdini_status", {})
                box = {"items": [{"parent": "/obj", "type": "geo", "name": "g"}]}
                out["ambiguous"] = await call("node_create", box)
                out["read"] = await call("node_find", {"root": "/obj"})

                # Pin and name the first worker; build something to cook there.
                out["pin1"] = await call("houdini_connect", {"pid": first, "name": "one"})
                await call("node_create", box)
                inner = {"items": [{"parent": "/obj/g", "type": "box", "name": "b"}]}
                await call("node_create", inner)
                cook = {"paths": ["/obj/g/b"], "frame_range": [1, 400], "wait_s": 0}
                out["job1"] = await call("cook", cook)
                out["events1"] = await call("events", {})

                # Pin the second worker: the first worker's job still answers by its id.
                out["pin2"] = await call("houdini_connect", {"pid": second})
                job_id = _json(out["job1"]).get("job_id")
                out["routed"] = await call("job", {"action": "status", "job_id": job_id})
                out["all"] = await call("job", {"action": "list", "all": True})
                since = _json(out["events1"])["next_since"]
                out["events2"] = await call("events", {"since": since})
                await call("node_create", box)
                await call("node_create", inner)
                out["job2"] = await call("cook", cook)
                job2 = _json(out["job2"]).get("job_id")
                await call("job", {"action": "status", "job_id": job2})

                # Kill the pinned second worker: no call may land on the first one.
                _kill(second)
                for _ in range(100):
                    if not pid_alive(second):
                        break
                    await anyio.sleep(0.1)
                out["lost"] = await call("node_find", {"root": "/obj"})
                out["lost_status"] = await call("houdini_status", {})
                out["lost_job"] = await call("job", {"action": "status", "job_id": job2})
                out["repin"] = await call("houdini_connect", {"name": "one"})
                out["after"] = await call("node_find", {"root": "/obj"})
                await call("job", {"action": "cancel", "job_id": job_id})
            return out

        out = anyio.run(run)

        status = _json(out["status"])
        rows = {row["pid"]: row for row in status["instances"]}
        assert set(rows) == {first, second}
        assert rows[second]["selected"] is True and rows[first]["selected"] is False  # newest
        assert all(isinstance(row["busy"], bool) for row in rows.values())
        assert all(row["jobs_running"] == 0 for row in rows.values())
        assert any("ambiguous_instance" in w for w in status["warnings"])

        ambiguous = out["ambiguous"]
        assert ambiguous.is_error and _json(ambiguous)["code"] == "ambiguous_instance"
        assert {c["pid"] for c in _json(ambiguous)["candidates"]} == {first, second}
        assert f'houdini_connect {{"pid": {first}}}' in _json(ambiguous)["hint"]

        read = out["read"]
        assert not read.is_error and _json(read)["_instance"]["pid"] == second
        assert read.meta["instance"]["pid"] == second

        assert _json(out["pin1"])["connected"]["name"] == "one"
        job1 = _json(out["job1"])
        assert job1["job_id"].startswith(f"{first}-"), job1
        assert _json(out["events1"])["next_since"].startswith(f"{first}:")

        routed = out["routed"]
        assert not routed.is_error, _json(routed)
        assert routed.meta["instance"]["pid"] == first
        every = _json(out["all"])
        assert {row["pid"] for row in every["instances"]} == {first, second}
        assert any(row["job_id"] == job1["job_id"] for row in every["jobs"])

        events2 = _json(out["events2"])
        assert events2["reset"] is True and str(first) in events2["note"]
        assert events2["next_since"].startswith(f"{second}:")

        lost = _json(out["lost"])
        assert out["lost"].is_error and lost["code"] == "instance_lost", lost
        assert str(second) in lost["message"] and lost["retryable"] is False
        assert [c["pid"] for c in lost["candidates"]] == [first]
        lost_status = _json(out["lost_status"])
        assert lost_status["connected"] is None and lost_status["lost"]["pid"] == second
        lost_job = _json(out["lost_job"])
        assert lost_job["code"] == "instance_lost" and lost_job["detail"]["last_status"]
        assert _json(out["repin"])["connected"]["pid"] == first
        assert out["after"].meta["instance"]["pid"] == first
    finally:
        _stop(state, pids)
