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
from hocuspocus.tools.catalog import ToolSpec, for_profile
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Launch records and registry reads stay in a temp state dir."""
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


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
                "quit": {"type": "boolean"},
                "on_unsaved": {"type": "string", "enum": ["fail", "save", "discard"]},
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
    ToolSpec("usd_stage", "USD.", dict(OBJ, properties={}), profiles=("compat_1x",)),
)


class FakeClient:
    def __init__(self) -> None:
        self.health_reply: dict[str, Any] = {
            "ok": True,
            "hp": 1,
            "pid": 4242,
            "houdini": "22.0.466",
            "generation": 2,
            "host_version": "2.0.0",
        }
        self.replies: dict[str, Any] = {}
        self.calls: list[tuple[str, dict, float]] = []
        self.budgets: list[int | None] = []

    live: list[Instance] = []
    port: int | None = None
    follow_registry = True
    """Answer /health with the pid registered for the port asked (a healthy registry)."""

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        if isinstance(self.health_reply, Exception):
            raise self.health_reply
        reply = dict(self.health_reply)
        match = next((i.pid for i in self.live if i.port == self.port), None)
        if self.follow_registry and match is not None:
            reply["pid"] = match
        return reply

    def quit(self, on_unsaved="fail", timeout_s=70.0):
        self.calls.append(("<quit>", {"on_unsaved": on_unsaved}, timeout_s))
        reply = self.replies.get(
            "<quit>",
            (True, {"quitting": True, "pid": 4242, "hip": "C:/work/a.hip", "saved": False}, {}),
        )
        if isinstance(reply, Exception):
            raise reply
        return reply

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append((tool, args, timeout_s))
        self.budgets.append(max_response_bytes)
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
    client.live = live

    def factory(port, token):
        client.port = port
        return client

    bridge = Bridge(
        config or BridgeConfig(),
        tools=tools,
        client_factory=factory,
        scan=lambda: list(live),
        launcher=launcher,
    )
    bridge.exit_grace_s = 0.0
    return bridge, client, live


def structured(result) -> dict:
    """The result's JSON as the model sees it (the text block; ``result_content = "text"``,
    the default, sends no structuredContent)."""
    return json.loads(result.content[0].text)


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
    assert structured(status)["connected"] is None
    assert structured(status)["instances"] == []


def test_profile_filters_real_catalogue():
    core = Bridge(BridgeConfig(profile="core"), scan=lambda: [])
    full = Bridge(BridgeConfig(profile="full"), scan=lambda: [])
    assert all("core" in t.profiles for t in core.tools)
    assert len(full.tools) >= len(core.tools)
    minimal = Bridge(BridgeConfig(profile="minimal"), scan=lambda: [])
    names = {t.name for t in for_profile("minimal")}
    assert len(names) == 10
    assert {t.name for t in minimal.tools} == names
    assert {t.name for t in minimal.list_tools()} == names


def test_tools_list_is_deterministic():
    bridge, _c, _l = make_bridge()
    assert [t.model_dump() for t in bridge.list_tools()] == [
        t.model_dump() for t in bridge.list_tools()
    ]


def test_instructions_cover_launch_lifetime_and_guide_recipes():
    from hocuspocus.bridge.instructions import guide_text

    assert "launched.outlives_server" in INSTRUCTIONS and "attach by pid" in INSTRUCTIONS
    assert 'detail: "folders"' in INSTRUCTIONS and "spare_parms" in INSTRUCTIONS
    assert "hocuspocus launch" in INSTRUCTIONS and "houdini://outline" in INSTRUCTIONS
    guide = guide_text()
    assert guide.index("## Instructions") < guide.index("## Resources") < guide.index("## Recipes")
    assert '"spare_parms": {"add": [' in guide
    assert 'network_describe {root: "/", format: "outline", depth: 2}' in guide


def test_outline_resource_reads_network_describe_outline():
    from hocuspocus.bridge.server import OUTLINE_ARGS

    bridge, client, _ = make_bridge()
    assert OUTLINE_ARGS == {"root": "/", "format": "outline", "depth": 2}
    assert bridge.route_resource("houdini://outline") == ("network_describe", OUTLINE_ARGS)
    assert "houdini://outline" in [str(r.uri) for r in bridge.list_resources()]
    client.replies["network_describe"] = (True, {"nodes": [{"path": "/obj"}]}, {})
    result = bridge.read_resource("houdini://outline")
    assert json.loads(result.contents[0].text) == {"nodes": [{"path": "/obj"}]}
    assert client.calls[-1][:2] == ("network_describe", OUTLINE_ARGS)


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
    # Review 07 papercut 10: suggest the nearest tool like every other error does.
    with pytest.raises(MCPError) as info:
        bridge.call_tool("node_inf", {})
    assert "Did you mean node_info" in str(info.value)
    assert info.value.error.data["candidates"][0] == "node_info"


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
    assert result.content[0].text == budget.dumps({"nodes": [{"path": "/obj/geo1"}]})
    assert result.structured_content is None  # result_content = "text" (the default)
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
    assert structured(result) == error
    assert json.loads(result.content[0].text) == error
    assert result.meta["scene_generation"] == 2


@pytest.mark.parametrize("code", ["delivery_unknown", "houdini_offline", "version_mismatch"])
def test_transport_errors_map_to_is_error(code):
    bridge, client, _ = make_bridge()
    client.replies["node_delete"] = ToolError(code, "boom")
    result = bridge.call_tool("node_delete", {"paths": ["/obj/a"]})
    assert result.is_error is True
    assert structured(result)["code"] == code
    assert len(client.calls) == 1  # one attempt, never retried


def test_offline_when_no_instances():
    bridge, client, _ = make_bridge(instances=())
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert structured(result)["code"] == "houdini_offline"
    assert "houdini_connect" in structured(result)["hint"]
    assert structured(result)["retryable"] is False  # nothing to retry against


def test_offline_names_the_houdini_that_exited():
    """Review 07 papercut 8: say which Houdini died and that its unsaved work is gone."""
    bridge, client, live = make_bridge()
    assert bridge.call_tool("node_info", {"paths": ["/obj"]}).is_error is False
    live.clear()
    error = structured(bridge.call_tool("node_info", {"paths": ["/obj"]}))
    assert error["code"] == "houdini_offline"
    assert "pid 4242" in error["message"] and "since its last save are lost" in error["message"]
    assert error["retryable"] is False
    assert "hip: 'C:/work/a.hip'" in error["hint"]
    assert error["detail"] == {"pid": 4242, "hip": "C:/work/a.hip"}


def test_offline_names_the_earlier_server_that_launched_houdini(tmp_path):
    """Review 11 B1: a later bridge says why nothing runs and how to keep Houdini alive."""
    from hocuspocus.bridge.instances import LaunchLog

    launches = LaunchLog(tmp_path / "launches")
    launches.directory.mkdir(parents=True)
    (launches.directory / "22740.json").write_text(
        json.dumps({"pid": 22740, "launched_by": 51010, "mode": "headless", "hip": ""})
    )
    client = FakeClient()
    bridge = Bridge(
        BridgeConfig(),
        tools=FAKE_TOOLS,
        client_factory=lambda port, token: client,
        scan=lambda: [],
        launches=launches,
    )
    error = structured(bridge.call_tool("node_info", {"paths": ["/obj"]}))
    assert error["code"] == "houdini_offline" and error["retryable"] is False
    assert "pid 22740" in error["message"] and "server (pid 51010)" in error["message"]
    assert "keep one MCP session open" in error["hint"] and "{pid}" in error["hint"]
    assert error["detail"]["launched_by"] == 51010
    again = structured(bridge.call_tool("node_info", {"paths": ["/obj"]}))
    assert "22740" not in again["message"]  # reported once


def test_exit_mid_call_is_reported_as_an_exit():
    bridge, client, live = make_bridge()

    def die(*_args, **_kwargs):
        live.clear()
        raise ToolError("delivery_unknown", "ConnectionResetError: [WinError 10054]")

    client.call = die
    error = structured(bridge.call_tool("node_delete", {"paths": ["/obj/a"]}))
    assert error["code"] == "houdini_offline"
    assert "exited while running node_delete" in error["message"]
    assert error["retryable"] is False
    assert "ConnectionResetError" in error["detail"]["transport"]


def test_lost_response_from_a_live_houdini_stays_delivery_unknown():
    bridge, client, _ = make_bridge()
    client.replies["node_delete"] = ToolError("delivery_unknown", "timed out")
    error = structured(bridge.call_tool("node_delete", {"paths": ["/obj/a"]}))
    assert error["code"] == "delivery_unknown"
    assert error["retryable"] is False


def test_switch_after_exit_warns_once_with_the_old_pid():
    bridge, client, live = make_bridge()
    bridge.call_tool("node_info", {"paths": ["/obj"]})
    live[:] = [Instance(pid=7777, port=51002, token="t3", started="2026-10-12T12:00:00Z")]
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.meta["pid"] == 7777
    assert any("pid 4242" in w and "lost" in w for w in result.meta["warnings"])
    again = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert not again.meta.get("warnings")


def test_registry_hp_mismatch_refuses():
    from dataclasses import replace

    bridge, client, _ = make_bridge(instances=(replace(INSTANCE, hp=2),))
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert structured(result)["code"] == "version_mismatch"
    assert client.calls == []


def test_health_version_mismatch_refuses_before_call():
    bridge, client, _ = make_bridge()
    client.health_reply = ToolError("version_mismatch", "hp/v2")
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert structured(result)["code"] == "version_mismatch"
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
    assert structured(result)["code"] == "internal"
    assert "traceback" in structured(result)["detail"]


# -- budget and images -----------------------------------------------------------------------


def test_truncation_cuts_lists_at_item_boundaries():
    bridge, client, _ = make_bridge(config=BridgeConfig(max_response_bytes=2048))
    rows = [{"path": f"/obj/geo{i}", "type": "geo", "pad": "x" * 40} for i in range(200)]
    client.replies["node_info"] = (True, {"nodes": rows, "total": 200}, {})
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    out = structured(result)
    assert out["truncated"] is True and "next_cursor" not in out
    assert 0 < len(out["nodes"]) < 200
    assert out["nodes"] == rows[: len(out["nodes"])]  # whole items, original order
    assert len(result.content[0].text.encode()) <= 2048
    cut = result.meta[budget.TRUNCATION_META_KEY][0]
    assert cut["path"] == "nodes" and cut["total"] == 200 and cut["kept"] == len(out["nodes"])
    assert client.budgets[-1] == 2048  # the host learns the budget and pages by it


ROWS = [{"path": f"/obj/geo{i}", "type": "geo", "pad": "x" * 40} for i in range(1000)]


def test_paged_trim_rewrites_an_offset_cursor_so_no_row_is_skipped():
    """Review 10 #3: 1,000 rows kept 96 and the cursor still said 1000."""
    page = {"nodes": ROWS[:1000], "total": 1000}
    out, cuts = budget.apply_budget(page, 16_384, {"limit": 1000}, pageable=True)
    kept = len(out["nodes"])
    assert 0 < kept < 1000 and out["truncated"] is True
    assert out["next_cursor"] == str(kept) and cuts[0]["kept"] == kept
    assert len(budget.dumps(out)) <= 16_384
    # A later page: the host said "1100"; the bridge resumes right after the kept rows.
    middle = {"nodes": ROWS[100:600], "next_cursor": "600", "total": 1000}
    out, _ = budget.apply_budget(middle, 4096, {"cursor": "100", "limit": 500}, pageable=True)
    assert out["next_cursor"] == str(100 + len(out["nodes"]))
    assert out["nodes"] == ROWS[100 : 100 + len(out["nodes"])]


