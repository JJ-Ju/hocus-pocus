"""The workloads tier (docs/redesign/spec-2.0.md §5.2): the evaluation workloads as tests.

One headless host (``hython -m hocuspocus.host``) serves the whole session, with an
isolated ``HOCUSPOCUS_STATE_DIR``, ``HOUDINI_USER_PREF_DIR`` (``__HVER__``, with the
tier's ``profile`` in ``prefs/houdini22.0/hocuspocus.toml``), work dir and temp dir, and
a neutral cwd. One persistent official ``mcp`` client session drives the stdio bridge
(``python -m hocuspocus.bridge``) from a background event loop, so the tests stay
synchronous and every workload talks to the same bridge, as an agent would.

The ``workload`` fixture hands each test a :class:`Recorder`. It wraps ``call_tool`` and
records, per call: tool, args bytes, text bytes (the JSON text block the model reads; image
content is counted apart), elapsed time and ``isError``. Per workload it totals calls, text
bytes, the largest call, wall time and the time to the first image. ``Recorder.finish``
checks the totals against ``budgets.json`` (each at most 115 % of its budget), or with
``--update-budgets`` records them there; either way they go to ``last_run.json``.

Text bytes are counted with this session's temporary root replaced by ``<tmp>``, so a
budget does not depend on how long the machine's temp path is. Between workloads the
scene is cleared with ``hip_new {on_unsaved: discard}``, running jobs are cancelled and the
workload's files are deleted. Never uses port 37219; kills only processes it started.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
HERE = Path(__file__).resolve().parent
BUDGETS = HERE / "budgets.json"
LAST_RUN = HERE / "last_run.json"
try:  # spec-2.0 M3 cut-over: the 1.4 catalogue is ``compat_1x``, ``full`` the 2.0 one
    from hocuspocus.tools.profiles import COMPAT_1X as PROFILE_1X
except ImportError:  # before it: ``full`` is the 1.4 catalogue
    PROFILE_1X = "full"
"""The profile the 1.4 workloads run under; the 2.0 workloads (``v2/``) choose their own."""
TOLERANCE = 1.15
"""A workload fails when a measured total exceeds its budget by more than 15 % (§5.2)."""
BUDGET_KEYS = ("calls", "text_bytes", "max_call_bytes", "wall_s")
WALL_ALLOWANCE_S = 5.0
"""Wall time gets a flat allowance on top of the tolerance: a cold capture child or a
licence check adds seconds that have nothing to do with the workload under test."""


def _limit(key: str, budget: float) -> float:
    limit = budget * TOLERANCE
    if key == "wall_s":
        limit = max(limit, budget + WALL_ALLOWANCE_S)
    return limit


REGISTER_TIMEOUT_S = 180.0
CALL_TIMEOUT_S = 300.0


def fwd(path: Path | str) -> str:
    return str(path).replace("\\", "/")


# -- the persistent MCP session -----------------------------------------------------------


class McpSession:
    """One official ``mcp.Client`` over stdio, kept open on a background event loop.

    ``call`` is synchronous: it schedules ``call_tool`` on the loop and waits. The client
    context is entered and left by the loop's own task, as anyio requires.
    """

    def __init__(self, params: Any, read_timeout_s: float = CALL_TIMEOUT_S) -> None:
        self.params = params
        self.read_timeout_s = read_timeout_s
        self.client: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="mcp-session", daemon=True)

    def start(self) -> McpSession:
        self._thread.start()
        if not self._ready.wait(120):
            raise RuntimeError("the MCP session did not initialise within 120 s")
        if self._error is not None:
            raise RuntimeError(f"the MCP session failed to start: {self._error!r}")
        return self

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        from mcp import Client

        self.loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            async with Client(self.params, read_timeout_seconds=self.read_timeout_s) as client:
                self.client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the starting thread
            self._error = exc
            self._ready.set()

    def _submit(self, coro: Any, timeout: float) -> Any:
        assert self.loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def call(
        self,
        name: str,
        args: dict[str, Any],
        timeout: float = CALL_TIMEOUT_S,
        progress: Callable[..., Any] | None = None,
    ) -> Any:
        return self._submit(self.client.call_tool(name, args, progress_callback=progress), timeout)

    def read_resource(self, uri: str, timeout: float = 60.0) -> Any:
        return self._submit(self.client.read_resource(uri), timeout)

    def one_shot(self, name: str, args: dict[str, Any], timeout: float = 120.0) -> Any:
        """A call through a fresh bridge process that exits afterwards (review 22's
        one-shot clients)."""

        async def run() -> Any:
            from mcp import Client

            async with Client(self.params, read_timeout_seconds=60) as client:
                return await client.call_tool(name, args)

        return self._submit(run(), timeout)

    def close(self) -> None:
        if self.loop is not None and self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(60)


# -- the recorder -------------------------------------------------------------------------


@dataclass
class Call:
    tool: str
    args_bytes: int
    text_bytes: int
    image_count: int
    image_bytes: int
    elapsed_s: float
    is_error: bool
    expected_error: bool = False
    one_shot: bool = False
    code: str | None = None


@dataclass
class Result:
    """A tool result: ``data`` is the JSON of its text block."""

    is_error: bool
    data: dict[str, Any]
    images: int
    raw: Any

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class Recorder:
    session: McpSession
    name: str
    work: Path
    normalise: list[str]
    calls: list[Call] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)
    first_image_s: float | None = None
    notes: list[str] = field(default_factory=list)
    finished: dict[str, Any] | None = None
    session_config: Any = None
    """The pytest config (for ``--update-budgets``)."""
    budgets: Path = BUDGETS
    progress: list[Any] = field(default_factory=list)
    """``(progress, total, message)`` notifications received by calls made with
    ``progress=True``."""

    # -- calling ------------------------------------------------------------------------

    def _text_bytes(self, text: str) -> int:
        for prefix in self.normalise:
            text = text.replace(prefix, "<tmp>")
        return len(text.encode("utf-8"))

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        expect_error: bool = False,
        one_shot: bool = False,
        timeout: float = CALL_TIMEOUT_S,
        progress: bool = False,
    ) -> Result:
        args = args or {}
        t0 = time.perf_counter()
        if one_shot:
            raw = self.session.one_shot(tool, args, timeout=timeout)
        else:
            raw = self.session.call(
                tool, args, timeout=timeout, progress=self._on_progress if progress else None
            )
        elapsed = time.perf_counter() - t0
        text = "".join(getattr(c, "text", "") or "" for c in raw.content)
        images = [c for c in raw.content if getattr(c, "type", "") == "image"]
        image_bytes = sum(len(getattr(c, "data", "") or "") for c in images)
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"_text": text}
        if not isinstance(data, dict):
            data = {"_value": data}
        is_error = bool(raw.is_error)
        self.calls.append(
            Call(
                tool=tool,
                args_bytes=len(json.dumps(args, separators=(",", ":")).encode("utf-8")),
                text_bytes=self._text_bytes(text),
                image_count=len(images),
                image_bytes=image_bytes,
                elapsed_s=elapsed,
                is_error=is_error,
                expected_error=expect_error and is_error,
                one_shot=one_shot,
                code=data.get("code") if is_error else None,
            )
        )
        if images and self.first_image_s is None:
            self.first_image_s = time.perf_counter() - self.started
        return Result(is_error, data, len(images), raw)

    async def _on_progress(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress.append((progress, total, message))

    def ok(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> Result:
        result = self.call(tool, args, **kw)
        assert not result.is_error, f"{tool} {_short(args)} failed: {_short(result.data)}"
        return result

    def error(
        self, tool: str, args: dict[str, Any] | None = None, code: str | None = None, **kw: Any
    ) -> Result:
        result = self.call(tool, args, expect_error=True, **kw)
        assert result.is_error, f"{tool} {_short(args)} unexpectedly succeeded: {_short(result)}"
        assert result.get("code"), result.data
        if code is not None:
            assert result["code"] == code, f"{tool}: expected {code}, got {_short(result.data)}"
        return result

    def read_resource(self, uri: str) -> str:
        """Read a resource and record it as a call named ``resource:<uri>``."""
        t0 = time.perf_counter()
        raw = self.session.read_resource(uri)
        text = "".join(getattr(c, "text", "") or "" for c in raw.contents)
        self.calls.append(
            Call(
                f"resource:{uri}", 0, self._text_bytes(text), 0, 0, time.perf_counter() - t0, False
            )
        )
        return text

    def wait_job(self, job_id: str, timeout_s: float = 240.0) -> Result:
        """Wait for a job to leave ``running``, then record one ``job status``.

        The polls before that are not recorded, so a workload's call count does not depend
        on how fast the machine runs the job (an agent's poll count would).
        """
        deadline = time.monotonic() + timeout_s
        while True:
            raw = self.session.call("job", {"action": "status", "job_id": job_id})
            state = json.loads(raw.content[0].text).get("state")
            if state != "running":
                break
            assert time.monotonic() < deadline, f"job {job_id} still running after {timeout_s} s"
            time.sleep(0.25)
        return self.ok("job", {"action": "status", "job_id": job_id})

    def path(self, *parts: str) -> str:
        """A path under this workload's work dir, with forward slashes (for parms)."""
        return fwd(self.work.joinpath(*parts))

    # -- totals -------------------------------------------------------------------------

    @property
    def unexpected_errors(self) -> list[Call]:
        return [c for c in self.calls if c.is_error and not c.expected_error]

    def totals(self) -> dict[str, Any]:
        wall = time.perf_counter() - self.started
        return {
            "calls": len(self.calls),
            "text_bytes": sum(c.text_bytes for c in self.calls),
            "max_call_bytes": max((c.text_bytes for c in self.calls), default=0),
            "wall_s": round(wall, 1),
            "first_image_s": None if self.first_image_s is None else round(self.first_image_s, 1),
            "images": sum(c.image_count for c in self.calls),
            "image_bytes": sum(c.image_bytes for c in self.calls),
            "args_bytes": sum(c.args_bytes for c in self.calls),
            "errors": sum(c.is_error for c in self.calls),
            "unexpected_errors": len(self.unexpected_errors),
            "tool_s": round(sum(c.elapsed_s for c in self.calls), 1),
        }

    def report(self) -> str:
        rows = [
            f"  {i + 1:3d}. {c.tool:<18} {c.text_bytes:7d} B {c.elapsed_s * 1000:8.0f} ms"
            + (f" img x{c.image_count}" if c.image_count else "")
            + (f" isError {c.code}" if c.is_error else "")
            + (" (expected)" if c.expected_error else "")
            + (" one-shot" if c.one_shot else "")
            for i, c in enumerate(self.calls)
        ]
        return "\n".join(rows)

    def per_tool(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            row = out.setdefault(c.tool, {"calls": 0, "text_bytes": 0, "max_bytes": 0, "s": 0.0})
            row["calls"] += 1
            row["text_bytes"] += c.text_bytes
            row["max_bytes"] = max(row["max_bytes"], c.text_bytes)
            row["s"] = round(row["s"] + c.elapsed_s, 3)
        return out

    def finish(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Total the workload, record it, and check it against ``budgets.json``."""
        totals = self.totals()
        if extra:
            totals.update(extra)
        self.finished = totals
        print(f"\n[{self.name}] {json.dumps(totals)}")
        assert not self.unexpected_errors, "unexpected errors:\n" + self.report()
        config = self.session_config
        if config.getoption("--update-budgets"):
            _update_budget(self.name, totals, self.budgets)
            return totals
        budgets = _read_json(self.budgets)
        budget = budgets.get("workloads", {}).get(self.name)
        if budget is None:
            pytest.fail(f"no budget for {self.name} in {self.budgets}; run with --update-budgets")
        over = [
            f"{key} {totals[key]} > {budget[key]} x {TOLERANCE} = {_limit(key, budget[key]):.1f}"
            for key in BUDGET_KEYS
            if key in budget and totals[key] > _limit(key, budget[key])
        ]
        assert not over, f"{self.name} over budget: " + "; ".join(over) + "\n" + self.report()
        return totals


def _short(value: Any, limit: int = 1500) -> str:
    text = json.dumps(value.data if isinstance(value, Result) else value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _update_budget(name: str, totals: dict[str, Any], path: Path = BUDGETS) -> None:
    data = _read_json(path) or {}
    data.setdefault(
        "about",
        "Per-workload budgets for tests/workloads (spec-2.0 section 5.2). A run fails when a total "
        "exceeds its budget by more than 15 %. Rewrite with --update-budgets.",
    )
    data.setdefault("workloads", {})
    data["workloads"][name] = {
        "calls": totals["calls"],
        "text_bytes": totals["text_bytes"],
        "max_call_bytes": totals["max_call_bytes"],
        "wall_s": math.ceil(totals["wall_s"] * 10) / 10,
    }
    data["workloads"] = dict(sorted(data["workloads"].items()))
    _write_json(path, data)


def _record_last_run(name: str, rec: Recorder, outcome: str, path: Path = LAST_RUN) -> None:
    data = _read_json(path)
    data.setdefault("workloads", {})
    totals = rec.finished or rec.totals()
    data["workloads"][name] = {
        "outcome": outcome,
        **totals,
        "per_tool": rec.per_tool(),
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write_json(path, data)


# -- fixtures -----------------------------------------------------------------------------


@dataclass
class Host:
    proc: subprocess.Popen
    pid: int
    root: Path
    state: Path
    work: Path
    env: dict[str, str]


def _stop_host(host: Host) -> None:
    """Stop the hython this fixture started: over HTTP, else by its pid."""
    entry = host.state / "instances" / f"{host.pid}.json"
    try:
        from hocuspocus.bridge.client import HostClient

        if entry.is_file() and host.proc.poll() is None:
            info = json.loads(entry.read_text(encoding="utf-8"))
            HostClient(info["port"], info["token"]).shutdown()
        host.proc.wait(timeout=30)
    except Exception:  # noqa: BLE001 - fall back to a hard stop of *our* process
        host.proc.kill()
        host.proc.wait(timeout=30)


@pytest.fixture(scope="session")
def wl_host(hython: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Host]:
    with start_host(hython, tmp_path_factory.mktemp("wl"), PROFILE_1X) as host:
        yield host


@contextmanager
def start_host(hython: Path, root: Path, profile: str) -> Iterator[Host]:
    """A headless host under ``root``; it and its bridges serve ``profile``."""
    state, prefs, cwd, work, tmp = (root / d for d in ("state", "prefs", "cwd", "work", "tmp"))
    for d in (state, cwd, work, tmp, prefs / "houdini22.0"):
        d.mkdir(parents=True, exist_ok=True)
    # Houdini expands __HVER__, so the toml lives in the expanded directory (CONTRIBUTING).
    toml = prefs / "houdini22.0" / "hocuspocus.toml"
    toml.write_text(f'profile = "{profile}"\n', encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "HOCUSPOCUS_STATE_DIR": str(state),
            "HOCUSPOCUS_WORK_DIR": str(work),
            "HOCUSPOCUS_HFS": str(hython.parent.parent),
            "HOCUSPOCUS_PROFILE": profile,
            # Houdini ignores HOUDINI_USER_PREF_DIR without the __HVER__ token.
            "HOUDINI_USER_PREF_DIR": fwd(prefs / "houdini__HVER__"),
            "PYTHONDONTWRITEBYTECODE": "1",
            # Capture children and Houdini's own temp files stay under this session's root.
            "TEMP": str(tmp),
            "TMP": str(tmp),
        }
    )
    env.pop("HOCUSPOCUS_LAUNCHED_BY", None)
    log_path = root / "hython.log"
    log = open(log_path, "wb")  # noqa: SIM115 - closed in teardown
    proc = subprocess.Popen(
        [str(hython), "-m", "hocuspocus.host", "--port", "0", "--state-dir", str(state)],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    host = Host(proc, proc.pid, root, state, work, env)
    entry = state / "instances" / f"{proc.pid}.json"
    deadline = time.monotonic() + REGISTER_TIMEOUT_S
    try:
        while not entry.is_file():
            if proc.poll() is not None:
                log.flush()
                pytest.fail(
                    f"hython exited ({proc.returncode}):\n" + log_path.read_text(errors="replace")
                )
            if time.monotonic() > deadline:
                pytest.fail("headless host did not register in time")
            time.sleep(0.25)
        assert json.loads(entry.read_text(encoding="utf-8"))["port"] != 37219
        yield host
    finally:
        _stop_host(host)
        log.close()
        _kill_launched(state, keep=set())


def _kill_launched(state: Path, keep: set[int]) -> None:
    """Stop Houdinis a workload launched through the bridge (they register in our state
    dir) that are still running."""
    from hocuspocus.bridge.client import HostClient

    for entry in (state / "instances").glob("*.json"):
        try:
            info = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if info.get("pid") in keep:
            continue
        try:
            HostClient(info["port"], info["token"]).shutdown()
        except Exception:  # noqa: BLE001 - fall back to killing that pid
            kill_pid(int(info["pid"]))


def kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        os.kill(pid, signal.SIGKILL)


@pytest.fixture(scope="session")
def wl_session(wl_host: Host) -> Iterator[McpSession]:
    with open_session(wl_host) as session:
        yield session


@contextmanager
def open_session(host: Host) -> Iterator[McpSession]:
    """A persistent MCP session through a stdio bridge, pinned to ``host``."""
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hocuspocus.bridge"],
        env=host.env,
        cwd=str(host.root / "cwd"),
    )
    session = McpSession(params).start()
    try:
        pinned = session.call("houdini_connect", {"pid": host.pid})
        assert not pinned.is_error, pinned.content
        yield session
    finally:
        session.close()


def _housekeeping(session: McpSession, host: Host) -> None:
    """Between workloads: re-pin the session host, cancel its running jobs, clear the
    scene. None of this is recorded."""
    session.call("houdini_connect", {"pid": host.pid})
    listed = session.call("job", {"action": "list"})
    if not listed.is_error:
        jobs = json.loads(listed.content[0].text).get("jobs", [])
        for job in jobs:
            if job.get("state") == "running":
                session.call("job", {"action": "cancel", "job_id": job["job_id"]})
    cleared = session.call("hip_new", {"on_unsaved": "discard"})
    assert not cleared.is_error, cleared.content
    session.call("time", {"frame": 1})


@pytest.fixture
def workload(
    request: pytest.FixtureRequest, wl_session: McpSession, wl_host: Host
) -> Iterator[Recorder]:
    with recording(request, wl_session, wl_host) as rec:
        yield rec


@contextmanager
def recording(
    request: pytest.FixtureRequest,
    session: McpSession,
    host: Host,
    *,
    factory: type[Recorder] = Recorder,
    budgets: Path = BUDGETS,
    last_run: Path = LAST_RUN,
) -> Iterator[Recorder]:
    """One workload's recorder: a clean scene before and after, its totals in ``last_run``."""
    name = request.node.name.removeprefix("test_")
    work = host.work / name
    work.mkdir(parents=True, exist_ok=True)
    _housekeeping(session, host)
    prefixes = {str(host.root), fwd(host.root)}
    prefixes |= {p.replace("\\", "\\\\") for p in prefixes}  # as JSON escapes it
    rec = factory(
        session=session, name=name, work=work, normalise=sorted(prefixes, key=len, reverse=True)
    )
    rec.session_config = request.config
    rec.budgets = budgets
    outcome = "error"
    try:
        yield rec
        outcome = "passed"
    finally:
        if rec.finished is not None or rec.calls:
            report = getattr(request.node, "rep_call", None)
            if report is not None:
                outcome = report.outcome
            _record_last_run(name, rec, outcome, last_run)
        try:
            _housekeeping(session, host)
        finally:
            _kill_launched(host.state, keep={host.pid})
            shutil.rmtree(work, ignore_errors=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.rep_call = report  # type: ignore[attr-defined]
