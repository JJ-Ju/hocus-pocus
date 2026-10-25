"""Unknown arguments are refused by the bridge (2.1 stream F, BIBLE §3.3 rule 2, §9).

``render {frame_range}`` once rendered the current frame without complaint. Every tool schema
says ``additionalProperties: false`` and the bridge's validator enforces it at every depth;
these tests pin that for the whole catalogue, and pin the answer: ``invalid_argument`` naming
the key, the closest valid key as a candidate, and a hint that names the tool's reference.
"""

from __future__ import annotations

import json

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.server import Bridge
from hocuspocus.bridge.validate import closest_keys, validate
from hocuspocus.tools.catalog import TOOLS


def _object_schemas(schema, steps=()):
    """``(steps, object schema)`` for every object with properties in ``schema``: ``steps``
    is the chain of property names, and ``None`` for an array's items, that reaches it."""
    if not isinstance(schema, dict):
        return
    if isinstance(schema.get("properties"), dict):
        yield steps, schema
        for name, sub in schema["properties"].items():
            yield from _object_schemas(sub, (*steps, name))
    if isinstance(schema.get("items"), dict):
        yield from _object_schemas(schema["items"], (*steps, None))


def _nest(steps, leaf):
    for step in reversed(steps):
        leaf = [leaf] if step is None else {step: leaf}
    return leaf


def _where(steps):
    path = ""
    for step in steps:
        path = f"{path}[0]" if step is None else (f"{path}.{step}" if path else step)
    return path


def test_every_object_with_properties_in_every_tool_schema_is_closed():
    open_objects = [
        f"{spec.name}: {_where(steps) or '(arguments)'}"
        for spec in TOOLS
        for steps, obj in _object_schemas(spec.input_schema)
        if obj.get("additionalProperties") is not False
    ]
    assert open_objects == []


def test_an_unknown_key_is_reported_at_every_depth_of_every_tool():
    checked = 0
    for spec in TOOLS:
        for steps, _obj in _object_schemas(spec.input_schema):
            violations = validate(_nest(steps, {"zz_bogus": 1}), spec.input_schema)
            where = _where(steps)
            expected = f"{where}.zz_bogus" if where else "zz_bogus"
            assert any(v.startswith(f"{expected}: unknown property") for v in violations), (
                spec.name,
                where,
                violations,
            )
            checked += 1
    assert checked > 25


@pytest.mark.parametrize(
    ("given", "meant"),
    [
        ("frame_range", ["frames"]),
        ("rop", ["rop_path"]),
        ("Frames", ["frames"]),
        ("frame", ["frames"]),
        ("camra", ["camera"]),
    ],
)
def test_closest_keys_finds_the_valid_name(given, meant):
    names = ["rop_path", "frames", "output", "camera", "wait_s", "thumbnail", "on"]
    assert closest_keys(given, names) == meant


def test_closest_keys_has_nothing_to_offer_for_an_unrelated_key():
    assert closest_keys("zz_bogus", ["rop_path", "frames", "on"]) == []
    assert closest_keys("on_the_fly", ["rop_path", "frames", "on"]) == []  # "on" is too short


def _bridge(profile="full"):
    return Bridge(BridgeConfig(profile=profile), scan=lambda: [])


def _error(bridge, tool, args):
    result = bridge.call_tool(tool, args)
    assert result.is_error is True
    return json.loads(result.content[0].text)


def test_every_tool_refuses_an_unknown_key_before_any_houdini_is_asked():
    # scan=lambda: [] means no Houdini: a call that got past validation would answer
    # houdini_offline (or launch one), never invalid_argument.
    bridge = _bridge("full")
    for spec in TOOLS:
        error = _error(bridge, spec.name, {"zz_bogus": 1})
        assert error["code"] == "invalid_argument", (spec.name, error)
        assert "zz_bogus: unknown property" in error["message"], (spec.name, error)
        assert f'inspect {{what: "tool", target: "{spec.name}"}}' in error["hint"], spec.name
        assert error["hint"].startswith("zz_bogus is not an argument of "), spec.name


def test_a_typo_of_a_valid_key_is_a_candidate_for_every_tool():
    bridge = _bridge("full")
    for spec in TOOLS:
        props = list(spec.input_schema.get("properties") or {})
        if not props:
            continue
        prop = max(props, key=len)
        error = _error(bridge, spec.name, {f"{prop}_x": 1})
        assert prop in error["candidates"], (spec.name, prop, error)
        assert error["hint"].startswith(f"Use {error['candidates'][0]} instead of {prop}_x."), (
            spec.name
        )


def test_render_with_frame_range_is_invalid_argument_with_frames_as_the_candidate():
    error = _error(_bridge("core"), "render", {"rop_path": "/out/karma1", "frame_range": [1, 24]})
    assert error["code"] == "invalid_argument"
    assert error["message"].startswith("1 argument problem(s) for render: frame_range: unknown")
    assert "did you mean frames?" in error["message"]
    assert error["candidates"] == ["frames"]
    assert 'inspect {what: "tool", target: "render"}' in error["hint"]
    assert error["hint"].startswith("Use frames instead of frame_range.")


def test_an_unknown_key_with_no_close_name_is_named_and_to_be_dropped():
    error = _error(_bridge("core"), "render", {"rop_path": "/out/k", "zz_bogus": 1})
    assert "zz_bogus: unknown property (allowed: rop_path, frames" in error["message"]
    assert "candidates" not in error
    assert error["hint"].startswith("zz_bogus is not an argument of render; drop it.")
    assert 'inspect {what: "tool", target: "render"}' in error["hint"]


def test_the_hint_names_the_reference_route_every_profile_has():
    for profile in ("minimal", "core", "full"):
        error = _error(_bridge(profile), "houdini_status", {"verbose": True})
        assert "houdini_status's reference: " in error["hint"], profile
        assert 'inspect {what: "tool", target: "houdini_status"}' in error["hint"], profile
        assert error["hint"].endswith("or hocuspocus://tools."), profile


def test_nested_unknown_keys_are_named_with_their_path():
    bridge = _bridge("core")
    launch = _error(bridge, "houdini_connect", {"launch": {"mode": "headless", "hipp": "x.hip"}})
    assert "launch.hipp: unknown property; did you mean hip?" in launch["message"]
    assert launch["candidates"] == ["hip"]
    assert 'inspect {what: "tool", target: "houdini_connect"}' in launch["hint"]
    op = _error(bridge, "edit", {"ops": [{"op": "set", "paht": "/obj/a/tx", "value": 1}]})
    assert "ops[0].paht: unknown property; did you mean path, " in op["message"]
    assert op["candidates"][0] == "path"
    assert 'inspect {what: "tool", target: "edit"}' in op["hint"]


def test_candidates_gather_every_unknown_key_without_repeats():
    error = _error(
        _bridge("core"), "render", {"rop_path": "/o", "frame_range": [1, 2], "camra": "/c"}
    )
    assert error["candidates"] == ["frames", "camera"]


def test_the_batch_shape_hint_still_wins_over_the_generic_one():
    error = _error(_bridge("core"), "edit", {"op": "set", "path": "/obj/a/tx", "value": 1})
    assert "pass the op inside ops" in error["hint"]
