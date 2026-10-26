# Danchi generator — work log

Output root: `sk4-out/` (scene in `work/`, asset `danchi.hdalc`, images in `evidence/`,
VEX in `vex/`, build scripts in `scripts/`).

## 0. Preparation

1. Loaded the `procedural-assets` skill and read its references (recipes, generator
   architecture, metrics and kits, believability, surfacing, game output) plus the
   `procedural-materials` and `procedural-mesh-damage` SKILL.md files. Why: the skill fixes the
   order of work (contract → skeleton → golden piece → golden bay → build-out → levels → game
   outputs → package) and lists the HocusPocus traps found on earlier generators (Copy to
   Points with no target attributes, packed instances losing materials, `displayColor` vs
   `Cd`, camera near clip, Karma intensities).
2. Read my memory note for machine facts: Houdini 22.0.466, Indie licence → `.hiplc`/`.hdalc`.
3. Created `work/`, `evidence/`, `vex/`, `scripts/`.

## 1. Session and de-risk (Houdini 22.0.466 headless, pid 20604)

4. `houdini_status` → nothing running; `houdini_connect {launch: headless}`; saved
   `work/danchi_v001.hiplc` at once so `$HIP` is the work folder.
5. De-risk checks (why: each one would force a redesign if it failed):
   - `houdini_python` listing node types: Font, PolyBevel 3, PolyReduce 2, Convex Decomposition,
     Copy to Points 2, all MaterialX noise/bump nodes present. **SideFX Labs not installed**
     (no LOD Create / Impostor Baker) → LODs built by the generator itself.
   - A throw-away SOP asset (`work/derisk_test.hdalc`) with a matnet inside, a box and a Font
     SOP「12号棟」, bound with `shop_materialpath` from an `opfullpath("../materials")` spare parm.
     `look final` (Karma) showed the Japanese glyphs and the displayColor; switching the material to
     glossy metal turned the box black against the dark environment → the binding is real, not
     Karma's default display colour. Uninstalled and deleted afterwards.
   - Polygon winding: a quad CCW seen from +Z gets normal −Z in Houdini → library writes
     right-hand order then reverses.
6. Wrote `README.md`: brief, signature features, metrics contract, piece list by level, budgets,
   de-risk results (gate 0/1 of the skill).

## 2. Generator source (plan → kit → instance → connective → assembly)

7. `vex/lib.vfl`: tag helper, box, chamfered box (24 pts, closed), profile prism with per-edge
   tags, cylinder, wall-with-openings grid (shared points, reveals, grooves, framed by a matrix),
   frame, folded curtain, shared bay layouts (`bal_layout`, `cor_layout`) so pieces and plan agree.
8. `vex/plan.vfl`: one point per placed piece. Building seed → palette (5), parapet style
   (solid/rail/mixed), cores (stairs at the ends or one bay in, centre stair ≥ 12 bays, lift ≥ 6
   floors), number. Life seed → one **persona per flat** (tidy, family, elderly, gardener, vacant)
   that picks curtains, sash state, AC model, laundry, futon, plants, storage, dish and corridor
   clutter together. Weather seed → cause hotspots per facade (leak, rust, neglect, damp; one
   dominant; corner bias) and repaint patches.
9. Kit pieces as separate wrangles (`pc_bal_wall`, `pc_bal_front`, `pc_bal_part` + curtains,
   `pc_cor_wall`, `pc_cor_front`, `pc_misc` (pipes, plinths, roof edges), `pc_props`), each emitting
   its LOD0 and LOD1 geometry tagged by `lod`.
10. Connective generators: `gen_gable` (joints, end-unit windows, hoods, corner downpipe, coping),
    `gen_roof` (surface + joint strips, drains, FRP panel water tank on a braced stand with ladder,
    Yagi antenna cluster all aimed one way, lightning rods), `gen_towers` (stair tower with real
    flights and staggered half-landing openings, lift shaft with doors + machine room), Font SOP
    number copied onto both gables, `gen_lod2` (shell), `gen_collision` (UCX boxes).
