"""``usd_stage``: read-only traversal of a LOP node's composed USD stage.

See docs/BIBLE.md §4.7. The LOP is cooked (non-forced) first; a failed cook or a missing
stage is ``cook_failed`` with the node's errors. Rows are prims in depth-first order
under ``prim`` (the prim itself first unless it is the pseudo-root), paged by
``limit``/``cursor``. ``prim`` may be a pattern: ``*`` matches within one path segment,
``**`` across segments, and ``|`` separates alternatives (each a prim path or glob, as in
``attribs``); matching prims are listed with their subtrees to ``depth``, in stage order.
An alternative that is not a valid ``Sdf.Path`` (with ``*`` read as a name character) is
``invalid_argument``; an exact alternative that names no prim is too.

Attribute values are authored values only, read at ``time`` (default: current frame;
the LOP is cooked at that frame, which is then restored); arrays of up to 4 elements are
listed in full (string and token arrays up to 8), longer ones summarised as
``{len, first}``; ``attribs`` keeps the names
matching a glob. ``depth`` is at most 16. Rows are built for the page only, and the walk
stops once it has the page plus one prim; ``total`` comes from a separate counting walk
(no rows), capped at :data:`COUNT_CAP`. ``summary`` returns counts by type and the world
bounds of the subtree instead of rows. Houdini's bookkeeping prim ``/HoudiniLayerInfo`` is
skipped, as in the scene graph tree.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import re
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

from ._common import DEFAULT_LIMIT, bad_arg, get_node, page
from ._diag import a_or_an, collect_problems
from .registry import HostContext

INCLUDE = ("attributes", "xform", "bindings", "layers")
HIDDEN_PRIMS = frozenset({"/HoudiniLayerInfo"})
ATTR_CAP = 64
"""Authored attributes listed per prim before ``attributes_truncated`` is set."""
ARRAY_PREVIEW = 3
ARRAY_FULL = 4
"""Arrays of at most this many elements are listed in full (an extent, a color)."""
TOKEN_ARRAY_FULL = 8
"""String and token arrays (an xformOpOrder) are listed in full up to this many."""
COUNT_CAP = 100_000
"""``total`` and ``summary`` stop counting here and say ``total_capped``."""
STRING_CAP = 200
LAYER_CAP = 50
_IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


# -- arguments --------------------------------------------------------------------------


def _include(args: dict[str, Any]) -> set[str]:
    value = args.get("include") or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(v not in INCLUDE for v in value):
        raise bad_arg(f"'include' must be a list of {', '.join(INCLUDE)}.")
    return set(value)


def _attribs(args: dict[str, Any]) -> list[str] | None:
    value = args.get("attribs")
    if value is None:
        return None
    if not isinstance(value, str) or not value.replace("|", "").strip():
        raise bad_arg(
            "'attribs' must be a non-empty glob such as inputs:* or focalLength|xformOp*."
        )
    return [part.strip() for part in value.split("|") if part.strip()]


MAX_DEPTH = 16


def _depth(args: dict[str, Any]) -> int:
    depth = args.get("depth", 1)
    if depth is None:
        return 1
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= MAX_DEPTH:
        raise bad_arg(
            f"'depth' must be an integer from 1 to {MAX_DEPTH}.",
            hint="Page deep hierarchies with prim (a subtree or a ** pattern) instead.",
        )
    return depth


def _time(args: dict[str, Any]) -> float | None:
    """The requested time code, or None for the current frame."""
    value = args.get("time")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise bad_arg("'time' must be a number (a USD time code; Houdini frames).")
    return float(value)


PRIM_HINT = (
    "Use absolute prim paths, * within a path segment, ** across segments and | between "
    "alternatives, e.g. /city/bldg_00*|/city/ground."
)


def prim_alternatives(prim: str) -> list[str]:
    """The ``|``-separated alternatives of ``prim``, each checked as an ``Sdf.Path`` (with
    ``*`` read as a name character). Raises ``invalid_argument`` for one that is not an
    absolute prim path (review 16 N3: ``/a*|/b`` used to match nothing, silently)."""
    from pxr import Sdf

    alternatives = []
    for raw in prim.split("|"):
        alt = raw.strip()
        if alt != "/":
            alt = alt.rstrip("/")
        probe = alt.replace("*", "x")
        valid = alt.startswith("/") and Sdf.Path.IsValidPathString(probe)
        if valid and alt != "/":
            path = Sdf.Path(probe)
            valid = path.IsAbsolutePath() and path.IsPrimPath()
        if not valid:
            raise ToolError(
                "invalid_argument",
                f"'prim' {raw.strip()!r} is not a prim path or pattern"
                + (f" (in {prim!r})." if "|" in prim else "."),
                hint=PRIM_HINT,
            )
        alternatives.append(alt)
    return alternatives


def _glob(alt: str) -> str:
    out = []
    i = 0
    while i < len(alt):
        if alt.startswith("**", i):
            out.append(".*")
            i += 2
        elif alt[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(alt[i]))
            i += 1
    return "".join(out) + r"\Z"


def _pattern(prim: str) -> re.Pattern[str] | None:
    """None for one exact prim path; else a regex matching any alternative."""
    if "*" not in prim and "|" not in prim:
        return None
    return re.compile("|".join(f"(?:{_glob(alt)})" for alt in prim_alternatives(prim)))


def _check_exact(stage: Any, prim: str) -> None:
    """An exact alternative of a ``|`` pattern must name a prim, as a lone path must."""
    for alt in prim_alternatives(prim):
        if "*" not in alt and alt != "/" and not stage.GetPrimAtPath(alt):
            raise _missing_prim(stage, alt)


# -- the LOP and its stage -------------------------------------------------------------


def usd_parm_name(node: Any, name: str) -> str | None:
    """Houdini's parm name for a USD attribute name on a LOP node (``inputs:intensity`` ->
    ``xn__inputsintensity_i0a``, via ``hou.text.encodeParm``), or None when the node is not
    a LOP or the name needs no encoding (review 13 papercut 7)."""
    import hou

    try:
        if node.type().category() != hou.lopNodeTypeCategory():
            return None
        encoded = hou.text.encodeParm(name)
    except Exception:
        return None
    return encoded if encoded and encoded != name else None


def resolve_lop(path: Any) -> Any:
    """The LOP node at ``path``; a LOP network resolves to its display node."""
    import hou

    node = get_node(path, field="lop_path")
    if isinstance(node, hou.LopNetwork) or (
        not isinstance(node, hou.LopNode) and node.childTypeCategory() == hou.lopNodeTypeCategory()
    ):
        display = node.displayNode() if hasattr(node, "displayNode") else None
        if display is None:
            raise ToolError(
                "invalid_argument",
                f"{node.path()} is a LOP network with no display node.",
                hint="Pass a LOP node path, or set a display flag inside the network.",
            )
        node = display
    if not isinstance(node, hou.LopNode):
        if node.type().category() == hou.lopNodeTypeCategory():
            # A ROP inside a LOP network (usdrender_rop): it renders a stage, has none.
            sources = [n.path() for n in node.inputs() if n is not None]
            where = f"; read its input {sources[0]}" if sources else ", and no input"
            raise ToolError(
                "invalid_argument",
                f"{node.path()} ({node.type().name()}) has no output stage{where}.",
                hint=(f"Pass lop_path {sources[0]}." if sources else "Pass the LOP it renders."),
                candidates=sources[:1],
            )
        raise ToolError(
            "invalid_argument",
            f"{node.path()} is {a_or_an(node.type().category().name())} node, not a LOP.",
            hint=f"{hint_tool('usd_stage', lop_path='/stage/OUT')} reads LOP (Solaris) nodes.",
        )
    return node


def rop_stage_source(lop_path: Any) -> tuple[Any, str | None]:
    """For a ROP inside a LOP network (``usd_rop``, ``usdrender_rop``), which has no stage
    of its own, the LOP it renders (its ``loppath``, else its first input) and a note;
    anything else unchanged. A ROP with neither is left to :func:`resolve_lop`'s error
    (review 23 papercut 10)."""
    import hou

    if not isinstance(lop_path, str) or not lop_path.strip().startswith("/"):
        return lop_path, None
    node = hou.node(lop_path.strip())
    if (
        node is None
        or isinstance(node, hou.LopNode)
        or not isinstance(node, hou.RopNode)
        or node.type().category() != hou.lopNodeTypeCategory()
    ):
        return lop_path, None
    source = None
    with contextlib.suppress(Exception):
        text = node.parm("loppath").eval() if node.parm("loppath") is not None else ""
        source = node.node(text) if text else None
    if not isinstance(source, hou.LopNode):
        inputs = [n for n in node.inputs() if n is not None]
        source = inputs[0] if inputs and isinstance(inputs[0], hou.LopNode) else None
    if source is None:
        return lop_path, None
    return source.path(), (
        f"Read {source.path()}, the stage {node.path()} renders: a ROP has no stage of its own."
    )


def cooked_stage(lop: Any) -> Any:
    report = collect_problems(lop, cook=True)
    stage = None
    if report["cook_state"] != "error":
        try:
            stage = lop.stage()
        except Exception as exc:  # pragma: no cover - defensive
            report["errors"].append(f"{type(exc).__name__}: {exc}")
    if stage is None:
        errors = report["errors"] or ["The LOP produced no stage."]
        raise ToolError(
            "cook_failed",
            f"{lop.path()} failed to cook: {errors[0].splitlines()[0] if errors[0] else ''}",
            hint=f"Fix the errors ({hint_tool('problems', root=lop.path())} lists them) and retry.",
            detail={"path": lop.path(), "errors": errors, "warnings": report["warnings"]},
        )
    return stage


# -- value serialisation ----------------------------------------------------------------


def _num(value: float) -> float | int:
    rounded = float(f"{value:.7g}")
    return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded


def jsonable(value: Any, *, top: bool = True) -> Any:
    """A compact JSON-able form of a USD value (arrays summarised at the top level)."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return _num(value)
    if isinstance(value, str):
        return value if len(value) <= STRING_CAP else value[:STRING_CAP] + "…"
    name = type(value).__name__
    if name.endswith("Array") or isinstance(value, list | tuple):
        if not top:
            return str(value)[:STRING_CAP]
        full = ARRAY_FULL
        if len(value) and isinstance(value[0], str):
            full = TOKEN_ARRAY_FULL
        if len(value) <= full:
            return [jsonable(v, top=False) for v in value]
        items = list(value[:ARRAY_PREVIEW])
        return {"len": len(value), "first": [jsonable(v, top=False) for v in items]}
    if name.startswith("Matrix"):
        rows = value.dimension[0] if hasattr(value, "dimension") else 4
        return [[_num(x) for x in value.GetRow(i)] for i in range(rows)]
    if name.startswith("Quat"):
        return [_num(value.GetReal()), *(_num(x) for x in value.GetImaginary())]
    if name.startswith("Vec"):
        return [_num(x) for x in value]
    if name == "AssetPath":
        return value.path
    if name in ("Path", "TimeCode", "Token"):
        return str(value)
    text = str(value)
    return text if len(text) <= STRING_CAP else text[:STRING_CAP] + "…"


