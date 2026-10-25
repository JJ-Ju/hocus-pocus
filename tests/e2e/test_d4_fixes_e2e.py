"""Stream D4 end to end on the default ``core`` profile (review 26 P3, review 28).

Official MCP client → ``hocuspocus-mcp`` (stdio, ``core``) → headless
``hython -m hocuspocus.host`` with ``job_threshold_s`` at 1 s:

1. a 4 s button press answers as a job (D70); a call that waits behind it answers
   ``houdini_busy`` naming the press and the job's ledger id; the job cannot be cancelled
   and its result is the press's row;
2. ``inspect geo`` with ``group_by``, ``attribs`` as a string, and ``stats`` on the
   summary (D71, D76);
3. a menu value ranked to its label (``volume`` finds ``atmosphere``, D72);
4. ``hda version`` with ``switch`` (D73);
5. a Karma ``render`` as a job while other calls still get the main thread (D74), and a
   final ``look`` past ``wait_s`` as a job whose result is the picture (D75).

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import pytest
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e


async def _job(rec: Recorder, job_id: str, timeout: float = 120.0) -> dict[str, Any]:
    import anyio

    deadline = time.monotonic() + timeout
    while True:
        status = await rec.ok("job", {"action": "result", "job_id": job_id})
        if status["state"] != "running" or time.monotonic() > deadline:
            return status
        await anyio.sleep(0.2)


async def _scenario(rec: Recorder, work: str) -> None:
    # 1. a long press ------------------------------------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "n", "parent": "/obj", "type": "null", "name": "exporter"},
                {
                    "op": "node",
                    "path": "$n",
                    "spare_parms": {
                        "add": [
                            {"name": "count", "type": "int", "default": 0},
                            {
                                "name": "export_all",
                                "type": "button",
                                "label": "Export All",
                                "callback": "import time; time.sleep(4); "
                                "hou.pwd().parm('count').set(1)",
                            },
                        ]
                    },
                },
            ]
        },
    )
    pressed = await rec.ok(
        "parm_set", {"items": [{"path": "/obj/exporter/export_all", "press": True}]}
    )
    assert pressed["state"] == "running", pressed
    assert pressed["running"] == "/obj/exporter/export_all"
    job_id = pressed["job_id"]
    assert job_id.startswith("j"), job_id  # the ledger's id
    busy = await rec.error("houdini_python", {"code": "1", "timeout_s": 1})
    assert busy["code"] == "houdini_busy", busy
    assert busy["detail"]["running"] == "/obj/exporter/export_all"
    assert busy["detail"]["job_id"] == job_id
    cancel = await rec.ok("job", {"action": "cancel", "job_id": job_id})
    assert cancel["cancelled"] is False
    done = await _job(rec, job_id)
    assert done["state"] == "done", done
    (row,) = done["result"]["results"]
    assert row["pressed"] is True and row["side_effects"] == {"count": [0, 1]}

    # 2. geometry analytics ----------------------------------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo", "name": "tower"},
                {"op": "create", "id": "box", "parent": "$g", "type": "box"},
                {
                    "op": "create",
                    "parent": "$g",
                    "type": "attribwrangle",
                    "name": "OUT",
                    "inputs": [{"from": "$box"}],
                    "parms": {
                        "class": "primitive",
                        "snippet": 's@surface = @primnum < 4 ? "glass" : "wall"; '
                        "f@streak = @primnum;",
                    },
                },
            ]
        },
    )
    target = "/obj/tower/OUT"
    grouped = await rec.ok(
        "inspect", {"what": "geo", "target": target, "group_by": "surface", "attribs": "streak"}
    )
    rows = {row[0]: row for row in grouped["rows"]}
    assert grouped["columns"][:5] == ["value", "prims", "points", "triangles", "area"]
    assert rows["glass"][1:4] == [4, 8, 8] and rows["wall"][1:4] == [2, 8, 4]
    assert grouped["columns"][-3:] == ["streak.min", "streak.max", "streak.mean"]
    assert rows["wall"][-3:] == [4.0, 5.0, 4.5]
    summary = await rec.ok("inspect", {"what": "geo", "target": target, "stats": True})
    assert summary["stats"]["prim"]["streak"] == {"min": 0.0, "max": 5.0, "mean": 2.5}

    # 3. a menu value found by its label ---------------------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "m", "parent": "/obj", "type": "matnet", "name": "mat"},
                {"op": "create", "id": "s", "parent": "$m", "type": "subnet", "name": "shader"},
                {"op": "create", "parent": "$s", "type": "subnetconnector", "name": "vol"},
            ]
        },
    )
    error = await rec.error(
        "edit",
        {"ops": [{"op": "set", "path": "/obj/mat/shader/vol/parmtype", "value": "volume"}]},
    )
    assert error["code"] == "invalid_value" and error["candidates"][0] == "atmosphere", error

    # 4. an asset version -------------------------------------------------------------------
    await rec.ok(
        "edit", {"ops": [{"op": "create", "parent": "/obj/tower", "type": "subnet", "name": "kit"}]}
    )
    ext = (await rec.ok("houdini_python", {"code": "hou.hda.defaultFileExtension()"}))["result"]
    library = f"{work}/otls/kit{ext}"
    made = await rec.ok(
        "hda",
        {
            "action": "create",
            "path": "/obj/tower/kit",
            "name": "hpe2e::kit::1.0",
            "library_path": library,
        },
    )
    bumped = await rec.ok(
        "hda", {"action": "version", "path": made["path"], "version": "1.1", "switch": "path"}
    )
    assert bumped["type"] == "Sop/hpe2e::kit::1.1" and bumped["switched"] == [made["path"]]

    # 5. Karma off the main thread, and a look as a job -------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "parent": "/obj", "type": "hlight::2.0", "name": "key",
                 "parms": {"t": [3, 4, 5]}},
                {"op": "create", "parent": "/obj", "type": "cam", "name": "cam1",
                 "parms": {"t": [0, 0, 5]}},
                {"op": "create", "parent": "/out", "type": "karma", "name": "beauty",
                 "parms": {"camera": "/obj/cam1", "resolutionx": 640, "resolutiony": 360,
                           "samplesperpixel": 64,
                           "picture": f"{work}/render/beauty.$F4.exr"}},
            ]
        },
    )  # fmt: skip
    render = await rec.ok("render", {"rop_path": "/out/beauty", "frames": [1, 3, 1], "wait_s": 0})
    assert render["state"] == "running", render
    started = time.monotonic()
    read = await rec.ok("inspect", {"what": "node", "target": "/out/beauty"})
    assert read["nodes"][0]["path"] == "/out/beauty"
    assert time.monotonic() - started < 3.0  # the main thread was free
    rendered = await _job(rec, render["job_id"], timeout=300)
    assert rendered["state"] == "done", rendered
    assert len(rendered["result"]["outputs"]) == 3
    looked = await rec.ok("look", {"quality": "final", "resolution": [320, 180], "wait_s": 0})
    assert looked["state"] == "running" and looked["job_id"].startswith("j"), looked
    picture = await _job(rec, looked["job_id"])
    assert picture["state"] == "done" and picture["result"]["backend_used"] == "karma"


@pytest.fixture
def fast_jobs(monkeypatch):
    """Listed before headless_host so the host starts with a 1 s job threshold."""
    monkeypatch.setenv("HOCUSPOCUS_JOB_THRESHOLD_S", "1")


def test_d4_fixes_e2e(fast_jobs, headless_host, tmp_path):  # noqa: F811 - the fixture above
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    _proc, state = headless_host
    env = dict(os.environ)
    env.pop("HOCUSPOCUS_PROFILE", None)  # the default profile, core
    env.update(
        {
            "HOCUSPOCUS_STATE_DIR": str(state),
            "PYTHONPATH": str(SRC),
            "HOUDINI_USER_PREF_DIR": (tmp_path / "bridge-prefs" / "houdini__HVER__").as_posix(),
        }
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
    )
    failures: list[BaseException] = []

    async def run() -> None:
        async with Client(params, read_timeout_seconds=300) as client:
            try:
                await _scenario(Recorder(client), (tmp_path / "work").as_posix())
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    if failures:
        raise failures[0]
