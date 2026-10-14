"""Catalogue entry for ``hda`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _cursor, _enum, _i, _limit, _obj, _s

SPEC = ToolSpec(
    name="hda",
    profiles=("full", "compat_1x"),
    description=(
        "Digital assets: create turns subnet path into an HDA; save updates the definition from"
        " path, spare parms included; unlock allows editing; match reverts to the definition "
        "and locks; install and reload take library_path; list shows loaded libraries or "
        "library_path's definitions."
    ),
    notes=(
        "create takes name, label (or description), version, library_path and optional "
        "min_inputs/max_inputs. save copies the instance's spare parms into the asset's "
        "interface (promoted lists them; promote_spare_parms: false keeps them on the "
        "instance). list is paged by limit and cursor; install of a loaded library says "
        "already_loaded. node_type_info and node_type_search report the definition's version "
        "and, without help, its label as description."
    ),
    input_schema=_obj(
        {
            "action": _enum(("create", "save", "unlock", "match", "install", "reload", "list")),
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
            "limit": _limit(),
            "cursor": _cursor(),
        },
        ("action",),
    ),
    # Registered scene=False: list must not open an undo group or dirty the scene; the
    # mutating actions open their own group (§4.1).
    examples=(
        {
            "action": "create",
            "path": "/obj/geo1/subnet1",
            "name": "studio::rock",
            "library_path": "C:/hda/rock.hda",
        },
        {"action": "list"},
    ),
)
