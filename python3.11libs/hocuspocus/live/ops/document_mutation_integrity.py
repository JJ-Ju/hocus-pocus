"""Fail-closed preflight and rollback helpers for document mutations."""

from __future__ import annotations

import copy
import time
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..houdini_undo import perform_stack_action
from .document_network_families import network_family_policy
from .document_typed_apply import execute_typed_updates


def _call(value: Any, name: str, default: Any = None) -> Any:
    method = getattr(value, name, None)
    if not callable(method):
        return default
    try:
        return method()
    except Exception:
        return default


def _template_kind(template: Any) -> str:
    template_type = _call(template, "type")
    name = _call(template_type, "name")
    if name:
        return str(name).strip().lower()
    return type(template).__name__.removesuffix("ParmTemplate").lower()


def _category_for_family(hou_module: Any, family: str) -> Any:
    getter_name = {
        "sop": "sopNodeTypeCategory",
        "mat": "vopNodeTypeCategory",
        "lop": "lopNodeTypeCategory",
        "top": "topNodeTypeCategory",
        "object": "objNodeTypeCategory",
        "rop": "ropNodeTypeCategory",
    }.get(str(family or "").lower())
    return _call(hou_module, getter_name) if getter_name else None


class DocumentMutationIntegrityMixin:
    def _document_prepare_direct_apply(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        target: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        prepared, prepared_target = self._document_preflight_apply_plan(
            plan, baseline, target
        )
        if prepared_target is None:
            raise JsonRpcError(
                INVALID_PARAMS, "Document apply target preparation failed."
            )
        inverse = self._document_prepare_direct_inverse(
            prepared, prepared_target, baseline
        )
        return prepared, prepared_target, inverse

    def _document_prepare_hash_bound_apply(
        self,
        validated: dict[str, Any],
        stored: dict[str, Any],
        inverse: dict[str, Any],
        current: dict[str, Any],
        target: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prepared_validated, _ = self._document_preflight_apply_plan(
            validated, current
        )
        prepared_execution, _ = self._document_preflight_apply_plan(
            stored, current
        )
        if self._hocus_canonical_digest(
            prepared_validated
        ) != self._hocus_canonical_digest(prepared_execution):
            self._hocus_fail(
                "HOCUS754", "Prepared parameter execution changed after planning."
            )
        prepared_inverse, _ = self._document_preflight_apply_plan(
            inverse, current
        )
        return prepared_execution, prepared_inverse

    def _document_execute_bindings(
        self, plan: dict[str, Any], state: dict[str, Any],
        executed: list[dict[str, Any]], checkpoint: Any,
    ) -> None:
        for reset in plan.get("parameterResets", []):
            checkpoint()
            path = self._document_binding_parm_path(state, reset)
            self._parm_revert_to_permanent_default_impl({"parm_path": path})
            parm = self._require_parm_by_path(path)
            is_default = getattr(parm, "isAtDefault", None)
            verified_default = callable(is_default) and bool(self._safe_value(
                lambda: is_default(
                    compare_temporary_defaults=False,
                    compare_expressions=True,
                ),
                False,
            ))
            if not verified_default:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Managed parameter reset could not be verified at {path}.",
                )
            executed.append({
                "type": "revert_parm", "bindingUid": reset.get("bindingUid"),
                "parmPath": path, "verifiedDefault": True,
            })
        for update in plan.get("parameterAssignments", []):
            checkpoint()
            self._document_execute_assignment(update, state, executed)
        execute_typed_updates(
            self, plan.get("typedValueUpdates", []), state, executed, checkpoint,
        )
        for update in plan.get("expressionUpdates", []):
            checkpoint()
            path = self._document_binding_parm_path(state, update)
            self._parm_set_expression_impl({
                "parm_path": path,
                "expression": update["expression"],
                "language": update.get("expressionLanguage", "hscript"),
            })
            executed.append({
                "type": "set_expression", "bindingUid": update.get("bindingUid"),
                "parmPath": path,
            })
        for update in plan.get("codeBlobInstalls", []):
            checkpoint()
            path = self._document_binding_parm_path(state, update)
            self._parm_set_impl({"parm_path": path, "value": update.get("body")})
            executed.append({
                "type": "install_code_blob",
                "bindingUid": update.get("bindingUid"),
                "codeBlobUid": update.get("codeBlobUid"),
                "parmPath": path,
                "language": update.get("language"),
                "adapter": update.get("adapter"),
            })

    def _document_execute_assignment(
        self,
        update: dict[str, Any],
        state: dict[str, Any],
        executed: list[dict[str, Any]],
    ) -> None:
        path = self._document_binding_parm_path(state, update)
        try:
            self._require_parm_by_path(path).set(update.get("value"))
        except Exception as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Could not assign document parameter {path}.",
                {
                    "diagnosticCode": "document.parameter_assignment_failed",
                    "bindingUid": update.get("bindingUid"),
                    "parmPath": path,
                    "expectedType": (update.get("metadata") or {}).get(
                        "templateType"
                    ),
                    "receivedValue": update.get("value"),
                    "errorType": exc.__class__.__name__,
                },
            ) from exc
        executed.append({
            "type": "set_parm", "bindingUid": update.get("bindingUid"),
            "parmPath": path,
        })

    @staticmethod
    def _document_plan_output(
        baseline: dict[str, Any],
        target: dict[str, Any],
        context: dict[str, Any],
        network_family: str,
    ) -> tuple[dict[str, Any] | None, None]:
        """Treat SOP node display flags as authority; output edges are observations."""
        del baseline, target
        if network_family_policy(network_family).output_strategy != "sop_display":
            return None, None
        display_uids = sorted(
            uid
            for uid, node in context["after"].items()
            if uid != context["rootUid"]
            and bool((node.get("flags") or {}).get("display", False))
        )
        return {
            "sourceUid": display_uids[0] if len(display_uids) == 1 else None,
            "targetDisplayUids": display_uids,
            "authority": "node_flags",
        }, None

    @staticmethod
    def _document_preflight_error(
        entry: dict[str, Any],
        parm_path: str,
        expected_type: str,
        received: Any,
        message: str,
    ) -> JsonRpcError:
        return JsonRpcError(
            INVALID_PARAMS,
            message,
            {
                "diagnosticCode": "document.parameter_preflight_failed",
                "bindingUid": entry.get("bindingUid"),
                "parmPath": parm_path,
                "expectedType": expected_type,
                "receivedValue": received,
                "receivedType": type(received).__name__,
            },
        )

    @staticmethod
    def _document_planned_node(
        plan: dict[str, Any], node_uid: str,
    ) -> dict[str, Any] | None:
        for replacement in plan.get("replaceNodes", []):
            if not isinstance(replacement, dict):
                continue
            target = replacement.get("target")
            if isinstance(target, dict) and str(target.get("uid", "")) == node_uid:
                return target
        return next((
            node
            for field in ("createNetworkContainers", "createNodes")
            for node in plan.get(field, [])
            if isinstance(node, dict) and str(node.get("uid", "")) == node_uid
        ), None)

    def _document_created_template(
        self,
        plan: dict[str, Any],
        entry: dict[str, Any],
    ) -> Any:
        created = self._document_planned_node(
            plan, str(entry.get("nodeUid", ""))
        )
        if created is None:
            return None
        hou_module = self._require_hou()
        category = _category_for_family(hou_module, str(plan.get("networkFamily", "")))
        type_name = str(created.get("typeName", "")).strip()
        node_type = None
        preferred = getattr(hou_module, "preferredNodeType", None)
        category_name = str(_call(category, "name", "") or "").strip()
        parent = None
        node_resolver = getattr(hou_module, "node", None)
        if callable(node_resolver):
            try:
                parent = node_resolver(str(created.get("parentPath", "")))
            except Exception:
                parent = None
        if category_name and callable(preferred):
            try:
                node_type = preferred(f"{category_name}/{type_name}", parent)
            except Exception:
                node_type = None
        resolver = getattr(hou_module, "nodeType", None)
        if node_type is None and category is not None and callable(resolver):
            try:
                node_type = resolver(category, type_name)
            except Exception:
                node_type = None
        if node_type is None and category is not None:
            node_type = (_call(category, "nodeTypes", {}) or {}).get(type_name)
        group = _call(node_type, "parmTemplateGroup") if node_type is not None else None
        finder = getattr(group, "find", None)
        try:
            return finder(str(entry.get("parmName", ""))) if callable(finder) else None
        except Exception:
            return None

    def _document_live_parm_template(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        entry: dict[str, Any],
    ) -> tuple[str, Any, Any | None]:
        state = self._document_apply_state(baseline)
        parm_path = self._document_binding_parm_path(state, entry)
        hou_module = self._require_hou()
        node_path, _, parm_name = parm_path.rpartition("/")
        planned_template = self._document_created_template(plan, entry)
        if planned_template is not None:
            return parm_path, planned_template, None
        node = None
        resolver = getattr(hou_module, "node", None)
        if callable(resolver):
            try:
                node = resolver(node_path)
            except Exception:
                node = None
        parm = None
        if node is not None:
            parm_getter = getattr(node, "parm", None)
            try:
                parm = parm_getter(parm_name) if callable(parm_getter) else None
            except Exception:
                parm = None
        template = _call(parm, "parmTemplate") if parm is not None else None
        if template is None:
            raise self._document_preflight_error(
                entry, parm_path, "existing assignable Houdini parameter",
                entry.get("value"), "Document apply could not resolve the live parameter template before mutation.",
            )
        return parm_path, template, parm

    def _document_coerce_assignment(
        self,
        entry: dict[str, Any],
        parm_path: str,
        template: Any,
    ) -> Any:
        value = entry.get("value")
        kind = _template_kind(template)
        menu_items = tuple(str(item) for item in (_call(template, "menuItems", ()) or ()))
        if menu_items:
            matches = (
                [index for index, token in enumerate(menu_items) if token == value]
                if isinstance(value, str) else []
            )
            if len(matches) == 1:
                return value if kind == "string" else matches[0]
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(menu_items):
                return value
            raise self._document_preflight_error(
                entry, parm_path, f"unambiguous menu token ({kind})", value,
                "Document parameter menu token is absent or ambiguous.",
            )
        if kind == "float":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif kind in {"int", "toggle"}:
            valid = isinstance(value, (int, bool))
        elif kind == "string":
            valid = isinstance(value, str)
        else:
            valid = (
                kind not in {"button", "folder", "label", "separator"}
                and isinstance(value, (str, int, float, bool))
            )
        if valid:
            if kind == "int":
                return int(value)
            if kind == "toggle":
                return bool(value)
            return value
        raise self._document_preflight_error(
            entry, parm_path, kind or "assignable scalar", value,
            "Document parameter value is incompatible with the live Houdini parameter template.",
        )

    def _document_preflight_apply_plan(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        target: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Resolve and type-check every scalar parameter target before mutation."""
        prepared = copy.deepcopy(plan)
        prepared_target = copy.deepcopy(target) if target is not None else None
        for field in (
            "parameterResets", "parameterAssignments", "expressionUpdates",
            "codeBlobInstalls", "typedValueUpdates",
        ):
            for entry in prepared.get(field, []):
                parm_path, template, parm = self._document_live_parm_template(
                    prepared, baseline, entry
                )
                if field == "parameterAssignments":
                    entry["value"] = self._document_coerce_assignment(
                        entry, parm_path, template
                    )
                    self._document_refresh_literal_target(
                        prepared_target, entry, entry["value"]
                    )
                else:
                    self._document_preflight_non_literal(
                        field, entry, parm_path, template, parm
                    )
        return prepared, prepared_target

    def _document_preflight_non_literal(
        self,
        field: str,
        entry: dict[str, Any],
        parm_path: str,
        template: Any,
        parm: Any | None,
    ) -> None:
        kind = _template_kind(template)
        forbidden = {"button", "label", "separator"}
        valid = kind not in forbidden
        expected = f"assignable {kind or 'parameter'}"
        received = entry.get("expression", entry.get("body"))
        if field == "codeBlobInstalls":
            valid, expected, received = kind == "string", "string code parameter", entry.get("body")
        elif field == "typedValueUpdates":
            mode = entry.get("valueMode")
            if mode == "ramp":
                valid, expected = kind == "ramp", "ramp parameter"
            elif mode == "multiparm":
                required = (
                    "eval", "multiParmStartOffset", "insertMultiParmInstance",
                    "removeMultiParmInstance",
                )
                valid = kind == "folder" and (
                    parm is None or all(callable(getattr(parm, name, None)) for name in required)
                )
                expected = "multiparm block parameter"
            else:
                valid, expected = False, "ramp or multiparm parameter"
            received = entry.get("typedBinding")
        if valid:
            return
        raise self._document_preflight_error(
            entry, parm_path, expected, received,
            "Document apply cannot author this Houdini parameter template.",
        )

    @staticmethod
    def _document_refresh_literal_target(
        target: dict[str, Any] | None,
        entry: dict[str, Any],
        value: Any,
    ) -> None:
        if target is None:
            return
        for binding in target.get("parameterBindings", []):
            if not isinstance(binding, dict):
                continue
            if binding.get("uid") != entry.get("bindingUid"):
                continue
            if binding.get("valueMode") == "literal":
                binding["value"] = value
            return

    def _document_rollback_direct_apply(
        self,
        *,
        root_path: str,
        baseline: dict[str, Any],
        undo_label: str,
        inverse_plan: dict[str, Any],
        forward_target: dict[str, Any],
    ) -> tuple[
        bool, str | None, dict[str, Any] | None,
        dict[str, Any] | None, list[dict[str, Any]],
    ]:
        verification = restored = None
        errors: list[str] = []
        inverse_executed: list[dict[str, Any]] = []
        try:
            perform_stack_action(
                self._require_hou(), "undo", expected_label=undo_label
            )
            self._monitor.mark_dirty(
                "tool:document.apply.rollback", scope_path=root_path
            )
            restored = self._document_current_network_payload(root_path, force_sync=True)
            verification = self._document_verification_diff_payload(baseline, restored)
            if self._document_diff_is_clean(verification):
                return True, None, verification, restored, inverse_executed
        except Exception as exc:
            errors.append(f"guarded undo: {exc.__class__.__name__}: {exc}")
        try:
            hou_module = self._require_hou()
            with hou_module.undos.group(f"{undo_label} inverse restoration"):
                self._document_execute_apply_plan(
                    inverse_plan, forward_target, executed=inverse_executed
                )
            self._monitor.mark_dirty(
                "tool:document.apply.inverse_rollback", scope_path=root_path
            )
            restored = self._document_current_network_payload(root_path, force_sync=True)
            verification = self._document_verification_diff_payload(baseline, restored)
            if self._document_diff_is_clean(verification):
                return True, "; ".join(errors) or None, verification, restored, inverse_executed
            errors.append("inverse restoration verification did not match the baseline")
        except Exception as exc:
            errors.append(f"inverse restoration: {exc.__class__.__name__}: {exc}")
        return False, "; ".join(errors), verification, restored, inverse_executed

    def _document_prepare_direct_inverse(
        self,
        plan: dict[str, Any],
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        inverse = self._document_build_apply_plan(target, baseline, mode="merge")
        created = [
            {
                "uid": node.get("uid"),
                "currentPath": node.get("path"),
            }
            for field in ("createNetworkContainers", "createNodes")
            for node in plan.get(field, [])
            if isinstance(node, dict)
        ]
        created_paths = self._document_prune_descendant_paths(
            [str(item.get("currentPath", "")) for item in created]
        )
        inverse["deleteNodes"] = [
            next(item for item in created if item.get("currentPath") == path)
            for path in created_paths
        ]
        inverse["summary"]["deleteNodeCount"] = len(inverse["deleteNodes"])
        prepared, _ = self._document_preflight_apply_plan(
            inverse, baseline
        )
        return prepared

    def _document_quarantine_direct_apply(
        self,
        root_path: str,
        apply_commit_id: str,
        reason: str,
    ) -> None:
        quarantine_map = getattr(self, "_hocus_quarantine_map", None)
        if callable(quarantine_map):
            quarantine_map()[root_path] = {
                "applyCommitId": apply_commit_id,
                "reason": reason,
                "createdAt": time.time(),
                "source": "document.apply",
            }

    def _document_raise_apply_failure(
        self,
        *,
        failure: dict[str, Any],
        rolled_back: bool,
    ) -> None:
        code = "HOCUS755" if rolled_back else "HOCUS756"
        message = (
            "Document apply failed and rollback was verified."
            if rolled_back
            else "Document apply failed and the network is in partial or unknown state."
        )
        fail = getattr(self, "_hocus_fail", None)
        if callable(fail):
            fail(code, message, family="runtime", retryable=False, failure=failure)
        raise JsonRpcError(
            INVALID_PARAMS, message,
            {"diagnosticCode": code, "failure": copy.deepcopy(failure)},
        )
