# neo_tower: a procedural anime skyscraper (HDA `hp::neo_tower::1.0`)

`neo_tower.hdalc` is a SOP digital asset that generates futuristic skyscrapers in the look
of 1980s and 1990s anime cities:

- **Tokyo-3** (*Evangelion*): setback tiers, armoured panel cladding with seams, visor
  hoods over slit windows, closed armour shutters, heavy armour bands with hazard
  stripes, vertical armour pilasters, and an armoured base collar (the "retract sleeve").
- **Neo-Tokyo** (*Akira*): dense slabs with ribbon windows, louvred spandrels, AC units,
  vertical sign blades and rooftop billboard frames.

Interiors are finished but unfurnished. Each floor gets a slab, a suspended ceiling with
light panels, a core (lift shafts with doors, a dog-leg stair, a lift lobby and a riser
room), corridors, and partitions with door openings, architraves, glazed sidelights and
skirting.

A second asset, `neo_tower_export.hdalc` (`hp::neo_tower_export::1.0`, phase P2), turns the
tower into a game asset: hero bevels, trim-sheet and tiling UVs, procedural PBR textures,
MaterialX materials, LOD0 to LOD2, UCX collision, and FBX and USD export. See the
Game export section below.

It was built in phase P1 of the HocusPocus 2.1 dogfood (plan-2.1 §2) entirely through the
HocusPocus MCP tools. The log is in `docs/redesign/review/26-neo-tower-dogfood.md` and
the images are in `docs/redesign/evidence/neo-tower/`.

**Licence note.** It was built on a Houdini **Indie** licence, so the asset is
`neo_tower.hdalc` and the build scene is `work/neo_tower_p1.hiplc`. A Commercial
session can load an `.hdalc`, but it turns that session into a limited-commercial
session.

## Loading it

```python
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower.hdalc")
geo = hou.node("/obj").createNode("geo", "tower")
tower = geo.createNode("hp::neo_tower::1.0")
```

Through HocusPocus, `hda {action: "install", library_path: "<repo>/examples/neo_tower/neo_tower.hdalc"}`
then `node_create {parent: "/obj/tower", type: "hp::neo_tower::1.0"}` (2.1; P1 had no install
tool and used `houdini_python`).

The build scene `work/neo_tower_p1.hiplc` is not committed. It holds the asset instance
(`/obj/neo_tower_build/neo_tower`), a preview object, cameras (hero, close-up, roof,
interior, core, topology), a dusk light rig (`/obj/sun`, `/obj/sky`), a ground plane,
the topology helper `/obj/topo` and the Karma ROP `/out/karma_evidence`.

## Parameters

| Folder | Parm | Meaning |
|---|---|---|
| Massing | `footprint` | rect, chamfer, stepped (notched corners), round |
| | `width`, `depth` | lowest-tier footprint in metres (clamped so the core fits) |
| | `corner` | chamfer length or notch size |
| | `floors`, `floor_height` | floor count and floor-to-floor height (3.6 m default) |
| | `tiers`, `setback`, `tier_taper` | setback tiers, inset per tier, floor share of each tier relative to the one below |
| | `collar`, `collar_floors` | Tokyo-3 armoured base collar with entrance portals |
| Facade | `style` | armour (Tokyo-3), ribbon (Neo-Tokyo), grid (punched), mixed per tier |
| | `module_width` | target bay width; each edge is split into whole modules |
| | `window_ratio` | window size within the bay |
| | `greeble` | density of louvres, AC units and service pipes |
| | `band_every`, `hazard` | armour band interval (armour style) and hazard stripes |
| Crown | `crown` | antenna mast, helipad, spire, armour cap |
| | `crown_height`, `roof_hardware`, `signage` | crown size, density of roof plant, rooftop billboard frames |
| Interior | `interior` | on: full interiors; off: one cheap proxy shell per tier, and the interior branch is never cooked (it sits behind a Switch) |
| | `core_width`, `core_depth` | core rectangle (lifts, stair, lobby) |
| | `partition`, `room_width` | open plan, ring corridor with offices, or spine corridor with units |
| Seed | `seed`, `variation` | the seed always varies details; `variation` lets it jitter tier heights, setbacks, corner size and crown height |
| Output | `preview_colors` | writes a per-surface preview colour to prim `Cd`; turn it off for export |
| | `cutaway`, `cut_floor`, `cut_front` | presentation only: removes floors above `cut_floor`, that floor's ceiling and the front facade |

