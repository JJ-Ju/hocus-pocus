# 20 — FX sim + cache rerun on 1.3: the same pyro plume, cached through `render`

**Seat:** an AI agent working as an FX TD, repeating review 17's workload on the 1.3 code. I used only the MCP tool surface, `docs/tools.md` (with its `notes`) and the `hocuspocus://guide` resource (6,321 B, under the 8 KB budget). I did not read the server source.
**Build:** `release/1.3` at `1b390de`, installed editable into a fresh scratch venv. The host loaded that commit at launch (23:19). Four docs commits landed during the run (`123412f`, `941f846`, `961320c`, and at 23:26 `bf79445`, which edits the bridge instructions after I had read the guide). None of them touched host code. **`hocuspocus version`, `bridge_version` and `host_version` all still say `1.2.1`**, while `CHANGELOG.md` now has a 1.3.0 section (N6).
**Host:** Houdini 22.0.466 hython, headless, pid **53784**, started with `hocuspocus launch --headless --work-dir <scratch>/c20/fx13` into a fresh untitled scene. `HOCUSPOCUS_STATE_DIR=<scratch>/c20/state`, `HOUDINI_USER_PREF_DIR=<scratch>/c20/prefs/houdini__HVER__`, `profile = "full"` in `<scratch>/c20/prefs/houdini22.0/hocuspocus.toml` and in `HOCUSPOCUS_PROFILE`. `launch` returned in 1.8 s. At the end, `houdini_connect {quit: true}` returned `{"quit":true,"pid":53784,"exited":true}`, `houdini_status` then showed `connected: null, instances: []`, and `tasklist` found no pid 53784. I killed nothing.
**Client:** review 17's one-shot `mcp.Client` (`hp20.py`, the same as `hp17.py` plus a resource-read mode), with `PYTHONIOENCODING=utf-8` from the start. Each call started a fresh `hocuspocus-mcp` and logged tool, args bytes, text bytes, pretty bytes, isError, image count and in-call seconds.
**Date:** 2026-10-12, 23:19:41 (launch) to 23:26:47 (quit): **7 min 06 s wall clock, 24.4 s of it inside tool calls.**
**Result:** the same smoke plume, 48 frames at 0.1 voxel size, cached by **`render` on the File Cache** to `$HIP/cache/pyro.$F4.bgeo.sc` (48 files, 77 MB), flipbooked at 480×270 by an OpenGL ROP, plus a `viewport_capture` of frame 36. **0 `houdini_python` calls.** Saved as `<scratch>/c20/fx13/pyro.hip` (1,086,265 B, `dirty: false`). Evidence: `docs/redesign/evidence/city-destruction/61_pyro_frames_1.3.png`, a 1464×586 contact sheet (40.6 KB) of frames 1, 10, 19, 28, 38 and 48 from the flipbook.

---

## 1. What I built

The network is review 17's final one, except that the container is taller after one look iteration:

```
/obj/pyro (geo)
  src_sphere   sphere                     polymesh, rad (0.8,0.5,0.8), t (0,0.5,0), freq 6
  pyrosource   pyrosource                 mode 2, particlesep 0.05, initialize "source" (pressed with value)
  rasterize    volumerasterizeattributes  attributes "density temperature", voxelsize 0.05
  pyrosolver   pyrosolver (v2)            divsize 0.1, clampsize on, maxsize (6,9,6), t (0,4.5,0),
                                          disturbance + turbulence on, buoyancylift 0.15, substep 2
  cache        filecache::2.0             filemethod explicit, $HIP/cache/pyro.$F4.bgeo.sc, f 1-48,
                                          savebackground off                    (display/render)
/obj/cam_fx    cam                        t (13,4.5,13), r (-3,45,0), 35 mm, 480x270
/obj/key       hlight::2.0                distant
/out/flipbook  opengl                     camera /obj/cam_fx, res 480x270, $HIP/flip/pyro.$F4.png, f 1-48
```

The six steps were the same as in review 17: discover, build, cook and inspect across frames, cache, flipbook and look, then stress (jobs, cancel, bad paths, profile, memory). I also exercised everything 1.3 added for this workload: `render` on the File Cache with job progress and `outputs_summary`, `parm_set press` on Save to Disk (good and unwritable paths), `press` with `value` on `pyrosource initialize`, `geo_read {frame}`, `cook {wait_s: 0}`, `cook {profile}` on the solver, `houdini_status` memory, a mid-render `job cancel` then `job result`, and a headless `viewport_capture` of the smoke.