11. Assembly: prop yaw → Copy to Points (piece attribute `name`, pack off, plan attributes applied
    to prims) → colour resolve → weathering primvars from the cause field → imperfection (band
    lippage and sag, glass pane tilt, height-above-floor for rust) → world tiling UVs → vertex
    normals (cusp 35°) → material binding → LOD split → switch/triangulate → outputs (render,
    collision).
12. `scripts/build.py` builds the whole network from the .vfl files (reproducible).

### Slowdowns so far
- **VEX structs are rejected inside wrangle snippets** ("unexpected struct"): functions are hoisted,
  struct definitions are not. Switched the tag type to `dict` everywhere (one regex pass).
- `ident()` passed directly as a function argument is ambiguous → declare a typed local first.
- Two tower faces were built with a mirrored matrix (det −1) which would flip normals; caught by
  reasoning before the first cook.
- Rebuilding the interface: folder template names must be removed by every contained parm name.

13. First full cook: all 21 wrangles compile; 444k points / 361k prims across all LODs (default
    8 floors × 10 flats). First draft look shows the danchi read (bands, laundry, number "22").

## 3. Skeleton gate, budgets, materials, look-dev

14. **Skeleton gate** — `inspect geo group_by name` on `lod0`: every piece name present with sane
    counts and bboxes (e.g. 80 corridor walls split 40/40 between `cor_wall`/`cor_wall_m`,
    `bal_part` only from bay 1 on, roof edges only at floor F, towers only at their bays).
    LOD0 was **~650k triangles** for 8×10 → over the 450k budget. Cause: 26-face chamfered boxes
    on 2–3 mm chamfers (sash, grille, louvre parts). Rule added to `cbox`: chamfers < 3.5 mm become
    plain boxes (invisible at bay distance). LOD0 → **406k triangles**.
15. `scripts/mats.py` builds 19 MaterialX materials inside the asset's matnet. All layers read
    primvars from the generator (displayColor, stop, slen, wst, wgr, wdamp, wbase, wtint, wrust,
    hfl, emit, duv, dstr) in object space, so they move with the asset.
16. `scripts/scene.py`: presentation scene outside the asset — Karma sun (distant, 26° high, 38°
    off the south normal), sky env light, ground (asphalt, grass verge, path, kerbs), three
    utility poles with catenary wires, cameras with look-at nulls (near clip 5 cm).
17. Look-dev loop (each step a Karma `look` and a critique):
    - Golden bay close-up #1: overexposed (whites clip) → sun 2.6→1.3, sky 0.9→0.5.
    - Street view: reads as a danchi; facade too clean; hero camera missed the gable → moved.
    - Corridor/gable/roof drafts: geometry correct (accent bands, lift shaft stripe, stair tower
      landings, tank on braced stand, penthouses, antennas, gable "22").
    - Weathering invisible at distance (estimated ~3 % darkening) → stronger streak/grime/base
      terms in VEX and shader.
    - Gable streaks then too orange and evenly spread like a fringe → dirt blends toward an
      absolute soot colour (no orange multiply); the streak cluster mask now varies only
      horizontally (dirty columns, clean columns); per-column streak length variation.
    - Laundry read as paper cards → whites lowered to cotton albedo, deeper folds, the big flat
      sheet removed; futon rebuilt as a pillowed soft sweep with rounded ends and drooping hem.
    - Gable needed streaks that start at features → new `gen_decals` stage: streak quads below
      exhaust hoods, drain spouts (onto the parapet below), rail post bases (rust), stair-tower
      sills; each source fires with probability 0.15–0.35 + cause field → clustered (63 decals).
    - Wall palette dimmed ~5 % to aged-paint values.

## 4. LODs

