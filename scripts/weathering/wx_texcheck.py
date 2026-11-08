"""wx_texcheck.py - the texture stage's rules on a build's fine composites: T0 (round J) the player's screen
gets at most 2 screen pixels per texel of each detail carrier at its nearest approach, T1 detail at game
texel density, T2 no tile period shows, T3 the fine composite keeps the coarse amounts; and the close-up
parts of P3 (flakes) and R7 (rims round rust). Called by weather_gate.py texture <build> (or directly).

python -I wx_texcheck.py <build_dir> [--json out.json]
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_hires as wh  # noqa: E402

# fixed check windows per plane (50 px/m boxes): open wall away from openings, and a close-up spot
WINDOWS = {"S_front": {"open": (1260, 400, 1460, 600), "close": (1323, 380, 1423, 440)},
           "N_front": {"open": (2580, 730, 2780, 930)},     # round I: plain wall (was 1260-1460: 21 % windows,
                                                             # a pipe and meter boxes repeating every storey)
           "W_gable": {"open": (200, 900, 500, 1200)}}
T1C = {"detail_ppm": 1000.0, "coat_ppm": 1000.0}
# round J (research art-review-and-qa.md 6.1-6.2): screen px per metre at a player's camera,
# p = W / (2 tan(HFOV / 2) d), UE's 90 deg horizontal FOV on a 3,840 px (4K) screen; the danchi's
# metrics sheet: nearest approach per surface class (walls and railings 1.0 m: a player at the wall,
# the far end of the research's walkway range; entrances and stair cores at 0.5 m are not in these
# planes). Detail carriers fail above 2 screen px per texel; the 50 px/m masks may exceed it because the
# detail reveals their edges (the edge rule).
T0C = {"screen_px": 3840, "hfov_deg": 90.0, "d_min": {"wall": 1.0, "rail": 1.0}, "max_m": 2.0,
       "report_d": (0.5, 1.0, 2.0, 5.0, 20.0)}
P3C = {"window": ("S_front", (1700, 1696, 1800, 1786), 1000.0), "ramp_px": 1.5, "b_L": (55.0, 68.0), "b_C": 4.0,
       "a_dL": (2.0, 10.0), "a_dab": 2.0, "size_mm": {"worn": (3.0, 30.0), "derelict": (10.0, 1e9)}}
R7CC = {"window": ("S_front", (1800, 1275, 1940, 1355), 1000.0), "patch_mm": 20.0, "rim_px": 2, "rim_share": 0.30,
        "edge_mm": 10.0,                                      # J28: patches with under 1 cm of edge on painted steel are left out
        "patches_share": 0.50}
T2C = {"ppm": 200.0, "max_excess": 0.15}
T3C = {"mean": 0.03, "p05": 0.85, "p95": 1.15, "erode_px": 1}


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def rule_T1():
    """Every detail tile and the coat's detail at 1,000 px/m or more."""
    vals = {}
    for name in sorted({v[1] for v in wh.REFINE.values() if v[1]}):
        t = wh.tile(name)
        vals[name] = round(t.u.shape[1] / t.w_m, 1)
    C = wh.coat()
    vals["coat_detail"] = round(C["detail"].shape[1] / C["det_m"], 1)
    vals["coat_macro"] = round(C["macro"].shape[1] / C["tile_m"], 1)
    low = [k for k, v in vals.items() if k != "coat_macro" and v < T1C["detail_ppm"]]
    return res("T1", not low, vals, ("below %d px/m: %s" % (T1C["detail_ppm"], low)) if low else "")


def coef_excess(Y, lag_px):
    """Correlation coefficient of a (high-passed) image at lag (0, L) and (L, 0), less the median over
    the ring at that radius: a tile repeating at L scores near its share of the variance (plain
    wrapped tiles 0.98), hex-tiled or untiled detail near 0 (research tiling-and-distribution-algorithms)."""
    f = Y - Y.mean()
    H, W = f.shape
    F = np.fft.rfft2(f, s=(2 * H, 2 * W))
    ac = np.fft.fftshift(np.fft.irfft2(np.abs(F) ** 2, s=(2 * H, 2 * W)))
    cy, cx = ac.shape[0] // 2, ac.shape[1] // 2
    yy, xx = np.mgrid[0:ac.shape[0], 0:ac.shape[1]]
    rho = ac / np.maximum((H - np.abs(yy - cy)) * (W - np.abs(xx - cx)), 1) / max(float(f.var()), 1e-12)
    ring = np.abs(np.hypot(yy - cy, xx - cx) - lag_px) < 1.5
    return max(float(rho[cy, cx + lag_px]), float(rho[cy + lag_px, cx])) - float(np.median(rho[ring]))


