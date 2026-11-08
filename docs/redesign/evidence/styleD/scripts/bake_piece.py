#!/usr/bin/env hython
"""bake_piece.py - round D: bake the painterly layer of one golden piece into plain engine
textures, then re-import them as plain textures and render both versions.

The golden piece is one balcony bay of the v3 danchi (floor F, bay B): back wall, partitions,
and the parapet band and slab edge clipped to the bay. Steps:
  1. apply the style (apply_painterly.setup: sdir and t2 vertex attributes, materials);
  2. SOPs: per-vertex projected UV `puv` (the same world-space projection the shader uses),
     base colour, then uvflatten + uvlayout into a 0-1 UV set;
  3. Copernicus: rasterizesetup (space uv) + rasterizegeo of the attributes, sample the stroke
     texture through puv, the HSV stroke maths, the emissive lift, a height -> tangent normal;
     write albedo (sRGB PNG), normal (raw 16-bit PNG, OpenGL +Y), ORM (raw PNG: R occlusion 1,
     G roughness, B metal 0), emissive (sRGB PNG), and a mask PNG;
  4. re-import: read the PNGs back with File COPs and compare to the graph; build a plain
     MaterialX material from the PNGs only (mtlximage -> standard surface inputs) and render the
     piece with it and with the procedural material, same camera.

  hython bake_piece.py <scene.hip> <out_dir> [--style t2|t1] [--floor 3] [--bay 5] [--res 2048]

Note: only Cd (the generator's base colour) and the round-D style layer are baked; the
procedural weathering of the base MaterialX graph is not (see the research note).
"""
import argparse
import importlib.util
import os
import time

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("pd_apply", os.path.join(HERE, "apply_painterly.py"))
AP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AP)


PIECE_VEX = r'''
// keep one bay: wall_bal and partition_board of (floor, bay); parapet/slab edge of that floor
int F = chi("floor"), B = chi("bay");
string p = s@part;
int keep = 0;
if ((p == "wall_bal" || p == "partition_board") && i@floor == F && i@bay == B && i@side == 0) keep = 1;
if ((p == "parapet_bal" || p == "slab_edge") && i@side == 0) {
    float y0 = chf("y0"), y1 = chf("y1");
    keep = (v@P.y > y0 && v@P.y < y1 && v@P.z > 0) ? 1 : 0;
}
if (!match("*materials/conc", s@shop_materialpath)) keep = 0;
if (!keep) removeprim(0, @primnum, 1);
'''

PUV_VEX = r'''
// the shader's projection, per vertex: dominant axis, U/V swapped where sdir = 1, / tile
vector n = abs(normalize(v@N));
vector2 uvx = set(v@P.z, v@P.y), uvz = set(v@P.x, v@P.y), uvy = set(v@P.x, v@P.z);
vector2 w = n.x > n.z ? uvx : uvz;
vector2 uv = n.y > max(n.x, n.z) ? uvy : w;
// TRAP: in a vertex-class wrangle, f@sdir does not fall back to the primitive attribute; it
// silently creates a new vertex attribute set to 0 (v@Cd likewise created a white vertex Cd).
// Read primitive attributes with prim().
if (prim(0, "sdir", @primnum) > 0.5) uv = set(uv.y, uv.x);
v@puv = set(uv.x / chf("tile") + 1000.0, uv.y / chf("tile") + 1000.0, 0);
// prim Cd promoted to vertex for rasterizing (see the TRAP above)

v@bcd = prim(0, "Cd", @primnum);
if (!haspointattrib(0, "pd_tint") && !hasvertexattrib(0, "pd_tint")) v@pd_tint = {1, 1, 1};
'''


