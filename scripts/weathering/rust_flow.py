"""Rust on steel rails by water flow (round I; docs/redesign/research/weathering-rust-water.md §7.1).

Rust starts where water stays (post feet, rail-upright joints, the top rail's upper face, the bottom
rail) and spreads ALONG the members by first-arrival time, fastest down the uprights, slowest upward:
each step of the control adds the next band of arrival time (longer segments along the rails, runs
further down the uprights), never rings around old rust. Below the rusted feet, stains run down the
slab edge (a wide head narrowing to a tail), and a drip curtain hangs under rusted rails.
numpy only.
"""
import numpy as np

import wx_noise as nz

F32 = np.float32

# research rule 2: wetness by part, the top rail's face = 1
W_FOOT, W_JOINT, W_BOTTOM = 3.0, 2.0, 1.5     # bottom rail 1.5 (research 1.8): fed by a joint every 11 cm
W_TOP = (1.2, 1.0, 0.9)              # top rail: upper row, middle, lower row (the lower arris)
W_UP = (0.8, 0.15, 0.35)             # uprights: 0.8 x exp(-d / 0.15 m) below a rail joint, at least 0.35
# research rule 3 (softened again: top quarter / bottom quarter 1.8 rather than 2.7)
EXPO = (0.75, 1.35, 1.25, 1.15, 0.85)   # bottom quarter, top quarter, end bays, windward, lee
# research rule 4: onset c / w; seeds at feet and joints, sparse along the rails and faces
# calibrated on the real south front to the research's per-part order (rule 7), _calib_rust.py; the
# research's own c (0.10, 0.20, 0.30, 0.35, 0.50, 0.85) left the top rail at 1-50 % of its targets
C_FOOT, C_JOINT, C_TOP, C_BOTTOM, C_LOWER, C_FACE = 0.050, 0.078, 0.036, 1.0, 0.50, 0.50   # feet 0.068 -> 0.05 (round I: R3 feet at 0.5)
SEED_DX = {"top": (0.2, 0.4), "bottom": (0.3, 0.6), "lower": (0.5, 1.0), "face": (0.8, 1.6)}   # m between seeds
SIG_SEED, SIG_PLACE, SIG_BAY = 0.35, 0.40, 0.20   # lognormal spread: per seed, smooth over the facade (1.5 m), per bay
# research rule 5: speed factors k
K_ALONG, K_DOWN, K_UP, K_ACROSS = 1.0, 2.5, 0.3, 3.0
V_SPREAD = 1.8                       # speed of spread against onset (calibrated, round I)
N_SWEEP = 8
FOOT_MIN_RUN, FOOT_MAX_W = 0.4, 0.10  # feet: on uprights 0.4 m or taller, 0.1 m wide or less (posts)
# flat steel panels (doors, pipe-shaft doors, meter boxes; round I: the north front's steel is 74 % panels):
# water sits on the bottom edge and in the lower corners, the edges' paint is thin, the face sheds water,
# and most hang under a corridor slab (shelter)
PANEL_FILL, PANEL_WIN = 0.75, 0.20   # a panel: the steel fills 75 % or more of a 0.2 m window
W_PANEL = (1.6, 2.0, 0.6, 0.25)      # wetness: bottom edge, lower corners, other edges, face
C_PANEL = (0.12, 0.08, 0.35, 0.85)   # onsets c for the same parts
K_PANEL = (0.8, 1.0, 0.3)            # spread on a panel: sideways, down, up (rust creeps up slowly)
SHELTER_K = 0.6                      # panels: wetness x (1 - this x shelter)
# research rule 10: colour by age u = (T* - T) / T* (CIELAB D65 targets; converted below)
LAB_FRESH, LAB_MID, LAB_OLD, LAB_WET = (53.0, 20.0, 34.0), (40.0, 16.5, 24.0), (31.0, 12.5, 18.5), (24.0, 8.5, 11.5)   # round I: C* +10 % (R6 steel C* sat on its floor)
LAB_HEAD, LAB_TAIL = (38.0, 19.0, 24.0), (51.0, 11.0, 25.5)   # stains on paint: hue ~52 deg head, ~67 deg tail (round I: over
# Typical's yellower grime film the thin tails composited at 80 deg, the heads at 61.5; research photos: heads 52-56, tails 68-75)
# research rule 9: stains below the feet and the drip curtain
FOOT_HEAD = (0.05, 0.05, 0.20)       # head width 2 x (a0 + a1 u) m, at most this
FOOT_TAIL = (0.3, 0.7)               # tail width / head width
FOOT_LEN = (0.08, 0.60)              # length a0 + a1 u (m)
FOOT_OP = (0.45, 0.45)               # opacity a0 + a1 u
CURTAIN_DX = (0.15, 0.25)            # m between drips under rusted rails
CURTAIN_W = (0.02, 0.08)
CURTAIN_K = 0.45                     # cover at the top of the face = this x the rails' rusted share there
CURTAIN_HALF = (0.35, 0.50)          # the cover halves every this far down (m)
PARAPET_MAX = (0.30, 0.20)           # parapet plates: share with an outer-face stain, longest stain (m)
PARAPET_Q = 0.20                     # the share stained (a quota, the most rusted first; under the 30 % limit)
PARAPET_LEN = 0.16                   # their longest stain (m; under the 0.2 m limit, fingers included)
CURTAIN_POST_M = 0.12                # no drip point this close to a post: the water runs down the post


def lab_to_lin(lab):
    L, a, b = lab
    fy = (L + 16.0) / 116.0
    fx, fz = fy + a / 500.0, fy - b / 200.0
    f = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787  # noqa: E731
    X, Y, Z = 0.95047 * f(fx), 1.0 * f(fy), 1.08883 * f(fz)
    M = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    return np.clip(M @ np.array([X, Y, Z]), 0.0, 1.0).astype(F32)


