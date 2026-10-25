# neo_tower: a procedural anime skyscraper (HDA `hp::neo_tower::1.1`)

`neo_tower.hdalc` is a SOP digital asset that generates futuristic skyscrapers in the look
of 1980s and 1990s anime cities:

- **Tokyo-3** (*Evangelion*):
  - slender telescoping tiers;
  - armoured panel cladding with seams, visor hoods over slit windows and closed armour
    shutters;
  - heavy armour bands with hazard stripes, and full-height armour fins;
  - an armoured sleeve ring where each tier rises out of the one below, and an armoured
    base collar;
  - heavy crown hardware: sensor stacks, pods, a radar dish, lattice masts and a
    crenellated cap ring;
  - NERV-style markings: floor and block numbers, warning plates and vertical stencils.
- **Neo-Tokyo** (*Akira*):
  - dense slabs with ribbon windows, louvred spandrels, AC units and vertical sign blades;
  - stacked and offset blocks bolted onto the facades, and cantilevered blocks on struts;
  - an attached service tower with sky bridges;
  - giant billboards on standoffs with floodlights;
  - rooftop clutter: water tanks on stilts, lattice aerials, AC banks and searchlights.

Interiors are finished but unfurnished. Each floor gets a slab, a suspended ceiling with
light panels, a core (lift shafts with doors, a dog-leg stair, a lift lobby and a riser
room), corridors, and partitions with door openings, architraves, glazed sidelights and
skirting.

A second asset, `neo_tower_export.hdalc` (`hp::neo_tower_export::1.0`, phase P2), turns the
tower into a game asset: hero bevels, trim-sheet and tiling UVs, procedural PBR textures,
MaterialX materials, LOD0 to LOD2, UCX collision, and FBX and USD export. See the
Game export section below.

It was built in phases P1 to P3 of the HocusPocus 2.1 dogfood (plan-2.1 §2) entirely
through the HocusPocus MCP tools. P3 added the silhouette vocabulary and the style presets
(version 1.1), plus grime, tone and decal layers in the export asset. The log is in `docs/redesign/review/26-neo-tower-dogfood.md` and
the images are in `docs/redesign/evidence/neo-tower/`.

**Licence note.** It was built on a Houdini **Indie** licence, so the asset is
`neo_tower.hdalc` and the build scene is `work/neo_tower_p1.hiplc`. A Commercial
session can load an `.hdalc`, but it turns that session into a limited-commercial
session.

## Loading it

```python
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower.hdalc")
geo = hou.node("/obj").createNode("geo", "tower")
tower = geo.createNode("hp::neo_tower::1.1")
tower.parm("preset").set("neotokyo_slab")
tower.hm().apply_preset(tower)   # the menu callback does this in the UI
```

Through HocusPocus (2.1), the steps are:

1. `hda {action: "install", library_path: "<repo>/examples/neo_tower/neo_tower.hdalc"}`.
2. `node_create {parent: "/obj/tower", type: "hp::neo_tower::1.1"}`.
3. `parm_set {path: ".../preset", value: "neotokyo_slab"}`, then press `apply_preset`.

P1 to P3 ran on the 2.0.0 bridge, which has no install tool, so they used
`houdini_python` for this.

**Versions.** `neo_tower.hdalc` holds both `hp::neo_tower::1.0` (P1 and P2, unchanged)
and `hp::neo_tower::1.1` (P3).

P3 bumped the generator to 1.1 because the change is visible to a 1.0 consumer:

- Output 2 gains volume primitives (`kind` fin, sleeve, annex) after the tier outlines.
- The tower gains the surface `decal` (`mat_id` 36) and the prim attributes `decal_id`,
  `fixture` and `aim`.
- Annex prims use tier 20 and up.
- Even at the defaults, a 1.1 tower adds fins, sleeves and markings.

Scenes saved with 1.0 therefore keep 1.0 and look the same.

The export asset stays at `hp::neo_tower_export::1.0`. Its outputs, parm names and
material slot names are unchanged. P3 only:

- added parms with defaults;
- fixed two defects, the LOD2 pop and the crown collision box;
- added the grime and decal content.

Existing scenes should pick these up.

The build scenes `work/neo_tower_p1.hiplc`, `_p2` and `_p3` are not committed.

