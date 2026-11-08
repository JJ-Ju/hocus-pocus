"""entry_images.py - review images for one accepted real-building entry: lit elevations (reduced)
and 1:1 crops at fixed places, so every entry is seen at the same spots.
python -I wx/entry_images.py <config_dir> <out_img_dir> <tag>"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts", "weathering"))
import lit_preview as lp  # noqa: E402

ROOT = os.environ.get("WX_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
# crops in pixels of the 50 px/m elevations (x0, y0, x1, y1)
CROPS = {
    "S_front": {"top": (1560, 330, 2460, 830), "base": (1560, 1350, 2460, 1800), "core": (2650, 330, 3150, 1130)},
    "W_gable": {"top": (0, 330, 744, 1000), "base": (0, 1250, 744, 1800)},
    "N_front": {"mid": (1500, 700, 2400, 1200)},
}


def main():
    d, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(d, "meta.json")))
    files = {}
    for name, pm in meta["planes"].items():
        z = np.load(os.path.join(d, name + ".npz"))
        v = name.split("_")[0]
        Ng = np.load(os.path.join(ROOT, "real", "clean_%s.npz" % v))["N"]
        img = lp.lit(z["rgb"].astype(np.float32), z["cls"], pm["ppm"], Ng, pm["orient"],
                     z["joint"] if "joint" in z.files else None, z["dmg_h"] if "dmg_h" in z.files else None)
        im = Image.fromarray((img * 255 + 0.5).astype(np.uint8))
        # trim the empty sky above the penthouses
        rows = np.flatnonzero(np.isin(z["cls"], (1, 2)).any(axis=1))
        top = max(0, int(rows[0]) - 20) if rows.size else 0
        small = im.crop((0, top, im.width, im.height))
        f = small.resize((max(1, small.width * 2 // 5), max(1, small.height * 2 // 5)), Image.LANCZOS)
        fn = "%s_%s.jpg" % (tag, name)
        f.save(os.path.join(out, fn), quality=86, optimize=True)
        files[name] = fn
        for cname, box in CROPS.get(name, {}).items():
            fn = "%s_%s_%s.jpg" % (tag, name, cname)
            im.crop(box).save(os.path.join(out, fn), quality=88, optimize=True)
            files["%s_%s" % (name, cname)] = fn
    json.dump(files, open(os.path.join(out, "%s_files.json" % tag), "w"), indent=1)
    print(tag, files)


if __name__ == "__main__":
    main()