**The comparison is not perfectly like for like.** I knew the parm names and the final look from review 17, so discovery took 5 `node_type_info` calls instead of 12, and the build needed one look iteration instead of two. On the other hand, I spent 3 calls on a 1-frame flipbook by mistake (`render` defaults to the current frame; review 17 had passed `frames`), and I exercised more 1.3 paths. Per-call averages are a fairer comparison than totals.

---

## 2. Measurements

**Totals, side by side**

| | Review 17 (1.2.1) | Review 20 (1.3) | Change |
|---|---:|---:|---|
| Calls | 93 (1 a repeat after a client crash) | **75** (+1 `hocuspocus://guide` read, 6,321 B, not counted) | −19 % |
| Text bytes | 90,073 | **77,956** | −13 % |
| Pretty bytes | 122,503 | 100,082 | −18 % |
| Args bytes | 7,012 | 5,637 | −20 % |
| Avg text bytes per call | 969 | 1,039 | +7 % (two 8 KB render `job result`s, see N5) |
| Errors | 6 (2 probes, 2 expected `cancelled`, 2 friction) | **5** (3 deliberate probes, 2 expected `cancelled`, **0 friction**) | |
| Seconds inside tools | 58.8 | **24.4** | the 34 s and 17 s sims ran inside jobs, not inside calls |
| `cook` blocked before the job id | 10.0 s (twice) | **0.04 s** (`wait_s: 0`) | |
| Wall clock, launch to quit | 8 min 59 s | **7 min 06 s** | |
| First cache on disk | 2 min 10 s (call 23, `parm_set press`) | **1 min 46 s** (call 21, `render` on the File Cache, done in 0.34 s) | |
| First image returned | 3 min 29 s (call 39) | **2 min 52 s** (call 33, `job result` of the flipbook) | |
| Images returned | 4 | 4 (3 `render`/`job` thumbnails, 1 `viewport_capture`) | |
| `houdini_python` | 0 | 0 | |

