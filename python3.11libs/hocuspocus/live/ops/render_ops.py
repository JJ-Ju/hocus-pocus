"""Render graph inspection, preflight, and lookdev helpers."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class RenderOperationsMixin:
    def _require_rop_node(self, node_path: str) -> Any:
        hou_module = self._require_hou()
        node = self._require_node_by_path(node_path)
        if not isinstance(node, hou_module.RopNode):
            raise JsonRpcError(INVALID_PARAMS, f"Node is not a ROP: {node_path}")
        return node

    def _render_node_reference_payload(self, node: Any) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for parm in node.parms():
            parm_template = self._safe_value(parm.parmTemplate, None)
            string_type = self._safe_value(lambda: parm_template.stringType().name(), None) if parm_template is not None else None
            if string_type != "NodeReference":
                continue
            raw = str(
                self._safe_value(parm.unexpandedString, None)
                or self._safe_value(parm.evalAsString, None)
                or ""
            ).strip()
            if not raw:
                continue
            target = self._safe_value(lambda raw=raw: self._require_node_by_path(raw), None)
            refs.append(
                {
                    "parmPath": parm.path(),
                    "targetPath": raw,
                    "exists": target is not None,
                }
            )
        return refs

    def _render_outputs_payload(self, node: Any) -> dict[str, Any]:
        file_parms: list[dict[str, Any]] = []
        for parm_name in ("picture", "vm_picture", "sopoutput", "lopoutput", "copoutput", "filename", "output"):
            parm = self._safe_value(lambda parm_name=parm_name: node.parm(parm_name), None)
            if parm is None:
                continue
            value = str(
                self._safe_value(parm.unexpandedString, None)
                or self._safe_value(parm.evalAsString, None)
                or ""
            ).strip()
            if not value:
                continue
            file_parms.append(
                {
                    "parmPath": parm.path(),
                    "parmName": parm.name(),
                    "rawValue": value,
                    "expandedPath": self._safe_value(lambda value=value: self._require_hou().expandString(value), value),
                }
            )

        aovs: list[dict[str, Any]] = []
        vm_numaux = self._safe_value(lambda: node.parm("vm_numaux"), None)
        if vm_numaux is not None:
            count = int(self._safe_value(vm_numaux.eval, 0) or 0)
            for index in range(1, count + 1):
                variable_parm = self._safe_value(lambda index=index: node.parm(f"vm_variable_plane{index}"), None)
                channel_parm = self._safe_value(lambda index=index: node.parm(f"vm_channel_plane{index}"), None)
                use_file_parm = self._safe_value(lambda index=index: node.parm(f"vm_usefile_plane{index}"), None)
                file_parm = self._safe_value(lambda index=index: node.parm(f"vm_filename_plane{index}"), None)
                aovs.append(
                    {
                        "index": index,
                        "variable": self._safe_value(variable_parm.evalAsString, None) if variable_parm is not None else None,
                        "channel": self._safe_value(channel_parm.evalAsString, None) if channel_parm is not None else None,
                        "useSeparateFile": bool(self._safe_value(use_file_parm.eval, False)) if use_file_parm is not None else False,
                        "filePath": self._safe_value(file_parm.evalAsString, None) if file_parm is not None else None,
                    }
                )

        return {
            "node": self._node_summary(node, include_parms=False),
            "fileParms": file_parms,
            "validatedOutputPaths": self._validate_render_output_paths(node),
            "aovs": aovs,
            "supportsAovInspection": bool(vm_numaux is not None),
        }

    def _render_graph_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        start = self._require_rop_node(str(arguments.get("node_path", "")).strip())
        max_depth = int(arguments.get("max_depth", 20))
        visited: set[str] = set()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        def walk(node: Any, depth: int) -> None:
            path = node.path()
            if path in visited or depth > max_depth:
                return
            visited.add(path)
            frame_range = {
                "trange": self._safe_value(lambda: node.parm("trange").evalAsString(), None),
                "f1": self._safe_value(lambda: node.parm("f1").eval(), None),
                "f2": self._safe_value(lambda: node.parm("f2").eval(), None),
                "f3": self._safe_value(lambda: node.parm("f3").eval(), None),
            }
            nodes.append(
                {
                    "node": self._node_summary(node, include_parms=False),
                    "validatedOutputPaths": self._validate_render_output_paths(node),
                    "frameRange": frame_range,
                    "nodeReferences": self._render_node_reference_payload(node),
                }
            )
            for input_node in node.inputs():
                if input_node is None:
                    continue
                edges.append({"from": input_node.path(), "to": path, "kind": "input"})
                walk(input_node, depth + 1)

        walk(start, 0)
        return {
            "rootNodePath": start.path(),
            "countNodes": len(nodes),
            "countEdges": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    def render_inspect_graph(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._render_graph_impl(arguments), context)
        return self._tool_response(
            f"Inspected render graph with {data['countNodes']} node(s).",
            data,
        )

    def _render_inspect_outputs_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node = self._require_rop_node(str(arguments.get("node_path", "")).strip())
        return self._render_outputs_payload(node)

    def render_inspect_outputs(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._render_inspect_outputs_impl(arguments), context)
        return self._tool_response("Inspected render outputs.", data)

    def _render_preflight_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        graph = self._render_graph_impl(arguments)
        issues: list[dict[str, Any]] = []
        graph_node_paths = {entry["node"]["path"] for entry in graph["nodes"]}

        dependency_entries = self._dependency_entries(node_paths=graph_node_paths)
        for entry in dependency_entries:
            if entry["direction"] == "input" and not entry["exists"]:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "missing_input_dependency",
                        "parmPath": entry["parmPath"],
                        "path": entry["expandedPath"] or entry["rawValue"],
                    }
                )
            if not entry["approved"]:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "path_policy",
                        "parmPath": entry["parmPath"],
                        "details": entry["policyError"],
                    }
                )

        for node_entry in graph["nodes"]:
            node_path = node_entry["node"]["path"]
            for ref in node_entry["nodeReferences"]:
                if not ref["exists"]:
                    issues.append(
                        {
                            "severity": "error",
                            "kind": "missing_node_reference",
                            "nodePath": node_path,
                            "parmPath": ref["parmPath"],
                            "targetPath": ref["targetPath"],
                        }
                    )

        severity_order = {"error": 2, "warning": 1, "info": 0}
        highest_severity = "info"
        if issues:
            highest_severity = max(
                (issue["severity"] for issue in issues),
                key=lambda severity: severity_order.get(severity, 0),
            )

        return {
            "rootNodePath": graph["rootNodePath"],
            "canRender": highest_severity != "error",
            "highestSeverity": highest_severity,
            "issueCount": len(issues),
            "issues": issues,
            "graph": graph,
        }

    def render_preflight(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._render_preflight_impl(arguments), context)
        state = "can proceed" if data["canRender"] else "has blocking issues"
        return self._tool_response(
            f"Render preflight {state} with {data['issueCount']} issue(s).",
            data,
        )

    def _create_light_node(self, parent: Any, node_name: str) -> Any:
        candidates = ("hlight::2.0", "hlight", "light")
        for node_type_name in candidates:
            try:
                return parent.createNode(node_type_name, node_name=node_name)
            except Exception:
                continue
        raise JsonRpcError(
            INVALID_PARAMS,
            "Could not create a supported object light node in this Houdini session.",
            {"candidates": list(candidates)},
        )

    def _lookdev_create_three_point_light_rig_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        obj = self._require_node_by_path("/obj")
        rig_name = str(arguments.get("rig_name", "lookdev_rig")).strip() or "lookdev_rig"
        target_name = str(arguments.get("target_name", f"{rig_name}_target")).strip() or f"{rig_name}_target"
        key_name = str(arguments.get("key_name", f"{rig_name}_key")).strip() or f"{rig_name}_key"
        fill_name = str(arguments.get("fill_name", f"{rig_name}_fill")).strip() or f"{rig_name}_fill"
        rim_name = str(arguments.get("rim_name", f"{rig_name}_rim")).strip() or f"{rig_name}_rim"

        with hou_module.undos.group("HocusPocus: create three point light rig"):
            target = obj.createNode("null", node_name=target_name)
            key = self._create_light_node(obj, key_name)
            fill = self._create_light_node(obj, fill_name)
            rim = self._create_light_node(obj, rim_name)

            target.parmTuple("t").set((0.0, 1.5, 0.0))
            key.parmTuple("t").set((6.0, 5.0, 6.0))
            fill.parmTuple("t").set((-6.0, 2.5, 4.5))
            rim.parmTuple("t").set((0.0, 4.0, -7.0))

            for light, intensity, exposure, color in (
                (key, 1.0, 1.5, (1.0, 0.96, 0.9)),
                (fill, 0.5, 0.25, (0.78, 0.84, 1.0)),
                (rim, 0.75, 1.0, (1.0, 1.0, 1.0)),
            ):
                lookat = self._safe_value(lambda light=light: light.parm("lookatpath"), None)
                if lookat is not None:
                    lookat.set(target.path())
                intensity_parm = self._safe_value(lambda light=light: light.parm("light_intensity"), None)
                if intensity_parm is None:
                    intensity_parm = self._safe_value(lambda light=light: light.parm("intensity"), None)
                if intensity_parm is not None:
                    intensity_parm.set(intensity)
                exposure_parm = self._safe_value(lambda light=light: light.parm("light_exposure"), None)
                if exposure_parm is not None:
                    exposure_parm.set(exposure)
                color_parm = self._safe_value(lambda light=light: light.parmTuple("light_color"), None)
                if color_parm is None:
                    color_parm = self._safe_value(lambda light=light: light.parmTuple("light_colorr"), None)
                if color_parm is not None and len(color_parm) >= 3:
                    color_parm.set(color)

            obj.layoutChildren(items=(target, key, fill, rim))

        return {
            "target": self._node_summary(target, include_parms=False),
            "lights": [
                self._node_summary(key, include_parms=False),
                self._node_summary(fill, include_parms=False),
                self._node_summary(rim, include_parms=False),
            ],
        }

    def lookdev_create_three_point_light_rig(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._lookdev_create_three_point_light_rig_impl(arguments), context)
        return self._tool_response(
            f"Created three-point light rig targeting {data['target']['path']}.",
            data,
        )

    def read_render_graph(self, node_path: str, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            f"houdini://renders/graph{node_path}",
            self._call_live(lambda: self._render_graph_impl({"node_path": node_path}), context),
        )
