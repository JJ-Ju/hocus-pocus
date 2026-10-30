"""weather_fields.py - rule-driven weathering fields for building facades (numpy only).

Each plane is an elevation image in facade space (row 0 at the top, `ppm` pixels per metre) with
the surface mask and the features that cause weathering (tops, drip edges, openings, arrises,
inside corners, fixings, joints, shelter). Each layer is built from the macro controls by explicit
rules (weather_rules.json): marks drawn at several scale levels from real sources, a cause field
shared by all layers (coherent 80/20), and a budget solver that sets the overall soiling and accent
gains so the composite hits the coverage-by-tier targets for the building's age and upkeep.

Output per plane: an opacity map and a colour per layer, the composite albedo, and the darkening
maps the gate measures (D and L_<layer>).
"""
import json
import os

import numpy as np

import material as mt
import weather_measure as wm_
import wx_noise as nz
from weather_measure import TIER_EDGES, luminance

F32 = np.float32

# layer colours, linear RGB. Dirt is a warm colour, never a grey multiply (rule I1).
COL = {
    "soiling": (0.094, 0.076, 0.052),
    "streaks": (0.074, 0.060, 0.042),
    "streaks_damp": (0.050, 0.055, 0.040),
    "stains": (0.084, 0.069, 0.050),
    "stains_crust": (0.040, 0.036, 0.029),
    "base": (0.100, 0.082, 0.058),
    "base_damp": (0.064, 0.062, 0.048),
    "bio": (0.034, 0.048, 0.028),
    "bio_algae": (0.075, 0.098, 0.042),
    "rust": (0.24, 0.105, 0.042),
    "efflorescence": (0.78, 0.78, 0.75),
    "substrate": (0.51, 0.51, 0.495),
    "rust_bar": (0.13, 0.062, 0.028),
    "old_paint": (0.70, 0.69, 0.64),
    "crack": (0.05, 0.046, 0.040),
}

# auto amounts by the soiling clock E (anchors: new, kept, typical, worn, neglected)
AUTO_E = [0.0, 10.75, 14.5, 19.8, 27.1]
AUTO = {
    "soiling": [0.0, 0.30, 0.38, 0.55, 0.80],
    "streaks": [0.0, 0.35, 0.45, 0.62, 0.85],
    "stains": [0.0, 0.20, 0.31, 0.50, 0.85],
    "base": [0.0, 0.35, 0.46, 0.63, 0.92],
    "bio": [0.0, 0.05, 0.12, 0.30, 0.75],
    "washed": [0.0, 0.10, 0.15, 0.25, 0.40],
    "film_k": [0.0, 0.62, 0.72, 0.90, 1.15],         # local contrast of the soiling film's water pattern
}
# age-driven layers (do not reset at a repaint)
AUTO_AGE = [0, 15, 35, 45, 60]
AUTO_A = {
    "rust": [0.0, 0.12, 0.30, 0.50, 0.75],
    "efflorescence": [0.0, 0.05, 0.18, 0.35, 0.55],
    "cracks": [0.0, 0.05, 0.20, 0.40, 0.60],
    "wear": [0.0, 0.15, 0.32, 0.50, 0.70],
    "damage": [0.0, 0.18, 0.40, 0.62, 0.85],
    "peeling": [0.0, 0.0, 0.08, 0.30, 0.55],
    "fading": [0.0, 0.30, 0.45, 0.55, 0.65],
}
RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_rules.json")


def clock(age, upkeep):
    cycle = 24.0 + (7.0 - 24.0) * upkeep
    r = min(age, cycle)
    return r, r + 0.22 * (age - r)


def auto_amounts(cfg):
    age, up = cfg["age"], cfg["upkeep"]
    R, E = clock(age, up)
    a = {k: float(np.interp(E, AUTO_E, v)) for k, v in AUTO.items()}
    care = 1.0 + 0.6 * (0.5 - up)                     # neglect pushes the age-driven layers
    for k, v in AUTO_A.items():
        a[k] = float(np.clip(np.interp(age, AUTO_AGE, v) * care, 0, 1))
    a["peeling"] *= float(np.clip((0.8 - up) / 0.6, 0, 1.5))
    a["repaint_patches"] = 0                # off by default: a control (cfg override), not part of the presets
    for k, v in cfg.get("override", {}).items():
        a[k] = v
    return R, E, a


# ---------------------------------------------------------------------------------------------
# shared fields (cached per plane)

TEXDIR = os.environ.get("WX_TEX", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "examples", "danchi", "tex", "round_e"))
_TEX = {}


def material_map(name, channel, tile_m, ppm, shape):
    """A round-E material map (coat strength, roller laps, seams...) tiled in facade space at its
    true size, as a float field. Weathering reads it so dirt follows the material (rule J2)."""
    k = (name, channel, ppm)
    if k not in _TEX:
        from PIL import Image
        im = Image.open(os.path.join(TEXDIR, name))
        im = im.convert("RGB") if channel is not None else im.convert("L")
        n = max(8, int(round(tile_m * ppm)))
        im = im.resize((n, n), Image.BOX)
        a = np.asarray(im, np.float32) / 255.0
        _TEX[k] = a[..., channel] if channel is not None else a
    t = _TEX[k]
    H, W = shape
    return t[(np.arange(H) % t.shape[0])[:, None], (np.arange(W) % t.shape[1])[None, :]]


def flow_accum(mask, rain, start=None):
    """Run-off accumulated down each column from the top of every surface run, reset at gaps
    and at given run starts (a depth step: water drips off a bottom edge and starts again on the
    next surface)."""
    H, W = mask.shape
    r = np.where(mask, rain, 0.0).astype(np.float64)
    cs = np.cumsum(r, axis=0)
    if start is None:
        start = mask & ~np.vstack([np.zeros((1, W), bool), mask[:-1]])
    idx = np.where(start, np.arange(H)[:, None], 0)
    idx = np.maximum.accumulate(idx, axis=0)
    cols = np.arange(W)[None, :]
    base = np.where(idx > 0, cs[np.maximum(idx - 1, 0), cols], 0.0)
    return ((cs - base) * mask).astype(F32)


class PlaneFields:
    def __init__(self, plane, cfg):
        self.p = plane
        sh, ppm = plane["mask"].shape, plane["ppm"]
        base_key = (cfg["seed"], plane["orient"], plane["name"])
        mask = plane["mask"]
        # cause field: S1-S4 lognormal + tall column bands (1-2 columns in 5 worse). Shared by
        # every layer so layers correlate and neighbouring floors stay alike (E1, D1). A draw is
        # kept only if it leaves no clean section (A2) and no clean end (A3); otherwise redraw.
        self.redraws = 0
        for attempt in range(12):
            key = base_key + (("draw", attempt) if attempt else ())
            c = nz.lognormal(sh, ppm, [0, 1, 2, 3], key + ("cause",), sigma=0.70, weights=[1.0, 1.0, 0.7, 0.12])
            cols = nz.gfield(sh, 1.2 * ppm, key + ("cols",), aniso=(20.0, 1.0))
            c = c * np.exp(0.40 * np.clip(cols, -1.5, 2.5))
            macro = nz.lognormal(sh, ppm, [0, 1, 2], key + ("macro",), sigma=0.35)
            test = np.where(mask, c ** 0.6 * macro, np.nan)
            if _fields_ok(test, ppm) and _top_ok(np.where(mask, c, np.nan), plane):
                break
            self.redraws += 1
        self.key = key
        self.C = (c / c[mask].mean()).astype(F32)
        self.macro = (macro / macro[mask].mean()).astype(F32)
        self.inner = nz.lognormal(sh, ppm, [4, 5, 6, 7], key + ("inner",), sigma=0.55,
                                  weights=[1.0, 1.0, 0.9, 0.8], aniso=(2.2, 1.0)).astype(F32)
        self.patt = nz.lognormal(sh, ppm, [3, 4, 5, 6, 7], key + ("patt",), sigma=1.0).astype(F32)
        self.biopatt = nz.lognormal(sh, ppm, [4, 5, 6, 7], key + ("biopatt",), sigma=1.0,
                                    weights=[0.5, 0.8, 1.0, 1.0], aniso=(4.0, 1.0)).astype(F32)   # along the run-off
        self.hgt = height01(plane).astype(F32)
        # mid variation (S4-S6, slightly vertical) and fine dust grain (S7-S8)
        self.mid = nz.lognormal(sh, ppm, [3, 4, 5], key + ("mid",), sigma=0.22, aniso=(4.0, 1.0)).astype(F32)
        self.speck = nz.lognormal(sh, ppm, [6, 7], key + ("speck",), sigma=0.45).astype(F32)
        at = 0.6 * nz.fbm(sh, ppm, [6, 7], key + ("acctex",), aniso=(2.0, 1.0)) +             0.45 * nz.gfield(sh, 0.05 * ppm, key + ("acctex", "fine"), aniso=(1.6, 1.0))
        at = np.exp(at)
        self.acctex = (at / at.mean()).astype(F32)               # grainy, streaky inside accumulations
        g = np.exp(0.35 * nz.gfield(sh, 0.8, key + ("grain",)))
        self.grain = (g / g.mean()).astype(F32)                 # dust grain below S8 (3 cm)
        # run-off: rain caught by the face (more at the top and at the plane's ends), flowing
        # down meandering channels 5-30 cm apart (vertical washing texture)
        H, W = sh
        x = np.arange(W)[None, :] / ppm
        cols_m = np.flatnonzero(plane["mask"].any(axis=0))
        x0, x1 = (cols_m[0] / ppm, cols_m[-1] / ppm) if cols_m.size else (0, W / ppm)
        dend = np.minimum(x - x0, x1 - x)
        self.ends = (1.0 + 0.25 * np.exp(-np.clip(dend, 0, None) / 1.2)).astype(F32) * np.ones((H, 1), F32)
        rain = plane.get("face_rain", 1.0) * (0.5 + 1.0 * self.hgt ** 1.5) * self.ends
        rain = rain * (1.0 - 0.85 * plane.get("shelter", np.zeros(sh)))
        self.F = flow_accum(plane["mask"], rain / ppm, plane.get("flow_start"))   # metres of wall above
        warp = nz.gfield(sh, 1.5 * ppm, key + ("warp",), aniso=(4.0, 1.0)) * 0.06 * ppm
        chan = nz.gfield(sh, 0.05 * ppm, key + ("chan",), aniso=(25.0, 1.0))
        xi = np.clip((np.arange(W)[None, :] + warp).astype(int), 0, W - 1)
        chan = chan[np.arange(H)[:, None], xi]
        self.chan = nz.smoothstep(-0.2, 1.4, chan).astype(F32)   # 0..1, about 30 % in channels
        # material response: coat strength and roller laps (painted), seams and voids (concrete)
        cls = plane.get("cls")
        self.mat = np.ones(sh, F32)
        try:
            coat = material_map("spraymacro_mask.png", 0, 3.6, ppm, sh)
            lap = material_map("spraymacro_lap.png", None, 3.6, ppm, sh)
            self.mat = (0.75 + 0.35 * coat + 0.25 * lap).astype(F32)
            if cls is not None:
                fm = material_map("formed_mask.png", 2, 3.6, ppm, sh)        # seam band
                fv = material_map("formed_mask.png", 1, 3.6, ppm, sh)        # voids
                conc = np.isin(cls, (4, 5))
                self.mat[conc] = (0.85 + 0.6 * fm + 0.8 * fv)[conc]
        except Exception:
            pass
        cc = plane.get("coat_cloud")
        self.zc = np.zeros(sh, F32)
        if cc is not None and mask.any():
            sd = max(float(np.std(cc[mask])), 1e-6)
            self.zc = np.clip((1.0 - cc) / sd, -2.5, 2.5).astype(F32)   # + where the coat is thin
        jh, jv = plane.get("joint_h"), plane.get("joint_v")
        if jh is not None and (jh.any() or jv.any()):
            self.jd = mt.joint_dirt(jh, jv, ppm)                       # dirt in the grooves and the lip below
            self.jwet = np.clip(wm_.gauss((jh | jv).astype(F32) + 0.6 * np.minimum(self.jd, 1.0),
                                          0.02 * ppm), 0, 1).astype(F32)
        else:
            self.jd = np.zeros(sh, F32)
            self.jwet = np.zeros(sh, F32)


