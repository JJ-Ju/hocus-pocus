"""real_planes.py - generator planes from the round-7 elevation captures of the real building.

Each view (S, N, W) is an orthographic capture at 50 px/m: class codes, depth, normal, albedo. A
plane here is that view's visible surfaces; the weathering features are read from the class and
depth images:
  surfaces   painted pixels, split where the depth jumps (> 5 cm) between vertical neighbours
  tops       first pixel of a surface run whose pixel above is empty or farther away (exposed top)
  shelter    a nearer surface within 1.5 m above (under a balcony, a slab, a canopy)
  bottoms    last pixel of a run (drip edges)
  edges      tops, bottoms and the side edges where this surface is the nearer one (arrises)
  sill_ends  the two ends of each window's bottom edge (glass above paint)
  corner_heads  tops of inside corners (a farther wall beside a nearer one)
  fixings    metal touching paint below it (rail posts, brackets), one per 0.6 m
Storeys and bays come from the building plan (building.json), as in r7_to_gate.
"""
import json
import os

import numpy as np

import weather_measure as wm

# capture class codes -> gate classes (1 paint, 2 coping, 3 soffit, 4 concrete, 5 plinth, 6 glass, 7 metal, 8 prop)
CODES = {0: "none", 1: "paint_ext", 2: "coping", 3: "soffit", 4: "concrete", 5: "glass", 6: "decal", 7: "steel",
         8: "alu", 9: "board", 10: "frp", 11: "room", 12: "fabric", 13: "plastic", 14: "sign", 15: "floor",
         16: "metal"}
GATE = {"paint_ext": 1, "coping": 2, "soffit": 3, "concrete": 4, "glass": 6, "steel": 7, "alu": 7, "metal": 7,
        "frp": 8, "plastic": 8, "fabric": 8, "board": 8, "sign": 8, "room": 8, "floor": 8, "decal": 1, "none": 0}
LUT = np.zeros(256, np.uint8)
for c, n in CODES.items():
    LUT[c] = GATE[n]


def _runs_start(surf, brk):
    """First pixel of each vertical run: surface here and (not above, or a break between)."""
    H, W = surf.shape
    above = np.zeros_like(surf)
    above[1:] = surf[:-1]
    b = np.zeros_like(surf)
    b[1:] = brk[1:]
    return surf & (~above | b)


def _label_cols(mask):
    lab, n = wm.label(mask)
    return lab, n


