# Danchi generator — build log

Task: procedural 1980s Japanese public housing block (danchi) generator as a Houdini digital
asset for games. Houdini driven only through the HocusPocus MCP tools. Outputs in this folder:
`work/` (hip), `danchi.hdalc`, `evidence/` (JPG < 400 KB), `README.md` (brief, contract,
budgets, interface), `scripts/` (VEX / Python sources fed to the nodes).

Times are local (EDT), 2026-10-26.

## 22:17 — Read the method first

- Loaded the `procedural-assets` skill and its two companions (`procedural-mesh-damage`,
  `procedural-materials`) with the Skill tool, as the main skill asks.
- Read the per-phase references the skill lists: believability.md, hocuspocus-recipes.md,
  metrics-and-kits.md, generator-architecture.md, game-output.md, surfacing.md (assets);
  causes.md (damage); realism.md, micro-noise.md, weather-and-use.md (materials).
- Why: the skill says most of the realism guidance lives in the references, and an earlier
  run that skipped them repeated a uniform streak fringe.
- Key rules I am carrying forward: contract first; a short box skeleton; quality bottom-up
  (golden piece -> golden bay -> facade -> building); 80/20 clustered detail from one cause
  field; streaks only from features (sill ends, tops without drips, attachments, rail posts);
  dirt is a colour; plan points + Copy to Points; randomness from stable ids; Copy to Points
  2.0 made by script copies no attributes until `targetattribs` is set; `shop_materialpath`
  must be on packed prims; SOP `Cd` reaches Karma as `displayColor`.

## 22:19 — Session and de-risk (phase 0)

- `houdini_status` (nothing running) -> `houdini_connect {launch: {mode: headless}}`: Houdini
  22.0.466, pid 6804. Saved at once to `work/danchi_v001.hiplc` so `$HIP` is the work folder.
- De-risk in one `houdini_python` call: node types present (Labs LOD Create **missing** -> LODs by
  PolyReduce / hand-made LOD pieces); Font SOP with `SideFX WenQuanYi Zen Hei` renders `12号棟`.
- Material route: a MaterialX builder in a matnet, assigned by `shop_materialpath` in SOPs,
  rendered through a Scene Import LOP with `look quality final`. **Slowdown:** the first render
  was empty grey — Scene Import 2.0's `objects` parm defaults to empty, so it imported nothing.
  Setting `objects` to `*` fixed it (found via `inspect stage`, 0 prims).
- Web search for exact danchi dimensions returned nothing useful (2 queries); used standard
  JHC proportions and the photo counts already in the skill references. No browser tool for
  studying photographs was available, so the README says the photo rules come from review 31.
- README written: brief, signature features, reference rules, de-risk table, contract, piece
  list, budgets (gate for phases 0 and 1).

## 22:25 — Helper library and plan (phases 1-2)

- Wrote `scripts/lib.vfl` (box/quad/tube/sheet helpers that tag every prim with `mat`, `part`
  and the piece `name`, box UVs in metres) and a build script `scripts/build.py` that creates
  the subnet, its interface (spare parms in tab folders) and one wrangle per piece from the
  `.vfl` files. Each piece is its own wrangle; Copy to Points places them by `name`.
- **Slowdown 1:** first winding test showed 13/16 faces inward. Cause was not the winding: a
  wrangle cannot read back points it has just added (`point()` reads the input), so the normal
  test saw zeros. Rewrote the helpers to carry positions with the point numbers; re-test: 0/16
  inward.
- **Slowdown 2:** VEX needs functions before any statement — moved `addp` to the top of the plan.
- Plan (`plan_bays.vfl`): points per bay piece with `name, floor, unit, side, id, flat, persona,
  tint, dirt, patch, rv, orient`; per-flat persona (tidy/family/gardener/elderly/vacant) chooses
  sash state, room and curtains together; 1-2 columns in 5 get heavy `dirt` through several
  floors (photo rule).

## 22:33 — Skeleton gate (phase 2)

- First build: no errors, 76k prims. `inspect geo group_by name` on the output: every piece
  present with the right counts and bounding boxes (balcony parapets at z 4.20–5.47, corridor
  parapets at −5.50…−4.20, cores only in core bays).
