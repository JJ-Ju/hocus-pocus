"""gate_rk.py - round-K rules (the user's round-J review; research member-rust-and-geometry-aware-wear.md and
rust-blue-sheen.md). At 50 px/m, from each plane's arrays:
  R10 rails rust along the drip line first, the face next, the top last, and grow with each step
  R11 dense dark scale carries the sheen mask (placement and amount), never blue in the albedo
  P4  flakes and breaks stay on their surface: no pattern runs on across a depth step
The close-up parts (R8c runs at the 1:1 view, N6 grooves) are wx_texcheck's. Imported by weather_gate."""
import numpy as np

import weather_measure as wm

PAINTED = (1, 2)
R10C = {"a": (0.25, 0.5, 0.75, 1.0), "lower": (0.35, 0.60, 0.75, 0.90), "middle": (0.0, 0.0, 0.10, 0.50),
        "upper_max": 0.10, "near_m": 0.10, "min_px": 200, "from": 0.2, "middle_from": 0.75}
R11C = {"a": (0.5, 0.55, 0.75, 1.0), "share": ((0.0, 0.001), (0.0, 0.04), (0.02, 0.08), (0.04, 0.15)), "dark_L": 32.0,
        "dark_share": 0.90, "wet_share": 0.60, "blue_max": 0.005, "min_px": 50}
P4C = {"step_m": 0.03, "peel_thr": 0.3, "dmg_thr": 0.5, "ratio_max": 2.0, "min_pairs": 30, "p_fail": 0.01}
# p_fail: a ratio over 2 fails when it is significant: the chance of that many coincidences at 2x the side's rate
# (Poisson) is under 1 % (round K test: Typical's breaks read 2.65x from 4 coincidences, 3.0 allowed at 2x: P 0.35;
# round J's layers read 64 where 7 were allowed: P ~ 0)


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _amount(cfg, k):
    ov = cfg.get("override") or {}
    return float(ov.get(k, (cfg.get("amounts") or {}).get(k, 0)) or 0)


def _band(a, keys, vals):
    if a <= keys[0]:
        return vals[0]
    if a >= keys[-1]:
        return vals[-1]
    i = int(np.searchsorted(keys, a)) - 1
    t = (a - keys[i]) / (keys[i + 1] - keys[i])
    if isinstance(vals[i], tuple):
        return tuple(vals[i][j] + t * (vals[i + 1][j] - vals[i][j]) for j in range(len(vals[i])))
    return vals[i] + t * (vals[i + 1] - vals[i])


def _steel(planes):
    import gate_r as gr
    for p in planes.values():
        if "steel" in p and "labw" in p and "labc" in p and "L_rust" in p and (np.asarray(p["steel"]) > 0).any():
            st, M, _ = gr._geo(p)
            yield p, st, M, gr._rusted(p, st)


def rule_R10(cfg, planes, R):
    """R10: on the top rails of railing panels (within 0.1 m of a T), from rust 0.2: the drip line (the rail's lower
    row) rusted >= 35 / 60 / 75 / 90 % at rust 0.25 / 0.5 / 0.75 / 1.0; the face (middle row) >= 10 % from 0.75 and >= 50 % at
    1.0; the top (upper row) <= 10 % up to 0.75 (the top advances with advanced wear)."""
    a = _amount(cfg, "rust")
    if a < R10C["from"] - 1e-6:
        return res("R10", True, {"rust": a}, "applies from rust 0.2")
    n = {"lower": [0, 0], "middle": [0, 0], "upper": [0, 0]}
    for p, st, M, rs in _steel(planes):
        if "tcorner" not in M:
            continue
        k_ = max(1, int(round(R10C["near_m"] * float(p.get("ppm", 50)))))
        tc = M["tcorner"].any(axis=0)
        near = tc.copy()
        for d_ in range(1, k_ + 1):
            near[d_:] |= tc[:-d_]
            near[:-d_] |= tc[d_:]
        lab, nl = wm.label(M["top"])
        if not nl:
            continue
        has = np.zeros(nl + 1, bool)
        has[np.unique(lab[M["tcorner"]])] = True
        has[0] = False
        panel = has[lab] & near[None, :] & st
        mid = M["top"] & ~M["upper"] & ~M["lower"]
        for k, m in (("lower", panel & M["lower"] & ~M["upper"]), ("middle", panel & mid), ("upper", panel & M["upper"])):
            n[k][0] += int((m & rs).sum())
            n[k][1] += int(m.sum())
    if n["lower"][1] < R10C["min_px"]:
        return res("R10", None, {"rust": a}, "no railing panels")
    sh = {k: v[0] / max(v[1], 1) for k, v in n.items()}
    need_low = _band(a, R10C["a"], R10C["lower"])
    need_mid = _band(a, R10C["a"], R10C["middle"]) if a >= R10C["middle_from"] - 1e-6 else 0.0   # K12: from 0.75
    ok = sh["lower"] >= need_low and sh["middle"] >= need_mid and (a > 0.75 + 1e-6 or sh["upper"] <= R10C["upper_max"])
    return res("R10", ok, {"rust": round(a, 3), "rusted": {k: round(v, 3) for k, v in sh.items()},
                           "need_lower": round(need_low, 3), "need_middle": round(need_mid, 3), "upper_max": R10C["upper_max"]})


