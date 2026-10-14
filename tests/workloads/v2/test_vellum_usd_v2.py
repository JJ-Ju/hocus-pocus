"""Review 24's Vellum cloth and USD round trip on the 2.0 tools (1.4: ``../test_vellum_usd.py``).

The same cloth, cache, USD export, sublayer and Karma frame. Each build step is one
``edit`` with ``$id`` chains; the cache is one ``render`` call with a progress token that
waits for the job (instead of ``render`` + ``job status`` + ``job result``); the stage is
read once with ``inspect what: stage`` (the tree and the extent's time samples together).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from wl2 import creates, load_1x, node_problems

pytestmark = pytest.mark.timeout(420)

w1 = load_1x("test_vellum_usd")
GEO, FRAMES = w1.GEO, w1.FRAMES


def test_vellum_usd(workload):
    rec = workload
    found = rec.ok("search", {"kind": "types", "query": "vellum", "category": "Sop", "limit": 10})
    names = [row["name"] for row in found["results"]]
    assert "vellumsolver" in str(names) and "vellumconstraints" in str(names), names
    rec.ok("inspect", {"what": "type", "target": "Sop/vellumconstraints",
                       "parms": "constrainttype|pin*"})  # fmt: skip

    # -- the cloth, simulated and cached in one waiting call ----------------------------
    cloth = [
        {"parent": "/obj", "type": "geo", "name": "cloth"},
        {"parent": GEO, "type": "grid", "name": "cloth_grid",
         "parms": {"size": [4, 4], "rows": 24, "cols": 24, "t": [0, 3, 0]}},
        {"parent": GEO, "type": "vellumconstraints", "name": "cloth_con",
         "inputs": [{"index": 0, "from": f"{GEO}/cloth_grid"}],
         "parms": {"constrainttype": "cloth", "pingroup": "0 23"}},
        {"parent": GEO, "type": "sphere", "name": "collider",
         "parms": {"type": "polymesh", "rad": [1, 1, 1], "t": [0, 1, 0]}},
        {"parent": GEO, "type": "vellumsolver", "name": "vsolver",
         "inputs": [{"index": 0, "from": f"{GEO}/cloth_con"},
                    {"index": 1, "from": f"{GEO}/cloth_con", "output": 1},
                    {"index": 2, "from": f"{GEO}/collider"}]},
        {"parent": GEO, "type": "filecache::2.0", "name": "cache",
         "inputs": [{"index": 0, "from": f"{GEO}/vsolver"}],
         "parms": {"filemethod": "explicit", "file": rec.path("cache", "cloth.$F4.bgeo.sc"),
                   "trange": "normal", "f1": 1, "f2": FRAMES},
         "flags": {"display": True, "render": True}},
    ]  # fmt: skip
    built = rec.ok("edit", {"ops": creates(cloth)})
    assert node_problems(built) == [], built.data
    cached = rec.ok(
        "render",
        {"rop_path": f"{GEO}/cache", "frames": [1, FRAMES], "wait_s": 280},
        progress=True,
        timeout=300,
    )
    assert cached["state"] == "done", cached.data
    summary = cached["outputs_summary"]
    assert summary["count"] == FRAMES and summary["missing_count"] == 0, summary
    draped = rec.ok(
        "inspect",
        {"what": "geo", "target": f"{GEO}/cache", "frame": FRAMES, "attributes": "names"},
    )
    assert draped["point_count"] == 576, draped.data
    assert draped["bbox"]["min"][1] < 2.9, draped.data  # it fell

    # -- export to USD with the ROP's own frame range ----------------------------------
    export = [
        {"parent": "/stage", "type": "sopimport", "name": "cloth_import",
         "parms": {"soppath": f"{GEO}/cache", "pathprefix": "/cloth",
                   "savepath": rec.path("usd", "$OS.usd")}},
        {"parent": "/stage", "type": "usd_rop", "name": "export_usd",
         "inputs": [{"index": 0, "from": "/stage/cloth_import"}],
         "parms": {"lopoutput": rec.path("usd", "cloth_root.usd"), "trange": "normal",
                   "f1": 1, "f2": FRAMES}},
    ]  # fmt: skip
    rec.ok("edit", {"ops": creates(export)})
    exported = rec.ok("render", {"rop_path": "/stage/export_usd"}, timeout=240)
    assert exported["state"] == "done", exported.data
    assert exported["frames"] == [1, FRAMES, 1], exported.data
    layers = {Path(row["path"]).name: row for row in exported["layers"]}
    assert layers["cloth_import.usd"]["time_samples"] == FRAMES, exported["layers"]

    # -- read it back through a sublayer, then render frame 24 with Karma ------------
    reimport = [
        {"parent": "/stage", "type": "sublayer", "name": "reimport",
         "parms": {"filepath1": rec.path("usd", "cloth_root.usd")}},
        {"parent": "/stage", "type": "camera", "name": "cam",
         "inputs": [{"index": 0, "from": "/stage/reimport"}],
         "parms": {"t": [6, 4, 6], "r": [-25, 45, 0]}},
        {"parent": "/stage", "type": "distantlight::2.0", "name": "key",
         "inputs": [{"index": 0, "from": "/stage/cam"}],
         "parms": {"r": [-50, 30, 0]}},
        {"parent": "/stage", "type": "karmarendersettings", "name": "rset",
         "inputs": [{"index": 0, "from": "/stage/key"}],
         "parms": {"camera": "/cameras/cam", "resolutionx": 320, "samplesperpixel": 4,
                   "picture": rec.path("render", "karma.$F4.png")},
         "flags": {"display": True}},
        {"parent": "/stage", "type": "usdrender_rop", "name": "karma_rop",
         "inputs": [{"index": 0, "from": "/stage/rset"}]},
    ]  # fmt: skip
    rec.ok("edit", {"ops": creates(reimport)})
    stage = rec.ok(
        "inspect",
        {"what": "stage", "target": "/stage/reimport", "prim": "/cloth", "depth": 2,
         "include": ["attributes"], "attribs": "extent", "time": FRAMES},
    )  # fmt: skip
    text = json.dumps(stage.data)
    assert "/cloth/mesh_0" in text, stage.data
    assert f'"time_samples": {FRAMES}' in text, stage.data
    karma = rec.ok(
        "render", {"rop_path": "/stage/karma_rop", "frames": [FRAMES, FRAMES]}, timeout=300
    )
    assert karma["state"] == "done" and karma.images == 1, karma.data
    assert karma["thumbnail"]["width"] == 320 and karma["thumbnail"]["height"] == 180, karma.data
    rec.ok("inspect", {"what": "problems", "target": "/stage"})

    rec.finish({"progress_notifications": len(rec.progress)})
