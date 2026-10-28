"""build_spray.py - a repainted spray-tile wall (複層仕上塗材E, flattened 凸部処理 pattern, two
repaints) applied directly on formed concrete, as a macro tiling set plus a detail set.
Round E, Houdini 22.0.466, run headless:

    hython build_spray.py <out_dir> [macro_res=2048] [detail_res=1024]

Why two sets: the coating texture (bumps 3-11 mm) needs about 1500 px/m, while the things
that make it read as a coat on a concrete building (panel steps and tie plugs telegraphing
through, roller laps and scaffold-lift bands from repaints, repair patches, a sealed crack
with injection seats, a hairline crack) live at 0.05-3.6 m. Games ship exactly this split: a
macro tiling set (here 3.6 m at 2048 = 569 px/m) and a mean-neutral detail set (0.6 m at
1024 = 1707 px/m) whose strength the macro mask modulates.

macro: spraymacro_{basecolor,roughness,height,normal,mask,lap,orm,ao}.png, mask raw RGB:
       R coat (detail strength 0..1, 1 = 1.5x), G repair patch, B crack and bead; lap overlap
       in its own file (Karma premultiplies RGB by A when it reads an RGBA PNG)
detail: spraydetail_{height,normal,cavity,top}.png (cavity: 1 = trough, for dirt fill;
        top: plateau mask, for chalk and wear)
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
MRES = int(sys.argv[2]) if len(sys.argv) > 2 else 2048
DRES = int(sys.argv[3]) if len(sys.argv) > 3 else 1024


def build_detail(res=DRES, tile_m=0.6, seed=0):
    g = G("/img", "spraydetail", res, tile_m)
    U = g.U

    def blobs(cell_m, rmin, rspan, keep_p, hmin, cap, lattice, jitter, s):
        wn = g.n("worleynoise", elementsize=U(cell_m), jitter=jitter, lattice=lattice,
                 off=(0.37 * s, 0.11 * s))
        d, i = (wn, "dist1"), (wn, "id")
        keep = g.inv(g.thr(g.rand(i, 201 + s), keep_p))
        R = g.scale(g.rand(i, 203 + s), rspan, rmin)
        t = g.inv(g.remap(g.div(d, R), 0.0, 1.0))
        dome = g.sub(g.scale(t, 2.0), g.mul(t, t))
        hgt = g.mul(dome, g.scale(g.rand(i, 207 + s), 1.0 - hmin, hmin))
        if cap < 1.0:                                  # 凸部処理: tops rolled flat
            hgt = g.scale(g.n("clamp", hgt, dolowerlimit=1, lowerlimit=0.0, doupperlimit=1,
                              upperlimit=cap), 1.0 / cap)
        return g.mul(hgt, keep)

    # spray passes are uneven: where a pass laid more material, big droplets merged into
    # plateaus; elsewhere small droplets sit on a thin base coat
    pas = g.thr(g.fractal(0.09, 3, off=(2.0, 7.0)), 0.5, 0.45)
    big = g.mul(blobs(0.0105, 0.40, 0.30, 0.80, 0.7, 0.6, "hex", 0.75, 1 + seed),
                g.scale(pas, 0.75, 0.25))
    mid = g.scale(blobs(0.0062, 0.36, 0.22, 0.55, 0.6, 0.7, "grid", 1.0, 5 + seed), 0.6)
    small = g.scale(blobs(0.0034, 0.3, 0.2, 0.5, 0.5, 1.0, "grid", 1.0, 9 + seed), 0.3)
    h = g.mx(g.mx(big, mid), small)
    # two or three repaints: edges rounded, troughs part-filled, peaks less sharp
    h = g.lerp(h, g.blur_m(h, 0.0006), g.const(0.6))
    h = g.add(h, g.blur_m(h, 0.003), 0.45)
    grit = g.scale(g.fractal(0.0007, 3, 0.6), 0.06, -0.03)
    h = g.add(h, grit)
    h01 = g.n("null", g.n("equalize", h, mode="stretch"), name="height")
    relief = 0.0009                                     # peak to trough after repaints
    hm = g.scale(h01, relief)
    normal = g.n("heighttonormal", hm, name="normal", scale=1.0 * 2.0 / tile_m)
    ao = g.n("heighttoambientocclusion", hm, heightscale=2.0 / tile_m, viewradius=U(0.004))
    cav = g.n("null", g.n("equalize", g.inv(ao), mode="stretch"), name="cavity")
    top = g.n("null", g.thr(h01, 0.72, 0.12), name="top")
    meta = dict(name="spraydetail", tile_m=tile_m, res=res, px_per_m=res / tile_m,
                relief_m=relief, normal_scale=2.0 / tile_m, stats_height=g.stats(h01),
                stats_top_cover=g.stats(top)["mean"], stats_cavity=g.stats(cav))
    for nm, nd, kind in [("height", h01, "data16"), ("normal", normal, "data16"),
                         ("cavity", cav, "data"), ("top", top, "data")]:
        g.write(nd, os.path.join(OUT, f"spraydetail_{nm}.png"), kind)
    save_meta(os.path.join(OUT, "spraydetail_meta.json"), meta)
    return meta


def build_macro(res=MRES, tile_m=3.6, seed=0):
    g = G("/img", "spraymacro", res, tile_m)
    U = g.U
    # substrate telegraphing through a 1-2 mm coat: panel steps and tie plugs, softened
    pan = g.n("tilepattern", patterntype="stackbond", patternmode="tilecount",
              stackbond_rows=2, stackbond_cols=4, inset=U(0.002))
    p_h = g.rand((pan, 1), 11 + seed, -1.0, 1.0)
    h_pan = g.blur_m(g.mul(g.scale(p_h, 0.0006), (pan, 0)), 0.004)
    tie = g.n("tilepattern", patterntype="stackbond", patternmode="tilecount",
              stackbond_rows=6, stackbond_cols=8, basictype="circle", scale=0.030 / 0.45,
              draw="gradient", gradienttype="radial", doposjitter=1, posjitter=0.012)
    t_disc = g.blur_m(g.remap((tie, 0), 0.0, 0.02), 0.004)
    h_wave = g.scale(g.fractal(0.7, 3, 0.45, off=(7.0, 3.0)), 0.0024, -0.0012)

    # repaint campaigns: roller laps about 0.9 m apart (vertical) and 1.2 m apart, scaffold
    # lifts every 1.8 m (horizontal); overlaps carry a double coat
    def laps(cycles, vertical, warp_m, halfw, off):
        rp = g.n("ramp", signature="f1", rampType="horizontal" if vertical else "vertical",
                 cycles=float(cycles), method="repeat", phase=off)
        wv = g.n("distort", rp, None, g.fractal(0.6, 3, off=(off * 7, 1.0)), dirtype="coord",
                 dir=(1.0, 0.0) if vertical else (0.0, 1.0), scale=U(warp_m))
        tri = g.mn(wv, g.inv(wv))
        return g.inv(g.remap(tri, 0.0, halfw))
    brk = lambda o: g.thr(g.fractal(0.45, 3, off=(o, 2.0 * o)), 0.5, 0.35)
    lap1 = g.mul(laps(4, True, 0.05, 0.03 / 0.9, 0.13), brk(3.0))
    lap2 = g.mul(laps(3, True, 0.08, 0.035 / 1.2, 0.61), brk(5.0))
    lift = g.mul(laps(2, False, 0.03, 0.02 / 1.8, 0.27), brk(7.0))
    lap = g.mx(g.mx(lap1, g.scale(lap2, 0.6)), g.scale(lift, 0.7))

    # repair patches (chipped-out spalls refilled, rolled smoother) with a slight edge ridge
    def patch(x0, y0, w_m, h_m, s):
        """Rectangle from two ramps (ramp units 0..1 across the tile; y up), edges warped."""
        rx = g.n("ramp", signature="f1", rampType="horizontal")
        ry = g.n("ramp", signature="f1", rampType="vertical")
        wx, wy = w_m / tile_m, h_m / tile_m
        e = 0.002 / tile_m
        inx = g.mul(g.remap(rx, x0, x0 + e), g.inv(g.remap(rx, x0 + wx - e, x0 + wx)))
        iny = g.mul(g.remap(ry, y0, y0 + e), g.inv(g.remap(ry, y0 + wy - e, y0 + wy)))
        m = g.mul(inx, iny)
        m = g.n("distort", m, None, g.fractal(0.04, 3, off=(s, s)), dirtype="coord",
                dir=(0.7, 0.7), scale=U(0.01))
        return g.blur_m(m, 0.0015)
    pat = g.mx(patch(0.20, 0.62, 0.42, 0.30, 1.0), patch(0.74, 0.12, 0.26, 0.62, 2.0))
    p_edge = g.mul(g.thr(pat, 0.15, 0.2), g.inv(g.thr(pat, 0.85, 0.2)))

    # a sealed crack with injection seats every 257 mm, and an open hairline crack
    def crack_line(x0, warp, yr, s):
        rh = g.n("ramp", signature="f1", rampType="horizontal")
        cw = g.n("distort", rh, None, g.fractal(0.25, 5, 0.6, off=(s, 8.0)), dirtype="coord",
                 dir=(1.0, 0.0), scale=U(warp))
        dist = g.absval(g.scale(cw, 1.0, -x0))            # ramp units: 1 = tile width
        cv = g.n("ramp", signature="f1", rampType="vertical")
        ext = g.mul(g.remap(cv, yr[0], yr[0] + 0.06), g.inv(g.remap(cv, yr[1] - 0.06, yr[1])))
        return dist, ext
    dist1, ext1 = crack_line(0.30, 0.06, (0.18, 0.62), 2.2)
    bead = g.mul(g.inv(g.remap(dist1, 0.0, 0.005 / tile_m)), ext1)
    seat_band = g.mul(g.inv(g.remap(dist1, 0.0, 0.011 / tile_m)), ext1)
    pulse = g.n("ramp", signature="f1", rampType="vertical", cycles=14.0, method="repeat")
    ptri = g.mn(pulse, g.inv(pulse))
    seats = g.blur_m(g.mul(seat_band, g.inv(g.remap(ptri, 0.0, 0.011 / 0.257))), 0.003)
    dist2, ext2 = crack_line(0.83, 0.04, (0.35, 0.72), 6.6)
    hair = g.mul(g.mul(g.inv(g.remap(dist2, 0.0, 0.0009 / tile_m)), ext2),
                 g.thr(g.fractal(0.12, 3, off=(4.0, 1.0)), 0.3, 0.3))

    h = g.add(h_pan, h_wave)
    h = g.sub(h, g.scale(t_disc, 0.0003))
    h = g.add(h, g.scale(lap, 0.00015))
    h = g.add(h, g.scale(p_edge, 0.0003))
    h = g.add(h, g.scale(g.blur_m(bead, 0.002), 0.00025))
    h = g.add(h, g.scale(seats, 0.0005))
    h = g.sub(h, g.scale(hair, 0.0002))
    height_m = g.n("null", h, name="height_m")

    # coat thickness, the detail strength: thicker in overlaps, thin and smooth in patches
    coatn = g.fractal(0.3, 3, off=(12.0, 4.0))
    coat = g.scale(coatn, 0.5, 0.55)                     # 0.55-1.05
    coat = g.add(coat, g.scale(lap, 0.12))
    coat = g.lerp(coat, g.const(0.45), pat)
    coat01 = g.n("null", g.remap(coat, 0.0, 1.5), name="coat")

    # colour: ivory off-white (Munsell about 2.5Y 8.5/1), very low-contrast macro variation
    V = g.scale(coatn, 0.03, 0.985)
    V = g.sub(V, g.scale(lap, 0.012))
    V = g.add(V, g.scale(pat, 0.008))                    # one-off marks repeat with the tile:
    #                                                      keep them faint; heroes go in decals
    V = g.sub(V, g.scale(hair, 0.25))
    V = g.sub(V, g.scale(p_edge, 0.02))
    # meso albedo at 2-8 cm (chalking and dirt blotches), clustered: photographed coated walls
    # carry 0.5-3 L* in this band, our first renders 0.05-0.1
    envm = g.scale(g.thr(g.fractal(0.35, 3, off=(23.0, 7.0)), 0.45, 0.6), 1.0, 0.35)
    blot = g.fractal(0.04, 3, 0.6, off=(29.0, 3.0))
    V = g.add(V, g.mul(g.scale(blot, 0.27, -0.135), envm))   # std 0.27 x 0.076 = 2 %
    base = g.n("constant", signature="f3", f3=(0.60, 0.585, 0.545))
    warm = g.n("constant", signature="f3", f3=(0.62, 0.595, 0.535))
    col = g.lerp(base, warm, g.scale(pat, 0.25), signature="f3")
    col = g.n("blend", col, V, mode="multiply")
    seal = g.n("constant", signature="f3", f3=(0.56, 0.55, 0.52))
    basecolor = g.n("null", g.lerp(col, seal, g.scale(bead, 0.25), signature="f3"), name="basecolor")

    Rg = g.scale(coatn, 0.04, 0.78)
    Rg = g.sub(Rg, g.scale(lap, 0.02))
    Rg = g.sub(Rg, g.scale(pat, 0.03))
    Rg = g.sub(Rg, g.scale(bead, 0.10))
    Rg = g.add(Rg, g.scale(hair, 0.06))
    rough = g.n("null", g.remap(Rg, 0.5, 1.0, 0.5, 1.0), name="roughness")

    HMIN, HMAX = -0.003, 0.003
    height01 = g.n("null", g.remap(height_m, HMIN, HMAX), name="height")
    nscale = 1.5 * 2.0 / tile_m
    normal = g.n("heighttonormal", height_m, name="normal", scale=nscale)
    ao = g.n("heighttoambientocclusion", height_m, heightscale=2.0 / tile_m, viewradius=U(0.02))
    # RGB only: Karma's texture reader (OIIO) premultiplies RGB by A when it loads an RGBA
    # PNG, so a fourth data channel goes in its own file (verified in round E)
    mask = g.n("channeljoin", coat01, pat, g.mx(bead, hair), name="mask", signature="f3")
    orm = g.n("channeljoin", ao, rough, g.const(0.0), name="orm", signature="f3")
    meta = dict(name="spraymacro", tile_m=tile_m, res=res, px_per_m=res / tile_m,
                height_range_m=[HMIN, HMAX], normal_scale=nscale,
                mask=dict(R="coat (detail strength, 1.0 = 1.5x)", G="repair patch",
                          B="crack and sealant bead"),
                lap="roller-lap and scaffold-lift overlap (own file)",
                stats_height_m=g.stats(height_m), stats_basecolor=g.stats(basecolor),
                stats_roughness=g.stats(rough), stats_coat=g.stats(coat),
                stats_patch_cover=g.stats(pat)["mean"])
    for nm, nd, kind in [("basecolor", basecolor, "color"), ("roughness", rough, "data"),
                         ("height", height01, "data16"), ("normal", normal, "data16"),
                         ("mask", mask, "data"), ("lap", lap, "data"), ("orm", orm, "data"),
                         ("ao", ao, "data")]:
        g.write(nd, os.path.join(OUT, f"spraymacro_{nm}.png"), kind)
    save_meta(os.path.join(OUT, "spraymacro_meta.json"), meta)
    return meta


if __name__ == "__main__":
    t0 = time.time()
    md = build_detail()
    mm = build_macro()
    print("built spray sets in %.1fs" % (time.time() - t0))
    for m in (md, mm):
        print({k: v for k, v in m.items() if k.startswith("stats")})
