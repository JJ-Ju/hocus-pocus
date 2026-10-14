> **Status: evaluation record.** HocusPocus 2.0 pre-release, scored from branch `release/2.0` at `426d015` on 2026-10-14. See [`../README.md`](../README.md).

# 25 — Scorecard re-run: the review 21 tasks against 2.0

**Reviewer seat:** an independent agent with only the MCP surface on the default `core` profile (the `server/discover` instructions, `tools/list`, the `hocuspocus://guide` and `hocuspocus://tools` resources, the prompts and error messages) plus `README.md`, `docs/quickstart.md` and `docs/migration-2.0.md`. I did not read the server source. The one other repo file I read was `tests/e2e/test_scenario_authoring_v2.py`, for the client pattern.
**Build:** `release/2.0` at `426d015`, installed with `uv pip install -e .` into a scratch venv. Every version string still says `1.4.0` (papercut 4).
**Host:** Houdini 22.0.466 `hython`, headless, launched *by the agent* through `houdini_connect {"launch":{"mode":"headless"}}` from one long-lived client session. The scratch dir held `HOCUSPOCUS_STATE_DIR`, `HOCUSPOCUS_WORK_DIR` and `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, with no `hocuspocus.toml` and no `HOCUSPOCUS_PROFILE`, so the profile was `core` (18 tools). Review 21 ran on `full` (35 tools).
**Transport:** the official `mcp` 2.3 client (`mcp.Client` + `StdioServerParameters`) talking to `hocuspocus-mcp` through a byte-counting stdio tee. The handshake is `server/discover`. Every call was logged with bytes and timing.
**Totals:** 111 JSON-RPC round trips and 435,593 response bytes on the wire (review 21: 122 and 458,109). Of that, 250 KB is three PNGs and 59 KB is the two opt-in reference resources.

Byte counts are on the wire unless marked *text*. *Text* is the tool result's JSON text block, which is what the model reads. Token estimates are `bytes / 4`.

**Concurrent edits.** Another agent was editing `src/` during the run (`git status` showed `src/hocuspocus/host/tools/search.py` modified). The host was launched three times and every `search` and `inspect` result kept the same shape throughout. One shape is off against the docs, though: `docs/migration-2.0.md` §1 says `inspect` returns `{what, target, etag, ...}`, but every `inspect` result I got started with `{etag, ...}`, with no `what` or `target` keys.

**1.4 names.** On the task path I never reached for a 1.4 name: the instructions and the guide led straight to `edit`, `inspect`, `search` and `look`. I called the 1.4 names on purpose in task 9 (`node_connect`, `node_info`, `viewport_capture`, a flat `parm_set`, `inspect {path}`). The refusals for the tool names are excellent. The `path` argument isn't steered to `target` (papercut 2). The real problem runs the other way: the 2.0 server's own **hints** send the agent to 1.4 tools (papercut 1).

---

## 0. Getting a host up: 2 calls, 2.3 KB

```
houdini_status {}                                174 B text  "No Houdini with HocusPocus is running; houdini_connect {launch: {mode}} starts one."
houdini_connect {"launch":{"mode":"headless"}} 1,434 B text  1.5 s; pid, role:"worker", hip .../work/untitled.hip,
                                                             launched.outlives_server:false + the hip_save note
```

The same as 1.3, with `role` added. The launch took 1.5 s on a warm machine; relaunches in task 12 also took 1.5 s.

## 1. Discover: 9 calls, 12.5 KB wire (+23.2 KB handshake)

| Call | Bytes | Notes |
|---|---:|---|
| `server/discover` | 2,633 wire | 2.5 KB of instructions, all in 2.0 terms: `edit` with `$id`, `dry_run`, `inspect {what, target}`, `search {kind}`, `look {quality}`, **and the `parm_set {items: [{path, value}]}` shape** |
| `tools/list` (core) | 20,532 wire | **18 tools, ~5.1k tokens** (review 21: 35 tools, 30.7 KB on `full`). The largest entries are `edit` (3.0 KB), `node_create` (2.8 KB) and `inspect` (2.5 KB) |
| `houdini_status` | 1,264 text | It doesn't show `role` per instance, though migration §4 says it adds one; it repeats the hip path (papercut 10) |
| `search {kind:"nodes", root:"/"}` | 1,063 text | 9 manager roots |
| `houdini://outline` / `inspect {what:"outline"}` | 905 / 340 text | The same tree. The tool form costs a third of the resource read |
| resources, templates, prompts lists | 5.5 KB text | 8 resources, 10 templates (every one says which `inspect` it is), 7 prompts |
| `get_prompt build_sop_chain`, `debug_red_node` | 2.1 KB text | Both are rewritten for 2.0 (one `edit` call, `dry_run`, `inspect`, `look`) |

