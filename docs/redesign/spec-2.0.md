# HocusPocus 2.0 specification

**Status:** planning spec, 2026-10-13. Authoritative for the 2.0 work; `docs/BIBLE.md` stays
the 1.x authority until 2.0 ships, when it is rewritten from this document.

## 0. Why a 2.0

Every evaluation since 1.0 (reviews 07–24) measured the same two numbers: calls per task and
bytes per call. 1.x drove both down by trimming descriptions, moving detail into `notes`,
adding filters and summary modes, and chasing a 40 KB `tools/list` cap. Those are the limits
of the 1.x contract: one tool per noun, every read a tool call with a schema, every mutation
its own round trip and undo group, jobs bound to the process that started them, and four
capture backends behind one argument. 2.0 changes the contract where the evidence says it
matters and leaves the rest alone.

Four contract changes, in priority order:

1. **One transaction tool for mutations** (`edit`) with `$ref` ids, dry runs, one undo group
   and a summary echo. Per-noun tools become thin conveniences or go away.
2. **Reads become resources with caching**, plus one `inspect` tool and one `search` tool for
   clients that do not read resources. Discovery bytes stop fighting the budget.
3. **A bridge ledger for instances and jobs**: durable across bridge restarts, instances have
   names and roles, jobs are addressed by id alone, progress is pushed.
4. **One `look` tool** that chooses the capture or render backend from a `quality` level.

And four refactors that pay for themselves regardless: the catalogue generated from per-tool
spec files; the evaluation workloads as a test tier; a GUI/headless parity matrix tested in
CI; the platform story finished (clean-machine install, Linux/macOS portability guards).

## 1. Principles carried over from 1.x

Houdini vocabulary is the API; small surface, deep tools; compact by default; truth over
ceremony; errors are instructions; safe by default; the main thread owns `hou`; the host is
stdlib-only; the agent may need a Houdini that is not running; localhost security; three
commands to first success; tests run against real Houdini. 2.0 adds:

13. **Measure what agents pay.** Every tool and resource has a recorded byte budget per
    workload, enforced by the workloads tier. A change that raises bytes per task must say why.
14. **One way to change the scene.** All mutations go through the transaction engine, whether
    the agent called `edit` or a convenience tool. There is one undo policy, one rollback, one
    echo shape.

## 2. The 2.0 tool surface

Profiles: `minimal` (10), `core` (18), `full` (21). Names stay `snake_case`. The 1.x names
that survive keep their semantics unless listed in §8.

### 2.1 Session (bridge-local)

| Tool | Change from 1.4 |
|---|---|
| `houdini_status` | Instances carry `name`, `role` (`editor` \| `worker`), `busy`, `jobs_running`, `selected`. Ledger-backed: an instance remembered by the ledger but currently dead is listed under `recent` with its last hip. |
| `houdini_connect` | Adds `role` on launch and attach; `quit` unchanged. Pin by `name` or `role` (`role: "worker"` picks the least busy worker). |

### 2.2 Hip (unchanged)

`hip_new`, `hip_open`, `hip_save`, `hip_merge` as in 1.4.

### 2.3 Reads

| Tool | Spec |
|---|---|
| `inspect` | `{target, what, ...}`. `what` ∈ `node` (1.4 `node_info`), `parms` (`parm_get` on a node or paths), `network` (`network_describe data`), `outline`, `geo` (`geo_info` + `geo_read` via `rows`), `image` (COP summary), `stage` (`usd_stage`), `problems`, `type` (`node_type_info`), `events` (`since`), `jobs`. One schema with per-`what` options in `notes`; the result carries an `etag` (not `what` or `target`, which the caller knows). Read-only, idempotent. |
| `search` | `{query, kind: types \| nodes, category?, root?, limit, cursor}`. Types: 1.4 ranking, synonyms, `current_only`. Nodes: `node_find` filters. |

Both remain for clients that never read resources. Their results are byte-identical to the
matching resource.

### 2.4 Mutations

| Tool | Spec |
|---|---|
| `edit` | `{ops: [...], dry_run, return: summary \| full, partial}`. Ops (each `{op, ...}` with an optional `id` usable as `$id` in later ops): `create` (type, parent, name, parms, inputs, flags), `delete`, `connect`, `set` (parm items incl. expression, keys, ramp, press), `node` (rename, flags, color, comment, position, lock, spare_parms), `copy`, `layout`, `build` (`hou.data` block), `select`. Executes on the main thread as one undo group labelled `HocusPocus: edit <n> ops`. `dry_run` validates every op (types, parms, inputs, names) and returns the plan with resolved paths and no changes. Failure rolls back and reports `items[i] (path)` with `rolled_back` truthfully. The echo is the 1.4 summary shape per touched node (`path, type, errors, warnings, cook_state, cook_ms`), with `full` elision rules. |
| `node_create` | Convenience: `edit` with `create` ops. Same arguments as 1.4. |
| `parm_set` | Convenience: `edit` with `set` ops. Same arguments as 1.4. |

