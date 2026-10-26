# Danchi generator — work log

Times are local (EDT), 2026-10-25.

## 02:43 Setup
1. Loaded the `procedural-assets` skill and read its five reference files (recipes, surfacing,
   game output, architecture, metrics). Followed its phase order: brief → metrics → plan →
   greybox → detail → variation → surfacing → weathering → game outputs → package → review.
2. `houdini_status` → nothing running. `houdini_connect {launch: {mode: headless}}` →
   Houdini 22.0.466, pid 36120, Indie (so `.hiplc` / `.hdalc`).
3. `hip_save` straight away to `work/danchi_v001.hiplc` (a launched Houdini dies with the MCP
   server, so save early).
4. Read tool references with `inspect {what: tool}` for `look`, `hda`, `edit` and the guide,
   rather than guessing argument shapes.
5. Wrote `README.md`: brief, signature features, budgets, metrics table, pivot convention,
   piece names (skill gates 0 and 1).

## 02:50 Risk spike (before any real building)
Why: the two things most likely to force a redesign late were (a) end-wall numbering in
Japanese ("12号棟") and (b) whether Karma picks up MaterialX materials that live in a matnet
*inside* a SOP network (needed so the HDA is self-contained).
- `houdini_python` listing of node types: copytopoints::2.0, font, matnet, unpack,
  convexdecomposition, polyreduce::2.0, mtlx* nodes all present; Labs LOD Create is **not**
  installed (so LODs are authored, not decimated). Found `SideFX-WenQuanYiZenHei.ttf` shipped
  with Houdini (portable CJK font).
- First Font SOP attempt failed: `file` wants the font *name* ("SideFX WenQuanYi Zen Hei"),
  not the .ttf file name. Read the parm's menu items to find it. (small slowdown)
- Check: wrangle `s@shop_materialpath = opfullpath("../materials/m_test")` works (VEX has
  opfullpath); `inspect geo group_by shop_materialpath` → 1 row, 8 prims.
- Check: `look quality final` (Karma) of the font → "3-12号棟" rendered in the Cd colour via
  `mtlxgeompropvalue displayColor`. Both risks cleared.

## 02:55–03:06 Plan, greybox kit, HDA shell, contact sheet (skill phases 2–3)
Architecture (from the skill: plan then instance, small single-purpose stages):
`plan_massing` (detail wrangle: seed → floors/flats/style/cores/number/palette as detail
attribs) → `plan_points` (one point per kit piece: name, role, floor, bay, side, stable id,
orient, per-flat curtain/lit/door/cloth/grime) → 14 kit wrangles (`kit_<piece>`, each its own
node, sharing `vex/lib.vfl` helpers) → `kit_normal` → `kit_uv` → `kit_surface` → `KIT` →
blast per LOD (`lodmask`) → `copytopoints::2.0` per LOD → per-instance wrangle; connective
geometry (`body`: plinth, end walls with panel joints, roof, parapet) and the end-wall number
(`num_font` → `num_points` → copy) are generated outright. All VEX lives in `work/vex/*.vfl`,
assembled by `work/vex/build.sh` and loaded with `edit set value_file`.

Checks and fixes, in order:
- `plan_points` → `inspect geo group_by name`: 40 balc + 30 corr + 10 corr_gap (=40 per side
  for 5F×8), 10 stair_flr + 2 stair_top, 1 tank, 4 antennas, props at ~expected densities. ✔
- First kit build: 14 VEX compile errors. Cause 1: `addpoint(0, point(...))` ambiguous —
  and it read points that don't exist in the input yet (VEX reads input geometry only);
  rewrote the cylinder caps to recompute positions. Cause 2: `foreach (... ; array(a,b,c))`
  ambiguous in VEX; replaced with explicit calls. Cause 3: Normal SOP wants `typevertex`, not
  `vertex` (error listed the tokens). `partial: "stop"` kept the good ops each time.
- Draft look: the slab reads; props render black. `inspect geo group_by name attribs Cd` on
  `merge_lod0` → laundry/futon Cd = 0. Cause: Copy to Points 2.0's "Attributes from Target"
  multiparm defaults to **0 entries**, so no plan attributes reach the copies. Set
  `targetattribs` = 1 with an explicit list. (slowed me down ~5 min)
