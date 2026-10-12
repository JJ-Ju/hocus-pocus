> **Status: historical.** Describes HocusPocus 0.9, archived at tag `v0.9-archive`. See [`../README.md`](../README.md).

# 06 — Hands-on Friction Log: driving HocusPocus 0.9.0 as an agent

**Reviewer seat:** an AI agent with only `tools/list`, `resources/list`, README, `docs/agent-workflows.md` and `docs/user-manual.md` to go on.
**Host:** Houdini 22.0.466 `hython.exe` (Python 3.13.10), headless, loopback HTTP MCP on port 37941, bearer auth on (generated token), policy profile `local-dev`.
**Transport:** direct HTTP JSON-RPC to `/hocuspocus/mcp` (`initialize` → `Mcp-Session-Id` → `tools/call` / `resources/read`). I did not test the stdio broker.
**Date:** 2026-10-12. 98 recorded round trips against the final host, 4.27 MB of response bytes in total.

Token estimates are `bytes / 4`. Every number below was measured on the wire.

---

## 0. Getting a host up (before task 1)

The supported startup path does not run on this machine. I needed about 45 minutes and several source reads to get a working host.

| Step | What happened | Did the message say how to fix it? |
|---|---|---|
| `hocuspocus.start_server()` in hython | `HOCUS998 runtime_admission unsupported_houdini: "HocusPocus requires Houdini 22.0.368; the active host is 22.0.466."` (`startup.py` pins one exact build.) | It says what is wrong. Nothing short of editing source fixes it. |
| `pythonrc.py` bootstrap (the reported `invalid_install_root`) | `_installed_root()` requires `HOCUSPOCUS_ROOT` to resolve to the same directory as the `pythonrc.py` that was loaded. The bootstrap then rejects any `__pycache__` under the governed roots, and the repo currently has several (`python3.11libs/hocuspocus/core/__pycache__`, …). | No. The reason code is printed, but not which path or which rule failed. |
| Workaround (legitimate, no source edits) | Copied the maintainers' `scripts/durable_h22_host.py` pattern: construct `HocusPocusRuntime(load_settings(...))` directly, with `PYTHONPATH`, `HOCUSPOCUS_ROOT` and `PYTHONDONTWRITEBYTECODE=1` set, and the port overridden in code. | n/a |
| Pref dir isolation | Setting `HOUDINI_USER_PREF_DIR` without `__HVER__` is silently ignored ("EnvControl: … missing __HVER__, ignored"). All server state then lands in the shared `~/houdini22.0/hocuspocus/runtime` (token, sqlite DBs, journal), and **other agents' hython processes on this machine were using the same files**. | No. Houdini only prints a warning to stderr. |
| **Every mutation failed** (once the pref dir was in my scratch dir) | `scene.new` → `-32009 "Operation identity is already active or belongs to another request." {hocusCode: HOCUS999, kind: operation_capacity, retryable: false}`. Root cause, found by wrapping `_reserve_journal` in my host script: `FileNotFoundError` from `os.open(...operation-history.sqlite3.journal\<64-hex>.slot)`. The path was **263 characters**, past Windows MAX_PATH. `_admit` turns *any* `OSError` from journal reservation into "capacity". | **No, and the message is actively misleading.** It reads as an idempotency collision. Read-only tools kept working, so the server looked healthy. |
| Fix | Moved the pref dir to a short path (`<repo>\.eval06\h__HVER__`, deleted afterwards). Every mutation then worked. | — |

Each mutating call also preallocates and `fsync`s a 16 MB zero-filled journal slot (`JOURNAL_SLOT_BYTES = 16 MiB + 16 KiB`). Admission budgets 16 MB per pending record against a 64 MB cap. Calls stayed fast on NVMe, but the I/O is heavy for "set one parm".

**Time to first successful mutation: about 45 min.** Almost all of it went on install/admission machinery and on an error that pointed the wrong way, not on Houdini.

---

## 1. Discover the session

