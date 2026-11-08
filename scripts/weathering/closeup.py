"""closeup.py - 1 m x 1 m close-ups of a weathered config at 1 mm per pixel, built the way the engine
shader builds the wall: the facade-space albedo and weathering (50 px/m, the baked atlas) times the
round-E coat set sampled at its own resolution (spraymacro 3.6 m tile, spraydetail 0.6 m tile).

At this range the material decides where the dirt sits (rule J2): each spot's coverage is decided
against the coat's relief (height-lerp, as the engine shader does it), so troughs take dirt first and
bump tops last, edges turn granular, and the amount over 1 cm and up stays the atlas' own. Algae
starts deeper in the troughs. Joints are 20 mm grooves 10 mm deep.

python -I wx/closeup.py <config_dir>      writes closeup_<plane>_<spot>.npz/.jpg and closeups.json
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_measure as wm  # noqa: E402
from weather_fields import TEXDIR  # noqa: E402

PPM = 1000.0                 # close-up resolution, px per metre
SIZE = 1.0                   # metres
TROUGH = 0.30                # share of the darkening that follows the cavity map
BIO_TROUGH = 0.6             # algae: more of it starts in the troughs
HL_CONTRAST = 1.6            # height-lerp contrast: how sharply coverage follows the relief
LIGHT = np.array([-0.35, 0.55, 0.76]) / np.linalg.norm([-0.35, 0.55, 0.76])
_T = {}


def _img(name, mode=None):
    k = (name, mode)
    if k not in _T:
        im = Image.open(os.path.join(TEXDIR, name))
        if mode == "I16":
            a = np.asarray(im, np.float64) / 65535.0
        else:
            a = np.asarray(im.convert(mode) if mode else im, np.float64) / 255.0
        _T[k] = a
    return _T[k]


def _meta(name):
    return json.load(open(os.path.join(TEXDIR, name + "_meta.json")))


def sample(tile, tile_m, X, Y):
    """Bilinear, wrapped sample of a square tile (tile_m metres) at facade metres X (right), Y (down)."""
    n = tile.shape[0]
    u = (X / tile_m * n) % n
    v = (Y / tile_m * n) % n
    x0 = np.floor(u).astype(int)
    y0 = np.floor(v).astype(int)
    fx, fy = u - x0, v - y0
    x1, y1 = (x0 + 1) % n, (y0 + 1) % n
    if tile.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    return ((tile[y0, x0] * (1 - fx) + tile[y0, x1] * fx) * (1 - fy) +
            (tile[y1, x0] * (1 - fx) + tile[y1, x1] * fx) * fy)


def up(a, x0, y0, n50, n):
    """Bilinear upsample of a facade-space window (50 px/m) to the close-up grid."""
    H, W = a.shape[:2]
    g = (np.arange(n) + 0.5) / n * n50 - 0.5
    ys = np.clip(y0 + g, 0, H - 1)
    xs = np.clip(x0 + g, 0, W - 1)
    yi, xi = np.floor(ys).astype(int), np.floor(xs).astype(int)
    yj, xj = np.minimum(yi + 1, H - 1), np.minimum(xi + 1, W - 1)
    fy, fx = (ys - yi)[:, None], (xs - xi)[None, :]
    if a.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    A = a.astype(np.float64)
    return ((A[yi][:, xi] * (1 - fx) + A[yi][:, xj] * fx) * (1 - fy) +
            (A[yj][:, xi] * (1 - fx) + A[yj][:, xj] * fx) * fy)


def coat_set(X, Y):
    """The coat at the close-up grid: albedo detail (mean 1), height (m), cavity (0-1)."""
    mm = _meta("spraymacro")
    dm = _meta("spraydetail")
    bc = wm.srgb_to_linear(_img("spraymacro_basecolor.png", "RGB") * 255.0)
    bc = bc / bc.reshape(-1, 3).mean(0)
    alb = sample(bc, mm["tile_m"], X, Y)
    lo, hi = mm["height_range_m"]
    hmac = lo + (hi - lo) * sample(_img("spraymacro_height.png", "I16"), mm["tile_m"], X, Y)
    coat = sample(_img("spraymacro_mask.png", "RGB")[..., 0], mm["tile_m"], X, Y)
    hdet = sample(_img("spraydetail_height.png", "I16"), dm["tile_m"], X, Y) * dm["relief_m"]
    cav = sample(_img("spraydetail_cavity.png", "L"), dm["tile_m"], X, Y)
    s = 1.5 * coat                                   # detail strength from the coat mask (1.0 = 1.5x)
    return alb, hmac + hdet * s, np.clip(cav * s, 0, 1)


def albedo_tile50(ppm):
    """The coat's base colour as the facade bases carry it (box-filtered to 50 px/m, mean 1)."""
    im = Image.open(os.path.join(TEXDIR, "spraymacro_basecolor.png")).convert("RGB")
    n = int(round(3.6 * ppm))
    a = wm.srgb_to_linear(np.asarray(im.resize((n, n), Image.BOX), np.float64))
    return a / a.reshape(-1, 3).mean(0)


