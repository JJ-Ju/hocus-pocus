"""material.py - the painted wall's material terms in facade space, shared by the clean bases, the
weathering (dirt follows the material: rule J2), the lit previews and the close-ups.

The round-E coat set (spraymacro, a 3.6 m tile; spraydetail, a 0.6 m tile) carries the coat's own
detail; its macro scales were left to the shader. These are those shader terms, as formulas the
engine shader repeats:
  coat clouding  spray-pass thickness: horizontal passes 0.25-1 m tall and 1.5-4 m long, and
                 clouds of 8-50 cm. About 1.5 % per band on a new coat; each repaint lays a new
                 coat over the old texture and adds a little (+12 % per repaint, capped).
  joints         construction joints at each floor and induced joints about every 3 m on flat
                 walls: 20 mm grooves, sealed and painted over. Dirt collects in them, water
                 runs out of the horizontal ones, and they shade as a thin line under light.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_measure as wm  # noqa: E402
import wx_noise as nz  # noqa: E402

F32 = np.float32
CLOUD_NEW = 0.015           # relative std per band (10-50 cm, 0.5-2 m) of a new coat's albedo
CLOUD_PER_REPAINT = 0.12    # x per repaint campaign
CLOUD_MAX = 0.026
JOINT_W = 0.02              # groove width, m
JOINT_TONE = 0.97           # sealant painted over: a hair darker when clean
VJ_SPACING = 4.0            # induced joints on flat walls, m: two across an 11 m end wall; a 3 m grid read as precast panels


def repaints(age, upkeep):
    """Repaint campaigns so far: one per cycle, cycle = lerp(24, 7, upkeep) years."""
    if age <= 0:
        return 0
    cycle = 24.0 + (7.0 - 24.0) * float(upkeep)
    return int(age // cycle)


def cloud_amp(n_repaint):
    return min(CLOUD_MAX, CLOUD_NEW * (1.0 + CLOUD_PER_REPAINT * n_repaint))


def coat_cloud(shape, ppm, key, n_repaint=0):
    """Albedo factor (mean 1) of the coat's thickness variation. Two parts with equal energy:
    spray passes (horizontal, anisotropic) and clouds (isotropic, 8 cm to 1 m)."""
    passes = (0.8 * nz.gfield(shape, nz.octave_sigma(5, ppm), key + ("pass6",), aniso=(1.0, 4.0)) +
              0.6 * nz.gfield(shape, nz.octave_sigma(6, ppm), key + ("pass7",), aniso=(1.0, 5.0)))
    clouds = (nz.fbm(shape, ppm, [4, 5, 6, 7], key + ("cloud",)) +
              0.8 * nz.gfield(shape, max(0.7, 0.08 / 3.0 * ppm), key + ("cloud9",)))
    f = passes / max(passes.std(), 1e-9) + clouds / max(clouds.std(), 1e-9)
    f = f / max(f.std(), 1e-9)
    return (1.0 + CLOUD_GAIN * cloud_amp(n_repaint) * f).astype(F32)


# calibrated so each J1 band (10-50 cm, 0.5-2 m) of the factor reads CLOUD_NEW on a new coat
CLOUD_GAIN = 2.26

# round J: the coat's colour drifts as well as its value (user, round I: 'more variety in saturation';
# research surface-detail-techniques.md 7: the clean coat varied only in value). A chroma field scales the
# paint's distance from grey, a warm/cool field tilts red against blue, both at the clouds' scales (10 cm-2 m).
TINT_ON = True
TINT_S = 0.22               # chroma: x (1 + TINT_S x s), s unit std (about 0.45 C* std on the cream paint)
TINT_W = 0.004              # warm/cool: R x (1 + TINT_W x w), B x (1 - TINT_W x w)


def coat_tint(base, paint, ppm, key):
    """The paint's colour with its chroma and warm/cool drift (linear RGB, luminance kept)."""
    sh = paint.shape

    def fld(tag):
        f = nz.fbm(sh, ppm, [5, 6, 7], key + ("tint", tag)) + 0.7 * nz.gfield(sh, 0.10 / 3.0 * ppm, key + ("tint", tag, "f"))
        return (f / max(float(f.std()), 1e-9)).astype(F32)
    s, w = fld("s"), fld("w")
    lum = np.array([0.2126, 0.7152, 0.0722], F32)
    Y = (base @ lum)[..., None]
    b2 = Y + (base - Y) * (1.0 + TINT_S * s)[..., None]
    b2 = b2 * (1.0 + TINT_W * w[..., None] * np.array([1.0, 0.0, -1.0], F32))
    b2 = b2 * (Y / np.maximum((b2 @ lum)[..., None], 1e-6))          # keep the luminance (J1 measures it)
    return np.where(paint[..., None], b2, base).astype(F32)


