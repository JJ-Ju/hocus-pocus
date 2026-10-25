# Danchi generator — work log

Output root: `sk2-out/` (scene in `work/`, asset `danchi.hdalc`, images in `evidence/`).
Method: the `procedural-assets` skill (contract → skeleton → golden piece → golden bay →
build-out → facade/building/block levels → LOD/collision → package → review), with the
`procedural-materials` and `procedural-mesh-damage` skills for surfacing and wear.
Houdini driven only through the `mcp__hocuspocus__*` tools.

## Timeline

### 17:56 — Setup
- Loaded the `procedural-assets` skill and read all five reference files
  (recipes, metrics, architecture, surfacing, game output).
- Created `work/`, `work/vex/`, `work/py/`, `evidence/`.

### 17:56 — Connect
- `houdini_status`: nothing running. `houdini_connect {launch: headless}` → Houdini 22.0.466,
  pid 8284. Saved `work/danchi_v001.hiplc` immediately (a launched Houdini dies with the server).

### 17:58 — Phase 0: brief and de-risk
Why: the skill says to de-risk anything that would force a redesign before building.
- `search types`: SideFX Labs not installed (no LOD Create / Impostor Baker). PolyReduce,
  Convex Decomposition, Font SOP, `rop_fbx` SOP, `copnet` and `matnet` in SOP context exist.
- Test scene `/obj/derisk` (script `work/py/derisk.py`, `derisk2.py`): MaterialX materials in a
  matnet inside the geo, Copy to Points packed instances with per-point Cd, a Font SOP with
  `12号棟`, a copnet texture read through `op:`.
- Check 1 (Karma `look final`): text renders in Japanese. ✔
- Check 2: materials did not appear at first. Cause found with a Scene Import LOP: my
  `shop_materialpath` was empty because I set the Copy to Points `applyto1` menu by index (1 =
  verts), so the string landed on vertices. Fixed (`prims`). **Slowed me down ~5 min.**
- Check 3: 4 materials side by side: `geompropvalue "Cd"` → black, `"displayColor"` → works,
  `op:` checker texture → works, constant red → works. So shaders must read `displayColor`.
- Check 4: Houdini polygon winding: points CCW (right-hand +Z) give normal −Z. Recorded for the
  VEX box helpers.
- Wrote `README.md`: brief, signature features, contract (3.0 m floors, 6.0 m bays, 8 m body,
  1.5 m balcony/corridor), pivots, joins, piece list by level, triangle budgets, de-risk results.
- Removed the test geometry.

### 18:03 — Phase 1: contract
- Fixed metrics in README (grid 0.5 m; floor 3.0 m; bay 6.0 m; body 8 m; balcony and corridor
  1.5 m; parapet 1.1 m; gable 0.3 m; towers 3×5 m and 3×3 m; 2 cm chamfer) and one pivot
  convention: bay pieces at bay centre / facade plane / floor level, local +Z out of the
  facade; the corridor side reuses the frame rotated 180°.
- Code layout: `work/vex/lib.vfl` (contract constants, `face()` with the measured winding,
  `pbox`, chamfered `bbox`, `frame`, `prism`), `work/vex/plan.vfl`, one file per piece family
  in `work/vex/pieces/`, `work/py/build.py` (builds the network, `reload()` re-reads VEX).

### 18:05 — Phase 2: functional skeleton
- Spare-parm interface on `/obj/danchi/gen` with one `edit` call (folders Massing, Style,
  Variation, Weathering, Output; menus as int; `disable_when` conditions).
- Network: `plan` (detail wrangle) → `kit` subnet (one wrangle per piece, merged into
  `KIT_ALL`) → `kit_lod0` (blast by `lodmask`) → `place_lod0` (Copy to Points 2.0, piece
  attribute `name`, packed, target attribs listed) → `unpack0` → merge with `connective`
  (gables, roof slab, plinth) → `colour` → `OUT`.
- Problems hit (each a few minutes):
  - VEX has no `>>` shift operator → rewrote corner indexing with `/` and `%`.
  - Vector literals cannot hold variables (`{1.4, hs, 1.0}`) → `set()`.
  - `addprimattrib` default did not name prims created in the same wrangle → `tag()` writes
    `name` from a `piece` spare parm.
  - `look {fit: all}` framed a tiny building → wrote `work/py/scene.py: frame()` to aim a
    camera at a SOP's bbox.