def test_paged_result_with_an_opaque_cursor_is_never_trimmed():
    page = {"nodes": ROWS[:300], "next_cursor": "after:/obj/geo299", "total": 1000}
    out, cuts = budget.apply_budget(page, 4096, {"cursor": "after:/obj/a"}, pageable=True)
    assert out["nodes"] == ROWS[:300] and out["next_cursor"] == "after:/obj/geo299"
    assert out["over_budget"] is True and "truncated" not in out
    assert cuts == [{"over_budget": True, "bytes": budget.size(page), "max_bytes": 4096}]
    problems = {"problems": ROWS[:300], "next_cursor": "50@1200"}
    assert budget.apply_budget(problems, 4096, {}, pageable=True)[0]["problems"] == ROWS[:300]


def test_small_results_are_not_marked_truncated():
    bridge, client, _ = make_bridge()
    client.replies["node_info"] = (True, {"nodes": []}, {})
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert "truncated" not in structured(result)


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
    sc = structured(result)
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
            "host_version": "2.0.0",
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


def test_status_prints_the_hip_path_once():
    """Review 25 papercut 10: hip.path stays; name, the identical recent entry, env.HIP,
    env.JOB, env.HIPNAME and the connected row's hip, which repeat it, are left out (2.0)."""
    bridge, client, _ = make_bridge()
    path = "C:/work/a.hip"
    client.replies["houdini_status"] = (
        True,
        {
            "pid": 4242,
            "hip": {"path": path, "name": "a.hip", "dirty": False, "recent": [path, "C:/b.hip"]},
            "env": {"HIP": "C:/work", "JOB": "C:/work", "HIPNAME": "a"},
        },
        {},
    )
    status = structured(bridge.call_tool("houdini_status", {}))
    conn = status["connected"]
    assert conn["hip"] == {"path": path, "dirty": False, "recent": ["C:/b.hip"]}
    assert "env" not in conn
    assert "hip" not in status["instances"][0]
    assert json.dumps(status).count("a.hip") == 1
    # What differs from the path stays.
    client.replies["houdini_status"] = (
        True,
        {
            "pid": 4242,
            "hip": {"path": path, "recent": [path]},
            "env": {"HIP": "C:/w", "JOB": "D:/j"},
        },
        {},
    )
    conn = structured(bridge.call_tool("houdini_status", {}))["connected"]
    assert conn["hip"] == {"path": path} and conn["env"] == {"HIP": "C:/w", "JOB": "D:/j"}


