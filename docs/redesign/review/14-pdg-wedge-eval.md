# 14 — PDG wedge on 1.1: a TOP network driven through `pdg`, `job` and `events`

**Seat:** an AI agent working as a pipeline TD. I used only the MCP tool surface, `docs/tools.md`, the README and the quickstart. I did not read the server source.
**Build:** `release/1.2` at `c812972` (1.1.0 code plus the 1.2 plan). It was installed editable at first. Partway through the session another agent's uncommitted edit left `src/hocuspocus/bridge/instructions.py` with a syntax error, and my next one-shot bridge died in `initialize` with `Connection closed`. From that point I ran the bridge from a clean `git archive c812972` snapshot in my venv. `tools/list` was 36,821 B serialised (35 tools, `full` profile) both before and after the switch.
**Host:** Houdini 22.0.466 hython, headless, pid **54696**, started with `hocuspocus launch --headless` in 1.7 s. It had its own `HOCUSPOCUS_STATE_DIR`, a scratch `HOUDINI_USER_PREF_DIR` whose `hocuspocus.toml` says `profile = "full"`, plus `HOCUSPOCUS_PROFILE=full` and `HOCUSPOCUS_WORK_DIR=<scratch>/pdg`. I killed it with `taskkill /T` at the end.
**Client:** a one-shot `mcp` client over stdio. Each call started a fresh `hocuspocus-mcp`. Every call was logged with tool, args bytes (compact JSON), result text bytes, `isError` and elapsed time.
**Date:** 2026-10-12, 20:04 to 20:14 local time (about 10 minutes, 28.6 s of it inside tool calls).
**Result:** 8 wedges cooked through two ROP Fetch TOPs into 8 `.bgeo.sc` files and 8 OpenGL PNGs. A forced failure, a subset recook, two cancels and a final clean cook all ran through `pdg`/`job`. I used **0 `houdini_python` calls**. The hip is `<scratch>/w14/pdg/wedges.hip` (176,753 B). The evidence image is `docs/redesign/evidence/city-destruction/40_pdg_wedges.png` (1960×826, 184 KB).

---

## 1. What I built

### `/obj/bldg` (building generator)
```
CONTROLS (null; node_edit spare_parms, folder "Building": seed int 1, hmin 12, hmax 45, floor_h 3.2)
mass (box polymesh; sizex/sizez = fit01(rand(seed*k), 8, 16);
      sizey = floors(fit01(rand(seed*7.13), hmin, hmax) / floor_h) * floor_h; ty = sizey/2;
      divrate1..3 from size, one division per floor)
 -> tag_faces (prim wrangle: facade/roof groups by prim_normal, Cd from seed, i@seed stamped)
 -> windows (polyextrude::2.0, group facade, elements, inset 0.35, dist -0.25)
 -> OUT (null, display/render)
/obj/cam_bldg   t (70, 45, 70), r (-10, 45, 0), 480x360
/out/geo_bldg   geometry ROP, soppath /obj/bldg/OUT, sopoutput $HIP/geo/bldg_`@wedgeindex`.bgeo.sc
/out/ogl_bldg   opengl ROP, camera /obj/cam_bldg, picture $HIP/render/bldg_`@wedgeindex`.png, 480x360
```
- **The build took 3 calls.** `node_create` made the geo and CONTROLS. `node_edit spare_parms` added the four parms in one call (487 B). A second `node_create` made 7 nodes: the 4 SOPs with all their expressions, the camera and both ROPs (1,882 B in, 810 B out). Everything worked on the first try. After a viewport capture I fixed the division count with one `parm_set` (box `divrate` counts points, not segments) and moved the camera twice.
- **Seed 1** gives 258 points, 256 polys, 15.4 × 16 × 11.9 m, a 48-prim `facade` group and an 8-prim `roof` group (`geo_info`, 608 B).

