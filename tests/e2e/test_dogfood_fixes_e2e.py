"""Stream D2b end to end on the default ``core`` profile (review 26 P1 #3, #5, #8, #9, #10).

Official MCP client → ``hocuspocus-mcp`` (stdio, ``core``) → headless
``hython -m hocuspocus.host``:

1. the guide and a tool's reference read through ``inspect`` (no resource reader), and an
   argument hint that names that route;
2. a 20 KB VEX snippet read back whole with ``full_strings``, over the response budget;
3. ``recurse_locked`` on ``geo`` ignored with a note;
4. ``cook profile`` leaving a Switch's unselected branch out (``inactive``);
5. ``look`` at a SOP inside a subnet, shown alone, and a Karma look at the size asked.

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

SNIPPET = "\n".join(f"float v{i} = {i} * 0.5; // facade line {i:05d}" for i in range(700))


async def _scenario(rec: Recorder) -> None:
    # 1. docs through inspect ------------------------------------------------------------
    guide = await rec.ok("inspect", {"what": "guide", "target": "spare parm"})
    assert guide["text"].startswith("### Add a spare parm")
    tool = await rec.ok("inspect", {"what": "tool", "target": "edit"})
    assert tool["text"].startswith("## edit") and "**Notes.**" in tool["text"]
    error = await rec.error("edit", {"ops": [{"op": "set", "node": ""}]})
    assert 'inspect {what: "tool", target: "edit"}' in error["hint"], error

    # 2. a long snippet back in full ------------------------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo", "name": "tower"},
                {
                    "op": "create",
                    "parent": "$g",
                    "type": "attribwrangle",
                    "name": "facade",
                    "parms": {"snippet": SNIPPET},
                    "cook": False,
                },
            ]
        },
    )
    parm = "/obj/tower/facade/snippet"
    whole = await rec.ok("inspect", {"what": "parms", "target": parm, "full_strings": True})
    assert whole["parms"][parm] == SNIPPET
    assert whole.get("over_budget") is True  # 20 KB > the 16 KB budget, sent whole

    # 3. an option that only shapes the answer ---------------------------------------------
    noted = await rec.ok(
        "inspect", {"what": "geo", "target": "/obj/tower/facade", "recurse_locked": True}
    )
    assert "recurse_locked does not apply" in noted["notes"][0]

    # 4. cook profile and a Switch --------------------------------------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo", "name": "neo"},
                {"op": "create", "id": "shell", "parent": "$g", "type": "box"},
                {"op": "create", "id": "rooms", "parent": "$g", "type": "sphere"},
                {
                    "op": "create",
                    "id": "dense",
                    "parent": "$g",
                    "type": "subdivide",
                    "parms": {"iterations": 4},
                    "inputs": [{"index": 0, "from": "$rooms"}],
                },
                {
                    "op": "create",
                    "id": "sw",
                    "parent": "$g",
                    "type": "switch",
                    "name": "interiors",
                    "inputs": [{"index": 0, "from": "$shell"}, {"index": 1, "from": "$dense"}],
                },
                {
                    "op": "create",
                    "parent": "$g",
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": "$sw"}],
                    "flags": {"display": True},
                },
            ]
        },
    )
    profile = await rec.ok("cook", {"paths": ["/obj/neo/OUT"], "profile": True})
    assert profile["inactive"]["count"] == 2, profile
    assert "/obj/neo/subdivide1" in profile["inactive"]["paths"]
    assert all("subdivide" not in row["path"] for row in profile["chain"])

    # 5. look at a SOP inside a subnet, and Karma at the size asked ------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "sub", "parent": "/obj/neo", "type": "subnet"},
                {"op": "create", "parent": "$sub", "type": "torus", "name": "core_ring"},
            ]
        },
    )
    alone = await rec.ok("look", {"target": "/obj/neo/subnet1/core_ring", "resolution": [160, 120]})
    assert alone["backend_used"] == "flipbook" and alone["fit_used"] == "target"
    assert any("alone" in note for note in alone["notes"]), alone
    karma = await rec.ok("look", {"quality": "lit", "resolution": [200, 120]})
    assert karma["backend_used"] == "karma" and karma["rendered"] == [200, 120], karma
    after: dict[str, Any] = await rec.ok("search", {"kind": "nodes", "root": "/obj"})
    assert not [n for n in after["nodes"] if "hocuspocus" in n["path"]], after  # no trace


def test_dogfood_fixes_e2e(headless_host, tmp_path):  # noqa: F811 - the fixture above
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
        async with Client(params, read_timeout_seconds=180) as client:
            try:
                await _scenario(Recorder(client))
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    if failures:
        raise failures[0]