P3's scene holds:

- the dusk (`D_*`), night (`N_*`), variation (`V_1` to `V_9`), cut-away (`C_cut`) and FBX
  re-import (`E_fbx`) objects;
- their light rigs;
- the Karma ROPs `/out/p3_*`.

The P1 scene holds the asset instance
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
| Silhouette | `preset` | style preset: custom, `tokyo3_spire`, `tokyo3_block`, `neotokyo_slab`, `neotokyo_stack`. Picking one (or **Apply Preset**) sets the massing, facade, crown and silhouette parms and nothing else; edit freely afterwards |
| | `fins`, `fin_depth`, `fin_width`, `fin_cap` | Tokyo-3 full-height armour fins per long face, at module boundaries; the cap is the raked rise above the tier parapet |
| | `sleeves`, `sleeve_depth`, `sleeve_height` | armoured sleeve ring where each tier rises out of the one below |
| | `shutter_ratio` | share of armour-style windows closed by armour shutters |
| | `crown_hw` | heavy crown hardware density: sensor stacks, pods, radar dish, lattice masts, crenellated cap ring |
| | `annex`, `annex_height`, `annex_width`, `annex_gap`, `bridges` | Neo-Tokyo service tower beside tier 0 (height as a share of the tower), linked by sky bridges |
| | `blocks`, `cantilevers`, `block_depth` | stacked and offset blocks bolted onto the facades; deep cantilevered blocks high up, on struts |
| | `billboards` | giant facade billboards (2:1, up to 26 m wide) on standoffs with floodlights |
| | `clutter` | rooftop clutter: water tanks on stilts, lattice aerials, AC banks, searchlights, aircraft warning lights |
| | `markings` | floor and block numbers, warning plates and vertical stencils (surface `decal`) |
| Seed | `seed`, `variation` | the seed always varies details; `variation` lets it jitter tier heights, setbacks, corner size and crown height |
| Output | `preview_colors` | writes a per-surface preview colour to prim `Cd`; turn it off for export |
| | `cutaway`, `cut_floor`, `cut_front` | presentation only: removes floors above `cut_floor`, that floor's ceiling and the front facade |

Disable-when rules: `corner` for rect and round, `collar_floors` without a collar,
`band_every` outside armour style, the Interior parms when interiors are off, the cut
parms when `cutaway` is off, the fin and sleeve sizes when those are off, the service tower
parms without a service tower, and `block_depth` with no blocks or cantilevers.

Presets (all at 3.6 m floors):

