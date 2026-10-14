"""One dirty source in both modes (docs/parity.md G1, BIBLE §3.2): the tracked flag OR a
change made outside HocusPocus. Pure logic; the GUI half is in test_parity_gui.py."""

from __future__ import annotations

from typing import Any

from hocuspocus.host.tools.events import EventLog
from hocuspocus.host.tools.registry import DIRTY_SOURCES, SceneState


def test_clean_scene_has_no_source() -> None:
    scene = SceneState()
    assert scene.is_dirty is False
    assert scene.dirty_source is None


def test_tracked_flag_wins_over_user_sources() -> None:
    scene = SceneState()
    scene.mark_user_dirty("user_event")
    assert scene.is_dirty is True
    assert scene.dirty_source == "user_event"
    scene.mark_dirty()
    assert scene.dirty_source == "tracked"
    scene.mark_clean()
    assert scene.is_dirty is False
    assert scene.dirty_source is None


def test_first_user_source_is_kept() -> None:
    scene = SceneState()
    scene.mark_user_dirty("houdini_flag")
    scene.mark_user_dirty("user_event")
    assert scene.dirty_source == "houdini_flag"
    assert set(DIRTY_SOURCES) == {"tracked", "user_event", "houdini_flag"}


def test_houdini_flag_counts_only_between_work_items() -> None:
    scene = SceneState()
    scene.mark_clean()  # a save, load or clear: Houdini's flag is clear too
    # A read's temporary nodes set Houdini's flag inside the work item: not a change.
    scene.check_houdini_flag(False)
    scene.note_houdini_flag(True)
    scene.check_houdini_flag(True)
    assert scene.is_dirty is False
    # Saved: the flag clears; the user then edits a node nobody watches.
    scene.mark_clean()
    scene.check_houdini_flag(True)
    assert scene.dirty_source == "houdini_flag"


def test_houdini_flag_unknown_is_ignored() -> None:
    scene = SceneState()
    assert scene.houdini_flag is None
    scene.check_houdini_flag(True)
    assert scene.is_dirty is False


def _log() -> tuple[EventLog, list[dict[str, Any]]]:
    log = EventLog()
    seen: list[dict[str, Any]] = []
    log.on_other = seen.append
    return log, seen


def test_other_node_events_reach_the_listener() -> None:
    log, seen = _log()
    log.record("NameChanged", "/obj/a", {"old_name": "b"})
    assert [e["kind"] for e in seen] == ["NameChanged"]
    assert seen[0]["origin"] == "other"


def test_agent_hip_and_pdg_events_do_not() -> None:
    log, seen = _log()
    assert log.begin()
    log.record("ChildCreated", "/obj/geo1")
    log.end()
    log.record("AfterSave", "C:/x.hip")
    log.record("pdg", "/obj/topnet1", {"event": "cook_start"}, origin="agent")
    log.record("ParmTupleChanged", "/obj/geo1", {"parm": "t"}, origin="agent")
    assert seen == []


def test_a_failing_listener_does_not_lose_the_event() -> None:
    log = EventLog()

    def boom(_event: dict[str, Any]) -> None:
        raise RuntimeError("listener")

    log.on_other = boom
    log.record("NameChanged", "/obj/a")
    assert log.read(0, 10)["events"][0]["kind"] == "NameChanged"


def test_events_mark_the_scene_user_dirty() -> None:
    scene = SceneState()
    log = EventLog()
    log.on_other = lambda _event: scene.mark_user_dirty("user_event")
    log.record("ParmTupleChanged", "/obj/a", {"parm": "tx"})
    assert scene.dirty_source == "user_event"
    scene.mark_clean()
    assert scene.is_dirty is False
