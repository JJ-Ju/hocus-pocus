"""Catalogue entry for ``houdini_python`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _enum, _n, _obj, _s

SPEC = ToolSpec(
    name="houdini_python",
    description=(
        "Run Python (hou bound) or HScript on Houdini's main thread in one undo step, for "
        "anything no tool covers. Returns stdout, stderr and result. An uncaught exception "
        "fails with python_exception and is rolled back; code still running near timeout_s is "
        "stopped (houdini_busy)."
    ),
    notes=(
        "result is the value of a trailing expression or a result variable, JSON-serialised "
        "(repr fallback). sys.exit counts as an uncaught exception; stdout, stderr and the "
        "traceback are in detail. Output is capped at the response budget (truncated). Fails "
        "with python_disabled when turned off."
    ),
    input_schema=_obj(
        {
            "code": _s(),
            "timeout_s": _n(None, minimum=1, default=30),
            "language": _enum(("python", "hscript"), "python"),
            "undo_label": _s(),
        },
        ("code",),
    ),
    destructive=True,
    examples=(
        {"code": "len(hou.node('/obj').children())"},
        {"code": "opls /obj", "language": "hscript"},
    ),
)
