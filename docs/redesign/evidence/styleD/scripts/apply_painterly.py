#!/usr/bin/env hython
"""apply_painterly.py - round D: surface-space painterly layers on the danchi MaterialX materials,
then Karma renders with AOVs. The hip is loaded read-only and is never saved.

Styles (all optional layers over the realistic material; `none` is the realistic baseline):
  none   the scene as it is.
  t1     task 1, anime-background brush layer: tiling Copernicus stroke texture (build_brush_tex.py
         "strokes", 4 m tile) projected in world space, stroke direction from the surface (vertical
         on walls, along the slab on slab edges and parapets). Per stroke: value +-VAL, hue +-HUE deg,
         saturation +-SAT, plus a faint bump and roughness from the paint height.
  t2     task 2, "hyper-real painterly" after Ruan Jia: world-space hue-drift field (blue<->green,
         warm zones), saturated lift of the darks through a small coloured emission (shadows keep a
         saturated, cool-shifted colour instead of going grey), warm shift on sun-facing faces,
         high-frequency multi-hue stroke detail (build_brush_tex.py "detail", 1.5 m tile) in albedo,
         bump and roughness, concentrated around a focal point.
Ablations for t2: --no-drift, --no-lift, --no-detail; --keyfill also recolours the lights
(warm key, saturated cool fill) - a lighting change, so it is its own comparison.

Engine portability (the looks are destined for Unreal / Godot):
  - stroke and detail textures: tiling textures (baked from Copernicus); projected here by world
    position (runtime: Unreal WorldAlignedTexture-style, Godot world triplanar) or baked into a
    piece's own UVs with bake_piece.py;
  - sdir (stroke direction), pd_tint (hue drift x sun warmth), pd_liftc, pd_lift, pd_famp: vertex
    attributes written in SOPs (export as vertex colour / UV channels);
  - HSV and emission maths: standard material maths and the standard emissive input;
  - no AOV, no screen-space post, no Karma-only node.

  hython apply_painterly.py <scene.hip> <style> <out_dir> [--cams cam_hero,cam_facade] [--spp 32]
         [--tex <dir with brush_*.exr>] [--set key=value ...] [--save-copy copy.hiplc]

Every node and parm name was read in Houdini 22.0.466. Numbers carry [S]/[I] tags in the note
docs/redesign/research/rD-painterly-surface.md.
"""
import argparse
import os
import time

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, "tex")

# --------------------------------------------------------------------------------------------
# Parameters. Amplitudes are per stroke (texture values are -1..1, roughly uniform).
# --------------------------------------------------------------------------------------------
P = dict(
    # task 1 [I; the user's brief: about +-2-4 % value, +-2-5 deg hue, mild saturation]
    t1_tile=4.0, t1_val=0.03, t1_hue=4.0, t1_sat=0.05, t1_temp=0.010,
    t1_bump=0.0015, t1_rough=0.04,
    # task 2
    drift_freq=0.085,            # 1/m: about 12 m features across a 60 m facade [I]
    warm_freq=0.045,             # 1/m: warm/cool zones about 20 m [I]
    drift_amt=1.0,               # mix of the drift multipliers below
    drift_blue=(0.93, 0.995, 1.09), drift_green=(0.94, 1.035, 0.975), drift_warm=(1.07, 1.0, 0.90),
    lift=0.040,                  # emission per unit albedo: lifts darks with saturated colour [S/P Ruan Jia]
    lift_cool=(0.35, 0.55, 1.0), lift_teal=(0.25, 0.75, 0.85), lift_violet=(0.55, 0.40, 1.0),
    lift_soffit=1.6,             # stronger in soffits (normal down), a cavity proxy [I]
    sun_warm=(1.035, 1.0, 0.955),  # sun-facing faces warm [S/2 warm accents; I]
    det_tile=1.5, det_val=0.06, det_hue=12.0, det_sat=0.15, det_temp=0.03,
    det_bump=0.002, det_rough=0.06,
    det_floor=0.45, focal=(5.0, 9.0, 6.0), focal_r=32.0,   # detail falls to 45 % away from focus [S/P detail at focus; I numbers]
    # warm key against a cold blue fill: the user picked dusk for "warm light against cold blue
    # shadows" (round C page); here as light colours, which an engine has natively [I values]
    key=(1.0, 0.82, 0.60), fill=(0.50, 0.68, 1.0), fill_gain=1.25,
)
STYLED = ("conc", "conc_raw", "roof", "steel")
SLAB_PARTS = ("slab_edge", "parapet_bal", "parapet_cor", "plinth", "coping")
SUN_L = (-0.567548, 0.469472, 0.676377)   # direction to the sun, from /obj/sun (read in this hip)


