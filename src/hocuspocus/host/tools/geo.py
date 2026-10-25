"""Geometry tools: ``geo_info`` and ``geo_read``. See docs/BIBLE.md §4.6.

Everything is read through intrinsics and bulk accessors (``*AttribValuesAsString`` into
numpy, ``countPrimType``, ``boundingBox``); nothing loops over points in Python. Group
membership is resolved in C++ by running the ``attribcreate`` verb on a copy of the
geometry, so a group (or an ad-hoc pattern such as ``0-99`` or ``@P.y>0``) over a million
elements costs milliseconds.
"""

from __future__ import annotations

import contextlib
import difflib
import itertools
import json
import math
import re
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import BARE, hint_tool

from ._common import int_arg, parse_offset
from ._diag import a_or_an, collect_problems, refresh_stale, require_node
from .readers import stale_file_notes
from .registry import HostContext

CLASSES = ("point", "prim", "vertex", "detail")
LIST_CAP = 60
"""Attributes or groups listed per class in ``geo_info`` before ``truncated`` is set."""
DETAIL_ARRAY_CAP = 16
DETAIL_STRING_CAP = 200
INTRINSIC_SAMPLES = 3
FIELD_ROWS_CAP = 100
"""Volume and VDB primitives listed per ``geo_info`` before ``volume_total`` is set (a pyro
sim has six; review 17 P1-7 found three of six listed)."""
VOLUME_COLUMNS = ["name", "prim", "resolution", "voxel_size", "min", "max"]
VDB_COLUMNS = ["name", "prim", "class", "value_type", "active_voxels", "voxel_size"]
STATS_UNIQUE_CAP = 20
ROWS_BYTE_BUDGET = 12_000
"""geo_read stops adding rows past this many bytes so the result stays under 16 KB and
``next_cursor`` stays exact (the bridge would otherwise cut rows without fixing it)."""

PRIM_TYPE_KEYS = {
    "Poly": "polygon",
    "PolySoup": "polysoup",
    "NURBCurve": "nurbs_curve",
    "BezierCurve": "bezier_curve",
    "Mesh": "mesh",
    "NURBMesh": "nurbs_surface",
    "BezierMesh": "bezier_surface",
    "Part": "particle_system",
    "MetaBall": "metaball",
    "MetaSQuad": "metasquad",
    "TriFan": "trifan",
    "TriStrip": "tristrip",
    "TriBezier": "tribezier",
    "Volume": "volume",
    "VDB": "vdb",
    "Tetrahedron": "tetrahedron",
    "Hexahedron": "hexahedron",
    "PackedGeometry": "packed",
    "PackedDisk": "packed_disk",
    "PackedDiskSequence": "packed_disk_sequence",
    "PackedFragment": "packed_fragment",
    "PackedAgent": "agent",
    "AlembicRef": "alembic",
    "PackedUSD": "packed_usd",
}
_PLAIN_GROUP = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# -- node resolution --------------------------------------------------------------


def resolve_sop(path: Any) -> Any:
    """Return the SOP for ``path``: a SOP itself, or an OBJ's display SOP."""
    import hou

    node = require_node(path)
    if isinstance(node, hou.SopNode):
        return node
    if isinstance(node, hou.ObjNode):
        display = node.displayNode()
        if isinstance(display, hou.SopNode):
            return display
        sops = [c.path() for c in node.children() if isinstance(c, hou.SopNode)][:5]
        raise ToolError(
            "invalid_argument",
            f"{node.path()} ({node.type().name()}) has no display SOP.",
            hint=(
                "Set the display flag on one of its SOPs, or pass a SOP path directly."
                if sops
                else "This object contains no SOPs; pass a SOP path (or a geo object with SOPs)."
            ),
            candidates=sops,
        )
    raise ToolError(
        "invalid_argument",
        f"{node.path()} is {a_or_an(node.type().category().name())} node, not a SOP or OBJ.",
        hint="Pass a SOP path such as /obj/geo1/OUT, or a geometry object such as /obj/geo1.",
    )


def cooked_geometry(sop: Any, frame: Any = None) -> Any:
    """Cook ``sop`` (at ``frame``) and return its geometry, or raise ``cook_failed``."""
    import hou

    if frame is not None and (isinstance(frame, bool) or not isinstance(frame, int | float)):
        raise ToolError("invalid_argument", "'frame' must be a number.")
    # A node fixed outside HocusPocus can keep its old error and fail every downstream
    # cook until it is cooked again (§5.18): refresh before fetching the geometry.
    refresh_stale(sop)
    try:
        geo = sop.geometry() if frame is None else sop.geometryAtFrame(float(frame))
    except hou.OperationFailed as exc:
        problems = collect_problems(sop)
        raise ToolError(
            "cook_failed",
            f"{sop.path()} failed to cook.",
            hint=cook_failed_hint(sop),
            hou_exception=f"hou.OperationFailed: {exc}",
            detail={"path": sop.path(), **problems},
        ) from exc
    errors = [str(e).strip() for e in sop.errors() if str(e).strip()]
    if geo is None or errors:
        problems = collect_problems(sop)
        raise ToolError(
            "cook_failed",
            f"{sop.path()} has cook errors: {errors[0] if errors else 'no geometry'}",
            hint=cook_failed_hint(sop),
            detail={"path": sop.path(), **problems},
        )
    return geo


def cook_failed_hint(node: Any) -> str:
    """``cook_failed``'s hint, naming the problems read the call's profile serves."""
    parent = node.parent()
    root = parent.path() if parent is not None else node.path()
    return (
        f"Fix the errors in detail ({hint_tool('problems', root=root)} also finds upstream "
        "causes), then retry."
    )


