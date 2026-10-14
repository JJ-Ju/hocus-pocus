# 24 — Vellum cloth + USD round trip, re-run on 1.4

**Seat:** the same seat as review 23: an AI agent working as an FX/pipeline TD, driving the workload through the MCP tools only. I read review 23, `docs/tools.md` and the `hocuspocus://guide` resource (7,256 B, up from 6,412 B). I did not read the server source.
**Build:** `release/1.4` at `3f52343`, installed editable into a fresh scratch venv. `hocuspocus version`, `bridge_version`, `host_version` and the MCP `serverInfo.version` all still say **1.3.0** (N6 below).
**Host:** Houdini 22.0.466 hython, headless, pid **62128**, port 52647. I started it with `hocuspocus launch --headless --work-dir <scratch>/c24/vel14`, with `HOCUSPOCUS_STATE_DIR=<scratch>/c24/state`, `HOUDINI_USER_PREF_DIR=<scratch>/c24/prefs/houdini__HVER__`, `profile = "full"` in `<scratch>/c24/prefs/houdini22.0/hocuspocus.toml` and `HOCUSPOCUS_PROFILE=full`. `launch` returned in 1.7 s. At the end, `houdini_connect {quit: true}` returned `{"quit":true,"pid":62128,"exited":true}`. After that, `tasklist` no longer listed pid 62128, and no capture child hython was left running. Other agents' Houdinis kept running, and I killed nothing.
**Client:** review 23's one-shot `mcp.Client` (`hp24.py`), extended to log the tool result's `_meta`. Each call started a fresh `hocuspocus-mcp` and logged the tool, args bytes, text bytes, pretty bytes, isError, image count, in-call seconds and `_meta`.
**Date:** 2026-10-13, 22:46:28 (launch) to 22:52:39 (quit): **6 min 11 s of wall clock, 23.9 s of it inside tool calls.**
**Result:** I rebuilt review 23's scene: a 24×24 cloth pinned at two corners, dropped over a sphere with Vellum and cached for 48 frames by `render` on a File Cache. I exported it with `sopimport` → `usd_rop`, re-imported it with `sublayer`, checked frames 1/24/48 and rendered frame 24 with Karma CPU at 480×270. The run made **0 `houdini_python` calls**. I saved the scene as `<scratch>/c24/vel14/cloth.hip` (1,209,683 B, `dirty: false`), then deleted every cache, USD layer, render and capture. Evidence: `docs/redesign/evidence/city-destruction/101_vellum_usd_karma_1.4.png` (480×270, 18.6 KB), the Karma thumbnail as `render` returned it, flattened onto grey.

**Headline: the USD round trip now works the first time.** A plain `render {rop_path: "/stage/export_usd"}` used the ROP's own 1–48 range, wrote the layers in one call, and listed both layer files: `cloth.usd` with 0 samples, and `collider_import.usd` at 1,662,923 B with **48 samples, `time_codes [1,48]`**. Read back, the layer had `"time_samples":48`, and its extents at frames 1, 24 and 48 match `geo_info` exactly. The `usdexport` SOP path is fixed too. All ten of review 23's papercuts are fixed or improved. The run found one new P1: a second USD ROP silently overwrites the shared `sopimport` save-path layer (N1).

---

## 1. Measurements, side by side

Review 23 is the baseline. Two caveats apply to the totals. First, I already knew review 23's answers (the Vellum input labels, the `trange` tokens, the Karma parms), so this run needed 12 discovery calls instead of 24, and the time-to-first numbers are mostly the agent's own thinking time. Second, this run added 24 calls for the 1.4 checks: 5 warm captures, the Flipbook and OpenGL `render camera` checks, the `events` origin check, and the single-frame probe ROP with its diagnosis. The **core** column leaves those 24 calls out. The per-tool averages and the like-for-like rows are the fair comparison.

**Totals**

