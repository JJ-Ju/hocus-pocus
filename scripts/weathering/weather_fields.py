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
    "bio_G1": (0.573, 0.514, 0.355),        # first greening, just visible (b* up first)
    "bio_G2": (0.473, 0.445, 0.247),        # young light-green film
    "bio_G2y": (0.567, 0.381, 0.203),       # dull or rusty-yellow young growth
    "bio_G3": (0.276, 0.297, 0.143),        # established green, damp
    "bio_G4": (0.088, 0.100, 0.042),        # severe dark green / olive
    "bio_G4r": (0.133, 0.068, 0.036),       # severe rust-brown (Trentepohlia + dirt)
    "bio_Tr": (0.46, 0.28, 0.16),           # Trentepohlia orange-rust, muted by dirt (round G)
    "bio_Cy": (0.061, 0.052, 0.048),        # cyanobacterial ink stripe
    "bio_Fu": (0.042, 0.041, 0.037),        # black fungal speckle
    "bio_dry": (0.52, 0.42, 0.22),          # dry film: lighter, less chromatic, hue toward 90 deg (research 4)
    "bio_dry_g": (0.482, 0.431, 0.219),     # dry green film: L 71, hue 99 deg (from 103-115)
    "bio_dry_r": (0.566, 0.405, 0.220),     # dry rusty film: L 71, hue 81 deg (from 62-77)
    "bio_Y1": (0.568, 0.403, 0.179),        # young yellow growth, lichen-like: L 71, a* +3, b* +31 (round H)
    "bio_Y3": (0.412, 0.262, 0.090),        # established ochre-yellow: L 60, a* +5, b* +34
    "bio_Y4": (0.221, 0.142, 0.053),        # old yellow growth, dark ochre-olive: L 46, a* +4, b* +26
    "film_g": (0.078, 0.184, 0.063),        # dark green marks (mildew and algae in the run-off): L 46, a* -24, b* +22
    "film_g_old": (0.036, 0.085, 0.033),    # older: darker green, L 32, a* -18, b* +15 (darkens with age)
    "film_y": (0.558, 0.429, 0.157),        # yellow-ochre marks: L 72, a* -1, b* +36 (hue 92 deg: yellow, not rust)
    "film_y_old": (0.452, 0.314, 0.103),    # older, deeper: L 64, a* +2, b* +36
    "rust": (0.24, 0.105, 0.042),
    "efflorescence": (0.78, 0.78, 0.75),
    "substrate": (0.51, 0.51, 0.495),
    "rust_bar": (0.13, 0.062, 0.028),
    "old_paint": (0.70, 0.69, 0.64),
    "old_coat": (0.6923, 0.634, 0.5545),   # J21: the coat under a flake, a pale cream (L* 84, a* 0.8, b* 7.0)
    "edge_chalk": (0.83, 0.82, 0.78),       # chalked, rain-washed top arris
    "edge_dirt": (0.292, 0.256, 0.203),     # dirt on drip and lower edges: darker, warm (b* +9; N5 at 1.3x contrast)
    "crack": (0.05, 0.046, 0.040),
}

# auto amounts by the soiling clock E (anchors: new, kept, typical, worn, neglected)
AUTO_E = [0.0, 10.75, 14.5, 19.8, 27.1]
AUTO = {
    "soiling": [0.0, 0.22, 0.30, 0.50, 0.80],        # Typical at the user's grime pick (round F)
    "streaks": [0.0, 0.30, 0.42, 0.62, 0.85],
    "stains": [0.0, 0.02, 0.08, 0.30, 0.60],         # round I: the user picked 0 stain fields at Typical (rounds G and H)
    "base": [0.0, 0.15, 0.28, 0.55, 0.92],           # the ground band comes in gently (round F)
    "bio": [0.0, 0.25, 0.40, 0.72, 0.92],            # growth: years unattended = bio_years(a): 3.1, 4.5, 11, 18 (round I: Derelict spreads)
    "washed": [0.0, 0.08, 0.12, 0.22, 0.40],
    "film_k": [0.0, 0.55, 0.62, 0.85, 1.15],         # local contrast of the soiling film's water pattern
}
# age-driven layers (do not reset at a repaint)
AUTO_AGE = [0, 15, 35, 45, 60]
AUTO_A = {
    "rust": [0.0, 0.12, 0.30, 0.50, 0.75],
    "efflorescence": [0.0, 0.05, 0.18, 0.35, 0.55],
    "cracks": [0.0, 0.05, 0.20, 0.40, 0.60],
    "wear": [0.0, 0.08, 0.25, 0.45, 0.70],           # gentler early: 'excessive wear' at Kept (round F)
    "damage": [0.0, 0.18, 0.40, 0.62, 0.85],
    "peeling": [0.0, 0.0, 0.08, 0.30, 0.55],
    "fading": [0.0, 0.30, 0.45, 0.55, 0.65],
}
RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_rules.json")


CLOCK_PHASE = 0.665         # share of its repaint cycle a building is through, on average (round H)
CLOCK_KEEP = 0.17           # share of the dirt that each repaint leaves in the coat (round H)


def clock(age, upkeep):
    """The soiling clock: (R, E). The repaint cycle runs 7 years at upkeep 1 and 24 at 0. A building
    is on average CLOCK_PHASE of the way through it, R years since the last repaint, and CLOCK_KEEP
    of the dirt survives each repaint: E = R + CLOCK_KEEP x (age - R).

    Round H: rounds F and G both had the user pick the next-cleaner preset as the 35-year default.
    The old clock took R at the cycle's end with 0.22 kept, which made every age look one level too
    weathered. The new constants put 35 years at upkeep 0.9 on the old Kept look (E 10.75), upkeep
    0.5 on the old Typical (14.5) and 45 years at 0.12 on the old Worn (19.8), the user's rename."""
    cycle = 24.0 + (7.0 - 24.0) * upkeep
    r = min(age, CLOCK_PHASE * cycle)
    return r, r + CLOCK_KEEP * (age - r)


def auto_amounts(cfg):
    age, up = cfg["age"], cfg["upkeep"]
    R, E = clock(age, up)
    a = {k: float(np.interp(E, AUTO_E, v)) for k, v in AUTO.items()}
    care = 1.0 + 0.6 * (0.5 - up)                     # neglect pushes the age-driven layers
    for k, v in AUTO_A.items():
        a[k] = float(np.clip(np.interp(age, AUTO_AGE, v) * care, 0, 1))
    a["peeling"] *= float(np.clip((0.8 - up) / 0.6, 0, 1.5))
    if PEEL_BY_COAT:                        # round J: the coat's age decides (research coatings §2)
        a["peeling"] = float(np.interp(R, PEEL_COAT_R, PEEL_COAT_A))
    a["repaint_patches"] = 0                # off by default: a control (cfg override), not part of the presets
    for k, v in cfg.get("override", {}).items():
        a[k] = v
    ov = cfg.get("override", {})
    if "damage" in ov and "cracks" not in ov:   # the damage control carries the cracks (round G); rust is
        a["cracks"] = ov["damage"]              # its own control from round H
    return R, E, a


# ---------------------------------------------------------------------------------------------
# shared fields (cached per plane)

TEXDIR = os.environ.get("WX_TEX", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "examples", "danchi", "tex", "round_e"))
_TEX = {}


def material_map(name, channel, tile_m, ppm, shape, key=None):
    """A round-E material map (coat strength, roller laps, seams...) in facade space at its true
    size, as a float field. Weathering reads it so dirt follows the material (rule J2). With a key,
    sampled per plane by tile_blend (no 3.6 m repeat: grid-breakup R1); the clean base uses the
    same key, so the two stay aligned."""
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
    if key is not None:
        return nz.tile_blend(t, shape, key, t.shape[0])
    return t[(np.arange(H) % t.shape[0])[:, None], (np.arange(W) % t.shape[1])[None, :]]

LIFT_M = 1.8          # scaffold lift: the painters' working height, registered to the ground


def lap_rule(shape, ppm, ground_row, key, lift_m=LIFT_M, drop_m=(0.7, 1.3), w_px=1.5):
    """Roller laps by rule (grid-breakup R1): a horizontal lap at every scaffold lift, registered
    to the ground, and vertical laps at jittered spacing, independent per lift (staggered: no line
    runs through two lifts); lines bent a little. Scaled to the round-E lap map's mean (0.025)."""
    H, W = shape
    r = nz.rng(*key)
    lap = np.zeros(shape, np.float32)
    step = max(4, int(round(lift_m * ppm)))
    g0 = H - 1 if ground_row is None else int(ground_row)
    bend = nz.gfield((H, W), 0.8 * ppm, key + ("bend",)) * 0.03 * ppm
    for y in range(g0, -step, -step):
        ya, yb = max(0, y - step), max(0, y)
        if 0 <= y < H:
            lap[max(0, y - 1):y + 1] = 1.0
        x = r.uniform(0.0, drop_m[1]) * ppm
        while x < W and yb > ya:
            lap[ya:yb, int(x):int(x) + 2] = r.uniform(0.6, 1.0)
            x += r.uniform(*drop_m) * ppm
    yy = np.clip(np.arange(H)[:, None] + bend.astype(int), 0, H - 1)
    lap = lap[yy, np.arange(W)[None, :]]
    lap = wm_.gauss(lap, w_px)
    return (0.025 * lap / max(float(lap.mean()), 1e-9)).astype(F32)     # the round-E map's mean


def bay_factor(plane, key, sigma=0.40, smooth_m=0.3):
    """One random factor per bay (between bay divisions, or about 4 m segments on a plane without
    them), smoothed over smooth_m: a dirtier bay is the building's rhythm (grid-breakup R2)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size == 0:
        return np.zeros((1, W), F32)
    edges = sorted(int(c) for c in (plane.get("bay_cols") or []) if cols[0] < c < cols[-1])
    if not edges:
        n = max(1, int(round((cols[-1] - cols[0]) / (4.0 * ppm))))
        edges = [int(cols[0] + (cols[-1] - cols[0]) * k / n) for k in range(1, n)]
    edges = [0] + edges + [W]
    r = nz.rng(*key)
    v = np.zeros(W)
    for a, b in zip(edges[:-1], edges[1:]):
        v[a:b] = r.standard_normal()
    k = max(1, int(smooth_m * ppm))
    ker = np.exp(-0.5 * (np.arange(-3 * k, 3 * k + 1) / k) ** 2)
    v = np.convolve(np.pad(v, 3 * k, mode="edge"), ker / ker.sum(), mode="same")[3 * k:-3 * k]
    return (v[None, :] / max(v.std(), 1e-6)).astype(F32)



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
            c = nz.lognormal(sh, ppm, [0, 1, 2, 3], key + ("cause",), sigma=0.70, weights=[1.0, 1.0, 0.7, 0.12],
                             aniso=C_ANISO)
            cols = bay_factor(plane, key + ("cols",))                # a dirtier bay, not a random stripe
            c = c * np.exp(0.40 * np.clip(cols, -1.5, 2.5))
            macro = nz.lognormal(sh, ppm, [0, 1, 2], key + ("macro",), sigma=0.35)
            test = np.where(mask, c ** 0.6 * macro, np.nan)
            if _fields_ok(test, ppm) and _top_ok(np.where(mask, c, np.nan), plane):
                break
            self.redraws += 1
        self.key = key
        self.C = (c / c[mask].mean()).astype(F32)
        self.macro = (macro / macro[mask].mean()).astype(F32)
        ym = 1.1 * ppm                                            # 0.39 of a storey: floors do not repeat
        self.inner = nz.lognormal(sh, ppm, [4, 5, 6, 7], key + ("inner",), sigma=0.55,
                                  weights=[1.0, 1.0, 0.9, 0.8], aniso=(2.2, 1.0), ymax_px=ym).astype(F32)
        self.patt = nz.lognormal(sh, ppm, [3, 4, 5, 6, 7], key + ("patt",), sigma=1.0).astype(F32)
        self.biopatt = nz.lognormal(sh, ppm, [4, 5, 6, 7], key + ("biopatt",), sigma=1.0,
                                    weights=[0.5, 0.8, 1.0, 1.0], aniso=(4.0, 1.0), ymax_px=ym).astype(F32)   # along the run-off
        self.hgt = height01(plane).astype(F32)
        # mid variation (S4-S6, slightly vertical) and fine dust grain (S7-S8)
        self.mid = nz.lognormal(sh, ppm, [3, 4, 5], key + ("mid",), sigma=0.22, aniso=(4.0, 1.0), ymax_px=ym).astype(F32)
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
        warp = nz.gfield(sh, 0.9 * ppm, key + ("warp",)) * 0.06 * ppm            # restarts per storey (G-2)
        chan = nz.gfield(sh, 0.05 * ppm, key + ("chan",), aniso=(18.0, 1.0))
        xi = np.clip((np.arange(W)[None, :] + warp).astype(int), 0, W - 1)
        chan = chan[np.arange(H)[:, None], xi]
        self.chan = nz.smoothstep(-0.2, 1.4, chan).astype(F32)   # 0..1, about 30 % in channels
        # material response: coat strength and roller laps (painted), seams and voids (concrete)
        cls = plane.get("cls")
        self.mat = np.ones(sh, F32)
        try:
            coat = material_map("spraymacro_mask.png", 0, 3.6, ppm, sh, key=("coat", plane["name"]))
            lap = lap_rule(sh, ppm, plane.get("ground_row"), ("lap", plane["name"]))
            self.mat = (0.75 + 0.35 * coat + 0.25 * lap).astype(F32)
            if cls is not None:
                fm = material_map("formed_mask.png", 2, 3.6, ppm, sh, key=("formed", plane["name"]))   # seam band
                fv = material_map("formed_mask.png", 1, 3.6, ppm, sh, key=("formed", plane["name"]))   # voids
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

RUN_FIX = True              # round I (G1): runs stay on their paint segment; thin runs keep one connected trail
RUN_THIN_PX = 1.0           # half-width (px) under which a run is drawn on the pixel grid


def est_tail(u, est, L=None):
    """A run's fade exponent: u for an ordinary run; a long established run (round I) maps the same draw
    to EST_FADE, a slower fade, so it reads at its length (blended in over EST_FADE_L, m)."""
    if not est or EST_FADE is None:
        return u
    slow = EST_FADE[0] + (u - 0.35) / 0.45 * (EST_FADE[1] - EST_FADE[0])
    k = 1.0 if L is None else float(nz.smoothstep(EST_FADE_L[0], EST_FADE_L[1], L))
    return u + (slow - u) * k


def stamp_run(acc, mask, ppm, x0, y0, length_m, w0_m, w1_m, opacity, key, striate=0.35,
              wobble_m=0.02, profile_p=0.6, tail=0.5, lean_px=0.0):
    """One run (streak), darkest at its source and fading downward (F2), ragged edges, inner
    vertical striation, clipped to the surface, 'over' build-up."""
    H, W = acc.shape
    L = max(2, int(length_m * ppm))
    half = max(w0_m, w1_m) * ppm * 0.5 + wobble_m * ppm + 2 + abs(lean_px)
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
    cen = x0 + wob[:, None]
    if lean_px:                                                    # round I (G1): leaves its source, then drifts aside
        cen = cen + lean_px * nz.smoothstep(0.0, max(1.0, RUN_LEAN_M * ppm), yy - y0)
    thin = hw < RUN_THIN_PX                                        # round I (G1): thin runs on the pixel grid
    if RUN_FIX:
        cen = np.where(thin, np.round(cen), cen)
    dx = np.abs(xx - cen) / np.maximum(hw, 0.6)
    across = np.clip(1.0 - dx * dx, 0.0, 1.0) ** profile_p
    along = np.clip(1.0 - np.clip(t, 0, 1) ** tail, 0.0, 1.0)
    if striate > 0:
        k = max(1, int(0.015 * ppm))
        if RUN_FIX:                                                # striations move with the run, none on thin runs
            nh = int(half) + 4
            sw = r.normal(0, 1, (2 * nh + 1,))
            sw = np.convolve(sw, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
            sw = sw / (sw.std() + 1e-9)
            off = np.clip(xx - cen + nh, 0.0, 2 * nh - 1e-3)          # sub-pixel: no row-to-row jumps (G1)
            i0 = np.floor(off).astype(np.int64)
            fr = off - i0
            swv = sw[i0] * (1.0 - fr) + sw[np.minimum(i0 + 1, 2 * nh)] * fr
            st_k = striate * np.clip((hw - RUN_THIN_PX) / 2.0, 0.0, 1.0)
            stria = np.clip(1.0 + st_k * swv, 0.2, 1.8)
        else:
            sw = r.normal(0, 1, (xb - xa,))
            sw = np.convolve(sw, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
            sw = sw / (sw.std() + 1e-9)
            stria = np.clip(1.0 + striate * sw[None, :], 0.2, 1.8)
    else:
        stria = 1.0
    m_ = mask[ya:yb, xa:xb]
    a = opacity * across * along * stria * m_
    if RUN_FIX:
        # water stays on the paint it runs on: each row keeps the mask segment under the run's centre
        # (the nearest one when the centre sits on a frame or pipe)
        ww = xb - xa
        cc = np.clip(np.round(cen[:, 0] - xa).astype(np.int64), 0, ww - 1)
        ar = np.arange(ww)[None, :]
        lft = np.maximum.accumulate(np.where(m_, ar, -1), axis=1)
        rgt = np.minimum.accumulate(np.where(m_, ar, ww)[:, ::-1], axis=1)[:, ::-1]
        rows = np.arange(m_.shape[0])
        l_, r_ = lft[rows, cc], rgt[rows, cc]
        pick = np.where(m_[rows, cc], cc, np.where((cc - l_ <= r_ - cc) & (l_ >= 0), l_, np.where(r_ < ww, r_, cc)))
        brk = np.cumsum(~m_, axis=1)
        a = a * (brk == brk[rows, pick][:, None])
        # thin runs: bridge a sideways step so the trail stays 4-connected
        st_ = thin[:, 0] if thin.ndim == 2 and thin.shape[1] == 1 else thin.any(axis=1)
        step = np.flatnonzero(st_[1:] & (cc[1:] != cc[:-1])) + 1
        if step.size:
            a[step, cc[step - 1]] = np.maximum(a[step, cc[step - 1]], a[step, cc[step]] * m_[step, cc[step - 1]])
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
    lam = np.empty(xs.size)
    for y in np.unique(ys):                          # each top edge its own gap profile (grid-breakup R2)
        sel = ys == y
        g = nz.gfield((1, plane["mask"].shape[1]), 0.6 * ppm, key + ("gap", int(y)))[0]
        lam[sel] = np.exp(gap_sigma * g[xs[sel]] - gap_sigma ** 2 / 2)
    p = density_per_m / ppm * lam
    keep = r.random(ys.size) < np.clip(p, 0, 1)
    pts = sorted(zip(xs[keep].tolist(), ys[keep].tolist()))
    out, last = [], {}
    for x, y in pts:
        if y in last and x - last[y] < 0.06 * ppm:
            continue
        last[y] = x
        out.append((x, y))
    return out


def channel_columns(plane, F, a, key):
    """Columns where the wall channels water from top to bottom, in a fixed priority order (the
    first n at a lower amount are the first n at a higher one). Score: continuity of wall below
    the top x (vertical joint 3x, bay division 2x, plane end 2x) x the cause field at the top.
    One per 11 m at amount 0.25, one per 4 m at 1.0, at least 1.5 m apart."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    tr, gr = plane.get("top_row"), plane.get("ground_row")
    if a <= 0 or tr is None or gr is None or gr <= tr:
        return []
    cls = plane.get("cls")
    wall = mask & np.isin(cls, (1, 2, 4, 5)) if cls is not None else mask
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size == 0:
        return []
    jv = plane.get("joint_v")
    e = int(0.6 * ppm)
    top_c = np.maximum(np.array([F.C[min(H - 1, tr + int(0.3 * ppm)), x] for x in range(W)], np.float64), 1e-3)

    def weights(cont):
        w = np.clip(cont - 0.5, 0, None) ** 2                # water runs on where the wall is unbroken
        if jv is not None:
            w = w * (1.0 + 2.0 * (jv[tr:gr].sum(axis=0) > 0.3 * (gr - tr)))
        for c in plane.get("bay_cols") or []:
            lo, hi = max(0, int(c) - int(0.15 * ppm)), min(W, int(c) + int(0.15 * ppm) + 1)
            w[lo:hi] *= 2.0
        w[cols[0]:cols[0] + e] *= 2.0
        w[max(0, cols[-1] - e):cols[-1] + 1] *= 2.0
        return w * top_c

    line = np.zeros(W, np.float64)                                   # round I: water gathers in the vertical lines
    if jv is not None:
        line = np.maximum(line, (jv[tr:gr].sum(axis=0) > 0.3 * (gr - tr)).astype(np.float64))
    for c in plane.get("bay_cols") or []:
        line[max(0, int(c) - int(0.15 * ppm)):min(W, int(c) + int(0.15 * ppm) + 1)] = 1.0
    line[cols[0]:cols[0] + e] = 1.0
    line[max(0, cols[-1] - e):cols[-1] + 1] = 1.0
    for (_y, x_) in plane.get("corner_heads", []):
        line[max(0, int(x_) - 2):min(W, int(x_) + 3)] = 1.0
    lw = CH_LINE + (1.0 - CH_LINE) * line
    cw = wall[tr:gr].mean(axis=0).astype(np.float64)
    w_main = weights(cw) * lw                                        # the main path: solid wall (H4)
    if CH_MAIN_SOLID and (cw >= 0.95).any():
        w_main = np.where(cw >= 0.95, w_main, 0.0)                   # never across windows where solid wall exists
    w = weights(mask[tr:gr].mean(axis=0).astype(np.float64)) * lw    # the rest: on the lines first
    if w.max() <= 0:
        return []
    width_m = cols.size / ppm
    n = int(np.ceil(width_m / 25.0 * (CH_N[0] + CH_N[1] * a) - 0.2))
    g = nz.rng(*key, "chanpri").gumbel(size=W)
    out = []
    if w_main.max() > 0:
        out.append(int(np.argmax(np.log(np.maximum(w_main, 1e-30)) + g)))
    order = np.argsort(-(np.log(np.maximum(w, 1e-30)) + g))
    gap = 1.5 * ppm
    for x in order:
        if len(out) >= n or w[x] <= 0:
            break
        if all(abs(int(x) - o) >= gap for o in out):
            out.append(int(x))
    return out


