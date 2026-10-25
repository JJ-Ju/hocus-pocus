"""Hints and messages name only tools the active profile serves (review 25 papercut 1).

Two checks:

* **Dynamic.** A fixture of representative errors (an ``edit`` plan validated against the
  fake ``hou`` scene of ``test_host_tx``, the hint helpers the host and bridge build their
  texts with, the bridge's own refusals and argument errors) is produced once per profile
  inside :func:`hocuspocus.tools.migration.using_profile`, as the host's dispatcher runs a
  call. Every ``message``, ``hint`` and note is scanned for ``\\b[a-z_]+\\b`` candidates
  that are tool names; none may be outside the profile's listing (from the catalogue).
* **Static.** No string literal in a hint or message of ``host/`` or ``bridge/`` names a
  1.4 tool 2.0 replaced (2.1 removed them): such a name only reaches a hint through
  :func:`~hocuspocus.tools.migration.hint_tool`, which renders its 2.0 call.

A snake_case candidate (``node_find``) always counts as naming a tool. A one-word tool name
is also an English word (cook, look, render, search, time, undo, job, events, problems), so
it counts only where the text uses it as a call: followed by ``{`` (``cook {paths}``) or by
``tool`` ("the problems tool"). :func:`~hocuspocus.tools.migration.hint_tool` always renders
the call form. A removed tool's own refusal names the tool that was called; that one name
is allowed there.
"""

from __future__ import annotations

import ast
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from test_host_tx import FakeScene  # the fake hou scene the transaction tests use

from hocuspocus.tools import catalog, migration
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

PROFILES = ("minimal", "core", "full")
TOOL_NAMES = frozenset(spec.name for spec in catalog.TOOLS) | frozenset(migration.REPLACEMENTS)
"""The tools a text can name: the catalogue's and the removed 1.4 ones (no profile serves
those, so a text that names one fails the check)."""
SRC = Path(__file__).resolve().parents[2] / "src" / "hocuspocus"


def named_tools(text: str) -> set[str]:
    """The tool names ``text`` uses (see the module docstring for what counts)."""
    found: set[str] = set()
    for match in re.finditer(r"\b[a-z_]+\b", text):
        word = match.group(0)
        if word not in TOOL_NAMES:
            continue
        rest = text[match.end() :]
        if "_" in word or re.match(r"\s*\{", rest) or re.match(r"\s+tool\b", rest):
            found.add(word)
    return found


def test_named_tools_reads_calls_not_english() -> None:
    assert named_tools('node_find {root: "/obj"} lists it') == {"node_find"}
    assert named_tools("see also the problems tool") == {"problems"}
    assert named_tools('cook {paths: ["/obj/a"], force: true} rechecks') == {"cook"}
    assert named_tools("the node failed to cook; render again; look closer") == set()


def texts(item: Any) -> list[str]:
    """Every message, hint and note string inside an error dict or a ToolError."""
    if isinstance(item, ToolError):
        item = item.to_dict()
    out: list[str] = []
    if isinstance(item, str):
        return [item]
    if isinstance(item, dict):
        for key, value in item.items():
            if key in ("message", "hint", "note", "notes", "problems") or isinstance(
                value, dict | list
            ):
                out += texts(value)
    elif isinstance(item, list):
        for value in item:
            out += texts(value)
    return out


# -- the fixture ----------------------------------------------------------------------------


class _Parented:
    """Enough of a node for the hint helpers that take one."""

    def __init__(self, path: str, category: str = "Sop", name: str = "box") -> None:
        self._path, self._category, self._name = path, category, name

    def path(self) -> str:
        return self._path

    def parent(self) -> _Parented:
        return _Parented(self._path.rpartition("/")[0] or "/")

    def type(self) -> Any:
        category = types.SimpleNamespace(name=lambda: self._category)
        return types.SimpleNamespace(
            name=lambda: self._name, category=lambda: category, maxNumInputs=lambda: 1
        )

    def inputNames(self) -> tuple:  # noqa: N802 - hou API
        raise RuntimeError("no inputs here: the fallback hint")


