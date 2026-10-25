"""M3: the 1.4 authoring scenario's build with the 2.0 tools only (spec-2.0 §2.3-§2.5).

Official MCP client → ``hocuspocus-mcp`` (stdio, the default ``core`` profile) → headless
``hython -m hocuspocus.host``. The same scene as the 1.4 scenario (review 06 tasks 2, 3, 4,
6 and 9), with ``edit``, ``inspect`` and ``look`` and nothing else:

1. ``edit``: geo → box → mountain (height 0.5, ``$F*0.1`` on offset's first component) →
   subdivide → null OUT, then scatter + sphere + copytopoints, wired and displayed, in one
   undo step;
2. ``inspect what: node`` reads mountain and OUT back (inputs, errors, flags, position);
3. ``inspect what: parms`` at frame 24 shows the animated parm at 2.4 (the 1.4 scenario
   needed ``time`` and ``parm_get``);
4. ``inspect what: geo`` on the copies: points and the P attribute, so the chain cooks;
5. a deliberate mistake: ``edit`` with a misspelt type and ``dry_run`` is an ``isError``
   result with the right candidate, and changes nothing;
6. ``look`` draft at a thumbnail size.

Budgets: at most 6 calls and 8 KB of response content (the 1.4 scenario: 14 calls, 40 KB).
Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

# The scenarios' hython fixtures and recorder (tests/e2e is on sys.path under pytest's
# default import mode); headless_host and hython are fixtures, used by name below.
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

MAX_CALLS = 6
MAX_BYTES = 8_000
GEO = "/obj/terrain"


async def _scenario(rec: Recorder) -> None:
    # -- 1. the whole build, one undo step ------------------------------------------------
    built = await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
                {"op": "create", "id": "box", "parent": "$geo", "type": "box"},
                {
                    "op": "create",
                    "id": "mtn",
                    "parent": "$geo",
                    "type": "mountain",
                    "inputs": [{"index": 0, "from": "$box"}],
                    "parms": {"height": 0.5, "offsetx": {"expr": "$F*0.1"}},
                },
                {
                    "op": "create",
                    "id": "sub",
                    "parent": "$geo",
                    "type": "subdivide",
                    "inputs": [{"index": 0, "from": "$mtn"}],
                },
                {
                    "op": "create",
                    "id": "out",
                    "parent": "$geo",
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": "$sub"}],
                },
                {
                    "op": "create",
                    "id": "scatter",
                    "parent": "$geo",
                    "type": "scatter",
                    "inputs": [{"index": 0, "from": "$out"}],
                    "parms": {"npts": 200},
                },
                {
                    "op": "create",
                    "id": "sphere",
                    "parent": "$geo",
                    "type": "sphere",
                    "parms": {"scale": 0.05},
                },
                {
                    "op": "create",
                    "id": "copy",
                    "parent": "$geo",
                    "type": "copytopoints",
                    "inputs": [{"index": 0, "from": "$sphere"}, {"index": 1, "from": "$scatter"}],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    paths = list(built["ids"].values())
    assert paths[:5] == [GEO, f"{GEO}/box1", f"{GEO}/mountain1", f"{GEO}/subdivide1", f"{GEO}/OUT"]
    copy_path = built["ids"]["copy"]
    assert copy_path == f"{GEO}/copytopoints1", paths
    assert all(not node.get("errors") for node in built["nodes"]), built["nodes"]

    # -- 2. read the chain back -------------------------------------------------------------
    read = await rec.ok(
        "inspect",
        {
            "what": "node",
            "paths": [f"{GEO}/mountain1", f"{GEO}/OUT"],
            "include": ["inputs", "errors", "flags", "position"],
        },
    )
    mountain, out = read["nodes"]
    assert mountain["inputs"] == [f"{GEO}/box1"]  # compact: positional sources
    assert out["inputs"] == [f"{GEO}/subdivide1"]
    assert "errors" not in mountain and "errors" not in out  # compact: empty left out
    assert out["position"] != mountain["position"]  # laid out
    assert out["position"][1] < mountain["position"][1]  # flowing downwards

    # -- 3. the animated parm at frame 24, no time call -------------------------------------
    parms = await rec.ok(
        "inspect",
        {"what": "parms", "target": f"{GEO}/mountain1", "parms": "height|offset", "frame": 24},
    )
    assert parms["parms"]["height"] == pytest.approx(0.5)  # compact: {name: value}
    offset = parms["parms"]["offset"]
    assert offset["expressions"]["offsetx"] == "$F*0.1", offset
    assert offset["value"][0] == pytest.approx(2.4), offset

    # -- 4. the copies cook -----------------------------------------------------------------
    geo = await rec.ok("inspect", {"what": "geo", "target": copy_path, "attributes": "names"})
    assert geo["point_count"] > 0 and geo["prim_count"] > 0, geo
    assert "P" in json_names(geo["attributes"]["point"]), geo["attributes"]

    # -- 5. a deliberate mistake, validated before anything changes -------------------------
    bad = await rec.error(
        "edit",
        {"ops": [{"op": "create", "parent": GEO, "type": "mountian"}], "dry_run": True},
    )
    assert bad["code"] == "node_type_not_found", bad
    assert bad["candidates"][0].split("::")[0] == "mountain", bad

    # -- 6. one look --------------------------------------------------------------------------
    look = await rec.ok("look", {"target": copy_path, "quality": "draft", "resolution": [64, 48]})
    assert look["width"] == 64 and look["height"] == 48, look
    assert look["backend_used"], look


def json_names(rows: Any) -> list[str]:
    """Attribute names from ``attributes: names`` (strings) or full rows (``{name}``)."""
    return [row if isinstance(row, str) else row.get("name") for row in rows]


def test_scenario_authoring_v2(headless_host, tmp_path):  # noqa: F811 - the fixture above
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
            # Never the user's real pref dir (and its hocuspocus.toml) for the bridge.
            "HOUDINI_USER_PREF_DIR": (tmp_path / "bridge-prefs" / "houdini__HVER__").as_posix(),
        }
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
    )
    recorders: list[Recorder] = []
    listed: list[str] = []
    failures: list[BaseException] = []

    async def run() -> None:
        async with Client(params, read_timeout_seconds=180) as client:
            listed.extend(tool.name for tool in (await client.list_tools()).tools)
            rec = Recorder(client)
            recorders.append(rec)
            try:
                await _scenario(rec)
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    rec = recorders[0]
    if failures:
        raise AssertionError(f"{failures[0]}\ncalls so far:\n{rec.report()}") from failures[0]
    summary = (
        f"\n[scenario_authoring_v2] {len(rec.calls)} tool calls, {rec.total_bytes} response "
        "bytes\n" + rec.report()
    )
    print(summary)  # shown with -s, and in the report when an assertion fails
    assert len(listed) == 19 and {"edit", "inspect", "look"} <= set(listed), listed  # core
    assert "node_info" not in listed
    assert {name for name, _size, _err in rec.calls} == {"edit", "inspect", "look"}, summary
    assert len(rec.calls) <= MAX_CALLS, summary
    assert rec.total_bytes <= MAX_BYTES, summary