def build_plane(view, z, frame, plan, ppm=50, kind=None, wind_from=200.0, exposure=0.6):
    code = np.rint(z["class_raw"] / 257.0).astype(np.int64)
    cls = LUT[np.clip(code, 0, 255)]
    alb = z["albedo"]
    depth = z["depth"][..., 0].astype(np.float64)
    cov = alb[..., 3] if alb.shape[-1] > 3 else np.ones(cls.shape)
    H, W = cls.shape
    painted = np.isin(cls, (1, 2)) & (cov > 0.999)
    mask = painted.copy()
    # vertical breaks: depth jump to the pixel above
    dz = np.zeros((H, W))
    dz[1:] = depth[1:] - depth[:-1]                 # > 0: this pixel farther than the one above
    brk = np.abs(dz) > 0.05
    start = _runs_start(mask, brk)
    above_cls = np.zeros_like(cls)
    above_cls[1:] = cls[:-1]
    above_dep = np.full((H, W), np.inf)
    above_dep[1:] = depth[:-1]
    above_surface = np.zeros((H, W), bool)
    above_surface[1:] = (cls[:-1] > 0) & (cov[:-1] > 0.5)
    # exposed top: nothing above, or the thing above is farther away (we stick out past it)
    exposed_top = start & (~above_surface | (above_dep > depth + 0.05))
    # under a nearer thing: sheltered start
    sheltered_start = start & above_surface & (above_dep < depth - 0.05)
    below = np.zeros_like(mask)
    below[:-1] = mask[1:] & ~brk[1:]
    bottoms = mask & ~below
    # side arrises: horizontal depth step where this pixel is the nearer one, or a side of the mask
    left_d = np.full((H, W), np.inf)
    left_d[:, 1:] = np.where(mask[:, :-1], depth[:, :-1], np.inf)
    right_d = np.full((H, W), np.inf)
    right_d[:, :-1] = np.where(mask[:, 1:], depth[:, 1:], np.inf)
    side_edge = mask & ((left_d > depth + 0.05) | (right_d > depth + 0.05))
    edges = exposed_top | bottoms | side_edge
    # inside corners: this pixel farther than its side neighbour (a nearer wall right beside it)
    inside = mask & ((left_d < depth - 0.05) | (right_d < depth - 0.05))
    # inside-corner runs at least 0.3 m tall; their top pixels are the corner heads
    ic = inside.copy()
    ic_above = np.zeros_like(ic)
    ic_above[1:] = ic[:-1]
    heads = np.argwhere(ic & ~ic_above)
    corner_heads = []
    for (yy, xx) in heads:
        n_run = 0
        while yy + n_run < H and ic[yy + n_run, xx]:
            n_run += 1
            if n_run >= int(0.3 * ppm):
                corner_heads.append((int(yy), int(xx)))
                break
    # shelter: a nearer surface within 1.5 m above
    sh = np.zeros((H, W), np.float32)
    reach = int(1.5 * ppm)
    occ = (cls > 0) & (cov > 0.5)
    near_above = np.zeros((H, W), bool)
    dep_occ = np.where(occ, depth, np.inf)
    # sliding min of depth over the `reach` rows above
    from weather_measure import _sliding_max
    neg = -dep_occ
    sm = _sliding_max(neg, reach // 2, 0)            # max of -depth over +-reach/2 rows
    shifted = np.full((H, W), -np.inf)
    shifted[reach // 2 + 1:] = sm[:H - reach // 2 - 1]  # window centred reach/2 above
    near_above = mask & (-shifted < depth - 0.3)
    sh = near_above.astype(np.float32)
    sh = wm.gauss(sh, 0.15 * ppm).astype(np.float32) * mask
    # sills: bottom edge of glass components with paint just below
    glass = cls == 6
    gl_below = np.zeros_like(glass)
    gl_below[:-1] = glass[:-1] & mask[1:] & (np.abs(depth[1:] - depth[:-1]) < 0.3)   # the window's own sill
    lab, n = wm.label(gl_below)
    sill_ends = []
    if n:
        ys, xs = np.nonzero(lab)
        ids = lab[ys, xs]
        for i in range(1, n + 1):
            sel = ids == i
            if sel.sum() < 0.3 * ppm:
                continue
            yy = int(ys[sel].max()) + 1
            sill_ends.append((yy, int(xs[sel].min())))
            sill_ends.append((yy, int(xs[sel].max())))
    # fixings: metal directly above paint, sampled every 0.6 m along each run of contacts
    metal = cls == 7
    # metal rising >= 20 cm above a contact with paint: posts and brackets, not bottom rails
    up = np.zeros((H, W), np.int32)
    for y in range(1, H):
        up[y] = np.where(metal[y], up[y - 1] + 1, 0)
    contact = np.zeros_like(metal)
    contact[:-1] = metal[:-1] & mask[1:] & (up[:-1] >= int(0.2 * ppm))
    fixings = []
    # one run per rail: contacts within 0.3 m of each other on a row merge before sampling
    k = int(0.3 * ppm)
    merged = contact.copy()
    for d in range(1, k + 1):
        merged[:, d:] |= contact[:, :-d]
        merged[:, :-d] |= contact[:, d:]
    contact = merged & np.vstack([np.zeros((0, W), bool), contact.any(axis=1, keepdims=True).repeat(W, 1)])
    lab, n = wm.label(contact)
    if n:
        ys, xs = np.nonzero(lab)
        ids = lab[ys, xs]
        order = np.argsort(ids, kind="stable")
        ys, xs, ids = ys[order], xs[order], ids[order]
        cut = np.flatnonzero(np.diff(ids)) + 1
        for seg_y, seg_x in zip(np.split(ys, cut), np.split(xs, cut)):
            x0, x1 = seg_x.min(), seg_x.max()
            for x in range(int(x0), int(x1) + 1, int(1.2 * ppm)):
                j = np.argmin(np.abs(seg_x - x))
                fixings.append((int(seg_y[j]) + 1, int(seg_x[j]), "post"))
    # frame rows
    top_y = frame["top_y"]
    row = lambda yv: int(round((top_y - yv) * ppm - 0.5))  # noqa: E731
    floors = plan.get("floors", 10)
    Hs = plan.get("H", 2.8)
    ytop = plan.get("ytop", 28.45)
    ground_row = row(0.0)
    top_row = row(ytop + 0.6)
    floor_rows = sorted({row(0.45 + f * Hs) for f in range(floors + 1)} | {top_row})
    kind = kind or ("gable" if view in ("W", "E") else "front")
    if view in ("S", "N"):
        x0 = plan.get("x0", -40.25)
        ed = [x0]
        for w in plan["bay_w"]:
            ed.append(ed[-1] + w)
        left = frame["left_edge"]["value"]
        sgn = 1 if view == "S" else -1
        bay_cols = sorted(int(round((sgn * (x - left)) * ppm)) for x in ed)
        bt = plan.get("bay_t", [0] * len(plan["bay_w"]))
        kinds = ["core" if t else "unit" for t in bt]
        bay_kinds = kinds if view == "S" else kinds[::-1]
    else:
        left = frame["left_edge"]["value"]
        bay_cols = [int(round((zz - left) * ppm)) for zz in (-5.6, -4.2, -2.1, 0.0, 2.1, 4.2, 5.4)]
        bay_kinds = None
    bearing = {"S": 180.0, "N": 0.0, "W": 270.0, "E": 90.0}[view]
    nwind = np.cos(np.radians(bearing - wind_from))
    p = {"name": view + ("_gable" if kind == "gable" else "_front"), "orient": view, "kind": kind, "ppm": ppm,
         "mask": mask, "cls": cls, "exposed": True, "tops": exposed_top, "bottoms": bottoms, "edges": edges,
         "flow_start": start, "ground_row": ground_row, "top_row": top_row, "floor_rows": floor_rows,
         "bay_cols": bay_cols, "sill_ends": sill_ends, "corner_heads": corner_heads, "fixings": fixings,
         "joints": [], "shelter": sh, "depth": depth, "decal": (code == 6) & mask}
    if bay_kinds:
        p["bay_kinds"] = bay_kinds
    p["face_rain"] = (1 - 0.6 * exposure) + 1.5 * exposure * max(0.0, nwind)
    p["lee"] = 1.0 + 0.4 * exposure * max(0.0, -nwind)
    # under a top: decays 12 cm below each exposed top, within the surface
    ut = np.zeros((H, W), np.float32)
    dist = np.full(W, 1e9)
    for y in range(H):
        dist = np.where(exposed_top[y], 0.0, np.where(mask[y] & ~start[y], dist + 1, np.where(start[y], 1e9, 1e9)))
        ut[y] = np.exp(-dist / (0.12 * ppm))
    p["under_top"] = ut * mask
    cp = np.zeros((H, W), np.float32)
    for (r0, c) in corner_heads:
        xa, xb = max(0, c - int(0.6 * ppm)), min(W, c + int(0.6 * ppm))
        ya, yb = r0, min(H, r0 + int(3.0 * ppm))
        dx = np.abs(np.arange(xa, xb) - c)[None, :] / (0.12 * ppm)
        dy = (np.arange(ya, yb) - r0)[:, None] / (0.9 * ppm)
        cp[ya:yb, xa:xb] = np.maximum(cp[ya:yb, xa:xb], 0.6 * np.exp(-dx) * np.exp(-dy))
    p["corner_prox"] = cp * mask
    p["washed"] = np.zeros((H, W), np.float32)
    if kind == "gable":
        cols = np.flatnonzero(mask.any(axis=0))
        xx = np.arange(W)[None, :]
        edge_x = cols[-1] if view == "W" else cols[0]
        wash = np.exp(-np.abs(edge_x - xx) / (0.25 * ppm)) * max(0.0, nwind + 0.3)
        p["washed"] = (np.clip(wash, 0, 1) * mask).astype(np.float32)
    p["face_sun"] = {"S": 1.0, "W": 0.7, "E": 0.5, "N": 0.0}[view]
    return p


def load_real(root, cfg="clean", views=("W", "S", "N")):
    E = json.load(open(os.path.join(root, "out", "elev_r7", "elevations.json")))
    B = json.load(open(os.path.join(root, "out", "elev_r7", "building", "building.json")))["plan"]
    planes, bases = [], {}
    for v in views:
        z = np.load(os.path.join(root, "real", "%s_%s.npz" % (cfg, v)))
        p = build_plane(v, z, E["frames"][v], B)
        import material as mt
        hm, vm, pts = mt.joints(p)                     # construction and induced joints on solid walls
        p["joint_h"], p["joint_v"], p["joints"] = hm, vm, pts
        planes.append(p)
        bases[p["name"]] = z["albedo"][..., :3].astype(np.float32)
    return planes, bases
