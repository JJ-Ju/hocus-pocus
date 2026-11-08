"""render_wall.py - render a texture set on a simple 14.4 x 5.4 m wall in Karma (CPU), headless.

    hython render_wall.py <tex_dir> <out_dir> <set> <view> <light> [res_x=1280] [spp=48]

set:   formed | spray | v6spray | v6concrete   (v6*: the round-6 danchi maps, same rig)
view:  close (2.4 m, oblique, arm's length) | bay (9 m, square on) | graze (1.5 m, along wall)
light: overcast (dome only) | sun (low raking sun at about 70 deg to the wall normal + sky)

Writes <out_dir>/<set>_<view>_<light>.exr and a .npy of the linear RGB (hython has numpy but
no Pillow); tonemap.py turns the .npy into a JPG. The stage is built from scratch each run;
nothing is saved. Every LOP and MaterialX node type and parm here was read from 22.0.466.

The materials put the "story" in the shader, the way an engine would: a world-space macro
value field (5-15 m), one cause field (a streak fringe below the wall top, sheltered patches,
a darker lower wall) that pulls toward soot and fills voids, seams and coat troughs first, a
damp base band with a ragged front, a per-panel world tint for the formed set (cell noise on
st / (0.9, 1.8)), and, for the spray set, the macro x detail split (detail height through
mtlxbump on top of the macro normal map, scaled by the macro coat mask). The v6 sets get the
same story, so a comparison isolates the texture.

Round-E previews: 1280 px, 48 samples; tonemap.py --exposure 1.7 (overcast) or 2.2 (sun).
"""
import os
import sys
import time

import hou
import numpy as np
import voptoolutils

TEX, OUT, SET, VIEW, LIGHT = sys.argv[1:6]
RESX = int(sys.argv[6]) if len(sys.argv) > 6 else 1280
SPP = int(sys.argv[7]) if len(sys.argv) > 7 else 48
V6TEX = "C:/Users/jujun/DEV/hocus-pocus/examples/danchi/tex"
os.makedirs(OUT, exist_ok=True)


# ----------------------------------------------------------------------------- MaterialX
def P(n, inp, value, sig=None):
    """Set an input parm whatever its signature suffix."""
    cands = ([f"{inp}_{sig}"] if sig else []) + [inp] + [
        f"{inp}_{s}" for s in ("color3", "color3FA", "float", "vector2", "vector3",
                               "vector2FA", "vector3FA")]
    want = len(value) if isinstance(value, (list, tuple)) else 1
    for c in cands:
        pt = n.parmTuple(c)
        if pt is not None and (len(pt) == want or want == 1):
            pt.set(value if isinstance(value, (list, tuple)) else (value,) * len(pt))
            return
    raise RuntimeError(f"{n.path()}: no parm for {inp}")


def M(mat, typ, sig=None, **ins):
    n = mat.createNode(typ)
    if sig:
        n.parm("signature").set(sig)
    for k, v in ins.items():
        if isinstance(v, hou.VopNode):
            n.setInput(n.inputIndex(k), v)
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], hou.VopNode):
            n.setInput(n.inputIndex(k), v[0], v[1])
        elif k in ("geomprop", "file", "space", "filecolorspace"):
            n.parm(k).set(v)
        else:
            P(n, k, v, sig)
    return n


def material(lib, name):
    m = lib.createNode("subnet", name)
    voptoolutils._setupMtlXBuilderSubnet(subnet_node=m, name=name)
    m.setMaterialFlag(True)
    return m, m.node("mtlxstandard_surface")


def link(dst, inp, src, out=0):
    dst.setInput(dst.inputIndex(inp), src, out)


def uv(m, tile_m):
    tc = M(m, "mtlxtexcoord", "vector2")
    return M(m, "mtlxmultiply", "vector2FA", in1=tc, in2=1.0 / tile_m)


def img(m, path, coords, sig="float", srgb=False):
    im = M(m, "mtlximage", sig, texcoord=coords)
    im.parm("file").set(path)
    im.parm("filecolorspace").set("srgb_texture" if srgb else "Raw")
    return im


