"""Read-only production-fixture observation for live Houdini acceptance.

The observer deliberately refuses dirty geometry.  A caller must explicitly
cook a disposable fixture before observation; geometry/stage inspection is
then verified not to change any node cook count.
"""

from __future__ import annotations

import hashlib
import copy
import json
import re
import time
from typing import Any, Iterable

MAX_OBSERVED_NODES = 10_000
MAX_OBSERVED_POINTS = 10_000_000
MAX_OBSERVED_VERTICES = 30_000_000
MAX_OBSERVED_PRIMITIVES = 10_000_000
MAX_OBSERVED_EDGES = 30_000_000
MAX_OBSERVED_USD_PRIMS = 1_000_000
MAX_OBSERVED_DEPENDENCIES = 4_096
MAX_OBSERVED_HDA_BYTES = 256 * 1024 * 1024


class ProductionObservationError(RuntimeError):
    """Raised when observation would mutate or escapes its disposable scope."""


class ProductionFixtureObserver:
    """Collect production evidence without cooking or editing Houdini state."""

    def __init__(self, hou_module: Any, *, authorized_roots: Iterable[str]):
        self._hou = hou_module
        self._hda_cache: dict[
            tuple[str, str], tuple[dict[str, Any], int]
        ] = {}
        self._roots = tuple(sorted({self._clean_path(path) for path in authorized_roots}))
        if not self._roots:
            raise ValueError("At least one authorized disposable root is required.")

    def observe(
        self,
        *,
        asset_id: str,
        geometry_paths: Iterable[str],
        usd_paths: Iterable[str] = (),
        platform: str = "houdini",
    ) -> dict[str, Any]:
        """Return deterministic production evidence and prove zero observer cooks."""

        self._hda_cache.clear()
        geometry_nodes = [self._node(path) for path in geometry_paths]
        usd_nodes = [self._node(path) for path in usd_paths]
        before = self._cook_counts()
        started = time.perf_counter()
        geometry = [self._geometry(node) for node in geometry_nodes]
        usd = [self._usd_stage(node) for node in usd_nodes]
        dependencies = self._dependencies()
        names = sorted({node.name() for node in self._iter_nodes()})
        contract_observation = self._contract_observation(
            asset_id=asset_id,
            geometry=geometry,
            usd=usd,
            dependencies=dependencies,
            names=names,
            platform=platform,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        after = self._cook_counts()
        changed = {
            path: {"before": before.get(path, 0), "after": count}
            for path, count in after.items()
            if count != before.get(path, 0)
        }
        if changed:
            raise ProductionObservationError(
                f"Observation executed unintended Houdini cooks: {changed!r}"
            )
        metrics = self._metrics(geometry, usd, dependencies, elapsed_ms)
        deterministic = {
            "geometry": geometry,
            "usd": usd,
            "dependencies": dependencies,
            "metrics": {key: value for key, value in metrics.items() if key != "observationMs"},
        }
        digest_projection = copy.deepcopy(deterministic)
        for stage in digest_projection["usd"]:
            stage.get("rootLayer", {}).pop("identifierDigest", None)
        return {
            **deterministic,
            "assetContractObservation": contract_observation,
            "metrics": metrics,
            "cookCounts": {"before": before, "after": after, "changed": changed},
            "observerCookExecuted": False,
            "deterministicDigest": self._digest(digest_projection),
        }

    def contract_dependencies(self) -> list[dict[str, Any]]:
        """Measure immutable dependency identities without cooking the fixture."""

        self._hda_cache.clear()
        before = self._cook_counts()
        dependencies = self._dependencies()
        after = self._cook_counts()
        if after != before:
            raise ProductionObservationError(
                "Dependency inspection executed an unintended Houdini cook."
            )
        records = {
            (
                "hda" if item["kind"] == "hda" else "asset",
                item["id"],
            ): {
                "id": item["id"],
                "kind": "hda" if item["kind"] == "hda" else "asset",
                "version": item["version"],
                "digest": item["digest"],
            }
            for item in dependencies
        }
        return sorted(
            records.values(),
            key=lambda item: (item["kind"], item["id"]),
        )

    @staticmethod
    def _clean_path(path: str) -> str:
        value = str(path or "").strip().rstrip("/")
        if not value.startswith("/"):
            raise ValueError(f"Expected an absolute Houdini path, got {path!r}.")
        return value or "/"

    def _authorized(self, path: str) -> bool:
        return any(path == root or path.startswith(root + "/") for root in self._roots)

    def _node(self, path: str) -> Any:
        clean = self._clean_path(path)
        if not self._authorized(clean):
            raise ProductionObservationError(
                f"Node is outside the disposable fixture roots: {clean}"
            )
        node = self._hou.node(clean)
        if node is None:
            raise ProductionObservationError(f"Fixture node is missing: {clean}")
        return node

    @staticmethod
    def _safe(callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default

    @staticmethod
    def _required(callback: Any, message: str) -> Any:
        try:
            return callback()
        except Exception as exc:
            raise ProductionObservationError(message) from exc

    def _iter_nodes(self) -> list[Any]:
        result: dict[str, Any] = {}
        for root_path in self._roots:
            root = self._hou.node(root_path)
            if root is None:
                continue
            pending = [root]
            while pending:
                node = pending.pop()
                result[node.path()] = node
                if len(result) > MAX_OBSERVED_NODES:
                    raise ProductionObservationError(
                        f"Fixture exceeds {MAX_OBSERVED_NODES} observable nodes."
                    )
                children = self._required(
                    node.children,
                    f"Could not enumerate fixture children at {node.path()}.",
                )
                pending.extend(children or ())
        return [result[path] for path in sorted(result)]

    def _cook_counts(self) -> dict[str, int]:
        return {
            node.path(): int(self._required(
                node.cookCount,
                f"Could not read fixture cook count at {node.path()}.",
            ))
            for node in self._iter_nodes()
        }

    def _geometry(self, node: Any) -> dict[str, Any]:
        target = self._required(
            node.displayNode,
            f"Could not resolve display geometry at {node.path()}.",
        ) or node
        if bool(self._required(
            target.needsToCook,
            f"Could not inspect geometry cook state at {target.path()}.",
        )):
            raise ProductionObservationError(
                f"Refusing implicit geometry cook for dirty node {target.path()}."
            )
        geometry = self._required(
            target.geometry,
            f"Could not read pre-cooked geometry at {target.path()}.",
        )
        if geometry is None:
            raise ProductionObservationError(
                f"Node has no pre-cooked geometry: {target.path()}"
            )
        admitted_counts = {
            "points": self._required_intrinsic_count(
                geometry, "pointcount", target.path(),
            ),
            "vertices": self._required_intrinsic_count(
                geometry, "vertexcount", target.path(),
            ),
            "primitives": self._required_intrinsic_count(
                geometry, "primitivecount", target.path(),
            ),
        }
        admitted_counts["edges"] = self._required_edge_count(
            geometry,
            admitted_vertices=admitted_counts["vertices"],
            node_path=target.path(),
        )
        limits = {
            "points": MAX_OBSERVED_POINTS,
            "vertices": MAX_OBSERVED_VERTICES,
            "primitives": MAX_OBSERVED_PRIMITIVES,
            "edges": MAX_OBSERVED_EDGES,
        }
        if any(admitted_counts[name] > limits[name] for name in limits):
            raise ProductionObservationError(
                f"Geometry exceeds bounded observation limits at {target.path()}."
            )
        bbox = geometry.boundingBox()
        point_attributes = self._attributes(geometry.pointAttribs())
        vertex_attributes = self._attributes(geometry.vertexAttribs())
        primitive_attributes = self._attributes(geometry.primAttribs())
        primitive_groups = sorted(group.name() for group in geometry.primGroups())
        material_paths = self._material_paths(geometry)
        owner = node.parent() if node.parent() is not None else node
        try:
            pivot_tuple = owner.parmTuple("p")
            if pivot_tuple is None:
                raise RuntimeError("Object has no pivot parameter tuple.")
            object_pivot = [float(value) for value in pivot_tuple.eval()]
        except Exception as exc:
            raise ProductionObservationError(
                f"Could not measure object pivot for {owner.path()}."
            ) from exc
        object_material = self._safe(
            lambda: owner.parm("shop_materialpath").evalAsString(), "",
        )
        if object_material:
            material_paths = sorted({*material_paths, object_material})
        topology = {
            **admitted_counts,
            "primitiveTypes": self._primitive_types(geometry),
            **self._topology_quality(geometry),
        }
        normal_quality = self._vector_quality(geometry, "N")
        tangent_quality = self._vector_quality(geometry, "tangentu", reference="N")
        instancing, instance_count = self._contract_instancing(geometry)
        contract_delivery = {
            "lods": self._contract_lods(geometry),
            "collision": self._contract_collision(geometry),
            "instancing": instancing,
            "instanceCount": instance_count,
        }
        return {
            "nodePath": node.path(),
            "geometryNodePath": target.path(),
            "topology": topology,
            "bounds": {
                "min": [float(value) for value in bbox.minvec()],
                "max": [float(value) for value in bbox.maxvec()],
                "size": [float(value) for value in bbox.sizevec()],
            },
            "attributes": {
                "point": point_attributes,
                "vertex": vertex_attributes,
                "primitive": primitive_attributes,
            },
            "uv": self._uv_summary(point_attributes, vertex_attributes),
            "uvDetails": self._uv_details(geometry),
            "materials": {"paths": material_paths, "slotCount": len(material_paths)},
            "lod": {
                "groups": [name for name in primitive_groups if "lod" in name.lower()],
                "nodes": self._matching_nodes("lod"),
            },
            "collision": {
                "groups": [
                    name for name in primitive_groups
                    if any(token in name.lower() for token in ("collision", "proxy", "ucx"))
                ],
                "nodes": self._matching_nodes("collision", "proxy", "ucx"),
            },
            "groups": {
                "point": sorted(group.name() for group in geometry.pointGroups()),
                "primitive": primitive_groups,
                "edge": sorted(group.name() for group in geometry.edgeGroups()),
            },
            "memoryBytes": int(self._intrinsic(geometry, "memoryusage", 0)),
            "objectPivot": object_pivot,
            "normalQuality": normal_quality,
            "tangentQuality": tangent_quality,
            "contractDelivery": contract_delivery,
        }

    def _attributes(self, attributes: Iterable[Any]) -> list[dict[str, Any]]:
        return sorted(
            (
                {
                    "name": attribute.name(),
                    "size": int(attribute.size()),
                    "dataType": str(self._safe(lambda: attribute.dataType().name(), "")),
                }
                for attribute in attributes
            ),
            key=lambda item: item["name"],
        )

    @staticmethod
    def _uv_summary(
        point_attributes: list[dict[str, Any]],
        vertex_attributes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sets = [
            {**attribute, "owner": owner}
            for owner, values in (("point", point_attributes), ("vertex", vertex_attributes))
            for attribute in values
            if attribute["name"].lower() in {"uv", "uv2", "st"} or attribute["name"].lower().startswith("uv")
        ]
        return {"sets": sets, "setCount": len(sets), "hasPrimaryUV": any(item["name"] == "uv" for item in sets)}

    def _uv_details(self, geometry: Any) -> list[dict[str, Any]]:
        result = []
        polygon_primitives = self._polygon_primitives(geometry)
        polygon_points = {
            vertex.point().number(): vertex.point()
            for primitive in polygon_primitives
            for vertex in primitive.vertices()
        }
        for owner, attributes, elements in (
            ("point", geometry.pointAttribs(), tuple(polygon_points.values())),
            (
                "vertex",
                geometry.vertexAttribs(),
                tuple(
                    vertex
                    for primitive in polygon_primitives
                    for vertex in primitive.vertices()
                ),
            ),
        ):
            for attribute in attributes:
                name = attribute.name()
                if name != "uv" and not name.lower().startswith("uv"):
                    continue
                tiles = set()
                for element in elements:
                    value = self._safe(
                        lambda element=element, attribute=attribute: element.attribValue(attribute),
                        (),
                    )
                    if isinstance(value, (tuple, list)) and len(value) >= 2:
                        u, v = int(float(value[0]) // 1), int(float(value[1]) // 1)
                        tiles.add(1001 + u + v * 10)
                result.append({
                    "name": name,
                    "owner": owner,
                    "udimTiles": sorted(tile for tile in tiles if tile >= 1001),
                    **self._uv_measurements(
                        geometry,
                        attribute,
                        owner=owner,
                        reference_resolution=2048,
                    ),
                })
        return sorted(result, key=lambda item: (item["name"], item["owner"]))

    def _uv_measurements(
        self,
        geometry: Any,
        attribute: Any,
        *,
        owner: str,
        reference_resolution: int,
    ) -> dict[str, Any]:
        signatures: dict[tuple[tuple[float, float], ...], int] = {}
        uv_area = 0.0
        world_area = 0.0
        for primitive in self._polygon_primitives(geometry):
            vertices = tuple(primitive.vertices())
            uv_values = []
            positions = []
            for vertex in vertices:
                element = vertex if owner == "vertex" else vertex.point()
                value = element.attribValue(attribute)
                uv_values.append((float(value[0]), float(value[1])))
                positions.append(tuple(float(item) for item in vertex.point().position()))
            signature = tuple(sorted(
                (round(value[0], 9), round(value[1], 9))
                for value in uv_values
            ))
            signatures[signature] = signatures.get(signature, 0) + 1
            for index in range(1, len(vertices) - 1):
                uv_area += self._triangle_area_2d(
                    uv_values[0], uv_values[index], uv_values[index + 1],
                )
                world_area += self._triangle_area_3d(
                    positions[0], positions[index], positions[index + 1],
                )
        if world_area <= 1e-12:
            raise ProductionObservationError(
                "UV texel-density measurement requires nonzero surface area."
            )
        duplicate_count = sum(
            count * (count - 1) // 2
            for count in signatures.values()
        )
        density = reference_resolution * (uv_area / world_area) ** 0.5
        return {
            "referenceTextureResolution": reference_resolution,
            "duplicateUvTriangleCount": {
                "status": "measured", "value": duplicate_count,
            },
            "texelDensity": {
                "status": "measured",
                "value": density,
                "unit": "px_per_scene_unit",
            },
        }

    @staticmethod
    def _triangle_area_2d(
        first: tuple[float, float],
        second: tuple[float, float],
        third: tuple[float, float],
    ) -> float:
        return abs(
            (second[0] - first[0]) * (third[1] - first[1])
            - (second[1] - first[1]) * (third[0] - first[0])
        ) * 0.5

    @staticmethod
    def _triangle_area_3d(
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
        return 0.5 * sum(value * value for value in cross) ** 0.5

    def _topology_quality(self, geometry: Any) -> dict[str, Any]:
        polygon_primitives = self._polygon_primitives(geometry)
        edge_counts: dict[tuple[int, int], int] = {}
        for primitive in polygon_primitives:
            points = [vertex.point().number() for vertex in primitive.vertices()]
            for first, second in zip(points, points[1:] + points[:1]):
                edge = tuple(sorted((first, second)))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
        edge_uses = list(edge_counts.values())
        max_sides = max(
            (len(self._safe(primitive.vertices, ()) or ()) for primitive in polygon_primitives),
            default=0,
        )
        degenerate = sum(
            1 for primitive in polygon_primitives
            if float(self._safe(lambda primitive=primitive: primitive.intrinsicValue("measuredarea"), 0.0) or 0.0) <= 1e-10
        )
        return {
            "manifold": all(count <= 2 for count in edge_uses),
            "watertight": bool(edge_uses) and all(count == 2 for count in edge_uses),
            "maxNgonSides": max_sides,
            "degenerateCount": degenerate,
        }

    def _vector_quality(
        self,
        geometry: Any,
        name: str,
        *,
        reference: str | None = None,
    ) -> dict[str, Any]:
        attribute = geometry.findVertexAttrib(name) or geometry.findPointAttrib(name)
        if attribute is None:
            return {"present": False, "consistent": False, "maxError": 0.0}
        is_vertex = geometry.findVertexAttrib(name) is not None
        polygon_primitives = self._polygon_primitives(geometry)
        reference_attribute = (
            geometry.findVertexAttrib(reference) or geometry.findPointAttrib(reference)
            if reference else None
        )
        reference_is_vertex = (
            reference_attribute is not None
            and geometry.findVertexAttrib(reference) is not None
        )
        use_vertices = is_vertex or reference_is_vertex
        elements = (
            (
                vertex
                for primitive in polygon_primitives
                for vertex in primitive.vertices()
            )
            if use_vertices
            else iter({
                vertex.point().number(): vertex.point()
                for primitive in polygon_primitives
                for vertex in primitive.vertices()
            }.values())
        )
        max_unit_error = 0.0
        max_orthogonal_error = 0.0
        sample_count = 0
        for element in elements:
            value_element = (
                element if is_vertex else element.point()
                if use_vertices else element
            )
            value = self._required(
                lambda value_element=value_element: value_element.attribValue(
                    attribute,
                ),
                f"Could not read {name} vector sample.",
            )
            if not isinstance(value, (tuple, list)) or len(value) < 3:
                raise ProductionObservationError(
                    f"{name} contains a malformed vector sample."
                )
            sample_count += 1
            length = sum(float(component) ** 2 for component in value[:3]) ** 0.5
            max_unit_error = max(max_unit_error, abs(length - 1.0))
            if reference_attribute is not None:
                reference_element = (
                    element if reference_is_vertex else element.point()
                    if use_vertices else element
                )
                ref = self._required(
                    lambda reference_element=reference_element: (
                        reference_element.attribValue(reference_attribute)
                    ),
                    f"Could not read {reference} vector sample.",
                )
                if not isinstance(ref, (tuple, list)) or len(ref) < 3:
                    raise ProductionObservationError(
                        f"{reference} contains a malformed vector sample."
                    )
                dot = abs(sum(float(value[i]) * float(ref[i]) for i in range(3)))
                max_orthogonal_error = max(max_orthogonal_error, dot)
        if sample_count == 0:
            raise ProductionObservationError(
                f"{name} is present but has no measurable polygon samples."
            )
        return {
            "present": True,
            "consistent": max_unit_error <= 1e-3,
            "maxError": max_orthogonal_error if reference else max_unit_error,
        }

    def _material_paths(self, geometry: Any) -> list[str]:
        attribute = geometry.findPrimAttrib("shop_materialpath")
        if attribute is None:
            return []
        values = {
            str(self._safe(lambda prim=prim: prim.stringAttribValue(attribute), "") or "")
            for prim in geometry.prims()
        }
        return sorted(value for value in values if value)

    def _primitive_types(self, geometry: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for primitive in geometry.prims():
            name = str(self._safe(lambda primitive=primitive: primitive.type().name(), "unknown"))
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items()))

    def _polygon_primitives(self, geometry: Any) -> tuple[Any, ...]:
        return tuple(
            primitive
            for primitive in geometry.prims()
            if "polygon" in str(self._safe(
                lambda primitive=primitive: primitive.type().name(), "",
            )).lower()
        )

    def _matching_nodes(self, *tokens: str) -> list[str]:
        return [
            node.path() for node in self._iter_nodes()
            if any(token in node.name().lower() for token in tokens)
        ]

    def _usd_stage(self, node: Any) -> dict[str, Any]:
        if bool(self._required(
            node.needsToCook,
            f"Could not inspect USD cook state at {node.path()}.",
        )):
            raise ProductionObservationError(
                f"Refusing implicit USD cook for dirty node {node.path()}."
            )
        stage = self._required(
            node.stage,
            f"Could not read pre-cooked USD stage at {node.path()}.",
        )
        if stage is None:
            raise ProductionObservationError(f"Node has no pre-cooked USD stage: {node.path()}")
        prims = []
        material_bindings = 0
        for prim in stage.Traverse():
            if len(prims) >= MAX_OBSERVED_USD_PRIMS:
                raise ProductionObservationError(
                    f"USD stage exceeds {MAX_OBSERVED_USD_PRIMS} prims at {node.path()}."
                )
            path = str(prim.GetPath())
            material = prim.GetRelationship("material:binding")
            if material and material.GetTargets():
                material_bindings += 1
            prims.append({
                "path": path,
                "type": prim.GetTypeName(),
                "kind": prim.GetMetadata("kind"),
                "purpose": self._safe(lambda prim=prim: prim.GetAttribute("purpose").Get(), None),
                "variantSets": sorted(prim.GetVariantSets().GetNames()),
                "variantSelections": [
                    {
                        "name": name,
                        "value": prim.GetVariantSet(name).GetVariantSelection(),
                    }
                    for name in sorted(prim.GetVariantSets().GetNames())
                    if prim.GetVariantSet(name).GetVariantSelection()
                ],
                "hasPayload": bool(prim.HasAuthoredPayloads()),
                "hasReference": bool(prim.HasAuthoredReferences()),
            })
        layer = stage.GetRootLayer()
        has_payload = any(item["hasPayload"] for item in prims)
        has_reference = any(item["hasReference"] for item in prims)
        return {
            "nodePath": node.path(),
            "defaultPrim": str(stage.GetDefaultPrim().GetPath()) if stage.GetDefaultPrim() else None,
            "upAxis": str(stage.GetMetadata("upAxis") or ""),
            "metersPerUnit": stage.GetMetadata("metersPerUnit"),
            "primCount": len(prims),
            "materialBindingCount": material_bindings,
            "variantSelections": sorted(
                {
                    (item["name"], item["value"])
                    for prim in prims
                    for item in prim["variantSelections"]
                }
            ),
            "publishArc": (
                "payload" if has_payload
                else "reference" if has_reference
                else "inline"
            ),
            "prims": prims,
            "rootLayer": {
                "identifierDigest": "sha256:" + hashlib.sha256(
                    str(layer.identifier).encode("utf-8"),
                ).hexdigest(),
                "subLayerCount": len(layer.subLayerPaths),
            },
        }

    def _contract_observation(
        self,
        *,
        asset_id: str,
        geometry: list[dict[str, Any]],
        usd: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        names: list[str],
        platform: str,
    ) -> dict[str, Any]:
        if not asset_id.strip() or not geometry or not usd:
            raise ProductionObservationError(
                "Asset contract observation requires asset_id, geometry, and USD."
            )
        geo = geometry[0]
        stage = usd[0]
        material_slots = sorted(path.rsplit("/", 1)[-1] for path in geo["materials"]["paths"])
        lods = geo["contractDelivery"]["lods"]
        collision = geo["contractDelivery"]["collision"]
        instancing = geo["contractDelivery"]["instancing"]
        root_prim = next(
            (prim for prim in stage["prims"] if prim["kind"] in {"component", "assembly", "group"}),
            stage["prims"][0] if stage["prims"] else {"path": "/World", "kind": "assembly", "purpose": None},
        )
        normal = geo["normalQuality"]
        tangent = geo["tangentQuality"]
        dependency_records = {
            (
                "hda" if item["kind"] == "hda" else "asset",
                item["id"],
            ): {
                "id": item["id"],
                "kind": "hda" if item["kind"] == "hda" else "asset",
                "version": item["version"],
                "digest": item["digest"],
            }
            for item in dependencies
        }
        uv_sets = {
            item["name"]: {
                "name": item["name"],
                "udimTiles": item["udimTiles"],
                "duplicateUvTriangleCount": item["duplicateUvTriangleCount"],
                "texelDensity": item["texelDensity"],
            }
            for item in geo["uvDetails"]
        }
        return {
            "assetId": asset_id,
            "space": {
                "metersPerUnit": float(stage.get("metersPerUnit") or 1.0),
                "upAxis": stage.get("upAxis") or "Y",
                "forwardAxis": "-Z",
                "handedness": "right",
            },
            "names": names,
            "geometry": {
                "pivot": geo["objectPivot"],
                "bounds": {
                    "minimum": geo["bounds"]["min"],
                    "maximum": geo["bounds"]["max"],
                },
                "topology": {
                    key: geo["topology"][key]
                    for key in ("manifold", "watertight", "maxNgonSides", "degenerateCount")
                },
                "normals": {
                    "present": normal["present"],
                    "consistent": normal["consistent"],
                    "maxUnitLengthError": normal["maxError"],
                },
                "tangents": {
                    "present": tangent["present"],
                    "orthogonal": tangent["present"] and tangent["maxError"] <= 1e-3,
                    "maxOrthogonalError": tangent["maxError"],
                },
            },
            "surface": {
                "uvSets": [uv_sets[name] for name in sorted(uv_sets)],
                "materialSlots": material_slots,
                # Dependency inspection rejects every ambient file reference,
                # so zero is an observed absence rather than an asserted budget.
                "textureBytes": 0,
            },
            "delivery": {
                "lods": lods,
                "collision": collision,
                "instancing": instancing,
                "platformMetrics": [{
                    "platform": platform,
                    "triangles": sum(item["triangles"] for item in lods),
                    "vertices": geo["topology"]["vertices"],
                    "textureBytes": 0,
                    "materialSlots": len(material_slots),
                    "instances": geo["contractDelivery"]["instanceCount"],
                }],
            },
            "usd": {
                "kind": root_prim["kind"] or "assembly",
                "purpose": root_prim["purpose"] or "default",
                "variantSelections": [
                    {"name": name, "value": value}
                    for name, value in stage["variantSelections"]
                ],
                "rootPrim": root_prim["path"],
                "defaultPrim": stage["defaultPrim"] or root_prim["path"],
                "payload": stage["publishArc"],
            },
            "dependencies": sorted(
                dependency_records.values(),
                key=lambda item: (item["kind"], item["id"]),
            ),
        }

    def _contract_lods(
        self,
        geometry: Any,
    ) -> list[dict[str, Any]]:
        groups = {
            group.name(): tuple(group.prims())
            for group in geometry.primGroups()
            if "lod" in group.name().lower()
        }
        reference_name = next(
            (name for name in groups if name.lower() == "lod0"),
            None,
        )
        if reference_name is None:
            raise ProductionObservationError(
                "Delivered output geometry has no lod0 primitive group."
            )
        reference_primitives = groups[reference_name]
        reference_triangles = sum(
            max(len(primitive.vertices()) - 2, 0)
            for primitive in reference_primitives
        )
        if reference_triangles <= 0:
            raise ProductionObservationError(
                "Delivered lod0 output group has no measurable triangles."
            )
        result = []
        for name, primitives in groups.items():
            triangles = sum(
                max(len(primitive.vertices()) - 2, 0)
                for primitive in primitives
            )
            result.append({
                "name": name,
                "triangles": triangles,
                "vertices": len({
                    vertex.point().number()
                    for primitive in primitives
                    for vertex in primitive.vertices()
                }),
                "relativeTriangleReduction": {
                    "status": "measured",
                    "value": 1.0 - triangles / reference_triangles,
                },
            })
        return sorted(result, key=lambda item: item["name"])

    def _contract_collision(self, geometry: Any) -> dict[str, Any]:
        primitives = [
            primitive
            for group in geometry.primGroups()
            if any(token in group.name().lower() for token in ("collision", "proxy", "ucx"))
            for primitive in group.prims()
        ]
        return {
            "mode": "mesh" if primitives else "none",
            "convex": self._is_convex(primitives),
            "primitives": len(primitives),
            "triangles": sum(max(len(primitive.vertices()) - 2, 0) for primitive in primitives),
        }

    def _is_convex(self, primitives: list[Any]) -> bool:
        if not primitives:
            return False
        if self._primitive_component_count(primitives) != 1:
            return False
        points = {
            vertex.point().number(): tuple(
                float(value) for value in vertex.point().position()
            )
            for primitive in primitives
            for vertex in primitive.vertices()
        }
        if len(primitives) * len(points) > 10_000_000:
            raise ProductionObservationError(
                "Collision convexity measurement exceeds its operation limit."
            )
        for primitive in primitives:
            vertices = tuple(primitive.vertices())
            if len(vertices) < 3:
                return False
            origin = tuple(float(value) for value in vertices[0].point().position())
            normal = tuple(float(value) for value in primitive.normal())
            distances = [
                sum((position[index] - origin[index]) * normal[index] for index in range(3))
                for position in points.values()
            ]
            if min(distances) < -1e-6 and max(distances) > 1e-6:
                return False
        return True

    def _contract_instancing(
        self,
        geometry: Any,
    ) -> tuple[dict[str, Any], int]:
        primitives = tuple(geometry.prims())
        packed = tuple(
            primitive
            for primitive in primitives
            if self._packed_primitive(primitive)
        )
        packed_sources = {
            self._packed_source_identity(primitive)
            for primitive in packed
        }
        point_sources = self._point_instance_sources(geometry)
        unpacked = sum(len(points) for points in point_sources.values())
        report = {
            "used": bool(packed or unpacked),
            "uniqueMeshes": len(packed_sources) + len(point_sources),
            "unpackedInstances": unpacked,
        }
        return report, len(packed) + unpacked

    def _packed_primitive(self, primitive: Any) -> bool:
        type_name = str(self._safe(
            lambda: primitive.type().name(), "",
        )).lower()
        return "packed" in type_name

    def _packed_source_identity(self, primitive: Any) -> tuple[str, str]:
        for intrinsic in ("geometryid", "packedpath", "packedprimname"):
            value = self._safe(
                lambda intrinsic=intrinsic: primitive.intrinsicValue(intrinsic),
                None,
            )
            if value not in (None, ""):
                return intrinsic, repr(value)
        implementation = self._safe(
            lambda: primitive.implementation(), None,
        )
        if implementation is not None:
            return "implementation", str(id(implementation))
        number = self._safe(primitive.number, -1)
        return "primitive", str(number)

    def _point_instance_sources(
        self,
        geometry: Any,
    ) -> dict[tuple[str, str], set[int]]:
        attributes = {
            attribute.name(): attribute
            for attribute in geometry.pointAttribs()
            if attribute.name().lower() in {
                "instance", "instancefile", "instancepath",
            }
        }
        sources: dict[tuple[str, str], set[int]] = {}
        for point in geometry.points():
            for name, attribute in attributes.items():
                value = str(self._safe(
                    lambda point=point, attribute=attribute: (
                        point.stringAttribValue(attribute)
                    ),
                    "",
                ) or "").strip()
                if value:
                    sources.setdefault(
                        (name.lower(), value), set(),
                    ).add(int(point.number()))
                    break
        return sources

    @staticmethod
    def _primitive_component_count(primitives: Iterable[Any]) -> int:
        primitive_values = tuple(primitives)
        pending = {
            primitive.number(): primitive for primitive in primitive_values
        }
        point_to_primitives: dict[int, set[int]] = {}
        for primitive in primitive_values:
            for vertex in primitive.vertices():
                point_to_primitives.setdefault(
                    vertex.point().number(), set(),
                ).add(primitive.number())
        component_count = 0
        while pending:
            component_count += 1
            frontier = [next(iter(pending))]
            while frontier:
                number = frontier.pop()
                primitive = pending.pop(number, None)
                if primitive is None:
                    continue
                for vertex in primitive.vertices():
                    frontier.extend(
                        point_to_primitives[vertex.point().number()] & pending.keys()
                    )
        return component_count

    def _dependencies(self) -> list[dict[str, Any]]:
        dependencies: dict[tuple[str, str, str], dict[str, Any]] = {}
        total_hda_bytes = 0
        for node in self._iter_nodes():
            hda = self._hda_dependency(node)
            if hda is not None:
                key, record, byte_count = hda
                dependencies[key] = record
                total_hda_bytes += byte_count
            for key, record in self._file_dependencies(node):
                dependencies[key] = record
            if total_hda_bytes > MAX_OBSERVED_HDA_BYTES:
                raise ProductionObservationError(
                    "Fixture HDA definitions exceed the 256 MiB observation limit."
                )
            if len(dependencies) > MAX_OBSERVED_DEPENDENCIES:
                raise ProductionObservationError(
                    f"Fixture exceeds {MAX_OBSERVED_DEPENDENCIES} dependencies."
                )
        return [dependencies[key] for key in sorted(dependencies)]

    def _hda_dependency(
        self,
        node: Any,
    ) -> tuple[tuple[str, str, str], dict[str, Any], int] | None:
        definition = self._required(
            lambda: node.type().definition(),
            f"Could not inspect HDA definition at {node.path()}.",
        )
        if definition is None:
            return None
        version = self._portable_version(
            str(self._safe(definition.version, "") or ""),
        )
        cache_key = (node.type().nameWithCategory(), version)
        cached = self._hda_cache.get(cache_key)
        if cached is not None:
            cached_record, cached_bytes = cached
            return (
                ("hda", node.path(), cached_record["digest"]),
                {**cached_record, "nodePath": node.path()},
                cached_bytes,
            )
        sections = self._required(
            definition.sections,
            f"Could not enumerate HDA sections at {node.path()}.",
        ) or {}
        if len(sections) > 128:
            raise ProductionObservationError(
                f"HDA definition exceeds 128 sections at {node.path()}."
            )
        receipts, total_bytes = [], 0
        for name in sorted(sections):
            try:
                content = sections[name].binaryContents()
            except Exception as exc:
                raise ProductionObservationError(
                    f"Could not read HDA section bytes at {node.path()}."
                ) from exc
            if not isinstance(content, (bytes, bytearray)):
                raise ProductionObservationError(
                    f"HDA section did not return bytes at {node.path()}."
                )
            content = bytes(content)
            total_bytes += len(content)
            if total_bytes > 64 * 1024 * 1024:
                raise ProductionObservationError(
                    f"HDA definition exceeds 64 MiB at {node.path()}."
                )
            receipts.append({
                "name": name,
                "bytes": len(content),
                "digest": hashlib.sha256(content).hexdigest(),
            })
        identity = json.dumps({
            "type": node.type().nameWithCategory(),
            "version": str(self._safe(definition.version, "") or ""),
            "sections": receipts,
        }, sort_keys=True, separators=(",", ":"))
        record = {
            "kind": "hda",
            "nodePath": node.path(),
            "id": self._portable_id(node.type().nameWithCategory()),
            "version": version,
            "digest": "sha256:" + hashlib.sha256(
                identity.encode("utf-8"),
            ).hexdigest(),
            "byteLength": total_bytes,
        }
        self._hda_cache[cache_key] = ({**record, "nodePath": ""}, total_bytes)
        return ("hda", node.path(), identity), record, total_bytes

    def _file_dependencies(
        self,
        node: Any,
    ) -> list[tuple[tuple[str, str, str], dict[str, Any]]]:
        result = []
        parms = self._required(
            node.parms,
            f"Could not enumerate parameters at {node.path()}.",
        )
        for parm in parms or ():
            template = self._required(
                parm.parmTemplate,
                f"Could not inspect parameter template at {parm.path()}.",
            )
            template_type = str(self._required(
                lambda template=template: template.type().name(),
                f"Could not inspect parameter type at {parm.path()}.",
            ))
            if template_type != "String":
                continue
            string_type = str(self._required(
                lambda template=template: template.stringType().name(),
                f"Could not inspect parameter string type at {parm.path()}.",
            ))
            if "FileReference" not in string_type:
                continue
            value = str(self._required(
                parm.unexpandedString,
                f"Could not inspect file dependency at {parm.path()}.",
            ) or "")
            if not value:
                continue
            if value.startswith(("/obj/", "/stage/", "/mat/")):
                continue
            raise ProductionObservationError(
                "Ambient file dependency lacks an approved bounded byte receipt "
                f"at {parm.path()}."
            )
        return result

    @staticmethod
    def _intrinsic(geometry: Any, name: str, default: Any) -> Any:
        try:
            return geometry.intrinsicValue(name)
        except Exception:
            return default

    @staticmethod
    def _required_intrinsic_count(
        geometry: Any,
        name: str,
        node_path: str,
    ) -> int:
        try:
            value = geometry.intrinsicValue(name)
        except Exception as exc:
            raise ProductionObservationError(
                f"Could not read required geometry intrinsic {name} at {node_path}."
            ) from exc
        if type(value) is not int or value < 0:
            raise ProductionObservationError(
                f"Required geometry intrinsic {name} is invalid at {node_path}."
            )
        return value

    @staticmethod
    def _required_edge_count(
        geometry: Any,
        *,
        admitted_vertices: int,
        node_path: str,
    ) -> int:
        try:
            edges = geometry.globEdges("*")
            if not isinstance(edges, (tuple, list)):
                raise TypeError(
                    "globEdges('*') did not return a bounded edge collection"
                )
            count = len(edges)
        except Exception as exc:
            raise ProductionObservationError(
                f"Could not enumerate geometry edges at {node_path}."
            ) from exc
        if count > admitted_vertices or count > MAX_OBSERVED_EDGES:
            raise ProductionObservationError(
                f"Geometry edge count exceeds its admitted bound at {node_path}."
            )
        return count

    @staticmethod
    def _portable_id(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", ".", str(value)).strip(".")
        if not cleaned or not cleaned[0].isalpha():
            cleaned = "dependency." + cleaned
        return cleaned[:128]

    @staticmethod
    def _portable_version(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._+-]+", ".", str(value)).strip(".")
        return (cleaned or "builtin")[:128]

    @staticmethod
    def _metrics(
        geometry: list[dict[str, Any]],
        usd: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        elapsed_ms: float,
    ) -> dict[str, Any]:
        return {
            "observationMs": elapsed_ms,
            "geometryCount": len(geometry),
            "pointCount": sum(item["topology"]["points"] for item in geometry),
            "primitiveCount": sum(item["topology"]["primitives"] for item in geometry),
            "vertexCount": sum(item["topology"]["vertices"] for item in geometry),
            "geometryMemoryBytes": sum(item["memoryBytes"] for item in geometry),
            "usdStageCount": len(usd),
            "usdPrimCount": sum(item["primCount"] for item in usd),
            "dependencyCount": len(dependencies),
        }

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