def test_compat_status_keeps_the_14_hip_fields():
    bridge, client, _ = make_bridge(config=BridgeConfig(profile="compat_1x"))
    client.replies["houdini_status"] = (
        True,
        {"pid": 4242, "hip": {"path": "C:/work/a.hip", "name": "a.hip"}, "env": {"HIP": "C:/work"}},
        {},
    )
    status = structured(bridge.call_tool("houdini_status", {}))
    assert status["connected"]["hip"]["name"] == "a.hip"
    assert status["connected"]["env"] == {"HIP": "C:/work"}


def test_server_info_only_in_the_handshake():
    """Review 25 papercut 4: serverInfo is stamped on initialize/server/discover only; a
    tool result keeps _meta.instance and timing without it."""
    import anyio
    from mcp import types as mcp_types

    from hocuspocus.bridge.server import build_server, server_info_once

    key = mcp_types.SERVER_INFO_META_KEY
    stamp = {"name": "hocuspocus", "version": "2.0.0"}
    stamped = {
        "content": [],
        "_meta": {"instance": {"pid": 1}, "timing": {"main_thread_ms": 1}, key: stamp},
    }

    def run(method: str, result: Any) -> Any:
        async def call_next(ctx: Any) -> Any:
            return result

        ctx = type("Ctx", (), {"method": method})()
        return anyio.run(server_info_once, ctx, call_next)

    out = run("tools/call", stamped)
    assert out["_meta"] == {"instance": {"pid": 1}, "timing": {"main_thread_ms": 1}}
    assert key in stamped["_meta"]  # the result it was given is not changed
    assert "_meta" not in run("resources/read", {"contents": [], "_meta": {key: stamp}})
    for method in ("server/discover", "initialize"):
        assert run(method, stamped)["_meta"][key] == stamp
    assert run("notifications/initialized", None) is None
    server = build_server(Bridge(BridgeConfig(), scan=lambda: []))
    assert server_info_once in server.middleware


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
    assert structured(result)["connected"]["pid"] == 4242
    forwarded = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert forwarded.meta["pid"] == 4242
    assert "warnings" not in forwarded.meta


