"""The MCP server (stdio) that fronts Houdini. See docs/BIBLE.md §3.3, §4.1, §4.8.

Built on the SDK's low-level :class:`mcp.server.Server` rather than ``MCPServer``: the tool
surface is *data* (names + raw JSON Schemas from :mod:`hocuspocus.tools.catalog`), and only
the low-level ``on_list_tools`` / ``on_call_tool`` handlers let us publish those schemas
verbatim, return ``structuredContent`` for arbitrary dicts, and own argument validation.
``MCPServer.add_tool`` derives schemas from Python signatures instead.
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
import re
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.shared.exceptions import MCPError

from ..tools import catalog, migration, profiles
from ..tools.catalog import ToolSpec
from ..tools.errors import ToolError
from ..version import __version__
from . import budget, routing
from . import instances as registry
from .client import OFFLINE_HINT, REINSTALL_HINT, HostClient
from .config import BridgeConfig
from .instructions import PROMPT_DEFAULTS, PROMPTS, guide_text, instructions_for, tools_text
from .launch import Launcher
from .ledger import Ledger, is_ledger_id
from .local_tools import LOCAL_TOOLS
from .validate import coerce_integers, shape_hint, validate

EXIT_GRACE_S = 1.5
"""After a lost response, how long to watch for the Houdini process to exit."""
OUTLINE_ARGS = {"root": "/", "format": "outline", "depth": 2}
"""What ``houdini://outline`` reads (review 11 B11)."""
MAX_STALE_ENTRIES = 5
"""How many stale registry entries one call may delete before giving up."""
LOAD_HEALTH_TIMEOUT_S = 2.0
"""``/health`` per candidate when a role picks the least busy instance."""
PROGRESS_INTERVAL_S = 0.5
"""How often the bridge polls the host for job progress while a call with a
``progressToken`` is in flight (BIBLE §7)."""

log = logging.getLogger(__name__)

SERVER_NAME = "hocuspocus"
MAX_TIMEOUT_S = 3600.0

_TRANSPORT_CODES = frozenset(
    {"houdini_offline", "houdini_busy", "delivery_unknown", "version_mismatch", "internal"}
)


KEEP_ALIVE_HINT = (
    "One-shot clients: keep one MCP session open for the whole job, or start Houdini "
    "outside the client with `hocuspocus launch` (it outlives every session) and attach "
    "with houdini_connect {pid}. houdini_connect {launch} starts a new one now."
)


def launcher_exited_error(record: dict[str, Any]) -> ToolError:
    """``houdini_offline`` for a Houdini an earlier bridge launched and that has exited."""
    pid, launcher = record.get("pid"), record.get("launched_by")
    if record.get("launcher_alive"):
        cause = f"was launched by another HocusPocus server (pid {launcher}) and has exited"
    else:
        cause = f"was launched by an earlier HocusPocus server (pid {launcher}) and exited with it"
    return ToolError(
        "houdini_offline",
        f"No Houdini is running: Houdini pid {pid} {cause}; its unsaved changes are lost.",
        hint=KEEP_ALIVE_HINT,
        retryable=False,
        detail={
            "pid": pid,
            "launched_by": launcher,
            "hip": record.get("hip") or None,
            "mode": record.get("mode"),
        },
    )


READ_ACTIONS: dict[str, frozenset[str]] = {
    "job": frozenset({"status", "result", "list"}),
    "undo": frozenset({"history"}),
    "hda": frozenset({"list"}),
    "pdg": frozenset({"status", "workitems"}),
}
"""Actions of ``scene=False`` tools that only read (BIBLE §4.1)."""
READ_WITHOUT: dict[str, tuple[str, ...]] = {
    "time": ("frame", "range", "fps"),
    "selection": ("paths",),
}
"""``scene=False`` tools that only read when none of these arguments is given."""


def mutates(spec: ToolSpec, args: dict[str, Any]) -> bool:
    """Whether a call may change a Houdini (its scene, files on disk, or work it runs).

    With several live instances and none pinned these calls refuse with
    ``ambiguous_instance`` (review 19 papercut 2); reads go to the preferred instance.
    ``viewport_capture`` and ``look`` count as reads: they leave no nodes, undo step or
    dirty flag."""
    if spec.read_only or spec.bridge_local or spec.name in ("viewport_capture", "look"):
        return False
    if spec.name in READ_ACTIONS:
        return args.get("action") not in READ_ACTIONS[spec.name]
    if spec.name in READ_WITHOUT:
        return any(args.get(key) is not None for key in READ_WITHOUT[spec.name])
    return True


JOB_ID_RE = re.compile(r"^(\d+)-[0-9A-Za-z]+$")
"""A host job id, ``<pid>-<hex>`` (1.3): the pid is the Houdini that runs the job."""
JOB_CACHE_SIZE = 200
"""How many job snapshots the bridge keeps, to report a job whose Houdini has exited."""
JOB_SNAPSHOT_KEYS = (
    "job_id", "tool", "label", "state", "progress", "current", "total", "message", "elapsed_s",
)  # fmt: skip


def reads_as(name: str, args: dict[str, Any]) -> str:
    """The 1.4 tool a call reads as for routing: ``inspect what: events`` is ``events``
    and ``inspect what: jobs`` is ``job`` (spec-2.0 §2.3), so they get the same cursor
    tagging and job-id routing; every other call is itself."""
    if name == "inspect":
        return {"events": "events", "jobs": "job"}.get(args.get("what"), name)
    return name


def job_owner(name: str, args: dict[str, Any]) -> int | None:
    """The pid a ``job`` call (or ``inspect what: jobs``) must go to, from its
    ``<pid>-<id>`` job id; else None."""
    if reads_as(name, args) != "job":
        return None
    match = JOB_ID_RE.match(str(args.get("job_id") or ""))
    return int(match.group(1)) if match else None


EVENTS_CURSOR_RE = re.compile(r"^(?:(\d+):)?(\d+)$")
"""An ``events`` cursor: ``<pid>:<seq>`` as the bridge returns it, or a bare ``<seq>``."""


def events_cursor(args: dict[str, Any]) -> tuple[int | None, int]:
    """``(pid or None, seq)`` from ``events`` ``since``; raises ``invalid_argument``."""
    since = args.get("since", 0)
    if isinstance(since, int) and not isinstance(since, bool) and since >= 0:
        return None, since
    match = EVENTS_CURSOR_RE.match(since) if isinstance(since, str) else None
    if match is None:
        raise ToolError(
            "invalid_argument",
            f"since must be the next_since of an earlier events read ('<pid>:<seq>') or a seq "
            f"number, not {since!r}.",
            hint="pass next_since back as since, or omit it to read from the start",
        )
    return (int(match.group(1)) if match.group(1) else None), int(match.group(2))


