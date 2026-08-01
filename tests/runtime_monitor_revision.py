from __future__ import annotations

import logging
from types import SimpleNamespace
import unittest

import hocuspocus.live.monitor as monitor_module
from hocuspocus.live.monitor import SceneEventMonitor


class _Event:
    def __init__(self, name: str):
        self._name = name

    def name(self):
        return self._name

    def __str__(self):
        return f"nodeEventType.{self._name}"


class _SceneNode:
    _next_id = 1

    def __init__(self, path: str, children=()):
        self._path = path
        self._children = list(children)
        self._callbacks = []
        self._id = _SceneNode._next_id
        _SceneNode._next_id += 1

    def path(self):
        return self._path

    def sessionId(self):
        return self._id

    def allSubChildren(self):
        return tuple(
            child
            for direct_child in self._children
            for child in (direct_child, *direct_child.allSubChildren())
        )

    def addEventCallback(self, event_types, callback):
        self._callbacks.append((tuple(event_types), callback))

    def removeEventCallback(self, callback):
        self._callbacks = [item for item in self._callbacks if item[1] != callback]

    def emit(self, event, **kwargs):
        for event_types, callback in list(self._callbacks):
            if event in event_types:
                callback(self, event_type=event, **kwargs)


class _CallbackHost:
    def addEventCallback(self, callback):
        self.callback = callback

    def removeEventCallback(self, _callback):
        pass


def _fixture():
    names = (
        "AppearanceChanged", "BeingDeleted", "ChildCreated", "ChildDeleted",
        "ChildReordered", "CustomDataChanged", "FlagChanged",
        "IndirectInputCreated", "IndirectInputDeleted", "IndirectInputRewired",
        "InputRewired", "NameChanged", "ParmTupleAnimated", "ParmTupleChanged",
        "ParmTupleChannelChanged", "PositionChanged", "SpareParmTemplatesChanged",
    )
    events = {name: _Event(name) for name in names}
    sop = _SceneNode("/obj/geo1/box1")
    geo = _SceneNode("/obj/geo1", [sop])
    root = _SceneNode("/", [geo])
    fake_hou = SimpleNamespace(
        nodeEventType=SimpleNamespace(**events),
        node=lambda path: root if path == "/" else None,
        hipFile=_CallbackHost(),
        playbar=_CallbackHost(),
        isUIAvailable=lambda: False,
    )
    return fake_hou, events, sop, geo


def assert_monitor_revision_contract(test: unittest.TestCase) -> None:
    fake_hou, events, sop, geo = _fixture()
    original_hou = monitor_module.hou
    monitor_module.hou = fake_hou
    try:
        monitor = SceneEventMonitor(logging.getLogger("test.monitor"))
        monitor.start()
        sop.emit(events["ParmTupleChanged"])
        sop.emit(events["InputRewired"])
        child = _SceneNode("/obj/geo1/new1")
        geo.emit(events["ChildCreated"], child_node=child)
        child.emit(events["FlagChanged"])
        snapshot = monitor.snapshot()
        test.assertEqual(set(snapshot["dirtyScopes"]), {"/obj/geo1"})
        test.assertEqual(snapshot["observedNodeCount"], 4)
        test.assertEqual(
            monitor.recent_events(limit=1)["events"][0]["event"],
            "node:FlagChanged",
        )

        structural = snapshot["structuralRevision"]
        cosmetic = snapshot["cosmeticRevision"]
        sop.emit(events["AppearanceChanged"])
        test.assertEqual(monitor.snapshot()["structuralRevision"], structural)
        test.assertEqual(monitor.snapshot()["cosmeticRevision"], cosmetic + 1)

        operation_id = "op:" + "c" * 32
        monitor.begin_tool_operation(operation_id, "node.set_parameters")
        with monitor.activate_tool_operation(operation_id):
            sop.emit(events["ParmTupleChanged"])
            sop.emit(events["InputRewired"])
            sop.emit(events["PositionChanged"])
        monitor.mark_tool_mutation(operation_id, "/obj/geo1")
        outcome = monitor.finish_tool_operation(operation_id)
        final = monitor.snapshot()
        test.assertTrue(outcome["structuralChanged"])
        test.assertEqual(final["structuralRevision"], structural + 1)
        test.assertEqual(final["cosmeticRevision"], cosmetic + 2)
        event = monitor.recent_events(limit=1)["events"][0]
        test.assertEqual(event["operationId"], operation_id)
        test.assertEqual(event["toolName"], "node.set_parameters")
        test.assertEqual(event["eventCount"], 4)

        move_id = "op:" + "d" * 32
        monitor.begin_tool_operation(move_id, "node.move")
        monitor.mark_tool_cosmetic(move_id)
        move = monitor.finish_tool_operation(move_id)
        moved = monitor.snapshot()
        test.assertFalse(move["structuralChanged"])
        test.assertTrue(move["cosmeticChanged"])
        test.assertEqual(moved["structuralRevision"], structural + 1)
        test.assertEqual(moved["cosmeticRevision"], cosmetic + 3)
    finally:
        monitor_module.hou = original_hou


__all__ = ["assert_monitor_revision_contract"]
