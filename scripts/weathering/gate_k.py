"""Round-G damage rules (roundG/research/cracks-edges-damage.md 8.2-8.3; bands at amounts 0.25 /
0.5 / 0.75 / 1.0, interpolated linearly). numpy only.

K5  spalled area share of the wall (S1)
K6  spalls start at edges: share within 150 mm of an arris (S5)
K7  crack length per m2 of wall, wide-crack length and median width (C1, C2, C4)
K8  crack orientation, length-weighted, map cracks left out (C7)
K9  diagonal cracks sit at opening corners (C8)
K10 cracks are seen through what they carry: line contrast by width class (C19)
K11 repairs: share of wide-crack length under a repair stripe (C23)
"""
import numpy as np

import weather_measure as wm

XS = [0.25, 0.5, 0.75, 1.0]
S1 = [(0.0001, 0.001), (0.001, 0.005), (0.005, 0.03), (0.03, 0.10)]
C1 = [(0.2, 0.6), (0.5, 1.2), (1.0, 2.0), (1.5, 3.5)]
C2 = [(0.03, 0.15), (0.15, 0.4), (0.3, 0.8), (0.6, 1.5)]
C4 = [(0.1, 0.2), (0.17, 0.33), (0.23, 0.47), (0.3, 0.6)]
C7 = {"vertical": (0.40, 0.65), "diagonal": (0.20, 0.40), "horizontal": (0.10, 0.25)}
C19 = [("hairline", 0.0, 0.2, 0.0, 3.0), ("fine", 0.2, 0.5, 3.0, 8.0), ("wide", 0.5, 1.0, 5.0, 10.0),
       ("open", 1.0, 99.0, 8.0, 20.0)]
C23 = [(0.50, 0.90), (0.30, 0.60), (0.20, 0.50), (0.10, 0.40)]


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg, layer):
    return float((cfg.get("amounts") or {}).get(layer, 0.0))


def band(a, table, below_lo=0.0):
    """Pass band at amount a from a table at 0.25/0.5/0.75/1.0 (linear); under 0.25 the low end
    falls to below_lo."""
    lo = [t[0] for t in table]
    hi = [t[1] for t in table]
    if a < 0.25:
        return below_lo, hi[0]
    return float(np.interp(a, XS, lo)), float(np.interp(a, XS, hi))


def _wall(p):
    cls = p.get("cls")
    m = np.isfinite(p["D"])
    return m & np.isin(cls, (1, 2, 4, 5)) if cls is not None else m


def _dilate(m, r):
    out = m.astype(np.uint8)
    for ax in (0, 1):
        out = wm._sliding_max(out, r, ax)
    return out > 0


def _box_mean(a, r):
    out = a.astype(np.float64)
    for ax in (0, 1):
        out = wm._box1(out, r, ax)
    return out


def rule_K5(cfg, planes, R):
    a = _amount(cfg, "damage")
    if a <= 0:
        return res("K5", True, {"amount": a}, "no damage")
    sp = area = 0.0
    for p in planes.values():
        if not p.get("exposed", True) or "dmg_a" not in p:
            continue
        w = _wall(p)
        area += w.sum() / p["ppm"] ** 2
        sp += ((p["dmg_a"].astype(np.float32) >= 0.5) & w).sum() / p["ppm"] ** 2
    if area <= 0:
        return res("K5", None, None, "no damage maps")
    s = sp / area
    lo, hi = band(a, S1)
    return res("K5", lo <= s <= hi, {"amount": round(a, 2), "spalled_pct": round(100 * s, 3),
                                     "band_pct": [round(100 * lo, 3), round(100 * hi, 3)]})


def rule_K6(cfg, planes, R):
    a = _amount(cfg, "damage")
    if a <= 0:
        return res("K6", True, {"amount": a}, "no damage")
    n = near = 0
    for p in planes.values():
        if not p.get("exposed", True) or "dmg_a" not in p or "edge" not in p:
            continue
        s = (p["dmg_a"].astype(np.float32) >= 0.5) & _wall(p)
        lab, k = wm.label(s)
        if k == 0:
            continue
        cnt = np.bincount(lab.ravel(), minlength=k + 1)
        big = cnt >= 2                                       # >= 30 mm across
        big[0] = False
        ez = _dilate(p["edge"].astype(bool), max(1, int(round(0.15 * p["ppm"]))))
        hit = np.zeros(k + 1, bool)
        hit[np.unique(lab[ez & s])] = True
        n += int(big.sum())
        near += int((big & hit).sum())
    if n < 10:
        return res("K6", True, {"spalls": n}, "under 10 spalls")
    sh = near / n
    return res("K6", sh >= 0.50, {"spalls": n, "near_edge_share": round(sh, 3)})


def _cracks(planes):
    for p in planes.values():
        if p.get("exposed", True) and "crk_w" in p:
            yield p


def rule_K7(cfg, planes, R):
    a = _amount(cfg, "cracks")
    if a <= 0:
        return res("K7", True, {"amount": a}, "no cracks")
    L = L3 = area = 0.0
    ws = []
    for p in _cracks(planes):
        w = p["crk_w"].astype(np.float32)
        wall = _wall(p)
        area += wall.sum() / p["ppm"] ** 2
        vis = (w >= 0.05) & wall
        L += vis.sum() / p["ppm"]
        L3 += ((w >= 0.3) & wall).sum() / p["ppm"]
        ws.append(w[vis])
    if area <= 0:
        return res("K7", None, None, "no crack maps")
    rho, rho3 = L / area, L3 / area
    med = float(np.median(np.concatenate(ws))) if ws and sum(x.size for x in ws) else 0.0
    b1, b2, b4 = band(a, C1), band(a, C2), band(a, C4)
    ok = b1[0] <= rho <= b1[1] and b2[0] <= rho3 <= b2[1] and b4[0] <= med <= b4[1]
    return res("K7", ok, {"amount": round(a, 2), "m_per_m2": round(rho, 3), "band": [round(v, 3) for v in b1],
                          "wide_m_per_m2": round(rho3, 3), "wide_band": [round(v, 3) for v in b2],
                          "median_mm": round(med, 3), "median_band": [round(v, 3) for v in b4]})


