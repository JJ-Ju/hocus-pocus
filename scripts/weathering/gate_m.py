"""Round-G growth rules (M family; roundG/research/organic-growth.md). numpy only.

M1 light growth is a tint; M2 severe growth is dark green or rust brown; M3 growth sits where
water stays; M4 the plinth belt; M5 (series) time unattended adds area grown from the old
patches; M6 patch outlines are ragged fronts."""
import numpy as np

import weather_measure as wm

BIO_STEPS = ([0.25, 0.5, 0.75, 1.0], [3.7, 5.9, 10.2, 22.0])   # as weather_fields.bio_years
BIO_EDGES = (0.15, 0.40, 0.70)               # wetness classes W0 | W1 | W2 | W3 (growth research 2.2)
BIO_XMAX = (0.30, 0.60, 0.90, 0.95)          # class ceilings (research 3.3)
O11 = [(3, 1.0, 0.15, None), (3, 3.0, 0.50, None), (2, 3.0, 0.10, None), (2, 8.0, 0.30, None),
       (1, 8.0, 0.03, None), (0, 15.0, None, 0.05)]   # (class, years, at least, at most)


def bio_years(a):
    xs, ys = BIO_STEPS
    if a <= 0:
        return 0.0
    if a < xs[0]:
        return float(ys[0] * a / xs[0])
    if a > xs[-1]:
        return float(ys[-1] * np.exp(np.log(ys[-1] / ys[-2]) / (xs[-1] - xs[-2]) * (a - xs[-1])))
    return float(np.exp(np.interp(a, xs, np.log(ys))))


def _dilate(m, r):
    out = m.astype(np.uint8)
    for ax in (0, 1):
        out = wm._sliding_max(out, r, ax)
    return out > 0


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg, layer):
    return float((cfg.get("amounts") or {}).get(layer, 0.0))


def _bio_px(p, lo, hi=None):
    """Pixels where growth makes most of the darkening, with L_bio in [lo, hi)."""
    if "L_bio" not in p or "labw" not in p:
        return None
    L = np.nan_to_num(p["L_bio"].astype(np.float64))
    D = np.nan_to_num(p["D"].astype(np.float64))
    m = (L >= lo) & (L >= 0.6 * np.maximum(D, 1e-6)) & np.isfinite(p["D"])
    if hi is not None:
        m &= L < hi
    return m


def rule_M1(cfg, planes, R):
    """Light growth is a tint (yellow-green or dull rusty yellow), not grey."""
    rows = []
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        m = _bio_px(p, wm.TIER_EDGES[1], wm.TIER_EDGES[3])
        if m is None or m.sum() == 0:
            continue
        w = p["labw"][m].astype(np.float64)
        c = p["labc"][m].astype(np.float64)
        per = np.maximum(np.nan_to_num(p["D"][m].astype(np.float64)), 0.02) / 0.1
        rows.append(np.c_[(w[:, 1] - c[:, 1]) / per, (w[:, 2] - c[:, 2]) / per])
    n = sum(len(r) for r in rows)
    if n < 200:
        return res("M1", True, {"px": n}, "little light growth")
    x = np.concatenate(rows)
    da, db = x[:, 0], x[:, 1]
    yel = (da >= 0.3) & (db >= 3.0)
    dirt = db <= 0.8
    green = ~yel
    med_db = float(np.median(db))
    med_da = float(np.median(da[green])) if green.any() else 0.0
    ok = 2.5 <= med_db <= 7.0 and -3.0 <= med_da <= -0.4 and 0.10 <= float(yel.mean()) <= 0.45 and float(dirt.mean()) <= 0.10
    return res("M1", ok, {"px": int(n), "db_per_0.1D": round(med_db, 2), "da_green_per_0.1D": round(med_da, 2),
                          "yellow_share": round(float(yel.mean()), 3), "dirt_band_share": round(float(dirt.mean()), 3)})


