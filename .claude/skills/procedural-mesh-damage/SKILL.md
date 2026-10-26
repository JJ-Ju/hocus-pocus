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
2. **Cluster, don't sprinkle (80/20).** About 80 % of the notable damage sits on 20–30 % of
   the edge length, in a few hotspots chosen by cause. Each hotspot has one dominant break,
   satellite chips around it, and a halo of worn, rounder arris. Between hotspots the edges
   stay crisp with sparse small nicks, about one per metre: aged, never pristine. Hotspot
   sizes follow a power law, one big and many small. Across a kit, a share of instances
   (30–50 %) gets background wear only.
3. **One mask drives every layer.** The same hotspots set chip density and size, bevel
   width, edge wear in the shader, grime, streaks and rust, so a cause shows all its effects
   in one place. Layers from independent noises read as procedural.
4. **Silhouette in geometry, the rest in the bake.** A break larger than a few centimetres at
   play distance, or one that changes the outline, is real geometry. Smaller nicks, pitting and
   fine cracks go to a normal map baked from a damaged high-poly copy, or to edge decals.
5. **Modular pieces stay tileable.** No damage within a margin of a face that meets a
   neighbour, unless the damage is generated once and mirrored onto both sides. Check that the
   seam profile is unchanged.
6. **Every instance different.** Damage is seeded per instance, or chosen from a few baked
   variants, so repeated pieces never show identical chips.
7. **Validate numbers, not pictures.** The worst failures here are silent: a boolean with
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
4. **Medium chips.** Run `chip_points_clustered.vfl` on the low-poly pre-bevel piece (a
   chamfer doubles the convex edges), with the mask carrier in input 1.
   - The mask sets each chip's keep probability, size, stretch along the edge and bite depth.
   - Every hotspot of strength 0.6 or more also gets one anchor break at its nearest edge;
     the chips around it become its satellites.
   - Seam exclusion counts each cutter's reach.

   Copy cutters onto the points with Copy to Points, **`pack` off**, with the `variant`
   attribute choosing among 3–4 cutter shapes. Then `boolean` subtract (`booleanop`
   subtract, `usebinsidea` on to group the cut faces).
   - **Concrete:** the convex hull (`shrinkwrap::2.0`) of about 16 random points on a
     flattened ellipsoid. The flat facets read as broken concrete. Break up the anchors with
     noise or a second, smaller cut, or large breaks read as carved pyramids.
   - **Stone:** rounder Worley spheres.

   Cutter resolution sets the triangle count. `chip_points.vfl` is the even-spread version,
   for background nicks only.

   *Check:* chips per metre inside the hotspots are at least 5× those outside (the test gave
   7.7–17×), and the triangles added fit the piece's budget.
5. **Varying edge width.** Keep the kit's constant chamfer as the default and widen it around
   hotspots:
   - set a point attribute `bevel_scale` = lerp(0.1, 1, `damage_halo`^1.2), reset to the
     kit's chamfer ratio at seams;
   - `polybevel::3.0` with `useoffsetscale` `byattrib` (`pointscaleattr`);
   - **`divide`, then the Boolean.**

   Edges stay crisp in clean stretches and worn round around breaks, for about 20 % more
   triangles. Add edge wear in the shader from `damage_halo` (lighter, rougher, a noisy band
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
10. **Correlated layers.** Promote `damage_hot`, `damage_halo` and the layer amounts to
   primvars for the shader, or rasterise them to UV with Copernicus (`rasterizesetup` `space`
   uv, then `rasterizegeo`, geometry in input 1). The shader reads them for edge wear, grime in
   and around the chips, a streak below strong hotspots, and rust below the largest break.
   Keep grime breakup large and soft on big flat faces, or it reads as blotches.
11. **Variation and LODs.** Expose `seed` on the HDA and drive every random source from it plus
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
