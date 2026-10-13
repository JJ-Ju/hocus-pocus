# 19 — Two instances (GUI + headless worker) and the shipped prompts

**Seat:** an AI agent working as a pipeline TD. I used only the MCP surface (tools, prompts, resources), `docs/tools.md`, the README, the quickstart and reviews 15/16. I did not read the server source.
**Build:** `release/1.3` at `88e654c` (1.2.1). The bridge came from a `git archive HEAD` snapshot installed non-editable into a scratch venv (`hocuspocus 1.2.1 (hp/v1, mcp 2.3.0)`), as review 15 §3.0 recommends. The GUI host loaded through the dev-mode package in the real pref dirs (`→ checkout src`, 1.2.1).
**Profile:** `full` everywhere. `HOCUSPOCUS_PROFILE=full` was in the environment of both launches and of the bridge. The worker also had `profile = "full"` in its isolated `<scratch>/c19/prefs/houdini22.0/hocuspocus.toml`. `doctor` reported `hocuspocus.toml: none (defaults)` for the real pref dirs, so I created no toml there; the GUI inherited the profile from the environment.
**Instances:**
- GUI `houdinifx` pid **3084**, from `hocuspocus launch --hip <scratch>/city/city_v01.hip --wait 240` (10.2 s to register).
- Headless worker `hython` pid **61900**, from `hocuspocus launch --headless --work-dir <scratch>/c19/worker` (2.3 s). `HOUDINI_USER_PREF_DIR` was isolated for that one command.
- Later, worker 2 (pid 61996) and worker 3 (pid 41120), launched the same way.
- `HOCUSPOCUS_STATE_DIR=<scratch>/c19/state` for every launch and the bridge, so other agents' hythons on this machine (1908, 9284) never appeared.

**Client:** one persistent `mcp.Client` session (`daemon.py`, one `hocuspocus-mcp`, fed by a file-queue CLI), because one-shot clients get a new bridge per call and cannot test selection. Each call logged tool, believed target pid, args/text bytes, images, isError and seconds. One session restart (to fix my pid tracker) doubled as a fresh-bridge test.
**Totals:** 92 logged requests over 7 min 18 s (22:23:46–22:31:04). They returned 145.1 KB of text and 6 images. 8 returned isError: 2 were my own schema mistakes, 1 was a deliberate unsaved-quit probe, and 5 were multi-instance failure modes. I made **0 `houdini_python` calls**. Evidence: `docs/redesign/evidence/city-destruction/80_two_instance_render.png` (1232×474, 470 KB), frames 1/5/10/14/19/24 of the worker's OpenGL render.

---

## 1. What I did

1. **Two instances.** I launched the GUI and then the worker. The first `houdini_status` listed both with `label`, `ui` and `selected`, and **selected the worker**: `"2 Houdini instances are running; using the most recent (pid 61900). Others: 3084. Pin one with houdini_connect {pid}."` An implicit `time {}` went to the worker with no warning in its result.
2. **Edit in the GUI.** After `houdini_connect {pid: 3084}` I made one `node_create` with three items: `/obj/orbit` (null, `ry` keyed 0→90 over 1–24), `/obj/cam_two` parented to it, and `/out/gl_two` (OpenGL, 640×360, frames 1–24, `$HIP/render/two.$F4.png`). Then a `parm_get` check, a `parm_set` on three parms, a 0.41 s `opengl_rop` check capture, and `hip_save` to `<scratch>/c19/two/city_work.hip` (278 KB).
3. **Render on the worker.** `houdini_connect {pid: 61900}`, then `hip_open` (0.2 s), then `render {rop_path: /out/gl_two, frames: [1,24], wait_s: 0}`, which returned `job_id 9c3e6f7ca53e`. I switched back to the GUI at once and polled with `job` (§3). The job finished in **5.09 s** on the worker, and `job result` (from the worker) returned all 24 outputs and a thumbnail. I built the contact sheet from those PNGs.
4. **Edit while it renders.** On the worker I set `res` to 1920×1080 and started `render` with frames 1–240 and `output: $HIP/render_long/long.$F4.png`, about 1.4 fps. While it ran, the GUI took a `parm_set`, a two-item `node_create` and a 0.35 s capture. None of them was slowed: every GUI call took ≤ 0.05 s apart from the capture.
5. **Failure modes.** Killed the worker mid-render (frame 29), then `job`, `houdini_status` and a write meant for the worker; launched worker 2; `houdini_connect` a dead pid; pinned the GUI and launched/quit worker 3 by pid; `disconnect` then a call, then `connect {}`; `events` on worker 2 after GUI edits.
6. **Prompts and resources.** `list_prompts`, `get_prompt` ×4, each followed literally in the GUI; read `hocuspocus://guide`, `houdini://outline` and the resource list.
7. **End.** Quit worker 2 by pid (GUI pin kept), GUI `quit` refused without `on_unsaved`, then `discard`; final `houdini_status` → `instances: []`, both processes gone.

