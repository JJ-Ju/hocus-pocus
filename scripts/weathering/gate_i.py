"""gate_i.py - round-I rules, from the round-H review: organic colour on one continuum in the growth
layer (I4, I5, I6), streaks in the vertical lines (H6), marks that grow in area with age (L5), and
rust that follows the water (R3, R4). Imported by weather_gate."""
import numpy as np

import weather_measure as wm

PAINTED = (1, 2)
WATER_LAYERS = ("L_streaks", "L_stains", "L_base")
STAGE = {"yellow": (60.0, 100.0), "green": (100.0, 180.0), "red": (15.0, 60.0)}   # hue sectors of the shift (deg)
I4C = {"E_min": 8.0, "E_red": 18.0, "share": 0.05, "bio_D": 0.02, "min_px": 2000}
I5C = {"back_max": 0.08, "dL": 1.0}
I6C = {"mark_D": 0.05, "green_max": 0.03}
H6C = {"a_min": 0.15, "band_m": 0.30, "share": 0.40}
L5C = {"streak_x": 1.15, "foot_dm": 0.05}
R3C = {"wet": 0.80, "early": 0.5, "enrich_early": 1.8, "enrich_late": 1.3, "dE": 8.0}
R4C = {"a_min": 0.5, "per_10m": 2.0, "dE": 6.0, "min_h": 0.08}


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _shift(p, sel):
    return (p["labw"][sel] - p["labc"][sel]).astype(np.float64)


def stage_index(d):
    """Continuum stage of an organic mark from its Lab shift: 0 yellow, 1 green, 2 red-muddy, -1 none.
    A lightness drop alone (black ink, soot) is not a stage."""
    h = np.degrees(np.arctan2(d[:, 2], d[:, 1])) % 360.0
    c = np.hypot(d[:, 1], d[:, 2])
    out = np.full(d.shape[0], -1, np.int8)
    ok = c >= 2.0
    y = ok & (h >= STAGE["yellow"][0]) & (h < STAGE["yellow"][1]) & (d[:, 2] >= 3.0)
    g = ok & (h >= STAGE["green"][0]) & (h <= STAGE["green"][1]) & (d[:, 1] <= -1.0)
    r = ok & (h >= STAGE["red"][0]) & (h < STAGE["red"][1]) & (d[:, 1] >= 1.5)
    out[y], out[g], out[r] = 0, 1, 2
    return out


def growth_px(p):
    if "labw" not in p or "labc" not in p or "L_bio" not in p:
        return None
    m = np.isin(p["cls"], PAINTED) & np.isfinite(p["D"]) & (np.nan_to_num(np.asarray(p["L_bio"], np.float32)) >= I4C["bio_D"])
    return m if m.sum() >= I4C["min_px"] else None


def rule_I4(cfg, planes, R):
    """I4 (round I): organic marks at different stages of the continuum sit side by side: of the
    growth pixels on paint, the yellow stage (hue 60-100 deg) and the green stage (100-180 deg) each
    hold 5 % or more from E 8, and the red-muddy stage (15-60 deg, a* +1.5 or more) too from E 18."""
    E = float(cfg.get("E", 0.0) or 0.0)
    if E < I4C["E_min"]:
        return res("I4", True, {"E": E}, "under E %g" % I4C["E_min"])
    cnt = np.zeros(4)
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        m = growth_px(p)
        if m is None:
            continue
        s = stage_index(_shift(p, m))
        cnt += np.bincount(s + 1, minlength=4)
    n = cnt.sum()
    if n < I4C["min_px"]:
        return res("I4", True, {"px": int(n)}, "little growth")
    sh = {"none": round(cnt[0] / n, 3), "yellow": round(cnt[1] / n, 3), "green": round(cnt[2] / n, 3), "red": round(cnt[3] / n, 3)}
    need = ["yellow", "green"] + (["red"] if E >= I4C["E_red"] else [])
    ok = all(sh[k] >= I4C["share"] for k in need)
    return res("I4", ok, sh, "needs %s at %.0f %% or more" % ("+".join(need), 100 * I4C["share"]))


