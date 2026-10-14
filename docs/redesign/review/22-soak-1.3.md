> **Status: evaluation record.** HocusPocus 1.3.0, run from branch `release/1.4` at `32450ef` on 2026-10-13. See [`../README.md`](../README.md).

# 22 — Soak test of 1.3.0: 616 calls in one session against one headless host

**Seat:** a reliability engineer running plan-1.4 workload 22. I drove HocusPocus only through the official `mcp` SDK client over stdio, using the same pattern as `tests/e2e/test_stdio_roundtrip.py`. I read the host and bridge source only after the run, to explain two findings (sections 5.1 and 5.2).
**Build:** branch `release/1.4` at `32450ef`. The code is 1.3.0 (`hocuspocus 1.3.0 (hp/v1, mcp 2.3.0, Python 3.13.14)`). I installed it editable into a fresh scratch venv (`uv venv`, `uv pip install -e <checkout> matplotlib psutil`).
**Host:** Houdini 22.0.466 hython, headless, pid **60396**. I started it with `hocuspocus launch --headless --work-dir <scratch>/soak`. The environment was isolated:
- `HOCUSPOCUS_STATE_DIR=<scratch>/state`
- `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, with `profile = "full"` in `<scratch>/prefs/houdini22.0/hocuspocus.toml`
- `HOCUSPOCUS_PROFILE=full`

`houdini_status` reported `"profile": "full"`. I made no writes to the real pref dirs, used no port 37219, and stopped only the processes I started.

**Client:** one persistent `mcp.Client` session for the whole run. It handled 566 calls, and the bridge stayed up from the first call to the last. Separately, **50 one-shot clients** each started a fresh `hocuspocus-mcp` and made one call. Every call went to `soak.jsonl` with these fields: tool, args bytes, result bytes, image count, isError, deliberate, elapsed_ms, and spawn_ms for one-shot calls. Every 50 calls the script also took a sample: `houdini_status.connected.memory`, the bridge's RSS, the sizes of the instances, logs and captures dirs, the host log size, and the `/obj` node count from `node_find`.

**Script:** `soak.py`, deterministic for a given `--seed`. I used `--seed 22 --calls 600`. It stays in the scratch dir and is not committed.

**Runs:**
- A **pilot** (614 calls, host pid 54448) found two scheduling bugs in my script: a sample could swallow the `hip_save` slot, and the cancel job never fired.
- The **official run** came after I fixed those bugs. It used a fresh host and a fresh state dir: 616 calls, 2026-10-13 21:52:54 to 21:54:31 local time.
- Two **side experiments** followed on separate throwaway hosts: one isolated the latency drift, and one overflowed the events ring (section 3.7).

The pilot is reported where it adds evidence.

**Headline:**
- **0 unexpected errors in 1,230 soak calls** (pilot and official run).
- **0 calls over 10 s.**
- **0 `houdini_busy` or `delivery_unknown`.**
- **0 leaked nodes, jobs or temp files.** The host was healthy at the end and `houdini_connect {quit: true}` closed it cleanly.
- Read latency did not drift: p50 2.3 → 2.2 ms, p95 16.8 → 21.7 ms from the first 100 calls to the last 100.
- **Mutation latency did drift.** `node_create` p50 went from **42 → 218 ms** after a state change inside Houdini. This is a mountain-HDA cook inside the call, which the tool surface cannot attribute (finding 2).
- **One correctness bug:** a budget-truncated `events` page returns a `next_since` past the events it dropped, so a client that follows the cursor silently skips them (finding 1, P0).

Evidence: `docs/redesign/evidence/city-destruction/90_soak_latency.png` (900×620, 66 KB) plots latency per call and host RSS against the call index.

---

## 1. The script's mix

The loop runs scheduled actions first, then one action from a weighted mix:
- **Sample:** every 50 calls (`houdini_status` and `node_find /obj`, plus file sizes).
- **Save:** `hip_save` to `<scratch>/soak/soak_NNN.hip` every 100 calls.
- **Capture:** `viewport_capture` at 640×480 every 40 calls (the headless OpenGL child).
- **Canary:** a forced `cook` of `/obj/soak_canary/mtn` every 25 calls.
- **Reopen:** one `hip_open` of the first save (`soak_102.hip`) at call 361.
- **Frame-range jobs:** forced at calls 150, 300 and 450. The job at 300 runs on a deliberately heavy object (a 300×300 grid, then 50,000 scattered points, then copies: 13.3 M points) and is cancelled right away.

An `undo` is always followed by a `redo`, so the script's model of the scene stays exact. Every 9th mix slot goes through a one-shot client, using read-only tools only.

**Scene shape.** Each new object is a geo with `box`, `sphere` or `grid`, then `xform` (`ry` = `$F*3`), then `mountain`. Half the objects also get `scatter`, a small `sphere` and `copytopoints`. Objects are deleted, oldest first, whenever the model passes 50 nodes or 8 objects. `node_find /obj` counted **33–53 nodes** at every sample. That is under the ~60 target; the canary adds 3 nodes to the script's own model count.

| Tool | Calls | Mix | One-shot | Scheduled / sample / canary / final | Deliberate invalid |
|---|---:|---:|---:|---:|---:|
| `node_find` (with cursors) | 89 | 63 | 8 | 18 | 0 |
| `cook` (sync, profile, force) | 54 | 30 | 0 | 23 canary | 1 |
| `parm_set` (values, `$F` and `sin()` expressions, keyframes, `animation: key`) | 40 | 36 | 0 | 0 | 4 |
| `node_info` | 40 | 26 | 12 | 0 | 2 |
| `parm_get` (keys, frame) | 38 | 30 | 8 | 0 | 0 |
| `node_create` (batches of 4–7) | 37 | 36 | 0 | 1 setup | 0 |
| `time` | 35 | 21 | 14 | 0 | 0 |
| `node_edit` (renames, bypass and template flags, comment, color) | 34 | 33 | 0 | 0 | 1 |
| `job` (status, result, cancel, list) | 29 | 26 | 0 | 2 | 1 |
| `node_delete` | 27 | 27 | 0 | 0 | 0 |
| `houdini_status` | 23 | 0 | 8 | 15 | 0 |
| `node_connect` | 20 | 20 | 0 | 0 | 0 |
| `events` (cursor chain) | 19 | 17 | 0 | 1 | 1 |
| `undo` (undo, redo, history) | 18 | 16 | 0 | 1 | 1 |
| `node_copy` | 17 | 17 | 0 | 0 | 0 |
| `network_describe` (data and outline) | 16 | 16 | 0 | 0 | 0 |
| `geo_info` | 16 | 14 | 0 | 0 | 2 |
| `viewport_capture` | 14 | 0 | 0 | 14 | 0 |
| `houdini_python` (read-only snippets) | 11 | 10 | 0 | 1 | 0 |
| `node_type_info` | 11 | 9 | 0 | 0 | 2 |
| `geo_read` | 10 | 10 | 0 | 0 | 0 |
| `hip_save` | 5 | 0 | 0 | 5 | 0 |
| `node_type_search` | 5 | 5 | 0 | 0 | 0 |
| `problems` | 4 | 3 | 0 | 1 | 0 |
| `hip_open` | 2 | 0 | 0 | 1 | 1 |
| `hip_new`, `houdini_connect` | 1 + 1 | 0 | 0 | 2 | 0 |
| **Total** | **616** | 465 | **50** | 85 + 16 | **17** (2.8 %) |

The deliberate-invalid share came out at 2.8 %, below the 5 % I aimed for. The script draws each invalid call with p = 0.05 inside the mix, and the scheduled calls dilute that rate. Fifteen invalid shapes were available, and 11 of them were drawn (section 4).

---

## 2. Totals

| | Official run | Pilot |
|---|---:|---:|
| Calls (persistent + one-shot) | **616** (566 + 50) | 614 (572 + 42) |
| Wall clock | 96.1 s | 81.9 s |
| Seconds inside tool calls | 63.2 s (43.6 s of it in `viewport_capture`) | 53.2 s |
| Args bytes / result bytes | 57,832 / 875,669 (14 images) | — |
| Errors | 17, **all deliberate** (16 probes + the cancelled job's `result`) | 18, all deliberate |
| Unexpected errors | **0** | **0** |
| Calls over 10 s | **0** (max 6,707 ms, `viewport_capture` with the 13 M-point object in the scene) | 0 (max 3,445 ms) |
| Calls over 1 s, captures excluded | **0** | 0 |
| `houdini_busy` / `delivery_unknown` / transport exceptions | **0 / 0 / 0** | 0 / 0 / 0 |
| Host RSS, start → end (peak) | 420 → 667 MB (2,002 MB) | 419 → 637 MB (640 MB) |
| Bridge RSS, start → end | 70.2 → 71.4 MB | 69.9 → 72.8 MB |

---

## 3. Measurements

### 3.1 Latency per tool (persistent session, 566 calls)

"First 100" and "last 100" are the first and last 100 persistent calls of the run: calls 1–109 and 497–603, before the final checks. Times are milliseconds from `call_tool` to its return, so they include the bridge's stdio hop and the HTTP hop to the host.

| Tool | Calls | Err (delib.) | Args B avg | Result B avg | p50 | p95 | Max | First 100: n / p50 / p95 | Last 100: n / p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `cook` | 54 | 1 (1) | 48 | 239 | 3.1 | 200.4 | 399.6 | 10 / 3.5 / 16.6 | 5 / 2.7 / 156.3 |
| `events` | 19 | 1 (1) | 33 | 3,274 | 2.3 | 16.8 | 20.5 | 3 / 1.9 / 1.9 | 4 / 2.2 / 2.9 |
| `geo_info` | 16 | 2 (2) | 28 | 432 | 2.9 | 12.2 | 36.0 | 4 / 3.3 / 31.1 | 2 / 2.5 / 2.7 |
| `geo_read` | 10 | 0 | 76 | 963 | 3.7 | 148.3 | 189.2 | 1 / 189.2 / 189.2 | 0 |
| `hip_open` | 2 | 1 (1) | 180 | 317 | 39.6 | 71.9 | 75.5 | 0 | 0 |
| `hip_save` | 5 | 0 | 153 | 239 | 17.4 | 18.5 | 18.6 | 1 / 18.6 | 1 / 17.4 |
| `houdini_connect` (quit) | 1 | 0 | 39 | 39 | 630.2 | — | 630.2 | — | — |
| `houdini_python` | 11 | 0 | 97 | 89 | 2.3 | 11.6 | 16.5 | 5 / 2.3 / 3.4 | 1 / 2.0 |
| `houdini_status` | 15 | 0 | 2 | 1,511 | 4.4 | 35.3 | 39.5 | 3 / 3.6 / 16.7 | 3 / 25.3 / 32.7 |
| `job` | 29 | 2 (2) | 50 | 956 | 2.0 | 10.5 | 16.3 | 1 / 2.0 | 0 |
| `network_describe` | 16 | 0 | 29 | 2,047 | 13.8 | 32.7 | 51.6 | 3 / 20.0 / 48.4 | 2 / 12.4 / 16.7 |
| `node_connect` | 20 | 0 | 117 | 510 | 4.2 | 34.1 | 34.9 | 4 / 2.6 / 4.8 | 2 / 3.3 / 4.2 |
| `node_copy` | 17 | 0 | 101 | 170 | 11.4 | 58.6 | 168.3 | 2 / 13.9 / 15.6 | 2 / 11.2 / 13.0 |
| **`node_create`** | 37 | 0 | 752 | 834 | 50.3 | 248.9 | 468.2 | 10 / **41.7** / 187.3 | 9 / **217.8** / 230.6 |
| `node_delete` | 27 | 0 | 43 | 56 | 9.0 | 27.4 | 30.7 | 2 / 7.5 / 8.4 | 5 / 17.1 / 28.2 |
| **`node_edit`** | 34 | 1 (1) | 72 | 331 | 21.9 | 205.0 | 209.4 | 8 / 2.5 / 137.4 | 8 / **112.5** / 208.8 |
| `node_find` | 81 | 0 | 49 | 624 | 2.3 | 4.0 | 22.3 | 15 / 2.4 / 3.1 | 21 / 2.2 / 2.3 |
| `node_info` | 28 | 2 (2) | 53 | 443 | 2.4 | 13.0 | 20.6 | 2 / 2.1 / 2.4 | 10 / 2.3 / 3.2 |
| `node_type_info` | 11 | 2 (2) | 39 | 782 | 5.6 | 29.4 | 31.9 | 0 | 2 / 4.3 / 4.6 |
| `node_type_search` | 5 | 0 | 52 | 2,280 | 10.2 | 308.8 | 380.2 | 0 | 2 / 8.3 / 10.0 |
| `parm_get` | 30 | 0 | 53 | 302 | 2.0 | 20.4 | 25.0 | 9 / 2.1 / 16.5 | 4 / 1.9 / 20.1 |
| `parm_set` | 40 | 4 (4) | 94 | 253 | 3.0 | 32.7 | 40.7 | 4 / 19.4 / 23.5 | 7 / 2.6 / 30.3 |
| `problems` | 4 | 0 | 28 | 200 | 4.2 | 4.4 | 4.4 | 1 / 3.4 | 0 |
| `time` | 21 | 0 | 8 | 62 | 1.9 | 15.5 | 16.3 | 2 / 7.2 / 11.3 | 3 / 2.1 / 2.5 |
| `undo` | 18 | 1 (1) | 19 | 329 | 2.0 | 6.6 | 14.4 | 7 / 2.0 / 2.5 | 5 / 2.0 / 4.9 |
| `viewport_capture` | 14 | 0 | 26 | 35,768 | 2,985 | 6,567 | 6,707 | 2 / 3,159 / 3,273 | 2 / 2,969 / 2,978 |

### 3.2 Drift: first 100 against last 100 calls

| Slice | First 100: p50 / p95 / max | Last 100: p50 / p95 / max | Pilot, first → last p50 / p95 |
|---|---|---|---|
| All calls | 2.8 / 58.5 / 3,273 | 2.7 / **219.9** / 2,978 | 2.9 / 50.4 → 2.6 / 213.3 |
| Without `viewport_capture` | 2.8 / 46.3 | 2.7 / **216.6** | 2.8 / 40.5 → 2.6 / 200.3 |
| Without capture, `node_create` and `node_edit` | 2.5 / 23.9 / 189 | 2.3 / 25.3 / 194 | 2.7 / 26.6 → 2.5 / 22.5 |
| Reads only (`node_find`, `node_info`, `parm_get`, `geo_info`, `time`, `houdini_status`, `events`, `undo`) | 2.3 / 16.8 / 36 | 2.2 / 21.7 / 34 | 2.2 / 16.9 → 2.3 / 17.5 |
| Canary `cook` (forced, same 2-node chain, 23 samples) | 2–13 ms | 2–6 ms (27 ms once, just after `hip_open`) | — |

**HocusPocus's own overhead does not drift.** p50 for reads stayed at about 2 ms for all 616 calls. A separate run of **2,400 back-to-back `parm_set` calls** on one session gave p50 2.1 ms, p95 2.4 ms and max 27.6 ms (section 3.7). The p95 rise in the whole-mix numbers comes entirely from `node_create` and `node_edit`, which moved from **~40 ms to ~215 ms** for a mountain chain (finding 2). In the official run the jump came right after `hip_open` (call 361): creates before it were 33–62 ms, and every create after it was 198–236 ms. In the pilot, which had no `hip_open`, the jump came at call 109, right after a frame-range cook job.

On a third, fresh host, every mountain-chain create took **180–240 ms** from the first call: after `hip_save`, after `hip_open`, after `hip_new`, at frame 1 or frame 7, with or without parms. So the ~40 ms phase is the unusual state, not the ~215 ms one.

Raw `hou` inside that host (one `houdini_python` call) reproduces the cost: `createNode('mountain')` takes 1.4 ms, its **first `cook(force=True)` takes 296.6 ms**, and later cooks take 35 ms. The time is a Houdini-side first cook of `mountain::2.0` (an HDA over attribnoise) that `node_create` runs inside the call. HocusPocus overhead is not the cause. The surface does not show this split (finding 2).

### 3.3 One-shot clients against the persistent session (50 one-shot calls)

| Tool | One-shot calls | Call p50 / p95 (ms) | Client spawn and initialize p50 / p95 (ms) | Total p50 (ms) | Persistent p50 / p95 (ms) |
|---|---:|---|---|---:|---|
| `houdini_status` | 8 | 19.1 / 25.1 | 583 / 649 | 678 | 2.2 / 3.2 (calls outside the samples) |
| `node_find` | 8 | 26.7 / 31.8 | 582 / 591 | 675 | 2.3 / 5.0 |
| `node_info` | 12 | 18.7 / 33.9 | 581 / 592 | 660 | 2.4 / 13.0 |
| `parm_get` | 8 | 10.1 / 33.4 | 586 / 634 | 662 | 2.0 / 20.4 |
| `time` | 14 | 15.9 / 38.6 | 581 / 630 | 678 | 1.9 / 15.5 |

A one-shot call costs about **670 ms end to end**: ~580 ms to spawn and initialize `hocuspocus-mcp`, then a first call about 8× slower than in a warm session. Results were otherwise the same. All 50 one-shot calls succeeded, they returned the same pid, and the persistent session never noticed them. Bridge-side state survived 566 calls with no growth that matters (RSS 70.2 → 71.4 MB).

### 3.4 Host memory and file growth (samples every 50 calls)

| Call | Host RSS MB (peak) | `/obj` nodes (`node_find` total) | Instances dir | Captures (files) | `host-60396.log` | Launch log | Files in state dir |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 419.6 (420.2) | 0 | 387 B | 0 (0) | 137 B | 212 B | 3 |
| 51 | 492.3 (544.1) | 49 | 387 B | 24,863 (1) | 137 B | 212 B | 4 |
| 101 | 505.7 (577.3) | 53 | 387 B | 41,650 (2) | 137 B | 212 B | 5 |
| 152 | 513.8 (590.7) | 43 | 387 B | 63,733 (3) | 137 B | 212 B | 6 |
| 201 | 513.2 (590.7) | 44 | 387 B | 83,172 (4) | 137 B | 212 B | 7 |
| 251 | 622.6 (622.7) | 44 | 387 B | 136,218 (6) | 137 B | **16,948 B** | 9 |
| 301 | 540.7 (623.2) | 33 | 387 B | 157,889 (7) | 137 B | 16,948 B | 10 |
| 351 | **1,927.4** (1,946.2) | 36 | 387 B | 216,570 (8) | 137 B | 16,948 B | 11 |
| 402 | 574.2 (2,002.2) | 39 | 387 B | 277,794 (9) | 137 B | 16,948 B | 12 |
| 451 | 661.4 | 50 | 387 B | 320,293 (11) | 137 B | 16,948 B | 14 |
| 501 | 660.3 | 43 | 387 B | 341,691 (12) | 137 B | 16,948 B | 15 |
| 551 | 594.7 | 44 | 387 B | 362,300 (13) | 137 B | 16,948 B | 16 |
| 603 | 667.2 (2,002.2) | 37 | 387 B | 382,424 (14) | 137 B | 16,948 B | 17 |

- **Memory:** 420 MB at start, a 490–660 MB plateau with the scene held at 33–53 nodes, and 667 MB at the end. The one spike (1.93 GB at call 351, peak 2.0 GB) is the 13.3 M-point object built for the cancel test. RSS was back to 574 MB by the next sample, after `hip_open` replaced the scene. Excluding that object, the trend is about +250 MB over 600 calls. Most of it arrived in the first 250 calls (Houdini loading SOP and COP libraries, plus the cook caches). From call 402 to call 603 RSS moved only within 574–667 MB, with no monotonic climb. The pilot told the same story: 419 → 637 MB, flat at 563–637 MB after call 100.
- **Instances dir:** 1 file, 387 B, unchanged all run. It was removed on quit.
- **Host log:** **137 B for the whole run.** It has one start line, and on quit three more lines (quit requested, shutdown, stopped). No per-call line is ever written (finding 4).
- **Launch log:** grew once, by 16.7 KB of `oplib:/Cop/...` handle-binding warnings (`error binding handle sidefx_transform2d because it doesn't exist.`). These 144 lines were written between calls 201 and 251, when the first `node_type_search` loaded the COP libraries. It did not grow again.
- **Captures:** 14 PNGs, 382 KB, about 27 KB each (75–78 KB with the heavy object in view). `prune_captures` keeps 50, so this growth is bounded at roughly 1.5–4 MB.
- **State dir:** start = `instances/60396.json`, `logs/host-60396.log`, `logs/launch-headless-*.log`; end = the same 3 files plus 14 captures. **There were no stray temp files.** I did not inspect `%TEMP%`; it is outside my scratch dir.

