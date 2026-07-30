"""Focused USD assertions shared by the HS8 integration scenario."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from unittest import mock

from hocuspocus.hocusscript.asset_contract_validation import (
    validate_asset_contract,
)
from hocuspocus.live.production_observation import ProductionObservationError
from hocuspocus.live.production_usd_geometry import (
    ProductionUsdGeometryError,
    _canonicalize_right_handed_meshes,
    _mesh_measurement,
    _render_inventory,
    _render_bounds,
    _source_meshes,
    _visible_render_meshes,
)
from hocuspocus.live.production_usd_observation import (
    ProductionUsdObservationError,
    _SurfaceOperationBudget,
    _aggregate_uv,
    _mesh_surface_fact,
    _mesh_uv_fact,
    _native_instancing_fact,
    _point_instancing_fact,
    observe_production_usda,
    project_asset_contract_observation,
)
from tests.hocusscript_hs8_asset_contract_helpers import _observation


PROTOTYPE_MESH = "/Flattened_Prototype_1/Geometry"


def assert_right_handed_export_truth(
    testcase: Any,
    *,
    Gf: Any,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    stage = Usd.Stage.CreateInMemory()
    root = UsdGeom.Xform.Define(stage, "/OverSource").GetPrim()
    mesh = UsdGeom.Mesh.Define(stage, "/OverSource/Geometry")
    author_tetra_mesh(
        mesh, Gf=Gf, Sdf=Sdf, UsdGeom=UsdGeom, surface=False,
    )
    mesh.CreateOrientationAttr(UsdGeom.Tokens.leftHanded)
    corners = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "corner_id",
        Sdf.ValueTypeNames.IntArray,
        UsdGeom.Tokens.faceVarying,
    )
    corners.Set(list(range(12)))
    stage.GetRootLayer().GetPrimAtPath(
        root.GetPath()
    ).specifier = Sdf.SpecifierOver
    original_points = list(mesh.GetPointsAttr().Get())
    testcase.assertEqual(
        _canonicalize_right_handed_meshes(
            stage.GetRootLayer(), Usd=Usd, UsdGeom=UsdGeom,
        ),
        1,
    )
    testcase.assertEqual(
        str(mesh.GetOrientationAttr().Get()),
        "rightHanded",
    )
    testcase.assertEqual(
        list(mesh.GetFaceVertexIndicesAttr().Get()),
        [1, 2, 0, 3, 1, 0, 3, 2, 1, 3, 0, 2],
    )
    mesh.GetFaceVertexIndicesAttr().Set(
        list(mesh.GetFaceVertexIndicesAttr().Get()),
        Usd.TimeCode(1),
    )
    with testcase.assertRaisesRegex(
        ProductionUsdGeometryError,
        "Time-sampled mesh semantics are unsupported",
    ):
        _canonicalize_right_handed_meshes(
            stage.GetRootLayer(), Usd=Usd, UsdGeom=UsdGeom,
        )
    mesh.GetFaceVertexIndicesAttr().ClearAtTime(Usd.TimeCode(1))
    testcase.assertEqual(
        list(corners.Get()),
        [2, 1, 0, 5, 4, 3, 8, 7, 6, 11, 10, 9],
    )
    testcase.assertEqual(list(mesh.GetPointsAttr().Get()), original_points)
    testcase.assertEqual(
        _canonicalize_right_handed_meshes(
            stage.GetRootLayer(), Usd=Usd, UsdGeom=UsdGeom,
        ),
        0,
    )
    testcase.assertEqual(
        list(mesh.GetFaceVertexIndicesAttr().Get()),
        [1, 2, 0, 3, 1, 0, 3, 2, 1, 3, 0, 2],
    )


def author_tetra_mesh(
    mesh: Any,
    *,
    Gf: Any,
    Sdf: Any,
    UsdGeom: Any,
    surface: bool,
) -> None:
    """Author a small closed mesh, optionally with required render frames."""

    mesh.CreatePointsAttr([
        Gf.Vec3f(0, 0, 0),
        Gf.Vec3f(1, 0, 0),
        Gf.Vec3f(0, 1, 0),
        Gf.Vec3f(0, 0, 1),
    ])
    mesh.CreateFaceVertexCountsAttr([3, 3, 3, 3])
    mesh.CreateFaceVertexIndicesAttr([
        0, 2, 1,
        0, 1, 3,
        1, 2, 3,
        2, 0, 3,
    ])
    if not surface:
        return
    mesh.CreateNormalsAttr([Gf.Vec3f(0, 0, 1)] * 4)
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    primvars = UsdGeom.PrimvarsAPI(mesh)
    tangents = primvars.CreatePrimvar(
        "tangentu",
        Sdf.ValueTypeNames.Vector3fArray,
        UsdGeom.Tokens.vertex,
    )
    tangents.Set([Gf.Vec3f(1, 0, 0)] * 4)
    uv = primvars.CreatePrimvar(
        "st",
        Sdf.ValueTypeNames.TexCoord2fArray,
        UsdGeom.Tokens.vertex,
    )
    uv.Set([
        Gf.Vec2f(0, 0),
        Gf.Vec2f(1, 0),
        Gf.Vec2f(0, 1),
        Gf.Vec2f(1, 1),
    ])


def assert_required_intrinsic_truth(testcase: Any, observer: Any) -> None:
    class _UnreadableGeometry:
        @staticmethod
        def intrinsicValue(_name: str) -> int:
            raise RuntimeError("intrinsic probe failed")

    for name in ("pointcount", "vertexcount", "primitivecount"):
        with testcase.assertRaises(ProductionObservationError):
            observer._required_intrinsic_count(
                _UnreadableGeometry(),
                name,
                "/obj/hs8/output",
            )

    class _UnreadableEdges:
        @staticmethod
        def globEdges(_pattern: str) -> tuple[Any, ...]:
            raise RuntimeError("edge enumeration failed")

    with testcase.assertRaises(ProductionObservationError):
        observer._required_edge_count(
            _UnreadableEdges(),
            admitted_vertices=3,
            node_path="/obj/hs8/output",
        )

    class _MalformedEdges:
        @staticmethod
        def globEdges(_pattern: str) -> str:
            return "not-an-edge-sequence"

    with testcase.assertRaises(ProductionObservationError):
        observer._required_edge_count(
            _MalformedEdges(),
            admitted_vertices=3,
            node_path="/obj/hs8/output",
        )

    class _BoundedEdges:
        @staticmethod
        def globEdges(pattern: str) -> tuple[object, object]:
            if pattern != "*":
                raise AssertionError("edge glob must enumerate the whole geometry")
            return (object(), object())

    testcase.assertEqual(
        observer._required_edge_count(
            _BoundedEdges(),
            admitted_vertices=2,
            node_path="/obj/hs8/output",
        ),
        2,
    )
    with testcase.assertRaises(ProductionObservationError):
        observer._required_edge_count(
            _BoundedEdges(),
            admitted_vertices=1,
            node_path="/obj/hs8/output",
        )


def assert_reopened_stage_authority(
    testcase: Any,
    *,
    path: Path,
    contract: dict[str, Any],
    baseline: dict[str, Any],
    Gf: Any,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    """Exercise hostile final-stage facts without adding public test cases."""

    missing_units = _copy_stage(path, "missing-units.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(missing_units))
    stage.ClearMetadata("metersPerUnit")
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(missing_units, contract=contract)

    malformed_units = _copy_stage(path, "malformed-units.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(malformed_units))
    stage.SetMetadata("metersPerUnit", 0.0)
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(malformed_units, contract=contract)

    missing_axis = _copy_stage(path, "missing-axis.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(missing_axis))
    stage.ClearMetadata("upAxis")
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(missing_axis, contract=contract)

    for key in ("forwardAxis", "pivotMode"):
        missing_authority = _copy_stage(
            path, f"missing-{key}.usda", Usd=Usd,
        )
        stage = Usd.Stage.Open(str(missing_authority))
        layer_data = dict(stage.GetRootLayer().customLayerData)
        authority = dict(layer_data["hocuspocus"])
        authority.pop(key)
        layer_data["hocuspocus"] = authority
        stage.GetRootLayer().customLayerData = layer_data
        stage.GetRootLayer().Save()
        del stage
        with testcase.assertRaises(ProductionUsdObservationError):
            observe_production_usda(missing_authority, contract=contract)

    wrong_pivot = _copy_stage(path, "wrong-pivot-mode.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(wrong_pivot))
    layer_data = dict(stage.GetRootLayer().customLayerData)
    authority = dict(layer_data["hocuspocus"])
    authority["pivotMode"] = "center"
    layer_data["hocuspocus"] = authority
    stage.GetRootLayer().customLayerData = layer_data
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(wrong_pivot, contract=contract)

    hostile_topology = (
        ("open", [3, 3, 3], [0, 2, 1, 0, 1, 3, 1, 2, 3], "watertight"),
        ("nonmanifold", [3, 3, 3], [0, 1, 2, 1, 0, 3, 0, 1, 3], "manifold"),
        ("degenerate", [3], [0, 0, 1], "degenerateCount"),
    )
    for name, counts, indices, fact in hostile_topology:
        hostile = _copy_stage(path, f"{name}.usda", Usd=Usd)
        stage = Usd.Stage.Open(str(hostile))
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath(PROTOTYPE_MESH))
        mesh.GetFaceVertexCountsAttr().Set(counts)
        mesh.GetFaceVertexIndicesAttr().Set(indices)
        stage.GetRootLayer().Save()
        del stage
        if fact == "degenerateCount":
            with testcase.assertRaises(ProductionUsdObservationError):
                observe_production_usda(hostile, contract=contract)
            continue
        observed = observe_production_usda(hostile, contract=contract)
        testcase.assertFalse(observed["topology"][fact])
        report = validate_asset_contract(
            contract,
            project_asset_contract_observation(_observation(), observed),
        )
        testcase.assertIn(
            f"/geometry/topology/{fact}",
            {item.json_pointer for item in report.diagnostics},
        )

    unexpected = _copy_stage(path, "unexpected-visible.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(unexpected))
    author_tetra_mesh(
        UsdGeom.Mesh.Define(stage, "/World/UnexpectedVisible"),
        Gf=Gf,
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        surface=False,
    )
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(unexpected, contract=contract)

    stale_extent = _copy_stage(path, "stale-extent.usda", Usd=Usd)
    stage = Usd.Stage.Open(str(stale_extent))
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath(PROTOTYPE_MESH))
    mesh.CreateExtentAttr([
        Gf.Vec3f(-1000, -1000, -1000),
        Gf.Vec3f(1000, 1000, 1000),
    ])
    stage.GetRootLayer().Save()
    del stage
    extent_observation = observe_production_usda(
        stale_extent,
        contract=contract,
    )
    testcase.assertEqual(extent_observation["bounds"], baseline["bounds"])

    _assert_triangle_uv_signatures(
        testcase,
        Gf=Gf,
        Sdf=Sdf,
        Usd=Usd,
        UsdGeom=UsdGeom,
    )


def _copy_stage(path: Path, name: str, *, Usd: Any) -> Path:
    target = path.parent / name
    target.write_bytes(path.read_bytes())
    stage = Usd.Stage.Open(str(target))
    if stage is None:
        raise AssertionError(f"Could not reopen copied stage: {target}")
    del stage
    return target


def _assert_triangle_uv_signatures(
    testcase: Any,
    *,
    Gf: Any,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    stage = Usd.Stage.CreateInMemory()
    mesh = UsdGeom.Mesh.Define(stage, "/DuplicateUvTriangles")
    mesh.CreatePointsAttr([
        Gf.Vec3f(0, 0, 0),
        Gf.Vec3f(1, 0, 0),
        Gf.Vec3f(1, 1, 0),
        Gf.Vec3f(0, 1, 0),
    ])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    primvar = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st",
        Sdf.ValueTypeNames.TexCoord2fArray,
        UsdGeom.Tokens.faceVarying,
    )
    primvar.Set([
        Gf.Vec2f(0, 0),
        Gf.Vec2f(1, 0),
        Gf.Vec2f(1, 1),
        Gf.Vec2f(1, 0),
    ])
    measured = _mesh_uv_fact(
        mesh,
        UsdGeom.PrimvarsAPI(mesh),
        "uv",
        counts=[4],
        point_indices=[0, 1, 2, 3],
        points=list(mesh.GetPointsAttr().Get()),
        surface_budget=_SurfaceOperationBudget(maximum=1_000),
    )
    testcase.assertEqual(
        _aggregate_uv(
            "uv",
            [{"uvSets": [measured]}],
        )["duplicateUvTriangleCount"]["value"],
        1,
    )
    signature = next(iter(measured["signatureCounts"]))
    one_triangle = {
        **measured,
        "signatureCounts": {signature: 1},
    }
    testcase.assertEqual(
        _aggregate_uv(
            "uv",
            [
                {"primPath": "/FirstMesh", "uvSets": [one_triangle]},
                {"primPath": "/SecondMesh", "uvSets": [one_triangle]},
            ],
        )["duplicateUvTriangleCount"]["value"],
        1,
    )

    original_uvs = list(primvar.Get())
    primvar.Set([Gf.Vec2f(0, 0)] * 64)
    with testcase.assertRaisesRegex(
        ProductionUsdObservationError,
        "exceeds 32 aggregate operations",
    ):
        _mesh_surface_fact(
            mesh,
            uv_names=("uv",),
            require_frames=False,
            surface_budget=_SurfaceOperationBudget(maximum=32),
            UsdGeom=UsdGeom,
        )
    primvar.Set(original_uvs)
    with (
        mock.patch(
            "hocuspocus.live.production_usd_surface._vector",
            side_effect=AssertionError(
                "UV conversion occurred before its tuple charge"
            ),
        ),
        testcase.assertRaisesRegex(
            ProductionUsdObservationError,
            "exceeds 27 aggregate operations",
        ),
    ):
        _mesh_surface_fact(
            mesh,
            uv_names=("uv",),
            require_frames=False,
            surface_budget=_SurfaceOperationBudget(maximum=27),
            UsdGeom=UsdGeom,
        )

    surface_budget = _SurfaceOperationBudget(maximum=55)
    _mesh_surface_fact(
        mesh,
        uv_names=("uv",),
        require_frames=False,
        surface_budget=surface_budget,
        UsdGeom=UsdGeom,
    )
    testcase.assertEqual(surface_budget.used, 55)
    with testcase.assertRaisesRegex(
        ProductionUsdObservationError,
        "exceeds 55 aggregate operations",
    ):
        _mesh_surface_fact(
            mesh,
            uv_names=("uv",),
            require_frames=False,
            surface_budget=surface_budget,
            UsdGeom=UsdGeom,
        )


def assert_point_instancer_truth(
    testcase: Any,
    *,
    Gf: Any,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    stage = Usd.Stage.CreateInMemory()
    prototype = UsdGeom.Xform.Define(stage, "/PointPrototype")
    prototype_mesh = UsdGeom.Mesh.Define(stage, "/PointPrototype/Geometry")
    author_tetra_mesh(
        prototype_mesh,
        Gf=Gf,
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        surface=False,
    )
    hidden_collision = UsdGeom.Mesh.Define(
        stage,
        "/PointPrototype/HiddenCollision",
    )
    author_tetra_mesh(
        hidden_collision,
        Gf=Gf,
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        surface=False,
    )
    hidden_collision.CreatePurposeAttr(UsdGeom.Tokens.proxy)
    hidden_collision.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
    instancer = UsdGeom.PointInstancer.Define(stage, "/PointInstancer")
    instancer.GetPrototypesRel().SetTargets([prototype.GetPath()])
    instancer.CreateProtoIndicesAttr([0, 0, 0])
    instancer.CreatePositionsAttr([
        Gf.Vec3f(0, 0, 0),
        Gf.Vec3f(1, 0, 0),
        Gf.Vec3f(2, 0, 0),
    ])
    instancer.CreateInvisibleIdsAttr([999])
    stale_mask = _point_instancing_fact(
        [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
    )
    testcase.assertEqual(stale_mask["renderedInstanceCount"], 3)
    testcase.assertEqual(
        _visible_render_meshes(
            list(stage.Traverse()),
            prototype_path="/PointPrototype",
            UsdGeom=UsdGeom,
        ),
        [],
    )
    instancer.CreatePurposeAttr(UsdGeom.Tokens.proxy)
    proxy_output = _point_instancing_fact(
        [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
    )
    testcase.assertEqual(proxy_output["renderedInstanceCount"], 0)
    instancer.GetPurposeAttr().Set(UsdGeom.Tokens.default_)
    instancer.CreateIdsAttr([10, 20, 30])
    instancer.GetInvisibleIdsAttr().Set([20, 999])
    mixed_mask = _point_instancing_fact(
        [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
    )
    testcase.assertEqual(mixed_mask["renderedInstanceCount"], 2)
    testcase.assertEqual(
        [
            str(prim.GetPath())
            for prim in _source_meshes(
                stage,
                "/PointPrototype",
                instancing=mixed_mask,
                Usd=Usd,
                UsdGeom=UsdGeom,
            )
        ],
        ["/PointPrototype/Geometry"],
    )
    with testcase.assertRaises(ProductionUsdGeometryError):
        _source_meshes(
            stage,
            "/PointPrototype",
            instancing={
                **mixed_mask,
                "prototypePaths": ["/WrongPrototype"],
            },
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
    second_prototype_mesh = UsdGeom.Mesh.Define(
        stage,
        "/PointPrototype/GeometryB",
    )
    author_tetra_mesh(
        second_prototype_mesh,
        Gf=Gf,
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        surface=False,
    )
    with (
        mock.patch(
            "hocuspocus.live.production_usd_geometry.MAX_RENDERED_MESHES",
            3,
        ),
        mock.patch(
            "hocuspocus.live.production_usd_geometry."
            "_point_instance_transforms",
            side_effect=AssertionError(
                "point transforms materialized before aggregate capacity preflight"
            ),
        ) as point_transforms,
        testcase.assertRaises(ProductionUsdGeometryError),
    ):
        _render_inventory(
            [], [],
            stage=stage,
            source_meshes=[
                prototype_mesh.GetPrim(),
                second_prototype_mesh.GetPrim(),
            ],
            point_instancers=[instancer.GetPrim()],
            instancing=mixed_mask,
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
    point_transforms.assert_not_called()
    inventory = _render_inventory(
        [], [],
        stage=stage,
        source_meshes=[prototype_mesh.GetPrim()],
        point_instancers=[instancer.GetPrim()],
        instancing=mixed_mask,
        Usd=Usd,
        UsdGeom=UsdGeom,
    )
    testcase.assertEqual(
        len(next(iter(inventory.values()))["transforms"]),
        2,
    )
    testcase.assertNotIn(
        str(hidden_collision.GetPath()),
        {
            str(prim.GetPath())
            for prim in _source_meshes(
                stage,
                "/PointPrototype",
                instancing=mixed_mask,
                Usd=Usd,
                UsdGeom=UsdGeom,
            )
        },
    )
    bounds = _render_bounds(
        inventory,
        allow_empty=False,
        Gf=Gf,
        UsdGeom=UsdGeom,
    )
    testcase.assertEqual(bounds["minimum"], [0.0, 0.0, 0.0])
    testcase.assertEqual(bounds["maximum"], [3.0, 1.0, 1.0])
    with (
        mock.patch(
            "hocuspocus.live.production_usd_geometry._point",
            side_effect=AssertionError(
                "mesh points materialized before shared topology budget"
            ),
        ) as point_conversion,
        testcase.assertRaisesRegex(
            ProductionUsdGeometryError,
            "exceeds 1 aggregate operations",
        ),
    ):
        _mesh_measurement(
            hidden_collision.GetPrim(),
            UsdGeom=UsdGeom,
            operation_budget=_SurfaceOperationBudget(maximum=1),
        )
    point_conversion.assert_not_called()

    class _ExplosivePoint:
        def __getitem__(self, _index: int) -> float:
            raise AssertionError("point conversion occurred before the bounds guard")

    class _HostileMesh:
        @staticmethod
        def GetPointsAttr() -> Any:
            class _Points:
                @staticmethod
                def Get() -> list[Any]:
                    return [_ExplosivePoint(), _ExplosivePoint()]

            return _Points()

    class _HostileUsdGeom:
        @staticmethod
        def Mesh(prim: Any) -> Any:
            return prim

    with (
        mock.patch(
            "hocuspocus.live.production_usd_geometry."
            "MAX_BOUND_POINT_TRANSFORMS",
            1,
        ),
        testcase.assertRaisesRegex(
            ProductionUsdGeometryError,
            "operation limit",
        ),
    ):
        _render_bounds(
            {
                "hostile": {
                    "prim": _HostileMesh(),
                    "transforms": [object()],
                },
            },
            allow_empty=False,
            Gf=Gf,
            UsdGeom=_HostileUsdGeom,
        )
    instancer.GetPrototypesRel().SetTargets([Sdf.Path("/MissingPrototype")])
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/MissingPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )
    nonmesh = UsdGeom.Xform.Define(stage, "/NonMeshPrototype")
    UsdGeom.Cube.Define(stage, "/NonMeshPrototype/Geometry")
    instancer.GetPrototypesRel().SetTargets([nonmesh.GetPath()])
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/NonMeshPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )
    with testcase.assertRaises(ProductionUsdGeometryError):
        _source_meshes(
            stage,
            "/NonMeshPrototype",
            instancing={
                "representation": "point_instancer",
                "prototypePrimPath": "/NonMeshPrototype",
                "prototypePaths": ["/NonMeshPrototype"],
            },
            Usd=Usd,
            UsdGeom=UsdGeom,
        )
    instancer.GetPrototypesRel().SetTargets([prototype.GetPath()])
    instancer.CreateProtoIndicesAttr([1])
    instancer.CreatePositionsAttr([Gf.Vec3f(0, 0, 0)])
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )
    instancer.CreateProtoIndicesAttr([])
    instancer.CreatePositionsAttr([])
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )
    instancer.CreateProtoIndicesAttr([0, 0])
    instancer.GetPrim().RemoveProperty("positions")
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )
    instancer.CreatePositionsAttr([Gf.Vec3f(0, 0, 0)])
    with testcase.assertRaises(ProductionUsdObservationError):
        _point_instancing_fact(
            [instancer.GetPrim()], "/PointPrototype", Usd=Usd, UsdGeom=UsdGeom,
        )


def assert_transformed_and_static_usd_truth(
    testcase: Any,
    *,
    path: Path,
    contract: dict[str, Any],
    baseline: dict[str, Any],
    Gf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    scaled = path.parent / "scaled-prototype.usda"
    scaled.write_bytes(path.read_bytes())
    scaled_stage = Usd.Stage.Open(str(scaled))
    for index in range(3):
        scaled_instance = scaled_stage.GetPrimAtPath(
            f"/World/RockFamily/Instances/rock_{index}"
        )
        UsdGeom.Xformable(scaled_instance).AddScaleOp().Set(
            Gf.Vec3f(2.0, 2.0, 2.0)
        )
    scaled_stage.GetRootLayer().Save()
    del scaled_stage
    scaled_observation = observe_production_usda(scaled, contract=contract)
    baseline_density = baseline["uvSets"][0]["texelDensity"]["value"]
    testcase.assertAlmostEqual(
        scaled_observation["uvSets"][0]["texelDensity"]["value"],
        baseline_density * (5.0 / 14.0) ** 0.5,
    )

    time_sampled = path.parent / "time-sampled-topology.usda"
    time_sampled.write_bytes(path.read_bytes())
    time_stage = Usd.Stage.Open(str(time_sampled))
    time_mesh = UsdGeom.Mesh(
        time_stage.GetPrimAtPath("/Flattened_Prototype_1/Geometry")
    )
    time_mesh.GetFaceVertexIndicesAttr().Set(
        list(time_mesh.GetFaceVertexIndicesAttr().Get()),
        Usd.TimeCode(1),
    )
    time_stage.GetRootLayer().Save()
    del time_stage
    with testcase.assertRaisesRegex(
        ProductionUsdObservationError,
        "Time-sampled mesh semantics are unsupported",
    ):
        observe_production_usda(time_sampled, contract=contract)


def assert_usd_dependency_truth(
    testcase: Any,
    path: Path,
    contract: dict[str, Any],
    *,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    root = path.parent
    texture = root / "rock-texture.bin"
    texture.write_bytes(b"hs8-texture-dependency")
    textured = root / "textured.usda"
    textured.write_bytes(path.read_bytes())
    stage = Usd.Stage.Open(str(textured))
    attribute = stage.GetPrimAtPath("/World").CreateAttribute(
        "hocus:texture",
        Sdf.ValueTypeNames.AssetArray,
    )
    attribute.Set([Sdf.AssetPath(texture.name)], Usd.TimeCode(1))
    stage.GetRootLayer().Save()
    del stage
    declared = copy.deepcopy(contract)
    declared["dependencies"].append({
        "id": "rock.texture",
        "kind": "texture",
        "version": "1.0.0",
        "digest": "sha256:" + hashlib.sha256(texture.read_bytes()).hexdigest(),
    })
    observed = observe_production_usda(textured, contract=declared)
    testcase.assertEqual(observed["textureCount"], 1)
    testcase.assertEqual(observed["textureBytes"], texture.stat().st_size)
    testcase.assertEqual(
        observed["contractDependencies"],
        [declared["dependencies"][-1]],
    )
    testcase.assertNotIn("path", observed["assetDependencies"][0])
    projected = project_asset_contract_observation(_observation(), observed)
    testcase.assertIn(declared["dependencies"][-1], projected["dependencies"])
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(textured, contract=contract)

    metadata = root / "metadata.usda"
    metadata.write_bytes(path.read_bytes())
    stage = Usd.Stage.Open(str(metadata))
    world = stage.GetPrimAtPath("/World")
    world.SetCustomDataByKey(
        "consumer",
        {"nested": {"source": Sdf.AssetPath(texture.name)}},
    )
    layer_data = dict(stage.GetRootLayer().customLayerData)
    layer_data["nested"] = {"source": Sdf.AssetPath(texture.name)}
    stage.GetRootLayer().customLayerData = layer_data
    variants = world.GetVariantSets().AddVariantSet("metadata")
    variants.AddVariant("asset")
    variants.SetVariantSelection("asset")
    with variants.GetVariantEditContext():
        world.SetCustomDataByKey(
            "variantSource",
            {"source": Sdf.AssetPath(texture.name)},
        )
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(metadata, contract=contract)
    metadata_observed = observe_production_usda(
        metadata,
        contract=declared,
    )
    testcase.assertEqual(
        metadata_observed["contractDependencies"],
        [declared["dependencies"][-1]],
    )

    external = root / "external.usda"
    external_stage = Usd.Stage.CreateNew(str(external))
    external_stage.SetDefaultPrim(
        UsdGeom.Xform.Define(external_stage, "/External").GetPrim()
    )
    external_stage.GetRootLayer().Save()
    del external_stage
    for arc in ("sublayer", "reference", "payload"):
        hostile = root / f"external-{arc}.usda"
        hostile.write_bytes(path.read_bytes())
        stage = Usd.Stage.Open(str(hostile))
        if arc == "sublayer":
            stage.GetRootLayer().subLayerPaths.append(external.name)
        elif arc == "reference":
            stage.GetPrimAtPath("/World").GetReferences().AddReference(
                external.name
            )
        else:
            stage.GetPrimAtPath("/World").GetPayloads().AddPayload(
                external.name
            )
        stage.GetRootLayer().Save()
        del stage
        with testcase.assertRaises(ProductionUsdObservationError):
            observe_production_usda(hostile, contract=contract)

    unresolved = root / "unresolved-reference.usda"
    unresolved.write_bytes(path.read_bytes())
    stage = Usd.Stage.Open(str(unresolved))
    stage.GetPrimAtPath("/World").GetReferences().AddReference("missing.usda")
    stage.GetRootLayer().Save()
    del stage
    with testcase.assertRaises(ProductionUsdObservationError):
        observe_production_usda(unresolved, contract=contract)


def assert_native_over_prototype_truth(
    testcase: Any,
    *,
    Gf: Any,
    Sdf: Any,
    Usd: Any,
    UsdGeom: Any,
) -> None:
    stage = Usd.Stage.CreateInMemory()
    source = UsdGeom.Xform.Define(stage, "/NativeOver").GetPrim()
    mesh = UsdGeom.Mesh.Define(stage, "/NativeOver/Geometry")
    author_tetra_mesh(
        mesh, Gf=Gf, Sdf=Sdf, UsdGeom=UsdGeom, surface=False,
    )
    stage.GetRootLayer().GetPrimAtPath(
        source.GetPath()
    ).specifier = Sdf.SpecifierOver
    instances = []
    for index in range(2):
        instance = stage.DefinePrim(f"/Native_{index}", "Xform")
        instance.GetReferences().AddInternalReference(source.GetPath())
        instance.SetInstanceable(True)
        instances.append(instance)
    testcase.assertFalse(stage.GetPrimAtPath(source.GetPath()).IsDefined())
    observed = _native_instancing_fact(
        instances, "/NativeOver", Usd=Usd, UsdGeom=UsdGeom,
    )
    testcase.assertEqual(observed["prototypePaths"], ["/__Prototype_1"])
    testcase.assertEqual(observed["renderedInstanceCount"], 2)

    missing = stage.DefinePrim("/MissingPrototypeInstance", "Xform")
    missing.GetReferences().AddInternalReference("/MissingTarget")
    missing.SetInstanceable(True)
    with testcase.assertRaises(ProductionUsdObservationError):
        _native_instancing_fact(
            [missing], "/MissingTarget", Usd=Usd, UsdGeom=UsdGeom,
        )

    unreadable_source = UsdGeom.Xform.Define(
        stage, "/UnreadableOver",
    ).GetPrim()
    UsdGeom.Mesh.Define(stage, "/UnreadableOver/Geometry")
    stage.GetRootLayer().GetPrimAtPath(
        unreadable_source.GetPath()
    ).specifier = Sdf.SpecifierOver
    unreadable = stage.DefinePrim("/UnreadableInstance", "Xform")
    unreadable.GetReferences().AddInternalReference(unreadable_source.GetPath())
    unreadable.SetInstanceable(True)
    with testcase.assertRaises(ProductionUsdObservationError):
        _native_instancing_fact(
            [unreadable], "/UnreadableOver", Usd=Usd, UsdGeom=UsdGeom,
        )

    divergent_source = UsdGeom.Xform.Define(
        stage, "/DivergentPrototype",
    ).GetPrim()
    divergent_mesh = UsdGeom.Mesh.Define(
        stage, "/DivergentPrototype/Geometry",
    )
    author_tetra_mesh(
        divergent_mesh, Gf=Gf, Sdf=Sdf, UsdGeom=UsdGeom, surface=False,
    )
    variants = divergent_source.GetVariantSets().AddVariantSet("shape")
    for name in ("a", "b"):
        variants.AddVariant(name)
    divergent = []
    for index, name in enumerate(("a", "b")):
        instance = stage.DefinePrim(f"/Divergent_{index}", "Xform")
        instance.GetReferences().AddInternalReference(
            divergent_source.GetPath()
        )
        instance.GetVariantSets().GetVariantSet(
            "shape"
        ).SetVariantSelection(name)
        instance.SetInstanceable(True)
        divergent.append(instance)
    with testcase.assertRaises(ProductionUsdObservationError):
        _native_instancing_fact(
            divergent,
            "/DivergentPrototype",
            Usd=Usd,
            UsdGeom=UsdGeom,
        )


__all__ = [
    "assert_native_over_prototype_truth",
    "assert_point_instancer_truth",
    "assert_reopened_stage_authority",
    "assert_required_intrinsic_truth",
    "assert_right_handed_export_truth",
    "assert_transformed_and_static_usd_truth",
    "assert_usd_dependency_truth",
    "author_tetra_mesh",
]