def rule_I6(cfg, planes, R):
    """I6 (round I): water and dirt marks keep the dirt palette (the organic colour is the growth
    layer's): of the streak, stain and ground-band pixels at T2+ outside growth, 3 % or less are green."""
    n = ng = 0
    for p in planes.values():
        if not p.get("exposed", True) or "labw" not in p:
            continue
        m = np.isin(p["cls"], PAINTED) & np.isfinite(p["D"])
        mk = np.zeros_like(m)
        for k in WATER_LAYERS:
            if k in p:
                mk |= np.nan_to_num(np.asarray(p[k], np.float32)) >= I6C["mark_D"]
        for ex in ("L_bio", "L_rust"):
            if ex in p:
                mk &= ~(np.nan_to_num(np.asarray(p[ex], np.float32)) >= wm.TIER_EDGES[0])
        sel = m & mk
        if sel.sum() < 200:
            continue
        s = stage_index(_shift(p, sel))
        n += sel.sum()
        ng += int((s == 1).sum())
    if n < 1000:
        return res("I6", True, {"px": int(n)}, "few marks")
    return res("I6", ng / n <= I6C["green_max"], {"green": round(ng / n, 4)})


def stage_maps(planes):
    out = {}
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        m = growth_px(p)
        if m is None:
            continue
        st = np.full(m.shape, -2, np.int8)
        st[m] = stage_index(_shift(p, m))
        dl = np.full(m.shape, np.nan, np.float32)
        dl[m] = (p["labw"][m][:, 0] - p["labc"][m][:, 0])
        out[p["name"]] = (st, dl)
    return out


def series_stage(runs):
    """I5 (round I): a place's organic colour only moves forward along the continuum: between
    successive presets, of the pixels with growth in both, 8 % or fewer go back a stage (green to
    yellow, red-muddy to green or yellow); and the growth darkens: its mean L* shift falls by 1.0 or
    more from each preset at E 8 or more to the next."""
    seq = [(c, stage_maps(p)) for c, p in runs]
    st, bad = [], []
    for (ca, ma), (cb, mb) in zip(seq[:-1], seq[1:]):
        if float(cb.get("E", 0) or 0) < I4C["E_min"]:
            continue
        back = tot = 0
        dla, dlb = [], []
        for name in ma:
            if name not in mb:
                continue
            sa, la = ma[name]
            sb, lb = mb[name]
            both = (sa >= 0) & (sb >= 0)
            tot += int(both.sum())
            back += int((both & (sb < sa)).sum())
            dla.append(la[np.isfinite(la)])
            dlb.append(lb[np.isfinite(lb)])
        if tot < 500:
            continue
        mla = float(np.mean(np.concatenate(dla))) if dla else 0.0
        mlb = float(np.mean(np.concatenate(dlb))) if dlb else 0.0
        e = {"from": ca.get("preset"), "to": cb.get("preset"), "back": round(back / tot, 4), "px": tot,
             "dL": [round(mla, 2), round(mlb, 2)]}
        st.append(e)
        if back / tot > I5C["back_max"]:
            bad.append("%s -> %s: %.1f %% go back" % (e["from"], e["to"], 100 * back / tot))
        if float(ca.get("E", 0) or 0) >= I4C["E_min"] and not (mlb <= mla - I5C["dL"]):
            bad.append("%s -> %s: growth not darker (%.2f -> %.2f)" % (e["from"], e["to"], mla, mlb))
    if not st:
        return res("I5", True, {"steps": st}, "no two presets with growth")
    return res("I5", not bad, {"steps": st, "bad": bad})


def line_mask(p):
    """Columns within 0.3 m of a vertical line: a vertical joint, a bay division, a plane end."""
    H, W = p["cls"].shape
    ppm = p["ppm"]
    b = int(H6C["band_m"] * ppm)
    cols = np.zeros(W, bool)
    if "joint" in p:
        jv = (p["joint"] & 2) > 0
        for c in np.flatnonzero(jv.sum(axis=0) > 0.1 * H):
            cols[max(0, c - b):c + b + 1] = True
    for c in p.get("bay_cols") or []:
        cols[max(0, int(c) - b):int(c) + b + 1] = True
    wall = np.isin(p["cls"], PAINTED)
    xs = np.flatnonzero(wall.any(axis=0))
    if xs.size:
        cols[xs[0]:xs[0] + b] = True
        cols[max(0, xs[-1] - b):xs[-1] + 1] = True
    return cols


