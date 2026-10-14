"""Review 24 (Vellum cloth and USD round trip on 1.4) as a workload, smaller.

A 24×24 cloth pinned at two corners falls onto a sphere (Vellum), cached for 24 frames by
``render`` on a ``filecache::2.0`` as a job. The cache goes to USD through ``sopimport``
and a ``usd_rop`` exported by ``render`` (its own frame range, one call), comes back
through a ``sublayer``, is checked with ``usd_stage`` for 24 time samples, and frame 24 is
rendered with Karma at 320×180. Every file is deleted afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(420)

GEO = "/obj/cloth"
FRAMES = 24


def test_vellum_usd(workload):
    rec = workload
    found = rec.ok("node_type_search", {"query": "vellum", "category": "Sop", "limit": 10})
    names = [row["name"] for row in found["results"]]
    assert "vellumsolver" in str(names) and "vellumconstraints" in str(names), names
    rec.ok("node_type_info", {"type": "Sop/vellumconstraints", "parms": "constrainttype|pin*"})

    # -- the cloth, simulated and cached as a job --------------------------------------
    built = rec.ok(
        "node_create",
        {
            "items": [
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
            ]
        },
    )  # fmt: skip
    assert all(not row.get("errors") for row in built["results"]), built.data
    started = rec.ok("render", {"rop_path": f"{GEO}/cache", "frames": [1, FRAMES], "wait_s": 0})
    assert rec.wait_job(started["job_id"], timeout_s=300)["state"] == "done"
    cached = rec.ok("job", {"action": "result", "job_id": started["job_id"]})
    summary = cached.get("result", cached.data)["outputs_summary"]
    assert summary["count"] == FRAMES and summary["missing_count"] == 0, summary
    draped = rec.ok("geo_info", {"path": f"{GEO}/cache", "frame": FRAMES, "attributes": "names"})
    assert draped["point_count"] == 576, draped.data
    assert draped["bbox"]["min"][1] < 2.9, draped.data  # it fell

    # -- export to USD with the ROP's own frame range ----------------------------------
    rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/stage", "type": "sopimport", "name": "cloth_import",
                 "parms": {"soppath": f"{GEO}/cache", "pathprefix": "/cloth",
                           "savepath": rec.path("usd", "$OS.usd")}},
                {"parent": "/stage", "type": "usd_rop", "name": "export_usd",
                 "inputs": [{"index": 0, "from": "/stage/cloth_import"}],
                 "parms": {"lopoutput": rec.path("usd", "cloth_root.usd"), "trange": "normal",
                           "f1": 1, "f2": FRAMES}},
            ]
        },
    )  # fmt: skip
    exported = rec.ok("render", {"rop_path": "/stage/export_usd"}, timeout=240)
    assert exported["state"] == "done", exported.data
    assert exported["frames"] == [1, FRAMES, 1], exported.data
    layers = {Path(row["path"]).name: row for row in exported["layers"]}
    assert layers["cloth_import.usd"]["time_samples"] == FRAMES, exported["layers"]

    # -- read it back through a sublayer, then render frame 24 with Karma ------------
    rec.ok(
        "node_create",
        {
            "items": [
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
            ]
        },
    )  # fmt: skip
    tree = rec.ok("usd_stage", {"lop_path": "/stage/reimport", "prim": "/cloth", "depth": 2})
    assert "/cloth/mesh_0" in str(tree.data), tree.data
    stage = rec.ok(
        "usd_stage",
        {"lop_path": "/stage/reimport", "prim": "/cloth/mesh_0", "include": ["attributes"],
         "attribs": "extent", "time": FRAMES},
    )  # fmt: skip
    assert f'"time_samples": {FRAMES}' in _json(stage.data), stage.data
    karma = rec.ok("render", {"rop_path": "/stage/karma_rop", "frames": [FRAMES, FRAMES]},
                   timeout=300)  # fmt: skip
    assert karma["state"] == "done" and karma.images == 1, karma.data
    assert karma["thumbnail"]["width"] == 320 and karma["thumbnail"]["height"] == 180, karma.data
    rec.ok("problems", {"root": "/stage"})

    rec.finish()


def _json(data: dict) -> str:
    import json

    return json.dumps(data)
