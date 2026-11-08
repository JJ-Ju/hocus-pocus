"""assemble_picker.py - round D: copy the renders into picker/ as A/B pairs (one variable each),
uncaptioned JPGs under 400 kB, plus pairs.json for the picker page.

  python -I assemble_picker.py
"""
import json
import os
import shutil

from PIL import Image

R = os.path.dirname(os.path.abspath(__file__))
FULL = os.path.join(R, "out", "full")
POST = os.path.join(R, "out", "post")
BAKE = os.path.join(R, "out", "bake")
PICK = os.path.join(R, "picker")

# (id, A, B, the one variable)
PAIRS = [
    ("p01", "base", "t1", "task 1 brush-stroke layer off / on"),
    ("p02", "t1", "t1_x2", "task 1 stroke amplitude x1 / x2 (value 3->6 %, hue 4->8 deg, sat 5->10 %)"),
    ("p03", "base_post", "t1_post", "task 1 brush layer off / on, both under the round-C post (dusk, strength 0.4, haze 0.70)"),
    ("p04", "t1", "t1_post", "round-C post off / on (dusk, strength 0.4, haze 0.70) over task 1 - post is offline only"),
    ("p05", "t1", "t1_keyfill", "light colours: neutral / warm key + cold blue fill (engine-native 'dusk' pick), task 1"),
    ("p06", "base", "t2", "task 2 hyper-real painterly layer off / on"),
    ("p07", "t2_nodrift", "t2", "task 2 hue-drift field (blue<->green, warm zones, sun warmth) off / on"),
    ("p08", "t2_nolift", "t2", "task 2 lifted saturated darks (emission) off / on"),
    ("p09", "t2_nodetail", "t2", "task 2 high-frequency multi-hue detail off / on"),
    ("p10", "t2", "t2_strong", "task 2 amplitudes default / strong (lift 0.04->0.07, detail x1.7, drift x1.5)"),
    ("p11", "t2", "t2_keyfill", "light colours: neutral / warm key + cold blue fill, task 2"),
    ("p12", "t1", "t2", "style: task 1 anime brush layer / task 2 hyper-real painterly"),
]
PIECES = [
    ("p13", "piece_t2_procedural", "piece_t2_plain", "golden piece: procedural MaterialX / baked plain textures re-imported (task 2)"),
    ("p14", "piece_t1_procedural", "piece_t1_plain", "golden piece: procedural MaterialX / baked plain textures re-imported (task 1)"),
]
ZOOMS = [  # (id, A, B, cam, box, variable)
    ("p01z", "base", "t1", "hero", (960, 400, 1280, 580), "2x crop of p01 (near parapets): brush layer off / on"),
    ("p02z", "t1", "t1_x2", "hero", (960, 400, 1280, 580), "2x crop of p02: amplitude x1 / x2"),
    ("p06z", "base", "t2", "facade", (420, 330, 740, 510), "2x crop of p06: task 2 off / on"),
    ("p09z", "t2_nodetail", "t2", "facade", (420, 330, 740, 510), "2x crop of p09: detail off / on"),
]


def src(name, cam):
    if name.endswith("_post"):
        return os.path.join(POST, "%s_cam_%s.jpg" % (name, cam))
    return os.path.join(FULL, "%s_cam_%s.jpg" % (name, cam))


def put(srcp, dst, box=None):
    im = Image.open(srcp).convert("RGB")
    if box:
        im = im.crop(box)
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    q = 92
    while True:
        im.save(dst, quality=q)
        if os.path.getsize(dst) < 400 * 1024 or q < 60:
            break
        q -= 4
    return os.path.getsize(dst)


def main():
    os.makedirs(PICK, exist_ok=True)
    out = []
    for pid, a, b, var in PAIRS:
        for cam in ("hero", "facade"):
            files = []
            for side, n in (("A", a), ("B", b)):
                s = src(n, cam)
                if not os.path.exists(s):
                    print("missing", s)
                    continue
                d = os.path.join(PICK, "%s_%s_%s_%s.jpg" % (pid, cam, side, n))
                files.append((os.path.basename(d), put(s, d)))
            out.append(dict(pair=pid, cam=cam, variable=var, A=files[0][0] if files else None,
                            B=files[1][0] if len(files) > 1 else None, sizes=[f[1] for f in files]))
    for pid, a, b, var in PIECES:
        files = []
        for side, n in (("A", a), ("B", b)):
            s = os.path.join(BAKE, n + ".jpg")
            if os.path.exists(s):
                d = os.path.join(PICK, "%s_piece_%s_%s.jpg" % (pid, side, n))
                files.append((os.path.basename(d), put(s, d)))
        if len(files) == 2:
            out.append(dict(pair=pid, cam="piece", variable=var, A=files[0][0], B=files[1][0], sizes=[f[1] for f in files]))
    for pid, a, b, cam, box, var in ZOOMS:
        files = []
        for side, n in (("A", a), ("B", b)):
            s = src(n, cam)
            if os.path.exists(s):
                d = os.path.join(PICK, "%s_%s_%s_%s.jpg" % (pid, cam, side, n))
                files.append((os.path.basename(d), put(s, d, box)))
        if len(files) == 2:
            out.append(dict(pair=pid, cam=cam, variable=var, A=files[0][0], B=files[1][0], sizes=[f[1] for f in files]))
    json.dump(out, open(os.path.join(PICK, "pairs.json"), "w"), indent=1)
    for o in out:
        print(o["pair"], o["cam"], o["A"], o["B"], o["sizes"])


if __name__ == "__main__":
    main()
