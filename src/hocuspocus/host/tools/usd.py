"""``usd_stage``: read-only traversal of a LOP node's composed USD stage.

See docs/BIBLE.md §4.7. The LOP is cooked (non-forced) first; a failed cook or a missing
stage is ``cook_failed`` with the node's errors. Rows are prims in depth-first order
under ``prim`` (the prim itself first unless it is the pseudo-root), paged by
``limit``/``cursor``. ``prim`` may be a pattern: ``*`` matches within one path segment,
``**`` across segments; matching prims are listed with their subtrees to ``depth``.

Attribute values are authored values only, read at ``time`` (default: current frame;
the LOP is cooked at that frame, which is then restored), arrays summarised as
``{len, first}``. ``depth`` is at most 16, and the walk stops once it has the page plus
one prim, so ``total`` is reported only on the last page. Houdini's bookkeeping prim ``/HoudiniLayerInfo``
is skipped, as in the scene graph tree.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError

from ._common import DEFAULT_LIMIT, bad_arg, get_node, page
from ._diag import a_or_an, collect_problems
from .registry import HostContext, tool

INCLUDE = ("attributes", "xform", "bindings", "layers")
HIDDEN_PRIMS = frozenset({"/HoudiniLayerInfo"})
ATTR_CAP = 64
"""Authored attributes listed per prim before ``attributes_truncated`` is set."""
ARRAY_PREVIEW = 3
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


def _pattern(prim: str) -> re.Pattern[str] | None:
    if "*" not in prim:
        return None
    out = []
    i = 0
    while i < len(prim):
        if prim.startswith("**", i):
            out.append(".*")
            i += 2
        elif prim[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(prim[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


# -- the LOP and its stage -------------------------------------------------------------


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
        raise ToolError(
            "invalid_argument",
            f"{node.path()} is {a_or_an(node.type().category().name())} node, not a LOP.",
            hint="usd_stage reads LOP (Solaris) nodes, e.g. /stage/OUT.",
        )
    return node


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
            hint="Fix the errors (problems tool) and retry.",
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


def _matrix(m: Any) -> Any:
    rows = tuple(tuple(float(x) for x in m.GetRow(i)) for i in range(4))
    if rows == _IDENTITY:
        return "identity"
    return [[_num(x) for x in row] for row in rows]


# -- per-prim blocks --------------------------------------------------------------------


def _attributes(prim: Any, time: Any) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    attrs = [a for a in prim.GetAttributes() if a.HasAuthoredValue()]
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
    return {"local": _matrix(local), "world": _matrix(cache.GetLocalToWorldTransform(prim))}


def _binding(prim: Any) -> str | None:
    from pxr import UsdShade

    if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
        return None
    material, _rel = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def prim_row(prim: Any, include: set[str], time: Any, cache: Any) -> dict[str, Any]:
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
        row["attributes"], truncated = _attributes(prim, time)
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


def layers_block(stage: Any, lop: Any) -> dict[str, Any]:
    stack = [layer.identifier for layer in stage.GetLayerStack(includeSessionLayers=False)]
    block: dict[str, Any] = {"stack": stack[:LAYER_CAP]}
    if len(stack) > LAYER_CAP:
        block["stack_total"] = len(stack)
    try:
        active = lop.activeLayer()
        if active is not None:
            block["active"] = active.identifier
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


@tool("usd_stage")
def usd_stage(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou
    from pxr import Usd, UsdGeom

    include = _include(args)
    depth = _depth(args)
    prim = args.get("prim") or "/"
    if not isinstance(prim, str) or not prim.startswith("/"):
        raise bad_arg("'prim' must be an absolute prim path (or pattern) like /geo.")
    if prim != "/":
        prim = prim.rstrip("/")
    requested = _time(args)
    limit, cursor = args.get("limit"), args.get("cursor")
    page([], limit, cursor)  # validate before cooking
    start = int(cursor) if cursor not in (None, "") else 0
    size = DEFAULT_LIMIT if limit is None else limit
    lop = resolve_lop(args.get("lop_path"))
    with _at_frame(requested):
        frame = float(hou.frame())
        stage = cooked_stage(lop)
        prims = collect_prims(stage, prim, depth, stop=start + size + 1)
        chunk, nxt = page(prims, limit, cursor)
        time = Usd.TimeCode(frame)
        cache = UsdGeom.XformCache(time)
        result: dict[str, Any] = {
            "lop_path": lop.path(),
            "time": _num(frame),
            "prims": [prim_row(p, include, time, cache) for p in chunk],
        }
        if nxt is None:
            result["total"] = len(prims)  # the walk ended: the count is exact
        else:
            result["next_cursor"] = nxt
        if "layers" in include:
            result["layers"] = layers_block(stage, lop)
    return result
