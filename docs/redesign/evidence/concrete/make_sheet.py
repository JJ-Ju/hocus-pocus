"""make_sheet.py - contact sheet of one texture set (plain Python 3 + numpy + Pillow).

    python make_sheet.py <tex_dir> <prefix> <out.jpg> [--crop 0.25] [--tile3]

Panels: base colour, height (stretched p1-p99), normal, roughness (stretched), mask RGB, AO,
and a full-resolution crop of the base colour and of a quick lit preview (Lambert of the normal
under a grazing light) so the micro read is visible. --tile3 adds a 3 x 3 repeat of the base
colour for the tiling check. JPGs are kept under 400 KB.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw


def load(path, mode=None):
    im = Image.open(path)
    a = np.asarray(im).astype(np.float32)
    a /= 65535.0 if a.max() > 255 else 255.0
    return a


def stretch(a):
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)


def to_img(a):
    a = np.clip(a, 0, 1)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    return Image.fromarray((a[..., :3] * 255 + 0.5).astype(np.uint8))


def lit(normal, light=(-0.75, 0.25, 0.62)):
    n = normal[..., :3] * 2.0 - 1.0
    l = np.array(light, np.float32)
    l /= np.linalg.norm(l)
    return np.clip((n * l).sum(-1), 0, 1)


def save_small(img, path, limit=400_000):
    for q in (90, 85, 80, 75, 70, 60, 50):
        img.save(path, quality=q, optimize=True)
        if os.path.getsize(path) <= limit:
            return q
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tex_dir")
    ap.add_argument("prefix")
    ap.add_argument("out")
    ap.add_argument("--crop", type=float, default=0.18, help="crop size as a fraction of the tile")
    ap.add_argument("--tile3", action="store_true")
    ap.add_argument("--cell", type=int, default=420)
    a = ap.parse_args()
    p = lambda n: os.path.join(a.tex_dir, f"{a.prefix}_{n}.png")
    maps = {}
    for n in ("basecolor", "height", "normal", "roughness", "mask", "ao"):
        if os.path.exists(p(n)):
            maps[n] = load(p(n))
    cell = a.cell
    panels = []
    if "basecolor" in maps:
        panels.append(("base colour", maps["basecolor"]))
    if "height" in maps:
        h = maps["height"]
        panels.append(("height (p1-p99)", stretch(h if h.ndim == 2 else h[..., 0])))
    if "normal" in maps:
        panels.append(("normal", maps["normal"]))
    if "roughness" in maps:
        r = maps["roughness"]
        r = r if r.ndim == 2 else r[..., 0]
        panels.append((f"roughness {np.percentile(r,1):.2f}-{np.percentile(r,99):.2f}", stretch(r)))
    if "mask" in maps:
        m = maps["mask"]
        panels.append(("mask RGB", m[..., :3] if m.ndim == 3 else m))
    if "ao" in maps:
        o = maps["ao"]
        panels.append(("ao", o if o.ndim == 2 else o[..., 0]))
    # full-res crops (top-left region of the tile)
    if "basecolor" in maps:
        b = maps["basecolor"]
        c = int(b.shape[0] * a.crop)
        y0, x0 = int(b.shape[0] * 0.05), int(b.shape[1] * 0.55)
        panels.append((f"base crop {a.crop:.2f} tile", b[y0:y0 + c, x0:x0 + c]))
        if "normal" in maps:
            L = lit(maps["normal"])[y0:y0 + c, x0:x0 + c]
            alb = b[y0:y0 + c, x0:x0 + c, :3].mean(-1) / max(b[..., :3].mean(), 1e-3)
            panels.append(("grazing lit crop", np.clip(L * alb * 0.9, 0, 1)))
    if a.tile3 and "basecolor" in maps:
        b = maps["basecolor"][..., :3]
        panels.append(("3x3 repeat", np.tile(b, (3, 3, 1))))
    cols = 4
    rows = (len(panels) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 18)), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for i, (label, arr) in enumerate(panels):
        im = to_img(arr).resize((cell, cell), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * (cell + 18)
        sheet.paste(im, (x, y + 18))
        d.text((x + 4, y + 3), label, fill=(230, 230, 230))
    q = save_small(sheet, a.out)
    print("wrote", a.out, os.path.getsize(a.out), "bytes, q", q)


if __name__ == "__main__":
    main()
