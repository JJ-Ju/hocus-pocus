"""weather_atlas.py — the weathering decal atlas and the macro-variation map (numpy + PIL).

Run inside Houdini (tex_build.py calls build_all) or alone:  python weather_atlas.py <tex_dir>

weather_atlas.png  4096 x 4096, one channel (alpha / coverage; white = full). The decal colour
                   comes from the decal mesh's vertex colour, so one atlas serves soot, damp,
                   rust, efflorescence and growth. Three regions:
  S  top half       16 tall cells 256 x 2048, source at the top (v = 1):
       0-2 narrow runs (notch, fixing; one with a break)   3-4 sill-end fans
       5-6 wide curtains built from 5-8 runs              7-8 fringes under a drip-less top
       9 rust run (teardrop)   10 rust run from a spall    11-12 layered stains (darker core)
       13 short partial drip   14 pale washed band         15 efflorescence drip
  B  bottom-left    16 cells 512 x 512:
       0-5 mottled stain blotches (2 round, 2 hanging, 2 with holes)   6-8 biological growth
       9 rust bloom   10 spall halo   11 soot cloud   12 efflorescence bloom   13 base algae
       14 repair ghost (soft rectangle)   15 soft round
  H  bottom-right   8 strips 2048 x 256, long axis along u:
       0-1 splash band (dense at the bottom, ragged top)   2-3 inside-corner grime (dense at the
       bottom edge)   4-5 worn-edge runs (half to two thirds empty)   6 drip-line band under a
       ledge (dense at the top, hair runs below)   7 tide mark
weather_atlas.json the cell rectangles in UV and the fill fraction of each streak cell.
macro_var.png      1024 x 1024, tileable value variation (mean 0.5) for the wall shader, sampled
                   with the wall UV (metres) / 40, so one tile spans 40 m.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

SW, SH = 256, 2048      # streak cell
BW = 512                # blotch cell
HW, HH = 2048, 256      # strip cell


def _resize(a, w, h):
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w, h), Image.BICUBIC))


def fbm(h, w, rng, base=4, octaves=5, gain=0.55, ay=1.0):
    """Value-noise fbm in [0, 1] (mean ~0.5); ay > 1 gives finer cells in y."""
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gx = max(2, int(base * 2 ** o))
        gy = max(2, int(base * 2 ** o * ay))
        g = rng.random((gy + 1, gx + 1)).astype(np.float32)
        out += amp * _resize(g, w, h)
        tot += amp
        amp *= gain
    out /= tot
    lo, hi = np.percentile(out, 1), np.percentile(out, 99)
    return np.clip((out - lo) / max(hi - lo, 1e-6), 0, 1)


def noise1d(n, cells, rng):
    v = rng.random(cells + 3)
    xs = np.linspace(0, cells, n)
    i = np.floor(xs).astype(int)
    f = xs - i
    f = f * f * (3 - 2 * f)
    return v[i] * (1 - f) + v[i + 1] * f


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def union(*layers):
    """Layered opacity: 1 - prod(1 - a). Overlaps get a darker core, gaps stay lighter."""
    out = np.zeros_like(layers[0])
    for a in layers:
        out = 1 - (1 - out) * (1 - np.clip(a, 0, 1))
    return out


# ------------------------------------------------------------------ streak cells
def _yx(h=SH, w=SW):
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    return y, x


def run(rng, cx, w0, w1, length, strength, meander=0.05, head=0.12, y0=0.0, grain=0.3):
    """One run: head width w0 widening to w1 (cell x units), from y0 down to y0 + length.
    Darkest in the head, then a long tail that fades out at its end."""
    y, x = _yx()
    t = np.clip((y - y0) / max(length, 1e-3), 0, 1)
    wig = (noise1d(SH, 40, rng)[:, None] - 0.5) * meander * 2 + (noise1d(SH, 300, rng)[:, None] - 0.5) * meander * 0.4
    width = w0 + (w1 - w0) * t
    d = np.abs(x - cx - wig * t) / np.maximum(width, 1e-3)
    prof = np.clip(1 - d, 0, 1) ** 1.2
    fade = np.clip(1 - t ** 1.4, 0, 1) ** 0.8 * (0.5 + 0.5 * np.exp(-t / head))
    fade = fade * (y >= y0) * (y <= y0 + length)
    g = 1 - grain + grain * noise1d(SH, 160, rng)[:, None]
    return strength * prof * fade * g


def texture2d(a, rng, amt=0.35, base=8, ay=1.5):
    """Mottle a coverage map with noise; on a 256 x 2048 streak cell ay 8 is square, so
    ay 1.5 gives grain stretched down the run."""
    n = fbm(a.shape[0], a.shape[1], rng, base=base, octaves=4, ay=ay)
    return a * (1 - amt + amt * n)


def streak_cells(rng):
    cells = []
    # 0-2 narrow runs
    cells.append(texture2d(run(rng, 0, 0.14, 0.24, 0.95, 1.0, 0.04), rng, 0.25))
    cells.append(texture2d(union(run(rng, 0.05, 0.12, 0.2, 0.62, 1.0, 0.06),
                                 run(rng, -0.1, 0.06, 0.1, 0.9, 0.35, 0.05)), rng, 0.25))
    cells.append(texture2d(union(run(rng, 0, 0.16, 0.22, 0.38, 1.0, 0.04),
                                 run(rng, 0.08, 0.1, 0.2, 0.42, 0.7, 0.05, y0=0.5)), rng, 0.3))
    # 3-4 sill-end fans: dark head 3-8 cm, fanning out, darkest in the first fifth
    cells.append(texture2d(union(run(rng, 0, 0.18, 0.8, 1.0, 0.9, 0.06, head=0.1),
                                 run(rng, 0, 0.1, 0.3, 0.3, 0.9, 0.02)), rng, 0.35))
    cells.append(texture2d(union(run(rng, -0.1, 0.15, 0.6, 0.7, 0.85, 0.08, head=0.15),
                                 run(rng, 0.25, 0.08, 0.25, 0.85, 0.45, 0.05),
                                 run(rng, -0.35, 0.06, 0.2, 0.5, 0.4, 0.05)), rng, 0.35))
    # 5-6 wide curtains from layered runs (where water collects)
    for nrun in (5, 8):
        layers = []
        for k in range(nrun):
            cx = -0.75 + 1.5 * (k + rng.uniform(-0.3, 0.3)) / (nrun - 1)
            layers.append(run(rng, cx, rng.uniform(0.08, 0.2), rng.uniform(0.18, 0.35),
                              0.3 + 0.7 * rng.random() ** 0.6, rng.uniform(0.18, 0.6), 0.05))
        top = np.clip(1 - _yx()[0] / 0.05, 0, 1) * 0.5 * (np.abs(_yx()[1]) < 0.85)
        cells.append(texture2d(union(*layers, top), rng, 0.35))
    # 7-8 fringes: dark band 5-15 cm under the lip, then hair runs 0.5-3 cm, spaced irregularly
    for nhair, band in ((16, 0.07), (9, 0.05)):
        y, x = _yx()
        bandn = noise1d(SW, 12, rng)[None, :]
        a = np.clip(1 - y / (band * (0.7 + 0.6 * bandn)), 0, 1) ** 0.7 * 0.75
        xs = np.sort(rng.uniform(-0.92, 0.92, nhair))
        layers = [a]
        for cx in xs:
            L = 0.06 + 0.94 * rng.random() ** 3.0          # most short, a few long
            layers.append(run(rng, cx, 0.02, 0.045, L, rng.uniform(0.25, 0.9), 0.015))
        cells.append(texture2d(union(*layers), rng, 0.3))
    # 9 rust run with a teardrop end
    y, x = _yx()
    c = run(rng, 0, 0.09, 0.15, 0.68, 1.0, 0.03)
    c = union(c, np.exp(-((x / 0.17) ** 2 + ((y - 0.64) / 0.04) ** 2)) * 0.75)
    cells.append(texture2d(c, rng, 0.25))
    # 10 rust from a spall: bloom at the head, a run below
    c = union(np.exp(-((x / 0.45) ** 2 + ((y - 0.03) / 0.03) ** 2)) * 0.9,
              run(rng, 0, 0.18, 0.3, 0.8, 0.9, 0.04, head=0.1))
    cells.append(texture2d(c, rng, 0.3))
    # 11-12 layered stains: 3-6 runs at 10-60 % plus a darker core
    for nrun, spread, lmax in ((5, 0.4, 0.95), (4, 0.55, 0.55)):
        layers = []
        for k in range(nrun):
            layers.append(run(rng, rng.uniform(-spread, spread), rng.uniform(0.2, 0.45), rng.uniform(0.35, 0.7),
                              rng.uniform(0.35, lmax), rng.uniform(0.1, 0.6), 0.08, head=0.25))
        cells.append(texture2d(union(*layers), rng, 0.45, base=6, ay=1.5))
    # 13 short partial drip
    cells.append(texture2d(run(rng, 0, 0.14, 0.2, 0.28, 0.95, 0.03), rng, 0.25))
    # 14 pale washed band: soft, wide, low contrast
    cells.append(texture2d(run(rng, 0, 0.55, 0.8, 1.0, 0.75, 0.08, head=0.6, grain=0.15), rng, 0.3, base=4, ay=1.5))
    # 15 efflorescence drip: lumpy head, short crusty runs
    n = fbm(SH, SW, rng, base=24, octaves=3, ay=4)
    c = union(np.exp(-((x / 0.5) ** 2 + ((y - 0.02) / 0.025) ** 2)) * 0.95,
              run(rng, 0, 0.3, 0.35, 0.35, 0.85, 0.06, head=0.3),
              run(rng, 0.3, 0.1, 0.15, 0.2, 0.7, 0.03))
    cells.append(c * sstep(0.25, 0.45, n * 0.6 + c * 0.6))
    return cells


# ------------------------------------------------------------------ blotch cells
def _blotch_frame(n=BW):
    y = np.linspace(-1, 1, n, dtype=np.float32)[:, None]
    x = np.linspace(-1, 1, n, dtype=np.float32)[None, :]
    return y, x


def mottle(rng, sx=1.0, sy=1.0, oy=0.0, holes=0.0, levels=(0.3, 0.5, 0.68), alphas=(0.35, 0.3, 0.35)):
    """Facade stain blotch: a warped soft shape cut at three noise levels, so it is built
    from layered opacities with lighter gaps, a darker core and a ragged edge."""
    y, x = _blotch_frame()
    w1 = fbm(BW, BW, rng, base=3, octaves=4) - 0.5
    w2 = fbm(BW, BW, rng, base=3, octaves=4) - 0.5
    r = np.sqrt(((x + 0.5 * w1) / sx) ** 2 + ((y - oy + 0.5 * w2) / sy) ** 2)
    shape = np.clip(1 - r, 0, 1)
    n = fbm(BW, BW, rng, base=5, octaves=5)
    f = shape * (0.35 + 0.9 * n)
    out = np.zeros_like(f)
    for lv, al in zip(levels, alphas):
        out = union(out, al * sstep(lv * 0.6 - 0.12, lv * 0.6 + 0.14, f))
    out *= sstep(0.0, 0.35, shape)                 # soft rim: the stain fades out, no outline
    if holes:
        h = fbm(BW, BW, rng, base=7, octaves=3)
        out *= 1 - holes * sstep(0.62, 0.75, h)
    fine = fbm(BW, BW, rng, base=20, octaves=3, ay=0.3)    # vertical mottle, as rain leaves it
    out *= 0.65 + 0.35 * fine
    edge = np.clip((1 - np.maximum(np.abs(x), np.abs(y))) / 0.06, 0, 1)
    return out * edge


def hanging(rng):
    """A blotch that hangs from a ledge: dense at the top, dripping runs off its lower edge."""
    y, x = _blotch_frame()
    a = mottle(rng, sx=0.9, sy=0.55, oy=-0.4)
    for k in range(6):
        cx = rng.uniform(-0.75, 0.75)
        L = rng.uniform(0.3, 1.2)
        w = rng.uniform(0.03, 0.08)
        t = np.clip((y + 0.2) / L, 0, 1)
        d = np.abs(x - cx) / (w * (1 + t))
        a = union(a, np.clip(1 - d, 0, 1) * (1 - t) * (y > -0.2) * rng.uniform(0.2, 0.5))
    edge = np.clip((1 - np.maximum(np.abs(x), np.abs(y))) / 0.06, 0, 1)
    return a * edge


def blotch_cells(rng):
    cells = [mottle(rng), mottle(rng, sx=0.8, sy=0.9),
             hanging(rng), hanging(rng),
             mottle(rng, holes=0.8, levels=(0.25, 0.45, 0.62)), mottle(rng, sx=0.9, sy=0.7, holes=0.6)]
    y, x = _blotch_frame()
    edge = np.clip((1 - np.maximum(np.abs(x), np.abs(y))) / 0.06, 0, 1)
    # 6-8 biological growth: speckled colonies inside a cluster mask, heavier at the bottom
    for k in range(3):
        cl = mottle(rng, sx=0.95, sy=0.8, oy=0.15, levels=(0.2, 0.35, 0.5), alphas=(0.4, 0.4, 0.4))
        sp = fbm(BW, BW, rng, base=64, octaves=2)
        speck = sstep(0.4, 0.75, sp)
        bottom = 0.45 + 0.55 * sstep(-0.6, 0.8, y)
        cells.append(np.clip(cl * (0.35 + 0.75 * speck) * bottom * 1.3, 0, 1) * edge)
    # 9 rust bloom
    w = fbm(BW, BW, rng, base=4, octaves=4) - 0.5
    r = np.sqrt(x ** 2 + y ** 2) + 0.35 * w
    cells.append(np.clip(1 - r / 0.75, 0, 1) ** 0.7 * (0.6 + 0.4 * fbm(BW, BW, rng, base=20, octaves=2)) * edge)
    # 10 spall halo: a ring of loosened, stained concrete around a spall
    ring = np.exp(-((r - 0.45) / 0.18) ** 2) * 0.8 + np.clip(1 - r / 0.45, 0, 1) * 0.3
    cells.append(ring * (0.6 + 0.4 * fbm(BW, BW, rng, base=16, octaves=3)) * edge)
    # 11 soot cloud: soft, broad, vertical texture
    s = mottle(rng, sx=0.95, sy=0.95, levels=(0.15, 0.3, 0.45), alphas=(0.3, 0.3, 0.3))
    cells.append(s * (0.6 + 0.4 * fbm(BW, BW, rng, base=12, octaves=3, ay=0.25)))
    # 12 efflorescence bloom: crusty, crisp edges
    n = fbm(BW, BW, rng, base=10, octaves=4)
    shape = np.clip(1 - np.sqrt(x ** 2 + (y * 1.3) ** 2) / 0.8, 0, 1)
    cells.append(sstep(0.48, 0.55, n * 0.7 + shape * 0.6) * (0.7 + 0.3 * n) * edge)
    # 13 base algae: bottom-heavy, ragged top
    top = -0.1 + 0.5 * (noise1d(BW, 8, rng)[None, :] - 0.5)
    a = sstep(top - 0.15, top + 0.3, y) * (0.5 + 0.5 * fbm(BW, BW, rng, base=24, octaves=3))
    cells.append(a * edge)
    # 14 repair ghost: soft rectangle with mottle
    rect = np.clip((0.85 - np.abs(x)) / 0.15, 0, 1) * np.clip((0.8 - np.abs(y)) / 0.15, 0, 1)
    cells.append(rect * (0.65 + 0.35 * fbm(BW, BW, rng, base=6, octaves=4)))
    # 15 soft round
    cells.append(np.clip(1 - np.sqrt(x ** 2 + y ** 2), 0, 1) ** 1.5 * (0.8 + 0.2 * fbm(BW, BW, rng, base=8, octaves=3)) * edge)
    return [np.clip(c, 0, 1) for c in cells]


# ------------------------------------------------------------------ strip cells
def strip_cells(rng):
    y = np.linspace(0, 1, HH, dtype=np.float32)[:, None]     # 0 = top edge of the strip
    u = np.linspace(0, 1, HW, dtype=np.float32)[None, :]
    endfade = np.clip(np.minimum(u, 1 - u) / 0.02, 0, 1)
    cells = []
    # 0-1 splash band: dense at the bottom, ragged top with droplets above it
    for k in range(2):
        h = 0.35 + 0.35 * noise1d(HW, 18, rng)[None, :] + 0.1 * noise1d(HW, 120, rng)[None, :]
        body = sstep(h - 0.12, h + 0.18, y)
        n = fbm(HH, HW, rng, base=700, octaves=1, ay=0.125)     # droplets 1-3 cm on a 4 m strip
        drops = sstep(0.82, 0.9, n) * sstep(h - 0.35, h, y) * 0.5
        dens = 0.55 + 0.45 * fbm(HH, HW, rng, base=10, octaves=3, ay=0.125)
        cells.append(union(body * dens, drops) * endfade)
    # 2-3 inside-corner grime: dense at the bottom edge (the corner), fading over the strip
    for k in range(2):
        brk = 0.55 + 0.45 * noise1d(HW, 14 + 10 * k, rng)[None, :]
        fall = np.exp(-(1 - y) / (0.18 + 0.12 * brk))
        streaky = 0.7 + 0.3 * fbm(HH, HW, rng, base=60, octaves=2, ay=0.03)
        cells.append(np.clip(fall * brk * streaky, 0, 1) * endfade)
    # 4-5 worn-edge runs: runs of bites along the arris, half to two thirds of it clean
    for k in range(2):
        runmask = sstep(0.5, 0.62, noise1d(HW, 22 + 8 * k, rng))[None, :]
        wid = 0.12 + 0.25 * noise1d(HW, 90, rng)[None, :] * runmask
        bite = 0.7 + 0.3 * noise1d(HW, 250, rng)[None, :]
        d = np.abs(y - 0.5) / np.maximum(wid * bite, 1e-3)
        cells.append(np.clip(1 - d, 0, 1) ** 0.6 * runmask * endfade)
    # 6 drip-line band under a ledge: dense at the top, hair runs below
    band = np.clip(1 - y / (0.18 + 0.12 * noise1d(HW, 20, rng)[None, :]), 0, 1) ** 0.8
    hairs = np.zeros((HH, HW), np.float32)
    xs = np.sort(rng.uniform(0.01, 0.99, 70))
    for cx in xs:
        L = 0.2 + 0.8 * rng.random() ** 2.5
        w = rng.uniform(0.0008, 0.002)
        prof = np.clip(1 - np.abs(u - cx) / w, 0, 1)
        hairs = np.maximum(hairs, prof * np.clip(1 - y / L, 0, 1) * rng.uniform(0.2, 0.7))
    cells.append(union(band * 0.8, hairs) * endfade)
    # 7 tide mark: damp below a wavy line, a darker salt line at the top
    h = 0.35 + 0.3 * noise1d(HW, 10, rng)[None, :]
    a = sstep(h - 0.05, h + 0.25, y) * 0.55 + np.exp(-((y - h) / 0.03) ** 2) * 0.5
    cells.append(np.clip(a * (0.7 + 0.3 * fbm(HH, HW, rng, base=20, octaves=3, ay=0.125)), 0, 1) * endfade)
    return [np.clip(c, 0, 1) for c in cells]


# ------------------------------------------------------------------ assemble
def normalise(c, target=0.92, q=97):
    """Scale a cell so the core of its mark (the q-th percentile of its covered pixels) sits at
    `target`: the decal's opacity then sets the strength, not the accident of how many soft
    layers the generator multiplied together (round 7: streak cells averaged 0.12-0.2)."""
    m = c[c > 0.02]
    if m.size == 0:
        return c
    return np.clip(c * (target / max(float(np.percentile(m, q)), 1e-3)), 0, 1)


def build_atlas(out_dir, seed=11):
    rng = np.random.default_rng(seed)
    A = np.zeros((4096, 4096), np.float32)
    table = {"size": [4096, 4096], "S": [], "B": [], "H": []}
    sc = [normalise(c) for c in streak_cells(rng)]
    for i, c in enumerate(sc):
        c = c.copy()
        c[:, :3] = 0; c[:, -3:] = 0; c[-4:, :] = 0
        A[0:SH, i * SW:(i + 1) * SW] = c
        cols = np.where(c.max(axis=0) > 0.08)[0]
        fill = (cols[-1] - cols[0] + 1) / SW if len(cols) else 1.0
        table["S"].append({"u0": i / 16, "u1": (i + 1) / 16, "v0": 0.5, "v1": 1.0, "fill": round(float(fill), 3)})
    bc = [normalise(c, 0.88) for c in blotch_cells(rng)]
    for j, c in enumerate(bc):
        col, row = j % 4, j // 4
        A[2048 + row * BW:2048 + (row + 1) * BW, col * BW:(col + 1) * BW] = c
        table["B"].append({"u0": col / 8, "u1": (col + 1) / 8, "v0": 0.5 - (row + 1) / 8, "v1": 0.5 - row / 8})
    hc = [normalise(c, 0.9) if k in (2, 3, 6) else c for k, c in enumerate(strip_cells(rng))]
    for k, c in enumerate(hc):
        A[2048 + k * HH:2048 + (k + 1) * HH, 2048:4096] = c
        table["H"].append({"u0": 0.5, "u1": 1.0, "v0": 0.5 - (k + 1) / 16, "v1": 0.5 - k / 16})
    img = (np.clip(A, 0, 1) * 255 + 0.5).astype(np.uint8)
    p = os.path.join(out_dir, "weather_atlas.png")
    Image.fromarray(img, "L").save(p, optimize=True)
    with open(os.path.join(out_dir, "weather_atlas.json"), "w") as f:
        json.dump(table, f, indent=1)
    return p, table


def build_macro(out_dir, n=1024, seed=5):
    """Tileable value variation: periodic 1/f noise from an inverse FFT, remapped to mean 0.5,
    p1-p99 spread 0.25-0.75 (the wall shader maps it to a ±6 % value change)."""
    rng = np.random.default_rng(seed)
    fy = np.fft.fftfreq(n)[:, None]
    fx = np.fft.fftfreq(n)[None, :]
    f = np.sqrt(fx ** 2 + fy ** 2)
    f[0, 0] = 1.0
    amp = 1.0 / f ** 1.6
    amp[f < 2.0 / n] = 0          # nothing larger than half a tile
    amp[f > 0.12] *= 0.15         # little fine grain; the spray tile carries that
    ph = rng.random((n, n)) * 2 * np.pi
    img = np.real(np.fft.ifft2(amp * np.exp(1j * ph)))
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    img = 0.25 + 0.5 * (img - lo) / (hi - lo)
    p = os.path.join(out_dir, "macro_var.png")
    Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "L").save(p, optimize=True)
    return p


def build_all(out_dir):
    a, table = build_atlas(out_dir)
    m = build_macro(out_dir)
    return {"atlas": a, "macro": m, "fills": [c["fill"] for c in table["S"]]}


if __name__ == "__main__":
    print(build_all(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "tex")))
