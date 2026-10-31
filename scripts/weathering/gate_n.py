"""Round-G edge rules, the N family (roundG/research/cracks-edges-damage.md 5.5 and 8.1: E5, E6,
E8, E9). At the facade scale (20 mm/px) an arris reads through its 1 px edge row, not a bevel.
Measured on the edge layer (L_wear, its darkening alone over the clean wall) and its chips.
numpy only.

N1 edge-row contrast: mean |delta L*| of the edge row (E9)
N2 band continuity: share of edge length carrying the band, |delta L*| >= 2 (E8)
N3 visible chips (>= 20 mm) per m of edge (E6)
N4 chips cluster: count variance over mean in 0.5 m windows (E5)
N5 tops lighter, drip and lower edges darker and warmer (E9)
"""
import numpy as np

import weather_measure as wm

XS = [0.25, 0.5, 0.75, 1.0]
E9 = [(3.0, 6.0), (4.0, 8.0), (6.0, 11.0), (7.0, 14.0)]
E8 = [(0.40, 0.70), (0.55, 0.80), (0.70, 0.90), (0.85, 1.0)]
E6 = [(0.04, 0.15), (0.19, 0.60), (0.35, 1.05), (0.50, 1.50)]


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg, layer):
    return float((cfg.get("amounts") or {}).get(layer, 0.0))


def band(a, table):
    if a < 0.25:
        return 0.0, table[0][1]
    return float(np.interp(a, XS, [t[0] for t in table])), float(np.interp(a, XS, [t[1] for t in table]))


def _lstar(Y):
    Y = np.clip(Y, 1e-6, None)
    f = np.where(Y > 216 / 24389, np.cbrt(Y), (24389 / 27 * Y + 16) / 116)
    return 116 * f - 16


def _edges(p):
    """Edge-row pixels on painted wall (the wear layer is off dark substrates), and their tone
    change from the edge layer alone as delta L* (+ lighter)."""
    if "L_wear" not in p or "edge" not in p or "Yc" not in p:
        return None
    cls = p.get("cls")
    e = p["edge"].astype(bool) & np.isfinite(p["D"])
    if cls is not None:
        e &= np.isin(cls, (1, 2))
    if e.sum() < 200:
        return None
    Yc = p["Yc"].astype(np.float64)
    Lw = np.nan_to_num(p["L_wear"].astype(np.float64))
    dL = _lstar(Yc * (1.0 - Lw)) - _lstar(Yc)
    return e, dL


def rule_N1(cfg, planes, R):
    a = _amount(cfg, "wear")
    if a <= 0:
        return res("N1", True, {"amount": a}, "no edge wear")
    v = [np.abs(r[1][r[0]]) for r in (_edges(p) for p in planes.values() if p.get("exposed", True)) if r]
    if not v:
        return res("N1", None, None, "no edge maps")
    m = float(np.concatenate(v).mean())
    lo, hi = band(a, E9)
    return res("N1", lo <= m <= hi, {"amount": round(a, 2), "edge_row_dL": round(m, 2), "band": [lo, hi]})


def rule_N2(cfg, planes, R):
    a = _amount(cfg, "wear")
    if a <= 0:
        return res("N2", True, {"amount": a}, "no edge wear")
    v = [np.abs(r[1][r[0]]) for r in (_edges(p) for p in planes.values() if p.get("exposed", True)) if r]
    if not v:
        return res("N2", None, None, "no edge maps")
    c = float((np.concatenate(v) >= 2.0).mean())
    lo, hi = band(a, E8)
    return res("N2", lo <= c <= hi, {"amount": round(a, 2), "continuity": round(c, 3), "band": [lo, hi]})


def _chips(p):
    if "wch_y" not in p:
        return np.zeros(0, int), np.zeros(0, int)
    return np.asarray(p["wch_y"]), np.asarray(p["wch_x"])


def rule_N3(cfg, planes, R):
    a = _amount(cfg, "wear")
    if a <= 0:
        return res("N3", True, {"amount": a}, "no edge wear")
    n = 0
    L = 0.0
    for p in planes.values():
        if not p.get("exposed", True) or "edge" not in p:
            continue
        L += p["edge"].astype(bool).sum() / p["ppm"]
        n += _chips(p)[0].size
    if L <= 0:
        return res("N3", None, None, "no edges")
    lam = n / L
    lo, hi = band(a, E6)
    return res("N3", lo <= lam <= hi, {"amount": round(a, 2), "chips_per_m": round(lam, 3), "band": [lo, hi]})


def rule_N4(cfg, planes, R):
    if _amount(cfg, "wear") <= 0:
        return res("N4", True, None, "no edge wear")
    counts = []
    for p in planes.values():
        if not p.get("exposed", True) or "edge" not in p:
            continue
        ys, xs = _chips(p)
        e = p["edge"].astype(bool)
        s = max(1, int(round(0.5 * p["ppm"])))
        H, W = e.shape
        h, w = H // s, W // s
        if h == 0 or w == 0:
            continue
        ecnt = e[:h * s, :w * s].reshape(h, s, w, s).sum(axis=(1, 3))
        ccnt = np.zeros((h, w))
        ok = (ys < h * s) & (xs < w * s)
        np.add.at(ccnt, (ys[ok] // s, xs[ok] // s), 1)
        counts.append(ccnt[ecnt >= 0.5 * s])
    if not counts or sum(c.sum() for c in counts) < 20:
        return res("N4", True, None, "under 20 chips")
    c = np.concatenate(counts)
    r = float(c.var() / max(c.mean(), 1e-9))
    return res("N4", r >= 1.2, {"chips": int(c.sum()), "var_over_mean": round(r, 2)})


def rule_N5(cfg, planes, R):
    if _amount(cfg, "wear") <= 0:
        return res("N5", True, None, "no edge wear")
    top, bot, bb = [], [], []
    for p in planes.values():
        if not p.get("exposed", True) or "etop" not in p:
            continue
        r = _edges(p)
        if r is None:
            continue
        e, dL = r
        et = np.asarray(p["etop"])
        on = np.abs(dL) >= 1.0
        t, b = e & on & ((et & 1) > 0), e & on & ((et & 2) > 0)
        top.append(dL[t])
        bot.append(dL[b])
        if "labw" in p:
            bb.append((p["labw"][..., 2] - p["labc"][..., 2])[b])
    if not top or sum(x.size for x in top) < 50 or sum(x.size for x in bot) < 50:
        return res("N5", True, None, "few banded edges")
    mt, mb = float(np.concatenate(top).mean()), float(np.concatenate(bot).mean())
    db = float(np.concatenate(bb).mean()) if bb else None
    ok = mt > 0 and mb < 0 and (db is None or 1.0 <= db <= 4.0)
    return res("N5", ok, {"top_dL": round(mt, 2), "bottom_dL": round(mb, 2), "bottom_db": None if db is None else round(db, 2)})


RULES = [rule_N1, rule_N2, rule_N3, rule_N4, rule_N5]