def rule_H6(cfg, planes, R):
    """H6 (round I): streaks gather in the vertical lines, the walls' natural channels: from streak
    amount 0.15, 40 % or more of the streak pixels at T2+ lie within 0.3 m of a vertical joint, a bay
    division or a wall's end."""
    a = float((cfg.get("amounts") or {}).get("streaks", 0) or 0)
    ov = (cfg.get("override") or {}).get("streaks")
    if ov is not None:
        a = float(ov)
    if a < H6C["a_min"]:
        return res("H6", True, {"amount": a}, "under %.2f" % H6C["a_min"])
    n = nl = 0
    for p in planes.values():
        if not p.get("exposed", True) or "L_streaks" not in p:
            continue
        m = np.isin(p["cls"], PAINTED) & (np.nan_to_num(np.asarray(p["L_streaks"], np.float32)) >= wm.TIER_EDGES[1])
        if m.sum() < 100:
            continue
        cols = line_mask(p)
        n += int(m.sum())
        nl += int(m[:, cols].sum())
    if n < 500:
        return res("H6", True, {"px": n}, "few streaks")
    return res("H6", nl / n >= H6C["share"], {"in_lines": round(nl / n, 3), "px": n})


def area_stats(planes):
    """Streak area at T2+ (m2) and the ground band's median height (m) over the exposed walls."""
    area, heights = 0.0, []
    for p in planes.values():
        if not p.get("exposed", True):
            continue
        ppm = p["ppm"]
        wall = np.isin(p["cls"], PAINTED)
        if "L_streaks" in p:
            area += float((wall & (np.nan_to_num(np.asarray(p["L_streaks"], np.float32)) >= wm.TIER_EDGES[1])).sum()) / ppm ** 2
        g = p.get("ground_row")
        if "L_base" in p and g is not None:
            b = np.nan_to_num(np.asarray(p["L_base"], np.float32)) >= wm.TIER_EDGES[0]
            hs = []
            for x in np.flatnonzero(wall[max(0, int(g) - 3 * int(ppm)):int(g)].any(axis=0))[::5]:
                col = b[:int(g), x]
                rows = np.flatnonzero(col)
                if rows.size:
                    hs.append((g - rows.min()) / ppm)
            if hs:
                heights.append(float(np.median(hs)))
    return area, (float(np.mean(heights)) if heights else 0.0)


def series_area(runs):
    """L5 (round I): marks grow in area with age, not only in strength: from Kept on, each preset's
    streak area at T2+ is 1.15 x the previous one's or more, and its ground band reaches 5 cm or
    more higher."""
    st, bad = [], []
    seq = [(c.get("preset"), area_stats(p)) for c, p in runs]
    for (pa, (aa, fa)), (pb, (ab, fb)) in zip(seq[:-1], seq[1:]):
        e = {"from": pa, "to": pb, "streak_m2": [round(aa, 1), round(ab, 1)], "foot_m": [round(fa, 3), round(fb, 3)]}
        st.append(e)
        if pa == "new":
            continue
        if not ab >= L5C["streak_x"] * aa:
            bad.append("%s -> %s: streak area x%.2f" % (pa, pb, ab / max(aa, 1e-6)))
        if not fb >= fa + L5C["foot_dm"]:
            bad.append("%s -> %s: ground band +%.3f m" % (pa, pb, fb - fa))
    return res("L5", not bad, {"steps": st, "bad": bad})


def steel_tow(p):
    import weather_fields as wf
    st = p["steel"] > 0
    tow, _ = wf.rail_wetness({"ppm": p["ppm"]}, st)
    return st, tow


