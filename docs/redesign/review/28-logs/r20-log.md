# HocusPocus 2.1 evaluation log: `hp::mini_tower::1.0`

Houdini 22.0.466 (headless, pid 37164), bridge 2.0.0, profile `core`. Agent: Claude (Opus 5.5). Date 2026-10-24.

## Deliverables

| What | Where |
|---|---|
| HDA `hp::mini_tower::1.0` (installed; fresh instance `/obj/tower/mini_tower`, locked, matches definition) | `r20-out/mini_tower.hdalc` |
| Scene | `r20-out/work/mini_tower.hiplc` |
| FBX of LOD0 | `r20-out/mini_tower_lod0.fbx` (binary, 767 KB) |
| Evidence (all < 300 KB) | `evidence/r1_01_hero_night.jpg` 278 KB · `r1_02_facade_closeup.jpg` 291 KB · `r1_03_interior_cutaway.jpg` 287 KB · `r1_04_lod0_lod1_collision.jpg` 246 KB · `r1_05_helipad_crown.jpg` 239 KB |

What the asset does: 2–3 setback tiers on a rectangular or chamfered footprint (floors, floor height, setback, asymmetry, seed); facade of armour spandrel panels with seams, inset glass with frame ring, reveals and mullions, louvred mechanical floors with accent trims, vertical armour fins, a mitred yellow/black hazard plinth, wall AC units, rooftop AC units and vent stacks (Copy to Points from a small greeble library); antenna mast (penthouse, stepped mast, arms, beacons) or raised helipad (struts, deck, ring, H, edge lights). Every polygon has `surface` ∈ {glass, panel, frame, trim, greeble, slab}; glass also has `lit` and `emitcol`. Top-tier interior (slabs, ceiling light strips, core with a door per floor, partitions with door gaps) behind a Switch, so it is not cooked when off (verified). Outputs: 0 LOD0 (~18.7k polys), 1 LOD1 (1,652 polys, no interior, no greebles), 2 convex collision (`UCX_tier0..2`, `UCX_crown`). Two Karma MaterialX materials (`/mat/armor_panel`: displayColor × fractal grime, coated; `/mat/glass_night`: dark reflective glass, emission = `lit` × intensity × `emitcol`), assigned inside the asset by `surface` through two Material SOPs whose paths are asset parms.

## Summary table

Calls = HocusPocus tool calls (MCP resource reads and my local shell commands not counted). Errors = calls that returned an error (or a node error caused by the call).

| # | Scope item | Calls | Errors | `houdini_python` |
|---|---|---|---|---|
| 0 | Setup (status, connect, guide, first save) | 4 | 1 | 0 |
| 1 | Massing | 6 (+ shared big build) | 1 | 0 |
| 2 | Facade (incl. the shared ≈45-op build, greebles, fins) | 10 | 0 | 0 |
| 3 | Interior (incl. "does not cook when off" proof) | 8 | 1 | 0 |
| 4 | Asset (interface, HDA, install, fresh locked instance) | 8 | 2 | 3 |
| 5 | Materials (2 Karma MaterialX, assignment by `surface`) | 17 | 2 | 4 |
| 6 | Game prep (UVs, LOD1, collision, FBX) | 16 | 1 | 0 |
| 7 | Evidence (scene, lights, 5 images; many render iterations) | 51 | 1 | 0 |
| – | Saves + quit | 5 | 0 | 0 |
| | **Total** | **125** | **9** | **7** |

Item 7 is large because I iterated lighting and framing (6 Karma renders of the hero/interior, plus re-renders to get under 300 KB) and spent 4 `houdini_status` polls waiting out a blocked `look`.

## `houdini_python` uses (7) and why no tool fitted

