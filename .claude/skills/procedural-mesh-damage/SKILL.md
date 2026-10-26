---
name: procedural-mesh-damage
description: Procedurally add edge wear and common damage to game meshes in Houdini through the HocusPocus MCP tools — chipped edges and corners, spalling, cracks, missing chunks, dents, bent rails, worn steps, weathered stone — driven by masks for where damage really happens, kept closed, UV-mapped, seam-safe for modular pieces, budgeted, varied per instance and validated. Use when a piece, kit or prop needs geometric wear or damage, or when deciding what damage belongs in geometry versus a normal map.
---

# Procedural edge wear and damage on the mesh

Damage is what makes a clean modular piece read as a real object with a history. This skill
covers damage in the geometry itself. Wear in the texture (edge highlights, dirt, rust) belongs
to the `procedural-materials` skill; the two are designed together, since a chip in the mesh
should show primer or bare concrete in the material.

Every node and parameter name here was checked in Houdini 22.0.466. The VEX in `scripts/` was
run there on a test piece.

**Read [references/causes.md](references/causes.md) before placing any damage.** It covers why
edges break and faces only pit, what photographs of real breaks show, edge exposure weights,
and the strike zones of people and industry. Then use the scripts in workflow order: start
from `cluster_mask.vfl` and `chip_points_edge.vfl`, not the older chip scripts.

## Principles

1. **Damage follows cause.** Chips concentrate on convex edges and corners, more near the
   ground and at contact heights (0.3–1.2 m), on corners people and vehicles pass, and on top
   edges exposed to weather. Thin parts break first. Sheltered and concave areas stay clean.
   Use and industry have their own strike zones (door feet, rack uprights below 0.3 m, aisle
   corners), listed in [references/causes.md](references/causes.md).
2. **Edges take the damage; faces dissipate it.** The force needed to chip rises linearly
   with distance from the edge, so the blow that takes a chip off an arris only makes a
   small crater on a face.
   - **One impact makes one asymmetric scar that removes the arris.** The struck face keeps
     a small bite; the shell runs across the adjacent face and feathers out.
   - **Never two large removals on opposite faces of one edge.** Both faces lose material
     only at a corner, as one wedge.
   - **Faces get only small, shallow pits,** at most 0.3× the nearby edge damage, densest
     beside damaged edges.
   - **Edges also wear round** along their whole length (5–25 mm on old concrete), and the
     breaks sit inside that rounding.
3. **Cluster, don't sprinkle (80/20).** About 80 % of the notable damage sits on 20–30 % of
   the edge length, in a few hotspots chosen by cause. Each hotspot has one dominant break,
   satellite chips around it, and a halo of worn, rounder arris. Between hotspots the edges
   stay crisp with sparse small nicks, about one per metre: aged, never pristine. Hotspot
   sizes follow a power law, one big and many small. Across a kit, a share of instances
   (30–50 %) gets background wear only. In photographs, most hotspots are runs of overlapping
   small bites (20–60 cm of 0.5–3 cm bites), and only a few are one large shell break.
4. **One mask drives every layer.** The same hotspots set chip density and size, bevel
   width, edge wear in the shader, grime, streaks and rust, so a cause shows all its effects
   in one place. Layers from independent noises read as procedural. A chip is an edge too:
   its lowest rim point is where a streak starts.
5. **Silhouette in geometry, the rest in the bake.** A break larger than a few centimetres at
   play distance, or one that changes the outline, is real geometry. Smaller nicks, pitting and
   fine cracks go to a normal map baked from a damaged high-poly copy, or to edge decals.
6. **Modular pieces stay tileable.** No damage within a margin of a face that meets a
   neighbour, unless the damage is generated once and mirrored onto both sides. Check that the
   seam profile is unchanged.
7. **Every instance different.** Damage is seeded per instance, or chosen from a few baked
   variants, so repeated pieces never show identical chips.
8. **Validate numbers, not pictures.** The worst failures here are silent: a boolean with
   packed cutters returns the input unchanged, and a world-space SDF erode can delete the
   mesh. Check counts after every damage stage.

## Workflow

Work on one piece at a time, at final metrics, after its clean form is done and approved. Each
step ends with a check.

1. **Clean base.** A closed, manifold piece with consistent winding (`polydoctor` or `clean`),
   bevelled where edges catch light (`polybevel`, `filletshape` chamfer or round), and UV- or
   trim-mapped. Keep this node as the **reference** for UV transfer and validation.
   *Check:* `damage_validate.vfl` on it reports 0 open and 0 non-manifold edges.
