"""Catalogue integrity (BIBLE §3.5, §4, §9, §11)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
try:
    import hocuspocus.tools.catalog  # noqa: F401
except ImportError:  # running from a checkout without an editable install
    sys.path.insert(0, str(REPO / "src"))

from hocuspocus.tools import catalog  # noqa: E402
from hocuspocus.tools.catalog import (  # noqa: E402
    ARGUMENT_DESCRIPTION_MAX_WORDS,
    DESCRIPTION_MAX_WORDS,
    TOOLS,
    TOOLS_LIST_MAX_BYTES,
    for_profile,
    get,
)
from hocuspocus.tools.docs import (  # noqa: E402
    SchemaError,
    render_tools_markdown,
    tools_list_text_size,
    validate,
    validate_examples,
)
from hocuspocus.tools.errors import ERROR_CODES  # noqa: E402

pytestmark = pytest.mark.unit

# Catalogue order: spec-2.0 §2's.
EXPECTED_ORDER = [
    "houdini_status", "houdini_connect",
    "hip_new", "hip_open", "hip_save", "hip_merge",
    "inspect", "search", "edit", "node_create", "parm_set",
    "cook", "render", "look", "houdini_python", "undo", "time", "job",
    "hda", "pdg", "events",
]  # fmt: skip
# spec-2.0 §2: the 2.0 profiles, transcribed.
MINIMAL = {
    "houdini_status", "houdini_connect", "hip_open", "hip_save", "inspect", "search", "edit",
    "node_create", "parm_set", "look",
}  # fmt: skip
CORE = MINIMAL | {
    "hip_new", "hip_merge", "cook", "render", "houdini_python", "job", "undo", "time", "hda",
}  # fmt: skip
FULL = CORE | {"pdg", "events"}

# BIBLE §9 code table, transcribed (`python_disabled / read_only` is one row, two codes).
BIBLE_ERROR_CODES = {
    "houdini_offline", "instance_lost", "ambiguous_instance", "houdini_busy",
    "delivery_unknown", "version_mismatch", "invalid_argument", "node_not_found", "parm_not_found", "node_type_not_found",
    "invalid_input", "invalid_value", "name_collision", "locked", "cook_failed",
    "unsaved_changes", "file_not_found", "path_not_allowed", "ui_required",
    "python_disabled", "read_only", "job_not_found", "cancelled", "python_exception",
    "internal",
}  # fmt: skip

# BIBLE §4.1 annotations.
DESTRUCTIVE = {"hip_new", "hip_open", "houdini_python", "edit"}
IDEMPOTENT = {"parm_set", "time", "cook", "job", "look"}
WITH_OUTPUT_SCHEMA = {
    "houdini_status", "hip_new", "hip_open", "hip_save", "hip_merge", "parm_set", "cook",
    "render", "time", "undo", "job", "look",
}  # fmt: skip

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _ids(spec: catalog.ToolSpec) -> str:
    return spec.name


def test_names_unique_snake_case_and_ordered() -> None:
    names = [spec.name for spec in TOOLS]
    assert len(names) == len(set(names))
    assert all(NAME_RE.match(name) for name in names), names
    assert names == EXPECTED_ORDER
    assert [spec.name for spec in catalog.TOOLS] == names  # stable across accesses
    assert get("parm_set") is TOOLS[names.index("parm_set")]
    assert get("no_such_tool") is None


def test_profiles() -> None:
    """spec-2.0 §2: minimal 10, core 19 (the default; 2.1 adds hda, D47), full 21 (2.1
    removed compat_1x)."""
    assert catalog.PROFILES == ("minimal", "core", "full")
    assert catalog.DEFAULT_PROFILE == "core"
    for profile, expected, size in (
        ("minimal", MINIMAL, 10),
        ("core", CORE, 19),
        ("full", FULL, 21),
    ):
        names = [spec.name for spec in for_profile(profile)]
        assert len(names) == size and set(names) == expected, profile
        assert names == [n for n in EXPECTED_ORDER if n in expected], profile
    assert {catalog.profile_of(spec) for spec in for_profile("minimal")} == {"minimal"}


def test_profiles_are_nested() -> None:
    """minimal ⊂ core ⊂ full (spec-2.0 §2): a bigger profile never drops a tool, so a client
    moving up a profile keeps every tool it knew. Each spec's ``profiles`` is a suffix of
    the three, so the nesting holds tool by tool."""
    names = {p: [spec.name for spec in for_profile(p)] for p in catalog.PROFILES}
    assert set(names["minimal"]) < set(names["core"]) < set(names["full"])
    for profile in catalog.PROFILES:  # each in catalogue order
        assert names[profile] == [n for n in EXPECTED_ORDER if n in set(names[profile])]
    for spec in TOOLS:
        assert spec.profiles, spec.name
        assert set(spec.profiles) <= set(catalog.PROFILES), spec.name
        assert len(set(spec.profiles)) == len(spec.profiles), spec.name
        listed = list(spec.profiles)
        assert listed == list(catalog.PROFILES[len(catalog.PROFILES) - len(listed) :]), spec.name
        assert [p for p in catalog.PROFILES if catalog.in_profile(spec, p)] == listed, spec.name
        assert catalog.profile_of(spec) == listed[0], spec.name
    assert catalog.in_profile(get("pdg"), "bogus") is False  # unknown reads as core
    assert catalog.in_profile(get("cook"), "bogus") is True
    assert catalog.for_profile("bogus") is catalog.for_profile("core")
    # 2.1 removed v2 and compat_1x: the catalogue reads them as unknown names (the config
    # readers turn them into full with a warning, test_profiles.py).
    assert catalog.for_profile("v2") is catalog.for_profile("core")
    assert catalog.for_profile("compat_1x") is catalog.for_profile("core")


def test_bridge_local_tools() -> None:
    assert {spec.name for spec in TOOLS if spec.bridge_local} == {
        "houdini_status",
        "houdini_connect",
    }


@pytest.mark.parametrize("spec", TOOLS, ids=_ids)
def test_description(spec: catalog.ToolSpec) -> None:
    words = spec.description.split()
    assert words, "empty description"
    assert len(words) <= DESCRIPTION_MAX_WORDS, f"{len(words)} words"
    if not spec.headless_ok:
        assert "(GUI only)" in spec.description


@pytest.mark.parametrize("spec", TOOLS, ids=_ids)
def test_input_schema_shape(spec: catalog.ToolSpec) -> None:
    schema = spec.input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert isinstance(schema.get("properties"), dict)
    assert set(schema.get("required", ())) <= set(schema["properties"])
    for key in schema["properties"]:
        assert NAME_RE.match(key), key


@pytest.mark.parametrize("spec", TOOLS, ids=_ids)
def test_annotations(spec: catalog.ToolSpec) -> None:
    assert spec.destructive == (spec.name in DESTRUCTIVE)
    assert spec.idempotent == (spec.name in IDEMPOTENT)
    assert not (spec.read_only and spec.destructive)
    assert spec.annotations()["openWorldHint"] is False
    assert (spec.output_schema is not None) == (spec.name in WITH_OUTPUT_SCHEMA)
    if spec.output_schema is not None:
        assert spec.output_schema["type"] == "object"


# MCP ToolAnnotations defaults (2025-06-18 schema).
MCP_HINT_DEFAULTS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}


@pytest.mark.parametrize("spec", TOOLS, ids=_ids)
def test_wire_annotations_mean_the_same_under_mcp_defaults(spec: catalog.ToolSpec) -> None:
    full = spec.annotations()
    wire = spec.wire_annotations()
    assert set(wire) <= set(full) and len(wire) < len(full)
    resolved = {**MCP_HINT_DEFAULTS, **wire}
    assert resolved["readOnlyHint"] == full["readOnlyHint"]
    assert resolved["openWorldHint"] is False
    if not full["readOnlyHint"]:  # destructive/idempotent are meaningful only then
        assert resolved["destructiveHint"] == full["destructiveHint"]
        assert resolved["idempotentHint"] == full["idempotentHint"]


def test_examples_validate() -> None:
    assert validate_examples(TOOLS) == []
    for spec in TOOLS:
        assert 1 <= len(spec.examples) <= 3, spec.name


def test_validator_rejects_bad_arguments() -> None:
    parm_set = get("parm_set").input_schema
    with pytest.raises(SchemaError):
        validate({"items": [{"path": "/obj/geo1/box1/sx", "animation": "smooth"}]}, parm_set)
    with pytest.raises(SchemaError):
        validate({"items": [], "bogus": 1}, parm_set)
    node_create = get("node_create").input_schema
    with pytest.raises(SchemaError):  # input link needs exactly one of index or name
        validate(
            {"items": [{"parent": "/obj", "type": "geo", "inputs": [{"from": "/a"}]}]}, node_create
        )
    with pytest.raises(SchemaError):
        validate({"on_unsaved": "save"}, get("hip_open").input_schema)  # path required
    with pytest.raises(SchemaError):
        validate({"kind": "nodes", "limit": 0}, get("search").input_schema)
    with pytest.raises(SchemaError):
        validate({"pid": True}, get("houdini_connect").input_schema)


TOOLS_LIST_DEFAULT_MAX_BYTES = 24_000
"""Cap on what a client sees by default (spec-2.0 §7 M3): the serialised ``tools/list``
result of the 2.0 full profile with ``result_content = "text"``, which declares no output
schemas. Argument detail lives in each spec's ``notes`` (``docs/tools.md`` and
``hocuspocus://tools``), not in ``tools/list``."""

