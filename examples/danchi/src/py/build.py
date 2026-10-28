# build.py — creates /obj/danchi (the asset subnet): interface, plan, dress, kit, placement,
# generated shell. Re-runnable: rebuilds the network from the .vfl files.
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())

TOP = "/obj/danchi"


def interface(sub):
    g = sub.parmTemplateGroup()
    for f in list(g.entries()):
        g.remove(f)

    def F(name, label, items):
        fo = hou.FolderParmTemplate(name, label, folder_type=hou.folderType.Tabs)
        for it in items:
            fo.addParmTemplate(it)
        g.append(fo)

    I = hou.IntParmTemplate
    R = hou.FloatParmTemplate
    T = hou.ToggleParmTemplate
    M = hou.MenuParmTemplate
    S = hou.StringParmTemplate
    F("f_mass", "Massing", [
        I("floors", "Floors", 1, (10,), min=4, max=14, min_is_strict=True, max_is_strict=True,
          help="Number of residential floors (4-14)."),
        I("units", "Units per Floor", 1, (12,), min=4, max=24, min_is_strict=True, max_is_strict=True,
          help="Flats per floor along the slab."),
        R("bay_w", "Unit Bay Width", 1, (6.0,), min=5.5, max=7.0, min_is_strict=True, max_is_strict=True,
          help="Frontage of one flat in metres (contract: 5.5-7.0, 0.5 steps)."),
        R("floor_h", "Floor Height", 1, (2.8,), min=2.7, max=3.0, min_is_strict=True, max_is_strict=True),
        M("roof_type", "Roof Edge", ("auto", "eave", "parapet"), ("Auto (eave below 8 floors)", "Projecting Eave", "Parapet"), default_value=0),
        T("mass_from_seed", "Massing from Seed", default_value=False,
          help="Pick floors and units from the ranges below using the seed (for estates and seed sheets)."),
        I("floors_min", "Floors Min", 1, (5,), min=4, max=14, disable_when="{ mass_from_seed == 0 }"),
        I("floors_max", "Floors Max", 1, (12,), min=4, max=14, disable_when="{ mass_from_seed == 0 }"),
        I("units_min", "Units Min", 1, (8,), min=4, max=24, disable_when="{ mass_from_seed == 0 }"),
        I("units_max", "Units Max", 1, (16,), min=4, max=24, disable_when="{ mass_from_seed == 0 }"),
    ])
    F("f_cores", "Cores", [
        I("n_cores", "Cores (0 = auto)", 1, (0,), min=0, max=3, min_is_strict=True, max_is_strict=True,
          help="Stair cores along the corridor side. Auto: 1, 2 from 10 units, 3 from 18."),
        M("lift_mode", "Lift", ("auto", "never", "always"), ("Auto (6+ floors)", "Never", "Always"), default_value=0),
    ])
    F("f_style", "Style", [
        I("seed", "Seed", 1, (1,), min=0, max=999,
          help="Drives every random choice: cores jitter, personas, props, damage, streaks, patches."),
        M("style", "Paint Scheme", ("seed", "white", "light_grey", "cream", "beige_brown", "pink"),
          ("From Seed", "White", "Light Grey", "Cream", "Beige", "Pale Pink"), default_value=0),
        I("bldg_no", "Building Number", 1, (0,), min=0, max=99,
          help="Number painted on the end walls. 0 picks one from the seed."),
        T("bldg_suffix", "Add 号棟", default_value=False),
    ])
    F("f_dress", "Dressing", [
        T("props", "Balcony Props", default_value=True, help="Laundry, futons, plants, AC units, by flat persona."),
        T("interiors", "Interior Cards", default_value=True, help="Curtains and a room behind the balcony glass."),
        T("damage", "Edge Damage Geometry", default_value=True, help="Balcony fronts use the damaged variants (Weathering > Edge Damage). Off: all fronts clean."),
        R("ac_share", "AC Unit Share", 1, (0.7,), min=0, max=1),
        T("retrofit_lift", "Retrofit Lift Tower", default_value=False,
          help="An added steel-and-glass lift tower (UR retrofit) at the west end of the corridor side."),
    ])
    # round 7: the Weathering tab (preset, history, site, detail overrides) lives in interface.py
    exec(open(PY + "/interface.py", encoding="utf-8").read(), globals())
    g.append(weather_folder())
    F("f_out", "Output", [
        M("lod", "LOD", ("0", "1", "2", "all"), ("LOD0 (full)", "LOD1 (no props, simplified)", "LOD2 (shell)", "All (groups lod0/lod1/lod2)"), default_value=0),
        T("collision", "Collision Hulls (UCX_)", default_value=True),
    ])
    sub.setParmTemplateGroup(g)


