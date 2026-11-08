"""wx_detail.py - high-resolution detail for the weathering layers (round I).

The facade-space generator decides where weathering goes and how much, at 50 px/m. Up close, the
look comes from tileable detail textures at about 1000 px/m. They are sampled without visible
repetition and blended so the macro amount is kept: the engine's layered material, mirrored in
numpy for the review images.

- Tiles are synthesised by spectrum (the inverse FFT of a shaped random spectrum), so they tile
  exactly. They are stored equalised (uniform histogram, `u`) and Gaussianised (`g`), so a
  coverage threshold at 1 - m covers exactly m.
- Hex tiling with a histogram-preserving blend (Heitz and Neyret 2018; Mikkelsen 2022): a
  triangle grid gives each pixel three vertices. Each vertex takes a random offset into the tile,
  and a random rotation or flip where the texture allows. The three samples blend in Gaussian
  space with weights w / sqrt(sum w^2), which keeps the tile's histogram, so no tile period shows
  and coverage thresholds stay exact.
- Refinement (see refine_cover and refine_film): a low-res alpha upsampled to the fine grid takes
  its edges and inner structure from the detail texture while keeping its mean.
"""
import numpy as np

F32 = np.float32


# ---------------------------------------------------------------------------------------------
# normal distribution (no scipy)

_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
      -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
      -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
      4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)


