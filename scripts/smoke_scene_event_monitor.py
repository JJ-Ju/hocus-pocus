"""Verify source-tree node callbacks and scope coalescing in a disposable hython scene."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import hou  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "python3.11libs" / "hocuspocus" / "live" / "monitor.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("hocuspocus_source_monitor_smoke", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load source monitor module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.hou = hou
    monitor = module.SceneEventMonitor(logging.getLogger("hocus.monitor.smoke"))
    received = []
    monitor.add_listener(received.append)
    target_path = "/obj/hocus_monitor_smoke"
    if hou.node(target_path) is not None:
        raise RuntimeError(f"Refusing to reuse or delete existing node {target_path}")
    monitor.start()
    root = None
    try:
        root = hou.node("/obj").createNode("geo", node_name="hocus_monitor_smoke")
        for child in tuple(root.children()):
            child.destroy()
        child = root.createNode("null", node_name="tracked")
        child.setPosition(hou.Vector2(2.0, 3.0))
        child.setDisplayFlag(True)
        scoped = [item for item in received if item.get("scopePath") == target_path]
        if not scoped:
            raise RuntimeError(f"No node-level event was coalesced to {target_path}: {received[-20:]!r}")
        snapshot = monitor.snapshot()
        if target_path not in snapshot["dirtyScopes"]:
            raise RuntimeError(f"Expected dirty network scope was absent: {snapshot!r}")
        print(
            "HS3 node monitor smoke passed",
            f"observedNodes={snapshot['observedNodeCount']}",
            f"scopedEvents={len(scoped)}",
            f"latest={scoped[-1]['event']}",
        )
        return 0
    finally:
        monitor.stop()
        if root is not None:
            root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
