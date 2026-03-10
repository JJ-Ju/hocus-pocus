"""Higher-level agent-friendly tools."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class HighLevelOperationsMixin:
    def _rollback_batch_actions(
        self,
        rollback_actions: list[tuple[str, Any]],
    ) -> bool:
        rolled_back = True
        while rollback_actions:
            action_name, action = rollback_actions.pop()
            try:
                action()
            except Exception:
                rolled_back = False
                self._logger.exception("failed rollback action %s", action_name)
        return rolled_back

    def _batch_resolve(self, value: Any, refs: dict[str, str]) -> Any:
        if isinstance(value, str) and value.startswith("$ref:"):
            ref_expr = value[5:]
            ref_name, separator, suffix = ref_expr.partition("/")
            if ref_name not in refs:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Unknown batch reference: {ref_name}",
                    {"knownRefs": sorted(refs.keys())},
                )
            resolved = refs[ref_name]
            if separator:
                resolved = f"{resolved}/{suffix}"
            return resolved
        if isinstance(value, list):
            return [self._batch_resolve(item, refs) for item in value]
        if isinstance(value, dict):
            return {key: self._batch_resolve(item, refs) for key, item in value.items()}
        return value

    def _graph_batch_edit_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not operations:
            raise JsonRpcError(INVALID_PARAMS, "operations must be a non-empty array.")
        transactional = bool(arguments.get("transactional", False))
        refs: dict[str, str] = {}
        results: list[dict[str, Any]] = []
        rollback_actions: list[tuple[str, Any]] = []
        label = str(arguments.get("label", "batch edit")).strip() or "batch edit"
        failed_index: int | None = None
        failed_type: str | None = None

        try:
            with hou_module.undos.group(f"HocusPocus: {label}"):
                for index, raw_op in enumerate(operations):
                    if not isinstance(raw_op, dict):
                        raise JsonRpcError(INVALID_PARAMS, f"Operation at index {index} must be an object.")
                    op_type = str(raw_op.get("type", "")).strip()
                    op_id = str(raw_op.get("id", "")).strip()
                    failed_index = index
                    failed_type = op_type
                    resolved = self._batch_resolve(raw_op, refs)
                    if op_type == "create_node":
                        result = self._node_create_impl(resolved)
                        if op_id:
                            refs[op_id] = result["path"]
                        if transactional:
                            created_path = result["path"]
                            rollback_actions.append(
                                (
                                    "destroy_node",
                                    lambda created_path=created_path: self._safe_value(
                                        lambda: self._require_node_by_path(created_path).destroy()
                                    ),
                                )
                            )
                    elif op_type == "connect":
                        dest = self._require_node_by_path(
                            str(resolved.get("dest_node_path", "")),
                            label="dest_node_path",
                        )
                        dest_input_index = int(resolved.get("dest_input_index", 0))
                        previous_input = None
                        previous_output_index = 0
                        input_connections = self._safe_value(dest.inputConnections, []) or []
                        if dest_input_index < len(input_connections):
                            connection = input_connections[dest_input_index]
                            previous_input = connection.inputNode()
                            previous_output_index = connection.outputIndex()
                        result = self._node_connect_impl(resolved)
                        if transactional:
                            rollback_actions.append(
                                (
                                    "restore_connection",
                                    lambda dest=dest, dest_input_index=dest_input_index, previous_input=previous_input, previous_output_index=previous_output_index: dest.setInput(dest_input_index, previous_input, output_index=previous_output_index) if previous_input is not None else dest.setInput(dest_input_index, None),
                                )
                            )
                    elif op_type == "set_parm":
                        parm = self._require_parm_by_path(str(resolved.get("parm_path", "")))
                        previous_expression = self._safe_value(parm.expression, None)
                        previous_expression_language = self._safe_value(parm.expressionLanguage, None)
                        previous_value = self._safe_value(parm.eval, None)
                        result = self._parm_set_impl(resolved)
                        if transactional:
                            def restore_parm(parm=parm, previous_expression=previous_expression, previous_expression_language=previous_expression_language, previous_value=previous_value) -> None:
                                if previous_expression is not None and previous_expression_language is not None:
                                    parm.setExpression(previous_expression, language=previous_expression_language)
                                else:
                                    parm.set(previous_value)
                            rollback_actions.append(("restore_parm", restore_parm))
                    elif op_type == "set_flags":
                        node = self._require_node_by_path(str(resolved.get("path", "")))
                        previous_flags = self._node_flags(node)
                        result = self._node_set_flags_impl(resolved)
                        if transactional:
                            def restore_flags(node=node, previous_flags=previous_flags) -> None:
                                if previous_flags["bypass"] is not None:
                                    node.bypass(bool(previous_flags["bypass"]))
                                if previous_flags["display"] is not None:
                                    self._safe_value(lambda: node.setDisplayFlag(bool(previous_flags["display"])))
                                if previous_flags["render"] is not None:
                                    self._safe_value(lambda: node.setRenderFlag(bool(previous_flags["render"])))
                                if previous_flags["template"] is not None:
                                    self._safe_value(lambda: node.setTemplateFlag(bool(previous_flags["template"])))
                            rollback_actions.append(("restore_flags", restore_flags))
                    elif op_type == "move_node":
                        node = self._require_node_by_path(str(resolved.get("path", "")))
                        previous_position = self._safe_value(node.position, None)
                        result = self._node_move_impl(resolved)
                        if transactional and previous_position is not None:
                            rollback_actions.append(
                                (
                                    "restore_position",
                                    lambda node=node, previous_position=previous_position: node.setPosition(previous_position),
                                )
                            )
                    elif op_type == "layout":
                        parent_path = str(resolved.get("parent_path", "/obj"))
                        parent = self._require_node_by_path(parent_path, label="parent_path")
                        previous_positions = {
                            child.path(): self._safe_value(child.position, None)
                            for child in parent.children()
                        }
                        result = self._node_layout_impl(resolved)
                        if transactional:
                            def restore_layout(previous_positions=previous_positions) -> None:
                                for child_path, position in previous_positions.items():
                                    if position is None:
                                        continue
                                    child = hou_module.node(child_path)
                                    if child is not None:
                                        child.setPosition(position)
                            rollback_actions.append(("restore_layout", restore_layout))
                    else:
                        raise JsonRpcError(INVALID_PARAMS, f"Unsupported batch operation type: {op_type}")
                    results.append({"index": index, "type": op_type, "result": result})
        except JsonRpcError as exc:
            rolled_back = self._rollback_batch_actions(rollback_actions) if transactional else False
            raise JsonRpcError(
                -32020,
                "Batch edit failed.",
                {
                    "transactional": transactional,
                    "rolledBack": rolled_back,
                    "failedIndex": failed_index,
                    "failedType": failed_type,
                    "completedCount": len(results),
                    "refs": refs,
                    "completedResults": results,
                    "originalError": exc.to_payload(),
                },
            ) from exc
        except Exception as exc:
            rolled_back = self._rollback_batch_actions(rollback_actions) if transactional else False
            raise JsonRpcError(
                -32020,
                "Batch edit failed.",
                {
                    "transactional": transactional,
                    "rolledBack": rolled_back,
                    "failedIndex": failed_index,
                    "failedType": failed_type,
                    "completedCount": len(results),
                    "refs": refs,
                    "completedResults": results,
                    "originalError": {"message": str(exc)},
                },
            ) from exc

        return {
            "count": len(results),
            "refs": refs,
            "results": results,
            "transactional": transactional,
            "rolledBack": False,
        }

    def graph_batch_edit(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._graph_batch_edit_impl(arguments), context)
        return self._tool_response(f"Applied {data['count']} batch operation(s).", data)

    def _model_create_house_blockout_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("node_name", "house_blockout1")).strip() or "house_blockout1"
        parent_path = str(arguments.get("parent_path", "/obj")).strip() or "/obj"
        batch = {
            "label": f"house blockout {name}",
            "operations": [
                {"type": "create_node", "id": "house", "parent_path": parent_path, "node_type_name": "geo", "node_name": name},
                {"type": "create_node", "id": "body", "parent_path": "$ref:house", "node_type_name": "box", "node_name": "body_box"},
                {"type": "set_parm", "parm_path": "$ref:body/sizex", "value": 4.0},
                {"type": "set_parm", "parm_path": "$ref:body/sizey", "value": 2.5},
                {"type": "set_parm", "parm_path": "$ref:body/sizez", "value": 3.0},
                {"type": "set_parm", "parm_path": "$ref:body/ty", "value": 1.25},
                {"type": "create_node", "id": "roof_left", "parent_path": "$ref:house", "node_type_name": "box", "node_name": "roof_left_box"},
                {"type": "set_parm", "parm_path": "$ref:roof_left/sizex", "value": 2.2},
                {"type": "set_parm", "parm_path": "$ref:roof_left/sizey", "value": 0.25},
                {"type": "set_parm", "parm_path": "$ref:roof_left/sizez", "value": 3.2},
                {"type": "set_parm", "parm_path": "$ref:roof_left/tx", "value": -0.95},
                {"type": "set_parm", "parm_path": "$ref:roof_left/ty", "value": 2.65},
                {"type": "set_parm", "parm_path": "$ref:roof_left/rz", "value": 28.0},
                {"type": "create_node", "id": "roof_right", "parent_path": "$ref:house", "node_type_name": "box", "node_name": "roof_right_box"},
                {"type": "set_parm", "parm_path": "$ref:roof_right/sizex", "value": 2.2},
                {"type": "set_parm", "parm_path": "$ref:roof_right/sizey", "value": 0.25},
                {"type": "set_parm", "parm_path": "$ref:roof_right/sizez", "value": 3.2},
                {"type": "set_parm", "parm_path": "$ref:roof_right/tx", "value": 0.95},
                {"type": "set_parm", "parm_path": "$ref:roof_right/ty", "value": 2.65},
                {"type": "set_parm", "parm_path": "$ref:roof_right/rz", "value": -28.0},
                {"type": "create_node", "id": "chimney", "parent_path": "$ref:house", "node_type_name": "box", "node_name": "chimney_box"},
                {"type": "set_parm", "parm_path": "$ref:chimney/sizex", "value": 0.45},
                {"type": "set_parm", "parm_path": "$ref:chimney/sizey", "value": 1.2},
                {"type": "set_parm", "parm_path": "$ref:chimney/sizez", "value": 0.45},
                {"type": "set_parm", "parm_path": "$ref:chimney/tx", "value": 1.0},
                {"type": "set_parm", "parm_path": "$ref:chimney/ty", "value": 3.35},
                {"type": "set_parm", "parm_path": "$ref:chimney/tz", "value": -0.6},
                {"type": "create_node", "id": "merge", "parent_path": "$ref:house", "node_type_name": "merge", "node_name": "house_merge"},
                {"type": "connect", "source_node_path": "$ref:body", "dest_node_path": "$ref:merge", "dest_input_index": 0},
                {"type": "connect", "source_node_path": "$ref:roof_left", "dest_node_path": "$ref:merge", "dest_input_index": 1},
                {"type": "connect", "source_node_path": "$ref:roof_right", "dest_node_path": "$ref:merge", "dest_input_index": 2},
                {"type": "connect", "source_node_path": "$ref:chimney", "dest_node_path": "$ref:merge", "dest_input_index": 3},
                {"type": "create_node", "id": "out", "parent_path": "$ref:house", "node_type_name": "null", "node_name": "OUT_house"},
                {"type": "connect", "source_node_path": "$ref:merge", "dest_node_path": "$ref:out"},
                {"type": "set_flags", "path": "$ref:out", "display": True, "render": True},
                {"type": "layout", "parent_path": "$ref:house"},
            ],
        }
        result = self._graph_batch_edit_impl(batch)
        house_path = result["refs"]["house"]
        return {
            "houseNode": self._node_get_impl({"path": house_path}),
            "outputNode": self._node_get_impl({"path": result["refs"]["out"]}),
            "refs": result["refs"],
        }

    def model_create_house_blockout(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._model_create_house_blockout_impl(arguments), context)
        return self._tool_response(f"Created house blockout {data['houseNode']['path']}.", data)
