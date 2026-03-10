"""Cook and render task operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class TaskExecutionOperationsMixin:
    def _cook_node_frame_impl(self, node_path: str, frame: float, force: bool) -> dict[str, Any]:
        node = self._require_node_by_path(node_path)
        node.cook(force=force, frame_range=(frame, frame, 1.0))
        return {
            "nodePath": node.path(),
            "frame": frame,
            "messages": self._safe_method_value(node, "messages", []),
            "errors": self._safe_method_value(node, "errors", []),
            "warnings": self._safe_method_value(node, "warnings", []),
        }

    def _cook_node_result_impl(self, node_path: str) -> dict[str, Any]:
        node = self._require_node_by_path(node_path)
        payload = {
            "node": self._node_summary(node, include_parms=False),
            "messages": self._safe_method_value(node, "messages", []),
            "errors": self._safe_method_value(node, "errors", []),
            "warnings": self._safe_method_value(node, "warnings", []),
        }
        try:
            payload["geometrySummary"] = self._geometry_summary_for_node(node)
        except JsonRpcError:
            payload["geometrySummary"] = None
        return payload

    def cook_node(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        hou_module = self._require_hou()
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        frames = self._frame_sequence(arguments.get("frame_range"), default_frame=hou_module.frame())
        force = bool(arguments.get("force", False))

        def runner(controller: Any) -> dict[str, Any]:
            controller.log(f"Cooking {node_path} across {len(frames)} frame(s).")
            total = len(frames)
            for index, frame in enumerate(frames, start=1):
                controller.raise_if_cancelled()
                controller.set_progress(
                    10.0 + ((index - 1) / max(total, 1)) * 80.0,
                    f"Cooking frame {frame}",
                )
                result = controller.run_live(
                    lambda frame=frame: self._cook_node_frame_impl(node_path, frame, force),
                    operation_label=f"cook-{index}",
                    timeout_seconds=max(context.timeout_seconds, 600.0),
                )
                if result.get("errors"):
                    controller.log(
                        f"Cook frame {frame} reported {len(result['errors'])} error(s).",
                        level="warning",
                    )
            controller.set_progress(95.0, "Collecting cook result")
            final = controller.run_live(
                lambda: self._cook_node_result_impl(node_path),
                operation_label="cook-result",
                timeout_seconds=max(context.timeout_seconds, 120.0),
            )
            final["frames"] = frames
            return final

        task = self._tasks.submit(
            task_type="cook.node",
            title=f"Cook {node_path}",
            caller_id=context.caller_id,
            permissions=context.permissions,
            metadata={"nodePath": node_path, "frames": frames, "force": force},
            runner=runner,
        )
        data = {
            "task": task,
            "taskResourceUri": f"houdini://tasks/{task['taskId']}",
            "taskLogResourceUri": f"houdini://tasks/{task['taskId']}/log",
        }
        return self._tool_response(f"Started cook task {task['taskId']} for {node_path}.", data)

    def _render_rop_frame_impl(
        self,
        node_path: str,
        frame: float,
        ignore_inputs: bool,
        verbose: bool,
        controller: Any,
    ) -> dict[str, Any]:
        hou_module = self._require_hou()
        node = self._require_node_by_path(node_path)
        if not isinstance(node, hou_module.RopNode):
            raise JsonRpcError(INVALID_PARAMS, f"Node is not a ROP: {node_path}")
        output_paths = self._validate_render_output_paths(node)

        def on_render_event(*event_args: Any) -> None:
            if len(event_args) < 2:
                return
            event_type = event_args[1]
            event_name_attr = getattr(event_type, "name", None)
            event_name = event_name_attr() if callable(event_name_attr) else event_name_attr
            if not event_name:
                event_name = str(event_type)
            controller.log(f"Render event {event_name} at frame {frame}.")

        self._safe_value(lambda: node.addRenderEventCallback(on_render_event))
        try:
            node.render(
                frame_range=(frame, frame, 1.0),
                ignore_inputs=ignore_inputs,
                verbose=verbose,
            )
        finally:
            self._safe_value(lambda: node.removeRenderEventCallback(on_render_event))
        return {
            "nodePath": node.path(),
            "frame": frame,
            "outputPaths": output_paths,
            "messages": self._safe_method_value(node, "messages", []),
            "errors": self._safe_method_value(node, "errors", []),
            "warnings": self._safe_method_value(node, "warnings", []),
        }

    def _render_rop_result_impl(self, node_path: str) -> dict[str, Any]:
        hou_module = self._require_hou()
        node = self._require_node_by_path(node_path)
        if not isinstance(node, hou_module.RopNode):
            raise JsonRpcError(INVALID_PARAMS, f"Node is not a ROP: {node_path}")
        return {
            "node": self._node_summary(node, include_parms=False),
            "outputPaths": self._validate_render_output_paths(node),
            "messages": self._safe_method_value(node, "messages", []),
            "errors": self._safe_method_value(node, "errors", []),
            "warnings": self._safe_method_value(node, "warnings", []),
        }

    def render_rop(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        hou_module = self._require_hou()
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        frames = self._frame_sequence(arguments.get("frame_range"), default_frame=hou_module.frame())
        ignore_inputs = bool(arguments.get("ignore_inputs", False))
        verbose = bool(arguments.get("verbose", True))

        def runner(controller: Any) -> dict[str, Any]:
            controller.log(f"Rendering {node_path} across {len(frames)} frame(s).")
            total = len(frames)
            for index, frame in enumerate(frames, start=1):
                controller.raise_if_cancelled()
                controller.set_progress(
                    10.0 + ((index - 1) / max(total, 1)) * 80.0,
                    f"Rendering frame {frame}",
                )
                result = controller.run_live(
                    lambda frame=frame: self._render_rop_frame_impl(
                        node_path,
                        frame,
                        ignore_inputs,
                        verbose,
                        controller,
                    ),
                    operation_label=f"render-{index}",
                    timeout_seconds=max(context.timeout_seconds, 3600.0),
                )
                if result.get("errors"):
                    controller.log(
                        f"Render frame {frame} reported {len(result['errors'])} error(s).",
                        level="warning",
                    )
            controller.set_progress(95.0, "Collecting render result")
            final = controller.run_live(
                lambda: self._render_rop_result_impl(node_path),
                operation_label="render-result",
                timeout_seconds=max(context.timeout_seconds, 120.0),
            )
            final["frames"] = frames
            return final

        task = self._tasks.submit(
            task_type="render.rop",
            title=f"Render {node_path}",
            caller_id=context.caller_id,
            permissions=context.permissions,
            metadata={
                "nodePath": node_path,
                "frames": frames,
                "ignoreInputs": ignore_inputs,
            },
            runner=runner,
        )
        data = {
            "task": task,
            "taskResourceUri": f"houdini://tasks/{task['taskId']}",
            "taskLogResourceUri": f"houdini://tasks/{task['taskId']}/log",
        }
        return self._tool_response(f"Started render task {task['taskId']} for {node_path}.", data)