```
initialize                 787 B   (~200 tok)  no "instructions" field
tools/list              99,690 B (~24,900 tok)  103 tools, 28 namespaces
resources/list          17,452 B  (~4,400 tok)  53 resources
resources/templates/list 13,014 B (~3,250 tok)  27 templates
session.info             3,698 B    (~925 tok)
scene.get_summary        1,329 B    (~330 tok)
houdini://documents/scene 2,658 B   (~660 tok)
```

Orientation costs **about 34k tokens before the first useful action.**

- `session.info` returns the version (`applicationVersion: [22,0,466]`), `uiAvailable: false`, granted capabilities and **all four policy profiles in full**. About 40% of the payload is policy boilerplate the agent didn't ask for.
- **The hip path is redacted**: `"hipFile": "<redacted>"` appears in both `session.info` and `scene.get_summary`. The resource `houdini://session/scene-summary` returns the real path, so the redaction protects nothing and only hides the answer from the tool.
- "What's open" is answered by `houdini://documents/scene`, which lists the nine manager roots. The tools give no node counts per context, no "/obj has N objects", and no list of top-level nodes.
- `hipDirty: true` on a brand-new session.

Round trips: 3 to get a useful picture (session.info, scene summary, scene document). Score: OK, but expensive and partly redacted.

---

## 2. Build geo → box → mountain → subdivide → null OUT

The docs say to use `object.create_geometry`, then `document.checkout`, edit the JSON, then `document.validate` and `document.apply`. The low-level `node.create`, `node.connect`, `parm.set` and `node.set_flags` are named in the docs **but are not in `tools/list`**: `operations.py` registers 27 legacy tools with `set_listed(False)`. They still work when called by name; I found that out in task 3.

### What happened, call by call

1. `scene.new`: 1,288 B, fine.
2. `object.create_geometry {"name":"terrain"}`: **26,499 B (~6.6k tok)** to create one empty Geometry object. The inline "SOP working document" carries 90 parameter bindings for the OBJ container itself (`bank`, `caching`, `vm_rendersubd`, …), each about 250 B.
3. Discovery for mountain:
   - `node_types.list {query:"mountain"}` → `mountain` and `mountain::2.0`. Neither is marked current or legacy, and nothing says which one the Tab menu creates.
   - `node_types.get_info {detail_level:"key_parms"}` returns 12 "key" parms: `group, elementsize, elementscale, accumg, accuml, basis, bias…`. That looks like the first parms alphabetically, not the key ones. **Neither `height` nor `offset` is in it.**
   - `detail_level:"full_parms"` (6.3 KB) gives `height` and `offset` (`numComponents: 3`) **but not the component names.**
4. I hand-built nodes, edges and bindings into the checkout document, then called `document.validate`. **3 errors, caused by the server's own output**:
   ```json
   {"code":"document.schema_violation","jsonPointer":"/$schema","message":"<redacted>"}
   {"code":"document.schema_violation","jsonPointer":"/documentId","message":"must match pattern '^network:'"}
   ```
   The checkout came back with `"$schema": "<redacted>"` and `"documentId": "<redacted>"`, so a checkout cannot be round-tripped unmodified. I had to guess `network:/obj/terrain` from the pattern in the error.
5. `document.apply` with `offset` as the parm name: rolled back cleanly (HOCUS755), 35 KB. Message: `Parameter not found: /obj/terrain/mountain1/offset`. It passed `validate` and failed at execution.
6. I tried `offsetx`, then `offset1`:
   ```json
   {"message":"Document apply could not resolve the live parameter template before mutation.",
    "data":{"diagnosticCode":"document.parameter_preflight_failed","parmPath":"/obj/terrain/mountain1/offsetx",
            "expectedType":"existing assignable Houdini parameter","receivedValue":null}}
   ```
   It turned out later that **`offsetx` is the correct name.** Preflight resolves parm components against the live node, and the node does not exist until this apply creates it. **You cannot bind a tuple component on a node created in the same apply.** The tuple name (`offset`) passes preflight and then fails at execution.
