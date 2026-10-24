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
