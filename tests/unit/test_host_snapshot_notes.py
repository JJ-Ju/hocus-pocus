"""The snapshot's note for simulation frames held in memory (docs/parity.md G8). Pure
formatting; the integration half is tests/integration/test_parity_headless.py."""

from __future__ import annotations

from hocuspocus.host.look.child import SIM_NOTE_CAP, simulation_cache_note


def test_no_cached_simulation_no_note() -> None:
    assert simulation_cache_note([]) is None


def test_the_note_names_each_network_and_its_frames() -> None:
    note = simulation_cache_note([{"path": "/obj/sim", "frame": 24.0, "start": 1.0}])
    assert note is not None
    assert "/obj/sim (frames 1-24)" in note
    assert "re-simulates" in note and "File Cache" in note


def test_the_note_is_capped() -> None:
    sims = [{"path": f"/obj/sim{i}", "frame": 10.0, "start": 1.0} for i in range(5)]
    note = simulation_cache_note(sims) or ""
    assert note.count("/obj/sim") == SIM_NOTE_CAP
    assert f"and {5 - SIM_NOTE_CAP} more" in note
