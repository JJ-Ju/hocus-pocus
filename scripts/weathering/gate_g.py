"""Round-G rules (streaks): H4 long streaks, H5 a darker subset, G5 seam crossings, and L4 the
streak control's top step. Imported by weather_gate; numpy only."""
import numpy as np

import weather_measure as wm


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg, layer):
    return float((cfg.get("amounts") or {}).get(layer, 0.0))


def _dilate(m, r, axes=(0, 1)):
    out = m.astype(np.uint8)
    for ax in axes:
        out = wm._sliding_max(out, r, ax)
    return out > 0


def col_runs(S, ppm, gap_m=0.6, band_px=3):
    """Per column: the longest vertical run of streak pixels (m), gaps up to gap_m bridged and a
    run allowed to wobble band_px either side."""
    Sb = _dilate(S, band_px, axes=(1,))
    g = max(1, int(gap_m * ppm / 2))
    Sd = _dilate(Sb, g, axes=(0,))
    H, W = Sd.shape
    run = np.zeros(W)
    best = np.zeros(W)
    for y in range(H):
        run = np.where(Sd[y], run + 1, 0)
        best = np.maximum(best, run)
    return np.maximum(best - 2 * g, 0) / ppm


def streak_runs(p):
    """(reach as a share of the wall height, distinct runs >= 3 m per 25 m of width) or None."""
    tr, gr = p.get("top_row"), p.get("ground_row")
    if tr is None or gr is None or "L_streaks" not in p:
        return None
    ppm = p["ppm"]
    Hw = (gr - tr) / ppm
    if Hw < 8.0:
        return None
    S = np.nan_to_num(p["L_streaks"]) >= wm.TIER_EDGES[1]
    best = col_runs(S, ppm)
    xs = np.flatnonzero(best >= 3.0)
    n_long, last = 0, -10 ** 9
    for x in xs:
        if x - last > ppm:
            n_long += 1
        last = x
    width_m = np.isfinite(p["D"]).any(axis=0).sum() / ppm
    return float(best.max() / Hw), n_long / max(width_m, 1.0) * 25.0, float(best.max())


H4_REACH = (0.35, 0.40)      # reach >= a0 + a1 x amount (share of the wall height)
H4_LONG = (1.0, 3.5)         # runs >= 3 m per 25 m of width >= b0 + b1 x amount


def rule_H4(cfg, planes, R):
    a = _amount(cfg, "streaks")
    if a < 0.25:
        return res("H4", True, {"amount": a}, "few streaks")
    out, ok = {}, True
    need_r, need_n = H4_REACH[0] + H4_REACH[1] * a, H4_LONG[0] + H4_LONG[1] * a
    for p in planes.values():
        if not p.get("exposed", True) or p.get("kind") not in ("wall", "gable", "front"):
            continue
        r = streak_runs(p)
        if r is None:
            continue
        reach, per25, longest = r
        good = reach >= need_r and per25 >= need_n
        ok &= good
        out[p["name"]] = {"reach": round(reach, 2), "longest_m": round(longest, 1), "long_per_25m": round(per25, 1)}
    if not out:
        return res("H4", None, None, "no wall of 3 storeys or more")
    return res("H4", ok, {"amount": round(a, 2), "need_reach": round(need_r, 2), "need_long_per_25m": round(need_n, 1),
                          "planes": out})


def rule_H5(cfg, planes, R):
    a = _amount(cfg, "streaks")
    if a < 0.25:
        return res("H5", True, {"amount": a}, "few streaks")
    vals = []
    for p in planes.values():
        if not p.get("exposed", True) or "L_streaks" not in p:
            continue
        mk = wm.marks(np.nan_to_num(p["L_streaks"]), p["ppm"], thr=wm.TIER_EDGES[1])
        vals += [m["mean"] for m in mk if m["h_m"] >= 0.3]
    if len(vals) < 20:
        return res("H5", None, {"marks": len(vals)}, "under 20 streaks of 0.3 m")
    v = np.array(vals)
    r = float(np.percentile(v, 90) / max(np.median(v), 1e-6))
    return res("H5", r >= 1.8, {"marks": len(vals), "p90_over_median": round(r, 2)})