def tag_events(
    payload: dict[str, Any], inst: registry.Instance, foreign: tuple[int, str] | None
) -> dict[str, Any]:
    """``next_since`` as ``<pid>:<seq>``, and the reset note when ``since`` was a cursor
    of another Houdini (review 19 papercut 8; the host's seq restarts per process)."""
    out = dict(payload)
    if isinstance(out.get("next_since"), int):
        out["next_since"] = f"{inst.pid}:{out['next_since']}"
    if foreign is not None:
        pid, since = foreign
        out["reset"] = True
        out["note"] = (
            f"since {since} is a cursor of Houdini pid {pid}; this is pid {inst.pid}, whose "
            "seq numbers are its own, so its events are listed from the start."
        )
    return out


def unknown_job_error(job_id: str, pid: int) -> ToolError:
    """``job_not_found`` for a job id whose pid was never a Houdini this bridge knew."""
    return ToolError(
        "job_not_found",
        f"No job {job_id}: pid {pid} is not a Houdini this server knows (no registry entry "
        "or launch record), so no job of that id ran here.",
        hint="job {action: list, all: true} lists the live jobs of every Houdini; pass a "
        "job_id exactly as render, cook or pdg returned it.",
        retryable=False,
        detail={"job_id": job_id, "pid": pid},
    )


def instance_meta(inst: registry.Instance) -> dict[str, Any]:
    """``_meta.instance``: which Houdini answered (review 19 papercut 4)."""
    out: dict[str, Any] = {"pid": inst.pid, "label": inst.label}
    if inst.name:
        out["name"] = inst.name
    return out


def ambiguous_error(tool: str, sel: registry.Selection) -> ToolError:
    """``ambiguous_instance``: a call that changes a scene, several instances, no pin."""
    ordered = list(sel.candidates)
    calls = "; ".join(
        f'houdini_connect {{"pid": {inst.pid}}} pins {inst.describe()}' for inst in ordered
    )
    return ToolError(
        "ambiguous_instance",
        f"{len(ordered)} Houdini instances are running and none is pinned, so {tool} (which "
        "changes a scene) was not sent to a guess. Pin the one you mean, then repeat the call.",
        hint=calls,
        candidates=[inst.candidate() for inst in ordered],
        retryable=False,
    )


RESULT_CONTENT_MODES = ("both", "text", "structured")
"""``result_content`` (BIBLE §4.1): where a tool result's JSON goes.

* ``text`` (default): compact JSON in the text block, no ``structuredContent`` and so no
  ``outputSchema`` in ``tools/list`` (the spec requires structured results whenever an
  output schema is declared). Measured for 1.1: Claude Code shows the model only the text
  block, so a structured copy is pure wire overhead there.
* ``both``: the 1.0 shape, the same JSON in both places.
* ``structured``: ``structuredContent`` holds the data and the text block is a one-line
  summary (``<tool>: ok``, or ``<code>: <message>`` for an error), for clients that feed
  the model the structured content.

Images are unaffected: they are always image content blocks."""


def make_result(
    mode: str,
    tool: str,
    data: dict[str, Any],
    *,
    is_error: bool,
    meta: dict[str, Any] | None = None,
    images: Sequence[Any] = (),
) -> types.CallToolResult:
    """One ``CallToolResult`` shaped by ``result_content`` (:data:`RESULT_CONTENT_MODES`)."""
    if mode == "structured":
        if is_error:
            text = f"{data.get('code', 'internal')}: {data.get('message', '')}".rstrip(": ")
        else:
            text = f"{tool}: ok"
    else:
        text = budget.dumps(data)
    content: list[Any] = [types.TextContent(type="text", text=text)]
    content += [
        types.ImageContent(type="image", data=img.data, mime_type=img.mime_type) for img in images
    ]
    return types.CallToolResult(
        content=content,
        structured_content=None if mode == "text" else data,
        is_error=is_error,
        meta=meta or None,
    )


