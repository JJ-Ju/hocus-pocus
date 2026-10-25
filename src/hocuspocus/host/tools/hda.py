"""Digital asset tool: ``hda``. See docs/BIBLE.md §4.7, D47 and review 04 §A4 "HDAs".

Thin wrappers over HOM (verified on 22.0.466):

* ``create``  — ``OpNode.createDigitalAsset(name, hda_file_name, description, min/max
  inputs, version=...)``. The node becomes an *unlocked* instance of the new type. Its
  spare parms (and ``interface``, added first) are promoted to the definition's parm
  template group, because ``createDigitalAsset`` leaves them on the instance.
* ``save``    — ``definition.updateFromNode(node)`` (updates and writes the library), the
  instance's spare parms and ``interface`` into the definition's group, ``help`` as the
  ``HelpText`` section, then ``lock`` runs ``matchCurrentDefinition()``.
* ``unlock``  — ``allowEditingOfContents()``.
* ``match``   — ``matchCurrentDefinition()`` (reverts edits and locks).
* ``install`` / ``uninstall`` / ``reload`` — ``hou.hda.installFile`` / ``uninstallFile`` /
  ``reloadFile``.
* ``list``    — ``hou.hda.loadedFiles()``; with ``library_path``, that file's definitions.
* ``info``    — one definition: library, version, sections, current or not, inputs, the
  interface's size, instances; for an instance (``path``) also its lock state.
* ``version`` — ``definition.copyToHDAFile(library, new_name=..., new_menu_name=...)``
  under the type name with the new version component (``hp::tower::1.0`` to
  ``hp::tower::1.1``), installed when its library was not loaded, then ``setVersion``;
  ``switch`` moves instances with ``changeNodeType`` (2.1, D73).
* ``save`` with ``name`` instead of ``path`` sets a definition's label, version, input
  counts, help and interface without an instance and without touching its contents.

The catalogue schema cannot express per-action required fields, so they are validated
here with ``invalid_argument`` hints. Library paths respect ``approved_roots``, and a
library the asset is written to must carry the licence's extension (an Indie session
writes ``.hdalc``, an Apprentice or Education one ``.hdanc``; review 26 P1 friction 1).
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

from hocuspocus.tools.errors import ToolError

from ..undo import hou_undo_group, make_label
from . import events
from ._common import (
    bad_arg,
    get_node,
    hou_exception_text,
    hou_message,
    page,
    refuse_if_read_only,
    response_budget,
)
from .hip import check_allowed, resolve_path
from .nodes import ensure_editable, hda_block, watch_nodes
from .parms import template_conditionals
from .registry import HostContext, tool

ACTIONS = (
    "create", "save", "unlock", "match", "install", "uninstall", "reload", "list", "info",
    "version",
)  # fmt: skip
READS = frozenset(("list", "info"))
REQUIRED: dict[str, tuple[str, ...]] = {
    "create": ("path", "name", "library_path"),
    "save": (),
    "unlock": ("path",),
    "match": ("path",),
    "install": ("library_path",),
    "uninstall": ("library_path",),
    "reload": ("library_path",),
    "list": (),
    "info": (),
    "version": ("version",),
}
BY_PATH_OR_NAME = frozenset(("info", "save", "version"))
"""Actions on one definition, named by an instance (``path``) or a type (``name``)."""
SWITCH = ("none", "path", "all")
"""``version``'s ``switch``: no instance, the instance ``path`` names, or every instance
of the old type."""
EXAMPLES = {
    "create": '{action: "create", path: "/obj/geo1/subnet1", name: "studio::rock::1.0", '
    'library_path: "$HIP/hda/rock.hda"}',
    "save": '{action: "save", path: "/obj/geo1/rock1", lock: true} or {action: "save", name: '
    '"Sop/studio::rock::1.0", label: "Rock"}',
    "unlock": '{action: "unlock", path: "/obj/geo1/rock1"}',
    "match": '{action: "match", path: "/obj/geo1/rock1"}',
    "install": '{action: "install", library_path: "$HIP/hda/rock.hda"}',
    "uninstall": '{action: "uninstall", library_path: "$HIP/hda/rock.hda"}',
    "reload": '{action: "reload", library_path: "$HIP/hda/rock.hda"}',
    "list": '{action: "list"} or {action: "list", library_path: "..."}',
    "info": '{action: "info", path: "/obj/geo1/rock1"} or {action: "info", name: '
    '"Sop/studio::rock::1.0"}',
    "version": '{action: "version", path: "/obj/geo1/rock1", version: "1.1", switch: "path"}',
}
HDA_EXTENSIONS = (".hda", ".otl", ".hdanc", ".hdalc", ".otlnc", ".otllc")
LICENCE_EXTENSIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "Commercial": ((".hda", ".otl"), "commercial"),
    "Indie": ((".hdalc", ".otllc"), "limited-commercial (Indie)"),
    "Apprentice": ((".hdanc", ".otlnc"), "non-commercial"),
    "ApprenticeHD": ((".hdanc", ".otlnc"), "non-commercial"),
    "Education": ((".hdanc", ".otlnc"), "non-commercial"),
}
"""Licence category -> the library extensions an asset written in such a session may
have, and what that asset is. Houdini writes any extension it is given (22.0.466), so a
``.hda`` written by an Indie session is a limited-commercial asset under a commercial
name; ``hou.hda.defaultFileExtension()`` is the one Houdini picks."""
HELP_SECTION = "HelpText"
LIST_TYPES_LIMIT = 20
SECTIONS_LIMIT = 40
CONDITIONALS_LIMIT = 100
"""``info`` lists at most this many parms' conditionals (``conditionals_total`` counts all)."""


