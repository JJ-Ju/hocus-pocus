"""``hocuspocus-mcp``: run the stdio MCP bridge. Logs go to stderr only; stdout is MCP."""

from __future__ import annotations

import contextlib
import logging
import os
import sys


def main() -> None:
    level = os.environ.get("HOCUSPOCUS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s hocuspocus-mcp %(levelname)s %(name)s: %(message)s",
    )
    import anyio

    from .server import serve_stdio

    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(serve_stdio)


if __name__ == "__main__":
    main()
