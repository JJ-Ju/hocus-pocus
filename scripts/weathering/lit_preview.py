"""lit_preview.py - lit previews of a weathered config folder: albedo x (sky + sun on the plane
normal perturbed by the round-E spray-coat normal map). Elevations at reduced scale and 1:1 crops.
python -I wx/lit_preview.py <dir> [--real] [--crops spec.json]"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weather_fields import TEXDIR as TEX  # noqa: E402
ROOT = os.environ.get("WX_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
_nm = {}


def normal_tile(ppm, shape):
    if ppm not in _nm:
        im = Image.open(os.path.join(TEX, "spraymacro_normal.png")).convert("RGB")
        n = int(round(3.6 * ppm))
        a = np.asarray(im.resize((n, n), Image.BOX), np.float32) / 255.0 * 2 - 1
        _nm[ppm] = a
    t = _nm[ppm]
    H, W = shape
    return t[(np.arange(H) % t.shape[0])[:, None], (np.arange(W) % t.shape[1])[None, :]]


def to_srgb(lin):
    a = np.clip(lin, 0, 1)
    return np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def lit(rgb, cls, ppm, Ngeom=None, view="S", joint=None, relief=None):
    H, W = cls.shape
    tn = normal_tile(ppm, (H, W))
    painted = np.isin(cls, (1, 2, 4, 5))
    # tangent-space normal on a vertical wall facing the camera: x right, y up, z out
    nx = np.where(painted, tn[..., 0] * 0.6, 0.0)
    ny = np.where(painted, tn[..., 1] * 0.6, 0.0)
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    if relief is not None:                             # breaks: the floor below the wall face (m)
        z = -np.nan_to_num(np.asarray(relief, np.float32))
        px = 1.0 / ppm
        dzdx = np.zeros_like(z)
        dzdx[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / (2 * px)
        dzdy = np.zeros_like(z)
        dzdy[1:-1] = -(z[2:] - z[:-2]) / (2 * px)       # rows run down, y up
        nx, ny = nx - dzdx * nz, ny - dzdy * nz
        n = np.sqrt(nx * nx + ny * ny + nz * nz)
        nx, ny, nz = nx / n, ny / n, nz / n
    if Ngeom is not None:
        # facing factor from the captured geometry normal (soffits, returns darker)
        # the capture's walls face +z on the south front, -z on the north, -x on the west gable (round I:
        # the south and north previews had the sign the other way round, so their walls took no sun)
        face = np.clip(Ngeom[..., 2] if view == "S" else -Ngeom[..., 2] if view == "N" else -Ngeom[..., 0], 0, 1)
        up = np.clip(Ngeom[..., 1], -1, 1)
    else:
        face = np.ones((H, W))
        up = np.zeros((H, W))
    L = np.array([-0.35, 0.55, 0.76])                       # sun from upper left, in front
    L = L / np.linalg.norm(L)
    sun = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1) * face
    sky = 0.45 + 0.15 * up
    shade = sky + 0.75 * sun
    if joint is not None:                              # 20 mm grooves: their lips shade them
        shade = shade * np.where(joint & 1, 0.80, 1.0) * np.where(joint & 2, 0.88, 1.0)
    out = rgb * shade[..., None]
    glass = cls == 6                                   # a dark sky reflection, lighter at the top of each pane
    if glass.any():
        yy = np.arange(H, dtype=np.float32)[:, None] / max(H, 1)
        refl = np.stack([0.05 + 0.03 * (1 - yy), 0.06 + 0.035 * (1 - yy), 0.075 + 0.04 * (1 - yy)], -1) * np.ones((1, W, 1))
        out = np.where(glass[..., None], refl, out)
    return to_srgb(out)


def main():
    d = sys.argv[1]
    real = "--real" in sys.argv
    meta = json.load(open(os.path.join(d, "meta.json")))
    out = {}
    for name, pm in meta["planes"].items():
        z = np.load(os.path.join(d, name + ".npz"))
        rgb = z["rgb"].astype(np.float32)
        cls = z["cls"]
        Ng = None
        if real:
            v = name.split("_")[0]
            r = np.load(os.path.join(ROOT, "real", "clean_%s.npz" % v))
            Ng = r["N"]
        img = lit(rgb, cls, pm["ppm"], Ng, pm["orient"], z["joint"] if "joint" in z.files else None,
                  z["dmg_h"] if "dmg_h" in z.files else None)
        out[name] = img
        im = Image.fromarray((img * 255 + 0.5).astype(np.uint8))
        im.save(os.path.join(d, "lit_%s.jpg" % name), quality=90)
        im.resize((im.width // 4, im.height // 4), Image.LANCZOS).save(os.path.join(d, "lit_%s_small.jpg" % name), quality=88)
    print("ok", list(out))


if __name__ == "__main__":
    main()