Disable-when rules: `corner` for rect and round, `collar_floors` without a collar,
`band_every` outside armour style, the Interior parms when interiors are off, and the
cut parms when `cutaway` is off.

## Geometry contract for P2 and P3

- **Units and frame.** Metres, Y up, the footprint centred on the origin, ground at y = 0.
  Floor strip `i` spans `y ∈ [i·H, (i+1)·H]`. Its slab is `[i·H, i·H + 0.3]`, so the
  finished floor level is `i·H + 0.3`. The ceiling underside is at `(i+1)·H − 0.5`, which
  gives 2.8 m clear at the default H of 3.6 m.
- **Primitives.** Every primitive is a polygon, mostly quads. Cylinders are n-gon prisms.
  Hazard stripes are clipped parallelograms. Stair flights are concave n-gon side
  profiles, so triangulate before export. Winding is Houdini's outward convention; the
  `qa_checks` node inside the asset verifies glass faces outward and decks face up.
  Vertex `N` comes from a Normal SOP with a 60° cusp.
- **Points are not fused.** Each box or piece has its own points. This is deliberate: it
  gives hard edges and independent pieces. Fuse per piece only if P2 needs welded meshes.
- **Two outputs.** Output 1 is the tower. Output 2 (added in P2) is the massing: one
  outline polygon per tier with `tier`, `style` (0 armour, 1 ribbon, 2 grid), `f0`, `nf`,
  `y0`, `y1`, `tw`, `td`, and the detail attribute `H`. The export asset uses it for the
  style-dependent materials, the LOD2 shell and the collision hulls.
- **No UVs on the tower.** `hp::neo_tower_export::1.0` writes them.
- **Glass is single-sided** (`facade_glass`, `int_glass`), so give it a two-sided material.

Primitive attributes:

| Attribute | Type | Meaning |
|---|---|---|
| `surface` | string | surface type, also a primitive group of the same name |
| `mat_id` | int | index of `surface` in the table below (stable order) |
| `part` | string | `facade`, `roof`, `crown`, `interior`, `proxy`; also groups `part_<name>` |
| `floor` | int | floor index. Facade and interior prims carry their floor (interior is derived from height). Roof and crown prims carry the top floor of their tier. Proxy prims carry the tier's first floor. |
| `tier` | int | setback tier, 0 at the bottom |
| `sign_slot` | int | −1 except on `sign_panel`: rooftop billboards are `tier·10 + slot`, facade sign blades are `100 + tier`; use it to assign sign textures |
| `Cd` | vector | preview colour only (`preview_colors`) |

`mat_id` order:

```
 0 facade_panel   1 facade_backer  2 facade_glass   3 mullion       4 sill
 5 louver         6 armour         7 column         8 plinth        9 hazard_yellow
10 hazard_black  11 trim          12 greeble       13 metal        14 pipe
15 light         16 sign_panel    17 sign_frame    18 canopy       19 door_frame
20 roof          21 parapet       22 coping        23 penthouse    24 tank
25 helipad       26 helipad_mark  27 slab          28 ceiling      29 int_wall
30 core          31 stair         32 lift_door     33 int_glass    34 skirting
35 int_proxy
```

Emissive candidates for P2: `light` (canopy downlights, ceiling panels, aircraft and
band beacons), `sign_panel`, `facade_glass` (night windows) and `int_glass`.

## Poly budget

Default settings (chamfered, armour, 36 floors, 3 tiers, interiors on, seed 1):

| Part | Polygons | Triangles |
|---|---|---|
| facade | 84,572 | 170,360 |
| roof | 1,095 | 2,374 |
| crown | 681 | 1,572 |
| interior | 63,344 | 133,024 |
| **total** | **149,692** | **307,330** |

