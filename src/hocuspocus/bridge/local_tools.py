"""Bridge-local tools: ``houdini_status`` and ``houdini_connect``. See docs/BIBLE.md §4.2, §3.6.

These run in the bridge (not in Houdini) so they work with no Houdini running.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..tools.errors import ToolError
from ..version import __version__
from . import instances as registry
from .client import OFFLINE_HINT

if TYPE_CHECKING:
    from .server import Bridge

HOST_STATUS_TIMEOUT_S = 10.0

DIES_WITH_SERVER_NOTE = (
    "This Houdini shares this MCP server's job object and closes when the server exits "
    "(the client ends both together): save with hip_save before the session ends. To keep "
    "Houdini alive across sessions, start it with `hocuspocus launch` and attach with "
    "houdini_connect {pid}."
)
OUTLIVES_NOTE = (
    "This Houdini is detached from this MCP server and should keep running after it exits, "
    "unless the client kills the whole process tree; save with hip_save before the session "
    "ends. A later session can attach to it with houdini_connect {pid}."
)

# Fields the host's own ``houdini_status`` answer may contribute to the connected block.
_HOST_FIELDS = ("hip", "time", "env", "scene_generation", "host_version", "houdini", "ui", "recent")


def connected_block(bridge: Bridge, inst: registry.Instance) -> dict[str, Any]:
    """Registry entry + ``/health`` + the host's ``houdini_status``. Raises if ``/health`` fails."""
    client = bridge.client_for(inst)
    health = client.health()
    bridge.mark_verified(inst)
    block: dict[str, Any] = {
        "pid": inst.pid,
        "port": inst.port,
        "label": inst.label,
        "houdini": health.get("houdini") or inst.houdini,
        "ui": inst.ui,
        "started": inst.started,
        "scene_generation": health.get("generation", inst.generation),
    }
    if inst.hip:
        block["hip"] = {"path": inst.hip}
    host_version = health.get("host_version") or health.get("version")
    if host_version:
        block["host_version"] = host_version
    try:
        ok, result, _meta = client.call("houdini_status", {}, HOST_STATUS_TIMEOUT_S)
    except ToolError as exc:
        block["host_error"] = exc.to_dict()
        return block
    if not ok:
        block["host_error"] = result
        return block
    host = result.get("connected") if isinstance(result.get("connected"), dict) else result
    for key in _HOST_FIELDS:
        if key in host:
            block[key] = host[key]
    for key in ("read_only", "allow_python"):
        if key in result:
            block.setdefault("_settings", {})[key] = result[key]
        elif key in host:
            block.setdefault("_settings", {})[key] = host[key]
    return block


def _split_settings(block: dict[str, Any] | None) -> dict[str, Any]:
    if not block:
        return {}
    return block.pop("_settings", {}) or {}


def houdini_status(bridge: Bridge, args: dict[str, Any]) -> dict[str, Any]:
    live = bridge.scan()
    warnings: list[str] = []
    connected: dict[str, Any] | None = None
    chosen_pid: int | None = None
    if bridge.detached:
        warnings.append("The bridge is disconnected; call houdini_connect to attach.")
    else:
        sel = registry.select(live, bridge.preferred_pid)
        warnings.extend(sel.warnings)
        if sel.instance is not None:
            chosen_pid = sel.instance.pid
            try:
                connected = connected_block(bridge, sel.instance)
                bridge.last_target = sel.instance
            except ToolError as exc:
                warnings.append(
                    f"pid {sel.instance.pid} is registered but unusable: {exc.code}: {exc.message}"
                )
    settings = _split_settings(connected)
    status: dict[str, Any] = {
        "connected": connected,
        "instances": [dict(inst.public(), selected=inst.pid == chosen_pid) for inst in live],
        "bridge_version": __version__,
        "profile": bridge.config.profile,
    }
    # Host settings are only known while connected; omit rather than report null.
    for key in ("read_only", "allow_python"):
        if isinstance(settings.get(key), bool):
            status[key] = settings[key]
    if not live:
        warnings.append(
            "No Houdini with HocusPocus is running; houdini_connect {launch: {mode}} starts one."
        )
    if warnings:
        status["warnings"] = warnings
    return status


def houdini_connect(bridge: Bridge, args: dict[str, Any]) -> dict[str, Any]:
    modes = [k for k in ("pid", "launch", "disconnect") if args.get(k) not in (None, False)]
    if len(modes) > 1:
        raise ToolError(
            "invalid_argument",
            f"Pass only one of pid, launch, disconnect (got {', '.join(modes)}).",
            hint="attach with {pid}, start one with {launch: {mode}}, or detach with {disconnect: true}",
        )

    if args.get("disconnect"):
        previous = bridge.preferred_pid
        bridge.preferred_pid = None
        bridge.detached = True
        return {"connected": None, "disconnected": previous}

    if args.get("launch") is not None:
        launch = args["launch"]
        result = bridge.launcher.launch(
            str(launch.get("mode", "gui")),
            launch.get("hip"),
            float(launch.get("wait_s", 90)),
        )
        block = connected_block(bridge, result.instance)
        bridge.preferred_pid = result.instance.pid
        bridge.last_target = result.instance
        bridge.detached = False
        _split_settings(block)
        launched: dict[str, Any] = {
            "mode": result.mode,
            "pid": result.instance.pid,
            "outlives_server": result.outlives_server,
            "note": OUTLIVES_NOTE if result.outlives_server else DIES_WITH_SERVER_NOTE,
        }
        if result.log:
            launched["log"] = result.log
        return {"connected": block, "launched": launched}

    live = bridge.scan()
    if args.get("pid") is not None:
        pid = int(args["pid"])
        match = next((inst for inst in live if inst.pid == pid), None)
        if match is None:
            raise ToolError(
                "houdini_offline",
                f"No live HocusPocus instance with pid {pid}.",
                hint="pick a pid from houdini_status.instances, or launch one with houdini_connect {launch}",
                candidates=[str(inst.pid) for inst in live],
            )
        block = connected_block(bridge, match)
        bridge.preferred_pid = pid
        bridge.last_target = match
        bridge.detached = False
        _split_settings(block)
        return {"connected": block}

    # No arguments: (re)enable automatic selection and report what it picks.
    sel = registry.select(live, bridge.preferred_pid)
    if sel.instance is None:
        raise ToolError(
            "houdini_offline",
            "No live Houdini instance with HocusPocus is running.",
            hint=OFFLINE_HINT,
        )
    block = connected_block(bridge, sel.instance)
    bridge.last_target = sel.instance
    bridge.detached = False
    _split_settings(block)
    out: dict[str, Any] = {"connected": block}
    if sel.warnings:
        out["warnings"] = list(sel.warnings)
    return out


LOCAL_TOOLS: dict[str, Callable[[Bridge, dict[str, Any]], dict[str, Any]]] = {
    "houdini_status": houdini_status,
    "houdini_connect": houdini_connect,
}
