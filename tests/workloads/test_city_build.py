"""Review 12 (city rebuild on 1.1) as a workload.

A procedural building generator whose controls are spare parms added by ``node_edit
spare_parms``, then a city: a lot layout, a for-each loop over the lots that runs the same
building core, and the ground, in one ``node_create``. ``OUT_CITY`` merges them; a
profiled ``cook`` attributes the cost to the loop; one ``viewport_capture`` looks at it.
No ``houdini_python``.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.timeout(300)

B = "/obj/building_gen"
C = "/obj/city_gen"

FIT_LOT = """\
float w = point(1, "lot_w", 0);
float d = point(1, "lot_d", 0);
int floors = point(1, "floors", 0);
float h = floors * ch("../CONTROLS/floor_h");
@P = set(@P.x * w, (@P.y + 0.5) * h, @P.z * d);
"""

TAG_FACES = """\
vector n = prim_normal(0, @primnum, 0.5, 0.5);
i@group_roof = n.y > 0.5;
i@group_base = n.y < -0.5;
i@group_facade = abs(n.y) <= 0.5;
"""

BUILDING_ATTRS = """\
int id = point(1, "bldg_id", 0);
i@bldg_id = id;
i@height_class = point(1, "height_class", 0);
i@district = point(1, "district", 0);
s@name = sprintf("bldg_%d", id);
v@Cd = set(0.55, 0.55, 0.6) + 0.15 * i@height_class;
"""

LOT_FROM_CONTROLS = """\
int seed = chi("../CONTROLS/seed");
float wmin = ch("../CONTROLS/width_min");
float wmax = ch("../CONTROLS/width_max");
int pt = addpoint(0, {0, 0, 0});
setpointattrib(0, "lot_w", pt, fit01(rand(seed + 0.1), wmin, wmax));
setpointattrib(0, "lot_d", pt, fit01(rand(seed + 0.2), wmin, wmax));
int fmin = chi("../CONTROLS/floors_min");
int fmax = chi("../CONTROLS/floors_max");
setpointattrib(0, "floors", pt, int(fit01(rand(seed + 0.3), fmin, fmax + 0.999)));
setpointattrib(0, "bldg_id", pt, 0);
setpointattrib(0, "height_class", pt, 1);
setpointattrib(0, "district", pt, 0);
"""

LOT_LAYOUT = """\
int blocks = chi("../CONTROLS/blocks");
float bs = ch("../CONTROLS/block_size");
float pitch = bs + ch("../CONTROLS/street_width");
int seed = chi("../CONTROLS/seed");
float half = 0.5 * pitch * blocks;
float off = -0.5 * pitch * (blocks - 1);
int id = 0;
for (int bx = 0; bx < blocks; bx++) {
    for (int bz = 0; bz < blocks; bz++) {
        vector c = set(off + bx * pitch, 0, off + bz * pitch);
        float r = rand(set(bx, bz, seed));
        int lots = r < 0.45 ? 2 : (r < 0.85 ? 3 : 4);
        float w = bs / lots;
        float dist = length(c) / half;
        int hc = dist < 0.35 ? 2 : (dist < 0.7 ? 1 : 0);
        for (int i = 0; i < lots; i++) {
            int pt = addpoint(0, c + set(-0.5 * bs + w * (i + 0.5), 0, 0));
            setpointattrib(0, "bldg_id", pt, id);
            setpointattrib(0, "lot_w", pt, w * 0.8);
            setpointattrib(0, "lot_d", pt, bs * 0.8);
            setpointattrib(0, "height_class", pt, hc);
            setpointattrib(0, "floors", pt, int(fit01(rand(id + seed * 7.13), 2, 6)) + hc * 6);
            setpointattrib(0, "district", pt, 0);
            id++;
        }
    }
}
"""

DISTRICT = """\
int near[] = nearpoints(0, {0, 0, 0}, 1e9, chi("../CONTROLS/district_count"));
foreach (int p; near) setpointattrib(0, "district", p, 1);
"""

BLOCK_POINTS = """\
int blocks = chi("../CONTROLS/blocks");
float pitch = ch("../CONTROLS/block_size") + ch("../CONTROLS/street_width");
float off = -0.5 * pitch * (blocks - 1);
for (int bx = 0; bx < blocks; bx++)
    for (int bz = 0; bz < blocks; bz++)
        addpoint(0, set(off + bx * pitch, 0, off + bz * pitch));
