"""The bridge's budget trim against the real shapes of the host's paged reads (BIBLE §4.1).

``bridge/budget.py`` rewrites the cursor of a page that is still over ``max_response_bytes``
so it resumes right after the last row kept. Until 2.1 it was keyed by the 1.4 tool names,
so a ``search kind: nodes`` or ``inspect what: network`` page was never trimmed. Here the
host answers with a budget far above the bridge's (so its page is one big page) and the
bridge's :func:`apply_budget` trims it to a small budget; the next call sends the cursor it
wrote back to the real host. Following ``next_cursor`` must visit every node exactly once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

hou = pytest.importorskip("hou")

from hocuspocus.bridge import budget  # noqa: E402

CAP = 4096
HOST_BUDGET = 4_000_000
COUNT = 90


def _scene() -> None:
    obj = hou.node("/obj")
    for i in range(COUNT):
        obj.createNode("geo", f"geo{i:03d}").createNode("box", "box1")


def _host_page(client, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    body = {"tool": tool, "args": args, "request_id": "t", "max_response_bytes": HOST_BUDGET}
    response = client.request("POST", "/hp/v1/call", body)
    assert response.status == 200 and response.body["ok"] is True, response.body
    return response.body["result"]


def _follow(
    client, tool: str, args: dict[str, Any], rows_of: Callable[[dict[str, Any]], list[str]]
) -> tuple[list[str], int, list[dict[str, Any]]]:
    """``(row ids seen, pages, pages)`` following the cursor the bridge writes."""
    seen: list[str] = []
    pages: list[dict[str, Any]] = []
    cursor: Any = None
    while True:
        call = dict(args) if cursor is None else {**args, "cursor": cursor}
        page, cuts = budget.apply_budget(
            _host_page(client, tool, call), CAP, call, pageable=True, tool=tool
        )
        assert "over_budget" not in page, (call, cuts)
        assert budget.size(page) <= CAP
        seen += rows_of(page)
        pages.append(page)
        assert len(pages) < 100
        cursor = page.get("next_cursor")
        if cursor is None:
            return seen, len(pages), pages


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_search_nodes_pages_visit_every_node_once(client, detail):
    _scene()
    args = {"kind": "nodes", "root": "/obj", "limit": 1000, "detail": detail}
    expected = [r["path"] for r in _host_page(client, "search", args)["nodes"]]
    assert len(expected) == 2 * COUNT
    seen, pages, results = _follow(
        client, "search", args, lambda p: [r["path"] for r in p["nodes"]]
    )
    assert seen == expected and pages > 3
    prefix = "after:" if detail == "full" else ""
    assert all(p["next_cursor"].startswith(f"{prefix}/obj/") for p in results[:-1])
    assert results[0]["total"] == 2 * COUNT and "next_cursor" not in results[-1]


def test_search_nodes_accepts_the_bare_path_it_wrote_in_either_form(client):
    _scene()
    args = {"kind": "nodes", "root": "/obj", "limit": 1000}
    first, _ = budget.apply_budget(
        _host_page(client, "search", args), CAP, args, pageable=True, tool="search"
    )
    last = first["nodes"][-1]["path"]
    assert first["next_cursor"] == last
    bare = _host_page(client, "search", {**args, "cursor": first["next_cursor"]})["nodes"]
    prefixed = _host_page(client, "search", {**args, "cursor": f"after:{last}"})["nodes"]
    assert bare == prefixed and bare[0]["path"] > last


def test_inspect_outline_pages_visit_every_node_once(client):
    _scene()
    args = {"what": "outline", "target": "/obj", "depth": 1}
    whole = _host_page(client, "inspect", args)
    expected = [r["path"] for r in whole["nodes"]]
    assert expected == [f"/obj/geo{i:03d}" for i in range(COUNT)]
    seen, pages, results = _follow(
        client, "inspect", args, lambda p: [r["path"] for r in p["nodes"]]
    )
    assert seen == expected and pages > 1
    for page in results:
        assert page["node_count"] == len(page["nodes"])  # depth 1: one node per row
    assert results[0]["next_cursor"] == f"after:geo{len(results[0]['nodes']) - 1:03d}"


def test_inspect_network_pages_visit_every_node_once(client):
    _scene()
    args = {"what": "network", "target": "/obj"}
    whole = _host_page(client, "inspect", args)
    assert isinstance(whole["data"], dict)  # keyed by name, not a list of rows
    expected = list(whole["data"])
    assert expected == [f"geo{i:03d}" for i in range(COUNT)]
    seen, pages, results = _follow(client, "inspect", args, lambda p: list(p["data"]))
    assert seen == expected and pages > 1
    first = results[0]
    assert first["next_cursor"] == f"after:{list(first['data'])[-1]}"
    assert first["node_count"] == len(first["data"]) and first["bytes"] == budget.size(
        first["data"]
    )
    assert first["data"]["geo000"] == whole["data"]["geo000"]


def test_search_types_pages_visit_every_type_once(client):
    args = {"kind": "types", "query": "noise", "limit": 100}
    whole = _host_page(client, "search", args)
    expected = [r["name"] for r in whole["results"]]
    assert 20 < len(expected) == whole["total"] and "next_cursor" not in whole
    seen, pages, results = _follow(
        client, "search", args, lambda p: [r["name"] for r in p["results"]]
    )
    assert seen == expected and pages > 1  # the bridge's t:<offset> resumes where it cut
    assert results[0]["next_cursor"] == f"t:{len(results[0]['results'])}"