## 2. Build geo → box → mountain → subdivide → null OUT: **1 call**, 588 B text

```json
edit {"ops":[{"op":"create","id":"geo","parent":"/obj","type":"geo","name":"terrain"},
  {"op":"create","id":"box","parent":"$geo","type":"box"},
  {"op":"create","id":"mtn","parent":"$geo","type":"mountain","parms":{"height":0.5,"offsetx":{"expression":"$F*0.1"}},"inputs":[{"index":0,"from":"$box"}]},
  {"op":"create","id":"sub","parent":"$geo","type":"subdivide","inputs":[{"index":0,"from":"$mtn"}]},
  {"op":"create","id":"out","parent":"$geo","type":"null","name":"OUT","inputs":[{"index":0,"from":"$sub"}],"flags":{"display":true,"render":true}},
  {"op":"layout","parent":"$geo"}]}
→ 588 B, 194 ms, one undo step "HocusPocus: edit 6 ops"; ids map, the mountain deprecation note, dirty:true
```

It worked on the first try, written from the instructions alone, and the layout went in the same call. Review 21 needed `node_create` plus `node_layout`: 2 calls, 1.1 KB text. The result rows are "problems only", so `/obj/terrain` shows `cook_state:"not_cooked"` while the SOPs show nothing at all. That reads oddly, but it is harmless.

## 3. Read back: 6 calls, 3.2 KB text

| Call | Text | Notes |
|---|---:|---|
| `inspect node` paths mountain1 + OUT | 1,155 | Same content as `node_info` in 1.3 (1,153), plus `etag` |
| `inspect parms` offset, height | 538 | `kind:"tuple"`, `component_names`, `expressions`, `hda_locked` |
| `cook` OUT | 142 | Redundant in 2.0: the `edit` rows already carry cook state |
| `inspect geo` OUT | 504 | 26/24/96, bbox, typed attributes |
| `inspect geo rows:true attribs:["P"] count:5` | 335 | rows + `next_cursor` |
| `inspect network` /obj/terrain | 523 | `hou.data` form, `hda_locked` on mountain1 |

The reads match 1.3 almost byte for byte. Each `inspect` adds a 35 B `etag`.

## 4. Frame 24: **3 calls**, 1.0 KB text

`inspect {what:"parms", target:".../offsetx", frame:24}` → `"value":2.4`, and with `frame:48` → `4.8`. `inspect geo frame:24` showed the bbox shifted. No `time` call was needed (review 21: 4 calls).

## 5. Save and dirty: **5 calls, 0 failures**, 5.7 KB wire

```
hip_save {"path":".../work/hips/friction.hip"}                       → dirty:false, bytes 88550 (directory created)
edit {"ops":[{"op":"set","path":".../mountain1/height","value":0.7}]} → 96 B, dirty:true
houdini_status                                                       → dirty:true, dirty_source:"tracked", recent:[friction.hip]
hip_save {} ; houdini_status                                         → dirty:false, dirty_source:null
```

Review 21 needed 12 calls here, two of them failed. 1.3's papercut 1 never came up, because the instructions now show the `items` shape and `edit set` is the obvious form. A detail: the `set` row doesn't echo the value it set. It shows only the node and its cook time.

## 6. Scatter + copy sphere: 9 calls, 10.5 KB text

