"""Round-G colour rule I3: weathering varies in colour like the reference walls. numpy only.

Measured as in _calib_colour.py: on painted wall, weathered pixels are D_local >= T3 on 4 cm
blocks; their shift is Lab against the clean albedo. Photo crops of ordinary danchi walls (five):
spread 1.2-3.9, non-neutral share (|dab| >= 1.5) 0.21-0.75, mark-to-mark spread 0.2-0.84
(three walls with three marks or more). Their clean wall has a noise spread of 0.65-0.99 and
non-neutral share of 0-0.13, so the build bands (no noise) are spread 0.9-4.0 and non-neutral
0.12-0.80. Round F's builds: spread 0.24-0.89, non-neutral 0.004-0.26,
marks 0.11-0.36."""
import numpy as np

import weather_measure as wm

I3 = {"E_min": 10.0, "spread": (0.9, 4.0), "non_neutral": (0.12, 0.80), "marks_min": 0.2, "min_px": 400}


def res(rid, ok, value, detail=""):
    return {"id": rid, "pass": (None if ok is None else bool(ok)), "value": value, "detail": detail}


def _blocks(a, f):
    H, W = a.shape[:2]
    h, w = H // f, W // f
    b = a[:h * f, :w * f].reshape((h, f, w, f) + a.shape[2:])
    return b.mean(axis=(1, 3))


def shift_stats(da, db, Dl, ppm_blk):
    """spread, non-neutral share and mark spread of weathered pixels' colour shift (bio and rust
    pixels left out by the caller, as in I1)."""
    w = np.nan_to_num(Dl) >= wm.TIER_EDGES[2]
    if w.sum() < I3["min_px"]:
        return None
    a, b = da[w], db[w]
    spread = float(np.sqrt(np.var(a) + np.var(b)))
    nn = float((np.hypot(a, b) >= 1.5).mean())
    lab, n = wm.label(w)
    means = []
    if n:
        cnt = np.bincount(lab.ravel(), minlength=n + 1)
        sa = np.bincount(lab.ravel(), weights=da.ravel(), minlength=n + 1)
        sb = np.bincount(lab.ravel(), weights=db.ravel(), minlength=n + 1)
        big = np.flatnonzero(cnt[1:] * (1.0 / ppm_blk) ** 2 >= 0.2) + 1     # 0.5 m eqd
        means = [(sa[i] / cnt[i], sb[i] / cnt[i]) for i in big]
    ms = None
    if len(means) >= 3:
        mm = np.array(means)
        ms = float(np.sqrt(mm[:, 0].var() + mm[:, 1].var()))
    return {"spread": round(spread, 2), "non_neutral": round(nn, 3), "marks": None if ms is None else round(ms, 2),
            "n_marks": len(means), "mean_shift": [round(float(a.mean()), 2), round(float(b.mean()), 2)]}


def rule_I3(cfg, planes, R):
    import weather_gate as wg
    E = float(cfg.get("E", 0.0) or 0.0)
    if E < I3["E_min"]:
        return res("I3", True, {"E": E}, "under E 10")
    out, ok, any_ = {}, True, False
    for p in planes.values():
        if not p.get("exposed", True) or "labw" not in p or "labc" not in p or p.get("cls") is None:
            continue
        img, lpp = wg.local_img(p)
        f_ = max(1, int(round(p["ppm"] / lpp)))
        m = np.isin(p["cls"], (1, 2))
        labw = _blocks(np.where(m[..., None], p["labw"], np.nan), f_)
        labc = _blocks(np.where(m[..., None], p["labc"], np.nan), f_)
        h, w = min(labw.shape[0], img.shape[0]), min(labw.shape[1], img.shape[1])
        d = np.nan_to_num((labw - labc)[:h, :w])
        Dl = np.array(img[:h, :w], np.float64)
        for ex in ("L_bio", "L_rust"):           # growth and rust have their own colour rules (M1, M2)
            if ex in p:
                e = _blocks(np.nan_to_num(np.asarray(p[ex], np.float64)), f_)[:h, :w]
                Dl = np.where(e >= wm.TIER_EDGES[0], np.nan, Dl)
        st = shift_stats(d[..., 1], d[..., 2], Dl, lpp)
        if st is None:
            continue
        any_ = True
        good = (I3["spread"][0] <= st["spread"] <= I3["spread"][1]
                and I3["non_neutral"][0] <= st["non_neutral"] <= I3["non_neutral"][1]
                and (st["marks"] is None or st["marks"] >= I3["marks_min"]))
        st["pass"] = bool(good)
        ok &= good
        out[p["name"]] = st
    if not any_:
        return res("I3", True, None, "little weathering at T3+")
    return res("I3", ok, out)
