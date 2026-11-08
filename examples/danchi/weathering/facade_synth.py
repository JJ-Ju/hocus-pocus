"""facade_synth.py - stand-in elevation planes for the danchi block, built from the layout
constants (examples/danchi README contract), for developing the generator before the real
elevation captures arrive. Two planes: the west gable and the south front (parapets + slab
edges + stair-tower fronts + roof parapet)."""
import numpy as np

PLINTH, D_DEPTH, BAL_D, SLAB_T, PARA_H, ROOF_PARA = 0.45, 8.4, 1.2, 0.15, 1.1, 0.6
H_FLOOR, W_BAY = 2.8, 6.0


def _common(mask, ppm, ground_row, top_row):
    H, W = mask.shape
    up = np.zeros_like(mask)
    up[1:, :] = mask[1:, :] & ~mask[:-1, :]
    up[0, :] = mask[0, :]
    down = np.zeros_like(mask)
    down[:-1, :] = mask[:-1, :] & ~mask[1:, :]
    left = np.zeros_like(mask)
    left[:, 1:] = mask[:, 1:] & ~mask[:, :-1]
    left[:, 0] = mask[:, 0]
    right = np.zeros_like(mask)
    right[:, :-1] = mask[:, :-1] & ~mask[:, 1:]
    right[:, -1] = mask[:, -1]
    return {"tops": up, "bottoms": down, "edges": up | down | left | right, "ground_row": ground_row,
            "top_row": top_row}


def gable(ppm=50, floors=10, wind_from=200.0, exposure=0.6, side="W"):
    Wm = D_DEPTH
    Htot = PLINTH + floors * H_FLOOR + ROOF_PARA
    margin = int(0.25 * ppm)
    H = int(Htot * ppm) + 2 * margin
    W = int(Wm * ppm) + 2 * margin
    mask = np.zeros((H, W), bool)
    top_row, ground_row = margin, margin + int(Htot * ppm) - 1
    mask[top_row:ground_row + 1, margin:W - margin] = True
    p = {"name": side + "_gable", "orient": side, "kind": "gable", "ppm": ppm, "mask": mask, "exposed": True}
    p.update(_common(mask, ppm, ground_row, top_row))
    p["tops"] = p["tops"].copy()
    cls = np.where(mask, 1, 0).astype(np.uint8)
    pl = int(PLINTH * ppm)
    cls[ground_row - pl + 1:ground_row + 1, margin:W - margin] = 5      # plinth band (concrete)
    p["cls"] = cls
    under = np.zeros((H, W))
    y = np.arange(H)[:, None]
    under += np.exp(-np.clip(y - top_row, 0, None) / (0.12 * ppm)) * mask
    p["under_top"] = under
    p["shelter"] = np.zeros((H, W))
    # horizontal construction joints at each floor slab
    joints = []
    for f in range(1, floors + 1):
        row = ground_row - int((PLINTH + f * H_FLOOR) * ppm)
        for x in range(margin + 10, W - margin - 10, int(0.5 * ppm)):
            joints.append((row, x))
    p["joints"] = joints
    p["floor_rows"] = sorted([ground_row - int((PLINTH + f * H_FLOOR) * ppm) for f in range(0, floors + 1)] + [top_row])
    p["bay_cols"] = [margin + int(i * Wm * ppm / 4) for i in range(5)]
    # windward vertical corner washed: south corner (right side seen from the west)
    bearing = {"W": 270.0, "E": 90.0}[side]
    nwind = np.cos(np.radians(bearing - wind_from))
    p["face_rain"] = (1 - 0.6 * exposure) + 1.5 * exposure * max(0.0, nwind)
    p["lee"] = 1.0 + 0.4 * exposure * max(0.0, -nwind)
    xx = np.arange(W)[None, :]
    wash = np.exp(-np.clip((W - margin) - xx, 0, None) / (0.25 * ppm)) * max(0.0, nwind + 0.3)
    p["washed"] = np.clip(wash, 0, 1) * mask
    p["corner_prox"] = np.zeros((H, W))
    p["face_sun"] = 0.7 if side == "W" else 0.3
    p["fixings"] = []
    return p


