"""The policy: which backends render a call, in which order (spec-2.0 §2.5). No ``hou``
except :func:`available_capture_rops`.

``look`` (:func:`plan`):

======================  ==========================================================
request                 chain
======================  ==========================================================
a Cop node (any         ``rop_image`` (the COP's own pixels; ``quality`` ignored)
quality)
``source: viewer``      ``viewer`` (GUI, ``/obj`` only, draft only)
``draft``               ``flipbook`` → ``opengl`` (the types this Houdini has), then
                        ``karma`` after a crash, headless only
``lit``, scene lights   as ``draft``, the Flipbook ROP set to full lighting with shadows
``lit``, no lights      ``karma`` at :data:`~.karma.LIT_SAMPLES` samples
``final``               ``karma`` at the target ROP's samples, else
                        :data:`~.karma.FINAL_SAMPLES`
======================  ==========================================================

A stage is never sent to the viewer.

Running a chain: headless, :func:`run_capture_chain` moves on when a child render
*crashes* and runs Karma only after a crash; in a GUI session a ROP that *writes no image*
hands over to the next and there is no Karma step (a crash there would take Houdini down).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hocuspocus.tools.errors import ToolError

from . import karma as karma_mod
from .base import ROP_LABELS, Env
from .child import child_crashed

CAPTURE_ROPS = ("flipbook", "opengl")
"""The viewport ROP types a draft or lit look tries, in order, before Karma."""
QUALITIES = ("draft", "lit", "final")
LIT_ROP_PARMS = {"lighting": 3}
"""The Flipbook ROP's Lighting menu at "High Quality Lighting with Shadows" (index 3): the
scene's lights with shadows. The ROP's default is the same; ``lit`` sets it explicitly so
a user default or a future default cannot turn a lit look into a headlight one."""

_stage_crashed: dict[str, str] = {}
"""ROP type -> crash message, set when a headless stage capture's child of that ROP crashed
in this process: later stage captures with source auto skip that ROP (each crash costs
seconds)."""


def available_capture_rops() -> list[str]:
    """The :data:`CAPTURE_ROPS` this Houdini has (22.0 has both; older builds lack the
    Flipbook ROP). Main thread."""
    import hou

    category = hou.ropNodeTypeCategory()
    return [t for t in CAPTURE_ROPS if hou.nodeType(category, t) is not None]


def fallback_note(failures: list[tuple[str, str]], used: str) -> str | None:
    """Why a capture used a later renderer of its chain: one note naming each ROP that
    did not render and why (``failures``: ``(rop type, reason)``)."""
    if not failures:
        return None
    why = "; ".join(f"the {ROP_LABELS[t]} {reason}" for t, reason in failures)
    if used == "karma":
        return karma_mod.karma_note(why)
    return f"Rendered with the {ROP_LABELS[used]} because {why}."


def run_capture_chain(
    chain: list[str],
    *,
    stage: bool,
    source: str,
    render_rop: Any,
    render_karma: Any,
) -> tuple[str, dict[str, Any], list[str]]:
    """Render one capture with the first renderer of ``chain`` that works. ``render_rop``
    (a ROP type) returns the render outcome or raises; a crashed child moves on to the next
    renderer, any other error is raised. Karma runs only after a crash or skip. Returns
    ``(renderer, outcome, notes)``. Headless, a stage whose child crashed once is not sent
    to that ROP again in this process when ``source`` is ``auto`` (each crash costs
    seconds)."""
    failures: list[tuple[str, str]] = []
    crash: ToolError | None = None
    for renderer in chain:
        if renderer == "karma":
            if not failures:
                break  # nothing crashed: the last ROP's error was raised already
            karma_mod.karma_after_crash(render_karma, crash)
            return "karma", {}, [n for n in (fallback_note(failures, "karma"),) if n]
        if stage and source == "auto" and renderer in _stage_crashed:
            failures.append(
                (renderer, "was skipped (it crashed a stage capture earlier in this session)")
            )
            continue
        try:
            outcome = render_rop(renderer)
        except ToolError as exc:
            if not child_crashed(exc):
                raise
            crash = exc
            if stage:
                _stage_crashed[renderer] = exc.message
            failures.append((renderer, f"crashed its render process ({exc.message})"))
            continue
        return renderer, outcome, [n for n in (fallback_note(failures, renderer),) if n]
    raise ToolError("internal", "No renderer could capture the scene.")


def backends() -> dict[str, Any]:
    """Every backend by name, in chain order."""
    from .cop import ROP_IMAGE
    from .flipbook import FLIPBOOK
    from .karma import KARMA
    from .opengl import OPENGL
    from .viewer import VIEWER

    return {b.name: b for b in (VIEWER, FLIPBOOK, OPENGL, KARMA, ROP_IMAGE)}


@dataclass(frozen=True)
class Plan:
    """The chosen chain and how its backends are set up."""

    chain: tuple[str, ...]
    samples: int | None = None
    """Karma's samples per pixel when Karma is the chosen renderer (not a fallback)."""
    rop_parms: dict[str, Any] = field(default_factory=dict)
    """Extra parms for the viewport ROPs."""
    notes: tuple[str, ...] = ()


