"""``cook {frame_range}`` and the playbar (docs/parity.md G4): put back only when nobody
moved it. Pure logic; the GUI half is in test_parity_gui.py."""

from __future__ import annotations

from hocuspocus.host.tools.cook import Playhead


def _run(playhead: Playhead, frames: list[float], scrubs: dict[int, float]) -> float:
    """Simulate the job: before step ``i`` the user may have moved the playbar to
    ``scrubs[i]``; returns the frame the playbar shows when the job ends."""
    now = playhead.start
    for index, frame in enumerate(frames):
        now = scrubs.get(index, now)
        playhead.before_step(now)
        now = frame  # the step sets its frame
        playhead.stepped(frame)
    return scrubs.get(len(frames), now)


def test_untouched_playbar_goes_back_to_the_start() -> None:
    playhead = Playhead(12)
    now = _run(playhead, [1, 2, 3, 4], {})
    assert playhead.finish(now) == ("restore", 12)
    assert playhead.note("restore", 12, ui=False) is None
    assert "put back to frame 12" in (playhead.note("restore", 12, ui=True) or "")


def test_a_scrub_after_the_last_step_is_left_alone() -> None:
    playhead = Playhead(12)
    now = _run(playhead, [1, 2, 3, 4], {4: 30})
    assert playhead.finish(now) == ("moved", 30)
    note = playhead.note("moved", 30, ui=True)
    assert note and "frame 30" in note and "frame 12" in note


def test_a_scrub_during_the_job_is_put_back_after_it() -> None:
    playhead = Playhead(12)
    now = _run(playhead, [1, 2, 3, 4], {2: 40})
    assert now == 4  # the later steps set their own frames
    assert playhead.finish(now) == ("user", 40)


def test_the_last_scrub_wins() -> None:
    playhead = Playhead(12)
    now = _run(playhead, [1, 2, 3, 4], {1: 40, 3: 41})
    assert playhead.finish(now) == ("user", 41)


def test_a_job_that_cooked_nothing_restores() -> None:
    playhead = Playhead(7)
    assert playhead.finish(7) == ("restore", 7)