| # | Item | What | Why no tool fitted |
|---|---|---|---|
| 1 | 5 | Introspect `voptoolutils` (names, signatures) | Read-only discovery of the Karma Material Builder tool script; no tool exposes tab-menu tool scripts. |
| 2 | 5 | `voptoolutils._setupMtlXBuilderSubnet(..., KARMAMTLX_TAB_MASK, render_context='kma')` × 2 | "Karma Material Builder" is not a node type (search finds none); it's a tab tool script. `edit create` can't run it, and hand-building the subnet would miss its tags. |
| 3 | 5 | `parm('signature').set('color3')` on `mtlxgeompropvalue` (and confirm output type) | `edit`/`parm_set` refuse the value: the signature menu is dynamic and `menuItems()` reports only `default`, so validation rejects every legal MaterialX signature. No override. |
| 4 | 5 | Set `color3FA` on `mtlxmultiply`, `color3` on `emitcol`, default colour | Same validation block. |
| 5 | 4 | Read the subnet's ParmTemplateGroup (folders, help) | No tool returns the parm *layout* (folder types/structure); `inspect parms` lists values. |
| 6 | 4 | `createDigitalAsset`, rebuild interface (tab folders, 8 disable-when conditions, node-reference material parms, remove input labels), HelpText section | No HDA tool; `spare_parms` has no conditionals, folder type or string type. |
| 7 | 4 | `definition.updateFromNode` + `save` + `hou.hda.installFile`, read back | No save/install tool. (Creating the fresh instance and locking it *was* done with `edit`.) |

## Every error and whether the hint/candidates fixed it in one step

| # | Item | Call | Error | One step? |
|---|---|---|---|---|
| 1 | 0 | `inspect {what: "guide"}` | `invalid_argument`: what not in enum | **No.** Hint said "inputSchema is authoritative" but did not mention `hocuspocus://guide`; I found it in the server instructions and read it as a resource. |
| 2 | 4 | `edit` `spare_parms` with `folder_type` | `unexpected keys ['folder_type']` + full schema in hint | Yes (and it showed me there is no disable_when). Note: the dry run before it said OK. |
| 3 | 1 | `edit` `spare_parms` toggle default 1 | `a toggle default is true or false` | Yes. |
| 4 | 6 | `inspect {what: geo, paths}` | `geo takes one path as target` + exact form | Yes. |
| 5 | 5 | `edit create mtlxgeompropvalue {signature: color3}` | `'color3' is not a menu item`, candidates `["default"]` | **No.** The candidates were wrong for this parm (Houdini accepts color3). Needed `houdini_python`. |
| 6 | 5 | `edit` creating `lod0_emitcol` | node error: VEX `Ambiguous call to function lerp()` (my code) | Yes: line/col in the message; one `parm_set`. |
| 7 | 4 | `edit` [create instance, lock] in one call | `lock applies to an existing digital asset; lock in a later call` | Yes. |
| 8 | 3 | `inspect node include: ["cook"]` | `Unknown include section` + valid list | Yes. |
| 9 | 7 | `look {quality: final}` | `houdini_busy` after 30 s; Houdini stayed busy ~2 more minutes | Partly. Hint "raise timeout_s or use a job" doesn't apply (`look` has neither); switching to `render` + `job` worked. |

## Friction, ranked, with a proposed tool change