- Checks:
  - Plan counts at default (10F × 10 bays): 100 balcony, 100 corridor (40/30 mirrored/30
    tower connections), 20 roof edges, 2 stair towers + lift (lift auto from 6F), 1 tank,
    props 105. Detail attribs carry floors/units/style/length/y_roof.
  - Footprint check (`work/py/checks.py`): every bay, roof and tower piece inside its
    contract box. ✔
  - Stress cases: 4F×3, 14F×24 (stairs every 6 + lift), 5F×7 (base 1.0, tank on stand).
    **Found a kit-logic bug**: 3 bays got two end towers covering the corridor face. Fixed in
    the plan rule (≤5 bays → one central stair) rather than patching.
  - Noted: tower ground pieces must reach grade for any base height (handled in detailing).
- Evidence: `evidence/01_skeleton_contact.jpg`. Saved `work/danchi_v002.hiplc`.

### 18:15 — Phase 3: golden piece (balcony bay `bal_bay_01`)
Why this piece: the south balcony face is what the player and the anime frame see most.
- Forms in three size classes: primary (wall, slab, parapet), secondary (coping and slab
  edge band standing 1 cm proud, window openings with 6 cm reveals, partition board in a
  steel frame), tertiary (sash stiles, vent hood, AC sleeve, drain spout, downpipe).
- Edge strategy for the kit: 2 cm chamfer (`bbox` helper, 44 tris per box) + face-area
  weighted normals (Normal SOP, cusp 50°, weighting `area`) added to the kit subnet.
- LOD1 version in the same wrangle (`lodmask` 2): plain boxes, glass at the same depth.
- Checks: triangles LOD0 940 (`bal_bay_01`) / 1,532 (`bal_bay_02`, railing; trimmed
  balusters 52→47 to meet the 1,600 budget) ; LOD1 88 / 100. Footprint check flagged the
  drain spout 5 mm proud → contract amended: fixtures may stand ≤1 cm proud of the facade.
- Draft look caught smooth shading across hard edges (no normals yet) → fixed with the
  weighted Normal SOP. Review blast `kit/review_lod0` shows one piece's LOD0 only.

### 18:18 — Surfacing (procedural-materials skill)
- `work/py/tex.py`: Copernicus copnet `gen/textures` inside the generator, 2 m tiles at
  1024 px (= 512 px/m contract density): spray-tile paint over formed concrete (stipple,
  formwork rhythm, sealed tie holes, sparse hairline cracks), bare concrete (cop_lib
  template, tie holes, leaks), roof pavers (moss), steel paint + rust mask, FRP tank panels.
  Looked at each map. Fixed: tie holes stretched to ellipses (non-square cells — the trap in
  the skill) → 4×4 grid; roof moss too blobby → smaller and weaker.
- `work/py/mat.py`: MaterialX materials in `gen/materials` (paint, concrete, roof, steel,
  glass, alu, dark, cloth, plant, plastic, frp). Colour from `displayColor`; textures via
  `op:`; weathering in the shader from world position plus per-face primvars written by
  the colour stage: `stop` (where water starts on that face), `slen` (streak length),
  `wexp` (exposure), `glow` (lit dwelling / corridor lamp). Streaks = vertically stretched
  fractal × fall-off below `stop` × exposure × a patch mask; splash band at the base;
  low-frequency grime; macro tone. Weathering amounts are channel-linked to HDA parms.
- `work/vex/colour.vfl`: three curated palettes (kodan70 cream, kodan80 white+terracotta,
  toei grey+blue) with a seed-picked accent; per-bay repaint value (±2.5 %) from the stable
  unit id; window panes per unit (curtain colours, open panes showing a dark room, insect
  screens, vacant units bare); frosted kitchen/bath glass; shop_materialpath via
  `opfullpath("../materials")`.
- `work/vex/uv_world.vfl`: box-projected world UVs in metres after unpacking.

### 18:22 — Golden bay (L2) lit review, iterations
- v1 (`work/tmp/bay_v1.png`): read as a danchi, but overexposed cream, streaks on every
  parapet at the same density ("uniform detail" failure), skeleton prop boxes.
  Fixes: wall albedo down ~6 %, sun 1.6→1.25 and sky 0.9→0.75, streak patch mask
  (fractal at 0.05–0.09 /m, smoothstep) so whole stretches stay clean, sharper streaks.
- Props rebuilt: laundry pole on soffit hangers with garments, peg hanger; AC unit floor
  or wall-hung (plan chooses wall-hung where a concrete parapet would hide it); futon over
  the coping; pots with a plant that peeks over the parapet; BS dish.
- v2 (`work/tmp/bay_v2.png`): garments read as paper cards in candy colours, futon as a
  white sign, AC casings and PVC downpipes rusting like bare steel. Fixed: cloth as two
  splayed panels + sleeves, muted laundry palette (whites, greys, navy), soft quilted futon
  with piping, AC and pipes moved to a plastic material.

