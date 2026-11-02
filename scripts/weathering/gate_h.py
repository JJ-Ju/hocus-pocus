"""gate_h.py - round-H rules: colour families (I4, I5), seeds and preset steps (A5, A6), growth
darkening with age (M9) and rust on steel (R1, R2). Imported by weather_gate."""
import json
import os

import numpy as np

import weather_measure as wm

PAINTED = (1, 2)
FAM_LAYERS = ("L_streaks", "L_stains", "L_base")
I4 = {"E_min": 8.0, "mark_D": 0.05, "green": (100.0, 180.0, -1.0), "yellow": (70.0, 100.0, 3.0),
      "olive": (105.0, 130.0, 2.0), "share": (0.05, 0.04, 0.35), "plane_min": 0.02, "olive_max": 0.35}
RUST_GRADE = ((0.25, 0.5, 0.75, 1.0), (0.05, 0.10, 0.20, 0.40))   # ISO 4628-3: Ri3-4, Ri4, Ri4-5, Ri5
RUST_BAND = (0.5, 2.0)          # the measured share of steel over the grade's share
RUST_VISIBLE = 8.0              # rust that shows on the steel: colour difference against clean (dE76); the rails'
                                # paint is darker than rust in places, so darkening alone misses it
SEEDS_TOL = {"tone": 0.04, "T3+": 0.07, "T4+": 0.08, "film_k": 0.02}
A6_MAX = 2.2                    # presets: the largest tone step over the smallest


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _hue(d):
    return np.degrees(np.arctan2(d[..., 2], d[..., 1])) % 360.0


def family_pixels(p):
    """Mark pixels of a plane (streaks, stains, ground band at T2+ on paint) and their Lab shift."""
    if "labw" not in p or "labc" not in p or "cls" not in p:
        return None
    m = np.isin(p["cls"], PAINTED) & np.isfinite(p["D"])
    mk = np.zeros_like(m)
    for k in FAM_LAYERS:
        if k in p:
            mk |= np.nan_to_num(np.asarray(p[k], np.float32)) >= I4["mark_D"]
    for ex in ("L_bio", "L_rust"):                 # growth and rust have their own colour rules
        if ex in p:
            mk &= ~(np.nan_to_num(np.asarray(p[ex], np.float32)) >= wm.TIER_EDGES[0])
    sel = m & mk
    if sel.sum() < 200:
        return None
    d = (p["labw"][sel] - p["labc"][sel]).astype(np.float64)
    return sel, d


def classify(d):
    h, c = _hue(d), np.hypot(d[:, 1], d[:, 2])
    g = (d[:, 1] <= I4["green"][2]) & (h >= I4["green"][0]) & (h <= I4["green"][1])
    y = (d[:, 2] >= I4["yellow"][2]) & (h >= I4["yellow"][0]) & (h < I4["yellow"][1])
    o = (c >= I4["olive"][2]) & (h >= I4["olive"][0]) & (h <= I4["olive"][1]) & ~g & ~y
    return g, y, o


def rule_I4(cfg, planes, R):
    """I4: dark green and yellow marks coexist, not blended: of the mark pixels (streaks, stains and
    the ground band at T2+ on paint), the green family (hue 100-180 deg, a* -1 or less) and the
    yellow family (hue 70-100 deg, b* +3 or more) each hold their share; each wall with marks has
    both; few pixels sit between them (olive, hue 105-130 deg), as a smooth blend would put there."""
    E = float(cfg.get("E", 0.0) or 0.0)
    if E < I4["E_min"]:
        return res("I4", True, {"E": E}, "under E %g" % I4["E_min"])
    n = ng = ny = no = 0
    per, ok_planes = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        fp = family_pixels(p)
        if fp is None:
            continue
        g, y, o = classify(fp[1])
        k = len(g)
        n, ng, ny, no = n + k, ng + int(g.sum()), ny + int(y.sum()), no + int(o.sum())
        st = {"px": k, "green": round(g.mean(), 3), "yellow": round(y.mean(), 3), "olive": round(o.mean(), 3)}
        if k >= 5000:
            st["both"] = bool(g.mean() >= I4["plane_min"] and y.mean() >= I4["plane_min"])
            ok_planes &= st["both"]
        per[p["name"]] = st
    if n < 1000:
        return res("I4", True, {"px": n}, "few marks")
    sg, sy, so = ng / n, ny / n, no / n
    lo_g, lo_y, hi = I4["share"]
    ok = (lo_g <= sg <= hi and lo_y <= sy <= hi and ok_planes and so <= I4["olive_max"] * min(sg, sy))
    return res("I4", ok, {"green": round(sg, 3), "yellow": round(sy, 3), "olive": round(so, 4),
                          "olive_limit": round(I4["olive_max"] * min(sg, sy), 4), "planes": per})


