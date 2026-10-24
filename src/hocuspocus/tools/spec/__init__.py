"""The tool specs: one module per tool, each exporting ``SPEC: ToolSpec`` (spec-2.0 §5.1).

Stdlib only. :data:`ORDER` is the catalogue order, which is the order of every profile's
``tools/list``, ``docs/tools.md`` and ``hocuspocus://tools`` (spec-2.0 §2's order). It is
an explicit list, never directory order, so the surface is the same on every filesystem; a
unit test checks that it names every module here and nothing else, and that each module is
named after its tool.
"""

from __future__ import annotations

from importlib import import_module

from ._helpers import ToolSpec

ORDER: tuple[str, ...] = (
    # Session and instances (bridge-local)
    "houdini_status", "houdini_connect",
    # Hip file
    "hip_new", "hip_open", "hip_save", "hip_merge",
    # Reads and mutations (spec-2.0 §2.3, §2.4)
    "inspect", "search", "edit", "node_create", "parm_set",
    # Cook, visual feedback, code, state
    "cook", "render", "look", "houdini_python", "undo", "time", "job",
    # Contexts (full)
    "hda", "pdg", "events",
)  # fmt: skip
"""Spec module names (each equal to its tool's name), in catalogue order."""


def _load() -> tuple[ToolSpec, ...]:
    return tuple(import_module(f"{__name__}.{name}").SPEC for name in ORDER)


TOOLS: tuple[ToolSpec, ...] = _load()
"""Every tool's spec, in :data:`ORDER`."""
