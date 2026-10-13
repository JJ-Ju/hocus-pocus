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
    MINIMAL_TOOLS,
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

# BIBLE §4.2–§4.7, in order. §4.7's tally says 30 core / 34 total, but its "9
# node/network" undercounts the ten tools §4.4 actually lists; every listed tool ships.
EXPECTED_ORDER = [
    "houdini_status", "houdini_connect",
    "hip_new", "hip_open", "hip_save", "hip_merge",
    "node_find", "node_info", "node_create", "node_delete", "node_edit", "node_copy",
    "node_connect", "node_layout", "network_describe", "network_build",
    "parm_get", "parm_set",
    "cook", "problems", "geo_info", "geo_read",
    "viewport_capture", "render", "houdini_python", "node_type_search", "node_type_info",
    "undo", "time", "selection", "job",
    "hda", "usd_stage", "pdg", "events",
]  # fmt: skip
FULL_ONLY = {"hda", "usd_stage", "pdg", "events"}
# BIBLE §4.1 (1.3): the minimal profile, for clients with a small context.
MINIMAL = {
    "houdini_status", "houdini_connect", "hip_open", "hip_save", "node_find", "node_info",
    "node_create", "node_connect", "parm_get", "parm_set", "cook", "geo_info",
    "viewport_capture", "houdini_python",
}  # fmt: skip

# BIBLE §9 code table, transcribed (`python_disabled / read_only` is one row, two codes).
BIBLE_ERROR_CODES = {
    "houdini_offline", "instance_lost", "houdini_busy", "delivery_unknown",
    "version_mismatch", "invalid_argument", "node_not_found", "parm_not_found", "node_type_not_found",
    "invalid_input", "invalid_value", "name_collision", "locked", "cook_failed",
    "unsaved_changes", "file_not_found", "path_not_allowed", "ui_required",
    "python_disabled", "read_only", "job_not_found", "cancelled", "python_exception",
    "internal",
}  # fmt: skip

# BIBLE §4.1 annotations.
DESTRUCTIVE = {"node_delete", "hip_new", "hip_open", "houdini_python"}
IDEMPOTENT = {
    "parm_set", "node_connect", "node_edit", "time", "selection", "cook", "job",
    "viewport_capture",
}  # fmt: skip
WITH_OUTPUT_SCHEMA = {
    "houdini_status", "hip_new", "hip_open", "hip_save", "hip_merge", "node_info",
    "parm_get", "parm_set", "cook", "geo_info", "geo_read", "viewport_capture", "render",
    "node_type_search", "time", "selection", "undo", "job",
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
    core = for_profile("core")
    assert len(core) == 31
    assert {spec.name for spec in TOOLS if spec.profile == "full"} == FULL_ONLY
    assert for_profile("full") == TOOLS
    assert [spec.name for spec in core] == [n for n in EXPECTED_ORDER if n not in FULL_ONLY]
    minimal = for_profile("minimal")
    assert MINIMAL_TOOLS == MINIMAL and len(minimal) == 14
    assert [spec.name for spec in minimal] == [n for n in EXPECTED_ORDER if n in MINIMAL]
    assert {catalog.profile_of(spec) for spec in minimal} == {"minimal"}


def test_profiles_are_nested() -> None:
    """minimal ⊂ core ⊂ full (BIBLE §4.1): a bigger profile never drops a tool, so a
    client moving up a profile keeps every tool it knew, and the integration tier, which
    runs its host on full, exercises every tool of every profile."""
    assert catalog.PROFILES == ("minimal", "core", "full")
    names = {p: [spec.name for spec in for_profile(p)] for p in catalog.PROFILES}
    assert set(names["minimal"]) < set(names["core"]) < set(names["full"])
    assert names["full"] == [spec.name for spec in TOOLS]
    for profile in catalog.PROFILES:  # each in catalogue order
        assert names[profile] == [n for n in names["full"] if n in set(names[profile])]
    for spec in TOOLS:
        smallest = catalog.profile_of(spec)
        listed = [p for p in catalog.PROFILES if catalog.in_profile(spec, p)]
        assert listed == list(catalog.PROFILES[catalog.PROFILES.index(smallest) :]), spec.name
    assert catalog.in_profile(get("pdg"), "bogus") is False  # unknown reads as core
    assert catalog.in_profile(get("geo_read"), "bogus") is True


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
        validate({"limit": 0}, get("node_find").input_schema)
    with pytest.raises(SchemaError):
        validate({"pid": True}, get("houdini_connect").input_schema)


TOOLS_LIST_WIRE_MAX_BYTES = 44_000
"""Cap on the serialised ``tools/list`` result a client receives (review 11 §1.1): names,
descriptions, input and output schemas and annotations, for the full profile."""

TOOLS_LIST_WIRE_TARGET_BYTES = 40_000
"""1.2 headroom target (BIBLE §4.1): the full profile sits at or under 40,000 bytes, leaving
4 KB under the cap for new tools. Argument detail lives in each spec's ``notes``
(``docs/tools.md`` and ``hocuspocus://guide``), not in ``tools/list``."""


def tools_list_wire_size(profile: str, result_content: str = "both") -> int:
    """Bytes of the ``ListToolsResult`` the bridge sends, serialised as the SDK does.
    ``both`` (output schemas declared) is the largest; the ``text`` default omits them."""
    import json

    import mcp_types as types

    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile, result_content=result_content), scan=lambda: [])
    result = types.ListToolsResult(tools=bridge.list_tools())
    payload = result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def test_tools_list_budget(capsys: pytest.CaptureFixture[str]) -> None:
    sizes = {profile: tools_list_wire_size(profile) for profile in ("minimal", "core", "full")}
    with capsys.disabled():
        print(
            f"\n[tools/list] serialised: minimal {sizes['minimal']:,} B, core "
            f"{sizes['core']:,} B, full {sizes['full']:,} B "
            f"(cap {TOOLS_LIST_WIRE_MAX_BYTES:,} B; full without output schemas, the "
            f"text default: {tools_list_wire_size('full', 'text'):,} B); "
            f"names+descriptions+input schemas {tools_list_text_size(TOOLS):,} B"
        )
    assert sizes["minimal"] < sizes["core"] < sizes["full"] <= TOOLS_LIST_WIRE_MAX_BYTES, sizes
    assert sizes["full"] <= TOOLS_LIST_WIRE_TARGET_BYTES, (
        f"tools/list (full profile, output schemas declared) is {sizes['full']:,} B, over the "
        f"{TOOLS_LIST_WIRE_TARGET_BYTES:,} B headroom target (BIBLE §4.1; hard cap "
        f"{TOOLS_LIST_WIRE_MAX_BYTES:,} B). Move argument detail from the description into the "
        "spec's notes (docs/tools.md, hocuspocus://guide) before raising the target."
    )
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
    from hocuspocus.bridge.instructions import guide_text
    from hocuspocus.bridge.server import Bridge

    noted = [spec for spec in TOOLS if spec.notes]
    assert len(noted) >= 10
    markdown = render_tools_markdown(TOOLS)
    guide = guide_text()
    listed = {
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