### `/obj/topnet1` (TOP network)
```
localscheduler (auto-created)
wedge1 (wedgecount 8; wedgeattributes 2:
        1 seed  int   range 1..97   "Parameter Value" -> /obj/bldg/CONTROLS/seed
        2 hmax  float range 20..80  "Parameter Value" -> /obj/bldg/CONTROLS/hmax)
 -> fetch_geo (ropfetch, roppath /out/geo_bldg)
 -> fetch_ogl (ropfetch, roppath /out/ogl_bldg)
 -> output1 (output, display)
```
- **The whole network was one `node_create` batch of 5 items** (870 B in, 626 B out). It included the multiparm count (`"wedgeattributes": {"multiparm_count": 2}`) and the instance parms `name1`, `intrange1`, `channel2` and so on, in the same `parms` dict. One `parm_get` of 10 paths confirmed every value had landed (2,004 B).
- **Type discovery:** `node_type_search` in the `Top` category found `wedge`, `ropfetch` and `output`. `node_type_info Top/wedge` in compact mode was 5,229 B. It was the largest single result of the session, and it was worth it, because it shows the whole `Wedge Attributes[]` multiparm template. A second, targeted `detail: full` call with `parms: "type#|wedgetype#|valuetype#"` returned the menu tokens in 1,061 B.

### Outputs
- The first non-blocking cook of `output1` finished **8/8 in 17.8 s** (24 work items across three nodes). `pdg workitems` reported each item's `output_files`. All 8 `bldg_N.bgeo.sc` (5.0–14.5 KB) and all 8 `bldg_N.png` (11–42 KB) were on disk at those paths.
- **OpenGL ROP inside PDG works headless.** Each ROP Fetch work item is an out-of-process hython that loads the saved hip and renders. No `viewport_capture` fallback was needed.
- **Wedge values reached the geometry.** I read the files back with a temporary File SOP (`$HIP/geo/bldg_$F.bgeo.sc`) and ran `cook {frame_range: [0, 7], summary: "bbox"}`. Heights were 12.8, 12.8, 19.2, 41.6, 28.8, 48.0, 64.0 and 73.6 m. Wedge 0's footprint matches seed 1 exactly. `geo_read` of the stamped `seed` prim attribute showed 15 for wedge 1. I had to work the per-item values out this way because `workitems` does not return attributes (papercut 7).
- **Contact sheet:** `40_pdg_wedges.png`. Wedges 6 and 7 are taller than the 60 m I framed the camera for, so their tops are clipped. That was my framing choice and not a tool problem.

---

## 2. Measurements

**Total: 88 logged calls, 9,375 B of arguments, 49,601 B of results, 1 tool error, 0 `houdini_python`.** Two more calls never reached the log. One was my first `houdini_status`: my client used the old `isError` attribute name. The other was the `pdg status` that hit the broken editable install. The build took 22 calls and 25.4 KB. The PDG loop took 66 calls and 24.2 KB.

