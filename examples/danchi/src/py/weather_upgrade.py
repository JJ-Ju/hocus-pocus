# weather_upgrade.py — round 7: turns the round-6 network (1.0) into the parameterised
# weathering of 1.1. Re-runnable; reads every snippet from src/vex. Run on an unlocked
# instance (or on the subnet build.py makes):
#   DANCHI = "<checkout>/examples/danchi"; exec(open(DANCHI + "/src/py/weather_upgrade.py").read())
#   upgrade("/obj/danchi")
# What it changes inside <asset>/build:
#   plan -> weather_params (new, weather.vfl) -> causes; dress reads weather_params
#   decals (decals.vfl) gets input 3 = dress (to find the damaged fronts)
#   grime (round-6 point grime for the shader) is removed; after ytop a bake chain writes the
#   engine-ready vertex colour: bake (bake.vfl) -> del_prim_cd -> vcol_to_cd -> del_vcol
#   decals_lod1 keeps the large decals (dlod), not the strong ones
#   kit_bal_front: hotspot count and break sizes follow the Edge Damage controls; the chips'
#   damage_halo reaches the placed pieces as a mask (the bake does not use it: the worn substrate
#   around a chip is a decal); eg_vN restores the slab-edge grime the boolean interpolates away
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())

WP = "../../weather_params"   # from a node inside kit_bal_front
EG_SNIP = """// edge_grime as on the clean front (input 1) at the nearest point of its surface
int pr; vector uv;
xyzdist(1, @P, pr, uv);
f@edge_grime = primuv(1, "edge_grime", pr, uv);"""


def _snip(n, name, lib=True):
    n.parm("snippet").set(vex(name, lib))


def upgrade(asset="/obj/danchi"):
    b = hou.node(asset + "/build")
    plan, causes, dress = b.node("plan"), b.node("causes"), b.node("dress")
    # ---- weather_params between the plan and its readers
    wp = wrangle(b, "weather_params", vex("weather"), [plan], cls="detail")
    dress.setInput(0, wp)
    causes.setInput(0, wp)
    for nm in ("plan", "dress", "causes", "gen_shell", "decals", "assign"):
        _snip(b.node(nm), nm)
    b.node("assign").setInput(1, causes)
    dec = b.node("decals")
    dec.setInput(3, dress)
    b.node("decals_lod1").parm("snippet").set("// LOD1 keeps the large decals (stain fields, splash, growth, curtains)\nif (!i@dlod) removeprim(0, @primnum, 1);")
    # ---- remove the round-6 point grime; bake the vertex colour at the end
    g = b.node("grime")
    asg = b.node("assign")
    if g is not None:
        asg.setInput(0, g.input(0))
        g.destroy()
    ytop = b.node("ytop")
    uvw = b.node("uv_world")
    bake = wrangle(b, "bake", vex("bake"), [ytop, causes], cls="vertex")
    if bake.parm("lod1_k") is None:
        g_ = bake.parmTemplateGroup()
        g_.append(hou.FloatParmTemplate("lod1_k", "LOD1 Albedo Factor", 1, (1.11,)))
        g_.append(hou.FloatParmTemplate("lod2_k", "LOD2 Albedo Factor", 1, (0.75,)))
        bake.setParmTemplateGroup(g_)
    d1 = node(b, "attribdelete", "del_prim_cd", [bake])
    d1.parm("primdel").set("Cd Alpha")
    vc = wrangle(b, "vcol_to_cd", "v@Cd = v@vcol;\nf@Alpha = f@valpha;", [d1], cls="vertex")
    d2 = node(b, "attribdelete", "del_vcol", [vc])
    d2.parm("vtxdel").set("vcol valpha")
    uvw.setInput(0, d2)
    # ---- damage variants follow the Edge Damage controls
    kb = b.node("kit_bal_front")
    for v, off in ((1, 0), (2, -1), (3, 1), (4, 0)):
        cm = kb.node(f"cluster_v{v}")
        cm.parm("hotspots").setExpression(f'max(1, detail("{WP}", "w_dhot", 0) + ({off}))')
        cm.parm("r_max").setExpression(f'clamp(0.25 + 2.5 * detail("{WP}", "w_dsize", 0), 0.3, 0.9)')
        cp = kb.node(f"chips_v{v}")
        S = f'detail("{WP}", "w_dsize", 0)'
        A = f'detail("{WP}", "w_dmg", 0)'
        cp.parm("anchor_max").setExpression(f"0.6 * {S}")
        cp.parm("anchor_size").setExpression(f"0.36 * {S}")
        cp.parm("size_max").setExpression(f"clamp(0.2 * {S}, 0.01, 0.06)")
        cp.parm("big_size").setExpression(f"clamp(0.2 * {S}, 0.01, 0.05)")
        cp.parm("bite_max").setExpression(f"clamp(0.14 * {S}, 0.008, 0.03)")
        cp.parm("wedge_max").setExpression(f"clamp(0.4 * {S}, 0.03, 0.12)")
        cp.parm("wedge_min").setExpression(f"clamp(0.2 * {S}, 0.02, 0.06)")
        cp.parm("shell_depth_max").setExpression(f"clamp(0.3 * {S}, 0.02, 0.06)")
        cp.parm("spacing").setExpression(f"0.06 / clamp({A} * 1.8, 0.3, 1.6)")
        # the halo of each hotspot onto the damaged piece (point damage_halo)
        nrm, nm = kb.node(f"normal_v{v}"), kb.node(f"name_v{v}")
        at = node(kb, "attribtransfer", f"halo_v{v}", [nrm, cm])
        at.parm("pointattriblist").set("damage_halo")
        at.parm("primitiveattribs").set(0) if at.parm("primitiveattribs") else None
        # edge_grime from the clean front's surface: the boolean and the reduce re-mesh the piece
        # and interpolate it away (a damaged front lost half its slab-edge grime and looked cleaner)
        eg = wrangle(kb, f"eg_v{v}", EG_SNIP, [at, kb.node("name_v0")], cls="point")
        nm.setInput(0, eg)
    kb.layoutChildren()
    b.layoutChildren()
    return [n.name() for n in (wp, bake, d1, vc, d2)]
