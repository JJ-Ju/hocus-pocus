"""wx_noise.py - deterministic fields for the weathering generator (numpy only).

Every random stream is keyed by stable names (seed, layer, source id), never by call order, so a
control that changes one layer cannot reshuffle another (the round-7 decal bug).
"""
import hashlib

import numpy as np

from weather_measure import gauss, LEVELS


def rng(*keys):
    h = hashlib.blake2b(repr(keys).encode(), digest_size=16).digest()
    return np.random.default_rng(np.frombuffer(h, dtype=np.uint64))


def resize(a, shape):
    """Bilinear resize to shape (H, W)."""
    H, W = shape
    h, w = a.shape
    if (h, w) == (H, W):
        return a
    ys = (np.arange(H) + 0.5) * h / H - 0.5
    xs = (np.arange(W) + 0.5) * w / W - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, h - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)
    fy = np.clip(ys - y0, 0, 1)[:, None]
    fx = np.clip(xs - x0, 0, 1)[None, :]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def _bspline_axis(n_out, c0, step, n_in):
    """Indices and weights of a cubic B-spline lookup: output i samples coarse coordinate c0 + i*step."""
    c = c0 + np.arange(n_out) * step
    i0 = np.floor(c).astype(int)
    t = c - i0
    w = ((1 - t) ** 3 / 6, (3 * t ** 3 - 6 * t ** 2 + 4) / 6, (-3 * t ** 3 + 3 * t ** 2 + 3 * t + 1) / 6, t ** 3 / 6)
    idx = [np.clip(i0 + k, 0, n_in - 1) for k in (-1, 0, 1, 2)]
    return idx, w


def _blur(n, sy, sx):
    if abs(sy - sx) < 1e-6:
        return gauss(n, sy)
    from weather_measure import _box1
    for axis, s in ((0, sy), (1, sx)):
        if s >= 0.5:
            r = max(1, int(round((np.sqrt(12.0 * s * s / 3.0 + 1.0) - 1.0) / 2.0)))
            for _ in range(3):
                n = _box1(n, r, axis)
    return n


def gfield(shape, sigma_px, key, aniso=(1.0, 1.0)):
    """Gaussian random field, zero mean, unit std, correlation ~sigma_px. aniso=(sy, sx)
    stretches it (sy > sx: vertical structure). Built at reduced resolution for big sigmas, with
    a margin past every edge (no edge clamping), a keyed sub-cell offset (no shared lattices) and
    cubic B-spline upsampling (no curvature on node lines): round G, grid-breakup R3."""
    H, W = shape
    sy, sx = sigma_px * aniso[0], sigma_px * aniso[1]
    f = max(1, int(min(sy, sx) // 5))
    r = rng(*key)
    if f == 1:
        my, mx = int(3 * sy) + 2, int(3 * sx) + 2
        n = _blur(r.standard_normal((H + 2 * my, W + 2 * mx)), sy, sx)[my:my + H, mx:mx + W]
    else:
        cy, cx = sy / f, sx / f
        my, mx = int(np.ceil(3 * cy)) + 3, int(np.ceil(3 * cx)) + 3
        h, w = H // f + 2 * my + 3, W // f + 2 * mx + 3
        n = _blur(r.standard_normal((h, w)), cy, cx)
        oy, ox = r.random(2)
        iy, wy = _bspline_axis(H, my + oy, 1.0 / f, h)
        ix, wx = _bspline_axis(W, mx + ox, 1.0 / f, w)
        t = sum(wy[k][:, None] * n[iy[k]] for k in range(4))
        n = sum(wx[k][None, :] * t[:, ix[k]] for k in range(4))
    n = n - n.mean()
    sd = n.std()
    return n / sd if sd > 1e-12 else n


def tile_blend(t, shape, key, cell_px, rows=192):
    """Per-plane stochastic sampling of a tileable stochastic map t (h, w) or (h, w, c): a
    triangle grid of cell_px per edge, a random patch offset per vertex, and a mean- and
    variance-preserving blend of the three lookups (Heitz and Neyret 2018). Keyed: the same key
    gives the same sampling, so maps of one tile set stay aligned."""
    H, W = shape
    th, tw = t.shape[:2]
    seed = int(rng(*key).integers(1 << 30))
    mu = t.reshape(th * tw, -1).mean(0) if t.ndim == 3 else t.mean()
    out = np.empty((H, W) + t.shape[2:], np.float32)
    xs = np.arange(W)
    for y0 in range(0, H, rows):
        y1 = min(H, y0 + rows)
        y, x = np.mgrid[y0:y1, 0:W].astype(np.float64)
        y, x = y / cell_px, x / cell_px
        s, u = x - 0.57735027 * y, 1.15470054 * y
        i, j = np.floor(s).astype(np.int64), np.floor(u).astype(np.int64)
        fx, fy = s - i, u - j
        up = (fx + fy) > 1.0
        verts = [(i + up, j + up), (i + 1, j), (i, j + 1)]
        ws = [np.where(up, fx + fy - 1.0, 1.0 - fx - fy), np.where(up, 1.0 - fy, fx), np.where(up, 1.0 - fx, fy)]
        acc = 0.0
        Y = np.arange(y0, y1)[:, None]
        for (vi, vj), wk in zip(verts, ws):
            hsh = ((vi * 73856093) ^ (vj * 19349663) ^ seed) & 0x7FFFFFFF
            oy, ox = hsh % th, (hsh // th) % tw
            v = t[(Y + oy) % th, (xs[None, :] + ox) % tw] - mu
            acc = acc + (wk[..., None] * v if t.ndim == 3 else wk * v)
        nrm = np.sqrt(ws[0] ** 2 + ws[1] ** 2 + ws[2] ** 2)
        out[y0:y1] = mu + acc / (nrm[..., None] if t.ndim == 3 else nrm)
    return out


def octave_sigma(level, ppm):
    """Gaussian sigma (px) whose field has most energy at scale level index `level`."""
    s = LEVELS[level][0] * 1.4
    return s / 2.8 * ppm


def fbm(shape, ppm, levels, key, weights=None, aniso=(1.0, 1.0), ymax_px=None):
    """Sum of unit fields, one per scale level (indices into LEVELS), normalised to unit std.
    Equal weights give a balanced spectrum (rule C1). ymax_px caps each octave's vertical sigma
    (a pattern field restarts from storey to storey: grid-breakup R2)."""
    out = np.zeros(shape)
    for i, lv in enumerate(levels):
        w = 1.0 if weights is None else weights[i]
        if w == 0:
            continue
        sg = octave_sigma(lv, ppm)
        an = aniso
        if ymax_px is not None and sg * aniso[0] > ymax_px:
            an = (max(min(aniso[0], ymax_px / sg), 1e-3), aniso[1])
        out += w * gfield(shape, sg, key + ("oct", lv), an)
    sd = out.std()
    return out / sd if sd > 1e-12 else out


def lognormal(shape, ppm, levels, key, sigma=1.0, weights=None, aniso=(1.0, 1.0), ymax_px=None):
    """Multiplicative cascade: exp(sigma * fbm), normalised to mean 1. sigma ~0.8-1.4 puts
    40-65 % of the total in the top 20 % of cells while nothing reaches zero (80/20 with a floor)."""
    f = np.exp(sigma * fbm(shape, ppm, levels, key, weights, aniso, ymax_px))
    return f / f.mean()


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def over(a, b):
    """Alpha 'over' accumulation of opacity maps: layered build-up."""
    return 1.0 - (1.0 - a) * (1.0 - b)
