# Document Graph Overhaul Roadmap

Status: active

Source spec:

- `docs/document-graph-overhaul-spec.md`

Objective:

- move HocusPocus from imperative node tooling to document-centric network authoring without losing live Houdini control

## Workstreams

## Workstream 1. Document Contract and Agent Surface

Status:

- completed

Owns:

- Sprint 0. Architecture Lock
- Sprint 3. Document Read Surface
- Sprint 4. Working Copies, Validation, and Diff
- Sprint 7. Migration of Existing MCP Surface

Immediate focus:

- delivered:
  - locked network-document schema and first-wave MCP contract
  - `document.*` tool surface for checkout, validate, diff, apply, query, and sync
  - document resources for scene, network, schema, checkout, and diagnostics
  - document-first default discovery with legacy tools retained as compatibility entry points

## Workstream 2. Graph Store and Live Sync

Status:

- completed

Owns:

- Sprint 1. Embedded Graph Store Core
- Sprint 2. Live Import and Dirty-Scope Sync
- graph-store and importer hardening slices from Sprint 9

Immediate focus after Workstream 1 contract lock:

- delivered:
  - embedded SQLite graph store with latest-document state, historical revisions, indexes, checkout persistence, apply commits, and live-sync state
  - store-backed scene and network document reads plus store-backed document query
  - scene-monitor listener integration with scope-aware dirty tracking
  - live import at network scope, including top-level root-network sync and explicit subnetwork-scope sync

## Workstream 3. Apply Compiler and Domain Adapters

Status:

- implemented in code; live Houdini validation pending

Owns:

- Sprint 5. Apply Compiler for SOP Networks
- Sprint 6. Code Blob and Expression Adapters
- Sprint 8. Broader Network Coverage
- apply and rollback hardening slices from Sprint 9

Immediate focus after Workstream 2 foundation work:

- delivered:
  - uid-based structural diff and ordered apply-plan compilation for create, rename, reparent, connect, parm, expression, code, flag, layout, and delete stages
  - code-blob adapters for supported VEX, Python, and script-parm surfaces plus structural channel-reference compilation
  - rollback-on-failure verification, apply timing instrumentation, and SQLite-backed apply audit rows
  - document-apply coverage extended across `/obj`, `/mat`, `/stage`, `/tasks`, and `/out` network families through the shared document contract

## Workstream Dependencies

- Workstream 1 defines the contract that Workstream 2 stores and Workstream 3 applies.
- Workstream 2 provides the persistence and live-sync foundation that Workstream 3 depends on.
- Workstream 3 should not invent its own document shape or importer behavior; it must implement against Workstream 1 and Workstream 2 outputs.

## Sprint 0. Architecture Lock

Outcome:

- the overhaul has a fixed contract before code starts spreading across the repo

Deliverables:

- document schema outline
- resource URI plan
- tool naming plan
- apply modes
- compatibility and deprecation policy
- locked artifacts:
  - `docs/document-contract-v1.md`
  - `docs/schemas/network-document-v1.schema.json`

Exit criteria:

- the team can point to one approved document shape and one approved migration path

## Sprint 1. Embedded Graph Store Core

Outcome:

- the server has a real intermediary persistence and revision layer

Deliverables:

- SQLite-backed graph store module
- document, node, edge, parm, code-blob, checkout, and commit tables
- revision metadata and optimistic concurrency support
- projection cache for hot network documents

Exit criteria:

- a network scope can be stored, versioned, and reloaded without using the old flat snapshot cache as the source of truth

## Sprint 2. Live Import and Dirty-Scope Sync

Outcome:

- live Houdini state can be imported into the store at network granularity

Deliverables:

- root-network importer
- subnetwork importer
- dirty-scope tracking from the scene monitor
- external-live-edit commit classification

Exit criteria:

- editing `/obj/geo1` directly in Houdini results in a refreshed `/obj/geo1` network document revision

## Sprint 3. Document Read Surface

Outcome:

- agents can read scene and network documents as canonical JSON

Deliverables:

- `houdini://documents/scene`
- `houdini://documents/network/{path}`
- document schema resource
- canonical JSON serialization rules
- document query tool over the new store

Exit criteria:

- agents no longer need `node.list` plus many `node.get` calls to understand a subnetwork

## Sprint 4. Working Copies, Validation, and Diff

Outcome:

- agents can edit documents safely before touching the live scene

Deliverables:

- checkout model
- `document.checkout`
- `document.validate`
- `document.diff`
- diagnostic payload model

Exit criteria:

- an agent can create a working copy, edit it, validate it, and inspect an exact diff without mutating Houdini

## Sprint 5. Apply Compiler for SOP Networks

Outcome:

- the first real document-to-Houdini apply path exists

Deliverables:

- structural diff compiler
- ordered live apply plan
- reconcile, merge, and validate-only modes
- post-apply verification
- one-undo-group execution

Exit criteria:

- an edited SOP network document can be applied end-to-end without imperative node calls from the agent

## Sprint 6. Code Blob and Expression Adapters

Outcome:

- document edits can represent scripting surfaces instead of shoving raw strings directly into random parms

Deliverables:

- VEX code blob adapter
- Python code blob adapter for supported nodes
- expression and channel-reference adapter
- diagnostics for code-target mismatches

Exit criteria:

- wrangle snippets and supported Python-scripted nodes round-trip through the document model

## Sprint 7. Migration of Existing MCP Surface

Outcome:

- the old tool surface is preserved only as a compatibility layer

Deliverables:

- legacy `graph.*` translation layer
- legacy `node.*` and `parm.*` compatibility wrappers
- hidden-by-default discovery policy for legacy tools
- updated agent guidance docs

Exit criteria:

- new workflows use document tools first and higher-level tools route through the document pipeline

## Sprint 8. Broader Network Coverage

Outcome:

- the architecture is no longer SOP-only

Deliverables:

- `/mat` and material-builder coverage
- `/stage` and LOP network coverage
- `/tasks` and TOP network coverage where representable
- HDA and locked-boundary handling policy

Exit criteria:

- at least three major Houdini network families can be edited through the same document contract

## Sprint 9. Hardening and Deprecation

Outcome:

- the redesign is stable enough to become the default path

Deliverables:

- performance profiling and cache tuning
- audit coverage for document apply
- rollback and recovery hardening
- deprecation notices for old graph mutation tools

Exit criteria:

- document resources and document apply are the default, documented path for agent workflows

## Recommended Execution Order

Critical path:

1. Sprint 0
2. Sprint 1
3. Sprint 2
4. Sprint 3
5. Sprint 4
6. Sprint 5
7. Sprint 6
8. Sprint 7
9. Sprint 8
10. Sprint 9

Reason:

- the store and importer have to exist before read resources are trustworthy
- read resources and validation have to exist before apply can be safe
- apply has to work for one network family before broad coverage or migration work begins
