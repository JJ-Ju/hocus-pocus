"""Fail-closed facts from a serialized, reopened production USD asset."""

from __future__ import annotations

import copy
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .production_usd_dependencies import (
    UsdDependencyError,
    asset_dependencies,
)
from .production_usd_geometry import (
    ProductionUsdGeometryError,
    _observe_composed_geometry_with_inventory,
    _require_static_mesh_semantics,
)
from .production_usd_surface import (
    MAX_SURFACE_OPERATIONS as MAX_SURFACE_OPERATIONS,
    ProductionUsdObservationError as ProductionUsdObservationError,
    _SurfaceOperationBudget as _SurfaceOperationBudget,
    _mesh_surface_fact as _mesh_surface_fact,
    _mesh_uv_fact as _mesh_uv_fact,
    _vector as _vector,
)

MAX_USD_BYTES = 64 * 1024 * 1024
MAX_USD_PRIMS = 1_000_000
MAX_USD_INSTANCES = 1_000_000
MAX_USD_MESH_VALUES = 16_000_000


def observe_production_usda(
    path: str | os.PathLike[str],
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Reopen a bounded USDA and measure the facts used for asset acceptance."""

    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    usd_path = Path(path).resolve()
    if not usd_path.is_file():
        raise ProductionUsdObservationError(f"USD output does not exist: {usd_path}")
    output_bytes = usd_path.stat().st_size
    if output_bytes > MAX_USD_BYTES:
        raise ProductionUsdObservationError(
            f"USD output exceeds {MAX_USD_BYTES} bytes: {usd_path}"
        )
    stage = Usd.Stage.Open(str(usd_path), load=Usd.Stage.LoadAll)
    if stage is None:
        raise ProductionUsdObservationError(f"USD output cannot be reopened: {usd_path}")
    root_layer = stage.GetRootLayer()
    if root_layer is None or root_layer.anonymous:
        raise ProductionUsdObservationError("Reopened USD has no file-backed root layer.")
    default_prim = stage.GetDefaultPrim()
    default_path = str(default_prim.GetPath()) if default_prim else None
    if default_path is None:
        raise ProductionUsdObservationError("Reopened USD has no authored default prim.")

    usd_contract = contract["usd"]
    publish = usd_contract["publish"]
    root_path = publish["rootPrim"]
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim or not root_prim.IsValid():
        raise ProductionUsdObservationError(f"USD publish root is absent: {root_path}")

    prims = _bounded_stage_prims(stage.Traverse())
    required_uv_names = tuple(
        uv["name"]
        for uv in contract["surface"]["uvSets"]
        if uv["required"]
    )
    surface_budget = _SurfaceOperationBudget()
    xforms = UsdGeom.XformCache(Usd.TimeCode.Default())
    bindings = [
        _binding_fact(
            stage,
            item,
            uv_names=required_uv_names,
            surface_budget=surface_budget,
            Usd=Usd,
            UsdGeom=UsdGeom,
            UsdShade=UsdShade,
            Gf=Gf,
            xforms=xforms,
        )
        for item in usd_contract["primBindings"]
    ]
    material_paths = sorted({
        item["materialPrimPath"]
        for item in bindings
        if item["materialPrimPath"] is not None
    })
    for material_path in material_paths:
        material_prim = stage.GetPrimAtPath(material_path)
        if not material_prim or not material_prim.IsA(UsdShade.Material):
            raise ProductionUsdObservationError(
                f"Bound material prim is absent or not a Material: {material_path}"
            )

    instancing = _instancing_fact(
        prims,
        contract["delivery"]["instancing"],
        Usd=Usd,
        UsdGeom=UsdGeom,
    )
    try:
        composed_geometry, render_inventory = _observe_composed_geometry_with_inventory(
            stage,
            root_prim,
            contract=contract,
            instancing=instancing,
            Usd=Usd,
            UsdGeom=UsdGeom,
            Gf=Gf,
            operation_budget=surface_budget,
        )
    except ProductionUsdGeometryError as exc:
        raise ProductionUsdObservationError(str(exc)) from exc
    if (
        composed_geometry["pivot"]["mode"]
        != contract["geometry"]["pivot"]["mode"]
    ):
        raise ProductionUsdObservationError(
            "Final USD pivot mode conflicts with the asset contract."
        )
    instancing["unpackedInstances"] = composed_geometry["unpackedVisibleMeshes"]
    instancing["uniqueMeshes"] = composed_geometry["uniqueMeshes"]
    bounds = composed_geometry["bounds"]
    asset_dependencies = _asset_dependencies(
        stage,
        usd_path,
        contract=contract,
        Sdf=Sdf,
    )
    variant_selections = sorted({
        (name, prim.GetVariantSet(name).GetVariantSelection())
        for prim in prims
        for name in prim.GetVariantSets().GetNames()
        if prim.GetVariantSet(name).GetVariantSelection()
    })
    publish_arc = _publish_arc(root_prim)
    render_surface = _render_surface_facts(
        bindings,
        render_inventory=render_inventory,
        uv_names=required_uv_names,
        surface_budget=surface_budget,
        UsdGeom=UsdGeom,
        UsdShade=UsdShade,
        Gf=Gf,
    )
    return {
        "path": str(usd_path),
        "bytes": output_bytes,
        "primCount": len(prims),
        "names": sorted({str(prim.GetName()) for prim in prims}),
        "bounds": bounds,
        "pivot": composed_geometry["pivot"],
        "space": composed_geometry["space"],
        "topology": composed_geometry["topology"],
        "rootPrim": root_path,
        "defaultPrim": default_path,
        "kind": str(Usd.ModelAPI(root_prim).GetKind() or ""),
        "purpose": _purpose(root_prim, UsdGeom),
        "publishArc": publish_arc,
        "variantSelections": [
            {"name": name, "value": value}
            for name, value in variant_selections
        ],
        "primBindings": [
            {key: value for key, value in item.items() if key != "_meshSurface"}
            for item in bindings
        ],
        "normals": render_surface["normals"],
        "tangents": render_surface["tangents"],
        "uvSets": render_surface["uvSets"],
        "materialSlots": [path.rsplit("/", 1)[-1] for path in material_paths],
        "instancing": instancing,
        "renderPolygons": composed_geometry["renderPolygons"],
        "renderVertices": composed_geometry["renderVertices"],
        "assetDependencies": asset_dependencies,
        "contractDependencies": [
            {
                key: item[key]
                for key in ("id", "kind", "version", "digest")
            }
            for item in asset_dependencies
        ],
        "textureCount": sum(
            item["kind"] == "texture" for item in asset_dependencies
        ),
        "textureBytes": sum(
            item["byteLength"]
            for item in asset_dependencies
            if item["kind"] == "texture"
        ),
    }


def project_asset_contract_observation(
    base_observation: Mapping[str, Any],
    final_usd: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace live-SOP projections with reopened final-asset facts."""

    observed = copy.deepcopy(dict(base_observation))
    bindings = list(final_usd["primBindings"])
    render_bindings = [item for item in bindings if item["role"] == "render"]
    collision_bindings = [item for item in bindings if item["role"] == "collision"]
    if len(collision_bindings) != 1:
        raise ProductionUsdObservationError(
            "Final USD must declare exactly one collision prim binding."
        )
    collision = collision_bindings[0]
    observed["surface"]["materialSlots"] = list(final_usd["materialSlots"])
    observed["surface"]["textureBytes"] = int(final_usd["textureBytes"])
    dependencies = {
        (item["kind"], item["id"]): copy.deepcopy(item)
        for item in observed["dependencies"]
    }
    for item in final_usd["contractDependencies"]:
        key = (item["kind"], item["id"])
        if key in dependencies and dependencies[key] != item:
            raise ProductionUsdObservationError(
                "Final USD dependency conflicts with live dependency evidence."
            )
        dependencies[key] = copy.deepcopy(item)
    observed["dependencies"] = [
        dependencies[key] for key in sorted(dependencies)
    ]
    observed["names"] = sorted(
        set(observed["names"]) | set(final_usd["names"])
    )
    observed["space"] = copy.deepcopy(final_usd["space"])
    observed["geometry"]["bounds"] = copy.deepcopy(final_usd["bounds"])
    observed["geometry"]["pivot"] = copy.deepcopy(
        final_usd["pivot"]["position"]
    )
    observed["geometry"]["topology"] = copy.deepcopy(final_usd["topology"])
    observed["geometry"]["normals"] = {
        key: final_usd["normals"][key]
        for key in ("present", "consistent", "maxUnitLengthError")
    }
    observed["geometry"]["tangents"] = {
        key: final_usd["tangents"][key]
        for key in ("present", "orthogonal", "maxOrthogonalError")
    }
    observed["surface"]["uvSets"] = [
        {
            key: item[key]
            for key in (
                "name", "udimTiles", "duplicateUvTriangleCount", "texelDensity",
            )
        }
        for item in final_usd["uvSets"]
    ]
    observed["delivery"]["lods"] = [
        {
            "name": item["name"],
            "triangles": item["triangles"],
            "vertices": item["vertices"],
            "relativeTriangleReduction": {
                "status": "measured",
                "value": _relative_reduction(item, render_bindings),
            },
        }
        for item in render_bindings
    ]
    observed["delivery"]["collision"] = {
        "mode": "mesh",
        "convex": False,
        "primitives": collision["meshCount"],
        "triangles": collision["triangles"],
    }
    observed["delivery"]["instancing"] = {
        key: final_usd["instancing"][key]
        for key in (
            "used", "prototypePrimPath", "representation",
            "uniqueMeshes", "unpackedInstances",
        )
    }
    for metric in observed["delivery"]["platformMetrics"]:
        metric["triangles"] = int(final_usd["renderPolygons"])
        metric["vertices"] = int(final_usd["renderVertices"])
        metric["textureBytes"] = int(final_usd["textureBytes"])
        metric["materialSlots"] = len(final_usd["materialSlots"])
        metric["instances"] = int(
            final_usd["instancing"]["renderedInstanceCount"]
        )
    observed["usd"] = {
        "kind": final_usd["kind"],
        "purpose": final_usd["purpose"],
        "variantSelections": copy.deepcopy(final_usd["variantSelections"]),
        "rootPrim": final_usd["rootPrim"],
        "defaultPrim": final_usd["defaultPrim"],
        "payload": final_usd["publishArc"],
        "primBindings": [
            {
                key: item[key]
                for key in (
                    "name", "role", "primPath", "purpose",
                    "visibility", "materialPrimPath",
                )
            }
            for item in bindings
        ],
    }
    return observed


def _instancing_fact(
    prims: list[Any],
    contract: Mapping[str, Any],
    *,
    Usd: Any,
    UsdGeom: Any,
) -> dict[str, Any]:
    native = [prim for prim in prims if prim.IsInstance()]
    point = [prim for prim in prims if prim.IsA(UsdGeom.PointInstancer)]
    representation = contract["representation"]
    if native and point:
        raise ProductionUsdObservationError(
            "Final USD mixes native instances and point instancers."
        )
    if representation == "native_instance":
        return _native_instancing_fact(
            native,
            contract["prototypePrimPath"],
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
    return _point_instancing_fact(
        point,
        contract["prototypePrimPath"],
        Usd=Usd,
        UsdGeom=UsdGeom,
    )


def _bounded_stage_prims(prims: Iterable[Any]) -> list[Any]:
    result = []
    for prim in prims:
        if len(result) >= MAX_USD_PRIMS:
            raise ProductionUsdObservationError(
                f"USD stage exceeds {MAX_USD_PRIMS} composed prims."
            )
        result.append(prim)
    return result


def _native_instancing_fact(
    instances: list[Any],
    expected_prototype: str,
    *,
    Usd: Any,
    UsdGeom: Any,
) -> dict[str, Any]:
    if not instances:
        raise ProductionUsdObservationError(
            "Final USD contains no authored native instances."
        )
    targets = []
    internal_prototypes = set()
    prototype_prims: dict[str, Any] = {}
    visible = 0
    for prim in instances:
        reference_op = prim.GetMetadata("references")
        references = (
            reference_op.GetAppliedItems()
            if reference_op is not None else ()
        )
        internal = [
            reference
            for reference in references
            if not str(reference.assetPath) and str(reference.primPath)
        ]
        if len(internal) != 1:
            raise ProductionUsdObservationError(
                f"Native instance must author one internal reference: {prim.GetPath()}"
            )
        target = str(internal[0].primPath)
        if target != expected_prototype:
            raise ProductionUsdObservationError(
                f"Native instance references the wrong prototype: {prim.GetPath()}"
            )
        targets.append(target)
    for prim in instances:
        prototype = prim.GetPrototype()
        if not prototype or not prototype.IsValid():
            raise ProductionUsdObservationError(
                f"Native instance has no composed internal prototype: {prim.GetPath()}"
            )
        prototype_path = str(prototype.GetPath())
        internal_prototypes.add(prototype_path)
        prototype_prims[prototype_path] = prototype
        if str(UsdGeom.Imageable(prim).ComputeVisibility()) != "invisible":
            visible += 1
    if len(internal_prototypes) != 1:
        raise ProductionUsdObservationError(
            "Native instances do not share one composed internal prototype."
        )
    actual_path = next(iter(internal_prototypes))
    if not _prototype_tree_has_readable_mesh(
        prototype_prims[actual_path], Usd=Usd, UsdGeom=UsdGeom,
    ):
        raise ProductionUsdObservationError(
            f"Native internal prototype has no readable mesh: {actual_path}"
        )
    return {
        "used": True,
        "representation": "native_instance",
        "prototypePrimPath": expected_prototype,
        "instanceCount": len(instances),
        "renderedInstanceCount": visible,
        "uniqueMeshes": len(set(targets)),
        "unpackedInstances": 0,
        "prototypePaths": sorted(internal_prototypes),
    }


def _point_instancing_fact(
    instancers: list[Any],
    expected_prototype: str,
    *,
    Usd: Any,
    UsdGeom: Any,
) -> dict[str, Any]:
    if not instancers:
        raise ProductionUsdObservationError(
            "Final USD contains no authored point instancer."
        )
    targets = set()
    instance_count = 0
    visible_count = 0
    for prim in instancers:
        count, visible = _point_instancer_measurement(
            prim,
            expected_prototype,
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
        targets.add(expected_prototype)
        instance_count += count
        visible_count += visible
    return {
        "used": True,
        "representation": "point_instancer",
        "prototypePrimPath": expected_prototype,
        "instanceCount": instance_count,
        "renderedInstanceCount": visible_count,
        "uniqueMeshes": len(targets),
        "unpackedInstances": 0,
        "prototypePaths": sorted(targets),
    }


def _point_instancer_measurement(
    prim: Any,
    expected_prototype: str,
    *,
    Usd: Any,
    UsdGeom: Any,
) -> tuple[int, int]:
    instancer = UsdGeom.PointInstancer(prim)
    targets = [
        str(path) for path in instancer.GetPrototypesRel().GetTargets()
    ]
    if targets != [expected_prototype]:
        raise ProductionUsdObservationError(
            f"Point instancer references the wrong prototype: {prim.GetPath()}"
        )
    _require_readable_mesh_prototype(
        prim, expected_prototype, Usd=Usd, UsdGeom=UsdGeom,
    )
    indices, mask = _point_instancer_arrays(
        instancer,
        target_count=len(targets),
        Usd=Usd,
        UsdGeom=UsdGeom,
    )
    visible = sum(bool(value) for value in mask)
    imageable = UsdGeom.Imageable(prim)
    if (
        str(imageable.ComputeVisibility()) == "invisible"
        or str(imageable.ComputePurpose() or "default") not in {
            "default", "render",
        }
    ):
        visible = 0
    return len(indices), visible


def _require_readable_mesh_prototype(
    prim: Any,
    path: str,
    *,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    prototype = prim.GetStage().GetPrimAtPath(path)
    readable_mesh = bool(
        prototype
        and prototype.IsValid()
        and _prototype_tree_has_readable_mesh(
            prototype, Usd=Usd, UsdGeom=UsdGeom,
        )
    )
    if not readable_mesh:
        raise ProductionUsdObservationError(
            f"Point instancer prototype has no readable mesh: {path}"
        )


def _prototype_tree_has_readable_mesh(
    prototype: Any,
    *,
    Usd: Any,
    UsdGeom: Any,
) -> bool:
    for index, candidate in enumerate(Usd.PrimRange(prototype)):
        if index >= MAX_USD_PRIMS:
            return False
        if _prototype_mesh_is_readable(candidate, UsdGeom=UsdGeom):
            return True
    return False


def _prototype_mesh_is_readable(candidate: Any, *, UsdGeom: Any) -> bool:
    if not candidate.IsA(UsdGeom.Mesh):
        return False
    try:
        mesh = UsdGeom.Mesh(candidate)
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        points = mesh.GetPointsAttr().Get()
        if counts is None or indices is None or points is None:
            return False
        if any(
            len(value) > MAX_USD_MESH_VALUES
            for value in (counts, indices, points)
        ):
            return False
        return (
            bool(points)
            and all(type(value) is int and value >= 0 for value in counts)
            and all(
                type(value) is int and 0 <= value < len(points)
                for value in indices
            )
            and sum(counts) == len(indices)
        )
    except Exception:
        return False


def _point_instancer_arrays(
    instancer: Any,
    *,
    target_count: int,
    Usd: Any,
    UsdGeom: Any,
) -> tuple[list[int], list[bool]]:
    prim_path = instancer.GetPrim().GetPath()
    try:
        indices_value = instancer.GetProtoIndicesAttr().Get()
        positions_value = instancer.GetPositionsAttr().Get()
        if indices_value is None or positions_value is None:
            raise ValueError("required arrays are unreadable")
        if (
            len(indices_value) > MAX_USD_INSTANCES
            or len(positions_value) > MAX_USD_INSTANCES
        ):
            raise ValueError(
                f"point-instancer arrays exceed {MAX_USD_INSTANCES} values"
            )
        indices = list(indices_value)
        positions = list(positions_value)
        if not indices:
            raise ValueError("protoIndices are empty")
        if any(
            type(index) is not int or not 0 <= index < target_count
            for index in indices
        ):
            raise ValueError("protoIndices are invalid")
        if len(positions) != len(indices):
            raise ValueError("positions do not match protoIndices")
        for position in positions:
            _vector(position, 3, "point-instancer position")
        time = Usd.TimeCode.Default()
        mask = list(instancer.ComputeMaskAtTime(time))
        transforms = list(instancer.ComputeInstanceTransformsAtTime(
            time,
            time,
            UsdGeom.PointInstancer.IncludeProtoXform,
            UsdGeom.PointInstancer.IgnoreMask,
        ))
    except Exception as exc:
        raise ProductionUsdObservationError(
            f"Point instancer data is unreadable: {prim_path}"
        ) from exc
    effective_mask = mask or [True] * len(indices)
    if len(effective_mask) != len(indices):
        raise ProductionUsdObservationError(
            f"Point instancer mask length is inconsistent: {prim_path}"
        )
    if len(transforms) != len(indices):
        raise ProductionUsdObservationError(
            f"Point instancer transforms are inconsistent: {prim_path}"
        )
    for transform in transforms:
        _require_finite_transform(transform, prim_path)
    return indices, effective_mask


def _require_finite_transform(transform: Any, prim_path: Any) -> None:
    try:
        finite = all(
            math.isfinite(float(transform[row][column]))
            for row in range(4)
            for column in range(4)
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise ProductionUsdObservationError(
            f"Point instancer transform is unreadable: {prim_path}"
        ) from exc
    if not finite:
        raise ProductionUsdObservationError(
            f"Point instancer transform is non-finite: {prim_path}"
        )


def _binding_fact(
    stage: Any,
    contract: Mapping[str, Any],
    *,
    uv_names: tuple[str, ...],
    surface_budget: _SurfaceOperationBudget,
    Usd: Any,
    UsdGeom: Any,
    UsdShade: Any,
    Gf: Any,
    xforms: Any,
) -> dict[str, Any]:
    prim_path = contract["primPath"]
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ProductionUsdObservationError(
            f"Declared USD prim binding is absent: {prim_path}"
        )
    material_path = _bound_material_path(prim, UsdShade=UsdShade)
    meshes = [
        candidate
        for candidate in Usd.PrimRange(prim)
        if candidate.IsA(UsdGeom.Mesh)
    ]
    if not meshes:
        raise ProductionUsdObservationError(
            f"Declared USD prim binding contains no mesh: {prim_path}"
        )
    triangles = 0
    vertices = 0
    mesh_surface = []
    for mesh_prim in meshes:
        mesh_material_path = _bound_material_path(
            mesh_prim,
            UsdShade=UsdShade,
        )
        if mesh_material_path != contract["materialPrimPath"]:
            raise ProductionUsdObservationError(
                "Declared USD binding mesh resolves an unexpected material: "
                f"{mesh_prim.GetPath()}"
            )
        mesh = UsdGeom.Mesh(mesh_prim)
        try:
            _require_static_mesh_semantics(mesh, UsdGeom=UsdGeom)
        except ProductionUsdGeometryError as exc:
            raise ProductionUsdObservationError(str(exc)) from exc
        counts = mesh.GetFaceVertexCountsAttr().Get()
        points = mesh.GetPointsAttr().Get()
        if counts is None or points is None:
            raise ProductionUsdObservationError(
                f"Mesh topology is unreadable: {mesh_prim.GetPath()}"
            )
        triangles += sum(max(0, int(count) - 2) for count in counts)
        vertices += len(points)
        surface_budget.charge(
            2,
            label=f"{mesh_prim.GetPath()} declared world-transform tuple",
        )
        world_transform = xforms.GetLocalToWorldTransform(mesh_prim)
        mesh_surface.append(
            {
                **_mesh_surface_fact(
                    mesh,
                    uv_names=uv_names,
                    require_frames=contract["role"] == "render",
                    surface_budget=surface_budget,
                    UsdGeom=UsdGeom,
                    world_transforms=(world_transform,),
                    Gf=Gf,
                ),
                "materialPrimPath": mesh_material_path,
            }
        )
    return {
        "name": contract["name"],
        "role": contract["role"],
        "primPath": prim_path,
        "purpose": str(
            UsdGeom.Imageable(prim).GetPurposeAttr().Get() or "default"
        ),
        "visibility": str(
            UsdGeom.Imageable(prim).GetVisibilityAttr().Get() or "inherited"
        ),
        "materialPrimPath": material_path,
        "meshCount": len(meshes),
        "triangles": triangles,
        "vertices": vertices,
        "_meshSurface": mesh_surface,
    }


def _bound_material_path(prim: Any, *, UsdShade: Any) -> str | None:
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    if material and material.GetPrim().IsValid():
        return str(material.GetPrim().GetPath())
    return None


def _render_surface_facts(
    bindings: list[dict[str, Any]],
    *,
    render_inventory: Mapping[str, Mapping[str, Any]],
    uv_names: tuple[str, ...],
    surface_budget: _SurfaceOperationBudget,
    UsdGeom: Any,
    UsdShade: Any,
    Gf: Any,
) -> dict[str, Any]:
    declared_by_path = {
        mesh["primPath"]: mesh
        for binding in bindings
        if binding["role"] == "render"
        for mesh in binding["_meshSurface"]
    }
    declared_meshes = list(declared_by_path.values())
    allowed_materials = {
        binding["materialPrimPath"]
        for binding in bindings
        if binding["role"] == "render"
    }
    delivered_meshes = []
    seen_paths = {item["primPath"] for item in declared_meshes}
    for item in render_inventory.values():
        surface_prim = None
        for prim in item["prims"]:
            material_path = _bound_material_path(prim, UsdShade=UsdShade)
            if material_path not in allowed_materials:
                raise ProductionUsdObservationError(
                    "Delivered render mesh resolves an undeclared material: "
                    f"{prim.GetPath()}"
                )
            surface_prim = surface_prim or prim
        if surface_prim is None:
            continue
        path = str(surface_prim.GetPath())
        if path in seen_paths:
            continue
        seen_paths.add(path)
        surface_budget.charge(
            len(item["transforms"]),
            label=f"{path} delivered world-transform tuple",
        )
        world_transforms = tuple(item["transforms"])
        delivered_meshes.append({
            **_mesh_surface_fact(
                UsdGeom.Mesh(surface_prim),
                uv_names=uv_names,
                require_frames=True,
                surface_budget=surface_budget,
                UsdGeom=UsdGeom,
                world_transforms=world_transforms,
                Gf=Gf,
            ),
            "materialPrimPath": _bound_material_path(
                surface_prim,
                UsdShade=UsdShade,
            ),
        })
    render_meshes = [*declared_meshes, *delivered_meshes]
    if not render_meshes:
        raise ProductionUsdObservationError(
            "Final USD has no measurable render meshes."
        )
    uv_names = sorted({
        uv["name"] for item in render_meshes for uv in item["uvSets"]
    })
    return {
        "normals": {
            "present": True,
            "consistent": max(
                item["normalMaxUnitLengthError"] for item in render_meshes
            ) <= 1e-3,
            "maxUnitLengthError": max(
                item["normalMaxUnitLengthError"] for item in render_meshes
            ),
            "interpolations": sorted({
                item["normalInterpolation"] for item in render_meshes
            }),
        },
        "tangents": {
            "present": True,
            "orthogonal": max(
                item["tangentMaxOrthogonalError"] for item in render_meshes
            ) <= 1e-3,
            "maxOrthogonalError": max(
                item["tangentMaxOrthogonalError"] for item in render_meshes
            ),
            "interpolations": sorted({
                item["tangentInterpolation"] for item in render_meshes
            }),
        },
        "uvSets": [
            _aggregate_uv(
                name,
                render_meshes,
                surface_budget=surface_budget,
            )
            for name in uv_names
        ],
    }


def _aggregate_uv(
    name: str,
    meshes: list[dict[str, Any]],
    *,
    surface_budget: _SurfaceOperationBudget | None = None,
) -> dict[str, Any]:
    budget = surface_budget or _SurfaceOperationBudget()
    budget.charge(
        len(meshes),
        label=f"{name} global UV measurement list",
    )
    values = [
        uv
        for mesh in meshes
        for uv in mesh["uvSets"]
        if uv["name"] == name
    ]
    if len(values) != len(meshes):
        raise ProductionUsdObservationError(
            f"Required USD UV set is absent from a render mesh: {name}"
        )
    world_area = sum(item["worldArea"] for item in values)
    uv_area = sum(item["uvArea"] for item in values)
    signature_operations = sum(
        sum(item["signatureCounts"].values())
        + len(item["signatureCounts"])
        for item in values
    )
    budget.charge(
        signature_operations,
        label=f"{name} global UV signature counter",
    )
    signature_counts: Counter[tuple[tuple[float, float], ...]] = Counter()
    for item in values:
        signature_counts.update(item["signatureCounts"])
    return {
        "name": name,
        "usdNames": sorted({item["usdName"] for item in values}),
        "interpolations": sorted({item["interpolation"] for item in values}),
        "udimTiles": sorted({
            tile for item in values for tile in item["udimTiles"]
        }),
        "duplicateUvTriangleCount": {
            "status": "measured",
            "value": sum(
                count * (count - 1) // 2
                for count in signature_counts.values()
            ),
        },
        "texelDensity": {
            "status": "measured",
            "value": 2048 * (uv_area / world_area) ** 0.5,
            "unit": "px_per_scene_unit",
        },
    }


def _purpose(prim: Any, UsdGeom: Any) -> str:
    purpose = UsdGeom.Imageable(prim).ComputePurpose()
    return str(purpose or "default")


def _publish_arc(root_prim: Any) -> str:
    has_payload = root_prim.HasAuthoredPayloads()
    has_reference = root_prim.HasAuthoredReferences()
    if has_payload and has_reference:
        raise ProductionUsdObservationError(
            "USD publish root mixes payload and reference composition arcs."
        )
    if has_payload:
        return "payload"
    if has_reference:
        return "reference"
    return "inline"


def _relative_reduction(
    binding: Mapping[str, Any],
    render_bindings: Iterable[Mapping[str, Any]],
) -> float:
    maximum = max((int(item["triangles"]) for item in render_bindings), default=0)
    if maximum <= 0:
        raise ProductionUsdObservationError("Render LOD triangle counts are empty.")
    return round(1.0 - (int(binding["triangles"]) / maximum), 9)


def _asset_dependencies(
    stage: Any,
    usd_path: Path,
    *,
    contract: Mapping[str, Any],
    Sdf: Any,
) -> list[dict[str, Any]]:
    try:
        return asset_dependencies(
            stage,
            usd_path,
            contract=contract,
            Sdf=Sdf,
        )
    except UsdDependencyError as exc:
        raise ProductionUsdObservationError(str(exc)) from exc
