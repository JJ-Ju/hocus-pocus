# 11 — Agent ergonomics review after the first real workloads

**Seat:** senior reviewer of the agent-facing surface. This is a read-only review. I read `docs/BIBLE.md` (§1, §3.6, §4, §9, §15), `docs/tools.md`, `src/hocuspocus/bridge/instructions.py`, reviews 07, 08 and 09, and `src/hocuspocus/tools/catalog.py`. I checked a few implementation details in `host/tools/{visual,types,cook,_diag,nodes}.py` and `bridge/{launch,local_tools,server}.py` so I could name the exact change.
**Build:** `master` @ `8b92569` (1.0, merged from `redesign/v1`).
**Date:** 2026-10-12.

Each backlog item has five parts: **Evidence** (quoted from the logs), **Change** (exact wording or result shape), **Benefit**, **Cost** (S < 2 h, M ≤ 1 day, L > 1 day), and **Track**. The track is *1.0.x* when the change is additive: a new optional argument, a new result field, `notes`/`hint` text, description wording, or a fix that makes behaviour match the documented contract. It is *1.1* when the change alters a default, renames or removes a field, or needs a BIBLE §4 table amendment.

---

## 1. Measurements

### 1.1 `tools/list` size (core profile, 31 tools)

I measured the catalogue with the project venv: `tools_list_text_size`, plus a real `ListToolsResult` serialised from `Bridge().list_tools()`.

| Part | Bytes |
|---|---:|
| Names + descriptions + compact input schemas (the CI metric, cap 48,000) | 23,738 |
| of which descriptions | 9,199 |
| of which input schemas | 14,238 |
| Output schemas (**not counted by CI**) | 9,734 |
| Annotations (not counted) | 2,799 |
| **Serialised `tools/list` result on the wire** | **38,460 (≈ 9.6k tokens)** |
| `full` profile, CI metric (35 tools) | 26,685 |
| Server `instructions` | 196 words, 1,294 B |

Largest tools: `parm_set` 2.9 KB, `node_create` 2.2 KB, `node_info` 1.8 KB, `parm_get` 1.8 KB, `houdini_status` 1.6 KB.

**Finding:** the CI metric reads as half the 48 KB cap, but models receive 38.5 KB, about 4 KB more than review 07 measured (34,557 B). The gate measures the wrong thing. **Recommendation (1.0.x, S):** make `test_tools_list_budget` serialise the real `ListToolsResult` and cap it at 40,000 B.

### 1.2 Per-call cost of the common results

Sources are the per-tool averages in 08 §2 and 09 §2 (pretty-printed `structuredContent`, indent 1), converted at about 4 B/token. The wire carries the payload twice (text and structured; 07 papercut 7), so wire tokens are about 2× these figures.

| Result | Avg bytes | ≈ tokens / call | Calls in 08 + 09 | ≈ share of text tokens |
|---|---:|---:|---:|---:|
| `node_type_info` (FX/ROP types) | 15,545 (09) / 3,099 (08) | 3,900 / 780 | 10 | **~30%** |
| `node_create` | 8,124 (08) / 5,918 (09) | 2,000 / 1,500 | 11 | **~27%** |
| `node_type_search "rbd"` | 12,989 | 3,250 | 1 | 4% |
| `render` (24 frames) | 2,320 | 580 | 4 | 3% |
| `node_layout` | ~2,000 | 500 | 3 | 2% |
| `geo_info` (packed geo) | 985 / 1,690 | 250 / 420 | 27 | 11% |
| `parm_set` | 1,046 / 575 | 260 / 145 | 16 | 4% |
| `viewport_capture` (text) | 421 / 506 | 110 / 125 (+ ~800 per 1024×576 image) | 22 | 1% text, most of the image budget |
| `cook`, `job`, `problems`, `time`, `hip_save` | 99–749 | 25–190 | 19 | 2% |

Across the two workloads (about 294 KB of text, ≈ 74k tokens), **two result types make up about 57% of all text tokens**: `node_type_info` and `node_create`. The read and verification tools (`geo_info`, `geo_read stats`, `cook`, `problems`) are already where they should be. The backlog targets the two big result types first.

---

## 2. Prioritised backlog

### P0 — the agent gets a wrong answer or loses its session

#### B1. Launch lifetime: say it, detect it, and steer agents to attach first

