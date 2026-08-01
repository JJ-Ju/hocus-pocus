"""Guarded access to Houdini's public undo and redo stack API."""

from __future__ import annotations

from typing import Any

from hocuspocus.core.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError


def _runtime_error(message: str, data: dict[str, Any]) -> JsonRpcError:
    return JsonRpcError(
        INTERNAL_ERROR,
        message,
        {"diagnosticCode": "HOCUS756", **data},
        family="runtime",
        retryable=False,
    )


def _stack_labels(undos: Any, direction: str) -> tuple[str, ...]:
    method_name = "undoLabels" if direction == "undo" else "redoLabels"
    method = getattr(undos, method_name, None)
    if not callable(method):
        raise _runtime_error(
            f"This Houdini session does not expose {method_name}().",
            {"direction": direction},
        )
    try:
        return tuple(str(item) for item in method())
    except Exception as exc:
        raise _runtime_error(
            f"Could not inspect the Houdini {direction} stack.",
            {
                "direction": direction,
                "errorType": exc.__class__.__name__,
            },
        ) from exc


def next_stack_label(hou_module: Any, direction: str) -> str:
    """Return the exact next stack label or fail without changing the scene."""
    labels = _stack_labels(hou_module.undos, direction)
    if not labels:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"The Houdini {direction} stack is empty.",
            {"diagnosticCode": "HOCUS755", "direction": direction},
        )
    return labels[0]


def stack_snapshot(hou_module: Any, *, limit: int = 16) -> dict[str, Any]:
    """Return bounded undo/redo labels for user-visible guarded stack receipts."""
    bounded = max(1, min(int(limit), 32))
    undo_labels = _stack_labels(hou_module.undos, "undo")
    redo_labels = _stack_labels(hou_module.undos, "redo")
    return {
        "undoLabels": list(undo_labels[:bounded]),
        "redoLabels": list(redo_labels[:bounded]),
        "undoCount": len(undo_labels),
        "redoCount": len(redo_labels),
        "truncated": len(undo_labels) > bounded or len(redo_labels) > bounded,
    }


def perform_stack_action(
    hou_module: Any,
    direction: str,
    *,
    expected_label: str,
) -> dict[str, Any]:
    """Perform one guarded stack action using the Houdini 22 public API."""
    if direction not in {"undo", "redo"}:
        raise ValueError("direction must be undo or redo")
    actual_label = next_stack_label(hou_module, direction)
    if actual_label != expected_label:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"The Houdini {direction} stack changed before the guarded action.",
            {
                "diagnosticCode": "HOCUS756",
                "direction": direction,
                "expectedLabel": expected_label,
                "actualLabel": actual_label,
            },
        )
    method_name = "performUndo" if direction == "undo" else "performRedo"
    method = getattr(hou_module.undos, method_name, None)
    if not callable(method):
        raise _runtime_error(
            f"This Houdini session does not expose {method_name}().",
            {"direction": direction},
        )
    try:
        completed = method()
    except Exception as exc:
        raise _runtime_error(
            f"Houdini could not {direction} {expected_label!r}.",
            {
                "direction": direction,
                "expectedLabel": expected_label,
                "errorType": exc.__class__.__name__,
            },
        ) from exc
    if completed is not True:
        raise _runtime_error(
            f"Houdini did not confirm {direction} for {expected_label!r}.",
            {
                "direction": direction,
                "expectedLabel": expected_label,
                "result": completed,
            },
        )
    return {"direction": direction, "label": expected_label, "performed": True}
