"""wx_concrete.py - the concrete under the paint, as tiling detail for the texture stage (round J).

The danchi's walls are painted all over, so concrete shows only where the paint failed (peeling,
chips) or the wall broke (spalls), and through the paint as its larger surface voids (bugholes). The
user's round-I note asked for faint flecks of darker, cooler aggregate, unevenly mixed paste, pits
about 1 cm wide, and paint that cracks, chips and peels to show the concrete below.

Two 1.024 m tiles at 1 mm per pixel (tileable: every field is periodic):
  formed  the cast face under the paint: paste mottled at 4 and 20 cm with a cool/warm drift, sand
          flecks (dark cool andesite and chert, light quartz and feldspar, a few iron-stained), coarse
          aggregate only as faint ghosts under the paste skin, and surface voids;
  broken  a fracture through the concrete (spalls): coarse aggregate cut through, 30-40 % of the
          area, in its own tones, set in a rougher paste.
Each tile holds an albedo multiplier (RGB, mean 1), a height (m) and a cavity (0-1). `pits` is the
voids alone: what survives the 1-3 mm spray coat (the voids from about 5 mm up, shallower), for the
painted wall.

Engine: the same tiles ship as tiling texture sets (base colour multiplier, height or normal, AO), sampled
with the coat's hex tiling and revealed by the peeling and damage masks.
"""
import os

import numpy as np

import wx_detail as wd

F32 = np.float32
N = 1024
TILE_M = 1.024

# surface voids (bugholes) on the cast face: diameters 3-14 mm on a power law, clustered (air rises
# along the formwork in each lift); the research sets the share (CON_VOID_SHARE). Depth about 0.4 x radius.
VOID_R_PX = (0.5, 12.0)      # J6: 1-24 mm across (research coatings §1: ACI up to 25 mm, mostly <= 15)
VOID_SLOPE = 3.35            # N(>d) ~ d^-2.2: about 4,000 per m2 >= 1 mm, 90-140 >= 5 mm, 16-35 >= 10 mm at 1.5 %
VOID_DENS = 0.58e-2          # per mm^2 before clustering (about 40 % kept): about 1.5 % of the face (JCI 1.25-1.82 %)
PAINT_VOID_SHARE = 0.009     # J6: through the spray coat only dimples from 5 mm, a few % of the bare count
PAINT_VOID_MIN_PX = 2.5      # through the spray coat: voids from 5 mm across stay visible (filler hides < 3 mm)
PAINT_VOID_DEPTH = 0.55      # and keep this share of their depth


def _splat_set(density, r0, r1, slope, key, cluster=None):
    return wd.splats(N, N, density, r0, r1, slope, key, cluster=cluster)


def _void_field(key, rmin=None, dens=None):
    """Coverage of the voids (0-1) and their depth (m)."""
    cl = wd.norm_cdf(wd.spectral(N, N, 180, 260, 3.0, key + "_vcl"))
    cl = np.clip((cl - 0.35) / 0.45, 0, 1) ** 1.5
    r0 = VOID_R_PX[0] if rmin is None else rmin
    cov = _splat_set(VOID_DENS if dens is None else dens, r0, VOID_R_PX[1], VOID_SLOPE, key + "_voids", cluster=cl)
    # bowl profile: the splat's soft coverage stands in for the radius profile
    depth = 0.0012 + 0.0022 * wd.norm_cdf(wd.spectral(N, N, 6, 6, 2.0, key + "_vd"))
    return cov.astype(F32), (cov ** 1.5 * depth).astype(F32)