```
search types "scatter" (Sop, 5)                    → #1 scatter::2.0                           1,590 B
search types "scatter points on a surface" (5)     → #1 scatter::2.0, #2 scatteralign          1,592 B
search types "copy to points" (Sop, 5)             → #1 copytopoints::2.0                      1,432 B   (U+FFFD on maskbyfeature, still)
inspect type Sop/scatter                           → 3,066 B compact rows
inspect type Sop/scatter detail:"folders"          →   711 B
inspect type Sop/scatter parms:"*count*|npts"      →   718 B (inputs → inputs_count, still)
inspect type Sop/copytopoints include_parms:false  →   607 B
edit 3 creates (scatter npts 200 ← OUT, sphere .05, copytopoints [0]←$sph [1]←$sc, display) → 290 B, first try
inspect geo copy1                                  → 200 pts, prim_types {"sphere":200}
```

Ranking and type info are as good as in 1.3. `search kind:types` now pages (`next_cursor`).

## 7. Arbitrary hou Python: 7 calls, 2.1 KB text

`houdini_python` behaved as in 1.3: hipFile, point count, `$HIPNAME` and `opls` through HScript, and the `1/0` exception came back `isError:true`, `python_exception`, with `rolled_back:true`. **1.3's papercut 2 is fixed.** `undo history` now shows `redo: []` and lists the failed step separately under `rolled_back`. `undo {"action":"redo"}` returns `performed: []`, `skipped: [...]`, "is a call that failed and was rolled back, so it is not redone", and `/obj/pyjunk` stays gone. One nit: the history `note` leaks an internal reference ("(review 22 finding 9)").

## 8. Visual: 11 calls, 256.1 KB (three PNGs)

```
look {}                                   → 143,095 B wire, 3.6 s cold; flipbook backend, chain [flipbook, opengl, karma], camera_used temporary, fit_used all
look {target: copy1, resolution:[512,384]} →  52,060 B, 0.45 s; 200 grey spheres, framed on the target
houdini_status → dirty:false;  search nodes /out → [];  undo history unchanged
search types flipbook (Driver)            → Driver/flipbook
edit create /out/fb flipbook              → 61 B
render /out/fb [1,3]                      → node_not_found "/out/fb's camera parm points at /obj/cam1, which does not exist."
                                            hint "Create a camera (node_create cam in /obj) and set the ROP's camera parm, or pass camera;
                                                  viewport_capture frames the scene without one."
edit create /obj/cam1; render             → 3 outputs, thumbnail, no-lights note, job_id "jb7896" (a ledger id), 3.9 s
```

`look` is side-effect free and picks its own backend. **1.3's papercut 5 is fixed**: the no-camera error now explains itself. But its hint names `viewport_capture`, which the `core` profile no longer serves (papercut 1). The default look is still 1024×768, about 143 KB.

## 9. Deliberate mistakes: 36 calls, 27.5 KB wire