| Tool (action) | Calls | Args B | Result B | Avg B | Max B | Errors | Avg s |
|---|---:|---:|---:|---:|---:|---:|---:|
| node_type_info | 5 | 386 | 9,442 | 1,888 | 5,229 | 0 | 0.035 |
| pdg workitems | 8 | 578 | 7,813 | 977 | 1,920 | 0 | 0.014 |
| events | 3 | 58 | 4,893 | 1,631 | 2,409 | 0 | 0.011 |
| node_type_search | 3 | 132 | 3,903 | 1,301 | 2,619 | 0 | 0.116 |
| parm_set | 5 | 954 | 3,343 | 669 | 1,535 | 0 | 0.014 |
| job status | 13 | 559 | 2,817 | 217 | 303 | 0 | 0.011 |
| parm_get | 1 | 331 | 2,004 | 2,004 | 2,004 | 0 | 0.011 |
| node_create | 4 | 3,089 | 1,974 | 494 | 810 | 0 | 0.101 |
| viewport_capture | 3 | 589 | 1,642 | 547 | 548 | 0 | 3.731 |
| pdg status | 11 | 593 | 1,542 | 140 | 152 | 0 | 0.012 |
| pdg cook | 7 | 429 | 1,537 | 220 | 227 | 0 | 2.158 |
| houdini_status | 1 | 2 | 1,216 | 1,216 | 1,216 | 0 | 0.012 |
| cook | 1 | 80 | 1,151 | 1,151 | 1,151 | 0 | 0.017 |
| hip_save | 4 | 302 | 936 | 234 | 234 | 0 | 0.022 |
| job result | 2 | 86 | 801 | 400 | 401 | 0 | 0.028 |
| pdg dirty | 6 | 315 | 681 | 114 | 115 | 0 | 0.014 |
| problems | 2 | 46 | 655 | 328 | 438 | 1 | 0.006 |
| job list | 1 | 17 | 640 | 640 | 640 | 0 | 0.014 |
| geo_info | 1 | 24 | 608 | 608 | 608 | 0 | 0.026 |
| node_info | 1 | 36 | 498 | 498 | 498 | 0 | 0.011 |
| node_edit | 1 | 515 | 487 | 487 | 487 | 0 | 0.013 |
| network_describe | 1 | 42 | 478 | 478 | 478 | 0 | 0.010 |
| job cancel | 1 | 43 | 210 | 210 | 210 | 0 | 0.010 |
| pdg cancel | 1 | 53 | 143 | 143 | 143 | 0 | 0.286 |
| geo_read | 1 | 84 | 140 | 140 | 140 | 0 | 0.198 |
| node_delete | 1 | 32 | 47 | 47 | 47 | 0 | 0.014 |
| **Total** | **88** | **9,375** | **49,601** | **564** | 5,229 | **1** | |

- **`pdg` overall:** 33 calls, 11.7 KB. **`job`:** 17 calls, 4.5 KB. **`events`:** 3 calls, 4.9 KB. These three tools together were 53 calls and 21.1 KB, 42 % of all result bytes.
- **About half of `pdg workitems` bytes (4.1 of 7.8 KB) were one absolute prefix** (`C:/Users/.../w14/pdg/`, 128 characters), repeated on every `output_files` entry.
- **`houdini_python`: 0 uses.** Once I would have used it: a failed work item has no error text through any tool. I read the PDG log from disk outside the tool surface instead, only to learn what a message would have said for this report (papercut 1).
- **Errors:** 1. `problems {path}` returned `invalid_argument ... path: unknown property (allowed: root, ...)`. That was my mistake, and the hint fixed it in one retry.
- **Cook timings:** first full cook 17.8 s. Cook with 6 items cached 6.8 s. Blocking cook with 2 failures 2.5 s. Subset recook of 2 items 2.4 s. Final full cook 16.1 s.

---

## 3. Friction log (in call order)