def _fields_ok(test, ppm):
    """A2/A3 on a candidate cause x macro draw: 4 m cells P10 >= 0.45 x mean and min >= 0.3 x
    mean; the 1 m bands at both ends >= 0.75 x mean (margins above the gate's limits)."""
    import weather_measure as wm
    g = wm.cells(test, ppm, 4.0)
    v = g[np.isfinite(g)]
    if v.size >= 5:
        if np.percentile(v, 10) < 0.45 * v.mean() or v.min() < 0.30 * v.mean():
            return False
    cols = np.flatnonzero(np.isfinite(test).any(axis=0))
    if cols.size > 3 * ppm:
        m = np.nanmean(test)
        b = int(ppm)
        if np.nanmean(test[:, cols[0]:cols[0] + b]) < 0.75 * m or np.nanmean(test[:, cols[-1] - b + 1:cols[-1] + 1]) < 0.75 * m:
            return False
    return True


def _top_ok(c, plane):
    """F1 on a candidate cause field: mean over the top 20 % of the wall height >= the 30-70 %
    band (the cause field may make a wall dirtier in places, not cleaner at the top)."""
    import weather_measure as wm
    hp = wm.height_profile(c ** 1.6, plane["ppm"], plane.get("ground_row"), plane.get("top_row"))
    if not hp or not hp["mid30_70"]:
        return True
    return hp["top20"] >= 1.05 * hp["mid30_70"]


def flow_top_ratio(plane, flow):
    """F1 on a draw of run-off marks: mean over the top 20 % of the wall height over the 30-70 %
    band, painted wall only (1e9 when there is nothing to compare)."""
    import weather_measure as wm
    if plane.get("kind") not in ("wall", "gable", "front"):
        return 1e9
    cls = plane.get("cls")
    v = np.where(plane["mask"] & (np.isin(cls, (1, 2)) if cls is not None else True), flow, np.nan)
    hp = wm.height_profile(v.astype(np.float64), plane["ppm"], plane.get("ground_row"), plane.get("top_row"))
    if not hp or not hp["mid30_70"]:
        return 1e9
    return hp["top20"] / hp["mid30_70"]


def height01(plane):
    H = plane["mask"].shape[0]
    g, t = plane["ground_row"], plane["top_row"]
    y = (g - np.arange(H)) / max(g - t, 1)
    return np.clip(y, 0, 1)[:, None] * np.ones((1, plane["mask"].shape[1]))


def region_below(mask, row, col, max_px):
    """How far a run starting at (row, col) can go down inside the surface before it leaves it."""
    H = mask.shape[0]
    end = min(H, row + max_px)
    col = int(np.clip(col, 0, mask.shape[1] - 1))
    seg = mask[row:end, col]
    if seg.size == 0:
        return 0
    off = np.flatnonzero(~seg)
    return int(off[0]) if off.size else seg.size


# ---------------------------------------------------------------------------------------------
# stamps (marks). Each returns (accepted, info); a mark that breaks its rule is not drawn.