| Mistake | Response (trimmed) | Verdict |
|---|---|---|
| `edit create type:"mountian"` | `node_type_not_found`, candidates `mountain, mpmcontainer`, hint "...**node_type_search** finds types by label." | Good message; the hint names a removed tool |
| `edit set box1/sizee` | "Did you mean size? It is a tuple: ... or a component (sizex/sizey/sizez)" | Excellent |
| `edit create box parms:{sizee:3}` | `parm_not_found`, candidates, hint "**Use node_type_info** to list the type's parms." | Removed tool in the hint |
| `parm_set {path, value}` (flat) | "...hint: this tool takes a batch; pass the item inside items: `{"items": [{"path": ".../height", "value": 0.7}]}`" | **Fixed** (1.3 papercut 1) |
| `node_connect {...}` (1.4 tool) | "node_connect is a 1.4 tool that the 2.0 core profile does not serve." hint "In 2.0 use edit op: connect ... compat_1x ..." | Excellent |
| `node_info`, `viewport_capture` (1.4 tools) | the same form; `viewport_capture` → "look (quality: draft \| lit \| final; source: viewer for the GUI view)" | Excellent |
| `node_creat` | `-32602` "Unknown tool: node_creat. Did you mean node_create?" | Good |
| connect `to_input:5` / `"points"` | "it has no input 5 (it takes 2)" + labelled inputs / "no input named 'points'" + candidates | Excellent |
| connect `from:".../nope"` | "**items[0] (/obj/terrain/copy1)**: No node at /obj/terrain/nope." hint "Did you mean a candidate? **node_find** {root: ...} lists its children." candidates `["/obj/terrain/copy1"]` | Still poor: wrong field name, target as candidate, removed tool |
| `inspect node .../OUTT` | candidates `["/obj/terrain/OUT"]`, the same `node_find` hint | Good candidate, stale hint |
| `create geo` in a SOP net | "geo is an Object node type, but /obj/terrain holds Sop nodes." + 8 noise candidates | Unchanged |
| `inspect {node_path}` | "node_path: unknown property; **did you mean depth?**" | **Worse than 1.3** ("did you mean path?") |
| `inspect {path}` (the 1.4 argument) | "path: unknown property; **did you mean paths, depth?**" | Misses `target`, the one rename every 1.4 user hits (papercut 2) |
| `ops` as an object | "ops: expected array, got object {..."val�" | Good, but the clip ends in U+FFFD |
| `height = "tall"` | "it is a float parm; got 'tall'." hint "use the expression field **in parm_set**, or ... **in node_create parms**" | Correct, but it talks about other tools, not the `edit set` op that was called |
| `size = [1,2]`, `generateby = "Count"` | components / tokens and labels | Good |
| expression `"$F*("` | `edit` row `errors:["Unable to evaluate expression (Bracing error ...)"]`, `cook_state:"error"` | Good |
| `inspect geo box1` (errored) | `cook_failed` + "see also **the problems tool**" | Removed tool in the hint |
| `inspect problems /obj` → fix (`revert_to_default`) → `problems` | one entry → `edit` row clean → `[]` "No problems under /obj" | Good (closed loop, unchanged) |
| `hip_open nope.hip` | `file_not_found`, candidate friction.hip | Good |
| `look camera:"/obj/nocam"` | candidates `["/obj/cam1"]`, the same `node_find` hint | Stale hint |
| `cook {bogus}` | lists the allowed arguments | Good |
| `job status "123-abc"` | `job_not_found` "pid 123 is not a Houdini this server knows ... so no job of that id ran here." | **Fixed** (1.3 papercut 3) |
| `job status "jzzzz"` (ledger form) | `job_not_found` hint "Jobs live in the Houdini process that started them (**the pid before the '-' in the id**) and **do not survive a Houdini restart**" | Describes 1.x ids and contradicts the 2.0 ledger |
| `inspect {what:"node"}` (no target) | "what: node needs target or paths." hint "...(**docs/tools.md**)" | Points at a repo file, not `hocuspocus://tools` |
| `inspect what:"nodes"` | enum listed | Good |
| `edit connect from:"$foo"` | "from '$foo' names no op id (ids in this call: none)." | Excellent |
| `edit dry_run` with two bad ops | `parm_not_found` "(+1 more problem(s))", `detail.problems` lists both | Excellent: every problem in one round trip |
| `search` without `kind` | "kind: required property is missing" | Fine |
| `inspect {bogus_frame}` | "did you mean frame?" | Good |

## 10. tools/list and the reference resources: 2 calls, 58.9 KB

- **`tools/list` (core): 18 tools, 20,532 B, about 5.1k tokens**, with no `outputSchema`. The 1.4 `core` profile was about 27 KB (README).
- `hocuspocus://guide` is 6.5 KB (7,155 B wire). Every recipe uses 2.0 forms, and the spare-parm recipe is now an `edit` with a `node` op and a `set` op that the schema accepts. **1.3's guide bug is fixed.**
- `hocuspocus://tools` is 51.7 KB. Its header is wrong: "18 in `core` (the default), 18 in `full`" (the README and migration doc say 21), and "`compat_1x` lists the 14 1.4 tools ..., 0 of them only there" (it lists 35, 18 of them only there). It also has a mojibake "`docs/BIBLE.md` �4". It still mentions `node_find`, `node_info`, `viewport_capture`, `network_build` and others 1–3 times each. Some of those are mapping notes; I didn't audit every mention.
- The `node_create` description still ends "network_build suits whole graphs."

## 11. `hip_new` with unsaved changes: 7 calls, 1.7 KB text

