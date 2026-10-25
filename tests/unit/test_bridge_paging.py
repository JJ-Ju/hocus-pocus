"""Budget cuts of paged results never skip rows (review 22 finding 1, BIBLE §4.1).

Every cursor style the bridge can trim is rewritten to resume right after the last row
kept, chosen by the call's tool and arguments (``budget.paged_mode``): ``events``' and
``inspect what: events``' ``next_since`` (``<pid>:<seq>``), ``search kind: nodes``'
path (bare, or ``after:<path>`` with ``detail: full``), ``inspect what: outline``'s
``after:<name>``, ``inspect what: network``'s ``after:<name>`` over its ``data`` dict,
``search kind: types``' ``t:<offset>`` and plain integer offsets (``geo`` rows with
``start``). Anything else is left whole with ``over_budget``. The payloads are copied from
what the host returns (a hython probe of 60 ``geo`` objects at ``max_response_bytes``
4096, 2.1); 2.0 keyed this by the 1.4 tool names, so none but ``events`` matched."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hocuspocus.bridge import budget
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.server import Bridge
from hocuspocus.host.tools.events import EventLog

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


HOST = Instance(pid=60396, port=52000, token="t", houdini="22.0.466", ui=False, label="hython")


def _event(seq: int) -> dict[str, Any]:
    return {
        "seq": seq,
        "time": "2026-10-13T10:00:00.000Z",
        "kind": "ParmTupleChanged",
        "path": f"/obj/soak_g{seq:03d}/xf",
        "origin": "agent",
        "detail": {"parm": "t", "components": ["tx", "ty", "tz"]},
    }


class EventsHost:
    """A 1.3-style host: pages by ``limit`` only and ignores the byte budget, so every
    cut is the bridge's."""

    def __init__(self, count: int) -> None:
        self.events = [_event(seq) for seq in range(1, count + 1)]
        self.calls: list[dict[str, Any]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": HOST.pid, "houdini": "22.0.466", "generation": 1}

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append(dict(args))
        since, limit = args.get("since", 0), args.get("limit", 50)
        newer = [e for e in self.events if e["seq"] > since]
        chunk = newer[:limit]
        out: dict[str, Any] = {
            "events": chunk,
            "next_since": chunk[-1]["seq"] if chunk else since,
            "dropped": 0,
        }
        if len(newer) > limit:
            out["more"] = True
        return True, out, {}


def _bridge(host: Any, max_bytes: int) -> Bridge:
    return Bridge(
        BridgeConfig(profile="full", max_response_bytes=max_bytes),
        client_factory=lambda port, token: host,
        scan=lambda: [HOST],
    )


def _text(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def test_following_a_trimmed_events_cursor_returns_every_event_exactly_once():
    host = EventsHost(400)
    bridge = _bridge(host, 16_384)
    seen: list[int] = []
    since: Any = 0
    pages = 0
    while True:
        result = bridge.call_tool("events", {"since": since, "limit": 1000})
        page = _text(result)
        assert len(result.content[0].text.encode()) <= 16_384
        seqs = [e["seq"] for e in page["events"]]
        seen += seqs
        pages += 1
        if seqs:
            # The cursor names the last event kept, never one past what was dropped.
            assert page["next_since"] == f"{HOST.pid}:{seqs[-1]}"
        if not page.get("more"):
            break
        since = page["next_since"]
        assert pages < 50
    assert seen == list(range(1, 401))
    assert pages > 1  # the budget did cut pages
    # The host got the bare seq of the last event each page kept.
    assert all(isinstance(c["since"], int) for c in host.calls)


def test_a_trimmed_events_page_says_more_and_reports_the_cut():
    host = EventsHost(400)
    result = _bridge(host, 16_384).call_tool("events", {"since": 0, "limit": 1000})
    page = _text(result)
    kept = len(page["events"])
    assert 0 < kept < 400 and page["truncated"] is True and page["more"] is True
    cut = result.meta[budget.TRUNCATION_META_KEY][0]
    assert cut == {"path": "events", "kept": kept, "total": 400, "next_since": page["next_since"]}


def test_an_untrimmed_events_page_keeps_the_host_cursor():
    host = EventsHost(10)
    page = _text(_bridge(host, 16_384).call_tool("events", {"since": 0}))
    assert page["next_since"] == f"{HOST.pid}:10" and "truncated" not in page


def _compact_node_rows(count: int) -> list[dict[str, Any]]:
    """Rows as ``search kind: nodes`` returns them by default (host projections applied):
    ``input_count``, ``has_errors`` and a ``category`` shared by every row are gone."""
    rows: list[dict[str, Any]] = []
    for i in range(count):
        geo = f"/obj/geo{i:04d}"
        rows.append({"path": geo, "type": "geo", "flags": ["display"], "child_count": 2})
        rows.append({"path": f"{geo}/box1", "type": "Sop/box", "flags": ["display", "render"]})
    return rows


def test_search_nodes_page_is_trimmed_with_a_bare_path_cursor():
    rows = _compact_node_rows(200)
    page = {
        "nodes": rows,
        "common": {"category": "Object"},
        "total": 1000,
        "next_cursor": rows[-1]["path"],
    }
    out, cuts = budget.apply_budget(page, 4096, {"kind": "nodes"}, pageable=True, tool="search")
    kept = len(out["nodes"])
    assert 0 < kept < len(rows) and out["nodes"] == rows[:kept] and out["truncated"] is True
    assert out["next_cursor"] == rows[kept - 1]["path"]  # as the host writes it
    assert out["total"] == 1000 and out["common"] == page["common"]
    assert len(budget.dumps(out).encode()) <= 4096
    assert cuts[0] == {
        "path": "nodes",
        "kept": kept,
        "total": len(rows),
        "next_cursor": out["next_cursor"],
    }
    # The last page (no host cursor) gets one too, so its trimmed rows come next.
    last = {k: v for k, v in page.items() if k != "next_cursor"}
    out, _ = budget.apply_budget(
        last, 4096, {"kind": "nodes", "cursor": "/obj/a"}, pageable=True, tool="search"
    )
    assert out["next_cursor"] == rows[len(out["nodes"]) - 1]["path"]


def test_search_nodes_full_detail_keeps_the_after_prefix():
    rows = [
        {
            "path": f"/obj/geo{i:04d}",
            "type": "geo",
            "category": "Object",
            "flags": {"display": True},
            "input_count": 0,
            "child_count": 1,
            "has_errors": False,
        }
        for i in range(120)
    ]
    full = {"kind": "nodes", "root": "/obj", "nodes": rows, "total": 500}
    out, _ = budget.apply_budget(
        {**full, "next_cursor": "after:/obj/geo0119"},
        4096,
        {"kind": "nodes", "detail": "full"},
        pageable=True,
        tool="search",
    )
    assert out["next_cursor"] == f"after:{rows[len(out['nodes']) - 1]['path']}"
    # No host cursor to copy the form from: detail says it.
    out, _ = budget.apply_budget(
        full, 4096, {"kind": "nodes", "detail": "full"}, pageable=True, tool="search"
    )
    assert out["next_cursor"] == f"after:{rows[len(out['nodes']) - 1]['path']}"
    out, _ = budget.apply_budget(full, 4096, {"kind": "nodes"}, pageable=True, tool="search")
    assert out["next_cursor"] == rows[len(out["nodes"]) - 1]["path"]


def test_search_nodes_rows_that_cannot_be_named_stay_whole():
    page = {"nodes": ["/obj/a"] * 800, "total": 800, "next_cursor": "/obj/a"}
    out, cuts = budget.apply_budget(page, 4096, {"kind": "nodes"}, pageable=True, tool="search")
    assert out["nodes"] == page["nodes"] and out["over_budget"] is True and "truncated" not in out
    assert cuts[0]["over_budget"] is True
    pathless = {"nodes": [{"type": "geo"}] * 800}
    out, _ = budget.apply_budget(pathless, 4096, {"kind": "nodes"}, pageable=True, tool="search")
    assert out["over_budget"] is True and len(out["nodes"]) == 800


def _outline_rows(count: int) -> list[dict[str, Any]]:
    """Rows of ``inspect what: outline`` after the host's projection: ``name`` is left out
    when it is the path's last segment, ``wiring`` is off (no ``inputs``)."""
    return [
        {
            "path": f"/obj/geo{i:03d}",
            "type": "geo",
            "children_count": 3,
            "display": f"/obj/geo{i:03d}/out",
            "flags": ["display"],
        }
        for i in range(count)
    ]


def test_inspect_outline_page_is_trimmed_with_the_last_kept_name():
    rows = _outline_rows(200)
    page = {
        "etag": "36056:1:20679574393b6756",
        "root": "/obj",
        "nodes": rows,
        "node_count": 200,
        "truncated": True,
        "next_cursor": "after:geo199",
    }
    out, cuts = budget.apply_budget(
        page, 4096, {"what": "outline", "target": "/obj"}, pageable=True, tool="inspect"
    )
    kept = len(out["nodes"])
    assert 0 < kept < 200 and out["nodes"] == rows[:kept]
    assert out["next_cursor"] == f"after:geo{kept - 1:03d}"  # the name, not the path
    assert out["node_count"] == kept  # what the page holds
    assert cuts[0]["next_cursor"] == out["next_cursor"]
    assert len(budget.dumps(out).encode()) <= 4096


def test_inspect_outline_uses_name_when_it_differs_from_the_path():
    rows = _outline_rows(200)
    for row in rows:
        row["name"] = row["path"].rsplit("/", 1)[-1].upper()  # kept: not the last segment
    out, _ = budget.apply_budget(
        {"root": "/obj", "nodes": rows, "next_cursor": "after:GEO199"},
        4096,
        {"what": "outline"},
        pageable=True,
        tool="inspect",
    )
    assert out["next_cursor"] == f"after:GEO{len(out['nodes']) - 1:03d}"


def test_inspect_outline_counts_listed_children():
    rows = []
    for i in range(100):
        children = [{"path": f"/obj/geo{i:03d}/n{j}", "type": "null"} for j in range(4)]
        rows.append({"path": f"/obj/geo{i:03d}", "type": "geo", "children": children})
    out, _ = budget.apply_budget(
        {"root": "/obj", "nodes": rows, "node_count": 500},
        4096,
        {"what": "outline", "depth": 2},
        pageable=True,
        tool="inspect",
    )
    assert out["node_count"] == 5 * len(out["nodes"])  # each geo and its four children


def _network_data(count: int) -> dict[str, Any]:
    """``data`` of ``inspect what: network``: a dict keyed by node name, not a list."""
    return {
        f"geo{i:03d}": {
            "type": "geo",
            "inputs": [],
            "flags": {"display": True},
            "parmtemplates": [{"insert_after": "display", "parmtemplates": {"x": {"type": "int"}}}],
        }
        for i in range(count)
    }


def test_inspect_network_page_is_trimmed_in_key_order_with_the_last_kept_name():
    data = _network_data(150)
    page = {
        "etag": "36056:1:1cf0f6892f64fb64",
        "root": "/obj",
        "format": "data",
        "data": data,
        "node_count": 150,
        "bytes": budget.size(data),
        "truncated": True,
        "next_cursor": "after:geo149",
    }
    out, cuts = budget.apply_budget(
        page, 4096, {"what": "network", "target": "/obj"}, pageable=True, tool="inspect"
    )
    kept = len(out["data"])
    assert 0 < kept < 150 and list(out["data"]) == list(data)[:kept]
    assert out["data"] == dict(list(data.items())[:kept])
    assert out["next_cursor"] == f"after:geo{kept - 1:03d}"
    assert out["node_count"] == kept and out["bytes"] == budget.size(out["data"])
    assert cuts[0] == {
        "path": "data",
        "kept": kept,
        "total": 150,
        "next_cursor": out["next_cursor"],
    }
    assert len(budget.dumps(out).encode()) <= 4096


def test_inspect_network_cursor_is_never_a_skipped_row():
    """The cursor names the last row the page holds: resuming after it returns the next."""
    data = _network_data(150)
    page = {"root": "/obj", "format": "data", "data": data, "node_count": 150}
    out, _ = budget.apply_budget(
        page, 4096, {"what": "network", "target": "/obj"}, pageable=True, tool="inspect"
    )
    names = list(data)
    after = out["next_cursor"][len("after:") :]
    assert names[names.index(after) + 1] not in out["data"]
    assert after == list(out["data"])[-1]


def test_inspect_network_children_count_in_node_count():
    data = {
        f"geo{i:03d}": {"type": "geo", "children": {f"n{j}": {"type": "null"} for j in range(3)}}
        for i in range(100)
    }
    out, _ = budget.apply_budget(
        {"root": "/obj", "format": "data", "data": data, "node_count": 400},
        4096,
        {"what": "network", "depth": 2},
        pageable=True,
        tool="inspect",
    )
    assert out["node_count"] == 4 * len(out["data"])


def test_a_network_dict_with_an_unnameable_row_stays_whole():
    page = {"root": "/obj", "data": {"": {"pad": "z" * 80}, **_network_data(100)}}
    out, cuts = budget.apply_budget(page, 4096, {"what": "network"}, pageable=True, tool="inspect")
    assert out["over_budget"] is True and out["data"] == page["data"] and cuts[0]["over_budget"]
    flat = {"root": "/obj", "data": ["z" * 80] * 100}  # a list where a dict was promised
    out, _ = budget.apply_budget(flat, 4096, {"what": "network"}, pageable=True, tool="inspect")
    assert out["over_budget"] is True and len(out["data"]) == 100


def test_search_types_offset_cursor_keeps_its_prefix():
    rows = [
        {
            "name": f"type{i}",
            "label": f"Type {i}",
            "category": "Sop",
            "description": "Creates points or polygons, or adds them to an input.",
            "inputs": "0-1",
        }
        for i in range(300)
    ]
    page = {"results": rows, "total": 2032, "notes": ["Cop2 is the legacy compositor."]}
    page["next_cursor"] = "t:300"
    out, _ = budget.apply_budget(
        page, 4096, {"kind": "types", "query": "a"}, pageable=True, tool="search"
    )
    kept = len(out["results"])
    assert 0 < kept < 300 and out["results"] == rows[:kept]
    assert out["next_cursor"] == f"t:{kept}"
    out, _ = budget.apply_budget(
        {**page, "next_cursor": "t:700"},
        4096,
        {"kind": "types", "query": "a", "cursor": "t:400"},
        pageable=True,
        tool="search",
    )
    assert out["next_cursor"] == f"t:{400 + len(out['results'])}"
    # A cursor in the wrong form is not rewritten.
    out, _ = budget.apply_budget(
        {**page, "next_cursor": "300"}, 4096, {"kind": "types"}, pageable=True, tool="search"
    )
    assert out["over_budget"] is True and len(out["results"]) == 300


def test_inspect_events_next_since_is_rewritten_like_the_events_tool():
    events = [_event(seq) for seq in range(1, 201)]
    page = {
        "etag": "36056:1:733c698711f43ca8",
        "events": events,
        "next_since": f"{HOST.pid}:200",
        "dropped": 0,
        "more": True,
    }
    out, _ = budget.apply_budget(
        page, 4096, {"what": "events", "since": 0}, pageable=True, tool="inspect"
    )
    kept = len(out["events"])
    assert 0 < kept < 200 and out["next_since"] == f"{HOST.pid}:{kept}" and out["more"] is True


def test_inspect_modes_without_a_cursor_are_sent_whole():
    """``inspect`` declares a ``cursor`` for network, outline, geo rows, stage and problems
    only; for the rest a cut page would carry a cursor the host rejects."""
    nodes = [{"path": f"/obj/geo{i}", "type": "geo", "pad": "x" * 60} for i in range(100)]
    for args in (
        {"what": "node", "paths": ["/obj"]},
        {"what": "type", "target": "Sop/box"},
        {"what": "geo", "target": "/obj/geo1/out"},  # geo_info: no rows, no cursor
        {"what": "jobs"},
    ):
        out, cuts = budget.apply_budget({"nodes": nodes}, 4096, args, pageable=True, tool="inspect")
        assert out["over_budget"] is True and out["nodes"] == nodes and cuts[0]["over_budget"]
        assert "next_cursor" not in out and "truncated" not in out


def test_inspect_modes_with_an_offset_cursor_are_trimmed_by_offset():
    rows = [[i, "x" * 60] for i in range(300)]
    for args in (
        {"what": "geo", "target": "/obj/geo1/out", "rows": True, "start": 0},
        {"what": "stage", "target": "/stage/out", "limit": 300},
    ):
        out, _ = budget.apply_budget(
            {"rows": rows, "start": 0, "next_cursor": "300"},
            4096,
            args,
            pageable=True,
            tool="inspect",
        )
        assert out["next_cursor"] == str(len(out["rows"])) and out["truncated"] is True


def test_paged_mode_is_chosen_by_tool_and_argument():
    assert budget.paged_mode("events", {}) is budget.EVENTS
    assert budget.paged_mode("inspect", {"what": "events"}) is budget.EVENTS
    assert budget.paged_mode("search", {"kind": "nodes"}) is budget.NODES
    assert budget.paged_mode("search", {"kind": "types"}) is budget.TYPES
    assert budget.paged_mode("inspect", {"what": "outline"}) is budget.OUTLINE
    assert budget.paged_mode("inspect", {"what": "network"}) is budget.NETWORK
    assert budget.paged_mode("inspect", {"what": "node"}) is None
    assert budget.paged_mode("inspect", {"what": "geo"}) is None
    assert budget.paged_mode("inspect", {"what": "geo", "rows": True}) == budget.OffsetCursor()
    assert budget.paged_mode("inspect", {"what": "problems"}) == budget.OffsetCursor()
    assert budget.paged_mode("search", {}) is None
    assert budget.paged_mode("hda", {"action": "list"}) == budget.OffsetCursor()


def test_offset_cursor_with_start_resumes_after_the_kept_rows():
    rows = [[i, "x" * 60] for i in range(100, 400)]
    page = {"rows": rows, "start": 100, "total": 1000, "next_cursor": "400"}
    out, _ = budget.apply_budget(
        page, 4096, {"start": 100, "count": 300}, pageable=True, tool="geo_read"
    )
    assert out["next_cursor"] == str(100 + len(out["rows"]))


def test_host_event_log_pages_by_the_byte_budget():
    log = EventLog()
    for i in range(300):
        log.record("ParmTupleChanged", f"/obj/geo{i}/xf", {"parm": "t"}, origin="agent")
    first = log.read(0, 1000, budget=4096)
    kept = len(first["events"])
    assert 0 < kept < 300 and first["more"] is True
    assert first["next_since"] == first["events"][-1]["seq"]
    seen = [e["seq"] for e in first["events"]]
    since = first["next_since"]
    while True:
        page = log.read(since, 1000, budget=4096)
        seen += [e["seq"] for e in page["events"]]
        if not page.get("more"):
            break
        since = page["next_since"]
    assert seen == list(range(1, 301))


# -- following a trimmed cursor through the bridge -------------------------------------------


class ScriptedHost:
    """A host that ignores the byte budget (its pages overflow), so every cut is the
    bridge's. ``fn(args)`` answers as the real host does, from the cursor forms it takes."""

    def __init__(self, fn) -> None:
        self.fn = fn
        self.calls: list[dict[str, Any]] = []

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": HOST.pid, "houdini": "22.0.466", "generation": 1}

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append(dict(args))
        return True, self.fn(dict(args)), {}


def _follow(bridge: Bridge, tool: str, args: dict[str, Any], rows_of, cap: int):
    """Pages of ``tool`` by ``next_cursor`` until it stops: the row ids seen, in order,
    and how many pages that took."""
    seen: list[Any] = []
    pages = 0
    cursor: Any = None
    while True:
        call = dict(args) if cursor is None else {**args, "cursor": cursor}
        result = bridge.call_tool(tool, call)
        assert not result.is_error, result.content[0].text
        assert len(result.content[0].text.encode()) <= cap
        page = _text(result)
        assert "over_budget" not in page, "a page was sent whole"
        seen += rows_of(page)
        pages += 1
        assert pages < 200
        cursor = page.get("next_cursor")
        if cursor is None:
            return seen, pages


def _cursor_path(cursor: Any) -> str | None:
    if cursor in (None, ""):
        return None
    text = str(cursor)
    return text[len("after:") :] if text.startswith("after:") else text


def _nodes_host():
    all_rows = [
        {"path": path, "type": "geo" if path.count("/") == 2 else "Sop/box", "flags": ["display"]}
        for i in range(150)
        for path in (f"/obj/geo{i:03d}", f"/obj/geo{i:03d}/box1")
    ]

    def fn(args: dict[str, Any]) -> dict[str, Any]:
        after = _cursor_path(args.get("cursor"))
        rows = [r for r in all_rows if after is None or r["path"] > after]
        # The whole rest: the host's page overflows the bridge's budget.
        return {"nodes": rows, "common": {"category": "Object"}, "total": len(all_rows)}

    return all_rows, fn


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_following_search_nodes_cursors_visits_every_node_once(detail):
    all_rows, fn = _nodes_host()
    host = ScriptedHost(fn)
    bridge = _bridge(host, 4096)
    args = {"kind": "nodes", "root": "/obj", "detail": detail}
    seen, pages = _follow(bridge, "search", args, lambda p: [r["path"] for r in p["nodes"]], 4096)
    assert seen == [r["path"] for r in all_rows] and pages > 3
    # The host got the path of the last row kept, in the form the bridge wrote it.
    sent = [c["cursor"] for c in host.calls[1:]]
    assert all(c.startswith("after:/obj" if detail == "full" else "/obj") for c in sent), sent


def test_following_inspect_outline_cursors_visits_every_node_once():
    names = [f"geo{i:03d}" for i in range(400)]

    def fn(args: dict[str, Any]) -> dict[str, Any]:
        cursor = args.get("cursor")
        assert cursor is None or cursor.startswith("after:"), cursor  # the host demands it
        start = 0 if cursor is None else names.index(cursor[len("after:") :]) + 1
        rows = [
            {"path": f"/obj/{n}", "type": "geo", "children_count": 3, "flags": ["display"]}
            for n in names[start:]
        ]
        return {"etag": "p:1:aa", "root": "/obj", "nodes": rows, "node_count": len(rows)}

    host = ScriptedHost(fn)
    seen, pages = _follow(
        _bridge(host, 4096),
        "inspect",
        {"what": "outline", "target": "/obj", "depth": 1},
        lambda p: [r["path"].rsplit("/", 1)[-1] for r in p["nodes"]],
        4096,
    )
    assert seen == names and pages > 3


def test_following_inspect_network_cursors_visits_every_node_once():
    names = [f"geo{i:03d}" for i in range(400)]

    def fn(args: dict[str, Any]) -> dict[str, Any]:
        cursor = args.get("cursor")
        assert cursor is None or cursor.startswith("after:"), cursor
        start = 0 if cursor is None else names.index(cursor[len("after:") :]) + 1
        data = {n: {"type": "geo", "flags": {"display": True}} for n in names[start:]}
        return {"root": "/obj", "format": "data", "data": data, "node_count": len(data)}

    host = ScriptedHost(fn)
    seen, pages = _follow(
        _bridge(host, 4096),
        "inspect",
        {"what": "network", "target": "/obj"},
        lambda p: list(p["data"]),
        4096,
    )
    assert seen == names and pages > 3


def test_following_search_types_cursors_visits_every_type_once():
    names = [f"type{i:04d}" for i in range(700)]

    def fn(args: dict[str, Any]) -> dict[str, Any]:
        cursor = args.get("cursor")
        offset = 0 if cursor is None else int(cursor[len("t:") :])  # the host's own parse
        rows = [{"name": n, "label": n.title(), "category": "Sop"} for n in names[offset:]]
        return {"results": rows, "total": len(names)}

    seen, pages = _follow(
        _bridge(ScriptedHost(fn), 4096),
        "search",
        {"kind": "types", "query": "a", "limit": 1000},
        lambda p: [r["name"] for r in p["results"]],
        4096,
    )
    assert seen == names and pages > 3


def test_following_inspect_events_cursors_visits_every_event_once():
    host = EventsHost(300)
    bridge = _bridge(host, 4096)
    seen: list[int] = []
    since: Any = 0
    for _ in range(100):
        page = _text(bridge.call_tool("inspect", {"what": "events", "since": since, "limit": 1000}))
        assert "over_budget" not in page
        seen += [e["seq"] for e in page["events"]]
        if not page.get("more"):
            break
        since = page["next_since"]
    assert seen == list(range(1, 301))
