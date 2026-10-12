"""M1 exit criterion (docs/BIBLE.md §14): review 06 tasks 2, 3, 4, 6 and 9 end to end.

Official MCP client → ``hocuspocus-mcp`` (stdio) → headless ``hython -m hocuspocus.host``.
Every tool call goes through the real bridge (argument validation, response shaping) and
the real host. The scenario counts its tool calls and the bytes of every response's
content and asserts both budgets (≤ 14 calls, ≤ 40 KB); both are printed (run with ``-s`` to see them on success).

Tasks (docs/redesign/review/06-hands-on-friction-log.md):

2. geo → box → mountain (height 0.5, ``$F*0.1`` on offset's first component) → subdivide
   → null OUT with the display flag, wired and laid out, in one ``node_create`` batch.
3. Read it back: ``node_info`` (evaluated and raw parms, inputs, errors) and ``geo_info``
   on OUT (skipped with a message while ``geo_info`` is not implemented).
4. ``time`` frame 24, then ``parm_get`` shows the animated parm at 2.4.
6. ``node_type_search`` for scatter and copy to points, build scatter + sphere +
   copytopoints in one batch, verify with ``cook``.
9. Deliberate mistakes: bad type, bad parm, wire to input 7. Each is an ``isError``
   result with a code and candidates or labels, never a protocol error.

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
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

pytestmark = pytest.mark.e2e

SRC = Path(__file__).resolve().parents[2] / "src"
REGISTER_TIMEOUT_S = 180.0
MAX_CALLS = 14
MAX_BYTES = 40_000

GEO = "/obj/terrain"


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


def _parm(block: dict[str, Any], name: str) -> dict[str, Any]:
    for row in block.get("parms", []):
        if row.get("name") == name:
            return row
    raise AssertionError(f"parm {name} not in {[r.get('name') for r in block.get('parms', [])]}")


async def _scenario(rec: Recorder, notes: list[str]) -> None:
    # -- Task 2: build the chain in one call -------------------------------------------
    built = await rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "terrain"},
                {"parent": GEO, "type": "box"},
                {
                    "parent": GEO,
                    "type": "mountain",
                    "inputs": [{"index": 0, "from": f"{GEO}/box1"}],
                    "parms": {"height": 0.5, "offsetx": {"expr": "$F*0.1"}},
                },
                {
                    "parent": GEO,
                    "type": "subdivide",
                    "inputs": [{"index": 0, "from": f"{GEO}/mountain1"}],
                },
                {
                    "parent": GEO,
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": f"{GEO}/subdivide1"}],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    paths = [r["path"] for r in built["results"]]
    assert paths == [GEO, f"{GEO}/box1", f"{GEO}/mountain1", f"{GEO}/subdivide1", f"{GEO}/OUT"]

    # -- Task 3: read it back ----------------------------------------------------------
    info = await rec.ok(
        "node_info",
        {
            "paths": [f"{GEO}/mountain1", f"{GEO}/OUT"],
            "include": ["parms", "inputs", "errors", "flags", "position"],
        },
    )
    mountain, out = info["nodes"]
    assert _parm(mountain, "height")["value"] == pytest.approx(0.5)
    # node_info reports tuples: offset carries raw/value lists and per-component expressions.
    offset = _parm(mountain, "offset")
    assert offset["raw"][0] == "$F*0.1", offset
    assert offset["value"][0] == pytest.approx(0.1), offset  # evaluated at frame 1
    assert "$F*0.1" in json.dumps(offset.get("expressions")), offset
    assert mountain["inputs"][0]["from"]["path"] == f"{GEO}/box1"
    assert out["inputs"][0]["from"]["path"] == f"{GEO}/subdivide1"
    assert out["flags"]["display"] is True
    assert mountain["errors"] == [] and out["errors"] == []
    # Laid out: distinct positions, flowing downwards from mountain to OUT.
    assert out["position"] != mountain["position"]
    assert out["position"][1] < mountain["position"][1]

    is_error, geo = await rec.call("geo_info", {"path": f"{GEO}/OUT"})
    if is_error:
        notes.append(f"geo_info step skipped: {geo.get('code')}: {geo.get('message')}")
    else:
        assert geo["point_count"] > 0 and geo["prim_count"] > 0
        assert geo["bbox"]["size"][0] > 0
        assert any(a["name"] == "P" for a in geo["attributes"]["point"])

    # -- Task 4: frame 24 and re-read --------------------------------------------------
    t = await rec.ok("time", {"frame": 24})
    assert t["frame"] == 24
    parms = await rec.ok("parm_get", {"paths": [f"{GEO}/mountain1/offsetx"]})
    (row,) = parms["parms"]
    assert row["value"] == pytest.approx(2.4)
    assert row["raw"] == "$F*0.1"

    # -- Task 6: discovery, scatter + copy to points -----------------------------------
    scatter = await rec.ok("node_type_search", {"query": "scatter", "category": "Sop", "limit": 5})
    names = [r["name"] for r in scatter["results"]]
    assert names[0].split("::")[0] == "scatter", names
    copy = await rec.ok(
        "node_type_search", {"query": "copy to points", "category": "Sop", "limit": 5}
    )
    copy_names = [r["name"] for r in copy["results"]]
    assert any(n.split("::")[0] == "copytopoints" for n in copy_names[:3]), copy_names

    made = await rec.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": GEO,
                    "type": "scatter",
                    "inputs": [{"index": 0, "from": f"{GEO}/OUT"}],
                    "parms": {"npts": 200},
                },
                {"parent": GEO, "type": "sphere", "parms": {"scale": 0.05}},
                {
                    "parent": GEO,
                    "type": "copytopoints",
                    "inputs": [
                        {"index": 0, "from": f"{GEO}/sphere1"},
                        {"index": 1, "from": f"{GEO}/scatter1"},
                    ],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    copy_path = made["results"][2]["path"]
    cooked = await rec.ok("cook", {"paths": [copy_path]})
    assert cooked["ok"] is True, cooked
    assert cooked["results"][0]["errors"] == []

    # -- Task 9: deliberate mistakes ---------------------------------------------------
    bad_type = await rec.error("node_create", {"items": [{"parent": GEO, "type": "mountian"}]})
    assert bad_type["code"] == "node_type_not_found"
    assert bad_type["candidates"][0].split("::")[0] == "mountain", bad_type

    bad_parm = await rec.error("parm_set", {"items": [{"path": f"{GEO}/box1/sizee", "value": 2}]})
    assert bad_parm["code"] == "parm_not_found"
    assert any("size" in c for c in bad_parm["candidates"]), bad_parm

    bad_input = await rec.error(
        "node_connect", {"items": [{"from": f"{GEO}/box1", "to": f"{GEO}/OUT", "to_input": 7}]}
    )
    assert bad_input["code"] == "invalid_input"
    assert "Input 1" in bad_input.get("hint", ""), bad_input  # lists the input labels


def test_scenario_authoring(headless_host, tmp_path):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    _proc, state = headless_host
    env = dict(os.environ)
    env.update({"HOCUSPOCUS_STATE_DIR": str(state), "PYTHONPATH": str(SRC)})
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hocuspocus.bridge"],
        env=env,
        cwd=str(tmp_path),
    )
    notes: list[str] = []
    recorders: list[Recorder] = []

    failures: list[BaseException] = []

    async def run() -> None:
        async with Client(params, read_timeout_seconds=180) as client:
            rec = Recorder(client)
            recorders.append(rec)
            try:
                await _scenario(rec, notes)
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    rec = recorders[0]
    if failures:
        raise AssertionError(f"{failures[0]}\ncalls so far:\n{rec.report()}") from failures[0]
    summary = (
        f"\n[scenario_authoring] {len(rec.calls)} tool calls, {rec.total_bytes} response bytes\n"
        + rec.report()
        + "".join(f"\n  note: {n}" for n in notes)
    )
    print(summary)  # shown with -s, and in the report when an assertion fails
    assert len(rec.calls) <= MAX_CALLS, summary
    assert rec.total_bytes <= MAX_BYTES, summary