The same as 1.3, and safe by default. `unsaved_changes` now carries `detail.dirty_source:"tracked"`. **1.3's papercut 7 is unchanged:** on an untitled scene the hint still offers `on_unsaved: 'save'` first, and that call then fails with "The scene is untitled, so on_unsaved: 'save' has nowhere to save it."

## 12. Kill Houdini, call, relaunch: 7 calls, 8.8 KB wire

```
taskkill 56120
search nodes /obj → instance_lost "The pinned Houdini pid 56120 (hython) has exited; ... Live: none is running." retryable:false
houdini_status    → connected:null, lost, recent:[{pid 56120, alive:false}], the same text as a warning ("Houdini_connect {pid} ...", capitalized)
houdini_connect {launch:{headless, hip:friction.hip}} → 1.5 s; inspect geo copy1 → 200 pts
houdini_python (create node, sleep 8) + kill after 3 s
  → houdini_offline "The Houdini you were driving (pid 10388) exited while running houdini_python; changes ... lost."
    hint: a pasteable houdini_connect {launch: {mode:'headless', hip:'.../friction.hip'}}
next call → instance_lost with the same pasteable launch in its hint; relaunch 1.5 s
```

This matches 1.3. The nits are unchanged: two codes for one event, "pins one of the candidates" when there are none, and the capitalized "Houdini_connect".

**Extra:** `inspect network /obj/terrain` (827 B) then `edit [create geo t2, build data]` (454 B) rebuilt all 7 nodes with an identical bbox. The `create` and the `build` went in one call (review 21: 6 calls, 6.6 KB; here 3 calls plus one ETag probe). Sending `_meta["If-None-Match"]` on an `inspect` *tool* call returned the full body. The guide promises `not_modified` for *resources* only, so this is as documented.

---

## Per-task totals

| Task | 1.3 calls | 1.3 wire | **2.0 calls** | **2.0 wire** | 2.0 first-try? |
|---|---:|---:|---:|---:|---|
| handshake (`server/discover` + `tools/list`) | 2 | 33,457 | 2 | 23,165 | — |
| 0 host up | 2 | 2,302 | 2 | 2,344 | yes |
| 1 discover | 6 | 7,723 | 9 | 12,525 | yes (3 extra: both outline forms, 2 prompts) |
| 2 build + layout | 2 | 2,042 | **1** | 1,138 | yes |
| 3 read back | 6 | 5,733 | 6 | 6,267 | yes |
| 4 frame 24 | 4 | 2,645 | 3 | 2,472 | yes |
| 5 save / dirty | 12 | 11,747 | **5** | 5,696 | **yes** (1.3: 2 rejected calls) |
| 6 scatter + copy | 10 | 16,417 | 9 | 15,703 | yes |
| 7 python | 5 | 4,475 | 7 | 5,683 | yes (2 extra: verified the redo fix) |
| 8 visual | 12 | 256,872 | 11 | 256,085 | look yes; `render` failed once (no camera), now with a hint |
| 9 mistakes | 37 | 27,576 | 36 | 27,529 | n/a |
| 10 guide + tools reference | 2 | 65,126 | 2 | 58,858 | — |
| 11 hip_new | 7 | 4,541 | 7 | 5,061 | yes |
| 12 kill + recover | 9 | 10,898 | 7 | 8,792 | yes |
| extra: describe → build | 6 | 6,555 | 4 | 4,275 | yes |
| **Total** | **122** | **458,109** | **111** | **435,593** | |

**Model-visible text:** the 101 tool results came to **52.6 KB, about 13.2k tokens** (review 21: 112 results, 57.7 KB, ~14.4k tokens). That excludes images, `tools/list`, resources and prompts. The handshake costs another 10.3 KB less than in review 21, but part of that is `core` against `full`.

**Where 2.0 saves, and where it doesn't.**
- The savings come from the change paths: build (2→1), save/dirty (12→5, by avoiding the shape trap) and describe→build (6→3).
- The read paths cost the same as 1.3: one `inspect` per 1.4 read, plus a 35 B `etag`.
- I spent the calls that were saved on extra checks (prompts, the redo verification). On the twelve tasks as review 21 ran them, a strict replay would come to about 106 calls.
- Per-response wire overhead is still ~450–520 B (`_meta` with `serverInfo`, `timing`, `instance`, `pid`). That's more than many payloads: a `set` result is 96 B of text and 579 B on the wire.