### 3.5 Leaks

| Check (end of run, before quit) | Result |
|---|---|
| `node_find pattern: *hocus*` in `/obj`, `/out`, `/stage`, `/img`, `/` | **0** at every root |
| `houdini_python`: node names containing `hocus` anywhere, or nodes with `hocuspocus*` userData | **0 / 0** |
| `/out`, `/stage`, `/img` children (14 captures and 5 frame-range cooks ran) | **empty / empty / empty** |
| `/obj` top level | `soak_canary` plus the 7 objects the script's model expected, no strays. `node_find` total 37 = the model's 34 + 3 canary nodes. `allSubChildren` = 517, because `node_find` does not enter locked HDAs, as documented |
| `job list all` | 5 jobs, **0 running**: 4 `done` frame-range cooks and 1 `cancelled` |
| `problems /` | 0 problems, 46 nodes scanned |
| Leaked temp files in the state dir | **0**; captures only, pruned at 50 |
| Undo history | `hou.undos.undoLabels()` = **67** after the 255 calls since `hip_open` (the pilot, without a reopen: **199** after 600 calls), 0 redo. `undo history` lists only the newest 20 and gives no total (finding 9) |

### 3.6 Jobs

- Four frame-range `cook` jobs with `wait_s: 0` were polled with `job status` and then `job result`. They took 3–7 polls, ran for 0.05–0.10 s each, and were all `done` with `result.ok: true`.
- The cancel test ran on the 240-frame, 13.3 M-point chain. `job cancel` came 3 ms after the start (`elapsed_s: 0.003`) and returned `"state":"running","message":"cancellation requested","cancelled":true`. The next `job result` returned `cancelled`: `Job 60396-94222b07f2eb was cancelled after 1 of 240 frames.`, with `detail.partial.frames[0]` = 13,300,000 points. The cancel took effect in the frame loop, at the next frame boundary.
- `jobs_running` in `houdini_status` was 0 at every sample. No call ever saw `busy: true`, even while a job ran between the mix calls.