def joint_crossings(plane):
    """Centres (y, x) where a horizontal and a vertical joint cross."""
    jh, jv = plane.get("joint_h"), plane.get("joint_v")
    if jh is None or jv is None:
        return []
    from weather_measure import label
    k = 2
    jvd = jv.copy()
    for s in range(1, k + 1):
        jvd[:, s:] |= jv[:, :-s]
        jvd[:, :-s] |= jv[:, s:]
    x_ = jh & jvd
    if not x_.any():
        return []
    lab, n = label(x_)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        out.append((int(round(ys.mean())), int(round(xs.mean()))))
    return out


def layer_streaks(plane, F, cfg, a, key, og=1.0):
    """Run-off streaks from features: low points along tops (fringe), sill ends (V fans), inside
    corners (wide), joints and fixings (narrow). Per source: power-law strength x cause field x
    driven rain x height (top floors 1.5-2.5x); lengths log-normal with a tail to the next catch;
    1-3 overlapping runs for build-up; colour by cause.

    Round I: `a` is the preset's own amount and sets the extent (sources, lengths, widths, channel
    count); the solver's gain `og` scales only the opacity, so a heavier preset's marks are larger,
    not just darker."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    damp = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    rain = plane.get("face_rain", 1.0)
    bias = 0.8 + 1.0 * cfg.get("exposure", 0.6)
    omax = (OMAX[0] + OMAX[1] * a) * og
    alpha = 1.75 - 0.25 * a                 # length tail: heavier with the amount, never below 1.5
    srcs = [(x, y, "top") for x, y in sources_along_tops(plane, key + ("tops",), TOP_DENS[0] + TOP_DENS[1] * a)]
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
        s *= {"sill": 1.6, "corner": 1.3, "joint": 0.45, "fixing": 0.6, "top": TOP_K[0]}.get(kind, 1.0)
        if r.random() > 0.35 + 0.65 * hgt[yy, xx] ** 1.2:  # driven rain wets the upper storeys more
            continue
        if s < 0.25 and r.random() > a * hf / 2.0:        # weak sources show on dirtier, higher walls
            continue
        nruns = 1 + int(r.random() < 0.35 + 0.4 * a) + int(r.random() < RUN3 * a)
        for j in range(nruns):
            rj = nz.rng(*key, "run", kind, x, y, j)
            # power law N(>L) ~ L^-1.5: each octave down holds 2.8x the runs (C3), few reach the
            # next drip edge, so a cap (the parapet's foot) does not pile them up
            Lm = 0.07 * (1.0 + 0.5 * a) * hf ** 0.5 * s ** 0.3 * (1.0 + rj.pareto(alpha))
            if kind == "top":                                # panel faces: short runs from the grooves
                Lm *= TOP_K[1]
            est_ = False
            if rj.random() < EST_SHARE[0] + EST_SHARE[1] * a:
                Lm = 0.8 * (1.0 + rj.pareto(EST_TAIL))         # an established run: 0.8 m up, power law
                est_ = True
            gw = CAP_WET * float(nz.smoothstep(0.40, 0.55, a))    # wetter walls: more and shorter stops (C3)
            if CAP_SHORT > 0 and Lm > room / ppm and rj.random() < CAP_SHORT + (0.95 - CAP_SHORT) * gw:
                Lm = room / ppm * rj.uniform(0.35 - 0.10 * gw, 0.9 - 0.30 * gw)   # most runs stop short of the next drip edge
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
            w0, w1 = w0 * (1.0 + RUN_WA * a), w1 * (1.0 + RUN_WA * a)   # wetter walls, wider runs
            op = omax * min(1.4, s) * rj.uniform(OP_LO, 1.0) * (0.75 if j else 1.0)
            op *= min(1.0, (Lm / 0.4) ** 0.4)               # a short drip is a little dirty water
            if rj.random() < 0.18 + 0.08 * a:                # layering: some runs much darker (round F)
                op *= rj.uniform(DARK_K[0], DARK_K[1]) * (1.0 + DARK_A * max(0.0, a - DARK_A0))
            if not j:
                dx = 0.0
            elif RUN_DX:                                     # the film divides: rivulets a few cm apart
                dx = rj.choice([-1.0, 1.0]) * rj.uniform(0.6, 1.4) * RUN_DX * ppm
            else:
                dx = rj.normal(0, 0.02 * ppm)
            target = damp if (plane.get("orient") == "N" and rj.random() < 0.4) else acc
            ok, info = stamp_run(target, mask, ppm, (x if RUN_LEAN else x + dx), y + 1, Lm, w0, w1, op,
                                 key + ("run", kind, x, y, j), striate=0.25 + 0.3 * rj.random(),
                                 tail=est_tail(rj.uniform(0.35, 0.8), est_, Lm), lean_px=(dx if RUN_LEAN else 0.0))
            if ok:
                info["kind"] = kind
                marks.append(info)
    # channels: water carried down the wall where the surface leads it (round F: long streaks,
    # some near the whole height); they carry on below each break, fading with distance
    try:                                     # how many channels: the control's own amount, not the
        a_ch = max(a, float(auto_amounts(cfg)[2]["streaks"]))   # solver's accent gain (H4 counts them)
    except Exception:  # noqa: BLE001
        a_ch = a
    for ci, x in enumerate(channel_columns(plane, F, a_ch, key)):
        rc = nz.rng(*key, "chan", x)
        rows = np.flatnonzero(mask[:, x])
        if rows.size == 0:
            continue
        u_len, u_op, u_dark, u_w, u_g = rc.random(), rc.uniform(0.7, 1.2), rc.random(), rc.uniform(0.06, 0.16), rc.uniform(1.4, 2.6)
        u_w *= CH_WA[0] + CH_WA[1] * a
        u2, u3 = rc.random(), rc.random()
        n_str = 1 + int(u2 < CH_STRANDS[0][0] + CH_STRANDS[0][1] * a) + int(u3 < CH_STRANDS[1][0] + CH_STRANDS[1][1] * a)
        offs = [0.0] + list(rc.uniform(CH_STRAND_DX[0], CH_STRAND_DX[1], n_str - 1) * rc.choice([-1, 1], n_str - 1))
        str_op = [1.0] + list(rc.uniform(0.5, 0.8, n_str - 1))
        Hw = (rows[-1] - rows[0]) / ppm
        if ci == 0 and CH_MAIN:              # the wall's main water path: most of its height (H4)
            Lc = Hw * min(1.0, 0.35 + 0.8 * a + 0.25 * u_len)
        else:                                # the rest by a power law from 3.5 m: more short than long (C3)
            Lc = min(Hw, CH_CAP * (0.7 + 0.6 * a), (CH_GROW[0] + CH_GROW[1] * a) *
                     3.5 * max(u_len, 1e-6) ** (-1.0 / (CH_TAIL[0] - CH_TAIL[1] * min(a, 1.0))))
        op0 = omax * u_op * (1.6 if u_dark < 0.20 + 0.25 * a else 1.0)
        if ci == 0 and CH_MAIN:              # the main path runs long but stays a film, not a stripe (H1)
            op0 = max(omax * u_op * CH_MAIN_OP, CH_MAIN_MIN * og)   # but always visible down its length (H4)
            u_w = u_w * CH_MAIN_W
        target = damp if (plane.get("orient") == "N" and u_dark > 0.6) else acc
        fade = CH_MAIN_FADE if (ci == 0 and CH_MAIN) else 0.55     # the main path stays one run (C3)
        cuts = sorted(int(r_) for r_ in (plane.get("floor_rows") or []))    # water pauses in each floor joint
        jh, tps, bts = plane.get("joint_h"), plane.get("tops"), plane.get("bottoms")
        real = set()                             # round I (G1): rows where this column has a joint, an edge or a break
        for c_ in cuts:
            a0_, b0_ = max(0, c_ - 3), min(H, c_ + 4)
            hit = not mask[a0_:b0_, x].all()
            for mp in (jh, tps, bts):
                if mp is not None and np.asarray(mp[a0_:b0_, x]).any():
                    hit = True
            if hit:
                real.add(c_)
        if CH_CUT_AT_JOINTS:
            cuts = sorted(real)
        y, done, seg = int(rows[0]), 0.0, 0
        pm = CH_MID * float(nz.smoothstep(0.40, 0.55, a)) if ci > 0 else 0.0
        if pm > 0:                                       # wetter walls also shed water from the lower ledges (D1)
            rm = nz.rng(*key, "chanmid", x)
            fl = [int(r_) for r_ in (plane.get("floor_rows") or []) if rows[0] + 2 * ppm < r_ < rows[-1] - 3 * ppm
                  and (int(r_) in real or not CH_PART_AT_SOURCE)]          # round I (G1): from a ledge with a source
            if fl and rm.random() < pm:
                below = rows[rows >= fl[int(rm.integers(len(fl)))]]
                if below.size:
                    y = int(below[0])                    # its own length from the ledge
        while done < Lc and y < H:
            room = region_below(mask, y, x, H) / ppm
            if room < 0.05:
                nxt = rows[rows > y]
                if nxt.size == 0:
                    break
                done += (int(nxt[0]) - y) / ppm
                y = int(nxt[0])
                continue
            room_m = room
            nc = [c_ for c_ in cuts if c_ > y + 0.3 * ppm]
            at_cut = None                                    # the cut this segment ends at (None: the surface ends)
            if nc:
                if (nc[0] - y) / ppm < room:
                    at_cut = nc[0]
                room = min(room, (nc[0] - y) / ppm)
            Ls = min(room, Lc - done)
            t0, t1 = done / max(Lc, 1e-6), min(1.0, (done + Ls) / max(Lc, 1e-6))
            last = done + Ls >= Lc - 1e-6
            ovl = CH_OVERLAP_REAL if (at_cut is not None and at_cut in real) else 0.35   # a joint interrupts (round I)
            Ld = Ls if last else min(room_m, Ls + ovl)       # overlap into the next storey: one channel
            p_part = CH_PARTIAL[0] + CH_PARTIAL[1] * a
            src_next = (at_cut is None) or (at_cut in real) or not CH_PART_AT_SOURCE   # the next one restarts at a source
            end_here = False
            if ci > 0 and not last and p_part > 0:          # round I (C3): this storey's deposit may stop partway
                rpt = nz.rng(*key, "chpart", x, seg)         # (its own stream: the other draws stay put)
                if rpt.random() < p_part:
                    if src_next:                             # the next storey's segment restarts at its source
                        Ld = Ls * rpt.uniform(0.35, 0.7)
                    elif Lc - done - Ls < CH_END_REM:        # no source below: near its end, the film runs out here
                        Ld = Ls * rpt.uniform(0.35, 0.7)
                        end_here = True
            main_cont = bool(CH_MAIN_CONT) and ci == 0 and CH_MAIN and at_cut is not None and at_cut not in real
            beat = rc.uniform(0.8, 1.25)                     # each storey's run a little different
            for k_, (o_, so_) in enumerate(zip(offs, str_op)):
                wk = 1.0 if k_ == 0 else 0.45
                ok, info = stamp_run(target, mask, ppm, x + o_ * ppm, y, Ld, wk * u_w * (1 + (u_g - 1) * t0),
                                     wk * u_w * (1 + (u_g - 1) * t1), so_ * beat * op0 * (1.0 - fade * t0),
                                     key + ("chan", x, seg, k_), striate=0.35,
                                     tail=0.6 if last else (CH_MAIN_CONT if main_cont else 2.5))
                if ok and k_ == 0:
                    info["kind"] = "channel"
                    marks.append(info)
            done += Ls + 1.0 / ppm
            y += max(1, int(round(Ls * ppm)) + 1)
            seg += 1
            if end_here:
                break
    # seam crossings: water collects where joints cross (a small head and a short run)
    for (y, x) in joint_crossings(plane):
        rx = nz.rng(*key, "jx", y, x)
        if rx.random() > 0.6 + 0.4 * a:
            continue
        stamp_blob(acc, ppm, x, y, rx.uniform(0.03, 0.05), rx.uniform(0.25, 0.45) * (0.7 + XING_A * a) * og, key + ("jxb", y, x),
                   ragged=0.4, hard=0.1)
        room = region_below(mask, y + 1, x, H) / ppm
        if room > 0.1:
            ok, info = stamp_run(acc, mask, ppm, x, y + 1, min(room, rx.uniform(0.08, 0.28)),
                                 0.012, rx.uniform(0.025, 0.05), rx.uniform(0.25, 0.40) * (0.7 + 0.6 * a) * og,
                                 key + ("jxr", y, x), striate=0.2, tail=rx.uniform(0.4, 0.8))
            if ok:
                info["kind"] = "jointx"
                marks.append(info)
    col = None
    if damp.max() > 0:
        wd = damp / np.maximum(acc + damp, 1e-6)
        col = ((1 - wd)[..., None] * np.array(COL["streaks"], F32) + wd[..., None] * np.array(COL["streaks_damp"], F32))
        acc = nz.over(acc, damp).astype(F32)
    return acc, col, marks


def layer_stains(plane, F, cfg, a, key, og=1.0):
    """Water-spread stains as accumulation (round F: 'strength should basically indicate
    accumulation'): every stain event is about as strong at any amount; a higher amount adds
    sites and layers. A site gets up to four layers over the years, each a new event a little
    larger or longer and offset, so stains darken where layers overlap and spread at their edges;
    faint small stains spread everywhere. Sites, layers and small stains are drawn at amount 1 in a
    fixed order, so a lower amount's stains are the first of a higher one's. Sizes by power law
    across S3-S8 (C3); each stamp keeps its inner pattern (B2)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    C, hgt = F.C, F.hgt
    d1 = 0.8 + 4.5                                   # top-site density at amount 1 (per m)
    anchors = [(x, y, 1.0, "top") for (x, y) in sources_along_tops(plane, key + ("anch",), d1, gap_sigma=1.3)]
    anchors += [(x, y, 1.0, "corner") for (y, x) in plane.get("corner_heads", [])]
    anchors += [(x, y, 0.25, "joint") for (y, x) in plane.get("joints", [])]   # seepage at joints: small, discrete
    tall = plane.get("kind") in ("gable", "wall", "tower")
    smax = (0.7 + 1.6 * a) if tall else (0.6 + 0.9 * a)
    alpha_sz = 1.9 + 0.2 * a
    # the control is perceptual: each step of 0.25 multiplies the stained area by about 2.5 (even
    # steps, L3); the curve is steeper near 1, where overlapping layers saturate
    thin = float(np.exp(4.08 * (a - 1.0) + 1.52 * (a - 1.0) ** 2))
    for (x, y, w_acc, kind) in anchors:
        jnt = kind == "joint"
        r = nz.rng(*key, "st", x, y)
        yy, xx = min(y, H - 1), min(x, W - 1)
        room = region_below(mask, y + 1, x, H)
        if room < 0.12 * ppm:
            continue
        c = C[yy, xx]
        u_site, u_thin = r.random(), r.random()
        if u_thin > thin:
            continue
        if u_site > min(1.0, w_acc * c ** 1.1 * (0.3 + 0.7 * hgt[yy, xx] ** 1.5) / 0.58):
            continue
        hf = 1.0 + 0.6 * hgt[yy, xx]
        size = min(smax, 0.10 * (1.0 + r.pareto(alpha_sz)) * (0.6 + a) * hf)  # power law, 3x+ per octave
        if jnt:
            size *= 0.5
        drop = float(np.clip(size * r.uniform(0.7, 2.0) * (1.5 if tall else 0.9), 0.08, room / ppm))
        width = float(np.clip(size * r.uniform(0.6, 1.6), 0.10, 0.8 if jnt else 4.5 if tall else 1.2 * drop + 0.1))
        op = 0.34 * min(1.5, c) ** 0.5 * r.uniform(0.6, 1.1) * (0.85 + 0.3 * hgt[yy, xx]) * og   # one event's strength
        layers = []
        for j in range(4):                            # events at this site over the years
            rl = nz.rng(*key, "stl", x, y, j)
            u_l, f_w, f_d, jit, f_o = rl.random(), rl.uniform(0.75, 1.3), rl.uniform(0.8, 1.5), rl.normal(0, 0.12), rl.uniform(0.7, 1.1)
            if j == 0 or u_l < min(1.0, a * (2.4 - 0.5 * j)) * (1.0 if size > 0.15 or j < 2 else 0.5):
                layers.append((j, f_w, f_d, jit, f_o))
        heavy = len(layers) >= 3 and a >= 0.5
        for n_, (j, f_w, f_d, jit, f_o) in enumerate(layers):
            dr = float(min(room / ppm, drop * (1.0 if j == 0 else f_d)))
            ok, info = stamp_stain(acc, mask, F.inner, ppm, x + jit * width * ppm, y + 1,
                                   width * (1.0 if j == 0 else f_w), dr, op * (1.0 if j == 0 else f_o),
                                   key + ("st", x, y, j), crust=(a - 0.5) * 0.8 if heavy and n_ == len(layers) - 1 else 0.0)
            if ok and j == 0:
                marks.append(info)
    # small stains: drops and splashes 5-40 cm, many more than the big ones (C3); faint, and more
    # of them with the amount (drawn at amount 1, the first n kept)
    r = nz.rng(*key, "small")
    ys, xs = np.nonzero(mask)
    n1 = int(9.9 * mask.sum() / ppm ** 2 / 4.0)
    n = int(n1 * np.exp(2.6 * (a - 1.0)))
    if ys.size and n:
        w = (C[ys, xs].astype(np.float64) ** 1.0) * (1.0 + hgt[ys, xs])
        pick = r.choice(ys.size, size=n1, p=w / w.sum())[:n]
        for i, j in enumerate(pick):
            ri = nz.rng(*key, "smi", i)
            size = min(0.40, 0.04 * (1.0 + ri.pareto(1.5)))
            op = 0.26 * ri.uniform(0.4, 1.0) * og
            if ri.random() < 0.6:                       # a splash: irregular, no tail
                res_ = stamp_blob(acc, ppm, xs[j], ys[j], 0.5 * size * ri.uniform(0.6, 1.3), op * 0.8,
                                  key + ("smb", i), ragged=0.55, hard=0.05)
                ok, info = res_ is not None, {"x": int(xs[j]), "y": int(ys[j]), "w_m": size, "h_m": size, "peak": op}
            else:                                      # a short dribble
                ok, info = stamp_stain(acc, mask, F.inner, ppm, xs[j], ys[j], size * ri.uniform(0.6, 1.4),
                                       size * ri.uniform(0.4, 1.0), op, key + ("sm", i))
            if ok:
                marks.append(info)
    return acc, None, marks


CK_VBLUR_M = 2.5            # the cause field as the film pattern's strength, smoothed down the wall (m)
CH_MAIN = True              # the first channel is the wall's main water path
FOOT_SPLASH = 0.8           # soiling added at the foot
FOOT_DECAY = 1.0            # over which it fades (m)
CH_MAIN_OP, CH_MAIN_W = 0.45, 0.5  # its opacity (no dark subset) and width factors
B2_MARGIN = 0.025           # the solver's last check wants B2 this far inside its thresholds
A1_ZMAX = 0.97              # the solver keeps every tier this far inside its band (log scale)
MATCH_TOL = (0.03, 0.05, 0.20)   # a matched seed's bands around the first seed: tone, T2+-T4+, T5+-T6+ (A5)
J2_MIN = 0.255              # and J2 (a) at least this (the gate needs 0.25)
CH_MID = 0.5                # share of ordinary channels starting at a floor line on wet walls (amount 0.4-0.55 ramp)
CAP_WET = 0.0               # on wet walls (amount 0.4-0.55 ramp) runs stop short more often and shorter


def _box_y(x, r):
    c = np.cumsum(np.pad(x, ((r + 1, r), (0, 0))), axis=0)
    return (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)


def vblur(a, mask, sigma_px):
    """Masked blur down the wall (three box passes, about Gaussian with sigma_px)."""
    r = max(1, int(round(sigma_px)))
    num = np.where(mask, a, 0.0).astype(np.float64)
    den = mask.astype(np.float64)
    for _ in range(3):
        num, den = _box_y(num, r), _box_y(den, r)
    return np.where(mask, num / np.maximum(den, 1e-9), a)


LOAD_DECAY_M = 7.0          # metres of run-off over which the carried dirt falls to 1/e
CK_TL_EXP = 0.6             # the film pattern's strength follows the tone (load) to this power
C_ANISO = (1.0, 1.0)        # the cause field's correlation (vertical, horizontal); 1.6 vertical was tried in T79
HGT_RAIN = (0.80, 0.60, 2.0)   # driven rain on the tone: a + b x height ** c


SOIL_LIGHT = (14.5, 1.0, 2.0)    # (E0, q, cap): under the Worn clock the coat and the grain keep their strength (round H)


def light_grain(E):
    """How much stronger the coat's texture and the dust grain are, relative to the film, under a
    light load. The coat's micro-relief fills with dirt first, so on a lightly soiled wall the film
    sits in the coat and the fine grain is set early: below the Worn clock E0, where the film gets
    thick enough to bury the coat's texture, both keep their absolute strength, their relative
    amplitude growing as (E0 / E) ** q, capped (Kept 2.0, Typical 1.35). 1 at E0 and above
    (B3: a light film is not a flat tint; J2: it follows the material)."""
    e0, q, cap = SOIL_LIGHT
    if E >= e0:
        return 1.0
    return float(min(cap, (e0 / max(E, 1e-3)) ** q))


FOOT_TEX = (0.45, 0.8)      # splash zone (round H, B2): reach variation along the wall, coat exponent of its texture
FOOT_ALONG = 0.8            # the splash zone heavier along some stretches than others (S2-S4, log amplitude)
FOOT_TEX_AMP = 0.8          # the texture's strength in the splash zone, relative (mean kept)
FOOT_CORE = (0.25, 0.6, 0.9)   # the splash core: decay (m), strength, its specks' grain exponent; after the saturation
FOOT_CORE_E = (12.0, 20.0)  # the splash zone's reach, texture and core: full up to this clock E, gone at the second


def foot_gain(E):
    """The splash zone's extra structure by the soiling clock: full on light and moderate walls,
    where it stands out from the wall above; fading out on heavily soiled ones, where the lower
    storey is dark already (and the darkest tier, A1 T6+, has no room)."""
    a, b = FOOT_CORE_E
    return float(np.clip((b - E) / (b - a), 0.0, 1.0))


def foot_splash(plane, F, sh, E):
    """The splash zone's reach and textures. Splash-back reaches higher in places (a ragged top,
    S4-S6 along the wall) and sits in the coat: more where the coat is rough or thin, a texture
    that follows the material (J2). Its core, the bottom 25 cm, is soil-splash specks and short
    drips in that coat (the deposits' own grain). Both have mean 1, so the zone's average soiling
    is unchanged by them and only its inside varies (B2: large marks have an inner pattern; at the
    Typical clock the foot bands were most of B2's large marks)."""
    ppm, W = plane["ppm"], sh[1]
    a_r, g_c = FOOT_TEX
    gain = foot_gain(E)
    rag = nz.fbm((1, W), ppm, [4, 5, 6], F.key + ("footrag",))[0]
    reach = FOOT_DECAY * np.clip(1.0 + a_r * gain * rag, 0.35, 2.2)[None, :]
    m = plane["mask"]
    mc = 1.0 + 0.35 * (F.mat - 1.0)
    tex = (mc / max(float(mc[m].mean()), 1e-6)) ** g_c
    tex = tex * np.exp(FOOT_ALONG * nz.fbm((1, W), ppm, [2, 3, 4], F.key + ("footalong",))[0])[None, :]   # heavier stretches
    tex = tex / max(float(tex[m].mean()), 1e-6)
    spk = tex * F.acctex ** FOOT_CORE[2]                   # the core: soil-splash specks and short drips in the coat
    spk = spk / max(float(spk[m].mean()), 1e-6)
    return reach.astype(F32), tex.astype(F32), spk.astype(F32), gain


# round J: zones for the top band, top corners, inside corners and recess bottoms (F5, G7)
ZONE_ON = True
XING_A = 0.6                # seam-crossing heads grow with the streak amount (J13's 1.0 reverted in J25)
F5_E = (14.0, 19.0)         # the top band and top corners come in from Worn to Derelict (soiling clock E)
F5_K = (1.8, 3.1)           # their excess in the soiling field: band, top corners (J12: F5 band 1.33, corners 1.53;
                            # J14: S 1.43, 1.62 at (1.6, 2.9), so a margin before the solver re-tunes)
                            # J13: S band 1.34, corners 1.58 at (1.4, 2.6))
F5_BAND_M = 0.45            # J13: the band's fall-off below the top (was 0.30: 1.73x at 5 cm, 1.10x by 0.5 m)
F5_WET = 0.85               # top corners' growth wetness at Derelict
G7_K = 1.30                 # inside corners' excess in the soiling field (0.1-0.4 m strips), from E 10 (J12)
G7_KD = 0.50                # J13: more from E 14 to 20 (Derelict 1.25-2.0x; it measured 1.13-1.14)
G7_REC = 0.60               # J12: recess faces (0.3 m or more behind the nearest wall around): not rain-washed
G7_R = 0.35                 # its reach (m), gaussian (J13; was exp(-d/0.2)): 0.6 over the strip, 0.045 at 0.55-0.7 m
G7_WET = (0.88, 0.68)       # growth wetness at corner bottoms (1 m above a floor) and recess bottoms (0.3 m)
                            # (J22: recess bottoms 0.85 -> 0.68: thin bands raised M6 to 1.50 at Worn; G7 4.5-6.6x)
PEEL_TOPEDGE = 0.15         # the peeling score's weight within 0.1 m of the wall top (F5: 15-50 % of the edge at Derelict;
                            # J17: 0.25 gave the W gable 53 %)
                            # J14: 0.45 gave the W gable 61 % once PEEL_BASE fell to 0.07)
XING_SOIL, XING_R = 0.8, 0.05   # J14: water pauses where joints cross: soiling excess there, from E 14 to 20 (G5)
ZONE_STAGE = 0.0            # J14 pushed the zone growth's stage (M2); J17: reverted, it greyed and greened it
ZONE_ALPHA = 0.50           # J17: where water stands the growth is thick: opacity x (1 + this x the zone weight)
                            # (J18: 0.25 left M2 at Worn at L* 50.2)
G7_RB_M = 0.15              # J17 tried 0.10 (G7 bottom growth fell to 1.72x); J18: back to 0.15
G7_RB_CUT = 0.3             # J21: the recess-bottom band's top (m above the floor line)
RECESS_SOFT_M = 0.25        # J14: the recess weight blurred (m): no step 1.5-2.5 m from a nearer wall


def plane_zones(plane):
    """Cached per plane: dtop (m below the wall top, per column; -1 above it), dend (m from the plane's
    nearer end), ic_d (m to the nearest inside-corner line in the row, at one depth), rb_up (m above
    the nearest recess bottom line in the column, inside the wall)."""
    if "_zones" in plane:
        return plane["_zones"]
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    tr = int(plane.get("top_row") or 0)
    rows = np.arange(H)[:, None]
    near_top = mask & (rows <= tr + int(1.0 * ppm))
    first = np.where(near_top.any(axis=0), np.argmax(near_top, axis=0), -1)
    dtop = np.where(first[None, :] >= 0, (rows - first[None, :]) / ppm, -1.0).astype(F32)
    cols = np.flatnonzero(first >= 0)
    xx = np.arange(W)[None, :]
    if cols.size:
        dend = (np.minimum(xx - cols.min(), cols.max() - xx) / ppm * np.ones((H, 1))).astype(F32)
    else:
        dend = np.full((H, W), 1e3, F32)
    d = plane.get("depth")
    ic_d = np.full((H, W), 1e3, F32)
    rb_up = np.full((H, W), 1e3, F32)
    if d is not None:
        d = np.nan_to_num(np.asarray(d, np.float64), nan=1e3, posinf=1e3)
        left = np.full((H, W), np.inf)
        right = np.full((H, W), np.inf)
        left[:, 1:] = np.where(mask[:, :-1], d[:, :-1], np.inf)
        right[:, :-1] = np.where(mask[:, 1:], d[:, 1:], np.inf)
        ic = mask & ((left < d - 0.05) | (right < d - 0.05))
        big = np.float32(1e9)
        dist = np.full((H, W), big, np.float32)
        for order in (range(W), range(W - 1, -1, -1)):
            run = np.full(H, big, np.float32)
            prev = None
            for x in order:
                ok = mask[:, x]
                if prev is not None:
                    ok = ok & (np.abs(d[:, x] - d[:, prev]) <= 0.05)
                run = np.where(ic[:, x], 0.0, np.where(ok, run + 1.0, big))
                dist[:, x] = np.minimum(dist[:, x], run)
                prev = x
        ic_d = (dist / ppm).astype(F32)
        below = np.full((H, W), np.inf)
        # J20: a recess's bottom is its floor line: m above the floor line below, on recess faces only (a
        # nearer surface below is usually a parapet hiding the wall, not the junction where water stands)
        fl = sorted(set([int(r) for r in (plane.get("floor_rows") or [])] + [int(plane.get("ground_row") or H - 1)]))
        nxt = np.full(H, -1)
        j_ = 0
        for y in range(H):
            while j_ < len(fl) and fl[j_] < y:
                j_ += 1
            nxt[y] = fl[j_] if j_ < len(fl) else -1
        up_ = np.where(nxt >= 0, (nxt - np.arange(H)) / ppm, 1e3)
        recb = (recess_of(plane) > 0.5) & mask
        rb_up = np.where(recb, up_[:, None], 1e3).astype(F32)
    plane["_zones"] = (dtop, dend, ic_d, rb_up)
    return plane["_zones"]


def zone_terms(plane, E):
    """(band, corner, icorner, f5): the top band (0.05-0.6 m under the top), the top corners (1.5 x 1.5 m),
    the inside-corner strips, and the F5 weight of this clock."""
    dtop, dend, ic_d, rb_up = plane_zones(plane)
    f5 = float(nz.smoothstep(F5_E[0], F5_E[1], E))
    band = np.where(dtop >= 0, np.exp(-np.clip(dtop - 0.05, 0, None) / F5_BAND_M), 0.0) * (dtop <= 1.2)
    corner = np.where((dtop >= 0) & (dtop <= 1.5) & (dend <= 1.5), np.exp(-dtop / 0.9) * np.exp(-dend / 0.9), 0.0)
    icn = np.exp(-(ic_d / G7_R) ** 2) * (ic_d < 1.0)
    return band.astype(F32), corner.astype(F32), icn.astype(F32), f5


def xing_field(plane):
    """J14: a gaussian of XING_R around each seam crossing (cached per plane)."""
    if "_xing" in plane:
        return plane["_xing"]
    H, W = plane["mask"].shape
    ppm = plane["ppm"]
    xf = np.zeros((H, W), F32)
    r = int(3 * XING_R * ppm) + 1
    for (cy, cx) in joint_crossings(plane):
        y0, y1, x0, x1 = max(cy - r, 0), min(cy + r + 1, H), max(cx - r, 0), min(cx + r + 1, W)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        g = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (XING_R * ppm) ** 2).astype(F32)
        xf[y0:y1, x0:x1] = np.maximum(xf[y0:y1, x0:x1], g)
    plane["_xing"] = xf
    return xf