def stage_bbox(stage: Any, prims: list[Any], frame: float) -> dict[str, Any] | None:
    """World-space bounds of ``prims`` (default and render purposes, extents hints used)
    as ``{min, max, size}``, or None when nothing has extent."""
    from pxr import Gf, Usd, UsdGeom

    cache = UsdGeom.BBoxCache(
        Usd.TimeCode(frame), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render], True
    )
    total = Gf.Range3d()
    for prim in prims:
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not box.IsEmpty():
            total = Gf.Range3d.GetUnion(total, box)
    if total.IsEmpty():
        return None
    lo, hi = total.GetMin(), total.GetMax()
    return {
        "min": [_num(x) for x in lo],
        "max": [_num(x) for x in hi],
        "size": [_num(hi[i] - lo[i]) for i in range(3)],
    }


def _matrix(m: Any) -> Any:
    rows = tuple(tuple(float(x) for x in m.GetRow(i)) for i in range(4))
    if rows == _IDENTITY:
        return "identity"
    return [[_num(x) for x in row] for row in rows]


# -- per-prim blocks --------------------------------------------------------------------


def _attributes(
    prim: Any, time: Any, patterns: list[str] | None = None
) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    attrs = [
        a
        for a in prim.GetAttributes()
        if a.HasAuthoredValue()
        and (patterns is None or any(fnmatch.fnmatchcase(a.GetName(), p) for p in patterns))
    ]
    for attr in attrs[:ATTR_CAP]:
        row: dict[str, Any] = {"name": attr.GetName(), "type": str(attr.GetTypeName())}
        try:
            row["value"] = jsonable(attr.Get(time))
        except Exception as exc:  # pragma: no cover - exotic value types
            row["value"] = None
            row["error"] = f"{type(exc).__name__}: {exc}"
        samples = attr.GetNumTimeSamples()
        if samples:
            row["time_samples"] = samples
        rows.append(row)
    return rows, len(attrs) > ATTR_CAP


