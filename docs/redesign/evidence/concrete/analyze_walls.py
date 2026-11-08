"""analyze_walls.py - why the walls read as stucco: grain statistics of wall crops from renders
and from real danchi photos (plain Python 3 + numpy + Pillow).

    python analyze_walls.py <refs_dir> <out_dir>

For each crop of a plain wall (no windows, rails or edges) it measures, on CIE L*:
- slope: the amplitude-spectrum slope between 3 and 48 px wavelength (natural images about
  -1; a flatter, less negative slope means the fine grain carries more energy than the
  large forms);
- fine/broad: std of the 1.5-4 px band over std of the 12-48 px band, the grain-to-form
  ratio;
- grain L*: std of the 1.5-4 px band, in L* units;
- kurtosis of that fine band (Gaussian grain = 3; pits, specks and cracks give heavy tails);
- cv: the coefficient of variation of the local std of the fine band (non-stationarity);
- aniso: |d/dx| over |d/dy| energy of the fine band (formwork, streaks and joints add
  direction; spray grain is isotropic, 1.0).
Writes a JSON of the numbers and a contact sheet of the crops.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
EV = os.path.join(REPO, "docs", "redesign", "evidence")

# (label, file, crop x0, y0, x1, y1) in source pixels; plain wall only
CROPS = [
    ("v2 close-up: spray parapet", os.path.join(EV, "danchi-v2", "02_golden_piece_closeup.jpg"), 820, 560, 1320, 760),
    ("v6 bay: spray parapet", os.path.join(EV, "danchi-v6", "02_golden_bay.jpg"), 780, 425, 1120, 500),
    ("v6 bay: spray parapet 2", os.path.join(EV, "danchi-v6", "02_golden_bay.jpg"), 1210, 390, 1440, 450),
    ("v3 close-up: parapet", os.path.join(EV, "danchi-v3", "02_golden_piece_closeup.jpg"), 520, 470, 1040, 640),
    ("photo bay_02: sprayed back wall", "bay_02_toei_umegaoka_balcony.jpg", 880, 600, 990, 930),
    ("photo bay_02: sprayed wall 2", "bay_02_toei_umegaoka_balcony.jpg", 1180, 600, 1290, 700),
    ("photo bay_01: balcony parapet", "bay_01_apartment_balconies_laundry.jpg", 380, 625, 620, 675),
    ("photo weathering_07: painted wall", "weathering_07_saginomiya_wall_close.jpg", 300, 420, 520, 640),
    ("photo weathering_02: end wall", "weathering_02_saginomiya_stained_end.jpg", 260, 420, 540, 900),
    ("photo weathering_01: bare concrete", "weathering_01_ogikubo_stained_facade.jpg", 600, 560, 880, 660),
    ("photo weathering_03: bare box", "weathering_03_tsukida_entrance.jpg", 300, 660, 520, 960),
]


def to_L(rgb):
    c = rgb / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    Y = lin @ np.array([0.2126, 0.7152, 0.0722])
    f = np.where(Y > 216 / 24389, np.cbrt(Y), (24389 / 27 * Y + 16) / 116)
    return 116 * f - 16


def gblur(a, s):
    if s <= 0:
        return a
    r = int(3 * s + 1)
    x = np.arange(-r, r + 1)
    k = np.exp(-x * x / (2 * s * s))
    k /= k.sum()
    p = np.pad(a, r, mode="reflect")
    p = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, p)
    p = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, p)
    return p


def band(a, s_lo, s_hi):
    return gblur(a, s_lo) - gblur(a, s_hi)


def spectrum_slope(a, lo=3.0, hi=48.0):
    a = a - a.mean()
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    F = np.abs(np.fft.fftshift(np.fft.fft2(a * win)))
    yy, xx = np.indices(F.shape)
    fy = (yy - h // 2) / h
    fx = (xx - w // 2) / w
    f = np.hypot(fx, fy)
    sel = (f > 1.0 / hi) & (f < 1.0 / lo)
    bins = np.logspace(np.log10(1.0 / hi), np.log10(1.0 / lo), 14)
    idx = np.digitize(f[sel], bins)
    amp = F[sel]
    xs, ys = [], []
    for i in range(1, len(bins)):
        m = idx == i
        if m.sum() > 4:
            xs.append(np.log10(f[sel][m].mean()))
            ys.append(np.log10(amp[m].mean()))
    return float(np.polyfit(xs, ys, 1)[0])


def measure(L):
    fine = band(L, 0.6, 1.6)
    broad = band(L, 5.0, 20.0)
    fstd = fine.std()
    k = float(((fine - fine.mean()) ** 4).mean() / (fstd ** 4 + 1e-9))
    loc = np.sqrt(np.maximum(gblur(fine ** 2, 6.0), 0))
    gx = np.abs(np.diff(fine, axis=1)).mean()
    gy = np.abs(np.diff(fine, axis=0)).mean()
    return dict(slope=round(spectrum_slope(L), 2),
                fine_over_broad=round(float(fstd / (broad.std() + 1e-9)), 3),
                grain_L=round(float(fstd), 2),
                broad_L=round(float(broad.std()), 2),
                kurtosis=round(k, 1),
                cv_local=round(float(loc.std() / (loc.mean() + 1e-9)), 2),
                aniso=round(float(gx / (gy + 1e-9)), 2),
                mean_L=round(float(L.mean()), 1))


def main():
    refs, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    extra = [c for c in sys.argv[3:]]  # label=path:x0,y0,x1,y1 for new renders
    crops = list(CROPS)
    for e in extra:
        lab, rest = e.split("=", 1)
        path, box = rest.rsplit(":", 1)
        crops.append((lab, path) + tuple(int(v) for v in box.split(",")))
    res, tiles = {}, []
    for lab, f, x0, y0, x1, y1 in crops:
        p = f if os.path.isabs(f) else os.path.join(refs, f)
        im = Image.open(p).convert("RGB")
        c = np.asarray(im.crop((x0, y0, x1, y1))).astype(np.float64)
        L = to_L(c)
        res[lab] = measure(L)
        res[lab]["crop_px"] = [x1 - x0, y1 - y0]
        t = Image.fromarray(c.astype(np.uint8)).resize((300, int(300 * (y1 - y0) / (x1 - x0))))
        tiles.append((lab, t))
    for lab, m in res.items():
        print(f"{lab:38s} slope {m['slope']:6.2f}  fine/broad {m['fine_over_broad']:5.2f}  "
              f"grain {m['grain_L']:5.2f}  broad {m['broad_L']:5.2f}  kurt {m['kurtosis']:5.1f}  "
              f"cv {m['cv_local']:4.2f}  aniso {m['aniso']:4.2f}  L {m['mean_L']}")
    with open(os.path.join(out, "wall_grain_stats.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    H = sum(t.height + 16 for _, t in tiles)
    cols = 2
    rows = (len(tiles) + 1) // 2
    hmax = max(t.height for _, t in tiles) + 16
    sheet = Image.new("RGB", (cols * 310, rows * hmax), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (lab, t) in enumerate(tiles):
        x, y = (i % cols) * 310, (i // cols) * hmax
        d.text((x + 3, y + 2), lab, fill=(230, 230, 230))
        sheet.paste(t, (x, y + 16))
    sheet.save(os.path.join(out, "wall_grain_crops.jpg"), quality=88)


if __name__ == "__main__":
    main()
