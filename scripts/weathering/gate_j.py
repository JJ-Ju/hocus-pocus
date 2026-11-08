"""gate_j.py - round-J rules (research docs/redesign/research/coatings-concrete-corrosion.md §5 and
surface-detail-techniques.md §11). At 50 px/m, from each plane's arrays:
  P1  coatings fail in the standard amounts (ISO 4628-5 classes by preset) and kinds (type a, type b)
  P2  coatings fail where water stays (named zones against the open wall)
  R7  the coating breaks before the steel rusts: bare metal by preset, at the hand zone, joints and chips
  R8  rust runs down the uprights below rusted joints, by rust amount, with a collar above the bottom rail
  R9  dark old rust and bright new rust side by side
  F5  Derelict's top band and top corners carry the most
  G7  inside corners and recesses collect a little more
  J1b the clean coat's colour drifts (chroma) as well as its value
and from the concrete tiles (wx_concrete), the texture stage's material:
  J3  concrete has voids, aggregate shadows and chroma; the paint shows only dimples
The close-up parts (P3 flakes, R7 rims) are wx_texcheck's. Imported by weather_gate."""
import os

import numpy as np

import weather_measure as wm

PAINTED = (1, 2)
T2 = wm.TIER_EDGES[1]


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _preset(cfg):
    return str(cfg.get("preset") or "")


def _amount(cfg, k):
    ov = cfg.get("override") or {}
    return float(ov.get(k, (cfg.get("amounts") or {}).get(k, 0)) or 0)


def _col_scan_below(src, mask, reach_px):
    """Per pixel: rows since the last True of src above it in the same column (inside the mask), or a big number."""
    H, W = src.shape
    out = np.full((H, W), 1e9, np.float32)
    run = np.full(W, 1e9, np.float32)
    for y in range(H):
        run = np.where(src[y], 0.0, run + 1.0)
        run = np.where(mask[y] | src[y], run, 1e9)
        out[y] = run
    return out


def _row_dist(lines, wall, depth=None, jump=0.05):
    """Per pixel: horizontal distance (px) to the nearest True of `lines` in the same row, scanning only
    across wall pixels at one depth (a depth jump or a gap stops the scan)."""
    H, W = lines.shape
    big = np.float32(1e9)
    out = np.full((H, W), big, np.float32)
    for order in (range(W), range(W - 1, -1, -1)):
        run = np.full(H, big, np.float32)
        prev = None
        for x in order:
            ok = wall[:, x]
            if prev is not None and depth is not None:
                ok = ok & (np.abs(depth[:, x] - depth[:, prev]) <= jump)
            run = np.where(lines[:, x], 0.0, np.where(ok, run + 1.0, big))
            out[:, x] = np.minimum(out[:, x], run)
            prev = x
    return out


# ------------------------------------------------------------------------------------------------
# P1, P2: coatings

P1C = {"area": {"new": (0.0, 0.0002), "kept": (0.0, 0.0002), "typical": (0.0, 0.001), "worn": (0.003, 0.010),
                "derelict": (0.03, 0.15)},
       "typeb": {"worn": (0.0, 0.25), "derelict": (0.30, 0.60)}}
P2C = {"below_top_m": 0.30, "drip_m": 0.10, "crack_m": 0.15, "rails_m": 0.50, "foot_m": 0.50,
       "zones_min": 0.65, "open_max": {"worn": 0.20, "derelict": 0.35}}


def _wall(p):
    return np.isin(p["cls"], PAINTED)


def rule_P1(cfg, planes, R):
    """P1: the flaked share of the painted wall by preset (ISO 4628-5 classes 0.1/0.3/1/3/15 %): Kept 0,
    Typical <= 0.1 %, Worn 0.3-1 %, Derelict 3-15 %; and the share of flaked area that reaches the
    concrete (type b): <= 25 % up to Worn, 30-60 % at Derelict."""
    pr = _preset(cfg)
    a_sum = w_sum = b_sum = 0.0
    any_peel = False
    for p in planes.values():
        wall = _wall(p)
        w_sum += float(wall.sum())
        if "peel_a" in p:
            any_peel = True
            a = np.nan_to_num(p["peel_a"].astype(np.float64)) * wall
            a_sum += float(a.sum())
            if "peel_b" in p:
                b_sum += float((a * np.nan_to_num(p["peel_b"].astype(np.float64))).sum())
    share = a_sum / max(w_sum, 1.0)
    tb = b_sum / a_sum if a_sum > 0 else None
    band = P1C["area"].get(pr)
    if band is None:                                  # a sweep entry: the preset it was built on
        return res("P1", None, {"share": round(share, 5)}, "no preset band for %r" % pr)
    ok = band[0] <= share <= band[1]
    tbb = P1C["typeb"].get(pr)
    if tbb is not None and tb is not None and share >= 0.001:
        ok = ok and tbb[0] <= tb <= tbb[1]
    v = {"preset": pr, "flaked_share": round(share, 5), "band": band, "type_b": None if tb is None else round(tb, 3),
         "type_b_band": tbb, "layer": any_peel}
    return res("P1", ok, v)


