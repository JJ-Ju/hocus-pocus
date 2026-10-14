"""Resources with etags and subscriptions (spec-2.0 §2.7, profile v2): the host's template
parser and ``/hp/v2/resource`` envelope, and the bridge's listing, reads (etag passthrough,
not-modified) and subscriptions, against a fake host that answers through the real
``host.resources.serve``."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import anyio
import pytest
from mcp import Client

from hocuspocus.bridge import resources as bridge_resources
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.server import Bridge, build_server
from hocuspocus.host import resources as host_resources
from hocuspocus.host.server import HostApp, HostHTTPServer, serve_in_thread
from hocuspocus.tools.catalog import ToolSpec
from hocuspocus.tools.errors import ToolError

pytestmark = [
    pytest.mark.unit,
    # resources/subscribe is the handshake-era (2025) way; 2026-07-28 clients listen.
    pytest.mark.filterwarnings("ignore:resources/.*subscribe is removed"),
]


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


# -- the template parser (host) ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "tool", "args"),
    [
        ("houdini://node/obj/geo1", "inspect", {"what": "node", "target": "/obj/geo1"}),
        ("houdini://node/%2Fobj%2Fgeo1", "inspect", {"what": "node", "target": "/obj/geo1"}),
        (
            "houdini://node/obj/geo1?include=parms,inputs&include_defaults=true",
            "inspect",
            {
                "what": "node",
                "target": "/obj/geo1",
                "include": ["parms", "inputs"],
                "include_defaults": True,
            },
        ),
        (
            "houdini://node/obj/geo1/box1?parms=size*",
            "inspect",
            {"what": "parms", "target": "/obj/geo1/box1", "parms": "size*"},
        ),
        ("houdini://outline", "inspect", {"what": "outline"}),
        (
            "houdini://outline?root=/obj&depth=3",
            "inspect",
            {"what": "outline", "target": "/obj", "depth": 3},
        ),
        (
            "houdini://network/obj/geo1?depth=2",
            "inspect",
            {"what": "network", "target": "/obj/geo1", "depth": 2},
        ),
        (
            "houdini://network/obj?format=outline",
            "inspect",
            {"what": "outline", "target": "/obj"},
        ),
        (
            "houdini://geo/obj/geo1/box1?frame=24",
            "inspect",
            {"what": "geo", "target": "/obj/geo1/box1", "frame": 24},
        ),
        (
            "houdini://geo/obj/geo1/box1?class=point&attribs=P,N&count=8&stats=1",
            "inspect",
            {
                "what": "geo",
                "target": "/obj/geo1/box1",
                "rows": True,
                "class": "point",
                "attribs": ["P", "N"],
                "count": 8,
                "stats": True,
            },
        ),
        ("houdini://image/img/net/n", "inspect", {"what": "image", "target": "/img/net/n"}),
        (
            "houdini://stage/stage/lop1?prim=/geo&time=1.5&summary=false",
            "inspect",
            {
                "what": "stage",
                "target": "/stage/lop1",
                "prim": "/geo",
                "time": 1.5,
                "summary": False,
            },
        ),
        (
            "houdini://type/Sop/scatter?detail=folders",
            "inspect",
            {"what": "type", "target": "Sop/scatter", "detail": "folders"},
        ),
        (
            "houdini://types?q=noise&category=Sop&limit=5",
            "search",
            {"kind": "types", "query": "noise", "category": "Sop", "limit": 5},
        ),
        ("houdini://problems?root=/obj", "inspect", {"what": "problems", "target": "/obj"}),
        (
            "houdini://events?since=12&limit=5",
            "inspect",
            {"what": "events", "since": 12, "limit": 5},
        ),
        ("houdini://events?since=4242:12", "inspect", {"what": "events", "since": "4242:12"}),
        ("houdini://jobs", "inspect", {"what": "jobs"}),
        ("houdini://status", "houdini_status", {}),
        ("houdini://instances", "", {}),
    ],
)
def test_parse_maps_each_template_to_its_call(uri, tool, args):
    route = host_resources.parse(uri)
    assert (route.tool, route.args) == (tool, args)


@pytest.mark.parametrize(
    ("uri", "needle"),
    [
        ("houdini://nodes/obj", "Unknown resource"),
        ("houdini://node/obj?depth=2", "does not take depth"),
        ("houdini://node/", "needs a path"),
        ("houdini://jobs/1-a", "takes no path"),
        ("houdini://geo/obj/a?stats=maybe", "true or false"),
        ("houdini://outline?depth=two", "integer"),
        ("houdini://network/obj?format=json", "data or outline"),
        ("houdini://type/Sop", "needs both"),
        ("file:///etc/passwd", "Not a houdini://"),
    ],
)
def test_parse_refuses_with_invalid_argument(uri, needle):
    with pytest.raises(ToolError) as info:
        host_resources.parse(uri)
    assert info.value.code == "invalid_argument" and needle in info.value.message


def test_every_advertised_template_kind_parses():
    for template, name, _desc in host_resources.TEMPLATES:
        assert template.startswith(f"houdini://{name}")
        assert name in host_resources.PARAMS
        variables = template.partition("{?")[2].rstrip("}")
        assert tuple(v for v in variables.split(",") if v) == host_resources.PARAMS[name]


@pytest.mark.parametrize(
    ("header", "match"),
    [('"a:1:x"', True), ('W/"a:1:x"', True), ("b, a:1:x", True), ("*", True), ("a:1:y", False)],
)
def test_if_none_match_semantics(header, match):
    assert host_resources.etag_matches(header, "a:1:x") is match
    assert host_resources.etag_matches(None, "a:1:x") is False


# -- a fake host -------------------------------------------------------------------------------


class FakeHostApp:
    """``HostApp``'s ``call``/``meta``: ``inspect`` answers ``{what, target, etag, ...}``
    with an etag per target that tests move with :meth:`touch`."""

    def __init__(self) -> None:
        self.versions: dict[str, int] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.seq = 0
        self.generation = 2
        self.fail: dict[str, Any] = {}

    def touch(self, target: str) -> None:
        self.versions[target] = self.versions.get(target, 0) + 1
        self.seq += 1

    def meta(self) -> dict[str, Any]:
        return {"scene_generation": self.generation, "undo_label": None, "elapsed_ms": 0}

    def call(self, tool, args, timeout_s=None, **budget):
        self.calls.append((tool, dict(args)))
        if tool in self.fail:
            return {"ok": False, "error": self.fail[tool], "_meta": self.meta()}
        if tool == "inspect":
            target = args.get("target")
            key = str(target if target is not None else args["what"])
            version = self.versions.get(key, 0)
            body = {
                "what": args["what"],
                "target": target,
                "etag": f"4242:{self.generation}:{key}#{version}",
                "path": target,
                "version": version,
            }
            if args["what"] == "events":
                body.update({"events": [], "next_since": self.seq})
            if args["what"] == "jobs":
                body.update({"jobs": []})
            return {"ok": True, "result": body, "_meta": self.meta()}
        return {"ok": True, "result": {"tool": tool, "args": args}, "_meta": self.meta()}


class FakeClient:
    """A HostClient whose resource reads run the real ``host.resources.serve``."""

    def __init__(self, app: FakeHostApp) -> None:
        self.app = app
        self.reads: list[tuple[str, str | None]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": 4242, "houdini": "22.0.466", "generation": 2}

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        envelope = self.app.call(tool, args, timeout_s)
        return envelope["ok"], envelope.get("result") or envelope.get("error"), envelope["_meta"]

    def resource(self, uri, *, if_none_match=None, timeout_s=None, max_response_bytes=None):
        self.reads.append((uri, if_none_match))
        envelope = host_resources.serve(self.app, uri, if_none_match)
        envelope["_meta"]["events_seq"] = self.app.seq
        return envelope["ok"], envelope.get("result") or envelope.get("error"), envelope["_meta"]


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
TOOLS = (
    ToolSpec(
        "houdini_status",
        "Status.",
        {"type": "object", "properties": {}},
        read_only=True,
        bridge_local=True,
    ),
)


def make_bridge(profile: str = "v2") -> tuple[Bridge, FakeHostApp, FakeClient]:
    app = FakeHostApp()
    client = FakeClient(app)
    bridge = Bridge(
        BridgeConfig(profile=profile),
        tools=TOOLS,
        client_factory=lambda port, token: client,
        scan=lambda: [INSTANCE],
    )
    return bridge, app, client


# -- the host envelope -------------------------------------------------------------------------


def test_serve_returns_the_inspect_body_and_its_etag():
    app = FakeHostApp()
    first = host_resources.serve(app, "houdini://node/obj/geo1")
    assert first["ok"] and first["result"]["etag"] == "4242:2:/obj/geo1#0"
    assert first["result"]["body"]["etag"] == first["result"]["etag"]
    assert first["_meta"]["etag"] == first["result"]["etag"]
    assert app.calls[-1] == ("inspect", {"what": "node", "target": "/obj/geo1"})
    same = host_resources.serve(app, "houdini://node/obj/geo1", '"4242:2:/obj/geo1#0"')
    assert same["result"] == {
        "uri": "houdini://node/obj/geo1",
        "etag": "4242:2:/obj/geo1#0",
        "not_modified": True,
    }
    app.touch("/obj/geo1")
    moved = host_resources.serve(app, "houdini://node/obj/geo1", "4242:2:/obj/geo1#0")
    assert moved["result"]["body"]["version"] == 1


def test_serve_gives_search_and_status_a_content_etag():
    app = FakeHostApp()
    one = host_resources.serve(app, "houdini://types?q=noise")
    two = host_resources.serve(app, "houdini://types?q=noise")
    other = host_resources.serve(app, "houdini://types?q=box")
    assert one["result"]["etag"] == two["result"]["etag"] != other["result"]["etag"]
    pid, generation, digest = one["result"]["etag"].split(":")
    assert pid.isdigit() and generation == "2" and len(digest) == 16
    status = host_resources.serve(app, "houdini://status")
    assert status["ok"] and app.calls[-1] == ("houdini_status", {})


def test_serve_passes_errors_and_refuses_bridge_kinds():
    app = FakeHostApp()
    app.fail["inspect"] = {"code": "node_not_found", "message": "No node /obj/nope."}
    failed = host_resources.serve(app, "houdini://node/obj/nope")
    assert failed["ok"] is False and failed["error"]["code"] == "node_not_found"
    bad = host_resources.serve(app, "houdini://instances")
    assert bad["ok"] is False and "bridge" in bad["error"]["message"]
    assert host_resources.serve(app, "houdini://nope")["error"]["code"] == "invalid_argument"


def test_http_route_honours_if_none_match():
    app = FakeHostApp()
    host_app = HostApp(token="tok", call=app.call, health=lambda: {"ok": True}, meta=app.meta)
    server = HostHTTPServer(host_app, "127.0.0.1", 0)
    serve_in_thread(server)
    try:
        assert server.port != 37219
        base = f"http://127.0.0.1:{server.port}/hp/v2/resource?uri="
        uri = urllib.parse.quote("houdini://node/%2Fobj%2Fgeo1", safe="")

        def get(headers: dict[str, str]) -> dict[str, Any]:
            request = urllib.request.Request(base + uri, headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())

        auth = {"Authorization": "Bearer tok"}
        first = get(auth)
        assert first["result"]["body"]["target"] == "/obj/geo1"
        again = get({**auth, "If-None-Match": first["result"]["etag"]})
        assert again["result"]["not_modified"] is True
        with pytest.raises(urllib.error.HTTPError) as info:
            get({})
        assert info.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


# -- bridge: listing and reads -----------------------------------------------------------------


def _run(fn, *args):
    return anyio.run(fn, *args)


def test_v2_lists_templates_and_resources_and_sets_capabilities():
    bridge, _app, _client = make_bridge()

    async def main():
        async with Client(build_server(bridge), mode="legacy") as client:
            caps = client.server_capabilities.resources
            assert caps.subscribe is True and caps.list_changed is True
            templates = (await client.list_resource_templates()).resource_templates
            listed = (await client.list_resources()).resources
            return [t.uri_template for t in templates], [r.uri for r in listed]

    templates, listed = _run(main)
    assert templates == [tpl for tpl, _n, _d in host_resources.TEMPLATES]
    assert "houdini://node/{path}{?include,parms,include_defaults}" in templates
    assert listed[:3] == ["houdini://status", "houdini://instances", "houdini://jobs"]
    assert "hocuspocus://guide" in listed


def test_compat_1x_keeps_the_1x_resources():
    bridge, _app, _client = make_bridge(profile="compat_1x")

    async def main():
        async with Client(build_server(bridge), mode="legacy") as client:
            caps = client.server_capabilities.resources
            templates = (await client.list_resource_templates()).resource_templates
            return caps.subscribe, [t.uri_template for t in templates]

    subscribe, templates = _run(main)
    assert not subscribe and "houdini://nodetype/{category}/{name}" in templates


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_read_passes_the_etag_and_answers_not_modified(mode):
    bridge, app, client = make_bridge()

    async def main():
        async with Client(build_server(bridge), mode=mode) as mcp:
            uri = "houdini://node/obj/geo1"
            first = await mcp.read_resource(uri, cache_mode="bypass")
            etag = first.meta["etag"]
            second = await mcp.read_resource(uri, meta={"If-None-Match": etag})
            app.touch("/obj/geo1")
            third = await mcp.read_resource(uri, meta={"etag": etag})
            return first, second, third

    first, second, third = _run(main)
    body = json.loads(first.contents[0].text)
    assert body["etag"] == first.meta["etag"] == "4242:2:/obj/geo1#0"
    assert first.contents[0].meta["etag"] == body["etag"]
    assert first.meta["cache_control"] == "no-cache" and first.meta["instance"]["pid"] == 4242
    assert second.contents == [] and second.meta["not_modified"] is True
    assert second.meta["etag"] == body["etag"]
    assert client.reads[1] == ("houdini://node/obj/geo1", body["etag"])
    assert json.loads(third.contents[0].text)["version"] == 1


def test_read_is_byte_identical_to_the_host_body():
    bridge, app, _client = make_bridge()
    result = bridge_resources.read(bridge, "houdini://geo/obj/geo1/box1?frame=3")
    body = host_resources.serve(app, "houdini://geo/obj/geo1/box1?frame=3")["result"]["body"]
    from hocuspocus.bridge import budget

    assert result.contents[0].text == budget.dumps(body)


def test_read_errors_and_events_cursor_tagging():
    bridge, app, client = make_bridge()
    from mcp.shared.exceptions import MCPError

    app.fail["inspect"] = {"code": "node_not_found", "message": "No node."}
    with pytest.raises(MCPError) as info:
        bridge_resources.read(bridge, "houdini://node/obj/nope")
    assert "node_not_found" in str(info.value)
    with pytest.raises(MCPError):
        bridge_resources.read(bridge, "houdini://bogus")
    del app.fail["inspect"]
    app.seq = 7
    out = bridge_resources.read(bridge, "houdini://events?since=4242:3")
    assert client.reads[-1][0] == "houdini://events?since=3"
    assert json.loads(out.contents[0].text)["next_since"] == "4242:7"
    foreign = bridge_resources.read(bridge, "houdini://events?since=999:3")
    assert client.reads[-1][0] == "houdini://events?since=0"
    assert json.loads(foreign.contents[0].text)["reset"] is True


def test_status_and_instances_are_served_by_the_bridge():
    bridge, _app, _client = make_bridge()
    status = bridge_resources.read(bridge, "houdini://status")
    instances = bridge_resources.read(bridge, "houdini://instances")
    assert status.meta["etag"].startswith("bridge:")
    assert json.loads(instances.contents[0].text)["instances"][0]["pid"] == 4242
    again = bridge_resources.read(
        bridge, "houdini://instances", {"If-None-Match": instances.meta["etag"]}
    )
    assert again.contents == [] and again.meta["not_modified"] is True


def test_v2_guide_and_tools_text():
    from hocuspocus.bridge.instructions import GUIDE_MAX_BYTES

    guide = bridge_resources.v2_guide_text()
    assert len(guide.encode("utf-8")) <= GUIDE_MAX_BYTES
    assert "If-None-Match" in guide and "houdini://nodetype" not in guide
    tools = bridge_resources.v2_tools_text(TOOLS)
    for template, _name, _desc in host_resources.TEMPLATES:
        assert template in tools
    bridge, _app, _client = make_bridge()
    read = bridge_resources.read(bridge, "hocuspocus://guide")
    assert read.contents[0].text == guide
    cached = bridge_resources.read(bridge, "hocuspocus://guide", {"etag": read.meta["etag"]})
    assert cached.contents == []


# -- subscriptions -----------------------------------------------------------------------------


def test_hub_only_rereads_nodes_when_the_events_feed_moves():
    bridge, app, client = make_bridge()
    hub = bridge_resources.ResourceHub(bridge)
    uri = "houdini://node/obj/geo1"
    hub.baseline(uri)
    hub.add(uri, "key")
    assert hub.check() == []  # the first heartbeat sets the gate
    node_reads = lambda: [r for r in client.reads if r[0] == uri]  # noqa: E731
    before = len(node_reads())
    assert hub.check() == [] and len(node_reads()) == before  # nothing moved: no node read
    app.touch("/obj/geo1")
    assert hub.check() == [uri]
    assert node_reads()[-1][1] == "4242:2:/obj/geo1#0"  # re-read with If-None-Match
    assert hub.check() == []
    hub.remove(uri, "key")
    assert hub.uris() == [] and hub.check() == []


def test_hub_refuses_unsubscribable_uris():
    bridge, _app, _client = make_bridge()

    from mcp.shared.exceptions import MCPError

    async def main():
        async with Client(build_server(bridge), mode="legacy") as mcp:
            with pytest.raises(MCPError) as info:
                await mcp.session.subscribe_resource("houdini://outline")
            return str(info.value)

    assert "houdini://node/{path}" in _run(main)


def test_subscribe_notifies_on_etag_change_legacy():
    bridge, app, _client = make_bridge()
    uri = "houdini://node/obj/geo1"
    got: list[str] = []

    async def on_message(message):
        params = getattr(getattr(message, "params", None), "uri", None)
        if getattr(message, "method", "") == "notifications/resources/updated":
            got.append(str(params))

    async def main():
        server = build_server(bridge)
        server.resource_hub.interval_s = 0.05
        async with Client(server, mode="legacy", message_handler=on_message) as mcp:
            await mcp.session.subscribe_resource(uri)
            await anyio.sleep(0.2)
            assert got == []
            app.touch("/obj/geo1")
            with anyio.fail_after(2):
                while not got:
                    await anyio.sleep(0.02)
            await mcp.session.unsubscribe_resource(uri)
            assert server.resource_hub.uris() == []

    _run(main)
    assert got == [uri]


def test_listen_notifies_on_etag_change_modern():
    bridge, app, _client = make_bridge()
    uri = "houdini://node/obj/geo1"

    async def main():
        server = build_server(bridge)
        server.resource_hub.interval_s = 0.05
        async with Client(server) as mcp, mcp.listen(resource_subscriptions=[uri]) as sub:
            assert server.resource_hub.uris() == [uri]
            app.touch("/obj/geo1")
            with anyio.fail_after(2):
                event = await sub.__anext__()
            return event

    event = _run(main)
    assert event.uri == uri
