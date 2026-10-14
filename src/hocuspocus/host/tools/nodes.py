"""Node tools: find, info, create, delete, edit, copy, connect, layout.

See docs/BIBLE.md §4.4 and §5. Node paths are identity and results carry final resolved
paths. Every mutation result reports each touched node's ``errors/warnings`` after a
cheap cook (``_diag.cheap_cook_problems``).

The mutation tools (``node_create``, ``node_delete``, ``node_edit``, ``node_copy``,
``node_connect``, ``node_layout``) are plan builders over the transaction engine
(``host/tx.py``, spec-2.0 principle 14): it runs their items as ops and rolls a failing
call back by compensation (:class:`Rollback`, re-exported here), because
``hou.undos.performUndo()`` refuses to run inside the dispatcher's open undo group. Each
tool shapes the engine's per-op results into its 1.4 result.
"""

from __future__ import annotations

import contextlib
import difflib
import re
from collections.abc import Iterable
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import BARE, hint_tool

from .. import tx
from ..tx import Rollback  # noqa: F401 (re-exported: the compensation the batch tools share)
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
from ._diag import a_or_an, cheap_cook_problems, collect_problems, missing_node_error
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
        hint=f"Unlock it with {hint_tool('node_edit', path=asset.path(), lock=False)} "
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
        hint = (
            f"Closest {category.name()} types: {', '.join(candidates[:5])}. "
            f"{hint_tool('node_type_search', query=type_name)} finds types by label."
        )
    else:
        hint = f"{hint_tool('node_type_search', query=type_name)} finds the type name."
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


def mutation_block(node: Any, *, cook: bool = True, **extra: Any) -> dict[str, Any]:
    """Compact per-node block for mutation results: path, type, flags, problems. Without
    ``cook`` the problems are read as they are (``cook_state`` from ``needsToCook()``)."""
    out: dict[str, Any] = {"path": node.path(), "name": node.name(), "type": node.type().name()}
    out.update(extra)
    out["flags"] = node_flags(node)
    out.update(cheap_cook_problems(node) if cook else collect_problems(node, cook=False))
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
    if "cook_time_ms" in problems:
        # Review 22 finding 2: a slow create is usually Houdini's first cook of an HDA.
        out["cook_ms"] = problems["cook_time_ms"]
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


# -- errors -----------------------------------------------------------------------


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
                f"Unlock {asset.path()} with "
                f"{hint_tool('node_edit', path=asset.path(), lock=False)} first."
                if asset is not None
                else "The node is not editable (locked asset or permission)."
            ),
            hou_exception=text,
        )
    if isinstance(exc, hou.InvalidInput):
        return ToolError(
            "invalid_input",
            hou_message(exc),
            hint=f"Check input indices with {_inputs_call(node)}.",
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
            hint=f"Check the node's state (locked asset, type, name) with "
            f"{hint_tool('node_info', paths=[node.path() if node is not None else BARE])} and "
            "retry with different arguments.",
            hou_exception=text,
        )
    from ..dispatch import tool_error_from_exception

    return tool_error_from_exception(exc)


ABOUT_KEY = "_about"
"""A ToolError ``detail`` key naming the node the error is about when that is not the
item's own path; :func:`batch_error` puts it in the message prefix and ``detail.path``."""


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
    about = error.detail.pop(ABOUT_KEY, None) if isinstance(error.detail, dict) else None
    if isinstance(about, str) and about:
        path = about  # the error is about another node than the item's (a wiring source)
        if message.startswith(path):
            message = message[len(path) :].lstrip(": ")
    shown = path if isinstance(path, str) and path else None
    error.message = f"{tag} ({shown}): {message}" if shown else f"{tag}: {message}"
    error.args = (error.message,)
    detail = error.detail if isinstance(error.detail, dict) else {}
    error.detail = {**detail, "item": index, "path": shown, "rolled_back": rolled_back}
    return error


# -- wiring helpers ---------------------------------------------------------------


def _inputs_call(node: Any) -> str | None:
    """The read that lists ``node``'s inputs, as the call's profile names it."""
    try:
        path = node.path()
    except Exception:
        path = BARE
    return hint_tool("node_info", paths=[path], include=["inputs"])


def _labels_hint(node: Any) -> str:
    try:
        names = list(node.inputNames())
        labels = list(node.inputLabels())
        max_inputs = node.type().maxNumInputs()
    except Exception:
        return f"Check the node's inputs with {_inputs_call(node)}."
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
    out: dict[str, Any] = {"nodes": nodes}
    if any("cook_state" in block for block in nodes):
        from .session import viewport_note  # docs/parity.md G2

        note = viewport_note(ctx, "cook_state")
        if note:
            out["notes"] = [note]
    return out


_DEPRECATION_NOTED: set[str] = set()
"""Types whose deprecation note ``node_create`` has given in this host session: later rows
of the type carry only ``deprecated: true``."""


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


# -- the 1.4 mutation tools: plan builders over the transaction engine (host/tx.py) ------
# Each builds a tx.Plan from its 1.4 arguments and shapes tx.execute's per-op results
# into its 1.4 result (spec-2.0 principle 14: one undo policy, one rollback, one engine).


