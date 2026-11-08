"""Round K: player views of a build (render_player_j's views and labels), rendered with the round-K generator,
and with --spec the sheen's reflection toggle for a view: the same shot lit three ways, saved beside it:
  player_<view>.png          the review's usual light (albedo, sun and sky fill; no reflection)
  player_<view>_refl0.png    plus a sky reflection everywhere at F0 0.04 (the sheen mask set to 0)
  player_<view>_refl1.png    plus the sky reflection with the sheen (F0 0.08 and roughness 0.55 under its mask)
The sky is wx_hires's stated clear sky (horizon 9,000 K, zenith 20,000 K, ground 0.30 grey), viewed straight on.

python -I render_player_k.py <build_dir> <out_dir> [--spec view,...] [view ...]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts", "weathering"))
os.environ.setdefault("WX_DATA", os.path.join(HERE, "data"))
os.environ.setdefault("WX_CROPS", os.path.join(os.environ["WX_DATA"], "out", "crops"))
import wx_hires as wh  # noqa: E402

# render_player_j's views (copied, not imported: each script sets its own path to the generator).
# key: (plane, 50 px/m box, distance m, screen width px, what it is)
VIEWS = {
    "touch_foot": ("S_front", (1700, 1722, 1800, 1778), 1.0, 3840, "the foot of the south front, a player at the wall"),
    "touch_rails": ("S_front", (1840, 1284, 1890, 1340), 1.0, 3840, "a balcony railing at arm's length, top rail to feet"),
    "touch_walkway": ("N_front", (2600, 760, 2700, 816), 1.0, 3840, "the north walkway wall at arm's length"),
    "walkway": ("S_front", (1650, 1674, 1850, 1786), 2.0, 1920, "two metres from the south front's ground floor"),
    "path": ("S_front", (1400, 1336, 2200, 1786), 8.0, 1920, "across the path, the two lower storeys"),
}
HFOV = 90.0
CROP = {"touch_rails": (1920, 2160)}     # the railing's full height: half of a 4K screen (1 m x 1.125 m at 1 m)


def screen_ppm(d, W):
    return W / (2.0 * np.tan(np.radians(HFOV) / 2.0) * d)


def crop_of(img, k):
    h, w = img.shape[:2]
    mw, mh = CROP.get(k, (1920, 1080))
    cw, ch = min(w, mw), min(h, mh)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    return img[y0:y0 + ch, x0:x0 + cw], (cw, ch)


def main():
    args = sys.argv[1:]
    spec = []
    if "--spec" in args:
        i = args.index("--spec")
        spec = args[i + 1].split(",")
        args = args[:i] + args[i + 2:]
    d, out = args[0], args[1]
    keys = args[2:] or list(VIEWS)
    os.makedirs(out, exist_ok=True)
    cp = {v: os.path.join(os.environ["WX_DATA"], "real", "clean_%s.npz" % v) for v in "SNW"}
    info = {}
    for k in keys:
        plane, box, dist, W, what = VIEWS[k]
        ppm = round(screen_ppm(dist, W))
        res = wh.compose(d, plane, box, float(ppm))
        Ng = np.load(cp[plane[0]])["N"] if os.path.exists(cp[plane[0]]) else None
        view = plane.split("_")[0]
        img, (cw, ch) = crop_of(wh.lit(res, Ng, view), k)
        fn = os.path.join(out, "player_%s.png" % k)
        Image.fromarray(img).save(fn, optimize=True)
        info[k] = {"file": os.path.basename(fn), "plane": plane, "distance_m": dist, "screen_px": W, "screen_ppm": ppm,
                   "detail_px_per_texel": round(ppm / 1000.0, 2), "mask_px_per_texel": round(ppm / 50.0, 1),
                   "crop_px": [cw, ch], "what": what, "renderer": "numpy mirror (wx_hires) over a Karma geometry capture"}
        if k in spec:
            ex = res.setdefault("extra", {})
            sh = ex.get("sheen")
            ex["sheen"] = np.zeros(res["cls"].shape, np.float32)
            r0, _ = crop_of(wh.lit(res, Ng, view, spec=True, tilt_deg=0.0), k)
            ex["sheen"] = sh if sh is not None else np.zeros(res["cls"].shape, np.float32)
            r1, _ = crop_of(wh.lit(res, Ng, view, spec=True, tilt_deg=0.0), k)
            Image.fromarray(r0).save(fn.replace(".png", "_refl0.png"), optimize=True)
            Image.fromarray(r1).save(fn.replace(".png", "_refl1.png"), optimize=True)
            shc, _ = crop_of(np.asarray(ex["sheen"]), k)
            info[k]["sheen_px"] = int((shc > 0.5).sum())
            info[k]["sheen_share_of_steel"] = round(float((shc > 0.5).sum()) / max(int(crop_of(res["cls"] == 7, k)[0].sum()), 1), 4)
            info[k]["reflection"] = "split-sum sky (Karis EnvBRDFApprox), F0 0.04 / 0.08 under the sheen, viewed straight on"
        print(k, json.dumps(info[k]), flush=True)
    json.dump(info, open(os.path.join(out, "player_views.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
