> **Status: evaluation record.** HocusPocus 1.3.0, scored from branch `release/1.4` at `32450ef` on 2026-10-13. See [`../README.md`](../README.md).

# 21 — Scorecard re-run: the review 07 tasks against 1.3.0

**Reviewer seat:** an independent agent with only the MCP surface (the `server/discover` instructions, `tools/list`, the `hocuspocus://guide` and `hocuspocus://tools` resources, and error messages) plus `README.md` and `docs/quickstart.md`. I did not read the server source. The one other repo file I read was `tests/e2e/test_stdio_roundtrip.py`, for the client pattern.
**Build:** `hocuspocus 1.3.0` (bridge and host), installed with `uv pip install -e .` into a scratch venv.
**Host:** Houdini 22.0.466 `hython`, headless, launched *by the agent* through `houdini_connect {"launch":{"mode":"headless"}}` from one long-lived client session. The scratch dir held `HOCUSPOCUS_STATE_DIR`, `HOCUSPOCUS_WORK_DIR` and `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, with `profile = "full"` in `prefs/houdini22.0/hocuspocus.toml`. The bridge also had `HOCUSPOCUS_PROFILE=full`.
**Transport:** the official `mcp` 2.3 client (`mcp.Client` + `StdioServerParameters`) talking to `hocuspocus-mcp` through a byte-counting stdio tee. The handshake is `server/discover`, as in review 07. Every call was logged with bytes and timing.
**Totals:** 122 JSON-RPC round trips and 458,109 response bytes on the wire. Of that, 250 KB is three PNGs and 65 KB is the two opt-in reference resources.

Byte counts are measured on the wire unless marked *text*. *Text* means the tool result's JSON text block, which is what the model reads. Since 1.1 the default `result_content = "text"` sends the JSON **once**, so the 2× duplication from review 07 is gone. Each response still carries about 500 B of envelope and `_meta` (see papercut 9). Token estimates are `bytes / 4`.

---

## 0. Getting a host up: 2 calls

```
houdini_status {}                                 174 B text  "No Houdini with HocusPocus is running; houdini_connect {launch: {mode}} starts one."
houdini_connect {"launch":{"mode":"headless"}}  1,398 B text  7.5 s (cold); pid, ui:false, hip .../work/untitled.hip,
                                                              "note":"$HIP is the launch directory until you hip_save.",
                                                              launched.outlives_server:false + a note saying to hip_save
```

`$HIP` and `$JOB` now point at `HOCUSPOCUS_WORK_DIR`, not at the state dir (review 07 papercut 3 is fixed). The launch result also says that this Houdini closes when the server exits. That is the one lifetime fact an agent needs. The cold launch took 7.5 s. The two later relaunches took 1.5 s each.

## 1. Discover: 6 calls, 7.7 KB (+33.5 KB handshake)

| Call | Bytes (wire) | Notes |
|---|---:|---|
| `server/discover` | 2,778 | Instructions are now ~2.4 KB. New: pinning, `instance_lost`, launch lifetime, `node_type_info` globs, `houdini://outline` |
| `tools/list` (full profile) | 30,679 | **35 tools, ~7.7k tokens, no `outputSchema`.** 1.0 had 37.3 KB for the same profile |
| `houdini_status` | 1,293 text | In 1.0 this was 2.6 KB. Adds `memory`, `read_only`, `allow_python`, `busy`, `jobs_running` |
| `node_find {"root":"/"}` | 1,048 text | 9 manager roots with `child_count` |
| `houdini://outline` | 1,015 | The whole scene as a tree. After task 6 it was 1.6 KB, with display nodes and flags |
| resources / templates / prompts lists | ~3.5 KB | 4 resources, 5 templates, 4 prompts |

Friction: `houdini_status` still prints the hip directory four times (`hip.path`, `env.HIP`, `env.JOB` and `instances[].hip`).