def N(mb, typ, name, sig=None, parms=None, inputs=None):
    n = mb.node(name)
    if n is None:
        n = mb.createNode(typ, name)
    if sig:
        n.parm("signature").set(sig)
    for k, v in (parms or {}).items():
        pt = None
        if sig and sig not in ("float", "default") and isinstance(v, (tuple, list)):
            pt = n.parmTuple(k + "_" + sig)
        if pt is None:
            pt = n.parmTuple(k)
        if pt is None:
            raise RuntimeError("%s %s: no parm %s" % (typ, name, k))
        pt.set(v if isinstance(v, (tuple, list)) else (v,))
    for k, v in (inputs or {}).items():
        src, out = (v if isinstance(v, tuple) else (v, 0))
        n.setNamedInput(k, src, out)
    return n


def f(mb, name, v):
    return N(mb, "mtlxconstant", name, sig="float", parms={"value": v})


def c3(mb, name, v):
    return N(mb, "mtlxconstant", name, sig="color3", parms={"value_color3": v})


def mul(mb, name, a, b, sig="float"):
    return N(mb, "mtlxmultiply", name, sig=sig, inputs={"in1": a, "in2": b})


def add(mb, name, a, b, sig="float"):
    return N(mb, "mtlxadd", name, sig=sig, inputs={"in1": a, "in2": b})


def ext(mb, name, src, i, sig="vector4"):
    return N(mb, "mtlxextract", name, sig=sig, parms={"index": i}, inputs={"in": src})


def conn(ss, name):
    c = ss.inputConnectors()[ss.inputNames().index(name)]
    return (c[0].inputNode(), c[0].outputIndex()) if c else None


def surface_uv(mb, tile, tag):
    """World-space planar UV chosen by the dominant normal axis; for slab-like parts (primvar
    sdir = 1) U and V swap so strokes run along the slab. Texture V is the stroke direction."""
    P_ = N(mb, "mtlxposition", "pd_P", parms={"space": "world"})
    Nw = N(mb, "mtlxnormal", "pd_N", parms={"space": "world"})
    an = N(mb, "mtlxabsval", "pd_absN", sig="vector3", inputs={"in": Nw})
    ax, ay, az = (ext(mb, "pd_a" + c, an, i, "vector3") for i, c in enumerate("xyz"))
    px, py, pz = (ext(mb, "pd_p" + c, P_, i, "vector3") for i, c in enumerate("xyz"))
    uvx = N(mb, "mtlxcombine2", "pd_uvx", sig="vector2", inputs={"in1": pz, "in2": py})
    uvz = N(mb, "mtlxcombine2", "pd_uvz", sig="vector2", inputs={"in1": px, "in2": py})
    uvy = N(mb, "mtlxcombine2", "pd_uvy", sig="vector2", inputs={"in1": px, "in2": pz})
    wall = N(mb, "mtlxifgreater", "pd_wall", sig="vector2",
             inputs={"value1": ax, "value2": az, "in1": uvx, "in2": uvz})
    mxz = N(mb, "mtlxmax", "pd_axz", sig="float", inputs={"in1": ax, "in2": az})
    uv = N(mb, "mtlxifgreater", "pd_uv0", sig="vector2",
           inputs={"value1": ay, "value2": mxz, "in1": uvy, "in2": wall})
    u, v = ext(mb, "pd_u", uv, 0, "vector2"), ext(mb, "pd_v", uv, 1, "vector2")
    sw = N(mb, "mtlxcombine2", "pd_uvswap", sig="vector2", inputs={"in1": v, "in2": u})
    sdir = N(mb, "mtlxgeompropvalue", "pd_sdir", sig="float", parms={"geomprop": "sdir"})
    sdir.parm("default").set(0.0)
    uvs = N(mb, "mtlxmix", "pd_uv", sig="vector2", inputs={"fg": sw, "bg": uv, "mix": sdir})
    return uvs, P_, Nw