def grime_field(m, wall_top=5.4):
    """One cause field for the plain test wall, in world space (an engine would read the
    generator's primvars instead): a fringe of streaks hanging from the wall top (a top with
    no drip), sheltered patches at 2-6 m, and more grime low on the wall. 0 = clean."""
    pos = M(m, "mtlxposition", space="world")
    sep = M(m, "mtlxseparate3v", **{"in": pos})
    # streaks: noise stretched 25x vertically, thresholded, fading 0.3-2.5 m below the top
    sp = M(m, "mtlxmultiply", "vector3FA", in1=pos, in2=1.0)
    st = M(m, "mtlxmultiply", "vector3", in1=sp, in2=(9.0, 0.36, 9.0))
    sn = M(m, "mtlxfractal3d", "float", position=st, octaves=3)
    streak = M(m, "mtlxsmoothstep", "float", **{"in": sn}, low=0.02, high=0.32)
    below = M(m, "mtlxsubtract", "float", in1=wall_top, in2=(sep, 1))
    lnn = M(m, "mtlxfractal3d", "float", position=M(m, "mtlxmultiply", "vector3", in1=pos,
                                                   in2=(1.3, 0.0, 1.3)), octaves=2)
    reach = M(m, "mtlxremap", "float", **{"in": lnn}, inlow=-0.5, inhigh=0.5, outlow=0.3,
              outhigh=2.5)
    fade = M(m, "mtlxsmoothstep", "float", **{"in": below}, low=reach, high=0.0)
    fringe = M(m, "mtlxmultiply", "float", in1=streak, in2=fade)
    # whole stretches of the top stay clean: a low-frequency patch mask (realism.md)
    pz = M(m, "mtlxfractal3d", "float", position=M(m, "mtlxmultiply", "vector3", in1=pos,
                                                   in2=(0.16, 0.0, 0.16)), octaves=2)
    fringe = M(m, "mtlxmultiply", "float", in1=fringe,
               in2=M(m, "mtlxsmoothstep", "float", **{"in": pz}, low=-0.15, high=0.2))
    # sheltered patches and a lower-wall gradient
    pn = M(m, "mtlxfractal3d", "float", position=M(m, "mtlxmultiply", "vector3FA", in1=pos,
                                                  in2=0.28), octaves=3)
    patch = M(m, "mtlxsmoothstep", "float", **{"in": pn}, low=0.0, high=0.35)
    low = M(m, "mtlxsmoothstep", "float", **{"in": (sep, 1)}, low=3.0, high=0.0)
    g = M(m, "mtlxmax", "float", in1=fringe, in2=M(m, "mtlxmultiply", "float", in1=patch,
                                                     in2=0.6))
    g = M(m, "mtlxmax", "float", in1=g, in2=M(m, "mtlxmultiply", "float", in1=low, in2=0.35))
    return g


def world_story(m, col, rough, macro_amp=0.06, damp=0.35, grime=None, grime_k=0.22,
                soot=(0.16, 0.15, 0.13)):
    """World macro value (0.07-0.2 cycles/m), dirt toward a soot colour by the cause field,
    and a damp splash band at the base."""
    pos = M(m, "mtlxposition", space="world")
    ps = M(m, "mtlxmultiply", "vector3FA", in1=pos, in2=0.11)
    fr = M(m, "mtlxfractal3d", "float", position=ps, octaves=3)
    mac = M(m, "mtlxremap", "float", **{"in": fr}, inlow=-0.5, inhigh=0.5,
            outlow=1.0 - macro_amp, outhigh=1.0 + macro_amp)
    col = M(m, "mtlxmultiply", "color3FA", in1=col, in2=mac)
    if grime is not None:
        col = M(m, "mtlxmix", "color3", fg=soot, bg=col,
                mix=M(m, "mtlxmultiply", "float", in1=grime, in2=grime_k))
        rough = M(m, "mtlxadd", "float", in1=rough,
                  in2=M(m, "mtlxmultiply", "float", in1=grime, in2=0.04))
    py = M(m, "mtlxseparate3v", **{"in": pos})
    pn = M(m, "mtlxmultiply", "vector3FA", in1=pos, in2=3.5)
    nz = M(m, "mtlxfractal3d", "float", position=pn, octaves=4)
    top = M(m, "mtlxremap", "float", **{"in": nz}, inlow=-0.5, inhigh=0.5, outlow=0.3,
            outhigh=0.85)
    edge = M(m, "mtlxsubtract", "float", in1=top, in2=0.2)    # a ragged front 20 cm wide
    band = M(m, "mtlxsmoothstep", "float", **{"in": (py, 1)}, low=top, high=edge)
    bk = M(m, "mtlxmultiply", "float", in1=band, in2=damp)
    col = M(m, "mtlxmix", "color3", fg=(0.13, 0.125, 0.11), bg=col, mix=bk)
    rough = M(m, "mtlxsubtract", "float", in1=rough,
              in2=M(m, "mtlxmultiply", "float", in1=band, in2=0.10))
    return col, rough