## 2. Build geo → box → mountain → subdivide → null OUT: 2 calls, 1.1 KB text

I built the chain from the instructions alone. This time I used the reader-side spelling `{"expression": ...}`, which 1.0 rejected:

```json
node_create {"items":[ ... {"parent":"/obj/terrain","type":"mountain","name":"mountain1",
   "parms":{"height":0.5,"offsetx":{"expression":"$F*0.1"}},"inputs":[{"index":0,"from":"/obj/terrain/box1"}]}, ...
   {"parent":"/obj/terrain","type":"null","name":"OUT", ..., "flags":{"display":true,"render":true}}]}
→ 766 B text, 648 ms
  {"results":[... {"path":"/obj/terrain/mountain1","type":"mountain::2.0","errors":[],"cook_state":"cooked","deprecated":true,
    "notes":["Sop/mountain::2.0 is deprecated since Houdini 19.0. Its replacement is Sop/attribnoise::2.0. It still works for now."]} ...],
   "created":[5 paths],"dirty":true}
```

- **It worked on the first try.** It took 766 B, where 1.0 needed 6,078 B. Both expression spellings are now accepted (review 07 papercut 4 is fixed).
- The result has a new deprecation note. It names the modern replacement for the node the Tab menu still creates.
- **`dirty` is returned by every mutating call** (review 07 papercut 9 is fixed).
- `node_layout` (301 B) stacked the chain top to bottom, as in 1.0.

## 3. Read back: 6 calls, 3.1 KB text

| Call | Text bytes | What came back |
|---|---:|---|
| `node_info` mountain1 + OUT | 1,153 | type with `help_url`, flags, labelled inputs, non-default parms with value, raw and expressions, `errors`, `warnings`, `messages`, `cook_state`, **`hda_locked`** (the `locked` ambiguity is resolved) |
| `parm_get` offset, height | 504 | `kind:"tuple"`, `component_names`, `expressions`, `is_default`, `locked`, `hda_locked` |
| `cook` OUT | 142 | `ok`, `cook_time_ms` |
| `geo_info` OUT | 470 | 26/24/96, bbox, prim types, typed attributes, groups. In 1.0 this was 1.3 KB |
| `geo_read` OUT P, 5 rows | 301 | rows plus `next_cursor` |
| `network_describe /obj/terrain` | 489 | `childrenAsData` form, `"hda_locked": true` on mountain1 |

Every read call is now 30–60 % smaller than in 1.0 and carries the same facts.

## 4. Frame 24: 4 calls, 1.0 KB text

`time {"frame":24}` returned 62 B. `parm_get offsetx` gave `"value":2.4`, and at `frame: 48` it gave `"value":4.8`. **The float noise is gone** (1.0 printed `2.4000000000000004`). `geo_info` at frame 24 showed the bbox shifted.

## 5. Save and dirty: 12 calls (2 of them failed), 11.7 KB wire

```
hip_save {"path":".../work/hips/friction.hip"}   → path, dirty:false, bytes:88568 (directory created)
parm_set {"path":".../height","value":0.7}       → invalid_argument: "items: required property is missing; path: unknown property
                                                    (allowed: items, frame, partial); value: unknown property ..."     ← papercut 1
parm_set {"items":[{"path":".../height","value":0.7}]}  → value 0.7, "dirty":true
hip_save {}                                     → dirty:false
houdini_status                                  → hip.dirty false, hip.recent now lists friction.hip
```

The save and dirty cycle is right on every surface, and `hip.recent` now fills in. The one stumble was mine, and the docs led me into it: I wrote `parm_set` as a single `{path, value}`, the form review 07 used against 1.0 and the form the guide's spare-parm recipe still shows. 1.3 requires the `items` array. The error lists the violations correctly, but it never shows the expected shape.

## 6. Scatter + copy sphere: 10 calls, 13.0 KB text