PROXY = {
    # name: (size x, size y, size z, centre x, centre y, centre z) as hscript expressions
    "bal_wall": ("W", "H", "0.18", "0", "H/2", "-0.09"),
    "sash_door": ("min(3.4, W-2.6)", "2.0", "0.08", "0", "1.0", "-0.08"),
    "bal_window": ("min(1.6, W-min(3.4,W-2.6)-1.25)", "1.1", "0.08", "0", "0.55", "-0.08"),
    "partition": ("0.04", "2.2", "1.1", "0", "1.1", "0.55"),
    "bal_fin": ("0.15", "H", "1.2", "0", "H/2-0.15", "0.6"),
    "room": ("W-0.4", "2.4", "3.4", "0", "1.2", "-1.9"),
    "cor_wall": ("W", "H", "0.18", "0", "H/2", "-0.09"),
    "steel_door": ("0.85", "2.0", "0.1", "0", "1.0", "-0.05"),
    "meter_door": ("0.8", "1.8", "0.05", "0", "0.9", "-0.025"),
    "kitchen_win": ("1.2", "0.9", "0.18", "0", "0.45", "-0.01"),
    "core_wall_3": ("3.0", "H", "0.18", "0", "H/2", "-0.09"),
    "core_wall_55": ("5.5", "H", "0.18", "0", "H/2", "-0.09"),
    "cor_landing_3": ("3.0", "0.18", "1.4", "0", "-0.09", "0.7"),
    "cor_landing_55": ("5.5", "0.18", "1.4", "0", "-0.09", "0.7"),
}
for v in range(5):
    PROXY[f"bal_front_v{v}"] = ("W", "1.25", "1.2", "0", "0.475", "0.6")
PROXY["cor_front"] = ("W", "1.28", "1.4", "0", "0.46", "0.7")


def proxy_piece(geo, name, spec, rel):
    """A kit piece as its own SOP subnet (proxy box until the real piece replaces it)."""
    old = geo.node("kit_" + name)
    if old:
        old.destroy()
    sn = geo.createNode("subnet", "kit_" + name)
    box = sn.createNode("box", "proxy")
    rr = "../" + rel
    def ex(e):
        return e.replace("W", f'ch("{rr}/bay_w")').replace("H", f'ch("{rr}/floor_h")')
    for i, a in enumerate("xyz"):
        box.parm("size" + a).setExpression(ex(spec[i]))
        box.parm("t" + a).setExpression(ex(spec[3 + i]))
    nm = sn.createNode("name", "name")
    nm.parm("name1").set(name)
    nm.setInput(0, box)
    o = sn.createNode("output", "output0")
    o.setInput(0, nm)
    sn.layoutChildren()
    return sn


