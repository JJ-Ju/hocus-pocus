#!/usr/bin/env hython
"""build_brush_tex.py - round D: tiling painterly stroke textures authored in Copernicus.

Two textures, both tiling (wrap border), written as raw float EXR (RGBA, signed data):

  strokes  (task 1, anime-background brush layer). One tile = TILE_M metres (default 4 m).
           Short directional strokes along +V (vertical in the texture), flat inside, soft dry
           edges (bristle breakup at the sides and the trailing end), painted over each other.
             R = per-stroke value offset    -1..1 (flat per stroke, 0 in gaps)
             G = per-stroke hue offset      -1..1
             B = per-stroke saturation offs -1..1
             A = paint height 0..1 (stroke body x bristle ridges), for a faint bump/roughness
  detail   (task 2, hyper-real painterly). Same structure at a smaller scale (default 1.5 m),
           denser and smaller strokes with a second, finer stroke layer, so the hue and value
           jitter is high-frequency and averages out at distance.

Run from a directory that holds no .py files:
  hython build_brush_tex.py --out <dir> [--kind strokes|detail|both] [--res 2048] [--preview]
         [--save-hip graph.hiplc]
Every node and parm name was read in Houdini 22.0.466.
"""
import argparse
import os
import time

import hou


class G:
    def __init__(self, net):
        self.net = net

    def mk(self, ntype, inp=(), name=None, **kw):
        n = self.net.createNode(ntype, name) if name else self.net.createNode(ntype)
        if not isinstance(inp, (list, tuple)):
            inp = [inp]
        for i, x in enumerate(inp):
            if x is None:
                continue
            if isinstance(x, tuple):
                src, o = x
                if isinstance(o, str):  # TRAP: setInput wants an output index
                    o = list(src.outputNames()).index(o)
                n.setInput(i, src, o)
            else:
                n.setInput(i, x)
        for k, v in kw.items():
            if n.parm(k) is not None:
                n.parm(k).set(v)
            elif n.parmTuple(k) is not None:
                n.parmTuple(k).set(v)
            else:
                raise RuntimeError("%s: no parm %s" % (ntype, k))
        return n

    def named(self, node, inname, src, out=0):
        idx = list(node.inputNames()).index(inname)
        if isinstance(out, str):
            out = list(src.outputNames()).index(out)
        node.setInput(idx, src, out)
        return node


# Stroke layer settings. Image space spans -1..1 = 2 units = one tile.
LAYERS = {
    # task 1: strokes 0.3-0.8 m long and 0.07-0.16 m wide on a 4 m tile (measured on the
    # written EXR, see the research note). Overlapping so almost every point is painted.
    "strokes": [dict(tag="a", sx=40, sy=21, scale=0.147, scalevar=0.35, angvar=5.0, jitter=0.95,
                     stretchvar=(0.35, 0.25), seed=3, density=1.0)],
    # task 2: two layers, medium strokes plus a fine dense layer on top (1.5 m tile)
    "detail": [dict(tag="a", sx=34, sy=18, scale=0.12, scalevar=0.4, angvar=9.0, jitter=0.95,
                    stretchvar=(0.4, 0.3), seed=11, density=1.0),
               dict(tag="b", sx=64, sy=34, scale=0.05, scalevar=0.5, angvar=14.0, jitter=1.0,
                    stretchvar=(0.5, 0.4), seed=23, density=0.75)],
}


