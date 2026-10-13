# 17 — FX sim + cache on 1.2.1: a pyro plume, cached, flipbooked and stressed

**Seat:** an AI agent working as an FX TD on workload 17 of `plan-1.3.md`. I used only the MCP tool surface, plus `docs/tools.md` (with its `notes`), the README, the quickstart and review 16 for the harness. I did not read the server source.
**Build:** `release/1.3` at `88e654c` (1.2.1 code plus the 1.3 plan), installed editable into a scratch venv. `hocuspocus version` → `hocuspocus 1.2.1 (hp/v1, mcp 2.3.0, Python 3.12.14)`. Review 16's N5 (stale version strings) is fixed: `houdini_status` reports `bridge_version` and `host_version` `1.2.1`.
**Host:** Houdini 22.0.466 hython, headless, pid **1908**, started with `hocuspocus launch --headless --work-dir <scratch>/c17/fx` into a fresh untitled scene. `HOCUSPOCUS_STATE_DIR=<scratch>/c17/state`, `HOUDINI_USER_PREF_DIR=<scratch>/c17/prefs/houdini__HVER__`, `profile = "full"` in `<scratch>/c17/prefs/houdini22.0/hocuspocus.toml` and in `HOCUSPOCUS_PROFILE`. `launch` returned in 1.7 s. At the end, `houdini_connect {quit: true}` returned `{"quit":true,"pid":1908,"exited":true}`, `houdini_status` then showed `connected: null, instances: []`, and `tasklist` found no pid 1908. I killed nothing.
**Client:** review 16's one-shot `mcp.Client` (`hp17.py`), which starts a fresh `hocuspocus-mcp` per call and logs tool, args bytes, text bytes, pretty bytes, isError, image count and in-call seconds. I added `PYTHONIOENCODING=utf-8` after call 9 crashed my client printing a `↓` from a menu label. The crash was in my client, not the server, but the call was logged, so call 10 repeats it.
**Date:** 2026-10-12, 22:22:05 (launch) to 22:31:04 (quit): **8 min 59 s wall clock, 58.8 s of it inside tool calls.**
**Result:** a smoke plume, 48 frames at 0.1 voxel size, cached to `$HIP/cache/pyro.$F4.bgeo.sc` (48 files, 61 MB), flipbooked at 480×270 by an OpenGL ROP, plus a `viewport_capture` of frame 36. **0 `houdini_python` calls.** Saved as `<scratch>/c17/fx/pyro.hip` (1,088,113 B, `dirty: false`). Evidence: `docs/redesign/evidence/city-destruction/60_pyro_frames.png`, a 1464×586 contact sheet (44.7 KB) of frames 1, 10, 19, 28, 38 and 48 from the flipbook.

---

## 1. What I built

```
/obj/pyro (geo)
  src_sphere   sphere                     polymesh, rad (0.8,0.5,0.8), t (0,0.5,0)
  pyrosource   pyrosource                 mode 2 (Volume Scatter), particlesep 0.05,
                                          attributes multiparm: density, temperature   (set by hand, see P1-4)
  rasterize    volumerasterizeattributes  attributes "density temperature", voxelsize 0.05
  pyrosolver   pyrosolver (v2)            divsize 0.1, clampsize on, maxsize (6,7,6), t (0,3.5,0),
                                          disturbance + turbulence on, buoyancylift 0.15, substep 2
  cache        filecache::2.0             filemethod explicit, file $HIP/cache/pyro.$F4.bgeo.sc,
                                          f 1-48, savebackground off            (display/render)
/obj/cam_fx    cam                        t (13,4.5,13), r (-3,45,0), 35 mm, 480x270
/obj/key       hlight::2.0                distant
/out/flipbook  opengl                     camera /obj/cam_fx, tres on, res 480x270, $HIP/flip/pyro.$F4.png
/out/geo_cache geometry                   soppath /obj/pyro/pyrosolver, $HIP/cache_rop/pyro.$F4.bgeo.sc  (stress tests)
```

