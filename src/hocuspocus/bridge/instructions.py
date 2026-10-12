"""Server ``instructions`` (shipped in ``initialize``) and the ``hocuspocus://guide`` text.

See docs/BIBLE.md §4.8. Keep ``INSTRUCTIONS`` under 400 words; a unit test enforces it.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

INSTRUCTIONS = """\
HocusPocus drives a live Houdini. Identity is Houdini paths. Start with `houdini_status`; \
if nothing is connected, `houdini_connect` can launch Houdini (GUI or headless hython) or \
attach to a running one by pid. Build with `node_create` (batch, with parms and inputs) or \
`network_build` (whole graph from the `network_describe` format). Read with `node_info` and \
`network_describe`. Change values with `parm_set`; tuple paths like `.../t` take lists, \
component paths like `.../tx` take scalars; expressions go in `expression`. After building, \
call `cook` or read `errors` in results, then `geo_info` to check counts and bounds, and \
`viewport_capture` to look at it. Every mutating call is one undo step. Hip tools refuse to \
discard unsaved work unless told to. Long cooks and renders return a `job_id`; poll it with \
`job`. When no tool fits, `houdini_python` runs `hou` code. Results are compact: non-default \
parms only, lists paged with `cursor`; `truncated: true` means the response budget cut a list, \
so page or narrow the query. Errors carry `code`, `hint` and `candidates`; read them and \
adjust. `delivery_unknown` means the call may or may not have run: inspect state before \
repeating it. `_meta.scene_generation` changes when the scene is cleared or loaded, so cached \
paths may be stale."""

GUIDE_HEADER = """\
# HocusPocus operating guide

## Instructions

"""


def _tools_md() -> Path | None:
    # Running from a checkout: <repo>/src/hocuspocus/bridge/instructions.py -> <repo>/docs/tools.md
    candidate = Path(__file__).resolve().parents[3] / "docs" / "tools.md"
    return candidate if candidate.is_file() else None


def guide_text() -> str:
    """The full operating manual: instructions plus ``docs/tools.md`` when available."""
    parts = [GUIDE_HEADER, INSTRUCTIONS, "\n"]
    tools_md = _tools_md()
    if tools_md is not None:
        with contextlib.suppress(OSError):
            parts += ["\n## Tools\n\n", tools_md.read_text(encoding="utf-8")]
    else:
        parts.append(
            "\nThe per-tool reference (`docs/tools.md`) is not installed; read each tool's "
            "description and inputSchema from `tools/list`.\n"
        )
    return "".join(parts)