C_FRESH, C_MID, C_OLD, C_WET = (lab_to_lin(c) for c in (LAB_FRESH, LAB_MID, LAB_OLD, LAB_WET))
# round J: runs down the uprights, colour variation, bare steel (each switchable)
RUNUP = True                   # rust carried down the bars by the water (J15: on by default)
RUNUP_L = (0.12, 0.55)         # decay length a0 + a1 x amount (m), per bar x exp(RUNUP_VAR x N) (before J9)
RUNUP_LEXP = (0.05, 5.4)       # J9: decay length L0 x G^((a - 0.5) / 0.5): 0.05 / 0.12 / 0.27 m at 0.5 / 0.75 / 1.0
RUNUP_COLLAR = (0.05, 0.6)     # J9: the film pools above the bottom rail: reach (m) and opacity x the run's source
RUNUP_VAR = 0.60                # round J2: more spread between bars (some reach the bottom rail)
RUNUP_OP = (0.25, 0.40)        # opacity at the source a0 + a1 x its rust age (J2: streaks, not a tint)
RUNUP_STREAK = 0.30            # streaky along the bar
COLOUR_VAR = True              # dark intense patches and bright fresh wet rust (J15: on by default)
VAR_AGE, VAR_SCALE_M = 0.50, 0.05     # age offset amplitude, patch scale (m)
LAB_RUN_HEAD, LAB_RUN_TAIL = (50.0, 22.0, 40.0), (66.0, 14.0, 34.0)   # J4: a thin iron-oxide film over white: orange (hue 61-68 deg, C* 36-46)
LAB_DARK = (25.0, 10.0, 11.0)         # J2: thick old scale, dark brown-black (darker than LAB_WET's hue)
DARK_K = 0.90                         # its weight where the age offset is high on old rust (J12: R9)
DARK_WET, DARK_WET_SCALE_M = 1.0, 0.03    # J13: dark scale in patches at feet, joints, the bottom rail, rail tops
DARK_WET_NV = (-2.5, -1.5)            # J17-J22: most wet-part rust (J14's (-1.0, 0.0) gave R9 dark 13.8 %)
DARK_OPAQUE = True                    # J13: thick old scale hides the paint (opacity toward 1 where dark)
LAB_BRIGHT = (56.0, 24.0, 40.0)       # fresh wet rust: brighter, more chroma (hue ~59 deg)
BRIGHT_K, BRIGHT_SCALE_M = 1.0, 0.03     # J18: 0.8 gave R9 bright 7.2 % once dark grew
BARE = True                    # bare steel where the paint flaked (J15: on by default)
BARE_HALO = (0.0, 0.50)        # the ring around the rust: alpha a0 + a1 x amount (2 cm pixels, partly bare; J25)
CHIP_P = (0.0, 0.006)           # chips: per-pixel chance on steel a0 + a1 x amount, x3 on top-rail tops and joints (J25)
LAB_BARE = (55.0, 0.0, 2.5)    # bare steel: dull grey, a trace of flash rust (J2: 60 read as paint)
C_BRIGHT, C_BARE, C_DARK = lab_to_lin(LAB_BRIGHT), lab_to_lin(LAB_BARE), lab_to_lin(LAB_DARK)
C_RUN_HEAD, C_RUN_TAIL = lab_to_lin(LAB_RUN_HEAD), lab_to_lin(LAB_RUN_TAIL)
C_HEAD, C_TAIL = lab_to_lin(LAB_HEAD), lab_to_lin(LAB_TAIL)


def _runs(m, axis):
    """Length of the run of True through each pixel along an axis."""
    a = np.moveaxis(m, axis, -1)
    out = np.zeros(a.shape, np.int32)
    for idx in np.ndindex(a.shape[:-1]):
        row = a[idx]
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        o = out[idx]
        for s, e in zip(st, en):
            o[s:e] = e - s
    return np.moveaxis(out, -1, axis)


def closed(metal, gap=2):
    """The steel with vertical gaps of up to `gap` px closed (thin balusters alias into dashes)."""
    m = metal.copy()
    for g in range(1, gap + 1):
        for a in range(1, g + 1):
            b = g + 1 - a
            fill = np.zeros_like(metal)
            fill[a:-b if b else None] = metal[:-a - b] & metal[a + b:]
            m |= fill
    return m


