# 07 — Friction re-run: driving HocusPocus 1.0 as an agent

**Reviewer seat:** a fresh AI agent with only the MCP surface (the `server/discover` instructions, `tools/list` descriptions and schemas, and error messages) plus `README.md` and `docs/quickstart.md`. I did not read the server source. The one repo file I read besides those was `tests/e2e/test_stdio_roundtrip.py`, to see the client pattern.
**Build:** `redesign/v1` @ `3a0df8a`, `hocuspocus 1.0.0a0`, bridge installed with `uv pip install -e .` into a scratch venv.
**Host:** Houdini 22.0.466 `hython`, headless, launched *by the agent* through `houdini_connect {"launch":{"mode":"headless"}}`. `HOCUSPOCUS_STATE_DIR` and `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__` pointed into my scratch dir, and Houdini created `prefs/houdini22.0` there as intended.
**Transport:** the official `mcp` 2.3 client (`mcp.Client` with `StdioServerParameters`). It spoke to `hocuspocus-mcp` over stdio through a byte-counting tee. With this SDK the handshake is `server/discover` (protocol `2026-07-28`), not `initialize`, and the server's instructions arrive in that result.
**Date:** 2026-10-12. 102 JSON-RPC round trips, 455,482 response bytes on the wire, 305 KB of which are three PNG images.

Byte counts are measured on the wire. Token estimates use `bytes / 4`. Every tool result carries the payload twice, once as `content[].text` and once as `structuredContent` (see papercut 7). A model normally reads only one copy, so model-visible cost is about half of what the wire shows.

---

## 0. Getting a host up

Review 06 spent about 45 minutes here. This time it took **two calls and about 1.5 s**:

```
houdini_status {}                       →   667 B  {"connected":null,"instances":[],"profile":"core",
                                                     "warnings":["No Houdini with HocusPocus is running;
                                                     houdini_connect {launch: {mode}} starts one."]}
houdini_connect {"launch":{"mode":"headless"}}
                                        → 2,329 B  {"connected":{"pid":14836,"port":59341,"houdini":"22.0.466",
                                                     "ui":false,"hip":{"name":"untitled.hip","dirty":false,...}},
                                                     "launched":{"mode":"headless","pid":14836,"log":"...launch-headless-...log"}}
```

There was no installer step, no version pin, no MAX_PATH journal and no token file to find. The host did not touch `C:\Users\jujun\houdini22.0`. Instance state stayed in my state dir, so I never saw any other agent's Houdini.

---

## 1. Discover the session — 4 calls, 8.3 KB (+36.3 KB handshake)

```
server/discover        1,735 B  instructions: ~1.3 KB of plain-English quickstart
tools/list            34,557 B  (~8.6k tok) 31 tools
houdini_status         2,639 B  pid, version, ui:false, hip path + dirty, $HIP/$JOB/$HIPNAME, frame/fps/range
node_find {"root":"/"} 2,631 B  the 9 manager roots with child_count
```

The instructions field is the quickstart review 06 asked for. It says start with `houdini_status`, build with `node_create`, read with `node_info`, look with `viewport_capture`, and use `houdini_python` when nothing else fits. It also explains `truncated`, `delivery_unknown` and `scene_generation`. The real hip path is shown everywhere, with no `<redacted>`. `dirty:false` on a fresh session is correct.

Friction:
- In `houdini_status`, the same long scratch path appears four times (`hip.path`, `HIP`, `JOB`, and `instances[].hip`), which is 2.6 KB for a status line.
- In an untitled headless session, **`$HIP` and `$JOB` point at the bridge's state directory**, the one that holds `instances/`, `logs/` and `captures/`. That happens because hython is launched with that directory as its cwd. The untitled hip is `.../state/untitled.hip`, so any `$HIP/render/...` output would land next to the registry.

Score: good. 3 useful calls to a full picture, roughly 2.5k tokens after the one-time list.

## 2. Build geo → box → mountain → subdivide → null OUT — 3 calls, 9.5 KB

