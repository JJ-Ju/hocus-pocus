"""Node graph operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class NodeOperationsMixin:
    def _node_list_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        recursive = bool(arguments.get("recursive", False))
        max_items = int(arguments.get("max_items", 200))
        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")
        nodes = list(parent.allSubChildren()) if recursive else list(parent.children())
        nodes = nodes[:max_items]
        return {
            "parentPath": parent.path(),
            "recursive": recursive,
            "count": len(nodes),
            "nodes": [self._node_summary(node) for node in nodes],
        }

    def node_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_list_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} nodes.", data)

    def _node_get_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        include_parms = bool(arguments.get("include_parms", False))
        return self._node_summary(node, include_parms=include_parms)

    def node_get(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_get_impl(arguments), context)
        return self._tool_response(f"Returned node data for {data['path']}.", data)

    def _node_create_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        node_type_name = arguments.get("node_type_name")
        if not node_type_name:
            raise JsonRpcError(INVALID_PARAMS, "node_type_name is required")
        node_name = arguments.get("node_name")
        run_init_scripts = bool(arguments.get("run_init_scripts", True))
        load_contents = bool(arguments.get("load_contents", True))
        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")

        with hou_module.undos.group(f"HocusPocus: create {node_type_name}"):
            node = parent.createNode(
                str(node_type_name),
                node_name=node_name,
                run_init_scripts=run_init_scripts,
                load_contents=load_contents,
            )
            node.setUserData("hpmcp.created_by", "hocuspocus")
            node.setUserData("hpmcp.operation_id", "tool:node.create")
            try:
                parent.layoutChildren(items=(node,))
            except Exception:
                self._logger.debug("failed to layout node", exc_info=True)

        return self._node_summary(node)

    def node_create(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_create_impl(arguments), context)
        return self._tool_response(f"Created node {data['path']}.", data)

    def _node_delete_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        paths = self._resolve_nodes_argument(arguments)
        ignore_missing = bool(arguments.get("ignore_missing", False))
        deleted: list[str] = []
        skipped: list[str] = []
        with hou_module.undos.group("HocusPocus: delete nodes"):
            for path in paths:
                node = hou_module.node(str(path))
                if node is None:
                    if ignore_missing:
                        skipped.append(str(path))
                        continue
                    node = self._require_node_by_path(path)
                deleted.append(node.path())
                node.destroy()
        return {
            "deletedPaths": deleted,
            "skippedPaths": skipped,
            "countDeleted": len(deleted),
            "countSkipped": len(skipped),
            "countRequested": len(paths),
            "ignoreMissing": ignore_missing,
        }

    def node_delete(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_delete_impl(arguments), context)
        if data["countSkipped"]:
            return self._tool_response(
                f"Deleted {data['countDeleted']} node(s) and skipped {data['countSkipped']} missing path(s).",
                data,
            )
        return self._tool_response(f"Deleted {data['countDeleted']} node(s).", data)

    def _node_rename_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        new_name = str(arguments.get("new_name", "")).strip()
        unique_name = bool(arguments.get("unique_name", False))
        if not path or not new_name:
            raise JsonRpcError(INVALID_PARAMS, "path and new_name are required")
        node = self._require_node_by_path(path)
        with hou_module.undos.group("HocusPocus: rename node"):
            node.setName(new_name, unique_name=unique_name)
        return self._node_summary(node)

    def node_rename(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_rename_impl(arguments), context)
        return self._tool_response(f"Renamed node to {data['path']}.", data)

    def _node_connect_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        source_path = str(arguments.get("source_node_path", "")).strip()
        dest_path = str(arguments.get("dest_node_path", "")).strip()
        if not source_path or not dest_path:
            raise JsonRpcError(INVALID_PARAMS, "source_node_path and dest_node_path are required")
        dest_input_index = int(arguments.get("dest_input_index", 0))
        source_output_index = int(arguments.get("source_output_index", 0))
        source = self._require_node_by_path(source_path, label="source_node_path")
        dest = self._require_node_by_path(dest_path, label="dest_node_path")
        with hou_module.undos.group("HocusPocus: connect nodes"):
            dest.setInput(dest_input_index, source, output_index=source_output_index)
        return self._node_summary(dest)

    def node_connect(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_connect_impl(arguments), context)
        return self._tool_response(
            f"Connected node {arguments['source_node_path']} to {arguments['dest_node_path']}.",
            data,
        )

    def _node_disconnect_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        input_index = arguments.get("input_index")
        with hou_module.undos.group("HocusPocus: disconnect node"):
            if input_index is None:
                for index, _ in enumerate(node.inputs()):
                    node.setInput(index, None)
            else:
                node.setInput(int(input_index), None)
        return self._node_summary(node)

    def node_disconnect(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_disconnect_impl(arguments), context)
        return self._tool_response(f"Disconnected inputs on {data['path']}.", data)

    def _node_move_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        x = float(arguments.get("x"))
        y = float(arguments.get("y"))
        with hou_module.undos.group("HocusPocus: move node"):
            node.setPosition(hou_module.Vector2((x, y)))
        return self._node_summary(node)

    def node_move(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_move_impl(arguments), context)
        return self._tool_response(f"Moved node {data['path']}.", data)

    def _node_layout_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/obj"))
        parent = hou_module.node(parent_path)
        if parent is None:
            raise JsonRpcError(INVALID_PARAMS, f"Parent node not found: {parent_path}")
        child_paths = [str(item) for item in arguments.get("child_paths", [])]
        if child_paths:
            items = []
            for child_path in child_paths:
                child = hou_module.node(child_path)
                if child is None:
                    raise JsonRpcError(INVALID_PARAMS, f"Node not found: {child_path}")
                items.append(child)
            parent.layoutChildren(items=tuple(items))
        else:
            parent.layoutChildren()
        return self._node_list_impl({"parent_path": parent_path, "recursive": False, "max_items": 500})

    def node_layout(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_layout_impl(arguments), context)
        return self._tool_response(f"Laid out nodes under {data['parentPath']}.", data)

    def _node_set_flags_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        path = str(arguments.get("path", "")).strip()
        node = self._require_node_by_path(path)
        with hou_module.undos.group("HocusPocus: set node flags"):
            if "bypass" in arguments:
                node.bypass(bool(arguments["bypass"]))
            if "display" in arguments:
                self._safe_value(lambda: node.setDisplayFlag(bool(arguments["display"])))
            if "render" in arguments:
                self._safe_value(lambda: node.setRenderFlag(bool(arguments["render"])))
            if "template" in arguments:
                self._safe_value(lambda: node.setTemplateFlag(bool(arguments["template"])))
        return self._node_summary(node)

    def node_set_flags(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_set_flags_impl(arguments), context)
        return self._tool_response(f"Updated flags on {data['path']}.", data)
