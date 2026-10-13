"""Bridge-local tools: ``houdini_status`` and ``houdini_connect``. See docs/BIBLE.md §4.2, §3.6.

These run in the bridge (not in Houdini) so they work with no Houdini running.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..tools.errors import ToolError
from ..version import __version__
from . import instances as registry
from .client import OFFLINE_HINT

if TYPE_CHECKING:
    from .server import Bridge

HOST_STATUS_TIMEOUT_S = 10.0
ROW_HEALTH_TIMEOUT_S = 2.0
"""``/health`` per ``instances[]`` row (busy, jobs_running); it never needs the main thread."""
QUIT_WAIT_S = 15.0
"""How long houdini_connect {quit} waits for the Houdini process to end."""

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
    """Registry entry + ``/health`` + the host's ``houdini_status``. Raises if ``/health``
    fails, and :class:`~hocuspocus.bridge.instances.StaleEntry` (after deleting the entry)
    when the port is not that host."""
    client = bridge.client_for(inst)
    health = bridge.verify(inst)
    block: dict[str, Any] = {
        "pid": inst.pid,
        "port": inst.port,
        "label": inst.label,
        "houdini": health.get("houdini") or inst.houdini,
        "ui": inst.ui,
        "started": inst.started,
        "scene_generation": health.get("generation", inst.generation),
    }
    if inst.name:
        block["name"] = inst.name
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


def _select_verified(
    bridge: Bridge, warnings: list[str]
) -> tuple[list[registry.Instance], registry.Selection, dict[str, Any] | None]:
    """Scan, select and connect, deleting stale entries on the way (review 10 1.4).

    Returns ``(live, selection, connected_block_or_None)``; a selected instance that is
    registered but unusable is reported in ``warnings``."""
    for _attempt in range(5):
        live = bridge.scan()
        sel = registry.select(live, bridge.preferred_pid)
        if sel.instance is None:
            return live, sel, None
        try:
            block = connected_block(bridge, sel.instance)
        except registry.StaleEntry as exc:
            warnings.append(f"Removed a stale registry entry: {exc}.")
            continue
        except ToolError as exc:
            warnings.extend(sel.warnings)
            warnings.append(
                f"pid {sel.instance.pid} is registered but unusable: {exc.code}: {exc.message}"
            )
            return live, sel, None
        warnings.extend(sel.warnings)
        bridge.last_target = sel.instance
        return live, sel, block
    live = bridge.scan()
    return live, registry.select(live, bridge.preferred_pid), None


def houdini_status(bridge: Bridge, args: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    connected: dict[str, Any] | None = None
    chosen_pid: int | None = None
    lost_block: dict[str, Any] | None = None
    if bridge.detached:
        live = bridge.scan()
        warnings.append("The bridge is disconnected; call houdini_connect to attach.")
    else:
        live, sel, connected = _select_verified(bridge, warnings)
        if sel.instance is not None:
            chosen_pid = sel.instance.pid
        if sel.lost_pid is not None:
            lost = bridge.lost_error(live)
            lost_block = {"pid": sel.lost_pid, "label": lost.detail["label"]}
            warnings.append(f"{lost.message} {lost.hint[0].upper()}{lost.hint[1:]}.")
    settings = _split_settings(connected)
    status: dict[str, Any] = {
        "connected": connected,
        **({"lost": lost_block} if lost_block else {}),
        "instances": [_row(bridge, inst, inst.pid == chosen_pid) for inst in live],
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


def _row(bridge: Bridge, inst: registry.Instance, selected: bool) -> dict[str, Any]:
    """One ``instances[]`` row: the registry entry, ``selected``, and from ``/health`` the
    host's ``busy`` flag and ``jobs_running`` (review 19 papercut 4)."""
    row = dict(inst.public(), selected=selected)
    try:
        health = bridge.client_for(inst).health(timeout_s=ROW_HEALTH_TIMEOUT_S)
    except ToolError as exc:
        row["unreachable"] = exc.code
        return row
    for key in ("busy", "jobs_running"):
        if key in health:
            row[key] = health[key]
    return row


