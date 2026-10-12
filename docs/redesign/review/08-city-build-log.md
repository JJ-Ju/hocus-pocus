> **Status: historical.** Evaluation record of 1.0 at commit `b56666d` on 2026-10-12. See [`../README.md`](../README.md).

# 08 — City build log: a building generator and a city generator driven through HocusPocus 1.0

**Seat:** an AI agent working as a Houdini TD. I used only the MCP tool surface, `docs/tools.md`, `README.md` and `docs/quickstart.md`. I did not read the server source.
**Build:** `redesign/v1` @ `b56666d`, bridge `1.0.0a0`, profile `core`.
**Host:** Houdini FX 22.0.466 GUI, pid **63324**, launched by `houdini_connect {"launch":{"mode":"gui"}}` (see §0 for why it is not the planned pid 63360). It is no longer running: it exited when its bridge was stopped after the session.
**Date:** 2026-10-12, about 09:46 to 10:03 local time (roughly 17 minutes of wall clock, including diagnosis).
**Result:** `/obj/building_gen` and `/obj/city_gen` built and cooked with 0 problems. The city has **191 buildings** and **80,123 polygons** (79,738 of them in buildings), a 30-building `district` group, and three evidence PNGs. The hip is saved as `<scratch>/city/city_v01.hip` (241,977 bytes, `dirty: false`).

Byte counts below are the size of the pretty-printed `structuredContent` (indent 1) that my caller wrote for each call. They are not wire bytes. Wire bytes are about twice as large, because text and structured copies are both sent (see review 07).

---

## 0. Getting a host: the planned GUI was gone, and a launched GUI dies with its bridge

1. **The brief's Houdini (pid 63360) was not running.** The first `houdini_status` logged `pruned stale registry entry for dead pid 63360` and returned `connected: null, instances: []`. `Get-Process` showed no 63360. The only Houdini on the machine was pid 59436 (Houdini Indie, not registered with HocusPocus). I left it alone, as instructed.
2. **`houdini_connect {"launch":{"mode":"gui","wait_s":240}}` worked.** It returned pid 22740 in about 6 s. But the one-shot caller (`hp.py`) starts a new `hocuspocus-mcp` bridge for each call. When that bridge exited, the Houdini it had launched exited too. The next call logged `pruned stale registry entry for dead pid 22740`, and `node_type_info` failed:
   ```
   {"code":"houdini_offline","message":"No live Houdini instance with HocusPocus is running.",
    "retryable":false,"hint":"call houdini_connect with launch to start one"}
   ```
   The hint was correct but did not help here, because launching again from a one-shot bridge has the same outcome. Nothing in the `houdini_connect` description says that a launched instance is owned by the bridge and dies with it. I found out by observing it.
3. **A plain `houdinifx.exe` does not load the host.** `Documents/houdini22.0/packages` is empty, so the bridge must inject the package at launch. The instance I started by hand sat on "Houdini Console" and never registered, so I killed it. That was my own process.
4. **Workaround:** I wrote a small persistent client in my scratch dir (`city/drv.py`). It is the same `mcp.Client` and `hocuspocus-mcp` command and environment as `hp.py`, but it stays alive and reads requests from an inbox dir. Through it I called `houdini_connect launch gui` once (pid 63324), and that instance served every call. **Consequence:** Houdini 63324 stayed alive only while that driver process ran. After the build, the agent harness stopped the driver as a background task (exit 255), and Houdini 63324 exited with it. The saved hip is intact. So the "leave Houdini running" requirement could not be met with a bridge-launched instance. Reopening `city_v01.hip` needs a host that outlives its client: a GUI with the package installed, or a detachable launch (improvement 2).

---

## 1. What I built

### `/obj/building_gen` (geo): reusable building generator