### 18:30 — Phase 5: build-out of the kit
- Corridor bay (deep-set steel door with frame, handle, mail slot, nameplate, bell;
  louvred meter-box door; frosted kitchen and bath sliders behind steel grilles; water
  heater vent; parapet + coping + steel top rail; soffit lamp that glows at night;
  mirrored variant via `mb/mp/mq` helpers; `conn` variant opens 1.8 m onto a tower).
- Roof edge (eave slab, band, parapet, aluminium coping, drain), stair tower (side
  openings at mid-landing, breeze-block lattice screen, two 9-riser flights, landings,
  entrance with canopy/platform/steps on the ground floor, penthouse with roof door),
  lift tower (recessed doors, indicator, accent stripe, machine room with louvres), FRP
  tank on a braced steel stand (ladder, manhole, vent, overflow), Yagi antennas, vents.
- End-wall number: Font SOP (bundled WenQuanYi), PolyExpand2D +7 cm for a bold painted
  look, Divide, both gables; text from the plan's `bnum` (seeded when Number = −1).
  Font LOD 1.0→0.35 cut it from 11.4k to 4.2k triangles.
- Problems: a bash heredoc broke on quoting → wrote files with the Write tool instead;
  functions defined after statements in a snippet → moved the mirrored helpers into
  `lib.vfl`; Font `valign` token is `middle`; vector×float multiply parm is `in2`.
- Checks: footprint report all `ok` after documenting proud bands/steps; LOD0 triangles per
  piece: corridor 1,432 (budget raised to 1,500, see README), stair floor 1,024, lift 348,
  tank 648/768, antenna 296. Default building (10F × 10) LOD0 ≈ 300k triangles.
- Renders `work/tmp/hero_v1.png` (south-east) and `nw_v1.png` (north-west): the banding,
  laundry, towers with lattice screens, lift tower and `11 号棟` all read. Found: doors look
  rust-orange (rust mask too generous → threshold now 1 − 0.4·rust), number too thin
  (→ bold + 3.8 m), ground too pale (→ presentation ground: grass, asphalt road, path).

### 18:38 — Phase 7: LODs and collision
- LOD1 = the `lodmask` 2 geometry inside every piece (no props, plain boxes, glass at the
  same depth) placed by its own Copy to Points; LOD2 = `work/vex/lod2.vfl`, a banded shell
  from the plan (light parapet strip + dark recess strip per floor on both long faces,
  gables, roof, tower and tank boxes). Normals on generated geometry (merging prims with
  and without vertex N would have zeroed them). `lod_switch` (0/1/2/All with groups
  `lod0/lod1/lod2`) feeds one colour + UV stage.
- Triangles (10F × 10): LOD0 304,418 · LOD1 17,474 · LOD2 154. Collision: 5 convex boxes
  `UCX_danchi_00..04`, group `collision_geo_ucx`, on a second output.
- Value match (skill: render each LOD from one camera): `cam_far` ~250 m, measured facade
  luminance with PIL: LOD0 160.6, LOD1 168.8 (+5 %), LOD2 187.9 (+17 %, its recess strips
  are sunlit while LOD0's recess is in the slab's shadow). Recess value 0.34 → 0.13 gave
  LOD2 162.0 (+0.9 %). Evidence `evidence/07_lod_value_match.jpg`.

### 18:44 — Mesh damage (procedural-mesh-damage skill)
- End walls and plinth only (unique per building, where people and vehicles pass):
  `chip_points.vfl` from the skill (local change: `max_height` 2.6 m keeps chips in the
  contact zone, 2 % weathering chips above; skip edges on the ground), noisy divided-box
  cutters copied **unpacked**, `boolean::2.0` subtract with `binsidea` → cut faces tagged
  `crole chip` (bare concrete). Seeded by the asset seed; toggle + amount on the HDA.
- First try: 2,681 chips / 143k triangles — the 4 cm chamfer doubles each convex edge and
  the whole 30 m gable height qualified. After the contact-zone rule and 0.8 m spacing:
  214 chips, 13k triangles, 0.15 s.
- `damage_validate.vfl`: open_edges 0, nonmanifold_edges 0 (1 in the first, denser run),
  unchanged 0, bbox_shrink 0, zero_uv_prims 0 (UVs are projected after damage anyway).
- Close-up `work/tmp/corner_v1.png`: chips read along the gable corner and plinth edge.

### 18:50 — Phase 8: packaging
- Packed output branch (`packed` toggle): kit coloured and UV'd in piece space, copied as
  packed instances (387 at default) + generated geometry as mesh. Per-pane curtain
  variation is lost in this mode (instances share geometry) — documented.
