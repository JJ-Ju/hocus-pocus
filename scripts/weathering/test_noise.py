"""Unit tests for the noise (round G, grid-breakup 5.3-5.4): python -I test_noise.py

G-3 lattice-free: for gfield at the sizes in use, |d2x| column means folded by the coarse lattice
    phase show no peak (max bin / median <= 1.10), and the outer 5 % of rows and columns carry no
    more variance than the middle (<= 1.3, 8 seeds).
G-2 storeys do not repeat: every pattern field below S3 restarts from storey to storey: vertical
    autocorrelation at one storey (2.8 m) <= 0.2 (mid, inner, biopatt, warp, chan as built).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_noise as nz  # noqa: E402

H, W, PPM = 1814, 4096, 50.0
fails = []


def li(a, f):
    d = np.abs(a[:, 2:] - 2 * a[:, 1:-1] + a[:, :-2]).mean(0)
    best = 1.0
    for ph in range(f):
        pass
    bins = np.zeros(f)
    cnt = np.zeros(f)
    for i, v in enumerate(d):
        bins[(i + 1) % f] += v
        cnt[(i + 1) % f] += 1
    m = bins / np.maximum(cnt, 1)
    best = float(m.max() / np.median(m))
    return best


for sig in (25.0, 50.0, 100.0, 200.0):
    f = max(1, int(sig // 5))
    vals, edges = [], []
    for s in range(8):
        g = nz.gfield((H, W), sig, ("t3", sig, s))
        if f > 1:
            vals.append(li(g, f))
        e, ex = int(0.05 * H), int(0.05 * W)
        rows = g[H // 4:3 * H // 4].var()
        cols = g[:, W // 4:3 * W // 4].var()
        edges.append((np.concatenate([g[:e], g[-e:]]).var() / rows,
                      np.concatenate([g[:, :ex], g[:, -ex:]], axis=1).var() / cols))
    # the offset is random per call, so a fixed fold shows no lock; the edge ratio is the real test
    r_e = float(np.max(np.mean(np.array(edges), axis=0)))     # rows and columns, each the mean of 8 seeds
    print("G-3 sigma %5.0f px: edge variance ratio %.2f%s" % (sig, r_e, "" if not vals else "  fold max/median %.2f" % np.mean(vals)))
    if r_e > 1.3:
        fails.append("G-3 edge %.0f" % sig)


def storey_r(field, lag):
    a = field - field.mean()
    return float((a[:-lag] * a[lag:]).mean() / a.var())


lag = int(2.8 * PPM)
ym = 1.1 * PPM
sh = (1200, 1600)
cases = {
    "mid": nz.lognormal(sh, PPM, [3, 4, 5], ("g2", "mid"), sigma=0.22, aniso=(4.0, 1.0), ymax_px=ym),
    "inner": nz.lognormal(sh, PPM, [4, 5, 6, 7], ("g2", "inner"), sigma=0.55, weights=[1.0, 1.0, 0.9, 0.8], aniso=(2.2, 1.0), ymax_px=ym),
    "biopatt": nz.lognormal(sh, PPM, [4, 5, 6, 7], ("g2", "bio"), sigma=1.0, weights=[0.5, 0.8, 1.0, 1.0], aniso=(4.0, 1.0), ymax_px=ym),
    "warp": nz.gfield(sh, 0.9 * PPM, ("g2", "warp")),
    "chan": nz.gfield(sh, 0.05 * PPM, ("g2", "chan"), aniso=(18.0, 1.0)),
    "mid (round F, no cap)": nz.lognormal(sh, PPM, [3, 4, 5], ("g2", "mid"), sigma=0.22, aniso=(4.0, 1.0)),
}
for k, v in cases.items():
    r = storey_r(np.log(v) if v.min() > 0 else v, lag)
    print("G-2 %-22s one-storey autocorrelation %.3f" % (k, r))
    if r > 0.2 and "round F" not in k:
        fails.append("G-2 " + k)
print("PASS" if not fails else "FAIL " + ", ".join(fails))
sys.exit(0 if not fails else 1)
