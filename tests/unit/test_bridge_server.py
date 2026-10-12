"""Bridge dispatch: tools/list offline, validation, forwarding, error mapping, budget, images,
bridge-local tools, resources and prompts. Uses a fake catalogue and a fake HostClient."""

from __future__ import annotations

import base64
import json
from typing import Any

import anyio
import pytest
from mcp import Client

from hocuspocus.bridge import budget
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.instructions import INSTRUCTIONS
from hocuspocus.bridge.server import Bridge, build_server, get_prompt, list_prompts
from hocuspocus.tools.catalog import ToolSpec
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

OBJ = {"type": "object", "additionalProperties": False}

FAKE_TOOLS = (
    ToolSpec(
        "houdini_status", "Status.", dict(OBJ, properties={}), read_only=True, bridge_local=True
    ),
    ToolSpec(
        "houdini_connect",
        "Connect.",
        dict(
            OBJ,
            properties={
                "pid": {"type": "integer"},
                "launch": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["gui", "headless"]},
                        "hip": {"type": "string"},
                        "wait_s": {"type": "number", "minimum": 1},
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                },
                "disconnect": {"type": "boolean"},
            },
        ),
        bridge_local=True,
    ),
    ToolSpec(
        "node_info",
        "Info.",
        dict(
            OBJ,
            properties={
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "include": {"type": "array", "items": {"type": "string"}},
            },
            required=["paths"],
        ),
        read_only=True,
    ),
    ToolSpec(
        "node_delete",
        "Delete.",
        dict(
            OBJ,
            properties={"paths": {"type": "array", "items": {"type": "string"}}},
            required=["paths"],
        ),
        destructive=True,
    ),
    ToolSpec(
        "viewport_capture",
        "Look.",
        dict(OBJ, properties={"timeout_s": {"type": "number"}}),
        headless_ok=False,
    ),
    ToolSpec(
        "geo_info",
        "Geo.",
        dict(OBJ, properties={"path": {"type": "string"}}, required=["path"]),
        read_only=True,
    ),
    ToolSpec("usd_stage", "USD.", dict(OBJ, properties={}), profile="full"),
)


