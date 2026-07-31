# Document Graph Overhaul Task Tracker

Status: active implementation

Source architecture:

- `docs/document-graph-overhaul-spec.md`

Current state:

- planning documents created
- Workstream 1 completed with runtime document tools, resources, validation, diff, apply, and compatibility discovery changes

## 1. Completion Definition

This overhaul is complete when:

- network documents are the primary MCP authoring surface
- the server persists a revisioned intermediary graph store
- scene and network scopes can be read as canonical JSON documents
- agents can validate, diff, and apply edited documents without node-by-node imperative calls
- live Houdini edits sync back into the graph store with revision tracking
- legacy graph and node tools operate as compatibility shims or are deprecated

## 2. Tracking Rules

- only mark work complete when code exists and the workflow can be manually exercised
- keep the old tool surface working until the document surface can replace it for the same workflow
- do not let importer work and apply work diverge into incompatible models
- treat network scope as the main implementation boundary
- record new tasks here instead of opening parallel trackers for the same overhaul

## 3. Workstreams

## Workstream 1. Document Contract and Agent Surface

Status:

- completed

Owns milestones:

- DG0. Planning and Contract Lock
- DG3. Document Resources and Query
- DG4. Working Copies, Validation, and Diff
- DG7. Compatibility Migration

Completed scope:

- DG0 contract lock
- DG3 document resources and query
- DG4 working copies, validation, and diff
- DG7 compatibility migration

Locked artifacts:

- `docs/document-contract-v1.md`
- `docs/schemas/network-document-v1.schema.json`

## Workstream 2. Graph Store and Live Sync

Status:

- completed

Owns milestones:

- DG1. Embedded Graph Store
- DG2. Live Import and Sync

## Workstream 3. Apply Compiler and Domain Adapters

Status:

- implemented in code; live Houdini validation pending

Owns milestones:

- DG5. Apply Compiler
- DG6. Code Blob and Expression Adapters
- DG8. Expanded Network Coverage
- DG9. Hardening

## 4. Milestones

## DG0. Planning and Contract Lock

Status: completed

Tasks:

- [x] Author the overhaul spec.
- [x] Author the overhaul roadmap.
- [x] Author the overhaul task tracker.
- [x] Lock the canonical network-document JSON schema.
- [x] Lock tool names and resource URIs for the first implementation slice.
- [x] Lock apply-mode semantics and legacy compatibility policy.

Done when:

- there is one approved schema and one approved first-wave tool and resource surface

Artifacts delivered:

- `docs/document-contract-v1.md`
- `docs/schemas/network-document-v1.schema.json`

## DG1. Embedded Graph Store

Status: completed

Tasks:

- [x] Add a dedicated graph-store package under `python3.11libs/hocuspocus/live/`.
- [x] Implement SQLite schema creation and migrations.
- [x] Add document, revision, node, edge, parm-binding, code-blob, checkout, and commit tables.
- [x] Add repository methods for load, save, query, and transactional updates.
- [x] Add a projection cache for hot scene and network documents.

Done when:

- the server can persist and reload a network document revision without relying on the old snapshot cache

## DG2. Live Import and Sync

Status: completed

Tasks:

- [x] Implement root network import for `/obj`, `/mat`, `/stage`, `/tasks`, and `/out`.
- [x] Implement recursive subnetwork import for subnet-like nodes.
- [x] Preserve stable ids across rename and move when possible using live node session ids when available, with path fallback.
- [x] Add dirty-scope tracking to the scene monitor.
- [x] Record direct user edits as external-live-edit imports in the store when sync follows non-tool monitor events.

Done when:

- changing one network in Houdini refreshes only the corresponding stored document scope

## DG3. Document Resources and Query

Status: completed

Tasks:

- [x] Register `houdini://documents/scene`.
- [x] Register `houdini://documents/network/{path}`.
- [x] Register the schema resource for the network-document contract.
- [x] Implement canonical JSON serialization with stable ordering.
- [x] Add `document.query` backed by the new document surface.

Done when:

- agents can inspect a whole network through one resource read and targeted graph-store queries

## DG4. Working Copies, Validation, and Diff

Status: completed

Tasks:

- [x] Implement checkout creation and lifecycle.
- [x] Add `document.checkout`.
- [x] Add `document.validate`.
- [x] Add `document.diff`.
- [x] Add structured diagnostic payloads with JSON pointers and Houdini paths.

Done when:

- an agent can create, edit, validate, and diff a working copy without mutating the live scene

## DG5. Apply Compiler

Status: implemented in code; live Houdini validation pending

Tasks:

- [x] Build baseline-vs-target structural diffing.
- [x] Compile ordered apply plans for create, rename, reparent, connect, parm, flag, and delete work.
- [x] Add reconcile, merge, and validate-only apply modes.
- [x] Execute applies in one undo group and one store transaction.
- [x] Reimport and verify the affected scope after apply.

Done when:

- an edited SOP network document can be applied to Houdini end-to-end

## DG6. Code Blob and Expression Adapters

Status: implemented in code; live Houdini validation pending

Tasks:

- [x] Implement VEX code-blob storage and install adapters.
- [x] Implement Python code-blob storage and install adapters for supported node families.
- [x] Implement expression and channel-reference compilation from structural document fields.
- [x] Add diagnostics for invalid code targets and unsupported script surfaces.

Done when:

- supported scripted nodes round-trip through the document model

## DG7. Compatibility Migration

Status: completed

Tasks:

- [x] Route `graph.query` through the new document-backed query path.
- [x] Let `graph.apply_patch` delegate into `document.apply` when a document or checkout is supplied.
- [x] Keep low-level `node.*` and `parm.*` tools as compatibility entry points while shifting default discovery to `document.*`.
- [x] Update agent workflow docs to prefer document resources and document apply.
- [x] Hide legacy graph, node, and parm tools from default discovery while preserving direct-call compatibility.

Done when:

- new workflows use document tools first and old workflows still function through compatibility shims

## DG8. Expanded Network Coverage

Status: implemented in code; live Houdini validation pending

Tasks:

- [x] Add material-network and material-builder document coverage.
- [x] Add Solaris network coverage for supported LOP authoring surfaces.
- [x] Add TOP network coverage where the document model maps cleanly.
- [x] Define locked-HDA and HDA-definition boundary behavior.

Done when:

- the document contract works for more than one major Houdini network family

## DG9. Hardening

Status: implemented in code; live Houdini validation pending

Tasks:

- [x] Add performance instrumentation for importer, projection, validation, and apply.
- [x] Add audit records at document and live-op levels.
- [x] Add rollback recovery for failed apply verification.
- [x] Add manual validation scripts or smoke procedures for document workflows.
- [x] Deprecate old imperative graph mutation paths once migration is complete.

Done when:

- document workflows are stable enough to become the default and documented path
