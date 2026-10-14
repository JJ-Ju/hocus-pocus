"""Review 20's FX cache on the 2.0 tools (the 1.4 version: ``../test_fx_cache.py``).

The same pyro plume, camera and light in one ``edit`` (``$id`` chains, the ``initialize``
button pressed in its ``create``), cached for 24 frames by ``render`` on the
``filecache::2.0``: one call with a progress token that waits for the job's end (progress
arrives as notifications) instead of ``render`` + ``job status`` + ``job result``. The
cache is read back with ``inspect``, the solver profiled, one ``look`` at frame 24.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from wl2 import creates, load_1x, rows_by_path

pytestmark = pytest.mark.timeout(420)

w1 = load_1x("test_fx_cache")
GEO, FRAMES, MAX_CACHE_BYTES = w1.GEO, w1.FRAMES, w1.MAX_CACHE_BYTES


def test_fx_cache(workload):
    rec = workload
    pattern = rec.path("cache", "pyro.$F4.bgeo.sc")

    found = rec.ok("search", {"kind": "types", "query": "pyro", "category": "Sop", "limit": 8})
    names = [row["name"] for row in found["results"]]
    assert "pyrosolver" in names and "pyrosource" in names, names

    items = [
        {"parent": "/obj", "type": "geo", "name": "pyro"},
        {"parent": GEO, "type": "sphere", "name": "src_sphere",
         "parms": {"type": "polymesh", "rad": [0.5, 0.4, 0.5], "t": [0, 0.5, 0], "freq": 6}},
        {"parent": GEO, "type": "pyrosource", "name": "pyrosource",
         "inputs": [{"index": 0, "from": f"{GEO}/src_sphere"}],
         "parms": {"mode": "2", "particlesep": 0.06,
                   "initialize": {"value": "source", "press": True}}},
        {"parent": GEO, "type": "volumerasterizeattributes", "name": "rasterize",
         "inputs": [{"index": 0, "from": f"{GEO}/pyrosource"}],
         "parms": {"attributes": "density temperature", "voxelsize": 0.06}},
        {"parent": GEO, "type": "pyrosolver", "name": "pyrosolver",
         "inputs": [{"index": 0, "from": f"{GEO}/rasterize"}],
         "parms": {"divsize": 0.12, "clampsize": True, "maxsize": [3, 5, 3]}},
        {"parent": GEO, "type": "filecache::2.0", "name": "cache",
         "inputs": [{"index": 0, "from": f"{GEO}/pyrosolver"}],
         "parms": {"filemethod": "explicit", "file": pattern, "trange": "normal",
                   "f1": 1, "f2": FRAMES},
         "flags": {"display": True, "render": True}},
        {"parent": "/obj", "type": "cam", "name": "cam_fx",
         "parms": {"t": [5, 2.5, 5], "r": [-10, 45, 0], "resx": 480, "resy": 270}},
        {"parent": "/obj", "type": "hlight::2.0", "name": "key",
         "parms": {"light_type": "distant", "r": [-45, 30, 0]}},
    ]  # fmt: skip
    built = rec.ok("edit", {"ops": creates(items)})
    rows = rows_by_path(built)
    assert rows[f"{GEO}/pyrosource"].get("side_effects"), rows[f"{GEO}/pyrosource"]
    source = rec.ok("inspect", {"what": "geo", "target": f"{GEO}/rasterize"})
    assert source["prim_count"] == 2, source.data  # density and temperature

    # -- cache through render: one call, progress pushed while it runs ---------------
    cached = rec.ok(
        "render",
        {"rop_path": f"{GEO}/cache", "frames": [1, FRAMES], "wait_s": 280},
        progress=True,
        timeout=300,
    )
    assert cached["state"] == "done", cached.data
    summary = cached["outputs_summary"]
    assert summary["count"] == FRAMES and summary["missing_count"] == 0, summary
    files = sorted(Path(rec.work, "cache").glob("pyro.*.bgeo.sc"))
    assert len(files) == FRAMES
    size = sum(f.stat().st_size for f in files)
    assert size <= MAX_CACHE_BYTES, size

    # -- read the cache back ---------------------------------------------------------
    vols = rec.ok("inspect", {"what": "geo", "target": f"{GEO}/cache", "frame": FRAMES})
    text = str(vols.data)
    for name in ("density", "temperature", "vel"):
        assert name in text, vols.data
    rec.ok(
        "inspect",
        {"what": "geo", "target": f"{GEO}/cache", "rows": True, "class": "prim",
         "attribs": ["name"], "frame": 12},
    )  # fmt: skip
    assert rec.ok("time", {})["frame"] == 1  # reading frames does not move the playbar
    profiled = rec.ok("cook", {"paths": [f"{GEO}/pyrosolver"], "profile": True, "frame": 12})
    row = next(r for r in profiled["chain"] if r["path"] == f"{GEO}/pyrosolver")
    assert "simulation" in row, row
    look = rec.ok(
        "look",
        {"camera": "/obj/cam_fx", "frame": FRAMES, "resolution": [480, 270]},
        timeout=180,
    )
    assert look.images == 1, look.data
    memory = rec.ok("houdini_status", {"detail": True})["connected"]["memory"]  # 2.0: asked for
    rec.ok("inspect", {"what": "problems", "target": GEO})

    rec.finish(
        {
            "cache_mb": round(size / 2**20, 1),
            "rss_mb": memory.get("rss_mb"),
            "progress_notifications": len(rec.progress),
        }
    )