| | Review 23 (1.3.0) | **Review 24 (1.4)** | Review 24, core only |
|---|---:|---:|---:|
| Calls | 91 (+ guide 6,412 B) | **87** (+ guide 7,256 B) | 63 |
| Text bytes | 95,454 | **63,073** (−34 %) | 50,557 |
| Pretty bytes | 127,630 | 80,657 | — |
| Args bytes | 10,115 | 9,410 | — |
| Avg text bytes per call | 1,049 | **725** (−31 %) | 802 |
| Errors | 5 (1 probe, 3 friction, 1 typo) | 8 (1 probe, 2 friction, 5 my own argument mistakes) | 7 |
| Seconds inside tools | 30.5 (9.8 in one `node_create`) | **23.9** (12.1 in 12 renders) | 12.6 |
| Wall clock, launch to quit | 8 min 42 s | **6 min 11 s** | — |
| Images returned | 3 | 8 (1 Karma, 2 ROP renders, 6 captures) | — |
| `houdini_python` | 0 | **0** | — |
| Discovery (`node_type_search` + `node_type_info`) | 24 calls, 46.4 KB, 46 % of bytes | 12 calls, 19.5 KB, 31 % | — |

**Time to first X** (from launch)

| Milestone | Review 23 | **Review 24** | Call in 24 |
|---|---:|---:|---|
| Network built and cooking | 1 min 57 s (9.8 s call) | **1 min 03 s** (0.86 s call) | #11 `node_create`, solver `cook_ms` 647 |
| **First cache on disk** (48 files, 2.2 MB) | 2 min 19 s | **1 min 14 s** | #13 `render /obj/cloth/cache`, job done in 2.9 s |
| First USD file on disk | 4 min 37 s (1 frame) | **1 min 55 s** (48 samples) | #27 `render /stage/export_usd`, no `frames` |
| **First correct 48-sample USD** | 5 min 58 s (only via `parm_set press execute`) | **1 min 55 s** (same call) | #27, 0.40 s inline |
| Round trip verified at 1/24/48 | 6 min 08 s | **2 min 30 s** | #35–37 `usd_stage {time}` |
| **First image** | 6 min 42 s | **2 min 39 s** | #38 `render /stage/karma_rop frames [24,24]`, 2.5 s |