def rule_T2(d, planes):
    """At each tile period the luminance correlation of open wall at 200 px/m exceeds its ring's median
    by 0.15 or less."""
    out, bad = {}, []
    periods = {"coat": wh.coat()["tile_m"], "coat_detail": wh.coat()["det_m"]}
    for name in sorted({v[1] for v in wh.REFINE.values() if v[1]}):
        t = wh.tile(name)
        periods[name] = t.w_m
        if t.h_m != t.w_m:
            periods[name + "_h"] = t.h_m
    for plane, wins in WINDOWS.items():
        if plane not in planes or "open" not in wins:
            continue
        res_ = wh.compose(d, plane, wins["open"], T2C["ppm"])
        Y = res_["albedo"] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        Y = Y - wh._box_blur(Y, int(0.05 * T2C["ppm"]))          # high-pass: the detail's own structure
        st = {}
        for k, P in periods.items():
            lag = int(round(P * T2C["ppm"]))
            if lag >= min(Y.shape) - 2:
                continue
            st[k] = round(coef_excess(Y, lag), 3)
            if st[k] > T2C["max_excess"]:
                bad.append("%s %s %.2f" % (plane, k, st[k]))
        out[plane] = st
    return res("T2", not bad, out, "; ".join(bad))


def rule_T3(d, planes):
    """The fine composite box-filtered to 50 px/m against the build: luminance ratio over walls."""
    out, bad = {}, []
    for plane, wins in WINDOWS.items():
        if plane not in planes:
            continue
        for k, box in wins.items():
            ppm = 1000.0 if k == "close" else 200.0
            r = wh.compose(d, plane, box, ppm)
            c = check_mean_eroded(r, d, plane)
            out["%s/%s" % (plane, k)] = c
            if abs(c["mean_ratio"] - 1) > T3C["mean"] or c["p05"] < T3C["p05"] or c["p95"] > T3C["p95"]:
                bad.append("%s/%s" % (plane, k))
    return res("T3", not bad, out, ", ".join(bad))


