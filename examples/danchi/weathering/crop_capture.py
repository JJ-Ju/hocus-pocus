#!/usr/bin/env hython
"""crop_capture.py - the clean danchi asset at a higher texel density over facade boxes (round I).

The weathering planes are captured at 50 px/m (elevation_capture.py). Review crops at game texel
density need the geometry itself at that density: window frames, glass, rails and balusters would
otherwise be 2 cm blocks. For each box this renders the `clean` config with the same two Karma
passes as the elevations, on a camera that covers only the box, and writes
<out>/<V>_<x0>_<y0>_<x1>_<y1>_<ppm>.npz with albedo (RGBA, A = coverage), class_raw, N, depth and P,
plus a JSON beside it with the exact mapping.

  hython crop_capture.py <elev_dir> <out_dir> <V:x0,y0,x1,y1:ppm> [...] [--engine xpu|cpu]

Boxes are in the 50 px/m pixels of the elevation frames in <elev_dir>/frames.json (V = S, N or W),
so a crop lines up with the facade-space maps. Loads the round-7 hip read-only, as the elevations do.
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hou  # noqa: E402
import elevation_capture as ec  # noqa: E402


def crop_frame(fr, box, ppm):
    """The frame of a facade box: same axes as the elevation, camera centred on the box."""
    x0, y0, x1, y1 = box
    mpp50 = fr["m_per_px"]
    o, u, v = np.array(fr["origin"]), np.array(fr["u_axis"], float), np.array(fr["v_axis"], float)
    centre = o + 0.5 * (x0 + x1) * mpp50 * u + 0.5 * (y0 + y1) * mpp50 * v
    w_m, h_m = (x1 - x0) * mpp50, (y1 - y0) * mpp50
    f = dict(fr)
    f.update(width_px=int(round(w_m * ppm)), height_px=int(round(h_m * ppm)), width_m=w_m, height_m=h_m,
             px_per_m=float(ppm), m_per_px=1.0 / ppm, cam_t=list(centre),
             origin=list(o + x0 * mpp50 * u + y0 * mpp50 * v), box50=list(box))
    return f


def set_cam(view, f):
    c = hou.node("/obj/elev_cam_" + view)
    c.parmTuple("t").set(f["cam_t"])
    c.parmTuple("r").set(f["cam_r"])
    c.parm("orthowidth").set(f["width_m"])
    c.parm("resx").set(f["width_px"])
    c.parm("resy").set(f["height_px"])
    c.parm("aspect").set(1.0)
    c.parm("near").set(1.0)
    c.parm("far").set(ec.CAM_DIST * 2 + 200.0)


def main():
    args = [a for a in sys.argv[1:]]
    if "--engine" in args:
        i = args.index("--engine")
        ec.ENGINE = args[i + 1]
        del args[i:i + 2]
    elev, out = args[0].replace("\\", "/"), args[1].replace("\\", "/")
    jobs = []
    for a in args[2:]:
        v, b, p = a.split(":")
        jobs.append((v, tuple(int(x) for x in b.split(",")), float(p)))
    os.makedirs(out, exist_ok=True)
    frames = json.load(open(elev + "/frames.json"))["frames"]
    ec.load_scene()
    ec.build_obj_nodes()
    chains = ec.build_lops()
    cfg = ec.config_table()["clean"]
    ec.set_parms(cfg["values"], cfg["dressing"])
    chains["look"][0].cook(force=True)
    cams = ec.find_cam_paths(chains["look"][0])
    ec.setup_krs(chains["look"][1], "look", ec.ENGINE, ec.SPP_LOOK, ec.LOOK_AOVS)
    ec.setup_krs(chains["surf"][1], "surf", ec.ENGINE, ec.SPP_SURF, ec.SURF_AOVS)
    for v, box, ppm in jobs:
        tag = "%s_%d_%d_%d_%d_%d" % ((v,) + box + (int(ppm),))
        dst = "%s/%s.npz" % (out, tag)
        if os.path.exists(dst):
            ec.log("skip (exists)", tag)
            continue
        f = crop_frame(frames[v], box, ppm)
        set_cam(v, f)
        t0 = time.time()
        pics = {}
        for ps in ("look", "surf"):
            pic = "%s/_raw_%s_%s.exr" % (out, tag, ps)
            dt, ok = ec.render(chains[ps], v, f, pic, cams[v])
            if not ok:
                raise RuntimeError("render failed %s %s" % (tag, ps))
            pics[ps] = pic
        L = ec.read_exr(pics["look"])
        S = ec.read_exr(pics["surf"])
        alb = L["albedo"][0]
        cov = L["C"][0][..., 3]
        cls = np.round(S["hpclass"][0][..., 0]).astype(np.int32)
        hit = cls > 0
        N = S["N"][0].copy()
        N[~hit] = 0.0
        dep = S["depth"][0][..., 0].copy()
        dep[~hit] = np.nan
        P = S["P"][0].copy()
        P[~hit] = np.nan
        np.savez_compressed(dst, albedo=np.dstack([alb, cov]).astype(np.float16), class_raw=cls.astype(np.uint8),
                            N=N.astype(np.float16), depth=dep.astype(np.float32), P=P.astype(np.float32))
        for pic in pics.values():
            os.remove(pic)
        json.dump(dict(f, view=v, render_s=round(time.time() - t0, 1)), open(dst[:-4] + ".json", "w"), indent=1)
        ec.log("crop %s %dx%d in %.1fs" % (tag, f["width_px"], f["height_px"], time.time() - t0))


if __name__ == "__main__":
    main()
