"""Network tools: ``network_describe`` and ``network_build`` over Houdini's ``hou.data`` format.

See docs/BIBLE.md §4.4, §5.10 and decision D6. ``network_describe`` returns
``childrenAsData(...)`` trimmed for agents; ``network_build`` validates the same shape and
applies it with ``setChildrenFromData``.

Verified against 22.0.466 (and why validation is ours, not Houdini's):

- ``setChildrenFromData`` silently skips unknown types, unknown parms, unresolvable input
  sources and out-of-range input indices; inputs without ``to_index`` all land on input 0.
- An invalid name raises *after* creating a sanitised node, and ``clear_content`` defaults
  to True (it would destroy the parent's existing children), so it is always passed False.
- On a locked HDA it replaces the asset's contents, so locked parents are refused.
- It does not run node init scripts: a rebuilt ``geo`` object has no render-property spare
  parms unless the data carries them as ``parmtemplates``.
- ``childrenAsData(position=False)`` still emits ``position``; positions are stripped here.
- It sets parms without running their callback scripts, as a plain ``parm.set`` does: a
  menu such as pyrosource's ``initialize`` keeps its token and applies nothing. Such parms
  get a note, and the ``press`` argument runs them after the build (1.4).
"""

from __future__ import annotations

import contextlib
import difflib
import json
import os
from typing import Any

from hocuspocus.tools.errors import ToolError

from . import nodes as N
from .registry import HostContext, tool

SPECIAL_TYPES = frozenset({"StickyNote", "NetworkDot", "NetworkBox", "SubnetIndirectInput"})
ON_COLLISION = ("error", "rename", "replace")
TAG_KEY = "hocuspocus:tag"
CHANGED_KEY = "_changed"
"""Result marker the dispatcher reads (``host/dispatch.py``): False means nothing changed."""
MAX_PROBLEMS = 20


# -- network_describe ---------------------------------------------------------------


def _trim_templates(templates: Any, keep: set[str]) -> Any:
    """Drop render-property spare templates (tagged ``spare_category``) the data doesn't set.

    Every ``geo`` object carries ~40 of them (~10 KB). Templates whose parm has a value in
    the node's ``parms`` are kept so the data still rebuilds that value.
    """
    if isinstance(templates, list):
        out = [t for t in (_trim_templates(t, keep) for t in templates) if t]
        return out
    if isinstance(templates, dict) and isinstance(templates.get("parmtemplates"), dict | list):
        children = _trim_templates(templates["parmtemplates"], keep)
        if not children:
            return None
        return {**templates, "parmtemplates": children}
    if isinstance(templates, dict):
        kept = {}
        for name, template in templates.items():
            if not isinstance(template, dict):
                kept[name] = template
                continue
            nested = template.get("parmtemplates")
            if nested is not None:
                trimmed = _trim_templates(nested, keep)
                if trimmed:
                    kept[name] = {**template, "parmtemplates": trimmed}
                continue
            tags = template.get("tags") or {}
            if "spare_category" in tags and name not in keep:
                continue
            kept[name] = template
        return kept
    return templates


def _locked_children_data(node: Any, opts: dict[str, Any]) -> dict[str, Any]:
    import hou

    try:
        data = hou.data.itemsAsData(list(node.children()), **opts)
    except Exception:
        data = None
    if not isinstance(data, dict):
        data = {child.name(): {"type": child.type().name()} for child in node.children()}
    return data


DESCRIBE_MAX_NODES = 2000
"""Node cap for one ``network_describe`` page, whatever the byte budget allows."""


class _Budget:
    """Byte and node budget for one ``network_describe`` page (BIBLE §4.1, default 16 KB)."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.nodes = 0

    @property
    def nodes_left(self) -> bool:
        return self.nodes < DESCRIBE_MAX_NODES


def _clean_entry(entry: dict[str, Any], positions: bool) -> None:
    if not positions:
        entry.pop("position", None)
    if "parmtemplates" in entry:
        keep = set((entry.get("parms") or {}).keys())
        trimmed = _trim_templates(entry["parmtemplates"], keep)
        if trimmed:
            entry["parmtemplates"] = trimmed
        else:
            entry.pop("parmtemplates")


def _expand(
    entry: dict[str, Any],
    node: Any,
    level: int,
    *,
    depth: int,
    positions: bool,
    recurse_locked: bool,
    opts: dict[str, Any],
    budget: _Budget,
) -> int:
    """Clean one entry and, while ``level < depth``, read and attach its children one level
    at a time (``childrenAsData`` never serialises more than the level it is asked for).
    Returns the number of nodes added below ``entry``."""
    _clean_entry(entry, positions)
    entry.pop("children", None)
    if node is None:
        return 0
    locked = N._is_locked_hda(node)
    if locked:
        entry["hda_locked"] = True  # BIBLE §4.1: locked is the SOP lock flag, not this
    if level >= depth or (locked and not recurse_locked):
        return 0
    try:
        if not node.children():
            return 0
    except Exception:
        return 0
    if not budget.nodes_left:
        entry["children_truncated"] = True
        return 0
    try:
        children = (
            _locked_children_data(node, opts) if locked else node.childrenAsData(**opts)
        ) or {}
    except Exception:
        return 0
    added = 0
    for name, child in children.items():
        if not isinstance(child, dict):
            continue
        added += 1
        budget.nodes += 1
        added += _expand(
            child,
            node.node(name),
            level + 1,
            depth=depth,
            positions=positions,
            recurse_locked=recurse_locked,
            opts=opts,
            budget=budget,
        )
    if children:
        entry["children"] = children
    return added


DESCRIBE_CURSOR = "after:"
FORMATS = ("data", "python", "outline")
OUTLINE_DEPTH = 2
"""``format: outline`` reads two levels unless ``depth`` says otherwise (review 11 B11)."""


def _error_count(node: Any) -> int:
    try:
        return len(node.errors())
    except Exception:
        return 0


_SHIPPED_LIBRARIES: dict[str, bool] = {}


def _shipped_asset(node: Any) -> bool:
    """True when ``node``'s asset definition comes from a library under ``$HFS``."""
    try:
        library = node.type().definition().libraryFilePath()
    except Exception:
        return False
    if library not in _SHIPPED_LIBRARIES:
        shipped = False
        with contextlib.suppress(Exception):
            import hou

            hfs = os.path.normcase(os.path.realpath(hou.text.expandString("$HFS")))
            lib = os.path.normcase(os.path.realpath(library))
            shipped = lib.startswith(os.path.join(hfs, ""))
        _SHIPPED_LIBRARIES[library] = shipped
    return _SHIPPED_LIBRARIES[library]