def test_connect_unknown_pid_lists_candidates():
    bridge, _c, _l = make_bridge()
    err = structured(bridge.call_tool("houdini_connect", {"pid": 1}))
    assert err["code"] == "houdini_offline" and err["retryable"] is False
    assert err["candidates"] == [
        {"pid": 4242, "label": "hython", "ui": False, "hip": "C:/work/a.hip"}
    ]
    assert "4242 (hython, headless, a.hip)" in err["message"]


def test_connect_rejects_two_modes():
    bridge, _c, _l = make_bridge()
    err = structured(bridge.call_tool("houdini_connect", {"pid": 4242, "disconnect": True}))
    assert err["code"] == "invalid_argument"


@pytest.fixture
def quick_quit(monkeypatch):
    from hocuspocus.bridge import local_tools

    monkeypatch.setattr(local_tools, "QUIT_WAIT_S", 0.0)
    monkeypatch.setattr(local_tools.registry, "pid_alive", lambda pid: False)


def test_quit_selected_houdini(quick_quit):
    bridge, client, _ = make_bridge()
    bridge.call_tool("houdini_connect", {"pid": 4242})
    out = structured(bridge.call_tool("houdini_connect", {"quit": True, "on_unsaved": "save"}))
    assert out == {"quit": True, "pid": 4242, "exited": True}
    assert ("<quit>", {"on_unsaved": "save"}, 70.0) in client.calls
    assert bridge.preferred_pid is None and bridge.last_target is None