1. **Setup.** The scratch `HOUDINI_USER_PREF_DIR` made `hocuspocus doctor` report `[FAIL] package JSON ... missing`. `launch --headless` worked anyway, because it runs `hython -m hocuspocus.host`. Doctor could say that headless launch does not need the package. `houdini_status` showed `$HIP` as my `HOCUSPOCUS_WORK_DIR`, so the review-12 `$HIP` complaint does not reproduce when the variable is set.
2. **`node_type_search {query: "rop", category: "Top"}`** ranked `ropfetch` 5th of 12, behind `ropfbx`, `ropnet`, `ropusd` and `ropgltf`. `output` in the Top category is described as "Subnet output". It still works as the terminal node in a `topnet`, but the description made me hesitate.
3. **The wedge multiparm in a single `node_create` worked.** That includes `multiparm_count` together with the `#`-instance parms in the same dict. I expected an ordering problem and none appeared.
4. **`node_type_info` flagged the OpenGL ROP** as `deprecated` ("Replaced by the Flipbook ROP."). It rendered fine inside PDG anyway.
5. **`parm_set` warns about `@wedgeindex`.** Setting `sopoutput` to a path with `` `@wedgeindex` `` returned `warnings: ["Local variable 'wedgeindex' not found."]` and `value: ".../bldg_.bgeo.sc"`. That is correct outside a PDG cook, but alarming the first time. A note such as "`@attr` resolves only inside a PDG cook" would help.
6. **`parm_set` still echoes redundantly.** An expression comes back three times (`raw` and `expression` are identical, next to `value`). Plain numeric tuples come back as `"raw": ["60","36","60"]`. That is the review-12 papercut 1, in a smaller form.
7. **The first non-blocking cook was smooth.** The reply names its own polling call, and `job result` wraps the final `pdg status`.
8. **`job` progress counts only the target node.** Five seconds in, `job status` said `0/8 work items finished` while `pdg status` on the same node already said `cooked_success: 1`. In the cancel run `job list` showed `progress 0.0, 0/8` while `pdg status fetch_geo` showed `cooked_success: 7, scheduled: 1`. The cook has 24 work items. The job only sees the 8 on `output1`, so progress jumps from 0 % to about 90 % in the last third of the cook.
9. **The stale hip was the worst trap of the session.** I changed `/out/geo_bldg/sopoutput` to send wedges 6 and 7 to a missing `Q:` drive, ran `pdg dirty`, and cooked **without saving**. The result was `ok: true`, `cooked_success: 8`. The out-of-process workers loaded the hip on disk and rewrote `bldg_6`/`bldg_7` at the old path. Nothing in `pdg cook`, `job`, `pdg status` or `workitems` mentions that the hip was dirty. A TD learns this; an agent will not.
10. **After a save the forced failure was real, but it had no message.** A blocking cook returned `ok: false`, `cooked_fail: 2`. `workitems` showed `{"id": 63, "name": "fetch_geo_63", "index": 6, "state": "cooked_fail", "output_files": []}`. That is all the tool surface ever says. `problems {root: "/obj/topnet1"}` said `No problems under /obj/topnet1`. `node_info` on `fetch_geo` said `cook_state: "cooked"`, `errors: []`. The real reason sits in `%TEMP%/houdini_temp/wedges/pdgtemp/54696/logs/fetch_geo_63.log`: `Error: Failed to save output to file "Q:/no_such_drive/bldg_6.bgeo.sc".` No tool surfaces that file, its path or its content.
11. **`pdg dirty` is per node, with no work-item subset.** Dirtying `fetch_geo` also dirtied downstream (`output1` went to `uncooked`), which is good, but it is not documented. "Recook a subset" comes from the cache: with `pdg_cachemode` automatic, a recook of `fetch_geo` reran only the 2 items whose files I had deleted (`cooked_cache: 6, cooked_success: 2`, 2.4 s). That works, but you have to know PDG's caching to get it.
12. **`node_type_info` had no menu for `pdg_cachemode`.** `detail: full` returned `{"type": "menu", "default": 0}` with no `menu` key (it is a script menu). I guessed the label `"Write Files"`. `parm_set` matched it and said so in a note (`'Write Files' matched menu label/token '2'`). The label matching saved the call.
13. **`pdg cancel` and `job` disagree.** I cancelled with `pdg cancel` partway through (late, at 7 of 8 upstream items). The reply was the status from *before* the cancel (`cooking: true`). The job then reported `state: "done", progress: 1.0, current: 8`, with `message: "7/8 work items finished"`. `output1` was `incomplete` and `fetch_ogl` showed `cooked_cancel: 1`. A job that was cancelled reads as done.
14. **`job cancel` is right.** One second into a second run, `job cancel` gave `state: "cancelled"` and `error.code: "cancelled"`. `fetch_geo` showed `cooked_cancel: 4, cooked_success: 4`. Two small issues: `message` stayed `"cancellation requested"` after the job was cancelled, and progress stayed `0/8` while 4 upstream items had finished.
15. **`block: true, timeout_s: 120` returned a job after 10.06 s with no note.** This is documented ("capped at the 10 s job threshold"), but the response does not say that it ignored my value.
16. **`events` saw no PDG activity.** Over 6 cooks, 6 dirties and 2 cancels, `events` recorded only node and hip events. Even those had gaps. `/obj/bldg/CONTROLS`, created in the same batch as its parent, has no `ChildCreated`, and neither do the five topnet children. The spare-parm `node_edit` shows up as `FlagChanged` on CONTROLS. Saving the hip records three `ParmTupleChanged` on `/obj/topnet1` (`taskgraphfile`, `checkpointfile` and one with no parm name). Those are noise.
17. **The outline still lacks wiring.** `network_describe outline` on the topnet is 478 B and lists 5 nodes, with no inputs, so it cannot show the chain. This is the review-12 leftover, already in the 1.2 plan.
18. **Evaluator hazard, not a product bug.** An editable install picked up another agent's half-written `instructions.py` (`SyntaxError: unterminated string literal`). Evaluations should install from a snapshot.

