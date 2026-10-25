# 26 - neo_tower dogfood (2.1)

Brief: plan-2.1.md §2. One agent drives Houdini 22.0.466 only through the HocusPocus MCP
tools (profile `core`, bridge and host 2.0.0). Phases: P1 massing, facade and interiors
(this section); P2 UVs, materials, textures, LODs, collision and export; P3 lookdev and
the variation block.

## P1: massing, facade, interiors

### Outcome

`examples/neo_tower/neo_tower.hdalc` defines `hp::neo_tower::1.0`, a self-contained SOP
HDA. It loads from file in a fresh scene: uninstall, install, `node_create`, cook in
136 ms, 164,316 primitives (before the light-panel optimisation below).

Default output (chamfered, armour style, 36 floors, 3 tiers, interiors on):
**149,692 polygons, 307,330 triangles.**

| Part | Polygons | Triangles |
|---|---|---|
| facade | 84,572 | 170,360 |
| roof | 1,095 | 2,374 |
| crown | 681 | 1,572 |
| interior | 63,344 | 133,024 |

With interiors off: about 90k polygons, and the interior branch is never cooked. This was
proven with a non-forced cook: `tier_loop_end` stays `not_cooked`. A full cook takes
about 0.1 s.

The build scene `examples/neo_tower/work/neo_tower_p1.hiplc` holds cameras, a dusk light
rig, a ground plane, a topology helper and a Karma ROP for P3. It is not committed. The
parm, attribute and group contract is in `examples/neo_tower/README.md`.

Evidence in `docs/redesign/evidence/neo-tower/`. All are Karma renders through `render`
with an output override, 16 spp, preview colours only (no materials yet).

| File | What it shows |
|---|---|
| `p1_01_hero_seed1.jpg` | Tokyo-3: chamfered, armour panels, armour bands with hazard stripes, pilasters, armoured collar, antenna mast |
| `p1_02_hero_seed2.jpg` | Neo-Tokyo: rect slab, ribbon windows, rooftop billboards, sign blade, helipad |
| `p1_03_hero_seed3.jpg` | stepped footprint, mixed styles per tier, armour cap crown |
| `p1_04_cutaway_interiors.jpg` | cut-away at floor 7: ring corridor, offices, core |
| `p1_05_facade_closeup.jpg` | seams, visor hoods, louvres, pipes, hazard coping, entrance canopy |
| `p1_06_core_detail.jpg` | lift doors, doors with architraves, glazed sidelights |
| `p1_07_wireframe_corner.jpg` | polywire topology of a chamfered corner, floors 2–5 |

Wall time: Houdini connected at 22:00 UTC, P1 done at about 22:55 UTC. The earlier
licence block cost about 10 minutes.

### Status before the licence fix (kept for the record)

At 21:49 UTC the machine had no licence. Two headless and one GUI launch returned
`houdini_offline`:

- **Headless.** The hint pointed at the launch log, which said "No licenses could be
  found". The hint worked.
- **GUI.** The hint ("run `install-houdini`/`doctor`") was wrong; the window title said
  "Unable to Acquire a License".

After the user logged in (Indie licence), the next `houdini_connect {launch: headless}`
worked first time.

### Call tally (P1, including the 3 failed launches)

| Tool | Calls | Errors | Notes |
|---|---|---|---|
| edit | 42 | 6 | 30+ carried whole VEX snippets (2–17 KB each) |
| inspect | 25 | 7 | all 7 were option-shape errors, each fixed on the next call |
| look | 19 | 0 | draft 15, lit 4 |
| parm_set | 16 | 0 | |
| render | 10 | 0 | Karma evidence; 3 re-renders for framing and exposure |
| hip_save | 8 | 0 | |
| houdini_python | 6 | 1 | see below |
| cook | 4 | 0 | 3 with profile |
| houdini_connect | 4 | 3 | licence |
| node_create | 3 | 1 | for-each pair; HDA load test (type missing before install) |
| houdini_status | 2 | 0 | |
| search | 1 | 0 | |
| hip_new | 1 | 0 | |
| hip_open | 1 | 0 | |
| **total** | **142** | **18** | |

Text bytes, estimated: about 150 KB sent and about 40 KB of text received, plus 29
images (19 looks, 10 render thumbnails).

What the sent bytes were:

- **VEX snippets:** about 120 KB. The facade (15.5 KB) and roof (17 KB) wrangles were
  each sent twice, and the interior walls wrangle (16 KB) three times, mostly to change
  one or two lines.
- **Everything else:** about 30 KB.

### houdini_python uses (6)

1. **Create the HDA from the subnet and build its interface.** This used
   `createDigitalAsset`, plus a `ParmTemplateGroup` with Tabs folders, new defaults and
   disable-when conditions. No tool creates an HDA, and `edit` `spare_parms` cannot
   express disable or hide conditions or folder type.
2. **Save the definition.** Help section, `updateFromNode`, `save`,
   `matchCurrentDefinition`. No tool saves, versions or locks an HDA. `edit node lock:
   false` does unlock it, and its hint said so.
3. **Re-save after fixing a VEX shadowing warning in `int_walls`.** Same reason.
4. **Uninstall and reinstall the `.hdalc` for a clean-load test.** No tool installs or
   uninstalls an HDA file. The call raised `OperationFailed` on a `nodeType()` lookup of
   the just-uninstalled type, and the uninstall itself went through. The error showed
   only a bare traceback line, with no hint about which call failed.
5. **Install the `.hdalc`.** Same reason as 4.
6. **Re-save after reducing ceiling light panels to one quad each.** Same reason as 2.

All six are HDA lifecycle. Every geometry, network, parm, render and QA step went through
the purpose-built tools.

### Errors and whether the hint led to the fix

| # | Call | Error | Hint useful? |
|---|---|---|---|
| 1–3 | houdini_connect | `houdini_offline` (licence) | headless yes (log); GUI no |
| 4 | edit spare_parms `{name: {...}}` | invalid_argument | **yes**: hint gave the full `{add: [...]}` shape. But `dry_run` had accepted the same bad shape a call earlier |
| 5 | edit spare_parms toggle default `1` | invalid_value | the message alone was clear |
| 6 | edit `set` with `path` | "'node' must be a non-empty node path" | the message gave the key name; the hint ("check hocuspocus://tools") is unreachable from this client |
| 7 | inspect parms `paths` + `include_defaults` | invalid_argument | yes |
| 8 | inspect geo `attribs` without `rows` | invalid_argument | yes |
| 9 | inspect geo vertex `group` | "'int_wall' is a prim group" | yes |
| 10 | VEX ambiguous `prim()` inside an edit | node error in the edit row | yes: compiler message with line and column |
| 11 | inspect geo `full_strings` | invalid_argument | yes, it listed valid options (but the option I needed does not exist) |
| 12 | inspect parms `detail: folders` | invalid_argument | yes |
| 13 | edit karma `alights` | parm_not_found | **yes**: "Did you mean lights?" plus candidates |
| 14 | edit groupcreate `grouptype: prim` | invalid_value | **yes**: candidates `primitive`, ... |
| 15 | inspect node inside locked HDA | locked | **yes**: `recurse_locked: true` |
| 16 | inspect geo `recurse_locked` | invalid_argument | yes, it was not needed for geo |
| 17 | edit `set` inside locked HDA | locked | **yes**: the hint gave the exact `{op: node, lock: false}` call. But `dry_run` had passed it |
| 18 | node_create of an uninstalled type | node_type_not_found | yes: suggested `search` |

Every error was fixed on the next call. The hints were consistently good when they named
candidates or the exact corrective call.

### Friction, ranked by severity, with proposed tool changes