def recess_of(plane):
    """J12: 1 on wall standing 0.3 m or more behind the nearest wall within about 1.5-2.5 m in its row."""
    if "_recess" in plane:
        return plane["_recess"]
    d = plane.get("depth")
    mask = plane["mask"]
    out = np.zeros(mask.shape, F32)
    if d is not None:
        d = np.nan_to_num(np.asarray(d, np.float64), nan=1e3, posinf=1e3)
        dm = np.where(mask, d, np.inf)
        front = dm.copy()
        s = 1
        while s <= int(1.5 * plane["ppm"]):
            front = np.minimum(front, np.minimum(np.roll(front, s, 1), np.roll(front, -s, 1)))
            s *= 2
        out = (mask & (d - front >= 0.3)).astype(F32)
        if RECESS_SOFT_M > 0:
            out = (np.clip(wm_.gauss(out, RECESS_SOFT_M * plane["ppm"]), 0, 1) * mask).astype(F32)
    plane["_recess"] = out
    return out


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
    ut_mod = np.exp(0.7 * nz.fbm(sh, plane["ppm"], [5, 6, 7], F.key + ("utmod",), aniso=(0.5, 1.0)))
    ut_mod = (ut_mod / ut_mod.mean()) * F.acctex              # broken up along each edge, per storey
    exc = exc + 0.9 * plane.get("under_top", np.zeros(sh)) * ut_mod
    exc = exc + 0.7 * plane.get("corner_prox", np.zeros(sh))
    if ZONE_ON:                                               # round J: top band and corners (F5), inside corners (G7)
        band_, corner_, icn_, f5_ = zone_terms(plane, E)
        g7_ = float(nz.smoothstep(8.0, 12.0, E))
        g7k = G7_K + G7_KD * float(nz.smoothstep(14.0, 20.0, E))
        exc = exc + f5_ * (F5_K[0] * band_ + F5_K[1] * corner_) + g7_ * (g7k * icn_ + G7_REC * recess_of(plane))
    if XING_SOIL > 0 and E > 14.0:
        exc = exc + XING_SOIL * float(nz.smoothstep(14.0, 20.0, E)) * xing_field(plane)
    phys = 0.70 + 0.50 * exc                                  # half as tone, half as deposits
    phys = phys * plane.get("lee", 1.0) * (1.0 - 0.55 * plane.get("washed", np.zeros(sh)))
    phys = phys * (HGT_RAIN[0] + HGT_RAIN[1] * F.hgt ** HGT_RAIN[2]) * F.ends   # driven rain: the top storeys get more
    flow = 1.0 - np.exp(-F.F / 1.2)                         # water: saturates 2-3 m below a top
    load = (1.0 - np.exp(-F.F / 0.6)) * np.exp(-F.F / LOAD_DECAY_M)   # dirt carried: peaks just below a top
    late = float(nz.smoothstep(12.0, 30.0, E))
    dirtwash = 1.0 + (1.5 * (1 - late) + 0.5) * F.chan * load / 0.55
    whitewash = 1.0 - 0.55 * late * F.chan * flow
    mac = F.macro ** 0.8
    footw = None
    if plane.get("ground_row") is not None:                   # the splash zone is never cleaner than the wall
        hf = (foot_rows(plane)[None, :] - np.arange(sh[0])[:, None]) / plane["ppm"]
        wf_ = np.clip(1.0 - hf / 1.5, 0.0, 1.0)
        mac = mac * (1.0 - wf_) + np.maximum(mac, 1.0) * wf_
        reach, ftex, fspk, fg = foot_splash(plane, F, sh, E)
        footw = np.exp(-np.clip(hf, 0.0, None) / reach)          # the splash zone: 1 at the foot, fading up
        mac = mac * (1.0 + FOOT_SPLASH * footw)                   # splash and soil at the foot (F3), ragged reach
    tone = g * phys * mac                                      # smooth: sets the greying (A0)
    m = plane["mask"]
    tm = max(float(tone[m].mean()), 1e-6)
    tone = 1.8 * tm * np.tanh(tone / (1.8 * tm))               # stacked exposure factors saturate gently
    if footw is not None and fg > 0:                           # the splash zone's texture and core, after the saturation (B2)
        core = np.exp(-np.clip(hf, 0.0, None) / FOOT_CORE[0])    # soil splash and damp: darkest low down
        tone = tone * (1.0 + fg * FOOT_TEX_AMP * footw * (ftex - 1.0)) * (1.0 + fg * FOOT_CORE[1] * core * fspk)
    mat = F.mat / max(float(F.mat[m].mean()), 1e-6)
    tn = tone / max(float(tone[m].mean()), 1e-6)
    lg = light_grain(E)
    kg = 0.20 * np.clip(tn, 0.2, 5.0) ** -0.4 * lg            # dust grain: a light film is grainy (B3)
    # the material's response: coat strength and laps, a thin coat chalks and holds more dirt,
    # the joints hold dirt (grooves and the lip below)
    F.matresp = ((1.0 + 0.35 * (mat - 1.0)) * (1.0 + 0.06 * F.zc) * (1.0 + 1.6 * F.jd)).astype(F32)
    mc = 1.0 + 0.35 * (mat - 1.0)
    F.matcoat = (mc / max(float(mc[plane["mask"]].mean()), 1e-6)).astype(F32)   # the coat's own response, mean 1
    coat = (1.0 + 0.35 * (mat - 1.0)) * (1.0 + 0.06 * F.zc)
    tone = tone * (1.0 + kg * (F.grain - 1.0)) * coat ** lg * (1.0 + 1.6 * F.jd)   # grain, coat (stronger on a light film), joints
    zm = (1.0 + 0.35 * (mat - 1.0)) * (1.0 + 0.06 * F.zc)
    zm = np.clip((zm - float(zm[m].mean())) / max(float(zm[m].std()), 1e-6), -2.5, 2.5)
    # water pattern, contrast solved (k); deposits follow the coat (rough or thin coat holds more)
    patt = F.mid * dirtwash * whitewash * F.speck * (1.0 + 0.35 * zm) * (1.0 + 1.6 * exc)
    patt = patt / max(float(patt[m].mean()), 1e-6)
    tl = np.clip(tn, 0.3, 3.0)
    Cc = F.C
    if CK_VBLUR_M > 0:                                          # the pattern's strength: storeys stay alike (E1)
        Cc = getattr(F, "_Cv", None)
        if Cc is None or getattr(F, "_Cv_m", None) != CK_VBLUR_M:
            Cc = F._Cv = vblur(F.C, plane["mask"], CK_VBLUR_M * plane["ppm"]).astype(F32)
            F._Cv_m = CK_VBLUR_M
    ck = Cc ** 1.2 * tl ** CK_TL_EXP                            # pattern strongest where the causes are and
    ck = ck / max(float(ck[m].mean()), 1e-6)                    # where the load is: dirtier, more varied
    ck = CK_FLOOR + (1.0 - CK_FLOOR) * ck                       # fainter where causes are weak, never gone
    dev = patt - 1.0
    dev = np.where(dev > 0, dev * F.acctex ** ACC_GAMMA * F.matcoat ** MAT_DEP, dev)   # deposits: grainy, and they follow the coat (B2, J2)
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


BASE_H = 1.5                # the ground band's height scale (m)
BASE_CAP = (0.30, 0.42)     # the splash band's opacity ceiling a0 + a1 x amount (round I: from 0.35 + 0.5 a, A1 T6+ at the foot)
BASE_GROW = (0.25, 1.9)     # x (a0 + a1 x amount): Kept 0.35 m, Typical 0.5, Worn 0.7, Derelict 1.15 on the south front (round I, research V4: 0.7 + 0.5 a)


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
    hb = BASE_H * (0.30 + 0.45 * cfg.get("exposure", 0.6)) * (BASE_GROW[0] + BASE_GROW[1] * a) * (1.0 + 0.3 * north)   # round I: rises with the amount
    rag = nz.fbm((1, W), ppm, [5, 6, 7], key + ("rag",))[0]
    along = np.exp(0.30 * nz.fbm((1, W), ppm, [2, 3, 4], key + ("along",))[0])
    top = hb * ppm * (1.0 + 0.50 * rag)
    y = (foot[None, :] - rows).astype(F32)
    t = np.clip(y / np.maximum(top[None, :], 1), -1, 1.5)
    band = np.where(t >= 0, np.clip(1.0 - t, 0, 1) ** 0.6, 1.0)                # below the foot: plinth
    acc = (1.05 * a ** 0.8 * (1.0 + 0.60 * north) * band * np.clip(F.patt, 0.2, 3) ** 1.4 * F.acctex ** 0.8 *
           along[None, :]).astype(F32)                                       # speckled, streaky splash
    cap = BASE_CAP[0] + BASE_CAP[1] * a                          # kept: peaks in T5
    acc = cap * np.tanh(acc / cap)
    r = nz.rng(*key, "spk")
    n = int(a * W / ppm * 60)
    xs = r.uniform(0, W, n)
    ys = foot[np.clip(xs.astype(int), 0, W - 1)] - np.abs(r.exponential(0.30 * hb * ppm, n))
    for i in range(n):
        if 0 <= ys[i] < H:
            stamp_blob(acc, ppm, xs[i], ys[i], r.uniform(0.004, 0.02), 0.25 * a, key + ("spk", i), ragged=0.3)
    acc = np.clip(acc, 0, 0.9) * mask
    wd = np.clip(band, 0, 1) * 0.6
    col = (1 - wd)[..., None] * np.array(COL["base"], F32) + wd[..., None] * np.array(COL["base_damp"], F32)
    return acc.astype(F32), col.astype(F32), []


def arrival_time(cost, T, n_iter=6, down=0.6, up=2.0):
    """First-passage time on a 4-neighbour grid by fast sweeping: T = min(T, T_nb + step cost).
    A step down the wall costs `down` x the cell's cost, a step up `up` x (water runs down)."""
    T = T.copy()
    H, W = T.shape
    Tt, ct = T.T, cost.T
    for _ in range(n_iter):
        for y in range(1, H):
            np.minimum(T[y], T[y - 1] + cost[y] * down, out=T[y])
        for y in range(H - 2, -1, -1):
            np.minimum(T[y], T[y + 1] + cost[y] * up, out=T[y])
        for x in range(1, W):
            np.minimum(Tt[x], Tt[x - 1] + ct[x], out=Tt[x])
        for x in range(W - 2, -1, -1):
            np.minimum(Tt[x], Tt[x + 1] + ct[x], out=Tt[x])
    return T


BIO_W = np.array([0.08, 0.27, 0.55, 0.85])      # class centres on the wetness map: W0 sunny, W1 shaded open, W2 damp, W3 wet
BIO_AMAX = (0.40, 0.50, 0.70, 0.92)             # growth opacity ceiling by wetness class (round I: damp walls 0.70, the wettest
                                                # cores 0.92: dense dark crusts only where water stays longest, A1 T5+/T6+)