TOOLS_LIST_BOTH_MAX_BYTES = 34_000
"""Cap on the largest 2.0 shape a client can ask for: the full profile with
``result_content = "both"``, output schemas declared."""

PROFILES = ("minimal", "core", "full")
MODES = ("text", "both")


def tools_list_wire_size(profile: str, result_content: str = "text") -> int:
    """Bytes of the ``ListToolsResult`` the bridge sends, serialised as the SDK does.
    ``text`` (the default) declares no output schemas; ``both`` declares them."""
    import json

    import mcp_types as types

    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile, result_content=result_content), scan=lambda: [])
    result = types.ListToolsResult(tools=bridge.list_tools())
    payload = result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def test_tools_list_budget(capsys: pytest.CaptureFixture[str]) -> None:
    """spec-2.0 §7 M3 (D44): cap what clients see by default (``text``) and the ``both``
    shape on the full profile; all six sizes are printed."""
    sizes = {(p, m): tools_list_wire_size(p, m) for m in MODES for p in PROFILES}
    caps = {"text": TOOLS_LIST_DEFAULT_MAX_BYTES, "both": TOOLS_LIST_BOTH_MAX_BYTES}
    with capsys.disabled():
        for mode in MODES:
            row = ", ".join(f"{p} {sizes[p, mode]:,} B" for p in PROFILES)
            print(
                f"\n[tools/list] result_content={mode}: {row} (full cap {caps[mode]:,} B)", end=""
            )
        print(f"\n[tools/list] names+descriptions+input schemas {tools_list_text_size(TOOLS):,} B")
    for mode in MODES:
        assert sizes["minimal", mode] < sizes["core", mode] < sizes["full", mode], sizes
        assert sizes["full", mode] <= caps[mode], (
            f"tools/list (full profile, result_content {mode}) is {sizes['full', mode]:,} B, "
            f"over the {caps[mode]:,} B cap (spec-2.0 §7 M3). Move argument detail from the "
            "description into the spec's notes (docs/tools.md, hocuspocus://tools) before "
            "raising the cap."
        )
    assert sizes["full", "text"] < sizes["full", "both"], sizes
    assert tools_list_text_size(TOOLS) <= TOOLS_LIST_MAX_BYTES