**The first attempt worked.** I wrote it from the instructions and the `node_create` schema alone, with no type discovery:

```json
node_create {"items":[
 {"parent":"/obj","type":"geo","name":"terrain"},
 {"parent":"/obj/terrain","type":"box","name":"box1"},
 {"parent":"/obj/terrain","type":"mountain","name":"mountain1",
  "parms":{"height":0.5,"offsetx":{"expr":"$F*0.1"}},
  "inputs":[{"index":0,"from":"/obj/terrain/box1"}]},
 {"parent":"/obj/terrain","type":"subdivide","name":"subdivide1","inputs":[{"index":0,"from":"/obj/terrain/mountain1"}]},
 {"parent":"/obj/terrain","type":"null","name":"OUT","inputs":[{"index":0,"from":"/obj/terrain/subdivide1"}],
  "flags":{"display":true,"render":true}}]}
→ 6,078 B, 202 ms
 {"path":"/obj/terrain/mountain1","type":{"name":"mountain::2.0",...},
  "parms":[{"name":"height","value":0.5,"raw":"0.5"},
           {"name":"offset","value":[0.1,0.0,0.0],"raw":["$F*0.1","0","0"],
            "expressions":{"offsetx":{"expression":"$F*0.1","language":"hscript"}}}],
  "errors":[],"warnings":[],"cook_state":"cooked"} ...
```

- `mountain` resolved to `mountain::2.0`, as the Tab menu would. The `type` block says so.
- Setting a tuple component (`offsetx`) on a node created in the same call works. That was the bug that quarantined review 06's apply.
- One undo step, labelled `HocusPocus: node_create 5 nodes`.

`node_layout {"parent":"/obj/terrain"}` (1 KB) stacked the chain **top to bottom** (`box1` y=0.71, `mountain1` −0.42, `subdivide1` −1.55, `OUT` −2.68). That matches how a Houdini artist reads a network. Even without the explicit layout call, `good_position` placement on create had already put the nodes in a sensible spot.

Friction: none worth listing. The README example spells the expression form `{expr, lang}`, so I guessed it correctly (but see papercut 4).

## 3. Read back — 6 calls, 8.6 KB

| Call | Bytes | What came back |
|---|---|---|
| `node_info` mountain1 + OUT | 2,834 | type, flags, inputs **with labels** (`"Sub-Network Input #1"`), non-default parms with value, raw and expression, `errors`, `warnings`, `cook_state` |
| `parm_get` offset, height | 1,390 | `kind:"tuple"`, **`component_names:["offsetx","offsety","offsetz"]`**, value, raw, expressions, `is_default` |
| `cook` OUT | 654 | `ok:true`, `errors:[]`, `cook_time_ms` |
| `geo_info` OUT | 1,348 | 26 pts / 24 prims / 96 verts, bbox min/max/size/center, `prim_types`, attributes **with type and size**, groups, memory |
| `geo_read` OUT P, count 5 | 970 | `columns:["ptnum","P"]`, 5 rows, `total:26`, `next_cursor:5` |
| `network_describe /obj/terrain` | 1,405 | whole network in `childrenAsData` form, 411-byte `data` |

```json
geo_read {"path":"/obj/terrain/OUT","attribs":["P"],"count":5}
→ {"columns":["ptnum","P"],"rows":[[0,[-0.251755,-0.2690879,-0.2423149]],[1,[0.2823013,-0.2625347,-0.259744]],...],
   "start":0,"total":26,"next_cursor":5}
```

Every gap review 06 found is closed: node errors are on every node read, component names are listed, there is a value sampler, and a whole network costs 1.4 KB instead of 78 KB–2 MB. Cooking the locked `mountain::2.0` no longer pulls its internals into anything. `network_describe` reports it as `{"type":"mountain::2.0", ..., "locked":true}`.

Friction: minor. In `network_describe`, `"locked": true` means "HDA contents locked". In `node_info`, `flags.locked` means the node's lock flag. Same word, two meanings.

