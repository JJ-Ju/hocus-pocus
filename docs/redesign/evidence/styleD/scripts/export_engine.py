#!/usr/bin/env hython
"""export_engine.py - round D: pack the painterly vertex data of the golden piece into channels
every engine reads, export glTF (.glb), re-import it, and check that the values survive.

Packing (Unreal: vertex colour + UV channel 1; Godot: COLOR + UV2; glTF: COLOR_0 + TEXCOORD_1):
  COLOR_0.rgb = 0.5 + (pd_tint - 1) * 2.5  (hue drift x sun warmth; decode 1 + (c - 0.5) * 0.4)
  COLOR_0.a   = sdir      (1 = strokes along the slab, 0 = vertical)
  TEXCOORD_0  = uv        (the unwrapped 0-1 set the baked textures use)
  TEXCOORD_1  = (pd_famp, pd_liftn)  (detail amplitude; lift-colour mix 0-1)
The lift strength (soffit boost) is rebuilt in the engine shader from the normal (N.y), and the
lift colour from pd_liftn and three colour parameters; see the research note for the recipes.

  hython export_engine.py <scene.hip> <out_dir> [--floor 3] [--bay 5]
"""
import argparse
import importlib.util
import os

import hou
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("pd_bake", os.path.join(HERE, "bake_piece.py"))
BK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BK)
AP = BK.AP

PACK_VEX = r'''
// 8-bit vertex colour clamps at 1 (Unreal FColor): store the tint as a 0.5-centred delta.
// decode in the engine: tint = 1 + (COLOR.rgb - 0.5) * 0.4   (covers 0.8 .. 1.2)
v@Cd = clamp(0.5 + (v@pd_tint - 1) * 2.5, 0, 1);
f@Alpha = prim(0, "sdir", @primnum);   // prim attribute: read with prim() in a vertex wrangle
v@uv2 = set(f@pd_famp, f@pd_liftn, 0);
'''


def vals(geo, name, cls="vertex"):
    a = geo.findVertexAttrib(name) if cls == "vertex" else geo.findPointAttrib(name)
    if a is None:
        a = geo.findPointAttrib(name) or geo.findPrimAttrib(name)
        if a is None:
            return None, None
        cls = {hou.attribType.Point: "point", hou.attribType.Prim: "prim"}[a.type()]
    f = {"vertex": geo.vertexFloatAttribValues, "point": geo.pointFloatAttribValues,
         "prim": geo.primFloatAttribValues}[cls]
    return np.array(f(name)).reshape(-1, a.size()), cls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hip")
    ap.add_argument("out")
    ap.add_argument("--floor", type=int, default=3)
    ap.add_argument("--bay", type=int, default=5)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    AP.setup(a.hip, "t2", dict(drift=True, lift=True, detail=True), AP.TEX)
    obj, proc, bakesop, _ = BK.piece_sops(a.floor, a.bay, AP.P["det_tile"], "t2")
    pk = obj.createNode("attribwrangle", "pack_engine")
    pk.setInput(0, bakesop)
    pk.parm("class").set("vertex")
    pk.parm("snippet").set(PACK_VEX)
    keep = obj.createNode("attribdelete", "keep_engine_attrs")
    keep.setInput(0, pk)
    keep.parm("vtxdel").set("* ^uv ^uv2 ^N ^Cd ^Alpha")
    keep.parm("ptdel").set("* ^P")
    keep.parm("primdel").set("*")
    keep.parm("dtldel").set("*")
    glb = os.path.join(a.out, "piece_t2.glb").replace("\\", "/")
    rop = hou.node("/out").createNode("gltf", "pd_gltf")
    rop.parm("usesoppath").set(1)
    rop.parm("soppath").set(keep.path())
    rop.parm("outputfile").set(glb)
    rop.parm("exportmaterials").set(0)
    rop.parm("exportcustomattributes").set(0)
    rop.render()
    print("exported", glb, os.path.exists(glb), os.path.getsize(glb) if os.path.exists(glb) else 0, "bytes")
    # re-import with the glTF SOP and compare
    imp = obj.createNode("gltf::2.0", "reimport")
    imp.parm("gltffile").set(glb)  # TRAP: the parm is gltffile, not filename
    print("import-as menu", imp.parm("importnodegeometryas").menuItems(), "loadby", imp.parm("loadby").menuItems())
    up = obj.createNode("unpack", "reimport_unpack")
    up.setInput(0, imp)
    gi = up.geometry()
    g0 = keep.geometry()
    print("source attribs  vtx", [x.name() for x in g0.vertexAttribs()], "pt", [x.name() for x in g0.pointAttribs()])
    print("reimport attribs vtx", [x.name() for x in gi.vertexAttribs()], "pt", [x.name() for x in gi.pointAttribs()],
          "prims", len(gi.prims()), "points", len(gi.points()))
    for nm in ("Cd", "Alpha", "uv", "uv2"):
        s, cs = vals(g0, nm)
        r, cr = vals(gi, nm)
        if s is None or r is None:
            print(nm, "missing on", "source" if s is None else "reimport")
            continue
        # glTF stores per point (vertices split on seams): compare the value distributions
        q = [0, 5, 50, 95, 100]
        print("%-5s src(%s) pct %s | reimport(%s) pct %s" % (nm, cs, np.round(np.percentile(s, q, axis=0), 4).tolist(),
                                                           cr, np.round(np.percentile(r, q, axis=0), 4).tolist()))


if __name__ == "__main__":
    main()