Removed from the surface (available as `edit` ops): `node_delete`, `node_edit`, `node_copy`,
`node_connect`, `node_layout`, `network_build`, `selection` (set). A 1.x compatibility profile
keeps them for one minor release (§8).

### 2.5 Execution

| Tool | Spec |
|---|---|
| `cook` | As 1.4 (`profile`, `frame_range`, `wait_s`); accepts `on: pid \| name \| role`. |
| `render` | As 1.4 (writer SOPs, single-file ROPs verified, `camera`); accepts `on`. |
| `look` | `{target?, quality: draft \| lit \| final, camera?, frame?, resolution?, fit?}`. `target` is an OBJ, SOP, LOP or COP path (or omitted for the display). The host chooses: `draft` = Flipbook/OpenGL ROP (warm child headless, viewer in GUI only when asked with `source: viewer`), `lit` = Flipbook with lights or Karma low samples, `final` = Karma at the ROP's settings. Returns the image, `backend_used`, `scene`, `context`, notes. Replaces `viewport_capture`; the OpenGL ROP backend is removed once Houdini 22.5 is the floor. |
| `houdini_python` | Unchanged. |
| `job` | `{action: status \| result \| cancel \| list, job_id?, all?}`. Ids are opaque ledger ids; the bridge knows the instance. Progress arrives as MCP progress notifications when a token is supplied, otherwise via `inspect what: jobs`. |

### 2.6 State and contexts

| Tool | Spec |
|---|---|
| `undo` | As 1.4. |
| `time` | As 1.4. |
| `hda` *(full)* | As 1.4. |
| `pdg` *(full)* | As 1.4; `workitems` also as `inspect what: pdg`. |
| `events` *(full)* | As 1.4; also `inspect what: events` and the `houdini://events` resource. |

### 2.7 Resources

Templates (RFC 6570), all read-only, each with an `etag` and `Cache-Control`-style hints in
`_meta`; the bridge serves `304`-equivalent empty results when a client supplies a matching
`If-None-Match` via `_meta`:

- `houdini://status`, `houdini://instances`, `houdini://jobs`
- `houdini://node/{path}{?include,parms,include_defaults}`
- `houdini://outline{?root,depth}`
- `houdini://network/{path}{?depth,format}`
- `houdini://geo/{path}{?frame,class,attribs,start,count,stats}`
- `houdini://image/{path}`
- `houdini://stage/{lop}{?prim,include,time,summary}`
- `houdini://type/{category}/{name}{?parms,folder,detail}`
- `houdini://types{?q,category,limit,cursor}`
- `houdini://problems{?root}`
- `houdini://events{?since,limit}`
- `hocuspocus://guide`, `hocuspocus://tools`

ETag = `<pid>:<scene_generation>:<16-hex BLAKE2b of the canonical body>` (sorted keys,
compact separators; an `inspect` body without its own `etag`), for every resource and
`inspect`. The host builds the body anyway, so the etag moves exactly when the answer does
(M4: hashing mtimes and cook counts gave byte-identical bodies a new etag after any recook,
and the soak never hit `not_modified`). Resource subscriptions (`resources/subscribe`) are supported for
`status`, `jobs`, `events`, and `node/{path}`; the host publishes change notifications from
the event ring buffer.

### 2.8 Prompts

`inspect_scene`, `build_sop_chain`, `debug_red_node`, `turntable_preview`, `cache_sim`,
`two_houdinis`, `lookdev_karma`, rewritten for the 2.0 tools.

## 3. The bridge ledger

A SQLite file `<state_dir>/ledger.sqlite` owned by the bridge (one writer; bridges on the same
machine coordinate through the registry files as today, the ledger is per bridge).

Tables: `instances(pid, name, role, label, ui, hip, started, last_seen, launched_by)`,
`jobs(id, instance_pid, tool, state, progress, message, started, finished, result_path)`,
`launches(pid, argv, work_dir, time)`. Job results over 16 KB are spilled to
`<state_dir>/jobs/<id>.json` and served by `job result` / `inspect what: jobs`. The ledger
survives bridge restarts; on start the bridge reconciles it with the registry and marks dead
instances. `instance_lost` and `ambiguous_instance` keep their 1.3 semantics.

