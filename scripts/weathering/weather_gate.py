"""weather_gate.py - accept or reject a weathered building against weather_rules.json.

A configuration is a folder of planes, one .npz per plane, in facade space (row 0 at the top):
  D            float32 HxW   composite darkening, 1 - Y_weathered / Y_clean (NaN = not measured)
  L_<layer>    float32 HxW   optional: the darkening one layer adds on its own (same convention)
  Yc           float32 HxW   optional: clean albedo luminance (linear)
  labw, labc   float32 HxWx3 optional: CIELAB of the weathered and clean albedo
  cls          uint8 HxW     optional: surface class (see CLASSES)
  src          bool  HxW     optional: source pixels for streaks (ledge drip lines, sill ends, ...)
  edge         bool  HxW     optional: exposed arrises (for the damage rules)
and a meta.json: {"config": {...preset, age, upkeep, E, controls...},
                  "planes": {name: {"ppm":50, "orient":"S", "kind":"front|wall|gable|plinth|soffit",
                                    "exposed":true, "ground_row":..., "top_row":...,
                                    "floor_rows":[...], "bay_cols":[...]}}}

  python -I weather_gate.py check <config_dir> [--rules weather_rules.json] [--json out.json]
  python -I weather_gate.py series <kind> <dir1> <dir2> ...   (kind: presets | sweep:<layer>)

Exit code 0 only when every binding rule that applies passes. Rules whose inputs are missing
report "na"; for acceptance they count as failures unless --allow-na is given.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_measure as wm  # noqa: E402
import gate_g as gg  # noqa: E402
import gate_m as gm  # noqa: E402
import gate_c as gc  # noqa: E402
import gate_p as gp  # noqa: E402
import gate_k as gk  # noqa: E402
import gate_n as gn  # noqa: E402
import gate_h as gh  # noqa: E402

CLASSES = {0: "none", 1: "paint", 2: "coping", 3: "soffit", 4: "concrete", 5: "plinth", 6: "glass",
           7: "metal", 8: "prop", 9: "decal"}
PAINTED = (1, 2)
DARK_SUBSTRATE = (4, 5)
AREAL = ("soiling", "stains", "base", "bio")
FLOW = ("streaks", "stains")
LIGHTENING = ("efflorescence", "washed", "fading", "repaint", "wear")


def load_config(d):
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    if "amounts" in meta:
        meta["config"]["amounts"] = meta["amounts"]
    planes = {}
    for name, pm in meta["planes"].items():
        z = np.load(os.path.join(d, name + ".npz"))
        p = {k: z[k] for k in z.files}
        p.update(pm)
        p["name"] = name
        planes[name] = p
    meta["config"]["_dir"] = d
    return meta["config"], planes


def interp_band(table, tier, E):
    Es = table["E"]
    lo = np.interp(E, Es, [b[0] for b in table[tier]])
    hi = np.interp(E, Es, [b[1] for b in table[tier]])
    return float(lo), float(hi)


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def exposed_vals(planes, key="D"):
    vals = []
    for p in planes.values():
        if not p.get("exposed", True) or key not in p:
            continue
        D = p[key]
        m = np.isfinite(D)
        if "cls" in p:
            m &= np.isin(p["cls"], PAINTED)
        vals.append(D[m])
    return np.concatenate(vals) if vals else np.array([])


def painted(p, key="D"):
    c = p.setdefault("_painted", {})
    if key not in c:
        D = p[key].astype(np.float64).copy()
        if "cls" in p:
            D[~np.isin(p["cls"], PAINTED)] = np.nan
        c[key] = D
    return c[key]


def bstats(p, key="D"):
    c = p.setdefault("_bands", {})
    if key not in c:
        c[key] = wm.band_stats(painted(p, key), p["ppm"])
    return c[key]


def pmarks(p, key, thr):
    c = p.setdefault("_marks", {})
    k = (key, thr)
    if k not in c:
        c[k] = wm.marks(painted(p, key), p["ppm"], thr=thr)
    return c[k]


# --- A amount --------------------------------------------------------------------------------

def local_img(p):
    """D_local image of a plane (4 cm blocks) and its ppm; NaN off the painted wall."""
    c = p.setdefault("_local", {})
    if "img" not in c:
        wall = np.isfinite(p["D"])
        if "cls" in p:
            wall &= np.isin(p["cls"], PAINTED)
        if "edge" in p:                    # arris rows are measured by the edge rules (N), not as wall
            wall &= ~np.asarray(p["edge"]).astype(bool)
        if "L_wear" in p:                  # and the edge layer's chips
            wall &= ~(np.abs(np.nan_to_num(p["L_wear"].astype(np.float32))) > 1e-4)
        # the weathering's own local contrast: base paint tones (element to element) do not count
        Y = 1.0 - np.nan_to_num(p["D"].astype(np.float64))
        c["img"], c["ppm"] = wm.local_contrast_D(Y, wall, p["ppm"])
    return c["img"], c["ppm"]


def local_vals(planes):
    """D_local values (4 cm blocks) over all exposed painted planes."""
    vals = []
    for p in planes.values():
        if p.get("exposed", True):
            img, _ = local_img(p)
            vals.append(img[np.isfinite(img)])
    return np.concatenate(vals) if vals else np.array([])


def local_meta(p):
    """The plane's floor rows and bay columns rescaled to the D_local grid."""
    img, lp = local_img(p)
    f = p["ppm"] / lp
    q = dict(p)
    q["floor_rows"] = [int(r / f) for r in p.get("floor_rows", [])]
    q["bay_cols"] = [int(c / f) for c in p.get("bay_cols", [])]
    return q


def rule_A0(cfg, planes, R):
    v = exposed_vals(planes)
    if v.size == 0:
        return res("A0", None, None, "no exposed painted pixels")
    m = float(np.clip(v, -1, 1).mean())
    t = R["tone"]
    lo = float(np.interp(cfg["E"], t["E"], [b[0] for b in t["mean_D"]]))
    hi = float(np.interp(cfg["E"], t["E"], [b[1] for b in t["mean_D"]]))
    return res("A0", lo - 0.002 <= m <= hi, [round(m, 4), [round(lo, 4), round(hi, 4)]])


def rule_A1(cfg, planes, R):
    v = local_vals(planes)
    if v.size == 0:
        return res("A1", None, None, "no exposed painted pixels")
    out, ok = {}, True
    for i, t in enumerate(["T2+", "T3+", "T4+", "T5+", "T6+"]):
        cov = float((v >= wm.TIER_EDGES[i + 1]).mean())
        lo, hi = interp_band(R["coverage"], t, cfg["E"])
        good = lo <= cov <= hi
        ok &= good
        out[t] = [round(cov, 4), [round(lo, 4), round(hi, 4)], "ok" if good else ("low" if cov < lo else "high")]
    return res("A1", ok, out)


