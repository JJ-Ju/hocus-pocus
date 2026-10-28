#!/usr/bin/env hython
"""build_anime_post.py - optional 1980s-90s anime-background stylisation as a Copernicus post.

Round C prototype (docs/redesign/research/rC-anime-background.md). It builds a COP network in
/img/anime_post that turns a realistic render into a painted-background look. The realistic
render stays the default; this is a switchable layer with a `strength` mix back to the original.

Two input modes:
  image  - a beauty JPG/PNG only. Sky, haze and edges come from image heuristics (weaker).
  aov    - a Karma multi-part EXR from karmarendersettings with albedo, hitPz and hitN on.
           Karma names the parts C, albedo, depth (hitPz; 0 = sky) and N (hitN).
           Bands come from lighting = C / albedo, so each material keeps its own value.

Run with hython (Houdini 22.0.466), from a directory that holds no .py files:
  hython build_anime_post.py --beauty in.jpg --out out.jpg [--preset summer_day]
  hython build_anime_post.py --aov-exr cam_aov.exr --out out.jpg --preset summer_day
         [--strength 0.4] [--horizon 0.35] [--before before.jpg] [--save-hip graph.hiplc]
         [--no-haze] [--no-sky] [--lines] [--set sky_zenith=0.2,0.4,0.8 ...]
  --horizon is the horizon height in the frame (0 bottom, 1 top); --strength mixes back to
  the original (0 = the realistic render, 0.4 = mostly realistic, 1 = the full profile).
Images are written by rop_image with its default OCIO conversion (linear in, sRGB JPG out).
Round C evidence: docs/redesign/evidence/styleC/. Reference:
.claude/skills/procedural-materials/references/stylisation-anime.md.

Every node and parm name here was read from Houdini 22.0.466 (hou.copNodeTypeCategory()).
Numbers in PRESETS carry their origin: [S] sourced (see the research note), [I] inference.
"""
import argparse
import os
import sys
import time

import hou

# ---------------------------------------------------------------------------------------------
# Colour keys. Linear RGB. Band levels are irradiance multipliers on the flattened albedo (aov
# mode) or fractions of the lit-wall luminance (image mode).
# ---------------------------------------------------------------------------------------------
PRESETS = {
    # Patlabor-1-like summer day: warm light, cool blue-violet shadows, saturated cerulean sky
    # with cumulus, haze toward a pale horizon. Shadows coloured, never grey [S Yasuda via
    # Animation Obsessive; Blue Protocol CEDEC 2020/21 hue-shifted shadows; Clip Studio 8939].
    "summer_day": dict(
        lit=(1.02, 0.98, 0.90), shadow=(0.36, 0.40, 0.52), deep=(0.16, 0.18, 0.27),
        # thresholds as fractions of the lit level; 3 values per material [S Gurney 3 values];
        # v3 hero street measured: lit 1.15-1.24, sky-lit shadow ~0.25, occluded 0.07-0.12
        t_deep=0.12, t_shadow=0.55,
        # deep zenith: the user preferred it over pale cerulean (0.24, 0.44, 0.80) (review 34),
        # though it drops notan dominance from 1.67 to 1.07 on the v3 hero street (round C)
        sky_zenith=(0.10, 0.25, 0.62), sky_mid=(0.46, 0.62, 0.86), sky_horizon=(0.74, 0.80, 0.86),
        cloud_lit=(0.92, 0.92, 0.90), cloud_shade=(0.52, 0.58, 0.72), cloud_cover=0.25,
        haze=(0.62, 0.70, 0.80), haze_near=40.0, haze_far=650.0, haze_max=0.50,
        line=(1.0, 0.96, 0.86), line_amt=0.55, dark_line_amt=0.25,
        sat=1.10, lift=(0.010, 0.012, 0.024), diffusion=0.07,
        stroke_amt=0.035, wash_amt=0.045, flatten=0.85),
    # Patlabor-2-like winter overcast: muted grey-green, low contrast, flat sky, strong haze.
    "winter_overcast": dict(
        lit=(0.80, 0.81, 0.78), shadow=(0.44, 0.47, 0.50), deep=(0.24, 0.26, 0.29),
        t_deep=0.18, t_shadow=0.60,
        sky_zenith=(0.48, 0.52, 0.55), sky_mid=(0.58, 0.61, 0.62), sky_horizon=(0.70, 0.71, 0.70),
        # overcast: one low-contrast cloud sheet, close to the gradient, or it reads as stains
        cloud_lit=(0.63, 0.65, 0.66), cloud_shade=(0.55, 0.58, 0.60), cloud_cover=0.45,
        haze=(0.66, 0.68, 0.67), haze_near=25.0, haze_far=380.0, haze_max=0.75,
        line=(0.92, 0.92, 0.88), line_amt=0.25, dark_line_amt=0.20,
        sat=0.78, lift=(0.020, 0.022, 0.024), diffusion=0.05,
        stroke_amt=0.030, wash_amt=0.040, flatten=0.80),
    # Dusk grade: orange key, violet shadows, orange-to-indigo sky. A post grade cannot move the
    # sun; pair it with the low-sun lighting preset in the generator (see the reference).
    "dusk": dict(
        lit=(1.10, 0.72, 0.46), shadow=(0.26, 0.24, 0.44), deep=(0.12, 0.11, 0.24),
        t_deep=0.12, t_shadow=0.55,
        sky_zenith=(0.08, 0.09, 0.30), sky_mid=(0.46, 0.27, 0.42), sky_horizon=(1.00, 0.58, 0.32),
        cloud_lit=(1.00, 0.58, 0.42), cloud_shade=(0.30, 0.24, 0.42), cloud_cover=0.38,
        haze=(0.85, 0.55, 0.45), haze_near=40.0, haze_far=600.0, haze_max=0.62,
        line=(1.0, 0.80, 0.55), line_amt=0.60, dark_line_amt=0.25,
        sat=1.05, lift=(0.014, 0.010, 0.030), diffusion=0.10,
        stroke_amt=0.035, wash_amt=0.045, flatten=0.85),
}


