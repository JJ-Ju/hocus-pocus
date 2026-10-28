"""build_formed.py - bare cast-in-place concrete (打ち放し) on Japanese 12 mm konpane formwork,
as a tiling Copernicus texture set. Round E, Houdini 22.0.466, run headless:

    hython build_formed.py <out_dir> [res=4096]

Contract (sources in docs/redesign/research/rE-concrete.md):
- tile 3.6 x 3.6 m: 4 x 2 vertical panels of 900 x 1800 mm (サブロク konpane);
- P-cone tie holes on a 450 x 600 mm grid (6 per panel), 30 mm across, mortar plugs 2-10 mm
  recessed, a few open (about 22 mm deep);
- seams: 2 mm gap, panel steps of +-1.2 mm, fins on some seams, paste-loss bands on others;
- placement layers every 600 mm: faint wavy layer lines, bug holes clustered toward the top
  of each layer (Poisson cells x cluster x layer phase), 1.5-12 mm, power-law sizes;
- faint plywood grain transfer per panel, waviness between battens, mottling per panel;
- one vertical hairline shrinkage crack; lime and rust runs from 4 of the 48 ties.

Writes basecolor (sRGB), roughness, ao, height (16-bit, metres mapped by meta.json), normal
(16-bit raw), mask (raw RGBA: R tie holes, G voids, B seam band, A layer phase), orm, plus
meta.json with the height range and the normal scale. Everything is linear in Copernicus.
"""
import os
import sys
import time

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, "cc_lib.py")).read())

if len(sys.argv) < 2:
    sys.exit("usage: hython %s <out_dir> [res...]  (keep the PNGs out of the repo)" % os.path.basename(__file__))
OUT = sys.argv[1]
RES = int(sys.argv[2]) if len(sys.argv) > 2 else 4096
TILE = 3.6
NAME = "formed"


