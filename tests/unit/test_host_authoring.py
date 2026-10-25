"""The pure parts of the 2.1 authoring changes (BIBLE §4.5, D48-D50): ``patch`` matching,
condition parsing, and ``path`` read as each ``edit`` op's node field."""

from __future__ import annotations

import pytest

from hocuspocus.host import tx
from hocuspocus.host.tools import parms as P
from hocuspocus.host.tools import spare
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

TEXT = "float h = chf('h');\nint n = chi('n');\n// a\n// a\nf@y = h * n;\n"


def test_patch_applies_edits_in_order_and_reports_lines():
    text, lines = P.apply_patch(
        TEXT,
        [{"find": "chf('h')", "replace": "chf('height')"}, {"find": "h * n", "replace": "h"}],
        "/obj/g/w/snippet",
    )
    assert text == TEXT.replace("chf('h')", "chf('height')").replace("h * n", "h")
    assert lines == [1, 5]
    text, lines = P.apply_patch(TEXT, {"find": "// a", "replace": "// b", "all": True}, "p")
    assert text.count("// b") == 2 and lines == [3]


def test_patch_refuses_a_find_that_does_not_occur_once():
    with pytest.raises(ToolError) as missing:
        P.apply_patch(TEXT, {"find": "int n = chi('m');"}, "/obj/g/w/snippet")
    assert missing.value.code == "invalid_value"
    assert missing.value.candidates[0] == "line 2: int n = chi('n');"  # nearest first
    with pytest.raises(ToolError) as several:
        P.apply_patch(TEXT, [{"find": "// a"}], "p")
    assert "patch[0].find occurs 2 times" in several.value.message
    assert several.value.detail == {"occurrences": 2, "lines": [3, 4]}
    with pytest.raises(ToolError) as spaced:
        P.apply_patch(TEXT, {"find": "float  h = chf('h');"}, "p")
    assert "whitespace" in spaced.value.hint
    for bad in ({}, [], [{"find": ""}], {"find": "a", "replace": 1}, {"find": "a", "x": 1}):
        with pytest.raises(ToolError) as shape:
            P.apply_patch(TEXT, bad, "p")
        assert shape.value.code == "invalid_argument", bad


def test_condition_names_are_the_compared_parms():
    assert spare.condition_names('{ interior == 0 } { style != "a == b" mode > 1 }') == {
        "interior",
        "style",
        "mode",
    }
    assert spare.condition_names("") == set()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"op": "create", "path": "/obj/geo1/box1", "type": "box"},
         {"parent": "/obj/geo1", "name": "box1", "type": "box"}),
        ({"op": "create", "path": "$g/box1", "type": "box"},
         {"parent": "$g", "name": "box1", "type": "box"}),
        ({"op": "set", "path": "/obj/geo1/box1", "parms": {"sizex": 1}},
         {"node": "/obj/geo1/box1", "parms": {"sizex": 1}}),
        ({"op": "set", "path": "/obj/geo1/box1/sizex", "value": 1},
         {"path": "/obj/geo1/box1/sizex", "value": 1}),
        ({"op": "node", "node": "/obj/geo1/box1", "comment": "c"},
         {"path": "/obj/geo1/box1", "comment": "c"}),
        ({"op": "connect", "from": "/obj/geo1/a", "path": "/obj/geo1/b"},
         {"from": "/obj/geo1/a", "to": "/obj/geo1/b"}),
        ({"op": "layout", "path": "/obj/geo1"}, {"parent": "/obj/geo1"}),
        ({"op": "build", "path": "/obj/geo1", "data": {}}, {"parent": "/obj/geo1", "data": {}}),
        ({"op": "select", "path": "/obj/geo1"}, {"paths": ["/obj/geo1"]}),
        ({"op": "copy", "path": "/obj/geo1", "to_parent": "/obj"},
         {"paths": ["/obj/geo1"], "to_parent": "/obj"}),
        ({"op": "delete", "path": "/obj/geo1"}, {"paths": ["/obj/geo1"]}),
        ({"op": "create", "path": "/obj/geo1/box1", "parent": "/obj/geo1", "type": "box"},
         {"parent": "/obj/geo1", "name": "box1", "type": "box"}),
    ],
)  # fmt: skip
def test_path_is_read_as_each_ops_node_field(raw, expected):
    (op,) = tx.parse_ops([raw]).ops
    assert op.args == expected


@pytest.mark.parametrize(
    "raw",
    [
        {"op": "create", "path": "box1", "type": "box"},
        {"op": "create", "path": "/obj/geo1/box1", "parent": "/obj", "type": "box"},
        {"op": "node", "path": "/obj/a", "node": "/obj/b"},
        {"op": "connect", "from": "/obj/a", "to": "/obj/b", "path": "/obj/c"},
    ],
)
def test_path_and_its_field_must_agree(raw):
    with pytest.raises(ToolError) as error:
        tx.parse_ops([raw])
    assert error.value.code == "invalid_argument"
    assert error.value.message.startswith("ops[0].")