def _zones(p):
    """Named zones where water stays (P2): below tops (sills, upstands, parapets), along drip lines and
    slab noses, by cracks and joints, below the rails, and the splash zone at the foot."""
    wall = _wall(p)
    ppm = float(p.get("ppm", 50))
    H, W = wall.shape
    z = {}
    et = p.get("etop")
    tops = (et & 1) > 0 if et is not None else np.zeros((H, W), bool)
    bots = (et & 2) > 0 if et is not None else np.zeros((H, W), bool)
    z["below_top"] = (_col_scan_below(tops, wall, 0) <= P2C["below_top_m"] * ppm) & wall
    bb = wm.gauss(bots.astype(np.float32), 0.5) > 0.02
    z["drip"] = (wm.gauss(bots.astype(np.float32), P2C["drip_m"] * ppm / 2.0) > 0.05) & wall | (bb & wall)
    cr = np.zeros((H, W), bool)
    if "crk_w" in p:
        cr |= np.nan_to_num(p["crk_w"].astype(np.float32)) > 0
    if "joint" in p:
        cr |= p["joint"] > 0
    z["crack"] = (wm.gauss(cr.astype(np.float32), P2C["crack_m"] * ppm / 2.0) > 0.03) & wall
    st = (p["steel"] > 0) if "steel" in p else np.zeros((H, W), bool)
    z["rails"] = (_col_scan_below(st, wall, 0) <= P2C["rails_m"] * ppm) & wall
    g = p.get("ground_row")
    if g is not None:
        rows = np.arange(H)[:, None]
        low = np.where(wall & (rows > g - 3 * ppm), rows, -1).max(axis=0)
        foot = np.where(low > 0, low, g)[None, :]
        z["foot"] = wall & ((foot - rows) >= 0) & ((foot - rows) <= P2C["foot_m"] * ppm)
    return z


def rule_P2(cfg, planes, R):
    """P2 (from Worn): >= 65 % of the flaking in the zones where water stays; the open wall holds <= 20 %
    of it at Worn and <= 35 % at Derelict. Soffits (2x the open wall in the research) are not in our
    planes' paint mask."""
    pr = _preset(cfg)
    if pr not in P2C["open_max"]:
        return res("P2", True, None, "applies from Worn")
    tot = inz = 0.0
    by = {}
    for p in planes.values():
        if "peel_a" not in p:
            continue
        wall = _wall(p)
        a = np.nan_to_num(p["peel_a"].astype(np.float64)) * wall
        zs = _zones(p)
        u = np.zeros(wall.shape, bool)
        for k, m in zs.items():
            u |= m
            by[k] = by.get(k, 0.0) + float(a[m].sum())
        tot += float(a.sum())
        inz += float(a[u].sum())
    if tot <= 0:
        return res("P2", None, None, "no flaking")
    sh = inz / tot
    ok = sh >= P2C["zones_min"] and (1.0 - sh) <= P2C["open_max"][pr]
    return res("P2", ok, {"in_zones": round(sh, 3), "open_wall": round(1 - sh, 3),
                          "by_zone": {k: round(v / tot, 3) for k, v in by.items()}})


# ------------------------------------------------------------------------------------------------
# R7, R8, R9: rust

R7C = {"bare": {"typical": (0.0005, 0.005), "worn": (0.003, 0.02), "derelict": (0.003, 0.02)}, "where": 0.60}
R8C = {"a": (0.5, 0.75, 1.0), "below": (0.50, 0.70, 0.85), "median": ((0.05, 0.15), (0.15, 0.40), (0.30, 0.90)),
       "stained": ((0.03, 0.10), (0.10, 0.25), (0.25, 0.60)), "min_m": 0.05, "head": 1.3, "collar": 0.50,
       "alpha": 0.06}
