# Damage techniques: verified names, costs, failure modes

Measured in Houdini 22.0.466 on a 2 × 1 × 0.5 test block whose x ends are tiling seams.
Times are wall clock after a forced cook. SideFX Labs is not installed on the test machine
(`labs::edge_damage` and the Labs rock tools are missing); everything here uses core nodes.

## Nodes and parms

| Purpose | Node | Key parms |
|---|---|---|
| Boolean | `boolean` (2.0) | `booleanop` (`union`, `intersect`, `subtract`, `shatter`, `seam`), `subtractchoices` (`aminusb`), `asurface`/`bsurface` (`solid`/`surface`), `resolvea`/`resolveb` (default on), `detriangulate`, `collapsetinyedges`, `usebinsidea`/`binsidea` (cut faces group), `useainsideb`/`ainsideb` |
| SDF build | `vdbfrompolygons` | `voxelsize`, `exteriorbandvoxels`, `interiorbandvoxels` (≥10 for erosion), `fillinterior` |
| SDF reshape | `vdbreshapesdf` | `operation` (`dilate`, `erode`, `open`, `close`), `voxeloffset` (the amount, in voxels), `useworldspaceunits` |
| SDF smooth | `vdbsmoothsdf` | `operation` (`meanvalue`, `gaussian`, `medianvalue`, `meancurvature`, `laplacianflow`), `iterations`, `radius` |
| SDF noise | `volumenoisesdf` | `amplitude`, `elementsize`, `basis`, `displacement` |
| SDF to mesh | `convertvdb` | `conversion` (`poly`), `adaptivity`, `isovalue`, `computenormals` |
| Fracture | `rbdmaterialfracture` (4.0) | `materialtype` (`concrete`, `glass`, `wood`, `metal`, `custom`), `concrete_enablechipping`, `concrete_chippingdepth`, `concrete_cornerratio`, `concrete_edgedetail`, `concrete_edgenoiseheight`, `concrete_detailsize`, `concrete_fracturelevel`, `randomseed`; groups `inside`, `outside`, `concrete_chips` |
| Other fracture | `voronoifracture` (3.0), `booleanfracture`, `rbdinteriordetail` (`detailsize`, `noiseamp`), `edgefracture`, `vdbfracture` | |
| Bevel | `polybevel` (3.0) | `offset`, `filletshape` (`chamfer`, `round`, `solid`, `crease`), `divisions`, `ignoreflatedges`, `grouptype` `edges`; varying width: `useoffsetscale` (`unscaled`, `byattrib`) with `pointscaleattr` (default `pscale`), per point only |
| Hull cutters | `shrinkwrap` (2.0) | convex hull of scattered points: faceted, broken-concrete cutters |
| Masks to UV | `rasterizesetup` (`space` uv) → `rasterizegeo` | geometry in input 1 (input 0 is `camera_ref`); multiparm `attributes`, `name#`, `outtype#`; COP `sopimport` `usesoppath`, `soppath` |
| Masks | `measure` (2.0) | `measure` = `curvature`, `curvaturetype` (`mean`, `gaussian`, `principal`, `curvedness`), `attribname` (set it) |
| | `maskbyfeature` | direction and AO masks (`enableao`, `aosamples`); writes point `mask` |
| | `distancefromgeometry` | `distmetric`, `rad`, `outattrib`, `outmask` |
| | `vdbocclusionmask`, `measurethickness`, `attribblur` (`iterations`), `groupexpand` | |
| Displace | `attribnoise` (2.0) | `attribs` = P, `amplitude`, `elementsize`, `basis` (`worleyFA`…) |
| | `mountain` (2.0) | `height`, `elementsize`, `centernoise` |
| | `peak` (`dist`), `smooth` (2.0, `strength`), `bend`, `lattice`, `sculpt` | |
| Cleanup and LOD | `polyreduce` (2.0) | `target`, `percentage`, `finalcount` (polygons), `hardfeatureedges`, `silhouetteweight`, `boundaryweight`, `vattribseamweight`, `preservequads` |
| | `remesh` (2.0: `targetsize`), `polydoctor`, `clean`, `fuse` (2.0), `divide`, `normal` (`cuspangle`) | |
| UVs | `attribtransfer` | `vertexattribs`, `vertexattriblist`, `dstgroups`, `primitiveattribs`/`pointattribs` (turn off) |
| | `uvflatten` (3.0), `uvlayout` (3.0), `uvunwrap`, `uvproject`, `attribtransferbyuv` | |

