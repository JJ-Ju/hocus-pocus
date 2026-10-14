"""The bridge's JSON-Schema-subset argument validator."""

from __future__ import annotations

import json

import pytest

from hocuspocus.bridge.validate import validate

pytestmark = pytest.mark.unit

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "value": {
                        "anyOf": [
                            {"type": "number"},
                            {"type": "string"},
                            {"type": "array", "items": {"type": "number"}},
                        ]
                    },
                    "language": {"type": "string", "enum": ["hscript", "python"]},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        "frame": {"type": "number", "minimum": 0, "maximum": 10000},
        "count": {"type": "integer", "exclusiveMinimum": 0},
        "to_input": {
            "oneOf": [{"type": "integer", "minimum": 0}, {"type": "string", "pattern": "^[a-z]+$"}]
        },
        "ref": {"$ref": "#/$defs/vec2"},
    },
    "required": ["items"],
    "additionalProperties": False,
    "$defs": {
        "vec2": {
            "type": "array",
            "prefixItems": [{"type": "number"}, {"type": "number"}],
            "minItems": 2,
            "maxItems": 2,
        }
    },
}


def test_valid_arguments_pass():
    args = {
        "items": [{"path": "/obj/geo1/box1/t", "value": [1, 2, 3], "language": "python"}],
        "frame": 12.5,
        "count": 2,
        "to_input": "next",
        "ref": [0, 1.5],
    }
    assert validate(args, SCHEMA) == []


def test_missing_required_and_unknown_property_with_suggestion():
    errors = validate({"items": [{"pth": "/obj"}], "frme": 1}, SCHEMA)
    assert "items[0].path: required property is missing" in errors
    assert any(e.startswith("items[0].pth: unknown property; did you mean path") for e in errors)
    assert any(e.startswith("frme: unknown property; did you mean frame") for e in errors)


def test_type_errors_bool_is_not_number_or_integer():
    errors = validate({"items": [{"path": "/a"}], "frame": True, "count": 1.5}, SCHEMA)
    assert any(e.startswith("frame: expected number, got boolean") for e in errors)
    assert any(e.startswith("count: expected integer, got number") for e in errors)


def test_integral_float_counts_as_integer():
    assert validate({"items": [{"path": "/a"}], "count": 2.0}, SCHEMA) == []


def test_enum_and_bounds():
    errors = validate(
        {"items": [{"path": "/a", "language": "vex"}], "frame": -1, "count": 0}, SCHEMA
    )
    assert any("items[0].language" in e and "not one of" in e for e in errors)
    assert any(e.startswith("frame: must be >= 0") for e in errors)
    assert any(e.startswith("count: must be > 0") for e in errors)


def test_array_length_bounds():
    assert any("at least 1" in e for e in validate({"items": []}, SCHEMA))
    errors = validate({"items": [{"path": "/a"}] * 4}, SCHEMA)
    assert any("at most 3" in e for e in errors)


def test_any_of_and_one_of():
    errors = validate({"items": [{"path": "/a", "value": {"x": 1}}]}, SCHEMA)
    assert any(e.startswith("items[0].value") and "anyOf" in e for e in errors)
    errors = validate({"items": [{"path": "/a"}], "to_input": "Next1"}, SCHEMA)
    assert any(e.startswith("to_input") and "oneOf" in e for e in errors)
    errors = validate({"items": [{"path": "/a"}], "to_input": -1}, SCHEMA)
    assert any(e.startswith("to_input") for e in errors)


def test_ref_and_prefix_items():
    errors = validate({"items": [{"path": "/a"}], "ref": [0, "x"]}, SCHEMA)
    assert any(e.startswith("ref[1]: expected number") for e in errors)


def test_root_type_error_is_labelled():
    assert validate([], SCHEMA)[0].startswith("(arguments): expected object")


def test_empty_schema_accepts_anything():
    assert validate({"anything": 1}, {}) == []
    assert validate({"anything": 1}, None) == []


def test_node_create_parms_take_both_expression_spellings():
    from hocuspocus.tools.catalog import get

    schema = get("node_create").input_schema

    def check(parms):
        return validate({"items": [{"parent": "/obj", "type": "box", "parms": parms}]}, schema)

    assert check({"sizex": {"expression": "$F", "language": "python"}}) == []
    assert check({"sizex": {"expr": "$F", "lang": "hscript"}}) == []
    (error,) = check({"sizex": {"exp": "$F"}})
    assert "{expr, lang}" in error and "expression, language" in error
    # node_create parms also take any parm_set item field without path (review 10).
    assert check({"tx": {"keyframes": [{"frame": 1, "value": 0}]}}) == []
    assert check({"sx": {"channel_ref": "/obj/geo1/box1/sizex"}}) == []
    assert check({"ramp": {"ramp": {"keys": [0, 1], "values": [0, 1]}}}) == []
    (error,) = check({"sizex": {"expr": "$F", "language": "python"}})
    assert "did you mean lang" in error


# -- review 10 section 1.10 --------------------------------------------------------------