def _outline_inputs(node: Any) -> list[str | None]:
    """Source path per input slot; ``"<path>:<n>"`` when the source's output ``n`` is not
    0 (review 23 papercut 5: Vellum's constraint output wired as geometry was invisible)."""
    try:
        sources = list(node.inputs())
    except Exception:
        return []
    outputs: dict[int, int] = {}
    try:
        for conn in node.inputConnections():
            outputs[conn.inputIndex()] = conn.outputIndex()
    except Exception:
        pass
    while sources and sources[-1] is None:
        sources.pop()
    return [
        None if source is None else source.path() + (f":{outputs[i]}" if outputs.get(i, 0) else "")
        for i, source in enumerate(sources)
    ]


def _outline_entry(
    node: Any, level: int, *, depth: int, recurse_locked: bool, budget: _Budget
) -> dict[str, Any]:
    """``{path, name, type, children_count?, display?, errors, inputs?, flags?, hda_locked?,
    children?}``: no parms, so a whole scene fits in one page (``houdini://outline``).

    ``inputs`` (1.2, review 12 papercut 4) lists the source node path per input slot
    (``path:n`` for output ``n`` > 0, 1.4), with
    ``null`` for an empty slot before a wired one, and is left out when nothing is wired;
    ``flags`` lists only the flags that are on (``["display", "render"]``), left out when
    none is.

    ``children_count`` is left out at 0. ``hda_locked`` marks only locked assets that are
    not shipped with Houdini: ``attribwrangle``, ``mountain`` and other SOPs from
    ``$HFS/houdini/otls`` are locked assets too (BIBLE §4.1; their contents appear once
    they cook), which flagged every wrangle of review 12 (papercut 4) and told the agent
    nothing it could act on. ``node_info`` still reports ``hda_locked`` for them."""
    locked = N._is_locked_hda(node)
    opaque = locked and not recurse_locked
    try:
        children = [] if opaque else list(node.children())
    except Exception:
        children = []
    entry: dict[str, Any] = {
        "path": node.path(),
        "name": node.name(),
        "type": node.type().name(),
    }
    if children:
        entry["children_count"] = len(children)
    display = getattr(node, "displayNode", None)
    if callable(display) and children:
        with contextlib.suppress(Exception):
            shown = display()
            if shown is not None:
                entry["display"] = shown.path()
    entry["errors"] = _error_count(node)
    inputs = _outline_inputs(node)
    if inputs:
        entry["inputs"] = inputs
    flags = [name for name, on in N.node_flags(node).items() if on]
    if flags:
        entry["flags"] = flags
    if locked and not _shipped_asset(node):
        entry["hda_locked"] = True
    if level < depth and children:
        if not budget.nodes_left:
            entry["children_truncated"] = True
            return entry
        rows = []
        for child in children:
            budget.nodes += 1
            rows.append(
                _outline_entry(
                    child, level + 1, depth=depth, recurse_locked=recurse_locked, budget=budget
                )
            )
            if not budget.nodes_left:
                break
        if len(rows) < len(children):
            entry["children_truncated"] = True
        entry["children"] = rows
    return entry