def rule_M2(cfg, planes, R):
    """Severe growth (the darkest, L_bio >= 0.55) is dark green or rust brown, black only in part:
    black (C* < 8) <= 35 %; of the rest, C* 10-26 and a green (95-135 deg) or rust (40-75 deg) hue
    for >= 75 %, and the darkest quarter at L* <= 50."""
    ws = []
    for p in planes.values():
        if not p.get("exposed", True) or p.get("orient") == "S":     # south: moulds (O8), not algae
            continue
        m = _bio_px(p, 0.55)
        if m is None or m.sum() == 0:
            continue
        ws.append(p["labw"][m].astype(np.float64))
    n = sum(len(w) for w in ws)
    if n < 2000:                              # under 0.8 m2: not a population of severe growth
        return res("M2", True, {"px": n}, "little severe growth")
    w = np.concatenate(ws)
    L, C = w[:, 0], np.hypot(w[:, 1], w[:, 2])
    hue = (np.degrees(np.arctan2(w[:, 2], w[:, 1])) + 360) % 360
    black = float((C < 8).mean())
    nb = C >= 8
    if nb.sum() < 50:
        return res("M2", False, {"px": int(n), "black_share": round(black, 3)}, "all black")
    chroma = float(((C[nb] >= 10) & (C[nb] <= 26)).mean())
    hue_ok = float((((hue[nb] >= 95) & (hue[nb] <= 135)) | ((hue[nb] >= 40) & (hue[nb] <= 75))).mean())
    dark = float(np.percentile(L[nb], 25))
    ok = black <= 0.35 and chroma >= 0.75 and hue_ok >= 0.75 and dark <= 50
    return res("M2", ok, {"px": int(n), "black_share": round(black, 3), "chroma_share": round(chroma, 3),
                          "hue_share": round(hue_ok, 3), "L_p25": round(dark, 1)})


def rule_M3(cfg, planes, R):
    """O4: growth sits where water stays. Pooled over exposed planes, the share of growth (T2+) in
    damp and wet zones (W2-W3, wetness >= 0.40): >= 70 % while growth covers under 5 %, >= 50 % at
    5-20 %; sunny open wall (W0, wetness < 0.15) holds <= 10 %."""
    n_g = n_m = n23 = n0 = 0
    for p in planes.values():
        if not p.get("exposed", True) or "L_bio" not in p or "bio_w" not in p:
            continue
        m = np.isfinite(p["D"])
        g = (np.nan_to_num(p["L_bio"]) >= wm.TIER_EDGES[1]) & m
        w = p["bio_w"].astype(np.float32)
        n_m += int(m.sum())
        n_g += int(g.sum())
        n23 += int((g & (w >= BIO_EDGES[1])).sum())
        n0 += int((g & (w < BIO_EDGES[0])).sum())
    cov = n_g / max(n_m, 1)
    if n_g < 400:
        return res("M3", True, {"cover": round(cov, 4)}, "little growth")
    s23, s0 = n23 / n_g, n0 / n_g
    need = 0.70 if cov < 0.05 else 0.50 if cov < 0.20 else None
    ok = (need is None or s23 >= need) and s0 <= 0.10
    return res("M3", ok, {"cover": round(cov, 4), "W2_W3_share": round(s23, 3), "need": need,
                          "W0_share": round(s0, 3)})


def _foot_rows(p):
    cls, gr, ppm = p.get("cls"), p.get("ground_row"), p["ppm"]
    if cls is None or gr is None:
        return None
    painted = np.isin(cls, (1, 2)) & np.isfinite(p["D"])
    rows = np.arange(cls.shape[0])[:, None]
    low = np.where(painted & (rows > gr - 3 * ppm), rows, -1).max(axis=0)
    return np.where(low > 0, low, gr).astype(np.float64)


def rule_M4(cfg, planes, R):
    """O5 plinth belt: growth in the bottom 0.3 m over the open wall (wetness < 0.4: not under
    another ledge or joint) 0.5-1.5 m above the foot, >= 3 (N, E, W walls)."""
    if bio_years(_amount(cfg, "bio")) < 2.0:
        return res("M4", True, {"amount": _amount(cfg, "bio")}, "under 2 years of growth")
    out, ok, any_ = {}, True, False
    for p in planes.values():
        if not p.get("exposed", True) or p.get("orient") == "S" or "L_bio" not in p:
            continue
        fr = _foot_rows(p)
        if fr is None:
            continue
        ppm = p["ppm"]
        h = (fr[None, :] - np.arange(p["D"].shape[0])[:, None]) / ppm
        L = np.nan_to_num(p["L_bio"].astype(np.float64))
        m = np.isfinite(p["D"])
        lo = m & (h >= 0) & (h < 0.3)
        hi = m & (h >= 0.5) & (h < 1.5)
        if "bio_w" in p:                     # the open wall above the belt, not other damp features
            hi &= p["bio_w"].astype(np.float32) < BIO_EDGES[1]
        if lo.sum() < 50 or hi.sum() < 50:
            continue
        a_, b_ = float(L[lo].mean()), float(L[hi].mean())
        if a_ < 0.002:
            continue
        any_ = True
        r = a_ / max(b_, 1e-4)
        ok &= r >= 3.0
        out[p["name"]] = round(r, 2)
    if not any_:
        return res("M4", True, None, "no foot growth to measure")
    return res("M4", ok, out)


