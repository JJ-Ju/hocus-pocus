"""Shared private types for platform workspace boundaries."""

from __future__ import annotations

from dataclasses import dataclass


class NativeWorkspaceError(RuntimeError):
    """Sanitized native trust-boundary failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NativeWorkspaceMissing(NativeWorkspaceError):
    """A safely inspected relative object was absent."""

    def __init__(self):
        super().__init__("HOCUS825", "Workspace file does not exist.")


@dataclass(frozen=True, slots=True)
class NativeRootInfo:
    identity_digest: str
    platform: str
    filesystem: str


__all__ = ["NativeRootInfo", "NativeWorkspaceError", "NativeWorkspaceMissing"]
