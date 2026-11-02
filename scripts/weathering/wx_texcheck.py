"""wx_texcheck.py - the texture stage's rules (round I) on a build's fine composites:
T1 detail at game texel density, T2 no tile period shows, T3 the fine composite keeps the coarse
amounts. Called by weather_gate.py texture <build> (or directly).

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


def check(d):
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    planes = set(meta["planes"])
    return [rule_T1(), rule_T2(d, planes), rule_T3(d, planes)]


if __name__ == "__main__":
    d = sys.argv[1]
    out = check(d)
    for r in out:
        print("%-4s %s  %s %s" % (r["id"], {True: "pass", False: "FAIL", None: "na  "}[r["pass"]], json.dumps(r["value"])[:400], r["detail"]))
    if "--json" in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
