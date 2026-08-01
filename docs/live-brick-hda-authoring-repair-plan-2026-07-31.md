# Live Brick HDA Authoring Repair Plan

Status: historical completion record; installed Houdini 22.0.368 acceptance passed

Source evidence: [live brick HDA findings](live-brick-hda-authoring-findings-2026-07-31.md)

## Outcome

Make the successful brick-wall workflow safe and repeatable in Houdini 22. A
failed mutation must either restore the exact baseline or enter an explicit
quarantined state. Agents must be able to discover authority, schemas, node
types, HDA instance controls, and the terminal outcome of an interrupted call
before making another mutation.

## Workstreams

### A. Mutation integrity

- Use one verified transaction boundary for direct document and HocusScript
  application.
- Validate parameter values against live Houdini parameter templates before
  opening an undo group.
- Use Houdini 22 `performUndo` and `performRedo`, guarded by undo-stack labels.
- Verify rollback against the captured baseline; quarantine any scope whose
  restoration cannot be proven.
- Make node display/output flags authoritative. Treat `output_flag` edges as
  regenerated observations, never competing mutation instructions.

### B. HDA authoring and authority

- Preserve the source value by default when promoting a parameter.
- Install the intended definition default, set the instance value, create the
  reference, recook, and verify the source and promoted values before commit.
- Expose a discoverable operation for editing public parameters on locked HDA
  instances without unlocking or structurally editing their internals.
- Report granted, required, and missing capabilities during session discovery
  and non-mutating document checks.
- Add an explicit opt-in procedural-authoring policy profile for `run_code`.

### C. Durable delivery and revisions

- Assign every tool call a stable operation ID before transport.
- Retain bounded terminal results and errors with tool, host generation,
  delivery stage, and commit state.
- Provide an authenticated read-only operation lookup after reconnect.
- Coalesce callbacks produced by one MCP mutation into one structural revision.
- Keep cosmetic callbacks from invalidating structural plans.

### D. Discovery and ergonomics

- Register canonical network-document schema resources and link document tools
  to them.
- Return stable category-qualified node type IDs and ambiguity candidates.
- Support token/compact node searches such as `poly bevel` and curate essential
  parameters such as Copy to Points `pack`.
- Label the legacy in-memory compiler lane honestly and direct modern source
  authoring through `source.project.build` and the preview/plan/apply pipeline.

## Integration order

1. Land and exercise verified rollback plus typed parameter preflight.
2. Normalize output verification and Houdini 22 undo/redo.
3. Land value-preserving HDA promotion and capability projection.
4. Join operation identity to the durable stdio broker and scene revisions.
5. Complete discovery metadata and documentation.
6. Install the candidate and repeat the real brick-wall workflow in Houdini 22.

## Acceptance

- Invalid numeric, toggle, and menu bindings fail before scene mutation with
  binding-level diagnostics.
- Injected apply failure either restores an exact baseline or returns a typed
  quarantined partial-state error.
- A stale observational output edge cannot reject a correctly applied display
  flag change.
- Guarded undo and redo work through the Houdini 22 API.
- Parameter promotion preserves geometry and values across definition refresh.
- A lost response can be reconciled by operation ID without replaying mutation.
- Session and validation results expose capability readiness before apply.
- One MCP transaction produces one structural revision.
- The installed live brick-wall authoring flow completes without the eight
  reported failures.

Public test count remains at 43. New hostile cases extend existing scenarios;
the primary release evidence is the installed Houdini 22 workflow.

## Completion evidence

- One full 43-scenario run passed after integration.
- The final focused operation-journal workflow passed with physical slot
  allocation, bounded orphan reclamation, cross-process publication locking,
  and fail-closed Windows namespace flushing.
- Installed first-use discovery proved Geometry bootstrap, inline checkout,
  stable `Sop/copytopoints` identity, curated `pack`, and token-normalized
  PolyBevel search.
- Installed authoring acceptance proved preserved tuple defaults, locked-HDA
  interface editing, real menu-token canonicalization, non-static channel
  rejection before definition mutation, file-write authority, Houdini 22
  guarded undo/redo, and one structural revision for one MCP mutation.
- A generated installed stdio broker remained connected while one disposable
  Houdini host stopped, returned typed offline status, and then reconnected to
  a second host identity without exposing its bearer credential.
- Independent mutation-integrity, HDA/capability, and durable-delivery reviews
  reported no remaining P0 or P1 findings.

The resulting user-facing behavior is documented in the
[agent workflows](agent-workflows.md#3-build-node-networks),
[durable transport contract](durable-mcp-transport.md), and
[user manual](user-manual.md). This file records the repair decision and its
acceptance evidence; it is not an additional runtime contract or active task
list.