---

## Scorecard (1 = poor, 5 = excellent; definitions as in review 07)

| Dimension | 0.9 | 1.0 | 1.3 | **2.0** | Why (2.0) |
|---|:---:|:---:|:---:|:---:|---|
| Discoverability | 2 | 4 | 4 | **4** | The happy path is now a 5. The instructions name every 2.0 shape (`edit` ops with `$id`, `dry_run`, `inspect {what, target}`, `search {kind}`, the `parm_set` `items` shape). The guide recipes all validate, the prompts were rewritten for 2.0, `tools/list` is 5.1k tokens, and every task call succeeded on the first try. It stays at 4 because the error path now *teaches 1.4*: hints name `node_find`, `node_type_info`, `node_type_search`, "the problems tool" and `viewport_capture`, which `core` refuses. `inspect {path}` doesn't suggest `target`. The tools reference header miscounts the profiles. |
| Idiom match with Houdini vocabulary | 2 | 5 | 5 | **5** | Still node, parm, tuple and component paths, `hou.data` for `build`, HScript in `houdini_python`, and deprecation notes that name the replacement. `edit` ops are Houdini verbs (create, connect, set, layout), and `look` hides the ROP plumbing. |
| Verbosity / token cost | 1 | 4 | 5 | **5** | 111 calls against 122, 435.6 KB against 458.1 KB on the wire, 52.6 KB against 57.7 KB of model text. `tools/list` is 20.5 KB (18 tools). A 5-node build plus layout costs 588 B. The leftover costs are unchanged: the 1024×768 default look (143 KB) and ~500 B of envelope per response. |
| Error quality | 3 | 4 | 5 | **4** | New and excellent: removed-tool refusals that name the replacement and the `compat_1x` escape, `dry_run` reporting every problem at once, `$id` errors, and the flat `parm_set` hint that shows the wrapped call. 1.3's false job message and its no-camera hint are fixed. But at least seven distinct messages now tell the agent to call a tool the default profile doesn't serve. That is the same class of fault that held 1.3's job message back ("states something false"), and here it is systematic: each one costs a wasted call. The 1.4→2.0 argument rename isn't suggested (`path` → "did you mean paths, depth?"; `node_path` regressed to "depth"). The `job_not_found` hint describes 1.x ids, and `edit` errors say `items[0]` for `ops[0]`. |
| Number of concepts to learn | 1 | 5 | 5 | **5** | Fewer tools (18 against 35). The new concepts are `what`/`kind` selectors, op `id`/`$id`, `dry_run`, `etag`, `quality` and roles, and the first four replace sixteen tool names. |
| Time to first success | 1 | 5 | 5 | **5** | 2 calls to a host (1.5 s). The 5-node chain with layout took **1** call (194 ms), verified with one `inspect`. |

**2.0: 4 / 5 / 5 / 4 / 5 / 5**, against 1.3's 4 / 5 / 5 / 5 / 5 / 5, 1.0's 4 / 5 / 4 / 4 / 5 / 5 and 0.9's 2 / 2 / 1 / 3 / 1 / 1.

---

## The 10 worst papercuts