```
CONTROLS (null + spare parms: seed, width_min, width_max, floors_min, floors_max, floor_h, roof_type[-1 random,0 parapet,1 penthouse,2 pyramid])
lot_from_controls (attribwrangle, detail) -> LOT (null)        one point holding w, d, floors, floor_h, win_rows, bays_x, bays_z,
                                                                roof_type, seed, bldg_id, district, ry, height_class
building core (every parm reads point("../LOT", 0, ...)):
  mass (box, polymesh, divrate = bays+1 / win_rows+1)
  -> tag_faces (wrangle, prim: groups facade / roof / base by centroid height)
  -> windows (polyextrude facade, individual elements, inset 0.45, dist -0.3, front group "glass")
  -> roof_base (polyextrude roof: parapet recess, penthouse ring or pyramid ring, by roof_type)
  -> roof_cap (polyextrude roof_top: penthouse block 4 m, or pyramid with inset)
  -> roof_switch (switch: parapet skips roof_cap)
  -> building_attrs (wrangle, prim, input 1 = LOT: bldg_id, name "bldg_###", height_class, district + group, Cd wall/glass)
  -> clean_groups (groupdelete facade roof base roof_top)
  -> place_on_lot (xform to LOT P and ry)
  -> OUT_BUILDING (null, display/render)
```
- The output is a closed polygon shell. It is a single mass with inset windows, which suits Voronoi fracture.
- The default seed (7) gives about 464 polys. The worst case I tested (40 m footprint, 40 floors, penthouse) gives **1,664 polys**. `win_rows` is capped at 20 and bays at 4, which keeps every building under 2,000.
- The object display flag is **off**, so the preview building does not sit in the middle of the city. Its `OUT_BUILDING` still has display and render flags set inside the object.

### `/obj/city_gen` (geo): city generator

```
CONTROLS (null + spare parms: seed 42, blocks 8, block_size 40, street_width 12, sidewalk 3, floor_h 3.2, district_count 30)
lot_layout (wrangle, detail): 8x8 blocks, each split into 2-4 lots (strips or 2x2), one point per lot.
   height_class by normalised distance from centre: tall < 0.3 (14-30 floors), mid < 0.6 (6-12), low (2-5).
   argsort of distance: the 30 nearest lots get point attr district=1 and point group "district".
foreach_lot (block_begin, piece) -> LOT (null) -> [building core, node_copy of building_gen's chain] -> foreach_lot_end (block_end, merge, per point)
   -> OUT_BUILDINGS (null)
block_points (wrangle) + sidewalk_slab (box 40x0.25x40) -> sidewalks (copytopoints)
street_plane (grid 428x428) + sidewalks -> ground_merge -> ground_attrs (name "ground", bldg_id -1, Cd) -> OUT_GROUND (null)
OUT_GROUND + OUT_BUILDINGS -> city_merge -> OUT_CITY (null, display + render, commented)
```
- **Final `geo_info` on `OUT_CITY`:** 80,636 points, 80,123 polygons, bbox 428 × 93.05 × 428. Prim groups: `district` 22,162 prims and `glass` 14,614 prims.
- **Prim attributes:** `name` (`bldg_000`..`bldg_190`, plus `ground`), `bldg_id` (-1 for ground), `height_class` (low, mid, tall, ground), `district` (int), `Cd`.
- **Building count:** `geo_read` stats on `OUT_BUILDINGS` show 191 unique `name` values and `bldg_id` 0..190. The `lot_layout` point stats give a `district` mean of 0.157, which is 30 of 191. The district contains `bldg_057`..`bldg_061`, `bldg_077`..`bldg_085`, `bldg_099`..`bldg_104` and others: 30 names in total.
- **Handoff notes for the destruction agent:** fracture the `district` prim group of `/obj/city_gen/OUT_BUILDINGS`, or of `OUT_CITY`, and use `name` as the piece attribute. `OUT_GROUND` is the static collider. Comments on `OUT_CITY`, `OUT_BUILDINGS`, `OUT_GROUND`, `CONTROLS`, `lot_layout` and `foreach_lot` record all of this inside the hip.
- **Cameras:** `/obj/cam_overview` (t 280,230,280, r -30,45,0, 35 mm) and `/obj/cam_street` (t 4,1.8,175, eye level on the x=0 avenue looking at the towers, 22 mm). Both are 1280×720.

### Evidence (`docs/redesign/evidence/city-destruction/`)

| File | Source | Size |
|---|---|---|
| `01_building.png` | `opengl_rop`, fit all, 1280×720, city hidden | 127 KB |
| `02_city_overview.png` | `opengl_rop`, `cam_overview`, **1024×576** (1280×720 came out at 717 KB, over the limit) | 503 KB |
| `03_city_street.png` | `opengl_rop`, `cam_street`, 1280×720 | 247 KB |

---

## 2. Tool calls