## 4. Frame 24 and re-read — 4 calls, 3.6 KB

```
time {"frame":24}                       → 480 B  {"frame":24,"fps":24,"range":[1,240],"playback_range":[1,240]}
parm_get mountain1/offsetx              → 858 B  {"value":2.4000000000000004,"raw":"$F*0.1","expression":"$F*0.1"}
parm_get mountain1/offsetx, frame 48    → 884 B  {"value":4.800000000000001, ..., "frame":48.0}
```

It works headless with no `Internal server error`, and `parm_get` can evaluate at any frame without moving the playbar. The only blemish is float noise (`2.4000000000000004`), which is harmless but adds tokens.

## 5. Save and dirty state — 8 calls, 12.3 KB

```
hip_save {"path":".../work/hips/friction.hip"}
  → {"path":"C:/.../work/hips/friction.hip","name":"friction.hip","dirty":false,"is_new":false,"bytes":88567}
houdini_status          → hip.dirty:false
parm_set height=0.5     → {"value":0.5, "errors":[], ...}            (no dirty field)
houdini_status          → hip.dirty:true
hip_save {}             → {"path":".../friction.hip","dirty":false,"bytes":88567}
houdini_status          → hip.dirty:false
```

All three surfaces agree on a real path. The directory was created, and the dirty flag goes false after a save and true after a change. That is exactly what review 06 asked for.

Friction:
- Mutating tools don't report the dirty state, so checking it costs a 2.6 KB `houdini_status`.
- `hip.recent` stayed `[]` after three saves and one load.

