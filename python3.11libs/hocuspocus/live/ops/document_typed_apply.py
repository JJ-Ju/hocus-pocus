"""HOM execution helpers for closed network-document-v2 compound values."""

from __future__ import annotations

from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError


_RAMP_BASIS_NAMES = {
    "constant": "Constant",
    "linear": "Linear",
    "catmullrom": "CatmullRom",
    "monotonecubic": "MonotoneCubic",
    "bezier": "Bezier",
    "bspline": "BSpline",
    "hermite": "Hermite",
}


def execute_typed_updates(
    operations: Any,
    updates: list[dict[str, Any]],
    state: dict[str, Any],
    executed: list[dict[str, Any]],
    checkpoint: Callable[[], None],
) -> None:
    for update in updates:
        checkpoint()
        path = operations._document_binding_parm_path(state, update)
        binding = update.get("typedBinding")
        if not isinstance(binding, dict):
            raise JsonRpcError(
                INVALID_PARAMS, "Typed parameter update lacks its binding."
            )
        mode = update.get("valueMode")
        if mode == "ramp":
            _apply_ramp(operations, path, binding)
        elif mode == "multiparm":
            _apply_multiparm(operations, path, binding, state)
        else:
            raise JsonRpcError(
                INVALID_PARAMS, f"Unsupported typed parameter update: {mode}."
            )
        executed.append({
            "type": f"set_{mode}",
            "bindingUid": update.get("bindingUid"),
            "parmPath": path,
        })


def _apply_ramp(operations: Any, path: str, binding: dict[str, Any]) -> None:
    hou_module = operations._require_hou()
    ramp_basis = getattr(hou_module, "rampBasis", None)
    ramp_class = getattr(hou_module, "Ramp", None)
    if ramp_basis is None or not callable(ramp_class):
        raise JsonRpcError(
            INVALID_PARAMS, "This Houdini build lacks the required ramp HOM API."
        )
    try:
        bases = tuple(
            getattr(ramp_basis, _RAMP_BASIS_NAMES[item])
            for item in binding["basis"]
        )
        positions = tuple(float(item["position"]) for item in binding["points"])
        if binding["rampKind"] == "color":
            values = tuple(
                tuple(float(component) for component in item["value"])
                for item in binding["points"]
            )
        else:
            values = tuple(float(item["value"]) for item in binding["points"])
        ramp = ramp_class(bases, positions, values)
        parm = operations._require_parm_by_path(path)
        parm.set(ramp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise JsonRpcError(
            INVALID_PARAMS, "Ramp value could not be represented by HOM."
        ) from exc


def _apply_multiparm(
    operations: Any,
    path: str,
    binding: dict[str, Any],
    state: dict[str, Any],
) -> None:
    parm = operations._require_parm_by_path(path)
    evaluate = getattr(parm, "eval", None)
    start_offset = getattr(parm, "multiParmStartOffset", None)
    insert = getattr(parm, "insertMultiParmInstance", None)
    remove = getattr(parm, "removeMultiParmInstance", None)
    if not all(
        callable(item) for item in (evaluate, start_offset, insert, remove)
    ):
        raise JsonRpcError(
            INVALID_PARAMS,
            "This parameter lacks the required multiparm HOM API.",
        )
    try:
        current = evaluate()
        live_start = start_offset()
        expected_start = binding["instanceStart"]
        if (
            type(current) is not int
            or not 0 <= current <= 4096
            or type(live_start) is not int
            or not 0 <= live_start <= 4096
            or live_start != expected_start
        ):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Multiparm instance metadata conflicts with live HOM state.",
            )
        for index in range(current - 1, -1, -1):
            remove(index)
        instances = binding["instances"]
        for index in range(len(instances)):
            insert(index)
        contracts = {
            item["name"]: item for item in binding["fieldContract"]
        }
        node_path = path.rsplit("/", 1)[0]
        for ordinal, instance in enumerate(instances):
            instance_token = expected_start + ordinal
            for field in instance["fields"]:
                contract = contracts[field["name"]]
                token = contract["tokenTemplate"].replace(
                    "#", str(instance_token)
                )
                child_path = f"{node_path}/{token}"
                _set_nested_value(
                    operations, child_path, field["value"], state
                )
    except JsonRpcError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise JsonRpcError(
            INVALID_PARAMS, "Multiparm value could not be represented by HOM."
        ) from exc


def _set_nested_value(
    operations: Any,
    path: str,
    value: dict[str, Any],
    state: dict[str, Any],
) -> None:
    kind = value["kind"]
    if kind in {"literal", "array"}:
        operations._parm_set_impl({"parm_path": path, "value": value["value"]})
        return
    if kind == "raw_path":
        operations._parm_set_impl({"parm_path": path, "value": value["raw"]})
        return
    if kind == "expression":
        operations._parm_set_expression_impl({
            "parm_path": path,
            "expression": value["body"],
            "language": value["language"],
        })
        return
    if kind == "channel_reference":
        reference_node_path = operations._document_apply_state_current_path(
            state, value["nodeUid"], None
        )
        if not reference_node_path:
            raise JsonRpcError(
                INVALID_PARAMS, "Nested channel target is unavailable."
            )
        expression, language = operations._document_compile_channel_reference(
            f"{reference_node_path}/{value['parmName']}", {}
        )
        operations._parm_set_expression_impl({
            "parm_path": path,
            "expression": expression,
            "language": language,
        })
        return
    raise JsonRpcError(
        INVALID_PARAMS, f"Unsupported nested multiparm value: {kind}."
    )
