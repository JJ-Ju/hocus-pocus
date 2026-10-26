# Danchi generator: work log

Times are local (EDT), 2026-10-25/26. Each step: what, why, the check run, what slowed me down.

## 0. Setup (23:05–23:08)

- Loaded the three skills (`procedural-assets`, `procedural-materials`, `procedural-mesh-damage`) and read every
  reference of `procedural-assets` (recipes, metrics, architecture, believability, surfacing, game output).
  Why: the brief is exactly the skill's case (building generator HDA for a game), and believability.md has danchi-specific
  numbers (timeline events, balcony clutter frequencies, end-wall detail octaves).
- Created `work/` (scene, `vex/`, `py/`, `tex/`), `evidence/`.
- Did not read any HocusPocus source or tests (only the skill files under `.claude/skills`).

## 1. De-risk (23:08–23:12)

- `houdini_status` → nothing running; `houdini_connect {launch: headless}` → Houdini 22.0.466, pid 29480.
  Saved `work/danchi_v001.hiplc` at once so `$HIP` is the work folder.
- Installed nodes (`hou.sopNodeTypeCategory`): copytopoints 2.0, polyreduce 2.0, convexdecomposition, font, polybevel 3.0,
  boolean 2.0, rop_fbx, Karma LOPs present. **SideFX Labs is not installed** (no LOD Create, no Impostor Baker) →
  LODs will be built from the plan (simplified pieces) and PolyReduce, not Labs.
- Font SOP with "SideFX WenQuanYi Zen Hei" renders `12号棟` (6 polygons). Japanese end-wall labels are possible.
- Materials inside the asset reach Karma: a MaterialX builder (`voptoolutils._setupMtlXBuilderSubnet`) in a matnet
  inside the SOP subnet, assigned with `opfullpath()` in `shop_materialpath`, rendered red with `look final`. ✔
- A custom primvar (`grime`) read by `mtlxgeompropvalue` drives a `mtlxmix` in Karma. ✔ (weathering can live in the shader)
- **Packed instances lose materials that sit inside the packed piece** (rendered grey); they keep a material only when
  `shop_materialpath` is on the packed prim itself. Decision: the asset outputs an unpacked mesh by default and offers
  packed instances as an engine option.
- numpy, PIL and OpenImageIO import inside Houdini's Python → render statistics (LOD value match) can be measured there.
- Wrote `README.md` (brief, signature features, contract table).

## 2. Geometry helper library (23:12–23:20)

- `work/vex/lib.vfl`: faces oriented by an explicit outward direction (`polyout`), boxes, chamfered boxes (26 faces),
  profile extrusion, walls with chamfered openings and reveals (`wallholes`), room boxes, cylinders, tubes.
  `work/py/dbuild.py` prepends the lib to each piece's `.vfl` so the asset stores complete snippets.
- Slowed down by three VEX traps: wrangles reject `struct` definitions (switched the tag type to `dict`), array return
  types need the `function` keyword, `array(set(...), set(...))` is ambiguous between vector4 and matrix2.
- Check: outward-normal test on box/chamfered box/cylinder (0 inverted), wall faces (0 facing −Z), Karma look.

## 3. Plan stage and functional skeleton (23:20–23:27)

- Plan wrangles, each single-purpose: `plan_massing` (segments: slab / stepped / staggered / by seed), `plan_style`
  (curated presets → detail colours and balcony type), `plan_cores` (stairs at ends and joints, extra every N units,
  lift original / retrofit / auto), `plan_bays` (every bay-level piece with `name`, `orient`, `scale`, `unit`, `pid`,
  `persona`), later `plan_props`, `plan_roof`, `plan_causes`. Randomness hashes `unit`/`pid` + seed, never `@ptnum`.
