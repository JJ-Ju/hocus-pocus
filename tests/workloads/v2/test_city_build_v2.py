"""Review 12's city rebuild on the 2.0 tools (the scene: ``city_scene.py``).

The same building generator and city, in three ``edit`` transactions instead of six
``node_create``/``node_edit``/``parm_set`` round trips: the two objects with their spare-parm
controls and the building core; the parapet roof with the building hidden; the city (lot
layout, for-each over the lots with the same core, ground, merge, comments, camera). Reads
are ``inspect`` and ``search``; ``look`` replaces ``viewport_capture``. Same outcomes.
"""

from __future__ import annotations

from typing import Any

import city_scene as w1
import pytest
from wl2 import creates, node_problems, rows_by_path

pytestmark = pytest.mark.timeout(300)

B, C = w1.B, w1.C


def _spare_parms() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roof_items = [
        {"token": "flat", "label": "Flat"},
        {"token": "parapet", "label": "Parapet"},
        {"token": "pyramid", "label": "Pyramid"},
    ]
    spare = w1._spare
    building = [
        spare("seed", "int", 7, "Building"),
        spare("width_min", "float", 12, "Building"),
        spare("width_max", "float", 40, "Building"),
        spare("floors_min", "int", 3, "Building"),
        spare("floors_max", "int", 40, "Building"),
        spare("floor_h", "float", 3.2, "Building"),
        spare("roof_type", "menu", "pyramid", "Building", menu_items=roof_items, value_type="int"),
    ]
    city = [
        spare("seed", "int", 42, "City"),
        spare("blocks", "int", 8, "City"),
        spare("block_size", "float", 40, "City"),
        spare("street_width", "float", 12, "City"),
        spare("sidewalk", "float", 3, "City"),
        spare("floor_h", "float", 3.2, "City"),
        spare("district_count", "int", 30, "City"),
    ]
    return building, city


def _city_items() -> list[dict[str, Any]]:
    """The 1.4 workload's 22 city nodes, plus the merge and OUT_CITY it made next."""
    node, wrangle = w1._node, w1._wrangle
    return [
        wrangle(C, "lot_layout", "detail", w1.LOT_LAYOUT),
        wrangle(C, "district_mark", "detail", w1.DISTRICT, "lot_layout"),
        node(C, "block_begin", "foreach_lot", "district_mark", method="piece"),
        node(C, "null", "LOT", "foreach_lot"),
        *w1._core(C, "LOT", 'point("../LOT", 0, "height_class", 0) > 0'),
        node(C, "block_end", "foreach_lot_end", "place_on_lot", itermethod="pieces",
             method="merge", useattrib=False, **{"class": "point"}),
        node(C, "null", "OUT_BUILDINGS", "foreach_lot_end"),
        wrangle(C, "block_points", "detail", w1.BLOCK_POINTS),
        node(C, "box", "sidewalk_slab",
             sizex={"expression": 'ch("../CONTROLS/block_size") + 2 * ch("../CONTROLS/sidewalk")'},
             sizey=0.3,
             sizez={"expression": 'ch("../CONTROLS/block_size") + 2 * ch("../CONTROLS/sidewalk")'},
             ty=0.15),
        node(C, "copytopoints", "sidewalks", "sidewalk_slab", "block_points"),
        node(C, "grid", "street_plane", sizex={"expression": w1.GRID_SIZE},
             sizey={"expression": w1.GRID_SIZE}, rows=2, cols=2),
        node(C, "merge", "ground_merge", "street_plane", "sidewalks"),
        wrangle(C, "ground_attrs", "primitive", w1.GROUND_ATTRS, "ground_merge"),
        node(C, "null", "OUT_GROUND", "ground_attrs"),
        node(C, "merge", "city_merge", "OUT_GROUND", "OUT_BUILDINGS"),
        {**node(C, "null", "OUT_CITY", "city_merge"), "flags": {"display": True, "render": True}},
    ]  # fmt: skip