R9C = {"dark_L": 32.0, "bright": (46.0, 30.0), "dark": (0.15, 0.40), "bright_share": (0.08, 0.25), "where": 0.60,
       "spread": 14.0}


def _steel_planes(planes):
    for p in planes.values():
        if "steel" in p and (np.asarray(p["steel"]) > 0).any():
            yield p


def _geo(p):
    import gate_r as gr
    return gr._geo(p)


def _rusted(p, st):
    import gate_r as gr
    if "L_rust" not in p or "labw" not in p:
        return np.zeros(st.shape, bool)
    return gr._rusted(p, st)


def rule_R7(cfg, planes, R):
    """R7 (50 px/m part): bare metal (the bare-steel layer) as a share of the railing steel by preset
    (Typical 0.05-0.5 %, Worn and Derelict 0.3-2 %), >= 60 % of it at the hand zone (the top rail), the
    joints or next to rust. The rims round rust patches are measured at 1 mm/px (wx_texcheck)."""
    pr = _preset(cfg)
    band = R7C["bare"].get(pr)
    tot = st_n = at = 0.0
    for p in _steel_planes(planes):
        st, M, _ = _geo(p)
        st_n += float(st.sum())
        if "bare_a" not in p:
            continue
        b = np.nan_to_num(p["bare_a"].astype(np.float64)) * st
        rs = _rusted(p, st)
        nr = wm.gauss(rs.astype(np.float32), 1.0) > 0.05
        where = (M["top"] | M["joint"] | nr) & st
        tot += float(b.sum())
        at += float(b[where].sum())
    share = tot / max(st_n, 1.0)
    w = at / tot if tot > 0 else None
    if band is None:
        return res("R7", None if st_n == 0 else True, {"bare_share": round(share, 5)}, "no preset band for %r" % pr)
    swept = "rust" in (cfg.get("override") or {})       # J25: a rust sweep entry: the control sets the amount
    ok = (swept or band[0] <= share <= band[1]) and (w is None or w >= R7C["where"])
    return res("R7", ok, {"preset": pr, "bare_share": round(share, 5), "band": band,
                          "at_hand_joints_rust": None if w is None else round(w, 3)})


def _bands_at(a, keys, vals):
    if a <= keys[0]:
        return vals[0]
    if a >= keys[-1]:
        return vals[-1]
    i = int(np.searchsorted(keys, a)) - 1
    t = (a - keys[i]) / (keys[i + 1] - keys[i])
    lo = vals[i][0] + t * (vals[i + 1][0] - vals[i][0]) if isinstance(vals[i], tuple) else vals[i] + t * (vals[i + 1] - vals[i])
    if isinstance(vals[i], tuple):
        hi = vals[i][1] + t * (vals[i + 1][1] - vals[i][1])
        return (lo, hi)
    return lo