---

## 4. What worked well

- **The authoring surface carried a non-SOP network without trouble.** A topnet with a multiparm-heavy `wedge`, ROP paths and an `output` was one 870 B batch, and every authoring call succeeded.
- **The `pdg cook` → `job` loop is the right shape.** The cook returns in 40 ms with a job id and tells you how to poll. `job status` is about 210 B, so 13 polls cost 2.8 KB. `job result` returns a final `ok` plus state counts. `job list` shows history across cooks.
- **`pdg status` is compact and honest.** At 140 B it gives per-state counts (`cooked_success`, `cooked_cache`, `cooked_fail`, `cooked_cancel`, `waiting`, `scheduled`) and a node `cook_state` (`cooking`, `failed`, `warning`, `incomplete`). These were the most useful numbers during a cook, more useful than `job` progress.
- **`pdg workitems` paging works.** `limit` and `next_cursor` work, and `output_files` are absolute and correct. They were enough to check every file on disk with no guessing.
- **`job cancel` stops a PDG cook cleanly** and leaves the graph in a consistent, inspectable state.
- **Blocking cooks are useful for short work.** A 2.5 s failing cook returned `ok: false` with counts in one call.
- **0 `houdini_python`.** The only gap that pushed toward it was diagnosing a failure (papercut 1).

---

## 5. Top 10 papercuts