def front(ppm=50, floors=10, units=12, wind_from=200.0, exposure=0.6, side="S"):
    """South front plane: per floor a slab edge (0.15 m) and a solid parapet (1.1 m) over 60 % of
    each unit bay (rail section on the other 40 %), stair-tower fronts on the core bays, the
    plinth and the roof parapet."""
    cores = [(4, 3.0), (8, 5.5)]           # core slots after unit index
    bays = []
    u = 0
    for k in range(units + len(cores)):
        c = [w for s, w in cores if s == u and not any(b[0] == "core" and b[2] == s for b in bays)]
        if c:
            bays.append(("core", c[0], u))
        else:
            bays.append(("unit", W_BAY, u))
            u += 1
    L = sum(b[1] for b in bays)
    Htot = PLINTH + floors * H_FLOOR + ROOF_PARA
    margin = int(0.25 * ppm)
    H = int(Htot * ppm) + 2 * margin
    W = int(L * ppm) + 2 * margin
    mask = np.zeros((H, W), bool)
    cls = np.zeros((H, W), np.uint8)
    top_row, ground_row = margin, margin + int(Htot * ppm) - 1

    def row(y_m):
        return ground_row - int(round(y_m * ppm))

    x = 0.0
    bay_cols = [margin]
    fixings = []
    corner_heads = []
    for kind, bw, _ in bays:
        c0, c1 = margin + int(x * ppm), margin + int((x + bw) * ppm)
        if kind == "core":
            mask[row(Htot):row(0) + 1, c0:c1] = True
            cls[row(Htot):row(0) + 1, c0:c1] = 1
            # inside corners where the tower meets the parapets
            for f in range(floors):
                yf = PLINTH + f * H_FLOOR
                corner_heads.append((row(yf + PARA_H), c0))
                corner_heads.append((row(yf + PARA_H), c1 - 1))
        else:
            for f in range(floors):
                yf = PLINTH + f * H_FLOOR
                mask[row(yf):row(yf - SLAB_T) + 1, c0:c1] = True               # slab edge
                cls[row(yf):row(yf - SLAB_T) + 1, c0:c1] = 1
                s0, s1 = (c0, c0 + int(0.6 * bw * ppm)) if side == "S" else (c0, c1)   # solid parapet
                mask[row(yf + PARA_H):row(yf) + 1, s0:s1] = True
                cls[row(yf + PARA_H):row(yf) + 1, s0:s1] = 1
                # rail posts along the rail section, on the slab edge top
                if side == "S":
                    for xp in np.arange(0.6 * bw + 0.1, bw - 0.05, 1.2):
                        fixings.append((row(yf), margin + int((x + xp) * ppm), "post"))
        bay_cols.append(c1)
        x += bw
    # plinth and roof parapet
    mask[row(PLINTH):row(0) + 1, margin:W - margin] = True
    cls[row(PLINTH):row(0) + 1, margin:W - margin] = 5
    mask[row(Htot):row(Htot - ROOF_PARA) + 1, margin:W - margin] = True
    cls[row(Htot):row(Htot - ROOF_PARA) + 1, margin:W - margin] = 2
    p = {"name": side + "_front", "orient": side, "kind": "front", "ppm": ppm, "mask": mask, "cls": cls, "exposed": True}
    p.update(_common(mask, ppm, ground_row, top_row))
    p["floor_rows"] = sorted({row(PLINTH + f * H_FLOOR + PARA_H) for f in range(floors)} |
                             {row(PLINTH + f * H_FLOOR - SLAB_T) for f in range(floors)} | {top_row, ground_row})
    p["floor_rows"] = sorted([row(PLINTH + f * H_FLOOR) for f in range(floors + 1)] + [top_row])
    p["bay_cols"] = bay_cols
    p["bay_kinds"] = [k for k, _w, _u in bays]
    p["fixings"] = fixings
    p["corner_heads"] = corner_heads
    nwind = np.cos(np.radians((180.0 if side == "S" else 0.0) - wind_from))
    p["face_rain"] = (1 - 0.6 * exposure) + 1.5 * exposure * max(0.0, nwind)
    p["lee"] = 1.0 + 0.4 * exposure * max(0.0, -nwind)
    p["shelter"] = np.zeros((H, W))
    under = np.zeros((H, W))
    yy = np.arange(H)[:, None]
    under += np.exp(-np.clip(yy - top_row, 0, None) / (0.12 * ppm)) * mask
    p["under_top"] = under
    p["washed"] = np.zeros((H, W))
    cp = np.zeros((H, W))
    for (r0, c) in corner_heads:          # wet inside corner: falls off 12 cm across, 0.9 m down
        xa, xb = max(0, c - int(0.6 * ppm)), min(W, c + int(0.6 * ppm))
        ya, yb = r0, min(H, r0 + int(3.0 * ppm))
        dx = np.abs(np.arange(xa, xb) - c)[None, :] / (0.12 * ppm)
        dy = (np.arange(ya, yb) - r0)[:, None] / (0.9 * ppm)
        cp[ya:yb, xa:xb] = np.maximum(cp[ya:yb, xa:xb], 0.6 * np.exp(-dx) * np.exp(-dy))
    p["corner_prox"] = cp * mask
    p["face_sun"] = 1.0 if side == "S" else 0.0
    p["joints"] = []
    return p