def _require(args: dict[str, Any], action: str) -> None:
    for key in REQUIRED[action]:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise bad_arg(
                f"hda action {action!r} needs '{key}'.",
                hint=f"Required for {action}: {', '.join(REQUIRED[action])}. "
                f"Example: {EXAMPLES[action]}",
            )
    if action in BY_PATH_OR_NAME and not any(
        isinstance(args.get(k), str) and args[k].strip() for k in ("path", "name")
    ):
        raise bad_arg(
            f"hda action {action!r} needs 'path' (an instance) or 'name' (a type).",
            hint=f"Example: {EXAMPLES[action]}",
        )
    by_name = action in BY_PATH_OR_NAME and not _has(args, "path")
    if action == "save" and by_name:
        for key in ("lock", "promote_spare_parms"):
            if args.get(key) is not None:
                raise bad_arg(
                    f"{key} needs an instance: hda save with name sets the definition only.",
                    hint=f"Pass path (an instance) to save its contents. {EXAMPLES['save']}",
                )
    switch = args.get("switch")
    if switch is not None and action != "version":
        raise bad_arg(f"switch is for hda version; {action} takes none.")
    if action == "version":
        if switch is not None and switch not in SWITCH:
            raise bad_arg(f"switch must be one of {', '.join(SWITCH)}; got {switch!r}.")
        if switch == "path" and by_name:
            raise bad_arg(
                "switch: path needs path, the instance to switch.",
                hint='Pass path, or switch: "all" for every instance of the old type.',
            )
    for key in ("min_inputs", "max_inputs"):
        value = args.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise bad_arg(f"'{key}' must be an integer >= 0.")
    for key in ("label", "description", "version", "help"):
        if key in args and not isinstance(args[key], str):
            raise bad_arg(f"'{key}' must be a string.")
    for key in ("lock", "promote_spare_parms"):
        if key in args and not isinstance(args[key], bool):
            raise bad_arg(f"'{key}' must be a boolean.")
    if args.get("lock") is not None and action != "save":
        raise bad_arg(
            f"lock is for hda save; {action} takes none.",
            hint="hda match locks an instance to its definition; hda unlock opens it.",
        )
    if args.get("interface") is not None and action not in ("create", "save"):
        raise bad_arg(f"interface is for hda create and save; {action} takes none.")
    if args.get("help") is not None and action not in ("create", "save"):
        raise bad_arg(f"help is for hda create and save; {action} takes none.")


def _has(args: dict[str, Any], key: str) -> bool:
    value = args.get(key)
    return isinstance(value, str) and bool(value.strip())


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