1. **Error hints name tools the 2.0 `core` profile does not serve.**
   - Every one of these sends the agent to a refusal (one wasted call; it then reads the refusal's replacement):
     - `node_not_found` (connect `from`, `inspect node`, `look camera`): "Did you mean a candidate? **node_find** {root: \"/obj/terrain\"} lists its children."
     - `parm_not_found` from create `parms`, and in `dry_run` problems: "**Use node_type_info** to list the type's parms."
     - `node_type_not_found`: "Closest Sop types: mountain, mpmcontainer. **node_type_search** finds types by label."
     - `cook_failed` from `inspect geo`: "Fix the errors in detail (see also **the problems tool**), then retry."
     - `render` no camera: "...or pass camera; **viewport_capture** frames the scene without one."
     - `invalid_value` on an `edit set` op: "use the expression field **in parm_set**, or ... **in node_create parms**."
   - Proposed change, by message:
     - `search {kind: "nodes", root}` instead of `node_find`
     - `inspect {what: "type", target, parms: "<glob>"}` instead of `node_type_info`
     - `search {kind: "types", query}` instead of `node_type_search`
     - `inspect {what: "problems"}` instead of "the problems tool"
     - `look {camera}` instead of `viewport_capture`
     - "the `expression` field of a `set` op" in the `invalid_value` hint
   - Also add a test that every hint string under each profile names only tools that profile lists.
2. **`inspect` doesn't steer the 1.4 path arguments to `target`.**
   - `inspect {what:"geo", path:...}` → "path: unknown property; did you mean paths, depth?"
   - `{node_path}` → "did you mean depth?" (1.3 said "did you mean path?")
   - Proposed change: a rename table (`path`, `root`, `lop_path`, `type`, `node_path` → `target`) checked before edit-distance suggestions: "path: unknown property; inspect takes the node as target".
3. **`edit` error locations are wrong.**
   - Messages say `items[N]` although the argument is `ops`.
   - The prefix names the op's node, not the bad field: "items[0] (/obj/terrain/copy1): No node at /obj/terrain/nope."
   - The only candidate is the connect *target* itself (`["/obj/terrain/copy1"]`).
   - Proposed change: "ops[0].from: No node at /obj/terrain/nope", with candidates taken from the parent's children by name distance.
4. **The 2.0 build reports itself as 1.4.0.**
   - `server_info.version`, `bridge_version` and `host_version` all say `1.4.0`, and `uv` installs the package as `hocuspocus 1.4.0`.
   - `serverInfo` (~200 B) is repeated in every result's `_meta`.
   - Proposed change: bump to `2.0.0` before tagging, and keep `serverInfo` in the handshake only.
5. **`job_not_found` hint describes 1.x job ids.** For `jzzzz`: "Jobs live in the Houdini process that started them (the pid before the '-' in the id) and do not survive a Houdini restart". 2.0 ids are ledger ids (`jb7896`) and survive a bridge restart. Proposed change: for a ledger-form id, say "No job jzzzz in the ledger; `job {action: list, all: true}` lists them"; keep the pid text for `<pid>-<id>` ids.
6. **The `hocuspocus://tools` reference and the tool descriptions are stale.**
   - The reference header says "18 in `core`, 18 in `full`" and "`compat_1x` lists the 14 1.4 tools ..., 0 of them only there".
   - The reference has a mojibake "`BIBLE.md` �4".
   - The `node_create` description ends "network_build suits whole graphs."
   - `invalid_argument` hints say "(docs/tools.md)", a file an MCP client can't read.
   - Proposed change: generate the header from all four profiles, write `§` as UTF-8, say "`edit` `build` op", and point to `hocuspocus://tools`.
7. **The default `look` is still 1024×768**, about 143 KB per look (3.6 s cold). The 512×384 look of the same scene was 52 KB, 0.45 s and fully readable. Proposed change: default `resolution` to `[512, 384]` (or name `resolution` in the instructions), with 1024 on request.
8. **U+FFFD in clipped strings.** `search` types: maskbyfeature's description ends "areas tha�" (unchanged since 1.3). An `ops` type error clips its echo to `"val�"`. Proposed change: clip on code points and append `…`.
9. **`hip_new` on an untitled scene still offers `on_unsaved: 'save'` first.** The hint is "Pass on_unsaved: 'save' to save first, 'discard' to drop the changes, or call hip_save (with path for an untitled scene) first." That `save` then fails with "has nowhere to save it". Proposed change: when `hip.is_new`, lead with `hip_save {path}` or `discard`.
10. **Small inconsistencies:**
    - `houdini_status`:
      - It prints the hip path 5 times (`hip.path`, `hip.recent`, `env.HIP`, `env.JOB`, `instances[].hip`).
      - It has no `role` on `connected` or `instances`, though migration §4 says it adds one.
      - After a crash, the second warning repeats the first with "Houdini_connect" capitalized.
    - `instance_lost` says "pins one of the candidates" when none are live.
    - `inspect` results:
      - They lack the `what` and `target` keys that migration §1 promises.
      - `inspect type` with `parms` swaps `inputs` for `inputs_count`.
    - `typical_parents` appears on only some `search` rows.
    - The `undo history` note leaks "(review 22 finding 9)".
    - The `edit set` row doesn't echo the value written.

## Five things that work well

1. **`edit` is the right primitive.**
   - The 5-node chain and its layout took one call, 588 B and one undo step, on the first try.
   - The scatter/copy branch took 290 B.
   - A `create` plus `build` reproduced a network exactly in one call.
   - `$id` wiring, `dry_run` with every problem in one answer, and rollback by default make "plan, validate, apply" a two-call loop.
2. **The migration refusals are a model for the rest of the server.** `node_connect`, `node_info` and `viewport_capture` each answer `invalid_argument` with the 2.0 replacement and the `compat_1x` escape. The flat `parm_set` now gets the exact wrapped call in its hint, which fixes 1.3's #1 papercut.
3. **`inspect` folds eleven reads into one schema without losing any.** `frame` on `parms` and `geo` reads values at any frame with no `time` call (2.4 / 4.8, no float noise). `rows: true` pages geometry. The type reads keep `folders` and parm globs. Each result costs the same as its 1.4 counterpart.
4. **`look` just works and is side-effect free.** It needs no source to pick, falls back through a reported `chain`, and frames the target. It left the scene clean, `/out` empty and the undo history unchanged. A warm look took 0.45 s. `render` now explains a missing camera.
5. **1.3's correctness bugs are fixed, and recovery is unchanged.**
   - Redo skips a rolled-back `houdini_python` and says why.
   - A made-up job id gets an accurate `job_not_found`.
   - Both crash codes still carry a pasteable `houdini_connect {launch: {..., hip}}`.
   - The instructions, the guide and the prompts are consistent with the 2.0 surface.

---

## Verdict

**Not yet. Ship after a small fix.** The bar was ≥ 1.3's score on every dimension, plus fewer calls and bytes:

- **Calls and bytes: met.**
  - Round trips: 111 against 122.
  - Wire bytes: 435.6 KB against 458.1 KB.
  - Model text: 52.6 KB against 57.7 KB.
  - `tools/list`: 20.5 KB against 30.7 KB.
  - The change paths roughly halve, and the read paths hold even.
- **Scores: missed on one dimension.**
  - 2.0 scores 4 / 5 / 5 / **4** / 5 / 5, against 1.3's 4 / 5 / 5 / **5** / 5 / 5.
  - Error quality dropped because the 2.0 server's own hints name 1.4 tools that `core` refuses (papercut 1), and because the argument rename isn't suggested (papercut 2).
  - Each is a string or table change on the error path; none touches the engines.

Before tagging, fix papercuts 1–5. They are message text plus a version bump. Add a test that cross-checks every hint against the active profile's tool list. Then re-run task 9 (36 calls, a few minutes). If those messages are clean, error quality returns to 5, discoverability arguably reaches 5, and 2.0 clears the bar on every dimension with fewer calls and bytes.

### Reproduction notes

- Scratch dir (session scratchpad `r25/`):
  - a venv with `hocuspocus` installed editable
  - `tee.py` (a byte-counting stdio proxy around `hocuspocus-mcp.exe`) and `wire.jsonl`
  - `driver.py` (one long-lived `mcp.Client` session fed from an inbox directory) and `c.py` (one request)
  - `calls.jsonl` / `calls_merged.json`, with each call's arguments, ms, text and wire bytes
  - `outbox/`, which has every result and the PNGs
- Env:
  - `HOCUSPOCUS_STATE_DIR=<scratch>/state`
  - `HOCUSPOCUS_WORK_DIR=<scratch>/work`
  - `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, with no `hocuspocus.toml`
  - `HOCUSPOCUS_PROFILE` unset, so the profile was `core`
- Ports: the hosts took ephemeral ports (61031, 52751 and one more). Port 37219 was never used.
- Processes: three hython processes were launched through `houdini_connect` (pids 56120, 10388, 52428). The first two were killed deliberately for task 12. The third exited with the bridge when the driver closed its session. No other process was touched.
- Edits: no repo file other than this report was edited, and nothing was written to `~/houdini22.0` or `Documents/houdini22.0`.