---

## 2. Measurements

### 2.1 Per tool (92 requests)

| tool | calls | errors | args B avg | text B avg | text B max | text B total | in-call s | images |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| read_resource (guide, outline) | 2 | 0 | – | 27,062 | **51,982** | 54,124 | 0.04 | 0 |
| network_describe | 4 | 0 | 42 | 8,887 | 15,256 | 35,549 | 0.38 | 0 |
| houdini_status | 10 | 0 | 2 | 1,463 | 2,112 | 14,634 | 0.20 | 0 |
| houdini_connect | 18 | 2 | 15 | 677 | 1,083 | 12,193 | 3.30 | 0 |
| job | 6 | 3 | 38 | 939 | 4,754 | 5,634 | 0.03 | 1 |
| events | 6 | 0 | 6 | 624 | 1,318 | 3,747 | 0.05 | 0 |
| get_prompt / list_prompts | 5 | 0 | 30 | 822 | 1,110 | 4,108 | 0.00 | 0 |
| viewport_capture | 5 | 0 | 44 | 443 | 590 | 2,216 | 2.54 | 5 |
| node_create | 5 | 0 | 373 | 420 | 707 | 2,100 | 0.24 | 0 |
| parm_set | 7 | 0 | 84 | 252 | 488 | 1,765 | 0.19 | 0 |
| parm_get | 2 | 0 | 82 | 726 | 1,243 | 1,452 | 0.05 | 0 |
| list_resources | 1 | 0 | 2 | 1,386 | 1,386 | 1,386 | 0.00 | 0 |
| node_info | 2 | 1 | 48 | 674 | 974 | 1,349 | 0.02 | 0 |
| geo_info | 2 | 0 | 32 | 616 | 810 | 1,233 | 0.05 | 0 |
| node_find | 3 | 1 | 30 | 351 | 569 | 1,055 | 0.06 | 0 |
| problems | 2 | 0 | 18 | 358 | 515 | 717 | 0.09 | 0 |
| hip_open / hip_save | 3 | 0 | 152 | 253 | 259 | 758 | 0.43 | 0 |
| time | 4 | 1 | 5 | 97 | 206 | 387 | 0.13 | 0 |
| render | 2 | 0 | 74 | 193 | 194 | 386 | 0.04 | 0 |
| cook | 2 | 0 | 38 | 150 | 152 | 300 | 0.17 | 0 |
| node_delete | 1 | 0 | 25 | 40 | 40 | 40 | 0.04 | 0 |
| **total** | **92** | **8** | | **1,578** | | **145,133** | **8.1** | **6** |

**Calls by target:** GUI 3084: 62. Worker 61900: 12. Worker 2 61996: 10. None (disconnected or no instance): 7. Silent fall-over 61900 → 3084: 1, plus the deliberate write that followed it.

### 2.2 Scenario timings

| Step | Result |
|---|---|
| `hocuspocus launch` GUI with the city hip / headless worker | 10.2 s / 2.3 s to register |
| `houdini_connect {pid}` switch | 0.01–0.05 s, 790–1,083 B (it echoes the full `connected` block) |
| GUI `hip_save` → worker `hip_open` | 0.13 s + 0.20 s |
| Worker `render` 24 frames, 640×360 OpenGL | job, **5.09 s**; `job result` 4,754 B (24 full paths **and** `outputs_summary`) |
| Worker `render` 240 frames, 1920×1080 | about 1.4 fps; 29 frames on disk when killed |
| GUI calls during the worker render | ≤ 0.05 s; capture 0.35 s. No interference. |
| `quit` worker by pid / GUI with `discard` | 0.41–0.63 s / 1.9 s, `exited: true` |
| Bytes spent on prompt-driven inspection | `inspect_scene` as written: **29.7 KB in 3 pages**. The outline alternative: 5.9 KB in 1 call. |

---

## 3. Instance selection as observed