18. LOD1 first measured 71k triangles (17.5 % of LOD0) → `group_by part` showed chamfered rails
    (22k) and meter-box louvres (11k) leaking into LOD1 → LOD0-only, with plain-box stand-ins.
    LOD1 = **42.5k triangles (10.5 %)**, LOD2 = **214 triangles**.
19. **Value match** (same camera at ~100 m, Karma, mean luminance over the facade crop, measured
    with PIL): first pass LOD1 −4.3 %, LOD2 +6.7 % (and +23 % chroma: LOD1 window cards took the
    saturated curtain colour). Fixes: LOD1 cards = mostly glass grey with a hint of curtain,
    tuned 0.95→0.52; LOD2 recess 0.5→0.36 and 30 % desaturation. Final: **LOD1 +0.7 %,
    LOD2 +1.5 %** (target ±3 %).

## 5. Packaging and validation

20. `hda create` → `danchi::danchi_gen::1.0` in `danchi.hdalc` (0 inputs, 2 outputs: render, collision),
    30 promoted parms in 6 tabs, help text, conditionals (life parms disabled when props off).
21. **Package gate** — fresh instance in `/obj/fresh_test` from the saved library: cooks with no
    errors/warnings, binds to its *own* 17 materials (`opfullpath` root), collision output =
    `UCX_danchi_00..02`, props toggle off drops 20k prims.
22. Stress sizes on the fresh instance: 4×3, 4×4, 5×16, 6×4, 14×16, 14×3, 4×8 (forced lift),
    10×7 (stairs only): all cook with no errors. Found: two stairs in adjacent bays on 4-flat slabs
    and the lift next to a stair on short slabs → rewrote core placement (one stair ≤ 5 flats; lift =
    nearest free bay to a seeded target, not adjacent to a stair). Re-checked all sizes.
    Scale: LOD0 ≈ 5k triangles per flat (406k for 8×10, 1.1M for 14×16).
23. **Slowdown:** `hda info` listed repeated folders → the definition held 47 empty tab folders left
    by early interface rebuilds (removing parms by name leaves their renamed folders). Rebuilt the
    definition's parm template group with only the 6 populated tabs. `build.py` now skips the
    interface for an asset instance and only unlocks + rebuilds contents.
24. **Slowdown:** the profiler treats a locked asset as one node (0.1 ms) — no reliable cook time
    from it, so none is claimed.

## 6. Variation, presentation, weathering clustering

25. 9-up at ~100 m with nine seeds: palettes/parapets/roof kit/laundry/weathering differ but the
    accent colour only showed on the north side → added seed-driven balcony accents (parapet stripe
    variants `bal_front_*_a`, tinted partition boards `bal_part_a`) and seed-driven lift placement.
26. Presentation (`scripts/context.py`): lat-long gradient sky made with PIL, 8 zelkova-like trees
    (tapered trunk, limbs, leaf-card clusters with gaps), second block (asset instance, seed 5,
    5×8) in the background, sidewalk + road markings + mesh fence; street camera level with lens
    shift (`winy`) so verticals stay straight.
27. **Clustering gate** (cause field rendered as colour + area statistics on facade prims):
    first measure — hotspots covered 10–14 % of the area but held only 14–25 % of streak/grime
    weight (uniform background dominated). Fix: lower background, stronger hotspot terms, radii
    ×1.4, shader streak gate reads the cause field; north face background ×1.7 (orientation bias).