class G:
    """Tiny builder: mk(type, inputs, **parms). Inputs are nodes or (node, output_name)."""

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
                o = x[1]
                if isinstance(o, str):  # TRAP: setInput wants an output index, not a name
                    o = list(x[0].outputNames()).index(o)
                n.setInput(i, x[0], o)
            else:
                n.setInput(i, x)
        for k, v in kw.items():
            if n.parm(k) is not None:
                n.parm(k).set(v)
            else:
                n.parmTuple(k).set(v)
        return n

    def const(self, rgb, ref, name=None):
        # constant COP sized by its input; signature f3 for colour
        return self.mk("constant", [ref], name, signature="f3", f3=rgb)

    def ramp_f3(self, n, pos, cols, basis=hou.rampBasis.Linear, parm="ramp"):
        n.parm(parm).set(hou.Ramp((basis,) * len(pos), pos, cols))

    def ramp_f1(self, n, pos, vals, basis=hou.rampBasis.Linear, parm="ramp"):
        n.parm(parm).set(hou.Ramp((basis,) * len(pos), pos, vals))


def file_in(g, path, raw_names=("N", "Pz", "P", "primid", "hitN", "hitPz", "depth")):
    f = g.mk("file", [], "src", filename=path)
    f.parm("addaovs").pressButton()  # TRAP: setting filename from Python adds no outputs
    names = list(f.outputNames())
    for i in range(1, f.parm("aovs").eval() + 1):
        if f.parm("aov%d" % i).eval() in raw_names:
            f.parm("raw%d" % i).set(1)
    return f, names


def pick(names, *cands):
    for c in cands:
        for n in names:
            if n == c:
                return n
    for c in cands:
        for n in names:
            if c.lower() in n.lower():
                return n
    return None


