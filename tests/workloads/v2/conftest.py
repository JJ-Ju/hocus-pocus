"""The 2.0 workloads tier: the five workloads of ``tests/workloads`` on the 2.0 tools.

Same harness as the 1.4 tier (``tests/workloads/conftest.py``: one headless host, one
persistent ``mcp`` session through the stdio bridge, the :class:`Recorder`), with its own
host serving the 2.0 profile (:data:`PROFILE`), its own ``budgets.json`` (each total at most
115 % of its budget) and ``last_run.json``.

Each workload uses only the 2.0 surface: ``edit`` (one transaction per logical step, ``$id``
chains), ``inspect`` and ``search`` for reads, ``houdini://`` resources with
``_meta["If-None-Match"]`` where a read repeats (:meth:`RecorderV2.read`; a not-modified
answer is a call with no bytes), ``look``, ``cook``/``render``/``job`` (``on`` to address a
worker, a progress token so a job's call waits for its end), ``houdini_connect {role}``.

The 2.0 exit check (spec-2.0 §7, M4): each workload's ``calls`` and ``text_bytes`` must be
below its 1.4 budget (``tests/workloads/budgets.json``) by :data:`MARGINS`, the margins the
reviews predicted. A workload that misses one fails with the per-tool table, so the fix can
be targeted; the margins are not relaxed. The end of the run prints the 1.4/2.0 comparison.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


def _tier_1x() -> Any:
    """The 1.4 tier's conftest, loaded under its own name (pytest imports every conftest as
    ``conftest`` and drops the previous one from ``sys.modules``)."""
    path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("hp_workloads_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _tier_1x()
Recorder = harness.Recorder

HERE = Path(__file__).resolve().parent
BUDGETS = HERE / "budgets.json"
LAST_RUN = HERE / "last_run.json"
BUDGETS_1X = harness.BUDGETS


def _profile() -> str:
    """``full`` once it lists the 2.0 tools (spec-2.0 M3), before that ``v2`` (M1-M2)."""
    from hocuspocus.tools import catalog

    names = {spec.name for spec in catalog.for_profile("full")}
    return "full" if {"edit", "inspect", "search", "look"} <= names else "v2"


PROFILE = _profile()
TOOLS_2X = frozenset(
    {
        "houdini_status", "houdini_connect", "hip_new", "hip_open", "hip_save", "hip_merge",
        "inspect", "search", "edit", "node_create", "parm_set", "cook", "render", "look",
        "houdini_python", "job", "undo", "time", "hda", "pdg", "events",
    }
)  # fmt: skip
"""The 2.0 tool surface (spec-2.0 §2); a v2 workload calling anything else fails."""

MARGINS: dict[str, tuple[float, float]] = {
    "city_build": (0.25, 0.20),
    "scorecard_twelve": (0.0, 0.20),
    "soak_200": (0.0, 0.20),
    "fx_cache": (0.15, 0.15),
    "vellum_usd": (0.15, 0.15),
}
"""Per workload, the fraction by which 2.0's ``calls`` and ``text_bytes`` must be below the
1.4 budget (spec-2.0 §7, "M4 margins"): the margins reviews 12, 20, 21, 22 and 24
predicted, except calls for the scorecard and the soak, enumerations of fixed tasks with
one call per task, where 2.0 must only not exceed 1.4 (0 %)."""

RESULTS: dict[str, dict[str, Any]] = {}
"""This run's v2 totals and margin verdicts, for the comparison table."""


