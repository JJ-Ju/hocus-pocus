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


class RecorderV2(Recorder):
    """The recorder, plus resource reads with ETags."""

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
