"""Parameter operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class ParmOperationsMixin:
    def _parm_list_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        node = self._require_node_by_path(node_path, label="node_path")
        name_prefix = str(arguments.get("name_prefix", "")).strip().lower()
        name_contains = str(arguments.get("name_contains", "")).strip().lower()
        limit = int(arguments.get("limit", 250))
        offset = int(arguments.get("offset", 0))
        if limit <= 0:
            raise JsonRpcError(INVALID_PARAMS, "limit must be greater than 0")
        if offset < 0:
            raise JsonRpcError(INVALID_PARAMS, "offset must be greater than or equal to 0")

        filtered = []
        for parm in node.parms():
            parm_name = self._safe_value(parm.name, "") or ""
            parm_label = self._safe_value(lambda: parm.parmTemplate().label(), "") or ""
            haystacks = (parm_name.lower(), parm_label.lower())
            if name_prefix and not any(item.startswith(name_prefix) for item in haystacks):
                continue
            if name_contains and not any(name_contains in item for item in haystacks):
                continue
            filtered.append(parm)

        total_count = len(filtered)
        window = filtered[offset: offset + limit]
        parms = [self._parm_summary(parm) for parm in window]
        return {
            "nodePath": node.path(),
            "count": len(parms),
            "totalCount": total_count,
            "offset": offset,
            "limit": limit,
            "hasMore": (offset + len(parms)) < total_count,
            "filters": {
                "namePrefix": name_prefix or None,
                "nameContains": name_contains or None,
            },
            "parms": parms,
        }

    def parm_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_list_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} parameters.", data)

    def _parm_get_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        return self._parm_summary(parm)

    def parm_get(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_get_impl(arguments), context)
        return self._tool_response(f"Returned parameter {data['path']}.", data)

    def _parm_set_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = arguments.get("parm_path")
        if not parm_path:
            raise JsonRpcError(INVALID_PARAMS, "parm_path is required")
        parm = self._require_parm_by_path(str(parm_path))
        value = arguments.get("value")
        with hou_module.undos.group(f"HocusPocus: set {parm_path}"):
            parm.set(value)
        return self._parm_summary(parm)

    def parm_set(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_set_impl(arguments), context)
        return self._tool_response(f"Set parameter {data['path']}.", data)

    def _parm_set_expression_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        expression = str(arguments.get("expression", "")).strip()
        language_name = str(arguments.get("language", "hscript")).strip().lower()
        if not parm_path or not expression:
            raise JsonRpcError(INVALID_PARAMS, "parm_path and expression are required")
        parm = self._require_parm_by_path(parm_path)
        language = (
            hou_module.exprLanguage.Python
            if language_name == "python"
            else hou_module.exprLanguage.Hscript
        )
        with hou_module.undos.group(f"HocusPocus: set expression {parm_path}"):
            parm.setExpression(expression, language=language)
        return self._parm_summary(parm)

    def parm_set_expression(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_set_expression_impl(arguments), context)
        return self._tool_response(f"Set expression on {data['path']}.", data)

    def _parm_press_button_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        with hou_module.undos.group(f"HocusPocus: press {parm_path}"):
            parm.pressButton()
        return self._parm_summary(parm)

    def parm_press_button(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_press_button_impl(arguments), context)
        return self._tool_response(f"Pressed button parameter {data['path']}.", data)

    def _parm_revert_to_default_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        parm_path = str(arguments.get("parm_path", "")).strip()
        parm = self._require_parm_by_path(parm_path)
        with hou_module.undos.group(f"HocusPocus: revert {parm_path}"):
            parm.revertToDefaults()
        return self._parm_summary(parm)

    def parm_revert_to_default(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        data = self._call_live(lambda: self._parm_revert_to_default_impl(arguments), context)
        return self._tool_response(f"Reverted parameter {data['path']} to default.", data)
