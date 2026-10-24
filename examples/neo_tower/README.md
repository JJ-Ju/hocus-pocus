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

Through HocusPocus, `node_create {parent: "/obj/tower", type: "hp::neo_tower::1.0"}` works
once the file is installed. There is no install tool yet, so P1 used `houdini_python`.

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
- **No UVs yet.** UVs are P2's job.
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