| Situation | What the bridge did | Visible to the agent? |
|---|---|---|
| Fresh session, GUI and worker running | Auto-selected the **most recently started** instance (the worker) | Only in `houdini_status.warnings` and `houdini_connect {}`. **Not** in other tool results (`time {}` went to the worker silently). |
| A second fresh session (bridge restart) | Same: the worker again. Selection does not persist between sessions. | Same |
| `houdini_connect {pid}` | Pinned. Kept across launches of new instances (worker 3 did not take it) and across a `quit` by pid of another instance | `selected: true` in `instances` |
| Pinned worker killed mid-render | **Fell over silently to the GUI.** `job` went to the GUI and answered `job_not_found`. `houdini_status` showed `connected.pid 3084` with **no warning**. A `parm_set` meant for the worker changed the GUI's `/out/gl_two/res`. | Only if you compare `connected.pid` |
| Unpinned (after the fall-over), new worker launched | **Selection moved to the new worker** (61996) | `warnings` in `houdini_status` only |
| `houdini_connect {pid: <dead>}` | `houdini_offline`, `retryable: true`, `candidates: ["61996","3084"]` | Yes, but the candidates carry no labels |
| `{disconnect: true}` then a call | `houdini_offline`: "The bridge was disconnected with houdini_connect {disconnect: true}." | Yes, clear |
| `houdini_connect {}` after a disconnect | The most recent again (the worker), with the warning | Yes |

**Telling the instances apart:** an agent sees `label` (`houdinifx` vs `hython`), `ui` (true/false), `started`, `port` and `hip`. After the worker opened the GUI's saved hip, **both rows showed the same `hip` path**. `ui` and `label` were then the only discriminators. No row says "busy" or "jobs running", and nothing lets the agent name an instance ("editor", "worker"). Tool results other than `houdini_status`/`houdini_connect` never say which pid answered.

**Jobs:** a `job_id` lives in the host that started it. The bridge does not route by job id. From the GUI-selected bridge, `job {action: status, job_id}` returned `job_not_found`: "No job with id '9c3e6f7ca53e'.", with the hint "Jobs live in the Houdini process that started them and do not survive a Houdini restart". That hint suggests a crash, not "wrong instance". `job {action: list}` returned `{"jobs":[]}` from the GUI while the worker was rendering.

**Events:** independent per instance, which is correct. GUI edits did not appear on the worker. But `seq` restarts at 1 in each host, and the response carries no instance identity. `since: 9` carried over from the GUI would silently skip worker events 3–9. `since: 99` on the worker returned `reset: true`, which is good.

---

## 4. Friction log

- **The killed worker** is the most dangerous moment of the session (§3). An agent that rendered on the worker and later says "now apply the fix on the worker" edits the user's GUI scene instead. Every call succeeds.
- **The first call lands on the wrong instance.** With the default "most recent" rule, the order of the brief (GUI first, then the worker) puts the first agent edits on the throwaway worker. A naive agent who skips the warning in `houdini_status` builds in the wrong Houdini.
- **`hip_save` in the GUI emitted two events on `/out/gl_two`:** seq 7 `ParmTupleChanged picture` and seq 8 `ParmTupleChanged` with no `detail`. These are save-time writes; the notes only suppress those for TOP networks.
- **The OpenGL ROP's own PNGs** have a transparent background, so they flatten to black in the contact sheet. `viewport_capture` output is grey. This is documented, but it is surprising when a sheet is built from `render` outputs.

---

## 5. Prompts: followed literally

