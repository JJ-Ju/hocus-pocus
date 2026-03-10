"""Dependency discovery, repathing, and cache topology operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class DependencyOperationsMixin:
    _OUTPUT_PARM_NAMES = {
        "sopoutput",
        "picture",
        "vm_picture",
        "copoutput",
        "lopoutput",
        "output",
        "filename",
    }

    _CACHE_NODE_TYPES = {
        "filecache",
        "filecache::2.0",
        "rop_geometry",
        "rop_alembic",
        "usd",
        "file",
        "dopio",
    }

    def _dependency_kind(self, parm: Any) -> tuple[str, str]:
        node = parm.node()
        node_type = self._safe_value(lambda: node.type().name().lower(), "") or ""
        category = self._safe_value(lambda: node.type().category().name().lower(), "") or ""
        parm_name = parm.name().lower()

        if parm_name in self._OUTPUT_PARM_NAMES or category == "driver":
            return ("render_output" if category == "driver" else "output_path", "output")
        if "cache" in node_type or node_type in self._CACHE_NODE_TYPES:
            return ("cache_path", "output" if parm_name in self._OUTPUT_PARM_NAMES else "input")
        if category == "lop":
            return ("usd_reference", "input")
        return ("file_reference", "input")

    def _dependency_entry(self, parm: Any, value: Any) -> dict[str, Any]:
        hou_module = self._require_hou()
        node = parm.node()
        raw = str(
            self._safe_value(parm.unexpandedString, None)
            or self._safe_value(parm.evalAsString, None)
            or value
            or ""
        ).strip()
        expanded = str(
            self._safe_value(lambda: hou_module.expandString(raw), raw) if raw else ""
        ).strip()
        kind, direction = self._dependency_kind(parm)
        path_candidate = expanded or raw
        exists = False
        is_absolute = False
        normalized_path: str | None = None
        policy_error: dict[str, Any] | None = None
        approved = True

        if path_candidate and not path_candidate.startswith("opdef:"):
            candidate_path = Path(path_candidate).expanduser()
            is_absolute = candidate_path.is_absolute()
            if is_absolute:
                normalized_path = str(candidate_path.resolve(strict=False))
            else:
                normalized_path = str(candidate_path)
            exists = candidate_path.exists()
            try:
                ensure_path_allowed(path_candidate, self._settings)
            except JsonRpcError as exc:
                approved = False
                policy_error = exc.to_payload()

        return {
            "nodePath": node.path(),
            "nodeTypeName": self._safe_value(lambda: node.type().name(), None),
            "nodeCategory": self._safe_value(lambda: node.type().category().name(), None),
            "parmPath": parm.path(),
            "parmName": parm.name(),
            "label": self._safe_value(lambda: parm.parmTemplate().label(), parm.name()),
            "kind": kind,
            "direction": direction,
            "rawValue": raw,
            "expandedPath": expanded,
            "normalizedPath": normalized_path,
            "exists": exists,
            "approved": approved,
            "policyError": policy_error,
            "isAbsolutePath": is_absolute,
        }

    def _dependency_entries(
        self,
        *,
        root_path: str | None = None,
        node_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        hou_module = self._require_hou()
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for parm, value in hou_module.fileReferences():
            if parm is None:
                continue
            node = self._safe_value(parm.node, None)
            if node is None:
                continue
            node_path = node.path()
            if root_path and not (node_path == root_path or node_path.startswith(f"{root_path}/")):
                continue
            if node_paths is not None and node_path not in node_paths:
                continue
            key = (parm.path(), str(value))
            if key in seen:
                continue
            seen.add(key)
            entries.append(self._dependency_entry(parm, value))
        return entries

    def _dependency_scan_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip() or None
        entries = self._dependency_entries(root_path=root_path)
        summary = {
            "count": len(entries),
            "missingCount": sum(1 for entry in entries if not entry["exists"] and entry["direction"] == "input"),
            "policyIssueCount": sum(1 for entry in entries if not entry["approved"]),
            "outputCount": sum(1 for entry in entries if entry["direction"] == "output"),
            "cacheCount": sum(1 for entry in entries if entry["kind"] == "cache_path"),
        }
        return {
            "rootPath": root_path,
            "summary": summary,
            "dependencies": entries,
        }

    def dependency_scan_scene(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._dependency_scan_impl(arguments), context)
        return self._tool_response(
            f"Scanned {data['summary']['count']} dependency reference(s).",
            data,
        )

    def _dependency_repath_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        old_path = str(arguments.get("old_path", "")).strip()
        new_path = str(arguments.get("new_path", "")).strip()
        if not old_path or not new_path:
            raise JsonRpcError(INVALID_PARAMS, "old_path and new_path are required")
        match_mode = str(arguments.get("match_mode", "exact")).strip().lower() or "exact"
        if match_mode not in {"exact", "prefix"}:
            raise JsonRpcError(INVALID_PARAMS, "match_mode must be 'exact' or 'prefix'")
        root_path = str(arguments.get("root_path", "")).strip() or None
        dry_run = bool(arguments.get("dry_run", False))

        changed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        def is_match(value: str) -> bool:
            if match_mode == "exact":
                return value == old_path
            return value.startswith(old_path)

        def replace_value(value: str) -> str:
            if match_mode == "exact":
                return new_path
            return new_path + value[len(old_path) :]

        for entry in self._dependency_entries(root_path=root_path):
            raw = str(entry["rawValue"] or "")
            expanded = str(entry["expandedPath"] or "")
            if not raw and not expanded:
                continue
            replacement: str | None = None
            if is_match(raw):
                replacement = replace_value(raw)
            elif expanded and is_match(expanded):
                replacement = replace_value(expanded)
            if replacement is None:
                skipped.append({"parmPath": entry["parmPath"], "reason": "no_match"})
                continue

            parm = self._require_parm_by_path(entry["parmPath"])
            try:
                ensure_path_allowed(replacement, self._settings)
            except JsonRpcError as exc:
                failed.append(
                    {
                        "parmPath": entry["parmPath"],
                        "oldValue": raw,
                        "newValue": replacement,
                        "error": exc.to_payload(),
                    }
                )
                continue

            if dry_run:
                changed.append(
                    {
                        "parmPath": entry["parmPath"],
                        "oldValue": raw,
                        "newValue": replacement,
                        "applied": False,
                    }
                )
                continue

            try:
                parm.set(replacement)
                changed.append(
                    {
                        "parmPath": entry["parmPath"],
                        "oldValue": raw,
                        "newValue": replacement,
                        "applied": True,
                    }
                )
            except hou_module.PermissionError as exc:
                failed.append(
                    {
                        "parmPath": entry["parmPath"],
                        "oldValue": raw,
                        "newValue": replacement,
                        "error": str(exc),
                    }
                )

        return {
            "rootPath": root_path,
            "matchMode": match_mode,
            "dryRun": dry_run,
            "countChanged": len(changed),
            "countFailed": len(failed),
            "countSkipped": len(skipped),
            "changed": changed,
            "failed": failed,
            "skipped": skipped,
        }

    def dependency_repath(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._dependency_repath_impl(arguments), context)
        verb = "Planned" if data["dryRun"] else "Applied"
        return self._tool_response(
            f"{verb} {data['countChanged']} dependency repath change(s).",
            data,
        )

    def _cache_topology_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip() or None
        hou_module = self._require_hou()
        entries: list[dict[str, Any]] = []
        for root_candidate in ("/obj", "/out", "/stage"):
            root = hou_module.node(root_candidate)
            if root is None:
                continue
            for node in root.allSubChildren():
                node_path = node.path()
                if root_path and not (node_path == root_path or node_path.startswith(f"{root_path}/")):
                    continue
                node_type_name = self._safe_value(lambda: node.type().name().lower(), "") or ""
                if node_type_name not in self._CACHE_NODE_TYPES and "cache" not in node_type_name:
                    continue
                file_paths = self._node_file_parm_paths(node)
                entries.append(
                    {
                        "node": self._node_summary(node, include_parms=False),
                        "cacheMode": (
                            "read"
                            if bool(self._safe_value(lambda: node.parm("loadfromdisk").eval(), False))
                            else "write"
                        ),
                        "filePaths": file_paths,
                        "existingFilePaths": self._existing_output_paths(file_paths),
                        "usesSimulationCache": "dop" in node_type_name or "filecache" in node_type_name,
                    }
                )
        return {
            "rootPath": root_path,
            "count": len(entries),
            "caches": entries,
        }

    def cache_get_topology(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._cache_topology_impl(arguments), context)
        return self._tool_response(f"Found {data['count']} cache node(s).", data)

    def read_scene_dependencies(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://dependencies/scene",
            self._call_live(lambda: self._dependency_scan_impl({}), context),
        )

    def read_cache_topology(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://caches/topology",
            self._call_live(lambda: self._cache_topology_impl({}), context),
        )