def rule_R8(cfg, planes, R):
    """R8 (from rust 0.5): runs >= 5 cm below 50 / 70 / 85 % of rusted joints (rust 0.5 / 0.75 / 1.0);
    median run 0.05-0.15 / 0.15-0.4 / 0.3-0.9 m; stained share of upright length 3-10 / 10-25 / 25-60 %;
    the head darker than the tail (dE x 1.3); a collar above the bottom rail on >= 50 % of uprights
    with a run."""
    a = _amount(cfg, "rust")
    if a < 0.5 - 1e-6:
        return res("R8", True, {"rust": a}, "applies from rust 0.5")
    runs, below, n_j, up_px, st_px, heads, tails, coll, n_up = [], 0, 0, 0, 0, [], [], 0, 0
    for p in _steel_planes(planes):
        if "run_a" not in p:
            continue
        st, M, _ = _geo(p)
        ppm = float(p.get("ppm", 50))
        ra = np.nan_to_num(p["run_a"].astype(np.float32))
        rs = _rusted(p, st)
        up = M["upright"] & ~M["joint"] & ~M["foot"] & st
        on = (ra >= R8C["alpha"]) & up
        up_px += int(up.sum())
        st_px += int(on.sum())
        dE = np.sqrt(((p["labw"].astype(np.float64) - p["labc"].astype(np.float64)) ** 2).sum(-1)) if "labw" in p else None
        H, W = st.shape
        topr = M["top"] & st                                 # joints hanging below a top rail (1-3 px above)
        above_top = np.zeros(st.shape, bool)
        for k in range(1, 4):
            above_top[k:] |= topr[:-k]
        jr = M["joint"] & rs & above_top
        cols = np.flatnonzero(jr.any(axis=0))
        for x in cols:
            ys = np.flatnonzero(jr[:, x])
            for y0 in ys[np.r_[True, np.diff(ys) > 1]]:      # the top of each rusted joint run in this column
                yb = y0
                while yb + 1 < H and jr[yb + 1, x]:
                    yb += 1
                y = yb + 1                                   # J28: the run starts below the whole joint
                while y < H and M["joint"][y, x]:
                    y += 1
                upm = M["upright"][:, x] & ~M["joint"][:, x] & ~M["foot"][:, x]   # the member, mask holes included
                seg = 0
                while y + seg < H and upm[y + seg]:
                    seg += 1
                if seg < R8C["min_m"] * ppm:
                    continue                                 # nothing, or a stub under 5 cm, hangs below this joint
                n_j += 1
                L = 0
                while L < seg:
                    if on[y + L, x]:
                        L += 1
                        continue
                    h = 0                                    # J28: over a 1-2 px hole in the steel mask
                    while L + h < seg and h < 3 and not st[y + L + h, x]:
                        h += 1
                    if 0 < h <= 2 and L + h < seg and on[y + L + h, x]:
                        L += h
                        continue
                    break
                runs.append(L / ppm)
                if L / ppm >= R8C["min_m"]:
                    below += 1
                    if dE is not None and L >= 4:
                        q = max(1, L // 4)
                        heads.append(float(dE[y:y + q, x].mean()))
                        tails.append(float(dE[y + L - q:y + L, x].mean()))
        bot = M["bottom"] & st
        onj = (ra >= R8C["alpha"]) & (M["upright"] | M["joint"]) & st     # the collar may sit on the joint
        for x in np.flatnonzero((on & up).any(axis=0)):
            yb_ = np.flatnonzero(bot[:, x])
            if yb_.size == 0:
                continue
            n_up += 1
            yb0 = int(yb_[0])
            seg = onj[max(0, yb0 - max(2, int(round(0.05 * ppm)))):yb0, x]
            if seg.size and seg.any():
                coll += 1
    if n_j == 0:
        return res("R8", None, {"rust": a}, "no rusted joints")
    share_below = below / n_j
    med = float(np.median(runs)) if runs else 0.0
    stained = st_px / max(up_px, 1)
    hd = (float(np.median(heads)) / max(float(np.median(tails)), 1e-6)) if heads else None
    cs = coll / n_up if n_up else None
    keys = R8C["a"]
    b_below = _bands_at(a, keys, R8C["below"])
    b_med = _bands_at(a, keys, R8C["median"])
    b_st = _bands_at(a, keys, R8C["stained"])
    ok = (share_below >= b_below and b_med[0] <= med <= b_med[1] and b_st[0] <= stained <= b_st[1]
          and (hd is None or hd >= R8C["head"]) and (cs is None or cs >= R8C["collar"]))
    return res("R8", ok, {"rust": a, "joints": n_j, "runs_below_share": round(share_below, 3), "band_below": round(b_below, 2),
                          "median_m": round(med, 3), "band_median": [round(b_med[0], 3), round(b_med[1], 3)],
                          "stained": round(stained, 4), "band_stained": [round(b_st[0], 3), round(b_st[1], 3)],
                          "head_over_tail": None if hd is None else round(hd, 2), "collar": None if cs is None else round(cs, 3)})


def rule_R9(cfg, planes, R):
    """R9 (from rust 0.5): dark rust (L* <= 32) 15-40 % of the rust, >= 60 % of it at feet, joints, the
    bottom rail and rail tops; bright rust (L* >= 46, C* >= 30) 8-25 %, >= 60 % of it within 2 cm of a
    rust front; L* p90 - p10 >= 14."""
    a = _amount(cfg, "rust")
    if a < 0.5 - 1e-6:
        return res("R9", True, {"rust": a}, "applies from rust 0.5")
    Ls, Cs, dk_w, br_w = [], [], [], []
    for p in _steel_planes(planes):
        st, M, _ = _geo(p)
        rs = _rusted(p, st)
        if not rs.any():
            continue
        lab = p["labw"].astype(np.float64)
        L, C = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
        wet_parts = (M["foot"] | M["joint"] | M["bottom"] | (M["rail"] & M["upper"])) & st
        er = rs & ~(np.roll(rs, 1, 0) & np.roll(rs, -1, 0) & np.roll(rs, 1, 1) & np.roll(rs, -1, 1))   # the front (edge)
        front = wm.gauss(er.astype(np.float32), 0.5) > 0.05
        dk = rs & (L <= R9C["dark_L"])
        br = rs & (L >= R9C["bright"][0]) & (C >= R9C["bright"][1])
        Ls.append(L[rs])
        Cs.append(C[rs])
        dk_w.append((int(dk.sum()), int((dk & wet_parts).sum())))
        br_w.append((int(br.sum()), int((br & front).sum())))
    if not Ls:
        return res("R9", None, {"rust": a}, "no rust")
    L = np.concatenate(Ls)
    n = L.size
    nd, ndw = sum(x[0] for x in dk_w), sum(x[1] for x in dk_w)
    nb, nbf = sum(x[0] for x in br_w), sum(x[1] for x in br_w)
    dsh, bsh = nd / n, nb / n
    spread = float(np.percentile(L, 90) - np.percentile(L, 10))
    ok = (R9C["dark"][0] <= dsh <= R9C["dark"][1] and R9C["bright_share"][0] <= bsh <= R9C["bright_share"][1]
          and (nd == 0 or ndw / nd >= R9C["where"]) and (nb == 0 or nbf / nb >= R9C["where"]) and spread >= R9C["spread"])
    return res("R9", ok, {"rust": a, "dark": round(dsh, 3), "dark_at_wet_parts": round(ndw / max(nd, 1), 3),
                          "bright": round(bsh, 3), "bright_at_fronts": round(nbf / max(nb, 1), 3),
                          "L_spread": round(spread, 1)})


# ------------------------------------------------------------------------------------------------
# F5, G7: top band, top corners, inside corners, recesses

F5C = {"E": 18.0, "band": (0.05, 0.60), "band_x": 1.4, "corner_m": 1.5, "corner_x": (1.6, 3.0), "growth_x": 2.0,
       "edge_m": 0.05, "edge_fail": {"derelict": (0.15, 0.50), "typical": (0.0, 0.05)}}
G7C = {"E": 10.0, "strip": (0.10, 0.40), "far": (0.60, 1.50), "ring": (0.55, 0.70), "corner_x": (1.15, 1.6),
       "corner_x_der": (1.25, 2.0), "ring_max": 1.10, "recess_m": 0.30, "recess_x": (1.1, 1.5), "growth_E": 14.0,
       "growth_x": 2.0, "bottom_m": 1.0, "min_m2": 1.0}


def _tops_and_ends(p, wall):
    """Per column: the wall top (topmost painted row within 1 m of the plane's top row); the plane's ends."""
    ppm = float(p.get("ppm", 50))
    H, W = wall.shape
    tr = int(p.get("top_row") or 0)
    rows = np.arange(H)[:, None]
    near_top = wall & (rows <= tr + int(1.0 * ppm))
    first = np.where(near_top.any(axis=0), np.argmax(near_top, axis=0), -1)
    cols = np.flatnonzero(first >= 0)
    return first, (int(cols.min()), int(cols.max())) if cols.size else (None, None)


def rule_F5(cfg, planes, R):
    """F5 (from E 18): in the band 0.05-0.6 m under the wall top, mean D over the wall mean >= 1.4; in the
    top corners (within 1.5 m of a wall end and of the top) 1.6-3; growth T2+ cover there >= 2x the open
    wall; the coat peeled along 15-50 % of the top edge (within 5 cm of the arris) at Derelict, <= 5 % at
    Typical. Arris rows are left out (N5)."""
    E = float(cfg.get("E", 0))
    pr = _preset(cfg)
    vals = {}
    oks = []
    for p in planes.values():
        if "D" not in p or not p.get("exposed", True):
            continue
        wall = _wall(p) & np.isfinite(p["D"])
        ppm = float(p.get("ppm", 50))
        H, W = wall.shape
        edge = (p["edge"] > 0) if "edge" in p else np.zeros((H, W), bool)
        first, (x0, x1) = _tops_and_ends(p, wall)
        if x0 is None:
            continue
        rows = np.arange(H)[:, None]
        dtop = np.where(first[None, :] >= 0, (rows - first[None, :]) / ppm, -1.0)
        band = wall & ~edge & (dtop >= F5C["band"][0]) & (dtop <= F5C["band"][1])
        xx = np.arange(W)[None, :]
        dend = np.minimum(xx - x0, x1 - xx) / ppm
        corner = wall & ~edge & (dtop >= 0) & (dtop <= F5C["corner_m"]) & (dend <= F5C["corner_m"])
        D = np.nan_to_num(p["D"].astype(np.float64))
        wm_ = float(D[wall & ~edge].mean())
        r_band = float(D[band].mean()) / max(wm_, 1e-6) if band.any() else None
        r_corner = float(D[corner].mean()) / max(wm_, 1e-6) if corner.any() else None
        g = None
        if "L_bio" in p:
            Lb = np.nan_to_num(p["L_bio"].astype(np.float64))
            openw = wall & ~edge & ~corner & ~band
            gc_, go_ = float((Lb[corner] >= T2).mean()) if corner.any() else 0.0, float((Lb[openw] >= T2).mean()) if openw.any() else 0.0
            g = gc_ / go_ if go_ > 0 else (None if gc_ == 0 else 99.0)
        te = None
        if "peel_a" in p:
            topline = wall & (dtop >= 0) & (dtop <= F5C["edge_m"])
            cols = np.flatnonzero(topline.any(axis=0))
            if cols.size:
                pa = np.nan_to_num(p["peel_a"].astype(np.float32))
                te = float(((pa * topline).max(axis=0)[cols] > 0.3).mean())
        vals[p["name"]] = {"band": None if r_band is None else round(r_band, 3), "corners": None if r_corner is None else round(r_corner, 3),
                           "corner_growth_x": None if g is None else round(g, 2), "top_edge_peeled": None if te is None else round(te, 3)}
        if E >= F5C["E"]:
            oks.append(r_band is not None and r_band >= F5C["band_x"])
            oks.append(r_corner is not None and F5C["corner_x"][0] <= r_corner <= F5C["corner_x"][1])
            oks.append(g is not None and g >= F5C["growth_x"])
        eb = F5C["edge_fail"].get(pr)
        if eb is not None and te is not None and (E >= F5C["E"] or pr == "typical"):
            oks.append(eb[0] <= te <= eb[1])
    if not vals:
        return res("F5", None, None, "no exposed walls")
    if not oks:
        return res("F5", True, vals, "applies from E 18 (Typical: the top-edge clause)")
    return res("F5", all(oks), vals)


def _inside_corners(p, wall):
    dep = p.get("dep")
    if dep is None:
        return None, None
    d = dep.astype(np.float64)
    H, W = d.shape
    left = np.full((H, W), np.inf)
    right = np.full((H, W), np.inf)
    left[:, 1:] = np.where(wall[:, :-1], d[:, :-1], np.inf)
    right[:, :-1] = np.where(wall[:, 1:], d[:, 1:], np.inf)
    ic = wall & ((left < d - 0.05) | (right < d - 0.05))
    below = np.full((H, W), np.inf)
    below[:-1] = d[1:]
    rb = wall & (below < d - 0.05)                       # a recess's bottom: the nearer slab below
    return ic, rb


def rule_G7(cfg, planes, R):
    """G7 (from E 10): mean D in 0.1-0.4 m strips beside inside-corner lines over the same rows' wall
    0.6-1.5 m away: 1.15-1.6 (1.25-2.0 at Derelict), and no outline (<= 1.1 at 0.55-0.7 m); recess faces
    (>= 0.3 m behind the local front) over the open wall: 1.1-1.5 when both exist; from E 14, growth T2+
    cover in the bottom 1 m of the corner strips and at recess bottoms >= 2x the open wall."""
    E = float(cfg.get("E", 0))
    if E < G7C["E"]:
        return res("G7", True, {"E": E}, "applies from E 10")
    der = _preset(cfg) == "derelict"
    vals, oks = {}, []
    for p in planes.values():
        if "D" not in p or "dep" not in p:
            continue
        wall = _wall(p) & np.isfinite(p["D"])
        ppm = float(p.get("ppm", 50))
        ic, rb = _inside_corners(p, wall)
        if ic is None or ic.sum() < 0.5 * ppm:
            continue
        dep = p["dep"].astype(np.float64)
        dist = _row_dist(ic, wall, dep) / ppm
        D = np.nan_to_num(p["D"].astype(np.float64))
        strip = wall & (dist >= G7C["strip"][0]) & (dist <= G7C["strip"][1])
        far = wall & (dist >= G7C["far"][0]) & (dist <= G7C["far"][1])
        ring = wall & (dist >= G7C["ring"][0]) & (dist <= G7C["ring"][1])
        rows = strip.any(axis=1) & far.any(axis=1)
        s_ = strip & rows[:, None]
        f_ = far & rows[:, None]
        g_ = ring & rows[:, None]
        if s_.sum() < G7C["min_m2"] * ppm * ppm or f_.sum() < G7C["min_m2"] * ppm * ppm:   # J13: 1 m2 each
            continue
        rc = float(D[s_].mean()) / max(float(D[f_].mean()), 1e-6)
        rr = float(D[g_].mean()) / max(float(D[f_].mean()), 1e-6) if g_.any() else None
        # recess faces against the local front (the nearest wall within about 1.5-2.5 m in the row)
        Wd = dep.shape[1]
        k = int(1.5 * ppm)
        dm = np.where(wall, dep, np.inf)
        front = dm.copy()
        s = 1
        while s <= k:                                      # sliding minimum by doubling
            front = np.minimum(front, np.minimum(np.roll(front, s, 1), np.roll(front, -s, 1)))
            s *= 2
        rec = wall & (dep - front >= G7C["recess_m"])
        opn = wall & (dep - front < 0.05)
        rx = None
        if rec.sum() > 0.05 * opn.sum() and opn.sum() > 0.05 * rec.sum() and rec.sum() > 200 and opn.sum() > 200:
            rx = float(D[rec].mean()) / max(float(D[opn].mean()), 1e-6)
        gx = None
        if E >= G7C["growth_E"] and "L_bio" in p:
            Lb = np.nan_to_num(p["L_bio"].astype(np.float64))
            H = wall.shape[0]
            fl = [int(r) for r in (p.get("floor_rows") or [])] + [int(p.get("ground_row") or H - 1)]
            nearfl = np.zeros(wall.shape, bool)
            rows_ = np.arange(H)
            for r in fl:
                nearfl |= ((r - rows_) >= 0)[:, None] & ((r - rows_) <= G7C["bottom_m"] * ppm)[:, None]
            cb = (strip | (wall & (dist < G7C["strip"][0]))) & nearfl
            nf3 = np.zeros(wall.shape, bool)                 # J20: the bottom 0.3 m of recess faces above a floor line
            for r in fl:
                nf3 |= ((r - rows_) >= 0)[:, None] & ((r - rows_) <= 0.3 * ppm)[:, None]
            rbz = rec & nf3
            zone = cb | rbz
            openw = wall & ~zone & (dist > G7C["far"][0])
            gz = float((Lb[zone] >= T2).mean()) if zone.any() else 0.0
            go = float((Lb[openw] >= T2).mean()) if openw.any() else 0.0
            gx = gz / go if go > 0 else (None if gz == 0 else 99.0)
        vals[p["name"]] = {"corner_x": round(rc, 3), "ring_x": None if rr is None else round(rr, 3),
                           "recess_x": None if rx is None else round(rx, 3), "bottom_growth_x": None if gx is None else round(gx, 2)}
        lo, hi = G7C["corner_x_der"] if der else G7C["corner_x"]
        oks.append(lo <= rc <= hi)
        if rr is not None:
            oks.append(rr <= G7C["ring_max"])
        if rx is not None:
            oks.append(G7C["recess_x"][0] <= rx <= G7C["recess_x"][1])
        if gx is not None:
            oks.append(gx >= G7C["growth_x"])
    if not vals:
        return res("G7", None, None, "no inside corners measured")
    return res("G7", all(oks), vals)


# ------------------------------------------------------------------------------------------------
# J1b: the coat's colour; J3: the concrete tiles

J1BC = {"band": (0.10, 2.0), "std": (0.3, 1.2)}


def rule_J1b(cfg, planes, R):
    """J1b: the clean coat's chroma varies: std of C* band-passed at 10 cm-2 m on the painted walls'
    clean albedo in [0.3, 1.2] on every plane."""
    vals, oks = {}, []
    for p in planes.values():
        if "labc" not in p:
            continue
        wall = _wall(p)
        if wall.sum() < 1000:
            continue
        ppm = float(p.get("ppm", 50))
        lab = p["labc"].astype(np.float64)
        C = np.hypot(lab[..., 1], lab[..., 2])
        Cf = np.where(wall, C, float(C[wall].mean())).astype(np.float32)
        b = wm.gauss(Cf, J1BC["band"][0] / 3.0 * ppm) - wm.gauss(Cf, J1BC["band"][1] / 3.0 * ppm)
        sd = float(b[wall].std())
        vals[p["name"]] = round(sd, 3)
        oks.append(J1BC["std"][0] <= sd <= J1BC["std"][1])
    if not vals:
        return res("J1b", None, None, "no clean colour")
    return res("J1b", all(oks), {"C_std_10cm_2m": vals})


J3C = {"void_share": (0.003, 0.02), "n5": (30, 150), "n10": (5, 40), "largest_mm": 25.0, "spots": (0.02, 0.08),
       "C_median_max": 4.0, "C_spread_min": 1.5, "paint_small_max": 0.0, "paint_dimples": (2.0, 60.0)}


def rule_J3(cfg, planes, R):
    """J3 (the texture stage's concrete, wx_concrete tiles at 1 mm/px): voids 0.3-2 % of the cast face, 30-150
    per m2 from 5 mm and 5-40 from 10 mm, the largest <= 25 mm; aggregate shadows 2-8 % cover; clean
    concrete C* median <= 4 with a p10-p90 spread >= 1.5; through the spray coat no open voids under
    2 mm and 2-60 dimples per m2 from 5 mm (2-20 % of the bare count from 3 mm)."""
    try:
        import wx_concrete as wc
        cache = os.environ.get("WX_DETAIL_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_detail_cache"))
        A = wc.TILE_M ** 2
        st = wc.stack("formed", cache)
        v = st[..., 4] > 0.3
        lab_, n = wm.label(v)
        d = 2 * np.sqrt(np.bincount(lab_.ravel())[1:] / np.pi) if n else np.zeros(0)
        vs = float(v.mean())
        n5, n10 = float((d >= 5).sum()) / A, float((d >= 10).sum()) / A
        big = float(d.max()) if d.size else 0.0
        conc = np.array([0.31, 0.30, 0.28])
        lab = wm.linear_to_lab((st[..., :3] * conc).astype(np.float64))
        C = np.hypot(lab[..., 1], lab[..., 2])
        Lc = lab[..., 0].astype(np.float32)
        bp = wm.gauss(Lc, 1.5) - wm.gauss(Lc, 10.0)                # blobs of about 5-25 mm
        sp = (bp <= -1.0) & ~v
        slab, sn = wm.label(sp)
        if sn:
            area = np.bincount(slab.ravel())[1:]
            dd = 2 * np.sqrt(area / np.pi)
            keep = np.r_[False, (dd >= 5) & (dd <= 25)]
            spots = float(keep[slab].mean())
        else:
            spots = 0.0
        pt = wc.stack("pits", cache)
        pv = pt[..., 4] > 0.3
        plab, pn = wm.label(pv)
        pd_ = 2 * np.sqrt(np.bincount(plab.ravel())[1:] / np.pi) if pn else np.zeros(0)
        small = float((pd_ < 2).sum()) / A
        dim5 = float((pd_ >= 5).sum()) / A
    except Exception as e:
        return res("J3", False, None, "error: %r" % (e,))
    ok = (J3C["void_share"][0] <= vs <= J3C["void_share"][1] and J3C["n5"][0] <= n5 <= J3C["n5"][1]
          and J3C["n10"][0] <= n10 <= J3C["n10"][1] and big <= J3C["largest_mm"]
          and J3C["spots"][0] <= spots <= J3C["spots"][1]
          and float(np.median(C)) <= J3C["C_median_max"] and float(np.percentile(C, 90) - np.percentile(C, 10)) >= J3C["C_spread_min"]
          and small <= J3C["paint_small_max"] and J3C["paint_dimples"][0] <= dim5 <= J3C["paint_dimples"][1])
    return res("J3", ok, {"void_share": round(vs, 4), "n5_m2": round(n5, 1), "n10_m2": round(n10, 1), "largest_mm": round(big, 1),
                          "shadow_spots": round(spots, 4), "C_median": round(float(np.median(C)), 2),
                          "C_spread": round(float(np.percentile(C, 90) - np.percentile(C, 10)), 2),
                          "paint_small_m2": round(small, 1), "paint_dimples5_m2": round(dim5, 1)})


RULES = [rule_P1, rule_P2, rule_R7, rule_R8, rule_R9, rule_F5, rule_G7, rule_J1b, rule_J3]
