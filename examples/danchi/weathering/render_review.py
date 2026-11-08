"""Round-I review images: each shot of each build composed at game texel density (wx_hires), with the
crop captures for the geometry, and the same build as its single 50 px/m sheet for comparison.

    python -I render_review_i.py <jobs.json> [workers]

jobs.json: [{"build": "real/R..", "shot": "S_front/top", "out": "../pickI/img/x.jpg", "mode": "hires"|"sheet"|"layers:a,b"}]
Shots (50 px/m boxes, density) are in SHOTS. Elevations are composed at 50 px/m in strips and
downsampled by two. Each job is skipped when its output exists."""
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("WX_DATA", os.path.join(HERE, "data"))
os.environ.setdefault("WX_CROPS", os.path.join(os.environ["WX_DATA"], "out", "crops"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts", "weathering"))

SHOTS = {
    "S_front/elev": ("S_front", None, 50),
    "S_front/top": ("S_front", (1560, 330, 2460, 830), 200),
    "S_front/core": ("S_front", (1323, 380, 1423, 440), 1000),
    "S_front/base": ("S_front", (1560, 1350, 2460, 1800), 200),
    "S_front/foot": ("S_front", (1700, 1696, 1800, 1786), 1000),
    "S_front/rails": ("S_front", (1800, 1275, 1940, 1355), 1000),
    "S_front/railswide": ("S_front", (1560, 1180, 2160, 1480), 200),
    "W_gable/top": ("W_gable", (0, 330, 744, 1000), 200),
    "N_front/mid": ("N_front", (1500, 700, 2400, 1200), 200),
    "N_front/foot": ("N_front", (1500, 1500, 2400, 1800), 200),
    "S_front/peel": ("S_front", (1700, 1696, 1800, 1786), 1000),       # round J: the P3 window, 1 mm/px
    "S_front/topcorner": ("S_front", (26, 300, 626, 600), 200),       # round J: the top-left corner (F5)
}


def _ng(plane):
    return np.load(os.path.join(os.environ["WX_DATA"], "real", "clean_%s.npz" % plane.split("_")[0]))["N"]


def hires(build, plane, box, ppm, layers=None):
    import wx_hires as wh
    Ng = _ng(plane)
    if box is not None:
        r = wh.compose(build, plane, box, ppm, layers=layers)
        return wh.lit(r, Ng, plane.split("_")[0])
    z = np.load(os.path.join(build, plane + ".npz"))
    H, W = z["cls"].shape
    rows = np.flatnonzero(np.isin(z["cls"], (1, 2)).any(axis=1))
    top = max(0, int(rows[0]) - 20) if rows.size else 0
    strips = []
    step = 512
    for x0 in range(0, W, step):
        r = wh.compose(build, plane, (x0, top, min(W, x0 + step), H), ppm, layers=layers)
        strips.append(wh.lit(r, Ng, plane.split("_")[0]))
    return np.concatenate(strips, axis=1)


def sheet(build, plane, box, ppm):
    """The same build as the generator's single 50 px/m albedo sheet, lit the same way, shown at the
    shot's density (each 2 cm pixel a block)."""
    import lit_preview as lp
    z = np.load(os.path.join(build, plane + ".npz"))
    meta = json.load(open(os.path.join(build, "meta.json")))
    pm = meta["planes"][plane]
    img = lp.lit(z["rgb"].astype(np.float32), z["cls"], pm["ppm"], _ng(plane), pm["orient"],
                 z["joint"] if "joint" in z.files else None, z["dmg_h"] if "dmg_h" in z.files else None)
    img = (img * 255 + 0.5).astype(np.uint8) if img.dtype != np.uint8 else img
    if box is None:
        rows = np.flatnonzero(np.isin(z["cls"], (1, 2)).any(axis=1))
        top = max(0, int(rows[0]) - 20) if rows.size else 0
        return img[top:]
    x0, y0, x1, y1 = box
    c = img[y0:y1, x0:x1]
    f = int(round(ppm / 50.0))
    return np.repeat(np.repeat(c, f, 0), f, 1)


def run(job):
    out = job["out"]
    if os.path.exists(out):
        return out, 0.0
    t0 = time.time()
    plane, box, ppm = SHOTS[job["shot"]]
    mode = job.get("mode", "hires")
    if mode == "sheet":
        img = sheet(job["build"], plane, box, ppm)
    else:
        layers = None
        if mode.startswith("layers:"):
            layers = [x for x in mode.split(":", 1)[1].split(",") if x]
        img = hires(job["build"], plane, box, ppm, layers)
    if img.dtype != np.uint8:
        img = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    im = Image.fromarray(img)
    if box is None:                                   # elevations: shown at 25 px/m
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out, quality=88, optimize=True)
    return out, time.time() - t0


def main():
    jobs = json.load(open(sys.argv[1], encoding="utf-8"))
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    with Pool(n) as pool:
        for out, dt in pool.imap_unordered(run, jobs):
            print("%s %.0f s" % (os.path.basename(out), dt), flush=True)


if __name__ == "__main__":
    main()