def long_path(path: str) -> str:
    """``path`` with Windows 8.3 short names expanded (``C:/PROGRA~1/...`` is how
    ``hou.hda.loadedFiles()`` reports $HFS libraries), forward slashes."""
    if "~" not in path or not os.path.exists(path):
        return path
    try:
        return os.path.realpath(path).replace("\\", "/")
    except OSError:
        return path


def licence_category() -> str | None:
    import hou

    try:
        return str(hou.licenseCategory()).rsplit(".", 1)[-1]
    except Exception:
        return None


def check_licence_extension(path: str) -> None:
    """Refuse to write an asset to a library whose extension another licence uses."""
    import hou

    category = licence_category()
    allowed, kind = LICENCE_EXTENSIONS.get(category or "", ((), ""))
    if not allowed or os.path.splitext(path)[1].lower() in allowed:
        return
    default = ""
    with contextlib.suppress(Exception):
        default = hou.hda.defaultFileExtension() or ""
    if default.lower() not in allowed:
        default = allowed[0]
    fixed = os.path.splitext(path)[0] + default
    raise ToolError(
        "invalid_argument",
        f"This Houdini runs on a{'n' if category[0] in 'AEI' else ''} {category} licence, so "
        f"the asset it writes is {kind}: its library must end in {' or '.join(allowed)}, "
        f"not {os.path.splitext(path)[1] or 'no extension'} ({path}).",
        hint=f"Use library_path {fixed!r}.",
        candidates=[fixed],
        detail={"licence": category, "extensions": list(allowed)},
    )