def test_description_cap_is_60_words() -> None:
    assert DESCRIPTION_MAX_WORDS == 60  # BIBLE §4.1 (1.2)


def _argument_descriptions(schema: dict, path: str = ""):
    """``(argument path, description)`` for every described property, nested ones too."""
    for name, prop in schema.get("properties", {}).items():
        where = f"{path}.{name}" if path else name
        if prop.get("description"):
            yield where, prop["description"]
        yield from _argument_descriptions(prop, where)
        if isinstance(prop.get("items"), dict):
            yield from _argument_descriptions(prop["items"], f"{where}[]")
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, ()):
            yield from _argument_descriptions(sub, path)


@pytest.mark.parametrize("spec", TOOLS, ids=_ids)
def test_argument_detail_lives_in_notes(spec: catalog.ToolSpec) -> None:
    """BIBLE §4.1 (1.3): an argument description is a phrase of at most 12 words. Shapes,
    edge cases and interactions go in the spec's notes (docs/tools.md and
    hocuspocus://guide), which tools/list leaves out, so new arguments do not eat the
    tools/list budget."""
    assert ARGUMENT_DESCRIPTION_MAX_WORDS == 12
    long = {
        where: len(text.split())
        for where, text in _argument_descriptions(spec.input_schema)
        if len(text.split()) > ARGUMENT_DESCRIPTION_MAX_WORDS
    }
    assert not long, (
        f"argument descriptions over {ARGUMENT_DESCRIPTION_MAX_WORDS} words: {long}. Keep a "
        "short phrase in the schema and move the detail into the spec's notes."
    )


def test_notes_reach_the_docs_and_guide_but_not_tools_list() -> None:
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.instructions import tools_text
    from hocuspocus.bridge.server import Bridge

    noted = [spec for spec in TOOLS if spec.notes]
    assert len(noted) >= 10
    markdown = render_tools_markdown(TOOLS)
    guide = tools_text()  # hocuspocus://tools (1.3; the guide itself is instructions only)
    listed = {  # full lists every tool
        tool.name: tool
        for tool in Bridge(BridgeConfig(profile="full"), scan=lambda: []).list_tools()
    }
    for spec in noted:
        assert spec.notes in markdown and spec.notes in guide, spec.name
        assert spec.notes not in (listed[spec.name].description or ""), spec.name