- **Evidence.** 08 §0: *"Nothing in the `houdini_connect` description says that a launched instance is owned by the bridge and dies with it. I found out by observing it."* The follow-up offline hint, *"call houdini_connect with launch to start one"*, was *"accurate but did not help"*. 08 §0.3: *"A plain `houdinifx.exe` does not load the host"*, so "start Houdini yourself" needs `install-houdini` first.
- **Context.** `bridge/launch.py` requests `CREATE_BREAKAWAY_FROM_JOB` and **silently** drops it when the client's job object refuses. The bridge knows whether the child can outlive it but never says; `launched.note` always claims it dies.
- **Change (1.0.x, all additive):**
  1. Replace the last sentence of the `houdini_connect` description with: *"A launched Houdini usually closes when this server exits; to keep one, start Houdini yourself (after hocuspocus install-houdini) and attach by pid."* (net +14 words, about 70 in total, under the 80-word cap.)
  2. Add `launched.outlives_server: bool` to the result, set from whether breakaway succeeded. Choose `launched.note` from that value.
  3. Have the launcher pass `HOCUSPOCUS_LAUNCHED_BY=<bridge pid>` in the child env. The host writes it into its registry entry, and `houdini_status.instances[]` gains `launched_by_server: <pid>|null`.
  4. When the bridge prunes a dead entry that has `launched_by` set to a pid other than its own, make the `houdini_offline` message: *"Houdini pid 22740 was launched by an earlier HocusPocus server (pid 51010) and exited with it; its unsaved changes are lost."* Set the hint to: *"One-shot clients: keep one MCP session open for the whole job, or start Houdini outside the client (after hocuspocus install-houdini) and attach with houdini_connect {pid}."* This is the **keep-alive note** the agent needed. Add the same paragraph to `docs/quickstart.md`, under "Scripted clients".
  5. Append one sentence to the instructions (see §4).
- **Change (1.1 / CLI, M):** add `hocuspocus launch [--gui|--headless] [--hip PATH]`. It starts Houdini with the package injected (the same env the bridge builds), fully detached, and prints `pid`. This is the attach-first workflow without changing who owns a bridge-launched process. A user or agent runs it from a terminal, and then calls `houdini_connect {pid}`.
- **Benefit.** 08 spent about 4 calls, a dead instance, a stray manual `houdinifx.exe` and a hand-written persistent driver to work this out. With the change, the first offline error tells the agent the cause and the fix.
- **Cost.** S for parts 1–5 together (about 2 h with tests). M for the CLI.

#### B2. GUI `viewport_capture` ignores `fit` and returns an empty grid