def piece_sops(floor, bay, tile, style):
    obj = hou.node("/obj").createNode("geo", "pd_piece")
    om = obj.createNode("object_merge", "src")
    om.parm("objpath1").set("/obj/danchi/OUT")
    om.parm("xformtype").set("local")
    # bay extents from its back wall
    g = hou.node("/obj/danchi/OUT").geometry()
    xs, ys = [], []
    for pr in g.prims():
        if pr.attribValue("part") == "wall_bal" and pr.attribValue("floor") == floor \
                and pr.attribValue("bay") == bay and pr.attribValue("side") == 0:
            bb = pr.boundingBox()
            xs += [bb.minvec()[0], bb.maxvec()[0]]
            ys += [bb.minvec()[1], bb.maxvec()[1]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w = obj.createNode("attribwrangle", "keep")
    w.setInput(0, om)
    w.parm("class").set("primitive")
    ptg = w.parmTemplateGroup()
    for k in ("floor", "bay"):
        ptg.append(hou.IntParmTemplate(k, k, 1))
    for k in ("y0", "y1"):
        ptg.append(hou.FloatParmTemplate(k, k, 1))
    w.setParmTemplateGroup(ptg)
    w.parm("snippet").set(PIECE_VEX)
    w.parm("floor").set(floor)
    w.parm("bay").set(bay)
    w.parm("y0").set(y0 - 1.3)   # parapet band and slab edge below the back wall's base
    w.parm("y1").set(y0 + 0.3)
    last = w
    for name, org, d in (("clip_l", (x0, 0, 0), (-1, 0, 0)), ("clip_r", (x1, 0, 0), (1, 0, 0))):
        c = obj.createNode("clip", name)
        c.setInput(0, last)
        c.parmTuple("origin").set(org)
        c.parmTuple("dir").set(d)
        c.parm("clipop").set("below")
        last = c
    pv = obj.createNode("attribwrangle", "puv")
    pv.setInput(0, last)
    pv.parm("class").set("vertex")
    ptg = pv.parmTemplateGroup()
    ptg.append(hou.FloatParmTemplate("tile", "tile", 1))
    pv.setParmTemplateGroup(ptg)
    pv.parm("tile").set(AP.P["det_tile"] if style == "t2" else AP.P["t1_tile"])
    pv.parm("snippet").set(PUV_VEX)
    proc = obj.createNode("null", "PROC")      # piece with the procedural material
    proc.setInput(0, pv)
    fl = obj.createNode("uvflatten::3.0", "flatten")
    fl.setInput(0, pv)
    lay = obj.createNode("uvlayout::3.0", "layout")
    lay.setInput(0, fl)
    out = obj.createNode("null", "BAKE")
    out.setInput(0, lay)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    return obj, proc, out, (x0, x1, y0, y1)


def mk(cn, t, name, inp=(), **kw):
    n = cn.createNode(t, name)
    if isinstance(inp, tuple) and len(inp) == 2 and isinstance(inp[0], hou.Node) and isinstance(inp[1], (int, str)):
        inp = [inp]  # a single (node, output) pair
    for i, x in enumerate(inp if isinstance(inp, (list, tuple)) else [inp]):
        if x is None:
            continue
        if isinstance(x, tuple):
            n.setInput(i, x[0], x[1] if isinstance(x[1], int) else list(x[0].outputNames()).index(x[1]))
        else:
            n.setInput(i, x)
    for k, v in kw.items():
        p = n.parmTuple(k) if isinstance(v, (tuple, list)) else n.parm(k)
        if p is None:
            raise RuntimeError("%s %s: no parm %s" % (t, name, k))
        p.set(v)
    return n


def write(cn, node, path, kind, idx=0):
    r = cn.createNode("rop_image", "rop_" + os.path.splitext(os.path.basename(path))[0])
    r.setInput(0, node, idx)
    r.parm("copoutput").set(path)
    if kind in ("normal", "orm", "mask"):
        r.parm("colorconversion").set("raw")
    if kind == "normal":
        r.parm("size1").set("int16")
    if kind in ("albedo", "emissive", "orm", "mask"):
        r.parm("size1").set("int8")
    r.render()
    if not os.path.exists(path):
        raise RuntimeError("not written %s: %s" % (path, r.errors()))
    return path


def bake(sop, style, res, outdir, metres_per_uv):
    P = AP.P
    cn = hou.node("/img").createNode("copnet", "pd_bake")
    cn.parm("setres").set(1)
    cn.parm("res1").set(res)
    cn.parm("res2").set(res)
    cn.parm("setprecision").set(1)
    cn.parm("precision").set("b32")
    si = mk(cn, "sopimport", "geo", usesoppath=1, soppath=sop.path())
    rs = mk(cn, "rasterizesetup", "uvspace", si, space="uv")
    rg = cn.createNode("rasterizegeo", "raster")
    rg.setInput(list(rg.inputNames()).index("geometry"), rs)
    attrs = [("bcd", "vector3"), ("pd_tint", "vector3"), ("pd_liftc", "vector3"), ("pd_lift", "float"),
             ("pd_famp", "float"), ("puv", "vector2"), ("intrinsic:alpha", "float")]
    rg.parm("attributes").set(len(attrs))
    for i, (nm, t) in enumerate(attrs, 1):
        rg.parm("name%d" % i).set(nm)
        rg.parm("outtype%d" % i).set(t)  # TRAP: tokens float/vector2/vector3/vector4/int
        rg.parm("optional%d" % i).set(1)
    o = {nm: (rg, i) for i, (nm, t) in enumerate(attrs)}
    if style != "t2":
        o["pd_famp"] = None
    # stroke texture through the projected UV, wrapped into 0-1
    tex = os.path.join(AP.TEX, "brush_detail.exr" if style == "t2" else "brush_strokes.exr").replace("\\", "/")
    ft = mk(cn, "file", "stroke_tex", filename=tex, colorspace="raw")
    ft.parm("addaovs").pressButton()  # TRAP: a File COP has no outputs until this is pressed
    print("stroke tex outputs", ft.outputNames())
    tc = mk(cn, "function", "puv_wrap", o["puv"], func="math", func_math="modulus", modbase=1.0)
    # TRAP: `sample` would not take the RGBA texture (signature auto -> "Can't convert RGBA to
    # Mono for tmap"; "default" did not help either). Split the texture first and sample each
    # channel as mono (signature f1).
    tsp = mk(cn, "channelsplit", "stroke_tex_split", ft)
    chans = []
    for i, c in enumerate("rgba"):
        smp = cn.createNode("sample", "stroke_sample_" + c)
        smp.parm("signature").set("f1")
        smp.parm("uvspace").set("texture")
        smp.setInput(list(smp.inputNames()).index("uv"), tc)
        smp.setInput(list(smp.inputNames()).index("texture"), tsp, i)
        chans.append((smp, 0))
    r_, g_, b_, a_ = chans
    if style == "t2":
        amp = o["pd_famp"]
        val, hue, sat, temp, bumpm, drough = P["det_val"], P["det_hue"], P["det_sat"], P["det_temp"], P["det_bump"], P["det_rough"]
    else:
        amp = None
        val, hue, sat, temp, bumpm, drough = P["t1_val"], P["t1_hue"], P["t1_sat"], P["t1_temp"], P["t1_bump"], P["t1_rough"]

    def scaled(x, k, nm):
        c = mk(cn, "constant", nm + "_c", [x], signature="f1", f1=k)
        y = mk(cn, "blend", nm + "_k", [x, c], mode="multiply")
        return mk(cn, "blend", nm + "_amp", [y, amp], mode="multiply") if amp is not None else y

    base = o["bcd"]
    if style == "t2":
        base = mk(cn, "blend", "albedo_drift", [o["bcd"], o["pd_tint"]], mode="multiply")
    hsv = mk(cn, "hsv", "to_hsv", base, op="to_hsv")
    hs = mk(cn, "channelsplit", "hsv_split", hsv)
    one = lambda nm, ref: mk(cn, "constant", nm, [ref], signature="f1", f1=1.0)
    h2 = mk(cn, "blend", "h2", [(hs, 0), scaled(g_, hue / 360.0, "dh")], mode="add")
    s2 = mk(cn, "blend", "s2", [(hs, 1), mk(cn, "blend", "sm", [scaled(b_, sat, "ds"), one("one_s", (hs, 1))], mode="add")], mode="multiply")
    v2 = mk(cn, "blend", "v2", [(hs, 2), mk(cn, "blend", "vm", [scaled(r_, val, "dv"), one("one_v", (hs, 2))], mode="add")], mode="multiply")
    hj = mk(cn, "channeljoin", "hsv2", [h2, s2, v2], signature="f3")
    rgb = mk(cn, "hsv", "to_rgb", hj, op="to_rgb")
    t = scaled(g_, temp, "dt")
    tr = mk(cn, "blend", "tr", [one("one_tr", t), t], mode="add")
    tb = mk(cn, "blend", "tb", [one("one_tb", t), t], mode="subtract")
    tilt = mk(cn, "channeljoin", "tilt", [tr, one("one_tg", t), tb], signature="f3")
    alb = mk(cn, "blend", "albedo", [rgb, tilt], mode="multiply")
    # emissive lift (t2): liftc x luminance(albedo) x pd_lift
    if style == "t2":
        lum = mk(cn, "mono", "albedo_lum", alb, op="hdtvlum")
        k = mk(cn, "blend", "lift_k", [lum, o["pd_lift"]], mode="multiply")
        em = mk(cn, "blend", "emissive", [o["pd_liftc"], k], mode="multiply")
    # height -> tangent-space normal (OpenGL: +Y up in UV space), and roughness
    hgt = mk(cn, "blend", "height", [a_, amp], mode="multiply") if amp is not None else mk(cn, "null", "height", a_)
    # relief bumpm metres over an image that is metres_per_uv wide: scale = relief / (width / 2)
    nrm = mk(cn, "heighttonormal", "normal", hgt, scale=bumpm / (metres_per_uv / 2.0))
    # roughness = 0.86 - drough * (h - 0.8). TRAP: the `function` COP gave a constant here
    # (scale ignored), so the maths is done with blends against constants.
    cst = lambda nm, v: mk(cn, "constant", nm, [hgt], signature="f1", f1=v)
    ro = mk(cn, "blend", "rough_h", [hgt, cst("c08", 0.8)], mode="subtract")
    ro = mk(cn, "blend", "rough_k", [ro, cst("ck", -drough)], mode="multiply")
    ro = mk(cn, "blend", "rough_d", [ro, cst("c086", 0.86)], mode="add")
    ro = mk(cn, "clamp", "rough", ro, lowerlimit=0.05, upperlimit=1.0)
    orm = mk(cn, "channeljoin", "orm", [one("ao", ro), ro, mk(cn, "constant", "metal", [ro], signature="f1", f1=0.0)], signature="f3")
    # pad the UV islands so mips do not bleed the background
    mask = o["intrinsic:alpha"]

    def pad(n, nm):
        e = cn.createNode("extrapolateboundaries", "pad_" + nm)
        e.setInput(0, n[0] if isinstance(n, tuple) else n, n[1] if isinstance(n, tuple) else 0)
        e.setInput(list(e.inputNames()).index("fillarea"), mask[0], mask[1])  # not "mask"
        return e
    outs = dict(albedo=pad(alb, "albedo"), normal=pad(nrm, "normal"), orm=pad(orm, "orm"))
    if style == "t2":
        outs["emissive"] = pad(em, "emissive")
    outs["mask"] = mk(cn, "null", "MASK", [mask])
    files = {}
    os.makedirs(outdir, exist_ok=True)
    for k, n in outs.items():
        files[k] = write(cn, n, os.path.join(outdir, "piece_%s_%s.png" % (style, k)), k)
    cn.layoutChildren()
    bad = [(n.name(), n.errors()) for n in cn.children() if n.errors()]
    return cn, outs, files, bad


def reimport_check(cn, outs, files):
    """Read each PNG back (File COP, raw for data maps), and report the max difference to the
    graph's own layer inside the mask, in 8-bit (16-bit for the normal) code values."""
    import numpy as np
    import OpenImageIO as oiio
    rep = {}
    m = oiio.ImageBuf(files["mask"]).get_pixels(oiio.FLOAT)[..., 0] > 0.5
    for k in ("albedo", "normal", "orm", "emissive"):
        if k not in files:
            continue
        x = oiio.ImageBuf(files[k]).get_pixels(oiio.FLOAT)[..., :3]
        e = dict(min=np.round(x[m].min(0), 3).tolist(), max=np.round(x[m].max(0), 3).tolist(),
                 mean=np.round(x[m].mean(0), 4).tolist())
        if k == "normal":
            # a flat tangent normal must read (0.5, 0.5, 1) raw
            e["share_z_above_0.95"] = float((x[m][:, 2] > 0.95).mean())
        rep[k] = e
    return rep


def plain_material(files):
    import voptoolutils
    mb = voptoolutils._setupMtlXBuilderSubnet(destination_node=hou.node("/mat"), name="pd_plain",
                                              mask=voptoolutils.MTLX_TAB_MASK, folder_label="MaterialX Builder",
                                              render_context="mtlx")
    ss = mb.node("mtlxstandard_surface")
    N = AP.N
    alb = N(mb, "mtlximage", "albedo", sig="color3", parms={"file": files["albedo"].replace("\\", "/")})
    alb.parm("filecolorspace").set("srgb_texture")
    nrm = N(mb, "mtlximage", "normal", sig="vector3", parms={"file": files["normal"].replace("\\", "/")})
    nm = N(mb, "mtlxnormalmap", "nmap", inputs={"in": nrm})
    orm = N(mb, "mtlximage", "orm", sig="vector3", parms={"file": files["orm"].replace("\\", "/")})
    rough = AP.ext(mb, "rough", orm, 1, "vector3")
    ss.setNamedInput("base_color", alb, 0)
    ss.setNamedInput("normal", nm, 0)
    ss.setNamedInput("specular_roughness", rough, 0)
    ss.parm("specular").set(0.35)
    if "emissive" in files:
        em = N(mb, "mtlximage", "emissive", sig="color3", parms={"file": files["emissive"].replace("\\", "/")})
        em.parm("filecolorspace").set("srgb_texture")
        ss.setNamedInput("emission_color", em, 0)
        ss.parm("emission").set(1.0)
    return mb


def render_piece(obj_paths, cam, pic, spp=32, resx=960):
    st = hou.node("/stage")
    for c in st.children():
        if c.name().startswith("pdp_"):
            c.destroy()
    si = st.createNode("sceneimport::2.0", "pdp_imp")
    si.parm("objects").set(" ".join(obj_paths + [cam, "/obj/sun", "/obj/sky"]))
    krs = st.createNode("karmarendersettings", "pdp_krs")
    krs.setInput(0, si)
    for k, v in dict(engine="cpu", pathtracedsamples=spp, samplesperpixel=spp, beauty=1, albedo=1).items():
        krs.parm(k).set(v)
    krs.parm("resolutionx").set(resx)
    si.cook(force=True)
    cp = [str(p.GetPath()) for p in si.stage().Traverse() if p.GetTypeName() == "Camera"]
    krs.parm("camera").set([c for c in cp if c.endswith("/" + cam.split("/")[-1])][0])
    krs.parm("picture").set(pic)
    rop = st.createNode("usdrender_rop", "pdp_rop")
    rop.setInput(0, krs)
    rop.parm("execute").pressButton()
    return pic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hip")
    ap.add_argument("out")
    ap.add_argument("--style", default="t2", choices=("t1", "t2"))
    ap.add_argument("--floor", type=int, default=3)
    ap.add_argument("--bay", type=int, default=5)
    ap.add_argument("--res", type=int, default=2048)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    done = AP.setup(a.hip, a.style, dict(drift=True, lift=True, detail=True), AP.TEX)
    obj, proc, bakesop, (x0, x1, y0, y1) = piece_sops(a.floor, a.bay, AP.P["det_tile"], a.style)
    g = bakesop.geometry()
    area3d = sum(p.intrinsicValue("measuredarea") for p in g.prims())
    # UV area: sum of the UV-space polygon areas
    import numpy as np
    uva = 0.0
    for p in g.prims():
        uv = [v.attribValue("uv")[:2] for v in p.vertices()]
        if len(uv) >= 3:
            x = np.array(uv)
            uva += 0.5 * abs(np.dot(x[:, 0], np.roll(x[:, 1], 1)) - np.dot(x[:, 1], np.roll(x[:, 0], 1)))
    mpu = (area3d / max(uva, 1e-9)) ** 0.5
    print("piece prims", len(g.prims()), "area %.2f m2" % area3d, "uv coverage %.2f" % uva,
          "metres per UV unit %.2f" % mpu, "texel %.1f mm" % (mpu / a.res * 1000), "bay x %.2f..%.2f y %.2f..%.2f" % (x0, x1, y0, y1))
    cn, outs, files, bad = bake(bakesop, a.style, a.res, a.out, mpu)
    print("baked", files, "errors", bad, "%.0fs" % (time.time() - t0))
    print("reimport", reimport_check(cn, outs, files))
    if a.no_render:
        return
    # the plain-texture twin: piece with UVs, plain material only
    plain = plain_material(files)
    po = hou.node("/obj").createNode("geo", "pd_piece_plain")
    om = po.createNode("object_merge", "src")
    om.parm("objpath1").set(bakesop.path())
    mw = po.createNode("attribwrangle", "mat")
    mw.setInput(0, om)
    mw.parm("class").set("primitive")
    mw.parm("snippet").set('s@shop_materialpath = "%s";' % plain.path())
    mw.setDisplayFlag(True)
    mw.setRenderFlag(True)
    pp = hou.node("/obj").createNode("geo", "pd_piece_proc")
    om2 = pp.createNode("object_merge", "src")
    om2.parm("objpath1").set(proc.path())
    om2.setDisplayFlag(True)
    om2.setRenderFlag(True)
    obj.setDisplayFlag(False)
    cam = hou.node("/obj").createNode("cam", "pd_cam")
    import collections
    print("piece parts", collections.Counter(p.attribValue("part") for p in g.prims()))
    bb = g.boundingBox()
    c = bb.center()
    ext = max(bb.sizevec()[0], bb.sizevec()[1] * 960.0 / 720.0)
    # 24 mm on a 41.42 mm aperture: half-width = 0.863 x distance; frame the piece at 80 %
    dist = 0.5 * ext / 0.863 / 0.8
    cam.parmTuple("t").set((c[0] + 0.15 * dist, c[1] + 0.05 * dist, bb.maxvec()[2] + dist))
    cam.parmTuple("r").set((-2.8, 8.5, 0.0))
    print("piece bbox", bb, "cam dist %.2f" % dist)
    cam.parm("resx").set(960)
    cam.parm("resy").set(720)
    for tag, o in (("procedural", pp), ("plain", po)):
        pic = os.path.join(a.out, "piece_%s_%s.exr" % (a.style, tag)).replace("\\", "/")
        render_piece([o.path()], cam.path(), pic)
        print("rendered", pic, os.path.exists(pic))
        AP.to_jpg(pic, pic[:-4] + ".jpg")


if __name__ == "__main__":
    main()