def _outline(
    root: Any, *, depth: int, recurse_locked: bool, cursor: Any, ctx: HostContext
) -> dict[str, Any]:
    """``network_describe format: outline``: one compact row per node, paged at the
    response budget by top-level child like ``format: data``."""
    if N._is_locked_hda(root) and not recurse_locked:
        children: list[Any] = []
    else:
        children = list(root.children())
    names = [c.name() for c in children]
    start = 0
    if cursor:
        after = cursor[len(DESCRIBE_CURSOR) :]
        if after not in names:
            raise N.bad_arg(
                f"The cursor's node {after!r} is no longer in {root.path()}.",
                hint="The network changed between pages; call network_describe again without cursor.",
            )
        start = names.index(after) + 1
    budget = _Budget(N.response_budget(ctx))
    used = N.ROW_ENVELOPE_BYTES + len(root.path())
    rows: list[dict[str, Any]] = []
    count = 0
    truncated = False
    more = False
    for child in children[start:]:
        if rows and not budget.nodes_left:
            truncated = more = True
            break
        before = budget.nodes
        budget.nodes += 1
        entry = _outline_entry(child, 1, depth=depth, recurse_locked=recurse_locked, budget=budget)
        size = N.compact_size(entry) + 1
        if rows and used + size > budget.max_bytes:
            budget.nodes = before
            truncated = more = True
            break
        if used + size > budget.max_bytes and "children" in entry:
            entry.pop("children")  # one entry alone overflows: keep it, without its subtree
            entry["children_truncated"] = True
            budget.nodes = before + 1
            size = N.compact_size(entry) + 1
        rows.append(entry)
        count = budget.nodes
        used += size
    result: dict[str, Any] = {
        "root": root.path(),
        "format": "outline",
        "nodes": rows,
        "node_count": count,
    }
    if truncated or any(_has_truncated_children(e) for e in rows):
        result["truncated"] = True
    if more and rows:
        result["next_cursor"] = DESCRIBE_CURSOR + rows[-1]["name"]
    return result