- Verified face winding with `houdini_python` (box faces' normals point outward). ✔
- `hda create` early (danchi::danchi_block::1.0 → `danchi.hdalc`) so a contact sheet can hold
  locked instances while the master stays unlocked for editing. 26 parms promoted.
- Contact sheet `/obj/sheet`: 7 seeds with massing-from-seed + the two extremes (4F×3, 14F×16).
  The automatic look camera overlapped rows; added `/obj/cam_sheet`. GL flipbook "lit" blows
  out Karma-scaled light values, so gate looks use Karma `final`.
- Gate result: bands, floor rhythm and silhouettes read as danchi; four palettes differ; tall
  blocks with only 3–4 flats look like point towers — skew tall blocks longer (to do).

## 03:07–03:13 Detailing the kit (phase 4: utility pieces first)
Order: balcony bay and corridor bay (most-used), then stair/lift tower floors and tops, then
roof props (tanks, antennas), then balcony props (AC, futon, laundry). Each piece stays its own
wrangle; shared helpers (`lib.vfl`: boxes with per-face skip masks so hidden faces are never
built, ledge-tagged quads, cylinders, `wall_openings`, `sash` with frame/panes/curtain/room box
and an LOD1 flat-window stand-in tagged `lodmask`).
- Compile error: `set()` inside `array()` is ambiguous (vector4 vs matrix2). Declared typed
  `vector4` locals first. (third VEX ambiguity of the day — VEX overloads are the main
  friction when writing VEX blind)
- Looked at `kit_balc_solid` and `kit_corr` alone in Karma: geometry right but everything
  blown out — Karma light units are not π-normalised; sun 3.2 + sky 0.7 was far too hot.
  Settled on sun 1.25 + sky dome 0.55 after several looks.

## 03:13–03:20 Materials, sky, cameras
- Probed mtlx node input names and signature parms with `houdini_python` (menus list only
  "default", but suffixes `color3`, `color3FA`, `vector3` work — as the skill notes).
- `work/py/materials.py` builds 9 materials in `danchi_gen/materials` (run via
  `houdini_python exec(open(...))` because wiring ~80 VOP connections as edit ops is long).
  Colour comes from `Cd` via `mtlxgeompropvalue displayColor`; grime/lit/litcol likewise.
- `inspect problems` flags the Font SOP's font name as a missing file — false positive (the
  parm takes a font name, and the node cooks). Noted, ignored.
- Sky: the env light had `light_contribprimary` off, so no visible sky. Made a vertical
  gradient in Copernicus (`/img/sky/sky_gradient` ramp → `rop_image` → `work/tex/sky_latlong.png`),
  set it as `env_map`, turned camera visibility on. Ground: asphalt MaterialX in `/mat`.
- Cameras aimed with a tiny `aim.py` (look-at → Houdini xyz rotation) instead of guessing.
- First hero look: reads as a danchi. Close-up and corridor views checked; the far end-wall
  number looked rotated — checked head-on with a dedicated camera: just foreshortening.

## 03:16–03:30 Weathering, LOD2, collision, budgets
- `weather.vfl` (point wrangle per LOD): ray up from inside the face → distance to the ledge
  water runs off; ray up from outside → overhang = rain shelter; `ledge_y` on end-wall panels;
  deposits on exposed tops; splash band; per-column amount. VEX has `smooth()`, not
  `smoothstep()` (compile error). Cooks in 44 ms.
- Check: `inspect geo group_by mat attribs grime` → parapets 0.40, end walls 0.38, base 0.49,
  sheltered walls 0.19, glass/alu/interior 0. ✔
- Budget check (`houdini_python` triangle count): default LOD0 38k > 25k target. Window frames
  rebuilt as a front ring + inner faces, grille bars 3-sided → 33k. README budget revised to
  measured values.
- LOD2 shell, collision (convex boxes `UCX_danchi_NN`, fused), LOD groups, `All` output.
- Pack mode: `place_lod*` `pack` = `ch("../pack")`; the clean step keeps per-flat attributes on
  packed instances. Checked: 142 packed prims + 104 polys.