def stamp(g, tag, seed):
    """One brush-stroke stamp on its own canvas: a rounded bar along +Y, a soft core, and dry
    bristle breakup at the sides and at the trailing (top) end."""
    sdf = g.mk("sdfshape", [], "stamp_sdf_" + tag, basictype="rect", rect_sizex=0.42,
               rect_sizey=1.80, rect_round=1, rect_roundness=0.35)
    m = g.mk("sdftomono", [sdf], "stamp_mask_" + tag)
    soft = g.mk("blur", [m], "stamp_soft_" + tag, units="pixels", size_pixel=110.0)
    # bristles: noise stretched along the stroke (thin in x, long in y)
    br = g.mk("fractalnoise", [m], "stamp_bristle_" + tag, elementsize=0.9, elementsizetype=1,
              elementscalex=0.035, elementscaley=1.0, amp=0.5, center=0.5, oct=3,
              offx=seed * 1.37, offy=seed * 0.71, dotiled=0)
    brc = g.mk("function", [br], "stamp_bristle_c_" + tag, func="math", func_math="abs",
               scale=2.5, shift=-1.25)  # abs(noise) - 0.5 -> -0.5..0.5 (abs is a no-op on 0..1)
    # trailing-end dryness: vertical ramp is 1 at the top, 0 at the bottom
    vr = g.mk("ramp", [m], "stamp_v_" + tag, rampType="vertical", signature="f1")
    dry = g.mk("remap", [vr], "stamp_dry_" + tag, useramp=0, inputmin=0.62, inputmax=0.98,
               outputmin=0.0, outputmax=0.55)
    t = g.mk("blend", [soft, brc], "stamp_t0_" + tag, mode="add", mask=0.75)
    t = g.mk("blend", [t, dry], "stamp_t1_" + tag, mode="subtract")
    a = g.mk("remap", [t], "stamp_alpha0_" + tag, useramp=0, inputmin=0.36, inputmax=0.46,
             outputmin=0.0, outputmax=1.0)
    inside = g.mk("remap", [soft], "stamp_inside_" + tag, useramp=0, inputmin=0.05, inputmax=0.30)
    a = g.mk("blend", [a, inside], "stamp_alpha_" + tag, mode="multiply")
    return a


def ridges(g, ref, tag):
    """Bristle ridge texture sampled per stroke through the stamp UV (so ridges follow each
    stroke, not the image)."""
    return g.mk("fractalnoise", [ref], "ridge_tex_" + tag, elementsize=0.6, elementsizetype=1, elementscalex=0.03,
                elementscaley=1.0, amp=0.5, center=0.5, oct=2, dotiled=1)


def layer(g, L, ref):
    tag = L["tag"]
    st = stamp(g, tag, L["seed"])
    # TRAP: stampscaling defaults to 1 (tile): every stamp is squeezed into its grid cell and
    # `scale` is ignored. 0 (image) makes `scale` the stamp half-size in image units.
    sc = g.mk("shapescatter", [ref], "scatter_" + tag, stampscaling=0, linkstamps=0, stampsx=L["sx"],
              stampsy=L["sy"], seed=L["seed"], scale=L["scale"], scalemode=1,
              scalevariance=L["scalevar"], jitter=L["jitter"], anglemode=1,
              anglevariance=L["angvar"], stretchmode=1, stretchvariancex=L["stretchvar"][0],
              stretchvariancey=L["stretchvar"][1], randompercomp=1, density=L["density"],
              blend=0, gridtype=1, dotiled=1, treatmonoasalpha=1)
    g.named(sc, "stamps", st)
    cov = g.mk("mono", [(sc, "result")], "cov_" + tag)
    ids = (sc, "id")
    rnd = []
    for k, s in (("val", 101), ("hue", 202), ("sat", 303)):
        r = g.mk("randommono", [], "rnd_%s_%s" % (k, tag), rangemethod=0, min=-1.0, max=1.0, seed=s + L["seed"],
                 zeroinvalid=1)
        g.named(r, "seed", ids[0], ids[1])
        g.named(r, "size_ref", ref)
        rnd.append(g.mk("blend", [r, cov], "%s_%s" % (k, tag), mode="multiply"))
    rt = ridges(g, ref, tag)
    rs = g.mk("sample", [], "ridge_%s" % tag, uvspace=0)
    g.named(rs, "uv", sc, "uv")
    g.named(rs, "texture", rt)
    rsm = g.mk("mono", [rs], "ridge_m_" + tag)
    h = g.mk("remap", [rsm], "ridge_h_" + tag, useramp=0, inputmin=0.0, inputmax=1.0,
             outputmin=0.70, outputmax=1.0)
    hgt = g.mk("blend", [h, cov], "height_" + tag, mode="multiply")
    return dict(cov=cov, val=rnd[0], hue=rnd[1], sat=rnd[2], hgt=hgt)


