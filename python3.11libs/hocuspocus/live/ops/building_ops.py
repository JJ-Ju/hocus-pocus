"""Semantic procedural building tools."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class BuildingOperationsMixin:
    _BUILDING_KIND_KEY = "hpmcp.building.kind"
    _BUILDING_OUT_KEY = "hpmcp.building.out"
    _BUILDING_MASSING_MERGE_KEY = "hpmcp.building.massing_merge"
    _BUILDING_DETAIL_MERGE_KEY = "hpmcp.building.detail_merge"

    def _mark_building_network(self, building_node: Any, out_node: Any, massing_merge: Any) -> None:
        building_node.setUserData(self._BUILDING_KIND_KEY, "tower")
        building_node.setUserData(self._BUILDING_OUT_KEY, out_node.path())
        building_node.setUserData(self._BUILDING_MASSING_MERGE_KEY, massing_merge.path())

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

    def _create_sop_node(self, parent: Any, node_type_name: str, node_name: str) -> Any:
        node = parent.createNode(node_type_name, node_name)
        self._place_node_on_grid(parent, node)
        return node

    def _set_parm_if_present(self, node: Any, parm_name: str, value: Any) -> None:
        parm = self._safe_value(lambda: node.parm(parm_name), None)
        if parm is not None:
            parm.set(value)

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
        }
        return {
            "buildingNode": self._node_summary(building_node),
            "outputNode": self._node_summary(out_node),
            "geometry": geometry,
            "refs": refs,
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

        self._mark_building_network(building_node, out_node, merge)
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
        geom = self._geometry_summary_for_node(out_node)
        width = float(geom["bboxMax"][0] - geom["bboxMin"][0])
        depth = float(geom["bboxMax"][2] - geom["bboxMin"][2])
        base_y = float(geom["bboxMin"][1])
        top_y = float(geom["bboxMax"][1])
        total_height = max(top_y - base_y, band_height)
        merge_node = self._ensure_detail_merge(building_node, out_node)

        created_paths: list[str] = []
        if count == 1:
            normalized_positions = [0.5]
        else:
            normalized_positions = [
                start_ratio + ((end_ratio - start_ratio) * (index / (count - 1)))
                for index in range(count)
            ]
        for index, normalized in enumerate(normalized_positions, start=1):
            band = self._create_sop_node(building_node, "box", f"BAND_{index:02d}_box")
            self._set_parm_if_present(band, "sizex", width * overhang_ratio)
            self._set_parm_if_present(band, "sizey", band_height)
            self._set_parm_if_present(band, "sizez", depth * overhang_ratio)
            self._set_parm_if_present(band, "ty", base_y + (total_height * normalized))
            merge_node.setInput(self._next_merge_input_index(merge_node), band)
            created_paths.append(band.path())

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["structuralBands"] = {
            "count": count,
            "bandHeight": band_height,
            "createdNodePaths": created_paths,
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
        geom = self._geometry_summary_for_node(out_node)
        width = float(geom["bboxMax"][0] - geom["bboxMin"][0])
        depth = float(geom["bboxMax"][2] - geom["bboxMin"][2])
        top_y = float(geom["bboxMax"][1])

        unit_width = max(width * footprint_ratio, 0.6)
        unit_depth = max(depth * footprint_ratio, 0.6)
        offset_x = max((width * 0.5) - (unit_width * 0.5) - (width * setback_ratio), 0.0)
        offset_z = max((depth * 0.5) - (unit_depth * 0.5) - (depth * setback_ratio), 0.0)
        placement_cycle = [
            (-offset_x, -offset_z),
            (offset_x, -offset_z),
            (0.0, offset_z),
            (-offset_x, offset_z),
            (offset_x, offset_z),
        ]

        merge_node = self._ensure_detail_merge(building_node, out_node)
        created_paths: list[str] = []
        for index in range(unit_count):
            mech = self._create_sop_node(building_node, "box", f"ROOF_MECH_{index + 1:02d}_box")
            self._set_parm_if_present(mech, "sizex", unit_width)
            self._set_parm_if_present(mech, "sizey", unit_height)
            self._set_parm_if_present(mech, "sizez", unit_depth)
            tx, tz = placement_cycle[index % len(placement_cycle)]
            self._set_parm_if_present(mech, "tx", tx)
            self._set_parm_if_present(mech, "tz", tz)
            self._set_parm_if_present(mech, "ty", top_y + (unit_height * 0.5))
            merge_node.setInput(self._next_merge_input_index(merge_node), mech)
            created_paths.append(mech.path())

        self._safe_value(lambda: out_node.setDisplayFlag(True))
        self._safe_value(lambda: out_node.setRenderFlag(True))
        self._sync_grid_state_for_parent(building_node)
        summary = self._building_summary(building_node)
        summary["rooftopMechanical"] = {
            "unitCount": unit_count,
            "unitHeight": unit_height,
            "createdNodePaths": created_paths,
        }
        return summary

    def building_add_rooftop_mech(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._building_add_rooftop_mech_impl(arguments), context)
        return self._tool_response(
            f"Added rooftop mechanical detail to {data['buildingNode']['path']}.",
            data,
        )