2. **Cluster mask.** `cluster_mask.vfl` (detail wrangle) on a dense copy of the piece, with
   the clean pre-bevel piece in input 1. It picks hotspots on convex edges (and a few on flat
   faces) weighted by cause: ground, the 0.3–1.2 m contact band, upward-facing edges,
   corners, a fade at seams, and an optional painted `damage_cause`. It writes three point
   attributes:
   - `damage_mask`: hotspots over a background of about 0.12;
   - `damage_hot`: the hotspots alone;
   - `damage_halo`: a wider, smooth zone for worn arrises.

   It also writes the hotspot list to detail (`hs_P`, `hs_r`, `hs_s`). The hotspots depend
   only on input 1 and the parms, so the same settings give the same field on the game
   mesh, a render copy, measuring curves and a UV copy.

   Settings that tested well: `hotspots_per_m` 0.75–0.9, `r_min` 0.15, `r_max` 0.65–0.9,
   `size_bias` 1.5, `s_min` 0.45, `background` 0.12, `breakup` 0.6, `halo` 1.5. Fold other
   causes into `damage_cause`, such as thinness (`measurethickness`) or exposure
   (`maskbyfeature`).

   *Check:* show `damage_hot` as `Cd` at the judging distance: a few distinct blobs, not
   speckle. Resample the convex edges at 1 cm and measure the share of edge length that holds
   80 % of the `damage_hot` mass; it should be 0.2–0.3. Measure on `damage_hot`, not on
   `damage_mask`, whose background covers everything by design.
3. **Large breaks.** Missing chunks at corners: fracture the piece (`voronoifracture`,
   `rbdmaterialfracture` with `materialtype` concrete), choose the pieces where the mask
   peaks, and boolean-subtract **only those pieces from the reference**. Never delete pieces
   and fuse the rest: shared interior walls become thousands of non-manifold edges.
4. **Edge breaks.** Run `chip_points_edge.vfl` on the low-poly pre-bevel piece (a chamfer
   doubles the convex edges), with the mask carrier in input 1. It writes one point per
   cutter, oriented along the edge: x along the edge, y across the shell face, z into the
   material, scaled by `v@scale`.
   - **Every cutter is centred on the edge line** (within 0.2–0.5 of the chip depth *d*), so
     the arris is always removed.
   - **The scar is asymmetric.** The struck face keeps a bite about *d* wide; the shell runs
     2–3 *d* across the other face and 2.5–3.5 *d* along the edge. The struck face comes from
     the cause: on top edges the shell goes on the vertical face; on vertical edges it comes
     from `impact_dir`.
   - **A cutter that overlaps an earlier large one takes the same shell face**, so two large
     removals never sit opposite each other.
   - **Each hotspot becomes one of three things:**
     - a run (most hotspots): 20–60 cm of overlapping power-law bites, 0.5–3 cm each;
     - a shell break: one 10–30 cm break plus a smaller cut at one end;
     - a corner wedge, only at a vertex.
   - **Edges are weighted by exposure:** top 1.0, windward vertical 0.8, other vertical 0.5,
     bottom 0.3 (0.9 in the contact band). Within 25 cm of a corner, breaks are 1.7× larger
     and 2.5× denser.
   - **Faces get only shallow pits.** Their density falls as exp(−distance / 0.15 m) from the
     nearest edge, and they get smaller further out.

   Build 8 cutter variants of about unit radius:
   - **0–3, breaks:** a 40-point hull, remeshed, then shaped by `cutter_shape.vfl`, which
     feathers or hinges the far end and makes one end thicker;
   - **4–5, nicks:** 18-point hulls;
   - **6–7, pits:** 14-point hulls.

   Copy them with Copy to Points, **`pack` off**, with piece attribute `variant`. Then
   `boolean` subtract (`usebinsidea` on, group `cut`).

   *Check:* `damage_measure.vfl` with these inputs:
   - input 0: the damaged piece, with prim `island` from Connectivity on the `cut` group;
   - input 1: the clean bevelled piece;
   - input 2: the pre-bevel piece.

   It must report all three of:
   - `flank_runs` = 0;
   - `edge_area_share` of 0.9 or more;
   - `face_to_edge` of 0.3 or less.

   (`chip_points_clustered.vfl` is the earlier version, which pushed cutters in along the edge
   bisector. That missed the arris and left two scoops flanking an intact edge on 9 of 10
   wall seeds. `chip_points.vfl` spreads chips evenly; use it for background nicks only.)
5. **Varying edge width.** Keep the kit's constant chamfer as the default and widen it around
   hotspots:
   - set a point attribute `bevel_scale` = lerp(0.1, 1, `damage_halo`^1.2), reset to the
     kit's chamfer ratio at seams;
   - `polybevel::3.0` with `useoffsetscale` `byattrib` (`pointscaleattr`);
   - **`divide`, then the Boolean.**

   On old concrete, also round the whole arris (5–25 mm). Edges stay crisp in clean stretches
   and worn round around breaks, for about 20 % more triangles. Add edge wear in the shader from `damage_halo` (lighter, rougher, a noisy band
   along the arris). It costs no triangles and gives the best abrasion read in colour.