@tool("network_describe")
def network_describe(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    root = N.get_node(args.get("root"), field="root")
    fmt = args.get("format", "data") or "data"
    if fmt not in FORMATS:
        raise N.bad_arg(f"'format' must be one of {', '.join(FORMATS)}.")
    depth = args.get("depth")
    if depth is None:
        depth = OUTLINE_DEPTH if fmt == "outline" else 1
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
        raise N.bad_arg("'depth' must be an integer >= 1.")
    include_defaults = N.arg_bool(args, "include_defaults", False)
    positions = N.arg_bool(args, "include_positions", False)
    recurse_locked = N.arg_bool(args, "recurse_locked", False)
    cursor = args.get("cursor")
    if cursor not in (None, "") and (
        not isinstance(cursor, str) or not cursor.startswith(DESCRIBE_CURSOR)
    ):
        raise N.bad_arg(
            f"Invalid cursor {cursor!r}.",
            hint=N.CURSOR_HINT,
        )
    if not recurse_locked and (
        N.inside_locked(root) or (fmt != "python" and N._is_locked_hda(root))
    ):
        raise N._locked_root_error(root)
    # events reports renames and edits of what the agent has described (review 15
    # papercut 3: a user rename of /obj/sky surfaced only as a failed call).
    if not N._is_locked_hda(root):
        N.watch_nodes([root, *root.children()])
    if fmt == "outline":
        return _outline(root, depth=depth, recurse_locked=recurse_locked, cursor=cursor, ctx=ctx)
    if fmt == "python":
        code = root.asCode(brief=True, recurse=False)
        return {"root": root.path(), "format": "python", "code": code, "bytes": len(code.encode())}
    opts = {
        "inputs": True,
        "flags": True,
        "position": positions,
        "default_parmvalues": include_defaults,
        "parmtemplates": "spare_only",
        "children": False,
    }
    if N._is_locked_hda(root):
        top = _locked_children_data(root, opts)
    else:
        try:
            top = root.childrenAsData(**opts)
        except Exception as exc:  # e.g. a node that is not a network
            raise N.bad_arg(
                f"Cannot describe {root.path()} as a network.",
                hint="root must be a network (e.g. /obj, a geo object, a subnet); use node_info for a leaf node.",
                hou_exception=N.hou_exception_text(exc),
            ) from exc
    top = top or {}
    names = list(top)
    start = 0
    if cursor:
        after = cursor[len(DESCRIBE_CURSOR) :]
        if after not in top:
            raise N.bad_arg(
                f"The cursor's node {after!r} is no longer in {root.path()}.",
                hint="The network changed between pages; call network_describe again without cursor.",
            )
        start = names.index(after) + 1
    budget = _Budget(N.response_budget(ctx))
    used = N.ROW_ENVELOPE_BYTES + len(root.path())
    data: dict[str, Any] = {}
    count = 0
    truncated = False
    next_name: str | None = None
    for name in names[start:]:
        entry = top[name]
        if not isinstance(entry, dict):
            continue
        if data and not budget.nodes_left:
            truncated, next_name = True, name
            break
        before_nodes = budget.nodes
        budget.nodes += 1
        added = 1 + _expand(
            entry,
            root.node(name),
            1,
            depth=depth,
            positions=positions,
            recurse_locked=recurse_locked,
            opts=opts,
            budget=budget,
        )
        size = N.compact_size({name: entry})
        if data and used + size > budget.max_bytes:
            budget.nodes = before_nodes
            truncated, next_name = True, name
            break
        if used + size > budget.max_bytes and "children" in entry:
            entry.pop("children")  # one entry alone overflows: keep it, without its subtree
            entry["children_truncated"] = True
            truncated = True
            added = 1
            size = N.compact_size({name: entry})
        data[name] = entry
        count += added
        used += size
    result: dict[str, Any] = {
        "root": root.path(),
        "format": "data",
        "data": data,
        "node_count": count,
        "bytes": N.compact_size(data),
    }
    if truncated or any(isinstance(e, dict) and _has_truncated_children(e) for e in data.values()):
        result["truncated"] = True
    if next_name is not None and data:
        result["next_cursor"] = DESCRIBE_CURSOR + list(data)[-1]
    return result


def _has_truncated_children(entry: dict[str, Any]) -> bool:
    if entry.get("children_truncated"):
        return True
    children = entry.get("children")
    if isinstance(children, dict):  # format data
        children = list(children.values())
    return isinstance(children, list) and any(
        isinstance(c, dict) and _has_truncated_children(c) for c in children
    )


# -- network_build --------------------------------------------------------------------


class _Problems:
    def __init__(self) -> None:
        self.items: list[ToolError] = []

    def add(self, error: ToolError, where: str) -> None:
        error.detail = {**(error.detail if isinstance(error.detail, dict) else {}), "at": where}
        self.items.append(error)

    def raise_if_any(self) -> None:
        if not self.items:
            return
        rows = []
        for error in self.items[:MAX_PROBLEMS]:
            row = {"code": error.code, "message": error.message, "at": error.detail.get("at")}
            if error.hint:
                row["hint"] = error.hint
            if error.candidates:
                row["candidates"] = error.candidates
            rows.append(row)
        first = self.items[0]
        if len(self.items) > 1:
            first.message = f"{first.message} (+{len(self.items) - 1} more problem(s))"
            first.args = (first.message,)
        first.detail = {"problems": rows}
        raise first


def _output_count(node_type: Any = None, node: Any = None) -> int:
    counts = []
    with contextlib.suppress(Exception):
        counts.append(int((node_type or node.type()).maxNumOutputs()))
    if node is not None:
        with contextlib.suppress(Exception):
            counts.append(len(node.outputNames()))
    return max(counts) if counts else 1


def _validate_level(
    data: Any,
    *,
    category: Any,
    container: Any,
    prefix: str,
    problems: _Problems,
    plan: list[dict[str, Any]],
    warnings: list[str],
    existing_names: set[str],
) -> None:
    """Validate one level of hou.data in place (types resolved, input indices filled)."""
    import hou

    if not isinstance(data, dict):
        problems.add(
            N.bad_arg(
                f"Children of {prefix or 'the parent'} must be an object of name -> node data.",
            ),
            prefix or "/",
        )
        return
    names = set(data)
    # Pass 1 resolves every type, so input checks can size a sibling's outputs; problems
    # are reported in entry order (pass 2).
    resolved: dict[str, Any] = {}
    early: dict[str, ToolError] = {}
    for name, entry in data.items():
        where = f"{prefix}{name}"
        if not isinstance(name, str) or not N.NAME_RE.match(name):
            early[name] = N.bad_arg(
                f"{name!r} is not a valid node name.",
                hint="Node names use letters, digits, '_', '.' and '-' only.",
            )
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            early[name] = N.bad_arg(
                f"{where}: each entry needs a string 'type'.",
                hint="data maps node names to {type, parms?, inputs?, flags?, children?}; "
                "pass the 'data' field of network_describe.",
            )
            continue
        type_name = entry["type"]
        if type_name in SPECIAL_TYPES:
            continue
        node_type = None
        with contextlib.suppress(Exception):
            node_type = hou.nodeType(category, type_name) or hou.preferredNodeType(
                f"{category.name()}/{type_name}", container
            )
        if node_type is None:
            candidates = N.type_candidates(category, type_name)
            early[name] = ToolError(
                "node_type_not_found",
                f"{where}: no {category.name()} node type {type_name!r}.",
                hint=(
                    f"Closest {category.name()} types: {', '.join(candidates[:5])}."
                    if candidates
                    else "Use node_type_search to find the type name."
                ),
                candidates=candidates,
            )
            continue
        if node_type.name() != type_name:
            entry["type"] = node_type.name()
        resolved[name] = node_type
        plan.append({"name": where, "type": node_type.name()})
    for name in data:
        where = f"{prefix}{name}"
        if name in early:
            problems.add(early[name], where)
            continue
        if name not in resolved:
            continue  # a network box, sticky note, dot or indirect input
        node_type = resolved[name]
        entry = data[name]
        parms = entry.get("parms")
        if parms is not None and not isinstance(parms, dict):
            problems.add(N.bad_arg(f"{where}: 'parms' must be an object."), where)
        inputs = entry.get("inputs")
        if inputs is not None:
            if not isinstance(inputs, list):
                problems.add(N.bad_arg(f"{where}: 'inputs' must be a list."), where)
            else:
                _validate_inputs(
                    inputs,
                    node_type,
                    where=where,
                    prefix=prefix,
                    names=names,
                    resolved=resolved,
                    existing_names=existing_names,
                    container=container,
                    problems=problems,
                )
        children = entry.get("children")
        if children is not None:
            child_category = node_type.childTypeCategory()
            if entry.get("hda_locked"):
                entry.pop("children")
                warnings.append(
                    f"{where}: children of the locked asset {node_type.name()} were ignored; "
                    "the asset provides its own contents."
                )
            elif child_category is None:
                problems.add(
                    N.bad_arg(
                        f"{where}: {node_type.name()} is not a network and cannot have children.",
                    ),
                    where,
                )
            else:
                _validate_level(
                    children,
                    category=child_category,
                    container=None,
                    prefix=f"{where}/",
                    problems=problems,
                    plan=plan,
                    warnings=warnings,
                    existing_names=set(),
                )
        for key in ("locked", "hda_locked", "children_truncated"):
            entry.pop(key, None)


def _validate_inputs(
    inputs: list[Any],
    node_type: Any,
    *,
    where: str,
    prefix: str,
    names: set[str],
    resolved: dict[str, Any],
    existing_names: set[str],
    container: Any,
    problems: _Problems,
) -> None:
    max_inputs = node_type.maxNumInputs()
    seen: dict[Any, int] = {}
    for position, link in enumerate(inputs):
        if not isinstance(link, dict) or not isinstance(link.get("from"), str):
            problems.add(
                N.bad_arg(
                    f"{where}: inputs[{position}] needs a string 'from'.",
                    hint="Input entries look like {from: 'box1', from_index: 0, to_index: 0}.",
                ),
                where,
            )
            continue
        source = link["from"]
        existing = None
        if source not in names and container is not None:
            with contextlib.suppress(Exception):
                existing = container.node(source)
        if source not in names and source not in existing_names and existing is None:
            known = sorted(names | existing_names)
            problems.add(
                ToolError(
                    "node_not_found",
                    f"{where}: input source {source!r} is neither in data nor in "
                    f"{prefix.rstrip('/') or 'the parent'}.",
                    hint="'from' names a sibling in data or an existing child of parent.",
                    candidates=difflib.get_close_matches(source, known, n=5, cutoff=0.5),
                ),
                where,
            )
        from_index = link.get("from_index", 0)
        if not isinstance(from_index, int) or isinstance(from_index, bool) or from_index < 0:
            problems.add(
                N.bad_arg(f"{where}: inputs[{position}].from_index must be an integer >= 0."),
                where,
            )
        else:
            outputs = None
            if source in resolved:
                outputs = _output_count(resolved[source])
            elif existing is not None:
                outputs = _output_count(node=existing)
            if outputs is not None and from_index >= max(outputs, 1):
                problems.add(
                    ToolError(
                        "invalid_input",
                        f"{where}: {source} has no output {from_index} (it has {outputs}).",
                        hint=f"Valid from_index values for {source} are 0..{max(outputs, 1) - 1}.",
                    ),
                    where,
                )
        if "to_index" not in link:
            link["to_index"] = position
        to_index = link["to_index"]
        if isinstance(to_index, int) and not isinstance(to_index, bool):
            if to_index < 0 or to_index >= max_inputs:
                problems.add(
                    ToolError(
                        "invalid_input",
                        f"{where}: {node_type.name()} has no input {to_index} "
                        f"(it takes {max_inputs}).",
                        hint=f"Valid to_index values are 0..{max_inputs - 1}."
                        if max_inputs
                        else f"{node_type.name()} takes no inputs.",
                    ),
                    where,
                )
        elif not isinstance(to_index, str):
            problems.add(
                N.bad_arg(f"{where}: to_index must be an integer or an input name."),
                where,
            )
            continue
        if to_index in seen:
            problems.add(
                ToolError(
                    "invalid_input",
                    f"{where}: inputs[{seen[to_index]}] and inputs[{position}] both feed "
                    f"to_index {to_index}.",
                    hint="Each input takes one connection; give every entry its own to_index.",
                ),
                where,
            )
        else:
            seen[to_index] = position


def _rename_refs(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    out = {}
    for name, entry in data.items():
        if isinstance(entry, dict):
            for link in entry.get("inputs") or []:
                if isinstance(link, dict) and link.get("from") in mapping:
                    link["from"] = mapping[link["from"]]
        out[mapping.get(name, name)] = entry
    return out


def _verify_level(
    data: dict[str, Any], container: Any, prefix: str, problems: _Problems
) -> list[Any]:
    """After the build: every node exists, every parm exists, every input is wired."""

    made = []
    for name, entry in data.items():
        where = f"{prefix}{name}"
        if entry.get("type") in SPECIAL_TYPES:
            continue
        node = container.node(name)
        if node is None:
            problems.add(
                N.bad_arg(
                    f"Houdini did not create {where} ({entry.get('type')}).",
                    hint="Check the entry's type and name.",
                ),
                where,
            )
            continue
        made.append(node)
        for parm_name in entry.get("parms") or {}:
            if node.parmTuple(parm_name) is None and node.parm(parm_name) is None:
                names = [pt.name() for pt in node.parmTuples()]
                problems.add(
                    ToolError(
                        "parm_not_found",
                        f"{where}: no parm {parm_name!r} on {node.type().name()}.",
                        hint="Use node_type_info to list the type's parms.",
                        candidates=difflib.get_close_matches(parm_name, names, n=5, cutoff=0.5),
                    ),
                    where,
                )
        connected = {c.inputIndex(): c for c in node.inputConnections()}
        input_names = list(node.inputNames())
        for link in entry.get("inputs") or []:
            to_index = link.get("to_index", 0)
            if isinstance(to_index, str):
                index = input_names.index(to_index) if to_index in input_names else None
            else:
                index = to_index
            if index is None or index not in connected:
                problems.add(
                    ToolError(
                        "invalid_input",
                        f"{where}: input {to_index!r} from {link.get('from')!r} was not connected.",
                        hint=N._labels_hint(node),
                        candidates=input_names,
                    ),
                    where,
                )
                continue
            conn = connected[index]
            fed = conn.inputItem() if hasattr(conn, "inputItem") else conn.inputNode()
            expected = None
            with contextlib.suppress(Exception):
                expected = container.node(link.get("from")) or container.item(link.get("from"))
            if expected is None:
                continue  # e.g. a subnet's indirect input: nothing to compare against
            want_output = link.get("from_index", 0)
            if fed is None or fed != expected or conn.outputIndex() != want_output:
                got = fed.name() if fed is not None and hasattr(fed, "name") else "nothing"
                problems.add(
                    ToolError(
                        "invalid_input",
                        f"{where}: input {to_index!r} is fed by {got} output "
                        f"{conn.outputIndex()}, not {link.get('from')!r} output {want_output}.",
                        hint="Check the entry's inputs: from names a sibling in data or an "
                        "existing child of parent.",
                        candidates=input_names,
                    ),
                    where,
                )
        children = entry.get("children")
        if isinstance(children, dict):
            made.extend(_verify_level(children, node, f"{where}/", problems))
    return made


def _data_paths(data: dict[str, Any], prefix: str = "") -> list[str]:
    """Every node in ``data`` as a path relative to the parent (``geo1/src``)."""
    out: list[str] = []
    for name, entry in data.items():
        if not isinstance(entry, dict) or entry.get("type") in SPECIAL_TYPES:
            continue
        out.append(prefix + name)
        if isinstance(entry.get("children"), dict):
            out.extend(_data_paths(entry["children"], f"{prefix}{name}/"))
    return out


def _press_plan(
    press: Any, data: dict[str, Any], parent: Any, renamed: dict[str, str]
) -> dict[str, list[str]]:
    """Validate ``press: {node: [parm names]}`` against ``data`` (before the build, so a
    dry run checks it too). A node is a path relative to ``parent`` or an absolute path
    under it, and must be built by this call. Returns ``{relative path: names}``."""
    if press is None:
        return {}
    if not isinstance(press, dict):
        raise N.bad_arg("'press' must be an object {node: [parm names]}.")
    base = parent.path().rstrip("/") + "/"
    known = _data_paths(data)
    plan: dict[str, list[str]] = {}
    for key, names in press.items():
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(n, str) and n for n in names)
        ):
            raise N.bad_arg(f"press[{key!r}] must be a non-empty list of parm names.")
        rel = key[len(base) :] if key.startswith(base) else key
        head, _, rest = rel.partition("/")
        rel = renamed.get(head, head) + (f"/{rest}" if rest else "")
        if rel not in known:
            raise N.bad_arg(
                f"press names {key!r}, which this call does not build.",
                hint="press keys are nodes in data, relative to parent (geo1/src) or absolute.",
                candidates=difflib.get_close_matches(rel, known, n=5, cutoff=0.0)[:5] or known[:5],
            )
        plan.setdefault(rel, []).extend(names)
    return plan


