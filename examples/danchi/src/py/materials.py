# materials.py — MaterialX materials in /obj/danchi/mats. Per-prim colour (Cd → displayColor),
# roughness (`rough`) and metalness (`metal`) come from the generator, so variation, repaint
# patches and personas live in the geometry; the shaders add what belongs to the world
# (macro value noise, damp base band, top-floor wash) and the tiling micro maps.
# Round 7: shaders reduced to what an engine rebuilds (vertex colour x textures on one UV set);
# all weathering lives in the vertex colour and the decal meshes.
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())

MATS = hou.node("/obj/danchi/mats")
TEX = '`chs("../../../tex_dir")`'


def P(n, inp, value, sig=None):
    """Set an input's parm whatever its signature suffix."""
    cands = ([f"{inp}_{sig}"] if sig else []) + [inp] + [f"{inp}_{s}" for s in ("color3", "color3FA", "float", "vector2", "vector3", "vector2FA", "vector3FA")]
    want = len(value) if isinstance(value, (list, tuple)) else 1
    for c in cands:
        pt = n.parmTuple(c)
        if pt is not None and (len(pt) == want or want == 1):
            if isinstance(value, (list, tuple)):
                pt.set(value)
            else:
                pt.set((value,) * len(pt))
            return
    raise RuntimeError(f"{n.path()}: no parm for {inp} ({sig}); has " + ",".join(p.name() for p in n.parms() if p.name().startswith(inp))[:300])


def M(mat, typ, sig=None, **ins):
    """Create a node; kwargs are inputs: a node/tuple wires, a value sets the parm."""
    n = mat.createNode(typ)
    if sig:
        n.parm("signature").set(sig)
    for k, v in ins.items():
        if isinstance(v, hou.VopNode):
            n.setInput(n.inputIndex(k), v)
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], hou.VopNode):
            n.setInput(n.inputIndex(k), v[0], v[1])
        else:
            if k in ("geomprop", "file", "space", "filecolorspace"):
                n.parm(k).set(v)
            else:
                P(n, k, v, sig)
    return n


def prim_f(mat, name, default):
    g = M(mat, "mtlxgeompropvalue", "float", geomprop=name)
    P(g, "default", default, "float")
    return g


def prim_c(mat, name="displayColor"):
    return M(mat, "mtlxgeompropvalue", "color3", geomprop=name)


def uv_scaled(mat, s):
    tc = M(mat, "mtlxtexcoord", "vector2")
    return M(mat, "mtlxmultiply", "vector2FA", in1=tc, in2=s)


def tex(mat, file, uv, sig="float", raw=True):
    im = M(mat, "mtlximage", sig, texcoord=uv)
    im.parm("file").set(f"{TEX}/{file}")
    if raw and im.parm("filecolorspace"):
        im.parm("filecolorspace").set("raw")
    return im


def generic(name, rough=0.6, metal=0.0, spec=0.5, coat=0.0):
    m, s = mtlx_material(MATS, name)
    link(s, "base_color", prim_c(m))
    link(s, "specular_roughness", prim_f(m, "rough", rough))
    link(s, "metalness", prim_f(m, "metal", metal))
    s.parm("specular").set(spec)
    if coat:
        s.parm("coat").set(coat)
    return m