def test_city_build(workload):
    rec = workload
    status = rec.ok("houdini_status")
    assert status["connected"] is not None

    # -- discovery: the one type the build needs to look up -------------------------------
    found = rec.ok("search", {"kind": "types", "query": "polyextrude", "category": "Sop",
                              "limit": 3})  # fmt: skip
    assert found["results"][0]["name"] == "polyextrude::2.0", found.data
    rec.ok(
        "inspect",
        {"what": "type", "target": "Sop/polyextrude::2.0", "parms": "group|splittype|inset|dist",
         "detail": "full"},
    )  # fmt: skip

    # -- 1. both objects, their controls, and the building core: one transaction ----------
    building, city = _spare_parms()
    objects = [
        {"parent": "/obj", "type": "geo", "name": "building_gen"},
        {"parent": B, "type": "null", "name": "CONTROLS"},
        {"parent": "/obj", "type": "geo", "name": "city_gen"},
        {"parent": C, "type": "null", "name": "CONTROLS"},
    ]
    core = [
        w1._wrangle(B, "lot_from_controls", "detail", w1.LOT_FROM_CONTROLS),
        w1._node(B, "null", "LOT", "lot_from_controls"),
        *w1._core(B, "LOT", 'ch("../CONTROLS/roof_type") > 0'),
        {**w1._node(B, "null", "OUT_BUILDING", "place_on_lot"),
         "flags": {"display": True, "render": True}},
    ]  # fmt: skip
    ops = creates(objects)
    ops += [
        {"op": "node", "path": "$building_gen_CONTROLS", "spare_parms": {"add": building}},
        {"op": "node", "path": "$city_gen_CONTROLS", "spare_parms": {"add": city}},
    ]
    ops += creates(core, known={B})
    built = rec.ok("edit", {"ops": ops})
    rows = rows_by_path(built)
    assert built["ids"]["building_gen_OUT_BUILDING"] == f"{B}/OUT_BUILDING", built.data
    assert len([p for p in rows if p.startswith(f"{B}/") and p != f"{B}/CONTROLS"]) == 12
    assert node_problems(built) == [], built.data
    geo = rec.ok("inspect", {"what": "geo", "target": f"{B}/OUT_BUILDING"})
    assert geo["prim_count"] > 100, geo.data
    assert "name" in str(geo["attributes"]["prim"])

    # -- 2. parapet roof, building hidden -------------------------------------------------
    parapet = rec.ok(
        "edit",
        {
            "ops": [
                {"op": "set", "path": f"{B}/CONTROLS/roof_type", "value": "parapet"},
                {"op": "node", "path": B, "flags": {"display": False}},
            ]
        },
    )
    # The spare menu exists (the set resolved it) and nothing complains.
    assert [r["path"] for r in parapet["nodes"]] == [f"{B}/CONTROLS", B], parapet.data
    assert node_problems(parapet) == [], parapet.data

    # -- 3. the city, its comments and the camera: one transaction ------------------------
    city_items = _city_items()
    assert len(city_items) == 24
    ops = creates(city_items)
    ops += [
        {"op": "node", "path": "$city_gen_OUT_CITY", "comment": "Final city: ground + buildings."},
        {"op": "node", "path": "$city_gen_lot_layout", "comment": "Lots per block; bldg_id per lot."},
        {"op": "node", "path": "$city_gen_foreach_lot", "comment": "One building per lot point."},
        {"op": "create", "parent": "/obj", "type": "cam", "name": "cam_overview",
         "parms": {"t": [280, 230, 280], "r": [-30, 45, 0], "resx": 960, "resy": 540}},
    ]  # fmt: skip
    city_built = rec.ok("edit", {"ops": ops})
    rows = rows_by_path(city_built)
    assert rows[f"{C}/foreach_lot_end"].get("paired_with") == f"{C}/foreach_lot", rows
    assert node_problems(city_built) == [], city_built.data

    # -- measure and inspect -------------------------------------------------------------
    profiled = rec.ok("cook", {"paths": [f"{C}/OUT_CITY"], "profile": True})
    assert profiled["total_ms"] > 0
    assert any("foreach_lot_end" in row["path"] for row in profiled["chain"]), profiled.data
    outline = rec.ok("inspect", {"what": "outline", "target": "/obj"})
    assert "OUT_CITY" in str(outline.data)
    problems = rec.ok("inspect", {"what": "problems", "target": "/obj", "cook_uncooked": True})
    assert problems["problems"] == [], problems.data
    lots = rec.ok(
        "inspect", {"what": "geo", "target": f"{C}/district_mark", "attributes": "names"}
    )["point_count"]
    assert 128 <= lots <= 256, lots
    city_geo = rec.ok("inspect", {"what": "geo", "target": f"{C}/OUT_CITY"})
    prim_attrs = str(city_geo["attributes"]["prim"])
    for attr in ("bldg_id", "height_class", "district", "name"):
        assert attr in prim_attrs, prim_attrs
    stats = rec.ok(
        "inspect",
        {"what": "geo", "target": f"{C}/OUT_CITY", "rows": True, "class": "prim",
         "attribs": ["bldg_id", "district"], "count": 1, "stats": True},
    )  # fmt: skip
    bldg = stats["stats"]["bldg_id"]
    assert bldg["max"] == lots - 1 and bldg["min"] == -1, stats.data

    # -- one look ------------------------------------------------------------------------
    look = rec.ok("look", {"camera": "/obj/cam_overview", "resolution": [960, 540]}, timeout=180)
    assert look.images == 1 and look["width"] == 960, look.data
    saved = rec.ok("hip_save", {"path": rec.path("city_v01.hip")})
    assert saved["dirty"] is False

    rec.finish({"buildings": lots})
