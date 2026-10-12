"""Digital asset tool: ``hda``. See docs/BIBLE.md §4.7 and review 04 §A4 "HDAs".

Thin wrappers over HOM (verified on 22.0.466):

* ``create``  — ``OpNode.createDigitalAsset(name, hda_file_name, description, min/max
  inputs, version=...)``. The node becomes an *unlocked* instance of the new type.
* ``save``    — ``definition.updateFromNode(node)`` (updates and writes the library).
* ``unlock``  — ``allowEditingOfContents()``.
* ``match``   — ``matchCurrentDefinition()`` (reverts edits and locks).
* ``install`` / ``reload`` — ``hou.hda.installFile`` / ``reloadFile``.
* ``list``    — ``hou.hda.loadedFiles()``; with ``library_path``, that file's definitions.

The catalogue schema cannot express per-action required fields, so they are validated
here with ``invalid_argument`` hints. Library paths respect ``approved_roots``.
"""

from __future__ import annotations

import os
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..undo import hou_undo_group, make_label
from .hip import check_allowed, resolve_path
from .nodes import (
    bad_arg,
    ensure_editable,
    get_node,
    hda_block,
    hou_exception_text,
    hou_message,
    page,
)
from .registry import HostContext, tool

ACTIONS = ("create", "save", "unlock", "match", "install", "reload", "list")
REQUIRED: dict[str, tuple[str, ...]] = {
    "create": ("path", "name", "library_path"),
    "save": ("path",),
    "unlock": ("path",),
    "match": ("path",),
    "install": ("library_path",),
    "reload": ("library_path",),
    "list": (),
}
EXAMPLES = {
    "create": '{action: "create", path: "/obj/geo1/subnet1", name: "studio::rock::1.0", '
    'library_path: "$HIP/hda/rock.hda"}',
    "save": '{action: "save", path: "/obj/geo1/rock1"}',
    "unlock": '{action: "unlock", path: "/obj/geo1/rock1"}',
    "match": '{action: "match", path: "/obj/geo1/rock1"}',
    "install": '{action: "install", library_path: "$HIP/hda/rock.hda"}',
    "reload": '{action: "reload", library_path: "$HIP/hda/rock.hda"}',
    "list": '{action: "list"} or {action: "list", library_path: "..."}',
}
HDA_EXTENSIONS = (".hda", ".otl", ".hdanc", ".hdalc", ".otlnc", ".otllc")
LIST_TYPES_LIMIT = 20


def _require(args: dict[str, Any], action: str) -> None:
    for key in REQUIRED[action]:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise bad_arg(
                f"hda action {action!r} needs '{key}'.",
                hint=f"Required for {action}: {', '.join(REQUIRED[action])}. "
                f"Example: {EXAMPLES[action]}",
            )
    for key in ("min_inputs", "max_inputs"):
        value = args.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise bad_arg(f"'{key}' must be an integer >= 0.")
    for key in ("label", "description", "version"):
        if key in args and not isinstance(args[key], str):
            raise bad_arg(f"'{key}' must be a string.")


def _label(args: dict[str, Any]) -> str | None:
    """The asset label: ``label`` or Houdini's own name for it, ``description``."""
    label = (args.get("label") or "").strip()
    description = (args.get("description") or "").strip()
    if label and description and label != description:
        raise bad_arg(
            f"label {label!r} and description {description!r} disagree.",
            hint="They are the same field (Houdini calls the label 'description'); pass one.",
        )
    return label or description or None


def _norm_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _library(args: dict[str, Any], ctx: HostContext) -> str:
    path = resolve_path(args["library_path"], field="library_path")
    if not path.lower().endswith(HDA_EXTENSIONS):
        raise bad_arg(
            f"library_path {path!r} is not an asset library.",
            hint="Use a .hda file (or .otl/.hdanc/.hdalc).",
        )
    check_allowed(path, ctx)
    return path


def _require_library_file(path: str) -> None:
    if not os.path.isfile(path):
        parent = os.path.dirname(path)
        names = (
            sorted(n for n in os.listdir(parent) if n.lower().endswith(HDA_EXTENSIONS))
            if os.path.isdir(parent)
            else []
        )
        raise ToolError(
            "file_not_found",
            f"No asset library at {path}.",
            hint="Check the path; hda list shows the libraries Houdini has loaded.",
            candidates=[f"{parent}/{n}" for n in names[:5]],
        )