| Prompt | Calls as written | Outcome | Fewest calls possible | Verdict |
|---|---:|---|---:|---|
| `inspect_scene` | 5 (status, 3 describe pages, problems) | Correct, but **29.7 KB**. `network_describe {root:/obj, depth:2}` defaults to `format: data`. Page 1 (7.7 KB) is mostly `building_gen`'s render-property `parmtemplates` and ends `truncated` after one node. | 3 (status, outline, problems), about 8 KB | **Rewrite.** Say `format: "outline"`, or read `houdini://outline`. Mention picking the instance when status warns. |
| `build_sop_chain` | 4 (create, cook, geo_info, capture) | Built in one `node_create`, 300 copies, bbox right. The final bare `viewport_capture` grabbed the viewer **as-is, in `/obj/city_gen` context** (note: "The viewer shows /obj/city_gen, not /obj"). The new object was not framed. | 3 (`node_create` already returns per-node errors, so `cook` is redundant) | **Good with a fix.** Capture with `{"fit":"all"}` or `source: opengl_rop`, and drop the separate cook unless the results show `not_cooked`. |
| `debug_red_node` | 4 (node_info, problems, parm_set, cook) | Root cause found (`freq` undefined, line 2 col 33). Fixed with `chf("freq")`, cooks clean. The "fix" leaves `amp` and `freq` at 0 because no spare parms exist; the prompt never mentions the wrangle's create-spare-parms button. `problems` repeated `node_info`'s errors, and `parm_set` already returned `cook_state: cooked, errors: []`. | 2 (node_info, parm_set) | **Adequate.** Drop the mandatory `problems` and `cook`. Add: for wrangles, `ch*()` to a missing parm silently gives 0, so create spare parms (`press` the button). |
| `turntable_preview` (`/obj/building_gen`) | 5 (geo_info, node_create, time, 2 captures) | **Poor outcome.** `building_gen` has its display flag **off** and sits at the centre of the city. Both captures show a city street with no building. The prompt also has the agent **change the user's playbar range** (`time {range:[1,48]}`) in a live GUI. The captures are 1024×768, not the camera's 16:9. The quarter turn was right (`ry` 91.9° at frame 13, auto-slope bezier). | 4 | **Rewrite.** Check `flags.display` from the outline. Isolate the object, or warn when other displayed objects intersect the camera frustum. Pass `resolution` from the camera. Do not touch the playbar in GUI sessions (captures take `frame`). |

**`hocuspocus://guide`:** **51,982 B** in one read, because the whole tool reference is appended after 44 lines of instructions and recipes. That is three times the 16 KB response budget, for a resource the guide says to "attach to a conversation for context". The instructions are good but say nothing about several instances: nothing on auto-select of the most recent, pinning, job ids being per instance, or `events` seq per instance.

**`houdini://outline`:** 2.1 KB, the right first read. It showed `building_gen` with no `flags`, which means not displayed. That is exactly the fact `turntable_preview` needed and never asked for.

**Contradictions:**
- **`inspect_scene` vs the guide.** The prompt says `network_describe depth 2`, which gives data format. The guide says to start with `houdini://outline` and then describe one network.
- **`viewport_capture`'s `fit`.** The schema default is `"all"`. The behaviour and Notes say no framing without `fit`. The guide says "without fit or camera the GUI viewer is captured as it is".
- **The `job` hint vs reality with two instances.** "do not survive a Houdini restart" fits a crash, not "wrong instance".
- **The README says** "Several Houdinis can run at once: houdini_status lists them and houdini_connect {pid} picks one". It does not mention that without a pick the newest wins, or that a dead pick falls over silently.
- **`houdini_status` returns `instances[].selected`.** `tools.md` does not list it.

---

## 6. What worked well

`hocuspocus launch` in both modes; cheap switches (≤ 0.05 s); an explicit pin that survives new launches and the quit of another instance; a three-call hand-off (`hip_save`, connect, `hip_open`) with `$HIP` following the hip; no GUI lag during a long worker render; clear `disconnect`, unsaved-`quit` and final-status messages.

---

## 7. Top 10 papercuts

