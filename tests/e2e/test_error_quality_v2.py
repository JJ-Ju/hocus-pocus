"""Review 25 task 9 as a test: deliberate mistakes on the default ``core`` profile.

Official MCP client → ``hocuspocus-mcp`` (stdio, ``core``, no profile set) → headless
``hython -m hocuspocus.host``. Every mistake must answer ``isError`` with a code, and every
``message`` and ``hint`` must name only tools ``core`` lists (review 25 papercut 1: the 2.0
server's hints sent the agent to ``node_find``, ``node_type_info``, ``node_type_search``, "the
problems tool" and ``viewport_capture``, which ``core`` refuses). Where the mistake has one
right call, the hint shows it and the test makes that call:

1. a misspelt type (``edit`` create ``mountian``): the type search;
2. a misspelt parm, at create and on a node: the type read and the tuple's components;
3. a bad input index, a missing wiring source and a value of the wrong type: located at
   the op field (``ops[0].to_input``, ``ops[0].from``, ``ops[0].value``; papercut 3), the
   source's candidates never the target itself;
4. a flat ``edit`` op and an ``ops`` object: the call with the op inside ``ops``;
5. 1.4 tool names (``node_info``, ``node_find``, ``viewport_capture``): the 2.0 replacement;
6. 1.4 ``inspect`` arguments (``path``, ``node_path``; papercut 2): the ``target`` call;
7. made-up job ids (papercut 5): a ledger-form ``jzzzz`` is answered about the ledger, a
   ``<pid>-<id>`` about an unknown Houdini;
8. and the rest of the task-9 set whose hints named tools: a cook error read through
   ``inspect geo``, a missing ``look`` camera, a ROP without its camera, ``hip_new`` on
   an untitled scene (papercut 9);
9. an argument the schema does not have (2.1 stream F): ``render {frame_range}`` is
   ``invalid_argument`` naming the key, with ``frames`` as the candidate and a hint that
   names ``inspect {what: "tool", target: "render"}``; the same nested (``houdini_connect``
   ``launch``, ``edit`` ``ops[0]``).

Never uses port 37219; hython runs from a neutral cwd with isolated state and pref dirs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import pytest

# The scenarios' hython fixtures and recorder (tests/e2e is on sys.path under pytest's
# default import mode); headless_host and hython are fixtures, used by name below.
from scenario_host import SRC, Recorder, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

GEO = "/obj/terrain"
ALL_TOOLS: frozenset[str] = frozenset()


def named_tools(text: str, every: frozenset[str]) -> set[str]:
    """Tool names ``text`` uses: a snake_case name always; a one-word name (cook, look,
    job, ...) only as a call, followed by ``{`` or by ``tool`` (as in
    ``tests/unit/test_hint_profiles.py``)."""
    found: set[str] = set()
    for match in re.finditer(r"\b[a-z_]+\b", text):
        word = match.group(0)
        rest = text[match.end() :]
        if word in every and (
            "_" in word or re.match(r"\s*\{", rest) or re.match(r"\s+tool\b", rest)
        ):
            found.add(word)
    return found


class Checker:
    """Runs each mistake and checks its texts against the profile's listing."""

    def __init__(self, rec: Recorder, listed: set[str], every: frozenset[str]) -> None:
        self.rec, self.listed, self.every = rec, listed, every
        self.errors: list[tuple[str, dict[str, Any]]] = []

    async def mistake(self, tool: str, args: dict[str, Any], code: str) -> dict[str, Any]:
        error = await self.rec.error(tool, args)
        assert error["code"] == code, (tool, args, error)
        allowed = self.listed | ({tool} if "1.4 tool" in error["message"] else set())
        for key in ("message", "hint"):
            outside = named_tools(str(error.get(key) or ""), self.every) - allowed
            assert not outside, f"{tool} {args}: {key} names {sorted(outside)}: {error[key]}"
        self.errors.append((tool, error))
        return error


def _after(text: str, marker: str) -> dict[str, Any]:
    return json.loads(text.split(marker, 1)[1].rstrip("."))


async def _scenario(check: Checker) -> None:
    rec = check.rec
    await rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo", "name": "terrain"},
                {"op": "create", "id": "b", "parent": "$g", "type": "box"},
                {
                    "op": "create",
                    "id": "c",
                    "parent": "$g",
                    "type": "copytopoints",
                    "name": "copy1",
                },
                {
                    "op": "create",
                    "parent": "$g",
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": "$b"}],
                    "flags": {"display": True},
                },
                {"op": "create", "parent": "/obj", "type": "cam", "name": "cam1"},
            ]
        },
    )

    # 1. a misspelt type -----------------------------------------------------------------------
    bad_type = await check.mistake(
        "edit",
        {"ops": [{"op": "create", "parent": GEO, "type": "mountian"}]},
        "node_type_not_found",
    )
    assert bad_type["candidates"][0] == "mountain"
    assert bad_type["message"].startswith("ops[0].type: ")
    assert 'search {kind: "types", query: "mountian"}' in bad_type["hint"]

    # 2. misspelt parms --------------------------------------------------------------------------
    at_create = await check.mistake(
        "edit",
        {"ops": [{"op": "create", "parent": GEO, "type": "box", "parms": {"sizee": 3}}]},
        "parm_not_found",
    )
    assert at_create["message"].startswith("ops[0].parms.sizee: ")
    assert "size" in at_create["candidates"]
    assert 'inspect {what: "type", target: "Sop/box"}' in at_create["hint"]
    on_node = await check.mistake(
        "edit", {"ops": [{"op": "set", "path": f"{GEO}/box1/sizee", "value": 3}]}, "parm_not_found"
    )
    assert (
        on_node["message"].startswith("ops[0].path: ") and "Did you mean size?" in on_node["hint"]
    )

    # 3. located at the op field -----------------------------------------------------------------
    bad_input = await check.mistake(
        "edit",
        {"ops": [{"op": "connect", "from": f"{GEO}/box1", "to": f"{GEO}/OUT", "to_input": 5}]},
        "invalid_input",
    )
    assert bad_input["message"].startswith("ops[0].to_input: ")
    missing = await check.mistake(
        "edit",
        {"ops": [{"op": "connect", "from": f"{GEO}/nope", "to": f"{GEO}/copy1", "to_input": 0}]},
        "node_not_found",
    )
    assert missing["message"] == f"ops[0].from: No node at {GEO}/nope."
    assert f"{GEO}/copy1" not in missing.get("candidates", [])  # never the wire's target
    assert f'search {{kind: "nodes", root: "{GEO}"}}' in missing["hint"]
    tall = await check.mistake(
        "edit",
        {"ops": [{"op": "set", "path": f"{GEO}/box1/sizex", "value": "tall"}]},
        "invalid_value",
    )
    assert tall["message"].startswith("ops[0].value: ")
    assert 'edit {ops: [{op: "set", path, expression}]}' in tall["hint"]

    # 4. a flat edit op, and ops as an object ----------------------------------------------------
    op = {"op": "set", "path": f"{GEO}/box1/sizex", "value": 2}
    flat = await check.mistake("edit", dict(op), "invalid_argument")
    fixed = _after(flat["hint"], "pass the op inside ops: ")
    assert fixed == {"ops": [op]}
    as_object = await check.mistake("edit", {"ops": dict(op)}, "invalid_argument")
    assert _after(as_object["hint"], "pass the op inside ops: ") == {"ops": [op]}
    await rec.ok("edit", fixed)  # the corrected call works

    # 5. 1.4 tool names --------------------------------------------------------------------------
    for name, args, use in (
        ("node_info", {"paths": [f"{GEO}/box1"]}, "inspect what: node"),
        ("node_find", {"root": GEO}, "search kind: nodes"),
        ("viewport_capture", {}, "look"),
    ):
        refused = await check.mistake(name, args, "invalid_argument")
        assert refused["hint"].startswith(f"Use {use}"), refused
        assert "2.1 removed it" in refused["message"], refused

    # 6. 1.4 inspect arguments -------------------------------------------------------------------
    for wrong in ("path", "node_path"):
        renamed = await check.mistake(
            "inspect", {"what": "node", wrong: f"{GEO}/OUT"}, "invalid_argument"
        )
        assert f"{wrong}: unknown property; 2.0 renamed it target" in renamed["message"]
        assert "did you mean" not in renamed["message"]
        call = _after(renamed["hint"], "inspect takes the path as target: inspect ")
        assert call == {"what": "node", "target": f"{GEO}/OUT"}
    read = await rec.ok("inspect", call)  # the corrected call works
    assert read["nodes"][0]["path"] == f"{GEO}/OUT"
    no_target = await check.mistake("inspect", {"what": "node"}, "invalid_argument")
    assert no_target["hint"].startswith('inspect {what: "node", target: ')
    assert "docs/tools.md" not in json.dumps(no_target)

    # 7. made-up job ids -------------------------------------------------------------------------
    ledger = await check.mistake("job", {"action": "status", "job_id": "jzzzz"}, "job_not_found")
    assert ledger["message"] == "No job jzzzz: this server's ledger has no job with that id."
    assert "before the '-'" not in ledger["hint"] and "ledger" in ledger["hint"]
    assert 'job {action: "list", all: true}' in ledger["hint"]
    pid_form = await check.mistake(
        "job", {"action": "status", "job_id": "123-abc"}, "job_not_found"
    )
    assert "pid 123 is not a Houdini this server knows" in pid_form["message"]

    # 8. the other task-9 hints that named tools -------------------------------------------------
    copy_errors = await check.mistake(
        "inspect", {"what": "geo", "target": f"{GEO}/copy1"}, "cook_failed"
    )
    assert f'inspect {{what: "problems", target: "{GEO}"}}' in copy_errors["hint"]
    camera = await check.mistake("look", {"camera": "/obj/nocam"}, "node_not_found")
    assert camera["candidates"] == ["/obj/cam1"]
    assert 'search {kind: "nodes", root: "/obj"}' in camera["hint"]
    await rec.ok(
        "edit", {"ops": [{"op": "create", "parent": "/out", "type": "opengl", "name": "gl"}]}
    )
    await rec.ok("edit", {"ops": [{"op": "delete", "path": "/obj/cam1"}]})
    rop = await check.mistake(
        "render", {"rop_path": "/out/gl", "output": "$HIP/render/gl.$F4.png"}, "node_not_found"
    )
    assert 'edit {ops: [{op: "create", parent: "/obj", type: "cam"}]}' in rop["hint"]
    assert "look frames the scene without one" in rop["hint"]
    untitled = await check.mistake("hip_new", {}, "unsaved_changes")
    assert untitled["hint"].startswith("The scene is untitled: hip_save {path} saves it")

    # 9. an argument the schema does not have (2.1 stream F) -------------------------------------
    stray = await check.mistake(
        "render", {"rop_path": "/out/gl", "frame_range": [1, 5]}, "invalid_argument"
    )
    assert "frame_range: unknown property; did you mean frames?" in stray["message"]
    assert stray["candidates"] == ["frames"]
    assert 'inspect {what: "tool", target: "render"}' in stray["hint"]
    nested = await check.mistake(
        "houdini_connect", {"launch": {"mode": "headless", "hipp": "a.hip"}}, "invalid_argument"
    )
    assert "launch.hipp: unknown property; did you mean hip?" in nested["message"]
    assert nested["candidates"] == ["hip"]
    in_op = await check.mistake(
        "edit",
        {"ops": [{"op": "set", "paht": f"{GEO}/box1/sizex", "value": 2}]},
        "invalid_argument",
    )
    assert "ops[0].paht: unknown property" in in_op["message"]
    assert in_op["candidates"][0] == "path"
    assert 'inspect {what: "tool", target: "edit"}' in in_op["hint"]
    # the same call with the right key passes validation: the ROP is asked (this one writes
    # to MPlay, which a headless host cannot do), so the error is the host's, not the bridge's
    again = await check.mistake(
        "render", {"rop_path": "/out/gl", "frames": [1, 5]}, "invalid_value"
    )
    assert "unknown property" not in again["message"]


def test_error_quality_v2(headless_host, tmp_path):  # noqa: F811 - the fixture above
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    sys.path.insert(0, str(SRC))
    try:
        from hocuspocus.tools.catalog import TOOLS
    finally:
        sys.path.remove(str(SRC))
    every = frozenset(spec.name for spec in TOOLS)

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
    checkers: list[Checker] = []
    failures: list[BaseException] = []

    async def run() -> None:
        async with Client(params, read_timeout_seconds=180) as client:
            listed = {tool.name for tool in (await client.list_tools()).tools}
            check = Checker(Recorder(client), listed, every)
            checkers.append(check)
            try:
                await _scenario(check)
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    check = checkers[0]
    report = "\n".join(
        f"  {tool:<16} {error['code']:<20} {error.get('hint', '')[:110]}"
        for tool, error in check.errors
    )
    if failures:
        raise AssertionError(f"{failures[0]}\nmistakes so far:\n{report}") from failures[0]
    print(f"\n[error_quality_v2] {len(check.errors)} mistakes, every hint core-only\n{report}")
    assert len(check.listed) == 19 and "node_find" not in check.listed  # core
    assert len(check.errors) >= 20
