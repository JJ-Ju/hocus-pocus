"""Authoritative geometry facts from a reopened, composed USD stage."""

from __future__ import annotations

import math
from collections import Counter
from itertools import chain
from typing import Any, Iterable, Mapping

from .production_usd_surface import (
    ProductionUsdObservationError as _SurfaceBudgetError,
    _SurfaceOperationBudget,
)


class ProductionUsdGeometryError(RuntimeError):
    """Raised when a contract-critical composed USD fact is unreadable."""


MAX_COMPOSED_PRIMS = 1_000_000
MAX_MESH_ARRAY_VALUES = 16_000_000
MAX_RENDERED_MESHES = 1_000_000
MAX_BOUND_POINT_TRANSFORMS = 30_000_000


def _canonicalize_right_handed_meshes(
    layer: Any,
    *,
    Usd: Any,
    UsdGeom: Any,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> int:
    """Preserve surface semantics while converting mesh winding to USD right-handed."""

    stage = Usd.Stage.Open(layer, load=Usd.Stage.LoadAll)
    if stage is None:
        raise ProductionUsdGeometryError(
            "Flattened USD layer cannot be opened for handedness canonicalization."
        )
    budget = operation_budget or _SurfaceOperationBudget()
    mesh_paths = _mesh_spec_paths(layer, operation_budget=budget)
    if not mesh_paths:
        raise ProductionUsdGeometryError(
            "Flattened USD layer contains no meshes to canonicalize."
        )
    converted = 0
    for path in mesh_paths:
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath(path))
        _require_static_mesh_semantics(mesh, UsdGeom=UsdGeom)
        orientation = str(
            mesh.GetOrientationAttr().Get() or UsdGeom.Tokens.rightHanded
        )
        if orientation == str(UsdGeom.Tokens.rightHanded):
            continue
        if orientation != str(UsdGeom.Tokens.leftHanded):
            raise ProductionUsdGeometryError(
                f"USD mesh has unsupported orientation at {path}: {orientation}"
            )
        _reverse_mesh_winding(
            mesh,
            UsdGeom=UsdGeom,
            operation_budget=budget,
        )
        mesh.GetOrientationAttr().Set(UsdGeom.Tokens.rightHanded)
        converted += 1
    return converted


def _mesh_spec_paths(
    layer: Any,
    *,
    operation_budget: _SurfaceOperationBudget,
) -> list[str]:
    pending = []
    for spec in layer.rootPrims:
        operation_budget.charge(1, label="flattened USD root prim-spec stack")
        pending.append(spec)
    paths = []
    visited = 0
    while pending:
        if visited >= MAX_COMPOSED_PRIMS:
            raise ProductionUsdGeometryError(
                "Flattened USD layer exceeds the bounded prim-spec limit."
            )
        visited += 1
        spec = pending.pop()
        if str(spec.typeName) == "Mesh":
            paths.append(str(spec.path))
        for child in spec.nameChildren:
            operation_budget.charge(1, label="flattened USD child prim-spec stack")
            pending.append(child)
    return paths


def _require_static_mesh_semantics(mesh: Any, *, UsdGeom: Any) -> None:
    attributes = [
        ("orientation", mesh.GetOrientationAttr()),
        ("faceVertexCounts", mesh.GetFaceVertexCountsAttr()),
        ("faceVertexIndices", mesh.GetFaceVertexIndicesAttr()),
        ("normals", mesh.GetNormalsAttr()),
    ]
    for primvar in UsdGeom.PrimvarsAPI(mesh).GetPrimvars():
        if str(primvar.GetInterpolation()) != "faceVarying":
            continue
        attributes.append(
            (f"primvars:{primvar.GetPrimvarName()}", primvar.GetAttr())
        )
        if primvar.IsIndexed():
            attributes.append(
                (
                    f"primvars:{primvar.GetPrimvarName()}:indices",
                    primvar.GetIndicesAttr(),
                )
            )
    for name, attribute in attributes:
        if attribute and attribute.GetTimeSamples():
            raise ProductionUsdGeometryError(
                "Time-sampled mesh semantics are unsupported at "
                f"{mesh.GetPath()}: {name}"
            )