def test_quit_refused_with_unsaved_changes(quick_quit):
    bridge, client, _ = make_bridge()
    client.replies["<quit>"] = (
        False,
        {"code": "unsaved_changes", "message": "The scene has unsaved changes.", "hint": "x"},
        {},
    )
    result = bridge.call_tool("houdini_connect", {"quit": True})
    assert result.is_error is True
    assert structured(result)["code"] == "unsaved_changes"
    assert client.calls[-1][1] == {"on_unsaved": "fail"}


def test_quit_argument_errors(quick_quit):
    bridge, _c, _l = make_bridge()
    err = structured(
        bridge.call_tool("houdini_connect", {"quit": True, "launch": {"mode": "headless"}})
    )
    assert err["code"] == "invalid_argument"
    err = structured(bridge.call_tool("houdini_connect", {"on_unsaved": "save"}))
    assert err["code"] == "invalid_argument" and "quit" in err["message"]
    err = structured(bridge.call_tool("houdini_connect", {"quit": True, "pid": 1}))
    assert err["code"] == "houdini_offline" and err["candidates"][0]["pid"] == 4242


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


def test_pinned_instance_exit_never_falls_back_to_new_one():
    """Review 19 papercut 1: a dead pin is instance_lost, not a silent switch."""
    bridge, client, live = make_bridge()
    bridge.call_tool("houdini_connect", {"pid": 4242})
    live.clear()
    live.append(Instance(pid=7777, port=51002, token="t3", started="2026-10-12T12:00:00Z"))
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert structured(result)["code"] == "instance_lost"
    assert structured(result)["candidates"][0]["pid"] == 7777
    assert [c[0] for c in client.calls] == ["houdini_status"]  # only the connect's status


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
        (
            "houdini://nodetype/Sop/scatter",
            "node_type_info",
            {"type": "Sop/scatter", "detail": "full"},
        ),
        ("houdini://job/abc123", "job", {"action": "status", "job_id": "abc123"}),
        ("houdini://status", "houdini_status", {}),
        (
            "houdini://outline",
            "network_describe",
            {"root": "/", "format": "outline", "depth": 2},
        ),
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
    # The 1.4 resources; every 2.0 profile serves the 2.0 ones (test_bridge_resources.py).
    bridge, _c, _l = make_bridge(instances=(), config=BridgeConfig(profile="compat_1x"))

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
    assert {str(r.uri) for r in resources} == {
        "houdini://status",
        "houdini://outline",
        "hocuspocus://guide",
        "hocuspocus://tools",
    }
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

    from hocuspocus.bridge.instructions import PROMPTS

    assert [p.name for p in list_prompts()] == list(PROMPTS) and len(PROMPTS) == 7
    assert [p.name for p in list_prompts("core")] == list(PROMPTS)
    assert len(list_prompts("compat_1x")) == 4  # the 1.4 prompts
    for profile in (None, "compat_1x"):
        with pytest.raises(MCPError):
            get_prompt("debug_red_node", {}, profile)
        assert "/obj" in get_prompt("inspect_scene", None, profile).messages[0].content.text
    assert "inspect" in get_prompt("inspect_scene", None).messages[0].content.text
    assert (
        "network_describe"
        in get_prompt("inspect_scene", None, "compat_1x").messages[0].content.text
    )