- Contact sheet (`evidence/01_skeleton_contact_sheet.jpg`): default (8 fl × 10 units), minimum
  (4 × 3, 5 m bays), maximum (14 × 24, 7 m bays, deep balconies) and cores at both ends with a
  forced lift on 5 floors. All cook without errors (11k–329k prims).
- Defects found and fixed:
  1. Copy to Points `applyto1 = 1` put the plan attributes on **vertices**; set the `prims`
     token (the recipe warns about exactly this).
  2. Stair-tower north wall: opening heights were passed relative to the floor while the
     helper wants absolute heights, so the face came out solid. Rebuilt as bands from half
     landing to half landing.
  3. `dwall` always hid the −z face; the stair wall faces −z. Added an `inside` argument.
- A false alarm cost a few minutes: corridor parapets looked missing in the flat-shaded draft;
  they were there (only the top 1.2 m of each door showed). Flat draft shading hides
  same-colour planes — judge forms lit.

## 22:38 — Render stage and first materials

- Built `/stage`: Scene Import (`objects` = `*`), Karma Physical Sky, render settings. First-pass
  MaterialX materials read `displayColor`, `rough`, `metal` primvars (`scripts/mats.py`).
- **Slowdown:** `look` refused an OBJ camera with a stage target; the hint listed the imported
  camera prims (`/cam_bay`). Used those.
- **Slowdown:** sun direction. The first lit render looked flat; I flipped the azimuth on a guess
  and it got darker. Read the sun prim's world transform off the USD stage instead: azimuth is a
  compass bearing with north = −z, east = +x. 215° was right but front-lit this camera; moved
  the sun to 145° (SE), 30° up, raking across the facade away from the camera.

## 22:44 — Golden piece: balcony parapet (phase 3)

- Forms in three size classes: slab + parapet + coping (primary); pipe rail on posts, spout,
  sealant joint, coping overhang (secondary); drip groove, base plates, anchor bolts (tertiary).
- Edges: one strategy per kit — 12 mm chamfer on piece concrete, 15 mm on connective walls,
  face-weighted normals (`normal` method area, cusp 50 so the 45° chamfer smooths into faces).
- Imperfection: rigid ±3 mm offsets along the facade normal per parapet instance (lippage
  behind the sealant joint, snapping kept).
- Damage with the `procedural-mesh-damage` scripts: `cluster_mask` → `chip_points_edge` →
  8 hull cutters (`cutter_shape`) → Boolean on the bevelled coping, three seeded variants
  (`bal_parapet_d1..3`) on about a third of instances; the rest keep background wear only.
  - First pass: ~750 cutters, 15–20k triangles per 6 m coping, mostly sub-cm bites invisible at
    bay distance (1 px ≈ 6 mm at 10 m). Raised the size floor, thinned background chips, added
    `divide` before the Boolean (variant 2 had 3 open edges), PolyReduce 45 % →
    **2.4–3.5k triangles per damaged coping**.
  - `damage_validate`: open 0, non-manifold 0, seam_changed 0, zero_uv 0, unchanged 0 (all 3).
  - `damage_measure`: flank_runs 0 / 0 / 0; edge_area_share 0.999 / 0.999 / 0.998 (≥ 0.9);
    face_to_edge 0.335 / 0.225 / 0.223 (target ≤ 0.3; variant 1 slightly over).
- **Slowdowns:** (1) menu parms rejected string tokens through `parm.set` (`filletshape`,
  `grouptype`) — wrote a `pset` helper; (2) PolyReduce `hardfeatureedges` is an edge-group
  string, not a toggle; (3) chips rendered as grey bulges because the kit's smooth normal pass
  rounded the concave cut faces — gave damaged copings their own 25° normals and excluded them
  from the kit normal pass; (4) two identical renders made me suspect stale geometry; forced
  the stage chain, same picture. It was not stale — the chips face the sun while the parapet
  face is in shade. A bounding-box check I wrote wrongly (box seeded at the origin) also cost
  a few minutes.
- **Slowdown:** `connectivity` parms are `connecttype` / `primincgroup`, not `group`.

## 22:53 — Surfacing (phase 3 materials, phase 4/6 weathering)

