"""Round J: player views of a build, straight on to the wall, at the screen's own density (research
art-review-and-qa.md 6.1-6.2): p = W / (2 tan(HFOV/2) d) with Unreal's 90 deg horizontal FOV, rendered by
the numpy mirror over geometry captured at that density, saved at 1:1 screen pixels (PNG, cropped,
never scaled), each with its label: renderer, distance, screen, px/m and texels per screen pixel.

python -I render_player_j.py <build_dir> <out_dir> [view ...]   (views: keys of VIEWS; default all)
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


def main():
    d, out = sys.argv[1], sys.argv[2]
    keys = sys.argv[3:] or list(VIEWS)
    os.makedirs(out, exist_ok=True)
    cp = {v: os.path.join(os.environ["WX_DATA"], "real", "clean_%s.npz" % v) for v in "SNW"}
    info = {}
    for k in keys:
        plane, box, dist, W, what = VIEWS[k]
        ppm = round(screen_ppm(dist, W))
        res = wh.compose(d, plane, box, float(ppm))
        Ng = np.load(cp[plane[0]])["N"] if os.path.exists(cp[plane[0]]) else None
        img = wh.lit(res, Ng, plane.split("_")[0])
        h, w = img.shape[:2]
        mw, mh = CROP.get(k, (1920, 1080))
        cw, ch = min(w, mw), min(h, mh)                         # one 1080p screen's worth (or CROP), 1:1, centred
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        crop = img[y0:y0 + ch, x0:x0 + cw]
        fn = os.path.join(out, "player_%s.png" % k)
        Image.fromarray(crop).save(fn, optimize=True)
        info[k] = {"file": os.path.basename(fn), "plane": plane, "distance_m": dist, "screen_px": W, "screen_ppm": ppm,
                   "detail_px_per_texel": round(ppm / 1000.0, 2), "mask_px_per_texel": round(ppm / 50.0, 1),
                   "crop_px": [cw, ch], "what": what, "renderer": "numpy mirror (wx_hires) over a Karma geometry capture"}
        print(k, json.dumps(info[k]), flush=True)
    json.dump(info, open(os.path.join(out, "player_views.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
