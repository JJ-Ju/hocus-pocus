"""Visual feedback: ``render``. See docs/BIBLE.md §4.6 and §8.

Images go back as ``{"image": {"png_base64", "mime_type"}}`` (the bridge turns that into
MCP image content) and are also written under ``<state_dir>/captures``.

**The capture and render backends live in** :mod:`hocuspocus.host.look` (2.0, spec-2.0
§4): the viewer grab, the Flipbook ROP with its kept headless child, the OpenGL ROP, Karma
and ``rop_image``, the snapshot and child hython, framing and the chain policy; ``look``
(``host/tools/look.py``) runs them. ``render`` of a Flipbook or OpenGL ROP renders
headless in a fresh :class:`~hocuspocus.host.look.child.ChildRender` (the snapshot
contract is in :mod:`hocuspocus.host.look.base`); every other ROP type renders in-process,
frame by frame, through the main-thread executor. (2.1 removed ``viewport_capture``, the
1.4 capture tool that ran the same backends with its own policy.)

The names the capture code had in 1.4 stay importable from here. The module-level
settings and stand-ins that tests and the docs set on this module (``WARM_CAPTURES``,
``_CHILD_SCRIPT``, ``_stage_crashed``, ``capture_with_karma``, ...) are forwarded to the
look module that owns them (:data:`_FORWARDED`), so setting ``visual.WARM_CAPTURES =
False`` still turns the kept child off.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import time
import types
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import BARE, hint_join, hint_tool

from ..look import child as _child
from ..look import flipbook as _flipbook
from ..look import karma as _karma
from ..look import select as _select
from ..look.base import (  # noqa: F401  (1.4 names, re-exported)
    INTERNAL_KEY,
    ROP_LABELS,
    TEMPORARY_CAMERA,
    error_lines,
    failure,
    log_tail,
)
from ..look.base import add_notes as _add_notes  # noqa: F401
from ..look.base import check_capture_output as _check_capture_output  # noqa: F401
from ..look.base import mark_internal as _mark_internal  # noqa: F401
from ..look.child import (  # noqa: F401
    CHILD_TIMEOUT_S,
    CRASH_LOG_CHARS,
    JOB_POLL_S,
    NOT_CARRIED_VARS,
    ChildRender,
    child_crashed,
    crash_summary,
    exit_error,
    snapshot_scene,
)
from ..look.cop import (  # noqa: F401
    CHANNEL_NAMES,
    NON_IMAGE_OUTPUTS,
    cop_display,
    cop_image_node,
    image_summary,
    is_cop_network,
    is_cop_node,
)
from ..look.flipbook import (  # noqa: F401
    WARM_CRASH_NOTE,
    WarmCapture,
    _warm,
    close_warm_capture,
    render_capture_child,
    warm_key,
)
from ..look.framing import (  # noqa: F401
    CAMERA_LENS,
    CAPTURE_CAMERA_PRIM,
    VIEW_DIRECTION,
    _capture_spec,
    _framing,
    _is_lop_camera,
    _is_obj_camera,
    _last_framing,
    _obj_camera,
    _usd_source_lop,
    _world_bbox,
    capture_target,
    rop_lop_source,
    scene_cameras,
    scene_has_lights,
    temporary_capture_nodes,
)
from ..look.image import (  # noqa: F401
    BACKGROUND,
    CAPTURES_KEEP,
    IMAGE_EXTS,
    IMAGE_MAX_SIDE,
    THUMB_MAX_SIDE,
    _captures,
    encode_png,
    flatten_png_in_place,
    prune_captures,
)
from ..look.image import capture_targets as _capture_targets  # noqa: F401
from ..look.karma import KARMA_SAMPLES, karma_after_crash, karma_note  # noqa: F401
from ..look.select import (  # noqa: F401
    CAPTURE_ROPS,
    available_capture_rops,
    fallback_note,
    run_capture_chain,
)
from ..look.viewer import _capture_viewer, _scene_viewer, _viewer_context_note  # noqa: F401
from ._diag import require_node
from .geo import frame_num
from .hip import _norm, check_allowed, resolve_path
from .registry import HostContext, tool

VIEWPORT_ROP_TYPES = frozenset(CAPTURE_ROPS)
"""ROP types whose headless renders go through a child hython (module docstring)."""

_FORWARDED: dict[str, Any] = {
    "_CHILD_SCRIPT": _child,
    "_BUILD_CAPTURE": _child,
    "WARM_CAPTURES": _flipbook,
    "WARM_IDLE_S": _flipbook,
    "WARM_MAX_USES": _flipbook,
    "_stage_crashed": _select,
    "capture_with_karma": _karma,
}
"""Names read and set through this module but owned by a look module: a property on the
module's class forwards both, so a test's ``monkeypatch.setattr(visual, ...)`` reaches the
code that uses the value."""


class _VisualModule(types.ModuleType):
    pass


def _forward(name: str, owner: Any) -> property:
    return property(
        lambda _self: getattr(owner, name),
        lambda _self, value: setattr(owner, name, value),
    )


for _name, _owner in _FORWARDED.items():
    setattr(_VisualModule, _name, _forward(_name, _owner))
sys.modules[__name__].__class__ = _VisualModule

OUTPUT_PARMS = (
    "picture",  # flipbook, opengl, karma
    "vm_picture",  # mantra (ifd)
    "sopoutput",  # geometry
    "copoutput",  # comp
    "lopoutput",  # usd
    "outputimage",  # usdrender
    "filename",  # alembic, fbx
    "file",
    "output",
)
MPLAY_OUTPUTS = {"ip", "md", "imdisplay"}
CONVERT_EXTS = {".exr", ".pic", ".rat", ".hdr", ".dpx", ".cin", ".sgi", ".rgb"}
IMAGE_PARMS = ("picture", "vm_picture", "copoutput", "outputimage")
"""Output parms that name an image; other ROPs (geometry, USD, Alembic) get no note about
a missing thumbnail."""
FRAME_TIMEOUT_S = 24 * 3600.0
INLINE_OUTPUTS = 5
"""A render result lists at most this many outputs; above it, ``outputs_summary`` and
``outputs_sample``, in the direct result and in ``job result`` alike (review 20 N5)."""
OUTPUTS_SAMPLE_ENDS = 2
"""``outputs_sample`` is this many outputs from each end of the sequence."""
MISSING_LISTED = 20
"""``missing`` lists at most this many paths; ``outputs_summary.missing_count`` counts all."""
DARK_MEAN = 8.0
"""A thumbnail whose mean luminance (0..255), measured on the flattened image the agent
receives, is below this is reported as nearly black."""
NO_LIGHTS_NOTE = (
    "Scene has no lights; a Flipbook or OpenGL ROP render relies on the ROP's headlight "
    "setting and other renderers may render black."
)


# -- small helpers ------------------------------------------------------------------


def run_with_fallback(executor: Any, fn: Any, timeout_s: float) -> str | None:
    """Run ``fn`` on the main thread; if that fails (busy, timeout), queue it with
    ``post`` instead. Never raises, so a caller's own error is not replaced. Returns a
    note when ``fn`` did not run synchronously."""
    try:
        executor.run(fn, timeout_s)
        return None
    except Exception as exc:
        first = f"{type(exc).__name__}: {exc}"
    try:
        executor.post(fn)
    except Exception as exc:
        return f"{first}; queueing a retry also failed ({type(exc).__name__}: {exc})"
    return f"{first}; a retry was queued for the main thread"


def rop_core_type(rop_node: Any) -> str:
    return rop_node.type().name().split("::")[0]


def needs_isolation(rop_node: Any, ctx: HostContext) -> bool:
    """Headless Flipbook and OpenGL ROPs render in a child hython (module docstring)."""
    return not ctx.ui and rop_core_type(rop_node) in VIEWPORT_ROP_TYPES


# -- Copernicus images (review 18) ----------------------------------------------------

COP_ROP_CANDIDATES = 10


def cop_rop_candidates(node: Any) -> list[str]:
    """The ``rop_image`` nodes in the COP network holding ``node`` (or ``node`` itself
    when it is the network), which ``render`` can render."""
    net = node if is_cop_network(node) else node.parent()
    out = []
    for child in net.children() if net is not None else ():
        with contextlib.suppress(Exception):
            if child.type().nameComponents()[2] == "rop_image":
                out.append(child.path())
    return out[:COP_ROP_CANDIDATES]


def cop_hint(node: Any) -> str:
    """Where a COP node's pixels come from: a look at the node (``look {target}``), a
    rop_image for files (review 18 papercuts 1 and 2)."""
    net = node if is_cop_network(node) else node.parent()
    where = net.path() if net is not None else "the COP network"
    return (
        f"{hint_tool('look', target=node.path())} returns the image; to write "
        f"files, render a Cop rop_image inside {where} (coppath = the node)."
    )


# -- render ---------------------------------------------------------------------------


def _frames(value: Any) -> list[float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list | tuple)
        or len(value) not in (2, 3)
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        raise ToolError("invalid_argument", "'frames' must be [start, end] or [start, end, inc].")
    start, end = float(value[0]), float(value[1])
    inc = float(value[2]) if len(value) == 3 else 1.0
    if inc <= 0:
        raise ToolError("invalid_argument", "The frame increment must be > 0.")
    if end < start:
        raise ToolError("invalid_argument", "'frames' end must be >= start.")
    if (end - start) / inc > 100_000:
        raise ToolError("invalid_argument", "'frames' covers more than 100000 frames.")
    return [start, end, inc]


def _frame_list(frames: list[float]) -> list[float]:
    start, end, inc = frames
    out = []
    i = 0
    while True:
        f = start + i * inc
        if f > end + 1e-6:
            break
        out.append(f)
        i += 1
    return out


def output_pattern(first: str, last: str) -> str:
    """``render/s.####.png`` from the first and last outputs: the digit run that differs
    becomes ``#`` per digit of the first. Falls back to ``first … last``."""
    if first == last:
        return first
    prefix = len(os.path.commonprefix([first, last]))
    suffix = len(os.path.commonprefix([first[::-1], last[::-1]]))
    suffix = min(suffix, len(first) - prefix, len(last) - prefix)
    start, end = prefix, len(first) - suffix
    while start > 0 and first[start - 1].isdigit():
        start -= 1
    while end < len(first) and first[end].isdigit():
        end += 1
    run = first[start:end]
    if not run.isdigit():
        return f"{first} … {last}"
    return first[:start] + "#" * len(run) + first[end:]