def panel_tint(m, amp=0.05):
    """Re-randomise per-panel tone in world space from the panel index (0.9 x 1.8 m), so the
    3.6 m tile's own panel tones do not repeat: cell noise of st / (0.9, 1.8)."""
    tc = M(m, "mtlxtexcoord", "vector2")
    q = M(m, "mtlxdivide", "vector2", in1=tc, in2=(0.9, 1.8))
    c = M(m, "mtlxcellnoise2d", texcoord=q)
    return M(m, "mtlxremap", "float", **{"in": c}, inlow=0.0, inhigh=1.0, outlow=1.0 - amp,
             outhigh=1.0 + amp)


def mat_formed(lib):
    m, s = material(lib, "formed")
    c = uv(m, 3.6)
    base = img(m, f"{TEX}/formed_basecolor.png", c, "color3", srgb=True)
    base = M(m, "mtlxmultiply", "color3FA", in1=base, in2=panel_tint(m))
    rough = img(m, f"{TEX}/formed_roughness.png", c)
    # dirt held in voids and seams (mask G, B) where the cause field is high
    fmask = M(m, "mtlxseparate3c", **{"in": img(m, f"{TEX}/formed_mask.png", c, "color3")})
    g = grime_field(m)
    hold = M(m, "mtlxmax", "float", in1=(fmask, 1), in2=M(m, "mtlxmultiply", "float",
                                                          in1=(fmask, 2), in2=0.5))
    gg = M(m, "mtlxmax", "float", in1=g, in2=M(m, "mtlxmultiply", "float", in1=hold, in2=g))
    col, rough = world_story(m, base, rough, grime=gg, grime_k=0.35,
                             soot=(0.12, 0.115, 0.10))
    link(s, "base_color", col)
    link(s, "specular_roughness", rough)
    nm = M(m, "mtlxnormalmap", **{"in": img(m, f"{TEX}/formed_normal.png", c, "vector3")})
    link(s, "normal", nm)
    s.parm("specular").set(0.5)
    return m


def mat_spray(lib, detail_k=0.75):
    m, s = material(lib, "spray")
    cm, cd = uv(m, 3.6), uv(m, 0.6)
    base = img(m, f"{TEX}/spraymacro_basecolor.png", cm, "color3", srgb=True)
    rough = img(m, f"{TEX}/spraymacro_roughness.png", cm)
    mask = img(m, f"{TEX}/spraymacro_mask.png", cm, "color3")
    sep = M(m, "mtlxseparate3c", **{"in": mask})
    coat = M(m, "mtlxmultiply", "float", in1=(sep, 0), in2=1.5 * detail_k)
    cav = img(m, f"{TEX}/spraydetail_cavity.png", cd)
    dh = img(m, f"{TEX}/spraydetail_height.png", cd)
    # dirt and shade held in the coating's troughs: albedo x (1 - k cavity), k by coat
    g = grime_field(m)
    # trough dirt is not stationary: little on washed wall, a lot where the cause field is
    kk = M(m, "mtlxmultiply", "float", in1=coat, in2=M(m, "mtlxadd", "float", in1=0.35,
                                                       in2=M(m, "mtlxmultiply", "float",
                                                             in1=g, in2=0.6)))
    k = M(m, "mtlxmultiply", "float", in1=cav, in2=kk)
    col = M(m, "mtlxmultiply", "color3FA", in1=base,
            in2=M(m, "mtlxsubtract", "float", in1=1.0, in2=k))
    crack_dirt = M(m, "mtlxmultiply", "float", in1=(sep, 2), in2=0.15)
    col = M(m, "mtlxmix", "color3", fg=(0.2, 0.19, 0.17), bg=col, mix=crack_dirt)
    rough = M(m, "mtlxadd", "float", in1=rough,
              in2=M(m, "mtlxmultiply", "float", in1=cav, in2=0.06))
    col, rough = world_story(m, col, rough, macro_amp=0.04, damp=0.25, grime=g, grime_k=0.18,
                             soot=(0.20, 0.19, 0.165))
    link(s, "base_color", col)
    link(s, "specular_roughness", rough)
    mn = M(m, "mtlxnormalmap", **{"in": img(m, f"{TEX}/spraymacro_normal.png", cm, "vector3")})
    bh = M(m, "mtlxmultiply", "float", in1=dh, in2=M(m, "mtlxmultiply", "float", in1=coat,
                                                     in2=0.0009))
    bump = M(m, "mtlxbump", height=bh, normal=mn)
    bump.parm("scale").set(1.0)
    link(s, "normal", bump)
    s.parm("specular").set(0.5)
    return m


