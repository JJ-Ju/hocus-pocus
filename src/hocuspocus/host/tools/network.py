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
"""

from __future__ import annotations

import contextlib
import difflib
import json
from typing import Any

from hocuspocus.tools.errors import ToolError

from . import nodes as N
from .registry import HostContext, tool

SPECIAL_TYPES = frozenset({"StickyNote", "NetworkDot", "NetworkBox", "SubnetIndirectInput"})
ON_COLLISION = ("error", "rename", "replace")
TAG_KEY = "hocuspocus:tag"
MAX_PROBLEMS = 20


def _compact_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str).encode("utf-8"))


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


def _postprocess(
    data: dict[str, Any],
    container: Any,
    level: int,
    *,
    depth: int,
    positions: bool,
    recurse_locked: bool,
    opts: dict[str, Any],
) -> int:
    count = 0
    for name, entry in list(data.items()):
        if not isinstance(entry, dict):
            continue
        count += 1
        if not positions:
            entry.pop("position", None)
        if "parmtemplates" in entry:
            keep = set((entry.get("parms") or {}).keys())
            trimmed = _trim_templates(entry["parmtemplates"], keep)
            if trimmed:
                entry["parmtemplates"] = trimmed
            else:
                entry.pop("parmtemplates")
        node = container.node(name) if container is not None else None
        if node is not None and N._is_locked_hda(node):
            entry["locked"] = True
            entry.pop("children", None)
            if recurse_locked and level < depth:
                children = _locked_children_data(node, opts)
                count += _postprocess(
                    children,
                    node,
                    level + 1,
                    depth=depth,
                    positions=positions,
                    recurse_locked=recurse_locked,
                    opts=opts,
                )
                if children:
                    entry["children"] = children
            continue
        if "children" in entry:
            if level >= depth or not isinstance(entry["children"], dict):
                entry.pop("children")
            else:
                count += _postprocess(
                    entry["children"],
                    node,
                    level + 1,
                    depth=depth,
                    positions=positions,
                    recurse_locked=recurse_locked,
                    opts=opts,
                )
    return count


@tool("network_describe")
def network_describe(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    root = N.get_node(args.get("root"), field="root")
    depth = args.get("depth", 1)
    if depth is None:
        depth = 1
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
        raise N.bad_arg("'depth' must be an integer >= 1.")
    include_defaults = N.arg_bool(args, "include_defaults", False)
    positions = N.arg_bool(args, "include_positions", False)
    recurse_locked = N.arg_bool(args, "recurse_locked", False)
    fmt = args.get("format", "data") or "data"
    if fmt not in ("data", "python"):
        raise N.bad_arg("'format' must be 'data' or 'python'.")
    if not recurse_locked and (N.inside_locked(root) or (fmt == "data" and N._is_locked_hda(root))):
        asset = root if N._is_locked_hda(root) else (N.locked_ancestor(root) or root)
        raise ToolError(
            "locked",
            f"{root.path()} is {'a' if asset is root else 'inside the'} locked asset "
            f"{asset.path()}; locked assets are opaque by default.",
            hint="Pass recurse_locked: true to read its contents.",
        )
    if fmt == "python":
        code = root.asCode(brief=True, recurse=False)
        return {"root": root.path(), "format": "python", "code": code, "bytes": len(code.encode())}
    opts = {
        "inputs": True,
        "flags": True,
        "position": positions,
        "default_parmvalues": include_defaults,
        "parmtemplates": "spare_only",
        "children": depth > 1,
    }
    if N._is_locked_hda(root):
        data = _locked_children_data(root, opts)
    else:
        try:
            data = root.childrenAsData(**opts)
        except Exception as exc:  # e.g. a node that is not a network
            raise N.bad_arg(
                f"Cannot describe {root.path()} as a network.",
                hint="root must be a network (e.g. /obj, a geo object, a subnet); use node_info for a leaf node.",
                hou_exception=N.hou_exception_text(exc),
            ) from exc
    data = data or {}
    count = _postprocess(
        data, root, 1, depth=depth, positions=positions, recurse_locked=recurse_locked, opts=opts
    )
    return {
        "root": root.path(),
        "format": "data",
        "data": data,
        "node_count": count,
        "bytes": _compact_bytes(data),
    }


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
    for name, entry in data.items():
        where = f"{prefix}{name}"
        if not isinstance(name, str) or not N.NAME_RE.match(name):
            problems.add(
                N.bad_arg(
                    f"{name!r} is not a valid node name.",
                    hint="Node names use letters, digits, '_', '.' and '-' only.",
                ),
                where,
            )
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            problems.add(
                N.bad_arg(
                    f"{where}: each entry needs a string 'type'.",
                    hint="data maps node names to {type, parms?, inputs?, flags?, children?}; "
                    "pass the 'data' field of network_describe.",
                ),
                where,
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
            problems.add(
                ToolError(
                    "node_type_not_found",
                    f"{where}: no {category.name()} node type {type_name!r}.",
                    hint=(
                        f"Closest {category.name()} types: {', '.join(candidates[:5])}."
                        if candidates
                        else "Use node_type_search to find the type name."
                    ),
                    candidates=candidates,
                ),
                where,
            )
            continue
        if node_type.name() != type_name:
            entry["type"] = node_type.name()
        plan.append({"name": where, "type": node_type.name()})
        parms = entry.get("parms")
        if parms is not None and not isinstance(parms, dict):
            problems.add(N.bad_arg(f"{where}: 'parms' must be an object."), where)
        inputs = entry.get("inputs")
        if inputs is not None:
            if not isinstance(inputs, list):
                problems.add(N.bad_arg(f"{where}: 'inputs' must be a list."), where)
            else:
                max_inputs = node_type.maxNumInputs()
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
                    if (
                        source not in names
                        and source not in existing_names
                        and not ("/" in source and container is not None and container.node(source))
                    ):
                        known = sorted(names | existing_names)

                        problems.add(
                            ToolError(
                                "node_not_found",
                                f"{where}: input source {source!r} is neither in data nor in "
                                f"{prefix.rstrip('/') or 'the parent'}.",
                                hint="'from' names a sibling in data or an existing child of parent.",
                                candidates=difflib.get_close_matches(
                                    source, known, n=5, cutoff=0.5
                                ),
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
                            N.bad_arg(
                                f"{where}: to_index must be an integer or an input name.",
                            ),
                            where,
                        )
        children = entry.get("children")
        if children is not None:
            child_category = node_type.childTypeCategory()
            if entry.get("locked"):
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
        entry.pop("locked", None)


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
        children = entry.get("children")
        if isinstance(children, dict):
            made.extend(_verify_level(children, node, f"{where}/", problems))
    return made


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
    tag = args.get("tag")
    if tag is not None and not isinstance(tag, str):
        raise N.bad_arg("'tag' must be a string.")

    data = json.loads(json.dumps(data))  # private copy: validation normalises in place
    existing = (
        {item.name() for item in parent.allItems()}
        if hasattr(parent, "allItems")
        else {c.name() for c in parent.children()}
    )
    collisions = [name for name in data if name in existing]
    problems = _Problems()
    renamed: dict[str, str] = {}
    if collisions and on_collision == "error":
        suggestions = []
        taken = set(data)
        for name in collisions:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            suggestions.append(free)
        problems.add(
            ToolError(
                "name_collision",
                f"{len(collisions)} name(s) already exist in {parent.path()}: "
                + ", ".join(collisions[:10]),
                hint="Pass on_name_collision: 'rename' to build under free names, 'replace' to "
                "swap the existing nodes out (downstream wires move to the new ones), or "
                "rename the entries in data.",
                candidates=suggestions,
            ),
            parent.path(),
        )
    elif collisions and on_collision == "rename":
        taken = set(data) | existing
        for name in collisions:
            free = N.unique_name(parent, name, taken)
            taken.add(free)
            renamed[name] = free
        data = _rename_refs(data, renamed)
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
        return out

    rollback = N.Rollback()
    rollback.keep_display(parent)
    originals: dict[str, Any] = {}
    for name in replaced:
        old = parent.item(name)
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
        "nodes": [N.mutation_block(n) for n in top_nodes],
    }
    if renamed:
        result["renamed"] = {
            f"{parent.path().rstrip('/')}/{k}": f"{parent.path().rstrip('/')}/{v}"
            for k, v in renamed.items()
        }
    if replaced:
        result["replaced"] = [f"{parent.path().rstrip('/')}/{n}" for n in replaced]
    if warnings:
        result["warnings"] = warnings
    return result
