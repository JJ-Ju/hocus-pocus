"""A large network paged through the bridge with a small ``max_response_bytes`` (BIBLE §4.1).

Against a real headless host (``hython -m hocuspocus.host``, isolated state, never port
37219), following ``next_cursor`` of ``search kind: nodes``, ``inspect what: outline`` and
``inspect what: network`` must visit every node exactly once:

1. In process (the bridge object with a client that tells the host a 2 MB budget): the host
   answers each read with one page far over the bridge's 4 KB, so every page is the bridge's
   trim, and the cursor it writes goes back to the real host. 2.0 keyed this trim by the
   1.4 tool names, so these pages came back whole with ``over_budget: true``.
2. Over stdio, as a client sees it (official MCP client → ``hocuspocus-mcp`` with
   ``HOCUSPOCUS_MAX_RESPONSE_BYTES=4096``): the host pages by the budget itself.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest
from scenario_host import SRC, headless_host, hython  # noqa: F401

pytestmark = pytest.mark.e2e

COUNT = 80
CAP = 4096
NAMES = [f"city{i:03d}" for i in range(COUNT)]


def _build_ops() -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for name in NAMES:
        ops.append({"op": "create", "id": name, "parent": "/obj", "type": "geo", "name": name})
        ops.append({"op": "create", "parent": f"${name}", "type": "box", "name": "box1"})
    return ops


def _check_chain(pages_of) -> None:
    """``pages_of(tool, args)`` yields the pages of a read in order; all three modes."""
    nodes = [r["path"] for page in pages_of("search", {"kind": "nodes", "root": "/obj"})
             for r in page["nodes"]]  # fmt: skip
    expected = [p for name in NAMES for p in (f"/obj/{name}", f"/obj/{name}/box1")]
    assert nodes == expected
    outline = [r["path"] for page in pages_of("inspect", {"what": "outline", "target": "/obj",
                                                          "depth": 1}) for r in page["nodes"]]  # fmt: skip
    assert outline == [f"/obj/{name}" for name in NAMES]
    network = [n for page in pages_of("inspect", {"what": "network", "target": "/obj"})
               for n in page["data"]]  # fmt: skip
    assert network == NAMES


def test_a_large_network_pages_through_the_bridge_exactly_once(
    headless_host,  # noqa: F811 - the fixture above
    tmp_path,
    monkeypatch,
):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    from hocuspocus.bridge.client import HostClient
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    _proc, state = headless_host
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(state))

    class WideClient(HostClient):
        """Asks the host for a page far over the bridge's budget."""

        def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
            return super().call(tool, args, timeout_s, request_id, 2_000_000)

    bridge = Bridge(
        BridgeConfig(profile="core", max_response_bytes=CAP),
        client_factory=lambda port, token: WideClient(port, token),
    )
    ok_edit = bridge.call_tool("edit", {"ops": _build_ops()})
    assert not ok_edit.is_error, ok_edit.content[0].text

    trimmed: list[int] = []

    def in_process(tool: str, args: dict[str, Any]):
        cursor: Any = None
        while True:
            call = dict(args) if cursor is None else {**args, "cursor": cursor}
            result = bridge.call_tool(tool, call)
            assert not result.is_error, result.content[0].text
            assert len(result.content[0].text.encode()) <= CAP
            page = json.loads(result.content[0].text)
            assert "over_budget" not in page, f"{tool} {call}: sent whole"
            trimmed.append(1 if page.get("truncated") else 0)
            yield page
            cursor = page.get("next_cursor")
            if cursor is None:
                return

    _check_chain(in_process)
    assert sum(trimmed) >= 6  # every mode was cut by the bridge, more than one page each

    env = dict(os.environ)
    env.update(
        {
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_MAX_RESPONSE_BYTES": str(CAP),
            "PYTHONPATH": str(SRC),
            "HOUDINI_USER_PREF_DIR": (tmp_path / "bridge-prefs" / "houdini__HVER__").as_posix(),
        }
    )
    env.pop("HOCUSPOCUS_PROFILE", None)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(tmp_path)
    )
    failures: list[BaseException] = []

    async def run() -> None:
        async with Client(params, read_timeout_seconds=180) as client:
            try:
                pages: dict[tuple[str, str], list[dict[str, Any]]] = {}
                for tool, args in (
                    ("search", {"kind": "nodes", "root": "/obj"}),
                    ("inspect", {"what": "outline", "target": "/obj", "depth": 1}),
                    ("inspect", {"what": "network", "target": "/obj"}),
                ):
                    cursor: Any = None
                    mine: list[dict[str, Any]] = []
                    while True:
                        call = dict(args) if cursor is None else {**args, "cursor": cursor}
                        result = await client.call_tool(tool, call)
                        assert not result.is_error, result.content[0].text
                        assert len(result.content[0].text.encode()) <= CAP
                        page = json.loads(result.content[0].text)
                        assert "over_budget" not in page
                        mine.append(page)
                        cursor = page.get("next_cursor")
                        if cursor is None:
                            break
                        assert len(mine) < 100
                    assert len(mine) > 1, (tool, args)
                    pages[(tool, json.dumps(args, sort_keys=True))] = mine

                def replay(tool: str, args: dict[str, Any]):
                    return iter(pages[(tool, json.dumps(args, sort_keys=True))])

                _check_chain(replay)
            except AssertionError as exc:  # re-raised below, outside the task groups
                failures.append(exc)

    anyio.run(run)
    if failures:
        raise failures[0]