def mat_v6spray(lib):
    """Round-6 painted_wall in short: flat colour, v6 spray normal at 2 m, scale 0.6."""
    m, s = material(lib, "v6spray")
    c = uv(m, 2.0)
    col = M(m, "mtlxconstant", "color3", value=(0.60, 0.585, 0.545))
    ao = img(m, f"{V6TEX}/spray_ao.png", c)
    cav = M(m, "mtlxremap", "float", **{"in": ao}, inlow=0.0, inhigh=1.0, outlow=0.95,
            outhigh=1.0)
    col = M(m, "mtlxmultiply", "color3FA", in1=col, in2=cav)
    col, rough = world_story(m, col, M(m, "mtlxconstant", "float", value=0.86),
                             grime=grime_field(m), grime_k=0.18, soot=(0.20, 0.19, 0.165))
    link(s, "base_color", col)
    link(s, "specular_roughness", rough)
    nm = M(m, "mtlxnormalmap", **{"in": img(m, f"{V6TEX}/spray_normal.png", c, "vector3")})
    nm.parm("scale").set(0.6)
    link(s, "normal", nm)
    s.parm("specular").set(0.4)
    return m


def mat_v6concrete(lib):
    m, s = material(lib, "v6concrete")
    c = uv(m, 2.4)
    base = img(m, f"{V6TEX}/concrete_basecolor.png", c, "color3", srgb=True)
    col, rough = world_story(m, base, img(m, f"{V6TEX}/concrete_roughness.png", c),
                             grime=grime_field(m), grime_k=0.35, soot=(0.12, 0.115, 0.10))
    link(s, "base_color", col)
    link(s, "specular_roughness", rough)
    link(s, "normal", M(m, "mtlxnormalmap",
                        **{"in": img(m, f"{V6TEX}/concrete_normal.png", c, "vector3")}))
    s.parm("specular").set(0.35)
    return m


def mat_ground(lib):
    m, s = material(lib, "ground")
    pos = M(m, "mtlxposition", space="world")
    fr = M(m, "mtlxfractal3d", "float", position=M(m, "mtlxmultiply", "vector3FA", in1=pos,
                                                   in2=3.0), octaves=4)
    v = M(m, "mtlxremap", "float", **{"in": fr}, inlow=-0.5, inhigh=0.5, outlow=0.07,
          outhigh=0.11)
    link(s, "base_color", M(m, "mtlxconvert", "floatcolor3", **{"in": v}))
    s.parm("specular_roughness").set(0.9)
    return m


# ----------------------------------------------------------------------------- scene
def geo():
    obj = hou.node("/obj")
    g = obj.createNode("geo", "wallgeo")
    wall = g.createNode("grid", "wall")
    wall.parm("orient").set("xy")
    wall.parmTuple("size").set((14.4, 5.4))
    wall.parmTuple("t").set((0.0, 2.7, 0.0))
    wall.parm("rows").set(2)
    wall.parm("cols").set(2)
    wr = g.createNode("attribwrangle", "uv_m")
    wr.setInput(0, wall)
    wr.parm("class").set("point")
    wr.parm("snippet").set("v@uv = set(@P.x + 7.2, @P.y, 0);")   # uv in metres
    wp = g.createNode("attribwrangle", "wpath")
    wp.setInput(0, wr)
    wp.parm("class").set("primitive")
    wp.parm("snippet").set("s@path = 'wall';")   # relative: becomes /walls/wall
    gr = g.createNode("grid", "ground")
    gr.parmTuple("size").set((40.0, 40.0))
    gr.parmTuple("t").set((0.0, 0.0, 12.0))
    gw = g.createNode("attribwrangle", "gpath")
    gw.setInput(0, gr)
    gw.parm("class").set("primitive")
    gw.parm("snippet").set("s@path = 'ground';")
    mg = g.createNode("merge")
    mg.setInput(0, wp)
    mg.setInput(1, gw)
    out = g.createNode("output")
    out.setInput(0, mg)
    out.setDisplayFlag(True)
    return out


