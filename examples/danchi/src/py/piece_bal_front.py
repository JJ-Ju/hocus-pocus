# piece_bal_front.py — the golden piece: balcony slab + parapet, clean (v0) and damaged (v1-v4).
exec(open("C:/Users/jujun/AppData/Local/Temp/claude/C--Users-jujun-DEV-hocus-pocus/d956ad22-ff1d-47a8-a6c1-b1930b7bee4a/scratchpad/sk6-out/work/py/hlib.py").read())
import vexpressionmenu

SKILL = "C:/Users/jujun/DEV/hp-r6/.claude/skills/procedural-mesh-damage/scripts"
geo = hou.node("/obj/danchi/build")

TAG = r'''
// tag faces by role: soffit (underside), balcony floor, painted parapet/slab edge
vector n = prim_normal(0, @primnum, {0.5, 0.5, 0});
vector c = {0, 0, 0};
int pp[] = primpoints(0, @primnum);
foreach (int p; pp) { vector q = point(0, "P", p); c += q; }
c /= len(pp);
s@mat = "paint_ext";
if (n.y < -0.7) s@mat = "soffit";
if (n.y > 0.7 && c.y < 0.05 && c.z < 1.17) s@mat = "floor";
if (n.y > 0.5 && c.y > 0.85) s@mat = "coping";
// slab-edge zone of the front face: accent stripes on some blocks; points at the slab bottom
// carry edge_grime (dark line along slab edges and soffits)
if (n.z > 0.7 && c.y < 0.0 && s@mat == "paint_ext") s@cdkey = "slabedge";
foreach (int p; pp) { vector q = point(0, "P", p); if (q.y < -0.14) setpointattrib(0, "edge_grime", p, 1.0); }
'''


def spare_from_ch(n):
    vexpressionmenu.createSpareParmsFromChCalls(n, "snippet")


def build_clean(sn):
    lo = wrangle(sn, "profile_lo", vex("bal_front_profile", lib=False), cls="detail")
    spare_from_ch(lo)
    lo.setParms({"chamfer": 0.0, "joint": 0.01, "solid_part": 1})
    hi = wrangle(sn, "profile", vex("bal_front_profile", lib=False), cls="detail")
    spare_from_ch(hi)
    hi.setParms({"chamfer": 0.012, "joint": 0.01, "solid_part": 1})
    tlo = wrangle(sn, "tag_lo", TAG, [lo], cls="prim")
    thi = wrangle(sn, "tag", TAG, [hi], cls="prim")
    return tlo, thi



def sk(name):
    return open(f"{SKILL}/{name}.vfl", encoding="utf-8").read()


CLUSTER = dict(hotspots_per_m=0.0, r_min=0.15, r_max=0.6, size_bias=1.5, s_min=0.45,
               separation=0.9, core=0.25, warp=0.35, breakup=0.6, breakup_freq=7.0,
               background=0.12, ground_y=-50.0, ground_boost=0.0, contact_lo=-50.0,
               contact_hi=-49.0, contact_boost=0.0, high_fade=1.0, top_boost=0.5,
               corner_boost=3.0, corner_radius=0.25, face_weight=0.1, min_angle=30.0,
               cand_spacing=0.05, seam_margin=0.15, halo=1.5)
CHIPS = dict(spacing=0.06, min_angle=30.0, keep_gamma=2.5, size_min=0.008, size_max=0.03,
             size_bias=2.5, size_bias_hot=1.2, size_floor=0.006, elong=1.5, break_thresh=0.6,
             w_top=1.0, w_wind=0.8, w_vert=0.5, w_bottom=0.6, w_bottom_contact=0.9, w_other=0.5,
             contact_hi=-49.0, ground_y=-50.0, weather=0.05, weather_freq=2.5,
             dl_min=2.2, dl_max=3.5, shell_min=2.0, shell_max=3.0, coff_min=0.2, coff_max=0.5,
             major_p=0.8, corner_size=0.7, corner_keep=1.5, corner_radius=0.25, big_size=0.03,
             run_s_min=0.45, run_min=0.2, run_max=0.5, bite_min=0.008, bite_max=0.022,
             bite_alpha=1.5, run_step=0.8, run_big_p=0.5, runs_per_edge=1, p_shell=0.3,
             p_wedge=0.6, anchor_s_min=0.75, anchor_size=0.07, anchor_max=0.12, anchor_elong=1.5,
             shell_depth_max=0.04, sat_size=0.45, wedge_radius=0.15, wedge_min=0.03,
             wedge_max=0.06, pit_spacing=0.1, pit_keep=0.06, pit_fall=0.08, pit_frac=0.1,
             pit_ref=0.02, pit_min=0.003, pit_flat=0.5, seam_margin=0.15)


def setp(n, d):
    for k, v in d.items():
        pt = n.parmTuple(k)
        if pt is None:
            raise RuntimeError(f"{n.path()} has no parm {k}")
        pt.set(v if isinstance(v, (tuple, list)) else (v,))