BIO_A = (0.80, 0.15)                            # growth opacity: a0 + a1 x old (young growth thinner than old crusts)
BIO_EDGES = (0.15, 0.40, 0.70)                   # class edges
BIO_TL = np.array([6.0, 3.5, 1.0, 0.3])          # onset (years), growth research 3.3; W1 3.0 -> 3.5 in round H (M3 at 5.7 y)
BIO_TAU = np.array([40.0, 15.0, 5.0, 1.5])       # time scale (years)
BIO_XMAX = np.array([0.30, 0.60, 0.90, 0.95])    # the most of a class's area ever covered
BIO_STEPS = ([0.25, 0.5, 0.75, 1.0], [3.1, 5.7, 10.0, 22.0])   # the control: years at its steps (even steps, L3; round H)
BIO_A0 = 0.5                # years a colony is faint before it shows (T2)
BIO_NUC = (0.4, 90.0)       # nuclei per m2: a + b x wetness ** 3
BIO_STAGGER = 0.6           # births after the onset, up to this share of the class time scale (round H: new patches, M8)
BIO_STAGGER_P = 2.0         # and spread as uniform ** this (2: most early; 1: even)
BIO_DARK = (2.5, 8.0)       # biomass-years over which wet-zone growth goes dark (round H, from 4-12: darkens with age, M9)
BIO_YEL_Q = 0.80            # the yellow family: above this quantile of its own field, outside the rusty family (round H)
BIO_SOUTH_GREY = 0.25       # south faces: share of the colour greyed toward mould (round G 0.5)
BIO_SOUTH_FU = 0.35         # and the black-fungus share of the dark stage (round G 0.45)
CH_TAIL = (1.6, 0.0)        # channel lengths: power-law exponent a0 - a1 x amount (from 3.5 m)
RUN_DX = 0.05               # extra runs at a source: 0 = on top of the first, else this far apart (m)
RUN_LEAN = True             # round I (G1): extra runs start at the source and drift to their offset (else start offset)
RUN_LEAN_M = 0.15           # over this much of their length (m)
DARK_A = 1.0                # round I (H5): darker runs x (1 + DARK_A x (amount - DARK_A0)) above DARK_A0
DARK_A0 = 0.4
BIO_BELT_VAR = (0.5, 1.0, 1.15)        # round I (C3): the splash belt's wetness along the wall: (least factor, scale m, most factor)
BIO_SAT2 = (4.0, 0.08, 1.7, 2.2)             # round I (C3): (lead years, blob scale m, threshold, age years): colonies ahead of the front
CAP_SHORT = 0.8             # share of runs reaching the next drip edge that stop short of it
CH_N = (0.5, 10.0)          # channels per 25 m of wall: a0 + a1 x amount
RUN3 = 0.6                  # chance of a third run at a source: this x amount
EST_FADE_L = (1.1, 1.5)     # round I: ... for established runs this long (m) and longer; shorter ones fade as ordinary runs
EST_FADE = (1.2, 2.5)          # round I (C3): established runs' fade exponent range (None: as ordinary runs, 0.35-0.8)
EST_TAIL = 1.6              # established runs: power-law exponent of their length (from 0.8 m)
ACC_GAMMA = 1.0             # contrast of the deposits' inner texture (B2)
CH_MAIN_FADE = 0.2          # the main path's fade over its length (other channels 0.55)
TOP_DENS = (0.4, 5.0)       # streak sources along tops (the horizontal grooves and drip edges) per m: a0 + a1 x amount (round I: 0.5, 8.5)
TOP_K = (0.55, 0.6)         # runs from tops on the panel faces: strength and length factors (round I: 'minimal ... from the horizontal grooves')
CH_LINE = 0.06              # channel weight off the vertical lines (joints, bay divisions, ends, inside corners), round I
CH_GROW = (0.55, 0.90)      # channel length factor: a0 + a1 x amount (round I: streaks lengthen with age)
CH_CUT_AT_JOINTS = False    # True: channel segments restart only at a real joint, edge or break (one long segment fades
                            # out early: H4); round I keeps every storey cut and gates the partial stops instead
CH_PART_AT_SOURCE = True    # a storey segment stops partway only where the next restarts at a source (G1)
CH_OVERLAP_REAL = 0.10      # round I (C3): a segment's overlap past a real joint (m); 0.35 elsewhere: the groove interrupts
CH_MAIN_CONT = 12.0         # round I (C3): the main path's fade exponent into a storey line with no joint (0: 2.5 as others)
CH_END_REM = 0.0            # ... or, with no source below, where the channel had under this much left (m): it ends there
CH_PARTIAL = (0.25, 0.30)   # chance a channel's storey segment stops partway: a0 + a1 x amount (round I, C3)
CH_WA = (0.25, 4.0)         # channel width factor: a0 + a1 x amount (round I: x3 Kept to Derelict, research V4)
CH_STRANDS = ((0.20, 0.40), (0.05, 0.25))   # chance of a second and third strand: a0 + a1 x amount
CH_STRAND_DX = (0.012, 0.035)   # strands 1.2-3.5 cm off the channel's centre: they merge into one wet path
EDGE_C0 = 0.48              # edge band continuity at 0.25 (x EDGE_G a step; N2 inside its band)
EDGE_K = 1.3                # edge band contrast factor (N1 inside its band)
EDGE_G = 1.27                # above 0.25: the edge band's continuity x this a step of 0.25 (L1)
EDGE_P = 1.10                # above 0.25: the band's contrast x this a step (L2); 0 keeps the flat contrast
CH_CAP = 7.5                # the longest ordinary channel (m): a few storeys; only the main path runs the height
EST_SHARE = (0.02, 0.03)    # share of runs that are established (0.8 m up): a0 + a1 x amount
DARK_K = (3.0, 4.0)         # the darker runs: opacity factor range (H5)
CK_FLOOR = 0.45             # the film pattern's strength where causes are weakest (B2)
OP_LO = 0.15                # ordinary runs: opacity factor from this to 1 (H5)
OMAX = (0.25, 0.38)         # streak opacity: a0 + a1 x amount (slower: the amount spreads more than it darkens, H5)
RUN_WA = 0.8                # streak widths grow by this x amount
CH_MAIN_MIN = 0.15          # the main path's least opacity (H4 at low amounts)
MAT_DEP = 3.0               # deposits' inner texture from the coat's response, this power (J2)
CH_MAIN_SOLID = True        # the main path only on columns of solid wall (95 %) where there are any
BIO_INK = (0.60, 7.7, 13.2, 0.80, 1.0)   # ink stripes: strength, biomass ramp, run-off ramp
BIO_INK_PATH = True         # ink stripes on the streak paths (else on the run-off map)
BIO_INK_P = (0.92, 9.0, 11.0, 0.12, 0.30)   # strength, biomass ramp, streak ramp (streaks smeared 0.3 m down)
BIO_DRY_FAM = True          # dry films per family (green, rusty)
BIO_RUST_Q = 0.66           # growth families: the rusty family above this quantile of the family field (round H, from 0.58)
# round I: organic marks on one continuum by local age, dark yellow -> dark green -> reddish-muddy
# ('Try to keep it on a continuum'); a place's stage only grows with time, so no colour flips between
# presets, and the stage jitter puts different stages side by side (I4)
BIO_RAMP = ((0.00, (0.520, 0.440, 0.190)),   # first growth: a light yellow tint (M1: weak growth is a tint)
            (0.18, (0.330, 0.228, 0.068)),   # dark yellow (ochre-olive): L 57, b* +34
            (0.38, (0.190, 0.170, 0.050)),   # olive
            (0.58, (0.067, 0.135, 0.024)),   # dark green: L 40, C* 37 (round I: more saturated, M2)
            (0.80, (0.170, 0.100, 0.042)),   # dark brown (muddy): L 40, C* 23, hue 75 (no darker than the green: A1 T6+)
            (1.00, (0.205, 0.090, 0.050)))   # reddish-muddy (Trentepohlia and soil): L 40, C* 24, hue 54
BIO_STAGE = (0.0, 7.0, 0.22)    # stage = a0 + (1 - a0) x smoothstep(0, years, biomass-years) + jitter x this
BIO_CONTINUUM = True


def bio_years(a):
    """Years unattended for the growth control: 3.1, 5.7, 10 and 22 years at 0.25-1.0 (log-linear
    between), so each step adds about the same share of growth over the walls (L3, emulated on the
    round-H Typical with _tune_bio_h.py); linear from 0 below 0.25."""
    xs, ys = BIO_STEPS
    if a <= 0:
        return 0.0
    if a < xs[0]:
        return float(ys[0] * a / xs[0])
    if a > xs[-1]:
        k = np.log(ys[-1] / ys[-2]) / (xs[-1] - xs[-2])
        return float(ys[-1] * np.exp(k * (a - xs[-1])))
    return float(np.exp(np.interp(a, xs, np.log(ys))))


def _bio_params(W):
    """Onset, time scale and ceiling for wetness W, continuous across the classes."""
    pos = np.interp(W, BIO_W, np.arange(4.0))
    k = np.arange(4.0)
    return (pos, np.exp(np.interp(pos, k, np.log(BIO_TL))), np.exp(np.interp(pos, k, np.log(BIO_TAU))),
            np.interp(pos, k, BIO_XMAX))


def bio_wetness(plane, F, stains=None, streaks=None, chips=None, key=("bw",)):
    """Where water stays (0-1), in the growth research's classes: W3 wet (the splash belt,
    0-0.3 m; stains and the run-off below them), W2 damp (0.3-1 m above the foot, streak paths,
    inside corners, joints, chips), W1 shaded open wall (N, E, W), W0 sunny open wall (S).
    Rain-sheltered wall (under slabs with drips) sits below its neighbours; damp zones dry faster
    on sunny faces. Returns (W, run-off)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W_ = mask.shape
    orient = plane.get("orient")
    base = {"N": 0.30, "E": 0.26, "W": 0.24, "S": 0.09}.get(orient, 0.24)
    o = {"N": 1.0, "E": 0.9, "W": 0.85, "S": 0.6}.get(orient, 0.85)
    w = np.full((H, W_), base, F32)
    shel = plane.get("shelter")
    if shel is not None:
        w = (w * (1.0 - 0.5 * np.clip(shel, 0, 1))).astype(F32)
    if plane.get("ground_row") is not None:
        hn = 0.06 * nz.gfield((8, W_), 0.5 * ppm, tuple(key) + ("bfoot",))[4]      # a ragged belt top
        h = np.clip((foot_rows(plane)[None, :] - np.arange(H)[:, None]) / ppm + hn[None, :], 0, None)
        wf = np.interp(h, [0.0, 0.08, 0.25, 0.60, 1.00], [0.95, 0.92, 0.70, 0.35, 0.0])   # belt top 0.05-0.3 m (O5)
        if BIO_BELT_VAR is not None:                     # round I (C3): splash is strongest under drip points and in
            lo_, sc_ = BIO_BELT_VAR[0], BIO_BELT_VAR[1]  # hollows, weaker between: the belt varies along the wall
            hi_ = BIO_BELT_VAR[2] if len(BIO_BELT_VAR) > 2 else 1.0
            bv = nz.gfield((8, W_), sc_ * ppm, tuple(key) + ("bbelt",))[4]
            wf = np.minimum(wf * (lo_ + (hi_ - lo_) * nz.smoothstep(-0.6, 0.6, bv))[None, :], 0.98)
        w = np.maximum(w, (wf * o).astype(F32))
    run = np.zeros((H, W_), F32)
    wet = np.zeros((H, W_), F32)
    if stains is not None:
        wet = np.maximum(wet, nz.smoothstep(0.03, 0.25, stains).astype(F32))
    if streaks is not None:
        wet = np.maximum(wet, (0.8 * nz.smoothstep(0.05, 0.35, streaks)).astype(F32))
    if wet.any():
        k = max(1, int(0.5 * ppm))
        run = wet.copy()
        for i in range(1, k + 1, max(1, k // 10)):
            run[i:] = np.maximum(run[i:], wet[:-i] * (1 - i / (k + 1)))
        w = np.maximum(w, (0.85 * o) * run)
    ut = plane.get("under_top")
    if ut is not None:                                   # run-off under tops and slab edges: damp 0-0.3 m
        gd = nz.gfield((H, W_), 0.12 * ppm, tuple(key) + ("bdrip",), aniso=(5.0, 1.0))   # drip points along the edge
        drip = 1.0 - 0.6 * (1.0 - nz.smoothstep(0.2, 0.8, gd))
        w = np.maximum(w, (o * 0.62 * np.clip(ut, 0, 1) ** 0.175 * drip).astype(F32))   # 0.62 at a drip point, 0.40 at 0.3 m
    w = np.maximum(w, (o * 0.40 * F.chan * (1.0 - np.exp(-F.F / 3.0))).astype(F32))   # flow channels: damp after rain
    cp = plane.get("corner_prox")
    if cp is not None:                                   # inside corners: damp 0.1-0.3 m each side
        w = np.maximum(w, (o * 0.75 * np.clip(cp / 0.6, 0, 1) ** 0.35).astype(F32))
    if ZONE_ON:                                          # round J: corner and recess bottoms (G7), top corners (F5)
        E_ = float(plane.get("_E", 0.0))
        band_, corner_, icn_, f5_ = zone_terms(plane, E_)
        dtop_, dend_, ic_d_, rb_up_ = plane_zones(plane)
        fl_ = [int(r) for r in (plane.get("floor_rows") or [])] + [int(plane.get("ground_row") or H - 1)]
        rows_ = np.arange(H)
        nearfl = np.zeros((H, 1), bool)
        for r_ in fl_:
            nearfl[:, 0] |= ((r_ - rows_) >= 0) & ((r_ - rows_) <= 1.0 * ppm)
        cbot = (ic_d_ <= 0.4) & nearfl
        z1 = G7_WET[0] * cbot * np.exp(-ic_d_ / 0.25)
        z2 = G7_WET[1] * np.exp(-np.clip(rb_up_, 0, None) / G7_RB_M) * (rb_up_ <= G7_RB_CUT)
        w = np.maximum(w, (o * z1).astype(F32))
        w = np.maximum(w, (o * z2).astype(F32))
        zw = np.maximum(z1, z2)
        if f5_ > 0:
            z3 = F5_WET * f5_ * np.clip(corner_ * 1.6, 0, 1)
            w = np.maximum(w, (o * z3).astype(F32))
            zw = np.maximum(zw, z3)
        plane["_zone_wet"] = np.clip(zw / 0.88, 0, 1).astype(F32)     # J14: for the growth stage (M2)
    w = np.maximum(w, (o * 0.62 * np.sqrt(np.clip(F.jwet, 0, 1))).astype(F32))
    for (cy, cx) in joint_crossings(plane):              # where two joints cross the wall is wettest
        ya, yb, xa, xb = max(0, cy - 3), min(H, cy + 4), max(0, cx - 3), min(W_, cx + 4)
        w[ya:yb, xa:xb] = np.maximum(w[ya:yb, xa:xb], 0.85 * o)
    if chips is not None:
        w = np.maximum(w, (0.55 * o * nz.smoothstep(0.2, 0.6, chips)).astype(F32))
    return (np.clip(w, 0, 1) * mask).astype(F32), (run * mask).astype(F32)


def bio_arrival(plane, Wt, key):
    """Years until growth shows at each pixel (99 = never). Shapes from nuclei and fronts: nuclei
    at a density rising with wetness, born around the class onset; fronts at the speed that gives
    the class its time scale (site saturation: tau = 1 / (v sqrt(pi N))), faster downward, slow on
    low-receptivity ground (a 0.15 m field), so fronts finger round it. Timing by class: within
    each class the k-th earliest cell is covered when the class curve reaches k / n, blended across
    class edges (O11 by construction; fronts keep their order, so growth is nested and outward)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W_ = mask.shape
    f = 2                                              # 4 cm cells
    h2, w2 = H // f, W_ // f
    Wd = Wt[:h2 * f, :w2 * f].reshape(h2, f, w2, f).mean(axis=(1, 3)).astype(np.float64)
    md = mask[:h2 * f, :w2 * f].reshape(h2, f, w2, f).mean(axis=(1, 3)) > 0.5
    cm = f / ppm
    r = nz.rng(*key, "bio")
    pos, tl, tau, xm = _bio_params(Wd)
    N = BIO_NUC[0] + BIO_NUC[1] * Wd ** 3               # nuclei per m2
    v = 1.0 / (tau * np.sqrt(np.pi * N))               # front speed, m per year
    g = nz.gfield((h2, w2), 0.15 * ppm / f, key + ("brec",))
    g2 = nz.gfield((h2, w2), 0.6 * ppm / f, key + ("bcost",))
    xi = r.standard_normal((h2, w2))
    cost = np.where(md, cm / v * np.exp(0.9 * g + 0.4 * g2 + 0.5 * xi), 1e4).astype(np.float64)
    lam = N * cm * cm * md
    n = int(r.poisson(float(lam.sum())))
    T = np.full((h2, w2), 1e4)
    if n > 0:
        pick = r.choice(lam.size, size=n, p=(lam / lam.sum()).ravel())
        born = tl.ravel()[pick] * r.uniform(0.6, 1.4, n)
        if BIO_STAGGER > 0:                           # colonies keep arriving after the onset
            born = born + BIO_STAGGER * tau.ravel()[pick] * r.random(n) ** BIO_STAGGER_P
        Tf = T.ravel()
        np.minimum.at(Tf, pick, born)
        T = Tf.reshape(h2, w2)
    T = arrival_time(cost, T)
    cls = np.digitize(Wd, BIO_EDGES)
    Q = np.zeros((4, h2, w2))
    for k in range(4):
        vals = np.sort(T[md & (cls == k)])
        if vals.size < 50:
            vals = np.sort(T[md])
        Q[k] = np.searchsorted(vals, T, side="right") / max(vals.size, 1)
    k0 = np.clip(np.floor(pos).astype(int), 0, 2)
    fr = pos - k0
    q = np.take_along_axis(Q, k0[None], 0)[0] * (1 - fr) + np.take_along_axis(Q, (k0 + 1)[None], 0)[0] * fr
    qq = np.clip(q / xm, 0, 1 - 1e-9)
    Tc = np.where(md & (q < xm), tl + tau * np.sqrt(-np.log(1.0 - qq)), 99.0)
    up = np.repeat(np.repeat(Tc, f, 0), f, 1)
    up = 0.25 * (up + np.roll(up, 1, 0) + np.roll(up, 1, 1) + np.roll(np.roll(up, 1, 0), 1, 1))
    tp = np.repeat(np.repeat(tau, f, 0), f, 1)
    Tfull = np.full((H, W_), 99.0, F32)
    Tfull[:h2 * f, :w2 * f] = up + 0.02 * tp * r.standard_normal(up.shape)
    return Tfull


def bio_ramp(stage):
    """The organic continuum's colour at stage 0-1 (linear RGB, per pixel)."""
    xs = np.array([k for k, _ in BIO_RAMP])
    cs = np.array([c for _, c in BIO_RAMP], F32)
    out = np.stack([np.interp(stage, xs, cs[:, i]) for i in range(3)], -1)
    return out.astype(F32)


