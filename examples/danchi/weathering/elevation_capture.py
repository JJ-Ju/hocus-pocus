#!/usr/bin/env hython
"""elevation_capture.py - orthographic elevation captures of the danchi asset for a numpy checker.

For one or more weathering configs of `hocuspocus::danchi::1.1` (the round-7 showcase instance),
renders Karma XPU orthographic elevations at exactly 50 px/m and writes <out_dir>/<config>/<V>_*,
V in S (south, camera on +Z), W (west gable, camera on -X), N (north, camera on -Z):
  V_albedo.exr (half RGBA) / V_albedo.png (16-bit linear RGB)
                            albedo AOV of the visible surface INCLUDING the decals; A = coverage
  V_albedo_vcol.exr         the same AOV with the decal meshes hidden (vertex colour only)
  V_P.exr                   world position of the first hit (float32), decals hidden, NaN = no hit
  V_N.exr                   world shading normal of the first hit (half), decals hidden
  V_depth.exr               distance from the camera plane along the view axis (float32), NaN = no hit
  V_class.png               8-bit surface class of the first hit, decals hidden (legend in elevations.json)
and per config `config.json` (parms set, resolved weathering values, bbox, decal count, and per view
the exact pixel <-> world mapping, render times, class pixel counts). <out_dir>/frames.json holds the
fixed frames, <out_dir>/elevations.json the conventions and legend.

Two Karma passes per view: "look" (geometry with decals: albedo, coverage) and "surf" (decals
removed: P, N, depth, primvar `hpclass`, all with closest-sample blending, plus albedo_vcol).

  hython elevation_capture.py <out_dir> <config,config,...|all> [--views S,W,N] [--engine xpu|cpu] [--force]

Configs come from examples/danchi/showcase/manifest.json ("values" of each shot) plus `clean`
(preset New, decal meshes off) and `clean_dressed` (the same with balcony props and interior
cards on). Weathering configs are captured with props and interior cards off.

Loads the round-7 hip read-only (never saves it), swaps the asset definition to the
hocus-pocus library, and points the asset's Texture Folder at a scratch copy of tex/ so the
.rat files Karma XPU writes next to its textures do not land in a checkout.
"""
import json
import math
import os
import shutil
import sys
import time

import hou
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = os.environ.get("WX_SCRATCH", os.path.join(os.environ.get("TEMP", "/tmp"), "danchi_weathering")).replace("\\", "/")
HIP = os.environ.get("WX_HIP", os.path.join(os.path.dirname(HERE), "work", "danchi_v007.hiplc")).replace("\\", "/")
LIB = os.path.join(os.path.dirname(HERE), "danchi.hdalc").replace("\\", "/")
REPO_DANCHI = os.path.dirname(HERE)
MANIFEST = REPO_DANCHI + "/showcase/manifest.json"
TEXCOPY = ROOT + "/tex_copy"
USDTMP = ROOT + "/usdtmp"
ASSET = "/obj/danchi"
TYPE = "hocuspocus::danchi::1.1"

PPM = 50                       # pixels per metre (2 cm / px)
MPP = 1.0 / PPM
MARGIN = 0.5                   # metres around the bounding box
CAM_DIST = 30.0                # camera plane distance outside the frame box (ortho: only clipping)

# surface classes (class.png value -> material); 0 = nothing hit (no ground or sky in the scene)
CLASSES = ["none", "paint_ext", "coping", "soffit", "concrete", "glass", "decal", "steel", "alu",
           "board", "frp", "room", "fabric", "plastic", "sign", "floor", "metal"]
UNKNOWN_CLASS = 255

BASE = {"w_preset": "typical", "w_age": 35.0, "w_upkeep": 0.5, "repaint_auto": 1, "w_grime": 0.5,
        "w_exposure": 0.6, "w_wind": 200.0, "w_seed": 1, "weather": 1.0, "decals": 1, "damage": 1,
        "ov_streak": 0, "ov_dmg": 0, "ov_grime": 0, "ov_stain": 0}