With interiors off (seed 5) the asset is about 90k polygons, about 181k triangles: the
exterior plus 30 proxy faces. The default asset cooks in about 0.1 s once VEX is
compiled. These figures are LOD0 for a hero tower; P2 owns LOD1 and LOD2 and the
collision proxy.

## Inside the asset

- `massing` (detail): one outline polygon per tier. The tier's style, floor range and
  dimensions are prim attributes, and `crown_scale` is a detail attribute.
- `facade` (Run Over Numbers, one invocation per floor, parallel): corner columns,
  modules (backers, seamed panels, piers, glass, frames, mullions, transoms, sills,
  visors, shutters, louvres, AC units), armour bands, pilasters, the collar, entrance
  canopies, pipes and sign blades.
- `roof_crown` (detail): terrace decks (rings between tier outlines), parapets and
  coping, beacons, roof plant, billboards, the penthouse and the four crowns.
- For-each over tiers, building one floor template per tier:
  - `int_solids` (slab and ceiling), booleaned against `int_cutters` (lift and stair
    voids, core cut-out);
  - `int_walls` (core, stair flights, lift doors, partitions, trims, lights);
  - copied onto `int_floor_points`.
  - `interior_switch` picks either this branch or `int_proxy`.
- `finalize` (groups, `mat_id`, interior `floor`, `Cd`), then `cutaway`, `normals` and
  `OUT`. `qa_checks` sits off to the side; it reports winding checks and per-part
  polygon and triangle counts.

VEX helpers are repeated in each wrangle, because one snippet cannot include another
inside a self-contained HDA:

- `nt_box`: oriented box with per-face skip bits, so hidden faces are never built;
- `nt_prism`, `nt_cyl`, `nt_loft`;
- `nt_hazard`: clipped stripes;
- `nt_wall`: wall with door and window openings;
- `nt_flight`: stair flight.

## Known limits (P1)

- **Points are not welded.** Coincident opposite-facing internal faces remain where
  separate solids touch (core walls against slabs, the spine wall against stair sides).
  They are hidden, but a strict manifold check will flag them.
- **The upper tier's base is buried.** Its lowest 0.3 m of facade sits below the deck
  of the terrace beneath it (hidden, but wasted polygons).
- **Light panels can clip walls.** Ceiling light panels (single downward quads 1 cm
  below the ceiling) can cross a partition wall.
- **Round footprints** use the same segment count on every tier (so terrace rings can be
  bridged). Module width therefore shrinks a little on upper tiers.
- **Shapes cannot change between tiers.** Every tier uses the same footprint shape.

## Game export: `hp::neo_tower_export::1.0` (P2)

`neo_tower_export.hdalc` is a second SOP asset. Input 1 takes the tower (neo_tower output
1), input 2 the massing (neo_tower output 2).

```python
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower.hdalc")
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower_export.hdalc")
geo = hou.node("/obj").createNode("geo", "tower")
tower = geo.createNode("hp::neo_tower::1.0")
game = geo.createNode("hp::neo_tower_export::1.0")
game.setInput(0, tower, 0)
game.setInput(1, tower, 1)
game.parm("export_dir").set("$HIP/export")
game.parm("export_all").pressButton()
```

**Why a second asset.** The generator is a design tool that cooks in about 0.1 s. Game prep
is a pipeline step: it has five outputs, owns textures, materials and ROPs, and its lightmap
packing takes about 30 s. Keeping it separate leaves the generator fast to art-direct and
lets the export asset wrap any generator that honours the geometry contract above. Each
asset has one job, as with SideFX Labs' game tools.

The build scene is `work/neo_tower_p2.hiplc` (not committed). The asset instance is
`/obj/neo_tower_build/neo_tower_export`. The scene also holds `/obj/lod_lineup`,
`/obj/collision_view`, the `cam_lods` and `cam_bevel` cameras, and `/mat/M_checker` and
`/mat/M_collision_debug`. `work/neo_tower_p2_fbx_reimport.hiplc` is the FBX re-import check.

### Outputs