- Every L1 piece first as a box at its footprint (`kit_skel`), placed by Copy to Points (piece attribute `name`;
  `targetattribs` set explicitly, the recipe's trap). Connective geometry generated outright: slab/parapet profiles,
  end walls (exposed part only = own rectangle minus the neighbour's), cores.
- Made the HDA early (`hda create` → `sk3::danchi::1.0` in `danchi.hdalc`) so stress and variation sheets use real
  instances while I edit the master copy.
- **Gate:** `inspect geo group_by name` → 110 flats (10×11), 220 sliding panels per opening type, 99 partitions (none at
  segment ends). Stress sheet of 6 instances (4×4 min, 14×24 max, stepped 3-seg, staggered 3-seg, bay 5 m / depth 7 /
  corridor 1.8, bay 7 m / floor 3.0 / stepped with extra stairs) → `evidence/01_skeleton_stress_sheet.jpg`; close looks
  at the stepped and staggered joints showed end walls only where exposed and no gaps.
- Slowed down: a stray test object at the origin confused the first sheet; the camera look-at constraint seemed ignored
  (it was actually fine; I switched to explicit rotations anyway, `py/aimcam.py`).

## 4. Materials and light rig (23:27–23:33)

- MaterialX builders inside the asset's own matnet (`py/mats.py`): conc, conc_raw, roof, steel, alu, glass,
  glass_frost, fabric, lace, interior, plastic, frp, rubber, lamp, plant. Base colour always from `displayColor`
  (so style presets, per-bay tint and repaint patches come from SOPs); weathering is world-space in the shader and
  driven by primvars (`wstop`, `wexp`, `c_dirt`, `c_leak`, `c_rust`, `c_patch`) plus HDA parms by channel reference.
- MaterialX parm names carry the signature (`in2_vector3`); fixed my helper after an `InvalidSize`.
- Sun (distant, 28° elevation, 40° off the facade normal) + sky dome. First renders were blown out; measured the
  sunlit parapet in the PNG (0.55 linear = expected for albedo 0.76 under sun 0.85 + sky 0.35) and kept those values.

## 5. Golden piece and golden bay: the balcony face (23:33–23:50)

- Pieces (own wrangle each): `bal_wall` (two sliding-door openings with the room floor 0.18 above the balcony,
  15 mm chamfered reveals 0.15 deep, alu frames with sill drip and two tracks, vent hood, AC sleeve, sealant edge
  joints), `sash_L/S` + `screen_L/S` (panels per track, open state per persona, each pane tilted 0.05–0.3°),
  `bal_part` (steel frame, fibre-cement board in two sheets with an H-joint, printed notice lines), `bal_rail_*`,
  `room` (3.9 m deep, persona wall colour, tatami/wood floors, partition, dark doorways, round lamps), `curtain`
  (pleated), `lace`, `furn_0..2`. Parapets became precast panels per bay with recessed sealant joints and overflow
  spouts.
- Props from one persona per flat (`plan_props`): AC units in 3 generations (floor or wall-hung) with duct covers,
  laundry poles with shirts/towels/trousers/sock hangers (thin shells with folds), futons, plant racks, one hero
  green curtain per segment, storage boxes, BS dishes, water heaters, umbrellas and pots in corridors.
  Rates on the default: laundry on 65/110 balconies, AC 73 %.
- Reviews at 9 m (Karma): first pass showed the green curtain stretched into big green cards (non-uniform piece
  scale), the futon reading as a white box, laundry hangers floating, rust dots on laundry poles. Fixed: curtain built
  at bay size with ~300 small leaves, futon as a draped grid shell with sagging hem, hangers to the soffit, poles plastic.
- Cause field (`plan_causes` + `apply_causes`): hotspots with type leak/rust/neglect/impact, power-law radii, leaks
  reach far below their source. **Check:** first version covered 0.8 % of points (radii too small); after 4–14 m radii,
  6 stories per facade and a squared falloff: 15.8 % of facade area above 0.15 and 69 % of the cause mass in the top 20 %
  of area (target 70–85 %). Rendered as colour → `evidence/05_cause_field_south.jpg`: a handful of blobs, no speckle.

## 6. Build-out: corridor face, end walls, cores, roof (23:50–00:10)

- `cor_wall` (steel door with pressed panel, lever, peephole, mail slot; louvred meter door; frosted windows behind
  vertical-bar grilles; nameplate, intercom; gas and water pipes along the top), `cor_lamp`, `dpipe`.
- End walls: precast panel grid per floor and per zone with 15 mm recessed joints, raw plinth, coping with overhang,
  corner downpipe with brackets every 1.8 m and a shoe, vent caps per floor; building number from the Font SOP
  (Python expression on the HDA parms, `号棟` optional), triangulated, painted 3 mm proud on both outer gables.
- Cores: stair towers with breeze-block screens (花ブロック), slot windows, flights and landings inside, entrance canopy,
  roof-access penthouse door; original lift (blank shaft, joints, machine-room louvres); retrofit lift (clad shaft on
  bridges, glass strip). Lib tags now carry a local→world transform so the wall helpers work facing any direction.
- Roof: FRP panel tank on a braced stand with deck, rail and ladder; older cylindrical steel tank; antenna masts with
  Yagi arrays and guy wires; roof vents; lightning rod.
- Facade-level review at 65 m and 35 m: banding and laundry read, but weathering was invisible at distance. Rebuilt the
  concrete shader stack (macro wash ±8 %, washed top floors, cause-driven grime ×2.6, north-face grime and biofilm,
  stronger streaks at joints/spouts/leaks). Gate image `evidence/04_facade_35m_gate.jpg`.
- Slowed down: a 1600×900 Karma look takes ~6 min and blocks Houdini (an `hda save` was refused as busy meanwhile);
  later evidence is rendered at 1280×720.

## 7. Game outputs: LODs, collision, export (00:06–00:16)

- LOD1 (`plan_l1` renames plan points to stand-ins, `kit_l1`, `conn_l1`): openings become a shallow recess with one
  window quad coloured per flat; partitions, AC units, rails as boxes/quads; laundry as two-sided cards; no interiors.
  LOD2 (`shell_l2`): flat banded shell (parapet band / painted recess band), boxes for cores, tank box, number kept.
  LOD branches are tagged `lod`, picked by a Switch (`lod` parm: 0, 1, 2, all), so unused branches do not cook.
- **Counts (default 10×11):** LOD0 506,878 tris, LOD1 24,908 (4.9 %), LOD2 490.
- **Value match** (same camera at ~210 m, ground hidden, mean linear luminance over the south face mask):
  first LOD2 was +8.1 % (flat painted recess is sunlit where the real recess is shadowed — the skill's warning);
  0.125 → −3.9 %; interpolated 0.155 → **−0.1 %**. LOD1 −2.4 %. `evidence/09_lod_value_match.jpg` (LOD0 | LOD1 | LOD2).
- Collision: one box per segment, per core and for the tank, named `UCX_<mesh>_NN` (mesh name parm), group `collision`.
- World-scale box UVs (1 uv = 1 m), vertex normals (cusp 40°), groups `lod0/lod1/lod2`, `path` attribute for FBX
  hierarchy, triangulate toggle.
- **Export check:** `rop_fbx` per LOD to `export/` (LOD0 20.7 MB with hulls, LOD1 0.8 MB, LOD2 58 KB), re-imported with
  File SOPs: LOD0 506,938 tris = 506,878 render + 60 hull tris; names `danchi`, `UCX_danchi_00..04`; `uv` and `N` present;
  material slots by name. Found one bug this way: insect screens referenced a non-existent `screen` material → added.
- Slowed down: `hda create` had nested my tabs inside "Standard"/"Spare" folders; rebuilt the definition's parm template
  group from `py/parms.py` so the six tabs are top level.

## 8. Variation sheet (00:16–00:21)

- 9 instances (3 styles, slab/stepped/staggered, 4–14 floors, 6–18 units, original and retrofit lifts, `号棟` format,
  3 fully seed-driven). Seed-driven ones resolved to greypc-stepped, pastel-staggered, pastel-stepped.
  `evidence/07_variation_9up.jpg`. Silhouettes, heights and colourways differ at skyline distance; the yellow pastel
  accent and the grey precast style separate well from cream.

## 9. Geometric damage, LOD0 only (00:21–00:36)

- Followed `procedural-mesh-damage`: damage where the cause is (rust and impact hotspots of the cause field), clustered,
  a random 35 % of qualifying bays keep background wear only. Balcony slab bays inside a hotspot are emitted closed by
  `conn_slabs`; `dmg_cutters` makes one dominant spall (size by cause strength), 3–7 satellites (power law, 0.3–0.5×)
  and 1–3 background chips, all clear of the bay seams; big spalls expose two rusty rebars at 35 mm cover.
  Fuse → Boolean subtract (cut faces grouped `spall`, textured as raw aggregate).
- **Validation** (`damage_validate.vfl` from the skill): open edges 0, non-manifold 0, unchanged 0, 96 → 666 tris,
  3 damaged bays in the default building (all inside the south-face rust cluster).
- Rust runs added to the concrete shader from `c_rust` (and rust now runs down in the cause field), so the spall, the
  stain and the rusty rails nearby read as one cause. `evidence/06_damage_spall_rust.jpg`.
- Slowed down: `mix()` is not VEX (`lerp`), and a failed call rolled back the whole damage build; the first damage
  test found no bays because I sampled only bay centres while the hotspot sat on a bay boundary (now 5 samples per edge);
  a new shader node reused the name of the `c_rust` primvar reader and the material rebuild rolled back.

## 10. Presentation context and evidence (00:36–01:18)

- Context (`/obj/context`, not part of the asset): base ground, patched asphalt road with kerbs and lines, planting strip,
  hedges, gravel splash band, paved north forecourt, 11 m concrete utility poles with crossarms, transformers and
  sagging wires, 16 trees, a bike shelter, a netted garbage station. Sky: a Copernicus lat-long gradient
  (`tex/sky.png`) on the dome light, visible to camera. Three more asset instances at LOD1 as the rest of the estate.
- Trees first came out as giant faceted octahedra (toy-like) → canopies of 170 small clumps on an ellipsoid shell.
- Hero street view at eye height 1.6 m, 24 mm, level camera with lens shift (`winy`) so verticals stay straight:
  `evidence/10_hero_street.jpg`.
- Golden piece at arm's length (`02_golden_piece_closeup.jpg`): first framing landed on the hero green-curtain balcony
  whose leaves read as paper diamonds at that distance → leaves are now folded along the midrib, smaller, denser.

- Golden bay gate at 9 m with presentation props hidden (a context tree sat in front of the camera):
  `03_golden_bay_9m.jpg`, grayscale `03b_golden_bay_grayscale.jpg` (value 5/25/50/75/95 %: 0.22/0.34/0.84/0.95/0.99 —
  bright parapets against dark recesses, the banding that names the style).
- Kit sheets: the first grid layout was unreadable (3 m tanks and 0.4 m sock hangers in equal cells) → packed rows
  sized per piece, architecture and props separately: `08a_kit_sheet_architecture.jpg`, `08b_kit_sheet_props.jpg`.
- Corridor side `11`, gable `12`, rooftop `13` (first try showed the roof finish blown out white — its colour role
  was never mapped — and aimed at the penthouse without the tank; fixed both), estate from a block away `14`.
- Antennas raised to 2–5 per segment (roof looked bare).

## 11. Packaging and final checks (01:18–01:24)

- Cost of switches, measured by cook counts after a seed change: LOD1 and LOD2 cook only their own branch;
  `damage` off used to cook an empty Boolean → added a `damage_on` switch, now the branch does not cook.
  Interiors and props off: LOD0 487k → 298k tris.
- Connective geometry now gets `name = conn_<part>` (26k tris had no piece name).
- Help page written into the definition (`work/help.txt` → `Help` section), comment set, definition saved and the
  master instance locked (`matches_definition: true`).
- **Fresh instance from the saved library** (after `hda reload`): no errors or warnings, 505,762 tris, identical to the
  master, all parms at defaults.
- FBX re-exported from the final asset and re-imported: LOD0 505,822 = 505,762 + 60 hull tris (`UCX_danchi_00..04`),
  LOD1 24,880, LOD2 490; `uv` and `N` present; 16 / 9 / 5 material slots.
- All evidence JPGs under 400 KB (largest 207 KB). Removed my superseded sparse kit sheet. Scene saved as
  `work/danchi_v005.hiplc`.

## What slowed me down (summary)

1. Karma looks block Houdini: 1280×720 at 32 samples took 1–3 min, 1600×900 about 6 min; an `hda save` was refused
   while a render ran. Long renders were started with `wait_s: 0` and I wrote docs meanwhile.
2. VEX traps: no `struct` in wrangles, `function` keyword for array returns, ambiguous `set()`/`point()` inside
   `array()`/`append()`, `mix` is `lerp`, functions must precede statements and cannot see snippet locals.
3. A failing `houdini_python` call rolls back everything it did, including earlier successful steps in the same
   script (twice I lost a whole build step to one late exception).
4. `hda create` wrapped my interface into "Standard"/"Spare" folders; fixed by setting the definition's parm group.
5. MaterialX parm names carry the signature suffix (`in2_vector3`) and node names inside a builder must be unique.
6. Packed instances lose inner materials through the Karma scene import → mesh output by default.
7. Weathering that looked right at 9 m vanished at 35–65 m; it took three passes (cause radii, falloff, shader gains)
   and a cause-field visualisation to get clusters that survive distance.

## 12. Close (01:25)

- Scene saved (`work/danchi_v005.hiplc`), asset saved and locked, then `houdini_connect {quit: true}`.
