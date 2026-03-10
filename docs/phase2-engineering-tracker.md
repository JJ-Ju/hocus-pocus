# HocusPocus Phase 2 Engineering Tracker

Status: active

Source roadmap: `docs/phase2roadmap.md`

Branch: `codex/phase2`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P2-M1 Reliability and idempotence
2. P2-M2 Transactional graph editing
3. P2-M3 Tool metadata and output hints
4. P2-M4 Materials and assignments
5. P2-M5 Export workflows
6. P2-M6 Task behavior improvements

## P2-M1. Reliability and Idempotence

Status: complete

Goal:

- remove avoidable friction from repeated automation runs

Tasks:

- [x] Replace managed snapshot filenames with wall-clock or UUID-backed unique paths.
- [x] Ensure managed snapshot paths do not overwrite previous captures from the same scene/frame.
- [x] Add `ignore_missing` support to `node.delete`.
- [x] Keep `node.delete` strict by default and quiet only when `ignore_missing = true`.
- [x] Improve delete result payloads so skipped and deleted paths are distinct.

Done when:

- repeated snapshot calls create distinct files
- delete-if-present cleanup flows can be idempotent
- callers can tell which requested paths were deleted vs skipped

Manual smoke:

- call `snapshot.capture_viewport` twice with no path and verify two different files
- call `node.delete` on a missing path with and without `ignore_missing`

## P2-M2. Transactional Graph Editing

Status: complete

Goal:

- let grouped graph edits be atomic when the caller needs that guarantee

Tasks:

- [x] Add `transactional` support to `graph.batch_edit`.
- [x] Roll back all edits in the batch when a transactional batch fails.
- [x] Return the failed step index, type, and error payload in the result.
- [x] Keep current non-transactional behavior available for best-effort batches.
- [x] Document rollback semantics in tool metadata.

Done when:

- transactional batches leave no partial graph edits behind after failure
- non-transactional batches retain the current best-effort behavior
- failure reporting identifies the precise failed step

Manual smoke:

- run a transactional batch with one invalid late step and verify no preceding edits remain
- run the same batch non-transactionally and verify earlier edits remain

## P2-M3. Tool Metadata and Output Hints

Status: not started

Goal:

- make the MCP surface more self-describing for agent clients

Tasks:

- [ ] Add output-shape hints for major tools.
- [ ] Add example payloads for key higher-level and task tools.
- [ ] Add explicit blocking vs non-blocking annotations where relevant.
- [ ] Improve cleanup/idempotence notes where behavior is intentionally best-effort.
- [ ] Ensure resource templates describe payload conventions cleanly.

Done when:

- tool metadata tells an agent what kind of result to expect
- key tools include concrete examples
- non-blocking tools advertise that clearly

Manual smoke:

- inspect `tools/list` and verify new metadata fields appear as expected

## P2-M4. Materials and Assignments

Status: not started

Goal:

- make material authoring a first-class workflow instead of only a geometry read concern

Tasks:

- [ ] Add material creation/update tools for common Houdini material workflows.
- [ ] Add material assignment tools for relevant node contexts.
- [ ] Return material-aware summaries from creation and assignment tools.
- [ ] Extend geometry summaries where useful for authored material state.

Done when:

- an agent can create a material and assign it without manual node-by-node Houdini setup
- resulting geometry/material state is inspectable through normal reads

Manual smoke:

- create a material
- assign it to simple geometry
- verify the material path appears in geometry summary output

## P2-M5. Export Workflows

Status: not started

Goal:

- add practical scene export targets beyond cook and render

Tasks:

- [ ] Implement `export.alembic`.
- [ ] Implement `export.usd`.
- [ ] Validate export output paths against approved roots and write policy.
- [ ] Return durable task or result metadata suitable for follow-up automation.

Done when:

- an agent can export at least Alembic and USD through the server
- outputs obey the same file policy rules as other write tools

Manual smoke:

- export a simple SOP network to Alembic
- export a simple scene or network to USD

## P2-M6. Task Behavior Improvements

Status: not started

Goal:

- improve interruption and recovery characteristics for long-running work

Tasks:

- [ ] Investigate and implement deeper render interruption where Houdini APIs allow it.
- [ ] Distinguish partial-output outcomes more clearly in task results.
- [ ] Add task cleanup/recovery notes to logs or result payloads.
- [ ] Tighten cancellation semantics documentation for long single-frame work.

Done when:

- task results communicate partial outputs and cancellation outcome clearly
- interruption behavior is as strong as the Houdini APIs permit

Manual smoke:

- cancel a long render and inspect task result/log/output reporting

## 2. Immediate Next Actions

Recommended next implementation order:

1. P2-M1 Reliability and idempotence
2. P2-M2 Transactional graph editing
3. P2-M3 Tool metadata and output hints

These give the highest agent-ergonomics return with the least product churn.

## 3. Session Log

### 2026-03-09

- Created the phase-two roadmap from a codebase review after the M16/M17 slice.
- Created the phase-two engineering tracker with concrete milestones for reliability, transactions, metadata, materials, export, and task behavior.
- Implemented the first code pass for P2-M1 and P2-M2:
  - managed snapshot paths now use wall-clock time plus a random suffix
  - `node.delete` supports `ignore_missing` and distinguishes deleted vs skipped paths
  - `graph.batch_edit` now accepts `transactional = true` and reports rollback metadata on failure
- Verified the phase-two slice compiles, but live Houdini validation is still pending.
- Live-validated P2-M1 against Houdini 21.0:
  - managed snapshots now produce distinct files for repeated captures
  - `node.delete` remains strict by default and becomes idempotent with `ignore_missing = true`
- Live-validated P2-M2 against Houdini 21.0:
  - non-transactional batches leave earlier edits behind after a late failure
  - transactional batches roll back created nodes on failure and report `rolledBack = true`