Roles: `editor` (default for GUI), `worker` (default for headless). `cook`, `render`, `look`
and `job` accept `on`; `edit` and `hip_*` always target the pinned/selected instance.

## 4. Host changes (hp/v2)

- `GET /hp/v2/resource?uri=...` serves the resource templates with ETags; `POST /hp/v2/call`
  unchanged in shape; `/hp/v2/jobs` adds server-sent progress for the bridge's poller.
- The transaction engine (`host/tx.py`) absorbs the batch engines of `nodes.py`, `parms.py`
  and `network.py`; every mutating tool is an `edit` plan.
- `look` backends live in `host/look/` (viewer, flipbook, opengl, karma), each a small class
  with `can_run(scene, headless)`, `render(spec)`, and the warm-child policy.
- The host keeps a `hp/v1` compatibility route for one minor release so a 1.4 bridge can talk
  to a 2.0 host and vice versa (feature-gated).

## 5. Refactors

1. **Catalogue from spec files.** `src/hocuspocus/tools/spec/<tool>.py` (one module per tool:
   name, description, schema builders, notes, examples, annotations, profile) and
   `catalog.py` becomes the loader. `docs/tools.md`, `hocuspocus://tools`, the guide reference
   and the budget report are generated from the same objects. The budget test keeps the 1.4
   caps and adds per-profile, per-mode history in `docs/redesign/budget.md`.
2. **Workloads tier.** `tests/workloads/` holds scripted versions of the city build (review 12),
   the scorecard twelve (review 21), the soak (review 22, 200 calls), the FX cache (review 20)
   and the USD round trip (review 24). Each records calls, text bytes, time to first image,
   and fails on a 15 % regression against `tests/workloads/budgets.json`. Runs on the Houdini
   runner nightly and before every tag.
3. **Parity matrix.** `docs/parity.md` lists every tool × (GUI, headless) with the behaviour
   difference, if any; a scripted `houdinifx` session in the slow tier executes the GUI column.
4. **Platform.** `install-houdini` and `launch` verified on a clean Windows VM image (scripted
   in CI with the self-hosted runner), Linux/macOS path handling guarded by unit tests with
   fakes; `uv publish` wired into the release workflow with a `PYPI_TOKEN` secret (enabled by
   the user).

## 6. Non-goals

HocusScript; APEX; Streamable-HTTP direct to Houdini; multi-user; remote hosts beyond the
loopback bridge (the ledger's `role` prepares for it but 2.0 does not ship it).

## 7. Milestones

| # | Milestone | Contents | Exit |
|---|---|---|---|
| M0 | Foundation | Spec files + generated catalogue; workloads tier with 1.4 budgets recorded; parity matrix doc | All tiers green; workloads tier runs on 1.4 and records budgets |
| M1 | Transaction and reads | `host/tx.py` and `edit`; `inspect`, `search`; 1.4 tools reimplemented on top; profile `v2` exposes the new names alongside the old | Scorecard twelve pass through `edit`/`inspect` only; bytes and calls ≤ 1.4 budgets |
| M2 | Resources, look, ledger | Resource templates with ETags and subscriptions; `look` with backends; bridge ledger, roles, `on`, pushed progress | Workloads pass with resources enabled; two-instance review tasks via roles |
| M3 | Cut-over | Default profiles switch to 2.0 names; `compat_1x` profile; docs, guide, prompts, BIBLE 2.0 | A 1.4 client script runs unchanged under `compat_1x` |
| M4 | Evaluate and ship | Fresh-agent scorecard and all workloads on 2.0; fix pass; tag `v2.0.0` | Scorecard ≥ 1.4's; calls and bytes per workload below 1.4 by the margins the reviews predicted |

## 8. Migration (1.4 → 2.0)

- `viewport_capture` → `look` (`source` → `quality`/`source: viewer`).
- `node_info`/`network_describe`/`geo_info`/`geo_read`/`usd_stage`/`node_type_info`/`problems`
  → `inspect what: ...`; `node_find`/`node_type_search` → `search kind: ...`.
- `node_delete`/`node_edit`/`node_copy`/`node_connect`/`node_layout`/`network_build`/`selection`
  → `edit` ops.
- Job ids become opaque; `events next_since` unchanged.
- `profile = compat_1x` serves the 1.4 catalogue mapped onto the 2.0 engines for one minor
  release (2.0.x); 2.1 removes it.
