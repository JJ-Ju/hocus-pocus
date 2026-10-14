"""Integration tier: runs INSIDE hython (``hython -m pytest tests/integration``).

One in-process host per session with isolated state and pref dirs; every call goes
through the real HTTP server with the real token, so the ``hp/v1`` envelope is tested.
In hython the test thread is the main thread: :class:`HostClient` sends each request
from a helper thread and pumps the headless executor on the main thread until the
response arrives. Each test starts from ``hou.hipFile.clear()``.

See docs/CONTRIBUTING.md for the exact command (isolated ``HOUDINI_USER_PREF_DIR``,
neutral working directory).

Profiles (spec-2.0 §2, §8): the session host runs ``full``, the largest 2.0 profile, which
refuses the 1.4 tools 2.0 removed. ``compat_client`` sends ``profile: compat_1x`` with every
call, as a ``compat_1x`` bridge does, so the host runs the 1.4 tools (and the 2.0 ones). A
module written against the 1.4 tools sets ``pytestmark = pytest.mark.compat_1x``, which makes
its ``client`` the compat client; every other module's ``client`` is the plain ``full`` one.

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
    config.addinivalue_line(
        "markers",
        "compat_1x: the module calls the 1.4 tools; its client fixture sends profile compat_1x",
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


class HostClient:
    """HTTP client that pumps the main-thread executor while it waits. ``profile`` is sent
    with every call, as the bridge sends its own (``compat_1x`` runs the 1.4 tools)."""

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
        self, tool: str, args: dict[str, Any] | None = None, timeout_s: float | None = None
    ) -> dict[str, Any]:
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
    # (pdg, hda, events), and full lists every 2.0 tool (test_profiles_are_nested). The 1.4
    # tools run through compat_client (module docstring).
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
def compat_client(host: Any) -> HostClient:
    """A client whose calls carry ``profile: compat_1x``, as a ``compat_1x`` bridge's do: the
    ``full`` host runs every 1.4 tool for it, and the 2.0 tools too (spec-2.0 §8)."""
    return HostClient(host, profile="compat_1x")


@pytest.fixture
def client(host: Any, request: pytest.FixtureRequest) -> HostClient:
    """The session's ``full`` host; ``compat_client`` in a module marked ``compat_1x``."""
    if request.node.get_closest_marker("compat_1x") is not None:
        return request.getfixturevalue("compat_client")
    return HostClient(host)


@pytest.fixture
def v2_client(compat_client: HostClient) -> HostClient:
    """The M1-M2 fixture of the 2.0 tools' tests, which compare each 2.0 tool with the 1.4
    tools it replaces (``_same``): both run under ``compat_1x``. A 2.0-only test can take
    ``client``, since the session host runs ``full``."""
    return compat_client


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
    """``crash(rop_type)`` makes every viewport_capture child that renders ``rop_type``
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