def build_cutters(sn):
    """8 unit-radius cutter variants (cutter_shape.vfl): 0-3 breaks, 4-5 nicks, 6-7 pits."""
    outs = []
    for k in range(8):
        npts = 40 if k < 4 else (18 if k < 6 else 14)
        pts = wrangle(sn, f"cut_pts{k}", f"""
for (int i = 0; i < {npts}; i++) {{
    vector2 u = set(rand(i * 1.37 + {k} * 11.1), rand(i * 2.91 + {k} * 5.3));
    vector d = sample_direction_uniform(u);
    float r = 0.82 + 0.18 * rand(i * 7.7 + {k});
    addpoint(0, d * r);
}}""", cls="detail")
        hull = node(sn, "shrinkwrap::2.0", f"cut_hull{k}", [pts])
        src = hull
        if k < 4:
            rm = node(sn, "remesh::2.0", f"cut_remesh{k}", [hull])
            rm.parm("targetsize").set(0.22)
            shp = wrangle(sn, f"cut_shape{k}", sk("cutter_shape"), [rm], cls="point")
            spare_from_ch(shp)
            setp(shp, dict(k=k, lumps=0.08, fine=0.07, hinge=1 if k == 3 else 0))
            src = shp
        var = wrangle(sn, f"cut_var{k}", f"i@variant = {k};", [src], cls="prim")
        outs.append(var)
    mg = node(sn, "merge", "cutters", outs)
    return mg


def build_damage(sn, tlo, thi, dense, cutters, v, nhot):
    cm = wrangle(sn, f"cluster_v{v}", sk("cluster_mask"), [dense, tlo], cls="detail")
    spare_from_ch(cm)
    setp(cm, CLUSTER)
    setp(cm, dict(hotspots=nhot, seed=100 + v, seam_axis=(1, 0, 0)))
    cp = wrangle(sn, f"chips_v{v}", sk("chip_points_edge"), [tlo, cm], cls="detail")
    spare_from_ch(cp)
    setp(cp, CHIPS)
    setp(cp, dict(seed=200 + v, seam_axis=(1, 0, 0), impact_dir=(1, 0, 0.4)))
    cc = node(sn, "copytopoints::2.0", f"place_cutters_v{v}", [cutters, cp])
    cc.setParms({"useidattrib": 1, "idattrib": "variant", "pack": 0})
    bo = node(sn, "boolean::2.0", f"bool_v{v}", [thi, cc])
    bo.parm("booleanop").set("subtract")
    bo.parm("subtractchoices").set("aminusb")
    bo.parm("usebinsidea").set(1)
    bo.parm("binsidea").set("cut")
    # cut faces show exposed concrete; damaged pieces keep their own normals (cusp 25)
    cut = wrangle(sn, f"cutmat_v{v}", 'if (inprimgroup(0, "cut", @primnum)) { s@mat = "concrete"; s@cdkey = "concrete"; }', [bo], cls="prim")
    dv0 = node(sn, "divide", f"tri0_v{v}", [cut])
    seam = wrangle(sn, f"seam_v{v}", 'float W = ch("../../../bay_w"); float xa = -W * 0.5 + rint(W * 0.4 * 10) / 10.0; if (abs(@P.x - W * 0.5) < 1e-3 || abs(@P.x - xa) < 1e-3) setpointgroup(0, "seam", @ptnum, 1);', [dv0], cls="point")
    red = node(sn, "polyreduce::2.0", f"reduce_v{v}", [seam])
    red.parm("target").set("poly_percent")
    red.parm("percentage").set(55)
    red.parm("hardfeaturepoints").set("seam")
    red.parm("silhouetteweight").set(1.5)
    red.parm("boundaryweight").set(3.0)
    nrm = node(sn, "normal", f"normal_v{v}", [red])
    nrm.parm("cuspangle").set(25)
    nm = node(sn, "name", f"name_v{v}", [nrm])
    nm.parm("name1").set(f"bal_front_v{v}")
    # validation and measurement (not in the output chain)
    val = wrangle(sn, f"validate_v{v}", sk("damage_validate"), [nm, thi], cls="detail")
    spare_from_ch(val)
    setp(val, dict(seam_axis=(1, 0, 0), seam_tol=1e-4))
    con = node(sn, "connectivity", f"islands_v{v}", [nm])
    con.parm("connecttype").set("prim")
    con.parm("primincgroup").set("cut")
    con.parm("attribname").set("island")
    isl = wrangle(sn, f"island_fix_v{v}", 'if (!inprimgroup(0, "cut", @primnum)) i@island = -1;', [con], cls="prim")
    me = wrangle(sn, f"measure_v{v}", sk("damage_measure"), [isl, thi, tlo], cls="detail")
    spare_from_ch(me)
    setp(me, dict(probe_u=0.05, probe_d=0.008, flank_min_run=2, corner_skip=0.04, edge_tol=0.012))
    return nm


def main():
    sn = geo.node("kit_bal_front")
    if sn:
        sn.destroy()
    sn = geo.createNode("subnet", "kit_bal_front")
    tlo, thi = build_clean(sn)
    n0 = node(sn, "normal", "normal_v0", [thi])
    n0.parm("cuspangle").set(25)
    nm0 = node(sn, "name", "name_v0", [n0])
    nm0.parm("name1").set("bal_front_v0")
    dense = node(sn, "remesh::2.0", "dense", [tlo])
    dense.parm("targetsize").set(0.03)
    cutters = build_cutters(sn)
    outs = [nm0]
    for v, nhot in ((1, 1), (2, 2), (3, 3), (4, 2)):
        outs.append(build_damage(sn, tlo, thi, dense, cutters, v, nhot))
    mg = node(sn, "merge", "variants", outs)
    o = node(sn, "output", "output0", [mg])
    sn.layoutChildren()
    sn.setUserData("covers", " ".join(f"bal_front_v{v}" for v in range(5)))
    return sn


main()