@pytest.mark.parametrize("profile", ["core", "compat_1x"])
def test_instructions_guide_and_prompts_follow_the_profile(profile):
    """spec-2.0 §2.8, §8: the 2.0 profiles get the 2.0 texts and the seven prompts,
    compat_1x the 1.4 texts and the four 1.4 prompts; each guide stays within its cap."""
    from hocuspocus.bridge.instructions import (
        GUIDE_MAX_BYTES,
        INSTRUCTIONS_1X,
        PROMPTS,
        guide_text,
    )
    from hocuspocus.bridge.server import PROMPTS_1X

    bridge, _c, _l = make_bridge(instances=(), config=BridgeConfig(profile=profile))
    compat = profile == "compat_1x"

    async def run():
        async with Client(build_server(bridge)) as client:
            guide = await client.read_resource("hocuspocus://guide")
            prompts = (await client.list_prompts()).prompts
            return client.instructions, guide.contents[0].text, prompts

    instructions, guide, prompts = anyio.run(run)
    assert instructions == (INSTRUCTIONS_1X if compat else INSTRUCTIONS)
    assert guide == guide_text(profile) and len(guide.encode("utf-8")) <= GUIDE_MAX_BYTES
    assert guide != guide_text("core" if compat else "compat_1x")
    assert [p.name for p in prompts] == list(PROMPTS_1X if compat else PROMPTS)


# -- progress notifications (BIBLE §7) ----------------------------------------------------


class ProgressClient(FakeClient):
    """A host whose call blocks while its job advances; call_jobs reports the job."""

    def __init__(self, steps):
        super().__init__()
        self.steps = list(steps)
        self.polls = 0
        self.request_ids = []
        self.job_ids = []

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        import time

        self.request_ids.append(request_id)
        deadline = time.monotonic() + 5
        while self.polls < len(self.steps) + 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        return True, {"job_id": "j1", "state": "running"}, {}

    def _next(self):
        snapshot = self.steps[min(self.polls, len(self.steps) - 1)]
        self.polls += 1
        return snapshot

    def call_jobs(self, request_id, timeout_s=5.0):
        assert request_id == self.request_ids[-1]
        return [self._next()]

    def job(self, job_id, timeout_s=10.0):
        self.job_ids.append(job_id)
        return True, self._next(), {}


def _progress_run(bridge, tool, args):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async def run():
        async with Client(build_server(bridge)) as client:
            return await client.call_tool(tool, args, progress_callback=on_progress)

    return anyio.run(run), seen


def test_progress_notifications_follow_the_call_job():
    steps = [
        {"state": "running"},  # nothing reported yet
        {"state": "running", "current": 1, "total": 4, "progress": 0.25, "message": "frame 1/4"},
        {"state": "running", "current": 1, "total": 4, "progress": 0.25, "message": "frame 1/4"},
        {"state": "running", "current": 3, "total": 4, "progress": 0.75, "message": "frame 3/4"},
    ]
    bridge, _client, _live = make_bridge()
    client = ProgressClient(steps)
    bridge.client_factory = lambda port, token: client
    bridge.progress_interval_s = 0.02
    result, seen = _progress_run(bridge, "geo_info", {"path": "/obj/geo1"})
    assert result.is_error is False
    # Repeated snapshots are not re-sent: progress only ever increases.
    assert seen == [(1.0, 4.0, "frame 1/4"), (3.0, 4.0, "frame 3/4")]
    assert client.request_ids[0]  # the bridge names the call so the host can file its job


