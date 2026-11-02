"""wx_hires.py - the weathered facade at game texel density (round I).

The generator (weather_fields.py) decides where and how much at 50 px/m and saves its layer stack
(steps_<plane>.npz: each layer's alpha and colour). This module replays that stack at any texel
density, the way the engine's layered material does it:
- the clean coat from the round-E tiles (hex-tiled, about 570-1700 px/m) under the facade's colours;
- each weathering layer's coarse mask upsampled with a cubic B-spline, then refined by its own
  tileable detail texture (wx_detail): films are modulated (mean kept), deposits and growth take
  coverage from the detail (coverage kept), so edges and inner structure are sharp at 1 mm per pixel;
- joints rendered as 20 mm grooves, the coat's relief and the breaks lit by the same sun as the
  50 px/m previews.

python -I wx_hires.py <build_dir> <plane> <x0,y0,x1,y1 at 50 px/m> <ppm> <out.jpg> [--clean]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_detail as wd  # noqa: E402
from weather_fields import TEXDIR  # noqa: E402

F32 = np.float32
P50 = 50.0
LIGHT = np.array([-0.35, 0.55, 0.76]) / np.linalg.norm([-0.35, 0.55, 0.76])
CACHE = os.environ.get("WX_DETAIL_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_detail_cache"))
DPPM = 1000.0                      # detail tiles: 1 mm per pixel
CROPS = os.environ.get("WX_CROPS", "")   # folder of crop captures (crop_capture.py), optional

# capture class codes -> gate classes (as real_planes.py)
_CODES = {0: "none", 1: "paint_ext", 2: "coping", 3: "soffit", 4: "concrete", 5: "glass", 6: "decal", 7: "steel",
          8: "alu", 9: "board", 10: "frp", 11: "room", 12: "fabric", 13: "plastic", 14: "sign", 15: "floor", 16: "metal"}
_GATE = {"paint_ext": 1, "coping": 2, "soffit": 3, "concrete": 4, "glass": 6, "steel": 7, "alu": 7, "metal": 7,
         "frp": 8, "plastic": 8, "fabric": 8, "board": 8, "sign": 8, "room": 8, "floor": 8, "decal": 1, "none": 0}
LUT = np.zeros(256, np.uint8)
for _c, _n in _CODES.items():
    LUT[_c] = _GATE[_n]


def load_capture(plane, box, ppm):
    """The crop capture for exactly this box and density, if there is one."""
    if not CROPS:
        return None
    v = plane.split("_")[0]
    fn = os.path.join(CROPS, "%s_%d_%d_%d_%d_%d.npz" % ((v,) + tuple(box) + (int(ppm),)))
    if not os.path.exists(fn):
        return None
    z = np.load(fn)
    code = z["class_raw"].astype(np.int64)
    return {"cls": LUT[np.clip(code, 0, 255)], "steel": np.isin(code, (7, 16)), "albedo": z["albedo"][..., :3].astype(F32),
            "N": z["N"].astype(F32)}

# how each layer is refined at high resolution: (mode, detail tile, cell or band m, width or k,
# colour variation, share of the coat's receptivity in the detail)
FILM_SPLIT_M = 0.03     # round I (T3): the film's detail split at this scale (m): below it the grain, above it the blotches
FILM_DENSE = 1.0        # round I (T3): the modulation x (1 - this x the film's own opacity)
FILM_WK = (0.40, 0.10)  # their weights (the film modulation was 0.40 at every scale: T3 failed from Typical up)
REFINE = {
    "soiling": ("film", "grime", 0.30, 0.40, 0.06, 0.75),
    "stains": ("cover", "stain", 0.45, 0.60, 0.08, 0.45),
    "streaks": ("band", "streak", 0.35, 0.55, 0.10, 0.30),
    "base": ("cover", "splash", 0.30, 0.45, 0.10, 0.35),
    "bio": ("cover", "bio", 0.30, 0.30, 0.14, 0.50),
    "rust": ("cover", "rust", 0.20, 0.25, 0.18, 0.0),
    "cracks": ("cover", "crack", 0.20, 0.35, 0.0, 0.0),
    "efflorescence": ("cover", "effl", 0.25, 0.30, 0.06, 0.3),
    "wear": ("cover", "chip", 0.20, 0.12, 0.05, 0.0),
    "peeling": ("cover", "chip", 0.25, 0.12, 0.05, 0.0),
    "damage": ("cover", "chip", 0.20, 0.10, 0.0, 0.0),
}
PEAK_R = 2                  # the local opacity a layer's spots take: max over (2 r + 1) coarse px, smoothed


# ---------------------------------------------------------------------------------------------
# detail tiles

def _make_tile(name):
    S = wd.spectral
    if name == "grime":
        f = 0.55 * S(1024, 1024, 4, 4, 2.5, "grime_a") + 0.45 * S(1024, 1024, 30, 30, 3.0, "grime_b")
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "streak":
        f = (0.50 * S(4096, 1024, 300, 3, 3.0, "streak_a") + 0.35 * S(4096, 1024, 900, 20, 3.0, "streak_b")
             + 0.15 * S(4096, 1024, 2, 2, 2.0, "streak_c"))
        return wd.Tile(name, f, 1.024, 4.096, rotate=False)
    if name == "stain":
        f = 0.65 * S(2048, 2048, 60, 60, 3.0, "stain_a") + 0.35 * S(2048, 2048, 8, 8, 2.0, "stain_b")
        return wd.Tile(name, f, 2.048, 2.048)
    if name == "splash":
        sp = wd.splats(1024, 1024, 0.004, 0.6, 5.0, 2.6, "splash_specks")
        f = 1.6 * sp + 0.35 * S(1024, 1024, 40, 40, 3.0, "splash_cloud") + 0.15 * S(1024, 1024, 2, 2, 2.0, "splash_fine")
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "bio":
        cl = wd.norm_cdf(S(1024, 1024, 80, 80, 3.0, "bio_cluster"))
        sp = wd.splats(1024, 1024, 0.0035, 1.5, 22.0, 2.2, "bio_colonies", cluster=np.clip((cl - 0.25) / 0.6, 0, 1))
        sp = wd.circ_conv(sp, wd.disc_kernel(1.5, 1.0) / wd.disc_kernel(1.5, 1.0).sum())
        f = 1.4 * sp + 0.5 * S(1024, 1024, 18, 18, 2.6, "bio_film") + 0.2 * S(1024, 1024, 2.5, 2.5, 2.0, "bio_fine")
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "rust":
        f = (0.55 * S(1024, 1024, 15, 15, 3.0, "rust_blotch") + 0.25 * S(1024, 1024, 60, 60, 3.0, "rust_big")
             + 0.6 * wd.splats(1024, 1024, 0.006, 0.5, 3.0, 2.5, "rust_pits"))
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "effl":
        f = 0.6 * S(1024, 1024, 2, 2, 1.5, "effl_a") + 0.4 * S(1024, 1024, 20, 20, 3.0, "effl_b")
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "chip":
        f = 0.6 * S(1024, 1024, 6, 6, 2.2, "chip_a") + 0.4 * S(1024, 1024, 40, 40, 3.0, "chip_b")
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "crack":
        f = S(1024, 1024, 2, 2, 2.0, "crack_a")
        return wd.Tile(name, f, 1.024, 1.024)
    raise KeyError(name)


_TILES = {}


def tile(name):
    if name not in _TILES:
        os.makedirs(CACHE, exist_ok=True)
        fn = os.path.join(CACHE, "tile_%s.npz" % name)
        if os.path.exists(fn):
            z = np.load(fn)
            t = wd.Tile.__new__(wd.Tile)
            t.name, t.u, t.g = name, z["u"], z["g"]
            t.w_m, t.h_m, t.rotate = float(z["w_m"]), float(z["h_m"]), bool(z["rotate"])
            t.extra = {}
            t._lv = {}
        else:
            t = _make_tile(name)
            np.savez(fn, u=t.u, g=t.g, w_m=t.w_m, h_m=t.h_m, rotate=t.rotate)
        _TILES[name] = t
    return _TILES[name]


# the round-E coat
_COAT = {}


def _img(name, mode=None):
    im = Image.open(os.path.join(TEXDIR, name))
    if mode == "I16":
        return np.asarray(im, np.float64) / 65535.0
    return np.asarray(im.convert(mode) if mode else im, np.float64) / 255.0


def _blur_tile(a, sigma_px):
    ny, nx = a.shape[:2]
    ky = np.fft.fftfreq(ny)[:, None]
    kx = np.fft.rfftfreq(nx)[None, :]
    G = np.exp(-2 * (np.pi * sigma_px) ** 2 * (ky * ky + kx * kx))
    if a.ndim == 2:
        return np.fft.irfft2(np.fft.rfft2(a) * G, s=(ny, nx))
    return np.stack([np.fft.irfft2(np.fft.rfft2(a[..., c]) * G, s=(ny, nx)) for c in range(a.shape[2])], -1)


def _std(a):
    m, sd = float(a.mean()), float(a.std())
    return ((a - m) / max(sd, 1e-12)).astype(F32), m, sd


def coat():
    """The round-E coat as standardised stacks for the histogram-preserving hex blend: the macro tile
    (3.6 m: the colour's detail under 2 cm in log space, the macro relief, the detail strength) and
    the detail tile (0.6 m: relief, cavity)."""
    if not _COAT:
        mm = json.load(open(os.path.join(TEXDIR, "spraymacro_meta.json")))
        dm = json.load(open(os.path.join(TEXDIR, "spraydetail_meta.json")))
        lin = _img("spraymacro_basecolor.png", "RGB")
        lin = np.where(lin <= 0.04045, lin / 12.92, ((lin + 0.055) / 1.055) ** 2.4)
        ppm = lin.shape[0] / mm["tile_m"]
        hp = np.log(np.maximum(lin / np.maximum(_blur_tile(lin, 0.02 * ppm), 1e-4), 1e-3))
        lo, hi = mm["height_range_m"]
        hm = lo + (hi - lo) * _img("spraymacro_height.png", "I16")
        hd = _img("spraydetail_height.png", "I16") * dm["relief_m"]

        def slope(h, tile_m):
            px = tile_m / h.shape[1]
            return ((np.roll(h, -1, 1) - np.roll(h, 1, 1)) / (2 * px), (np.roll(h, -1, 0) - np.roll(h, 1, 0)) / (2 * px))
        sx, sy = slope(hm, mm["tile_m"])
        chans, stats = [], []
        for a in [hp[..., 0], hp[..., 1], hp[..., 2], hm, 1.5 * _img("spraymacro_mask.png", "RGB")[..., 0], sx, sy]:
            g, m, sd = _std(a)
            chans.append(g)
            stats.append((m, sd))
        dx_, dy_ = slope(hd, dm["tile_m"])
        dchans, dstats = [], []
        for a in [hd, _img("spraydetail_cavity.png", "L"), dx_, dy_]:
            g, m, sd = _std(a)
            dchans.append(g)
            dstats.append((m, sd))
        _COAT.update(macro=np.stack(chans, -1), mstats=stats, tile_m=mm["tile_m"],
                     detail=np.stack(dchans, -1), dstats=dstats, det_m=dm["tile_m"])
    return _COAT


_MIP = {}


def mip(name, stack, tile_m, ppm_out):
    """Box-filtered level of a coat stack for the output density (appearance: no re-standardising)."""
    f = 1
    ppm = stack.shape[1] / tile_m
    while ppm / (2 * f) >= ppm_out and stack.shape[0] // (2 * f) >= 64:
        f *= 2
    if f == 1:
        return stack
    k = (name, f)
    if k not in _MIP:
        ny, nx = (stack.shape[0] // f) * f, (stack.shape[1] // f) * f
        _MIP[k] = stack[:ny, :nx].reshape(ny // f, f, nx // f, f, -1).mean(axis=(1, 3)).astype(F32)
    return _MIP[k]


def coat_at(XX, YY, ppm, salt):
    """The coat at the fine grid: albedo detail (mean about 1), relief (m), cavity, receptivity
    (a standard normal field: high in the troughs, where dirt settles first)."""
    C = coat()
    M = wd.hex_multi(mip("macro", C["macro"], C["tile_m"], ppm), C["tile_m"], C["tile_m"], XX, YY, 1.2, salt,
                     vec=((5, 6),))
    Dt = wd.hex_multi(mip("detail", C["detail"], C["det_m"], ppm), C["det_m"], C["det_m"], XX, YY, 0.2, salt + 1,
                      vec=((2, 3),))
    ms, ds = C["mstats"], C["dstats"]
    hp = np.exp(np.stack([ms[c][0] + ms[c][1] * M[..., c] for c in range(3)], -1))
    hmac = ms[3][0] + ms[3][1] * M[..., 3]
    strength = np.clip(ms[4][0] + ms[4][1] * M[..., 4], 0, 2)
    hdet = ds[0][0] + ds[0][1] * Dt[..., 0]
    cav = np.clip((ds[1][0] + ds[1][1] * Dt[..., 1]) * strength, 0, 1)
    sk = np.clip(strength, 0.3, 1.5)
    rec = -(Dt[..., 0] * sk + 0.35 * M[..., 3]) / np.sqrt(sk ** 2 + 0.1225)
    # slopes of the relief (d/dx right, d/dy down the facade), blended as slopes
    gx = ms[5][0] + ms[5][1] * M[..., 5] + (ds[2][0] + ds[2][1] * Dt[..., 2]) * strength
    gy = ms[6][0] + ms[6][1] * M[..., 6] + (ds[3][0] + ds[3][1] * Dt[..., 3]) * strength
    return {"hp": hp.astype(F32), "h": (hmac + hdet * strength).astype(F32), "cav": cav.astype(F32), "rec": rec.astype(F32),
            "gx": gx.astype(F32), "gy": gy.astype(F32)}


# ---------------------------------------------------------------------------------------------
# upsampling from 50 px/m

def _axis(n_out, start50, ppm):
    """Coarse coordinates (50 px/m pixel centres) of the fine samples along one axis."""
    return start50 + (np.arange(n_out) + 0.5) * (P50 / ppm) - 0.5


def bspline_up(a, cy, cx):
    """Cubic B-spline sample of a coarse array a (h, w[, c]) at coarse coordinates cy (rows), cx (cols)."""
    def wts(c, n):
        i0 = np.floor(c).astype(np.int64)
        t = c - i0
        w = ((1 - t) ** 3 / 6, (3 * t ** 3 - 6 * t ** 2 + 4) / 6, (-3 * t ** 3 + 3 * t ** 2 + 3 * t + 1) / 6, t ** 3 / 6)
        return [np.clip(i0 + k, 0, n - 1) for k in (-1, 0, 1, 2)], w
    a = np.asarray(a, F32)
    iy, wy = wts(cy, a.shape[0])
    ix, wx = wts(cx, a.shape[1])
    tmp = sum(a[:, i] * (w[None, :, None] if a.ndim == 3 else w[None, :]) for i, w in zip(ix, wx))
    return sum(tmp[i] * (w[:, None, None] if a.ndim == 3 else w[:, None]) for i, w in zip(iy, wy)).astype(F32)


def bilinear_up(a, cy, cx):
    a = np.asarray(a, F32)
    y0 = np.clip(np.floor(cy).astype(np.int64), 0, a.shape[0] - 1)
    x0 = np.clip(np.floor(cx).astype(np.int64), 0, a.shape[1] - 1)
    y1 = np.clip(y0 + 1, 0, a.shape[0] - 1)
    x1 = np.clip(x0 + 1, 0, a.shape[1] - 1)
    fy = np.clip(cy - np.floor(cy), 0, 1).astype(F32)[:, None]
    fx = np.clip(cx - np.floor(cx), 0, 1).astype(F32)[None, :]
    if a.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    return ((a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx) * (1 - fy) + (a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx) * fy).astype(F32)


def nearest_up(a, cy, cx):
    iy = np.clip(np.round(cy).astype(np.int64), 0, a.shape[0] - 1)
    ix = np.clip(np.round(cx).astype(np.int64), 0, a.shape[1] - 1)
    return a[iy][:, ix]


def masked_up(a, m, cy, cx):
    """B-spline of a over the mask m only (normalised), so wall colours do not bleed into frames."""
    mf = m.astype(F32)
    num = bspline_up(a * (mf[..., None] if a.ndim == 3 else mf), cy, cx)
    den = bspline_up(mf, cy, cx)
    return num / np.maximum(den[..., None] if a.ndim == 3 else den, 1e-4)


def blur_coarse(a, sigma=1.0):
    """Small separable Gaussian on a coarse window: removes the 50 px/m grain a film carries for the
    coarse rules, which the fine detail replaces."""
    r = int(np.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    p = np.pad(np.asarray(a, F32), r, mode="edge")
    t = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    return sum(k[i] * t[i:i + a.shape[0]] for i in range(2 * r + 1)).astype(F32)


def local_max3(a, r=None):
    """The local opacity of a coarse alpha: its maximum over (2 r + 1)^2 coarse pixels, smoothed, so a
    layer's grain at 50 px/m does not turn into isolated dots at the fine grid."""
    r = PEAK_R if r is None else r
    p = np.pad(a, r, mode="edge")
    out = a.copy()
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out = np.maximum(out, p[dy:dy + a.shape[0], dx:dx + a.shape[1]])
    return np.maximum(blur_coarse(out, 1.0), a)


# ---------------------------------------------------------------------------------------------
# the composite

def load_steps(d, plane):
    z = np.load(os.path.join(d, "steps_%s.npz" % plane))
    out = []
    for i in range(int(z["n"])):
        rec = {"name": str(z["s%d_name" % i]), "op": str(z["s%d_op" % i])}
        for k in ("alpha", "colour", "shift", "cavity", "bar"):
            key = "s%d_%s" % (i, k)
            if key in z.files:
                rec[k] = z[key].astype(F32)
        out.append(rec)
    return out


class Region:
    """A window of a plane at a texel density: fine-grid coordinates and the coarse window around it."""

    def __init__(self, box, ppm, shape50):
        x0, y0, x1, y1 = box
        self.ppm = float(ppm)
        self.W = int(round((x1 - x0) / P50 * ppm))
        self.H = int(round((y1 - y0) / P50 * ppm))
        self.X = (x0 / P50 + (np.arange(self.W) + 0.5) / ppm).astype(np.float64)
        self.Y = (y0 / P50 + (np.arange(self.H) + 0.5) / ppm).astype(np.float64)
        m = 4
        self.cy0, self.cx0 = max(0, y0 - m), max(0, x0 - m)
        self.cy1, self.cx1 = min(shape50[0], y1 + m), min(shape50[1], x1 + m)
        self.cy = _axis(self.H, y0, ppm) - self.cy0       # coarse coordinates inside the window
        self.cx = _axis(self.W, x0, ppm) - self.cx0

    def win(self, a, half=False):
        if half:
            return a[self.cy0 // 2:(self.cy1 + 1) // 2, self.cx0 // 2:(self.cx1 + 1) // 2]
        return a[self.cy0:self.cy1, self.cx0:self.cx1]

    def half_coords(self):
        return (self.cy + self.cy0) / 2.0 - 0.25 - self.cy0 // 2, (self.cx + self.cx0) / 2.0 - 0.25 - self.cx0 // 2


def compose(d, plane, box, ppm, clean_only=False, layers=None, salt=7):
    """Albedo (linear RGB), height (m), cavity and lit sRGB of a window of a built plane."""
    z = np.load(os.path.join(d, plane + ".npz"))
    cls50 = z["cls"]
    R = Region(box, ppm, cls50.shape)
    XX, YY = np.meshgrid(R.X, R.Y)
    cap = load_capture(plane, box, ppm)
    if cap is not None and cap["cls"].shape == (R.H, R.W):
        cls = cap["cls"]
        steel = cap["steel"]
    else:
        cap = None
        cls = nearest_up(R.win(cls50), R.cy, R.cx)
        steel = nearest_up(R.win(z["steel"]), R.cy, R.cx) > 0 if "steel" in z.files else cls == 7
    wall50 = np.isin(R.win(cls50), (1, 2))
    wall = np.isin(cls, (1, 2))
    base50 = R.win(z["base"]).astype(F32)
    # clean albedo: wall colours spline-interpolated over the wall only, other classes nearest,
    # times the coat's detail under 2 cm (hex-tiled so the 3.6 m tile does not repeat)
    A = cap["albedo"] if cap is not None else nearest_up(base50, R.cy, R.cx).astype(F32)
    Aw = masked_up(base50, wall50, R.cy, R.cx)
    co = coat_at(XX, YY, ppm, salt)
    A = np.where(wall[..., None], Aw * co["hp"], A)
    h, cav = co["h"], co["cav"]
    h_extra = np.zeros(cls.shape, F32)          # joints and breaks: smooth, their slopes from finite differences
    # joints: 20 mm rounded grooves 8 mm deep, centred on the joint pixel's centre line
    jj = np.zeros(cls.shape, bool)
    if "joint" in z.files:
        jn = nearest_up(R.win(z["joint"]), R.cy, R.cx)
        dv = np.abs(R.cx - np.round(R.cx))[None, :] / P50 * np.ones((R.H, 1))
        dh = np.abs(R.cy - np.round(R.cy))[:, None] / P50 * np.ones((1, R.W))
        dj = np.where((jn & 2) > 0, dv, 1.0)
        dj = np.minimum(dj, np.where((jn & 1) > 0, dh, 1.0))
        prof = np.clip(1.0 - (dj / 0.0105) ** 2, 0, 1)
        jj = (prof > 0) & wall
        h = np.where(wall, h - 0.008 * prof, h)
        h_extra = h_extra - np.where(wall, 0.008 * prof, 0.0)
        cav = np.where(wall, np.maximum(cav, 0.75 * prof), cav)
    h = np.where(wall, h, 0.0)
    if "dmg_h" in z.files:
        dh_ = bspline_up(np.nan_to_num(R.win(z["dmg_h"]).astype(F32)), R.cy, R.cx)
        h = h - np.where(wall, dh_, 0.0)
        h_extra = h_extra - np.where(wall, dh_, 0.0)
    clean = A.copy()
    if not clean_only:
        st50 = R.win(z["steel"]) > 0 if "steel" in z.files else R.win(cls50) == 7
        A = replay(A, load_steps(d, plane), R, XX, YY, wall, cls, salt, layers=layers, rec=co["rec"],
                   masks={"wall50": wall50, "steel50": st50, "steel": steel})
    gx = np.where(wall, co["gx"], 0.0)
    gy = np.where(wall, co["gy"], 0.0)
    ey, ex = np.gradient(h_extra, 1.0 / ppm)
    return {"albedo": A, "clean": clean, "height": h.astype(F32), "cav": cav.astype(F32), "cls": cls, "joint": jj,
            "region": R, "gx": (gx + ex).astype(F32), "gy": (gy + ey).astype(F32),
            "Ncap": cap["N"] if cap is not None else None}


def replay(A, steps, R, XX, YY, wall, cls, salt, layers=None, rec=None, masks=None):
    """The generator's composite, step by step, at the fine grid with each layer refined."""
    lum = np.array([0.2126, 0.7152, 0.0722], F32)
    hy, hx = R.half_coords()
    for k, s in enumerate(steps):
        name, op = s["name"], s["op"]
        if layers is not None and name not in layers:
            continue
        a50 = R.win(s["alpha"]) if "alpha" in s else None
        if op == "fade":
            f = bspline_up(a50, R.cy, R.cx)[..., None]
            grey = (A @ lum)[..., None]
            A = (A + (grey - A) * 0.18 * f) * (1.0 + 0.035 * f)
            continue
        if op == "shift":
            m = nearest_up(a50, R.cy, R.cx)
            sh = s["shift"]
            sh = nearest_up(R.win(sh), R.cy, R.cx) if np.ndim(sh) == 2 else float(sh)
            A = A * (1.0 + sh * m)[..., None]
            continue
        col = s.get("colour")
        if col is not None and col.ndim == 3:
            col = bspline_up(R.win(col, half=True), hy, hx)
        elif col is not None:
            col = np.broadcast_to(col.astype(F32), A.shape)
        mode, tname, cell, wk, cvar, rshare = REFINE.get(name, ("smooth", None, 0, 0, 0, 0))
        src = blur_coarse(a50) if mode == "film" else a50
        if masks is not None:
            a_up = np.where(wall, masked_up(src, masks["wall50"], R.cy, R.cx), 0.0)
            pk50 = local_max3(np.where(masks["wall50"], a50, 0.0))
            peak = np.where(wall, masked_up(pk50, masks["wall50"], R.cy, R.cx), 1.0)
            if name == "rust":                           # rust on the steel, its runs on the walls
                a_st = masked_up(a50, masks["steel50"], R.cy, R.cx)
                a_up = np.where(masks["steel"], a_st, a_up)
                peak = np.where(masks["steel"], masked_up(local_max3(np.where(masks["steel50"], a50, 0.0)), masks["steel50"],
                                                          R.cy, R.cx), peak)
            a_up = np.clip(a_up, 0, 1)
        else:
            a_up = np.clip(bspline_up(src, R.cy, R.cx), 0, 1)
            peak = bspline_up(local_max3(a50), R.cy, R.cx)
        g = None
        if mode in ("film", "cover", "band"):
            if mode == "band":
                g = wd.band_g(tile(tname), XX, YY, cell, salt + 11 * k, ppm_out=R.ppm)
            else:
                g = wd.hex_g(tile(tname), XX, YY, cell, salt + 11 * k, ppm_out=R.ppm)
            if rec is not None and rshare > 0:          # the coat's troughs take it first
                g = np.where(wall, (rshare * rec + (1 - rshare) * g) / np.sqrt(rshare ** 2 + (1 - rshare) ** 2), g)
        if mode == "film":
            if FILM_SPLIT_M > 0:                         # round I (T3): grain below the split keeps the full weight; the
                rr_ = max(1, int(round(FILM_SPLIT_M * R.ppm / 2)))   # blotches above it, which the 50 px/m masks already
                lo_ = _box_blur(g, rr_)                  # draw, stay weak so the close-up keeps the measured amounts
                hi_ = g - lo_
                gs_ = (FILM_WK[0] * hi_ / max(float(hi_.std()), 1e-6) + FILM_WK[1] * lo_ / max(float(lo_.std()), 1e-6))
                gs_ = gs_ * (1.0 - FILM_DENSE * np.clip(a_up, 0.0, 1.0))   # a thick deposit fills the texture: less modulation
                a = wd.refine_film(a_up, gs_.astype(F32), 1.0)
            else:
                a = wd.refine_film(a_up, g, wk)
            cmod = 1.0 + cvar * np.clip(g, -2.5, 2.5) / 2.5
        elif mode in ("cover", "band"):
            peak = np.maximum(np.clip(peak, 1e-4, 1), a_up)
            u = wd.norm_cdf(g).astype(F32)
            a = wd.refine_cover(a_up, peak, u, wk)
            cmod = 1.0 + cvar * (u - 0.5) * 2.0
        else:
            a = a_up
            cmod = 1.0
        if op == "damage":
            A = A + (col - A) * a[..., None]
            if "cavity" in s:
                cv = bspline_up(R.win(s["cavity"]), R.cy, R.cx)
                A = A + (np.array([0.05, 0.046, 0.040], F32) - A) * np.clip(cv, 0, 1)[..., None]
            if "bar" in s:
                b = np.clip(bspline_up(R.win(s["bar"]), R.cy, R.cx), 0, 1)
                A = A + (np.array([0.20, 0.09, 0.04], F32) - A) * b[..., None]
            continue
        c = col * (cmod[..., None] if np.ndim(cmod) == 2 else cmod)
        An = A + (c - A) * a[..., None]
        if op == "lerp_dark":
            Yn, Yo = An @ lum, A @ lum
            An = np.where((Yn > Yo)[..., None], An * (Yo / np.maximum(Yn, 1e-6))[..., None], An)
        A = An.astype(F32)
    return A


# ---------------------------------------------------------------------------------------------
# lighting (the 50 px/m previews' sun and sky)

def _box_blur(a, r):
    """Separable box blur of radius r px (twice: close to a Gaussian)."""
    for _ in range(2):
        for ax in (0, 1):
            c = np.cumsum(np.pad(a, [(r + 1, r) if i == ax else (0, 0) for i in range(2)], mode="edge"), axis=ax)
            a = (np.take(c, range(2 * r + 1, c.shape[ax]), axis=ax) - np.take(c, range(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
    return a


def to_srgb8(lin):
    a = np.clip(lin, 0, 1)
    s = np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def lit(res, Ngeom=None, view="S"):
    h, cav, A = res["height"], res["cav"], res["albedo"]
    R = res["region"]
    if "gx" in res:                                  # blended slopes (rows run down: y up is -row)
        gx, gy = res["gx"], res["gy"]
    else:
        gy, gx = np.gradient(h, 1.0 / R.ppm)
    nx, ny, nzz = -gx, gy, np.ones_like(h)
    L = np.sqrt(nx * nx + ny * ny + nzz * nzz)
    sun = np.clip((nx * LIGHT[0] + ny * LIGHT[1] + nzz * LIGHT[2]) / L, 0, 1)
    if res.get("Ncap") is not None:                  # the crop capture: the geometry at this density
        Nc = res["Ncap"]
        Nb = np.stack([_box_blur(Nc[..., c], max(1, int(0.006 * R.ppm))) for c in range(3)], -1)
        Nb = Nb / np.maximum(np.linalg.norm(Nb, axis=-1, keepdims=True), 1e-6)
        face = np.clip(Nb[..., 2] if view == "S" else -Nb[..., 2] if view == "N" else -Nb[..., 0], 0, 1)
        up = np.clip(Nb[..., 1], -1, 1)
    elif Ngeom is not None:
        # the geometry's facing only: the capture's normals carry the coat's normal map at 50 px/m,
        # which the fine relief replaces, so they are smoothed first (walls face +z on the south
        # front, -z on the north, -x on the west gable)
        Nw = np.stack([blur_coarse(R.win(Ngeom)[..., c], 1.5) for c in range(3)], -1)
        Ng = bspline_up(Nw, R.cy, R.cx)
        Ng = Ng / np.maximum(np.linalg.norm(Ng, axis=-1, keepdims=True), 1e-6)
        face = np.clip(Ng[..., 2] if view == "S" else -Ng[..., 2] if view == "N" else -Ng[..., 0], 0, 1)
        up = np.clip(Ng[..., 1], -1, 1)
    else:
        face, up = 1.0, 0.0
    shade = (0.45 + 0.15 * up) * (1.0 - 0.4 * cav) + 0.75 * sun * face
    out = A * shade[..., None]
    glass = res["cls"] == 6
    if glass.any():
        yy = np.linspace(0, 1, glass.shape[0], dtype=F32)[:, None]
        refl = np.stack([0.05 + 0.03 * (1 - yy), 0.06 + 0.035 * (1 - yy), 0.075 + 0.04 * (1 - yy)], -1) * np.ones((1, glass.shape[1], 1), F32)
        out = np.where(glass[..., None], refl, out)
    return to_srgb8(out)


def check_mean(res, d, plane):
    """How far the fine albedo, box-filtered back to 50 px/m, sits from the build's own albedo
    (luminance ratio over walls): the refinement must keep the macro amounts the gate measured."""
    R = res["region"]
    z = np.load(os.path.join(d, plane + ".npz"))
    f = int(round(R.ppm / P50))
    A = res["albedo"]
    H, W = (A.shape[0] // f) * f, (A.shape[1] // f) * f
    lum = np.array([0.2126, 0.7152, 0.0722], F32)
    Yf = (A[:H, :W] @ lum).reshape(H // f, f, W // f, f).mean(axis=(1, 3))
    x0, y0 = int(round(R.X[0] * P50 - 0.5)), int(round(R.Y[0] * P50 - 0.5))
    rgb = z["rgb"][y0:y0 + H // f, x0:x0 + W // f].astype(F32)
    Yc = rgb @ lum
    wall = np.isin(z["cls"][y0:y0 + H // f, x0:x0 + W // f], (1, 2))
    r = (Yf / np.maximum(Yc, 1e-4))[wall]
    return {"mean_ratio": float(r.mean()), "p05": float(np.percentile(r, 5)), "p95": float(np.percentile(r, 95))}


def main():
    d, plane, box, ppm, out = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
    box = tuple(int(v) for v in box.split(","))
    res = compose(d, plane, box, ppm, clean_only="--clean" in sys.argv)
    root = os.environ.get("WX_DATA", os.path.dirname(os.path.dirname(os.path.abspath(d))))
    Ng = None
    cp = os.path.join(root, "real", "clean_%s.npz" % plane.split("_")[0])
    if os.path.exists(cp):
        Ng = np.load(cp)["N"]
    Image.fromarray(lit(res, Ng, plane.split("_")[0])).save(out, quality=92)
    print(json.dumps(check_mean(res, d, plane)))


if __name__ == "__main__":
    main()
