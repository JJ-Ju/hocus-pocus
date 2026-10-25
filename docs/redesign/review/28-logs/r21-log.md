# HocusPocus 2.1 evaluation log: `hp::mini_tower::1.0`

Houdini 22.0.466 Indie, headless (hython, pid 31408), driven only through `mcp__hocuspocus__*`.
Local file checks (sizes) used the shell. I did not read HocusPocus source, tests or docs.

## Deliverables

| What | Where |
|---|---|
| HDA (Indie) | `r21-out/mini_tower.hdalc`, type `Sop/hp::mini_tower::1.0`, 35 parms in tabs Massing / Facade / Crown / Interior / Output, HelpText 3,232 chars |
| Scene | `r21-out/work/mini_tower.hiplc` (fresh locked instance `/obj/mini_tower/tower`, plus 10 more instances for context, comparisons and variants) |
| FBX LOD0 | `r21-out/mini_tower_lod0.fbx` (684 KB binary; read back: 19,406 polygons, `uv`, 2 material slots) |
| Evidence | `r21-out/evidence/r1_01_hero.jpg` (196 KB), `r1_02_facade_closeup.jpg` (243 KB), `r1_03_interior_cutaway.jpg` (177 KB), `r1_04_lod0_lod1_collision.jpg` (131 KB), `r1_05_variants.jpg` (155 KB), `r1_06_uv_layout.jpg` (256 KB), `r1_07_night_emission.jpg` (162 KB) |

Houdini also wrote `r21-out/backup/mini_tower_bak*.hdalc` on each asset save (its default backup behaviour).

## Summary table (HocusPocus calls; counted from my transcript, accurate to about +/-2)

| # | Scope item | Calls | Tool errors (returned `error`) | Other failures | `houdini_python` |
|---|---|---|---|---|---|
| - | Setup (status, connect, guide, tool refs, final quit) | 7 | 0 | - | 0 |
| 1 | Massing (+ crown: antenna / helipad) | 11 | 1 (menu token) | 1 VEX compile error in a node row | 0 |
| 2 | Facade (plates, seams, glass, mullions, hazard band, greebles, `surface`) | 10 | 0 | 1 VEX compile error in a node row | 0 |
| 3 | Interior (slabs, core with doors, partitions, switch) | 6 | 1 (`locked`) | 0 | 0 |
| 4 | Asset (interface, assembly, create/save/install/instance/lock) | 26 | 1 (toggle default) | 0 | 1 |
| 5 | Materials (2 MaterialX, assignment by `surface`, USD check) | 24 | 4 (`invalid_argument` x4) | 1 silent: Material SOP cooked before /mat existed | 0 |
| 6 | Game prep (UVs, LOD1, collision, FBX) | 19 | 0 | 1 my bug (Connectivity class on points) | 0 |
| 7 | Evidence (cameras, lights, Karma ROPs, JPEG conversion) | 69 | 2 (`houdini_busy`; 1 deliberate menu probe) | 3 silent stale images from the COP File cache | 0 |
| | **Total** | **~172** | **9** (1 deliberate) | | **1** |

## How it is built (inside the asset)

