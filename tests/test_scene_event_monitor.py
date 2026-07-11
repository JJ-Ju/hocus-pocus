from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

import hocuspocus.live.monitor as monitor_module
from hocuspocus.live.monitor import SceneEventMonitor


class _Event:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name

    def __str__(self) -> str:
        return "nodeEventType." + self._name


class _Node:
    _next_id = 1

    def __init__(self, path: str, children: list["_Node"] | None = None):
        self._path = path
        self._children = list(children or [])
        self._callbacks = []
        self._id = _Node._next_id
        _Node._next_id += 1

    def path(self) -> str:
        return self._path

    def sessionId(self) -> int:
        return self._id

    def allSubChildren(self):
        result = []
        for child in self._children:
            result.append(child)
            result.extend(child.allSubChildren())
        return tuple(result)

    def addEventCallback(self, event_types, callback) -> None:
        self._callbacks.append((tuple(event_types), callback))

    def removeEventCallback(self, callback) -> None:
        self._callbacks = [item for item in self._callbacks if item[1] != callback]

    def emit(self, event: _Event, **kwargs) -> None:
        for event_types, callback in list(self._callbacks):
            if event in event_types:
                callback(self, event_type=event, **kwargs)


class _Callbacks:
    def addEventCallback(self, callback) -> None:
        self.callback = callback

    def removeEventCallback(self, callback) -> None:
        pass


class SceneEventMonitorNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        names = (
            "AppearanceChanged", "BeingDeleted", "ChildCreated", "ChildDeleted", "ChildReordered",
            "CustomDataChanged", "FlagChanged", "IndirectInputCreated", "IndirectInputDeleted",
            "IndirectInputRewired", "InputRewired", "NameChanged", "ParmTupleAnimated",
            "ParmTupleChanged", "ParmTupleChannelChanged", "PositionChanged", "SpareParmTemplatesChanged",
        )
        self.events = {name: _Event(name) for name in names}
        self.sop = _Node("/obj/geo1/box1")
        self.geo = _Node("/obj/geo1", [self.sop])
        self.root = _Node("/", [self.geo])
        self.hou = SimpleNamespace(
            nodeEventType=SimpleNamespace(**self.events),
            node=lambda path: self.root if path == "/" else None,
            hipFile=_Callbacks(),
            playbar=_Callbacks(),
            isUIAvailable=lambda: False,
        )
        self.original_hou = monitor_module.hou
        monitor_module.hou = self.hou

    def tearDown(self) -> None:
        monitor_module.hou = self.original_hou

    def test_node_events_are_observed_and_coalesced_by_network_scope(self) -> None:
        monitor = SceneEventMonitor(logging.getLogger("test.monitor"))
        monitor.start()
        self.sop.emit(self.events["ParmTupleChanged"])
        self.sop.emit(self.events["InputRewired"])

        snapshot = monitor.snapshot()
        self.assertTrue(snapshot["nodeCallbacksInstalled"])
        self.assertEqual(snapshot["observedNodeCount"], 3)
        self.assertEqual(snapshot["dirtyScopeCount"], 1)
        self.assertIn("/obj/geo1", snapshot["dirtyScopes"])

    def test_created_child_is_observed_for_future_edits(self) -> None:
        monitor = SceneEventMonitor(logging.getLogger("test.monitor"))
        monitor.start()
        child = _Node("/obj/geo1/new1")
        self.geo.emit(self.events["ChildCreated"], child_node=child)
        child.emit(self.events["FlagChanged"])

        events = monitor.recent_events(limit=10)["events"]
        self.assertEqual(events[-1]["scopePath"], "/obj/geo1")
        self.assertEqual(events[-1]["event"], "node:FlagChanged")
        self.assertEqual(monitor.snapshot()["observedNodeCount"], 4)


if __name__ == "__main__":
    unittest.main()