def _xform(prim: Any, time: Any, cache: Any) -> dict[str, Any] | None:
    from pxr import UsdGeom

    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return None
    local = xformable.GetLocalTransformation(time)
    if isinstance(local, tuple):  # older signature returned (matrix, resetsXformStack)
        local = local[0]
    block = {"local": _matrix(local)}
    world = _matrix(cache.GetLocalToWorldTransform(prim))
    if world != block["local"]:
        block["world"] = world  # left out when the parents add nothing
    return block


def _binding(prim: Any) -> str | None:
    from pxr import UsdShade

    if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
        return None
    material, _rel = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def prim_row(
    prim: Any, include: set[str], time: Any, cache: Any, attribs: list[str] | None = None
) -> dict[str, Any]:
    from pxr import Usd, UsdGeom

    row: dict[str, Any] = {"path": str(prim.GetPath()), "type": prim.GetTypeName() or ""}
    kind = Usd.ModelAPI(prim).GetKind()
    if kind:
        row["kind"] = kind
    row["active"] = prim.IsActive()
    imageable = UsdGeom.Imageable(prim)
    if imageable:
        purpose = imageable.GetPurposeAttr().Get()
        if purpose and purpose != "default":
            row["purpose"] = str(purpose)
    row["children_count"] = len(prim.GetAllChildren())
    if "attributes" in include:
        row["attributes"], truncated = _attributes(prim, time, attribs)
        if truncated:
            row["attributes_truncated"] = True
    if "xform" in include:
        xform = _xform(prim, time, cache)
        if xform is not None:
            row["xform"] = xform
    if "bindings" in include:
        material = _binding(prim)
        if material:
            row["material"] = material
    return row