- `scripts/tex.py`: spray-tile paint (Copernicus: flat mesas with troughs × clustered envelope +
  roller meso), board-formed concrete (cop_lib template, 3.6 m tile), streak decal atlas and a
  horizontally tiling parapet fringe drawn with numpy (exact head width, fan angle, power-law
  lengths). 5 s total. `cellularnoise` has no gap/bevel parms in this build (`smoothedge`).
- Wall shader (`m_wall`, `m_conc`): primvar colour × 12 m world macro wash (±8 %) × spray-tile
  cavity; per-column `dirt` drives vertically stretched streak noise lerped toward soot brown
  (dirt as a colour); damp splash band with a ragged top at 0.35–0.85 m (darker, smoother);
  roughness = primvar + tile − damp.
- Decals placed only at sources (`g_decals.vfl`): spout fans, rail-post rust runs (biased to
  neglected flats and dirty columns), V pairs at kitchen/toilet sill ends, coarse fringe + dark
  band under the corridor parapet tops and roof parapets (tops without drips), fine fringe on
  corridor parapet inner faces, end-wall top band and a vent streak. Strength = power law ×
  column dirt × Weathering. 399 decals + 168 fringe strips on the default building.

## 23:00 — Golden bay dressing, roof, LODs, collision, number

- Props by persona (`plan_props.vfl`, `p_props.vfl`): AC outdoor units in three generations
  with duct covers to a wall sleeve, laundry poles with shell garments, towels and a sock
  hanger, futons over the rail, potted plants, storage boxes, BS dishes aimed SW 38° up,
  corridor umbrellas and pots; one hero balcony per building.
- Roof (`p_roof.vfl`): FRP sectional tank on a braced steel stand with ladder and rail; antenna
  masts with two Yagi arrays and guy wires.
- LOD1 = same pieces with `#define LOD1` (no groove, bolts, grilles, louvres; glass + dark room
  card instead of rooms/curtains), no props or damage (built from undamaged sources), large
  fringes only. LOD2 = banded shell (light parapet bands, dark recess bands), cores, tank,
  number. Collision = 4 boxes `UCX_danchi_00..03`.
- Number: Font SOP (`SideFX WenQuanYi Zen Hei`, lod 0.35) with a Python text expression for
  `7` / `3-7` / `7号棟`, scaled to 0.18 × height (≤ 4.5 m), on both end walls.
- VEX slowdowns: inline `point()` inside `setpointattrib` and `rand()` inside `lerp` are
  ambiguous (the recipe warns about both); functions declared after statements (twice).
- Budgets measured: **LOD0 340,528 tris, LOD1 51,998, LOD2 116** (budgets 400k / 60k / 4k).

## 23:10 — Asset (phase 8)

- `hda create` → `jj::danchi::1.0` in `danchi.hdalc` (33 parms promoted), wired the Edge Damage
  and Weathering parms that were not yet connected, `hda save` with help, locked.
- Gate: a fresh instance from the library cooks in 0.81 s, no errors or warnings, 180k prims,
  4 collision hulls, every `shop_materialpath` resolves inside that instance.

## 23:11 — Presentation scene and street views (phase 9)

- Context in `/obj/context` (`ctx_ground.vfl`, `ctx_props.vfl`): planting strip with worn
  earth and a gravel drip strip, kerbs, paver sidewalks, patched asphalt road with wheel-path
  darkening and worn lines, a north parking lot, utility poles (11 m, crossarms, insulators,
  a transformer) with sagging wires, a low fence. Four more instances of the asset in the
  background with other seeds, sizes and random palettes (11, 5, 9, 7 floors).
- Cameras at eye height 1.6 m, 24–28 mm, level, with lens shift (`winy`) to keep verticals
  straight; a 55 mm estate camera.
- Review of the first street view and fixes: left half was a bare plane → reframed and moved a
  block into it; laundry too colourful and busy → muted palette (mostly white/grey/navy/beige,
  ~1 in 6 tinted); column dirt too faint at 40 m → shader dirt amount 0.55 → 0.85.
- Each asset change was unlock → reload nodes from the `.vfl` files → `hda save lock`.
- **Slowdown:** the hero view showed no number on the end wall. I checked the stage (number
  mesh present), the colour and material binding (identical to the visible "6"), then a close
  render (the "7" was there). Cause: a utility pole stood exactly in front of it from that
  camera position. Moved the camera.