def _hou_failure(exc: BaseException, what: str) -> ToolError:
    return ToolError(
        "internal",
        f"{what} failed: {hou_message(exc)}",
        hint="Houdini rejected the operation; the message is Houdini's own.",
        hou_exception=hou_exception_text(exc),
    )


def _asset_node(args: dict[str, Any]) -> tuple[Any, Any]:
    node = get_node(args["path"])
    definition = node.type().definition()
    if definition is None:
        raise bad_arg(
            f"{node.path()} ({node.type().name()}) is not a digital asset instance.",
            hint="Turn a subnet into an asset with hda action 'create' first.",
        )
    return node, definition


def _instance_result(node: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"path": node.path(), "type": node.type().name()}
    out.update(hda_block(node) or {})
    return out


def _definition_row(definition: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": definition.nodeTypeName(),
        "category": definition.nodeTypeCategory().name(),
        "label": definition.description(),
    }
    version = definition.version()
    if version:
        row["version"] = version
    return row


def _definitions(path: str) -> list[Any]:
    import hou

    try:
        return list(hou.hda.definitionsInFile(path))
    except hou.Error:
        return []


def _is_builtin(path: str) -> bool:
    hfs = os.environ.get("HFS")
    if not hfs:
        return False
    try:
        return os.path.commonpath(
            [_norm_key(os.path.realpath(path)), _norm_key(os.path.realpath(hfs))]
        ) == _norm_key(os.path.realpath(hfs))
    except ValueError:
        return False


# -- actions ------------------------------------------------------------------------


