"""Headless host: ``hython -m hocuspocus.host [--hip FILE] [--port N] [--state-dir D]``.

Starts the HTTP listener on a daemon thread, prints one JSON line
``{"pid", "port", "token_file"}`` to stdout, then pumps the main-thread executor until
SIGINT/SIGTERM or ``POST /hp/v1/shutdown``, and exits normally (never ``os._exit``:
it segfaults hython in PDG teardown). Run it from a neutral working directory: hython
puts its cwd on ``HOUDINI_PATH``.

Once started it moves to ``--work-dir`` (default ``HOCUSPOCUS_WORK_DIR``, else the home
directory) and re-anchors the untitled scene there, so ``$HIP`` and ``$JOB`` never point
at the launch or state directory. ``--work-dir .`` keeps the launch directory.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import sys
from typing import Any


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hython -m hocuspocus.host", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--hip", help="hip file to load before serving")
    parser.add_argument("--port", type=int, default=None, help="TCP port (default 0: ephemeral)")
    parser.add_argument("--state-dir", default=None, help="override the HocusPocus state directory")
    parser.add_argument("--label", default=None, help="instance label for the registry")
    parser.add_argument(
        "--read-only", action="store_true", default=None, help="refuse mutating tools"
    )
    parser.add_argument("--no-python", action="store_true", help="disable houdini_python")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="directory for the untitled scene's $HIP/$JOB "
        "(default: HOCUSPOCUS_WORK_DIR, else the home directory)",
    )
    return parser.parse_args(argv)


def _move_to_work_dir(hou: Any, work_dir: str | None, *, keep_scene: bool) -> None:
    """chdir to the work dir; re-anchor an untitled scene's $HIP and a default $JOB there.

    Verified on 22.0.466: ``$HIP`` of an untitled scene follows the cwd at the next
    ``hipFile.clear()``; ``$JOB`` stays at the startup cwd unless set.
    """
    from pathlib import Path

    from hocuspocus.tools.paths import work_dir as default_work_dir

    started_in = os.path.normcase(os.path.abspath(os.getcwd()))
    target = Path(work_dir).expanduser() if work_dir else default_work_dir()
    target.mkdir(parents=True, exist_ok=True)
    os.chdir(target)
    if not keep_scene:
        hou.hipFile.clear(suppress_save_prompt=True)
    job = hou.getenv("JOB") or ""
    if not job or os.path.normcase(os.path.abspath(job)) == started_in:
        hou.putenv("JOB", target.resolve().as_posix())


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    try:
        import hou
    except ImportError:
        print(
            json.dumps({"error": "hocuspocus.host must run inside Houdini (hython)."}), flush=True
        )
        return 2

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    logging.getLogger("hocuspocus").addHandler(stderr_handler)

    from . import current, start, stop
    from .config import load_config

    overrides: dict[str, Any] = {}
    if args.port is not None:
        overrides["port"] = args.port
    if args.state_dir:
        overrides["state_dir"] = args.state_dir
    if args.label:
        overrides["label"] = args.label
    if args.read_only:
        overrides["read_only"] = True
    if args.no_python:
        overrides["allow_python"] = False
    config = load_config(**overrides)

    _move_to_work_dir(hou, args.work_dir, keep_scene=bool(args.hip))
    if args.hip:
        try:
            hou.hipFile.load(args.hip, suppress_save_prompt=True, ignore_load_warnings=True)
        except hou.Error as exc:
            print(json.dumps({"error": f"cannot load {args.hip}: {exc}"}), flush=True)
            return 1

    info = start(config)
    host = current()
    if host is None or not info.get("running"):
        print(json.dumps({"error": info.get("error", "host failed to start")}), flush=True)
        return 1

    def _on_signal(signum: int, frame: Any) -> None:
        host.shutdown_event.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, _on_signal)

    print(
        json.dumps({"pid": info["pid"], "port": info["port"], "token_file": info["token_file"]}),
        flush=True,
    )
    try:
        host.executor.pump_forever(host.shutdown_event)
    except KeyboardInterrupt:
        pass
    finally:
        stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