def rule_A2(cfg, planes, R):
    if cfg["E"] < 10:
        return res("A2", True, "E < 10: not applied")
    f10, fmin = (0.40, 0.25) if cfg["E"] >= 25 else (0.30, 0.15)
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        img, lp = local_img(p)
        g = wm.cells(np.clip(img, 0, None), lp, 4.0)
        c = wm.concentration(g)
        if c["top_share"] is None:
            continue
        good = c["floor"] >= f10 and c["min_over_mean"] >= fmin
        ok &= good
        out[p["name"]] = [round(c["floor"], 3), round(c["min_over_mean"], 3), "ok" if good else "clean zones"]
    return res("A2", ok, out, "P10/mean >= %.2f, min/mean >= %.2f" % (f10, fmin))


def rule_A3(cfg, planes, R):
    if cfg["E"] < 10:
        return res("A3", True, "E < 10: not applied")
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        D, ppm = local_img(p)
        b = int(ppm * 1.0)
        mean = np.nanmean(np.clip(D, 0, None))
        if not np.isfinite(mean) or mean <= 0:
            continue
        cols = np.where(np.isfinite(D).any(axis=0))[0]
        rows = np.where(np.isfinite(D).any(axis=1))[0]
        if cols.size < 3 * b or rows.size < 3 * b:
            continue
        f = p["ppm"] / ppm
        r0 = int(p["top_row"] / f) if p.get("top_row") is not None else rows[0]
        r0 = max(r0, rows[0])                      # the wall top, not a penthouse above it
        bands = {"left": D[:, cols[0]:cols[0] + b], "right": D[:, cols[-1] - b + 1:cols[-1] + 1],
                 "top": D[r0:r0 + b, :]}
        r = {k: float(np.nanmean(np.clip(v, 0, None)) / mean) for k, v in bands.items() if np.isfinite(v).any()}
        good = all(x >= 0.6 for x in r.values())
        ok &= good
        out[p["name"]] = {k: round(x, 2) for k, x in r.items()}
    return res("A3", ok, out, ">= 0.6 of the plane mean")


# --- B opacity -------------------------------------------------------------------------------

def rule_B1(cfg, planes, R):
    if cfg["E"] < 10:
        return res("B1", True, "E < 10: not applied")
    v = local_vals(planes)
    e = wm.TIER_EDGES + [np.inf]
    sh = [float(((v >= e[i]) & (v < e[i + 1])).mean()) for i in range(1, 6)]     # T2..T6
    stained = sum(sh)
    n_used = sum(1 for x in sh if x >= 0.01)
    biggest = max(sh) / max(stained, 1e-9)
    cap = 0.70 if cfg["E"] < 12 else 0.60          # light walls: the faint tier may hold more (photos up to 0.76)
    ok = n_used >= 4 and biggest <= cap
    falling = None
    if cfg["E"] <= 20:
        falling = all(sh[i + 1] <= 0.9 * sh[i] + 1e-4 for i in range(1, 4))
        ok = ok and falling
    return res("B1", ok, {"shares_T2..T6": [round(x, 4) for x in sh], "tiers_used": n_used,
                          "largest_tier_share": round(biggest, 3), "falling_from_T3": falling})


def _marks_all(planes, key, thr):
    mk = []
    for p in planes.values():
        if key not in p or not p.get("exposed", True):
            continue
        for m in pmarks(p, key, thr):
            m = dict(m)
            m["plane"] = p["name"]
            mk.append(m)
    return mk


def rule_B2(cfg, planes, R):
    mk = []
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        img, lp = local_img(p)
        mk += [m for m in wm.marks(img, lp, thr=wm.TIER_EDGES[2]) if m["eqd_m"] >= 0.5]
    if not mk:
        return res("B2", True, {"n": 0})
    cv = np.median([m["cv"] for m in mk])
    span3 = np.mean([m["tiers_spanned"] >= 3 for m in mk])
    big = np.array([m["cv"] for m in mk if m["eqd_m"] >= 2.0])
    heavy = cfg["E"] >= 25
    b_med, b_p10, b_min = (0.33, 0.25, 0.20) if heavy else (0.40, 0.33, 0.25)
    big_ok = True
    if big.size:
        big_ok = (np.median(big) >= b_med and np.percentile(big, 10) >= b_p10 and big.min() >= b_min)
    ok = cv >= 0.30 and span3 >= 0.60 and big_ok
    return res("B2", ok, {"n": len(mk), "cv_median": round(float(cv), 3), "span3_share": round(float(span3), 3),
                          "big_n": int(big.size),
                          "big_cv_median": round(float(np.median(big)), 3) if big.size else None,
                          "big_cv_p10": round(float(np.percentile(big, 10)), 3) if big.size else None,
                          "big_min_cv": round(float(big.min()), 3) if big.size else None})


def rule_B3(cfg, planes, R):
    out, ok = {}, True
    for key in ("D", "L_soiling"):
        vals = []
        for p in planes.values():
            if key in p and p.get("exposed", True):
                vals.append(wm.flat_fraction(painted(p, key), p["ppm"]))
        if vals:
            f = float(np.max(vals))
            good = f <= 0.05
            ok &= good
            out[key] = [round(f, 3), "ok" if good else "flat tint"]
    if not out:
        return res("B3", None, None)
    return res("B3", ok, out, "worst plane")


# --- C scale ---------------------------------------------------------------------------------

def rule_C1(cfg, planes, R):
    if cfg["E"] < 10:
        return res("C1", True, "E < 10: not applied")
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        bs = bstats(p)
        lv = {k: v["std"] for k, v in bs.items() if k in ("S2", "S3", "S4", "S5", "S6", "S7", "S8")}
        if not lv:
            continue
        low = [k for k, s in lv.items() if s < 0.004]
        mid = [lv[k] for k in ("S3", "S4", "S5", "S6", "S7", "S8") if k in lv]
        ratio = max(mid) / max(min(mid), 1e-9) if mid else None
        good = not low and (ratio is None or ratio <= 3.0)
        ok &= good
        out[p["name"]] = {"std": {k: round(s, 4) for k, s in lv.items()}, "max/min": round(ratio, 2) if ratio else None,
                          "weak": low}
    return res("C1", ok, out)


def rule_C2(cfg, planes, R):
    out, ok, any_layer = {}, True, False
    for layer in AREAL:
        key = "L_" + layer
        lv = {}
        for p in planes.values():
            if key in p and p.get("exposed", True):
                for k, v in bstats(p, key).items():
                    lv[k] = max(lv.get(k, 0.0), v["std"])
        if not lv or max(lv.values()) < 1e-4:
            continue
        any_layer = True
        top = max(lv.values())
        present = [k for k, s in lv.items() if s >= 0.15 * top]
        groups = {g: any(("S%d" % (i + 1)) in present for i in idx) for g, idx in wm.GROUP.items()}
        good = all(groups.values()) and len(present) >= 5
        ok &= good
        out[layer] = {"present": present, "groups": groups}
    if not any_layer:
        return res("C2", None, None, "no layer maps")
    return res("C2", ok, out)


def rule_C3(cfg, planes, R):
    out, ok, any_layer = {}, True, False
    for layer in ("streaks", "stains", "bio", "damage"):
        key = "L_" + layer
        mk = _marks_all(planes, key, wm.TIER_EDGES[1])
        if not mk:
            continue
        any_layer = True
        c = wm.level_counts(mk)
        nz = [i for i in range(8) if c[i] > 0]
        bad = []
        if nz:
            for i in range(nz[0], 6):          # up to S7
                if c[i] >= 10 and c[i + 1] < 1.5 * c[i]:
                    bad.append("S%d->S%d" % (i + 1, i + 2))
        good = not bad
        ok &= good
        out[layer] = {"counts": c, "bad": bad}
    if not any_layer:
        return res("C3", None, None, "no layer maps")
    return res("C3", ok, out)


