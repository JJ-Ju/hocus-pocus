"""gate_r.py - round-I rust rules from docs/redesign/research/weathering-rust-water.md §7.2: rust follows
the water (R3), grows along the flow between steps (R4, series), post feet stain the concrete (R5),
and its colour follows age and density (R6; the old-against-new part is a series). Imported by
weather_gate. The steel's parts (rails, uprights, joints, feet) come from its geometry
(rust_flow.members), never from the generator's own state."""
import numpy as np

import weather_measure as wm

PAINTED = (1, 2)
RUST_DE = 8.0                       # rust shows on the steel: colour difference 8 or more (as R1)
R3C = {"a_min": 0.25, "feet": (0.4, 0.8), "rails_x": 3.0, "faces_max": (0.10, 0.25), "panel_low": 0.60, "panel_px": 200,
       "ts": (0.6, 0.85), "ts_from": 0.2}   # the T clause from 0.2: Typical (0.228), where the user named it       # K: Ts (a bar under the top rail and the rail's underside corners) rusted, from 0.25 / 0.5
R4C = {"along_m": 0.30, "down_m": 0.50, "up_m": 0.05, "share": 0.70, "creep_max": 0.10, "seg_x": 1.3, "rails_full": 0.80}
R5C = {"stained": ((0.25, 0.5, 0.75, 1.0), (0.25, 0.5, 0.8, 0.9)), "reach_m": 0.10, "head": (1.5, 4.5),
       "cover": {0.5: (0.05, 0.20), 1.0: (0.20, 0.50)}, "cover_m": 0.05, "parapet": (0.30, 0.20), "win_m": 0.12}
R6C = {"steel_hue": (40.0, 75.0), "steel_C": (10.0, 35.0), "old_dL": 4.0, "head_hue": (48.0, 62.0),
       "tail_hue": (64.0, 80.0), "head_dL": 6.0, "min_px": 30}


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg):
    ov = cfg.get("override") or {}
    return float(ov.get("rust", (cfg.get("amounts") or {}).get("rust", 0)) or 0)


def _geo(p):
    """Members of the plane's steel (cached on the plane dict)."""
    if "_rust_geo" not in p:
        import rust_flow as rfl
        st = np.asarray(p["steel"]).astype(bool)
        pl = {"ppm": p["ppm"], "mask": np.isin(p["cls"], PAINTED), "cls": p["cls"]}
        M = rfl.members(pl, st)
        p["_rust_geo"] = (st, M, pl)
    return p["_rust_geo"]


def _rusted(p, st):
    d = np.sqrt(((p["labw"].astype(np.float64) - p["labc"].astype(np.float64)) ** 2).sum(axis=-1))
    L = np.nan_to_num(np.asarray(p["L_rust"], np.float64))
    return st & (d >= RUST_DE) & (np.abs(L) > 1e-4)


def _parts(M, st):
    up03 = M["upright"] & ~M["joint"] & ~M["foot"] & (M["depth"] <= 0.3)
    faces = (M["upright"] | M["other"]) & ~M["joint"] & ~M["foot"] & ~up03
    return {"feet": M["foot"] & st, "joints": M["joint"] & ~M["foot"] & st, "rails": M["rail"] & st,
            "up03": up03 & st, "faces": faces & st}


def _planes(planes):
    for p in planes.values():
        if "steel" in p and "labw" in p and "labc" in p and "L_rust" in p and (np.asarray(p["steel"]) > 0).any():
            yield p


