"""Stream D5 end to end on the default ``core`` profile (review 28 r21 frictions 2-6, 8).

Official MCP client -> ``hocuspocus-mcp`` (stdio, ``core``) -> headless
``hython -m hocuspocus.host``:

1. a Python SOP that warned about a node created later: ``problems`` names it, ``cook
   {force: true}`` leaves the input stale and says so, ``cook {force: "chain"}`` (the
   bridge validates the mixed enum) recooks it (D81);
2. a File COP whose PNG is overwritten: ``look`` notes the stale image, ``cook {force:
   true}`` presses Reload (D80), and ``look {output: .jpg, jpeg_quality}`` sizes the JPEG
   (D86; a quality outside 1-100 is refused by the bridge's schema check);
3. a comma glob on ``inspect parms`` (D85).

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import os
import struct
import sys
import time
import zlib
from pathlib import Path

import pytest
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

PROBE = """
node = hou.pwd()
found = hou.node("/obj/later") is not None
node.geometry().addAttrib(hou.attribType.Global, "found", 0)
node.geometry().setGlobalAttribValue("found", int(found))
if not found:
    node.addWarning('The node "/obj/later" was not found.')
"""


def _png(path: Path, rgb: tuple[int, int, int], when: float, size: int = 64) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(
        b"\x00" + b"".join(bytes(((rgb[0] + x * 7) % 256, rgb[1], (rgb[2] + y * 5) % 256))
                           for x in range(size))
        for y in range(size)
    )  # fmt: skip
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
    path.write_bytes(data + chunk(b"IEND", b""))
    os.utime(path, (when, when))


async def _found(rec: Recorder) -> int:
    geo = await rec.ok("inspect", {"what": "geo", "target": "/obj/net/OUT"})
    return geo["attributes"]["detail"]["found"]["value"]


async def _scenario(rec: Recorder, tmp_path: Path) -> None:
    # 1. an input cooked before the node it looks for existed -----------------------------
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "path": "/obj/net", "type": "geo"},
                {"op": "create", "id": "p", "parent": "$g", "type": "python", "name": "probe",
                 "parms": {"python": PROBE}},
                {"op": "create", "parent": "$g", "type": "null", "name": "OUT",
                 "inputs": [{"from": "$p"}]},
            ]
        },
    )  # fmt: skip
    await rec.ok("cook", {"paths": ["/obj/net/OUT"]})
    await rec.ok("edit", {"ops": [{"op": "create", "path": "/obj/later", "type": "geo"}]})
    scan = await rec.ok("inspect", {"what": "problems", "target": "/obj/net"})
    (row,) = [r for r in scan["problems"] if r["path"] == "/obj/net/probe"]
    assert "/obj/later exists now" in row["hint"], row
    forced = await rec.ok("cook", {"paths": ["/obj/net/OUT"], "force": True})
    assert 'force: "chain"' in forced["results"][0].get("hint", ""), forced
    assert await _found(rec) == 0
    chained = await rec.ok("cook", {"paths": ["/obj/net/OUT"], "force": "chain"})
    assert chained["results"][0]["inputs_cooked"] == 1, chained
    assert await _found(rec) == 1
    wrong = await rec.error("cook", {"paths": ["/obj/net/OUT"], "force": "inputs"})
    assert wrong["code"] == "invalid_argument", wrong

    # 2. a File COP and its file on disk ---------------------------------------------------
    png = tmp_path / "plate.png"
    now = time.time()
    _png(png, (200, 30, 30), now - 60)
    plate = png.as_posix()
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "net", "path": "/img/plates", "type": "copnet"},
                {"op": "create", "parent": "$net", "type": "file", "name": "plate",
                 "parms": {"filename": plate}},
                {"op": "set", "path": "/img/plates/plate", "parms": {"addaovs": {"press": True}}},
            ]
        },
    )  # fmt: skip
    first = await rec.ok("look", {"target": "/img/plates/plate"})
    assert not [n for n in first.get("notes", []) if "older copy" in n], first
    _png(png, (30, 30, 200), now)
    stale = await rec.ok("look", {"target": "/img/plates/plate"})
    assert any("older copy" in n and plate in n for n in stale.get("notes", [])), stale
    reloaded = await rec.ok("cook", {"paths": ["/img/plates/plate"], "force": True})
    assert reloaded["results"][0]["reloaded"] is True, reloaded
    sizes = {}
    for quality in (5, 95):
        out = await rec.ok(
            "look",
            {"target": "/img/plates/plate", "output": f"$HIP/evidence/q{quality}.jpg",
             "jpeg_quality": quality},
        )  # fmt: skip
        assert not [n for n in out.get("notes", []) if "older copy" in n], out
        sizes[quality] = out["output_bytes"]
        assert Path(out["output"]).stat().st_size == out["output_bytes"]
    assert sizes[5] < sizes[95], sizes
    bad = await rec.error(
        "look", {"target": "/img/plates/plate", "output": "$HIP/x.jpg", "jpeg_quality": 0}
    )
    assert bad["code"] == "invalid_argument", bad

    # 3. a comma glob ----------------------------------------------------------------------
    parms = await rec.ok(
        "inspect",
        {"what": "parms", "target": "/obj/later", "parms": "t, r", "include_defaults": True},
    )
    assert list(parms["parms"]) == ["t", "r"], parms


def test_stale_reads_e2e(headless_host, tmp_path):  # noqa: F811 - the fixture above
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
                await _scenario(Recorder(client), tmp_path)
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    if failures:
        raise failures[0]
