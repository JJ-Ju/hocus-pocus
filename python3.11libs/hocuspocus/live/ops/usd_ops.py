"""LOP and USD authoring operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class UsdOperationsMixin:
    def _lop_summary(self, node: Any) -> dict[str, Any]:
        data = self._node_summary(node, include_parms=False)
        for parm_name, key in (
            ("primpath", "primPath"),
            ("refprimpath", "referencePrimPath"),
            ("filepath1", "referenceFilePath"),
            ("savepath", "layerSavePath"),
            ("primpattern1", "primPattern"),
            ("matspecpath1", "materialSpecPath"),
            ("variantset1", "variantSet"),
            ("variantname1", "variantName"),
            ("matpathprefix", "materialPathPrefix"),
        ):
            parm = self._safe_value(lambda parm_name=parm_name: node.parm(parm_name), None)
            if parm is None:
                continue
            data[key] = self._safe_value(parm.evalAsString, None)
        return data

    def _lop_parent(self, parent_path: str) -> Any:
        parent = self._require_node_by_path(parent_path, label="parent_path")
        return parent

    def _lop_create_node_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/stage")).strip() or "/stage"
        node_type_name = str(arguments.get("node_type_name", "")).strip()
        node_name = str(arguments.get("node_name", "")).strip() or None
        input_node_path = str(arguments.get("input_node_path", "")).strip() or None
        input_index = int(arguments.get("input_index", 0))
        if not node_type_name:
            raise JsonRpcError(INVALID_PARAMS, "node_type_name is required")
        parent = self._lop_parent(parent_path)
        with hou_module.undos.group(f"HocusPocus: create LOP {node_type_name}"):
            node = parent.createNode(node_type_name, node_name=node_name)
            if input_node_path:
                source = self._require_node_by_path(input_node_path, label="input_node_path")
                node.setInput(input_index, source)
            try:
                parent.layoutChildren(items=(node,))
            except Exception:
                self._logger.debug("failed to layout lop node", exc_info=True)
        return self._lop_summary(node)

    def lop_create_node(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._lop_create_node_impl(arguments), context)
        return self._tool_response(f"Created LOP node {data['path']}.", data)

    def _usd_assign_material_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/stage")).strip() or "/stage"
        input_node_path = str(arguments.get("input_node_path", "")).strip() or None
        prim_pattern = str(arguments.get("prim_pattern", "")).strip()
        material_path = str(arguments.get("material_path", "")).strip()
        node_name = str(arguments.get("node_name", "assignmaterial1")).strip() or "assignmaterial1"
        if not prim_pattern or not material_path:
            raise JsonRpcError(INVALID_PARAMS, "prim_pattern and material_path are required")
        parent = self._lop_parent(parent_path)
        with hou_module.undos.group("HocusPocus: assign USD material"):
            node = parent.createNode("assignmaterial", node_name=node_name)
            if input_node_path:
                source = self._require_node_by_path(input_node_path, label="input_node_path")
                node.setInput(0, source)
            node.parm("primpattern1").set(prim_pattern)
            node.parm("matspecpath1").set(material_path)
        return self._lop_summary(node)

    def usd_assign_material(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_assign_material_impl(arguments), context)
        return self._tool_response(f"Created USD material assignment node {data['path']}.", data)

    def _usd_set_variant_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/stage")).strip() or "/stage"
        input_node_path = str(arguments.get("input_node_path", "")).strip() or None
        prim_pattern = str(arguments.get("prim_pattern", "")).strip()
        variant_set = str(arguments.get("variant_set", "")).strip()
        variant_name = str(arguments.get("variant_name", "")).strip()
        node_name = str(arguments.get("node_name", "setvariant1")).strip() or "setvariant1"
        if not prim_pattern or not variant_set or not variant_name:
            raise JsonRpcError(INVALID_PARAMS, "prim_pattern, variant_set, and variant_name are required")
        parent = self._lop_parent(parent_path)
        with hou_module.undos.group("HocusPocus: set USD variant"):
            node = parent.createNode("setvariant", node_name=node_name)
            if input_node_path:
                source = self._require_node_by_path(input_node_path, label="input_node_path")
                node.setInput(0, source)
            node.parm("primpattern1").set(prim_pattern)
            node.parm("variantset1").set(variant_set)
            node.parm("variantname1").set(variant_name)
        return self._lop_summary(node)

    def usd_set_variant(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_set_variant_impl(arguments), context)
        return self._tool_response(f"Created USD variant node {data['path']}.", data)

    def _usd_add_reference_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/stage")).strip() or "/stage"
        input_node_path = str(arguments.get("input_node_path", "")).strip() or None
        prim_path = str(arguments.get("prim_path", "")).strip()
        file_path = str(arguments.get("file_path", "")).strip()
        reference_prim_path = str(arguments.get("reference_prim_path", "")).strip() or None
        node_name = str(arguments.get("node_name", "reference1")).strip() or "reference1"
        if not prim_path or not file_path:
            raise JsonRpcError(INVALID_PARAMS, "prim_path and file_path are required")
        parent = self._lop_parent(parent_path)
        with hou_module.undos.group("HocusPocus: add USD reference"):
            node = parent.createNode("reference", node_name=node_name)
            if input_node_path:
                source = self._require_node_by_path(input_node_path, label="input_node_path")
                node.setInput(0, source)
            node.parm("primpath").set(prim_path)
            node.parm("filepath1").set(file_path)
            if reference_prim_path:
                node.parm("refprimpath").set(reference_prim_path)
        return self._lop_summary(node)

    def usd_add_reference(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_add_reference_impl(arguments), context)
        return self._tool_response(f"Created USD reference node {data['path']}.", data)

    def _usd_create_layer_break_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/stage")).strip() or "/stage"
        input_node_path = str(arguments.get("input_node_path", "")).strip() or None
        node_name = str(arguments.get("node_name", "layerbreak1")).strip() or "layerbreak1"
        save_path = str(arguments.get("save_path", "")).strip() or None
        parent = self._lop_parent(parent_path)
        with hou_module.undos.group("HocusPocus: create USD layer break"):
            layer_break = parent.createNode("layerbreak", node_name=node_name)
            upstream = None
            if input_node_path:
                upstream = self._require_node_by_path(input_node_path, label="input_node_path")
                layer_break.setInput(0, upstream)
            configure = None
            if save_path:
                configure = parent.createNode("configurelayer", node_name=f"{node_name}_configure")
                configure.setInput(0, layer_break)
                configure.parm("setsavepath").set(True)
                configure.parm("savepath").set(save_path)
            try:
                parent.layoutChildren(items=tuple(item for item in (layer_break, configure) if item is not None))
            except Exception:
                self._logger.debug("failed to layout layer break nodes", exc_info=True)
        return {
            "layerBreakNode": self._lop_summary(layer_break),
            "configureLayerNode": self._lop_summary(configure) if configure is not None else None,
        }

    def usd_create_layer_break(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_create_layer_break_impl(arguments), context)
        return self._tool_response(f"Created USD layer break node {data['layerBreakNode']['path']}.", data)
