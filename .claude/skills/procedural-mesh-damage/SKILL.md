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

## Principles

1. **Damage follows cause.** Chips concentrate on convex edges and corners, more near the
   ground and at contact heights (0.3–1.2 m), on corners people and vehicles pass, and on top
   edges exposed to weather. Thin parts break first. Sheltered and concave areas stay clean.
2. **A hierarchy, not an even sprinkle.** Per piece: 1–3 large breaks, 5–15 medium chips, many
   small nicks, with clean rest areas between clusters. Bias sizes with a power curve: many
   small, few large.
3. **Silhouette in geometry, the rest in the bake.** A break larger than a few centimetres at
   play distance, or one that changes the outline, is real geometry. Smaller nicks, pitting and
   fine cracks go to a normal map baked from a damaged high-poly copy, or to edge decals.
4. **Modular pieces stay tileable.** No damage within a margin of a face that meets a
   neighbour, unless the damage is generated once and mirrored onto both sides. Check that the
   seam profile is unchanged.
5. **Every instance different.** Damage is seeded per instance, or chosen from a few baked
   variants, so repeated pieces never show identical chips.
6. **Validate numbers, not pictures.** The worst failures here are silent: a boolean with
   packed cutters returns the input unchanged, and a world-space SDF erode can delete the
   mesh. Check counts after every damage stage.

## Workflow

Work on one piece at a time, at final metrics, after its clean form is done and approved. Each
step ends with a check.

1. **Clean base.** A closed, manifold piece with consistent winding (`polydoctor` or `clean`),
   bevelled where edges catch light (`polybevel`, `filletshape` chamfer or round), and UV- or
   trim-mapped. Keep this node as the **reference** for UV transfer and validation.
   *Check:* `damage_validate.vfl` on it reports 0 open and 0 non-manifold edges.
2. **Masks.** Compute 0–1 point attributes and multiply them into `damage_mask`:
   - convex edges and corners: `convex_edges.vfl`, then distance to them;
   - height: more near the ground;
   - contact band and passage proximity;
   - exposure: `maskbyfeature` direction or AO;
   - thinness: `measurethickness`;
   - seam exclusion.

   Blur with `attribblur` (2–5 iterations). *Check:* show the mask as `Cd` with
   `look` and read its range with `inspect geo stats`.
3. **Large breaks.** Missing chunks at corners: fracture the piece (`voronoifracture`,
   `rbdmaterialfracture` with `materialtype` concrete), choose the pieces where the mask
   peaks, and boolean-subtract **only those pieces from the reference**. Never delete pieces
   and fuse the rest: shared interior walls become thousands of non-manifold edges.
4. **Medium chips.** `chip_points.vfl` scatters chips along convex edges with the size and
   density hierarchy and seam exclusion. Copy noisy cutter shapes onto them with Copy to Points,
   **`pack` off**, then `boolean` subtract (`booleanop` subtract, `usebinsidea` on to group the
   cut faces). Use angular cutters (a divided box plus noise) for concrete and painted metal,
   rounder Worley spheres for stone. Cutter resolution sets the triangle count. Run
   `chip_points.vfl` on the pre-bevel shape, since a chamfer doubles the convex edges, and
   use `damage_mask` to cap tall walls to the contact zone. *Check:* the chip count and
   the triangles added, against the piece's budget.
5. **Small nicks.** For the bake source only, or a piece that can afford it: SDF erosion along
   the edges with `edge_erosion.vfl` (VDB from Polygons, then a Volume Wrangle, then Convert VDB
   at adaptivity 0.1–0.3). Otherwise leave them to the normal map.
6. **Validate.** `damage_validate.vfl` with the reference in input 1. Everything below must
   hold:
   - `unchanged` is 0;
   - `open_edges` and `nonmanifold_edges` are 0;
   - `seam_changed` is 0 for tiling pieces;
   - `zero_uv_prims` is 0 after step 7;
   - triangles are within budget;
   - the node has no errors.
7. **Fix UVs and normals.** A boolean leaves cut faces at uv (0,0); the VDB route drops every
   attribute. Transfer vertex `uv` from the reference with `attribtransfer` onto the cut-face
   group (keeps trim mapping), or flatten those faces with `uvflatten` and lay them out. Keep the
   cut-face group as a material or vertex-colour channel for "broken interior" texturing.
   Recompute normals with a cusp angle (`normal`, `cuspangle`).
8. **Budget and bake.** `polyreduce` (`hardfeatureedges`, `silhouetteweight`,
   `vattribseamweight` to keep UV seams), triangulate with `divide`, count triangles. Bake
   small damage from the dense copy into the game mesh's normal and AO maps (see the
   `procedural-materials` skill).
9. **Variation and LODs.** Expose `seed` on the HDA and drive every random source from it plus
   the instance `id`. For LODs, regenerate with a size cutoff (drop chips under a threshold)
   rather than reducing a dense mesh, and keep silhouette breaks to the last LOD that shows
   them.

## Techniques by damage type

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
