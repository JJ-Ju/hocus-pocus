"""``inspect {what: "guide" | "tool"}`` (2.1, D54; review 26 P1 #10): the guide and one
tool's reference through a tool, for clients that cannot read MCP resources, answered by
the bridge with or without a Houdini; and hints that cite a resource name that route."""

from __future__ import annotations

import json

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instructions import guide_sections, guide_text
from hocuspocus.bridge.server import Bridge
from hocuspocus.tools.docs import tool_section


def offline(profile: str = "core") -> Bridge:
    """A bridge with no Houdini at all: the docs reads must not need one."""
    return Bridge(BridgeConfig(profile=profile), scan=lambda: [])


def call(bridge: Bridge, args: dict) -> tuple[bool, dict]:
    result = bridge.call_tool("inspect", args)
    return not result.is_error, json.loads(result.content[0].text)


def test_guide_without_target_is_the_whole_guide_with_its_topics():
    ok, out = call(offline(), {"what": "guide"})
    assert ok, out
    assert out["text"] == guide_text()
    assert out["etag"].startswith("bridge:")
    assert "Copernicus (COP) images" in out["topics"]


def test_guide_topic_is_its_section():
    ok, out = call(offline(), {"what": "guide", "target": "copernicus"})
    assert ok, out
    assert out["text"].startswith("### Copernicus (COP) images")
    assert "### Flipbook frames" not in out["text"]
    ok, out = call(offline(), {"what": "guide", "target": "Spare Parm"})
    assert ok and out["text"].startswith("### Add a spare parm")
    ok, recipes = call(offline(), {"what": "guide", "target": "recipes"})
    assert ok and "### Two Houdinis" in recipes["text"]  # a ## section holds its ###


def test_unknown_guide_topic_lists_the_topics():
    ok, out = call(offline(), {"what": "guide", "target": "fluids"})
    assert not ok and out["code"] == "invalid_argument"
    assert out["candidates"] == [title for title, _ in guide_sections()]


def test_tool_reference_is_the_docs_section_of_that_tool():
    bridge = offline()
    ok, out = call(bridge, {"what": "tool", "target": "look"})
    assert ok, out
    spec = next(s for s in bridge.tools if s.name == "look")
    assert out["text"] == tool_section(spec)
    assert out["text"].startswith("## look") and "**Notes.**" in out["text"]


def test_tool_needs_a_target_known_to_the_profile():
    ok, out = call(offline(), {"what": "tool"})
    assert not ok and out["code"] == "invalid_argument" and "look" in out["candidates"]
    ok, out = call(offline("core"), {"what": "tool", "target": "pdg"})  # full only
    assert not ok and out["code"] == "invalid_argument"
    ok, out = call(offline(), {"what": "tool", "target": "lok"})
    assert not ok and out["candidates"][0] == "look"
    ok, out = call(offline(), {"what": "tool", "target": "node_info"})
    assert not ok and "inspect what: node" in out["hint"]


def test_docs_reads_take_no_other_option():
    ok, out = call(offline(), {"what": "guide", "detail": "full"})
    assert not ok and out["code"] == "invalid_argument" and "detail" in out["message"]


def test_guide_points_at_the_instructions_and_its_topic_has_them():
    """2.1 (D65): the guide does not repeat the server instructions; its ``instructions``
    topic is them, for a client that dropped them."""
    from hocuspocus.bridge.instructions import INSTRUCTIONS

    ok, out = call(offline(), {"what": "guide"})
    assert ok and INSTRUCTIONS not in out["text"] and "Instructions" in out["topics"]
    assert 'inspect {what: "guide", target: "instructions"}' in out["text"]
    ok, out = call(offline(), {"what": "guide", "target": "instructions"})
    assert ok and out["text"].startswith("## Instructions") and INSTRUCTIONS in out["text"]
    assert "## Resources" not in out["text"]


def test_instructions_name_the_tool_route_to_the_docs():
    from hocuspocus.bridge.instructions import INSTRUCTIONS

    assert 'inspect {what: "guide"' in INSTRUCTIONS
    assert 'inspect {what: "tool", target: name}' in INSTRUCTIONS


def test_argument_hints_name_the_running_tools_reference():
    from hocuspocus.host import dispatch
    from hocuspocus.host.tools._common import ARG_HINT, bad_arg, reference_hint

    assert bad_arg("x").hint == ARG_HINT  # outside a call
    dispatch._CALL.tool = "edit"
    try:
        hint = bad_arg("x").hint
    finally:
        dispatch._CALL.tool = None
    assert 'inspect {what: "tool", target: "edit"}' in hint and "hocuspocus://tools" in hint
    assert reference_hint("search").startswith('inspect {what: "tool", target: "search"}')