| Output | Content |
|---|---|
| 0 | preview, chosen by `preview` (LOD0, LOD1, LOD2, collision) |
| 1 | LOD0: the full tower, bevelled, with interiors |
| 2 | LOD1: no interiors, reduced greebles, opaque atlas windows, `uv2` |
| 3 | LOD2: the shell proxy with a far-facade atlas, the crown, `uv2` |
| 4 | collision: closed convex hulls named `UCX_<mesh>_NN` |

### Parameters

| Folder | Parm | Meaning |
|---|---|---|
| Output | `preview` | what output 0 shows |
| | `mesh_name` | FBX and USD mesh name (`SM_neo_tower`) |
| | `export_dir` | textures go to `<dir>/textures`; FBX and USD go to `<dir>` |
| | `write_textures`, `export_fbx`, `export_usd`, `export_all` | buttons |
| Edges | `bevel`, `bevel_width`, `bevel_angle` | hero bevel on or off, width (3 cm), minimum dihedral angle (30°) |
| | `hero_surfaces` | surfaces with every qualifying edge bevelled at full width |
| | `half_surfaces` | surfaces with only their front-face edges bevelled at half width |
| | `bevel_interior` | also bevel interiors (off) |
| UVs | `texel_density`, `tex_res` | 512 px/m on 2K textures, so one texture covers 4 m |
| | `uv_seed`, `lit_ratio` | atlas cell choice and the share of lit windows (0.55) |
| | `lightmap_uv` | `uv2` on LOD1 and LOD2 (UV Unwrap plus UV Layout) |
| LODs | `lod1_drop`, `lod1_min_area`, `lod1_min_width` | LOD1 reduction rules |
| | `lod2_module` | LOD2 quad width (3 m modules, two per quad) |
| Vertex Masks | `vertex_ao`, `ao_samples`, `ao_distance` | ray-traced vertex AO in `Cd.r` |
| Materials | `emission_scale`, `edge_wear`, `sign_font` | night emission strength, bevel edge wear, sign font (`YuGothB.ttc`) |

### Edges

Hero edges are real geometry: PolyBevel 3.0, one segment, with face-area-weighted normals
(cusp 50°). This is the mid-poly approach: chamfers catch the light and need no unique
bake. Hero surfaces (`column plinth coping parapet canopy penthouse`) get every edge
between faces of the same piece with a dihedral angle above 30°, at 3 cm. Fine surfaces
(`armour facade_panel trim`) get only the edges of their front faces, at 1.5 cm. Front
faces are those facing out of the nearest tier-outline edge. Corners then get a mitre
instead of a corner patch.

The cost is **+56,104 triangles (+18 %)** at the default settings: LOD0 is 363,434
triangles against 307,330 unbevelled. Bevelling every edge of these surfaces plus sills
cost +115,832 triangles, so it was cut back. Small strips (mullions, sills, louvres,
frames, hazard stripes) get their rounded edges from the trim sheet's normal map instead.
Chamfer faces carry `Cd.g = 1`, which the materials use for edge wear.

### UVs

Every face gets a `uv` from one of four modes (prim attribute `mat` names its material):

- **World tiling** (cladding, armour, backers, plinth, roof, slabs, ceilings, walls, metal
  parts): a box projection in metres / 4 m, giving 512 px/m on 2K textures. Each tier and
  floor gets a random U offset so floors do not repeat in step.
- **Trim rows** (mullions, sills, louvres, trims, hazard stripes, coping, frames, skirting,
  brackets, lights, helipad marks): U runs along the face's long axis at 512 px/m and
  tiles across the sheet; V spans the face's short axis, fitted into the surface's row with
  3 px padding.
- **Window atlas** (`facade_glass`): each window is fitted into one 512 px cell of a 4×4
  atlas. Row 0 holds unlit variants and rows 1 to 3 lit ones. Lit or unlit is chosen per
  window and per office zone of about 9 m per floor, so night facades read as lit floors
  rather than noise. The same choice is written to `Cd.b`.
- **Sign atlas** (`sign_panel`): facade blades map into four 1:8 columns, with V spanning
  the whole blade over all its floors. Rooftop billboards map into three 2:1 cells.
  `sign_slot` picks the cell.

