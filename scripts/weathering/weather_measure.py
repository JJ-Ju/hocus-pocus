"""weather_measure.py - measurements for the weathering rules, in facade space (numpy only).

Everything works on a darkening map D (H x W, float): D = 1 - Y_weathered / Y_clean, so 0 is
clean, 0.1 is 10 % darker, negative is lighter. NaN marks pixels that are not measured (glass,
props, sky, other planes). `ppm` is pixels per metre; row 0 is the top of the image.

Scale levels S1-S8 are octaves of feature size, 16-32 m down to 12.5-25 cm. Opacity tiers T1-T6
are bands of D. Both are defined here once and used by the rules (weather_rules.json) and the
gate (weather_gate.py).
"""
import numpy as np

TIER_EDGES = [0.02, 0.05, 0.10, 0.18, 0.30, 0.45]          # T1..T6 lower bounds of D
TIER_NAMES = ["T1 trace", "T2 faint", "T3 light", "T4 medium", "T5 heavy", "T6 very heavy"]
LEVELS = [(16.0, 32.0), (8.0, 16.0), (4.0, 8.0), (2.0, 4.0), (1.0, 2.0), (0.5, 1.0),
          (0.25, 0.5), (0.125, 0.25)]                         # S1..S8, metres
LEVEL_NAMES = ["S%d" % (i + 1) for i in range(len(LEVELS))]
GROUP = {"macro": (0, 1, 2), "mid": (3, 4), "micro": (5, 6, 7)}


# ---------------------------------------------------------------------------------------------
# filtering

def _box1(a, r, axis):
    """Box filter of radius r (window 2r+1) along an axis, by cumulative sums, edge-clamped."""
    if r <= 0:
        return a
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def gauss(a, sigma):
    """Approximate Gaussian blur (three box passes per axis). sigma in pixels."""
    if sigma < 0.5:
        return a.astype(np.float64)
    r = max(1, int(round((np.sqrt(12.0 * sigma * sigma / 3.0 + 1.0) - 1.0) / 2.0)))
    out = a.astype(np.float64)
    for axis in (0, 1):
        for _ in range(3):
            out = _box1(out, r, axis)
    return out


def masked_gauss(a, valid, sigma):
    """Normalised convolution: blur of the valid pixels only. Returns NaN where no support."""
    v = valid.astype(np.float64)
    num = gauss(np.where(valid, a, 0.0), sigma)
    den = gauss(v, sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den < 1e-3] = np.nan
    return out


def _down(D, f):
    """Block-average downsample by f, NaN-aware. Returns (values, valid fraction)."""
    if f <= 1:
        return D, np.isfinite(D).astype(np.float64)
    H, W = D.shape
    h, w = H // f, W // f
    a = D[:h * f, :w * f].reshape(h, f, w, f)
    v = np.isfinite(a)
    s = np.where(v, a, 0.0).sum(axis=(1, 3))
    n = v.sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = s / n
    out[n == 0] = np.nan
    return out, n / float(f * f)