class Bridge:
    """Tool dispatch, instance selection and response shaping, independent of transport."""

    def __init__(
        self,
        config: BridgeConfig | None = None,
        *,
        tools: Sequence[ToolSpec] | None = None,
        client_factory: Callable[[int, str], HostClient] = HostClient,
        scan: Callable[[], list[registry.Instance]] | None = None,
        launcher: Launcher | None = None,
        launches: registry.LaunchLog | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        self.config = config or BridgeConfig.load()
        profile = profiles.normalize(self.config.profile) or profiles.DEFAULT_PROFILE
        if profile != self.config.profile:  # an alias (v2) or an unknown name
            self.config = dataclasses.replace(self.config, profile=profile)
        self.tools: tuple[ToolSpec, ...] = (
            tuple(tools) if tools is not None else catalog.for_profile(profile)
        )
        self._by_name = {spec.name: spec for spec in self.tools}
        self.client_factory = client_factory
        self.scan: Callable[[], list[registry.Instance]] = scan or (lambda: registry.scan())
        self.launches = launches or registry.LaunchLog()
        self.launcher = launcher or Launcher(
            self.config.hfs or None,
            scan=self.scan,
            launches=self.launches,
            on_launch=lambda pid, argv, work_dir, mode: self.ledger.record_launch(
                pid, argv, work_dir, mode
            ),
        )
        self._ledger = ledger
        self._reconciled = False
        self._memory_ledger = scan is not None
        """A bridge given a fake ``scan`` (tests) keeps its ledger in memory unless one is
        passed in, so it never writes to the real state dir."""
        self.preferred_pid: int | None = None
        """The pinned pid (``houdini_connect {pid}`` or ``{launch}``); BIBLE §3.6."""
        self.pinned: registry.Instance | None = None
        """The pinned instance as last seen, to name it once it has exited."""
        self.last_target: registry.Instance | None = None
        """The instance the last forwarded call went to, to name it if it exits."""
        self._previous_target: registry.Instance | None = None
        self.exit_grace_s = EXIT_GRACE_S
        self.detached = False
        self._verified: set[tuple[int, int, str]] = set()
        self._lock = threading.Lock()
        self.progress_interval_s = PROGRESS_INTERVAL_S
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        """job_id -> {pid, label, status}: the last snapshot of every job this bridge saw."""
        self._inflight: dict[str, registry.Instance] = {}
        """request_id -> the instance a call in flight was sent to (progress polling)."""
        self._seen_pids: set[int] = set()
        """Every Houdini pid this bridge has seen live in the registry."""

    # -- the ledger (spec-2.0 §3) -----------------------------------------------------------

    @property
    def ledger(self) -> Ledger:
        """The bridge ledger (``<state_dir>/ledger.sqlite``), opened on first use and then
        reconciled with the registry: remembered instances that are gone are marked dead."""
        if self._ledger is None:
            self._ledger = Ledger() if self._memory_ledger else Ledger.at()
        if not self._reconciled:
            self._reconciled = True
            try:
                live = self.scan()
            except Exception:  # noqa: BLE001 - reconciling is best effort
                log.debug("ledger reconcile scan failed", exc_info=True)
            else:
                self._ledger.observe(live, reconcile=True)
        return self._ledger

    @property
    def v2(self) -> bool:
        """Whether this bridge serves a 2.0 profile (roles, ``on``, ledger job ids,
        resources); ``compat_1x`` serves the 1.4 surface."""
        return profiles.is_2x(self.config.profile)

    def role_of(self, inst: registry.Instance) -> str:
        """``inst``'s role: as ``houdini_connect {role}`` set it, else editor for a GUI
        Houdini and worker for a headless one (spec-2.0 §3)."""
        return self.ledger.role_of(inst.pid, inst.ui)

    def load_of(self, inst: registry.Instance) -> tuple[int, bool] | None:
        """``(jobs_running, busy)`` from ``inst``'s ``/health``; None when it fails."""
        try:
            health = self.client_for(inst).health(timeout_s=LOAD_HEALTH_TIMEOUT_S)
        except ToolError:
            return None
        return int(health.get("jobs_running") or 0), bool(health.get("busy"))

    def instance_meta(self, inst: registry.Instance) -> dict[str, Any]:
        """``_meta.instance``; the v2 profile adds the instance's ``role``."""
        meta = instance_meta(inst)
        if self.v2:
            meta["role"] = self.role_of(inst)
        return meta

    def _note_live(self, live: list[registry.Instance]) -> None:
        """Remember the live instances (``job_not_found`` vs ``instance_lost``; ledger)."""
        self._seen_pids.update(inst.pid for inst in live)
        self.ledger.observe(live, reconcile=True)

    # -- instances -----------------------------------------------------------------------

    def pin(self, inst: registry.Instance | None) -> None:
        """Pin ``inst`` (or clear the pin): only an explicit ``houdini_connect`` calls this."""
        self.pinned = inst
        self.preferred_pid = inst.pid if inst is not None else None

    def lost_error(self, live: list[registry.Instance]) -> ToolError:
        """``instance_lost``: the pinned Houdini exited and the bridge will not pick another
        (review 19 papercut 1)."""
        pid = self.preferred_pid
        pinned = self.pinned if self.pinned is not None and self.pinned.pid == pid else None
        label = pinned.label if pinned is not None and pinned.label else "houdini"
        hip = pinned.hip if pinned is not None else ""
        ordered = registry.sort_preferred(live)
        choices = "; ".join(inst.describe() for inst in ordered) or "none is running"
        saved = hip and not hip.replace("\\", "/").endswith("/untitled.hip")
        launch = (
            f"houdini_connect {{launch: {{mode: 'headless', hip: '{hip}'}}}} reopens its last "
            "saved scene"
            if saved
            else "houdini_connect {launch} starts one"
        )
        return ToolError(
            "instance_lost",
            f"The pinned Houdini pid {pid} ({label}) has exited; changes made in it since its "
            f"last save are lost. Not switching to another Houdini on its own. Live: {choices}.",
            hint=f"houdini_connect {{pid}} pins one of the candidates, {launch}, "
            "houdini_connect {} returns to automatic selection",
            candidates=[inst.candidate() for inst in ordered],
            retryable=False,
            detail={"pid": pid, "label": label, "hip": hip or None},
        )

    def client_for(self, inst: registry.Instance) -> HostClient:
        client = self.client_factory(inst.port, inst.token)
        if isinstance(client, HostClient):
            # The host runs the 1.4 tools for a compat_1x bridge whatever its own profile.
            client.profile = self.config.profile
        return client

    def mark_verified(self, inst: registry.Instance) -> None:
        self._verified.add((inst.pid, inst.port, inst.token))

    def verify(self, inst: registry.Instance) -> dict[str, Any]:
        """``/health`` of ``inst`` with the identity check (review 10 section 1.4).

        A stale entry (port refused, or answered by another pid) is deleted from the
        registry and :class:`~hocuspocus.bridge.instances.StaleEntry` is raised, so the
        caller selects again."""
        try:
            health = registry.check_identity(inst, self.client_for(inst))
        except registry.StaleEntry as exc:
            self.forget(inst, str(exc))
            raise
        self.mark_verified(inst)
        return health

    def forget(self, inst: registry.Instance, reason: str) -> None:
        """Drop a stale registry entry and everything this bridge remembers about it."""
        log.info("forgetting stale instance: %s", reason)
        registry.forget(inst)
        key = (inst.pid, inst.port, inst.token)
        never_used = key not in self._verified
        self._verified.discard(key)
        if never_used and self.last_target is not None and self.last_target.pid == inst.pid:
            # A ghost entry this bridge never talked to: nothing "exited" from its view.
            self.last_target = self._previous_target

    def resolve(
        self, tool: str = "", args: dict[str, Any] | None = None
    ) -> tuple[registry.Instance, list[str]]:
        """Pick the target instance (BIBLE §3.3 rule 3) or raise ``houdini_offline``,
        ``instance_lost`` (a dead pin) or ``ambiguous_instance`` (``tool`` changes a scene,
        several instances run and none is pinned)."""
        inst, warnings, _ambiguous = self._resolve(tool, args)
        return inst, warnings

    def _resolve(
        self, tool: str = "", args: dict[str, Any] | None = None, target_pid: int | None = None
    ) -> tuple[registry.Instance, list[str], str | None]:
        """:meth:`resolve`, plus the ambiguity warning when the choice was a guess (a read
        on the preferred one of several unpinned instances). ``target_pid`` (a job's
        Houdini) bypasses the selection: that instance or ``instance_lost``."""
        if target_pid is not None:
            live = self.scan()
            owner = next((inst for inst in live if inst.pid == target_pid), None)
            self._note_live(live)
            if owner is None:
                job_id = str((args or {}).get("job_id"))
                if not self._known_pid(target_pid):
                    raise unknown_job_error(job_id, target_pid)
                raise self.job_lost_error(target_pid, job_id, live)
            self._check_hp(owner)
            return owner, [], None
        if self.detached:
            raise ToolError(
                "houdini_offline",
                "The bridge was disconnected with houdini_connect {disconnect: true}.",
                hint="call houdini_connect (with pid, launch, or no arguments) to attach again",
            )
        live = self.scan()
        self._note_live(live)
        sel = registry.select(live, self.preferred_pid)
        if sel.lost_pid is not None:
            raise self.lost_error(live)
        warnings = list(sel.warnings)
        exited = self._exited_target(live)
        if sel.instance is None:
            if exited is not None:
                raise self._exited_error(exited, "")
            orphans = self.launches.take_orphans()
            if orphans:
                raise launcher_exited_error(orphans[0])
            raise ToolError(
                "houdini_offline",
                "No live Houdini instance with HocusPocus is running.",
                hint=OFFLINE_HINT,
                retryable=False,  # repeating cannot work until something is launched
            )
        inst = sel.instance
        spec = self._by_name.get(tool)
        if sel.ambiguous and spec is not None and mutates(spec, args or {}):
            raise ambiguous_error(tool, sel)
        self._previous_target = self.last_target
        if exited is not None and exited.pid != inst.pid:
            warnings.append(
                f"The Houdini you were driving (pid {exited.pid}) has exited; changes made in it "
                f"since its last save are lost. Now using pid {inst.pid}."
            )
        self.last_target = inst
        self._check_hp(inst)
        return inst, warnings, (sel.warnings[0] if sel.ambiguous and sel.warnings else None)

    @staticmethod
    def _check_hp(inst: registry.Instance) -> None:
        if inst.hp != catalog.HP_RPC_VERSION:
            raise ToolError(
                "version_mismatch",
                f"Houdini pid {inst.pid} runs a host speaking hp/v{inst.hp}; this bridge speaks "
                f"hp/v{catalog.HP_RPC_VERSION}.",
                hint=REINSTALL_HINT,
            )

    # -- jobs (review 19 papercut 3) -------------------------------------------------------

    def _known_pid(self, pid: int) -> bool:
        """Whether ``pid`` was ever one of ours: seen live in the registry, the owner of a
        job this bridge saw, the pin or the last target, or in a launch record (review 21
        papercut 3: a made-up job id must not be reported as a Houdini that exited)."""
        if pid in self._seen_pids or any(job["pid"] == pid for job in self._jobs.values()):
            return True
        if any(inst is not None and inst.pid == pid for inst in (self.pinned, self.last_target)):
            return True
        return self.launches.has(pid) or self.ledger.knows_pid(pid)

    def job_lost_error(self, pid: int, job_id: str, live: list[registry.Instance]) -> ToolError:
        """``instance_lost`` for a job whose Houdini has exited, with its last known status."""
        cached = self._jobs.get(job_id)
        label = cached["label"] if cached else ""
        if not label and self.pinned is not None and self.pinned.pid == pid:
            label = self.pinned.label
        if not label:
            remembered = self.ledger.instance(pid)
            label = remembered["label"] if remembered else ""
        label = label or "houdini"
        # A restarted bridge has no cache: the ledger kept the last status it saw.
        last = cached["status"] if cached else self.ledger.last_status(job_id)
        message = (
            f"Job {job_id} ran in Houdini pid {pid} ({label}), which has exited; its jobs are gone."
        )
        if last:
            steps = (
                f", {last['current']}/{last['total']}"
                if last.get("current") is not None and last.get("total")
                else ""
            )
            note = f", {last['message']}" if last.get("message") else ""
            message += f" Last status seen: {last.get('state')}{steps}{note}."
        ordered = registry.sort_preferred(live)
        return ToolError(
            "instance_lost",
            message,
            hint="start the work again on a live Houdini (houdini_connect {pid} or {launch}, "
            "then repeat the render, cook or pdg call); outputs already written stay on disk",
            candidates=[inst.candidate() for inst in ordered],
            retryable=False,
            detail={"pid": pid, "label": label, "job_id": job_id, "last_status": last},
        )

    def _remember_jobs(self, inst: registry.Instance, payload: dict[str, Any]) -> None:
        rows = [payload] if isinstance(payload.get("job_id"), str) else []
        if isinstance(payload.get("jobs"), list):
            rows += [row for row in payload["jobs"] if isinstance(row, dict)]
        for row in rows:
            job_id = row.get("job_id")
            if not isinstance(job_id, str) or "state" not in row:
                continue
            snapshot = {key: row[key] for key in JOB_SNAPSHOT_KEYS if key in row}
            self._jobs[job_id] = {"pid": inst.pid, "label": inst.label, "status": snapshot}
            self._jobs.move_to_end(job_id)
            self.ledger.record_job(inst.pid, row)
            if row is payload and row.get("state") == "done" and "result" in row:
                self.ledger.store_result(job_id, row["result"])
        while len(self._jobs) > JOB_CACHE_SIZE:
            self._jobs.popitem(last=False)

    def _job_list_all(self) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """``job {action: list, all: true}``: every live instance's jobs, GUI first."""
        jobs: list[dict[str, Any]] = []
        instances: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for inst in registry.sort_preferred(self.scan()):
            try:
                if (inst.pid, inst.port, inst.token) not in self._verified:
                    self.verify(inst)
                ok, payload, _meta = self.client_for(inst).call(
                    "job", {"action": "list"}, self.config.default_timeout_s
                )
            except registry.StaleEntry:
                continue
            except ToolError as exc:
                errors.append({"pid": inst.pid, "code": exc.code, "message": exc.message})
                continue
            if not ok:
                errors.append(
                    {
                        "pid": inst.pid,
                        "code": payload.get("code"),
                        "message": payload.get("message"),
                    }
                )
                continue
            rows = [
                dict(row, pid=inst.pid)
                for row in payload.get("jobs") or []
                if isinstance(row, dict)
            ]
            self._remember_jobs(inst, {"jobs": rows})
            jobs += rows
            running = sum(1 for row in rows if row.get("state") == "running")
            instances.append(dict(instance_meta(inst), jobs=len(rows), running=running))
        out: dict[str, Any] = {"jobs": jobs, "instances": instances}
        if errors:
            out["errors"] = errors
        return True, out, {}

    def _exited_target(self, live: list[registry.Instance]) -> registry.Instance | None:
        last = self.last_target
        if last is None or any(inst.pid == last.pid for inst in live):
            return None
        return last

    @staticmethod
    def _exited_error(inst: registry.Instance, during: str) -> ToolError:
        hip = inst.hip or ""
        saved = hip and not hip.replace("\\", "/").endswith("/untitled.hip")
        launch = (
            f"houdini_connect {{launch: {{mode: 'headless', hip: '{hip}'}}}} reopens its last "
            "saved scene"
            if saved
            else "houdini_connect {launch: {mode}} starts a new Houdini"
        )
        return ToolError(
            "houdini_offline",
            f"The Houdini you were driving (pid {inst.pid}) exited{during}; changes made in it "
            "since its last save are lost.",
            hint=f"{launch}; repeating the call without that cannot work.",
            retryable=False,
            detail={"pid": inst.pid, "hip": hip or None},
        )

    def _wait_exit(self, inst: registry.Instance) -> bool:
        """True when ``inst`` has exited (checked for up to ``exit_grace_s``)."""
        deadline = time.monotonic() + self.exit_grace_s
        while True:
            if not any(live.pid == inst.pid for live in self.scan()):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    # -- on and ledger job ids (spec-2.0 §2.5, §3) -------------------------------------------

    def _host_job_id(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """``args`` with a ledger job id (``j7f3a9``) replaced by the host's ``<pid>-<id>``,
        and that ledger id; ``job_not_found`` when the ledger has no such job."""
        job_id = args.get("job_id")
        if reads_as(name, args) != "job" or not is_ledger_id(job_id):
            return args, None
        mapped = self.ledger.to_host(job_id)
        if mapped is None:
            raise ToolError(
                "job_not_found",
                f"No job {job_id}: this server's ledger has no job with that id.",
                hint="job {action: list, all: true} lists the live jobs of every Houdini; pass a "
                "job_id exactly as render, cook or pdg returned it.",
                retryable=False,
                detail={"job_id": job_id},
            )
        return dict(args, job_id=mapped[1]), job_id

    def _remembered(self, target: routing.Target) -> dict[str, Any] | None:
        """The ledger's row for an ``on`` pid or name that is not live (to name it)."""
        if target.kind == "pid":
            return self.ledger.instance(int(target.value))
        if target.kind == "name":
            return self.ledger.find_name(str(target.value))
        return None

    def _route(
        self,
        name: str,
        args: dict[str, Any],
        target_pid: int | None,
        on: routing.Target | None,
    ) -> tuple[registry.Instance, list[str], str | None]:
        """:meth:`_resolve`, or for ``on`` the instance it names, whatever is pinned or
        selected: no ambiguity refusal (the target is explicit) and the pin stays."""
        if on is None:
            return self._resolve(name, args, target_pid)
        live = self.scan()
        self._note_live(live)
        inst = routing.pick(
            on,
            live,
            role_of=self.role_of,
            load=self.load_of,
            remembered=self._remembered,
            tool=name,
        )
        self._check_hp(inst)
        return inst, [], None

    def _ledger_result(self, job_id: str, exc: ToolError) -> dict[str, Any] | None:
        """``job result`` for a finished job whose Houdini has exited: the result the
        ledger kept, if it fetched one before (spec-2.0 §3)."""
        row = self.ledger.job(job_id)
        if row is None or row["state"] != "done" or not row["has_result"]:
            return None
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return {
            **row["status"],
            "result": self.ledger.result(job_id),
            "note": f"Houdini pid {detail.get('pid')} has exited; this is the result the "
            "bridge ledger kept.",
        }

    def forward(
        self, name: str, args: dict[str, Any], request_id: str | None = None
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """Send a call to its Houdini: :meth:`_forward`, plus ``on`` (v2: ``cook``,
        ``render``, ``job``, ``look``) and ledger job ids both ways (a ledger id is
        accepted in every profile; v2 results carry ledger ids instead of host ids)."""
        on = None
        if "on" in args and name in routing.ROUTABLE:
            on = routing.parse_on(args["on"])
            args = {key: value for key, value in args.items() if key != "on"}
        args, asked_as = self._host_job_id(name, args)
        try:
            ok, payload, meta = self._forward(name, args, request_id, on)
        except ToolError as exc:
            host_id = args.get("job_id")
            if exc.code == "instance_lost" and args.get("action") == "result" and host_id:
                kept = self._ledger_result(str(host_id), exc)
                if kept is not None:
                    ok, payload, meta = True, kept, {}
                    return ok, self._present_jobs(payload), meta
            if self.v2 and isinstance(host_id, str):
                ledger_id = asked_as or self.ledger.ledger_id(host_id)
                if ledger_id:
                    exc.message = exc.message.replace(host_id, ledger_id)
                    wrapped = routing.rewrite_job_ids({"detail": exc.detail}, self.ledger.ledger_id)
                    exc.detail = wrapped["detail"]
            raise
        return ok, self._present_jobs(payload), meta

    def _present_jobs(self, payload: dict[str, Any]) -> dict[str, Any]:
        """v2: the agent sees ledger job ids (opaque; the bridge knows the instance)."""
        if not self.v2:
            return payload
        return routing.rewrite_job_ids(payload, self.ledger.ledger_id)

    def _forward(
        self,
        name: str,
        args: dict[str, Any],
        request_id: str | None = None,
        on: routing.Target | None = None,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        request_id = request_id or uuid.uuid4().hex
        if name == "job":
            if args.get("all") and args.get("action") == "list":
                return self._job_list_all()
            args = {key: value for key, value in args.items() if key != "all"}
        target_pid = job_owner(name, args)
        if target_pid is not None:
            on = None  # a job id names its Houdini
        cursor = events_cursor(args) if reads_as(name, args) == "events" else None
        stale: list[str] = []
        for _attempt in range(MAX_STALE_ENTRIES):
            inst, warnings, ambiguous = self._route(name, args, target_pid, on)
            client = self.client_for(inst)
            try:
                if (inst.pid, inst.port, inst.token) not in self._verified:
                    self.verify(inst)  # identity and version, before the first call
            except registry.StaleEntry as exc:
                stale.append(str(exc))
                continue  # deleted; select again
            self._inflight[request_id] = inst
            sent, foreign = args, None
            if cursor is not None:
                # The host keeps a bare seq; another Houdini's cursor reads from the start.
                cursor_pid, seq = cursor
                foreign = None if cursor_pid in (None, inst.pid) else (cursor_pid, args["since"])
                sent = dict(args, since=0 if foreign else seq)
            try:
                ok, payload, meta = client.call(
                    name,
                    sent,
                    self._timeout(args),
                    request_id,
                    max_response_bytes=self.config.max_response_bytes,
                )
            except ToolError as exc:
                if registry.is_stale_error(exc):
                    # Refused or rejected before it ran: the entry is stale, select again.
                    stale.append(exc.message)
                    self.forget(inst, exc.message)
                    continue
                # A connection reset usually means Houdini died mid-call: say so.
                if exc.code == "delivery_unknown" and self._wait_exit(inst):
                    error = self._exited_error(inst, f" while running {name}")
                    error.detail = {**error.detail, "transport": exc.message}
                    raise error from exc
                raise
            finally:
                self._inflight.pop(request_id, None)
            meta = dict(meta)
            meta.setdefault("pid", inst.pid)
            meta["instance"] = self.instance_meta(inst)
            if ok:
                self._remember_jobs(inst, payload)
                if cursor is not None:
                    payload = tag_events(payload, inst, foreign)
            if ambiguous and ok:
                # _meta is not shown to the model by every client: say it in the result too.
                payload = {
                    **payload,
                    "_instance": dict(instance_meta(inst), ui=inst.ui, warning=ambiguous),
                }
            if stale:
                warnings = [f"Removed stale registry entries: {'; '.join(stale)}.", *warnings]
            if warnings:
                meta["warnings"] = warnings
            return ok, payload, meta
        raise ToolError(
            "houdini_offline",
            "Every registered Houdini instance was stale (" + "; ".join(stale) + ").",
            hint=OFFLINE_HINT,
            detail={"stale": stale},
        )

    def progress_snapshot(
        self, name: str, args: dict[str, Any], request_id: str
    ) -> dict[str, Any] | None:
        """The job snapshot to report progress from while ``request_id`` is in flight:
        the job named by ``args.job_id`` (the ``job`` tool), else the newest job the call
        started on the host. ``None`` when there is none; never raises (best effort)."""
        inst = self._inflight.get(request_id)
        if inst is None:
            return None
        try:
            client = self.client_for(inst)
            job_id = args.get("job_id")
            if is_ledger_id(job_id):
                mapped = self.ledger.to_host(job_id)
                job_id = mapped[1] if mapped else None
            if isinstance(job_id, str) and job_id:
                ok, snapshot, _meta = client.job(job_id, timeout_s=5.0)
                snapshot = snapshot if ok else None
            else:
                jobs = client.call_jobs(request_id)
                snapshot = jobs[-1] if jobs else None
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("job_id"), str):
                return snapshot
            # The poller feeds the ledger; progress is reported from the ledger's view.
            self.ledger.record_job(inst.pid, snapshot)
            return self.ledger.last_status(snapshot["job_id"]) or snapshot
        except Exception:  # noqa: BLE001 - progress must never fail the call
            log.debug("progress poll for %s failed", name, exc_info=True)
            return None

    def _timeout(self, args: dict[str, Any]) -> float:
        for key in ("timeout_s", "wait_s"):
            value = args.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
                return min(float(value), MAX_TIMEOUT_S)
        return self.config.default_timeout_s

    # -- tools ---------------------------------------------------------------------------

    def list_tools(self) -> list[types.Tool]:
        out = []
        for spec in self.tools:
            description = spec.description
            if not spec.headless_ok and "(GUI only)" not in description:
                description = f"{description} (GUI only)"
            out.append(
                types.Tool(
                    name=spec.name,
                    description=description,
                    input_schema=spec.input_schema,
                    # No structuredContent in text mode, so no outputSchema either.
                    output_schema=(
                        spec.output_schema if self.config.result_content != "text" else None
                    ),
                    annotations=types.ToolAnnotations.model_validate(spec.wire_annotations()),
                )
            )
        return out

    def invoke(
        self, name: str, args: dict[str, Any], request_id: str | None = None
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """Run a tool without MCP wrapping: ``(ok, result_or_error, meta)``. Never raises ToolError."""
        spec = self._by_name.get(name)
        try:
            if spec is not None and spec.bridge_local:
                impl = LOCAL_TOOLS.get(name)
                if impl is None:
                    raise ToolError(
                        "internal", f"Bridge-local tool {name!r} has no implementation."
                    )
                with self._lock:
                    result = impl(self, args)
                connected = result.get("connected")
                meta = {}
                if isinstance(connected, dict) and isinstance(connected.get("pid"), int):
                    meta["instance"] = {
                        "pid": connected["pid"],
                        "label": connected.get("label", ""),
                    }
                return True, result, meta
            return self.forward(name, args, request_id)
        except ToolError as exc:
            return False, exc.to_dict(), {}
        except Exception as exc:  # noqa: BLE001 - every failure must be a tool result
            log.exception("tool %s failed in the bridge", name)
            return (
                False,
                ToolError(
                    "internal",
                    f"The bridge failed while handling {name}: {exc.__class__.__name__}: {exc}",
                    hint="this is a HocusPocus bug; the details are in the bridge's stderr log",
                    detail={"traceback": traceback.format_exc(limit=8)},
                ).to_dict(),
                {},
            )

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None, request_id: str | None = None
    ) -> types.CallToolResult:
        """Validate, dispatch and shape one ``tools/call``. Unknown tools raise ``MCPError``.
        ``request_id`` names the host call, so progress can be polled while it runs."""
        spec = self._by_name.get(name)
        if spec is None and self.v2 and migration.replacement(name):
            # A 1.4 name on a 2.0 profile: say what replaces it (spec-2.0 §8).
            error = migration.removed_error(name, self.config.profile)
            return make_result(self.config.result_content, name, error.to_dict(), is_error=True)
        if spec is None:
            close = difflib.get_close_matches(name, list(self._by_name), n=3, cutoff=0.6)
            message = f"Unknown tool: {name}." + (
                f" Did you mean {' or '.join(close)}?" if close else ""
            )
            data: dict[str, Any] = {"tools": sorted(self._by_name)}
            if close:
                data["candidates"] = close
            raise MCPError(types.INVALID_PARAMS, message, data)
        args = dict(arguments or {})
        violations = validate(args, spec.input_schema)
        if violations:
            # Review 21 papercut 1: a flat item of a batch tool gets the corrected call.
            wrapped = shape_hint(args, spec.input_schema)
            error = ToolError(
                "invalid_argument",
                f"{len(violations)} argument problem(s) for {name}: " + "; ".join(violations[:5]),
                hint=wrapped
                or f"fix the listed arguments; {name}'s inputSchema in tools/list is authoritative",
                detail={"violations": violations},
            )
            return make_result(self.config.result_content, name, error.to_dict(), is_error=True)
        # 50.0 validates as an integer; the host checks isinstance(..., int) (review 10).
        args = coerce_integers(args, spec.input_schema)
        ok, payload, meta = self.invoke(name, args, request_id)
        props = spec.input_schema.get("properties") or {}
        pageable = "cursor" in props or "since" in props  # events pages by since
        return self.shape(ok, payload, meta, args=args, pageable=pageable, tool=name)

    def shape(
        self,
        ok: bool,
        payload: dict[str, Any],
        meta: dict[str, Any],
        *,
        args: dict[str, Any] | None = None,
        pageable: bool = False,
        tool: str = "",
    ) -> types.CallToolResult:
        meta = dict(meta)
        mode = self.config.result_content
        if not ok:
            return make_result(mode, tool, payload, is_error=True, meta=meta)
        result, images = budget.extract_images(payload)
        result, cuts = budget.apply_budget(
            result, self.config.max_response_bytes, args, pageable=pageable, tool=tool
        )
        if cuts:
            meta[budget.TRUNCATION_META_KEY] = cuts
        return make_result(mode, tool, result, is_error=False, meta=meta, images=images)

    # -- resources -----------------------------------------------------------------------

    RESOURCES: tuple[tuple[str, str, str, str], ...] = (
        (
            "houdini://status",
            "status",
            "application/json",
            "Connected Houdini, hip file, frame and instances.",
        ),
        (
            "houdini://outline",
            "outline",
            "application/json",
            "The whole scene as a compact tree, two levels deep: each node's path, type, "
            "children count, display node and errors (network_describe format outline).",
        ),
        (
            "hocuspocus://guide",
            "guide",
            "text/markdown",
            "The HocusPocus operating manual: instructions and recipes (several Houdinis, "
            "Copernicus, spare parms).",
        ),
        (
            "hocuspocus://tools",
            "tools",
            "text/markdown",
            "The tool reference: every tool's arguments, notes and examples (large).",
        ),
    )
    TEMPLATES: tuple[tuple[str, str, str], ...] = (
        (
            "houdini://node/{path}",
            "node",
            "A node's info: type, flags, inputs, non-default parms, errors.",
        ),
        ("houdini://node/{path}/parms", "node_parms", "A node's non-default parameters."),
        (
            "houdini://node/{path}/geo",
            "node_geo",
            "Geometry summary of a SOP (or an OBJ's display SOP).",
        ),
        (
            "houdini://nodetype/{category}/{name}",
            "nodetype",
            "A node type's inputs and parameters.",
        ),
        ("houdini://job/{id}", "job", "Status of a long-running job (render, cook, PDG)."),
    )

    def route_resource(self, uri: str) -> tuple[str, dict[str, Any]] | None:
        """Map a resource URI to ``(tool, args)``; ``None`` for the static guide/unknown."""
        if uri == "houdini://status":
            return "houdini_status", {}
        if uri == "houdini://outline":
            return "network_describe", dict(OUTLINE_ARGS)
        if m := re.fullmatch(r"houdini://node/(.+)/parms", uri):
            return "node_info", {"paths": [_node_path(m.group(1))], "include": ["parms"]}
        if m := re.fullmatch(r"houdini://node/(.+)/geo", uri):
            return "geo_info", {"path": _node_path(m.group(1))}
        if m := re.fullmatch(r"houdini://node/(.+)", uri):
            return "node_info", {"paths": [_node_path(m.group(1))]}
        if m := re.fullmatch(r"houdini://nodetype/([^/]+)/(.+)", uri):
            return "node_type_info", {
                "type": f"{unquote(m.group(1))}/{unquote(m.group(2))}",
                "detail": "full",
            }
        if m := re.fullmatch(r"houdini://job/(.+)", uri):
            return "job", {"action": "status", "job_id": unquote(m.group(1))}
        return None

    def read_resource(self, uri: str) -> types.ReadResourceResult:
        if uri in ("hocuspocus://guide", "hocuspocus://tools"):
            text = (
                guide_text(self.config.profile)
                if uri == "hocuspocus://guide"
                else tools_text(self.tools)
            )
            return types.ReadResourceResult(
                contents=[types.TextResourceContents(uri=uri, text=text, mime_type="text/markdown")]
            )
        route = self.route_resource(uri)
        if route is None:
            raise MCPError(types.INVALID_PARAMS, f"Unknown resource: {uri}", {"uri": uri})
        name, args = route
        if name == "houdini_status":
            ok, payload, _ = True, LOCAL_TOOLS["houdini_status"](self, {}), {}
        else:
            ok, payload, _ = self.invoke(name, args)
        if not ok:
            code = (
                types.INTERNAL_ERROR
                if payload.get("code") in _TRANSPORT_CODES
                else types.INVALID_PARAMS
            )
            message = f"{payload.get('code')}: {payload.get('message')}"
            if payload.get("hint"):
                message += f" ({payload['hint']})"
            raise MCPError(code, message, payload)
        result, _images = budget.extract_images(payload)
        result, _cuts = budget.apply_budget(result, self.config.max_response_bytes)
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri, text=budget.dumps(result), mime_type="application/json"
                )
            ]
        )

    def list_resources(self) -> list[types.Resource]:
        return [
            types.Resource(uri=uri, name=name, mime_type=mime, description=desc)
            for uri, name, mime, desc in self.RESOURCES
        ]

    def list_resource_templates(self) -> list[types.ResourceTemplate]:
        return [
            types.ResourceTemplate(
                uri_template=tpl, name=name, mime_type="application/json", description=desc
            )
            for tpl, name, desc in self.TEMPLATES
        ]