def rule_R3(cfg, planes, R):
    """R3 (round I, research §7.2): rust follows the water. From rust 0.25: feet rusted 50 % or more (80 %
    from 0.5); the rails' rusted share 3x or more that of the other upright faces; those faces hold at
    most 10 % of all rust up to 0.75 and 25 % at 1.0."""
    a = _amount(cfg)
    if a < R3C["ts_from"]:
        return res("R3", True, {"amount": a}, "under %.2f" % R3C["ts_from"])
    ts_only = a < R3C["a_min"]                         # 0.2-0.25: only the T clause binds
    n = {k: 0 for k in ("feet", "joints", "rails", "up03", "faces")}
    r = dict(n)
    tot_r = 0
    pan_r = pan_low = 0
    t_n = t_r = 0
    for p in _planes(planes):
        st, M, _ = _geo(p)
        rust = _rusted(p, st)
        if "tcorner" in M:                            # K: each T rusted anywhere (the joint or its corners)
            labT, nT = wm.label(M["tjoint"] | M["tcorner"])
            if nT:
                hitT = np.zeros(nT + 1, bool)
                np.logical_or.at(hitT, labT[labT > 0], rust[labT > 0])
                t_n += nT
                t_r += int(hitT[1:].sum())
        pr = rust & M["panel"]
        if pr.any():                                  # panels: rust in each panel's bottom quarter
            lab, nl = wm.label(M["panel"])
            ys, xs = np.nonzero(lab)
            ll = lab[ys, xs]
            y0 = np.full(nl + 1, 1 << 30)
            y1 = np.full(nl + 1, -1)
            np.minimum.at(y0, ll, ys)
            np.maximum.at(y1, ll, ys)
            ry, rx = np.nonzero(pr)
            rl = lab[ry, rx]
            q = y1[rl] - (y1[rl] - y0[rl] + 1) / 4.0
            pan_r += int(ry.size)
            pan_low += int((ry >= q).sum())
        rust = rust & ~M["panel"]
        tot_r += int(rust.sum())
        for k, m in _parts(M, st).items():
            n[k] += int(m.sum())
            r[k] += int((m & rust).sum())
    if tot_r < 50 or n["feet"] == 0:
        return res("R3", True, {"rusted_px": tot_r}, "little rust or no feet")
    sh = {k: (r[k] / n[k] if n[k] else 0.0) for k in n}
    faces_of_all = r["faces"] / tot_r
    need_feet = R3C["feet"][1] if a >= 0.5 else R3C["feet"][0]
    faces_max = R3C["faces_max"][1] if a > 0.75 else R3C["faces_max"][0]
    ok = sh["feet"] >= need_feet and sh["rails"] >= R3C["rails_x"] * sh["faces"] and faces_of_all <= faces_max
    if ts_only:
        ok = True
    ts_sh = t_r / t_n if t_n else None
    need_ts = R3C["ts"][1] if a >= 0.5 else R3C["ts"][0]
    if ts_sh is not None:
        ok = ok and ts_sh >= need_ts
    low = pan_low / pan_r if pan_r else None
    if pan_r >= R3C["panel_px"] and not ts_only:
        ok &= low >= R3C["panel_low"]
    return res("R3", ok, {"amount": round(a, 3), "rusted_share": {k: round(v, 3) for k, v in sh.items()},
                          "faces_of_all_rust": round(faces_of_all, 3), "need_feet": need_feet, "faces_max": faces_max,
                          "ts_rusted": None if ts_sh is None else round(ts_sh, 3), "need_ts": need_ts, "ts": t_n,
                          "panel_rust_px": pan_r, "panel_bottom_quarter": None if low is None else round(low, 3),
                          "binding": "T clause only (rust under %.2f)" % R3C["a_min"] if ts_only else "all"})


