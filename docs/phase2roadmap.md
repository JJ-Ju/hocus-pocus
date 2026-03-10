# HocusPocus Phase 2 Roadmap

Status: active roadmap

Branch: `codex/phase2`

Scope:

- improve agent reliability and ergonomics on top of the current live Houdini MCP server
- tighten behavior where current tools are technically correct but awkward in real use
- add the next set of production-meaningful authoring and export capabilities

This phase assumes the current `0.9.0` live Houdini server, task system, higher-level tools, and `live/ops/` refactor are the new baseline.

## 1. Goals

Primary goals:

- make destructive and cleanup workflows more idempotent
- make task and snapshot behavior more predictable in practice
- add stronger higher-level authoring workflows without losing low-level control
- add the next most useful export and material capabilities

Non-goals for this phase:

- HDK/native implementation work
- Python Panel UI work
- HAPI worker plane work
- broad automated test infrastructure

## 2. Priority Order

1. Reliability fixes for existing tools
2. Better batch/transaction semantics
3. Cleaner agent-facing metadata and examples
4. Material and assignment authoring
5. Export workflows
6. Deeper task behavior improvements

## 3. Phases

## Phase 2A. Reliability and Idempotence

Problem:

- managed snapshots can collide on filename
- cleanup flows like delete-if-present are noisy and non-idempotent
- some tool behavior is underspecified or surprising in repeated runs

Deliver:

- wall-clock or UUID-backed managed snapshot filenames
- `ignore_missing` support for cleanup-oriented node deletion
- clearer behavior notes where tools are intentionally best-effort

## Phase 2B. Transactional Graph Editing

Problem:

- `graph.batch_edit` is useful, but it is not atomic
- agents often want grouped edits that either all apply or all roll back

Deliver:

- `transactional` mode for grouped graph edits
- rollback behavior on mid-batch failure
- stronger reporting for which step failed

## Phase 2C. Metadata and Examples

Problem:

- descriptions are improved but still missing output-shape hints and examples
- clients still need to infer too much from names and schemas alone

Deliver:

- output-shape hints in tool metadata
- example payloads for key tools
- stronger blocking vs non-blocking annotations

## Phase 2D. Materials and Assignments

Problem:

- geometry summaries expose material paths, but authoring materials still requires manual Houdini knowledge

Deliver:

- create/update material tools
- assignment tools for SOP/object/ROP contexts as appropriate
- material-aware summary improvements

## Phase 2E. Export Workflows

Problem:

- the server can cook and render, but common export targets are still missing

Deliver:

- `export.alembic`
- `export.usd`
- other export helpers where the live Houdini context makes them practical

## Phase 2F. Task Behavior Improvements

Problem:

- cancellation is good, but long single-frame work is still only cooperatively cancellable between operations

Deliver:

- better cancellation semantics where Houdini APIs allow it
- clearer result and partial-output reporting
- stronger task metadata for recovery and cleanup

## 4. Recommended Sequence

1. Reliability fixes: snapshot naming and idempotent delete
2. Transactional batch-edit mode
3. Metadata/output-hint improvements
4. Material authoring
5. Export tools
6. Task interruption improvements

## 5. Success Criteria

This phase is successful when:

- repeated automation runs are quieter and safer
- grouped graph edits can be atomic when needed
- agents need fewer defensive checks and retries
- common lookdev/export workflows become first-class