def rule_R11(cfg, planes, R):
    """R11: the sheen mask (alpha >= 0.5) on rusted railing steel: none below rust 0.5, <= 4 % to 0.55, 2-8 % at 0.75,
    4-15 % at 1.0; >= 90 % of it in the dark class (L* <= 32), >= 60 % at feet, joints, the bottom rail and rail tops;
    and no rusted steel with b* < 0 in the albedo (<= 0.5 %): the sheen lives in F0 and roughness, never in colour."""
    a = _amount(cfg, "rust")
    tot = sh_n = dark_n = wet_n = blue = 0
    have = False
    for p, st, M, rs in _steel(planes):
        rs = rs & ~M["panel"]
        tot += int(rs.sum())
        lab = p["labw"]
        blue += int((rs & (lab[..., 2] < 0)).sum())
        if "sheen" not in p:
            continue
        have = True
        s = (np.nan_to_num(np.asarray(p["sheen"], np.float32)) >= 0.5) & rs
        sh_n += int(s.sum())
        dark_n += int((s & (lab[..., 0] <= R11C["dark_L"])).sum())
        wet = M["foot"] | M["joint"] | M["bottom"] | (M["rail"] & M["upper"])
        wet_n += int((s & wet).sum())
    if tot == 0:
        return res("R11", True, {"rust": a}, "no rusted steel")
    share = sh_n / tot
    b_ = _band(a, R11C["a"], R11C["share"]) if a >= R11C["a"][0] else (0.0, 0.001)
    blue_sh = blue / tot
    v = {"rust": round(a, 3), "sheen_share": round(share, 4), "band": [round(b_[0], 3), round(b_[1], 3)],
         "blue_rust_share": round(blue_sh, 4)}
    ok = blue_sh <= R11C["blue_max"] and (b_[0] <= share <= b_[1] or (not have and b_[0] == 0))
    if sh_n >= R11C["min_px"]:
        v["in_dark"] = round(dark_n / sh_n, 3)
        v["at_wet_parts"] = round(wet_n / sh_n, 3)
        ok = ok and v["in_dark"] >= R11C["dark_share"] and v["at_wet_parts"] >= R11C["wet_share"]
    return res("R11", ok, v)


def _pois_sf(k, lam):
    """P(X >= k) for X ~ Poisson(lam); a normal approximation from lam 50."""
    import math
    if k <= 0:
        return 1.0
    if lam > 50:
        return 0.5 * math.erfc((k - 0.5 - lam) / math.sqrt(2.0 * lam))
    term = math.exp(-lam)
    cdf = term
    for i in range(1, int(k)):
        term *= lam / i
        cdf += term
    return max(0.0, 1.0 - cdf)


def rule_P4(cfg, planes, R):
    """P4: flakes (the paint failure's alpha >= 0.3) and breaks (the damage alpha >= 0.5) stay on their surface: over
    the pixel pairs across a depth step of 3 cm or more on painted wall, a flaked (broken) pixel's neighbour across the
    step is flaked (broken) at most 2x as often as any pixel on that side of a step (independent patterns: about 1x;
    one pattern run across the step: 5x or more); a ratio over 2 fails when it is significant (Poisson, 1 %): few
    breaks at steps cannot tell 1x from 3x."""
    out = {}
    oks = []
    for key, thr in (("peel_a", P4C["peel_thr"]), ("dmg_a", P4C["dmg_thr"])):
        both = cond_n = cond_hit = base_n = base_hit = 0
        for p in planes.values():
            if key not in p or "dep" not in p:
                continue
            m = np.isin(p["cls"], PAINTED)
            dep = np.nan_to_num(np.asarray(p["dep"], np.float64), nan=1e3, posinf=1e3)
            f = np.nan_to_num(np.asarray(p[key], np.float32)) >= thr
            for ax in (0, 1):
                a_ = (slice(None, -1), slice(None)) if ax == 0 else (slice(None), slice(None, -1))
                b_ = (slice(1, None), slice(None)) if ax == 0 else (slice(None), slice(1, None))
                stp = m[a_] & m[b_] & (np.abs(dep[b_] - dep[a_]) >= P4C["step_m"])
                if not stp.any():
                    continue
                for s1, s2 in ((a_, b_), (b_, a_)):
                    fp, fq = f[s1][stp], f[s2][stp]
                    base_n += fq.size
                    base_hit += int(fq.sum())
                    cond_n += int(fp.sum())
                    cond_hit += int((fp & fq).sum())
                    both += int((fp & fq).sum())
        if cond_n < P4C["min_pairs"] or base_hit == 0:
            out[key] = {"pairs": cond_n, "na": True}
            continue
        ratio = (cond_hit / cond_n) / (base_hit / base_n)
        lam = P4C["ratio_max"] * cond_n * base_hit / base_n       # coincidences allowed on average at 2x
        pv = _pois_sf(cond_hit, lam)
        out[key] = {"pairs": cond_n, "p_cross": round(cond_hit / cond_n, 3), "p_side": round(base_hit / base_n, 4),
                    "ratio": round(ratio, 2), "hits": cond_hit, "allowed_mean": round(lam, 1), "p": round(pv, 4)}
        oks.append(ratio <= P4C["ratio_max"] or pv >= P4C["p_fail"])
    if not oks:
        return res("P4", True, out, "too few flakes or breaks at depth steps")
    return res("P4", all(oks), out)


RULES = [rule_R10, rule_R11, rule_P4]