| Preset | Massing | Silhouette |
|---|---|---|
| `tokyo3_spire` | chamfered 36 × 34 m, 60 floors, 5 tiers, armour cap crown | 2 fins, sleeves, 45 % shutters, crown hardware 0.9 |
| `tokyo3_block` | rect 48 × 40 m, 34 floors, 3 tiers, mast | 3 fins, sleeves, service tower with 3 bridges, crown hardware 1.0 |
| `neotokyo_slab` | rect 66 × 30 m, 50 floors, 2 tiers, ribbon, helipad | service tower with 4 bridges, 3 blocks, 1 cantilever, 2 billboards, clutter 0.9 |
| `neotokyo_stack` | stepped 52 × 44 m, 44 floors, 4 tiers, mixed styles, spire | 5 blocks, 2 cantilevers, 3 billboards, clutter 1.0 |


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
- **Two outputs.** Output 1 is the tower. Output 2 (added in P2) is the massing.
  - It has one outline polygon per tier with `tier`, `style` (0 armour, 1 ribbon, 2 grid),
    `f0`, `nf`, `y0`, `y1`, `tw` and `td`.
  - Its detail attributes are `H`, `nfloors`, `ntiers`, `nannex` and `crown_scale`.
  - The export asset uses it for the style-dependent materials, the LOD2 shell and the
    collision hulls.
  - In 1.1 the tier outlines have `kind` "" and are followed by the **volumes**, closed
    outlines wound the same way, each with a `kind`:
    - `annex`: the service tower, blocks and cantilevers. They have tier `20 + k`, `sub`
      (0 service tower, 1 block, 2 cantilever), the attach frame `aO`, `aX`, `aZ`, the gap
      `ag` to the host facade, and `host` and `skip_e`.
    - `fin`: an armour fin, with its frame `fO`, `fX`, `fZ`, `fu0`, `fu1`.
    - `sleeve`: a sleeve ring, with depth `sd`.
  - Filter on `kind == ""` to get only the tiers, as in the 1.0 contract.
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
| `sign_slot` | int | −1 except on `sign_panel`: rooftop billboards are `tier·10 + slot`, giant facade billboards (1.1) `50 + k`, facade sign blades `100 + tier`; use it to assign sign textures |
| `decal_id` | int | 1.1: −1 except on `decal` quads (1 cm off their face); the cell in the export's decal atlas (see Decals) |
| `fixture` | string | 1.1: "" or `beacon`, `spot`, `flood` on `light` faces, so a light rig can place lights there |
| `aim` | vector | 1.1: unit aim direction of `spot` and `flood` lens faces; {0,0,0} elsewhere |
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
35 int_proxy     36 decal (1.1)
```

Emissive candidates for P2: `light` (canopy downlights, ceiling panels, aircraft and
band beacons), `sign_panel`, `facade_glass` (night windows) and `int_glass`.

Where the 1.1 additions land:

- **Annex volumes** (tier 20 and up) are built by `facade_annex`, a copy of `facade`. Their
  prims have `part` facade, the same surfaces, and their own `floor`.
- **Fins and sleeves** are `armour` with `part` facade.
- **Crown hardware, rooftop clutter and sky-bridge roofs** are `part` crown or roof.

## Poly budget

1.1 at its defaults (chamfered, armour, 36 floors, 3 tiers, 2 fins, sleeves, markings,
interiors on, seed 1) gives **153,891 polygons, 315,776 triangles**:

- facade 177,702;
- roof 2,374;
- crown 2,676;
- interior 133,024.

That is 2.7 % more than 1.0. It includes 603 decal quads and 230 beacon fixtures.

The presets cost more because they are bigger towers. The table gives the export's
triangle counts (LOD0 adds bevels):

| Preset (seed) | Interiors | LOD0 | LOD1 | LOD2 | Collision |
|---|---|---|---|---|---|
| `tokyo3_spire` (1) | on | 510,948 | 92,405 | 2,434 | 324 (7 hulls) |
| `neotokyo_slab` (2) | on | 788,804 | 94,592 | 3,824 | 96 |
| `tokyo3_block` (3) | off | 333,122 | 88,715 | 4,454 | not measured |
| `neotokyo_stack` (5) | off | 539,794 | 122,620 | 3,154 | not measured |

1.0 at its defaults (P1):

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
- 1.1 adds four nodes:
  - `volumes` (detail) builds the volume outlines from the massing and the Silhouette
    parms.
  - `facade_annex` (a copy of `facade`, Run Over Numbers over `nfloors × nannex`) gives
    the annex volumes real facades.
  - `silhouette` (detail) builds the fins, sleeves, annex roofs, parapets, soffits and
    struts, sky bridges, giant billboards, crown hardware, rooftop clutter and decal
    quads.
  - `massing_out` merges the massing and the volumes into output 2.
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

## Known limits (P1, P3)

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
- **Annex volumes are boxes (1.1).** They have rect outlines on every footprint. Blocks
  sit on the long faces of tiers 0 to 2 only, and bridges run straight from the service
  tower to tier 0.
- **Decals are flat quads 1 cm off the face.** They do not wrap corners, and one can
  overlap a louvre or AC unit on the same bay.

## Game export: `hp::neo_tower_export::1.0` (P2, P3)

`neo_tower_export.hdalc` is a second SOP asset. Input 1 takes the tower (neo_tower output
1), input 2 the massing (neo_tower output 2). It works with both generator versions. It
reads the tier outlines (`kind` "") for styles and materials. The 1.1 volumes feed only the
LOD2 shell and the collision hulls.

```python
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower.hdalc")
hou.hda.installFile("<repo>/examples/neo_tower/neo_tower_export.hdalc")
geo = hou.node("/obj").createNode("geo", "tower")
tower = geo.createNode("hp::neo_tower::1.1")
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
| | `grime_streaks` (1.0), `grime_dirt` (0.3), `grime_darken` (0.32), `grime_length` (2.6 m) | P3: rain-streak strength, blotch dirt, albedo multiplier at full grime, how far below an overhang a streak fades out |
| | `tone_variation` (0.14) | P3: per-piece albedo variation on cladding and armour |
| | `lod2_tone` (0.68) | P3: vertex tone of the LOD2 shell, calibrated against LOD1 (see LODs) |

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

