# HocusPocus Core Engineering Delivery Record

Status: historical core-runtime milestones complete; superseded for active V1
tracking

Current sources of truth:

- architecture and public surface: `houdini-mcp-spec.md`
- operator workflow: `user-manual.md`
- HocusScript implementation: `hocusscript-task-tracker.md`
- V1 release closure: `hocusscript-roadmap-completion-plan.md`
- release commands and gates: `release-validation.md`

This file replaces the original greenfield checklist, whose unchecked items
became misleading after later phases delivered the same outcomes through
different architecture. It preserves the useful milestone history without
presenting obsolete 2026-03 tasks as current work.

## 1. Current Product Baseline

The supported V1 runtime is exact Houdini `22.0.368`. The installed product now
provides:

- a normal Houdini package with explicit start/stop/status controls;
- a localhost Streamable HTTP host plus a client-owned stdio broker that can
  reconnect across Houdini restarts;
- serialized main-thread HOM execution and guarded mutation boundaries;
- scene, node, parameter, selection, playbar, viewport, cook, render, HDA,
  source-workspace, document, and production operations;
- permission profiles, approved-root enforcement, audit records, and
  destructive-operation policy gates;
- task progress, cancellation, logs, and bounded durable operation-history
  reconciliation;
- dynamic resources, canonical schemas, a Houdini panel, and install/client
  configuration tooling;
- HocusScript source, compiler, module, document, guarded apply, and production
  qualification paths described by the HocusScript roadmap.

The product implementation has passed internal installed Houdini 22 technical
acceptance. That does not claim a production release: clean-image authority,
detached human visual approval, and final release publication remain governed
by the release-closure plan.

## 2. Historical Milestone Disposition

| Milestone | Original intent | Final disposition |
| --- | --- | --- |
| M0 | Package scaffold | Delivered and installed on Houdini 22 |
| M1 | MCP runtime and transport | Delivered; durable stdio broker fronts replaceable HTTP hosts |
| M2 | Live execution lane | Delivered; mutation integrity, undo/redo, rollback, quarantine, and revisions were hardened in M18 |
| M3 | Core scene automation | Delivered, including resources and OBJ Geometry bootstrap |
| M4 | Safety, auth, and audit | Delivered in improvement milestones M12-M13 and later trust-boundary repairs |
| M5 | Long-running jobs | Delivered with cook/render task state, progress, logs, and cancellation |
| M6 | Headless/runtime modes | Hython and clean-process qualification exist; speculative HAPI/HARS offload is post-v1, not a V1 blocker |
| M7 | Packaging and docs | Delivered; current operator guidance is in the README and user manual |
| M8 | Houdini panel | Delivered for server and source-workspace operation |
| M9 | Embedded terminal | Deferred product option; not required by the MCP product contract |
| M10 | HDK bridge | Deferred optimization; Python/HOM remains the supported runtime |
| M11 | Hardening and dogfooding | Delivered through live first-use, HocusScript HS4-HS8, and M18 acceptance |

## 3. Architectural Decisions That Replaced Early Assumptions

- The direct Houdini HTTP endpoint is a replaceable host, not the durable client
  session. Codex/Claude connect to the stdio broker, which rediscovers a live
  authenticated Houdini host after restart.
- Scene mutation is document-centric for substantial graph work. Agents
  checkout or compile content, validate and diff it, then apply through guarded
  immutable plans. Small purpose-built operations remain available where they
  remove bootstrap or operational friction.
- `.hocus` files are ordinary Git-visible code in a user-selected project
  directory. MCP source access is an explicit project-scoped authority, never a
  general filesystem surface.
- HAPI/HARS and an HDK bridge are possible future execution lanes, not missing
  requirements for the supported V1 Python/HOM product.
- Automated workflows are intentionally capped and scenario-oriented. Installed
  Houdini acceptance and real user workflows carry more weight than test count.

## 4. Remaining Work

No unchecked task in the original M0-M11 list is an active V1 implementation
ticket. Remaining work falls into two explicit groups:

1. V1 release authority and immutable-candidate evidence in
   `hocusscript-roadmap-completion-plan.md`.
2. Post-v1 breadth such as HAPI/HARS offload, an optional HDK bridge, richer
   connector metadata, notifications, and additional production fixtures.

New work should be added to the HocusScript tracker or a new post-v1 roadmap,
not appended to this historical file.

## 5. Historical Note

The original tracker began on 2026-03-09 as a greenfield, code-first plan. It
correctly established the package scaffold, localhost MCP runtime, serialized
dispatcher, initial scene/node/parameter operations, build/install script, and
orientation resources. Later phase trackers and live acceptance superseded its
per-task state. This condensed record intentionally removes stale claims such
as "pending Houdini validation," "safety not started," and "resource templates
missing," all of which contradicted the accepted implementation.