def _no_such_pid(pid: int, live: list[registry.Instance], hint: str) -> ToolError:
    """A pid that is not a live instance: repeating cannot help (review 19 papercut 9)."""
    ordered = registry.sort_preferred(live)
    return ToolError(
        "houdini_offline",
        f"No live HocusPocus instance with pid {pid}."
        + (f" Live: {'; '.join(i.describe() for i in ordered)}." if ordered else ""),
        hint=hint,
        candidates=[inst.candidate() for inst in ordered],
        retryable=False,
    )


def _apply_name(
    bridge: Bridge, inst: registry.Instance, name: str | None, live: list[registry.Instance]
) -> registry.Instance:
    """Store ``name`` on ``inst`` (moving it from any other instance) and return the
    updated instance."""
    if name is None:
        return inst
    name = name.strip()
    for other in live:
        if other.pid != inst.pid and other.name and other.name == name:
            registry.set_name(other, "")
    registry.set_name(inst, name)
    return replace(inst, name=name)


def houdini_connect(bridge: Bridge, args: dict[str, Any]) -> dict[str, Any]:
    if args.get("name") is not None and args.get("pid") is None and args.get("launch") is None:
        if args.get("quit") or args.get("disconnect"):
            raise ToolError(
                "invalid_argument",
                "name goes with pid (to name that Houdini) or alone (to select it by name).",
                hint="houdini_connect {pid, name: 'worker'}, then houdini_connect {name: 'worker'}",
            )
        return _connect_by_name(bridge, str(args["name"]))
    modes = [k for k in ("pid", "launch", "disconnect") if args.get(k) not in (None, False)]
    if args.get("quit"):
        # quit takes an optional pid (the Houdini to quit); nothing else.
        others = [m for m in modes if m != "pid"]
        if others:
            raise ToolError(
                "invalid_argument",
                f"quit cannot be combined with {', '.join(others)}.",
                hint="quit the selected Houdini with {quit: true}, or one by pid with "
                "{quit: true, pid}",
            )
        return _quit(bridge, args)
    if args.get("on_unsaved") is not None:
        raise ToolError(
            "invalid_argument",
            "on_unsaved applies only with quit: true.",
            hint="houdini_connect {quit: true, on_unsaved: 'fail'|'save'|'discard'}",
        )
    if len(modes) > 1:
        raise ToolError(
            "invalid_argument",
            f"Pass only one of pid, launch, disconnect (got {', '.join(modes)}).",
            hint="attach with {pid}, start one with {launch: {mode}}, or detach with {disconnect: true}",
        )

    if args.get("disconnect"):
        previous = bridge.preferred_pid
        bridge.pin(None)
        bridge.detached = True
        return {"connected": None, "disconnected": previous}

    if args.get("launch") is not None:
        launch = args["launch"]
        result = bridge.launcher.launch(
            str(launch.get("mode", "gui")),
            launch.get("hip"),
            float(launch.get("wait_s", 90)),
        )
        instance = _apply_name(bridge, result.instance, args.get("name"), bridge.scan())
        block = _connect_block(bridge, instance)
        bridge.pin(instance)
        bridge.last_target = instance
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
            raise _no_such_pid(
                pid,
                live,
                "pick a pid from the candidates, or launch one with houdini_connect {launch}",
            )
        match = _apply_name(bridge, match, args.get("name"), live)
        block = _connect_block(bridge, match)
        bridge.pin(match)
        bridge.last_target = match
        bridge.detached = False
        _split_settings(block)
        return {"connected": block}

    # No arguments: clear any pin, (re)enable automatic selection and report what it picks.
    bridge.pin(None)
    warnings: list[str] = []
    _live, sel, block = _select_verified(bridge, warnings)
    if sel.instance is None or block is None:
        raise ToolError(
            "houdini_offline",
            "No live Houdini instance with HocusPocus is running."
            if sel.instance is None
            else f"Houdini pid {sel.instance.pid} is registered but unusable.",
            hint=OFFLINE_HINT,
            detail={"warnings": warnings} if warnings else None,
        )
    bridge.detached = False
    _split_settings(block)
    out: dict[str, Any] = {"connected": block}
    if warnings:
        out["warnings"] = warnings
    return out


