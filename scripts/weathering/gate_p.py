"""Round-G pattern rule G6: no accidental lattice (roundG/research/grid-breakup.md 5.1-5.2). numpy only.

Per plane, axis and map (the dirt layers and D), on the painted wall:
  1. edge-energy profile: per column the trimmed mean of |dA/dx| over the wall rows (per row the
     same of |dA/dy|), gaps interpolated, high-passed (Gaussian 300 px), Hann window;
  2. periodogram normalised by its running median over +-(15 % + 3) bins (about 1 off-peak);
  3. building bins excluded: +-2 bins (a Hann main lobe) around every harmonic of the floor
     pitch, twice it, the bay pitch, the scaffold lift (1.8 m), and the peaks (> 8x) of the plane's
     own feature map (wall, openings and joints);
  4. harmonic sum: for periods of 16-600 px, the mean over the first 8 harmonics (>= 6 px) of the
     peak in +-1 bin. Pass: the largest <= 9 (tile-free controls 4.0-7.9; round F soiling 12.8).
"""
import numpy as np

import weather_measure as wm

G6_MAX = 9.0
G6_MAPS = ("L_soiling", "L_stains", "L_streaks", "L_base", "L_bio", "D")
LIFT_M = 1.8


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def profile(A, wall, axis):
    H, W = A.shape
    d = np.abs(np.diff(A, axis=axis))
    ok = (wall[:, 1:] & wall[:, :-1]) if axis == 1 else (wall[1:] & wall[:-1])
    ok &= np.isfinite(d)
    if ok.sum() < 1000:
        return None
    q = np.percentile(d[ok], 99.5)
    a = np.where(ok, np.minimum(d, q), 0.0)
    n = ok.sum(axis=0 if axis == 1 else 1)
    with np.errstate(all="ignore"):
        p = a.sum(axis=0 if axis == 1 else 1) / np.maximum(n, 1)
    good = n > 0.15 * (H if axis == 1 else W)
    if good.sum() < 64:
        return None
    x = np.arange(p.size)
    p = np.where(good, p, np.interp(x, x[good], p[good]))
    k = np.exp(-0.5 * (np.arange(-900, 901) / 300.0) ** 2)
    k /= k.sum()
    pad = min(900, p.size - 1)
    pp = np.pad(p, pad, mode="reflect")
    lo = np.convolve(pp, k, mode="same")[pad:pad + p.size]
    return p - lo


def norm_spec(p):
    S = np.abs(np.fft.rfft(p * np.hanning(p.size))) ** 2
    n = S.size
    bg = np.empty(n)
    for i in range(n):
        h = int(0.15 * i) + 3
        w = np.concatenate([S[max(1, i - h):max(1, i - 1)], S[i + 2:i + h + 1]])
        bg[i] = np.median(w) if w.size else S[i]
    Sn = S / np.maximum(bg, 1e-30)
    Sn[:3] = 1.0
    return Sn


def comb(n_px, nspec, periods, Sfeat=None):
    m = np.zeros(nspec, bool)
    for P in periods:
        if not P or P < 4:
            continue
        k = 1
        while k * n_px / P < nspec - 1:
            i = int(round(k * n_px / P))
            m[max(0, i - 2):i + 3] = True          # +-2: a Hann window's main lobe
            k += 1
    if Sfeat is not None:
        for i in np.flatnonzero(Sfeat > 8.0):
            m[max(0, i - 2):i + 3] = True
    return m


def harmonic_sum(Sn, bmask, n_px, K=8, Pmin=16.0, Pmax=600.0):
    best = []
    for P in np.exp(np.linspace(np.log(Pmin), np.log(min(Pmax, n_px / 3.0)), 1500)):
        tot, used = 0.0, 0
        for k in range(1, K + 1):
            if P / k < 6.0:
                break
            i = int(round(k * n_px / P))
            if i + 1 >= Sn.size:
                break
            seg = [j for j in (i - 1, i, i + 1) if not bmask[j]]
            if not seg:
                continue
            tot += max(Sn[j] for j in seg)
            used += 1
        if used >= 3:
            best.append((tot / used, P))
    best.sort(reverse=True)
    out, taken = [], []
    for v, P in best:
        if all(abs(np.log(P / t)) > 0.03 for t in taken):
            taken.append(P)
            out.append((round(float(P), 1), round(float(v), 2)))
        if len(out) == 3:
            break
    return out


def _pitch(rows):
    d = [b - a for a, b in zip(sorted(rows), sorted(rows)[1:]) if b - a > 40]
    return float(np.median(d)) if d else None


def scan_plane(p, maps=G6_MAPS):
    cls = p.get("cls")
    if cls is None:
        return {}
    wall = np.isin(cls, (1, 2)) & np.isfinite(p["D"])
    ppm = p["ppm"]
    feat = wall.copy()
    if "joint" in p:
        feat &= ~(np.asarray(p["joint"]) > 0)       # joints are building features too
    fp, bp = _pitch(p.get("floor_rows") or []), _pitch(p.get("bay_cols") or [])
    out = {}
    for axis, name in ((1, "x"), (0, "y")):
        fprof = profile(feat.astype(np.float64), np.ones_like(wall), axis)
        Sfeat = norm_spec(fprof) if fprof is not None else None
        periods = [bp] if axis == 1 else [fp, 2 * fp if fp else None, LIFT_M * ppm]
        for key in maps:
            if key not in p:
                continue
            A = np.nan_to_num(np.asarray(p[key], np.float64))
            if key != "D":                               # a layer's period needs the layer across the axis
                on = (A >= wm.TIER_EDGES[0]) & wall
                share = on.mean(axis=0 if axis == 1 else 1)
                if (share >= 0.01).mean() < 0.33:
                    continue
            pr = profile(A, wall, axis)
            if pr is None or np.abs(pr).max() < 1e-9:
                continue
            Sn = norm_spec(pr)
            bm = comb(pr.size, Sn.size, periods, Sfeat if Sfeat is not None and Sfeat.size == Sn.size else None)
            top = harmonic_sum(Sn, bm, pr.size)
            if top:
                out["%s/%s" % (key, name)] = top
    return out


def rule_G6(cfg, planes, R):
    if float(cfg.get("E", 0.0) or 0.0) <= 0:
        return res("G6", True, None, "no weathering")
    out, ok, worst = {}, True, 0.0
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        sc = scan_plane(p)
        if not sc:
            continue
        bad = {k: v[0] for k, v in sc.items() if v[0][1] > G6_MAX}
        worst = max([worst] + [v[0][1] for v in sc.values()])
        ok &= not bad
        top = max(sc.items(), key=lambda kv: kv[1][0][1])
        out[p["name"]] = {"max": top[1][0][1], "where": top[0], "top3": top[1], "over": bad}
    if not out:
        return res("G6", None, None, "no wall to scan")
    return res("G6", ok, {"limit": G6_MAX, "worst": round(worst, 2), "planes": out})
