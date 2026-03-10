"""Scene graph indexing, query, and diff operations."""

from __future__ import annotations

import copy
import re
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class GraphOperationsMixin:
    _CHANNEL_REF_PATTERN = re.compile(r"""ch[sifv]?\(\s*["']([^"']+)["']\s*\)""")
    _PYTHON_PARM_PATTERN = re.compile(r"""hou\.parm\(\s*["']([^"']+)["']\s*\)""")

    def _json_safe_graph_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [self._json_safe_graph_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._json_safe_graph_value(item)
                for key, item in value.items()
            }
        name_attr = getattr(value, "name", None)
        if callable(name_attr):
            try:
                return name_attr()
            except Exception:
                pass
        return str(value)

    def _parm_reference_paths(self, parm: Any) -> list[str]:
        references: list[str] = []
        referenced = self._safe_value(parm.getReferencedParm, None)
        if referenced is not None:
            ref_path = self._safe_value(referenced.path, None)
            if ref_path and ref_path != parm.path():
                references.append(str(ref_path))
        raw_value = self._safe_value(parm.rawValue, "") or ""
        expression = self._safe_value(parm.expression, "") or ""
        for candidate in self._CHANNEL_REF_PATTERN.findall(raw_value) + self._CHANNEL_REF_PATTERN.findall(expression):
            if candidate.startswith("/") and candidate not in references:
                references.append(candidate)
        for candidate in self._PYTHON_PARM_PATTERN.findall(expression):
            if candidate.startswith("/") and candidate not in references:
                references.append(candidate)
        return references

    def _graph_parm_summary(self, parm: Any) -> dict[str, Any]:
        expression_language = self._safe_value(parm.expressionLanguage, None)
        expression_language_name = None
        if expression_language is not None:
            expression_language_name = getattr(expression_language, "name", None)
            if callable(expression_language_name):
                expression_language_name = expression_language_name()
            if expression_language_name is None:
                expression_language_name = str(expression_language)
        return {
            "path": parm.path(),
            "name": parm.name(),
            "nodePath": self._safe_value(lambda: parm.node().path(), None),
            "label": self._safe_value(lambda: parm.parmTemplate().label(), parm.name()),
            "templateType": self._safe_value(lambda: parm.parmTemplate().type().name(), None),
            "rawValue": self._safe_value(parm.rawValue, None),
            "value": self._safe_value(parm.eval, None),
            "expression": self._safe_value(parm.expression, None),
            "expressionLanguage": expression_language_name,
            "referencePaths": self._parm_reference_paths(parm),
        }

    def _scene_graph_snapshot_build_impl(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        root = hou_module.node("/")
        if root is None:
            raise JsonRpcError(INVALID_PARAMS, "Could not resolve the Houdini root node.")

        nodes_by_path: dict[str, dict[str, Any]] = {}
        parms_by_path: dict[str, dict[str, Any]] = {}
        top_level_paths: list[str] = []
        stack = list(reversed(root.children()))
        while stack:
            node = stack.pop()
            if self._safe_value(lambda: node.parent().path(), None) == "/":
                top_level_paths.append(node.path())
            children = list(self._safe_value(node.children, []) or [])
            stack.extend(reversed(children))

            node_payload = self._node_summary(node, include_parms=False)
            node_payload["childPaths"] = [child.path() for child in children]
            node_payload["parmPaths"] = []
            node_payload["materialPath"] = self._material_path_for_node(node)
            node_payload["fileOutputs"] = self._node_file_parm_paths(node)
            nodes_by_path[node_payload["path"]] = node_payload

            for parm in node.parms():
                parm_payload = self._graph_parm_summary(parm)
                parms_by_path[parm_payload["path"]] = parm_payload
                node_payload["parmPaths"].append(parm_payload["path"])

        edges: list[dict[str, Any]] = []
        downstream_map: dict[str, list[str]] = {}
        upstream_map: dict[str, list[str]] = {}
        material_assignments: list[dict[str, Any]] = []
        parm_references: list[dict[str, Any]] = []

        for node_path, node_payload in nodes_by_path.items():
            for input_index, input_path in enumerate(node_payload.get("inputs", [])):
                if not input_path:
                    continue
                edge = {"kind": "input", "from": input_path, "to": node_path, "inputIndex": input_index}
                edges.append(edge)
                downstream_map.setdefault(input_path, []).append(node_path)
                upstream_map.setdefault(node_path, []).append(input_path)

            for edge_kind, target_key in (("display", "displayNodePath"), ("render", "renderNodePath"), ("output", "outputNodePath")):
                target_path = node_payload.get(target_key)
                if isinstance(target_path, str) and target_path:
                    edges.append({"kind": edge_kind, "from": node_path, "to": target_path})

            material_path = node_payload.get("materialPath")
            if isinstance(material_path, str) and material_path:
                assignment = {"kind": "material", "from": node_path, "to": material_path}
                material_assignments.append(assignment)
                edges.append(assignment)

        for parm_path, parm_payload in parms_by_path.items():
            for ref_path in parm_payload.get("referencePaths", []):
                edge = {
                    "kind": "parm_reference",
                    "from": parm_path,
                    "to": ref_path,
                    "fromNodePath": parm_payload.get("nodePath"),
                }
                parm_references.append(edge)
                edges.append(edge)

        for node_path, node_payload in nodes_by_path.items():
            node_payload["upstreamPaths"] = sorted(set(upstream_map.get(node_path, [])))
            node_payload["downstreamPaths"] = sorted(set(downstream_map.get(node_path, [])))

        return self._json_safe_graph_value(
            {
            "revision": self._monitor.snapshot()["revision"],
            "topLevelPaths": top_level_paths,
            "nodes": sorted(nodes_by_path.values(), key=lambda item: item["path"]),
            "parms": sorted(parms_by_path.values(), key=lambda item: item["path"]),
            "edges": edges,
            "materialAssignments": material_assignments,
            "parmReferences": parm_references,
            "stats": {
                "nodeCount": len(nodes_by_path),
                "parmCount": len(parms_by_path),
                "edgeCount": len(edges),
                "topLevelCount": len(top_level_paths),
            },
        })

    def _graph_snapshot(self) -> dict[str, Any]:
        return self._graph.get_or_refresh(
            revision=int(self._monitor.snapshot()["revision"]),
            builder=self._scene_graph_snapshot_build_impl,
            max_age_seconds=0.5,
        )

    @staticmethod
    def _graph_nodes_by_path(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {item["path"]: item for item in snapshot.get("nodes", [])}

    @staticmethod
    def _graph_parms_by_path(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {item["path"]: item for item in snapshot.get("parms", [])}

    def _graph_subgraph_payload(self, snapshot: dict[str, Any], root_path: str) -> dict[str, Any]:
        root_path = str(root_path).strip()
        if not root_path:
            raise JsonRpcError(INVALID_PARAMS, "root_path is required")
        nodes = [
            self._json_safe_graph_value(node)
            for node in snapshot.get("nodes", [])
            if node["path"] == root_path or node["path"].startswith(f"{root_path}/")
        ]
        if not nodes:
            raise JsonRpcError(INVALID_PARAMS, f"Subgraph root not found: {root_path}", {"rootPath": root_path})
        node_paths = {item["path"] for item in nodes}
        parms = [
            self._json_safe_graph_value(parm)
            for parm in snapshot.get("parms", [])
            if parm.get("nodePath") in node_paths
        ]
        parm_paths = {item["path"] for item in parms}
        edges = [
            self._json_safe_graph_value(edge)
            for edge in snapshot.get("edges", [])
            if (
                edge.get("kind") == "parm_reference" and edge.get("from") in parm_paths
            ) or (
                edge.get("kind") != "parm_reference" and edge.get("from") in node_paths and edge.get("to") in node_paths
            )
        ]
        return self._json_safe_graph_value({
            "rootPath": root_path,
            "revision": snapshot.get("revision"),
            "nodes": nodes,
            "parms": parms,
            "edges": edges,
            "stats": {"nodeCount": len(nodes), "parmCount": len(parms), "edgeCount": len(edges)},
        })

    def _graph_dependency_payload(self, snapshot: dict[str, Any], node_path: str) -> dict[str, Any]:
        node_path = str(node_path).strip()
        nodes_by_path = self._graph_nodes_by_path(snapshot)
        if node_path not in nodes_by_path:
            raise JsonRpcError(INVALID_PARAMS, f"Node not found: {node_path}")
        edges = [
            self._json_safe_graph_value(edge)
            for edge in snapshot.get("edges", [])
            if edge.get("from") == node_path or edge.get("to") == node_path or edge.get("fromNodePath") == node_path
        ]
        parm_refs = [
            self._json_safe_graph_value(parm)
            for parm in snapshot.get("parms", [])
            if parm.get("nodePath") == node_path and parm.get("referencePaths")
        ]
        return self._json_safe_graph_value({"node": nodes_by_path[node_path], "edges": edges, "referencingParms": parm_refs})

    def _graph_reference_payload(self, snapshot: dict[str, Any], node_path: str) -> dict[str, Any]:
        node_path = str(node_path).strip()
        refs = [
            self._json_safe_graph_value(parm)
            for parm in snapshot.get("parms", [])
            if parm.get("nodePath") == node_path and parm.get("referencePaths")
        ]
        if not refs and node_path not in self._graph_nodes_by_path(snapshot):
            raise JsonRpcError(INVALID_PARAMS, f"Node not found: {node_path}")
        return self._json_safe_graph_value({"nodePath": node_path, "count": len(refs), "parms": refs})

    def _graph_query_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._graph_snapshot()
        path_prefix = str(arguments.get("path_prefix", "")).strip() or None
        root_path = str(arguments.get("root_path", "")).strip() or None
        node_type_name = str(arguments.get("node_type_name", "")).strip() or None
        category = str(arguments.get("category", "")).strip() or None
        name_contains = str(arguments.get("name_contains", "")).strip().lower() or None
        material_path = str(arguments.get("material_path", "")).strip() or None
        flag_name = str(arguments.get("flag_name", "")).strip() or None
        flag_value = arguments.get("flag_value")
        limit = int(arguments.get("limit", 200))

        matches: list[dict[str, Any]] = []
        for node in snapshot.get("nodes", []):
            if root_path and not (node["path"] == root_path or node["path"].startswith(f"{root_path}/")):
                continue
            if path_prefix and not node["path"].startswith(path_prefix):
                continue
            if node_type_name and node.get("typeName") != node_type_name:
                continue
            if category and node.get("category") != category:
                continue
            if name_contains and name_contains not in str(node.get("name", "")).lower():
                continue
            if material_path and node.get("materialPath") != material_path:
                continue
            if flag_name:
                flags = node.get("flags", {})
                if flag_name not in flags:
                    continue
                if flag_value is not None and bool(flags.get(flag_name)) != bool(flag_value):
                    continue
            matches.append(self._json_safe_graph_value(node))
            if len(matches) >= limit:
                break

        return self._json_safe_graph_value({"count": len(matches), "revision": snapshot.get("revision"), "nodes": matches})

    def graph_query(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._graph_query_impl(arguments), context)
        return self._tool_response(f"Matched {data['count']} graph node(s).", data)

    def _graph_bfs_impl(self, start_path: str, *, direction: str, max_depth: int) -> dict[str, Any]:
        snapshot = self._graph_snapshot()
        nodes_by_path = self._graph_nodes_by_path(snapshot)
        if start_path not in nodes_by_path:
            raise JsonRpcError(INVALID_PARAMS, f"Node not found: {start_path}")

        frontier = [(start_path, 0)]
        visited = {start_path}
        traversed_edges: list[dict[str, Any]] = []
        ordered_nodes: list[dict[str, Any]] = [self._json_safe_graph_value(nodes_by_path[start_path])]
        while frontier:
            current, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            current_node = nodes_by_path[current]
            neighbor_paths = current_node.get("upstreamPaths", []) if direction == "upstream" else current_node.get("downstreamPaths", [])
            for neighbor in neighbor_paths:
                if neighbor not in nodes_by_path:
                    continue
                edge = {
                    "kind": direction,
                    "from": current if direction == "downstream" else neighbor,
                    "to": neighbor if direction == "downstream" else current,
                }
                traversed_edges.append(edge)
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                ordered_nodes.append(self._json_safe_graph_value(nodes_by_path[neighbor]))
                frontier.append((neighbor, depth + 1))
        return self._json_safe_graph_value({
            "startPath": start_path,
            "direction": direction,
            "maxDepth": max_depth,
            "count": len(ordered_nodes),
            "nodes": ordered_nodes,
            "edges": traversed_edges,
        })

    def graph_find_upstream(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        max_depth = int(arguments.get("max_depth", 20))
        data = self._call_live(lambda: self._graph_bfs_impl(path, direction="upstream", max_depth=max_depth), context)
        return self._tool_response(f"Found {data['count']} upstream node(s).", data)

    def graph_find_downstream(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        max_depth = int(arguments.get("max_depth", 20))
        data = self._call_live(lambda: self._graph_bfs_impl(path, direction="downstream", max_depth=max_depth), context)
        return self._tool_response(f"Found {data['count']} downstream node(s).", data)

    def graph_find_by_type(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        forwarded = {
            "node_type_name": arguments.get("node_type_name"),
            "root_path": arguments.get("root_path"),
            "limit": arguments.get("limit", 200),
        }
        data = self._call_live(lambda: self._graph_query_impl(forwarded), context)
        return self._tool_response(f"Matched {data['count']} node(s) of the requested type.", data)

    def graph_find_by_flag(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        forwarded = {
            "flag_name": arguments.get("flag_name"),
            "flag_value": arguments.get("flag_value", True),
            "root_path": arguments.get("root_path"),
            "limit": arguments.get("limit", 200),
        }
        data = self._call_live(lambda: self._graph_query_impl(forwarded), context)
        return self._tool_response(f"Matched {data['count']} node(s) by flag.", data)

    @staticmethod
    def _graph_node_diff_fields(node: dict[str, Any]) -> dict[str, Any]:
        return {
            "path": node.get("path"),
            "name": node.get("name"),
            "typeName": node.get("typeName"),
            "category": node.get("category"),
            "parentPath": node.get("parentPath"),
            "position": node.get("position"),
            "flags": node.get("flags"),
            "inputs": node.get("inputs"),
            "displayNodePath": node.get("displayNodePath"),
            "renderNodePath": node.get("renderNodePath"),
            "outputNodePath": node.get("outputNodePath"),
            "outputNodePaths": node.get("outputNodePaths"),
            "materialPath": node.get("materialPath"),
            "fileOutputs": node.get("fileOutputs"),
        }

    def _graph_diff_payload(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_nodes = self._graph_nodes_by_path(before)
        after_nodes = self._graph_nodes_by_path(after)
        before_parms = self._graph_parms_by_path(before)
        after_parms = self._graph_parms_by_path(after)
        before_edges = {repr(edge): edge for edge in before.get("edges", [])}
        after_edges = {repr(edge): edge for edge in after.get("edges", [])}

        created_node_paths = sorted(set(after_nodes) - set(before_nodes))
        deleted_node_paths = sorted(set(before_nodes) - set(after_nodes))
        changed_nodes: list[dict[str, Any]] = []
        for path in sorted(set(before_nodes) & set(after_nodes)):
            before_node = self._graph_node_diff_fields(before_nodes[path])
            after_node = self._graph_node_diff_fields(after_nodes[path])
            changes = {}
            for key in before_node:
                if before_node[key] != after_node[key]:
                    changes[key] = {"before": before_node[key], "after": after_node[key]}
            if changes:
                changed_nodes.append({"path": path, "changes": changes})

        parm_changes: list[dict[str, Any]] = []
        for parm_path in sorted(set(before_parms) | set(after_parms)):
            before_parm = before_parms.get(parm_path)
            after_parm = after_parms.get(parm_path)
            if before_parm is None:
                parm_changes.append({"path": parm_path, "changeType": "created", "after": after_parm})
                continue
            if after_parm is None:
                parm_changes.append({"path": parm_path, "changeType": "deleted", "before": before_parm})
                continue
            changes = {}
            for key in ("rawValue", "value", "expression", "referencePaths"):
                if before_parm.get(key) != after_parm.get(key):
                    changes[key] = {"before": before_parm.get(key), "after": after_parm.get(key)}
            if changes:
                parm_changes.append({"path": parm_path, "changeType": "updated", "changes": changes})

        created_edges = [self._json_safe_graph_value(after_edges[key]) for key in sorted(set(after_edges) - set(before_edges))]
        deleted_edges = [self._json_safe_graph_value(before_edges[key]) for key in sorted(set(before_edges) - set(after_edges))]
        return self._json_safe_graph_value({
            "summary": {
                "createdNodeCount": len(created_node_paths),
                "deletedNodeCount": len(deleted_node_paths),
                "changedNodeCount": len(changed_nodes),
                "changedParmCount": len(parm_changes),
                "createdEdgeCount": len(created_edges),
                "deletedEdgeCount": len(deleted_edges),
            },
            "createdNodes": [self._json_safe_graph_value(after_nodes[path]) for path in created_node_paths],
            "deletedNodes": [self._json_safe_graph_value(before_nodes[path]) for path in deleted_node_paths],
            "changedNodes": changed_nodes,
            "changedParms": parm_changes,
            "createdEdges": created_edges,
            "deletedEdges": deleted_edges,
        })

    def _extract_baseline_snapshot(self, baseline: Any) -> dict[str, Any]:
        if not isinstance(baseline, dict):
            raise JsonRpcError(INVALID_PARAMS, "baseline must be a graph snapshot object.")
        if "nodes" not in baseline:
            raise JsonRpcError(INVALID_PARAMS, "baseline snapshot must include a nodes array.")
        return baseline

    def _scene_diff_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        baseline = self._extract_baseline_snapshot(arguments.get("baseline"))
        current = self._graph_snapshot()
        diff = self._graph_diff_payload(baseline, current)
        diff["baselineRevision"] = baseline.get("revision")
        diff["currentRevision"] = current.get("revision")
        return diff

    def scene_diff(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._scene_diff_impl(arguments), context)
        return self._tool_response("Computed a scene graph diff.", data)

    def _graph_diff_subgraph_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        baseline = self._extract_baseline_snapshot(arguments.get("baseline"))
        root_path = str(arguments.get("root_path", "")).strip()
        current_subgraph = self._graph_subgraph_payload(self._graph_snapshot(), root_path)
        diff = self._graph_diff_payload(baseline, current_subgraph)
        diff["rootPath"] = root_path
        diff["baselineRevision"] = baseline.get("revision")
        diff["currentRevision"] = current_subgraph.get("revision")
        return diff

    def graph_diff_subgraph(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._graph_diff_subgraph_impl(arguments), context)
        return self._tool_response(f"Computed a subgraph diff for {data['rootPath']}.", data)

    def _planned_node_path(
        self,
        *,
        parent_path: str,
        node_type_name: str,
        node_name: str | None,
        fallback_index: int,
        existing_paths: set[str],
    ) -> str:
        proposed_name = node_name or f"{node_type_name}_planned_{fallback_index}"
        candidate = f"{parent_path.rstrip('/')}/{proposed_name}"
        if candidate not in existing_paths:
            return candidate
        suffix = 1
        while True:
            alt = f"{candidate}_{suffix}"
            if alt not in existing_paths:
                return alt
            suffix += 1

    def _simulate_graph_patch(self, snapshot: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
        state = copy.deepcopy(self._json_safe_graph_value(snapshot))
        nodes_by_path = self._graph_nodes_by_path(state)
        parms_by_path = self._graph_parms_by_path(state)
        refs: dict[str, str] = {}
        planned_results: list[dict[str, Any]] = []

        for index, raw_op in enumerate(operations):
            if not isinstance(raw_op, dict):
                raise JsonRpcError(INVALID_PARAMS, f"Operation at index {index} must be an object.")
            op_type = str(raw_op.get("type", "")).strip()
            op_id = str(raw_op.get("id", "")).strip()
            resolved = self._batch_resolve(raw_op, refs)

            if op_type == "create_node":
                parent_path = str(resolved.get("parent_path", "/obj")).strip() or "/obj"
                node_type_name = str(resolved.get("node_type_name", "")).strip()
                node_name = str(resolved.get("node_name", "")).strip() or None
                if parent_path not in nodes_by_path:
                    raise JsonRpcError(INVALID_PARAMS, f"Parent node not found in graph snapshot: {parent_path}")
                if not node_type_name:
                    raise JsonRpcError(INVALID_PARAMS, "create_node requires node_type_name")
                predicted_path = self._planned_node_path(
                    parent_path=parent_path,
                    node_type_name=node_type_name,
                    node_name=node_name,
                    fallback_index=index,
                    existing_paths=set(nodes_by_path.keys()),
                )
                node_payload = {
                    "path": predicted_path,
                    "name": predicted_path.rsplit("/", 1)[-1],
                    "typeName": node_type_name,
                    "category": None,
                    "parentPath": parent_path,
                    "isNetwork": True,
                    "position": None,
                    "flags": {"bypass": False, "display": None, "render": None, "template": None},
                    "inputs": [],
                    "childCount": 0,
                    "displayNodePath": None,
                    "renderNodePath": None,
                    "outputNodePath": None,
                    "outputNodePaths": [],
                    "childPaths": [],
                    "parmPaths": [],
                    "materialPath": None,
                    "fileOutputs": [],
                    "upstreamPaths": [],
                    "downstreamPaths": [],
                }
                nodes_by_path[predicted_path] = node_payload
                parent = nodes_by_path[parent_path]
                parent.setdefault("childPaths", []).append(predicted_path)
                parent["childCount"] = len(parent.get("childPaths", []))
                if op_id:
                    refs[op_id] = predicted_path
                planned_results.append({"index": index, "type": op_type, "path": predicted_path})
            elif op_type == "connect":
                source_path = str(resolved.get("source_node_path", "")).strip()
                dest_path = str(resolved.get("dest_node_path", "")).strip()
                dest_input_index = int(resolved.get("dest_input_index", 0))
                if source_path not in nodes_by_path or dest_path not in nodes_by_path:
                    raise JsonRpcError(INVALID_PARAMS, "connect references unknown path in graph snapshot.")
                dest = nodes_by_path[dest_path]
                inputs = list(dest.get("inputs", []))
                while len(inputs) <= dest_input_index:
                    inputs.append(None)
                inputs[dest_input_index] = source_path
                dest["inputs"] = inputs
                planned_results.append({"index": index, "type": op_type, "path": dest_path})
            elif op_type == "set_parm":
                parm_path = str(resolved.get("parm_path", "")).strip()
                node_path = parm_path.rsplit("/", 1)[0] if "/" in parm_path else None
                if not node_path or node_path not in nodes_by_path:
                    raise JsonRpcError(INVALID_PARAMS, f"Parameter target not found in graph snapshot: {parm_path}")
                parm_payload = self._json_safe_graph_value(
                    parms_by_path.get(
                        parm_path,
                        {
                            "path": parm_path,
                            "name": parm_path.rsplit("/", 1)[-1],
                            "nodePath": node_path,
                            "referencePaths": [],
                            "expression": None,
                        },
                    )
                )
                parm_payload["rawValue"] = resolved.get("value")
                parm_payload["value"] = resolved.get("value")
                parms_by_path[parm_path] = parm_payload
                if parm_path not in nodes_by_path[node_path].get("parmPaths", []):
                    nodes_by_path[node_path].setdefault("parmPaths", []).append(parm_path)
                planned_results.append({"index": index, "type": op_type, "path": parm_path})
            elif op_type == "set_flags":
                path = str(resolved.get("path", "")).strip()
                if path not in nodes_by_path:
                    raise JsonRpcError(INVALID_PARAMS, f"Node not found in graph snapshot: {path}")
                flags = dict(nodes_by_path[path].get("flags", {}))
                for key in ("bypass", "display", "render", "template"):
                    if key in resolved:
                        flags[key] = bool(resolved[key])
                nodes_by_path[path]["flags"] = flags
                planned_results.append({"index": index, "type": op_type, "path": path})
            elif op_type == "move_node":
                path = str(resolved.get("path", "")).strip()
                if path not in nodes_by_path:
                    raise JsonRpcError(INVALID_PARAMS, f"Node not found in graph snapshot: {path}")
                nodes_by_path[path]["position"] = [float(resolved.get("x", 0.0)), float(resolved.get("y", 0.0))]
                planned_results.append({"index": index, "type": op_type, "path": path})
            elif op_type == "layout":
                planned_results.append({"index": index, "type": op_type, "note": "layout is not simulated structurally"})
            else:
                raise JsonRpcError(INVALID_PARAMS, f"Unsupported patch operation type: {op_type}")

        state["nodes"] = sorted(nodes_by_path.values(), key=lambda item: item["path"])
        state["parms"] = sorted(parms_by_path.values(), key=lambda item: item["path"])
        return self._json_safe_graph_value({
            "refs": refs,
            "plannedResults": planned_results,
            "diff": self._graph_diff_payload(snapshot, state),
            "plannedGraph": state,
        })

    def _graph_plan_edit_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not operations:
            raise JsonRpcError(INVALID_PARAMS, "operations must be a non-empty array.")
        snapshot = self._graph_snapshot()
        result = self._simulate_graph_patch(snapshot, operations)
        result["currentRevision"] = snapshot.get("revision")
        return result

    def graph_plan_edit(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._graph_plan_edit_impl(arguments), context)
        return self._tool_response("Planned a graph patch against the current scene graph.", data)

    def graph_apply_patch(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        operations = arguments.get("operations")
        patch = arguments.get("patch")
        transactional = bool(arguments.get("transactional", True))
        dry_run = bool(arguments.get("dry_run", False))
        if patch is not None and operations is None:
            if not isinstance(patch, dict):
                raise JsonRpcError(INVALID_PARAMS, "patch must be an object with an operations array.")
            operations = patch.get("operations")

        plan = self._call_live(lambda: self._graph_plan_edit_impl({"operations": operations}), context)
        if dry_run:
            return self._tool_response("Computed a dry-run graph patch plan.", {"dryRun": True, "plan": plan})

        execution = self.graph_batch_edit(
            {
                "operations": operations,
                "transactional": transactional,
                "label": str(arguments.get("label", "graph patch")).strip() or "graph patch",
            },
            context,
        )
        self._monitor.mark_dirty("tool:graph.apply_patch")
        after_snapshot = self._call_live(self._graph_snapshot, context)
        return self._tool_response(
            "Applied graph patch operations.",
            {
                "dryRun": False,
                "transactional": transactional,
                "plan": plan,
                "execution": execution["structuredContent"],
                "postApplyRevision": after_snapshot.get("revision"),
            },
        )

    def read_graph_scene(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://graph/scene",
            self._call_live(self._graph_snapshot, context),
        )

    def read_graph_index(self, context: RequestContext) -> dict[str, Any]:
        data = {
            "monitorRevision": self._monitor.snapshot()["revision"],
            "cache": self._graph.stats(),
        }
        return self._resource_response("houdini://graph/index", data)