### 3.7 Events

- **Cursor chain:** 17 `events` calls followed `next_since` from `0` to `60396:307`. The seq numbers were **strictly increasing**, every page started at previous last + 1 (**no gaps**), and `dropped` was 0. `hip_open` (call 361) caused **no `reset`**: the seq numbers continued (162 → 195 on the next page). In total, 310 events were recorded in 616 calls. The noise is low because events cover only watched nodes.
- **Truncated pages skip events (P0, finding 1).** `events {since: 0, limit: 1000}` at the end returned **113 events (seq 1–113)**, `"truncated": true` and **`"next_since": "60396:310"`**. With `limit: 200` the page held 1–114 with `next_since` `…:200` and `more: true`. A client that passes `next_since` back never sees seq 114/115 to 310: in the pilot that was **331 events**, and here **197**. My follow-the-cursor check on the pilot host stopped with 114 of 445 events.
- **Ring overflow behaves correctly.** On a throwaway host I made 2,440 events (40 `null`s, then 2,400 `parm_set` calls in 5.9 s). Reading from a cursor taken before the burst returned `"dropped": 400, "more": true` and seq 441 onward. Reading from `0` returned `dropped: 440`. `dropped` counts exactly what the 2,000-event ring evicted, and the 2,400 `parm_set` calls themselves did not drift (p50 2.1 ms).