Discovery took 2 `node_type_search` calls and 10 distinct `node_type_info` calls (16.1 KB together). `node_type_search {query: "pyro", category: "Sop"}` returned the whole Houdini 22 SOP pyro family in one 3.7 KB page. `node_type_info` with `detail: folders` on the solver, then `folder:` and `parms:` globs, found every parm I set without a guess. The sim volumes are 48×80×48 by frame 24 (density max 15.5, `vel.y` max 33.0). On the first pass the plume was a thin column clipped by the container. Two look iterations (disturbance and turbulence, lower buoyancy, a wider source, a bigger container, a new camera) produced the mushroom in the contact sheet. Each iteration was one `parm_set` batch, a re-save and a re-render, all done in 10–15 s.

---

## 2. Measurements

**Totals**

| | Value |
|---|---:|
| Calls | **93** (1 a repeat after my client crash) |
| Text bytes | **90,073** (pretty 122,503) |
| Args bytes | 7,012 |
| Errors | 6 (2 deliberate probes, 2 expected `cancelled` results, 2 friction: P1-4 and P1-5) |
| Seconds inside tools | 58.8 (cook 32.2, render 13.6, viewport_capture 4.9, parm_set 4.3) |
| Wall clock, launch to quit | 8 min 59 s |
| First cache on disk | 2 min 10 s after the first call (call 23, `parm_set press`) |
| First image returned | 3 min 29 s (call 39, `job result` of the flipbook, inline thumbnail) |
| Images returned | 4 (3 `render` thumbnails, 1 `viewport_capture`) |
| `houdini_python` | 0 |

**Per tool** (sorted by text bytes)

