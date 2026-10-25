"""End to end: the bridge ledger, roles and ``on`` (spec-2.0 §2.1, §2.5, §3; M2 exit).

Two headless Houdinis started with `hocuspocus launch --headless` into one isolated state
dir, driven by two `hocuspocus-mcp` processes in turn (the second one is the bridge
"restarted"), profile full (the 2.0 surface):

1. roles: both start as workers; one becomes the editor and is pinned;
2. `render {on: "worker"}` runs on the other one while the editor stays pinned, and returns
   an opaque ledger job id;
3. a new bridge process answers `job status` for that id from the ledger and the live host,
   pins the worker by role, cancels the job;
4. after `houdini_connect {quit}` the worker is listed under `recent` with its role, and its
   job's status is `instance_lost` carrying the last status from the ledger.

Only the two hythons this test starts are stopped. Never uses port 37219; hython runs from
its own work dir with an isolated pref dir (BIBLE §11).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from test_two_instances import _env, _launch, _stop

pytestmark = pytest.mark.e2e

FRAMES = 400
SLOW_SOP = "import time\ntime.sleep(0.05)\n"
"""A Python SOP that takes 50 ms per frame: the render runs long enough to restart a bridge."""


def _json(result) -> dict:
    return json.loads(result.content[0].text)


def test_ledger_roles_on_and_a_bridge_restart(hython, tmp_path):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    env = dict(_env(tmp_path, hython), HOCUSPOCUS_PROFILE="full")
    state = tmp_path / "state"
    pids: list[int] = []
    try:
        pids.append(_launch(env, tmp_path / "w1"))
        time.sleep(1.1)  # registry `started` has one-second resolution: keep the order
        pids.append(_launch(env, tmp_path / "w2"))
        editor, worker = pids
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
        )
        cache = (tmp_path / "w2" / "cache" / "slow.$F4.bgeo.sc").as_posix()

        async def first_bridge() -> dict[str, object]:
            out: dict[str, object] = {}
            async with Client(params, read_timeout_seconds=180) as client:

                async def call(tool: str, args: dict) -> object:
                    return await client.call_tool(tool, args)

                out["status0"] = await call("houdini_status", {})
                # Build the slow cache on the worker (pinned for the edits).
                out["pin_worker"] = await call("houdini_connect", {"pid": worker, "name": "w"})
                build = {
                    "items": [
                        {"parent": "/obj", "type": "geo", "name": "g"},
                        {
                            "parent": "/obj/g",
                            "type": "box",
                            "name": "b",
                            "parms": {"sizex": {"expr": "1 + $F * 0.01"}},
                        },
                        {
                            "parent": "/obj/g",
                            "type": "python",
                            "name": "slow",
                            "parms": {"python": SLOW_SOP},
                            "inputs": [{"index": 0, "from": "/obj/g/b"}],
                        },
                        {
                            "parent": "/obj/g",
                            "type": "rop_geometry",
                            "name": "rop",
                            "parms": {"sopoutput": cache},
                            "inputs": [{"index": 0, "from": "/obj/g/slow"}],
                        },
                    ]
                }
                out["build"] = await call("node_create", build)
                # The other Houdini becomes the editor and is pinned.
                out["pin_editor"] = await call(
                    "houdini_connect", {"pid": editor, "role": "editor", "name": "ed"}
                )
                out["render"] = await call(
                    "render",
                    {"rop_path": "/obj/g/rop", "frames": [1, FRAMES], "wait_s": 0, "on": "worker"},
                )
                out["status1"] = await call("houdini_status", {})
                job_id = _json(out["render"]).get("job_id")
                out["job1"] = await call("job", {"action": "status", "job_id": job_id})
                out["editor_read"] = await call("search", {"kind": "nodes", "root": "/obj"})
            return out

        async def second_bridge(job_id: str) -> dict[str, object]:
            out: dict[str, object] = {}
            async with Client(params, read_timeout_seconds=180) as client:

                async def call(tool: str, args: dict) -> object:
                    return await client.call_tool(tool, args)

                out["job2"] = await call("job", {"action": "status", "job_id": job_id})
                out["by_role"] = await call("houdini_connect", {"role": "worker"})
                out["cancel"] = await call("job", {"action": "cancel", "job_id": job_id})
                for _ in range(100):
                    status = await call("job", {"action": "status", "job_id": job_id})
                    if _json(status).get("state") != "running":
                        break
                    await anyio.sleep(0.1)
                out["final"] = status
                out["quit"] = await call(
                    "houdini_connect", {"quit": True, "pid": worker, "on_unsaved": "discard"}
                )
                out["status2"] = await call("houdini_status", {})
                out["lost_job"] = await call("job", {"action": "status", "job_id": job_id})
                out["no_worker"] = await call("cook", {"paths": ["/obj"], "on": "worker"})
            return out

        one = anyio.run(first_bridge)
        status0 = _json(one["status0"])
        # 2.0 M4: a row names its role only when it is not the mode's default (headless:
        # worker).
        assert {row["pid"]: row.get("role", "worker") for row in status0["instances"]} == {
            editor: "worker",
            worker: "worker",
        }
        assert all("role" not in row for row in status0["instances"]), status0
        assert not one["build"].is_error, _json(one["build"])
        pinned = _json(one["pin_editor"])["connected"]
        assert pinned["pid"] == editor and pinned["role"] == "editor"

        render = one["render"]
        assert not render.is_error, _json(render)
        job_id = _json(render)["job_id"]
        assert job_id.startswith("j") and "-" not in job_id, job_id
        assert render.meta["instance"]["pid"] == worker
        assert render.meta["instance"]["role"] == "worker"
        status1 = _json(one["status1"])
        assert status1["connected"]["pid"] == editor  # the pin did not move
        rows = {row["pid"]: row for row in status1["instances"]}
        assert rows[editor]["role"] == "editor" and "role" not in rows[worker]  # worker
        assert rows[worker]["jobs_running"] == 1
        job1 = _json(one["job1"])
        assert job1["job_id"] == job_id and job1["state"] == "running", job1
        assert one["job1"].meta["instance"]["pid"] == worker
        assert one["editor_read"].meta["instance"]["pid"] == editor

        ledger = state / "ledger.sqlite"
        assert ledger.is_file()
        with sqlite3.connect(ledger) as db:
            row = db.execute(
                "SELECT host_id, instance_pid FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            assert row is not None and row[1] == worker and row[0].startswith(f"{worker}-")
            assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

        two = anyio.run(second_bridge, job_id)  # a new bridge process
        job2 = _json(two["job2"])
        assert not two["job2"].is_error, job2
        assert job2["job_id"] == job_id and job2["state"] in ("running", "done"), job2
        assert two["job2"].meta["instance"]["pid"] == worker
        assert _json(two["by_role"])["connected"]["pid"] == worker
        assert _json(two["final"])["state"] in ("cancelled", "done")
        assert _json(two["quit"])["quit"] is True

        status2 = _json(two["status2"])
        assert [row["pid"] for row in status2["instances"]] == [editor]
        recent = {row["pid"]: row for row in status2.get("recent", [])}
        assert worker in recent, status2
        assert "role" not in recent[worker] and recent[worker]["name"] == "w"  # worker
        assert "alive" not in recent[worker]  # every recent row is dead (2.1, D66)

        lost = _json(two["lost_job"])
        assert two["lost_job"].is_error and lost["code"] == "instance_lost", lost
        assert job_id in lost["message"] and lost["detail"]["last_status"]["state"] in (
            "cancelled",
            "done",
        )
        no_worker = _json(two["no_worker"])
        assert no_worker["code"] == "houdini_offline" and "worker" in no_worker["message"]
        assert Path(cache.replace("$F4", "0001")).is_file()
    finally:
        _stop(state, pids)