28. Gable then showed a hard-edged dirt rectangle bounded by joints (per-prim terms on big cells)
    → hotspot terms moved to **per-point** attributes (`pst`, `pgr`, `pdp`, `prs`, `hotp`),
    per-prim keeps only exposure background. Final: **20 % of facade area holds 45 % of streak
    weight (~73 % after the shader's cause gate) and 54 % of grime**.
29. Night: lit rooms were invisible behind curtains → lace/drapes of lit flats emit (backlit
    glow), room lamps ×2; corridor lamps on.
30. Golden bay close-up re-aimed into the strongest south leak hotspot (looked the hotspot list up
    from the plan's `hs_P`) so the beauty shot shows a story, not a quiet zone. In it the streaks
    read as evenly spaced drips → a second, broader column noise groups them into clumps; leak
    strength 4.2 → 3.4.
31. Corridor close-up likewise re-aimed at the north damp hotspot (ground floor, x ≈ 8).

## 7. Game outputs

32. Export (`/obj/export`): three asset instances (LOD0/1/2, triangulated) → path attribute
    `danchi_lodN`, LOD0 also gets the collision output renamed `UCX_danchi_lod0_NN` → ROP FBX per LOD
    with Build Hierarchy from Path → `export/danchi_lod{0,1,2}.fbx`.
33. **Re-import check** (File SOP): LOD0 329,976 tris + 4 UCX meshes, LOD1 38,800, LOD2 214;
    17 material slots; but `Cd` came back per polygon and the weathering primvars are Houdini-only.
    → New asset stage `engine_pack` (vertex): `Cd` = base colour with grime/damp applied, `Alpha` =
    streak amount, `uv2` = (metres below source, streak length, cause); the Karma shaders now read a
    clean prim `base_cd` so nothing is weathered twice. Re-rendered the golden bay: unchanged.
    Re-exported and re-imported: `N`, `uv`, `Cd`, `Alpha`, `uv2` all survive.
34. Rendered the re-import with a plain vertex-colour material (the engine's view) and with the UCX
    hulls as a red overlay → `evidence/10`.

## 8. Final evidence pass and package check

35. Re-rendered every evidence image against the final asset: 01 hero, 02 golden bay (+02b
    grayscale value check), 03/04 corridor, 05 gable, 06 roof, 07 9-up (re-rendered with context,
    labels read back from each seed's plan), 08 LODs (re-measured on seed 1 with the gradient sky:
    LOD1 +0.7 %, LOD2 −0.9 %), 09 kit sheet (two Karma renders of a layout of the KIT node, labels
    placed by projecting each slot through the camera matrix), 10 export, 11 night, 12 cause field,
    13 extremes. All 14 JPGs checked < 400 KB (largest 365 KB, the 9-up).
36. Final package check after `hou.hda.reloadFile(danchi.hdalc)`: new instance, LOD0 405,560 /
    LOD1 42,678 / LOD2 214 tris, "All" carries groups lod0/lod1/lod2, 4 UCX hulls, no errors or
    warnings, 6 tabs, help text present.
37. Tidied the scene (removed test instances, commented the evidence networks), saved
    `work/danchi_v002.hiplc`. Deleted my own throw-away `work/derisk_test.hdalc`. Houdini wrote 16
    automatic asset backups to `sk4-out/backup/` on each `hda save`; left in place.
38. Updated README: measured budgets, interface, seeds, attributes, export proof, evidence index,
    honest assessment by level and what an artist should still do.

### Other slowdowns
- `look final` takes 1–4 min per 1600×900 Karma frame with the full context; ~45 renders in total
  were the main time cost. Batched cheap checks as draft looks where lighting did not matter.
- An attribute wrangle created by script defaults to Detail class (index 0): my kit-sheet layout
  wrangle silently did nothing until set to Points (index 2).
- Camera framing for annotated sheets: computed label positions with the camera's world-to-camera
  matrix, focal and aperture instead of guessing.
- A locked asset cooks as one node in `cook {profile}` (0.1 ms reported), so no internal cook
  timings are claimed. `node.cook(force=True)` on the asset returned in 0.08 s (5×6), 0.14 s (8×10),
  0.33 s (14×16), but its internal nodes may have been served from cache, so those are lower
  bounds, not cook costs.
39. `houdini_connect {quit: true}` → Houdini (pid 20604) exited cleanly after the final save.
