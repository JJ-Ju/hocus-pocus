"""run_real.py - weathering on the real building's elevation planes (round-7 captures).

python -I wx/run_real.py <out_dir> <preset> [--seed N] [--override k=v ...] [--gains gs,ga,k]
Painted surfaces take the round-E spray-coat texture under run 7's paint colours (blurred 0.5 m).
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts", "weathering"))
import real_planes as rpl  # noqa: E402
import run_proto as rp  # noqa: E402
import weather_measure as wm  # noqa: E402
import weather_fields as wf  # noqa: E402
import wx_noise as nz  # noqa: E402

ROOT = os.environ.get("WX_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


def real_bases(planes, bases0, raw_codes=None):
    """Clean albedo for the real planes: each painted element (a connected surface at one depth)
    takes the median colour of the round-7 albedo over it, times the round-E spray-coat texture;
    decal pixels keep their own albedo; other classes are unchanged."""
    out = {}
    for p in planes:
        b = bases0[p["name"]].astype(np.float64)
        m = p["mask"]
        ppm = p["ppm"]
        dec = p.get("decal", np.zeros_like(m))
        surf = m & ~dec
        # elements: connected painted pixels without a depth step to the neighbour
        dep = p.get("depth")
        if dep is not None:
            brk_v = np.zeros_like(surf)
            brk_v[1:] = np.abs(dep[1:] - dep[:-1]) > 0.05
            brk_h = np.zeros_like(surf)
            brk_h[:, 1:] = np.abs(dep[:, 1:] - dep[:, :-1]) > 0.05
            surf_l = surf & ~brk_v & ~brk_h
        else:
            surf_l = surf
        lab, n = wm.label(surf_l)
        flat = np.zeros_like(b)
        if n:
            L = lab.ravel()
            sel = L > 0
            for c in range(3):
                v = b[..., c].ravel()[sel]
                order = np.argsort(L[sel], kind="stable")
                ls, vs = L[sel][order], v[order]
                cut = np.flatnonzero(np.diff(ls)) + 1
                med = np.array([np.median(x) for x in np.split(vs, cut)])
                ids = np.unique(ls)
                lut = np.zeros(n + 1)
                lut[ids] = med
                flat[..., c] = lut[lab]
        # pixels on the breaks themselves take their neighbour's colour
        miss = surf & (lab == 0)
        if miss.any():
            have = lab > 0
            src = b[have] if have.any() else b[surf]
            gmed = np.median(src, axis=0)
            for c in range(3):
                fill = np.full(m.shape, np.nan)
                for sg in (2.0, 6.0, 18.0):                # nearest elements first, then wider
                    g = wm.masked_gauss(flat[..., c], have, sg)
                    fill = np.where(np.isnan(fill), g, fill)
                fill = np.where(np.isfinite(fill), fill, gmed[c])
                flat[..., c] = np.where(miss, fill, flat[..., c])
        tex = rp.tile_rgb("spraymacro_basecolor.png", 3.6, ppm)
        H, W = m.shape
        tt = nz.tile_blend(tex, (H, W), ("coat", p["name"]), tex.shape[0])     # same sampling as the dirt (J2)
        lap = wf.lap_rule((H, W), ppm, p.get("ground_row"), ("lap", p["name"]))
        tt = tt * (1.0 - 0.012 * lap)[..., None]                                # laps 0.4-0.7 % darker, clean
        o = np.where(surf[..., None], flat * tt, b)
        out[p["name"]] = o.astype(np.float32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("preset")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--override", nargs="*", default=[])
    ap.add_argument("--gains")
    ap.add_argument("--match", help="build dir of this preset's first seed: keep its film contrast, aim at its coverage (A5)")
    a = ap.parse_args()
    age, up = rp.PRESETS[a.preset]
    cfg = {"preset": a.preset, "age": age, "upkeep": up, "seed": a.seed, "grime": 0.5, "exposure": 0.6,
           "wind": 200.0, "override": {}, "gains": {}, "building": "round-7 danchi, real elevations"}
    if a.match:
        import json
        m = json.load(open(os.path.join(a.match, "meta.json"), encoding="utf-8"))
        if m["config"].get("preset") != a.preset:
            raise SystemExit("--match %s is preset %s, not %s" % (a.match, m["config"].get("preset"), a.preset))
        cfg["match"] = {"dir": a.match, "seed": m["config"].get("seed"), "film_k": m["gains"]["film_k"],
                        "coverage": m["coverage"]}
    for o in a.override:
        k, v = o.split("=")
        cfg["override"][k] = float(v)
    planes, bases0 = rpl.load_real(ROOT)
    bases = real_bases(planes, bases0)
    fg = tuple(float(x) for x in a.gains.split(",")) if a.gains else None
    rp.run(a.out, cfg, planes=planes, bases=bases, fixed_gains=fg)
    import closeup
    closeup.make_all(a.out)                       # 1 m close-ups at 1 mm/px (rules J1, J2)


if __name__ == "__main__":
    main()
