"""The MCP server (stdio) that fronts Houdini. See docs/BIBLE.md §3.3, §4.1, §4.8.

Built on the SDK's low-level :class:`mcp.server.Server` rather than ``MCPServer``: the tool
surface is *data* (names + raw JSON Schemas from :mod:`hocuspocus.tools.catalog`), and only
the low-level ``on_list_tools`` / ``on_call_tool`` handlers let us publish those schemas
verbatim, return ``structuredContent`` for arbitrary dicts, and own argument validation.
``MCPServer.add_tool`` derives schemas from Python signatures instead.
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.shared.exceptions import MCPError

from ..tools import catalog
from ..tools.catalog import ToolSpec
from ..tools.errors import ToolError
from ..version import __version__
from . import budget
from . import instances as registry
from .client import OFFLINE_HINT, REINSTALL_HINT, HostClient
from .config import BridgeConfig
from .instructions import INSTRUCTIONS, guide_text
from .launch import Launcher
from .local_tools import LOCAL_TOOLS
from .validate import coerce_integers, validate

EXIT_GRACE_S = 1.5
"""After a lost response, how long to watch for the Houdini process to exit."""
OUTLINE_ARGS = {"root": "/", "format": "outline", "depth": 2}
"""What ``houdini://outline`` reads (review 11 B11)."""
MAX_STALE_ENTRIES = 5
"""How many stale registry entries one call may delete before giving up."""
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
    ) -> None:
        self.config = config or BridgeConfig.load()
        profile = self.config.profile if self.config.profile in catalog.PROFILES else "core"
        self.tools: tuple[ToolSpec, ...] = (
            tuple(tools) if tools is not None else catalog.for_profile(profile)
        )
        self._by_name = {spec.name: spec for spec in self.tools}
        self.client_factory = client_factory
        self.scan: Callable[[], list[registry.Instance]] = scan or (lambda: registry.scan())
        self.launches = launches or registry.LaunchLog()
        self.launcher = launcher or Launcher(
            self.config.hfs or None, scan=self.scan, launches=self.launches
        )
        self.preferred_pid: int | None = None
        self.last_target: registry.Instance | None = None
        """The instance the last forwarded call went to, to name it if it exits."""
        self._previous_target: registry.Instance | None = None
        self.exit_grace_s = EXIT_GRACE_S
        self.detached = False
        self._verified: set[tuple[int, int, str]] = set()
        self._lock = threading.Lock()
        self.progress_interval_s = PROGRESS_INTERVAL_S
        self._inflight: dict[str, registry.Instance] = {}
        """request_id -> the instance a call in flight was sent to (progress polling)."""

    # -- instances -----------------------------------------------------------------------

    def client_for(self, inst: registry.Instance) -> HostClient:
        return self.client_factory(inst.port, inst.token)

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

    def resolve(self) -> tuple[registry.Instance, list[str]]:
        """Pick the target instance (BIBLE §3.3 rule 3) or raise ``houdini_offline``."""
        if self.detached:
            raise ToolError(
                "houdini_offline",
                "The bridge was disconnected with houdini_connect {disconnect: true}.",
                hint="call houdini_connect (with pid, launch, or no arguments) to attach again",
            )
        live = self.scan()
        sel = registry.select(live, self.preferred_pid)
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
        self._previous_target = self.last_target
        if self.preferred_pid is not None and inst.pid != self.preferred_pid:
            self.preferred_pid = None  # the pinned instance exited; fall back to auto-selection
        elif exited is not None and exited.pid != inst.pid:
            warnings.append(
                f"The Houdini you were driving (pid {exited.pid}) has exited; changes made in it "
                f"since its last save are lost. Now using pid {inst.pid}."
            )
        self.last_target = inst
        if inst.hp != catalog.HP_RPC_VERSION:
            raise ToolError(
                "version_mismatch",
                f"Houdini pid {inst.pid} runs a host speaking hp/v{inst.hp}; this bridge speaks "
                f"hp/v{catalog.HP_RPC_VERSION}.",
                hint=REINSTALL_HINT,
            )
        return inst, warnings

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

    def forward(
        self, name: str, args: dict[str, Any], request_id: str | None = None
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        request_id = request_id or uuid.uuid4().hex
        stale: list[str] = []
        for _attempt in range(MAX_STALE_ENTRIES):
            inst, warnings = self.resolve()
            client = self.client_for(inst)
            try:
                if (inst.pid, inst.port, inst.token) not in self._verified:
                    self.verify(inst)  # identity and version, before the first call
            except registry.StaleEntry as exc:
                stale.append(str(exc))
                continue  # deleted; select again
            self._inflight[request_id] = inst
            try:
                ok, payload, meta = client.call(
                    name,
                    args,
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
            if isinstance(job_id, str) and job_id:
                ok, snapshot, _meta = client.job(job_id, timeout_s=5.0)
                return snapshot if ok else None
            jobs = client.call_jobs(request_id)
        except Exception:  # noqa: BLE001 - progress must never fail the call
            log.debug("progress poll for %s failed", name, exc_info=True)
            return None
        return jobs[-1] if jobs else None

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
                    return True, impl(self, args), {}
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
            error = ToolError(
                "invalid_argument",
                f"{len(violations)} argument problem(s) for {name}: " + "; ".join(violations[:5]),
                hint=f"fix the listed arguments; {name}'s inputSchema in tools/list is authoritative",
                detail={"violations": violations},
            )
            return make_result(self.config.result_content, name, error.to_dict(), is_error=True)
        # 50.0 validates as an integer; the host checks isinstance(..., int) (review 10).
        args = coerce_integers(args, spec.input_schema)
        ok, payload, meta = self.invoke(name, args, request_id)
        pageable = "cursor" in (spec.input_schema.get("properties") or {})
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
            result, self.config.max_response_bytes, args, pageable=pageable
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
            "The HocusPocus operating manual with tool reference.",
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
        if uri == "hocuspocus://guide":
            return types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        uri=uri, text=guide_text(), mime_type="text/markdown"
                    )
                ]
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