"""

GROUND_ATTRS = """\
s@name = "ground";
i@bldg_id = -1;
i@height_class = 0;
i@district = 0;
v@Cd = {0.3, 0.3, 0.32};
"""


def _wrangle(parent: str, name: str, cls: str, snippet: str, *inputs: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "parent": parent,
        "type": "attribwrangle",
        "name": name,
        "parms": {"class": cls, "snippet": snippet},
    }
    if inputs:
        item["inputs"] = [{"index": i, "from": f"{parent}/{src}"} for i, src in enumerate(inputs)]
    return item


def _node(parent: str, type_: str, name: str, *inputs: str, **parms: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"parent": parent, "type": type_, "name": name}
    if inputs:
        item["inputs"] = [{"index": i, "from": f"{parent}/{src}"} for i, src in enumerate(inputs)]
    if parms:
        item["parms"] = parms
    return item


def _core(parent: str, lot: str, roof_expr: str) -> list[dict[str, Any]]:
    """The building core: a box fitted to the lot, windows, roof, attributes, placed."""
    return [
        _node(parent, "box", "mass", type="polymesh", divrate=[4, 4, 4]),
        _wrangle(parent, "fit_lot", "point", FIT_LOT, "mass", lot),
        _wrangle(parent, "tag_faces", "primitive", TAG_FACES, "fit_lot"),
        _node(
            parent,
            "polyextrude::2.0",
            "windows",
            "tag_faces",
            group="facade",
            splittype="elements",
            inset=0.4,
            dist=-0.3,
        ),
        _node(
            parent, "polyextrude::2.0", "roof_base", "windows", group="roof", inset=1.0, dist=2.0
        ),
        _node(
            parent, "switch", "roof_switch", "windows", "roof_base", input={"expression": roof_expr}
        ),
        _wrangle(parent, "building_attrs", "primitive", BUILDING_ATTRS, "roof_switch", lot),
        _node(parent, "groupdelete", "clean_groups", "building_attrs", group1="facade roof base"),
        _wrangle(parent, "place_on_lot", "point", 'v@P += point(1, "P", 0);', "clean_groups", lot),
    ]


def _spare(name: str, type_: str, default: Any, folder: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": type_, "label": name.replace("_", " ").title(), "default": default,
            "folder": folder, **extra}  # fmt: skip


def test_city_build(workload):
    rec = workload
    status = rec.ok("houdini_status")
    assert status["profile"] == "full"

    # -- discovery: the one type the build needs to look up -------------------------------
    found = rec.ok("node_type_search", {"query": "polyextrude", "category": "Sop", "limit": 3})
    assert found["results"][0]["name"] == "polyextrude::2.0", found.data
    rec.ok(
        "node_type_info",
        {"type": "Sop/polyextrude::2.0", "parms": "group|splittype|inset|dist", "detail": "full"},
    )

    # -- the two objects and their controls ------------------------------------------------
    rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "building_gen"},
                {"parent": B, "type": "null", "name": "CONTROLS"},
                {"parent": "/obj", "type": "geo", "name": "city_gen"},
                {"parent": C, "type": "null", "name": "CONTROLS"},
            ]
        },
    )
    roof_items = [
        {"token": "flat", "label": "Flat"},
        {"token": "parapet", "label": "Parapet"},
        {"token": "pyramid", "label": "Pyramid"},
    ]
    building = [
        _spare("seed", "int", 7, "Building"),
        _spare("width_min", "float", 12, "Building"),
        _spare("width_max", "float", 40, "Building"),
        _spare("floors_min", "int", 3, "Building"),
        _spare("floors_max", "int", 40, "Building"),
        _spare("floor_h", "float", 3.2, "Building"),
        _spare("roof_type", "menu", "pyramid", "Building", menu_items=roof_items, value_type="int"),
    ]
    city = [
        _spare("seed", "int", 42, "City"),
        _spare("blocks", "int", 8, "City"),
        _spare("block_size", "float", 40, "City"),
        _spare("street_width", "float", 12, "City"),
        _spare("sidewalk", "float", 3, "City"),
        _spare("floor_h", "float", 3.2, "City"),
        _spare("district_count", "int", 30, "City"),
    ]
    spare = rec.ok(
        "node_edit",
        {
            "items": [
                {"path": f"{B}/CONTROLS", "spare_parms": {"add": building}},
                {"path": f"{C}/CONTROLS", "spare_parms": {"add": city}},
            ]
        },
    )
    assert "roof_type" in str(spare.data) and "district_count" in str(spare.data), spare.data

    # -- building generator: the core in one batch ---------------------------------------
    built = rec.ok(
        "node_create",
        {
            "items": [
                _wrangle(B, "lot_from_controls", "detail", LOT_FROM_CONTROLS),
                _node(B, "null", "LOT", "lot_from_controls"),
                *_core(B, "LOT", 'ch("../CONTROLS/roof_type") > 0'),
                {
                    **_node(B, "null", "OUT_BUILDING", "place_on_lot"),
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    assert len(built["results"]) == 12
    assert all(not row.get("errors") for row in built["results"]), built.data
    geo = rec.ok("geo_info", {"path": f"{B}/OUT_BUILDING"})
    assert geo["prim_count"] > 100, geo.data
    assert "name" in str(geo["attributes"]["prim"])
    parapet = rec.ok(
        "parm_set", {"items": [{"path": f"{B}/CONTROLS/roof_type", "value": "parapet"}]}
    )
    assert parapet["results"][0]["value"] in ("parapet", 1), parapet.data
    rec.ok("node_edit", {"items": [{"path": B, "flags": {"display": False}}]})

    # -- the city: layout, for-each over the lots with the same core, ground -------------
    city_items = [
        _wrangle(C, "lot_layout", "detail", LOT_LAYOUT),
        _wrangle(C, "district_mark", "detail", DISTRICT, "lot_layout"),
        _node(C, "block_begin", "foreach_lot", "district_mark", method="piece"),
        _node(C, "null", "LOT", "foreach_lot"),
        *_core(C, "LOT", 'point("../LOT", 0, "height_class", 0) > 0'),
        _node(
            C,
            "block_end",
            "foreach_lot_end",
            "place_on_lot",
            itermethod="pieces",
            method="merge",
            useattrib=False,
            **{"class": "point"},
        ),
        _node(C, "null", "OUT_BUILDINGS", "foreach_lot_end"),
        _wrangle(C, "block_points", "detail", BLOCK_POINTS),
        _node(
            C,
            "box",
            "sidewalk_slab",
            sizex={"expression": 'ch("../CONTROLS/block_size") + 2 * ch("../CONTROLS/sidewalk")'},
            sizey=0.3,
            sizez={"expression": 'ch("../CONTROLS/block_size") + 2 * ch("../CONTROLS/sidewalk")'},
            ty=0.15,
        ),
        _node(C, "copytopoints", "sidewalks", "sidewalk_slab", "block_points"),
        _node(
            C,
            "grid",
            "street_plane",
            sizex={"expression": GRID_SIZE},
            sizey={"expression": GRID_SIZE},
            rows=2,
            cols=2,
        ),
        _node(C, "merge", "ground_merge", "street_plane", "sidewalks"),
        _wrangle(C, "ground_attrs", "primitive", GROUND_ATTRS, "ground_merge"),
        _node(C, "null", "OUT_GROUND", "ground_attrs"),
    ]
    assert len(city_items) == 22
    city_built = rec.ok("node_create", {"items": city_items})
    rows = {row["path"]: row for row in city_built["results"]}
    assert rows[f"{C}/foreach_lot_end"].get("paired_with") == f"{C}/foreach_lot", rows
    assert all(not row.get("errors") for row in city_built["results"]), city_built.data

    rec.ok(
        "node_create",
        {
            "items": [
                _node(C, "merge", "city_merge", "OUT_GROUND", "OUT_BUILDINGS"),
                {
                    **_node(C, "null", "OUT_CITY", "city_merge"),
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    rec.ok(
        "node_edit",
        {
            "items": [
                {"path": f"{C}/OUT_CITY", "comment": "Final city: ground + buildings."},
                {"path": f"{C}/lot_layout", "comment": "Lots per block; bldg_id per lot."},
                {"path": f"{C}/foreach_lot", "comment": "One building per lot point."},
            ]
        },
    )

    # -- measure and inspect -------------------------------------------------------------
    profiled = rec.ok("cook", {"paths": [f"{C}/OUT_CITY"], "profile": True})
    assert profiled["total_ms"] > 0
    assert any("foreach_lot_end" in row["path"] for row in profiled["chain"]), profiled.data
    outline = rec.ok("network_describe", {"root": "/obj", "format": "outline"})
    assert "OUT_CITY" in str(outline.data)
    problems = rec.ok("problems", {"root": "/obj", "cook_uncooked": True})
    assert problems["problems"] == [], problems.data
    lots = rec.ok("geo_info", {"path": f"{C}/district_mark", "attributes": "names"})["point_count"]
    assert 128 <= lots <= 256, lots
    city_geo = rec.ok("geo_info", {"path": f"{C}/OUT_CITY"})
    prim_attrs = str(city_geo["attributes"]["prim"])
    for attr in ("bldg_id", "height_class", "district", "name"):
        assert attr in prim_attrs, prim_attrs
    stats = rec.ok(
        "geo_read",
        {"path": f"{C}/OUT_CITY", "class": "prim", "attribs": ["bldg_id", "district"],
         "count": 1, "stats": True},
    )  # fmt: skip
    bldg = stats["stats"]["bldg_id"]
    assert bldg["max"] == lots - 1 and bldg["min"] == -1, stats.data

    # -- one look ------------------------------------------------------------------------
    rec.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": "/obj",
                    "type": "cam",
                    "name": "cam_overview",
                    "parms": {"t": [280, 230, 280], "r": [-30, 45, 0], "resx": 960, "resy": 540},
                }
            ]
        },
    )
    look = rec.ok(
        "viewport_capture", {"camera": "/obj/cam_overview", "resolution": [960, 540]}, timeout=180
    )
    assert look.images == 1 and look["width"] == 960, look.data
    saved = rec.ok("hip_save", {"path": rec.path("city_v01.hip")})
    assert saved["dirty"] is False

    rec.finish({"buildings": lots})


GRID_SIZE = (
    'ch("../CONTROLS/blocks") * (ch("../CONTROLS/block_size") + ch("../CONTROLS/street_width"))'
    ' + ch("../CONTROLS/street_width")'
)
