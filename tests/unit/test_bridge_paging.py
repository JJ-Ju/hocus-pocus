"""Budget cuts of paged results never skip rows (review 22 finding 1, BIBLE §4.1).

Every cursor style the bridge can trim is rewritten to resume right after the last row
kept: ``events``' ``next_since`` (``<pid>:<seq>``), ``after:<path>`` (``node_find``),
``after:<name>`` (``network_describe``) and integer offsets (``geo_read`` with ``start``).
Anything else is left whole with ``over_budget``."""

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


def test_after_path_cursor_is_rewritten_to_the_last_kept_row():
    rows = [{"path": f"/obj/geo{i:04d}", "type": "geo", "pad": "x" * 60} for i in range(400)]
    page = {"root": "/obj", "nodes": rows, "total": 1000, "next_cursor": "after:/obj/geo0399"}
    out, cuts = budget.apply_budget(page, 4096, {}, pageable=True, tool="node_find")
    kept = len(out["nodes"])
    assert 0 < kept < 400 and out["nodes"] == rows[:kept]
    assert out["next_cursor"] == f"after:{rows[kept - 1]['path']}"
    assert cuts[0]["next_cursor"] == out["next_cursor"]
    # The last page (no host cursor) gets one too, so its trimmed rows come next.
    last = {"root": "/obj", "nodes": rows, "total": 400}
    out, _ = budget.apply_budget(
        last, 4096, {"cursor": "after:/obj/a"}, pageable=True, tool="node_find"
    )
    assert out["next_cursor"] == f"after:{rows[len(out['nodes']) - 1]['path']}"


def test_after_name_cursor_of_an_outline_names_the_last_kept_row():
    rows = [
        {"path": f"/obj/n{i}", "name": f"n{i}", "type": "null", "pad": "y" * 80} for i in range(200)
    ]
    page = {"root": "/obj", "format": "outline", "nodes": rows}
    out, _ = budget.apply_budget(
        page, 4096, {"format": "outline"}, pageable=True, tool="network_describe"
    )
    assert out["next_cursor"] == f"after:{rows[len(out['nodes']) - 1]['name']}"


def test_network_describe_data_format_is_never_trimmed():
    page = {
        "root": "/obj",
        "format": "data",
        "data": {f"n{i}": {"pad": "z" * 80} for i in range(200)},
    }
    out, cuts = budget.apply_budget(page, 4096, {}, pageable=True, tool="network_describe")
    assert out["over_budget"] is True and out["data"] == page["data"] and cuts[0]["over_budget"]


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