- `cook profile` reported only the last 3 nodes and called the cached rest "inactive", and
  treats a locked asset as one node — not usable to prove branch cost here. Used node
  `cookCount()` deltas instead: LOD0 cooks only `place/weather/clean/group_lod0`, LOD1 and
  LOD2 likewise. ✔ (slowdown ~5 min)
- First collision read-back showed 3 boxes for 14F×16 — stale geometry (node outside the
  display chain); explicit `cook(force=True)` → 5 boxes. ✔
- Worst case 14F×16: LOD0 168.6k, LOD1 34.2k, LOD2 634 tris.

## 03:22–03:30 Variation gate and night
- 9-up sheet re-rendered with materials: massing, palette, roofs and tanks differ at distance.
- Night test: no windows lit although `lit` reached the prims (checked with group_by). Cause:
  glass was an opaque standard surface, hiding room boxes and curtains day and night. Made it
  thin-walled transmissive → lit flats show. Emission 3 clipped to white → 1.5.
- Weathering too subtle on pale palettes → darker dirt tint, wider streak range, cap 0.7,
  default Weathering 0.7. Mirrored every live tweak back into `materials.py`.

## 03:27–03:58 LOD match, estate, evidence
- Rendered LOD0/1/2 from one camera and measured the balcony face with PIL: LOD1's steel
  railing stand-in read as a dark brown band and LOD2 assumed solid parapets → made LOD2
  railing-aware and tinted the stand-in toward the wall. Final means 0.484 / 0.502 / 0.476.
- Estate scene (4 locked instances, Kodan Cream, numbers 5-1…5-4) for the hero; re-aimed the
  camera three times to stop the tallest block hiding behind the nearest.
- Kit layout object (`/obj/kitview`) for the piece sheet. Checker and collision viewer objects
  override `shop_materialpath` via object merges. Coplanar hull faces made the overlay muddy →
  rendered hulls alone and paired them with the building.
- 9 labelled variation tiles from the master (auto-framed looks) composited with PIL. First
  composite was 465 KB → regenerated from the PNGs at q74 (not re-encoding the JPEG twice).
- The look capture folder keeps only the newest 50 images, so the greybox-gate image had
  rolled off; recovered it from the saved tool-result copy. (slowdown)
- Every evidence JPG checked under 400 KB (largest 303 KB) and looked at.

## 04:03–04:09 Package, export, fresh-scene test
- `hda save` with full help (measured budgets, parms, attributes), `lock: true`
  (matches_definition: true). `hda info`: 26 parms, 5 folders, 9 conditionals, 14 instances.
- FBX: `/obj/export_fbx` merges `group_lod0/1/2` + `COLLISION`, writes a `path` attribute
  (`danchi_LOD0..2`, `UCX_danchi_LOD0_NN`), triangulates, `rop_fbx` with build-from-path →
  `export/danchi_lods.fbx`. Re-imported with `hou.hipFile.importFBX`: LOD0 32,410 / LOD1 6,618
  / LOD2 438 tris, 3 UCX meshes, UVs present — identical to the in-Houdini counts. ✔
- Fresh scene: `hip_save` → `hip_new` → `hda install danchi.hdalc` → new instance (seed 42,
  massing from seed, LOD all) → cook: no errors or warnings, 8 materials resolved inside the
  instance, `inspect problems` clean; Karma render `evidence/15_fresh_scene_instance.jpg`. ✔
- `hip_open` the work scene back (discarding the test scene), final save, quit.

## What slowed me down (summary)
1. VEX overload ambiguities (`point()`, `array()` of `set()`) and `smoothstep` vs `smooth`.
2. Copy to Points 2.0 copying no target attributes by default (props came out black).
3. Karma light scale and the hidden sky (env light camera visibility off by default).
4. Opaque glass hiding the interiors — only found when night mode showed nothing.
5. `cook profile` not usable for internal branch cost of an asset; stale geometry reads on
   nodes outside the display chain.
6. Capture folder rotation (50 images) losing an early gate image.

## 04:09 Done
Final `hip_save`, `houdini_connect {quit: true}` → Houdini exited.