| # | Pri | Tool | Argument | Exact message / behaviour | Proposed change |
|---|---|---|---|---|---|
| 1 | **P0** | bridge selection (every tool) | after the pinned pid dies | `houdini_connect {pid:61900}` → worker killed → `job {action:status, job_id:"7b26f0d32646"}` → `job_not_found` "No job with id '7b26f0d32646'." from the **GUI**. `houdini_status` → `connected.pid: 3084`, no warning. `parm_set /out/gl_two/res [1920,1080]` meant for the worker changed the GUI scene. | Never fall over from a pinned instance. Every call returns `houdini_offline` with a new `code: instance_lost`: "Pinned Houdini pid 61900 (hython) exited; not switching. houdini_connect {pid} to choose: 3084 (houdinifx, GUI)". The pin clears only on an explicit `houdini_connect`. |
| 2 | **P0** | bridge selection | no pin, more than one instance | A fresh session picks the newest: "2 Houdini instances are running; using the most recent (pid 61900)…" appears only in `houdini_status`. `time {}` went to the worker with no warning. An unpinned selection moved to a newly launched worker (61996). | With more than one instance and no pin, mutating tools refuse with `ambiguous_instance` and labelled candidates. Read tools add `_meta.instance {pid,label,ui}` and the warning. Optionally prefer the `ui: true` instance. |
| 3 | **P1** | `job` | `job_id` from another instance | `job_not_found`: "No job with id '9c3e6f7ca53e'." Hint: "Jobs live in the Houdini process that started them and do not survive a Houdini restart". `job {action:list}` → `{"jobs":[]}` while the worker renders. | The bridge records `job_id → pid` when `render`/`cook`/`pdg` return a job and routes `job` (and `houdini://job/{id}`) to the owner. Add `pid` to job payloads. If the owner is dead: `code: instance_lost`, "job 7b26… ran on pid 61900, which exited at frame ~29/240". |
| 4 | **P1** | `houdini_status` / all results | `instances[]` | Rows differ only by `label`/`ui`/`started` once both hold the same hip. There is no busy state, no name, and no pid on ordinary results. | Add `jobs_running`, `busy` and `name` to instance rows. Add `houdini_connect {pid, name: "worker"}`, then `{name}` to select. Add `_meta.instance` to every result. Document `selected`. |
| 5 | **P1** | prompt `inspect_scene` | as written | "Then network_describe on /obj with depth 2" → `format: data`: 7,655 + 15,256 + 6,758 B over 3 pages (page 1 `truncated` after `building_gen`). | "Read houdini://outline (or network_describe {root, format: "outline"}), then problems on /obj. If houdini_status warns of several instances, ask which one or houdini_connect the GUI." About 8 KB in 3 calls. |
| 6 | **P1** | prompt `turntable_preview` | `path: /obj/building_gen` | It follows to the letter and returns two images of a city street. The target has its display flag off and is surrounded by `/obj/city_gen`. `time {range:[1,48]}` changed the user's playbar. The captures are 1024×768 for a 640×360 camera. | Add the steps: check `flags.display` (outline) and set it if off; warn about other displayed objects, or capture with an isolate option (`viewport_capture {only: [path]}`). Capture at the camera's `resolution`. Skip `time range` in GUI sessions, or restore it. |
| 7 | **P1** | `viewport_capture` / prompt `build_sop_chain` | no `fit` | Schema default `fit: "all"`, but `{}` → `"fit_used":"none"`, `"context":"/obj/city_gen"`, note "The viewer shows /obj/city_gen, not /obj". The built object is not framed. | Make the schema default match the behaviour (no default, or `none`). In the prompt, end with `viewport_capture {"fit": "all"}` or `{"source": "opengl_rop"}`. |
| 8 | **P1** | `events` | `since` across instances | `seq` restarts at 1 per host. `since: 2` on the worker after reading the GUI returned `{"events":[],"next_since":2}` with nothing to show it was a different stream. | Return `instance: {pid, started}` and make `next_since` an opaque `"<pid>:<started>:<seq>"`. On a mismatch, return `reset: true` with a note that the cursor is from another instance. |
| 9 | **P2** | `houdini_connect` | `pid: <dead>` | `{"code":"houdini_offline","message":"No live HocusPocus instance with pid 61900.","retryable":true,…,"candidates":["61996","3084"]}` | Set `retryable: false`. Use labelled candidates, for example `"3084 (houdinifx GUI, city_work.hip)"` or objects `{pid,label,ui,hip}`. |
| 10 | **P2** | resource `hocuspocus://guide` | read | 51,982 B: 44 lines of guide plus all of `tools.md`. No section on several instances. | Serve the instructions and recipes (about 6 KB). Leave the reference to `tools/list` or put it at `hocuspocus://guide/tools`. Add a "Two Houdinis" recipe: pin with `houdini_connect {pid}`, jobs and events per instance, re-pin after a crash. |

**Honourable mentions:** `debug_red_node`'s redundant `problems`/`cook`; `job result` listing every path beside `outputs_summary`; save-time `ParmTupleChanged` on the OpenGL ROP; `hda_locked: true` on a stock wrangle; transparent ROP PNGs; 0.8–1.1 KB echo on every `houdini_connect {pid}`.

---

## 8. Verdict

On the happy path, two instances work well: launch both, pin, hand off through `hip_save`/`hip_open`, render on the worker, keep editing the GUI. Everything around the pin is unsafe. The default is the newest instance, an unpinned selection moves to whatever launches next, and a dead pin falls over **silently** to the user's GUI. Jobs and events are per instance, but nothing in their payloads says so. Papercuts 1–4 are one design change: selection is explicit and sticky, and every result names its instance. Of the prompts, `build_sop_chain` is good, `debug_red_node` adequate, `inspect_scene` costs five times what it should, and `turntable_preview` gives a wrong picture on a real scene.