6. **Small nicks.** Leave them to the normal map unless this is a bake source or a hero
   piece that can afford 2.5–3× the triangles. Then use SDF erosion along the edges, masked by
   the clusters: VDB from Polygons, then a Volume Wrangle with `edge_erosion_clustered.vfl`,
   then Convert VDB at adaptivity 0.1–0.3. It looks the most weathered, but it re-meshes the
   seams and drops attributes.
7. **Validate.** `damage_validate.vfl` with the reference in input 1. Everything below must
   hold:
   - `unchanged` is 0;
   - `open_edges` and `nonmanifold_edges` are 0;
   - `seam_changed` is 0 for tiling pieces;
   - `zero_uv_prims` is 0 after step 8;
   - triangles are within budget;
   - the node has no errors.
8. **Fix UVs and normals.** A boolean leaves cut faces at uv (0,0); the VDB route drops every
   attribute. Transfer vertex `uv` from the reference with `attribtransfer` onto the cut-face
   group (keeps trim mapping), or flatten those faces with `uvflatten` and lay them out. Keep the
   cut-face group as a material or vertex-colour channel for "broken interior" texturing:
   exposed aggregate, darker and rougher, grime in the recesses. Cut faces textured like the
   clean surface read bright and fake.
   Recompute normals with a cusp angle (`normal`, `cuspangle`).
9. **Budget and bake.** `polyreduce` (`hardfeatureedges`, `silhouetteweight`,
   `vattribseamweight` to keep UV seams), triangulate with `divide`, count triangles. Bake
   small damage from the dense copy into the game mesh's normal and AO maps (see the
   `procedural-materials` skill).
10. **Streaks and micro fields.** On a dense render copy (`remesh` at about 1 cm, sharp
    edges kept hard):
    - **`streak_sources.vfl`** finds where streaks start, with the damaged piece and its
      `cut`/`island` prims in input 0, the pre-bevel piece in input 1 and the mask carrier in
      input 2:
      - top edges without a drip, in clustered runs, with 20–30 % of the sources dominant;
      - both ends of every top edge;
      - the lower lip of every chip over about 1 cm on a vertical face.

      Each source's length is k·√(catchment). Set `drip` 1 where the edge has a drip groove.
    - **`streak_mask.vfl`** draws them down each face as `f@streak`. A streak is full
      strength at the source and fans out at the source's angle, fading as exp(−3t) and
      meandering further down. Top edges with no drip also get a dark band 5–15 cm deep.
      Remap the mask with smoothstep(0, 0.5) before darkening, or it reads too faint.
    - **`micro_fields.vfl`** writes three primvars for the shader or Copernicus:
      - `micro_env`, the grain amplitude: floor + cluster²;
      - `micro_pd`, pore density, highest at the tops of pour lifts, along form joints and in
        clusters;
      - `micro_w`, worn or filled character.

      Multiply the micro noise by them. *Check:* an unlit, straight-on render of the micro
      layer, measured in 20 cm windows: a coefficient of variation of window variance of
      0.6 or more, a 90th/10th percentile spread of local std of 3–6, kurtosis 5–20. The test
      went from 0.03 to 1.1, from 1.2 to 3.5, and from 2.8 to 7.6.

    Fields on the low-poly game mesh smear; for an engine, rasterise them to UV (step 11).
11. **Correlated layers.** Promote `damage_hot`, `damage_halo` and the layer amounts to
   primvars for the shader, or rasterise them to UV with Copernicus (`rasterizesetup` `space`
   uv, then `rasterizegeo`, geometry in input 1). The shader reads them for edge wear, grime in
   and around the chips, a streak below strong hotspots, and rust below the largest break.
   Keep grime breakup large and soft on big flat faces, or it reads as blotches.
12. **Variation and LODs.** Expose `seed` on the HDA and drive every random source from it plus
   the instance `id`. For LODs, regenerate with a size cutoff (drop chips under a threshold)
   rather than reducing a dense mesh, and keep silhouette breaks to the last LOD that shows
   them.

## Techniques by damage type

See [references/causes.md](references/causes.md) for why and where edges break (fracture
mechanics, what photographs show, exposure weights, use and industrial strike zones), and
See [references/techniques.md](references/techniques.md) for the verified node and parm names,
measured costs and failure modes of each:

