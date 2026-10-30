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


def gfield(shape, sigma_px, key, aniso=(1.0, 1.0)):
    """Gaussian random field, zero mean, unit std, correlation ~sigma_px. aniso=(sy, sx)
    stretches it (sy > sx: vertical structure). Built at reduced resolution for big sigmas."""
    H, W = shape
    sy, sx = sigma_px * aniso[0], sigma_px * aniso[1]
    f = max(1, int(min(sy, sx) // 5))
    h, w = max(4, H // f + 3), max(4, W // f + 3)
    n = rng(*key).standard_normal((h, w))
    if abs(sy - sx) < 1e-6:
        n = gauss(n, sy / f)
    else:
        from weather_measure import _box1
        for axis, s in ((0, sy / f), (1, sx / f)):
            if s >= 0.5:
                r = max(1, int(round((np.sqrt(12.0 * s * s / 3.0 + 1.0) - 1.0) / 2.0)))
                for _ in range(3):
                    n = _box1(n, r, axis)
    n = resize(n, (H + 2 * f, W + 2 * f))[f:f + H, f:f + W] if f > 1 else n[:H, :W]
    n = n - n.mean()
    sd = n.std()
    return n / sd if sd > 1e-12 else n


def octave_sigma(level, ppm):
    """Gaussian sigma (px) whose field has most energy at scale level index `level`."""
    s = LEVELS[level][0] * 1.4
    return s / 2.8 * ppm


def fbm(shape, ppm, levels, key, weights=None, aniso=(1.0, 1.0)):
    """Sum of unit fields, one per scale level (indices into LEVELS), normalised to unit std.
    Equal weights give a balanced spectrum (rule C1)."""
    out = np.zeros(shape)
    for i, lv in enumerate(levels):
        w = 1.0 if weights is None else weights[i]
        if w == 0:
            continue
        out += w * gfield(shape, octave_sigma(lv, ppm), key + ("oct", lv), aniso)
    sd = out.std()
    return out / sd if sd > 1e-12 else out


def lognormal(shape, ppm, levels, key, sigma=1.0, weights=None, aniso=(1.0, 1.0)):
    """Multiplicative cascade: exp(sigma * fbm), normalised to mean 1. sigma ~0.8-1.4 puts
    40-65 % of the total in the top 20 % of cells while nothing reaches zero (80/20 with a floor)."""
    f = np.exp(sigma * fbm(shape, ppm, levels, key, weights, aniso))
    return f / f.mean()


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def over(a, b):
    """Alpha 'over' accumulation of opacity maps: layered build-up."""
    return 1.0 - (1.0 - a) * (1.0 - b)