1. **High: no HDA lifecycle tool.** Creating from a subnet, saving the definition,
   adding help sections, and installing or uninstalling a library caused all 6 escapes.
   *Proposal:* `hda {action: create|save|install|uninstall|info, node, name, file,
   version, help, interface}`. `save` should do `updateFromNode` + `save` + relock.
   `create` should take the same `spare_parms` shape for the interface.
2. **High: long string parms cannot be patched or read back.**
   - Changing one line of a 16 KB wrangle means resending all of it (120 KB of my
     150 KB sent).
   - `inspect parms` elides long strings and offers no `full_strings`.
   - *Proposal:* an `edit` op `patch` (`{node, parm, find, replace}` or line ranges),
     `inspect parms full_strings: true`, and `set` accepting `value_file` (a local path).
3. **High: `look` on a SOP inside a subnet or HDA renders the object's output, not that
   SOP.** I built a `/obj/preview` object with an Object Merge to see any internal node,
   which cost 3 extra edits and many `objpath1` changes. *Proposal:* when `target` is a
   SOP that is not the object's display output, isolate it automatically and say so in
   `notes`.
4. **Medium: `look` cannot write to a chosen path.** It saves to
   `%LOCALAPPDATA%/HocusPocus/captures` and returns the path. Evidence took a Karma ROP,
   10 `render` calls and 7 parm changes for camera, resolution and output.
   *Proposal:* `look {output: "<file>"}` (the fix is reported in progress).
5. **Medium: `look quality: lit` is inconsistent.**
   - With no scene lights it rendered Karma at 1024×576 when 640×480 was requested.
   - With scene lights it silently used the Flipbook backend.
   - *Proposal:* honour `resolution` and the camera aspect, and report the backend
     choice in `notes`.
6. **Medium: op key names differ and `dry_run` misses real failures.**
   - `create` uses `parent`, `node` uses `path`, `set` uses `node`.
   - `dry_run` passed a malformed `spare_parms` and a `set` inside a locked HDA; both
     then failed for real.
   - *Proposal:* accept `path` as an alias everywhere, and run full validation
     (including spare_parms shape and lock state) in `dry_run`.
7. **Medium: `spare_parms` lacks interface design features.** There is no
   `disable_when` or `hide_when`, no folder type, no `join_next`, no range locking and no
   ordering control. *Proposal:* add these fields so an HDA interface needs no Python.
8. **Medium: `cook profile` force-cooks every input chain, including inactive Switch
   inputs.** "Interiors off costs nothing" looked false in the profile; proving it took a
   non-forced cook plus an `inspect` of `cook_state`. *Proposal:* profile the cook path
   that actually runs, and mark inactive branches.
9. **Low: inspect options are inconsistent across `what`.**
   - `recurse_locked` works for `node` but is rejected by `geo`, and `geo` reads inside
     locked HDAs anyway.
   - `include_defaults` is not allowed with `paths`.
   - `detail: folders` works only for `type`.
   - *Proposal:* the same options everywhere, or ignore the inapplicable ones with a note
     instead of failing.
10. **Low: no resource reader in this client.** `ReadMcpResourceTool` and
    `ListMcpResourcesTool` are not exposed, so `hocuspocus://guide` and
    `hocuspocus://tools` are unreachable, yet hints point at them. *Proposal:* a `guide`
    tool or `inspect {what: "guide"}`, and hints that inline the relevant schema
    fragment.
11. **Low: a licence failure looks like a generic `houdini_offline`** (from the blocked
    start). *Proposal:* a `licence_unavailable` code, and GUI launches that detect the
    "Unable to Acquire a License" window instead of waiting 90 s.

What worked well:

- One `edit` call per subsystem (create, wire, set and flag together) with `$id`
  references.
- Menu label-to-token matching, with notes saying which token was set.
- VEX compile errors surfaced in the edit result.
- `node_create` paired `block_begin` with `block_end` automatically.
- `inspect type detail: folders` on the HDA.
- `cook profile` loop attribution (per-iteration ms for `int_walls` and the boolean).
- `render` with `output` override and an inline thumbnail.

### Capability verdicts

| Area | Verdict | Notes |
|---|---|---|
| Massing (footprints, tiers, setbacks, seed variation) | native | VEX in an attribwrangle via `edit` |
| Facade modules, greebles, hazard stripes | native | per-floor Run Over Numbers wrangle |
| Roof, crown, signage | native | |
| Interiors (for-each per tier, boolean, copy to points, Switch) | native | |
| Parameter interface: folders, menus, toggles, ranges, help | native | `edit` `spare_parms` |
| Parameter interface: disable-when, Tabs, defaults in the definition | escape hatch | |
| HDA create, save, help, install | escape hatch | 6 `houdini_python` calls; unlock is native |
| Visual review | native | `look` draft and lit, cameras made with `edit` |
| Evidence files | native, indirect | `render` with Karma ROP and output override; `look` saves only to its captures dir |
| QA (winding, poly budget, cost when off) | native | VEX QA node plus `inspect geo` rows, `cook`, `inspect node` |

### Assessment

**Can an agent build a AAA-grade generator with these tools?** For the geometry, largely
yes. The asset has:

- floor-aligned modular facades with real human-scale detail;
- interiors that read correctly in cut-away;
- clean quad topology, verified winding and a stated poly budget;
- interiors that cost nothing when off;
- a designed interface.

The tools never blocked a geometry task. Only the HDA lifecycle needed Python.

**What limits it is mostly the agent, not the tools.** All the geometry is hand-written
VEX (about 60 KB across 9 wrangles). The tools only carry the strings, so quality comes
down to the agent's spatial reasoning: face winding, skip masks against z-fighting,
miters, stair profiles. I caught one real layout bug by eye (a billboard intersecting the
helipad safety net) and one false alarm (the Flipbook drew interior wall faces black;
a ray-test QA node showed the winding was fine).

My visual judgement is bounded by 1024-pixel images with preview colours and no
materials:

- I cannot see sub-centimetre z-fighting, so I relied on construction rules (offset or
  skipped coplanar faces) and QA.
- Unwelded internal faces where solids touch remain. A strict manifold check would flag
  them.
- **No bevels.** Hard 90° box edges, with no rounding or edge wear, are the biggest
  remaining gap to AAA. P2 should bake a bevel/edge normal map, or add chamfers to the
  hero pieces: columns, pilasters, bands, coping.

On the tool side, the long-string round trips (friction 2) and the `look` targeting gap
(friction 3) cost the most.

**What P2 needs:**

- UVs at a stated texel density:
  - planar or box projection per `surface`;
  - for the facade, UVs aligned to the module from `floor` and edge position.
- Materials keyed on `mat_id` and `surface`, with a two-sided material for glass.
- An emissive set: `light`, `sign_panel` keyed by `sign_slot`, and night windows on
  `facade_glass`.
- LOD1 and LOD2:
  - drop interiors and swap in `int_proxy`;
  - collapse greebles;
  - replace facade modules with textured quads.
- A collision proxy from the tier outlines (`massing`).
- FBX and USD export through ROPs with `render`.

Tool asks for P2: the `hda` tool, `look {output}`, and file-backed parm values.

**What P3 needs:**

- Real materials and the dusk and night rig (the `/obj/sun` and `/obj/sky` starting
  point is in the build hip).
- Haze and fog.
- The 6+ variation block from `seed` and `variation`.
- The `cutaway` parm for the interior shot.

## P2: edges, UVs, textures, materials, LODs, collision, export

### Outcome