def _edit_errors(scene: FakeScene) -> list[ToolError]:
    """The errors an ``edit`` op's run raises for the usual mistakes (BIBLE D56: the run is
    the validation): a bad type, a bad parm, a missing wire end, a bad input, a missing
    parent, a wire across networks or from a subnet input that does not exist."""
    from hocuspocus.host import tx
    from hocuspocus.host.tools import nodes, parms

    geo = scene.nodes["/obj/geo1"]
    box = scene.nodes["/obj/geo1/box1"]
    out: list[ToolError] = [
        nodes.type_not_found(geo, "mountian", scene.sop),
        nodes.type_not_found(geo, "geo", scene.sop),  # wrong category
        parms.parm_not_found(box, "sise"),
    ]
    for call in (
        lambda: tx.wire_source("/obj/geo1/nope", box, "from"),
        lambda: nodes.resolve_input_index(box, 5),
        lambda: nodes.get_node("/obj/nogeo", field="parent"),
        lambda: tx.wire_source("/obj", box, "from"),
        lambda: tx.wire_output(geo, box, 7, "from_output"),
    ):
        with pytest.raises(ToolError) as info:
            call()
        out.append(info.value)
    return out


def _host_errors(scene: FakeScene) -> list[Any]:
    from hocuspocus.host.tools import _common, _diag, geo, network, nodes, parms, state

    out: list[Any] = _edit_errors(scene)
    out.append(_diag.missing_node_error("/obj/geo1/boxx"))
    out.append(_diag.missing_node_error("/obj/gone/boxx"))
    out.append(parms.expression_hint())
    out.append(parms.spare_parms_hint())
    out.append(_common.dynamic_menu_note())
    out.append(state.context_changed_note())
    out.append(_diag.stale_hint("/obj/geo1/box1", 2.0))
    out.append(network.data_hint())
    node = _Parented("/obj/geo1/box1")
    out.append(geo.cook_failed_hint(node))
    out.append(nodes._labels_hint(node))
    out.append(nodes._locked_error(node, node, "edit"))
    return out


def _bridge_errors(profile: str) -> list[Any]:
    from hocuspocus.bridge.client import delivery_hint
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
    from hocuspocus.bridge.server import ledger_job_error, unknown_job_error

    out: list[Any] = [
        delivery_hint(profile),
        ledger_job_error("jzzzz", profile),
        unknown_job_error("123-abc", 123, profile),
    ]
    calls: list[tuple[str, dict[str, Any]]] = [
        ("parm_set", {"path": "/obj/geo1/box1/sizex", "value": 1}),  # flat batch item
        ("houdini_connect", {"bogus": 1}),
    ]
    if profile != "minimal":
        calls.append(("job", {"action": "status", "job_id": "jzzzz"}))  # the ledger's form
    calls += [
        ("inspect", {"what": "node", "path": "/obj/geo1"}),
        ("inspect", {"what": "node", "bogus_frame": 1}),
        ("edit", {"op": "set", "path": "/obj/a/t", "value": 1}),
        ("search", {"query": "box"}),
    ]
    for name, args in calls:
        result = bridge.call_tool(name, args)
        assert result.is_error, (name, args)
        out.append(_payload(result))
    return out


def _payload(result: Any) -> dict[str, Any]:
    import json

    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _refusals(profile: str) -> list[tuple[str, Any]]:
    """Every removed 1.4 tool's refusal, as the host builds it and as the bridge answers it."""
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile), scan=lambda: [])
    out: list[tuple[str, Any]] = []
    for tool in migration.REPLACEMENTS:
        out.append((tool, migration.removed_error(tool, profile)))
        out.append((tool, _payload(bridge.call_tool(tool, {}))))
    return out


@pytest.fixture
def scene(monkeypatch) -> FakeScene:
    fake = FakeScene()
    monkeypatch.setitem(sys.modules, "hou", fake.module())
    return fake


@pytest.mark.parametrize("profile", PROFILES)
def test_every_hint_names_only_tools_the_profile_serves(profile, scene) -> None:
    listed = {spec.name for spec in catalog.for_profile(profile)}
    with migration.using_profile(profile):
        produced = _host_errors(scene) + _bridge_errors(profile)
        refusals = _refusals(profile)
    bad = []
    for item in produced:
        for text in texts(item):
            outside = named_tools(text) - listed
            if outside:
                bad.append((sorted(outside), text))
    for called, error in refusals:
        for text in texts(error):
            outside = named_tools(text) - listed - {called}
            if outside:
                bad.append((sorted(outside), text))
    assert not bad, "\n".join(f"{names}: {text}" for names, text in bad)
    assert len(produced) > 20