_PROMPTS: dict[str, tuple[str, list[tuple[str, str, bool]], str]] = {
    "inspect_scene": (
        "Summarise the open Houdini scene: hip file, networks, problems.",
        [("root", "Network to start from (default /obj)", False)],
        "Inspect the Houdini scene under {root}. Call houdini_status first (hip file, frame, "
        "instance). Then network_describe on {root} with depth 2, and problems on {root}. "
        "Summarise: what each top-level network builds, the display/render nodes, and any "
        "errors or warnings with the node path and the likely cause. Do not modify anything.",
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
        "node_type_search when unsure of a type name. Then cook the display node, check "
        "geo_info (counts, bbox), fix any errors from the results, and finish with "
        "viewport_capture. Report the final node paths.",
    ),
    "debug_red_node": (
        "Find out why a node has errors and fix it.",
        [("path", "Node path, e.g. /obj/geo1/attribwrangle1", True)],
        "The node {path} shows errors. Call node_info on it (include errors, parms, inputs) "
        "and problems on its parent. Read the error text, inspect upstream inputs and any "
        "expressions or file paths involved, and explain the root cause. Propose the smallest "
        "fix; apply it with parm_set/node_connect only if it is unambiguous, then cook {path} "
        "to confirm it is clean.",
    ),
    "turntable_preview": (
        "Set up a turntable camera around an object and capture preview frames.",
        [
            ("path", "Object or SOP to orbit, e.g. /obj/geo1", True),
            ("frames", "Frame count for a full turn (default 48)", False),
        ],
        "Create a turntable preview of {path} over {frames} frames. Read geo_info for its "
        "bounding box, then create a null at the bbox centre with ry keyed 0→360 over frames "
        "1–{frames} and a camera parented to it, framed to the bbox. Set the playbar range with "
        "time. Capture viewport_capture at the first frame and at a quarter turn using that "
        "camera, and show both images.",
    ),
}
_PROMPT_DEFAULTS = {"root": "/obj", "parent": "a new geo node under /obj", "frames": "48"}


def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name=name,
            description=desc,
            arguments=[types.PromptArgument(name=a, description=d, required=r) for a, d, r in args],
        )
        for name, (desc, args, _tpl) in _PROMPTS.items()
    ]


def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    if name not in _PROMPTS:
        raise MCPError(
            types.INVALID_PARAMS, f"Unknown prompt: {name}", {"prompts": sorted(_PROMPTS)}
        )
    desc, spec, template = _PROMPTS[name]
    values = dict(_PROMPT_DEFAULTS)
    values.update({k: v for k, v in (arguments or {}).items() if v})
    missing = [a for a, _d, required in spec if required and not values.get(a)]
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
        return types.ListPromptsResult(prompts=list_prompts())

    async def on_get_prompt(
        ctx: Any, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        return get_prompt(params.name, params.arguments)

    def tool_schema(name: str) -> dict[str, Any] | None:
        spec = bridge._by_name.get(name)
        return spec.input_schema if spec else None

    server: Server[Any] = Server(
        SERVER_NAME,
        version=__version__,
        title="HocusPocus",
        description="Drive a live SideFX Houdini session.",
        instructions=INSTRUCTIONS,
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
    return server


async def serve_stdio(bridge: Bridge | None = None) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(bridge)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