def _library(args: dict[str, Any], ctx: HostContext) -> str:
    path = resolve_path(args["library_path"], field="library_path")
    if not path.lower().endswith(HDA_EXTENSIONS):
        default = ".hda"
        with contextlib.suppress(Exception):
            import hou

            default = hou.hda.defaultFileExtension() or default
        raise bad_arg(
            f"library_path {path!r} is not an asset library.",
            hint=f"Use a {default} file (asset libraries end in {', '.join(HDA_EXTENSIONS)}).",
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


def _is_loaded(path: str) -> bool:
    import hou

    return _norm_key(path) in {_norm_key(long_path(p)) for p in hou.hda.loadedFiles()}


def _interface_plan(node: Any, spec: Any, *, spare_only: bool) -> dict[str, Any] | None:
    """Validate ``interface`` against ``node`` before anything changes: as spare parms
    of the subnet (create), or as the asset's whole interface (save)."""
    if spec is None:
        return None
    from . import spare

    if spare_only:
        iface = spare.node_interface(node, field="interface")
    else:
        names: set[str] = set()
        with contextlib.suppress(Exception):
            names = {p.name() for p in node.parms()} | {t.name() for t in node.parmTuples()}
        iface = spare.Interface.of_group(
            node.parmTemplateGroup(), owner=node.path(), field="interface", parm_names=names
        )
    return spare.plan(spec, iface)


def _interface_rows(node: Any, planned: dict[str, Any] | None) -> dict[str, Any]:
    if not planned:
        return {}
    rows = {
        key: [name for name, *_rest in planned[key]] if key != "remove" else list(planned[key])
        for key in ("add", "change", "remove")
    }
    return {"interface": {k: v for k, v in rows.items() if v}}


def _set_help(definition: Any, text: str | None) -> bool:
    if text is None:
        return False
    if text:
        definition.addSection(HELP_SECTION, text)
    elif definition.hasSection(HELP_SECTION):
        definition.removeSection(HELP_SECTION)
    return True


def _write_library(definition: Any) -> None:
    """Write the definition (its interface and sections) to its library file."""
    library = definition.libraryFilePath()
    if library and library != "Embedded":
        definition.save(library)


# -- actions ------------------------------------------------------------------------


def _create(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    from ..tx import Rollback
    from . import spare

    node = get_node(args["path"])
    ensure_editable(node, "turn into an asset")
    name = args["name"].strip()
    library = _library(args, ctx)
    check_licence_extension(library)
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
    planned = _interface_plan(node, args.get("interface"), spare_only=True)
    if planned is not None:
        spare.apply_spare_parms(node, planned, Rollback())  # the undo group rolls it back
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
    promoted = _promote(asset, definition, args.get("promote_spare_parms", True))
    helped = _set_help(definition, args.get("help"))
    if promoted or helped:
        _write_library(definition)
    out = _instance_result(asset)
    out.update(_definition_row(definition))
    out["type"] = asset.type().name()
    out["inputs"] = {"min": min_inputs, "max": max_inputs}
    if promoted:
        out["promoted"] = promoted
    out.update(_interface_rows(asset, planned))
    if helped:
        out["help"] = True
    out["note"] = (
        "The node is now an unlocked instance; edit its contents, then hda save (lock: true "
        "locks it to the saved definition)."
    )
    return out


def _promote(node: Any, definition: Any, promote: Any, group: Any = None) -> list[str]:
    """Make the instance's spare parms (and ``group``'s changes) the definition's
    interface; returns the spare parm names promoted (folders left out). The instance's
    template group is the definition's plus its spares, so making it the definition's
    keeps their values."""
    import hou

    folders = (hou.parmTemplateType.Folder, hou.parmTemplateType.FolderSet)
    spares = (
        sorted(
            {p.tuple().name() for p in node.spareParms() if p.parmTemplate().type() not in folders}
        )
        if promote
        else []
    )
    if spares or group is not None:
        definition.setParmTemplateGroup(group if group is not None else node.parmTemplateGroup())
    return spares


def _definition_library(definition: Any, ctx: HostContext) -> str | None:
    """The definition's library as a checked path (``approved_roots``, the licence's
    extension), or None for an embedded one."""
    library = definition.libraryFilePath()
    if library and library != "Embedded" and os.path.isabs(library):
        library = resolve_path(library, field="library_path")
        check_allowed(library, ctx)
        check_licence_extension(library)
        return library
    return None


def _inputs(args: dict[str, Any], definition: Any) -> tuple[int, int]:
    min_inputs, max_inputs = args.get("min_inputs"), args.get("max_inputs")
    low = definition.minNumInputs() if min_inputs is None else int(min_inputs)
    high = definition.maxNumInputs() if max_inputs is None else int(max_inputs)
    if low > high:
        raise bad_arg(
            f"min_inputs ({low}) is greater than max_inputs ({high}).",
            hint="Pass min_inputs <= max_inputs.",
        )
    return low, high


def _save_definition(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """``save`` with ``name`` (2.1, D73): the definition's label, version, input counts,
    help and interface, written to its library; no instance, its contents untouched."""
    import hou

    from . import spare

    node_type = _type_by_name(args["name"])
    definition = node_type.definition()
    _definition_library(definition, ctx)
    label = _label(args) or ""
    low, high = _inputs(args, definition)
    planned = None
    if args.get("interface") is not None:
        owner = f"{node_type.category().name()}/{node_type.name()}"
        iface = spare.Interface.of_group(
            definition.parmTemplateGroup(), owner=owner, field="interface"
        )
        planned = spare.plan(args["interface"], iface)
    changed: list[str] = []
    try:
        if label:
            definition.setDescription(label)
            changed.append("label")
        if args.get("version") is not None:
            definition.setVersion(args["version"].strip())
            changed.append("version")
        if args.get("min_inputs") is not None or args.get("max_inputs") is not None:
            definition.setMaxNumInputs(high)
            definition.setMinNumInputs(low)
            changed.append("inputs")
        if planned is not None:
            group = definition.parmTemplateGroup()
            spare.apply_to_group(group, planned)
            definition.setParmTemplateGroup(group)
        helped = _set_help(definition, args.get("help"))
        _write_library(definition)
    except hou.Error as exc:
        raise _hou_failure(exc, f"Saving the definition of {node_type.name()}") from exc
    out: dict[str, Any] = {
        "type": f"{node_type.category().name()}/{node_type.name()}",
        **{k: v for k, v in _definition_row(definition).items() if k in ("label", "version")},
        "library": long_path(definition.libraryFilePath()),
        "saved": True,
    }
    if changed:
        out["changed"] = changed
    if planned is not None:
        rows = {
            key: [name for name, *_rest in planned[key]] if key != "remove" else list(planned[key])
            for key in ("add", "change", "remove")
        }
        out["interface"] = {k: v for k, v in rows.items() if v}
    if helped:
        out["help"] = True
    return out


def versioned_name(node_type: Any, version: str) -> str:
    """The type name of ``node_type`` with ``version`` as its version component
    (``hp::tower::1.0`` to ``hp::tower::1.1``; ``hp::tower`` to ``hp::tower::1.1``)."""
    import hou

    scope, namespace, name, _old = node_type.nameComponents()
    try:
        return hou.hda.fullNodeTypeNameFromComponents(scope, namespace, name, version)
    except Exception:  # pragma: no cover - present in every 22.0 build
        return "::".join(p for p in (scope, namespace, name, version) if p)


def _version(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """``version`` (2.1, D73): copy a definition, its contents, interface and sections,
    to the type name with a new version component, in its library or ``library_path``;
    ``switch`` moves the instance at ``path`` (``"path"``) or every instance of the old
    type (``"all"``) to it with ``changeNodeType``, keeping parm values; an unlocked
    instance keeps its edited contents, unsaved, for an ``hda save``."""
    import hou

    node = None
    if _has(args, "path"):
        node, definition = _asset_node(args)
        node_type = node.type()
    else:
        node_type = _type_by_name(args["name"])
        definition = node_type.definition()
    category = node_type.category()
    version = args["version"].strip()
    if not version:
        raise bad_arg("'version' must be a version such as 1.1.")
    new_name = versioned_name(node_type, version)
    old_ref = f"{category.name()}/{node_type.name()}"
    if new_name == node_type.name():
        raise bad_arg(
            f"{old_ref} already has version {version}.",
            hint="Pass the new version, such as 1.1 or 2.0.",
        )
    existing = hou.nodeType(category, new_name)
    if existing is not None:
        where = existing.definition().libraryFilePath() if existing.definition() else None
        raise ToolError(
            "name_collision",
            f"A {category.name()} node type named {new_name!r} already exists"
            + (f" (from {long_path(where)})." if where else "."),
            hint="Pick another version, or hda save with path or name to change that one.",
        )
    if _has(args, "library_path"):
        library = _library(args, ctx)
        check_licence_extension(library)
    else:
        library = _definition_library(definition, ctx)
        if library is None:
            raise bad_arg(
                f"{old_ref} is embedded in the hip file; pass library_path for the new version.",
                hint=f"Example: {EXAMPLES['version']} plus library_path.",
            )
    label = _label(args) or definition.description()
    switch = args.get("switch") or "none"
    targets: list[Any] = []
    if switch == "path" and node is not None:
        targets = [node]
    elif switch == "all":
        targets = sorted(node_type.instances(), key=lambda n: n.path())
    for target in targets:
        ensure_editable(target, "switch to the new version")
    os.makedirs(os.path.dirname(library) or ".", exist_ok=True)
    installed = False
    try:
        definition.copyToHDAFile(library, new_name=new_name, new_menu_name=label)
        if not _is_loaded(library):
            hou.hda.installFile(library)
            installed = True
        new_type = hou.nodeType(category, new_name)
        if new_type is None:
            hou.hda.reloadFile(library)
            new_type = hou.nodeType(category, new_name)
        if new_type is None or new_type.definition() is None:
            raise ToolError(
                "internal",
                f"Copied {old_ref} to {library} as {new_name}, but Houdini did not load it.",
                hint=f"hda install {{library_path: {library!r}}}, then hda info.",
            )
        new_definition = new_type.definition()
        new_definition.setVersion(version)
        new_definition.save(library)
    except hou.Error as exc:
        raise _hou_failure(exc, f"Copying {old_ref} to {new_name}") from exc
    switched: list[str] = []
    kept_edits: list[str] = []
    try:
        for target in targets:
            unlocked = not target.isLockedHDA()
            moved = target.changeNodeType(
                new_name, keep_name=True, keep_parms=True, keep_network_contents=unlocked
            )
            switched.append(moved.path())
            if unlocked:
                kept_edits.append(moved.path())
    except hou.Error as exc:
        raise _hou_failure(exc, f"Switching instances to {new_name}") from exc
    out: dict[str, Any] = {
        "type": f"{category.name()}/{new_name}",
        "from": old_ref,
        "label": label,
        "version": version,
        "library": long_path(library),
    }
    if installed:
        out["installed"] = True
    if switched:
        out["switched"] = switched
        watch_nodes([n for n in (hou.node(p) for p in switched) if n is not None])
    notes = [
        f"{old_ref} stays in its library, and instances not switched keep it; creating "
        f"{versioned_name(node_type, '')} without a version now makes the newest one."
    ]
    if kept_edits:
        notes.append(
            f"{', '.join(kept_edits)} {'is' if len(kept_edits) == 1 else 'are'} unlocked and "
            "kept the edited contents, not saved to the new version yet: hda save writes them."
        )
    out["notes"] = notes
    if node is not None and switch == "path":
        out["path"] = switched[0] if switched else node.path()
    return out


def _save(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    from . import spare

    if not _has(args, "path"):
        return _save_definition(args, ctx)
    node, definition = _asset_node(args)
    library = definition.libraryFilePath()
    if library and library != "Embedded" and os.path.isabs(library):
        library = resolve_path(library, field="library_path")
        check_allowed(library, ctx)
        check_licence_extension(library)
    label = _label(args) or ""
    promote = args.get("promote_spare_parms", True)
    planned = _interface_plan(node, args.get("interface"), spare_only=False)
    min_inputs, max_inputs = args.get("min_inputs"), args.get("max_inputs")
    low = definition.minNumInputs() if min_inputs is None else int(min_inputs)
    high = definition.maxNumInputs() if max_inputs is None else int(max_inputs)
    if low > high:
        raise bad_arg(
            f"min_inputs ({low}) is greater than max_inputs ({high}).",
            hint="Pass min_inputs <= max_inputs.",
        )
    try:
        if label:
            definition.setDescription(label)
        if args.get("version") is not None:
            definition.setVersion(args["version"].strip())
        if min_inputs is not None or max_inputs is not None:
            definition.setMaxNumInputs(high)
            definition.setMinNumInputs(low)
        definition.updateFromNode(node)
        group = None
        if planned is not None:
            # updateFromNode saves the contents, not the instance's spare parms (review
            # 15 papercut 6); the instance's group is the definition's plus its spares.
            group = node.parmTemplateGroup()
            if not promote:
                for parm in node.spareParms():
                    with contextlib.suppress(Exception):
                        group.remove(parm.tuple().name())
            spare.apply_to_group(group, planned)
        promoted = _promote(node, definition, promote, group)
        helped = _set_help(definition, args.get("help"))
        if planned is not None or promoted or helped:
            _write_library(definition)
    except hou.Error as exc:
        raise _hou_failure(exc, f"Saving {node.type().name()} from {node.path()}") from exc
    if args.get("lock") and not node.isLockedHDA():
        try:
            node.matchCurrentDefinition()
        except hou.Error as exc:
            raise _hou_failure(exc, f"Locking {node.path()} to its definition") from exc
    out = _instance_result(node)
    out["saved"] = True
    if promoted:
        out["promoted"] = promoted
    out.update(_interface_rows(node, planned))
    if helped:
        out["help"] = True
    if not node.isLockedHDA():
        out["note"] = "Saved; the instance stays unlocked for editing. hda match locks it."
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
    was_loaded = _is_loaded(library)
    try:
        if action == "reload" and was_loaded:
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
    if action == "install" and was_loaded:
        out["already_loaded"] = True
    if action == "reload" and done == "installed":
        out["note"] = "The library was not loaded, so it was installed instead."
    return out


def _uninstall(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """``hou.hda.uninstallFile``. Instances of its types stay in the scene and fall back to
    another loaded definition, or to the copy Houdini embeds in the hip (verified on
    22.0.466); the result says which, by path, never through the uninstalled type."""
    import hou

    library = _library(args, ctx)
    if not _is_loaded(library):
        loaded = [long_path(p) for p in hou.hda.loadedFiles() if not _is_builtin(p)]
        raise ToolError(
            "file_not_found",
            f"{library} is not a loaded asset library.",
            hint="hda list shows the libraries Houdini has loaded.",
            candidates=sorted(loaded)[:5],
        )
    definitions = _definitions(library)
    rows = [_definition_row(d) for d in definitions]
    instances: list[str] = []
    for definition in definitions:
        with contextlib.suppress(Exception):
            instances += [n.path() for n in definition.nodeType().instances()]
    try:
        hou.hda.uninstallFile(library)
    except hou.Error as exc:
        raise _hou_failure(exc, f"uninstall {library}") from exc
    out: dict[str, Any] = {"library": library, "action": "uninstalled", "definitions": rows}
    if instances:
        fallback: dict[str, str] = {}
        for path in sorted(instances):
            node = hou.node(path)
            definition = None
            with contextlib.suppress(Exception):
                definition = node.type().definition() if node is not None else None
            fallback[path] = definition.libraryFilePath() if definition is not None else "none"
        out["instances"] = fallback
        out["note"] = (
            "Instances stay in the scene on the definition named per path (Embedded: the "
            "copy in the hip file); hda install puts the library back."
        )
    return out


def _list(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    if isinstance(args.get("library_path"), str) and args["library_path"].strip():
        library = _library(args, ctx)  # extension and approved_roots, like install
        _require_library_file(library)
        rows = [_definition_row(d) for d in _definitions(library)]
        chunk, nxt = page(rows, args.get("limit"), args.get("cursor"), budget=response_budget(ctx))
        out: dict[str, Any] = {"library": library, "total": len(rows), "definitions": chunk}
        if not _is_loaded(library):
            out["loaded"] = False
        if nxt is not None:
            out["next_cursor"] = nxt
        return out
    libraries: list[dict[str, Any]] = []
    for path in hou.hda.loadedFiles():
        builtin = _is_builtin(path)
        definitions = _definitions(path)
        row: dict[str, Any] = {"path": long_path(path), "definition_count": len(definitions)}
        if builtin:
            row["builtin"] = True
        else:
            row["types"] = [d.nodeTypeName() for d in definitions[:LIST_TYPES_LIMIT]]
            if len(definitions) > LIST_TYPES_LIMIT:
                row["types_truncated"] = True
        libraries.append(row)
    # User libraries first; Houdini's own ($HFS) libraries after, without type names.
    libraries.sort(key=lambda r: bool(r.get("builtin")))
    chunk, nxt = page(libraries, args.get("limit"), args.get("cursor"), budget=response_budget(ctx))
    out = {
        "libraries": chunk,
        "total": len(libraries),
        "hint": "Pass library_path to list one library's definitions, or info a type.",
    }
    if nxt is not None:
        out["next_cursor"] = nxt
    return out


def _type_by_name(raw: str) -> Any:
    """The node type ``Category/name`` (or a bare name that one category defines)."""
    import difflib

    import hou

    text = raw.strip()
    categories = hou.nodeTypeCategories()
    if "/" in text:
        cat_name, _, name = text.partition("/")
        category = categories.get(cat_name) or next(
            (c for n, c in categories.items() if n.lower() == cat_name.lower()), None
        )
        if category is None:
            raise bad_arg(
                f"No node type category {cat_name!r}.",
                candidates=difflib.get_close_matches(cat_name, sorted(categories), n=5),
            )
        found = [hou.nodeType(category, name)]
    else:
        found = [hou.nodeType(c, text) for c in categories.values()]
    found = [t for t in found if t is not None]
    assets = [t for t in found if t.definition() is not None]
    if len(assets) == 1:
        return assets[0]
    if len(assets) > 1:
        raise bad_arg(
            f"{text!r} names a digital asset in several categories.",
            hint="Pass name as Category/name.",
            candidates=[f"{t.category().name()}/{t.name()}" for t in assets],
        )
    if found:
        raise bad_arg(f"{text} is a built-in node type, not a digital asset.")
    raise ToolError(
        "node_type_not_found",
        f"No digital asset type {text!r} is loaded.",
        hint="hda list shows the loaded libraries; hda install loads one.",
    )


def _info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    path = args.get("path")
    node = None
    if isinstance(path, str) and path.strip():
        node, definition = _asset_node(args)
        node_type = node.type()
    else:
        node_type = _type_by_name(args["name"])
        definition = node_type.definition()
    out: dict[str, Any] = {
        "type": f"{node_type.category().name()}/{node_type.name()}",
        "label": definition.description(),
    }
    if definition.version():
        out["version"] = definition.version()
    library = definition.libraryFilePath()
    out["library"] = long_path(library) if library else library
    if not definition.isCurrent():
        out["is_current"] = False
        with contextlib.suppress(Exception):
            current = node_type.definition()
            if current is not None:
                out["current_library"] = long_path(current.libraryFilePath())
    others = []
    with contextlib.suppress(Exception):
        others = [
            long_path(d.libraryFilePath())
            for d in node_type.allInstalledDefinitions()
            if _norm_key(d.libraryFilePath()) != _norm_key(library or "")
        ]
    if others:
        out["other_libraries"] = others
    out["inputs"] = {"min": definition.minNumInputs(), "max": definition.maxNumInputs()}
    sections = sorted(definition.sections())
    out["sections"] = sections[:SECTIONS_LIMIT]
    if len(sections) > SECTIONS_LIMIT:
        out["sections_total"] = len(sections)
    if HELP_SECTION in sections:
        with contextlib.suppress(Exception):
            out["help_chars"] = len(definition.sections()[HELP_SECTION].contents())
    from .spare import walk

    with contextlib.suppress(Exception):
        group = definition.parmTemplateGroup()
        templates = list(walk(group.entries()))
        out["interface"] = {
            "parms": sum(1 for t in templates if t.type().name() != "Folder"),
            "folders": [t.label() for t in group.entries() if t.type().name() == "Folder"],
        }
        # D82: the parms' disable_when / hide_when, which no read showed (r21 friction 5).
        conditions = {t.name(): c for t in templates if (c := template_conditionals(t))}
        if conditions:
            names = list(conditions)[:CONDITIONALS_LIMIT]
            out["interface"]["conditionals"] = {n: conditions[n] for n in names}
            if len(conditions) > CONDITIONALS_LIMIT:
                out["interface"]["conditionals_total"] = len(conditions)
    with contextlib.suppress(Exception):
        out["instances"] = len(node_type.instances())
    if node is not None:
        block = hda_block(node) or {}
        out["instance"] = {
            "path": node.path(),
            "hda_locked": block.get("hda_locked"),
            "matches_definition": block.get("matches_definition"),
        }
    return out


HANDLERS = {
    "create": _create,
    "save": _save,
    "unlock": _unlock,
    "match": _match,
    "install": _install,
    "uninstall": _uninstall,
    "reload": _install,
    "list": _list,
    "info": _info,
    "version": _version,
}


@tool("hda", scene=False)
def hda(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Registered with ``scene=False`` because only some actions mutate: ``list`` and
    ``info`` must not open an undo group, dirty the scene or be refused in read-only mode.
    Mutating actions get the dispatcher's treatment here: read-only refusal, one labelled
    undo group (rolled back on failure), a history record and the dirty flag.
    """
    action = args.get("action")
    if action not in ACTIONS:
        raise bad_arg(
            f"action must be one of {', '.join(ACTIONS)}; got {action!r}.",
            candidates=list(ACTIONS),
        )
    _require(args, action)
    handler = HANDLERS[action]
    if action in READS:
        return handler(args, ctx)
    refuse_if_read_only(ctx, f"hda {action}")
    label = make_label(
        "hda",
        {
            "undo_label": f"{action} "
            f"{args.get('path') or args.get('name') or args.get('library_path')}"
        },
    )
    # create, match, unlock and a locking save rebuild the asset's contents: one events
    # entry for the asset, not one per internal node (review 15 papercut 2).
    rebuilds = action in ("create", "match", "unlock") or (action == "save" and args.get("lock"))
    rebuilt = get_node(args["path"]) if rebuilds else None
    with hou_undo_group(label):
        if rebuilt is None:
            result = handler(args, ctx)
        else:
            path = rebuilt.path()
            # createDigitalAsset builds the asset as a sibling, deletes the subnet and
            # renames the sibling, so for create the whole parent network is in scope.
            parent = rebuilt.parent()
            scope = parent.path() if action == "create" and parent is not None else path
            with events.collapsed(path, scope=scope):
                result = handler(args, ctx)
            watch_nodes([get_node(result.get("path") or path)])
    ctx.undo.record(label, "hda")
    ctx.scene.mark_dirty()
    result["undo_label"] = label
    return result
