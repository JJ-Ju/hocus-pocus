# Shared helpers for the danchi build scripts (run inside Houdini via houdini_python).
#
# Paths are relative to the repository. Each script finds this file through the global DANCHI
# (the examples/danchi folder), or, if DANCHI is not set, through $HIP/.. (a hip saved in
# examples/danchi/work). Run a script as:
#   DANCHI = "<checkout>/examples/danchi"; exec(open(DANCHI + "/src/py/build.py").read())
import os
import hou
import voptoolutils

ROOT = os.path.normpath(globals().get("DANCHI") or hou.text.expandString("$HIP/..")).replace("\\", "/")
VEX = ROOT + "/src/vex"          # wrangle sources (*.vfl)
PY = ROOT + "/src/py"            # build scripts
TEXDIR = ROOT + "/tex"           # generated textures (the asset's default Texture Folder)
REPO = os.path.normpath(ROOT + "/../..").replace("\\", "/")
SKILLS = REPO + "/.claude/skills"   # skill scripts reused by the build (cop_lib, damage VEX)
OUT = ROOT                       # round-6 name, kept for older snippets


def vex(name, lib=True):
    """Read a VEX snippet; prepend lib.vfl unless lib=False."""
    src = open(f"{VEX}/{name}.vfl", encoding="utf-8").read()
    if lib:
        src = open(f"{VEX}/lib.vfl", encoding="utf-8").read() + "\n" + src
    return src


def node(parent, typ, name, inputs=(), parms=None):
    n = parent.node(name)
    if n is None:
        n = parent.createNode(typ, name)
    for i, src in enumerate(inputs):
        if src is not None:
            n.setInput(i, src)
    if parms:
        n.setParms(parms)
    return n


def wrangle(parent, name, code, inputs=(), cls="point", parms=None):
    n = node(parent, "attribwrangle", name, inputs)
    cls_idx = {"detail": 0, "prim": 1, "primitive": 1, "point": 2, "vertex": 3, "number": 4}[cls]
    n.parm("class").set(cls_idx)
    n.parm("snippet").set(code)
    if parms:
        n.setParms(parms)
    return n


def mtlx_material(parent, name):
    """A MaterialX builder subnet with the material flag; returns (subnet, standard_surface)."""
    m = parent.node(name)
    if m is not None:
        m.destroy()
    m = parent.createNode("subnet", name)
    voptoolutils._setupMtlXBuilderSubnet(subnet_node=m, name=name)
    m.setMaterialFlag(True)
    surf = m.node("mtlxstandard_surface")
    return m, surf


def mx(mat, typ, name=None, parms=None, inputs=None, sig=None):
    """Create a MaterialX VOP in mat; inputs is {input_name: node or (node, out_idx)}."""
    n = mat.createNode(typ, name) if name else mat.createNode(typ)
    if sig:
        n.parm("signature").set(sig)
    if parms:
        for k, v in parms.items():
            p = n.parmTuple(k) or n.parm(k)
            if p is None:
                raise RuntimeError(f"{n.path()} has no parm {k}: " + ",".join(x.name() for x in n.parms())[:600])
            p.set(v if isinstance(v, (list, tuple)) else (v,) if isinstance(p, hou.ParmTuple) else v)
    if inputs:
        for k, src in inputs.items():
            idx = n.inputIndex(k)
            if idx < 0:
                raise RuntimeError(f"{n.path()} has no input {k}: {n.inputNames()}")
            if isinstance(src, tuple):
                n.setInput(idx, src[0], src[1])
            else:
                n.setInput(idx, src)
    return n


def link(dst, inp, src, out=0):
    idx = dst.inputIndex(inp)
    if idx < 0:
        raise RuntimeError(f"{dst.path()} has no input {inp}: {dst.inputNames()}")
    dst.setInput(idx, src, out)
