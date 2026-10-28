# check_skeleton.py — contract checks on the placed kit: per floor, the facade pieces must tile
# [x0, x1] exactly (no gaps, no overlaps) on both sides; roles per floor must match the plan.
import collections

def check(sub_path="/obj/danchi"):
    geo = hou.node(sub_path + "/build/place_kit").geometry()
    plan = hou.node(sub_path + "/build/plan").geometry()
    x0 = plan.attribValue("x0"); L = plan.attribValue("L")
    floors = plan.attribValue("floors"); units = plan.attribValue("units"); ncores = plan.attribValue("ncores")
    name_a = geo.findPrimAttrib("name"); floor_a = geo.findPrimAttrib("floor")
    # collect x intervals of facade wall pieces per floor and side
    spans = collections.defaultdict(list)
    counts = collections.Counter()
    for pr in geo.prims():
        nm = pr.attribValue(name_a)
        counts[(nm, pr.attribValue(floor_a))] += 1
    # bbox per piece instance: group by (name, floor, bay, side)
    inst = collections.defaultdict(lambda: [1e9, -1e9])
    for pr in geo.prims():
        nm = pr.attribValue(name_a)
        if nm not in ("bal_wall", "cor_wall", "core_wall_3", "core_wall_55"):
            continue
        key = (nm, pr.attribValue("floor"), pr.attribValue("bay"), pr.attribValue("side"))
        for v in pr.vertices():
            x = v.point().position()[0]
            inst[key][0] = min(inst[key][0], x); inst[key][1] = max(inst[key][1], x)
    for (nm, f, b, s), (a, c) in inst.items():
        side = 0 if nm.startswith("bal") or nm.startswith("core") else 1
        spans[(f, side)].append((a, c))
    problems = []
    for (f, side), iv in spans.items():
        if side == 1:
            continue
        iv.sort()
        if abs(iv[0][0] - x0) > 1e-3 or abs(iv[-1][1] - (x0 + L)) > 1e-3:
            problems.append(f"floor {f}: ends {iv[0][0]:.3f}..{iv[-1][1]:.3f} vs {x0:.3f}..{x0+L:.3f}")
        for (a1, c1), (a2, c2) in zip(iv, iv[1:]):
            if abs(c1 - a2) > 1e-3:
                problems.append(f"floor {f}: {'gap' if a2 > c1 else 'overlap'} {c1:.3f}->{a2:.3f}")
    # corridor side: cor_wall per floor plus core bays (core walls are balcony-side only)
    for f in range(floors):
        if counts[("bal_wall", f)] // 6 != units or counts[("cor_wall", f)] // 6 != units:
            problems.append(f"floor {f}: bal_wall {counts[('bal_wall', f)]//6} cor_wall {counts[('cor_wall', f)]//6} != {units}")
        nc = (counts[("core_wall_3", f)] + counts[("core_wall_55", f)]) // 6
        if nc != ncores:
            problems.append(f"floor {f}: cores {nc} != {ncores}")
    return {"floors": floors, "units": units, "ncores": ncores, "L": round(L, 3),
            "has_lift": plan.attribValue("has_lift"), "problems": problems[:12], "n_problems": len(problems)}
