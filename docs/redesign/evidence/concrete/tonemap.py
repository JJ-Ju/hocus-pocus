"""tonemap.py - linear render (.npy from render_wall.py) to an sRGB JPG under 400 KB.

    python tonemap.py <in.npy> <out.jpg> [--exposure 1.0] [--label "text"]
    python tonemap.py --pair a.npy b.npy <out.jpg> --labels "A" "B" [--exposure 1.0]

The same fixed exposure and curve go on every frame of one lighting setup, so sets compare
fairly: exposure, then an extended-Reinhard shoulder (white point 3.0), then the sRGB OETF.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw


def tonemap(lin, exposure):
    x = np.clip(lin * exposure, 0, None)
    w = 3.0
    y = x * (1 + x / (w * w)) / (1 + x)
    y = np.clip(y * 1.25, 0, 1)                      # put mid-grey near 0.18 -> ~0.46 sRGB
    s = np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(y, 1 / 2.4) - 0.055)
    return (np.clip(s, 0, 1) * 255 + 0.5).astype(np.uint8)


def caption(img, text):
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.rectangle([0, h - 22, min(w, 9 * len(text) + 16), h], fill=(10, 10, 10))
    d.text((6, h - 18), text, fill=(235, 235, 235))
    return img


def save_small(img, path, limit=400_000):
    for q in (92, 88, 84, 80, 75, 70, 62, 55):
        img.save(path, quality=q, optimize=True)
        if os.path.getsize(path) <= limit:
            return q
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--pair", action="store_true")
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--label", default="")
    ap.add_argument("--labels", nargs="*", default=[])
    ap.add_argument("--width", type=int, default=0, help="resize each panel to this width")
    a = ap.parse_args()
    out = a.inputs[-1]
    srcs = a.inputs[:-1]
    ims = []
    for i, s in enumerate(srcs):
        im = Image.fromarray(tonemap(np.load(s), a.exposure))
        if a.width:
            im = im.resize((a.width, int(im.height * a.width / im.width)), Image.LANCZOS)
        lab = a.labels[i] if i < len(a.labels) else (a.label if len(srcs) == 1 else "")
        if lab:
            caption(im, lab)
        ims.append(im)
    if len(ims) == 1:
        sheet = ims[0]
    else:
        w = sum(i.width for i in ims) if a.pair else max(i.width for i in ims)
        h = max(i.height for i in ims) if a.pair else sum(i.height for i in ims)
        sheet = Image.new("RGB", (w, h))
        x = y = 0
        for im in ims:
            sheet.paste(im, (x, y))
            if a.pair:
                x += im.width
            else:
                y += im.height
    q = save_small(sheet, out)
    print("wrote", out, os.path.getsize(out), "q", q)


if __name__ == "__main__":
    main()