P2 started from the committed P1 files only: `neo_tower.hdalc`, the README contract and
the P1 log. The `work/neo_tower_p1.hiplc` scene loaded the asset from
`examples/neo_tower/`. The handoff worked. The contract (surface, `mat_id`, `part`,
`floor`, `tier`, `sign_slot`, units, winding, unfused pieces) was enough to plan every P2
step without reading P1's VEX, except `facade`, which I read once to learn piece
dimensions. One gap: the materials need each tier's `style`, which is not on the tower.
P2 adds **output 2 (massing)** to `hp::neo_tower::1.0`, a backward-compatible change.

`examples/neo_tower/neo_tower_export.hdalc` defines **`hp::neo_tower_export::1.0`**. It
takes the tower and its massing and has five outputs: preview, LOD0, LOD1, LOD2 and
collision. It also has Write Textures, Export FBX, Export USD and Export All buttons
(Python module callbacks that press the internal ROPs). It is a second asset rather than
new parms on the generator. The generator stays a 0.1 s design tool, and game prep (five
outputs, textures, materials, ROPs, a 32 s lightmap pack) is a pipeline step that can wrap
any generator that honours the contract. The README has the full contract.

Default tower (chamfered, armour, 36 floors, 3 tiers, interiors on, seed 1):

| Output | Polygons | Triangles | Materials | Notes |
|---|---|---|---|---|
| LOD0 | 178,093 | 363,434 | 12 | bevelled, interiors, vertex AO |
| LOD1 | 27,596 | 56,596 | 8 | no interiors or greebles, opaque atlas windows, `uv2` |
| LOD2 | 1,054 | 2,330 | 5 | shell plus far-facade atlas, crown, `uv2` |
| collision | 36 | 96 | – | 4 closed convex `UCX_` hulls (3 tiers and the crown) |

**Edge cost:** +56,104 triangles (+18 %) over the unbevelled 307,330. A first pass that
bevelled every edge of the hero surfaces plus sills cost +115,832 (+38 %). It was cut to
front-face edges on the fine surfaces, which turns corner patches into mitres. Strips get
their rounded edges from the trim sheet's normal map.

**Texel density:** 512 px/m on 2K maps, so one texture covers 4 m. The checker render
(`p2_01`) shows square 0.25 m checks at one density on all tiling surfaces. Trim strips
are fitted to their rows in V, by design.

**Textures:** 13 sets × 4 maps (BaseColor, Normal, ORM, Emissive), 2048² PNG, 52 files:
the trim sheet, window, sign and LOD2 atlases, and nine 4 m tiling sets. All are authored
in Copernicus inside the asset, rendered headless under Indie through `render` on
`Cop/rop_image`. One wrangle per set is selected by frame through four Switches, so one
ROP per map writes all 13 sets as frames 1–13. The neon signs are Copernicus Font nodes
with a Japanese system font (YuGothB). Each 13-frame map render returned within the
`render` call's wait, a few seconds each.

**Materials:** 14 MaterialX materials (standard surface, 4 images, normal map, ORM split,
vertex masks for AO and edge wear). They are bound by `mat_id` through `s@mat` and
`shop_materialpath`, and are style-aware: pale cladding on Tokyo-3 tiers, dark on
Neo-Tokyo tiers. The same names become the FBX material slots and the USD GeomSubset
bindings.

**Exports** (`examples/neo_tower/export/`, gitignored): `SM_neo_tower_LOD0.fbx` (11 MB,
with the UCX hulls), `_LOD1.fbx` (2.8 MB), `_LOD2.fbx` (0.1 MB), `_collision.fbx`, and
`SM_neo_tower.usd` (49 MB). The USD has a `LOD` variant set (LOD0 selected), MaterialX
materials with relative `./textures/` paths, and guide-purpose collision. This was checked
with `usdcat`. The **FBX re-import proof** used a fresh scene: a File SOP read
`SM_neo_tower_LOD1.fbx`, which brought back 55,338 triangles, `uv`, `uv2`, `Cd`,
`shop_materialpath` slot names and `mat_id`. A Reference LOP pulled only the materials from
the USD, an Assign Material bound them by slot name with a VEXpression, and Karma rendered
it (`p2_07`). A clean-load test in a new scene (install both files, wire, cook) passed.

Evidence in `docs/redesign/evidence/neo-tower/` (Karma, 16 spp, every file under 300 KB):

| File | What it shows |
|---|---|
| `p2_01_checker_uv.jpg` | 0.25 m checker on LOD0 at 512 px/m: tiling surfaces uniform, trims fitted in rows, windows in atlas cells |
| `p2_02_trim_sheet.jpg` | trim sheet BaseColor/Normal/ORM/Emissive, window atlas, sign emissive, LOD2 atlas (downscaled) |
| `p2_03_hero_dusk.jpg` | textured LOD0, dusk rig from P1 |
| `p2_04_night_windows.jpg` | night: moonlight, emission ×3, per-window and per-zone lit variation |
| `p2_05_lod0_lod1_lod2.jpg` | LOD0, LOD1, LOD2 side by side at dusk |
| `p2_06_collision_proxy.jpg` | LOD1 with the UCX hulls in translucent orange |
| `p2_07_fbx_reimport.jpg` | the FBX LOD1 re-imported in a fresh scene, materials bound by slot name, Karma |
| `p2_08_bevel_closeup.jpg` | bevelled panel edges, visor hoods, plate lines and rivets, hazard band |
| `p2_09_neo_tokyo_night_signs.jpg` | extra: seed 2, rect ribbon style, helipad, night; neon blade カラオケ, billboards 新東京, 電気街 and 居酒屋 |

Wall time: P2 ran from 22:56 to about 00:05 UTC (about 70 min). About 4 min of that was
UV Layout cooks and 2 min Karma renders.

### Call tally (P2)

| Tool | Calls | Errors | Notes |
|---|---|---|---|
| inspect | 86 | 8 | 30 `type` lookups for new vocabulary (Cop, Lop, mtlx, uvlayout, polybevel) |
| edit | 84 | 17 (+3 `houdini_busy`) | the big texture and material builds were 4 to 30 KB each |
| render | 43 | 0 | 4 texture ROPs × 13 frames ×2, 4 FBX, 4 USD, 16 Karma evidence and tests |
| parm_set | 32 | 3 | snippet fixes, lights, presses (`fillmaterials`, `export_all`) |
| houdini_python | 9 | 1 | see below |
| search | 8 | 0 | |
| cook | 7 | 0 | 2 became jobs (UV Layout) |
| hip_save | 6 | 0 | |
| look | 4 | 1 | one Flipbook timed out at 30 s on the 360k-tri tower |
| hip_open | 4 | 0 | switching to and from the re-import scene |
| job | 4 | 0 | |
| houdini_status | 2 | 0 | |
| houdini_connect | 2 | 0 | launch headless with the hip, then pin by pid (the GUI Houdini 48868 was never touched) |
| hip_new | 2 | 0 | |
| **total** | **293** | **30** | |

Text bytes, estimated: about 170 KB sent and about 130 KB of text received, plus about 45
images (39 render thumbnails, 4 looks, the contact sheets read locally).

What the sent bytes were:

- **Texture VEX:** about 75 KB. 13 snippets of 1.5 to 3.7 KB. The first full send failed
  to compile (`smoothstep` is `smooth` in VEX; `rand()` is ambiguous inside expressions),
  so the 4 atlas snippets were sent twice and window, clad, LOD2 and clad_dark a third
  time for art changes.
- **SOP VEX:** about 35 KB (uv_assign 5.5 KB ×2, bevel_select ×3, lod1_reduce ×3, lod2 ×2,
  collision ×2).
- **Wiring:** about 30 KB. 52 switch connections sent twice, because one bad menu token
  rolled back the whole 13 KB call.
- **Everything else:** about 30 KB.

### houdini_python uses (9)

1. **Raise neo_tower's max outputs to 2 and save the definition.** This failed on a bug in
   my print line and was rolled back, but the file save had already happened. HDA
   lifecycle: no `hda` tool in the 2.0.0 bridge.
