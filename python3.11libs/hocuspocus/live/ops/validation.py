"""Validation and event-feed operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class ValidationOperationsMixin:
    def _broken_reference_payload(self, root_path: str | None = None) -> dict[str, Any]:
        snapshot = self._graph_snapshot()
        broken: list[dict[str, Any]] = []
        for parm in snapshot.get("parms", []):
            node_path = parm.get("nodePath")
            if root_path and node_path:
                if not (node_path == root_path or node_path.startswith(f"{root_path}/")):
                    continue
            for ref_path in parm.get("referencePaths", []):
                if self._safe_value(lambda ref_path=ref_path: self._require_parm_by_path(ref_path), None) is None:
                    broken.append(
                        {
                            "parmPath": parm.get("path"),
                            "nodePath": node_path,
                            "referencePath": ref_path,
                            "reason": "target_missing",
                        }
                    )
        return {
            "rootPath": root_path,
            "count": len(broken),
            "brokenReferences": broken,
        }

    def parm_find_broken_refs(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip() or None
        data = self._call_live(lambda: self._broken_reference_payload(root_path), context)
        return self._tool_response(f"Found {data['count']} broken parameter reference(s).", data)

    def _usd_validation_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        snapshot = self._graph_snapshot()
        for node in snapshot.get("nodes", []):
            node_path = node.get("path")
            type_name = node.get("typeName")
            if type_name == "reference":
                parm = self._safe_value(lambda node_path=node_path: self._require_parm_by_path(f"{node_path}/filepath1"), None)
                if parm is not None:
                    value = self._safe_value(parm.evalAsString, "") or ""
                    if not value:
                        issues.append({"severity": "warning", "kind": "usd_reference_missing_file", "path": node_path})
            if type_name == "configurelayer":
                parm = self._safe_value(lambda node_path=node_path: self._require_parm_by_path(f"{node_path}/savepath"), None)
                if parm is not None:
                    value = self._safe_value(parm.evalAsString, "") or ""
                    if value:
                        try:
                            ensure_path_allowed(value, self._settings)
                        except JsonRpcError as exc:
                            issues.append({"severity": "error", "kind": "usd_layer_savepath_policy", "path": node_path, "details": exc.to_payload()})
        return issues

    def _render_export_validation_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        hou_module = self._require_hou()
        for root_path in ("/out",):
            root = hou_module.node(root_path)
            if root is None:
                continue
            for node in root.children():
                try:
                    self._validate_render_output_paths(node)
                except JsonRpcError as exc:
                    issues.append(
                        {
                            "severity": "error",
                            "kind": "output_policy",
                            "path": node.path(),
                            "details": exc.to_payload(),
                        }
                    )
        return issues

    def graph_check_errors(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip() or None
        broken_refs = self._broken_reference_payload(root_path)["brokenReferences"]
        material_issues = []
        snapshot = self._graph_snapshot()
        nodes_by_path = {node["path"]: node for node in snapshot.get("nodes", [])}
        for node in snapshot.get("nodes", []):
            if root_path and not (node["path"] == root_path or node["path"].startswith(f"{root_path}/")):
                continue
            material_path = node.get("materialPath")
            if material_path and material_path not in nodes_by_path:
                material_issues.append(
                    {
                        "severity": "warning",
                        "kind": "missing_material_node",
                        "path": node["path"],
                        "materialPath": material_path,
                    }
                )
        issues = broken_refs + material_issues
        data = {
            "rootPath": root_path,
            "count": len(issues),
            "issues": issues,
        }
        return self._tool_response(f"Found {data['count']} graph issue(s).", data)

    def scene_validate(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        broken_refs = self._call_live(lambda: self._broken_reference_payload(None), context)
        usd_issues = self._call_live(self._usd_validation_issues, context)
        output_issues = self._call_live(self._render_export_validation_issues, context)
        issues = broken_refs["brokenReferences"] + usd_issues + output_issues
        summary = {
            "issueCount": len(issues),
            "brokenReferenceCount": broken_refs["count"],
            "usdIssueCount": len(usd_issues),
            "outputIssueCount": len(output_issues),
        }
        data = {
            "summary": summary,
            "issues": issues,
            "graph": self._graph.stats(),
        }
        return self._tool_response(f"Validated scene with {summary['issueCount']} issue(s).", data)

    def scene_events_recent(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        limit = int(arguments.get("limit", 100))
        after_sequence = arguments.get("after_sequence")
        after_sequence_value = int(after_sequence) if after_sequence is not None else None
        data = self._monitor.recent_events(limit=limit, after_sequence=after_sequence_value)
        return self._tool_response(f"Returned {data['count']} recent scene event(s).", data)

    def read_scene_events(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://scene/events",
            self._monitor.recent_events(limit=200),
        )