- Corridor side: correctly in shade under a south-east sun, but dark and flat. Rendered it with
  a summer-morning sun from the north-east (62°, 22° up), which is when a north face in Tokyo
  gets direct light.
- End wall still read as the bare-wall case (30 m to a 4 m number with little between) → added
  the 1–3 m class: downpipes with brackets and shoes at both corners, a roof outlet, and dark
  edge lines down each side of each pipe (vertical attachments: side lines, not a centre streak).
- Estate view: ground outside the near grid rendered white. Cause: point `Cd` on the near
  ground and prim `Cd` on the far ground and props → after the merge the prim-coloured parts
  got the white point default. Switched the ground wrangle to primitives.
- Close-up review: spray-tile read as a regular waffle grid at arm's length → two cell sizes,
  domain-warped by a slope-direction field, normal strength lowered; futon was a rigid box →
  two wavy 60 mm layers with a rolled fold and clips. Cleared the texture cache (`texcache -c`)
  before re-rendering.

## 23:48 — Variation, LOD gate, night (phases 6, 7)

- 9-up variation sheet: nine instances with designed differences (4–14 floors, 6–15 units,
  cores one/both/middle, number formats, palettes, weathering, occupancy). Reviewed: silhouettes
  differ well; **palettes read too alike under warm light** (left as a known weakness).
- LOD value match, measured with `scripts/png_stats.py` (mean linear luminance of the same
  facade rectangle in three renders from one camera):
  - first pass: LOD1 −11.7 %, LOD2 +22.0 % (LOD2's sunlit dark band stands in for a recess that
    is really in shadow; LOD1's dark room card replaces bright lace and laundry);
  - solved the LOD2 dark band for the measured mean (wall × 0.36 → 0.18) → **+0.8 %**;
  - LOD1 room card 0.05 → 0.24 gave −7.7 %; from that slope, 0.50 (lace over a dark room)
    → **−1.9 %**. Both within ±3 %.
- Night: first render left the facade dark (small lamp discs barely light rooms at 32
  samples, the failure the skill warns about). Made rooms, curtains and balcony lamps of lit
  flats emissive (one lit/unlit decision per flat, vacant flats dark), wired `emit` into the
  generic and cutout materials. Windows now glow per flat.
- Packaging gate: brand-new instances cooked at LOD0 0.83 s, LOD1 0.78 s, LOD2 0.04 s — the LOD0
  branch costs nothing when LOD2 is selected. (A first attempt re-cooked one instance and read
  cached internals; switched to fresh instances per setting.) Triangles: LOD0 354,384, LOD1
  53,018, LOD2 192.

## 23:58 — Wrap-up

- Saved `work/danchi_v002.hiplc`; asset saved and locked in `danchi.hdalc`.
- Evidence: 11 JPGs in `evidence/`, 65–214 KB each (all under 400 KB). The two skeleton images
  are drafts from the phase-2 gate; `02` predates the stair-opening fix (see `06`).
- README holds the brief, contract, budgets, interface, attributes, measured numbers, evidence
  list, an assessment by level and the limits.

## What slowed me down, in order of cost

1. Rendering and judging in Karma: each final look at 1600×900 took 1–3 min; about 30 of
   them. The single largest cost, and the most useful.
2. VEX writing traps: points not readable after `addpoint`, functions after statements (×3),
   ambiguous overloads (`point()` inside `setpointattrib`, `rand()` inside `lerp`), a missing
   `~` operator workaround. Each was caught by the node error with line/column.
3. Houdini parm details: menu tokens through `parm.set`, Copy to Points `applyto1` index 1 =
   vertices, PolyReduce `hardfeatureedges` being a group, Connectivity parm names, Scene Import
   `objects` empty by default, `cellularnoise` without gap/bevel.
4. Diagnosing pictures: sun azimuth convention, chips reading as bulges (normals), the number
   hidden by a pole, white ground from mixed attribute classes, two "stale render" suspicions
   that were not stale.
5. The shell heredoc broke once on quoting; wrote the patch as a Python file instead.

Nothing in the HocusPocus tools themselves blocked the work; the error hints (camera
candidates, menu-token notes from `parm_set`) saved several round trips.

## 00:00 — Quit

- `houdini_status`: hip `danchi_v002.hiplc`, not dirty. `houdini_connect {quit: true}` → exited.
