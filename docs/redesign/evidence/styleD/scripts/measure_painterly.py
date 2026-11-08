#!/usr/bin/env hython
"""measure_painterly.py - round D measurements on Karma AOV EXRs (parts C, albedo, depth, N).

  hython measure_painterly.py <base.exr> <styled.exr> [--json out.json]

Reports, on geometry pixels (depth > 0), in CIE Lab (D65, from linear sRGB):
  albedo  : per-pixel value change (L* and ratio), a*/b* change, hue change where C* >= 4,
            the hue-drift range (hue angle percentiles of the albedo low-passed at 48 px),
            and high-frequency jitter (std of albedo minus a 6 px blur);
  beauty  : L* percentiles, chroma and hue angle of the darkest and brightest quartiles of
            non-sky pixels (the light/dark hue contrast), shadow b*.
"""
import argparse
import json
import os

import numpy as np

# outside hython, Houdini's bundled python313 finds the OIIO DLLs only through add_dll_directory
_HB = r"C:/Program Files/Side Effects Software/Houdini 22.0.466/bin"
if os.name == "nt" and os.path.isdir(_HB):
    os.add_dll_directory(_HB)
import OpenImageIO as oiio


def parts(path):
    out = {}
    for i in range(oiio.ImageBuf(path).nsubimages):
        b = oiio.ImageBuf(path, i, 0)
        out[b.spec().getattribute("name") or str(i)] = b.get_pixels(oiio.FLOAT)
    return out


def lab(rgb):
    rgb = np.clip(rgb, 0, None)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = rgb @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    return np.stack([L, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def blur(x, r):
    import OpenImageIO as o
    sp = o.ImageSpec(x.shape[1], x.shape[0], x.shape[2], o.FLOAT)
    b = o.ImageBuf(sp)
    b.set_pixels(o.ROI(), x.astype(np.float32))
    k = o.ImageBufAlgo.make_kernel("gaussian", 2 * r + 1, 2 * r + 1)
    return o.ImageBufAlgo.convolve(b, k).get_pixels(o.FLOAT)


def hue(a, b):
    return np.degrees(np.arctan2(b, a)) % 360


def circ_pct(h, q):
    # percentiles of an angle around its circular mean
    m = np.degrees(np.angle(np.exp(1j * np.radians(h)).mean()))
    d = (h - m + 180) % 360 - 180
    return m % 360, np.percentile(d, q)


def measure(base, sty):
    A, B = parts(base), parts(sty)
    geo = (A["depth"][..., 0] > 1e-3) & (B["depth"][..., 0] > 1e-3)
    r = {}
    la, lb = lab(A["albedo"][..., :3]), lab(B["albedo"][..., :3])
    m = geo & (la[..., 0] > 20)
    dL = (lb[..., 0] - la[..., 0])[m]
    ratio = (B["albedo"][..., :3].mean(-1) / np.maximum(A["albedo"][..., :3].mean(-1), 1e-4))[m]
    ca, cb = np.hypot(la[..., 1], la[..., 2]), np.hypot(lb[..., 1], lb[..., 2])
    mc = m & (ca >= 4) & (cb >= 4)
    dh = ((hue(lb[..., 1], lb[..., 2]) - hue(la[..., 1], la[..., 2]) + 180) % 360 - 180)[mc]
    r["albedo"] = dict(
        frac_changed=float((np.abs(ratio - 1) > 0.004).mean()),
        value_ratio_std=float(ratio.std()), value_ratio_p5_p95=np.percentile(ratio, [5, 95]).round(4).tolist(),
        dL_std=float(dL.std()), da_std=float((lb[..., 1] - la[..., 1])[m].std()),
        db_std=float((lb[..., 2] - la[..., 2])[m].std()),
        dhue_deg_p5_p95=np.percentile(dh, [5, 95]).round(2).tolist() if dh.size else None,
        dhue_deg_std=float(dh.std()) if dh.size else None, chroma_px_share=float(mc.sum() / max(m.sum(), 1)),
        chroma_mean_base=float(ca[m].mean()), chroma_mean_styled=float(cb[m].mean()))
    for name, L_ in (("base", la), ("styled", lb)):
        lp = lab(blur(np.where(geo[..., None], (A if name == "base" else B)["albedo"][..., :3], 0), 24))
        mm = geo & (np.hypot(lp[..., 1], lp[..., 2]) >= 1.5) & (L_[..., 0] > 20)
        h = hue(lp[..., 1], lp[..., 2])[mm]
        if h.size:
            mean, (p5, p95) = circ_pct(h, [5, 95])
            r["albedo"]["lowpass_hue_" + name] = dict(mean=round(float(mean), 1), p5=round(float(p5), 1),
                                                      p95=round(float(p95), 1), share=float(mm.mean()))
        hp = (L_ - lab(blur((A if name == "base" else B)["albedo"][..., :3], 3)))[m]
        r["albedo"]["hf_std_" + name] = np.round(hp.std(0), 3).tolist()  # L*, a*, b*
    for name, P in (("base", A), ("styled", B)):
        c = lab(P["C"][..., :3])
        L = c[..., 0][geo]
        q1, q3 = np.percentile(L, [25, 75])
        dark, light = geo & (c[..., 0] <= q1), geo & (c[..., 0] >= q3)
        e = dict(L_p1_p50_p99=np.percentile(L, [1, 50, 99]).round(1).tolist())
        for k, mk in (("dark", dark), ("light", light)):
            a_, b_ = c[..., 1][mk], c[..., 2][mk]
            e[k] = dict(a=round(float(a_.mean()), 2), b=round(float(b_.mean()), 2),
                        C=round(float(np.hypot(a_, b_).mean()), 2),
                        hue=round(float(hue(a_.mean(), b_.mean())), 1))
        e["dark_minus_light_hue"] = round(float((e["dark"]["hue"] - e["light"]["hue"] + 180) % 360 - 180), 1)
        r["beauty_" + name] = e
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("styled")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = measure(a.base, a.styled)
    s = json.dumps(r, indent=1)
    print(s)
    if a.json:
        open(a.json, "w").write(s)


if __name__ == "__main__":
    main()
