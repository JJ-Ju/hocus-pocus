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
import wx_concrete as wc  # noqa: E402
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
            "N": z["N"].astype(F32), "depth": z["depth"].astype(np.float64) if "depth" in z.files else None}

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
    "rust_run": ("band", "streak", 0.12, 0.40, 0.10, 0.0),   # round J: runs down the bars, as bands
    "rust_bare": ("cover", "chip", 0.10, 0.10, 0.04, 0.0),   # round J: bare steel, chip shapes
    "rust": ("cover", "rust", 0.20, 0.25, 0.18, 0.0),
    "cracks": ("cover", "crack", 0.20, 0.35, 0.0, 0.0),
    "efflorescence": ("cover", "effl", 0.25, 0.30, 0.06, 0.3),
    "wear": ("cover", "chip", 0.20, 0.12, 0.05, 0.0),
    "peeling": ("cover", "flake2", 0.20, 0.02, 0.03, 0.0),  # round J: paint fragments (J19: cell flakes, edge 0.02)
    "damage": ("cover", "chip", 0.20, 0.10, 0.0, 0.0),
}
PEAK_R = 2                  # the local opacity a layer's spots take: max over (2 r + 1) coarse px, smoothed
BARE_RING_MM = 2.5          # round J3: bare steel as a thin ring round the fine rust patches (and chips elsewhere)
RUST_ANAT = True            # round J4: rust anatomy at the fine grid (research surface-detail-techniques.md 6):
                            # a fresh bright margin inside the edge, exposed steel on part of the perimeter, a
                            # yellowed blister halo outside it
ANAT_METAL_MM = (0.5, 3.0)  # exposed steel band width
ANAT_METAL_SHARE = 0.5      # share of the perimeter with exposed steel (research: 30-70 %)
ANAT_MARGIN_MM = (1.0, 4.0) # fresh rust margin width
ANAT_HALO_MM = 6.0          # blister halo reach
C_FRESH_MARGIN = np.array([0.30, 0.135, 0.045], F32)   # L* about 53, hue about 60 deg, C* about 40
C_FLASH = np.array([0.24, 0.20, 0.17], F32)            # bare steel with a haze of flash rust (L* about 52)
import rust_flow as _rf                                  # noqa: E402
C_TARN = _rf.lab_to_lin((43.0, 1.5, 4.5)).astype(F32)       # round K: tarnished steel (L* 43)
C_DARK_K = _rf.lab_to_lin(_rf.LAB_DARK).astype(F32)       # round K: old dark scale (rust_flow LAB_DARK)


