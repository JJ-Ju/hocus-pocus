"""The tool specs: one module per tool, each exporting ``SPEC: ToolSpec`` (spec-2.0 §5.1).

Stdlib only. :data:`ORDER` is the catalogue order, which is the order of every profile's
``tools/list``, ``docs/tools.md`` and ``hocuspocus://tools``: the 2.0 profiles list their
tools in spec-2.0 §2's order and ``compat_1x`` the 1.4 tools in 1.4's. It is an explicit
list, never directory order, so the surface is the same on every filesystem; a unit test
checks that it names every module here and nothing else, and that each module is named
after its tool.
"""

from __future__ import annotations

from importlib import import_module

from ._helpers import ToolSpec

ORDER: tuple[str, ...] = (
    # Session and instances (bridge-local)
    "houdini_status", "houdini_connect",
    # Hip file
    "hip_new", "hip_open", "hip_save", "hip_merge",
    # Reads and mutations (spec-2.0 §2.3, §2.4), then the 1.4 node tools they replace
    "inspect", "search", "edit",
    "node_find", "node_info", "node_create", "node_delete", "node_edit", "node_copy",
    "node_connect", "node_layout", "network_describe", "network_build",
    # Parms
    "parm_get", "parm_set",
    # Cook, problems, geometry
    "cook", "problems", "geo_info", "geo_read",
    # Visual feedback, code, types, state
    "viewport_capture", "render", "look", "houdini_python", "node_type_search",
    "node_type_info", "undo", "time", "selection", "job",
    # Contexts (full)
    "hda", "usd_stage", "pdg", "events",
)  # fmt: skip
"""Spec module names (each equal to its tool's name), in catalogue order."""


def _load() -> tuple[ToolSpec, ...]:
    return tuple(import_module(f"{__name__}.{name}").SPEC for name in ORDER)


TOOLS: tuple[ToolSpec, ...] = _load()
"""Every tool's spec, in :data:`ORDER`."""