def _foot_stains(p):
    """Per post foot over paint: (stained?, head width m, lowest-quarter width m, post width m, length m,
    parapet?, head px, tail px)."""
    st, M, pl = _geo(p)
    ppm = p["ppm"]
    H, W = st.shape
    paint = pl["mask"]
    L = np.nan_to_num(np.asarray(p["L_rust"], np.float64))
    stain = paint & (L >= wm.TIER_EDGES[1])
    lab, n = wm.label(M["foot"])
    out = []
    if not n:
        return out
    ys, xs = np.nonzero(lab)
    ll = lab[ys, xs]
    yb = np.full(n + 1, -1)
    np.maximum.at(yb, ll, ys)
    x0 = np.full(n + 1, W)
    x1 = np.full(n + 1, -1)
    np.minimum.at(x0, ll, xs)
    np.maximum.at(x1, ll, xs)
    par = np.zeros(n + 1, bool)
    np.logical_or.at(par, ll, M["parapet"][ys, xs])
    hw = int(R5C["win_m"] * ppm)
    for i in range(1, n + 1):
        y0 = int(yb[i]) + 1
        xc = int((x0[i] + x1[i]) // 2)
        if y0 >= H or not paint[y0, xc]:
            continue
        xa, xb = max(0, xc - hw), min(W, xc + hw + 1)
        win = stain[y0:min(H, y0 + int(1.0 * ppm)), xa:xb]
        rows = win.any(axis=1)
        ln = 0
        while ln < rows.size and rows[ln]:
            ln += 1
        post_w = (x1[i] - x0[i] + 1) / ppm
        if ln == 0:
            out.append((False, 0.0, 0.0, post_w, 0.0, bool(par[i]), None, None))
            continue
        widths = win[:ln].sum(axis=1) / ppm
        k4 = max(1, int(round(0.04 * ppm)))
        head = float(widths[:k4].max())
        q = max(1, ln // 4)
        low = float(widths[ln - q:ln].max())
        hy, hx = np.nonzero(win[:max(1, ln // 4)])
        ty, tx = np.nonzero(win[ln // 2:ln])
        hp = (hy + y0, hx + xa)
        tp = (ty + y0 + ln // 2, tx + xa)
        out.append((ln / ppm >= R5C["reach_m"], head, low, post_w, ln / ppm, bool(par[i]), hp, tp))
    return out


def rule_R5(cfg, planes, R):
    """R5 (round I, research §7.2): post feet stain the concrete. Stained feet (rust on the paint below,
    T2+, reaching 0.1 m) 25 / 50 / 80 / 90 % at rust 0.25 / 0.5 / 0.75 / 1.0; the head 1.5-4.5x the post
    width (median) and the lowest quarter no wider than the head (80 % of stains); the slab-edge face
    below the rails rusted over 5-20 % of its width at 0.5 and 20-50 % at 1.0 (top 0.05 m); parapet
    plates: 30 % or fewer stain the outer face, each 0.2 m or shorter."""
    a = _amount(cfg)
    if a < 0.25:
        return res("R5", True, {"amount": a}, "under 0.25")
    feet, cov_n, cov_r = [], 0, 0
    import rust_flow as rfl
    for p in _planes(planes):
        feet += _foot_stains(p)
        st, M, pl = _geo(p)
        fy, fx = rfl.face_below(pl, M)
        if fy.size:
            L = np.nan_to_num(np.asarray(p["L_rust"], np.float64))
            k = max(1, int(round(R5C["cover_m"] * p["ppm"])))
            for y, x in zip(fy, fx):
                cov_n += 1
                cov_r += int((L[y:y + k, x] >= wm.TIER_EDGES[1]).any())
    open_ = [f for f in feet if not f[5]]
    par = [f for f in feet if f[5]]
    if len(open_) < 10:
        return res("R5", True, {"feet": len(open_)}, "few feet")
    xs, ys = R5C["stained"]
    need = float(np.interp(a, xs, ys))
    stained = [f for f in open_ if f[0]]
    share = len(stained) / len(open_)
    ratio = float(np.median([f[1] / max(f[3], 1e-6) for f in stained])) if stained else 0.0
    narrow = float(np.mean([f[2] <= f[1] + 1e-9 for f in stained])) if stained else 1.0
    cover = cov_r / cov_n if cov_n else 0.0
    ok = share >= need and (not stained or (R5C["head"][0] <= ratio <= R5C["head"][1] and narrow >= 0.8))
    band = None
    if a >= 0.5 and cov_n:
        lo = float(np.interp(a, [0.5, 1.0], [R5C["cover"][0.5][0], R5C["cover"][1.0][0]]))
        hi = float(np.interp(a, [0.5, 1.0], [R5C["cover"][0.5][1], R5C["cover"][1.0][1]]))
        band = [round(lo, 3), round(hi, 3)]
        ok &= lo <= cover <= hi
    par_sh = (sum(1 for f in par if f[0]) / len(par)) if par else 0.0
    par_long = max([f[4] for f in par], default=0.0)
    ok &= (not par) or (par_sh <= R5C["parapet"][0] and par_long <= R5C["parapet"][1] + 0.02)
    return res("R5", ok, {"amount": round(a, 3), "feet": len(open_), "stained_share": round(share, 3), "need": round(need, 3),
                          "head_over_post": round(ratio, 2), "tail_not_wider": round(narrow, 3), "slab_cover": round(cover, 3),
                          "cover_band": band, "parapet_stained": round(par_sh, 3), "parapet_longest_m": round(par_long, 2)})


def _lch(lab):
    return lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]), (np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) + 360.0) % 360.0


def rule_R6(cfg, planes, R):
    """R6 (round I, research §7.2): rust colour. From 0.25: rusted steel at hue 40-75 deg and C* 10-35
    (medians); stains on the paint below the feet have a darker, redder head (hue 48-62) than their
    tail (64-80), head L* 6 or more below the tail's."""
    a = _amount(cfg)
    if a < 0.25:
        return res("R6", True, {"amount": a}, "under 0.25")
    labs, heads, tails = [], [], []
    for p in _planes(planes):
        st, M, pl = _geo(p)
        rust = _rusted(p, st)
        labs.append(p["labw"][rust].astype(np.float64))
        for f in _foot_stains(p):
            if f[0] and f[6] is not None:
                heads.append(p["labw"][f[6]].astype(np.float64))
                tails.append(p["labw"][f[7]].astype(np.float64))
    v = {"amount": round(a, 3)}
    ok = True
    lab = np.concatenate(labs) if labs else np.zeros((0, 3))
    if lab.shape[0] >= R6C["min_px"]:
        L, C, h = _lch(lab)
        v["steel_hue"], v["steel_C"] = round(float(np.median(h)), 1), round(float(np.median(C)), 1)
        ok &= R6C["steel_hue"][0] <= v["steel_hue"] <= R6C["steel_hue"][1] and R6C["steel_C"][0] <= v["steel_C"] <= R6C["steel_C"][1]
    hd = np.concatenate(heads) if heads else np.zeros((0, 3))
    tl = np.concatenate(tails) if tails else np.zeros((0, 3))
    if hd.shape[0] >= R6C["min_px"] and tl.shape[0] >= R6C["min_px"]:
        Lh, _, hh = _lch(hd)
        Lt, _, ht = _lch(tl)
        v["head_hue"], v["tail_hue"] = round(float(np.median(hh)), 1), round(float(np.median(ht)), 1)
        v["head_L"], v["tail_L"] = round(float(np.median(Lh)), 1), round(float(np.median(Lt)), 1)
        ok &= (R6C["head_hue"][0] <= v["head_hue"] <= R6C["head_hue"][1] and R6C["tail_hue"][0] <= v["tail_hue"] <= R6C["tail_hue"][1]
               and v["head_L"] <= v["tail_L"] - R6C["head_dL"])
    return res("R6", ok, v)


def _hdilate(m, r):
    out = m.copy()
    for k in range(1, r + 1):
        out[:, k:] |= m[:, :-k]
        out[:, :-k] |= m[:, k:]
    return out


def _down(m, r):
    """Pixels up to r below a True pixel in their column."""
    out = np.zeros_like(m)
    for k in range(1, r + 1):
        out[k:] |= m[:-k]
    return out


def _up(m, r):
    out = np.zeros_like(m)
    for k in range(1, r + 1):
        out[:-k] |= m[k:]
    return out


def _segments(rail_rust, rail):
    """Mean length (px) of the rusted runs along the rails' rows."""
    lens = []
    for y in np.flatnonzero(rail_rust.any(axis=1)):
        row = rail_rust[y].astype(np.int8)
        d = np.diff(np.concatenate([[0], row, [0]]))
        st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        lens += list(en - st)
    return float(np.mean(lens)) if lens else 0.0


def series_rust_flow(runs):
    """R4 and R6 (series, round I): between rust steps, 70 % or more of the new rusted steel continues
    earlier rust along its member (0.3 m along a rail, 0.5 m down or 0.05 m up an upright) or starts at a
    foot or joint (round K: a T with the rail's underside corners beside it, as R3 counts it); 10 % or less creeps up an upright more than 0.05 m above earlier rust; the mean rusted
    rail segment grows x1.3 or more a step until the rails are 80 % rusted. R6: the rust already there at
    the last step is 4 or more L* darker than the new rust (medians)."""
    steps, bad4, bad6 = [], [], []
    prev = None
    for cfg, planes in runs:
        cur = {}
        for p in _planes(planes):
            st, M, _ = _geo(p)
            cur[p["name"]] = (_rusted(p, st), st, M, p)
        if prev is not None:
            new_n = cont_n = creep_n = 0
            seg0 = seg1 = 0.0
            rails_n = rails_r = 0
            Lo, Ln = [], []
            for name, (r1, st, M, p) in cur.items():
                if name not in prev:
                    continue
                r0 = prev[name][0] & ~prev[name][2]["panel"]
                r1 = r1 & ~M["panel"]
                ppm = p["ppm"]
                new = r1 & ~r0
                near = (M["rail"] & _hdilate(r0, int(R4C["along_m"] * ppm))) | \
                       (~M["rail"] & (_down(r0, int(R4C["down_m"] * ppm)) | _up(r0, int(R4C["up_m"] * ppm)) | _hdilate(r0, 1)))
                start = M["foot"] | M["joint"] | M.get("tcorner", np.zeros_like(M["joint"]))   # K13: a T as R3 counts it
                cont = new & (near | start)
                below0 = _up(r0, int(1.0 * ppm))                 # earlier rust somewhere below, within 1 m
                creep = new & M["upright"] & below0 & ~_up(r0, int(R4C["up_m"] * ppm)) & ~_down(r0, int(0.5 * ppm)) \
                    & ~M["joint"] & ~M["foot"]
                new_n += int(new.sum())
                cont_n += int(cont.sum())
                creep_n += int(creep.sum())
                seg0 += _segments(r0 & M["rail"], M["rail"]) * max(1, int((r0 & M["rail"]).sum()))
                seg1 += _segments(r1 & M["rail"], M["rail"]) * max(1, int((r1 & M["rail"]).sum()))
                rails_n += int((M["rail"] & st).sum())
                rails_r += int((M["rail"] & r0).sum())
                lab = p["labw"].astype(np.float64)
                Lo.append(lab[r0 & r1][:, 0])
                Ln.append(lab[new][:, 0])
            n0 = sum(int((prev[k][0] & prev[k][2]["rail"]).sum()) for k in prev)
            n1 = sum(int((cur[k][0] & cur[k][2]["rail"]).sum()) for k in cur)
            s0, s1 = seg0 / max(n0, 1), seg1 / max(n1, 1)
            share = cont_n / new_n if new_n else 1.0
            crp = creep_n / new_n if new_n else 0.0
            full = rails_r / rails_n if rails_n else 0.0
            ok4 = new_n == 0 or (share >= R4C["share"] and crp <= R4C["creep_max"]
                                 and (full >= R4C["rails_full"] or s0 == 0 or s1 >= R4C["seg_x"] * s0))
            lo = np.concatenate(Lo) if Lo else np.zeros(0)
            ln = np.concatenate(Ln) if Ln else np.zeros(0)
            dl = float(np.median(ln) - np.median(lo)) if lo.size >= R6C["min_px"] and ln.size >= R6C["min_px"] else None
            ok6 = dl is None or dl >= R6C["old_dL"]
            steps.append({"new_px": new_n, "continues": round(share, 3), "creeps_up": round(crp, 3),
                          "seg_px": [round(s0, 1), round(s1, 1)], "rails_rusted": round(full, 3),
                          "old_darker_L": None if dl is None else round(dl, 1)})
            if not ok4:
                bad4.append(len(steps) - 1)
            if not ok6:
                bad6.append(len(steps) - 1)
        prev = cur
    return [res("R4", not bad4, {"steps": steps, "bad_steps": bad4}), res("R6s", not bad6, {"bad_steps": bad6})]


RULES = [rule_R3, rule_R5, rule_R6]
