# HocusPocus Phase 5 Roadmap

Status: active roadmap

Branch: `codex/phase5`

Scope:

- improve agent usability, operator trust, and runtime maturity
- make the MCP surface easier to understand, safer to configure, and easier to observe
- add the in-Houdini experience and event model needed for day-to-day use
- leave asset-building macros and bespoke content-generation helpers for phase 6

This phase assumes the current baseline from phases 1 through 4:

- strong live scene automation and graph-aware planning
- production-oriented HDA, dependency, render, packaging, Solaris, and PDG support
- richer tool metadata, tasking, safety controls, and validation

## 1. Goals

Primary goals:

- reduce agent ambiguity through better contracts, examples, and compatibility guarantees
- make HocusPocus easier for less technical users to install, trust, and operate
- reduce polling-heavy workflows through event streaming and better in-app visibility
- improve runtime safety and confidence with repeatable regression coverage

Non-goals for this phase:

- bespoke asset generators and procedural macros
- simulation-specific authoring layers
- cloud farm integration
- HDK-native acceleration as a primary implementation path

## 2. Priority Order

1. contracts, docs, and regression smokes
2. policy profiles and error normalization
3. in-Houdini panel and self-contained operator UX
4. event streaming and subscriptions
5. runtime worker-plane options and advanced operability

## 3. Phases

## Phase 5A. Contracts, Docs, and Regression Coverage

Problem:

- the server is powerful, but it still relies too much on implicit agent knowledge and manual smoke discipline

Deliver:

- a stable compatibility and deprecation policy for Houdini 21.x and MCP surface changes
- canonical workflow guidance for agents and operators
- stronger output/error contracts for the most important tools
- end-to-end regression smoke coverage for live Houdini-hosted flows

## Phase 5B. Policy Profiles and Error Normalization

Problem:

- current policy controls are flexible, but not ergonomic for less technical users, and some runtime failures still require interpretation

Deliver:

- named config profiles such as `safe`, `local-dev`, and `pipeline`
- clearer machine-readable error families and consistent failure payloads
- better operator-facing status for auth, safety, and policy decisions

## Phase 5C. In-Houdini Panel and Operator Experience

Problem:

- the server runs in Houdini, but users still have to inspect it mostly from shells, logs, or external clients

Deliver:

- a Python Panel or Qt panel for HocusPocus
- status, endpoint, token, and health visibility
- recent tasks, events, and quick actions
- optional embedded terminal or agent-launch surface for self-contained operation

## Phase 5D. Event Streaming and Subscription Model

Problem:

- polling works, but it is wasteful and too slow for richer agent collaboration or UI experiences

Deliver:

- subscription-capable event transport for scene, task, and selection changes
- graph-delta or scene-delta event payloads where practical
- cleaner event history and replay boundaries

## Phase 5E. Worker Plane and Runtime Extensions

Problem:

- UI-hosted execution is the right default, but some workloads benefit from a separate worker lane or headless execution model

Deliver:

- a documented worker-plane design for headless/background operations
- initial HAPI or Engine-backed worker experiments where they materially reduce UI coupling
- runtime observability improvements around worker selection, fallback, and failure handling

## 4. Recommended Sequence

1. contracts, docs, and regression coverage
2. policy profiles and error normalization
3. in-Houdini panel and operator UX
4. event streaming and subscriptions
5. worker-plane and runtime extensions

## 5. Success Criteria

This phase is successful when:

- a new user can install, connect, and trust the server without reading source code
- an agent can choose tools with less guesswork because contracts and examples are explicit
- failures are easier to classify and recover from programmatically
- event-driven workflows reduce polling and improve responsiveness
- the Houdini-hosted experience feels like a product, not just a server

## 6. Explicit Deferral to Phase 6

The following are intentionally deferred to phase 6:

- bespoke procedural asset generators
- environment and vegetation macros
- simulation setup macros
- reusable modeling, shading, and layout recipe libraries
- agent-oriented asset-building helper suites
