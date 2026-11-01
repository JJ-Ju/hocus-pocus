"""run_proto.py - generate weathering for the stand-in planes, write gate folders and previews.

python -I run_proto.py <out_dir> <preset|custom> [--age A --upkeep U] [--override layer=value ...]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts", "weathering"))
import facade_synth as fs  # noqa: E402
import weather_fields as wf  # noqa: E402
import weather_measure as wm  # noqa: E402

from weather_fields import TEXDIR as TEX  # noqa: E402
# (age, upkeep). Round H: the user's rename. Kept is new, between New and Typical; Typical (35 years,
# ordinary upkeep) has round G's Kept look, Worn round G's Typical, Derelict round G's Worn (soiling clock)
PRESETS = {"new": (0, 1.0), "kept": (10, 1.0), "typical": (35, 0.9), "worn": (35, 0.5), "derelict": (45, 0.12)}
PAINT = np.array([0.62, 0.60, 0.555])
CONCRETE = np.array([0.30, 0.29, 0.27])
COPING = np.array([0.58, 0.57, 0.53])

_tile_cache = {}


def tile_rgb(name, tile_m, ppm):
    k = (name, ppm)
    if k not in _tile_cache:
        im = Image.open(os.path.join(TEX, name)).convert("RGB")
        n = max(8, int(round(tile_m * ppm)))
        im = im.resize((n, n), Image.BOX)
        a = wm.srgb_to_linear(np.asarray(im, np.float64))
        _tile_cache[k] = a / a.reshape(-1, 3).mean(0)
    return _tile_cache[k]


def base_albedo(plane):
    H, W = plane["mask"].shape
    ppm = plane["ppm"]
    coat = tile_rgb("spraymacro_basecolor.png", 3.6, ppm)
    try:
        formed = tile_rgb("formed_basecolor.png", 3.6, ppm)
    except FileNotFoundError:                 # not shipped (15.7 MB): the coat stands in
        formed = coat
    n = coat.shape[0]
    yy = (np.arange(H) % n)[:, None]
    xx = (np.arange(W) % n)[None, :]
    c = coat[yy, xx]
    f = formed[(np.arange(H) % formed.shape[0])[:, None], (np.arange(W) % formed.shape[0])[None, :]]
    rgb = PAINT[None, None, :] * c
    cls = plane["cls"]
    rgb[cls == 5] = (CONCRETE[None, None, :] * f)[cls == 5]
    rgb[cls == 2] = (COPING[None, None, :] * c)[cls == 2]
    rgb[~plane["mask"]] = 0.0
    return rgb


def to_srgb8(lin):
    a = np.clip(lin, 0, 1)
    s = np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def src_map(plane, out):
    s = plane["tops"].copy()
    if plane.get("bottoms") is not None:
        s |= plane["bottoms"]                     # drip lines under ledges and slabs (G1)
    cls = plane.get("cls")
    if cls is not None:                           # the drip edge under any object above the wall
        wall = np.isin(cls, (1, 2, 4, 5))
        s[1:] |= wall[1:] & ~wall[:-1] & (cls[:-1] > 0)
    for (y, x) in wf.joint_crossings(plane):      # crossing runs start where joints cross
        if 0 <= y < s.shape[0] and 0 <= x < s.shape[1]:
            s[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
    for key in ("sill_ends", "corner_heads"):
        for (y, x) in plane.get(key, []):
            if 0 <= y < s.shape[0] and 0 <= x < s.shape[1]:
                s[y, x] = True
    for (y, x, _k) in plane.get("fixings", []):
        if 0 <= y < s.shape[0] and 0 <= x < s.shape[1]:
            s[y, x] = True
    for (y, x) in plane.get("joints", []):
        if 0 <= y < s.shape[0] and 0 <= x < s.shape[1]:
            s[y, x] = True
    for m in out["marks"].get("damage", []):
        y, x = m["y"], m["x"]
        if 0 <= y < s.shape[0] and 0 <= x < s.shape[1]:
            s[y, x] = True
    return s


def default_planes():
    return [fs.gable(), fs.front(side="S"), fs.front(side="N")]


def run(out_dir, cfg, planes=None, preview=True, fixed_gains=None, bases=None):
    t0 = time.time()
    planes = planes or default_planes()
    os.makedirs(out_dir, exist_ok=True)
    if bases is None:
        bases = {p["name"]: base_albedo(p).astype(np.float32) for p in planes}
    # the coat's own clouding (more with each repaint) and the joint lines, in the clean albedo
    import material as mt
    nrep = mt.repaints(cfg.get("age", 0), cfg.get("upkeep", 1.0))
    bases = dict(bases)
    for p in planes:
        p["coat_cloud"] = mt.coat_cloud(p["mask"].shape, p["ppm"], ("coat", cfg.get("seed", 1), p["name"]), nrep)
        paint = p["mask"] & np.isin(p["cls"], (1, 2))
        if p.get("decal") is not None:
            paint = paint & ~p["decal"]
        f = p["coat_cloud"]
        if p.get("joint_h") is not None:
            f = f * mt.joint_tone(p["joint_h"], p["joint_v"])
        bases[p["name"]] = np.where(paint[..., None], bases[p["name"]] * f[..., None], bases[p["name"]]).astype(np.float32)
    b = wf.Builder(planes, cfg, bases)
    log = []
    gs, ga, out = b.solve(log, fixed_gains=fixed_gains)
    meta = {"config": dict(cfg, E=b.E, R=b.R), "planes": {}, "gains": {"soiling": gs, "accent": ga, "film_k": b.k},
            "coverage": b.coverage(out), "targets": b.targets(),
            "amounts": {k: float(v) for k, v in b.a.items()},
            "material": {"repaints": nrep, "cloud_amp": mt.cloud_amp(nrep)}}
    for p in planes:
        o = out[p["name"]]
        D = np.where(p["mask"], o["D"], np.nan).astype(np.float32)
        arrs = {"D": D, "Yc": wm.luminance(bases[p["name"]]).astype(np.float32), "cls": p["cls"],
                "src": src_map(p, o), "edge": p["edges"]}
        for k, v in o["L"].items():
            m_ = p["mask"] | p["steel"] if (k == "rust" and p.get("steel") is not None) else p["mask"]   # rust on the steel too (R1, R2)
            arrs["L_" + k] = np.where(m_, v, np.nan).astype(np.float32)
        dm = o["marks"].get("damage", [])
        if dm:
            arrs["dmg_y"] = np.array([m["y"] for m in dm], np.int32)
            arrs["dmg_x"] = np.array([m["x"] for m in dm], np.int32)
            arrs["dmg_r"] = np.array([m["r_m"] for m in dm], np.float32)
            arrs["dmg_d"] = np.array([m["d_m"] for m in dm], np.float32)
            arrs["dmg_k"] = np.array([m.get("k", -1) for m in dm], np.int32)   # hotspot index, -1 background
            dl = b.fixed.get(p["name"], ({}, {}))[0].get("damage")
            if dl is not None:
                arrs["dmg_a"] = dl["alpha"].astype(np.float16)          # break coverage (K4)
                arrs["dmg_h"] = dl["depth"].astype(np.float16)          # break depth, m (relief)
        arrs["rgb"] = o["rgb"].astype(np.float16)                 # weathered albedo (previews)
        tf = getattr(b, "tint", {}).get(p["name"])
        if tf is not None and "fam_g" in tf:                         # mark colour families (I4): 1 green, 2 yellow
            arrs["fam"] = ((tf["fam_g"] >= 0.5).astype(np.uint8) + 2 * (tf["fam_y"] >= 0.5).astype(np.uint8))
        if p.get("steel") is not None:
            arrs["steel"] = p["steel"].astype(np.uint8)              # rusting metal (R1-R3)
        if p["name"] in getattr(b, "wet", {}):
            arrs["bio_w"] = b.wet[p["name"]]                         # where water stays (growth rules)
        cs = getattr(b, "crk", {}).get(p["name"])
        if cs is not None:                                           # cracks (K7-K11)
            arrs["crk_w"] = cs.wmm.astype(np.float16)
            arrs["crk_t"] = cs.typ
            arrs["crk_o"] = cs.ori
        mw = o["marks"].get("wear", [])
        if mw:                                                       # edge chips (N3, N4)
            arrs["wch_y"] = np.array([m["y"] for m in mw], np.int32)
            arrs["wch_x"] = np.array([m["x"] for m in mw], np.int32)
        if p.get("tops") is not None:
            arrs["etop"] = (p["tops"] & p["edges"]).astype(np.uint8) + 2 * (p["bottoms"] & p["edges"]).astype(np.uint8)
        ops = wf.plane_openings(p)
        if ops:
            arrs["openings"] = np.array(ops, np.int32)
        Fp = b.F[p["name"]]
        arrs["mat"] = getattr(Fp, "matresp", Fp.mat).astype(np.float16)   # the material response dirt follows (J2)
        arrs["base"] = bases[p["name"]].astype(np.float16)          # clean albedo (close-ups)
        if p.get("joint_h") is not None:
            arrs["joint"] = (p["joint_h"].astype(np.uint8) + 2 * p["joint_v"].astype(np.uint8))
        arrs["labw"] = wm.linear_to_lab(o["rgb"]).astype(np.float32)
        arrs["labc"] = wm.linear_to_lab(bases[p["name"]]).astype(np.float32)
        np.savez_compressed(os.path.join(out_dir, p["name"] + ".npz"), **arrs)   # lossless: the gate reads the same numbers
        meta["planes"][p["name"]] = {k: p[k] for k in ("ppm", "orient", "kind", "exposed", "ground_row", "top_row") if k in p}
        meta["planes"][p["name"]]["floor_rows"] = [int(v) for v in p.get("floor_rows", [])]
        meta["planes"][p["name"]]["bay_cols"] = [int(v) for v in p.get("bay_cols", [])]
        if p.get("bay_kinds"):
            meta["planes"][p["name"]]["bay_kinds"] = list(p["bay_kinds"])
        meta["planes"][p["name"]]["n_marks"] = {k: len(v) for k, v in o["marks"].items()}
        if preview:
            Image.fromarray(to_srgb8(o["rgb"])).save(os.path.join(out_dir, p["name"] + ".jpg"), quality=90)
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
    json.dump(log, open(os.path.join(out_dir, "solver_log.json"), "w"), indent=0)
    print("built %s in %.0fs  E %.1f  gains soiling %.2f accent %.2f film_k %.3f  coverage %s" % (
        out_dir, time.time() - t0, b.E, gs, ga, b.k, " ".join("%.3f" % c for c in meta["coverage"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("preset")
    ap.add_argument("--age", type=float)
    ap.add_argument("--upkeep", type=float)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--override", nargs="*", default=[])
    ap.add_argument("--gain", nargs="*", default=[])
    ap.add_argument("--gains", help="fixed solver gains gs,ga,film_k (sweeps)")
    ap.add_argument("--control", help="name of the swept control (recorded in the config)")
    a = ap.parse_args()
    age, up = PRESETS.get(a.preset, (a.age, a.upkeep))
    if a.age is not None:
        age = a.age
    if a.upkeep is not None:
        up = a.upkeep
    cfg = {"preset": a.preset, "age": age, "upkeep": up, "seed": a.seed, "grime": 0.5, "exposure": 0.6,
           "wind": 200.0, "override": {}, "gains": {}}
    for o in a.override:
        k, v = o.split("=")
        cfg["override"][k] = float(v)
    for g in a.gain:
        k, v = g.split("=")
        cfg["gains"][k] = float(v)
    if a.control:
        cfg["sweep_control"] = a.control
    fg = tuple(float(x) for x in a.gains.split(",")) if a.gains else None
    run(a.out, cfg, fixed_gains=fg)


if __name__ == "__main__":
    main()