def _callback_notes(
    data: dict[str, Any], container: Any, plan: dict[str, list[str]], prefix: str = ""
) -> list[str]:
    """A note for each menu or toggle that data set and whose callback did not run
    (``setChildrenFromData`` runs none; review 20 N2), unless ``press`` ran it."""
    from .parms import NETWORK_CALLBACK_NOTE, skips_callback

    notes: list[str] = []
    for name, entry in data.items():
        if not isinstance(entry, dict) or entry.get("type") in SPECIAL_TYPES:
            continue
        node = container.node(name)
        if node is None:
            continue
        rel = prefix + name
        for parm_name in entry.get("parms") or {}:
            parm = node.parm(parm_name)
            if parm is None or parm_name in plan.get(rel, ()):
                continue
            with contextlib.suppress(Exception):
                if skips_callback(parm):
                    notes.append(
                        NETWORK_CALLBACK_NOTE.format(path=parm.path(), key=rel, name=parm_name)
                    )
        if isinstance(entry.get("children"), dict):
            notes.extend(_callback_notes(entry["children"], node, plan, f"{rel}/"))
    return notes


def _run_presses(
    parent: Any, plan: dict[str, list[str]], ctx: HostContext
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Run the planned callbacks through the ``parm_set`` press engine, in ``press``
    order. Returns the pressed parm paths and ``side_effects`` per node path."""
    from .parms import set_parm_items

    pressed: list[str] = []
    effects: dict[str, dict[str, Any]] = {}
    for rel, names in plan.items():
        node = parent.node(rel)
        for name in names:
            (row,) = set_parm_items(node, {name: {"press": True}}, ctx)
            pressed.append(row.get("path") or f"{node.path()}/{name}")
            if row.get("side_effects"):
                effects.setdefault(node.path(), {}).update(row["side_effects"])
    return pressed, effects


def prepare_build(parent: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Validate a ``network_build`` call (or an ``edit`` build op) against ``parent``
    without changing anything: ``data`` normalised (types resolved, input indices filled,
    renamed for ``on_name_collision: rename``), the node ``plan``, ``renamed``,
    ``replaced``, ``warnings`` and the ``press`` plan. Raises the first problem with
    ``detail.problems`` listing all of them."""
    N.ensure_can_hold_children(parent, "build in")
    data = args.get("data")
    if not isinstance(data, dict) or not data:
        raise N.bad_arg(
            "'data' must be a non-empty object of node name -> node data.",
            hint="Pass the 'data' field of network_describe, e.g. {box1: {type: box}}.",
        )
    if set(data) >= {"root", "data"} and isinstance(data.get("data"), dict):
        raise N.bad_arg(
            "'data' looks like a whole network_describe result.",
            hint="Pass its 'data' field instead.",
        )
    on_collision = args.get("on_name_collision", "error") or "error"
    if on_collision not in ON_COLLISION:
        raise N.bad_arg(f"on_name_collision must be one of {', '.join(ON_COLLISION)}.")
    layout = N.arg_bool(args, "layout", True)
    dry_run = N.arg_bool(args, "dry_run", False)
    mode = N.return_mode(args)
    tag = args.get("tag")
    if tag is not None and not isinstance(tag, str):
        raise N.bad_arg("'tag' must be a string.")

    data = json.loads(json.dumps(data))  # private copy: validation normalises in place
    existing = {c.name() for c in parent.children()}
    # Network boxes, sticky notes and dots share the namespace (Houdini would give the
    # new node another name) but are not nodes: they are never "replaced".
    items = (
        {item.name() for item in parent.allItems()} - existing
        if hasattr(parent, "allItems")
        else set()
    )
    collisions = [name for name in data if name in existing]
    item_collisions = [name for name in data if name in items]
    problems = _Problems()
    renamed: dict[str, str] = {}
    if (collisions or item_collisions) and on_collision == "error":
        clashing = collisions + item_collisions
        suggestions = []
        taken = set(data) | items
        for name in clashing:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            suggestions.append(free)
        problems.add(
            ToolError(
                "name_collision",
                f"{len(clashing)} name(s) already exist in {parent.path()}: "
                + ", ".join(clashing[:10]),
                hint="Pass on_name_collision: 'rename' to build under free names, 'replace' to "
                "swap the existing nodes out (downstream wires move to the new ones), or "
                "rename the entries in data.",
                candidates=suggestions,
            ),
            parent.path(),
        )
    elif item_collisions and on_collision == "replace":
        problems.add(
            ToolError(
                "name_collision",
                f"{', '.join(item_collisions[:10])} in {parent.path()} is a network box, sticky "
                "note or dot, not a node; replace only swaps nodes.",
                hint="Rename the entries in data, or pass on_name_collision: 'rename'.",
                candidates=[N.unique_name(parent, n, set(data) | items) for n in item_collisions],
            ),
            parent.path(),
        )
    elif (collisions or item_collisions) and on_collision == "rename":
        taken = set(data) | existing | items
        for name in collisions + item_collisions:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            renamed[name] = free
        data = _rename_refs(data, renamed)
    press_plan = _press_plan(args.get("press"), data, parent, renamed)
    plan: list[dict[str, Any]] = []
    warnings: list[str] = []
    # Existing children stay referencable by name except those being replaced/renamed away.
    referencable = existing - set(collisions) if on_collision != "error" else existing
    _validate_level(
        data,
        category=parent.childTypeCategory(),
        container=parent,
        prefix=parent.path().rstrip("/") + "/",
        problems=problems,
        plan=plan,
        warnings=warnings,
        existing_names=referencable,
    )
    problems.raise_if_any()
    return {
        "data": data,
        "plan": plan,
        "renamed": renamed,
        "replaced": collisions if on_collision == "replace" else [],
        "existing": existing,
        "warnings": warnings,
        "press": press_plan,
        "layout": layout,
        "dry_run": dry_run,
        "mode": mode,
        "tag": tag,
    }


@tool("network_build")
def network_build(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    parent = N.get_node(args.get("parent"), field="parent")
    N.ensure_can_hold_children(parent, "build in")
    data = args.get("data")
    if not isinstance(data, dict) or not data:
        raise N.bad_arg(
            "'data' must be a non-empty object of node name -> node data.",
            hint="Pass the 'data' field of network_describe, e.g. {box1: {type: box}}.",
        )
    if set(data) >= {"root", "data"} and isinstance(data.get("data"), dict):
        raise N.bad_arg(
            "'data' looks like a whole network_describe result.",
            hint="Pass its 'data' field instead.",
        )
    on_collision = args.get("on_name_collision", "error") or "error"
    if on_collision not in ON_COLLISION:
        raise N.bad_arg(f"on_name_collision must be one of {', '.join(ON_COLLISION)}.")
    layout = N.arg_bool(args, "layout", True)
    dry_run = N.arg_bool(args, "dry_run", False)
    mode = N.return_mode(args)
    tag = args.get("tag")
    if tag is not None and not isinstance(tag, str):
        raise N.bad_arg("'tag' must be a string.")

    data = json.loads(json.dumps(data))  # private copy: validation normalises in place
    existing = {c.name() for c in parent.children()}
    # Network boxes, sticky notes and dots share the namespace (Houdini would give the
    # new node another name) but are not nodes: they are never "replaced".
    items = (
        {item.name() for item in parent.allItems()} - existing
        if hasattr(parent, "allItems")
        else set()
    )
    collisions = [name for name in data if name in existing]
    item_collisions = [name for name in data if name in items]
    problems = _Problems()
    renamed: dict[str, str] = {}
    if (collisions or item_collisions) and on_collision == "error":
        clashing = collisions + item_collisions
        suggestions = []
        taken = set(data) | items
        for name in clashing:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            suggestions.append(free)
        problems.add(
            ToolError(
                "name_collision",
                f"{len(clashing)} name(s) already exist in {parent.path()}: "
                + ", ".join(clashing[:10]),
                hint="Pass on_name_collision: 'rename' to build under free names, 'replace' to "
                "swap the existing nodes out (downstream wires move to the new ones), or "
                "rename the entries in data.",
                candidates=suggestions,
            ),
            parent.path(),
        )
    elif item_collisions and on_collision == "replace":
        problems.add(
            ToolError(
                "name_collision",
                f"{', '.join(item_collisions[:10])} in {parent.path()} is a network box, sticky "
                "note or dot, not a node; replace only swaps nodes.",
                hint="Rename the entries in data, or pass on_name_collision: 'rename'.",
                candidates=[N.unique_name(parent, n, set(data) | items) for n in item_collisions],
            ),
            parent.path(),
        )
    elif (collisions or item_collisions) and on_collision == "rename":
        taken = set(data) | existing | items
        for name in collisions + item_collisions:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            renamed[name] = free
        data = _rename_refs(data, renamed)
    press_plan = _press_plan(args.get("press"), data, parent, renamed)
    plan: list[dict[str, Any]] = []
    warnings: list[str] = []
    # Existing children stay referencable by name except those being replaced/renamed away.
    referencable = existing - set(collisions) if on_collision != "error" else existing
    _validate_level(
        data,
        category=parent.childTypeCategory(),
        container=parent,
        prefix=parent.path().rstrip("/") + "/",
        problems=problems,
        plan=plan,
        warnings=warnings,
        existing_names=referencable,
    )
    problems.raise_if_any()
    replaced = collisions if on_collision == "replace" else []
    if dry_run:
        out: dict[str, Any] = {
            "parent": parent.path(),
            "dry_run": True,
            "plan": plan,
            "node_count": len(plan),
        }
        if renamed:
            out["renamed"] = renamed
        if replaced:
            out["replaces"] = [f"{parent.path().rstrip('/')}/{n}" for n in replaced]
        if warnings:
            out["warnings"] = warnings
        out[CHANGED_KEY] = False  # a dry run changes nothing: no undo step, no dirty
        return out

    rollback = N.Rollback()
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
        rollback.run()
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
    verify = _Problems()
    made = _verify_level(data, parent, parent.path().rstrip("/") + "/", verify)
    if verify.items:
        rollback.run()
        verify.raise_if_any()
    # Callbacks run after the whole build is wired, as clicking them would (review 20 N2),
    # and before replaced nodes are deleted, so a failed press still rolls back cleanly.
    try:
        pressed, side_effects = _run_presses(parent, press_plan, ctx)
    except Exception:
        rollback.run()
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
        old.destroy()
    if layout and top_nodes:
        with contextlib.suppress(Exception):
            parent.layoutChildren(items=tuple(top_nodes))
    if tag:
        for node in top_nodes:
            node.setUserData(TAG_KEY, tag)
    N.watch_nodes(made)
    result: dict[str, Any] = {
        "parent": parent.path(),
        "dry_run": False,
        "created": [n.path() for n in top_nodes],
        "created_count": len(made),
        "nodes": [
            N.summary_block(n) if mode == "summary" else N.mutation_block(n) for n in top_nodes
        ],
    }
    if mode == "summary":
        N.collapse_problems(result["nodes"])
    if renamed:
        result["renamed"] = {
            f"{parent.path().rstrip('/')}/{k}": f"{parent.path().rstrip('/')}/{v}"
            for k, v in renamed.items()
        }
    if replaced:
        result["replaced"] = [f"{parent.path().rstrip('/')}/{n}" for n in replaced]
    if warnings:
        result["warnings"] = warnings
    if pressed:
        result["pressed"] = pressed
    if side_effects:
        result["side_effects"] = side_effects
    notes = _callback_notes(data, parent, press_plan)
    if notes:
        result["notes"] = notes
    return result