def stroke_tex(mb, uvs, path, tile, tag):
    k = N(mb, "mtlxconstant", "pd_tile_" + tag, sig="float", parms={"value": 1.0 / tile})
    tc = N(mb, "mtlxmultiply", "pd_tc_" + tag, sig="vector2FA", inputs={"in1": uvs, "in2": k})
    img = N(mb, "mtlximage", "pd_img_" + tag, sig="vector4",
            parms={"file": path, "uaddressmode": "periodic", "vaddressmode": "periodic",
                   "filtertype": "linear"}, inputs={"texcoord": tc})
    if img.parm("signature").eval() != "vector4":
        raise RuntimeError("mtlximage signature did not take vector4")
    return [ext(mb, "pd_%s_%s" % (c, tag), img, i) for i, c in enumerate("rgba")]


def hsv_mod(mb, col, r, g, b, val, hue_deg, sat, temp, tag, amp=None):
    """value x (1 + val*r), hue + hue_deg*g, saturation x (1 + sat*b); temperature tilt
    (R up, B down by temp*g) so the hue offset also shows on near-grey concrete."""
    def scaled(x, k, nm):
        y = mul(mb, nm, x, f(mb, nm + "_k", k))
        return mul(mb, nm + "_amp", y, amp) if amp is not None else y
    hsv = N(mb, "mtlxrgbtohsv", "pd_hsv_" + tag, sig="color3", inputs={"in": col})
    h, s, v = (N(mb, "mtlxextract", "pd_%s_%s" % (c, tag), sig="color3", parms={"index": i},
                 inputs={"in": hsv}) for i, c in enumerate("hsv"))
    h2 = add(mb, "pd_h2_" + tag, h, scaled(g, hue_deg / 360.0, "pd_dh_" + tag))
    s2 = mul(mb, "pd_s2_" + tag, s, add(mb, "pd_sm_" + tag, scaled(b, sat, "pd_ds_" + tag), f(mb, "pd_one_s" + tag, 1.0)))
    v2 = mul(mb, "pd_v2_" + tag, v, add(mb, "pd_vm_" + tag, scaled(r, val, "pd_dv_" + tag), f(mb, "pd_one_v" + tag, 1.0)))
    hsv2 = N(mb, "mtlxcombine3", "pd_hsv2_" + tag, sig="color3", inputs={"in1": h2, "in2": s2, "in3": v2})
    rgb = N(mb, "mtlxhsvtorgb", "pd_rgb_" + tag, sig="color3", inputs={"in": hsv2})
    t = scaled(g, temp, "pd_dt_" + tag)
    one = f(mb, "pd_one_t" + tag, 1.0)
    tr = add(mb, "pd_tr_" + tag, one, t)
    tb = N(mb, "mtlxsubtract", "pd_tb_" + tag, sig="float", inputs={"in1": one, "in2": t})
    tilt = N(mb, "mtlxcombine3", "pd_tilt_" + tag, sig="color3", inputs={"in1": tr, "in2": one, "in3": tb})
    return mul(mb, "pd_col_" + tag, rgb, tilt, "color3")


def gpv(mb, name, prop, sig, default):
    n = N(mb, "mtlxgeompropvalue", name, sig=sig, parms={"geomprop": prop})
    if sig == "float":
        n.parm("default").set(default)
    else:
        n.parmTuple("default_" + sig).set(default)
    return n


