"""PDG and TOP network automation operations."""

from __future__ import annotations

import time
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import OperationCancelledError, RequestContext


class PdgOperationsMixin:
    def _pdg_enum_name(self, value: Any) -> str | None:
        if value is None:
            return None
        name_attr = getattr(value, "name", None)
        if callable(name_attr):
            try:
                return str(name_attr())
            except Exception:
                return str(value)
        if name_attr is not None:
            return str(name_attr)
        return str(value)

    def _pdg_graph_nodes(self) -> list[Any]:
        hou_module = self._require_hou()
        candidates: list[Any] = []
        for root_path in ("/tasks", "/obj"):
            root = hou_module.node(root_path)
            if root is None:
                continue
            for node in root.allSubChildren():
                if self._safe_value(lambda node=node: node.type().name(), "") == "topnet":
                    candidates.append(node)
        return sorted(candidates, key=lambda item: item.path())

    def _require_pdg_graph_node(self, graph_path: str) -> Any:
        node = self._require_node_by_path(graph_path, label="graph_path")
        if self._safe_value(lambda: node.type().name(), "") != "topnet":
            raise JsonRpcError(INVALID_PARAMS, f"Node is not a TOP network: {graph_path}")
        return node

    def _pdg_result_summary(self, result: Any) -> dict[str, Any]:
        path = self._safe_value(lambda: result.path, None)
        if callable(path):
            path = self._safe_value(path, None)
        tag = self._safe_value(lambda: result.tag, None)
        if callable(tag):
            tag = self._safe_value(tag, None)
        result_type = self._safe_value(lambda: result.resultType, None)
        if callable(result_type):
            result_type = self._safe_value(result_type, None)
        return {
            "path": str(path) if path is not None else None,
            "tag": str(tag) if tag is not None else None,
            "resultType": self._pdg_enum_name(result_type),
        }

    def _pdg_work_item_summary(self, work_item: Any) -> dict[str, Any]:
        return {
            "name": self._safe_value(lambda: work_item.name, None),
            "id": self._safe_value(lambda: int(work_item.id), None),
            "index": self._safe_value(lambda: int(work_item.index), None),
            "state": self._pdg_enum_name(self._safe_value(lambda: work_item.state, None)),
            "cookType": self._pdg_enum_name(self._safe_value(lambda: work_item.cookType, None)),
            "cookPercent": self._safe_value(lambda: float(work_item.cookPercent), None),
            "hasWarnings": bool(self._safe_value(lambda: work_item.hasWarnings, False)),
            "customState": self._safe_value(lambda: work_item.customState, None),
            "resultData": [self._pdg_result_summary(item) for item in list(self._safe_value(lambda: work_item.resultData, []) or [])],
            "logMessages": list(self._safe_value(lambda: work_item.logMessages, []) or []),
            "attribNames": [str(name) for name in list(self._safe_value(lambda: work_item.attribNames(), []) or [])],
        }

    def _pdg_graph_summary(self, graph_node: Any) -> dict[str, Any]:
        ctx = graph_node.getPDGGraphContext()
        graph = ctx.graph
        pdg_nodes = list(self._safe_value(graph.nodes, []) or [])
        work_items = []
        state_counts: dict[str, int] = {}
        for pdg_node in pdg_nodes:
            for work_item in list(self._safe_value(lambda pdg_node=pdg_node: pdg_node.workItems, []) or []):
                summary = self._pdg_work_item_summary(work_item)
                work_items.append(summary)
                state = summary.get("state") or "unknown"
                state_counts[state] = state_counts.get(state, 0) + 1
        return {
            "graphPath": graph_node.path(),
            "graphName": graph_node.name(),
            "cookState": self._pdg_enum_name(self._safe_value(lambda: graph_node.getCookState(True), None)),
            "cooking": bool(ctx.cooking),
            "canceling": bool(ctx.canceling),
            "nodeCount": len(pdg_nodes),
            "workItemCount": len(work_items),
            "workItemStateCounts": state_counts,
        }

    def _pdg_list_graphs_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graphs = [self._pdg_graph_summary(node) for node in self._pdg_graph_nodes()]
        return {"count": len(graphs), "graphs": graphs}

    def pdg_list_graphs(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_list_graphs_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} PDG graph(s).", data)

    def _pdg_get_workitems_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        node_path = str(arguments.get("node_path", "")).strip() or None
        limit = int(arguments.get("limit", 200))
        graph_node = self._require_pdg_graph_node(graph_path)
        if node_path:
            node = self._require_node_by_path(node_path, label="node_path")
            pdg_nodes = [node.getPDGNode()]
        else:
            pdg_nodes = list(self._safe_value(graph_node.getPDGGraphContext().graph.nodes, []) or [])
        items: list[dict[str, Any]] = []
        for pdg_node in pdg_nodes:
            if pdg_node is None:
                continue
            node_name = self._safe_value(lambda pdg_node=pdg_node: pdg_node.name, None)
            for work_item in list(self._safe_value(lambda pdg_node=pdg_node: pdg_node.workItems, []) or []):
                payload = self._pdg_work_item_summary(work_item)
                payload["pdgNodeName"] = node_name
                items.append(payload)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return {
            "graphPath": graph_path,
            "nodePath": node_path,
            "count": len(items),
            "workItems": items,
        }

    def pdg_get_workitems(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_get_workitems_impl(arguments), context)
        return self._tool_response(f"Returned {data['count']} PDG work item(s).", data)

    def _pdg_get_results_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._pdg_get_workitems_impl(arguments)
        results = []
        for item in payload["workItems"]:
            if item.get("resultData"):
                results.append(
                    {
                        "workItemId": item.get("id"),
                        "workItemName": item.get("name"),
                        "pdgNodeName": item.get("pdgNodeName"),
                        "resultData": item.get("resultData"),
                    }
                )
        return {
            "graphPath": payload["graphPath"],
            "nodePath": payload["nodePath"],
            "count": len(results),
            "results": results,
        }

    def pdg_get_results(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_get_results_impl(arguments), context)
        return self._tool_response(f"Returned {data['count']} PDG result item(s).", data)

    def _pdg_cancel_impl(self, graph_path: str) -> dict[str, Any]:
        graph_node = self._require_pdg_graph_node(graph_path)
        graph_node.cancelCook()
        summary = self._pdg_graph_summary(graph_node)
        summary["cancelRequested"] = True
        return summary

    def pdg_cancel(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        if not graph_path:
            raise JsonRpcError(INVALID_PARAMS, "graph_path is required")
        data = self._call_live(lambda: self._pdg_cancel_impl(graph_path), context)
        return self._tool_response(f"Requested PDG cook cancellation for {graph_path}.", data)

    def _pdg_poll_status_impl(self, graph_path: str) -> dict[str, Any]:
        graph_node = self._require_pdg_graph_node(graph_path)
        return self._pdg_graph_summary(graph_node)

    def pdg_cook(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        if not graph_path:
            raise JsonRpcError(INVALID_PARAMS, "graph_path is required")
        dirty_before = bool(arguments.get("dirty_before", False))
        generate_only = bool(arguments.get("generate_only", False))
        tops_only = bool(arguments.get("tops_only", False))

        def runner(controller: Any) -> dict[str, Any]:
            controller.add_recovery_note(
                "PDG cancellation is cooperative. HocusPocus requests graph cancellation, but active work may complete its current step before the graph fully stops."
            )
            controller.set_outcome(
                {
                    "graphPath": graph_path,
                    "partialResultsPossible": True,
                    "cancellationSemantics": "graph_cooperative",
                    "stateHistory": [],
                }
            )
            controller.log(f"Starting PDG cook for {graph_path}.")
            controller.run_live(
                lambda: self._pdg_start_cook_impl(graph_path, dirty_before, generate_only, tops_only),
                operation_label="pdg-start",
                timeout_seconds=max(context.timeout_seconds, 120.0),
            )

            state_history: list[str] = []
            while True:
                status = controller.run_live(
                    lambda: self._pdg_poll_status_impl(graph_path),
                    operation_label="pdg-status",
                    timeout_seconds=max(context.timeout_seconds, 60.0),
                )
                cook_state = status.get("cookState") or "unknown"
                state_history.append(cook_state)
                controller.update_outcome(
                    {
                        "stateHistory": state_history[-20:],
                        "latestCookState": cook_state,
                        "workItemStateCounts": status.get("workItemStateCounts"),
                    }
                )
                controller.set_progress(
                    min(95.0, 10.0 + len(state_history) * 5.0),
                    f"PDG state {cook_state}",
                )
                if controller.is_cancelled():
                    controller.run_live(
                        lambda: self._pdg_cancel_impl(graph_path),
                        operation_label="pdg-cancel",
                        timeout_seconds=max(context.timeout_seconds, 60.0),
                    )
                    raise OperationCancelledError(
                        f"PDG cook for {graph_path} was cancelled.",
                        {"graphPath": graph_path, "latestCookState": cook_state},
                    )
                if not status.get("cooking", False):
                    break
                time.sleep(0.25)

            final_workitems = self._pdg_get_workitems_impl({"graph_path": graph_path, "limit": 500})
            final_results = self._pdg_get_results_impl({"graph_path": graph_path, "limit": 500})
            final = {
                "graph": self._pdg_poll_status_impl(graph_path),
                "workItems": final_workitems["workItems"],
                "results": final_results["results"],
            }
            controller.set_progress(100.0, "PDG cook completed")
            controller.update_outcome({"partialResultsPossible": False})
            return final

        task = self._tasks.submit(
            task_type="pdg.cook",
            title=f"PDG cook {graph_path}",
            caller_id=context.caller_id,
            permissions=context.permissions,
            metadata={
                "graphPath": graph_path,
                "dirtyBefore": dirty_before,
                "generateOnly": generate_only,
                "topsOnly": tops_only,
            },
            runner=runner,
        )
        data = {
            "task": task,
            "taskResourceUri": f"houdini://tasks/{task['taskId']}",
            "taskLogResourceUri": f"houdini://tasks/{task['taskId']}/log",
        }
        return self._tool_response(f"Started PDG cook task {task['taskId']} for {graph_path}.", data)

    def _pdg_start_cook_impl(
        self,
        graph_path: str,
        dirty_before: bool,
        generate_only: bool,
        tops_only: bool,
    ) -> dict[str, Any]:
        graph_node = self._require_pdg_graph_node(graph_path)
        if dirty_before:
            graph_node.dirtyAllWorkItems(False)
        graph_node.executeGraph(block=False, generate_only=generate_only, tops_only=tops_only)
        return self._pdg_graph_summary(graph_node)