def bands(D, ppm, levels=None):
    """Difference-of-Gaussian band images, one per scale level that fits the image.

    Level k (sizes s..2s) uses sigma1 = s/3 and sigma2 = 2s/3 (an octave apart); its response
    peaks for features about 1.3 s across. Each band is computed at a reduced resolution where
    sigma1 is about 3 px (enough for its statistics). Returns {level: (band image, ppm_used)}.
    """
    H, W = D.shape
    ext = max(H, W) / ppm
    out = {}
    for k, (s, _s2) in enumerate(LEVELS if levels is None else levels):
        if s > 0.75 * ext:
            continue
        s1 = s / 3.0 * ppm
        if s1 < 0.7:
            continue
        f = max(1, int(s1 // 3))
        d, vf = _down(D, f)
        valid = vf >= 0.5
        d = np.where(valid, d, np.nan)
        g1 = masked_gauss(d, valid, s1 / f)
        g2 = masked_gauss(d, valid, 2 * s1 / f)
        b = g1 - g2
        b[~valid] = np.nan
        out[k] = (b, ppm / f)
    return out


def band_stats(D, ppm):
    """Per level: std of the band, and anisotropy gx/gy (> 1 = vertical structure)."""
    res = {}
    for k, (b, _p) in bands(D, ppm).items():
        v = np.isfinite(b)
        if v.sum() < 30:
            continue
        sd = float(np.nanstd(b))
        gx = np.abs(np.diff(b, axis=1))
        gy = np.abs(np.diff(b, axis=0))
        ax = float(np.nanmean(gx)) / max(float(np.nanmean(gy)), 1e-12)
        res[LEVEL_NAMES[k]] = {"std": sd, "aniso": ax}
    return res


# ---------------------------------------------------------------------------------------------
# opacity tiers

def tier_coverage(D):
    """Fraction of measured pixels at or above each tier (cumulative)."""
    v = D[np.isfinite(D)]
    n = max(v.size, 1)
    return [float((v >= t).sum()) / n for t in TIER_EDGES]


def tier_shares(D):
    """Fraction of measured pixels inside each tier band (T1..T6), plus 'clean' and 'lighter'."""
    v = D[np.isfinite(D)]
    n = max(v.size, 1)
    e = TIER_EDGES + [np.inf]
    sh = [float(((v >= e[i]) & (v < e[i + 1])).sum()) / n for i in range(len(TIER_EDGES))]
    return {"lighter": float((v <= -TIER_EDGES[0]).sum()) / n,
            "clean": float(((v > -TIER_EDGES[0]) & (v < TIER_EDGES[0])).sum()) / n,
            "tiers": sh}


def tier_decay(D):
    """Area ratio of each tier to the one below it (T2/T1 ... T6/T5); None where the lower is ~0."""
    sh = tier_shares(D)["tiers"]
    return [(sh[i + 1] / sh[i]) if sh[i] > 1e-4 else None for i in range(len(sh) - 1)]


def flat_fraction(D, ppm, window_m=0.2, sd_min=0.005, footprint=TIER_EDGES[0]):
    """Share of the stained footprint (D >= T1) whose local std over window_m is below sd_min:
    flat tint, the 'just changing the base colour' failure."""
    valid = np.isfinite(D)
    sig = window_m * ppm / 2.0
    m1 = masked_gauss(D, valid, sig)
    m2 = masked_gauss(np.where(valid, D * D, 0.0), valid, sig)
    sd = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    fp = valid & (D >= footprint)
    if fp.sum() == 0:
        return 0.0
    return float((sd[fp] < sd_min).mean())


# ---------------------------------------------------------------------------------------------
# connected marks

def label(binary, conn=8):
    """8-connected (or 4-connected, conn=4) component labels, vectorised: row runs, overlaps between
    consecutive rows, then min-label propagation with pointer jumping. Returns (labels, count); 0 = background."""
    H, W = binary.shape
    b = np.zeros((H, W + 2), np.int8)
    b[:, 1:-1] = binary
    d = np.diff(b, axis=1)
    rs, cs = np.nonzero(d == 1)
    re_, ce = np.nonzero(d == -1)
    n = rs.size
    if n == 0:
        return np.zeros((H, W), np.int32), 0
    K = W + 2
    skey = rs.astype(np.int64) * K + cs
    ekey = re_.astype(np.int64) * K + ce
    idx = np.flatnonzero(rs > 0)
    prow = (rs[idx] - 1).astype(np.int64) * K
    j0 = np.searchsorted(ekey, prow + cs[idx], side="left" if conn == 8 else "right")   # 4: runs must share a column
    j1 = np.searchsorted(skey, prow + ce[idx], side="right" if conn == 8 else "left")
    cnt = np.maximum(j1 - j0, 0)
    ii = np.repeat(idx, cnt)
    off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    jj = np.repeat(j0, cnt) + off
    lab = np.arange(n)
    if ii.size:
        for _ in range(500):
            m = np.minimum(lab[ii], lab[jj])
            new = lab.copy()
            np.minimum.at(new, ii, m)
            np.minimum.at(new, jj, m)
            for _k in range(4):
                new = new[new]
            if np.array_equal(new, lab):
                break
            lab = new
    uniq, comp = np.unique(lab, return_inverse=True)
    out = np.zeros(H * W, np.int32)
    lengths = ce - cs
    pix = np.repeat(rs.astype(np.int64) * W + cs, lengths) + (np.arange(lengths.sum()) -
                                                             np.repeat(np.cumsum(lengths) - lengths, lengths))
    out[pix] = np.repeat(comp + 1, lengths)
    return out.reshape(H, W), uniq.size


def marks(D, ppm, thr=TIER_EDGES[1], min_area_m2=0.0004):
    """Connected marks at D >= thr. For each: area (m2), equivalent diameter (m), bbox height and
    width (m), aspect h/w, mean and std of D inside, tiers spanned, mean D in its top and bottom
    thirds, top row and the x range of its top rows (px), level index of its size (by the larger
    of eq. diameter and height; len(LEVELS) = below S8). Vectorised over components."""
    valid = np.isfinite(D)
    lab, n = label(valid & (D >= thr))
    if n == 0:
        return []
    H, W = D.shape
    L = lab.ravel()
    sel = L > 0
    li = L[sel] - 1
    vals = np.where(valid, D, 0.0).ravel()[sel]
    pos = np.flatnonzero(sel)
    ys, xs = pos // W, pos % W
    area = np.bincount(li, minlength=n).astype(np.float64)
    s1 = np.bincount(li, vals, n)
    s2 = np.bincount(li, vals * vals, n)
    y0 = np.full(n, H, np.int64)
    np.minimum.at(y0, li, ys)
    y1 = np.zeros(n, np.int64)
    np.maximum.at(y1, li, ys)
    x0 = np.full(n, W, np.int64)
    np.minimum.at(x0, li, xs)
    x1 = np.zeros(n, np.int64)
    np.maximum.at(x1, li, xs)
    vmin = np.full(n, np.inf)
    np.minimum.at(vmin, li, vals)
    vmax = np.full(n, -np.inf)
    np.maximum.at(vmax, li, vals)
    xsum = np.bincount(li, xs.astype(np.float64), n)
    third = np.maximum(1, (y1 - y0 + 1) // 3)
    top = ys < (y0 + third)[li]
    bot = ys > (y1 - third)[li]
    tsum = np.bincount(li[top], vals[top], n)
    tcnt = np.bincount(li[top], minlength=n)
    bsum = np.bincount(li[bot], vals[bot], n)
    bcnt = np.bincount(li[bot], minlength=n)
    toprow = ys <= (y0 + 1)[li]
    txmin = np.full(n, W, np.int64)
    np.minimum.at(txmin, li[toprow], xs[toprow])
    txmax = np.zeros(n, np.int64)
    np.maximum.at(txmax, li[toprow], xs[toprow])
    a_m2 = area / (ppm * ppm)
    mean = s1 / np.maximum(area, 1)
    std = np.sqrt(np.maximum(s2 / np.maximum(area, 1) - mean * mean, 0))
    h_m = (y1 - y0 + 1) / ppm
    w_m = (x1 - x0 + 1) / ppm
    eqd = 2.0 * np.sqrt(a_m2 / np.pi)
    size = np.maximum(eqd, h_m)
    lo_t = np.searchsorted(TIER_EDGES, vmin, side="right")
    hi_t = np.searchsorted(TIER_EDGES, vmax, side="right")
    lv_edges = np.array([lv[0] for lv in LEVELS][::-1])      # ascending lower bounds S8..S1
    out = []
    for c in np.flatnonzero(a_m2 >= min_area_m2):
        k = int(np.searchsorted(lv_edges, size[c], side="right"))   # number of lower bounds <= size
        lvl = len(LEVELS) - k if k > 0 else len(LEVELS)
        lvl = max(0, lvl)
        out.append({"area_m2": float(a_m2[c]), "eqd_m": float(eqd[c]), "h_m": float(h_m[c]), "w_m": float(w_m[c]),
                    "aspect": float(h_m[c] / max(w_m[c], 1e-6)), "mean": float(mean[c]), "std": float(std[c]),
                    "cv": float(std[c] / max(mean[c], 1e-6)), "tiers_spanned": int(hi_t[c] - lo_t[c] + 1),
                    "top_mean": float(tsum[c] / max(tcnt[c], 1)), "bottom_mean": float(bsum[c] / max(bcnt[c], 1)),
                    "y_top_px": int(y0[c]), "x_mid_px": int(xsum[c] / max(area[c], 1)),
                    "x_top": [int(txmin[c]), int(txmax[c])], "level": lvl})
    return out


def level_counts(mk):
    """Number of marks per scale level (S1..S8, plus 'below S8')."""
    c = [0] * (len(LEVELS) + 1)
    for m in mk:
        c[m["level"]] += 1
    return c


# ---------------------------------------------------------------------------------------------
# clustering, coherence, gradients

def cells(D, ppm, cell_m, min_valid=0.5):
    """Grid of cell means (NaN where under min_valid of the cell is measured)."""
    c = max(1, int(round(cell_m * ppm)))
    H, W = D.shape
    ny, nx = H // c, W // c
    if ny == 0 or nx == 0:
        return np.full((0, 0), np.nan)
    a = D[:ny * c, :nx * c].reshape(ny, c, nx, c)
    v = np.isfinite(a)
    s = np.where(v, a, 0.0).sum(axis=(1, 3))
    n = v.sum(axis=(1, 3))
    out = np.full((ny, nx), np.nan)
    ok = n >= min_valid * c * c
    out[ok] = s[ok] / n[ok]
    return out


def concentration(cellgrid, top=0.2):
    """Share of the total (D clipped at 0) held by the top `top` fraction of cells, and the
    floor: the 10th-percentile cell over the mean."""
    v = cellgrid[np.isfinite(cellgrid)]
    v = np.clip(v, 0, None)
    if v.size < 5 or v.sum() <= 0:
        return {"top_share": None, "floor": None, "n": int(v.size)}
    s = np.sort(v)[::-1]
    k = max(1, int(round(top * s.size)))
    return {"top_share": float(s[:k].sum() / s.sum()), "floor": float(np.percentile(v, 10) / v.mean()),
            "min_over_mean": float(v.min() / v.mean()), "n": int(v.size)}


def coherence(cellgrid):
    """Lag-1 correlation of neighbouring cells (vertical, horizontal) and the P90 of the vertical
    neighbour difference over the P90-P10 spread of all cells."""
    g = cellgrid

    def corr(a, b):
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < 6 or np.std(a[m]) < 1e-9 or np.std(b[m]) < 1e-9:
            return None
        return float(np.corrcoef(a[m], b[m])[0, 1])

    rv = corr(g[:-1, :], g[1:, :]) if g.shape[0] > 1 else None
    rh = corr(g[:, :-1], g[:, 1:]) if g.shape[1] > 1 else None
    v = g[np.isfinite(g)]
    spread = float(np.percentile(v, 90) - np.percentile(v, 10)) if v.size > 5 else None
    dv = np.abs(g[1:, :] - g[:-1, :]) if g.shape[0] > 1 else np.array([])
    dv = dv[np.isfinite(dv)]
    jump = float(np.percentile(dv, 90) / spread) if (dv.size > 5 and spread) else None
    return {"rho_v": rv, "rho_h": rh, "jump_p90_over_spread": jump}


def height_profile(D, ppm, ground_row=None, top_row=None):
    """Mean D in the top 20 % of the wall height and in the 30-70 % band (from the ground)."""
    H = D.shape[0]
    g = H - 1 if ground_row is None else ground_row
    t = 0 if top_row is None else top_row
    span = g - t
    if span < 10:
        return None

    def band(f0, f1):           # fractions of height above ground
        r0, r1 = int(g - f1 * span), int(g - f0 * span)
        v = D[max(r0, 0):max(r1, 1)]
        v = v[np.isfinite(v)]
        return float(np.clip(v, 0, None).mean()) if v.size else None

    top, mid, base = band(0.8, 1.0), band(0.3, 0.7), None
    if ppm and span / ppm > 3:
        r0 = int(g - 1.0 * ppm)
        v = D[max(r0, 0):g + 1]
        v = v[np.isfinite(v)]
        base = float(np.clip(v, 0, None).mean()) if v.size else None
    allv = D[t:g + 1]
    allv = allv[np.isfinite(allv)]
    return {"top20": top, "mid30_70": mid, "base1m": base,
            "mean": float(np.clip(allv, 0, None).mean()) if allv.size else None}


# ---------------------------------------------------------------------------------------------
# colour helpers

def srgb_to_linear(a):
    a = np.asarray(a, np.float64) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def linear_to_lab(rgb):
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = rgb @ M.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(np.maximum(xyz, 0)), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1)


def luminance(rgb_linear):
    return rgb_linear @ np.array([0.2126, 0.7152, 0.0722])


def photo_relative_D(Y, valid, ref_pct=95.0, detrend="plane"):
    """Darkening relative to the cleanest paint in the crop, for photos (and for renders measured
    the same way): fit a plane to log Y (the light gradient), divide it out, then
    D = 1 - Y / P95(Y). Lighting and exposure cancel; macro tone across the crop is lost."""
    logy = np.log(np.maximum(Y, 1e-5))
    H, W = Y.shape
    yy, xx = np.mgrid[0:H, 0:W]
    m = valid & np.isfinite(logy)
    if detrend == "plane" and m.sum() > 50:
        A = np.c_[xx[m], yy[m], np.ones(m.sum())]
        coef, *_ = np.linalg.lstsq(A, logy[m], rcond=None)
        logy = logy - (coef[0] * xx + coef[1] * yy + coef[2]) + logy[m].mean()
    Yc = np.exp(logy)
    ref = np.percentile(Yc[m], ref_pct)
    D = 1.0 - Yc / ref
    D[~m] = np.nan
    return D


def local_relative_D(Y, valid, ppm, window_m=2.0, k=1.3):
    """Darkening relative to the local clean paint: ref = local mean + k * local std over a
    Gaussian window of window_m (about the local P90). Removes lighting and macro tone; keeps
    stains as the eye compares them with the wall around them."""
    sig = window_m * ppm / 2.0
    m1 = masked_gauss(Y, valid, sig)
    m2 = masked_gauss(np.where(valid, Y * Y, 0.0), valid, sig)
    sd = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    ref = m1 + k * sd
    with np.errstate(invalid="ignore", divide="ignore"):
        D = 1.0 - Y / ref
    D[~valid] = np.nan
    return D


def _sliding_max(a, r, axis):
    """Max over a window of +-r along an axis (NaN = -inf), by repeated doubling."""
    out = a.copy()
    cur, done = a.copy(), 0
    # build max over [i, i + 2^k) then combine; simple and O(n log r)
    span = 1
    pw = [a]
    while span * 2 <= 2 * r + 1:
        prev = pw[-1]
        sh = np.full_like(prev, -np.inf)
        if axis == 0:
            sh[:-span] = prev[span:]
        else:
            sh[:, :-span] = prev[:, span:]
        pw.append(np.maximum(prev, sh))
        span *= 2
    # window [i - r, i + r] = max of two overlapping power-of-two windows
    k = len(pw) - 1
    p = 2 ** k
    w = 2 * r + 1
    m = pw[k]
    n = a.shape[axis]
    idx = np.arange(n)
    lo = np.clip(idx - r, 0, n - 1)
    hi = np.clip(idx + r - p + 1, 0, n - 1)
    if axis == 0:
        out = np.maximum(m[lo], m[hi])
    else:
        out = np.maximum(m[:, lo], m[:, hi])
    return out


def local_contrast_D(Y, valid, ppm, window_m=2.0, ref_block_m=0.10, meas_block_m=0.04):
    """Darkening against the locally cleanest wall, the way the eye reads a stain: the reference is
    the brightest 10 cm patch within +-window/2, smoothed; D_local = 1 - Y / ref, measured on
    meas_block_m block means (4 cm: above the material's own grain and photo noise). A uniform
    darkening of the whole wall gives D_local = 0 (it reads as a paint colour, not as weathering).
    Returns the D_local image at the measurement-block grid and that grid's ppm."""
    Yv = np.where(valid, Y, np.nan)
    fb = max(1, int(round(ref_block_m * ppm)))
    rb, rv = _down(Yv, fb)
    rb = np.where(rv >= 0.5, rb, -np.inf)
    r = max(1, int(round(window_m / 2.0 / ref_block_m)))
    ref = _sliding_max(_sliding_max(rb, r, 0), r, 1)
    ref = np.where(np.isfinite(ref), ref, np.nan)
    ref = masked_gauss(ref, np.isfinite(ref), r / 2.0)
    fm = max(1, int(round(meas_block_m * ppm)))
    mb, mv = _down(Yv, fm)
    mb = np.where(mv >= 0.5, mb, np.nan)
    # resample ref (block grid fb) onto the measurement grid (fm)
    H, W = mb.shape
    ys = np.clip(((np.arange(H) + 0.5) * fm / fb).astype(int), 0, ref.shape[0] - 1)
    xs = np.clip(((np.arange(W) + 0.5) * fm / fb).astype(int), 0, ref.shape[1] - 1)
    refm = ref[ys][:, xs]
    with np.errstate(invalid="ignore", divide="ignore"):
        Dl = 1.0 - mb / refm
    Dl[~np.isfinite(Dl)] = np.nan
    return Dl, ppm / fm


# ---------------------------------------------------------------------------------------------
# material (rules J1, J2)

J1_BANDS = [(0.005, 0.02), (0.02, 0.10), (0.10, 0.50), (0.50, 2.0)]


def band_rel_std(Y, valid, ppm, a, b):
    """Relative std (std / mean) of the band-pass of Y between feature sizes a and b metres
    (DoG with sigmas a/3 and b/3, as `bands`), over the valid pixels. NaN when the band does not
    fit: a below 2 px or b above the valid extent."""
    s1, s2 = a / 3.0 * ppm, b / 3.0 * ppm
    if a * ppm < 2.0:
        return float("nan")
    ys, xs = np.nonzero(valid)
    if ys.size < 100 or b * ppm > 0.75 * max(ys.max() - ys.min(), xs.max() - xs.min()):
        return float("nan")
    f = max(1, int(s1 // 3))
    d, vf = _down(np.where(valid, Y, np.nan), f)
    v = vf >= 0.5
    d = np.where(v, d, np.nan)
    g1 = masked_gauss(np.nan_to_num(d), v, s1 / f)
    g2 = masked_gauss(np.nan_to_num(d), v, s2 / f)
    bd = (g1 - g2)[v]
    mu = float(np.nanmean(d[v]))
    bd = bd[np.isfinite(bd)]
    if bd.size < 50 or mu <= 0:
        return float("nan")
    return float(bd.std() / mu)


def rms_slope_deg(h, ppm, a=0.001, b=0.010):
    """RMS slope angle (degrees) of a height map h (metres) band-passed to features a..b metres."""
    s1, s2 = max(a / 3.0 * ppm, 0.5), b / 3.0 * ppm
    d = gauss(h, s1) - gauss(h, s2)
    gy, gx = np.gradient(d, 1.0 / ppm)
    return float(np.degrees(np.sqrt(np.mean(np.arctan(np.hypot(gx, gy)) ** 2))))


def corr(a, b, valid=None):
    """Pearson correlation over the valid pixels."""
    v = np.isfinite(a) & np.isfinite(b)
    if valid is not None:
        v &= valid
    if v.sum() < 50:
        return float("nan")
    x, y = a[v] - a[v].mean(), b[v] - b[v].mean()
    den = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / den) if den > 0 else float("nan")