Every face gets a `uv` from one of five modes (prim attribute `mat` names its material):

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
  `sign_slot` picks the cell. The 1.1 giant billboards (`sign_slot` 50 and up) use the
  billboard cells.
- **Decal atlas** (`decal`, P3): each decal quad maps to the atlas cell named by
  `decal_id` (see Decals).

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

Vertex colour `Cd` is a mask set, not a colour:

- **r** is tone × AO: a per-piece tone (1 − `tone_variation` × random, on cladding and
  armour; `lod2_tone` on the LOD2 shell) multiplied by the vertex AO (12 cosine rays,
  1.5 m).
- **g** is the bevel-edge mask.
- **b** is the lit-window flag on `facade_glass`, and the rain-streak mask on every other
  surface (P3).

The streak mask is computed by `grime_mask` before the LOD split, so LOD0 and LOD1 match.
It casts a ray straight up from just in front of each point of a non-horizontal exterior
face. Where the ray meets an overhang (sill, ledge, visor, band, sleeve, canopy) within
`grime_length`, the mask is 1 at the overhang and fades to 0 at `grime_length` below it.
To give the spandrels a streak edge, 1.1's `facade` splits each spandrel at the sill
ends.

### Textures

14 sets × 4 maps, plus `T_decals_Opacity.png` and `T_grime_Mask.png`, all 2048² PNG and
written by Copernicus inside the asset (`textures/`). Each set has one VEX wrangle, Height
to Normal makes the normal map, and Font nodes draw the signs and decals. Names
are `T_<set>_BaseColor.png` (sRGB), `T_<set>_Normal.png` (OpenGL, +Y up), `T_<set>_ORM.png`
(R occlusion, G roughness, B metalness, linear) and `T_<set>_Emissive.png` (sRGB).

| Set | Kind | Content |
|---|---|---|
| `trim` | trim sheet | the 16 rows above, with rounded edges in the normal map |
| `window` | atlas 4×4 | fake interiors: ceiling light strips, desks, monitors, blinds, painted frames |
| `signs` | atlas | neon katakana and kanji blades (ネオン東京, ラーメン, 薬局24, カラオケ) and backlit billboards (新東京, 電気街, 居酒屋) |
| `lod2` | atlas 4×4 | far facade, two modules × two floors per cell, Tokyo-3 and Neo-Tokyo, lit and dark; P3 adds 35 % armour shutters and sill grime, and Neo-Tokyo emission × 0.58, so it matches LOD1 |
| `decals` | atlas (P3) | NERV-style markings in sRGB colour plus `T_decals_Opacity` (linear alpha); layout below |
| `grime` | mask (P3) | `T_grime_Mask.png`, linear, tiles every 4 m: R long vertical streaks over a soft wash, G paint-chip noise, B large dirt blotches |
| `clad_pale`, `clad_dark`, `armour` | tiling, 4 m | Tokyo-3 paint with rain streaks; Neo-Tokyo dark slabs with rust; lilac armour plates with 2 × 1 m plate lines, rivets and chips |
| `concrete`, `metal`, `roof` | tiling, 4 m | formwork concrete with tie holes; painted steel with scratches and rust; bitumen membrane |
| `floor`, `ceiling`, `wall` | tiling, 4 m | 0.5 m vinyl tiles; 0.5 m acoustic tiles in a T-bar grid; painted plaster |

### Decals (P3)

`T_decals_*` is a 2048² atlas drawn in Copernicus: `gen_decals` composes 16 Font nodes
(Japanese system font) with procedural plates, stripes and emblems. `decal_id`:

