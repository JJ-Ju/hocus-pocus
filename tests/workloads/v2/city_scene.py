"""Review 12's building generator and city: the VEX, the node builders and the spare-parm
rows ``test_city_build_v2.py`` assembles into ``edit`` ops (not a test module). Until 2.1
they lived in the 1.4 workload ``tests/workloads/test_city_build.py``.
"""

from __future__ import annotations

from typing import Any

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


GRID_SIZE = (
    'ch("../CONTROLS/blocks") * (ch("../CONTROLS/block_size") + ch("../CONTROLS/street_width"))'
    ' + ch("../CONTROLS/street_width")'
)