def rule_R3(cfg, planes, R):
    """R3 (round I): rust starts where water sits: the rusted steel (colour difference 8 or more)
    over-represents the wet parts (bottom rails, the junctions under the top rail and over the
    bottom rail, the feet: time of wetness 0.8 or more) by 1.8 x or more up to rust 0.5, 1.3 x above."""
    a = float((cfg.get("override") or {}).get("rust", (cfg.get("amounts") or {}).get("rust", 0)) or 0)
    if a <= 0:
        return res("R3", True, {"amount": a}, "no rust")
    nw = nr = nrw = ns = 0
    for p in planes.values():
        if "steel" not in p or "labw" not in p or not (p["steel"] > 0).any():
            continue
        st, tow = steel_tow(p)
        d = np.sqrt(((p["labw"] - p["labc"]) ** 2).sum(axis=-1))
        rust = st & (d >= R3C["dE"])
        wet = st & (tow >= R3C["wet"])
        ns += int(st.sum())
        nw += int(wet.sum())
        nr += int(rust.sum())
        nrw += int((rust & wet).sum())
    if nr < 50 or ns == 0 or nw == 0:
        return res("R3", True, {"rusted_px": nr}, "little rust")
    enrich = (nrw / nr) / (nw / ns)
    need = R3C["enrich_early"] if a <= R3C["early"] else R3C["enrich_late"]
    return res("R3", enrich >= need, {"amount": round(a, 3), "enrich": round(enrich, 2), "need": need,
                                      "wet_share_of_steel": round(nw / ns, 3), "wet_share_of_rust": round(nrw / nr, 3)})


def rule_R4(cfg, planes, R):
    """R4 (round I): from rust 0.5, rust runs streak the concrete below the rusted feet and rails:
    two or more runs (8 cm or longer, colour difference 6 or more, warm) per 10 m of rail."""
    a = float((cfg.get("override") or {}).get("rust", (cfg.get("amounts") or {}).get("rust", 0)) or 0)
    if a < R4C["a_min"]:
        return res("R4", True, {"amount": a}, "under %.2f" % R4C["a_min"])
    runs, rail_m = 0, 0.0
    for p in planes.values():
        if "steel" not in p or "labw" not in p or not (p["steel"] > 0).any():
            continue
        ppm = p["ppm"]
        st = p["steel"] > 0
        _, horiz = __import__("weather_fields").rail_wetness({"ppm": ppm}, st)
        rail_m += float(horiz.sum()) / ppm / 3.0                # rails are about 3 px tall
        d = p["labw"] - p["labc"]
        dE = np.sqrt((d ** 2).sum(axis=-1))
        warm = (d[..., 2] > 2.0) & (d[..., 1] > 0.5)
        wall = np.isin(p["cls"], PAINTED)
        rr = wall & (dE >= R4C["dE"]) & warm & (np.nan_to_num(np.asarray(p.get("L_rust", np.zeros(st.shape)), np.float32)) > 0.01)
        below = np.zeros_like(st)
        for k in range(1, 3):
            below[k:] |= st[:-k]
        lab, n = wm.label(rr)
        if n:
            ys, xs = np.nonzero(lab)
            ll = lab[ys, xs]
            y0 = np.full(n + 1, 1 << 30)
            y1 = np.full(n + 1, -1)
            np.minimum.at(y0, ll, ys)
            np.maximum.at(y1, ll, ys)
            touch = np.zeros(n + 1, bool)
            np.logical_or.at(touch, ll, below[ys, xs])
            runs += int(((y1 - y0 + 1) / ppm >= R4C["min_h"])[1:][touch[1:]].sum())
    if rail_m < 5:
        return res("R4", True, {"rail_m": round(rail_m, 1)}, "little rail")
    per = runs / rail_m * 10.0
    return res("R4", per >= R4C["per_10m"], {"amount": round(a, 3), "runs": runs, "rail_m": round(rail_m, 1),
                                             "per_10m": round(per, 2)})


RULES = [rule_I4, rule_I6, rule_H6]     # R3, R4: moved to gate_r (research weathering-rust-water.md)