### 3.8 Health at the end

- `houdini_status` returned `connected.pid 60396`, `busy: false`, `jobs_running: 0`, `scene_generation: 2` and memory 667 MB, in 3.3 ms.
- `houdini_connect {quit: true, on_unsaved: "discard"}` returned `{"quit":true,"pid":60396,"exited":true}` in 630 ms. The host log shows quit, then shutdown, then `host stopped` within 0.4 s.
- `houdini_status` afterwards returned `connected: null, instances: []`. `tasklist` showed no process 60396. The registry entry was removed (`removed stale registry entry for pid 60396`).
- One observation: `psutil.pid_exists(60396)`, called 1 ms after the quit returned, was still `True`. A Windows process can linger briefly after `exited: true` is reported. Nothing was left by the next check.

---

## 4. Errors

**Unexpected errors: none in either run, 0 of 1,230 calls.** Every error below was one I provoked. Messages are as received. The verdict column says whether the error is actionable without another lookup.

| # | Tool and arguments | Code: message | Hint | Verdict |
|---|---|---|---|---|
| 135, 255 | `geo_info {path: /obj/soak_missing}` | `node_not_found`: `No node at /obj/soak_missing.` | `Check the node name.` | **Weak** (finding 8): `cook` on a path under the same missing parent says `The parent /obj/soak_missing does not exist either.` |
| 172 | `job {action: status, job_id: "999-deadbeef"}` | `instance_lost`: `Job 999-deadbeef ran in Houdini pid 999 (houdini), which has exited; its jobs are gone.` | `start the work again on a live Houdini …` | **Wrong** (finding 7): pid 999 never existed and the job never ran. The answer invents a history. |
| 197, 412, 449 | `parm_set …/xf/tx value "not a number"` | `invalid_value`: `items[0] (/obj/soak_g022/xf/tx): it is a float parm; got 'not a number'.` | `For an expression use the expression field …` | Yes |
| 253, 258 | `node_type_info {type: Sop/definitely_not_a_type}` | `node_type_not_found`: `No Sop node type named 'definitely_not_a_type'.` | `Use node_type_search …` | Yes |
| 267 | `node_edit` rename to `bad name/with slash` | `invalid_argument`: `… 'bad name/with slash' is not a valid node name.` | `… e.g. 'bad_name_with_slash'.` | Yes |
| 271 | `undo {action: sideways}` | `invalid_argument`: `1 argument problem(s) for undo: action: "sideways" is not one of ["undo", "redo", "history"]` | schema pointer | Yes |
| 281 | `hip_open` of a missing file in the soak dir | `file_not_found`: `No file at …/soak/no_such_file.hip.` | `No similar hip files in …/soak.` | Yes, although 5 `soak_*.hip` files were there (the similarity check found none close enough, which is reasonable) |
| 309 | `job result` of the cancelled job | `cancelled`: `Job 60396-94222b07f2eb was cancelled after 1 of 240 frames.` | — | Yes. It carries `detail.partial` |
| 332 | `parm_set …/xf/not_a_parm` | `parm_not_found`: `No parm or parm tuple 'not_a_parm' on /obj/soak_g030/xf.` | `List the node's parm names with node_info (include_defaults: true).` | Yes |
| 410 | `cook {paths: [/obj/soak_missing/out]}` | `node_not_found`: `No node at /obj/soak_missing/out.` | `The parent /obj/soak_missing does not exist either.` | Yes |
| 477, 511 | `node_info /obj/soak_g910/does_not_exist` | `node_not_found`: `No node at /obj/soak_g910/does_not_exist.` | `/obj/soak_g910 has no similar child.` | Yes |
| 579 | `events {since: "abc:xyz"}` | `invalid_argument`: `since must be the next_since of an earlier events call ('<pid>:<seq>') or a seq number, not 'abc:xyz'.` | `pass next_since back as since …` | Yes |

