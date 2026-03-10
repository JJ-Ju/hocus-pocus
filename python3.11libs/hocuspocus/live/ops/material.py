"""Material creation, update, and assignment operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class MaterialOperationsMixin:
    def _material_create_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parent_path = str(arguments.get("parent_path", "/mat")).strip() or "/mat"
        node_name = str(arguments.get("node_name", "")).strip() or None
        requested_type = str(arguments.get("material_type_name", "")).strip()
        parent = self._require_node_by_path(parent_path, label="parent_path")

        candidates = [requested_type] if requested_type else []
        candidates.extend(["principledshader::2.0", "principledshader"])
        node = None
        created_type = None
        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                node = parent.createNode(candidate, node_name=node_name)
                created_type = candidate
                break
            except Exception as exc:
                last_error = exc
                continue
        if node is None or created_type is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Could not create a material node with the requested or fallback node types.",
                {
                    "parentPath": parent_path,
                    "requestedType": requested_type or None,
                    "attemptedTypes": candidates,
                    "error": str(last_error) if last_error else None,
                },
            )

        changes = self._material_apply_properties(node, arguments)
        try:
            self._place_node_on_grid(parent, node)
        except Exception:
            self._logger.debug("failed to place material node on grid", exc_info=True)
        data = self._material_summary(node)
        data.update(changes)
        data["materialTypeName"] = created_type
        return data

    def material_create(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._material_create_impl(arguments), context)
        return self._tool_response(f"Created material {data['path']}.", data)

    def _material_update_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        material_path = str(arguments.get("material_path", "")).strip()
        if not material_path:
            raise JsonRpcError(INVALID_PARAMS, "material_path is required")
        node = self._require_node_by_path(material_path, label="material_path")
        changes = self._material_apply_properties(node, arguments)
        data = self._material_summary(node)
        data.update(changes)
        return data

    def material_update(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._material_update_impl(arguments), context)
        return self._tool_response(f"Updated material {data['path']}.", data)

    def _material_assign_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        target_path = str(arguments.get("target_node_path", "")).strip()
        material_path = str(arguments.get("material_path", "")).strip()
        if not target_path:
            raise JsonRpcError(INVALID_PARAMS, "target_node_path is required")
        if not material_path:
            raise JsonRpcError(INVALID_PARAMS, "material_path is required")

        target = self._require_node_by_path(target_path, label="target_node_path")
        material_node = self._require_node_by_path(material_path, label="material_path")
        owner = self._material_owner_for_node(target)
        if owner is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Could not find a material assignment owner with a shop_materialpath parameter.",
                {"targetNodePath": target_path},
            )

        parm = owner.parm("shop_materialpath")
        if parm is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Resolved material owner does not expose a shop_materialpath parameter.",
                {"assignmentNodePath": owner.path()},
            )

        with hou_module.undos.group(f"HocusPocus: assign material {material_path}"):
            parm.set(material_node.path())

        data = {
            "targetNodePath": target.path(),
            "assignmentNodePath": owner.path(),
            "materialPath": material_node.path(),
            "assignmentMode": "object_material_parm",
            "material": self._material_summary(material_node),
            "assignmentNode": self._node_summary(owner, include_parms=False),
        }
        try:
            data["geometrySummary"] = self._geometry_summary_for_node(target)
        except JsonRpcError:
            data["geometrySummary"] = None
        return data

    def material_assign(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._material_assign_impl(arguments), context)
        return self._tool_response(
            f"Assigned material {data['materialPath']} to {data['assignmentNodePath']}.",
            data,
        )