- Optional input 0 = world-space override points (`plan_override.vfl`: `remove`, `piece`,
  `lit`, `occ`, filtered by `role`, radius `pscale`); every plan consumer re-wired to it.
- Outputs: `output0` building, `output1` collision.
- `hda create` → `jj::danchi::1.0` in `sk2-out/danchi.hdalc` (Indie → .hdalc), 31 parms
  promoted with folders and conditions, help text; `hda save lock: true`.
- Gate checks on a fresh instance `/obj/danchi_test/danchi1` from the library:
  no errors, no warnings; override test removed bay id 3040 (98 + 1 balcony bays of 100)
  and swapped id 5060 to `bal_bay_02`; collision output 30 prims (5 boxes).
- Toggled-off branches cost nothing (cookCount before/after a seed change, inside the
  locked asset): LOD0 cooks plan, place_lod0, unpack0, damage, colour, uv (212 ms); LOD2
  cooks only plan, lod2, colour, uv (2 ms); damage off leaves dmg_* idle (93 ms); LOD1,
  packed and collision branches stay idle unless selected.
- `cook profile` on a locked asset only reports the asset as one node (as the skill warns),
  hence the cookCount method. Saved `work/danchi_v007.hiplc`.

### 18:52 — Phase 9: evidence and final review
- Presentation setups outside the asset (`work/py/present.py`): `/obj/kit_sheet` (object
  merge of the asset's internal coloured kit, laid out by piece) and `/obj/estate` (nine
  instances, seeds 1–9, massing + style from seed; floors 5–14, bays 6–15, all three
  styles, numbers 1–32).
- Arm's-length close-up showed window panes as flat colour cards → added curtain pleats
  (triangle wave on curtain panes only, flagged by a new `fold` primvar) in the glass
  shader; re-rendered.
- Kit sheet showed meter doors and tank stands covered in rust blotches → the grunge rust
  saturates over large areas; remapped it sparse in Copernicus and rebalanced the shader
  threshold (two iterations: first pass too sparse).
- End-wall close-up showed the 号棟 suffix as mojibake (`å·æ£Ÿ`): my builder had
  `.encode().decode("unicode_escape")` on an already-Unicode string. Set the text directly;
  re-rendered the hero and north views that carried the bad suffix. **Slowed me ~5 min.**
- Night: sky swapped to a dark gradient, sun off, `night` 1 → flats lit in floor runs,
  corridor lamps per door. Daylight restored after.
- Converted every render to labelled JPGs with PIL (`work/py/sheet.py`), all under 400 KB
  (largest 360 KB). Looked at each; damage reads but is subtle, so 12 includes a 2.5× crop.

### 19:22 — Game export check
- FBX ROP SOP in `/obj/danchi` (mesh `path=/danchi` + collision `path=/UCX_danchi_NN`,
  build hierarchy from path). First export was 13 KB: the collision wrangle was wired to
  output 0 (the edit op's `from_output` did not take) and paths lacked a leading `/`.
  Fixed both → LOD0 5.3 MB.
- Re-imported each FBX with `hou.hipFile.importFBX`: LOD0 `danchi` 316,960 tris + 5 `UCX_`
  boxes, 11 material slots, UVs. **LOD1 came back at 30k** — it carried the 13k-triangle
  damage chips. Fixed in the asset (LOD1 uses an undamaged connective branch) → 17,176.
  LOD2 154. Texture maps written to `export/tex/` (normals/height 16-bit raw).
- Re-saved and locked the HDA after each internal change (unlock → edit → save lock).

## What slowed me down (summary)
1. Copy to Points `applyto` set by index landed strings on vertices (materials vanished).
2. VEX: no `>>`; vector literals can't hold variables; helper functions must come before
   statements; inline `array()` ambiguity avoided by typed locals.
3. Prim names: `addprimattrib` defaults did not apply to prims created in the same wrangle.
4. Unicode double-decoding in the font suffix (caught only at a close render).
5. Damage first pass far too dense because chamfered boxes double convex edges.
6. LOD1 inheriting LOD0-only damage (caught only by the FBX re-import check).
7. Bash heredoc quoting broke once; switched to the Write tool for VEX files.
8. Karma final looks take 25–60 s each; ~30 renders in total were the largest time cost.

### 19:27 — Wrap-up
- `inspect problems /obj`: none. `hda info`: 31 parms in 5 folders, 9 conditionals, help,
  11 instances, locked and matching the definition.
- Final scene saved as `work/danchi_final.hiplc` (main building visible; kit sheet, estate
  and override test hidden). Then `houdini_connect {quit: true}`.