def _reverse_mesh_winding(
    mesh: Any,
    *,
    UsdGeom: Any,
    operation_budget: _SurfaceOperationBudget,
) -> None:
    counts_value = mesh.GetFaceVertexCountsAttr().Get()
    indices_value = mesh.GetFaceVertexIndicesAttr().Get()
    if counts_value is None or indices_value is None:
        raise ProductionUsdGeometryError(
            f"USD mesh topology is unreadable at {mesh.GetPath()}."
        )
    if (
        len(counts_value) > MAX_MESH_ARRAY_VALUES
        or len(indices_value) > MAX_MESH_ARRAY_VALUES
        or any(type(value) is not int or value < 0 for value in counts_value)
    ):
        raise ProductionUsdGeometryError(
            f"USD mesh topology exceeds canonicalization bounds at {mesh.GetPath()}."
        )
    operation_budget.charge(
        len(counts_value),
        label=f"{mesh.GetPath()} canonical face-count list",
    )
    counts = list(counts_value)
    mesh.GetFaceVertexIndicesAttr().Set(
        _reverse_face_slices(
            indices_value,
            counts,
            label=str(mesh.GetPath()),
            operation_budget=operation_budget,
        )
    )
    if str(mesh.GetNormalsInterpolation()) == "faceVarying":
        values = mesh.GetNormalsAttr().Get()
        mesh.GetNormalsAttr().Set(
            _reverse_face_slices(
                values, counts, label=f"{mesh.GetPath()} normals",
                operation_budget=operation_budget,
            )
        )
    for primvar in UsdGeom.PrimvarsAPI(mesh).GetPrimvars():
        if str(primvar.GetInterpolation()) != "faceVarying":
            continue
        if primvar.IsIndexed():
            primvar.SetIndices(_reverse_face_slices(
                primvar.GetIndices(),
                counts,
                label=f"{mesh.GetPath()} {primvar.GetPrimvarName()} indices",
                operation_budget=operation_budget,
            ))
        else:
            primvar.Set(_reverse_face_slices(
                primvar.Get(),
                counts,
                label=f"{mesh.GetPath()} {primvar.GetPrimvarName()}",
                operation_budget=operation_budget,
            ))


def _reverse_face_slices(
    values: Any,
    counts: list[int],
    *,
    label: str,
    operation_budget: _SurfaceOperationBudget,
) -> list[Any]:
    if values is None or sum(counts) != len(values):
        raise ProductionUsdGeometryError(
            f"USD face-varying samples are inconsistent at {label}."
        )
    operation_budget.charge(
        len(values),
        label=f"{label} reversed face-varying list",
    )
    result = []
    offset = 0
    for count in counts:
        result.extend(reversed(values[offset:offset + count]))
        offset += count
    return result


def observe_composed_geometry(
    stage: Any,
    root_prim: Any,
    *,
    contract: Mapping[str, Any],
    instancing: Mapping[str, Any],
    Usd: Any,
    UsdGeom: Any,
    Gf: Any,
) -> dict[str, Any]:
    """Measure space, topology, and the complete visible rendered output."""

    facts, _ = _observe_composed_geometry_with_inventory(
        stage,
        root_prim,
        contract=contract,
        instancing=instancing,
        Usd=Usd,
        UsdGeom=UsdGeom,
        Gf=Gf,
        operation_budget=_SurfaceOperationBudget(),
    )
    public_facts = dict(facts)
    public_facts.pop("bounds")
    return public_facts


