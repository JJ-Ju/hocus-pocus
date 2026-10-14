# 23 — Vellum cloth + USD round trip on 1.3.0

**Seat:** an AI agent working as an FX/pipeline TD, running workload 23 of `plan-1.4.md` through the MCP tools only. I read `docs/tools.md`, the README, the quickstart, review 20 and the `hocuspocus://guide` resource (6,412 B). I did not read the server source for the workload. I only looked at `cli.py` during setup, to confirm that `hocuspocus launch --headless` sets `PYTHONPATH` itself, because `install-houdini` would also write into the default pref dirs, which I had to avoid.
**Build:** `release/1.4` at `32450ef`, installed editable into a fresh scratch venv. `hocuspocus version`, `bridge_version` and `host_version` all say **1.3.0** (review 20's N6 is fixed).
**Host:** Houdini 22.0.466 hython, headless, pid **62268**, port 51983. I started it with `hocuspocus launch --headless --work-dir <scratch>/c23/vel`, with `HOCUSPOCUS_STATE_DIR=<scratch>/c23/state`, `HOUDINI_USER_PREF_DIR=<scratch>/c23/prefs/houdini__HVER__`, `profile = "full"` in `<scratch>/c23/prefs/houdini22.0/hocuspocus.toml` and `HOCUSPOCUS_PROFILE=full`. `launch` returned in 1.7 s. At the end, `houdini_connect {quit: true}` returned `{"quit":true,"pid":62268,"exited":true}`, and `tasklist` no longer listed pid 62268. Other agents' Houdinis were running on the machine, but my isolated state dir never saw them. I killed nothing.
**Client:** review 20's one-shot `mcp.Client` (`hp23.py`). Each call started a fresh `hocuspocus-mcp` and logged the tool, args bytes, text bytes, pretty bytes, isError, image count and seconds spent inside the call.
**Date:** 2026-10-13, 21:45:24 (launch) to 21:54:06 (quit): **8 min 42 s wall clock, 30.5 s of it inside tool calls.**
**Result:** a 24×24 cloth pinned at two corners, dropping over a sphere with Vellum, 48 frames, cached by `render` on a File Cache. I exported it with a LOP `sopimport` → `usd_rop`, re-imported it with `sublayer`, checked the time samples at 1, 24 and 48, and rendered frame 24 with Karma CPU at 480×270. **0 `houdini_python` calls.** I saved the scene as `<scratch>/c23/vel/cloth.hip` (1,183,059 B, `dirty: false`) and then deleted every cache, USD file and render. Evidence: `docs/redesign/evidence/city-destruction/100_vellum_usd_karma.png` (480×270, 18.6 KB). It is the Karma thumbnail, flattened onto grey. I chose it over the OpenGL `viewport_capture`, which has the same framing but flat shading.

**Headline: the USD round trip silently loses the animation.** `render` on a `usd_rop` (and on a `usdexport` SOP) over `frames [1,48]` reports 48 outputs and `done`. The layer it writes has **one time sample: frame 48**. Pressing the ROP's Save to Disk button through `parm_set press` writes the correct layer, with 48 samples (1.66 MB against 63 KB). Nothing in the result, `problems` or `events` says that anything is wrong (P0-1 below).

---

## 1. What I built

```
/obj/cloth (geo)
  cloth_grid      grid                size 4x4, rows/cols 24, t (0,3,0)        576 points
  collider        sphere              polymesh, rad 1, t (0,1.2,0), freq 8
  cloth_con       vellumconstraints   constrainttype cloth
  pin_con         vellumconstraints   constrainttype pin, grouptype points, group "0 23"
                                      inputs: cloth_con out 0 -> 0, cloth_con out 1 -> 1
  vsolver         vellumsolver        substeps 2, useground on
                                      inputs: pin_con 0, pin_con 1, collider -> 2 ("Collision Geometry")
  cache           filecache::2.0      filemethod explicit, $HIP/cache/cloth.$F4.bgeo.sc, f 1-48   (display/render)
  usd_out         usdexport           $HIP/usd/cloth_sop.usd, trange normal, f 1-48   (comparison only)
/stage
  cloth_import    sopimport           soppath /obj/cloth/cache, pathprefix /cloth
  collider_import sopimport           soppath /obj/cloth/collider, pathprefix /collider
  export_usd      usd_rop             lopoutput $HIP/usd/cloth.usd, trange normal, f 1-48
  reimport        sublayer            filepath1 $HIP/usd/cloth.usd
  cam             camera              t (9,5,10), look-at (0,1.6,-0.4), 30 mm
  key / fill      distantlight::2.0 (intensity 2.5) / domelight::3.0 (intensity 0.35)
  rset            karmarendersettings camera /cameras/cam, resolutionx 480 (auto height 270),
                                      4 primary / 16 path-traced samples, $HIP/render/cloth.$F4.png
  karma_rop       usdrender_rop
  sop_check       sublayer            (reads cloth_sop.usd, then the bad-path probe)
```

On the task's "collider via the second input": discovery showed that `vellumsolver` has three labelled inputs (`Vellum Geometry`, `Constraint Geometry`, `Collision Geometry`), so the collider goes into index 2. The labels from `node_type_info` were enough to wire Vellum right the first time. The pins held: `geo_read` at frame 24 shows points 0 and 23 at exactly (−2, 3, −2) and (2, 3, −2), with `v` (0,0,0).

---

## 2. Measurements

**Totals**

| | Review 20 (pyro, 1.3) | **Review 23 (Vellum + USD, 1.3.0)** |
|---|---:|---:|
| Calls | 75 | **91** (+1 `hocuspocus://guide` read, 6,412 B, not counted) |
| Text bytes | 77,956 | **95,454** |
| Pretty bytes | 100,082 | 127,630 |
| Args bytes | 5,637 | 10,115 |
| Avg text bytes per call | 1,039 | **1,049** |
| Errors | 5 (3 probes, 2 expected cancels) | **5** (1 probe, 3 friction, 1 my typo) |
| Seconds inside tools | 24.4 | **30.5** (9.8 of them in one `node_create`) |
| Wall clock, launch to quit | 7 min 06 s | **8 min 42 s** |
| Images returned | 4 | 3 (2 Karma thumbnails, 1 `viewport_capture`) |
| `houdini_python` | 0 | **0** |

**Time to first X** (from launch at 21:45:24)

| Milestone | Time | Call |
|---|---:|---|
| Network built and cooking | 1 min 57 s | #13 `node_create` (9.8 s, the solver cooks frame 1) |
| **First cache on disk** (48 files, 2.2 MB) | **2 min 19 s** | #15 `render /obj/cloth/cache` job, done in 7.2 s |
| First USD file on disk | 4 min 37 s | #40 `render /stage/export_usd`: **1 frame** (no `frames`, see P1-2) |
| First USD file claimed to cover 1–48 | 4 min 56 s | #44 `render … frames [1,48]`: **1 time sample** (P0-1) |
| **First correct 48-sample USD** | **5 min 58 s** | #57 `parm_set press /stage/export_usd/execute` |
| Round trip verified at 1/24/48 | 6 min 08 s | #59–61 `usd_stage {time}` after `reload` |
| **First image** | **6 min 42 s** | #67 `render /stage/karma_rop frames [24,24]`, 4.3 s |

**Per tool** (sorted by text bytes)

| Tool | Calls | Errors | Args B | Text B | Avg B | Max B | Secs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `node_type_info` | 18 | 0 | 1,146 | 24,615 | 1,367 | 2,837 | 0.5 |
| `node_type_search` | 6 | 0 | 247 | 21,744 | 3,624 | 12,503 | 0.5 |
| `geo_info` | 4 | 0 | 142 | 9,382 | 2,345 | 2,948 | 0.1 |
| `events` | 1 | 0 | 2 | 6,483 | 6,483 | 6,483 | 0.0 |
| `usd_stage` | 14 | 1 | 1,322 | 6,125 | 437 | 820 | 0.2 |
| `job` | 10 | 1 | 476 | 4,893 | 489 | 1,557 | 0.2 |
| `houdini_status` | 3 | 0 | 6 | 3,858 | 1,286 | 1,288 | 3.7 |
| `node_create` | 7 | 2 | 5,037 | 3,472 | 496 | 870 | 10.3 |
| `render` | 7 | 0 | 331 | 3,217 | 459 | 1,323 | 7.3 |
| `parm_set` | 7 | 0 | 548 | 2,450 | 350 | 672 | 0.6 |
| `network_describe` | 2 | 0 | 70 | 2,064 | 1,032 | 1,042 | 0.0 |
| `geo_read` | 1 | 0 | 82 | 1,971 | 1,971 | 1,971 | 0.2 |
| `cook` | 2 | 0 | 116 | 1,685 | 842 | 876 | 1.7 |
| `problems` | 3 | 0 | 49 | 1,312 | 437 | 905 | 0.2 |
| `parm_get` | 1 | 0 | 191 | 1,215 | 1,215 | 1,215 | 0.0 |
| `viewport_capture` | 2 | 1 | 173 | 637 | 318 | 433 | 4.3 |
| `hip_save` | 1 | 0 | 148 | 233 | 233 | 233 | 0.1 |
| `time` | 1 | 0 | 16 | 59 | 59 | 59 | 0.0 |
| `houdini_connect` | 1 | 0 | 13 | 39 | 39 | 39 | 0.6 |

**Where the bytes went.** **Discovery took 46 % of the run**: 24 calls and 46.4 KB across `node_type_search` and `node_type_info`. One call, `node_type_search {query: "vellum", category: "Sop", limit: 40}`, returned 12.5 KB for 37 rows (P2-6). Vellum's many parms were well contained: `detail: "folders"` gave the solver's 20 folders in 1.5 KB, and four folder or glob calls found every parm I set. Each of those calls, though, repeats the same 600-byte header (P2-7). `job` shrank to 489 B per call, against 1,222 B in review 20, because render results now carry `outputs_summary` and a 4-path sample instead of every path (review 20's N5 is fixed: the 48-frame cache result is 1,557 B instead of 8,372 B).

**Jobs.** Seven render jobs: the cache (48 frames, 7.2 s; a `houdini_status` during it blocked 3.6 s on the busy main thread), three USD exports (P0-1, P1-2), two inline Karma frames (4.3 s and 2.4 s) and a second cache after `resimulate`, polled at `"33/48 frames done, rendering frame 34"` and done in 2.8 s. Memory went from 418.5 MB at launch to 885.7 MB before the save.

---

## 3. The USD round trip, step by step

1. **Discovery.** `node_type_search "usd export"` ranked `Sop/usdexport` first and `Driver/usd` second, and `"usd_rop"` found `Lop/usd_rop`. Both have **empty descriptions**, and `include_help` on `usd_rop` returns `"See the USD render node."`, so discovery does not say how the two export paths differ.
2. **Export, first try.** `render {rop_path: "/stage/export_usd", wait_s: 0}` returned `"frames":[1,1,1]` and wrote a 695 B `cloth.usd` plus a 21 KB `collider_import.usd`, even though I had created the ROP with `trange: "normal", f: [1,48,1]`. The tool documents its default as the current frame, but a FX TD who has just set the ROP's frame range expects that range to be used (P1-2).
3. **Export, second try.** `render {…, frames: [1,48], wait_s: 0}` → `job result`: `"frames":[1,48,1],"outputs_summary":{"count":48,"first":".../usd/cloth.usd","last":".../usd/cloth.usd","pattern":".../usd/cloth.usd","missing_count":0}`, and `outputs_sample` lists `cloth.usd` four times. `collider_import.usd` was 63,118 B.
4. **Re-import.** `sublayer` → `usd_stage {include: ["layers"]}` showed `cloth.usd` and `collider_import.usd` on the stack, so the default `sopimport` `enable_savepath` had split the data into a second file (P1-4). Then `usd_stage {prim: "/cloth/mesh_0", include: ["attributes"], attribs: "points|extent", time: 1|24|48}` returned **the same extent `[[-2,0.525,-2.18],[2,3,1.07]]` at all three times, with `"time_samples":1`**. That is frame 48's bbox (it matches `geo_info` of the cache at frame 48).
5. **Diagnosis, through the tools only.** The live `/stage/collider_import` stage was time-varying (extent at 1: flat at y=3; at 24: min y 0.68). `parm_set {path: ".../export_usd/execute", press: true}` (0.36 s) rewrote `collider_import.usd` at **1,662,921 B**. After `parm_set press /stage/reimport/reload`, the same three `usd_stage` calls returned **`"time_samples":48`**, with flat cloth at 1, frame 24's exact extent `[[-2,0.6817,-2.1911],[2,3.0085,1.1539]]` at 24, and frame 48's extent at 48. The cached cloth survived the round trip, but only through the Save to Disk button.
6. **`usdexport` SOP, for comparison.** `render {rop_path: "/obj/cloth/usd_out", frames: [1,48]}` went "through its ROP `/obj/cloth/usd_out/lopnet_EXPORT/USD_OUT`" and wrote a 59 KB `cloth_sop.usd`. Read back through a second `sublayer`, its extent at time 24 also had `"time_samples":1` and frame 48's values. The SOP-side path has the same defect.

My reading of the cause, without having read the code: `render` drives these ROPs one frame per `rop.render()` call, to report per-frame progress. That works for per-frame outputs (File Cache, images), but a USD ROP writes a single file that holds every frame, so each call overwrites the file, and the last frame wins. The result's 48-fold count of one path is the visible symptom.

---

## 4. Friction log (chronological)

| # | Call | What happened | Cost |
|---|---|---|---|
| 1 | #2 `node_type_search vellum` | 12.5 KB, every row with the same `typical_parents`, `child_category` and `is_current_version` | 1 call, ~6 KB of noise |
| 2 | #7 `node_type_info parms "*pin*"` | The glob matched 8 `*dampingratio*` parms as well as the 4 pin parms (d-a-m-**pin**-g) | 2.8 KB |
| 3 | #12 `node_create … filecache trange: "range"` | `'range' is not a menu item … Use a token or label: off (Single Frame), normal (Frame Range)`, candidates, rolled back | 1 retry, a good error |
| 4 | #13 `node_create` | 9.8 s, with no note that `vellumsolver` cooked its first frame (OpenCL start-up) | none, but surprising |
| 5 | #16 `houdini_status` during the cache job | blocked 3.6 s (the main thread was simulating) | none |
| 6 | #40 `render usd_rop` without `frames` | wrote frame 1 only (P1-2) | 1 retry |
| 7 | #41 `job {job_id: "LAST"}` | my own placeholder; `job_not_found`, with a helpful hint | 1 call |
| 8 | #44–#61 | single-sample USD, diagnosed through `usd_stage` and a `press` (P0-1) | 10 calls, 1 min 30 s |
| 9 | #47 `node_create rset resolution [480,270]` | `locked`: `resolutiony is locked and computed by the expression 'pythonexprf(…computeResolutionParameter…)' (now 720)`, hint `Set resolutionx only` | 1 retry, a good error |
| 10 | #69 `viewport_capture lop_path: /stage/karma_rop` | `invalid_argument: /stage/karma_rop (usdrender_rop) has no output stage; read its input /stage/rset.` | 1 retry |
| 11 | #78 `events` | 25 parm events, 16 of them Houdini-internal LOP writes labelled `origin: agent` | 6.5 KB |

---

## 5. What worked

- **Vellum discovery through folders.** `node_type_info {detail: "folders"}` turned the solver's 133 parms into 20 folders in 1.5 KB, and `folder` or `parms` globs found every parm I needed (`constrainttype`, `grouptype`, `group`, `pintype`, `substeps`, `useground`) in four calls. The input labels made the three-input wiring obvious, and the build cooked clean on the first real attempt.
- **Menu and lock errors that fix themselves.** The `trange` error listed the tokens with their labels. The `resolution` error named the locked component, the expression behind it and the exact workaround. Both rolled the batch back.
- **The File Cache path from review 20 holds up for Vellum.** `render` on the File Cache wrote 48 frames in 7.2 s, turned on Load from Disk, and reported progress as `"33/48 frames done, rendering frame 34"` (review 20's N7 is fixed). The result is 1.5 KB, not 8 KB.
- **Inspection across frames.** `geo_info {frame}` at 1/24/48 and `geo_read {frame: 24, stats: true}` proved the pins and the drape without moving the playbar.
- **`cook {profile}` on a Vellum solver now tells the truth.** On a warm cache it returned `"resimulated":false` and the note *"…did not re-simulate: …cache already held frame 24, so its cook_time_ms is a cache read. Reset the simulation (its resimulate button) to time a full run."* After `parm_set press resimulate`, it returned `"resimulated":true`, 1,623 ms. Review 20's N3 is fixed.
- **`usd_stage` with `time` and `time_samples`.** The per-attribute `time_samples` count is what exposed P0-1. Without it, the bug would have shown up only as a frozen Karma sequence.
- **Missing files.** A bad `filepath1` on `sublayer` came back on the `parm_set` row as `errors: ["Unable to find layer file: …"]`, `cook_state: "error"`. `usd_stage` then failed with `cook_failed`, and `problems` gave an `error` row and a `missing_file` row with `parm`, `file` and the raw `$HIP/...` value.
- **Karma through `render`.** A 480×270 frame at 4 spp in 2.4–4.3 s, with an opaque thumbnail flattened onto grey (the PNG on disk keeps its alpha). `viewport_capture {lop_path, camera: "/cameras/cam"}` took 4.3 s through the OpenGL ROP.

---

## 6. Top 10 papercuts

**P0-1. `render` on a USD ROP or `usdexport` over a range writes one time sample and reports 48.**
- **Tool / argument:** `render {rop_path: "/stage/export_usd", frames: [1,48], wait_s: 0}` (`Lop/usd_rop`). Same for `render {rop_path: "/obj/cloth/usd_out", frames: [1,48]}` (`Sop/usdexport`).
- **Exact result:** `"frames":[1,48,1],"outputs_summary":{"count":48,"first":"…/usd/cloth.usd","last":"…/usd/cloth.usd","pattern":"…/usd/cloth.usd","missing_count":0}`, state `done`, no notes. Read back, `usd_stage` gives `"time_samples":1`, with frame 48's points at times 1, 24 and 48. The data layer is 63 KB, against 1.66 MB from `parm_set press …/execute`.
- **Proposed change:** when a ROP's output path does not vary with `$F` (`usd_rop`, `Driver/usd`, `usdexport`, Alembic), render the whole range in one `rop.render(frame_range=(s,e,i))` call, and take progress from a per-frame callback rather than from separate calls. Afterwards, open the written root layer with `Sdf.Layer.OpenAsAnonymous` (or a `Usd.Stage`) and report `time_codes: [start, end]` plus the number of samples on one animated attribute. If that comes back as a single sample while more than one frame was asked for, fail with a `render_incomplete` error.

**P1-2. `render` on a ROP ignores the ROP's own frame range.**
- **Tool / argument:** `render {rop_path: "/stage/export_usd", wait_s: 0}` on a ROP with `trange: "normal"`, `f: [1,48,1]`.
- **Exact result:** `"frames":[1,1,1]`, one output, no note. Writer SOPs (File Cache, `usdexport`) do use their own range, which makes the two cases inconsistent.
- **Proposed change:** default `frames` to the ROP's `f1–f3` when its `trange` is not `off`, as for writer SOPs. When `trange` is `off`, add the note `"Rendered the current frame (1) only: /stage/export_usd's Valid Frame Range is 'Render Current Frame'. Pass frames to render a range."`

**P1-3. Render outputs count one file N times and miss the layers that hold the data.**
- **Tool / argument:** the `job result` of the 48-frame `usd_rop` render.
- **Exact result:** `count: 48`, and `outputs_sample` lists the same `cloth.usd` 4 times. `collider_import.usd`, the 1.66 MB file with all the geometry, is not listed, and `cloth.usd` is a 697 B stub that sublayers it.
- **Proposed change:** de-duplicate outputs. For USD ROPs, list every layer file written in that render, with its size: the root layer, sopimport/configure-layer save paths and `Extra Files`. Something like `layers: [{path, bytes, time_codes}]`.

**P1-4. Nothing says that `sopimport` split the export into a second file.**
- **Tool / argument:** `usd_stage {lop_path: "/stage/collider_import", include: ["layers"]}` before the export.
- **Exact result:** `"layers":{"stack":["anon:000000003FF80080:LOP:rootlayer","anon:…:LOP",…]}`: anonymous ids only, with no save paths. The default `enable_savepath: on`, `savepath: $HIP/usd/$OS.usd` is what produced `collider_import.usd`, and an agent has no way to see that coming.
- **Proposed change:** make each `layers` row an object, `{identifier, save_path?, owner_node?, time_codes?}`, where `save_path` comes from the `HoudiniLayerInfo` save path. Add a `render` note on `usd_rop`: `"2 layer files written: cloth.usd (root, sublayers ./collider_import.usd) …"`.

**P1-5. `network_describe` outline drops the output index of an input.**
- **Tool / argument:** `network_describe {root: "/obj", format: "outline"}`.
- **Exact result:** `"inputs":["/obj/cloth/cloth_con","/obj/cloth/cloth_con"]` for `pin_con`, and `["/obj/cloth/pin_con","/obj/cloth/pin_con","/obj/cloth/collider"]` for the solver. Vellum's most common wiring mistake (geometry into the constraint input) cannot be seen.
- **Proposed change:** write `"/obj/cloth/cloth_con:1"` when the output index is not 0, in the outline and in `houdini://outline`.

**P2-6. `node_type_search` rows repeat constant fields.**
- **Tool / argument:** `node_type_search {query: "vellum", category: "Sop", limit: 40}`.
- **Exact result:** 12,503 B for 37 rows. Every row carries `"is_current_version":true`, `"child_category":"Sop"` and `"typical_parents":["a geo object such as /obj/geo1"]`, about 120 B per row, 4.4 KB in all.
- **Proposed change:** leave out `is_current_version` when `current_only` is true. Hoist `typical_parents` and `child_category` into one `common: {...}` block when every row shares them, or send them only for network types.

**P2-7. `node_type_info` repeats its header on every narrowed call, and its globs match inside words.**
- **Tool / argument:** 18 calls to `node_type_info` with `folder` or `parms`, and `parms: "*pin*|grouptype"`.
- **Exact result:** every call repeats `description`, `outputs` (3 rows for Vellum) and `min/max_inputs`, about 600 B each time. `*pin*` also matched `stretchdampingratio`, `benddampingscale` and 6 other damping parms.
- **Proposed change:** `header: false` (or leave the header out automatically when `folder` or `parms` is given) so that only `parms` is returned. For globs, rank matches on whole name segments and labels first, or add `"matched_by": "substring"` on rows that matched only inside a word.

**P2-8. `geo_info` on a Vellum result is mostly solver internals.**
- **Tool / argument:** `geo_info {path: "/obj/cloth/cache", frame: 24}`.
- **Exact result:** 2,948 B per frame. It lists 28 point attributes (`has_pprevious`, `hitnml`, `dPw`, `overlap_self`, `vprevious`, `plast`, `targetv`…) and the `varmap` detail strings. Checking three frames cost 8.7 KB.
- **Proposed change:** add `attributes: "names"` to give one compact name list per class, or collapse known Vellum and DOP internals into `{"vellum_internal": 21}` unless asked for. Also mark when the attribute set matches the previous `geo_info` call on the same node (`attributes_same_as_frame: 24`).

**P2-9. `events` labels Houdini's own LOP writes as the agent's.**
- **Tool / argument:** `events {}` after building the LOP chain.
- **Exact result:** 16 of the 25 `ParmTupleChanged` rows were written by Houdini's callbacks, not by me, and all are `"origin":"agent"`: `xn__houdiniguidescale_s3a` (×6), the camera's `*Converted` parms (×6: `focalLengthConverted`, `horizontalApertureConverted`, …), `labelparm17` and `rset resolution` (×3).
- **Proposed change:** within an agent call, record only the parms the call itself set, and tag the rest `origin: "houdini"` (or drop them). Also collapse a node's parm events from one call into one row with `parms: [...]`.

**P2-10. Stage tools refuse a render ROP instead of reading its input.**
- **Tool / argument:** `viewport_capture {lop_path: "/stage/karma_rop", camera: "/cameras/cam", frame: 24}`.
- **Exact message:** `"/stage/karma_rop (usdrender_rop) has no output stage; read its input /stage/rset."`, hint `"Pass lop_path /stage/rset."` A clear message, but the tool already knows the right node.
- **Proposed change:** for a `usdrender_rop` or `usd_rop`, use its input's stage and add a note (`"Captured /stage/rset, the input of /stage/karma_rop."`), in both `viewport_capture` and `usd_stage`. Keep the error only when the ROP has no input.

**Honourable mentions (P3):** `node_create` took 9.8 s with no note that the solver cooked frame 1; `include_help` on `usd_rop` returns only `"See the USD render node."`; a `problems` `missing_file` row repeats the absolute path three times.

---

## 7. Review 20 carry-over

Fixed: N3 (`resimulated` is now `false` with a note on a warm cache, `true` and 1,623 ms after `resimulate`), N5 (the 48-frame render result is 1,557 B, was 8,372 B), N6 (1.3.0 everywhere) and N7 (`"33/48 frames done, rendering frame 34"`). N1 and N2 were not exercised.

---

## 8. Verdict

The Vellum half of the workload is in good shape on 1.3.0. Discovery coped with Vellum's 133- and 161-parm nodes through folders and globs, the wiring was right the first time, the File Cache `render` path from review 20 cached 48 frames in 7 s with honest progress, and every inspection and profiling tool told the truth. The run used no `houdini_python`, had 3 friction errors that all fixed themselves from the error text, and reached the first cache in 2 min 19 s.

The USD half has one serious defect. **`render` cannot currently write an animated USD file.** On both `usd_rop` and `usdexport` it reports success over 48 frames and writes one. An agent that does not read time samples back would ship a frozen layer, and Karma would render the same pose for every frame. Together with the ROP-range default (P1-2), the single-file output count (P1-3) and the hidden save-path layer (P1-4), this is the 1.4 fix list for USD IO. Fix P0-1 and P1-2 before tagging, and add a tier test that renders a 3-frame `usd_rop` and asserts 3 time samples. P1-5 is a one-line outline change that matters for every multi-output SOP. P2-6 to P2-10 are byte and noise savings that fit the 1.4 budget work.