2. **The same, rerun.**
3. **Wire the export subnet's indirect inputs to its IN nulls.** `edit connect` refuses a
   subnet's own inputs ("in different networks") and there is no syntax for them.
4. **Set `signature` on mtlxmultiply and mtlxmix (color3FA, color3).** The bridge reports
   those menus as only `default`, so `edit` and `parm_set` reject valid tokens. `hou`
   reports the same single item; the menu is script-generated.
5. **Set the VOP material flag on the 14 material subnets.** The Material Library LOP
   ignores subnets without it. `edit` `flags` accepts only display, render, bypass and
   template.
6. **Create the HDA from the subnet.** This covered the Tabs interface (30 parms,
   disable-when), the PythonModule for the buttons, help, 5 outputs and the save.
   HDA lifecycle again.
7. **Input and output labels** (DialogScript edit) on both assets, then save.
8. **Install both `.hdalc` files** for the clean-load test.
9. **Read `maxNumOutputs`** to prove an `edit` validation error was wrong (friction 3).

Six of the nine (1, 2, 6, 7, 8 and partly 9) are HDA lifecycle, which 2.1 stream D2a now
covers with the `hda` tool. Three are real gaps: subnet inputs, mtlx signatures and the
material flag.

### Errors and whether the hint led to the fix