def build(kind, res):
    old = hou.node("/img/brush_" + kind)
    if old:
        old.destroy()
    cn = hou.node("/img").createNode("copnet", "brush_" + kind)
    cn.parm("setres").set(1)
    cn.parm("res1").set(res)
    cn.parm("res2").set(res)
    cn.parm("setborder").set(1)
    cn.parm("border").set("wrap")
    cn.parm("setprecision").set(1)
    cn.parm("precision").set("b32")
    g = G(cn)
    ref = g.mk("constant", [], "ref", signature="f1", f1=0.0)
    ls = [layer(g, L, ref) for L in LAYERS[kind]]
    out = ls[0]
    for L2 in ls[1:]:
        # the upper layer paints over the lower one where it has coverage
        o = {}
        for k in ("val", "hue", "sat", "hgt"):
            o[k] = g.mk("blend", [out[k], L2[k], L2["cov"]], "%s_over_%s" % (k, len(o)),
                        mode="blend")
        o["cov"] = g.mk("blend", [out["cov"], L2["cov"]], "cov_max", mode="max")
        out = o
    rgba = g.mk("channeljoin", [out["val"], out["hue"], out["sat"], out["hgt"]], "RGBA",
                signature="f4")
    nul = g.mk("null", [rgba], "OUT")
    cov = g.mk("null", [out["cov"]], "COVERAGE")
    cn.layoutChildren()
    return cn, nul, cov, out


def write(cn, node, path, raw=True, size=None):
    r = cn.createNode("rop_image", "rop_" + os.path.splitext(os.path.basename(path))[0])
    r.parm("coppath").set(node.path())
    r.parm("copoutput").set(path)
    if raw:
        r.parm("colorconversion").set("raw")
    if size:
        r.parm("size1").set(size)
    r.render()
    if not os.path.exists(path):
        raise RuntimeError("not written %s %s" % (path, r.errors()))
    return path


def engine_png(cn, out, path):
    """Engine copy: 8-bit linear PNG (import with sRGB off), RGB = 0.5 + 0.5 x offset, A = height.
    Decode in the material: offset = tex.rgb * 2 - 1."""
    g = G(cn)
    ch = [g.mk("remap", [out[k]], "eng_" + k, useramp=0, inputmin=-1.0, inputmax=1.0)
          for k in ("val", "hue", "sat")]
    j = g.mk("channeljoin", ch + [out["hgt"]], "ENGINE_RGBA", signature="f4")
    return write(cn, j, path, raw=True, size="int8")


def preview(cn, out, path):
    """Visual check: value offset as grey around 0.5, at 8 bit."""
    g = G(cn)
    v = g.mk("function", [out["val"]], "pv_val", func="math", func_math="abs", scale=1.0)
    v = g.mk("remap", [out["val"]], "pv_val01", useramp=0, inputmin=-1.0, inputmax=1.0)
    h = g.mk("remap", [out["hue"]], "pv_hue01", useramp=0, inputmin=-1.0, inputmax=1.0)
    j = g.mk("channeljoin", [v, h, out["cov"]], "pv_rgb", signature="f3")
    write(cn, cn.node("stamp_alpha_a"), path.replace(".png", "_stamp.png"), raw=True, size="int8")
    return write(cn, j, path, raw=True, size="int8")


def stats(path):
    import numpy as np
    import OpenImageIO as oiio
    b = oiio.ImageBuf(path)
    x = b.get_pixels(oiio.FLOAT)
    r, gch, bch, a = x[..., 0], x[..., 1], x[..., 2], x[..., 3]
    cov = a > 0.05
    e = dict(coverage=float(cov.mean()), val_mean=float(r.mean()), val_std=float(r.std()),
             hue_mean=float(gch.mean()), hue_std=float(gch.std()), h_mean=float(a.mean()))
    # tiling check: edge difference vs neighbour difference
    e["seam_lr"] = float(np.abs(x[:, 0] - x[:, -1]).mean())
    e["nbr"] = float(np.abs(x[:, 1:] - x[:, :-1]).mean())
    return e


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--kind", default="both", choices=("strokes", "detail", "both"))
    ap.add_argument("--res", type=int, default=2048)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--save-hip")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    kinds = ("strokes", "detail") if a.kind == "both" else (a.kind,)
    for k in kinds:
        t = time.time()
        cn, nul, cov, out = build(k, a.res)
        p = write(cn, nul, os.path.join(a.out, "brush_%s.exr" % k), raw=True, size="float16")
        engine_png(cn, out, os.path.join(a.out, "brush_%s_engine.png" % k))
        if a.preview:
            preview(cn, out, os.path.join(a.out, "brush_%s_preview.png" % k))
        bad = [(n.name(), n.errors()) for n in cn.children() if n.errors()]
        print(k, p, "%.1fs" % (time.time() - t), "errors", bad)
        print("  stats", {kk: round(vv, 4) for kk, vv in stats(p).items()})
    if a.save_hip:
        hou.hipFile.save(a.save_hip)


if __name__ == "__main__":
    main()
