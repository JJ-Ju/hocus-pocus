"""Deeper Solaris/USD inspection and diagnostics."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class UsdStageOperationsMixin:
    def _require_usd_stage(self) -> Any:
        try:
            from pxr import Sdf, UsdShade  # type: ignore
        except ImportError as exc:
            raise JsonRpcError(INVALID_PARAMS, "USD Python modules are not available.") from exc
        return {"Sdf": Sdf, "UsdShade": UsdShade}

    def _require_lop_node(self, node_path: str) -> Any:
        node = self._require_node_by_path(node_path, label="node_path")
        if self._safe_value(lambda: node.type().category().name(), "") != "Lop":
            raise JsonRpcError(INVALID_PARAMS, f"Node is not a LOP node: {node_path}")
        return node

    def _stage_for_lop_node(self, node_path: str) -> Any:
        node = self._require_lop_node(node_path)
        stage = self._safe_value(node.stage, None)
        if stage is None:
            raise JsonRpcError(INVALID_PARAMS, f"LOP node has no USD stage: {node_path}")
        return stage

    def _sdf_layer_summary(self, layer: Any) -> dict[str, Any]:
        identifier = self._safe_value(lambda: layer.identifier, None)
        real_path = self._safe_value(lambda: layer.realPath, None)
        return {
            "identifier": str(identifier) if identifier is not None else None,
            "realPath": str(real_path) if real_path is not None else None,
            "anonymous": bool(self._safe_value(lambda: layer.anonymous, False)),
            "dirty": bool(self._safe_value(lambda: layer.dirty, False)),
            "empty": bool(self._safe_value(lambda: layer.empty, False)),
        }

    def _usd_stage_summary_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        stage = self._stage_for_lop_node(node_path)
        root_layer = stage.GetRootLayer()
        session_layer = stage.GetSessionLayer()
        used_layers = list(stage.GetUsedLayers())
        traversed = [prim for prim in stage.Traverse()]
        default_prim = stage.GetDefaultPrim()
        return {
            "nodePath": node_path,
            "defaultPrimPath": default_prim.GetPath().pathString if default_prim and default_prim.IsValid() else None,
            "primCount": len(traversed),
            "rootLayer": self._sdf_layer_summary(root_layer),
            "sessionLayer": self._sdf_layer_summary(session_layer) if session_layer is not None else None,
            "usedLayers": [self._sdf_layer_summary(layer) for layer in used_layers],
            "primPathsSample": [prim.GetPath().pathString for prim in traversed[:200]],
        }

    def usd_stage_summary(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_stage_summary_impl(arguments), context)
        return self._tool_response(f"Inspected USD stage for {data['nodePath']}.", data)

    def _usd_prim_summary(self, prim: Any) -> dict[str, Any]:
        usd = self._require_usd_stage()
        UsdShade = usd["UsdShade"]
        variant_sets = {}
        variant_set_names = self._safe_value(lambda: list(prim.GetVariantSets().GetNames()), []) or []
        for name in variant_set_names:
            variant_set = prim.GetVariantSets().GetVariantSet(name)
            variant_sets[str(name)] = {
                "selection": variant_set.GetVariantSelection(),
                "variants": list(variant_set.GetVariantNames()),
            }
        binding_api = UsdShade.MaterialBindingAPI(prim)
        bound_material = None
        if binding_api:
            material, rel = binding_api.ComputeBoundMaterial()
            if material and material.GetPrim().IsValid():
                bound_material = {
                    "materialPath": material.GetPath().pathString,
                    "relationshipPath": rel.GetPath().pathString if rel and rel.IsValid() else None,
                }
        references = []
        prim_stack = self._safe_value(prim.GetPrimStack, []) or []
        for spec in prim_stack:
            ref_list = self._safe_value(lambda spec=spec: spec.referenceList.prependedItems, []) or []
            for ref in ref_list:
                references.append(
                    {
                        "assetPath": str(self._safe_value(lambda ref=ref: ref.assetPath, "") or ""),
                        "primPath": str(self._safe_value(lambda ref=ref: ref.primPath, "") or ""),
                    }
                )
        return {
            "path": prim.GetPath().pathString,
            "name": prim.GetName(),
            "typeName": prim.GetTypeName(),
            "active": bool(prim.IsActive()),
            "loaded": bool(prim.IsLoaded()),
            "defined": bool(prim.IsDefined()),
            "specifier": str(prim.GetSpecifier()),
            "hasAuthoredReferences": bool(prim.HasAuthoredReferences()),
            "kind": self._safe_value(lambda: prim.GetMetadata("kind"), None),
            "variantSets": variant_sets,
            "references": references,
            "materialBinding": bound_material,
            "childPrimPaths": [child.GetPath().pathString for child in prim.GetChildren()],
        }

    def _usd_inspect_prim_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        prim_path = str(arguments.get("prim_path", "")).strip()
        if not node_path or not prim_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path and prim_path are required")
        stage = self._stage_for_lop_node(node_path)
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            raise JsonRpcError(INVALID_PARAMS, f"USD prim not found: {prim_path}")
        return {
            "nodePath": node_path,
            "prim": self._usd_prim_summary(prim),
        }

    def usd_inspect_prim(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_inspect_prim_impl(arguments), context)
        return self._tool_response(f"Inspected USD prim {data['prim']['path']}.", data)

    def _usd_material_bindings_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        root_prim_path = str(arguments.get("root_prim_path", "")).strip() or "/"
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        stage = self._stage_for_lop_node(node_path)
        normalized_root = root_prim_path.rstrip("/") or "/"
        if normalized_root != "/":
            root_prim = stage.GetPrimAtPath(normalized_root)
            if root_prim is None or not root_prim.IsValid():
                raise JsonRpcError(INVALID_PARAMS, f"Root prim not found: {root_prim_path}")
        bindings: list[dict[str, Any]] = []
        usd = self._require_usd_stage()
        UsdShade = usd["UsdShade"]
        for prim in stage.Traverse():
            prim_path = prim.GetPath().pathString
            if normalized_root != "/":
                if prim_path != normalized_root and not prim_path.startswith(f"{normalized_root}/"):
                    continue
            binding_api = UsdShade.MaterialBindingAPI(prim)
            if not binding_api:
                continue
            material, rel = binding_api.ComputeBoundMaterial()
            if material and material.GetPrim().IsValid():
                bindings.append(
                    {
                        "primPath": prim_path,
                        "materialPath": material.GetPath().pathString,
                        "relationshipPath": rel.GetPath().pathString if rel and rel.IsValid() else None,
                    }
                )
        return {
            "nodePath": node_path,
            "rootPrimPath": root_prim_path,
            "count": len(bindings),
            "bindings": bindings,
        }

    def usd_inspect_material_bindings(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_material_bindings_impl(arguments), context)
        return self._tool_response(f"Found {data['count']} USD material binding(s).", data)

    def _usd_validate_stage_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        stage = self._stage_for_lop_node(node_path)
        issues: list[dict[str, Any]] = []
        for prim in stage.Traverse():
            summary = self._usd_prim_summary(prim)
            for reference in summary["references"]:
                asset_path = str(reference.get("assetPath") or "").strip()
                if asset_path:
                    try:
                        resolved = self._require_hou().expandString(asset_path)
                        candidate = self._safe_value(lambda resolved=resolved: ensure_path_allowed(resolved, self._settings), None)
                        if candidate is not None and not candidate.exists():
                            issues.append(
                                {
                                    "severity": "warning",
                                    "kind": "usd_reference_missing_file",
                                    "primPath": summary["path"],
                                    "assetPath": resolved,
                                }
                            )
                    except Exception:
                        issues.append(
                            {
                                "severity": "warning",
                                "kind": "usd_reference_unresolved",
                                "primPath": summary["path"],
                                "assetPath": asset_path,
                            }
                        )
        # reuse existing configurelayer save-path validation from graph snapshot
        snapshot = self._graph_snapshot()
        for node in snapshot.get("nodes", []):
            if node.get("category") != "Lop":
                continue
            if node.get("typeName") != "configurelayer":
                continue
            parm = self._safe_value(lambda path=node["path"]: self._require_parm_by_path(f"{path}/savepath"), None)
            if parm is None:
                continue
            value = self._safe_value(parm.evalAsString, "") or ""
            if not value:
                continue
            try:
                ensure_path_allowed(value, self._settings)
            except JsonRpcError as exc:
                issues.append(
                    {
                        "severity": "error",
                        "kind": "usd_layer_savepath_policy",
                        "nodePath": node["path"],
                        "details": exc.to_payload(),
                    }
                )
        return {
            "nodePath": node_path,
            "issueCount": len(issues),
            "issues": issues,
        }

    def usd_validate_stage(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._usd_validate_stage_impl(arguments), context)
        return self._tool_response(f"Validated USD stage with {data['issueCount']} issue(s).", data)

    def read_usd_stage_summary(self, node_path: str, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            f"houdini://usd/stage{node_path}",
            self._call_live(lambda: self._usd_stage_summary_impl({"node_path": node_path}), context),
        )
