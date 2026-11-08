"""Convert the round-7 elevation captures into weather_gate folders (run in hython: needs OIIO).

hython r7_to_gate.py <elev_r7 dir> <out dir>
D = 1 - Y(albedo) / Y(albedo of 'clean') on wall classes, per view, pixel-aligned frames.
"""
import json
import os
import sys

import numpy as np
import OpenImageIO as oiio

SRC, OUT = sys.argv[1], sys.argv[2]
E = json.load(open(os.path.join(SRC, "elevations.json")))
B = json.load(open(os.path.join(SRC, "building", "building.json")))["plan"]
legend = E.get("class_legend") or E.get("classes")


def read_exr(path, sub=0):
    inp = oiio.ImageInput.open(path)
    if sub:
        inp.seek_subimage(sub, 0)
    a = inp.read_image(oiio.FLOAT)
    inp.close()
    return np.asarray(a)


def read_png16(path):
    inp = oiio.ImageInput.open(path)
    a = inp.read_image(oiio.FLOAT)
    inp.close()
    return np.asarray(a)


def lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


# class names -> gate classes (1 paint, 2 coping, 3 soffit, 4 concrete, 5 plinth, 6 glass, 7 metal, 8 prop, 0 none)
GATE = {"paint_ext": 1, "coping": 2, "soffit": 3, "concrete": 4, "glass": 6, "steel": 7, "alu": 7, "metal": 7,
        "frp": 8, "plastic": 8, "fabric": 8, "board": 8, "sign": 8, "room": 8, "floor": 8, "decal": 1, "none": 0}
if isinstance(legend, dict):
    inv = {int(k): v for k, v in legend.items()} if all(str(k).isdigit() for k in legend) else {int(v): k for k, v in legend.items()}
else:
    inv = {i: n for i, n in enumerate(legend)}
lut = np.zeros(256, np.uint8)
for code, name in inv.items():
    lut[int(code)] = GATE.get(name, 8)

PRESET_E = {"preset_new": ("new", 0, 1.0), "preset_well_kept": ("kept", 15, 0.85), "preset_typical": ("worn", 35, 0.5),
            "preset_neglected": ("neglected", 45, 0.12)}


def clock(age, upkeep):
    cycle = 24.0 + (7.0 - 24.0) * upkeep
    r = min(age, cycle)
    return r + 0.22 * (age - r)


def meta_for(view, fr):
    ppm = 50
    top_y = fr["top_y"]
    row = lambda y: int(round((top_y - y) * ppm - 0.5))  # noqa: E731
    floors = B.get("floors", 10)
    H = B.get("H", 2.8)
    ytop = B.get("ytop", 28.45)
    m = {"ppm": ppm, "orient": view, "kind": "gable" if view in ("W", "E") else "front", "exposed": True,
         "ground_row": row(0.0), "top_row": row(ytop + 0.6),
         "floor_rows": sorted({row(0.45 + f * H) for f in range(floors + 1)} | {row(ytop + 0.6)})}
    if view in ("S", "N"):
        x0 = B.get("x0", -40.25)
        edges = [x0]
        for w in B["bay_w"]:
            edges.append(edges[-1] + w)
        left = fr["left_edge"]["value"]
        sgn = 1 if view == "S" else -1
        m["bay_cols"] = sorted(int(round((sgn * (x - left)) * ppm)) for x in edges)
    else:
        left = fr["left_edge"]["value"]
        m["bay_cols"] = [int(round((z - left) * ppm)) for z in (-5.6, -4.2, -2.1, 0.0, 2.1, 4.2, 5.4)]
    return m


def convert(cfgname):
    d = os.path.join(SRC, cfgname)
    c = json.load(open(os.path.join(d, "config.json")))
    out = os.path.join(OUT, cfgname)
    os.makedirs(out, exist_ok=True)
    eff = c.get("effective", {})
    age, up = eff.get("age", 0.0), eff.get("upkeep", 1.0)
    pname = PRESET_E.get(cfgname, (cfgname, age, up))[0]
    cfg = {"preset": pname, "age": age, "upkeep": up, "E": clock(age, up), "source": "round-7 capture",
           "parms": c.get("parms_set", {})}
    meta = {"config": cfg, "planes": {}}
    for view in ("S", "W", "N"):
        f = os.path.join(d, view + "_albedo.exr")
        if not os.path.exists(f):
            continue
        alb = read_exr(f)
        cln = read_exr(os.path.join(SRC, "clean", view + "_albedo.exr"))
        clsraw = read_png16(os.path.join(d, view + "_class.png"))
        code = np.rint(clsraw[..., 0] * (255.0 if clsraw.max() <= 1.0 else 1.0)).astype(np.int64)
        cls = lut[np.clip(code, 0, 255)]
        cov = alb[..., 3] if alb.shape[-1] > 3 else np.ones(alb.shape[:2])
        Y, Yc = lum(alb[..., :3]), lum(cln[..., :3])
        wall = np.isin(cls, (1, 2)) & (cov > 0.999) & (Yc > 0.02)
        D = np.full(Y.shape, np.nan, np.float32)
        D[wall] = (1.0 - Y[wall] / Yc[wall]).astype(np.float32)
        np.savez(os.path.join(out, view + ".npz"), D=D, Yc=Yc.astype(np.float32), cls=cls.astype(np.uint8))
        meta["planes"][view] = meta_for(view, E["frames"][view])
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=1)
    print("converted", cfgname, list(meta["planes"]))


names = [n for n in sorted(os.listdir(SRC)) if os.path.isdir(os.path.join(SRC, n)) and
         os.path.exists(os.path.join(SRC, n, "config.json"))]
for n in names:
    if n in ("clean", "clean_dressed"):
        continue
    convert(n)