VIEWS = {  # camera t, r (deg), focal mm, horizontal aperture mm
    "close": ((1.1, 1.55, 2.4), (-2.0, 14.0, 0.0), 35.0, 36.0),
    "bay": ((0.0, 2.6, 9.0), (0.0, 0.0, 0.0), 35.0, 36.0),
    "graze": ((3.3, 1.6, 1.4), (-4.0, 52.0, 0.0), 35.0, 36.0),
}


def build_stage():
    out = geo()
    st = hou.node("/stage")
    si = st.createNode("sopimport", "walls")
    si.parm("soppath").set(out.path())
    si.parm("pathattr").set("path") if si.parm("pathattr") else None
    lib = st.createNode("materiallibrary", "mats")
    lib.setInput(0, si)
    {"formed": mat_formed, "spray": mat_spray, "v6spray": mat_v6spray,
     "v6concrete": mat_v6concrete}[SET](lib)
    mat_ground(lib)
    am = st.createNode("assignmaterial", "assign")
    am.setInput(0, lib)
    am.parm("nummaterials").set(2)
    am.parm("primpattern1").set("/walls/wall")
    am.parm("matspecpath1").set(f"/materials/{SET}")
    am.parm("primpattern2").set("/walls/ground")
    am.parm("matspecpath2").set("/materials/ground")
    cam = st.createNode("camera", "cam")
    cam.setInput(0, am)
    t, r, fl, ap = VIEWS[VIEW]
    for k, v in zip(("tx", "ty", "tz"), t):
        cam.parm(k).set(v)
    for k, v in zip(("rx", "ry", "rz"), r):
        cam.parm(k).set(v)
    cam.parm("focalLength").set(fl)
    cam.parm("horizontalAperture").set(ap)
    cam.parm("verticalAperture").set(ap * 9.0 / 16.0)
    cam.parm("primpath").set("/cameras/cam")
    last = cam
    dome = st.createNode("domelight::3.0", "sky")
    dome.setInput(0, last)
    last = dome
    if LIGHT == "overcast":
        dome.parm("xn__inputsintensity_i0a").set(1.0)
        for c, v in zip("rgb", (0.93, 0.95, 1.0)):
            dome.parm(f"xn__inputscolor_zta{c}").set(v)
    else:
        dome.parm("xn__inputsintensity_i0a").set(0.32)
        for c, v in zip("rgb", (0.75, 0.85, 1.0)):
            dome.parm(f"xn__inputscolor_zta{c}").set(v)
        sun = st.createNode("distantlight::2.0", "sun")
        sun.setInput(0, last)
        sun.parm("rx").set(-38.0)     # elevation 38 deg
        sun.parm("ry").set(-70.0)     # from the left, about 70 deg off the wall normal
        sun.parm("xn__inputsintensity_i0a").set(3.2)
        sun.parm("xn__inputsangle_zta").set(0.53)
        for c, v in zip("rgb", (1.0, 0.95, 0.86)):
            sun.parm(f"xn__inputscolor_zta{c}").set(v)
        last = sun
    krs = st.createNode("karmarendersettings", "krs")
    krs.setInput(0, last)
    krs.parm("camera").set("/cameras/cam")
    # resolutiony is locked (hou.PermissionError) even after res_mode "manual"; keep the
    # default autoheight and let the camera aperture (16:9) set the height
    krs.parm("resolutionx").set(RESX)
    krs.parm("engine").set("cpu")
    krs.parm("pathtracedsamples").set(SPP)
    krs.parm("samplesperpixel").set(SPP)
    pic = f"{OUT}/{SET}_{VIEW}_{LIGHT}.exr"
    krs.parm("picture").set(pic)
    rop = st.createNode("usdrender_rop", "rop")
    rop.setInput(0, krs)
    return rop, pic, st


def exr_to_npy(pic):
    """Read the EXR with OpenImageIO (ships with Houdini; a Copernicus file COP created from
    Python shows no outputs until its AOVs are set up), save linear RGB as .npy."""
    import OpenImageIO as oiio
    a = oiio.ImageBuf(pic).get_pixels(oiio.FLOAT)
    np.save(pic[:-4] + ".npy", a[..., :3].astype(np.float32))
    return a.shape


if __name__ == "__main__":
    rop, pic, st = build_stage()
    t0 = time.time()
    rop.parm("execute").pressButton()
    dt = time.time() - t0
    ok = os.path.exists(pic)
    print("rendered", pic, ok, "%.0fs" % dt, rop.errors() or "")
    if ok:
        print("npy", exr_to_npy(pic))