def _node_path(raw: str) -> str:
    return "/" + unquote(raw).lstrip("/")


# -- prompts -----------------------------------------------------------------------------

PROMPTS_1X: dict[str, tuple[str, list[tuple[str, str, bool]], str]] = {
    "inspect_scene": (
        "Summarise the open Houdini scene: hip file, networks, problems.",
        [("root", "Network to start from (default /obj)", False)],
        "Inspect the Houdini scene under {root}. Call houdini_status first (hip file, frame, "
        "instance). If it warns that several Houdinis are running and none is pinned, ask the "
        "user which one to inspect, or pin the GUI session with houdini_connect {{pid}}, before "
        "going on. Read the resource houdini://outline (or call network_describe {{root: "
        '"{root}", format: "outline"}}) for the tree, then problems on {root}. Describe one '
        "network in more detail only when the summary needs it. Summarise: what each top-level "
        "network builds, the display/render nodes, and any errors or warnings with the node "
        "path and the likely cause. Do not modify anything.",
    ),
    "build_sop_chain": (
        "Build a SOP network from a plain-language description, then verify it.",
        [
            (
                "description",
                "What to build, e.g. 'a box scattered with 500 points copied spheres'",
                True,
            ),
            ("parent", "Parent network (default: create /obj/<name> geo)", False),
        ],
        "Build this in Houdini: {description}. Parent network: {parent}. Plan the SOP chain "
        "first, then create it with one node_create call (items with parms and inputs; set the "
        "display flag on the last node), or network_build for larger graphs. Use "
        "node_type_search when unsure of a type name. node_create already reports each "
        "node's errors and cook state: fix any errors it shows (cook only nodes it reports "
        "not_cooked), check geo_info on the display node (counts, bbox), and finish with "
        'viewport_capture {{"fit": "all"}} so the new geometry is framed. Report the final node '
        "paths.",
    ),
    "debug_red_node": (
        "Find out why a node has errors and fix it.",
        [("path", "Node path, e.g. /obj/geo1/attribwrangle1", True)],
        "The node {path} shows errors. Call node_info on it (include errors, parms, inputs). "
        "Read the error text, inspect upstream inputs and any expressions or file paths "
        "involved (problems on its parent when the cause may lie upstream), and explain the "
        "root cause. Propose the smallest fix; apply it with parm_set/node_connect only if it "
        "is unambiguous: the result re-cooks the node, so its errors confirm the fix. In a "
        "wrangle, ch() of a parm that does not exist is 0 without an error: add the parms it "
        "reads with node_edit spare_parms and set them.",
    ),
    "turntable_preview": (
        "Set up a turntable camera around an object and capture preview frames.",
        [
            ("path", "Object or SOP to orbit, e.g. /obj/geo1", True),
            ("frames", "Frame count for a full turn (default 48)", False),
        ],
        "Create a turntable preview of {path} over {frames} frames. Check houdini_status (ui: "
        "GUI or headless) and the resource houdini://outline: if {path}'s display flag is off, "
        "turn it on with node_edit (flags: {{display: true}}) and say so. Other displayed "
        "objects can hide it: turn their display flags off for the captures and back on "
        "afterwards, or tell the user which objects block the view. Read geo_info on {path} "
        "for its bounding box, then create a null at the bbox centre with ry keyed 0→360 over "
        "frames 1–{frames} and a camera parented to it, framed to the bbox, with resx/resy set "
        "(e.g. 1280×720). Do not change the playbar range in a GUI session: each capture takes "
        "frame. Capture viewport_capture {{camera, frame, resolution: [resx, resy]}} at the "
        "first frame and at a quarter turn, and show both images.",
    ),
}
"""The 1.4 prompts, in the 1.4 tools' words: ``compat_1x`` serves them (spec-2.0 §8); the
2.0 profiles serve :data:`hocuspocus.bridge.instructions.PROMPTS` (spec-2.0 §2.8)."""
PROMPT_DEFAULTS_1X = {"root": "/obj", "parent": "a new geo node under /obj", "frames": "48"}


