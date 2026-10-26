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