def make(kind):
    """kind: 'formed', 'broken' or 'pits'. Returns (N, N, 5): albedo multiplier RGB, height (m), cavity."""
    S = wd.spectral
    k = "conc_" + kind
    if kind == "pits":
        cov, dep = _void_field("conc_paint", rmin=PAINT_VOID_MIN_PX, dens=PAINT_VOID_SHARE * VOID_DENS)
        cav = np.clip(cov * 0.8, 0, 1)
        mult = np.ones((N, N, 3), F32) * (1.0 - 0.12 * cav)[..., None]   # shadow and dust in the dimple
        return np.dstack([mult, -PAINT_VOID_DEPTH * dep, cav]).astype(F32)
    m1 = S(N, N, 40, 40, 3.0, k + "_m1")
    m2 = S(N, N, 200, 200, 3.0, k + "_m2")
    tw = S(N, N, 120, 120, 3.0, k + "_tw")                    # cool / warm drift of the paste
    sat = S(N, N, 300, 300, 3.0, k + "_sat")                  # saturation drift (unevenly mixed)
    L = 1.0 + 0.035 * m1 + 0.05 * m2
    mult = np.stack([L * (1 + 0.012 * tw + 0.010 * sat), L * (1 + 0.002 * sat), L * (1 - 0.014 * tw - 0.012 * sat)], -1)
    h = 0.00008 * S(N, N, 1.5, 1.5, 2.0, k + "_hr")           # paste micro relief
    cav = np.zeros((N, N), F32)
    fine = 1.0 if kind == "broken" else 0.70                   # the paste skin hides part of the sand
    flecks = (("dark", 0.0040, 0.4, 1.3, (0.56, 0.59, 0.67)),   # andesite, chert: darker and cooler
              ("light", 0.0030, 0.4, 1.0, (1.14, 1.13, 1.10)),  # quartz, feldspar
              ("warm", 0.0008, 0.4, 1.0, (1.07, 0.97, 0.86)))   # iron-stained sand
    for name, dens, r0, r1, c in flecks:
        cov = _splat_set(dens * fine, r0, r1, 2.2, k + "_" + name)
        mult = mult * (1.0 + (np.array(c, F32) - 1.0) * cov[..., None])
        h = h + 0.0002 * cov
    if kind == "formed":
        peb = _splat_set(4.5e-4, 2.5, 12.0, 2.4, k + "_peb")    # J6: aggregate shadows 5-25 mm, 2-8 % cover,
        mult = mult * (1.0 + (np.array((0.955, 0.958, 0.972), F32) - 1.0) * peb[..., None])   # dL* -1 to -4, cooler
        vc, vd = _void_field(k)
        mult = mult * (1.0 - 0.30 * vc)[..., None]              # the void's shadow and the dust in it
        h = h - vd
        cav = np.maximum(cav, 0.9 * vc)
    else:
        # fracture: coarse aggregate cut through, each stone its own tone (andesite greys, a few warm)
        ny = nx = N
        g = wd.rng("conc", k, "stones")
        n = int(0.0040 * ny * nx)                                 # about 35 % of a fracture is stone (Gmax 20 mm)
        ys, xs = g.uniform(0, ny, n), g.uniform(0, nx, n)
        u = g.uniform(0, 1, n)
        r = 2.5 * (10.0 / 2.5) ** u                                # radii 2.5-10 mm, log-uniform
        kind_ = g.uniform(0, 1, n)
        grey = np.array([0.96, 0.98, 1.03])[None, :] * g.uniform(0.55, 0.95, n)[:, None]   # andesite, darker than the paste
        grey = grey * (1.0 + 0.012 * g.standard_normal((n, 3)))
        warm = np.array([0.86, 0.77, 0.66])[None, :] * g.uniform(0.85, 1.15, n)[:, None]
        white = np.array([1.18, 1.18, 1.16])[None, :] * g.uniform(0.95, 1.05, n)[:, None]
        tones = np.where((kind_ < 0.75)[:, None], grey, np.where((kind_ < 0.90)[:, None], warm, white))
        relief = g.uniform(-0.0012, 0.0010, n)
        srel = np.zeros((ny, nx), F32)
        stone = np.zeros((ny, nx), F32)
        col = np.ones((ny, nx, 3), F32)
        order = np.argsort(-r)
        for i in order:
            rr = r[i]
            y0, x0 = ys[i], xs[i]
            nn = int(np.ceil(rr + 2))
            yy, xx = np.mgrid[-nn:nn + 1, -nn:nn + 1]
            nv = g.integers(5, 9)                                # an angular stone: a random polygon
            th = np.sort(g.uniform(0, 2 * np.pi, nv))
            rv = rr * g.uniform(0.65, 1.0, nv)
            px_, py_ = rv * np.cos(th), rv * np.sin(th)
            X_, Y_ = xx - (x0 % 1), yy - (y0 % 1)
            sd = np.full(X_.shape, -np.inf)                       # signed distance inside (convex hull of the vertices)
            for j in range(nv):
                ax_, ay_ = px_[j], py_[j]
                bx_, by_ = px_[(j + 1) % nv], py_[(j + 1) % nv]
                ex_, ey_ = bx_ - ax_, by_ - ay_
                ln = max(np.hypot(ex_, ey_), 1e-6)
                d_ = ((X_ - ax_) * ey_ - (Y_ - ay_) * ex_) / ln       # > 0 outside this edge (counter-clockwise)
                sd = np.maximum(sd, d_)
            cov = np.clip(0.6 - sd, 0, 1)
            iy = (int(y0) + yy) % ny
            ix = (int(x0) + xx) % nx
            upd = cov > stone[iy, ix]
            stone[iy, ix] = np.where(upd, cov, stone[iy, ix])
            col[iy, ix] = np.where(upd[..., None], tones[i], col[iy, ix])
            srel[iy, ix] = np.where(upd, relief[i] * cov, srel[iy, ix])
        mult = mult * (1.0 + (col - 1.0) * stone[..., None])
        mult = mult * np.array([1.06, 1.05, 1.02], F32)            # fracture paste: light, a little warm
        h = h * (1.0 - 0.7 * stone) + 0.0015 * S(N, N, 25, 25, 2.5, k + "_hb") + srel   # stone faces smoother
        cav = np.maximum(cav, 0.5 * np.clip(-S(N, N, 4, 4, 2.0, k + "_cb") - 1.2, 0, 1))
    mult = mult / mult.reshape(-1, 3).mean(0)                  # mean 1: the masks keep the amounts
    return np.dstack([mult, h, cav]).astype(F32)


_C = {}


def stack(kind, cache):
    if kind not in _C:
        os.makedirs(cache, exist_ok=True)
        fn = os.path.join(cache, "conc_%s_v9.npy" % kind)
        if os.path.exists(fn):
            _C[kind] = np.load(fn)
        else:
            _C[kind] = make(kind)
            np.save(fn, _C[kind])
    return _C[kind]


def sample(kind, XX, YY, salt, cache, ppm=None):
    """The tile at facade metres (hex-tiled, sharp blend: flecks and voids stay crisp)."""
    st = stack(kind, cache)
    if ppm is not None and ppm < 500:                          # box level for coarser output
        f = 1
        while (N / TILE_M) / (2 * f) >= ppm and N // (2 * f) >= 64:
            f *= 2
        if f > 1:
            st = st.reshape(N // f, f, N // f, f, -1).mean(axis=(1, 3))
    return wd.hex_multi(st, TILE_M, TILE_M, XX, YY, 0.35, salt, sharp=7.0, gaussian=False)