# VEX for the t2 vertex attributes. World-space fields, evaluated once on the geometry, so they
# travel to an engine as vertex colour (pd_tint, pd_liftc) and spare UV channels (pd_famp,
# pd_lift). Run over vertices so the per-face normal (vertex N) is used.
T2_VEX = r'''
float ss(float a; float b; float x) { float t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
float fbm01(const vector q0; int oct) {
    // TRAP: VEX passes arguments by reference; modifying a parameter fed by an expression
    // fails with "Read-only expression given for read/write parameter". Copy it first.
    vector q = q0;
    float s = 0, w = 0, a = 1;
    for (int i = 0; i < oct; i++) { s += a * (noise(q) - 0.5); w += a; q = q * 2.03 + {5.3, 1.7, 9.1}; a *= 0.5; }
    return clamp(fit(s / w, -0.22, 0.22, 0, 1), 0, 1);
}
vector p = v@P;
vector n = normalize(v@N);
float n1 = fbm01(p * chf("drift_freq") + {13.1, 7.7, 2.9}, 3);
float n2 = fbm01(p * chf("warm_freq") + {41.3, 3.1, 17.9}, 2);
float n3 = fbm01(p * chf("drift_freq") * 0.8 + {71.0, 5.0, 33.0}, 3);
vector cool = lerp(chv("drift_blue"), chv("drift_green"), ss(0.25, 0.75, n1));
vector tint = lerp(cool, chv("drift_warm"), ss(0.58, 0.80, n2));
tint = lerp({1, 1, 1}, tint, chf("drift_amt"));
float ndl = dot(n, chv("sun_L"));
tint *= lerp({1, 1, 1}, chv("sun_warm"), ss(0.0, 0.4, ndl));
v@pd_tint = tint;
vector a1 = lerp(chv("lift_cool"), chv("lift_teal"), ss(0.5, 0.85, n3));
v@pd_liftc = lerp(a1, chv("lift_violet"), 1 - ss(0.1, 0.35, n3));
f@pd_liftn = n3;   // the scalar behind pd_liftc: an engine rebuilds the colour from it (UV2.y)
f@pd_lift = chf("lift") / 0.5 * lerp(1.0, chf("lift_soffit"), ss(0.3, 0.8, -n.y));
float d = distance(p, chv("focal"));
f@pd_famp = lerp(chf("det_floor"), 1.0, 1 - ss(chf("focal_r") * 0.25, chf("focal_r"), d));
'''


def t2_attrs(obj, name="pd_t2attrs"):
    """Insert the t2 attribute wrangle before obj/OUT; parms from P as spare parms."""
    outn = obj.node("OUT")
    w = obj.createNode("attribwrangle", name)
    w.setInput(0, outn.inputs()[0])
    w.parm("class").set("vertex")
    w.parm("snippet").set(T2_VEX)
    ptg = w.parmTemplateGroup()
    vals = dict(P, sun_L=SUN_L)
    for k in ("drift_freq", "warm_freq", "drift_amt", "lift", "lift_soffit", "det_floor", "focal_r"):
        ptg.append(hou.FloatParmTemplate(k, k, 1))
    for k in ("drift_blue", "drift_green", "drift_warm", "sun_L", "sun_warm", "lift_cool", "lift_teal",
              "lift_violet", "focal"):
        ptg.append(hou.FloatParmTemplate(k, k, 3))
    w.setParmTemplateGroup(ptg)
    for k, v in vals.items():
        if w.parmTuple(k) is not None:
            w.parmTuple(k).set(v if isinstance(v, (tuple, list)) else (v,))
    # colour type info so USD writes color3f primvars (MaterialX geompropvalue color3)
    w2 = obj.createNode("attribwrangle", name + "_ti")
    w2.setInput(0, w)
    w2.parm("class").set("detail")
    w2.parm("snippet").set('setattribtypeinfo(0, "vertex", "pd_tint", "color");\n'
                           'setattribtypeinfo(0, "vertex", "pd_liftc", "color");')
    outn.setInput(0, w2)
    return w