class FakeClient:
    def __init__(self) -> None:
        self.health_reply: dict[str, Any] = {
            "ok": True,
            "hp": 1,
            "pid": 4242,
            "houdini": "22.0.466",
            "generation": 2,
            "host_version": "1.0.0a0",
        }
        self.replies: dict[str, Any] = {}
        self.calls: list[tuple[str, dict, float]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        if isinstance(self.health_reply, Exception):
            raise self.health_reply
        return self.health_reply

    def call(self, tool, args, timeout_s, request_id=None):
        self.calls.append((tool, args, timeout_s))
        reply = self.replies.get(tool, (True, {"echo": tool}, {"scene_generation": 2}))
        if isinstance(reply, Exception):
            raise reply
        return reply


INSTANCE = Instance(
    pid=4242,
    port=51000,
    token="tok",
    houdini="22.0.466",
    ui=False,
    hip="C:/work/a.hip",
    started="2026-10-12T10:00:00Z",
    label="hython",
)


def make_bridge(instances=(INSTANCE,), config=None, launcher=None, tools=FAKE_TOOLS):
    client = FakeClient()
    live = list(instances)
    bridge = Bridge(
        config or BridgeConfig(),
        tools=tools,
        client_factory=lambda port, token: client,
        scan=lambda: list(live),
        launcher=launcher,
    )
    return bridge, client, live


def structured(result) -> dict:
    return result.structured_content


# -- tools/list ------------------------------------------------------------------------------


def test_tools_list_with_no_houdini_over_mcp_client():
    bridge, _client, _live = make_bridge(instances=())

    async def run():
        async with Client(build_server(bridge)) as client:
            assert client.instructions == INSTRUCTIONS
            listed = (await client.list_tools()).tools
            status = await client.call_tool("houdini_status", {})
            return listed, status

    listed, status = anyio.run(run)
    assert [t.name for t in listed] == [t.name for t in FAKE_TOOLS]
    by_name = {t.name: t for t in listed}
    assert by_name["node_info"].annotations.read_only_hint is True
    assert by_name["node_delete"].annotations.destructive_hint is True
    assert by_name["node_info"].annotations.open_world_hint is False
    assert by_name["viewport_capture"].description.endswith("(GUI only)")
    assert by_name["node_info"].input_schema["required"] == ["paths"]
    assert status.is_error is False
    assert status.structured_content["connected"] is None
    assert status.structured_content["instances"] == []


def test_profile_filters_real_catalogue():
    core = Bridge(BridgeConfig(profile="core"), scan=lambda: [])
    full = Bridge(BridgeConfig(profile="full"), scan=lambda: [])
    assert {t.profile for t in core.tools} <= {"core"}
    assert len(full.tools) >= len(core.tools)


def test_tools_list_is_deterministic():
    bridge, _c, _l = make_bridge()
    assert [t.model_dump() for t in bridge.list_tools()] == [
        t.model_dump() for t in bridge.list_tools()
    ]


def test_instructions_under_400_words():
    assert len(INSTRUCTIONS.split()) <= 400


# -- validation ------------------------------------------------------------------------------


def test_invalid_arguments_return_is_error_without_forwarding():
    bridge, client, _ = make_bridge()
    result = bridge.call_tool("node_info", {"path": "/obj"})
    err = structured(result)
    assert result.is_error is True
    assert err["code"] == "invalid_argument"
    assert "paths: required property is missing" in err["detail"]["violations"]
    assert any("did you mean paths" in v for v in err["detail"]["violations"])
    assert json.loads(result.content[0].text) == err
    assert client.calls == []


def test_unknown_tool_is_protocol_error():
    from mcp.shared.exceptions import MCPError

    bridge, _c, _l = make_bridge()
    with pytest.raises(MCPError):
        bridge.call_tool("usd_stage_typo", {})


# -- forwarding ------------------------------------------------------------------------------


def test_forward_ok_structured_and_text_and_meta():
    bridge, client, _ = make_bridge()
    client.replies["node_info"] = (
        True,
        {"nodes": [{"path": "/obj/geo1"}]},
        {"scene_generation": 7, "elapsed_ms": 3},
    )
    result = bridge.call_tool("node_info", {"paths": ["/obj/geo1"]})
    assert result.is_error is False
    assert result.structured_content == {"nodes": [{"path": "/obj/geo1"}]}
    assert json.loads(result.content[0].text) == result.structured_content
    assert result.content[0].text == budget.dumps(result.structured_content)
    assert result.meta["scene_generation"] == 7
    assert result.meta["pid"] == 4242
    assert client.calls == [("node_info", {"paths": ["/obj/geo1"]}, 30.0)]


def test_forward_uses_timeout_argument():
    bridge, client, _ = make_bridge()
    bridge.call_tool("viewport_capture", {"timeout_s": 120})
    assert client.calls[-1][2] == 120.0


def test_host_error_maps_to_is_error():
    bridge, client, _ = make_bridge()
    error = {
        "code": "node_not_found",
        "message": "No node /obj/nope",
        "hint": "use node_find",
        "candidates": ["/obj/geo1"],
    }
    client.replies["node_info"] = (False, error, {"scene_generation": 2})
    result = bridge.call_tool("node_info", {"paths": ["/obj/nope"]})
    assert result.is_error is True
    assert result.structured_content == error
    assert json.loads(result.content[0].text) == error
    assert result.meta["scene_generation"] == 2


@pytest.mark.parametrize("code", ["delivery_unknown", "houdini_offline", "version_mismatch"])
def test_transport_errors_map_to_is_error(code):
    bridge, client, _ = make_bridge()
    client.replies["node_delete"] = ToolError(code, "boom")
    result = bridge.call_tool("node_delete", {"paths": ["/obj/a"]})
    assert result.is_error is True
    assert result.structured_content["code"] == code
    assert len(client.calls) == 1  # one attempt, never retried


def test_offline_when_no_instances():
    bridge, client, _ = make_bridge(instances=())
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.structured_content["code"] == "houdini_offline"
    assert "houdini_connect" in result.structured_content["hint"]


def test_registry_hp_mismatch_refuses():
    from dataclasses import replace

    bridge, client, _ = make_bridge(instances=(replace(INSTANCE, hp=2),))
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.structured_content["code"] == "version_mismatch"
    assert client.calls == []


def test_health_version_mismatch_refuses_before_call():
    bridge, client, _ = make_bridge()
    client.health_reply = ToolError("version_mismatch", "hp/v2")
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.structured_content["code"] == "version_mismatch"
    assert client.calls == []


def test_multiple_instances_warning_in_meta():
    newer = Instance(pid=5555, port=51001, token="t2", started="2026-10-12T11:00:00Z")
    bridge, client, _ = make_bridge(instances=(INSTANCE, newer))
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.meta["pid"] == 5555
    assert "2 Houdini instances" in result.meta["warnings"][0]


def test_bridge_exception_becomes_internal():
    bridge, client, _ = make_bridge()
    client.replies["node_info"] = RuntimeError("kaboom")
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.is_error is True
    assert result.structured_content["code"] == "internal"
    assert "traceback" in result.structured_content["detail"]


# -- budget and images -----------------------------------------------------------------------


def test_truncation_cuts_lists_at_item_boundaries():
    bridge, client, _ = make_bridge(config=BridgeConfig(max_response_bytes=2048))
    rows = [{"path": f"/obj/geo{i}", "type": "geo", "pad": "x" * 40} for i in range(200)]
    client.replies["node_info"] = (True, {"nodes": rows, "next_cursor": "c1", "total": 200}, {})
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    out = result.structured_content
    assert out["truncated"] is True
    assert out["next_cursor"] == "c1"
    assert 0 < len(out["nodes"]) < 200
    assert out["nodes"] == rows[: len(out["nodes"])]  # whole items, original order
    assert len(result.content[0].text.encode()) <= 2048
    cut = result.meta[budget.TRUNCATION_META_KEY][0]
    assert cut["path"] == "nodes" and cut["total"] == 200 and cut["kept"] == len(out["nodes"])


def test_small_results_are_not_marked_truncated():
    bridge, client, _ = make_bridge()
    client.replies["node_info"] = (True, {"nodes": []}, {})
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert "truncated" not in result.structured_content


def test_budget_truncates_huge_strings_last():
    out, cuts = budget.apply_budget({"stdout": "y" * 50_000, "result": 1}, 4096)
    assert out["truncated"] is True and out["result"] == 1
    assert len(budget.dumps(out)) <= 4096
    assert cuts[0]["path"] == "stdout"


def test_nested_lists_are_truncated():
    data = {"attributes": {"point": [{"name": f"a{i}", "pad": "z" * 50} for i in range(300)]}}
    out, cuts = budget.apply_budget(data, 1500)
    assert len(budget.dumps(out)) <= 1500
    assert cuts[0]["path"] == "attributes.point"


def test_image_is_converted_to_image_content_and_exempt_from_budget():
    bridge, client, _ = make_bridge(config=BridgeConfig(max_response_bytes=512))
    png = base64.b64encode(b"\x89PNG" + b"\0" * 5000).decode()
    client.replies["viewport_capture"] = (
        True,
        {
            "image": {"png_base64": png, "width": 1024, "height": 768},
            "path": "C:/cap.png",
            "camera_used": "/obj/cam1",
        },
        {},
    )
    result = bridge.call_tool("viewport_capture", {})
    kinds = [c.type for c in result.content]
    assert kinds == ["text", "image"]
    assert result.content[1].data == png
    assert result.content[1].mime_type == "image/png"
    sc = result.structured_content
    assert "png_base64" not in json.dumps(sc)
    assert sc["image"]["width"] == 1024 and sc["path"] == "C:/cap.png"
    assert "truncated" not in sc


def test_nested_thumbnail_image_is_extracted():
    rest, images = budget.extract_images(
        {"outputs": ["a.exr"], "thumbnail": {"image": {"png_base64": "QUJD"}}}
    )
    assert len(images) == 1 and images[0].data == "QUJD"
    assert rest["thumbnail"]["image"] == {"attached": True}


# -- bridge-local tools ----------------------------------------------------------------------


def test_status_merges_registry_health_and_host():
    bridge, client, _ = make_bridge()
    client.replies["houdini_status"] = (
        True,
        {
            "pid": 4242,
            "hip": {"path": "C:/work/a.hip", "name": "a.hip", "dirty": True, "is_new": False},
            "time": {"frame": 1, "fps": 24, "range": [1, 240]},
            "env": {"HIP": "C:/work"},
            "scene_generation": 5,
            "host_version": "1.0.0a0",
            "read_only": False,
            "allow_python": True,
        },
        {},
    )
    status = structured(bridge.call_tool("houdini_status", {}))
    conn = status["connected"]
    assert conn["pid"] == 4242 and conn["port"] == 51000 and conn["label"] == "hython"
    assert conn["hip"]["dirty"] is True and conn["time"]["fps"] == 24
    assert conn["scene_generation"] == 5
    assert status["read_only"] is False and status["allow_python"] is True
    assert status["instances"][0]["selected"] is True
    assert "token" not in json.dumps(status)
    assert status["bridge_version"] and status["profile"] == "core"


def test_status_survives_host_error():
    bridge, client, _ = make_bridge()
    client.replies["houdini_status"] = (False, {"code": "houdini_busy", "message": "busy"}, {})
    status = structured(bridge.call_tool("houdini_status", {}))
    assert status["connected"]["pid"] == 4242
    assert status["connected"]["host_error"]["code"] == "houdini_busy"
    assert "read_only" not in status


def test_status_with_dead_listener_reports_warning():
    bridge, client, _ = make_bridge()
    client.health_reply = ToolError("houdini_offline", "refused")
    status = structured(bridge.call_tool("houdini_status", {}))
    assert status["connected"] is None
    assert any("unusable" in w for w in status["warnings"])


def test_connect_pid_pins_selection():
    newer = Instance(pid=5555, port=51001, token="t2", started="2026-10-12T11:00:00Z")
    bridge, client, _ = make_bridge(instances=(INSTANCE, newer))
    result = bridge.call_tool("houdini_connect", {"pid": 4242})
    assert result.is_error is False
    assert result.structured_content["connected"]["pid"] == 4242
    forwarded = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert forwarded.meta["pid"] == 4242
    assert "warnings" not in forwarded.meta


def test_connect_unknown_pid_lists_candidates():
    bridge, _c, _l = make_bridge()
    err = structured(bridge.call_tool("houdini_connect", {"pid": 1}))
    assert err["code"] == "houdini_offline" and err["candidates"] == ["4242"]


def test_connect_rejects_two_modes():
    bridge, _c, _l = make_bridge()
    err = structured(bridge.call_tool("houdini_connect", {"pid": 4242, "disconnect": True}))
    assert err["code"] == "invalid_argument"


def test_disconnect_then_reconnect():
    bridge, client, _ = make_bridge()
    out = structured(bridge.call_tool("houdini_connect", {"disconnect": True}))
    assert out["connected"] is None
    err = structured(bridge.call_tool("node_info", {"paths": ["/obj"]}))
    assert err["code"] == "houdini_offline"
    assert structured(bridge.call_tool("houdini_status", {}))["connected"] is None
    again = structured(bridge.call_tool("houdini_connect", {}))
    assert again["connected"]["pid"] == 4242
    assert bridge.call_tool("node_info", {"paths": ["/obj"]}).is_error is False


def test_pinned_instance_exit_falls_back_to_new_one():
    bridge, client, live = make_bridge()
    bridge.call_tool("houdini_connect", {"pid": 4242})
    live.clear()
    live.append(Instance(pid=7777, port=51002, token="t3", started="2026-10-12T12:00:00Z"))
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.meta["pid"] == 7777
    assert any("4242" in w for w in result.meta["warnings"])


# -- resources and prompts -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "tool", "args"),
    [
        ("houdini://node//obj/geo1", "node_info", {"paths": ["/obj/geo1"]}),
        (
            "houdini://node/obj/geo1/parms",
            "node_info",
            {"paths": ["/obj/geo1"], "include": ["parms"]},
        ),
        ("houdini://node/%2Fobj%2Fgeo1%2Fbox1/geo", "geo_info", {"path": "/obj/geo1/box1"}),
        ("houdini://nodetype/Sop/scatter", "node_type_info", {"type": "Sop/scatter"}),
        ("houdini://job/abc123", "job", {"action": "status", "job_id": "abc123"}),
        ("houdini://status", "houdini_status", {}),
    ],
)
def test_resource_routing(uri, tool, args):
    bridge, _c, _l = make_bridge()
    assert bridge.route_resource(uri) == (tool, args)