def test_progress_for_the_job_tool_polls_its_job_id():
    steps = [{"state": "running", "progress": 0.5}, {"state": "running", "progress": 0.9}]
    tools = (
        *FAKE_TOOLS,
        ToolSpec("job", "Job.", dict(OBJ, properties={"job_id": {"type": "string"}})),
    )
    bridge, _client, _live = make_bridge(tools=tools)
    client = ProgressClient(steps)
    bridge.client_factory = lambda port, token: client
    bridge.progress_interval_s = 0.02
    _result, seen = _progress_run(bridge, "job", {"job_id": "abc"})
    assert set(client.job_ids) == {"abc"}
    assert seen == [(0.5, 1.0, None), (0.9, 1.0, None)]


def test_no_progress_token_means_no_polling():
    bridge, client, _live = make_bridge()
    bridge.progress_interval_s = 0.0

    async def run():
        async with Client(build_server(bridge)) as mcp_client:
            return await mcp_client.call_tool("node_info", {"paths": ["/obj"]})

    assert anyio.run(run).is_error is False  # FakeClient has no call_jobs: never asked


def test_progress_tracker_only_increases():
    from hocuspocus.bridge.server import ProgressTracker

    tracker = ProgressTracker()
    assert tracker.update(None) is None
    assert tracker.update({"message": "starting"}) is None
    assert tracker.update({"progress": 0.0}) == (0.0, 1.0, None)
    assert tracker.update({"progress": 0.0, "message": "x"}) is None
    assert tracker.update({"current": 0, "total": 0, "progress": 0.5}) == (0.5, 1.0, None)


# -- result_content (BIBLE §4.1, review 11 B13a) -------------------------------------------


def _mode_bridge(mode):
    bridge, client, _ = make_bridge(config=BridgeConfig(result_content=mode))
    client.replies["node_info"] = (True, {"nodes": [{"path": "/obj/geo1"}]}, {})
    client.replies["node_delete"] = (
        False,
        {"code": "node_not_found", "message": "No node at /obj/x.", "retryable": False},
        {},
    )
    return bridge


def test_result_content_text_is_the_default_and_drops_output_schemas():
    assert BridgeConfig().result_content == "text"
    bridge = _mode_bridge("text")
    ok = bridge.call_tool("node_info", {"paths": ["/obj/geo1"]})
    assert ok.structured_content is None
    assert json.loads(ok.content[0].text) == {"nodes": [{"path": "/obj/geo1"}]}
    error = bridge.call_tool("node_delete", {"paths": ["/obj/x"]})
    assert error.is_error is True and error.structured_content is None
    assert json.loads(error.content[0].text)["code"] == "node_not_found"
    # The spec requires structuredContent whenever outputSchema is declared.
    assert all(tool.output_schema is None for tool in bridge.list_tools())


def test_result_content_both_duplicates_and_declares_output_schemas():
    from hocuspocus.tools import catalog

    bridge = _mode_bridge("both")
    ok = bridge.call_tool("node_info", {"paths": ["/obj/geo1"]})
    assert ok.structured_content == {"nodes": [{"path": "/obj/geo1"}]}
    assert json.loads(ok.content[0].text) == ok.structured_content
    error = bridge.call_tool("node_delete", {"paths": ["/obj/x"]})
    assert error.structured_content["code"] == "node_not_found"
    assert json.loads(error.content[0].text) == error.structured_content
    real = Bridge(BridgeConfig(result_content="both"), scan=lambda: [])
    by_name = {tool.name: tool for tool in real.list_tools()}
    with_schema = [spec.name for spec in real.tools if spec.output_schema is not None]
    assert with_schema and all(by_name[name].output_schema for name in with_schema)
    listed = catalog.v2_spec(catalog.get(with_schema[0]))  # core lists the 2.0 overlay
    assert listed.output_schema == by_name[with_schema[0]].output_schema