- **Massing**: a detail wrangle makes one footprint polygon per tier (rectangle or chamfered octagon), splitting the floors 50/30/20 (or 60/40) with seeded jitter and seeded per-side setbacks (`asym`). Prim attributes carry each tier's floor range and bounds; detail attributes (roof centre/size, top-tier floors) feed the crown, interior and collision through `detail()` expressions.
- **Facade**: one detail wrangle (~350 lines of VEX) walks tiers x edges x floors x bays and writes every polygon facing outward (winding verified first): dark seam backing, raised armour plates (corner piers stand out twice as far, a seeded "service spine", blind bays), frames with reveals, glass inset 0.3 m, mullions, a lobby transom, louvred mechanical floors (`greeble`), a red accent band under the top cornice, cornices with mitred corners, parapets, roof decks, a yellow/black 45-degree hazard-striped plinth (stripes clipped per edge so they run continuously round the corners), red emissive aviation lights on parapet corners. Per-window `lit`/`litcol` (whole floors lit together, warm or cool).
- **Greebles**: the facade wrangle emits anchor points; Copy to Points places AC units (box + fan) on spandrels and HVAC boxes / water tanks (piece attribute `variant`) on tier roofs.
- **Crown**: Switch between an antenna (plant house, tapered mast, 3 red rings with cross-arms, red light) and a helipad (deck, PolyExtrude-inset ring, Font "H"), placed by `detail()` expressions.
- **Interior (top tier)**: Blast top footprint -> PolyExtrude inset -> PolyExtrude slab -> Copy and Transform per floor; core = Boolean (outer box - inner box), then Boolean (- door cutters copied per floor); partitions = Copy to Points of a unit box with `v@scale`/`p@orient`. Behind a Switch on `interior && output == 0`; a `cutaway` toggle blasts the top tier's +Z facade.
- **Output menu**: LOD0; LOD1 (the facade wrangle switches to 2-3 flat quads per bay, greebles and interior switched off: 1,889 vs 19,406 polygons); Collision (one PolyExtrude prism per tier with per-prim `zscale`, plus a Bound box of the crown, Connectivity-named `UCX_mini_tower_00..03`, hard-edged normals).
- **UVs**: computed in metres from each edge frame in VEX (facing-dependent projection, continuous along the wall), then a UV Transform SOP scales them so one UV tile = one bay x one floor. Greebles, crown and interior get UV Unwrap.
- **Materials**: `/mat/mt_armour` and `/mat/mt_glass`, VOP subnets with the material flag: `mtlxstandard_surface` -> `subnetconnector` (surface). Armour base colour = geompropvalue `displayColor` (the `Cd` paint); glass = dark, specular 1, roughness 0.05, emission = geompropvalue `lit` x 1.8 with colour geompropvalue `litcol`. A Material SOP in the asset assigns armour everywhere and glass on `@surface=glass` (paths are asset parms).
- **Checks done**: every polygon has one of the six `surface` values (stats: `frame, glass, greeble, panel, slab, trim`; LOD1: `glass, panel, trim`); a brand-new instance created with Interior off cooks with `core_doors`, `partitions`, `slabs`, `interior_merge` reporting `not_cooked`; the definition holds `DisableWhen { interior == 0 }` on `door_w` (and on partitions, cutaway), `{ footprint == 0 }` on chamfer, crown-driven ones on mast/pad; the FBX reads back with UVs and material paths.

## Every error, and whether the hint/candidates fixed it in one step

| # | Tool | Error | Fixed in one step from the hint? |
|---|---|---|---|
| 1 | edit (create Normal SOP) | `invalid_value`: `'prim' is not a menu item of .../type` | Yes: hint listed `typepoint/typevertex/typeprim/typedetail` |
| 2 | edit (spare_parms) | `invalid_value`: `spare_parms.add[26]: a toggle default is true or false` | Yes: said exactly what to send (I sent 1/0) |
| 3 | edit (massing wrangle) | not a tool error: node row carried VEX `Ambiguous call to function setprimattrib()` (matrix2 vs vector4) at (73,5) | Yes: line, column and candidates; fixed with one `set` `patch` |
| 4 | edit (facade wrangle) | node row: VEX `Syntax error, unexpected identifier` at (110,10) | Yes, with my VEX knowledge (array-returning functions need `function`); one `patch` |
| 5 | inspect stage (`attributes`) | `invalid_argument`: stage does not take `attributes` | Yes: hint listed `attribs` |
| 6 | inspect geo (summary + attribs/class/stats) | `invalid_argument`: need `rows: true` | Yes |
| 7 | inspect geo (`attribs` as a string) | `invalid_argument`: `'attribs' must be a list` | Yes, but the schema says `string or array` |
| 8 | inspect geo (`attribs: shop_materialpath`) | `invalid_argument`: no such prim attribute; candidates = real attributes | Yes, and it diagnosed the real bug: the Material SOP had written nothing, so I force-cooked it |
| 9 | look (quality final, 1024x768) | `houdini_busy` after 30 s, result discarded | Partly: hint says "raise timeout_s, or use a job", but `look` has neither; I switched to Karma ROPs + `render` (jobs) |
| 10 | inspect node inside the locked asset | `locked`: pass `recurse_locked: true` | Yes |
| 11 | edit dry_run (deliberate: `"?"` for two env-light menus) | `invalid_value` with both menus' tokens and labels in one reply | Yes, used on purpose to list menu tokens |

Silent failures (no error):
- Material SOP created before `/mat` materials existed -> cooked with "not found" warnings and never re-cooked, so no `shop_materialpath`; the first Karma look simply had no glow. `cook {force}` on the output does not re-cook inputs (the result says so), so I had to find the node myself.
- COP File node served the old image after the PNG on disk was overwritten (same path); `cook {force: true}` did not reload it. Three `look {output}` calls wrote stale JPEGs before I noticed by eye. Fixed by giving the same file a different path spelling (`renders/../renders/x.png`).
- Inside the asset, Merge SOPs warn "mis-match of attributes"; they do not reach the asset node (cook reports no warnings), so I left them.

