"""Node tools: find, info, create, delete, edit, copy, connect, layout.

See docs/BIBLE.md §4.4 and §5. Node paths are identity and results carry final resolved
paths. Every mutation result reports each touched node's ``errors/warnings`` after a
cheap cook (``_diag.cheap_cook_problems``).

Rollback: ``hou.undos.performUndo()`` refuses to run inside an open undo group, and the
dispatcher's group is open while a tool runs, so batch tools undo their own work by
compensation (:class:`Rollback`) when an item fails and ``partial`` is false.
"""

from __future__ import annotations

import contextlib
import difflib
import re
from collections.abc import Callable, Iterable
from typing import Any

from hocuspocus.tools.errors import ToolError

from ._common import (  # noqa: F401 (re-exported for the other tool modules)
    CURSOR_HINT,
    DEFAULT_LIMIT,
    ROW_ENVELOPE_BYTES,
    arg_bool,
    arg_list,
    bad_arg,
    compact_size,
    get_node,
    hou_exception_text,
    hou_message,
    page,
    parse_limit,
    response_budget,
)
from ._diag import a_or_an, cheap_cook_problems, collect_problems
from .registry import HostContext, tool

NODE_INFO_SECTIONS = (
    "parms", "inputs", "outputs", "children", "errors", "flags", "hda", "comment", "position",
    "userdata",
)  # fmt: skip
DEFAULT_INCLUDE = ("parms", "inputs", "errors", "flags")
FLAG_NAMES = ("display", "render", "bypass", "template", "locked")
SETTABLE_FLAGS = ("display", "render", "bypass", "template")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
CHILDREN_LIST_LIMIT = 200

_FLAG_GETTERS = {
    "display": "isDisplayFlagSet",
    "render": "isRenderFlagSet",
    "bypass": "isBypassed",
    "template": "isTemplateFlagSet",
    "locked": "isHardLocked",
}
_FLAG_SETTERS = {
    "display": "setDisplayFlag",
    "render": "setRenderFlag",
    "bypass": "bypass",
    "template": "setTemplateFlag",
}


# -- generic helpers --------------------------------------------------------------


def arg_xy(value: Any, key: str) -> tuple[float, float]:
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        raise bad_arg(f"'{key}' must be [x, y] numbers.")
    return float(value[0]), float(value[1])


def check_name(name: Any, field: str = "name") -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        suggestion = ""
        if isinstance(name, str) and name:
            with contextlib.suppress(Exception):
                import hou

                suggestion = hou.text.alphaNumeric(name)
        raise bad_arg(
            f"{name!r} is not a valid node name.",
            hint="Node names use letters, digits, '_', '.' and '-' only"
            + (f"; e.g. {suggestion!r}." if suggestion else "."),
            candidates=[suggestion] if suggestion else None,
        )
    return name


def unique_name(parent: Any, base: str, taken: Iterable[str] = ()) -> str:
    """``base`` if free in ``parent`` (and not in ``taken``), else base with a numeric suffix."""
    used = set(taken)
    if parent.node(base) is None and base not in used:
        return base
    stem = base.rstrip("0123456789") or base
    i = 1
    while True:
        candidate = f"{stem}{i}"
        if parent.node(candidate) is None and candidate not in used:
            return candidate
        i += 1


# -- node lookup ------------------------------------------------------------------


def locked_ancestor(node: Any) -> Any:
    current = node.parent() if node is not None else None
    while current is not None:
        if _is_locked_hda(current):
            return current
        current = current.parent()
    return None


def _is_locked_hda(node: Any) -> bool:
    try:
        return bool(node.isLockedHDA())
    except Exception:
        return False


def inside_locked(node: Any) -> bool:
    try:
        return bool(node.isInsideLockedHDA()) and not bool(node.isEditableInsideLockedHDA())
    except Exception:
        return False


def _locked_error(node: Any, asset: Any, action: str) -> ToolError:
    return ToolError(
        "locked",
        f"Cannot {action} {node.path()}: it is inside the locked asset {asset.path()} "
        f"({asset.type().name()})."
        if asset is not node
        else f"Cannot {action} {node.path()}: it is a locked asset ({node.type().name()}).",
        hint=f"Unlock it with node_edit {{path: {asset.path()!r}, lock: false}} "
        "(allowEditingOfContents) first, or work outside the asset.",
    )


def ensure_editable(node: Any, action: str = "edit") -> None:
    """Refuse to change a node that lives inside a locked HDA."""
    if inside_locked(node):
        raise _locked_error(node, locked_ancestor(node) or node, action)


def ensure_can_hold_children(parent: Any, action: str = "create nodes in") -> None:
    ensure_editable(parent, action)
    if _is_locked_hda(parent):
        raise _locked_error(parent, parent, action)
    try:
        category = parent.childTypeCategory()
    except Exception:
        category = None
    if category is None:
        raise bad_arg(
            f"{parent.path()} ({parent.type().name()}) is not a network and cannot contain nodes.",
            hint="Pass a network such as /obj, a geo object or a subnet as parent.",
        )


# -- type resolution --------------------------------------------------------------


def _type_short_name(node_type: Any) -> str:
    _scope, namespace, core, _version = node_type.nameComponents()
    return f"{namespace}::{core}" if namespace else core


TYPE_SYNONYMS: dict[str, dict[str, tuple[str, str]]] = {
    # Names other packages (and the LOP context) use for what one OBJ type does here.
    "Object": {
        **{
            name: ("hlight", f"set light_type to {kind}")
            for kind, names in (
                ("distant", ("distantlight", "directionallight", "sunlight", "dirlight")),
                ("point", ("pointlight", "omnilight")),
                ("spot", ("spotlight",)),
                ("grid", ("arealight", "rectlight", "gridlight", "quadlight")),
                ("sphere", ("spherelight",)),
                ("disk", ("disklight",)),
            )
            for name in names
        },
        "domelight": ("envlight", "an environment light (envlight) lights from a dome"),
        "camera": ("cam", "set focal, resx and resy on it"),
    },
}
"""``{category: {query: (type, note)}}`` for type names an agent reaches for that the
category spells differently (review 11 B10: ``distantlight`` is ``hlight`` in /obj)."""


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def type_synonym(category: Any, query: str) -> tuple[str, str] | None:
    """``(type, note)`` when ``query`` is a known other name for a type in ``category``."""
    import hou

    table = TYPE_SYNONYMS.get(category.name(), {})
    hit = table.get(_squash(query.split("::")[0].split("/")[-1]))
    if hit is None:
        return None
    with contextlib.suppress(Exception):
        if hou.nodeType(category, hit[0]) is not None:
            return hit
    return None