# --- D clustering ----------------------------------------------------------------------------

def rule_D1(cfg, planes, R):
    if cfg["E"] <= 0:
        return res("D1", True, "no weathering")
    out, ok = {}, True
    for key, lo, hi in (("local", 0.28, 0.60), ("L_streaks", 0.40, 0.85), ("L_stains", 0.40, 0.85)):
        for p in planes.values():
            if not p.get("exposed", True) or (key != "local" and key not in p):
                continue
            if key != "local":
                v = painted(p, key)
                v = v[np.isfinite(v)]
                if v.size == 0 or (v >= wm.TIER_EDGES[1]).mean() < 0.03:
                    continue
                img, lp = painted(p, key), p["ppm"]
            else:
                img, lp = local_img(p)
                img = np.clip(img, 0, None)
            for cm in (4.0, 2.0):
                c = wm.concentration(wm.cells(img, lp, cm))
                if c["top_share"] is None or c["n"] < 10:
                    continue
                good = lo <= c["top_share"] <= hi
                ok &= good
                out["%s/%s/%gm" % (key, p["name"], cm)] = [round(c["top_share"], 3), "ok" if good else "out of [%.2f, %.2f]" % (lo, hi)]
    return res("D1", ok, out)


# --- E coherence -----------------------------------------------------------------------------

def storey_rows(p):
    """Floor rows bounding storeys: drops a top band shorter than 0.6 x the median storey (the
    roof parapet or coping above the top slab) and the ground storey (splash zone, rule F3)."""
    fr = sorted(p.get("floor_rows") or [])
    if len(fr) < 3:
        return fr
    h = np.diff(fr)
    med = float(np.median(h))
    if h[0] < 0.6 * med:
        fr = fr[1:]
    return fr[:-1] if len(fr) > 3 else fr


def floor_bay_cells(D, p, storeys_only=False):
    fr, bc = (storey_rows(p) if storeys_only else p.get("floor_rows")), p.get("bay_cols")
    if not fr or not bc or len(fr) < 3 or len(bc) < 3:
        return None
    g = np.full((len(fr) - 1, len(bc) - 1), np.nan)
    for i in range(len(fr) - 1):
        for j in range(len(bc) - 1):
            blk = D[fr[i]:fr[i + 1], bc[j]:bc[j + 1]]
            m = np.isfinite(blk)
            if m.mean() > 0.2:
                g[i, j] = float(np.clip(blk[m], 0, None).mean())
    return g


def rule_E1(cfg, planes, R):
    if cfg["E"] <= 0:
        return res("E1", True, "no weathering")
    out, ok, any_p = {}, True, False
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        img, lp = local_img(p)
        g = floor_bay_cells(img, local_meta(p), storeys_only=True)
        if g is None:
            continue
        any_p = True
        c = wm.coherence(g)
        kinds = p.get("bay_kinds")
        if kinds and len(kinds) == g.shape[1]:      # bay to bay: compare bays of the same kind only
            pa, pb = [], []
            for j in range(g.shape[1] - 1):
                if kinds[j] == kinds[j + 1]:
                    pa.append(g[:, j])
                    pb.append(g[:, j + 1])
            if pa:
                A, B = np.concatenate(pa), np.concatenate(pb)
                ok_ = np.isfinite(A) & np.isfinite(B)
                if ok_.sum() >= 6 and np.std(A[ok_]) > 1e-9 and np.std(B[ok_]) > 1e-9:
                    c["rho_h"] = float(np.corrcoef(A[ok_], B[ok_])[0, 1])
        need_h = p.get("kind") == "front"          # bay to bay: units side by side; a gable is one wall
        good = (c["rho_v"] is None or c["rho_v"] >= 0.30) and \
            (not need_h or c["rho_h"] is None or c["rho_h"] >= 0.20) and \
            (c["jump_p90_over_spread"] is None or c["jump_p90_over_spread"] <= 0.80)
        ok &= good
        out[p["name"]] = {k: (round(v, 3) if v is not None else None) for k, v in c.items()}
    if not any_p:
        return res("E1", None, None, "no floor/bay grid")
    return res("E1", ok, out, "floor to floor rho >= 0.30, bay to bay >= 0.20, jump <= 0.80")


# --- F gradients -----------------------------------------------------------------------------

def _flow(p):
    keys = [k for k in ("L_streaks", "L_stains") if k in p]
    if not keys:
        return None
    s = np.zeros(p["D"].shape)
    for k in keys:
        s = s + np.nan_to_num(np.clip(p[k], 0, None))
    s[~np.isfinite(p["D"])] = np.nan
    return s


def rule_F1(cfg, planes, R):
    if cfg["E"] < 5:
        return res("F1", True, "E < 5: not applied")
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True) or p.get("kind") not in ("wall", "gable", "front"):
            continue
        g, t = p.get("ground_row"), p.get("top_row")
        hp = wm.height_profile(painted(p), p["ppm"], g, t)
        f = _flow(p)
        hf = wm.height_profile(f, p["ppm"], g, t) if f is not None else None
        r_c = hp["top20"] / max(hp["mid30_70"], 1e-6) if hp and hp["mid30_70"] else None
        r_f = hf["top20"] / max(hf["mid30_70"], 1e-6) if hf and hf["mid30_70"] else None
        good = (r_c is None or r_c >= 1.10) and (r_f is None or r_f >= 1.30)
        ok &= good
        out[p["name"]] = {"composite": round(r_c, 2) if r_c else None, "flow": round(r_f, 2) if r_f else None}
    return res("F1", ok, out)


def rule_F2(cfg, planes, R):
    mk = []
    for layer in FLOW:
        mk += [m for m in _marks_all(planes, "L_" + layer, wm.TIER_EDGES[1]) if m["h_m"] > 0.5]
    if not mk:
        return res("F2", None, None, "no flow layers")
    r = float(np.median([m["top_mean"] / max(m["bottom_mean"], 1e-6) for m in mk]))
    return res("F2", r >= 1.25, {"n": len(mk), "top_over_bottom_median": round(r, 2)})


def rule_F3(cfg, planes, R):
    if cfg["E"] < 8:
        return res("F3", True, "E < 8: not applied")
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True) or p.get("kind") not in ("wall", "gable", "front"):
            continue
        Dd = p["D"].astype(np.float64)
        for k in ("L_damage", "L_cracks", "L_crack_repair", "L_wear"):   # the dirt gradient, not structure
            if k in p:
                Dd = Dd - np.nan_to_num(p[k].astype(np.float64))
        hp = wm.height_profile(Dd, p["ppm"], p.get("ground_row"), p.get("top_row"))
        if not hp or hp["base1m"] is None:
            continue
        r = hp["base1m"] / max(hp["mean"], 1e-6)
        good = r >= (1.30 if cfg["E"] >= 13 else 1.15)
        ok &= good
        out[p["name"]] = round(r, 2)
    return res("F3", ok, out)