**74 tool calls.** Calls 1–5 went through one-shot `hp.py`. Calls 6–74 went through the persistent driver, which uses the same server and arguments.

| Tool | Calls | Avg bytes | Notes |
|---|---:|---:|---|
| geo_info | 15 | 985 | Workhorse for checking each step. Stayed near the documented ~1 KB, even for the 80k-prim city. |
| parm_set | 11 | 1,046 | 2 errors (below) |
| viewport_capture | 9 | 421 (+ image) | 2 were wasted on `source: viewer` (see problem 3) |
| node_create | 6 | 8,124 | Largest single response was 20,264 B (12 nodes) |
| node_type_info | 5 | 3,099 | polyextrude compact was 9,876 B. 1 call failed offline in §0 |
| node_edit | 5 | 1,404 | flags, colours, comments |
| houdini_status | 4 | 566 | |
| problems | 3 | 289 | |
| geo_read | 3 | 633 | `stats` with `count:1` gives unique names and min/max cheaply. Very useful. |
| cook | 3 | 274 | |
| node_layout | 2 | 2,008 | |
| houdini_python | 2 | 208 | Spare parms only (see §3) |
| houdini_connect | 2 | 683 | |
| parm_get, node_copy, node_connect, hip_save | 1 each | 1,984 / 5,154 / 538 / 261 | |

**Total structured bytes:** about 121 KB, plus 9 images. The 3 node_create calls with VEX snippets were 45% of all text bytes.

`network_build` and `network_describe` were never needed. Batched `node_create`, with `inputs` wired to nodes created earlier in the same call, covered every graph. It built 12 nodes with full wiring and expressions in one undo step, and it did so on the first try.

---

## 3. Every `houdini_python` use

| # | Call | Why |
|---|---|---|
| 1 | Add a `Building` folder with 7 spare parms to `/obj/building_gen/CONTROLS` | No typed tool creates spare parms or parm templates. I confirmed this first: `parm_set` on `CONTROLS/seed` returned `parm_not_found` (below). `node_edit` has no parm-template option either. |
| 2 | Add a `City` folder with 7 spare parms to `/obj/city_gen/CONTROLS` | Same reason. |

Nothing else needed Python. Without spare parms, the fallback would have been to keep the controls as detail attributes in a wrangle. That works, but the result is not a real control panel.

---

## 4. Errors and surprises (exact messages)

**Tool errors (isError):**
1. `node_type_info`, call 4, after the one-shot launch died:
   `houdini_offline: "No live Houdini instance with HocusPocus is running."`, with hint `call houdini_connect with launch to start one`. The hint was accurate but **did not help**, because the cause was the instance's lifetime (§0).
2. `parm_set` on `/obj/building_gen/CONTROLS/seed` (a deliberate probe):
   `parm_not_found: "/obj/building_gen/CONTROLS/seed: No parm or parm tuple 'seed' on /obj/building_gen/CONTROLS."`, with hint `List the node's parm names with node_info (include_defaults: true).` The message is accurate, but the hint **does not help** when the goal is to *add* a parm. It could say "spare parms: use houdini_python".
3. `parm_set` with `mass/divratex`:
   `parm_not_found: "items[2] (/obj/building_gen/mass/divratex): No parm or parm tuple 'divratex' on /obj/building_gen/mass."`, with hint `Did you mean divrate? It is a tuple: use .../divrate with a list of 3 values, or a component (divrate1/divrate2/divrate3) with a scalar.`, candidates, and `rolled_back: true`. **This was excellent.** I fixed it in one retry. The rollback meant the two items before it were not left half-applied.