## houdini_python uses

1. **Read the asset's parm conditionals** (`parmTemplateGroup().find(name).conditionals()`, plus the HelpText length). Why no tool fitted: `inspect parms` (even `detail: full`) and `inspect type` (`folder`, `detail: full`) list label/default/range/help/folder but not disable_when/hide_when; `hda info` gives only `interface {parms, folders}`. `parm.isDisabled()` is False either way in hython (conditionals are evaluated by the UI), so the definition is the only place to check.

## Friction, ranked, with a proposed tool change

1. **Final-quality `look` cannot exceed ~30 s.** A 1024x768 Karma `look {quality: final}` hit `houdini_busy` and the result was discarded; `look` has no `timeout_s`, `wait_s` or job. *Change:* give `look` `wait_s` and return a `job_id` like `render`, or fall back to a job automatically for `final`.
2. **No control over JPEG size.** The Karma ROP's JPEG was 436 KB and it has no quality parm; `look {output: .jpg}` has a fixed quality too. I built a Karma -> PNG -> COP File -> `look {output}` pipeline (about 3 extra calls per image). *Change:* `render`/`look` `output` options `jpeg_quality` and/or `max_bytes`, or let `look` take an image file as `target`.
3. **Stale COP File images.** After overwriting a file, the File COP kept the cached image even with `cook {force: true}`. *Change:* have `cook force` on a File COP reload the file (or press its reload), and have `look` on a file-backed COP note when the file's mtime is newer than the cooked image.
4. **Upstream re-cooks and stale warnings.** The Material SOP that cooked before its materials existed kept its stale result. *Change:* `cook {force: "chain"}` to force-cook the whole input chain; `inspect problems` could flag "warning older than the node it names" (here: the node it could not find now exists).
5. **Parm conditionals and HDA help are invisible.** No read shows `disable_when`/`hide_when`; `inspect type` on the asset says "No help found ... nodes.zip" although the definition has a 3,232-char HelpText (`hda info` counts it). *Change:* include `disable_when`/`hide_when` in `inspect parms`/`type` `detail: full` and in `hda info interface`; read an asset's HelpText section in `inspect type {include_help}`.
6. **USD stage reads omit material bindings.** `inspect stage {attribs}` lists primvars but not `material:binding` or GeomSubsets, so I could not confirm the per-face materials on the stage and debugged from the SOP side instead. *Change:* list relationships (bindings) and subsets in stage reads.
7. **`inspect geo` argument shapes.** `attribs` is declared `string|array` but a string is rejected; summary mode rejects `attribs`/`stats`. *Change:* accept a comma/space string; allow `stats` on the summary.
8. **Parm globs.** `parms: "a,b,c"` matched nothing; `|` is the separator (the hint said so). *Change:* accept commas as well.

## My view

**What the tools made easy.** `edit` is excellent: a whole 25-node sub-network in one call with `$id` wiring, one undo step, and node rows that carry cook errors (VEX compile errors arrive with line and column). `patch` on a string parm let me fix and extend a 350-line VEX snippet with surgical find/replace instead of resending it. Menu tokens are forgiving (labels, indices, and a note on what was chosen), and wrong tokens come back with the full list. `dry_run` caught nothing because nothing was wrong, but it made a 21-node batch cheap to try. The HDA flow (`hda create` promoting spare parms into tab folders with help, `save {lock}`, `install`, `info` showing `hda_locked`/`matches_definition`) was smooth. `look` on a SOP showing it alone, `recurse_locked` reads of internal `cook_state` (which proved the interior does not cook), and `render` jobs were all exactly what I needed.

**What they made hard.** Producing final images: the 30 s `look` limit, no JPEG size control and the stale COP cache cost roughly 25 of the 69 evidence calls. Debugging materials across SOP -> USD needed a hand-made Scene Import and several argument-shape retries on `inspect`. Verifying parm conditionals needed `houdini_python`.

**What limits the result's quality.** Mostly my own choices, not the tools. The facade is one hand-written VEX generator, so its vocabulary is small: flat plates without bevels or panel-line normals, no textures (colour is `Cd`), flat emissive glass with no interior mapping, hollow lower tiers, and a fairly regular lit-window pattern. It reads as a late-80s armoured office slab, but it is plainer and cleaner than Evangelion or Akira backgrounds (no signage, pipes, catwalks or weathering). The game prep is honest but basic: tiling world-scale UVs (good for a trim sheet, not a packed lightmap atlas), per-tier prism collision rather than a computed hull, and `surface` reaching the FBX only as two material slots. The tools never stopped me from doing more; time and judgement did.
