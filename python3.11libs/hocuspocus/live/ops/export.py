"""Alembic and USD export operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import OperationCancelledError, RequestContext


class ExportOperationsMixin:
    def _ensure_out_network(self) -> Any:
        return self._require_node_by_path("/out", label="export network")

    def _normalize_export_path(self, path_value: Any, *, stem: str, suffix: str) -> Path:
        if path_value:
            output_path = ensure_path_allowed(str(path_value), self._settings)
        else:
            output_path = self._managed_export_path(stem, suffix)
            output_path = ensure_path_allowed(output_path, self._settings)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _configure_frame_range(self, node: Any, frames: list[float]) -> None:
        trange = self._safe_value(lambda: node.parm("trange"), None)
        f1 = self._safe_value(lambda: node.parm("f1"), None)
        f2 = self._safe_value(lambda: node.parm("f2"), None)
        f3 = self._safe_value(lambda: node.parm("f3"), None)
        if trange is not None:
            trange.set(1)
        if f1 is not None:
            f1.set(frames[0])
        if f2 is not None:
            f2.set(frames[-1])
        if f3 is not None:
            step = frames[1] - frames[0] if len(frames) > 1 else 1.0
            f3.set(step)

    def _resolve_alembic_sop_path(self, source_node: Any) -> str:
        display_node = self._safe_method_value(source_node, "displayNode", None)
        if display_node is not None:
            return display_node.path()
        geometry = self._safe_method_value(source_node, "geometry", None)
        if geometry is not None:
            return source_node.path()
        raise JsonRpcError(
            INVALID_PARAMS,
            "Alembic export requires a SOP node or an object with a display SOP.",
            {"nodePath": source_node.path()},
        )

    def _existing_output_paths(self, paths: list[str | Path]) -> list[str]:
        existing: list[str] = []
        for path in paths:
            candidate = Path(path)
            if candidate.exists():
                existing.append(str(candidate.resolve(strict=False)))
        return existing

    def _create_temp_export_node(self, node_type_name: str, node_name: str) -> Any:
        out = self._ensure_out_network()
        return out.createNode(node_type_name, node_name=node_name)

    def _export_alembic_impl(
        self,
        source_node_path: str,
        output_path: str,
        frames: list[float],
        root_path: str,
    ) -> dict[str, Any]:
        hou_module = self._require_hou()
        source = self._require_node_by_path(source_node_path, label="source_node_path")
        export_node = self._create_temp_export_node("alembic", "hp_export_alembic")
        try:
            filename = export_node.parm("filename")
            use_sop_path = export_node.parm("use_sop_path")
            sop_path = export_node.parm("sop_path")
            root = export_node.parm("root")
            if filename is None or use_sop_path is None or sop_path is None or root is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Alembic export node does not expose the expected parameters.",
                    {"nodePath": export_node.path()},
                )
            filename.set(output_path)
            use_sop_path.set(1)
            sop_path.set(self._resolve_alembic_sop_path(source))
            root.set(root_path)
            self._configure_frame_range(export_node, frames)
            export_node.render(frame_range=(frames[0], frames[-1], frames[1] - frames[0] if len(frames) > 1 else 1.0))
            return {
                "exportNodePath": export_node.path(),
                "sourceNodePath": source.path(),
                "outputPaths": [output_path],
                "existingOutputPaths": self._existing_output_paths([output_path]),
                "messages": self._safe_method_value(export_node, "messages", []),
                "errors": self._safe_method_value(export_node, "errors", []),
                "warnings": self._safe_method_value(export_node, "warnings", []),
            }
        finally:
            self._safe_value(export_node.destroy)

    def export_alembic(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        hou_module = self._require_hou()
        source_node_path = str(arguments.get("source_node_path", "")).strip()
        if not source_node_path:
            raise JsonRpcError(INVALID_PARAMS, "source_node_path is required")
        frames = self._frame_sequence(arguments.get("frame_range"), default_frame=hou_module.frame())
        root_path = str(arguments.get("root_path", "/obj")).strip() or "/obj"
        output_path = self._normalize_export_path(
            arguments.get("path"),
            stem="alembic_export",
            suffix=".abc",
        )
        recovery_note = (
            "Alembic export cancellation is cooperative. Once the underlying Alembic ROP render call starts, "
            "Houdini may finish the active export call before cancellation is observed."
        )

        def runner(controller: Any) -> dict[str, Any]:
            controller.add_recovery_note(recovery_note)
            controller.set_outcome(
                {
                    "exportType": "alembic",
                    "expectedOutputPaths": [str(output_path)],
                    "existingOutputPaths": [],
                    "partialOutputsPossible": True,
                    "cancellationSemantics": "cooperative_single_export_call",
                    "completedFrames": [],
                    "remainingFrames": frames,
                }
            )
            controller.log(f"Exporting Alembic from {source_node_path} to {output_path}.")
            controller.set_progress(10.0, "Running Alembic export")
            result = controller.run_live(
                lambda: self._export_alembic_impl(source_node_path, str(output_path), frames, root_path),
                operation_label="export-alembic",
                timeout_seconds=max(context.timeout_seconds, 3600.0),
            )
            existing_outputs = result.get("existingOutputPaths", [])
            controller.update_outcome(
                {
                    "existingOutputPaths": existing_outputs,
                    "completedFrames": frames,
                    "remainingFrames": [],
                    "partialOutputsPossible": False,
                }
            )
            controller.set_progress(100.0, "Alembic export completed")
            result["frames"] = frames
            result["outputPolicyValidated"] = True
            return result

        task = self._tasks.submit(
            task_type="export.alembic",
            title=f"Alembic export {source_node_path}",
            caller_id=context.caller_id,
            permissions=context.permissions,
            metadata={
                "sourceNodePath": source_node_path,
                "outputPath": str(output_path),
                "frames": frames,
                "rootPath": root_path,
            },
            runner=runner,
        )
        data = {
            "task": task,
            "taskResourceUri": f"houdini://tasks/{task['taskId']}",
            "taskLogResourceUri": f"houdini://tasks/{task['taskId']}/log",
        }
        return self._tool_response(
            f"Started Alembic export task {task['taskId']} for {source_node_path}.",
            data,
        )

    def _export_usd_impl(
        self,
        lop_node_path: str,
        output_path: str,
        frames: list[float],
    ) -> dict[str, Any]:
        export_node = self._create_temp_export_node("usd", "hp_export_usd")
        try:
            loppath = export_node.parm("loppath")
            lopoutput = export_node.parm("lopoutput")
            if loppath is None or lopoutput is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "USD export node does not expose the expected parameters.",
                    {"nodePath": export_node.path()},
                )
            self._require_node_by_path(lop_node_path, label="node_path")
            loppath.set(lop_node_path)
            lopoutput.set(output_path)
            self._configure_frame_range(export_node, frames)
            export_node.render(frame_range=(frames[0], frames[-1], frames[1] - frames[0] if len(frames) > 1 else 1.0))
            return {
                "exportNodePath": export_node.path(),
                "sourceNodePath": lop_node_path,
                "outputPaths": [output_path],
                "existingOutputPaths": self._existing_output_paths([output_path]),
                "messages": self._safe_method_value(export_node, "messages", []),
                "errors": self._safe_method_value(export_node, "errors", []),
                "warnings": self._safe_method_value(export_node, "warnings", []),
            }
        finally:
            self._safe_value(export_node.destroy)

    def export_usd(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        hou_module = self._require_hou()
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        frames = self._frame_sequence(arguments.get("frame_range"), default_frame=hou_module.frame())
        output_path = self._normalize_export_path(
            arguments.get("path"),
            stem="usd_export",
            suffix=".usd",
        )
        recovery_note = (
            "USD export cancellation is cooperative. Once the underlying USD ROP render call starts, "
            "Houdini may finish the active export call before cancellation is observed."
        )

        def runner(controller: Any) -> dict[str, Any]:
            controller.add_recovery_note(recovery_note)
            controller.set_outcome(
                {
                    "exportType": "usd",
                    "expectedOutputPaths": [str(output_path)],
                    "existingOutputPaths": [],
                    "partialOutputsPossible": True,
                    "cancellationSemantics": "cooperative_single_export_call",
                    "completedFrames": [],
                    "remainingFrames": frames,
                }
            )
            controller.log(f"Exporting USD from {node_path} to {output_path}.")
            controller.set_progress(10.0, "Running USD export")
            result = controller.run_live(
                lambda: self._export_usd_impl(node_path, str(output_path), frames),
                operation_label="export-usd",
                timeout_seconds=max(context.timeout_seconds, 3600.0),
            )
            existing_outputs = result.get("existingOutputPaths", [])
            controller.update_outcome(
                {
                    "existingOutputPaths": existing_outputs,
                    "completedFrames": frames,
                    "remainingFrames": [],
                    "partialOutputsPossible": False,
                }
            )
            controller.set_progress(100.0, "USD export completed")
            result["frames"] = frames
            result["outputPolicyValidated"] = True
            return result

        task = self._tasks.submit(
            task_type="export.usd",
            title=f"USD export {node_path}",
            caller_id=context.caller_id,
            permissions=context.permissions,
            metadata={
                "sourceNodePath": node_path,
                "outputPath": str(output_path),
                "frames": frames,
            },
            runner=runner,
        )
        data = {
            "task": task,
            "taskResourceUri": f"houdini://tasks/{task['taskId']}",
            "taskLogResourceUri": f"houdini://tasks/{task['taskId']}/log",
        }
        return self._tool_response(
            f"Started USD export task {task['taskId']} for {node_path}.",
            data,
        )