**Non-error surprises:**
1. **`viewport_capture` with the GUI viewer ignored `fit`.** Both the default and an explicit `"fit":"all"` returned `fit_used: "none"`, `camera_used: "viewport"`, and an image of the empty construction grid from the default camera. The 35 m building was not visible, and no `notes` entry explained why. `source: "opengl_rop"` framed it correctly every time. Because `auto` picks the viewer in a GUI session, **the default call gives a useless picture in GUI mode**, and the response does not say so.
2. **`viewport_capture` image versus file:** the attached image was downscaled to 1024×576 and composited on grey. The file written to `path` was the full 1280×720 with an alpha background, so it shows white in most viewers. That is fine, but it is not mentioned in the docs.
3. **`cook` timing:** `cook {"paths":["/obj/city_gen/OUT_CITY"],"force":true}` returned `cook_time_ms: 0.1` for a 191-iteration for-each. The first city cook reported `0.0`. The number evidently covers only the named null. It is misleading when you need to judge whether a network is "cheap enough for a sim".
4. **`problems` after a fix:** after I fixed the `city_merge` attribute-mismatch warning upstream, `problems` on `/obj/city_gen` said `"No problems ... Uncooked nodes report no errors; pass cook_uncooked to cook them first."` That was true, but it means a node with a stale warning is not rechecked the way errored nodes are. I had to run `cook` and `problems` with `cook_uncooked` to confirm.
5. **`node_copy` cooks every copy and repeats the same upstream error.** It returned 9 copies of `Invalid sop specified: "../foreach_lot_end"` in 5 KB, which is noise while a block loop is still being assembled. `node_create` did the same for the loop head. These are expected transient errors, and they can't be avoided when a pair of nodes refer to each other by path (block_begin and block_end).
6. **geo_info group class:** on the first, broken build (calls 16 and 18), `geo_info` listed `glass` under `groups.edge` with count 243, equal to the prim count. After the box fix, `glass` appeared under `groups.prim`. I did not dig further, so this is unverified. It may be a real misclassification of a polyextrude front group in the degenerate case.
7. **My own mistakes, not the tool's:** (a) box `type: poly` + `dodivs` gave an open 81-quad lattice. I switched to `polymesh`, where `divrate` counts points, not segments. (b) `prim_normal(0, @primnum, 0.5, 0.5)` put every face into `facade`. I classified by centroid height instead. `geo_info` group counts and an `opengl_rop` capture made both problems obvious within 2 calls each.

---

## 5. Response-size notes

- **node_create echoes full node_info for every node,** including every non-default parm value. That means each VEX `snippet` comes back verbatim, and the input list includes four "Ancillary Input" labels per wrangle. 12 nodes produced 20 KB, and the city head produced 19.5 KB. I needed none of it beyond the paths and the errors.
- **`node_type_info` compact for polyextrude was 9.9 KB.** The `folder` filter helps, but there is no way to ask for just one set of parms, such as the group and extrude ones.
- **`geo_info`, `geo_read` with `stats`, `cook`, `problems` and `hip_save` were all small and dense.** They were exactly right for the verification steps.
- **`viewport_capture` text is about 420 B.** The image cost dominates, so I mostly saved images to disk and looked at them selectively.

---

## 6. Top 5 suggested improvements

1. **A typed spare-parm / parm-template tool.** For example, `parm_template {node, add: [{name, type, label, default, min, max, folder, help}], remove: [...]}`. Exposing controls on a CONTROLS null or an object is the most basic procedural-TD move, and it was the *only* reason I needed `houdini_python`. The `parm_not_found` hint could also point to it when the target is a null or subnet.
2. **Make launched-instance lifetime explicit and controllable.** `houdini_connect launch` should document that the instance is owned by the bridge, and it should offer `detach: true` (or `persist`) so the instance outlives a short-lived or crashed bridge. When `houdini_offline` follows a launch from an earlier bridge, the error could say "the instance launched by a previous bridge exited with it". Today, any one-shot client loses its Houdini silently.
3. **Make `viewport_capture` with the viewer honour `fit`,** or fall back to `opengl_rop` and add a `notes` entry when `fit` can't be applied. The default call in a GUI session should never return an unframed empty grid without a warning.
4. **Add a lean return mode for mutation tools.** For example, `return: "paths" | "summary" | "full"` on `node_create`, `node_copy` and `network_build`, defaulting to paths, flags and errors. Or elide string parms longer than about 200 characters (`"snippet": "<1,234 chars>"`). Collapse repeated identical upstream errors into one "N nodes: same upstream error from X" entry.
5. **Honest cook cost.** `cook` should report upstream (total) cook time, or the time of the whole dependency cook, and `force` should be able to recook the upstream chain. `problems` should recheck nodes with stale warnings, not only errored ones. A procedural build is judged by "how long does the city take to cook", and the tool can't answer that today.

Honourable mention: a `block` helper, or `node_create` support for paired nodes (block_begin/block_end and compile_begin/compile_end), that sets `blockpath` and `templatepath` automatically, the way the TAB menu does. I did it by hand with expected transient errors, and it worked.