**Per tool** (review 20, sorted by text bytes; review 17's average in the last column)

| Tool | Calls | Errors | Args B | Text B | Avg B | Max B | Secs | R17 avg B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `job` | 22 | 2 | 1,078 | 26,904 | 1,222 | 8,372 | 0.4 | 603 |
| `geo_info` | 5 | 0 | 170 | 7,558 | 1,511 | 2,214 | 0.1 | 1,882 |
| `events` | 1 | 0 | 2 | 7,275 | 7,275 | 7,275 | 0.0 | 5,798 |
| `node_type_info` | 5 | 0 | 444 | 7,068 | 1,413 | 3,371 | 0.4 | 1,266 |
| `parm_set` | 10 | 1 | 1,180 | 6,019 | 601 | 1,150 | 1.0 | 416 |
| `houdini_status` | 5 | 0 | 10 | 5,346 | 1,069 | 1,294 | 0.1 | 864 |
| `node_create` | 2 | 0 | 1,527 | 4,914 | 2,457 | 4,565 | 0.8 | 1,603 |
| `node_type_search` | 1 | 0 | 33 | 4,753 | 4,753 | 4,753 | 0.5 | 2,435 |
| `render` | 9 | 2 | 424 | 3,843 | 427 | 950 | 12.1 | 459 |
| `cook` | 4 | 0 | 295 | 2,088 | **522** | 907 | 3.7 | **2,586** |
| `parm_get` | 1 | 0 | 65 | 558 | 558 | 558 | 0.0 | 395 |
| `geo_read` | 2 | 0 | 162 | 499 | 249 | 250 | 0.2 | 539 |
| `viewport_capture` | 1 | 0 | 58 | 405 | 405 | 405 | 4.3 | 405 |
| `time` | 4 | 0 | 8 | 244 | 61 | 61 | 0.1 | 60 |
| `hip_save` | 1 | 0 | 148 | 232 | 232 | 232 | 0.0 | 230 |
| `problems` | 1 | 0 | 20 | 211 | 211 | 211 | 0.0 | 356 |
| `houdini_connect` | 1 | 0 | 13 | 39 | 39 | 39 | 0.6 | 38 |

Review 17 also used `node_info` (1) and `node_find` (1); I did not need them. `node_type_search` and `node_create` look larger on average only because I made fewer small calls; the comparable calls are the same size (`node_type_search pyro` 3,689 → 4,753 B, with more rows; the 6-item build 4,314 → 4,565 B). `parm_set` grew because a save-button press now returns `outputs_summary` with absolute paths (1,068 B for a good press).

**Jobs and polling**

| Job | Started by | Frames | Became a job after | Polls (status) | Other job calls | Outcome |
|---|---|---:|---|---:|---|---|
| `07a0…` | **`render /obj/pyro/cache`**, `wait_s: 0` | 48 | 0 s | 2 | 1 result (8,372 B) | done, 0.34 s (frames from the solver's memory cache) |
| `de0b…` | `render /out/flipbook`, `wait_s: 0`, no `frames` | 1 | 0 s | 2 | 1 result (795 B, thumbnail) | done, 7.9 s (my mistake: the default is the current frame) |
| `95b9…` | `render /out/flipbook`, `frames [1,48]`, `wait_s: 0` | 48 | 0 s | 2 (`"28/48 frames"`) | 1 result (8,262 B) | done, 5.1 s |
| `4380…` | `cook pyrosolver frame_range [1,120]` at 0.05, **`wait_s: 0`** | 120 | **0.04 s** | 3 (`frame 44/120`, `66`, `87`) | 1 cancel (too late), 1 result (2,801 B) | done, 34.3 s |
| `2d18…` | `cook pyrosolver frame_range [1,240]` at 0.05, `wait_s: 0` | 240 | 0.47 s | 1 | 1 cancel, 1 result (2,367 B) | **cancelled at 72/240, `detail.partial` with 72 frames** |
| `c960…` | **`render /obj/pyro/cache`, `frames [1,240]`**, `wait_s: 0` | 240 | 0 s | 3 (`frame 90.0 (90/240)` …) | 1 cancel, 1 result (925 B) | **cancelled, 155 files on disk, `partial.outputs_summary.count: 155`** |
| (three inline renders) | `render` with the default wait | 48 | finished inside the wait | 0 | 0 | done: cache 3.3 s and 3.2 s (773 B), flipbook 5.0 s (950 B) |

There were 22 `job` calls: 13 status polls (review 17: 13), 3 cancels and 6 results. Polls cost 190–229 B. Cancel took effect in about 0.3 s both times, and **the playbar stayed at 1 throughout** (`time` after every job). Memory from `houdini_status`: 421.7 MB at launch, **6,851.9 MB** during the 0.05-voxel cook, 7,454.2 MB (peak 7,473.2) during the 240-frame cache render, 1,094.7 MB after switching back to 0.1.

**Where the bytes went.** `job` is now the largest tool, and two calls account for 16.6 KB of it: the `result`s of the 48-frame cache and flipbook renders, which list all 48 absolute paths (N5). Without those two, the run is 61.3 KB. Inspection shrank: `cook` summaries went from 15.5 KB to 2.1 KB, and the three `geo_info {frame}` calls from 8.1 KB to 6.6 KB while now listing all six volumes.

---

## 3. Papercuts from review 17, one by one

| # | Papercut | Verdict |
|---|---|---|
| P0-1 | `cook {frame_range}` on a File Cache reports success and writes nothing | **Fixed** |
| P0-2 | Save to Disk fails silently | **Fixed** |
| P1-3 | No job, progress or cancel path for a File Cache | **Fixed** |
| P1-4 | Callback menus skip their callback; `press` refuses menus | **Fixed** for `parm_set`; `node_create` still silent (N2) |
| P1-5 | `geo_read` has no `frame` | **Fixed** |
| P1-6 | A cancelled job's result loses the work done | **Fixed** (cook and render) |
| P1-7 | `geo_info` hides half the volumes, spends half its bytes on `volvis` | **Fixed** |
| P2-8 | `cook {frame_range}` blocks 10 s; its summary repeats itself | **Fixed** |
| P2-9 | No memory reporting | **Fixed** in `houdini_status` (no `memory_delta_mb` on jobs) |
| P2-10 | `cook {profile}` on a solver is one opaque row | **Improved** (simulation row and note; no DOP breakdown; N3) |

**P0-1 — fixed.** The same call, `cook {paths: ["/obj/pyro/cache"], frame_range: [1,48], summary: "bbox"}`, still cooks 48 frames, and now says why nothing was written:
> `"notes":["Cooking /obj/pyro/cache does not write files: a cook passes its input through. render {rop_path: /obj/pyro/cache} saves its frame range as a job with progress and cancel; parm_set press on /obj/pyro/cache/execute saves in one blocking call."]`

The `cook` description itself now says "Cooking never writes files (render does)". The result is 907 B instead of 4,862 B (see P2-8).

**P0-2 — fixed.** Pressing Save to Disk with `file` set to `Q:/fxcache/pyro.$F4.bgeo.sc` now fails, and the whole batch is rolled back (the `file` parm was back on its old value afterwards):
> `{"code":"cook_failed","message":"items[2] (/obj/pyro/cache/execute): /obj/pyro/cache execute wrote 0 of 48 files: Failed to save output to file \"Q:/fxcache/pyro.0001.bgeo.sc\".","hint":"Check that the output directory is writable and the input cooks, then press again; render runs the same save as a job with progress and cancel.","detail":{"missing":[…20 paths…],"missing_count":48,"errors":[…],"item":2,"path":"/obj/pyro/cache/execute","rolled_back":true}}`

A good press returns `"pressed":true,"outputs_summary":{"count":48,"first":…,"last":…,"pattern":"…/cache_press/pyro.####.bgeo.sc","missing_count":0}`, and with `loadfromdisk` off beforehand also `"side_effects":{"loadfromdisk":[0,1]}`. The `value: null, raw: "0"` noise is gone.

**P1-3 — fixed.** `render {rop_path: "/obj/pyro/cache"}` works. It renders the node's own frame range through the ROP inside it (`"notes":["/obj/pyro/cache rendered through its ROP /obj/pyro/cache/render."]`), reports per-frame progress (`"frame 136.0 (136/240)"`), cancels, and returns `outputs_summary` plus `side_effects: {"loadfromdisk":[0,1]}`. Inline it is 773 B. A bad path through `render` fails the same good way as in 1.2.1: `/obj/pyro/cache/render failed to render frame 1.0: Could not create directory 'Q:/fxcache'.` An `output` override is refused with a clear message: `/obj/pyro/cache (filecache::2.0) writes through the ROP inside it, whose output cannot be overridden.` (hint, see N4).

**P1-4 — fixed in `parm_set`, not in `node_create`.** A plain `parm_set` of the menu now warns:
> `"notes":["initialize has a callback script that a plain set does not run (clicking the parm in Houdini would); pass press: true with the value to run it."]`

`{path: ".../initialize", value: "source", press: true}` then ran the callback in one call: `"pressed":true,"side_effects":{"initialize":["source","none"],"attributes":[0,2]}`. `rasterize` went from 0 prims to 2 VDBs (19,045 active voxels each). **But the same value set through `node_create … parms {"initialize": "source"}` returned no note**, and `rasterize` then cooked to `point_count: 0, bbox: null` with no warning, exactly as in 1.2.1 (N2). `node_type_info detail: full` does not mark callback parms either.

**P1-5 — fixed.** `geo_read {path: "/obj/pyro/cache", class: "prim", attribs: ["name","maximum"], frame: 24}` returned all 6 volumes with `"frame":24` (250 B), and `time` afterwards still showed frame 1.

**P1-6 — fixed for cook and render.**
- Cook, cancelled at 72/240: `{"code":"cancelled","message":"Job 53784-2d18091f22fd was cancelled after 72 of 240 frames.","detail":{"last_status":{…},"partial":{"frames_cooked":72,"results":[…],"frames":[…16 run-length rows…]}}}` (2,367 B).
- Render of the File Cache, cancelled at 155/240: `"message":"Job 53784-c960ba2691a4 was cancelled after 155 of 240 output files."`, `"partial":{"outputs_summary":{"count":155,…,"last":"…/pyro.0155.bgeo.sc","missing_count":85}}` (925 B). There were 155 files on disk, and the last one was complete (25.5 MB, like its neighbours).

**P1-7 — fixed.** `geo_info {path: "/obj/pyro/cache", frame: 24}` is 2,213 B (was 2,701 B) and lists **all six volumes** under `volume_columns [name, prim, resolution, voxel_size, min, max]`: density, temperature, flame, `vel.x`, `vel.y`, `vel.z`. `volvis` is now `{"elided":805,"keys":["ambientshadows","cdfield",…]}`. One leftover: `voxel_size` prints as `0.1000001`.

**P2-8 — fixed.** `cook {frame_range: [1,120], wait_s: 0}` returned the job id after 0.04 s (it blocked for 10.0 s in 1.2.1). `summary: "bbox"` is run-length encoded with `through`: 48 frames came back as **4 rows (907 B, was 4,862 B)**, and 120 frames at 0.05 as 21 rows (2,801 B).

**P2-9 — fixed in `houdini_status`.** `connected.memory: {rss_mb, peak_mb}` tracked the sim cache filling up (421.7 → 6,851.9 → 7,454.2 MB, back to 1,094.7 MB). Cook and render results still have no `memory_delta_mb`, so an agent has to poll `houdini_status` alongside the job.

**P2-10 — improved.** `cook {paths: [".../pyrosolver"], profile: true, frame: 24}` now labels the solver row and adds a note:
> `{"path":"/obj/pyro/pyrosolver","type":"pyrosolver","cook_time_ms":4.0,"simulation":{"dopnet":"/obj/pyro/pyrosolver/dopnet1","resimulated":true,"frame":24}}` and `"notes":["/obj/pyro/pyrosolver simulated frames in /obj/pyro/pyrosolver/dopnet1 up to frame 24; its cook_time_ms includes that simulation."]`

There are still no microsolver rows, and the row contradicts itself (N3).

**Honourable mentions**

| Mention | Verdict |
|---|---|
| Render `job result` repeats all 48 absolute paths | **Unchanged** (8,372 B and 8,262 B; inline results now leave them out and hint `job {action: result} lists every output`) |
| `node_type_search` clips descriptions mid UTF-8 sequence | **Fixed**: `"…and detona…"` ends in a real `…` (U+2026) |
| `job cancel` on a finished job returns `done` silently | **Unchanged**: the 120-frame cook finished before my cancel arrived, and `cancel` returned the plain `done` status with no `cancelled: false` |
| `node_create` of `Driver/opengl` has no deprecation note | **Unchanged** |
| OpenGL ROP progress stuck at `0/48`; frames print as `20.0` | **Progress fixed** (`"28/48 frames"` at 4.2 s); **`frame 90.0 (90/240)` unchanged** |

---

## 4. New papercuts

**N1. A false "nearly black" note on OpenGL flipbooks (P1).**
- **Tool / argument:** `render {rop_path: "/out/flipbook"}` at frame 1, a small smoke puff on the ROP's transparent background.
- **Exact note:** `"The thumbnail is nearly black (mean luminance 1.5/255): check lights, camera framing and exposure."`
- The attached thumbnail is fine: it is flattened onto grey, and the puff is plainly visible. The luminance is measured on the raw RGBA file, where the empty transparent pixels count as black (PIL: mean 1.5 at frame 1, 11.6 at frame 48). An agent that trusts the note will start debugging lights that are not broken.
- **Proposed change:** measure the flattened thumbnail, or only the pixels with alpha > 0. When almost all pixels are transparent, say `"mostly empty: the subject covers 2% of the frame"` instead.

**N2. `node_create` sets callback parms without the note `parm_set` now gives (P1).**
- **Tool / argument:** `node_create … pyrosource parms {"initialize": "source"}`.
- **Result:** `{"name":"initialize","value":"source","menu_token":"source","is_default":false}`, no `notes`. `rasterize` then cooks to `point_count: 0, bbox: null`, and `geo_info` and `problems` stay silent. This is the review 17 trap, still open on the path an agent uses most to build.
- **Proposed change:** add the same note to `node_create` (and `network_build`) results, or run the callback when a `parms` entry is `{value, press: true}`. `node_create` already accepts any `parm_set` item without path, so `{"initialize": {"value": "source", "press": true}}` might already work, but nothing says so.

**N3. `cook {profile}` says a 4 ms cook re-simulated 24 frames (P2).**
- The solver row has `"cook_time_ms":4.0` and `"resimulated":true`, and the note says the cook time "includes that simulation". The same 24 frames took about 1.5 s to simulate, so this force-cook read cached frames (as the `cook` notes say it usually does), and `resimulated` should be `false`.
- **Proposed change:** set `resimulated` from whether the DOP network actually stepped (compare its simulation cache before and after, or time the solve), and word the note on that basis.

**N4. The File Cache `output` hint names a menu index (P3).** `"hint":"Set the node's own output parm with parm_set (on a File Cache: filemethod 1 and file), then render without output."` `parm_set` takes menu tokens, and `node_type_info` shows `filemethod` as a menu whose value is `explicit`. Say `filemethod: "explicit"`.

**N5. The render `job result` path list is now the biggest cost in an FX run (P2).** This is review 17's honourable mention, promoted. With File Cache renders now the normal way to cache, every cache and flipbook result lists every absolute path: 8,372 B for 48 frames, and, by the same arithmetic, about 42 KB of paths for a 240-frame cache, more than twice the 16 KB response budget (I did not fetch one). The same `outputs_summary` already has `pattern`, `first`, `last` and `missing_count`. Return `outputs` only on request (`job {action: result, outputs: true}`), or only the missing ones. Also cap `detail.missing` on a failed press at a pattern plus a count, rather than 20 full paths (~700 B).

**N6. The 1.3 build still calls itself 1.2.1 (P3).** `pyproject.toml` is `1.2.1`, so `hocuspocus version`, `houdini_status.bridge_version` and `connected.host_version` all say `1.2.1`, while `CHANGELOG.md` has a 1.3.0 section. Bump it before the tag (this is review 16's N5 again).

**N7. Small inconsistencies in job status (P3).** A running cook's status says `"current":43 … "message":"frame 44/120"` (the message counts the frame in progress, `current` the frames done). A cancelled job's `detail.last_status` keeps `"state":"running"` and `"message":"frame 73/240"` next to `frames_cooked: 72`. Make the message use `current`, and set `last_status.state` to `cancelled`.

---

## 5. What worked

- **The cache step is now one obvious call.** `render {rop_path: "/obj/pyro/cache"}` wrote 48 frames inline in 3.3 s (773 B), and the same call with `wait_s: 0` and `frames [1,240]` gave a job with per-frame progress, a 0.3 s cancel and an exact partial count. The `cook` notes and the press hint both point to it.
- **Save to Disk is trustworthy.** A good press reports `outputs_summary` and its side effect, and a bad one fails with `cook_failed`, the missing files and a rollback of the batch.
- **Callback menus.** `press` with `value` ran the `pyrosource` callback, and `side_effects` showed what it changed (`attributes: [0, 2]`).
- **Inspection across frames.** `geo_info {frame}` and `geo_read {frame}` read any frame without moving the playbar. `geo_info` lists all six volumes in 2.2 KB.
- **Sims as jobs.** `cook {wait_s: 0}` returns at once, the run-length summary keeps a 120-frame result under 3 KB, and a cancelled cook keeps its frames.
- **Memory.** `houdini_status` showed the sim at 0.05 voxels taking 6.9 GB, which a 1.2.1 agent could not see.
- **Flipbook and capture.** The OpenGL ROP reported real progress and returned a thumbnail. `viewport_capture {camera, frame: 36}` drew the smoke headless on the first try (4.3 s, `opengl_rop`).
- **Lifecycle.** `hocuspocus launch --work-dir` → 75 one-shot bridges → `houdini_connect {quit: true}`, with no orphan processes.

---

## 6. Verdict

**1.3 fixes the cache step that review 17 named as the weak spot.** All ten review 17 papercuts are fixed or improved, and the two P0s are fixed outright: cooking a File Cache now says it wrote nothing and names the two ways to write, and Save to Disk verifies its outputs and fails loudly with a rollback. `render` on the File Cache is the job-shaped cache path that review 17 had to build a `/out` Geometry ROP for. The run had **0 friction errors** (1.2.1: 2), the first cache landed 24 s sooner and the first image 37 s sooner, and the whole workload took 75 calls, 78 KB and 7 minutes against 93 calls, 90 KB and 9 minutes, with no `houdini_python`.

What is left is smaller. The callback trap is closed in `parm_set` but still open in `node_create` (N2), which is where an agent sets `initialize` first. The "nearly black" note fires on every sparse OpenGL flipbook frame (N1). Render job results spend 8 KB per 48 frames on paths the summary already describes (N5). Before tagging, fix N1 and N2 and bump the version string (N6). N3, N4, N5 and N7 can wait for 1.3.x.
