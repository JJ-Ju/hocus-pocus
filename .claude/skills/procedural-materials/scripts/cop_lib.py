"""Copernicus material helpers and starting graphs, for Houdini 22.

Load and call inside Houdini, for example through HocusPocus:

    houdini_python {code: "exec(open(r'<skill dir>/scripts/cop_lib.py').read());
                           result = build_concrete_panels('/img', 'concrete', out_dir=r'C:/proj/tex', tile_m=2.4)"}

Each builder makes one copnet with a tiling 0-1 height map first, normal, AO and curvature
derived from it, then base colour and roughness driven by masks, and writes PNGs with the
right encoding. It returns {"net": path, "maps": {name: node path}, "files": {name: file}}.
The graphs are starting points: open them with inspect and edit, and change the numbers to
match your reference.

Encoding rules applied by write_map (verified in 22.0.466):
- base colour: the default OCIO conversion, so linear values in Copernicus land as sRGB;
- normal, packed masks and other RGB data: colorconversion "raw" (the default sRGB-encodes
  RGB layers, so a flat normal would be written as 188,188,255);
- height and normal: 16-bit PNG (size1 "int16") to avoid banding;
- mono maps (roughness, AO, metal, height) are written raw by default.
"""

import os

import hou

DATA_KINDS = {"normal", "orm", "mask", "id", "position"}
HIGH_DEPTH = {"height", "normal"}


def net(parent, name, res=2048, tile=True):
    """A copnet with fixed resolution, wrap border (tiling) and 32-bit precision."""
    cn = hou.node(parent).createNode("copnet", name)
    cn.parm("setres").set(1)
    cn.parm("res1").set(res)
    cn.parm("res2").set(res)
    cn.parm("setborder").set(1)
    cn.parm("border").set("wrap" if tile else "clamp")
    cn.parm("setprecision").set(1)
    cn.parm("precision").set("b32")
    return cn


def mk(cn, node_type, name, **parms):
    """Create a COP and set parms; tuples go to parm tuples. Raises on an unknown parm."""
    n = cn.createNode(node_type, name)
    for key, value in parms.items():
        p = n.parmTuple(key) if isinstance(value, (tuple, list)) else n.parm(key)
        if p is None:
            raise RuntimeError(f"{node_type} {name}: no parm {key}")
        p.set(value)
    return n


def w(dst, idx, src, out=0):
    """Wire src's output into dst's input; either may be given by name."""
    if isinstance(idx, str):
        idx = dst.inputNames().index(idx)
    if isinstance(out, str):
        out = src.outputNames().index(out)
    dst.setInput(idx, src, out)


def normal_scale(relief_m, tile_m, exaggerate=2.0):
    """heighttonormal scale for a 0-1 height map: relief depth / (tile width / 2), since a
    Copernicus image is 2 units wide. Artists usually exaggerate by 1.5-3x."""
    return exaggerate * relief_m / (tile_m / 2.0)