def stylise(mb, style, cfg, tex):
    ss = mb.node("mtlxstandard_surface")
    bc, rough, nrm = conn(ss, "base_color"), conn(ss, "specular_roughness"), conn(ss, "normal")
    if bc is None:
        return False
    col = bc
    uvs, P_, Nw = surface_uv(mb, 1.0, "s")
    if rough is None:
        rough = f(mb, "pd_rough0", ss.parm("specular_roughness").eval())
    h_extra, r_extra = [], []
    if style == "t1":
        r, g, b, a = stroke_tex(mb, uvs, os.path.join(tex, "brush_strokes.exr").replace("\\", "/"), P["t1_tile"], "t1")
        col = hsv_mod(mb, col, r, g, b, P["t1_val"], P["t1_hue"], P["t1_sat"], P["t1_temp"], "t1")
        h_extra.append((a, P["t1_bump"]))
        r_extra.append((a, -P["t1_rough"]))
    if style == "t2":
        # Every low-frequency field is a VERTEX ATTRIBUTE written by the SOP wrangle in
        # t2_attrs() (engine-portable: it exports as vertex colour / UV-set data). The
        # material only reads them; nothing here needs Karma-specific shading.
        if cfg.get("drift", True):
            # 1. hue-drift field (blue <-> green, warm zones) x warm on sun-facing faces
            tint = gpv(mb, "pd_tint_in", "pd_tint", "color3", (1.0, 1.0, 1.0))
            col = mul(mb, "pd_col_drift", col, tint, "color3")
        if cfg.get("detail", True):
            # 3. high-frequency multi-hue stroke detail (tiling texture), amplitude from the
            #    focal-falloff attribute
            r, g, b, a = stroke_tex(mb, uvs, os.path.join(tex, "brush_detail.exr").replace("\\", "/"), P["det_tile"], "t2")
            amp = gpv(mb, "pd_famp_in", "pd_famp", "float", P["det_floor"])
            col = hsv_mod(mb, col, r, g, b, P["det_val"], P["det_hue"], P["det_sat"], P["det_temp"], "t2", amp=amp)
            h_extra.append((mul(mb, "pd_dh_amp", a, amp), P["det_bump"]))
            r_extra.append((mul(mb, "pd_dr_amp", a, amp), -P["det_rough"]))
        if cfg.get("lift", True):
            # 2. lifted, saturated darks: emission = albedo luminance x saturated colour x k.
            #    Emission is a standard PBR input (Unreal Emissive Color, Godot EMISSION).
            liftc = gpv(mb, "pd_liftc_in", "pd_liftc", "color3", (0.0, 0.0, 0.0))
            liftk = gpv(mb, "pd_lift_in", "pd_lift", "float", 0.0)
            lum = N(mb, "mtlxluminance", "pd_alb_lum", sig="color3", inputs={"in": col})
            k = mul(mb, "pd_lift_k", lum, liftk)
            emc = N(mb, "mtlxmultiply", "pd_emc", sig="color3FA", inputs={"in1": liftc, "in2": k})
            ss.setNamedInput("emission_color", emc, 0)
            ss.parm("emission").set(1.0)
    ss.setNamedInput("base_color", col if not isinstance(col, tuple) else col[0], 0 if not isinstance(col, tuple) else col[1])
    rr = rough
    for i, (h, k) in enumerate(r_extra):
        d = N(mb, "mtlxsubtract", "pd_rh%d" % i, sig="float", inputs={"in1": h, "in2": f(mb, "pd_rh%d_m" % i, 0.8)})
        rr = add(mb, "pd_rough%d" % i, rr, mul(mb, "pd_rk%d" % i, d, f(mb, "pd_rk%d_k" % i, k)))
    if r_extra:
        rr = N(mb, "mtlxclamp", "pd_rough_c", sig="float", parms={"low": 0.05, "high": 1.0}, inputs={"in": rr})
        ss.setNamedInput("specular_roughness", rr, 0)
    nn = nrm
    for i, (h, k) in enumerate(h_extra):
        bm = N(mb, "mtlxbump", "pd_bump%d" % i, parms={"scale": k}, inputs={"height": h})
        if nn is not None:
            bm.setNamedInput("normal", nn[0], nn[1])
        nn = (bm, 0)
    if h_extra:
        ss.setNamedInput("normal", nn[0], nn[1])
    return True


def setup(hip, style, cfg, tex):
    try:
        hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    except hou.LoadWarning as e:
        print("load warning:", str(e)[:200])
    done = []
    if style != "none":
        # primvar sdir: 1 on slab-like parts so strokes run along the slab
        for objp in ("/obj/danchi", "/obj/estate"):
            obj = hou.node(objp)
            outn = obj.node("OUT")
            w = obj.createNode("attribwrangle", "pd_sdir")
            w.setInput(0, outn.inputs()[0])
            w.parm("class").set("primitive")
            w.parm("snippet").set("string sl[] = {%s};\nf@sdir = find(sl, s@part) >= 0 ? 1.0 : 0.0;"
                                  % ", ".join('"%s"' % p for p in SLAB_PARTS))
            outn.setInput(0, w)
            if style == "t2":
                t2_attrs(obj)
        # TRAP: the matnets live inside locked sk3::danchi HDA instances, and
        # hou.node("/obj").allSubChildren() does not descend into locked HDAs. Unlock the
        # instances in memory (allowEditingOfContents; the hip is never saved), then edit.
        for gp in ("/obj/danchi/gen", "/obj/estate/b0", "/obj/estate/b1", "/obj/estate/b2"):
            gen = hou.node(gp)
            if gen.isLockedHDA():
                gen.allowEditingOfContents()
            for m in gen.node("materials").children():
                if m.name() in STYLED and stylise(m, style, cfg, tex):
                    done.append(m.path())
    if cfg.get("keyfill"):
        sun, sky = hou.node("/obj/sun"), hou.node("/obj/sky")
        sun.parmTuple("light_color").set(P["key"])
        sky.parmTuple("light_color").set(P["fill"])
        sky.parm("light_intensity").set(sky.parm("light_intensity").eval() * P["fill_gain"])
    return done


