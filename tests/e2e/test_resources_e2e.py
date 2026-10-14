"""End to end, profile full (spec-2.0 §2.7): the official MCP client lists the resource
templates, reads a node resource twice (the second read, with the first etag as
``_meta["If-None-Match"]``, is ``not_modified``), subscribes to the node and receives
``notifications/resources/updated`` within 2 s of a ``parm_set``; over the 2026-07-28
``subscriptions/listen`` stream and over a handshake-era ``resources/subscribe``.

The host and the bridge read ``profile = "full"`` from ``hocuspocus.toml`` in the isolated
pref dir (``prefs/houdini22.0/``). Never uses port 37219; hython runs from a neutral cwd.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SRC = Path(__file__).resolve().parents[2] / "src"
REGISTER_TIMEOUT_S = 120.0
NODE = "/obj/geo1/box1"
NODE_URI = "houdini://node/obj/geo1/box1"


def _find_hython() -> Path | None:
    exe = "hython.exe" if sys.platform == "win32" else "hython"
    explicit = os.environ.get("HOUDINI_HYTHON")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    sys.path.insert(0, str(SRC))
    try:
        from hocuspocus.bridge.launch import detect_hfs
    finally:
        sys.path.remove(str(SRC))
    hfs = detect_hfs(None)
    return hfs / "bin" / exe if hfs else None


@pytest.fixture(scope="module")
def v2_host(tmp_path_factory):
    hython = _find_hython()
    if hython is None or not hython.is_file():
        pytest.skip("hython not found (set HOUDINI_HYTHON or HFS)")
    base = tmp_path_factory.mktemp("res")
    state, prefs, cwd, work = (base / n for n in ("state", "prefs", "cwd", "work"))
    for d in (state, prefs / "houdini22.0", cwd):
        d.mkdir(parents=True)
    # Houdini expands __HVER__: the host and the bridge read prefs/houdini22.0/.
    (prefs / "houdini22.0" / "hocuspocus.toml").write_text('profile = "full"\n', encoding="utf-8")
    env = dict(os.environ)
    env.pop("HOCUSPOCUS_PROFILE", None)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_WORK_DIR": str(work),
            "HOUDINI_USER_PREF_DIR": (prefs / "houdini__HVER__").as_posix(),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    log = open(base / "hython.log", "wb")  # noqa: SIM115 - closed in teardown
    proc = subprocess.Popen(
        [str(hython), "-m", "hocuspocus.host", "--port", "0", "--state-dir", str(state)],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    entry = state / "instances" / f"{proc.pid}.json"
    deadline = time.monotonic() + REGISTER_TIMEOUT_S
    try:
        while not entry.is_file():
            if proc.poll() is not None:
                log.flush()
                pytest.fail(f"hython exited:\n{(base / 'hython.log').read_text(errors='replace')}")
            if time.monotonic() > deadline:
                pytest.fail("headless host did not register in time")
            time.sleep(0.25)
        info = json.loads(entry.read_text(encoding="utf-8"))
        assert info["port"] != 37219
        yield proc, env, base
    finally:
        try:
            from hocuspocus.bridge.client import HostClient

            info = json.loads(entry.read_text(encoding="utf-8")) if entry.is_file() else None
            if info and proc.poll() is None:
                HostClient(info["port"], info["token"]).shutdown()
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001 - fall through to a hard stop of *our* process
            proc.kill()
            proc.wait(timeout=30)
        log.close()


def _params(env, base):
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable, args=["-m", "hocuspocus.bridge"], env=env, cwd=str(base)
    )


def _text(result) -> dict:
    return json.loads(result.content[0].text)


async def _build(client) -> None:
    status = _text(await client.call_tool("houdini_status", {}))
    assert status["profile"] == "full", status
    await client.call_tool("hip_new", {"on_unsaved": "discard"})
    made = await client.call_tool(
        "node_create",
        {"items": [{"parent": "/obj", "type": "geo", "name": "geo1"}]},
    )
    assert not made.is_error, made.content
    made = await client.call_tool(
        "node_create", {"items": [{"parent": "/obj/geo1", "type": "box", "name": "box1"}]}
    )
    assert not made.is_error, made.content


async def _set(client, value: float) -> None:
    done = await client.call_tool(
        "parm_set", {"items": [{"path": f"{NODE}/sizey", "value": value}]}
    )
    assert not done.is_error, done.content


def test_templates_read_not_modified_and_listen(v2_host):
    import anyio
    from mcp import Client

    proc, env, base = v2_host

    async def run():
        async with Client(_params(env, base), read_timeout_seconds=120) as client:
            assert client.server_capabilities.resources.subscribe is True
            templates = (await client.list_resource_templates()).resource_templates
            await _build(client)
            first = await client.read_resource(NODE_URI, cache_mode="bypass")
            etag = first.meta["etag"]
            second = await client.read_resource(NODE_URI, meta={"If-None-Match": etag})
            tool = await client.call_tool("inspect", {"what": "node", "target": NODE})
            async with client.listen(resource_subscriptions=[NODE_URI]) as sub:
                started = time.monotonic()
                await _set(client, 3.0)
                with anyio.fail_after(2.0):
                    event = await sub.__anext__()
                waited = time.monotonic() - started
            after = await client.read_resource(NODE_URI, meta={"If-None-Match": etag})
            return templates, first, second, tool, event, waited, after

    templates, first, second, tool, event, waited, after = anyio.run(run)
    advertised = [t.uri_template for t in templates]
    assert "houdini://node/{path}{?include,parms,include_defaults}" in advertised
    assert "houdini://type/{category}/{name}{?parms,folder,detail}" in advertised
    body = first.contents[0].text
    assert json.loads(body)["etag"] == first.meta["etag"]
    assert first.meta["instance"]["pid"] == proc.pid
    assert body == tool.content[0].text  # the resource is the inspect result, byte for byte
    assert second.contents == [] and second.meta["not_modified"] is True
    assert event.uri == NODE_URI and waited < 2.0
    assert after.contents and after.meta["etag"] != first.meta["etag"]


def test_subscribe_handshake_era(v2_host):
    import anyio
    from mcp import Client

    _proc, env, base = v2_host
    updates: list[str] = []

    async def on_message(message):
        if getattr(message, "method", "") == "notifications/resources/updated":
            updates.append(str(message.params.uri))

    async def run():
        async with Client(
            _params(env, base), mode="legacy", read_timeout_seconds=120, message_handler=on_message
        ) as client:
            caps = client.server_capabilities.resources
            assert caps.subscribe is True and caps.list_changed is True
            await _build(client)
            await client.read_resource(NODE_URI)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # resources/subscribe is the 2025 way
                await client.session.subscribe_resource(NODE_URI)
                await _set(client, 4.0)
                with anyio.fail_after(2.0):
                    while not updates:
                        await anyio.sleep(0.05)
                await client.session.unsubscribe_resource(NODE_URI)

    anyio.run(run)
    assert updates[0] == NODE_URI
