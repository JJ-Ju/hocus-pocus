"""HocusPocus Houdini MCP server package."""

from .startup import restart_server, server_status, start_server, stop_server
from .version import __version__


def show_panel():
    from .ui import show_panel as _show_panel

    return _show_panel()

__all__ = [
    "__version__",
    "restart_server",
    "server_status",
    "show_panel",
    "start_server",
    "stop_server",
]