- **Evidence.** 08 §4.1: *"Both the default and an explicit `"fit":"all"` returned `fit_used: "none"`… an image of the empty construction grid… **the default call gives a useless picture in GUI mode**."* Two of 9 captures were wasted; 09 avoided it by always passing `source: opengl_rop` and a camera.
- **Context.** `_capture_viewer` never reads `fit` and hard-codes `"fit_used": "none"`, against the documented contract.
- **Change (1.0.x, bug fix):** when `camera` is absent and `fit != "none"`, stash the user's view with `saved = viewport.defaultCamera().stash()`, call `viewport.frameAll()` (or `frameSelected()`), flipbook, then `viewport.setDefaultCamera(saved)` in `finally`. Report the real `fit_used`. If framing raises, return `notes: ["The Scene Viewer could not be framed; the image shows the user's current view. Pass source: 'opengl_rop' for an auto-framed shot."]`. Change the description's middle sentence to: *"…uses the GUI Scene Viewer when present (framed per fit, then the user's view is restored), else an OpenGL ROP…"*. Also document that the attached image is downscaled and composited on grey, while the file at `path` is full-resolution with alpha (08 §4.2).
- **Benefit.** The default call in a GUI session becomes useful. That saves about 2 wasted captures (≈ 1.6k image tokens each) per session, plus the diagnosis turns.
- **Cost.** S.

#### B3. `node_type_info` reports one output for multi-output HDAs

- **Evidence.** 09 §5.1: *"`rbdmaterialfracture::4.0`, `rbdconfigure` and `rbdbulletsolver` each report `"outputs": [{"index":0,...}]`. Each really has 3 outputs… An agent trusting `node_type_info` would conclude that the constraint output does not exist."*
- **Context.** `types.py` probes inputs and outputs by creating an instance with `load_contents=False`. An HDA whose contents are not loaded has no output nodes, so `outputNames()` has length 1.
- **Change (1.0.x, bug fix):** size output rows by `max(len(node.outputNames()), node_type.maxNumOutputs())`, naming gaps `output{n}`; or probe HDAs with `load_contents=True` (cached per type) to get real labels. Add an integration case on `Sop/rbdmaterialfracture`.
- **Benefit.** Removes a correctness trap where constraint and proxy outputs are the whole point.
- **Cost.** S.

### P1 — token cost: the two result types that make up 57% of text

#### B4. `node_type_info`: parm-name filter and a folders-only pass

- **Evidence.** 09 §6: *"The four big RBD/ROP types cost 75 KB… `folder` filtering exists, but I had to fetch everything once to learn the folder names. A `names: "concrete_*"` glob, or a folders-only first pass, would cut this by about 90%."* 08 §5: polyextrude compact was 9.9 KB *"no way to ask for just one set of parms"*. 07 papercut 6 was only half fixed: compact mode exists, but there is still no name filter.
- **Change (1.0.x, additive):**
  - `parms: ["concrete_*", "scatterpts", "glue*"]`: a list of `fnmatch` globs on parm name **or** label. It filters rows within the selected folders.
  - `detail: "folders"`: a new enum value that returns `folders: [{name, parm_count}]`, inputs and outputs only, about 0.5 KB.
  - Description sentence: *"parms filters by name or label glob; detail folders lists folder names and counts first."* (+15 words.)
- **Benefit.** rbdmaterialfracture drops from 25.9 KB to roughly 1–3 KB. Across 09 that saves about 60 KB, or ≈ 15k tokens (about 35% of that session's text).
- **Cost.** S–M.

#### B5. `node_create` / `node_copy` / `network_build` result verbosity

- **Evidence.** 08 §5: *"node_create echoes full node_info for every node… each VEX `snippet` comes back verbatim… 12 nodes produced 20 KB… I needed none of it beyond the paths and the errors."* 09 §5.5: two lights returned 5.1 KB of *"ramp keys and `s`/`scale`/`dimmer` reported as `is_default: false`"* that the creation script set. 08 §4.5: `node_copy` returned 9 copies of the same upstream error in 5 KB.
- **Change (1.0.x, additive):** add an optional `return: "full" | "summary"` argument, defaulting to `full`. `summary` returns, per node, `{path, type, errors, warnings, cook_state}` plus `inputs` only when an input failed to wire. Both modes collapse identical error strings: the first node carries the text, and later nodes carry `errors_same_as: "<path>"`. Description: *"return summary gives path, type and problems only."*
- **Change (1.1, contract):** make `summary` the default; in `full`, elide strings over 200 characters as `{"elided": 1234}`, and stop reporting creation-script values as user edits.
- **Benefit.** The 08 builds go from 8.1 KB to about 0.9 KB per call on average (≈ 1.8k tokens saved per call, about 25k tokens per workload). The VEX echo disappears.
- **Cost.** S for 1.0.x. M for the 1.1 default and elision.

#### B6. `node_type_search` rows and `render` outputs

- **Evidence.** 09 §6: *"`node_type_search "rbd"` was 13 KB for 40 rows… older versions of each type are listed. Hiding non-current versions by default would halve it."* 09 §5.3: *"`outputs` lists all 24 absolute paths: 4 KB of 4.0 KB"* and *"The finished result has no `state` field."*
- **Change (1.0.x):**
  - `render`: always include `state: "done"` (this is a fix; the description says "state") and an `outputs_summary: {pattern, count, first, last, missing_count}`.
  - `node_type_search`: an optional `current_only: bool = false`.
- **Change (1.1):** default `current_only: true`, folding older versions into `other_versions: ["rbdmaterialfracture::3.0"]` on the current row. Cap `description` at 120 characters. When `render` has more than 5 outputs, return only `outputs_summary`, and page the full list via `job result`.
- **Benefit.** About 6 KB saved per search and about 3.5 KB per sequence render. Clients that check `state == "done"` stop misreading finished renders.
- **Cost.** S.

### P1 — numbers that mislead

#### B7. `cook` cost reporting

- **Evidence.** 08 §4.3: *"`cook … OUT_CITY, force:true` returned `cook_time_ms: 0.1` for a 191-iteration for-each… misleading when you need to judge whether a network is 'cheap enough for a sim'."* 09 §5.2: *"`cook` on `fracture` after creation reported `cook_time_ms: 0.1`, because `node_create` had already cooked it. I never learned what the fracture costs."*
- **Context.** `_diag._timed_cook` times `node.cook(force)` on the named node only. `force` does not reach upstream nodes, and `node_create` cooks every node it creates (§4.1), so a later `cook` hits a warm cache.
- **Change (1.0.x, wording, S):** change the `cook` description to: *"…cook_time_ms is the named node's own cook; inputs already cooked are not recooked or timed."* Add `hint` when `force` is true and `cook_time_ms < 1` on a node with inputs: *"Upstream nodes were already cooked and are not included in cook_time_ms."* (In 1.1, point it at `profile: true`.)
- **Change (additive, M; scheduled 1.1 for size):** `profile: true` force-cooks the node's `inputAncestors()` in dependency order as one job (each node is a main-thread step). It returns `chain: [{path, cook_time_ms}]` sorted by cost (top 10), plus `total_ms`. This gives a TD the answer *"fracture 1.8 s, cfg_pieces 0.1 s, solver 4.5 s"*.
- **Benefit.** Removes a wrong number from the decision TDs make most often (scatter and iteration counts).
- **Cost.** M.

#### B8. Binary job progress for sims

- **Evidence.** 09 §5.2: *"`progress` is only 0 or 1. There is no 'frame 37/96' while a sim runs, so for a long sim an agent is polling blind."* 09 §7.2 also asked for per-frame bbox to replace 5 `geo_info` calls.
- **Context.** `cook` runs each path as **one** main-thread step, so the job has nothing to report until the cook ends. Sims cook incrementally anyway, so stepping frames costs the same total time.
- **Change (additive, M; scheduled 1.1 for size):** add `frame_range: [start, end, step?]` to `cook`. The job cooks each frame as its own main-thread step, sets `progress` and `message: "frame 37/96"`, and with `summary: "bbox"` returns `frames: [{frame, point_count, prim_count, bbox_min, bbox_max}]`. A long sim then yields the main thread between frames, so the GUI stays responsive.
- **Benefit.** Polling becomes meaningful, and 5 `geo_info` calls (≈ 2k tokens) collapse into one result.
- **Cost.** M.

### P2 — missing conveniences agents reached for

#### B9. Spare parms (the only reason 08 used `houdini_python`, twice)

- **Evidence.** 08 §3: *"No typed tool creates spare parms or parm templates… it was the *only* reason I needed `houdini_python`."* The `parm_not_found` hint *"does not help when the goal is to *add* a parm."* 09 §5.7 hit the consequence: `chf("glue_strength")` with no spare parm silently evaluated to 0.
- **Change (1.0.x, S):** when `parm_not_found` targets a `null`, `subnet`, `geo` or an unlocked HDA, append to the hint: *"To add a control parm, use houdini_python with node.addSpareParmTuple(...), or reference an existing parm."* Add a 6-line spare-parm snippet to `docs/tools.md` / the guide under `houdini_python`.
- **Change (1.1, M):** add a `spare_parms` field to `node_edit` items: `{add: [{name, type: float|int|string|toggle|menu|button, label?, default?, size?, min?, max?, menu_items?, folder?}], remove: [names]}`. No new tool; it needs a BIBLE §4.4 row, hence 1.1. For wrangles the hint should name the existing "Create spare parameters" button via `parm_set press`.
- **Benefit.** Removes the most common reason for Python in procedural builds, and the silent `ch()`→0 class of bug.

#### B10. Lights for OpenGL renders, and light-type candidates

- **Evidence.** 09 §5.4: *"My first GIF pass was 24 silhouettes: RGB max 5… `viewport_capture` had lit the same scene… Nothing in either tool says so."* 09 §5.1: `node_create distantlight` candidates were `indirectlight, ambient, envlight` and *"missed the obvious answer… `hlight`"*.
- **Change (1.0.x, S):**
  - In `render` and `viewport_capture`, add `notes: ["Scene has no lights; OpenGL output relies on the ROP's headlight setting and may render black."]` when `/obj` has no light objects and no LOP lights, and `"thumbnail is nearly black"` when its mean luminance is under 2%.
  - Verify why the temporary capture ROP rendered lit and `/out/ogl_gif` did not (both default `opengl` nodes; unexplained) and document the cause.
  - In `node_type_not_found`, also score candidates by label, and add `distantlight|pointlight|spotlight → hlight` to the synonym table with *"set light_type"* in the hint.
- **Benefit.** One wasted 24-frame render pass and one retry per lighting task.

#### B11. A scene outline view

- **Evidence.** 09 learned the scene from review 08's prose and node comments. No call answers "what's in this hip" (objects, OUT nulls, display flags, cameras, lights, ROPs, comments): `network_describe` is per-network and parm-heavy, and `node_find` rows carry no comments.
- **Change (additive enum value, M; scheduled 1.1):** `network_describe {root: "/", format: "outline", depth: 2}` returns one compact line per node, for example `"/obj/city_gen geo [display] — 'City generator: CONTROLS…' (out: OUT_CITY)"`, plus a `cameras`, `lights` and `rops` roll-up. No parms; about 4 KB cap with `cursor`; mirror as `houdini://outline`.
- **Benefit.** A handoff between agents, or after `hip_open`, costs 1 call and about 1k tokens instead of reading a log or making 5–10 `node_info` calls.

#### B12. Buttons and paired blocks

- **Evidence.** 09 §3: *"`parm_set press` reset the sim"*. It works, but `press` is one word in a 9-option list. 08 §4.5 and the honourable mention: block_begin/block_end were wired by hand, with *"expected transient errors"*.
- **Change (1.0.x, S):** in the `parm_set` description, change `press` to *"press (click a button parm such as resetsim)"*.
- **Change (1.1, M):** in `node_create`, when a `block_begin` and a `block_end` (or `compile_begin`/`compile_end`) are created in the same call, set `blockpath`/`templatepath` before the first cook, as the Tab menu does. Collapse the transient errors with B5.

### P3 — review 07 papercuts not yet fixed

`42065bf` skipped three: text/structured duplication, `houdini_python` `isError`, and `locked`. The rest of 07's list is fixed (I confirmed the unknown-tool "Did you mean" in `server.py`).

| # | Item | Change | Track | Cost |
|---|---|---|---|---|
| B13a | **Text/structured duplication** (07 papercut 7) doubles every result on the wire. The biggest lever left. | Bridge config `text_content = "full" \| "summary"` (default `full`); `summary` sends a ≤ 300 B digest in `content[0].text`. Measure client behaviour before changing the default. | 1.0.x opt-in; default in 1.1 | M |
| B13b | **`houdini_python` exceptions are `isError: false`** (07 §7). | Add a top-level `ok: false` and append `exception.type: message` to the text block's first line. Revisit `isError` in 1.1. | 1.0.x | S |
| B13c | **`locked`** means HDA-locked in `network_describe` but the lock flag in `node_info`. | Emit `hda_locked` next to `locked` in `network_describe` now; drop the ambiguous key in 1.1. | 1.0.x + 1.1 | S |
| B13d | `problems` does not recheck stale **warnings** (08 §4.4; 09 could not reproduce). | Reproduce with an attribute-mismatch warning on a merge, then extend the §5.18 recheck to warnings when it is cheap. | 1.0.x if reproduced | S |
| B13e | `geo_info` listed a polyextrude `glass` group under `groups.edge` (08 §4.6, unverified). | Write an integration repro; if it is real, classify groups by `geometry.primGroups()` and not by name lookup. | investigate | S |

---

## 3. Description wording that misled either agent

| Tool | Current text | Problem | Fix |
|---|---|---|---|
| `houdini_connect` | "The selection lasts for the bridge's lifetime." | Read as the selection, not the process. | B1.1 |
| `viewport_capture` | "…framing a temporary camera per fit" | `fit` assumed to apply to the viewer. | B2 |
| `cook` | "report per node … cook_time_ms" | Both agents took it as network cost. | B7 |
| `node_type_info` | "named inputs and outputs" | Wrong for HDAs. | B3 |
| `render` | "else job_id and state to poll with job" | Implies `state` only while running. | *"Returns state, outputs, outputs_summary and a thumbnail when done within wait_s; else job_id and state: running."* |
| `job` | "status returns state …, progress" | Implies granular progress. | *"progress is per node for cook, per frame for render, per work item for pdg."* |
| `parm_not_found` hint | "List the node's parm names with node_info…" | Dead end when adding a parm. | B9 |

---

## 4. The `instructions` text

It is 196 words against a 400-word cap, and both agents followed it. The route it gives (`houdini_status` → build → `cook`/`geo_info` → `viewport_capture`) matches what 08 and 09 actually did. It is missing the three facts that cost them the most. I propose appending these (+68 words, total ≈ 264):

> A Houdini started with `houdini_connect {launch}` usually closes when this server exits; save with `hip_save`, keep one session open for long jobs, or attach by pid to a Houdini the user started. In a GUI session prefer `viewport_capture {camera}` or `source: "opengl_rop"` for framed shots. `node_type_info` is large for FX types: pass `folder` or `parms` globs. Spare parms need `houdini_python` (`addSpareParmTuple`).

The `viewport_capture` sentence can come out once B2 ships. `geo_read {stats: true, count: 1}` was *"the fastest debugger in the toolbox"* (09), and it is worth one more clause if there is room.

---

## 5. What not to change

Protect with tests: batched `node_create` with intra-call wiring (14 nodes, HDA outputs 1 and 2, one call); `rolled_back` with tuple-aware hints (*"This was excellent. I fixed it in one retry."*); `geo_read stats`; `cook`→`job` escalation. No proposal here adds a tool; the count stays at 31.

---

## 6. Recommended scope

### 1.0.1 (additive only, ≤ 1 day)

1. **B2:** the GUI viewer honours `fit` (stash, frame, flipbook, restore), reports `fit_used` honestly, and adds `notes` on fallback. The `viewport_capture` description and docs mention the grey composite versus the alpha file. *(S)*
2. **B1.1–B1.5, launch lifetime:** `houdini_connect` description wording, `launched.outlives_server` from the breakaway result, `launched_by` in the registry and status, an offline error that names the earlier server, the keep-alive hint, and a quickstart "Scripted clients" note. *(S)*
3. **B3:** correct `node_type_info` outputs for multi-output HDAs, with an rbdmaterialfracture test. *(S)*
4. **B4:** `node_type_info` `parms` glob filter and `detail: "folders"`. *(S–M)*
5. **B5 (1.0.x part):** `return: "full" | "summary"` on `node_create`, `node_copy` and `network_build`, with identical-error collapsing in `summary`. *(S)*
6. **B6 (1.0.x part) + B10:** `render` always carries `state` and `outputs_summary`, with no-lights / near-black `notes`. `node_type_search` gets `current_only`. Light-type candidates come from labels and synonyms. *(S)*
7. **Wording and hints:** the `cook` description and warm-cache hint (B7), the spare-parm `parm_not_found` hint and guide snippet (B9), the `press` wording (B12), the `render`/`job` wording (§3), `hda_locked` next to `locked` (B13c), and `ok: false` on `houdini_python` exceptions (B13b). *(S)*
8. **Instructions update (§4) and the real `tools/list` budget test** (§1.1, 40,000 B cap on the serialised result). *(S)*

That is about 7–8 hours, with no default changed and no field removed. Every change is either a new optional argument or result field, `notes`/`hint` text, or a fix that brings behaviour into line with the documented contract (B2, B3, `render.state`).

### 1.1 (contract changes and larger additions)

- **B5:** `summary` becomes the default mutation echo; long strings are elided; creation-script values are not reported as user edits.
- **B13a:** text/structured de-duplication by default, after measuring client behaviour. This is worth about 50% of wire bytes on every call.
- **B7 + B8:** `cook {profile: true}` with chain timing, and `cook {frame_range, summary: "bbox"}` with per-frame progress and a motion summary.
- **B9:** `node_edit` `spare_parms`, with a BIBLE §4.4 amendment.
- **B11:** `network_describe format: "outline"` and `houdini://outline`.
- **B6:** `node_type_search` defaults to current versions, with capped descriptions; `render` returns only `outputs_summary` above 5 frames.
- **B12:** automatic `blockpath` pairing in `node_create`.
- **B13b/c:** decide `houdini_python` `isError` semantics; remove the ambiguous `locked` key.
- **B1 CLI:** `hocuspocus launch` for an attach-first workflow that outlives any MCP client.
- BIBLE: record that the CI budget measures the serialised `tools/list`, and add the `outline`, `profile` and `frame_range` rows to §4.

On the two logged workloads, 1.0.1 would have saved about 30–35% of text tokens (mostly B4 and opt-in B5), 2 wasted captures, 1 black render pass, 1 dead instance and 1 wrong model of the RBD graph.
