#!/usr/bin/env python3
"""frame_critique.py - picture-level self-critique for procedural renders.

Lets an agent art-direct its own Houdini/Karma output with numbers instead of a human eye.
Every test is independent and reports: value, target, status (pass/warn/fail/info/na), a
one-line plain-language explanation, the sub-metrics, and where its thresholds came from.
There is deliberately no single overall score.

Dependencies: Python 3, numpy, Pillow. scipy is used for a few filters when present.

Usage
  python frame_critique.py image.jpg [--profile realistic|painterly] [--mask regions.json]
         [--depth depth.png] [--ref ref1.jpg ...] [--json out.json] [--sheet out.jpg]
         [--crop x0,y0,x1,y1] [--fov 54.4] [--grid 3x3 --grid-trim 0.12]
  python frame_critique.py --pair a.jpg b.jpg [--json out.json] [--sheet out.jpg]

Mask file (all coordinates are in the cropped image; values <= 1 are read as fractions):
  {"wall":  {"rects": [[x0,y0,x1,y1], ...]},
   "focal": {"polygon": [[x,y], ...]},
   "sky":   {"png": "sky_mask.png"},
   "near": {...}, "mid": {...}, "far": {...}}
  Recognised names: wall (or surface), focal, sky, near/mid/far, facade.
  A Karma ID or depth AOV converted to PNG is the best source for these.

Tests (r5-meta section 2 numbering in brackets):
  value_range [T1]  value_grouping [T2]  squint [T2/T7b]  spectral_slope [T7b]
  saturation_budget [T5]  palette [T6]  depth_separation [T3]  detail_density [T9]
  repetition [T10]  streak_evenness [r4-visual 2: fringe share; T10 periodicity]
  micro_uniformity [r4-noise 6; --input-kind variance_map for local-variance maps]
  saliency [T8]  camera [believability 6]  reference_match [T7]  (grid mode: seed_spread [T11])
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:  # optional
    import scipy.ndimage as _ndi
    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _ndi = None
    HAVE_SCIPY = False

ANALYSIS_W = 1024
GRID_W = 256
VERSION = "0.1 (round A)"

# --------------------------------------------------------------------------------------------
# Thresholds. Every number has an origin string. [S] sourced, [I] inference / starting point,
# [A] set or checked against round-A acceptance judgments (not ground truth).
# --------------------------------------------------------------------------------------------
BASE_T = {
    "clip_hi_warn": (0.005, "[I] photographic practice: only speculars and the sun may clip"),
    "clip_hi_fail": (0.02, "[I] same; 2 % of the frame clipped is visible as blown paint"),
    "crush_warn": (0.02, "[I] crushed blacks beyond 2 % hide shadow detail"),
    "span_warn": (50.0, "[I] p1-p99 L* span under 50 reads flat/foggy for a sunlit exterior"),
    "surf_L_warn": (90.0, "realism.md: white masonry paint albedo <= 0.8; 0.8 under a correctly "
                          "exposed sun (18 % card -> 0.18) renders ~L* 92"),
    "surf_L_fail": (94.4, "realism.md: paint never above 240 sRGB = L* 94.4"),
    "notan_dom_pass": (1.5, "[S] 2:1 unequal-shapes rule (r5 T2) relaxed to 1.5 for photographs [I]"),
    "notan_dom_fail": (1.15, "[S] r5 T2: equal thirds = muddy; 1.15 ~ equal [I]"),
    "notan_eta_pass": (0.80, "[I] Otsu separability of the 3-value thumbnail"),
    "notan_eta_fail": (0.65, "[I]"),
    "notan_confetti_warn": (0.15, "[S] r5 T2 'confetti'; 15 % of area in tiny shapes [I]"),
    "squint_pass": (0.75, "[I] share of contrast (std) surviving a 64 px squint"),
    "squint_fail": (0.55, "[I]"),
    "slope_lo": (-1.5, "[S] natural images amplitude slope ~ -1 (Field 1987; van der Schaaf 1996), "
                       "art -1.2..-1.4 (r5 T7b); steeper than -1.5 reads CG-smooth [I]"),
    "slope_hi": (-0.85, "[S] same sources; shallower than -0.85 reads noisy [I]"),
    "chroma_hi": (40.0, "[I] C*ab 40 ~ Munsell chroma 6-7, above any facade base-colour limit"),
    "chroma_share_warn": (0.05, "[S] r5 T5 (5-10 %); Tokyo landscape plan: accent colours <= 5 % "
                                "of a facade"),
    "chroma_share_fail": (0.10, "[S] r5 T5 upper bound"),
    "paint_std": (True, "[S] Tokyo Metropolitan Landscape Plan exterior base-colour standard "
                        "(general area; Toshima/Machida tables): 0R-4.9YR C<=4 (V>=8.5: 1.5); "
                        "5YR-5Y C<=6 (2); other hues C<=2 (1). Munsell->CIELAB approx "
                        "V=L*/10, chroma=C*/6 [I]. Sources: toshiseibi.metro.tokyo.lg.jp/kenchiku/"
                        "keikan/keikaku21.pdf, city.toshima.lg.jp/documents/16762/"
                        "sikisaikizyun.pdf, city.arakawa.tokyo.jp/documents/3209/sikisai64_1.pdf"),
    "paint_fail_ratio": (1.5, "[I] 1.5x the base-colour limit allows for the Munsell approximation"),
    "pale_over_warn": (0.04, "[I] share of the frame that is pale (L* >= 85), unclipped and over "
                             "the V>=8.5 base-colour chroma limit"),
    "pale_over_fail": (0.10, "[I] a tenth of the frame in over-saturated pale paint = toy look "
                             "(believability 6)"),
    "harmony_warn": (0.75, "[I] share of chroma-weighted hue mass inside the best Matsuda template"),
    "ref_dE_warn": (15.0, "[I] palette distance; dE 10-20 is 'a different colour' in practice"),
    "ref_dE_fail": (25.0, "[I]"),
    "detail_a80_pass": (0.45, "[I] picture-level 80/20: believability 1 asks 70-85 % of detail in "
                              "15-25 % of a surface; a whole frame is allowed 45 %"),
    "detail_a80_fail": (0.62, "[I] uniform detail needs ~70-80 % of the frame for 80 % of energy"),
    "detail_rest_warn": (0.30, "[I] r5 T9: >= 30 % rest windows"),
    "detail_empty_warn": (0.80, "[I] r5 T9 opposite failure: an empty frame"),
    "streak_period_warn": (0.25, "[S] r5 T10 autocorrelation method on the darkening profile along "
                                 "each wall band; max of 1-D noise over 110 lags ~ 0.1, so 0.25 "
                                 "is a real repeat [I]. Real streaks line up with openings but "
                                 "1-2 columns in 5 are much worse (r4-visual 2), which keeps "
                                 "the peak low"),
    "streak_period_fail": (0.40, "[I] a clear secondary autocorrelation peak"),
    "streak_fringe_pass": (0.50, "[S] r4-visual 2: of 17 streak photos, sources were sill ends / "
                                 "window corners 6, drip-less tops 6, attachments 5, so ~35 % "
                                 "of streaks hang from a top edge; 0.50 allows for parapet-heavy "
                                 "views [I]"),
    "streak_fringe_fail": (0.70, "[I] twice the photographed share: nearly every streak hangs "
                                 "from the band top = a fringe"),
    "repeat_warn": (0.20, "[I] share of textured frame that is a near-copy (local NCC > 0.8) at "
                          "the strongest autocorrelation shift (r5 T10 method [S])"),
    "repeat_fail": (0.35, "[I]"),
    "micro_p9010_lo": (2.0, "[S] r4-noise 6: fail if p90/p10 < 2"),
    "micro_p9010_pass": (3.0, "[S] r4-noise 2: target p90/p10 3-6"),
    "micro_kurt_lo": (4.0, "[S] r4-noise 6: fail if kurtosis < 4"),
    "micro_cv_pass": (0.4, "[S] r4-noise 2: CV 0.4-0.8"),
    "sal_compete_warn": (3, "[I] r5 T8: competing peaks >= 75 % of the top peak"),
    "sal_compete_fail": (5, "[I]"),
    "sal_focus_warn": (0.10, "[I] saliency mass in the top 5 % of the frame; uniform = 0.05, "
                             "so 0.10 = twice uniform; round-A renders span 0.07-0.14"),
    "cam_tilt_warn": (2.0, "[S] believability 6: verticals kept straight with a level camera; "
                           "2 deg is visible [I]"),
    "cam_tilt_fail": (6.0, "[I]"),
    "cam_pitch_down_warn": (12.0, "[S] believability 6: eye height 1.5-1.7 m; a downward pitch "
                                  "over 12 deg is an elevated view [I]"),
    "cam_bare_ground": (0.6, "[S] believability 6: aerial over a bare plane reads as a miniature; "
                             "60 % rest windows below the horizon = bare [I]"),
    "ref_emd_L_warn": (8.0, "[I] L* histogram EMD vs reference"),
    "ref_emd_L_fail": (15.0, "[I]"),
    "ref_emd_C_warn": (5.0, "[I] C* histogram EMD vs reference"),
    "ref_emd_C_fail": (10.0, "[I]"),
    "seed_collapse_dE": (3.0, "[I] surface colours of all seeds within dE 3 = one look (r5 T11)"),
}

PAINTERLY_OVERRIDES = {
    "chroma_share_warn": (0.15, "[I] painterly profile: anime/painted keys allow more accent"),
    "chroma_share_fail": (0.25, "[I] painterly profile"),
    "paint_std": (False, "painterly profile: base-colour standard reported as info only"),
    "notan_dom_pass": (2.0, "[S] 2:1 rule applies in full to designed images (r5 T2)"),
    "slope_lo": (-1.9, "[I] painterly: flat cel shapes give steep spectra"),
    "slope_hi": (-0.7, "[I] painterly"),
    "detail_a80_pass": (0.40, "[I] painterly: stronger focus expected"),
    "cam_tilt_warn": (4.0, "[I] painterly: dramatic perspective allowed"),
    "cam_tilt_fail": (12.0, "[I] painterly"),
}


def thresholds(profile):
    t = dict(BASE_T)
    if profile == "painterly":
        t.update(PAINTERLY_OVERRIDES)
    return t


# --------------------------------------------------------------------------------------------
# Image utilities
# --------------------------------------------------------------------------------------------
def srgb_to_lin(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb_to_lab(rgb):
    lin = srgb_to_lin(rgb.astype(np.float32))
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], np.float32)
    xyz = lin @ m.T
    t = xyz / np.array([0.95047, 1.0, 1.08883], np.float32)
    e = 216.0 / 24389.0
    f = np.where(t > e, np.cbrt(np.maximum(t, 0)), (24389.0 / 27.0 * t + 16.0) / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1).astype(np.float32)


def lab_to_rgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    e = 6.0 / 29.0

    def finv(f):
        return np.where(f > e, f ** 3, 3 * e * e * (f - 4.0 / 29.0))
    xyz = np.stack([finv(fx) * 0.95047, finv(fy), finv(fz) * 1.08883], -1)
    m = np.array([[3.2404542, -1.5371385, -0.4985314],
                  [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    lin = np.clip(xyz @ m.T, 0, 1)
    s = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(s * 255 + 0.5, 0, 255).astype(np.uint8)


def lch(lab):
    C = np.hypot(lab[..., 1], lab[..., 2])
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360.0
    return C, h


def _box1d(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def gblur1d(a, sigma, axis):
    """Gaussian blur along one axis (3 box passes, or scipy when present)."""
    a = np.asarray(a, np.float32)
    if sigma <= 0.3:
        return a
    if HAVE_SCIPY:
        return _ndi.gaussian_filter1d(a, sigma, axis=axis, mode="nearest").astype(np.float32)
    w = math.sqrt(12.0 * sigma * sigma / 3.0 + 1.0)
    r = max(1, int(round((w - 1) / 2.0)))
    for _ in range(3):
        a = _box1d(a, r, axis)
    return a


def gblur(a, sigma, sigma_x=None):
    sx = sigma if sigma_x is None else sigma_x
    return gblur1d(gblur1d(a, sigma, 0), sx, 1)


def resize_f(a, w, h, up=False):
    im = Image.fromarray(np.asarray(a, np.float32))
    rs = Image.Resampling.BILINEAR if up else Image.Resampling.BOX
    return np.asarray(im.resize((int(w), int(h)), rs), np.float32)


def resize_mask(m, w, h):
    im = Image.fromarray((np.asarray(m) > 0).astype(np.uint8) * 255)
    return np.asarray(im.resize((int(w), int(h)), Image.Resampling.NEAREST)) > 127


def erode(m, r):
    if r < 1:
        return m.copy()
    f = m.astype(np.float32)
    f = _box1d(_box1d(f, r, 0), r, 1)
    return f > 0.999


def dilate(m, r):
    if r < 1:
        return m.copy()
    f = m.astype(np.float32)
    return _box1d(_box1d(f, r, 0), r, 1) > 1e-3


def close_mask(m, r):
    """Morphological closing: fills streak-sized holes in a colour-cluster mask."""
    return erode(dilate(m, r), r)


def label(mask):
    """4-connected components. Returns (labels, n). Pure numpy fallback by min-propagation."""
    mask = np.asarray(mask, bool)
    if HAVE_SCIPY:
        lab, n = _ndi.label(mask)
        return lab, n
    H, W = mask.shape
    big = H * W + 1
    lab = np.where(mask, np.arange(H * W).reshape(H, W) + 1, big).astype(np.int64)
    for _ in range(4 * (H + W) + 200):
        prev = lab
        m = lab.copy()
        m[1:, :] = np.minimum(m[1:, :], lab[:-1, :])
        m[:-1, :] = np.minimum(m[:-1, :], lab[1:, :])
        m[:, 1:] = np.minimum(m[:, 1:], lab[:, :-1])
        m[:, :-1] = np.minimum(m[:, :-1], lab[:, 1:])
        m = np.where(mask, m, big)
        # pointer jumping through the flat label table speeds up long snakes
        flat = m.ravel()
        idx = np.where(flat < big, flat - 1, 0)
        jumped = np.where(flat < big, np.minimum(flat, m.ravel()[idx]), big)
        lab = jumped.reshape(H, W)
        if np.array_equal(lab, prev):
            break
    out = np.zeros((H, W), np.int32)
    vals = np.unique(lab[mask])
    if len(vals):
        out[mask] = np.searchsorted(vals, lab[mask]) + 1
    return out, len(vals)


def kmeans(X, k, iters=30, seed=0):
    X = np.asarray(X, np.float32)
    rng = np.random.default_rng(seed)
    if len(X) > 40000:
        X_fit = X[rng.choice(len(X), 40000, replace=False)]
    else:
        X_fit = X
    k = min(k, len(X_fit))
    C = [X_fit[rng.integers(len(X_fit))]]
    for _ in range(1, k):
        d = np.min(((X_fit[:, None, :] - np.array(C)[None]) ** 2).sum(-1), 1)
        s = d.sum()
        C.append(X_fit[rng.choice(len(X_fit), p=d / s)] if s > 0 else X_fit[rng.integers(len(X_fit))])
    C = np.array(C, np.float32)
    for _ in range(iters):
        d = ((X_fit[:, None, :] - C[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        newC = np.array([X_fit[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(k)],
                        np.float32)
        if np.allclose(newC, C, atol=1e-3):
            C = newC
            break
        C = newC
    d = ((X[:, None, :] - C[None]) ** 2).sum(-1)
    return C, d.argmin(1)


def otsu_multi(values, nlev=3, bins=64):
    """Exhaustive multi-Otsu for 3 levels; returns thresholds and eta (separability)."""
    v = np.asarray(values, np.float64).ravel()
    lo, hi = v.min(), v.max() + 1e-6
    hist, edges = np.histogram(v, bins=bins, range=(lo, hi))
    p = hist / hist.sum()
    cent = 0.5 * (edges[:-1] + edges[1:])
    mu_t = (p * cent).sum()
    var_t = (p * (cent - mu_t) ** 2).sum()
    best, bt = -1, (bins // 3, 2 * bins // 3)
    P = np.cumsum(p)
    M = np.cumsum(p * cent)
    for i in range(1, bins - 1):
        for j in range(i + 1, bins):
            w0, w1, w2 = P[i - 1], P[j - 1] - P[i - 1], 1 - P[j - 1]
            if min(w0, w1, w2) <= 0:
                continue
            m0 = M[i - 1] / w0
            m1 = (M[j - 1] - M[i - 1]) / w1
            m2 = (M[-1] - M[j - 1]) / w2
            sb = w0 * (m0 - mu_t) ** 2 + w1 * (m1 - mu_t) ** 2 + w2 * (m2 - mu_t) ** 2
            if sb > best:
                best, bt = sb, (i, j)
    eta = best / var_t if var_t > 0 else 0.0
    return (edges[bt[0]], edges[bt[1]]), float(eta)


def circ_mean_deg(h, w=None):
    r = np.radians(h)
    w = np.ones_like(r) if w is None else w
    s, c = (w * np.sin(r)).sum(), (w * np.cos(r)).sum()
    R = math.hypot(s, c) / max(w.sum(), 1e-9)
    return math.degrees(math.atan2(s, c)) % 360.0, R


def gini(x):
    x = np.sort(np.asarray(x, np.float64).ravel())
    if x.sum() <= 0:
        return 0.0
    n = len(x)
    i = np.arange(1, n + 1)
    return float((2 * (i * x).sum() / (n * x.sum())) - (n + 1) / n)


def area_for_share(x, share=0.8):
    x = np.sort(np.asarray(x, np.float64).ravel())[::-1]
    if x.sum() <= 0:
        return 1.0
    c = np.cumsum(x) / x.sum()
    return float((np.searchsorted(c, share) + 1) / len(x))


def max_filter(a, r):
    if HAVE_SCIPY:
        return _ndi.maximum_filter(a, size=2 * r + 1, mode="nearest")
    p = np.pad(a, r, mode="edge")
    out = np.full_like(a, -np.inf)
    H, W = a.shape
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out = np.maximum(out, p[dy:dy + H, dx:dx + W])
    return out


def emd1d(a, b, bins, rng):
    ha, _ = np.histogram(a, bins=bins, range=rng)
    hb, _ = np.histogram(b, bins=bins, range=rng)
    ha = ha / max(ha.sum(), 1)
    hb = hb / max(hb.sum(), 1)
    bw = (rng[1] - rng[0]) / bins
    return float(np.abs(np.cumsum(ha) - np.cumsum(hb)).sum() * bw), float(np.minimum(ha, hb).sum())


def status_rank(s):
    return {"pass": 0, "info": 0, "na": 0, "warn": 1, "fail": 2}.get(s, 0)


def worst(*ss):
    return max(ss, key=status_rank)


def band_badness(v, lo, hi, scale):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0.0
    if lo is not None and v < lo:
        return (lo - v) / scale
    if hi is not None and v > hi:
        return (v - hi) / scale
    return 0.0


def R(x, n=3):
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        return round(float(x), n)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


# --------------------------------------------------------------------------------------------
# Frame: loads an image, holds analysis-resolution arrays, shared masks and segmentation.
# --------------------------------------------------------------------------------------------
def parse_crop(spec, W, H):
    if not spec:
        return None
    v = [float(s) for s in spec.split(",")]
    if all(abs(x) <= 1.0 for x in v):
        v = [v[0] * W, v[1] * H, v[2] * W, v[3] * H]
    return tuple(int(round(x)) for x in v)


class Frame:
    def __init__(self, path=None, img=None, crop=None, masks_path=None, depth_path=None,
                 name=None, kind="render"):
        self.kind = kind
        if img is None:
            img = Image.open(path).convert("RGB")
        if crop:
            box = parse_crop(crop, img.width, img.height) if isinstance(crop, str) else crop
            img = img.crop(box)
        self.path = path
        self.name = name or (os.path.basename(path) if path else "frame")
        self.native = np.asarray(img, np.uint8)
        self.H0, self.W0 = self.native.shape[:2]
        w = min(ANALYSIS_W, self.W0) if self.W0 >= 512 else self.W0
        h = int(round(self.H0 * w / self.W0))
        self.rgb = np.asarray(img.resize((w, h), Image.Resampling.LANCZOS), np.uint8)
        self.H, self.W = h, w
        self.lab = rgb_to_lab(self.rgb)
        self.clip = self.rgb.max(-1) >= 250
        self.white = self.rgb.min(-1) >= 250
        self.L = self.lab[..., 0]
        self.C, self.h = lch(self.lab)
        gw = min(GRID_W, w)
        gh = int(round(h * gw / w))
        self.gw, self.gh = gw, gh
        self.lab_g = np.stack([resize_f(self.lab[..., i], gw, gh) for i in range(3)], -1)
        self.C_g, self.h_g = lch(self.lab_g)
        self.masks = load_masks(masks_path, self.W, self.H, self.W0, self.H0) if masks_path             else {}
        self.depth = load_depth(depth_path, self.W, self.H) if depth_path else None
        self._sky = None
        self._seg = None
        self.maps = {}

    # sky ------------------------------------------------------------------------------------
    @property
    def sky(self):
        """Sky mask at analysis resolution (heuristic unless a 'sky' mask is given)."""
        if self._sky is None:
            if "sky" in self.masks:
                self._sky = self.masks["sky"]
            else:
                self._sky = resize_mask(self._sky_grid(), self.W, self.H)
        return self._sky

    def _sky_grid(self):
        L = self.lab_g[..., 0]
        C, h = self.C_g, self.h_g
        m = gblur(L, 1.0)
        sd = np.sqrt(np.maximum(gblur(L * L, 1.0) - m * m, 0))
        gy, gx = np.gradient(gblur(L, 0.7))
        g = np.hypot(gx, gy)
        smooth = (sd < 1.2) & (g < 1.2)
        colour = ((h >= 170) & (h <= 300) & (C >= 3)) | (C < 6)
        cand = smooth & colour
        lab, n = label(cand)
        if n == 0:
            return np.zeros_like(cand)
        top = np.unique(lab[0][lab[0] > 0])
        sky = np.isin(lab, top)
        # keep only regions that are a real sky: wide along the top row and >= 3 % of frame
        keep = np.zeros_like(sky)
        for t in top:
            r = lab == t
            if r[0].mean() >= 0.15 and r.mean() >= 0.03:
                keep |= r
        # fill small holes (wires, antennae) inside the sky
        if keep.any():
            ref = self.lab_g[keep].mean(0)
            close_col = np.sqrt(((self.lab_g - ref) ** 2).sum(-1)) < 8
            hole = gblur(keep.astype(np.float32), 1.5) > 0.6
            keep = keep | (hole & smooth & close_col)
        return keep

    # segmentation -----------------------------------------------------------------------------
    @property
    def seg(self):
        if self._seg is None:
            self._seg = segment_surfaces(self)
        return self._seg

    def surface_mask(self):
        """Mask of the main judged surface ('wall' mask wins), analysis resolution."""
        for key in ("wall", "surface"):
            if key in self.masks:
                return self.masks[key], key
        s = self.seg
        judged = [c for c in s["clusters"] if c["judged"]]
        if not judged:
            return None, None
        c = max(judged, key=lambda c: c["share"])
        m = resize_mask(s["labels"] == c["id"], self.W, self.H)
        # close streak-sized holes (streaks are darker and fall in another colour cluster)
        m = close_mask(m, max(6, int(0.025 * self.W))) & ~self.sky
        return m, "S%d" % c["id"]


def load_masks(path, W, H, W0=None, H0=None):
    """Masks are given in (cropped) image pixels, or as fractions when all values <= 1."""
    W0 = W0 or W
    H0 = H0 or H
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    out = {}
    for name, d in spec.items():
        m = Image.new("L", (W, H), 0)
        dr = ImageDraw.Draw(m)

        def sc(pts):
            flat = [abs(x) for p in pts for x in p]
            if flat and max(flat) <= 1.0:
                return [(p[0] * W, p[1] * H) for p in pts]
            return [(p[0] * W / W0, p[1] * H / H0) for p in pts]
        if isinstance(d, str):
            d = {"png": d}
        for r in d.get("rects", []):
            (x0, y0), (x1, y1) = sc([r[:2], r[2:]])
            dr.rectangle([x0, y0, x1, y1], fill=255)
        polys = d.get("polygons", [])
        if "polygon" in d:
            polys = polys + [d["polygon"]]
        for p in polys:
            dr.polygon(sc(p), fill=255)
        if "png" in d:
            pm = Image.open(os.path.join(base, d["png"])).convert("L").resize((W, H))
            m = Image.fromarray(np.maximum(np.asarray(m), np.asarray(pm)))
        out["surface" if name == "surface" else name] = np.asarray(m) > 127
    return out


def load_depth(path, W, H):
    im = Image.open(path)
    a = np.asarray(im.convert("F") if im.mode not in ("I;16", "I") else im, np.float32)
    a = resize_f(a, W, H)
    return a


# --------------------------------------------------------------------------------------------
# Surface segmentation and the paint-colour standard
# --------------------------------------------------------------------------------------------
def munsell_limit(h, V):
    """Tokyo landscape-plan base-colour chroma limit (Munsell) for CIELAB hue h and value V.

    Hue bands in CIELAB degrees (approx.): 0R-4.9YR ~ 10-58, 5YR-5Y ~ 58-95, other.
    Limits are blended over +-5 degrees at the band edges because the mapping is approximate.
    Works on scalars and arrays.
    """
    h = np.asarray(h, np.float32)
    V = np.asarray(V, np.float32)

    def lim_at(hh):
        hh = hh % 360
        a = (hh >= 10) & (hh < 58)
        b = (hh >= 58) & (hh <= 95)
        lo = np.where(a, 4.0, np.where(b, 6.0, 2.0))
        hi = np.where(a, 1.5, np.where(b, 2.0, 1.0))
        return lo, hi
    los, his = zip(*[lim_at(h + off) for off in (-5, 0, 5)])
    lo = sum(los) / 3.0
    hi = sum(his) / 3.0
    # value bands: 4 <= V < 8.5 -> lo; V >= 8.5 -> hi (blended over 8.0-9.0)
    t = np.clip((V - 8.0) / 1.0, 0, 1)
    out = lo * (1 - t) + hi * t
    return float(out) if np.ndim(out) == 0 else out


def segment_surfaces(fr, k=6):
    lab = fr.lab_g
    sky_g = resize_mask(fr.sky, fr.gw, fr.gh)
    valid = ~sky_g
    X = lab[valid].copy()
    if len(X) < 50:
        return {"labels": np.zeros((fr.gh, fr.gw), np.int32) - 1, "clusters": []}
    Xw = X * np.array([1.0, 1.6, 1.6], np.float32)  # chroma differences matter for surfaces
    C, lbl = kmeans(Xw, k, seed=1)
    labels = np.full((fr.gh, fr.gw), -1, np.int32)
    labels[valid] = lbl
    clusters = []
    N = fr.gh * fr.gw
    clip_g = resize_f(fr.white.astype(np.float32), fr.gw, fr.gh) > 0.3
    for j in range(len(C)):
        m = labels == j
        if not m.any():
            continue
        clip_share = float(clip_g[m].mean())
        L50_all = float(np.median(lab[m][:, 0]))
        # colour is only measurable on unclipped pixels
        mu = m & ~clip_g
        px = lab[mu] if mu.sum() >= max(20, 0.15 * m.sum()) else lab[m]
        Cc = np.hypot(px[:, 1], px[:, 2])
        hh = np.degrees(np.arctan2(px[:, 2], px[:, 1])) % 360
        hm, _ = circ_mean_deg(hh, Cc + 1e-3)
        L50 = float(np.median(px[:, 0]))
        C50 = float(np.median(Cc))
        cc, n = label(m)
        largest = np.bincount(cc.ravel())[1:].max() / N if n else 0
        ys = np.nonzero(m)[0]
        vegetation = (100 <= hm <= 170) and C50 > 6 and L50 < 70
        bluish = (180 <= hm <= 300) and C50 > 6
        judged = (m.mean() >= 0.06 and largest >= 0.02 and L50_all >= 40 and not vegetation
                  and not bluish)
        V = L50 / 10.0
        mchroma = C50 / 6.0
        lim = munsell_limit(hm, V)
        clusters.append({
            "id": j, "share": float(m.mean()), "largest_cc": float(largest),
            "L50": L50, "L50_all": L50_all, "clip_share": clip_share,
            "L95": float(np.percentile(lab[m][:, 0], 95)), "C50": C50, "hue": hm,
            "y_mean": float(ys.mean() / fr.gh), "judged": bool(judged),
            "munsell_V": V, "munsell_chroma": mchroma, "chroma_limit": lim,
            "limit_ratio": mchroma / lim if lim > 0 else 0,
            "rgb": "#%02x%02x%02x" % tuple(lab_to_rgb(np.array([[L50, px[:, 1].mean(),
                                                                 px[:, 2].mean()]]))[0]),
            "note": "vegetation?" if vegetation else ("blue (sky/glass?)" if bluish else
                                                       ("dark (<V4)" if L50 < 40 else "")),
        })
    clusters.sort(key=lambda c: -c["share"])
    return {"labels": labels, "clusters": clusters}


# --------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------
def result(name, status, value, target, explain, metrics, origin, badness=0.0, ref=""):
    return {"test": name, "status": status, "value": R(value), "target": target,
            "explain": explain, "metrics": {k: R(v) for k, v in metrics.items()},
            "origin": origin, "badness": R(badness), "source": ref}


def t_value_range(fr, T):
    L = fr.L
    p = np.percentile(L, [1, 5, 50, 95, 99])
    mx = fr.native.max(-1)
    clip = float((mx >= 250).mean())
    crush = float((mx <= 5).mean())
    span = float(p[4] - p[0])
    m, key = fr.surface_mask()
    s50 = s95 = None
    if m is not None and m.any():
        # judge the brightest large surface: pick the brightest judged cluster unless masked
        if key and key.startswith("S"):
            judged = [c for c in fr.seg["clusters"] if c["judged"]]
            cb = max(judged, key=lambda c: c["L50_all"])
            m = resize_mask(fr.seg["labels"] == cb["id"], fr.W, fr.H)
            key = "S%d" % cb["id"]
        s50 = float(np.median(L[m]))
        s95 = float(np.percentile(L[m], 95))
    st = "pass"
    why = []
    if clip > T["clip_hi_fail"][0]:
        st = worst(st, "fail"); why.append("%.1f %% of pixels clipped white" % (clip * 100))
    elif clip > T["clip_hi_warn"][0]:
        st = worst(st, "warn"); why.append("%.1f %% clipped" % (clip * 100))
    if s50 is not None:
        if s50 > T["surf_L_fail"][0]:
            st = worst(st, "fail"); why.append("brightest large surface median L* %.0f is above "
                                               "paint's 240 sRGB ceiling" % s50)
        elif s50 > T["surf_L_warn"][0]:
            st = worst(st, "warn"); why.append("brightest large surface median L* %.0f is "
                                               "brighter than white paint in sun" % s50)
    if span < T["span_warn"][0]:
        st = worst(st, "warn"); why.append("low dynamic range (p1-p99 span %.0f)" % span)
    if crush > T["crush_warn"][0]:
        st = worst(st, "warn"); why.append("%.1f %% crushed black" % (crush * 100))
    if not why:
        why.append("values sit inside photographic ranges; no surface brighter than white paint")
    bad = band_badness(s50 if s50 is not None else 0, None, T["surf_L_warn"][0], 4.0) + \
        band_badness(clip, None, T["clip_hi_warn"][0], 0.01)
    return result("value_range", st, s50 if s50 is not None else p[2],
                  "surface L* <= %.0f (warn) / %.1f (fail); clipped < %.1f %%" %
                  (T["surf_L_warn"][0], T["surf_L_fail"][0], T["clip_hi_warn"][0] * 100),
                  "; ".join(why),
                  {"L_p1": p[0], "L_p5": p[1], "L_p50": p[2], "L_p95": p[3], "L_p99": p[4],
                   "L_mean": float(L.mean()), "L_std": float(L.std()), "span_p1_p99": span,
                   "clipped_share": clip, "crushed_share": crush, "surface": key,
                   "surface_L50": s50, "surface_L95": s95},
                  {k: T[k][1] for k in ("clip_hi_warn", "surf_L_warn", "surf_L_fail",
                                        "span_warn")}, bad, "r5 T1")


def notan_maps(fr):
    sig = 0.0125 * fr.W
    Lb = gblur(fr.L, sig)
    gw = 128
    gh = max(8, int(round(fr.H * gw / fr.W)))
    Ls = resize_f(Lb, gw, gh)
    (t1, t2), eta = otsu_multi(Ls, 3)
    q3 = np.digitize(Ls, [t1, t2])
    # 5 levels by 1-D k-means
    C5, l5 = kmeans(Ls.reshape(-1, 1), 5, seed=2)
    order = np.argsort(C5[:, 0])
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    q5 = rank[l5].reshape(Ls.shape)
    return Ls, q3, q5, (t1, t2), eta


def shape_stats(q, nlev):
    N = q.size
    big, conf_area = 0, 0
    for lv in range(nlev):
        lab, n = label(q == lv)
        if n == 0:
            continue
        areas = np.bincount(lab.ravel())[1:] / N
        big += int((areas >= 0.01).sum())
        conf_area += float(areas[areas < 0.005].sum())
    return big, conf_area


def t_value_grouping(fr, T):
    Ls, q3, q5, (t1, t2), eta = notan_maps(fr)
    fr.maps["notan3"] = q3
    fr.maps["notan5"] = q5
    shares3 = np.array([(q3 == i).mean() for i in range(3)])
    shares5 = np.array([(q5 == i).mean() for i in range(5)])
    srt = np.sort(shares3)[::-1]
    dom = srt[0] / max(srt[1], 1e-6)
    big3, conf3 = shape_stats(q3, 3)
    big5, conf5 = shape_stats(q5, 5)
    read = eta * (1 - conf3)
    st = "pass"
    why = []
    if dom < T["notan_dom_fail"][0]:
        st = worst(st, "fail"); why.append("value groups are near-equal (%.2f:1) - no dominant "
                                           "value" % dom)
    elif dom < T["notan_dom_pass"][0]:
        st = worst(st, "warn"); why.append("weak dominance %.2f:1 between the two largest value "
                                           "groups" % dom)
    if eta < T["notan_eta_fail"][0]:
        st = worst(st, "fail"); why.append("3-value thumbnail barely separates (eta %.2f)" % eta)
    elif eta < T["notan_eta_pass"][0]:
        st = worst(st, "warn"); why.append("3-value thumbnail is soft (eta %.2f)" % eta)
    if conf3 > T["notan_confetti_warn"][0]:
        st = worst(st, "warn"); why.append("%.0f %% of the thumbnail is confetti" % (conf3 * 100))
    if not why:
        why.append("one value dominates (%.1f:1) in %d big shapes; reads as a thumbnail" %
                   (dom, big3))
    bad = band_badness(dom, T["notan_dom_pass"][0], None, 0.5) + \
        band_badness(eta, T["notan_eta_pass"][0], None, 0.1) + \
        band_badness(conf3, None, T["notan_confetti_warn"][0], 0.1)
    return result("value_grouping", st, dom,
                  "dominance >= %.2f:1, eta >= %.2f, confetti <= %.0f %%" %
                  (T["notan_dom_pass"][0], T["notan_eta_pass"][0],
                   T["notan_confetti_warn"][0] * 100),
                  "; ".join(why),
                  {"shares3_dark_mid_light": "/".join("%.2f" % s for s in shares3),
                   "shares5": "/".join("%.2f" % s for s in shares5), "dominance": dom,
                   "eta3": eta, "cuts_L": "%.0f/%.0f" % (t1, t2), "big_shapes3": big3,
                   "confetti3": conf3, "big_shapes5": big5, "confetti5": conf5,
                   "thumbnail_read": read},
                  {k: T[k][1] for k in ("notan_dom_pass", "notan_dom_fail", "notan_eta_pass",
                                        "notan_confetti_warn")}, bad, "r5 T2")


def t_squint(fr, T):
    L = fr.L
    full = resize_f(L, 512, max(8, int(fr.H * 512 / fr.W)))
    low = resize_f(L, 64, max(4, int(fr.H * 64 / fr.W)))
    s_full, s_low = float(full.std()), float(low.std())
    surv = s_low / max(s_full, 1e-6)
    gy, gx = np.gradient(full)
    gfull = float(np.hypot(gx, gy).mean())
    gy, gx = np.gradient(low)
    glow = float(np.hypot(gx, gy).mean()) * 64 / 512
    st = "pass" if surv >= T["squint_pass"][0] else ("warn" if surv >= T["squint_fail"][0]
                                                     else "fail")
    why = ("%.0f %% of the contrast survives a heavy squint: the picture is built on big shapes"
           % (surv * 100)) if st == "pass" else (
        "only %.0f %% of the contrast survives the squint: structure lives in small detail, "
        "big shapes are weak" % (surv * 100))
    return result("squint", st, surv, ">= %.2f" % T["squint_pass"][0], why,
                  {"std_full": s_full, "std_64px": s_low, "edge_energy_full": gfull,
                   "edge_energy_64px_scaled": glow, "edge_ratio": glow / max(gfull, 1e-6)},
                  {k: T[k][1] for k in ("squint_pass", "squint_fail")},
                  band_badness(surv, T["squint_pass"][0], None, 0.1), "r5 T2 squint")


def spectral_slope_value(L):
    H, W = L.shape
    a = (L - L.mean()) * np.outer(np.hanning(H), np.hanning(W))
    A = np.abs(np.fft.fftshift(np.fft.fft2(a)))
    fy = (np.arange(H) - H // 2) / H
    fx = (np.arange(W) - W // 2) / W
    f = np.hypot(fy[:, None], fx[None, :])
    edges = np.logspace(np.log10(0.008), np.log10(0.15), 18)
    xs, ys = [], []
    for i in range(len(edges) - 1):
        m = (f >= edges[i]) & (f < edges[i + 1])
        if m.sum() > 4:
            xs.append(np.log10(np.sqrt(edges[i] * edges[i + 1])))
            ys.append(np.log10(A[m].mean() + 1e-9))
    if len(xs) < 4:
        return float("nan")
    return float(np.polyfit(xs, ys, 1)[0])


def t_spectral_slope(fr, T):
    s = spectral_slope_value(fr.L)
    lo, hi = T["slope_lo"][0], T["slope_hi"][0]
    if math.isnan(s):
        return result("spectral_slope", "na", None, "", "image too small", {}, {})
    if s < lo:
        st, why = "warn", ("amplitude spectrum slope %.2f is steep: too little mid/high "
                           "frequency, reads CG-smooth" % s)
    elif s > hi:
        st, why = "warn", ("slope %.2f is shallow: too much fine-scale energy, reads noisy" % s)
    else:
        st, why = "pass", "slope %.2f is in the natural-image/art range" % s
    return result("spectral_slope", st, s, "%.2f .. %.2f" % (lo, hi), why,
                  {"amplitude_slope": s}, {k: T[k][1] for k in ("slope_lo", "slope_hi")},
                  band_badness(s, lo, hi, 0.2), "r5 T7b")


def t_saturation(fr, T):
    ns = ~fr.sky
    C, h = fr.C[ns], fr.h[ns]
    if C.size == 0:
        C, h = fr.C.ravel(), fr.h.ravel()
    hi_share = float((C > T["chroma_hi"][0]).mean())
    c25 = float((C > 25).mean())
    w = np.clip(C - 8, 0, None)
    if w.sum() > 0:
        hm, Rr = circ_mean_deg(h, w)
        hue_spread = math.degrees(math.sqrt(max(-2 * math.log(max(Rr, 1e-6)), 0)))
    else:
        hm, hue_spread = float("nan"), 0.0
    fr.maps["chroma"] = fr.C
    lim_px = munsell_limit(fr.h, fr.L / 10.0)
    pale = (~fr.sky) & (fr.L >= 85) & ~dilate(fr.white, 1)
    over = pale & (fr.C / 6.0 > lim_px)
    pale_share = float(over.mean())
    fr.maps["pale_over"] = over
    judged = [c for c in fr.seg["clusters"] if c["judged"]]
    surf = []
    st = "pass"
    why = []
    use_std = T["paint_std"][0]
    worst_ratio = 0.0
    if "wall" in fr.masks or "surface" in fr.masks:
        m = fr.masks.get("wall", fr.masks.get("surface"))
        px = fr.lab[m]
        Cc = np.hypot(px[:, 1], px[:, 2])
        hh = np.degrees(np.arctan2(px[:, 2], px[:, 1])) % 360
        hmm, _ = circ_mean_deg(hh, Cc + 1e-3)
        L50, C50 = float(np.median(px[:, 0])), float(np.median(Cc))
        lim = munsell_limit(hmm, L50 / 10)
        judged = [{"id": "mask", "share": float(m.mean()), "L50": L50, "C50": C50, "hue": hmm,
                   "munsell_V": L50 / 10, "munsell_chroma": C50 / 6, "chroma_limit": lim,
                   "limit_ratio": C50 / 6 / lim, "rgb": "", "judged": True}]
    for c in judged:
        ratio = c["limit_ratio"]
        worst_ratio = max(worst_ratio, ratio)
        cs = "pass"
        if ratio > T["paint_fail_ratio"][0]:
            cs = "fail"
        elif ratio > 1.0:
            cs = "warn"
        surf.append("S%s %s %.0f%% L*%.0f C*%.1f h%.0f -> Munsell ~V%.1f/C%.1f, limit %.1f "
                    "(%.1fx) %s" % (c["id"], c.get("rgb", ""), c["share"] * 100, c["L50"],
                                    c["C50"], c["hue"], c["munsell_V"], c["munsell_chroma"],
                                    c["chroma_limit"], ratio, cs.upper()))
        if use_std and cs != "pass":
            st = worst(st, cs)
            pale = " pale" if c["L50"] >= 75 else ""
            why.append("large%s surface S%s (L* %.0f, C* %.1f) is %.1fx over the facade "
                       "base-colour chroma limit" % (pale, c["id"], c["L50"], c["C50"], ratio))
    if use_std and pale_share > T["pale_over_fail"][0]:
        st = worst(st, "fail"); why.append("%.0f %% of the frame is pale paint tinted beyond any "
                                           "real facade colour (toy cream)" % (pale_share * 100))
    elif use_std and pale_share > T["pale_over_warn"][0]:
        st = worst(st, "warn"); why.append("%.0f %% of the frame is over-tinted pale paint" %
                                           (pale_share * 100))
    if hi_share > T["chroma_share_fail"][0]:
        st = worst(st, "fail"); why.append("%.0f %% of the frame is high-chroma" % (hi_share * 100))
    elif hi_share > T["chroma_share_warn"][0]:
        st = worst(st, "warn"); why.append("%.0f %% of the frame is high-chroma" % (hi_share * 100))
    if not judged:
        why.append("no large surface found to judge (pass a wall mask)")
    if not why:
        why.append("large surfaces are within facade base-colour limits; accents are under %.0f %%"
                   % (T["chroma_share_warn"][0] * 100))
    if not use_std and st == "pass":
        st = "pass"
    bad = (band_badness(worst_ratio, None, 1.0, 0.5) +
           band_badness(pale_share, None, T["pale_over_warn"][0], 0.03)) * (1 if use_std else 0) + \
        band_badness(hi_share, None, T["chroma_share_warn"][0], 0.05)
    return result("saturation_budget", st, worst_ratio,
                  "surface chroma <= 1.0x base-colour limit; C*>%.0f share <= %.0f %%" %
                  (T["chroma_hi"][0], T["chroma_share_warn"][0] * 100), "; ".join(why),
                  {"high_chroma_share": hi_share, "chroma25_share": c25,
                   "pale_oversat_share": pale_share,
                   "mean_C_nonsky": float(C.mean()), "p95_C_nonsky": float(np.percentile(C, 95)),
                   "hue_mean": hm, "hue_spread_deg": hue_spread, "surfaces": surf,
                   "worst_limit_ratio": worst_ratio},
                  {k: T[k][1] for k in ("chroma_hi", "chroma_share_warn", "chroma_share_fail",
                                        "paint_std", "paint_fail_ratio", "pale_over_warn",
                                        "pale_over_fail")}, bad, "r5 T5")


TEMPLATES = {  # Matsuda / Cohen-Or hue templates: (centre offset, width) sectors in degrees
    "i": [(0, 18)], "V": [(0, 93.6)], "L": [(0, 18), (90, 79.2)], "I": [(0, 18), (180, 18)],
    "T": [(0, 180)], "Y": [(0, 93.6), (180, 18)], "X": [(0, 93.6), (180, 93.6)],
}
TEMPLATE_WORDS = {"i": "monochromatic", "V": "analogous", "L": "analogous + 90deg accent",
                  "I": "complementary", "T": "half-wheel (wide)", "Y": "analogous + complement",
                  "X": "double complementary", "N": "near-neutral (achromatic)"}


def harmony(h, w):
    best = {}
    hb = np.round(h).astype(int) % 360
    hist = np.bincount(hb, weights=w, minlength=360)
    tot = hist.sum()
    if tot <= 0:
        return "N", 1.0, {}
    ang = np.arange(360)
    for name, secs in TEMPLATES.items():
        bs, ba = 0, 0
        for a in range(0, 360, 2):
            inside = np.zeros(360, bool)
            for off, wd in secs:
                c = (a + off) % 360
                d = np.abs((ang - c + 180) % 360 - 180)
                inside |= d <= wd / 2
            s = hist[inside].sum() / tot
            if s > bs:
                bs, ba = s, a
        best[name] = (bs, ba)
    order = ["i", "I", "V", "L", "Y", "X", "T"]
    for name in order:
        if best[name][0] >= 0.85:
            return name, best[name][0], best
    name = max(best, key=lambda n: best[n][0])
    return name, best[name][0], best


def palette_of(fr, k=6):
    X = fr.lab_g.reshape(-1, 3)
    C, lbl = kmeans(X, k, seed=3)
    shares = np.bincount(lbl, minlength=len(C)) / len(lbl)
    order = np.argsort(-shares)
    return C[order], shares[order]


def t_palette(fr, T, refs=None):
    C, sh = palette_of(fr)
    cols = lab_to_rgb(C)
    pal = ["#%02x%02x%02x %.0f%%" % (tuple(c) + (s * 100,)) for c, s in zip(cols, sh)]
    Cc, hh = fr.C_g.ravel(), fr.h_g.ravel()
    w = np.clip(Cc - 5, 0, None)
    mean_c = float(Cc.mean())
    if mean_c < 6 or w.sum() == 0:
        cls, share, best = "N", 1.0, {}
    else:
        cls, share, best = harmony(hh, w)
    warm = float(w[((hh >= 330) | (hh < 110))].sum() / max(w.sum(), 1e-9))
    cool = float(w[(hh >= 150) & (hh < 300)].sum() / max(w.sum(), 1e-9))
    st = "info"
    why = "%s palette (template %s holds %.0f %% of hue mass); warm %.0f %% / cool %.0f %%" % (
        TEMPLATE_WORDS[cls], cls, share * 100, warm * 100, cool * 100)
    if share < T["harmony_warn"][0]:
        st = "warn"
        why = "hue mass is scattered: best template %s holds only %.0f %%" % (cls, share * 100)
    m = {"palette": pal, "harmony_template": cls, "harmony_share": share,
         "warm_share": warm, "cool_share": cool, "mean_C": mean_c}
    bad = band_badness(share, T["harmony_warn"][0], None, 0.1)
    if refs:
        dEs = []
        for rf in refs:
            Cr, shr = palette_of(rf)
            d_ab = np.sqrt(((C[:, None] - Cr[None]) ** 2).sum(-1))
            dE = 0.5 * ((d_ab.min(1) * sh).sum() + (d_ab.min(0) * shr).sum())
            dEs.append(float(dE))
        dE = float(np.mean(dEs))
        m["ref_palette_dE"] = dE
        if dE > T["ref_dE_fail"][0]:
            st = "fail"
        elif dE > T["ref_dE_warn"][0]:
            st = worst(st, "warn")
        elif st == "info":
            st = "pass"
        why += "; palette distance to reference dE %.1f" % dE
        bad += band_badness(dE, None, T["ref_dE_warn"][0], 5)
    return result("palette", st, share, "template share >= %.2f%s" % (
        T["harmony_warn"][0], "; ref dE <= %.0f" % T["ref_dE_warn"][0] if refs else ""), why, m,
        {k: T[k][1] for k in ("harmony_warn", "ref_dE_warn", "ref_dE_fail")}, bad, "r5 T6")


def plane_stats(fr, m):
    if m is None or m.sum() < 50:
        return None
    L = fr.L[m]
    hp = fr.L - gblur(fr.L, 3)
    Cm = fr.C[m]
    hm, _ = circ_mean_deg(fr.h[m], Cm + 1e-3)
    return {"share": float(m.mean()), "L_mean": float(L.mean()),
            "L_iqr": float(np.percentile(L, 75) - np.percentile(L, 25)),
            "local_contrast": float(np.abs(hp[m]).mean()), "C_mean": float(Cm.mean()),
            "hue": hm}


def t_depth(fr, T, cam=None):
    mode = None
    near = mid = far = None
    if fr.depth is not None:
        d = fr.depth
        valid = ~fr.sky
        q1, q2 = np.percentile(d[valid], [33, 66])
        near, mid, far = valid & (d <= q1), valid & (d > q1) & (d <= q2), valid & (d > q2)
        mode = "depth AOV"
    elif all(k in fr.masks for k in ("near", "far")):
        near, far = fr.masks["near"], fr.masks["far"]
        mid = fr.masks.get("mid")
        mode = "region mask"
    else:
        hy = cam.get("horizon_y") if cam else None
        if hy is None or not (0.05 < hy < 0.98) or fr.sky.mean() < 0.03:
            return result("depth_separation", "na", None, "far plane: lower contrast and chroma",
                          "no depth AOV or near/far mask, and no horizon with sky to infer "
                          "distance from; pass --depth or a near/far mask", {}, {}, 0, "r5 T3")
        H, W = fr.H, fr.W
        hpx = int(hy * H)
        sky = fr.sky
        # skyline per column: first non-sky row
        nonsky = ~sky
        first = np.where(nonsky.any(0), nonsky.argmax(0), H)
        far_cols = first > (hpx - 0.18 * H)
        rows = np.arange(H)[:, None]
        far = nonsky & far_cols[None, :] & (rows < hpx + 0.02 * H)
        near = nonsky & (~far_cols[None, :]) & (rows < hpx - 0.2 * H)
        mode = "heuristic (skyline height vs horizon)"
    sn, sf = plane_stats(fr, near), plane_stats(fr, far)
    sm = plane_stats(fr, mid) if mid is not None else None
    if not sn or not sf:
        return result("depth_separation", "na", None, "", "planes too small to compare (%s)" %
                      mode, {"mode": mode}, {}, 0, "r5 T3")
    dc = sf["local_contrast"] / max(sn["local_contrast"], 1e-6)
    dch = sf["C_mean"] / max(sn["C_mean"], 1e-6)
    drops = (dc < 0.85) + (dch < 0.9)
    st = "pass" if drops == 2 else ("warn" if drops == 1 else "fail")
    if mode.startswith("heuristic") and st == "fail":
        st = "warn"
    why = {2: "far plane is softer and less saturated than near: aerial perspective reads",
           1: "only one of contrast/chroma falls with distance",
           0: "far plane is as crisp and saturated as near: flat CG depth, add haze"}[drops]
    m = {"mode": mode, "far_vs_near_contrast": dc, "far_vs_near_chroma": dch,
         "near": json.dumps({k: round(v, 2) for k, v in sn.items()}),
         "far": json.dumps({k: round(v, 2) for k, v in sf.items()})}
    if sm:
        m["mid"] = json.dumps({k: round(v, 2) for k, v in sm.items()})
    return result("depth_separation", st, dc, "far/near contrast < 0.85 and chroma < 0.9",
                  why + " [%s]" % mode, m, {"all": "[S] Gurney/r5 T3 rule; ratios [I]"},
                  band_badness(dc, None, 0.85, 0.2) + band_badness(dch, None, 0.9, 0.2), "r5 T3")


def detail_grid(fr):
    w = 512
    h = max(16, int(fr.H * w / fr.W))
    L = resize_f(gblur(fr.L, 0.8), w, h)
    gy, gx = np.gradient(L)
    g = np.hypot(gx, gy)
    win = 16
    ny, nx = h // win, w // win
    E = g[:ny * win, :nx * win].reshape(ny, win, nx, win).mean((1, 3))
    return E


def t_detail(fr, T):
    E = detail_grid(fr)
    fr.maps["detail"] = E
    a80 = area_for_share(E, 0.8)
    gi = gini(E)
    rest = float((E < 0.35 * E.mean()).mean())
    fr.maps["detail_rest"] = E < 0.35 * E.mean()
    st = "pass"
    why = []
    if a80 > T["detail_a80_fail"][0]:
        st = "fail"; why.append("detail is spread evenly: 80 %% of it needs %.0f %% of the frame"
                                % (a80 * 100))
    elif a80 > T["detail_a80_pass"][0]:
        st = "warn"; why.append("detail is only loosely focused (80 %% in %.0f %% of the frame)"
                                % (a80 * 100))
    if rest < T["detail_rest_warn"][0]:
        st = worst(st, "warn"); why.append("only %.0f %% of the frame is quiet" % (rest * 100))
    if rest > T["detail_empty_warn"][0]:
        st = worst(st, "warn"); why.append("%.0f %% of the frame is empty" % (rest * 100))
    if not why:
        why.append("80 %% of the detail sits in %.0f %% of the frame, %.0f %% rest area" %
                   (a80 * 100, rest * 100))
    return result("detail_density", st, a80, "area for 80 %% <= %.2f; rest >= %.2f" %
                  (T["detail_a80_pass"][0], T["detail_rest_warn"][0]), "; ".join(why),
                  {"area_for_80pct": a80, "gini": gi, "rest_share": rest,
                   "mean_grad_L_per_px512": float(E.mean())},
                  {k: T[k][1] for k in ("detail_a80_pass", "detail_a80_fail", "detail_rest_warn",
                                        "detail_empty_warn")},
                  band_badness(a80, None, T["detail_a80_pass"][0], 0.1) +
                  band_badness(rest, T["detail_rest_warn"][0], None, 0.1), "r5 T9")


def local_ncc(A, B, r):
    def bx(x):
        return _box1d(_box1d(x, r, 0), r, 1)
    ma, mb = bx(A), bx(B)
    va = bx(A * A) - ma * ma
    vb = bx(B * B) - mb * mb
    cov = bx(A * B) - ma * mb
    return cov / np.sqrt(np.maximum(va * vb, 1e-9)), va, vb


def t_repetition(fr, T):
    w = 512
    h = max(32, int(fr.H * w / fr.W))
    L = resize_f(fr.L, w, h)
    hp = L - gblur(L, 0.01 * w * 2)
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    F = np.fft.fft2(hp * win)
    ac = np.real(np.fft.ifft2(np.abs(F) ** 2))
    ac = np.fft.fftshift(ac) / max(ac[0, 0], 1e-9)
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.hypot(yy - cy, xx - cx)
    acm = np.where((rr > 0.03 * w) & (yy >= cy), ac, -1)  # half plane (ac is symmetric)
    pk = (acm == max_filter(acm, 3)) & (acm > 0.05)
    ys, xs = np.nonzero(pk)
    vals = acm[ys, xs]
    order = np.argsort(-vals)[:5]
    peaks = [(int(xs[i] - cx), int(ys[i] - cy), float(vals[i])) for i in order]
    fr.maps["autocorr"] = ac
    copy_share = 0.0
    best_shift = None
    textured_share = 0.0
    for dx, dy, v in peaks[:3]:
        if abs(dx) >= w // 2 or abs(dy) >= h // 2:
            continue
        A = hp[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
        B = hp[max(0, dy):max(0, dy) + A.shape[0], max(0, dx):max(0, dx) + A.shape[1]]
        if A.shape != B.shape or A.size < 100:
            continue
        ncc, va, vb = local_ncc(A, B, 8)
        tex = (va > 4.0) & (vb > 4.0)  # std > 2 L*: textured
        if tex.sum() < 50:
            continue
        cs = float((ncc[tex] > 0.8).mean() * tex.mean())
        if cs > copy_share:
            copy_share, best_shift, textured_share = cs, (dx, dy, v), float(tex.mean())
    st = "pass" if copy_share <= T["repeat_warn"][0] else (
        "warn" if copy_share <= T["repeat_fail"][0] else "fail")
    if best_shift:
        dx, dy, v = best_shift
        lag = "shift (%d, %d) px at 512 w" % (dx, dy)
    else:
        lag = "none"
    why = ("%.0f %% of the frame is a near-copy of itself at %s" % (copy_share * 100, lag))
    why += ": stencil/clone repeats are visible" if st != "pass" else ": no strong clone repeats"
    return result("repetition", st, copy_share, "near-copy share <= %.2f" % T["repeat_warn"][0],
                  why, {"autocorr_peaks_dx_dy_r": ["%d,%d,%.2f" % p for p in peaks],
                        "copy_share": copy_share, "textured_share": textured_share,
                        "best_shift": lag},
                  {k: T[k][1] for k in ("repeat_warn", "repeat_fail")},
                  band_badness(copy_share, None, T["repeat_warn"][0], 0.1), "r5 T10")


def band_profiles(fr, me, min_share=0.012):
    """Per wall band (connected piece of the wall mask): darkening profile along x."""
    lab, n = label(me)
    bands = []
    for k in range(1, n + 1):
        b = lab == k
        if b.mean() < min_share:
            continue
        cnt = b.sum(0)
        cols = np.nonzero(cnt >= 5)[0]
        if len(cols) < 150:
            continue
        ref = np.percentile(fr.L[b], 90)
        dk = np.where(b, np.clip(ref - fr.L, 0, None), 0).sum(0)
        prof = dk[cols] / cnt[cols]
        p = prof - gblur1d(prof[None].astype(np.float32), 40, 1)[0]  # drop the macro wash
        p = p - p.mean()
        ac = np.correlate(p, p, "full")[len(p) - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        hi = min(160, len(p) // 3)
        # a repeat is a secondary peak: search only beyond the first zero crossing, so the
        # width of a single streak (short-lag correlation) does not count as repetition
        neg = np.nonzero(ac[1:hi] <= 0)[0]
        if not len(neg):
            continue
        lo = int(neg[0]) + 1
        if hi - lo < 4:
            continue
        lag = int(np.argmax(ac[lo:hi]) + lo)
        bands.append({"cols": int(len(cols)), "periodicity": float(max(ac[lag], 0)),
                      "lag_px": lag, "first_zero_px": lo,
                      "coverage": float((p > 2.0).mean()), "amplitude": float(prof.std()),
                      "x0": int(cols[0]), "y": float(np.nonzero(b)[0].mean())})
    return bands


def streak_objects(fr, me):
    """Narrow vertical dark features inside the wall mask, with their band-relative position."""
    v = gblur1d(fr.L, 4, 0)
    s_ = gblur1d(v, 1.5, 1) - gblur1d(v, 10, 1)
    sd = 1.4826 * np.median(np.abs(s_[me] - np.median(s_[me]))) + 1e-6
    lab, n = label((-s_ > 2.5 * sd) & me)
    blab, _ = label(me)
    out = []
    if not n:
        return out, s_
    idx = np.nonzero(lab.ravel())[0]
    ids = lab.ravel()[idx]
    yy, xx = np.divmod(idx, fr.W)
    wts = -s_.ravel()[idx]
    cnt = np.bincount(ids, minlength=n + 1)
    sx = np.bincount(ids, xx, n + 1) / np.maximum(cnt, 1)
    strength = np.bincount(ids, wts, n + 1)
    ymin = np.full(n + 1, fr.H)
    ymax = np.zeros(n + 1)
    xmin = np.full(n + 1, fr.W)
    xmax = np.zeros(n + 1)
    np.minimum.at(ymin, ids, yy)
    np.maximum.at(ymax, ids, yy)
    np.minimum.at(xmin, ids, xx)
    np.maximum.at(xmax, ids, xx)
    for k in range(1, n + 1):
        h_ = ymax[k] - ymin[k] + 1
        w_ = xmax[k] - xmin[k] + 1
        if h_ < 6 or h_ < 1.5 * w_:
            continue
        x = int(round(sx[k]))
        band = blab[int(ymin[k]), min(max(x, 0), fr.W - 1)]
        if band == 0:
            continue
        col = np.nonzero(blab[:, x] == band)[0]
        if len(col) < 8:
            continue
        bh = col.max() - col.min() + 1
        out.append({"x": float(sx[k]), "y0": float(ymin[k]), "h": float(h_),
                    "strength": float(strength[k]), "len_rel": float(h_ / bh),
                    "top_rel": float((ymin[k] - col.min()) / bh)})
    return out, s_


def t_streaks(fr, T):
    """Run-off streaks on the wall bands: sourced, or a fringe hanging from every top edge?

    Main measure (fringe share): the share of streak objects (narrow vertical dark features in
    the wall mask) whose top sits within 15 % of the band height from the band's top edge.
    Photographs (r4-visual 2) put about a third of streaks at drip-less tops; the rest start at
    sill ends, window corners and attachments. Secondary: periodicity of the darkening profile
    along each band (secondary autocorrelation peak), streak-length spread (p90/p50; a power
    law gives a long tail) and the share of darkening in the strongest 20 % of streaks.
    Needs a wall mask for reliable numbers; with the automatic colour-cluster mask the result
    is reported as info only.
    """
    m, key = fr.surface_mask()
    auto = not ("wall" in fr.masks or "surface" in fr.masks)
    if m is None or m.mean() < 0.04:
        return result("streak_evenness", "na", None, "", "no large wall surface found (pass a "
                      "wall mask)", {}, {}, 0, "believability 1")
    me = erode(m, 3)
    fr.maps["streak_mask"] = me
    bands = band_profiles(fr, me)
    objs, s_ = streak_objects(fr, me)
    fr.maps["streak_objs"] = objs
    tile = 32
    ny, nx = fr.H // tile, fr.W // tile
    E = np.full((ny, nx), np.nan, np.float32)
    s2 = s_ * s_
    for j in range(ny):
        for i in range(nx):
            mm = me[j * tile:(j + 1) * tile, i * tile:(i + 1) * tile]
            if mm.mean() >= 0.5:
                E[j, i] = s2[j * tile:(j + 1) * tile, i * tile:(i + 1) * tile][mm].mean()
    fr.maps["streak"] = E
    if len(objs) < 8:
        return result("streak_evenness", "na", len(objs), "", "only %d streaks found on the "
                      "wall (%s): nothing to judge" % (len(objs), key),
                      {"surface": key, "auto_mask": auto, "streaks": len(objs)}, {}, 0,
                      "believability 1")
    fringe = float(np.mean([o["top_rel"] < 0.15 for o in objs]))
    lens = np.array([o["len_rel"] for o in objs])
    len_ratio = float(np.percentile(lens, 90) / max(np.median(lens), 1e-6))
    srt = np.sort([o["strength"] for o in objs])[::-1]
    top20 = float(srt[:max(1, int(round(0.2 * len(srt))))].sum() / srt.sum())
    per = [b_["periodicity"] for b_ in bands] if bands else [0.0]
    worst_p = float(max(per))
    fp, ff = T["streak_fringe_pass"][0], T["streak_fringe_fail"][0]
    st = "pass" if fringe <= fp else ("warn" if fringe <= ff else "fail")
    why = {"pass": "%.0f %% of streaks hang from a band's top edge; the rest start at other "
                   "sources, as in photographs" % (fringe * 100),
           "warn": "%.0f %% of streaks hang from the band top edges: drifting toward a fringe"
                   % (fringe * 100),
           "fail": "%.0f %% of streaks hang from the band top edges: a uniform fringe under every "
                   "coping instead of sourced streaks" % (fringe * 100)}[st]
    if worst_p > T["streak_period_warn"][0]:
        st = worst(st, "warn")
        why += "; the darkening also repeats along a band (peak %.2f)" % worst_p
    if auto:
        why += " [automatic wall mask: low confidence, reported as info; pass a wall mask]"
        st = "info"
    return result("streak_evenness", st, fringe, "fringe share <= %.2f (photos ~0.35)" % fp, why,
                  {"surface": key, "auto_mask": auto, "streaks": len(objs),
                   "fringe_share": fringe, "length_p90_p50": len_ratio,
                   "median_len_rel": float(np.median(lens)), "top20_share": top20,
                   "periodicity_worst": worst_p,
                   "periodicity_mean": float(np.mean(per)),
                   "band_detail": json.dumps([{k: round(v, 3) if isinstance(v, float) else v
                                               for k, v in b_.items()} for b_ in bands])},
                  {k: T[k][1] for k in ("streak_fringe_pass", "streak_fringe_fail",
                                        "streak_period_warn")},
                  band_badness(fringe, None, fp, 0.1) +
                  band_badness(worst_p, None, T["streak_period_warn"][0], 0.1),
                  "r4-visual 2 + believability 1 + r5 T10")


def micro_stats(Lnat, m, hp_sigma=1.5, win_sigma=6.0):
    hp = Lnat - gblur(Lnat, hp_sigma * 2)
    mu = gblur(hp, win_sigma)
    var = gblur(hp * hp, win_sigma) - mu * mu
    ls = np.sqrt(np.maximum(var, 0))
    v = ls[m]
    x = hp[m]
    if v.size < 200:
        return None
    p10, p90 = np.percentile(v, [10, 90])
    # floor: 0.25 L* is below 8-bit/JPEG quantisation; avoids dividing by flat (clipped) areas
    p10 = max(p10, 0.25)
    xs = x - x.mean()
    kurt = float((xs ** 4).mean() / max((xs ** 2).mean() ** 2, 1e-12))
    # trimmed: drop the 0.2 % largest |hp| (left-over geometry edges dominate raw kurtosis)
    q = np.percentile(np.abs(xs), 99.8)
    xt = xs[np.abs(xs) <= q]
    kurt_t = float((xt ** 4).mean() / max((xt ** 2).mean() ** 2, 1e-12))
    return {"cv_local_std": float(v.std() / max(v.mean(), 1e-9)),
            "p90_p10": float(p90 / p10), "kurtosis": kurt_t, "kurtosis_raw": kurt,
            "mean_local_std": float(v.mean())}, ls


def decode_map(rgb):
    """Scalar from a viridis-coloured (or grey) diagnostic map, 0..1."""
    px = rgb.reshape(-1, 3).astype(np.float32)
    if np.abs(px[:, 0] - px[:, 2]).mean() < 4:  # grey map
        return (px.mean(1) / 255.0).reshape(rgb.shape[:2])
    t = np.linspace(0, 1, 128)
    dense = cmap(t, _VIR).astype(np.float32)
    out = np.empty(len(px), np.float32)
    for i in range(0, len(px), 65536):
        d = ((px[i:i + 65536, None, :] - dense[None]) ** 2).sum(-1)
        out[i:i + 65536] = t[d.argmin(1)]
    return out.reshape(rgb.shape[:2])


def t_micro_map(fr, T):
    """Map mode: the input already encodes local micro amplitude (e.g. a local-variance AOV or
    a COP statistics output). Measure its spread directly."""
    m = fr.masks.get("wall", fr.masks.get("surface"))
    key = "mask" if m is not None else "frame"
    if m is None:
        m = np.ones((fr.H, fr.W), bool)
    val = decode_map(fr.rgb)[m]
    p10, p90 = np.percentile(val, [10, 90])
    r = float(p90 / max(p10, 1e-3))
    cv = float(val.std() / max(val.mean(), 1e-9))
    st = "fail" if r < T["micro_p9010_lo"][0] else (
        "warn" if r < T["micro_p9010_pass"][0] or cv < T["micro_cv_pass"][0] else "pass")
    why = ("micro amplitude map is %s (p90/p10 %.2f, CoV %.2f)" %
           ({"fail": "flat: stationary grain", "warn": "only mildly varied",
             "pass": "clustered"}[st], r, cv))
    return result("micro_uniformity", st, r, "p90/p10 3-6, CV 0.4-0.8 (map mode)", why,
                  {"surface": key, "mode": "variance_map", "p90_p10": r, "cv_local_std": cv},
                  {k: T[k][1] for k in ("micro_p9010_lo", "micro_p9010_pass", "micro_cv_pass")},
                  band_badness(r, T["micro_p9010_pass"][0], None, 0.5), "r4-noise 6")


def t_micro(fr, T):
    if getattr(fr, "kind", "render") == "variance_map":
        return t_micro_map(fr, T)
    m, key = fr.surface_mask()
    if m is None or m.mean() < 0.03:
        return result("micro_uniformity", "na", None, "", "no large surface to measure",
                      {}, {}, 0, "r4-noise 6")
    # native resolution (capped) so the grain band is real grain
    scale = min(1.0, 2048.0 / fr.W0)
    nw, nh = int(fr.W0 * scale), int(fr.H0 * scale)
    Ln = rgb_to_lab(np.asarray(Image.fromarray(fr.native).resize((nw, nh),
                                                                 Image.Resampling.LANCZOS)))[..., 0]
    mn = resize_mask(m, nw, nh)
    mn = erode(mn, 8)
    share_clip = 0.0
    cl = resize_mask(fr.clip, nw, nh)
    if mn.any():
        share_clip = float(cl[mn].mean())
    mn &= ~dilate(cl, 3)  # clipped paint has no measurable grain
    # drop strong edges (geometry, not grain)
    gy, gx = np.gradient(gblur(Ln, 2.0))
    g = np.hypot(gx, gy)
    if mn.sum() > 500:
        mn &= g < np.percentile(g[mn], 85)
    out = micro_stats(Ln, mn)
    if out is None:
        return result("micro_uniformity", "na", None, "", "surface too small after edge removal",
                      {"surface": key}, {}, 0, "r4-noise 6")
    s, ls = out
    if s["mean_local_std"] < 0.35:
        return result("micro_uniformity", "na", None, "", "surface has no measurable grain "
                      "(mean local std %.2f L*, below 8-bit/JPEG quantisation)" %
                      s["mean_local_std"], s, {}, 0, "r4-noise 6")
    fr.maps["micro"] = resize_f(np.where(mn, ls, 0), fr.W, fr.H)
    st = "pass"
    why = []
    if s["p90_p10"] < T["micro_p9010_lo"][0] or s["kurtosis"] < T["micro_kurt_lo"][0]:
        st = "fail"
        why.append("grain is stationary (p90/p10 %.2f, kurtosis %.1f): the same contrast "
                   "everywhere, reads as sandpaper" % (s["p90_p10"], s["kurtosis"]))
    elif s["p90_p10"] < T["micro_p9010_pass"][0] or s["cv_local_std"] < T["micro_cv_pass"][0]:
        st = "warn"
        why.append("grain varies a little (p90/p10 %.2f, CV %.2f); target 3-6 and 0.4-0.8" %
                   (s["p90_p10"], s["cv_local_std"]))
    else:
        why.append("grain is clustered (p90/p10 %.2f, CV %.2f, kurtosis %.1f)" %
                   (s["p90_p10"], s["cv_local_std"], s["kurtosis"]))
    s["surface"] = key
    s["surface_clipped_share"] = share_clip
    if share_clip > 0.3:
        why.append("%.0f %% of this surface is clipped, so its grain is gone there" %
                   (share_clip * 100))
    s["note"] = "pixel-scale band; geometry at distance also counts as 'grain'"
    return result("micro_uniformity", st, s["p90_p10"], "p90/p10 3-6, CV 0.4-0.8, kurtosis "
                  "5-20 (fail p90/p10 < 2 or kurt < 4)", "; ".join(why), s,
                  {k: T[k][1] for k in ("micro_p9010_lo", "micro_p9010_pass", "micro_kurt_lo",
                                        "micro_cv_pass")},
                  band_badness(s["p90_p10"], T["micro_p9010_pass"][0], None, 0.5), "r4-noise")


def saliency_map(fr):
    gw = 64
    gh = max(8, int(round(fr.H * gw / fr.W)))
    S = np.zeros((gh, gw), np.float32)
    for i, wt in ((0, 1.0), (1, 0.5), (2, 0.5)):
        ch = resize_f(fr.lab[..., i], gw, gh)
        ch = (ch - ch.mean()) / (ch.std() + 1e-6)
        F = np.fft.fft2(ch)
        A = np.log(np.abs(F) + 1e-6)
        P = np.angle(F)
        Rr = A - _box1d(_box1d(A, 1, 0), 1, 1)
        sr = np.abs(np.fft.ifft2(np.exp(Rr + 1j * P))) ** 2
        S += wt * gblur(sr.astype(np.float32), 2.0)
    S = S / (S.max() + 1e-9)
    # centre-surround colour/luminance contrast at 128 px
    cw = 128
    chh = max(8, int(round(fr.H * cw / fr.W)))
    cs = np.zeros((chh, cw), np.float32)
    for i, wt in ((0, 1.0), (1, 1.5), (2, 1.5)):
        ch = resize_f(fr.lab[..., i], cw, chh)
        cs += wt * np.abs(gblur(ch, 2) - gblur(ch, 16))
    cs = resize_f(cs, gw, gh)
    cs = cs / (cs.max() + 1e-9)
    S = 0.5 * S + 0.5 * cs
    return S / (S.max() + 1e-9)


def t_saliency(fr, T):
    S = saliency_map(fr)
    fr.maps["saliency"] = S
    gh, gw = S.shape
    # peaks: local maxima over a 25 %-of-width neighbourhood (separate regions of the frame)
    pk = (S == max_filter(S, max(2, int(0.12 * gw)))) & (S >= 0.4)
    ys, xs = np.nonzero(pk)
    order = np.argsort(-S[ys, xs])
    peaks = []
    for i in order[:6]:
        y, x = ys[i], xs[i]
        reg_lab, _ = label(S >= 0.5 * S[y, x])
        area = float((reg_lab == reg_lab[y, x]).mean())
        Y, X = int((y + 0.5) * fr.H / gh), int((x + 0.5) * fr.W / gw)
        win = (slice(max(0, Y - 6), Y + 7), slice(max(0, X - 6), X + 7))
        Lp, Cp = float(fr.L[win].mean()), float(fr.C[win].mean())
        Lmax = float(fr.L[win].max())
        artifact = area < 0.004 and (Lmax > 95 or Cp > 45)
        peaks.append({"x": round(x / gw, 3), "y": round(y / gh, 3), "s": round(float(S[y, x]), 3),
                      "area": round(area, 4), "L": round(Lp, 1), "C": round(Cp, 1),
                      "artifact": bool(artifact)})
    fr.maps["sal_peaks"] = peaks
    p = S.ravel() / S.sum()
    ent = float(-(p * np.log(p + 1e-12)).sum() / math.log(p.size))
    ps = np.sort(p)[::-1]
    focus = float(ps[:max(1, int(0.05 * ps.size))].sum())
    top = peaks[0]["s"] if peaks else 1
    compete = sum(1 for q in peaks if q["s"] >= 0.75 * top)
    st = "pass"
    why = []
    if compete >= T["sal_compete_fail"][0]:
        st = "fail"; why.append("%d peaks compete for attention" % compete)
    elif compete >= T["sal_compete_warn"][0]:
        st = "warn"; why.append("%d peaks compete for attention" % compete)
    if focus < T["sal_focus_warn"][0]:
        st = worst(st, "warn"); why.append("attention is spread over the frame (top 5 %% of area "
                                           "holds %.0f %% of saliency)" % (focus * 100))
    if peaks and peaks[0]["artifact"]:
        st = worst(st, "warn"); why.append("the top peak is a small bright/saturated spot at "
                                           "(%.2f, %.2f), likely a distractor" %
                                           (peaks[0]["x"], peaks[0]["y"]))
    m = {"entropy": ent, "focus_top5": focus, "competing_peaks": compete,
         "peaks": json.dumps(peaks[:3])}
    if "focal" in fr.masks:
        fm = resize_mask(fr.masks["focal"], gw, gh)
        inside = float(S[fm].sum() / S.sum())
        m["focal_mass"] = inside
        m["focal_lift"] = inside / max(fm.mean(), 1e-6)
        if m["focal_lift"] < 1.2:
            st = worst(st, "warn"); why.append("the focal region gets no more attention than its "
                                               "area (lift %.2f)" % m["focal_lift"])
    if not why:
        pk0 = peaks[0] if peaks else {"x": 0, "y": 0}
        why.append("one clear focus at (%.2f, %.2f), %d competing" % (pk0["x"], pk0["y"],
                                                                      compete))
    return result("saliency", st, compete, "competing peaks < %d, top-5 %% focus >= %.2f" %
                  (T["sal_compete_warn"][0], T["sal_focus_warn"][0]), "; ".join(why), m,
                  {k: T[k][1] for k in ("sal_compete_warn", "sal_compete_fail",
                                        "sal_focus_warn")},
                  band_badness(compete, None, T["sal_compete_warn"][0] - 1, 1) +
                  band_badness(focus, T["sal_focus_warn"][0], None, 0.03), "r5 T8")


def vertical_lines(fr):
    """Near-vertical straight lines: thin edges -> Hough over +-20 deg -> contiguity check."""
    L = gblur(fr.L, 1.2)
    gy, gx = np.gradient(L)
    mag = np.hypot(gx, gy)
    thr = np.percentile(mag, 80)
    # thin the edges: keep horizontal local maxima of the gradient magnitude
    nms = (mag >= np.roll(mag, 1, 1)) & (mag >= np.roll(mag, -1, 1))
    sel = (mag > max(thr, 1.5)) & nms & (np.abs(gx) > 3 * np.abs(gy))
    ys, xs = np.nonzero(sel)
    H, W = fr.H, fr.W
    cy = H / 2.0
    if len(xs) < 200:
        return []
    if len(xs) > 150000:
        idx = np.random.default_rng(0).choice(len(xs), 150000, replace=False)
        ys, xs = ys[idx], xs[idx]
    angs = np.arange(-20, 20.01, 0.25)
    t = np.tan(np.radians(angs))
    nb = W
    acc = np.zeros((len(t), nb), np.float32)
    for i, ti in enumerate(t):
        xc = xs - ti * (ys - cy)
        b = ((xc + 0.5 * W) / 2).astype(int)
        ok = (b >= 0) & (b < nb)
        acc[i] = np.bincount(b[ok], minlength=nb)[:nb]
    accs = acc + 0.5 * (np.roll(acc, 1, 1) + np.roll(acc, -1, 1))  # tolerate 1-bin wobble
    pk = (accs == max_filter(accs, 4)) & (accs >= 0.10 * H)
    ii, jj = np.nonzero(pk)
    order = np.argsort(-accs[ii, jj])[:120]
    seld = sel | np.roll(sel, 1, 1) | np.roll(sel, -1, 1)
    yy = np.arange(H)
    lines = []
    for o in order:
        i, j = ii[o], jj[o]
        xc = j * 2 - 0.5 * W + 1
        xs_l = np.round(xc + t[i] * (yy - cy)).astype(int)
        ok = (xs_l >= 0) & (xs_l < W)
        hit = np.zeros(H, bool)
        hit[ok] = seld[yy[ok], xs_l[ok]]
        # close gaps of <= 6 px, take the longest run, and require 60 % real hits inside it
        hc = np.convolve(hit.astype(float), np.ones(7), "same") > 0
        best, run, end = 0, 0, 0
        for k, v in enumerate(hc):
            run = run + 1 if v else 0
            if run > best:
                best, end = run, k
        hy_ = np.nonzero(hit)[0]
        span = (hy_[-1] - hy_[0]) if len(hy_) else 0
        # aligned but interrupted edges (a column of window jambs broken by slabs) count too:
        # >= 15 % of the height in hits, spread over >= 30 %, with some contiguous run
        if hit.sum() >= 0.15 * H and span >= 0.3 * H and best >= 0.05 * H and                 hit.sum() >= 0.45 * span:
            # suppress near-duplicates of an accepted line
            if any(abs(xc - l[0]) < 6 and abs(t[i] - l[1]) < 0.02 for l in lines):
                continue
            lines.append((float(xc), float(t[i]), float(best)))
        if len(lines) >= 40:
            break
    return lines


def t_camera(fr, T, fov=54.4):
    H, W = fr.H, fr.W
    cx, cy = W / 2.0, H / 2.0
    f = W / (2 * math.tan(math.radians(fov) / 2))
    lines = vertical_lines(fr)
    fr.maps["vlines"] = lines
    pitch = None
    tilt_edge = None
    lean = None
    vp = None
    roll = None
    vp_ok = False
    if len(lines) >= 3:
        xc = np.array([l[0] for l in lines])
        tt = np.array([l[1] for l in lines])
        wv = np.array([l[2] for l in lines])
        # median absolute lean of the lines (robust to a few false lines)
        lean = float(np.degrees(np.median(np.abs(np.arctan(tt)))))
        tilt_edge = lean
        if np.std(tt) < math.tan(math.radians(0.3)):
            pitch = 0.0
            roll = float(np.degrees(np.median(np.arctan(tt))))
        elif len(lines) >= 6 and np.ptp(xc) > 0.3 * W:
            A = np.stack([np.ones_like(tt), -tt], 1) * np.sqrt(wv)[:, None]
            b = (xc - tt * cy) * np.sqrt(wv)
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            xv, yv = sol
            res = np.abs(xv - tt * yv - (xc - tt * cy))
            keep = res <= max(2.5 * np.median(res), 4)
            if keep.sum() >= 6:
                sol, *_ = np.linalg.lstsq(A[keep], b[keep], rcond=None)
                xv, yv = sol
                res = np.abs(xv - tt * yv - (xc - tt * cy))[keep]
                vp_ok = float(np.median(res)) < 0.01 * W
            vp = (float(xv), float(yv))
            dist = cy - yv
            # a vertical VP inside the frame or far off to the side is a bad fit, not a camera
            if abs(dist) < 0.6 * H or abs(xv - cx) > 0.2 * abs(dist) + 0.5 * W:
                vp_ok = False
            if vp_ok and abs(dist) > 1e-3:
                pitch = math.degrees(math.atan(f / dist))
                if dist < 0:
                    pitch = -math.degrees(math.atan(f / -dist))
                # lean of a vertical at the left/right frame edge implied by the VP
                tilt_edge = math.degrees(math.atan((W / 2.0) / abs(dist)))
                roll = math.degrees(math.atan((xv - cx) / dist))
    horizon_vp = None
    if pitch is not None and abs(pitch) > 0.3:
        horizon_vp = (cy + f * math.tan(math.radians(pitch))) / H
    # horizon from the sky boundary (lowest unobstructed sky)
    horizon_sky = None
    if fr.sky.mean() > 0.03:
        sky = fr.sky
        has = sky[0]
        bottoms = np.array([np.nonzero(~sky[:, x])[0][0] if (~sky[:, x]).any() else H
                            for x in range(W)])[has]
        if len(bottoms) > 0.1 * W:
            horizon_sky = float(np.percentile(bottoms, 95) / H)
    hy = horizon_sky if horizon_sky is not None else (
        horizon_vp if horizon_vp is not None and 0 <= horizon_vp <= 1 else None)
    # ground below the horizon: bare if it is mostly rest windows
    bare = None
    if hy is not None and hy < 0.8:
        E = detail_grid(fr)
        r0 = int(np.ceil(hy * E.shape[0]))
        sub = E[r0:]
        if sub.size:
            bare = float((sub < 0.35 * E.mean()).mean())
    st = "pass"
    why = []
    if tilt_edge is not None:
        if tilt_edge > T["cam_tilt_fail"][0]:
            st = "fail"; why.append("verticals lean %.1f deg at the frame edges (keystoning)" %
                                    tilt_edge)
        elif tilt_edge > T["cam_tilt_warn"][0]:
            st = "warn"; why.append("verticals lean %.1f deg at the frame edges; level the camera "
                                    "and shift instead" % tilt_edge)
    elevated = (pitch is not None and pitch < -T["cam_pitch_down_warn"][0]) or \
        (hy is not None and hy < 0.30 and (pitch is None or pitch < 0))
    if elevated:
        st = worst(st, "warn")
        why.append("elevated viewpoint (pitch %s, horizon at %s of height)" % (
            "%.0f deg" % pitch if pitch is not None else "?", "%.2f" % hy if hy is not None
            else "?"))
        if bare is not None and bare > T["cam_bare_ground"][0]:
            st = "fail"
            why.append("looking down on a bare plane (%.0f %% of the ground is empty): reads as "
                       "a miniature" % (bare * 100))
    void = float(fr.sky[-1].mean()) > 0.3
    if void:
        st = "fail"
        why.append("the 'sky' runs to the bottom of the frame: subjects sit on a featureless "
                   "backdrop with no ground or horizon, which reads as a model")
    if not why:
        why.append("level, eye-height-like camera" if tilt_edge is not None else
                   "no vertical lines found; camera not judged")
    return result("camera", st, tilt_edge, "edge tilt <= %.0f deg; not looking down on a bare "
                  "plane" % T["cam_tilt_warn"][0], "; ".join(why),
                  {"vertical_lines": len(lines), "edge_tilt_deg": tilt_edge,
                   "median_line_lean_deg": lean, "vp_fit_ok": vp_ok,
                   "pitch_deg_est": pitch, "roll_deg_est": roll, "vp_xy_px": json.dumps(vp) if vp else None,
                   "horizon_y_from_vp": horizon_vp, "horizon_y_from_sky": horizon_sky,
                   "horizon_y": hy, "ground_rest_share": bare, "void_backdrop": void, "fov_assumed_deg": fov,
                   "sky_share": float(fr.sky.mean())},
                  {k: T[k][1] for k in ("cam_tilt_warn", "cam_tilt_fail", "cam_pitch_down_warn",
                                        "cam_bare_ground")},
                  band_badness(tilt_edge or 0, None, T["cam_tilt_warn"][0], 2) +
                  (1.0 if elevated else 0) + (1.0 if st == "fail" and elevated else 0),
                  "believability 6")


def t_reference(fr, T, refs):
    if not refs:
        return result("reference_match", "na", None, "", "no --ref given", {}, {}, 0, "r5 T7")
    rows = []
    for rf in refs:
        emdL, hiL = emd1d(fr.L, rf.L, 100, (0, 100))
        emdC, hiC = emd1d(fr.C, rf.C, 80, (0, 80))
        hm, _ = circ_mean_deg(fr.h.ravel(), fr.C.ravel())
        hr, _ = circ_mean_deg(rf.h.ravel(), rf.C.ravel())
        dh = abs((hm - hr + 180) % 360 - 180)
        con = fr.L.std() / max(rf.L.std(), 1e-6)
        ea, eb = detail_grid(fr).mean(), detail_grid(rf).mean()
        sa, sb = spectral_slope_value(fr.L), spectral_slope_value(rf.L)
        rows.append({"ref": rf.name, "emd_L": emdL, "hist_int_L": hiL, "emd_C": emdC,
                     "hist_int_C": hiC, "hue_diff_deg": dh, "contrast_ratio": con,
                     "hf_energy_ratio": ea / max(eb, 1e-9), "slope_diff": sa - sb})
    agg = {k: float(np.mean([r[k] for r in rows])) for k in rows[0] if k != "ref"}
    st = "pass"
    why = []
    if agg["emd_L"] > T["ref_emd_L_fail"][0]:
        st = "fail"; why.append("value histogram far from reference (EMD %.1f L*)" % agg["emd_L"])
    elif agg["emd_L"] > T["ref_emd_L_warn"][0]:
        st = "warn"; why.append("value histogram off reference (EMD %.1f L*)" % agg["emd_L"])
    if agg["emd_C"] > T["ref_emd_C_fail"][0]:
        st = "fail"; why.append("chroma histogram far from reference (EMD %.1f)" % agg["emd_C"])
    elif agg["emd_C"] > T["ref_emd_C_warn"][0]:
        st = worst(st, "warn"); why.append("chroma off reference (EMD %.1f)" % agg["emd_C"])
    if not why:
        why.append("value and chroma statistics match the reference set")
    m = dict(agg)
    m["refs"] = [r["ref"] for r in rows]
    return result("reference_match", st, agg["emd_L"], "EMD L* <= %.0f, EMD C* <= %.0f" %
                  (T["ref_emd_L_warn"][0], T["ref_emd_C_warn"][0]), "; ".join(why), m,
                  {k: T[k][1] for k in ("ref_emd_L_warn", "ref_emd_L_fail", "ref_emd_C_warn")},
                  band_badness(agg["emd_L"], None, T["ref_emd_L_warn"][0], 4) +
                  band_badness(agg["emd_C"], None, T["ref_emd_C_warn"][0], 3), "r5 T7")


# --------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------
def critique(fr, profile="realistic", refs=None, fov=54.4):
    T = thresholds(profile)
    tests = []
    tests.append(t_value_range(fr, T))
    tests.append(t_value_grouping(fr, T))
    tests.append(t_squint(fr, T))
    tests.append(t_spectral_slope(fr, T))
    tests.append(t_saturation(fr, T))
    tests.append(t_palette(fr, T, refs))
    cam = t_camera(fr, T, fov)
    tests.append(t_depth(fr, T, cam["metrics"]))
    tests.append(t_detail(fr, T))
    tests.append(t_repetition(fr, T))
    tests.append(t_streaks(fr, T))
    tests.append(t_micro(fr, T))
    tests.append(t_saliency(fr, T))
    tests.append(cam)
    tests.append(t_reference(fr, T, refs))
    summ = {"fail": [t["test"] for t in tests if t["status"] == "fail"],
            "warn": [t["test"] for t in tests if t["status"] == "warn"],
            "pass": [t["test"] for t in tests if t["status"] == "pass"],
            "na": [t["test"] for t in tests if t["status"] in ("na", "info")]}
    seg = [{k: (R(v) if not isinstance(v, str) else v) for k, v in c.items()}
           for c in fr.seg["clusters"]]
    return {"image": fr.path or fr.name, "name": fr.name, "profile": profile,
            "size": [fr.W0, fr.H0], "tool_version": VERSION, "scipy": HAVE_SCIPY,
            "sky_share": R(float(fr.sky.mean())), "surfaces": seg,
            "tests": {t["test"]: t for t in tests}, "summary": summ}


def seed_spread(img_path, grid, trim, crop, profile, fov):
    """Split a variation sheet into tiles and measure the spread between seeds (r5 T11)."""
    im = Image.open(img_path).convert("RGB")
    if crop:
        im = im.crop(parse_crop(crop, im.width, im.height))
    r, c = [int(x) for x in grid.lower().split("x")]
    tw, th = im.width // c, im.height // r
    tiles = []
    for j in range(r):
        for i in range(c):
            t = im.crop((i * tw, j * th, (i + 1) * tw, (j + 1) * th - int(th * trim)))
            fr = Frame(img=t, name="tile%d%d" % (j, i))
            res = critique(fr, profile, None, fov)
            judged = [s for s in fr.seg["clusters"] if s["judged"]]
            main = max(judged, key=lambda s: s["share"]) if judged else None
            row = {"tile": fr.name,
                   "surface_L": main["L50"] if main else None,
                   "surface_C": main["C50"] if main else None,
                   "surface_hue": main["hue"] if main else None,
                   "statuses": {k: v["status"] for k, v in res["tests"].items()}}
            for key, tn in (("detail_a80", "detail_density"), ("notan_dom", "value_grouping"),
                            ("sal_compete", "saliency"), ("limit_ratio", "saturation_budget"),
                            ("surface_L50", "value_range")):
                row[key] = res["tests"][tn]["value"]
            tiles.append(row)
    labs = []
    for t in tiles:
        if t["surface_L"] is not None:
            hr = math.radians(t["surface_hue"])
            labs.append([t["surface_L"], t["surface_C"] * math.cos(hr), t["surface_C"] * math.sin(hr)])
    labs = np.array(labs)
    spread = {}
    if len(labs) >= 2:
        d = np.sqrt(((labs[:, None] - labs[None]) ** 2).sum(-1))
        iu = np.triu_indices(len(labs), 1)
        spread["surface_dE_max"] = float(d[iu].max())
        spread["surface_dE_median"] = float(np.median(d[iu]))
        i, j = iu[0][d[iu].argmin()], iu[1][d[iu].argmin()]
        spread["most_similar_pair"] = "%s~%s (dE %.1f)" % (tiles[i]["tile"], tiles[j]["tile"],
                                                           d[i, j])
        out = int(np.argmax(np.median(d, 1)))
        spread["outlier_tile"] = tiles[out]["tile"]
    for key in ("detail_a80", "notan_dom", "limit_ratio", "surface_L50"):
        v = np.array([t[key] for t in tiles if t[key] is not None], float)
        if len(v):
            spread[key + "_cov"] = float(v.std() / max(abs(v.mean()), 1e-9))
            spread[key + "_range"] = "%.2f..%.2f" % (v.min(), v.max())
    T = thresholds(profile)
    collapsed = spread.get("surface_dE_max", 99) < T["seed_collapse_dE"][0]
    fails = {}
    for t in tiles:
        for k, s in t["statuses"].items():
            if s == "fail":
                fails[k] = fails.get(k, 0) + 1
    st = "warn" if collapsed else "info"
    why = ("seeds collapse to one surface look (max dE %.1f)" % spread["surface_dE_max"]
           if collapsed else "surface colour spread across seeds: max dE %.1f, median %.1f" % (
               spread.get("surface_dE_max", 0), spread.get("surface_dE_median", 0)))
    if fails:
        why += "; failing in most tiles: " + ", ".join(
            "%s %d/%d" % (k, n, len(tiles)) for k, n in sorted(fails.items(), key=lambda x: -x[1]))
    return {"image": img_path, "grid": grid, "status": st, "explain": why, "spread": spread,
            "tiles": tiles, "fail_counts": fails,
            "origin": T["seed_collapse_dE"][1]}


# --------------------------------------------------------------------------------------------
# Diagnostic contact sheet
# --------------------------------------------------------------------------------------------
_VIR = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
                np.float32)
_MAG = np.array([[0, 0, 4], [81, 18, 124], [183, 55, 121], [252, 137, 97], [252, 253, 191]],
                np.float32)


def cmap(x, lut=_VIR):
    x = np.clip(np.nan_to_num(x, nan=0.0), 0, 1) * (len(lut) - 1)
    i = np.clip(np.floor(x).astype(int), 0, len(lut) - 2)
    t = (x - i)[..., None]
    return (lut[i] * (1 - t) + lut[i + 1] * t).astype(np.uint8)


def _font(size):
    for f in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def panel_images(fr, res, pw):
    ph = int(round(pw * fr.H / fr.W))
    out = []

    def up(a, nearest=True):
        im = Image.fromarray(a)
        return im.resize((pw, ph), Image.Resampling.NEAREST if nearest else
                         Image.Resampling.BILINEAR)
    tests = res["tests"]
    out.append(("render  " + fr.name[:34], Image.fromarray(fr.rgb).resize((pw, ph),
                                                                        Image.Resampling.LANCZOS)))
    q3 = fr.maps.get("notan3")
    if q3 is not None:
        g = np.array([35, 128, 225], np.uint8)[q3]
        out.append(("3 values  dom %.2f  eta %.2f  [%s]" % (
            tests["value_grouping"]["metrics"]["dominance"],
            tests["value_grouping"]["metrics"]["eta3"], tests["value_grouping"]["status"]),
            up(np.stack([g] * 3, -1))))
    # surfaces judged
    lab = fr.seg["labels"]
    cols = np.zeros(lab.shape + (3,), np.uint8)
    for c in fr.seg["clusters"]:
        rgb = tuple(int(c["rgb"][i:i + 2], 16) for i in (1, 3, 5))
        cols[lab == c["id"]] = rgb
    skyg = resize_mask(fr.sky, fr.gw, fr.gh)
    cols[skyg] = (90, 140, 255)
    im = up(cols)
    d = ImageDraw.Draw(im)
    fnt = _font(11)
    for c in fr.seg["clusters"]:
        if not c["judged"]:
            continue
        m = lab == c["id"]
        ys, xs = np.nonzero(m)
        x, y = xs.mean() * pw / fr.gw, ys.mean() * ph / fr.gh
        stt = "FAIL" if c["limit_ratio"] > 1.5 else ("warn" if c["limit_ratio"] > 1 else "ok")
        d.rectangle([x - 2, y - 2, x + 118, y + 14], fill=(0, 0, 0))
        d.text((x, y), "S%d L%.0f C%.0f %.1fx %s" % (c["id"], c["L50"], c["C50"],
                                                     c["limit_ratio"], stt),
               fill=(255, 80, 80) if stt == "FAIL" else (255, 255, 255), font=fnt)
    out.append(("surfaces (blue=sky) [%s]" % tests["saturation_budget"]["status"], im))
    Cm = fr.maps.get("chroma", fr.C)
    rgbc = cmap(Cm / 50.0, _MAG)
    po = fr.maps.get("pale_over")
    if po is not None:
        rgbc[po] = (0, 255, 255)
    out.append(("chroma C* 0-50, cyan=pale over-tint %.0f%% [%s]" % (
        tests["saturation_budget"]["metrics"].get("pale_oversat_share", 0) * 100,
        tests["saturation_budget"]["status"]), up(rgbc, False)))
    E = fr.maps.get("detail")
    if E is not None:
        e = E / (np.percentile(E, 98) + 1e-9)
        im = up(cmap(e))
        out.append(("detail  80%% in %.0f%%  rest %.0f%% [%s]" % (
            tests["detail_density"]["metrics"]["area_for_80pct"] * 100,
            tests["detail_density"]["metrics"]["rest_share"] * 100,
            tests["detail_density"]["status"]), im))
    S = fr.maps.get("saliency")
    if S is not None:
        grey = np.asarray(Image.fromarray(fr.rgb).convert("L").resize((pw, ph)), np.float32)
        heat = cmap(np.asarray(Image.fromarray((S * 255).astype(np.uint8)).resize(
            (pw, ph), Image.Resampling.BILINEAR), np.float32) / 255.0, _MAG).astype(np.float32)
        blend = (0.45 * grey[..., None] + 0.55 * heat).astype(np.uint8)
        im = Image.fromarray(blend)
        d = ImageDraw.Draw(im)
        for k, p in enumerate(fr.maps.get("sal_peaks", [])[:3]):
            x, y = p["x"] * pw, p["y"] * ph
            r = 10 - 2 * k
            d.ellipse([x - r, y - r, x + r, y + r], outline=(0, 255, 255), width=2)
            d.text((x + r + 1, y - 6), str(k + 1), fill=(0, 255, 255), font=fnt)
        out.append(("saliency  %d competing  focus %.2f [%s]" % (
            tests["saliency"]["metrics"]["competing_peaks"],
            tests["saliency"]["metrics"]["focus_top5"], tests["saliency"]["status"]), im))
    St = fr.maps.get("streak")
    base = np.asarray(Image.fromarray(fr.rgb).convert("L").resize((pw, ph)), np.float32)
    if St is not None:
        v = St / (np.nanpercentile(St, 98) + 1e-9)
        rgb = cmap(v)
        rgb[np.isnan(St)] = (40, 40, 40)
        im = up(rgb).convert("RGB")
        a = np.asarray(im, np.float32)
        a = (0.7 * a + 0.3 * base[..., None]).astype(np.uint8)
        im = Image.fromarray(a)
        d = ImageDraw.Draw(im)
        sx_ = pw / fr.W
        objs = fr.maps.get("streak_objs", [])
        for q in objs:
            col = (255, 60, 60) if q["top_rel"] < 0.15 else (0, 255, 255)
            d.line([(q["x"] * sx_, q["y0"] * sx_), (q["x"] * sx_, (q["y0"] + q["h"]) * sx_)],
                   fill=col, width=2)
        sm = tests["streak_evenness"]["metrics"]
        out.append(("streaks red=from top edge: fringe %s%s [%s]" % (
            fmt(sm.get("fringe_share")), " auto-mask" if sm.get("auto_mask") else "",
            tests["streak_evenness"]["status"]), im))
    ac = fr.maps.get("autocorr")
    if ac is not None:
        a = np.clip((ac + 0.05) / 0.5, 0, 1)
        im = up(cmap(a), False)
        d = ImageDraw.Draw(im)
        d.text((4, ph - 16), "centre = zero shift; bright off-centre spots = repeats",
               fill=(255, 255, 255), font=_font(10))
        out.append(("autocorrelation  near-copy %.0f%% [%s]" % (
            tests["repetition"]["metrics"]["copy_share"] * 100,
            tests["repetition"]["status"]), im))
    # camera: detected vertical lines and horizon
    im = Image.fromarray(fr.rgb).resize((pw, ph), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(im)
    sx = pw / fr.W
    cyy = fr.H / 2.0
    for xc, t, _ in fr.maps.get("vlines", []):
        y0, y1 = 0, fr.H
        d.line([((xc + t * (y0 - cyy)) * sx, y0 * sx), ((xc + t * (y1 - cyy)) * sx, y1 * sx)],
               fill=(255, 60, 60), width=1)
    cm = tests["camera"]["metrics"]
    if cm.get("horizon_y") is not None:
        y = cm["horizon_y"] * ph
        d.line([(0, y), (pw, y)], fill=(0, 255, 0), width=2)
    out.append(("camera  lean %s deg, pitch %s [%s]" % (
        fmt(cm.get("edge_tilt_deg")), fmt(cm.get("pitch_deg_est")), tests["camera"]["status"]),
        im))
    return out, ph


def make_sheet(items, out_path, title="", pw=400, ncol=3, max_kb=390):
    """items: list of (frame, result). Each frame gets a block of diagnostic panels."""
    blocks = []
    for fr, res in items:
        panels, ph = panel_images(fr, res, pw)
        blocks.append((panels, ph, res))
    lab_h = 16
    head = 26 if title else 0
    foot = 18
    Ht = head
    for panels, ph, _ in blocks:
        nrow = int(math.ceil(len(panels) / float(ncol)))
        Ht += nrow * (ph + lab_h) + foot
    Wt = ncol * pw + (ncol - 1) * 3
    sheet = Image.new("RGB", (Wt, Ht), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    fnt = _font(12)
    if title:
        d.text((6, 5), title, fill=(255, 255, 255), font=_font(15))
    y = head
    for panels, ph, res in blocks:
        for i, (lbl, im) in enumerate(panels):
            x = (i % ncol) * (pw + 3)
            yy = y + (i // ncol) * (ph + lab_h)
            d.text((x + 3, yy + 1), lbl, fill=(230, 230, 230), font=fnt)
            sheet.paste(im.convert("RGB"), (x, yy + lab_h))
        nrow = int(math.ceil(len(panels) / float(ncol)))
        y += nrow * (ph + lab_h)
        s = res["summary"]
        d.text((4, y + 2), "%s   FAIL: %s   WARN: %s" % (
            res["name"], ", ".join(s["fail"]) or "-", ", ".join(s["warn"]) or "-"),
            fill=(255, 190, 120), font=_font(12))
        y += foot
    q = 85
    while True:
        sheet.save(out_path, quality=q, optimize=True)
        if os.path.getsize(out_path) <= max_kb * 1024 or q <= 35:
            break
        q -= 6
    if os.path.getsize(out_path) > max_kb * 1024:
        sc = 0.8
        sheet.resize((int(Wt * sc), int(Ht * sc)), Image.Resampling.LANCZOS).save(
            out_path, quality=70, optimize=True)
    return out_path


# --------------------------------------------------------------------------------------------
# Text output
# --------------------------------------------------------------------------------------------
def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return "%.3g" % v
    return str(v)


def print_report(res, out=sys.stdout):
    out.write("\n== %s  (%dx%d, profile %s)\n" % (res["name"], res["size"][0], res["size"][1],
                                                  res["profile"]))
    for name, t in res["tests"].items():
        out.write("[%-4s] %-18s value=%-8s target: %s\n        %s\n" % (
            t["status"].upper(), name, fmt(t["value"]), t["target"], t["explain"]))
    s = res["summary"]
    out.write("Summary: %d fail (%s), %d warn (%s), %d pass, %d n/a or info\n" % (
        len(s["fail"]), ", ".join(s["fail"]), len(s["warn"]), ", ".join(s["warn"]),
        len(s["pass"]), len(s["na"])))


def pair_table(ra, rb):
    rows = []
    for name in ra["tests"]:
        a, b = ra["tests"][name], rb["tests"].get(name)
        if b is None:
            continue
        ka = (status_rank(a["status"]), a["badness"] or 0)
        kb = (status_rank(b["status"]), b["badness"] or 0)
        if a["status"] in ("na",) or b["status"] in ("na",):
            better = "-"
        elif ka < kb:
            better = "A"
        elif kb < ka:
            better = "B"
        else:
            better = "="
        rows.append({"test": name, "A_status": a["status"], "A_value": a["value"],
                     "B_status": b["status"], "B_value": b["value"], "better": better,
                     "target": a["target"]})
    return rows


def print_pair(ra, rb, rows, out=sys.stdout):
    out.write("\n== A/B  A=%s  B=%s\n" % (ra["name"], rb["name"]))
    out.write("%-18s %-6s %-9s %-6s %-9s %s\n" % ("test", "A", "A value", "B", "B value",
                                                   "better"))
    for r in rows:
        out.write("%-18s %-6s %-9s %-6s %-9s %s\n" % (r["test"], r["A_status"], fmt(r["A_value"]),
                                                     r["B_status"], fmt(r["B_value"]),
                                                     r["better"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image", nargs="?")
    ap.add_argument("--pair", nargs=2, metavar=("A", "B"))
    ap.add_argument("--profile", default="realistic", choices=["realistic", "painterly"])
    ap.add_argument("--mask")
    ap.add_argument("--mask-b", help="mask for B in --pair mode")
    ap.add_argument("--depth")
    ap.add_argument("--ref", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--sheet", help="write a diagnostic contact sheet (JPG)")
    ap.add_argument("--crop", help="x0,y0,x1,y1 (pixels or fractions), e.g. to drop captions")
    ap.add_argument("--crop-b")
    ap.add_argument("--fov", type=float, default=54.4, help="horizontal FOV (35 mm = 54.4)")
    ap.add_argument("--grid", help="RxC: treat the image as a seed contact sheet (seed spread)")
    ap.add_argument("--input-kind", default="render", choices=["render", "variance_map"],
                    help="variance_map: the image is a local-variance visualisation")
    ap.add_argument("--grid-trim", type=float, default=0.0,
                    help="fraction of each tile's bottom to drop (labels)")
    a = ap.parse_args(argv)
    refs = [Frame(p) for p in a.ref] if a.ref else None
    if a.pair:
        fa = Frame(a.pair[0], crop=a.crop, masks_path=a.mask)
        fb = Frame(a.pair[1], crop=a.crop_b, masks_path=a.mask_b)
        ra, rb = critique(fa, a.profile, refs, a.fov), critique(fb, a.profile, refs, a.fov)
        rows = pair_table(ra, rb)
        print_report(ra)
        print_report(rb)
        print_pair(ra, rb, rows)
        out = {"A": ra, "B": rb, "pair": rows}
        if a.sheet:
            make_sheet([(fa, ra), (fb, rb)], a.sheet, "A/B: %s vs %s" % (fa.name, fb.name))
    elif a.grid:
        out = seed_spread(a.image, a.grid, a.grid_trim, a.crop, a.profile, a.fov)
        print(json.dumps({k: out[k] for k in ("status", "explain", "spread")}, indent=1))
    else:
        if not a.image:
            ap.error("image required")
        fr = Frame(a.image, crop=a.crop, masks_path=a.mask, depth_path=a.depth,
                   kind=a.input_kind)
        out = critique(fr, a.profile, refs, a.fov)
        print_report(out)
        if a.sheet:
            make_sheet([(fr, out)], a.sheet, fr.name)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, default=str)
    return out


if __name__ == "__main__":
    main()