| Damage | Technique |
|---|---|
| Chipped edges and corners | Edge-band chip cutters + boolean subtract; SDF edge erosion for soft wear |
| Spalling concrete | Masked SDF erosion with Worley F2−F1 (flat-floored flakes), or flat noisy disc cutters |
| Cracks | Swept V-profile cutter along a crack curve (predictable cost); fine cracks in the normal map |
| Missing chunks, broken bricks and tiles | Fracture, choose pieces by mask, subtract them from the reference; bricks as separate pieces |
| Dents in panels | Smooth radial displacement along −N on a subdivided panel, edges pinned |
| Bent railings | `bend` or `lattice` on the curve before sweeping |
| Worn steps | SDF erosion masked by distance to the nosing times a walking-lane falloff |
| Weathered stone edges | `vdbreshapesdf` open (in voxels) or `vdbsmoothsdf` mean curvature |
| Exposed rebar | Curves inside a removed chunk, swept, clipped, ends bent (pattern, not verified) |

## Traps

- **Cutters pushed in along the edge bisector miss the arris.** Pushed or flattened along the
  bisector, a cutter reaches both faces but not the edge, leaving two divots flanking an intact
  arris: one impact never does that. Centre cutters on the edge line. `damage_measure.vfl`'s
  `flank_runs` finds the pattern.
- **Smooth cutters read as scoops.** Low-frequency displacement on a big cutter gives a soft
  rounded hollow. Broken concrete is angular and grainy: raise the fine noise, add a few
  clip planes, and give the cut faces exposed aggregate.
- **Cap the shell's length, not only its depth.** A depth cap alone let 45–50 cm shells reach
  1:6. Cap the final length after stretching.
- **Count cut islands as edge damage by distance too.** On round bevels the normal angle misses
  some edge breaks. An island that comes within about 1.2 cm of an edge line is edge damage.
- **A file named `dbg.py` next to a hython script shadows Houdini's `dbg` module.** Karma's
  MaterialX translator then fails (`theTranslators not defined`), the render writes nothing, and
  an old PNG stays in place.
- **Even spacing reads as CG.** Chips spread evenly along every convex edge, even with a
  height bias, came out only 1.6–2.5× denser in the contact zone than elsewhere; the
  clustered version gave 7.7–17×. Even spacing and an identical bevel highlight on every
  edge are the most common critique of procedural wear.
- **`polybevel` offset scale is per point.** There is no per-edge attribute, so a long edge
  needs points along it before its width can vary.
- **A varying bevel leaves non-planar n-gons.** Boolean then left 3–9 open edges on half the
  seeds. `divide` before the Boolean fixed every seed; `polydoctor` afterwards made it worse.
- **The seam margin must include the cutter's reach.** A stretched break centred outside the
  margin still crosses it. Both chip scripts now test the margin plus the cutter's radius and
  stretch.
- **Chamfers double the convex edges.** A chamfered or bevelled box has two convex edges
  where the raw box had one, and a tall wall qualifies along its whole height. In the danchi
  test, a 30 m end wall with a 4 cm chamfer gave 2,681 chips and 143k triangles. Find chip
  points on the pre-bevel shape and subtract them from the bevelled one, and cap their height
  to the contact zone on tall unique walls: 214 chips, 13k triangles.
- **Damage too small to see is wasted triangles.** Size the large breaks to at least about
  8 px at the judging distance, and check them in that view, not in a close crop. At 35 mm
  and 1600 px wide, one pixel is about 6 mm at 10 m and 3 cm at 45 m.
- **Damage leaks into LOD1.** Branch damage off after the LOD split, and build lower LODs
  from undamaged sources. Re-import the export to check.
- **Packed cutters are ignored.** Boolean with packed primitives in input 2 returns input 1
  unchanged with no error. Copy to Points `pack` = 0, or Unpack first.
- **`vdbreshapesdf` amount is `voxeloffset`, in voxels.** With `useworldspaceunits` on, the
  default 1.0 means one metre: erode and open return an empty mesh. `radius` and `iterations`
  do not set the amount.
- **`measure` curvature from a script keeps `attribname` = `area`.** Set it. Mean curvature is
  positive on convex edges, negative on concave, and meaningless on an unbevelled coarse box:
  bevel and remesh first.
- **`wnoise` needs an int variable** for its seed argument, not a literal.
- **Edge-angle groups do not tell convex from concave.** Use the half-edge test in
  `convex_edges.vfl`.
- **`polyreduce` `finalcount` counts polygons**, not triangles; report triangles after `divide`.
- **The VDB route re-meshes the seams.** For tiling pieces keep the ends out of the VDB, or
  accept that only the profile, not the topology, matches the neighbour.

## With HocusPocus

- Build each damage stage in one `edit` call. Load the VEX with
  `{"op": "set", "path": ".../snippet", "value_file": "<skill>/scripts/chip_points.vfl"}` and
  add the documented spare parms with the `node` op's `spare_parms`.
- Read validation numbers with `inspect {what: "geo", target: ".../validate"}`. The detail
  attributes are in the result.
- Look at the piece alone with `look {target: ".../damaged", quality: "draft"}`, and at final
  quality from three angles. Look at a row of six instances with different seeds to check
  variation.
- Measure triangles per part with `inspect {what: "geo", target, group_by: "name"}`.