def type_candidates(category: Any, query: str, n: int = 8) -> list[str]:
    """Nearest type names for ``query``: synonyms, then names and labels (UI descriptions)
    close to it, then types whose whole label occurs in it (``distant light`` -> Light)."""
    q = (
        query.lower().split("::")[-1]
        if "::" in query and not query.endswith("::")
        else query.lower()
    )
    q = q.split("/")[-1]
    squashed = _squash(q)
    pool: dict[str, str] = {}
    labels: dict[str, str] = {}
    for node_type in category.nodeTypes().values():
        try:
            if node_type.hidden():
                continue
            short = _type_short_name(node_type)
            pool.setdefault(short.lower(), short)
            pool.setdefault(node_type.nameComponents()[2].lower(), short)
            label = node_type.description().lower()
            pool.setdefault(label, short)
            labels.setdefault(_squash(label), short)
        except Exception:
            continue
    out: list[str] = []

    def add(name: str) -> None:
        if name not in out:
            out.append(name)

    synonym = type_synonym(category, query)
    if synonym is not None:
        add(synonym[0])
    if squashed in labels:
        add(labels[squashed])  # the label typed without spaces: "environmentlight"
    for match in difflib.get_close_matches(q, list(pool), n=n * 2, cutoff=0.6):
        add(pool[match])
    # A label that occurs whole inside the query, longest first ("light" in "spot_light").
    for label in sorted(labels, key=len, reverse=True):
        if len(label) >= 4 and label in squashed:
            add(labels[label])
    if len(out) < n:
        for key in sorted(pool, key=len):
            if q and q in key:
                add(pool[key])
            if len(out) >= n:
                break
    return out[:n]


def other_categories_with(name: str, exclude: Any) -> list[str]:
    import hou

    found = []
    for cat_name, category in hou.nodeTypeCategories().items():
        if category == exclude:
            continue
        with contextlib.suppress(Exception):
            if hou.preferredNodeType(f"{cat_name}/{name}") or hou.nodeType(category, name):
                found.append(cat_name)
    return found


def type_not_found(parent: Any, type_name: str, category: Any) -> ToolError:
    candidates = type_candidates(category, type_name)
    others = other_categories_with(type_name, category)
    synonym = type_synonym(category, type_name)
    if synonym is not None:
        hint = (
            f"{category.name()} networks spell {type_name} as {synonym[0]}: create "
            f"{synonym[0]} and {synonym[1]}."
        )
        if others:
            hint += f" ({type_name} itself is {a_or_an('/'.join(others))} node type.)"
    elif others:
        hint = (
            f"{type_name} is {a_or_an('/'.join(others))} node type, but {parent.path()} holds "
            f"{category.name()} nodes."
        )
        if "Sop" in others and category.name() == "Object":
            hint += " Create a geo object first and put SOPs inside it."
    elif candidates:
        hint = f"Closest {category.name()} types: {', '.join(candidates[:5])}. node_type_search finds types by label."
    else:
        hint = "Use node_type_search to find the type name."
    return ToolError(
        "node_type_not_found",
        f"No {category.name()} node type {type_name!r} (parent {parent.path()}).",
        hint=hint,
        candidates=candidates,
    )


def resolve_type(parent: Any, type_name: str, *, exact: bool = False) -> Any:
    """Resolve ``type_name`` in ``parent``'s child category like ``createNode`` would."""
    import hou

    category = parent.childTypeCategory()
    node_type = None
    with contextlib.suppress(Exception):
        if exact:
            node_type = hou.nodeType(category, type_name)
        else:
            node_type = hou.preferredNodeType(f"{category.name()}/{type_name}", parent)
            if node_type is None:
                node_type = hou.nodeType(category, type_name)
    if node_type is None:
        raise type_not_found(parent, type_name, category)
    return node_type


# -- flags and node blocks ---------------------------------------------------------


def node_flags(node: Any) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for name, getter in _FLAG_GETTERS.items():
        fn = getattr(node, getter, None)
        if callable(fn):
            with contextlib.suppress(Exception):
                flags[name] = bool(fn())
    return flags


def check_flags(node: Any, flags: Any) -> None:
    """Raise ``invalid_argument`` unless every flag in ``flags`` can be set on ``node``."""
    if flags is None:
        return
    if not isinstance(flags, dict):
        raise bad_arg("'flags' must be an object of booleans.")
    for name, value in flags.items():
        if name not in SETTABLE_FLAGS:
            raise bad_arg(
                f"Unknown flag {name!r}.",
                hint=f"Settable flags: {', '.join(SETTABLE_FLAGS)}.",
            )
        if not isinstance(value, bool):
            raise bad_arg(f"Flag {name!r} must be a boolean.")
        if not callable(getattr(node, _FLAG_SETTERS[name], None)):
            have = ", ".join(sorted(node_flags(node))) or "none"
            raise bad_arg(
                f"{node.path()} ({node.type().category().name()}) has no {name} flag.",
                hint=f"Flags on this node: {have}.",
            )


def set_flags(node: Any, flags: Any) -> None:
    check_flags(node, flags)
    for name, value in (flags or {}).items():
        getattr(node, _FLAG_SETTERS[name])(value)


def type_block(node_type: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": node_type.name(),
        "category": node_type.category().name(),
    }
    with contextlib.suppress(Exception):
        version = node_type.nameComponents()[3]
        if version:
            out["version"] = version
    with contextlib.suppress(Exception):
        out["description"] = node_type.description()
    with contextlib.suppress(Exception):
        url = node_type.defaultHelpUrl()
        if url:
            out["help_url"] = url
    return out


def hda_block(node: Any) -> dict[str, Any] | None:
    try:
        definition = node.type().definition()
    except Exception:
        definition = None
    if definition is None:
        return None
    locked = _is_locked_hda(node)
    out: dict[str, Any] = {
        "hda_locked": locked,  # BIBLE §4.1: locked is the SOP lock flag (flags.locked)
        "definition": definition.nodeTypeName(),
        "library": definition.libraryFilePath(),
    }
    with contextlib.suppress(Exception):
        out["matches_definition"] = bool(node.matchesCurrentDefinition())
    return out


def _round(values: Iterable[float]) -> list[float]:
    return [round(float(v), 4) for v in values]


def input_rows(node: Any) -> list[dict[str, Any]]:
    try:
        names = list(node.inputNames())
        labels = list(node.inputLabels())
    except Exception:
        names, labels = [], []
    sources: dict[int, dict[str, Any]] = {}
    for conn in node.inputConnections():
        src = conn.inputItem() if hasattr(conn, "inputItem") else conn.inputNode()
        if src is None:
            continue
        path = src.path() if hasattr(src, "path") else str(src)
        sources[conn.inputIndex()] = {"path": path, "output": conn.outputIndex()}
    count = max(len(names), (max(sources) + 1) if sources else 0)
    rows = []
    for index in range(count):
        row: dict[str, Any] = {
            "index": index,
            "name": names[index] if index < len(names) else f"input{index + 1}",
            "label": labels[index] if index < len(labels) else "",
            "from": sources.get(index),
        }
        rows.append(row)
    return rows


def output_rows(node: Any) -> list[dict[str, Any]]:
    try:
        names = list(node.outputNames())
    except Exception:
        names = []
    targets: dict[int, list[dict[str, Any]]] = {}
    for conn in node.outputConnections():
        dest = conn.outputItem() if hasattr(conn, "outputItem") else conn.outputNode()
        if dest is None:
            continue
        path = dest.path() if hasattr(dest, "path") else str(dest)
        targets.setdefault(conn.outputIndex(), []).append(
            {"path": path, "input": conn.inputIndex()}
        )
    count = max(len(names), (max(targets) + 1) if targets else 0)
    return [
        {
            "index": i,
            "name": names[i] if i < len(names) else f"output{i + 1}",
            "to": targets.get(i, []),
        }
        for i in range(count)
    ]


_VALUELESS_TEMPLATES = ("Folder", "FolderSet", "Separator", "Label", "Button")


def _is_multiparm_block(template: Any) -> bool:
    import hou

    try:
        return template.folderType() in (
            hou.folderType.MultiparmBlock,
            hou.folderType.ScrollingMultiparmBlock,
            hou.folderType.TabbedMultiparmBlock,
        )
    except Exception:
        return False


