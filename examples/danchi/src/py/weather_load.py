"""weather_load.py — how much weathering does a wall carry? Presets against reference photos,
on the same kind of view: a plain end wall (gable) seen from 30-60 m.

    python -I weather_load.py <refs_img_dir> <renders.json> <out_dir>

renders.json: {"<name>": {"file": "...jpg", "crop": [x0, y0, x1, y1] (pixels)}} for the renders.
The round-7 set is showcase/checks/weather_load_renders.json (the west end wall in the facade-camera
images, projected through the camera with toNDC); run from examples/danchi:
    python -I src/py/weather_load.py ../../docs/redesign/evidence/refs/img showcase/checks/weather_load_renders.json showcase/checks
The photo crops are below (fractions of the image), picked by eye on plain stretches of end wall:
no windows, numbers, pipes, trees or sky.

Measures on each crop, in CIE L*, after removing a fitted plane (the light gradient across the
wall) and resampling the crop to 160 px high (a common scale for different distances):
  soil    P95 - P50 of L*: how far the typical wall sits below its cleanest paint
  mottle  standard deviation of L* (blotches, streaks, patches)
  dark    share of the wall more than 8 L* below its P95 (stained area)
  vstreak mean |dL/dx| / mean |dL/dy| on a lightly blurred crop (> 1: vertical structure, runs)
None of these knows about lighting direction or paint colour, so read them as a ranking, not
as absolute truth. The point of the check: New should sit below every photo, Typical inside the
photo range (around the median), Neglected at the heavy end.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

# end-wall crops in the reference photos (fractions x0, y0, x1, y1), chosen on gridded previews
PHOTO_CROPS = {
    "end_01_akabanedai_34_end.jpg": [0.265, 0.30, 0.40, 0.72],
    "end_02_soshigaya_22_end.jpg": [0.73, 0.28, 0.90, 0.55],
    "end_03_nagasawa_2-2_end.jpg": [0.33, 0.25, 0.52, 0.62],
    "end_05_naruko_end_b.jpg": [0.58, 0.20, 0.72, 0.40],
    "end_06_kita_ward_end.jpg": [0.67, 0.30, 0.79, 0.70],
    "weathering_02_saginomiya_stained_end.jpg": [0.13, 0.22, 0.29, 0.70],
    # the heavy end of the range: the stained wall beside the stair of weathering_02, and raw
    # concrete between window columns on weathering_01 (decades without paint)
    "weathering_02_saginomiya_stained_end.jpg#stained": [0.305, 0.06, 0.345, 0.60],
    "weathering_01_ogikubo_stained_facade.jpg": [0.205, 0.17, 0.255, 0.70],
}


def to_L(rgb):
    a = np.asarray(rgb, np.float32) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    Y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    f = np.where(Y > 216 / 24389, np.cbrt(Y), (24389 / 27 * Y + 16) / 116)
    return 116 * f - 16


def blur(a):
    p = np.pad(a, 1, mode="edge")
    return sum(p[i:i + a.shape[0], j:j + a.shape[1]] for i in range(3) for j in range(3)) / 9.0


def metrics(im):
    h = 160
    w = max(16, int(im.width * h / im.height))
    L = to_L(im.convert("RGB").resize((w, h), Image.LANCZOS))
    yy, xx = np.mgrid[0:h, 0:w]
    A = np.c_[xx.ravel(), yy.ravel(), np.ones(h * w)]
    coef, *_ = np.linalg.lstsq(A, L.ravel(), rcond=None)
    R = L - (A @ coef).reshape(h, w) + L.mean()
    p95, p50 = np.percentile(R, [95, 50])
    B = blur(R)
    gx = np.abs(np.diff(B, axis=1)).mean()
    gy = np.abs(np.diff(B, axis=0)).mean()
    return {"L_mean": round(float(L.mean()), 1), "soil": round(float(p95 - p50), 2), "mottle": round(float(R.std()), 2),
            "dark": round(float((R < p95 - 8).mean()), 3), "vstreak": round(float(gx / max(gy, 1e-6)), 2)}


def main(refdir, renders_json, out_dir):
    rows = {}
    crops = []
    for f, c in PHOTO_CROPS.items():
        im = Image.open(os.path.join(refdir, f.split("#")[0])).convert("RGB")
        W, H = im.size
        cr = im.crop((int(c[0] * W), int(c[1] * H), int(c[2] * W), int(c[3] * H)))
        nm = f.split(".")[0] + ("#" + f.split("#")[1] if "#" in f else "")
        rows["photo:" + nm] = metrics(cr)
        crops.append((nm[:10] + nm[-8:], cr))
    rj = json.load(open(renders_json))
    for name, d in rj.items():
        im = Image.open(d["file"]).convert("RGB")
        cr = im.crop(tuple(int(v) for v in d["crop"]))
        rows["render:" + name] = metrics(cr)
        crops.append((name, cr))
    keys = ["soil", "mottle", "dark", "vstreak"]
    ph = [v for k, v in rows.items() if k.startswith("photo:")]
    summ = {k: {"photo_min": min(p[k] for p in ph), "photo_median": float(np.median([p[k] for p in ph])),
                "photo_max": max(p[k] for p in ph)} for k in keys}
    os.makedirs(out_dir, exist_ok=True)
    json.dump({"rows": rows, "photo_range": summ}, open(os.path.join(out_dir, "weather_load.json"), "w"), indent=1)
    # crop sheet, to check by eye that every crop is plain wall
    tw, th = 160, 220
    sh = Image.new("RGB", (tw * len(crops), th + 22), (20, 20, 20))
    d = ImageDraw.Draw(sh)
    for i, (lab, cr) in enumerate(crops):
        c2 = cr.copy()
        c2.thumbnail((tw - 4, th - 4))
        sh.paste(c2, (i * tw + 2, 2))
        d.text((i * tw + 3, th + 4), lab[:22], fill=(230, 230, 230))
    sh.save(os.path.join(out_dir, "weather_load_crops.jpg"), quality=85)
    lines = ["| image | L* mean | soil (P95-P50) | mottle (sd) | dark share | vertical streak |", "|---|---:|---:|---:|---:|---:|"]
    for k, v in rows.items():
        lines.append(f"| {k} | {v['L_mean']} | {v['soil']} | {v['mottle']} | {v['dark']} | {v['vstreak']} |")
    lines.append("| photo range (min / median / max) | | " + " | ".join(
        f"{summ[k]['photo_min']} / {summ[k]['photo_median']:.2f} / {summ[k]['photo_max']}" for k in keys) + " |")
    open(os.path.join(out_dir, "weather_load.md"), "w").write("\n".join(lines) + "\n")
    return "\n".join(lines)


if __name__ == "__main__":
    print(main(sys.argv[1], sys.argv[2], sys.argv[3]))