def shade(h, cav):
    gy, gx = np.gradient(h, 1.0 / PPM)
    # facade rows run down: y up in the wall is -row
    nx, ny = -gx, gy
    nz = np.ones_like(h)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    sun = np.clip((nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / L, 0, 1)
    ao = 1.0 - 0.4 * cav
    return 0.45 * ao + 0.75 * sun


def to_srgb8(lin):
    a = np.clip(lin, 0, 1)
    s = np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def spots(z, pm):
    """Fixed places per plane, chosen from the geometry: a joint on a solid wall (upper third),
    the open wall between joints, and the foot of the wall. (name, x0, y0) in facade px."""
    ppm = pm["ppm"]
    n = int(round(SIZE * ppm))
    cls = z["cls"]
    paint = np.isin(cls, (1, 2))
    joint = z["joint"] if "joint" in z.files else np.zeros(cls.shape, np.uint8)
    H, W = cls.shape
    ii = np.pad(paint.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    jv = np.pad(((joint & 2) > 0).astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    ja = np.pad((joint > 0).astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def box(I, x0, y0):
        return I[y0 + n, x0 + n] - I[y0, x0 + n] - I[y0 + n, x0] + I[y0, x0]

    def inside(x0, y0):
        return 0 <= x0 and 0 <= y0 and x0 + n <= W and y0 + n <= H

    def solid(x0, y0):
        return inside(x0, y0) and box(ii, x0, y0) >= 0.98 * n * n

    out = []
    hj = (joint & 1) > 0
    rows = np.flatnonzero(hj.any(axis=1)).tolist()
    if rows:
        top, bot = rows[0], rows[-1]
        upper = [r for r in rows if r <= top + (bot - top) / 3.0]
        jr = upper[len(upper) // 2]
        c = [x - n // 2 for x in np.flatnonzero(hj[jr])[::5]
             if solid(x - n // 2, jr - n // 3) and box(jv, x - n // 2, jr - n // 3) == 0]
        if c:
            out.append(("joint", int(c[len(c) // 2]), int(jr - n // 3)))
        mid = rows[len(rows) // 2]
        nxt = [r for r in rows if r > mid + 0.5 * ppm]
        if nxt:
            y0 = (mid + nxt[0]) // 2 - n // 2
            c = [x for x in np.flatnonzero(paint[min(H - 1, y0 + n // 2)])[::5]
                 if solid(x, y0) and box(ja, x, y0) == 0]
            if c:
                out.append(("wall", int(c[len(c) // 2]), int(y0)))
    g = pm.get("ground_row")
    if g is not None:
        for y0 in range(int(g) - n, int(g) - 3 * n, -max(1, n // 5)):
            if y0 < 0:
                break
            c = [x for x in np.flatnonzero(paint[y0 + n - 1])[::5] if solid(x, y0)]
            if c:
                out.append(("foot", int(c[len(c) // 2]), int(y0)))
                break
    return out


def make(d, name, z, pm, spot):
    tag, x0, y0 = spot
    ppm = pm["ppm"]
    n50 = int(round(SIZE * ppm))
    n = int(round(SIZE * PPM))
    X = (x0 + (np.arange(n) + 0.5) / PPM * ppm) / ppm
    Y = (y0 + (np.arange(n) + 0.5) / PPM * ppm) / ppm
    XX, YY = np.meshgrid(X, Y)
    alb, h, cav = coat_set(XX, YY)
    t50 = albedo_tile50(ppm)
    yy, xx = np.arange(y0, y0 + n50), np.arange(x0, x0 + n50)
    tt = t50[(yy % t50.shape[0])[:, None], (xx % t50.shape[1])[None, :]]
    base50 = z["base"][y0:y0 + n50, x0:x0 + n50].astype(np.float64)
    flat50 = base50 / np.maximum(tt, 1e-4)                 # element colour x clouding x joint tone
    full = np.pad(flat50, ((1, 1), (1, 1), (0, 0)), mode="edge")
    flat = up(full, 1, 1, n50, n)
    clean = flat * alb
    # joints: grooves cut into the height, full cavity inside
    jm = z["joint"][y0:y0 + n50, x0:x0 + n50] if "joint" in z.files else np.zeros((n50, n50), np.uint8)
    h_coat = h.copy()                                         # the coat's own relief: where dirt settles
    if jm.any():
        jj = up(np.pad((jm > 0).astype(np.float64), 1, mode="edge"), 1, 1, n50, n) > 0.5
        h = np.where(jj, h - 0.010, h)
        h = wm.gauss(h, 1.5)
        cav = np.where(jj, 0.5, cav)                       # occlusion only: its dirt is in the atlas
    else:
        jj = np.zeros((n, n), bool)
    sh = shade(h, cav)
    # weathering: the atlas ratio (weathered / clean, per channel) shared by the coat's relief
    rgb50 = z["rgb"][y0:y0 + n50, x0:x0 + n50].astype(np.float64)
    ratio50 = rgb50 / np.maximum(base50, 1e-4)
    ratio = up(np.pad(ratio50, ((1, 1), (1, 1), (0, 0)), mode="edge"), 1, 1, n50, n)
    dark = np.clip(1.0 - ratio, -0.5, 0.98)
    d1 = dark.mean(axis=2)
    # receptivity of the coat: troughs take dirt first, bump tops last (1 = deepest)
    hd = h_coat - wm.gauss(h_coat, 8.0)
    lo_, hi_ = np.percentile(hd[~jj] if (~jj).any() else hd, (5, 95))
    rec = np.clip(1.0 - (hd - lo_) / max(hi_ - lo_, 1e-9), 0, 1)
    # height-lerp (the engine's HeightLerp): the atlas gives each spot a local peak and a soft
    # coverage; at 1 mm the coverage is decided against the coat's relief, so edges turn granular
    pos = np.clip(d1, 0, None)
    r = 15                                                    # 15 mm: the atlas' soft edge
    wall = ~jj                                                # the joint's own dirt is not the wall's peak
    peak = wm._sliding_max(wm._sliding_max(np.where(wall, pos, 0.0), r, 0), r, 1)
    alpha = np.where(wall, pos / np.maximum(peak, 1e-4), 1.0)
    a_close = np.clip((alpha - (1.0 - rec)) * HL_CONTRAST + 0.5, 0, 1)
    bio50 = z["L_bio"][y0:y0 + n50, x0:x0 + n50] if "L_bio" in z.files else None
    if bio50 is not None and np.nanmax(bio50) > 0:          # algae: more of it starts in the troughs
        b = up(np.pad(np.nan_to_num(bio50.astype(np.float64)), 1, mode="edge"), 1, 1, n50, n)
        share = np.clip(b / np.maximum(pos, 1e-4), 0, 1)
        a_close = a_close * (1.0 - share) + share * np.clip((alpha - (1.0 - rec) * 0.6) * HL_CONTRAST + 0.5, 0, 1)
    cm = max(float(cav[~jj].mean()) if (~jj).any() else float(cav.mean()), 1e-4)
    dc = peak * a_close * ((1.0 - TROUGH) + TROUGH * cav / cm)     # inside: troughs hold more of it
    s_ = 10.0                                                 # keep the atlas amount at 1 cm and up
    g = wm.masked_gauss(pos, wall, s_) / np.maximum(wm.masked_gauss(dc, wall, s_), 1e-5)
    g = np.nan_to_num(g, nan=1.0)
    dc = np.clip(dc * np.clip(g, 0, 4), 0, 0.98)
    dc = np.where(jj, pos, dc)                                # the joint's dirt is in the atlas already
    gain = np.where(pos > 1e-4, dc / np.maximum(pos, 1e-4), 1.0)
    darkc = np.where((d1 > 0)[..., None], dark * gain[..., None], dark)
    weathered = clean * (1.0 - np.clip(darkc, -0.5, 0.98))
    soil50 = z["L_soiling"][y0:y0 + n50, x0:x0 + n50] if "L_soiling" in z.files else None
    soil = up(np.pad(np.nan_to_num(soil50.astype(np.float64)), 1, mode="edge"), 1, 1, n50, n) * gain if soil50 is not None else None
    lit_c = clean * sh[..., None]
    lit_w = weathered * sh[..., None]
    base_name = "closeup_%s_%s" % (name, tag)
    arrs = {"Yc_alb": wm.luminance(clean).astype(np.float32), "Yc_lit": wm.luminance(lit_c).astype(np.float32),
            "Yw_lit": wm.luminance(lit_w).astype(np.float32), "height": h.astype(np.float32),
            "cav": cav.astype(np.float32), "joint": jj}
    if soil is not None:
        arrs["soil"] = soil.astype(np.float32)
    np.savez_compressed(os.path.join(d, base_name + ".npz"), **arrs)
    Image.fromarray(to_srgb8(lit_c)).save(os.path.join(d, base_name + "_clean.jpg"), quality=90)
    Image.fromarray(to_srgb8(lit_w)).save(os.path.join(d, base_name + ".jpg"), quality=90)
    return {"plane": name, "spot": tag, "x0": x0, "y0": y0, "size_m": SIZE, "ppm": PPM, "file": base_name}


def make_all(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    out = []
    for name, pm in meta["planes"].items():
        z = np.load(os.path.join(d, name + ".npz"))
        if "base" not in z.files:
            continue
        for sp in spots(z, pm):
            out.append(make(d, name, z, pm, sp))
    json.dump(out, open(os.path.join(d, "closeups.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    for r in make_all(sys.argv[1]):
        print(r)