1. **No asset authoring tools** (item 4: 3 of 7 Python calls). Creating an HDA, editing its interface (tab folders, disable/hide-when, help), saving, installing and versioning all need `hou`. *Proposal:* an `hda` tool or `edit` op `{op: "hda", action: create|save|install|update_interface, node, name, file, version, help}`, and extend `spare_parms` with `disable_when`, `hide_when`, `folder_type` (tabs/collapsible), `string_type: node_ref|file`, `join_next`.
2. **`look {quality: final}` can block Houdini for minutes with no way to wait or cancel.** The 30 s call timeout fired, the render kept the main thread, and every call (even `houdini_status`) reported busy for ~2 min. *Proposal:* give `look` `wait_s`/`timeout_s` and return a `job_id` like `render`; render Karma looks out of process (like the Flipbook child); estimate cost and cut samples/resolution in `look` (it's a preview).
3. **Menu validation rejects legal values on dynamic menus** (MaterialX `signature`), and the `candidates` were actively misleading. *Proposal:* when a menu is script-generated (or the parm is a MaterialX signature), accept any string with a warning; or support `force: true` on `set`; and list known MaterialX signatures in candidates.
4. **`look` on a SOP inside a subnet silently shows the subnet's output 0.** I lost two looks and only noticed because the image didn't match. *Proposal:* when the target isn't on the displayed path, render it via a temporary object merge, or at least add a note.
5. **Tab-menu tool scripts / recipes are unreachable** ("Karma Material Builder", likewise "MaterialX Builder"). *Proposal:* `edit {op: "create", tool: "Karma Material Builder"}`, or a `tool` op that runs a tab tool by label in a parent; let `search types` surface tab tools next to node types.
6. **The guide isn't where the brief and agents expect it** (`inspect {what: "guide"}`, `inspect {what: "tool"}`). *Proposal:* add `guide`/`tool` to `inspect` (or alias them) and point the enum error's hint at `hocuspocus://guide` / `hocuspocus://tools`.
7. **Output image size/quality control.** JPEG from Karma came out 450–570 KB at 1280×720; the only lever I had was resolution (ended at 960×540). *Proposal:* `render {image_options: {jpeg_quality, scale}}` or a convert/downscale step in the tool.
8. **`dry_run` doesn't validate `spare_parms`** (said OK to keys the real run rejected). *Proposal:* run the same schema check in dry runs.
9. Minor: `look quality lit` asked 640×480 and returned 1024×576 while reporting `rendered: [640,480]`; `lock` can't share a call with the `create` that made the node; `inspect geo` takes one path only.

## Honest view

**What the tools made easy.** `edit` is excellent: one call with ≈45 ops and `$id` references built the entire generator graph (wrangles, switches, copy-to-points, materials with multiparm counts and `chs()` expressions, three outputs, layout) with no tool error, and per-node problems in the result caught my VEX mistake at once. Error messages were mostly precise and actionable (7 of 9 fixed in one step). `inspect geo rows` (with `stats`) made checks quick: winding, UV ranges, tier data, attribute cleanliness. `cook force` plus `inspect node recurse_locked` proved the interior doesn't cook when off without any Python. `render` with jobs, camera/output overrides and thumbnails handled the FBX SOP, Flipbook and Karma ROPs the same way, and the draft `look` (~0.3 s) was ideal for framing.

**What they made hard.** Packaging the asset: the core of scope item 4 had to be Python. MaterialX signatures needed Python because validation was over-strict. Karma previews through `look` were a trap (blocking, no job). Writing ~13 KB of VEX inside JSON strings works but is fragile to edit; I had to resend whole snippets.

**What limits the result's quality.** Mostly my own judgement and time, not the tools. The facade generator is clean and procedural but regular: it reads more as "90s office tower with armour panels" than as Tokyo-3's heavy armoured blocks (no shutters, blast plates, retractable sections, large signage or numbered hull markings). Lit windows are per-cell random, which reads as noise at a distance. Materials are untextured (Cd + fractal grime), and the lighting setups were improvised in a few iterations. The 300 KB cap pushed images to ≤960 px. The tools held me back mainly in iteration speed for final-quality looks and in the asset-packaging step, which I would have liked to keep inside `edit`.

---

## Running notes (written as I went)

### Setup / discovery
- `houdini_status`: nothing connected. `houdini_connect {launch: headless}`: OK first try.
- `inspect {what: "guide"}` → **error** `invalid_argument` (what must be node|parms|...). The brief said `guide` exists; it doesn't in this build. The hint said "inputSchema is authoritative" but didn't point to the `hocuspocus://guide` resource. Fixed by reading the MCP resource `hocuspocus://guide` (named in the server instructions) and `hocuspocus://tools` (54 KB) for the full reference. Not one step: I had to recall the resource from the instructions.
- `hip_save {path}` to the work path: OK.
- `edit` dry run with `spare_parms` containing a made-up `folder_type` and `disable_when` key → dry run said OK. Real run → **error** `invalid_argument: unexpected keys ['folder_type']`; the hint listed the full spare_parms schema (types, folder, help, menu_items...). One-step fix. Friction: dry_run doesn't validate spare_parms; the schema has no disable_when / hide_when / tab-folder type.

### 1-3. Massing, facade, interior (built as a SOP subnet, then turned into the HDA)
- One `edit` call: geo + subnet + 36 spare parms in 4 folders (+help) + `tiers` wrangle + preview extrude + output. First try **error** `invalid_value: a toggle default is true or false` (I sent 1/0). Clear message, fixed in one step.
- `inspect geo rows` on the tier prims + `look`: massing OK; top tier too thin (7.6 m) → changed the depth setback to follow the footprint ratio.
- One big `edit` call (≈45 ops) created the whole graph: `shell_lod0` (facade generator, VEX), `shell_lod1` (same snippet via a `chs()` reference, `lod` spare parm), greeble library + Copy to Points (piece attribute `name`), `crown`, `interior`, two Switches fed by an empty Add SOP, merges, attribute cleanup, Normal, two Material SOPs (multiparm count + `chs()` expressions), LOD1 path, collision path (PolyExtrude by `hgt` attr → Convex Decomposition), three Output SOPs, layout. **No errors**; every VEX snippet compiled first time. `cook` on the three outputs: all OK.
- `inspect geo rows` on vertex N confirmed the winding (roof +Y, south wall −Z).
- `look` with a facade camera: hazard stripes mitre correctly around chamfers; panels/seams/inset glass/mullions/AC units/louvre band visible.
- `parm_set cutaway` + `look` with an interior camera: slabs, core with a door per floor, partitions.
- **Friction:** `look {target: <SOP inside a subnet>}` silently showed the subnet's output 0 (LOD0) for OUT_LOD1 and OUT_COLLISION: the flag moves inside the subnet, but the object displays the subnet. No note warned. Workaround: object-level nulls wired to outputs 1 and 2 (`view_lod1`, `view_collision`).
- `inspect {what: geo, paths: [...]}` → **error** `geo takes one path as target`; hint gave the exact form. One step.
- Added vertical armour fins as a separate wrangle (`fins`) + `fin_every` spare parm.
- Merge nodes warn about attribute mismatches between branches (my choice to keep generator wrangles reading input 0; cleaned downstream by Attribute Delete). Accepted.

### 5. Materials (done before the HDA so the asset can assign them)
- `search types "karma material builder"`: no node type; the Karma Material Builder is a tab-menu tool script. **houdini_python #1** (introspect `voptoolutils`) and **#2** (`voptoolutils._setupMtlXBuilderSubnet(... KARMAMTLX_TAB_MASK, render_context='kma')` for `armor_panel` and `glass_night`).
- `edit` create `mtlxgeompropvalue {signature: color3}` → **error** `'color3' is not a menu item ... candidates: ["default"]`. The signature menu is dynamic and reports one item in this session; Houdini itself accepts `color3`. **houdini_python #3** (confirm `parm.set('color3')` works) and **#4** (set `color3FA` on the multiply and `color3` on `emitcol`).
- Remaining network (fractal grime × displayColor → base_color; `lit` × intensity → emission; `emitcol` → emission_color) with `edit` (2 calls).
- `lod0_emitcol` wrangle: **error** `Ambiguous call to function lerp()` (my VEX: `rand()` return type). Error text pinpointed line/col; fixed in one `parm_set`.
- `look quality lit` (Karma, default light): panels pick up Cd, glass emits. Requested 640×480, got a 1024×576 PNG (`rendered: [640,480]`).

### 4. Asset
- **houdini_python #5** (read the subnet's ParmTemplateGroup). **#6** (`createDigitalAsset('hp::mini_tower::1.0')`, rebuilt interface: tabs; disable-when on chamfer / greeble_density / mast_height / helipad_size / partitions / core_size / door_width / cutaway; node-reference material parms; HelpText section). **#7** (`updateFromNode` + `save` + `hou.hda.installFile`, read back tabs/conditions/help).
- Tab folder names `massing_tab_1`, `_2`…: that's Houdini's tab-set naming, not a tool bug.
- `edit` [delete old, create fresh instance, lock] → **error** `lock applies to an existing digital asset; lock in a later call`. Clear hint; split into two calls. Lock result reports `hda_locked: true, matches_definition: true`.
- Interior not cooking when off: `parm_set interior=0, partitions=6` → `cook force` → `inspect node recurse_locked`: `interior` = `not_cooked`, switch and shell cooked. Back on → cooked. (`inspect include: ["cook"]` → error listing valid sections; one step.)

### 6. Game prep
- UVs: generated in the VEX generators as vertex `uv` (typeinfo texturecoord): world-scaled (UV Tile Size, default 4 m), unwrapped around the perimeter, depth faces sheared so no face is degenerate; roofs planar XZ; greebles/crown/interior per-face box projection. Checked with `inspect geo rows stats` (u 0..55, v 0..40 on LOD0; every vertex has uv).
- LOD1: `shell_lod1` (lod=1: flat panel/glass strips, single hazard band) + crown without `greeble` prims + fins; no interior, no greebles. 1,652 polygons vs ~18.7k LOD0.
- Collision: PolyExtrude of the tier footprints by the `hgt` attribute + crown base without the mast → Convex Decomposition (piece attr `name`) → `UCX_tier0..2`, `UCX_crown`. 164 polygons.
- FBX: `search types fbx` → `Sop/rop_fbx`; `edit` create on the asset's output 0; `render {rop_path}` wrote `mini_tower_lod0.fbx` (binary, 767 KB) in one call, with a note that it rendered the current frame only.

### 7. Evidence / render setup
- One `edit` call: ground (grid → color → material), five more asset instances in their own geo objects with different seeds/footprints/crowns (a small Tokyo-3 skyline), distant sun, env light, `/out` Karma ROP writing .jpg.
- `look` draft through the hero camera: the Flipbook already shows MaterialX emission; reframed with `parm_set`.
- `look {quality: final}` at 640×480 → **error** `houdini_busy` after 30 s: Karma took longer than the bridge call limit. `look` has no `timeout_s`/`wait_s`/job mode, the render kept the main thread busy, and the next 3 `houdini_status` calls reported busy (~2 min; I confirmed a `husk` process via the OS). The capture still landed on disk. Fix: render through the Karma ROP with `render` (`wait_s: 0` + `job`, later `wait_s: 110`); XPU + OIDN rendered a frame in ~60 s.
- Env light was invisible to camera (black sky) → `inspect type` found `light_contribprimary` ("Render Light Geometry").
- Hero iterations: daylight emission blew windows to white → night (moon 0.12, navy sky, 3 sodium point lights, emission 3.5). JPEG sizes 566 → 453 → 310 → 278 KB (1280×720 → 1024×576 → 960×540, OIDN denoiser on).
- Facade close-up: daylight raking sun, emission 0.15, 960×720 (291 KB).
- Interior: draft look to frame, first Karma version washed out by direct sun → dusk version (sun 0.9 warm, sky dim, ceiling strips at emission 4); re-rendered at 880×660 to get under 300 KB (287 KB).
- LOD comparison: object-merged LOD0 | LOD1 | collision side by side away from the city; Flipbook ROP straight to JPG (first 1280×960 = 381 KB, too big → 960×720 = 246 KB; first pass blown out by lights → dimmed).
- Helipad crown close-up on a skyline instance (239 KB).
- Final: `search nodes has_errors` → none; scene restored to the hero-night state; `hip_save`; `houdini_connect {quit: true}` → exited.