# -- traversal --------------------------------------------------------------------------


def _walk(
    prim: Any, depth: int, out: list[Any], *, include_self: bool, stop: int | None = None
) -> None:
    """Depth-first: ``prim`` (if asked) then descendants up to ``depth`` levels below it.
    Stops once ``out`` holds ``stop`` prims."""
    stack = [(prim, 0)]
    while stack:
        if stop is not None and len(out) >= stop:
            return
        current, level = stack.pop()
        if level > 0 or include_self:
            if str(current.GetPath()) not in HIDDEN_PRIMS:
                out.append(current)
            else:
                continue
        if level < depth:
            stack.extend((child, level + 1) for child in reversed(current.GetAllChildren()))


def _missing_prim(stage: Any, path: str) -> ToolError:
    from pxr import Sdf

    candidates: list[str] = []
    try:
        sdf = Sdf.Path(path)
        parent = sdf.GetParentPath()
        while parent and not stage.GetPrimAtPath(parent):
            parent = parent.GetParentPath()
        anchor = stage.GetPrimAtPath(parent) if parent else stage.GetPseudoRoot()
        import difflib

        names = [c.GetName() for c in anchor.GetAllChildren()]
        close = difflib.get_close_matches(sdf.name, names, n=5, cutoff=0.4) or names[:5]
        base = str(anchor.GetPath()).rstrip("/")
        candidates = [f"{base}/{n}" for n in close]
    except Exception:
        pass
    return ToolError(
        "invalid_argument",
        f"No prim at {path!r} on this stage.",
        hint=(f"Prims that exist near it: {', '.join(candidates)}. " if candidates else "")
        + "List the stage from prim '/' to see what exists.",
        candidates=candidates,
    )


