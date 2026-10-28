# showcase.py — the round-7 weathering showcase: one building (/obj/danchi), plain ground, the
# evidence lighting (sun 28° up on the camera side of the south facade, sky dome), fixed cameras,
# and a shot list rendered by one Karma ROP job (one frame per shot, parms keyed per frame).
#   DANCHI = "<checkout>/examples/danchi"; exec(open(DANCHI + "/src/py/showcase.py").read())
#   setup(); key_shots(SHOTS); dump_shots(SHOTS)   then render /out/karma_show frames 1..len(SHOTS)
# The manifest and contact sheets are written outside Houdini by showcase_sheets.py.
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())
import json

ASSET = "/obj/danchi"

GROUND = r'''
// plain ground for the showcase: asphalt, a lawn strip along the block, footpath and kerb
function void gbox(vector mn; vector mx; string mat; vector cd; float rough) {
    int p = addbox(0, mn, mx, "ground");
    for (int f = 0; f < 6; f++) {
        setprimattrib(0, "shop_materialpath", p + f, chs("mats") + "/" + mat);
        setprimattrib(0, "Cd", p + f, cd);
        setprimattrib(0, "rough", p + f, rough);
    }
}
gbox({-200, -0.3, -120}, {200, -0.02, 160}, "floor", {0.115, 0.115, 0.11}, 0.9);
gbox({-60, -0.3, 5.55}, {60, 0.03, 12.0}, "fabric", {0.085, 0.11, 0.05}, 0.95);
gbox({-200, -0.3, 12.0}, {200, 0.12, 14.0}, "concrete", {0.62, 0.61, 0.58}, 0.85);
gbox({-200, -0.3, 13.9}, {200, 0.15, 14.1}, "concrete", {0.55, 0.55, 0.53}, 0.85);
gbox({-60, -0.3, -12.0}, {60, 0.03, -8.3}, "fabric", {0.085, 0.11, 0.05}, 0.95);
gbox({-48, -0.3, -8.3}, {-41.0, 0.03, 12.0}, "fabric", {0.085, 0.11, 0.05}, 0.95);
gbox({41.0, -0.3, -8.3}, {48, 0.03, 12.0}, "fabric", {0.085, 0.11, 0.05}, 0.95);
'''

# cameras: name -> (position, aim, focal mm, vertical shift). Eye height 1.6 m; the camera is
# level (aim at eye height) and the frame is shifted up (winy), so verticals stay straight.
CAMS = {
    "bay": ((6.5, 1.6, 15.5), (-1.0, 1.6, 5.0), 28.0, 0.32),       # golden bay, ~10 m
    "facade": ((-58.0, 1.6, 36.0), (-22.0, 1.6, 0.0), 24.0, 0.36),  # facade + west gable, 37-60 m
    "sweep": ((-58.0, 1.6, 22.0), (-36.0, 1.6, 2.0), 24.0, 0.38),   # west end, ~24 m to the gable
}


def setup():
    obj = hou.node("/obj")
    # the evidence light rig: sun 28 deg high from the south-west, on the camera side of the south
    # facade and of the west end wall the facade and sweep cameras see; pale sky dome
    sun = obj.node("sun") or obj.createNode("hlight::2.0", "sun")
    sun.parm("light_type").set(7)                 # distant
    sun.parmTuple("r").set((-28.0, -40.0, 0.0))
    sun.parm("light_intensity").set(0.72)
    sky = obj.node("sky") or obj.createNode("envlight", "sky")
    sky.parm("env_map").set(TEXDIR + "/sky.png")
    sky.parm("light_intensity").set(0.6)
    sky.parm("light_contribprimary").set(1)       # the sky is visible to the camera
    g = obj.node("ground_show") or obj.createNode("geo", "ground_show")
    w = g.node("ground") or g.createNode("attribwrangle", "ground")
    w.parm("class").set(0)
    if w.parm("mats") is None:
        pg = w.parmTemplateGroup()
        pg.append(hou.StringParmTemplate("mats", "Materials", 1, (ASSET + "/mats",)))
        w.setParmTemplateGroup(pg)
    w.parm("snippet").set(open(VEX + "/lib.vfl", encoding="utf-8").read() + "\n" + GROUND)
    w.setDisplayFlag(True); w.setRenderFlag(True)
    cam = obj.node("cam_show") or obj.createNode("cam", "cam_show")
    aim = obj.node("cam_show_aim") or obj.createNode("null", "cam_show_aim")
    cam.parm("lookatpath").set(aim.path())
    cam.parm("resx").set(1600); cam.parm("resy").set(900)
    cam.parm("near").set(0.1) if cam.parm("near") else None
    out = hou.node("/out")
    rop = out.node("karma_show") or out.createNode("karma", "karma_show")
    rop.setParms({"camera": cam.path(), "override_camerares": 1, "res_fraction": "specific",
                  "resolutionx": 1600, "resolutiony": 900, "samplesperpixel": 32,
                  "candobjects": "", "objects": f"{ASSET}/build /obj/ground_show"})
    rop.parm("trange").set(1)
    rop.parm("enablemblur").set(0)      # shots jump the camera between frames: no motion blur
    rop.parm("engine").set("xpu")       # Karma XPU (GPU): ~20 s a frame instead of 1-4 min on CPU
    rop.parm("picture").set("$HIP/../showcase/raw/shot_$F3.png")
    return [g.path(), cam.path(), aim.path(), rop.path()]


