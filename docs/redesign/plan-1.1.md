# HocusPocus 1.1 plan

Source: `docs/redesign/review/10-code-review.md` (open items) and `11-ergonomics-review.md`
(§6 "1.1" scope). 1.1 is a minor release: contract changes are allowed where the reviews
show a clear win, each recorded in `docs/BIBLE.md`.

## Scope

**Results and defaults (contract)**
- `node_create`, `node_copy`, `network_build`: `return: "summary"` becomes the default; `full`
  elides strings over 200 chars; values set by a node's creation script are not reported as edits.
- `node_type_search`: `current_only` defaults to true with `other_versions` on the current row;
  descriptions capped at 120 chars.
- `render`: above 5 outputs only `outputs_summary` inline; the full list via `job result`.
- `houdini_python`: an uncaught exception is an `isError` result (`code: python_exception`) carrying
  stdout, stderr and traceback.
- `locked` means the SOP lock flag everywhere; `hda_locked` means inside or at a locked asset.
- Text/structured duplication: decided after measuring what Claude Code shows the model (see §Measurement).

**Cook and jobs**
- `cook {profile: true}`: force-cook `inputAncestors()` in dependency order as a job; return
  `chain: [{path, cook_time_ms}]` (top 10) and `total_ms`.
- `cook {frame_range: [start, end, step], summary: "bbox"}`: one main-thread step per frame,
  `progress` and `message: "frame 37/96"`, per-frame counts and bbox.
- Bridge emits MCP progress notifications for jobs when the client supplies a `progressToken`.

**Conveniences**
- `node_edit.spare_parms {add: [...], remove: [...]}`.
- `node_create` pairs `block_end` with its feeding `block_begin` (`blockpath`) automatically.
- `network_describe format: "outline"` and resource `houdini://outline`.
- `hocuspocus launch [--headless] [--hip FILE]` CLI: start a Houdini that outlives any MCP client.

**Robustness (code review 10)**
- Registry identity check against pid/port reuse; executor timeout race; `houdini_python` deadline
  (`sys.settrace`); undo rollback reported honestly; HTTP handler timeout and `Host` check; host
  `profile` enforcement; `job_threshold_s` honoured by `render`/`pdg`; `_common.py` for duplicated
  helpers; consistent batch error shape; dead code removed; e2e pref-dir leak; flaky executor test.

## Out of scope
Linux/macOS qualification; any new process-ownership mechanism for launched Houdini (the CLI
`launch` command covers the need); APEX; HocusScript.

## Exit criteria
All tiers green; `tools/list` ≤ 44 KB; review-07 scenario and the two workload scripts still pass;
CHANGELOG 1.1.0; BIBLE updated; tag `v1.1.0` + GitHub release.