def _create(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    node = get_node(args["path"])
    ensure_editable(node, "turn into an asset")
    name = args["name"].strip()
    library = _library(args, ctx)
    if not node.canCreateDigitalAsset():
        raise bad_arg(
            f"{node.path()} ({node.type().name()}) cannot become a digital asset.",
            hint="Create assets from a subnet: put the nodes in a subnet and pass its path.",
        )
    category = node.type().category()
    version = (args.get("version") or "").strip() or None
    existing = hou.nodeType(category, name)
    if existing is None and version and name.count("::") < 2:
        existing = hou.nodeType(category, f"{name}::{version}")
    if existing is not None:
        library_of = existing.definition().libraryFilePath() if existing.definition() else None
        raise ToolError(
            "name_collision",
            f"A {category.name()} node type named {existing.name()!r} already exists"
            + (f" (from {library_of})." if library_of else "."),
            hint="Pick another name or a new version (e.g. studio::rock::2.0); to update the "
            "existing asset from an instance use hda action 'save'.",
        )
    label = _label(args)
    min_inputs = args.get("min_inputs")
    min_inputs = 0 if min_inputs is None else int(min_inputs)
    max_inputs = args.get("max_inputs")
    if max_inputs is None:
        max_inputs = max(len(node.inputs()), int(node.type().maxNumInputs()), min_inputs)
    max_inputs = int(max_inputs)
    if min_inputs > max_inputs:
        raise bad_arg(
            f"min_inputs ({min_inputs}) is greater than max_inputs ({max_inputs}).",
            hint="Pass min_inputs <= max_inputs.",
        )
    os.makedirs(os.path.dirname(library) or ".", exist_ok=True)
    kwargs: dict[str, Any] = {
        "name": name,
        "hda_file_name": library,
        "description": label,
        "min_num_inputs": min_inputs,
        "max_num_inputs": max_inputs,
    }
    if version:
        kwargs["version"] = version
    try:
        asset = node.createDigitalAsset(**kwargs)
    except hou.Error as exc:
        raise _hou_failure(exc, f"createDigitalAsset on {node.path()}") from exc
    definition = asset.type().definition()
    out = _instance_result(asset)
    out.update(_definition_row(definition))
    out["type"] = asset.type().name()
    out["inputs"] = {"min": min_inputs, "max": max_inputs}
    out["note"] = (
        "The node is now an unlocked instance; edit its contents, then hda save. "
        "hda match locks it to the saved definition."
    )
    return out


def _save(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    node, definition = _asset_node(args)
    library = definition.libraryFilePath()
    if library and library != "Embedded" and os.path.isabs(library):
        check_allowed(resolve_path(library, field="library_path"), ctx)
    label = _label(args) or ""
    try:
        if label:
            definition.setDescription(label)
        definition.updateFromNode(node)
    except hou.Error as exc:
        raise _hou_failure(exc, f"Saving {node.type().name()} from {node.path()}") from exc
    out = _instance_result(node)
    out["saved"] = True
    return out


def _unlock(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    node, _definition = _asset_node(args)
    ensure_editable(node, "unlock")
    try:
        node.allowEditingOfContents()
    except hou.Error as exc:
        raise _hou_failure(exc, f"Unlocking {node.path()}") from exc
    return _instance_result(node)


def _match(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    node, _definition = _asset_node(args)
    ensure_editable(node, "match")
    try:
        node.matchCurrentDefinition()
    except hou.Error as exc:
        raise _hou_failure(exc, f"Matching {node.path()} to its definition") from exc
    return _instance_result(node)


def _install(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    library = _library(args, ctx)
    _require_library_file(library)
    action = args["action"]
    loaded = {_norm_key(p) for p in hou.hda.loadedFiles()}
    try:
        if action == "reload" and _norm_key(library) in loaded:
            hou.hda.reloadFile(library)
            done = "reloaded"
        else:
            hou.hda.installFile(library)
            done = "installed"
    except hou.Error as exc:
        raise _hou_failure(exc, f"{action} {library}") from exc
    out: dict[str, Any] = {
        "library": library,
        "action": done,
        "definitions": [_definition_row(d) for d in _definitions(library)],
    }
    if action == "reload" and done == "installed":
        out["note"] = "The library was not loaded, so it was installed instead."
    return out


def _list(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    if isinstance(args.get("library_path"), str) and args["library_path"].strip():
        library = resolve_path(args["library_path"], field="library_path")
        _require_library_file(library)
        rows = [_definition_row(d) for d in _definitions(library)]
        chunk, nxt = page(rows, args.get("limit"), args.get("cursor"))
        out: dict[str, Any] = {"library": library, "total": len(rows), "definitions": chunk}
        if nxt is not None:
            out["next_cursor"] = nxt
        return out
    libraries: list[dict[str, Any]] = []
    for path in hou.hda.loadedFiles():
        builtin = _is_builtin(path)
        definitions = _definitions(path)
        row: dict[str, Any] = {"path": path, "definition_count": len(definitions)}
        if builtin:
            row["builtin"] = True
        else:
            row["types"] = [d.nodeTypeName() for d in definitions[:LIST_TYPES_LIMIT]]
            if len(definitions) > LIST_TYPES_LIMIT:
                row["types_truncated"] = True
        libraries.append(row)
    # User libraries first; Houdini's own ($HFS) libraries after, without type names.
    libraries.sort(key=lambda r: bool(r.get("builtin")))
    chunk, nxt = page(libraries, args.get("limit"), args.get("cursor"))
    out = {
        "libraries": chunk,
        "total": len(libraries),
        "hint": "Pass library_path to list one library's definitions.",
    }
    if nxt is not None:
        out["next_cursor"] = nxt
    return out


HANDLERS = {
    "create": _create,
    "save": _save,
    "unlock": _unlock,
    "match": _match,
    "install": _install,
    "reload": _install,
    "list": _list,
}


@tool("hda", scene=False)
def hda(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Registered with ``scene=False`` because only some actions mutate: ``list`` must not
    open an undo group, dirty the scene or be refused in read-only mode. Mutating actions
    get the dispatcher's treatment here: read-only refusal, one labelled undo group (rolled
    back on failure), a history record and the dirty flag.
    """
    action = args.get("action")
    if action not in ACTIONS:
        raise bad_arg(
            f"action must be one of {', '.join(ACTIONS)}; got {action!r}.",
            candidates=list(ACTIONS),
        )
    _require(args, action)
    handler = HANDLERS[action]
    if action == "list":
        return handler(args, ctx)
    if ctx.config.read_only:
        raise ToolError(
            "read_only",
            f"hda {action} changes the scene, and the host is in read-only mode.",
            hint="Set read_only = false in hocuspocus.toml (or HOCUSPOCUS_READ_ONLY=0) and "
            "restart the host.",
        )
    label = make_label(
        "hda", {"undo_label": f"{action} {args.get('path') or args.get('library_path')}"}
    )
    with hou_undo_group(label):
        result = handler(args, ctx)
    ctx.undo.record(label, "hda")
    ctx.scene.mark_dirty()
    result["undo_label"] = label
    return result