The pilot also covered `geo_read class: pointz` (schema error), a raising `houdini_python`, which was rolled back with `python_exception: ValueError: soak deliberate`, and `node_connect … to_input 7`. The last gave `invalid_input`: `it has no input 7 (it takes 1).`, with hint `Inputs of …/mtn: 0: input1 (Sub-Network Input #1).`. All of these are actionable.

---

## 5. Top 10 findings

### P0

**1. A budget-truncated `events` page returns a `next_since` past what it dropped, and the cursor contract loses events silently.**
- **Evidence:** `events {since: 0, limit: 1000}` returned 113 events (seq 1–113, 16.3 KB) with `{"next_since":"60396:310","dropped":0,"truncated":true}`. With `limit: 200`: seq 1–114 and `next_since …:200`. Following `next_since` skips seq 114 to 310. `dropped` stays 0, so nothing tells the client.
- **Cause:** `bridge/budget.py` cuts the largest list of a non-paged result at its byte budget. `events` pages by `since`/`next_since`, not `cursor`, so it takes the generic path: the list is cut and the host's `next_since` (the last seq *scanned*) passes through unchanged.
- **Proposed change:** treat `events` as paged in the bridge. When the list is cut, rewrite `next_since` to `<pid>:<seq of the last kept event>` and set `more: true`, the way integer cursors are already rewritten. Better still, have the host page by `max_response_bytes` itself, as `node_find` and `problems` do. Add a unit test: 300 events, 16 KB budget, follow `next_since`, and assert that every seq arrives exactly once.

