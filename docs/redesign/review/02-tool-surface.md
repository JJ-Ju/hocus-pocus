> **Status: historical.** Describes HocusPocus 0.9, archived at tag `v0.9-archive`. See [`../README.md`](../README.md).

# 02 — MCP Tool Surface Audit and Gap Analysis

Reviewer: senior review, tool-surface track
Date: 2026-10-12
Baseline: `master` @ `cab2430`
Method: read the registration code. Dumped the live registries by calling
`LiveOperations.__new__(LiveOperations).register(ToolRegistry(), ResourceRegistry())`,
the same way `tests/test_runtime_scenarios.py:598` does. Measured payloads with
hython 22.0.466 against a scratch scene: `HOUDINI_USER_PREF_DIR` pointed at a
scratch dir, no server or port, no package install. Every number below comes
from that run unless marked otherwise.

---

## 0. Executive summary

* **The registered surface is 130 tools, not ~250.** 103 are listed and 27 are
  hidden but still callable. There are 53 static resources, 27 resource
  templates and **0 prompts**. Server `instructions` are not set. A client
  receives about 100 KB from `tools/list`. About 57 KB of that is model-visible
  text (names, descriptions and input schemas), roughly 14k tokens. One tool,
  `production.asset.qualify`, is 16 KB of that on its own.
* **The listed surface contains no general-purpose primitives for editing a
  node graph.** `node.create/connect/delete/set_flags` and
  `parm.set/set_expression/set_many` are all hidden in
  `operations.py:279-306` (`tools.set_listed(name, False)`). An agent that
  follows `tools/list` can only change an arbitrary SOP parameter by doing all
  of the following:
  1. Check out a "network document". For a **5-node** SOP chain this was
     **1.37 MB, 67 nodes and 4,728 parameter bindings**. That is over the 1 MB
     inline limit, so the document comes back as a resource URI.
  2. Edit the JSON.
  3. Validate it.
  4. Apply it with revision guards.

  Meanwhile `docs/user-manual.md` §5 still advertises the hidden `node.*` and
  `parm.*` tools as the "Core MCP Surface".
* **Most of the code and surface goes to invented abstractions, not Houdini
  vocabulary:**
  * the network document (v1 and v2 JSON schemas);
  * the HocusScript DSL (versions 0.1–0.5), its bundles, plans and quarantine;
  * the source-workspace IDE;
  * production-qualification carriers;
  * a "managed 12×64 grid" for node positions.

  The document and HocusScript lanes alone are about 14.7k LOC in `live/` plus
  about 56k LOC in `hocuspocus/hocusscript/`, against about 98k LOC in the
  whole package.
