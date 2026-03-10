"""UI integration scaffolding."""

from __future__ import annotations


def show_panel():
    from .panel import show_panel as _show_panel

    return _show_panel()


__all__ = ["show_panel"]