def stamp_run(acc, mask, ppm, x0, y0, length_m, w0_m, w1_m, opacity, key, striate=0.35,
              wobble_m=0.02, profile_p=0.6, tail=0.5):
    """One run (streak), darkest at its source and fading downward (F2), ragged edges, inner
    vertical striation, clipped to the surface, 'over' build-up."""
    H, W = acc.shape
    L = max(2, int(length_m * ppm))
    half = max(w0_m, w1_m) * ppm * 0.5 + wobble_m * ppm + 2
    xa, xb = int(max(0, x0 - half - 2)), int(min(W, x0 + half + 3))
    ya, yb = int(max(0, y0)), int(min(H, y0 + L))
    if xb <= xa or yb <= ya:
        return False, None
    r = nz.rng(*key)
    yy = np.arange(ya, yb)[:, None]
    xx = np.arange(xa, xb)[None, :]
    t = (yy - y0) / L
    nwob = max(4, (yb - ya) // max(1, int(0.25 * ppm)) + 3)
    wob = np.interp(np.arange(ya, yb), np.linspace(ya, yb, nwob), r.normal(0, 1, nwob)) * wobble_m * ppm
    hw = 0.5 * ppm * (w0_m + (w1_m - w0_m) * np.clip(t, 0, 1) ** 0.7)
    edge_n = np.interp(np.arange(ya, yb), np.linspace(ya, yb, nwob * 2), r.normal(0, 1, nwob * 2))[:, None]
    hw = hw * (1.0 + 0.25 * edge_n)
    dx = np.abs(xx - (x0 + wob[:, None])) / np.maximum(hw, 0.6)
    across = np.clip(1.0 - dx * dx, 0.0, 1.0) ** profile_p
    along = np.clip(1.0 - np.clip(t, 0, 1) ** tail, 0.0, 1.0)
    if striate > 0:
        sw = r.normal(0, 1, (xb - xa,))
        k = max(1, int(0.015 * ppm))
        sw = np.convolve(sw, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
        sw = sw / (sw.std() + 1e-9)
        stria = np.clip(1.0 + striate * sw[None, :], 0.2, 1.8)
    else:
        stria = 1.0
    a = opacity * across * along * stria * mask[ya:yb, xa:xb]
    a = np.clip(a, 0, 0.95)
    if a.max() < 0.01:
        return False, None
    acc[ya:yb, xa:xb] = nz.over(acc[ya:yb, xa:xb], a)
    return True, {"x": x0, "y": y0, "L_m": (yb - ya) / ppm, "w_m": max(w0_m, w1_m), "peak": float(a.max())}


def stamp_stain(acc, mask, inner, ppm, x0, y0, width_m, drop_m, opacity, key, crust=0.0):
    """A water-spread stain hanging from (x0, y0): a curtain with a ragged, fingered lower edge,
    an inner pattern on S5-S8 (>= 3 tiers inside, B2), darker toward the top (F1/F2)."""
    H, W = acc.shape
    wpx, dpx = max(4, int(width_m * ppm)), max(4, int(drop_m * ppm))
    xa, xb = int(max(0, x0 - wpx // 2 - 4)), int(min(W, x0 + wpx // 2 + 4))
    ya, yb = int(max(0, y0)), int(min(H, y0 + int(dpx * 1.35)))
    if xb - xa < 4 or yb - ya < 4:
        return False, None
    r = nz.rng(*key)
    h, w = yb - ya, xb - xa
    xx = (np.arange(xa, xb) - x0) / (wpx / 2.0)
    ncol = max(6, w // max(1, int(0.12 * ppm)) + 2)
    prof = np.interp(np.arange(w), np.linspace(0, w - 1, ncol), r.normal(0, 1, ncol))
    fing = np.interp(np.arange(w), np.linspace(0, w - 1, ncol * 4), np.abs(r.normal(0, 1, ncol * 4)))
    side = np.clip(1.0 - xx ** 2, 0.0, 1.0) ** 0.5
    nw = max(4, w // max(1, int(0.25 * ppm)) + 2)            # darkness varies across the width
    across = np.interp(np.arange(w), np.linspace(0, w - 1, nw), r.normal(0, 1, nw))
    across = 0.5 + 1.0 * nz.smoothstep(-1.2, 1.2, across)
    drop = np.maximum(dpx * side * (0.75 + 0.22 * prof + 0.30 * fing ** 2), 1)
    yy = np.arange(h)[:, None] + (ya - y0)
    t = yy / drop[None, :]
    body = np.clip(1.0 - t, 0.0, 1.0) ** 0.55
    soft = nz.smoothstep(0.0, 0.25, 1.0 - np.abs(xx))[None, :]
    inn = inner[ya:yb, xa:xb]
    a = opacity * body * soft * across[None, :] * np.clip(inn, 0.15, 2.2)
    if crust > 0:
        core = nz.smoothstep(0.55, 0.0, t) * nz.smoothstep(0.4, 0.95, inn / 2.0)
        a = a + crust * opacity * core
    a = np.clip(a * mask[ya:yb, xa:xb], 0, 0.80)
    if a.max() < 0.02:
        return False, None
    acc[ya:yb, xa:xb] = nz.over(acc[ya:yb, xa:xb], a)
    return True, {"x": x0, "y": y0, "w_m": w / ppm, "h_m": h / ppm, "peak": float(a.max())}


def stamp_blob(acc, ppm, xc, yc, r_m, opacity, key, ragged=0.35, hard=0.15):
    """Irregular blob (chip, flake, speck) with a ragged edge. Returns its footprint."""
    H, W = acc.shape
    R = max(1.0, r_m * ppm)
    xa, xb = int(max(0, xc - 1.6 * R - 2)), int(min(W, xc + 1.6 * R + 3))
    ya, yb = int(max(0, yc - 1.6 * R - 2)), int(min(H, yc + 1.6 * R + 3))
    if xb <= xa or yb <= ya:
        return None
    r = nz.rng(*key)
    yy, xx = np.mgrid[ya:yb, xa:xb]
    ang = np.arctan2(yy - yc, xx - xc)
    amp = r.normal(0, 1, 5) / np.arange(1, 6) ** 1.2
    ph = r.uniform(0, 2 * np.pi, 5)
    rad = R * (1.0 + ragged * sum(amp[i] * np.cos((i + 1) * ang + ph[i]) for i in range(5)))
    d = np.hypot(yy - yc, xx - xc) / np.maximum(rad, 0.5)
    a = opacity * nz.smoothstep(1.0, max(0.0, 1.0 - hard - 1.5 / R), d) if R > 2 else opacity * (d < 1.0)
    acc[ya:yb, xa:xb] = nz.over(acc[ya:yb, xa:xb], a)
    return (ya, yb, xa, xb, d)


def chip_depth(r_m):
    """How deep a break goes: the paint and skin on small chips (2-5 mm), the cover concrete on
    spalls (to 4 cm, the rebar depth)."""
    return min(0.04, 0.0015 + 0.22 * r_m)


def edge_angle(edges, y, x, k=4):
    """Direction of the edge through (y, x): 0 along a horizontal run, pi/2 along a vertical one."""
    H, W = edges.shape
    row = int(edges[y, max(0, x - k):x + k + 1].sum())
    col = int(edges[max(0, y - k):y + k + 1, x].sum())
    return 0.0 if row >= col else np.pi / 2


def _polygon_sd(px, py, vx, vy):
    """Signed distance (px) from points to a closed polygon: + inside, - outside."""
    d = np.full(px.shape, np.inf)
    inside = np.zeros(px.shape, bool)
    n = len(vx)
    for i in range(n):
        x0, y0, x1, y1 = vx[i], vy[i], vx[(i + 1) % n], vy[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        L2 = ex * ex + ey * ey + 1e-12
        t = np.clip(((px - x0) * ex + (py - y0) * ey) / L2, 0, 1)
        d = np.minimum(d, np.hypot(px - x0 - t * ex, py - y0 - t * ey))
        cross = ((y0 > py) != (y1 > py)) & (px < x0 + (py - y0) * ex / (ey + 1e-12))
        inside ^= cross
    return np.where(inside, d, -d)


def stamp_break(sub, dep, tone, cav, ppm, xc, yc, r_m, depth_m, key, theta=0.0, bar=None, gk=None,
                mask=None):
    """One break: concrete fractures along planes, so the outline is a polygon of 5-8 corners with
    a jagged line between them, stretched along the edge it broke from (the bar runs with the
    arris); alpha is the pixel's coverage (a 1 px edge, no falloff). The floor is recessed by
    depth_m, a cliff at the rim and deeper inwards, with a rough fracture surface; each break has
    its own tone (an old one has soiled again, a fresh one is lighter). From 3 cm radius a spall:
    the concrete body (darker than the skin a chip shows, coarser grain, pores); from 8 cm the bar
    shows with a rust halo. Returns {"box", "low": the lowest rim point near the bar} or None."""
    H, W = sub.shape
    R = r_m * ppm
    r = nz.rng(*key)
    spall = r_m >= 0.03
    s = r.uniform(1.3, 2.2) if spall else r.uniform(1.0, 1.6)
    n = int(r.integers(5, 9))
    ang = np.sort(r.uniform(0, 2 * np.pi, n))
    rad = R * r.uniform(0.6, 1.15, n)
    ux, uy = rad * np.cos(ang) * np.sqrt(s), rad * np.sin(ang) / np.sqrt(s)
    jx, jy = [], []
    for i in range(n):                                  # each side broken into three jagged pieces
        x0, y0, x1, y1 = ux[i], uy[i], ux[(i + 1) % n], uy[(i + 1) % n]
        nx_, ny_ = -(y1 - y0), x1 - x0
        for f in (0.0, 1 / 3, 2 / 3):
            j = 0.0 if f == 0.0 else r.normal(0, 0.10)
            jx.append(x0 + f * (x1 - x0) + j * nx_)
            jy.append(y0 + f * (y1 - y0) + j * ny_)
    c, sn = np.cos(theta), np.sin(theta)
    vx = xc + np.array(jx) * c - np.array(jy) * sn
    vy = yc + np.array(jx) * sn + np.array(jy) * c
    ext = 1.3 * R * np.sqrt(s) + 2
    xa, xb = int(max(0, xc - ext)), int(min(W, xc + ext + 1))
    ya, yb = int(max(0, yc - ext)), int(min(H, yc + ext + 1))
    if xb <= xa or yb <= ya:
        return None
    yy, xx = np.mgrid[ya:yb, xa:xb]
    sd = _polygon_sd(xx + 0.0, yy + 0.0, vx, vy)
    a = np.clip(sd + 0.5, 0.0, 1.0).astype(F32)
    if not a.any():
        return None
    from weather_measure import gauss
    rough = 1.0 + 0.12 * gauss(r.uniform(-1, 1, a.shape), 0.8) / 0.35
    floor = 0.7 + 0.3 * np.clip(sd / max(0.5 * R, 1.0), 0, 1)
    d = (depth_m * a * floor * np.clip(rough, 0.7, 1.3)).astype(F32)
    t = float(r.uniform(0.86, 1.06)) * (0.82 if spall else 1.0)
    S = sub[ya:yb, xa:xb]
    newer = a > S
    tone[ya:yb, xa:xb] = np.where(newer, t, tone[ya:yb, xa:xb])
    if gk is not None:
        gk[ya:yb, xa:xb] = np.where(newer, 0.11 if spall else 0.06, gk[ya:yb, xa:xb])
    sub[ya:yb, xa:xb] = nz.over(S, a)
    dep[ya:yb, xa:xb] = np.maximum(dep[ya:yb, xa:xb], d)
    if spall:
        pores = (0.15 * a * (rough > 1.10)).astype(F32)
        cav[ya:yb, xa:xb] = np.maximum(cav[ya:yb, xa:xb], pores)
    low = None
    if bar is not None and r_m >= 0.08:
        ax_, ay_ = c, sn                                # along the arris
        px_, py_ = -sn, c                               # across it
        o = 0.3 * R

        def on(yv, xv):
            yi, xi = int(round(yv)), int(round(xv))
            return 0 <= yi < H and 0 <= xi < W and (mask is None or bool(mask[yi, xi]))
        side = 1.0 if on(yc + py_ * o, xc + px_ * o) or not on(yc - py_ * o, xc - px_ * o) else -1.0
        cxb, cyb = xc + side * px_ * o, yc + side * py_ * o       # at cover depth, into the face
        along = (xx - cxb) * ax_ + (yy - cyb) * ay_
        acr = np.abs((xx - cxb) * px_ + (yy - cyb) * py_)
        half = 0.8 * R * np.sqrt(s)
        wpx = 1.0 if r_m < 0.2 else 1.6
        lim = np.clip(half - np.abs(along) + 0.5, 0, 1)
        b_ = np.clip(wpx / 2 + 0.5 - acr, 0, 1) * lim * (a > 0.5)
        halo = 0.40 * np.exp(-acr / (1.2 + 0.08 * R)) * lim * a
        bar[ya:yb, xa:xb] = np.maximum(bar[ya:yb, xa:xb], np.maximum(0.9 * b_, halo).astype(F32))
        inside = a > 0.5
        rows = np.flatnonzero(inside.any(axis=1))
        if rows.size:
            ry = rows[-1]
            cols = np.flatnonzero(inside[ry])
            low = (int(ya + ry), int(xa + cols[len(cols) // 2]))
    return {"box": (ya, yb, xa, xb), "low": low}


# ---------------------------------------------------------------------------------------------
# layers

def sources_along_tops(plane, key, density_per_m, gap_sigma=1.0):
    """Irregular low points along every top edge: a Poisson process thinned by a 1D cascade, so
    there are clusters and gaps of 0.5-2 m with nothing (streak spacing)."""
    tops = plane["tops"]
    ppm = plane["ppm"]
    ys, xs = np.nonzero(tops)
    if ys.size == 0:
        return []
    r = nz.rng(*key)
    lam = np.exp(gap_sigma * nz.gfield((1, plane["mask"].shape[1]), 0.6 * ppm, key + ("gap",))[0] - gap_sigma ** 2 / 2)
    p = density_per_m / ppm * lam[xs]
    keep = r.random(ys.size) < np.clip(p, 0, 1)
    pts = sorted(zip(xs[keep].tolist(), ys[keep].tolist()))
    out, last = [], {}
    for x, y in pts:
        if y in last and x - last[y] < 0.06 * ppm:
            continue
        last[y] = x
        out.append((x, y))
    return out


def layer_streaks(plane, F, cfg, a, key):
    """Run-off streaks from features: low points along tops (fringe), sill ends (V fans), inside
    corners (wide), joints and fixings (narrow). Per source: power-law strength x cause field x
    driven rain x height (top floors 1.5-2.5x); lengths log-normal with a tail to the next catch;
    1-3 overlapping runs for build-up; colour by cause."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    damp = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    rain = plane.get("face_rain", 1.0)
    bias = 0.8 + 1.0 * cfg.get("exposure", 0.6)
    omax = 0.25 + 0.40 * a
    alpha = 1.75 - 0.25 * a                 # length tail: heavier with the amount, never below 1.5
    srcs = [(x, y, "top") for x, y in sources_along_tops(plane, key + ("tops",), 1.5 + 2.5 * a)]
    srcs += [(x, y, "sill") for (y, x) in plane.get("sill_ends", [])]
    srcs += [(x, y, "corner") for (y, x) in plane.get("corner_heads", [])]
    srcs += [(x, y, "fixing") for (y, x, _k) in plane.get("fixings", [])]
    srcs += [(x, y, "joint") for (y, x) in plane.get("joints", [])]
    C, hgt = F.C, F.hgt
    for (x, y, kind) in srcs:
        r = nz.rng(*key, "src", kind, x, y)
        yy, xx = min(y, H - 1), min(x, W - 1)
        room = region_below(mask, y + 1, x, H)
        if room < 0.05 * ppm:
            continue
        hf = 1.0 + bias * hgt[yy, xx] ** 1.5
        s = np.exp(r.normal(0.0, 0.45)) * 0.75 * C[yy, xx] ** 1.6 * rain * hf
        s *= {"sill": 1.6, "corner": 1.3, "joint": 0.45, "fixing": 0.6}.get(kind, 1.0)
        if r.random() > 0.35 + 0.65 * hgt[yy, xx] ** 1.2:  # driven rain wets the upper storeys more
            continue
        if s < 0.25 and r.random() > a * hf / 2.0:        # weak sources show on dirtier, higher walls
            continue
        nruns = 1 + int(r.random() < 0.35 + 0.4 * a) + int(r.random() < 0.25 * a)
        for j in range(nruns):
            rj = nz.rng(*key, "run", kind, x, y, j)
            # power law N(>L) ~ L^-1.5: each octave down holds 2.8x the runs (C3), few reach the
            # next drip edge, so a cap (the parapet's foot) does not pile them up
            Lm = 0.07 * (1.0 + 0.5 * a) * hf ** 0.5 * s ** 0.3 * (1.0 + rj.pareto(alpha))
            if rj.random() < 0.015 + 0.03 * a:
                Lm = 0.8 * (1.0 + rj.pareto(1.0))              # an established run: 0.8 m up, power law
            Lm = min(Lm, room / ppm)
            if Lm < 0.05:
                continue
            lw = (Lm / 0.3) ** 0.35                       # longer runs fan out wider
            if kind == "corner":
                w0, w1 = rj.uniform(0.04, 0.10) * lw ** 0.5, rj.uniform(0.08, 0.18) * lw ** 0.5
            elif kind == "sill" or (s > 1.4 and rj.random() < 0.3):
                w0, w1 = rj.uniform(0.025, 0.06) * lw, rj.uniform(0.08, 0.18) * lw
            elif kind in ("fixing", "joint"):
                w0, w1 = rj.uniform(0.008, 0.025) * lw, rj.uniform(0.015, 0.05) * lw
            else:
                w0, w1 = rj.uniform(0.006, 0.03) * lw, rj.uniform(0.010, 0.055) * lw
            op = omax * min(1.4, s) * rj.uniform(0.35, 1.0) * (0.75 if j else 1.0)
            op *= min(1.0, (Lm / 0.4) ** 0.4)               # a short drip is a little dirty water
            dx = rj.normal(0, 0.02 * ppm) if j else 0.0
            target = damp if (plane.get("orient") == "N" and rj.random() < 0.4) else acc
            ok, info = stamp_run(target, mask, ppm, x + dx, y + 1, Lm, w0, w1, op,
                                 key + ("run", kind, x, y, j), striate=0.25 + 0.3 * rj.random(),
                                 tail=rj.uniform(0.35, 0.8))
            if ok:
                info["kind"] = kind
                marks.append(info)
    col = None
    if damp.max() > 0:
        wd = damp / np.maximum(acc + damp, 1e-6)
        col = ((1 - wd)[..., None] * np.array(COL["streaks"], F32) + wd[..., None] * np.array(COL["streaks_damp"], F32))
        acc = nz.over(acc, damp).astype(F32)
    return acc, col, marks


def layer_stains(plane, F, cfg, a, key):
    """Large water-spread stains from wall tops, strong sources and inside corners, placed by
    the cause field; sizes by power law across S3-S8 (more small than large, C3); nested
    build-up of 2-4 stains with an inner pattern (B2)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    C, hgt = F.C, F.hgt
    anchors = [(x, y, 1.0) for (x, y) in sources_along_tops(plane, key + ("anch",), 0.8 + 4.5 * a, gap_sigma=1.3)]
    anchors += [(x, y, 1.0) for (y, x) in plane.get("corner_heads", [])]
    anchors += [(x, y, 0.25) for (y, x) in plane.get("joints", [])]      # seepage at joints: small, discrete
    tall = plane.get("kind") in ("gable", "wall", "tower")
    smax = (0.7 + 1.6 * a) if tall else (0.6 + 0.9 * a)
    alpha_sz = 1.9 + 0.2 * a                 # more amount: more stains rather than a heavier tail
    for (x, y, w_acc) in anchors:
        jnt = w_acc < 0.5                    # a joint anchor
        r = nz.rng(*key, "st", x, y)
        yy, xx = min(y, H - 1), min(x, W - 1)
        room = region_below(mask, y + 1, x, H)
        if room < 0.12 * ppm:
            continue
        c = C[yy, xx]
        if r.random() > min(1.0, w_acc * (0.2 + 0.8 * a) * c ** 1.1 * (0.3 + 0.7 * hgt[yy, xx] ** 1.5) / 0.58):
            continue
        hf = 1.0 + 0.6 * hgt[yy, xx]
        size = min(smax, 0.10 * (1.0 + r.pareto(alpha_sz)) * (0.6 + a) * hf)  # power law, 3x+ per octave
        if jnt:
            size *= 0.5
        drop = float(np.clip(size * r.uniform(0.7, 2.0) * (1.5 if tall else 0.9), 0.08, room / ppm))
        width = float(np.clip(size * r.uniform(0.6, 1.6), 0.10, 0.8 if jnt else 4.5 if tall else 1.2 * drop + 0.1))
        op = (0.22 + 0.40 * a) * min(1.5, c) ** 0.5 * r.uniform(0.6, 1.1) * (0.85 + 0.3 * hgt[yy, xx])
        crust = 0.0 if a < 0.5 else (a - 0.5) * 0.8
        n = min(3, 1 + int(size > 0.4) + int(r.random() < 0.5 and size > 0.8) + int(r.random() < 0.3 * a))
        for j in range(n):
            f = 1.0 - 0.22 * j
            ok, info = stamp_stain(acc, mask, F.inner, ppm, x + r.normal(0, 0.08 * width * ppm), y + 1,
                                   width * f, drop * f ** 1.4, op * (0.45 + 0.15 * j),
                                   key + ("st", x, y, j), crust=crust if j == n - 1 else 0.0)
            if ok and j == 0:
                marks.append(info)
    # small stains: drops and splashes 5-40 cm, many more than the big ones (C3)
    r = nz.rng(*key, "small")
    ys, xs = np.nonzero(mask)
    n = int((0.9 + 9.0 * a) * mask.sum() / ppm ** 2 / 4.0)
    if ys.size and n:
        w = (C[ys, xs].astype(np.float64) ** 1.0) * (1.0 + hgt[ys, xs])
        pick = r.choice(ys.size, size=n, p=w / w.sum())
        for i, j in enumerate(pick):
            size = min(0.40, 0.04 * (1.0 + r.pareto(1.5)))
            op = (0.15 + 0.30 * a) * r.uniform(0.4, 1.0)
            if r.random() < 0.6:                       # a splash: irregular, no tail
                res_ = stamp_blob(acc, ppm, xs[j], ys[j], 0.5 * size * r.uniform(0.6, 1.3), op * 0.8,
                                  key + ("smb", i), ragged=0.55, hard=0.05)
                ok, info = res_ is not None, {"x": int(xs[j]), "y": int(ys[j]), "w_m": size, "h_m": size, "peak": op}
            else:                                      # a short dribble
                ok, info = stamp_stain(acc, mask, F.inner, ppm, xs[j], ys[j], size * r.uniform(0.6, 1.4),
                                       size * r.uniform(0.4, 1.0), op, key + ("sm", i))
            if ok:
                marks.append(info)
    return acc, None, marks


def soiling_field(plane, F, cfg, E):
    """The un-scaled soot film, built from causes: dry deposition everywhere (a floor, so no
    face is pristine: A2) with soft macro tone (S1-S3) and mid variation (S4-S6), more where
    sheltered, under tops, in inside corners and at the plane ends (A3); rain run-off along
    meandering channels darkens the wall early in a paint cycle ('dirt washing') and cleans it
    later ('white washing'); the material holds dirt in its rougher coat and laps (J2); a faint
    dust speckle (S8). No free marble-like cascade: the pattern follows water and the material."""
    sh = plane["mask"].shape
    g = 0.6 + 0.8 * cfg.get("grime", 0.5)
    shel = plane.get("shelter", np.zeros(sh))
    if np.any(shel > 0):
        # dust in a recess: patchy (S4-S6), heavier near the soffit above
        dt = np.exp(0.75 * nz.fbm(sh, plane["ppm"], [5, 6, 7], F.key + ("dusttex2",), aniso=(1.6, 1.0)) +
                    0.30 * nz.fbm(sh, plane["ppm"], [3, 4], F.key + ("dusttex",)))
        dt = dt / dt.mean()
        run = np.zeros(sh, F32)
        H_ = sh[0]
        cnt = np.zeros(sh[1], F32)
        for y in range(H_):
            cnt = np.where(shel[y] > 0.5, cnt + 1, 0)
            run[y] = cnt
        near_soffit = np.exp(-run / (0.45 * plane["ppm"]))
        corner_line = np.exp(-run / (0.05 * plane["ppm"]))        # dust in the ceiling corner
        shel = shel * (dt * (0.2 + 1.6 * near_soffit) + 0.8 * corner_line)
    exc = 0.25 * shel                                         # physical excess: shelter, tops, corners
    W_ = sh[1]
    ut_mod = np.exp(0.7 * nz.fbm((1, W_), plane["ppm"], [5, 6, 7], F.key + ("utmod",))[0])
    ut_mod = (ut_mod / ut_mod.mean())[None, :] * F.acctex     # broken up along the edge and inside
    exc = exc + 0.9 * plane.get("under_top", np.zeros(sh)) * ut_mod
    exc = exc + 0.7 * plane.get("corner_prox", np.zeros(sh))
    phys = 0.70 + 0.50 * exc                                  # half as tone, half as deposits
    phys = phys * plane.get("lee", 1.0) * (1.0 - 0.55 * plane.get("washed", np.zeros(sh)))
    phys = phys * (0.80 + 0.60 * F.hgt ** 2) * F.ends          # driven rain: the top storeys get more
    flow = 1.0 - np.exp(-F.F / 1.2)                         # water: saturates 2-3 m below a top
    load = (1.0 - np.exp(-F.F / 0.6)) * np.exp(-F.F / 7.0)     # dirt carried: peaks just below a top
    late = float(nz.smoothstep(12.0, 30.0, E))
    dirtwash = 1.0 + (1.5 * (1 - late) + 0.5) * F.chan * load / 0.55
    whitewash = 1.0 - 0.55 * late * F.chan * flow
    tone = g * phys * F.macro ** 0.8                           # smooth: sets the greying (A0)
    m = plane["mask"]
    tm = max(float(tone[m].mean()), 1e-6)
    tone = 1.8 * tm * np.tanh(tone / (1.8 * tm))               # stacked exposure factors saturate gently
    mat = F.mat / max(float(F.mat[m].mean()), 1e-6)
    tn = tone / max(float(tone[m].mean()), 1e-6)
    kg = 0.16 * np.clip(tn, 0.2, 5.0) ** -0.4
    # the material's response: coat strength and laps, a thin coat chalks and holds more dirt,
    # the joints hold dirt (grooves and the lip below)
    F.matresp = ((1.0 + 0.35 * (mat - 1.0)) * (1.0 + 0.06 * F.zc) * (1.0 + 1.6 * F.jd)).astype(F32)
    tone = tone * (1.0 + kg * (F.grain - 1.0)) * F.matresp                    # grain, material: always
    zm = (1.0 + 0.35 * (mat - 1.0)) * (1.0 + 0.06 * F.zc)
    zm = np.clip((zm - float(zm[m].mean())) / max(float(zm[m].std()), 1e-6), -2.5, 2.5)
    # water pattern, contrast solved (k); deposits follow the coat (rough or thin coat holds more)
    patt = F.mid * dirtwash * whitewash * F.speck * (1.0 + 0.35 * zm) * (1.0 + 1.6 * exc)
    patt = patt / max(float(patt[m].mean()), 1e-6)
    tl = np.clip(tn, 0.3, 3.0)
    ck = F.C ** 1.2 * tl ** 0.6                                 # pattern strongest where the causes are and
    ck = ck / max(float(ck[m].mean()), 1e-6)                    # where the load is: dirtier, more varied
    ck = 0.45 + 0.55 * ck                                       # fainter where causes are weak, never gone
    dev = patt - 1.0
    dev = np.where(dev > 0, dev * F.acctex, dev)                # deposits are grainy and streaky inside
    return (tone * m).astype(F32), (dev * m).astype(F32), (ck * m).astype(F32)


def film_of(tone, dev, k, ck=None):
    """Film = tone x (1 + k x sat(dev)); k is the film's local contrast (solved for T3+). The
    pattern saturates above: a film locally much darker than that is a mark, not a film."""
    d = np.where(dev > 0, 1.2 * np.tanh(dev / 1.2), 0.10 * np.tanh(dev / 0.10))   # dust floor + accumulations
    on = dev != 0
    d = np.where(on, d - (float(d[on].mean()) if on.any() else 0.0), 0.0)      # re-centred: no shift of the mean
    if ck is not None:
        d = d * ck
    return np.clip(tone * (1.0 + np.clip(k * d, -0.95, None)), 0, None).astype(F32)


def layer_soiling(field, a):
    return (1.0 - np.exp(-0.40 * a * field)).astype(F32)


def foot_rows(plane):
    """Per column: the foot of the painted wall (lowest painted row within 3 m of the ground; a
    plinth's top), or the ground row."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    g = plane["ground_row"]
    cls = plane.get("cls")
    painted = mask & (np.isin(cls, (1, 2)) if cls is not None else True)
    rows = np.arange(H)[:, None]
    low = np.where(painted & (rows > g - 3 * ppm), rows, -1).max(axis=0)
    return np.where(low > 0, low, g).astype(np.float64)


def layer_base(plane, F, cfg, a, key):
    """Splash, soil and damp at the foot of walls: a band of 0.3-0.9 m with a ragged top, darkest
    at the foot, splash specks above it. The foot is the ground, or the top of a plinth where the
    splash lands on its ledge and rises onto the wall above (the plinth itself also gets it).
    Splash follows the ground and the exposure, not the cause field: a 1D variation along the
    foot (S3-S5) instead."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    if a <= 0 or plane.get("ground_row") is None:
        return np.zeros((H, W), F32), None, []
    foot = foot_rows(plane)
    rows = np.arange(H)[:, None]
    north = {"N": 1.0, "E": 0.55, "W": 0.35, "S": 0.15}.get(plane.get("orient"), 0.4)
    hb = 1.5 * (0.30 + 0.45 * cfg.get("exposure", 0.6)) * (0.7 + 0.5 * a) * (1.0 + 0.3 * north)   # damp faces taller
    rag = nz.fbm((1, W), ppm, [5, 6, 7], key + ("rag",))[0]
    along = np.exp(0.30 * nz.fbm((1, W), ppm, [2, 3, 4], key + ("along",))[0])
    top = hb * ppm * (1.0 + 0.50 * rag)
    y = (foot[None, :] - rows).astype(F32)
    t = np.clip(y / np.maximum(top[None, :], 1), -1, 1.5)
    band = np.where(t >= 0, np.clip(1.0 - t, 0, 1) ** 0.6, 1.0)                # below the foot: plinth
    acc = (1.05 * a ** 0.8 * (1.0 + 0.60 * north) * band * np.clip(F.patt, 0.2, 3) ** 1.4 * F.acctex ** 0.8 *
           along[None, :]).astype(F32)                                       # speckled, streaky splash
    cap = 0.35 + 0.5 * a                                         # kept: peaks in T5; neglected: T6
    acc = cap * np.tanh(acc / cap)
    r = nz.rng(*key, "spk")
    n = int(a * W / ppm * 60)
    xs = r.uniform(0, W, n)
    ys = foot[np.clip(xs.astype(int), 0, W - 1)] - np.abs(r.exponential(0.25 * ppm, n))
    for i in range(n):
        if 0 <= ys[i] < H:
            stamp_blob(acc, ppm, xs[i], ys[i], r.uniform(0.004, 0.02), 0.25 * a, key + ("spk", i), ragged=0.3)
    acc = np.clip(acc, 0, 0.9) * mask
    wd = np.clip(band, 0, 1) * 0.6
    col = (1 - wd)[..., None] * np.array(COL["base"], F32) + wd[..., None] * np.array(COL["base_damp"], F32)
    return acc.astype(F32), col.astype(F32), []


def layer_bio(plane, F, cfg, a, key, stains=None):
    """Algae and mould where water stays: a band at the foot of the wall (darkest at the foot,
    ragged top), wet zones at and below the heads of stains, inside corners, shaded north faces.
    Patches are stretched along the run-off (S5-S8 field, vertical), green-black, greener at the
    margins; small mould and lichen dots (1-12 cm) cluster at the patch margins."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    if a <= 0:
        return np.zeros((H, W), F32), None, []
    north = {"N": 1.0, "E": 0.55, "W": 0.35, "S": 0.15}.get(plane.get("orient"), 0.4)
    damp = np.zeros((H, W), F32)
    if plane.get("ground_row") is not None:
        y = (foot_rows(plane)[None, :] - np.arange(H)[:, None]) / ppm
        damp += np.exp(-np.clip(y, 0, None) / 0.45).astype(F32)
    if stains is not None:
        wet = nz.smoothstep(0.03, 0.25, stains).astype(F32)
        k = max(1, int(0.4 * ppm))                     # water keeps the wall wet below the stain
        run = wet.copy()
        for i in range(1, k + 1, max(1, k // 8)):
            run[i:] = np.maximum(run[i:], wet[:-i] * (1 - i / (k + 1)))
        damp += 1.8 * run
    damp += 1.2 * plane.get("corner_prox", np.zeros((H, W), F32))
    damp += 0.12 * plane.get("shelter", np.zeros((H, W), F32)) * north  # humid but out of the rain
    damp += 1.0 * F.jwet * (0.4 + 0.6 * north)                # joints stay wet: algae lines along them
    f = damp * F.biopatt * F.C ** 0.5 * (0.25 + 0.75 * north)
    q = min(0.35, (0.03 + 0.32 * a) * (0.35 + 0.65 * north))   # share of the wall; it follows the damp
    thr = np.quantile(f[mask], 1.0 - q) if mask.any() else 1e9
    alpha = 0.55 * a ** 0.6 * nz.smoothstep(thr, thr * 2.2, f) * np.clip(F.biopatt, 0.3, 2.0) / 1.6
    alpha = np.clip(alpha, 0, 0.7)
    r = nz.rng(*key, "spots")
    edge = (alpha > 0.02) & (alpha < 0.25) & mask
    ys, xs = np.nonzero(edge)
    n = int(a * mask.sum() / ppm ** 2 * 8.0)
    if ys.size and n:
        pick = r.integers(0, ys.size, n)
        for i, j in enumerate(pick):
            rad = min(0.06, 0.005 * (1.0 + r.pareto(1.3)))
            stamp_blob(alpha, ppm, xs[j] + r.normal(0, 0.08 * ppm), ys[j] + r.normal(0, 0.08 * ppm),
                       rad, 0.35 * a ** 0.6 * r.uniform(0.4, 1.0), key + ("spot", i), ragged=0.5)
    alpha = (np.clip(alpha, 0, 0.85) * mask).astype(F32)
    margin = np.clip(1.0 - alpha / 0.4, 0, 1)
    col = (1 - margin)[..., None] * np.array(COL["bio"], F32) + margin[..., None] * np.array(COL["bio_algae"], F32)
    return alpha, col.astype(F32), []


def layer_rust(plane, F, cfg, a, key, spalls=None):
    """Rust from fixings (a bloom and a run) and, where a spall shows its bar, a bleed from the
    break's lowest rim down the wall."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    for (y, x, rm) in (spalls or []):
        r = nz.rng(*key, "spall", int(y), int(x))
        room = region_below(mask, y + 1, x, H)
        if room <= 0.03 * ppm:
            continue
        ln = min(room / ppm, r.uniform(0.25, 1.0) * (0.5 + a) * min(2.0, (rm / 0.1) ** 0.5))
        w0 = min(0.06, 0.25 * rm)
        ok, info = stamp_run(acc, mask, ppm, x, y + 1, ln, w0, 1.5 * w0, 0.30 + 0.35 * a,
                             key + ("sr", int(y), int(x)), striate=0.3)
        if ok:
            marks.append(info)
    for (y, x, kind) in plane.get("fixings", []):
        r = nz.rng(*key, "rust", x, y)
        if r.random() > 0.25 + 0.75 * a:
            continue
        room = region_below(mask, y + 1, x, H)
        stamp_blob(acc, ppm, x, y + 1, r.uniform(0.02, 0.05) * (0.6 + a), 0.55 * a ** 0.6, key + ("bl", x, y))
        if room > 0.05 * ppm:
            ok, info = stamp_run(acc, mask, ppm, x, y + 1, min(room / ppm, r.uniform(0.15, 1.2) * (0.5 + a)),
                                 0.012, r.uniform(0.02, 0.05), 0.55 * a ** 0.6, key + ("rr", x, y), striate=0.2)
            if ok:
                marks.append(info)
    return np.clip(acc, 0, 0.9), None, marks


def layer_efflorescence(plane, F, cfg, a, key, cracks=None):
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    if a <= 0:
        return acc, None, []
    srcs = list(plane.get("joints", []))
    if cracks is not None:
        ys, xs = np.nonzero(cracks > 0.3)
        if ys.size:
            r = nz.rng(*key, "cr")
            pick = r.choice(ys.size, size=min(ys.size, int(40 * a) + 1), replace=False)
            srcs += [(int(ys[i]), int(xs[i])) for i in pick]
    cls = plane.get("cls")
    for i, (y, x) in enumerate(srcs):
        r = nz.rng(*key, "ef", i)
        if r.random() > 0.15 + 0.6 * a:
            continue
        if cls is not None and cls[min(y + 2, H - 1), min(x, W - 1)] in (4, 5):
            continue                      # no light runs on dark substrates (G2)
        room = region_below(mask, y + 1, x, H)
        if room < 0.03 * ppm:
            continue
        stamp_run(acc, mask, ppm, x, y + 1, min(room / ppm, r.uniform(0.04, 0.35)), r.uniform(0.01, 0.04),
                  r.uniform(0.03, 0.09), 0.35 * a ** 0.7, key + ("ef", i), striate=0.4, tail=0.4)
    return np.clip(acc, 0, 0.7), None, []


def layer_cracks(plane, F, cfg, a, key):
    """Hairline cracks from re-entrant corners of openings and, with age, map cracks on large
    faces: a dark line with a dirt halo."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    if a <= 0:
        return acc, None, []
    starts = list(plane.get("reentrant", []))
    r = nz.rng(*key, "map")
    area = mask.sum() / ppm ** 2
    nmap = int(a ** 1.5 * area / 60.0)
    ys, xs = np.nonzero(mask)
    if ys.size:
        for i in range(nmap):
            j = r.integers(ys.size)
            starts.append((int(ys[j]), int(xs[j])))
    for i, (y, x) in enumerate(starts):
        rr = nz.rng(*key, "ck", i)
        if rr.random() > 0.3 + 0.7 * a:
            continue
        L = rr.uniform(0.3, 1.5) * (0.6 + a) * ppm
        ang = rr.uniform(-1.1, 1.1) + np.pi / 2
        px, py = float(x), float(y)
        for s in range(int(L)):
            ang += rr.normal(0, 0.12)
            px += np.cos(ang)
            py += abs(np.sin(ang)) * 0.9 + 0.1
            ix, iy = int(px), int(py)
            if not (0 <= iy < H and 0 <= ix < W) or not mask[iy, ix]:
                break
            acc[iy, ix] = max(acc[iy, ix], 0.55 * (1 - s / L) ** 0.3)
            if ix + 1 < W:
                acc[iy, ix + 1] = max(acc[iy, ix + 1], 0.15 * (1 - s / L))
    return np.clip(acc, 0, 0.8), None, []


def layer_wear(plane, F, cfg, a, key):
    """Worn arrises: broken runs of light older paint along exposed edges (half to two thirds of
    each edge clean). Not on dark substrates, where it would read as light streaks (G2)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    if a <= 0 or "edges" not in plane:
        return np.zeros((H, W), F32), None, []
    e = plane["edges"].astype(F32)
    cls = plane.get("cls")
    if cls is not None:
        e = e * ~np.isin(cls, (4, 5))
    brk = nz.gfield((H, W), 0.25 * ppm, key + ("brk",))
    keep = brk > np.quantile(brk, 0.55 - 0.15 * a)
    k = max(1, int(0.02 * ppm))
    w = e.copy()
    for s in range(1, k + 1):
        f = 1 - s / (k + 1)
        w[s:, :] = np.maximum(w[s:, :], e[:-s, :] * f)
        w[:, s:] = np.maximum(w[:, s:], e[:, :-s] * f)
        w[:, :-s] = np.maximum(w[:, :-s], e[:, s:] * f)
    return (0.5 * a * w * keep * mask).astype(F32), None, []


def layer_damage(plane, F, cfg, a, key):
    """Chips and spalls along exposed edges at up to eight size levels (K1): the largest radius
    doubles every 0.25 of the amount (0.09 m at 0.25 ... 0.72 m at 1.0); hotspots from the cause
    field with the largest break at the centre and smaller ones around it (K3); a background of
    micro chips. Each break: a sharp outline over exposed concrete with a rough recessed floor
    (K4). Returns alpha, cavity, marks, depth (m) and the exposed concrete's tone x grain."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    sub = np.zeros((H, W), F32)
    cav = np.zeros((H, W), F32)
    dep = np.zeros((H, W), F32)
    tone = np.ones((H, W), F32)
    bar = np.zeros((H, W), F32)
    gk = np.full((H, W), 0.06, F32)
    spall_low = []
    marks = []
    if a <= 0 or "edges" not in plane:
        return sub, cav, marks, dep, tone, bar, spall_low
    ys, xs = np.nonzero(plane["edges"])
    if ys.size == 0:
        return sub, cav, marks, dep, tone, bar, spall_low
    rmax = 0.045 * 2.0 ** (4.0 * a)
    rmax1 = 0.045 * 2.0 ** 4.0                       # at amount 1: fixes where satellites sit
    rmin = 0.006
    edge_len = ys.size / ppm
    nhot = max(1, int(edge_len / 40.0 * (0.5 + 3.0 * a)))
    cw = F.C[ys, xs].astype(np.float64) ** 1.5
    # hotspots in a fixed order of priority: the ones at a lower amount are the first of those at a
    # higher amount, so the control grows damage where it was
    pri = np.log(np.maximum(cw, 1e-30)) + nz.rng(*key, "hotpri").gumbel(size=ys.size)
    hots = np.argsort(-pri)[:min(nhot, ys.size)]
    grow = 0.6 + 0.8 * a
    chips = []
    for n_h, hi in enumerate(hots):
        rh = nz.rng(*key, "hot", int(n_h))
        hy, hx = int(ys[hi]), int(xs[hi])
        u0, X, un = rh.uniform(0.85, 1.0), rh.pareto(1.4), rh.uniform(0.6, 1.4)
        if n_h == 0:                                   # the plane's largest break
            R, R1 = rmax * u0, rmax1 * u0
        else:                                          # most hotspots are runs of small bites
            R, R1 = min(rmax, 0.012 * grow * (1.0 + X)), min(rmax1, 0.012 * 1.4 * (1.0 + X))
        chips.append((hy, hx, R, 0.0, n_h, ("h", int(n_h))))
        n_sat = int((4 + 40 * a) * min(1.0, R / 0.04) ** 0.5 * un)
        n_max = max(1, int(44 * min(1.0, R1 / 0.04) ** 0.5 * un))
        spread = 0.75 * max(R1 / 0.04, 0.25) ** 0.3   # the run's full length at amount 1
        band = np.flatnonzero(np.abs(ys - hy) < 0.5 * ppm + 1.3 * spread * ppm)
        if band.size == 0:
            continue
        ext = max(1.2 * spread * (min(n_sat, n_max) / n_max) ** 1.3, 0.02)   # the run's length now
        for k in range(min(n_sat, n_max)):
            rs = nz.rng(*key, "hot", int(n_h), "sat", k)
            d = 1.2 * spread * ((k + rs.uniform()) / n_max) ** 1.3     # outwards with k
            near = 3.5 * np.exp(-2.0 * d / ext) + 0.25                # smaller further from the centre
            cap = 0.7 * R * np.exp(-1.2 * d / ext) * rs.uniform(0.45, 1.0)   # an envelope, not a law
            rk = min(cap, rmin * (1.0 + rs.pareto(1.3)) * near)       # power law under the main break
            side = rs.choice([-1, 1])
            jit = rs.random(band.size)
            if rk < rmin:
                continue
            tx = hx + side * d * ppm
            sel = band[np.abs(ys[band] - hy) < 0.5 * ppm + d * ppm]
            if sel.size == 0:
                continue
            j = sel[np.argmin(np.abs(xs[sel] - tx) + jit[:sel.size] * 3)]
            chips.append((ys[j], xs[j], rk, d, n_h, ("s", int(n_h), k)))
    # background chipping on an area budget: 25 % of the hotspots' area (K3 share ~0.8 at any amount)
    hot_area = sum(np.pi * c[2] ** 2 for c in chips)
    rb_ = nz.rng(*key, "bg")
    acc_a, k = 0.0, 0
    bcap = min(0.10, 0.15 * rmax)
    while acc_a < 0.25 * hot_area and k < 200000:
        j = rb_.integers(ys.size)
        rb = min(rmin * (1.0 + rb_.pareto(1.3)), bcap)
        chips.append((ys[j], xs[j], rb, -1.0, -1, ("b", k)))
        acc_a += np.pi * rb * rb
        k += 1
    # breaks under a pixel add their area as coverage: micro chipping reads as flecks of varying
    # strength, not as a row of equal dots
    sy, sx, sc, sd = [], [], [], []
    for cy, cx, rk, d, kh, cid in chips:
        Rp = rk * ppm
        if Rp < 0.75:
            sy.append(cy)
            sx.append(cx)
            sc.append(min(0.95, np.pi * Rp * Rp))
            sd.append(chip_depth(rk))
        else:
            res = stamp_break(sub, dep, tone, cav, ppm, cx, cy, rk, chip_depth(rk), key + ("chip",) + cid,
                              edge_angle(plane["edges"], cy, cx), bar=bar, gk=gk, mask=mask)
            if res is None:
                continue
            if res["low"] is not None:
                spall_low.append((res["low"][0], res["low"][1], float(rk)))
        marks.append({"y": int(cy), "x": int(cx), "r_m": float(rk), "eqd_m": 2 * float(rk), "d_m": float(d),
                      "k": int(kh)})
    if sy:
        sy, sx = np.asarray(sy, np.int64), np.asarray(sx, np.int64)
        sc, sd = np.asarray(sc, np.float64), np.asarray(sd, np.float64)
        lg = np.zeros((H, W), np.float64)
        np.add.at(lg, (sy, sx), np.log1p(-sc))
        sub = (1.0 - (1.0 - sub) * np.exp(lg)).astype(F32)
        dm = np.zeros((H, W), F32)
        np.maximum.at(dm, (sy, sx), (sd * sc).astype(F32))
        dep = np.maximum(dep, dm)
    grain = nz.gfield((H, W), 0.6, key + ("grain",)).astype(F32)     # aggregate and fines, 1-2 cm
    tone = (tone * (1.0 + gk * grain)).astype(F32)
    return sub * mask, cav * mask, marks, dep * mask, tone, bar * mask, spall_low


def layer_repaint(plane, n, key):
    """Repaint patches bounded by features: on a front, the parapet run of 1-2 units on one floor
    (one household's balcony front redone); on a gable or tower, the full width between two floor
    joints over 1-2 floors (a repair from a gondola). Inside, the soiling has restarted (x 0.7
    of the wall's) and the paint is 1-1.5 % off in value; edges feathered over 3 cm."""
    mask = plane["mask"]
    H, W = mask.shape
    ppm = plane["ppm"]
    m = np.zeros((H, W), F32)
    if n <= 0:
        return m, []
    r = nz.rng(*key, "rp")
    fr, bc = sorted(plane.get("floor_rows") or []), plane.get("bay_cols") or []
    rects = []
    for i in range(n):
        if len(fr) < 3:
            break
        f0 = int(r.integers(1, len(fr) - 1))
        nf = 1 + int(r.random() < 0.4 and plane.get("kind") != "front")
        y0, y1 = fr[max(0, f0 - nf)], fr[f0]
        if plane.get("kind") == "front" and len(bc) > 2:
            b0 = int(r.integers(0, len(bc) - 1))
            x0, x1 = bc[b0], bc[min(len(bc) - 1, b0 + 1 + int(r.random() < 0.3))]
        else:
            cols = np.flatnonzero(mask.any(axis=0))
            x0, x1 = int(cols[0]), int(cols[-1]) + 1
        m[min(y0, y1):max(y0, y1), x0:x1] = 1.0
        rects.append((int(y0), int(y1), int(x0), int(x1)))
    from weather_measure import gauss
    m = np.clip(gauss(m, 0.015 * ppm), 0, 1).astype(F32)
    return m * mask, rects


# ---------------------------------------------------------------------------------------------
# compositing

def down2(a):
    """2 x 2 block mean (float arrays, 2D or HxWx3), cropped to even size."""
    H, W = a.shape[:2]
    h, w = H // 2, W // 2
    b = np.asarray(a[:2 * h, :2 * w], np.float32).reshape((h, 2, w, 2) + a.shape[2:])
    return b.mean(axis=(1, 3)).astype(F32)


def _lerp(A, col, alpha):
    col = np.asarray(col, F32)
    if col.ndim == 1:
        col = col[None, None, :]
    return A + (col - A) * alpha[..., None]


def composite(plane, base_rgb, L):
    """Apply the layers over the clean albedo. Returns weathered RGB, D, and L_<layer> maps (each
    layer alone over clean). On dark substrates, chips expose fresher concrete of the same tone
    rather than a light colour (G2)."""
    A = base_rgb.astype(F32).copy()
    Y0 = np.maximum(luminance(base_rgb), 1e-4).astype(F32)
    Lm = {}
    if "fading" in L:
        f = L["fading"]["alpha"]
        grey = luminance(A)[..., None]
        A = (A + (grey - A) * 0.18 * f[..., None]) * (1.0 + 0.035 * f[..., None])
        Lm["fading"] = 1 - luminance(A) / Y0
    if "repaint" in L:
        m, d = L["repaint"]["alpha"], L["repaint"]["shift"]
        A2 = A * (1.0 + d * m)[..., None]
        Lm["repaint"] = 1 - luminance(A2) / Y0 - Lm.get("fading", 0)
        A = A2
    for name in ("soiling", "stains", "streaks", "base", "bio", "rust", "cracks", "efflorescence"):
        if name not in L:
            continue
        al = L[name]["alpha"]
        if "repaint" in L and name in ("soiling", "streaks", "stains"):
            al = al * (1.0 - 0.30 * L["repaint"]["alpha"])
        col = L[name].get("colour")
        if col is None:
            col = COL.get(name, COL["soiling"])
        Lm[name] = 1 - luminance(_lerp(base_rgb, col, al)) / Y0
        A = _lerp(A, col, al)
    for name in ("peeling", "wear"):
        if name in L:
            al = L[name]["alpha"]
            Lm[name] = 1 - luminance(_lerp(base_rgb, COL["old_paint"], al)) / Y0
            A = _lerp(A, COL["old_paint"], al)
    if "damage" in L:
        sub, cav = L["damage"]["alpha"], L["damage"]["cavity"]
        cls = plane.get("cls")
        subcol = np.broadcast_to(np.array(COL["substrate"], F32), A.shape).copy()
        if cls is not None:
            dark = np.isin(cls, (4, 5))
            subcol[dark] = base_rgb[dark] * 1.10          # fresh break of a dark concrete: same tone
        if L["damage"].get("tone") is not None:           # each break's own tone, the aggregate's grain
            subcol = subcol * L["damage"]["tone"][..., None]
        A2 = A + (subcol - A) * sub[..., None]
        A2 = _lerp(A2, COL["crack"], cav)
        B2 = base_rgb + (subcol - base_rgb) * sub[..., None]
        B2 = _lerp(B2, COL["crack"], cav)
        if L["damage"].get("bar") is not None:            # the bar and its rust in a deep spall
            A2 = _lerp(A2, COL["rust_bar"], L["damage"]["bar"])
            B2 = _lerp(B2, COL["rust_bar"], L["damage"]["bar"])
        Lm["damage"] = 1 - luminance(B2) / Y0
        A = A2
    D = 1 - luminance(A) / Y0
    return A, D.astype(F32), {k: np.asarray(v, F32) for k, v in Lm.items()}


# ---------------------------------------------------------------------------------------------
# building and the budget solver

class Builder:
    """Builds every plane for one configuration and solves two gains so that the composite
    coverage by tier lands in the A1 bands for the configuration's E: 'soiling' scales the film
    (it sets T1+/T2+), 'accent' scales streaks and stains (T3+..T5+)."""

    def __init__(self, planes, cfg, bases, rules=None):
        self.planes, self.cfg, self.bases = planes, cfg, bases
        self.R, self.E, self.a = auto_amounts(cfg)
        self.rules = rules or json.load(open(RULES, encoding="utf-8"))
        self.F = {p["name"]: PlaneFields(p, cfg) for p in planes}
        self.soil_field = {p["name"]: soiling_field(p, self.F[p["name"]], cfg, self.E) for p in planes}
        self.k = max(self.a["film_k"], 0.02)
        self.fixed = {}
        self.accent_cache = {}
        self.bio_cache = {}
        self.half = {}

    def key(self, layer, p):
        return (self.cfg["seed"], layer, p["name"])

    def _fixed_layers(self, p):
        """Layers the solver does not scale: base, bio (needs stains: computed with the accent
        layers), rust, cracks, efflorescence, wear, damage, repaint, fading."""
        n = p["name"]
        if n in self.fixed:
            return self.fixed[n]
        F, a, cfg = self.F[n], self.a, self.cfg
        L, marks = {}, {}
        al, col, _ = layer_base(p, F, cfg, a["base"], self.key("base", p))
        L["base"] = {"alpha": al, "colour": col}
        sub, cav, mk, dep, tone, bar, spl = layer_damage(p, F, cfg, a["damage"], self.key("damage", p))
        L["damage"] = {"alpha": sub, "cavity": cav, "depth": dep.astype(np.float16), "tone": tone, "bar": bar}
        marks["damage"] = mk
        al, _, _ = layer_rust(p, F, cfg, a["rust"], self.key("rust", p), spalls=spl)
        L["rust"] = {"alpha": al}
        al, _, _ = layer_cracks(p, F, cfg, a["cracks"], self.key("cracks", p))
        L["cracks"] = {"alpha": al, "colour": COL["crack"]}
        al2, _, _ = layer_efflorescence(p, F, cfg, a["efflorescence"], self.key("efflorescence", p), cracks=al)
        L["efflorescence"] = {"alpha": al2}
        al, _, _ = layer_wear(p, F, cfg, a["wear"], self.key("wear", p))
        L["wear"] = {"alpha": al}
        rp, _ = layer_repaint(p, a["repaint_patches"], self.key("repaint", p))
        L["repaint"] = {"alpha": rp, "shift": float(nz.rng(self.cfg["seed"], "rpshift", n).uniform(-0.015, 0.015))}
        if p.get("face_sun", 0) > 0 and a["fading"] > 0:
            fad = a["fading"] * p["face_sun"] * (0.85 + 0.3 * nz.fbm(p["mask"].shape, p["ppm"], [0, 1, 2],
                                                                    self.key("fading", p)))
            L["fading"] = {"alpha": (np.clip(fad, 0, 1) * p["mask"]).astype(F32)}
        self.fixed[n] = (L, marks)
        return self.fixed[n]

    def _accent_layers(self, p, g):
        k = (p["name"], round(g, 3))
        if k in self.accent_cache:
            return self.accent_cache[k]
        F, a, cfg = self.F[p["name"]], self.a, self.cfg
        L, marks = {}, {}
        best = None
        for draw in range(5):
            sfx = ("draw", draw) if draw else ()
            al, _, mks = layer_stains(p, F, cfg, min(1.0, a["stains"] * g), self.key("stains", p) + sfx)
            al2, col, mkr = layer_streaks(p, F, cfg, min(1.0, a["streaks"] * g), self.key("streaks", p) + sfx)
            ratio = flow_top_ratio(p, al + al2)
            if best is None or ratio > best[0]:
                best = (ratio, al, mks, al2, col, mkr)
            if ratio >= 1.45:
                break
        _r, al, mks, al2, col, mkr = best
        L["stains"] = {"alpha": al}
        marks["stains"] = mks
        L["streaks"] = {"alpha": al2, "colour": col}
        marks["streaks"] = mkr
        if p["name"] not in self.bio_cache:
            ref = al if abs(g - 1.0) < 1e-3 else layer_stains(p, F, cfg, min(1.0, a["stains"]), self.key("stains", p))[0]
            self.bio_cache[p["name"]] = layer_bio(p, F, cfg, a["bio"], self.key("bio", p), stains=ref)[:2]
        alb, colb = self.bio_cache[p["name"]]
        L["bio"] = {"alpha": alb, "colour": colb}
        self.accent_cache[k] = (L, marks)
        while len(self.accent_cache) > 2 * len(self.planes):        # keep memory bounded
            self.accent_cache.pop(next(iter(self.accent_cache)))
        return self.accent_cache[k]

    def _half(self, p):
        """Half-resolution base albedo, painted mask and classes of a plane (cached)."""
        n = p["name"]
        if n not in self.half:
            H, W = p["mask"].shape
            h, w = H // 2, W // 2
            self.half[n] = {"base": down2(self.bases[n]), "cls": p["cls"][:2 * h:2, :2 * w:2],
                            "wall": down2((p["mask"] & np.isin(p["cls"], (1, 2))).astype(F32)) >= 0.999}
        return self.half[n]

    def build(self, gs, ga, fast=False):
        out = {}
        for p in self.planes:
            n = p["name"]
            Lf, mf = self._fixed_layers(p)
            La, ma = self._accent_layers(p, ga)
            tone, dev, ck = self.soil_field[n]
            soil = layer_soiling(film_of(tone, dev, self.k, ck), self.a["soiling"] * gs)
            L = {}
            for k, v in list(Lf.items()) + list(La.items()) + [("soiling", {"alpha": soil})]:
                if fast:
                    L[k] = {kk: (down2(vv) if isinstance(vv, np.ndarray) and vv.ndim >= 2 else vv) for kk, vv in v.items()}
                else:
                    L[k] = v
            if fast:
                hp = self._half(p)
                rgb, D, Lm = composite({"cls": hp["cls"]}, hp["base"], L)
            else:
                rgb, D, Lm = composite(p, self.bases[n], L)
            out[n] = {"rgb": rgb, "D": D, "L": Lm, "layers": L, "marks": {**mf, **ma}, "step": 2 if fast else 1}
        return out

    def coverage(self, out):
        """(tone, local tier coverage T2+..T6+) over the exposed painted walls, as the gate measures."""
        import weather_measure as wm
        tone, loc, mk = [], [], []
        for p in self.planes:
            if not p.get("exposed", True):
                continue
            o = out[p["name"]]
            st = o.get("step", 1)
            if st == 2:
                hp = self._half(p)
                m, base = hp["wall"], hp["base"]
            else:
                m, base = p["mask"] & np.isin(p["cls"], (1, 2)), self.bases[p["name"]]
            D = o["D"]
            tone.append(np.clip(D[m], -1.0, 1.0))
            Y = 1.0 - D                                    # the weathering's own local contrast
            Dl, lpp = wm.local_contrast_D(Y, m, p["ppm"] / st)
            loc.append(Dl[np.isfinite(Dl)])
            mk += [q for q in wm.marks(Dl, lpp, thr=TIER_EDGES[2]) if q["eqd_m"] >= 0.5]
        if mk:
            big = np.array([q["cv"] for q in mk if q["eqd_m"] >= 2.0])
            self._b2 = (float(np.median([q["cv"] for q in mk])),
                        float(np.percentile(big, 10)) if big.size else 1.0,
                        float(np.mean([q["tiers_spanned"] >= 3 for q in mk])),
                        float(np.median(big)) if big.size else 1.0, float(big.min()) if big.size else 1.0)
        else:
            self._b2 = (1.0, 1.0, 1.0, 1.0, 1.0)
        t = np.concatenate(tone)
        v = np.concatenate(loc)
        return [float(t.mean())] + [float((v >= x).mean()) for x in TIER_EDGES[1:]]

    def targets(self):
        R = self.rules
        bands = []
        lo = float(np.interp(self.E, R["tone"]["E"], [b[0] for b in R["tone"]["mean_D"]]))
        hi = float(np.interp(self.E, R["tone"]["E"], [b[1] for b in R["tone"]["mean_D"]]))
        bands.append((lo, hi))
        cov = R["coverage"]
        for t in ("T2+", "T3+", "T4+", "T5+", "T6+"):
            lo = float(np.interp(self.E, cov["E"], [b[0] for b in cov[t]]))
            hi = float(np.interp(self.E, cov["E"], [b[1] for b in cov[t]]))
            bands.append((lo, hi))
        return bands

    def solve(self, log=None, fixed_gains=None):
        """Soiling gain: bisection on the tone (A0, middle of its band). Film contrast k and accent
        gain: golden-section searches minimising the tiers' normalised distance from their band
        middles, sum z^2 + 10 x sum max(0, |z| - 0.7)^2 with z = log(cov / mid) / log(hi / mid).
        k and the accent gain stay within 0.4-2.5 x and 0.6-1.6 x their defaults. Two rounds at half
        resolution, a full-resolution bias measurement, a last round on corrected coverage."""
        if fixed_gains is not None:
            gs, ga = fixed_gains[:2]
            if len(fixed_gains) > 2:
                self.k = fixed_gains[2]
            return gs, ga, self.build(gs, ga)
        if self.E <= 0.5:
            return 1.0, 1.0, self.build(1.0, 1.0)
        tb = self.targets()
        ov = self.cfg.get("override", {})
        k0 = max(self.a["film_k"], 0.02)
        self.bias = [1.0] * 6
        state = {"gs": 1.0, "ga": 1.0}

        def cov(gs, ga, k):
            self.k = k
            c = self.coverage(self.build(gs, ga, fast=True))
            return [x * b for x, b in zip(c, self.bias)]

        def zs(c):
            out = []
            for i, (lo, hi) in enumerate(tb):
                lo, hi = max(lo, 1e-4), max(hi, 2e-4)
                mid = np.sqrt(lo * hi)
                out.append(float(np.log(max(c[i], 1e-5) / mid) / np.log(hi / mid)))
            return out

        b_med, b_p10, b_min = (0.33, 0.25, 0.20) if self.E >= 25 else (0.40, 0.33, 0.25)

        def cost(c):
            z = zs(c)[1:]
            t = sum(x * x for x in z) + 10.0 * sum(max(0.0, abs(x) - 0.7) ** 2 for x in z)
            med, p10, span, bmed, bmin = getattr(self, "_b2", (1.0,) * 5)   # B2, from the same build
            t += (max(0.0, 0.34 - med) / 0.02) ** 2 + (max(0.0, 0.64 - span) / 0.03) ** 2
            t += (max(0.0, b_med + 0.03 - bmed) / 0.02) ** 2 + (max(0.0, b_p10 + 0.03 - p10) / 0.02) ** 2
            t += (max(0.0, b_min + 0.03 - bmin) / 0.02) ** 2
            return t

        def golden(f, lo, hi, n):
            a, b = np.log(lo), np.log(hi)
            g = (np.sqrt(5.0) - 1.0) / 2.0
            c, d = b - g * (b - a), a + g * (b - a)
            fc, fd = f(float(np.exp(c))), f(float(np.exp(d)))
            for _ in range(n):
                if fc < fd:
                    b, d, fd = d, c, fc
                    c = b - g * (b - a)
                    fc = f(float(np.exp(c)))
                else:
                    a, c, fc = c, d, fd
                    d = a + g * (b - a)
                    fd = f(float(np.exp(d)))
            return float(np.exp(c if fc < fd else d))

        def round_():
            gs, ga = state["gs"], state["ga"]
            k = self.k
            if "soiling" not in ov:
                lo, hi = np.log(0.05), np.log(20.0)
                lo0, hi0 = tb[0]
                mid0 = np.sqrt(max(lo0, 1e-5) * max(hi0, 1e-5))
                for _ in range(9):
                    m = 0.5 * (lo + hi)
                    c = cov(float(np.exp(m)), ga, k)
                    if log is not None:
                        log.append(("soiling", float(np.exp(m)), c))
                    if c[0] < mid0:
                        lo = m
                    else:
                        hi = m
                gs = float(np.exp(0.5 * (lo + hi)))
            if "film_k" not in ov:
                def fk(kk):
                    c = cov(gs, ga, kk)
                    if log is not None:
                        log.append(("film_k", kk, c, cost(c)))
                    return cost(c)
                k = golden(fk, 0.4 * k0, 2.5 * k0, 6)
            else:
                k = ov["film_k"]
            if "streaks" not in ov and "stains" not in ov:
                def fa(g):
                    c = cov(gs, g, k)
                    if log is not None:
                        log.append(("accent", g, c, cost(c)))
                    return cost(c)
                ga = golden(fa, 0.6, 1.6, 5)
            self.k = k
            state["gs"], state["ga"] = gs, ga

        self.k = k0
        round_()
        round_()
        gs, ga = state["gs"], state["ga"]
        full = self.coverage(self.build(gs, ga))
        self.bias = [1.0] * 6
        half = self.coverage(self.build(gs, ga, fast=True))
        self.bias = [f / h if h > 1e-4 else 1.0 for f, h in zip(full, half)]
        if log is not None:
            log.append(("bias", self.bias, full))
        round_()
        gs, ga = state["gs"], state["ga"]
        out = self.build(gs, ga)
        self.coverage(out)                            # full resolution: B2 as the gate measures it
        if self._b2_fails():
            k_best = self.k
            for f in (0.85, 0.72, 1.18):
                self.k = k_best * f
                o2 = self.build(gs, ga)
                c2 = self.coverage(o2)
                if log is not None:
                    log.append(("b2_check", self.k, c2, list(self._b2)))
                if not self._b2_fails() and max(abs(z) for z in zs(c2)) <= 1.0:      # tone and tiers in band
                    return gs, ga, o2
            self.k = k_best
            out = self.build(gs, ga)
        return gs, ga, out

    def _b2_fails(self):
        """B2 at the gate's thresholds, from the last coverage() call."""
        med, p10, span, bmed, bmin = getattr(self, "_b2", (1.0,) * 5)
        b_med, b_p10, b_min = (0.33, 0.25, 0.20) if self.E >= 25 else (0.40, 0.33, 0.25)
        return med < 0.30 or span < 0.60 or bmed < b_med or p10 < b_p10 or bmin < b_min
