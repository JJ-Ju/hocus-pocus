"""wx_export.py - a weathered build as engine textures (round I): the unique facade masks the layered
material reads, beside the shared tiling sets, so the look ships as masks + tiling detail + decals
instead of one low-res sheet.

Per plane, from the build's layer stack (steps_<plane>.npz) and planes (<plane>.npz):
  <plane>_M_hi.png   RGBA8 linear, 50 px/m: R streaks (run-off envelope), G stains + ground band
                     (on steel: rust), B growth cover, A light layers (efflorescence)
  <plane>_M_lo.png   RGBA8 linear, 25 px/m: R soiling film, G damp (where water stays), B coat tone
                     (0.5 = none: fading, repaint), A edge-wear amount (for the trims)
  <plane>_tint.png   RGB8 sRGB, 25 px/m: the dirt colour (film and marks)
  <plane>_stage.png  R8 linear, 25 px/m: the growth's stage on its continuum (0 dark yellow ... 1 reddish)
  growth_ramp.png    256 x 1 RGB8 sRGB: the continuum the stage indexes
  <plane>_decals.json  decal placements: rust runs and stains below the steel, cracks (kind, head, box)
  export.json        frames (plane size in metres, px/m per texture), memory in MB with mips

python -I wx_export.py <build_dir> <out_dir>
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_fields as wf  # noqa: E402


DECAL_KINDS = (("L_rust", "rust_run", 0.08), ("L_cracks", "crack", 0.30))   # layer, decal kind, shortest kept (m); smaller marks stay in the masks (LOD bake)


def decal_list(z, pm):
    """Discrete marks as decal placements for one atlas: each connected mark of the layer at T2 or more
    on the painted wall (rust runs and stains below the steel, cracks) becomes one decal: its kind, top
    centre (the head), width and height in facade metres, and strength (mean of the layer there). The
    engine places a head-body-tail decal (or a crack strip) of the kind over that box; the masks keep
    the soft envelope."""
    import weather_measure as wm
    ppm = float(pm["ppm"])
    paint = np.isin(z["cls"], (1, 2))
    out = []
    for key, kind, min_h in DECAL_KINDS:
        if key not in z.files:
            continue
        L = np.nan_to_num(z[key].astype(np.float32))
        lab, n = wm.label(paint & (L >= wm.TIER_EDGES[1]))
        if not n:
            continue
        ys, xs = np.nonzero(lab)
        ll = lab[ys, xs]
        y0 = np.full(n + 1, 1 << 30)
        y1 = np.full(n + 1, -1)
        x0 = np.full(n + 1, 1 << 30)
        x1 = np.full(n + 1, -1)
        np.minimum.at(y0, ll, ys)
        np.maximum.at(y1, ll, ys)
        np.minimum.at(x0, ll, xs)
        np.maximum.at(x1, ll, xs)
        ssum = np.bincount(ll, L[ys, xs], n + 1)
        cnt = np.bincount(ll, minlength=n + 1)
        top = ys <= y0[ll] + 1
        tx = np.bincount(ll[top], xs[top], n + 1) / np.maximum(np.bincount(ll[top], minlength=n + 1), 1)
        for i in range(1, n + 1):
            h = (y1[i] - y0[i] + 1) / ppm
            if h < min_h:
                continue
            out.append({"kind": kind, "x_m": round(float(tx[i] + 0.5) / ppm, 3), "y_m": round(float(y0[i]) / ppm, 3),
                        "w_m": round(float(x1[i] - x0[i] + 1) / ppm, 3), "h_m": round(float(h), 3),
                        "strength": round(float(ssum[i] / max(cnt[i], 1)), 3)})
    return out


def _u8(a):
    return (np.clip(np.nan_to_num(a), 0, 1) * 255 + 0.5).astype(np.uint8)


def _srgb8(lin):
    a = np.clip(lin, 0, 1)
    return _u8(np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1 / 2.4) - 0.055))


def _half(a):
    h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
    a = a[:h, :w]
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def steps_of(d, plane):
    z = np.load(os.path.join(d, "steps_%s.npz" % plane))
    out = {}
    for i in range(int(z["n"])):
        name = str(z["s%d_name" % i])
        out[name] = {k.split("_", 1)[1]: z[k] for k in z.files if k.startswith("s%d_" % i) and not k.endswith(("_name", "_op"))}
    return out


def mb_with_mips(w, h, bytes_px):
    return w * h * bytes_px * 4.0 / 3.0 / 2 ** 20


def export(d, out):
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    info = {"build": os.path.abspath(d), "planes": {}, "mb": 0.0}
    for name, pm in meta["planes"].items():
        z = np.load(os.path.join(d, name + ".npz"))
        st = steps_of(d, name)
        H, W = z["cls"].shape

        def al(k):
            return st[k]["alpha"].astype(np.float32) if k in st else np.zeros((H, W), np.float32)
        steel = z["steel"] > 0 if "steel" in z.files else np.zeros((H, W), bool)
        hi = np.dstack([al("streaks"), np.where(steel, al("rust"), np.maximum(al("stains"), al("base"))), al("bio"),
                        al("efflorescence")])
        damp = z["bio_w"].astype(np.float32) if "bio_w" in z.files else np.zeros((H, W), np.float32)
        tone = 0.5 - 0.5 * al("fading") * 0.18
        if "repaint" in st:
            tone = tone + 0.5 * st["repaint"]["alpha"].astype(np.float32) * float(np.asarray(st["repaint"].get("shift", 0)))
        lo = np.dstack([_half(al("soiling")), _half(damp), _half(tone), _half(al("wear"))])
        Image.fromarray(_u8(hi), "RGBA").save(os.path.join(out, name + "_M_hi.png"))
        Image.fromarray(_u8(lo), "RGBA").save(os.path.join(out, name + "_M_lo.png"))
        col = st.get("soiling", {}).get("colour")
        if col is not None and np.ndim(col) == 3:
            Image.fromarray(_srgb8(col.astype(np.float32))).save(os.path.join(out, name + "_tint.png"))
        bcol = st.get("bio", {}).get("colour")
        if bcol is not None and np.ndim(bcol) == 3:
            xs = np.array([k for k, _ in wf.BIO_RAMP])
            cs = np.array([c for _, c in wf.BIO_RAMP], np.float32)
            ramp = np.stack([np.interp(np.linspace(0, 1, 256), xs, cs[:, i]) for i in range(3)], -1)
            # the stage that best matches each pixel's growth colour, on the ramp
            c = bcol.astype(np.float32).reshape(-1, 3)
            d2 = ((c[:, None, :] - ramp[None, ::4, :]) ** 2).sum(-1)
            stg = (np.argmin(d2, axis=1) * 4 / 255.0).reshape(bcol.shape[:2])
            Image.fromarray(_u8(stg)).save(os.path.join(out, name + "_stage.png"))
            Image.fromarray(_srgb8(ramp[None, :, :].astype(np.float32))).save(os.path.join(out, "growth_ramp.png"))
        decals = decal_list(z, pm)
        json.dump({"plane": name, "units": "facade metres, origin top-left, y down", "decals": decals},
                  open(os.path.join(out, name + "_decals.json"), "w"), indent=0)
        info.setdefault("decals", {})[name] = {"n": len(decals), "per_m2": round(len(decals) / max(1e-6, float(np.isin(z["cls"], (1, 2)).sum()) / pm["ppm"] ** 2), 3)}
        ppm = pm["ppm"]
        mb = mb_with_mips(W, H, 1.0) + mb_with_mips(W // 2, H // 2, 1.0) + 2 * mb_with_mips(W // 2, H // 2, 0.5)
        info["planes"][name] = {"size_m": [W / ppm, H / ppm], "M_hi_ppm": ppm, "M_lo_ppm": ppm / 2, "mb_bc": round(mb, 1),
                                "orient": pm.get("orient")}
        info["mb"] += mb
    info["mb"] = round(info["mb"], 1)
    json.dump(info, open(os.path.join(out, "export.json"), "w"), indent=1)
    return info


if __name__ == "__main__":
    print(json.dumps(export(sys.argv[1], sys.argv[2]), indent=1))