def parm_rows(node: Any, include_defaults: bool) -> list[dict[str, Any]]:
    import hou

    from .parms import summarize_parm  # lazy: parms imports this module

    skip = {
        getattr(hou.parmTemplateType, n)
        for n in _VALUELESS_TEMPLATES
        if hasattr(hou.parmTemplateType, n)
    }
    rows = []
    for parm_tuple in node.parmTuples():
        try:
            template = parm_tuple.parmTemplate()
            # A multiparm's instance count is a Folder template too, and has a value.
            if template.type() in skip and not _is_multiparm_block(template):
                continue
            if not include_defaults and parm_tuple.isAtDefault():
                continue
        except Exception:
            continue
        rows.append(summarize_parm(parm_tuple))
    return rows


def node_block(
    node: Any,
    include: Iterable[str] = DEFAULT_INCLUDE,
    *,
    include_defaults: bool = False,
    recurse_locked: bool = False,
    problems: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``node_info`` block for one node (also returned by mutating node tools)."""
    sections = set(include)
    out: dict[str, Any] = {
        "path": node.path(),
        "name": node.name(),
        "session_id": node.sessionId(),
        "type": type_block(node.type()),
    }
    if "flags" in sections:
        out["flags"] = node_flags(node)
    if "inputs" in sections:
        out["inputs"] = input_rows(node)
    if "outputs" in sections:
        out["outputs"] = output_rows(node)
    if "parms" in sections:
        out["parms"] = parm_rows(node, include_defaults)
    if "errors" in sections or problems is not None:
        out.update(problems if problems is not None else collect_problems(node, cook=False))
    if _is_locked_hda(node) or inside_locked(node):
        out["hda_locked"] = True
    opaque = _is_locked_hda(node) and not recurse_locked
    if not opaque:
        with contextlib.suppress(Exception):
            out["children_count"] = len(node.children())
    if "children" in sections:
        if opaque:
            out["children"] = []
            out["children_hidden"] = "locked asset; pass recurse_locked: true to list its contents"
        else:
            names = [c.name() for c in node.children()]
            out["children"] = names[:CHILDREN_LIST_LIMIT]
            if len(names) > CHILDREN_LIST_LIMIT:
                out["children_truncated"] = True
    if "hda" in sections:
        out["hda"] = hda_block(node)
    if "comment" in sections:
        out["comment"] = node.comment()
    if "position" in sections:
        out["position"] = _round(node.position())
        with contextlib.suppress(Exception):
            out["color"] = _round(node.color().rgb())
    if "userdata" in sections:
        with contextlib.suppress(Exception):
            out["userdata"] = {
                k: v for k, v in node.userDataDict().items() if not k.startswith("___")
            }
    return out


def mutation_block(node: Any, **extra: Any) -> dict[str, Any]:
    """Compact per-node block for mutation results: path, type, flags, problems."""
    out: dict[str, Any] = {"path": node.path(), "name": node.name(), "type": node.type().name()}
    out.update(extra)
    out["flags"] = node_flags(node)
    out.update(cheap_cook_problems(node))
    return out


RETURN_MODES = ("full", "summary")
DEFAULT_RETURN = "summary"
"""1.1 (review 11 B5): mutation echoes are path, type and problems unless asked for more."""


def return_mode(args: dict[str, Any]) -> str:
    mode = args.get("return") or DEFAULT_RETURN
    if mode not in RETURN_MODES:
        raise bad_arg("'return' must be 'full' or 'summary'.")
    return mode


def _raw_text(parm: Any) -> Any:
    for getter in ("unexpandedString", "rawValue"):
        with contextlib.suppress(Exception):
            return getattr(parm, getter)()
    return None


def parm_state(node: Any) -> dict[str, tuple[Any, ...]]:
    """``{tuple name: raw component values}`` for the node's non-default parm tuples.

    Taken right after ``createNode`` (creation scripts have run), it tells the values a
    creation script set apart from the ones the call set (review 11 B5)."""
    out: dict[str, tuple[Any, ...]] = {}
    for parm_tuple in node.parmTuples():
        with contextlib.suppress(Exception):
            if not parm_tuple.isAtDefault():
                out[parm_tuple.name()] = tuple(_raw_text(p) for p in parm_tuple)
    return out


def call_edited_parms(
    node: Any, baseline: dict[str, tuple[Any, ...]], named: Iterable[str]
) -> set[str]:
    """Parm row names the call changed: those it named, and any whose raw value moved from
    ``baseline`` (a side effect of the call, such as a menu that rewrites another parm)."""
    keep: set[str] = set()
    for name in named:
        target = node.parm(name) or node.parmTuple(name)
        parm_tuple = target.tuple() if hasattr(target, "tuple") else target
        if parm_tuple is not None:
            keep.add(parm_tuple.name())
            if len(parm_tuple) == 1:
                keep.add(parm_tuple[0].name())
    for name, raw in parm_state(node).items():
        if baseline.get(name) != raw:
            keep.add(name)
            parm_tuple = node.parmTuple(name)
            if parm_tuple is not None and len(parm_tuple) == 1:
                keep.add(parm_tuple[0].name())
    return keep


def summary_block(
    node: Any, problems: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """``return: summary`` row: path, type and problems only."""
    problems = problems if problems is not None else cheap_cook_problems(node)
    out: dict[str, Any] = {"path": node.path(), "type": node.type().name(), **extra}
    for key in ("errors", "warnings", "cook_state", "hint"):
        if key in problems:
            out[key] = problems[key]
    return out


def collapse_problems(blocks: Iterable[dict[str, Any]]) -> None:
    """Report an identical errors/warnings list once: later rows point at the first one
    with ``errors_same_as`` / ``warnings_same_as`` (one upstream error repeats downstream)."""
    seen: dict[str, dict[tuple[str, ...], str]] = {"errors": {}, "warnings": {}}
    for block in blocks:
        if not isinstance(block, dict) or "path" not in block:
            continue
        for key, first in seen.items():
            values = block.get(key)
            if not values:
                continue
            signature = tuple(values)
            if signature in first:
                del block[key]
                block[f"{key}_same_as"] = first[signature]
            else:
                first[signature] = block["path"]


def watch_nodes(nodes: Iterable[Any]) -> None:
    """Have the ``events`` ring buffer record later changes to ``nodes`` (bible §4.7:
    "parms changed on nodes HocusPocus touched"). Call after the call's own changes, so
    they are not recorded. Main thread; never raises."""
    from . import events  # lazy: events imports this module

    for node in nodes:
        if node is not None:
            events.watch_node(node)


# -- rollback ---------------------------------------------------------------------


class Rollback:
    """Compensating actions run newest-first when a batch fails (see module docstring)."""

    def __init__(self) -> None:
        self._actions: list[Callable[[], Any]] = []

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


def to_tool_error(exc: BaseException, *, node: Any = None, op: str | None = None) -> ToolError:
    """Map an exception from a node operation to a ToolError (``internal`` if unknown).

    ``hou.OperationFailed`` (``destroy``, ``setName``, ``matchCurrentDefinition``,
    ``copyItems``...) is Houdini refusing a valid-looking request: ``name_collision`` for
    ``op="rename"``, else ``invalid_argument``, with ``hou_exception`` set.
    """
    if isinstance(exc, ToolError):
        return exc
    import hou

    text = hou_exception_text(exc)
    if isinstance(exc, hou.PermissionError):
        asset = locked_ancestor(node) if node is not None else None
        return ToolError(
            "locked",
            hou_message(exc),
            hint=(
                f"Unlock {asset.path()} with node_edit lock: false first."
                if asset is not None
                else "The node is not editable (locked asset or permission)."
            ),
            hou_exception=text,
        )
    if isinstance(exc, hou.InvalidInput):
        return ToolError(
            "invalid_input",
            hou_message(exc),
            hint="Check input indices with node_info include inputs.",
            hou_exception=text,
        )
    refusals = tuple(
        getattr(hou, name)
        for name in ("OperationFailed", "NameConflict", "InvalidNodeName", "MatchDefinitionError")
        if isinstance(getattr(hou, name, None), type)
    )
    if isinstance(exc, refusals):
        where = f" on {node.path()}" if node is not None else ""
        if op == "rename" or type(exc).__name__ == "NameConflict":
            return ToolError(
                "name_collision",
                f"Houdini refused the new name{where}: {hou_message(exc)}",
                hint="The name may be taken by a node, network box or sticky note; pick another.",
                hou_exception=text,
            )
        return ToolError(
            "invalid_argument",
            f"Houdini refused the operation{where}: {hou_message(exc)}",
            hint="Check the node's state (locked asset, type, name) with node_info and retry "
            "with different arguments.",
            hou_exception=text,
        )
    from ..dispatch import tool_error_from_exception

    return tool_error_from_exception(exc)


def batch_error(index: int, path: Any, exc: BaseException, *, rolled_back: bool) -> ToolError:
    """The one batch error shape (review 10 §4): ``items[i] (<path>): <message>`` and
    ``detail: {item, path, rolled_back}``, ``rolled_back`` as actually performed.

    A message that already names the item (``items[i].type ...``) or starts with its path
    is not repeated: the path appears once."""
    error = to_tool_error(exc)
    message = error.message
    tag = f"items[{index}]"
    if message.startswith(tag):
        message = message[len(tag) :].lstrip(".: ")
    elif isinstance(path, str) and path and message.startswith(path):
        rest = message[len(path) :]
        if rest.startswith(": "):
            message = rest[2:]
        elif rest.startswith(" "):
            message = "it" + rest
    shown = path if isinstance(path, str) and path else None
    error.message = f"{tag} ({shown}): {message}" if shown else f"{tag}: {message}"
    error.args = (error.message,)
    detail = error.detail if isinstance(error.detail, dict) else {}
    error.detail = {**detail, "item": index, "path": shown, "rolled_back": rolled_back}
    return error


def run_batch(
    items: list[Any],
    partial: bool,
    rollback: Rollback,
    apply: Callable[[Any, int], Any],
    path_of: Callable[[Any], Any],
) -> tuple[dict[int, Any], dict[int, dict[str, Any]]]:
    """Apply ``apply(item, index)`` to every item (BIBLE §4.1 batch semantics).

    A failure rolls back the whole call and raises :func:`batch_error`, or with
    ``partial`` rolls back that item only and records the error dict in ``failures``."""
    done: dict[int, Any] = {}
    failures: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(items):
        mark = rollback.mark()
        try:
            done[index] = apply(item, index)
        except Exception as exc:
            path = path_of(item) if isinstance(item, dict) else None
            if not partial:
                ok = rollback.run()
                raise batch_error(index, path, exc, rolled_back=ok) from exc
            ok = rollback.run(mark)
            failures[index] = batch_error(index, path, exc, rolled_back=ok).to_dict()
    return done, failures


# -- wiring helpers ---------------------------------------------------------------


def _labels_hint(node: Any) -> str:
    try:
        names = list(node.inputNames())
        labels = list(node.inputLabels())
        max_inputs = node.type().maxNumInputs()
    except Exception:
        return "Check the node's inputs with node_info include inputs."
    if not names and max_inputs == 0:
        return f"{node.path()} takes no inputs."
    shown = [
        f"{i}: {names[i]} ({labels[i] if i < len(labels) else ''})"
        for i in range(min(len(names), 10))
    ]
    text = f"Inputs of {node.path()}: " + "; ".join(shown)
    if max_inputs > len(names):
        text += f". Up to {max_inputs} inputs; use to_input 'next' to append."
    return text + "."


def resolve_input_index(node: Any, to_input: Any) -> int | str:
    """Return an input index, or ``"next"``. Raises invalid_input with labels."""
    if to_input is None:
        return 0
    if isinstance(to_input, bool):
        raise bad_arg("to_input must be an index, an input name or 'next'.")
    if isinstance(to_input, int):
        max_inputs = node.type().maxNumInputs()
        if to_input < 0 or to_input >= max(max_inputs, 0):
            raise ToolError(
                "invalid_input",
                f"{node.path()} has no input {to_input} (it takes {max_inputs}).",
                hint=_labels_hint(node),
                candidates=list(node.inputNames()),
            )
        return to_input
    if isinstance(to_input, str):
        if to_input == "next":
            return "next"
        if to_input.isdigit():
            return resolve_input_index(node, int(to_input))
        names = list(node.inputNames())
        if to_input in names:
            return names.index(to_input)
        labels = [label.lower() for label in node.inputLabels()]
        if to_input.lower() in labels:
            return labels.index(to_input.lower())
        raise ToolError(
            "invalid_input",
            f"{node.path()} has no input named {to_input!r}.",
            hint=_labels_hint(node),
            candidates=difflib.get_close_matches(to_input, names, n=5, cutoff=0.0)[:5] or names,
        )
    raise bad_arg("to_input must be an index, an input name or 'next'.")


def check_output_index(src: Any, output: Any) -> int:
    if output is None:
        return 0
    if not isinstance(output, int) or isinstance(output, bool) or output < 0:
        raise bad_arg("Output index must be a non-negative integer.")
    try:
        count = len(src.outputNames())
    except Exception:
        count = 1
    if output >= max(count, 1):
        names = list(src.outputNames()) if count else []
        raise ToolError(
            "invalid_input",
            f"{src.path()} has no output {output} (it has {count}).",
            hint="Outputs: " + "; ".join(f"{i}: {n}" for i, n in enumerate(names)) + ".",
        )
    return output


def connect(dest: Any, index: int | str, src: Any, output: int, rollback: Rollback | None) -> int:
    """Wire ``src``:``output`` into ``dest`` at ``index`` (or the next free input)."""
    import hou

    if src is not None and src.parent() != dest.parent():
        raise ToolError(
            "invalid_input",
            f"{src.path()} and {dest.path()} are in different networks.",
            hint="Connect nodes that share a parent; use an object_merge SOP to bring geometry across networks.",
        )
    previous = {c.inputIndex(): (c.inputNode(), c.outputIndex()) for c in dest.inputConnections()}
    try:
        if index == "next":
            if src is None:
                raise bad_arg("to_input 'next' needs a from node.")
            dest.setNextInput(src, output)
            now = {c.inputIndex() for c in dest.inputConnections()}
            added = sorted(now - set(previous))
            used = added[-1] if added else max(now) if now else 0
        else:
            dest.setInput(int(index), src, output)
            used = int(index)
    except hou.InvalidInput as exc:
        raise ToolError(
            "invalid_input",
            f"Cannot connect {src.path() if src is not None else 'nothing'} into {dest.path()} "
            f"input {index}.",
            hint=_labels_hint(dest),
            hou_exception=hou_exception_text(exc),
            candidates=list(dest.inputNames()),
        ) from exc
    if rollback is not None:
        old = previous.get(used)
        if old is None:
            rollback.add(lambda: dest.setInput(used, None))
        else:
            rollback.add(lambda: dest.setInput(used, old[0], old[1]))
    return used


# -- tools ------------------------------------------------------------------------


def _match(pattern: str, text: str) -> bool:
    import hou

    return bool(hou.text.patternMatch(pattern, text))


def _walk(root: Any, recurse_locked: bool) -> Iterable[Any]:
    stack = list(reversed(root.children()))
    while stack:
        node = stack.pop()
        yield node
        if _is_locked_hda(node) and not recurse_locked:
            continue
        with contextlib.suppress(Exception):
            stack.extend(reversed(node.children()))


CURSOR_AFTER = "after:"
"""``node_find`` cursors name the last returned path: rows are in path order, so inserts
and deletes between pages neither skip nor repeat rows."""


def path_key(path: str) -> tuple[str, ...]:
    """Sort key that keeps a node directly before its subtree."""
    return tuple(path.split("/"))


def _find_cursor(cursor: Any) -> tuple[str, ...] | int | None:
    if cursor in (None, ""):
        return None
    if isinstance(cursor, str) and cursor.startswith(CURSOR_AFTER + "/"):
        return path_key(cursor[len(CURSOR_AFTER) :])
    if isinstance(cursor, str) and cursor.isdigit():
        return int(cursor)  # an offset cursor from an older host; still honoured
    raise bad_arg(
        f"Invalid cursor {cursor!r}.",
        hint=CURSOR_HINT,
    )


def _has_errors(node: Any) -> bool:
    try:
        return bool(node.errors())
    except Exception:
        return False


def _locked_root_error(root: Any) -> ToolError:
    """The refusal ``node_find`` and ``network_describe`` share for a locked-asset root."""
    asset = root if _is_locked_hda(root) else (locked_ancestor(root) or root)
    return ToolError(
        "locked",
        f"{root.path()} is {'a' if asset is root else 'inside the'} locked asset "
        f"{asset.path()}; locked assets are opaque by default.",
        hint="Pass recurse_locked: true to read its contents.",
    )


@tool("node_find")
def node_find(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    from hocuspocus.tools.catalog import CATEGORIES

    root = get_node(args.get("root") or "/", field="root")
    pattern = args.get("pattern") or "*"
    type_pattern = args.get("type")
    category = args.get("category")
    flags = args.get("flags") or {}
    has_errors = args.get("has_errors")
    recurse_locked = arg_bool(args, "recurse_locked", False)
    if not isinstance(pattern, str):
        raise bad_arg("'pattern' must be a string glob.")
    if type_pattern is not None and not isinstance(type_pattern, str):
        raise bad_arg("'type' must be a string glob.")
    if category is not None and category not in CATEGORIES:
        raise bad_arg(
            f"Unknown category {category!r}.",
            hint="Categories: " + ", ".join(CATEGORIES) + ".",
            candidates=difflib.get_close_matches(str(category), CATEGORIES, n=3, cutoff=0.0),
        )
    if not isinstance(flags, dict) or any(k not in FLAG_NAMES for k in flags):
        raise bad_arg(f"'flags' keys must be among {', '.join(FLAG_NAMES)}.")
    if not recurse_locked and (inside_locked(root) or _is_locked_hda(root)):
        raise _locked_root_error(root)
    limit = parse_limit(args.get("limit"))
    after = _find_cursor(args.get("cursor"))
    # Pass 1: filter cheaply. errors() can be expensive, so it is read here only when
    # has_errors filters; otherwise only for the rows on the returned page.
    matches: list[tuple[Any, dict[str, bool], bool | None]] = []
    for node in _walk(root, recurse_locked):
        if pattern != "*" and not _match(pattern, node.name()):
            continue
        node_type = node.type()
        if type_pattern and not (
            _match(type_pattern, node_type.name())
            or _match(type_pattern, node_type.nameComponents()[2])
        ):
            continue
        if category and node_type.category().name() != category:
            continue
        node_flag_values = node_flags(node)
        if any(bool(node_flag_values.get(k, False)) != bool(v) for k, v in flags.items()):
            continue
        errored = None
        if has_errors is not None:
            errored = _has_errors(node)
            if errored != bool(has_errors):
                continue
        matches.append((node, node_flag_values, errored))
    matches.sort(key=lambda m: path_key(m[0].path()))
    if isinstance(after, int):
        start = after
    elif after is not None:
        start = next((i for i, m in enumerate(matches) if path_key(m[0].path()) > after), None)
        start = len(matches) if start is None else start
    else:
        start = 0
    budget = response_budget(ctx)
    used = ROW_ENVELOPE_BYTES + len(root.path())
    rows: list[dict[str, Any]] = []
    for node, node_flag_values, errored in matches[start : start + limit]:
        try:
            child_count = 0 if _is_locked_hda(node) and not recurse_locked else len(node.children())
        except Exception:
            child_count = 0
        node_type = node.type()
        row = {
            "path": node.path(),
            "type": node_type.name(),
            "category": node_type.category().name(),
            "flags": {k: True for k, v in node_flag_values.items() if v},
            "input_count": len(node.inputConnections()),
            "child_count": child_count,
            "has_errors": _has_errors(node) if errored is None else errored,
        }
        used += compact_size(row) + 1
        if rows and used > budget:
            break  # BIBLE §4.1: page by the byte budget too; next_cursor resumes here
        rows.append(row)
    result: dict[str, Any] = {"root": root.path(), "nodes": rows, "total": len(matches)}
    if rows and start + len(rows) < len(matches):
        result["next_cursor"] = CURSOR_AFTER + rows[-1]["path"]
    return result


@tool("node_info")
def node_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = arg_list(args, "paths")
    include = args.get("include")
    if include is None:
        include = list(DEFAULT_INCLUDE)
    if not isinstance(include, list) or any(s not in NODE_INFO_SECTIONS for s in include):
        bad = list(include) if isinstance(include, list) else include
        raise bad_arg(
            f"Unknown include section(s): {bad!r}.",
            hint="Sections: " + ", ".join(NODE_INFO_SECTIONS) + ".",
        )
    include_defaults = arg_bool(args, "include_defaults", False)
    recurse_locked = arg_bool(args, "recurse_locked", False)
    nodes = []
    for path in paths:
        node = get_node(path, field="paths")
        if inside_locked(node) and not recurse_locked:
            asset = locked_ancestor(node) or node
            raise ToolError(
                "locked",
                f"{node.path()} is inside the locked asset {asset.path()}; locked assets are "
                "opaque by default.",
                hint="Pass recurse_locked: true to read inside it.",
            )
        block = node_block(
            node, include, include_defaults=include_defaults, recurse_locked=recurse_locked
        )
        if node.type().category().name() == "Top":
            from .pdg import pdg_state  # lazy: TOP nodes only

            with contextlib.suppress(Exception):
                block["pdg_state"] = pdg_state(node)
        nodes.append(block)
        # events reports later changes to what the agent has read (review 15 papercut 3).
        watch_nodes([node])
    return {"nodes": nodes}


def _create_one(
    item: Any,
    index: int,
    args: dict[str, Any],
    ctx: HostContext,
    rollback: Rollback,
    created: dict[int, dict[str, tuple[Any, ...]]],
    pairs: dict[int, str],
    extras: dict[int, dict[str, Any]],
) -> Any:
    """Create one ``node_create`` item; ``created`` maps the new node's session id to its
    parm state right after ``createNode`` (see :func:`parm_state`), ``pairs`` to the
    ``block_begin`` a new ``block_end`` was paired with (see :func:`pair_block_end`),
    ``extras`` to the ``notes`` and ``side_effects`` its parms reported."""
    import hou

    if not isinstance(item, dict):
        raise bad_arg(f"items[{index}] must be an object.")
    parent = get_node(item.get("parent"), field="parent")
    ensure_can_hold_children(parent)
    type_name = item.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise bad_arg(f"items[{index}].type must be a non-empty string.")
    name = item.get("name")
    if name is not None:
        check_name(name)
        existing = parent.node(name)
        if existing is not None:
            free = unique_name(parent, name)
            raise ToolError(
                "name_collision",
                f"{existing.path()} already exists ({existing.type().name()}).",
                hint=f"Pick another name (e.g. {free!r}), omit name to let Houdini number it, "
                "or edit the existing node.",
                candidates=[free],
            )
    exact = arg_bool(args, "exact_type", False)
    node_type = resolve_type(parent, type_name, exact=exact)
    rollback.keep_display(parent)
    try:
        node = parent.createNode(node_type.name(), name, exact_type_name=True)
    except hou.PermissionError as exc:
        raise to_tool_error(exc, node=parent) from exc
    except hou.OperationFailed as exc:
        message = hou_message(exc)
        if "name" in message.lower() and "type" not in message.lower():
            raise bad_arg(
                f"Houdini rejected the node name {name!r}.",
                hint="Use letters, digits, '_', '.' and '-'.",
                hou_exception=hou_exception_text(exc),
            ) from exc
        raise type_not_found(parent, type_name, parent.childTypeCategory()) from exc
    rollback.destroy_later(node)
    created[node.sessionId()] = parm_state(node)
    note = deprecation_note(node.type())
    if note:
        extra = extras.setdefault(node.sessionId(), {})
        extra["deprecated"] = True
        extra.setdefault("notes", []).append(note)
    parms = item.get("parms")
    pressed: dict[str, Any] = {}
    if parms:
        if not isinstance(parms, dict):
            raise bad_arg(f"items[{index}].parms must be an object.")
        # A {value, press: true} entry runs its callback after the plain values are set
        # and the inputs are wired, as clicking it in the parameter pane would (review 20 N2).
        plain = {k: v for k, v in parms.items() if not _is_press(v)}
        pressed = {k: v for k, v in parms.items() if _is_press(v)}
        _set_create_parms(node, plain, ctx, extras)
    for link_index, link in enumerate(item.get("inputs") or []):
        if not isinstance(link, dict) or "from" not in link:
            raise bad_arg(
                f"items[{index}].inputs[{link_index}] must be {{index|name, from, output}}.",
            )
        if "index" in link and "name" in link:
            raise bad_arg(
                f"items[{index}].inputs[{link_index}]: pass index or name, not both.",
            )
        src = get_node(link["from"], field="inputs.from", relative_to=parent)
        target = link.get("name") if "name" in link else link.get("index", link_index)
        dest_index = resolve_input_index(node, target)
        output = check_output_index(src, link.get("output", 0))
        connect(node, dest_index, src, output, None)
    set_flags(node, item.get("flags"))
    if pressed:
        _set_create_parms(node, pressed, ctx, extras)
    begin = pair_block_end(node, rollback)
    if begin is not None:
        pairs[node.sessionId()] = begin.path()
    position = item.get("position")
    if position is not None:
        node.setPosition(arg_xy(position, f"items[{index}].position"))
    elif args.get("layout", "good_position") == "good_position":
        with contextlib.suppress(Exception):
            node.moveToGoodPosition(move_inputs=False, move_outputs=False, move_unconnected=False)
    return node


def _is_press(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("press") is True


def _set_create_parms(
    node: Any, parms: dict[str, Any], ctx: HostContext, extras: dict[int, dict[str, Any]]
) -> None:
    """Set ``node_create`` parms through the ``parm_set`` engine and keep what its results
    report: the skipped-callback note and a press's ``side_effects`` (review 20 N2)."""
    if not parms:
        return
    from .parms import CREATE_CALLBACK_NOTE, set_parm_items  # lazy: parms imports this module

    results = set_parm_items(
        node, parms, ctx, animation="replace", callback_note=CREATE_CALLBACK_NOTE
    )
    extra = extras.setdefault(node.sessionId(), {})
    for result in results:
        for note in result.get("notes") or ():
            extra.setdefault("notes", []).append(note)
        if result.get("side_effects"):
            extra.setdefault("side_effects", {}).update(result["side_effects"])


def deprecation_note(node_type: Any) -> str | None:
    """A note when ``hou.NodeType.deprecated()`` says the type is deprecated (the OpenGL
    ROP in 22.0, replaced by the Flipbook ROP), with its ``deprecationInfo()``."""
    try:
        if not node_type.deprecated():
            return None
    except Exception:
        return None
    info: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        info = dict(node_type.deprecationInfo() or {})
    text = f"{node_type.category().name()}/{node_type.name()} is deprecated"
    if info.get("version"):
        text += f" since Houdini {info['version']}"
    new_type = info.get("new_type")
    if new_type is not None and not isinstance(new_type, str):
        try:
            new_type = f"{new_type.category().name()}/{new_type.name()}"
        except Exception:
            new_type = None
    reason = str(info.get("reason") or "").strip()
    if reason:
        text += f": {reason.rstrip('.')}."
    else:
        text += "."
    if new_type:
        text += f" Its replacement is {new_type}."
    return text + " It still works for now."


def add_create_extras(block: dict[str, Any], extra: dict[str, Any] | None) -> None:
    """Put a created node's ``deprecated`` flag, parm ``side_effects`` and ``notes`` on its
    result row."""
    for key in ("deprecated", "side_effects", "notes"):
        if extra and extra.get(key):
            block[key] = extra[key]


BLOCK_BEGIN, BLOCK_END = "block_begin", "block_end"


def _core_type(node: Any) -> str:
    try:
        return node.type().nameComponents()[2]
    except Exception:
        return ""


def _parm_text(node: Any, name: str) -> str:
    parm = node.parm(name)
    if parm is None:
        return ""
    try:
        return parm.unexpandedString().strip()
    except Exception:
        return ""


def _block_partner(node: Any, parm: str = "blockpath") -> Any:
    text = _parm_text(node, parm)
    return node.node(text) if text else None


def pair_block_end(node: Any, rollback: Rollback) -> Any:
    """Pair a new ``block_end`` whose ``blockpath`` is unset with its ``block_begin``, as
    the Tab menu does (review 11 B12): the nearest begin upstream through the inputs, else
    the only unpaired begin in the same network. Sets the end's ``blockpath`` and
    ``templatepath`` and the begin's ``blockpath`` (where unset) to relative paths.
    Returns the begin, or None when there is nothing unambiguous to pair with."""
    if _core_type(node) != BLOCK_END or node.parm("blockpath") is None:
        return None
    if _parm_text(node, "blockpath"):
        return None  # the caller chose
    begin = None
    seen: set[int] = set()
    queue = [n for n in node.inputs() if n is not None]
    while queue and begin is None:
        current = queue.pop(0)
        if current.sessionId() in seen:
            continue
        seen.add(current.sessionId())
        partner = _block_partner(current)
        if _core_type(current) == BLOCK_BEGIN and (partner is None or partner == node):
            begin = current
            break
        queue.extend(n for n in current.inputs() if n is not None)
    if begin is None:
        loose = [
            child
            for child in node.parent().children()
            if _core_type(child) == BLOCK_BEGIN and _block_partner(child) is None
        ]
        if len(loose) != 1:
            return None
        begin = loose[0]
    node.parm("blockpath").set(node.relativePathTo(begin))
    template = node.parm("templatepath")
    if template is not None and not _parm_text(node, "templatepath"):
        template.set(node.relativePathTo(begin))
    back = begin.parm("blockpath")
    if back is not None and not _parm_text(begin, "blockpath"):
        back.set(begin.relativePathTo(node))
        rollback.add(lambda: back.set(""))
    return begin


def _create_item_path(item: dict[str, Any]) -> Any:
    """What a ``node_create`` error names: ``parent/name``, else the parent."""
    parent, name = item.get("parent"), item.get("name")
    if isinstance(parent, str) and isinstance(name, str) and name:
        return f"{parent.rstrip('/')}/{name}"
    return parent


@tool("node_create")
def node_create(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    layout = args.get("layout", "good_position")
    if layout not in ("good_position", "none"):
        raise bad_arg("'layout' must be 'good_position' or 'none'.")
    partial = arg_bool(args, "partial", False)
    mode = return_mode(args)
    rollback = Rollback()
    baselines: dict[int, dict[str, tuple[Any, ...]]] = {}
    pairs: dict[int, str] = {}
    extras: dict[int, dict[str, Any]] = {}
    done, failures = run_batch(
        items,
        partial,
        rollback,
        lambda item, index: _create_one(item, index, args, ctx, rollback, baselines, pairs, extras),
        _create_item_path,
    )
    created = list(done.items())  # item order
    if mode == "summary":
        blocks = {index: summary_block(node) for index, node in created}
    else:
        blocks = {}
        for index, node in created:
            block = node_block(node, DEFAULT_INCLUDE, problems=cheap_cook_problems(node))
            keep = call_edited_parms(
                node, baselines.get(node.sessionId(), {}), items[index].get("parms") or {}
            )
            block["parms"] = [row for row in block["parms"] if row["name"] in keep]
            blocks[index] = block  # parm rows elide long strings (summarize_parm)
    for index, node in created:
        if node.sessionId() in pairs:
            blocks[index]["paired_with"] = pairs[node.sessionId()]
        add_create_extras(blocks[index], extras.get(node.sessionId()))
    results = [blocks.get(i) or {"error": failures[i]} for i in range(len(items))]
    if mode == "summary":
        collapse_problems(results)
    out: dict[str, Any] = {"results": results, "created": [b["path"] for b in blocks.values()]}
    watch_nodes(node for _, node in created)
    if failures:
        out["failed"] = len(failures)
    return out


@tool("node_delete")
def node_delete(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = arg_list(args, "paths")
    keep = arg_bool(args, "keep_connections", True)
    nodes = []
    for path in paths:
        node = get_node(path, field="paths")
        if node.path() == "/" or node.parent() is None or node.parent().path() == "/":
            raise bad_arg(
                f"Refusing to delete the manager {node.path()}.",
                hint="Delete nodes inside it instead.",
            )
        ensure_editable(node, "delete")
        nodes.append(node)
    selected_paths = {n.path() for n in nodes}
    # Drop nodes whose ancestor is also being deleted, and duplicates.
    unique: list[Any] = []
    seen: set[str] = set()
    for node in nodes:
        path = node.path()
        if path in seen or any(path.startswith(p + "/") for p in selected_paths):
            continue
        seen.add(path)
        unique.append(node)
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
                    with contextlib.suppress(Exception):
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
                    with contextlib.suppress(Exception):
                        dest.setInput(conn.inputIndex(), None)
        try:
            node.destroy()
        except Exception as exc:
            raise to_tool_error(exc, node=node) from exc
        deleted.append(path)
        touched.pop(path, None)
    result: dict[str, Any] = {"deleted": deleted}
    if reconnected:
        alive = [n for p, n in touched.items() if p not in seen]
        result["reconnected"] = [r for r in reconnected if r["to"] not in seen]
        result["nodes"] = [mutation_block(n) for n in alive]
    return result


def _check_color(color: Any) -> tuple[float, float, float]:
    if (
        not isinstance(color, list)
        or len(color) != 3
        or not all(isinstance(c, int | float) and not isinstance(c, bool) for c in color)
    ):
        raise bad_arg("'color' must be [r, g, b] with 0-1 floats.")
    return float(color[0]), float(color[1]), float(color[2])


def _edit_one(item: Any, index: int, rollback: Rollback) -> dict[str, Any]:
    """Validate every field of one ``node_edit`` item, then apply it with ``lock`` last.

    ``lock: true`` runs ``matchCurrentDefinition()``, which discards edits made inside the
    asset; compensation cannot bring them back, so nothing may fail after it.
    """
    import hou

    if not isinstance(item, dict):
        raise bad_arg(f"items[{index}] must be an object.")
    node = get_node(item.get("path"))
    old_path = node.path()
    # -- validate ------------------------------------------------------------------
    lock = item.get("lock")
    if lock is not None:
        if not isinstance(lock, bool):
            raise bad_arg("'lock' must be a boolean.")
        if hda_block(node) is None:
            raise bad_arg(
                f"{node.path()} ({node.type().name()}) is not a digital asset; lock applies to HDAs.",
                hint="Use flags.bypass or the hard-lock flag for ordinary nodes.",
            )
        ensure_editable(node, "lock or unlock")
    else:
        ensure_editable(node, "edit")
    name = item.get("name")
    if name is not None and name != node.name():
        check_name(name)
        existing = node.parent().node(name)
        if existing is not None:
            free = unique_name(node.parent(), name)
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
    check_flags(node, flags)
    color = item.get("color")
    rgb = _check_color(color) if color is not None else None
    comment = item.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise bad_arg("'comment' must be a string.")
    position = item.get("position")
    xy = arg_xy(position, "position") if position is not None else None
    spare_plan = None
    if item.get("spare_parms") is not None:
        from .parms import plan_spare_parms  # lazy: parms imports this module

        # A locked asset's own instance takes spare parms (the wrangle "Create spare
        # parameters" button does that); nodes inside a locked asset were refused above.
        spare_plan = plan_spare_parms(node, item["spare_parms"])
    # -- apply ---------------------------------------------------------------------
    try:
        if name is not None:
            old_name = node.name()
            node.setName(name)
            rollback.add(lambda: node.setName(old_name))
    except hou.OperationFailed as exc:
        raise to_tool_error(exc, node=node, op="rename") from exc
    if flags:
        before = node_flags(node)
        rollback.keep_display(node.parent())

        def restore_flags(before: dict[str, bool] = before) -> None:
            for key, value in before.items():
                setter = getattr(node, _FLAG_SETTERS.get(key, ""), None)
                if callable(setter):
                    setter(value)

        rollback.add(restore_flags)
        set_flags(node, flags)
    if rgb is not None:
        old_color = node.color()
        node.setColor(hou.Color(rgb))
        rollback.add(lambda: node.setColor(old_color))
    if comment is not None:
        old_comment = node.comment()
        node.setComment(comment)
        rollback.add(lambda: node.setComment(old_comment))
        with contextlib.suppress(Exception):
            node.setGenericFlag(hou.nodeFlag.DisplayComment, bool(comment))
    if xy is not None:
        old_pos = node.position()
        node.setPosition(xy)
        rollback.add(lambda: node.setPosition(old_pos))
    spare = None
    if spare_plan is not None:
        from .parms import apply_spare_parms

        spare = apply_spare_parms(node, spare_plan, rollback)
    if lock is not None:
        was_locked = _is_locked_hda(node)
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
        extra["hda"] = hda_block(node)
    if spare is not None:
        extra["spare_parms"] = spare
    return {"node": node, "extra": extra}


@tool("node_edit")
def node_edit(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    partial = arg_bool(args, "partial", False)
    rollback = Rollback()
    done, failures = run_batch(
        items,
        partial,
        rollback,
        lambda item, index: _edit_one(item, index, rollback),
        lambda item: item.get("path"),
    )
    results = []
    for index in range(len(items)):
        if index in failures:
            results.append({"error": failures[index]})
            continue
        entry = done[index]
        node = entry["node"]
        block = mutation_block(node, **entry["extra"])
        block["comment"] = node.comment()
        block["position"] = _round(node.position())
        block["color"] = _round(node.color().rgb())
        results.append(block)
    watch_nodes(entry["node"] for entry in done.values())
    out: dict[str, Any] = {"results": results}
    if failures:
        out["failed"] = len(failures)
    return out


@tool("node_copy")
def node_copy(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    paths = arg_list(args, "paths")
    dest = get_node(args.get("to_parent"), field="to_parent")
    ensure_can_hold_children(dest, "copy nodes into")
    names = args.get("names") or []
    if not isinstance(names, list) or len(names) > len(paths):
        raise bad_arg("'names' must be a list no longer than 'paths'.")
    for name in names:
        check_name(name, "names")
    if len(set(names)) != len(names):
        raise bad_arg("'names' must not repeat.")
    with_inputs = arg_bool(args, "with_inputs", True)
    mode = return_mode(args)
    offset = args.get("position_offset")
    offset_xy = arg_xy(offset, "position_offset") if offset is not None else None
    sources = [get_node(p, field="paths") for p in paths]
    category = dest.childTypeCategory()
    for src in sources:
        if src.type().category() != category:
            raise bad_arg(
                f"{src.path()} is {a_or_an(src.type().category().name())} node; {dest.path()} holds "
                f"{category.name()} nodes.",
                hint="Copy into a network of the same context.",
            )
    for name in names:
        existing = dest.node(name)
        if existing is not None:
            free = unique_name(dest, name, names)
            raise ToolError(
                "name_collision",
                f"{existing.path()} already exists.",
                hint=f"Pick another name, e.g. {free!r}, or omit names to let Houdini number copies.",
                candidates=[free],
            )
    rollback = Rollback()
    try:
        copies = list(dest.copyItems(tuple(sources)))
    except hou.OperationFailed as exc:
        raise bad_arg(
            f"Houdini could not copy into {dest.path()}.",
            hint="All sources must share a context with to_parent.",
            hou_exception=hou_exception_text(exc),
        ) from exc
    copies = [c for c in copies if isinstance(c, hou.Node)]
    for copy in copies:
        rollback.destroy_later(copy)
    try:
        for copy, name in zip(copies, names, strict=False):
            try:
                copy.setName(name)
            except hou.OperationFailed as exc:
                raise to_tool_error(exc, node=copy, op="rename") from exc
        for copy in copies:
            if not with_inputs:
                for conn in copy.inputConnections():
                    copy.setInput(conn.inputIndex(), None)
            if offset_xy is not None:
                pos = copy.position()
                copy.setPosition((pos[0] + offset_xy[0], pos[1] + offset_xy[1]))
    except Exception as exc:
        rollback.run()
        raise to_tool_error(exc) from exc
    block = summary_block if mode == "summary" else mutation_block
    results = [block(copy, source=src.path()) for src, copy in zip(sources, copies, strict=False)]
    if mode == "summary":
        collapse_problems(results)
    watch_nodes(copies)
    return {"paths": [c.path() for c in copies], "results": results}


def _connect_one(item: Any, index: int, rollback: Rollback) -> dict[str, Any]:
    if not isinstance(item, dict) or "to" not in item or "from" not in item:
        raise bad_arg(f"items[{index}] needs 'from' (path or null) and 'to'.")
    dest = get_node(item.get("to"), field="to")
    ensure_editable(dest, "rewire")
    src_path = item.get("from")
    src = None if src_path is None else get_node(src_path, field="from", relative_to=dest.parent())
    to_input = item.get("to_input", 0)
    index_or_next = resolve_input_index(dest, to_input)
    if src is None:
        if index_or_next == "next":
            raise bad_arg(
                "to_input 'next' cannot disconnect.",
                hint="Pass the input index or name to disconnect.",
            )
        used = connect(dest, index_or_next, None, 0, rollback)
        output = 0
    else:
        output = check_output_index(src, item.get("from_output", 0))
        used = connect(dest, index_or_next, src, output, rollback)
    names = list(dest.inputNames())
    return {
        "node": dest,
        "extra": {
            "input": used,
            "input_name": names[used] if used < len(names) else f"input{used + 1}",
            "from": src.path() if src is not None else None,
            "from_output": output,
        },
    }


@tool("node_connect")
def node_connect(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    partial = arg_bool(args, "partial", False)
    rollback = Rollback()
    done, failures = run_batch(
        items,
        partial,
        rollback,
        lambda item, index: _connect_one(item, index, rollback),
        lambda item: item.get("to"),
    )
    results = []
    for index in range(len(items)):
        if index in failures:
            results.append({"error": failures[index]})
            continue
        entry = done[index]
        block = mutation_block(entry["node"], **entry["extra"])
        block["to"] = block["path"]
        results.append(block)
    watch_nodes(entry["node"] for entry in done.values())
    out: dict[str, Any] = {"results": results}
    if failures:
        out["failed"] = len(failures)
    return out


@tool("node_layout")
def node_layout(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    parent = get_node(args.get("parent"), field="parent")
    ensure_can_hold_children(parent, "lay out")
    mode = args.get("mode", "children")
    if mode not in ("children", "good_position"):
        raise bad_arg("'mode' must be 'children' or 'good_position'.")
    raw_paths = arg_list(args, "paths", required=False)
    nodes = [get_node(p, field="paths", relative_to=parent) for p in raw_paths]
    for node in nodes:
        if node.parent() != parent:
            raise bad_arg(
                f"{node.path()} is not a child of {parent.path()}.",
                hint="paths must be children of parent.",
            )
    if mode == "children":
        if nodes:
            parent.layoutChildren(items=tuple(nodes))
        else:
            parent.layoutChildren()
        moved = nodes or list(parent.children())
    else:
        moved = nodes or list(parent.children())
        for node in moved:
            node.moveToGoodPosition()
    rows = [{"path": n.path(), "position": _round(n.position())} for n in moved]
    chunk = rows[:CHILDREN_LIST_LIMIT]
    out: dict[str, Any] = {
        "parent": parent.path(),
        "mode": mode,
        "nodes": chunk,
        "count": len(rows),
    }
    if len(rows) > len(chunk):
        out["truncated"] = True
    return out