def test_result_content_structured_summarises_the_text_block():
    bridge = _mode_bridge("structured")
    ok = bridge.call_tool("node_info", {"paths": ["/obj/geo1"]})
    assert ok.content[0].text == "node_info: ok"
    assert ok.structured_content == {"nodes": [{"path": "/obj/geo1"}]}
    error = bridge.call_tool("node_delete", {"paths": ["/obj/x"]})
    assert error.content[0].text == "node_not_found: No node at /obj/x."
    assert error.structured_content["code"] == "node_not_found"
    invalid = bridge.call_tool("node_info", {})
    assert invalid.content[0].text.startswith("invalid_argument: ")


def test_result_content_keeps_images_as_image_blocks():
    import base64

    png = base64.b64encode(b"png").decode()
    for mode in ("text", "both", "structured"):
        bridge, client, _ = make_bridge(config=BridgeConfig(result_content=mode))
        client.replies["viewport_capture"] = (True, {"image": {"png_base64": png}}, {})
        result = bridge.call_tool("viewport_capture", {})
        assert [c.type for c in result.content] == ["text", "image"], mode


# -- registry identity (review 10 section 1.4) ---------------------------------------------


def _entries(tmp_path):
    from dataclasses import replace

    ghost = replace(INSTANCE, pid=5555, port=51005, started="2026-10-12T12:00:00Z")
    ghost = replace(ghost, file=tmp_path / "5555.json")
    real = replace(INSTANCE, file=tmp_path / "4242.json")
    for inst in (ghost, real):
        inst.file.write_text("{}")
    return ghost, real


def test_a_reused_pid_is_detected_and_its_entry_deleted(tmp_path):
    ghost, real = _entries(tmp_path)
    bridge, client, live = make_bridge(instances=(ghost, real))
    client.follow_registry = False  # every port answers as pid 4242: the ghost's is reused

    def scan():
        return [i for i in live if i.file.exists()]

    bridge.scan = scan
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.is_error is False
    assert result.meta["pid"] == 4242
    assert not ghost.file.exists() and real.file.exists()
    assert any("stale" in w for w in result.meta["warnings"])


def test_a_refused_call_drops_the_entry_and_selects_again(tmp_path):
    ghost, real = _entries(tmp_path)
    bridge, client, live = make_bridge(instances=(ghost, real))
    bridge.scan = lambda: [i for i in live if i.file.exists()]
    bridge.mark_verified(ghost)  # it answered once; now nothing listens there
    refused = ToolError("houdini_offline", "refused", detail={"reason": "refused"})
    calls = []

    def call(tool, args, timeout_s, request_id=None, max_response_bytes=None):
        calls.append(client.port)
        if client.port == ghost.port:
            raise refused
        return True, {"ok": 1}, {}

    client.call = call
    result = bridge.call_tool("node_info", {"paths": ["/obj"]})
    assert result.is_error is False and calls == [ghost.port, real.port]
    assert not ghost.file.exists()


def test_status_removes_a_stale_entry(tmp_path):
    ghost, real = _entries(tmp_path)
    bridge, client, live = make_bridge(instances=(ghost, real))
    client.follow_registry = False
    bridge.scan = lambda: [i for i in live if i.file.exists()]
    status = structured(bridge.call_tool("houdini_status", {}))
    assert status["connected"]["pid"] == 4242
    assert [i["pid"] for i in status["instances"]] == [4242]
    assert any("stale registry entry" in w for w in status["warnings"])


def test_connect_to_a_stale_pid_is_offline(tmp_path):
    ghost, real = _entries(tmp_path)
    bridge, client, live = make_bridge(instances=(ghost, real))
    client.follow_registry = False
    error = structured(bridge.call_tool("houdini_connect", {"pid": 5555}))
    assert error["code"] == "houdini_offline" and "removed" in error["message"]
    assert not ghost.file.exists()