def box_dim(mask, sizes=(2, 4, 8, 16, 32)):
    """Box-counting dimension of a mask's boundary (pixels with a 4-neighbour outside)."""
    m = mask
    b = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    ns = []
    for s in sizes:
        H, W = b.shape
        h, w = H // s, W // s
        if h == 0 or w == 0:
            return None
        bb = b[:h * s, :w * s].reshape(h, s, w, s).any(axis=(1, 3))
        ns.append(max(1, int(bb.sum())))
    return float(np.polyfit(np.log(1.0 / np.array(sizes, float)), np.log(np.array(ns, float)), 1)[0])


def outline_dim(g, min_px=20):
    """Perimeter-area dimension of a mask's patches: fit log P = (D / 2) log A over patches of
    min_px or more (a disc gives about 1; ragged fronts 1.15-1.4)."""
    lab, n = wm.label(g)
    if n < 5:
        return None
    b = g & ~(np.roll(g, 1, 0) & np.roll(g, -1, 0) & np.roll(g, 1, 1) & np.roll(g, -1, 1))
    A = np.bincount(lab.ravel(), minlength=n + 1)[1:].astype(np.float64)
    P = np.bincount(lab[b].ravel(), minlength=n + 1)[1:].astype(np.float64)
    k = (A >= min_px) & (P > 0)
    if k.sum() < 5 or np.ptp(np.log(A[k])) < 1.0:
        return None
    return float(2.0 * np.polyfit(np.log(A[k]), np.log(P[k]), 1)[0])


def rule_M6(cfg, planes, R):
    """O12: patch outlines are ragged fronts, not smooth blobs: perimeter-area dimension 1.10-1.45,
    on planes where growth covers at least 3 %."""
    out, ok, any_ = {}, True, False
    for p in planes.values():
        if not p.get("exposed", True) or "L_bio" not in p:
            continue
        m = np.isfinite(p["D"])
        g = (np.nan_to_num(p["L_bio"]) >= wm.TIER_EDGES[1]) & m
        if g.sum() < 0.03 * m.sum() or g.sum() < 400:
            continue
        d = outline_dim(g, min_px=60)
        if d is None:
            continue
        any_ = True
        ok &= 1.10 <= d <= 1.45
        out[p["name"]] = round(d, 3)
    if not any_:
        return res("M6", True, None, "little growth")
    return res("M6", ok, out)


def series_growth(runs):
    """M5 (O9): time unattended adds area grown from the old patches. Per step: area x >= 1.25
    while the damp and wet zones (W2-W3) are under 85 % covered, at least half the added darkening
    on newly covered pixels, >= 95 % of the old growth kept."""
    stats, bad = [], []
    prev = None
    for cfg, planes in runs:
        cur = {n: (np.nan_to_num(p["L_bio"].astype(np.float64)), p.get("bio_w"), np.isfinite(p["D"]))
               for n, p in planes.items() if p.get("exposed", True) and "L_bio" in p}
        if prev is not None:
            area0 = area1 = 0
            add_new = add_all = keep = old = 0.0
            w23 = c23 = 0
            for n in cur:
                if n not in prev:
                    continue
                L0, L1 = prev[n][0], cur[n][0]
                g0, g1 = L0 >= wm.TIER_EDGES[1], L1 >= wm.TIER_EDGES[1]
                area0 += int(g0.sum())
                area1 += int(g1.sum())
                dd = np.clip(L1 - L0, 0, None)
                add_all += float(dd.sum())
                add_new += float(dd[g1 & ~g0].sum())
                keep += float((g0 & g1).sum())
                old += float(g0.sum())
                if cur[n][1] is not None:
                    z = (cur[n][1].astype(np.float32) >= BIO_EDGES[1]) & cur[n][2]
                    w23 += int(z.sum())
                    c23 += int((z & g0).sum())
            full = c23 / max(w23, 1)
            st = {"area_x": round(area1 / max(area0, 1), 2), "new_share": round(add_new / max(add_all, 1e-9), 3),
                  "kept": round(keep / max(old, 1), 3), "W2_W3_cover_before": round(full, 3)}
            if area0 > 50 and ((st["area_x"] < 1.25 and full < 0.85) or st["new_share"] < 0.5 or st["kept"] < 0.95):
                bad.append(len(stats))
            stats.append(st)
        prev = cur
    return res("M5", not bad, {"steps": stats, "bad_steps": bad})