def build():
    obj = hou.node("/obj")
    sub = obj.node("danchi")
    if sub is None:
        sub = obj.createNode("subnet", "danchi")
        interface(sub)
    geo = sub.node("build") or sub.createNode("geo", "build")
    sub.node("mats") or sub.createNode("matnet", "mats")

    plan = wrangle(geo, "plan", vex("plan"), cls="detail")
    dress = wrangle(geo, "dress", vex("dress"), [plan], cls="point")

    # real pieces declare the names they cover (user data "covers"); proxies fill the rest
    covered = set()
    for ch_ in geo.children():
        if ch_.name().startswith("kit_") and ch_.userData("covers"):
            covered.update(ch_.userData("covers").split())
    for ch_ in list(geo.children()):
        if ch_.name().startswith("kit_") and ch_.node("proxy") is not None and len(covered) > 20:
            ch_.destroy()
    for name, spec in (PROXY.items() if len(covered) <= 20 else []):
        px = geo.node("kit_" + name)
        if name in covered:
            if px is not None and not px.userData("covers"):
                px.destroy()
            continue
        if px is None or px.node("proxy") is not None:
            proxy_piece(geo, name, spec, "../..")
    kit = node(geo, "merge", "KIT")
    for i in range(len(kit.inputs())):
        kit.setInput(i, None)
    kits = sorted([c for c in geo.children() if c.name().startswith("kit_")], key=lambda n: n.name())
    for i, k in enumerate(kits):
        kit.setInput(i, k)

    cp = node(geo, "copytopoints::2.0", "place_kit", [kit, dress])
    cp.setParms({"useidattrib": 1, "idattrib": "name", "pack": 0})
    cp.parm("targetattribs").set(1)
    cp.parm("applyattribs1").set("floor bay side unit persona colneglect variant role")
    cp.parm("applyto1").set("prims")

    causes = wrangle(geo, "causes", vex("causes"), [plan], cls="detail")
    shell = wrangle(geo, "gen_shell", vex("gen_shell"), [None, causes], cls="detail")
    # building number on both gables (font → placed by two points)
    font = node(geo, "font", "number_font")
    font.parm("text").set('`details("../plan", "numtext")`')
    font.parm("file").set("DejaVu Sans Bold")
    font.parm("fontsize").setExpression('0.4 * ch("../../floor_h") / 0.72')
    font.parm("lod").set(0.35)
    ftag = wrangle(geo, "number_tag", 's@mat = "sign"; s@cdkey = "number";', [font], cls="prim")
    npts = wrangle(geo, "number_points", vex("number_points"), [None, causes, shell], cls="detail")
    ncp = node(geo, "copytopoints::2.0", "place_number", [ftag, npts])
    ncp.parm("pack").set(0)
    dec = wrangle(geo, "decals", vex("decals"), [None, causes, shell], cls="detail")
    mg = node(geo, "merge", "merge_all", [cp, shell, ncp, dec])
    # ---- LOD1: from undamaged sources, no props, interior card, strong decals only
    d1 = wrangle(geo, "lod1_filter", vex("lod1_filter", lib=False), [dress], cls="point")
    cp1 = node(geo, "copytopoints::2.0", "place_kit_lod1", [kit, d1])
    cp1.setParms({"useidattrib": 1, "idattrib": "name", "pack": 0})
    cp1.parm("targetattribs").set(1)
    cp1.parm("applyattribs1").set(cp.parm("applyattribs1").eval())
    cp1.parm("applyto1").set("prims")
    dec1 = wrangle(geo, "decals_lod1", 'if (f@dstr < 0.45) removeprim(0, @primnum, 1);', [dec], cls="prim")
    m1 = node(geo, "merge", "merge_lod1", [cp1, shell, ncp, dec1])
    # ---- LOD2: banded shell
    l2 = wrangle(geo, "lod2_shell", vex("lod2_shell"), [None, causes, shell], cls="detail")
    m2 = node(geo, "merge", "merge_lod2", [l2, ncp])
    tagged = []
    for i, m in enumerate((mg, m1, m2)):
        tagged.append(wrangle(geo, f"group_lod{i}", f'setprimgroup(0, "lod{i}", @primnum, 1); i@lod = {i};', [m], cls="prim"))
    allm = node(geo, "merge", "merge_lods", tagged)
    sw = node(geo, "switch", "lod_select", tagged + [allm])
    sw.parm("input").setExpression('ch("../../lod")')
    grime = wrangle(geo, "grime", vex("grime"), [sw, causes], cls="point")
    asg = wrangle(geo, "assign", vex("assign"), [grime, plan], cls="prim")
    if asg.parm("matroot") is None:
        g_ = asg.parmTemplateGroup()
        g_.append(hou.StringParmTemplate("matroot", "Material Root", 1, ('`opfullpath("../../mats")`',)))
        asg.setParmTemplateGroup(g_)
    ytop = wrangle(geo, "ytop", 'f@ytop = detail(1, "ytop");', [asg, plan], cls="detail")
    uvw = wrangle(geo, "uv_world", vex("uv_world", lib=False), [ytop], cls="vertex")
    out = node(geo, "null", "OUT", [uvw])
    # ---- collision hulls (own object, never rendered)
    col = wrangle(geo, "collision", vex("collision"), [None, causes, shell], cls="detail")
    cnull = node(geo, "null", "COLLISION", [col])
    sub = geo.parent()
    cg = sub.node("collision") or sub.createNode("geo", "collision")
    om = cg.node("in") or cg.createNode("object_merge", "in")
    om.parm("objpath1").set("../../build/COLLISION")
    emp = cg.node("empty") or cg.createNode("null", "empty")
    csw = cg.node("on") or cg.createNode("switch", "on")
    csw.setInput(0, emp); csw.setInput(1, om)
    csw.parm("input").setExpression('ch("../../collision")')
    csw.setDisplayFlag(True); csw.setRenderFlag(True)
    cg.parm("vm_rendervisibility").set("") if cg.parm("vm_rendervisibility") else None
    cg.setRenderFlag(False) if hasattr(cg, "setRenderFlag") else None
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    geo.layoutChildren()
    return sub


build()
# round 7: weather_params, the new decals, the vertex-colour bake and the damage expressions
# (needs the real kit pieces: run pieces.py, pieces_l1.py and piece_bal_front.py first, then
# materials.py, then this script again)
if hou.node(TOP + "/build/kit_bal_front/cluster_v1") is not None:
    exec(open(PY + "/weather_upgrade.py", encoding="utf-8").read(), globals())
    upgrade(TOP)
