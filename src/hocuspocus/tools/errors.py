"""Error model shared by host and bridge. Stdlib only. See docs/BIBLE.md §9.

Every tool failure is an ``isError`` MCP result whose structured content is
``ToolError.to_dict()``. The code set is closed; adding a code is a design change.
"""

from __future__ import annotations

from typing import Any

ERROR_CODES: dict[str, str] = {
    "houdini_offline": "No live Houdini instance is connected.",
    "instance_lost": "The pinned Houdini exited; the bridge does not switch to another on its own.",
    "ambiguous_instance": "Several Houdinis run and none is pinned; pin one before changing a scene.",
    "houdini_busy": "Houdini's main thread did not finish the call within the timeout.",
    "delivery_unknown": "The request was sent but the response was lost; inspect state before repeating.",
    "version_mismatch": "Host and bridge speak different hp RPC versions.",
    "invalid_argument": "Arguments failed schema or shape validation.",
    "node_not_found": "No node at the given path.",
    "parm_not_found": "No parm or parm tuple with that name on the node.",
    "node_type_not_found": "No node type with that name in the category.",
    "invalid_input": "Input index or name is not valid for the node.",
    "invalid_value": "Value does not match the parm's type, range or menu.",
    "name_collision": "A node with that name already exists.",
    "locked": "The target is inside a locked HDA or is otherwise not editable.",
    "cook_failed": "Cooking raised; node errors are attached.",
    "unsaved_changes": "The scene has unsaved changes and consent was not given.",
    "file_not_found": "The file path does not exist.",
    "path_not_allowed": "The path is outside the configured approved roots.",
    "ui_required": (
        "A GUI-only argument value (source: viewer) on a headless Houdini, or a modal "
        "hou.ui dialog refused during a call in a GUI session."
    ),
    "python_disabled": "houdini_python is disabled by configuration.",
    "read_only": "The host is in read-only mode.",
    "job_not_found": "No job with that id (jobs do not survive a Houdini restart).",
    "cancelled": "The job was cancelled.",
    "python_exception": "houdini_python code raised; stdout, stderr and traceback are in detail.",
    "internal": "Unexpected failure; hou_exception and detail are attached.",
}

RETRYABLE: frozenset[str] = frozenset({"houdini_offline", "houdini_busy"})

READ_ONLY_HINT = (
    "Set read_only = false in hocuspocus.toml (or HOCUSPOCUS_READ_ONLY=0) and restart the host."
)


class ToolError(Exception):
    """Raise from a tool implementation to produce a structured ``isError`` result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        candidates: list[Any] | None = None,
        hou_exception: str | None = None,
        detail: Any = None,
        retryable: bool | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(
                f"unknown error code {code!r}; see hocuspocus.tools.errors.ERROR_CODES"
            )
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.candidates = candidates or []
        self.hou_exception = hou_exception
        self.detail = detail
        self.retryable = code in RETRYABLE if retryable is None else retryable
        """Defaults to the code's (BIBLE §9); False where repeating cannot work, e.g.
        ``houdini_offline`` when no Houdini is running at all."""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.hint:
            payload["hint"] = self.hint
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        if self.hou_exception:
            payload["hou_exception"] = self.hou_exception
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolError:
        code = str(data.get("code", "internal"))
        if code not in ERROR_CODES:
            code = "internal"
        return cls(
            code,
            str(data.get("message", ERROR_CODES[code])),
            hint=data.get("hint"),
            candidates=list(data.get("candidates") or []),
            hou_exception=data.get("hou_exception"),
            detail=data.get("detail"),
            retryable=data.get("retryable") if isinstance(data.get("retryable"), bool) else None,
        )


def read_only_error(what: str) -> ToolError:
    """The one ``read_only`` refusal: ``<what> changes the scene, and the host is in
    read-only mode.`` with :data:`READ_ONLY_HINT`."""
    return ToolError(
        "read_only",
        f"{what} changes the scene, and the host is in read-only mode.",
        hint=READ_ONLY_HINT,
    )