def render(cams, outdir, spp, tag, resx=0):
    st = hou.node("/stage")
    si = st.createNode("sceneimport::2.0", "pd_imp")
    si.parm("objects").set("*")  # TRAP: empty from Python, imports nothing
    si.cook(force=True)
    campaths = [str(p.GetPath()) for p in si.stage().Traverse() if p.GetTypeName() == "Camera"]
    krs = st.createNode("karmarendersettings", "pd_krs")
    krs.setInput(0, si)
    for k, v in dict(engine="cpu", pathtracedsamples=spp, samplesperpixel=spp, beauty=1,
                     albedo=1, hitPz=1, hitN=1).items():
        krs.parm(k).set(v)
    if resx:
        krs.parm("resolutionx").set(resx)
    rop = st.createNode("usdrender_rop", "pd_rop")
    rop.setInput(0, krs)
    os.makedirs(outdir, exist_ok=True)
    res = []
    for cam in cams:
        cp = [c for c in campaths if c.endswith("/" + cam)][0]
        krs.parm("camera").set(cp)
        pic = "%s/%s_%s.exr" % (outdir, tag, cam)
        krs.parm("picture").set(pic)
        t0 = time.time()
        rop.parm("execute").pressButton()
        print("rendered", pic, os.path.exists(pic), "%.0fs" % (time.time() - t0))
        res.append(pic)
    return res


def to_jpg(exr, jpg, q=90):
    net = hou.node("/img/pd_jpg") or hou.node("/img").createNode("copnet", "pd_jpg")
    fi = net.createNode("file")
    fi.parm("filename").set(exr)
    fi.parm("addaovs").pressButton()  # TRAP: no outputs until pressed
    names = list(fi.outputNames())
    cs = fi.createOutputNode("channelsplit") if False else net.createNode("channelsplit")
    cs.setInput(0, fi, names.index("C"))
    cj = net.createNode("channeljoin")
    cj.parm("signature").set("f3")
    for i in range(3):
        cj.setInput(i, cs, i)
    r = net.createNode("rop_image")
    r.setInput(0, cj)
    r.parm("copoutput").set(jpg)
    r.parm("vm_image_jpeg_quality").set(q)
    r.parm("execute").pressButton()
    return os.path.getsize(jpg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hip")
    ap.add_argument("style", choices=("none", "t1", "t2"))
    ap.add_argument("out")
    ap.add_argument("--tag")
    ap.add_argument("--cams", default="cam_hero,cam_facade")
    ap.add_argument("--spp", type=int, default=32)
    ap.add_argument("--resx", type=int, default=0)
    ap.add_argument("--tex", default=TEX)
    ap.add_argument("--no-drift", action="store_true")
    ap.add_argument("--no-lift", action="store_true")
    ap.add_argument("--no-detail", action="store_true")
    ap.add_argument("--keyfill", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--save-copy")
    a = ap.parse_args()
    for kv in a.set:
        k, v = kv.split("=", 1)
        vals = tuple(float(x) for x in v.split(","))
        P[k] = vals if len(vals) > 1 else vals[0]
    cfg = dict(drift=not a.no_drift, lift=not a.no_lift, detail=not a.no_detail, keyfill=a.keyfill)
    done = setup(a.hip, a.style, cfg, a.tex)
    print("styled", len(done), "materials", done[:6])
    if a.save_copy:
        hou.hipFile.save(a.save_copy)  # only ever a copy in round D's own folder
    tag = a.tag or a.style
    for exr in render(a.cams.split(","), a.out, a.spp, tag, a.resx):
        print("jpg", to_jpg(exr, exr[:-4] + ".jpg"))


if __name__ == "__main__":
    main()