def layer_bio(plane, F, cfg, a, key, stains=None, streaks=None, chips=None):
    """Organic growth as nucleation and outward growth (round G), timed by wetness class (the
    growth research): at amount a (years unattended, bio_years) growth covers {T <= years}, so a
    higher amount keeps a lower one's growth and extends it. Colour follows local age: yellow-green
    or dull rusty yellow, then green or orange-rust, then dark olive or rust-brown; black stripes in
    the wettest run-off; mould-dark on south faces. Returns alpha, colour, marks, and the wetness
    map (for the gate)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W_ = mask.shape
    Wt, run = bio_wetness(plane, F, stains, streaks, chips, key=key)
    if a <= 0:
        return np.zeros((H, W_), F32), None, [], Wt
    t = bio_years(a)
    Tfull = bio_arrival(plane, Wt, key)
    A = np.clip(t + BIO_A0 - Tfull, 0, None)           # local age in years (faint for the first BIO_A0)
    ahead = (Tfull > t + BIO_A0 + 0.5) & (Tfull < t + BIO_A0 + 2.0)   # satellites: colonies ahead of a front
    sat = ahead & (nz.gfield((H, W_), 0.8, key + ("bsat",)) > 1.2)
    A = np.where(sat, 1.5, A)
    if BIO_SAT2 is not None:                           # round I (C3): colonies seeded a few years ahead of the front
        lead_, ell_, thr_, age_ = BIO_SAT2
        ahead2 = (Tfull > t + BIO_A0) & (Tfull < t + BIO_A0 + lead_) & mask.astype(bool)
        sat2 = ahead2 & (nz.gfield((H, W_), ell_ * ppm, key + ("bsat2",)) > thr_)
        A = np.where(sat2, np.maximum(A, age_), A)
    rho = 1.0 - np.exp(-A / 1.0)
    u = 0.5 + 0.5 * np.tanh(nz.gfield((H, W_), 0.8, key + ("bspk",)))   # young fronts: colonies 2-4 cm
    keep = u < np.clip(0.4 + 0.6 * A, 0, 1)
    rho = np.where(A < 1.0, rho * keep, rho)
    Am = A * np.interp(Wt, BIO_W, [0.25, 0.4, 0.7, 1.0])   # biomass builds where water stays
    mott = np.clip(0.5 + 0.5 * nz.gfield((H, W_), 0.06 * ppm, key + ("bmott",)), 0, 1)   # mottled inside
    wetter = nz.smoothstep(0.30, 0.60, Wt)                 # dark crusts belong to damp and wet zones
    old = nz.smoothstep(BIO_DARK[0], BIO_DARK[1], Am) * wetter
    amax = np.interp(Wt, BIO_W, list(BIO_AMAX))   # biomass is limited by water: open wall stays a film
    alpha = (amax * (BIO_A[0] + BIO_A[1] * old) * rho * ((0.6 + 0.4 * mott) * (1 - old) + (0.9 + 0.1 * mott) * old) * mask).astype(F32)
    if ZONE_ALPHA > 0 and "_zone_wet" in plane:             # J17: thick growth where water stands (M2)
        alpha = np.minimum(alpha * (1.0 + ZONE_ALPHA * plane["_zone_wet"]), np.maximum(amax, alpha)).astype(F32)
    # colour by age and family
    fam = nz.gfield((H, W_), 0.8 * ppm, key + ("bfam",))
    cls = plane.get("cls")
    conc = np.isin(cls, (4, 5)) if cls is not None else np.zeros((H, W_), bool)
    foot = np.zeros((H, W_), bool)
    if plane.get("ground_row") is not None:
        foot = ((foot_rows(plane)[None, :] - np.arange(H)[:, None]) / ppm) < 0.3
    rust = np.where(foot, fam > np.quantile(fam, 0.85),
                    (fam > np.quantile(fam, BIO_RUST_Q)) | (conc & (fam > np.quantile(fam, 0.45))))
    yel = ~rust & (nz.gfield((H, W_), 0.5 * ppm, key + ("byel",)) > norm_ppf(BIO_YEL_Q))   # yellow family, sharp-edged
    s0 = nz.smoothstep(0.0, 1.3, A)[..., None]
    s1 = nz.smoothstep(1.3, 4.8, Am)[..., None]
    s2 = (nz.smoothstep(BIO_DARK[0], BIO_DARK[1], Am) * wetter)[..., None]
    C_ = {k_: np.array(COL["bio_" + k_], F32) for k_ in ("G1", "G2", "G2y", "G3", "G4", "G4r", "Tr", "Cy", "Fu",
                                                          "Y1", "Y3", "Y4")}
    green = C_["G1"] + (C_["G2"] - C_["G1"]) * s0
    green = green + (C_["G3"] - green) * s1
    green = green + (C_["G4"] - green) * s2
    rusty = C_["G2y"] + (C_["Tr"] - C_["G2y"]) * s1
    rusty = rusty + (C_["G4r"] - rusty) * s2
    yellow = C_["G1"] + (C_["Y1"] - C_["G1"]) * s0          # lichen-like yellow: young yellow, ochre, dark ochre-olive
    yellow = yellow + (C_["Y3"] - yellow) * s1
    yellow = yellow + (C_["Y4"] - yellow) * s2
    col = np.where(rust[..., None], rusty, np.where(yel[..., None], yellow, green))
    if BIO_CONTINUUM:
        jit = nz.gfield((H, W_), 0.6 * ppm, key + ("bstage",))
        stage = np.clip(BIO_STAGE[0] + (1 - BIO_STAGE[0]) * nz.smoothstep(0.0, BIO_STAGE[1], Am) + BIO_STAGE[2] * jit
                        + ZONE_STAGE * plane.get("_zone_wet", 0.0) * (Am > 0), 0, 1)
        col = bio_ramp(stage)
    dry = (0.45 * nz.smoothstep(0.50, 0.20, Wt))[..., None]   # dry films stay lighter, hue toward yellow-olive
    if BIO_DRY_FAM:                                      # toward 90 deg from either side: green stays green-yellow
        dcol = np.where(rust[..., None], np.array(COL["bio_dry_r"], F32), np.array(COL["bio_dry_g"], F32))
    else:
        dcol = np.array(COL["bio_dry"], F32)
    col = col + (dcol - col) * dry
    if BIO_INK_PATH and streaks is not None and plane.get("orient") == "S":
        ink = np.zeros((H, W_, 1), F32)                  # south faces grow moulds (O8), not ink stripes
    elif BIO_INK_PATH and streaks is not None:           # ink stripes: old growth on the run-off paths (O2)
        kp = max(1, int(0.3 * ppm))
        sp = np.asarray(streaks, F32).copy()
        for i in range(1, kp + 1):
            sp[i:] = np.maximum(sp[i:], streaks[:-i] * (1.0 - i / (kp + 1.0)))
        ink = (BIO_INK_P[0] * nz.smoothstep(BIO_INK_P[1], BIO_INK_P[2], Am) * nz.smoothstep(BIO_INK_P[3], BIO_INK_P[4], sp))[..., None]
    else:
        ink = (BIO_INK[0] * nz.smoothstep(BIO_INK[1], BIO_INK[2], Am) * nz.smoothstep(BIO_INK[3], BIO_INK[4], run))[..., None]
    col = col + (C_["Cy"] - col) * ink
    if plane.get("orient") == "S":                     # moulds rather than green algae
        col = col + (C_["Fu"] - col) * (BIO_SOUTH_FU * s2)
        grey = col.mean(axis=-1, keepdims=True)
        col = col + (grey - col) * BIO_SOUTH_GREY
    return alpha, col.astype(F32), [], Wt


RUST_SHARE = ((0.25, 0.5, 0.75, 1.0), (0.05, 0.10, 0.20, 0.40))   # rusted share of the steel at the control's
# steps, x2 a step (L3): ISO 4628-3 Ri3-4, Ri4, Ri4-5, Ri5 (round H: round G's 0.25-8 % over 0.25-0.75 read 'too little')
RUST_RUN_P = (0.20, 0.80)    # chance of a run below a post: a0 + a1 x amount
RUST_RUN_OP = 0.60           # run opacity x amount ** 0.5
RUST_EDGE_RUNS = 1.6         # runs per m of rusted lower rail edge, x amount
RUST_AGE = (0.2, 0.8)        # older rust: darker brown, from this share of the deepest rust at 0 to the most at 1


def rust_share(a):
    """Rusted share of the metal for rust amount a (log-linear between the RUST_SHARE steps)."""
    xs, ys = RUST_SHARE
    if a <= 0:
        return 0.0
    if a < xs[0]:
        return float(ys[0] * (a / xs[0]) ** 2)
    if a > xs[-1]:
        return float(min(0.75, ys[-1] * a / xs[-1]))
    return float(np.exp(np.interp(a, xs, np.log(ys))))


RUST_FLOW = "arrival"        # round I: rust by first arrival along the members from the wet parts (rust_flow.py,
                             # research weathering-rust-water.md); True: the time-of-wetness score of the first round-I pass
RUST_FLOW_K = (2.2, 0.55, 0.35)   # score: wetness, noise along the element, fine noise
RUST_CONC = (0.35, 0.65, 0.55)    # runs on the concrete below rusted feet: chance a0 + a1 x amount, opacity x amount ** 0.5


def rail_wetness(plane, metal):
    """Time of wetness on the steel (0-1) and which pixels belong to horizontal rails. The bottom
    rail holds water and debris (highest), the junctions where bars meet a rail are next, the top
    rail's upper face holds water, and on the bars the water runs down, wetter toward the foot."""
    ppm = plane["ppm"]
    H, W = metal.shape
    m = metal.astype(np.int32)
    # horizontal runs: length of the steel run along each row
    run = np.zeros((H, W), np.int32)
    for y in range(H):
        row = m[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row, [0]]))
        st_, en_ = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        for a_, b_ in zip(st_, en_):
            run[y, a_:b_] = b_ - a_
    horiz = metal & (run >= int(0.30 * ppm))
    vert = metal & ~horiz
    tow = np.zeros((H, W), F32)
    # a horizontal rail with bars above it is a bottom rail (collects); otherwise a top rail
    above = np.zeros((H, W), bool)
    for k in range(1, 4):
        above[k:] |= vert[:-k]
    below = np.zeros((H, W), bool)
    for k in range(1, 4):
        below[:-k] |= vert[k:]
    lab_rows = horiz.copy()
    bottom = horiz & above & ~below
    top_face = horiz.copy()
    top_face[1:] &= ~horiz[:-1]                         # the rail's upper face: no rail pixel above
    tow = np.where(horiz, 0.55, tow)
    tow = np.where(bottom, 0.85, tow)
    tow = np.where(top_face, np.maximum(tow, 0.70), tow)
    # bars: fraction down their run, junction boosts
    vy = np.zeros((H, W), F32)
    vl = np.ones((H, W), F32)
    for x in range(W):
        col = vert[:, x]
        if not col.any():
            continue
        d = np.diff(np.concatenate([[0], col.astype(np.int8), [0]]))
        st_, en_ = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        for a_, b_ in zip(st_, en_):
            n_ = b_ - a_
            vy[a_:b_, x] = (np.arange(n_) + 0.5) / n_
            vl[a_:b_, x] = n_
    j = int(round(0.04 * ppm))
    near_top = np.zeros((H, W), bool)                   # bar pixels within 4 cm below a rail
    near_bot = np.zeros((H, W), bool)                   # and within 4 cm above one
    for k in range(1, j + 2):
        near_top[k:] |= horiz[:-k]
        near_bot[:-k] |= horiz[k:]
    tow = np.where(vert, 0.30 + 0.30 * vy, tow)
    tow = np.where(vert & near_top, np.maximum(tow, 0.62), tow)    # drips from the top rail onto the bars
    tow = np.where(vert & near_bot, np.maximum(tow, 0.88), tow)    # the bars' feet at the bottom rail
    foot = vert & (vy > 1.0 - 2.0 / np.maximum(vl, 1))             # a bar's last pixels: an anchor or a foot
    tow = np.where(foot, np.maximum(tow, 0.92), tow)
    return (tow * metal).astype(F32), horiz


