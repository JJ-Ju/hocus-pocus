"""The bridge's JSON-Schema-subset argument validator."""

from __future__ import annotations

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