def _orient_shares(planes):
    tot = {"vertical": 0, "diagonal": 0, "horizontal": 0}
    for p in _cracks(planes):
        t = p["crk_t"].astype(np.uint8) & 15
        m = (p["crk_w"].astype(np.float32) >= 0.05) & (t > 0) & (t != 4)
        o = p["crk_o"].astype(np.float32)[m]
        tot["vertical"] += int(((o >= 67.5) & (o < 112.5)).sum())
        tot["horizontal"] += int(((o < 22.5) | (o >= 157.5)).sum())
        tot["diagonal"] += int((((o >= 22.5) & (o < 67.5)) | ((o >= 112.5) & (o < 157.5))).sum())
    return tot


def rule_K8(cfg, planes, R):
    if _amount(cfg, "cracks") <= 0:
        return res("K8", True, None, "no cracks")
    tot = _orient_shares(planes)
    n = sum(tot.values())
    if n < 500:
        return res("K8", True, {"px": n}, "few cracks")
    sh = {k: round(v / n, 3) for k, v in tot.items()}
    ok = all(C7[k][0] <= sh[k] <= C7[k][1] for k in C7)
    return res("K8", ok, {"shares": sh, "bands": C7})


def rule_K9(cfg, planes, R):
    if _amount(cfg, "cracks") <= 0:
        return res("K9", True, None, "no cracks")
    n = near = 0
    for p in _cracks(planes):
        if "openings" not in p:
            continue
        t = p["crk_t"].astype(np.uint8) & 15
        o = p["crk_o"].astype(np.float32)
        m = (p["crk_w"].astype(np.float32) >= 0.05) & (t > 0) & (t != 4)
        m &= ((o >= 22.5) & (o < 67.5)) | ((o >= 112.5) & (o < 157.5))
        ys, xs = np.nonzero(m)
        if ys.size == 0:
            continue
        ops = np.asarray(p["openings"])
        best = np.full(ys.size, np.inf)
        for (y0, x0, y1, x1) in ops:
            ow = max(1.0, float(x1 - x0 + 1))
            for (cy, cx) in ((y0, x0), (y0, x1), (y1, x0), (y1, x1)):
                d = np.hypot(ys - cy, xs - cx) / ow
                best = np.minimum(best, d)
        n += ys.size
        near += int((best <= 1.0).sum())
    if n < 200:
        return res("K9", True, {"px": n}, "few diagonal cracks")
    sh = near / n
    return res("K9", sh >= 0.70, {"diagonal_px": n, "at_corner_share": round(sh, 3)})


def rule_K10(cfg, planes, R):
    if _amount(cfg, "cracks") <= 0:
        return res("K10", True, None, "no cracks")
    acc = {c[0]: [] for c in C19}
    for p in _cracks(planes):
        if "labw" not in p:
            continue
        w = p["crk_w"].astype(np.float32)
        t = p["crk_t"].astype(np.uint8)
        crack = (w > 0) & (t < 16) & _wall(p)
        if not crack.any():
            continue
        Lw = p["labw"][..., 0].astype(np.float64)
        keep = (~_dilate(crack, 1)) & _wall(p)
        num = _box_mean(np.where(keep, Lw, 0.0), 3)
        den = _box_mean(keep.astype(np.float64), 3)
        ref = np.where(den > 0.05, num / np.maximum(den, 1e-9), np.nan)
        dL = ref - Lw
        for (name, lo, hi, _a, _b) in C19:
            sel = crack & (w >= lo) & (w < hi) & np.isfinite(dL)
            if sel.any():
                acc[name].append(dL[sel])
    out, ok = {}, True
    for (name, lo, hi, blo, bhi) in C19:
        if not acc[name] or sum(x.size for x in acc[name]) < 50:
            continue
        v = float(np.median(np.concatenate(acc[name])))
        good = (v <= bhi) if name == "hairline" else (blo <= v <= bhi)
        ok &= good
        out[name] = {"dL": round(v, 2), "band": [blo, bhi], "ok": bool(good)}
    if not out:
        return res("K10", True, None, "few cracks")
    return res("K10", ok, out)


def rule_K11(cfg, planes, R):
    a = _amount(cfg, "cracks")
    if a <= 0:
        return res("K11", True, None, "no cracks")
    n = rep = 0
    for p in _cracks(planes):
        w = p["crk_w"].astype(np.float32)
        t = p["crk_t"].astype(np.uint8)
        m = (w >= 0.3) & (t > 0)
        n += int(m.sum())
        rep += int((m & (t >= 16)).sum())
    if n < 200:
        return res("K11", True, {"px": n}, "few wide cracks")
    sh = rep / n
    lo, hi = band(a, C23, below_lo=C23[0][0])
    return res("K11", lo <= sh <= hi, {"amount": round(a, 2), "repaired_share": round(sh, 3),
                                       "band": [round(lo, 2), round(hi, 2)]})


RULES = [rule_K5, rule_K6, rule_K7, rule_K8, rule_K9, rule_K10, rule_K11]
