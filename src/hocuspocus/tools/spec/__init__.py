"""The tool specs: one module per tool, each exporting ``SPEC: ToolSpec`` (spec-2.0 §5.1).

Stdlib only. :data:`ORDER` is the catalogue order (BIBLE §4.2–§4.7), which is the order of
``tools/list``, ``docs/tools.md`` and ``hocuspocus://tools``. It is an explicit list, never
directory order, so the surface is the same on every filesystem; a unit test checks that it
names every module here and nothing else, and that each module is named after its tool.
"""

from __future__ import annotations

from importlib import import_module

from ._helpers import ToolSpec

ORDER: tuple[str, ...] = (
    # §4.2 Session and instances (bridge-local)
    "houdini_status", "houdini_connect",
    # §4.3 Hip file
    "hip_new", "hip_open", "hip_save", "hip_merge",
    # §4.4 Nodes and networks
    "node_find", "node_info", "node_create", "node_delete", "node_edit", "node_copy",
    "node_connect", "node_layout", "network_describe", "network_build",
    # §4.5 Parms
    "parm_get", "parm_set",
    # §4.6 Cook, problems, geometry
    "cook", "problems", "geo_info", "geo_read",
    # §4.7 Visual feedback, code, types, state, contexts
    "viewport_capture", "render", "houdini_python", "node_type_search", "node_type_info",
    "undo", "time", "selection", "job",
    # full profile only
    "hda", "usd_stage", "pdg", "events",
    # 2.0 tools, v2 profile only (spec-2.0 §2.3; BIBLE §4.9)
    "inspect",
)  # fmt: skip
"""Spec module names (each equal to its tool's name), in catalogue order."""


def _load() -> tuple[ToolSpec, ...]:
    return tuple(import_module(f"{__name__}.{name}").SPEC for name in ORDER)


TOOLS: tuple[ToolSpec, ...] = _load()
"""Every tool's spec, in :data:`ORDER`."""