EFFECTIVE = ["w_age", "w_upkeep", "w_repaint", "w_soil", "w_damage", "w_grime", "w_exposure", "w_streak",
             "w_stain", "w_soot", "w_corner", "w_dmg", "w_dsize", "w_dhot", "w_wear", "w_rust", "w_patches",
             "w_efflo", "w_bio", "w_splash"]

# render settings shared by every config (same seed and samples everywhere)
SPP_LOOK = 16
SPP_SURF = 4
ENGINE = "xpu"


def log(*a):
    print("[elev %s]" % time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------------------------
# configs
# ----------------------------------------------------------------------------------------------
def config_table():
    """name -> {"values": parm dict, "views": [...], "dressing": bool, "source": manifest file}"""
    m = json.load(open(MANIFEST, encoding="utf-8"))
    by_file = {im["file"]: im for im in m["images"]}
    cfg = {}
    new_vals = dict(by_file["preset_facade_new.jpg"]["values"])
    cfg["clean"] = {"values": dict(new_vals, decals=0), "views": ["S", "W", "N"], "dressing": False,
                    "source": "preset_facade_new.jpg values + decals=0 (New leaves 2 soot-cloud decals)"}
    cfg["clean_dressed"] = {"values": dict(new_vals, decals=0), "views": ["S", "W", "N"], "dressing": True,
                            "source": "as clean, balcony props and interior cards on"}
    for tok in ("new", "well_kept", "typical", "neglected"):
        f = "preset_facade_%s.jpg" % tok
        cfg["preset_" + tok] = {"values": dict(by_file[f]["values"]), "views": ["S", "W", "N"], "dressing": False,
                                "source": f}
    for ctl in ("streaks", "edge_damage", "grime", "stain_fields"):
        for v in ("000", "025", "050", "075", "100"):
            f = "sweep_%s_%s.jpg" % (ctl, v)
            cfg["sweep_%s_%s" % (ctl, v)] = {"values": dict(by_file[f]["values"]), "views": ["S", "W"],
                                             "dressing": False, "source": f}
    for a in ("10", "35", "60"):
        for u in ("090", "050", "010"):
            f = "grid_age%s_upkeep%s.jpg" % (a, u)
            cfg["grid_age%s_upkeep%s" % (a, u)] = {"values": dict(by_file[f]["values"]), "views": ["S", "W"],
                                                   "dressing": False, "source": f}
    return cfg


# ----------------------------------------------------------------------------------------------
# scene
# ----------------------------------------------------------------------------------------------
def load_scene():
    t0 = time.time()
    try:
        hou.hipFile.load(HIP, suppress_save_prompt=True, ignore_load_warnings=True)
    except hou.LoadWarning:
        pass
    # use the hocus-pocus copy of the library (byte-identical to the hp-r7 one the hip names)
    old = [f for f in hou.hda.loadedFiles() if f.replace("\\", "/").lower().endswith("danchi.hdalc")
           and os.path.normcase(os.path.abspath(f)) != os.path.normcase(os.path.abspath(LIB))]
    hou.hda.installFile(LIB)
    for f in old:
        hou.hda.uninstallFile(f)
    n = hou.node(ASSET)
    lib = n.type().definition().libraryFilePath()
    for p in n.parms():
        if p.keyframes():
            p.deleteAllKeyframes()
    # textures: a scratch copy (Karma XPU writes .rat mip maps next to the textures it reads)
    if not os.path.isdir(TEXCOPY):
        os.makedirs(TEXCOPY)
        for f in os.listdir(REPO_DANCHI + "/tex"):
            if f.lower().endswith((".png", ".json")):
                shutil.copy2(REPO_DANCHI + "/tex/" + f, TEXCOPY + "/" + f)
    n.parm("tex_dir").deleteAllKeyframes()
    n.parm("tex_dir").set(TEXCOPY)
    n.parm("lod").set(list(n.parm("lod").menuItems()).index("0"))
    hou.setFrame(1)
    log("scene loaded %.1fs, library %s, tex %s" % (time.time() - t0, lib, n.parm("tex_dir").eval()))
    return n


def set_parms(values, dressing):
    n = hou.node(ASSET)
    vals = dict(BASE)
    vals.update(values)
    for k, v in vals.items():
        p = n.parm(k)
        if p is None:
            raise RuntimeError("no parm " + k)
        if isinstance(v, str):
            v = list(p.menuItems()).index(v)
        p.set(v)
    n.parm("props").set(1 if dressing else 0)
    n.parm("interiors").set(1 if dressing else 0)
    return vals


CLASS_VEX = "string m = s@mat;\nint c = %d;\n" % UNKNOWN_CLASS + "".join(
    'if (m == "%s") c = %d;\n' % (c, i) for i, c in enumerate(CLASSES) if i > 0) + "f@hpclass = c;\n"


def build_obj_nodes():
    obj = hou.node("/obj")
    made = {}
    for nm, keep_decals in (("elev_look", True), ("elev_surf", False)):
        g = obj.node(nm) or obj.createNode("geo", nm)
        for c in g.children():
            c.destroy()
        om = g.createNode("object_merge", "in")
        om.parm("objpath1").set(ASSET + "/build/OUT")
        om.parm("xformtype").set(1)                     # into this object (danchi is at identity)
        w = g.createNode("attribwrangle", "hpclass")
        w.parm("class").set(1)                          # primitives
        w.parm("snippet").set(CLASS_VEX)
        w.setInput(0, om)
        last = w
        if not keep_decals:
            b = g.createNode("blast", "no_decals")
            b.parm("group").set('@mat="decal"')
            b.parm("grouptype").set(4) if b.parm("grouptype") else None
            b.setInput(0, w)
            last = b
        o = g.createNode("null", "OUT")
        o.setInput(0, last)
        o.setDisplayFlag(True)
        o.setRenderFlag(True)
        made[nm] = g
    dome = obj.node("elev_dome") or obj.createNode("envlight", "elev_dome")
    dome.parm("env_map").set("")
    dome.parmTuple("light_color").set((1, 1, 1))
    dome.parm("light_intensity").set(1.0)
    dome.parm("light_contribprimary").set(0)           # not visible to camera
    made["elev_dome"] = dome
    for v in ("S", "W", "N"):
        c = obj.node("elev_cam_" + v) or obj.createNode("cam", "elev_cam_" + v)
        c.parm("projection").set(1)                    # ortho
        made["elev_cam_" + v] = c
    return made


# the white dome casts no shadows: a decal quad 4-10 mm off its wall would otherwise shadow the
# wall behind it by its own opacity (a lit render then darkens decals twice), and every surface
# gets the full unoccluded dome, so diffuse = albedo x 1 with no occlusion to cancel
DOME_SHADOWS = False
FIX_LOP = """
from pxr import Sdf
stage = hou.pwd().editableStage()
p = stage.GetPrimAtPath('/elev_dome')
if p and p.IsValid():
    p.CreateAttribute('inputs:shadow:enable', Sdf.ValueTypeNames.Bool).Set(%s)
""" % DOME_SHADOWS


def build_lops():
    st = hou.node("/stage")
    for c in st.children():
        if c.name().startswith("elev_"):
            c.destroy()
    chains = {}
    for ps, geo in (("look", "/obj/elev_look"), ("surf", "/obj/elev_surf")):
        si = st.createNode("sceneimport::2.0", "elev_imp_" + ps)
        si.parm("objects").set(geo + " /obj/elev_dome /obj/elev_cam_S /obj/elev_cam_W /obj/elev_cam_N")
        fix = st.createNode("pythonscript", "elev_fix_" + ps)
        fix.parm("python").set(FIX_LOP)
        fix.setInput(0, si)
        krs = st.createNode("karmarendersettings", "elev_krs_" + ps)
        krs.setInput(0, fix)
        rop = st.createNode("usdrender_rop", "elev_rop_" + ps)
        rop.setInput(0, krs)
        chains[ps] = (si, krs, rop)
    return chains


def find_cam_paths(si):
    stage = si.stage()
    out = {}
    for p in stage.Traverse():
        if p.GetTypeName() == "Camera":
            nm = p.GetName()
            for v in ("S", "W", "N"):
                if nm == "elev_cam_" + v:
                    out[v] = str(p.GetPath())
    return out


def setup_krs(krs, ps, engine, spp, aovs, screendoor=8):
    """aovs: list of (name, sourceName, sourceType, format, filter)"""
    P = krs.parm
    P("engine").set(engine)
    P("samplesperpixel").set(spp)
    P("pathtracedsamples").set(spp)
    P("convergence_mode").set("Path Traced")
    P("pixelfilter").set("box")
    P("pixelfiltersize").set(1.0)
    P("pixelfilterscale").set(1.0)
    P("enablemblur").set(0)
    P("enabledof").set(0)
    P("screendoorlimit").set(screendoor)
    P("diffuselimit").set(0)
    P("reflectionlimit").set(0)
    P("refractionlimit").set(1)
    P("res_mode").set("manual")
    for r in ("resolutionx", "resolutiony"):      # locked while res_mode was autoheight; callbacks do not
        P(r).lock(False)                          # run on set() from Python, so unlock by hand
    P("denoiser").set("off")
    P("tonemap").set("off")
    P("image_exr_compression").set("zips")
    P("beauty").set(1)
    P("albedo").set(1)
    for t in ("hitP", "hitN", "hitPz"):
        P(t).set(1 if ps == "surf" else 0)
    if ps == "surf":
        P("hitPfilter").set('["minmax",{"mode":"zmin"}]')
        P("hitPprecision").set("float3")
        P("hitNfilter").set('["minmax",{"mode":"zmin"}]')
        P("hitNprecision").set("float3")
        P("hitPzfilter").set('["minmax",{"mode":"zmin"}]')
        P("hitPzprecision").set("float")
    P("extrarendervars").set(len(aovs))
    for i, (nm, src, styp, fmt, flt) in enumerate(aovs, 1):
        P("enable%d" % i).set(1)
        P("name%d" % i).set(nm)
        P("format%d" % i).set(fmt)
        P("dataType%d" % i).set(fmt)
        P("sourceName%d" % i).set(src)
        P("sourceType%d" % i).set(styp)
        P("filter%d" % i).set(flt)


# ----------------------------------------------------------------------------------------------
# framing
# ----------------------------------------------------------------------------------------------
def geo_bbox(objpath):
    g = hou.node(objpath).displayNode().geometry()
    bb = g.boundingBox()
    return [list(bb.minvec()), list(bb.maxvec())]


def union(a, b):
    return [[min(a[0][i], b[0][i]) for i in range(3)], [max(a[1][i], b[1][i]) for i in range(3)]]


def snap_lo(v):
    return math.floor((v - MARGIN) * PPM + 1e-6) / PPM


def snap_hi(v):
    return math.ceil((v + MARGIN) * PPM - 1e-6) / PPM


def make_frames(bbox):
    """Fixed frames (same pixel grid for every config). bbox = [[xmin,ymin,zmin],[xmax,ymax,zmax]]"""
    (x0, y0, z0), (x1, y1, z1) = bbox
    X0, X1, Y0, Y1, Z0, Z1 = snap_lo(x0), snap_hi(x1), snap_lo(y0), snap_hi(y1), snap_lo(z0), snap_hi(z1)
    H = int(round((Y1 - Y0) * PPM))
    fr = {}
    # S: camera on +Z looking -Z; image right = +X
    W_ = int(round((X1 - X0) * PPM))
    fr["S"] = dict(view="S", view_dir=[0, 0, -1], u_axis=[1, 0, 0], v_axis=[0, -1, 0], width_px=W_, height_px=H,
                   origin=[X0, Y1, Z1 + CAM_DIST], cam_t=[(X0 + X1) / 2, (Y0 + Y1) / 2, Z1 + CAM_DIST], cam_r=[0, 0, 0],
                   left_edge={"axis": "x", "value": X0}, right_edge={"axis": "x", "value": X1})
    # N: camera on -Z looking +Z; image right = -X
    fr["N"] = dict(view="N", view_dir=[0, 0, 1], u_axis=[-1, 0, 0], v_axis=[0, -1, 0], width_px=W_, height_px=H,
                   origin=[X1, Y1, Z0 - CAM_DIST], cam_t=[(X0 + X1) / 2, (Y0 + Y1) / 2, Z0 - CAM_DIST], cam_r=[0, 180, 0],
                   left_edge={"axis": "x", "value": X1}, right_edge={"axis": "x", "value": X0})
    # W: camera on -X looking +X; image right = +Z
    Wz = int(round((Z1 - Z0) * PPM))
    fr["W"] = dict(view="W", view_dir=[1, 0, 0], u_axis=[0, 0, 1], v_axis=[0, -1, 0], width_px=Wz, height_px=H,
                   origin=[X0 - CAM_DIST, Y1, Z0], cam_t=[X0 - CAM_DIST, (Y0 + Y1) / 2, (Z0 + Z1) / 2], cam_r=[0, -90, 0],
                   left_edge={"axis": "z", "value": Z0}, right_edge={"axis": "z", "value": Z1})
    for v, f in fr.items():
        f.update(px_per_m=PPM, m_per_px=MPP, top_y=Y1, bottom_y=Y0, frame_box=[[X0, Y0, Z0], [X1, Y1, Z1]],
                 width_m=f["width_px"] * MPP, height_m=H * MPP, camera="orthographic",
                 depth_plane_world=(f["cam_t"][2] if v in "SN" else f["cam_t"][0]),
                 mapping=("world(col,row,depth) = origin + (col+0.5)*m_per_px*u_axis + (row+0.5)*m_per_px*v_axis"
                          " + depth*view_dir; row 0 = top; origin = top-left image corner on the camera plane"))
    return fr


def set_cams(frames):
    for v, f in frames.items():
        c = hou.node("/obj/elev_cam_" + v)
        c.parmTuple("t").set(f["cam_t"])
        c.parmTuple("r").set(f["cam_r"])
        c.parm("orthowidth").set(f["width_m"])
        c.parm("resx").set(f["width_px"])
        c.parm("resy").set(f["height_px"])
        c.parm("aspect").set(1.0)
        c.parm("near").set(1.0)
        c.parm("far").set(CAM_DIST * 2 + 200.0)
        c.parm("winx").set(0)
        c.parm("winy").set(0)


# ----------------------------------------------------------------------------------------------
# render + read
# ----------------------------------------------------------------------------------------------
def render(chain, view, frame, picture, campath):
    si, krs, rop = chain
    krs.parm("camera").set(campath)
    krs.parm("resolutionx").set(frame["width_px"])
    krs.parm("resolutiony").set(frame["height_px"])
    krs.parm("picture").set(picture)
    rop.parm("loppath").set(krs.path())
    rop.parm("renderer").set("BRAY_HdKarmaXPU" if krs.parm("engine").eval() == "xpu" else "BRAY_HdKarma")
    if rop.parm("savetodirectory_directory"):
        rop.parm("savetodirectory_directory").set(USDTMP)
    if os.path.exists(picture):
        os.remove(picture)
    t0 = time.time()
    rop.parm("execute").pressButton()
    dt = time.time() - t0
    ok = os.path.exists(picture)
    errs = rop.errors()
    if not ok or errs:
        log("RENDER PROBLEM", view, picture, ok, errs, rop.warnings())
    return dt, ok


def read_exr(path):
    """{aov_name: float32 array HxWxC} from a (multi-part) EXR, via OpenImageIO."""
    import OpenImageIO as oiio
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError("cannot open " + path + " " + oiio.geterror())
    out = {}
    si = 0
    while True:
        if not inp.seek_subimage(si, 0):
            break
        spec = inp.spec()
        pix = inp.read_image(si, 0, 0, spec.nchannels, oiio.FLOAT)
        pix = np.asarray(pix, dtype=np.float32).reshape(spec.height, spec.width, spec.nchannels)
        part = spec.getattribute("name") or ("part%d" % si)
        chans = list(spec.channelnames)
        # group channels by prefix (multi-part: one AOV per part; single part: "aov.R" names)
        groups = {}
        for ci, cn in enumerate(chans):
            if "." in cn:
                g, c = cn.rsplit(".", 1)
            else:
                g, c = part, cn
            groups.setdefault(g, []).append((c, ci))
        for g, lst in groups.items():
            out[g] = (pix[:, :, [ci for _, ci in lst]], [c for c, _ in lst])
        si += 1
    inp.close()
    return out


def write_exr(path, arr, chans, half=False):
    import OpenImageIO as oiio
    h, w = arr.shape[:2]
    nc = 1 if arr.ndim == 2 else arr.shape[2]
    spec = oiio.ImageSpec(w, h, nc, oiio.HALF if half else oiio.FLOAT)
    spec.channelnames = tuple(chans)
    spec.attribute("compression", "zip")
    o = oiio.ImageOutput.create(path)
    o.open(path, spec)
    o.write_image(np.ascontiguousarray(arr.reshape(h, w, nc).astype(np.float32)))
    o.close()


def write_png(path, arr, bits):
    import OpenImageIO as oiio
    h, w = arr.shape[:2]
    nc = 1 if arr.ndim == 2 else arr.shape[2]
    if bits == 16:
        data = np.clip(np.round(arr * 65535.0), 0, 65535).astype(np.uint16)
        td = oiio.UINT16
    else:
        data = np.clip(arr, 0, 255).astype(np.uint8)
        td = oiio.UINT8
    spec = oiio.ImageSpec(w, h, nc, td)
    spec.attribute("oiio:ColorSpace", "linear" if bits == 16 else "data")
    spec.attribute("png:compressionLevel", 6)
    o = oiio.ImageOutput.create(path)
    o.open(path, spec)
    o.write_image(np.ascontiguousarray(data.reshape(h, w, nc)))
    o.close()


# ----------------------------------------------------------------------------------------------
# production
# ----------------------------------------------------------------------------------------------
LOOK_AOVS = []                                                   # C (+alpha) and albedo are toggles
SURF_AOVS = [("hpclass", "hpclass", "primvar", "float", '["minmax",{"mode":"zmin"}]')]
ALBEDO_NOTE = ("Karma XPU 'albedo' AOV (export_basecolor = MaterialX base colour of the shaded hit), box pixel "
               "filter 1 px, %d spp, screendoor limit 8: the translucent decal quads are composited by Karma's "
               "screendoor transparency, i.e. albedo = decal Cd x opacity over the wall's base colour, layer by "
               "layer. Verified on the Neglected west gable: an unshadowed white dome render's diffuse (LPE C<RD>L) "
               "divided by this AOV is 1.004 on decal-covered wall pixels and 1.001 on clean ones (median); "
               "the LPE albedo C<RD>A is identical to it (max diff 2e-4).")


def frames_for(outdir):
    path = outdir + "/frames.json"
    if os.path.exists(path):
        return json.load(open(path))["frames"]
    cfg = config_table()
    bb = None
    for nm in ("clean_dressed", "preset_neglected", "preset_typical"):
        set_parms(cfg[nm]["values"], cfg[nm]["dressing"])
        b = geo_bbox("/obj/elev_look")
        bb = b if bb is None else union(bb, b)
    fr = make_frames(bb)
    json.dump({"bbox_union": bb, "from": ["clean_dressed", "preset_neglected", "preset_typical"],
               "frames": fr}, open(path, "w"), indent=1)
    return fr


def effective_values():
    g = hou.node(ASSET + "/build/weather_params").geometry()
    out = {}
    for k in EFFECTIVE:
        v = g.attribValue(k)
        out[k[2:]] = round(v, 4) if isinstance(v, float) else v
    return out


def inside(bb, box):
    return all(box[0][i] <= bb[0][i] and bb[1][i] <= box[1][i] for i in range(3))


def capture_config(name, cfg, frames, chains, cams, outdir, views=None):
    t0 = time.time()
    d = outdir + "/" + name
    os.makedirs(d, exist_ok=True)
    vals = set_parms(cfg["values"], cfg["dressing"])
    tc = time.time()
    glook = hou.node("/obj/elev_look").displayNode().geometry()
    hou.node("/obj/elev_surf").displayNode().geometry()
    cook_s = time.time() - tc
    bb = geo_bbox("/obj/elev_look")
    mats = glook.primStringAttribValues("mat")
    n_decal = sum(1 for m in mats if m == "decal")
    unknown = sorted(set(m for m in mats if m not in CLASSES))
    info = {"config": name, "source": cfg["source"], "dressing": cfg["dressing"],
            "parms_set": {k: vals[k] for k in sorted(vals)},
            "props": int(cfg["dressing"]), "interiors": int(cfg["dressing"]), "lod": "0",
            "effective": effective_values(), "bbox": bb, "decal_prims": n_decal,
            "prims": len(glook.prims()), "unknown_materials": unknown,
            "views": {}, "cook_s": round(cook_s, 2)}
    for v in (views or cfg["views"]):
        fr = frames[v]
        if not inside(bb, fr["frame_box"]):
            log("WARNING bbox outside frame", name, v, bb, fr["frame_box"])
        times = {}
        pics = {}
        for ps in ("look", "surf"):
            pic = "%s/_raw_%s_%s.exr" % (d, v, ps)
            dt, ok = render(chains[ps], v, fr, pic, cams[v])
            times[ps] = round(dt, 1)
            if not ok:
                raise RuntimeError("render failed %s %s %s" % (name, v, ps))
            pics[ps] = pic
        tw = time.time()
        L = read_exr(pics["look"])
        S = read_exr(pics["surf"])
        alb = L["albedo"][0]
        cov = L["C"][0][..., 3]
        cls = np.round(S["hpclass"][0][..., 0]).astype(np.int32)
        hit = cls > 0
        Pw = S["P"][0].copy()
        Nw = S["N"][0].copy()
        dep = S["depth"][0][..., 0].copy()
        Pw[~hit] = np.nan
        dep[~hit] = np.nan
        Nw[~hit] = 0.0
        write_exr("%s/%s_albedo.exr" % (d, v), np.dstack([alb, cov]), ("R", "G", "B", "A"), half=True)
        write_png("%s/%s_albedo.png" % (d, v), alb, 16)
        write_exr("%s/%s_albedo_vcol.exr" % (d, v), S["albedo"][0], ("R", "G", "B"), half=True)
        write_exr("%s/%s_P.exr" % (d, v), Pw, ("x", "y", "z"))
        write_exr("%s/%s_N.exr" % (d, v), Nw, ("x", "y", "z"), half=True)
        write_exr("%s/%s_depth.exr" % (d, v), dep, ("Z",))
        write_png("%s/%s_class.png" % (d, v), np.clip(cls, 0, 255).astype(np.uint8), 8)
        counts = np.bincount(np.clip(cls, 0, 255).ravel(), minlength=256)
        for ps in ("look", "surf"):
            os.remove(pics[ps])
        times["write"] = round(time.time() - tw, 1)
        wallm = np.isin(cls, [1, 2, 3])
        info["views"][v] = {"files": {k: "%s_%s" % (v, k) for k in ("albedo.exr", "albedo.png", "albedo_vcol.exr",
                                                                         "P.exr", "N.exr", "depth.exr", "class.png")},
                            "mapping": fr, "render_s": times,
                            "class_pixels": {(CLASSES[i] if i < len(CLASSES) else str(i)): int(c)
                                             for i, c in enumerate(counts) if c},
                            "albedo_wall_mean": ([round(float(x), 5) for x in alb[wallm].mean(axis=0)]
                                                 if wallm.any() else None)}
        log("%s %s look %.1fs surf %.1fs write %.1fs" % (name, v, times["look"], times["surf"], times["write"]))
    info["total_s"] = round(time.time() - t0, 1)
    json.dump(info, open(d + "/config.json", "w"), indent=1)
    return info


def write_index(outdir, frames):
    idx = {"asset": TYPE, "library": LIB, "scene": HIP + " (loaded read-only, never saved)",
           "building": "default instance /obj/danchi of the round-7 showcase hip: 10 floors x 12 units, seed 1, "
                       "paint scheme 'white' (style=1 in that hip), LOD0",
           "px_per_m": PPM, "m_per_px": MPP, "margin_m": MARGIN,
           "frames": frames,
           "frame_note": "one fixed frame per view for every config (union bbox of clean_dressed, preset_neglected, "
                         "preset_typical + 0.5 m, snapped outward to the 2 cm pixel grid), so images of different "
                         "configs are pixel-aligned for ratios",
           "image_convention": "row 0 = top; pixel (col,row) centre at origin + (col+0.5)*m_per_px*u_axis + "
                               "(row+0.5)*m_per_px*v_axis on the camera plane; the ray goes along view_dir",
           "files": {
               "V_albedo.exr": "half RGBA. RGB = linear albedo (base colour) of the visible surface INCLUDING the "
                               "decals; A = pixel coverage (0 where nothing is hit). " + ALBEDO_NOTE % SPP_LOOK,
               "V_albedo.png": "16-bit RGB PNG of the same albedo, LINEAR values (no sRGB transfer): "
                               "value = round(albedo * 65535)",
               "V_albedo_vcol.exr": "half RGB, the same AOV with the decal meshes hidden (vertex colour x wall "
                                    "textures only), from the surf pass (%d spp)" % SPP_SURF,
               "V_P.exr": "float32 xyz world position of the first hit, decals hidden; NaN where nothing is hit",
               "V_N.exr": "half xyz world-space shading normal of the first hit, decals hidden; 0 where nothing is hit",
               "V_depth.exr": "float32 Z = distance from the camera plane along view_dir; world coordinate along the "
                              "view axis = depth_plane_world + depth * (view_dir component); NaN where nothing is hit",
               "V_class.png": "8-bit surface class of the first hit with the decals hidden (the wall behind a decal); "
                              "legend below",
           },
           "aov_sampling": "P, N, depth, class use 'closest sample' blending (minmax zmin) at %d spp, so every pixel "
                           "holds one real sample (no blended normals or class ids at edges); the sample lies within "
                           "+-0.25 px of the pixel centre. Albedo is a 1-px box average of %d samples." % (SPP_SURF, SPP_LOOK),
           "class_legend": {str(i): c for i, c in enumerate(CLASSES)},
           "class_note": "0 = nothing hit (the scene has no ground, sky or other objects); 255 = unknown material",
           "lighting": "white dome, intensity 1, invisible to camera, shadows off (only the beauty C, unused; the "
                       "albedo AOV does not depend on lights). No sun, sky texture or ground.",
           "render": {"engine": ENGINE, "look_spp": SPP_LOOK, "surf_spp": SPP_SURF, "pixel_filter": "box 1px",
                      "seed": "Karma default (fixed)", "screendoor_limit": 8, "diffuse_limit": 0},
           "textures": TEXCOPY + " (scratch copy of examples/danchi/tex; Karma XPU writes .rat mip maps beside it)"}
    json.dump(idx, open(outdir + "/elevations.json", "w"), indent=1)


def main():
    global ENGINE
    args = sys.argv[1:]
    outdir = args[0].replace("\\", "/")
    which = args[1] if len(args) > 1 else "all"
    views = None
    if "--views" in args:
        views = args[args.index("--views") + 1].split(",")
    if "--engine" in args:
        ENGINE = args[args.index("--engine") + 1]
    os.makedirs(outdir, exist_ok=True)
    load_scene()
    build_obj_nodes()
    chains = build_lops()
    cfg = config_table()
    names = list(cfg) if which == "all" else which.split(",")
    frames = frames_for(outdir)
    set_cams(frames)
    chains["look"][0].cook(force=True)
    cams = find_cam_paths(chains["look"][0])
    setup_krs(chains["look"][1], "look", ENGINE, SPP_LOOK, LOOK_AOVS)
    setup_krs(chains["surf"][1], "surf", ENGINE, SPP_SURF, SURF_AOVS)
    write_index(outdir, frames)
    t0 = time.time()
    done = []
    for nm in names:
        if os.path.exists(outdir + "/" + nm + "/config.json") and "--force" not in args:
            log("skip (exists)", nm)
            continue
        info = capture_config(nm, cfg[nm], frames, chains, cams, outdir, views)
        done.append((nm, info["total_s"]))
        log("DONE %s %.1fs (total %.1f min)" % (nm, info["total_s"], (time.time() - t0) / 60))
    log("all done", len(done), "configs in %.1f min" % ((time.time() - t0) / 60))


if __name__ == "__main__":
    main()