@tool("node_create")
def node_create(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    layout = args.get("layout", "good_position")
    if layout not in ("good_position", "none"):
        raise bad_arg("'layout' must be 'good_position' or 'none'.")
    partial = arg_bool(args, "partial", False)
    cook = arg_bool(args, "cook", True)
    mode = return_mode(args)
    opts = {"exact_type": args.get("exact_type"), "cook": cook, "layout": layout}
    plan = tx.Plan([tx.Op("create", item, opts=opts) for item in items], partial=partial)
    result = tx.execute(plan, ctx)
    state, failures = result.state, result.failures
    created = [(res.index, res.node) for res in result.done()]  # item order

    def problems_of(node: Any) -> dict[str, Any]:
        return cheap_cook_problems(node) if cook else collect_problems(node, cook=False)

    if mode == "summary":
        blocks = {index: summary_block(node, problems_of(node)) for index, node in created}
    else:
        blocks = {}
        for index, node in created:
            problems = problems_of(node)
            block = node_block(node, DEFAULT_INCLUDE, problems=problems)
            if "cook_time_ms" in problems:
                block["cook_ms"] = block.pop("cook_time_ms")
            keep = call_edited_parms(
                node, state.baselines.get(node.sessionId(), {}), items[index].get("parms") or {}
            )
            block["parms"] = [row for row in block["parms"] if row["name"] in keep]
            blocks[index] = block  # parm rows elide long strings (summarize_parm)
    for index, node in created:
        if node.sessionId() in state.pairs:
            blocks[index]["paired_with"] = state.pairs[node.sessionId()]
        add_create_extras(blocks[index], state.extras.get(node.sessionId()))
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
    plan = tx.Plan([tx.Op("delete", args)], raw_errors=True)
    data = tx.execute(plan, ctx).results[0].data
    result: dict[str, Any] = {"deleted": data["deleted"]}
    if data["any_reconnected"]:
        result["reconnected"] = data["reconnected"]
        result["nodes"] = [mutation_block(n) for n in data["alive"]]
    return result


@tool("node_edit")
def node_edit(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    partial = arg_bool(args, "partial", False)
    result = tx.execute(tx.Plan([tx.Op("node", item) for item in items], partial=partial), ctx)
    results = []
    for res in result.results:
        if res.error is not None:
            results.append({"error": res.error})
            continue
        node = res.node
        # Review 22 finding 3: a rename recooked a mountain HDA (~200 ms). An edit reports
        # problems as they are; only cook and creates cook.
        block = mutation_block(node, cook=False, **res.extra)
        block["comment"] = node.comment()
        block["position"] = _round(node.position())
        block["color"] = _round(node.color().rgb())
        results.append(block)
    watch_nodes(res.node for res in result.done())
    out: dict[str, Any] = {"results": results}
    if result.failures:
        out["failed"] = len(result.failures)
    return out


@tool("node_copy")
def node_copy(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    mode = return_mode(args)
    data = tx.execute(tx.Plan([tx.Op("copy", args)], raw_errors=True), ctx).results[0].data
    sources, copies = data["sources"], data["copies"]
    block = summary_block if mode == "summary" else mutation_block
    results = [block(copy, source=src.path()) for src, copy in zip(sources, copies, strict=False)]
    if mode == "summary":
        collapse_problems(results)
    watch_nodes(copies)
    return {"paths": [c.path() for c in copies], "results": results}


def _connect_source(src_path: Any, dest: Any, field: str = "from") -> Any:
    """The ``from`` node of a wiring item. A missing one is reported by its own path, with
    near misses from its parent (never ``dest``) and a ``node_find`` hint on that parent
    (review 21 papercut 4: the error named the target and offered it as the candidate)."""
    import hou

    try:
        return get_node(src_path, field=field, relative_to=dest.parent())
    except ToolError as exc:
        if exc.code != "node_not_found":
            raise
    full = (
        src_path if src_path.startswith("/") else f"{dest.parent().path().rstrip('/')}/{src_path}"
    )
    full = hou.hscriptExpandString(full) if "$" in full else full
    error = missing_node_error(
        full,
        message=f"{full}: no node there to wire into {dest.path()} ({field}).",
        exclude=dest,
    )
    error.detail = {ABOUT_KEY: full}
    raise error


connect_source = _connect_source
"""The wiring-source lookup under the name the transaction engine (``host/tx.py``) uses."""


@tool("node_connect")
def node_connect(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = arg_list(args, "items")
    partial = arg_bool(args, "partial", False)
    result = tx.execute(tx.Plan([tx.Op("connect", item) for item in items], partial=partial), ctx)
    results = []
    for res in result.results:
        if res.error is not None:
            results.append({"error": res.error})
            continue
        block = mutation_block(res.node, **res.extra)
        block["to"] = block["path"]
        results.append(block)
    watch_nodes(res.node for res in result.done())
    out: dict[str, Any] = {"results": results}
    if result.failures:
        out["failed"] = len(result.failures)
    return out


@tool("node_layout")
def node_layout(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    data = tx.execute(tx.Plan([tx.Op("layout", args)], raw_errors=True), ctx).results[0].data
    parent, moved = data["parent"], data["moved"]
    rows = [{"path": n.path(), "position": _round(n.position())} for n in moved]
    chunk = rows[:CHILDREN_LIST_LIMIT]
    out: dict[str, Any] = {
        "parent": parent.path(),
        "mode": data["mode"],
        "nodes": chunk,
        "count": len(rows),
    }
    if len(rows) > len(chunk):
        out["truncated"] = True
    return out