def test_read_resource_forwards_and_errors():
    from mcp.shared.exceptions import MCPError

    bridge, client, _ = make_bridge()
    client.replies["geo_info"] = (True, {"point_count": 8}, {})
    res = bridge.read_resource("houdini://node/obj/geo1/geo")
    assert json.loads(res.contents[0].text) == {"point_count": 8}
    client.replies["geo_info"] = (False, {"code": "node_not_found", "message": "nope"}, {})
    with pytest.raises(MCPError):
        bridge.read_resource("houdini://node/obj/missing/geo")
    with pytest.raises(MCPError):
        bridge.read_resource("houdini://bogus")


def test_resources_over_mcp_client():
    bridge, _c, _l = make_bridge(instances=())

    async def run():
        async with Client(build_server(bridge)) as client:
            resources = (await client.list_resources()).resources
            templates = (await client.list_resource_templates()).resource_templates
            guide = await client.read_resource("hocuspocus://guide")
            status = await client.read_resource("houdini://status")
            prompts = (await client.list_prompts()).prompts
            prompt = await client.get_prompt("build_sop_chain", {"description": "a torus"})
            return resources, templates, guide, status, prompts, prompt

    resources, templates, guide, status, prompts, prompt = anyio.run(run)
    assert {str(r.uri) for r in resources} == {"houdini://status", "hocuspocus://guide"}
    assert "houdini://nodetype/{category}/{name}" in {t.uri_template for t in templates}
    assert "HocusPocus drives a live Houdini" in guide.contents[0].text
    assert json.loads(status.contents[0].text)["connected"] is None
    assert [p.name for p in prompts] == [
        "inspect_scene",
        "build_sop_chain",
        "debug_red_node",
        "turntable_preview",
    ]
    assert "a torus" in prompt.messages[0].content.text


def test_prompt_requires_arguments():
    from mcp.shared.exceptions import MCPError

    assert len(list_prompts()) == 4
    with pytest.raises(MCPError):
        get_prompt("debug_red_node", {})
    assert "/obj" in get_prompt("inspect_scene", None).messages[0].content.text
