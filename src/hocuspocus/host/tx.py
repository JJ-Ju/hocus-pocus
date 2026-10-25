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
* :func:`execute` runs the plan on the main thread, inside the one undo group the
  dispatcher opened for the call (``HocusPocus: edit <n> ops`` for ``edit``). Houdini
  refuses ``performUndo`` inside an open group, so a failing op is reverted by
  compensation (:class:`Rollback`), newest first; with ``partial`` only that op's own
  changes are reverted and the rest stand (``stop``: the ops after it do not run).
  ``rolled_back`` is what really happened: a delete cannot be compensated, so ``edit``
  then leaves the answer to the dispatcher, which undoes the whole group after it closes
  (``host/undo.py``).
* Validation is the run itself (BIBLE D56): every op is checked by running it against the
  scene the earlier ops left. ``edit`` (``Plan.collect``) does not stop at a failing op: it
  reverts that op, runs the rest in *check mode* (:func:`checking`: no ``press``
  callbacks, no selection change, a delete renames the node out of the way, ``lock:
  true`` and a build's ``replace`` keep the old contents) to report their problems too,
  then compensates everything and raises the first problem with all of them in
  ``detail.problems``. :func:`dry_run` is check mode from the first op, with undo off and
  events muted, compensated whether or not it failed: a dry run and the run agree by
  construction.
* :func:`echo` is the ``edit`` result: by default one compact row per touched node
  (``path``, ``type``, and only the notable problems; each cooked once at the end) with the
  ops' results folded in and an ``ids`` map; ``return: ops`` adds one row per op;
  ``return: full`` gives the 1.4 full shapes (flags, parm rows with long strings elided).
  ``edit`` cooks off the call's main-thread work (:func:`cook_targets`, D58).

Pure Python apart from the op handlers, which import ``hou`` and the tool families lazily
(the families import this module).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from hocuspocus.tools.errors import ToolError

OP_KINDS = ("create", "delete", "connect", "set", "node", "copy", "layout", "build", "select")

SET_ITEM_FIELDS = frozenset(
    (
        "path", "value", "expression", "language", "keyframe", "keyframes", "channel_ref",
        "ramp", "multiparm_count", "revert_to_default", "press", "animation", "patch",
        "value_file",
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
            "path",
        )
    ),  # fmt: skip
    "delete": frozenset(("paths", "path", "keep_connections")),
    "connect": frozenset(("from", "from_output", "to", "to_input", "path")),
    "set": SET_ITEM_FIELDS | {"frame", "node", "parms"},
    "node": frozenset(
        (
            "path",
            "node",
            "name",
            "flags",
            "color",
            "comment",
            "position",
            "lock",
            "bypass",
            "spare_parms",
        )
    ),  # fmt: skip
    "copy": frozenset(("paths", "path", "to_parent", "names", "with_inputs", "position_offset")),
    "layout": frozenset(("parent", "path", "paths", "mode")),
    "build": frozenset(("parent", "path", "data", "on_name_collision", "layout", "tag", "press")),
    "select": frozenset(("paths", "path")),
}
"""The fields each ``edit`` op takes besides ``op`` and ``id``. ``path`` is every op's
canonical name for the node it acts on (review 26 P1 friction 6; :data:`PATH_ALIASES`)."""

PATH_ALIASES: dict[str, str] = {
    "connect": "to",
    "layout": "parent",
    "build": "parent",
    "copy": "paths",
    "select": "paths",
    "delete": "paths",
}
"""``edit`` ops whose node field has its 1.4 name: ``path`` is read as that field (a list
field takes ``[path]``). ``create``'s ``path`` is the new node's (``parent`` + ``name``), a
``node`` op's ``node`` is its ``path``, and a ``set`` op's ``path`` with ``parms`` is its
``node``."""

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
        def destroy() -> None:
            if _session_id(node) is not None:  # a later op may have deleted it already
                node.destroy()

        self.add(destroy)

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
    sent_as: dict[str, str] = field(default_factory=dict)
    """Canonical field -> the key the caller wrote (``path`` read as ``parent``, ``to``...):
    errors name the key that was sent (:func:`as_sent`)."""


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
    label: str = "items"
    """What a batch error calls the argument: ``items[i] (<path>)`` for the 1.4 tools,
    ``ops[i].<field>`` for ``edit`` (review 25 papercut 3)."""
    collect: bool = False
    """``edit`` (D56): a failing op does not end the run; it is reverted, the rest run in
    check mode, and every problem is raised together after the whole plan is compensated."""
    stop: bool = False
    """``edit`` ``partial: "stop"`` (D57): keep the ops before the first failing op; the
    ops after it do not run."""
    dry_run: bool = False
    """Check mode from the first op (:func:`dry_run`)."""

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
    data_row: dict[str, Any] | None = None
    """A dry run's row for the op (:func:`dry_run`), taken when the op ran."""

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
    checking: bool = False
    """Check mode (:func:`checking`): ops run for real but leave out what compensation
    could not take back (callbacks, selection, deletes, ``lock: true``)."""
    stopped: int | None = None
    """``partial: "stop"``: the index of the op that failed; later ops do not run."""