def _prompts(
    profile: str | None,
) -> tuple[dict[str, tuple[str, list[tuple[str, str, bool]], str]], dict[str, str]]:
    """The prompt table and defaults for ``profile`` (``None``: a 2.0 profile)."""
    if profile is not None and not profiles.is_2x(profile):
        return PROMPTS_1X, PROMPT_DEFAULTS_1X
    return PROMPTS, PROMPT_DEFAULTS


def list_prompts(profile: str | None = None) -> list[types.Prompt]:
    table, _defaults = _prompts(profile)
    return [
        types.Prompt(
            name=name,
            description=desc,
            arguments=[types.PromptArgument(name=a, description=d, required=r) for a, d, r in args],
        )
        for name, (desc, args, _tpl) in table.items()
    ]


def get_prompt(
    name: str, arguments: dict[str, str] | None, profile: str | None = None
) -> types.GetPromptResult:
    table, defaults = _prompts(profile)
    if name not in table:
        raise MCPError(types.INVALID_PARAMS, f"Unknown prompt: {name}", {"prompts": sorted(table)})
    desc, spec, template = table[name]
    values = dict(defaults)
    values.update({k: v for k, v in (arguments or {}).items() if v})
    # Defaults fill optional arguments only: a required one must come from the caller.
    given = {k for k, v in (arguments or {}).items() if v}
    missing = [a for a, _d, required in spec if required and a not in given]
    if missing:
        raise MCPError(types.INVALID_PARAMS, f"Prompt {name} needs: {', '.join(missing)}")
    text = template.format(**{a: values.get(a, "") for a, _d, _r in spec})
    return types.GetPromptResult(
        description=desc,
        messages=[
            types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))
        ],
    )