def build(res=RES, tile_m=TILE, seed=1):
    g = G("/img", NAME, res, tile_m)
    U = g.U

    # ------------------------------------------------------------------ panels and seams
    pan = g.n("tilepattern", name="panels", patterntype="stackbond", patternmode="tilecount",
              stackbond_rows=2, stackbond_cols=4, inset=U(0.002))
    tiles, pid = (pan, 0), (pan, 1)
    p_h = g.rand(pid, 11 + seed, -1.0, 1.0)        # panel height offset
    p_v = g.rand(pid, 23 + seed)                   # panel tone (reuse, absorbency)
    p_r = g.rand(pid, 37 + seed)                   # wear level: mottling, roughness
    p_g = g.rand(pid, 41 + seed, 0.25, 1.0)        # grain transfer strength
    p_dx = g.rand(pid, 53 + seed)                  # grain offsets per panel
    p_dy = g.rand(pid, 59 + seed)

    edge = g.n("feather", tiles, name="seam_feather", unitdist=U(0.012), includeborder=0)
    seam = g.inv(edge)                              # 1 at a seam, 0 beyond 12 mm
    seam_core = g.thr(seam, 0.8, 0.15)
    seam_band = g.thr(seam, 0.45, 0.4)
    # which seams carry a fin (raised paste) and which a paste-loss sand band: a coarse 1D
    # breakup along each seam
    sbreak = g.thr(g.fractal(0.35, 3, 0.5), 0.5, 0.15)
    fin = g.mul(seam_core, sbreak)
    loss = g.mul(seam_band, g.inv(sbreak))

    # ------------------------------------------------------------------ tie holes
    tie = g.n("tilepattern", name="ties", patterntype="stackbond", patternmode="tilecount",
              stackbond_rows=6, stackbond_cols=8, basictype="circle", scale=0.030 / 0.45,
              draw="gradient", gradienttype="radial", doposjitter=1, posjitter=0.012,
              posjitterseed=float(seed))
    tg, tid = (tie, 0), (tie, 1)
    t_disc = g.remap(tg, 0.0, 0.02)
    t_wall = g.remap(tg, 0.0, 0.35)                 # conical wall, flat plug face inside
    t_r = g.rand(tid, 5 + seed)
    t_depth = g.scale(g.pw(t_r, 1.6), 0.008, 0.002)  # 2-10 mm, most shallow
    t_open = g.thr(g.rand(tid, 7 + seed), 0.93)       # about 7 % never plugged
    t_depth = g.lerp(t_depth, g.const(0.022), t_open)
    h_tie = g.mul(t_wall, t_depth)                   # subtracted below
    plug = g.mul(t_disc, g.inv(t_open))
    ring = g.mul(t_disc, g.inv(g.remap(tg, 0.05, 0.16)))
    # per-hole choices are made inside the disc (where the id is valid), then widened
    t_k = g.rand(tid, 9 + seed)
    halo_d = g.sub(g.remap(g.blur_m(g.mul(t_disc, g.thr(t_k, 0.3)), 0.035), 0.0, 0.22), t_disc)
    halo_p = g.sub(g.remap(g.blur_m(g.mul(t_disc, g.inv(g.thr(t_k, 0.1))), 0.035), 0.0, 0.22), t_disc)

    # ------------------------------------------------------------------ placement layers
    lay = g.n("ramp", name="layer_saw", signature="f1", rampType="vertical",
              cycles=tile_m / 0.6, method="repeat")
    wob = g.fractal(1.4, 3, 0.5, off=(3.1, 0.7))
    lay_w = g.n("distort", lay, None, wob, name="layer_wavy", dirtype="coord", dir=(0.0, 1.0),
                scale=U(0.06))
    tri = g.mn(lay_w, g.inv(lay_w))                  # 0 at a layer line, 0.5 mid-layer
    lline = g.mul(g.inv(g.remap(tri, 0.0, 0.012)),
                  g.thr(g.fractal(0.5, 3, off=(9.0, 2.0)), 0.45, 0.3))
    top = g.pw(lay_w, 2.0)                           # toward the top of each layer

    # ------------------------------------------------------------------ bug holes
    cl = g.thr(g.fractal(0.22, 3, off=(5.5, 1.5)), 0.6, 0.16)    # clusters
    cl2 = g.thr(g.fractal(0.6, 2, off=(2.5, 9.5)), 0.5, 0.4)     # broad zones of a bad pour
    dens = g.add(g.const(0.010), g.mul(g.mul(top, cl), g.scale(cl2, 0.22, 0.06)))
    dens = g.add(dens, g.mul(cl, g.const(0.04)))
    cell_m = 0.010
    wn = g.n("worleynoise", name="bug_cells", elementsize=U(cell_m), jitter=1.0)
    wd, wid = (wn, "dist1"), (wn, "id")
    keep = g.thr(g.sub(dens, g.rand(wid, 101 + seed)), 0.0)
    rs = g.rand(wid, 103 + seed)
    R = g.mul(g.scale(g.pw(rs, 2.5), 0.34, 0.08), g.scale(cl, 0.55, 0.8))   # cell units
    wdj = g.n("distort", wd, None, g.fractal(0.004, 2, off=(1.0, 4.0)), dirtype="coord",
              dir=(1.0, 0.6), scale=U(0.0012))       # irregular rims
    t = g.inv(g.remap(g.div(wdj, R), 0.0, 1.0))
    prof = g.sub(g.scale(t, 2.0), g.mul(t, t))       # 2t - t^2: sharp rim, round bottom
    void = g.mul(prof, keep)
    h_bug = g.mul(void, g.scale(R, 0.6 * cell_m))    # depth 0.6 x radius

    # ------------------------------------------------------------------ crack
    rh = g.n("ramp", name="crack_x", signature="f1", rampType="horizontal")
    cw = g.n("distort", rh, None, g.fractal(0.25, 5, 0.6, off=(2.2, 8.0)), dirtype="coord",
             dir=(1.0, 0.0), scale=U(0.05))
    cx = g.absval(g.scale(cw, 1.0, -0.612))
    crack = g.inv(g.remap(cx, 0.0, 0.0008 / tile_m))   # ramp units: 1 = tile width
    cv = g.n("ramp", name="crack_y", signature="f1", rampType="vertical")
    cext = g.mul(g.remap(cv, 0.08, 0.2), g.inv(g.remap(cv, 0.8, 0.95)))
    crack = g.mul(crack, g.mul(cext, g.thr(g.fractal(0.18, 3, off=(4.0, 4.0)), 0.3, 0.3)))

    # ------------------------------------------------------------------ surface relief
    gr = g.fractal(0.0035, 4, 0.55, stretch=(1.0, 26.0), off=(0.3, 0.9))
    pvec = g.n("channeljoin", p_dx, p_dy, name="panel_offset", signature="f2")
    gr_p = g.n("distort", gr, pvec, name="grain_per_panel", dirtype="coord", scale=U(0.8))
    h_grain = g.mul(g.scale(gr_p, 0.0003, -0.00015), p_g)
    h_wave = g.scale(g.fractal(0.7, 3, 0.45, off=(7.0, 3.0)), 0.0016, -0.0008)
    sand = g.thr(g.fractal(0.12, 4, off=(6.0, 6.0)), 0.6, 0.25)
    h_micro = g.mul(g.scale(g.fractal(0.0016, 3, 0.6, off=(2.0, 5.0)), 0.00012, -0.00006),
                    g.scale(sand, 1.5, 0.5))
    h_panel = g.blur_m(g.mul(g.scale(p_h, 0.0012), tiles), 0.0015)

    h = g.add(h_panel, h_wave)
    h = g.add(h, h_grain)
    h = g.add(h, h_micro)
    h = g.add(h, g.scale(fin, 0.0008))
    h = g.sub(h, g.scale(loss, 0.0006))
    h = g.sub(h, h_tie)
    h = g.sub(h, h_bug)
    h = g.sub(h, g.scale(crack, 0.0004))
    height_m = g.n("null", h, name="height_m")

    # ------------------------------------------------------------------ value and colour
    mott = g.fractal(0.32, 4, 0.5, off=(11.0, 1.0))
    marb = g.fractal(0.07, 3, 0.5, off=(13.0, 2.0))
    V = g.scale(p_v, 0.12, 0.94)                                     # +-6 % per panel
    V = g.add(V, g.mul(g.scale(mott, 0.22, -0.11), g.scale(p_r, 0.9, 0.5)))
    cloud = g.thr(g.fractal(0.18, 4, 0.55, off=(17.0, 5.0)), 0.62, 0.18)   # hydration clouds
    V = g.sub(V, g.mul(g.scale(cloud, 0.07), g.scale(p_r, 1.0, 0.4)))
    frame = g.inv(g.n("feather", tiles, unitdist=U(0.07), includeborder=0))
    V = g.sub(V, g.mul(g.scale(frame, 0.035), g.thr(g.fractal(0.5, 2, off=(21.0, 3.0)), 0.5, 0.3)))
    V = g.add(V, g.scale(marb, 0.04, -0.02))
    bleed = g.fractal(0.012, 4, 0.55, stretch=(1.0, 18.0), off=(15.0, 4.0))   # bleed-water streaks
    V = g.add(V, g.mul(g.scale(bleed, 0.05, -0.025), g.scale(g.thr(g.fractal(0.4, 2, off=(19.0, 9.0)), 0.5, 0.4), 1.0, 0.3)))
    V = g.sub(V, g.scale(lline, 0.035))
    V = g.sub(V, g.scale(loss, 0.05))
    V = g.add(V, g.scale(fin, 0.02))
    V = g.sub(V, g.scale(halo_d, 0.035))                             # absorption shadows
    V = g.add(V, g.scale(halo_p, 0.02))
    V = g.add(V, g.mul(plug, g.scale(t_r, 0.10, 0.03)))              # plugs lighter
    V = g.sub(V, g.scale(ring, 0.18))
    V = g.sub(V, g.scale(void, 0.40))
    V = g.sub(V, g.scale(crack, 0.30))
    V = g.add(V, g.scale(sand, 0.025))
    # meso and fine albedo (round E measurement: renders had 0.2 L* in the 2-10 cm band where
    # photographed bare concrete has 1.4-3.5): pores, sand and dirt specks at 3-5 mm and
    # blotches at 2-6 cm, both with a clustered amplitude envelope
    envm = g.scale(g.thr(g.fractal(0.3, 3, off=(23.0, 7.0)), 0.45, 0.6), 1.0, 0.4)
    speck = g.fractal(0.004, 3, 0.6, off=(27.0, 1.0))
    blot = g.fractal(0.035, 3, 0.6, off=(29.0, 3.0))
    # fractalnoise around 0.5 has a std of only about 0.076, so these factors are large:
    # 0.35 x 0.076 = 2.7 % and 0.5 x 0.076 = 3.8 % std before the envelope
    V = g.add(V, g.mul(g.scale(speck, 0.35, -0.175), envm))
    V = g.add(V, g.mul(g.scale(blot, 0.5, -0.25), envm))
    ao = g.n("heighttoambientocclusion", height_m, name="ao", heightscale=1.0 / (tile_m / 2.0),
             viewradius=U(0.02))
    V = g.mul(V, g.remap(ao, 0.0, 1.0, 0.82, 1.0))                   # dirt held in recesses

    base_rgb = g.n("constant", name="cement_grey", signature="f3", f3=(0.305, 0.300, 0.283))
    cool_rgb = g.n("constant", name="cool_grey", signature="f3", f3=(0.272, 0.282, 0.288))
    hue_m = g.scale(g.inv(mott), 0.5, -0.1)                          # dark clouds a bit cooler
    col = g.lerp(base_rgb, cool_rgb, hue_m, signature="f3")
    col = g.n("blend", col, V, mode="multiply", name="col_value")

    # lime and rust runs from a few ties: downward streaks (streakblur bias 1 = one-sided)
    t_s = g.rand(tid, 13 + seed)
    pick_l = g.remap(g.blur_m(g.mul(t_disc, g.thr(t_s, 0.92)), 0.012), 0.0, 0.3)
    pick_r = g.remap(g.blur_m(g.mul(g.mul(t_disc, g.inv(g.thr(t_s, 0.04))),
                                    g.thr(t_s, 0.0001)), 0.012), 0.0, 0.3)
    brk = g.thr(g.fractal(0.05, 3, stretch=(1.0, 4.0), off=(8.0, 8.0)), 0.35, 0.5)
    def run(pick, length_m, nm):
        """A run below a source: one-sided streak (bias 1), tapering with distance (mode on
        averages), wavering sideways, broken up by a vertically stretched noise."""
        st = g.n("streakblur", pick, name=nm, dirtype="coord", dir=(0.0, -1.0), bias=1.0,
                 length=U(length_m), mode="on")
        st = g.n("distort", st, None, g.fractal(0.08, 3, off=(length_m * 50, 3.0)),
                 dirtype="coord", dir=(1.0, 0.0), scale=U(0.012))
        return g.mul(g.pw(g.remap(st, 0.0, 0.35), 1.5), brk)
    lime = run(pick_l, 0.30, "lime_run")
    rust = run(pick_r, 0.18, "rust_run")
    col = g.lerp(col, g.n("constant", signature="f3", f3=(0.46, 0.46, 0.45)),
                 g.scale(lime, 0.35), signature="f3")
    col = g.lerp(col, g.n("constant", signature="f3", f3=(0.22, 0.11, 0.05)),
                 g.scale(rust, 0.35), signature="f3")
    basecolor = g.n("null", col, name="basecolor")

    # ------------------------------------------------------------------ roughness
    Rg = g.scale(p_r, 0.06, 0.77)
    Rg = g.add(Rg, g.scale(sand, 0.06))
    Rg = g.add(Rg, g.scale(loss, 0.06))
    Rg = g.sub(Rg, g.scale(g.inv(mott), 0.04))
    Rg = g.add(Rg, g.scale(void, 0.14))
    Rg = g.add(Rg, g.scale(plug, 0.04))
    Rg = g.add(Rg, g.scale(lime, 0.10))
    Rg = g.add(Rg, g.scale(crack, 0.08))
    rough = g.n("null", g.remap(Rg, 0.5, 1.0, 0.5, 1.0), name="roughness")

    # ------------------------------------------------------------------ derived and write
    HMIN, HMAX = -0.024, 0.004
    height01 = g.n("null", g.remap(height_m, HMIN, HMAX), name="height")
    nscale = 1.5 * 2.0 / tile_m                       # physical slope x 1.5
    normal = g.n("heighttonormal", height_m, name="normal", scale=nscale)
    mask = g.n("channeljoin", t_disc, void, seam_band, name="mask", signature="f3")
    orm = g.n("channeljoin", ao, rough, g.const(0.0), name="orm", signature="f3")

    meta = dict(name=NAME, tile_m=tile_m, res=res, px_per_m=res / tile_m,
                height_range_m=[HMIN, HMAX], normal_scale=nscale, normal_exaggeration=1.5,
                mask=dict(R="tie hole disc", G="voids (bug holes)", B="seam band"),
                layer="placement-layer phase, own file (0 bottom, 1 top of each 0.6 m layer)")
    for nm, nd in dict(height_m=height_m, basecolor=basecolor, roughness=rough).items():
        meta[f"stats_{nm}"] = g.stats(nd)
    meta["stats_void_cover"] = g.stats(g.thr(void, 0.05))["mean"]
    meta["stats_tie_cover"] = g.stats(t_disc)["mean"]
    files = {}
    t0 = time.time()
    for nm, nd, kind in [("basecolor", basecolor, "color"), ("roughness", rough, "data"),
                         ("ao", ao, "data"), ("height", height01, "data16"),
                         ("normal", normal, "data16"), ("mask", mask, "data"),
                         ("layer", g.n("null", lay_w, name="layer"), "data"),
                         ("orm", orm, "data")]:
        files[nm] = g.write(nd, os.path.join(OUT, f"{NAME}_{nm}.png"), kind)
    meta["write_s"] = round(time.time() - t0, 1)
    save_meta(os.path.join(OUT, f"{NAME}_meta.json"), meta)
    return g, meta


if __name__ == "__main__":
    t0 = time.time()
    g, meta = build()
    print("built", NAME, "in %.1fs" % (time.time() - t0))
    for k in ("stats_height_m", "stats_basecolor", "stats_roughness", "stats_void_cover",
              "stats_tie_cover"):
        print(k, meta[k])
