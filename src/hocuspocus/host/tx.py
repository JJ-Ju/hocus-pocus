"""The transaction engine: every scene mutation is a :class:`Plan` of :class:`Op` steps
(spec-2.0 §2.4, §4; principle 14, "one way to change the scene").

``edit`` builds a plan from its ``ops``; ``node_create``, ``parm_set``, ``node_connect``,
``node_delete``, ``node_edit``, ``node_copy``, ``node_layout`` and ``network_build`` build
one from their 1.4 arguments and shape :func:`execute`'s :class:`Result` into their 1.4
result. So there is one undo policy, one rollback and one echo engine.

* **Ops** (``Op.op``): ``create``, ``delete``, ``connect``, ``set``, ``node`` (rename,
  flags, color, comment, position, lock, spare_parms, bypass), ``copy``, ``layout``,
  ``build`` (``hou.data`` with ``press``) and ``select``. An op may carry an ``id``; a later
  op names its node as ``$id`` (or ``$id/child``, ``$id/parm``) in its path fields, and the
  reference resolves to the path the op actually produced when the later op runs.
* :func:`validate` checks a plan without changing the scene (types resolve, parents exist
  and hold the category, parms and tuples exist or are spare parms an earlier op adds,
  inputs by index, name, ``"next"`` or ``$id``, names free, locked assets refused) and
  returns :class:`Diagnostics`: the plan with resolved (and predicted) paths, and the
  problems. A dry run is that.
* :func:`execute` runs the plan on the main thread, inside the one undo group the
  dispatcher opened for the call (``HocusPocus: edit <n> ops`` for ``edit``). Houdini
  refuses ``performUndo`` inside an open group, so a failing op is reverted by
  compensation (:class:`Rollback`), newest first; with ``partial`` only that op's own
  changes are reverted and the rest stand. ``rolled_back`` is what really happened:
  a delete cannot be compensated, so ``edit`` then leaves the answer to the dispatcher,
  which undoes the whole group after it closes (``host/undo.py``).
* :func:`echo` is the ``edit`` result: one row per op and the 1.4 summary row (``path,
  type, errors, warnings, cook_state, cook_ms``) per touched node, each cooked once at the
  end; ``return: full`` gives the 1.4 full shapes (flags, parm rows with long strings
  elided).

Pure Python apart from the op handlers, which import ``hou`` and the tool families lazily
(the families import this module).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from hocuspocus.tools.errors import ToolError

OP_KINDS = ("create", "delete", "connect", "set", "node", "copy", "layout", "build", "select")

SET_ITEM_FIELDS = frozenset(
    (
        "path", "value", "expression", "language", "keyframe", "keyframes", "channel_ref",
        "ramp", "multiparm_count", "revert_to_default", "press", "animation",
    )
)  # fmt: skip

OP_FIELDS: dict[str, frozenset[str]] = {
    "create": frozenset(
        (
            "parent",
            "type",
            "name",
            "parms",
            "inputs",
            "flags",
            "position",
            "exact_type",
            "cook",
            "layout",
        )
    ),  # fmt: skip
    "delete": frozenset(("paths", "path", "keep_connections")),
    "connect": frozenset(("from", "from_output", "to", "to_input")),
    "set": SET_ITEM_FIELDS | {"frame", "node", "parms"},
    "node": frozenset(
        ("path", "name", "flags", "color", "comment", "position", "lock", "bypass", "spare_parms")
    ),
    "copy": frozenset(("paths", "to_parent", "names", "with_inputs", "position_offset")),
    "layout": frozenset(("parent", "paths", "mode")),
    "build": frozenset(("parent", "data", "on_name_collision", "layout", "tag", "press")),
    "select": frozenset(("paths",)),
}
"""The fields each ``edit`` op takes besides ``op`` and ``id``."""

OPTION_FIELDS: dict[str, tuple[str, ...]] = {
    "create": ("exact_type", "cook", "layout"),
    "set": ("frame",),
}
"""Op fields that are options of the op rather than of the item a 1.4 tool takes (the
1.4 tools pass them once per call)."""

ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REF_FIELDS: dict[str, tuple[str, ...]] = {
    "create": ("parent",),
    "delete": ("paths",),
    "connect": ("from", "to"),
    "set": ("path", "node", "channel_ref"),
    "node": ("path",),
    "copy": ("paths", "to_parent"),
    "layout": ("parent", "paths"),
    "build": ("parent",),
    "select": ("paths",),
}
"""Path fields in which ``$id`` resolves (never parm values: ``$F`` and ``$HIP`` are
Houdini's). ``create`` also resolves ``inputs[].from``."""

REF_HINT = "An $id names an earlier op of the same call that succeeded; ids resolve in op order."


# -- rollback --------------------------------------------------------------------------


class Rollback:
    """Compensating actions run newest-first when an op fails (see the module docstring)."""

    def __init__(self) -> None:
        self._actions: list[Callable[[], Any]] = []
        self.irreversible = False
        """True once an op made a change compensation cannot revert (a delete)."""

    def add(self, action: Callable[[], Any]) -> None:
        self._actions.append(action)

    def mark(self) -> int:
        return len(self._actions)

    def run(self, since: int = 0) -> bool:
        """Undo newest-first back to ``since``. Returns whether every compensating action
        succeeded (vacuously true when there was nothing to undo): the ``rolled_back`` a
        batch error reports, never assumed."""
        ok = True
        while len(self._actions) > since:
            action = self._actions.pop()
            try:
                action()
            except Exception:
                ok = False
        return ok

    def cannot_undo(self) -> None:
        """Record a change no action can revert: :meth:`run` then reports False."""
        self.irreversible = True

        def fail() -> None:
            raise RuntimeError("this change cannot be compensated")

        self.add(fail)

    def destroy_later(self, node: Any) -> None:
        self.add(lambda: node.destroy())

    def keep_display(self, parent: Any) -> None:
        """Restore ``parent``'s display/render node (SOP-style networks) on rollback."""
        for getter, setter in (("displayNode", "setDisplayFlag"), ("renderNode", "setRenderFlag")):
            fn = getattr(parent, getter, None)
            if not callable(fn):
                continue
            with contextlib.suppress(Exception):
                current = fn()
                if current is not None:
                    self.add(lambda current=current, setter=setter: getattr(current, setter)(True))


def _checked(restore: Callable[[], bool]) -> Callable[[], None]:
    """A restore function that returns False becomes an action that raises."""

    def action() -> None:
        if not restore():
            raise RuntimeError("restore failed")

    return action


# -- plans ----------------------------------------------------------------------------


@dataclass
class Op:
    """One step: ``op`` is a kind from :data:`OP_KINDS`, ``args`` its fields (the 1.4
    item for the tools that take items; anything that is not a dict fails when the op
    runs, as a malformed item did), ``opts`` the per-call options (``exact_type``,
    ``cook``, ``layout``, ``frame``)."""

    op: str
    args: Any
    id: str | None = None
    opts: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    ops: list[Op]
    partial: bool = False
    raw_errors: bool = False
    """Single-op 1.4 tools (``node_delete``, ``node_copy``, ``node_layout``,
    ``network_build``) raise the op's own error, not the ``items[i] (path)`` batch shape."""
    strict_refs: bool = False
    """``edit``: a ``$name`` that names no op of the plan is an error. The 1.4 tools pass
    path text through unchanged."""
    defer_rollback: bool = False
    """``edit``: when compensation could not revert everything (a delete ran), report
    ``rolled_back: null`` so the dispatcher fills in what undoing the whole group did."""
    tool_errors_only: bool = False
    """``parm_set`` (1.4): only a :class:`ToolError` is an op's failure; any other
    exception ends the call at once and the dispatcher's undo group rolls it back."""

    @property
    def declared(self) -> set[str]:
        return {op.id for op in self.ops if op.id}


@dataclass
class OpResult:
    index: int
    op: Op
    args: Any = None
    """The op's fields with ``$id`` references resolved."""
    node: Any = None
    path: str | None = None
    """What ``$id`` of this op resolves to."""
    nodes: list[Any] = field(default_factory=list)
    """Nodes the op touched, for the echo."""
    cook: bool = True
    """Whether the echo cooks ``nodes`` (``node`` ops and ``cook: false`` creates do not)."""
    extra: dict[str, Any] = field(default_factory=dict)
    data: Any = None
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class State:
    ctx: Any
    plan: Plan
    rollback: Rollback = field(default_factory=Rollback)
    ids: dict[str, str] = field(default_factory=dict)
    baselines: dict[int, dict[str, tuple[Any, ...]]] = field(default_factory=dict)
    """Session id of a created node -> its parm state right after ``createNode``."""
    pairs: dict[int, str] = field(default_factory=dict)
    """Session id of a created ``block_end`` -> the ``block_begin`` it was paired with."""
    extras: dict[int, dict[str, Any]] = field(default_factory=dict)
    """Session id of a created node -> ``deprecated``, ``notes``, ``side_effects``."""


@dataclass
class Result:
    plan: Plan
    results: list[OpResult]
    state: State

    @property
    def failures(self) -> dict[int, dict[str, Any]]:
        return {r.index: r.error for r in self.results if r.error is not None}

    def done(self) -> list[OpResult]:
        return [r for r in self.results if r.ok]

    def touched(self) -> list[tuple[Any, bool]]:
        """``(node, cook)`` per node the ops touched that still exists, in first-touch
        order; a node is cooked when any op that touched it cooks."""
        order: dict[int, list[Any]] = {}
        for res in self.done():
            for node in res.nodes:
                key = _session_id(node)
                if key is None:
                    continue
                if key in order:
                    order[key][1] = order[key][1] or res.cook
                else:
                    order[key] = [node, res.cook]
        return [(node, cook) for node, cook in order.values() if _session_id(node) is not None]


def _session_id(node: Any) -> int | None:
    """The node's session id, or None once it was deleted."""
    try:
        node.path()
        return int(node.sessionId())
    except Exception:
        return None


# -- $id references ----------------------------------------------------------------------


def resolve_ref(
    value: Any, ids: dict[str, str], declared: Iterable[str], field: str, *, strict: bool
) -> Any:
    """``$id`` -> the path op ``id`` produced; ``$id/rest`` -> that path + ``/rest``.

    A ``$name`` that no op declares is returned unchanged unless ``strict`` (``edit``),
    where it is ``invalid_argument``; a declared id whose op has not produced a node (it
    comes later, failed, or made none) is ``invalid_argument`` always."""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    head, _, rest = value[1:].partition("/")
    declared = set(declared)
    if head not in declared:
        if strict:
            known = ", ".join(f"${name}" for name in sorted(declared)) or "none"
            raise ToolError(
                "invalid_argument",
                f"{field} {value!r} names no op id (ids in this call: {known}).",
                hint=REF_HINT,
            )
        return value
    if head not in ids:
        raise ToolError(
            "invalid_argument",
            f"{field} {value!r} refers to op ${head}, which has not produced a node.",
            hint=REF_HINT,
        )
    base = ids[head]
    return f"{base.rstrip('/')}/{rest}" if rest else base


def resolve_args(
    kind: str, args: Any, ids: dict[str, str], declared: Iterable[str], *, strict: bool = False
) -> Any:
    """A copy of ``args`` with ``$id`` resolved in the op's path fields (:data:`REF_FIELDS`)."""
    if not isinstance(args, dict):
        return args
    declared = set(declared)
    if not declared and not strict:
        return args
    out = dict(args)
    for key in REF_FIELDS.get(kind, ()):
        value = out.get(key)
        if isinstance(value, list):
            out[key] = [
                resolve_ref(v, ids, declared, f"{key}[{i}]", strict=strict)
                for i, v in enumerate(value)
            ]
        elif value is not None:
            out[key] = resolve_ref(value, ids, declared, key, strict=strict)
    if kind == "create" and isinstance(out.get("inputs"), list):
        links = []
        for i, link in enumerate(out["inputs"]):
            if isinstance(link, dict) and "from" in link:
                link = {
                    **link,
                    "from": resolve_ref(
                        link["from"], ids, declared, f"inputs[{i}].from", strict=strict
                    ),
                }
            links.append(link)
        out["inputs"] = links
    return out


def path_of(kind: str, args: Any) -> Any:
    """What a failing op's batch error names (``items[i] (<path>)``)."""
    if not isinstance(args, dict):
        return None
    if kind == "create":
        parent, name = args.get("parent"), args.get("name")
        if isinstance(parent, str) and isinstance(name, str) and name:
            return f"{parent.rstrip('/')}/{name}"
        return parent
    if kind == "connect":
        return args.get("to")
    if kind == "set":
        return args.get("path") if args.get("path") is not None else args.get("node")
    if kind == "node":
        return args.get("path")
    if kind == "delete":
        paths = args.get("paths")
        if isinstance(paths, list) and len(paths) == 1:
            return paths[0]
        return args.get("path")
    if kind == "copy":
        return args.get("to_parent")
    if kind in ("layout", "build"):
        return args.get("parent")
    return None


# -- execute ---------------------------------------------------------------------------


def execute(plan: Plan, ctx: Any) -> Result:
    """Run ``plan`` on the main thread (inside the call's undo group). Returns per-op
    results; a failing op rolls the plan back and raises the batch error, or with
    ``partial`` rolls back that op only and records its error."""
    from .tools.nodes import batch_error

    state = State(ctx, plan)
    declared = plan.declared
    results: list[OpResult] = []
    for index, op in enumerate(plan.ops):
        mark = state.rollback.mark()
        args = op.args
        try:
            args = resolve_args(op.op, op.args, state.ids, declared, strict=plan.strict_refs)
            res = HANDLERS[op.op](args, op.opts, index, state)
            res.index, res.op, res.args = index, op, args
            if op.id and res.path:
                state.ids[op.id] = res.path
        except Exception as exc:
            if plan.tool_errors_only and not isinstance(exc, ToolError):
                raise
            if plan.raw_errors:
                state.rollback.run()
                raise
            path = path_of(op.op, args)
            if not plan.partial:
                ok = state.rollback.run()
                if not ok and plan.defer_rollback:
                    reported: Any = None  # the dispatcher's undo of the group decides
                else:
                    reported = ok
                raise batch_error(index, path, exc, rolled_back=reported) from exc
            ok = state.rollback.run(mark)
            error = batch_error(index, path, exc, rolled_back=ok).to_dict()
            res = OpResult(index, op, args, error=error)
        results.append(res)
    return Result(plan, results, state)


def watch(nodes: Iterable[Any]) -> None:
    """Have ``events`` record later changes to ``nodes``; after the call's own changes."""
    from .tools.nodes import watch_nodes

    watch_nodes(nodes)


# -- op handlers -----------------------------------------------------------------------
# Each takes (args with $id resolved, opts, index, state) and returns an OpResult; it
# raises on failure after registering compensation for what it changed.


def _op_create(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    import hou

    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    rollback = st.rollback
    parent = N.get_node(args.get("parent"), field="parent")
    N.ensure_can_hold_children(parent)
    type_name = args.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise N.bad_arg(f"items[{index}].type must be a non-empty string.")
    name = args.get("name")
    if name is not None:
        N.check_name(name)
        existing = parent.node(name)
        if existing is not None:
            free = N.unique_name(parent, name)
            raise ToolError(
                "name_collision",
                f"{existing.path()} already exists ({existing.type().name()}).",
                hint=f"Pick another name (e.g. {free!r}), omit name to let Houdini number it, "
                "or edit the existing node.",
                candidates=[free],
            )
    exact = N.arg_bool(opts, "exact_type", False)
    if opts.get("layout", "good_position") not in ("good_position", "none"):
        raise N.bad_arg("'layout' must be 'good_position' or 'none'.")
    node_type = N.resolve_type(parent, type_name, exact=exact)
    rollback.keep_display(parent)
    try:
        node = parent.createNode(node_type.name(), name, exact_type_name=True)
    except hou.PermissionError as exc:
        raise N.to_tool_error(exc, node=parent) from exc
    except hou.OperationFailed as exc:
        message = N.hou_message(exc)
        if "name" in message.lower() and "type" not in message.lower():
            raise N.bad_arg(
                f"Houdini rejected the node name {name!r}.",
                hint="Use letters, digits, '_', '.' and '-'.",
                hou_exception=N.hou_exception_text(exc),
            ) from exc
        raise N.type_not_found(parent, type_name, parent.childTypeCategory()) from exc
    rollback.destroy_later(node)
    st.baselines[node.sessionId()] = N.parm_state(node)
    note = N.deprecation_note(node.type())
    if note:
        extra = st.extras.setdefault(node.sessionId(), {})
        extra["deprecated"] = True
        key = node.type().nameWithCategory()
        if key not in N._DEPRECATION_NOTED:
            # Review 22 finding 10: 37 mountain creates repeated the same ~150 B note.
            N._DEPRECATION_NOTED.add(key)
            extra.setdefault("notes", []).append(note)
    parms = args.get("parms")
    pressed: dict[str, Any] = {}
    if parms:
        if not isinstance(parms, dict):
            raise N.bad_arg(f"items[{index}].parms must be an object.")
        # A {value, press: true} entry runs its callback after the plain values are set
        # and the inputs are wired, as clicking it in the parameter pane would (review 20 N2).
        plain = {k: v for k, v in parms.items() if not _is_press(v)}
        pressed = {k: v for k, v in parms.items() if _is_press(v)}
        _set_create_parms(node, plain, st)
    for link_index, link in enumerate(args.get("inputs") or []):
        if not isinstance(link, dict) or "from" not in link:
            raise N.bad_arg(
                f"items[{index}].inputs[{link_index}] must be {{index|name, from, output}}.",
            )
        if "index" in link and "name" in link:
            raise N.bad_arg(
                f"items[{index}].inputs[{link_index}]: pass index or name, not both.",
            )
        src = N.connect_source(link["from"], node, field="inputs.from")
        target = link.get("name") if "name" in link else link.get("index", link_index)
        dest_index = N.resolve_input_index(node, target)
        output = N.check_output_index(src, link.get("output", 0))
        N.connect(node, dest_index, src, output, None)
    N.set_flags(node, args.get("flags"))
    if pressed:
        _set_create_parms(node, pressed, st)
    begin = N.pair_block_end(node, rollback)
    if begin is not None:
        st.pairs[node.sessionId()] = begin.path()
    position = args.get("position")
    if position is not None:
        node.setPosition(N.arg_xy(position, f"items[{index}].position"))
    elif opts.get("layout", "good_position") == "good_position":
        with contextlib.suppress(Exception):
            node.moveToGoodPosition(move_inputs=False, move_outputs=False, move_unconnected=False)
    cook = N.arg_bool(opts, "cook", True)
    return OpResult(index, Op("create", args), node=node, path=node.path(), nodes=[node], cook=cook)


def _is_press(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("press") is True


def _set_create_parms(node: Any, parms: dict[str, Any], st: State) -> None:
    """Set create parms through the ``parm_set`` engine and keep what its results report:
    the skipped-callback note and a press's ``side_effects`` (review 20 N2)."""
    if not parms:
        return
    from .tools.parms import CREATE_CALLBACK_NOTE, set_parm_items

    results = set_parm_items(
        node, parms, st.ctx, animation="replace", callback_note=CREATE_CALLBACK_NOTE
    )
    extra = st.extras.setdefault(node.sessionId(), {})
    for result in results:
        for note in result.get("notes") or ():
            extra.setdefault("notes", []).append(note)
        if result.get("side_effects"):
            extra.setdefault("side_effects", {}).update(result["side_effects"])


def _op_set(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    from .tools import parms as P
    from .tools.nodes import get_node

    if not isinstance(args, dict):
        raise ToolError("invalid_argument", f"items[{index}] must be an object.")
    frame = opts.get("frame")
    if "parms" in args or "node" in args:
        # edit's node form: {node, parms: {name: value | item without path}}.
        unknown = set(args) - {"node", "parms", "animation"}
        if unknown:
            raise ToolError(
                "invalid_argument",
                f"A set op with node and parms takes no {sorted(unknown)}.",
                hint="Use {node, parms: {name: value}} or {path, value} (one parm), not both.",
            )
        node = get_node(args.get("node"), field="node")
        animation = args.get("animation") or "replace"
        rows = P.set_parm_items(
            node, args.get("parms"), st.ctx, animation=animation, rollback=st.rollback, frame=frame
        )
        return OpResult(
            index, Op("set", args), node=node, path=node.path(), nodes=[node], data=rows
        )
    unknown = set(args) - SET_ITEM_FIELDS
    if unknown:
        raise ToolError("invalid_argument", f"Unexpected item keys {sorted(unknown)}.")
    node, target = P.resolve_path(args.get("path"))
    st.rollback.add(_checked(P._snapshot(target)))  # never leave an item half-applied
    row = P._apply(node, target, args, frame=frame)
    return OpResult(index, Op("set", args), node=node, path=node.path(), nodes=[node], data=row)


def _op_connect(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    from .tools import nodes as N

    if not isinstance(args, dict) or "to" not in args or "from" not in args:
        raise N.bad_arg(f"items[{index}] needs 'from' (path or null) and 'to'.")
    dest = N.get_node(args.get("to"), field="to")
    N.ensure_editable(dest, "rewire")
    src_path = args.get("from")
    src = None if src_path is None else N.connect_source(src_path, dest)
    index_or_next = N.resolve_input_index(dest, args.get("to_input", 0))
    if src is None:
        if index_or_next == "next":
            raise N.bad_arg(
                "to_input 'next' cannot disconnect.",
                hint="Pass the input index or name to disconnect.",
            )
        used = N.connect(dest, index_or_next, None, 0, st.rollback)
        output = 0
    else:
        output = N.check_output_index(src, args.get("from_output", 0))
        used = N.connect(dest, index_or_next, src, output, st.rollback)
    names = list(dest.inputNames())
    extra = {
        "input": used,
        "input_name": names[used] if used < len(names) else f"input{used + 1}",
        "from": src.path() if src is not None else None,
        "from_output": output,
    }
    return OpResult(
        index, Op("connect", args), node=dest, path=dest.path(), nodes=[dest], extra=extra
    )


def _check_color(color: Any) -> tuple[float, float, float]:
    from .tools.nodes import bad_arg

    if (
        not isinstance(color, list)
        or len(color) != 3
        or not all(isinstance(c, int | float) and not isinstance(c, bool) for c in color)
    ):
        raise bad_arg("'color' must be [r, g, b] with 0-1 floats.")
    return float(color[0]), float(color[1]), float(color[2])


def plan_node_edit(item: Any, index: int, node: Any = None) -> dict[str, Any]:
    """Validate every field of one ``node`` op (a ``node_edit`` item) against ``node``
    without changing anything. Returns what :func:`_op_node` applies."""
    from .tools import nodes as N

    if not isinstance(item, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    if node is None:
        node = N.get_node(item.get("path"))
    lock = item.get("lock")
    if lock is not None:
        if not isinstance(lock, bool):
            raise N.bad_arg("'lock' must be a boolean.")
        if N.hda_block(node) is None:
            raise N.bad_arg(
                f"{node.path()} ({node.type().name()}) is not a digital asset; lock applies to HDAs.",
                hint="Use flags.bypass or the hard-lock flag for ordinary nodes.",
            )
        N.ensure_editable(node, "lock or unlock")
    else:
        N.ensure_editable(node, "edit")
    name = item.get("name")
    if name is not None and name != node.name():
        N.check_name(name)
        existing = node.parent().node(name)
        if existing is not None:
            free = N.unique_name(node.parent(), name)
            raise ToolError(
                "name_collision",
                f"{existing.path()} already exists.",
                hint=f"Pick another name, e.g. {free!r}.",
                candidates=[free],
            )
    else:
        name = None
    flags = dict(item.get("flags") or {})
    if item.get("bypass") is not None:
        flags["bypass"] = item["bypass"]
    N.check_flags(node, flags)
    color = item.get("color")
    rgb = _check_color(color) if color is not None else None
    comment = item.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise N.bad_arg("'comment' must be a string.")
    position = item.get("position")
    xy = N.arg_xy(position, "position") if position is not None else None
    spare_plan = None
    if item.get("spare_parms") is not None:
        from .tools.parms import plan_spare_parms

        # A locked asset's own instance takes spare parms (the wrangle "Create spare
        # parameters" button does that); nodes inside a locked asset were refused above.
        spare_plan = plan_spare_parms(node, item["spare_parms"])
    return {
        "node": node,
        "lock": lock,
        "name": name,
        "flags": flags,
        "rgb": rgb,
        "comment": comment,
        "xy": xy,
        "spare": spare_plan,
    }


def _op_node(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    """Apply one ``node`` op with ``lock`` last: ``lock: true`` runs
    ``matchCurrentDefinition()``, which discards edits made inside the asset;
    compensation cannot bring them back, so nothing may fail after it."""
    import hou

    from .tools import nodes as N

    plan = plan_node_edit(args, index)
    node, rollback = plan["node"], st.rollback
    old_path = node.path()
    try:
        if plan["name"] is not None:
            old_name = node.name()
            node.setName(plan["name"])
            rollback.add(lambda: node.setName(old_name))
    except hou.OperationFailed as exc:
        raise N.to_tool_error(exc, node=node, op="rename") from exc
    flags = plan["flags"]
    if flags:
        before = N.node_flags(node)
        rollback.keep_display(node.parent())

        def restore_flags(before: dict[str, bool] = before) -> None:
            for key, value in before.items():
                setter = getattr(node, N._FLAG_SETTERS.get(key, ""), None)
                if callable(setter):
                    setter(value)

        rollback.add(restore_flags)
        N.set_flags(node, flags)
    if plan["rgb"] is not None:
        old_color = node.color()
        node.setColor(hou.Color(plan["rgb"]))
        rollback.add(lambda: node.setColor(old_color))
    comment = plan["comment"]
    if comment is not None:
        old_comment = node.comment()
        node.setComment(comment)
        rollback.add(lambda: node.setComment(old_comment))
        with contextlib.suppress(Exception):
            node.setGenericFlag(hou.nodeFlag.DisplayComment, bool(comment))
    if plan["xy"] is not None:
        old_pos = node.position()
        node.setPosition(plan["xy"])
        rollback.add(lambda: node.setPosition(old_pos))
    spare = None
    if plan["spare"] is not None:
        from .tools.parms import apply_spare_parms

        spare = apply_spare_parms(node, plan["spare"], rollback)
    lock = plan["lock"]
    if lock is not None:
        was_locked = N._is_locked_hda(node)
        if lock and not was_locked:
            node.matchCurrentDefinition()
            rollback.add(lambda: node.allowEditingOfContents())
        elif not lock and was_locked:
            node.allowEditingOfContents()
            rollback.add(lambda: node.matchCurrentDefinition())
    extra: dict[str, Any] = {}
    if node.path() != old_path:
        extra["old_path"] = old_path
    if lock is not None:
        extra["hda"] = N.hda_block(node)
    if spare is not None:
        extra["spare_parms"] = spare
    return OpResult(
        index, Op("node", args), node=node, path=node.path(), nodes=[node], cook=False, extra=extra
    )


def delete_targets(paths: list[Any]) -> list[Any]:
    """The nodes a ``delete`` op removes, validated (no managers, nothing inside a locked
    asset), without the ones an ancestor in the list already takes."""
    from .tools import nodes as N

    nodes = []
    for path in paths:
        node = N.get_node(path, field="paths")
        if node.path() == "/" or node.parent() is None or node.parent().path() == "/":
            raise N.bad_arg(
                f"Refusing to delete the manager {node.path()}.",
                hint="Delete nodes inside it instead.",
            )
        N.ensure_editable(node, "delete")
        nodes.append(node)
    selected_paths = {n.path() for n in nodes}
    unique: list[Any] = []
    seen: set[str] = set()
    for node in nodes:
        path = node.path()
        if path in seen or any(path.startswith(p + "/") for p in selected_paths):
            continue
        seen.add(path)
        unique.append(node)
    return unique


def _op_delete(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    import contextlib as _c

    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    paths = N.arg_list(args, "paths")
    keep = N.arg_bool(args, "keep_connections", True)
    unique = delete_targets(paths)
    seen = {n.path() for n in unique}
    deleted: list[str] = []
    reconnected: list[dict[str, Any]] = []
    touched: dict[str, Any] = {}
    for node in unique:
        path = node.path()
        if keep:
            source = next((c for c in node.inputConnections() if c.inputIndex() == 0), None)
            if source is not None and source.inputNode() is not None:
                src, src_out = source.inputNode(), source.outputIndex()
                for conn in node.outputConnections():
                    dest = conn.outputNode()
                    if dest is None:
                        continue
                    with _c.suppress(Exception):
                        dest.setInput(conn.inputIndex(), src, src_out)
                        reconnected.append(
                            {"from": src.path(), "to": dest.path(), "input": conn.inputIndex()}
                        )
                        touched[dest.path()] = dest
        else:
            # destroy() splices input 0 through to the outputs by itself; cut them first.
            for conn in node.outputConnections():
                dest = conn.outputNode()
                if dest is not None:
                    with _c.suppress(Exception):
                        dest.setInput(conn.inputIndex(), None)
        st.rollback.cannot_undo()
        try:
            node.destroy()
        except Exception as exc:
            raise N.to_tool_error(exc, node=node) from exc
        deleted.append(path)
        touched.pop(path, None)
    alive = [n for p, n in touched.items() if p not in seen]
    data = {
        "deleted": deleted,
        "reconnected": [r for r in reconnected if r["to"] not in seen],
        "alive": alive,
        "any_reconnected": bool(reconnected),
    }
    return OpResult(index, Op("delete", args), nodes=alive, data=data)


def _op_copy(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    import hou

    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    paths = N.arg_list(args, "paths")
    dest = N.get_node(args.get("to_parent"), field="to_parent")
    N.ensure_can_hold_children(dest, "copy nodes into")
    names = args.get("names") or []
    if not isinstance(names, list) or len(names) > len(paths):
        raise N.bad_arg("'names' must be a list no longer than 'paths'.")
    for name in names:
        N.check_name(name, "names")
    if len(set(names)) != len(names):
        raise N.bad_arg("'names' must not repeat.")
    with_inputs = N.arg_bool(args, "with_inputs", True)
    offset = args.get("position_offset")
    offset_xy = N.arg_xy(offset, "position_offset") if offset is not None else None
    sources = [N.get_node(p, field="paths") for p in paths]
    category = dest.childTypeCategory()
    for src in sources:
        if src.type().category() != category:
            raise N.bad_arg(
                f"{src.path()} is {N.a_or_an(src.type().category().name())} node; {dest.path()} "
                f"holds {category.name()} nodes.",
                hint="Copy into a network of the same context.",
            )
    for name in names:
        existing = dest.node(name)
        if existing is not None:
            free = N.unique_name(dest, name, names)
            raise ToolError(
                "name_collision",
                f"{existing.path()} already exists.",
                hint=f"Pick another name, e.g. {free!r}, or omit names to let Houdini number copies.",
                candidates=[free],
            )
    try:
        copies = list(dest.copyItems(tuple(sources)))
    except hou.OperationFailed as exc:
        raise N.bad_arg(
            f"Houdini could not copy into {dest.path()}.",
            hint="All sources must share a context with to_parent.",
            hou_exception=N.hou_exception_text(exc),
        ) from exc
    copies = [c for c in copies if isinstance(c, hou.Node)]
    for copy in copies:
        st.rollback.destroy_later(copy)
    try:
        for copy, name in zip(copies, names, strict=False):
            try:
                copy.setName(name)
            except hou.OperationFailed as exc:
                raise N.to_tool_error(exc, node=copy, op="rename") from exc
        for copy in copies:
            if not with_inputs:
                for conn in copy.inputConnections():
                    copy.setInput(conn.inputIndex(), None)
            if offset_xy is not None:
                pos = copy.position()
                copy.setPosition((pos[0] + offset_xy[0], pos[1] + offset_xy[1]))
    except Exception as exc:
        raise N.to_tool_error(exc) from exc
    return OpResult(
        index,
        Op("copy", args),
        node=copies[0] if len(copies) == 1 else None,
        path=copies[0].path() if len(copies) == 1 else None,
        nodes=copies,
        data={"sources": sources, "copies": copies},
    )


def _op_layout(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    parent = N.get_node(args.get("parent"), field="parent")
    N.ensure_can_hold_children(parent, "lay out")
    mode = args.get("mode", "children")
    if mode not in ("children", "good_position"):
        raise N.bad_arg("'mode' must be 'children' or 'good_position'.")
    raw_paths = N.arg_list(args, "paths", required=False)
    nodes = [N.get_node(p, field="paths", relative_to=parent) for p in raw_paths]
    for node in nodes:
        if node.parent() != parent:
            raise N.bad_arg(
                f"{node.path()} is not a child of {parent.path()}.",
                hint="paths must be children of parent.",
            )
    moved = nodes or list(parent.children())
    before = [(n, n.position()) for n in moved]

    def restore() -> None:
        for node, position in before:
            node.setPosition(position)

    st.rollback.add(restore)
    if mode == "children":
        if nodes:
            parent.layoutChildren(items=tuple(nodes))
        else:
            parent.layoutChildren()
    else:
        for node in moved:
            node.moveToGoodPosition()
    return OpResult(
        index,
        Op("layout", args),
        node=parent,
        path=parent.path(),
        data={"parent": parent, "mode": mode, "moved": moved},
    )


def _op_build(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    import hou

    from .tools import network as W
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    parent = N.get_node(args.get("parent"), field="parent")
    prep = opts.get("prep") or W.prepare_build(parent, args)
    rollback = st.rollback
    mark = rollback.mark()
    data, replaced, existing = prep["data"], prep["replaced"], prep["existing"]
    rollback.keep_display(parent)
    originals: dict[str, Any] = {}
    for name in replaced:
        old = parent.node(name)
        temp = N.unique_name(parent, f"{name}_hp_replaced", set(data))
        old.setName(temp)
        rollback.add(lambda old=old, name=name: old.setName(name))
        originals[name] = old
    top_names = list(data)
    try:
        parent.setChildrenFromData(
            data, clear_content=False, force_item_creation=True, external_connections=True
        )
    except Exception as exc:
        for name in top_names:
            item = parent.item(name)
            if item is not None and name not in existing - set(replaced):
                with contextlib.suppress(Exception):
                    item.destroy()
        rollback.run(mark)
        if isinstance(exc, hou.PermissionError):
            raise N.to_tool_error(exc, node=parent) from exc
        raise N.bad_arg(
            f"Houdini could not build the network in {parent.path()}.",
            hint="Run with dry_run: true to validate; check names, types and parm values.",
            hou_exception=N.hou_exception_text(exc),
        ) from exc
    for name in top_names:
        item = parent.item(name)
        if item is not None:
            rollback.add(lambda item=item: item.destroy())
    verify = W._Problems()
    made = W._verify_level(data, parent, parent.path().rstrip("/") + "/", verify)
    if verify.items:
        rollback.run(mark)
        verify.raise_if_any()
    # Callbacks run after the whole build is wired, as clicking them would (review 20 N2),
    # and before replaced nodes are deleted, so a failed press still rolls back cleanly.
    try:
        pressed, side_effects = W._run_presses(parent, prep["press"], st.ctx)
    except Exception:
        rollback.run(mark)
        raise
    top_nodes = [parent.node(n) for n in top_names if parent.node(n) is not None]
    for name, old in originals.items():
        new = parent.node(name)
        if new is None:
            continue
        for conn in old.outputConnections():
            consumer = conn.outputNode()
            if consumer is None or consumer.parent() != parent or consumer.name() in data:
                continue
            consumer.setInput(conn.inputIndex(), new, conn.outputIndex())
        rollback.cannot_undo()
        old.destroy()
    if prep["layout"] and top_nodes:
        with contextlib.suppress(Exception):
            parent.layoutChildren(items=tuple(top_nodes))
    tag = prep["tag"]
    if tag:
        for node in top_nodes:
            node.setUserData(W.TAG_KEY, tag)
    out = {
        "parent": parent,
        "made": made,
        "top_nodes": top_nodes,
        "renamed": prep["renamed"],
        "replaced": replaced,
        "warnings": prep["warnings"],
        "pressed": pressed,
        "side_effects": side_effects,
        "notes": W._callback_notes(data, parent, prep["press"]),
    }
    return OpResult(
        index, Op("build", args), node=parent, path=parent.path(), nodes=top_nodes, data=out
    )


def _op_select(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    import hou

    from .tools import nodes as N
    from .tools.state import CONTEXT_CHANGED_NOTE, select_nodes

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    paths = args.get("paths")
    if not isinstance(paths, list):
        raise N.bad_arg("'paths' must be a list of node paths (an empty list clears).")
    nodes: list[Any] = []
    for i, path in enumerate(paths):
        node = N.get_node(path, field=f"paths[{i}]")
        if node not in nodes:
            nodes.append(node)
    before = list(hou.selectedNodes())

    def restore() -> None:
        hou.clearAllSelected()
        for node in before:
            with contextlib.suppress(Exception):
                node.setSelected(True, clear_all_selected=False)

    st.rollback.add(restore)
    # GUI: context_changed names the panes the selection takes into its network
    # (docs/parity.md G3).
    moved = select_nodes(nodes)
    data: dict[str, Any] = {"selected": [n.path() for n in hou.selectedNodes()]}
    if moved:
        data["context_changed"] = moved
        data["notes"] = [CONTEXT_CHANGED_NOTE]
    return OpResult(index, Op("select", args), data=data)


HANDLERS: dict[str, Callable[[Any, dict[str, Any], int, State], OpResult]] = {
    "create": _op_create,
    "delete": _op_delete,
    "connect": _op_connect,
    "set": _op_set,
    "node": _op_node,
    "copy": _op_copy,
    "layout": _op_layout,
    "build": _op_build,
    "select": _op_select,
}


# -- edit plans ------------------------------------------------------------------------


def parse_ops(ops: Any, *, partial: bool = False) -> Plan:
    """An ``edit`` plan from its ``ops``: kinds, ids and fields checked, nothing else."""
    from .tools.nodes import bad_arg, batch_error

    if not isinstance(ops, list) or not ops:
        raise bad_arg("'ops' must be a non-empty array of {op, ...} objects.")
    plan = Plan([], partial=partial, strict_refs=True, defer_rollback=True)
    seen: set[str] = set()
    for index, raw in enumerate(ops):
        try:
            plan.ops.append(_parse_op(raw, seen))
        except ToolError as exc:
            raise batch_error(index, path_of_raw(raw), exc, rolled_back=True) from exc
    return plan


def path_of_raw(raw: Any) -> Any:
    if isinstance(raw, dict) and raw.get("op") in OP_KINDS:
        return path_of(raw["op"], raw)
    return None


def _parse_op(raw: Any, seen: set[str]) -> Op:
    from .tools.nodes import bad_arg

    if not isinstance(raw, dict):
        raise bad_arg("Each op must be an object {op, ...}.")
    kind = raw.get("op")
    if kind not in OP_KINDS:
        import difflib

        raise bad_arg(
            f"Unknown op {kind!r}.",
            hint=f"Ops: {', '.join(OP_KINDS)}.",
            candidates=difflib.get_close_matches(str(kind), OP_KINDS, n=3, cutoff=0.0),
        )
    op_id = raw.get("id")
    if op_id is not None:
        if not isinstance(op_id, str) or not ID_RE.match(op_id):
            raise bad_arg(
                f"id {op_id!r} is not an identifier.",
                hint="An id is letters, digits and _ (not starting with a digit); later ops "
                "name it as $id.",
            )
        if op_id in seen:
            raise bad_arg(f"id {op_id!r} is used twice.", hint="Give every op its own id.")
        seen.add(op_id)
    fields = {k: v for k, v in raw.items() if k not in ("op", "id")}
    unknown = set(fields) - OP_FIELDS[kind]
    if unknown:
        raise bad_arg(
            f"A {kind} op takes no {', '.join(sorted(unknown))}.",
            hint=f"{kind} fields: {', '.join(sorted(OP_FIELDS[kind]))}.",
        )
    if kind == "delete":
        if "path" in fields and "paths" in fields:
            raise bad_arg("Pass path or paths to a delete op, not both.")
        if "path" in fields:
            fields["paths"] = [fields.pop("path")]
    opts = {k: fields.pop(k) for k in OPTION_FIELDS.get(kind, ()) if k in fields}
    if kind == "set" and "frame" in opts:
        from .tools.parms import _frame_arg

        opts["frame"] = _frame_arg(opts["frame"])
    return Op(kind, fields, op_id, opts)


# -- validate --------------------------------------------------------------------------

SIM_PARM_CATEGORIES = frozenset({"Sop", "Cop", "Cop2", "Chop", "Dop", "Top", "Vop"})
"""Categories whose type templates list every parm a new node has. Objects, ROPs and LOPs
get spare parms from creation scripts (a geo object's render properties), so their parms
are checked when the op runs, not in validation."""


@dataclass
class VNode:
    """A node an earlier op of the plan creates (or copies, or builds)."""

    path: str
    type: Any
    """Its ``hou.NodeType``, or None when validation cannot know it."""
    spare: set[str] = field(default_factory=set)


@dataclass
class Diagnostics:
    """What :func:`validate` found: ``rows`` (the plan with resolved paths) and
    ``problems`` (batch errors, in op order)."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    problems: list[ToolError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def raise_if_any(self) -> None:
        if not self.problems:
            return
        first = self.problems[0]
        if len(self.problems) > 1:
            listing = []
            for error in self.problems[:20]:
                row: dict[str, Any] = {
                    "item": error.detail.get("item"),
                    "code": error.code,
                    "message": error.message,
                }
                if error.hint:
                    row["hint"] = error.hint
                listing.append(row)
            first.message = f"{first.message} (+{len(self.problems) - 1} more problem(s))"
            first.args = (first.message,)
            first.detail = {**first.detail, "problems": listing}
        raise first


class _Skip(Exception):
    """An op depends on an op that already failed validation: report the root cause only."""


class Sim:
    """The scene as the plan's earlier ops leave it, without changing anything: real
    nodes (minus deleted and renamed ones) plus virtual nodes (:class:`VNode`)."""

    def __init__(self) -> None:
        self.virtual: dict[str, VNode] = {}
        self.gone: set[str] = set()
        """Real (``hou``) paths of nodes an earlier op deletes."""
        self.moved: dict[str, str] = {}
        """New path -> real path, for real nodes an earlier op renames."""
        self.vacated: set[str] = set()
        """Paths that named a renamed node before its rename."""
        self.spare: dict[str, set[str]] = {}
        """Real node path (as the plan names it) -> spare parm names an earlier op adds."""

    @staticmethod
    def _under(path: str, roots: Iterable[str]) -> bool:
        return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)

    def _real_path(self, path: str) -> str:
        for new, old in self.moved.items():
            if path == new or path.startswith(new + "/"):
                return old + path[len(new) :]
        return path

    def full(self, path: Any, field: str, relative_to: str | None = None) -> str:
        from .tools.nodes import bad_arg

        if not isinstance(path, str) or not path:
            raise bad_arg(f"'{field}' must be a non-empty node path.")
        if not path.startswith("/"):
            if relative_to is None:
                raise bad_arg(
                    f"'{field}' must be an absolute node path like /obj/geo1; got {path!r}.",
                    hint="Node paths start with '/'.",
                )
            return f"{relative_to.rstrip('/')}/{path}"
        return path.rstrip("/") or "/"

    def lookup(self, path: Any, field: str, relative_to: str | None = None) -> tuple[str, Any]:
        """``(path, VNode | hou.Node)`` for ``path`` as the plan has left it, or the one
        ``node_not_found``."""
        import hou

        from .tools._diag import missing_node_error

        full = self.full(path, field, relative_to)
        if full in self.virtual:
            return full, self.virtual[full]
        mapped = self._under(full, self.moved)
        if not mapped and self._under(full, self.vacated):
            raise missing_node_error(full)
        real = self._real_path(full)
        if self._under(real, self.gone):
            raise missing_node_error(full)
        node = hou.node(real)
        if node is None:
            raise missing_node_error(full)
        return full, node

    def children(self, parent_path: str) -> set[str]:
        """Names taken in ``parent_path`` once the earlier ops ran."""
        import hou

        base = parent_path.rstrip("/")
        names: set[str] = set()
        real = None if parent_path in self.virtual else hou.node(self._real_path(parent_path))
        if real is not None:
            real_base = real.path().rstrip("/")
            with contextlib.suppress(Exception):
                for child in real.children():
                    if self._under(f"{real_base}/{child.name()}", self.gone):
                        continue
                    if f"{base}/{child.name()}" in self.vacated:
                        continue
                    names.add(child.name())
        for new, old in self.moved.items():
            head, _, name = new.rpartition("/")
            if head == base and not self._under(old, self.gone):
                names.add(name)
        for path in self.virtual:
            head, _, name = path.rpartition("/")
            if head == base:
                names.add(name)
        return names

    def free_name(self, parent_path: str, base: str, taken: Iterable[str] = ()) -> str:
        used = self.children(parent_path) | set(taken)
        if base not in used:
            return base
        stem = base.rstrip("0123456789") or base
        i = 1
        while f"{stem}{i}" in used:
            i += 1
        return f"{stem}{i}"


def validate(plan: Plan, ctx: Any) -> Diagnostics:
    """Check every op of ``plan`` in order against the scene as the earlier ops leave it;
    changes nothing. Ops that depend on an op that failed are not reported again."""
    from .tools.nodes import batch_error

    sim = Sim()
    ids: dict[str, str] = {}
    failed: set[str] = set()
    declared = plan.declared
    diag = Diagnostics()
    for index, op in enumerate(plan.ops):
        args = op.args
        try:
            refs = _refs(op.op, op.args)
            if refs & failed:
                raise _Skip
            args = resolve_args(op.op, op.args, ids, declared, strict=plan.strict_refs)
            row = VALIDATORS[op.op](args, op.opts, index, sim)
        except _Skip:
            if op.id:
                failed.add(op.id)
            continue
        except Exception as exc:
            if op.id:
                failed.add(op.id)
            diag.problems.append(batch_error(index, path_of(op.op, args), exc, rolled_back=True))
            continue
        row = {"op": op.op, **({"id": op.id} if op.id else {}), **row}
        if op.id and row.get("path"):
            ids[op.id] = row["path"]
        diag.rows.append(row)
    return diag


def _refs(kind: str, args: Any) -> set[str]:
    """The ids ``args`` references in its path fields."""
    found: set[str] = set()
    if not isinstance(args, dict):
        return found

    def take(value: Any) -> None:
        if isinstance(value, str) and value.startswith("$"):
            found.add(value[1:].partition("/")[0])

    for key in REF_FIELDS.get(kind, ()):
        value = args.get(key)
        for v in value if isinstance(value, list) else [value]:
            take(v)
    if kind == "create":
        for link in args.get("inputs") or []:
            if isinstance(link, dict):
                take(link.get("from"))
    return found


def _category_of(target: Any) -> Any:
    """The child category of a real network node or a :class:`VNode`."""
    if isinstance(target, VNode):
        return target.type.childTypeCategory() if target.type is not None else None
    try:
        return target.childTypeCategory()
    except Exception:
        return None


def _type_of(target: Any) -> Any:
    if isinstance(target, VNode):
        return target.type
    try:
        return target.type()
    except Exception:
        return None


class _PathShim:
    """Enough of a node for ``type_not_found`` to name a parent that does not exist yet."""

    def __init__(self, path: str) -> None:
        self._path = path

    def path(self) -> str:
        return self._path


def _resolve_type_virtual(path: str, category: Any, type_name: str, exact: bool) -> Any:
    import hou

    from .tools.nodes import type_not_found

    node_type = None
    with contextlib.suppress(Exception):
        if exact:
            node_type = hou.nodeType(category, type_name)
        else:
            node_type = hou.preferredNodeType(f"{category.name()}/{type_name}")
            if node_type is None:
                node_type = hou.nodeType(category, type_name)
    if node_type is None:
        raise type_not_found(_PathShim(path), type_name, category)
    return node_type


def _template_names(node_type: Any) -> tuple[set[str], list[re.Pattern[str]]]:
    """Parm and component names a new node of ``node_type`` has, and multiparm patterns."""
    names: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    suffixes = {
        "XYZW": "xyzw", "XYWH": "xywh", "UVW": "uvw", "RGBA": "rgba",
    }  # fmt: skip

    def add(template: Any) -> None:
        try:
            name = template.name()
        except Exception:
            return
        children = []
        with contextlib.suppress(Exception):
            children = list(template.parmTemplates())
        if "#" in name:
            patterns.append(re.compile("^" + re.escape(name).replace("\\#", r"\d+") + r"\w*$"))
        else:
            names.add(name)
        try:
            size = int(template.numComponents())
        except Exception:
            size = 1
        if size > 1:
            scheme = str(getattr(template, "namingScheme", lambda: "")()).rsplit(".", 1)[-1]
            letters = suffixes.get(scheme)
            if letters:
                names.update(name + letters[i] for i in range(min(size, len(letters))))
            elif scheme == "MinMax":
                names.update((name + "min", name + "max"))
            elif scheme == "StartEnd":
                names.update((name + "start", name + "end"))
            elif scheme == "BeginEnd":
                names.update((name + "begin", name + "end"))
            else:
                names.update(f"{name}{i + 1}" for i in range(size))
        for child in children:
            add(child)

    with contextlib.suppress(Exception):
        for template in node_type.parmTemplateGroup().entries():
            add(template)
    return names, patterns


def _check_type_parm(node_type: Any, path: str, name: str, spare: set[str]) -> None:
    """Refuse a parm a new node of ``node_type`` will not have (only for
    :data:`SIM_PARM_CATEGORIES`; anything uncertain passes)."""
    import difflib

    if node_type is None or name in spare or ":" in name:
        return
    try:
        category = node_type.category().name()
    except Exception:
        return
    if category not in SIM_PARM_CATEGORIES:
        return
    names, patterns = _template_names(node_type)
    if not names or name in names or any(p.match(name) for p in patterns):
        return
    raise ToolError(
        "parm_not_found",
        f"No parm or parm tuple '{name}' on {path} ({node_type.name()}).",
        hint="Use node_type_info to list the type's parms.",
        candidates=difflib.get_close_matches(name, sorted(names), n=5, cutoff=0.6),
    )


def _check_parm(sim: Sim, path: str, target: Any, name: str) -> None:
    if isinstance(target, VNode):
        _check_type_parm(target.type, path, name, target.spare)
        return
    if name in sim.spare.get(path, set()):
        return
    from .tools.parms import resolve_name

    resolve_name(target, name)


def _check_value_fields(item: dict[str, Any], path: Any) -> None:
    """Exactly one value field per set item, as ``parm_set`` requires."""
    from .tools import parms as P

    press_after = item.get("press") is True and item.get("value") is not None
    present = [
        f
        for f in P.VALUE_FIELDS
        if (item.get(f) is True if f in P._FLAG_FIELDS else item.get(f) is not None)
        and not (press_after and f == "press")
    ]
    if len(present) != 1:
        got = ", ".join(present) if present else "none"
        raise ToolError(
            "invalid_argument",
            f"Each item takes exactly one of {', '.join(P.VALUE_FIELDS)}; got {got} for {path}.",
        )
    if (item.get("animation") or "replace") not in P.ANIMATION_MODES:
        raise ToolError(
            "invalid_argument", f"animation must be one of {', '.join(P.ANIMATION_MODES)}."
        )
    if (item.get("language") or "hscript") not in P.LANGUAGES:
        raise ToolError("invalid_argument", "language must be hscript or python.")


def _v_create(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N
    from .tools.parms import _item_from_spec

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    parent_path, parent = sim.lookup(args.get("parent"), "parent")
    if not isinstance(parent, VNode):
        N.ensure_can_hold_children(parent)
    category = _category_of(parent)
    if category is None:
        raise N.bad_arg(
            f"{parent_path} is not a network and cannot contain nodes.",
            hint="Pass a network such as /obj, a geo object or a subnet as parent.",
        )
    type_name = args.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise N.bad_arg(f"items[{index}].type must be a non-empty string.")
    exact = N.arg_bool(opts, "exact_type", False)
    N.arg_bool(opts, "cook", True)
    if opts.get("layout", "good_position") not in ("good_position", "none"):
        raise N.bad_arg("'layout' must be 'good_position' or 'none'.")
    if isinstance(parent, VNode):
        node_type = _resolve_type_virtual(parent_path, category, type_name, exact)
    else:
        node_type = N.resolve_type(parent, type_name, exact=exact)
    name = args.get("name")
    base = parent_path.rstrip("/")
    if name is not None:
        N.check_name(name)
        if name in sim.children(parent_path):
            free = sim.free_name(parent_path, name)
            raise ToolError(
                "name_collision",
                f"{base}/{name} already exists.",
                hint=f"Pick another name (e.g. {free!r}), omit name to let Houdini number it, "
                "or edit the existing node.",
                candidates=[free],
            )
        predicted = False
    else:
        core = node_type.nameComponents()[2] or node_type.name()
        name = sim.free_name(parent_path, f"{core}1")
        predicted = True
    path = f"{base}/{name}"
    vnode = VNode(path, node_type)
    parms = args.get("parms")
    if parms:
        if not isinstance(parms, dict):
            raise N.bad_arg(f"items[{index}].parms must be an object.")
        for parm_name, spec in parms.items():
            _item_from_spec(parm_name, spec, "replace")
            _check_type_parm(node_type, path, parm_name, set())
    inputs = args.get("inputs") or []
    if not isinstance(inputs, list):
        raise N.bad_arg(f"items[{index}].inputs must be a list.")
    wires = []
    for link_index, link in enumerate(inputs):
        if not isinstance(link, dict) or "from" not in link:
            raise N.bad_arg(
                f"items[{index}].inputs[{link_index}] must be {{index|name, from, output}}.",
            )
        if "index" in link and "name" in link:
            raise N.bad_arg(f"items[{index}].inputs[{link_index}]: pass index or name, not both.")
        target = link.get("name") if "name" in link else link.get("index", link_index)
        src_path, src = _wire_source(sim, link["from"], path, parent_path, "inputs.from")
        _check_input(vnode, path, target)
        _check_output(src, src_path, link.get("output", 0))
        wires.append(src_path)
    flags = args.get("flags")
    if flags is not None:
        _check_flag_shape(flags)
    if args.get("position") is not None:
        N.arg_xy(args["position"], f"items[{index}].position")
    sim.virtual[path] = vnode
    row: dict[str, Any] = {"path": path, "type": node_type.name()}
    if predicted:
        row["predicted"] = True
    if wires:
        row["inputs"] = wires
    return row


def _check_flag_shape(flags: Any) -> None:
    from .tools.nodes import SETTABLE_FLAGS, bad_arg

    if not isinstance(flags, dict):
        raise bad_arg("'flags' must be an object of booleans.")
    for name, value in flags.items():
        if name not in SETTABLE_FLAGS:
            raise bad_arg(
                f"Unknown flag {name!r}.", hint=f"Settable flags: {', '.join(SETTABLE_FLAGS)}."
            )
        if not isinstance(value, bool):
            raise bad_arg(f"Flag {name!r} must be a boolean.")


def _wire_source(
    sim: Sim, value: Any, dest_path: str, parent_path: str, field: str
) -> tuple[str, Any]:
    src_path, src = sim.lookup(value, field, relative_to=parent_path)
    if src_path.rpartition("/")[0] != parent_path.rstrip("/"):
        raise ToolError(
            "invalid_input",
            f"{src_path} and {dest_path} are in different networks.",
            hint="Connect nodes that share a parent; use an object_merge SOP to bring "
            "geometry across networks.",
        )
    if src_path == dest_path:
        raise ToolError(
            "invalid_input",
            f"{dest_path} cannot be wired into itself.",
            hint="Wire an upstream node into it instead.",
        )
    return src_path, src


def _check_input(dest: Any, dest_path: str, to_input: Any) -> Any:
    """``to_input`` against a real node (as ``node_connect`` checks it) or a new node's
    type (indices only; input names need the node)."""
    from .tools import nodes as N

    if not isinstance(dest, VNode):
        return N.resolve_input_index(dest, to_input)
    if to_input is None:
        return 0
    if isinstance(to_input, bool):
        raise N.bad_arg("to_input must be an index, an input name or 'next'.")
    if isinstance(to_input, str) and to_input.isdigit():
        to_input = int(to_input)
    if isinstance(to_input, int):
        max_inputs = dest.type.maxNumInputs() if dest.type is not None else None
        if to_input < 0 or (max_inputs is not None and to_input >= max(max_inputs, 0)):
            raise ToolError(
                "invalid_input",
                f"{dest_path} has no input {to_input} (it takes {max_inputs}).",
                hint="Check the type's inputs with node_type_info.",
            )
        return to_input
    if isinstance(to_input, str):
        return to_input  # "next" or an input name: checked when the op runs
    raise N.bad_arg("to_input must be an index, an input name or 'next'.")


def _check_output(src: Any, src_path: str, output: Any) -> None:
    from .tools import nodes as N

    if not isinstance(src, VNode):
        N.check_output_index(src, output)
        return
    if output is None:
        return
    if not isinstance(output, int) or isinstance(output, bool) or output < 0:
        raise N.bad_arg("Output index must be a non-negative integer.")
    if src.type is None:
        return
    with contextlib.suppress(Exception):
        count = int(src.type.maxNumOutputs())
        if output >= max(count, 1):
            raise ToolError(
                "invalid_input",
                f"{src_path} has no output {output} (it has {count}).",
                hint=f"Valid outputs are 0..{max(count, 1) - 1}.",
            )


def _v_delete(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    N.arg_bool(args, "keep_connections", True)
    paths = N.arg_list(args, "paths")
    removed = []
    for path in paths:
        full, target = sim.lookup(path, "paths")
        if isinstance(target, VNode):
            for key in [p for p in sim.virtual if sim._under(p, [full])]:
                del sim.virtual[key]
        else:
            if full == "/" or full.count("/") < 2:
                raise N.bad_arg(
                    f"Refusing to delete the manager {full}.",
                    hint="Delete nodes inside it instead.",
                )
            N.ensure_editable(target, "delete")
            sim.gone.add(target.path())
        removed.append(full)
    return {"paths": removed}


def _v_connect(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict) or "to" not in args or "from" not in args:
        raise N.bad_arg(f"items[{index}] needs 'from' (path or null) and 'to'.")
    dest_path, dest = sim.lookup(args.get("to"), "to")
    if not isinstance(dest, VNode):
        N.ensure_editable(dest, "rewire")
    parent_path = dest_path.rpartition("/")[0] or "/"
    to_input = _check_input(dest, dest_path, args.get("to_input", 0))
    row: dict[str, Any] = {"to": dest_path, "to_input": to_input}
    if args.get("from") is None:
        if to_input == "next":
            raise N.bad_arg(
                "to_input 'next' cannot disconnect.",
                hint="Pass the input index or name to disconnect.",
            )
        row["from"] = None
    else:
        src_path, src = _wire_source(sim, args["from"], dest_path, parent_path, "from")
        _check_output(src, src_path, args.get("from_output", 0))
        row["from"] = src_path
    row["path"] = dest_path
    return row


def _v_set(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools.parms import _item_from_spec

    if not isinstance(args, dict):
        raise ToolError("invalid_argument", f"items[{index}] must be an object.")
    if "parms" in args or "node" in args:
        node_path, node = sim.lookup(args.get("node"), "node")
        parms = args.get("parms")
        if not isinstance(parms, dict) or not parms:
            raise ToolError("invalid_argument", "parms must be an object {name: value}.")
        animation = args.get("animation") or "replace"
        for name, spec in parms.items():
            _item_from_spec(name, spec, animation)
            _check_parm(sim, node_path, node, name)
        return {"path": node_path, "parms": list(parms)}
    unknown = set(args) - SET_ITEM_FIELDS
    if unknown:
        raise ToolError("invalid_argument", f"Unexpected item keys {sorted(unknown)}.")
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", "Parm paths must be non-empty strings.")
    text = path.strip().rstrip("/")
    if not text.startswith("/") or text.count("/") < 2:
        raise ToolError(
            "invalid_argument",
            f"{path!r} is not an absolute parm path.",
            hint="Use <node path>/<parm name>, e.g. /obj/geo1/box1/size or /obj/geo1/box1/sizex.",
        )
    node_path, _, name = text.rpartition("/")
    node_path, node = sim.lookup(node_path, "path")
    _check_value_fields(args, text)
    _check_parm(sim, node_path, node, name)
    return {"path": f"{node_path}/{name}"}


def _v_node(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    path, target = sim.lookup(args.get("path"), "path")
    parent_path = path.rpartition("/")[0] or "/"
    name = args.get("name")
    spare_names = _spare_add_names(args.get("spare_parms"))
    if isinstance(target, VNode):
        if name is not None:
            N.check_name(name)
        flags = dict(args.get("flags") or {})
        if args.get("bypass") is not None:
            flags["bypass"] = args["bypass"]
        _check_flag_shape(flags)
        if args.get("color") is not None:
            _check_color(args["color"])
        if args.get("comment") is not None and not isinstance(args["comment"], str):
            raise N.bad_arg("'comment' must be a string.")
        if args.get("position") is not None:
            N.arg_xy(args["position"], "position")
        if args.get("lock") is not None:
            raise N.bad_arg(
                f"{path} is created by this call; lock applies to an existing digital asset.",
                hint="Lock or unlock the asset in a later call.",
            )
        target.spare |= spare_names
    else:
        plan_node_edit(args, index, node=target)
        sim.spare.setdefault(path, set()).update(spare_names)
    row: dict[str, Any] = {"path": path}
    if name is not None and name != path.rpartition("/")[2]:
        if name in sim.children(parent_path):
            free = sim.free_name(parent_path, name)
            raise ToolError(
                "name_collision",
                f"{parent_path.rstrip('/')}/{name} already exists.",
                hint=f"Pick another name, e.g. {free!r}.",
                candidates=[free],
            )
        new_path = f"{parent_path.rstrip('/')}/{name}"
        if isinstance(target, VNode):
            for key in [p for p in sim.virtual if p == path or p.startswith(path + "/")]:
                vnode = sim.virtual.pop(key)
                vnode.path = new_path + key[len(path) :]
                sim.virtual[vnode.path] = vnode
        else:
            sim.moved[new_path] = target.path()
            sim.vacated.add(path)
            sim.spare[new_path] = sim.spare.pop(path, set())
        row = {"path": new_path, "old_path": path}
    return row


def _spare_add_names(spec: Any) -> set[str]:
    if not isinstance(spec, dict):
        return set()
    return {
        entry["name"]
        for entry in spec.get("add") or []
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _v_copy(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    paths = N.arg_list(args, "paths")
    dest_path, dest = sim.lookup(args.get("to_parent"), "to_parent")
    if not isinstance(dest, VNode):
        N.ensure_can_hold_children(dest, "copy nodes into")
    category = _category_of(dest)
    names = args.get("names") or []
    if not isinstance(names, list) or len(names) > len(paths):
        raise N.bad_arg("'names' must be a list no longer than 'paths'.")
    for name in names:
        N.check_name(name, "names")
    if len(set(names)) != len(names):
        raise N.bad_arg("'names' must not repeat.")
    N.arg_bool(args, "with_inputs", True)
    if args.get("position_offset") is not None:
        N.arg_xy(args["position_offset"], "position_offset")
    out: list[str] = []
    taken: set[str] = set()
    for i, path in enumerate(paths):
        src_path, src = sim.lookup(path, "paths")
        src_type = _type_of(src)
        if category is not None and src_type is not None and src_type.category() != category:
            raise N.bad_arg(
                f"{src_path} is {N.a_or_an(src_type.category().name())} node; {dest_path} "
                f"holds {category.name()} nodes.",
                hint="Copy into a network of the same context.",
            )
        if i < len(names):
            name = names[i]
            if name in sim.children(dest_path):
                free = sim.free_name(dest_path, name, names)
                raise ToolError(
                    "name_collision",
                    f"{dest_path.rstrip('/')}/{name} already exists.",
                    hint=f"Pick another name, e.g. {free!r}, or omit names to let Houdini "
                    "number copies.",
                    candidates=[free],
                )
        else:
            name = sim.free_name(dest_path, src_path.rpartition("/")[2], taken)
        taken.add(name)
        copy_path = f"{dest_path.rstrip('/')}/{name}"
        sim.virtual[copy_path] = VNode(copy_path, src_type)
        out.append(copy_path)
    row: dict[str, Any] = {"paths": out}
    if len(out) == 1:
        row["path"] = out[0]
    return row


def _v_layout(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    parent_path, parent = sim.lookup(args.get("parent"), "parent")
    if not isinstance(parent, VNode):
        N.ensure_can_hold_children(parent, "lay out")
    if args.get("mode", "children") not in ("children", "good_position"):
        raise N.bad_arg("'mode' must be 'children' or 'good_position'.")
    for path in N.arg_list(args, "paths", required=False):
        full, _node = sim.lookup(path, "paths", relative_to=parent_path)
        if full.rpartition("/")[0] != parent_path.rstrip("/"):
            raise N.bad_arg(
                f"{full} is not a child of {parent_path}.", hint="paths must be children of parent."
            )
    return {"path": parent_path}


def _v_build(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    import json

    import hou

    from .tools import network as W
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    parent_path, parent = sim.lookup(args.get("parent"), "parent")
    if isinstance(parent, VNode):
        category = _category_of(parent)
        if category is None:
            raise N.bad_arg(f"{parent_path} is not a network and cannot contain nodes.")
        data = args.get("data")
        if not isinstance(data, dict) or not data:
            raise N.bad_arg(
                "'data' must be a non-empty object of node name -> node data.",
                hint="Pass the 'data' field of network_describe, e.g. {box1: {type: box}}.",
            )
        data = json.loads(json.dumps(data))
        problems = W._Problems()
        plan_rows: list[dict[str, Any]] = []
        W._validate_level(
            data,
            category=category,
            container=None,
            prefix=parent_path.rstrip("/") + "/",
            problems=problems,
            plan=plan_rows,
            warnings=[],
            existing_names=set(),
        )
        problems.raise_if_any()
        renamed: dict[str, str] = {}
    else:
        prep = W.prepare_build(parent, args)
        plan_rows, renamed = prep["plan"], prep["renamed"]
    built = []
    for entry in plan_rows:
        path = entry["name"]
        holder = sim.virtual.get(path.rpartition("/")[0])
        category = None
        if holder is not None:
            category = _category_of(holder)
        else:
            real = hou.node(path.rpartition("/")[0] or "/")
            category = _category_of(real) if real is not None else None
        node_type = None
        with contextlib.suppress(Exception):
            node_type = hou.nodeType(category, entry["type"]) if category is not None else None
        sim.virtual[path] = VNode(path, node_type)
        built.append(path)
    row: dict[str, Any] = {"path": parent_path, "nodes": built}
    if renamed:
        row["renamed"] = renamed
    return row


def _v_select(args: Any, opts: dict[str, Any], index: int, sim: Sim) -> dict[str, Any]:
    from .tools import nodes as N

    if not isinstance(args, dict):
        raise N.bad_arg(f"items[{index}] must be an object.")
    paths = args.get("paths")
    if not isinstance(paths, list):
        raise N.bad_arg("'paths' must be a list of node paths (an empty list clears).")
    return {"paths": [sim.lookup(p, f"paths[{i}]")[0] for i, p in enumerate(paths)]}


VALIDATORS: dict[str, Callable[[Any, dict[str, Any], int, Sim], dict[str, Any]]] = {
    "create": _v_create,
    "delete": _v_delete,
    "connect": _v_connect,
    "set": _v_set,
    "node": _v_node,
    "copy": _v_copy,
    "layout": _v_layout,
    "build": _v_build,
    "select": _v_select,
}


# -- the edit echo ------------------------------------------------------------------------


def node_problems(node: Any, cook: bool) -> dict[str, Any]:
    from .tools._diag import cheap_cook_problems, collect_problems

    return cheap_cook_problems(node) if cook else collect_problems(node, cook=False)


def echo(result: Result, mode: str) -> dict[str, Any]:
    """The ``edit`` result: ``results`` (one row per op: ``op``, ``id``, what it did) and
    ``nodes`` (the 1.4 summary row per touched node, cooked once; ``full`` adds flags
    and messages). Identical error lists after the first become ``errors_same_as`` in
    summary mode."""
    from .tools import nodes as N

    rows: list[dict[str, Any]] = []
    for res in result.results:
        row: dict[str, Any] = {"op": res.op.op}
        if res.op.id:
            row["id"] = res.op.id
        if res.error is not None:
            row["error"] = res.error
        else:
            row.update(_op_row(res, mode, result.state))
        rows.append(row)
    blocks: list[dict[str, Any]] = []
    for node, cook in result.touched():
        problems = node_problems(node, cook)
        if mode == "summary":
            blocks.append(N.summary_block(node, problems))
        else:
            block = {"path": node.path(), "name": node.name(), "type": node.type().name()}
            block["flags"] = N.node_flags(node)
            block.update(problems)
            if "cook_time_ms" in block:
                block["cook_ms"] = block.pop("cook_time_ms")
            blocks.append(block)
    if mode == "summary":
        N.collapse_problems(blocks)
    out: dict[str, Any] = {"results": rows, "nodes": blocks}
    if result.failures:
        out["failed"] = len(result.failures)
    return out


def _short_parm_row(row: dict[str, Any]) -> dict[str, Any]:
    """A set row for ``return: summary``: the parm path, its value as Houdini holds it
    (menus as tokens), and only what is notable (expression, keys written, notes, a
    press's side effects)."""
    keep = (
        "path", "value", "raw", "expression", "expressions", "keyed", "pressed",
        "side_effects", "outputs_summary", "notes",
    )  # fmt: skip
    out = {k: row[k] for k in keep if k in row}
    if row.get("wrote_keyframe"):
        out["wrote_keyframe"] = True
    return out


def _op_row(res: OpResult, mode: str, st: State) -> dict[str, Any]:
    from .tools import nodes as N

    kind, data, full = res.op.op, res.data, mode == "full"
    if kind == "create":
        node = res.node
        row: dict[str, Any] = {"path": node.path()}
        sid = node.sessionId()
        if sid in st.pairs:
            row["paired_with"] = st.pairs[sid]
        N.add_create_extras(row, st.extras.get(sid))
        if full:
            keep = N.call_edited_parms(node, st.baselines.get(sid, {}), res.args.get("parms") or {})
            row["parms"] = [r for r in N.parm_rows(node, False) if r["name"] in keep]
        return row
    if kind == "set":
        if isinstance(data, list):  # the node form
            row = {"path": res.node.path()}
            if full:
                row["parms"] = data
            else:
                row["values"] = {r["name"]: r.get("value") for r in data}
                notes = [n for r in data for n in r.get("notes") or ()]
                effects = {k: v for r in data for k, v in (r.get("side_effects") or {}).items()}
                if notes:
                    row["notes"] = notes
                if effects:
                    row["side_effects"] = effects
            return row
        return dict(data) if full else _short_parm_row(data)
    if kind == "connect":
        extra = res.extra
        row = {"path": res.node.path(), "input": extra["input"], "from": extra["from"]}
        if full:
            row.update(input_name=extra["input_name"], from_output=extra["from_output"])
        elif extra["from_output"]:
            row["from_output"] = extra["from_output"]
        return row
    if kind == "node":
        node = res.node
        row = {"path": node.path(), **res.extra}
        if full:
            row["comment"] = node.comment()
            row["position"] = N._round(node.position())
            row["color"] = N._round(node.color().rgb())
        return row
    if kind == "delete":
        row = {"deleted": data["deleted"]}
        if data["reconnected"]:
            row["reconnected"] = data["reconnected"]
        return row
    if kind == "copy":
        row = {"paths": [c.path() for c in data["copies"]]}
        if full:
            row["sources"] = [s.path() for s in data["sources"]]
        return row
    if kind == "layout":
        return {"path": data["parent"].path(), "mode": data["mode"], "count": len(data["moved"])}
    if kind == "build":
        parent = data["parent"]
        base = parent.path().rstrip("/")
        row = {"path": parent.path(), "created": [n.path() for n in data["top_nodes"]]}
        if full or len(data["made"]) != len(data["top_nodes"]):
            row["created_count"] = len(data["made"])
        if data["renamed"]:
            row["renamed"] = {f"{base}/{k}": f"{base}/{v}" for k, v in data["renamed"].items()}
        if data["replaced"]:
            row["replaced"] = [f"{base}/{n}" for n in data["replaced"]]
        for key in ("warnings", "pressed", "side_effects", "notes"):
            if data[key]:
                row[key] = data[key]
        return row
    if kind == "select":
        return dict(data)
    return {}
