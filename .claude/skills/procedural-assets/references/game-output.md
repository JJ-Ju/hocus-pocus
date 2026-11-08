# Game output: LODs, collision, lightmap UVs, export

What a generator hands to an engine, and the naming engines expect. Sources are at the end.

## Deliver instances, not one merged mesh

- Keep kit pieces as instances (packed primitives in Houdini; instanced static meshes or
  Nanite instances in Unreal). Merge only for distant proxies.
- Insomniac streamed Manhattan in 128 m tiles and generated impostors in Houdini; City Sample
  builds every building from instanced kit pieces under Nanite.
- Under Nanite, geometry buried well inside a surface is culled cheaply, but nearly coplanar
  shells near the surface cost overdraw and z-fight. Overlap generously or not at all.

## LODs

- Per piece: Labs LOD Create (per-LOD triangle percentage, UV cleanup, FBX export) or
  PolyReduce (UV-seam and boundary weights). Re-apply weighted normals on every LOD.
- Per building at distance: drop interiors and small greebles first, then flatten facades to
  a few quads per bay, then a shell or impostor. Match albedo and value across LODs so the
  switch does not pop: compare a render of each LOD from the same camera and light.
- Impostors: Labs Impostor Baker bakes base-colour and normal atlases in full-sphere,
  upper-hemisphere or turntable modes.
- Unreal through Houdini Engine reads LODs from primitive groups `lod0`, `lod1`, … (sorted
  alphabetically); LOD geometry must not be packed, and `lodX_screensize` sets switch
  distances.

No studio publishes per-building budgets. Measure triangles per role and per LOD, and keep a
budget table in the asset's README.

## Collision

- Convex hulls per volume: Convex Decomposition SOP (Max Concavity, per piece), or simple
  boxes per tier extruded from the plan. Keep masts, antennas and thin aerials out of the
  main hull: give them their own slim hull or none.
- FBX naming for Unreal: `UCX_<mesh>_00`, `UCX_<mesh>_01` (convex), `UBX_` (box), `USP_`
  (sphere), where `<mesh>` is the exact render mesh name.
- Houdini Engine group names: `collision_geo_ucx`, `collision_geo_simple_box`,
  `collision_geo` (complex; not used for physics), `rendered_*` variants; number several with
  `_1`, `_2`.
- Embark generates collision and occluders automatically from per-feature planar proxies;
  arbitrary building shapes need dedicated collision meshes.

## UVs

- Texture UVs: trim-sheet rows for strips, world-scale tiling for large surfaces
  (see `surfacing.md`).
- Lightmap UVs: a second set (`uv2` in Houdini Engine, UV channel 1 in FBX), non-overlapping
  and packed per mesh; set `unreal_lightmap_resolution` if exporting through Houdini Engine.
  For background buildings where unwrapping fails, triplanar shading is an accepted fallback.

## Engine attributes (Houdini Engine)

| Attribute | Use |
|---|---|
| `unreal_instance` | Reference an existing asset per point |
| `unreal_material`, `unreal_materialN` | Material per primitive or per instance slot |
| `unreal_split_attr` | One instancer per distinct value |
| `unreal_nanite_enabled` | Nanite on the output mesh |
| `unreal_uproperty_*` | Set UProperties |
| `unity_instance`, `unity_material` | Unity equivalents, paths relative to `Assets/` |

Instances need their own geometry part; replace-geometry instancing was removed in
Houdini 21.

## Export routes

- FBX per LOD, with collision meshes named for the render mesh.
- USD with a LOD variant set and material bindings, collision as guide geometry.
- Point clouds plus engine-side rules (City Sample).
- Live Houdini Engine assets for artists working in the editor (Ubisoft ran their HDAs in the
  in-house editor so every artist could iterate).

Always prove an export: re-import it into a fresh scene and render it with only its own
textures, and check triangle counts, UV sets, material slots and collision names.

## Validate every export (`asset_check`)

Studios validate on save and in CI (Unreal's Data Validation commandlet, Allar's style rules,
Pyblish validators). Run a validator after every export, over the preset strip and at least 4 seeds,
reading the asset's `spec.json` (research `docs/redesign/research/pro-asset-pipeline.md` §4 #1-2).
It fails when:
- texel density measured from the UVs (√(UV area × texture pixels ÷ world area), with the world-UV
  tile sizes the shader uses) is under 0.5× its class target anywhere, or under 90 % of the area
  within ±25 % of it;
- material slots or triangles exceed the spec at the heaviest preset (danchi's LOD1 reached 99,946
  of a 100k cap at age 60 and upkeep 0.1, because its decals grow with weathering);
- a Nanite mesh has 2 or more vertices per triangle (warn above 1);
- a texture side is not a power of two (streamed) or not a multiple of 4 (block compression);
- UV1 or UV2 overlap, or have under 2 texels of padding at the lowest lightmap resolution, when the
  spec asks for lightmaps;
- either engine's collision names are missing, or mesh and slot names changed without a version bump;
- the bounding box differs from the contract by more than 1 cm.

## Two builds from one plan

| | Unreal 5 with Nanite | Godot 4 |
|---|---|---|
| Kit pieces | Nanite meshes, no LOD chain | authored LOD1 and LOD2 on visibility ranges (fade off, 2-5 m margin), Generate LODs off where edges must meet |
| Glass, decals, translucent | separate non-Nanite meshes | Decal nodes for hero marks (Forward+ and Mobile only), mesh decals otherwise |
| Distance | World Partition HLOD (instancing near, simplified mesh far) | Visibility Parent pointing at a merged building HLOD |
| Instances | instanced static meshes, per-instance custom data | one MultiMesh per piece type per facade (Mobile, Compatibility) or MeshInstance3D (Forward+ auto-instances) |
| Collision, occlusion | `UCX_` hulls | `-colonly` primitives per slab tier and balcony line; `-occonly` closed boxes inset 0.3 m behind each facade |
| Lightmaps | off under Lumen | UV2 per piece if the renderer needs LightmapGI (Mobile, Compatibility) |

Name the Godot renderer in the brief: Compatibility has no Decal nodes, Mobile has only LightmapGI,
and only Forward+ auto-instances.

## Sources

- Houdini Engine for Unreal, instancing: https://www.sidefx.com/docs/houdini/unreal/instancing.html
- Houdini Engine for Unreal, meshes and LODs: https://www.sidefx.com/docs/houdini/unreal/meshes.html
- Houdini Engine for Unreal, collisions: https://sidefx.com/docs/houdini/unreal/meshes/collisions.html
- Houdini Engine for Unity, attributes: https://www.sidefx.com/docs/unity20.5/_attributes.html
- Unreal FBX static mesh and collision naming: https://docs.unrealengine.com/4.27/WorkingWithContent/Importing/FBX/StaticMeshes
- Labs LOD Create: https://www.sidefx.com/docs/houdini/nodes/sop/labs--lod_create-2.0.html
- PolyReduce: https://www.sidefx.com/docs/houdini/nodes/sop/polyreduce.html
- Labs Impostor Baker: https://www.sidefx.com/docs/houdini/nodes/sop/labs--impostor_baker-1.1.html
- Convex Decomposition: https://www.sidefx.com/docs/houdini/nodes/sop/convexdecomposition.html
- World Partition HLOD: https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine
- Nanite content: https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-naniteenabled-content
- Spider-Man streaming tiles: https://blog.playstation.com/?p=204132
- Embark, THE FINALS: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