def set_cam(name):
    pos, tgt, focal, winy = CAMS[name]
    cam, aim = hou.node("/obj/cam_show"), hou.node("/obj/cam_show_aim")
    cam.parmTuple("t").set(pos)
    aim.parmTuple("t").set(tgt)
    cam.parm("focal").set(focal)
    cam.parm("winy").set(winy)


# shot list: (file stem, camera, parm values). Every shot starts from the same base
# (preset Typical, no overrides, site defaults); "parms" lists what the shot changes.
BASE = {"w_preset": "typical", "w_age": 35.0, "w_upkeep": 0.5, "repaint_auto": 1, "w_grime": 0.5,
        "w_exposure": 0.6, "w_wind": 200.0, "w_seed": 1, "weather": 1.0, "decals": 1, "damage": 1,
        "ov_streak": 0, "ov_dmg": 0, "ov_grime": 0, "ov_stain": 0}
PRESETS = [("new", "New"), ("well_kept", "Well kept"), ("typical", "Typical"), ("neglected", "Neglected")]
SWEEP = {
    # the main detail controls, swept with every other layer on its Typical auto value
    "streaks": {"ov_streak": 1, "_amt": "streak_amt", "_keep": {"streak_density": 1.0, "streak_len": 1.3, "streak_tail": 0.11,
                "streak_width": 1.0, "streak_int": 1.0, "streak_colvar": 0.7, "streak_top": 0.88}},
    "edge_damage": {"ov_dmg": 1, "_amt": "dmg_amt", "_keep": {"dmg_size": 0.16, "dmg_hot": 2}},
    "grime": {"ov_grime": 1, "_amt": "grime_amt", "_keep": {"grime_corner": 0.87}},
    "stain_fields": {"ov_stain": 1, "_amt": "stain_amt", "_keep": {"stain_scale": 1.0}},
}
AGES = [10.0, 35.0, 60.0]
UPKEEPS = [0.9, 0.5, 0.1]


def shot_list():
    shots = []
    for cam in ("bay", "facade"):
        for tok, label in PRESETS:
            shots.append({"file": f"preset_{cam}_{tok}", "group": "preset_strip", "camera": cam, "label": f"{label} ({cam})",
                          "parms": {"w_preset": tok}})
    for ctl, d in SWEEP.items():
        for v in (0.0, 0.25, 0.5, 0.75, 1.0):
            p = {k: v_ for k, v_ in d.items() if not k.startswith("_")}
            p.update(d["_keep"])
            p[d["_amt"]] = v
            shots.append({"file": f"sweep_{ctl}_{int(v * 100):03d}", "group": f"sweep_{ctl}", "camera": "sweep",
                          "label": f"{ctl.replace('_', ' ')} {v:.2f}", "parms": p})
    for a in AGES:
        for u in UPKEEPS:
            shots.append({"file": f"grid_age{int(a):02d}_upkeep{int(u * 100):03d}", "group": "age_upkeep_grid", "camera": "facade",
                          "label": f"age {int(a)}, upkeep {u:.1f}", "parms": {"w_preset": "custom", "w_age": a, "w_upkeep": u, "repaint_auto": 1}})
    # chips are 3-30 cm: a few pixels at the sweep camera's 24 m, so the edge-damage sweep is
    # also shot at the bay camera (appended, so frames 1-37 keep their numbers)
    d = SWEEP["edge_damage"]
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        p = {k: v_ for k, v_ in d.items() if not k.startswith("_")}
        p.update(d["_keep"])
        p[d["_amt"]] = v
        shots.append({"file": f"sweep_edge_damage_bay_{int(v * 100):03d}", "group": "sweep_edge_damage_bay", "camera": "bay",
                      "label": f"edge damage {v:.2f} (bay)", "parms": p})
    return shots