| # | Call | Error | Hint useful? |
|---|---|---|---|
| 1 | edit: unlock op then create inside the asset, same call | `locked` | **misleading**: the hint said to unlock, which the call already did. Validation runs before op 1 executes. Split into 2 calls |
| 2 | inspect network `wiring` | invalid_argument | yes, listed the valid options |
| 3 | inspect parms `paths` of nodes inside a locked asset | parm_not_found "No parm 'finalize' on …/neo_tower" | no: it read the node path as a parm path |
| 4 | edit spare_parms toggle default `1` | invalid_value | the message is clear (same as P1 #5) |
| 5 | edit polybevel `useoffsetscale` | invalid_value | **yes**: candidates `unscaled`, `byattrib` |
| 6 | edit connect from the subnet to its child | invalid_input | partly: the object_merge advice works but is the wrong idiom inside an asset; escape 3 |
| 7–8 | edit: multiparm `aovs` count plus `type3` in one op, then in 2 ops of one call | parm_not_found | yes ("Did you mean type2?"), but the real cause is upfront validation; parm_set count, then edit |
| 9 | edit resample `basesize: custom` | invalid_value | **yes**: candidates `parm`, `input` |
| 10 | edit `resolution` tuple of expression dicts | invalid_value | yes, use the components |
| 11 | inspect geo `full_strings` | invalid_argument | yes |
| 12 | edit uvlayout `rotstep: 90` | invalid_value | **yes**: candidates PI2 (90°)… |
| 13–15 | edit created UV Layout or LOD chains | `houdini_busy` (30 s) | the call kept running and finished. The hint (inspect before repeating) was right. `cook: false` on the create op did not stop the cook |
| 16 | edit copy with `name` | invalid_argument | yes, gave the fields |
| 17 | edit copy: one source, 12 names | OperationFailed (copy collisions) | yes in effect: one op per copy worked |
| 18 | edit rop_image `colorconversion: none` | invalid_value | **yes**: `raw`. But it rolled back a 13 KB, 70-op call |
| 19 | edit mtlxgeompropvalue `signature: vector3` | invalid_value, only `default` | **no**: the token is valid in Houdini. I switched to `mtlxgeomcolor` |
| 20–21 | edit and parm_set mtlxmultiply `signature: color3FA` | same | **no**: escape 4. `dry_run` had passed it |
| 22 | edit layout with `path` | invalid_argument | yes |
| 23 | edit flags `material` | invalid_argument | yes, it is clear the flag is not supported |
| 24 | parm_set sopimport `bindmaterials: zz` (a probe) | invalid_value | **yes**: the candidate list taught the 5 modes |
| 25 | parm_set usd_rop `savestyle: zz` (a probe) | invalid_value | **yes**: candidates. The default left a 49 MB sublayer in `work/usd/`, and `flattenstage` baked out the variant set; `flattenalllayers` keeps both right |
| 26 | edit renames into names freed earlier in the same call | name_collision | misleading (upfront validation again) |
| 27 | inspect node `include_parms`, stage `detail`, stage `include` tokens, parms `paths` + `parms` | invalid_argument ×4 | yes, each listed the valid options |
| 28 | look draft on the 360k-tri tower | internal, render timeout 29.9 s | no hint; Karma `render` worked |
| 29 | edit connect `from_output: 1` from a node created in the same call | "has no output 1 (it has 1)" | **wrong**: the type has 2 outputs (escape 9). Split calls |
| 30 | python print bug (#1 above) | python_exception, rolled back | yes, the traceback |

The hints were good when they listed candidates (8 times, each fixed on the next call).
They misled where validation runs before earlier ops apply (unlock, multiparm count,
rename, outputs of a new node) and where a script-generated menu is reported as one item.

### Friction, ranked, with proposed tool changes

1. **High: `edit` validates every op against the scene as it was before the call.**
   - Unlock-then-create, multiparm-count-then-instances, rename-then-reuse and
     outputs of a node created earlier in the call all fail. Each cost an extra call, and
     two cost a resend of a large op list.
   - `dry_run` passed a script-menu token that then failed for real (as in P1 #4 and #17).
   - *Proposal:* validate op by op against a simulated state (or apply inside the undo
     block and roll back), so later ops see earlier ones. For a node created in the call,
     take outputs from its type.
2. **High: one bad parm value rolls back a 70-op, 13 KB build.** *Proposal:* when
   `partial` is false, still report all invalid values in one error, as the edit already
   does for some problems, so the fix-up is a single resend. Better, accept
   `on_invalid: "skip"` for parms so the graph is built and the bad parm is reported.
3. **High: still no HDA lifecycle tool in this 2.0.0 bridge** (escapes 1, 2, 6, 7, 8).
   Stream D2a's `hda` tool should cover create from a subnet with interface,
   PythonModule and help sections, input and output labels, max outputs, install and
   save. Its interface spec should include button callbacks and folder type, which this
   asset needed.
4. **High: long VEX snippets are resent whole** (about 110 KB of the 170 KB sent). D2a's
   `edit` patch and `value_file` address this. A Cop-wrangle `#include` of an HDA
   section would also let 13 snippets share one 1 KB helper header (sent 13 times here).
5. **Medium: `edit` cooks every created node and times out on heavy ones.** A UV Layout
   (32 s) made 3 calls return `houdini_busy` with the result discarded. *Proposal:* honour
   `cook: false` per op and add a call-level `cook: "none" | "created" | "touched"`, or
   return a `job_id` when the cook exceeds the budget.
6. **Medium: no way to address a subnet's indirect inputs** (escape 3). *Proposal:* `connect
   {from: "<subnet>", from_input: 0, to: "<child>"}` mapping to `indirectInputs()`, or
   `from: "<subnet>/input:0"`.
7. **Medium: script-generated menus look like single-item menus** (mtlx `signature`,
   escape 4). *Proposal:* for MaterialX nodes, read the signatures from the node type's
   input variants, or skip the menu check when the menu is script-generated and accept the
   value with a note.
8. **Medium: the VOP material flag is not settable** (escape 5). Without it a Material
   Library LOP silently imports nothing (empty stage, no warning). *Proposal:* `flags:
   {material: true}`, and an `inspect problems` note when a materiallibrary finds no
   materials.
9. **Medium: `look` cannot handle a production-size SOP.** The Flipbook timed out at 30 s
   on 360k triangles, so every visual check went through Karma `render`, which was fine:
   about 15–25 s, with notes such as "thumbnail nearly black". `look {output}` (P1
   friction 4) is still missing in 2.0.0.
10. **Low: `inspect` on the Karma ROP returned about 8 KB of locked tonemap-ramp parms**
    that no one sets. *Proposal:* drop locked parms whose value comes from an internal
    expression unless `include_defaults`.
11. **Low: `inspect outline`/`network` of an uncooked locked asset returns no children.**
    It needed a `cook` first, with no note. *Proposal:* say "asset not cooked; pass
    cook_uncooked".
12. **Low: inspect option shapes vary by `what`** (geo `stats` requires `rows`; stage takes
    `include` tokens unlike node's; node has no `include_parms`). Same as P1 friction 9.
13. **Low: `copy` cannot copy one source to several names in one op.** *Proposal:* allow
    `names` longer than `paths` when `paths` has one entry.

What worked well:

- `render` is the workhorse. It handled Copernicus `rop_image` frame ranges, which turned
  13 texture sets into frames. It also rendered SOP `rop_fbx`, the LOP `usd_rop`
  (it reported the layers written, which caught a stray 49 MB sublayer), Karma in `/obj`
  and `usdrender_rop` in a fresh scene. Output overrides were always restored.
- `inspect image` gave resolution, layer type and channel stats, enough to tune the normal
  map strength without looking. `inspect stage` with `include: bindings` proved the
  GeomSubset bindings.
- `parm_set press` drove the HDA's Python callback buttons (`export_all` wrote all 57
  files).
- Menu-token hints with candidates (rotstep, colorconversion, bindmaterials, savestyle,
  basesize, useoffsetscale).
- `cook` turning long cooks into jobs, with per-node attribution (it found the 32 s UV
  Layout).

### Capability verdicts

| Area | Verdict | Notes |
|---|---|---|
| Hero bevels (edge selection, PolyBevel, weighted normals) | native | VEX edge group plus PolyBevel 3.0 via `edit` |
| UVs: trim rows, world tiling, window and sign atlases | native | one VEX wrangle |
| Lightmap `uv2` (UV Unwrap, UV Layout) | native, slow | 32 s on LOD1; not feasible on LOD0's 178k faces |
| Vertex AO and edge masks | native | VEX `intersect`, 0.4 s on LOD0 |
| Procedural textures in Copernicus, headless, Indie | native | wrangle, Font, Height to Normal, Switch, `rop_image` via `render` |
| Normal and AO baking from geometry | not needed, available | `bakegeometrytextures` (edge, curvature, AO, rounded-normal maps) and `karmatexturebaker` exist; P3 can bake the LOD2 impostor |
| MaterialX materials | native with 2 escapes | signature menus and the material flag |
| LOD1, LOD2, collision | native | |
| FBX export and re-import | native | `rop_fbx` plus `render`; File SOP re-import |
| USD export with LOD variants and materials | native | sopimport, materiallibrary, assignmaterial (VEXpression), addvariant, usd_rop |
| HDA create, interface, buttons, save, install | escape hatch | 2.0.0 bridge; D2a's `hda` tool targets this |
| Evidence | native | `render` with output override |

### Assessment against AAA, and what P3 needs

**What is now at a game-production standard:**

- The asset structure: trim sheet plus tiling materials at a stated 512 px/m, atlas
  windows with per-zone lit variation, a sign atlas keyed by `sign_slot`, three LODs at
  about 6.4:1 and 24:1 triangle ratios, and Unreal-convention collision.
- FBX with slot names and `uv2`, and USD with LOD variants and relative texture paths.
- Mid-poly bevels on hero edges with face-weighted normals. The close-up (`p2_08`) reads
  as manufactured panels instead of grey-box cubes.
- The Neo-Tokyo night (`p2_09`) is the first image that reads as the art direction: a
  dark slab, hundreds of lit cells, neon katakana.

**What is not AAA yet:**

- *Materials are clean procedural paint.* No decals (stencils, numbers, NERV-style
  warning plates), no per-building colour variation, little dirt where surfaces meet.
  The tiling sets are fairly uniform at 4 m repeats.
- *LOD0 windows are opaque atlas cards.* The interiors from P1 show only in cut-away.
  A clear-glass LOD0 mode, or interior mapping (a parallax cubemap atlas), is the AAA
  answer.
- *LOD2 pops.* It is slightly brighter than LOD1 at dusk. An impostor bake of LOD1 onto
  the LOD2 shell (`karmatexturebaker` or `bakegeometrytextures`) would match it.
- *There is no lightmap or AO texture.* `uv2` exists, but nothing is baked into it.
- *The lead's silhouette critique is not addressed.* P2 fixed edges, not massing. The
  towers still read as office towers from afar: no Tokyo-3 armour fins, retractable
  crown or sleeve; no Neo-Tokyo rooftop clutter density, antennas or neon stacks.
- *Agent limits.* Every look judgement comes from 1024-px renders. I cannot see mip
  bleeding, normal-map seams across faces in the trim rows, or tangent-space
  handedness errors on mirrored faces. The UV frame is right-handed by construction,
  but this was not verified with a lit normal-map test.

**P3 needs:**

1. Lookdev: haze and fog, the dusk and night rigs, and exposure (the dusk renders clip
   slightly).
2. Decal and variation layers: material IDs or vertex colours for paint variation per
   tower and per tier.
3. A silhouette pass in `neo_tower`: Tokyo-3 armour fins and a crown sleeve; Neo-Tokyo
   rooftop clutter and neon.
4. An LOD2 impostor bake.
5. The clear-glass LOD0 option.
6. The 6+ variation block, mixing Tokyo-3 and Neo-Tokyo seeds.
7. The cut-away interior shot.

The tool asks from P2 are friction items 1, 2, 5, 6, 7 and 8. Items 3 and 4 are in flight
in D2a.

## P3: silhouette, materials, lookdev, evidence

### Outcome

P3 started from the committed P2 files and worked through the lead's four critiques:

1. The silhouettes read as generic office towers.
2. The materials are clean paint.
3. LOD2 pops brighter than LOD1 at dusk.
4. The crown collision box encloses the mast.

**Silhouette (generator `hp::neo_tower::1.1`).** `neo_tower.hdalc` now holds 1.0
(unchanged) and 1.1. 1.1 adds a Silhouette folder with 20 parms, a style preset menu and
an Apply Preset button. The menu callback applies one of four presets: `tokyo3_spire`, `tokyo3_block`,
`neotokyo_slab` and `neotokyo_stack`.

- **Tokyo-3 vocabulary:**
  - full-height armour fins with raked caps;
  - telescoping sleeve rings where each tier rises out of the one below;
  - armour shutters closing up to 45 % of the windows;
  - heavy crown hardware: sensor stacks, pods, a radar dish, lattice masts and a
    crenellated cap ring;
  - NERV-style markings: floor, block and sleeve numbers, warning plates, and 4.5:1
    vertical stencils on the fins.
- **Neo-Tokyo vocabulary:**
  - an attached service tower with sky bridges;
  - stacked and offset blocks, and cantilevered blocks on struts, each with real facades
    (`facade_annex`);
  - giant billboards on standoffs with floodlights;
  - rooftop clutter: water tanks on stilts, lattice aerials, AC banks, searchlights and
    aircraft warning lights.

**Why 1.1.** P3 is not a silent change for 1.0 consumers:

- output 2 gains volume prims (`kind` fin, sleeve, annex);
- the tower gains the surface `decal` (`mat_id` 36) and the attributes `decal_id`,
  `fixture` and `aim`;
- even the defaults add fins, sleeves and markings.

So 1.0 stays in the library and old scenes load unchanged. Interiors and the P2 contract
are untouched: tier outlines have `kind` "" and keep every P2 attribute.

**Why the export asset stays at 1.0.** Its outputs, parm names and material slot names did
not change. P3 added parms with defaults, fixed two defects and added content, and existing
scenes should get those.

**Materials (export asset).**

- *Rain streaks.* A `grime_mask` node ray-casts upward from every exterior point and
  writes a streak mask below sills, ledges, visors, bands, sleeves and canopies, fading
  over `grime_length` (2.6 m). It runs before the LOD split, so LOD0 and LOD1 match. The
  generator's spandrels are split at the sill ends so the mask has an edge to follow.
- *Grime layer.* A new Copernicus `T_grime_Mask` holds R streak pattern, G chips and
  B blotches. Eight materials gained a MaterialX grime layer from it: albedo darkening,
  roughness rise, and edge wear broken up by chips.
- *Per-piece tone.* Each cladding and armour piece gets its own tone, multiplied into
  `Cd.r` with the AO.
- *Decals.* A 34-cell decal atlas is drawn procedurally in Copernicus: 16 Font nodes with
  a Japanese system font, plus plates, stripes and emblems. It is written as
  `T_decals_*` with an opacity map and bound through a new `M_decals` (UV mode 4,
  `decal_id`).
- *New parms:* `grime_streaks`, `grime_dirt`, `grime_darken`, `grime_length`,
  `tone_variation` and `lod2_tone`.

**LOD2 pop fixed.** It was measured as the masked mean luminance of the same framing at
dusk, with PIL on the local render.

- Before: Tokyo-3 LOD2 was +15 % over LOD1 (0.313 against 0.272), Neo-Tokyo +12 %.
- Three changes fixed it:
  - the shell's vertex tone `lod2_tone` = 0.68, standing in for recess shadowing;
  - the `lod2` atlas gained 35 % armour shutters and sill grime;
  - Neo-Tokyo far-facade emission × 0.58.
- After:
  - Tokyo-3: LOD0 0.261, LOD1 0.267, LOD2 0.270 (+1.1 %);
  - Neo-Tokyo: LOD1 0.224, LOD2 0.232 (+3.7 %).

**Crown collision fixed.** On the `tokyo3_spire` preset there are now 7 hulls (324
triangles):

- one per tier, widened to include the fins and sleeves;
- a crown body hull from 216.2 to 233.6 m;
- a separate slim mast hull, 4.7 × 3.2 m, up to 245.8 m.

P2 had one box around the whole crown, mast included. Thin aerials get no collision.
Annex volumes get their own prisms.

Triangle counts (export asset):

| Tower (preset, seed) | Interiors | LOD0 | LOD1 | LOD2 | Collision |
|---|---|---|---|---|---|
| Tokyo-3 spire (`tokyo3_spire`, 1) | on | 510,948 | 92,405 | 2,434 | 324 (7 hulls) |
| Neo-Tokyo slab (`neotokyo_slab`, 2) | on | 788,804 | 94,592 | 3,824 | 96 |
| `tokyo3_block`, 3 | off | 333,122 | 88,715 | 4,454 | not measured |
| `neotokyo_stack`, 5 | off | 539,794 | 122,620 | 3,154 | not measured |
| 1.1 defaults, 1 | on | 378,814 | 65,267 | 3,766 | 204 (5 hulls) |

The 1.1 defaults cost +4.2 % LOD0 triangles over P2's 363,434.

**Exports re-run** with the final locked assets, in `examples/neo_tower/export/`
(gitignored):

- 59 textures (58 maps and the checker);
- `SM_neo_tower_LOD0.fbx` (17.6 MB, the `tokyo3_spire` build, with the UCX hulls);
- `SM_neo_tower_LOD1.fbx` (5.0 MB), `SM_neo_tower_LOD2.fbx` and
  `SM_neo_tower_collision.fbx`;
- `SM_neo_tower.usd` (78 MB).

P3 attributes leaked into the FBX at first (`kind`, `piece`, `streak`, the annex frame).
The clean nodes now strip them, and the collision output keeps only `name`.

**Load and save checks.** A fresh `hp::neo_tower::1.1` from the saved library applied the
`neotokyo_slab` preset (width 66, service tower, 2 billboards) and cooked with no errors or
warnings. Both build instances are locked and match their definitions.

Evidence in `docs/redesign/evidence/neo-tower/`. All are Karma renders through `render`
(OIDN denoiser), 1600 to 1910 px wide, and every JPG is under 400 KB. The
night image has a soft bloom added locally with PIL. The sheets were assembled locally.

| File | What it shows |
|---|---|
| `p3_00_overview.jpg` | contact sheet of p3_01 to p3_10 |
| `p3_01_tokyo3_dusk.jpg` | Tokyo-3 at dusk: the hero `tokyo3_spire` and a `tokyo3_block` over a low city of lots, sun glow, height fog |
| `p3_02_neotokyo_night.jpg` | Neo-Tokyo at night: slabs and stacks, searchlights from the `fixture` spots, giant billboards, lit window zones, fog, wet ground |
| `p3_03_variation_block.jpg` | 9 towers from the 4 presets plus a custom one, with different seeds and footprints, labelled |
| `p3_04_interior_cutaway.jpg` | cut-away at floor 6: core, corridors, offices, partitions |
| `p3_05_hero_three_angles.jpg` | the hero spire at 0°, 120° and 240° |
| `p3_06_engine_check_fbx_lod0.jpg` | `SM_neo_tower_LOD0.fbx` re-imported with a File SOP, UCX hulls blasted, materials bound by slot name, flat engine-style key and ambient light |
| `p3_07_materials_closeup.jpg` | the base of the spire: streaks under sills, edge chips, per-panel tone, stencils and hazard band |
| `p3_08_lod_match_dusk.jpg` | Tokyo-3 LOD0, LOD1 and LOD2, and Neo-Tokyo LOD1 and LOD2, at dusk with their measured luminance |
| `p3_09_collision_crown_fix.jpg` | the 7 UCX hulls of the spire, and a close-up of the crown body hull and the slim mast hull |
| `p3_10_decal_grime_textures.jpg` | the decal atlas, a normal map, `T_grime_Mask` and the recalibrated LOD2 atlas |

Wall time: P3 ran from 00:02 to about 01:55 UTC (about 113 min). Of that, about 19 min
was inside `render` (Karma evidence and tests, texture and FBX ROPs) and about 4 min was
blocked by `export_all` presses.

### Call tally (P3)

These counts come from the session transcript and include the final save and quit.

| Tool | Calls | Errors | Notes |
|---|---|---|---|
| edit | 83 | 10 | node builds, MaterialX grime layers in 8 materials, 16 Font nodes, lights, ROPs |
| render | 83 | 0 | Karma evidence and tests, texture ROPs (frames 1–14), FBX re-runs |
| inspect | 50 | 8 | option-shape errors, each fixed on the next call |
| parm_set | 45 | 2 | both were `houdini_busy` from `export_all`, which finished |
| houdini_python | 37 | 0 | see below |
| job | 7 | 0 | |
| cook | 4 | 0 | |
| hip_save | 5 | 0 | |
| houdini_status | 2 | 0 | |
| houdini_connect | 3 | 0 | launch headless, pin pid 1672, quit. The GUI Houdini (pid 48868) was never touched |
| look | 1 | 1 | Flipbook draft timed out at 30 s on the 0.5 M-triangle spire |
| search | 1 | 0 | |
| **total** | **321** | **21** | |

Text bytes, measured from the transcript: **138 KB sent** and **277 KB of text
received**, plus 9 render thumbnails and 56 local images that I read to judge renders and
sheets.

What the bytes were:

- **Sent:**
  - `edit`: 78 KB (MaterialX and Copernicus graphs, lights and ROPs; the long VEX went
    through files, below).
  - `houdini_python`: 24 KB.
  - `parm_set`: 15 KB.
  - `render`: 12 KB.
- **Received:**
  - `inspect`: 130 KB. The largest replies were Karma ROP parms with the 8 KB tonemap
    junk, `full_strings` reads, and type lookups.
  - `parm_set`: 48 KB.
  - `edit`: 40 KB.
- **VEX through files.** About 70 KB of VEX (volumes 12 KB, silhouette 27 KB,
  collision, LOD2 shell, finish, grime mask, gen_grime, gen_decals, two skies) never went
  through a tool argument. I kept each snippet in a local file and loaded it with a
  2-line `houdini_python` reload (`parm.set(open(file).read())`). That emulates
  `value_file`, which the 2.0.0 bridge lacks. Without it, the silhouette snippet alone
  (7 revisions) would have cost about 190 KB.

### houdini_python uses (37)

| Group | Count | Calls | Why no tool fits (2.0.0 bridge) |
|---|---|---|---|
| HDA lifecycle | 7 | create the 1.1 definition (copyToHDAFile, changeNodeType, Silhouette folder inserted after Crown, PythonModule presets); add the Apply Preset button; export grime parms and defaults; save ×3; final save and relock | no `hda` tool. The interface needed `insertAfter` of a folder, a menu callback, disable-when rules and changes to definition defaults |
| `value_file` emulation | 9 | load or reload long snippets from local files (volumes, silhouette, facade_annex, texture wrangles, skies) | `edit set` takes the snippet inline only |
| String patches | 5 | `gen_lod2` (shutters, grime, Neo-Tokyo emission ×2), facade spandrel split, collision fin and sleeve hulls | no `patch` op. A one-line change would otherwise resend a 3 to 27 KB snippet |
| Reads the tools refuse or cut off | 6 | children wiring of both assets (`inspect network` takes no `wiring`); the PythonModule section; material subnet contents; texture switch wiring; `subnetconnector parmtype` menu ×2 | `network` has no wiring; no HDA section reader; the candidate list was cut at 20 items, so `atmosphere` was missing |
| Geometry and QA analysis | 10 | sky-bridge bbox; streak statistics ×3 (through the bevel, on the spandrels); fixture list with world transforms for the light rig; collision hull report; QA reports; fresh-instance preset test; default budget; `export_dir` raw value | `inspect geo` cannot group stats by an attribute (bbox per `name`), filter a vertex attribute by a prim group, or read several targets |

The five string patches and nine snippet reloads (14 in all) fall to stream D2a's `edit
patch` and `value_file` once the bridge is 2.1. The `hda` tool covers the seven HDA
lifecycle uses if it handles version bumps (copy to a new type name, then
changeNodeType) and inserting a folder at a position. The ten analysis calls are a real
gap.

### Errors and whether the hint led to the fix

| # | Call | Error | Hint useful? |
|---|---|---|---|
| 1 | inspect network `cook_uncooked` | invalid_argument | yes, listed the valid options |
| 2 | inspect parms `paths` + `include_defaults` | invalid_argument | yes (same as P1 #7) |
| 3 | inspect network `wiring` | invalid_argument | yes, but wiring is what I needed; escape |
| 4 | inspect parms `.../gen_signs/snippet` | parm_not_found | **yes**: "Did you mean vexsnippet?" |
| 5 | edit copy with `to_parent` missing in op 1 | invalid_argument | yes, named the field; the generic `hocuspocus://tools` pointer is unreachable here |
| 6 | look draft on the spire | internal, render timeout 30 s | no hint; Karma `render` worked (P2 #28 again) |
| 7 | edit mtlxadd created in the same call, then connected | "has no input 0 (it takes 0)" | **wrong**: mtlxadd has 2 inputs. Validation before the node exists (P2 #29). Split calls |
| 8 | edit connect with relative names | invalid_argument (+18 problems) | **yes**: all 19 problems in one error, fixed in one resend |
| 9 | edit: create the 1.1 tower and wire `from_output: 1` | "has no output 1 (it has 1)" | **wrong**: the type has 2 outputs. Same up-front validation |
| 10 | edit copy, then delete children of the copy | node_not_found | misleading: the children exist once the copy runs. Split calls |
| 11 | edit subnetconnector `parmtype: volume` | invalid_value | partly: listed 20 candidates, cut off before `atmosphere`; escape |
| 12 | edit volume `uniformsamples: nonuniform` | invalid_value | **yes**: candidates, `size` |
| 13 | inspect parms `paths: ["/obj/sky", ...]` | "No parm 'sky' on /obj" | no: it read a node path as a parm path (P2 #3 again) |
| 14 | inspect geo with `paths` | invalid_argument | yes, one per target |
| 15 | inspect geo `Cd` as prim | invalid_argument | **yes**: "'Cd' is a vertex attribute" |
| 16 | inspect geo vertex `Cd` in prim group | invalid_argument | the message is clear, but no way round it; escape |
| 17 | edit copy ×4 while a Karma render ran | houdini_busy, not started | yes: retry after the render |
| 18 | edit `$prev` | invalid_argument | **yes**: "An $id names an earlier op ..." |
| 19 | edit `set` on a button | invalid_value | **yes**: "Use press: true" |
| 20–21 | parm_set press `export_all` | houdini_busy (30 s), still running | yes: inspect before repeating. I waited on the file timestamps |

Other problems that were not error results:

- VEX problems surfaced in edit rows: two compile errors with line and column (an
  ambiguous `prim()` inside `append()`, and a string comparison of `prim()`), plus two
  semantic surprises found by looking (`nprimitives` does not count new prims, and
  `point(geoself())` does not see new points).
- `$id` is not substituted inside parm values (`lookatpath: "$tg"`).
- `inspect parms full_strings` printed a channel-referenced snippet twice.
- An `edit` summary lists every touched node even with `summary`.

The hints were good whenever they named candidates or the corrective call (8 times). They
misled in the same places as in P2: up-front validation (3 errors) and truncated or
script-generated menus (1).

### Friction, ranked, with proposed tool changes

1. **High: a Karma render or long button press blocks the main thread.**
   - Every `render` ran synchronously in the session's Houdini: 83 renders, about 19 min.
   - Edits sent during a render came back `houdini_busy`.
   - Each `export_all` press (3 to 4 min) returned `houdini_busy` twice. Its result was
     discarded, and I watched file timestamps to know when it ended.
   - *Proposal:*
     - run Karma ROPs out of process (husk on a saved USD or hip snapshot) so the scene
       stays editable;
     - make `parm_set press` return a `job_id` past `wait_s`, like `cook` and `render`.
2. **High: no file-backed values or patch op in 2.0.0.** Fourteen escapes. About 70 KB of
   VEX went through local files plus a reload, and five 1-line fixes were Python string
   replaces. D2a's `edit patch` and `value_file` close this. *Proposal:* also let
   `value_file` watch the file (re-set on change) for a VEX edit loop.
3. **High: `edit` still validates ops against the scene before the call.**
   - It rejected connections to a node created in the same call (wrong input and output
     counts, #7 and #9).
   - It rejected edits inside a copy made in the same call (#10).
   - Same as P2 friction 1. *Proposal:* as P2, validate against a simulated state; for a
     created node take inputs and outputs from its type.
4. **Medium: no geometry analytics.** QA questions needed Python:
   - "how long are the streaks on spandrels";
   - "where are the spot fixtures in world space";
   - "what is the bbox of each collision hull".
   - *Proposal:* `inspect geo {group_by: "name", stats: ["bbox", "count"], where:
     "surface == 'decal'"}`, and vertex attributes filtered by a prim group (promote
     internally).
5. **Medium: the HDA lifecycle needs version bumps.** 1.0 to 1.1 took copyToHDAFile under
   a new name, an install and changeNodeType. Then came a folder inserted at a position,
   a PythonModule, changed defaults on the definition, and a save with relock. *Proposal:*
   `hda {action: "version", node, new_version, keep_old: true}`, plus interface ops that
   take `after: "<folder>"` and `default` changes.
6. **Medium: `look` is unusable on production geometry.** The Flipbook timed out at 30 s on
   0.5 M triangles (P2 #9 again), so every visual check was a Karma render plus a local
   Read. *Proposal:* `look` with a bounding-box or LOD proxy, or a raised timeout with
   progress.
7. **Medium: menu candidates are cut off at 20.** `subnetconnector parmtype` has more than
   40 items, and the right one (`atmosphere`) was not shown. *Proposal:* rank candidates
   by similarity to the rejected value (`volume` against `atmosphere`, by label "Volume
   Shader"), or list all of them for an invalid_value.
8. **Low: image analysis and sheets are local.** Luminance matching for the LOD2 fix,
   contact sheets, bloom and JPG size limits were all done in PIL. *Proposal:* `inspect
   image` on a rendered file with region or mask stats, and `render {output, format:
   "jpg", max_kb}`.
9. **Low: output noise.**
   - Karma ROP parms (8 KB of tonemap ramps, P2 #10).
   - `full_strings` repeats channel-referenced values.
   - The edit summary lists every node.
   - `inspect network` rejects `wiring` and `cook_uncooked` while `node` accepts them.
10. **Low: `$id` is not substituted inside string parm values.** Light rigs wanted
    `lookatpath: "$target"`. *Proposal:* substitute a whole-value `$id` in string parms,
    or accept `{"node": "$id"}` as a value.

What worked well:

- `render` again: Karma `/obj` ROPs with camera, object and light lists, Copernicus
  `rop_image` frame ranges (14 texture frames per map), FBX ROPs and USD. It always
  restored overrides.
- `edit` `copy`: copying a `color3FA` multiply node avoided the mtlx signature escape from
  P2, which put the grime layer into 8 materials with no Python.
- `edit` built 16 Font nodes with Japanese text and expressions in one call.
- The error that listed all 19 problems at once (#8) was fixed in one resend.
- `parm_set press: true` ran the HDA's Python buttons.
- The "Use press: true" and "'Cd' is a vertex attribute" hints.
- Pinning: the GUI Houdini (48868) stayed untouched for the whole phase.

### Capability verdicts

| Area | Verdict | Notes |
|---|---|---|
| Silhouette volumes, fins, sleeves, annexes, bridges, billboards, clutter | native | VEX through `edit`. The long snippets were loaded from files by escape (value_file gap) |
| Style presets (menu callback, PythonModule) | escape hatch | HDA interface and section editing |
| HDA versioning 1.0 → 1.1, save, relock | escape hatch | |
| Rain-streak mask (ray cast), per-piece tone | native | |
| Procedural decal and grime textures in Copernicus | native | Font nodes, wrangles, Switch frames, `rop_image` |
| MaterialX grime layer, decal material with opacity | native | the `copy` trick avoided P2's signature escape |
| LOD2 calibration | native, plus local measurement | luminance measured in PIL |
| Collision crown fix | native | the hull report needed Python |
| Lookdev (latlong sky from Copernicus, fog volumes, spot rig from fixtures, OIDN) | native | the fixture positions were read by escape |
| Variation block and cut-away | native | |
| FBX engine check | native | File SOP, blast, material bind by slot name |
| Evidence and contact sheets | native render, local sheets | |
| Export re-run | native, blocking | `export_all` press, `houdini_busy` |

## Overall assessment

**Can these tools produce a AAA procedural skyscraper generator?** They can produce the
generator and the pipeline. They have not, in three phases, produced AAA-quality output,
and the gap is mostly the agent's, not the tools'.

The asset pair now has:

- a fast design asset with four art-directed presets and 20 silhouette parms on top of
  the P1 massing, facade and interior system;
- an export asset with three LODs, convex collision, trim-sheet, atlas and tiling UVs,
  59 procedural textures, 15 MaterialX materials with grime and decal layers, and FBX
  and USD outputs;
- a stated contract and polygon budgets.

Every step from an empty scene to an engine-ready FBX went through the HocusPocus tools.
The 37 Python escapes were HDA lifecycle, string transport and analysis, never modelling.
A team could put this generator in a pipeline as it stands.

**Tool-limited** (each cost time; none blocked a result):

- the main thread blocks during renders and presses (about 19 min of renders plus the
  export presses);
- no file-backed values or patches in 2.0.0 (14 escapes, about 70 KB of VEX moved around
  the tool);
- up-front `edit` validation (4 split calls);
- no geometry or image analytics (10 Python reads, local PIL);
- `look` timeouts on real geometry.

The 2.1 streams already in flight (`hda`, `edit patch`, `value_file`, validation fixes)
cover 21 of the 37 escapes.

**Agent-limited** (what decides whether the result is AAA):

- *All geometry is hand-written VEX*: about 60 KB in P1 and 70 KB in P3, plus P2's
  texture and SOP wrangles. Quality is
  bounded by spatial reasoning in text. The 1.1 additions are boxes, prisms and lofts.
  Annex volumes are rectangles on every footprint, bridges run straight, and the clutter
  is placed by rule. A human artist's kitbash pieces would read richer.
- *Visual judgement at 1600 px.* I judged every image by eye, but I cannot see
  sub-centimetre z-fighting, mip bleed or normal-map seams. The grime ended up subtle
  because I raised it only until it read in close-ups (`p3_07`). From far away the
  towers still look clean.
- *Composition and lighting.* The dusk and night images read as the art direction (armoured
  Tokyo-3 spires against a sunset; Neo-Tokyo slabs with searchlights and billboards).
  But a lighting artist would push contrast, atmospheric depth and focal hierarchy
  further.
- *Silhouette.* The fins, sleeves and crown hardware make Tokyo-3 read as armoured rather
  than office. The Neo-Tokyo slab and stack read as dense megablocks. The variation block
  (`p3_03`) still shows the family resemblance of a single generator: all towers are
  extrusions of one footprint shape per tower.

**What remains before shipping quality:**

1. **An LOD2 impostor bake** of LOD1 (`karmatexturebaker`), so the window pattern matches
   as well as the brightness. Then HLOD and Nanite-style settings for city blocks.
2. **Interior mapping for LOD0 windows** (a parallax cubemap atlas), so the P1 interiors
   show from outside without the full geometry.
3. **LOD0 cost.** The presets reach 0.33 to 0.79 M triangles. Interiors are on demand, but
   the facade alone is 0.3 M or more on big towers. Instanced module kits (packed
   primitives exported as instances) would cut memory a lot.
4. **Lightmap or AO bakes into `uv2`**, and a texture budget. 59 maps at 2K are about
   1 GB as uncompressed RGBA8, or about 0.3 GB with block compression and mips.
   Engine-ready packing needs channel packing, BC formats and streaming groups.
5. **A real engine import.** The "engine check" here is a flat-lit Houdini render of the
   re-imported FBX. An Unreal or Unity import, with collision, material slot and LOD-group
   checks, is the real test.
6. **Richer massing grammar:** tier shapes that change per tier, non-box annexes,
   curved bridges, and crown and clutter kits. Plus a human art-direction pass on the
   presets.
7. **Decals that wrap corners** (projected decals in the engine, rather than baked quads),
   and grime strong enough to read from a distance.

The tools are ready for this work. The next gains come from the 2.1 tool fixes for the
agent's iteration speed, and from human art direction for the last mile.