def is_usd_render_rop(rop: Any) -> bool:
    """A USD render ROP (``Lop/usdrender_rop``, ``Driver/usdrender``, Karma's wrappers):
    husk renders the stage; ``lopoutput`` is only its intermediate USD file."""
    return rop.parm("outputimage") is not None and rop.parm("lopoutput") is not None


def _output_parm(rop: Any) -> Any:
    if is_usd_render_rop(rop):
        return rop.parm("outputimage")  # never lopoutput (review 13 papercut 2)
    for name in OUTPUT_PARMS:
        parm = rop.parm(name)
        if parm is not None:
            return parm
    return None


# -- writer SOPs: File Cache, ROP SOPs (review 17 P0-1, P0-2, P1-3) --------------------

SAVE_BUTTON = "execute"
"""The save button of a File Cache and of every ROP (``Save to Disk``, ``Render``)."""
SIDE_EFFECT_CAP = 10
WRITTEN_SLACK_S = 2.0
"""A file counts as written by a press when its mtime is at most this much older than
the press (file systems round mtimes)."""


def writer_rop(node: Any) -> Any:
    """The ROP that writes ``node``'s files: the node itself when it is a ROP (a /out
    driver, a SOP-level ``rop_geometry``/``rop_alembic``, a Cop ``rop_image``), or the
    ROP inside a SOP whose ``execute`` button saves through one, such as
    ``filecache::2.0`` (its ``render`` child, else the first ROP inside it). None for any
    other node. Main thread."""
    import hou

    if isinstance(node, hou.RopNode):
        return node
    if not isinstance(node, hou.SopNode):
        return None
    button = node.parm(SAVE_BUTTON)
    try:
        if button is None or button.parmTemplate().type() != hou.parmTemplateType.Button:
            return None
    except Exception:
        return None
    inner = node.node("render")
    if isinstance(inner, hou.RopNode):
        return inner
    try:
        children = node.allSubChildren(recurse_in_locked_nodes=True)
    except Exception:
        children = ()
    return next((c for c in children if isinstance(c, hou.RopNode)), None)


def rop_frame_range(rop: Any) -> list[float] | None:
    """``[start, end, inc]`` from the ROP's own Valid Frame Range, or None when it renders
    the current frame only (``trange`` 0) or has no range. Main thread."""
    trange = rop.parm("trange")
    if trange is None:
        return None
    try:
        if not int(trange.eval()):
            return None
        start, end = (float(rop.parm(n).eval()) for n in ("f1", "f2"))
        inc = float(rop.parm("f3").eval()) if rop.parm("f3") is not None else 1.0
    except Exception:
        return None
    if inc <= 0 or end < start:
        return None
    return [start, end, inc]


def default_frames(rop: Any, name: str) -> tuple[list[float], str | None]:
    """The frames ``render`` renders without ``frames``: the ROP's own Valid Frame Range,
    else the current frame, with a note saying which (review 23 P1-2: a usd_rop set to
    frames 1-48 rendered frame 1 only, silently). Main thread."""
    import hou

    own = rop_frame_range(rop)
    if own is not None:
        start, end, inc = own
        step = f" step {frame_num(inc)}" if inc != 1 else ""
        return own, (
            f"Rendered {name}'s own frame range {frame_num(start)}-{frame_num(end)}{step}; "
            "pass frames to render others."
        )
    frame = hou.frame()
    note = None
    if rop.parm("trange") is not None:
        note = (
            f"Rendered the current frame ({frame_num(frame)}) only: {name}'s Valid Frame Range "
            "is 'Render Current Frame'. Pass frames to render a range."
        )
    return [frame, frame, 1.0], note


def expected_outputs(rop: Any, frames: list[float]) -> list[str]:
    """The files ``rop`` writes for ``frames`` (``[start, end, inc]``), from its output
    parm; MPlay and empty outputs are left out. Main thread."""
    parm = _output_parm(rop)
    if parm is None:
        return []
    out = []
    for frame in _frame_list(frames):
        value = parm.evalAtFrame(frame).strip()
        if value and value not in MPLAY_OUTPUTS:
            out.append(_norm(value))
    return out


def outputs_summary(outputs: list[str], missing: list[str]) -> dict[str, Any]:
    """``{count, first, last, pattern, missing_count}`` for a file sequence. No ``hou``."""
    summary: dict[str, Any] = {"count": len(outputs)}
    if outputs:
        summary["first"] = outputs[0]
        summary["last"] = outputs[-1]
        summary["pattern"] = output_pattern(outputs[0], outputs[-1])
    summary["missing_count"] = len(missing)
    return summary


def _top_parm_values(node: Any) -> dict[str, Any]:
    """Raw values of ``node``'s value parms (not buttons, folders or labels; menus as
    tokens), to report what a button press changed. Main thread."""
    import hou

    skip = (
        hou.parmTemplateType.Button,
        hou.parmTemplateType.Folder,
        hou.parmTemplateType.FolderSet,
        hou.parmTemplateType.Label,
        hou.parmTemplateType.Separator,
    )
    values: dict[str, Any] = {}
    for parm in node.parms():
        try:
            kind = parm.parmTemplate().type()
            if parm.isMultiParmParent():
                values[parm.name()] = parm.eval()  # the instance count
                continue
            if kind in skip:
                continue
            if kind == hou.parmTemplateType.Menu:
                values[parm.name()] = parm.evalAsString()  # the token, not the index
                continue
            try:
                values[parm.name()] = parm.unexpandedString()
            except Exception:
                values[parm.name()] = parm.eval()
        except Exception:
            continue
    return values