def _observe_composed_geometry_with_inventory(
    stage: Any,
    root_prim: Any,
    *,
    contract: Mapping[str, Any],
    instancing: Mapping[str, Any],
    Usd: Any,
    UsdGeom: Any,
    Gf: Any,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    composed = _bounded_prims(
        Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()),
        label="composed prims including instance proxies",
    )
    prototype_path = str(
        contract["delivery"]["instancing"]["prototypePrimPath"]
    )
    binding_paths = {
        str(item["primPath"]) for item in contract["usd"]["primBindings"]
    }
    render_binding_paths = {
        str(item["primPath"])
        for item in contract["usd"]["primBindings"]
        if item["role"] == "render"
    }
    visible_meshes = _visible_render_meshes(
        composed,
        prototype_path=prototype_path,
        UsdGeom=UsdGeom,
    )
    ordinary = [prim for prim in visible_meshes if not prim.IsInstanceProxy()]
    proxy_meshes = [prim for prim in visible_meshes if prim.IsInstanceProxy()]
    _require_contract_render_coverage(ordinary, render_binding_paths)
    source_meshes = []
    if instancing["representation"] == "point_instancer":
        source_meshes = _source_meshes(
            stage,
            prototype_path,
            instancing=instancing,
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
    render_inventory = _render_inventory(
        ordinary,
        proxy_meshes,
        stage=stage,
        source_meshes=source_meshes,
        point_instancers=[
            prim for prim in composed if prim.IsA(UsdGeom.PointInstancer)
        ],
        instancing=instancing,
        Usd=Usd,
        UsdGeom=UsdGeom,
        operation_budget=operation_budget,
    )
    if int(instancing["renderedInstanceCount"]) and not render_inventory:
        raise ProductionUsdGeometryError(
            "Composed stage contains no visible render mesh output."
        )
    topology_meshes = _topology_meshes(
        stage,
        composed,
        binding_paths=binding_paths,
        prototype_path=prototype_path,
        Usd=Usd,
        UsdGeom=UsdGeom,
    )
    for prim in topology_meshes:
        _require_static_mesh_semantics(UsdGeom.Mesh(prim), UsdGeom=UsdGeom)
    measurements = {
        str(prim.GetPath()): _mesh_measurement(
            prim,
            UsdGeom=UsdGeom,
            operation_budget=operation_budget,
        )
        for prim in topology_meshes
    }
    rendered = {
        identity: _mesh_measurement(
            item["prim"],
            UsdGeom=UsdGeom,
            operation_budget=operation_budget,
        )
        for identity, item in render_inventory.items()
    }
    return {
        "space": _space(stage, topology_meshes, UsdGeom=UsdGeom),
        "pivot": _pivot(stage, root_prim, Usd=Usd, UsdGeom=UsdGeom, Gf=Gf),
        "bounds": _render_bounds(
            render_inventory,
            allow_empty=int(instancing["renderedInstanceCount"]) == 0,
            Gf=Gf,
            UsdGeom=UsdGeom,
        ),
        "topology": _aggregate_topology(measurements.values()),
        "renderPolygons": sum(
            rendered[identity]["triangles"] * len(item["transforms"])
            for identity, item in render_inventory.items()
        ),
        "renderVertices": sum(
            rendered[identity]["vertices"] * len(item["transforms"])
            for identity, item in render_inventory.items()
        ),
        "unpackedVisibleMeshes": sum(
            not prim.IsInstance() for prim in ordinary
        ),
        "uniqueMeshes": len(render_inventory),
    }, render_inventory


def _render_inventory(
    ordinary: list[Any],
    proxies: list[Any],
    *,
    stage: Any,
    source_meshes: list[Any],
    point_instancers: list[Any],
    instancing: Mapping[str, Any],
    Usd: Any,
    UsdGeom: Any,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    xforms = UsdGeom.XformCache(Usd.TimeCode.Default())
    occurrence_count = len(ordinary) + len(proxies)
    _require_render_occurrence_capacity(0, occurrence_count)
    for prim in chain(ordinary, proxies):
        if operation_budget is not None:
            operation_budget.charge(
                1,
                label=f"{prim.GetPath()} render transform",
            )
        transform = xforms.GetLocalToWorldTransform(prim)
        _add_rendered_mesh(
            inventory,
            prim,
            transform,
        )
    if instancing["representation"] == "point_instancer":
        _require_render_occurrence_capacity(
            occurrence_count,
            int(instancing["renderedInstanceCount"]) * len(source_meshes),
        )
        prototype = stage.GetPrimAtPath(instancing["prototypePrimPath"])
        if operation_budget is not None:
            operation_budget.charge(1, label="point prototype world transform")
        prototype_world = xforms.GetLocalToWorldTransform(prototype)
        for instancer in point_instancers:
            if operation_budget is not None:
                operation_budget.charge(
                    1,
                    label=f"{instancer.GetPath()} instancer world transform",
                )
            instance_world = xforms.GetLocalToWorldTransform(instancer)
            instance_transforms = _point_instance_transforms(
                instancer,
                expected_prototype=instancing["prototypePrimPath"],
                Usd=Usd,
                UsdGeom=UsdGeom,
                operation_budget=operation_budget,
            )
            additional = len(instance_transforms) * len(source_meshes)
            _require_render_occurrence_capacity(occurrence_count, additional)
            occurrence_count += additional
            for instance_transform in instance_transforms:
                for prim in source_meshes:
                    if operation_budget is not None:
                        operation_budget.charge(
                            4,
                            label=f"{prim.GetPath()} prototype-relative transform",
                        )
                    mesh_relative = (
                        xforms.GetLocalToWorldTransform(prim)
                        * prototype_world.GetInverse()
                    )
                    _add_rendered_mesh(
                        inventory,
                        prim,
                        mesh_relative * instance_transform * instance_world,
                    )
    return inventory


def _require_render_occurrence_capacity(used: int, additional: int) -> None:
    if (
        isinstance(used, bool)
        or not isinstance(used, int)
        or used < 0
        or isinstance(additional, bool)
        or not isinstance(additional, int)
        or additional < 0
        or additional > MAX_RENDERED_MESHES - used
    ):
        raise ProductionUsdGeometryError(
            f"USD output exceeds {MAX_RENDERED_MESHES} rendered meshes."
        )


def _add_rendered_mesh(
    inventory: dict[str, dict[str, Any]],
    prim: Any,
    transform: Any,
) -> None:
    _require_finite_matrix(transform, label=str(prim.GetPath()))
    identity = _mesh_identity(prim)
    item = inventory.setdefault(
        identity,
        {"prim": prim, "prims": [], "transforms": []},
    )
    if all(str(value.GetPath()) != str(prim.GetPath()) for value in item["prims"]):
        item["prims"].append(prim)
    item["transforms"].append(transform)


def _point_instance_transforms(
    prim: Any,
    *,
    expected_prototype: str,
    Usd: Any,
    UsdGeom: Any,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> list[Any]:
    imageable = UsdGeom.Imageable(prim)
    if (
        str(imageable.ComputeVisibility()) == "invisible"
        or str(imageable.ComputePurpose() or "default") not in {
            "default", "render",
        }
    ):
        return []
    instancer = UsdGeom.PointInstancer(prim)
    targets = [str(path) for path in instancer.GetPrototypesRel().GetTargets()]
    if targets != [expected_prototype]:
        raise ProductionUsdGeometryError(
            f"Point instancer references the wrong prototype: {prim.GetPath()}"
        )
    time = Usd.TimeCode.Default()
    try:
        raw_indices = instancer.GetProtoIndicesAttr().Get() or ()
        index_count = len(raw_indices)
        if operation_budget is not None:
            operation_budget.charge(
                index_count,
                label=f"{prim.GetPath()} point-instancer index list",
            )
        indices = list(raw_indices)
        if operation_budget is not None:
            operation_budget.charge(
                index_count,
                label=f"{prim.GetPath()} point-instancer mask",
            )
        raw_mask = instancer.ComputeMaskAtTime(time)
        mask = list(raw_mask)
        if operation_budget is not None:
            operation_budget.charge(
                2 * index_count,
                label=f"{prim.GetPath()} point-instancer transform arrays",
            )
        transforms = list(instancer.ComputeInstanceTransformsAtTime(
            time,
            time,
            UsdGeom.PointInstancer.IncludeProtoXform,
            UsdGeom.PointInstancer.IgnoreMask,
        ))
    except _SurfaceBudgetError as exc:
        raise ProductionUsdGeometryError(str(exc)) from exc
    except Exception as exc:
        raise ProductionUsdGeometryError(
            f"Point instancer transforms are unreadable: {prim.GetPath()}"
        ) from exc
    effective_mask = mask or [True] * len(indices)
    if len(effective_mask) != len(indices) or len(transforms) != len(indices):
        raise ProductionUsdGeometryError(
            f"Point instancer transforms are inconsistent: {prim.GetPath()}"
        )
    if operation_budget is not None:
        operation_budget.charge(
            len(transforms),
            label=f"{prim.GetPath()} visible point-instancer transform list",
        )
    result = [
        transform
        for transform, visible in zip(transforms, effective_mask)
        if visible
    ]
    for transform in result:
        _require_finite_matrix(transform, label=str(prim.GetPath()))
    return result


def _require_finite_matrix(transform: Any, *, label: str) -> None:
    try:
        finite = all(
            math.isfinite(float(transform[row][column]))
            for row in range(4)
            for column in range(4)
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise ProductionUsdGeometryError(
            f"USD transform is unreadable at {label}."
        ) from exc
    if not finite:
        raise ProductionUsdGeometryError(
            f"USD transform is non-finite at {label}."
        )


def _render_bounds(
    inventory: Mapping[str, Mapping[str, Any]],
    *,
    allow_empty: bool,
    Gf: Any,
    UsdGeom: Any,
) -> dict[str, list[float]]:
    minimum = [math.inf] * 3
    maximum = [-math.inf] * 3
    operations = 0
    for item in inventory.values():
        raw_points = UsdGeom.Mesh(item["prim"]).GetPointsAttr().Get()
        if raw_points is None:
            raise ProductionUsdGeometryError(
                f"USD mesh points are unreadable at {item['prim'].GetPath()}."
            )
        point_count = len(raw_points)
        additional = point_count * len(item["transforms"])
        if additional > MAX_BOUND_POINT_TRANSFORMS - operations:
            raise ProductionUsdGeometryError(
                "USD point-derived bounds exceed their operation limit."
            )
        operations += additional
        points = [
            _point(value)
            for value in raw_points
        ]
        for transform in item["transforms"]:
            for point in points:
                world = transform.Transform(Gf.Vec3d(*point))
                values = _point(world)
                for index, value in enumerate(values):
                    minimum[index] = min(minimum[index], value)
                    maximum[index] = max(maximum[index], value)
    if math.isinf(minimum[0]):
        if allow_empty:
            return {"minimum": [0.0] * 3, "maximum": [0.0] * 3}
        raise ProductionUsdGeometryError(
            "USD publish root has no point-derived render bounds."
        )
    return {"minimum": minimum, "maximum": maximum}


def _space(stage: Any, meshes: list[Any], *, UsdGeom: Any) -> dict[str, Any]:
    meters = _authored_positive_number(stage, "metersPerUnit")
    if not stage.HasAuthoredMetadata("upAxis"):
        raise ProductionUsdGeometryError("USD stage has no authored upAxis.")
    up_axis = str(stage.GetMetadata("upAxis") or "").upper()
    if up_axis not in {"Y", "Z"}:
        raise ProductionUsdGeometryError(
            f"USD stage has unsupported upAxis: {up_axis or '<empty>'}"
        )
    authority = _hocus_authority(stage)
    forward_axis = authority.get("forwardAxis")
    if forward_axis not in {"X", "Y", "Z", "-X", "-Y", "-Z"}:
        raise ProductionUsdGeometryError(
            "USD stage has no valid authored hocuspocus.forwardAxis."
        )
    if str(forward_axis).lstrip("-") == up_axis:
        raise ProductionUsdGeometryError(
            "USD stage forwardAxis conflicts with its upAxis."
        )
    orientations = {
        str(UsdGeom.Mesh(prim).GetOrientationAttr().Get() or "rightHanded")
        for prim in meshes
    }
    if len(orientations) != 1:
        raise ProductionUsdGeometryError(
            "Delivered USD meshes do not have one authoritative handedness."
        )
    orientation = next(iter(orientations), "")
    handedness = {"rightHanded": "right", "leftHanded": "left"}.get(orientation)
    if handedness is None:
        raise ProductionUsdGeometryError(
            f"Delivered USD mesh orientation is unsupported: {orientation}"
        )
    return {
        "metersPerUnit": meters,
        "upAxis": up_axis,
        "forwardAxis": forward_axis,
        "handedness": handedness,
    }


def _authored_positive_number(stage: Any, name: str) -> float:
    if not stage.HasAuthoredMetadata(name):
        raise ProductionUsdGeometryError(
            f"USD stage has no authored {name}."
        )
    value = stage.GetMetadata(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProductionUsdGeometryError(
            f"USD stage {name} is not numeric."
        )
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ProductionUsdGeometryError(
            f"USD stage {name} must be finite and positive."
        )
    return result


def _pivot(
    stage: Any,
    root_prim: Any,
    *,
    Usd: Any,
    UsdGeom: Any,
    Gf: Any,
) -> dict[str, Any]:
    mode = _hocus_authority(stage).get("pivotMode")
    if mode not in {"origin", "center", "base", "explicit"}:
        raise ProductionUsdGeometryError(
            "USD stage has no valid authored hocuspocus.pivotMode."
        )
    try:
        transform = UsdGeom.Xformable(root_prim).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()
        )
        point = transform.Transform(Gf.Vec3d(0.0, 0.0, 0.0))
        result = [float(point[index]) for index in range(3)]
    except Exception as exc:
        raise ProductionUsdGeometryError(
            "USD publish-root pivot is unreadable."
        ) from exc
    if not all(math.isfinite(value) for value in result):
        raise ProductionUsdGeometryError(
            "USD publish-root pivot is non-finite."
        )
    return {"mode": mode, "position": result}


def _hocus_authority(stage: Any) -> Mapping[str, Any]:
    layer = stage.GetRootLayer()
    data = layer.customLayerData if layer is not None else None
    authority = data.get("hocuspocus") if isinstance(data, Mapping) else None
    if not isinstance(authority, Mapping):
        raise ProductionUsdGeometryError(
            "USD root layer has no authored hocuspocus authority metadata."
        )
    return authority


def _visible_render_meshes(
    prims: Iterable[Any],
    *,
    prototype_path: str,
    UsdGeom: Any,
) -> list[Any]:
    result = []
    for prim in prims:
        path = str(prim.GetPath())
        if _at_or_below(path, prototype_path):
            continue
        if not prim.IsA(UsdGeom.Boundable):
            continue
        imageable = UsdGeom.Imageable(prim)
        visible = str(imageable.ComputeVisibility()) != "invisible"
        renderable = str(imageable.ComputePurpose() or "default") in {
            "default", "render",
        }
        if not visible or not renderable:
            continue
        if prim.IsA(UsdGeom.PointInstancer):
            continue
        if not prim.IsA(UsdGeom.Mesh):
            raise ProductionUsdGeometryError(
                "Visible renderable geometry cannot be measured as polygons: "
                f"{path}"
            )
        result.append(prim)
    return result


def _require_contract_render_coverage(
    meshes: Iterable[Any],
    render_roots: set[str],
) -> None:
    for prim in meshes:
        path = str(prim.GetPath())
        if prim.IsInstance() or any(
            _at_or_below(path, root) for root in render_roots
        ):
            continue
        raise ProductionUsdGeometryError(
            f"Visible render mesh is not covered by a contract binding: {path}"
        )


def _source_meshes(
    stage: Any,
    prototype_path: str,
    *,
    instancing: Mapping[str, Any],
    Usd: Any,
    UsdGeom: Any,
) -> list[Any]:
    if (
        instancing["representation"] == "point_instancer"
        and (
            instancing["prototypePrimPath"] != prototype_path
            or instancing["prototypePaths"] != [prototype_path]
        )
    ):
        raise ProductionUsdGeometryError(
            "USD point-instancer prototype relationship is inconsistent."
        )
    prototype = stage.GetPrimAtPath(prototype_path)
    if not prototype or not prototype.IsValid():
        raise ProductionUsdGeometryError(
            f"USD instance prototype is absent: {prototype_path}"
        )
    meshes = [
        prim
        for prim in Usd.PrimRange(prototype)
        if prim.IsA(UsdGeom.Mesh)
        and str(UsdGeom.Imageable(prim).ComputeVisibility()) != "invisible"
        and str(UsdGeom.Imageable(prim).ComputePurpose() or "default")
        in {"default", "render"}
    ]
    if not meshes:
        raise ProductionUsdGeometryError(
            "USD instance prototype contains no visible render mesh: "
            f"{prototype_path}"
        )
    return meshes


def _topology_meshes(
    stage: Any,
    composed: list[Any],
    *,
    binding_paths: set[str],
    prototype_path: str,
    Usd: Any,
    UsdGeom: Any,
) -> list[Any]:
    paths = set()
    for path in {*binding_paths, prototype_path}:
        root = stage.GetPrimAtPath(path)
        if not root or not root.IsValid():
            raise ProductionUsdGeometryError(
                f"USD topology root is absent: {path}"
            )
        paths.update(
            str(prim.GetPath())
            for prim in Usd.PrimRange(root)
            if prim.IsA(UsdGeom.Mesh)
        )
    paths.update(
        str(prim.GetPath())
        for prim in composed
        if prim.IsA(UsdGeom.Mesh)
        and not prim.IsInstanceProxy()
        and not _at_or_below(str(prim.GetPath()), prototype_path)
        and str(UsdGeom.Imageable(prim).ComputeVisibility()) != "invisible"
        and str(UsdGeom.Imageable(prim).ComputePurpose() or "default")
        in {"default", "render"}
    )
    meshes = [stage.GetPrimAtPath(path) for path in sorted(paths)]
    if not meshes:
        raise ProductionUsdGeometryError(
            "Delivered USD stage contains no topology-bearing meshes."
        )
    return meshes


def _mesh_measurement(
    prim: Any,
    *,
    UsdGeom: Any,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> dict[str, Any]:
    mesh = UsdGeom.Mesh(prim)
    try:
        counts_value = mesh.GetFaceVertexCountsAttr().Get()
        indices_value = mesh.GetFaceVertexIndicesAttr().Get()
        points_value = mesh.GetPointsAttr().Get()
        if counts_value is None or indices_value is None or points_value is None:
            raise ValueError("required mesh arrays are absent")
        for label, value in (
            ("face counts", counts_value),
            ("face indices", indices_value),
            ("points", points_value),
        ):
            if len(value) > MAX_MESH_ARRAY_VALUES:
                raise ValueError(
                    f"mesh {label} exceed {MAX_MESH_ARRAY_VALUES} values"
                )
        if operation_budget is not None:
            operation_budget.charge(
                (
                    len(counts_value)
                    + len(indices_value)
                    + 2 * len(points_value)
                    + 5 * len(indices_value)
                ),
                label=f"{prim.GetPath()} topology measurement working set",
            )
        counts = list(counts_value)
        indices = list(indices_value)
        points = [_point(value) for value in points_value]
        if not points or any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("mesh counts or points are invalid")
        if any(type(value) is not int or not 0 <= value < len(points) for value in indices):
            raise ValueError("mesh indices are invalid")
        if sum(counts) != len(indices):
            raise ValueError("mesh face arrays are inconsistent")
    except _SurfaceBudgetError as exc:
        raise ProductionUsdGeometryError(str(exc)) from exc
    except Exception as exc:
        raise ProductionUsdGeometryError(
            f"Mesh topology is unreadable: {prim.GetPath()}"
        ) from exc
    quality = _mesh_topology_quality(
        counts,
        indices,
        points,
        operation_budget=operation_budget,
    )
    return {
        "vertices": len(points),
        "polygons": len(counts),
        "triangles": sum(max(0, count - 2) for count in counts),
        **quality,
    }


def _mesh_topology_quality(
    counts: list[int],
    indices: list[int],
    points: list[tuple[float, float, float]],
    *,
    operation_budget: _SurfaceOperationBudget | None = None,
) -> dict[str, Any]:
    edges: Counter[tuple[int, int]] = Counter()
    degenerate = 0
    offset = 0
    for count in counts:
        face = indices[offset:offset + count]
        offset += count
        face_edges = [
            tuple(sorted((face[index], face[(index + 1) % count])))
            for index in range(count)
        ] if count else []
        bad_edge = any(left == right for left, right in face_edges)
        bad_edge = bad_edge or len(set(face_edges)) != len(face_edges)
        bad_area = _face_area(face, points) <= 1e-12
        if count < 3 or len(set(face)) < 3 or bad_edge or bad_area:
            degenerate += 1
        edges.update(face_edges)
    if operation_budget is not None:
        operation_budget.charge(
            len(edges),
            label="USD topology edge-incidence list",
        )
    incidence = list(edges.values())
    return {
        "manifold": degenerate == 0 and all(value <= 2 for value in incidence),
        "watertight": (
            degenerate == 0
            and bool(incidence)
            and all(value == 2 for value in incidence)
        ),
        "degenerateCount": degenerate,
        "maxNgonSides": max(counts, default=0),
    }


def _face_area(
    face: list[int],
    points: list[tuple[float, float, float]],
) -> float:
    if len(face) < 3:
        return 0.0
    origin = points[face[0]]
    return sum(
        _triangle_area(origin, points[face[index]], points[face[index + 1]])
        for index in range(1, len(face) - 1)
    )


def _triangle_area(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> float:
    left = tuple(second[index] - first[index] for index in range(3))
    right = tuple(third[index] - first[index] for index in range(3))
    cross = (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )
    return 0.5 * math.sqrt(sum(value * value for value in cross))


def _point(value: Any) -> tuple[float, float, float]:
    try:
        result = tuple(float(value[index]) for index in range(3))
    except (IndexError, TypeError, ValueError) as exc:
        raise ProductionUsdGeometryError("USD mesh point is malformed.") from exc
    if not all(math.isfinite(component) for component in result):
        raise ProductionUsdGeometryError("USD mesh point is non-finite.")
    return result


def _aggregate_topology(values: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(values)
    return {
        "manifold": all(bool(item["manifold"]) for item in items),
        "watertight": all(bool(item["watertight"]) for item in items),
        "degenerateCount": sum(int(item["degenerateCount"]) for item in items),
        "maxNgonSides": max(
            (int(item["maxNgonSides"]) for item in items),
            default=0,
        ),
    }


def _mesh_identity(prim: Any) -> str:
    if prim.IsInstanceProxy():
        source = prim.GetPrimInPrototype()
        if not source or not source.IsValid():
            raise ProductionUsdGeometryError(
                f"Instance proxy has no prototype identity: {prim.GetPath()}"
            )
        return str(source.GetPath())
    if prim.IsInstance():
        prototype = prim.GetPrototype()
        if not prototype or not prototype.IsValid():
            raise ProductionUsdGeometryError(
                f"Instance mesh has no prototype identity: {prim.GetPath()}"
            )
        return str(prototype.GetPath())
    return str(prim.GetPath())


def _at_or_below(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _bounded_prims(prims: Iterable[Any], *, label: str) -> list[Any]:
    result = []
    for prim in prims:
        if len(result) >= MAX_COMPOSED_PRIMS:
            raise ProductionUsdGeometryError(
                f"USD stage exceeds {MAX_COMPOSED_PRIMS} {label}."
            )
        result.append(prim)
    return result


__all__ = [
    "ProductionUsdGeometryError",
    "observe_composed_geometry",
]