_ACTIVE: list[State] = []
"""The states of the plans running now (innermost last): :func:`checking` reads it."""


def checking() -> bool:
    """Whether the op running now is in check mode (``dry_run``, or the ops after a failing
    one in ``edit``): a ``press`` then sets the value but runs no callback."""
    return bool(_ACTIVE) and _ACTIVE[-1].checking


@dataclass
class Result:
    plan: Plan
    results: list[OpResult]
    state: State
    rows: dict[int, dict[str, Any]] = field(default_factory=dict)
    """Session id -> the node's row in the :func:`echo` (for :func:`patch_rows`)."""

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
            raise at_field(
                ToolError(
                    "invalid_argument",
                    f"{field} {value!r} names no op id (ids in this call: {known}).",
                    hint=REF_HINT,
                ),
                field,
            )
        return value
    if head not in ids:
        raise at_field(
            ToolError(
                "invalid_argument",
                f"{field} {value!r} refers to op ${head}, which has not produced a node.",
                hint=REF_HINT,
            ),
            field,
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
    ``partial`` rolls back that op only and records its error (``stop``: and runs no
    later op). With ``collect`` (``edit``) the ops after a failing one still run, in
    check mode, so the error lists every problem (:func:`combined_error`)."""
    from .tools.nodes import batch_error

    state = State(ctx, plan, checking=plan.dry_run)
    declared = plan.declared
    results: list[OpResult] = []
    problems: list[ToolError] = []
    failed: set[str] = set()
    _ACTIVE.append(state)
    try:
        for index, op in enumerate(plan.ops):
            if state.stopped is not None:
                break
            if plan.collect and _refs(op.op, op.args) & failed:
                # Depends on an op that failed: its root cause is reported once.
                if op.id:
                    failed.add(op.id)
                continue
            mark = state.rollback.mark()
            args = op.args
            try:
                args = resolve_args(op.op, op.args, state.ids, declared, strict=plan.strict_refs)
                res = HANDLERS[op.op](args, op.opts, index, state)
                res.index, res.op, res.args = index, op, args
                if op.id and res.path:
                    state.ids[op.id] = res.path
                if plan.dry_run:
                    res.data_row = _dry_row(res)  # the paths as this op left them
            except Exception as exc:
                if plan.tool_errors_only and not isinstance(exc, ToolError):
                    raise
                if plan.raw_errors:
                    state.rollback.run()
                    raise
                if op.id:
                    failed.add(op.id)
                path = path_of(op.op, args)
                where = {"label": plan.label, "op": {"op": op.op, **(args or {})}}
                if not isinstance(args, dict):
                    where["op"] = {"op": op.op}
                if plan.partial or plan.stop:
                    ok = state.rollback.run(mark)
                    error = as_sent(
                        batch_error(index, path, exc, rolled_back=ok, **where), op
                    ).to_dict()
                    results.append(OpResult(index, op, args, error=error))
                    if plan.stop:
                        state.stopped = index
                    continue
                if not plan.collect:
                    ok = state.rollback.run()
                    reported = None if not ok and plan.defer_rollback else ok
                    raise as_sent(
                        batch_error(index, path, exc, rolled_back=reported, **where), op
                    ) from exc
                # edit: revert this op and check the rest against what the others leave.
                state.rollback.run(mark)
                problems.append(
                    as_sent(batch_error(index, path, exc, rolled_back=True, **where), op)
                )
                state.checking = True
                continue
            results.append(res)
        if problems:
            ok = state.rollback.run()
            reported = None if not ok and plan.defer_rollback else ok
            for problem in problems:
                problem.detail["rolled_back"] = reported
            raise combined_error(problems)
    finally:
        _ACTIVE.remove(state)
    return Result(plan, results, state)


def combined_error(problems: list[ToolError]) -> ToolError:
    """The first problem, with ``(+n more problem(s))`` and ``detail.problems`` listing up
    to 20 (``{item, code, message, hint?}``) when there are several."""
    first = problems[0]
    if len(problems) > 1:
        listing = []
        for error in problems[:20]:
            row: dict[str, Any] = {
                "item": error.detail.get("item"),
                "code": error.code,
                "message": error.message,
            }
            if error.hint:
                row["hint"] = error.hint
            listing.append(row)
        first.message = f"{first.message} (+{len(problems) - 1} more problem(s))"
        first.args = (first.message,)
        first.detail = {**first.detail, "problems": listing}
    return first


def dry_run(plan: Plan, ctx: Any) -> list[dict[str, Any]]:
    """Check ``plan`` by running it in check mode and compensating it, with undo off and
    events muted, so nothing is left behind: no node, undo step, event or dirty flag
    (D56). Returns one row per op with resolved paths (``predicted: true`` where Houdini
    numbered a new node), or raises the first problem with all of them listed."""
    import hou

    from .tools.events import muted

    plan.dry_run = True
    plan.collect = True
    with hou.undos.disabler(), muted():
        result = execute(plan, ctx)  # compensated already when it raises
        try:
            rows = [res.data_row for res in result.results]
        finally:
            restored = result.state.rollback.run()
    if not restored:
        raise ToolError(
            "internal",
            "The dry run could not take back every change it made to check the ops.",
            hint="Inspect the nodes the ops name before editing them.",
        )
    return rows


def _dry_row(res: OpResult) -> dict[str, Any]:
    """A dry run's row for one op: what the run did, by path (before the compensation)."""
    kind, data, args = res.op.op, res.data, res.args if isinstance(res.args, dict) else {}
    row: dict[str, Any] = {"op": kind}
    if res.op.id:
        row["id"] = res.op.id
    if kind == "create":
        row.update(path=res.node.path(), type=res.node.type().name())
        if args.get("name") is None:
            row["predicted"] = True  # Houdini numbered it
        if res.extra.get("wires"):
            row["inputs"] = res.extra["wires"]
    elif kind == "connect":
        row["to"] = res.node.path()
        row["to_input"] = res.extra["input"]
        row["from"] = res.extra["from"]
        row["path"] = res.node.path()
    elif kind == "set":
        if isinstance(data, list):
            row.update(path=res.node.path(), parms=list((args.get("parms") or {}).keys()))
        else:
            row["path"] = data.get("path") if isinstance(data, dict) else res.path
    elif kind == "node":
        row["path"] = res.node.path()
        if "old_path" in res.extra:
            row["old_path"] = res.extra["old_path"]
    elif kind == "delete":
        row["paths"] = data["deleted"]
    elif kind == "copy":
        row["paths"] = [c.path() for c in data["copies"]]
        if len(row["paths"]) == 1:
            row["path"] = row["paths"][0]
    elif kind == "layout":
        row["path"] = data["parent"].path()
    elif kind == "build":
        row.update(path=data["parent"].path(), nodes=[n.path() for n in data["top_nodes"]])
        if data["renamed"]:
            row["renamed"] = data["renamed"]
    elif kind == "select":
        row["paths"] = data["selected"]
    return row


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
    with located("parent"):
        N.ensure_can_hold_children(parent)
    type_name = args.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise N.bad_arg(f"items[{index}].type must be a non-empty string.")
    name = args.get("name")
    if name is not None:
        with located("name"):
            N.check_name(name)
        existing = parent.node(name)
        if existing is not None:
            free = N.unique_name(parent, name)
            raise at_field(
                ToolError(
                    "name_collision",
                    f"{existing.path()} already exists.",
                    hint=f"Pick another name (e.g. {free!r}), omit name to let Houdini number "
                    "it, or edit the existing node.",
                    candidates=[free],
                ),
                "name",
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
    inputs = args.get("inputs") or []
    if not isinstance(inputs, list):
        raise N.bad_arg(f"items[{index}].inputs must be a list.")
    wires = []
    for link_index, link in enumerate(inputs):
        at = f"inputs[{link_index}]"
        if not isinstance(link, dict) or "from" not in link:
            raise N.bad_arg(f"items[{index}].{at} must be {{index|name, from, output}}.")
        if "index" in link and "name" in link:
            raise N.bad_arg(f"items[{index}].{at}: pass index or name, not both.")
        src = wire_source(link["from"], node, f"{at}.from")
        target = link.get("name") if "name" in link else link.get("index", link_index)
        with located(f"{at}.{'name' if 'name' in link else 'index'}"):
            dest_index = N.resolve_input_index(node, target)
        item, output = wire_output(src, node, link.get("output", 0), f"{at}.output")
        with located(at):
            N.connect(node, dest_index, item, output, None)
        wires.append(src.path())
    with located("flags"):
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
    return OpResult(
        index,
        Op("create", args),
        node=node,
        path=node.path(),
        nodes=[node],
        cook=cook,
        extra={"wires": wires} if wires else {},
    )


def wire_source(value: Any, dest: Any, field: str) -> Any:
    """The node ``value`` names as a wire into ``dest`` (absolute, or relative to
    ``dest``'s network): a sibling, or ``dest``'s parent, whose own inputs feed its
    children (a subnet's indirect inputs, D59). A missing one is ``node_not_found`` at
    ``field`` with the network's nearest children as candidates (never ``dest``)."""
    import hou

    from .tools._diag import missing_node_error
    from .tools.nodes import ABOUT_KEY, bad_arg

    with located(field):
        if not isinstance(value, str) or not value.strip():
            raise bad_arg(f"'{field}' must be a node path.")
        network = dest.parent()
        text = value.strip()
        src = hou.node(text) if text.startswith("/") else network.node(text)
        if src is None:
            full = text if text.startswith("/") else f"{network.path().rstrip('/')}/{text}"
            error = missing_node_error(full.rstrip("/") or "/", exclude=dest)
            error.detail = {ABOUT_KEY: full}  # a 1.4 batch error names the source, not dest
            raise error
        if src == dest:
            raise ToolError(
                "invalid_input",
                f"{dest.path()} cannot be wired into itself.",
                hint="Wire an upstream node into it instead.",
            )
        if src != network and src.parent() != network:
            raise ToolError(
                "invalid_input",
                f"{src.path()} and {dest.path()} are in different networks.",
                hint="Connect nodes that share a parent; inside a subnet, from: <the subnet> "
                "with an output index wires its input of that index. An object_merge SOP "
                "brings geometry across networks.",
            )
    return src


def wire_output(src: Any, dest: Any, output: Any, field: str) -> tuple[Any, int]:
    """``(item, output index)`` to wire into ``dest``: ``src`` and its checked output, or,
    when ``src`` is ``dest``'s parent, that subnet's indirect input ``output`` (D59)."""
    from .tools import nodes as N

    with located(field):
        if src != dest.parent():
            return src, N.check_output_index(src, output)
        if output is None:
            output = 0
        if not isinstance(output, int) or isinstance(output, bool) or output < 0:
            raise N.bad_arg("Output index must be a non-negative integer.")
        try:
            inputs = list(src.indirectInputs())
        except Exception:
            inputs = []
        if output >= len(inputs):
            hint = (
                f"Inside {src.path()}, its inputs 0..{len(inputs) - 1} are wire sources."
                if inputs
                else f"{src.path()} has no inputs to wire from inside it; wire from its "
                "input node instead (a VOP subnet's subinput)."
            )
            raise ToolError(
                "invalid_input",
                f"{src.path()} has no input {output} to wire from inside it.",
                hint=hint,
            )
        return inputs[output], 0


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
    text_field = next((f for f in ("patch", "value_file") if args.get(f) is not None), None)
    with located(text_field) if text_field else contextlib.nullcontext():
        row = P._apply(node, target, args, frame=frame, ctx=st.ctx)
    return OpResult(index, Op("set", args), node=node, path=node.path(), nodes=[node], data=row)


def _op_connect(args: Any, opts: dict[str, Any], index: int, st: State) -> OpResult:
    from .tools import nodes as N

    if not isinstance(args, dict) or "to" not in args or "from" not in args:
        raise N.bad_arg(f"items[{index}] needs 'from' (path or null) and 'to'.")
    dest = N.get_node(args.get("to"), field="to")
    with located("to"):
        N.ensure_editable(dest, "rewire")
    src_path = args.get("from")
    src = None if src_path is None else wire_source(src_path, dest, "from")
    with located("to_input"):
        index_or_next = N.resolve_input_index(dest, args.get("to_input", 0))
    if src is None:
        if index_or_next == "next":
            raise at_field(
                N.bad_arg(
                    "to_input 'next' cannot disconnect.",
                    hint="Pass the input index or name to disconnect.",
                ),
                "to_input",
            )
        used = N.connect(dest, index_or_next, None, 0, st.rollback)
        output = 0
    else:
        item, out_index = wire_output(src, dest, args.get("from_output", 0), "from_output")
        used = N.connect(dest, index_or_next, item, out_index, st.rollback)
        # From the parent: from_output named the subnet input that feeds the wire.
        output = (args.get("from_output") or 0) if src == dest.parent() else out_index
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
        from .tools.spare import plan_spare_parms

        # A locked asset's own instance takes spare parms (the wrangle "Create spare
        # parameters" button does that); nodes inside a locked asset were refused above.
        with located("spare_parms"):
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
        before = N.flag_state(node, flags)
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
        from .tools.spare import apply_spare_parms

        spare = apply_spare_parms(node, plan["spare"], rollback)
    lock = plan["lock"]
    if lock and st.checking:
        lock = None  # matchCurrentDefinition() discards edits compensation cannot restore
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
    soft = st.checking
    for node in unique:
        path = node.path()
        src = src_out = None
        if keep:
            source = next((c for c in node.inputConnections() if c.inputIndex() == 0), None)
            if source is not None and source.inputNode() is not None:
                src, src_out = source.inputNode(), source.outputIndex()
        for conn in list(node.outputConnections()):
            dest = conn.outputNode()
            if dest is None:
                continue
            slot, old = conn.inputIndex(), (node, conn.outputIndex())
            if src is not None:
                try:
                    dest.setInput(slot, src, src_out)
                except Exception:
                    continue
                reconnected.append({"from": src.path(), "to": dest.path(), "input": slot})
                touched[dest.path()] = dest
            elif soft or not keep:
                # destroy() splices input 0 through to the outputs by itself; cut them first.
                with _c.suppress(Exception):
                    dest.setInput(slot, None)
            else:
                continue
            if soft:
                st.rollback.add(lambda d=dest, i=slot, o=old: d.setInput(i, o[0], o[1]))
        if soft:
            _set_aside(node, st.rollback)
        else:
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


def _set_aside(node: Any, rollback: Rollback) -> None:
    """Check mode's delete (D56): the node is renamed out of the way, so its path and
    name are free and later ops see it gone; compensation renames it back. Houdini
    updates expressions that name it either way."""
    from .tools.nodes import unique_name

    old_name = node.name()
    node.setName(unique_name(node.parent(), f"{old_name}_hp_deleted"))
    rollback.add(lambda: node.setName(old_name))


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
            slot, out_index = conn.inputIndex(), conn.outputIndex()
            consumer.setInput(slot, new, out_index)
            rollback.add(lambda c=consumer, i=slot, o=old, n=out_index: c.setInput(i, o, n))
        if st.checking:
            continue  # check mode keeps the old node, renamed aside, for compensation
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
    from .tools.state import context_changed_note, select_nodes

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
    if st.checking:
        # Selecting moves unpinned panes into the network (parity G3): not compensable.
        return OpResult(index, Op("select", args), data={"selected": [n.path() for n in nodes]})
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
        data["notes"] = [context_changed_note()]
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


PARTIAL_MODES = (False, True, "stop")
"""``edit``'s ``partial``: false (a failing op rolls the call back, after every op was
checked), true (each failing op reverts only itself) or ``"stop"`` (D57: the ops before
the first failing op stay, the rest do not run)."""


def partial_mode(args: dict[str, Any]) -> bool | str:
    from .tools.nodes import bad_arg

    value = args.get("partial", False)
    if value is None:
        return False
    if value not in PARTIAL_MODES or (value in (0, 1) and not isinstance(value, bool)):
        raise bad_arg("'partial' must be true, false or \"stop\".")
    return value


def parse_ops(ops: Any, *, partial: bool | str = False) -> Plan:
    """An ``edit`` plan from its ``ops``: kinds, ids and fields checked, nothing else."""
    from .tools.nodes import bad_arg, batch_error

    if not isinstance(ops, list) or not ops:
        raise bad_arg("'ops' must be a non-empty array of {op, ...} objects.")
    plan = Plan(
        [],
        partial=partial is True,
        stop=partial == "stop",
        collect=partial is False,
        strict_refs=True,
        defer_rollback=True,
        label="ops",
    )
    seen: set[str] = set()
    for index, raw in enumerate(ops):
        try:
            plan.ops.append(_parse_op(raw, seen))
        except ToolError as exc:
            raise batch_error(
                index, path_of_raw(raw), exc, rolled_back=True, label="ops", op=raw
            ) from exc
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

        raise at_field(
            bad_arg(
                f"Unknown op {kind!r}.",
                hint=f"Ops: {', '.join(OP_KINDS)}.",
                candidates=difflib.get_close_matches(str(kind), OP_KINDS, n=3, cutoff=0.0),
            ),
            "op",
        )
    op_id = raw.get("id")
    if op_id is not None:
        if not isinstance(op_id, str) or not ID_RE.match(op_id):
            raise at_field(
                bad_arg(
                    f"id {op_id!r} is not an identifier.",
                    hint="An id is letters, digits and _ (not starting with a digit); later "
                    "ops name it as $id.",
                ),
                "id",
            )
        if op_id in seen:
            raise at_field(
                bad_arg(f"id {op_id!r} is used twice.", hint="Give every op its own id."), "id"
            )
        seen.add(op_id)
    fields = {k: v for k, v in raw.items() if k not in ("op", "id")}
    unknown = set(fields) - OP_FIELDS[kind]
    if unknown:
        raise at_field(
            bad_arg(
                f"A {kind} op takes no {', '.join(sorted(unknown))}.",
                hint=f"{kind} fields: {', '.join(sorted(OP_FIELDS[kind]))}.",
            ),
            sorted(unknown)[0],
        )
    sent_as = _canonical_path(kind, fields)
    opts = {k: fields.pop(k) for k in OPTION_FIELDS.get(kind, ()) if k in fields}
    if kind == "set" and "frame" in opts:
        from .tools.parms import _frame_arg

        opts["frame"] = _frame_arg(opts["frame"])
    return Op(kind, fields, op_id, opts, sent_as)


def _canonical_path(kind: str, fields: dict[str, Any]) -> dict[str, str]:
    """Read ``path`` (and a ``node`` op's ``node``) as the op's own node field, in place
    (:data:`PATH_ALIASES`). Both spellings at once is ``invalid_argument`` unless they
    agree. Returns ``{canonical field: key sent}`` for the fields only the alias gave."""
    from .tools.nodes import bad_arg

    sent: dict[str, str] = {}

    def merge(alias: str, target: str, value: Any) -> None:
        if target in fields and fields[target] != value:
            raise at_field(
                bad_arg(
                    f"A {kind} op takes {alias} or {target}, not both.",
                    hint=f"{alias} is the same field as {target} on a {kind} op.",
                ),
                alias,
            )
        if target not in fields:
            sent[target] = alias
        fields[target] = value

    if kind == "node" and "node" in fields:
        merge("node", "path", fields.pop("node"))
        return sent
    if "path" not in fields:
        return sent
    if kind == "set":
        if "parms" in fields:
            merge("path", "node", fields.pop("path"))
        return sent
    if kind == "create":
        path = fields.pop("path")
        parent, _, name = (
            path.rstrip("/").rpartition("/") if isinstance(path, str) else ("", "", "")
        )
        if not isinstance(path, str) or "/" not in path or not name:
            raise at_field(
                bad_arg(
                    f"A create op's path is the new node's path, <parent>/<name>; got {path!r}.",
                    hint="Pass path: /obj/geo1/box1 (or $id/box1), or parent and name.",
                ),
                "path",
            )
        merge("path", "parent", parent or "/")
        merge("path", "name", name)
        return sent
    target = PATH_ALIASES.get(kind)
    if target is None:
        return sent
    value = fields.pop("path")
    if target == "paths":
        value = [value]
    merge("path", target, value)
    return sent


def as_sent(error: ToolError, op: Op) -> ToolError:
    """``error`` located at the key the caller wrote: ``ops[i].path`` where the op's
    ``path`` was read as ``parent``, ``to`` or ``paths`` (and ``paths[0]`` as ``path``)."""
    detail = error.detail if isinstance(error.detail, dict) else {}
    located_at = detail.get("field")
    if not op.sent_as or not isinstance(located_at, str):
        return error
    root = re.split(r"[.\[]", located_at, maxsplit=1)[0]
    alias = op.sent_as.get(root)
    if alias is None:
        return error
    rest = located_at[len(root) :]
    if root == "paths" and rest.startswith("[0]"):
        rest = rest[3:]  # the one path the caller sent
    renamed = alias + rest
    old_prefix = f"ops[{detail.get('item')}].{located_at}"
    if error.message.startswith(old_prefix):
        error.message = f"ops[{detail.get('item')}].{renamed}" + error.message[len(old_prefix) :]
        error.args = (error.message,)
    error.detail = {**detail, "field": renamed}
    return error


# -- field locations ---------------------------------------------------------------------

FIELD_KEY = "_field"
"""``detail`` key a validator sets on an error to name the op field it is about; the batch
error turns it into the ``ops[i].<field>`` location and drops it (review 25 papercut 3)."""


def at_field(error: ToolError, field: str) -> ToolError:
    """``error`` located at op field ``field``, unless a deeper field was named already."""
    detail = error.detail if isinstance(error.detail, dict) else {}
    if FIELD_KEY not in detail:
        error.detail = {**detail, FIELD_KEY: field}
    return error


@contextlib.contextmanager
def located(field: str) -> Iterator[None]:
    """Locate a :class:`ToolError` raised in the block at op field ``field``."""
    try:
        yield
    except ToolError as exc:
        raise at_field(exc, field) from None


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


# -- the edit echo ------------------------------------------------------------------------


def node_problems(node: Any, cook: bool) -> dict[str, Any]:
    from .tools._diag import cheap_cook_problems, collect_problems

    return cheap_cook_problems(node) if cook else collect_problems(node, cook=False)


RETURN_MODES = ("summary", "ops", "full")
"""``edit``'s ``return``: ``summary`` (the default) is one compact row per touched node with
the ops' notable results folded in; ``ops`` adds the per-op rows; ``full`` is the 1.4 full
shapes."""


def return_mode(args: dict[str, Any]) -> str:
    from .tools.nodes import bad_arg

    mode = args.get("return") or "summary"
    if mode not in RETURN_MODES:
        raise bad_arg("'return' must be 'summary', 'ops' or 'full'.")
    return mode


def compact_row(node: Any, problems: dict[str, Any]) -> dict[str, Any]:
    """The summary row of a touched node: ``path`` and ``type``, then only what is
    notable: non-empty ``errors``/``warnings``, ``cook_state`` unless ``cooked``,
    ``cook_ms`` from 1 ms, a ``hint``."""
    row: dict[str, Any] = {"path": node.path(), "type": node.type().name()}
    for key in ("errors", "warnings"):
        if problems.get(key):
            row[key] = problems[key]
    state = problems.get("cook_state")
    if state and state != "cooked":
        row["cook_state"] = state
    ms = problems.get("cook_time_ms")
    if isinstance(ms, (int, float)) and ms >= 1:
        row["cook_ms"] = ms
    if problems.get("hint"):
        row["hint"] = problems["hint"]
    return row


FOLDED_NODE_KEYS = ("old_path", "paired_with", "deprecated", "hda", "notes", "side_effects")
"""Op results that belong to one node and are folded into its ``summary`` row."""


COOKING: dict[str, Any] = {"errors": [], "warnings": [], "messages": [], "cook_state": "cooking"}
"""The problems of a node whose echo cook still runs as a job (D58)."""

PROBLEM_KEYS = frozenset(
    ("errors", "warnings", "messages", "cook_state", "cook_ms", "hint", "errors_same_as",
     "warnings_same_as")
)  # fmt: skip
"""The keys of a node row that its cook decides (:func:`patch_rows`)."""


def cook_targets(result: Result) -> list[tuple[int, Any]]:
    """``(session id, node)`` of every touched node the echo cooks: touched by an op that
    cooks, in a category a mutation result cooks (``CHEAP_COOK_CATEGORIES``), in
    first-touch order."""
    from .tools._diag import CHEAP_COOK_CATEGORIES

    out = []
    for node, cook in result.touched():
        if not cook:
            continue
        try:
            category = node.type().category().name()
        except Exception:
            continue
        if category in CHEAP_COOK_CATEGORIES:
            sid = _session_id(node)
            if sid is not None:
                out.append((sid, node))
    return out


def echo(result: Result, mode: str, *, pending: Iterable[int] = ()) -> dict[str, Any]:
    """The ``edit`` result.

    ``summary``: ``nodes`` (one :func:`compact_row` per touched node, cooked once, with
    the ops' per-node results folded in: :data:`FOLDED_NODE_KEYS`), ``ids`` (``{id:
    path}`` for every op id), and what is not one node's: ``deleted``, ``reconnected``,
    ``selected`` (and ``context_changed``), ``renamed``, ``replaced``, ``failed`` (with
    ``partial``: ``[{item, op, id?, error}]``), ``applied`` (``partial: "stop"`` after a
    failure: how many ops ran). ``ops`` is ``results`` (one row per op) plus the compact
    ``nodes``; ``full`` is the 1.4 full shapes (flags, messages, parm rows). Identical
    error lists after the first become ``errors_same_as`` outside ``full``.

    Nodes whose session id is in ``pending`` are not cooked here: their rows carry
    ``cook_state: "cooking"`` until :func:`patch_rows` fills in their cook (``edit`` cooks
    them after the call's main-thread work, D58); ``result.rows`` maps each session id to
    its node row for that."""
    from .tools import nodes as N

    waiting = set(pending)
    result.rows = {}

    def problems_of(node: Any, cook: bool) -> dict[str, Any]:
        if _session_id(node) in waiting:
            return dict(COOKING)
        return node_problems(node, cook)

    if mode == "summary":
        out = _summary_echo(result, problems_of, waiting)
    else:
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
            block = node_block(node, problems_of(node, cook), mode)
            result.rows[_session_id(node)] = block
            blocks.append(block)
        if mode == "ops" and not waiting:
            N.collapse_problems(blocks)
        out = {"results": rows, "nodes": blocks}
        if result.failures:
            out["failed"] = len(result.failures)
    if result.state.stopped is not None:
        out["applied"] = result.state.stopped
    return out


def node_block(node: Any, problems: dict[str, Any], mode: str) -> dict[str, Any]:
    """A touched node's row: :func:`compact_row` (``summary``, ``ops``) or the 1.4 full
    block (``full``: name, flags, messages)."""
    from .tools import nodes as N

    if mode != "full":
        return compact_row(node, problems)
    block = {"path": node.path(), "name": node.name(), "type": node.type().name()}
    block["flags"] = N.node_flags(node)
    block.update(problems)
    if "cook_time_ms" in block:
        block["cook_ms"] = block.pop("cook_time_ms")
    return block


def patch_rows(
    out: dict[str, Any],
    rows: dict[int, dict[str, Any]],
    cooked: dict[int, Any],
    *,
    collapse: bool,
) -> None:
    """Put each cooked node's problems (``cooked``: session id -> its row as
    :func:`node_block` builds it after the cook) into its row of ``out``, keeping the
    row's other keys (the ops' folded results); with ``collapse`` (not ``full``) report
    identical error lists once, which :func:`echo` left to this. Pure Python: it runs
    off the main thread (D58)."""
    from .tools import nodes as N

    for sid, fresh in cooked.items():
        row = rows.get(sid)
        if row is None:
            continue
        rest = {k: v for k, v in row.items() if k not in fresh and k not in PROBLEM_KEYS}
        row.clear()
        row.update(fresh)
        row.update(rest)
    if collapse and isinstance(out.get("nodes"), list):
        N.collapse_problems(out["nodes"])


def _summary_echo(
    result: Result, problems_of: Callable[[Any, bool], dict[str, Any]], waiting: set[int]
) -> dict[str, Any]:
    from .tools import nodes as N

    blocks: dict[str, dict[str, Any]] = {}
    for node, cook in result.touched():
        row = compact_row(node, problems_of(node, cook))
        blocks[row["path"]] = row
        result.rows[_session_id(node)] = row
    out: dict[str, Any] = {}
    ids: dict[str, str] = {}
    failed: list[dict[str, Any]] = []
    for res in result.results:
        if res.error is not None:
            entry: dict[str, Any] = {"item": res.index, "op": res.op.op}
            if res.op.id:
                entry["id"] = res.op.id
            entry["error"] = res.error
            failed.append(entry)
            continue
        if res.op.id and res.path:
            ids[res.op.id] = _current_path(res.node) or res.path  # after later renames
        _fold(res, result.state, blocks, out)
    rows = list(blocks.values())
    if not waiting:
        N.collapse_problems(rows)  # else patch_rows does, once the cooks are in
    final: dict[str, Any] = {"nodes": rows}
    if ids:
        final["ids"] = ids
    final.update(out)
    if failed:
        final["failed"] = failed
    return final


def _current_path(node: Any) -> str | None:
    if node is None or _session_id(node) is None:
        return None
    return node.path()


def _fold(res: OpResult, st: State, blocks: dict[str, dict[str, Any]], out: dict[str, Any]) -> None:
    """Fold one op's notable results into the summary: per-node keys onto that node's
    row (when it is still there), the rest onto the top level."""
    from .tools import nodes as N

    kind, data = res.op.op, res.data

    def onto(path: str | None, key: str, value: Any) -> None:
        row = blocks.get(path or "")
        if row is None:
            return
        if isinstance(value, list) and isinstance(row.get(key), list):
            row[key] = row[key] + [v for v in value if v not in row[key]]
        elif isinstance(value, dict) and isinstance(row.get(key), dict):
            row[key] = {**row[key], **value}
        else:
            row[key] = value

    def top(key: str, values: Any) -> None:
        if isinstance(values, dict):
            out.setdefault(key, {}).update(values)
        else:
            out.setdefault(key, []).extend(v for v in values if v not in out.get(key, []))

    if kind == "create" and res.node is not None:
        extra: dict[str, Any] = {}
        sid = res.node.sessionId()
        if sid in st.pairs:
            extra["paired_with"] = st.pairs[sid]
        N.add_create_extras(extra, st.extras.get(sid))
        for key, value in extra.items():
            onto(res.path, key, value)
    elif kind == "node":
        for key in ("old_path", "hda"):
            if key in res.extra:
                onto(res.path, key, res.extra[key])
    elif kind == "set":
        items = data if isinstance(data, list) else [data]
        path = res.node.path() if res.node is not None else None
        for item in items:
            if not isinstance(item, dict):
                continue
            target = path or str(item.get("path", "")).rpartition("/")[0]
            if item.get("notes"):
                onto(target, "notes", list(item["notes"]))
            if item.get("side_effects"):
                onto(target, "side_effects", dict(item["side_effects"]))
    elif kind == "delete":
        top("deleted", data["deleted"])
        if data["reconnected"]:
            top("reconnected", data["reconnected"])
    elif kind == "build":
        base = data["parent"].path().rstrip("/")
        if data["renamed"]:
            top("renamed", {f"{base}/{k}": f"{base}/{v}" for k, v in data["renamed"].items()})
        if data["replaced"]:
            top("replaced", [f"{base}/{n}" for n in data["replaced"]])
        for node_path, effects in (data.get("side_effects") or {}).items():
            onto(node_path, "side_effects", effects)
        for key in ("warnings", "notes"):
            if data[key]:
                top(key, data[key])
    elif kind == "select":
        out["selected"] = data["selected"]
        if data.get("context_changed"):
            out["context_changed"] = data["context_changed"]
        if data.get("notes"):
            top("notes", data["notes"])


def _short_parm_row(row: dict[str, Any]) -> dict[str, Any]:
    """A set row for ``return: summary``: the parm path, its value as Houdini holds it
    (menus as tokens), and only what is notable (expression, keys written, notes, a
    press's side effects)."""
    keep = (
        "path", "value", "raw", "expression", "expressions", "keyed", "pressed",
        "side_effects", "outputs_summary", "notes", "patched_lines", "value_file",
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