### P1

**2. Mutation latency drifts 5× (≈40 → ≈215 ms per mountain-chain `node_create`), and the surface cannot say why.**
- **Evidence:** in the official run the switch came right after `hip_open`; in the pilot, after a frame-range job; on a fresh host it applied from the first call.
- **Cause:** the cost is Houdini's first cook of `mountain::2.0` / attribnoise. `node_create` cooks what it creates so it can report `cook_state` and problems. Raw `hou`: create 1.4 ms, first forced cook 296.6 ms, then 35 ms.
- **Impact:** a model or an operator sees only "node_create got slow".
- **Proposed change:** add `cook_ms` to each `node_create`/`node_copy`/`node_edit` result row (it is already measured for `cook`). Add a `_meta.timing: {queue_ms, main_thread_ms, cook_ms}` block to every host call, so drift can be split between the bridge, the queue and Houdini. Add `cook: false` to `node_create` for batch builders that will cook once at the end. Make plan-1.4 workload 22 (this soak) a CI-able script whose drift check uses `main_thread_ms − cook_ms`.

**3. A `node_edit` rename recooks the node: ~200 ms, against 2–3 ms for flag, comment or color edits.**
- **Evidence:** the first rename of a mountain node (`mtn` to `mtn_tmp`) took 191–239 ms every time: 7 times in the soak and 5 in the side experiments. The rename back usually took 21–32 ms (once 209 ms), and flag, comment or color edits took 2–4 ms.
- **Cause:** the rename returns a full row with `cook_state` and `cook_time_ms`, and building it cooks the renamed HDA.
- **Proposed change:** report `cook_state` from `node.needsToCook()` and `node.errors()` without cooking in `node_edit`, the same as `node_info`. Only `cook` and creates should cook.

