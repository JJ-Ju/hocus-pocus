"""painterly_metrics.py - candidate painterly checks from round C (not part of frame_critique.py).

Usage (hython, for numpy and PIL):  hython painterly_metrics.py image.jpg@horizon [...]
  horizon = horizon height in the frame, 0 bottom 1 top (sky is searched above it).
Prints per image: flat3 (share of non-sky pixels with 3x3 L* std < 1), peak3 (share within
+-4 L* of the three strongest L* histogram peaks), L* p1 (black floor), mean b* and hue of the
darkest and lightest non-sky quartiles, shadow chroma, sky chroma, sky top-minus-bottom L*
(unreliable: clouds and the crude sky mask disturb it).
See .claude/skills/procedural-materials/references/stylisation-anime.md section 5.
"""
import sys, numpy as np
from PIL import Image
def lab(x):
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)
def box(a, r):
    k = 2 * r + 1; p = np.pad(a, r, mode="edge"); c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
print("name | flat3 | peak3 | L_p1 | shadow_b | lit_b | shadow_hue | lit_hue | dHue | shadow_C | sky_C | sky_dL(top-bottom)")
for spec in sys.argv[1:]:
    path, hz = spec.split("@"); hz = float(hz)
    im = Image.open(path).convert("RGB"); im = im.resize((1024, int(1024 * im.size[1] / im.size[0])))
    x = np.asarray(im).astype(np.float64) / 255.0; L = lab(x); H, W = L.shape[:2]
    rows = np.arange(H)[:, None] / H
    sky = ((x[..., 2] - x[..., 0]) > 0.03) & (L[..., 0] > 45) & (rows < (1 - hz))
    sky |= (L[..., 0] > 75) & (np.hypot(L[..., 1], L[..., 2]) < 12) & (rows < (1 - hz) * 0.6) & ((x[..., 2] - x[..., 0]) > 0.0)
    ns = ~sky
    l = L[..., 0]
    sd = np.sqrt(np.maximum(box(l * l, 1) - box(l, 1) ** 2, 0))
    flat = (sd < 1.0)[ns].mean()
    hist, _ = np.histogram(l[ns], bins=100, range=(0, 100)); hs = np.convolve(hist, np.ones(3) / 3, "same")
    peaks = [i for i in range(1, 99) if hs[i] >= hs[i - 1] and hs[i] >= hs[i + 1]]
    peaks = sorted(peaks, key=lambda i: -hs[i])[:3]
    near = np.zeros(100, bool)
    for p in peaks: near[max(0, p - 4):p + 5] = True
    peak3 = hist[near].sum() / hist.sum()
    q25, q75 = np.percentile(l[ns], [25, 75])
    sh = ns & (l <= q25); li = ns & (l >= q75)
    hue = lambda m: (np.degrees(np.arctan2(L[..., 2][m].mean(), L[..., 1][m].mean())) % 360)
    C = np.hypot(L[..., 1], L[..., 2])
    skyC = C[sky].mean() if sky.any() else float("nan")
    if sky.sum() > 100:
        ys = np.where(sky)[0]; top = sky & (rows < np.percentile(ys, 20) / H); bot = sky & (rows > np.percentile(ys, 80) / H)
        sdl = l[top].mean() - l[bot].mean()
    else: sdl = float("nan")
    dh = (hue(sh) - hue(li) + 180) % 360 - 180
    print("%s | %.3f | %.3f | %.1f | %.1f | %.1f | %.0f | %.0f | %+.0f | %.1f | %.1f | %+.1f" % (path.split("/")[-1].split("\\")[-1], flat, peak3, np.percentile(l[ns], 1), L[..., 2][sh].mean(), L[..., 2][li].mean(), hue(sh), hue(li), dh, C[sh].mean(), skyC, sdl))