def build(g, args, P):
    """Returns (original_rgb_node, stylised_node, final_node)."""
    mode = "aov" if args.aov_exr else "image"
    f, names = file_in(g, args.aov_exr or args.beauty)
    cname = pick(names, "C", "beauty", "rgba")
    split = g.mk("channelsplit", [(f, cname)], "c_split")
    rgb = g.mk("channeljoin", [(split, 0), (split, 1), (split, 2)], "rgb", signature="f3")
    key = args.key  # lit level (aov: irradiance of a sunlit wall; image: its luminance)

    if mode == "aov":
        alb = (f, pick(names, "albedo"))
        nrm = (f, pick(names, "N", "hitN"))
        pz = (f, pick(names, "Pz", "hitPz", "depth"))
        # sky: Karma depth (hitPz) is 0 where no geometry is hit. Alpha is no use: with the
        # dome light visible to camera it is 1 everywhere (measured, v3 hero street).
        skym = g.mk("remap", [pz], "sky_mask", op="threshold", side="less", threshold=1e-3)
        # 1. painted base colour per material: Kuwahara chain on albedo [S Blender manual: chain
        #    flattens more; size 3-9]. Stains: posterise albedo against its local mean into 3
        #    levels, so physical noise becomes a few hard-edged stain shapes.
        a1 = g.mk("kuwaharafilter", [alb], "alb_kuwa_fine", radius=args.r_fine)
        a2 = g.mk("kuwaharafilter", [a1], "alb_kuwa_base", radius=args.r_base)
        a3 = g.mk("kuwaharafilter", [a2], "alb_kuwa_local", radius=args.r_local)
        la1 = g.mk("mono", [a2], "alb_L")
        la3 = g.mk("mono", [a3], "alb_L_local")
        ratio = g.mk("blend", [la1, la3], "stain_ratio", mode="divide")
        rq = g.mk("remap", [ratio], "stain_levels", useramp=1, inputmin=0.0, inputmax=2.0)
        # ratio 0..2 mapped to 0..1 by inputmin/max; 0.84 -> 0.42, 0.94 -> 0.47, 1.08 -> 0.54
        g.ramp_f1(rq, (0.0, 0.42, 0.47, 0.54), (0.78 / 2, 0.90 / 2, 1.0 / 2, 1.06 / 2),
                  hou.rampBasis.Constant)
        rq2 = g.mk("function", [rq], "stain_x2", func="math", scale=2.0)  # back to 0.78..1.06
        # value-only posterise: gain = level / ratio keeps each small item's hue (laundry,
        # signs) and its value relative to the local mean; only the noise between levels goes
        sg = g.mk("blend", [rq2, ratio], "stain_gain", mode="divide")
        sg = g.mk("clamp", [sg], "stain_gain_clamp", lowerlimit=0.6, upperlimit=1.6)
        albp = g.mk("blend", [a2, sg], "albedo_painted", mode="multiply")
        albp = g.mk("blend", [a2, albp], "albedo_flatten", mode="blend", mask=P["flatten"])
        # 2. lighting bands from C / albedo [I]
        lc = g.mk("mono", [rgb], "C_L")
        lal = g.mk("mono", [alb], "albedo_L")
        lal = g.mk("clamp", [lal], "albedo_floor", lowerlimit=0.03, doupperlimit=0)
        shade = g.mk("blend", [lc, lal], "irradiance", mode="divide")
        # painted shadow shapes: Kuwahara on the irradiance merges 32-spp speckle into shapes
        lum_for_bands = g.mk("kuwaharafilter", [shade], "irradiance_shapes", radius=args.r_shade)
        base_rgb = albp
    else:
        # sky from colour: bluer than red, not dark, above the horizon line [I]
        r_, g_, b_ = (split, 0), (split, 1), (split, 2)
        bmr = g.mk("blend", [b_, r_], "blue_minus_red", mode="subtract")
        sky_c = g.mk("remap", [bmr], "sky_blue", op="threshold", threshold=args.sky_bmr, width=0.01)
        lsk = g.mk("mono", [rgb], "rgb_L")
        sky_l = g.mk("remap", [lsk], "sky_bright", op="threshold", threshold=args.sky_l, width=0.02)
        vr = g.mk("ramp", [rgb], "v_ramp", rampType="vertical", signature="f1")
        above = g.mk("remap", [vr], "above_horizon", op="threshold", threshold=args.horizon,
                     width=0.01)
        skym = g.mk("blend", [sky_c, sky_l], "sky_cl", mode="multiply")
        skym = g.mk("blend", [skym, above], "sky_mask0", mode="multiply")
        # open the mask: removes small blue false positives (laundry) and keeps thin dark
        # wires, which a median filter erased (round C test)
        skym = g.mk("dilateerode", [skym], "sky_open_erode", units="pixels", radius=-4.0)
        skym = g.mk("dilateerode", [skym], "sky_mask", units="pixels", radius=4.0)
        a1 = g.mk("kuwaharafilter", [rgb], "kuwa_fine", radius=args.r_fine)
        a2 = g.mk("kuwaharafilter", [a1], "kuwa_base", radius=args.r_base)
        base_rgb = a2
        # bands follow a coarser, edge-preserving luminance so that stains and grain do not
        # flip bands (they stay as relative detail through the gain); v5 blotched without it
        a_band = g.mk("kuwaharafilter", [a2], "kuwa_band", radius=args.r_band)
        lum_for_bands = g.mk("mono", [a_band], "base_L")

    # 3. hand-cut band edges: wobble the band input with a low-amplitude noise field [I]
    nx = g.mk("fractalnoise", [rgb], "wobble_x", elementsize=0.03, amp=1.0, center=0.0)
    ny = g.mk("fractalnoise", [rgb], "wobble_y", elementsize=0.03, amp=1.0, center=0.0,
              off=(17.3, 4.1))
    wob = g.mk("channeljoin", [nx, ny], "wobble_dir", signature="f2")
    lb = g.mk("blur", [lum_for_bands], "band_soften", units="pixels", size_pixel=1.0)
    lw = g.mk("distort", [lb, wob], "band_wobble", scale=args.wobble)

    # 4. colour key: three bands with their own colours (constant ramp). Input normalised by key.
    ln = g.mk("function", [lw], "band_norm", func="math", func_math="abs", scale=1.0 / key)
    band = g.mk("monotorgb", [ln], "colour_key", inputmin=0.0, inputmax=2.0)
    td, ts = P["t_deep"] / 2.0, P["t_shadow"] / 2.0
    if mode == "aov":
        g.ramp_f3(band, (0.0, td, ts), (P["deep"], P["shadow"], P["lit"]), hou.rampBasis.Constant)
        painted = g.mk("blend", [base_rgb, band], "painted", mode="multiply")
    else:
        # image mode: the band sets the value, the Kuwahara colour keeps the hue (gain = Lq / L)
        lit_l = sum(P["lit"]) / 3.0
        dv, sv = sum(P["deep"]) / 3.0 / lit_l, sum(P["shadow"]) / 3.0 / lit_l
        bandL = g.mk("remap", [ln], "band_value", useramp=1, inputmin=0.0, inputmax=2.0)
        # 4 values for the frame: deep, shadow, light-mid, lit (outputs are x 2 key below)
        g.ramp_f1(bandL, (0.0, td, ts, 0.40), (dv / 2, sv / 2, 0.80 / 2, 1.0 / 2),
                  hou.rampBasis.Constant)
        # the painter picks the lit value: a target, not the render exposure [I]
        target = min(max(key, args.lit_lo), args.lit_hi)
        bandv = g.mk("function", [bandL], "band_value_x2target", func="math", scale=2.0 * target)
        lsafe = g.mk("clamp", [lum_for_bands], "L_floor", lowerlimit=0.004, doupperlimit=0)
        gain = g.mk("blend", [bandv, lsafe], "value_gain", mode="divide")
        gain = g.mk("clamp", [gain], "value_gain_clamp", lowerlimit=0.0, upperlimit=4.0)
        valp = g.mk("blend", [base_rgb, gain], "value_painted", mode="multiply")
        valp = g.mk("blend", [base_rgb, valp], "value_flatten", mode="blend", mask=P["flatten"])
        # tint by band: hard bands, normalised so the lit band keeps the image's own value
        tint = g.mk("monotorgb", [ln], "colour_tint", inputmin=0.0, inputmax=2.0)
        norm = lambda c: tuple(x / (sum(c) / 3.0) for x in c)
        mix = lambda c, k: tuple(1.0 + (x - 1.0) * k for x in norm(c))
        g.ramp_f3(tint, (0.0, td, ts), (mix(P["deep"], 1.0), mix(P["shadow"], 1.0),
                                        mix(P["lit"], 0.5)), hou.rampBasis.Constant)
        painted = g.mk("blend", [valp, tint], "painted", mode="multiply")

    # 5. painted texture: directional strokes + a broad wash instead of photographic grain [I]
    st = g.mk("fractalnoise", [rgb], "strokes", elementsize=0.010, elementscale=(3.0, 0.6),
              amp=P["stroke_amt"], center=1.0, oct=3)
    wa = g.mk("fractalnoise", [rgb], "wash", elementsize=0.25, elementscale=(1.6, 1.0),
              amp=P["wash_amt"], center=1.0, oct=2)
    tex = g.mk("blend", [st, wa], "paint_texture", mode="multiply")
    painted = g.mk("blend", [painted, tex], "painted_tex", mode="multiply")

    # 6. distance simplification and haze
    if mode == "aov":
        far = g.mk("remap", [pz], "far_ramp", inputmin=P["haze_near"], inputmax=P["haze_far"],
                   outputmin=0.0, outputmax=1.0)
        pass  # linear in depth; sqrt over-hazed the 200-300 m blocks (round C test)
    else:
        # fallback: a band around the horizon line stands in for depth [I, weak]
        far = g.mk("remap", [vr], "far_ramp", inputmin=args.horizon - 0.22, inputmax=args.horizon,
                   outputmin=0.0, outputmax=1.0)
        far = g.mk("blend", [far, skym], "far_not_sky", mode="multiply")
        far = g.mk("blend", [far, skym], "far_not_sky2", mode="subtract")
        far = g.mk("clamp", [far], "far_clamp")
    simp = g.mk("kuwaharafilter", [painted], "far_simplify", radius=args.r_base * 1.6)
    painted = g.mk("blend", [painted, simp, far], "distance_simplify", mode="blend")
    if not args.no_haze:
        hz = g.const(P["haze"], rgb, "haze_colour")
        hm = g.mk("function", [far], "haze_amount", func="math", func_math="abs",
                  scale=P["haze_max"])
        painted = g.mk("blend", [painted, hz, hm], "haze", mode="blend")

    # 7. edge highlight lines on lit edges; soft darker colour steps at silhouettes [I]
    litm = g.mk("remap", [ln], "lit_mask", op="threshold", threshold=ts, width=0.01)
    litm = g.mk("blend", [litm, skym], "lit_not_sky", mode="subtract")  # wires next to sky
    litm = g.mk("clamp", [litm], "lit_not_sky_clamp")
    litm = g.mk("dilateerode", [litm], "lit_mask_grow", units="pixels", radius=1.5)
    if mode == "aov":
        en = g.mk("edgedetectnormal", [nrm], "edges_normal", normtolerance=args.norm_tol,
                  thickscale=args.line_px)
        ed = g.mk("edgedetectdepth", [pz], "edges_depth", depthtolerance=args.depth_tol,
                  thickscale=args.line_px)
        # the edge layers peak around 0.2-0.4, so stretch them before use (measured) [I]
        en = g.mk("remap", [en], "edges_normal_norm", inputmin=args.edge_lo, inputmax=args.edge_hi,
                  useramp=0)
        ed = g.mk("remap", [ed], "edges_depth_norm", inputmin=args.edge_lo, inputmax=args.edge_hi,
                  useramp=0)
    else:
        en = g.mk("edgedetect", [lum_for_bands], "edges_luma", method=4, preblur=0.6,
                  highthr=args.luma_edge)
        ed = en
    hl = g.mk("blend", [en, litm], "highlight_mask", mode="multiply")
    hl = g.mk("blend", [hl, skym], "highlight_not_sky", mode="subtract")
    hl = g.mk("clamp", [hl], "highlight_clamp")
    hl = g.mk("function", [hl], "highlight_amt", func="math", func_math="abs", scale=P["line_amt"])
    if args.lines:
        lc_ = g.const(P["line"], rgb, "line_colour")
        painted = g.mk("blend", [painted, lc_, hl], "edge_highlight", mode="screen")
        dk = g.mk("function", [ed], "dark_line_amt", func="math", func_math="abs",
                  scale=P["dark_line_amt"])
        dk = g.mk("blend", [dk, skym], "dark_line_not_sky", mode="subtract")
        dk = g.mk("clamp", [dk], "dark_line_clamp")
        dcol = g.mk("hsv", [painted], "dark_line_colour", valscale=0.55, satscale=1.15)
        painted = g.mk("blend", [painted, dcol, dk], "edge_dark", mode="blend")

    # 8. painted sky: 3-colour gradient from the horizon line, cumulus as hard-edged shapes with
    #    a shaded underside [S Clip Studio 8939 replace sky with gradient + drawn clouds; S 2-3
    #    sky colours]
    if not args.no_sky:
        vr2 = g.mk("ramp", [rgb], "sky_v", rampType="vertical", signature="f1")
        skyg = g.mk("monotorgb", [vr2], "sky_gradient")
        h = max(0.0, min(0.95, args.horizon))
        g.ramp_f3(skyg, (0.0, h, h + (1.0 - h) * 0.45, 1.0),
                  (P["sky_horizon"], P["sky_horizon"], P["sky_mid"], P["sky_zenith"]))
        cn = g.mk("fractalnoise", [rgb], "cloud_noise", elementsize=0.16, elementscale=(2.4, 1.0),
                  amp=0.5, center=0.5, oct=5, rough=0.55, off=(3.7, 1.3))
        cm = g.mk("remap", [cn], "cloud_shape", op="threshold",
                  threshold=0.5 + (0.5 - P["cloud_cover"]) * 0.4, width=0.003)
        band_c = g.mk("remap", [vr2], "cloud_band", useramp=1)
        g.ramp_f1(band_c, (0.0, h, h + 0.08, h + 0.40, 1.0), (0.0, 0.0, 1.0, 0.85, 0.25))
        cm = g.mk("blend", [cm, band_c], "clouds0", mode="multiply")
        # open the mask (erode, then dilate) so noise islands do not read as specks
        cm = g.mk("dilateerode", [cm], "clouds_erode", units="pixels", radius=-4.0)
        cm = g.mk("dilateerode", [cm], "clouds", units="pixels", radius=4.0)
        cup = g.mk("xform2d", [cm], "cloud_up", t=(0.0, 0.022))
        under = g.mk("blend", [cm, cup], "cloud_underside", mode="subtract")
        under = g.mk("clamp", [under], "cloud_under_clamp")
        ccol = g.mk("blend", [g.const(P["cloud_lit"], rgb, "cloud_lit"),
                              g.const(P["cloud_shade"], rgb, "cloud_shade"), under],
                    "cloud_colour", mode="blend")
        sky = g.mk("blend", [skyg, ccol, cm], "sky_painted", mode="blend")
        skt = g.mk("fractalnoise", [rgb], "sky_strokes", elementsize=0.03, elementscale=(6.0, 0.5),
                   amp=0.02, center=1.0, oct=2)
        sky = g.mk("blend", [sky, skt], "sky_tex", mode="multiply")
        skm = g.mk("blur", [skym], "sky_mask_soft", units="pixels", size_pixel=0.8)
        painted = g.mk("blend", [painted, sky, skm], "sky_replace", mode="blend")

    # 9. grade: no pure black (Akira: no black, dark reds and blues) [S manga-passion]; saturation;
    #    a light diffusion (satsuei) [S Clip Studio 8952 Gaussian + Screen]
    gr = g.mk("colorcorrect", [painted], "grade", master_add=P["lift"])
    gr = g.mk("hsv", [gr], "saturation", satscale=P["sat"])
    if P["diffusion"] > 0:
        df = g.mk("blur", [gr], "diffusion_blur", units="image", size=0.02)
        gr = g.mk("blend", [gr, df], "diffusion", mode="screen", mask=P["diffusion"])
    styl = g.mk("null", [gr], "STYLISED")
    out = g.mk("blend", [rgb, styl], "strength_mix", mode="blend", mask=args.strength)
    out = g.mk("null", [out], "OUT")
    return rgb, styl, out


