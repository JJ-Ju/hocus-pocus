# HocusPocus Improvement Roadmap

Status: active roadmap

Branch: `codex/develop`

Scope:

- strengthen the existing Houdini-hosted MCP server
- make the MCP interface easier for agents to use reliably
- expand the server where that adds practical automation power

This roadmap is intentionally focused on the current Python/HOM server. It does not assume the HDK bridge, Python Panel, or HAPI worker plane are available yet.

## 1. Goals

Primary goals:

- make the server safe by default
- make the server self-describing and easy for agents to reason about
- reduce the number of tool calls agents need for common tasks
- add the highest-value missing automation features next

Non-goals for this phase:

- large UI work
- native/HDK work
- distributed execution
- exhaustive automated test infrastructure

## 2. Priorities

Priority order:

1. Security and safety hardening
2. Agent-facing interface consistency
3. Dynamic resources and better scene state access
4. Long-running task support for real Houdini workloads
5. Higher-level workflow and modeling tools
6. Internal refactoring for maintainability

## 3. Roadmap Phases

## Phase A. Safe Defaults

Problem:

- the current auth model is undermined by status/health payload design
- config-based permissions exist conceptually but are not enforced
- file-writing tools are not restricted to approved roots

Deliver:

- no token leakage in unauthenticated responses
- authenticated or sanitized health/status endpoints
- explicit capability checks per tool
- approved-root enforcement for filesystem writes
- audit logging for tool calls and write operations

Why this comes first:

- the server already performs destructive scene and file operations
- more power without safety will make the system harder to trust

## Phase B. Agent-Usable MCP Surface

Problem:

- agents still need too many low-level tool calls for common reads
- tool outputs are inconsistent across read vs write operations
- there are too few stable resource URIs for scene exploration

Deliver:

- dynamic resources for nodes, parms, and geometry summaries
- consistent response shapes across read and write tools
- richer session/scene resources
- managed snapshot outputs and discoverable camera information

Why this matters:

- agents become more capable when state is browseable and stable
- reducing round-trips improves both speed and robustness

## Phase C. Real Workload Execution

Problem:

- the server lacks first-class cook/render task workflows
- long operations still do not expose the full task/progress model needed for production use

Deliver:

- task registry with durable task ids
- `cook.node`
- `render.rop`
- cancel, poll, and progress reporting
- log resources for recent task output

Why this matters:

- real Houdini automation is not just CRUD
- cooks, renders, and exports are core workloads

## Phase D. Higher-Level Agent Primitives

Problem:

- low-level node authoring works, but agents still have to manually assemble too many primitive operations

Deliver:

- semantic graph-building helpers
- modeling macros such as simple asset/blockout generators
- scene utility helpers such as turntable camera creation and preview snapshot flows
- geometry summary tools for quick reasoning

Why this matters:

- agents are more reliable with fewer opportunities to make brittle low-level mistakes

## Phase E. Internal Refactoring

Problem:

- `live/operations.py` is becoming the entire product surface in one file
- maintainability and reviewability will degrade as more features are added

Deliver:

- split operation domains into separate modules
- shared schema helpers
- clearer boundary between tool registration and Houdini implementation

Why this matters:

- this is what keeps future additions from turning into chaos

## 4. Recommended Feature Additions

## 4.1 Highest-value additions

- Dynamic node resources:
  - `houdini://nodes/<path>`
  - `houdini://nodes/<path>/parms`
  - `houdini://nodes/<path>/geometry-summary`
- Filesystem-safe snapshot capture with server-managed default output paths
- `cook.node`
- `render.rop`
- geometry inspection summaries:
  - primitive count
  - point count
  - bbox
  - groups
  - materials
- transaction/batch tool for multi-step graph edits

## 4.2 High-value ergonomics

- consistent read/write response schemas
- explicit “active display/output node” resource views
- camera framing helpers
- tool-call labels that are clearer in audit/task logs

## 4.3 Higher-level agent tools

- `model.create_house_blockout`
- `network.build_sop_chain`
- `scene.create_turntable_camera`
- `snapshot.capture_turntable`

These should come after the low-level surface is safe and stable.

## 5. Risks

- Safety work delayed too long will multiply cleanup cost later.
- Dynamic resources will require careful path encoding and invalidation.
- Task support will force more explicit state management in the runtime.
- Refactoring too early can slow progress; refactoring too late can harden bad interfaces.

## 6. Recommended Sequence

Immediate sequence:

1. Fix auth leakage and enforce write/path permissions.
2. Add dynamic resources and normalize tool outputs.
3. Add taskified cook/render support.
4. Add managed snapshots and geometry summaries.
5. Add batch/transaction graph-edit support.
6. Split `live/operations.py` by domain.

## 7. Success Criteria

This roadmap phase is successful when:

- an agent can safely connect without hidden auth flaws
- an agent can browse stable scene state through resources instead of only tool calls
- an agent can build, inspect, cook, render, and snapshot a scene with clear progress and fewer brittle steps
- the codebase remains easy to extend without one giant operations file owning everything
