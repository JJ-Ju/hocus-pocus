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

from ._common import int_arg, parse_offset
from ._diag import a_or_an, collect_problems, refresh_stale, require_node
from .registry import HostContext, tool

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
            hint="Fix the errors in detail (see also the problems tool), then retry.",
            hou_exception=f"hou.OperationFailed: {exc}",
            detail={"path": sop.path(), **problems},
        ) from exc
    errors = [str(e).strip() for e in sop.errors() if str(e).strip()]
    if geo is None or errors:
        problems = collect_problems(sop)
        raise ToolError(
            "cook_failed",
            f"{sop.path()} has cook errors: {errors[0] if errors else 'no geometry'}",
            hint="Fix the errors in detail (see also the problems tool), then retry.",
            detail={"path": sop.path(), **problems},
        )
    return geo


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


def _attributes(geo: Any, out: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    attributes: dict[str, list[dict[str, Any]]] = {}
    for cls in ("point", "vertex", "prim"):
        entries = [attrib_entry(a) for a in _class_attribs(geo, cls)]
        attributes[cls] = _capped(entries, out, f"attributes.{cls}")
    detail = []
    for attrib in _class_attribs(geo, "detail"):
        entry = attrib_entry(attrib)
        try:
            value = geo.attribValue(attrib.name())
        except Exception as exc:  # pragma: no cover - defensive
            value = f"<unreadable: {exc}>"
        entry["value"] = _detail_value(value)
        detail.append(entry)
    attributes["detail"] = _capped(detail, out, "attributes.detail")
    return attributes


def _detail_value(value: Any) -> Any:
    """A detail attribute value for ``geo_info``: arrays and strings capped, and a dict
    whose JSON is longer than :data:`DETAIL_STRING_CAP` as ``{elided: <chars>, keys}``
    (review 17 P1-7: a pyro ``volvis`` dict was half of every ``geo_info``)."""
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
    return out


@tool("geo_info")
def geo_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    frame = args.get("frame")
    image = _cop_info(args.get("path"), frame)
    if image is not None:
        return image
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
    out["attributes"] = _attributes(geo, out)
    out["groups"] = _groups(geo, out)
    intrinsics = _intrinsics(geo, prim_types)
    if intrinsics:
        out["intrinsics"] = intrinsics
    with contextlib.suppress(Exception):
        out["memory_bytes"] = int(geo.intrinsicValue("memoryusage"))
    warnings = [str(w).strip() for w in sop.warnings() if str(w).strip()]
    if warnings:
        out["warnings"] = warnings
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


def _resolve_attribs(geo: Any, cls: str, wanted: Any) -> list[Any]:
    available = _class_attribs(geo, cls)
    if wanted is None:
        return available
    if not isinstance(wanted, list) or not all(isinstance(w, str) for w in wanted):
        raise ToolError("invalid_argument", "'attribs' must be a list of attribute names.")
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


@tool("geo_read")
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
        out["rows"] = [[jsonable(geo.attribValue(a.name()), array_cap=256) for a in attribs]]
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