class RecorderV2(Recorder):
    """The recorder, plus resource reads with ETags and the 2.0 exit check."""

    etags: dict[str, str]

    def call(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> Any:
        assert tool in TOOLS_2X, f"{tool} is not a 2.0 tool"
        result = super().call(tool, args, **kw)
        dump = os.environ.get("HP_WORKLOADS_DUMP")
        if dump:  # debugging: every call's arguments and text, one JSON file per call
            out = Path(dump) / self.name
            out.mkdir(parents=True, exist_ok=True)
            row = {"tool": tool, "args": args, "text": result.data}
            text = json.dumps(row, indent=1, default=str)
            (out / f"{len(self.calls):03d}_{tool}.json").write_text(text, encoding="utf-8")
        return result

    def read(self, uri: str, *, revalidate: bool = True) -> tuple[Any, dict[str, Any]]:
        """``resources/read`` of ``uri``: ``(json, or Markdown text, or None, _meta)``.

        With ``revalidate`` the etag of the last read of this URI goes out as
        ``_meta["If-None-Match"]``; an unchanged resource answers ``not_modified`` with no
        contents and ``None`` comes back. Recorded as ``resource:<scheme://kind>``.
        """
        if not hasattr(self, "etags"):
            self.etags = {}
        meta = {"If-None-Match": self.etags[uri]} if revalidate and uri in self.etags else None
        t0 = harness.time.perf_counter()
        raw = self.session._submit(
            self.session.client.read_resource(uri, meta=meta, cache_mode="bypass"), 60.0
        )
        elapsed = harness.time.perf_counter() - t0
        text = "".join(getattr(c, "text", "") or "" for c in raw.contents)
        got = dict(raw.meta or {})
        if got.get("etag"):
            self.etags[uri] = got["etag"]
        kind = uri.split("?", 1)[0]
        kind = "/".join(kind.split("/")[:3])
        self.calls.append(
            harness.Call(f"resource:{kind}", 0, self._text_bytes(text), 0, 0, elapsed, False)
        )
        if not text:
            return None, got
        try:
            return json.loads(text), got
        except json.JSONDecodeError:  # hocuspocus://guide and tools are Markdown
            return text, got

    def finish(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            totals = super().finish(extra)
        finally:
            if self.finished is not None:
                verdict = margin_verdict(self.name, self.finished)
                RESULTS[self.name] = {**self.finished, **verdict}
        missed = RESULTS[self.name]["missed"]
        assert not missed, (
            f"{self.name} misses the 2.0 exit margin (spec-2.0 §7 M4): "
            + "; ".join(missed)
            + "\nper tool:\n"
            + per_tool_table(self)
            + "\ncalls:\n"
            + self.report()
        )
        return totals


def margin_verdict(name: str, totals: dict[str, Any]) -> dict[str, Any]:
    budget = harness._read_json(BUDGETS_1X).get("workloads", {}).get(name, {})
    calls_margin, bytes_margin = MARGINS[name]
    missed = []
    for key, margin in (("calls", calls_margin), ("text_bytes", bytes_margin)):
        if key not in budget:
            missed.append(f"no 1.4 budget for {key}")
            continue
        limit = budget[key] * (1 - margin)
        if totals[key] > limit:
            cut = 1 - totals[key] / budget[key]
            missed.append(
                f"{key} {totals[key]} vs 1.4 {budget[key]}: {cut:+.0%} below, "
                f"needs {margin:.0%} (<= {limit:.0f})"
            )
    return {"budget_1x": budget, "missed": missed}


def per_tool_table(rec: Recorder) -> str:
    rows = sorted(rec.per_tool().items(), key=lambda kv: -kv[1]["text_bytes"])
    lines = [f"  {'tool':<26} {'calls':>5} {'bytes':>8} {'max':>7}"]
    lines += [
        f"  {tool:<26} {row['calls']:>5} {row['text_bytes']:>8} {row['max_bytes']:>7}"
        for tool, row in rows
    ]
    return "\n".join(lines)


# -- fixtures (override the 1.4 tier's for tests under v2/) ---------------------------------


@pytest.fixture(scope="session")
def wl_host(hython: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    with harness.start_host(hython, tmp_path_factory.mktemp("wl2"), PROFILE) as host:
        yield host


@pytest.fixture(scope="session")
def wl_session(wl_host: Any) -> Iterator[Any]:
    with harness.open_session(wl_host) as session:
        yield session


@pytest.fixture
def workload(request: pytest.FixtureRequest, wl_session: Any, wl_host: Any) -> Iterator[Any]:
    with harness.recording(
        request, wl_session, wl_host, factory=RecorderV2, budgets=BUDGETS, last_run=LAST_RUN
    ) as rec:
        yield rec


# -- the comparison table -------------------------------------------------------------------


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not RESULTS:
        return
    tr = terminalreporter
    tr.section("workloads: 1.4 budget vs 2.0 (spec-2.0 §7 M4 margins)")
    tr.write_line(
        f"{'workload':<17} {'calls 1.4':>9} {'2.0':>5} {'cut':>5} {'need':>5}  "
        f"{'bytes 1.4':>9} {'2.0':>7} {'cut':>5} {'need':>5}  {'wall 1.4':>8} {'2.0':>6}  margin"
    )
    for name in sorted(RESULTS):
        r = RESULTS[name]
        b = r["budget_1x"]
        calls_margin, bytes_margin = MARGINS[name]
        tr.write_line(
            f"{name:<17} {b.get('calls', '-'):>9} {r['calls']:>5} {_cut(r, b, 'calls'):>5} "
            f"{calls_margin:>5.0%}  {b.get('text_bytes', '-'):>9} {r['text_bytes']:>7} "
            f"{_cut(r, b, 'text_bytes'):>5} {bytes_margin:>5.0%}  "
            f"{b.get('wall_s', '-'):>8} {r['wall_s']:>6}  "
            + ("met" if not r["missed"] else "MISSED: " + "; ".join(r["missed"]))
        )


def _cut(r: dict[str, Any], b: dict[str, Any], key: str) -> str:
    return f"{1 - r[key] / b[key]:+.0%}" if b.get(key) else "-"