# -- value formatting -------------------------------------------------------------


def num(value: Any, digits: int = 7) -> Any:
    """Compact JSON number: ``digits`` significant digits for floats; NaN/inf as strings."""
    if isinstance(value, bool | int):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(f):
        return str(f)
    return float(f"{f:.{digits}g}")


def frame_num(value: Any) -> Any:
    """A frame as JSON and in messages: an int when it is whole (``90``, not ``90.0``;
    review 17 and 20), else :func:`num`."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if isinstance(value, bool) or not math.isfinite(f):
        return num(value)
    return int(f) if f.is_integer() else num(f)


def jsonable(value: Any, *, array_cap: int | None = None, string_cap: int | None = None) -> Any:
    """Make an attribute value JSON-safe and compact (rounded floats, capped lists)."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return num(value)
    if isinstance(value, str):
        if string_cap is not None and len(value) > string_cap:
            return value[:string_cap] + "…"
        return value
    if isinstance(value, dict):
        return {
            str(k): jsonable(v, array_cap=array_cap, string_cap=string_cap)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        items = list(value)
        if array_cap is not None and len(items) > array_cap:
            return [jsonable(v, string_cap=string_cap) for v in items[:array_cap]] + [
                f"… {len(items) - array_cap} more"
            ]
        return [jsonable(v, array_cap=array_cap, string_cap=string_cap) for v in items]
    rows = getattr(value, "asTupleOfTuples", None)  # hou.Matrix2/3/4
    if callable(rows):
        with contextlib.suppress(Exception):
            return [[num(v) for v in row] for row in rows()]
    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        with contextlib.suppress(Exception):  # hou.Vector2/3/4, hou.Quaternion, hou.Color
            return [jsonable(value[i]) for i in range(len(value))]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


# -- attribute helpers ------------------------------------------------------------


def _class_attribs(geo: Any, cls: str) -> list[Any]:
    getter = {
        "point": geo.pointAttribs,
        "prim": geo.primAttribs,
        "vertex": geo.vertexAttribs,
        "detail": geo.globalAttribs,
    }[cls]
    return list(getter())


def attrib_type(attrib: Any) -> str:
    import hou

    base = {
        hou.attribData.Float: "float",
        hou.attribData.Int: "int",
        hou.attribData.String: "string",
        hou.attribData.Dict: "dict",
    }.get(attrib.dataType(), str(attrib.dataType()).rsplit(".", 1)[-1].lower())
    return base + "[]" if attrib.isArrayType() else base


def attrib_type_info(attrib: Any) -> str | None:
    try:
        qualifier = attrib.qualifier()
    except Exception:
        return None
    return qualifier.strip().lower() or None


def attrib_entry(attrib: Any) -> dict[str, Any]:
    return {
        "name": attrib.name(),
        "type": attrib_type(attrib),
        "size": attrib.size(),
        "type_info": attrib_type_info(attrib),
    }


def class_count(geo: Any, cls: str) -> int:
    if cls == "detail":
        return 1
    key = {"point": "pointcount", "prim": "primitivecount", "vertex": "vertexcount"}[cls]
    return int(geo.intrinsicValue(key))


# -- geo_info ---------------------------------------------------------------------


def _bbox(geo: Any) -> dict[str, list[Any]] | None:
    if class_count(geo, "point") == 0:
        return None
    bbox = geo.boundingBox()
    if not bbox.isValid():
        return None
    return {
        "min": [num(v) for v in bbox.minvec()],
        "max": [num(v) for v in bbox.maxvec()],
        "size": [num(v) for v in bbox.sizevec()],
        "center": [num(v) for v in bbox.center()],
    }


def prim_type_counts(geo: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in geo.primTypeNames():
        n = int(geo.countPrimType(name))
        if n:
            key = PRIM_TYPE_KEYS.get(name, name.lower())
            counts[key] = counts.get(key, 0) + n
    return counts


def _capped(items: list[dict[str, Any]], out: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if len(items) > LIST_CAP:
        out.setdefault("truncated", []).append(key)
        return items[:LIST_CAP]
    return items


INTERNAL_ATTRIBUTES = frozenset(
    {
        # Vellum and DOP solver bookkeeping (review 23 papercut 8; listed on 22.0.466)
        "dP", "dPw", "plast", "pprevious", "has_pprevious", "vlast", "vprevious",
        "hitnml", "hitnum", "hitpos", "hitprim", "hittime", "hituv", "hitv",
        "overlap_self", "overlap_external", "disableself", "disableexternal", "fallback",
        "target_path", "target_pt", "targetv", "targetw", "dopobject", "doppath",
        "rest_ratio", "rest2_ratio", "timescale", "varmap",
    }
)  # fmt: skip
INTERNAL_PREFIXES = ("__",)
"""Attributes ``geo_info`` counts as ``internal_attribute_count`` instead of listing:
solver state an agent rarely reads (``geo_read`` with ``attribs`` still reads them)."""
ATTRIBUTE_MODES = ("full", "names")


def is_internal_attribute(name: str) -> bool:
    return name in INTERNAL_ATTRIBUTES or name.startswith(INTERNAL_PREFIXES)


def _attributes(
    geo: Any, out: dict[str, Any], mode: str = "full", full_strings: bool = False
) -> dict[str, list[Any]]:
    """``geo_info``'s attributes per class, ``full`` rows or ``names`` only, without the
    solver internals (counted in ``out``)."""
    attributes: dict[str, list[Any]] = {}
    internal: list[str] = []

    def visible(cls: str) -> list[Any]:
        kept = []
        for attrib in _class_attribs(geo, cls):
            if is_internal_attribute(attrib.name()):
                internal.append(attrib.name())
            else:
                kept.append(attrib)
        return kept

    for cls in ("point", "vertex", "prim"):
        attribs = visible(cls)
        if mode == "names":
            attributes[cls] = [a.name() for a in attribs]
        else:
            entries = [attrib_entry(a) for a in attribs]
            attributes[cls] = _capped(entries, out, f"attributes.{cls}")
    detail_attribs = visible("detail")
    if internal:
        out["internal_attribute_count"] = len(internal)
        shown = ", ".join(internal[:6]) + (", ..." if len(internal) > 6 else "")
        out.setdefault("notes", []).append(
            f"{len(internal)} solver-internal attribute(s) left out ({shown}); "
            f"{hint_tool('geo_read', path=BARE, attribs=BARE)} reads them."
        )
    if mode == "names":
        attributes["detail"] = [a.name() for a in detail_attribs]
        return attributes
    detail = []
    for attrib in detail_attribs:
        entry = attrib_entry(attrib)
        try:
            value = geo.attribValue(attrib.name())
        except Exception as exc:  # pragma: no cover - defensive
            value = f"<unreadable: {exc}>"
        entry["value"] = _detail_value(value, full_strings)
        detail.append(entry)
    attributes["detail"] = _capped(detail, out, "attributes.detail")
    return attributes


def _detail_value(value: Any, full_strings: bool = False) -> Any:
    """A detail attribute value for ``geo_info``: arrays and strings capped, and a dict
    whose JSON is longer than :data:`DETAIL_STRING_CAP` as ``{elided: <chars>, keys}``
    (review 17 P1-7: a pyro ``volvis`` dict was half of every ``geo_info``); whole with
    ``full_strings`` (``inspect what: geo``, 2.1, review 26 P1 #9)."""
    if full_strings:
        return jsonable(value)
    out = jsonable(value, array_cap=DETAIL_ARRAY_CAP, string_cap=DETAIL_STRING_CAP)
    if isinstance(out, dict):
        size = len(json.dumps(out, separators=(",", ":"), default=str))
        if size > DETAIL_STRING_CAP:
            return {"elided": size, "keys": sorted(out)[:DETAIL_ARRAY_CAP]}
    return out


def _groups(geo: Any, out: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "point": [{"name": g.name(), "count": g.pointCount()} for g in geo.pointGroups()],
        "prim": [{"name": g.name(), "count": g.primCount()} for g in geo.primGroups()],
        "edge": [{"name": g.name(), "count": g.edgeCount()} for g in geo.edgeGroups()],
        "vertex": [{"name": g.name(), "count": g.vertexCount()} for g in geo.vertexGroups()],
    }
    return {cls: _capped(entries, out, f"groups.{cls}") for cls, entries in groups.items()}


def _prim_name(geo: Any, prim: Any) -> str | None:
    attrib = geo.findPrimAttrib("name")
    import hou

    if attrib is None or attrib.dataType() != hou.attribData.String or attrib.isArrayType():
        return None
    try:
        return prim.attribValue("name") or None
    except Exception:
        return None


def _intrinsics(geo: Any, prim_types: dict[str, int]) -> dict[str, Any]:
    """Summaries of the first few packed / volume / VDB primitives (never voxel data)."""
    import hou

    out: dict[str, Any] = {}

    def sample(ptype: Any) -> list[Any]:
        return list(itertools.islice(geo.iterPrimsOfType(ptype), INTRINSIC_SAMPLES))

    def iv(prim: Any, name: str) -> Any:
        try:
            return jsonable(prim.intrinsicValue(name))
        except Exception:
            return None

    if any(k.startswith("packed") or k in ("agent", "alembic") for k in prim_types):
        rows = []
        for prim in (
            sample(hou.primType.PackedPrim)
            + sample(hou.primType.Agent)
            + sample(hou.primType.AlembicRef)
        ):
            row = {
                "prim": prim.number(),
                "type": iv(prim, "packedtypename"),
                "bounds": iv(prim, "packedbounds"),
            }
            name = _prim_name(geo, prim)
            if name:
                row["name"] = name
            rows.append(row)
            if len(rows) >= INTRINSIC_SAMPLES:
                break
        out["packed"] = rows
    # Every volume and VDB as one compact row (review 17 P1-7), up to FIELD_ROWS_CAP.
    fields = (
        ("volume", hou.primType.Volume, VOLUME_COLUMNS,
         ("voxelresolution", "voxelsize", "volumeminvalue", "volumemaxvalue")),
        ("vdb", hou.primType.VDB, VDB_COLUMNS,
         ("vdb_class", "vdb_value_type", "activevoxelcount", "voxelsize")),
    )  # fmt: skip
    for key, ptype, columns, names in fields:
        if key not in prim_types:
            continue
        rows = [
            [_prim_name(geo, prim), prim.number(), *(iv(prim, name) for name in names)]
            for prim in itertools.islice(geo.iterPrimsOfType(ptype), FIELD_ROWS_CAP)
        ]
        out[f"{key}_columns"] = columns
        out[key] = rows
        if prim_types[key] > len(rows):
            out[f"{key}_total"] = prim_types[key]
    return out


def _cop_info(path: Any, frame: Any) -> dict[str, Any] | None:
    """The image summary of a Cop node (or a COP network's display node), or None for
    other nodes (review 18 papercut 3: geo_info refused COPs)."""
    from .visual import cop_image_node, image_summary, is_cop_network

    node = require_node(path)
    target = cop_image_node(node)
    if target is None:
        if is_cop_network(node):
            raise ToolError(
                "invalid_argument",
                f"{node.path()} has no display node.",
                hint="Pass a Cop node inside it, or set a display flag.",
            )
        return None
    if frame is not None and (isinstance(frame, bool) or not isinstance(frame, int | float)):
        raise ToolError("invalid_argument", "'frame' must be a number.")
    refresh_stale(target)
    out: dict[str, Any] = {"path": target.path(), "kind": "image"}
    if frame is not None:
        out["frame"] = num(frame)
    out.update(image_summary(target, frame))
    errors = [str(e).strip() for e in target.errors() if str(e).strip()]
    if errors:
        out["errors"] = errors
    stale = stale_file_notes(target, frame)  # D80: a File COP keeps an overwritten image
    if stale:
        out["notes"] = stale
    return out


def geo_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    frame = args.get("frame")
    image = _cop_info(args.get("path"), frame)
    if image is not None:
        return image
    mode = args.get("attributes", "full") or "full"
    if mode not in ATTRIBUTE_MODES:
        raise ToolError("invalid_argument", "'attributes' must be 'full' or 'names'.")
    sop = resolve_sop(args.get("path"))
    geo = cooked_geometry(sop, frame)
    out: dict[str, Any] = {"path": sop.path()}
    if frame is not None:
        out["frame"] = num(frame)
    out["point_count"] = class_count(geo, "point")
    out["prim_count"] = class_count(geo, "prim")
    out["vertex_count"] = class_count(geo, "vertex")
    out["bbox"] = _bbox(geo)
    prim_types = prim_type_counts(geo)
    out["prim_types"] = prim_types
    full_strings = bool(args.get("full_strings", False))
    out["attributes"] = _attributes(geo, out, mode, full_strings)
    out["groups"] = _groups(geo, out)
    intrinsics = _intrinsics(geo, prim_types)
    if intrinsics:
        out["intrinsics"] = intrinsics
    with contextlib.suppress(Exception):
        out["memory_bytes"] = int(geo.intrinsicValue("memoryusage"))
    if args.get("stats") or args.get("attribs") is not None:
        out["stats"] = summary_stats(geo, args.get("attribs"))
    warnings = [str(w).strip() for w in sop.warnings() if str(w).strip()]
    if warnings:
        out["warnings"] = warnings
    return out


SUMMARY_STATS_CAP = 24
"""Attributes the summary's ``stats`` covers when ``attribs`` names none."""


def summary_stats(geo: Any, wanted: Any) -> dict[str, Any]:
    """``geo_info``'s ``stats`` (2.1, D76): per class, the ``attribs`` named (any class
    holding them; each class a name is found in) or every visible point, prim and vertex
    attribute up to :data:`SUMMARY_STATS_CAP`, as ``rows: true, stats: true`` gives them
    (min, max and mean of numbers, unique values of strings; arrays and dicts left out)."""
    names = attrib_names(wanted)
    out: dict[str, Any] = {}
    seen: set[str] = set()
    budget = SUMMARY_STATS_CAP
    for cls in ("point", "prim", "vertex"):
        for attrib in _class_attribs(geo, cls):
            name = attrib.name()
            if names is None and (is_internal_attribute(name) or budget <= 0):
                continue
            if names is not None and name not in names:
                continue
            seen.add(name)
            result = _Column(geo, cls, attrib).stats(None)
            if result is not None:
                out.setdefault(cls, {})[name] = result
                budget -= 1
    missing = [n for n in names or () if n not in seen]
    if missing:
        detail = [a.name() for a in _class_attribs(geo, "detail")]
        known = sorted(
            {a.name() for c in ("point", "prim", "vertex") for a in _class_attribs(geo, c)}
        )
        raise ToolError(
            "invalid_argument",
            f"No point, prim or vertex attribute named {missing[0]!r} for stats"
            + (
                " (it is a detail attribute: the summary lists its value)."
                if missing[0] in detail
                else "."
            ),
            candidates=difflib.get_close_matches(missing[0], known, n=5, cutoff=0.3) or known[:10],
        )
    return out


# -- geo_read ---------------------------------------------------------------------


_GROUPTYPE = {"vertex": 1, "point": 3, "prim": 4}
_VERB_CLASS = {"prim": 1, "point": 2, "vertex": 3}
_MEMBER_ATTRIB = "__hocuspocus_member"


def _class_groups(geo: Any, cls: str) -> list[str]:
    getter = {"point": geo.pointGroups, "prim": geo.primGroups, "vertex": geo.vertexGroups}[cls]
    return [g.name() for g in getter()]


def group_members(geo: Any, cls: str, group: str) -> Any:
    """Sorted numpy indices of the ``cls`` elements in ``group`` (a name or pattern)."""
    import hou
    import numpy as np

    if _PLAIN_GROUP.match(group):
        names = _class_groups(geo, cls)
        if group not in names:
            others = [
                other
                for other in ("point", "prim", "vertex")
                if other != cls and group in _class_groups(geo, other)
            ]
            hint = (
                f"{group!r} is {a_or_an(others[0])} group; read class {others[0]!r} or promote it."
                if others
                else f"Available {cls} groups are listed in candidates; patterns like '0-9' or "
                "'@P.y>0' also work."
            )
            raise ToolError(
                "invalid_argument",
                f"No {cls} group named {group!r}.",
                hint=hint,
                candidates=difflib.get_close_matches(group, names, n=5, cutoff=0.3) or names[:10],
            )
    verb = hou.sopNodeTypeCategory().nodeVerb("attribcreate::2.0")
    entry = dict(verb.parms()["numattr"][0])
    entry.update(
        {
            "name#": _MEMBER_ATTRIB,
            "class#": _VERB_CLASS[cls],
            "type#": 1,
            "size#": 1,
            "default#v": hou.Vector4(0, 0, 0, 0),
            "value#v": hou.Vector4(1, 0, 0, 0),
        }
    )
    verb.setParms({"group": group, "grouptype": _GROUPTYPE[cls], "numattr": (entry,)})
    scratch = hou.Geometry()
    try:
        verb.execute(scratch, [geo])
    except hou.OperationFailed as exc:
        raise ToolError(
            "invalid_argument",
            f"Group pattern {group!r} could not be evaluated for class {cls}.",
            hou_exception=f"hou.OperationFailed: {exc}",
        ) from exc
    getter = {
        "point": scratch.pointIntAttribValuesAsString,
        "prim": scratch.primIntAttribValuesAsString,
        "vertex": scratch.vertexIntAttribValuesAsString,
    }[cls]
    try:
        mask = np.frombuffer(getter(_MEMBER_ATTRIB), dtype=np.int32)
    except hou.OperationFailed:
        return np.zeros(0, dtype=np.int64)
    return np.nonzero(mask)[0]


class _Column:
    """Bulk access to one attribute of one class."""

    def __init__(self, geo: Any, cls: str, attrib: Any) -> None:
        self.geo = geo
        self.cls = cls
        self.attrib = attrib
        self.name = attrib.name()
        self.size = attrib.size()
        self.type = attrib_type(attrib)
        self._cache: Any = None

    @property
    def numeric(self) -> bool:
        return self.type in ("float", "int")

    def _float64(self) -> bool:
        import hou

        try:
            return self.attrib.numericDataType() in (hou.numericData.Float64, hou.numericData.Int64)
        except Exception:
            return False

    def values(self) -> Any:
        """All values: an (n, size) numpy array for numerics, else a tuple."""
        if self._cache is not None:
            return self._cache
        import hou
        import numpy as np

        geo, cls, name = self.geo, self.cls, self.name
        prefix = {"point": "point", "prim": "prim", "vertex": "vertex"}[cls]
        if self.type == "float":
            wide = self._float64()
            raw = getattr(geo, f"{prefix}FloatAttribValuesAsString")(
                name, float_type=hou.numericData.Float64 if wide else hou.numericData.Float32
            )
            arr = np.frombuffer(raw, dtype=np.float64 if wide else np.float32)
            self._cache = arr.reshape(-1, max(self.size, 1))
        elif self.type == "int":
            wide = self._float64()
            raw = getattr(geo, f"{prefix}IntAttribValuesAsString")(
                name, int_type=hou.numericData.Int64 if wide else hou.numericData.Int32
            )
            arr = np.frombuffer(raw, dtype=np.int64 if wide else np.int32)
            self._cache = arr.reshape(-1, max(self.size, 1))
        elif self.type == "string":
            self._cache = getattr(geo, f"{prefix}StringAttribValues")(name)
        elif self.type in ("float[]", "int[]", "string[]"):
            kind = {"float[]": "Float", "int[]": "Int", "string[]": "String"}[self.type]
            self._cache = getattr(geo, f"{prefix}{kind}ListAttribValues")(name)
        else:
            self._cache = None  # dicts: read per row
        return self._cache

    def cells(self, indices: Any, *, bulk: bool = True) -> list[Any]:
        """Values for ``indices``. Without ``bulk`` (and no column already loaded) each
        element is read on its own, so a page never builds a whole-class column."""
        values = self.values() if bulk or self._cache is not None else None
        if values is None:
            element = {"point": self.geo.point, "prim": self.geo.prim, "vertex": self.geo.vertex}[
                self.cls
            ]
            raw = [element(int(i)).attribValue(self.name) for i in indices]
            if self.numeric:
                if self.size == 1:
                    return [num(v) for v in raw]
                return [[num(x) for x in v] for v in raw]
            return [jsonable(v) for v in raw]
        if self.numeric:
            block = values[indices]
            if self.size == 1:
                return [num(v) for v in block[:, 0].tolist()]
            return [[num(v) for v in row] for row in block.tolist()]
        return [jsonable(values[int(i)]) for i in indices]

    def stats(self, indices: Any) -> dict[str, Any] | None:
        import numpy as np

        values = self.values()
        if values is None or self.type.endswith("[]"):
            return None
        if self.numeric:
            block = values if indices is None else values[indices]
            if block.shape[0] == 0:
                return {"min": None, "max": None, "mean": None}
            lo = block.min(axis=0)
            hi = block.max(axis=0)
            mean = block.mean(axis=0, dtype=np.float64)

            def shape(vec: Any) -> Any:
                items = [num(v) for v in vec.tolist()]
                return items[0] if self.size == 1 else items

            return {"min": shape(lo), "max": shape(hi), "mean": shape(mean)}
        strings = values if indices is None else [values[int(i)] for i in indices]
        unique = set(strings)
        out: dict[str, Any] = {
            "unique": sorted(unique)[:STATS_UNIQUE_CAP],
            "unique_count": len(unique),
        }
        return out


def attrib_names(wanted: Any) -> list[str] | None:
    """``attribs`` as a list of names: a list, or (2.1) one string of names separated by
    commas or spaces (``"P, Cd"``), as the schema allows."""
    if wanted is None:
        return None
    if isinstance(wanted, str):
        wanted = [w for w in re.split(r"[,\s]+", wanted) if w]
    if not isinstance(wanted, list) or not wanted or not all(isinstance(w, str) for w in wanted):
        raise ToolError(
            "invalid_argument",
            "'attribs' must be attribute names: a list, or one string such as \"P, Cd\".",
        )
    return wanted


def _resolve_attribs(geo: Any, cls: str, wanted: Any) -> list[Any]:
    available = _class_attribs(geo, cls)
    wanted = attrib_names(wanted)
    if wanted is None:
        return available
    by_name = {a.name(): a for a in available}
    picked = []
    for name in wanted:
        attrib = by_name.get(name)
        if attrib is None:
            elsewhere = [
                other
                for other in CLASSES
                if other != cls and any(a.name() == name for a in _class_attribs(geo, other))
            ]
            hint = (
                f"{name!r} is {a_or_an(elsewhere[0])} attribute; pass class {elsewhere[0]!r}."
                if elsewhere
                else f"Available {cls} attributes: {', '.join(sorted(by_name)) or 'none'}."
            )
            raise ToolError(
                "invalid_argument",
                f"No {cls} attribute named {name!r} on this geometry.",
                hint=hint,
                candidates=difflib.get_close_matches(name, list(by_name), n=5, cutoff=0.3)
                or sorted(by_name)[:10],
            )
        picked.append(attrib)
    return picked


BULK_SHARE = 4
"""A page covering at least 1/BULK_SHARE of the class reads whole columns (cheaper than
per-element reads); smaller pages read only their own rows."""


def geo_read(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import numpy as np

    cls = args.get("class", "point") or "point"
    if cls not in CLASSES:
        raise ToolError(
            "invalid_argument",
            f"'class' must be one of {', '.join(CLASSES)}; got {cls!r}.",
            candidates=difflib.get_close_matches(str(cls), CLASSES, n=2, cutoff=0.3)
            or list(CLASSES),
        )
    cursor = args.get("cursor")
    start = parse_offset(cursor) if cursor not in (None, "") else int_arg(args, "start", 0, 0)
    count = min(int_arg(args, "count", 50, 1), 10_000)
    stats = args.get("stats", False)
    if not isinstance(stats, bool):
        raise ToolError("invalid_argument", "'stats' must be a boolean.")
    group = args.get("group")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise ToolError("invalid_argument", "'group' must be a non-empty string.")
    frame = args.get("frame")

    sop = resolve_sop(args.get("path"))
    # geometryAtFrame: the playbar stays where the user left it (review 17 P1-5).
    geo = cooked_geometry(sop, frame)
    attribs = _resolve_attribs(geo, cls, args.get("attribs"))
    out: dict[str, Any] = {"path": sop.path(), "class": cls}
    if frame is not None:
        out["frame"] = num(frame)

    if cls == "detail":
        if group:
            raise ToolError("invalid_argument", "'group' does not apply to class 'detail'.")
        out["columns"] = [a.name() for a in attribs]
        cap = None if args.get("full_strings") else 256
        out["rows"] = [[jsonable(geo.attribValue(a.name()), array_cap=cap) for a in attribs]]
        out["total"] = 1
        return out

    members = group_members(geo, cls, group.strip()) if group else None
    total = int(len(members)) if members is not None else class_count(geo, cls)
    end = min(total, start + count)
    indices = members[start:end] if members is not None else np.arange(start, end, dtype=np.int64)

    columns = [_Column(geo, cls, a) for a in attribs]
    index_cols = {"point": ["ptnum"], "prim": ["primnum"], "vertex": ["vtxnum", "primnum", "ptnum"]}
    out["columns"] = index_cols[cls] + [c.name for c in columns]
    if group:
        out["group"] = group
    # Whole columns only when stats need them anyway or the page is a large share.
    bulk = stats or len(indices) * BULK_SHARE >= max(total, 1)
    cells = [c.cells(indices, bulk=bulk) for c in columns]
    if cls == "vertex":
        owners = []
        for i in indices.tolist():
            vertex = geo.vertex(int(i))
            owners.append((vertex.prim().number(), vertex.point().number()))
    rows: list[list[Any]] = []
    used = 0
    for r, index in enumerate(indices.tolist()):
        row: list[Any] = [int(index)]
        if cls == "vertex":
            row.extend(owners[r])
        row.extend(col[r] for col in cells)
        size = len(json.dumps(row, separators=(",", ":"), default=str))
        if rows and used + size > ROWS_BYTE_BUDGET:
            out["truncated"] = True
            break
        used += size + 1
        rows.append(row)
    out["rows"] = rows
    out["start"] = start
    out["total"] = total
    if start + len(rows) < total:
        out["next_cursor"] = str(start + len(rows))
    if stats:
        stat_rows: dict[str, Any] = {}
        for column in columns:
            result = column.stats(members)
            if result is not None:
                stat_rows[column.name] = result
        out["stats"] = stat_rows
    return out


# -- geo groups (2.1, D71) -----------------------------------------------------------

GROUPS_PAGE = 50
"""Groups per page of ``inspect {what: "geo", group_by}`` unless ``count`` says."""
GROUP_KEY_TYPES = ("string", "int")
_TOPO_PT = "__hocuspocus_pt"
_TOPO_PR = "__hocuspocus_pr"
_TOPO_AREA = "__hocuspocus_area"
_PROMOTE_CLASS = {"prim": 1, "point": 2, "vertex": 3}
"""``attribpromote``'s ``inclass``/``outclass`` menu indices (detail is 0)."""


def _verb(name: str) -> Any:
    import hou

    verb = hou.sopNodeTypeCategory().nodeVerb(name)
    if verb is None:  # pragma: no cover - every 22.0 build has these verbs
        raise ToolError("internal", f"The {name} SOP verb is not available in this Houdini.")
    return verb


def _topology(geo: Any) -> tuple[Any, Any, Any]:
    """``(vertex_prim, vertex_point, prim_area)`` as numpy arrays, computed in C++ on a
    copy of ``geo``: every point and prim numbered into an attribute, both promoted to
    vertices (``attribpromote``), and each prim's area measured (``measure::2.0``). The
    cooked geometry is never changed."""
    import hou
    import numpy as np

    work = hou.Geometry()
    work.merge(geo)
    work.addAttrib(hou.attribType.Point, _TOPO_PT, 0)
    work.addAttrib(hou.attribType.Prim, _TOPO_PR, 0)
    work.setPointIntAttribValuesFromString(
        _TOPO_PT, np.arange(class_count(geo, "point"), dtype=np.int32).tobytes()
    )
    work.setPrimIntAttribValuesFromString(
        _TOPO_PR, np.arange(class_count(geo, "prim"), dtype=np.int32).tobytes()
    )
    for name, cls in ((_TOPO_PT, "point"), (_TOPO_PR, "prim")):
        verb = _verb("attribpromote")
        verb.setParms(
            {
                "inname": name,
                "inclass": _PROMOTE_CLASS[cls],
                "outclass": _PROMOTE_CLASS["vertex"],
                "deletein": 0,
            }
        )
        out = hou.Geometry()
        verb.execute(out, [work])
        work = out
    measure = _verb("measure::2.0")
    measure.setParms({"grouptype": 1, "measure": 1, "attribname": _TOPO_AREA})
    measured = hou.Geometry()
    measure.execute(measured, [work])
    vprim = np.frombuffer(measured.vertexIntAttribValuesAsString(_TOPO_PR), dtype=np.int32)
    vpoint = np.frombuffer(measured.vertexIntAttribValuesAsString(_TOPO_PT), dtype=np.int32)
    area = np.frombuffer(
        measured.primFloatAttribValuesAsString(_TOPO_AREA), dtype=np.float32
    ).astype(np.float64)
    return vprim, vpoint, area


def _mask(geo: Any, cls: str, pattern: str, count: int) -> Any:
    import numpy as np

    mask = np.zeros(count, dtype=bool)
    mask[group_members(geo, cls, pattern)] = True
    return mask


def _key_column(geo: Any, name: Any) -> tuple[str, Any]:
    """The class and the attribute ``group_by`` names: a prim attribute first, then a
    point one; a string or int of size 1."""
    if not isinstance(name, str) or not name.strip():
        raise ToolError("invalid_argument", "'group_by' must be an attribute name.")
    name = name.strip()
    for cls in ("prim", "point"):
        attrib = next((a for a in _class_attribs(geo, cls) if a.name() == name), None)
        if attrib is None:
            continue
        kind = attrib_type(attrib)
        if kind not in GROUP_KEY_TYPES or attrib.size() != 1:
            raise ToolError(
                "invalid_argument",
                f"group_by takes a string or int {cls} attribute of size 1; {name!r} is "
                f"{kind}{attrib.size() if attrib.size() != 1 else ''}.",
                hint="Pass it in attribs for its min, max and mean per group of another "
                "attribute, or read it with rows: true and stats: true.",
            )
        return cls, attrib
    elsewhere = [
        cls
        for cls in ("vertex", "detail")
        if any(a.name() == name for a in _class_attribs(geo, cls))
    ]
    names = sorted({a.name() for cls in ("prim", "point") for a in _class_attribs(geo, cls)})
    raise ToolError(
        "invalid_argument",
        f"No prim or point attribute named {name!r} to group by"
        + (f" (it is {a_or_an(elsewhere[0])} attribute)." if elsewhere else "."),
        hint="group_by takes a prim attribute (surface, name, mat_id) or a point one; "
        "promote a vertex attribute first.",
        candidates=difflib.get_close_matches(name, names, n=5, cutoff=0.3) or names[:10],
    )


def _stats_columns(geo: Any, cls: str, wanted: Any) -> list[_Column]:
    """The numeric attributes ``attribs`` names for the group stats: of any class for prim
    groups (a vertex attribute over the prims of each group), points for point groups."""
    wanted = attrib_names(wanted)
    if wanted is None:
        return []
    owners = ("prim", "point", "vertex") if cls == "prim" else ("point",)
    picked: list[_Column] = []
    for name in wanted:
        column = None
        for owner in owners:
            attrib = next((a for a in _class_attribs(geo, owner) if a.name() == name), None)
            if attrib is not None:
                column = _Column(geo, owner, attrib)
                break
        if column is None:
            names = sorted({a.name() for owner in owners for a in _class_attribs(geo, owner)})
            raise ToolError(
                "invalid_argument",
                f"No {', '.join(owners)} attribute named {name!r} for the group stats.",
                candidates=difflib.get_close_matches(name, names, n=5, cutoff=0.3) or names[:10],
            )
        if not column.numeric:
            raise ToolError(
                "invalid_argument",
                f"attribs takes numeric attributes for the group stats; {name!r} is {column.type}.",
                hint=f"group_by {name!r} counts the elements per value instead.",
            )
        picked.append(column)
    return picked


def _group_keys(column: _Column) -> tuple[list[Any], Any]:
    """``(values, index)``: the distinct values of a key column and each element's index
    into them."""
    import numpy as np

    values = column.values()
    if column.type == "int":
        keys, inverse = np.unique(values[:, 0], return_inverse=True)
        return [int(k) for k in keys.tolist()], inverse
    keys, inverse = np.unique(np.asarray(values, dtype=object), return_inverse=True)
    return [str(k) for k in keys.tolist()], inverse


def _reduce(keys: Any, values: Any, groups: int) -> dict[str, Any]:
    """Per group ``min``, ``max`` and ``mean`` (arrays of shape (groups, size)) of
    ``values`` (n, size) grouped by ``keys`` (n); a group without elements is NaN."""
    import numpy as np

    values = values.reshape(len(keys), -1)
    size = values.shape[1]
    lo = np.full((groups, size), np.nan)
    hi = np.full((groups, size), np.nan)
    mean = np.full((groups, size), np.nan)
    if len(keys):
        order = np.argsort(keys, kind="stable")
        sorted_keys = keys[order]
        block = values[order].astype(np.float64)
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
        present = sorted_keys[starts]
        lo[present] = np.minimum.reduceat(block, starts, axis=0)
        hi[present] = np.maximum.reduceat(block, starts, axis=0)
        counts = np.diff(np.r_[starts, len(sorted_keys)])
        mean[present] = np.add.reduceat(block, starts, axis=0) / counts[:, None]
    return {"min": lo, "max": hi, "mean": mean}


def _cell(row: Any) -> Any:
    items = [None if math.isnan(v) else num(v) for v in row.tolist()]
    return items[0] if len(items) == 1 else items


def geo_groups(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """``inspect {what: "geo", group_by}`` (2.1, D71): per value of a prim (or point)
    attribute, the prim, point and triangle counts, the area and the bounding box, and
    ``attribs``' min, max and mean (prim, point or vertex attributes of those prims), over
    the elements of ``group`` when given. Rows under ``columns``, largest group first,
    paged by ``count`` and ``cursor`` and cut at :data:`ROWS_BYTE_BUDGET`."""
    import numpy as np

    sop = resolve_sop(args.get("path"))
    frame = args.get("frame")
    geo = cooked_geometry(sop, frame)
    cls, key_attrib = _key_column(geo, args.get("group_by"))
    cursor = args.get("cursor")
    start = parse_offset(cursor) if cursor not in (None, "") else int_arg(args, "start", 0, 0)
    count = min(int_arg(args, "count", GROUPS_PAGE, 1), 10_000)
    group = args.get("group")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise ToolError("invalid_argument", "'group' must be a non-empty string.")
    stats_cols = _stats_columns(geo, cls, args.get("attribs"))
    out: dict[str, Any] = {"path": sop.path(), "group_by": key_attrib.name(), "class": cls}
    if frame is not None:
        out["frame"] = num(frame)
    if group:
        out["group"] = group.strip()

    values, index = _group_keys(_Column(geo, cls, key_attrib))
    n_groups = len(values)
    n_elems = class_count(geo, cls)
    selected = _mask(geo, cls, group.strip(), n_elems) if group else np.ones(n_elems, dtype=bool)
    keys = np.where(selected, index, -1)
    live = keys >= 0
    positions = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32)
    positions = positions.reshape(-1, 3)
    data: dict[str, Any] = {}
    if cls == "prim":
        vprim, vpoint, area = _topology(geo)
        nverts = np.bincount(vprim, minlength=n_elems)
        closed_poly = _mask(geo, "prim", "@intrinsic:typename==Poly", n_elems) & _mask(
            geo, "prim", "@intrinsic:closed==1", n_elems
        )
        tris = np.where(closed_poly & (nverts >= 3), nverts - 2, 0)
        size_of = np.bincount(keys[live], minlength=n_groups)
        data["triangles"] = np.bincount(keys[live], weights=tris[live], minlength=n_groups)
        data["area"] = np.bincount(keys[live], weights=area[live], minlength=n_groups)
        vkeys = keys[vprim]
        vlive = vkeys >= 0
        n_points = max(1, class_count(geo, "point"))
        pairs = np.unique(vkeys[vlive].astype(np.int64) * n_points + vpoint[vlive])
        pair_keys, pair_points = pairs // n_points, pairs % n_points
        data["points"] = np.bincount(pair_keys, minlength=n_groups)
        box = _reduce(pair_keys, positions[pair_points], n_groups)
        for col in stats_cols:
            vals = col.values()
            if col.cls == "prim":
                data[col.name] = _reduce(keys[live], vals[live], n_groups)
            elif col.cls == "point":
                data[col.name] = _reduce(pair_keys, vals[pair_points], n_groups)
            else:
                data[col.name] = _reduce(vkeys[vlive], vals[vlive], n_groups)
        columns = ["value", "prims", "points", "triangles", "area", "bbox_min", "bbox_max"]
    else:
        size_of = np.bincount(keys[live], minlength=n_groups)
        box = _reduce(keys[live], positions[live], n_groups)
        for col in stats_cols:
            data[col.name] = _reduce(keys[live], col.values()[live], n_groups)
        columns = ["value", "points", "bbox_min", "bbox_max"]
    for col in stats_cols:
        columns += [f"{col.name}.min", f"{col.name}.max", f"{col.name}.mean"]

    present = [g for g in range(n_groups) if size_of[g] > 0]
    present.sort(key=lambda g: (-int(size_of[g]), str(values[g])))
    out["total"] = len(present)
    rows: list[list[Any]] = []
    used = 0
    for g in present[start : start + count]:
        row: list[Any] = [values[g], int(size_of[g])]
        if cls == "prim":
            row += [int(data["points"][g]), int(data["triangles"][g]), num(float(data["area"][g]))]
        row += [_cell(box["min"][g]), _cell(box["max"][g])]
        for col in stats_cols:
            reduced = data[col.name]
            row += [_cell(reduced["min"][g]), _cell(reduced["max"][g]), _cell(reduced["mean"][g])]
        size = len(json.dumps(row, separators=(",", ":"), default=str))
        if rows and used + size > ROWS_BYTE_BUDGET:
            out["truncated"] = True
            break
        used += size + 1
        rows.append(row)
    out["columns"] = columns
    out["rows"] = rows
    if start:
        out["start"] = start
    if start + len(rows) < len(present):
        out["next_cursor"] = str(start + len(rows))
    return out