def rule_F4(cfg, planes, R):
    cov = {}
    for p in planes.values():
        if "L_bio" in p:
            v = painted(p, "L_bio")
            v = v[np.isfinite(v)]
            if v.size:
                cov.setdefault(p.get("orient"), []).append(float((v >= wm.TIER_EDGES[1]).mean()))
    if not cov or "N" not in cov or "S" not in cov:
        return res("F4", None, None, "need N and S bio maps")
    n, s = np.mean(cov["N"]), np.mean(cov["S"])
    if n < 0.002:
        return res("F4", True, {"N": n, "S": s}, "no bio")
    return res("F4", n >= 1.5 * max(s, 1e-6), {"N": round(n, 4), "S": round(s, 4)})


# --- G placement -----------------------------------------------------------------------------

def rule_G1(cfg, planes, R):
    tot = hit = 0
    for p in planes.values():
        if "L_streaks" not in p or "src" not in p:
            continue
        src = p["src"].astype(bool)
        ppm = p["ppm"]
        reach = max(1, int(0.15 * ppm))
        # a source "covers" the rows from its own row down to reach below
        cover = src.copy()
        for k in range(1, reach + 1):
            cover[k:, :] |= src[:-k, :]
        # widen by 3 cm sideways
        w = max(1, int(0.03 * ppm))
        cw = cover.copy()
        for k in range(1, w + 1):
            cw[:, k:] |= cover[:, :-k]
            cw[:, :-k] |= cover[:, k:]
        Ls = painted(p, "L_streaks")
        trail, _n = wm.label(np.isfinite(Ls) & (Ls >= wm.TIER_EDGES[0]))
        # top row of each trail, and whether that top touches a source
        lab = trail.ravel()
        sel = lab > 0
        rows = np.flatnonzero(sel) // trail.shape[1]
        top = np.full(_n + 1, trail.shape[0], np.int64)
        np.minimum.at(top, lab[sel], rows)
        ys, xs = np.nonzero(trail)
        at_top = ys <= top[trail[ys, xs]] + 1
        ok_trail = np.zeros(_n + 1, bool)
        ok_trail[np.unique(trail[ys[at_top], xs[at_top]][cw[ys[at_top], xs[at_top]]])] = True
        for m in pmarks(p, "L_streaks", wm.TIER_EDGES[1]):
            if m["aspect"] < 2.0 or m["h_m"] < 0.15:
                continue
            tot += 1
            y = m["y_top_px"]
            x0, x1 = m["x_top"]
            t = trail[y, x0:x1 + 1]
            t = t[t > 0]
            if t.size and ok_trail[t].any():
                hit += 1
    if tot == 0:
        return res("G1", None, None, "no streak layer or sources")
    return res("G1", hit / tot >= 0.95, {"n": tot, "share_at_source": round(hit / tot, 3)})


def rule_G2(cfg, planes, R):
    out, ok, any_p = {}, True, False
    for p in planes.values():
        if "cls" not in p:
            continue
        m = np.isin(p["cls"], DARK_SUBSTRATE) & np.isfinite(p["D"])
        if "Yc" in p:
            m |= (p["Yc"] < 0.30) & np.isfinite(p["D"]) & ~np.isin(p["cls"], (0, 6, 7, 8))
        if m.sum() < 50:
            continue
        any_p = True
        D = np.where(m, p["D"], np.nan)
        light = float((D[m] < -wm.TIER_EDGES[1]).mean())
        mk = wm.marks(-D, p["ppm"], thr=wm.TIER_EDGES[1])
        tall = [x for x in mk if x["h_m"] > 0.3]
        good = light <= 0.02 and not tall
        ok &= good
        out[p["name"]] = {"lighter_share": round(light, 4), "light_marks_over_0.3m": len(tall)}
    if not any_p:
        return res("G2", True, None, "no dark substrate on this building")
    return res("G2", ok, out)