def write(g, node, path, raw=False, q=92):
    r = g.mk("rop_image", [node], None, copoutput=path)
    r.parm("vm_image_jpeg_quality").set(q)
    if raw:
        r.parm("colorconversion").set("raw")
    t = time.time()
    r.parm("execute").pressButton()
    errs = r.errors()
    if errs:
        raise RuntimeError("rop failed: %s" % (errs,))
    return time.time() - t


def auto_key(a):
    """Lit level measured from the input with numpy: the 80th percentile of irradiance
    (C / albedo) on geometry in aov mode, the 90th percentile of linear luminance on non-sky
    pixels in image mode. [I] v3 hero street: aov 1.21, image 0.63."""
    import numpy as np
    W = np.array([0.2126, 0.7152, 0.0722])
    if a.aov_exr:
        import OpenImageIO as oiio
        parts = {}
        for i in range(oiio.ImageBuf(a.aov_exr).nsubimages):
            b = oiio.ImageBuf(a.aov_exr, i, 0)
            sp = b.spec()
            parts[sp.getattribute("name") or str(i)] = b.get_pixels(oiio.FLOAT).reshape(
                sp.height, sp.width, sp.nchannels)
        c = parts["C"][..., :3] @ W
        al = np.maximum(parts["albedo"][..., :3] @ W, 0.03)
        geo = parts["depth"][..., 0] > 1e-3
        return float(np.percentile((c / al)[geo], 80))
    from PIL import Image
    x = np.asarray(Image.open(a.beauty).convert("RGB")).astype(np.float64) / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    notsky = (lin[..., 2] - lin[..., 0]) < a.sky_bmr
    return float(np.percentile((lin @ W)[notsky], 90))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--beauty")
    ap.add_argument("--aov-exr")
    ap.add_argument("--out", required=True)
    ap.add_argument("--before")
    # dusk is the showcase key: the user picked it on both cameras for warm light against cold
    # blue shadows and its sky gradient (review 34); haze_max raised ~25 % in all presets
    ap.add_argument("--preset", default="dusk", choices=sorted(PRESETS))
    # 0.4 is the user's pick (review 34): 1.0 reads as a filter, not a painting
    ap.add_argument("--strength", type=float, default=0.4)
    ap.add_argument("--key", type=float, default=None,
                    help="lit level: irradiance (aov) or linear luminance (image) of a sunlit wall")
    ap.add_argument("--horizon", type=float, default=0.35, help="horizon height, 0 bottom 1 top")
    ap.add_argument("--r-fine", type=float, default=1.5)
    ap.add_argument("--r-base", type=float, default=2.5)
    ap.add_argument("--r-local", type=float, default=8.0)
    ap.add_argument("--r-shade", type=float, default=3.0)
    ap.add_argument("--r-band", type=float, default=6.0)
    ap.add_argument("--lit-lo", type=float, default=0.50)
    ap.add_argument("--lit-hi", type=float, default=0.72)
    ap.add_argument("--edge-lo", type=float, default=0.05)
    ap.add_argument("--edge-hi", type=float, default=0.30)
    ap.add_argument("--wobble", type=float, default=0.0025)
    ap.add_argument("--line-px", type=float, default=1.0)
    ap.add_argument("--norm-tol", type=float, default=0.12)
    ap.add_argument("--depth-tol", type=float, default=0.25)
    ap.add_argument("--luma-edge", type=float, default=0.25)
    ap.add_argument("--sky-bmr", type=float, default=0.015)
    ap.add_argument("--sky-l", type=float, default=0.12)
    ap.add_argument("--no-haze", action="store_true")
    ap.add_argument("--no-sky", action="store_true")
    # off by default: the user read the edge lines as CG outlines, not paint (review 34)
    ap.add_argument("--lines", action="store_true")
    ap.add_argument("--save-hip")
    ap.add_argument("--set", action="append", help="override a preset value, key=v or key=r,g,b")
    a = ap.parse_args(argv)
    if not (a.beauty or a.aov_exr):
        ap.error("--beauty or --aov-exr")
    if a.key is None:
        a.key = auto_key(a)
    print("key", round(a.key, 3))
    P = dict(PRESETS[a.preset])
    for kv in a.set or []:  # e.g. --set sky_zenith=0.2,0.4,0.8 --set haze_max=0.3
        k, v = kv.split("=", 1)
        vals = tuple(float(x) for x in v.split(","))
        P[k] = vals if len(vals) > 1 else vals[0]
    old = hou.node("/img/anime_post")
    if old:
        old.destroy()
    net = hou.node("/img").createNode("copnet", "anime_post")
    g = G(net)
    t0 = time.time()
    rgb, styl, out = build(g, a, P)
    dt = write(g, out, a.out)
    if a.before:
        write(g, rgb, a.before)
    net.layoutChildren()
    if a.save_hip:
        hou.hipFile.save(a.save_hip)
    bad = [(n.path(), n.errors()) for n in net.children() if n.errors()]
    print("built %d nodes, cook+write %.1fs, total %.1fs, errors %s" %
          (len(net.children()), dt, time.time() - t0, bad))


if __name__ == "__main__":
    main()
