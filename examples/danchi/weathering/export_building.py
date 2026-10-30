#!/usr/bin/env hython
"""export_building.py - building description and decal meshes of the danchi asset, no rendering.

  hython export_building.py <out_dir>

Writes into <out_dir>:
  building/building_<cfg>.npz   every paint_ext / coping / soffit / concrete primitive of the cooked LOD0
                                geometry (cfg = typical: the asset default preset; new: no chips)
  building/building.json        plan detail attributes, asset constants (from the HDA's own VEX), legend
  <config>/decals.npz           the decal quads of every capture config (positions, uv, vertex Cd/Alpha, layer...)
  <config>/decals.json          counts and the per-config weathering detail values (patches, causes)
  _shared/weather_atlas.png/.json   the decal alpha atlas the decal uv point into (copied from tex/)
Same scene handling as elevation_capture.py (hip loaded read-only, hocus-pocus library, LOD0,
props and interior cards off for the weathering configs as in the captures).
"""
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hou
import numpy as np
import elevation_capture as ec

WALL = ["paint_ext", "coping", "soffit", "concrete"]
PRIM_INT = ["side", "floor", "bay", "unit", "gable", "tower", "fresh", "variant", "pane", "persona", "lod"]
PRIM_STR = ["role", "name", "cdkey"]
DECAL_INT = ["wlayer", "dlod", "side", "floor", "bay", "fresh", "gable", "tower"]
DECAL_FLOAT = ["dstr"]
LAYERS = {0: "stain field", 1: "soot cloud", 2: "growth", 3: "splash", 4: "inside-corner grime", 5: "streak",
          6: "rust", 7: "efflorescence", 8: "worn edge"}


def export_node():
    obj = hou.node("/obj")
    g = obj.node("elev_export") or obj.createNode("geo", "elev_export")
    for c in g.children():
        c.destroy()
    om = g.createNode("object_merge", "in")
    om.parm("objpath1").set(ec.ASSET + "/build/OUT")
    om.parm("xformtype").set(1)
    w = g.createNode("attribwrangle", "vtx_pos")
    w.parm("class").set(3)                       # vertices: copy the point position onto each vertex
    w.parm("snippet").set('v@vP = point(0, "P", @ptnum);')
    w.setInput(0, om)
    o = g.createNode("null", "OUT")
    o.setInput(0, w)
    o.setDisplayFlag(True)
    return o


def prim_arrays(geo, keep_mask, names_int, names_float=(), names_str=()):
    prims = geo.prims()
    counts = np.array([p.numVertices() for p in prims], dtype=np.int64)
    vstart = np.concatenate([[0], np.cumsum(counts)])
    sel = np.nonzero(keep_mask)[0]
    vP = np.array(geo.vertexFloatAttribValues("vP"), dtype=np.float32).reshape(-1, 3)
    vidx = np.concatenate([np.arange(vstart[i], vstart[i + 1]) for i in sel]) if len(sel) else np.zeros(0, np.int64)
    out = {"prim_num": sel.astype(np.int32), "points": vP[vidx],
           "offsets": np.concatenate([[0], np.cumsum(counts[sel])]).astype(np.int64)}
    pa = {a.name(): a for a in geo.primAttribs()}
    for nm in names_int:
        if nm in pa:
            out[nm] = np.array(geo.primIntAttribValues(nm), dtype=np.int32)[sel]
    for nm in names_float:
        if nm in pa:
            out[nm] = np.array(geo.primFloatAttribValues(nm), dtype=np.float32)[sel]
    for nm in names_str:
        if nm in pa:
            out[nm] = np.array(geo.primStringAttribValues(nm))[sel]
    return out, vidx


def prim_normals(geo, sel):
    prims = geo.prims()
    return np.array([tuple(prims[i].normal()) for i in sel], dtype=np.float32)


def detail(geo):
    out = {}
    for a in geo.globalAttribs():
        v = geo.attribValue(a.name())
        if isinstance(v, tuple):
            v = list(v)
        out[a.name()] = v
    return out


def constants():
    """#define constants: from the HDA's own wrangle snippet (what the asset cooks with) and lib.vfl."""
    sn = hou.node(ec.ASSET + "/build/plan").parm("snippet").eval()
    hda = {k: float(v) for k, v in re.findall(r"#define\s+([A-Z_][A-Z0-9_]*)\s+([-+\d.eE]+)\s*$", sn, re.M)}
    lib = open(ec.REPO_DANCHI + "/src/vex/lib.vfl", encoding="utf-8").read()
    repo = {k: float(v) for k, v in re.findall(r"#define\s+([A-Z_][A-Z0-9_]*)\s+([-+\d.eE]+)\s*$", lib, re.M)}
    return hda, repo