* **Core Houdini idioms are missing or weak:**
  * There is no Python/HScript exec tool. A `run_code` capability exists, but
    no tool uses it except code-blob installation.
  * Parm tuples cannot be addressed (`/obj/geo1/box1/size` → "Parameter not
    found").
  * Inputs cannot be set by name, and the source output index is dropped from
    node summaries.
  * There is no synchronous way to read node errors or warnings.
  * Geometry inspection returns attribute *names* only: no types, no values, no
    detail attributes, no sampling.
  * The viewport capture returns a file path instead of an image the model can
    see.
  * There is no help or documentation lookup.
  * Node-type discovery covers only OBJ/SOP/LOP/TOP. COP/DOP/VOP/CHOP/ROP are
    rejected.
* **Errors are JSON-RPC protocol errors, never `isError: true` tool results.**
  Raw `hou` exceptions become `-32603 "Internal server error"` with the
  exception text buried in `data.details`. Examples: a bad node type
  (`OperationFailed: Invalid node type name`) and a bad input index
  (`InvalidInput`). No candidate names or recovery hints are given.
* **The recommended target is about 28 tools and 8 resource templates**,
  expressed in `hou` vocabulary. It adds a sandboxed `houdini_python` escape
  hatch, a transactional `edit` batch tool (reusing the good `$ref` design of
  the hidden `graph.batch_edit`), and an image-returning `viewport_capture`.
  The document/HocusScript/source/production lanes would move off the default
  agent surface (§2, §7).

---

## 1. Inventory

### 1.1 Registration mechanism (where names really come from)

| Mechanism | Location | Count |
|---|---|---|
| `tool_specs` list of `(name, title, description, input_schema, annotations, handler)` tuples, registered in a loop | `live/operations.py:137-276` | 122 |
| `register_source_tools` → `_source_tool_definitions` | `live/ops/source_workspace.py:45,385` | 7 |
| `register_production_surface` | `live/ops/production.py:82` | 1 tool + 10 schema resources |
| Hidden ("legacy") set: `tools.set_listed(name, False)` | `live/operations.py:279-306` | 27 hidden, still dispatchable (`ToolRegistry.get` ignores `listed`) |
| Capability map | `live/ops/base.py:337` `_tool_capabilities` | — |
| Static resources | `live/operations.py:308-367` + production | 53 |
| Resource templates | `resource_templates_payload` / `read_dynamic_resource` (`live/ops/resources.py`) | 27 |
| Prompts | none (`core/server.py:951-972` has no `prompts/*` handler) | 0 |
| Server instructions | not set in `_initialize_payload` (`core/server.py:1137`) | — |

The dispatcher (`live/dispatcher.py`) only marshals callbacks onto the
Houdini main thread, via `hdefereval` in UI sessions or a worker thread in
hython. It registers nothing. `tools/list` is a single unpaginated page.
`listChanged` and `subscribe` are both `false`.

Non-standard per-tool fields are `outputSummary`, `executionHint`,
`failureNotes`, `examples` and `requiredCapabilities`. They inflate `tools/list`
but most clients never show them to the model. No tool declares an MCP
`outputSchema`, even though every tool returns `structuredContent`.

**Doc and code drift found:**
* `model.create_house_blockout` is referenced in `docs/agent-workflows.md` §3
  and in `core/server.py:_should_bump_graph_revision`. Its handler exists
  (`live/ops/high_level.py:304`), but it is **not registered**.
* `live/ops/building_ops.py` (815 LOC, 8 `building_*` handlers) is dead code:
  it is mixed into `LiveOperations`, but none of its handlers are registered.
* `docs/user-manual.md` §5 lists hidden `node.*`/`parm.*` tools as the core
  surface.

### 1.2 Tool counts by family (listed / hidden)

| Family | Listed / hidden | Model-visible size (listed) |
|---|---|---|
| Session/ops/tasks (`session.*`, `task.*`) | 6 / 0 | ~3 KB |
| Hip/scene/selection/playbar | 12 / 1 (`scene.diff`) | ~6 KB |
| Node CRUD (`node.*`, `object.create_geometry`) | 1 / 10 | 1.5 KB |
| Parms (`parm.*`) | 1 (`find_broken_refs`) / 7 | 0.5 KB |
| Graph query/patch (`graph.*`) | 1 (`check_errors`) / 9 | 0.5 KB |
| Network document (`document.checkout/validate/diff/apply/discard_checkout/query/sync_from_houdini`) | 7 / 0 | ~9 KB |
| HocusScript lane (`document.*_source`, `*_bundle`, `*plan*`, quarantines, recover) | 10 / 0 | ~8 KB |
| Source workspace (`source.*`) | 7 / 0 | ~9 KB |
| Production (`production.asset.qualify`) | 1 / 0 | **16.7 KB** |
| HDA (`hda.*`) | 12 / 0 | ~8 KB |
| Node types (`node_types.*`) | 4 / 0 | ~4.6 KB |
| Geometry / viewport / camera / snapshot | 6 / 0 | ~2.8 KB |
| Cook / render / export / lookdev | 8 / 0 | ~7 KB |
| PDG (`pdg.*`) | 9 / 0 | ~6 KB |
| USD/LOP (`usd.*`, `lop.create_node`) | 9 / 0 | ~7 KB |
| Materials (`material.*`) | 3 / 0 | ~3 KB |
| Deps/cache/package | 5 / 0 | ~4.5 KB |
| Validation/events (`scene.validate`, `graph.check_errors`, `parm.find_broken_refs`, `scene.events_recent`) | 4 / 0 | ~2 KB |
| **Total** | **103 / 27 = 130** | **~57 KB (~14k tokens)** |

**Appendix A** has the full per-tool table: name, handler module:line, schema
size, required properties, capabilities, read-only hint, family, verdict and
purpose.

### 1.3 Resources (53 static)

Grouped by kind:

* **Session (8):**
  * `houdini://session/{info,health,policy,conventions,scene-summary,selection,playbar,operations}`
* **Graph/scene caches (6):**
  * `houdini://graph/scene`, `houdini://graph/index`
  * `houdini://dependencies/scene`, `houdini://caches/topology`
  * `houdini://packages/preview`, `houdini://scene/events`
* **Tasks (1):** `houdini://tasks/recent`
* **Documents (3):**
  * `houdini://documents/scene`
  * `houdini://documents/hocusscript/fidelity/hs7`
  * `houdini://documents/schema/network-document/v1|v2`
* **Schemas (35).** Document/HocusScript schemas:
  * graph-spec v0.1–v0.5
  * expansion-map v1–v3
  * resolved-module-set v1–v3
  * compiled-bundle v0.4/v0.5
  * 8 input/output schemas for individual tools
  * apply-plan

  Production schemas: 5 schemas, each published twice under
  `hocuspocus://schemas/...` and `houdini://production/schema/...`. The two
  network-document schemas are also published under both schemes.

**About two-thirds of all resources are JSON Schemas** for HocusScript or
production carriers. None of these tells an agent anything about the user's
scene.

### 1.4 Resource templates (27)

* `hocus-source://{projectId}`
* `hocus-source://{projectId}/{relativePath}`
* `houdini://documents/network/{path}`
* `houdini://documents/checkouts/{checkout_id}`
* `houdini://documents/diagnostics/{checkout_id}`
* `houdini://documents/previews/{preview_id}`
* `houdini://documents/plans/{plan_id}`
* `houdini://usd/stage/{path}`
* `houdini://pdg/graph/{path}`
* `houdini://graph/subgraph/{path}`
* `houdini://graph/dependencies/{path}`
* `houdini://graph/references/{path}`
* `houdini://renders/graph/{path}`
* `houdini://nodes/{path}`
* `houdini://nodes/{path}/parms`
* `houdini://nodes/{path}/geometry-summary`
* `houdini://tasks/{task_id}`
* `houdini://tasks/{task_id}/log`
* about 9 static URIs re-listed as "templates"

### 1.5 Prompts

None. There is no `prompts/list` handler.

---

## 2. Families and verdicts

The target is a surface a model can hold in its head: names that read like
`hou` calls, few modes per tool, and Houdini paths as the only identity
system. Per-tool verdicts are in Appendix A.

| # | Family | Today | Verdict | Rationale |
|---|---|---|---|---|
| A | Session / operations | `session.info`, `list_operations`, `get_operation`, `cancel_operation` | **KEEP 1, MERGE rest** | `session.info` is a good orientation read. Fold `scene.get_summary` and conventions into it, and add `$HIP/$JOB/$HIPNAME`, unsaved state, the Houdini build and UI availability. `get_operation` is broker reconciliation plumbing: keep it, but mark it advanced. `list_operations` should only be a resource. Cancellation belongs in `task`. |
| B | Hip / selection / time / undo | 12 tools | **MERGE → `hip`, `undo`, `selection`, `time`** | `hou.hipFile` is one concept: `hip(action=new/open/save/save_as/merge)`. Today `open_hip` and `new` default to `suppress_save_prompt=True`, which **silently discards unsaved work**; require `discard_unsaved: true` when `hasUnsavedChanges()` is true. There is no frame-range or FPS setter. The undo expected-label guard (`houdini_undo.py`) is good: keep it, and add `history`. |
| C | Node CRUD | 10 hidden + `object.create_geometry` | **REDESIGN → `node_create`, `node_delete`, `node_edit`, `node_copy`, `connect`, `layout`** | The hidden versions are close to `hou` but have defects: no tuples, no named inputs, raw errors. The grid in `node.move` rejects legal coordinates (measured: `x=-10` fails "outside the managed grid bounds"). `object.create_geometry` is a special case that only exists because `node.create` was hidden. CUT it. |
| D | Parms | 7 hidden + broken-ref finder | **REDESIGN → `parm_get`, `parm_set`** | This is the most important family, and the listed surface lacks it. The document v2 lane already has the hard parts (ramp, multiparm, keyframes, channel refs, menu tokens, quantities: `docs/schemas/network-document-v2.schema.json` `$defs`). Move that typed value engine behind `parm_set`. |
| E | Graph index (`graph.*`, `scene.diff`) | 10 hidden | **MERGE → `node_find`, `node_info`; CUT diffs** | `graph.query` is served from a snapshot that walks *every node and every parm in the scene* and evaluates each parm (`graph.py:138-197`). It also descends into locked-HDA internals. For 5 SOPs it returned 67 nodes and 47 KB. Use `glob`/`recursiveGlob`/`allSubChildren(recurse_in_locked_nodes=False)` with field projection instead. The baseline-diff tools need the agent to hold a 2 MB baseline. |
| E′ | `graph.batch_edit` / `plan_edit` / `apply_patch` | hidden | **REDESIGN → `edit`** | Ordered ops in one undo group with `$ref:id` symbolic references (`high_level.py:70-75, 244-300`). This is the most agent-friendly design in the repo, and it is hidden. Promote it as `edit(ops[], dry_run?)`. |
| F | Network document (`document.checkout/validate/diff/apply/...`) | 7 listed | **CUT from default surface** (keep internals for transaction verify/rollback) | It replaces Houdini's model with a parallel object model: `uid`, `nodeUid`, `binding:*`, `documentRevision`, `baselineLiveRevision`, `ports`, `codeBlobs`. It serializes *every* parm, including defaults and locked-HDA internals: 1.37 MB / 4,728 bindings for 5 SOPs, and 2.1 MB for the network resource. It cannot be held in context. Revision gating and rollback verification are valuable as server-side semantics of `edit`. |
| F2 | HocusScript lane (compile/format/complete/export source, preview/plan/apply/discard bundle, quarantines, recover) | 10 listed | **CUT from agent surface** → separate optional server or CLI | It is a new language the model has never seen, with five versions and a 1,192-line spec. `document.export_source` on a trivial hand-built SOP chain took **55 s**, returned **785 KB**, and was **blocked**. Every node was rejected with HOCUS803 ("requires persistent_user_data identity"), so it does not round-trip scenes built by hand. |
| G | Source workspace (`source.*`) | 7 | **CUT** | This is an IDE for `.hocus` files (search, read, patch, build, navigate). Agent clients already have filesystem tools. These tools also write files while declaring only `observe` (`source.file.apply_patch`, `source.file.write_export`, `source.project.build`). The gate is workspace grants instead, so the capability model does not show it. |
| H | Production (`production.asset.qualify`) | 1 | **CUT** | Its input schema is 15.8 KB, about 4k tokens in every session. By design it always returns advisory output with both readiness flags false (`docs/agent-workflows.md`), so it gives an agent nothing. |
| I | HDA | 12 | **MERGE → one `hda` tool + reads in `node_info`/`node_type_info`** | The read tools overlap (`get_definition`, `get_instance`, `get_interface`). Missing actions: unlock (`allowEditingOfContents`), save (`updateFromNode`), lock or match (`matchCurrentDefinition`), general interface editing (add a parm or folder, not just promote), and section edits. `set_instance_parms` exists only because `parm.set` is hidden. |
| J | Node types | 4 | **REDESIGN → `node_type_search`, `node_type_info`** | It uses heuristic substring-driven tags (`node_types.py:24-75`) and a curated "task" enum (`list_compatible`). Only four categories work (`Cop` measured as "Unsupported discovery category"). There is no help text. It returns 32 KB for 100 SOP types. `info` should return input/output *labels*, max inputs, parm templates and a help excerpt. `catalog_provider.py` already extracts connectors, menus, multiparm and ramp contracts; reuse it. |
| K | Geometry | `geometry.get_summary` | **REDESIGN → `geo_info`, `geo_read`** | Today it returns counts, bbox, and group and attribute *names* only. **Detail attributes are missing entirely** (`base.py:678-705`). There are no types, sizes or values, no group counts, no prim-type histogram, no intrinsics and no sampling. |
| L | Viewport / camera / snapshot | 4 | **MERGE → `viewport` + REDESIGN `viewport_capture`** | `viewport.capture` and `snapshot.capture_viewport` share one implementation (`viewport.py:54-91`). Neither returns MCP `image` content, so the model cannot see the result. `camera.get_active` is a superset of `viewport.get_state`. Both require a UI. There is no headless fallback. |
| M | Tasks / cook | `cook.node`, `task.list`, `task.cancel` | **REDESIGN → `cook` (sync with timeout, async opt-in) + `task`** | `cook.node` is always asynchronous: the agent has to poll `houdini://tasks/{id}` to learn whether a 5 ms SOP cook failed. Errors come from the target node only, not from the upstream node that originated them. `hou.OperationFailed` from `node.cook()` is not translated. |
| N | Render / export / lookdev | `render.rop`, `render.inspect_graph`, `render.inspect_outputs`, `render.preflight`, `export.alembic`, `export.usd`, `lookdev.*` | **KEEP `render` (merge inspect); CUT exports and recipes** | Exports are just ROPs. The light rig is a recipe, not an API. |
| O | PDG/TOPs | 9 | **MERGE → `pdg`** (status/cook/cancel/dirty/workitems/logs) | The functionality is reasonable but split nine ways. `get_graph_state`, `get_workitems` and `houdini://pdg/graph/{path}` overlap. |
| P | USD/LOPs | 9 | **REDESIGN → `usd_stage`; CUT creators** | `usd.add_reference`, `set_variant`, `assign_material`, `create_layer_break` and `lop.create_node` are thin wrappers over "create a LOP and set parms". Inspection lacks prim attributes and values, xform, purpose, visibility, traversal with patterns, layer stack and opinion sources. |
| Q | Materials | 3 | **CUT** (or one recipe/prompt) | They hard-code legacy Principled Shader under `/mat` with `shop_materialpath` assignment. That is not the H22 Karma/MaterialX/LOP idiom. |
| R | Deps / cache / package | 5 | **KEEP `dependencies` (scan + repath); CUT cache/package** | Missing-file scanning is valuable. Packaging is pipeline functionality, not agent driving. |
| S | Validation / events | 4 | **MERGE → `problems` + `events`** | `scene.validate`, `graph.check_errors`, `parm.find_broken_refs`, `usd.validate_stage` and `render.preflight` are five partial "what is wrong" reads. None of them reports node errors or warnings, the most common failure. The event monitor is good: keep it as `events(since)`. |
| T | Recipes | `scene.create_turntable_camera`, `lookdev.create_three_point_light_rig` | **CUT** → MCP prompts or doc snippets | Opinionated content generators. With `edit` or `houdini_python` they become ten-line recipes. |

---

## 3. Idiom check: where the API fights Houdini

| Houdini concept | Current mapping | Problem |
|---|---|---|
| **Node paths** (`hou.node('/obj/geo1')`) | Used for low-level tools and resources. The document lane switches to `uid: "node-session:10"`, `nodeUid`, `binding:node-session:10:bank`. HocusScript adds `@id("...")` and needs `persistent_user_data` identity. | Two identity systems. The agent has to map `uid` ↔ path, and the "session" uids are not stable. Houdini already has paths plus `hou.Node.sessionId()`. |
| **Parm tuples** (`t`, `size`, `Cd`) | `_require_parm_by_path` uses `hou.parm()` only (`base.py:243-258`) | `parm.get /obj/geo1/box1/size` → "Parameter not found" (measured). The agent has to know component naming (`sizex/sizey/sizez`, `colorr/g/b`). Fix: `hou.parmTuple()` fallback, and accept list values. |
| **Raw vs evaluated vs expression vs keyframes** | `_parm_summary` returns `rawValue`, `value` and `expression` (`base.py:114-123`). `parm.set` calls `parm.set(value)`, which **edits the current keyframe if one exists**. `parm.set_expression` exists. | There is no keyframe API on the low-level path (only document v2 `animations`). There is no `deleteAllKeyframes`, no channel-reference helper, no lock state, and no "is animated" flag. `parm.expression()` raises on non-expression parms and is swallowed to `None`, which hides the difference between "no expression" and "error". |
| **Menus** | `menuItems`/`menuLabels` only on type info (`node_types.py`) | When the agent sets a menu parm it has to guess whether to send the token or the index. Return `menu: [{token, label}]` and accept either. |
| **Multiparms / ramps** | Only in the document v2 lane (`rampBinding`, `multiparmBinding`) | The low-level path cannot set a `hou.Ramp` or an instance count without knowing internal naming (`ramp1pos`, `#`). |
| **Inputs and outputs** | `node.connect(dest_input_index, source_output_index)`. `_node_summary.inputs` is paths only (`base.py:131-134`). Graph edges omit the output index (`graph.py:96-106`). | No named inputs (`inputNames`, `inputLabels`, `setNamedInput`, `inputIndex`), so the model sees "input 1" instead of "Collision". The source output index is lost on read, so multi-output nodes (Split, Block End, Vellum Solver) cannot be read back. Bad index → raw `hou.InvalidInput` (measured). Nothing appends to a Merge node's next free input. |
| **Network contexts** (OBJ/SOP/LOP/TOP/COP/DOP/VOP/CHOP/ROP) | Discovery supports `Object`, `Sop`, `Lop` and `Top` only. Documents are SOP-first. Materials hard-code `/mat` and `shop_materialpath`. | COP (Copernicus), DOP, VOP/MAT, CHOP and ROP authoring are absent or rejected. The model learns HocusPocus's category list instead of `hou.NodeTypeCategory`. |
| **Subnets / HDAs / locked internals** | The graph snapshot recurses into **locked HDA internals**. The 5-node chain produced 67 nodes, mostly mountain's internal attribvop. | Houdini's UI hides locked contents. The agent drowns in VOP internals it cannot edit. Default to `recurse_in_locked_nodes=False`. |
| **Cook / dirty** | Async `cook.node` task. `needsToCook`, `isTimeDependent` and `cookCount` are only used in production observation code. | Houdini's model is "cook, then read errors on the node". Agents need a synchronous `cook(path) → {ok, errors, warnings, ms, summary}`. |
| **Errors / warnings** | `node.errors()/warnings()/messages()` are read only inside the cook task (`tasks_ops.py:13-36`) | There is no read-only "what is red in this network" query. |
| **Flags** | `node.set_flags` (hidden): bypass, display, render, template | Fine, but hidden. Missing `lock` (soft/hard), `highlight` and `selectable`. OBJ display-node vs SOP display-flag semantics are not explained. |
| **Node positions** | A managed 12×64 grid stored in node userData (`hpmcp.grid.*`) and parent state (`base.py:24-31, 707-737`). `node.move` rejects positions outside the grid. | Houdini already has `layoutChildren()`, `moveToGoodPosition()`, network boxes and dots. The grid writes HocusPocus metadata into the user's `.hip` and refuses legal coordinates. |
| **Geometry attributes and groups** | Names only | `hou.Geometry` exposes class, type, size, typeInfo, values, intrinsics and group membership. None of it is surfaced. |
| **Python / HScript / VEX** | No exec tool. A wrangle `snippet` can be written via hidden `parm.set` with `edit_scene` only. Python parm expressions via `parm.set_expression(language=python)` also need only `edit_scene`. | An inconsistent trust model. Code effectively runs through parm expressions without `run_code`, while the documented `procedural-authoring` profile is required for document code blobs (`document_apply.py:868-875`). The idiomatic escape hatch (sandboxed `hou` Python) does not exist. |
| **Undo** | Every mutation is wrapped in `hou.undos.group(...)`. `scene.undo/redo` have a label guard. | Good. Keep it. |
| **Events** | `SceneEventMonitor` installs `hipFile`, node, selection and playbar callbacks (`monitor.py:58-90, 377-410`). Exposed only as polled `scene.events_recent` / `houdini://scene/events`. | Good foundation. Expose it as a cursor, or implement `resources/subscribe`. |

### Invented abstractions an agent must learn

1. **The network document.** A 24-key top-level object (`ports`,
   `parameterBindings`, `codeBlobs`, `layoutConstraints`, `timeSamples`, ...)
   with 45 `$defs`. It has two versions, and each schema is published under
   two URI schemes. It uses its own apply modes (`reconcile`/`merge`/
   `validate_only`) and three revision counters. `reconcile`, the documented
   default for checkout flows, **deletes live nodes missing from the target**.
   That is a dangerous default for a model editing a truncated JSON.
2. **HocusScript.** A DSL with modules, imports, control flow, `@id`,
   lockfiles and external module roots. It comes with bundles (versions
   0.2–0.5), content-addressed previews, immutable plans
   (`planId/planHash/idempotencyKey`, leases), quarantines and
   `recover_scope`. About 450 distinct `HOCUSnnn` codes.
3. **Source workspace.** Opaque `projectId`s, grants, exact-digest patching
   and `write_export` handoffs.
4. **Production carriers.** Asset contract, build provenance, publish gate,
   qualification.
5. **The managed grid** (see above).
6. **Checkout generations.** `checkout_id` is rejected after a host restart
   (`core/server.py:_require_generation_checkout`).

None of this is Houdini vocabulary. A model trained on SideFX docs and
forums already knows `hou.node`, `parm`, `parmTuple`, `setInput`, `cook`,
`geometry().pointAttribs()`, `glob` and `layoutChildren`. The cheapest
interface is one that uses those words.

---

## 4. Gap analysis

Legend: **OK** = adequate. **Weak** = present but limited. **Hidden** = works
but is not in `tools/list`. **Doc-lane** = only via network document v2.
**Missing** = not available.

| Need | Status | Evidence / notes |
|---|---|---|
| Hip new/open/save/save-as/merge | OK–Weak | `scene.*`. New and open discard unsaved changes silently by default. Load warnings are not returned. |
| Recent files / unsaved state | Weak / Missing | `hipDirty` only. No recent-files or backup info. |
| `hou.hipFile` events | Weak | Monitor captures them; polling only |
| `$HIP`, `$JOB`, `$HIPNAME`, env, `expandString` | **Missing** | Not in `session.info` or `scene.get_summary`; no env or expand tool |
| Node create / delete / rename | Hidden | `node.create/delete/rename` |
| Move / layout | Hidden + wrong abstraction | The grid rejects legal positions. `node.layout` is the grid layout, not `layoutChildren`. |
| Copy / paste / duplicate | **Missing** | `copyNodesTo` is used only inside document apply (`document_apply.py:109`) |
| Network boxes / sticky notes / dots / comments / color | Doc-lane | `document_editor_entities.py` |
| Wire by index | Hidden | `node.connect` |
| Wire by named input | **Missing** | No `inputNames`/`inputLabels`/`setNamedInput` anywhere in `live/` |
| Output index on read | **Missing** | Use `inputConnections()` |
| Parm set raw value | Hidden | `parm.set` |
| Parm set tuple | **Missing** | Measured "Parameter not found" for `size` |
| Parm set expression | Hidden | `parm.set_expression` (hscript/python) |
| Keyframes | Doc-lane | No direct tool |
| Channel reference | Doc-lane | `channelBinding` |
| Evaluated vs raw read | OK (hidden) | `rawValue`, `value` and `expression`. No unexpanded vs expanded string distinction beyond `rawValue`. |
| Multiparm / ramps | Doc-lane | |
| Menu labels / tokens on a live parm | Weak | Type info only |
| Spare parms / parm templates | Weak | HDA promote only |
| Cook node | Weak | Async only, target-node errors only |
| Errors / warnings read | **Missing** | Only inside cook-task results |
| Geometry counts / bbox | OK | `geometry.get_summary` follows OBJ display SOP |
| Attribute class/type/size | **Missing** | Names only |
| Detail attributes | **Missing** | `globalAttribs()` never read |
| Attribute values / sampling / spreadsheet | **Missing** | |
| Groups (counts, membership, edge groups) | Weak | Point and prim group names only |
| Prim types / intrinsics (packed, volume, VDB) | **Missing** | |
| Screenshot the model can see | **Missing** | It writes a file and returns its path (`viewport.py:54-73`). The client must read the file separately, and only if it shares a filesystem. |
| Flipbook (range) | **Missing** | Single frame only |
| Render to image (headless preview) | Weak | `render.rop` writes files asynchronously. No preview or thumbnail is returned. |
| Camera control (frame selected, set view) | **Missing** | Read-only camera info |
| Python exec (sandboxed `hou`) | **Missing** | `run_code` capability is unused for this |
| HScript exec | **Missing** | |
| VEX test | **Missing** | Would need a wrangle via hidden tools |
| Node-type / parm help | **Missing** | No `helpUrl`, `embeddedHelp` or parm-template `help()` |
| Undo / redo | OK | Label guard. No history listing. |
| Selection | OK | |
| Display flag | Hidden | `node.set_flags` |
| Current frame | OK | |
| Frame range / FPS set | **Missing** | Read only, via `hou.playbar` (UI-only) |
| TOPs cooking | OK–Weak | 9 tools; async |
| LOP stage inspection | Weak | No attributes, values, xforms, layer stack or opinion sources. Prim list is "a prim-path sample". |
| HDA create | OK | `hda.create_from_subnet` |
| HDA edit / save / interface | Weak | Promote-parm and version only |
| Scene event watching | Weak | Polling only; `resources.subscribe=false` |
| Multiple Houdini instances | **Missing** | Fixed port 37219 (`core/settings.py:77`, `core/stdio_bridge.py:1157`). No instance registry or selection. A second Houdini cannot serve. |
| Headless (hython) awareness | Partial | Viewport, selection and playbar tools need UI. Schemas do not say so; the failure is a runtime `INVALID_PARAMS`. |

---

## 5. Response design

### Measured sizes

5-node SOP chain `box → polyextrude → mountain → attribwrangle → null`, plus
3 LOPs:

| Call | Bytes | Notes |
|---|---|---|
| `session.info` | 3.6 KB | Fine |
| `houdini://session/info` | 10.2 KB | The resource is about 3× the tool for the same concept |
| `scene.get_summary` | 1.1 KB | Fine |
| `node.get` | 0.55 KB | Fine |
| `node.get include_parms` / `parm.list` (40 parms) | 7.0–7.3 KB | All parms including defaults; no non-default filter |
| `geometry.get_summary` | 0.57 KB | Small because it is shallow |
| `node_types.list category=Sop` | 32 KB | 100 types per page |
| `node_types.get_info` / `full_parms` | 2.2 / 6.0 KB | |
| `graph.query root=/obj/geo1` | 47 KB | 67 nodes: recursed into HDA internals |
| `document.query root=/obj/geo1` | 50 KB | Same |
| `document.checkout /obj/geo1` | 0.85 KB + **1.37 MB** resource | Over the 1 MB inline limit (`document.py:59`) |
| `houdini://documents/network/obj/geo1` | **2.1 MB** | 4,728 parameter bindings |
| `houdini://graph/scene` | **2.06 MB** | Near-empty scene; the full-scene walk evaluates every parm |
| `document.export_source /obj/geo1` | **785 KB, 55 s** | Blocked: HOCUS803 |

### Findings

* **Data lives in `structuredContent`, while `content[0].text` is a one-line
  summary** ("Listed 40 parameters.", `base.py:_tool_response`). MCP
  recommends that tools returning structured content also serialize it into a
  text block. Clients that only feed `content` to the model show it nothing
  useful. Clients that feed both pay twice. No `outputSchema` is declared.
* **Pagination is inconsistent:**
  * `parm.list` has `offset/limit/hasMore`.
  * `node.list` has `max_items` and silently truncates (no `hasMore`).
  * `graph.query` has `limit` and returns no total.
  * `tools/list` has none.
  * Most resources have none (`resources/list` paginates only the workspace
    part).

  There is no cursor convention.
* **There is no default response budget.** The inline caps are 1 MB for a
  checkout and 128 KB for a preview. The stdio broker allows 16 MB per
  message. For an LLM, 1 MB is about 250k tokens. The default should be about
  8–16 KB, with cursors or opt-in beyond that.
* **Default-heavy payloads.** Parm listings and documents include every
  parameter at its default. Houdini's own `opscript`/`.hip` model is
  "non-defaults only". `isAtDefault` is already computed (`graph.py:52-64`).
* **Inconsistent key casing.** Inputs are mostly snake_case (`node_path`),
  but the HocusScript tools use camelCase (`planId`,
  `expectedDocumentRevision`, `rootPath`). Outputs are camelCase.
* **A whole-scene snapshot is the backing store for reads.**
  `_graph_snapshot()` rebuilds the full scene graph whenever the monitor
  revision changes (`graph.py:199-204`). On production scenes (10^5–10^6
  parms), every query after an edit re-walks and re-evaluates the whole scene
  on the main thread. That is a latency and stability risk as well as a token
  cost.

---

## 6. Error design

* **Transport.** Every failure is raised as a JSON-RPC error
  (`core/operation_execution.py:162-177`). No tool ever returns
  `isError: true` (no `isError: True` anywhere in the package). MCP intends
  tool-execution errors to be returned as results with `isError`, so the
  model can read them and self-correct. JSON-RPC errors are meant for
  protocol faults, and some clients show them to the model only as a generic
  failure.
* **Envelope.** `{code, message, data: {errorFamily, retryable, ...}}`
  (`core/jsonrpc.py:18-62`). The families are request, unsupported,
  validation, auth, policy, cancelled, runtime and conflict. That is
  sensible, but `retryable` defaults to `true` for "runtime", which also
  covers deterministic `hou` failures.
* **Unmapped `hou` exceptions.** Any non-`JsonRpcError` becomes
  `-32603 "Internal server error"`, with `str(exc)` in `data.details`.
  Measured examples:
  * unknown node type → `OperationFailed ... Invalid node type name`
  * bad input index → `InvalidInput: Invalid input.`

  These are the two most common agent mistakes, and neither returns
  candidates ("did you mean `polyextrude::2.0`?") or the valid range.
* **Not-found errors** carry an `expectedFormat` example, which is good. They
  do not suggest the nearest existing path or parm. A tuple name gives
  "Parameter not found" with no hint that `sizex/sizey/sizez` exist.
* **About 450 `HOCUSnnn` codes**, almost all in the HocusScript and document
  lanes. They are precise for compiler diagnostics (JSON pointers, spans) but
  opaque without the spec. HOCUS755/756 (rollback-verified vs quarantined)
  are the useful ones; keep them as general `edit` outcomes.
* **Policy errors** (`-32010`, `missingCapabilities`) are clear. Keep them.
* **Recommended error result** (`isError: true` content plus structured
  data):

  `{code: "node_type_not_found", message, path, hint, candidates[], hou_exception}`

  Use a stable vocabulary of ≤ 25 codes, mapped from `OperationFailed`,
  `InvalidInput`, `InvalidNodeType`, `PermissionError` (locked HDA),
  `ObjectWasDeleted`, `TypeError`/`ValueError` on set, and cook errors.

---

## 7. Proposed surface (≈28 tools, 8 resource templates)

Names use `snake_case` without dots, because several model APIs restrict tool
names to `[A-Za-z0-9_-]` and so clients rewrite dotted names. Every tool
takes Houdini paths. Every mutation runs in one `hou.undos.group`, returns
compact summaries of the changed nodes plus their cook errors, and carries an
operation ID for reconciliation.

| Group | Tool | Notes |
|---|---|---|
| Session | `houdini_status` | Build, UI or headless, hip path, `$HIP/$JOB`, dirty flag, frame/fps/range, capabilities, instance id |
| | `houdini_instances` | List and select running hosts (port registry; broker-level) |
| Hip | `hip` | new / open / save / save_as / merge. Refuses to discard unsaved changes without `discard_unsaved`. Returns load warnings. |
| Find/read | `node_find` | Glob, type, category, flag and error-state filters. `recurse_locked=false`. Field projection. Cursor. |
| | `node_info` | Paths. `include`: parms (non-default by default), inputs (index, name, label, source output), outputs, errors, children, hda, deps |
| Mutate | `node_create` | Batched. Type fuzzy-resolved with candidates; name; inputs by index or name; parms |
| | `node_delete` | Paths, `keep_connections` |
| | `node_edit` | Rename, flags (incl. lock), color, comment, position |
| | `node_copy` | Copy or duplicate to a parent (`copyNodesTo`) |
| | `connect` | `[{from, from_output, to, to_input (index \| name \| "next")}]`; `from: null` disconnects |
| | `layout` | `layoutChildren` / `moveToGoodPosition`; optional network boxes and notes |
| | `edit` | Ordered op list with `$ref` ids and `dry_run`. Transactional (rollback-verified, from the document lane's integrity code). |
| Parms | `parm_get` | Parm *or tuple*. Raw, evaluated, expression and language, keyframes summary, lock, menu `{token, label}`, ramp, multiparm, template type, default flag |
| | `parm_set` | `[{path, value \| expression+language \| keys \| ref \| ramp \| multiparm_count \| revert \| press}]`. Tuple-aware. Reports whether a key was written. |
| Cook/diag | `cook` | Sync with timeout (escalates to a task). Errors and warnings with originating node, time, counts. |
| | `problems` | Errors and warnings in a subtree, broken refs, missing files, bad output paths |
| Geometry | `geo_info` | Counts, prim-type histogram, bbox, attributes (class/type/size/typeInfo), detail values, groups with counts, packed/volume intrinsics |
| | `geo_read` | Spreadsheet query: class, attribs, start/count/stride, group or expression filter, per-attribute stats (min/max/mean/unique), cursor |
| Visual | `viewport_capture` | Returns MCP `image` (size-capped). Camera, frame, home/frame-selected, resolution. Headless OpenGL-ROP fallback. |
| | `render` | ROP over frames (task). Inspect outputs and AOVs. Optional thumbnail. |
| Code | `houdini_python` | Exec `hou` Python in an undo group, under `run_code`. Captured stdout/stderr and a JSON return value. `language=hscript` option. |
| Types/help | `node_type_search` | All categories. Name, label and keyword match. Compact. |
| | `node_type_info` | Input/output labels, max inputs, parm templates (name, type, default, menu, range), help excerpt, `helpUrl` |
| State | `undo` | undo / redo / history (existing label guard) |
| | `time` | Get or set frame, range, fps |
| | `selection` | Get or set |
| Contexts | `usd_stage` | Prim traversal (pattern, type, depth), attributes and values at time, xform, purpose, bindings, composition arcs, layer stack |
| | `pdg` | status / cook / cancel / dirty / workitems / logs |
| | `hda` | create from subnet, unlock, save (`updateFromNode`), match/lock, interface add/promote/remove, libraries list/install/reload |
| Files | `dependencies` | scan / repath |
| Events | `events` | `since` cursor over the monitor feed |
| Tasks | `task` | status / list / cancel |

**Resources:**

* `houdini://hip`
* `houdini://node/{path}`
* `houdini://node/{path}/parms`
* `houdini://node/{path}/geometry`
* `houdini://node-type/{category}/{name}`
* `houdini://help/{category}/{name}`
* `houdini://usd/{lop_path}/prim/{prim_path}`
* `houdini://task/{id}`

**Prompts (new, optional):**

* `inspect-scene`
* `build-sop-network`
* `debug-red-node`
* `turntable-and-lights` (replaces the cut recipe tools)
* `karma-materialx-lookdev`

**What moves off the default surface:**

* document/checkout/HocusScript/plan/bundle/source/production tools. Ship
  them as a separately registered optional server or the existing CLI, gated
  by a profile.
* schema resources
* recipe tools
* duplicate tools

**What is worth reusing behind the new surface:**

* the typed value engine (`document_typed_*`, `catalog_provider.py`) for
  ramps, multiparms, keyframes, channel refs and menu tokens
* mutation integrity and rollback verification (`document_mutation_integrity.py`)
* the operation journal and broker reconciliation
* the scene event monitor
* the undo label guard
* the policy and path-root checks

---

## 8. Top 10 recommendations (ranked)

1. **Expose real, idiomatic primitives on the default surface.**
   `node_create`, `connect` (index *and* name), `parm_get`/`parm_set`
   (tuple-aware; value, expression, keys, ref, ramp, multiparm), `node_edit`,
   `node_delete`. Today they are hidden, and the listed alternative is a
   1.4 MB document round-trip.
2. **Add `houdini_python` (with HScript) under `run_code`.** It is the
   universal escape hatch that matches what models know best. It also closes
   today's inconsistency, where Python *expressions* and wrangle snippets
   already run code under `edit_scene` alone.
3. **Return images.** `viewport_capture` should return MCP `image` content
   (size-capped), with a headless OpenGL-ROP fallback. Visual feedback is
   currently impossible for a client that does not share the filesystem.
4. **Make cook and diagnosis synchronous and honest.** `cook` returns errors,
   warnings, the originating node and timing. `problems` consolidates the
   five partial validators and adds node error/warning scanning.
5. **Make geometry legible.** `geo_info` covers attribute class, type and
   size, detail values, group counts and prim types. `geo_read` is a
   paginated spreadsheet with stats. This is how an agent verifies what it
   built.
6. **Move the document, HocusScript, source and production lanes off the
   agent surface.** That removes about 35 tools, about 40 schema resources
   and roughly 9k tokens of `tools/list`. Keep their transactional internals
   behind `edit`.
7. **Return tool failures as `isError: true` results with a small, stable
   code set plus `hint` and `candidates`.** Map `hou` exceptions. Never send
   "Internal server error" for a user-level mistake.
8. **Set a response budget and a single pagination convention.** Default
   about 8–16 KB, `cursor`/`nextCursor` everywhere, non-default parms only,
   no recursion into locked HDAs, and field projection (`include=[...]`). Put
   the JSON in the text content, or declare `outputSchema` consistently.
9. **Replace the whole-scene graph snapshot as the read path** with scoped
   direct `hou` queries. Drop the managed grid in favor of
   `layoutChildren`/`moveToGoodPosition`. Stop writing `hpmcp.*` userData into
   user scenes unless it is required for reconciliation.
10. **Fill in Houdini lifecycle and context gaps:**
    * hip safety (no silent discard; `$HIP`/`$JOB`; load warnings)
    * frame range and FPS
    * named inputs and output indices on read
    * help and discovery for *all* categories (COP, DOP, VOP, CHOP, ROP)
    * HDA unlock/save/interface editing
    * `events(since)`
    * multi-instance discovery

    Fix the doc drift (user manual lists hidden tools; the unregistered
    `model.create_house_blockout`; dead `building_ops.py`).

---

## Appendix A — Full tool inventory (130 registered)

The "Module:line" column points at the **handler definition**. Registration
happens at `live/operations.py:137-276` (the `tool_specs` list),
`live/ops/source_workspace.py:385` (source tools) and
`live/ops/production.py:82` (production). Schema B is the serialized
`inputSchema` size in bytes. Capabilities come from
`base.py:_tool_capabilities`. RO is the `readOnlyHint`. HIDDEN means
`listed=False` but still callable. The verdict column maps each tool to its
§7 replacement.

| # | Tool | Listed | Module:line (handler) | Props (required) | Schema B | Capabilities | RO | Family | Verdict | Purpose |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `session.cancel_operation` | yes | live/ops/session.py:96 | 1 (operation_id) | 100 | observe |  | A Session | MERGE->task | Request cancellation for a queued or running dispatcher operation by operation id. |
| 2 | `session.get_operation` | yes | live/ops/session.py:76 | 1 (operation_id) | 163 | observe | Y | A Session | KEEP (internal/broker) | Reconcile one admitted operation by its stable identity without replaying its mutation. |
| 3 | `session.info` | yes | live/ops/session.py:62 | 0 (-) | 36 | observe | Y | A Session | KEEP (merge w/ scene summary) | Return Houdini session state, server version, active operations, recent tasks, and orientation conventions. |
| 4 | `session.list_operations` | yes | live/ops/session.py:67 | 1 (-) | 79 | observe | Y | A Session | CUT (resource only) | List recent live dispatcher operations, including request ids, states, and cancellation flags. |
| 5 | `playbar.get_state` | yes | live/ops/scene.py:214 | 0 (-) | 36 | observe | Y | B Hip/scene | MERGE->time | Return current frame, FPS, and playbar ranges from the live Houdini session. |
| 6 | `playbar.set_frame` | yes | live/ops/scene.py:228 | 1 (frame) | 86 | edit_scene |  | B Hip/scene | MERGE->time | Set the current Houdini frame and return the updated playbar state. |
| 7 | `scene.get_summary` | yes | live/ops/scene.py:57 | 0 (-) | 36 | observe | Y | B Hip/scene | MERGE->hip_info | Return a compact scene summary with hip path, dirty state, frame information, selection, and orientation conventions. |
| 8 | `scene.merge_hip` | yes | live/ops/scene.py:100 | 1 (path) | 84 | edit_scene |  | B Hip/scene | MERGE->hip | Merge a hip file into the current scene without replacing the session. |
| 9 | `scene.new` | yes | live/ops/scene.py:70 | 0 (-) | 36 | edit_scene |  | B Hip/scene | MERGE->hip | Start a new empty Houdini scene in the current session. |
| 10 | `scene.open_hip` | yes | live/ops/scene.py:88 | 3 (path) | 209 | edit_scene |  | B Hip/scene | MERGE->hip | Load a hip file into the current Houdini session. |
| 11 | `scene.redo` | yes | live/ops/scene.py:176 | 1 (-) | 106 | edit_scene |  | B Hip/scene | MERGE->undo | Redo the last undone Houdini operation in the current session. |
| 12 | `scene.save_hip` | yes | live/ops/scene.py:128 | 2 (-) | 124 | edit_scene,write_files |  | B Hip/scene | MERGE->hip | Save the current scene to the existing hip path or to a new explicit path. |
| 13 | `scene.undo` | yes | live/ops/scene.py:154 | 1 (-) | 106 | edit_scene |  | B Hip/scene | MERGE->undo | Undo the last Houdini operation in the current session. |
| 14 | `selection.get` | yes | live/ops/scene.py:184 | 0 (-) | 36 | observe | Y | B Hip/scene | MERGE->selection | Return the currently selected node paths in the live Houdini session. |
| 15 | `selection.set` | yes | live/ops/scene.py:201 | 2 (paths) | 170 | edit_scene |  | B Hip/scene | MERGE->selection | Set the selected node paths in the live Houdini session. |
| 16 | `node.connect` | HIDDEN | live/ops/node.py:420 | 4 (source_node_path,dest_node_path) | 277 | edit_scene |  | C Node CRUD | REDESIGN->connect | Connect a source node output to a destination node input and return the destination node summary. |
| 17 | `node.create` | HIDDEN | live/ops/node.py:78 | 5 (node_type_name) | 304 | edit_scene |  | C Node CRUD | REDESIGN->node_create | Create a Houdini node under a parent network and return the created node summary. |
| 18 | `node.delete` | HIDDEN | live/ops/node.py:381 | 3 (-) | 176 | edit_scene |  | C Node CRUD | KEEP->node_delete | Delete one or more nodes by explicit path. |
| 19 | `node.disconnect` | HIDDEN | live/ops/node.py:440 | 2 (path) | 120 | edit_scene |  | C Node CRUD | MERGE->connect | Disconnect one input or all inputs from a node and return the updated node summary. |
| 20 | `node.get` | HIDDEN | live/ops/node.py:43 | 2 (path) | 140 | observe | Y | C Node CRUD | REDESIGN->node_info | Return summary information for a single node, including flags, inputs, display/render/output node pointers, and optionally parameter summ... |
| 21 | `node.layout` | HIDDEN | live/ops/node.py:530 | 2 (-) | 151 | edit_scene |  | C Node CRUD | REDESIGN->layout (hou.layoutChildren) | Auto-layout child nodes under a network and return the resulting child listing. |
| 22 | `node.list` | HIDDEN | live/ops/node.py:33 | 3 (-) | 190 | observe | Y | C Node CRUD | REDESIGN->node_find | List child nodes under a network path, optionally recursively. |
| 23 | `node.move` | HIDDEN | live/ops/node.py:485 | 3 (path,x,y) | 144 | edit_scene |  | C Node CRUD | REDESIGN->node_edit (drop grid) | Move a node in network-editor space by setting its graph position. |
| 24 | `node.rename` | HIDDEN | live/ops/node.py:402 | 3 (path,new_name) | 182 | edit_scene |  | C Node CRUD | MERGE->node_edit | Rename a node and return the updated node summary. |
| 25 | `node.set_flags` | HIDDEN | live/ops/node.py:549 | 5 (path) | 211 | edit_scene |  | C Node CRUD | MERGE->node_edit | Set common node flags such as bypass, display, render, and template, then return the updated node summary. |
| 26 | `object.create_geometry` | yes | live/ops/node.py:336 | 2 (-) | 220 | edit_scene |  | C Node CRUD | CUT (node_create covers it) | Create one Geometry object under `/obj` and immediately return a document-centric checkout of its editable SOP network. |
| 27 | `parm.get` | HIDDEN | live/ops/parm.py:62 | 1 (parm_path) | 94 | observe | Y | D Parms | REDESIGN->parm_get | Return metadata and value information for a single parameter path. |
| 28 | `parm.list` | HIDDEN | live/ops/parm.py:53 | 5 (node_path) | 257 | observe | Y | D Parms | MERGE->parm_get | List parameters on a node and return normalized parameter summaries. |
| 29 | `parm.press_button` | HIDDEN | live/ops/parm.py:137 | 1 (parm_path) | 94 | edit_scene |  | D Parms | MERGE->parm_set(press) | Press a button parameter and return the resulting parameter summary. |
| 30 | `parm.revert_to_default` | HIDDEN | live/ops/parm.py:162 | 1 (parm_path) | 94 | edit_scene |  | D Parms | MERGE->parm_set(revert) | Revert a parameter to its default value and return the updated parameter summary. |
| 31 | `parm.set` | HIDDEN | live/ops/parm.py:77 | 2 (parm_path,value) | 116 | edit_scene |  | D Parms | REDESIGN->parm_set | Set a parameter value and return the updated parameter summary. |
| 32 | `parm.set_expression` | HIDDEN | live/ops/parm.py:125 | 3 (parm_path,expression) | 196 | edit_scene |  | D Parms | MERGE->parm_set | Set an HScript or Python expression on a parameter and return the updated parameter summary. |
| 33 | `parm.set_many` | HIDDEN | live/ops/parm.py:104 | 1 (assignments) | 224 | edit_scene |  | D Parms | MERGE->parm_set | Set many parameter values in one request and one undo group. |
| 34 | `graph.apply_patch` | HIDDEN | live/ops/graph.py:702 | 5 (-) | 275 | edit_scene |  | E Graph query/patch | MERGE->edit | Apply a graph patch using the current batch-edit execution path. |
| 35 | `graph.batch_edit` | HIDDEN | live/ops/high_level.py:244 | 3 (operations) | 209 | edit_scene |  | E Graph query/patch | REDESIGN->edit (keep $ref model) | Apply a grouped set of node, parm, flag, move, connect, and layout operations in one live request and one undo block. |
| 36 | `graph.diff_subgraph` | HIDDEN | live/ops/graph.py:489 | 2 (root_path,baseline) | 138 | observe | Y | E Graph query/patch | CUT | Diff a current rooted subgraph against a previously captured baseline subgraph snapshot. |
| 37 | `graph.find_by_flag` | HIDDEN | live/ops/graph.py:374 | 4 (flag_name) | 225 | observe | Y | E Graph query/patch | MERGE->node_find | Return indexed graph nodes that match a named Houdini flag such as `display`, `render`, `bypass`, or `template`. |
| 38 | `graph.find_by_type` | HIDDEN | live/ops/graph.py:365 | 3 (node_type_name) | 183 | observe | Y | E Graph query/patch | MERGE->node_find | Return indexed graph nodes that match a Houdini node type name, optionally under a root path. |
| 39 | `graph.find_downstream` | HIDDEN | live/ops/graph.py:359 | 2 (path) | 133 | observe | Y | E Graph query/patch | MERGE->node_info(deps) | Traverse downstream structural input edges from a starting node path using the indexed scene graph. |
| 40 | `graph.find_upstream` | HIDDEN | live/ops/graph.py:353 | 2 (path) | 133 | observe | Y | E Graph query/patch | MERGE->node_info(deps) | Traverse upstream structural input edges from a starting node path using the indexed scene graph. |
| 41 | `graph.plan_edit` | HIDDEN | live/ops/graph.py:698 | 1 (operations) | 124 | observe | Y | E Graph query/patch | MERGE->edit(dry_run) | Simulate a grouped graph patch against the current indexed scene graph and return the predicted diff without mutating Houdini. |
| 42 | `graph.query` | HIDDEN | live/ops/graph.py:305 | 9 (-) | 360 | observe | Y | E Graph query/patch | MERGE->node_find | Query the indexed scene graph by path prefix, root path, node type, category, flag, name fragment, or material assignment. |
| 43 | `scene.diff` | HIDDEN | live/ops/graph.py:475 | 1 (baseline) | 92 | observe | Y | E Graph query/patch | CUT | Diff the current indexed scene graph against a previously captured baseline graph snapshot. |
| 44 | `document.apply` | yes | live/ops/document_apply.py:1104 | 5 (-) | 1020 | edit_scene |  | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Apply a canonical network document (hocuspocus://schemas/network-document/v1 or /v2) or checkout using reconcile, merge, or validate-only... |
| 45 | `document.checkout` | yes | live/ops/document.py:123 | 2 (-) | 148 | observe | Y | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Create a working copy for a network or scene document. |
| 46 | `document.diff` | yes | live/ops/document_diff.py:638 | 2 (-) | 839 | observe | Y | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Diff a supplied canonical network document (hocuspocus://schemas/network-document/v1 or /v2) or checkout against its baseline. |
| 47 | `document.discard_checkout` | yes | live/ops/document.py:136 | 1 (checkout_id) | 98 | observe |  | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Delete a working copy that is no longer needed. |
| 48 | `document.query` | yes | live/ops/document_diff.py:674 | 9 (-) | 360 | observe | Y | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Query the current document-backed graph surface without materializing a full network document. |
| 49 | `document.sync_from_houdini` | yes | live/ops/document.py:146 | 1 (-) | 67 | observe | Y | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Force a document refresh from the live Houdini scene for a network root or for the whole scene manifest. |
| 50 | `document.validate` | yes | live/ops/document_validation.py:902 | 2 (-) | 839 | observe | Y | F Document+HocusScript | CUT from agent surface (separate server/CLI) | Validate a supplied canonical network document (discoverable at hocuspocus://schemas/network-document/v1 or /v2), scene document, or exis... |
| 51 | `document.apply_plan` | yes | live/ops/hocusscript_apply.py:490 | 6 (planId,planHash,expectedDocumentRevision,expectedLiveRevision,idempotencyKey) | 468 | edit_scene |  | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Validate immutable plan identity plus live session, policy, catalog, capability, revision, ownership, target, confirmation, lease, idempo... |
| 52 | `document.apply_quarantines` | yes | live/ops/hocusscript.py:1071 | 0 (-) | 67 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | List network scopes blocked after an apply whose rollback could not be verified. |
| 53 | `document.compile_source` | yes | live/ops/hocusscript_editor_compile.py:16 | 3 (source) | 270 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Parse, structurally validate, and canonically format unsaved HocusScript without mutating Houdini. |
| 54 | `document.complete_source` | yes | live/ops/hocusscript.py:148 | 4 (source,offset) | 353 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Return bounded, deterministic completions for an unsaved HocusScript buffer using the current live Houdini operator catalog. |
| 55 | `document.discard_plan` | yes | live/ops/hocusscript.py:1024 | 2 (planId,planHash) | 163 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Revoke an immutable HocusScript apply plan by exact plan ID and hash without mutating Houdini. |
| 56 | `document.export_source` | yes | live/ops/hocusscript.py:183 | 2 (root_path) | 177 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Export one supported flat direct-child live SOP, fixed-port material/VOP, LOP, or TOP network as canonical HocusScript plus durable prove... |
| 57 | `document.format_source` | yes | live/ops/hocusscript.py:121 | 3 (source) | 270 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Validate and canonically format unsaved HocusScript text without reading or writing project files. |
| 58 | `document.plan_bundle` | yes | live/ops/hocusscript.py:1020 | 2 (bundle) | 324 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Rerun the exact-version live validation of an authenticated flat Bundle 0.2, module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5, ... |
| 59 | `document.preview_bundle` | yes | live/ops/hocusscript.py:574 | 1 (bundle) | 241 | observe | Y | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Strictly decode an exact flat Bundle 0.2, frozen module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5, freshly revalidate its authe... |
| 60 | `document.recover_scope` | yes | live/ops/hocusscript.py:1082 | 1 (rootPath) | 123 | edit_scene |  | F2 HocusScript lane | CUT from agent surface (separate server/CLI) | Force-reimport and validate a quarantined network scope, then release its quarantine only when the canonical document is valid. |
| 61 | `source.file.apply_patch` | yes | live/ops/source_workspace.py:87 | 7 (projectId,path,mode) | 520 | observe |  | G Source workspace | CUT from agent surface (separate server/CLI) | Exclusively create or exact-digest patch one authored .hocus file or validated project manifest. |
| 62 | `source.file.read` | yes | live/ops/source_workspace.py:74 | 5 (projectId,paths) | 530 | observe | Y | G Source workspace | CUT from agent surface (separate server/CLI) | Read one or a bounded batch of exact authored files through the approved project workspace. |
| 63 | `source.file.search` | yes | live/ops/source_workspace.py:61 | 9 (projectId) | 675 | observe | Y | G Source workspace | CUT from agent surface (separate server/CLI) | Run a bounded filename/glob or UTF-8 text search over authorized authored project files. |
| 64 | `source.file.write_export` | yes | live/ops/source_workspace.py:100 | 5 (projectId,destination,handoff) | 445 | observe |  | G Source workspace | CUT from agent surface (separate server/CLI) | Validate, recompile, and publish a bounded document.export_source handoff through the authorized source workspace. |
| 65 | `source.project.build` | yes | live/ops/source_workspace.py:113 | 9 (projectId,action) | 826 | observe |  | G Source workspace | CUT from agent surface (separate server/CLI) | Run exactly one native format, check, compile, or explicit generated-lock update action without introducing a second resolver. |
| 66 | `source.project.describe` | yes | live/ops/source_workspace.py:48 | 1 (-) | 132 | observe | Y | G Source workspace | CUT from agent surface (separate server/CLI) | List only projects currently authorized to this connection, or describe one opaque project id. |
| 67 | `source.project.navigate` | yes | live/ops/source_workspace.py:126 | 7 (projectId,operation,path,offset) | 581 | observe | Y | G Source workspace | CUT from agent surface (separate server/CLI) | Run native completion or go-to-definition over a saved file or supplied dirty source buffer. |
| 68 | `production.asset.qualify` | yes | live/ops/production.py:128 | 12 (artistOverrideEvidence,baselineProvenance,budget,candidateProvenance,contract,metrics,numericBaseline,numericCandidate,numericTolerances,observation,visualComparisons,visualVersionReviewEvidence) | 15824 | observe | Y | H Production | CUT | Bind an asset contract, exact observation, repeated-build provenance, budgets, numeric/visual regressions, and artist override plus expli... |
| 69 | `hda.create_from_subnet` | yes | live/ops/hda_ops.py:717 | 6 (node_path,asset_name,hda_file_path) | 298 | edit_scene,write_files |  | I HDA | KEEP->hda(create) | Turn a subnet-like node into a digital asset saved to a policy-approved HDA file path and return both the new instance and definition sum... |
| 70 | `hda.get_definition` | yes | live/ops/hda_ops.py:611 | 4 (-) | 204 | observe | Y | I HDA | MERGE->hda | Return metadata, sections, and parm-interface structure for a specific HDA definition resolved by node type name, library file, or HDA in... |
| 71 | `hda.get_instance` | yes | live/ops/hda_ops.py:625 | 1 (node_path) | 94 | observe | Y | I HDA | MERGE->hda | Return HDA instance metadata, current-definition status, spare-parm count, and the effective parm interface for a live node instance. |
| 72 | `hda.get_interface` | yes | live/ops/hda_ops.py:649 | 3 (-) | 146 | observe | Y | I HDA | MERGE->hda | Return the parm interface for either a live HDA instance or a resolved HDA definition. |
| 73 | `hda.install_library` | yes | live/ops/hda_ops.py:662 | 2 (library_file_path) | 169 | edit_scene,write_files |  | I HDA | MERGE->hda | Install an HDA library file into the current Houdini session from a policy-approved path. |
| 74 | `hda.list_definitions` | yes | live/ops/hda_ops.py:599 | 1 (-) | 75 | observe | Y | I HDA | MERGE->hda | List HDA definitions from a specific library file or from all currently loaded HDA libraries. |
| 75 | `hda.list_libraries` | yes | live/ops/hda_ops.py:575 | 0 (-) | 36 | observe | Y | I HDA | MERGE->hda | List installed HDA library files and the first set of definitions they contain. |
| 76 | `hda.promote_parm` | yes | live/ops/hda_ops.py:867 | 9 (instance_path,source_parm_path) | 506 | edit_scene,write_files |  | I HDA | MERGE->hda(interface) | Promote one static internal parm into a locked, current HDA definition without losing its value. |
| 77 | `hda.reload_library` | yes | live/ops/hda_ops.py:688 | 1 (library_file_path) | 110 | edit_scene |  | I HDA | MERGE->hda | Reload an installed HDA library file from disk. |
| 78 | `hda.set_definition_version` | yes | live/ops/hda_ops.py:1032 | 4 (version) | 202 | edit_scene,write_files |  | I HDA | MERGE->hda | Update the version on an embedded definition or an external HDA library inside approved write roots, returning its library identity. |
| 79 | `hda.set_instance_parms` | yes | live/ops/hda_ops.py:1006 | 2 (instance_path,assignments) | 401 | edit_scene |  | I HDA | CUT (parm_set covers) | Set only public interface parameters on an HDA instance, including a locked instance, without unlocking or editing its internal network. |
| 80 | `hda.uninstall_library` | yes | live/ops/hda_ops.py:675 | 1 (library_file_path) | 110 | edit_scene |  | I HDA | MERGE->hda | Uninstall an HDA library file from the current Houdini session. |
| 81 | `node_types.get_info` | yes | live/ops/node_types.py:523 | 4 (-) | 404 | observe | Y | J Node types | REDESIGN->node_type_info(+help) | Return focused metadata for one node type selected by its stable typeId or by type name and optional category. |
| 82 | `node_types.list` | yes | live/ops/node_types.py:486 | 8 (-) | 384 | observe | Y | J Node types | REDESIGN->node_type_search | List discoverable node types for supported categories such as SOP, OBJ, LOP, and TOP. |
| 83 | `node_types.list_compatible` | yes | live/ops/node_types.py:609 | 7 (-) | 572 | observe | Y | J Node types | CUT | Suggest node types using exactly one canonical task or a bounded natural-language intent. |
| 84 | `node_types.list_groups` | yes | live/ops/node_types.py:426 | 1 (-) | 66 | observe | Y | J Node types | CUT | List curated node-type discovery groups for the supported Houdini categories. |
| 85 | `geometry.get_summary` | yes | live/ops/viewport.py:100 | 1 (node_path) | 94 | observe | Y | K Geometry | REDESIGN->geo_info | Return geometry facts for a node with cooked geometry, including counts, bbox, groups, attributes, and discovered material paths. |
| 86 | `camera.get_active` | yes | live/ops/viewport.py:46 | 0 (-) | 36 | observe | Y | L Viewport | MERGE->viewport | Return the active viewport camera path, or indicate that the viewport is in perspective mode. |
| 87 | `snapshot.capture_viewport` | yes | live/ops/viewport.py:83 | 1 (-) | 62 | observe,write_files |  | L Viewport | CUT (duplicate) | Capture the current scene viewer viewport to an explicit path or a managed snapshot path. |
| 88 | `viewport.capture` | yes | live/ops/viewport.py:75 | 1 (-) | 62 | observe,write_files |  | L Viewport | REDESIGN->viewport_capture (return image) | Capture the current scene viewer viewport to an image file. |
| 89 | `viewport.get_state` | yes | live/ops/viewport.py:26 | 0 (-) | 36 | observe | Y | L Viewport | MERGE->viewport | Return scene viewer, viewport, and current camera information for the active viewport. |
| 90 | `cook.node` | yes | live/ops/tasks_ops.py:38 | 3 (node_path) | 235 | edit_scene |  | M Tasks | REDESIGN->cook (sync+errors) | Start a non-blocking cook task for a Houdini node and return a task handle immediately. |
| 91 | `task.cancel` | yes | live/ops/session.py:124 | 1 (task_id) | 90 | observe |  | M Tasks | MERGE->task | Request cancellation for a queued or running long-running task by task id. |
| 92 | `task.list` | yes | live/ops/session.py:115 | 1 (-) | 79 | observe | Y | M Tasks | MERGE->task | List recent non-blocking task records such as cooks and renders. |
| 93 | `export.alembic` | yes | live/ops/export.py:106 | 4 (source_node_path) | 281 | edit_scene,write_files |  | N Render | CUT (render ROP) | Start a non-blocking Alembic export task for a SOP node or a geometry object with a display SOP. |
| 94 | `export.usd` | yes | live/ops/export.py:213 | 3 (node_path) | 215 | edit_scene,write_files |  | N Render | CUT (render ROP) | Start a non-blocking USD export task for a LOP node. |
| 95 | `render.inspect_graph` | yes | live/ops/render_ops.py:134 | 2 (node_path) | 143 | observe | Y | N Render | MERGE->render(inspect) | Inspect a ROP node and its upstream ROP input chain, including output paths, frame-range parms, and node-reference parms. |
| 96 | `render.inspect_outputs` | yes | live/ops/render_ops.py:145 | 1 (node_path) | 94 | observe | Y | N Render | MERGE->render(inspect) | Inspect a render node's file-output parms and AOV or image-plane parms where the node type exposes them. |
| 97 | `render.preflight` | yes | live/ops/render_ops.py:206 | 2 (node_path) | 143 | observe | Y | N Render | MERGE->problems | Run a render preflight over a ROP chain, checking output-path policy, missing file dependencies, and broken node-reference parms before r... |
| 98 | `render.rop` | yes | live/ops/tasks_ops.py:164 | 4 (node_path) | 292 | edit_scene,write_files |  | N Render | KEEP->render | Start a non-blocking render task for a ROP node and return a task handle immediately. |
| 99 | `pdg.cancel` | yes | live/ops/pdg_ops.py:172 | 1 (graph_path) | 96 | edit_scene |  | O PDG/TOPs | MERGE->pdg | Request cancellation for an active PDG graph cook on a TOP network. |
| 100 | `pdg.cook` | yes | live/ops/pdg_ops.py:183 | 4 (graph_path) | 259 | edit_scene |  | O PDG/TOPs | MERGE->pdg | Start a non-blocking PDG graph cook task for a TOP network. |
| 101 | `pdg.get_graph_state` | yes | live/ops/pdg_prod_ops.py:118 | 2 (graph_path) | 142 | observe | Y | O PDG/TOPs | MERGE->pdg | Return graph summary plus expanded work-item state for a TOP network. |
| 102 | `pdg.get_results` | yes | live/ops/pdg_ops.py:161 | 3 (graph_path) | 175 | observe | Y | O PDG/TOPs | MERGE->pdg | Return result-data records for cooked PDG work items on a TOP graph or specific TOP node. |
| 103 | `pdg.get_workitem_logs` | yes | live/ops/pdg_prod_ops.py:71 | 4 (graph_path) | 241 | observe | Y | O PDG/TOPs | MERGE->pdg | Return stored log messages for PDG work items on a TOP graph or a specific TOP node. |
| 104 | `pdg.get_workitems` | yes | live/ops/pdg_ops.py:137 | 3 (graph_path) | 175 | observe | Y | O PDG/TOPs | MERGE->pdg | Return work-item state, attributes, and result metadata for a TOP graph or a specific TOP node inside that graph. |
| 105 | `pdg.inspect_schedulers` | yes | live/ops/pdg_prod_ops.py:41 | 1 (graph_path) | 96 | observe | Y | O PDG/TOPs | MERGE->pdg | Inspect scheduler nodes under a TOP network, including working directory and scheduler type information. |
| 106 | `pdg.list_graphs` | yes | live/ops/pdg_ops.py:103 | 0 (-) | 36 | observe | Y | O PDG/TOPs | MERGE->pdg | List TOP networks and summarize their cook state, graph size, and work-item state counts. |
| 107 | `pdg.retry_workitems` | yes | live/ops/pdg_prod_ops.py:102 | 3 (graph_path) | 179 | edit_scene |  | O PDG/TOPs | MERGE->pdg | Dirty a PDG graph or specific TOP node so work can be retried, and optionally restart graph execution. |
| 108 | `lop.create_node` | yes | live/ops/usd_ops.py:57 | 5 (node_type_name) | 282 | edit_scene |  | P USD/LOPs | CUT (node_create) | Create a Solaris LOP node under `/stage` or another LOP network and optionally wire an input node into it. |
| 109 | `usd.add_reference` | yes | live/ops/usd_ops.py:134 | 6 (prim_path,file_path) | 336 | edit_scene |  | P USD/LOPs | CUT | Create a Reference LOP and author a file reference at a prim path. |
| 110 | `usd.assign_material` | yes | live/ops/usd_ops.py:81 | 5 (prim_pattern,material_path) | 312 | edit_scene |  | P USD/LOPs | CUT | Create an Assign Material LOP and author a material binding for a prim pattern. |
| 111 | `usd.create_layer_break` | yes | live/ops/usd_ops.py:164 | 4 (-) | 221 | edit_scene |  | P USD/LOPs | CUT | Create a Layer Break LOP and, when `save_path` is provided, a Configure Layer LOP with an authored save path. |
| 112 | `usd.inspect_material_bindings` | yes | live/ops/usd_stage_ops.py:231 | 2 (node_path) | 148 | observe | Y | P USD/LOPs | MERGE->usd_stage | Inspect bound USD materials under a root prim path on a composed stage. |
| 113 | `usd.inspect_prim` | yes | live/ops/usd_stage_ops.py:189 | 2 (node_path,prim_path) | 140 | observe | Y | P USD/LOPs | REDESIGN->usd_stage(prim) | Inspect a single USD prim at a LOP node, including references, variant sets, child prims, and bound material information. |
| 114 | `usd.set_variant` | yes | live/ops/usd_ops.py:107 | 6 (prim_pattern,variant_set,variant_name) | 356 | edit_scene |  | P USD/LOPs | CUT | Create a Set Variant LOP for a prim pattern, variant set, and variant name. |
| 115 | `usd.stage_summary` | yes | live/ops/usd_stage_ops.py:124 | 1 (node_path) | 94 | observe | Y | P USD/LOPs | REDESIGN->usd_stage | Inspect the composed USD stage at a LOP node, including root/session layers, used layers, default prim, and a prim-path sample. |
| 116 | `usd.validate_stage` | yes | live/ops/usd_stage_ops.py:248 | 1 (node_path) | 94 | observe | Y | P USD/LOPs | MERGE->problems | Validate composed USD stage references and Solaris save-path policy issues for a LOP node. |
| 117 | `material.assign` | yes | live/ops/material.py:119 | 2 (target_node_path,material_path) | 162 | edit_scene |  | Q Materials | CUT (parm_set / LOP) | Assign a material to a target node by resolving the nearest owner with a `shop_materialpath` parameter. |
| 118 | `material.create` | yes | live/ops/material.py:57 | 9 (-) | 489 | edit_scene |  | Q Materials | CUT/REDESIGN (MaterialX recipe) | Create a material node, defaulting to a Principled Shader under `/mat`, and optionally apply common lookdev properties such as base color... |
| 119 | `material.update` | yes | live/ops/material.py:71 | 7 (material_path) | 428 | edit_scene |  | Q Materials | CUT | Update common lookdev properties on an existing material node and return the updated material summary. |
| 120 | `cache.get_topology` | yes | live/ops/dependency_ops.py:270 | 1 (-) | 67 | observe | Y | R Deps/package | CUT | Summarize common cache-producing or cache-consuming nodes such as File Cache, file, and geometry-output nodes. |
| 121 | `dependency.repath` | yes | live/ops/dependency_ops.py:227 | 5 (old_path,new_path) | 302 | edit_scene |  | R Deps/package | MERGE->dependencies | Rewrite file-reference parm values by exact match or prefix match. |
| 122 | `dependency.scan_scene` | yes | live/ops/dependency_ops.py:183 | 1 (-) | 67 | observe | Y | R Deps/package | KEEP->dependencies | Scan scene file references and classify them as input, output, USD, or cache dependencies. |
| 123 | `package.create_scene_package` | yes | live/ops/package_ops.py:220 | 9 (-) | 474 | write_files |  | R Deps/package | CUT (pipeline) | Create a scene package as a zip archive or directory tree at a validated destination. |
| 124 | `package.preview_scene` | yes | live/ops/package_ops.py:162 | 5 (-) | 272 | observe | Y | R Deps/package | CUT (pipeline) | Preview which files would be collected into a scene package or archive. |
| 125 | `graph.check_errors` | yes | live/ops/validation.py:87 | 1 (-) | 67 | observe | Y | S Validation/events | MERGE->problems | Check the indexed scene graph for broken parameter references and missing material assignments, optionally within a root path. |
| 126 | `parm.find_broken_refs` | yes | live/ops/validation.py:38 | 1 (-) | 67 | observe | Y | S Validation/events | MERGE->problems | Return broken absolute parameter references discovered in parameter expressions and channel references. |
| 127 | `scene.events_recent` | yes | live/ops/validation.py:132 | 2 (-) | 119 | observe | Y | S Validation/events | REDESIGN->events (cursor) | Return recent monitor events from the live Houdini session, optionally filtered by sequence number. |
| 128 | `scene.validate` | yes | live/ops/validation.py:114 | 0 (-) | 36 | observe | Y | S Validation/events | MERGE->problems | Run a high-signal validation pass over broken parameter references, USD save-path policy issues, and output-path policy issues. |
| 129 | `lookdev.create_three_point_light_rig` | yes | live/ops/render_ops.py:353 | 6 (-) | 259 | edit_scene |  | T Recipes | CUT (recipe) | Create a scale-aware three-point light rig under `/obj`. |
| 130 | `scene.create_turntable_camera` | yes | live/ops/scene.py:304 | 5 (-) | 351 | edit_scene |  | T Recipes | CUT (recipe) | Create a target null, rig null, and camera for a simple orbit shot under `/obj`. |

## Appendix B — Reproduction

Registry dump: `LiveOperations.__new__(LiveOperations).register(ToolRegistry(), ResourceRegistry())`, then serialize `ToolRegistry.tools`. Payload measurements: hython 22.0.466 with `HOUDINI_USER_PREF_DIR` set to a scratch dir. Build `/obj/geo1` as `box -> polyextrude::2.0 -> mountain::2.0 -> attribwrangle -> null(OUT)`, construct `LiveOperations(LiveCommandDispatcher, SceneEventMonitor, LiveTaskManager, ServerSettings(), logger)`, and call handlers directly with `RequestContext(permissions=("observe","edit_scene","write_files"))`. No server was started, no port was bound, and nothing was installed. The scripts were kept in the session scratch directory and are not committed.
