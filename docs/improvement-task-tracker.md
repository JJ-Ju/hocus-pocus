# HocusPocus Improvement Task Tracker

Status: active

Source roadmap: `docs/improvement-roadmap.md`

Branch: `codex/develop`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. M12 Auth and health hardening
2. M13 Safety enforcement and audit
3. M14 Dynamic resources and interface normalization
4. M15 Taskified cooks, renders, and progress
5. M16 Higher-level agent primitives
6. M17 Operations module refactor

## M12. Auth and Health Hardening

Status: complete

Goal:

- remove auth flaws and make status endpoints safe by default

Tasks:

- [x] Remove bearer token exposure from all normal status and health payloads.
- [x] Decide whether health requires auth or returns only non-sensitive data.
- [x] Ensure no unauthenticated route exposes connection secrets or sensitive scene metadata.
- [x] Add a clear “auth disabled” indicator when token auth is turned off intentionally.
- [x] Validate that Codex app and manual HTTP clients still connect cleanly after the changes.

Done when:

- unauthenticated requests cannot discover the bearer token
- health/status data is intentionally scoped and non-sensitive
- existing clients can still connect with the documented token flow

Manual smoke:

- request health without auth
- request MCP methods with and without auth
- verify no token is present in any unauthenticated payload

## M13. Safety Enforcement and Audit

Status: complete

Goal:

- enforce the safety model that currently exists mostly as configuration intent

Tasks:

- [x] Add a capability requirement map for each tool.
- [x] Enforce tool capabilities from request context and server config.
- [x] Enforce approved-root restrictions for file-writing tools such as hip save and viewport capture.
- [x] Add a read-only mode that blocks scene mutations.
- [x] Add structured JSONL audit logging for tool calls and file writes.
- [x] Include operation id, tool name, caller id, arguments summary/hash, and result in audit records.

Done when:

- destructive tools can be blocked centrally
- file outputs cannot escape configured roots unless explicitly allowed
- every tool call leaves an audit record

Manual smoke:

- attempt blocked save/capture paths
- enable an allowed root and verify the same write succeeds
- inspect the generated audit log

## M14. Dynamic Resources and Interface Normalization

Status: complete

Goal:

- make the MCP surface easier for agents to explore and chain

Tasks:

- [x] Add node-path-addressable resources such as `houdini://nodes/<path>`.
- [x] Add parameter resources such as `houdini://nodes/<path>/parms`.
- [x] Add geometry summary resources such as `houdini://nodes/<path>/geometry-summary`.
- [x] Normalize write-tool outputs so they align with corresponding read-tool summaries.
- [x] Add explicit URI/path encoding rules for dynamic resource lookup.
- [x] Expose display/output node state where relevant.
- [x] Add richer error messages when a node or parm path is invalid.

Done when:

- an agent can inspect nodes and parms through resources instead of repeated tool calls
- write tools return enough structured state to avoid immediate follow-up reads
- resource lookup is stable and documented

Manual smoke:

- read a node resource for an object node and a SOP node
- read the associated parm resource
- compare `node.get` and `node.create` output shapes for consistency

## M15. Taskified Cooks, Renders, and Progress

Status: complete

Goal:

- support real Houdini workloads beyond graph editing

Tasks:

- [x] Add a task registry resource with durable task ids.
- [x] Implement `cook.node`.
- [x] Implement `render.rop`.
- [x] Add progress state and cancellation support for those tasks.
- [x] Add recent task log resources.
- [x] Add task result summaries and failure reasons.

Done when:

- a client can launch a cook or render without blocking the request lifecycle
- progress and cancellation are visible through MCP
- task state remains inspectable after completion

Manual smoke:

- launch a node cook
- launch a small render
- cancel one run and allow another to finish

## M16. Higher-Level Agent Primitives

Status: complete

Goal:

- reduce the number of brittle low-level tool calls agents need for common work

Tasks:

- [x] Add a batch or transaction tool for grouped node edits.
- [x] Add a geometry summary tool or resource for bbox, counts, groups, and materials.
- [x] Add a scene helper for creating a turntable camera.
- [x] Add a snapshot helper that can write to a managed temp location when no path is supplied.
- [x] Add one high-level modeling macro as a proof point.

Done when:

- an agent can perform a meaningful multi-step graph edit through one higher-level entry point
- scene inspection includes geometry-level facts, not just node metadata
- snapshots are easier to request without manual path management

Manual smoke:

- use the batch/transaction tool to build a small network
- request a geometry summary
- capture a viewport snapshot without pre-creating a custom output path

## M17. Operations Module Refactor

Status: complete

Goal:

- reduce maintenance risk from the large all-in-one operations module

Tasks:

- [x] Split `live/operations.py` into domain modules:
  - session
  - scene
  - node
  - parm
  - viewport
  - resources
- [x] Extract shared schema and response helpers.
- [x] Keep registration centralized but implementation domain-specific.
- [x] Preserve existing tool names and wire compatibility during the refactor.

Done when:

- the code is split by domain without changing public behavior
- new tools can be added without expanding one monolithic file

Manual smoke:

- rerun the existing live MCP checks after the refactor
- verify tool names and responses remain stable

## 2. Immediate Next Actions

Recommended next implementation order:

1. M12 Auth and health hardening
2. M13 Safety enforcement and audit
3. M14 Dynamic resources and interface normalization

Those three items improve safety and agent usability the most with the least product churn.

## 3. Session Log

### 2026-03-09

- Created the improvement roadmap from the current codebase review.
- Created a concrete task tracker for the next server improvement phase.
- Completed M12 with sanitized health/status payloads, explicit auth-required indicators, and local HTTP validation.
- Completed M13 with per-tool capability enforcement, approved-root write policy, read-only mode, and JSONL audit logging.
- Implemented the M14 code path for dynamic node resources and normalized outputs, but left the milestone in progress until those resources are smoke-tested against a live Houdini session.
- Implemented the M15 task registry, task resources, task logs, and cancellation model, and locally validated those with a transient runtime. `cook.node` and `render.rop` remain in progress until they are smoke-tested against a live Houdini session.
- Live-validated M14 against Houdini 21.0 with real object/SOP node resources, parm resources, and geometry-summary resources.
- Live-validated successful `cook.node` and `render.rop` task execution against Houdini 21.0, including task polling, recent-task resources, task logs, and a Geometry ROP writing a `.bgeo.sc` output.
- Live-validated render-task cancellation against Houdini 21.0. A long render was cancelled mid-run, the task entered `cancelled`, and partial frame outputs remained on disk as expected.
- Completed M16 with live validation of `graph.batch_edit`, `geometry.get_summary`, `scene.create_turntable_camera`, managed-path `snapshot.capture_viewport`, and `model.create_house_blockout`.
- Completed M17 by splitting the monolithic live operations implementation into domain mixins under `python3.11libs/hocuspocus/live/ops/` while preserving the public MCP surface.