**4. The host log records nothing per call, so a soak or an incident cannot be reconstructed host-side.**
- **Evidence:** `host-60396.log` was 137 B for 616 calls: one start line, and three lines on quit.
- **Impact:** the absence of `houdini_busy` and of slow calls rests only on my client log.
- **Proposed change:** one INFO line per call: `tool`, `ms` (queue/main/cook as in finding 2), `ok` or error `code`, result bytes, `job_id`. Keep the existing `RotatingFileHandler`. At ~150 B per call, this run would have written ~90 KB, well inside `LOG_MAX_BYTES` with rotation. Add `log_level` to `houdini_status` so a caller can see it.

### P2

**5. One-shot clients cost ~670 ms per call against 2 ms in a session.**
- **Evidence:** 50 one-shot calls had p50 spawn and initialize 581–586 ms, and the first call in a fresh bridge took 10–27 ms against 2 ms warm.
- **Proposed change:** say in `docs/tools.md` and the README client section that clients should keep one session. Profile bridge startup (I did not profile it here); deferring catalog and validator construction until the first `tools/list` is the first thing to try. Track the spawn time in the e2e tier.

**6. `viewport_capture` is 69 % of tool time: 43.6 s of 63.2 s, for 14 calls.**
- **Evidence:** each headless capture starts a fresh OpenGL render child, taking 2.9–3.7 s, or 6.5–6.7 s with a 13 M-point object in view.
- **Proposed change:** keep the render child warm between captures (one child per host, with a short idle timeout), or reuse the frame when `scene_generation` and the camera have not changed. Return `elapsed_ms` and `child_start_ms` in the result. This also belongs in the Flipbook-ROP migration in plan-1.4 phase 2.