(Two of my `houdini_status` calls in this task failed inside my own test harness and never reached the server. They aren't counted.)

## 6. Scatter + copy sphere (discovery) — 8 calls, 35.5 KB

```
node_type_search {"query":"scatter","category":"Sop","limit":5}
  → #1 scatter::2.0 (is_current_version:true), #2 scatter (is_current_version:false, current:"scatter::2.0"),
    #3 scatteralign ...                                                        3,144 B
node_type_search {"query":"scatter points on a surface","limit":5}
  → relax, guidesurface, hairgen::2.0, scatter::2.0, scatteralign            2,951 B
node_type_search {"query":"copy to points","category":"Sop","limit":5}
  → #1 copytopoints::2.0 (current)                                           3,477 B
node_type_info {"type":"Sop/scatter"}         → 12,620 B: inputs labelled, all parms by folder, npts present
node_type_info {"type":"Sop/copytopoints"}    →  6,270 B: input 0 "Geometry to Copy", 1 "Target Points to Copy to"
node_create scatter(npts 200) ← OUT; sphere(scale .05); copytopoints[0]←sphere,[1]←scatter, display  → 4,311 B
geo_info copy1 → point_count 200, prim_types {"sphere":200}
node_layout    → sphere to the left, copy1 below both
```

Searching by name is fixed: `scatter` is now #1 instead of #68, and the current version is marked. The type info lists named inputs, so wiring copy-to-points correctly needed no guessing. The build itself was one call and worked first try.

Friction:
- A natural-language query still ranks `relax` and `hairgen` above `scatter::2.0`.
- `node_type_info` has no "common parms" view. Scatter costs 12.6 KB (~3k tokens) to find `npts`, and the only filter is `folder`.

## 7. Arbitrary hou Python — 4 calls, 3.1 KB

```
houdini_python {"code":"n = hou.node(\"/obj/terrain/copy1\")\nprint(hou.hipFile.name())\ng = n.geometry()\n
                         result = {\"pts\": len(g.points()), \"first\": list(g.point(0).position()), \"errors\": n.errors()}"}
  → {"stdout":"C:/.../friction.hip\n","stderr":"","result":{"pts":200,"first":[0.4557,0.1454,-0.0104],"errors":[]}}
houdini_python {"code":"len(hou.node(\"/obj/terrain\").children())"}       → {"result":7}
houdini_python {"code":"echo $HIPNAME; opls /obj/terrain","language":"hscript"} → stdout "friction\nbox1\n..."
houdini_python {"code":"1/0"}
  → isError:false, {"exception":{"type":"ZeroDivisionError","message":"division by zero","traceback":"..."}}
```

The escape hatch exists, is advertised in the instructions, returns a trailing expression as `result`, and supports HScript too. A Python exception comes back as `isError:false` with an `exception` block. That is defensible, since the tool itself did run, but an agent that only checks `isError` will miss it.

## 8. Visual — 8 calls, 232.8 KB (three PNGs)

```
viewport_capture {}                         → 145,283 B, 4.2 s (first OpenGL in a fresh hython)
   content: [image/png 1024×768] + {"path":".../state/captures/capture_...png","camera_used":"/obj/hocuspocus_capture_cam",
                                    "fit_used":"all","source_used":"opengl_rop"}
viewport_capture {"resolution":[512,384]}   →  52,709 B, 3.3 s  (image showed 200 grey spheres, framed correctly)
render {"rop_path":"/out/gl","frames":[1,3],"output":".../render/r.$F4.png"}
   → 27,517 B, 3.6 s: outputs r.0001–r.0003 (all on disk), thumbnail attached as image, job_id; job status → done
```

This is the biggest change from review 06. The image is **returned as MCP image content**, one call works headless, and the output paths are right (frames 1–3, not "0024").

Friction:
- **`viewport_capture` mutates the user's scene.** It leaves `/obj/hocuspocus_capture_cam` and `/out/hocuspocus_capture` behind, sets `dirty:true`, and adds two `HocusPocus: viewport_capture` undo entries. Task 11's `hip_new {"on_unsaved":"save"}` then saved them into `friction.hip`.
- The default capture is 1024×768, which comes to 145 KB per look. A smaller default would be enough for "check that it's there".

## 9. Deliberate mistakes — 27 calls, 34.2 KB

| Mistake | Response (trimmed) | Verdict |
|---|---|---|
| `node_create type:"mountian"` | `node_type_not_found` "No Sop node type 'mountian' (parent /obj/terrain)." hint "Closest Sop types: mountain, mpmcontainer. node_type_search finds types by label." `candidates`, `rolled_back:true` | Excellent |
| `parm_set .../box1/sizee` | `parm_not_found` hint "**Did you mean size? It is a tuple: use /obj/terrain/box1/size with a list of 3 values, or a component (sizex/sizey/sizez) with a scalar.**" | Excellent |
| `node_create box parms:{"sizee":3}` | same hint, scoped to `parms.sizee`, `rolled_back:true` | Excellent |
| `node_connect ... to_input:5` | `invalid_input` "/obj/terrain/copy1 has no input 5 (it takes 2)." hint "Inputs of /obj/terrain/copy1: 0: input1 (Geometry to Copy); 1: input2 (Target Points to Copy to)." | Excellent: exactly what review 06 asked for |
| `to_input:"points"` | same, with `candidates:["input2","input1"]` | Good |
| `from:"/obj/terrain/nope"` | `node_not_found` hint "/obj/terrain exists; list its children with node_find root='/obj/terrain'." | Good |
| `node_info /obj/terrain/OUTT` | hint "Did you mean /obj/terrain/OUT? Paths are absolute and case-sensitive." | Excellent |
| `node_create type:"geo"` in a SOP net | hint "geo is a Object node type, but /obj/terrain holds Sop nodes." | Excellent (grammar aside) |
| `geo_info {"node_path":...}` | `invalid_argument` "path: required property is missing; node_path: unknown property; did you mean path?" | Excellent |
| `items` as object not array | "items: expected array, got object {...}" | Good |
| `height = "tall"` | `invalid_value` "…is a float parm; got 'tall'." hint "Use the expression field for expressions." plus range | Good |
| `size = [1,2]` | "…has 3 components; got 2 values." hint "Components: sizex, sizey, sizez." | Good |
| menu `generateby = "Count"` | lists tokens and labels | Good |
| `expression "$F*("` | `isError:false`, but `errors:["Unable to evaluate expression (Bracing error ...)"]`, `cook_state:"error"` | Good: no longer silent |
| `geo_info box1` (errored) | `cook_failed` with Houdini's actual error text | Good |
| `problems {"root":"/obj"}` | lists box1 with the real message | Good, though it lists the same error twice |
| bad tool `node_creat` | JSON-RPC `-32602 "Unknown tool: node_creat"` plus all 31 tool names, no suggestion | OK |

**Correctness problem: stale errors after the fix.** After `parm_set {"path":".../box1/sizex","revert_to_default":true}`:
- The `parm_set` result still showed the Bracing error.
- `cook copy1` (not forced) returned `ok:false` with the old error.
- `problems` grew to **7 stale problems** across the whole chain.

Only `cook box1 force:true` followed by `cook copy1 force:true` cleared them. An agent that trusts these results will "fix" a node that is already fixed. The hints don't mention `force`.

## 10. tools/list as an artifact

- **31 tools, 34,557 B, about 8.6k tokens** (the `full` profile: 35 tools, 37.3 KB). Review 06 had 103 tools and 99.7 KB. Of the 34.3 KB: `inputSchema` 13.9 KB, `description` 8.6 KB, `outputSchema` 6.8 KB, `annotations` 2.8 KB. The largest tool is `parm_set` at 2.6 KB. There are no outliers like `production.asset.qualify`.
- The names are plain Houdini words: `node_create`, `node_connect`, `parm_set`, `geo_info`, `cook`, `problems`, `hip_save`, `viewport_capture`, `houdini_python`. Every description starts with what the tool does and ends with "use X instead for Y", which is how I chose between `node_info`/`network_describe`, `cook`/`problems`, `geo_info`/`geo_read` and `viewport_capture`/`render` without trial and error.
- Arguments are consistent: `path` (one) and `paths` (many), `root` for subtrees, `parent` for containers, all snake_case. Review 06 counted five spellings for "node path".
- Resources and prompts are small: `resources/list` 551 B, templates 1,051 B, prompts 1,324 B. `hocuspocus://guide` is 37.5 KB, but it is opt-in.
- The core surface still exceeds the "under 8k tokens" target from review 06 by about 8%. The `outputSchema` blocks (6.8 KB) are the obvious trim.

## 11. `hip_new` with unsaved changes — 8 calls, 11.1 KB

```
hip_new {}  → isError, code "unsaved_changes": "The scene C:/.../friction.hip has unsaved changes; refusing to clear it."
              hint "Pass on_unsaved: 'save' to save first, 'discard' to drop the changes, or call hip_save (with path for an untitled scene) first."
hip_new {"on_unsaved":"save"}     → {"path":".../state/untitled.hip","dirty":false,"is_new":true,"scene_generation":1,"saved_first":true}
node_create /obj/scratchgeo; hip_new {} → unsaved_changes again (untitled scene)
hip_new {"on_unsaved":"discard"}  → {"scene_generation":2,"saved_first":false}; node_find /obj → []
```

This is safe by default, the hint names every way out, and `scene_generation` changes so cached paths can be invalidated. The only catch is the capture artefacts from task 8, which got saved into the user's file.

## 12. Kill Houdini, call a tool, relaunch — 12 calls, 14.4 KB

```
taskkill hython 14836
node_find {"root":"/obj"} → isError, code "houdini_offline", "No live Houdini instance with HocusPocus is running.",
                            retryable:true, hint "call houdini_connect with launch to start one"
houdini_status {}         → connected:null, warnings ["The connected Houdini (pid 14836) is gone; selecting another live instance.", ...]
houdini_connect {"launch":{"mode":"headless","hip":".../friction.hip"}}  → new pid 61556 in 1.5 s, hip loaded, dirty:false
node_find /obj/terrain; geo_info copy1 → 200 pts: full recovery from the saved file
```

**Killed in the middle of a call** (a `houdini_python` that creates a node and then sleeps 8 s; hython killed after 3 s):

```
→ isError, code "delivery_unknown": "The request to Houdini (port 57372) was sent but no complete response arrived
   (ConnectionResetError: [WinError 10054] ...)." retryable:false,
   hint "The call may or may not have run in Houdini. Inspect state (houdini_status, node_info, undo history) before repeating it; never blindly repeat a mutation."
```

The next call returned `houdini_offline`, and `houdini_connect launch` recovered in 1.0 s. The bridge pruned the dead registry entries itself, so no client restart was needed.

Friction:
- The `houdini_offline` and `delivery_unknown` messages never say *the process you were driving exited*, and never mention that its unsaved changes are gone. Only `houdini_status` reports "pid 14836 is gone".
- `retryable:true` on `houdini_offline` tempts a blind retry, which can't succeed without a launch.

---

## Per-task totals

| Task | Calls | Response bytes | First-try success? |
|---|---:|---:|---|
| handshake (`server/discover` + `tools/list`) | 2 | 36,292 | — |
| 1 discover | 4 | 8,266 | yes |
| 2 build chain + layout | 3 | 9,450 | yes (1 call to build) |
| 3 read back | 6 | 8,601 | yes |
| 4 frame 24 | 4 | 3,569 | yes |
| 5 save / dirty | 8 | 12,263 | yes |
| 6 scatter + copy | 8 | 35,549 | yes (build in 1 call) |
| 7 python | 4 | 3,083 | yes |
| 8 visual | 8 | 232,827 (3 images) | yes |
| 9 mistakes | 27 | 34,238 | n/a (each error was actionable) |
| 10 resources / prompts / guide | 5 | 41,543 | — |
| 11 hip_new | 8 | 11,055 | yes |
| 12 kill + recover | 12 | 14,379 | yes |
| extra: `network_describe` → `network_build` round trip into `/obj/t2` | 3 | 4,367 | yes |
| **Total** | **102** | **455,482** | |

Without images and the optional 37.5 KB guide, the whole twelve-task run cost about 113 KB on the wire. That is roughly 14k model-visible tokens, since each result is duplicated. Review 06 needed about 400 KB for task 2 alone.

---

## Scorecard (1 = poor, 5 = excellent)

| Dimension | 0.9 | 1.0 | Why (1.0) |
|---|:---:|:---:|---|
| Discoverability | 2 | **4** | 31 tools / 8.6k tokens, instructions give the workflow, descriptions route between siblings, exact names rank first and current versions are marked, inputs are labelled, tuple components are listed. Held back by weak natural-language ranking, `node_type_info` with no "common parms" view (12.6 KB for scatter), and a list slightly over 8k tokens. |
| Idiom match with Houdini vocabulary | 2 | **5** | Node and parm paths, tuple vs component paths, `createNode` version resolution, input labels, display/render flags, `childrenAsData`, HScript, `$F` expressions, one undo group per call, top-to-bottom layout. The tools read like Houdini. |
| Verbosity / token cost | 1 | **4** | Typical calls are 0.5–3 KB. Building 5 nodes cost 6 KB, a whole network 1.4 KB, `geo_info` 1.3 KB. Held back by every result being sent twice (text + structured), 12.6 KB type infos, 145 KB default captures, and a 2.6 KB status line that repeats one path four times. |
| Error quality | 3 | **4** | Every deliberate mistake got a stable `code`, a hint that names the fix, and `candidates` ("Did you mean size? It is a tuple…", "copy1 has no input 5 (it takes 2)…"). `unsaved_changes` and `delivery_unknown` are model answers. Held back by **stale cook errors after a fix** (papercut 1), crash errors that don't name the dead process, and an unknown tool name getting no suggestion. |
| Number of concepts to learn | 1 | **5** | Node path, parm/tuple/component path, undo step, `on_unsaved`, job, `scene_generation`, `delivery_unknown`. Everything else is plain Houdini. |
| Time to first success | 1 | **5** | 2 calls and 1.5 s to a running headless Houdini. The first build call succeeded. About 41 s of wall clock from client connect to a verified 5-node chain, including my own think time. |

---

## The 10 worst remaining papercuts

1. **Stale node errors after fixing the cause.** `parm_set {"path":"/obj/terrain/box1/sizex","revert_to_default":true}` returns `value:1.0, is_default:true`, but still `errors:["Unable to evaluate expression (Bracing error ...)"]`. A following `cook {"paths":["/obj/terrain/copy1"]}` returns `ok:false` with the same old error. `problems` grows from 2 to 7 entries. Only `cook box1 force:true` and then `cook copy1 force:true` clear it. Either recook (or force) the fixed node inside `parm_set` and `cook`, or say in the hint that `force:true` is needed.
2. **`viewport_capture` leaves artefacts in the user's scene.** It creates `/obj/hocuspocus_capture_cam` and `/out/hocuspocus_capture`, flips `hip.dirty` to true, and adds a `HocusPocus: viewport_capture` undo step per call. `hip_new {"on_unsaved":"save"}` then wrote them into `friction.hip`. A "look" should be read-only: build the camera and ROP temporarily and delete them, or keep them outside the saved scene.
3. **The untitled headless scene lives in the bridge state dir.** After `houdini_connect launch`, `hip.path` is `<HOCUSPOCUS_STATE_DIR>/untitled.hip`, and `$HIP` and `$JOB` point at the directory that holds `instances/` and `logs/`. Renders to `$HIP/...` would land next to the registry. Launch hython from a neutral per-instance work dir, or set `HIP`/`JOB` to one.
4. **Three spellings for "an expression".** `node_create` parms take `{"expr": "...", "lang": "hscript"}`. `parm_set` takes `"expression"` and `"language"`. `network_describe` emits `{"expression": "$F*0.1"}` inside a parm list. `node_create`'s schema (`required:["expr"]`, `additionalProperties:false`) rejects the spelling the reader tools emit. I checked this: `{"sizex":{"expression":"$F"}}` → `invalid_argument` "expected string or number or boolean, got object … (no alternative of anyOf matched)", and the message never mentions `{expr}`. Accept both everywhere, or settle on one.
5. **Natural-language type search ranks poorly.** `node_type_search {"query":"scatter points on a surface"}` puts `relax`, `guidesurface` and `hairgen::2.0` ahead of `scatter::2.0` (#4). Name queries are now perfect. Weight label and name token hits above description words.
6. **`node_type_info` has no compact view.** `Sop/scatter` returns 12,620 B (~3k tokens) to reveal `npts`. `Sop/copytopoints` returns 6.3 KB, much of it multiparm template rows. Add `parms: "common"` (first folder, or non-advanced) or a `query` filter.
7. **Every tool result is duplicated on the wire** (`content[0].text` holds the same JSON as `structuredContent`), which doubles response bytes. Clients that read `structuredContent` don't need the text copy at full length. Consider a short text summary when structured content is present.
8. **Crash messages don't say what crashed.** After the selected hython dies, `node_find` returns `houdini_offline` "No live Houdini instance with HocusPocus is running." with `retryable:true`, and a mid-call kill returns `delivery_unknown` with `ConnectionResetError`. Neither says "the Houdini you were driving (pid 14836) exited; unsaved changes since the last save are lost". `retryable:true` invites a blind retry that cannot work without a `launch`.
9. **Dirty state is only visible through a 2.6 KB `houdini_status`.** `parm_set`, `node_create` and friends don't return `dirty`, and `houdini_status` repeats the hip path four times (`hip.path`, `env.HIP`, `env.JOB`, `instances[].hip`). `hip.recent` stays `[]` after saves and loads.
10. **Small inconsistencies in messages:**
    - An unknown tool (`node_creat`) gets a JSON-RPC `-32602` with all 31 names but no "did you mean node_create", unlike every other error.
    - `houdini_python` exceptions come back as `isError:false`.
    - Messages repeat the path ("/obj/terrain/mountain1/height: /obj/terrain/mountain1/height is a float parm").
    - `problems` lists box1's single error twice.
    - Grammar: "geo is a Object node type".
    - Float noise (`2.4000000000000004`).
    - `locked` means "HDA contents locked" in `network_describe` but the lock flag in `node_info`.

## Five things that work well

1. **`node_create` as a batch in Houdini terms.** Parent, type, name, parms (tuple, component or expression), inputs (by index or name, including nodes created earlier in the same call) and flags, in one undo step. It returns each node's errors and cook state. Task 2 took one call where review 06 needed 14 calls and two quarantines.
2. **Errors you can act on.** Stable `code`, a `hint` that states the fix, `candidates`, and `rolled_back`. Tuple-aware "Did you mean size?", input lists that say how many inputs a node takes and what they're called, and schema violations with "did you mean path?". `unsaved_changes` and `delivery_unknown` ("never blindly repeat a mutation") are exactly right.
3. **The read side is compact.** `geo_info` (~1.3 KB, with attribute types and sizes), `geo_read` (spreadsheet rows with a cursor), `parm_get` (value, raw, expression and component names, at any frame) and `network_describe` (a whole network in 1.4 KB that `network_build` takes back as-is).
4. **Headless works and is honest.** The agent can launch Houdini itself in 1.5 s. `time` works without a playbar. `viewport_capture` falls back to an OpenGL ROP and returns the PNG as image content. `render` returns correct per-frame outputs and a thumbnail image. Recovery after a crash is one `houdini_connect` call with no client restart.
5. **Small surface, clear routing, and an escape hatch.** 31 tools with plain names, descriptions that end with "use X for Y", consistent snake_case `path`/`paths`/`root`/`parent` arguments, instructions that work as a 10-line manual, and `houdini_python`, which returns stdout, a result value and an exception block, for anything the typed tools don't cover.

---

## Verdict on BIBLE §14 M5 exit criterion

The criterion is "Scorecard ≥ 4/5 on every dimension". **It is met: 4 / 5 / 4 / 4 / 5 / 5**, against 2 / 2 / 1 / 3 / 1 / 1 for 0.9. All twelve tasks succeeded on the first attempt. None needed a source read or a workaround, and none left the scene in an unknown state.

Three dimensions sit at exactly 4, so the pass has little margin:
- **Error quality** would drop if the stale-error behaviour (papercut 1) misled an agent into a fix loop.
- **Verbosity** would drop if the text/structured duplication and large type infos grow.
- **Discoverability** depends on `tools/list` staying near 8k tokens.

Before the PR to `master`, I recommend fixing papercuts 1 (stale errors), 2 (capture leaves scene artefacts) and 3 (`$HIP` in the state dir). They are the only ones that can make an agent do the wrong thing, not just spend more tokens.

### Reproduction notes

- Scratch dir: a venv with `hocuspocus` installed editable; `tee.py` (byte-counting stdio proxy around `hocuspocus-mcp.exe`); `driver.py` (one long-lived `mcp.Client` session fed from an inbox directory); `wire.jsonl` (every JSON-RPC line with its byte size).
- Env: `HOCUSPOCUS_STATE_DIR=<scratch>/state`, `HOUDINI_USER_PREF_DIR=<scratch>/prefs/houdini__HVER__`, `HOCUSPOCUS_HFS=C:\Program Files\Side Effects Software\Houdini 22.0.466`. Port 37219 was never used: the hosts took ephemeral ports 59341, 57372 and 57395.
- Three hython processes were launched through `houdini_connect` (pids 14836, 61556, 57044). Two were killed deliberately for task 12, and the last was killed at the end. No other process was touched. No repo file other than this report was edited.
