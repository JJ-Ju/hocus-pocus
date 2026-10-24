"""Integration tier: runs INSIDE hython (``hython -m pytest tests/integration``).

One in-process host per session with isolated state and pref dirs; every call goes
through the real HTTP server with the real token, so the ``hp/v1`` envelope is tested.
In hython the test thread is the main thread: :class:`HostClient` sends each request
from a helper thread and pumps the headless executor on the main thread until the
response arrives. Each test starts from ``hou.hipFile.clear()``.

See docs/CONTRIBUTING.md for the exact command (isolated ``HOUDINI_USER_PREF_DIR``,
neutral working directory).

Profiles (spec-2.0 §2): the session host runs ``full``, the largest profile.

The 1.4 read engines (BIBLE Appendix A). 2.1 removed the 1.4 tools with ``compat_1x``; the
reads behind ``inspect`` and ``search`` are still host functions named after them
(``nodes.node_info``, ``geo.geo_read``, ...). The engine tests call them by those names:
``client.call("node_info", args)`` runs :data:`READ_ENGINES`'s function in process, on
hython's main thread (the test thread), and returns an envelope of the same shape, so a
test sees the engine's own result or error exactly, without ``inspect``'s 2.0 projection.
Any other removed 1.4 name goes to the host and answers ``invalid_argument``; the 1.4
mutation tools and ``viewport_capture`` have no engine of their own (``edit`` ops and
``look`` replace them).

``test_parity_gui.py`` (marker ``gui``) is the GUI column of docs/parity.md: it runs in the
dev venv's Python, launches ``houdinifx`` with an isolated pref dir and drives it over HTTP.
It is deselected unless ``--rungui`` is given (which also implies ``--runslow``); nothing
here changes for the headless tier.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

try:
    import hou
except ImportError:  # plain CPython: every integration test module skips itself
    hou = None


def check_output_schema(tool: str, result: Any) -> None:
    """Every successful result must satisfy the catalogue's outputSchema: MCP clients
    (the official SDK among them) validate ``structuredContent`` against it. Bridge-local
    tools are skipped (the bridge, not the host, builds their result)."""
    from hocuspocus.tools.catalog import get
    from hocuspocus.tools.docs import validate

    spec = get(tool)
    if spec is None or spec.bridge_local or spec.output_schema is None:
        return
    validate(result, spec.output_schema, f"{tool}")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rungui",
        action="store_true",
        default=False,
        help="run the GUI parity session (marker gui: launches houdinifx with an isolated "
        "pref dir; implies --runslow)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "gui: launches a GUI houdinifx (docs/parity.md); run with --rungui"
    )
    if config.getoption("--rungui", default=False):
        # The GUI session is also marked slow, which tests/conftest.py deselects unless
        # asked for; --rungui asks for it.
        config.option.runslow = True


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--rungui", default=False):
        return
    gui = [item for item in items if "gui" in item.keywords]
    if gui:
        config.hook.pytest_deselected(items=gui)
        items[:] = [item for item in items if "gui" not in item.keywords]


def pytest_sessionstart(session: pytest.Session) -> None:
    if hou is None:
        return
    # hython fills HOUDINI_USER_PREF_DIR in-process even when the caller did not set it,
    # so compare the resolved pref dir against the user's real default locations.
    major, minor = hou.applicationVersion()[:2]
    name = f"houdini{major}.{minor}"
    real = {
        os.path.normcase(os.path.abspath(p))
        for p in (Path.home() / name, Path.home() / "Documents" / name)
    }
    resolved = os.path.normcase(os.path.abspath(hou.homeHoudiniDirectory()))
    if resolved in real:
        pytest.exit(
            "Integration tests need an isolated HOUDINI_USER_PREF_DIR (e.g. "
            "<tmp>/houdini__HVER__) so they never touch your real Houdini prefs. "
            "See docs/CONTRIBUTING.md.",
            returncode=4,
        )


@dataclass
class Response:
    status: int
    body: Any
    headers: dict[str, str]


READ_ENGINES: dict[str, tuple[str, str]] = {
    "node_find": ("nodes", "node_find"),
    "node_info": ("nodes", "node_info"),
    "network_describe": ("network", "network_describe"),
    "parm_get": ("parms", "parm_get"),
    "problems": ("cook", "problems"),
    "geo_info": ("geo", "geo_info"),
    "geo_read": ("geo", "geo_read"),
    "node_type_search": ("types", "node_type_search"),
    "node_type_info": ("types", "node_type_info"),
    "usd_stage": ("usd", "usd_stage"),
}
"""1.4 read name -> ``(hocuspocus.host.tools module, function)``: the engine ``inspect`` or
``search`` runs for it (module docstring)."""


def run_read_engine(host: Any, tool: str, args: dict[str, Any], timeout_s: Any) -> dict:
    """One 1.4 read engine called in process on the main thread, as the dispatcher would
    run it (the call's response budget and timeout set), wrapped in an ``hp/v1`` envelope.
    ``_meta`` carries the scene generation; the rest is what a read reports."""
    import importlib

    from hocuspocus.host import dispatch

    module, name = READ_ENGINES[tool]
    fn = getattr(importlib.import_module(f"hocuspocus.host.tools.{module}"), name)
    ctx = host.ctx
    started = time.perf_counter()
    ctx.extras["max_response_bytes"] = int(host.config.max_response_bytes)
    saved = getattr(dispatch._CALL, "timeout_s", None)
    dispatch._CALL.timeout_s = dispatch.Dispatcher(ctx, lambda n: None).effective_timeout(
        args, timeout_s
    )
    try:
        result = fn(dict(args), ctx)
        envelope: dict[str, Any] = {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - the dispatcher maps every failure
        envelope = {"ok": False, "error": dispatch.tool_error_from_exception(exc).to_dict()}
    finally:
        dispatch._CALL.timeout_s = saved
    envelope["_meta"] = {
        "scene_generation": ctx.scene.generation,
        "undo_label": None,
        "elapsed_ms": int(round((time.perf_counter() - started) * 1000)),
        "timing": {"main_thread_ms": 0},
    }
    return envelope


class HostClient:
    """HTTP client that pumps the main-thread executor while it waits. ``profile`` is sent
    with every call, as the bridge sends its own (the host's hints name that profile's
    tools). A 1.4 read name runs its engine in process (:func:`run_read_engine`) unless
    ``wire=True`` sends it to the host, which refuses it as a removed tool."""

    def __init__(self, host: Any, profile: str | None = None) -> None:
        self.host = host
        self.profile = profile

    @property
    def port(self) -> int:
        return self.host.port

    @property
    def token(self) -> str:
        return self.host.token

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        token: str | None | bool = True,
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> Response:
        send_headers = {"Content-Type": "application/json"}
        if token is True:
            send_headers["Authorization"] = f"Bearer {self.token}"
        elif isinstance(token, str):
            send_headers["Authorization"] = f"Bearer {token}"
        send_headers.update(headers or {})
        payload = None if body is None else json.dumps(body).encode("utf-8")
        box: dict[str, Any] = {}

        def worker() -> None:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
                conn.request(method, path, body=payload, headers=send_headers)
                resp = conn.getresponse()
                raw = resp.read()
                box["response"] = Response(
                    resp.status, json.loads(raw) if raw else None, dict(resp.getheaders())
                )
                conn.close()
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while thread.is_alive():
            self.host.executor.pump_once(0.01)
            if time.monotonic() > deadline:
                raise TimeoutError(f"{method} {path} did not complete in {timeout}s")
        if "error" in box:
            raise box["error"]
        return box["response"]

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        wire: bool = False,
    ) -> dict[str, Any]:
        if tool in READ_ENGINES and not wire:
            return run_read_engine(self.host, tool, args or {}, timeout_s)
        body: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "request_id": f"test-{time.time_ns()}",
        }
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        if self.profile:
            body["profile"] = self.profile
        response = self.request("POST", "/hp/v1/call", body)
        assert response.status == 200, response.body
        envelope = response.body
        assert set(envelope) == {"ok", "result", "_meta"} or set(envelope) == {
            "ok",
            "error",
            "_meta",
        }, envelope
        assert set(envelope["_meta"]) == {"scene_generation", "undo_label", "elapsed_ms", "timing"}
        assert envelope["_meta"]["timing"]["main_thread_ms"] >= 0
        return envelope

    def ok(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        envelope = self.call(tool, args, **kw)
        assert envelope["ok"] is True, envelope
        check_output_schema(tool, envelope["result"])
        return envelope["result"]

    def error(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        envelope = self.call(tool, args, **kw)
        assert envelope["ok"] is False, envelope
        return envelope["error"]


@pytest.fixture(scope="session")
def hp_dirs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("hocuspocus")
    dirs = {"base": base, "state": base / "state", "prefs": base / "prefs", "work": base / "work"}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture(scope="session")
def host(hp_dirs: dict[str, Path]) -> Any:
    if hou is None:
        pytest.skip("needs hython")
    import hocuspocus.host as hp
    from hocuspocus.host.config import HostConfig

    os.environ["HOCUSPOCUS_STATE_DIR"] = str(hp_dirs["state"])
    # profile "full", never minimal or core: those hosts refuse the tools outside them
    # (pdg, hda, events), and full lists every tool (test_profiles_are_nested).
    config = HostConfig(
        state_dir=str(hp_dirs["state"]), pref_dir=str(hp_dirs["prefs"]), profile="full"
    )
    info = hp.start(config)
    assert info["running"], info
    running = hp.current()
    assert running is not None
    assert running.config.profile == "full"
    assert running.executor.backend == "headless"
    yield running
    hp.stop()


@pytest.fixture
def client(host: Any) -> HostClient:
    """The session's ``full`` host."""
    return HostClient(host)


@pytest.fixture
def v2_client(client: HostClient) -> HostClient:
    """The fixture of the 2.0 tools' tests, which compare each 2.0 tool with the 1.4 read
    engine it runs (``_same``): the same client (module docstring)."""
    return client


@pytest.fixture(autouse=True)
def clean_scene(request: pytest.FixtureRequest) -> Any:
    if hou is None or "host" not in request.fixturenames and "client" not in request.fixturenames:
        yield
        return
    host = request.getfixturevalue("host")
    hou.hipFile.clear(suppress_save_prompt=True)
    saved = (host.config.read_only, host.config.allow_python, list(host.config.approved_roots))
    yield
    host.config.read_only, host.config.allow_python, host.config.approved_roots = saved


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def crash_capture_child(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``crash(rop_type)`` makes every look child that renders ``rop_type``
    (``flipbook`` or ``opengl``) exit as a segfault would, and forgets earlier crashes."""
    from hocuspocus.host.tools import visual

    def crash(rop_type: str) -> None:
        prefix = (
            "import json, os, sys\n"
            "with open(sys.argv[1], encoding='utf-8') as fh:\n"
            f"    if (json.load(fh).get('capture') or {{}}).get('rop_type') == {rop_type!r}:\n"
            "        os._exit(139)\n"
        )
        monkeypatch.setattr(visual, "_CHILD_SCRIPT", prefix + visual._CHILD_SCRIPT)
        monkeypatch.setattr(visual, "_stage_crashed", {})

    return crash