# -- SDK wiring --------------------------------------------------------------------------


class ProgressTracker:
    """Turns job snapshots into MCP progress values that only ever increase.

    ``current``/``total`` (steps) are reported as they are; a bare ``progress`` fraction
    as ``progress`` of ``total: 1``. A snapshot that would not increase ``progress`` is
    skipped, as the spec requires."""

    def __init__(self) -> None:
        self.last: float | None = None

    def update(
        self, snapshot: dict[str, Any] | None
    ) -> tuple[float, float | None, str | None] | None:
        if not isinstance(snapshot, dict):
            return None
        current, total = snapshot.get("current"), snapshot.get("total")
        fraction = snapshot.get("progress")
        if _number(current) and _number(total) and total > 0:
            value, out_total = float(current), float(total)
        elif _number(fraction):
            value, out_total = float(fraction), 1.0
        else:
            return None
        if self.last is not None and value <= self.last:
            return None
        self.last = value
        message = snapshot.get("message")
        return value, out_total, message if isinstance(message, str) and message else None


def _wants_progress(ctx: Any) -> bool:
    """Whether the caller asked for progress: a ``_meta.progressToken`` on the request, or
    (the SDK's in-process transport) a progress callback on the request's channel."""
    meta = getattr(ctx, "meta", None)
    if isinstance(meta, dict) and any(
        meta.get(key) is not None for key in ("progressToken", "progress_token")
    ):
        return True
    channel = getattr(getattr(ctx, "session", None), "_request_outbound", None)
    for _ in range(3):  # the SDK wraps the request's dispatch context
        if channel is None:
            break
        if (
            getattr(channel, "_progress_token", None) is not None
            or getattr(channel, "_on_progress", None) is not None
        ):
            return True
        channel = getattr(channel, "_inner", None)
    return False


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