def nz_smooth(a, b, x):
    t = np.clip((x - a) / max(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)
C_TARN_DARK = _rf.lab_to_lin((34.0, 0.5, 0.5)).astype(F32)  # darker blue-grey scale
C_TARN_BROWN = _rf.lab_to_lin((46.0, 5.0, 11.0)).astype(F32)   # a brown flash-rust haze
RUN_PEAK_KEEP = 0.985
# round K: runs drawn in each bar's own coordinates (across 0-1, along), so a run reads as a stripe down the bar
# (the user, round J: "There's still no rust going DOWN the vertical slats"). The 50 px/m layer gives the run's
# coverage (alpha) and opacity (peak): the stripe is coverage / opacity of the bar wide, at that opacity.
RUN_MEMBER = True
RUN_BAR_MAX_M = 0.06        # a row run of steel at most this wide is a bar (rails, panels: wider)
RUN_WOB = (0.45, 0.13)      # the stripe centre's wobble wavelengths along the bar (m): gravity keeps runs straight
RUN_WOB_K = 0.25            # and its amplitude, x the free room either side
RUN_FIB = 0.35              # fibres: the opacity x (1 + this x the streak detail)
RUN_EDGE_PX = 1.0           # the stripe's soft edge (px)
RUN_RAG_MM = 1.2            # its edge ragged by this much (mm, the streak detail)
BARE_OPAQUE = True          # round K: exposed steel is opaque; its amount is coverage
STEEL_DETAIL_K = 3.0        # K: rust detail on steel at a third of the wall's scale (a 16 mm bar's front was a straight cut)
DCORE = (0.35, 0.80, 0.85)  # K: dark old scale inside a rust patch beyond its fresh margin: weight up to the last value,
DCORE_CELL = 0.04           # from rust age (the 50 px/m 'age') the first to the second, in blotches of this scale (m)
RUN_TIDE = (1.5, 0.22)      # K: a run's edge darker where the film dries (px, darkening)
# round K: exposed steel tarnished (the user: "a little darker, tarnished/worn"): a dull warm grey, darker
# blue-grey scale in places, a brown flash-rust haze in others
TARN = True
TARN_OPACITY = 1.0          # K9: the coat is gone where metal shows (0.9 left 10 % of the white paint: L* 48.6, not 43)
# round K: patterns tied to surfaces and grooves (the user, round J). Detail offsets per surface colour (the build's 'surf':
# depth steps of 3 cm or more), so no pattern runs on from the balcony front to the wall behind it; at the panel joints
# (20 mm grooves) the paint failure's flakes are offset per panel (they stop at the groove), take the lips first and the
# floor last, the face under a horizontal groove more (water runs off the lower lip); chips along the lips, a crack and
# dirt in the floor (research member-rust-and-geometry-aware-wear.md: lips 3-8x the open face's chips, the floor
# 0.3-0.6x, a crack along 30-60 % of the joint at Worn-Derelict, 5-15 L* darker floor).
SURF_FINE = True
SURF_OFF = (41.7, 23.3)     # m: the detail's offset per surface colour (x, y) x the colour
EXTRA = {}                  # (plane, key) -> an array a build lacks (the test loops: 'surf' for a round-J build)
JOINT_HALF_M = 0.0105       # the groove's half-width (compose's profile)
LIP_M = 0.004               # the lip: the face within this of the groove's edge
GROOVE_BIAS = (1.6, 1.2, 0.8)   # the paint failure's detail: + lips, - floor, + the face under a horizontal groove (std)
UNDER_M = 0.025             # that face: this far below the groove
LIP_CHIP = (0.05, 0.35, 4.0)   # K9: (0.02, 0.25, 4.0) chipped 2 % of Typical's lips, under N6's 4 %;   # chips on the lips: the arris's share chipped, a0 + a1 x wear + a2 x the flaked share around
FLOOR_CRACK = (3.0, 12.0, 0.85)  # the floor crack: years since repaint from-to, its share of the joint's length at most
FLOOR_DIRT = 0.30           # the floor's albedo x (1 - this x the local soiling)
PANEL_LAYERS = ("peeling", "wear")
GROOVE_ZONES = True
PITS_ON = True              # round J: the concrete's larger voids through the paint (wx_concrete 'pits'; J15: on)
PEEL_EDGE_MM = 1.5          # round J: the paint's edge round a flake: a shadow line inside, a lifted lip outside
PEEL_OPAQUE = True          # J19: flakes revealed at full opacity, their coverage the mask's alpha
PEEL_PURE = True            # J23: older coat or concrete per pixel, each its own colour times the local dirt
PEEL_DITHER = 0.6           # J23: the type boundary dithered by the flake cell's value (deepest cells: concrete)
PEEL_FILM_M = 0.0012        # the film's thickness: the flake sits this far below the paint (relief)
CHECK_DARK = 0.45           # the checked film's crack lines (dirt in them), times the halo
PEEL_GRIME = 0.14           # J13: mottling of the dirt on exposed concrete (the grime tile, 0.3 m cells)       # round J2: a rust run's peak opacity kept per 2 cm down the bar (half at about 1 m)


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
    if name == "flake":                                  # round J: paint lost in fragments about 1 cm across,
        _, cid = wd.worley(1024, 1024, 96, 96, "flake_cells")   # gathered into flakes by the larger field
        hv = np.clip(wd.hash01(cid // 96, cid % 96, 0x5A17), 1e-4, 1 - 1e-4)
        f = (0.55 * wd.norm_ppf(hv) + 0.75 * S(1024, 1024, 30, 30, 3.0, "flake_big")
             + 0.25 * S(1024, 1024, 2, 2, 2.0, "flake_edge"))
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "flake2":                                 # J19: flakes about 1 cm, cell-wise, paint bridges at the
        _, cid = wd.worley(1024, 1024, 96, 96, "flake_cells")   # borders until the area is nearly all flaked
        hv = np.clip(wd.hash01(cid // 96, cid % 96, 0x5A17), 1e-4, 1 - 1e-4)
        edge = ((cid != np.roll(cid, 1, 0)) | (cid != np.roll(cid, 1, 1)) | (cid != np.roll(cid, -1, 0))
                | (cid != np.roll(cid, -1, 1))).astype(F32)
        hb = wd.hash01(cid // 96, cid % 96, 0x0B0D)                 # some borders hold longer than others
        f = (0.85 * wd.norm_ppf(hv) + 0.40 * S(1024, 1024, 30, 30, 3.0, "flake_big")
             + 0.15 * S(1024, 1024, 2, 2, 2.0, "flake_edge") - (0.6 + 1.2 * hb) * edge)
        return wd.Tile(name, f, 1.024, 1.024)
    if name == "check":                                  # round J: the checked film, cells about 2.5 cm
        _, cid = wd.worley(1024, 1024, 40, 40, "check_cells")
        edge = (cid != np.roll(cid, 1, 0)) | (cid != np.roll(cid, 1, 1))
        f = edge.astype(F32) + 0.05 * S(1024, 1024, 1, 1, 2.0, "check_n")
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
        for k in ("alpha", "colour", "shift", "cavity", "bar", "halo", "conc", "peak", "age", "sheen"):
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
    sf50 = z["surf"] if "surf" in z.files else EXTRA.get((plane, "surf"))
    surf_f = None
    if SURF_FINE and sf50 is not None and cap is not None and cap.get("depth") is not None and "dep" in z.files:
        surf_f = fine_surfaces(R, R.win(np.asarray(sf50)), R.win(z["dep"]), cap["depth"])
        XX = XX + SURF_OFF[0] * np.maximum(surf_f, 0)
        YY = YY + SURF_OFF[1] * np.maximum(surf_f, 0)
    co = coat_at(XX, YY, ppm, salt)
    A = np.where(wall[..., None], Aw * co["hp"], A)
    h, cav = co["h"], co["cav"]
    h_extra = np.zeros(cls.shape, F32)          # joints and breaks: smooth, their slopes from finite differences
    if PITS_ON:                                  # round J: the concrete's larger voids show through the paint
        pt = wc.sample("pits", XX, YY, salt + 3, CACHE, ppm)
        A = np.where(wall[..., None], A * pt[..., :3], A)
        h = np.where(wall, h + pt[..., 3], h)
        h_extra = h_extra + np.where(wall, pt[..., 3], 0.0)
        cav = np.where(wall, np.maximum(cav, pt[..., 4]), cav)
        co["rec"] = (co["rec"] + 1.5 * pt[..., 4]).astype(F32)   # dust settles in them first
    # joints: 20 mm rounded grooves 8 mm deep, centred on the joint pixel's centre line
    jj = np.zeros(cls.shape, bool)
    jz = None
    if "joint" in z.files:
        jn = nearest_up(R.win(z["joint"]), R.cy, R.cx)
        if GROOVE_ZONES:                         # round K: distances from the joint lines within 2 coarse px
            j50 = R.win(z["joint"])
            iy = np.clip(np.round(R.cy).astype(np.int64), 0, j50.shape[0] - 1)
            ix = np.clip(np.round(R.cx).astype(np.int64), 0, j50.shape[1] - 1)
            dh = np.ones((R.H, R.W))
            sgn = np.zeros((R.H, R.W))           # > 0: below the horizontal joint's centre line
            dv = np.ones((R.H, R.W))
            for o in (0, -1, 1, -2, 2):
                yy = np.clip(iy + o, 0, j50.shape[0] - 1)
                d_ = np.abs(R.cy - yy)[:, None] / P50 * np.ones((1, R.W))
                on_ = (j50[yy][:, ix] & 1) > 0
                upd = on_ & (d_ < dh)
                dh = np.where(upd, d_, dh)
                sgn = np.where(upd, np.sign(R.cy - yy)[:, None] * np.ones((1, R.W)), sgn)
                xx = np.clip(ix + o, 0, j50.shape[1] - 1)
                d_ = np.abs(R.cx - xx)[None, :] / P50 * np.ones((R.H, 1))
                on_ = (j50[iy][:, xx] & 2) > 0
                dv = np.where(on_ & (d_ < dv), d_, dv)
            dj = np.minimum(dh, dv)
        else:
            dv = np.abs(R.cx - np.round(R.cx))[None, :] / P50 * np.ones((R.H, 1))
            dh = np.abs(R.cy - np.round(R.cy))[:, None] / P50 * np.ones((1, R.W))
            dj = np.where((jn & 2) > 0, dv, 1.0)
            dj = np.minimum(dj, np.where((jn & 1) > 0, dh, 1.0))
        prof = np.clip(1.0 - (dj / 0.0105) ** 2, 0, 1)
        jj = (prof > 0) & wall
        if GROOVE_ZONES:
            jz = groove_zones(R, jn, dv, dh, sgn, dj, prof, wall, z["joint"])       # round K
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
        ext = {}
        A = replay(A, load_steps(d, plane), R, XX, YY, wall, cls, salt, layers=layers, rec=co["rec"],
                   masks={"wall50": wall50, "steel50": st50, "steel": steel, "jz": jz}, extra=ext)
        if jz is not None:                       # round K: the groove's floor (crack, dirt) and the lips' chips
            A = groove_floor(A, d, plane, R, XX, YY, jz, ext, salt)
        if "h" in ext:                           # round J: the flakes sit a film's thickness below the paint
            h = np.where(wall, h + ext["h"], h)
            h_extra = h_extra + np.where(wall, ext["h"], 0.0)
    gx = np.where(wall, co["gx"], 0.0)
    gy = np.where(wall, co["gy"], 0.0)
    ey, ex = np.gradient(h_extra, 1.0 / ppm)
    return {"albedo": A, "clean": clean, "height": h.astype(F32), "cav": cav.astype(F32), "cls": cls, "joint": jj,
            "extra": ext if not clean_only else {},
            "region": R, "gx": (gx + ex).astype(F32), "gy": (gy + ey).astype(F32),
            "Ncap": cap["N"] if cap is not None else None}


def dist_upto(core, R_):
    """Distance in pixels (Euclidean shells) from the True pixels, up to R_; R_ + 1 beyond."""
    d = np.where(core, 0, R_ + 1).astype(np.int16)
    offs = [(dy, dx) for dy in range(-R_, R_ + 1) for dx in range(-R_, R_ + 1) if 0 < dy * dy + dx * dx <= R_ * R_]
    offs.sort(key=lambda o: o[0] * o[0] + o[1] * o[1])
    for dy, dx in offs:
        r = int(np.ceil(np.hypot(dy, dx)))
        sh = np.roll(np.roll(core, dy, 0), dx, 1)
        d = np.where(sh & (d > r), r, d).astype(np.int16)
    return d


def fine_surfaces(R, s50, d50, dep_f):
    """Round K: each fine pixel's surface colour: of its 3x3 coarse neighbours, the one whose depth is nearest the
    capture's depth there (both from the same camera plane), so the boundary follows the fine geometry."""
    H, W = dep_f.shape
    iy = np.clip(np.round(R.cy).astype(np.int64), 0, s50.shape[0] - 1)
    ix = np.clip(np.round(R.cx).astype(np.int64), 0, s50.shape[1] - 1)
    best = np.full((H, W), np.inf)
    out = np.full((H, W), -1, np.int16)
    dep_f = np.nan_to_num(dep_f, nan=1e3, posinf=1e3)
    for dy in (0, -1, 1):
        yy = np.clip(iy + dy, 0, s50.shape[0] - 1)
        for dx in (0, -1, 1):
            xx = np.clip(ix + dx, 0, s50.shape[1] - 1)
            s_ = s50[yy][:, xx]
            e_ = np.abs(d50[yy][:, xx] - dep_f) + 1e-3 * (abs(dy) + abs(dx)) + np.where(s_ < 0, 1e6, 0.0)
            upd = e_ < best
            best = np.where(upd, e_, best)
            out = np.where(upd, s_, out)
    return out


def groove_zones(R, jn, dv, dh, sgn, dj, prof, wall, jfull=None):
    """Round K: the joint grooves' zones at the fine grid: lip (the face within LIP_M of the edge), floor, the face
    under a horizontal groove, and a panel offset per side of each groove (from the joint lines' coarse positions:
    the same in every crop)."""
    ppm = R.ppm
    lip = wall & (dj > JOINT_HALF_M) & (dj <= JOINT_HALF_M + LIP_M)
    floor = wall & (dj < 0.7 * JOINT_HALF_M)
    horiz = (dh <= dv) & (dh < 1.0)
    under = wall & horiz & (sgn > 0) & (dj > JOINT_HALF_M) & (dj <= JOINT_HALF_M + UNDER_M)
    # panels: split at each joint's centre line (the last joint row whose centre the pixel is below, the last joint
    # column whose centre it is right of; coarse and absolute, so the same in every crop)
    ycoarse = np.floor(R.cy + R.cy0 + 0.5).astype(np.int64)[:, None] * np.ones((1, R.W), np.int64)
    xcoarse = np.floor(R.cx + R.cx0 + 0.5).astype(np.int64)[None, :] * np.ones((R.H, 1), np.int64)
    below = (R.cy - np.round(R.cy))[:, None] * np.ones((1, R.W)) >= 0
    right = (R.cx - np.round(R.cx))[None, :] * np.ones((R.H, 1)) >= 0
    h0 = np.full((1, R.W), -1, np.int64)                  # the last joint above / left of the window, per column / row
    v0 = np.full((R.H, 1), -1, np.int64)
    if jfull is not None:
        cols = np.clip(np.floor(R.cx + R.cx0 + 0.5).astype(np.int64), 0, jfull.shape[1] - 1)
        rows = np.clip(np.floor(R.cy + R.cy0 + 0.5).astype(np.int64), 0, jfull.shape[0] - 1)
        if R.cy0 > 0:
            hj = (jfull[:R.cy0][:, cols] & 1) > 0
            h0 = np.where(hj.any(axis=0), R.cy0 - 1 - np.argmax(hj[::-1], axis=0), -1)[None, :]
        if R.cx0 > 0:
            vj = (jfull[rows][:, :R.cx0] & 2) > 0
            v0 = np.where(vj.any(axis=1), R.cx0 - 1 - np.argmax(vj[:, ::-1], axis=1), -1)[:, None]
    hrow = np.maximum.accumulate(np.maximum(np.where(((jn & 1) > 0) & below, ycoarse, -1), np.where(np.arange(R.H)[:, None] == 0, h0, -1)), axis=0)
    vcol = np.maximum.accumulate(np.maximum(np.where(((jn & 2) > 0) & right, xcoarse, -1), np.where(np.arange(R.W)[None, :] == 0, v0, -1)), axis=1)
    ph = (np.sin(hrow * 12.9898 + vcol * 78.233) * 43758.5453) % 1.0
    pv = (np.sin(hrow * 39.3468 + vcol * 11.135) * 24634.6345) % 1.0
    under_w = (wall & horiz & (sgn > 0)) * np.clip(1.0 - (dj - JOINT_HALF_M) / UNDER_M, 0, 1) * (dj > JOINT_HALF_M - 0.002)
    return {"lip": lip, "floor": floor, "under": under, "under_w": under_w.astype(F32), "dj": dj, "prof": prof,
            "wall": wall.astype(F32), "pox": (17.0 * ph).astype(F32), "poy": (13.0 * pv).astype(F32)}


def groove_bias(jz):
    """Round K: the paint failure's detail bias at a groove (in the detail's std), smooth so flake edges stay curved:
    a bump at the arris (lips first), a ramp down into the floor (last), a ramp on the face under a horizontal groove."""
    dj = jz["dj"]
    lip = np.exp(-0.5 * ((dj - JOINT_HALF_M - 0.5 * LIP_M) / (0.6 * LIP_M)) ** 2)
    floor = np.clip((JOINT_HALF_M - dj) / (0.5 * JOINT_HALF_M), 0, 1)
    under = jz["under_w"] if "under_w" in jz else jz["under"].astype(F32)
    return (GROOVE_BIAS[0] * lip - GROOVE_BIAS[1] * floor + GROOVE_BIAS[2] * under) * jz["wall"]


def groove_floor(A, d, plane, R, XX, YY, jz, ext, salt):
    """Round K: in the groove: dirt in the floor (sealant bleed and run-off, by the local soiling), a hairline crack along
    part of the joint (years since repaint), chips on the lips (by the local paint failure)."""
    import json as _json
    try:
        cfg_ = _json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))["config"]
        Rs = float(cfg_.get("R", 0.0))
        import weather_fields as wf_
        wear_ = float(wf_.auto_amounts(cfg_)[2].get("wear", 0.0))
    except Exception:
        Rs, wear_ = 0.0, 0.0
    st = {s["name"]: s for s in load_steps(d, plane)} if FLOOR_DIRT > 0 or LIP_CHIP[1] > 0 else {}
    soil = np.clip(bspline_up(R.win(st["soiling"]["alpha"]), R.cy, R.cx), 0, 1) if "soiling" in st else 0.0
    peel = np.clip(bspline_up(R.win(st["peeling"]["alpha"]), R.cy, R.cx), 0, 1) if "peeling" in st else 0.0
    fl = jz["floor"]
    A = np.where(fl[..., None], A * (1.0 - FLOOR_DIRT * np.clip(soil * 2.0, 0, 1) * jz["prof"])[..., None], A).astype(F32)
    ck = FLOOR_CRACK[2] * nz_smooth(FLOOR_CRACK[0], FLOOR_CRACK[1], Rs)
    if ck > 0:
        g = wd.hex_g(tile("crack"), XX, YY, 0.20, salt + 404, ppm_out=R.ppm)
        along = wd.norm_cdf(wd.band_g(tile("streak"), YY, XX, 0.3, salt + 405, ppm_out=R.ppm))   # breaks along the joint
        line = (jz["dj"] < 0.35e-3 + 0.25e-3 * np.clip(g, -2, 2)) & (along < ck) & fl
        A = np.where(line[..., None], A * 0.35, A).astype(F32)
        if ext is not None:
            ext["groove_crack"] = line
    reg = 0.0                                                   # the flaking around (0.5 m): lips 3-8x the open face
    if "peeling" in st:
        pr = _box_blur(np.asarray(R.win(st["peeling"]["alpha"]), np.float64), 12)
        reg = np.clip(bspline_up(pr, R.cy, R.cx), 0, 1)
    p_ = np.clip(LIP_CHIP[0] + LIP_CHIP[1] * wear_ + LIP_CHIP[2] * reg, 0, 0.5)
    u = wd.norm_cdf(wd.hex_g(tile("chip"), XX * 8.0, YY * 8.0, 1.6, salt + 406, ppm_out=R.ppm / 8.0))
    dl_ = (jz["dj"] - JOINT_HALF_M) / LIP_M                   # 0 at the arris, 1 at the lip's inner end
    zone = (jz["dj"] > JOINT_HALF_M - 0.001) & (dl_ <= 1.0) & ~jz["floor"]
    chip = zone & (u > 1.0 - 2.0 * p_ + 0.25 * np.clip(dl_, 0, 1))    # bites, deepest at the arris
    if chip.any():
        import weather_fields as wf_
        oc = np.array(wf_.COL["old_coat"], F32)
        A = np.where(chip[..., None], A + (oc - A) * 0.9, A).astype(F32)
        if ext is not None:
            ext["lip_chip"] = chip
    if ext is not None:
        ext["jz"] = {k: v for k, v in jz.items() if k in ("lip", "floor", "under", "dj", "wall")}
    return A


def bar_coords(st, ppm):
    """Round K: each fine steel pixel in a bar (a row run of steel 2 px to RUN_BAR_MAX_M wide): its place across
    the bar t (0-1), the run's width (px) and centre (px column). Returns (bar, t, wid, cx)."""
    H, W = st.shape
    d = np.diff(np.pad(st.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    xs = np.arange(W)[None, :]
    start = np.maximum.accumulate(np.where(d[:, :-1] == 1, xs, -1), axis=1)
    end = np.minimum.accumulate(np.where(d[:, 1:] == -1, xs, W)[:, ::-1], axis=1)[:, ::-1]
    wid = end - start + 1
    bar = st & (wid <= RUN_BAR_MAX_M * ppm) & (wid >= 2)
    t = (xs - start + 0.5) / np.maximum(wid, 1)
    return bar, t.astype(F32), wid, 0.5 * (start + end)


def _run_member(A, a50, pk50, col, R, XX, YY, masks, salt, extra=None):
    """Round K: a run as a stripe down each bar: coverage / opacity of the bar wide (the head covers it, the
    tail narrows to a drip end), its centre wobbling along the bar, fibres in its opacity; on wider steel (posts
    over RUN_BAR_MAX_M) a film. The mean over a bar's row is the 50 px/m coverage, as in the cover rule."""
    st, st50 = masks["steel"], masks["steel50"]
    cov = np.clip(np.where(st, masked_up(a50, st50, R.cy, R.cx), 0.0), 0, 1)
    op = np.clip(np.where(st, masked_up(pk50, st50, R.cy, R.cx), 0.0), 0, 1)
    bar, t, wid, cx = bar_coords(st, R.ppm)
    xc_m = R.X[0] + (cx - 0.0) / R.ppm                   # the bar's centre (m, plane x)
    wf_ = np.clip(cov / np.maximum(op, 1e-4), 0.0, 1.0)
    amp = 0.5 * (1.0 - wf_) * RUN_WOB_K
    c = 0.5 + amp * (0.6 * np.sin(2 * np.pi * YY / RUN_WOB[0] + 23.0 * xc_m)
                     + 0.4 * np.sin(2 * np.pi * YY / RUN_WOB[1] + 41.0 * xc_m))
    g = wd.band_g(tile("streak"), XX, YY, 0.12, salt, ppm_out=R.ppm)
    g2 = wd.band_g(tile("streak"), XX, YY, 0.05, salt + 7, ppm_out=R.ppm)
    e = (0.5 * wf_ - np.abs(t - c)) * wid + RUN_RAG_MM * 1e-3 * R.ppm * np.clip(g2, -2.5, 2.5) / 1.5
    inside = np.clip(e / RUN_EDGE_PX + 0.5, 0.0, 1.0)
    fib = np.clip(1.0 + RUN_FIB * g, 0.45, 1.3)
    a = np.where(bar, op * fib * inside, np.where(st, cov * np.clip(1.0 + 0.5 * RUN_FIB * g, 0.6, 1.2), 0.0))
    a = np.clip(a, 0.0, 0.95).astype(F32)
    if extra is not None:                                 # the close-up check (R8c)
        extra["run_af"] = a
        extra["bar"] = bar
    c_ = col * (1.0 + 0.08 * np.clip(g, -2, 2) / 2)[..., None]
    if RUN_TIDE[1] > 0:                                   # K: the film dries at its edges, darker there
        tide = np.clip(1.0 - np.maximum(e, 0.0) / RUN_TIDE[0], 0.0, 1.0) * (bar & (inside > 0.05)) * (wf_ < 0.97)
        c_ = c_ * (1.0 - RUN_TIDE[1] * tide)[..., None]
    return (A + (c_ - A) * a[..., None]).astype(F32)


def replay(A, steps, R, XX, YY, wall, cls, salt, layers=None, rec=None, masks=None, extra=None):
    """The generator's composite, step by step, at the fine grid with each layer refined."""
    lum = np.array([0.2126, 0.7152, 0.0722], F32)
    A_clean = A.copy()                                   # J23: the clean albedo, for the flakes' dirt
    hy, hx = R.half_coords()
    bare_pending = None
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
        if name == "rust_run" and RUN_MEMBER and masks is not None and "peak" in s:   # round K
            A = _run_member(A, a50, R.win(s["peak"]), col, R, XX, YY, masks, salt + 11 * k, extra=extra)
            continue
        mode, tname, cell, wk, cvar, rshare = REFINE.get(name, ("smooth", None, 0, 0, 0, 0))
        src = blur_coarse(a50) if mode == "film" else a50
        if masks is not None:
            a_up = np.where(wall, masked_up(src, masks["wall50"], R.cy, R.cx), 0.0)
            pk50 = local_max3(np.where(masks["wall50"], a50, 0.0))
            peak = np.where(wall, masked_up(pk50, masks["wall50"], R.cy, R.cx), 1.0)
            if name in ("rust", "rust_run", "rust_bare"):   # rust on the steel, its runs on the walls
                a_st = masked_up(a50, masks["steel50"], R.cy, R.cx)
                a_up = np.where(masks["steel"], a_st, a_up)
                pk_st = local_max3(np.where(masks["steel50"], a50, 0.0))
                if name == "rust_run" and RUN_PEAK_KEEP > 0:   # J2: a run keeps its source's opacity and narrows
                    pk_ = np.where(masks["steel50"], a50, 0.0).astype(F32)   # (coverage falls, not the colour)
                    for yy_ in range(1, pk_.shape[0]):
                        pk_[yy_] = np.where(masks["steel50"][yy_], np.maximum(pk_[yy_], RUN_PEAK_KEEP * pk_[yy_ - 1]), 0.0)
                    pk_st = np.maximum(pk_st, pk_)
                peak = np.where(masks["steel"], masked_up(pk_st, masks["steel50"], R.cy, R.cx), peak)
            a_up = np.clip(a_up, 0, 1)
        else:
            a_up = np.clip(bspline_up(src, R.cy, R.cx), 0, 1)
            peak = bspline_up(local_max3(a50), R.cy, R.cx)
        g = None
        if mode in ("film", "cover", "band"):
            jz_ = masks.get("jz") if masks is not None else None
            XXg, YYg = XX, YY
            if jz_ is not None and name in PANEL_LAYERS:          # K: flakes stop at the groove (offset per panel)
                XXg, YYg = XX + jz_["pox"], YY + jz_["poy"]
            if mode == "band":
                g = wd.band_g(tile(tname), XXg, YYg, cell, salt + 11 * k, ppm_out=R.ppm)
            else:
                g = wd.hex_g(tile(tname), XXg, YYg, cell, salt + 11 * k, ppm_out=R.ppm)
            if jz_ is not None and name == "peeling":            # K: lips first, the floor last, the face under more
                g = (g + groove_bias(jz_)).astype(F32)
            if name in ("rust", "rust_bare") and masks is not None and STEEL_DETAIL_K > 1:   # K: finer on steel
                kk_ = STEEL_DETAIL_K
                g_st = wd.hex_g(tile(tname), XX * kk_, YY * kk_, cell * kk_, salt + 11 * k + 5, ppm_out=R.ppm / kk_)
                g = np.where(masks["steel"], g_st, g)
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
            if name == "peeling" and PEEL_OPAQUE:          # J19: paint is there or gone
                peak = np.ones_like(a_up)
            if name == "rust_bare" and BARE_OPAQUE:        # K: so is the paint on steel (30 % opaque chips read as
                peak = np.ones_like(a_up)                  # light grey paint, not as exposed metal)
            u = wd.norm_cdf(g).astype(F32)
            a = wd.refine_cover(a_up, peak, u, wk)
            cmod = 1.0 + cvar * (u - 0.5) * 2.0
        else:
            a = a_up
            cmod = 1.0
        if name == "rust_bare" and BARE_RING_MM > 0 and masks is not None:   # J3: drawn with the rust (its ring)
            bare_pending = (a_up, col, a)
            continue
        if name == "rust" and bare_pending is not None and RUST_ANAT:
            b_up, b_col, b_chip = bare_pending
            core = a > 0.12
            mm = R.ppm * 1e-3
            Rp = max(2, int(round(ANAT_HALO_MM * mm)))
            dout = dist_upto(core, Rp)
            din = dist_upto(~core & masks["steel"], max(2, int(round(ANAT_MARGIN_MM[1] * mm))))
            n1 = wd.norm_cdf(wd.hex_g(tile("rust"), XX, YY, 0.20, salt + 101, ppm_out=R.ppm))
            n2 = wd.norm_cdf(wd.hex_g(tile("rust"), XX, YY, 0.20, salt + 202, ppm_out=R.ppm))
            st_ = masks["steel"]
            near_b = b_up > 0.02
            wm_ = (ANAT_METAL_MM[0] + (ANAT_METAL_MM[1] - ANAT_METAL_MM[0]) * n2) * mm
            metal_ = st_ & ~core & (dout <= np.maximum(wm_, 1.0)) & (n1 > 1.0 - ANAT_METAL_SHARE) & near_b
            halo_ = st_ & ~core & ~metal_ & (dout <= Rp) & near_b
            hw = np.clip(1.0 - dout / max(Rp, 1), 0, 1) * 0.6
            A = (A * np.where(halo_[..., None], 1.0 - hw[..., None] * np.array([0.0, 0.03, 0.10], F32), 1.0)).astype(F32)
            if TARN:                                 # round K: tarnished, varied (n1, n2: the anatomy's own fields)
                ct_ = C_TARN + (C_TARN_DARK - C_TARN) * np.clip((n1 - 0.55) / 0.3, 0, 1)[..., None]
                ct_ = ct_ + (C_TARN_BROWN - ct_) * np.clip((n2 - 0.6) / 0.3, 0, 1)[..., None]
                A = np.where(metal_[..., None], A + (ct_ - A) * TARN_OPACITY, A).astype(F32)
            else:
                A = np.where(metal_[..., None], A + (C_FLASH - A) * 0.9, A).astype(F32)
            wmar = (ANAT_MARGIN_MM[0] + (ANAT_MARGIN_MM[1] - ANAT_MARGIN_MM[0]) * n1) * mm
            margin_ = core & st_ & (din <= np.maximum(wmar, 1.0)) & (n2 > 0.35)
            if extra is not None:                         # J11: the rails close-up checks (R7 rims)
                extra["rust_a"], extra["rim"] = a, (metal_ | halo_)
                extra["metal"] = metal_                    # K: R7c's metal colour
                extra["steel"] = st_                       # J28: R7c's perimeter on painted steel
            chips_ = np.where(dout <= Rp, 0.0, b_chip)
            A = (A + (b_col - A) * chips_[..., None]).astype(F32)
            bare_pending = None
            c = col * (cmod[..., None] if np.ndim(cmod) == 2 else cmod)
            if DCORE and "age" in s:                      # K: old scale dark inside the patch, fresh at its edge
                age_ = np.clip(masked_up(R.win(s["age"]), masks["steel50"], R.cy, R.cx), 0, 1)
                n3 = wd.norm_cdf(wd.hex_g(tile("rust"), XX * 4.0, YY * 4.0, DCORE_CELL * 4.0, salt + 303, ppm_out=R.ppm / 4.0))
                dk_ = (DCORE[2] * nz_smooth(DCORE[0], DCORE[1], age_) * np.clip((n3 - 0.30) / 0.35, 0, 1)
                       * (core & st_ & ~margin_))
                c = c + (C_DARK_K - c) * dk_[..., None]
                if extra is not None:
                    extra["rust_dark"] = dk_
                    if "sheen" in s:                          # K7: the sheen inside the fine dark scale
                        sh_ = np.clip(masked_up(R.win(s["sheen"]), masks["steel50"], R.cy, R.cx), 0, 1)
                        extra["sheen"] = (np.clip((sh_ - 0.25) / 0.3, 0, 1) * np.clip((dk_ - 0.25) / 0.3, 0, 1)
                                          * st_ * a).astype(F32)
            c = np.where(margin_[..., None], c + (C_FRESH_MARGIN - c) * 0.65, c)
            A = (A + (c - A) * a[..., None]).astype(F32)
            continue
        if name == "rust" and bare_pending is not None:
            b_up, b_col, b_chip = bare_pending
            core = a > 0.12
            r_ = max(1, int(round(BARE_RING_MM * 1e-3 * R.ppm)))
            ring = core.copy()
            for dy in range(-r_, r_ + 1):
                for dx in range(-r_, r_ + 1):
                    if dy * dy + dx * dx <= r_ * r_:
                        ring |= np.roll(np.roll(core, dy, 0), dx, 1)
            ring &= ~core & masks["steel"]
            near = ring.copy()
            for _ in range(3):
                near = near | np.roll(near, 1, 0) | np.roll(near, -1, 0) | np.roll(near, 1, 1) | np.roll(near, -1, 1)
            w_ring = np.where(ring & (b_up > 0.02), 0.85, 0.0)
            w_chip = np.where(near | core, 0.0, b_chip)                # chips away from the rust
            wb = np.maximum(w_ring, w_chip).astype(F32)
            A = (A + (b_col - A) * wb[..., None]).astype(F32)
            bare_pending = None
        if name == "peeling":                    # round J: flakes of concrete in the paint
            cm = wc.sample("formed", XX, YY, salt + 5, CACHE, R.ppm)
            wbu = np.clip(bspline_up(R.win(s["conc"]), R.cy, R.cx), 0, 1)[..., None] if "conc" in s else 1.0
            rr_ = max(1, int(round(0.01 * R.ppm)))          # J6: type a keeps the coat's grain (the older coat's)
            Al = A @ lum
            grain = np.clip(Al / np.maximum(_box_blur(Al, rr_), 1e-4), 0.7, 1.3)[..., None]
            if PEEL_PURE and "conc" in s:                   # J23: older coat or concrete per pixel, each pure
                import weather_fields as wf_
                import rust_flow as rf_
                conc_c = np.array(rf_.lab_to_lin(wf_.PEEL_CONC_LAB), F32) * np.array(wf_.PEEL_WARM, F32)
                old_c = np.array(wf_.COL["old_coat"], F32)
                uu = u if u is not None else 0.5
                tbm = (wbu[..., 0] + PEEL_DITHER * (uu - 0.5)) > 0.5
                rl = np.clip((A @ lum) / np.maximum(A_clean @ lum, 1e-4), 0.3, 1.15)[..., None]   # dirt as lightness
                cb_ = conc_c * rl ** wf_.PEEL_DIRT * cm[..., :3]
                ca_ = old_c * rl ** wf_.PEEL_DIRT_A * grain
                Ya, Yk = ca_ @ lum, A_clean @ lum
                ca_ = np.where((Ya > Yk)[..., None], ca_ * (Yk / np.maximum(Ya, 1e-6))[..., None], ca_)
                c = np.where(tbm[..., None], cb_, ca_).astype(F32)
                wbu = tbm[..., None].astype(F32)
            else:
                c = col * (wbu * cm[..., :3] + (1.0 - wbu) * grain)
            if PEEL_GRIME > 0:                            # J13: the exposed concrete's dirt is mottled, not a 2 cm blur
                gm_ = wd.hex_g(tile("grime"), XX, YY, 0.30, salt + 17 * k, ppm_out=R.ppm)
                c = c * (1.0 + PEEL_GRIME * wbu * np.clip(gm_, -2.5, 2.5)[..., None] / 2.5)
            pk = np.maximum(np.clip(peak, 1e-4, 1), 1e-4) if np.ndim(peak) else np.full(a.shape, max(float(peak), 1e-4))
            core = a > 0.5 * pk
            r_ = max(1, int(round(PEEL_EDGE_MM * 1e-3 * R.ppm)))
            dil, ero = core.copy(), core.copy()
            for dy in range(-r_, r_ + 1):
                for dx in range(-r_, r_ + 1):
                    if dy * dy + dx * dx <= r_ * r_:
                        sh_ = np.roll(np.roll(core, dy, 0), dx, 1)
                        dil |= sh_
                        ero &= sh_
            An = A + (c - A) * a[..., None]
            rim_in = core & ~ero
            top_e = rim_in & ~np.roll(core, r_ + 1, 0)                     # J5: paint above: its lip's shadow and the
            An = np.where(top_e[..., None], An * 0.70, np.where(rim_in[..., None], An * 0.90, An))   # dirt under it
            An = np.where((dil & ~core & wall)[..., None], An * 1.06, An)   # the broken paint edge: its clean body
            if "halo" in s:
                hl = np.clip(bspline_up(R.win(s["halo"]), R.cy, R.cx), 0, 1)
                gl = wd.hex_g(tile("check"), XX, YY, 0.30, salt + 13 * k, ppm_out=R.ppm)
                line = np.clip((gl - 1.3) / 0.3, 0, 1) * hl * (wall & ~dil)
                An = An * (1.0 - CHECK_DARK * line)[..., None]
            if extra is not None:
                extra["h"] = extra.get("h", 0.0) - PEEL_FILM_M * np.clip(a / pk, 0, 1)
                extra["peel_a"], extra["peel_pk"] = a, pk          # J11: the flake checks (P3)
                extra["peel_b"] = wbu[..., 0] if np.ndim(wbu) == 3 else np.full(a.shape, float(wbu), F32)
            A = An.astype(F32)
            continue
        if op == "damage":
            cb = wc.sample("broken", XX, YY, salt + 6, CACHE, R.ppm)   # round J: the fracture's aggregate
            col = col * cb[..., :3]
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


# round K7: an optional sky reflection for the review's sheen toggle (research rust-blue-sheen.md section 5): split-sum
# specular with Karis's EnvBRDFApprox; F0 0.04 everywhere, 0.08 under the sheen; roughness 0.86 on the coat and 0.88 on
# rust, 0.55 under the sheen, 0.45 on painted steel; a stated clear sky: horizon 0.80 x (0.869, 1.009, 1.296) (9,000 K),
# zenith 0.50 x (0.721, 1.004, 1.781) (20,000 K), linear in the sine of elevation; ground 0.30 neutral; the reflection
# averaged toward the hemisphere's mean as roughness grows. The gates measure albedo; this is for review only.
SKY_HOR = 0.80 * np.array([0.869, 1.009, 1.296], F32)
SKY_ZEN = 0.50 * np.array([0.721, 1.004, 1.781], F32)
SKY_GND = np.array([0.30, 0.30, 0.30], F32)


def env_brdf(rough, nov):
    c0 = np.array([-1.0, -0.0275, -0.572, 0.022])
    c1 = np.array([1.0, 0.0425, 1.04, -0.04])
    r = rough[..., None] * c0 + c1
    a004 = np.minimum(r[..., 0] * r[..., 0], np.exp2(-9.28 * nov)) * r[..., 0] + r[..., 1]
    return -1.04 * a004 + r[..., 2], 1.04 * a004 + r[..., 3]


def sky_env(Rdir, rough):
    """Radiance reflected along Rdir (y up), blurred toward the hemisphere mean with roughness."""
    el = np.clip(Rdir[..., 1], -1, 1)
    sky = SKY_HOR + (SKY_ZEN - SKY_HOR) * np.clip(el, 0, 1)[..., None]
    sharp = np.where((el >= 0)[..., None], sky, SKY_GND)
    mean = 0.5 * (0.5 * (SKY_HOR + SKY_ZEN)) + 0.5 * SKY_GND
    w = np.clip(rough, 0, 1)[..., None] ** 2
    return sharp + (mean - sharp) * w


def spec_term(res, view="S", tilt_deg=0.0):
    """The sky reflection (linear RGB) for a crop with captured normals: V toward the camera, tilted tilt_deg so the
    view looks up (a player below the surface); F0 and roughness by class and the sheen."""
    Nc = res.get("Ncap")
    if Nc is None:
        return None
    Nb = Nc / np.maximum(np.linalg.norm(Nc, axis=-1, keepdims=True), 1e-6)
    t = np.radians(tilt_deg)
    vz = {"S": 1.0, "N": -1.0}.get(view, 0.0)
    V = np.array([0.0 if view in ("S", "N") else -1.0, -np.sin(t), vz * np.cos(t) if view in ("S", "N") else 0.0])
    V = V / np.linalg.norm(V)
    nov = np.clip((Nb * V).sum(-1), 1e-3, 1.0)
    Rdir = 2.0 * nov[..., None] * Nb - V
    cls = res["cls"]
    sheen = res.get("extra", {}).get("sheen")
    sheen = np.zeros(cls.shape, F32) if sheen is None else sheen
    steel = cls == 7
    rust_a = res.get("extra", {}).get("rust_a")
    rough = np.where(steel, 0.45, 0.86).astype(F32)
    if rust_a is not None:
        rough = np.where(steel, 0.45 + (0.88 - 0.45) * np.clip(rust_a, 0, 1), rough)
    rough = rough + (0.55 - rough) * sheen
    F0 = 0.04 + 0.04 * sheen
    Aa, Bb = env_brdf(rough, nov)
    return ((F0 * Aa + Bb)[..., None] * sky_env(Rdir, rough)).astype(F32)


def lit(res, Ngeom=None, view="S", spec=False, tilt_deg=0.0):
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
    if spec:                                     # K7: the review's sky-reflection toggle
        sp = spec_term(res, view, tilt_deg)
        if sp is not None:
            out = out + sp * (1.0 - 0.4 * cav)[..., None]
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