Trim sheet rows (px from the bottom of the 2048 px sheet):

| Row | px | Surfaces |
|---|---|---|
| 0 frame dark | 0–128 | mullions (Neo-Tokyo), door frames, sign frames, skirting |
| 1 frame pale | 128–256 | mullions (Tokyo-3) |
| 2 sill | 256–384 | sills |
| 3 louvre | 384–448 | louvre slats |
| 4 NERV orange, 5 NERV purple, 15 chevron stencil | 448–704, 1728–2048 | `trim`, picked per tier and floor |
| 6 hazard yellow, 7 hazard black | 704–960 | hazard stripes |
| 8 white paint | 960–1088 | helipad markings |
| 9 warm, 10 red, 11 cyan light | 1088–1280 | `light` (interior and canopy, crown beacons, Neo-Tokyo accents) |
| 12 coping | 1280–1536 | coping |
| 13 steel | 1536–1664 | brackets (`metal`) |
| 14 gasket | 1664–1728 | spare |

`uv2` (lightmap and AO) is on LOD1 and LOD2: UV Unwrap per piece, then UV Layout at 1024
with 2 px padding and area-correct scaling. LOD0 has no `uv2`. Its 178k faces form
hundreds of thousands of islands, which would not pack usefully, so LOD0 carries vertex
AO instead.

Vertex colour `Cd` is a mask set, not a colour: **r** is AO (12 cosine rays, 1.5 m),
**g** is the bevel-edge mask and **b** is the lit-window flag.

### Textures

13 sets × 4 maps, 2048² PNG, written by Copernicus inside the asset (`textures/`): one VEX
wrangle per set, Height to Normal for the normal map, and Font nodes for the signs. Names
are `T_<set>_BaseColor.png` (sRGB), `T_<set>_Normal.png` (OpenGL, +Y up), `T_<set>_ORM.png`
(R occlusion, G roughness, B metalness, linear) and `T_<set>_Emissive.png` (sRGB).

| Set | Kind | Content |
|---|---|---|
| `trim` | trim sheet | the 16 rows above, with rounded edges in the normal map |
| `window` | atlas 4×4 | fake interiors: ceiling light strips, desks, monitors, blinds, painted frames |
| `signs` | atlas | neon katakana and kanji blades (ネオン東京, ラーメン, 薬局24, カラオケ) and backlit billboards (新東京, 電気街, 居酒屋) |
| `lod2` | atlas 4×4 | far facade, two modules × two floors per cell, Tokyo-3 and Neo-Tokyo, lit and dark |
| `clad_pale`, `clad_dark`, `armour` | tiling, 4 m | Tokyo-3 paint with rain streaks; Neo-Tokyo dark slabs with rust; lilac armour plates with 2 × 1 m plate lines, rivets and chips |
| `concrete`, `metal`, `roof` | tiling, 4 m | formwork concrete with tie holes; painted steel with scratches and rust; bitumen membrane |
| `floor`, `ceiling`, `wall` | tiling, 4 m | 0.5 m vinyl tiles; 0.5 m acoustic tiles in a T-bar grid; painted plaster |

### Materials

14 MaterialX materials live in `materials/` inside the asset: subnets with the material
flag set, holding `mtlx_standard_surface`, 4 images, a normal map, ORM split and vertex
masks. Each material derives its texture set from its own name (`M_trim` reads `T_trim_*`).
`shop_materialpath` binds them for Karma. The FBX material slots carry the same names, and
the USD binds GeomSubsets to `/neo_tower/materials/<name>`.