| Ids | Cells | Content |
|---|---|---|
| 0–15 | glyph squares, top row | ０–９, Ｆ, Ｂ, －, ！, ▲, × (floor, block and sleeve numbers) |
| 16–19 | 2:1 plates | 危険, 立入禁止, 非常口, 第３新東京市 |
| 20–21 | 4:1 plates | 緊急避難所 SHELTER 03, 装甲区画 ARMOUR BLOCK |
| 22–25 | 2:1 | chevron, 注意 triangle, red and white stripes, 重量物注意 |
| 26–29 | vertical 1:4.5 stencils | 第三新東京市, 立入禁止区域, 装甲隔壁区画, 特別警戒区域 |
| 30–33 | emblems | ３ in a ring, crosshair, ！ in a diamond, 避難 arrow |

`M_decals` is `M_trim`'s network with `T_decals_*` and the opacity map wired to
`surface.opacity`. Decal quads sit 1 cm off their face. Engines need a masked or
alpha-tested material for this slot.

### Materials

15 MaterialX materials live in `materials/` inside the asset: subnets with the material
flag set, holding `mtlx_standard_surface`, 4 images, a normal map, ORM split and vertex
masks. Each material derives its texture set from its own name (`M_trim` reads `T_trim_*`).

In P3, eight materials (`M_clad_pale`, `M_clad_dark`, `M_armour`, `M_concrete`, `M_metal`,
`M_roof`, `M_trim`, `M_lod2`) gained a grime layer:

- grime = `Cd.b` × the mask's R streaks × `grime_streaks`, plus the mask's B blotches ×
  `grime_dirt`;
- the albedo is mixed towards albedo × `grime_darken` by that amount;
- the roughness rises by 0.25 × grime;
- the edge-wear mask (`Cd.g`) is broken up by the mask's G chips.
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
| `M_decals` | 36 decal (P3; alpha opacity) |

### LODs and collision

Default tower (chamfered, armour, 36 floors, 3 tiers, interiors on, seed 1):

| Output | Polygons | Triangles | Materials |
|---|---|---|---|
| LOD0 | 178,093 | 363,434 | 12 |
| LOD1 | 27,596 | 56,596 | 8 |
| LOD2 | 1,054 | 2,330 | 5 |
| collision | 36 | 96 | 4 hulls |

With generator 1.1 at its defaults (P3; fins, sleeves and markings):

| Output | Polygons | Triangles | Materials |
|---|---|---|---|
| LOD0 | 185,759 | 378,814 | 13 |
| LOD1 | 31,889 | 65,267 | 9 |
| LOD2 | 1,736 | 3,766 | 7 |
| collision | 66 | 204 | 5 hulls |

The preset budgets are in Poly budget above.

- **LOD1** drops interiors and the surfaces in `lod1_drop` (greebles, pipes, brackets,
  louvres, mullions, sills, door frames, tanks). It also drops faces under 0.01 m², thin
  returns under 0.1 m that do not face out, and inward-facing facade faces. The crown is
  kept whole. Windows become opaque atlas windows with painted frames, so the same lit
  pattern carries over from LOD0.
- **LOD2** is each tier outline extruded from `y0` to `y1`, cut into quads of two modules
  × two floors. Each quad maps to a random cell of its style's lit or dark row in the
  `lod2` atlas. Roof caps and the LOD1 crown are added.
  - P3 turns fin and sleeve volumes into armour prisms with world UVs, adds the annex
    volumes with soffit caps, and keeps the giant billboards.
  - **LOD2 calibration (P3).** P2's LOD2 was about 15 % brighter than LOD1 at dusk. P3
    fixed it in three places: the shell's vertex tone `lod2_tone` = 0.68, which stands
    in for the recess shadowing; shutters and sill grime in the `lod2` atlas; and
    Neo-Tokyo emission × 0.58. Masked mean luminance from the same camera at dusk:

    | Tower | LOD0 | LOD1 | LOD2 | LOD2 vs LOD1 |
    |---|---|---|---|---|
    | Tokyo-3 spire | 0.261 | 0.267 | 0.270 | +1.1 % (P2 +15 %) |
    | Neo-Tokyo slab | – | 0.224 | 0.232 | +3.7 % (P2 +12 %) |

