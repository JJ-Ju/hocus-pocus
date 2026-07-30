"""Bounded USD mesh-surface measurement for production observation."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


# Keep the complete Houdini/USD/Python process below 2 GiB: reserve 1 GiB for
# Houdini, the reopened USD stage, and interpreter state; retain 256 MiB of
# emergency headroom; and permit this observer 768 MiB.  Each charged sample
# conservatively represents 128 bytes of simultaneous Vt/Python list, tuple,
# index, and Counter working set.  Rounding 768 MiB / 128 down to six million
# leaves allocator slack while still admitting production meshes with hundreds
# of thousands of fully framed, single-UV render corners.
SURFACE_OBSERVER_WORKING_BYTES = 768 * 1024 * 1024
SURFACE_OPERATION_BYTES = 128
MAX_SURFACE_OPERATIONS = 6_000_000


class ProductionUsdObservationError(RuntimeError):
    """Raised when a serialized asset cannot prove its declared USD semantics."""


class _SurfaceOperationBudget:
    """Fail-closed aggregate budget for topology and expanded surface samples."""

    def __init__(self, maximum: int = MAX_SURFACE_OPERATIONS) -> None:
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
            raise ProductionUsdObservationError(
                "USD surface-operation budget must be a nonnegative integer."
            )
        self.maximum = maximum
        self.used = 0

    def charge(self, operations: int, *, label: str) -> None:
        if (
            isinstance(operations, bool)
            or not isinstance(operations, int)
            or operations < 0
        ):
            raise ProductionUsdObservationError(
                f"USD surface-operation charge is invalid: {label}"
            )
        if operations > self.maximum - self.used:
            raise ProductionUsdObservationError(
                "USD surface observation exceeds "
                f"{self.maximum} aggregate operations: {label}"
            )
        self.used += operations


def _mesh_surface_fact(
    mesh: Any,
    *,
    uv_names: tuple[str, ...],
    require_frames: bool,
    UsdGeom: Any,
    surface_budget: _SurfaceOperationBudget | None = None,
    world_transforms: tuple[Any, ...] | None = None,
    Gf: Any | None = None,
) -> dict[str, Any]:
    budget = surface_budget or _SurfaceOperationBudget()
    raw_counts = mesh.GetFaceVertexCountsAttr().Get()
    raw_point_indices = mesh.GetFaceVertexIndicesAttr().Get()
    raw_points = mesh.GetPointsAttr().Get()
    if raw_counts is None or raw_point_indices is None or raw_points is None:
        raise ProductionUsdObservationError(
            f"Mesh topology cannot drive primvar interpolation: {mesh.GetPath()}"
        )
    corner_count = len(raw_point_indices)
    point_count = len(raw_points)
    face_count = len(raw_counts)
    declared_corners = 0
    fan_triangles = 0
    for raw_count in raw_counts:
        count = int(raw_count)
        if count < 0:
            raise ProductionUsdObservationError(
                f"Mesh topology has a negative face size: {mesh.GetPath()}"
            )
        declared_corners += count
        fan_triangles += max(0, count - 2)
    budget.charge(
        face_count + point_count + corner_count + fan_triangles,
        label=f"{mesh.GetPath()} topology arrays",
    )
    if declared_corners != corner_count or point_count == 0:
        raise ProductionUsdObservationError(
            f"Mesh topology cannot drive primvar interpolation: {mesh.GetPath()}"
        )
    counts = [int(value) for value in raw_counts]
    point_indices = [int(value) for value in raw_point_indices]
    points = list(raw_points)
    primvars = UsdGeom.PrimvarsAPI(mesh)
    result = {
        "primPath": str(mesh.GetPath()),
        "uvSets": [
            _mesh_uv_fact(
                mesh,
                primvars,
                name,
                counts=counts,
                point_indices=point_indices,
                points=points,
                surface_budget=budget,
                world_transforms=world_transforms,
                Gf=Gf,
            )
            for name in uv_names
        ],
    }
    if require_frames:
        result.update(_mesh_frame_fact(
            mesh,
            primvars,
            counts=counts,
            point_indices=point_indices,
            surface_budget=budget,
        ))
    return result


def _mesh_frame_fact(
    mesh: Any,
    primvars: Any,
    *,
    counts: list[int],
    point_indices: list[int],
    surface_budget: _SurfaceOperationBudget,
) -> dict[str, Any]:
    normals = _expanded_attribute(
        mesh.GetNormalsAttr().Get(),
        mesh.GetNormalsInterpolation(),
        counts=counts,
        point_indices=point_indices,
        label=f"{mesh.GetPath()} normals",
        surface_budget=surface_budget,
    )
    tangent_primvar = primvars.GetPrimvar("tangentu")
    tangents = _expanded_primvar(
        tangent_primvar,
        counts=counts,
        point_indices=point_indices,
        label=f"{mesh.GetPath()} tangentu",
        surface_budget=surface_budget,
    )
    surface_budget.charge(
        len(normals) + len(tangents),
        label=f"{mesh.GetPath()} normal and tangent tuples",
    )
    normal_vectors = [_vector(value, 3, "normal") for value in normals]
    tangent_vectors = [_vector(value, 3, "tangent") for value in tangents]
    if len(normal_vectors) != len(tangent_vectors):
        raise ProductionUsdObservationError(
            f"Normals and tangents do not address the same mesh corners: {mesh.GetPath()}"
        )
    return {
        "normalInterpolation": str(mesh.GetNormalsInterpolation()),
        "normalMaxUnitLengthError": max(
            abs(_length(value) - 1.0) for value in normal_vectors
        ),
        "tangentInterpolation": str(tangent_primvar.GetInterpolation()),
        "tangentMaxOrthogonalError": max(
            abs(sum(normal[index] * tangent[index] for index in range(3)))
            for normal, tangent in zip(normal_vectors, tangent_vectors)
        ),
    }


def _expanded_primvar(
    primvar: Any,
    *,
    counts: list[int],
    point_indices: list[int],
    label: str,
    surface_budget: _SurfaceOperationBudget,
) -> list[Any]:
    if not primvar or not primvar.IsDefined():
        raise ProductionUsdObservationError(f"Required USD primvar is absent: {label}")
    raw_values = primvar.Get()
    raw_count = _sample_count(raw_values, label=label)
    indexed = bool(primvar.IsIndexed())
    raw_indices = primvar.GetIndices() if indexed else ()
    index_count = _sample_count(raw_indices, label=label + " indices")
    flattened_count = index_count if indexed else raw_count
    surface_budget.charge(
        raw_count + index_count + flattened_count,
        label=f"{label} raw, indexed, and flattened samples",
    )
    flattened = primvar.ComputeFlattened()
    if _sample_count(flattened, label=label + " flattened") != flattened_count:
        raise ProductionUsdObservationError(
            f"USD primvar flattened sample count is inconsistent: {label}"
        )
    return _expanded_attribute(
        flattened,
        primvar.GetInterpolation(),
        counts=counts,
        point_indices=point_indices,
        label=label,
        surface_budget=surface_budget,
    )


def _expanded_attribute(
    raw_values: Any,
    interpolation: Any,
    *,
    counts: list[int],
    point_indices: list[int],
    label: str,
    surface_budget: _SurfaceOperationBudget,
) -> list[Any]:
    mode = str(interpolation)
    corner_count = len(point_indices)
    raw_count = _sample_count(raw_values, label=label)
    if raw_count == 0:
        raise ProductionUsdObservationError(f"Required USD attribute has no samples: {label}")
    valid = (
        (mode == "constant" and raw_count == 1)
        or (mode == "uniform" and raw_count == len(counts))
        or (
            mode in {"vertex", "varying"}
            and max(point_indices, default=-1) < raw_count
        )
        or (mode == "faceVarying" and raw_count == corner_count)
    )
    if not valid:
        raise ProductionUsdObservationError(
            f"USD attribute sample count does not match {mode} interpolation: {label}"
        )
    surface_budget.charge(
        raw_count + corner_count,
        label=f"{label} Python and expanded samples",
    )
    values = list(raw_values)
    if mode == "constant":
        return values * corner_count
    if mode == "uniform":
        return [
            value
            for value, count in zip(values, counts)
            for _ in range(count)
        ]
    if mode in {"vertex", "varying"}:
        return [values[index] for index in point_indices]
    if mode == "faceVarying":
        return values
    raise AssertionError("validated USD interpolation was not expanded")


def _sample_count(values: Any, *, label: str) -> int:
    if values is None:
        return 0
    try:
        count = len(values)
    except (TypeError, ValueError) as exc:
        raise ProductionUsdObservationError(
            f"USD attribute samples are unreadable: {label}"
        ) from exc
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ProductionUsdObservationError(
            f"USD attribute sample count is invalid: {label}"
        )
    return count


def _vector(value: Any, size: int, label: str) -> tuple[float, ...]:
    try:
        result = tuple(float(value[index]) for index in range(size))
    except (IndexError, TypeError, ValueError) as exc:
        raise ProductionUsdObservationError(
            f"USD {label} sample is malformed."
        ) from exc
    if not all(math.isfinite(component) for component in result):
        raise ProductionUsdObservationError(f"USD {label} sample is non-finite.")
    return result


def _length(value: tuple[float, ...]) -> float:
    return sum(component * component for component in value) ** 0.5


def _mesh_uv_fact(
    mesh: Any,
    primvars: Any,
    name: str,
    *,
    counts: list[int],
    point_indices: list[int],
    points: list[Any],
    surface_budget: _SurfaceOperationBudget,
    world_transforms: tuple[Any, ...] | None = None,
    Gf: Any | None = None,
) -> dict[str, Any]:
    primvar = primvars.GetPrimvar(name)
    usd_name = name
    if (not primvar or not primvar.IsDefined()) and name == "uv":
        primvar = primvars.GetPrimvar("st")
        usd_name = "st"
    expanded_values = _expanded_primvar(
        primvar,
        counts=counts,
        point_indices=point_indices,
        label=f"{mesh.GetPath()} {name}",
        surface_budget=surface_budget,
    )
    surface_budget.charge(
        len(expanded_values),
        label=f"{mesh.GetPath()} {name} UV tuples",
    )
    values = [
        _vector(value, 2, "UV")
        for value in expanded_values
    ]
    fan_triangles = sum(max(0, count - 2) for count in counts)
    triangle_tuple_operations = 5 * fan_triangles
    if world_transforms is None:
        triangle_tuple_operations += 3 * fan_triangles
    surface_budget.charge(
        2 * len(values) + triangle_tuple_operations,
        label=f"{mesh.GetPath()} {name} point and signature tuples",
    )
    if world_transforms is not None:
        surface_budget.charge(
            7 * fan_triangles * len(world_transforms),
            label=f"{mesh.GetPath()} {name} transformed triangle tuples",
        )
    signature_counts: Counter[tuple[tuple[float, float], ...]] = Counter()
    uv_area = 0.0
    world_area = 0.0
    offset = 0
    for count in counts:
        face_uvs = values[offset:offset + count]
        face_points = [
            _vector(points[index], 3, "point")
            for index in point_indices[offset:offset + count]
        ]
        offset += count
        for index in range(1, count - 1):
            signature = tuple(sorted(
                (round(value[0], 9), round(value[1], 9))
                for value in (
                    face_uvs[0],
                    face_uvs[index],
                    face_uvs[index + 1],
                )
            ))
            signature_counts[signature] += 1
            triangle_uv_area = _triangle_area_2d(
                face_uvs[0], face_uvs[index], face_uvs[index + 1],
            )
            if world_transforms is None:
                uv_area += triangle_uv_area
                world_area += _triangle_area_3d(
                    face_points[0], face_points[index], face_points[index + 1],
                )
                continue
            if Gf is None:
                raise ProductionUsdObservationError(
                    "USD world-space surface measurement requires Gf."
                )
            uv_area += triangle_uv_area * len(world_transforms)
            for transform in world_transforms:
                transformed = tuple(
                    _vector(
                        transform.Transform(Gf.Vec3d(*point)),
                        3,
                        "transformed point",
                    )
                    for point in (
                        face_points[0],
                        face_points[index],
                        face_points[index + 1],
                    )
                )
                world_area += _triangle_area_3d(*transformed)
    if world_area <= 1e-12:
        raise ProductionUsdObservationError(
            f"USD UV measurement requires nonzero mesh area: {mesh.GetPath()}"
        )
    return {
        "name": name,
        "usdName": usd_name,
        "interpolation": str(primvar.GetInterpolation()),
        "udimTiles": sorted({
            1001 + math.floor(value[0]) + math.floor(value[1]) * 10
            for value in values
            if 1001 + math.floor(value[0]) + math.floor(value[1]) * 10 >= 1001
        }),
        "signatureCounts": signature_counts,
        "uvArea": uv_area,
        "worldArea": world_area,
    }


def _triangle_area_2d(
    first: tuple[float, ...],
    second: tuple[float, ...],
    third: tuple[float, ...],
) -> float:
    return abs(
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    ) * 0.5


def _triangle_area_3d(
    first: tuple[float, ...],
    second: tuple[float, ...],
    third: tuple[float, ...],
) -> float:
    left = tuple(second[index] - first[index] for index in range(3))
    right = tuple(third[index] - first[index] for index in range(3))
    cross = (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )
    return 0.5 * _length(cross)
