"""showcase_sheets.py — after the showcase render: uncaptioned JPGs (< 400 KB), labelled contact
sheets and showcase/manifest.json. Runs outside Houdini (PIL):

    python showcase_sheets.py <examples/danchi> <shots.json>

shots.json is written by showcase.py (dump_shots, after key_shots): the shot list with frame, camera, the parms
the shot set and the effective values weather_params resolved for that frame.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

MAX_BYTES = 400_000
# 1:1 detail crops per camera (x0, y0, x1, y1 in the 1600 x 900 frames)
DETAIL = {"sweep": (540, 0, 940, 520), "bay": (450, 250, 850, 770), "facade": (420, 300, 820, 820)}


def save_jpg(im, path, q=90):
    while True:
        im.save(path, quality=q, optimize=True, progressive=True)
        if os.path.getsize(path) < MAX_BYTES or q <= 50:
            return q
        q -= 4


def font(sz):
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def sheet(items, cols, out, title, tile_w=None, row_labels=None, col_labels=None):
    """items: [(label, PIL image)]. Labels go in a strip under each tile, never on the picture."""
    w0, h0 = items[0][1].size
    tw = tile_w or min(w0, 1600 // cols)
    th = int(h0 * tw / w0)
    lab_h, top_h = 26, 34
    left = 150 if row_labels else 0
    head = 24 if col_labels else 0
    rows = (len(items) + cols - 1) // cols
    W = left + tw * cols
    Hh = top_h + head + rows * (th + lab_h)
    sh = Image.new("RGB", (W, Hh), (24, 24, 24))
    d = ImageDraw.Draw(sh)
    d.text((8, 7), title, fill=(235, 235, 235), font=font(20))
    if col_labels:
        for c, t in enumerate(col_labels):
            d.text((left + c * tw + 6, top_h + 2), t, fill=(220, 220, 220), font=font(16))
    for k, (label, im) in enumerate(items):
        r, c = k // cols, k % cols
        x, y = left + c * tw, top_h + head + r * (th + lab_h)
        sh.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 6, y + th + 4), label, fill=(230, 230, 230), font=font(15))
        if row_labels and c == 0:
            d.text((8, y + th // 2 - 8), row_labels[r], fill=(220, 220, 220), font=font(16))
    q = save_jpg(sh, out, 88)
    return out, sh.size, os.path.getsize(out), q


def main(root, shots_json):
    shots = json.load(open(shots_json))
    sd = os.path.join(root, "showcase")
    raw = os.path.join(sd, "raw")
    os.makedirs(os.path.join(sd, "sheets"), exist_ok=True)
    images = {}
    manifest = {"asset": "hocuspocus::danchi::1.1", "building": "default: 10 floors x 12 units, seed 1, 1600x900, Karma",
                "lighting": "distant sun 28 deg high from the south-west (camera side of the south facade and the west end wall; /obj/sun r = -28, -40, 0), intensity 0.72; sky dome tex/sky.png at 0.6; Karma XPU, 32 spp, no motion blur",
                "cameras": {}, "images": []}
    old_q = {}
    if os.path.exists(os.path.join(sd, "manifest.json")):
        old_q = {i["file"]: i.get("jpeg_quality") for i in json.load(open(os.path.join(sd, "manifest.json")))["images"]}
    for s in shots:
        src = os.path.join(raw, "shot_%03d.png" % s["frame"])
        im = Image.open(src).convert("RGB")
        dst = os.path.join(sd, s["file"] + ".jpg")
        # keep a JPG that is newer than its frame (so critique results for it stay valid)
        if os.path.exists(dst) and os.path.getmtime(dst) > os.path.getmtime(src) and old_q.get(s["file"] + ".jpg"):
            q = old_q[s["file"] + ".jpg"]
        else:
            q = save_jpg(im, dst)
        images[s["file"]] = im
        manifest["images"].append({"file": s["file"] + ".jpg", "group": s["group"], "camera": s["camera"], "label": s["label"],
                                   "set": s["parms"], "values": s.get("values", {}), "effective": s.get("effective", {}),
                                   "bytes": os.path.getsize(dst), "jpeg_quality": q})
    for cam, v in shots[0].get("cameras", {}).items():
        manifest["cameras"][cam] = v
    out = []
    # preset strips
    for cam in ("bay", "facade"):
        it = [(s["label"].split(" (")[0], images[s["file"]]) for s in shots if s["group"] == "preset_strip" and s["camera"] == cam]
        out.append(sheet(it, 4, os.path.join(sd, "sheets", f"preset_strip_{cam}.jpg"),
                         f"Presets, {cam} camera: New - Well kept - Typical - Neglected", tile_w=400))
    # sweeps
    for g in sorted({s["group"] for s in shots if s["group"].startswith("sweep_")}):
        it = [(s["label"], images[s["file"]]) for s in shots if s["group"] == g]
        cam = next(s["camera"] for s in shots if s["group"] == g)
        ctl = g[6:].replace("_bay", "").replace("_", " ").capitalize()
        out.append(sheet(it, 5, os.path.join(sd, "sheets", f"{g}.jpg"),
                         f"{ctl} sweep (override on, other layers at Typical auto), {cam} camera", tile_w=320))
    # the same sweeps as 1:1 crops (upper end wall and facade edge; the bay at 10 m): the effect of
    # one control is often a few pixels wide at the contact-sheet scale
    for g in sorted({s["group"] for s in shots if s["group"].startswith("sweep_")}):
        cam = next(s["camera"] for s in shots if s["group"] == g)
        box = DETAIL[cam]
        it = [(s["label"], images[s["file"]].crop(box)) for s in shots if s["group"] == g]
        ctl = g[6:].replace("_bay", "").replace("_", " ").capitalize()
        out.append(sheet(it, 5, os.path.join(sd, "sheets", f"{g}_detail.jpg"),
                         f"{ctl} sweep, 1:1 crops of the {cam} camera", tile_w=box[2] - box[0]))
    # all sweeps in one sheet, one row per control
    it = [(s["label"], images[s["file"]]) for s in shots if s["group"].startswith("sweep_")]
    rows = [g[6:].replace("_bay", " (bay)").replace("_", " ") for g in sorted({s["group"] for s in shots if s["group"].startswith("sweep_")},
                                                   key=lambda g: [x["group"] for x in shots].index(g))]
    out.append(sheet(it, 5, os.path.join(sd, "sheets", "sweeps_all.jpg"), "Detail sweeps at 0, 0.25, 0.5, 0.75, 1 (sweep camera; edge damage also at the bay camera)",
                     tile_w=290, row_labels=rows, col_labels=["0", "0.25", "0.5", "0.75", "1"]))
    # age x upkeep grid
    it = [(s["label"], images[s["file"]]) for s in shots if s["group"] == "age_upkeep_grid"]
    out.append(sheet(it, 3, os.path.join(sd, "sheets", "age_upkeep_grid.jpg"),
                     "Age (rows: 10, 35, 60 years) x Upkeep (columns: 0.9, 0.5, 0.1), facade camera", tile_w=500))
    manifest["sheets"] = [os.path.relpath(o[0], sd).replace("\\", "/") for o in out]
    # the LOD value-match strip is made with the LOD check (checks.py / README), not from these shots
    if os.path.exists(os.path.join(sd, "sheets", "lod_value_match.jpg")):
        manifest["sheets"].append("sheets/lod_value_match.jpg")
    json.dump(manifest, open(os.path.join(sd, "manifest.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    for o in main(sys.argv[1], sys.argv[2]):
        print(o)