| # | Pri | Tool / argument | What happens (exact) | Proposed change |
|---|---|---|---|---|
| 1 | **P0** | `pdg workitems`, `pdg cook` result, `job result` | A failed item is only `{"id":63,"name":"fetch_geo_63","index":6,"state":"cooked_fail","output_files":[]}`. The reason (`Failed to save output to file "Q:/no_such_drive/bldg_6.bgeo.sc"`) is only in `pdgtemp/<pid>/logs/fetch_geo_63.log`. | For `cooked_fail`, add `error` (the last `ERROR:`/`Error:` lines of the work item log, ≤ 400 chars), `log_path` and `exit_code`. Have `cook`/`job result` list the first 5 failed items with `error` when `ok` is false. |
| 2 | **P0** | `pdg cook` (any out-of-process scheduler) | With the hip dirty, the cook used the file on disk: `ok: true`, `cooked_success: 8`, with outputs written from the stale parm. Nothing warns. | When `hip.dirty` and the graph has out-of-process items, refuse with `hip_dirty` and the hint "out-of-process work items load the saved hip; hip_save first, or pass save: true". Add `save: true` to save before cooking. |
| 3 | **P1** | `job status` for `pdg` | `"progress":0.0,"current":0,"total":8,"message":"0/8 work items finished"` while upstream `fetch_geo` had 7/8 done. 24 items in the graph. | Count every work item upstream of `top_path` (24 here), and add `nodes: {"fetch_geo": "7/8", "fetch_ogl": "0/8", ...}`. Keep `current/total` for the whole graph. |
| 4 | **P1** | `pdg {action: cancel}` | Returns the pre-cancel status (`"cooking":true`). The job then reports `"state":"done","progress":1.0,"current":8` with `"message":"7/8 work items finished"`. | Make `pdg cancel` cancel the owning job too (`state: cancelled`). Return the post-cancel state with `cancelled: true`. Never report `done` for a cook with `cooked_cancel` items. |
| 5 | **P1** | `problems {root}`, `node_info` on TOP nodes | `problems` returned `No problems under /obj/topnet1` with 2 `cooked_fail` items. `node_info fetch_geo` returned `cook_state: "cooked"`, `errors: []`. | Have `problems` report TOP nodes with failed work items (count plus the first `error` from #1). Have `node_info` on a TOP node add `pdg_state` (the `pdg status` counts). |
| 6 | **P1** | `events` | Six cooks, two cancels and six dirties produced no event. `ChildCreated` was missing for nodes created in the same batch as their parent (CONTROLS, all topnet children). Spare parm add was logged as `FlagChanged`. Saving logged 3 `ParmTupleChanged` on the topnet. | Add PDG events (`PdgCookStart`, `PdgCookDone {states}`, `PdgWorkItemFailed {node, id, error}`). Record children created in a batch. Name spare-parm edits `SpareParmsChanged`. Drop the `taskgraphfile`/`checkpointfile` save noise. |
| 7 | **P1** | `pdg workitems` | No attributes. I could not see a wedge's `seed`/`hmax` and had to read the bgeo back with a File SOP. There is also no state filter, so finding failures means paging every item. | Add `attribs: ["seed","hmax"]` (or `include: ["attributes"]`, values clipped), `state: "failed"` (filter), and `cook_time_s` per item. |
| 8 | **P2** | `pdg workitems` | Every `output_files` entry repeats a 128-character absolute prefix: 4.1 of the 7.8 KB across 8 calls. `name` repeats the node name and `id`. | Return `output_root` once plus relative paths (or `$HIP`-relative paths), and drop `name`. |
| 9 | **P2** | `pdg {cook, block: true, timeout_s: 120}` | Returned `{"job_id":...,"state":"running"}` after 10.06 s. Nothing says that `timeout_s` was capped. | Add `notes: ["block capped at job_threshold_s (10 s); poll job"]`, or honour `timeout_s` up to `default_timeout_s`. |
| 10 | **P2** | `node_type_info {parms: "pdg_cachemode", detail: "full"}` | `{"name":"pdg_cachemode","type":"menu","default":0}`: no `menu` for a script menu. I had to guess the label. | Evaluate script menus (on a temporary instance if needed) or return `"menu": "dynamic"` with a hint to read it via `parm_get include: ["menu"]` on a live node. Also rank exact-prefix and most-used types (`ropfetch`) higher for `rop` in the Top category. |

**Honourable mentions.** `parm_set` echoes `raw` equal to `expression` and `raw` string tuples for plain numbers. Its warning `Local variable 'wedgeindex' not found.` could carry a note that `@attr` resolves only in a PDG cook. `pdg dirty` returns an empty status, where it could return `dirtied: [nodes]` and state that downstream is dirtied. `doctor` fails on the missing package JSON even though headless launch doesn't need it. The outline view lacks wiring (already planned).

---

## 6. How useful was `job` progress during the cook?

Moderately useful. As a liveness signal it was good: `state`, `elapsed_s` and a short message at about 210 B per poll, so polling every 4 s is cheap. As a progress bar it was misleading. It counts only the target node's items, so a 3-node, 24-item graph reads 0 % for two thirds of the cook and then jumps. I relied on `pdg status` for the target node and its upstream nodes, which costs about 140 B per node per poll and gives real per-state counts. After a `pdg cancel`, `job` reported `done`/1.0. A job with failed items reported `done` too, and only `result.ok: false` showed the failures. Fixes 3 and 4 would make `job` alone enough to watch a cook. With fix 1 added, a failed cook's `job result` would say why, and the agent would not need to look at disk.