def rule_G5(cfg, planes, R):
    if _amount(cfg, "streaks") < 0.2:
        return res("G5", True, {"amount": _amount(cfg, "streaks")}, "few streaks")
    out, ok, any_ = {}, True, False
    for p in planes.values():
        if "joint" not in p or not p.get("exposed", True):
            continue
        j = p["joint"].astype(np.uint8)
        jh, jv = (j & 1) > 0, (j & 2) > 0
        if not jh.any() or not jv.any():
            continue
        xm = jh & _dilate(jv, 2, axes=(1,))
        if xm.sum() < 3:
            continue
        any_ = True
        D = np.nan_to_num(p["D"])
        ppm = p["ppm"]
        near = _dilate(xm, 2) & (jh | jv)                     # joint pixels at the crossing
        ring = (jh | jv) & ~_dilate(xm, int(0.2 * ppm)) & _dilate(xm, int(0.6 * ppm))
        if ring.sum() < 20:
            continue
        r = float(D[near].mean() / max(D[ring].mean(), 1e-4))
        good = 1.15 <= r <= 2.0
        ok &= good
        out[p["name"]] = round(r, 2)
    if not any_:
        return res("G5", True, None, "no seam crossings")
    return res("G5", ok, out)


L4_TOP = {"streaks": (0.035, 0.012)}     # at the control's top step: layer T2+ and T4+ (exposed walls)


def series_top(layer, runs, vals):
    """L4: the control's top step is strong (streaks: round F's 1.0 was 'even the last is too weak')."""
    if layer not in L4_TOP or not runs:
        return None
    cfg, planes = runs[-1]
    v = []
    for p in planes.values():
        if p.get("exposed", True) and ("L_" + layer) in p:
            x = np.asarray(p["L_" + layer], np.float64)
            m = np.isfinite(p["D"])
            v.append(x[m])
    if not v:
        return res("L4", None, None, "no layer map")
    v = np.nan_to_num(np.concatenate(v))
    t2, t4 = float((v >= wm.TIER_EDGES[1]).mean()), float((v >= wm.TIER_EDGES[3]).mean())
    need2, need4 = L4_TOP[layer]
    return res("L4", t2 >= need2 and t4 >= need4, {"top_value": vals[-1] if vals else None, "T2+": round(t2, 4),
                                                    "T4+": round(t4, 4), "need": [need2, need4]})


def _layer_vals(planes, key):
    v = []
    for p in planes.values():
        if p.get("exposed", True) and key in p:
            x = np.asarray(p[key], np.float64)
            cls = p.get("cls")
            dom = np.isin(cls, (1, 2)) if cls is not None else np.ones(x.shape, bool)
            if key == "L_rust" and "steel" in p:          # rust is measured on the steel too (round H), by the
                dom = dom | np.asarray(p["steel"]).astype(bool)   # size of its change: on dark rails it lightens
                m = np.isfinite(x) & dom
                x = np.abs(x)
            else:
                m = np.isfinite(p["D"]) & dom
            v.append(np.nan_to_num(x[m]))
    return np.concatenate(v) if v else None


def series_even(layer, runs, vals):
    """L3: the control's steps look even: per step, the ratio of the layer's mean D and of its
    coverage at the frontier tier (the lowest tier under half the wall at the first step shown);
    the largest ratio over the smallest. Steps from 0 and the damage control are left out."""
    if layer == "damage":
        return None
    ser = []
    for (cfg, planes), v in zip(runs, vals):
        x = _layer_vals(planes, "L_" + layer)
        if x is None or (v is not None and float(v) <= 0):
            continue
        ser.append((float(v) if v is not None else None, x))
    if len(ser) < 3:
        return res("L3", True, {"steps": len(ser)}, "under three steps above 0")
    first = ser[0][1]
    tier = next((t for t in wm.TIER_EDGES[1:] if (first >= t).mean() < 0.5), wm.TIER_EDGES[-1])
    ms = [float(np.clip(x, 0, None).mean()) for _, x in ser]
    cs = [float((x >= tier).mean()) for _, x in ser]
    rm = [b / a for a, b in zip(ms, ms[1:]) if a > 1e-5]
    rc = [b / a for a, b in zip(cs, cs[1:]) if 1e-5 < a <= 0.5]     # a tier past half the wall cannot show a step
    em = max(rm) / min(rm) if rm and min(rm) > 0 else None
    ec = max(rc) / min(rc) if rc and min(rc) > 0 else None
    ok = (em is None or em <= 1.5) and (ec is None or ec <= 1.4)
    return res("L3", ok, {"values": [s[0] for s in ser], "tier": tier, "mean_ratios": [round(r, 2) for r in rm],
                          "cover_ratios": [round(r, 2) for r in rc], "mean_evenness": None if em is None else round(em, 2),
                          "cover_evenness": None if ec is None else round(ec, 2)})