## Measured results

**Edge-band chip cutters, boolean subtract** (`scripts/chip_points.vfl`).
- Bevel 0.02 chamfer, `uvunwrap`, chips every 0.08 m on convex edges, keep 0.9 at the bottom
  and 0.35 at the top, seam margin 0.06, sizes `fit01(pow(r, 4), 0.02, 0.12)`.
- 55–58 chips; 0.05–0.35 s.
- Triangles by cutter: sphere 6×8 → about 2,150–2,600; 8×10 → 3,038; 24×32 → 17,702; divided
  box 3³ → 1,556 (more angular). Seeds 1–3 gave 1,418–1,672 triangles with different layouts.
- `polyreduce` 50 % → 1,118 triangles, still closed.
- Seams: with the margin, each end face keeps its original points (`seam_changed` 0); with no
  margin, 102 points landed on the seam planes.
- Cut faces: uv (0,0) on about 95 % of output prims until `attribtransfer` of vertex `uv` from
  the reference onto the `binsidea` group (0.007 s, 0 unmapped after).

**SDF edge erosion** (`scripts/edge_erosion.vfl`).
- Triangles (adaptivity 0 / 0.1 / 0.3): voxel 0.02 → 35,752 / 4,384 / 2,520; voxel 0.01 →
  143,396 / 14,290 / 7,314. Under 0.2 s each, always closed.
- Output has only `P`; transfer `uv`, `N`, `Cd` back. Seams are re-meshed.

**`vdbreshapesdf`.** `erode` 5 voxels shrank the block 0.1 per side at voxel 0.02. `open`
5–10 rounds convex corners and keeps the size: the weathered-stone operator. With world units
on and the default amount, erode and open returned nothing and close took 7.6 s.

**Concrete fracture for missing chunks.** `rbdmaterialfracture` concrete: 25 pieces in 1.9 s;
with chipping and edge detail, 52 pieces and 20,650 triangles. Blasting two pieces and fusing
the rest gave 8,763 non-manifold edges; subtracting the two pieces from the reference gave a
closed 1,774-triangle piece. `voronoifracture` with 30 cells: 0.02 s.

**Curvature sign.** On a notched, round-bevelled, remeshed box: 0 on flats, +0.45 on convex
edges, −0.31 in the notch.

**Brick wear by intersecting with a noisy copy.** `remesh` → `smooth` → `mountain`
(`centernoise` off) → `boolean` intersect with the original only cut with `smooth`
`strength` 100–200 and a small inward `peak`; at 20–50 the copy enclosed the brick and nothing
was cut. Check that `binsidea` is not empty.

**Dents.** Radial bowls along −N on a 60 × 60 grid: 0.02 s. The panel needs enough rows.

**Clustered damage (`cluster_mask.vfl`, `chip_points_clustered.vfl`).** Two pieces: a 2 × 1 ×
0.3 m block whose x ends are seams, and a unique 2.4 × 3 × 2 m wall corner. Edge samples every
1 cm; "hot" means `damage_hot` ≥ 0.3; sweep figures are over seeds 1–10.