def rust_runs_concrete(plane, metal, rmask, a, acc, key):
    """Rust runs on the concrete below rusted steel that ends on it (post feet, bar feet, the bottom
    rail over the slab edge), following the rain down the face."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    cls = plane.get("cls")
    out = []
    ends = np.zeros((H, W), bool)
    ends[:-1] = rmask[:-1] & ~metal[1:] & mask[1:] & np.isin(cls[1:], (1, 2))
    ys, xs = np.nonzero(ends)
    if not ys.size:
        return out
    r = nz.rng(*key, "conc_runs")
    take = r.random(ys.size) < RUST_CONC[0] + RUST_CONC[1] * a
    for j in np.flatnonzero(take):
        rj = nz.rng(*key, "cr", int(ys[j]), int(xs[j]))
        yb, xc = int(ys[j]) + 1, int(xs[j])
        room = region_below(mask, yb, xc, H)
        if room < 0.04 * ppm:
            continue
        ln = min(room / ppm, rj.uniform(0.12, 0.7) * (0.5 + 1.2 * a))
        ok, info = stamp_run(acc, mask, ppm, xc, yb, ln, rj.uniform(0.008, 0.02), rj.uniform(0.02, 0.06),
                             RUST_CONC[2] * a ** 0.5 * rj.uniform(0.6, 1.0), key + ("crr", int(ys[j]), int(xs[j])),
                             striate=0.3, tail=rj.uniform(0.4, 0.8))
        if ok:
            info["kind"] = "rust_conc"
            out.append(info)
    return out


def layer_rust(plane, F, cfg, a, key, spalls=None, flow=None):
    """Rust from fixings (a bloom and a run), where a spall shows its bar a bleed from the break's
    lowest rim down the wall, and on the rails: rust by ISO grade from the metal's edges and lower
    parts, older rust darker, with runs below the posts and the rusted lower edges (round H).
    Returns alpha, colour (H, W, 3) and marks."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    marks = []
    if a <= 0:
        return acc, None, marks
    oldw = np.zeros((H, W), F32)                        # weight of the old (dark) rust colour
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
    # rails (round G, research X1): rust on the metal by ISO grade, and rust runs below posts
    cls = plane.get("cls")
    flow_col = None
    if cls is not None and a > 0 and RUST_FLOW == "arrival":
        metal = plane["steel"] if plane.get("steel") is not None else cls == 7
        if metal.any():
            import rust_flow as rfl
            pre, Ts = flow if flow is not None else (None, None)          # the building's clock (Builder)
            acc_r, flow_col, mk, _st = rfl.layer(plane, metal, a, rust_share(a), key, pre=pre, Ts=Ts)
            plane["_rust_extra"] = {k_: _st.get(k_) for k_ in ("run_a", "run_c", "bare_a", "bare_c")}   # round J
            marks.extend(mk)
            # spall bleeds (acc so far, plain rust colour) under the flow layer
            c_sp = np.array(COL["rust"], F32)
            na = acc + acc_r * (1.0 - acc)
            flow_col = ((c_sp[None, None, :] * (acc * (1.0 - acc_r))[..., None] + flow_col * acc_r[..., None])
                        / np.maximum(na, 1e-6)[..., None]).astype(F32)
            acc = na.astype(F32)
    elif cls is not None and a > 0:
        metal = plane["steel"] if plane.get("steel") is not None else cls == 7    # steel rusts; aluminium sashes do not
        if metal.any():
            share = rust_share(a)
            from weather_measure import gauss
            low0 = np.zeros((H, W), bool)                                    # the metal's lower edges: water sits there
            low0[:-1] = metal[:-1] & ~metal[1:]
            if RUST_FLOW:                                                    # round I: rust follows the water
                tow, horiz = rail_wetness(plane, metal)
                along = np.where(horiz, nz.gfield((H, W), 0.03 * ppm, key + ("rail_h",), aniso=(1.0, 12.0)),
                                 nz.gfield((H, W), 0.03 * ppm, key + ("rail_v",), aniso=(10.0, 1.0)))
                z = RUST_FLOW_K[0] * tow + RUST_FLOW_K[1] * along + RUST_FLOW_K[2] * nz.gfield((H, W), 0.6, key + ("rail2",))
            else:
                inner = gauss(metal.astype(F32), 0.04 * ppm)                 # low at the metal's edges
                low = gauss(low0.astype(F32), 0.12 * ppm)
                z = (0.7 * nz.gfield((H, W), 0.6, key + ("rail",)) + 0.5 * nz.gfield((H, W), 0.08 * ppm, key + ("rail2",))
                     + 1.6 * (1.0 - np.clip(inner * 2.0, 0, 1)) + 1.2 * np.clip(low / max(float(low.max()), 1e-6), 0, 1))
            thr = np.quantile(z[metal], 1.0 - min(0.95, share))
            deep = nz.smoothstep(thr, thr + 1.2, z)
            ra = np.clip(0.55 + 0.40 * deep, 0, 0.92)                         # speckled at its front, dense inward
            rmask = metal & (z > thr)
            acc = np.maximum(acc, np.where(rmask, ra, 0.0).astype(F32))
            oldw = np.where(rmask, np.clip(RUST_AGE[0] + (RUST_AGE[1] - RUST_AGE[0]) * a, 0, 1) * deep, oldw).astype(F32)
            if RUST_FLOW:                                                    # runs onto the concrete below post feet and the bottom rail
                for info in rust_runs_concrete(plane, metal, rmask, a, acc, key):
                    marks.append(info)
            ys_, xs_ = np.nonzero(low0 & rmask)                              # runs from the rusted lower edges
            if ys_.size:
                r = nz.rng(*key, "edge_runs")
                n = r.poisson(RUST_EDGE_RUNS * a * ys_.size / ppm)
                for j, i in enumerate(r.choice(ys_.size, size=min(int(n), ys_.size), replace=False)):
                    yb, xc = int(ys_[i]) + 1, int(xs_[i])
                    room = region_below(mask, yb, xc, H)
                    if room > 0.04 * ppm and cls[min(yb, H - 1), xc] != 7:
                        ok, info = stamp_run(acc, mask, ppm, xc, yb, min(room / ppm, r.uniform(0.1, 0.6) * (0.5 + a)),
                                             r.uniform(0.008, 0.02), r.uniform(0.015, 0.04), 0.45 * a ** 0.5,
                                             key + ("er", j), striate=0.3)
                        if ok:
                            marks.append(info)
            from weather_measure import label
            lab, n = label(metal)
            if n:
                ys, xs = np.nonzero(lab)
                ll = lab[ys, xs]
                y1 = np.full(n + 1, -1)
                np.maximum.at(y1, ll, ys)
                x0 = np.full(n + 1, W)
                x1 = np.full(n + 1, -1)
                np.minimum.at(x0, ll, xs)
                np.maximum.at(x1, ll, xs)
                for i in range(1, n + 1):
                    if x1[i] - x0[i] > 0.12 * ppm:                    # posts: narrow uprights
                        continue
                    r = nz.rng(*key, "post", i)
                    if r.random() > RUST_RUN_P[0] + RUST_RUN_P[1] * a:
                        continue
                    yb, xc = int(y1[i]) + 1, int((x0[i] + x1[i]) // 2)
                    room = region_below(mask, yb, xc, H)
                    if room > 0.05 * ppm:
                        ok, info = stamp_run(acc, mask, ppm, xc, yb, min(room / ppm, r.uniform(0.3, 1.0) * (0.6 + a)),
                                             max(0.01, (x1[i] - x0[i] + 1) / ppm), 3.0 * max(0.01, (x1[i] - x0[i] + 1) / ppm),
                                             RUST_RUN_OP * a ** 0.5, key + ("pr", i), striate=0.3)
                        if ok:
                            marks.append(info)
    for (y, x, kind) in plane.get("fixings", []):
        if kind == "alu":                                # aluminium sash fixings do not rust (round H)
            continue
        if kind == "post" and RUST_FLOW == "arrival":     # the flow layer stains below the post feet
            continue
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
    c0, c1 = np.array(COL["rust"], F32), np.array(COL["rust_bar"], F32)
    col = (c0 + (c1 - c0) * oldw[..., None]).astype(F32)            # older rust on the metal is darker brown
    if flow_col is not None:
        col = np.where((flow_col.sum(axis=-1) > 0)[..., None], flow_col, col).astype(F32)
    return np.clip(acc, 0, 0.92), col, marks


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


def _old_layer_cracks(plane, F, cfg, a, key):
    """Round F's cracks (kept for reference): random walks from re-entrant corners and map starts."""
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


def plane_openings(plane):
    """Window and door openings as boxes (y0, x0, y1, x1) from the class map: glass and metal
    (frames, doors) merged per opening, and holes inside the plane; 0.3-4 m, mostly rectangular.
    Cached on the plane."""
    if "_openings" in plane:
        return plane["_openings"]
    from weather_measure import label
    cls, ppm = plane.get("cls"), plane["ppm"]
    out = []
    if cls is not None:
        H, W = cls.shape
        for kinds, grow in (((6,), 3), ((7,), 0), ((0,), 0)):   # glass panes merged per window; doors; holes
            o = np.isin(cls, kinds)
            if grow:
                for ax in (0, 1):
                    o2 = o.copy()
                    for s_ in range(1, grow + 1):
                        if ax == 0:
                            o2[s_:] |= o[:-s_]
                            o2[:-s_] |= o[s_:]
                        else:
                            o2[:, s_:] |= o[:, :-s_]
                            o2[:, :-s_] |= o[:, s_:]
                    o = o2
            lab, n = label(o)
            if n == 0:
                continue
            ys, xs = np.nonzero(lab)
            ll = lab[ys, xs]
            y0 = np.full(n + 1, H)
            x0 = np.full(n + 1, W)
            y1 = np.full(n + 1, -1)
            x1 = np.full(n + 1, -1)
            np.minimum.at(y0, ll, ys)
            np.minimum.at(x0, ll, xs)
            np.maximum.at(y1, ll, ys)
            np.maximum.at(x1, ll, xs)
            cnt = np.bincount(ll, minlength=n + 1)
            for i in range(1, n + 1):
                h, w = (y1[i] - y0[i] + 1) / ppm, (x1[i] - x0[i] + 1) / ppm
                fill = cnt[i] / max(1, (y1[i] - y0[i] + 1) * (x1[i] - x0[i] + 1))
                if not (0.3 <= h <= 3.5 and 0.3 <= w <= 4.0 and fill >= 0.6):
                    continue
                if y0[i] <= 1 or x0[i] <= 1 or y1[i] >= H - 2 or x1[i] >= W - 2:
                    continue
                out.append((int(y0[i]), int(x0[i]), int(y1[i]), int(x1[i])))
    plane["_openings"] = out
    return out


def crack_alpha(w_mm):
    """Opacity of a crack's 1 px line at 20 mm/px from its width, halo included (research 3.6)."""
    return np.clip(0.10 * (np.asarray(w_mm, np.float64) / 0.2) ** 0.7, 0.0, 0.75)


class CrackSet:
    """Cracks on a plane: traced paths rasterised into opacity, width (mm), type and orientation
    maps; an id map for T junctions."""

    def __init__(self, plane):
        cls = plane.get("cls")
        self.mask = plane["mask"] & (np.isin(cls, (1, 2, 4, 5)) if cls is not None else True)   # never across glass or doors
        self.ppm = plane["ppm"]
        H, W = self.mask.shape
        self.H, self.W = H, W
        self.acc = np.zeros((H, W), F32)
        self.wmm = np.zeros((H, W), F32)
        self.typ = np.zeros((H, W), np.uint8)
        self.ori = np.zeros((H, W), np.uint8)
        self.ids = np.zeros((H, W), np.int32)
        self.rep = np.zeros((H, W), F32)
        self.n = 0
        self.paths = []

    def near(self, y, x, me, r=2):
        H, W = self.H, self.W
        ya, yb, xa, xb = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
        v = self.ids[ya:yb, xa:xb]
        hit = (v > 0) & (v != me)
        if not hit.any():
            return None
        yy, xx = np.nonzero(hit)
        k = np.argmin((yy + ya - y) ** 2 + (xx + xa - x) ** 2)
        return int(yy[k] + ya), int(xx[k] + xa)

    def trace(self, y, x, ang, L_m, pref, rng_, persist=0.25, sig=0.14, stop=True, box=None):
        """Walk from (y, x) at angle ang (x right, y down) for up to L_m, relaxing toward pref with
        the persistence and wobble per step; stops at the mask edge or the box; a tip within 4 px
        of another crack turns to it and stops (a T). Returns (ys, xs, joined)."""
        H, W, ppm = self.H, self.W, self.ppm
        me = self.n + 1
        py, px = float(y), float(x)
        ys, xs = [], []
        joined = False
        n = int(L_m * ppm)
        for s_ in range(n):
            d = np.arctan2(np.sin(pref - ang), np.cos(pref - ang))
            ang += persist * d + rng_.normal(0.0, sig)
            px += np.cos(ang)
            py += np.sin(ang)
            iy, ix = int(round(py)), int(round(px))
            if not (0 <= iy < H and 0 <= ix < W) or not self.mask[iy, ix]:
                break
            if box is not None and not (box[0] <= iy <= box[2] and box[1] <= ix <= box[3]):
                break
            if not ys or (iy, ix) != (ys[-1], xs[-1]):
                ys.append(iy)
                xs.append(ix)
            if stop and s_ > 6:
                ly, lx = int(round(py + 4 * np.sin(ang))), int(round(px + 4 * np.cos(ang)))
                hit = self.near(ly, lx, me)
                if hit is not None:
                    hy, hx = hit
                    m_ = max(abs(hy - iy), abs(hx - ix))
                    for t in range(1, m_ + 1):
                        ys.append(int(round(iy + (hy - iy) * t / m_)))
                        xs.append(int(round(ix + (hx - ix) * t / m_)))
                    joined = True
                    break
        return np.array(ys, np.int64), np.array(xs, np.int64), joined

    def draw(self, ys, xs, w0, kind, rng_, free_start=False, free_end=True, repaired=False, shift=0.0):
        """Rasterise a path: width w0 (mm) varying along it (CoV about 0.3), tapering at free ends."""
        n = ys.size
        if n < 3:
            return False
        self.n += 1
        t = np.linspace(0.0, 1.0, n)
        tap = np.ones(n)
        if free_end:
            tap = np.minimum(tap, np.clip((1.0 - t) / 0.18, 0.0, 1.0) ** 0.7)
        if free_start:
            tap = np.minimum(tap, np.clip(t / 0.15, 0.0, 1.0) ** 0.7)
        k = max(3, n // 6)
        v = np.convolve(rng_.standard_normal(n + 2 * k), np.ones(k) / k, mode="same")[k:k + n]
        w = w0 * np.exp(0.30 * v / max(v.std(), 1e-6)) * np.maximum(tap, 0.05)
        al = crack_alpha(w).astype(F32)
        if repaired:
            al = al * 0.3
            sh = np.zeros(n, F32) + shift
            for dy, dx in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = np.clip(ys + dy, 0, self.H - 1), np.clip(xs + dx, 0, self.W - 1)
                self.rep[yy, xx] = sh
        kk = min(4, max(1, n // 4))
        ip = np.clip(np.arange(n) + kk, 0, n - 1)
        im = np.clip(np.arange(n) - kk, 0, n - 1)
        dy_, dx_ = (ys[ip] - ys[im]).astype(np.float64), (xs[ip] - xs[im]).astype(np.float64)
        o = (np.degrees(np.arctan2(-dy_, dx_)) % 180.0).astype(np.uint8)
        cur = self.acc[ys, xs]
        upd = al > cur
        self.acc[ys[upd], xs[upd]] = al[upd]
        self.wmm[ys, xs] = np.maximum(self.wmm[ys, xs], w.astype(F32))
        self.typ[ys, xs] = np.where(self.typ[ys, xs] == 0, kind + (16 if repaired else 0), self.typ[ys, xs])
        self.ori[ys, xs] = o
        self.ids[ys, xs] = self.n
        self.paths.append((kind, n, repaired))
        return True


def layer_cracks(plane, F, cfg, a, key):
    """Cracks from hairline to pattern cracks (round G; research 7.4): corner cracks at openings,
    vertical cracks in solid panels and parapets, horizontal cracks along floor joints, and from
    a = 0.35 pattern cracks with T junctions. Every candidate is drawn at amount 1 in a fixed order
    with its own keyed draws and kept when its draw is under the amount's probability, so a lower
    amount's cracks are the first of a higher one's; lengths grow with the amount. Returns the
    opacity, None, marks and the CrackSet (width, type, orientation and repair maps)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    cs = CrackSet(plane)
    if a <= 0:
        return cs.acc, None, [], cs
    med = 0.10 + 0.45 * a                                  # median width (mm) of the primary cracks, C4

    def width(r_):
        return float(med * np.exp(0.55 * r_.standard_normal()))

    def repair(r_, w0):
        return w0 >= 0.15 and r_.random() < float(np.clip(0.80 - 0.60 * a, 0.15, 0.9))

    cols = np.flatnonzero(mask.any(axis=0))
    x_lo, x_hi = (int(cols[0]), int(cols[-1])) if cols.size else (0, W - 1)
    gr = plane.get("ground_row") or H - 1
    fr = sorted(int(v) for v in (plane.get("floor_rows") or []))
    low2 = fr[-3] if len(fr) >= 3 else 0                   # the lowest two storeys
    # 1. corner cracks: a diagonal leg at 45 +- 15 deg for 0.5-1 opening width, then toward vertical
    ops = plane_openings(plane)
    for i, (y0, x0, y1, x1) in enumerate(ops):
        ow = (x1 - x0 + 1) / ppm
        for j, (cy, cx, sy, sx) in enumerate(((y0, x0, -1, -1), (y0, x1, -1, 1), (y1, x0, 1, -1), (y1, x1, 1, 1))):
            r_ = nz.rng(*key, "cc", i, j)
            u, ang_j, lu, wv, ur = r_.random(), r_.normal(0.0, 0.26), r_.uniform(0.3, 1.0), r_, r_.random()
            p = 0.08 + 0.35 * a
            if cy > low2 or min(cx - x_lo, x_hi - cx) < 6.0 * ppm:
                p *= 1.3
            if u > p:
                continue
            ang = np.arctan2(sy, sx) + ang_j
            L_all = min(2.5, lu * ow * (1.0 + 1.0 * a))
            L_d = min(L_all, r_.uniform(0.5, 1.0) * ow)
            ys, xs, j_ = cs.trace(cy + 2 * sy, cx + 2 * sx, ang, L_d, ang, r_, persist=0.08, sig=0.06)
            if not j_ and ys.size >= 2 and L_all - L_d > 0.05:
                ang2 = float(np.arctan2(ys[-1] - ys[max(0, ys.size - 6)], xs[-1] - xs[max(0, xs.size - 6)]))
                ys2, xs2, j_ = cs.trace(int(ys[-1]), int(xs[-1]), ang2, L_all - L_d, np.pi / 2 * sy, r_,
                                        persist=0.04, sig=0.08)
                ys, xs = np.concatenate([ys, ys2]), np.concatenate([xs, xs2])
            w0 = width(r_)
            cs.draw(ys, xs, w0, 1, r_, free_end=not j_, repaired=repair(r_, w0), shift=r_.choice([-1, 1]) * r_.uniform(0.02, 0.04))
    # 2. vertical cracks in solid panels, by storey; parapet cracks
    bands = list(zip(fr[:-1], fr[1:])) if len(fr) >= 2 else []
    if plane.get("top_row") is not None and fr:
        bands.append((int(plane["top_row"]), fr[0]))
    for bi, (r0, r1) in enumerate(bands):
        if r1 - r0 < 0.4 * ppm:
            continue
        para = r0 == plane.get("top_row")
        rb = nz.rng(*key, "vb", bi)
        x = x_lo + rb.uniform(0.5, 3.0) * ppm
        k = 0
        while x < x_hi:
            xi = int(x)
            r_ = nz.rng(*key, "vc", bi, k)
            u, up = r_.random(), r_.random() < 0.5
            solid = mask[r0:r1, xi].mean() > 0.9 and np.isin(plane["cls"][r0:r1, xi], (1, 2, 4, 5)).mean() > 0.9 \
                if plane.get("cls") is not None else mask[r0:r1, xi].mean() > 0.9
            if solid and u < (0.20 + 0.70 * a if para else 0.30 + 0.65 * a):
                Lm = (r1 - r0) / ppm * r_.uniform(0.5, 1.0) * (0.8 + 0.5 * a)
                y_s = r1 - 3 if up else r0 + 3
                ys, xs, j_ = cs.trace(y_s, xi, -np.pi / 2 if up else np.pi / 2, Lm, -np.pi / 2 if up else np.pi / 2,
                                      r_, persist=0.3, sig=0.14)
                w0 = width(r_)
                cs.draw(ys, xs, w0, 2, r_, free_end=not j_, repaired=repair(r_, w0), shift=r_.choice([-1, 1]) * r_.uniform(0.02, 0.04))
            x += (rb.uniform(1.0, 3.0) if para else rb.uniform(1.2, 4.5)) * ppm
            k += 1
    # 3. horizontal cracks along floor joints
    jh = plane.get("joint_h")
    if jh is not None and jh.any():
        rows = np.flatnonzero(jh.any(axis=1))
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if rows.size else []
        for gi, g in enumerate(groups):
            y = int(g[-1]) + 1
            xs_j = np.flatnonzero(jh[g[0]])
            if xs_j.size == 0 or y >= H:
                continue
            r_g = nz.rng(*key, "hj", gi)
            span = xs_j[-1] - xs_j[0]
            x = xs_j[0] + r_g.uniform(0.0, 2.0) * ppm
            k = 0
            while x < xs_j[-1]:
                r_ = nz.rng(*key, "hc", gi, k)
                u, Lm = r_.random(), r_.uniform(0.5, 3.0)
                if u < 0.05 + 0.35 * a:
                    ys, xs, j_ = cs.trace(y, int(x), 0.0, Lm, 0.0, r_, persist=0.5, sig=0.05, stop=False)
                    w0 = width(r_) * 0.8
                    cs.draw(ys, xs, w0, 3, r_, free_start=True, repaired=repair(r_, w0), shift=r_.choice([-1, 1]) * r_.uniform(0.02, 0.04))
                x += (Lm + r_g.uniform(0.3, 2.5)) * ppm
                k += 1
    # 4. hairline shrinkage cracks: short, mostly vertical, 0.05-0.15 mm (dark only where dirt
    #    finds them), about 0.7 + 0.1 a per m2 of wall: wider cracks take over with the amount (C4)
    area = mask.sum() / ppm ** 2
    ys_h, xs_h = np.nonzero(cs.mask[::5, ::5])
    # an opening corner's outward quadrant within 0.8 opening widths: hairlines there follow the
    # corner diagonal (C8: diagonal length within one opening width of a corner)
    cz_d = np.full(ys_h.size, np.inf)
    cz_y = np.zeros(ys_h.size)
    cz_x = np.zeros(ys_h.size)
    for (y0, x0, y1, x1) in ops:
        ow_px = max(1.0, float(x1 - x0 + 1))
        for (cy, cx, sy, sx) in ((y0, x0, -1, -1), (y0, x1, -1, 1), (y1, x0, 1, -1), (y1, x1, 1, 1)):
            yy, xx = ys_h * 5.0 - cy, xs_h * 5.0 - cx
            q = (np.sign(yy) == sy) & (np.sign(xx) == sx)
            dd = np.where(q, np.hypot(yy, xx) / ow_px, np.inf)
            upd = dd < cz_d
            cz_d, cz_y, cz_x = np.where(upd, dd, cz_d), np.where(upd, sy, cz_y), np.where(upd, sx, cz_x)
    if ys_h.size:
        n1 = int(area * 1.2)
        pick = nz.rng(*key, "hl").choice(ys_h.size, size=max(1, n1))
        keep_n = int(round(area * (0.7 + 0.1 * a)))
        for hi_, j in enumerate(pick[:keep_n]):
            r_ = nz.rng(*key, "hlc", hi_)
            u_d, u_c = r_.random(), r_.random()
            if cz_d[j] <= 0.8 and u_c < 0.8:                  # along the corner diagonal, either way
                ang = np.arctan2(cz_y[j], cz_x[j]) + r_.normal(0.0, 0.2) + (np.pi if r_.random() < 0.5 else 0.0)
            elif u_d < 0.64:
                ang = np.pi / 2 if r_.random() < 0.5 else -np.pi / 2
            elif u_d < 0.92:
                ang = 0.0 if r_.random() < 0.5 else np.pi
            else:
                ang = r_.uniform(0, np.pi)
            ys, xs, j_ = cs.trace(int(ys_h[j] * 5), int(xs_h[j] * 5), ang, r_.uniform(0.2, 0.8), ang, r_,
                                  persist=0.2, sig=0.16)
            cs.draw(ys, xs, float(0.07 * np.exp(0.4 * r_.standard_normal())), 5, r_, free_start=True, free_end=not j_)
    # 5. pattern cracks: patches split recursively (T junctions), from a = 0.35
    if a > 0.35:
        n1 = int(area * 0.05)                                # candidates at amount 1
        frac = (a - 0.35) / 0.65
        ys_m, xs_m = np.nonzero(mask[::4, ::4])
        if ys_m.size:
            wgt = F.C[ys_m * 4, xs_m * 4].astype(np.float64) ** 1.5
            pick = nz.rng(*key, "mp").choice(ys_m.size, size=max(1, n1), p=wgt / wgt.sum())
            for pi_, j in enumerate(pick[:int(round(n1 * frac))]):
                r_ = nz.rng(*key, "mpatch", pi_)
                cy, cx = int(ys_m[j] * 4), int(xs_m[j] * 4)
                R = r_.uniform(0.6, 2.0) * (0.6 + 0.8 * a) * ppm
                box = (max(0, int(cy - R)), max(0, int(cx - R)), min(H - 1, int(cy + R)), min(W - 1, int(cx + R)))
                cell = r_.uniform(0.25, 0.6) * ppm
                prep = r_.random() < float(np.clip(0.35 - 0.20 * a, 0.10, 0.35))   # a repaired patch
                psh = r_.choice([-1, 1]) * r_.uniform(0.02, 0.04)
                stack = [(box, med * 1.3, 0)]
                while stack:
                    (by0, bx0, by1, bx1), w_, dep_ = stack.pop()
                    hh, ww = by1 - by0, bx1 - bx0
                    if max(hh, ww) < cell or dep_ > 7:
                        continue
                    f_ = r_.uniform(0.35, 0.65)
                    if ww >= hh:
                        xc = int(bx0 + f_ * ww)
                        ys, xs, j_ = cs.trace(by0, xc, np.pi / 2, hh / ppm * 1.2, np.pi / 2, r_, persist=0.25, sig=0.12,
                                              box=(by0, bx0, by1, bx1))
                        kids = [((by0, bx0, by1, xc), ), ((by0, xc, by1, bx1), )]
                    else:
                        yc = int(by0 + f_ * hh)
                        ys, xs, j_ = cs.trace(yc, bx0, 0.0, ww / ppm * 1.2, 0.0, r_, persist=0.25, sig=0.12,
                                              box=(by0, bx0, by1, bx1))
                        kids = [((by0, bx0, yc, bx1), ), ((yc, bx0, by1, bx1), )]
                    if ys.size:
                        dd = np.hypot(ys - cy, xs - cx) / R
                        keep = dd < 1.0 + 0.25 * nz.rng(*key, "mpk", pi_, int(ys[0]), int(xs[0])).standard_normal()
                        ys, xs = ys[keep], xs[keep]
                    cs.draw(ys, xs, w_, 4, r_, free_start=True, free_end=not j_, repaired=prep, shift=psh)
                    for (kb,) in kids:
                        stack.append((kb, max(0.06, w_ * r_.uniform(0.85, 0.95)), dep_ + 1))
    marks = [{"kind": k_, "px": n_, "repaired": rp} for (k_, n_, rp) in cs.paths]
    return np.clip(cs.acc, 0, 0.8) * mask, None, marks, cs


def layer_wear(plane, F, cfg, a, key):
    """Edges (round G; research cracks-edges-damage 5.5): at the facade scale an arris reads through
    its 1 px edge row, not a bevel. Tops (copings, slab and sill tops) lighter: chalked and
    rain-washed (at most +5 L*); drip and lower edges and side arrises darker and warmer: dirt.
    The band runs along 48 % of each edge at 0.25; above 0.25 each step of 0.25 widens it x EDGE_G and
    deepens it x EDGE_P (1.27 and 1.1: 96 % and an edge-row delta L* about 12 at 1.0, from 4.3 at 0.25,
    so each step widens coverage and is visible, L1 and L2); visible chips 20-60 mm across at 0.09 per m
    of edge at 0.25 to 0.9 per m at 1.0, clustered, exposing older paint or concrete. Not on dark
    substrates (G2). Returns alpha, per-pixel colour, chip marks."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    if a <= 0 or "edges" not in plane:
        return np.zeros((H, W), F32), None, []
    e = plane["edges"] & mask
    cls = plane.get("cls")
    if cls is not None:
        e &= ~np.isin(cls, (4, 5, 6, 7))
    tops = e & plane.get("tops", np.zeros((H, W), bool))
    bots = e & plane.get("bottoms", np.zeros((H, W), bool))
    side = e & ~tops & ~bots
    # band continuity (N2: 40-70 % at 0.25, 85-100 % at 1.0), x EDGE_G a step so each step widens (L1)
    gs = (a - 0.25) / 0.25
    c = min(1.0, EDGE_C0 * EDGE_G ** gs) if a >= 0.25 else EDGE_C0 * a / 0.25
    brk = nz.gfield((H, W), 0.25 * ppm, key + ("brk",))
    keep = brk > np.quantile(brk[e], 1.0 - c) if e.any() else np.zeros((H, W), bool)
    dl = EDGE_K * (2.8 + 7.7 * a) / max(c, 0.45)              # band contrast so the mean edge row meets N1
    if EDGE_P > 0 and a > 0.25:                               # above 0.25 each step also deepens the band (L2)
        dl = EDGE_K * (2.8 + 7.7 * 0.25) / max(EDGE_C0, 0.45) * EDGE_P ** gs
    alpha = np.zeros((H, W), F32)
    col = np.zeros((H, W, 3), F32)
    chalk = np.array(COL["edge_chalk"], F32)
    dirt = np.array(COL["edge_dirt"], F32)
    lighter = tops                                            # chalked, rain-washed tops
    bots = bots | side                                        # side arrises catch run-off dirt (research 5.2)
    # opacity for a delta L*: lighter toward chalk (about 8 L* above pale paint, capped at +5 so a
    # 1 px line does not read as a drawn highlight), darker toward the warm dirt (about 30 L* below)
    al_l = min(0.62, dl / 8.0)
    al_d = min(0.9, dl / 30.0)
    jit = np.clip(1.0 + 0.25 * nz.gfield((H, W), 0.6 * ppm, key + ("bj",)), 0.5, 1.5)
    m = lighter & keep
    alpha[m] = (al_l * jit[m]).astype(F32)
    col[m] = chalk
    m = bots & keep
    alpha[m] = (al_d * jit[m]).astype(F32)
    col[m] = dirt
    # visible chips (E6), clustered (E5): a rate along the edges modulated by a lognormal field
    marks = []
    ys, xs = np.nonzero(e)
    if ys.size:
        lam = 0.09 * 10.0 ** ((a - 0.25) / 0.75)              # per m of edge
        if 0.25 < a < 1.0:                                    # mid-band between the anchors (N3 at 0.5-0.75)
            lam *= 1.0 + 0.35 * np.sin(np.pi * (a - 0.25) / 0.75)
        clus = np.exp(1.9 * nz.gfield((H, W), 0.3 * ppm, key + ("chipc",))[ys, xs] - 1.805)
        r_ = nz.rng(*key, "chips")
        u = r_.random(ys.size)                                # drawn at amount 1: nested
        p_ = lam / ppm * clus
        sel = np.flatnonzero(u < p_)
        old = np.array(COL["old_paint"], F32)
        conc = np.array(COL["substrate"], F32) * 0.85
        for j in sel:
            rj = nz.rng(*key, "chip", int(ys[j]), int(xs[j]))
            size = rj.uniform(0.02, 0.06)
            rp = max(0.5, 0.5 * size * ppm)
            y0, x0 = int(ys[j]), int(xs[j])
            ya, yb, xa, xb = max(0, y0 - 2), min(H, y0 + 3), max(0, x0 - 2), min(W, x0 + 3)
            yy, xx = np.mgrid[ya:yb, xa:xb]
            cov = np.clip(rp + 0.5 - np.hypot(yy - y0, xx - x0), 0, 1) * mask[ya:yb, xa:xb]
            cc = conc if rj.random() < 0.15 else old
            upd = cov > alpha[ya:yb, xa:xb]
            alpha[ya:yb, xa:xb] = np.where(upd, cov * 0.9, alpha[ya:yb, xa:xb])
            col[ya:yb, xa:xb] = np.where(upd[..., None], cc, col[ya:yb, xa:xb])
            marks.append({"y": y0, "x": x0, "r_m": size / 2})
    return (alpha * mask).astype(F32), col, marks


def _old_layer_wear(plane, F, cfg, a, key):
    """Round F's worn arrises (kept for reference)."""
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
    # delamination spalls (round G, research S1-S5): from a = 0.4, on an area budget that brings
    # the spalled share to the S1 bands; placed by edges, bar lines and the cause field; drawn at
    # amount 1 in a fixed order and kept while they fit the budget (nested)
    wall_area = float(mask.sum()) / ppm ** 2
    target = 0.0003 * (0.055 / 0.0003) ** ((a - 0.25) / 0.75) if a > 0.25 else 0.0
    have = float((sub >= 0.5).sum()) / ppm ** 2 / max(wall_area, 1e-6)
    extra = max(0.0, target - have) * wall_area
    if extra > 0 and a >= 0.4:
        from weather_measure import gauss
        prox = gauss(plane["edges"].astype(F32), 0.15 * ppm)
        prox = prox / max(float(prox.max()), 1e-6)
        barl = (np.abs(((np.arange(H)[:, None] + 3.0 * nz.gfield((H, W), 0.5 * ppm, key + ("barw",))) % (0.2 * ppm))
                       - 0.1 * ppm) < 0.02 * ppm).astype(F32)
        risk = (prox + 0.25 * barl) * np.maximum(F.C, 1e-3) * mask
        rs = risk[::3, ::3]
        yy, xx = np.nonzero(rs > 0)
        if yy.size:
            wv = rs[yy, xx].astype(np.float64)
            rd = nz.rng(*key, "del")
            pri = np.log(wv) + rd.gumbel(size=yy.size)            # weighted order without replacement
            order = np.argsort(-pri)[:90000]
            acc_a = 0.0
            goal = target * float(mask.sum())
            for k, j in enumerate(order):
                rk = nz.rng(*key, "delr", k)
                r_m = min(0.5, 0.03 * (1.0 + rk.pareto(1.4)))
                if k % 50 == 0 and float((sub >= 0.5).sum()) >= goal:
                    break
                cy, cx = int(yy[j] * 3), int(xx[j] * 3)
                res = stamp_break(sub, dep, tone, cav, ppm, cx, cy, r_m, chip_depth(r_m), key + ("del", k),
                                  edge_angle(plane["edges"], cy, cx) if plane["edges"][max(0, cy - 4):cy + 5, max(0, cx - 4):cx + 5].any()
                                  else (0.0 if rk.random() < 0.6 else np.pi / 2), bar=bar, gk=gk, mask=mask)
                if res is None:
                    continue
                if res["low"] is not None:
                    spall_low.append((res["low"][0], res["low"][1], float(r_m)))
                acc_a += np.pi * r_m ** 2
                marks.append({"y": cy, "x": cx, "r_m": float(r_m), "eqd_m": 2 * float(r_m), "d_m": -2.0, "k": -2})
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
    grain = nz.gfield((H, W), 0.6, key + ("grain",)) + 0.7 * nz.gfield((H, W), 1.2, key + ("agg",))
    grain = (grain / max(float(grain.std()), 1e-6)).astype(F32)     # aggregate 2-5 cm and fines (S9)
    deep = dep >= 0.010
    gk = np.where(deep, np.maximum(gk, 0.16), gk).astype(F32)       # spall floors show the aggregate
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


# dirt palette (round G, I3): luminance-1 multipliers of a layer's colour, and the Lab shift each
# gives at 20 % on pale paint (0.55, 0.53, 0.48)
DIRT_TINT = {
    "neutral": (0.985, 1.017, 0.837),   # (0.0, +0.3)
    "warm": (1.952, 0.827, 0.020),      # dust and soil (+1.2, +1.4)
    "soot": (0.677, 1.049, 2.017),      # black carbon (0.0, -1.0)
    "green": (0.416, 1.302, 0.020),     # damp, algae-tinted (-1.4, +1.2)
}
DIRT_MIX = {                            # (warm, soot, damp green) weights per layer; round I: damp water marks
    "soiling": (1.00, 0.75, 0.15),      # are not green (growth is its own layer): green 0.45-0.60 -> 0.15
    "base": (0.90, 0.25, 0.15),
    "stains": (0.90, 0.45, 0.15),
    "streaks": (0.50, 0.90, 0.15),
}


# dirt families (round H, I4): each streak, stain and ground-band mark takes one colour family, dark
# green (mildew and algae in the run-off), yellow-ochre or the ordinary dirt, from tall narrow cells
# (a streak stays in one cell), so marks of different colours sit side by side with a sharp change
# between them ('a little more dark green and yellow. Not blended smoothly, but coexisting'). Green
# cells favour damp and sheltered wall; with the soiling clock the green ones darken and thicken
# ('mold and mildew darken/intensify with age').
FAM_CELL = (0.45, 5.0)        # family cells: width, height (m): most streaks stay in one cell
FAM_WARP = 0.10               # cell edges warped by this much (m), so they are not straight
FAM_P = {"green": (0.16, 0.30, 0.12), "yellow": (0.07, -0.04, -0.03)}   # cell share: a0 + a1 x damp + a2 x shelter
FAM_AGE = (5.0, 20.0)         # E over which the green cells darken and grow (x 0.7 to 1.2)
FAM_K = {}                    # round I: no colour cells on water and dirt marks (organic colour is the growth layer's)
FAM_K_H = {"streaks": 0.92, "stains": 0.88, "base": 0.55}   # round H's values
FAM_ALPHA = {"green": (1.40, 0.35), "yellow": (1.45, 0.10)}   # mark opacity x (a0 + a1 x age) in a family cell
_PPF = np.linspace(-4.5, 4.5, 1801)
_CDF = 0.5 * (1.0 + np.array([__import__("math").erf(x / np.sqrt(2.0)) for x in _PPF]))


def norm_ppf(p):
    """Inverse of the standard normal CDF (table, |error| < 0.003 inside +-4.5)."""
    return np.interp(np.clip(p, _CDF[0], _CDF[-1]), _CDF, _PPF)


def family_cells(plane, damp, shel, key, age):
    """Green and yellow family weights (0-1) from jittered cells of FAM_CELL, edges warped by FAM_WARP
    and softened over one pixel. Each cell's family is drawn once, its odds from the damp and the
    shelter at its seed."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    f = 2
    h, w = (H + f - 1) // f, (W + f - 1) // f
    cw, ch = FAM_CELL[0] * ppm, FAM_CELL[1] * ppm
    ny, nx = int(H / ch) + 3, int(W / cw) + 3
    r = nz.rng(*key, "famcells")
    sy = (np.arange(ny)[:, None] - 1 + r.random((ny, nx))) * ch
    sx = (np.arange(nx)[None, :] - 1 + r.random((ny, nx))) * cw
    yy = (np.arange(h)[:, None] * f + 0.5) + FAM_WARP * ppm * nz.gfield((h, w), 0.25 * ppm / f, key + ("fwy",))
    xx = (np.arange(w)[None, :] * f + 0.5) + FAM_WARP * ppm * nz.gfield((h, w), 0.25 * ppm / f, key + ("fwx",))
    gy = np.clip(np.floor(yy / ch).astype(int) + 1, 1, ny - 2)
    gx = np.clip(np.floor(xx / cw).astype(int) + 1, 1, nx - 2)
    best = np.full((h, w), np.inf)
    cid = np.zeros((h, w), np.int64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            iy, ix = gy + dy, gx + dx
            d = ((yy - sy[iy, ix]) / ch) ** 2 + ((xx - sx[iy, ix]) / cw) ** 2
            better = d < best
            best = np.where(better, d, best)
            cid = np.where(better, iy * nx + ix, cid)
    cy_ = np.clip(sy.astype(int), 0, H - 1).ravel()
    cx_ = np.clip(sx.astype(int), 0, W - 1).ravel()
    dmp, shl = damp[cy_, cx_], shel[cy_, cx_]
    grow = 0.7 + 0.5 * age
    pg = np.clip((FAM_P["green"][0] + FAM_P["green"][1] * dmp + FAM_P["green"][2] * shl) * grow, 0, 0.8)
    py = np.clip(FAM_P["yellow"][0] + FAM_P["yellow"][1] * dmp + FAM_P["yellow"][2] * shl, 0, 0.5)
    u = r.random(ny * nx)
    fam = np.where(u < pg, 1, np.where(u < pg + py, 2, 0))[cid]
    from weather_measure import gauss

    def up(m):
        return np.repeat(np.repeat(m, f, 0), f, 1)[:H, :W]
    g = np.clip(gauss(up((fam == 1).astype(F32)), 0.7), 0, 1)
    y = np.clip(gauss(up((fam == 2).astype(F32)), 0.7), 0, 1)
    return g.astype(F32), y.astype(F32)


def dirt_fields(plane, wet, key, E=0.0):
    """The palette's fields for a plane: z, a colour field of 3 m and 0.8 m (std about 1: warm
    where high, soot where low), damp (0-1) from the growth wetness map, and the green and yellow
    family weights of the marks with their age (0-1 over FAM_AGE)."""
    mask, ppm = plane["mask"], plane["ppm"]
    sh = mask.shape
    z = 0.75 * nz.gfield(sh, 3.0 * ppm, key + ("dz3",)) + 0.65 * nz.gfield(sh, 0.8 * ppm, key + ("dz08",))
    damp = np.zeros(sh, F32) if wet is None else nz.smoothstep(0.35, 0.70, wet.astype(F32))
    out = {"z": z.astype(F32), "damp": damp.astype(F32)}
    age = float(nz.smoothstep(FAM_AGE[0], FAM_AGE[1], float(E))) if E > 0 else 0.0
    shel = plane.get("shelter")
    shel = np.zeros(sh, F32) if shel is None else np.clip(np.asarray(shel, F32), 0, 1)
    out["fam_g"], out["fam_y"] = family_cells(plane, damp, shel, key, age)
    out["fam_age"] = age
    return out


FAM_HEAVY = (0.5, 0.35)       # streaks above this amount: the cells' boost and colour fade to this share at 1.0 (round H)


def fam_heavy(name, amt):
    """The colour cells' strength for a layer at its amount. Heavy streaking (above 0.5) runs so
    many overlapping streaks that a cell's boost and colour would outweigh the dirt itself, past
    the photo walls' colour spread (I3). The cells fade toward the plain dirt there; every preset
    and the sweeps' lower steps keep 1."""
    if name != "streaks" or amt is None or amt <= FAM_HEAVY[0]:
        return 1.0
    return float(np.interp(amt, [FAM_HEAVY[0], 1.0], [1.0, FAM_HEAVY[1]]))


def family_alpha(name, tf, al, amt=None):
    """A dirt layer's opacity in the family cells: green marks thicker (more with age), yellow ones
    a little thicker so they hold their darkening in a lighter colour."""
    if tf is None or name not in FAM_K or "fam_g" not in tf:
        return al
    k, age = FAM_K[name] * fam_heavy(name, amt), tf["fam_age"]
    mg = 1.0 + (FAM_ALPHA["green"][0] - 1.0 + FAM_ALPHA["green"][1] * age) * k * tf["fam_g"]
    my = 1.0 + (FAM_ALPHA["yellow"][0] - 1.0 + FAM_ALPHA["yellow"][1] * age) * k * tf["fam_y"]
    return np.clip(al * mg * my, 0, 0.95).astype(F32)


def dirt_patch(name, tf, col, amt=None):
    """The layer colour with its cell families laid in (H, W, 3), or None."""
    if tf is None or name not in FAM_K or "fam_g" not in tf:
        return None
    k, age = FAM_K[name] * fam_heavy(name, amt), tf["fam_age"]
    g0, g1 = np.array(COL["film_g"], F32), np.array(COL["film_g_old"], F32)
    y0, y1 = np.array(COL["film_y"], F32), np.array(COL["film_y_old"], F32)
    g, y = g0 + (g1 - g0) * age, y0 + (y1 - y0) * (0.4 + 0.6 * age)
    wg, wy = k * tf["fam_g"], k * tf["fam_y"]
    col = np.asarray(col, F32)
    if col.ndim == 1:
        col = np.broadcast_to(col, wg.shape + (3,))
    return (col * (1.0 - wg - wy)[..., None] + g * wg[..., None] + y * wy[..., None]).astype(F32)


def dirt_tint(name, tf):
    """Per-pixel tint (H, W, 3) for a dirt layer from the palette fields, or None."""
    if tf is None or name not in DIRT_MIX:
        return None
    kw, ks, kg = DIRT_MIX[name]
    z, damp = tf["z"], tf["damp"]
    ww = kw * nz.smoothstep(-0.2, 0.8, z)
    wsoot = ks * nz.smoothstep(-0.2, 0.8, -z)
    wg = kg * damp
    tot = ww + wsoot + wg
    sc = np.where(tot > 1.0, 1.0 / np.maximum(tot, 1e-6), 1.0)
    ww, wsoot, wg = ww * sc, wsoot * sc, wg * sc
    wn = 1.0 - ww - wsoot - wg
    T = {k: np.array(v, F32) for k, v in DIRT_TINT.items()}
    return (wn[..., None] * T["neutral"] + ww[..., None] * T["warm"] + wsoot[..., None] * T["soot"]
            + wg[..., None] * T["green"]).astype(F32)


# round J: paint failure exposing the concrete (user, round I). The amount sets the share of painted wall
# where the film is gone, on the ISO 4628-5 flaking quantity grades (1 = 0.1 %, 3 = 1 %, 4 = 3 %, 5 = 15 %).
PEEL_ON = True              # J15: on by default
PEEL_AREA = ((0.08, 0.001), (0.30, 0.010), (0.55, 0.035), (1.0, 0.15))
PEEL_W = (("chan", 0.15), ("crack", 0.45), ("effl", 0.20), ("edge", 0.25), ("base", 0.35), ("joint", 0.20),
          ("top", 0.25))
PEEL_SIGMA = 1.0            # the adhesion defects' spread (lognormal patchiness)
PEEL_SOFT = 0.35            # soft threshold, in the score's std: flakes under 2 cm stay partial pixels
PEEL_HALO_M = 0.08          # the checked film around the flakes (m)
PEEL_DIRT = 0.5             # the exposed concrete carries this power of the wall's dirt ratio (J24: 0.7 gave L* 51 at
                            # Derelict's foot, under the research's 55-68)
PEEL_TOP_M = 0.3            # how far below a top (cap, sill) water behind the film reaches (m)
PEEL_WARM = (1.01, 1.0, 0.985)  # J5: old exposed concrete is a little warmer than the fresh substrate grey
                                # (J16: (1.02, 1.0, 0.95) gave C* 4.97 before dirt; P3 wants 4 or less)
PEEL_DIRT_A = 0.3               # J16: the older coat (type a) carries this power of the wall's dirt ratio
PEEL_B_W = 0.02                 # J21: the type split's half-width (score std): older coat or concrete, not a mix
PEEL_BY_COAT = True         # J6: the amount from the years since the last repaint (Kept 4.7, Typical 5.8, Worn 10.3,
PEEL_COAT_R = (5.0, 6.0, 10.0, 15.0, 20.0, 30.0)     # Derelict 14.6): stage 2 (cracks, peels) from 10-15 years,
PEEL_COAT_A = (0.0, 0.05, 0.25, 0.60, 0.85, 1.0)     # stage 3 after about 20 unmaintained (NILIM, research)
PEEL_B_SHARE = ((0.0, 0.15), (0.30, 0.20), (0.60, 0.45), (1.0, 0.60))   # J6: type-b share of the flaked area
PEEL_CONC_LAB = (64.0, 0.3, 2.2)    # J6: old concrete under the coat, L* 55-68, C* <= 4 (research §2; J16; J24: L* 64)
PEEL_W_EXTRA = (("rails", 0.30), ("drip", 0.25))      # J6: below the rails, along drip lines and slab noses
PEEL_BASE = 0.07            # J13: the open wall's score floor (was 0.10, channels 0.30: Worn's open wall held 27 %)
PEEL_AMAX = ((0.0, 0.5), (0.27, 0.55), (0.45, 0.8), (0.55, 1.0))   # J19: the most of a 2 cm pixel that is flaked,
                            # by peel amount (Worn 0.27, Derelict 0.57): small separate flakes, then sheets


def layer_peeling(plane, F, cfg, a, key, cracks=None, effl=None):
    """Paint failure exposing the concrete (round J). Water behind the film lifts it: along the water's
    channels, at cracks and joints, under efflorescence (salts push the film off), at the foot (rising
    damp) and below tops (caps, sills); the film is thin at arrises. A lognormal adhesion field makes it
    patchy, the sun-facing front a little more. The amount sets the exposed share (PEEL_AREA); the score
    does not depend on it, so a higher amount's flakes contain the lower one's and grow by merging.
    Returns alpha (exposed share per pixel), colour (the concrete, a tone per flake area) and the halo
    where the film around the flakes is checked (the texture stage draws its crack network)."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    z = np.zeros((H, W), F32)
    if not PEEL_ON or a <= 0 or not mask.any():
        return z, None, z
    xs_, ys_ = [p_[0] for p_ in PEEL_AREA], [np.log(p_[1]) for p_ in PEEL_AREA]
    share = float(np.exp(np.interp(a, xs_, ys_))) if a >= xs_[0] else PEEL_AREA[0][1] * a / xs_[0]
    fx = {"chan": F.chan.astype(F32)}
    fx["crack"] = (np.clip(wm_.gauss((cracks > 0.05).astype(F32), 0.05 * ppm) * 5.0, 0, 1)
                   if cracks is not None else z)
    fx["effl"] = (np.clip(wm_.gauss(effl.astype(F32), 0.03 * ppm) / max(float(effl.max()), 1e-6) * 3.0, 0, 1)
                  if effl is not None and float(effl.max()) > 0 else z)
    e = plane.get("edges")
    fx["edge"] = np.clip(wm_.gauss(e.astype(F32), 0.02 * ppm) * 4.0, 0, 1) if e is not None else z
    hm = (plane["ground_row"] - np.arange(H))[:, None] / ppm * np.ones((1, W))
    fx["base"] = np.exp(-np.clip(hm, 0, None) / 0.5).astype(F32)
    fx["joint"] = np.clip(F.jwet, 0, 1).astype(F32) if getattr(F, "jwet", None) is not None else z
    tp = plane.get("tops")
    tb = np.zeros((H, W), F32)
    if tp is not None:
        run = np.zeros(W, F32)
        k_ = np.exp(-1.0 / (PEEL_TOP_M * ppm))
        for y in range(H):
            run = np.where(tp[y], 1.0, run * k_)
            run = np.where(mask[y] | tp[y], run, 0.0).astype(F32)
            tb[y] = run
    fx["top"] = tb
    st_ = plane.get("steel")
    rb = np.zeros((H, W), F32)
    if st_ is not None and st_.any():                     # J6: 0-0.5 m below the rails: their drips
        run = np.zeros(W, F32)
        k_ = np.exp(-1.0 / (0.25 * ppm))
        for y in range(H):
            run = np.where(st_[y], 1.0, run * k_).astype(F32)
            rb[y] = np.where(mask[y], run, 0.0)
    fx["rails"] = rb
    bt = plane.get("bottoms")
    fx["drip"] = (np.clip(wm_.gauss(bt.astype(F32), 0.05 * ppm) * 6.0, 0, 1) if bt is not None else z)
    ex = sum(w * fx[k] for k, w in PEEL_W + PEEL_W_EXTRA)
    if ZONE_ON:                                           # J: the wall top's edge (F5): water through the cap
        dtop_ = plane_zones(plane)[0]
        ex = ex + PEEL_TOPEDGE * ((dtop_ >= 0) & (dtop_ <= 0.10)).astype(F32) * float(nz.smoothstep(8.0, 19.0, float(plane.get("_E", 0.0))))
    defect = nz.fbm((H, W), ppm, [5, 6, 7], key + ("adh",))
    fine = nz.gfield((H, W), 0.7, key + ("adhf",))
    score = np.log(PEEL_BASE + ex) + PEEL_SIGMA * (0.8 * defect + 0.45 * fine) + 0.15 * float(plane.get("face_sun", 0.0))
    sm = score[mask]
    soft = PEEL_SOFT * float(sm.std())
    lo, hi = float(sm.min()) - 3 * soft, float(sm.max()) + 3 * soft
    acap = float(np.interp(a, [p_[0] for p_ in PEEL_AMAX], [p_[1] for p_ in PEEL_AMAX]))   # J19
    for _ in range(48):                                   # the threshold that exposes `share` of the wall
        thr = 0.5 * (lo + hi)
        if float(np.clip((sm - thr) / (2 * soft) + 0.5, 0, acap).mean()) > share:
            lo = thr
        else:
            hi = thr
    alpha = (np.clip((score - thr) / (2 * soft) + 0.5, 0, acap) * mask).astype(F32)
    tone = np.clip(0.95 + 0.06 * nz.gfield((H, W), 0.15 * ppm, key + ("tone",)), 0.8, 1.1)
    # J6: type b (to the concrete) is the deepest part of the failure, a share of the flaked area by amount
    d_ = (score - thr) / max(float(sm.std()), 1e-6)
    tb_share = float(np.interp(a, [p_[0] for p_ in PEEL_B_SHARE], [p_[1] for p_ in PEEL_B_SHARE]))
    fl = (alpha > 0.02) & mask
    if fl.any():                                          # the threshold whose alpha-weighted share is tb_share
        av, dv = alpha[fl].astype(np.float64), d_[fl].astype(np.float64)
        lo_b, hi_b = float(dv.min()) - 0.2, float(dv.max()) + 0.2
        for _ in range(40):
            t_b = 0.5 * (lo_b + hi_b)
            if float((av * nz.smoothstep(t_b - PEEL_B_W, t_b + PEEL_B_W, dv)).sum() / av.sum()) > tb_share:
                lo_b = t_b
            else:
                hi_b = t_b
        wb = nz.smoothstep(t_b - PEEL_B_W, t_b + PEEL_B_W, d_).astype(F32) * (alpha > 0.0)
    else:
        wb = z
    import rust_flow as _rfl
    conc = np.array(_rfl.lab_to_lin(PEEL_CONC_LAB), F32) * np.array(PEEL_WARM, F32)
    oldc = np.array(COL["old_coat"], F32)              # J21: its own colour (wear keeps old_paint)
    tone_ = 1.0 + (tone - 1.0) * wb                          # J16: the older coat keeps its clean body (no 0.95)
    col = ((oldc[None, None, :] * (1.0 - wb[..., None]) + conc[None, None, :] * wb[..., None]) * tone_[..., None]).astype(F32)
    plane["_peel_conc"] = wb.astype(F32)
    halo = (np.clip(wm_.gauss(alpha, PEEL_HALO_M * ppm) * 4.0, 0, 1) * (1.0 - alpha) * mask).astype(F32)
    return alpha, col, halo


def composite(plane, base_rgb, L, rec=None):
    """Apply the layers over the clean albedo. Returns weathered RGB, D, and L_<layer> maps (each
    layer alone over clean). On dark substrates, chips expose fresher concrete of the same tone
    rather than a light colour (G2).

    rec: a list that receives each step as (name, op, arrays) so the high-resolution compositor
    (wx_hires.py, round I) can replay the stack at any texel density."""
    A = base_rgb.astype(F32).copy()
    Y0 = np.maximum(luminance(base_rgb), 1e-4).astype(F32)
    Lm = {}
    if "fading" in L:
        f = L["fading"]["alpha"]
        grey = luminance(A)[..., None]
        A = (A + (grey - A) * 0.18 * f[..., None]) * (1.0 + 0.035 * f[..., None])
        if rec is not None:
            rec.append(("fading", "fade", {"alpha": f}))
        Lm["fading"] = 1 - luminance(A) / Y0
    if "repaint" in L:
        m, d = L["repaint"]["alpha"], L["repaint"]["shift"]
        A2 = A * (1.0 + d * m)[..., None]
        Lm["repaint"] = 1 - luminance(A2) / Y0 - Lm.get("fading", 0)
        A = A2
        if rec is not None:
            rec.append(("repaint", "shift", {"alpha": m, "shift": d}))
    if "crack_repair" in L:                  # repaired cracks: a stripe of slightly different tone
        m, d = L["crack_repair"]["alpha"], L["crack_repair"]["shift"]
        A2 = A * (1.0 + d * m)[..., None]
        Lm["crack_repair"] = 1 - luminance(A2) / Y0 - (1 - luminance(A) / Y0)
        A = A2
        if rec is not None:
            rec.append(("crack_repair", "shift", {"alpha": m, "shift": d}))
    for name in ("soiling", "stains", "streaks", "base", "bio", "rust_run", "rust_bare", "rust", "cracks", "efflorescence"):
        if name not in L:
            continue
        al = family_alpha(name, L.get("_tint"), L[name]["alpha"], L[name].get("amount"))
        if "repaint" in L and name in ("soiling", "streaks", "stains"):
            al = al * (1.0 - 0.30 * L["repaint"]["alpha"])
        col = L[name].get("colour")
        if col is None:
            col = COL.get(name, COL["soiling"])
        tn = dirt_tint(name, L.get("_tint"))
        if tn is not None:
            col = np.asarray(col, F32) * tn
        pc = dirt_patch(name, L.get("_tint"), col, L[name].get("amount"))
        if pc is not None:
            col = pc
        Lm[name] = 1 - luminance(_lerp(base_rgb, col, al)) / Y0
        An = _lerp(A, col, al)
        if rec is not None:
            rec.append((name, "lerp_dark" if name == "bio" else "lerp", {"alpha": al, "colour": col}))
        if name == "bio":                    # a biofilm tints a dirty wall but never brightens it
            Yn, Yo = luminance(An), luminance(A)
            An = np.where((Yn > Yo)[..., None], An * (Yo / np.maximum(Yn, 1e-6))[..., None], An).astype(F32)
        A = An
    for name in ("peeling", "wear"):
        if name in L:
            al = L[name]["alpha"]
            cw = L[name].get("colour")
            cw = COL["old_paint"] if cw is None else cw
            if name == "peeling" and PEEL_DIRT > 0:      # round J: the exposed concrete carries the wall's dirt
                ratio = np.clip(A / np.maximum(np.asarray(base_rgb, F32), 1e-4), 0.3, 1.15)
                wbp = L[name].get("conc")
                pw = PEEL_DIRT if wbp is None else (PEEL_DIRT_A + (PEEL_DIRT - PEEL_DIRT_A) * np.asarray(wbp, F32))[..., None]
                cw = (np.asarray(cw, F32) * ratio ** pw).astype(F32)   # J16: type a less dirty than type b
                Yc, Yb = luminance(cw), luminance(base_rgb)          # J18: never lighter than the clean paint
                cw = np.where((Yc > Yb)[..., None], cw * (Yb / np.maximum(Yc, 1e-6))[..., None], cw).astype(F32)
            Lm[name] = 1 - luminance(_lerp(base_rgb, cw, al)) / Y0
            A = _lerp(A, cw, al)
            if rec is not None:
                d_ = {"alpha": al, "colour": cw}
                if name == "peeling" and L[name].get("halo") is not None:
                    d_["halo"] = L[name]["halo"]
                if name == "peeling" and L[name].get("conc") is not None:
                    d_["conc"] = L[name]["conc"]
                rec.append((name, "lerp", d_))
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
        if rec is not None:
            rec.append(("damage", "damage", {"alpha": sub, "colour": subcol, "cavity": cav,
                                               "bar": L["damage"].get("bar")}))
    D = 1 - luminance(A) / Y0
    return A, D.astype(F32), {k: np.asarray(v, F32) for k, v in Lm.items()}


# ---------------------------------------------------------------------------------------------
# building and the budget solver

ACCENT_HEAVY_E = 19.0       # from this soiling clock (Derelict), the accent search starts lower (round H)
ACCENT_LO_HEAVY = 0.45      # its lower end there (0.6 elsewhere)


class Builder:
    """Builds every plane for one configuration and solves two gains so that the composite
    coverage by tier lands in the A1 bands for the configuration's E: 'soiling' scales the film
    (it sets T1+/T2+), 'accent' scales streaks and stains (T3+..T5+)."""

    def __init__(self, planes, cfg, bases, rules=None):
        self.planes, self.cfg, self.bases = planes, cfg, bases
        self.R, self.E, self.a = auto_amounts(cfg)
        for p_ in planes:                          # round J: zones that come in with the clock (F5, G7)
            p_["_E"] = self.E
        self.rules = rules or json.load(open(RULES, encoding="utf-8"))
        self.F = {p["name"]: PlaneFields(p, cfg) for p in planes}
        self.soil_field = {p["name"]: soiling_field(p, self.F[p["name"]], cfg, self.E) for p in planes}
        self.k = max(self.a["film_k"], 0.02)
        self.match = cfg.get("match")             # another seed of the preset to match (A5, round H)
        if self.match:
            self.k = float(self.match["film_k"])
        self.fixed = {}
        self.accent_cache = {}
        self.bio_cache = {}
        self.wet = {}
        self.tint = {}
        self.crk = {}
        self.half = {}

    def key(self, layer, p):
        return (self.cfg["seed"], layer, p["name"])

    def _rust_clock(self):
        """Round I: one rust clock for the building. Arrival times on every plane's steel once, cut at
        the rust amount's share of all the railing steel, so sheltered or lee steel rusts less than
        the exposed balcony rails instead of every plane reaching the same share."""
        if getattr(self, "_rclock", None) is None:
            import rust_flow as rfl
            pre, states = {}, []
            for q in self.planes:
                metal = q.get("steel")
                if metal is None or not np.asarray(metal).any():
                    continue
                pr = rfl.arrival_T(q, metal, self.key("rust", q))
                pre[q["name"]] = pr
                states.append((metal, pr))
            a = self.a["rust"]
            self._rclock = (pre, rfl.cut(states, rust_share(a)) if a > 0 else 0.0)
        return self._rclock

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
        flow = None
        if RUST_FLOW == "arrival":
            pre, Ts = self._rust_clock()
            flow = (pre.get(n), Ts)
        al, colr, _ = layer_rust(p, F, cfg, a["rust"], self.key("rust", p), spalls=spl, flow=flow)
        L["rust"] = {"alpha": al} if colr is None else {"alpha": al, "colour": colr}
        ex = p.pop("_rust_extra", None) or {}                # round J: runs down the bars, bare steel
        if ex.get("run_a") is not None and np.asarray(ex["run_a"]).any():
            L["rust_run"] = {"alpha": ex["run_a"], "colour": ex["run_c"]}
        if ex.get("bare_a") is not None and np.asarray(ex["bare_a"]).any():
            L["rust_bare"] = {"alpha": ex["bare_a"], "colour": np.ascontiguousarray(ex["bare_c"])}
        al, _, mkc, cs = layer_cracks(p, F, cfg, a["cracks"], self.key("cracks", p))
        L["cracks"] = {"alpha": al, "colour": COL["crack"]}
        L["crack_repair"] = {"alpha": (cs.rep != 0).astype(F32), "shift": cs.rep}
        marks["cracks"] = mkc
        self.crk[n] = cs
        al2, _, _ = layer_efflorescence(p, F, cfg, a["efflorescence"], self.key("efflorescence", p), cracks=al)
        L["efflorescence"] = {"alpha": al2}
        alp, colp, halo = layer_peeling(p, F, cfg, a.get("peeling", 0.0), self.key("peeling", p), cracks=al, effl=al2)
        if alp.any():                                    # round J: paint failure exposing the concrete
            L["peeling"] = {"alpha": alp, "colour": colp, "halo": halo, "conc": p.pop("_peel_conc", None)}
        al, colw, mkw = layer_wear(p, F, cfg, a["wear"], self.key("wear", p))
        L["wear"] = {"alpha": al, "colour": colw}
        marks["wear"] = mkw
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
            al, _, mks = layer_stains(p, F, cfg, min(1.0, a["stains"]), self.key("stains", p) + sfx, og=g)
            al2, col, mkr = layer_streaks(p, F, cfg, min(1.0, a["streaks"]), self.key("streaks", p) + sfx, og=g)
            ratio = flow_top_ratio(p, al + al2)
            if best is None or ratio > best[0]:
                best = (ratio, al, mks, al2, col, mkr)
            if ratio >= 1.45:
                break
        _r, al, mks, al2, col, mkr = best
        L["stains"] = {"alpha": al}
        marks["stains"] = mks
        L["streaks"] = {"alpha": al2, "colour": col, "amount": min(1.0, a["streaks"])}
        marks["streaks"] = mkr
        if p["name"] not in self.bio_cache:
            if abs(g - 1.0) < 1e-3:
                ref, ref2 = al, al2
            else:
                ref = layer_stains(p, F, cfg, min(1.0, a["stains"]), self.key("stains", p))[0]
                ref2 = layer_streaks(p, F, cfg, min(1.0, a["streaks"]), self.key("streaks", p))[0]   # the paths at gain 1
            dmg = self._fixed_layers(p)[0].get("damage", {}).get("alpha")
            alb, colb, _, wt = layer_bio(p, F, cfg, a["bio"], self.key("bio", p), stains=ref, streaks=ref2, chips=dmg)
            self.bio_cache[p["name"]] = (alb, colb)
            self.wet[p["name"]] = wt.astype(np.float16)
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
                            "wall": down2((p["mask"] & np.isin(p["cls"], (1, 2))).astype(F32)) >= 0.999,
                            "edge": down2(p["edges"].astype(F32)) > 0}
        return self.half[n]

    def build(self, gs, ga, fast=False):
        out = {}
        for p in self.planes:
            n = p["name"]
            Lf, mf = self._fixed_layers(p)
            La, ma = self._accent_layers(p, ga)
            tone, dev, ck = self.soil_field[n]
            soil = layer_soiling(film_of(tone, dev, self.k, ck), self.a["soiling"] * gs)
            if n not in self.tint:
                self.tint[n] = dirt_fields(p, self.wet.get(n), self.key("dirt", p), E=self.E)
            L = {}
            for k, v in list(Lf.items()) + list(La.items()) + [("soiling", {"alpha": soil}), ("_tint", self.tint[n])]:
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
            wear = o["layers"].get("wear", {}).get("alpha")
            if st == 2:
                hp = self._half(p)
                m, base = hp["wall"] & ~hp["edge"], hp["base"]
            else:                                          # arris rows are the edge rules' (N), not the wall's
                m, base = p["mask"] & np.isin(p["cls"], (1, 2)) & ~p["edges"], self.bases[p["name"]]
            if wear is not None and wear.shape == m.shape:
                m = m & ~(wear > 0)                        # and the edge layer's chips
            D = o["D"]
            tone.append(np.clip(D[m], -1.0, 1.0))
            peel = o["layers"].get("peeling", {}).get("alpha")
            ml = m & ~(peel > 0) if peel is not None and peel.shape == m.shape else m   # J26: and the flakes
            Y = 1.0 - D                                    # the weathering's own local contrast
            Dl, lpp = wm.local_contrast_D(Y, ml, p["ppm"] / st)
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
        if self.match:                            # a seed of a preset aims at the first seed's coverage (A5)
            c = self.match["coverage"]
            tol = [MATCH_TOL[0]] + [MATCH_TOL[1]] * 3 + [MATCH_TOL[2]] * 2
            return [(max(v * (1 - t), 1e-5), max(v * (1 + t), 2e-5)) for v, t in zip(c, tol)]
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
        k0 = float(self.match["film_k"]) if self.match else max(self.a["film_k"], 0.02)
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
            t += self._b1_cost(c)
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
            if "film_k" not in ov and not self.match:
                def fk(kk):
                    c = cov(gs, ga, kk)
                    if log is not None:
                        log.append(("film_k", kk, c, cost(c)))
                    return cost(c)
                k = golden(fk, 0.4 * k0, 2.5 * k0, 6)
            else:
                k = self.k if self.match else ov["film_k"]
            if "streaks" not in ov and "stains" not in ov:
                def fa(g):
                    c = cov(gs, g, k)
                    if log is not None:
                        log.append(("accent", g, c, cost(c)))
                    return cost(c)
                ga = golden(fa, ACCENT_LO_HEAVY if self.E >= ACCENT_HEAVY_E else 0.6, 1.6, 5)   # heavy presets may
                                                                                    # take the marks lower (A1 T6+)
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
        c1 = self.coverage(out)                       # full resolution: B1-B3 as the gate measures them
        b3 = self._b3_soiling(out)
        if log is not None:
            log.append(("final", self.k, ga, c1, list(self._b2), self._b1_fails(c1), b3))
        j0 = self._j2_corr(out)
        if log is not None:
            log.append(("j2", self.k, ga, j0))
        ok0 = (not (self._b2_fails() or self._b1_fails(c1) or b3 > 0.045) and j0 >= J2_MIN
               and max(abs(z) for z in zs(c1)) <= A1_ZMAX)          # round I: A1's tiers checked too
        m0 = self._b2_margin() if ok0 else -1.0
        if m0 < B2_MARGIN:                  # B1-B3 at full resolution, B2 with a margin for the sweeps, J2 kept
            k_best = self.k
            best = (m0, k_best, ga, None)
            tries = (((1.0, 1.05), (1.0, 0.95), (1.0, 1.10), (1.0, 0.90)) if self.match else   # a matched seed keeps k
                     ((1.15, 1.0), (1.32, 1.0), (0.85, 1.0), (0.72, 1.0), (1.0, 1.12), (1.0, 0.9)))
            for fk, fa in tries:
                self.k = k_best * fk
                o2 = self.build(gs, ga * fa)
                c2 = self.coverage(o2)
                b3 = self._b3_soiling(o2)
                j2 = self._j2_corr(o2)
                ok2 = (not self._b2_fails() and not self._b1_fails(c2) and b3 <= 0.045 and j2 >= J2_MIN and
                       max(abs(z) for z in zs(c2)) <= A1_ZMAX)   # tone and tiers in band, with a margin
                m2 = self._b2_margin() if ok2 else -1.0
                if log is not None:
                    log.append(("b_check", self.k, ga * fa, c2, list(self._b2), self._b1_fails(c2), b3, m2, j2))
                if m2 > best[0]:
                    best = (m2, self.k, ga * fa, o2)
                if m2 >= B2_MARGIN:
                    break
            if best[3] is not None:
                self.k = best[1]
                return gs, best[2], best[3]
            self.k = k_best
            out = self.build(gs, ga)
        return gs, ga, out

    def _j2_corr(self, out):
        """J2 (a) as the gate measures it: the soiling layer against the material response in the
        4-50 cm band on the painted walls, pixel-weighted over the exposed planes (1.0 under E 5)."""
        import weather_measure as wm
        if self.E < 5:
            return 1.0
        num = den = 0.0
        for p in self.planes:
            if not p.get("exposed", True):
                continue
            L = out[p["name"]].get("L", {}).get("soiling")
            M = getattr(self.F[p["name"]], "matresp", None)
            if L is None or M is None or L.shape != p["mask"].shape:
                continue
            m = p["mask"] & np.isin(p["cls"], (1, 2)) & np.isfinite(L)
            if m.sum() < 1000:
                continue
            ppm = p["ppm"]
            Lm = np.where(m, L.astype(np.float64), 0.0)
            Mm = np.where(m, M.astype(np.float16).astype(np.float64), 0.0)
            bl = wm.masked_gauss(Lm, m, 0.04 / 3 * ppm) - wm.masked_gauss(Lm, m, 0.50 / 3 * ppm)
            bm = wm.masked_gauss(Mm, m, 0.04 / 3 * ppm) - wm.masked_gauss(Mm, m, 0.50 / 3 * ppm)
            c = wm.corr(bl, bm, m)
            if np.isfinite(c):
                num += c * m.sum()
                den += m.sum()
        return num / den if den else 1.0

    def _b2_margin(self):
        """The smallest distance of B2's five measures above the gate's thresholds."""
        med, p10, span, bmed, bmin = getattr(self, "_b2", (1.0,) * 5)
        b_med, b_p10, b_min = (0.33, 0.25, 0.20) if self.E >= 25 else (0.40, 0.33, 0.25)
        return min(med - 0.30, span - 0.60, bmed - b_med, p10 - b_p10, bmin - b_min)

    def _b1_bands(self, c):
        """T2..T6 band shares of the exposed painted wall from cumulative coverage (B1)."""
        return [max(0.0, c[1] - c[2]), max(0.0, c[2] - c[3]), max(0.0, c[3] - c[4]), max(0.0, c[4] - c[5]),
                max(0.0, c[5])]

    def _b1_cost(self, c):
        if self.E < 10:
            return 0.0
        sh = self._b1_bands(c)
        tot = max(sum(sh), 1e-9)
        cap = (0.70 if self.E < 12 else 0.60) - 0.03
        t = (max(0.0, max(sh) / tot - cap) / 0.02) ** 2
        t += (max(0.0, 0.012 - sorted(sh)[-4]) / 0.002) ** 2
        if self.E <= 20:
            for i in range(1, 4):
                t += (max(0.0, sh[i + 1] - 0.85 * sh[i]) / max(0.05 * sh[i], 1e-4)) ** 2
        return t

    def _b1_fails(self, c):
        """B1 at the gate's thresholds."""
        if self.E < 10:
            return False
        sh = self._b1_bands(c)
        tot = max(sum(sh), 1e-9)
        cap = 0.70 if self.E < 12 else 0.60
        bad = sum(1 for x in sh if x >= 0.01) < 4 or max(sh) / tot > cap
        if self.E <= 20:
            bad = bad or not all(sh[i + 1] <= 0.9 * sh[i] + 1e-4 for i in range(1, 4))
        return bad

    def _b3_soiling(self, out):
        """B3 on the soiling layer: the worst exposed plane's flat share (local std over 20 cm under
        0.005 on the stained painted footprint)."""
        import weather_measure as wm
        worst = 0.0
        for p in self.planes:
            if not p.get("exposed", True):
                continue
            o = out[p["name"]]
            L = o.get("L", {}).get("soiling")
            if L is None or L.shape != p["mask"].shape:
                continue
            m = p["mask"] & np.isin(p["cls"], (1, 2))
            worst = max(worst, wm.flat_fraction(np.where(m, L.astype(np.float64), np.nan), p["ppm"]))
        return worst

    def _b2_fails(self):
        """B2 at the gate's thresholds, from the last coverage() call."""
        med, p10, span, bmed, bmin = getattr(self, "_b2", (1.0,) * 5)
        b_med, b_p10, b_min = (0.33, 0.25, 0.20) if self.E >= 25 else (0.40, 0.33, 0.25)
        return med < 0.30 or span < 0.60 or bmed < b_med or p10 < b_p10 or bmin < b_min