| Material | `mat_id` surfaces |
|---|---|
| `M_trim` | 3 mullion, 4 sill, 5 louver, 9–11 hazard and trim, 13 metal, 15 light, 17 sign_frame, 19 door_frame, 22 coping, 26 helipad_mark, 34 skirting |
| `M_clad_pale` / `M_clad_dark` | 0 facade_panel, 21 parapet, 23 penthouse (pale on armour and grid tiers, dark on ribbon tiers) |
| `M_clad_dark` | 1 facade_backer, 35 int_proxy; 7 column on non-armour tiers |
| `M_armour` | 6 armour; 7 column on armour tiers |
| `M_window` | 2 facade_glass (opaque atlas, emissive at night) |
| `M_signs` | 16 sign_panel |
| `M_concrete` | 8 plinth, 31 stair, slab edges |
| `M_metal` | 12 greeble, 14 pipe, 18 canopy, 24 tank, 32 lift_door |
| `M_roof` | 20 roof, 25 helipad, LOD2 roof caps |
| `M_floor`, `M_ceiling`, `M_wall` | 27 slab tops, 28 ceiling undersides, 29 int_wall and 30 core |
| `M_glass` | 33 int_glass (transmissive, thin-walled) |
| `M_lod2` | the LOD2 shell |

### LODs and collision

Default tower (chamfered, armour, 36 floors, 3 tiers, interiors on, seed 1):

| Output | Polygons | Triangles | Materials |
|---|---|---|---|
| LOD0 | 178,093 | 363,434 | 12 |
| LOD1 | 27,596 | 56,596 | 8 |
| LOD2 | 1,054 | 2,330 | 5 |
| collision | 36 | 96 | 4 hulls |

- **LOD1** drops interiors and the surfaces in `lod1_drop` (greebles, pipes, brackets,
  louvres, mullions, sills, door frames, tanks). It also drops faces under 0.01 m², thin
  returns under 0.1 m that do not face out, and inward-facing facade faces. The crown is
  kept whole. Windows become opaque atlas windows with painted frames, so the same lit
  pattern carries over from LOD0.
- **LOD2** is each tier outline extruded from `y0` to `y1`, cut into quads of two modules
  × two floors. Each quad maps to a random cell of its style's lit or dark row in the
  `lod2` atlas. Roof caps and the LOD1 crown are added.
- **Collision** is one prism per tier from the 2D convex hull of its outline (at most 16
  sides; a box for rect footprints), plus a box around the crown. The hulls are closed,
  face outward and are named for Unreal (`UCX_SM_neo_tower_00…`).

### Exports (`export_dir`, not committed)

| File | Content |
|---|---|
| `SM_neo_tower_LOD0.fbx` | LOD0 triangulated, with the `UCX_` hulls (Unreal picks them up as collision) |
| `SM_neo_tower_LOD1.fbx`, `SM_neo_tower_LOD2.fbx` | LOD1 and LOD2 with `uv`, `uv2`, `N` and `Cd` |
| `SM_neo_tower_collision.fbx` | the hulls alone |
| `SM_neo_tower.usd` | `/neo_tower` (kind component) with variant set `LOD` (LOD0, LOD1, LOD2; LOD0 selected), `/neo_tower/materials` (MaterialX, texture paths relative: `./textures/…`) and `/neo_tower/collision` (purpose guide) |
| `textures/T_*.png` | 52 maps |

The FBX carries polygon groups and integer attributes such as `mat_id` as user
attributes. String attributes such as `surface` are dropped. The re-import check
(`p2_07_fbx_reimport.jpg`) loads `SM_neo_tower_LOD1.fbx` with a File SOP in a fresh scene.
It references only the materials from `SM_neo_tower.usd` and binds them by FBX slot name,
then renders with Karma.

### Known limits (P2)

- **No `uv2` on LOD0** (see UVs). LOD1's UV Layout takes about 32 s, and it is the slowest
  node in the asset. Turn `lightmap_uv` off while art-directing.
- **Trim mapping fits V to the face.** Pieces much taller than their row, such as a
  0.55 m coping top in a 0.5 m row, stretch the row's profile.
- **Windows are opaque atlas cards, even at LOD0.** The real interiors show only
  through `int_glass` and in cut-away. A `clear glass` mode for LOD0 is P3 work.
- **LOD2 reads slightly brighter than LOD1 at dusk**: the flat shell lacks the recess
  shadowing (`p2_05`).
- **The crown collision box encloses the whole crown**, mast included.
- **The sign font is a Windows path.** On other systems, set `sign_font`.
- **Textures are generated, not scanned.** They are clean, readable stylised PBR at
  512 px/m. Grime, decals and per-building colour variation are P3 lookdev.
