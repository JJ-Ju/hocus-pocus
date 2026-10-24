"""2.1 (D47-D50, review 26 P1): an HDA authored, patched, saved, reinstalled and read back
on the default ``core`` profile with no ``houdini_python``.

Official MCP client → ``hocuspocus-mcp`` (stdio, ``core``) → headless ``hython -m
hocuspocus.host``:

1. ``edit``: geo → subnet → attribwrangle with a long snippet, wired and displayed;
2. ``hda create`` with an interface (tabs, a disable-when rule, a strict range) and help,
   first with a ``.hda`` library: on a non-Commercial licence the error's candidate is the
   path to use, so the second call takes it;
3. ``edit`` ``set`` with ``patch`` changes one line of the snippet inside the asset;
4. ``hda save`` with ``lock: true``; ``hda info`` reads it back;
5. ``hda uninstall`` and ``install`` of the library, then ``hda info`` again from the file.

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import os
import sys

import pytest
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

SNIPPET = "float h = chf('height');\n" + "".join(f"// line {i}\n" for i in range(300))


async def _scenario(rec: Recorder, library_dir: str) -> None:
    built = await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "geo", "path": "/obj/tower", "type": "geo"},
                {"op": "create", "id": "sub", "path": "$geo/tower", "type": "subnet",
                 "flags": {"display": True}},
                {"op": "create", "id": "w", "path": "$sub/facade", "type": "attribwrangle",
                 "parms": {"snippet": SNIPPET, "class": "detail"}},
            ]
        },
    )  # fmt: skip
    subnet = built["ids"]["sub"]
    interface = {
        "add": [
            {"type": "folder", "label": "Massing"},
            {"name": "height", "type": "float", "default": 3.6, "min": 2, "min_strict": True,
             "folder": "Massing"},
            {"name": "interior", "type": "toggle", "default": True, "folder": "Massing"},
            {"name": "core_width", "type": "float", "default": 12, "folder": "Massing",
             "disable_when": "{ interior == 0 }"},
        ]
    }  # fmt: skip
    create = {
        "action": "create",
        "path": subnet,
        "name": "hpe2e::tower::1.0",
        "label": "E2E Tower",
        "library_path": f"{library_dir}/tower.hda",
        "interface": interface,
        "help": "= E2E Tower =\nA test tower.",
    }
    is_error, made = await rec.call("hda", create)
    if is_error:  # not a Commercial licence: the candidate is the licence's extension
        assert made["code"] == "invalid_argument" and made["candidates"], made
        create["library_path"] = made["candidates"][0]
        made = await rec.ok("hda", create)
    library = create["library_path"]
    assert made["promoted"] == ["core_width", "height", "interior"], made
    assert made["hda_locked"] is False
    patched = await rec.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "set",
                    "path": f"{subnet}/facade/snippet",
                    "patch": {"find": "chf('height')", "replace": "chf('../height')"},
                }
            ],
            "return": "ops",
        },
    )
    assert patched["results"][0]["patched_lines"] == [1], patched
    saved = await rec.ok("hda", {"action": "save", "path": subnet, "lock": True})
    assert saved["hda_locked"] is True, saved
    info = await rec.ok("hda", {"action": "info", "path": subnet})
    assert info["type"] == "Sop/hpe2e::tower::1.0" and info["label"] == "E2E Tower", info
    assert "HelpText" in info["sections"], info
    assert info["interface"] == {"parms": 3, "folders": ["Massing"]}, info
    assert info["instance"]["matches_definition"] is True, info
    gone = await rec.ok("hda", {"action": "uninstall", "library_path": library})
    assert subnet in gone["instances"], gone
    await rec.ok("hda", {"action": "install", "library_path": library})
    again = await rec.ok("hda", {"action": "info", "name": "Sop/hpe2e::tower::1.0"})
    assert again["interface"] == info["interface"], again
    assert again["help_chars"] == info["help_chars"], again
    parms = await rec.ok(
        "inspect",
        {
            "what": "parms",
            "target": f"{subnet}/facade/snippet",
            "full_strings": True,
        },
    )
    snippet = next(iter(parms["parms"].values()))
    snippet = snippet["value"] if isinstance(snippet, dict) else snippet
    assert snippet.startswith("float h = chf('../height');"), snippet[:80]


def test_hda_authoring_on_core(headless_host, tmp_path):  # noqa: F811 - the fixture above
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
    recorders: list[Recorder] = []
    failures: list[BaseException] = []
    library_dir = (tmp_path / "otls").as_posix()

    async def run() -> None:
        async with Client(params, read_timeout_seconds=180) as client:
            listed = {tool.name for tool in (await client.list_tools()).tools}
            assert "hda" in listed and "pdg" not in listed, listed  # core (D47)
            rec = Recorder(client)
            recorders.append(rec)
            try:
                await _scenario(rec, library_dir)
            except AssertionError as exc:
                failures.append(exc)

    anyio.run(run)
    rec = recorders[0]
    if failures:
        raise AssertionError(f"{failures[0]}\ncalls so far:\n{rec.report()}") from failures[0]
    print(f"\n[hda_authoring_e2e] {len(rec.calls)} calls, {rec.total_bytes} bytes\n{rec.report()}")
    assert "houdini_python" not in {name for name, _size, _err in rec.calls}