def rule_G4(cfg, planes, R):
    """Algae sits where water stays: the foot, below water sources, joints."""
    tot = wet = 0.0
    out = {}
    for p in planes.values():
        if not p.get("exposed", True) or "L_bio" not in p:
            continue
        b = np.where(np.isin(p["cls"], PAINTED), np.nan_to_num(p["L_bio"].astype(np.float64)), 0.0)
        if (b >= wm.TIER_EDGES[1]).mean() < 0.002:
            continue
        ppm, H = p["ppm"], b.shape[0]
        src = p["src"].astype(bool) if "src" in p else np.zeros(b.shape, bool)
        for k in ("L_stains", "L_streaks"):
            if k in p:
                src |= np.nan_to_num(p[k].astype(np.float64)) >= 0.05
        if "joint" in p:
            src |= p["joint"] > 0
        zone = src.copy()
        k = int(0.8 * ppm)
        step = max(1, k // 16)
        for i in range(step, k + 1, step):              # 0.8 m below any source
            zone[i:] |= src[:-i]
        g = p.get("ground_row")
        if g is not None:
            zone[max(0, int(g - 1.5 * ppm)):] = True
        if "joint" in p:
            j = (p["joint"] > 0).astype(np.float64)
            zone |= wm.gauss(j, 0.05 * ppm) > 0.02
        t, w = float(b.sum()), float(b[zone].sum())
        tot += t
        wet += w
        out[p["name"]] = round(w / max(t, 1e-9), 3)
    if tot <= 0:
        return res("G4", True, out, "no algae to place")
    share = wet / tot
    out["all"] = round(share, 3)
    return res("G4", share >= 0.60, out)


def rule_G3(cfg, planes, R):
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        D = painted(p)
        v = D[np.isfinite(D)]
        if v.size == 0:
            continue
        light = float((v <= -wm.TIER_EDGES[0]).mean())
        dark = float((v >= wm.TIER_EDGES[0]).mean())
        good = light <= 0.25 * dark + 1e-4
        ok &= good
        out[p["name"]] = [round(light, 4), round(dark, 4), "ok" if good else "too much lightening"]
    return res("G3", ok, out, "[lighter share, darker share]")


# --- H separability --------------------------------------------------------------------------

def rule_H1(cfg, planes, R):
    if cfg["E"] < 5:
        return res("H1", True, "E < 5: not applied")
    out, ok = {}, True
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        bs = bstats(p)
        a = [bs[k]["aniso"] for k in ("S5", "S6", "S7", "S8") if k in bs]
        if not a:
            continue
        med = float(np.median(a))
        good = 0.40 <= med <= 1.80
        ok &= good
        out[p["name"]] = [round(med, 2), "ok" if good else ("striped" if med > 1.8 else "banded")]
    return res("H1", ok, out)


def rule_H2(cfg, planes, R):
    out, ok, any_l = {}, True, False
    for layer, lvls, lo, hi in (("streaks", ("S7", "S8"), 2.0, 99), ("stains", ("S4", "S5", "S6"), 0.5, 2.0)):
        a = []
        for p in planes.values():
            if "L_" + layer in p and p.get("exposed", True):
                bs = bstats(p, "L_" + layer)
                a += [bs[k]["aniso"] for k in lvls if k in bs and bs[k]["std"] > 1e-4]
        if not a:
            continue
        any_l = True
        med = float(np.median(a))
        good = lo <= med <= hi
        ok &= good
        out[layer] = round(med, 2)
    if not any_l:
        return res("H2", None, None, "no layer maps")
    return res("H2", ok, out)


def rule_H3(cfg, planes, R):
    vals = []
    for p in planes.values():
        if "L_streaks" not in p or "L_stains" not in p:
            continue
        D = painted(p)
        core = (np.nan_to_num(p["L_streaks"]) >= wm.TIER_EDGES[2]) & (np.nan_to_num(p["L_stains"]) >= wm.TIER_EDGES[1])
        if core.sum() < 20:
            continue
        ppm = p["ppm"]
        ring_far = wm.masked_gauss(D, np.isfinite(D), 0.15 * ppm)
        vals.append(np.nanmedian((D - ring_far)[core]))
    if not vals:
        return res("H3", True, "no streak cores inside stains")
    v = float(np.median(vals))
    return res("H3", v >= 0.03, round(v, 4))


# --- I colour --------------------------------------------------------------------------------

def rule_I1(cfg, planes, R):
    db, da = [], []
    for p in planes.values():
        if "labw" not in p or "labc" not in p:
            continue
        D = painted(p)
        m = np.isfinite(D) & (D >= wm.TIER_EDGES[2])
        for ex in ("L_bio", "L_rust"):
            if ex in p:
                m &= ~(np.nan_to_num(p[ex]) >= wm.TIER_EDGES[0])
        if m.sum() < 50:
            continue
        d = p["labw"][m] - p["labc"][m]
        k = D[m] / 0.1
        db.append(np.median(d[:, 2] / k))
        da.append(np.median(np.abs(d[:, 1]) / k))
    if not db:
        return res("I1", None, None, "no colour")
    b, a = float(np.median(db)), float(np.median(da))
    return res("I1", -0.30 <= b <= 0.80 and a <= 1.0, {"db_per_0.1D": round(b, 2), "abs_da_per_0.1D": round(a, 2)})


def rule_I2(cfg, planes, R):
    present = []
    layers = set()
    for p in planes.values():
        layers |= {k[2:] for k in p if k.startswith("L_")}
    if not layers:
        return res("I2", None, None, "no layer maps")
    for layer in sorted(layers):
        v = exposed_vals(planes, "L_" + layer)
        if v.size == 0:
            continue
        share = float((v <= -wm.TIER_EDGES[0]).mean()) if layer in LIGHTENING else float((v >= wm.TIER_EDGES[1]).mean())
        if share >= 0.003:
            present.append(layer)
    E = cfg["E"]
    need = 7 if E >= 25 else 5 if E >= 19 else 3 if E >= 10 else 0
    return res("I2", len(present) >= need, {"present": present, "need": need})


# --- J material ------------------------------------------------------------------------------

J1_LO, J1_HI, J1_SLOPE = 0.012, 0.05, 2.0


def _closeups(cfg):
    d = cfg.get("_dir")
    f = os.path.join(d, "closeups.json") if d else None
    if not f or not os.path.exists(f):
        return []
    out = []
    for c in json.load(open(f, encoding="utf-8")):
        z = np.load(os.path.join(d, c["file"] + ".npz"))
        out.append((c, {k: z[k] for k in z.files}))
    return out


def rule_J1(cfg, planes, R):
    """The clean material: tone varies at every band from 5 mm to 2 m, and it has relief."""
    bad, val = [], {}
    for p in planes.values():
        if not p.get("exposed", True) or "Yc" not in p:
            continue
        m = np.isin(p["cls"], PAINTED)
        if m.sum() < 1000:
            continue
        r = [wm.band_rel_std(p["Yc"].astype(np.float64), m, p["ppm"], a, b) for a, b in wm.J1_BANDS[2:]]
        val[p["name"]] = [round(x, 4) if np.isfinite(x) else None for x in r]
        for (a, b), x in zip(wm.J1_BANDS[2:], r):
            if np.isfinite(x) and not J1_LO <= x <= J1_HI:
                bad.append("%s %g-%g m %.4f" % (p["name"], a, b, x))
    cu = _closeups(cfg)
    if not cu:
        return res("J1", None, val, "no close-ups")
    for c, z in cu:
        v = np.ones(z["Yc_lit"].shape, bool)
        r = [wm.band_rel_std(z["Yc_lit"].astype(np.float64), v, c["ppm"], a, b) for a, b in wm.J1_BANDS[:2]]
        sl = wm.rms_slope_deg(z["height"].astype(np.float64), c["ppm"])
        key = "%s/%s" % (c["plane"], c["spot"])
        val[key] = [round(x, 4) for x in r] + ["slope %.1f deg" % sl]
        for (a, b), x in zip(wm.J1_BANDS[:2], r):
            if not (np.isfinite(x) and J1_LO <= x <= J1_HI):
                bad.append("%s %g-%g m %.4f" % (key, a, b, x))
        if not sl >= J1_SLOPE:
            bad.append("%s slope %.1f" % (key, sl))
    return res("J1", not bad, val, "; ".join(bad))


def rule_J2(cfg, planes, R):
    """Weathering follows the material: the soiling follows the coat's response at 4-50 cm, the
    joints hold dirt, and at close range the dirt sits in the coat's troughs."""
    if cfg.get("E", 0) < 5:
        return res("J2", True, None, "E < 5: not applied")
    soil_max = max((float(np.nanmax(p["L_soiling"])) for p in planes.values() if "L_soiling" in p), default=0.0)
    if soil_max < 0.01:
        return res("J2", None, None, "no soiling to measure")
    bad, val = [], {}
    num = den = 0.0
    jr = []
    for p in planes.values():
        if not p.get("exposed", True) or "L_soiling" not in p or "mat" not in p:
            continue
        m = np.isin(p["cls"], PAINTED) & np.isfinite(p["L_soiling"])
        if m.sum() < 1000:
            continue
        ppm = p["ppm"]
        L = np.where(m, p["L_soiling"].astype(np.float64), 0.0)
        M = np.where(m, p["mat"].astype(np.float64), 0.0)
        bl = wm.masked_gauss(L, m, 0.04 / 3 * ppm) - wm.masked_gauss(L, m, 0.50 / 3 * ppm)
        bm = wm.masked_gauss(M, m, 0.04 / 3 * ppm) - wm.masked_gauss(M, m, 0.50 / 3 * ppm)
        c = wm.corr(bl, bm, m)
        if np.isfinite(c):
            num += c * m.sum()
            den += m.sum()
            val[p["name"]] = round(c, 3)
        if "joint" in p and p["joint"].any() and cfg.get("E", 0) >= 10:
            jm = (p["joint"] > 0) & m
            near = (wm.gauss(jm.astype(np.float64), 0.15 * ppm) > 0.01) & m & ~jm
            if jm.sum() >= 50 and near.sum() >= 50:
                ratio = float(L[jm].mean() / max(L[near].mean(), 1e-6))
                jr.append(ratio)
                val[p["name"] + "/joints"] = round(ratio, 2)
    cm = num / den if den else float("nan")
    val["corr_mean"] = round(cm, 3) if np.isfinite(cm) else None
    if not (np.isfinite(cm) and cm >= 0.25):
        bad.append("soiling-material corr %.3f" % cm)
    if jr and min(jr) < 1.3:
        bad.append("joints %.2f" % min(jr))
    cu = _closeups(cfg)
    if not cu:
        return res("J2", None, val, "no close-ups")
    for c, z in cu:
        if "soil" not in z:
            continue
        cav, soil = z["cav"].astype(np.float64), z["soil"].astype(np.float64)
        hi = cav >= np.quantile(cav, 0.80)
        lo = cav <= np.quantile(cav, 0.50)
        if soil[lo].mean() <= 1e-4:
            continue
        r = float(soil[hi].mean() / soil[lo].mean())
        val["%s/%s troughs" % (c["plane"], c["spot"])] = round(r, 2)
        if r < 1.3:
            bad.append("%s/%s troughs %.2f" % (c["plane"], c["spot"], r))
    return res("J2", not bad, val, "; ".join(bad))


# --- K damage --------------------------------------------------------------------------------

def _damage_amount(cfg):
    am = cfg.get("amounts") or {}
    return float(am.get("damage", 0.0))


def rule_K1(cfg, planes, R):
    a = _damage_amount(cfg)
    if a < 0.2:
        return res("K1", True, {"amount": a}, "little or no damage")
    mk = _marks_all(planes, "L_damage", wm.TIER_EDGES[1])
    if not mk:
        return res("K1", False, {"amount": a, "marks": 0})
    c = wm.level_counts(mk)
    need = 7 if a < 0.5 else 6 if a < 0.75 else 5 if a < 1.0 else 4      # index of the largest level due
    largest = min([i for i in range(8) if c[i] > 0] or [8])
    ok = largest <= need
    bad = []
    lv = [i for i in range(need, 8) if c[i] >= 3]          # from the level due at this amount down to S8
    gm = None
    if len(lv) >= 2:
        gm = (c[lv[-1]] / c[lv[0]]) ** (1.0 / (lv[-1] - lv[0]))
        if not 2.0 <= gm <= 6.0:
            bad.append("mean ratio %.2f" % gm)
        for i0, i1 in zip(lv[:-1], lv[1:]):
            step = (c[i1] / c[i0]) ** (1.0 / (i1 - i0))
            if step < 1.3:
                bad.append("S%d->S%d %.2f" % (i0 + 1, i1 + 1, step))
    ok = ok and not bad
    return res("K1", ok, {"amount": round(a, 2), "counts": c, "largest": "S%d" % (largest + 1) if largest < 8 else "-",
                          "due": "S%d" % (need + 1), "mean_ratio": None if gm is None else round(gm, 2), "bad": bad})


def rule_K3(cfg, planes, R):
    a = _damage_amount(cfg)
    if a < 0.2:
        return res("K3", True, {"amount": a}, "little or no damage")
    edge_n = tot_n = 0
    hot_area = all_area = 0.0
    rs, ds = [], []
    per = []
    any_p = False
    for p in planes.values():
        if "dmg_r" not in p or "edge" not in p:
            continue
        any_p = True
        e = p["edge"].astype(bool)
        ppm = p["ppm"]
        k = max(1, int(0.10 * ppm))
        near = e.copy()
        for s in range(1, k + 1):
            near[s:, :] |= e[:-s, :]
            near[:-s, :] |= e[s:, :]
            near[:, s:] |= e[:, :-s]
            near[:, :-s] |= e[:, s:]
        y, x, r, d = p["dmg_y"], p["dmg_x"], p["dmg_r"], p["dmg_d"]
        cl = d >= -1.0                      # edge-damage clusters and background chips; delamination
        y, x, r, d = y[cl], x[cl], r[cl], d[cl]   # spalls (d = -2, round G) follow K5/K6
        if "dmg_k" in p:
            p = dict(p, dmg_k=p["dmg_k"][cl])
        inb = (y >= 0) & (y < e.shape[0]) & (x >= 0) & (x < e.shape[1])
        edge_n += int(near[y[inb], x[inb]].sum())
        tot_n += int(inb.sum())
        area = np.pi * r.astype(np.float64) ** 2
        hot_area += float(area[d >= 0].sum())
        all_area += float(area.sum())
        sel = d > 0
        rs += r[sel].tolist()
        ds += d[sel].tolist()
        if "dmg_k" in p:
            kk = p["dmg_k"]
            for k_ in np.unique(kk[sel]):
                m_ = sel & (kk == k_)
                if m_.sum() >= 6:
                    per.append((r[m_], d[m_]))
    if not any_p or tot_n == 0:
        return res("K3", None, None, "no chip list")
    edge_share = edge_n / tot_n
    hot_share = hot_area / max(all_area, 1e-12)
    rho = None
    within = None

    def spearman(a_, b_):
        ra, rb = np.argsort(np.argsort(a_)), np.argsort(np.argsort(b_))
        if ra.std() == 0 or rb.std() == 0:
            return None
        return float(np.corrcoef(ra, rb)[0, 1])
    if per:                                     # within each hotspot: size falls with distance
        vals = [v for v in (spearman(a_, b_) for a_, b_ in per) if v is not None]
        if vals:
            rho = float(np.median(vals))
            within = len(vals)
    elif len(rs) >= 10:                         # builds without hotspot ids: pooled
        rho = spearman(rs, ds)
    ok = edge_share >= 0.80 and 0.70 <= hot_share <= 0.90 and (rho is None or rho <= -0.3)
    return res("K3", ok, {"edge_share": round(edge_share, 3), "hotspot_area_share": round(hot_share, 3),
                          "size_vs_distance_rho": None if rho is None else round(rho, 3),
                          "hotspots_measured": within})


def rule_K4(cfg, planes, R):
    """Breaks are sharp, rough and recessed: the outline ramp on radial profiles of every break at
    least 3 px in radius; the exposed concrete's pixel-scale texture inside breaks of 4 cm radius
    and up; their depth."""
    a = _damage_amount(cfg)
    if a < 0.2:
        return res("K4", True, {"amount": a}, "little or no damage")
    widths, hp_rel, depths = [], [], []
    have = False
    for p in planes.values():
        if "dmg_a" not in p or "dmg_r" not in p:
            continue
        have = True
        A = np.nan_to_num(p["dmg_a"].astype(np.float32))
        Hh, Ww = A.shape
        out = np.isnan(p["D"]) if "D" in p else np.zeros(A.shape, bool)   # off the plane: a cut, not an outline
        ppm = p["ppm"]
        y, x, r = p["dmg_y"], p["dmg_x"], p["dmg_r"]
        big = np.flatnonzero(r * ppm >= 3.0)
        rs = np.random.default_rng(7)
        if big.size > 300:
            big = rs.choice(big, 300, replace=False)
        for i in big:
            Rp = float(r[i] * ppm)
            t = np.arange(0.0, 2.4 * Rp + 4, 0.25)
            for th in np.linspace(0, 2 * np.pi, 16, endpoint=False):
                yy = np.round(y[i] - t * np.sin(th)).astype(int)
                xx = np.round(x[i] + t * np.cos(th)).astype(int)
                ok = (yy >= 0) & (yy < Hh) & (xx >= 0) & (xx < Ww)
                if not ok.all() or A[yy[0], xx[0]] < 0.9:
                    continue
                v = A[yy, xx]
                i90 = np.flatnonzero(v < 0.9)
                if i90.size == 0:
                    continue
                i10 = np.flatnonzero(v[i90[0]:] < 0.1)
                if i10.size == 0:
                    continue
                j = i90[0] + i10[0]
                if out[yy[j], xx[j]] or out[yy[i90[0]], xx[i90[0]]]:
                    continue
                widths.append(t[j] - t[i90[0]])
        if "rgb" in p and "dmg_h" in p:
            Y = wm.luminance(np.asarray(p["rgb"], np.float32))
            hp = Y - wm.gauss(Y, 1.5)
            inside = np.zeros(A.shape, bool)
            sp = np.flatnonzero(r >= 0.04)
            for i in sp[:400]:
                Rp = int(r[i] * ppm)
                ya, yb = max(0, y[i] - Rp), min(Hh, y[i] + Rp + 1)
                xa, xb = max(0, x[i] - Rp), min(Ww, x[i] + Rp + 1)
                inside[ya:yb, xa:xb] |= A[ya:yb, xa:xb] >= 0.95
            if inside.sum() >= 50:
                hp_rel.append(float(np.nanstd(hp[inside]) / max(np.nanmean(Y[inside]), 1e-4)))
                depths.append(float(np.nanmedian(np.asarray(p["dmg_h"], np.float32)[inside])))
    if not have:
        return res("K4", None, None, "no break coverage map")
    if not widths:
        return res("K4", None, {"amount": a}, "no break of 3 px radius or more")
    w = float(np.median(widths))
    rel = float(np.median(hp_rel)) if hp_rel else None
    dp = float(np.median(depths)) if depths else None
    ok = w <= 2.0 and (rel is None or rel >= 0.035) and (dp is None or 0.008 <= dp <= 0.045)
    return res("K4", ok, {"outline_px": round(w, 2), "profiles": len(widths),
                          "texture_rel_std": None if rel is None else round(rel, 3),
                          "depth_m": None if dp is None else round(dp, 4)})


def series_damage(runs):
    """K2: between damage steps of 0.25, damaged area x >= 1.6 and chip count x >= 1.5."""
    stats = []
    for cfg, planes in runs:
        area = cnt = 0.0
        for p in planes.values():
            if "L_damage" in p:
                v = painted(p, "L_damage")
                area += float(np.nansum(v >= wm.TIER_EDGES[1])) / p["ppm"] ** 2
            if "dmg_r" in p:
                cnt += len(p["dmg_r"])
        stats.append((area, cnt))
    bad = []
    for i in range(len(stats) - 1):
        (a0, c0), (a1, c1) = stats[i], stats[i + 1]
        if a0 > 0 and (a1 < 1.6 * a0 or c1 < 1.5 * c0):
            bad.append(i)
    return res("K2", not bad, {"area_m2": [round(a, 3) for a, _ in stats], "chips": [int(c) for _, c in stats],
                               "bad_steps": bad})


# --- L controls, A4 presets (series) ----------------------------------------------------------

PRESET_ORDER = ["new", "kept", "typical", "worn", "derelict"]     # round H: the user's rename


def series_presets(runs):
    """A4 (order at every tier, the ground band), A6 (even tone steps) and I5 (green marks darken
    with age) over the presets."""
    order = PRESET_ORDER
    runs = sorted(runs, key=lambda r: order.index(r[0].get("preset")) if r[0].get("preset") in order else 99)
    cov, tones = {}, {}
    for cfg, planes in runs:
        v = local_vals(planes)
        cov[cfg.get("preset")] = [float((v >= t).mean()) for t in wm.TIER_EDGES]
        tones[cfg.get("preset")] = float(np.clip(exposed_vals(planes), -1, 1).mean())
    seq = [k for k in order if k in cov]
    bad = []
    for i in range(len(seq) - 1):
        a, b = cov[seq[i]], cov[seq[i + 1]]
        for t in range(5):
            if not (b[t] > a[t] or (a[t] < 0.001 and b[t] < 0.001)):
                bad.append("%s>=%s at T%d+" % (seq[i], seq[i + 1], t + 1))
    # the ground band: base excess (bottom 1 m over the wall mean, minus 1) rises without a jump
    ex = {}
    for cfg, planes in runs:
        rs = []
        for p in planes.values():
            if not p.get("exposed", True) or p.get("kind") not in ("wall", "gable", "front"):
                continue
            hp = wm.height_profile(p["D"].astype(np.float64), p["ppm"], p.get("ground_row"), p.get("top_row"))
            if hp and hp["base1m"] is not None and hp["mean"] > 1e-4:
                rs.append(hp["base1m"] / hp["mean"] - 1.0)
        if rs:
            ex[cfg.get("preset")] = float(np.mean(rs))
    steps = []
    if all(k in ex for k in seq) and len(seq) >= 3:
        span = ex[seq[-1]] - ex[seq[0]] if seq[0] != "new" else ex[seq[-1]]
        prev = 0.0 if seq[0] == "new" else ex[seq[0]]
        for i, k in enumerate(seq[1:]):
            st = ex[k] - prev
            steps.append(round(st / max(span, 1e-6), 3))
            prev = ex[k]
        if steps and steps[0] > 0.30:
            bad.append("ground band: first step %.2f of the range (max 0.30)" % steps[0])
        if any(s > 0.45 for s in steps):
            bad.append("ground band: a step over 0.45 of the range")
    return [res("A4", not bad, {"coverage": {k: [round(x, 4) for x in cov[k]] for k in seq},
                                "ground_excess": {k: round(v, 3) for k, v in ex.items()}, "ground_steps": steps, "bad": bad}),
            gh.series_steps(tones, order), gh.series_green_age(runs)]


def series_sweep(layer, runs):
    """runs ordered by control value. L1 + L2 on the layer map (or the composite)."""
    key = "L_" + layer
    tiers, tops, steps, lay = [], [], [], []
    prev = None
    for cfg, planes in runs:
        use = key if all(key in p for p in planes.values()) else "D"
        v = gg._layer_vals(planes, key) if layer == "rust" else exposed_vals(planes, use)   # rust: paint and steel
        tiers.append([float((v >= t).mean()) for t in wm.TIER_EDGES[1:]])      # T2+..T6+
        lay.append(tiers[-1][0])
        tops.append(int(sum(1 for t in wm.TIER_EDGES if (v >= t).mean() >= 0.0005)))
        if prev is not None:
            sh, md = [], []
            for name, p in planes.items():
                q = prev.get(name)
                if q is None:
                    continue
                if layer == "rust" and "steel" in p and "L_rust" in p and "L_rust" in q:   # rust shows on the steel too:
                    dom = np.isin(p["cls"], PAINTED) | np.asarray(p["steel"]).astype(bool)  # the layer's own change there
                    d = np.abs(np.where(dom, p["L_rust"].astype(np.float64), np.nan) - np.where(dom, q["L_rust"].astype(np.float64), np.nan))
                else:
                    d = np.abs(painted(p) - painted(q))
                m = np.isfinite(d)
                big = d[m] >= 0.01
                sh.append(float(big.mean()))
                md.append(float(d[m][big].mean()) if big.any() else 0.0)
            steps.append((max(sh) if sh else 0.0, max(md) if md else 0.0))
        prev = planes
    grow, used, front = [], [], []
    floor = 1e-5 if layer == "damage" else 0.002          # breaks are discrete: any area of them counts
    for i in range(len(tiers) - 1):
        t = next((j for j in range(5) if floor < tiers[i][j] < 0.50), None)    # the intensity frontier
        if t is None:
            if max(tiers[i]) <= floor:                       # nothing yet: the next step must add some
                ok_i = tiers[i + 1][0] > floor
                grow.append(ok_i)
                used.append("T2+ from nothing")
            else:
                grow.append(True)
                used.append("all saturated")
            continue
        grow.append(tiers[i + 1][t] >= 1.25 * tiers[i][t])
        used.append("T%d+ %.4f -> %.4f" % (t + 2, tiers[i][t], tiers[i + 1][t]))
        front.append((i, t))
    fr = dict(front)
    heavy = [t[2] / t[0] if t[0] > 0.002 else 0.0 for t in tiers]          # share of the layer's area at T4+

    def up(i):
        return (tops[i + 1] > tops[i] or (i in fr and i - 1 in fr and fr[i] > fr[i - 1])
                or (heavy[i] > 0 and heavy[i + 1] >= 1.10 * heavy[i]))
    rises = sum(1 for i in range(len(tops) - 1) if up(i))      # top tier, frontier, or the heavier share up
    need_rises = (len(tops) - 1 + 1) // 2                     # once per two steps: 2 over a 5-step sweep
    l1 = all(grow) and (layer in ("damage", "rust") or rises >= need_rises)   # full contrast at any amount: K2, R2
    l2 = True
    for i, (sh, md) in enumerate(steps):
        need = min(0.02, 0.5 * lay[i + 1]) if lay[i + 1] > 0 else 0.02
        l2 &= sh >= need and md >= 0.02
    return [res("L1", l1, {"tiers_T2+..T6+": [[round(c, 4) for c in t] for t in tiers], "widened_at": used,
                           "top_tier": tops, "rises": rises}),
            res("L2", l2, {"steps_[share>=0.01, mean|dD|]": [[round(s_, 3), round(m_, 3)] for s_, m_ in steps],
                           "layer_T2+": [round(c, 4) for c in lay]})]


def fresh(cfg):
    """A building with no weathering at all (new): rules about weathering layers do not apply."""
    return cfg.get("E", 0) <= 0.5 and cfg.get("age", 0) <= 0


CONFIG_RULES = [rule_A0, rule_A1, rule_A2, rule_A3, rule_B1, rule_B2, rule_B3, rule_C1, rule_C2, rule_C3, rule_D1,
                rule_E1, rule_F1, rule_F2, rule_F3, rule_F4, rule_G1, rule_G2, rule_G3, rule_G4, rule_H1, rule_H2,
                rule_H3, rule_I1, rule_I2, rule_J1, rule_J2, rule_K1, rule_K3, rule_K4,
                gg.rule_G5, gp.rule_G6, gg.rule_H4, gg.rule_H5, gc.rule_I3,
                gm.rule_M1, gm.rule_M2, gm.rule_M3, gm.rule_M4, gm.rule_M6, gm.rule_M7] + gk.RULES + gn.RULES + gh.RULES


LAYER_RULES = ("C2", "C3", "F2", "G1", "H2", "I1")


SWEEP_EXEMPT = ("A0", "A1", "B1")       # amount budgets: a swept control overrides them by design


def check_config(d, R, sweep=False):
    cfg, planes = load_config(d)
    out = []
    for fn in CONFIG_RULES:
        if sweep and fn.__name__[5:] in SWEEP_EXEMPT:
            out.append(res(fn.__name__[5:], True, None, "sweep entry: amount budget set by the control"))
            continue
        try:
            r = fn(cfg, planes, R)
            if r["pass"] is None and r["id"] in LAYER_RULES and fresh(cfg):
                r = res(r["id"], True, None, "fresh building: no weathering layers")
            off = [k for k, v in (cfg.get("override") or {}).items() if float(v) == 0.0]
            if sweep and r["pass"] is None and off:
                r = res(r["id"], True, None, "sweep step with %s off: nothing of it to measure" % ", ".join(off))
            out.append(r)
        except Exception as e:      # a broken measurement is a failure, never a pass
            out.append(res(fn.__name__[5:], False, None, "error: %r" % (e,)))
    return cfg, out


def summary(results, allow_na=False):
    fails = [r["id"] for r in results if r["pass"] is False]
    nas = [r["id"] for r in results if r["pass"] is None]
    accepted = not fails and (allow_na or not nas)
    return {"accepted": accepted, "fail": fails, "na": nas}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["check", "series"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--rules", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_rules.json"))
    ap.add_argument("--json")
    ap.add_argument("--allow-na", action="store_true")
    ap.add_argument("--sweep", action="store_true", help="a sweep entry: amount budgets A0/A1/B1 not applied")
    a = ap.parse_args()
    R = json.load(open(a.rules, encoding="utf-8"))
    if a.mode == "check":
        cfg, out = check_config(a.args[0], R, sweep=a.sweep)
        s = summary(out, a.allow_na)
        report = {"config": cfg, "rules": out, "summary": s}
    else:
        kind, dirs = a.args[0], a.args[1:]
        runs = [load_config(d) for d in dirs]
        if kind == "presets":
            out = series_presets(runs)
        elif kind == "seeds":
            out = [gh.series_seeds(runs, local_vals, exposed_vals)]
        elif kind.startswith("sweep:"):
            layer = kind.split(":", 1)[1]
            out = series_sweep(layer, runs)
            if layer == "damage":
                out.append(series_damage(runs))
            if layer == "bio":
                out += [gm.series_growth(runs), gm.series_fronts(runs), gh.series_growth_age(runs)]
            if layer == "rust":
                out.append(gh.series_rust(runs))
            vals = [(c.get("override") or {}).get(layer) for c, _ in runs]
            for extra in (gg.series_even(layer, runs, vals), gg.series_top(layer, runs, vals)):
                if extra is not None:
                    out.append(extra)
        else:
            raise SystemExit("unknown series kind " + kind)
        s = summary(out, a.allow_na)
        report = {"series": kind, "dirs": dirs, "rules": out, "summary": s}
    for r in report["rules"]:
        flag = {True: "pass", False: "FAIL", None: "na  "}[r["pass"]]
        print("%-4s %s  %s %s" % (r["id"], flag, json.dumps(r["value"])[:300], r["detail"]))
    print("ACCEPTED" if report["summary"]["accepted"] else "REJECTED", report["summary"])
    if a.json:
        json.dump(report, open(a.json, "w", encoding="utf-8"), indent=1)
    sys.exit(0 if report["summary"]["accepted"] else 1)


if __name__ == "__main__":
    main()