def collect_prims(stage: Any, prim: str, depth: int, stop: int | None = None) -> list[Any]:
    """Prims to list, in order; at most ``stop`` of them (the page plus one, so the caller
    knows whether more exist without walking the whole stage)."""
    pattern = _pattern(prim)
    out: list[Any] = []
    if pattern is None:
        target = stage.GetPseudoRoot() if prim == "/" else stage.GetPrimAtPath(prim)
        if not target:
            raise _missing_prim(stage, prim)
        _walk(target, depth, out, include_self=prim != "/", stop=stop)
        return out
    from pxr import Usd

    _check_exact(stage, prim)
    seen: set[str] = set()
    for candidate in stage.Traverse(Usd.PrimAllPrimsPredicate):
        if stop is not None and len(out) >= stop:
            break
        path = str(candidate.GetPath())
        if path in seen or path in HIDDEN_PRIMS or not pattern.match(path):
            continue
        found: list[Any] = []
        _walk(candidate, depth - 1, found, include_self=True)
        for p in found:
            key = str(p.GetPath())
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out if stop is None else out[:stop]


def _subtree(root: Any, depth: int | None, *, include_self: bool) -> Iterator[Any]:
    """Prims under ``root`` (and ``root`` itself if asked) to ``depth`` levels, in the
    order and with the hidden prims of :func:`_walk`, without building a list."""
    from pxr import Usd

    base = root.GetPath().pathElementCount
    prims = iter(Usd.PrimRange(root, Usd.PrimAllPrimsPredicate))
    for prim in prims:
        level = prim.GetPath().pathElementCount - base
        if str(prim.GetPath()) in HIDDEN_PRIMS:
            prims.PruneChildren()
            continue
        if level > 0 or (include_self and not prim.IsPseudoRoot()):
            yield prim
        if depth is not None and level >= depth:
            prims.PruneChildren()


def count_prims(stage: Any, prim: str, depth: int) -> tuple[int, bool]:
    """How many rows the listing has in all, and whether counting stopped at the cap."""
    if _pattern(prim) is not None:
        found = collect_prims(stage, prim, depth, stop=COUNT_CAP + 1)
        return min(len(found), COUNT_CAP), len(found) > COUNT_CAP
    target = stage.GetPseudoRoot() if prim == "/" else stage.GetPrimAtPath(prim)
    total = 0
    for _ in _subtree(target, depth, include_self=prim != "/"):
        total += 1
        if total > COUNT_CAP:
            return COUNT_CAP, True
    return total, False


def summary_block(stage: Any, prim: str, frame: float) -> dict[str, Any]:
    """``{total_prims, counts_by_type, bbox_world}`` for the whole subtree under ``prim``
    (every match of a pattern), any depth."""
    pattern = _pattern(prim)
    if pattern is None:
        root = stage.GetPseudoRoot() if prim == "/" else stage.GetPrimAtPath(prim)
        if not root:
            raise _missing_prim(stage, prim)
        roots = [root]
    else:
        _check_exact(stage, prim)
        roots = [
            p
            for p in stage.Traverse()
            if pattern.match(str(p.GetPath())) and str(p.GetPath()) not in HIDDEN_PRIMS
        ]
    counts: dict[str, int] = {}
    seen: set[str] = set()
    total = 0
    capped = False
    for root in roots:
        for p in _subtree(root, None, include_self=True):
            key = str(p.GetPath())
            if key in seen:
                continue
            seen.add(key)
            total += 1
            kind = p.GetTypeName() or "(untyped)"
            counts[kind] = counts.get(kind, 0) + 1
            if total >= COUNT_CAP:
                capped = True
                break
        if capped:
            break
    block: dict[str, Any] = {
        "total_prims": total,
        "counts_by_type": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "bbox_world": stage_bbox(stage, roots, frame) if roots else None,
    }
    if capped:
        block["total_capped"] = True
    return block


def _fwd(path: str) -> str:
    """A layer identifier or path with forward slashes, as every path HocusPocus returns
    (review 24 N7: save_path repeated the identifier with backslashes)."""
    return str(path).replace("\\", "/")