def write_map(cn, node, kind, path):
    """Write one map with the encoding its kind needs, return the file path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rop = mk(cn, "rop_image", "rop_" + node.name(), coppath=node.path(), copoutput=path)
    if kind in DATA_KINDS:
        rop.parm("colorconversion").set("raw")
    if kind in HIGH_DEPTH:
        rop.parm("size1").set("int16")
    rop.render()
    if not os.path.exists(path):
        raise RuntimeError(f"rop_image did not write {path}: {rop.errors()}")
    return path


def _finish(cn, maps, kinds, out_dir, prefix):
    files = {}
    for name, node in maps.items():
        node.cook(force=True)
        if node.errors():
            raise RuntimeError(f"{node.path()}: {node.errors()}")
        if out_dir:
            files[name] = write_map(
                cn, node, kinds.get(name, name), os.path.join(out_dir, f"{prefix}_{name}.png")
            )
    return {"net": cn.path(), "maps": {k: v.path() for k, v in maps.items()}, "files": files}


def _derived(cn, height, relief_m, tile_m, ao_radius=0.05):
    nrm = mk(cn, "heighttonormal", "normal", scale=normal_scale(relief_m, tile_m))
    w(nrm, 0, height)
    ao = mk(cn, "heighttoambientocclusion", "ao", heightscale=ao_radius, viewradius=ao_radius)
    w(ao, 0, height)
    curv = mk(cn, "curvature", "curvature_raw")
    w(curv, 0, height)
    # Stretch to the full 0-1 range for use as a mask; whatever range the Curvature COP
    # gives (0-1 in 22.0.466 on these graphs), an 8-bit write then cannot clip it.
    curv01 = mk(cn, "equalize", "curvature", mode="stretch")
    w(curv01, 0, curv)
    return nrm, ao, curv01


def _ramp(node, positions, colors):
    node.parm("ramp").set(
        hou.Ramp((hou.rampBasis.Linear,) * len(positions), tuple(positions), tuple(colors))
    )


def build_concrete_panels(parent="/img", name="concrete", res=2048, out_dir=None, tile_m=2.4,
                          rows=4, cols=2, relief_m=0.02, seed=3):
    """Board-formed concrete: panels with soft seams and per-panel height, tie holes, broad
    waviness, pitting, fine grain; leaks running down from the tie holes; value from
    0.18-0.52 linear (fresh concrete measures about 0.51)."""
    cn = net(parent, name, res)
    panels = mk(cn, "tilepattern", "panels", patterntype="stackbond", patternmode="tilecount",
                stackbond_rows=rows, stackbond_cols=cols, inset=0.004, value_mode="varying",
                value=1.0, value_var=0.08, value_seed=seed)
    seams = mk(cn, "blur", "seam_soft", units="pixels", size_pixel=2.0)
    w(seams, 0, panels)
    ties = mk(cn, "tilepattern", "tieholes", patterntype="stackbond", patternmode="tilecount",
              stackbond_rows=rows * 2, stackbond_cols=cols * 3, basictype="circle", scale=0.12,
              draw="gradient", gradienttype="radial")
    broad = mk(cn, "fractalnoise", "broad", elementsize=0.6, oct=4, amp=0.5, center=0.5)
    pit_src = mk(cn, "worleynoise", "pit_src", elementsize=0.006, jitter=1.0)
    pits = mk(cn, "remap", "pits", inputmin=0.0, inputmax=0.35)
    w(pits, 0, pit_src, 0)
    pit_density = mk(cn, "fractalnoise", "pit_density", elementsize=0.25, oct=3)
    fine = mk(cn, "fractalnoise", "fine", elementsize=0.01, oct=6, amp=0.5)

    h1 = mk(cn, "blend", "h_broad", mode="add", mask=0.15)
    w(h1, 0, seams)
    w(h1, 1, broad)
    pit_inv = mk(cn, "invert", "pit_inv")
    w(pit_inv, 0, pits)
    h2 = mk(cn, "blend", "h_pits", mode="subtract", mask=0.12)
    w(h2, 0, h1)
    w(h2, 1, pit_inv)
    w(h2, 2, pit_density)
    h3 = mk(cn, "blend", "h_ties", mode="subtract", mask=0.6)
    w(h3, 0, h2)
    w(h3, 1, ties)
    h4 = mk(cn, "blend", "h_fine", mode="add", mask=0.03)
    w(h4, 0, h3)
    w(h4, 1, fine)
    height = mk(cn, "equalize", "height", mode="stretch")
    w(height, 0, h4)
    nrm, ao, curv = _derived(cn, height, relief_m, tile_m)

    leak = mk(cn, "streakblur", "tie_leaks", dirtype="coord", dir=(0.0, -1.0), length=0.08)
    w(leak, 0, ties)
    gleak = mk(cn, "grunge_leakingstreaks", "leak_grunge", elementsize=0.4)
    stain = mk(cn, "blend", "stain", mode="max", mask=0.6)
    w(stain, 0, leak)
    w(stain, 1, gleak)

    gray = mk(cn, "blend", "gray_ao", mode="multiply")
    w(gray, 0, seams)
    w(gray, 1, ao)
    tone = mk(cn, "blend", "tone", mode="blend", mask=0.3)
    w(tone, 0, gray)
    w(tone, 1, broad)
    stain_inv = mk(cn, "invert", "stain_inv")
    w(stain_inv, 0, stain)
    stained = mk(cn, "blend", "stained", mode="multiply", mask=0.35)
    w(stained, 0, tone)
    w(stained, 1, stain_inv)
    base = mk(cn, "monotorgb", "basecolor")
    _ramp(base, (0.0, 1.0), ((0.18, 0.17, 0.16), (0.52, 0.50, 0.47)))
    w(base, 0, stained)
    rough = mk(cn, "remap", "roughness", outputmin=0.95, outputmax=0.72)
    w(rough, 0, stain)

    maps = {"height": height, "normal": nrm, "ao": ao, "curvature": curv,
            "basecolor": base, "roughness": rough}
    return _finish(cn, maps, {"basecolor": "color"}, out_dir, name)


def build_painted_steel(parent="/img", name="steel", res=2048, out_dir=None, tile_m=2.0,
                        rows=2, cols=2, relief_m=0.006, paint=(0.08, 0.22, 0.30),
                        rust=(0.28, 0.12, 0.05)):
    """Painted steel panels: seams, rivets along the panel edges, paint chipped to rust at
    the edges. Paint is dielectric (metal 0); only bare steel would be metal 1."""
    cn = net(parent, name, res)
    pan = mk(cn, "tilepattern", "panels", patterntype="stackbond", patternmode="tilecount",
             stackbond_rows=rows, stackbond_cols=cols, inset=0.006)
    seam = mk(cn, "blur", "seam_bevel", units="pixels", size_pixel=3.0)
    w(seam, 0, pan, "tiles")
    stamp = mk(cn, "sdfshape", "rivet_sdf", basictype="circle", circle_radius=0.5)
    dome = mk(cn, "sdftomono", "rivet_dome", shapevaluemode=1)
    w(dome, 0, stamp)
    riv = mk(cn, "shapescatter", "rivets", linkstamps=0, stampsx=24, stampsy=24,
             scale=0.012, density=1.0)
    w(riv, "stamps", dome)
    riv_mono = mk(cn, "mono", "rivet_mono")
    w(riv_mono, 0, riv, "result")
    feather = mk(cn, "feather", "edge_feather", unitdist=0.06, includeborder=1)
    w(feather, 0, pan, "tiles")
    edge = mk(cn, "invert", "edge_band")
    w(edge, 0, feather)
    edge_thr = mk(cn, "remap", "edge_thr", op="threshold", threshold=0.5)
    w(edge_thr, 0, edge)
    riv_edge = mk(cn, "blend", "rivets_masked", mode="multiply")
    w(riv_edge, 0, riv_mono)
    w(riv_edge, 1, edge_thr)
    h = mk(cn, "blend", "h_rivets", mode="add", mask=0.3)
    w(h, 0, seam)
    w(h, 1, riv_edge)
    rust_g = mk(cn, "grunge_rust", "rust_grunge", coverage=0.5)
    chip_src = mk(cn, "blend", "chip_src", mode="multiply")
    w(chip_src, 0, edge)
    w(chip_src, 1, rust_g)
    chips = mk(cn, "remap", "chips", op="threshold", threshold=0.35)
    w(chips, 0, chip_src)
    height = mk(cn, "blend", "height", mode="subtract", mask=0.04)
    w(height, 0, h)
    w(height, 1, chips)
    nrm, ao, curv = _derived(cn, height, relief_m, tile_m, ao_radius=0.03)
    paint_c = mk(cn, "constant", "paint_col", signature="f3", f3=paint)
    rust_c = mk(cn, "constant", "rust_col", signature="f3", f3=rust)
    base = mk(cn, "blend", "basecolor", signature="f3")
    w(base, 0, paint_c)
    w(base, 1, rust_c)
    w(base, 2, chips)
    rough = mk(cn, "remap", "roughness", outputmin=0.45, outputmax=0.85)
    w(rough, 0, chips)
    maps = {"height": height, "normal": nrm, "ao": ao, "curvature": curv,
            "basecolor": base, "roughness": rough, "chips": chips}
    return _finish(cn, maps, {"basecolor": "color", "chips": "mask"}, out_dir, name)


def build_brick(parent="/img", name="brick", res=2048, out_dir=None, tile_m=2.0,
                rows=16, cols=4, relief_m=0.015):
    """Stretcher-bond brick: per-brick colour and height from the tile id, rounded and
    slope-eroded edges, recessed grainy mortar."""
    cn = net(parent, name, res)
    tiles = mk(cn, "tilepattern", "bricks", patterntype="stretcherbond", patternmode="tilecount",
               stretcherbond_rows=rows, stretcherbond_cols=cols, inset=0.012, rect_round=1,
               rect_roundness=0.15)
    rnd = mk(cn, "randommono", "brick_rand", min=0.0, max=1.0)
    w(rnd, "seed", tiles, "id")
    bev = mk(cn, "feather", "bevel", direction="circle", unitdist=0.01, includeborder=1)
    w(bev, 0, tiles, "tiles")
    rh = mk(cn, "remap", "rand_h", outputmin=0.85, outputmax=1.0)
    w(rh, 0, rnd)
    hb = mk(cn, "blend", "h_brick", mode="multiply")
    w(hb, 0, bev)
    w(hb, 1, rh)
    surf = mk(cn, "fractalnoise", "surf", elementsize=0.03, oct=6)
    slope = mk(cn, "slopedir", "slope")
    w(slope, 0, surf)
    erode = mk(cn, "distort", "slopeblur", scale=0.01, streak="min")
    w(erode, 0, hb)
    w(erode, "dir", slope)
    hm = mk(cn, "blend", "h_surf", mode="subtract", mask=0.08)
    w(hm, 0, erode)
    w(hm, 1, surf)
    mortar = mk(cn, "fractalnoise", "mortar_n", elementsize=0.005, oct=4, amp=0.1, center=0.12)
    height = mk(cn, "blend", "height", mode="max")
    w(height, 0, hm)
    w(height, 1, mortar)
    nrm, ao, curv = _derived(cn, height, relief_m, tile_m, ao_radius=0.03)
    brick_col = mk(cn, "monotorgb", "brick_col")
    _ramp(brick_col, (0.0, 0.6, 1.0), ((0.30, 0.11, 0.07), (0.42, 0.17, 0.10), (0.48, 0.26, 0.18)))
    w(brick_col, 0, rnd)
    mortar_c = mk(cn, "constant", "mortar_col", signature="f3", f3=(0.45, 0.43, 0.40))
    base = mk(cn, "blend", "basecolor", signature="f3")
    w(base, 0, mortar_c)
    w(base, 1, brick_col)
    w(base, 2, tiles, "tiles")
    rough = mk(cn, "remap", "roughness", outputmin=0.92, outputmax=0.78)
    w(rough, 0, tiles, "tiles")
    maps = {"height": height, "normal": nrm, "ao": ao, "curvature": curv,
            "basecolor": base, "roughness": rough}
    return _finish(cn, maps, {"basecolor": "color"}, out_dir, name)