def changed_parms(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """``{name: [old, new]}`` for parms whose raw value changed, at most
    :data:`SIDE_EFFECT_CAP`. No ``hou``."""
    changes = {
        name: [before[name], value]
        for name, value in after.items()
        if name in before and before[name] != value
    }
    return dict(list(changes.items())[:SIDE_EFFECT_CAP])


def press_button(node: Any, parm: Any) -> dict[str, Any]:
    """Press a button (or run a menu's callback) and report it: ``{pressed: true,
    side_effects?}``, plus ``outputs_summary`` for the save button of a writer (a File
    Cache's Save to Disk, a ROP's Render): the files its output parm names over the
    writer's frame range are checked afterwards, and a press that left any of them
    unwritten fails with ``cook_failed`` listing them (review 17 P0-2: a failed save
    reported success). Main thread."""
    import hou

    rop = writer_rop(node) if parm.name() == SAVE_BUTTON else None
    expected: list[str] = []
    if rop is not None:
        frames = rop_frame_range(rop) or [hou.frame(), hou.frame(), 1.0]
        try:
            expected = expected_outputs(rop, frames)
        except Exception:
            expected = []
    before = _top_parm_values(node)
    started = time.time()
    parm.pressButton()
    out: dict[str, Any] = {"pressed": True}
    changes = changed_parms(before, _top_parm_values(node))
    if changes:
        out["side_effects"] = changes
    if not expected:
        return out
    written, missing = [], []
    for path in expected:
        try:
            fresh = os.path.getmtime(path) >= started - WRITTEN_SLACK_S
        except OSError:
            fresh = False
        (written if fresh else missing).append(path)
    if missing:
        errors: list[str] = []
        with contextlib.suppress(Exception):
            errors = error_lines([str(e) for e in rop.errors()])
        detail: dict[str, Any] = {
            "missing": missing[:MISSING_LISTED],
            "missing_count": len(missing),
        }
        if errors:
            detail["errors"] = errors[:5]
        raise ToolError(
            "cook_failed",
            f"{node.path()} {parm.name()} wrote {len(written)} of {len(expected)} files"
            + (f": {errors[0]}" if errors else "."),
            hint="Check that the output directory is writable and the input cooks, then press "
            "again"
            + (
                f"; {render} runs the same save as a job with progress and cancel."
                if (render := hint_tool("render", rop_path=node.path()))
                else "."
            ),
            detail=detail,
        )
    out["outputs_summary"] = outputs_summary(written, missing)
    return out


def _render_settings_prim(stage: Any, rop: Any) -> Any:
    """The RenderSettings prim husk uses: the ROP's ``rendersettings``, else the stage's
    ``renderSettingsPrimPath``, else the first one under /Render (then anywhere)."""
    from pxr import Usd, UsdRender

    path = ""
    if rop.parm("rendersettings") is not None:
        path = rop.parm("rendersettings").eval().strip()
    if path:
        prim = stage.GetPrimAtPath(path)
        return prim if prim and prim.IsA(UsdRender.Settings) else None
    with contextlib.suppress(Exception):
        settings = UsdRender.Settings.GetStageRenderSettings(stage)
        if settings:
            return settings.GetPrim()
    render = stage.GetPrimAtPath("/Render")
    ranges = [Usd.PrimRange(render)] if render else []
    ranges.append(stage.Traverse())
    for prims in ranges:
        for prim in prims:
            if prim.IsA(UsdRender.Settings):
                return prim
    return None


def usd_render_outputs(rop: Any, frames: list[float]) -> tuple[list[str], str | None]:
    """Image files a USD render ROP writes when ``outputimage`` is empty: the
    ``productName`` of every RenderProduct of its render settings, per frame (review 13
    papercut 1). Returns ``(paths, note)``; the note says why nothing resolved. Main thread."""
    from pxr import Usd, UsdRender

    lop = _usd_source_lop(rop)
    if lop is None:
        return [], (
            f"{rop.path()} has no LOP to render (loppath or an input), so its output image "
            "is unknown; set outputimage, or wire the render settings LOP into it."
        )
    stages: dict[float, Any] = {}

    def stage_at(frame: float | None) -> Any:
        key = -1e30 if frame is None else frame
        if key not in stages:
            stages[key] = lop.stage() if frame is None else lop.stage(frame=frame)
        return stages[key]

    try:
        stage = stage_at(None)
        settings = _render_settings_prim(stage, rop) if stage is not None else None
    except Exception:
        stage = settings = None
    if settings is None:
        return [], (
            f"No output image resolved for {rop.path()}: outputimage is empty and "
            f"{lop.path()}'s stage has no render settings prim with a RenderProduct; set "
            "outputimage, or picture on the render settings LOP."
        )
    targets = UsdRender.Settings(settings).GetProductsRel().GetForwardedTargets()
    paths: list[str] = []
    for frame in frames:
        for target in targets:
            attr = UsdRender.Product(stage.GetPrimAtPath(target)).GetProductNameAttr()
            if not attr:
                continue
            samples = attr.GetTimeSamples()
            current = attr
            if samples and not samples[0] <= frame <= samples[-1]:
                # Sampled over the playbar only: cook the stage at that frame.
                with contextlib.suppress(Exception):
                    current = stage_at(frame).GetPrimAtPath(target).GetAttribute("productName")
            value = current.Get(Usd.TimeCode(frame)) if current else None
            if value:
                paths.append(str(value))
    if not paths:
        return [], (
            f"No output image resolved for {rop.path()}: outputimage is empty and the "
            f"RenderProduct productName under {settings.GetPath()} is empty; set outputimage, "
            "or picture on the render settings LOP."
        )
    return paths, None


# -- single-file ROPs: USD, Alembic (review 23 P0-1) -----------------------------------

USD_EXTS = (".usd", ".usda", ".usdc", ".usdz")
LAYERS_LISTED = 20
"""A USD render lists at most this many layer files."""
SAMPLE_SLACK = 1e-3


def single_file_kind(path: str) -> str | None:
    """``usd`` or ``abc`` for an output file that holds every frame of a range, from its
    extension; None for any other file. No ``hou``."""
    ext = os.path.splitext(path)[1].lower()
    if ext in USD_EXTS:
        return "usd"
    return "abc" if ext == ".abc" else None


def _layer_dependencies(layer: Any, path: str) -> list[str]:
    """The files ``layer`` (opened from ``path``) composes: sublayers, references and
    payloads, relative paths resolved against its directory. No ``hou``."""
    out = []
    for dep in layer.GetCompositionAssetDependencies():
        dep = str(dep).split(":SDF_FORMAT_ARGS:")[0]
        if not dep or dep.startswith("anon:"):
            continue
        full = dep if os.path.isabs(dep) else os.path.join(os.path.dirname(path), dep)
        out.append(_norm(os.path.normpath(full)))
    return out


def usd_layers(root: str, since: float | None = None) -> list[dict[str, Any]]:
    """Every USD layer file a render wrote: ``root`` and the files it composes, followed
    through each layer (a sopimport's save path is a sublayer of a usd_rop's root layer),
    then USD files in ``root``'s directory modified since ``since`` that none of them
    reached. Rows ``{path, bytes, time_samples, time_codes?}``, at most
    :data:`LAYERS_LISTED`. Opened as anonymous copies, so the session's cached layers are
    neither used nor reloaded. ``pxr``, no ``hou``."""
    from pxr import Sdf

    queue, seen, rows = [_norm(root)], set(), []
    scanned = False
    while len(rows) < LAYERS_LISTED:
        if not queue:
            if scanned or since is None:
                break
            scanned = True
            folder = os.path.dirname(_norm(root))
            with contextlib.suppress(OSError):
                for name in sorted(os.listdir(folder)):
                    full = _norm(os.path.join(folder, name))
                    if os.path.splitext(name)[1].lower() not in USD_EXTS:
                        continue
                    with contextlib.suppress(OSError):
                        if os.path.getmtime(full) >= since - WRITTEN_SLACK_S:
                            queue.append(full)
            continue
        path = queue.pop(0)
        key = os.path.normcase(path)
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        row: dict[str, Any] = {"path": path, "bytes": os.path.getsize(path)}
        layer = None
        with contextlib.suppress(Exception):
            layer = Sdf.Layer.OpenAsAnonymous(path)
        if layer is not None:
            samples = sorted(layer.ListAllTimeSamples())
            row["time_samples"] = len(samples)
            if samples:
                row["time_codes"] = [frame_num(samples[0]), frame_num(samples[-1])]
            queue.extend(_layer_dependencies(layer, path))
        rows.append(row)
    return rows


def _lost_frames(rop: str, path: str, found: str, frames: list[float]) -> ToolError:
    return ToolError(
        "cook_failed",
        f"{rop} wrote {found} for {len(frames)} frames to {os.path.basename(path)}: a "
        "single-file output lost frames.",
        hint="Check the ROP's frame range parms and that the input is animated, then render "
        "again with frames.",
        detail={"path": path, "frames": [frame_num(frames[0]), frame_num(frames[-1])]},
    )


def check_single_file(
    rop: str, path: str, frames: list[float], since: float | None = None
) -> dict[str, Any]:
    """Read back a single-file output after a render (review 23 P0-1: frame by frame,
    each call overwrote the file and only the last frame's sample survived). USD: lists
    :func:`usd_layers`, and over a range the layer with the most time samples must have
    one per frame; none at all is a static stage (a note). Alembic: the archive's time
    range must cover the frames. Raises ``cook_failed``; returns ``{notes?, layers?}``.
    Main thread (``hou.fps``)."""
    import hou

    kind = single_file_kind(path)
    out: dict[str, Any] = {}
    if kind is None or not os.path.isfile(path):
        return out
    if kind == "usd":
        # Every layer file written, not only the root (review 23 P1-3: the data was in the
        # sopimport's save path, a sublayer of a 697 B root layer).
        layers = usd_layers(path, since)
        out["layers"] = layers
    if len(frames) < 2:
        return out
    start, end = frames[0], frames[-1]
    if kind == "usd":
        counts = []
        for row in layers:
            codes = row.get("time_codes")
            if codes and codes[-1] >= start - SAMPLE_SLACK and codes[0] <= end + SAMPLE_SLACK:
                counts.append((row["time_samples"], row["path"]))
        if not counts:
            out["notes"] = [
                f"No layer {rop} wrote has time samples: the exported stage is static over "
                f"frames {frame_num(start)}-{frame_num(end)}."
            ]
            return out
        best, where = max(counts)
        if best < len(frames):
            plural = "s" if best != 1 else ""
            raise _lost_frames(rop, where, f"{best} time sample{plural}", frames)
        return out
    import _alembic_hom_extensions as alembic

    span = None
    with contextlib.suppress(Exception):
        span = alembic.alembicTimeRange(path)
    fps = hou.fps()
    if span is None:
        raise _lost_frames(rop, path, "a single time sample", frames)
    first, last = span[0] * fps, span[1] * fps
    if first > start + SAMPLE_SLACK or last < end - SAMPLE_SLACK:
        raise _lost_frames(
            rop, path, f"frames {frame_num(round(first, 3))}-{frame_num(round(last, 3))}", frames
        )
    return out


# -- shared USD layers (review 24 N1) ------------------------------------------------

USD_WRITER_TYPES = (("Lop", "usd_rop"), ("Driver", "usd"), ("Sop", "usdexport"))
"""ROPs that write USD layer files (not husk renders): their ``lopoutput`` and the save
paths of the LOPs they export can collide."""


def _layer_key(path: str) -> str:
    return os.path.normcase(_norm(path))


def usd_save_paths(rop: Any) -> dict[str, str]:
    """``{save path: LOP path}`` for the LOPs a USD writer ROP exports that save their layer
    to a file of their own (a ``sopimport``'s ``savepath``, on by default as
    ``$HIP/usd/$OS.usd`` whatever the ROP's output). Main thread."""
    import hou

    out: dict[str, str] = {}
    lop = None
    with contextlib.suppress(Exception):
        lop = rop.inputs()[0] if isinstance(rop, hou.LopNode) and rop.inputs() else None
        if lop is None and rop.parm("loppath") is not None:
            lop = _usd_source_lop(rop)
    if not isinstance(lop, hou.LopNode):
        return out
    try:
        nodes = [lop, *lop.inputAncestors()]
    except Exception:
        nodes = [lop]
    for node in nodes:
        parm = node.parm("savepath") if isinstance(node, hou.LopNode) else None
        if parm is None:
            continue
        with contextlib.suppress(Exception):
            enable = node.parm("enable_savepath")
            if enable is not None and not int(enable.eval()):
                continue
            value = parm.eval().strip()
            if value and single_file_kind(value) == "usd":
                out.setdefault(_norm(value), node.path())
    return out


def usd_writer_rops() -> list[Any]:
    """Every USD writer ROP in the scene (:data:`USD_WRITER_TYPES`). Main thread."""
    import hou

    categories = {
        "Lop": hou.lopNodeTypeCategory,
        "Driver": hou.ropNodeTypeCategory,
        "Sop": hou.sopNodeTypeCategory,
    }
    found = []
    for category, name in USD_WRITER_TYPES:
        with contextlib.suppress(Exception):
            node_type = hou.nodeType(categories[category](), name)
            if node_type is not None:
                found.extend(node_type.instances())
    return found


def shared_layer_writers(rop: Any, root: str, saves: dict[str, str]) -> dict[str, list[str]]:
    """``{layer path: [other ROP paths]}`` for the layer files ``rop`` writes (its root
    layer ``root`` and the save paths ``saves``) that another USD writer ROP in the scene
    writes too: the same ``lopoutput``, or a LOP save path they both export. Main thread."""
    mine = {_layer_key(root): _norm(root)}
    mine.update({_layer_key(path): path for path in saves})
    shared: dict[str, list[str]] = {}
    for other in usd_writer_rops():
        if other.path() == rop.path():
            continue
        theirs: set[str] = set()
        with contextlib.suppress(Exception):
            value = other.parm("lopoutput").eval().strip()
            if value:
                theirs.add(_layer_key(value))
        theirs.update(_layer_key(path) for path in usd_save_paths(other))
        for key in sorted(theirs & set(mine)):
            shared.setdefault(mine[key], []).append(other.path())
    return shared


def layer_snapshot(paths: list[str]) -> dict[str, dict[str, Any]]:
    """``{normcase path: layer row}`` for the USD layer files that exist now among
    ``paths`` and the layers they compose (:func:`usd_layers`), taken before a render so
    its read-back can tell what it replaced. ``pxr``, no ``hou``."""
    out: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not os.path.isfile(path) or _layer_key(path) in out:
            continue
        with contextlib.suppress(Exception):
            for row in usd_layers(path):
                out.setdefault(_layer_key(row["path"]), row)
    return out


def _samples_text(row: dict[str, Any]) -> str:
    count = row.get("time_samples") or 0
    text = f"{count} sample{'s' if count != 1 else ''}"
    codes = row.get("time_codes")
    if codes:
        text += f" ({frame_num(codes[0])}-{frame_num(codes[-1])})"
    return text


def overwrote_samples(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Whether a render replaced a layer's time samples with fewer, or with time codes
    that no longer cover the old range (review 24 N1). No ``hou``."""
    old = before.get("time_samples") or 0
    if not old:
        return False
    new = after.get("time_samples") or 0
    if new < old:
        return True
    was, now = before.get("time_codes"), after.get("time_codes")
    if not was or not now:
        return False
    return now[0] > was[0] + SAMPLE_SLACK or now[-1] < was[-1] - SAMPLE_SLACK


def layer_overwrites(
    layers: list[dict[str, Any]],
    before: dict[str, dict[str, Any]],
    shared: dict[str, list[str]],
    saves: dict[str, str],
) -> list[str]:
    """Mark the layer rows a USD render replaced (review 24 N1: a second ``usd_rop``
    rewrote the ``sopimport`` save path another ROP had written with 48 samples, silently):
    ``overwrote_samples`` (the sample count it had) on a row whose samples shrank or moved,
    and ``shared_with`` (the other ROPs writing that file). Returns the notes, the
    overwrites first. No ``hou``."""
    shared_keys = {_layer_key(path): rops for path, rops in shared.items()}
    owners = {_layer_key(path): node for path, node in saves.items()}
    overwrites, warnings = [], []
    for row in layers:
        key = _layer_key(row["path"])
        name = os.path.basename(row["path"])
        others = shared_keys.get(key)
        if others:
            row["shared_with"] = others
        where = f" (the save path of {owners[key]})" if key in owners else ""
        old = before.get(key)
        if old is not None and overwrote_samples(old, row):
            row["overwrote_samples"] = old.get("time_samples") or 0
            why = (
                f"two ROPs share this layer path: {', '.join(others)} also writes it{where}; "
                "re-render that ROP to restore its samples"
                if others
                else "an earlier render wrote it; re-render that one to restore its samples"
            )
            overwrites.append(
                f"Overwrote {name}, which had {_samples_text(old)}, with {_samples_text(row)}; "
                f"{why}."
            )
        elif others:
            warnings.append(
                f"{', '.join(others)} also writes {name}{where}: rendering either ROP replaces "
                "the other's time samples in it."
            )
    return overwrites + warnings


def rop_camera_parm(rop: Any) -> str | None:
    """The parm naming the camera ``rop`` renders through: ``override_camera`` (a prim) on
    a USD render ROP, ``cameraprim`` on a viewport ROP reading a stage, else ``camera`` (an
    OBJ camera); None when it has none. Main thread."""
    if is_usd_render_rop(rop):
        return "override_camera" if rop.parm("override_camera") is not None else None
    source = rop.parm("opsource")
    if source is not None and rop.parm("cameraprim") is not None:
        with contextlib.suppress(Exception):
            if source.eval() == 1:
                return "cameraprim"
    return "camera" if rop.parm("camera") is not None else None


def _looks_like_prim(lop: Any, path: str) -> bool:
    """Whether ``path``, which names no node, is a prim: one on ``lop``'s stage, or (no
    LOP to look in) a path whose parent is not a node either (``/cameras/cam``, not
    ``/obj/nope``). Main thread."""
    import hou

    if lop is not None:
        with contextlib.suppress(Exception):
            from .usd import cooked_stage

            return bool(cooked_stage(lop).GetPrimAtPath(path))
        return False
    parent = path.rstrip("/").rsplit("/", 1)[0] or "/"
    return parent != "/" and hou.node(parent) is None


def _check_camera_source(rop: Any, name: str, override: str) -> None:
    """Refuse a ``camera`` override that does not fit a viewport ROP's ``opsource`` (review
    24 N4: a camera prim on a Flipbook ROP reading /obj failed with "No node at
    /cameras/cam" and a hint about /cameras, and finding ``opsource`` took two calls): a
    prim path or LOP camera while it reads /obj, an OBJ camera while it reads a stage. The
    error names ``opsource`` and the value to set. Main thread."""
    import hou

    source = rop.parm("opsource")
    if source is None or rop.parm("cameraprim") is None or not override.startswith("/"):
        return
    node = hou.node(override)
    loppath = rop.parm("loppath")
    lop_value = loppath.eval().strip() if loppath is not None else ""
    lop = rop.node(lop_value) if lop_value else None
    if name == "camera":
        prim = override
        if node is not None:
            if not _is_lop_camera(node):
                return
            prim = node.parm("primpath").eval()
        elif not _looks_like_prim(lop, override):
            return  # a missing node: node_not_found, with the scene's cameras
        where = f" from {lop.path()}" if lop is not None else ""
        then = (
            f"then render with camera {prim}"
            if lop is not None
            else "set loppath to the LOP whose stage has it, then render with camera " + prim
        )
        what = (
            f"{override} is a LOP camera (prim {prim})"
            if node is not None
            else f"{override} is not a node"
        )
        raise ToolError(
            "invalid_argument",
            f"{rop.path()} reads /obj (opsource: obj), and {what}; set opsource to lop to "
            f"render the camera prim {prim}{where}.",
            hint=f"{_set_call(rop.path(), 'opsource', 'lop')}, {then}; or pass an OBJ camera.",
        )
    if name == "cameraprim" and node is not None and _is_obj_camera(node):
        raise ToolError(
            "invalid_argument",
            f"{rop.path()} reads a stage (opsource: lop), and {override} is an OBJ camera; set "
            "opsource to obj to render through it.",
            hint=f"{_set_call(rop.path(), 'opsource', 'obj')}, then "
            f"render with camera {override}; or pass a camera prim path.",
        )


def _set_call(node: str, parm: str, value: str) -> str:
    """The parm change a hint asks for: an ``edit`` ``set`` op."""
    return hint_tool("parm_set", path=f"{node}/{parm}", value=value) or ""


def rop_camera(rop: Any, override: Any) -> dict[str, str]:
    """The temporary camera parm value for ``render``'s ``camera`` override, checked
    (``{}`` without one). Without an override, a ROP whose ``camera`` parm names a node
    that does not exist fails here with ``node_not_found``, naming the parm and listing the
    scene's OBJ cameras (review 21 papercut 5: the render said only "No camera specified
    for render."). Main thread."""
    name = rop_camera_parm(rop)
    if override is not None:
        if not isinstance(override, str) or not override.strip():
            raise ToolError("invalid_argument", "'camera' must be a camera node or prim path.")
        override = override.strip()
        if name is None:
            raise ToolError(
                "invalid_argument",
                f"{rop.path()} ({rop.type().name()}) has no camera parm to override.",
                hint="Render without camera; this ROP does not render through a camera.",
            )
        _check_camera_source(rop, name, override)
        if name == "camera":
            return {name: _obj_camera(override).path()}
        if not override.startswith("/"):
            raise ToolError(
                "invalid_argument",
                f"{rop.path()} renders a stage: camera must be a camera prim path such as "
                "/cameras/cam1.",
            )
        return {name: override}
    if name != "camera":
        return {}
    value = rop.parm("camera").eval().strip()
    if value and rop.node(value) is not None:
        return {}
    cameras = [c for c in scene_cameras() if c.startswith("/obj/")]
    what = f"points at {value}, which does not exist" if value else "is empty"
    hint = (
        f"Cameras here: {', '.join(cameras)}. Set the ROP's camera parm to one, or pass camera."
        if cameras
        else hint_join(
            f"Create a camera ({hint_tool('node_create', parent='/obj', type='cam')}) and set "
            "the ROP's camera parm, or pass camera;",
            hint_tool("look"),
            "frames the scene without one.",
        )
    )
    raise ToolError(
        "node_not_found",
        f"{rop.path()}'s camera parm {what}.",
        hint=hint,
        candidates=cameras,
    )


def _not_a_render_node(node: Any) -> ToolError:
    if is_cop_node(node) or is_cop_network(node):
        return ToolError(
            "invalid_argument",
            f"{node.path()} ({node.type().name()}) is not a render node.",
            hint=cop_hint(node),
            candidates=cop_rop_candidates(node),
        )
    return ToolError(
        "invalid_argument",
        f"{node.path()} ({node.type().name()}) is not a render node.",
        hint="Pass a ROP such as /out/karma1 or /out/flipbook1, or a writer SOP such as a "
        "File Cache or rop_geometry.",
    )


def job_snapshot(job: Any) -> dict[str, Any]:
    """The job's status as ``job status`` would show it, best effort (``{}`` when the
    job context does not expose it). No ``hou``."""
    inner = getattr(job, "_job", None)
    with contextlib.suppress(Exception):
        if inner is not None:
            return dict(inner.status())
    return {}


def cancelled_with_partial(job: Any, partial: dict[str, Any], done: str) -> ToolError:
    """The ``cancelled`` error a job raises when it stops early, with ``detail:
    {last_status, partial}`` so ``job result`` keeps what was done before the cancel
    (review 17 P1-6). No ``hou``."""
    status = job_snapshot(job)
    if status:
        status["state"] = "cancelled"  # the snapshot was taken while it ran (review 20 N7)
    job_id = status.get("job_id")
    name = f"Job {job_id}" if job_id else "The job"
    return ToolError(
        "cancelled",
        f"{name} was cancelled after {done}.",
        detail={"last_status": status, "partial": partial},
    )


def _render_partial(plan: dict[str, Any]) -> tuple[dict[str, Any], str]:
    outputs = [p for p in plan["expected"] if os.path.isfile(p)]
    missing = [p for p in plan["expected"] if not os.path.isfile(p)]
    total = len(plan["expected"]) or len(plan["frame_list"])
    return {"outputs_summary": outputs_summary(outputs, missing)}, (
        f"{len(outputs)} of {total} output files"
    )


SAVE_SIDE_EFFECTS = ("hardenBaseName", "enableLoadFromDisk")
"""What a File Cache's Save to Disk does after its ROP rendered (its PythonModule's
``saveToDisk``): harden the base name, turn on Load from Disk."""


def _writer_side_effects(owner_path: str) -> dict[str, list[Any]]:
    """After a writer SOP rendered through its inner ROP, do what its own save button
    does next (a File Cache turns on Load from Disk and reloads) as one undo step, and
    return the parms that changed. Main thread."""
    import hou

    from ..undo import hou_undo_group, make_label

    node = hou.node(owner_path)
    if node is None:
        return {}
    before = _top_parm_values(node)
    try:
        module = node.hdaModule()
    except Exception:
        return {}
    steps = [getattr(module, name, None) for name in SAVE_SIDE_EFFECTS]
    if not any(callable(step) for step in steps):
        return {}
    with hou_undo_group(make_label("render", {"rop_path": owner_path})):
        for step in steps:
            if callable(step):
                with contextlib.suppress(Exception):
                    step(node)
        reload = node.parm("reload")
        if reload is not None:
            with contextlib.suppress(Exception):
                reload.pressButton()
    return changed_parms(before, _top_parm_values(node))


def _writer_output_hint(owner: Any) -> str:
    """How to change the output of a writer SOP that renders through its inner ROP, in
    ``parm_set`` terms: a File Cache's ``filemethod`` by its menu token (review 20 N4: the
    hint said ``filemethod 1``, an index ``parm_set`` does not take)."""
    method, file_parm = owner.parm("filemethod"), owner.parm("file")
    explicit = None
    with contextlib.suppress(Exception):
        if method is not None and "explicit" in method.menuItems():
            explicit = "explicit"
    if explicit and file_parm is not None:
        method_set = hint_tool("parm_set", path=f"{owner.path()}/filemethod", value=explicit)
        return (
            f"Set the output with {method_set}, then file to the path; then render without output."
        )
    return (
        f"Set the node's own output parm ({hint_tool('parm_set', path=BARE, value=BARE)}), "
        "then render without output."
    )


def _prepare_render(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Validate on the main thread and compute the expected output files."""
    import hou

    rop_path = args.get("rop_path")
    if not isinstance(rop_path, str) or not rop_path.strip():
        raise ToolError("invalid_argument", "'rop_path' must be a ROP node path.")
    owner = require_node(rop_path, field="rop_path")
    rop = owner if callable(getattr(owner, "render", None)) else writer_rop(owner)
    if rop is None:
        raise _not_a_render_node(owner)
    # Without frames every ROP renders its own Valid Frame Range, as writer SOPs did since
    # review 17 P1-3 (review 23 P1-2), or the current frame when it is set to that; a File
    # Cache renders through the ROP inside it.
    frames = _frames(args.get("frames"))
    range_note = None
    if frames is None:
        frames, range_note = default_frames(rop, owner.path())
    output = args.get("output")
    parm = _output_parm(rop)
    usd = is_usd_render_rop(rop)
    if output is not None:
        if not isinstance(output, str) or not output.strip():
            raise ToolError("invalid_argument", "'output' must be a non-empty path.")
        if rop is not owner:
            raise ToolError(
                "invalid_argument",
                f"{owner.path()} ({owner.type().name()}) writes through the ROP inside it, "
                "whose output cannot be overridden.",
                hint=_writer_output_hint(owner),
            )
        if parm is None:
            raise ToolError(
                "invalid_argument",
                f"{rop.path()} ({rop.type().name()}) has no output parm to override.",
                hint=f"Set the ROP's output parm ({hint_tool('parm_set', path=BARE, value=BARE)}), "
                "then render without output.",
            )
        output = output.strip()
        check_allowed(resolve_path(output), ctx)
    expected: list[str] = []
    note = None
    if output is None and usd and not parm.evalAtFrame(frames[0]).strip():
        expected, note = usd_render_outputs(rop, _frame_list(frames))
    else:
        for f in _frame_list(frames):
            if output is not None:
                expected.append(hou.text.expandStringAtFrame(output, f))
            elif parm is not None:
                expected.append(parm.evalAtFrame(f))
    # Every file the render will write, not only an override (one check per directory).
    checked: set[str] = set()
    for path in expected:
        if not path.strip() or path.strip() in MPLAY_OUTPUTS:
            continue
        full = _norm(path)
        folder = os.path.dirname(full)
        if folder not in checked:
            checked.add(folder)
            check_allowed(full, ctx)
    if parm is not None and any(p.strip() in MPLAY_OUTPUTS for p in expected):
        raise ToolError(
            "invalid_value",
            f"{rop.path()} renders to MPlay ({parm.name()} = {expected[0]!r}), which needs a GUI.",
            hint="Pass output with a file path such as $HIP/render/$OS.$F4.png.",
        )
    camera_parms = rop_camera(rop, args.get("camera"))
    camera_note = None
    if camera_parms and args.get("camera") is not None:
        parm_name, value = next(iter(camera_parms.items()))
        camera_note = f"Rendered through {value} ({parm_name} restored)."
    # One file for the whole range (a USD layer, an Alembic archive, any path without $F):
    # one render() call writes every frame; frame by frame each call overwrote the file
    # (review 23 P0-1).
    distinct = {_norm(p) for p in expected if p.strip()}
    single_file = len(_frame_list(frames)) > 1 and len(distinct) == 1
    readback = len(distinct) == 1 and single_file_kind(next(iter(distinct))) is not None
    layer_watch = None
    if readback and single_file_kind(next(iter(distinct))) == "usd":
        # What the layer files hold now, and which other ROPs write them (review 24 N1).
        root = next(iter(distinct))
        saves = usd_save_paths(rop)
        layer_watch = {
            "before": layer_snapshot([root, *saves]),
            "shared": shared_layer_writers(rop, root, saves),
            "saves": saves,
        }
    return {
        "rop": rop.path(),
        "owner": owner.path() if rop is not owner else None,
        "type": rop.type().name(),
        "core_type": rop_core_type(rop),
        "frames": frames,
        "frame_list": _frame_list(frames),
        "parm": parm.name() if parm is not None else None,
        "image_rop": usd or (parm is not None and parm.name() in IMAGE_PARMS),
        "output": output,
        "camera_note": camera_note,
        "camera_parms": camera_parms,
        # One file per path: a single-file ROP's 48 frames are one output (review 23 P1-3).
        "expected": list(dict.fromkeys(_norm(p) for p in expected)),
        "usd": usd,
        "single_file": single_file,
        "readback": readback,
        "layer_watch": layer_watch,
        "note": note,
        "range_note": range_note,
        "isolate": needs_isolation(rop, ctx),
        "stage_source": rop.parm("opsource") is not None and rop.parm("opsource").eval() == 1,
        "hfs": hou.text.expandString("$HFS"),
        # A COP image needs no lights (review 18 papercut 7).
        "lights": (parm is not None and parm.name() == "copoutput") or scene_has_lights(),
    }


def outputs_listing(outputs: list[str], missing: list[str]) -> dict[str, Any]:
    """``outputs`` when there are at most :data:`INLINE_OUTPUTS`, else ``outputs_summary``
    plus ``outputs_sample`` (the first and last :data:`OUTPUTS_SAMPLE_ENDS`); ``missing``
    up to :data:`MISSING_LISTED`. A 48-frame render's ``job result`` was 8 KB of paths
    (review 20 N5). The summary has no ``first`` and ``last`` here: the sample starts and
    ends with them (2.1, D67). No ``hou``."""
    out: dict[str, Any] = {}
    if len(outputs) > INLINE_OUTPUTS:
        summary = outputs_summary(outputs, missing)
        summary.pop("first", None)
        summary.pop("last", None)
        out["outputs_summary"] = summary
        out["outputs_sample"] = outputs[:OUTPUTS_SAMPLE_ENDS] + outputs[-OUTPUTS_SAMPLE_ENDS:]
    else:
        out["outputs"] = outputs
    if missing:
        out["missing"] = missing[:MISSING_LISTED]
    return out


def thumbnail_note(mean_luma: float | None, coverage: float | None) -> str | None:
    """The note on how a render thumbnail looks, from :func:`encode_png`'s ``measure``:
    a fully transparent image is empty; an opaque or mostly opaque one whose flattened
    mean is under :data:`DARK_MEAN` is nearly black. A sparse subject on a transparent
    background is neither (review 20 N1). No ``hou``."""
    if coverage is not None and coverage <= 0.0:
        return (
            "The thumbnail is empty (every pixel is transparent): check camera framing and "
            "which objects are displayed."
        )
    if mean_luma is not None and mean_luma < DARK_MEAN:
        return (
            f"The thumbnail is nearly black (mean luminance {mean_luma:.1f}/255): check "
            "lights, camera framing and exposure."
        )
    return None


def _render_result(plan: dict[str, Any], thumbnail: bool) -> dict[str, Any]:
    outputs = [p for p in plan["expected"] if os.path.isfile(p)]
    missing = [p for p in plan["expected"] if not os.path.isfile(p)]
    result: dict[str, Any] = {
        "rop_path": plan.get("owner") or plan["rop"],
        "frames": [frame_num(v) for v in plan["frames"]],
    }
    result.update(outputs_listing(outputs, missing))
    notes: list[str] = []
    if plan.get("owner"):
        notes.append(f"{plan['owner']} rendered through its ROP {plan['rop']}.")
    if plan.get("range_note"):
        notes.append(plan["range_note"])
    if plan.get("camera_note") and outputs:
        notes.append(plan["camera_note"])
    images = [
        p for p in plan["expected"] if os.path.splitext(p)[1].lower() in IMAGE_EXTS | CONVERT_EXTS
    ]
    if images and not plan.get("lights", True):
        notes.append(NO_LIGHTS_NOTE)
    if plan.get("note") and not outputs:
        notes.append(plan["note"])
    if notes:
        result["notes"] = notes
    if thumbnail and outputs:
        last = outputs[-1]
        ext = os.path.splitext(last)[1].lower()
        if ext not in IMAGE_EXTS | CONVERT_EXTS and plan.get("image_rop"):
            # Review 16 N4: say why there is no thumbnail.
            notes.append(
                f"No thumbnail: {ext or 'a file without an extension'} is not an image "
                "format the thumbnail reads (" + ", ".join(sorted(IMAGE_EXTS | CONVERT_EXTS)) + ")."
            )
            result["notes"] = notes
        elif ext in IMAGE_EXTS or ext in CONVERT_EXTS:
            try:
                image = encode_png(last, THUMB_MAX_SIDE, hfs=plan["hfs"], measure=True)
                look = thumbnail_note(image.pop("mean_luma", None), image.pop("coverage", None))
                if look:
                    notes.append(look)
                    result["notes"] = notes
                result["thumbnail"] = {
                    "path": last,
                    "width": image["width"],
                    "height": image["height"],
                    "image": image,
                }
            except Exception as exc:  # a thumbnail is a nicety; never fail the render
                reason = exc.message if isinstance(exc, ToolError) else f"{type(exc).__name__}"
                notes.append(
                    f"No thumbnail: {os.path.basename(last)} could not be read ({reason})."
                )
                result["notes"] = notes
    return result


def _render_job(plan: dict[str, Any], ctx: HostContext, thumbnail: bool) -> Any:
    import hou

    frame_list = plan["frame_list"]

    def run_isolated(job: Any) -> dict[str, Any]:
        tmp_dir = tempfile.mkdtemp(prefix="hp-render-")
        try:
            snapshot = job.run_main(lambda: snapshot_scene(tmp_dir))
            parms = {plan["parm"]: plan["output"]} if plan["output"] is not None else {}
            parms.update(plan.get("camera_parms") or {})
            child = ChildRender(
                snapshot,
                tmp_dir,
                plan["rop"],
                plan["frames"],
                parms,
                # An OpenGL ROP on a stage (review 16 N1); the Flipbook ROP keeps its threads.
                single_thread=plan.get("stage_source", False) and plan["core_type"] == "opengl",
            )
            child.start()

            def poll() -> None:
                done = sum(1 for p in plan["expected"] if os.path.isfile(p))
                if plan["expected"]:
                    total = len(plan["expected"])
                    job.set_progress(done, total, f"{done}/{total} frames done")

            job.progress(0.0, f"rendering {len(frame_list)} frame(s) in a child hython")
            try:
                outcome = child.wait(
                    timeout_s=FRAME_TIMEOUT_S, cancelled=lambda: job.cancelled, on_poll=poll
                )
            except ToolError as exc:
                if exc.code != "cancelled":
                    raise
                partial, done = _render_partial(plan)
                raise cancelled_with_partial(job, partial, done) from exc
            finally:
                child.kill()
            if outcome.get("errors"):
                message, detail = failure(f"{plan['rop']} failed to render", outcome["errors"])
                warnings = error_lines(outcome.get("warnings") or [])
                if warnings:
                    detail["warnings"] = warnings
                raise ToolError("cook_failed", message, detail=detail or None)
            job.progress(1.0, "done")
            result = _render_result(plan, thumbnail)
            if outcome.get("notes"):
                result["notes"] = [*outcome["notes"], *result.get("notes", [])]
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_in_process(job: Any) -> dict[str, Any]:
        saved: dict[str, tuple[Any, Any]] = {}
        notes: list[str] = []
        side_effects: dict[str, list[Any]] = {}
        logs: list[str] = []
        log_dir: list[str] = []

        def temporary_parms(node: Any) -> dict[str, Any]:
            """The camera and output overrides and, on USD render ROPs, husk logs to read on
            failure."""
            parms: dict[str, Any] = dict(plan.get("camera_parms") or {})
            if plan["output"] is not None:
                parms[plan["parm"]] = plan["output"]
            names = ("husk_log", "husk_stdout", "husk_stderr")
            if plan.get("usd") and all(node.parm(n) is not None for n in names):
                if node.parm("husk_log").eval():
                    logs.extend(node.parm(n).eval() for n in names[1:])
                else:
                    log_dir.append(tempfile.mkdtemp(prefix="hp-husk-"))
                    out, err = (_norm(os.path.join(log_dir[0], f)) for f in ("out.log", "err.log"))
                    parms.update(husk_log=1, husk_stdout=out, husk_stderr=err)
                    logs.extend((err, out))
            return parms

        def apply_override() -> None:
            from .events import muted

            node = hou.node(plan["rop"])
            with hou.undos.disabler(), muted():
                for name, value in temporary_parms(node).items():
                    parm = node.parm(name)
                    string = parm.parmTemplate().type() == hou.parmTemplateType.String
                    keys = parm.keyframes()
                    saved[name] = (parm.unexpandedString() if string else parm.eval(), keys)
                    if keys:
                        parm.deleteAllKeyframes()
                    parm.set(value)

        def restore() -> None:
            from .events import muted

            node = hou.node(plan["rop"])
            if node is None:
                return
            with hou.undos.disabler(), muted():
                for name, (raw, keys) in saved.items():
                    parm = node.parm(name)
                    parm.set(raw)
                    if keys:
                        parm.setKeyframes(keys)

        def render_frame(frame: float) -> list[str]:
            node = hou.node(plan["rop"])
            if node is None:
                return [f"{plan['rop']} was deleted during the render."]
            errors: list[str] = []
            try:
                node.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in node.errors()]
            return errors

        def render_range(on_frame: Any) -> list[str]:
            """One render() call over the whole range, ``on_frame`` after each frame."""
            node = hou.node(plan["rop"])
            if node is None:
                return [f"{plan['rop']} was deleted during the render."]

            def event(_node: Any, kind: Any, _time: float) -> None:
                if kind == hou.ropRenderEventType.PostFrame:
                    with contextlib.suppress(Exception):
                        on_frame()

            errors: list[str] = []
            hooked = False
            with contextlib.suppress(Exception):
                node.addRenderEventCallback(event)
                hooked = True
            try:
                start, end, inc = plan["frames"]
                node.render(frame_range=(start, end, inc), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            finally:
                if hooked:
                    with contextlib.suppress(Exception):
                        node.removeRenderEventCallback(event)
            errors += [str(e) for e in node.errors()]
            return errors

        def run_single_file(total: int) -> None:
            done = [0]
            name = os.path.basename(plan["expected"][0])

            def on_frame() -> None:
                done[0] = min(total, done[0] + 1)
                job.set_progress(done[0], total, f"{done[0]}/{total} frames written to {name}")

            job.set_progress(0, total, f"0/{total} frames written to {name} (one render call)")
            try:
                errors = job.run_main(lambda: render_range(on_frame), timeout_s=FRAME_TIMEOUT_S)
            except ToolError as exc:
                if exc.code != "cancelled":
                    raise
                partial, written = _render_partial(plan)
                raise cancelled_with_partial(job, partial, written) from exc
            if errors:
                message, detail = failure(f"{plan['rop']} failed to render", errors)
                raise ToolError("cook_failed", message, detail=detail or None)

        readback: dict[str, Any] = {}
        started = time.time()
        try:
            job.run_main(apply_override)
            total = len(frame_list)
            if plan.get("single_file"):
                run_single_file(total)
            for i, frame in enumerate([] if plan.get("single_file") else frame_list):
                # The count is current, the frames finished (review 20 N7).
                job.set_progress(
                    i, total, f"{i}/{total} frames done, rendering frame {frame_num(frame)}"
                )
                try:
                    errors = job.run_main(
                        lambda f=frame: render_frame(f), timeout_s=FRAME_TIMEOUT_S
                    )
                except ToolError as exc:
                    if exc.code != "cancelled":
                        raise
                    partial, done = _render_partial(plan)
                    raise cancelled_with_partial(job, partial, done) from exc
                if errors:
                    message, detail = failure(
                        f"{plan['rop']} failed to render frame {frame_num(frame)}", errors
                    )
                    detail["frame"] = frame_num(frame)
                    hint = None
                    tail = log_tail(logs)
                    if tail:
                        detail["log_tail"] = tail
                        hint = "husk failed; detail.log_tail has the end of its log."
                    raise ToolError(
                        "cook_failed",
                        message,
                        hint=hint,
                        detail=detail,
                    )
            if plan.get("readback"):
                # A single-file range render cannot stop mid-range, so a cancel sent during
                # it is too late: the file is complete and is read back (no cancel check).
                readback.update(
                    ctx.executor.run(
                        lambda: check_single_file(
                            plan.get("owner") or plan["rop"],
                            plan["expected"][0],
                            frame_list,
                            started,
                        ),
                        ctx.config.default_timeout_s,
                    )
                )
            job.set_progress(total, total, "done")
            if plan.get("owner"):
                effects = job.run_main(lambda: _writer_side_effects(plan["owner"]))
                if effects:
                    side_effects.update(effects)
                    ctx.scene.mark_dirty()
        finally:
            if saved:
                # Never raises: a render error stays the error the caller sees.
                note = run_with_fallback(ctx.executor, restore, 60.0)
                if note:
                    names = ", ".join(saved)
                    notes.append(f"Restoring {plan['rop']} {names} failed: {note}.")
            for folder in log_dir:
                shutil.rmtree(folder, ignore_errors=True)
        result = _render_result(plan, thumbnail)
        watch = plan.get("layer_watch")
        if readback.get("layers") and watch:
            # First, so an overwritten layer is the first thing read (review 24 N1).
            notes[:0] = layer_overwrites(
                readback["layers"], watch["before"], watch["shared"], watch["saves"]
            )
        notes.extend(readback.get("notes") or [])
        if readback.get("layers"):
            result["layers"] = readback["layers"]
        if side_effects:
            result["side_effects"] = side_effects
        if notes:
            result["notes"] = [*notes, *result.get("notes", [])]
        return result

    return run_isolated if plan["isolate"] else run_in_process


@tool("render", main_thread=False, scene=False)
def render(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """Runs on the request thread so it can wait for its job; ``hou`` only via the executor."""
    if ctx.config.read_only:
        raise ToolError(
            "read_only",
            "render writes files and changes ROP state, and the host is in read-only mode.",
            hint="Set read_only = false in hocuspocus.toml (or HOCUSPOCUS_READ_ONLY=0) and restart the host.",
        )
    # An explicit wait_s is the caller's own threshold; without one, job_threshold_s
    # decides as for cook and pdg (BIBLE §7).
    wait_s = args.get("wait_s")
    if wait_s is None:
        wait_s = float(ctx.config.job_threshold_s)
    if isinstance(wait_s, bool) or not isinstance(wait_s, int | float) or wait_s < 0:
        raise ToolError("invalid_argument", "'wait_s' must be a number >= 0.")
    thumbnail = args.get("thumbnail", True)
    if not isinstance(thumbnail, bool):
        raise ToolError("invalid_argument", "'thumbnail' must be a boolean.")
    plan = ctx.executor.run(lambda: _prepare_render(args, ctx), ctx.config.default_timeout_s)
    job = ctx.jobs.start("render", _render_job(plan, ctx, thumbnail), label=plan["rop"])
    job.done_event.wait(float(wait_s))
    if job.state == "done":
        result = dict(job.result)
        result["job_id"] = job.id
        result["state"] = "done"
        return result
    if job.state in ("failed", "cancelled") and job.error:
        raise ToolError.from_dict(job.error)
    status = job.status()
    status["hint"] = "Poll with job {action: 'status' | 'result', job_id}."
    return status
