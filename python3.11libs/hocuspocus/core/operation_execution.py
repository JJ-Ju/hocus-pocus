"""Host-side admitted tool execution and terminal response retention."""

from __future__ import annotations

from typing import Any

from .jsonrpc import INTERNAL_ERROR, JsonRpcError
from .operation_history import (
    SESSION_POLICY_PRINCIPAL,
    argument_digest,
    attach_operation_metadata,
    commit_state_for_result,
    error_from_terminal,
    sanitize_terminal_payload,
)
from .policy import require_capabilities


def _audit(
    runtime: Any,
    tool: Any,
    arguments: dict[str, Any],
    context: Any,
    identity: Any,
    commit_state: str,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    try:
        runtime.audit.log_tool_call(
            operation_id=context.operation_id,
            caller_id=context.caller_id,
            tool_name=tool.name,
            arguments=arguments,
            success=error is None,
            result=result,
            error=error,
            host_instance_id=identity.instance_id,
            host_generation=identity.generation,
            delivery_stage="terminal",
            commit_state=commit_state,
        )
    except Exception:
        runtime.logger.error("operation audit persistence failed")


def _finish_failure(
    runtime: Any,
    tool: Any,
    arguments: dict[str, Any],
    context: Any,
    identity: Any,
    failure: JsonRpcError,
) -> None:
    transaction = runtime.monitor.finish_tool_operation(context.operation_id)
    commit_state = _failure_commit_state(failure, transaction)
    error = failure.to_payload()
    runtime.operation_history.finish(
        context.operation_id, principal_id=context.principal_id,
        commit_state=commit_state, error=error,
    )
    _audit(
        runtime, tool, arguments, context, identity, commit_state, error=error
    )


def _failure_commit_state(
    failure: JsonRpcError, transaction: dict[str, Any]
) -> str:
    data = failure.data if isinstance(failure.data, dict) else {}
    outcome = data.get("failure")
    outcome = outcome if isinstance(outcome, dict) else data
    code = data.get("hocusCode")
    if (
        code == "HOCUS755"
        and outcome.get("rolledBack") is True
        and outcome.get("state") in {None, "aborted"}
    ):
        return "not_committed"
    if code == "HOCUS756" or outcome.get("state") == "partial_or_unknown":
        return "partial_or_unknown"
    return (
        "partial_or_unknown"
        if transaction["structuralChanged"]
        else "not_committed"
    )
def _admit(
    runtime: Any,
    tool: Any,
    arguments: dict[str, Any],
    context: Any,
    identity: Any,
) -> dict[str, Any] | None:
    admission, prior = runtime.operation_history.admit(
        context.operation_id,
        tool.name,
        context.principal_id,
        context.session_id,
        identity.instance_id,
        identity.generation,
        argument_digest(arguments),
        SESSION_POLICY_PRINCIPAL,
        tool.annotations.get("readOnlyHint") is not True,
    )
    if admission == "terminal" and prior is not None:
        if prior["terminalError"] is not None:
            error_from_terminal(prior["terminalError"])
        return prior["terminalResult"]
    if admission != "new":
        raise JsonRpcError(
            -32009,
            "Operation identity is already active or belongs to another request.",
            {
                "hocusCode": "HOCUS999",
                "kind": f"operation_{admission}",
                "operationId": context.operation_id,
            },
            family="conflict",
            retryable=admission == "pending",
        )
    return None


def _mark_mutation(
    runtime: Any,
    tool: Any,
    arguments: dict[str, Any],
    context: Any,
    result: dict[str, Any],
) -> None:
    if tool.annotations.get("readOnlyHint") is True:
        return
    if not runtime._should_bump_graph_revision(tool.name):
        return
    scope_path = None
    resolver = getattr(runtime.operations, "dirty_scope_for_tool", None)
    if callable(resolver):
        try:
            scope_path = resolver(tool.name, arguments, result)
        except Exception:
            runtime.logger.debug(
                "failed to resolve dirty scope for %s", tool.name, exc_info=True
            )
    if tool.name in {"node.move", "node.layout"}:
        runtime.monitor.mark_tool_cosmetic(context.operation_id)
    else:
        runtime.monitor.mark_tool_mutation(context.operation_id, scope_path)


def execute_tool_call(
    runtime: Any,
    tool: Any,
    arguments: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    identity = runtime.host_identity
    prior = _admit(runtime, tool, arguments, context, identity)
    if prior is not None:
        return prior
    runtime.monitor.begin_tool_operation(context.operation_id, tool.name)
    try:
        require_capabilities(context.permissions, tool.required_capabilities)
        result = tool.handler(arguments, context)
    except JsonRpcError as exc:
        _finish_failure(runtime, tool, arguments, context, identity, exc)
        raise
    except Exception as exc:
        failure = JsonRpcError(
            INTERNAL_ERROR,
            "Internal server error",
            str(exc),
            family="runtime",
            retryable=False,
        )
        _finish_failure(runtime, tool, arguments, context, identity, failure)
        raise failure from exc
    _mark_mutation(runtime, tool, arguments, context, result)
    runtime.monitor.finish_tool_operation(context.operation_id)
    commit_state = commit_state_for_result(result, tool.annotations)
    result = attach_operation_metadata(
        result,
        operation_id=context.operation_id,
        tool_name=tool.name,
        host_instance_id=identity.instance_id,
        host_generation=identity.generation,
        commit_state=commit_state,
    )
    terminal = runtime.operation_history.finish(
        context.operation_id, principal_id=context.principal_id,
        commit_state=commit_state, result=result,
    )
    _audit(runtime, tool, arguments, context, identity, commit_state, result=result)
    try:
        runtime._track_generation_checkout(tool.name, arguments, result)
    except Exception:
        runtime.logger.error("operation checkout tracking failed")
    if terminal is not None and terminal["terminalResult"] is not None:
        return terminal["terminalResult"]
    return sanitize_terminal_payload(result)


__all__ = ["execute_tool_call"]