async def _call_with_progress(
    bridge: Bridge, ctx: Any, params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Run the call in a worker thread and, while it is in flight, poll the host for the
    job it started (or the one ``job_id`` names) and emit ``notifications/progress``."""
    request_id = uuid.uuid4().hex
    args = dict(params.arguments or {})
    tracker = ProgressTracker()
    result: types.CallToolResult | None = None

    async def poll() -> None:
        while True:
            await anyio.sleep(bridge.progress_interval_s)
            snapshot = await anyio.to_thread.run_sync(
                bridge.progress_snapshot, params.name, args, request_id
            )
            update = tracker.update(snapshot)
            if update is not None:
                progress, total, message = update
                try:
                    await ctx.session.report_progress(progress, total, message)
                except Exception:  # noqa: BLE001 - a lost notification is not a failure
                    log.debug("progress notification failed", exc_info=True)

    async with anyio.create_task_group() as group:
        group.start_soon(poll)
        result = await anyio.to_thread.run_sync(
            bridge.call_tool, params.name, params.arguments, request_id
        )
        group.cancel_scope.cancel()
    assert result is not None
    return result


def build_server(bridge: Bridge | None = None) -> Server[Any]:
    bridge = bridge or Bridge()

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=bridge.list_tools())

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        spec = bridge._by_name.get(params.name)
        if not _wants_progress(ctx) or spec is None or spec.bridge_local:
            return await anyio.to_thread.run_sync(bridge.call_tool, params.name, params.arguments)
        return await _call_with_progress(bridge, ctx, params)

    async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=bridge.list_resources())

    async def on_list_resource_templates(
        ctx: Any, params: Any
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=bridge.list_resource_templates()
        )

    async def on_read_resource(
        ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return await anyio.to_thread.run_sync(bridge.read_resource, str(params.uri))

    async def on_list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=list_prompts(bridge.config.profile))

    async def on_get_prompt(
        ctx: Any, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        return get_prompt(params.name, params.arguments, bridge.config.profile)

    def tool_schema(name: str) -> dict[str, Any] | None:
        spec = bridge._by_name.get(name)
        return spec.input_schema if spec else None

    server: Server[Any] = Server(
        SERVER_NAME,
        version=__version__,
        title="HocusPocus",
        description="Drive a live SideFX Houdini session.",
        instructions=instructions_for(bridge.config.profile),
        get_tool_input_schema=tool_schema,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_list_resource_templates=on_list_resource_templates,
        on_read_resource=on_read_resource,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
    )
    server.bridge = bridge  # type: ignore[attr-defined]
    from .resources import install as install_resources

    install_resources(server, bridge)  # profile v2: resources with etags and subscriptions
    return server


async def serve_stdio(bridge: Bridge | None = None) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(bridge)
    _ = server.bridge.ledger  # type: ignore[attr-defined]  # open and reconcile it at start
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