```
node_type_search "scatter" (Sop, 5)                     → #1 scatter::2.0 (current, other_versions:["scatter"])    1,685 B
node_type_search "scatter points on a surface" (5)      → #1 scatter::2.0, #2 scatteralign                         1,687 B
node_type_search "copy to points" (Sop, 5)              → #1 copytopoints::2.0                                     1,527 B
node_type_info Sop/scatter (compact)                    → 3,032 B: all parms as rows [name,label,type,default], npts present
node_type_info Sop/scatter detail:"folders"             →   677 B: 3 folders with counts
node_type_info Sop/scatter parms:"*count*|npts"         →   684 B: forcetotal, npts, primcountattrib
node_type_info Sop/copytopoints include_parms:false     →   573 B: inputs "Geometry to Copy", "Target Points to Copy to"
node_create scatter(npts 200) ← OUT; sphere(scale .05); copytopoints[0]←sphere,[1]←scatter, display → 410 B, first try
geo_info copy1                                          → 200 pts, prim_types {"sphere":200}
```

**Both of review 07's discovery papercuts are fixed.** The natural-language query now ranks `scatter::2.0` first, where 1.0 had it fourth behind `relax` and `hairgen`. `node_type_info` has a compact default (3 KB, where 1.0 needed 12.6 KB), a folder overview and a parm glob filter. The instructions point at the filter.

Friction:
- A clipped description contains a U+FFFD replacement character (`"...limit the effect of other nodes to areas tha�"`, on `maskbyfeature`).
- With a `parms` filter, `node_type_info` swaps the labelled `inputs` list for a bare `inputs_count`.
- `typical_parents` appears on some search rows and not on others.

## 7. Arbitrary hou Python: 5 calls, 1.1 KB text

```
houdini_python {hipFile.name, len(points), point(0), n.errors()} → stdout + result {"pts":200,...,"errors":[]}
houdini_python "len(hou.node('/obj/terrain').children())"        → {"result":7}
houdini_python "echo $HIPNAME; opls /obj/terrain" (hscript)      → stdout "friction\nbox1\n..."
houdini_python "createNode('geo','pyjunk')\n1/0"
  → isError:true, code python_exception, "ZeroDivisionError: division by zero",
    hint "...the call's undo step was rolled back (detail.rolled_back says whether that worked)...", detail.traceback
```

**Exceptions are now `isError:true` and roll back their partial changes**: `pyjunk` was gone afterwards. Review 07 flagged `isError:false` here.

New problem: the rolled-back step stays on the **redo** stack. `undo {"action":"history"}` lists `redo: ["HocusPocus: houdini_python hou.node(\"/obj\").createNode(\"geo\",\"py..."]`. After a second failing call, `undo {"action":"redo"}` **re-created `/obj/pyjunk2`**, the side effect of code that had raised (papercut 2). The next mutation clears the redo stack, so the window is narrow.

## 8. Visual: 12 calls, 256.9 KB (three PNGs)

```
viewport_capture {}                       → 144,857 B wire, 3.2 s; text 405 B: camera_used "temporary", fit_used "all", source_used "opengl_rop"
viewport_capture {"resolution":[512,384]} →  52,286 B, 2.8 s; 200 grey spheres, framed correctly
houdini_status → dirty:false;  node_find /out → [];  undo history → no capture steps
```

**Capturing is now read-only.** It leaves no camera or ROP behind, adds no undo step and doesn't change the dirty flag (review 07 papercut 2 is fixed; the tool description says so).

`render`:
- `node_create /out opengl` returned a note that `Driver/opengl is deprecated since Houdini 22.0: Replaced by the Flipbook ROP`, and `node_type_search flipbook` finds it.
- The first `render` failed: `cook_failed "/out/gl failed to render: No camera specified for render."`, with **no hint**. The ROP's `camera` parm defaults to `/obj/cam1`, which didn't exist.
- After I created `/obj/cam1`, `render {"frames":[1,3]}` returned all three outputs. It also returned a thumbnail as image content, a note that the scene has no lights, `job_id` and `state:"done"`, in 2.9 s.

