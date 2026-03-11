"""Semantic procedural building tools."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class BuildingOperationsMixin:
    _BUILDING_KIND_KEY = "hpmcp.building.kind"
    _BUILDING_OUT_KEY = "hpmcp.building.out"
    _BUILDING_MASSING_MERGE_KEY = "hpmcp.building.massing_merge"
    _BUILDING_DETAIL_MERGE_KEY = "hpmcp.building.detail_merge"
    _BUILDING_STYLE_KEY = "hpmcp.building.style"
    _BUILDING_CORE_KEY = "hpmcp.building.core"
    _BUILDING_SEGMENTS_KEY = "hpmcp.building.segments"
    _BUILDING_MASSING_SPEC_KEY = "hpmcp.building.massing.spec"
    _BUILDING_ENVELOPE_KEY = "hpmcp.building.envelope"

    def _mark_building_network(
        self,
        building_node: Any,
        out_node: Any,
        massing_merge: Any,
        *,
        segment_paths: dict[str, str],
        massing_spec: dict[str, float],
    ) -> None:
        building_node.setUserData(self._BUILDING_KIND_KEY, "tower")
        building_node.setUserData(self._BUILDING_OUT_KEY, out_node.path())
        building_node.setUserData(self._BUILDING_MASSING_MERGE_KEY, massing_merge.path())
        building_node.setUserData(self._BUILDING_SEGMENTS_KEY, json.dumps(segment_paths, ensure_ascii=True))
        building_node.setUserData(self._BUILDING_MASSING_SPEC_KEY, json.dumps(massing_spec, ensure_ascii=True))

    def _require_building_network(self, building_path: str) -> tuple[Any, Any]:
        building_node = self._require_node_by_path(building_path)
        if self._safe_value(lambda: building_node.userData(self._BUILDING_KIND_KEY), "") != "tower":
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Node is not a HocusPocus building network: {building_path}",
                {"path": building_path},
            )
        out_path = self._safe_value(lambda: building_node.userData(self._BUILDING_OUT_KEY), "") or ""
        out_node = self._require_node_by_path(out_path, label="building output")
        return building_node, out_node

    def _building_segment_paths(self, building_node: Any) -> dict[str, str]:
        raw = self._safe_value(lambda: building_node.userData(self._BUILDING_SEGMENTS_KEY), "") or ""
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return {str(key): str(value) for key, value in payload.items()}
        except Exception:
            pass
        return {}

    def _building_massing_spec(self, building_node: Any) -> dict[str, float]:
        raw = self._safe_value(lambda: building_node.userData(self._BUILDING_MASSING_SPEC_KEY), "") or ""
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return {str(key): float(value) for key, value in payload.items()}
        except Exception:
            pass
        return {}

    def _destroy_building_children(self, building_node: Any, prefixes: tuple[str, ...]) -> list[str]:
        destroyed: list[str] = []
        for child in list(self._safe_value(building_node.children, []) or []):
            name = self._safe_value(child.name, "") or ""
            if any(name.startswith(prefix) for prefix in prefixes):
                destroyed.append(child.path())
                child.destroy()
        if destroyed:
            self._sync_grid_state_for_parent(building_node)
        return destroyed

    def _create_sop_node(self, parent: Any, node_type_name: str, node_name: str) -> Any:
        node = parent.createNode(node_type_name, node_name)
        self._place_node_on_grid(parent, node)
        return node

    def _create_subnet_node(self, parent: Any, node_name: str) -> Any:
        return self._create_sop_node(parent, "subnet", node_name)

    def _finalize_subnet_output(self, subnet: Any, source_node: Any) -> Any:
        output_node = subnet.createNode("output", "output1")
        output_node.setInput(0, source_node)
        self._safe_value(output_node.moveToGoodPosition)
        return output_node

    def _set_parm_if_present(self, node: Any, parm_name: str, value: Any) -> None:
        parm = self._safe_value(lambda: node.parm(parm_name), None)
        if parm is not None:
            parm.set(value)

    def _configure_copyxform(
        self,
        node: Any,
        *,
        copies: int,
        tx: float = 0.0,
        ty: float = 0.0,
        tz: float = 0.0,
    ) -> None:
        self._set_parm_if_present(node, "ncy", max(1, copies))
        self._set_parm_if_present(node, "tx", tx)
        self._set_parm_if_present(node, "ty", ty)
        self._set_parm_if_present(node, "tz", tz)

    def _next_merge_input_index(self, merge_node: Any) -> int:
        inputs = self._safe_value(merge_node.inputs, []) or []
        for index, item in enumerate(inputs):
            if item is None:
                return index
        return len(inputs)

    def _ensure_detail_merge(self, building_node: Any, out_node: Any) -> Any:
        detail_merge_path = self._safe_value(lambda: building_node.userData(self._BUILDING_DETAIL_MERGE_KEY), "") or ""
        if detail_merge_path:
            merge_node = self._safe_value(lambda: self._require_node_by_path(detail_merge_path), None)
            if merge_node is not None:
                return merge_node

        parent = building_node
        merge_node = self._create_sop_node(parent, "merge", "DETAIL_merge")
        input_connections = self._safe_value(out_node.inputConnections, []) or []
        if input_connections:
            current_source = input_connections[0].inputNode()
            current_output = input_connections[0].outputIndex()
            if current_source is not None:
                merge_node.setInput(0, current_source, current_output)
        out_node.setInput(0, merge_node)
        building_node.setUserData(self._BUILDING_DETAIL_MERGE_KEY, merge_node.path())
        return merge_node

    def _building_summary(self, building_node: Any) -> dict[str, Any]:
        out_path = self._safe_value(lambda: building_node.userData(self._BUILDING_OUT_KEY), "") or ""
        out_node = self._require_node_by_path(out_path, label="building output")
        geometry = self._geometry_summary_for_node(out_node)
        refs = {
            "out": out_node.path(),
            "massingMerge": self._safe_value(lambda: building_node.userData(self._BUILDING_MASSING_MERGE_KEY), None),
            "detailMerge": self._safe_value(lambda: building_node.userData(self._BUILDING_DETAIL_MERGE_KEY), None),
            "core": self._safe_value(lambda: building_node.userData(self._BUILDING_CORE_KEY), None),
            "envelope": self._safe_value(lambda: building_node.userData(self._BUILDING_ENVELOPE_KEY), None),
        }
        return {
            "buildingNode": self._node_summary(building_node),
            "outputNode": self._node_summary(out_node),
            "geometry": geometry,
            "refs": refs,
            "styleProfile": self._safe_value(lambda: building_node.userData(self._BUILDING_STYLE_KEY), None),
        }

    def _building_generate_massing_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parent_path = str(arguments.get("parent_path", "/obj")).strip() or "/obj"
        building_name = str(arguments.get("node_name", "tower_massing1")).strip() or "tower_massing1"
        width = float(arguments.get("width", 12.0))
        depth = float(arguments.get("depth", 10.0))
        height = float(arguments.get("height", 60.0))
        podium_height = float(arguments.get("podium_height", max(8.0, height * 0.14)))
        upper_setback_ratio = float(arguments.get("upper_setback_ratio", 0.78))
        top_setback_ratio = float(arguments.get("top_setback_ratio", 0.58))
        bevel_radius = float(arguments.get("bevel_radius", 0.18))

        if width <= 0 or depth <= 0 or height <= 0:
            raise JsonRpcError(INVALID_PARAMS, "width, depth, and height must be greater than 0.")
        if podium_height <= 0 or podium_height >= height:
            raise JsonRpcError(INVALID_PARAMS, "podium_height must be greater than 0 and less than height.")
        if not (0.2 <= upper_setback_ratio <= 1.0):
            raise JsonRpcError(INVALID_PARAMS, "upper_setback_ratio must be between 0.2 and 1.0.")
        if not (0.15 <= top_setback_ratio <= upper_setback_ratio):
            raise JsonRpcError(INVALID_PARAMS, "top_setback_ratio must be between 0.15 and upper_setback_ratio.")

        remaining = height - podium_height
        mid_height = remaining * 0.62
        top_height = remaining - mid_height
        upper_width = width * upper_setback_ratio
        upper_depth = depth * upper_setback_ratio
        top_width = width * top_setback_ratio
        top_depth = depth * top_setback_ratio

        parent = self._require_node_by_path(parent_path, label="parent_path")
        if not self._safe_value(parent.isNetwork, False):
            raise JsonRpcError(INVALID_PARAMS, f"Parent is not a network: {parent_path}")

        building_node = self._create_sop_node(parent, "geo", building_name)
        file_node = self._safe_value(lambda: building_node.node("file1"), None)
        if file_node is not None:
            file_node.destroy()

        podium = self._create_sop_node(building_node, "box", "PODIUM_box")
        self._set_parm_if_present(podium, "sizex", width)
        self._set_parm_if_present(podium, "sizey", podium_height)
        self._set_parm_if_present(podium, "sizez", depth)
        self._set_parm_if_present(podium, "ty", podium_height * 0.5)

        shaft = self._create_sop_node(building_node, "box", "SHAFT_box")
        self._set_parm_if_present(shaft, "sizex", upper_width)
        self._set_parm_if_present(shaft, "sizey", mid_height)
        self._set_parm_if_present(shaft, "sizez", upper_depth)
        self._set_parm_if_present(shaft, "ty", podium_height + (mid_height * 0.5))

        crown = self._create_sop_node(building_node, "box", "CROWN_box")
        self._set_parm_if_present(crown, "sizex", top_width)
        self._set_parm_if_present(crown, "sizey", top_height)
        self._set_parm_if_present(crown, "sizez", top_depth)
        self._set_parm_if_present(crown, "ty", podium_height + mid_height + (top_height * 0.5))

        merge = self._create_sop_node(building_node, "merge", "MASSING_merge")
        merge.setInput(0, podium)
        merge.setInput(1, shaft)
        merge.setInput(2, crown)

        bevel = self._create_sop_node(building_node, "polybevel", "MASSING_bevel")
        bevel.setInput(0, merge)
        self._set_parm_if_present(bevel, "offset", bevel_radius)
        self._set_parm_if_present(bevel, "filletshape", 0)

        normal = self._create_sop_node(building_node, "normal", "MASSING_normal")
        normal.setInput(0, bevel)

        out_node = self._create_sop_node(building_node, "null", "OUT_building")
        out_node.setInput(0, normal)
        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))

        self._mark_building_network(
            building_node,
            out_node,
            merge,
            segment_paths={
                "podium": podium.path(),
                "shaft": shaft.path(),
                "crown": crown.path(),
            },
            massing_spec={
                "width": width,
                "depth": depth,
                "height": height,
                "podiumHeight": podium_height,
                "midHeight": mid_height,
                "topHeight": top_height,
                "upperWidth": upper_width,
                "upperDepth": upper_depth,
                "topWidth": top_width,
                "topDepth": top_depth,
            },
        )
        self._sync_grid_state_for_parent(building_node)

        summary = self._building_summary(building_node)
        summary["massing"] = {
            "width": width,
            "depth": depth,
            "height": height,
            "podiumHeight": podium_height,
            "upperSetbackRatio": upper_setback_ratio,
            "topSetbackRatio": top_setback_ratio,
        }
        return summary

    def building_generate_massing(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_generate_massing_impl(arguments), context)
        return self._tool_response(f"Generated building massing {data['buildingNode']['path']}.", data)

    def _building_add_envelope_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        wall_thickness = float(arguments.get("wall_thickness", 0.45))
        floor_clearance = float(arguments.get("floor_clearance", 0.08))

        if wall_thickness <= 0:
            raise JsonRpcError(INVALID_PARAMS, "wall_thickness must be greater than 0.")

        building_node, out_node = self._require_building_network(building_path)
        spec = self._building_massing_spec(building_node)
        segments = self._building_segment_paths(building_node)
        if not spec or not segments:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Building network is missing massing metadata: {building_path}",
                {"path": building_path},
            )

        removed_paths = self._destroy_building_children(
            building_node,
            ("ENVELOPE_merge", "PODIUM_SHELL_", "SHAFT_SHELL_", "CROWN_SHELL_", "ENVELOPE_SYS"),
        )
        self._safe_value(lambda: building_node.destroyUserData(self._BUILDING_ENVELOPE_KEY))
        detail_merge = self._ensure_detail_merge(building_node, out_node)
        envelope_subnet = self._create_subnet_node(building_node, "ENVELOPE_SYS")
        envelope_merge = envelope_subnet.createNode("merge", "merge_segments")
        detail_merge.setInput(0, envelope_subnet)
        building_node.setUserData(self._BUILDING_ENVELOPE_KEY, envelope_subnet.path())

        created_paths: list[str] = [envelope_subnet.path()]
        segment_specs = [
            ("PODIUM", segments["podium"], spec["width"], spec["depth"], spec["podiumHeight"], spec["podiumHeight"] * 0.5),
            ("SHAFT", segments["shaft"], spec["upperWidth"], spec["upperDepth"], spec["midHeight"], spec["podiumHeight"] + (spec["midHeight"] * 0.5)),
            ("CROWN", segments["crown"], spec["topWidth"], spec["topDepth"], spec["topHeight"], spec["podiumHeight"] + spec["midHeight"] + (spec["topHeight"] * 0.5)),
        ]

        input_index = 0
        for label, _, outer_width, outer_depth, outer_height, center_y in segment_specs:
            outer = envelope_subnet.createNode("box", f"{label}_SHELL_OUTER")
            self._set_parm_if_present(outer, "sizex", outer_width)
            self._set_parm_if_present(outer, "sizey", outer_height)
            self._set_parm_if_present(outer, "sizez", outer_depth)
            self._set_parm_if_present(outer, "ty", center_y)

            inner = envelope_subnet.createNode("box", f"{label}_SHELL_INNER")
            self._set_parm_if_present(inner, "sizex", max(outer_width - (wall_thickness * 2.0), wall_thickness))
            self._set_parm_if_present(inner, "sizey", max(outer_height - (floor_clearance * 2.0), floor_clearance))
            self._set_parm_if_present(inner, "sizez", max(outer_depth - (wall_thickness * 2.0), wall_thickness))
            self._set_parm_if_present(inner, "ty", center_y)

            shell = envelope_subnet.createNode("boolean", f"{label}_SHELL_BOOLEAN")
            self._set_parm_if_present(shell, "booleanop", 1)
            shell.setInput(0, outer)
            shell.setInput(1, inner)
            envelope_merge.setInput(input_index, shell)
            input_index += 1
            created_paths.extend([outer.path(), inner.path(), shell.path()])

        self._finalize_subnet_output(envelope_subnet, envelope_merge)
        self._safe_value(envelope_subnet.layoutChildren)
        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["envelope"] = {
            "wallThickness": wall_thickness,
            "createdNodePaths": created_paths,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_envelope(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_envelope_impl(arguments), context)
        return self._tool_response(
            f"Added building envelope to {data['buildingNode']['path']}.",
            data,
        )

    def _building_add_structural_bands_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        count = int(arguments.get("count", 3))
        band_height = float(arguments.get("band_height", 0.55))
        overhang_ratio = float(arguments.get("overhang_ratio", 1.06))
        start_ratio = float(arguments.get("start_ratio", 0.18))
        end_ratio = float(arguments.get("end_ratio", 0.86))

        if count <= 0:
            raise JsonRpcError(INVALID_PARAMS, "count must be greater than 0.")
        if band_height <= 0:
            raise JsonRpcError(INVALID_PARAMS, "band_height must be greater than 0.")

        building_node, out_node = self._require_building_network(building_path)
        removed_paths = self._destroy_building_children(building_node, ("BAND_", "BAND_SYS"))
        geom = self._geometry_summary_for_node(out_node)
        width = float(geom["bboxMax"][0] - geom["bboxMin"][0])
        depth = float(geom["bboxMax"][2] - geom["bboxMin"][2])
        base_y = float(geom["bboxMin"][1])
        top_y = float(geom["bboxMax"][1])
        total_height = max(top_y - base_y, band_height)
        merge_node = self._ensure_detail_merge(building_node, out_node)

        start_y = base_y + (total_height * start_ratio)
        end_y = base_y + (total_height * end_ratio)
        band_spacing = (end_y - start_y) / max(count - 1, 1)

        band_subnet = self._create_subnet_node(building_node, "BAND_SYS")
        band_source = band_subnet.createNode("box", "source_band")
        self._set_parm_if_present(band_source, "sizex", width * overhang_ratio)
        self._set_parm_if_present(band_source, "sizey", band_height)
        self._set_parm_if_present(band_source, "sizez", depth * overhang_ratio)
        self._set_parm_if_present(band_source, "ty", start_y)

        band_repeat = band_subnet.createNode("copyxform", "repeat_bands")
        band_repeat.setInput(0, band_source)
        self._configure_copyxform(band_repeat, copies=count, ty=band_spacing)

        self._finalize_subnet_output(band_subnet, band_repeat)
        self._safe_value(band_subnet.layoutChildren)
        merge_node.setInput(self._next_merge_input_index(merge_node), band_subnet)
        created_paths = [band_subnet.path(), band_source.path(), band_repeat.path()]

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["structuralBands"] = {
            "count": count,
            "bandHeight": band_height,
            "createdNodePaths": created_paths,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_structural_bands(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_structural_bands_impl(arguments), context)
        return self._tool_response(
            f"Added {data['structuralBands']['count']} structural band(s) to {data['buildingNode']['path']}.",
            data,
        )

    def _building_add_rooftop_mech_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        unit_count = int(arguments.get("unit_count", 3))
        unit_height = float(arguments.get("unit_height", 1.8))
        footprint_ratio = float(arguments.get("footprint_ratio", 0.2))
        setback_ratio = float(arguments.get("setback_ratio", 0.16))

        if unit_count <= 0:
            raise JsonRpcError(INVALID_PARAMS, "unit_count must be greater than 0.")
        if unit_height <= 0:
            raise JsonRpcError(INVALID_PARAMS, "unit_height must be greater than 0.")

        building_node, out_node = self._require_building_network(building_path)
        removed_paths = self._destroy_building_children(building_node, ("ROOF_MECH_", "ROOF_MECH_SYS"))
        geom = self._geometry_summary_for_node(out_node)
        width = float(geom["bboxMax"][0] - geom["bboxMin"][0])
        depth = float(geom["bboxMax"][2] - geom["bboxMin"][2])
        top_y = float(geom["bboxMax"][1])

        unit_width = max(width * footprint_ratio, 0.6)
        unit_depth = max(depth * footprint_ratio, 0.6)
        merge_node = self._ensure_detail_merge(building_node, out_node)
        mech_subnet = self._create_subnet_node(building_node, "ROOF_MECH_SYS")
        roof_plate = mech_subnet.createNode("box", "roof_zone")
        self._set_parm_if_present(roof_plate, "sizex", max(width * (1.0 - setback_ratio * 1.8), unit_width * 2.0))
        self._set_parm_if_present(roof_plate, "sizey", 0.05)
        self._set_parm_if_present(roof_plate, "sizez", max(depth * (1.0 - setback_ratio * 1.8), unit_depth * 2.0))
        self._set_parm_if_present(roof_plate, "ty", top_y + 0.025)

        scatter = mech_subnet.createNode("scatter", "scatter_roof_units")
        scatter.setInput(0, roof_plate)
        self._set_parm_if_present(scatter, "forcetotal", 1)
        self._set_parm_if_present(scatter, "npts", unit_count)
        self._set_parm_if_present(scatter, "seed", 11)
        self._set_parm_if_present(scatter, "relaxpoints", 1)
        self._set_parm_if_present(scatter, "relaxiterations", 20)

        base_unit = mech_subnet.createNode("box", "unit_module")
        self._set_parm_if_present(base_unit, "sizex", unit_width)
        self._set_parm_if_present(base_unit, "sizey", unit_height)
        self._set_parm_if_present(base_unit, "sizez", unit_depth)
        copy_to_points = mech_subnet.createNode("copytopoints", "copy_units_to_roof")
        copy_to_points.setInput(0, base_unit)
        copy_to_points.setInput(1, scatter)

        lift = mech_subnet.createNode("xform", "lift_units")
        lift.setInput(0, copy_to_points)
        self._set_parm_if_present(lift, "ty", unit_height * 0.5)

        self._finalize_subnet_output(mech_subnet, lift)
        self._safe_value(mech_subnet.layoutChildren)
        merge_node.setInput(self._next_merge_input_index(merge_node), mech_subnet)
        created_paths = [mech_subnet.path(), roof_plate.path(), scatter.path(), base_unit.path(), copy_to_points.path(), lift.path()]

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["rooftopMechanical"] = {
            "unitCount": unit_count,
            "unitHeight": unit_height,
            "createdNodePaths": created_paths,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_rooftop_mech(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_rooftop_mech_impl(arguments), context)
        return self._tool_response(
            f"Added rooftop mechanical detail to {data['buildingNode']['path']}.",
            data,
        )

    def _building_add_window_grid_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        floors = int(arguments.get("floors", 18))
        columns = int(arguments.get("columns", 6))
        frame_thickness = float(arguments.get("frame_thickness", 0.18))
        frame_depth = float(arguments.get("frame_depth", 0.25))
        sill_height = float(arguments.get("sill_height", 1.2))
        head_height = float(arguments.get("head_height", 3.2))
        inset = float(arguments.get("inset", 0.12))

        if floors <= 0 or columns <= 0:
            raise JsonRpcError(INVALID_PARAMS, "floors and columns must be greater than 0.")
        if frame_thickness <= 0 or frame_depth <= 0:
            raise JsonRpcError(INVALID_PARAMS, "frame_thickness and frame_depth must be greater than 0.")
        if head_height <= sill_height:
            raise JsonRpcError(INVALID_PARAMS, "head_height must be greater than sill_height.")

        building_node, out_node = self._require_building_network(building_path)
        removed_paths = self._destroy_building_children(building_node, ("WINDOW_", "WINDOW_SYS"))
        geom = self._geometry_summary_for_node(out_node)
        bbox_min = geom["bboxMin"]
        bbox_max = geom["bboxMax"]
        width = float(bbox_max[0] - bbox_min[0])
        depth = float(bbox_max[2] - bbox_min[2])
        total_height = float(bbox_max[1] - bbox_min[1])
        usable_height = max(total_height - (sill_height * 1.2), head_height)
        floor_spacing = usable_height / max(floors, 1)
        column_spacing = width / max(columns, 1)

        merge_node = self._ensure_detail_merge(building_node, out_node)
        window_subnet = self._create_subnet_node(building_node, "WINDOW_SYS")
        created_paths: list[str] = [window_subnet.path()]

        front_z = (depth * 0.5) - inset
        back_z = -front_z
        side_x = (width * 0.5) - inset
        base_x = (-width * 0.5) + (column_spacing * 0.5)
        base_y = sill_height + (floor_spacing * 0.5)

        front_vertical = window_subnet.createNode("box", "front_vertical_src")
        self._set_parm_if_present(front_vertical, "sizex", frame_thickness)
        self._set_parm_if_present(front_vertical, "sizey", usable_height)
        self._set_parm_if_present(front_vertical, "sizez", frame_depth)
        self._set_parm_if_present(front_vertical, "tx", base_x)
        self._set_parm_if_present(front_vertical, "ty", (usable_height * 0.5) + sill_height)
        self._set_parm_if_present(front_vertical, "tz", front_z)

        front_vertical_repeat = window_subnet.createNode("copyxform", "front_vertical_repeat")
        front_vertical_repeat.setInput(0, front_vertical)
        self._configure_copyxform(front_vertical_repeat, copies=columns, tx=column_spacing)

        back_vertical = window_subnet.createNode("box", "back_vertical_src")
        self._set_parm_if_present(back_vertical, "sizex", frame_thickness)
        self._set_parm_if_present(back_vertical, "sizey", usable_height)
        self._set_parm_if_present(back_vertical, "sizez", frame_depth)
        self._set_parm_if_present(back_vertical, "tx", base_x)
        self._set_parm_if_present(back_vertical, "ty", (usable_height * 0.5) + sill_height)
        self._set_parm_if_present(back_vertical, "tz", back_z)

        back_vertical_repeat = window_subnet.createNode("copyxform", "back_vertical_repeat")
        back_vertical_repeat.setInput(0, back_vertical)
        self._configure_copyxform(back_vertical_repeat, copies=columns, tx=column_spacing)

        front_horizontal = window_subnet.createNode("box", "front_horizontal_src")
        self._set_parm_if_present(front_horizontal, "sizex", width)
        self._set_parm_if_present(front_horizontal, "sizey", frame_thickness)
        self._set_parm_if_present(front_horizontal, "sizez", frame_depth)
        self._set_parm_if_present(front_horizontal, "ty", base_y)
        self._set_parm_if_present(front_horizontal, "tz", front_z)

        front_horizontal_repeat = window_subnet.createNode("copyxform", "front_horizontal_repeat")
        front_horizontal_repeat.setInput(0, front_horizontal)
        self._configure_copyxform(front_horizontal_repeat, copies=floors, ty=floor_spacing)

        back_horizontal = window_subnet.createNode("box", "back_horizontal_src")
        self._set_parm_if_present(back_horizontal, "sizex", width)
        self._set_parm_if_present(back_horizontal, "sizey", frame_thickness)
        self._set_parm_if_present(back_horizontal, "sizez", frame_depth)
        self._set_parm_if_present(back_horizontal, "ty", base_y)
        self._set_parm_if_present(back_horizontal, "tz", back_z)

        back_horizontal_repeat = window_subnet.createNode("copyxform", "back_horizontal_repeat")
        back_horizontal_repeat.setInput(0, back_horizontal)
        self._configure_copyxform(back_horizontal_repeat, copies=floors, ty=floor_spacing)

        side_strip = window_subnet.createNode("box", "side_strip_src")
        self._set_parm_if_present(side_strip, "sizex", frame_depth)
        self._set_parm_if_present(side_strip, "sizey", frame_thickness)
        self._set_parm_if_present(side_strip, "sizez", depth * 0.82)
        self._set_parm_if_present(side_strip, "tx", -side_x)
        self._set_parm_if_present(side_strip, "ty", base_y)

        side_vertical_repeat = window_subnet.createNode("copyxform", "side_y_repeat")
        side_vertical_repeat.setInput(0, side_strip)
        self._configure_copyxform(side_vertical_repeat, copies=floors, ty=floor_spacing)

        side_pair_repeat = window_subnet.createNode("copyxform", "side_x_repeat")
        side_pair_repeat.setInput(0, side_vertical_repeat)
        self._configure_copyxform(side_pair_repeat, copies=2, tx=side_x * 2.0)

        frame_merge = window_subnet.createNode("merge", "merge_facade")
        for index, system_node in enumerate((
            front_vertical_repeat,
            back_vertical_repeat,
            front_horizontal_repeat,
            back_horizontal_repeat,
            side_pair_repeat,
        )):
            frame_merge.setInput(index, system_node)

        self._finalize_subnet_output(window_subnet, frame_merge)
        self._safe_value(window_subnet.layoutChildren)
        merge_node.setInput(self._next_merge_input_index(merge_node), window_subnet)

        created_paths.extend([
            front_vertical.path(),
            front_vertical_repeat.path(),
            back_vertical.path(),
            back_vertical_repeat.path(),
            front_horizontal.path(),
            front_horizontal_repeat.path(),
            back_horizontal.path(),
            back_horizontal_repeat.path(),
            side_strip.path(),
            side_vertical_repeat.path(),
            side_pair_repeat.path(),
            frame_merge.path(),
        ])

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["windowGrid"] = {
            "floors": floors,
            "columns": columns,
            "frameThickness": frame_thickness,
            "frameDepth": frame_depth,
            "createdNodeCount": len(created_paths),
            "createdNodePaths": created_paths,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_window_grid(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_window_grid_impl(arguments), context)
        return self._tool_response(
            f"Added window-grid articulation to {data['buildingNode']['path']}.",
            data,
        )

    def _building_add_floor_stack_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        floor_count = int(arguments.get("floor_count", 18))
        slab_thickness = float(arguments.get("slab_thickness", 0.32))
        inset_ratio = float(arguments.get("inset_ratio", 0.06))
        base_clearance = float(arguments.get("base_clearance", 0.25))

        if floor_count <= 0:
            raise JsonRpcError(INVALID_PARAMS, "floor_count must be greater than 0.")
        if slab_thickness <= 0:
            raise JsonRpcError(INVALID_PARAMS, "slab_thickness must be greater than 0.")
        if not (0.0 <= inset_ratio < 0.45):
            raise JsonRpcError(INVALID_PARAMS, "inset_ratio must be between 0.0 and 0.45.")

        building_node, out_node = self._require_building_network(building_path)
        removed_paths = self._destroy_building_children(building_node, ("FLOOR_", "FLOOR_SYS"))
        geom = self._geometry_summary_for_node(out_node)
        bbox_min = geom["bboxMin"]
        bbox_max = geom["bboxMax"]
        width = float(bbox_max[0] - bbox_min[0])
        depth = float(bbox_max[2] - bbox_min[2])
        total_height = float(bbox_max[1] - bbox_min[1])

        slab_width = width * (1.0 - (inset_ratio * 2.0))
        slab_depth = depth * (1.0 - (inset_ratio * 2.0))
        usable_height = max(total_height - base_clearance - slab_thickness, slab_thickness)
        floor_spacing = usable_height / max(floor_count - 1, 1)

        merge_node = self._ensure_detail_merge(building_node, out_node)
        floor_subnet = self._create_subnet_node(building_node, "FLOOR_SYS")
        slab = floor_subnet.createNode("box", "slab_src")
        self._set_parm_if_present(slab, "sizex", slab_width)
        self._set_parm_if_present(slab, "sizey", slab_thickness)
        self._set_parm_if_present(slab, "sizez", slab_depth)
        self._set_parm_if_present(slab, "ty", base_clearance + (slab_thickness * 0.5))

        slab_repeat = floor_subnet.createNode("copyxform", "repeat_floors")
        slab_repeat.setInput(0, slab)
        self._configure_copyxform(slab_repeat, copies=floor_count, ty=floor_spacing)

        self._finalize_subnet_output(floor_subnet, slab_repeat)
        self._safe_value(floor_subnet.layoutChildren)
        merge_node.setInput(self._next_merge_input_index(merge_node), floor_subnet)
        created_paths = [floor_subnet.path(), slab.path(), slab_repeat.path()]

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["floorStack"] = {
            "floorCount": floor_count,
            "slabThickness": slab_thickness,
            "createdNodePaths": created_paths,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_floor_stack(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_floor_stack_impl(arguments), context)
        return self._tool_response(
            f"Added {data['floorStack']['floorCount']} floor slab(s) to {data['buildingNode']['path']}.",
            data,
        )

    def _building_add_core_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        width_ratio = float(arguments.get("width_ratio", 0.22))
        depth_ratio = float(arguments.get("depth_ratio", 0.2))
        height_ratio = float(arguments.get("height_ratio", 0.94))
        base_offset = float(arguments.get("base_offset", 0.0))

        if not (0.05 <= width_ratio <= 0.6):
            raise JsonRpcError(INVALID_PARAMS, "width_ratio must be between 0.05 and 0.6.")
        if not (0.05 <= depth_ratio <= 0.6):
            raise JsonRpcError(INVALID_PARAMS, "depth_ratio must be between 0.05 and 0.6.")
        if not (0.1 <= height_ratio <= 1.0):
            raise JsonRpcError(INVALID_PARAMS, "height_ratio must be between 0.1 and 1.0.")

        building_node, out_node = self._require_building_network(building_path)
        geom = self._geometry_summary_for_node(out_node)
        bbox_min = geom["bboxMin"]
        bbox_max = geom["bboxMax"]
        width = float(bbox_max[0] - bbox_min[0])
        depth = float(bbox_max[2] - bbox_min[2])
        total_height = float(bbox_max[1] - bbox_min[1])

        merge_node = self._ensure_detail_merge(building_node, out_node)
        removed_paths = self._destroy_building_children(building_node, ("CORE_box", "CORE_SYS"))
        core_subnet = self._create_subnet_node(building_node, "CORE_SYS")
        core = core_subnet.createNode("box", "core_volume")
        merge_node.setInput(self._next_merge_input_index(merge_node), core_subnet)
        building_node.setUserData(self._BUILDING_CORE_KEY, core_subnet.path())

        core_height = total_height * height_ratio
        self._set_parm_if_present(core, "sizex", width * width_ratio)
        self._set_parm_if_present(core, "sizey", core_height)
        self._set_parm_if_present(core, "sizez", depth * depth_ratio)
        self._set_parm_if_present(core, "ty", base_offset + (core_height * 0.5))
        self._finalize_subnet_output(core_subnet, core)
        self._safe_value(core_subnet.layoutChildren)

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["core"] = {
            "path": core_subnet.path(),
            "widthRatio": width_ratio,
            "depthRatio": depth_ratio,
            "heightRatio": height_ratio,
            "replacedNodePaths": removed_paths,
        }
        return summary

    def building_add_core(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_core_impl(arguments), context)
        return self._tool_response(
            f"Added building core to {data['buildingNode']['path']}.",
            data,
        )

    def _building_apply_style_profile_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        building_path = str(arguments.get("building_path", "")).strip()
        profile = str(arguments.get("profile", "brutalist_sci_fi")).strip() or "brutalist_sci_fi"
        building_node, _ = self._require_building_network(building_path)

        profiles = {
            "brutalist_sci_fi": {
                "envelope": {"wall_thickness": 0.55, "floor_clearance": 0.12},
                "floors": {"floor_count": 18, "slab_thickness": 0.42, "inset_ratio": 0.08},
                "core": {"width_ratio": 0.24, "depth_ratio": 0.24, "height_ratio": 0.92},
                "bands": {"count": 5, "band_height": 0.55, "overhang_ratio": 1.08},
                "windows": {"floors": 20, "columns": 7, "frame_thickness": 0.16, "frame_depth": 0.22, "sill_height": 3.0, "head_height": 66.0},
                "rooftop": {"unit_count": 5, "unit_height": 2.4, "footprint_ratio": 0.18},
            },
            "corporate_futurist": {
                "envelope": {"wall_thickness": 0.32, "floor_clearance": 0.08},
                "floors": {"floor_count": 24, "slab_thickness": 0.28, "inset_ratio": 0.05},
                "core": {"width_ratio": 0.2, "depth_ratio": 0.18, "height_ratio": 0.96},
                "bands": {"count": 3, "band_height": 0.3, "overhang_ratio": 1.03},
                "windows": {"floors": 24, "columns": 8, "frame_thickness": 0.12, "frame_depth": 0.18, "sill_height": 2.2, "head_height": 68.0},
                "rooftop": {"unit_count": 3, "unit_height": 1.6, "footprint_ratio": 0.15},
            },
        }
        if profile not in profiles:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Unknown building style profile: {profile}",
                {"knownProfiles": sorted(profiles.keys())},
            )

        building_node.setUserData(self._BUILDING_STYLE_KEY, profile)
        envelope_result = self._building_add_envelope_impl({"building_path": building_path, **profiles[profile]["envelope"]})
        floor_result = self._building_add_floor_stack_impl({"building_path": building_path, **profiles[profile]["floors"]})
        core_result = self._building_add_core_impl({"building_path": building_path, **profiles[profile]["core"]})
        band_result = self._building_add_structural_bands_impl({"building_path": building_path, **profiles[profile]["bands"]})
        window_result = self._building_add_window_grid_impl({"building_path": building_path, **profiles[profile]["windows"]})
        rooftop_result = self._building_add_rooftop_mech_impl({"building_path": building_path, **profiles[profile]["rooftop"]})
        summary = self._building_summary(building_node)
        summary["appliedProfile"] = profile
        summary["profileResults"] = {
            "envelope": envelope_result.get("envelope"),
            "floors": floor_result.get("floorStack"),
            "core": core_result.get("core"),
            "bands": band_result.get("structuralBands"),
            "windows": window_result.get("windowGrid"),
            "rooftop": rooftop_result.get("rooftopMechanical"),
        }
        return summary

    def building_apply_style_profile(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_apply_style_profile_impl(arguments), context)
        return self._tool_response(
            f"Applied style profile {data['appliedProfile']} to {data['buildingNode']['path']}.",
            data,
        )