def painted_wall(name, tile=2.0, normal_scale=0.6, rough=0.86):
    """Exterior paint on spray tile, engine-portable (round 7). Everything the weathering does
    is already in the vertex colour (displayColor: paint x tint x patch x baked soot) and in the
    decal meshes; the shader adds only what an engine material can rebuild with two texture
    samples on the one UV set (world metres):
      base_color = vertex colour x cavity(spray_ao, 0.95-1) x macro(macro_var at uv / 40, 0.94-1.06)
      normal     = spray_normal at uv / 2;  roughness = constant.
    The round-6 procedural MaterialX noise, damp band and top-floor wash are gone (Karma-only);
    the splash band, soot and wash are now decals and vertex colour."""
    m, s = mtlx_material(MATS, name)
    cd = prim_c(m)
    uv = uv_scaled(m, 1.0 / tile)
    ao = tex(m, "spray_ao.png", uv)
    cav = M(m, "mtlxremap", "float", **{"in": ao}, inlow=0.0, inhigh=1.0, outlow=0.95, outhigh=1.0)
    uvm = uv_scaled(m, 1.0 / 40.0)
    mv = tex(m, "macro_var.png", uvm)
    mac = M(m, "mtlxremap", "float", **{"in": mv}, inlow=0.25, inhigh=0.75, outlow=0.94, outhigh=1.06)
    k = M(m, "mtlxmultiply", "float", in1=mac, in2=cav)
    col = M(m, "mtlxmultiply", "color3FA", in1=cd, in2=k)
    link(s, "base_color", col)
    s.parm("specular_roughness").set(rough)
    s.parm("specular").set(0.4)
    nimg = tex(m, "spray_normal.png", uv, sig="vector3")
    nm = M(m, "mtlxnormalmap", **{"in": nimg})
    nm.parm("scale").set(normal_scale)
    link(s, "normal", nm)
    return m


def concrete(name):
    m, s = mtlx_material(MATS, name)
    uv = uv_scaled(m, 1.0 / 2.4)
    bc = tex(m, "concrete_basecolor.png", uv, sig="color3", raw=False)
    cd = prim_c(m)
    col = M(m, "mtlxmultiply", "color3", in1=bc, in2=cd)
    link(s, "base_color", M(m, "mtlxmultiply", "color3FA", in1=col, in2=1.6))
    link(s, "specular_roughness", tex(m, "concrete_roughness.png", uv))
    nimg = tex(m, "concrete_normal.png", uv, sig="vector3")
    link(s, "normal", M(m, "mtlxnormalmap", **{"in": nimg}))
    s.parm("specular").set(0.35)
    return m


def glass(name):
    m, s = mtlx_material(MATS, name)
    s.parmTuple("base_color").set((1, 1, 1))
    s.parm("specular").set(1.0)
    s.parm("specular_roughness").set(0.03)
    s.parm("specular_IOR").set(1.52)
    s.parm("transmission").set(1.0)
    s.parmTuple("transmission_color").set((0.86, 0.9, 0.88))
    s.parm("thin_walled").set(1)
    return m


def decal(name):
    """Mesh decal (round 7): albedo = vertex colour, opacity = weather_atlas (alpha) x vertex alpha
    (displayOpacity). One material for every decal layer; the engine version is the same two
    multiplies (README)."""
    m, s = mtlx_material(MATS, name)
    link(s, "base_color", prim_c(m))
    uv = M(m, "mtlxtexcoord", "vector2")
    a = tex(m, "weather_atlas.png", uv)
    st = prim_f(m, "displayOpacity", 1.0)
    op = M(m, "mtlxmultiply", "float", in1=a, in2=st)
    cv = m.createNode("mtlxconvert")
    cv.parm("signature").set("floatcolor3")
    cv.setInput(0, op)
    link(s, "opacity", cv)
    s.parm("specular_roughness").set(0.9)
    s.parm("specular").set(0.3)
    return m


def main():
    for c in MATS.children():
        c.destroy()
    painted_wall("paint_ext")
    painted_wall("coping")
    painted_wall("soffit", normal_scale=0.4)
    concrete("concrete")
    glass("glass")
    decal("decal")
    for nm, r, mt, sp in (("steel", 0.45, 0.0, 0.5), ("alu", 0.35, 1.0, 0.5), ("board", 0.55, 0.0, 0.4),
                          ("frp", 0.5, 0.0, 0.45), ("room", 0.85, 0.0, 0.3), ("fabric", 0.9, 0.0, 0.25),
                          ("plastic", 0.5, 0.0, 0.45), ("sign", 0.6, 0.0, 0.4), ("floor", 0.6, 0.0, 0.4),
                          ("metal", 0.4, 1.0, 0.5)):
        generic(nm, r, mt, sp)
    MATS.layoutChildren()
    return [c.name() for c in MATS.children()]


print(main())
