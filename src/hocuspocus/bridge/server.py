"""The MCP server (stdio) that fronts Houdini. See docs/BIBLE.md §3.3, §4.1, §4.8.

Built on the SDK's low-level :class:`mcp.server.Server` rather than ``MCPServer``: the tool
surface is *data* (names + raw JSON Schemas from :mod:`hocuspocus.tools.catalog`), and only
the low-level ``on_list_tools`` / ``on_call_tool`` handlers let us publish those schemas
verbatim, return ``structuredContent`` for arbitrary dicts, and own argument validation.
``MCPServer.add_tool`` derives schemas from Python signatures instead.
"""

from __future__ import annotations

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
from .validate import validate

EXIT_GRACE_S = 1.5
"""After a lost response, how long to watch for the Houdini process to exit."""

log = logging.getLogger(__name__)

SERVER_NAME = "hocuspocus"
MAX_TIMEOUT_S = 3600.0

_TRANSPORT_CODES = frozenset(
    {"houdini_offline", "houdini_busy", "delivery_unknown", "version_mismatch", "internal"}
)


def _error_result(
    error: dict[str, Any], meta: dict[str, Any] | None = None
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=budget.dumps(error))],
        structured_content=error,
        is_error=True,
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
    ) -> None:
        self.config = config or BridgeConfig.load()
        profile = self.config.profile if self.config.profile in ("core", "full") else "core"
        self.tools: tuple[ToolSpec, ...] = (
            tuple(tools) if tools is not None else catalog.for_profile(profile)
        )
        self._by_name = {spec.name: spec for spec in self.tools}
        self.client_factory = client_factory
        self.scan: Callable[[], list[registry.Instance]] = scan or (lambda: registry.scan())
        self.launcher = launcher or Launcher(self.config.hfs or None, scan=self.scan)
        self.preferred_pid: int | None = None
        self.last_target: registry.Instance | None = None
        """The instance the last forwarded call went to, to name it if it exits."""
        self.exit_grace_s = EXIT_GRACE_S
        self.detached = False
        self._verified: set[tuple[int, int, str]] = set()
        self._lock = threading.Lock()

    # -- instances -----------------------------------------------------------------------

    def client_for(self, inst: registry.Instance) -> HostClient:
        return self.client_factory(inst.port, inst.token)

    def mark_verified(self, inst: registry.Instance) -> None:
        self._verified.add((inst.pid, inst.port, inst.token))

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
            raise ToolError(
                "houdini_offline",
                "No live Houdini instance with HocusPocus is running.",
                hint=OFFLINE_HINT,
                retryable=False,  # repeating cannot work until something is launched
            )
        inst = sel.instance
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
        self, name: str, args: dict[str, Any]
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        inst, warnings = self.resolve()
        client = self.client_for(inst)
        key = (inst.pid, inst.port, inst.token)
        if key not in self._verified:
            client.health()  # version check before the first call to this instance
            self._verified.add(key)
        try:
            ok, payload, meta = client.call(name, args, self._timeout(args), uuid.uuid4().hex)
        except ToolError as exc:
            # A connection reset usually means Houdini died mid-call: say so, not "unknown".
            if exc.code == "delivery_unknown" and self._wait_exit(inst):
                error = self._exited_error(inst, f" while running {name}")
                error.detail = {**error.detail, "transport": exc.message}
                raise error from exc
            raise
        meta = dict(meta)
        meta.setdefault("pid", inst.pid)
        if warnings:
            meta["warnings"] = warnings
        return ok, payload, meta

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
                    output_schema=spec.output_schema,
                    annotations=types.ToolAnnotations.model_validate(spec.annotations()),
                )
            )
        return out

    def invoke(
        self, name: str, args: dict[str, Any]
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
            return self.forward(name, args)
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

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        """Validate, dispatch and shape one ``tools/call``. Unknown tools raise ``MCPError``."""
        spec = self._by_name.get(name)
        if spec is None:
            raise MCPError(
                types.INVALID_PARAMS, f"Unknown tool: {name}", {"tools": sorted(self._by_name)}
            )
        args = dict(arguments or {})
        violations = validate(args, spec.input_schema)
        if violations:
            error = ToolError(
                "invalid_argument",
                f"{len(violations)} argument problem(s) for {name}: " + "; ".join(violations[:5]),
                hint=f"fix the listed arguments; {name}'s inputSchema in tools/list is authoritative",
                detail={"violations": violations},
            )
            return _error_result(error.to_dict())
        ok, payload, meta = self.invoke(name, args)
        return self.shape(ok, payload, meta)

    def shape(
        self, ok: bool, payload: dict[str, Any], meta: dict[str, Any]
    ) -> types.CallToolResult:
        meta = dict(meta)
        if not ok:
            return _error_result(payload, meta)
        result, images = budget.extract_images(payload)
        result, cuts = budget.apply_budget(result, self.config.max_response_bytes)
        if cuts:
            meta[budget.TRUNCATION_META_KEY] = cuts
        content: list[Any] = [types.TextContent(type="text", text=budget.dumps(result))]
        content += [
            types.ImageContent(type="image", data=img.data, mime_type=img.mime_type)
            for img in images
        ]
        return types.CallToolResult(
            content=content, structured_content=result, is_error=False, meta=meta or None
        )

    # -- resources -----------------------------------------------------------------------

    RESOURCES: tuple[tuple[str, str, str, str], ...] = (
        (
            "houdini://status",
            "status",
            "application/json",
            "Connected Houdini, hip file, frame and instances.",
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


def build_server(bridge: Bridge | None = None) -> Server[Any]:
    bridge = bridge or Bridge()

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=bridge.list_tools())

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        return await anyio.to_thread.run_sync(bridge.call_tool, params.name, params.arguments)

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