def test_enum_and_const_compare_json_values():
    assert validate(True, {"enum": [0, 1]})
    assert validate(1, {"enum": [True]})
    assert validate(False, {"const": 0})
    assert not validate(1, {"enum": [0, 1]})
    assert not validate(1.0, {"enum": [1]})  # numbers compare as numbers
    assert not validate([True], {"const": [True]})
    assert validate([1], {"const": [True]})


def test_integral_floats_are_coerced_where_the_schema_says_integer():
    from hocuspocus.bridge.validate import coerce_integers

    schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer"},
            "scale": {"type": "number"},
            "frames": {"type": "array", "items": {"type": "integer"}},
            "nested": {"$ref": "#/$defs/n"},
        },
        "$defs": {"n": {"type": "object", "properties": {"count": {"type": "integer"}}}},
    }
    args = {"limit": 50.0, "scale": 2.0, "frames": [1.0, 24.0], "nested": {"count": 3.0}}
    assert validate(args, schema) == []
    out = coerce_integers(args, schema)
    assert out == {"limit": 50, "scale": 2.0, "frames": [1, 24], "nested": {"count": 3}}
    assert type(out["limit"]) is int and type(out["scale"]) is float
    assert type(out["frames"][0]) is int and args["limit"] == 50.0  # input untouched


def _defaults(schema, path=""):
    if isinstance(schema, dict):
        if "default" in schema:
            yield path, schema
        for key, value in schema.items():
            yield from _defaults(value, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, value in enumerate(schema):
            yield from _defaults(value, f"{path}[{i}]")


def test_every_catalogue_example_and_default_passes_the_runtime_validator():
    """The strict docs validator checks the examples; the bridge's runtime one must agree."""
    from hocuspocus.tools.catalog import TOOLS

    for spec in TOOLS:
        for example in spec.examples:
            assert validate(example, spec.input_schema) == [], (spec.name, example)
        for where, prop in _defaults(spec.input_schema):
            sub = {k: v for k, v in prop.items() if k != "default"}
            sub["$defs"] = spec.input_schema.get("$defs", {})
            assert validate(prop["default"], sub) == [], (spec.name, where)


# -- the corrected call for a flat batch item (review 21 papercut 1) -----------------------


def _catalog_schema(name: str) -> dict:
    from hocuspocus.tools import catalog

    return catalog.get(name).input_schema


@pytest.mark.parametrize(
    ("tool", "args", "item"),
    [
        (
            "parm_set",
            {"path": "/obj/g/height", "value": 0.7},
            {"path": "/obj/g/height", "value": 0.7},
        ),
        (
            "node_connect",
            {"from": "/obj/g/box1", "to": "/obj/g/merge1", "to_input": 0},
            {"from": "/obj/g/box1", "to": "/obj/g/merge1", "to_input": 0},
        ),
        ("node_create", {"parent": "/obj", "type": "geo"}, {"parent": "/obj", "type": "geo"}),
        ("node_edit", {"path": "/obj/a", "name": "b"}, {"path": "/obj/a", "name": "b"}),
    ],
)
def test_flat_batch_item_gets_the_items_form_with_its_own_fields(tool, args, item):
    from hocuspocus.bridge.validate import shape_hint

    schema = _catalog_schema(tool)
    assert validate(args, schema)  # the flat form is rejected
    hint = shape_hint(args, schema)
    fixed = json.loads(hint.split("items: ", 1)[1])
    assert fixed == {"items": [item]}
    assert not validate(fixed, schema)  # and the hint's form is valid


def test_top_level_fields_stay_outside_items():
    from hocuspocus.bridge.validate import shape_hint

    hint = shape_hint({"path": "/x", "value": 1, "partial": True}, _catalog_schema("parm_set"))
    assert json.loads(hint.split("items: ", 1)[1]) == {
        "items": [{"path": "/x", "value": 1}],
        "partial": True,
    }


def test_no_shape_hint_for_unrelated_mistakes():
    from hocuspocus.bridge.validate import shape_hint

    assert shape_hint({"bogus": 1}, _catalog_schema("parm_set")) is None
    assert shape_hint({"items": "x"}, _catalog_schema("parm_set")) is None
    assert shape_hint({"paths": ["/obj"]}, _catalog_schema("node_info")) is None


def test_bridge_error_for_a_flat_parm_set_shows_the_items_form():
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile="full"), scan=lambda: [])
    result = bridge.call_tool("parm_set", {"path": "/obj/geo1/box1/sizex", "value": 2})
    error = json.loads(result.content[0].text)
    assert error["code"] == "invalid_argument"
    assert '{"items": [{"path": "/obj/geo1/box1/sizex", "value": 2}]}' in error["hint"]


def test_guide_examples_use_the_items_form():
    import re

    from hocuspocus.bridge.instructions import GUIDE_MAX_BYTES, INSTRUCTIONS, guide_text

    guide = guide_text()
    assert len(guide.encode("utf-8")) <= GUIDE_MAX_BYTES
    for text in (guide, INSTRUCTIONS):
        for tool in ("parm_set", "node_connect", "node_create", "node_edit"):
            assert not re.search(rf"`{tool} \{{(?!items)", text), tool