def panels(metal, ppm):
    """Flat steel panels: where the steel fills PANEL_FILL or more of a PANEL_WIN window."""
    k = max(3, int(round(PANEL_WIN * ppm)))
    H, W = metal.shape
    c = np.pad(metal.astype(np.float32), ((k // 2 + 1, k), (k // 2 + 1, k)))
    cs = c.cumsum(0).cumsum(1)
    box = (cs[k:k + H, k:k + W] - cs[:H, k:k + W] - cs[k:k + H, :W] + cs[:H, :W]) / float(k * k)
    return metal & (box >= PANEL_FILL)


def members(plane, metal):
    """Split the steel into rails (top / bottom, upper / lower rows), uprights, joints and feet, on the
    gap-closed steel. Returns a dict of boolean masks plus 'depth' (m below the nearest rail above,
    on uprights)."""
    ppm = plane["ppm"]
    H, W = metal.shape
    mask, cls = plane["mask"], plane.get("cls")
    metal = closed(metal)                    # topology on the gap-closed steel: 0.8 px balusters alternate
    panel = panels(metal, ppm)
    full = metal
    metal = metal & ~panel                   # the railing classes below are on the railing steel only
    hrun = _runs(metal, 1)
    rail = metal & (hrun >= int(0.30 * ppm))
    rail &= _runs(rail, 0) <= max(2, int(round(0.07 * ppm)) + 1)          # rails are at most 7 cm tall
    vrun = _runs(metal, 0)
    upr = metal & ~rail & (vrun >= int(0.15 * ppm))
    other = metal & ~rail & ~upr
    # top or bottom rail, per rail component: uprights standing on it (bottom) or hanging below it (top)
    from weather_measure import label
    lab, n = label(rail)
    top = np.zeros((H, W), bool)
    bottom = np.zeros((H, W), bool)
    if n:
        ab = np.zeros((H, W), bool)          # an upright pixel directly above (1-3 px)
        be = np.zeros((H, W), bool)          # and directly below
        for k in range(1, 4):
            ab[k:] |= upr[:-k]
            be[:-k] |= upr[k:]
        ys, xs = np.nonzero(lab)
        ll = lab[ys, xs]
        na = np.bincount(ll, weights=(ab[ys, xs] & ~rail[np.maximum(ys - 1, 0), xs]).astype(float), minlength=n + 1)
        nb = np.bincount(ll, weights=(be[ys, xs] & ~rail[np.minimum(ys + 1, H - 1), xs]).astype(float), minlength=n + 1)
        is_bot = na > 0.5 * nb
        bottom[ys, xs] = is_bot[ll]
        top[ys, xs] = ~is_bot[ll]
    upper = rail.copy()
    upper[1:] &= ~rail[:-1]
    lower = rail.copy()
    lower[:-1] &= ~rail[1:]
    # joints: upright pixels within 0.04 m of a rail in their column
    j = max(1, int(round(0.04 * ppm)))
    near = np.zeros((H, W), bool)
    for k in range(1, j + 1):
        near[k:] |= rail[:-k]
        near[:-k] |= rail[k:]
    joint = upr & near
    # feet: the lowest 0.1 m of an upright run that stands on paint
    paint = mask & (np.isin(cls, (1, 2)) if cls is not None else True)
    end = np.zeros((H, W), bool)
    end[:-1] = metal[:-1] & ~metal[1:] & paint[1:]
    end &= upr & (vrun >= int(FOOT_MIN_RUN * ppm))                      # posts, not brackets or spouts
    foot = np.zeros((H, W), bool)
    kf = max(1, int(round(0.10 * ppm)))
    for k in range(kf):
        foot[:H - k] |= end[k:]
    foot &= upr
    lab_f, nf = label(foot)                                             # post-like: at most 0.1 m wide
    if nf:
        ys, xs = np.nonzero(lab_f)
        ll = lab_f[ys, xs]
        x0 = np.full(nf + 1, W)
        x1 = np.full(nf + 1, -1)
        np.minimum.at(x0, ll, xs)
        np.maximum.at(x1, ll, xs)
        wide = (x1 - x0 + 1) > FOOT_MAX_W * ppm
        foot[ys[wide[ll]], xs[wide[ll]]] = False
    parapet = np.zeros((H, W), bool)                                     # feet on copings: parapet plates
    if cls is not None:
        on_cop = np.zeros((H, W), bool)
        on_cop[:-1] = end[:-1] & (cls[1:] == 2)
        for k in range(kf):
            parapet[:H - k] |= on_cop[k:]
        parapet &= foot
    # depth below the nearest rail above, through continuous steel
    depth = np.full((H, W), np.inf, F32)
    last = np.full(W, -10 ** 6)
    for y in range(H):
        last = np.where(rail[y], y, np.where(metal[y], last, -10 ** 6))
        ok = upr[y] & (last >= 0)
        depth[y, ok] = (y - last[ok]) / ppm
    # panel parts: bottom edge (2 px), lower corners (bottom 0.1 m within 0.06 m of a side), other edges, face
    pb = panel.copy()
    pb[:-1] &= ~panel[1:]
    kb = max(1, int(round(0.04 * ppm)))
    p_bot = np.zeros((H, W), bool)
    for k in range(kb):
        p_bot[:H - k] |= pb[k:]
    p_bot &= panel
    inner = panel.copy()
    inner[:, 1:] &= panel[:, :-1]
    inner[:, :-1] &= panel[:, 1:]
    side = panel & ~inner                                         # left or right perimeter
    ks = max(1, int(round(0.06 * ppm)))
    near_side = side.copy()
    for k in range(1, ks + 1):
        near_side[:, k:] |= side[:, :-k]
        near_side[:, :-k] |= side[:, k:]
    low = np.zeros((H, W), bool)
    for k in range(max(1, int(round(0.10 * ppm)))):
        low[:H - k] |= pb[k:]
    p_corner = panel & low & near_side
    top_e = panel.copy()
    top_e[1:] &= ~panel[:-1]
    p_edge = panel & (side | top_e) & ~p_bot & ~p_corner
    p_face = panel & ~p_bot & ~p_corner & ~p_edge
    return {"rail": rail, "top": top, "bottom": bottom, "upper": upper, "lower": lower, "upright": upr,
            "other": other, "joint": joint, "foot": foot, "parapet": parapet, "depth": depth, "closed": full,
            "panel": panel, "p_bot": p_bot, "p_corner": p_corner, "p_edge": p_edge, "p_face": p_face}


def wetness(plane, metal, M):
    """Research rules 2-3: wetness by part times the exposure (storey, end bays, wind)."""
    ppm = plane["ppm"]
    H, W = metal.shape
    w = np.zeros((H, W), F32)
    w[M["upright"] | M["other"]] = W_UP[2]
    d = np.where(np.isfinite(M["depth"]), M["depth"], 9.0)
    w = np.where(M["upright"], np.maximum(W_UP[2], W_UP[0] * np.exp(-d / W_UP[1])), w)
    w = np.where(M["top"], W_TOP[1], w)
    w = np.where(M["top"] & M["upper"], W_TOP[0], w)
    w = np.where(M["top"] & M["lower"] & ~M["upper"], W_TOP[2], w)
    w = np.where(M["bottom"], W_BOTTOM, w)
    w = np.where(M["joint"], W_JOINT, w)
    w = np.where(M["foot"], W_FOOT, w)
    if M["panel"].any():
        sh = plane.get("shelter")
        sf = (1.0 - SHELTER_K * np.clip(sh, 0, 1)) if sh is not None else 1.0
        wp = np.where(M["p_corner"], W_PANEL[1], np.where(M["p_bot"], W_PANEL[0],
                                                          np.where(M["p_edge"], W_PANEL[2], W_PANEL[3])))
        w = np.where(M["panel"], wp * sf, w)
    E = np.ones((H, W), F32)
    tr, gr = plane.get("top_row"), plane.get("ground_row")
    if tr is not None and gr is not None and gr > tr:
        hf = (gr - np.arange(H, dtype=F32)) / float(gr - tr)
        E *= np.interp(hf, [0.25, 0.75], [EXPO[0], EXPO[1]]).astype(F32)[:, None]
    bc = sorted(plane.get("bay_cols") or [])
    if len(bc) >= 3:
        xx = np.arange(W)
        endb = ((xx >= min(bc[0], bc[1])) & (xx < max(bc[0], bc[1]))) | ((xx >= min(bc[-2], bc[-1])) & (xx < max(bc[-2], bc[-1])))
        E *= np.where(endb, EXPO[2], 1.0).astype(F32)[None, :]
    o = plane.get("orient")
    E *= EXPO[3] if o == "S" else EXPO[4] if o == "N" else 1.0
    return (w * np.clip(E, 0.5, 2.0) * metal).astype(F32)


def _place(plane, metal, key):
    """Spread of onset over the facade: smooth (balconies, 1.5 m) times per bay."""
    ppm = plane["ppm"]
    H, W = metal.shape
    g = nz.gfield((H, W), 1.5 * ppm, key + ("rplace",))
    f = np.exp(SIG_PLACE * g)
    bc = sorted(plane.get("bay_cols") or [])
    if len(bc) >= 2:
        r = nz.rng(*key, "rbay")
        fb = np.ones(W, F32)
        for i in range(len(bc) - 1):
            fb[max(0, bc[i]):max(0, bc[i + 1])] = np.exp(SIG_BAY * r.normal())
        f = f * fb[None, :]
    return f.astype(F32)


def seeds(plane, metal, M, w, key):
    """Research rule 4: onset times T0 (inf where no seed). Every foot and joint is a seed (one onset
    per joint), the rails and faces get sparse seeds."""
    ppm = plane["ppm"]
    H, W = metal.shape
    T0 = np.full((H, W), np.inf, F32)
    place = _place(plane, metal, key)
    r = nz.rng(*key, "rseeds")
    from weather_measure import label

    def put(m, c):
        lab, n = label(m)
        if not n:
            return
        u = np.exp(SIG_SEED * r.normal(size=n + 1)).astype(F32)
        ys, xs = np.nonzero(lab)
        ll = lab[ys, xs]
        t = c / np.maximum(w[ys, xs], 1e-3) * u[ll] * place[ys, xs]
        T0[ys, xs] = np.minimum(T0[ys, xs], t)

    put(M["foot"], C_FOOT)
    put(M["joint"], C_JOINT)

    def sparse(m, c, dx, along_rows=True):
        ys, xs = np.nonzero(m)
        if not ys.size:
            return
        if along_rows:                                   # along each row run
            order = np.lexsort((xs, ys))
        else:
            order = np.lexsort((ys, xs))
        ys, xs = ys[order], xs[order]
        pos = (xs if along_rows else ys).astype(np.float64)
        line = (ys if along_rows else xs)
        brk = np.flatnonzero((np.diff(line) != 0) | (np.diff(pos) > 1)) + 1
        for seg in np.split(np.arange(ys.size), brk):
            if seg.size == 0:
                continue
            s = r.uniform(0, dx[1] * ppm)
            while s < seg.size:
                i = seg[int(s)]
                t = c / max(float(w[ys[i], xs[i]]), 1e-3) * np.exp(SIG_SEED * r.normal()) * place[ys[i], xs[i]]
                T0[ys[i], xs[i]] = min(T0[ys[i], xs[i]], t)
                s += r.uniform(dx[0], dx[1]) * ppm

    if M["panel"].any():
        put(M["p_corner"], C_PANEL[1])                                   # each lower corner: one onset
        sparse(M["p_bot"], C_PANEL[0], (0.15, 0.30))
        sparse(M["p_edge"], C_PANEL[2], (0.4, 0.8))
        sparse(M["p_face"], C_PANEL[3], (0.8, 1.6))
    sparse(M["top"] & M["upper"], C_TOP, SEED_DX["top"])
    sparse(M["bottom"] & M["upper"], C_BOTTOM, SEED_DX["bottom"])
    sparse(M["rail"] & M["lower"], C_LOWER, SEED_DX["lower"])
    sparse(M["upright"] & ~M["joint"] & ~M["foot"], C_FACE, SEED_DX["face"], along_rows=False)
    return T0


def arrival(metal, M, w, T0, ppm):
    """Research rule 5: T = min over seeds of T0 + sum dl / (w k), by min-plus sweeps on the steel.
    k: along a rail 1, down an upright 2.5, up 0.3, across a member 3."""
    dl = 1.0 / ppm
    inf = np.float32(np.inf)
    ww = np.maximum(w, 1e-3)
    rail, pan = M["rail"], M["panel"]
    kh = np.where(rail, K_ALONG, np.where(pan, K_PANEL[0], K_ACROSS))
    kd = np.where(rail, K_ACROSS, np.where(pan, K_PANEL[1], K_DOWN))
    ku = np.where(rail, K_ACROSS, np.where(pan, K_PANEL[2], K_UP))
    ch = np.where(metal, dl / (V_SPREAD * ww * kh), inf).astype(F32)   # cost to enter a pixel sideways
    cd = np.where(metal, dl / (V_SPREAD * ww * kd), inf).astype(F32)   # entering from above (moving down)
    cu = np.where(metal, dl / (V_SPREAD * ww * ku), inf).astype(F32)   # entering from below (moving up)
    T = np.where(metal, T0, inf).astype(F32)
    H, W = T.shape
    Tt, cht = T.T, ch.T
    for _ in range(N_SWEEP):
        prev = T.copy()
        for y in range(1, H):
            np.minimum(T[y], T[y - 1] + cd[y], out=T[y])
        for y in range(H - 2, -1, -1):
            np.minimum(T[y], T[y + 1] + cu[y], out=T[y])
        for x in range(1, W):
            np.minimum(Tt[x], Tt[x - 1] + cht[x], out=Tt[x])
        for x in range(W - 2, -1, -1):
            np.minimum(Tt[x], Tt[x + 1] + cht[x], out=Tt[x])
        if np.array_equal(prev, T):
            break
    return T


def arrival_T(plane, metal, key):
    """Members, wetness and the tie-broken arrival time of the plane's steel: (M, w, Tn). Independent
    of the amount, so a building computes it once and cuts every plane at one time (one clock)."""
    ppm = plane["ppm"]
    M = members(plane, metal)
    mc = M["closed"]                                     # spread over the gap-closed steel, rust on the steel
    w = wetness(plane, mc, M)
    T0 = seeds(plane, mc, M, w, key)
    T = arrival(mc, M, w, T0, ppm)
    fin = metal & np.isfinite(T)
    if not fin.any():
        return M, w, np.full(metal.shape, np.inf, F32)
    tie = 0.03 * float(np.median(T[fin])) * nz.gfield(metal.shape, 0.03 * ppm, key + ("rtie",))   # break ties
    return M, w, np.where(fin, T + tie, np.inf).astype(F32)


def cut(states, share):
    """The building's rust time for a rusted share of its railing steel (rails, posts, balusters;
    panels rust by the same clock but are not part of the share). states: [(metal, (M, w, Tn))]."""
    vals = [Tn[metal & ~M["panel"] & np.isfinite(Tn)] for metal, (M, w, Tn) in states]
    vals = np.concatenate(vals) if vals else np.zeros(0)
    if vals.size == 0 or share <= 0:
        return 0.0
    return float(np.quantile(vals, min(0.95, share)))


def rust_state(plane, metal, share, key, pre=None, Ts=None):
    """Members, wetness, arrival time and the cut for a rusted share (this plane's railing steel, or
    the building's time Ts when given). Returns a dict."""
    M, w, Tn = pre if pre is not None else arrival_T(plane, metal, key)
    fin = metal & np.isfinite(Tn)
    if not fin.any() or share <= 0:
        return {"M": M, "w": w, "T": Tn, "Ts": 0.0, "rust": np.zeros_like(metal), "u": np.zeros(metal.shape, F32)}
    if Ts is None:
        Ts = cut([(metal, (M, w, Tn))], share)
    rust = fin & (Tn <= Ts)
    u = np.where(rust, np.clip((Ts - Tn) / max(Ts, 1e-6), 0, 1), 0).astype(F32)
    return {"M": M, "w": w, "T": Tn, "Ts": Ts, "rust": rust, "u": u}


def rust_colour(u, w):
    """Research rule 10: fresh orange at the front, mid, old dark brown; old and wet darker still."""
    u = u[..., None]
    c = C_FRESH + (C_MID - C_FRESH) * np.clip(u / 0.3, 0, 1)
    c = c + (C_OLD - c) * np.clip((u - 0.3) / 0.4, 0, 1)
    wet = (np.clip((w - 1.6) / 0.6, 0, 1)[..., None] * np.clip((u - 0.4) / 0.3, 0, 1))
    return (c + (C_WET - c) * wet).astype(F32)


def _over_col(acc, col, ya, yb, xa, xb, a, c):
    """'over' a layer of alpha a and colour c (h, w, 3) into acc and its colour."""
    a0 = acc[ya:yb, xa:xb]
    na = a0 + a * (1.0 - a0)
    keep = a0 * (1.0 - a)
    col[ya:yb, xa:xb] = ((col[ya:yb, xa:xb] * keep[..., None] + c * a[..., None]) / np.maximum(na, 1e-6)[..., None])
    acc[ya:yb, xa:xb] = na


def stain(acc, col, mask, ppm, x0, y0, length_m, head_m, tail_m, op, key, confine=True):
    """A rust stain hanging from (x0, y0): a dark red head over its top quarter narrowing to a
    yellower tail in fingers (research §3-4: runs narrow, they do not fan out). Clipped to the
    paint segment it starts on."""
    H, W = acc.shape
    L = max(2, int(length_m * ppm))
    half = 0.5 * max(head_m, tail_m) * ppm + 3
    xa, xb = int(max(0, x0 - half)), int(min(W, x0 + half + 1))
    ya, yb = int(max(0, y0)), int(min(H, y0 + L))
    if xb <= xa or yb <= ya:
        return None
    r = nz.rng(*key)
    yy = np.arange(ya, yb)[:, None]
    xx = np.arange(xa, xb)[None, :]
    t = np.clip((yy - y0) / L, 0, 1)
    hw = 0.5 * ppm * (head_m + (tail_m - head_m) * np.clip(t / 0.25, 0, 1) ** 0.8)   # the head fills the top quarter
    nw = max(4, (yb - ya) // max(1, int(0.1 * ppm)) + 3)
    wob = np.interp(np.arange(ya, yb), np.linspace(ya, yb, nw), r.normal(0, 0.3, nw))[:, None]
    fing = np.interp(np.arange(xa, xb), np.linspace(xa, xb, max(3, (xb - xa) // 2)), r.normal(0, 1, max(3, (xb - xa) // 2)))[None, :]
    dx = np.abs(xx - x0 - wob) / np.maximum(hw, 0.8)
    across = np.clip(1.0 - dx ** 2, 0, 1) ** 0.6
    along = np.clip(1.0 - t ** np.maximum(0.6 + 0.25 * fing, 0.25), 0, 1)        # fingers end at different heights
    a = op * across * along * (0.85 + 0.15 * nz.smoothstep(-1, 1, fing))
    m = mask[ya:yb, xa:xb]
    if confine:                                                                     # never across a frame or a pipe
        brk = np.cumsum(~m, axis=1)
        c0 = int(np.clip(x0 - xa, 0, xb - xa - 1))
        a = a * (brk == brk[:, c0:c0 + 1])
    a = np.clip(a * m, 0, 0.92).astype(F32)
    if a.max() < 0.01:
        return None
    c = (C_HEAD[None, None, :] + (C_TAIL - C_HEAD)[None, None, :] * np.clip(t / 0.6, 0, 1)[..., None]).astype(F32)
    c = np.broadcast_to(c, a.shape + (3,))
    _over_col(acc, col, ya, yb, xa, xb, a, c)
    return {"x": int(x0), "y": int(y0), "L_m": (yb - ya) / ppm, "w_m": head_m, "peak": float(a.max()), "kind": "rust_foot"}


def face_below(plane, M, gap_m=0.12):
    """(rows, cols) of the first paint pixel below the lowest rail pixel of each column with a rail,
    looking down at most gap_m through non-paint pixels (the gap under a bottom rail). Sorted by x."""
    mask, ppm = plane["mask"], plane["ppm"]
    rail = M["rail"]
    H, W = rail.shape
    g = max(1, int(gap_m * ppm))
    low = np.zeros((H, W), bool)                    # a rail pixel with no rail pixel below it
    low[:-1] = rail[:-1] & ~rail[1:]
    ys, xs = np.nonzero(low)
    oy, ox = [], []
    for y, x in zip(ys, xs):
        for d in range(1, g + 1):
            yy = y + d
            if yy >= H:
                break
            if mask[yy, x]:
                oy.append(yy)
                ox.append(x)
                break
            if rail[yy, x]:
                break
    oy, ox = np.array(oy, int), np.array(ox, int)
    o = np.argsort(ox, kind="stable")
    return oy[o], ox[o]


def coping_below(cls, row, col, ppm, max_px, skip=2):
    """Rows from row down to the first coping row (class 2 within 0.1 m sideways), skipping the first
    `skip` rows: a stain stops there (the coping separates the wall behind a rail from the parapet face)."""
    if cls is None:
        return max_px
    H = cls.shape[0]
    cx = max(1, int(0.10 * ppm))
    ya, yb = row + skip, min(H, row + max_px)
    if ya >= yb:
        return max_px
    k = np.flatnonzero((cls[ya:yb, max(0, col - cx):col + cx + 1] == 2).any(axis=1))
    return int(k[0] + skip) if k.size else max_px


def region_below(mask, row, col, max_px):
    H = mask.shape[0]
    n = 0
    while row + n < H and n < max_px and mask[row + n, col]:
        n += 1
    return n


def layer(plane, metal, a, share, key, pre=None, Ts=None):
    """The rust layer on the steel and the stains it drops on the paint below. pre: arrival_T's result;
    Ts: the building's rust time (cut). Returns alpha (H, W), colour (H, W, 3), marks, state."""
    mask, ppm = plane["mask"], plane["ppm"]
    H, W = mask.shape
    acc = np.zeros((H, W), F32)
    col = np.zeros((H, W, 3), F32)
    marks = []
    S = rust_state(plane, metal, share, key, pre=pre, Ts=Ts)
    rust, u, w = S["rust"], S["u"], S["w"]
    if not rust.any():
        return acc, col, marks, S
    sp = nz.gfield((H, W), 0.012 * ppm + 0.5, key + ("rspk",))
    front = nz.smoothstep(0.0, 0.12, u)                                 # speckled at the front, dense behind it
    ra = 0.30 + 0.62 * nz.smoothstep(0.0, 0.5, u)                       # opacity 0.3 at the front to 0.9 (rule 8)
    ra = ra * np.where(front < 1, np.clip(0.55 + 0.45 * front + 0.35 * sp, 0.2, 1.0), 1.0)
    acc = np.where(rust, np.clip(ra, 0, 0.92), 0).astype(F32)
    col = np.where(rust[..., None], rust_colour(u, w), 0).astype(F32)
    M = S["M"]
    if COLOUR_VAR:                                      # round J: dark intense patches, bright fresh wet rust
        nv = nz.gfield((H, W), VAR_SCALE_M * ppm + 0.5, key + ("rvar",))
        nb = nz.gfield((H, W), BRIGHT_SCALE_M * ppm + 0.5, key + ("rbri",))
        uv = np.clip(u + VAR_AGE * nv, 0, 1).astype(F32)
        cv = rust_colour(uv, w)
        wet_ = 0.5 + 0.5 * nz.smoothstep(0.8, 2.0, w)
        bright = (BRIGHT_K * nz.smoothstep(0.0, 1.0, nb) * (1.0 - nz.smoothstep(0.25, 0.75, uv)) * wet_)[..., None]
        cv = cv + (C_BRIGHT - cv) * bright
        dark = (DARK_K * nz.smoothstep(-0.6, 0.4, nv) * nz.smoothstep(0.25, 0.55, uv))[..., None]   # J2, J3, J12, J20, J22
        if DARK_WET > 0:                                # J13: water stays at feet, joints, bottom rail, rail tops
            wetp = (M["foot"] | M["joint"] | M["bottom"] | (M["rail"] & M["upper"])).astype(F32)
            nd = nz.gfield((H, W), DARK_WET_SCALE_M * ppm + 0.5, key + ("rdkw",))
            dw = DARK_WET * wetp * nz.smoothstep(DARK_WET_NV[0], DARK_WET_NV[1], nd) * nz.smoothstep(0.05, 0.25, uv)
            dark = np.maximum(dark, dw[..., None])
        dark = dark * (1.0 - bright / max(BRIGHT_K, 1e-6))        # J18: dark old scale does not cover fresh fronts
        cv = cv + (C_DARK - cv) * dark
        if DARK_OPAQUE:
            acc = np.where(rust, acc + (1.0 - acc) * dark[..., 0], acc).astype(F32)
        col = np.where(rust[..., None], cv, 0).astype(F32)
    S["run_a"], S["run_c"] = np.zeros((H, W), F32), np.zeros((H, W, 3), F32)
    if RUNUP and a > 0:                                 # round J: rust carried down the bars by the water
        updn = M["upright"] | M["joint"]
        path = updn | M["rail"]                         # through rail crossings
        src = np.where(rust & updn, RUNUP_OP[0] + RUNUP_OP[1] * u, 0.0).astype(F32)
        s_r = np.where(rust & M["rail"], RUNUP_OP[0] + RUNUP_OP[1] * u, 0.0).astype(F32)
        src[1:] = np.maximum(src[1:], s_r[:-1] * updn[1:])          # from the rail into the bar below it
        colf = np.exp(RUNUP_VAR * nz.gfield((8, W), 0.8, key + ("rufac",))[4]).astype(F32)
        Lrun = RUNUP_LEXP[0] * RUNUP_LEXP[1] ** ((a - 0.5) / 0.5) if RUNUP_LEXP else RUNUP_L[0] + RUNUP_L[1] * a
        dec = np.exp(-1.0 / np.maximum(Lrun * ppm * colf, 1.0)).astype(F32)
        carry = np.zeros(W, F32)
        dist = np.zeros(W, F32)
        run_a = np.zeros((H, W), F32)
        run_t = np.zeros((H, W), F32)
        for y in range(H):
            on = path[y]
            cp = np.where(on, carry * dec, 0.0)
            sy = src[y]
            take = sy >= cp
            carry = np.where(on, np.maximum(sy, cp), 0.0).astype(F32)
            dist = np.where(take, 0.0, dist + 1.0 / ppm).astype(F32)
            run_a[y] = np.where(updn[y], carry, 0.0)
            run_t[y] = dist
        streak = np.clip(1.0 + RUNUP_STREAK * nz.gfield((H, W), 0.08 * ppm + 0.5, key + ("rustr",)), 0.3, 1.6)
        run_a = np.clip(run_a * streak, 0, 0.85).astype(F32)
        if RUNUP_COLLAR and M.get("bottom") is not None:   # J9: a collar where the film pools on the bottom rail
            bot = M["bottom"]
            k_c = max(1, int(round(RUNUP_COLLAR[0] * ppm)))
            near_bot = np.zeros((H, W), bool)
            for s_ in range(1, k_c + 1):
                near_bot[:-s_] |= bot[s_:]
            has_run = (np.where(updn, run_a, 0.0) > 0.05).any(axis=0)       # a bar that carries a run
            reach = near_bot & updn & has_run[None, :]
            run_a = np.where(reach, np.maximum(run_a, RUNUP_COLLAR[1] * (RUNUP_OP[0] + RUNUP_OP[1] * 0.5)), run_a).astype(F32)
        Lm_ = Lrun * colf[None, :]
        tt = np.clip(run_t / np.maximum(0.6 * Lm_, 1e-3), 0, 1)[..., None]
        S["run_a"] = run_a
        S["run_c"] = (C_RUN_HEAD + (C_RUN_TAIL - C_RUN_HEAD) * tt).astype(F32)
    S["bare_a"], S["bare_c"] = np.zeros((H, W), F32), np.broadcast_to(C_BARE.astype(F32), (H, W, 3))
    if BARE and a > 0:                                  # round J: the paint flakes around the rust; chips
        ring = np.zeros((H, W), bool)
        ring[1:] |= rust[:-1]
        ring[:-1] |= rust[1:]
        ring[:, 1:] |= rust[:, :-1]
        ring[:, :-1] |= rust[:, 1:]
        ring &= metal & ~rust
        rb = nz.rng(*key, "rbare")
        expo = 1.0 + 2.0 * ((M["top"] & M["upper"]) | M["joint"])
        chip = metal & ~rust & (rb.random((H, W)) < (CHIP_P[0] + CHIP_P[1] * a) * expo)
        ba = np.where(ring, BARE_HALO[0] + BARE_HALO[1] * a, 0.0)
        ba = np.maximum(ba, np.where(chip, rb.uniform(0.3, 0.7, (H, W)), 0.0))
        S["bare_a"] = ba.astype(F32)
    # stains below the rusted feet (rule 9)
    M = S["M"]
    from weather_measure import label
    lab, n = label(M["foot"] & rust)
    if n:
        ys, xs = np.nonzero(lab)
        ll = lab[ys, xs]
        yb = np.full(n + 1, -1)
        np.maximum.at(yb, ll, ys)
        x0 = np.full(n + 1, W)
        x1 = np.full(n + 1, -1)
        np.minimum.at(x0, ll, xs)
        np.maximum.at(x1, ll, xs)
        uf = np.zeros(n + 1)
        np.maximum.at(uf, ll, u[ys, xs])
        par = np.zeros(n + 1, bool)
        np.logical_or.at(par, ll, M["parapet"][ys, xs])
        r = nz.rng(*key, "rfeet")
        pids = [i for i in range(1, n + 1) if par[i]]
        pids.sort(key=lambda i: -float(uf[i]))
        par_ok = set(pids[:int(PARAPET_Q * len(pids))])          # parapet plates: a quota, the most rusted first
        for i in range(1, n + 1):
            xc, y0 = int((x0[i] + x1[i]) // 2), int(yb[i]) + 1
            if y0 >= H or not mask[y0, xc]:
                continue
            ui = float(uf[i])
            room = region_below(mask, y0, xc, int(1.5 * ppm))
            room = min(room, coping_below(plane.get("cls"), y0, xc, ppm, int(1.5 * ppm)))   # not over a coping
            ln = FOOT_LEN[0] + FOOT_LEN[1] * ui
            if par[i]:
                if i not in par_ok:
                    continue
                ln = min(ln, PARAPET_LEN)
            ln = min(ln, max(0.0, room / ppm - 0.03 * (room < 1.5 * ppm)))
            if ln < 0.04:
                continue
            post_w = (x1[i] - x0[i] + 1) / ppm
            head = min(FOOT_HEAD[2], 2.0 * (FOOT_HEAD[0] + FOOT_HEAD[1] * ui), max(1.5 * post_w, 0.0) + 0.1)
            head = max(head, 1.6 * post_w)
            tail = head * r.uniform(*FOOT_TAIL)
            info = stain(acc, col, mask, ppm, xc, y0, ln, head, tail, FOOT_OP[0] + FOOT_OP[1] * ui,
                         key + ("rf", i))
            if info:
                info["u"] = round(ui, 3)
                marks.append(info)
    # drip curtain under rusted rails over paint (rule 9): the slab-edge face below each rail, found
    # through the gap under the bottom rail (0.12 m at most)
    rail_r = M["rail"] & rust
    fy, fx = face_below(plane, M)
    if fy.size:
        r = nz.rng(*key, "rcurtain")
        up = int(1.3 * ppm)
        rows_ = []                       # [row, last x] per slab-edge row: each storey keeps its own spacing
        tol = max(2, int(0.3 * ppm))     # (faces come sorted by x; one shared last x let only the top storey drip)
        cls_c = plane.get("cls")
        fw_c = max(1, int(CURTAIN_POST_M * ppm))
        cop_x, cop_y = max(1, int(0.10 * ppm)), max(1, int(0.06 * ppm))   # the coping line is drawn as sparse pixels
        for y0, x in zip(fy, fx):
            ri = next((i_ for i_, rw in enumerate(rows_) if abs(rw[0] - int(y0)) <= tol), None)
            if ri is None:
                rows_.append([int(y0), -10 ** 6])
                ri = len(rows_) - 1
            if x - rows_[ri][1] < r.uniform(*CURTAIN_DX) * ppm:
                continue
            if cls_c is not None and (cls_c[max(0, int(y0) - cop_y):int(y0) + cop_y + 1,
                                            max(0, int(x) - cop_x):int(x) + cop_x + 1] == 2).any():
                continue                                                # a parapet top: slopes inward (research section 4)
            if M["foot"][max(0, int(y0) - int(0.3 * ppm)):int(y0) + 1, max(0, int(x) - fw_c):int(x) + fw_c + 1].any():
                continue                                                # at a post: its own foot stain
            ya = max(0, y0 - up)
            xa_, xb_ = max(0, x - int(0.1 * ppm)), min(W, x + int(0.1 * ppm) + 1)
            rr = M["rail"][ya:y0, xa_:xb_]
            if rr.sum() < 3:
                continue
            rows_[ri][1] = x
            sh = float(rail_r[ya:y0, xa_:xb_].sum()) / float(rr.sum())
            if sh <= 0 or r.random() > min(1.0, CURTAIN_K * sh * (sum(CURTAIN_DX) / sum(CURTAIN_W))):
                continue
            room = region_below(mask, int(y0), int(x), int(1.5 * ppm))
            room = min(room, coping_below(cls_c, int(y0), int(x), ppm, int(1.5 * ppm)))      # not over a coping
            half_m = r.uniform(*CURTAIN_HALF)
            ln = min(room / ppm, half_m * 2.0)
            if ln < 0.04:
                continue
            wd = r.uniform(*CURTAIN_W)
            info = stain(acc, col, mask, ppm, int(x), int(y0), ln, wd, wd * r.uniform(0.5, 0.9),
                         min(0.85, 0.35 + 0.6 * sh), key + ("rc", int(y0), int(x)))
            if info:
                info["kind"] = "rust_curtain"
                marks.append(info)
    return np.clip(acc, 0, 0.92).astype(F32), col, marks, S