def layer_row(layer: Any) -> dict[str, Any]:
    """One layer of the stack (review 23 papercut 4: anonymous ids only, so nothing said
    that ``sopimport`` would save its data to a second file): ``identifier``, plus
    ``save_path`` (where Houdini saves an anonymous LOP layer, from its HoudiniLayerInfo,
    or a file layer's own path when it differs from the identifier), ``owner_node`` (the LOP that created it) and
    ``time_codes`` ([start, end] when the layer authors them)."""
    import hou

    row: dict[str, Any] = {"identifier": _fwd(layer.identifier)}
    info: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        prim = layer.GetPrimAtPath("/HoudiniLayerInfo")
        if prim:
            info = dict(prim.customData)
    save = info.get("HoudiniSavePath")
    if not save and not layer.anonymous:
        save = layer.realPath or None
    # Forward slashes, and no save_path that repeats the identifier (review 24 N7).
    if save and os.path.normcase(_fwd(str(save))) != os.path.normcase(row["identifier"]):
        row["save_path"] = _fwd(str(save))
    # HoudiniCreatorNode can be the SOP a sopimport read; the owner is the first LOP
    # among the creator and the editors.
    ids = [info.get("HoudiniCreatorNode")]
    with contextlib.suppress(Exception):
        ids += [int(i) for i in info.get("HoudiniEditorNodes") or ()]
    nodes = []
    for sid in ids:
        with contextlib.suppress(Exception):
            node = hou.nodeBySessionId(int(sid)) if sid is not None else None
            if node is not None:
                nodes.append(node)
    owner = next((n for n in nodes if isinstance(n, hou.LopNode)), None)
    if owner is not None:
        row["owner_node"] = owner.path()
    with contextlib.suppress(Exception):
        if layer.HasStartTimeCode() or layer.HasEndTimeCode():
            row["time_codes"] = [_num(layer.startTimeCode), _num(layer.endTimeCode)]
    return row


def layers_block(stage: Any, lop: Any) -> dict[str, Any]:
    layers = list(stage.GetLayerStack(includeSessionLayers=False))
    block: dict[str, Any] = {"stack": [layer_row(layer) for layer in layers[:LAYER_CAP]]}
    if len(layers) > LAYER_CAP:
        block["stack_total"] = len(layers)
    try:
        active = lop.activeLayer()
        if active is not None:
            block["active"] = _fwd(active.identifier)
    except Exception:
        pass
    return block


@contextlib.contextmanager
def _at_frame(frame: float | None) -> Iterator[None]:
    """Evaluate at ``frame`` (the LOP cooks there), restoring the current frame."""
    import hou

    previous = hou.frame()
    switch = frame is not None and frame != previous
    if switch:
        hou.setFrame(frame)
    try:
        yield
    finally:
        if switch:
            hou.setFrame(previous)


def usd_stage(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou
    from pxr import Usd, UsdGeom

    include = _include(args)
    attribs = _attribs(args)
    if attribs is not None:
        include.add("attributes")
    depth = _depth(args)
    summary = args.get("summary", False)
    if not isinstance(summary, bool):
        raise bad_arg("'summary' must be a boolean.")
    prim = args.get("prim") or "/"
    if not isinstance(prim, str) or not prim.startswith("/"):
        raise bad_arg("'prim' must be an absolute prim path (or pattern) like /geo.")
    prim = "|".join(prim_alternatives(prim))
    requested = _time(args)
    limit, cursor = args.get("limit"), args.get("cursor")
    page([], limit, cursor)  # validate before cooking
    start = int(cursor) if cursor not in (None, "") else 0
    size = DEFAULT_LIMIT if limit is None else limit
    source, rop_note = rop_stage_source(args.get("lop_path"))
    lop = resolve_lop(source)
    with _at_frame(requested):
        frame = float(hou.frame())
        stage = cooked_stage(lop)
        if summary:
            out = {
                "lop_path": lop.path(),
                "time": _num(frame),
                "prim": prim,
                "summary": summary_block(stage, prim, frame),
            }
            if rop_note:
                out["note"] = rop_note
            return out
        prims = collect_prims(stage, prim, depth, stop=start + size + 1)
        chunk, nxt = page(prims, limit, cursor)
        time = Usd.TimeCode(frame)
        cache = UsdGeom.XformCache(time)
        result: dict[str, Any] = {
            "lop_path": lop.path(),
            "time": _num(frame),
            "prims": [prim_row(p, include, time, cache, attribs) for p in chunk],
        }
        if nxt is None:
            result["total"] = len(prims)  # the walk ended: the count is exact
        else:
            result["total"], capped = count_prims(stage, prim, depth)
            if capped:
                result["total_capped"] = True
            result["next_cursor"] = nxt
        if "layers" in include:
            result["layers"] = layers_block(stage, lop)
        if rop_note:
            result["note"] = rop_note
    return result