The default capture is still 1024×768, about 145 KB per look.

## 9. Deliberate mistakes: 37 calls, 27.6 KB wire

| Mistake | Response (trimmed) | Verdict |
|---|---|---|
| `node_create type:"mountian"` | `node_type_not_found`, "Closest Sop types: mountain, mpmcontainer", `rolled_back:true` | Excellent (unchanged) |
| `parm_set box1/sizee` | `parm_not_found` "Did you mean size? It is a tuple: ... or a component (sizex/sizey/sizez)" | Excellent (unchanged) |
| `node_create box parms:{sizee:3}` | same hint, scoped to `parms.sizee` | Excellent |
| `node_connect {from,to,to_input}` (flat) | `invalid_argument` "items: required property is missing; from: unknown property (allowed: items, partial)..." | OK: correct, but no example of the expected shape (papercut 1) |
| `node_connect ... to_input:5` | "it has no input 5 (it takes 2)." + labelled input list | Excellent |
| `to_input:"points"` | "no input named 'points'", candidates `input2, input1` | Good |
| `from:"/obj/terrain/nope"` | `node_not_found` "items[0] (/obj/terrain/copy1): No node at /obj/terrain/nope." hint **"Check the node name."**, candidates `["/obj/terrain/copy1"]` | **Worse than 1.0**: the prefix names the `to` node, the candidate is the target rather than a near-miss, and the "list children with node_find" hint is gone (papercut 4) |
| `node_info /obj/terrain/OUTT` | candidates `["/obj/terrain/OUT"]`, "Check the node name." | Good (1.0's "paths are case-sensitive" wording is gone) |
| `type:"geo"` in a SOP net | "geo is **an** Object node type, but /obj/terrain holds Sop nodes." | Grammar fixed. The 8 candidates are noise (`heatgeodesic`, `rop_geometry`, `topnet`, ...) |
| `geo_info {"node_path":...}` | "node_path: unknown property; did you mean path?" | Excellent |
| `items` as an object | "items: expected array, got object {...}" | Good |
| `height = "tall"` | `invalid_value` "it is a float parm; got 'tall'." + hint naming both expression spellings + range | Excellent (the duplicated path is gone) |
| `size = [1,2]` | "it has 3 components; got 2 values." "Components: sizex, sizey, sizez." | Good |
| `generateby = "Count"` | tokens and labels, candidates | Good |
| unknown tool `node_creat` | `-32602` "Unknown tool: node_creat. **Did you mean node_create or node_edit or node_connect?**" | Fixed |
| expression `"$F*("` | `isError:false`, `errors:["Unable to evaluate expression (Bracing error ...)"]`, `cook_state:"error"` | Good |
| `geo_info box1` (errored) | `cook_failed` with Houdini's text and "see also the problems tool" | Good |
| `problems /obj` | **one** entry for box1 (1.0 listed it twice) | Fixed |
| **fix, then re-read** | `parm_set sizex revert_to_default` → `errors:[]`, `cook copy1` → `ok:true`, `problems` → `[]` + "No problems under /obj" | **Fixed.** This was review 07's #1 papercut. No `force` needed |
| `hip_open .../nope.hip` | `file_not_found`, candidates `[".../friction.hip"]` | Good |
| `viewport_capture camera:"/obj/nocam"` | `node_not_found`, candidates `["/obj/cam1"]` | Good |
| `cook {..., "bogus":1}` | lists the allowed arguments | Good |
| `job status "123-abc"` | `instance_lost` "**Job 123-abc ran in Houdini pid 123 (houdini), which has exited**; its jobs are gone." | **Misleading**: a made-up id is reported as a dead Houdini (papercut 3) |
| `job status "46936-zzzz"` | `job_not_found` + an exact explanation of job id scoping | Excellent |

## 10. tools/list and the reference resources

- **35 tools (full profile), 30,679 B, about 7.7k tokens.** In 1.0 the full profile was 37.3 KB and core was 34.6 KB; review 06 had 99.7 KB. With `outputSchema` dropped, the list is under review 06's 8k-token target for the first time, even on `full`. The largest entries are `node_create` (2.7 KB) and `parm_set` (2.2 KB).
- Every description is one paragraph that states what the tool does and routes to its siblings ("parm_get reads keyframes, menus and templates; network_describe a whole network"). The names haven't changed since 1.0.
- `hocuspocus://guide` shrank to 6.4 KB (from 37.5 KB). It now holds the instructions, a resource map and three recipes, and the full reference moved to `hocuspocus://tools` (55.8 KB, labelled "large"). **One guide recipe uses the flat `parm_set {path: ..., expression: ...}` form, which the schema rejects** (papercut 1).
- Resources: 4 static ones and 5 templates, no duplicate aliases. Prompts: 4.

## 11. `hip_new` with unsaved changes: 7 calls, 1.8 KB text

```
hip_new {}                    → unsaved_changes, hint "Pass on_unsaved: 'save' ..., 'discard' ..., or call hip_save (with path for an untitled scene) first."
hip_new {"on_unsaved":"save"} → saved_first:true, scene_generation:1
node_create scratchgeo; hip_new {} → unsaved_changes, the same hint (offers 'save' for an untitled scene)
hip_new {"on_unsaved":"save"} → unsaved_changes "The scene is untitled, so on_unsaved: 'save' has nowhere to save it." hint "Use hip_save with path first, or on_unsaved: 'discard'."
hip_new {"on_unsaved":"discard"} → scene_generation:2; node_find /obj → []
```

Safe by default, as in 1.0. Since the capture fix, `save` no longer writes stray nodes into the user's file. The hint for an untitled scene still offers `'save'` first, and that option then fails (papercut 7).

## 12. Kill Houdini, call, relaunch: 9 calls, 10.9 KB wire

```
taskkill 46936
node_find /obj  → instance_lost: "The pinned Houdini pid 46936 (hython) has exited; changes made in it since its last save are lost.
                  Not switching to another Houdini on its own. Live: none is running." retryable:false
houdini_status  → connected:null, lost:{pid:46936}, the same text as a warning
houdini_connect {launch:{headless, hip:friction.hip}} → pid 47580 in 1.5 s, dirty:false; geo_info copy1 → 200 pts
```

**Killed mid-call:** a `houdini_python` that creates a node and then sleeps 8 s, with hython killed after 3 s:

```
→ houdini_offline: "The Houdini you were driving (pid 47580) exited while running houdini_python; changes made in it since its
   last save are lost." retryable:false,
   hint "houdini_connect {launch: {mode: 'headless', hip: '.../friction.hip'}} reopens its last saved scene; repeating the call
   without that cannot work."  detail.transport keeps the ConnectionResetError
next call → instance_lost, its hint includes the same ready-to-run launch call
houdini_connect launch → pid 65360 in 1.5 s
```

This is review 07 papercut 8, fully addressed: the message names the dead process, says what was lost, sets `retryable:false`, and the hint is a call the agent can paste.

Remaining nits:
- The same event gets two codes: `houdini_offline` mid-call, then `instance_lost`.
- The `instance_lost` hint says "pins one of the candidates" when there are none.
- `houdini_status` repeats the message as a second warning, with the tool name capitalized ("Houdini_connect {pid} ...").

Extra: `network_describe /obj/terrain` (793 B) → `network_build` into `/obj/t2` (868 B) rebuilt all 7 nodes with identical geometry, on the first try.

---

## Per-task totals

| Task | Calls | Wire bytes | First-try success? |
|---|---:|---:|---|
| handshake (`server/discover` + `tools/list`) | 2 | 33,457 | — |
| 0 host up | 2 | 2,302 | yes |
| 1 discover | 6 | 7,723 | yes |
| 2 build + layout | 2 | 2,042 | yes (1 call) |
| 3 read back | 6 | 5,733 | yes |
| 4 frame 24 | 4 | 2,645 | yes |
| 5 save / dirty | 12 | 11,747 | no: 2 `parm_set` calls rejected for the flat shape |
| 6 scatter + copy | 10 | 16,417 | yes (build in 1 call) |
| 7 python | 5 | 4,475 | yes |
| 8 visual | 12 | 256,872 (3 images) | capture yes; `render` failed once (no camera, no hint) |
| 9 mistakes | 37 | 27,576 | n/a |
| 10 guide + tools reference | 2 | 65,126 | — |
| 11 hip_new | 7 | 4,541 | yes |
| 12 kill + recover | 9 | 10,898 | yes |
| extra: describe → build round trip | 6 | 6,555 | yes |
| **Total** | **122** | **458,109** | |

The model-visible text of all 112 tool results, excluding images, `tools/list` and the two reference resources, is **57.7 KB, about 14.4k tokens**. 1.0 needed about 14k tokens for 102 calls; this run made 20 more calls (mostly extra mistakes) in the same budget. The wall clock from client connect to a verified 5-node chain was 41 s, including the 7.5 s cold launch and my own think time.

---

## Scorecard (1 = poor, 5 = excellent; definitions as in review 07)

| Dimension | 0.9 | 1.0 | 1.3 | Why (1.3) |
|---|:---:|:---:|:---:|---|
| Discoverability | 2 | 4 | **4** | Every 1.0 holdback is fixed: the natural-language query ranks `scatter::2.0` first, `node_type_info` has a 3 KB compact default plus `folders` and parm globs, and `tools/list` is 7.7k tokens on `full` with no `outputSchema`. The instructions route to `houdini://outline` and the globs. It stays at 4 because the batch-only shapes of `parm_set` and `node_connect` appear nowhere in the instructions, and the guide shows a flat `parm_set` the schema rejects. Writing the call from the docs cost me two failed calls. |
| Idiom match with Houdini vocabulary | 2 | 5 | **5** | Unchanged strengths, plus deprecation notes that name the modern node (`mountain::2.0` → `attribnoise::2.0`, `opengl` → Flipbook), `hda_locked` separated from the lock flag, both expression spellings accepted, HScript in `houdini_python`, and `undo` labels per tool. |
| Verbosity / token cost | 1 | 4 | **5** | JSON is sent once (`result_content: text`). Building 5 nodes costs 766 B (1.0: 6 KB), `geo_info` 470 B (1.0: 1.3 KB), `houdini_status` 1.3 KB (1.0: 2.6 KB), and scatter type info 3 KB or 684 B filtered (1.0: 12.6 KB). The whole run was ~14k model tokens. Remaining cost: 145 KB default captures and ~500 B of `_meta` and envelope per response. |
| Error quality | 3 | 4 | **5** | All of 1.0's holdbacks are gone. Fixed errors clear without `force`, and `problems` lists each error once. Unknown tools get "did you mean". Python exceptions are `isError` with rollback. A crash names the pid, says what was lost, and offers a launch call with the hip path. Every deliberate mistake got a code, hint and candidates. The new flaws are smaller and none of them sends the agent the wrong way for more than one call: a vaguer `node_not_found` hint, a bogus job id reported as a dead Houdini, and a hint-less `render` "No camera". |
| Number of concepts to learn | 1 | 5 | **5** | Still node path, parm/tuple/component path, undo step, `on_unsaved`, job, `scene_generation`. Pinning and `instance_lost` only show up with two Houdinis. |
| Time to first success | 1 | 5 | **5** | 2 calls to a host (7.5 s cold, 1.5 s warm). The first build call succeeded with either expression spelling. 41 s from connect to a verified chain. |

**1.3: 4 / 5 / 5 / 5 / 5 / 5**, against 1.0's 4 / 5 / 4 / 4 / 5 / 5 and 0.9's 2 / 2 / 1 / 3 / 1 / 1.

---

## The 10 worst remaining papercuts

1. **`parm_set` and `node_connect` accept only `{"items":[...]}`, and the docs don't show it.**
   - The flat `{path, value}` and `{from, to, to_input}` forms fail with "items: required property is missing; path: unknown property". Review 07 used those forms against 1.0, and the instructions ("Change values with `parm_set`; ... expressions go in `expression`") read as if they work.
   - `hocuspocus://guide` §"Add a spare parm" literally shows `parm_set {path: "/obj/geo1/rbd1/strength", expression: '...'}`.
   - Fix: either accept a single item at the top level, or put the shape in the hint (`wrap it: {"items":[{"path":..., "value":...}]}`), and correct the guide.
2. **Redo resurrects a rolled-back `houdini_python`.**
   - After a `python_exception` rollback, the failed step sits on the redo stack under a truncated label (two failed calls look identical).
   - `undo {"action":"redo"}` re-ran it: it re-created `/obj/pyjunk2` from code that had raised.
   - Fix: drop the step from the redo stack after rollback, or at least leave it out of `history.redo` and refuse to redo it.
3. **A malformed job id is reported as a dead Houdini.** `job {"action":"status","job_id":"123-abc"}` returns `instance_lost` with "Job 123-abc ran in Houdini pid 123 (houdini), which has exited; its jobs are gone." Nothing ever ran there. If no registry entry ever had that pid, say `job_not_found` (the good message that `46936-zzzz` gets).
4. **`node_not_found` hints regressed.**
   - Message: `node_connect` with a missing `from` returns "items[0] (/obj/terrain/copy1): No node at /obj/terrain/nope." The prefix names the *target*.
   - Hint: "Check the node name."
   - Candidates: `["/obj/terrain/copy1"]`, the target itself rather than a near-miss sibling.
   - 1.0 said "/obj/terrain exists; list its children with node_find root='/obj/terrain'", which is more useful.
5. **`render` "No camera specified" has no hint.**
   - A fresh OpenGL ROP points at `/obj/cam1` by default. When that camera doesn't exist, `render` returns a bare `cook_failed`.
   - Fix: a hint that names the ROP's `camera` value and that it doesn't exist, plus "create a camera, or use `viewport_capture` for a quick look".
6. **Clipped descriptions in `node_type_search` contain U+FFFD** (`"areas tha�"` on `maskbyfeature`). The clip cuts inside a multibyte sequence. Clip on characters, then add the ellipsis.
7. **The `hip_new` hint on an untitled scene offers an option that cannot work.** The first `unsaved_changes` hint lists `on_unsaved: 'save'` first, and that call then fails with "has nowhere to save it". When the scene is untitled, lead with `hip_save {path}` or `discard`.
8. **`houdini_status` still prints the hip directory four times** (`hip.path`, `env.HIP`, `env.JOB`, `instances[].hip`), about 600 of its 1.3 KB with a long scratch path. After a crash it adds a second, near-duplicate warning with the tool name capitalized ("Houdini_connect {pid} ...").
9. **Per-response overhead and image size.**
   - Every result carries a `_meta` block (serverInfo, instance, pid, scene_generation, undo label, elapsed): ~500 B of wire per call, more than many payloads (a 62 B `time` result).
   - The default `viewport_capture` is still 1024×768, about 145 KB.
   - A 512 px default (or `resolution` mentioned in the instructions) would cut most visual cost.
10. **Small inconsistencies:**
    - With a `parms` filter, `node_type_info` swaps the labelled `inputs` list for `inputs_count`.
    - `typical_parents` appears on only some `node_type_search` rows.
    - `type:"geo"` in a SOP network returns 8 noise candidates (`heatgeodesic`, `rop_geometry`, `topnet`, ...) under a correct hint.
    - A mid-call kill is `houdini_offline`, while the next call on the same dead instance is `instance_lost`.
    - The `instance_lost` hint offers to "pin one of the candidates" when none are live.
    - The cold launch took 7.5 s, against 1.5 s warm.

## Five things that work well

1. **One-call builds in Houdini terms, now smaller.** `node_create` built the five-node chain and, separately, the scatter/copy branch on the first try. It returned 766 B and 410 B, per-node errors and cook state, `dirty`, and a deprecation note with the replacement type. Both expression spellings work.
2. **Reads are compact and exact.** `node_info`, `parm_get` (component names, expressions, values at any frame, with no float noise), `geo_info` (470 B), `geo_read` (paged rows) and `network_describe` (489–793 B, which `network_build` takes back verbatim). `hda_locked` ends the `locked` ambiguity.
3. **The error loop is closed.** Fixing a node clears its errors everywhere, with no stale state and no `force`. `problems` lists each error once. Every tested mistake returned a code, a hint and candidates; that includes an unknown tool name and Python exceptions, which now roll back.
4. **Looking is side-effect free, and headless works fully.** `viewport_capture` leaves no nodes, no undo step and no dirty flag. `$HIP` is a real work directory. `render` returns every output and a thumbnail. Crash recovery is one pasteable `houdini_connect {launch, hip}`, and the error says exactly what was lost.
5. **The surface is small and fits in context.** 35 tools in 7.7k tokens on the `full` profile. Results are text-only JSON. A 6.4 KB guide is separate from the 56 KB reference, which is labelled as large and opt-in. Instructions route to the cheap paths (`houdini://outline`, `node_type_info` globs).

---

## Verdict

1.3.0 scores **4 / 5 / 5 / 5 / 5 / 5**. That clears the BIBLE §14 M5 bar (≥ 4 everywhere) with more margin than 1.0, which scored 4 / 5 / 4 / 4 / 5 / 5:
- Verbosity rose because of single-copy results and smaller reads.
- Error quality rose because review 07's #1 papercut (stale errors) and #8 (crash messages) are fixed.
- Ten of review 07's top-10 papercuts are fixed or reduced. The exception is #9 (the repeated hip path in `houdini_status`).

Ranked by how they mislead an agent, the issues to fix for 1.4:
1. **The `items`-only shape vs. the guide's flat example** (papercut 1). It's the only reason discoverability stayed at 4, and the only first-try failure on the core build path.
2. **Redo of a rolled-back Python step** (papercut 2), the one correctness issue found.
3. **The made-up-job-id `instance_lost`** (papercut 3), the one message that states something false.

### Reproduction notes

- Scratch dir (session scratchpad `r21/`):
  - a venv with `hocuspocus` installed editable
  - `tee.py` (a byte-counting stdio proxy around `hocuspocus-mcp.exe`) and `wire.jsonl`, which has every JSON-RPC line with its byte count
  - `driver.py` (one long-lived `mcp.Client` session fed from an inbox directory) and `calls.jsonl`, which has each call's arguments, ms and bytes
  - `outbox/`, which has every result and the PNGs
- Env:
  - `HOCUSPOCUS_STATE_DIR=<scratch>/state`
  - `HOCUSPOCUS_WORK_DIR=<scratch>/work`
  - `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, with `profile = "full"` in `prefs/houdini22.0/hocuspocus.toml`
  - `HOCUSPOCUS_PROFILE=full`
- Ports: the hosts took ephemeral ports 54056, 65513 and 49162. Port 37219 was never used.
- Processes: three hython processes were launched through `houdini_connect` (pids 46936, 47580, 65360). The first two were killed deliberately for task 12. The third exited with the bridge when the driver closed its session. No other process was touched.
- Edits: no repo file other than this report was edited, and nothing was written to `~/houdini22.0` or `Documents/houdini22.0`.