- **Collision** is closed convex hulls named for Unreal (`UCX_SM_neo_tower_00…`):
  - one prism per tier, from the 2D convex hull of its outline (at most 16 sides; a box
    for rect footprints);
  - P3: one prism per annex volume. Fin and sleeve outlines widen their tier's hull
    instead of getting their own.
  - P3: the crown gets a **body hull** and a separate **slim mast hull**, instead of P2's
    one box around the whole crown. The body hull covers crown prims at least 6 m across
    plus everything that starts below their top (stacks, pods). The mast hull covers the
    slender prims above the body, within 2.5 m of the crown axis.
  - Thin aerials get no collision.
  - On the `tokyo3_spire` preset this gives 7 hulls and 324 triangles. The crown body
    runs from 216.2 to 233.6 m, and the mast hull is 4.7 × 3.2 m up to 245.8 m
    (`p3_09`).
  - The collision output keeps only `name`. P3 strips every other attribute from it.

### Exports (`export_dir`, not committed)

| File | Content |
|---|---|
| `SM_neo_tower_LOD0.fbx` | LOD0 triangulated, with the `UCX_` hulls (Unreal picks them up as collision); 17.6 MB for the `tokyo3_spire` build |
| `SM_neo_tower_LOD1.fbx`, `SM_neo_tower_LOD2.fbx` | LOD1 and LOD2 with `uv`, `uv2`, `N` and `Cd` |
| `SM_neo_tower_collision.fbx` | the hulls alone |
| `SM_neo_tower.usd` | `/neo_tower` (kind component) with variant set `LOD` (LOD0, LOD1, LOD2; LOD0 selected), `/neo_tower/materials` (MaterialX, texture paths relative: `./textures/…`) and `/neo_tower/collision` (purpose guide) |
| `textures/T_*.png` | 58 maps plus `T_checker.png` (59 files) |

The FBX carries polygon groups and integer attributes such as `mat_id` as user
attributes. String attributes such as `surface` are dropped. The re-import check
(`p2_07_fbx_reimport.jpg`) loads `SM_neo_tower_LOD1.fbx` with a File SOP in a fresh scene.
It references only the materials from `SM_neo_tower.usd` and binds them by FBX slot name,
then renders with Karma.

The FBX re-import check for P3 (`p3_06_engine_check_fbx_lod0.jpg`) loads
`SM_neo_tower_LOD0.fbx` with a File SOP, blasts the `UCX_` hulls, binds the asset's
materials by FBX slot name and renders under a flat engine-style key and ambient light.
During P3 the new internal attributes (`kind`, `piece`, `streak` and the annex frame)
leaked into the FBX as user attributes. The clean nodes now strip them.

### Known limits (P2, P3)

- **No `uv2` on LOD0** (see UVs). LOD1's UV Layout takes about 56 s on the 1.1 presets
  (32 s in P2), and it is the slowest node in the asset. Turn `lightmap_uv` off while
  art-directing.
- **Trim mapping fits V to the face.** Pieces much taller than their row, such as a
  0.55 m coping top in a 0.5 m row, stretch the row's profile.
- **Windows are opaque atlas cards, even at LOD0.** The real interiors show only
  through `int_glass` and in cut-away. A `clear glass` mode for LOD0 is P3 work.
- **The LOD2 window pattern differs from LOD1's.** The brightness now matches (fixed in
  P3), but the lit cells of the far-facade atlas are a random pick, not a bake of LOD1's
  window choice. A `karmatexturebaker` impostor bake would match it exactly.
- **The LOD2 calibration is a constant.** `lod2_tone` was measured under the dusk rig. A
  very different sun angle can show a few percent of pop again.
- **The sign font is a Windows path.** On other systems, set `sign_font`.
- **Textures are generated, not scanned.** They are readable stylised PBR at 512 px/m.
  P3 added rain streaks, blotch dirt, edge chips, per-piece tone and decals.
- **The grime is subtle at a distance.** Streaks are about 2.6 m long and darken by at most
  32 %. They read in close-ups (`p3_07`) but barely at full-tower framing. Raise
  `grime_streaks` and `grime_darken` for a dirtier city.
- **Interior glass slivers.** In cut-away views, the edges of `int_glass` sidelights can
  show as thin purple lines where the cut runs through them (`p3_04`).
- **LOD0 is heavy on the presets**: 0.33 to 0.79 M triangles. That is fine for a hero
  tower. Background towers in a city block should use LOD1 or LOD2.