def rule_M7(cfg, planes, R):
    """O11: onset by wetness class. Growth (T2+) cover of each class's area at the build's years
    unattended: W3 >= 15 % from 1 year and >= 50 % from 3; W2 >= 10 % from 3 years and >= 30 % from
    8; W1 >= 3 % from 8 years; W0 <= 5 % up to 15 years; no class over its ceiling (+0.03)."""
    t = bio_years(_amount(cfg, "bio"))
    if t <= 0:
        return res("M7", True, {"years": 0.0}, "no growth")
    cov, tot = np.zeros(4), np.zeros(4)
    for p in planes.values():
        if not p.get("exposed", True) or "L_bio" not in p or "bio_w" not in p:
            continue
        m = np.isfinite(p["D"])
        c = np.digitize(p["bio_w"].astype(np.float32), BIO_EDGES)
        g = (np.nan_to_num(p["L_bio"]) >= wm.TIER_EDGES[1]) & m
        for k in range(4):
            mk = m & (c == k)
            tot[k] += mk.sum()
            cov[k] += (g & mk).sum()
    X = cov / np.maximum(tot, 1)
    fails = []
    for (k, yr, lo, hi) in O11:
        if tot[k] < 2000:
            continue
        if lo is not None and t >= yr and X[k] < lo:
            fails.append("W%d %.3f < %.2f at %.0f+ years" % (k, X[k], lo, yr))
        if hi is not None and t <= yr and X[k] > hi:
            fails.append("W%d %.3f > %.2f up to %.0f years" % (k, X[k], hi, yr))
    for k in range(4):
        if tot[k] >= 2000 and X[k] > BIO_XMAX[k] + 0.03:
            fails.append("W%d %.3f over its ceiling %.2f" % (k, X[k], BIO_XMAX[k]))
    return res("M7", not fails, {"years": round(t, 1), "cover": {"W%d" % k: round(float(X[k]), 3) for k in range(4)},
                                 "class_px": {"W%d" % k: int(tot[k]) for k in range(4)}, "fails": fails})


def series_fronts(runs):
    """M8 (O10): fronts grow outward. Per step, new growth (T2+) within 0.3 m of the previous
    step's growth is front growth, the rest new patches: front >= 70 %, new patches 5-30 %."""
    stats, bad = [], []
    prev = None
    for cfg, planes in runs:
        cur = {n: (np.nan_to_num(p["L_bio"].astype(np.float64)) >= wm.TIER_EDGES[1], p["ppm"])
               for n, p in planes.items() if p.get("exposed", True) and "L_bio" in p}
        if prev is not None:
            near = far = 0
            for n in cur:
                if n not in prev:
                    continue
                g0, g1, ppm = prev[n][0], cur[n][0], cur[n][1]
                new = g1 & ~g0
                z = _dilate(g0, int(round(0.3 * ppm)))
                near += int((new & z).sum())
                far += int((new & ~z).sum())
            tot = near + far
            st = {"new_px": tot, "front_share": round(near / max(tot, 1), 3)}
            if tot >= 400 and not (st["front_share"] >= 0.70 and 0.05 <= 1 - st["front_share"] <= 0.30):
                bad.append(len(stats))
            stats.append(st)
        prev = cur
    return res("M8", not bad, {"steps": stats, "bad_steps": bad})