def test_hints_name_the_2x_call_on_2x_profiles(scene) -> None:
    """The papercut's own examples, both ways."""
    with migration.using_profile("core"):
        bad_type, _category, bad_parm, missing, *_rest = _edit_errors(scene)
        assert 'search {kind: "types", query: "mountian"}' in bad_type.hint
        assert 'inspect {what: "node", target: "/obj/geo1/box1"' in bad_parm.hint
        assert 'search {kind: "nodes", root: "/obj/geo1"}' in missing.hint
        assert (
            'edit {ops: [{op: "set", path, expression}]}'
            in __import__("hocuspocus.host.tools.parms", fromlist=["x"]).expression_hint()
        )


def test_hint_tool_renders_each_profile() -> None:
    h = migration.hint_tool
    assert h("node_find", "core", root="/obj") == 'search {kind: "nodes", root: "/obj"}'
    assert h("node_info", "full", paths=["/obj/a"]) == 'inspect {what: "node", target: "/obj/a"}'
    assert h("viewport_capture", "minimal") == "look {}"
    assert h("problems", "core") == 'inspect {what: "problems"}'
    assert h("parm_set", "core", path=migration.BARE) == 'edit {ops: [{op: "set", path}]}'
    assert h("cook", "minimal") is None and h("cook", "core", paths=["/a"]) == (
        'cook {paths: ["/a"]}'
    )
    assert h("hda", "minimal") is None and h("hda", "core") == "hda"  # 2.1: D47
    assert migration.current_profile() == "full"
    with migration.using_profile("minimal") as resolved:
        assert resolved == "minimal" and h("node_type_info") == 'inspect {what: "type"}'
    # A removed profile name never reaches here resolved (the config reads it as full);
    # as an unknown name it is the default.
    with migration.using_profile("compat_1x") as resolved:
        assert resolved == "core" and h("node_find") == 'search {kind: "nodes"}'


# -- the static guard -------------------------------------------------------------------------

HINT_NAMES = re.compile(r"(^|_)(HINT|NOTE)S?$")


def _literals(node: ast.AST) -> list[str]:
    """String pieces of ``node``, skipping calls (``hint_tool("node_find", ...)`` names a
    tool on purpose)."""
    if isinstance(node, ast.Call):
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    out: list[str] = []
    for child in ast.iter_child_nodes(node):
        out += _literals(child)
    return out


def _hint_literals(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in ("ToolError", "bad_arg"):
                for arg in node.args[1:2]:
                    found += [(node.lineno, s) for s in _literals(arg)]
            for keyword in node.keywords:
                if keyword.arg in ("hint", "message"):
                    found += [(node.lineno, s) for s in _literals(keyword.value)]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(HINT_NAMES.search(t) for t in targets):
                found += [(node.lineno, s) for s in _literals(node.value)]
    return found


def test_no_hint_literal_names_a_removed_tool() -> None:
    removed = set(migration.REPLACEMENTS)
    bad = []
    for path in sorted([*SRC.glob("host/**/*.py"), *SRC.glob("bridge/*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, text in _hint_literals(tree):
            words = named_tools(text) & removed
            if words:
                bad.append(f"{path.relative_to(SRC)}:{line}: {sorted(words)} in {text!r}")
    assert not bad, "route these through migration.hint_tool:\n" + "\n".join(bad)


def test_no_tool_reference_text_names_a_removed_tool() -> None:
    """The reference a model reads (description, notes, argument descriptions and examples
    of every spec, which the tools resource and inspect tool render), the server
    instructions, the guide and the prompts name 2.0 calls, never a 1.4 tool 2.1 removed
    (2.1 stream F: search's notes still described node_find and node_type_search). Only the
    migration table and the docs about migration do."""
    import json

    from hocuspocus.bridge import instructions

    texts: dict[str, str] = {}
    for spec in catalog.TOOLS:
        texts[f"spec {spec.name}"] = "\n".join(
            [
                spec.description,
                spec.notes or "",
                json.dumps(spec.input_schema, ensure_ascii=False),
                json.dumps(spec.examples, ensure_ascii=False),
            ]
        )
    texts["instructions"] = instructions.INSTRUCTIONS + instructions.INSTRUCTIONS_POINTER
    texts["guide"] = instructions.guide_text()
    texts["prompts"] = json.dumps(instructions.PROMPTS, ensure_ascii=False)
    removed = set(migration.REPLACEMENTS)
    found = {
        where: sorted(named_tools(text) & removed)
        for where, text in texts.items()
        if named_tools(text) & removed
    }
    assert found == {}
