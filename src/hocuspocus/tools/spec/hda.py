"""Catalogue entry for ``hda`` (BIBLE §4.7, D47)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _cursor, _enum, _i, _limit, _obj, _s

ACTIONS = (
    "create", "save", "unlock", "match", "install", "uninstall", "reload", "list", "info",
    "version",
)  # fmt: skip

SPEC = ToolSpec(
    name="hda",
    # 2.1 (D47): in core, so an agent building a tool another artist uses never needs
    # houdini_python for the asset's lifecycle (review 26 P1 friction 1).
    profiles=("core", "full"),
    description=(
        "Digital assets: create turns subnet path into an HDA; save writes path's contents "
        "and spare parms to its definition; unlock allows editing; match reverts and locks; "
        "install, uninstall and reload take library_path; list shows loaded libraries; info "
        "describes one definition; version copies it as a new version. interface edits parms "
        "as spare_parms does."
    ),
    notes=(
        "create takes name, label (or description), version, library_path and optional "
        "min_inputs/max_inputs, and promotes the subnet's spare parms (2.1), so the "
        "definition has the interface at once. save copies the instance's spare parms into "
        "the asset's interface (promoted lists them; promote_spare_parms: false keeps them on "
        "the instance) and also takes label, version and min_inputs/max_inputs; lock: true "
        "locks the instance to the saved definition (matchCurrentDefinition) after saving. "
        "interface (create, save) is the asset's parm interface in the edit node op's "
        "spare_parms shape {add, change, remove}: on create it is added to the subnet first; "
        "on save it changes any parm of the definition, and the result lists interface "
        "{add, change, remove}. help (create, save) is the HelpText section (Houdini wiki "
        "markup; an empty string removes it). action uninstall takes library_path (a loaded "
        "library): instances stay and fall back to another loaded definition or the copy "
        "embedded in the hip, named per path in instances. info takes path (an instance) or "
        "name (Category/type, e.g. Sop/studio::rock::1.0) and returns type, label, version, "
        "library, is_current: false and current_library when another definition wins, "
        "other_libraries, inputs, sections (names), help_chars, interface {parms, folders, "
        "conditionals?} (2.1: conditionals {parm: {disable_when?, hide_when?}} for at most "
        "100 parms, conditionals_total past that), instances (a count) and, for path, instance {hda_locked, matches_definition}. list "
        "is paged by limit and cursor; install of a loaded library says already_loaded. list "
        "and info only read. A library the asset is written to (create, save) must carry the "
        "licence's extension: .hda or .otl on Commercial, .hdalc or .otllc on Indie, .hdanc "
        "or .otlnc on Apprentice and Education; another is invalid_argument with the "
        "corrected path as candidate. inspect {what: type} and search {kind: types} report "
        "the definition's version and, without help, its label as description; inspect "
        "{what: type, include_help: true} reads the HelpText section (2.1), help_source "
        "<library>:HelpText. "
        "save with name (Category/type) instead of path (2.1) sets that definition's label, "
        "version, min_inputs/max_inputs, help and interface without an instance and without "
        "touching its contents (lock and promote_spare_parms need path); the result names "
        "what changed. version (2.1) takes path (an instance) or name and version, the new "
        "version component of the type name (hp::tower::1.0 with version 1.1 is "
        "hp::tower::1.1; a name without one gains it): the definition, contents, interface "
        "and sections, is copied to the new type name in its own library or library_path "
        "(installed when not loaded), with label (default the old one) and the definition's "
        "version field set; an existing type of that name is name_collision. The old "
        "version stays, and creating the bare name (hp::tower) makes the newest. switch: "
        "path moves the instance at path to the new version, all every instance of the old "
        "type (none, the default, moves none); parm values are kept, a locked instance "
        "takes the new definition's contents and an unlocked one keeps its edited contents "
        "for an hda save. The result lists switched paths."
    ),
    input_schema=_obj(
        {
            "action": _enum(ACTIONS),
            "path": _s("Node path."),
            "library_path": _s(".hda file."),
            "name": _s("Type name."),
            "label": _s(),
            # Houdini's own name for the label (createDigitalAsset description=).
            "description": _s("Same as label."),
            "version": _s(),
            "min_inputs": _i(None, minimum=0, maximum=9999),
            "max_inputs": _i(None, minimum=0, maximum=9999),
            "promote_spare_parms": _b(True),
            "interface": {"type": "object"},
            "help": _s(),
            "lock": {"type": "boolean"},
            "switch": _enum(("none", "path", "all")),
            "limit": _limit(),
            "cursor": _cursor(),
        },
        ("action",),
    ),
    # Registered scene=False: list and info must not open an undo group or dirty the
    # scene; the mutating actions open their own group (§4.1).
    examples=(
        {
            "action": "create",
            "path": "/obj/geo1/subnet1",
            "name": "studio::rock::1.0",
            "library_path": "$HIP/hda/rock.hdalc",
            "interface": {"add": [{"name": "seed", "type": "int", "default": 1}]},
        },
        {
            "action": "save",
            "path": "/obj/geo1/rock",
            "interface": {"change": [{"name": "seed", "default": 7}]},
            "help": "= Rock =\nA procedural rock.",
            "lock": True,
        },
        {"action": "version", "path": "/obj/geo1/rock", "version": "1.1", "switch": "path"},
    ),
)