def test_error_codes_match_bible() -> None:
    assert set(ERROR_CODES) == BIBLE_ERROR_CODES


def test_read_only_refusal_is_one_text() -> None:
    from hocuspocus.tools.errors import READ_ONLY_HINT, read_only_error

    error = read_only_error("undo")
    assert error.code == "read_only" and error.hint == READ_ONLY_HINT
    assert error.message == "undo changes the scene, and the host is in read-only mode."


def test_tools_md_is_current() -> None:
    path = REPO / "docs" / "tools.md"
    assert path.exists(), "run `python -m hocuspocus.tools.docs`"
    committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == render_tools_markdown(TOOLS), (
        "docs/tools.md is stale; run `python -m hocuspocus.tools.docs`"
    )


# ---------------------------------------------------------------------------
# 2.0 (spec-2.0 §5.1): the catalogue is loaded from one spec module per tool
# ---------------------------------------------------------------------------


def _spec_modules() -> set[str]:
    import pkgutil

    from hocuspocus.tools import spec as spec_package

    return {
        info.name
        for info in pkgutil.iter_modules(spec_package.__path__)
        if not info.name.startswith("_")
    }


def test_each_spec_module_is_named_after_its_tool() -> None:
    import importlib

    for name in _spec_modules():
        module = importlib.import_module(f"hocuspocus.tools.spec.{name}")
        assert isinstance(module.SPEC, catalog.ToolSpec), name
        assert module.SPEC.name == name, f"spec/{name}.py defines {module.SPEC.name!r}"


def test_spec_order_lists_every_module_once() -> None:
    """The catalogue order is an explicit list, never directory order: it names every spec
    module and nothing else, and the loader keeps it."""
    from hocuspocus.tools import spec as spec_package

    order = spec_package.ORDER
    assert len(order) == len(set(order)), "a module is listed twice"
    assert set(order) == _spec_modules(), (
        f"missing from ORDER: {sorted(_spec_modules() - set(order))}; "
        f"no such module: {sorted(set(order) - _spec_modules())}"
    )
    assert [spec.name for spec in TOOLS] == list(order)
    assert catalog.TOOLS is spec_package.TOOLS


def test_one_tools_reference_implementation() -> None:
    """hocuspocus://tools is rendered by tools/docs.py, the docs/tools.md renderer."""
    from hocuspocus.bridge import instructions
    from hocuspocus.tools import docs

    assert instructions.tools_text is docs.tools_reference
    assert docs.tools_reference() == render_tools_markdown(TOOLS)
    assert docs.tools_reference(for_profile("minimal")) == render_tools_markdown(
        for_profile("minimal")
    )


def test_budget_md_is_current() -> None:
    """docs/redesign/budget.md (spec-2.0 §5.1): its latest history row is the current
    measurement, and its per-tool table is the current one."""
    from hocuspocus.tools import docs

    assert docs.TOOLS_LIST_CAPS == {
        "text": TOOLS_LIST_DEFAULT_MAX_BYTES,
        "both": TOOLS_LIST_BOTH_MAX_BYTES,
    }
    path = REPO / "docs" / "redesign" / "budget.md"
    hint = "run `python -m hocuspocus.tools.docs --budget` and commit docs/redesign/budget.md"
    assert path.exists(), hint
    committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    history = docs.parse_budget_history(committed)
    assert history, hint
    measured = docs.measure_budget()
    assert history[-1]["sizes"] == measured["sizes"], (
        f"docs/redesign/budget.md is stale (latest row {history[-1]['sizes']}, now "
        f"{measured['sizes']}); {hint}"
    )
    assert measured["sizes"] == {
        f"{p} {m}": tools_list_wire_size(p, m) for m in MODES for p in PROFILES
    }
    assert committed == docs.render_budget_markdown(history, measured), hint


def test_budget_history_appends_a_dated_row(tmp_path: Path) -> None:
    from hocuspocus.tools import docs

    target = tmp_path / "budget.md"
    docs.update_budget_markdown(target, date="2026-01-01")
    docs.update_budget_markdown(target, date="2026-01-01")  # an exact repeat adds nothing
    docs.update_budget_markdown(target, date="2026-01-02")
    rows = docs.parse_budget_history(target.read_text(encoding="utf-8"))
    assert [row["date"] for row in rows] == ["2026-01-01", "2026-01-02"]
    assert rows[0]["sizes"] == rows[1]["sizes"]
    assert set(rows[0]["sizes"]) == {f"{p} {m}" for m in MODES for p in PROFILES}