def green_stats(planes):
    """Mean lightness change and colour difference of the green-family mark pixels (I5)."""
    dl, de, n = 0.0, 0.0, 0
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        fp = family_pixels(p)
        if fp is None:
            continue
        g, _, _ = classify(fp[1])
        if g.sum():
            d = fp[1][g]
            dl += float(d[:, 0].sum())
            de += float(np.sqrt((d ** 2).sum(axis=1)).sum())
            n += int(g.sum())
    return (dl / n, de / n, n) if n >= 300 else None


def series_green_age(runs):
    """I5: the green marks darken and intensify with age: from each preset at E 8 or more to the
    next older one, their mean L* change falls by 1.0 or more and their colour difference grows."""
    st, bad = [], []
    for cfg, planes in runs:
        if float(cfg.get("E", 0) or 0) < I4["E_min"]:
            continue
        g = green_stats(planes)
        if g is None:
            continue
        st.append({"preset": cfg.get("preset"), "dL": round(g[0], 2), "dE": round(g[1], 2), "px": g[2]})
    for i in range(len(st) - 1):
        a, b = st[i], st[i + 1]
        if not (b["dL"] <= a["dL"] - 1.0 and b["dE"] > a["dE"]):
            bad.append("%s -> %s" % (a["preset"], b["preset"]))
    if len(st) < 2:
        return res("I5", True, {"steps": st}, "under two presets at E 8 or more")
    return res("I5", not bad, {"steps": st, "bad": bad})


def _meta(cfg):
    return json.load(open(os.path.join(cfg["_dir"], "meta.json"), encoding="utf-8"))


def series_seeds(runs, local_vals, exposed_vals):
    """A5: seeds of one preset read as the same age: tone, T3+ and T4+ within their tolerance of
    the seeds' mean, and the same film contrast."""
    rows = []
    for cfg, planes in runs:
        v = local_vals(planes)
        t = exposed_vals(planes)
        rows.append({"seed": cfg.get("seed"), "preset": cfg.get("preset"), "tone": float(np.clip(t, -1, 1).mean()),
                     "T3+": float((v >= wm.TIER_EDGES[2]).mean()), "T4+": float((v >= wm.TIER_EDGES[3]).mean()),
                     "film_k": float(_meta(cfg)["gains"]["film_k"])})
    if len({r["preset"] for r in rows}) != 1:
        return res("A5", False, rows, "seeds of different presets")
    bad = []
    for k, tol in SEEDS_TOL.items():
        mu = np.mean([r[k] for r in rows])
        dev = max(abs(r[k] / mu - 1.0) for r in rows) if mu > 1e-6 else 0.0
        if dev > tol:
            bad.append("%s off by %.1f %% (limit %.0f %%)" % (k, 100 * dev, 100 * tol))
    return res("A5", not bad, {"seeds": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                                         for r in rows], "bad": bad})


def series_steps(tones, order):
    """A6: the presets step evenly: tone steps from New up, the largest over the smallest <= A6_MAX
    (round G's ladder, which the user called even, measured 1.9)."""
    seq = [k for k in order if k in tones]
    steps = [tones[b] - tones[a] for a, b in zip(seq, seq[1:])]
    if len(steps) < 2:
        return res("A6", True, {"steps": steps}, "under three presets")
    ratio = max(steps) / max(min(steps), 1e-6)
    return res("A6", min(steps) > 0 and ratio <= A6_MAX, {"presets": seq, "tone": [round(tones[k], 4) for k in seq],
                                                          "steps": [round(s, 4) for s in steps], "ratio": round(ratio, 2),
                                                          "limit": A6_MAX})


def series_growth_age(runs):
    """M9: growth darkens and intensifies with age: between growth steps, the pixels that were
    growth (T2+) at the earlier step lose 1.0 L* or more and gain 0.02 or more of growth darkening."""
    st, bad = [], []
    prev = None
    for cfg, planes in runs:
        cur = {n: (np.nan_to_num(np.asarray(p["L_bio"], np.float64)), np.asarray(p["labw"][..., 0], np.float64))
               for n, p in planes.items() if p.get("exposed", True) and "L_bio" in p and "labw" in p}
        if prev is not None:
            n = 0
            dl = dd = 0.0
            for k in cur:
                if k not in prev:
                    continue
                g0 = prev[k][0] >= wm.TIER_EDGES[1]
                if not g0.any():
                    continue
                n += int(g0.sum())
                dl += float((cur[k][1][g0] - prev[k][1][g0]).sum())
                dd += float((cur[k][0][g0] - prev[k][0][g0]).sum())
            if n >= 400:
                s = {"old_px": n, "dL": round(dl / n, 2), "dD": round(dd / n, 4)}
                if not (s["dL"] <= -1.0 and s["dD"] >= 0.02):
                    bad.append(len(st))
                st.append(s)
        prev = cur
    if not st:
        return res("M9", True, {"steps": st}, "no step with earlier growth")
    return res("M9", not bad, {"steps": st, "bad_steps": bad})


