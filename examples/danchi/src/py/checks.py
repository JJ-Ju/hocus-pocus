# checks.py — the danchi gate checks (round 7), run inside Houdini:
#   DANCHI = "<checkout>/examples/danchi"; exec(open(DANCHI + "/src/py/checks.py").read())
#   skeleton(); damage(); budgets(); export_fbx(); reimport(); fresh_instance()
# Each returns a dict that goes into the README results table and the log.
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())
exec(open(PY + "/check_skeleton.py", encoding="utf-8").read())
import time
import os

ASSET = "/obj/danchi"


def _tris(geo):
    return sum(len(p.vertices()) - 2 for p in geo.prims())


def _set(n, d):
    old = {}
    for k, v in d.items():
        p = n.parm(k)
        old[k] = p.evalAsString() if p.parmTemplate().type() == hou.parmTemplateType.Menu else p.eval()
        p.set(v)
    return old


def skeleton(asset=ASSET):
    """Contract check of round 6 on the five configurations (gaps/overlaps per floor)."""
    n = hou.node(asset)
    configs = [dict(floors=10, units=12, bay_w=6.0, n_cores=0, lift_mode="auto"),
               dict(floors=4, units=4, bay_w=5.5, n_cores=0, lift_mode="auto"),
               dict(floors=14, units=24, bay_w=7.0, n_cores=3, lift_mode="auto"),
               dict(floors=7, units=9, bay_w=6.5, n_cores=1, lift_mode="always"),
               dict(floors=5, units=13, bay_w=6.0, n_cores=3, lift_mode="never")]
    out = []
    for c in configs:
        old = _set(n, c)
        r = check(asset)
        out.append({k: r[k] for k in ("floors", "units", "ncores", "n_problems")})
        _set(n, old)
    return out


def damage(asset=ASSET, settings=None):
    """Validation and measurement of the four damage variants (skill scripts) at the current
    settings, or at `settings` (parm values on the asset) and back."""
    n = hou.node(asset)
    old = _set(n, settings) if settings else None
    kb = hou.node(asset + "/build/kit_bal_front")
    res = {}
    for v in range(1, 5):
        val = kb.node(f"validate_v{v}"); me = kb.node(f"measure_v{v}")
        val.cook(force=True); me.cook(force=True)
        g, m = val.geometry(), me.geometry()
        res[f"v{v}"] = {"open": g.attribValue("open_edges"), "nonmanifold": g.attribValue("nonmanifold_edges"),
                        "seam_changed": g.attribValue("seam_changed"), "tris": g.attribValue("triangles"),
                        "flank_runs": m.attribValue("flank_runs"), "edge_share": round(m.attribValue("edge_area_share"), 3),
                        "face_to_edge": round(m.attribValue("face_to_edge"), 2),
                        "hotspots": kb.node(f"cluster_v{v}").parm("hotspots").eval()}
    if old:
        _set(n, old)
    return res


def budgets(asset=ASSET):
    n = hou.node(asset)
    out = hou.node(asset + "/build/OUT")
    old = _set(n, {"lod": "0"})
    res = {}
    for lod in ("0", "1", "2"):
        n.parm("lod").set(lod)
        g = out.geometry()
        dec = [p for p in g.prims() if p.attribValue("mat") == "decal"]
        res["lod" + lod] = {"tris": _tris(g), "decals": len(dec), "decal_tris": sum(len(p.vertices()) - 2 for p in dec)}
    _set(n, old)
    return res


def export_fbx(src="/obj/danchi_export"):
    """FBX per LOD and the collision hulls, into examples/danchi/export (relative to the repo)."""
    e = hou.node("/obj/export")
    inst = hou.node(src)
    rop, rcol = e.node("fbx_lod"), e.node("fbx_col")
    res = {}
    for lod in (0, 1, 2):
        inst.parm("lod").set(str(lod))
        rop.parm("sopoutput").set(f"$HIP/../export/danchi_lod{lod}.fbx")
        t = time.time()
        rop.render()
        res[f"lod{lod}"] = {"bytes": os.path.getsize(hou.text.expandString(rop.parm("sopoutput").eval())), "s": round(time.time() - t, 1)}
    inst.parm("lod").set("0")
    rcol.parm("sopoutput").set("$HIP/../export/danchi_collision.fbx")
    rcol.render()
    res["collision"] = {"bytes": os.path.getsize(hou.text.expandString(rcol.parm("sopoutput").eval()))}
    return res


def reimport():
    """Re-import every FBX and count what an engine would get."""
    res = {}
    for nm in ("danchi_lod0", "danchi_lod1", "danchi_lod2", "danchi_collision"):
        path = hou.text.expandString(f"$HIP/../export/{nm}.fbx")
        sub, msg = hou.hipFile.importFBX(path, suppress_save_prompt=True, merge_into_scene=True, import_materials=True)
        geos = [c for c in sub.allSubChildren() if c.type().name() == "geo"]
        tris, names, mats, cd, alpha, uv, decal_meshes = 0, [], set(), False, False, False, 0
        for g in geos:
            d = g.displayNode()
            if d is None:
                continue
            geo = d.geometry()
            tris += _tris(geo)
            names.append(g.name())
            a = geo.findPrimAttrib("shop_materialpath")
            if a:
                mats.update(p.attribValue(a).split("/")[-1] for p in geo.prims())
            cd = cd or geo.findVertexAttrib("Cd") is not None or geo.findPointAttrib("Cd") is not None
            alpha = alpha or geo.findVertexAttrib("Alpha") is not None or geo.findPointAttrib("Alpha") is not None
            uv = uv or geo.findVertexAttrib("uv") is not None
        matnodes = [c.name() for c in sub.allSubChildren() if c.type().category() == hou.vopNodeTypeCategory() or "material" in c.type().name()]
        res[nm] = {"meshes": len(geos), "tris": tris, "material_slots": len(mats) or len(matnodes),
                   "materials": sorted(mats)[:20], "vertex_colour": cd, "vertex_alpha": alpha, "uv": uv,
                   "mesh_names": sorted(names)[:12]}
        sub.destroy()
    return res


def fresh_instance(type_name="hocuspocus::danchi::1.1"):
    obj = hou.node("/obj")
    n = obj.createNode(type_name, "fresh_check")
    n.moveToGoodPosition()
    t = time.time()
    out = n.node("build/OUT")
    out.cook(force=True)
    dt = time.time() - t
    errs = [e for c in n.allSubChildren() for e in c.errors()]
    g = out.geometry()
    mp = {p.attribValue("shop_materialpath") for p in g.prims()}
    res = {"cook_s": round(dt, 1), "errors": errs[:5], "n_errors": len(errs), "tris": _tris(g),
           "materials_bind_inside": all(m.startswith(n.path() + "/mats/") for m in mp),
           "tex_dir": n.parm("tex_dir").eval(), "locked": n.isLockedHDA()}
    n.destroy()
    return res