def _connect_by_name(bridge: Bridge, name: str) -> dict[str, Any]:
    """``houdini_connect {name}``: pin the live instance named ``name``."""
    live = bridge.scan()
    match = next((inst for inst in live if inst.name and inst.name == name.strip()), None)
    if match is None:
        ordered = registry.sort_preferred(live)
        raise ToolError(
            "houdini_offline",
            f"No live HocusPocus instance is named {name!r}.",
            hint="name one with houdini_connect {pid, name}, or pick a pid from the candidates",
            candidates=[inst.candidate() for inst in ordered],
            retryable=False,
        )
    block = _connect_block(bridge, match)
    bridge.pin(match)
    bridge.last_target = match
    bridge.detached = False
    _split_settings(block)
    return {"connected": block}


def _quit(bridge: Bridge, args: dict[str, Any]) -> dict[str, Any]:
    """``houdini_connect {quit: true, on_unsaved, pid?}``: quit a Houdini through its host
    (review 15 papercut 9: hou.exit in houdini_python looked like a failure)."""
    on_unsaved = args.get("on_unsaved") or "fail"
    live = bridge.scan()
    if args.get("pid") is not None:
        pid = int(args["pid"])
        inst = next((i for i in live if i.pid == pid), None)
        if inst is None:
            raise _no_such_pid(pid, live, "pick a pid from the candidates")
    else:
        warnings: list[str] = []
        _live, sel, block = _select_verified(bridge, warnings)
        if sel.lost_pid is not None:
            raise bridge.lost_error(_live)
        inst = sel.instance if block is not None else None
        if inst is None:
            raise ToolError(
                "houdini_offline",
                "No live Houdini instance with HocusPocus is running; nothing to quit.",
                hint=OFFLINE_HINT,
                retryable=False,
            )
    client = bridge.client_for(inst)
    ok, result, _meta = client.quit(on_unsaved)
    if not ok:
        raise ToolError.from_dict(result)
    # Forget it now: the bridge must not report this Houdini as having "exited" later.
    registry.forget(inst)
    if bridge.preferred_pid == inst.pid:
        bridge.pin(None)
    if bridge.last_target is not None and bridge.last_target.pid == inst.pid:
        bridge.last_target = None
    deadline = time.monotonic() + QUIT_WAIT_S
    exited = not registry.pid_alive(inst.pid)
    while not exited and time.monotonic() < deadline:
        time.sleep(0.2)
        exited = not registry.pid_alive(inst.pid)
    out: dict[str, Any] = {"quit": True, "pid": inst.pid, "exited": exited}
    if result.get("saved"):
        out["saved"] = result.get("hip")
    if not exited:
        out["note"] = f"Houdini (pid {inst.pid}) is still closing."
    return out


def _connect_block(bridge: Bridge, inst: registry.Instance) -> dict[str, Any]:
    """:func:`connected_block` for an explicit target: a stale entry is an offline error."""
    try:
        return connected_block(bridge, inst)
    except registry.StaleEntry as exc:
        raise ToolError(
            "houdini_offline",
            f"No live HocusPocus instance with pid {inst.pid}: {exc}; the entry was removed.",
            hint="pick a pid from houdini_status.instances, or launch one with houdini_connect {launch}",
        ) from exc


LOCAL_TOOLS: dict[str, Callable[[Bridge, dict[str, Any]], dict[str, Any]]] = {
    "houdini_status": houdini_status,
    "houdini_connect": houdini_connect,
}
