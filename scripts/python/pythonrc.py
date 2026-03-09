"""Houdini startup helpers for HocusPocus."""

from __future__ import annotations


def hocuspocus_server_status():
    import hocuspocus

    return hocuspocus.server_status()


def _maybe_autostart_hocuspocus():
    try:
        from hocuspocus.core.settings import load_settings
        import hocuspocus
    except Exception:
        return

    try:
        settings = load_settings()
    except Exception:
        return

    if not settings.auto_start:
        return

    try:
        hocuspocus.start_server()
    except Exception:
        # Avoid breaking Houdini startup if the server fails to initialize.
        return


_maybe_autostart_hocuspocus()