def _menu_index(parm, token):
    return list(parm.menuItems()).index(token)


def key_shots(shots):
    """One frame per shot: constant keys on the asset parms and the camera."""
    n = hou.node(ASSET)
    cam, aim = hou.node("/obj/cam_show"), hou.node("/obj/cam_show_aim")
    names = set(BASE)
    for s in shots:
        names.update(s["parms"])
    targets = [n.parm(k) for k in names] + list(cam.parmTuple("t")) + list(aim.parmTuple("t")) + [cam.parm("focal"), cam.parm("winy")]
    for p in targets:
        p.deleteAllKeyframes()
    for i, s in enumerate(shots):
        fr = i + 1
        vals = dict(BASE)
        vals.update(s["parms"])
        for k, v in vals.items():
            p = n.parm(k)
            if isinstance(v, str):
                v = _menu_index(p, v)
            kf = hou.Keyframe(float(v))
            kf.setFrame(fr)
            kf.setExpression("constant()")
            p.setKeyframe(kf)
        pos, tgt, focal, winy = CAMS[s["camera"]]
        for p, v in list(zip(cam.parmTuple("t"), pos)) + list(zip(aim.parmTuple("t"), tgt)) + [(cam.parm("focal"), focal), (cam.parm("winy"), winy)]:
            kf = hou.Keyframe(float(v))
            kf.setFrame(fr)
            kf.setExpression("constant()")
            p.setKeyframe(kf)
        s["frame"] = fr
        s["values"] = {k: vals[k] for k in sorted(vals)}
    # after the last shot every keyed parm returns to BASE (frames 101-103 are the LOD check)
    for k in names:
        p = n.parm(k)
        if k in BASE:
            v = BASE[k]
        else:
            dv = p.parmTemplate().defaultValue()
            v = dv[p.componentIndex()] if isinstance(dv, tuple) else dv
        if isinstance(v, str):
            v = _menu_index(p, v)
        kf = hou.Keyframe(float(v))
        kf.setFrame(len(shots) + 1)
        kf.setExpression("constant()")
        p.setKeyframe(kf)
    hou.playbar.setFrameRange(1, len(shots))
    return len(shots)


def clear_keys():
    n = hou.node(ASSET)
    for p in n.parms():
        if p.keyframes():
            p.deleteAllKeyframes()
    for nm in ("/obj/cam_show", "/obj/cam_show_aim"):
        for p in hou.node(nm).parms():
            if p.keyframes():
                p.deleteAllKeyframes()


EFFECTIVE = ["w_age", "w_upkeep", "w_repaint", "w_soil", "w_damage", "w_grime", "w_exposure", "w_streak", "w_stain", "w_soot",
             "w_corner", "w_dmg", "w_dsize", "w_dhot", "w_wear", "w_rust", "w_patches", "w_efflo", "w_bio", "w_splash"]


def dump_shots(shots, path="$HIP/../showcase/raw/shots.json"):
    """After key_shots: add the values weather_params resolved on each frame and the cameras, write
    the JSON that showcase_sheets.py turns into the manifest."""
    wp = hou.node(ASSET + "/build/weather_params")
    for s in shots:
        hou.setFrame(s["frame"])
        g = wp.geometry()
        s["effective"] = {k[2:]: (round(g.attribValue(k), 3) if isinstance(g.attribValue(k), float) else g.attribValue(k))
                          for k in EFFECTIVE}
    hou.setFrame(1)
    shots[0]["cameras"] = {k: {"position": v[0], "aim": v[1], "focal_mm": v[2], "window_shift_y": v[3]} for k, v in CAMS.items()}
    path = hou.text.expandString(path)
    json.dump(shots, open(path, "w"), indent=1)
    return path


SHOTS = shot_list()