def main():
    out = sys.argv[1].replace("\\", "/")
    t0 = time.time()
    ec.load_scene()
    o = export_node()
    cfg = ec.config_table()
    os.makedirs(out + "/building", exist_ok=True)
    os.makedirs(out + "/_shared", exist_ok=True)
    for f in ("weather_atlas.png", "weather_atlas.json"):
        shutil.copy2(ec.TEXCOPY + "/" + f, out + "/_shared/" + f)
    # ---- building description ----
    hda_c, repo_c = constants()
    desc = {"asset": ec.TYPE, "library": ec.LIB, "instance": ec.ASSET,
            "building": "10 floors x 12 units, seed 1 (the showcase instance), LOD0, props and interior cards off",
            "constants_from_hda_vex": hda_c, "constants_from_repo_lib_vfl": repo_c,
            "constants_match": all(repo_c.get(k) == v for k, v in hda_c.items()),
            "material_index_legend": {str(i): c for i, c in enumerate(ec.CLASSES)},
            "npz": {"prim_num": "primitive number in the cooked OUT geometry", "mat_index": "index into the legend "
                    "(same numbers as class.png)", "normal": "geometric primitive normal (float32 x3)",
                    "points": "float32 (n_vertices, 3) world vertex positions of the selected prims, concatenated",
                    "offsets": "int64 (n_prims+1): prim i uses points[offsets[i]:offsets[i+1]] (polygon order)",
                    "area": "polygon area m^2", "vtx_cd": "float16 baked vertex colour (linear) per vertex, same "
                    "order as points", "side/floor/bay/...": "the asset's prim attributes (plan attributes, README)",
                    "role/name/cdkey": "prim string attributes"},
            "configs": {}}
    for cname in ("preset_typical", "clean"):
        ec.set_parms(cfg[cname]["values"], False)
        g = o.geometry()
        mats = np.array(g.primStringAttribValues("mat"))
        keep = np.isin(mats, WALL)
        arr, vidx = prim_arrays(g, keep, PRIM_INT, (), PRIM_STR)
        sel = arr["prim_num"]
        arr["mat_index"] = np.array([ec.CLASSES.index(m) for m in mats[sel]], dtype=np.int8)
        arr["normal"] = prim_normals(g, sel)
        prims = g.prims()
        arr["area"] = np.array([prims[i].intrinsicValue("measuredarea") for i in sel], dtype=np.float32)
        vcd = np.array(g.vertexFloatAttribValues("Cd"), dtype=np.float32).reshape(-1, 3)
        arr["vtx_cd"] = vcd[vidx].astype(np.float16)
        tag = "typical" if cname == "preset_typical" else "new"
        np.savez_compressed(out + "/building/building_%s.npz" % tag, **arr)
        plan = detail(hou.node(ec.ASSET + "/build/plan").geometry())
        desc["plan"] = {k: plan[k] for k in ("floors", "units", "L", "x0", "ytop", "H", "W", "bay_x", "bay_w", "bay_t",
                                             "main_core", "has_lift", "ncores", "bay_core") if k in plan}
        desc["plan_all"] = plan
        wp = detail(hou.node(ec.ASSET + "/build/weather_params").geometry())
        desc["configs"][tag] = {"from_config": cname, "file": "building_%s.npz" % tag, "prims": int(len(sel)),
                                "by_material": {m: int((mats[sel] == m).sum()) for m in WALL},
                                "bbox": ec.geo_bbox("/obj/elev_export"),
                                "weather_params": {k: v for k, v in wp.items() if k.startswith(("w_", "p_"))}}
        ec.log("building", tag, len(sel), "prims")
    desc["plan_notes"] = ("x0 = west end of the slab (x of the first bay's left edge), L = slab length, bay_x = bay "
                          "centres, bay_w = bay widths, bay_t = bay type (0 unit, 1 stair core 3.0 m, 2 stair+lift "
                          "core 5.5 m), bay_core = core index per bay, ytop = roof slab top, H = floor height, "
                          "W = unit bay width. Balconies face +Z, corridors -Z (README contract).")
    json.dump(desc, open(out + "/building/building.json", "w"), indent=1)
    # ---- decals per config ----
    for cname, c in cfg.items():
        ec.set_parms(c["values"], c["dressing"])
        g = o.geometry()
        mats = np.array(g.primStringAttribValues("mat"))
        keep = mats == "decal"
        arr, vidx = prim_arrays(g, keep, DECAL_INT, DECAL_FLOAT, ("cdkey",))
        n = len(arr["prim_num"])
        if n:
            uv = np.array(g.vertexFloatAttribValues("uv"), dtype=np.float32).reshape(-1, 3)[vidx, :2]
            cd = np.array(g.vertexFloatAttribValues("Cd"), dtype=np.float32).reshape(-1, 3)[vidx]
            al = np.array(g.vertexFloatAttribValues("Alpha"), dtype=np.float32)[vidx]
            arr.update(uv=uv, Cd=cd, Alpha=al, normal=prim_normals(g, arr["prim_num"]))
        d = out + "/" + cname
        os.makedirs(d, exist_ok=True)
        np.savez_compressed(d + "/decals.npz", **arr)
        wp = detail(hou.node(ec.ASSET + "/build/causes").geometry())
        cnt = np.bincount(arr.get("wlayer", np.zeros(0, np.int32)), minlength=9).tolist() if n else [0] * 9
        nv = np.diff(arr["offsets"]).tolist() if n else []
        json.dump({"config": cname, "decal_quads": n, "vertices_per_prim": sorted(set(nv)),
                   "by_layer": {LAYERS[i]: cnt[i] for i in range(9)}, "layer_legend": LAYERS,
                   "npz": {"points/offsets": "as building npz (quads: 4 vertices each)", "uv": "vertex uv into "
                           "_shared/weather_atlas.png (opacity = atlas R x Alpha)", "Cd": "vertex colour (linear)",
                           "Alpha": "vertex alpha (decal opacity scale)", "wlayer": "layer (legend)",
                           "dstr": "decal strength before the bake", "dlod": "1 = kept in LOD1",
                           "normal": "quad normal", "cdkey": "colour key"},
                   "decal_offset_note": "quads sit 4 mm + 0.7 mm x layer off their face (decals.vfl dq1)",
                   "weather_detail": {k: v for k, v in wp.items() if k.startswith(("w_", "p_", "cause_"))}},
                  open(d + "/decals.json", "w"), indent=1)
        ec.log("decals", cname, n)
    ec.log("export done %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