def check_mean_eroded(res_, d, plane):
    R = res_["region"]
    z = np.load(os.path.join(d, plane + ".npz"))
    f = int(round(R.ppm / wh.P50))
    A = res_["albedo"]
    H, W = (A.shape[0] // f) * f, (A.shape[1] // f) * f
    lum = np.array([0.2126, 0.7152, 0.0722], np.float32)
    Yf = (A[:H, :W] @ lum).reshape(H // f, f, W // f, f).mean(axis=(1, 3))
    x0, y0 = int(round(R.X[0] * wh.P50 - 0.5)), int(round(R.Y[0] * wh.P50 - 0.5))
    Yc = z["rgb"][y0:y0 + H // f, x0:x0 + W // f].astype(np.float32) @ lum
    wall = np.isin(z["cls"][y0:y0 + H // f, x0:x0 + W // f], (1, 2))
    e = T3C["erode_px"]
    core = wall.copy()
    for dy in range(-e, e + 1):
        for dx in range(-e, e + 1):
            core &= np.roll(np.roll(wall, dy, 0), dx, 1)
    r = (Yf / np.maximum(Yc, 1e-4))[core]
    return {"mean_ratio": round(float(r.mean()), 4), "p05": round(float(np.percentile(r, 5)), 4),
            "p95": round(float(np.percentile(r, 95)), 4), "px": int(core.sum())}


def screen_ppm(d_m):
    return T0C["screen_px"] / (2.0 * np.tan(np.radians(T0C["hfov_deg"]) / 2.0) * d_m)


def rule_T0():
    """T0 (round J): magnification m = screen px per metre at the nearest approach / the carrier's px per
    metre, for every detail carrier; fail above 2. The masks are reported, not judged (edge rule)."""
    car = {}
    for name in sorted({v[1] for v in wh.REFINE.values() if v[1]}):
        t = wh.tile(name)
        car[name] = t.u.shape[1] / t.w_m
    C = wh.coat()
    car["coat_detail"] = C["detail"].shape[1] / C["det_m"]
    import wx_concrete as wc
    car["concrete"] = wc.N / wc.TILE_M
    d0 = T0C["d_min"]["wall"]
    m = {k: round(screen_ppm(d0) / v, 2) for k, v in car.items()}
    rep = {}
    for d_ in T0C["report_d"]:
        rep["%g m" % d_] = {"screen_px_m": round(screen_ppm(d_), 1), "detail_1000": round(screen_ppm(d_) / 1000.0, 2),
                            "mask_50": round(screen_ppm(d_) / 50.0, 1)}
    bad = [k for k, v in m.items() if v > T0C["max_m"]]
    return res("T0", not bad, {"d_min_m": d0, "magnification": m, "by_distance": rep},
               ("over %g at %g m: %s" % (T0C["max_m"], d0, bad)) if bad else "")


def _lab(A):
    import weather_measure as wm
    return wm.linear_to_lab(np.clip(A, 0, 1).astype(np.float64))


def rule_P3c(d, planes, preset):
    """P3 at 1 mm/px: flake outlines crisp (the 0.9-0.1 ramp <= 1.5 px), typical flake size by preset (ISO
    4628-5 size classes: Worn 3-30 mm, Derelict 10 mm and up), type-b flakes show concrete (L* 55-68,
    C* <= 4), type-a flakes an older coat 2-10 L* lighter than the paint round them."""
    plane, box, ppm = P3C["window"]
    early = preset in ("new", "kept", "typical")
    if plane not in planes:
        return res("P3", None, None, "no window plane")
    r = wh.compose(d, plane, box, ppm)
    ex = r.get("extra") or {}
    if "peel_a" not in ex:
        return res("P3", True if early else None, None, "no flakes in the window")
    a, pk, b = ex["peel_a"], ex["peel_pk"], ex["peel_b"]
    mrel = np.clip(a / np.maximum(pk, 1e-6), 0, 1)
    core = mrel > 0.9
    if core.sum() < 30:
        return res("P3", True if early else None, {"flake_px": int(core.sum())}, "too few flake pixels")
    bm = mrel > 0.5                                      # J21: the mean 0.9-0.1 width, partial px per outline px
    per = bm & ~(np.roll(bm, 1, 0) & np.roll(bm, -1, 0) & np.roll(bm, 1, 1) & np.roll(bm, -1, 1))
    tr = (mrel > 0.1) & (mrel < 0.9)
    ramp = float(tr.sum()) / max(float(per.sum()), 1.0)
    import weather_measure as wm
    lab_, n = wm.label(mrel > 0.5)
    sizes = np.bincount(lab_.ravel())[1:]
    dmm = 2 * np.sqrt(sizes / np.pi) * 1000.0 / ppm
    typ = float(np.sum(dmm * sizes) / max(np.sum(sizes), 1))          # area-weighted mean size (mm)
    L = _lab(r["albedo"])
    C = np.hypot(L[..., 1], L[..., 2])
    tb = core & (b > 0.5)
    ta = core & (b < 0.5)
    def _grow(m_, rr_):
        o_ = m_.copy()
        for dy in range(-rr_, rr_ + 1):
            for dx in range(-rr_, rr_ + 1):
                if dy * dy + dx * dx <= rr_ * rr_:
                    o_ |= np.roll(np.roll(m_, dy, 0), dx, 1)
        return o_
    fl_ = mrel > 0.5                                   # J16: the paint 3-8 mm out, past the 1.5 mm lip
    ring = _grow(fl_, max(3, int(0.008 * ppm))) & ~_grow(fl_, max(2, int(0.003 * ppm)))
    ring &= ~(mrel > 0.1) & np.isin(r["cls"], (1, 2))
    v = {"ramp_px": round(ramp, 2), "flakes": int(n), "typical_mm": round(typ, 1),
         "largest_mm": round(float(dmm.max()) if dmm.size else 0.0, 1)}
    oks = [ramp <= P3C["ramp_px"]]
    if tb.sum() >= 30:
        v["type_b_L"] = round(float(np.median(L[..., 0][tb])), 1)
        v["type_b_C"] = round(float(np.median(C[tb])), 2)
        oks += [P3C["b_L"][0] <= v["type_b_L"] <= P3C["b_L"][1], v["type_b_C"] <= P3C["b_C"]]
    if ta.sum() >= 30 and ring.sum() >= 30:              # J21: 2-10 L* lighter, or a hue step away
        dL = float(np.median(L[..., 0][ta]) - np.median(L[..., 0][ring]))
        dab = float(np.hypot(np.median(L[..., 1][ta]) - np.median(L[..., 1][ring]),
                             np.median(L[..., 2][ta]) - np.median(L[..., 2][ring])))
        v["type_a_dL"], v["type_a_dab"] = round(dL, 1), round(dab, 1)
        oks.append(P3C["a_dL"][0] <= dL <= P3C["a_dL"][1] or (abs(dL) <= P3C["a_dL"][1] and dab >= P3C["a_dab"]))
    sb = P3C["size_mm"].get(preset)
    if sb is not None:
        oks.append(sb[0] <= typ <= sb[1])
    return res("P3", all(oks), v)


def rule_R7c(d, planes, rust_amount):
    """R7 at 1 mm/px: from rust 0.5, >= 50 % of rust patches of 2 cm or more have exposed metal or lifted
    paint on >= 30 % of their perimeter."""
    if rust_amount < 0.5 - 1e-6:
        return res("R7c", True, {"rust": rust_amount}, "applies from rust 0.5")
    plane, box, ppm = R7CC["window"]
    if plane not in planes:
        return res("R7c", None, None, "no window plane")
    r = wh.compose(d, plane, box, ppm)
    ex = r.get("extra") or {}
    if "rust_a" not in ex:
        return res("R7c", None, None, "no rust anatomy in the window")
    import weather_measure as wm
    core = ex["rust_a"] > 0.12
    rim = ex["rim"]
    lab_, n = wm.label(core)
    if n == 0:
        return res("R7c", None, None, "no rust")
    sizes = np.bincount(lab_.ravel())
    min_px = np.pi * (0.5 * R7CC["patch_mm"] * ppm / 1000.0) ** 2
    er = core & np.roll(core, 1, 0) & np.roll(core, -1, 0) & np.roll(core, 1, 1) & np.roll(core, -1, 1)
    edge = core & ~er
    near = rim.copy()
    for _ in range(R7CC["rim_px"]):
        near = near | np.roll(near, 1, 0) | np.roll(near, -1, 0) | np.roll(near, 1, 1) | np.roll(near, -1, 1)
    st_ = ex.get("steel")                                  # J28: the perimeter where it borders painted steel
    paint = (st_ & ~core) if st_ is not None else ~core
    pn = paint | np.roll(paint, 1, 0) | np.roll(paint, -1, 0) | np.roll(paint, 1, 1) | np.roll(paint, -1, 1)
    edge = edge & pn
    tot = np.bincount(lab_[edge], minlength=n + 1)
    hit = np.bincount(lab_[edge & near], minlength=n + 1)
    min_edge = R7CC["edge_mm"] * ppm / 1000.0
    big = [i for i in range(1, n + 1) if sizes[i] >= min_px and tot[i] >= min_edge]
    if not big:
        return res("R7c", None, {"patches": 0}, "no rust patch of 2 cm or more in the window")
    shares = [hit[i] / tot[i] for i in big]
    ok_share = float(np.mean([s_ >= R7CC["rim_share"] for s_ in shares]))
    return res("R7c", ok_share >= R7CC["patches_share"], {"patches": len(big), "with_rim": round(ok_share, 3),
                                                         "median_rim_share": round(float(np.median(shares)), 3)})


def check(d):
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    planes = set(meta["planes"])
    cfg = meta.get("config", {})
    ov = cfg.get("override") or {}
    rust = float(ov.get("rust", (meta.get("amounts") or {}).get("rust", 0)) or 0)
    return [rule_T0(), rule_T1(), rule_T2(d, planes), rule_T3(d, planes),
            rule_P3c(d, planes, str(cfg.get("preset") or "")), rule_R7c(d, planes, rust)]


if __name__ == "__main__":
    d = sys.argv[1]
    out = check(d)
    for r in out:
        print("%-4s %s  %s %s" % (r["id"], {True: "pass", False: "FAIL", None: "na  "}[r["pass"]], json.dumps(r["value"])[:400], r["detail"]))
    if "--json" in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