7. I dropped the expression and applied again. Result: **`HOCUS756 "Document apply failed and the network is in partial or unknown state."`** (69 KB, ~17k tok). Verification flagged two things:
   - My edge uids (`e1`, `e2`, `e3`) were replaced by canonical `edge:data:<destUid>:<index>`, which the verifier counts as 3 deleted plus 3 created edges.
   - `mountain::2.0` is an HDA, so its node gained `subnetworkDocumentId: "network:/obj/terrain/mountain1"`.

   Rollback then failed: `"guarded undo: The Houdini undo stack is empty."` (undo appears to be unavailable in hython), followed by "inverse restoration verification did not match the baseline". **The scope was quarantined.**
8. `document.apply_quarantines` → `document.recover_scope {"root_path": …}` → `"rootPath must be an absolute Houdini network path."`. The real problem is that this one tool takes **`rootPath` in camelCase**, while 177 other parameters across the surface are snake_case. 43 parameters, mostly on `document.*plan*` and `source.*`, are camelCase. The error message blames the wrong thing.
9. Fresh `document.checkout`, canonical edge uids, and `subnetworkDocumentId` filled in by hand. **Applied, verified: true.** 61 KB response (~15k tok) for 4 nodes.
10. Second apply to add the `offsetx` expression. First the server's checkout failed its own schema: `/diagnostics/0/details must be of type object`, because `details` had been redacted to the string `"<redacted>"`. After I stripped that: **HOCUS756 again**. Two causes:
    - `subnetworkDocumentId` was `<redacted>` in the checkout, so sending it back counts as a change.
    - `expressionLanguage` was sent as `"hscript"` and read back as `"Hscript"`; the verifier is case-sensitive.

    The expression was in fact applied live (`rawValue: "$F*0.1"`), but the scope was quarantined again.

**Round trips for task 2 via the document lane: 14**, including 2 quarantines and 2 recoveries. About 400 KB of responses (~100k tokens) to produce 4 SOPs and one expression.

### Layout
`node.layout` (hidden) works, but positions come out as a single horizontal row in creation order: `gridCell [1,0] … [7,0]`, with `mountain1` to the left of `box1`. Houdini SOP networks read top to bottom along the data flow. "Managed integer grid" placement is not how Houdini users lay out networks.

---

## 3. Read the network back

- `houdini://documents/network/obj/terrain`: **78,787 B (~19.7k tok)** for 5 nodes, because every parm on every node is serialized (180 bindings).
- **After the first cook, the same network's checkout jumped to 1,333,363 B.** Once cooked, the locked HDA internals of `mountain::2.0` (an `attribvop1` with ~55 VOP nodes, 110 bindings each) are included in the parent network document. The checkout switched to `mode: resource`, its `resourceUri` was `<redacted>`, and reading `houdini://documents/checkouts/{id}` returned **2,088,726 B (~522k tokens)**. A `validate_only` of a 2.9 KB document returned **1,426,428 B (~357k tokens)**. Either one ends an agent's context window.
- Raw versus evaluated values: `houdini://nodes/{path}/parms` is good. It gives `{"name":"offsetx","rawValue":"$F*0.1","value":2.4,"expression":"$F*0.1"}` in 8.3 KB per node.
- `node.get` (hidden) is compact (~850 B), with `inputs` as a path list. It has **no errors or warnings field**. No tool exposes `node.errors()` or `node.warnings()` (see task 9).
- `geometry.get_summary {"node_path":"/obj/terrain/OUT"}`: **902 B and excellent**:
  ```json
  {"pointCount":26,"primitiveCount":24,"vertexCount":96,"bboxMin":[-0.47,-0.49,-0.47],"bboxMax":[0.50,0.48,0.50],
   "pointAttributes":["P"],"primitiveAttributes":[],"vertexAttributes":[],"pointGroups":[],"primitiveGroups":[]}
  ```
  It has no detail attributes, no attribute types or sizes, and **no way to sample P values**. I found no tool or resource that returns element values.

---

## 4. Frame 24 and re-read

```
playbar.set_frame {"frame":24} → -32603 "Internal server error"
   details: "Not available in this context.\nPlaybar UI not available."
```
**The frame did change anyway.** `scene.get_summary` reports `currentFrame: 24.0`, and the parms resource shows `offsetx value: 2.4`. The tool reports failure for a mutation that committed. `playbar.get_state` fails the same way, so a headless agent's only way to read the frame is `scene.get_summary`. 2 round trips to recover the truth.

