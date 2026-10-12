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

# BIBLE §9 code table, transcribed (`python_disabled / read_only` is one row, two codes).
BIBLE_ERROR_CODES = {
    "houdini_offline", "houdini_busy", "delivery_unknown", "version_mismatch",
    "invalid_argument", "node_not_found", "parm_not_found", "node_type_not_found",
    "invalid_input", "invalid_value", "name_collision", "locked", "cook_failed",
    "unsaved_changes", "file_not_found", "path_not_allowed", "ui_required",
    "python_disabled", "read_only", "job_not_found", "cancelled", "internal",
}  # fmt: skip

# BIBLE §4.1 annotations.
DESTRUCTIVE = {"node_delete", "hip_new", "hip_open", "houdini_python"}
IDEMPOTENT = {"parm_set", "node_connect", "node_edit", "time"}
WITH_OUTPUT_SCHEMA = {
    "houdini_status", "hip_new", "hip_open", "hip_save", "hip_merge", "node_info",
    "parm_get", "parm_set", "cook", "geo_info", "node_type_search", "time", "undo", "job",
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


def test_bridge_local_tools() -> None:
    assert {spec.name for spec in TOOLS if spec.bridge_local} == {"houdini_status", "houdini_connect"}


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
        validate({"items": [{"parent": "/obj", "type": "geo", "inputs": [{"from": "/a"}]}]}, node_create)
    with pytest.raises(SchemaError):
        validate({"on_unsaved": "save"}, get("hip_open").input_schema)  # path required
    with pytest.raises(SchemaError):
        validate({"limit": 0}, get("node_find").input_schema)
    with pytest.raises(SchemaError):
        validate({"pid": True}, get("houdini_connect").input_schema)


def test_tools_list_budget() -> None:
    size = tools_list_text_size(TOOLS)
    assert size <= TOOLS_LIST_MAX_BYTES, size


def test_error_codes_match_bible() -> None:
    assert set(ERROR_CODES) == BIBLE_ERROR_CODES


def test_tools_md_is_current() -> None:
    path = REPO / "docs" / "tools.md"
    assert path.exists(), "run `python -m hocuspocus.tools.docs`"
    committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == render_tools_markdown(TOOLS), "docs/tools.md is stale; run `python -m hocuspocus.tools.docs`"