def norm_ppf(p):
    """Inverse standard normal CDF (Acklam's approximation, relative error < 1.2e-9)."""
    p = np.clip(np.asarray(p, np.float64), 1e-12, 1 - 1e-12)
    x = np.empty_like(p)
    lo, hi = p < 0.02425, p > 1 - 0.02425
    mid = ~(lo | hi)
    q = p[mid] - 0.5
    r = q * q
    x[mid] = ((((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q /
              (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1))
    for sel, sgn, pp in ((lo, 1.0, p[lo]), (hi, -1.0, 1 - p[hi])):
        q = np.sqrt(-2 * np.log(pp))
        x[sel] = sgn * ((((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) /
                        ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1))
    return x


def norm_cdf(x):
    """Standard normal CDF (Abramowitz and Stegun 7.1.26, |error| < 1.5e-7)."""
    x = np.asarray(x, np.float64)
    z = np.abs(x) / np.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * y)


# ---------------------------------------------------------------------------------------------
# hashing and tile synthesis

def _seed(*keys):
    import hashlib
    h = hashlib.blake2b(repr(keys).encode(), digest_size=8).digest()
    return int.from_bytes(h, "little")


def rng(*keys):
    return np.random.default_rng(_seed(*keys))


def hash_u32(i, j, salt):
    """Integer hash of lattice coordinates (vectorised): uint32."""
    with np.errstate(over="ignore"):
        x = (np.asarray(i, np.int64).astype(np.uint32) * np.uint32(0x8DA6B343)) ^ \
            (np.asarray(j, np.int64).astype(np.uint32) * np.uint32(0xD8163841)) ^ np.uint32(salt & 0xFFFFFFFF)
        x ^= x >> np.uint32(16)
        x *= np.uint32(0x7FEB352D)
        x ^= x >> np.uint32(15)
        x *= np.uint32(0x846CA68B)
        x ^= x >> np.uint32(16)
    return x


def hash01(i, j, salt):
    return hash_u32(i, j, salt).astype(np.float64) / 4294967296.0


def spectral(ny, nx, ell_y, ell_x, beta, key):
    """Tileable Gaussian field (ny, nx), zero mean, unit std: power spectrum (1 + (2 pi k ell)^2)^(-beta/2)
    with correlation lengths ell_y, ell_x in pixels (anisotropic when they differ)."""
    g = rng("spectral", key)
    ky = np.fft.fftfreq(ny)[:, None]
    kx = np.fft.rfftfreq(nx)[None, :]
    r2 = (2 * np.pi * ky * ell_y) ** 2 + (2 * np.pi * kx * ell_x) ** 2
    amp = (1.0 + r2) ** (-beta / 4.0)
    amp[0, 0] = 0.0
    Z = g.standard_normal(amp.shape) + 1j * g.standard_normal(amp.shape)
    f = np.fft.irfft2(amp * Z, s=(ny, nx))
    return ((f - f.mean()) / max(f.std(), 1e-12)).astype(F32)


def circ_conv(a, k):
    """Circular convolution of a tile with a small kernel (FFT): keeps the tile seamless."""
    ny, nx = a.shape
    K = np.zeros((ny, nx), np.float64)
    kh, kw = k.shape
    K[:kh, :kw] = k
    K = np.roll(K, (-(kh // 2), -(kw // 2)), axis=(0, 1))
    return np.fft.irfft2(np.fft.rfft2(a) * np.fft.rfft2(K), s=(ny, nx)).astype(F32)


def disc_kernel(r_px, soft=0.8):
    n = int(np.ceil(r_px + 2 * soft + 1))
    y, x = np.mgrid[-n:n + 1, -n:n + 1]
    d = np.sqrt(x * x + y * y)
    return np.clip((r_px + soft - d) / (2 * soft), 0, 1)


def splats(ny, nx, density, r_min, r_max, slope, key, aspect=1.0, cluster=None):
    """Tileable field of soft discs: `density` per pixel^2 of area, radii from a power law
    (pdf ~ r^-slope) between r_min and r_max px. `cluster`: an optional (ny, nx) weight field in
    0-1 that thins the points (Thomas-like clustering when it is a thresholded noise)."""
    g = rng("splats", key)
    n = int(density * ny * nx)
    ys = g.uniform(0, ny, n)
    xs = g.uniform(0, nx, n)
    if cluster is not None:
        keep = g.uniform(0, 1, n) < cluster[ys.astype(int) % ny, xs.astype(int) % nx]
        ys, xs = ys[keep], xs[keep]
        n = ys.size
    u = g.uniform(0, 1, n)
    if abs(slope - 1.0) < 1e-6:
        r = r_min * (r_max / r_min) ** u
    else:
        a, b = r_min ** (1 - slope), r_max ** (1 - slope)
        r = (a + u * (b - a)) ** (1.0 / (1 - slope))
    out = np.zeros((ny, nx), F32)
    edges = np.geomspace(r_min, r_max * 1.0001, 9)
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (r >= lo) & (r < hi)
        if not sel.any():
            continue
        imp = np.zeros((ny, nx), F32)
        np.add.at(imp, (ys[sel].astype(int) % ny, xs[sel].astype(int) % nx), 1.0)
        k = disc_kernel(0.5 * (lo + hi))
        if aspect != 1.0:
            from PIL import Image
            kh = max(3, int(round(k.shape[0] * aspect)) | 1)
            k = np.asarray(Image.fromarray((k * 255).astype(np.uint8)).resize((k.shape[1], kh), Image.BILINEAR), F32) / 255.0
        out = np.maximum(out, np.clip(circ_conv(imp, k), 0, 1))
    return out


def worley(ny, nx, cells_y, cells_x, key):
    """Tileable cellular noise: distance to the nearest feature point (F1) and the cell id of that
    point, on a jittered grid of cells_y x cells_x cells."""
    g = rng("worley", key)
    py = (np.arange(cells_y)[:, None] + g.uniform(0, 1, (cells_y, cells_x))) * (ny / cells_y)
    px = (np.arange(cells_x)[None, :] + g.uniform(0, 1, (cells_y, cells_x))) * (nx / cells_x)
    yy, xx = np.mgrid[0:ny, 0:nx].astype(F32)
    cy = (yy * cells_y / ny).astype(int)
    cx = (xx * cells_x / nx).astype(int)
    best = np.full((ny, nx), np.inf, F32)
    bid = np.zeros((ny, nx), np.int64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            jy, jx = (cy + dy) % cells_y, (cx + dx) % cells_x
            qy = py[jy, jx] + np.where(cy + dy < 0, -ny, np.where(cy + dy >= cells_y, ny, 0))
            qx = px[jy, jx] + np.where(cx + dx < 0, -nx, np.where(cx + dx >= cells_x, nx, 0))
            d = np.sqrt((qy - yy) ** 2 + (qx - xx) ** 2)
            closer = d < best
            best = np.where(closer, d, best)
            bid = np.where(closer, jy * cells_x + jx, bid)
    return best, bid


def equalize(a):
    """Rank transform to a uniform histogram in (0, 1)."""
    f = a.ravel()
    order = np.argsort(f, kind="stable")
    u = np.empty(f.size, F32)
    u[order] = (np.arange(f.size, dtype=np.float64) + 0.5) / f.size
    return u.reshape(a.shape)


class Tile:
    """A detail tile: `u` (uniform), `g` (Gaussian) of the same pattern, size in metres (w, h),
    and whether it may be rotated (isotropic) or only flipped left-right (anisotropic).
    Coarser levels (box-filtered by 2, 4, 8, re-standardised) serve sampling below the tile's own
    density, so a coverage threshold stays exact at every texel density."""

    def __init__(self, name, field, w_m, h_m, rotate=True, extra=None):
        self.name = name
        self.u = equalize(field)
        self.g = norm_ppf(self.u).astype(F32)
        self.w_m, self.h_m = w_m, h_m
        self.rotate = rotate
        self.extra = extra or {}
        self._lv = {}

    @property
    def ppm(self):
        return self.u.shape[1] / self.w_m

    def level(self, ppm_out):
        """(g, factor): the Gaussian field at the coarsest level still at or above ppm_out."""
        f = 1
        while self.ppm / (2 * f) >= ppm_out and min(self.g.shape) // (2 * f) >= 64:
            f *= 2
        if f == 1:
            return self.g, 1
        if f not in self._lv:
            g = self.g
            ny, nx = (g.shape[0] // f) * f, (g.shape[1] // f) * f
            c = g[:ny, :nx].reshape(ny // f, f, nx // f, f).mean(axis=(1, 3))
            self._lv[f] = ((c - c.mean()) / max(c.std(), 1e-9)).astype(F32)
        return self._lv[f], f


# ---------------------------------------------------------------------------------------------
# sampling

def bilinear_wrap(t, ty, tx):
    """Bilinear sample of a tile (ny, nx[, c]) at fractional pixel coordinates, wrapping."""
    ny, nx = t.shape[:2]
    y0 = np.floor(ty).astype(np.int64)
    x0 = np.floor(tx).astype(np.int64)
    fy = (ty - y0).astype(F32)
    fx = (tx - x0).astype(F32)
    y0 %= ny
    x0 %= nx
    y1 = (y0 + 1) % ny
    x1 = (x0 + 1) % nx
    if t.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    return ((t[y0, x0] * (1 - fx) + t[y0, x1] * fx) * (1 - fy) + (t[y1, x0] * (1 - fx) + t[y1, x1] * fx) * fy)


def tri_grid(X, Y, cell_m):
    """Triangle (simplex) grid of cell size cell_m metres: three lattice vertices per point and their
    barycentric weights (Heitz and Neyret 2018)."""
    u = X / cell_m
    v = Y / cell_m
    su = u - 0.57735027 * v                       # skew to the equilateral lattice (column-major as in the
    sv = 1.15470054 * v                           # reference: x' = x - y/sqrt3, y' = 2y/sqrt3)
    bu, bv = np.floor(su), np.floor(sv)
    fu, fv = su - bu, sv - bv
    fz = 1.0 - fu - fv
    lower = fz > 0
    w1 = np.where(lower, fz, -fz)
    w2 = np.where(lower, fv, 1.0 - fv)            # round I fix: the upper triangle's weights were swapped
    w3 = np.where(lower, fu, 1.0 - fu)            # (1-fu, 1-fv), a jump of up to 0.73 along every edge
    v1 = (np.where(lower, bu, bu + 1), np.where(lower, bv, bv + 1))
    v2 = (np.where(lower, bu, bu + 1), np.where(lower, bv + 1, bv))
    v3 = (np.where(lower, bu + 1, bu), np.where(lower, bv, bv + 1))
    return (v1, v2, v3), (w1, w2, w3)


def _vertex_xform(vi, shape, w_m, h_m, rotate, salt, X, Y):
    """Texture pixel coordinates for one lattice vertex: random offset; rotation by a random angle
    for isotropic tiles, a random left-right flip for the others."""
    i, j = vi
    ny, nx = shape
    ox = hash01(i, j, salt) * nx
    oy = hash01(i, j, salt ^ 0x5BD1E995) * ny
    ppm_x, ppm_y = nx / w_m, ny / h_m
    if rotate:
        th = hash01(i, j, salt ^ 0x27D4EB2F) * 2 * np.pi
        c, s = np.cos(th), np.sin(th)
        xr, yr = c * X - s * Y, s * X + c * Y
    else:
        flip = np.where(hash01(i, j, salt ^ 0x165667B1) < 0.5, -1.0, 1.0)
        xr, yr = flip * X, Y
    return yr * ppm_y + oy, xr * ppm_x + ox


def hex_g(tile, X, Y, cell_m, salt, sharp=2.0, ppm_out=None):
    """Histogram-preserving hex-tiled sample of a tile's Gaussian field at facade metres X, Y.
    Returns the blended Gaussian value (mean 0, std 1 wherever the three samples are independent).
    ppm_out picks the tile level for the output density (no aliasing below the tile's own)."""
    g, f = tile.level(ppm_out) if ppm_out else (tile.g, 1)
    verts, ws = tri_grid(X, Y, cell_m)
    num = 0.0
    den = 0.0
    for vi, w in zip(verts, ws):
        w = np.power(np.maximum(w, 0.0), sharp)
        ty, tx = _vertex_xform(vi, g.shape, tile.w_m, tile.h_m, tile.rotate, salt, X, Y)
        num = num + w * bilinear_wrap(g, ty, tx)
        den = den + w * w
    return (num / np.sqrt(np.maximum(den, 1e-12))).astype(F32)


def hex_u(tile, X, Y, cell_m, salt, sharp=2.0, ppm_out=None):
    """As hex_g, mapped back to a uniform histogram (0-1)."""
    return norm_cdf(hex_g(tile, X, Y, cell_m, salt, sharp, ppm_out)).astype(F32)


def band_g(tile, X, Y, band_m, salt, sharp=2.0, ppm_out=None):
    """For vertically anisotropic tiles (streaks): offsets per vertical band band_m wide, blended
    across bands only (variance-preserving), so no seam ever cuts a streak horizontally."""
    g, f = tile.level(ppm_out) if ppm_out else (tile.g, 1)
    b = X / band_m
    i0 = np.floor(b)
    t = b - i0
    ny, nx = g.shape
    num = 0.0
    den = 0.0
    for i, w in ((i0, 1.0 - t), (i0 + 1, t)):
        w = np.power(np.maximum(w, 0.0), sharp)
        ox = hash01(i, 0, salt) * nx
        oy = hash01(i, 0, salt ^ 0x5BD1E995) * ny
        flip = np.where(hash01(i, 0, salt ^ 0x165667B1) < 0.5, -1.0, 1.0)
        tx = flip * X * (nx / tile.w_m) + ox
        ty = Y * (ny / tile.h_m) + oy
        num = num + w * bilinear_wrap(g, ty, tx)
        den = den + w * w
    return (num / np.sqrt(np.maximum(den, 1e-12))).astype(F32)


def hex_multi(stack, w_m, h_m, X, Y, cell_m, salt, sharp=2.0, rotate=True, gaussian=True, vec=()):
    """Hex-tiled sample of a multi-channel tile (ny, nx, c), every channel with the same vertex
    transforms. gaussian=True: channels are standardised fields, blended variance-preserving
    (Heitz and Neyret); False: plain normalised weights (for appearance maps already filtered).
    vec: channel pairs (ix, iy) holding a slope (d/dx, d/dy), turned with each sample's rotation or
    flip, so lighting can blend slopes instead of heights (no creases along the cell edges)."""
    verts, ws = tri_grid(X, Y, cell_m)
    num = 0.0
    den = 0.0
    for vi, w in zip(verts, ws):
        w = np.power(np.maximum(w, 0.0), sharp)[..., None]
        ty, tx = _vertex_xform(vi, stack.shape[:2], w_m, h_m, rotate, salt, X, Y)
        v = bilinear_wrap(stack, ty, tx)
        if vec:
            i, j = vi
            if rotate:
                th = hash01(i, j, salt ^ 0x27D4EB2F) * 2 * np.pi
                c, sn = np.cos(th), np.sin(th)
            else:
                c = np.where(hash01(i, j, salt ^ 0x165667B1) < 0.5, -1.0, 1.0)
                sn = 0.0
            v = v.copy()
            for ix, iy in vec:
                gx, gy = v[..., ix].copy(), v[..., iy].copy()
                if rotate:
                    v[..., ix] = gx * c + gy * sn
                    v[..., iy] = -gx * sn + gy * c
                else:
                    v[..., ix] = gx * c
        num = num + w * v
        den = den + (w * w if gaussian else w)
    return (num / (np.sqrt(np.maximum(den, 1e-12)) if gaussian else np.maximum(den, 1e-12))).astype(F32)


def hex_rgb(t, w_m, h_m, X, Y, cell_m, salt, exp=7.0, contrast=0.6, rotate=True):
    """Hex-tiled sample of a colour tile (Mikkelsen 2022): barycentric weights to a power, scaled by
    each sample's luminance so the brighter structure wins at the seams."""
    verts, ws = tri_grid(X, Y, cell_m)
    cs, Ws = [], []
    for vi, w in zip(verts, ws):
        ty, tx = _vertex_xform(vi, t.shape[:2], w_m, h_m, rotate, salt, X, Y)
        c = bilinear_wrap(t, ty, tx)
        lum = c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
        cs.append(c)
        Ws.append((1.0 - contrast + contrast * lum) * np.power(np.maximum(w, 0.0), exp))
    S = Ws[0] + Ws[1] + Ws[2] + 1e-12
    return ((cs[0] * Ws[0][..., None] + cs[1] * Ws[1][..., None] + cs[2] * Ws[2][..., None]) / S[..., None]).astype(F32)


# ---------------------------------------------------------------------------------------------
# refinement of a coarse alpha by a detail field

def refine_cover(a_up, peak, u, w):
    """Coverage-preserving refinement: a coarse alpha `a_up` (upsampled) whose local peak opacity is
    `peak` becomes spots of that opacity where the detail `u` (uniform 0-1) is above 1 - a/peak, with a
    transition up to `w` wide that narrows toward m = 0 and 1, so the mean over the detail equals a_up
    exactly and a zero mask stays zero."""
    m = np.clip(a_up / np.maximum(peak, 1e-6), 0.0, 1.0)
    hw = np.maximum(np.minimum(np.minimum(0.5 * w, m), 1.0 - m), 5e-5)   # half-width: w/2, narrowing at m = 0 and 1
    return (peak * np.clip((u - (1.0 - m)) / (2.0 * hw) + 0.5, 0.0, 1.0)).astype(F32)   # mean m exactly; 0 stays 0


def refine_film(a_up, g, k):
    """Mean-preserving modulation of a translucent film by a Gaussian detail g: a (1 + k g), floored
    at 0 (k up to about 0.4 keeps the floor rare)."""
    return (a_up * np.maximum(1.0 + k * g, 0.0)).astype(F32)
