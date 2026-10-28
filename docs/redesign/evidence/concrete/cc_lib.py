"""cc_lib.py - small Copernicus graph-building helpers for the round-E concrete sets.

Load inside hython (Houdini 22.0.466):  exec(open(".../cc_lib.py").read())

Every node type and parm used here was read from the 22.0.466 node types with
hou.nodeType(hou.copNodeTypeCategory(), name).parmTemplateGroup() before use
(docs/redesign/research/rE-concrete.md, Part 2, "Verified traps").

Units: a Copernicus image spans -1..1 (2 units) across. A tile of tile_m metres therefore has
1 unit = tile_m / 2 metres; G.U(m) converts metres to image units. Heights are built in metres
and only normalised when written, so heighttonormal can use the physical scale 2 / tile_m.
"""
import json
import os

import hou
import numpy as np


class G:
    """A copnet with fixed resolution, wrap border and 32-bit precision, plus maths helpers.
    Every helper returns the node it made; outputs are picked with (node, index) tuples."""

    def __init__(self, parent, name, res, tile_m):
        old = hou.node(f"{parent}/{name}")
        if old:
            old.destroy()
        self.cn = hou.node(parent).createNode("copnet", name)
        for k, v in dict(setres=1, res1=res, res2=res, setborder=1, border="wrap",
                         setprecision=1, precision="b32").items():
            self.cn.parm(k).set(v)
        self.res, self.tile_m, self._i = res, tile_m, 0

    # ---- units
    def U(self, metres):
        return metres * 2.0 / self.tile_m

    # ---- node creation and wiring
    def n(self, node_type, *inputs, name=None, **parms):
        self._i += 1
        nd = self.cn.createNode(node_type, name or f"{node_type}_{self._i}")
        for k, v in parms.items():
            p = nd.parmTuple(k) if isinstance(v, (tuple, list)) else nd.parm(k)
            if p is None:
                raise RuntimeError(f"{node_type}: no parm {k}")
            p.set(v)
        for i, src in enumerate(inputs):
            if src is not None:
                self.w(nd, i, src)
        return nd

    @staticmethod
    def w(dst, idx, src):
        """Wire src (node or (node, output index or name)) into dst input idx (int or name)."""
        out = 0
        if isinstance(src, tuple):
            src, out = src
        if isinstance(idx, str):
            idx = dst.inputNames().index(idx)
        if isinstance(out, str):
            out = src.outputNames().index(out)
        dst.setInput(idx, src, out)

    # ---- maths on mono layers (blend: bg = input 0, fg = input 1, mask = opacity)
    def const(self, v):
        return self.n("constant", signature="f1", f1=float(v))

    def add(self, a, b, k=1.0):
        return self.n("blend", a, b, mode="add", mask=k)

    def sub(self, a, b, k=1.0):
        return self.n("blend", a, b, mode="subtract", mask=k)

    def mul(self, a, b):
        return self.n("blend", a, b, mode="multiply")

    def div(self, a, b):
        return self.n("blend", a, b, mode="divide")

    def mx(self, a, b):
        return self.n("blend", a, b, mode="max")

    def mn(self, a, b):
        return self.n("blend", a, b, mode="min")

    def lerp(self, a, b, m, signature=None):
        nd = self.n("blend", a, b, m, mode="blend")
        if signature:
            nd.parm("signature").set(signature)
        return nd

    def scale(self, a, k, offset=0.0):
        """a * k + offset, through remap with method extend (no clamping)."""
        return self.n("remap", a, inputmin=0.0, inputmax=1.0, outputmin=offset,
                      outputmax=offset + k, method="extend")

    def remap(self, a, imin, imax, omin=0.0, omax=1.0, clamp=True):
        return self.n("remap", a, inputmin=imin, inputmax=imax, outputmin=omin, outputmax=omax,
                      method="clamp" if clamp else "extend")

    def thr(self, a, t, width=0.0):
        return self.n("remap", a, op="threshold", threshold=t, width=width)

    def inv(self, a):
        return self.n("invert", a)

    def pw(self, a, e):
        return self.n("function", a, func="pow", func_pow="powx", exponent=float(e))

    def absval(self, a):
        return self.n("function", a, func="math", func_math="abs")

    def blur_m(self, a, metres):
        return self.n("blur", a, units="image", size=self.U(metres), filter="gaussian")

    def rand(self, id_src, seed, lo=0.0, hi=1.0):
        """Per-element random from an id layer (tilepattern or worleynoise id output)."""
        # zeroinvalid: pixels outside a tilepattern shape carry an invalid id, and randommono
        # gives them one shared value (seed-dependent, e.g. 0.98) unless this is on (verified)
        r = self.n("randommono", min=lo, max=hi, seed=float(seed), zeroinvalid=1)
        self.w(r, "seed", id_src)
        return r

    def fractal(self, size_m, oct=4, rough=0.5, stretch=None, off=(0.0, 0.0), ntype="perlin"):
        """fractalnoise around 0.5. stretch=(sx, sy) needs elementsizetype 1, or elementscale
        is ignored (verified)."""
        kw = dict(elementsize=self.U(size_m), oct=float(oct), rough=rough, amp=0.5, center=0.5,
                  noisetype=ntype, off=off)
        if stretch:
            kw.update(elementsizetype=1, elementscale=stretch)
        return self.n("fractalnoise", **kw)

    # ---- read back
    @staticmethod
    def arr(node, out=0):
        node.cook(force=True)
        lay = node.layer(out)
        w, h = lay.bufferResolution()
        d = np.frombuffer(lay.allBufferElements(), dtype=np.float32)
        return d.reshape(h, w, -1)[::-1]  # buffer row 0 is the bottom; flip to image order

    def stats(self, node, out=0):
        a = self.arr(node, out)[..., 0]
        return dict(min=float(a.min()), max=float(a.max()), mean=float(a.mean()),
                    p01=float(np.percentile(a, 1)), p99=float(np.percentile(a, 99)))

    # ---- write
    def write(self, node, path, kind, res=None):
        """kind: color (OCIO, 8-bit), data (raw 8-bit), data16 (raw 16-bit: height, normal)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rop = self.n("rop_image", name="rop_" + os.path.splitext(os.path.basename(path))[0],
                     coppath=node.path(), copoutput=path)
        if kind != "color":
            rop.parm("colorconversion").set("raw")
            # PNG/TGA alpha: the default token "premult" (label "Unpremultiply if needed")
            # divides RGB by A, which wrecks a packed RGBA mask; "unpremult" is labelled "Raw"
            rop.parm("pngtga_alpha_multiplication").set("unpremult")
        rop.parm("size1").set("int16" if kind == "data16" else "int8")
        if res:
            rop.parm("setres").set(1)
            rop.parmTuple("res").set((res, res))
        rop.render()
        if not os.path.exists(path):
            raise RuntimeError(f"rop_image did not write {path}: {rop.errors()}")
        return path


def save_meta(path, meta):
    with open(path, "w") as f:
        json.dump(meta, f, indent=1)