| | Block | Wall corner |
|---|---|---|
| Edge length holding 80 % of `damage_hot` | 23 % (17–27 %) | 18 % (14–22 %) |
| Even chips: count; per m in / out of hotspots | 58; 7.8 / 3.1 | 239; 11.5 / 7.1 |
| Clustered chips: count; per m in / out | 48; 11.9 / 0.71 (17×), 85 % inside | 130; 14.1 / 1.8 (7.7×), 67 % inside |
| Clustered chip radius in / out | 3.9 / 2.2 cm | 4.4 / 1.9 cm |
| Triangles added: even / clustered / + varied bevel / SDF erosion | +2,160 / +1,254 / +1,526 / +10,810 | +9,298 / +3,606 / +5,312 / +32,578 |

- **Validation:** 0 open and 0 non-manifold edges on every seed for the even, clustered and
  varied-bevel routes, once `divide` precedes the Boolean on the varied bevel. Seams were
  unchanged except on the SDF route.
- **Cost:** the varied-bevel base itself adds 1,152 triangles on the block and 2,064 on the
  wall, over the constant chamfer.
- **Timings:** mask 8–39 ms; chip points 4–18 ms; Boolean 30–100 ms; SDF route 0.15–0.63 s;
  rasterising 5 layers to UV at 1K, 0.14–1.1 s.

## Recipes

- **Chipped edges:** clustered chip cutters for hard materials (a cluster mask, then clustered
  chip points), a varied bevel and shader edge wear from the same mask; erosion for soft wear
  on a bake source.
  Push cutter centres into the piece (`inset`) so chips bite instead of grazing.
- **Spalling:** erosion with the mask from a face-region or painted attribute instead of edge
  distance; Worley F2−F1 gives flat-floored flakes. Or subtract large flat noisy discs parallel
  to the face.
- **Cracks:** a thin V-profile swept along a crack curve and subtracted gives a predictable
  cost. `rbdmaterialfracture` with edge detail gives realistic crack networks; keep only the
  seams. Cracks finer than about 1 cm go in the normal map.
- **Missing chunks:** choose fracture pieces near the corner by mask; subtract only them.
- **Bricks:** build bricks as separate pieces; remove those fully inside a damage shape
  (`groupexpand`), rotate or offset the edge bricks, keep corner bricks. Detail a few brick
  variants and copy them.
- **Dents:** a few large and more small radial falloffs along −N; pin edges and fixings;
  recompute normals.
- **Bent railings:** bend the curve, then sweep; UVs and topology survive.
- **Worn steps:** erosion masked by distance to the front top edge times a lane falloff across
  the width, plus a light `open`.
- **Weathered stone:** `vdbreshapesdf` open (3–10 voxels) or `vdbsmoothsdf` mean curvature,
  `convertvdb` adaptivity 0.1–0.3, `polyreduce`.

## Sources

- SideFX: Labs Edge Damage https://www.sidefx.com/docs/houdini/nodes/sop/labs--edge_damage-2.0.html · RBD Material Fracture https://www.sidefx.com/docs/houdini/nodes/sop/rbdmaterialfracture.html · Boolean https://www.sidefx.com/docs/houdini/nodes/sop/boolean.html · VDB Reshape SDF https://www.sidefx.com/docs/houdini/nodes/sop/vdbreshapesdf.html · Measure https://www.sidefx.com/docs/houdini/nodes/sop/measure.html · Mask by Feature https://www.sidefx.com/docs/houdini/nodes/sop/maskbyfeature.html
- Tutorials: Houdini Edge Wear https://www.sidefx.com/tutorials/houdini-edge-wear/ · Auto Edge Damage https://www.sidefx.com/tutorials/auto-edge-damage/
- 80.lv: edge damage tool https://80.lv/articles/how-to-create-houdini-tool-to-automate-procedural-edge-damage · concrete damage tool https://80.lv/articles/setting-up-a-procedural-concrete-damage-tool-in-houdini · ruined wall generator https://80.lv/articles/creating-a-procedural-wall-generator-for-unreal-in-houdini/ · Wall Breaker HDA https://80.lv/articles/making-a-wall-braker-hda-in-houdini/ · mid-poly workflow https://80.lv/articles/creating-assets-within-the-mid-poly-workflow-in-ue5/