---

## 5. Save and dirty state

- `scene.save_hip {"path": ".../friction.hip"}` → `{"hipDirty": true, "path": "<redacted>"}`. The file was written (97 KB), but the tool won't tell me where, and reports dirty *immediately after saving*.
- `hou.hipFile.name` confirmation: the tool redacts it. `houdini://documents/scene` says `hipFilePath: null` (stale). Only `houdini://session/scene-summary` shows the real path. Three surfaces, three answers.
- After `parm.set`, `hipDirty` is true; after a second save, still true. **The dirty flag is never false**, so it carries no signal. I suspect the server's own identity userData writes re-dirty the scene after save, but I could not check that through the API.

Round trips: 6. The save works; confirming it through the tools does not.

---

## 6. Scatter points, copy a sphere (discovery)

- `node_types.list_compatible {"intent":"scatter points on a surface then copy a sphere to them"}` → `"Compatibility intent is ambiguous"` with candidates `copying` and `scatter`. The response is honest and machine-readable.
- `intent:"scatter points on a surface"` ranks first **`kinefx::motionclipunpack`**, then `scatteralign` and `copytopoints`. The Scatter SOP is missing from the top 5.
- `node_types.list {query:"scatter", limit:100}` (28.8 KB): 87 hits, and **`scatter` is #68 and `scatter::2.0` #69**. The ranking is driven by tags, not by name match.
- `get_info scatter::2.0 key_parms` leaves out the parm everyone uses, Force Total Count (`npts`). `full_parms` has it.
- I built it with the document lane: merge mode with a minimal 2.9 KB document → `document.parameter_preflight_failed` on **`/obj/terrain/shop_materialopts`** (value `"override"` versus template `button`). That is a binding *I did not send*; merge preflights the server's own live state and rejects its own data. Reconcile needed the full 1.3 MB document.
- **Fallback to the unlisted low-level tools: 11 calls, about 200 tokens each, all successful on the first try:**
  ```
  node.create scatter::2.0 / sphere / copytopoints::2.0
  node.connect OUT→scatter1; sphere1→copy1[0]; scatter1→copy1[1]
  parm.set scatter1/npts=200; sphere1/scale=0.05
  node.set_flags copy1 display+render; node.layout
  geometry.get_summary copy1 → pointCount 200, primitiveCount 200, bbox ±1
  ```
  This is the plain answer to "what should the redesign look like".

---

## 7. Arbitrary hou Python

There is no exec tool in any profile. `procedural-authoring` grants a `run_code` capability, but in this build it only gates python/vex code blobs inside documents. An agent that needs `hou.hipFile.name`, `node.errors()` or a point's `P` has no escape hatch, so every gap in the typed surface blocks it outright. (I verified this in `core/policy.py` and `live/operations.py`; tools/list alone gives no hint.)

---

## 8. Visuals

- `viewport.capture`, `snapshot.capture_viewport` and `viewport.get_state` → `"This tool requires a Houdini UI session."` The error is clear, but these tools are **advertised in a session whose own `session.info` says `uiAvailable: false`**.
- A path that works, though nothing documents it: `scene.create_turntable_camera` → hidden `node.create /out opengl` → `parm.set camera, picture` → `render.preflight` (`canRender: true`) → `render.rop` (async task) → poll `houdini://tasks/{id}`. That gave a correct 1280×720 PNG of 200 spheres in about 1.8 s headless.
- Problems on that path:
  - Task `outputPaths` reported `render.0024.png` (evaluated at the current frame) when the file written was `render.0001.png`.
  - The tool response redacts `taskResourceUri`, while the task resource itself shows the real path.
  - **The image is never returned as MCP image content**, so an agent without filesystem access can't see it.

---

## 9. Deliberate mistakes