def flat_walls(plane):
    """Painted pixels that belong to large solid flat elements (gables, core walls): a box of at
    least 2.5 x 5 m at one depth, at least 15 m2, filling >= 60 % of its box (a balcony back wall
    full of openings is not one). Joints are cut there."""
    m = plane["mask"] & np.isin(plane["cls"], (1, 2))
    dep = plane.get("depth")
    ppm = plane["ppm"]
    if dep is None:
        return m
    brk = np.zeros_like(m)
    brk[1:] |= np.abs(dep[1:] - dep[:-1]) > 0.05
    brk[:, 1:] |= np.abs(dep[:, 1:] - dep[:, :-1]) > 0.05
    lab, n = wm.label(m & ~brk)
    out = np.zeros_like(m)
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if xs.size < 15.0 * ppm * ppm:
            continue
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if bw >= 2.5 * ppm and bh >= 5.0 * ppm and xs.size >= 0.6 * bw * bh:
            out[ys, xs] = True
    return out


def joints(plane):
    """Joint grooves on the flat walls: horizontal at each floor row, vertical about every 3 m
    (spaced evenly across each flat element, at least 0.6 m from its sides). Returns
    (hmask, vmask, points): points are (row, col) along the horizontal joints, 0.25-0.75 m apart
    (jittered: a fixed 0.5 m step printed a lattice into the streaks, round G G6), the sources and
    anchors the weathering layers read."""
    ppm = plane["ppm"]
    H, W = plane["mask"].shape
    fw = plane.get("_flat")
    if fw is None:
        fw = flat_walls(plane)
        plane["_flat"] = fw
    hm = np.zeros((H, W), bool)
    vm = np.zeros((H, W), bool)
    wpx = max(1, int(round(JOINT_W * ppm)))
    rows = [r for r in plane.get("floor_rows", []) if plane.get("top_row", 0) + 0.3 * ppm < r < plane.get("ground_row", H) - 0.3 * ppm]
    for r in rows:
        r0 = int(r)
        hm[r0:r0 + wpx] = True
    hm &= fw
    lab, n = wm.label(fw)
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        x0, x1 = xs.min(), xs.max()
        span = (x1 - x0) / ppm
        k = int(np.floor(span / VJ_SPACING))
        if k < 1:
            continue
        for j in range(1, k + 1):
            x = int(round(x0 + j * (x1 - x0) / (k + 1)))
            col = (lab[:, x:x + wpx] == i)
            vm[:, x:x + wpx] |= col
    pts = []
    for r in rows:
        r0 = int(r)
        xs = np.flatnonzero(hm[r0])
        if xs.size == 0:
            continue
        rr = nz.rng("jpts", plane.get("name"), r0)
        x = xs[0] + rr.uniform(0.0, 0.5) * ppm
        on = np.zeros(W, bool)
        on[xs] = True
        while x <= xs[-1]:
            xi = int(x)
            if on[xi]:
                pts.append((r0 + wpx, xi))       # just below the groove: water leaves it here
            x += rr.uniform(0.25, 0.75) * ppm
    return hm, vm, pts


def joint_tone(hm, vm):
    """Clean albedo factor of the joints: the sealant line, painted over, a hair darker."""
    return np.where(hm | vm, JOINT_TONE, 1.0).astype(F32)


def joint_shade(hm, vm, ppm):
    """Lighting of a 20 mm groove under the preview sun (upper left): its upper and left lips cast
    a thin shadow into it. A factor on the shading, 1 elsewhere."""
    s = np.ones(hm.shape, F32)
    s[hm] *= 0.80
    s[vm] *= 0.88
    return s


def joint_dirt(hm, vm, ppm):
    """How much more dirt the material holds near the joints, for the weathering's material field:
    the groove itself (x1.9) and a short lip below each horizontal joint where water leaves it
    (decays over 4 cm)."""
    g = np.zeros(hm.shape, F32)
    g[hm | vm] = 0.9
    lip = np.zeros(hm.shape, F32)
    H = hm.shape[0]
    d = np.full(hm.shape[1], 1e9, F32)
    dec = 0.04 * ppm
    for y in range(H):
        d = np.where(hm[y], 0.0, d + 1.0)
        lip[y] = np.exp(-d / dec)
    lip[hm] = 0.0
    # where the joints cross, water from both meets and pauses (G5): +0.45 within 2 cm, 0 at 8 cm
    vd = vm.copy()
    for s in (1, 2):
        vd[:, s:] |= vm[:, :-s]
        vd[:, :-s] |= vm[:, s:]
    xm = hm & vd
    if xm.any():
        ys, xs = np.nonzero(xm)
        r = max(1, int(round(0.08 * ppm)))
        near = np.full(hm.shape, np.inf, F32)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                yy, xx = ys + dy, xs + dx
                ok = (yy >= 0) & (yy < H) & (xx >= 0) & (xx < hm.shape[1])
                near[yy[ok], xx[ok]] = np.minimum(near[yy[ok], xx[ok]], np.float32(np.hypot(dy, dx) / ppm))
        f = np.clip((0.08 - near) / 0.06, 0.0, 1.0)
        g = g + np.where(hm | vm, 0.45 * f, 0.0).astype(F32)
    return g + 0.5 * lip
