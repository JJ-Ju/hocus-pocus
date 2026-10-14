"""Review 20 (FX sim and cache re-run on 1.3) as a workload, smaller.

A pyro plume from a sphere (``pyrosource`` with its ``initialize`` callback pressed in
``node_create``, rasterized, ``pyrosolver``), cached for 24 frames by ``render`` on a
``filecache::2.0`` as a job, polled to the end. Then the cached volumes are read back at
frame 24 with ``geo_info``/``geo_read``, the solver is profiled, and one
``viewport_capture`` looks at frame 24 through a camera. The cache is deleted afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(420)

GEO = "/obj/pyro"
FRAMES = 24
MAX_CACHE_BYTES = 300 * 1024 * 1024


def test_fx_cache(workload):
    rec = workload
    pattern = rec.path("cache", "pyro.$F4.bgeo.sc")

    found = rec.ok("node_type_search", {"query": "pyro", "category": "Sop", "limit": 8})
    names = [row["name"] for row in found["results"]]
    assert "pyrosolver" in names and "pyrosource" in names, names

    built = rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "pyro"},
                {"parent": GEO, "type": "sphere", "name": "src_sphere",
                 "parms": {"type": "polymesh", "rad": [0.5, 0.4, 0.5], "t": [0, 0.5, 0],
                           "freq": 6}},
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
            ]
        },
    )  # fmt: skip
    rows = {row["path"]: row for row in built["results"]}
    assert rows[f"{GEO}/pyrosource"].get("side_effects"), rows[f"{GEO}/pyrosource"]
    source = rec.ok("geo_info", {"path": f"{GEO}/rasterize"})
    assert source["prim_count"] == 2, source.data  # density and temperature

    # -- cache through render, as a job ----------------------------------------------
    started = rec.ok("render", {"rop_path": f"{GEO}/cache", "frames": [1, FRAMES], "wait_s": 0})
    job_id = started["job_id"]
    assert rec.wait_job(job_id, timeout_s=300)["state"] == "done"
    result = rec.ok("job", {"action": "result", "job_id": job_id})
    summary = result.get("result", result.data)["outputs_summary"]
    assert summary["count"] == FRAMES and summary["missing_count"] == 0, summary
    files = sorted(Path(rec.work, "cache").glob("pyro.*.bgeo.sc"))
    assert len(files) == FRAMES
    size = sum(f.stat().st_size for f in files)
    assert size <= MAX_CACHE_BYTES, size

    # -- read the cache back ---------------------------------------------------------
    vols = rec.ok("geo_info", {"path": f"{GEO}/cache", "frame": FRAMES})
    text = str(vols.data)
    for name in ("density", "temperature", "vel"):
        assert name in text, vols.data
    rec.ok(
        "geo_read",
        {"path": f"{GEO}/cache", "class": "prim", "attribs": ["name"], "frame": 12},
    )
    assert rec.ok("time", {})["frame"] == 1  # reading frames does not move the playbar
    profiled = rec.ok("cook", {"paths": [f"{GEO}/pyrosolver"], "profile": True, "frame": 12})
    row = next(r for r in profiled["chain"] if r["path"] == f"{GEO}/pyrosolver")
    assert "simulation" in row, row
    look = rec.ok(
        "viewport_capture",
        {"camera": "/obj/cam_fx", "frame": FRAMES, "resolution": [480, 270]},
        timeout=180,
    )
    assert look.images == 1, look.data
    memory = rec.ok("houdini_status")["connected"]["memory"]
    rec.ok("problems", {"root": GEO})

    rec.finish({"cache_mb": round(size / 2**20, 1), "rss_mb": memory.get("rss_mb")})