| Mistake | Response | Verdict |
|---|---|---|
| `node.create node_type_name:"mountian"` | `-32603 Internal server error` / `"Invalid node type name"` | Wrong family (runtime/internal instead of validation), no suggestion. `node_types.get_info` on the same name gives a clean `Node type not found in category Sop: mountian`. |
| `parm.set .../box1/sizee` | `Parameter not found` plus `expectedFormat: "/obj/geo1/tx"` | Clear, but no "did you mean `sizex`". |
| `node.connect` to input 5 / 7 | `-32603 Internal server error` / `"Invalid input."` | Poor: doesn't say how many inputs the node has. |
| missing source node | `Node not found: /obj/terrain/nope` | Good. |
| `geometry.get_summary {"path":…}` | `node_path is required` | Good. Other tools use `path` (`node.get`, `node.set_flags`), `node_path`, `parm_path`, `root_path`, `rootPath`, `parent_path`… |
| `parm.set_expression "$F*("` | **Accepted**, `value: 0.0` | Silent failure. |
| …then `geometry.get_summary box1` | `Node has no accessible geometry: /obj/terrain/box1` | Misleading. The node errors on cook, but the real error is hidden. |
| `cook.node box1` → task | `state: failed, "The attempted operation failed.\nError while cooking."` | Doesn't include Houdini's actual error text. `graph.check_errors` and `scene.validate` both report 0 issues. |
| bad tool name | `Unknown tool: node.creat` | Fine. No suggestion. |

The structured `errorFamily` and `retryable` fields are a strong foundation. Content is the weak part: there are no suggestions, internal errors leak as `-32603`, and Houdini's own node errors are never surfaced.

---

## 10. tools/list as an artifact

- **103 tools, 99,690 bytes, about 25k tokens.** `production.asset.qualify` alone is 16,661 B (~4.2k tok), 17% of the list, for a release-gate workflow almost no session will use.
- Namespaces: `document` 17, `hda` 12, `scene` 10, `pdg` 9, `usd` 8, `source` 7, then 22 more. HocusScript, workspace and production tools (`document.*_source`, `*_bundle`, `*_plan`, `source.*`, `production.*`), about 25 in all, take up much of the list.
- **The single most-used Houdini verbs are hidden:** create node, connect, set parm, set flags, get node, list parms, set expression and layout are among the 27 unlisted tools. Docs and tools/list contradict each other.
- Descriptions are mostly readable English. Many are written in project jargon, though: "Rerun the exact-version live validation of an authenticated flat Bundle 0.2, module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5…", "immutable plan identity", "guarded identity/revisions". A Houdini artist-agent can't map these to Houdini concepts.
- 10 of the 53 resources are duplicate schema aliases (`hocuspocus://schemas/...` and `houdini://production/schema/...`).
- Duplicated affordances: `viewport.capture` vs `snapshot.capture_viewport`, `pdg.get_workitems` vs `pdg.get_graph_state`, `scene.events_recent` vs `houdini://scene/events`.

---

## Scorecard (1 = poor, 5 = excellent)

| Dimension | Score | Why |
|---|---|---|
| Discoverability | **2** | 25k-token list. Core verbs are hidden. Key-parm metadata misses `height`, `offset` and `npts`. Ranking puts `scatter` at #68. |
| Idiom match with Houdini vocabulary | **2** | Houdini concepts (node, parm, input, display flag) are hidden behind "network documents", "bindings", "edges with uids" and "checkouts". Layout is horizontal. Parm tuples have no component names. |
| Verbosity / token cost | **1** | 6.6k tokens to create an empty geo, 15–17k per apply, 357k for a `validate_only`, 522k to read a 5-SOP network after cooking. |
| Error quality | **3** | Good structure (`errorFamily`, `retryable`, `jsonPointer`, `HOCUS755`/`756` distinction). Messages are often misleading (HOCUS999 "capacity", `rootPath` "absolute"), internal `-32603` leaks, there are no suggestions, and cook errors are never shown. |
| Number of concepts to learn | **1** | checkout, document revision, live revision, baseline, uid namespace, canonical edge uid, binding, valueMode, subnetworkDocumentId, merge/reconcile/validate_only, quarantine, recover_scope, operation identity, host generation, capabilities, policy profiles, plus HocusScript bundles, plans and projects. |
| Time to first success | **1** | About 45 min to the first mutation (admission and path issues). About 14 round trips and 2 quarantines to the first 4-node chain via the documented lane. 11 calls (~2 min) via the hidden lane. |