**7. `job status` with an unknown id invents a history.**
- **Evidence:** `999-deadbeef` returned `instance_lost`: `Job 999-deadbeef ran in Houdini pid 999 (houdini), which has exited; its jobs are gone.` No Houdini 999 ever existed and no such job ran.
- **Proposed change:** when the pid is not one the bridge has seen (registry, launch log or job table), return `job_not_found` with `No job 999-deadbeef: pid 999 is not a Houdini this server knows; job list shows the live jobs.`. Keep `instance_lost` for pids the bridge did see exit.

**8. `geo_info` on a path whose parent is missing has a weaker hint than `cook` and `node_info`.**
- **Evidence:** `geo_info` says `Check the node name.`, where `cook` says `The parent /obj/soak_missing does not exist either.` and `node_info` says `/obj/soak_g910 has no similar child.`
- **Proposed change:** route `geo_info` and `geo_read` path resolution through the same node resolver and hint builder as `node_info` and `cook`.

**9. Undo history grows without a total.**
- **Evidence:** in the pilot, `hou.undos.undoLabels()` = 199 after 600 calls. `undo history` shows only the newest 20 and gives neither `undo_count` (which only `undo`/`redo` return) nor Houdini's undo limit, so a long session cannot see how deep its history is.
- **Proposed change:** add `undo_count`, `redo_count` and `limit` (from Houdini's undo preferences, where `hou` exposes them) to `undo {action: history}`. Document that `hip_open` and `hip_new` clear the history: the official run had 67 after the reopen.

**10. Repeated, unchanged notes inflate every mountain create.**
- **Evidence:** every `node_create` with a mountain carries `"deprecated":true` and the same ~150 B note (`Sop/mountain::2.0 is deprecated since Houdini 19.0. Its replacement is Sop/attribnoise::2.0. …`). That was 37 times in this run, about 5.5 KB of identical text.
- **Proposed change:** send the note once per session per type, then send only `deprecated: true` with `notes_same_as: "<type>"`, as `errors_same_as` already does. Relatedly, the launch log takes 144 lines of COP `error binding handle sidefx_*` warnings the first time COP libraries load headless. Filter those handle warnings in the headless host, or note them in `doctor`.

---

## 6. Verdict

**1.3.0 is stable under sustained use.** This soak ran 616 calls on one session, plus a 614-call pilot and a 2,400-call `parm_set` burst on separate hosts. Results:
- **No unexpected error.**
- **No call over 10 s, and none over 1 s outside captures.**
- **No `houdini_busy`.**
- **No leaked node, job, registry entry or temp file.**
- **No growth in the bridge.**
- **Bounded growth in captures (pruned at 50) and the launch log (once).**

Host memory settled at about 600 ± 60 MB with the scene bounded. It fully released a 1.3 GB transient. The cancel stopped a 240-frame job after one frame. `hip_open` mid-session kept the events cursor and the jobs table consistent. The host quit cleanly on request.

**Two things need attention before 1.4:**
- The `events` truncation bug (finding 1). It silently breaks the one tool whose contract is "you will see every change".
- The opaque mutation timings (findings 2–4). The 5× `node_create` drift is Houdini's cook, not HocusPocus. The proof here needed `houdini_python` and a side experiment, because neither the result nor the host log separates bridge, queue and cook time.

Findings 5–10 are cost and polish.

Evidence: `docs/redesign/evidence/city-destruction/90_soak_latency.png`. Top: latency per call (log scale) for captures, creates and edits, and everything else, with the `hip_open` marker and the 10 s line. Bottom: host RSS per sample.