def rust_grade(a):
    xs, ys = RUST_GRADE
    if a <= 0:
        return 0.0
    if a < xs[0]:
        return ys[0] * (a / xs[0]) ** 2
    if a > xs[-1]:
        return min(0.75, ys[-1] * a / xs[-1])
    return float(np.exp(np.interp(a, xs, np.log(ys))))


def steel_rust(planes):
    """(rusted share of the steel, mean colour difference on the steel, rust area on paint in m2).
    Rust shows where the steel's colour moved dE >= RUST_VISIBLE from clean and the rust layer
    touched it; only rust changes the steel."""
    ns = nr = 0
    dsum = 0.0
    paint_m2 = 0.0
    for p in planes.values():
        if "steel" not in p or "L_rust" not in p or "labw" not in p or "labc" not in p:
            continue
        s = np.asarray(p["steel"]).astype(bool)
        if "cls" in p:                            # round I: the railing steel R1 names (rails, posts); flat
            import gate_r as _gr                  # panels (doors) are judged by R3's panel clause
            s = s & ~_gr._geo(p)[1]["panel"]
        L = np.nan_to_num(np.asarray(p["L_rust"], np.float64))
        dE = np.sqrt(((p["labw"][s].astype(np.float64) - p["labc"][s].astype(np.float64)) ** 2).sum(axis=1))
        ns += int(s.sum())
        nr += int(((dE >= RUST_VISIBLE) & (np.abs(L[s]) > 1e-4)).sum())
        dsum += float(dE.sum())
        if "cls" in p:
            paint = np.isin(p["cls"], PAINTED)
            paint_m2 += float((paint & (L >= wm.TIER_EDGES[1])).sum()) / p["ppm"] ** 2
    if ns < 500:
        return None
    return nr / ns, dsum / ns, paint_m2


def rule_R1(cfg, planes, R):
    """R1: rust on steel by grade: the share of the steel where rust shows (colour difference 8 or
    more against clean) within 0.5-2x the ISO 4628-3 grade for the rust amount (Ri3-4 at 0.25 ... Ri5 at 1.0)."""
    a = float((cfg.get("amounts") or {}).get("rust", 0.0))
    st = steel_rust(planes)
    if st is None:
        return res("R1", True, None, "no steel")
    want = rust_grade(a)
    if a < 0.1:
        return res("R1", st[0] <= max(0.02, 2.0 * want), {"amount": round(a, 3), "share": round(st[0], 4)},
                   "light rust: only an upper limit")
    lo, hi = RUST_BAND[0] * want, RUST_BAND[1] * want
    return res("R1", lo <= st[0] <= hi, {"amount": round(a, 3), "share": round(st[0], 4), "band": [round(lo, 4), round(hi, 4)],
                                          "steel_mean_dE": round(st[1], 2), "paint_m2": round(st[2], 3)})


def series_rust(runs):
    """R2: each rust step shows: between steps, the rusted share of the steel x 1.5 or more (or +10
    points), the steel's mean colour difference x 1.5 or more (or +2), and the rust on the paint
    below grows."""
    st, bad = [], []
    for cfg, planes in runs:
        s = steel_rust(planes)
        st.append(None if s is None else {"amount": (cfg.get("override") or {}).get("rust"), "share": round(s[0], 4),
                                          "steel_mean_dE": round(s[1], 2), "paint_m2": round(s[2], 3)})
    for i in range(len(st) - 1):
        a, b = st[i], st[i + 1]
        if a is None or b is None:
            bad.append(i)
            continue
        if a["share"] <= 0.001:
            if b["share"] <= 0.005:
                bad.append(i)
            continue
        if not ((b["share"] >= 1.5 * a["share"] or b["share"] >= a["share"] + 0.10)
                and (b["steel_mean_dE"] >= 1.5 * a["steel_mean_dE"] or b["steel_mean_dE"] >= a["steel_mean_dE"] + 2.0)
                and b["paint_m2"] > a["paint_m2"]):
            bad.append(i)
    return res("R2", not bad, {"steps": st, "bad_steps": bad})


RULES = [rule_I4, rule_R1]