def _usable(names: Any, spec: Any, env: Env) -> list[str]:
    table = backends()
    return [n for n in names if table[n].can_run(spec, env)[0]]


def _rop_chain(spec: Any, env: Env) -> tuple[str, ...]:
    """The viewport ROPs this Houdini has, and Karma after a crash headless."""
    rops = _usable(CAPTURE_ROPS, spec, env)
    return tuple(rops + ([] if env.ui else ["karma"]))


def plan(spec: Any, env: Env) -> Plan:
    """``look``'s chain for ``spec`` (``kind``, ``quality``, ``source``, ``rop_samples``)
    in ``env``. Raises the error an agent can act on when the request cannot be met."""
    if spec.quality not in QUALITIES:
        raise ToolError("invalid_argument", f"'quality' must be one of {', '.join(QUALITIES)}.")
    if spec.kind == "cop":
        if spec.source == "viewer":
            raise ToolError(
                "invalid_argument",
                "source viewer shows the Scene Viewer; a Cop node renders through rop_image.",
                hint="Omit source.",
            )
        notes = ()
        if spec.quality != "draft":
            notes = (f"quality {spec.quality} is ignored for a Cop node: the image is its own.",)
        return Plan(("rop_image",), notes=notes)
    if spec.source == "viewer":
        ok, why = backends()["viewer"].can_run(spec, env)
        if not ok:
            if not env.ui:
                raise ToolError(
                    "ui_required",
                    "source viewer grabs the GUI Scene Viewer, and this Houdini is headless.",
                    hint="Omit source: the Flipbook ROP renders headless.",
                )
            if spec.kind == "lop":
                raise ToolError(
                    "invalid_argument",
                    "source viewer shows the Scene Viewer; a stage renders through a Flipbook ROP.",
                    hint="Omit source.",
                )
            raise ToolError(
                "invalid_value",
                f"source viewer cannot run: {why}.",
                hint="Open a Scene Viewer, or omit source.",
            )
        if spec.quality != "draft":
            raise ToolError(
                "invalid_argument",
                f"source viewer is a draft look; quality {spec.quality} renders.",
                hint="Omit source, or use quality draft.",
            )
        return Plan(("viewer",))
    if spec.quality == "final":
        samples = spec.rop_samples or karma_mod.FINAL_SAMPLES
        return Plan(("karma",), samples=samples)
    if spec.quality == "lit" and not env.lights:
        return Plan(
            ("karma",),
            samples=karma_mod.LIT_SAMPLES,
            notes=(
                f"The scene has no lights, so lit rendered Karma at {karma_mod.LIT_SAMPLES} "
                "samples per pixel with its default light; add a light for the Flipbook ROP.",
            ),
        )
    chain = _rop_chain(spec, env)
    if not chain or chain == ("karma",):
        # No viewport ROP type: Karma is the only renderer left (headless), or none (GUI).
        if env.ui:
            raise ToolError(
                "internal", "This Houdini has neither a Flipbook ROP nor an OpenGL ROP."
            )
        return Plan(("karma",), samples=karma_mod.KARMA_SAMPLES)
    return Plan(chain, rop_parms=dict(LIT_ROP_PARMS) if spec.quality == "lit" else {})