**Per tool** (review 24, sorted by text bytes; the last column is review 23's average)

| Tool | Calls | Errors | Args B | Text B | Avg B | Max B | Secs | Avg B in 23 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `node_type_search` | 3 | 0 | 128 | 10,127 | 3,375 | 8,816 | 0.5 | 3,624 |
| `node_type_info` | 9 | 1 | 687 | 9,365 | 1,040 | 1,776 | 0.2 | 1,367 |
| `render` | 12 | 1 | 579 | 5,766 | 480 | 811 | 12.1 | 459 |
| `usd_stage` | 13 | 2 | 1,119 | 5,690 | 437 | 1,159 | 0.2 | 437 |
| `events` | 2 | 0 | 22 | 5,252 | 2,626 | 3,556 | 0.0 | 6,483 |
| `houdini_status` | 3 | 0 | 6 | 3,882 | 1,294 | 1,296 | 0.1 | 1,286 |
| `geo_info` | 4 | 0 | 184 | 3,867 | 966 | 1,183 | 0.1 | 2,345 |
| `node_create` | 8 | 1 | 4,719 | 3,421 | 427 | 960 | 1.2 | 496 |
| `job` | 6 | 0 | 294 | 3,327 | 554 | 1,653 | 0.1 | 489 |
| `cook` | 5 | 2 | 284 | 3,148 | 629 | 809 | 2.2 | 842 |
| `viewport_capture` | 6 | 0 | 509 | 2,705 | 450 | 530 | 5.7 | 318 |
| `parm_set` | 6 | 0 | 540 | 2,108 | 351 | 549 | 0.2 | 350 |
| `network_describe` | 2 | 0 | 70 | 1,991 | 995 | 1,026 | 0.1 | 1,032 |
| `problems` | 2 | 0 | 19 | 1,103 | 551 | 907 | 0.1 | 437 |
| `time` | 2 | 1 | 67 | 369 | 184 | 310 | 0.0 | 59 |
| `geo_read` | 1 | 0 | 96 | 342 | 342 | 342 | 0.2 | 1,971 |
| `parm_get` | 1 | 0 | 49 | 336 | 336 | 336 | 0.0 | 1,215 |
| `hip_save` | 1 | 0 | 25 | 235 | 235 | 235 | 0.1 | 233 |
| `houdini_connect` | 1 | 0 | 13 | 39 | 39 | 39 | 0.8 | 39 |

**Like-for-like calls**

| Call | Review 23 | Review 24 |
|---|---:|---:|
| `node_type_search {query: "vellum", category: "Sop", limit: 40}` (37 rows) | 12,503 B | **8,816 B** |
| `node_type_info vellumsolver detail: folders` | 1,526 B | 1,526 B |
| `node_create` of the 7-node Vellum network | 870 B, 9.8 s | 960 B (adds `cook_ms`), **0.86 s** |
| `geo_info /obj/cloth/cache frame 24` | 2,948 B | **1,183 B** full, **756 B** with `attributes: "names"` |
| `job result` for the 48-frame File Cache | 1,557 B | 1,653 B (two notes and `side_effects` added) |
| `render usd_rop` 1–48, result | 1,358 B, **1 sample** | 829 B (`job result`) / 760 B inline, **48 samples** |
| `events {}` after the build | 6,483 B, 25 rows, 16 Houdini writes as `agent` | **3,556 B**, 25 rows, 0 Houdini writes |
| Karma `render frames [24,24]` | 532 B, 4.3 s | 536 B, 2.5 s |
| `viewport_capture lop_path: /stage/karma_rop` | `invalid_argument`, plus a retry | 530 B, 3.5 s, first try |
| Warm `viewport_capture` ×5 (headless) | — | 435 B each, **0.40 / 0.47 / 0.44 / 0.44 / 0.47 s** |

**`_meta.timing`** came back on every host call that succeeded. Examples: `node_type_search` `{"main_thread_ms":399.0,"queue_ms":0.1}`, the Vellum `node_create` 834.3 ms, `geo_read` 190.2 ms, `hip_save` 74.5 ms. Validation errors (bridge-side) and the bridge-local `houdini_status` and `houdini_connect` carry no `timing`. Every job-backed tool reports `{"main_thread_ms":0}` with no `queue_ms`: `render`, `job`, `viewport_capture`, `events` and `cook`, even a `cook {profile}` that held the main thread for 1,811 ms (N5).

---

## 2. The 1.4 additions, exercised

- **`render` on `usd_rop` without `frames`** gave `"frames":[1,48,1]` and the note `"Rendered /stage/export_usd's own frame range 1-48; pass frames to render others."`. It was one inline call (0.40 s), `outputs` listed `cloth.usd` once, and `layers` was `[{cloth.usd, bytes 700, time_samples 0}, {collider_import.usd, bytes 1662923, time_samples 48, time_codes [1,48]}]`.
- **With `frames: [1,48], wait_s: 0`**, the job finished in 0.39 s and its result was the same, with no note. A `usd_rop` left at `trange: off` gave `"frames":[1,1,1]` with the note `"Rendered the current frame (1) only: /stage/single_probe's Valid Frame Range is 'Render Current Frame'. Pass frames to render a range."`. With `frames: [1,3]` it wrote **3 samples, `time_codes [1,3]`**.
- **Read-back via `usd_stage`.** After the `sublayer`, `/cloth/mesh_0` `extent` and `points` reported `"time_samples":48` at times 1, 24 and 48. The extents were flat at y=3 at time 1, `[[-2,0.6816572,-2.191145],[2,3.008478,1.153945]]` at 24 (exactly `geo_info`'s frame-24 bbox) and `[[-2,0.5252781,-2.179837],[2,3,1.071355]]` at 48.
- **`usdexport` SOP.** Rendering it without `frames` went through `lopnet_EXPORT/USD_OUT` and wrote `cloth_sop.usd` at 1,659,293 B with 48 samples, and its read-back showed 48 samples at 24.
- **`render camera` on a Flipbook ROP.** `render {rop_path: "/out/fb", frames: [24,24], camera: "/cameras/cam"}` rendered through the camera prim in 3.5 s, and afterwards `parm_get` showed `cameraprim` back at `""`. It worked only after I set `opsource: lop` (N4). The deprecated OpenGL ROP did the same in 4.8 s. Its `node_create` row carries `deprecated: true` and the note `"Driver/opengl is deprecated since Houdini 22.0: Replaced by the Flipbook ROP. It still works for now."`.
- **Warm capture child.** The first headless `viewport_capture` took 3.5 s, and the next five took 0.40–0.47 s. Each image showed the right frame (10, 20, 30, …), and `source_used` was `flipbook_rop` every time. No child was left running after `quit`.
- **`viewport_capture lop_path: /stage/karma_rop`** worked on the first try, with `"lop_path":"/stage/rset"` and the note `"Captured /stage/rset, the LOP /stage/karma_rop renders: a ROP has no output stage."`. `usd_stage {lop_path: "/stage/karma_rop", summary: true}` read the same stage, with the note `"Read /stage/rset, the stage /stage/karma_rop renders: a ROP has no stage of its own."`.
- **`geo_info attributes: "names"`** gave `"point":["v","airresist",…,"P","pscale"]`, 756 B. Solver internals are left out by default in both modes, with `internal_attribute_count: 25` and a note naming the first six.
- **`node_create cook: false`** gave `cook_state: "not_cooked"` on the `sublayer` and no `cook_ms`. With the default cook, every row carries `cook_ms`. The Vellum solver's 647 ms and `cloth_con`'s 109 ms now explain where a slow create goes.
- **`network_describe format: outline`** gave `"inputs":["/obj/cloth/cloth_con","/obj/cloth/cloth_con:1"]` for `pin_con` and `["/obj/cloth/pin_con","/obj/cloth/pin_con:1","/obj/cloth/collider"]` for the solver.
- **`events` origins.** A `parm_set` of the camera's `focalLength` and `horizontalAperture` and of `rset resolutionx` produced 11 rows. Three were `origin: agent` (the three parms I set). Eight were `origin: houdini`: `focalLengthConverted`, `verticalApertureSwitch`, `verticalApertureConverted`, `horizontalApertureConverted`, the light guide scales on `/stage/key` and `/stage/fill`, `rset resolution` and `karma_rop labelparm17`. `render`'s camera set-and-restore left no event.
- **Busy host.** A `houdini_status` sent during the 48-frame cache job came back in 0.03 s with `"busy":false,"jobs_running":1`. In review 23 the same call blocked for 3.6 s.

---

## 3. Review 23 papercuts, one by one

| # | Papercut | Verdict | What 1.4 does now |
|---|---|---|---|
| P0-1 | USD ROP over a range writes one sample and reports 48 | **Fixed** | One render call. `layers` reports `time_samples: 48, time_codes [1,48]`, and both `usd_rop` and `usdexport` read back 48 samples. The `cook_failed` check for fewer frames than asked is documented. I could not trigger it, since every export was correct. |
| P1-2 | `render` ignores the ROP's own range | **Fixed** | Without `frames` it uses `f1–f3`: `"Rendered /stage/export_usd's own frame range 1-48; pass frames to render others."`. At `trange: off`: `"Rendered the current frame (1) only: /stage/single_probe's Valid Frame Range is 'Render Current Frame'. Pass frames to render a range."`. This is word for word what review 23 proposed. |
| P1-3 | Outputs count one file N times and miss the data layer | **Fixed** | `outputs` lists `cloth.usd` once, and `layers` adds `collider_import.usd` with bytes, samples and time codes. |
| P1-4 | Nothing says `sopimport` splits the export into a second file | **Fixed** (small leftovers, N7) | Before any export, `usd_stage include: ["layers"]` on `collider_import` shows `{"identifier":"anon:…:LOP","save_path":".../vel14/usd/collider_import.usd","owner_node":"/stage/collider_import"}`. After the re-import, rows carry `time_codes [1,48]`. No `render` note spells out "root sublayers ./collider_import.usd", but `layers` makes the split plain. |
| P1-5 | Outline drops the output index | **Fixed** | `"/obj/cloth/cloth_con:1"`, `"/obj/cloth/pin_con:1"`. |
| P2-6 | `node_type_search` repeats constant fields | **Fixed** | 12,503 → 8,816 B for the same 37 rows. `is_current_version` is gone, and `child_category` and `typical_parents` moved into one `"common":{"child_category":"Sop","typical_parents":["a geo object such as /obj/geo1"]}`. In a mixed-category search (`"usd export"`) they stay on the network-type rows only. |
| P2-7 | `node_type_info` repeats its header, and globs match inside words | **Improved** | `inputs` becomes `inputs_count` on narrowed calls, and word-start matches rank first: `*pin*` puts `pingroup`, `pintype` and `pinrotation` first and moves the damping parms into `substring_matches` with a note. The header (`description`, `outputs`, `min/max_inputs`, `is_current_version`, `parm_columns`, `hint`) is still repeated on every narrowed call, about 450–600 B each time. A new bug: exact names are classified as substring matches (N2). |
| P2-8 | `geo_info` on Vellum is mostly solver internals | **Fixed** | Internals are left out by default with `"internal_attribute_count":25` and the note `"25 solver-internal attribute(s) left out (vlast, has_pprevious, target_pt, hitnml, dPw, disableexternal, ...); geo_read with attribs reads them."`. 2,948 → 1,183 B, or 756 B with `attributes: "names"`. The proposed `attributes_same_as_frame` was not added. |
| P2-9 | `events` labels Houdini's LOP writes as the agent's | **Fixed** | A `node_create` of the LOP chain records no Houdini writes. A `parm_set` tags them `origin: "houdini"` (8 of 11 rows above). Not done: one row per node per call. `rset resolution` appears twice, once `houdini` (seq 28) and once `agent` (seq 36). |
| P2-10 | Stage tools refuse a render ROP | **Fixed** | Both `viewport_capture` and `usd_stage` read the ROP's input, with the notes quoted above. |
| P3 | `node_create` slow with no note | **Fixed** | `cook_ms` on every row (solver 647 ms). The 9.8 s first cook did not recur on this machine: 0.86 s for the whole call. |
| P3 | `usd_rop` `include_help` is `"See the USD render node."` | **Unchanged** | Same text. `usdexport` and `usd_rop` still have empty `description`s in search and info. |
| P3 | `problems` `missing_file` repeats the absolute path 3 times | **Unchanged** | It still repeats it 3 times in the `missing_file` row (in `message` twice and in `file`), plus once in the `error` row. |
| R20 N3 | `cook {profile}` honest about warm caches | **Changed, see N3** | After `resimulate`: `"resimulated":true`, 1,811 ms (correct). Repeat cooks at the same frame give `"resimulated":true` at 77 ms and 208 ms. |

---

## 4. New papercuts

**N1 (P1). A second USD ROP silently rewrites the shared `sopimport` save-path layer.**
- **Tool / argument:** `render {rop_path: "/stage/single_probe", frames: [1,3]}`. This is a second `usd_rop` with a different `lopoutput` (`probe.usd`), wired to the same `collider_import`.
- **What happened:** The result lists `collider_import.usd` at `bytes 91557, time_samples 3, time_codes [1,3]`. That is the same file `/stage/export_usd` had written with 48 samples. No note. `/stage/reimport`, which feeds Karma, then read `"time_samples":3`, and at time 24 returned frame 3's nearly flat cloth (`[[-2.000575,2.971533,-2.000777],[2.000396,3,1.999603]]`). A `reload` press did not bring it back. Re-rendering `export_usd` did. This is Houdini's behaviour (the `sopimport` default `savepath` is `$HIP/usd/$OS.usd`, whatever the ROP's output), but it is exactly the kind of silent clobber that P0-1 was.
- **Proposed change:** `render` already reads every layer back. When a layer it writes was written by another ROP's render in this session, or is loaded by a LOP in the scene, and its sample count changes, add a note like `"collider_import.usd (sopimport save path of /stage/collider_import) was 48 samples from /stage/export_usd and is now 3; /stage/reimport reads it."`. Also have `usd_stage layers` flag a `save_path` shared by several ROPs.

**N2 (P2). `node_type_info parms`: exact names are reported as substring matches.**
- `parms: "*pin*|grouptype|constrainttype|group"` gave `"substring_matches":["constrainttype","grouptype","group","stretchdampingratio",…]` and the note `"11 parm(s) matched … only inside a word"`, but 3 of those 11 are exact names.
- On the Flipbook ROP, `parms: "camera|loppath|picture|res*|trange|f|*output*"` gave `"substring_matches":["trange","f","camera","loppath","cameraprim"]`. Only `cameraprim` (via `camera`) is arguably inside-word, and `picture` is correctly listed as a word-start match.
- **Proposed change:** treat a `|` alternative without wildcards as an exact match (word-start rank). Count only the wildcard alternatives' inside-word hits in the note.

**N3 (P2). A repeat `cook {profile}` on a warm Vellum solver says `resimulated: true`.**
- The first cook after `resimulate` returned 1,811.2 ms with `"resimulated":true`. Two more identical calls at frame 24 returned 77.3 ms and 208.5 ms, also with `"resimulated":true` and the same note: `"/obj/cloth/vsolver simulated frames in /obj/cloth/vsolver/dopnet1 up to frame 24; its cook_time_ms includes that simulation."`. My guess is that a forced cook re-steps only the last frame, but the result reads like a full re-run. Review 23 got `"resimulated":false` with a "cache already held frame 24" note in the same situation, so this looks like a regression of review 20's N3.
- **Proposed change:** report the frames actually simulated (`"simulated_frames":[24,24]`) next to `resimulated`, and keep the "cache held frame N−1, only frame N was re-stepped" wording.

**N4 (P2). `render camera:` on a Flipbook ROP at `opsource: obj` gives a misleading error.**
- `render {rop_path: "/out/fb", camera: "/cameras/cam"}` (the ROP has `loppath` set, but `opsource` is at its default `obj`) failed with `node_not_found`, `"No node at /cameras/cam."`, hint `"The parent /cameras does not exist either; node_find {root: \"/\"} lists what does."`. It cost one `node_type_info` and one `parm_set` to find `opsource`.
- **Proposed change:** when `camera` is not a node, the ROP has `cameraprim`, and its `loppath` is set, say `"/out/fb reads /obj (Source: obj); set opsource to lop to render the camera prim /cameras/cam from /stage/rset."`. On success, add a note naming the override (`"Rendered through /cameras/cam (cameraprim restored)."`).

**N5 (P3). `_meta.timing` is `{"main_thread_ms":0}` on job-backed tools.**
`render`, `job`, `viewport_capture`, `events` and `cook` all report 0 with no `queue_ms`, including a 1.9 s `cook {profile}` that ran on the main thread. Either measure them, or leave `timing` out where it is not measured.

**N6 (P3). The version still reads 1.3.0 on `release/1.4`.**
`hocuspocus version` says `hocuspocus 1.3.0 (hp/v1, mcp 2.3.0, …)`, as do `bridge_version`, `host_version` and `serverInfo.version`. Bump it before tagging, or review 20's N6 comes back.

**N7 (P3). `layers` rows mix path styles.**
For file layers, `save_path` repeats `identifier` with backslashes (`C:\\Users\\…\\cloth.usd` next to `C:/Users/…/cloth.usd`). Leave `save_path` out when it equals the identifier, and use forward slashes as everywhere else.

---

## 5. Friction log (chronological)

| # | Call | What happened | Cost |
|---|---|---|---|
| 1 | #3 `node_type_info {name: …}` | My mistake (`name` for `type`); a clear `invalid_argument` | 1 call |
| 2 | #8 `time {action: "set"}` | My mistake; the error listed the allowed `frame, range, fps` | 1 call |
| 3 | #10 `node_create … trange: "range"` | Repeated on purpose: same good menu error, rolled back | 1 retry |
| 4 | #49 `render /out/fb camera: /cameras/cam` | N4 | 2 calls |
| 5 | #56, #58 `cook {path: …}` | My mistake twice; `"path: unknown property; did you mean paths?"` | 2 calls |
| 6 | #69 `usd_stage prim /cloth/mesh_0` on the `usdexport` layer | My wrong prim. The candidates (`/usd_out`, `/HoudiniLayerInfo`) fixed it at once | 1 call |
| 7 | #71 `usd_stage` on the missing-file `sublayer` | Deliberate probe: `cook_failed`, then `problems` gave `error` + `missing_file` with `raw '$HIP/usd/missing_cloth.usd'` | probe |
| 8 | #76–#80 | N1: the probe ROP clobbered the 48-sample layer; diagnosed and restored in 5 calls | 5 calls |

Review 23's P0-1 diagnosis took 10 calls and 1 min 30 s, and its locked-`resolution` error came back unchanged. Neither came up this time: the first was fixed, and I passed `resolutionx` directly.

---

## 6. Verdict

**1.4 fixes the USD round trip.** The workload that in review 23 silently shipped a frozen layer now reaches a correct 48-sample USD on the first `render` call, with no `frames` argument. The result says how many samples each layer holds, so the agent can see it is right without a second tool. Every review 23 papercut is fixed or improved: 9 of the 10 fixed outright and 1 improved (P2-7), plus one of the three P3s. Byte use fell by a third: 725 B per call against 1,049, the Vellum search fell from 12.5 to 8.8 KB, `geo_info` from 2.9 to 0.8–1.2 KB and `events` from 6.5 to 3.6 KB. The warm capture child does what it promises (3.5 s, then 0.40–0.47 s), and render ROPs are now valid stage sources. The run used no `houdini_python`, and the time to first image dropped from 6 min 42 s to 2 min 39 s, part of it from knowing the answers and part from the tools.

Before tagging, I would fix **N1** (warn when a render rewrites a layer that another ROP produced or the scene reads: the same failure class as P0-1, now one step removed), **N3** (the `resimulated` wording, a likely regression of review 20's N3) and **N6** (the version string). N2, N4, N5 and N7 are small and fit the 1.4.x polish budget. The P2-7 header repetition is the largest remaining byte cost in discovery.
