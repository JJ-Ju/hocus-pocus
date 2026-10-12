# 12 — City rebuild on 1.1: the review-08 workload, measured again

**Seat:** an AI agent working as a Houdini TD. I used only the MCP tool surface and `docs/tools.md`. I did not read the server source.
**Build:** `release/1.1` working tree at `12b07fd` (with that moment's uncommitted host edits), installed editable into a scratch venv. `hocuspocus version` still prints `1.0.0`.
**Host:** Houdini 22.0.466 hython, headless, pid **57600**, started with `hocuspocus launch --headless`. I killed it at the end of the session.
**Client:** a one-shot `mcp.Client` over stdio. Each call started a fresh `hocuspocus-mcp` and exited after the call. Every call was logged with tool, args bytes, result text bytes and isError.
**Date:** 2026-10-12, 16:53 to 17:00 local time (about 7 minutes of tool time).
**Result:** `/obj/building_gen` and `/obj/city_gen` built and cooked with 0 problems. The city has **191 buildings**, a 30-building `district` group and `OUT_CITY`. I used **0 `houdini_python` calls**. The hip is saved as `<scratch>/city11/city_v01_1.1.hip` (182,711 bytes, `dirty: false`). The evidence image is `docs/redesign/evidence/city-destruction/02_city_overview_1.1.png` (960×540, `opengl_rop`, `cam_overview`, 382 KB).

**How bytes are counted.** 1.1 returns text only, so `structuredContent` is absent. The "text" column is the exact text the model receives. To compare with review 08, which counted `structuredContent` pretty-printed at indent 1, I also re-printed each text result the same way. That is the "pretty" column, and the side-by-side table uses it.

---

## 1. Build summary

### `/obj/building_gen`
```
CONTROLS (null; 7 spare parms added by node_edit spare_parms, folder "Building":
          seed, width_min, width_max, floors_min, floors_max, floor_h, roof_type menu -1/0/1/2)
lot_from_controls (wrangle, detail) -> LOT (null)
mass (box polymesh, divrate from LOT) -> tag_faces (prim wrangle; facade/roof/base by centroid height)
 -> windows (polyextrude facade, elements, inset 0.45, dist -0.3, front group glass)
 -> roof_base (polyextrude roof: parapet recess / penthouse ring / pyramid ring)
 -> roof_cap (polyextrude roof_top) -> roof_switch -> building_attrs (prim wrangle, input 1 = LOT)
 -> clean_groups (groupdelete) -> place_on_lot (xform) -> OUT_BUILDING
```
- The default seed (7) gives 732 polys and a pyramid roof. The worst case (40 m footprint, 40 floors, penthouse) gives **1,664 polys**, the same figure review 08 reported. I checked parapet and pyramid with `opengl_rop` captures in my scratch dir. The object display flag is off.
- This network took **two `node_create` calls**: the geo and CONTROLS, then 12 nodes in one batch. It also took **one `node_edit`** that added both CONTROLS folders. In 1.0 the same work took `node_create` plus two `houdini_python` calls.

### `/obj/city_gen`
```
CONTROLS (7 spare parms, folder "City": seed 42, blocks 8, block_size 40, street_width 12, sidewalk 3,
          floor_h 3.2, district_count 30)
lot_layout (detail wrangle: 8x8 blocks, 2-4 lots each, height_class by distance, 30 nearest = district)
foreach_lot (block_begin, piece) -> LOT -> [building core, same 10 nodes] -> foreach_lot_end (block_end, merge, per point)
 -> OUT_BUILDINGS
block_points + sidewalk_slab -> sidewalks (copytopoints) ; street_plane (grid 428) ; -> ground_merge -> ground_attrs -> OUT_GROUND
OUT_GROUND + OUT_BUILDINGS -> city_merge -> OUT_CITY (display/render, commented)
```
- **The whole loop and the ground were one `node_create` batch of 23 items.** `foreach_lot_end` came back with `"paired_with": "/obj/city_gen/foreach_lot"`. No item reported a transient error. In 1.0, `node_copy` returned 9 copies of `Invalid sop specified: "../foreach_lot_end"`.
- **Final:** 191 unique `bldg_id` (0..190), 30 unique `name` values in the `district` prim group, 53,910 points, 53,397 polygons, bbox 428 × 92.8 × 428. Prim attributes are `name`, `bldg_id`, `height_class`, `district` and `Cd`. Prim groups are `district` and `glass`. `problems {cook_uncooked: true}` on `/obj` reported 0.
- **Polygon count:** my lots are subdivided less finely than review 08's, so the total is 53k polygons where 1.0 had 80k. Building count, district size, footprint and height classes match. To land on exactly 191 lots I tuned the 2×2-split probability with 4 `parm_set` calls on the wrangle `snippet`. Those 4 calls cost 23 KB (see papercut 1).
- `cam_overview` is at t (280, 230, 280), r (-30, 45, 0), 35 mm, 960×540. OUT nodes, `lot_layout` and `foreach_lot` carry comments for the destruction hand-off.

### Inspection and cost
- **`network_describe {root: "/obj", format: "outline"}`**: 39 nodes in one call, 4,430 B of text. It was enough to confirm both trees and their display nodes.
- **`cook {paths: [OUT_CITY], profile: true}`**: `total_ms` **367.2**. The chain shows `foreach_lot_end` at 355.9 ms (97 %), `city_merge` at 7.0 ms, and the rest of the top 10 at 1.3 ms or less each. 1.0 reported `cook_time_ms: 0.1` for the same question. The cost is now visible: the loop accounts for nearly all of it. The response does not split that cost among the nodes inside the loop body (papercut 5).

---

## 2. Side by side

| Metric | 1.0 (review 08) | 1.1 (this run) |
|---|---:|---:|
| Host | GUI launched by `houdini_connect`; died with each bridge. A persistent driver process was needed. | `hocuspocus launch --headless` in **1.7 s**. Survived **57 one-shot clients**. |
| Total tool calls | 74 | **58** (51 build calls + 7 deliberate probes or measurements) |
| Total result bytes | ~121 KB (pretty) | **91.2 KB pretty / 73.4 KB text**, of which 23 KB was 4 snippet `parm_set` calls |
| `node_create` calls, avg bytes | 6 calls, 8,124 avg | **4 summary calls, 1,717 avg** (pretty), 1,322 text |
| `node_create` bytes per node | ~1,690 (20,264 B / 12 nodes) | **~172** (6,866 B / 40 nodes) |
| Largest `node_create` | 20,264 B (12 nodes) | 3,884 B (**23 nodes**, whole for-each loop) |
| `node_create return: full`, 373-char snippet | snippet echoed verbatim (twice) | 1,642 B; snippet shown as `{"elided": 373, "head": ...}` |
| `node_type_search` | not used | 3 calls, 1,150 avg; polyextrude query → 1 row with `other_versions` (348 B) |
| `node_type_info` | 5 calls, 3,099 avg; polyextrude compact 9,876 B | 11 calls, 1,731 avg; largest 5,339 B (one folder subtree). 4 of the 11 went to working around the folder filter. |
| `houdini_python` uses | 2 (spare parms) | **0** |
| Spare parms | `houdini_python` | `node_edit spare_parms`, both CONTROLS in 1 call (1,698 B) |
| Block pairing | manual `blockpath`, 9 transient errors in 5 KB | automatic, `paired_with`, 0 transient errors |
| City cook cost | `cook_time_ms: 0.1` (only the null) | `profile`: `total_ms 367.2`, loop 355.9 ms |
| Network inspection | not used (`network_describe` data too large) | `outline`: 39 nodes in 4,430 B text |
| Tool errors | 3 (1 offline, 2 `parm_not_found`) | 5 (2 deliberate probes, 1 my path quoting, 1 menu default, 1 folder filter) |
| `tools/list` the model sees | 34,557 B (review 07) / 38,460 B serialised (review 11) | **30,626 B** serialised (31 tools, no `outputSchema`) |
| Buildings / polys | 191 / 80,123 | 191 / 53,397 |
| Hip | 241,977 B | 182,711 B |

**Host lifetime test.** `hocuspocus launch --headless` printed the registry entry as one JSON line on stdout: pid, port, label, version, ui, hip, started, mode and log path, with no token. On stderr it printed `Houdini pid 57600 is running and outlives this command; attach ... houdini_connect {"pid": 57600}`, then exited 0. Every later call started and stopped its own `hocuspocus-mcp`. After the build, `tasklist` showed no `hocuspocus-mcp.exe` running and `hython.exe 57600` still alive (543 MB). A fresh client's `houdini_status` auto-selected 57600 with the saved hip and `dirty: false`. I then ran `taskkill /PID 57600 /F`. The next `houdini_status` logged `pruned stale registry entry for dead pid 57600` and returned `connected: null` with a warning that names `houdini_connect {launch}`. Review 08's improvement 2 is resolved for this workflow.

---

## 3. Friction log (in call order)

1. **`node_type_search` worked as advertised.** `polyextrude` returned one row, `polyextrude::2.0`, with `other_versions: ["polyextrude"]`. That is 348 B, where 1.0 returned two versions plus noise. For "copy to points", `total` read `200` for 5 rows shown, which looks like a cap rather than a count.
2. **`node_type_info parms` takes one glob only.** `"*inset*|*dist*|*group*|..."` returned `parms: {}`, with the hint `No parm name or label matches ...; globs are case-insensitive`. The hint does not say that alternation is unsupported.
3. **The `folder` filter cannot reach unfoldered parms.** `detail: folders` listed `{"folder": "(no folder)", "parms": 12}` first. Passing `folder: "(no folder)"` failed with `invalid_argument: No folder '(no folder)'` and a candidate list that leaves it out. On polyextrude those 12 parms are the important ones: `group`, `splittype`, `dist` and `inset`. I reached `splittype` with `parms: "split*", detail: full` and guessed the rest. That cost 4 calls.
4. **`node_edit spare_parms` menu default.** `"default": -1` failed with `default -1 is not one of the menu tokens`, hint `Tokens: -1, 0, 1, 2 (or an index)`. The string `"-1"` worked, and the hint got me there in one retry. Then `parm_get` showed that `type: menu` makes a **string** menu parm, so VEX needs `atoi(chs(...))`, not `chi()`. Neither the description nor the error says so, and there is no option for an int-valued menu.
5. **The 12-node building core worked on the first try** (2,124 B). Component names such as `divrate1` and `sizex` in `node_create` parms just worked.
6. **The 23-node city batch with automatic pairing worked on the first try.** `paired_with` was reported and no errors appeared.
7. **Tuning `lot_layout` through `parm_set` on `snippet` cost 5,783 B per call.** The whole VEX came back twice, as `value` and as `raw`. `node_create return: full` elides strings over 200 characters, but `parm_set` does not.
8. **The outline marks every `attribwrangle` as `"hda_locked": true`.** Wranglers are locked HDAs internally, so this is technically true, but it is noise in a tree view. `node_create return: full` shows the same flag.
9. **Profile attribution.** See §1. `results[0].cook_time_ms: 0.0` sits next to `total_ms: 367.2`, which reads oddly but is documented ("its own cook").
10. **Hints on the deliberate probes.** `parm_set` on a missing CONTROLS parm now says `To add a control parm, use node_edit spare_parms.` That is the fix review 08 asked for. The `divratex` hint is still excellent: it names the tuple, gives the components and lists candidates. `rolled_back: true` is still reported.
11. **A mistake that was mine.** Shell quoting turned a `path` into one without `.png`. The error (`'path' must be a .png file`) was clear. The capture with `camera` reported `fit_used: "none"`, as it should. The file written to `path` has an alpha background, so it shows white in most viewers. That is still not mentioned in the docs.
12. **Two smaller oddities.** `houdini_status` right after `launch` says `$HIP is the launch directory until you hip_save`, but `HIP` was `C:/Users/jujun` although I ran `launch` from my scratch dir. `hocuspocus version` on `release/1.1` still prints `hocuspocus 1.0.0`.

---

## 4. Top 5 remaining papercuts

1. **`parm_set` echoes long string values in full, twice.** A `snippet` edit returns the whole VEX as both `value` and `raw`: 5.7 KB per call. Four tuning calls were 25 % of all result bytes in this session. Apply the `node_create full` rule (elide strings over 200 characters, `{elided, head}`), and drop `raw` when it equals `value`.
2. **`node_type_info` can't target a node's main parms cheaply.** `folder: "(no folder)"` is listed by `detail: folders` but rejected. `parms` takes one glob, so `a|b` silently matches nothing. Accept the `(no folder)` label, or add `folder: ""` for top-level parms, and support `|` or a list in `parms`. Either would have saved 3 of my 11 type-info calls.
3. **The spare-parm `menu` type is string-only, and nothing says so.** Document that `menu` makes a string parm whose value is the token, accept a numeric `default` that matches a token, or add `int_menu` (an int parm with a menu) so `chi()` works. Today the agent finds out from `parm_get`.
4. **The outline view could be leaner and more useful.** It gives 114 B per node: `path` and `name` repeat each other, `children_count: 0` appears on every SOP, and `hda_locked: true` appears on every wrangle. It also omits the wiring (input sources) and the flags that make an outline readable. Drop `name`, omit zero counts, show `hda_locked` only for non-SOP-builtin assets (or only on containers), and add `inputs: [names]` plus a display/render marker.
5. **Profiled cooks stop at the loop boundary.** `chain` attributes 97 % to `foreach_lot_end` and lists body nodes at their single-iteration cost (≤ 1.3 ms). That doesn't say which body node to optimise. Report loop bodies as iterations × per-node cost (or use Houdini's perf monitor for the profiled cook). Also omit or relabel the 0.0 `cook_time_ms` in `results` when `profile` is on.

Honourable mentions: `node_type_search total` reads 200 for a broad query, and the overview PNG from `path` has an alpha background. `houdini_status` reports `HIP` as the home dir after `launch` from another cwd, and `hocuspocus version` is not bumped to 1.1.