---

## The 10 worst papercuts

1. **The documented build lane can't round-trip its own output.** `$schema`, `documentId`, `subnetworkDocumentId` and `diagnostics[].details` come back as `"<redacted>"`, then fail schema or verification when sent back. Two of my applies were quarantined (HOCUS756) for this reason alone.
2. **The verifier is too strict about non-semantic differences** (agent-chosen edge uids, `hscript` vs `Hscript`, HDA `subnetworkDocumentId`), and **rollback depends on an undo stack that hython doesn't have**. So a benign mismatch becomes a quarantined scope.
3. **Low-level verbs (`node.create`, `node.connect`, `parm.set`, `node.set_flags`, `node.get`, `parm.list`, `parm.set_expression`, `node.layout`) are hidden from tools/list** but named in the docs, and they are the only lane that worked first try.
4. **Document size explodes when a locked HDA cooks.** The internals of `mountain::2.0` are serialized into the parent network: 1.3 MB per checkout, 2 MB per resource read, 1.4 MB per `validate_only` response.
5. **Journal reservation failure is reported as an idempotency conflict** (`HOCUS999 operation_capacity`, "already active or belongs to another request"). In my case the cause was MAX_PATH. All mutations failed while reads succeeded.
6. **Tuple parm components can't be bound on nodes created in the same apply**, and type metadata never lists component names (`offset` has `numComponents: 3`, with no `offsetx/y/z`).
7. **Redaction of facts the agent needs:** hip path in `session.info`, `scene.get_summary` and `scene.save_hip`; ROP output paths; `resourceUri` and `taskResourceUri`. Sibling resources show the same values, so the redaction protects nothing.
8. **Houdini node errors and warnings are never surfaced.** A broken expression is accepted silently. Downstream calls say "no accessible geometry" or "Error while cooking", and `graph.check_errors` reports 0 issues.
9. **Headless mismatch:** UI-only tools (viewport ×3, playbar ×2) are listed when `uiAvailable: false`, and `playbar.set_frame` returns `Internal server error` *after* changing the frame.
10. **Discovery ranking and "key parms" are unreliable** (`kinefx::motionclipunpack` first for "scatter"; `scatter` at #68; key parms are alphabetical-ish and omit `height` and `npts`). Inconsistent parameter naming adds to this (`path`/`node_path`/`parm_path`/`root_path`/`rootPath`).

Runners-up: `hipDirty` never goes false; the official start path refuses 22.0.466 because the build is pinned exactly; the shared default state root collided with other agents' hosts; `production.asset.qualify` is 17% of tools/list; the render task reports the wrong output frame; images are never returned as MCP content.

## Five things that worked well and should be kept

1. **`geometry.get_summary`.** About 900 B gives counts, bbox, attribute names and groups. It is the right shape and size for agent reasoning. Extend it (attribute types, detail attributes, a bounded value sample) rather than replace it.
2. **`houdini://nodes/{path}/parms` with `rawValue`, `value` and `expression` side by side.** This is exactly what an agent needs to reason about animated or expression parms.
3. **Structured error envelope.** `errorFamily`, `retryable`, `jsonPointer`, `parmPath`, and the HOCUS755 (rolled back, verified) vs HOCUS756 (partial, quarantined) distinction are good foundations. Keep the structure and fix the messages.
4. **Async task model for cooks and renders.** A task handle, then `houdini://tasks/{id}` and `/log`, gave clear states and per-frame events. `render.preflight` (`canRender`, node-reference existence) is useful.
5. **The low-level lane itself.** `node.create`, `node.connect`, `parm.set` and `node.set_flags` returned compact (~200-token) node summaries with the final resolved path and inputs, worked first try, and read like Houdini. Also keep `node_types.list_compatible` returning *ambiguity with candidates* instead of guessing.

## Recommendations for the redesigned tool surface (from the agent's seat)

1. **Make the default surface small and Houdini-shaped: about 15–20 tools, under 8k tokens.** Suggested set:
   - `scene.info`, `scene.open`, `scene.save` (returning the real path and dirty state), `scene.new`, `frame.set`
   - `node.create`, `node.delete`, `node.connect`, `node.set_flags`, `node.layout`, and `node.get` (inputs, outputs, flags, **errors/warnings**)
   - `parm.get` and `parm.set`, accepting tuples (`offset: [0,0,0]`) and per-component names, `value` or `expression`
   - `geometry.inspect`, `node_types.search`, `node_types.info`, `render.snapshot`

   Move HocusScript, source workspace, production, HDA library, PDG and USD into opt-in tool groups (a `tools/list` filter or profile), not the default list.
2. **Provide a batch edit in Houdini vocabulary, not a full-document round trip.** One call that takes an ordered list of ops: `{create: {type, name, parent}}`, `{connect: {from, to, input}}`, `{set: {parm, value|expression}}`, `{flags: …}`, executed in one undo group, returning a ~1 KB delta. Agents should never have to send back 50 KB of unchanged parms or invent uids. If the document model stays, make it sparse (non-default parms only, no locked-HDA internals) and loose in verification (ignore uids the server canonicalizes, case-fold enum strings).
3. **Never redact values the agent needs to act on.** If something is sensitive, omit the field and say so. Don't return `"<redacted>"` inside payloads the agent must send back.
4. **Surface Houdini's own truth:** `node.errors()`/`warnings()` on every node read and after every mutation that cooks. Silent acceptance of bad expressions should become a warning.
5. **Write error messages around the next action:** "did you mean `sizex`?"; "`copy1` has 2 inputs (0: geometry to copy, 1: target points)"; "this tool needs a UI session; use `render.snapshot` instead"; "journal path exceeds Windows MAX_PATH (263 > 260): set a shorter `HOUDINI_USER_PREF_DIR`".
6. **Fix discovery quality:** exact name and label match must outrank tag hits. Mark the current version among `x` and `x::2.0`. Make "key parms" the parms on the node's first tab or most used, and list tuple component names.
7. **Make it honest headless:** hide UI-only tools when `uiAvailable` is false. Make `frame.set` work with `hou.setFrame` and no playbar. Give the visual path one call (`render.snapshot` → OpenGL ROP under the hood) that returns the image as MCP image content.
8. **Offer a gated `python.exec`** (or `hou.eval`) under an explicit capability. It removes the "API has a gap, so the agent is stuck" failure mode, and the typed surface can then concentrate on the common cases.
9. **Keep the operational machinery out of the agent's way:**
   - Don't admit by preallocating 16 MB per call.
   - Don't classify local `OSError`s as identity conflicts.
   - Isolate state per host instance and port so concurrent hosts don't share sqlite and journal files.
   - Accept a range of Houdini 22.0.x builds instead of pinning 22.0.368 exactly.
   - Add `initialize.instructions` with a 10-line quickstart.

---

### Appendix: reproduction notes

- Scratch host: `scratchpad/hp/host.py` (the `durable_h22_host.py` pattern; reads `config/default.toml`, overrides port 37941; a diagnostic-only wrapper logs `_reserve_journal` exceptions). Client: `scratchpad/hp/mcp.py` (HTTP JSON-RPC, logs bytes per call to `calls.jsonl`).
- Env: `PYTHONPATH=<repo>\python3.11libs`, `HOCUSPOCUS_ROOT=<repo>`, `PYTHONDONTWRITEBYTECODE=1`, `HOUDINI_USER_PREF_DIR=<short path>\h__HVER__`.
- No source files were edited. The temporary pref dir `<repo>\.eval06` was moved out of the repo afterwards, and all hython processes I started were stopped.
- One unintended side effect: my first launch (pref dir override ignored) created `~/houdini22.0/hocuspocus/runtime/*`. I removed my files there. Some sqlite files were locked by another agent's hython that was using the same directory at the same time, and were left alone.