| Tool | Calls | Errors | Args B | Text B | Avg B | Max B | Secs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cook` | 6 | 0 | 406 | 15,519 | 2,586 | 4,867 | 32.2 |
| `node_type_info` | 12 | 0 | 865 | 15,200 | 1,266 | 3,371 | 0.7 |
| `geo_info` | 8 | 0 | 286 | 15,061 | 1,882 | 2,750 | 0.4 |
| `job` | 21 | 2 | 877 | 12,674 | 603 | 8,129 | 0.3 |
| `events` | 1 | 0 | 13 | 5,798 | 5,798 | 5,798 | 0.0 |
| `parm_set` | 12 | 1 | 1,473 | 4,999 | 416 | 1,062 | 4.3 |
| `node_type_search` | 2 | 0 | 93 | 4,871 | 2,435 | 3,689 | 0.4 |
| `node_create` | 3 | 0 | 1,648 | 4,810 | 1,603 | 4,314 | 1.0 |
| `render` | 7 | 2 | 524 | 3,213 | 459 | 936 | 13.6 |
| `houdini_status` | 3 | 0 | 6 | 2,592 | 864 | 1,210 | 0.0 |
| `geo_read` | 4 | 1 | 282 | 2,156 | 539 | 1,375 | 0.3 |
| `parm_get` | 2 | 0 | 134 | 790 | 395 | 544 | 0.0 |
| `problems` | 2 | 0 | 35 | 712 | 356 | 511 | 0.0 |
| `node_info` | 1 | 0 | 50 | 493 | 493 | 493 | 0.0 |
| `viewport_capture` | 1 | 0 | 58 | 405 | 405 | 405 | 4.9 |
| `time` | 5 | 0 | 35 | 300 | 60 | 60 | 0.1 |
| `hip_save` | 1 | 0 | 146 | 230 | 230 | 230 | 0.1 |
| `node_find` | 1 | 0 | 68 | 212 | 212 | 212 | 0.0 |
| `houdini_connect` | 1 | 0 | 13 | 38 | 38 | 38 | 0.6 |

**Jobs and polling**

| Job | Started by | Frames | Became a job after | Polls (status) | Other job calls | Outcome |
|---|---|---:|---|---:|---|---|
| `9c2f…` | `render /out/flipbook`, `wait_s: 0` | 48 | 0 s (forced) | 2 | 1 result (8,129 B) | done, 10.8 s |
| `a66f…` | `cook pyrosolver frame_range [1,120]` at 0.05 | 120 | **10.0 s blocked in `cook`** | 3 | 1 cancel (too late), 1 status | done, 15.7 s |
| `871c…` | `cook pyrosolver frame_range [1,240]` at 0.05 | 240 | **10.0 s blocked in `cook`** | 4 | 1 cancel, 1 result | **cancelled at 165/240** |
| `be76…` | `render /out/geo_cache`, `wait_s: 0` | 240 | 0 s (forced) | 4 | 1 cancel, 1 result | **cancelled, 126 files on disk** |
| (two flipbook re-renders) | `render`, default wait | 48 | finished inside the wait | 0 | 0 | done, 6.5 s each |

There were 21 `job` calls, 1 of them `list`. Status polls cost 164–219 B each, so polling is cheap in bytes. The one expensive `job` call is the flipbook `result`, which lists all 48 absolute paths (7.2 KB, honourable mention). Progress messages were good where the work was frame-shaped: `"frame 77/240"` for the cook and `"frame 20.0 (20/240)"` for the Geometry ROP. The OpenGL ROP went from `"0/48 frames"` at 5.1 s straight to `done` at 10.8 s.

**Where the bytes went.** Inspection was 34 % of all bytes: `geo_info` 15.1 KB, `cook` summaries 15.5 KB. **About 1,350 B of every pyro `geo_info` (half of it) is one detail attribute,** `volvis`, a dict holding two JSON ramp strings and `"<hou.Vector2 [0, 1]>"` reprs (P1-7). A 48-frame `cook {summary: bbox}` is 4.86 KB at ~100 B per frame. All 48 rows have identical point and prim counts, and the bbox changes on only 4 frames (3, 6, 12, 18) (P2-8).

---

## 3. Friction log (in order)

1. **Discovery was quick.** Two searches and the folder listing gave me the H22 SOP pyro chain. One clipped description ends in a broken UTF-8 byte (`"…and detona�"`).
2. **The first build cooked green but sourced nothing.** `pyrosource` with `initialize: "source"` stored the value, but the menu's callback, which fills the attribute multiparm, never ran. `rasterize` returned **0 prims, `bbox: null`, no warning**, and `problems` was empty. Only a `geo_info` at each step caught it. `press` on the menu was refused (P1-4), so I filled the multiparm by hand in one `parm_set` (menu tokens accepted directly).
3. **`cook {frame_range: [1,48], summary: "bbox"}` on the File Cache** returned `ok: true, frames_cooked: 48` in 1.2 s **and wrote nothing**. Cooking a File Cache passes its input through, and only the Save button writes. Nothing in the result says so (P0-1).
4. **`parm_set press` on `execute`** wrote all 48 files (61 MB) in 0.5 s, from the solver's in-memory cache. The result does not mention files, or the button's side effect: it turned `loadfromdisk` on. `events` showed that change.
5. **`geo_info {frame}` across frames 1/24/48** gave resolution 16×32×16 → 48×80×48, voxel size, per-volume min/max and bbox growth, but **only 3 of the 6 volumes** (P1-7). `geo_read` cannot take a frame (P1-5), so a per-frame read costs a `time` call that moves the playbar.
6. **Flipbook.** The OpenGL ROP rendered 48 frames in 10.8 s as a job (6.5 s inline later), with the thumbnail attached. `Driver/opengl` is `"deprecated":true` ("Replaced by the Flipbook ROP."), but `node_create` did not say so. `viewport_capture {camera, frame: 36}` worked first try (4.9 s, `opengl_rop`), volumes drawn as smoke. Review 16's N1 crash does not reproduce for `/obj`.
7. **Getting a job at all was hard.** The sim took 1.2–2.5 s at 0.1 voxels and 7.6 s at 0.05. Only 120 frames at 0.05 became a job, **after `cook` blocked for the full 10.0 s** (P2-8). That job finished before my cancel arrived, and `cancel` on a `done` job returned the plain status with no note.
8. **Cancel works.** The 240-frame cook went `"cancellation requested"` → `cancelled` at 165/240 within 0.2 s, and **the playbar was restored to 24**. The result lost the 164 cooked frames and lacks the documented `detail` (P1-6).
9. **A cancellable cache write needs a `/out` Geometry ROP**, because `render` refuses the File Cache (P1-3). As a job it reported every frame. Cancelled at frame 126, it left **126 complete files** (the last one 14.0 MB, like its neighbours) and restored the frame.
10. **Bad cache paths.** With `approved_roots` unset, `render … output:` outside `$HIP` created the directory and wrote. `Q:/fxcache/…` through `render` failed well: `Could not create directory 'Q:/fxcache'.` **The same path through the Save button reported success** (P0-2).
11. **`cook {profile: true}` on the solver**: 513 B, `pyrosolver 792.6 ms`, `pyrosource 27.3`, `rasterize 6.1`, `src_sphere 0.6`. The solver is one opaque row (P2-10).
12. **Memory.** `geo_info.memory_bytes` (95 KB at frame 1, 2.6 MB at frame 24) is the only memory number on the surface (P2-9).
13. **Save and quit were clean.**

---

## 4. What worked

- **Discovery and parm idioms.** `node_type_info` folders → `folder` → `parms` globs found 30+ solver, source, cache and ROP parms in 10 calls with 0 wrong names. Menu tokens, tuple lists and multiparm counts all went through `parm_set` and `node_create` without type errors.
- **`node_create` with 6 items** built the whole SOP chain with wiring and flags in one call (0.8 s). The `return: full` rows showed `$HIP` expanded next to `raw`.
- **`geo_info` on volumes**, apart from the 3-volume cap: `prim_types: {volume: 6}`, per-volume `resolution`, `voxel_size`, `min`/`max`, `memory_bytes`, and `vdb` intrinsics (`active_voxels`, `class: fog volume`) on the VDB rasterizer. That is the inspection an FX TD needs, in under 3 KB.
- **`cook {frame_range}` as a sim driver.** It advanced the sim correctly, the bbox summary showed the container growing in tile-sized steps (1.6 units at 0.1 voxels, 0.8 at 0.05), and it **restored the current frame every time** (24 before, 24 after, including after cancel).
- **Jobs.** Frame-accurate progress, cheap polls (~190 B), a fast cancel (~0.2 s), `job list` with five jobs in 998 B, and partial outputs left intact.
- **`render` errors.** The bad drive letter produced a one-line, actionable `cook_failed` that names the directory.
- **`viewport_capture` on `/obj` volumes**, headless, with a camera and a frame, first try.
- **`events`.** 40 events, none duplicated: 10 `ChildCreated` for 10 nodes, so review 16's N2 is fixed. It recorded the File Cache callbacks that `parm_set` did not report.
- **Lifecycle.** `hocuspocus launch --work-dir` → 93 one-shot bridges → `houdini_connect {quit: true}`, with no orphan processes.

---

## 5. Top 10 papercuts

### P0

**P0-1. `cook {frame_range}` on a File Cache reports success and writes nothing.**
- **Tool / argument:** `cook {paths: ["/obj/pyro/cache"], frame_range: [1,48], summary: "bbox"}` on `filecache::2.0`.
- **Exact result:** `{"ok":true,"results":[{"path":"/obj/pyro/cache","ok":true,"cook_time_ms":1184.6,…}],"frame_range":[1,48,1],"frames_cooked":48,…}`. `$HIP/cache` does not exist afterwards.
- **Proposed change:** when a cooked node is a cache or writer SOP (`filecache*`, `rop_geometry`, `file` in write mode, `rop_*` SOPs), add `notes: ["Cooking /obj/pyro/cache does not save it; cook passes geometry through. Save with parm_set press on execute, or render the node as a job."]`. Better, let `render` accept these nodes (P1-3). Also add a sentence to the `cook` notes: "frame_range cooks; it never writes caches".

**P0-2. The File Cache's Save button fails silently.**
- **Tool / argument:** `parm_set {items: [{path: "/obj/pyro/cache/file", value: "Q:/fxcache/pyro.$F4.bgeo.sc"}, {path: "/obj/pyro/cache/execute", press: true}]}`.
- **Exact result:** `isError: false`, and on `execute`: `"errors":[],"warnings":["Unable to read file \"Q:/fxcache/pyro.0024.bgeo.sc\".","GeometryIO[hjson]: Unable to open file 'Q:/fxcache/pyro.0024.bgeo.sc'…"]`. The successful press returns `{"value":null,"raw":"0","is_default":true}` and says nothing about the 48 files written.
- **Proposed change:** for known save buttons (`filecache::2.0/execute`, `rop_geometry/execute`, `*/execute` on ROP-like SOPs), resolve the output pattern over the node's frame range before the press and check the files afterwards. Return `outputs_summary {count, pattern, missing_count}`, and fail with `cook_failed` (`"Save to Disk wrote 0 of 48 frames; Q:/fxcache is not writable"`) when the files are missing. Report the side effects of the button (`loadfromdisk: false → true`), and drop `value: null` and `raw: "0"` for buttons.

### P1

**P1-3. There is no job, progress or cancel path for caching through a File Cache.**
- **Tool / argument:** `render {rop_path: "/obj/pyro/cache", wait_s: 0}`.
- **Exact message:** `/obj/pyro/cache (filecache::2.0) is not a render node.`, hint `Pass a ROP such as /out/karma1 or /out/opengl1.`
- `press` is synchronous: a 30-minute sim would hold the host in one blocking `parm_set`, with no progress and no cancel. A `/out` Geometry ROP gave exactly the job behaviour an FX TD wants (per-frame progress, cancel, partial files).
- **Proposed change:** let `render` take `filecache::2.0`, `rop_geometry` SOPs and other output SOPs, and run their internal ROP (the File Cache has one at `topnet1/ropgeometry1/ropnet1/geometry1`) or `hou.SopNode` save as a job with the node's frame range. Until then, change the hint to `For a SOP cache, render a Geometry ROP (/out geometry, soppath <node>) or press execute (blocking).`

**P1-4. Setting a callback menu stores the value and skips the callback; `press` refuses menus without a hint.**
- **Tool / argument:** `node_create … pyrosource parms {"initialize": "source"}`, then `parm_set {path: ".../pyrosource/initialize", press: true}`.
- **Exact message:** `items[0] (/obj/pyro/pyrosource/initialize): it is a menu parm, not a button.` (no hint). Downstream, `rasterize` cooked to 0 prims and `bbox: null` with no warning.
- **Proposed change:** make `press: true` valid on any parm with a callback script (menus included: run `pressButton()` or the callback after setting the value), and allow `{value, press: true}` together. When `parm_set` or `node_create` sets a parm with a callback script, add a note: `initialize has a callback that a plain set does not run; pass press: true to run it.` Mark callback parms in `node_type_info detail: full` (`"callback": true`).

**P1-5. `geo_read` has no `frame`.**
- **Tool / argument:** `geo_read {path: "/obj/pyro/cache", class: "prim", attribs: ["name","maximum"], frame: 24}`.
- **Exact message:** `1 argument problem(s) for geo_read: frame: unknown property (allowed: path, class, attribs, start, count, group, stats, cursor)`.
- Inspecting a sim means reading across frames. `geo_info` takes `frame`, `geo_read` does not, so the agent has to move the user's playbar with `time`.
- **Proposed change:** add `frame` to `geo_read`, evaluated like `geo_info`'s without moving the playbar, and echo `frame` in the result.

**P1-6. A cancelled job's result loses everything done before the cancel.**
- **Tool / argument:** `job {action: "result", job_id: "871c6dd760de"}` after a cancel at 165/240, and the same for the Geometry ROP job cancelled with 126 files on disk.
- **Exact message:** `{"code":"cancelled","message":"Job 871c6dd760de was cancelled.","retryable":false}` (82 B). The `job` notes say "A cancelled job's result is the cancelled error, whose detail holds the last status", but there is no `detail`.
- **Proposed change:** put `detail: {last_status, partial}` on the cancelled error. For `cook`, `partial` holds `frames_cooked` and the `frames` summary so far. For `render`, it holds `outputs_summary` of the files that exist (`count: 126, last: pyro.0126.bgeo.sc`). Add a test that the documented `detail` is present.

**P1-7. `geo_info` on a pyro sim hides half the volumes and spends half its bytes on `volvis`.**
- **Tool / argument:** `geo_info {path: "/obj/pyro/cache", frame: 24}` (2,701 B).
- **Exact result:** `"prim_types":{"volume":6}` but `"intrinsics":{"volume":[…3 rows: density, temperature, flame]}`, with no `truncated` or count. The detail attribute `volvis` value carries `"cdrange":"<hou.Vector2 [0, 1]>"` and two multi-line JSON ramp strings (`emitcdramp`, `emitramp`), about 1,350 B.
- **Proposed change:** list every volume as a compact row (`[name, res, voxel_size, min, max]`), or cap with `volumes_total` and `truncated: true`. Serialize `hou.Vector*` as lists, and elide dict-valued detail attributes over ~200 B as `{elided, keys}` the way long strings are elided.

### P2

**P2-8. `cook {frame_range}` blocks for the whole job threshold, and its summary repeats itself.**
- **Tool / argument:** `cook {frame_range: [1,240]}` (10.03 s before the `job_id`), and `summary: "bbox"` (4,867 B for 48 frames, so about 24 KB for 240).
- **Proposed change:** add `wait_s` to `cook` (as on `render`; `0` returns the job at once). Run-length-encode the summary: emit a row only when counts or bbox change, with `frames: "1-2"` style ranges. This frame range collapses from 48 rows to 5.

**P2-9. No memory reporting.**
- **Tool:** `houdini_status`. There is no `memory` field anywhere. The solver keeps up to `cachemaxsize` 5000 MB of frames in RAM.
- **Proposed change:** `connected.memory: {rss_mb, peak_mb}` in `houdini_status`, and `memory_delta_mb` on `cook` and `render` job results, so that an agent can see a sim cache filling up before the host is killed.

**P2-10. `cook {profile: true}` on a solver is one opaque row.**
- **Exact result:** `"chain":[{"path":"/obj/pyro/pyrosolver","type":"pyrosolver","cook_time_ms":792.6},…]` with no word on what the 792 ms covers.
- **Proposed change:** for a sim node, add a note on whether the force-cook re-simulated (`re-simulated frames 1-24`), and attribute the DOP network inside it (microsolver rows from the performance monitor) the way loops are attributed today.

### Honourable mentions

- A render `job result` repeats all 48 absolute paths (~7.2 KB of an 8,129 B result) next to an `outputs_summary` with `pattern` and `missing_count: 0`. Return `outputs` only when they differ from the pattern, or on request.
- `node_type_search` clips descriptions mid UTF-8 sequence: `"…and detona�"`. Clip on a character boundary and add `…`.
- `job cancel` on a finished job returns its `done` status silently. Add `cancelled: false, note: "job had already finished"`.
- `node_create` of `Driver/opengl` gives no deprecation note, although `node_type_info` knows `"Replaced by the Flipbook ROP."`. Surface `deprecated` in `node_create` results.
- The OpenGL ROP job reported `0/48 frames` until it was `done`. The Geometry ROP reported every frame (`frame 20.0 (20/240)`; the frame could print as `20`).

---

## 6. Verdict

The sim and inspection loop is good. One batch builds the network, `geo_info {frame}` reads volume resolution, ranges and bbox across frames, `cook {frame_range}` advances the sim and puts the playbar back, the OpenGL flipbook comes back with a thumbnail, and jobs report frame progress and cancel in a fraction of a second, leaving partial outputs intact. I needed no `houdini_python`, and the whole workload, including two look iterations and four stress tests, took 93 calls, 90 KB and 9 minutes.

**The cache, the step the workload is named after, is where 1.2.1 lets an FX TD down.** The plan's suggested path, a File Cache driven by `cook {frame_range}`, reports 48 green frames and writes nothing (P0-1). The path that does write, pressing Save to Disk, gives no outputs, no progress and no cancel, and **reports success when the save fails** (P0-2). The path that behaves like a real cache job, a Geometry ROP through `render`, is one the `render` hint does not point to (P1-3). For 1.3, I recommend that `render` treat File Cache and ROP-like SOPs as render nodes, and that `parm_set press` verify the outputs of known save buttons. Then fix the silent callback menu (P1-4), `geo_read {frame}` (P1-5), partial results on cancel (P1-6), and the `geo_info` volume list (P1-7). Each of those cost me a retry or a blind spot in this run.
