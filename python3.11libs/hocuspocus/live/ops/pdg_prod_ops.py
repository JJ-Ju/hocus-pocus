"""Deeper PDG production orchestration tools."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class PdgProductionOperationsMixin:
    def _pdg_scheduler_summaries_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        if not graph_path:
            raise JsonRpcError(INVALID_PARAMS, "graph_path is required")
        graph_node = self._require_pdg_graph_node(graph_path)
        ctx = graph_node.getPDGGraphContext()
        graph = ctx.graph
        schedulers = []
        for child in graph_node.allSubChildren():
            type_name = self._safe_value(lambda child=child: child.type().name(), "") or ""
            if "scheduler" not in type_name.lower():
                continue
            schedulers.append(
                {
                    "node": self._node_summary(child, include_parms=False),
                    "workingDir": self._safe_value(lambda child=child: child.parm("pdg_workingdir").evalAsString(), None),
                    "maxThreads": self._safe_value(lambda child=child: child.parm("maxprocsmenu").evalAsString(), None),
                    "graphCooking": bool(ctx.cooking),
                    "schedulerTypeName": type_name,
                }
            )
        return {
            "graphPath": graph_path,
            "graphNodeCount": self._safe_value(graph.nodeCount, None),
            "count": len(schedulers),
            "schedulers": schedulers,
        }

    def pdg_inspect_schedulers(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_scheduler_summaries_impl(arguments), context)
        return self._tool_response(f"Found {data['count']} PDG scheduler node(s).", data)

    def _pdg_get_workitem_logs_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._pdg_get_workitems_impl(arguments)
        work_item_ids = {int(item) for item in arguments.get("work_item_ids", [])} if isinstance(arguments.get("work_item_ids"), list) else None
        logs = []
        for item in payload["workItems"]:
            if work_item_ids and int(item.get("id", -1)) not in work_item_ids:
                continue
            messages = list(item.get("logMessages") or [])
            if not messages:
                continue
            logs.append(
                {
                    "workItemId": item.get("id"),
                    "workItemName": item.get("name"),
                    "pdgNodeName": item.get("pdgNodeName"),
                    "state": item.get("state"),
                    "messages": messages,
                }
            )
        return {
            "graphPath": payload["graphPath"],
            "nodePath": payload["nodePath"],
            "count": len(logs),
            "logs": logs,
        }

    def pdg_get_workitem_logs(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_get_workitem_logs_impl(arguments), context)
        return self._tool_response(f"Returned logs for {data['count']} PDG work item(s).", data)

    def _pdg_retry_workitems_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        node_path = str(arguments.get("node_path", "")).strip() or None
        execute = bool(arguments.get("execute", False))
        if not graph_path:
            raise JsonRpcError(INVALID_PARAMS, "graph_path is required")
        graph_node = self._require_pdg_graph_node(graph_path)
        if node_path:
            node = self._require_node_by_path(node_path, label="node_path")
            pdg_node = node.getPDGNode()
            if pdg_node is None:
                raise JsonRpcError(INVALID_PARAMS, f"Node has no PDG node: {node_path}")
            self._safe_value(lambda: pdg_node.dirty(False))
            target_nodes = [node.path()]
        else:
            self._safe_value(lambda: graph_node.getPDGGraphContext().graph.dirty(False))
            target_nodes = [graph_path]
        if execute:
            graph_node.executeGraph(block=False)
        return {
            "graphPath": graph_path,
            "nodePath": node_path,
            "execute": execute,
            "dirtiedTargets": target_nodes,
            "graph": self._pdg_graph_summary(graph_node),
        }

    def pdg_retry_workitems(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_retry_workitems_impl(arguments), context)
        verb = "Dirtied and restarted" if data["execute"] else "Dirtied"
        return self._tool_response(f"{verb} PDG work for {data['graphPath']}.", data)

    def _pdg_graph_state_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graph_path = str(arguments.get("graph_path", "")).strip()
        if not graph_path:
            raise JsonRpcError(INVALID_PARAMS, "graph_path is required")
        graph_node = self._require_pdg_graph_node(graph_path)
        workitems = self._pdg_get_workitems_impl({"graph_path": graph_path, "limit": int(arguments.get("limit", 500))})
        return {
            "graph": self._pdg_graph_summary(graph_node),
            "workItems": workitems["workItems"],
        }

    def pdg_get_graph_state(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._pdg_graph_state_impl(arguments), context)
        return self._tool_response(f"Returned PDG graph state for {data['graph']['graphPath']}.", data)

    def read_pdg_graph_state(self, graph_path: str, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            f"houdini://pdg/graph{graph_path}",
            self._call_live(lambda: self._pdg_graph_state_impl({"graph_path": graph_path}), context),
        )
