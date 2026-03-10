# HocusPocus Phase 5 Engineering Tracker

Status: active

Source roadmap: `docs/phase5roadmap.md`

Branch: `codex/phase5`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P5-M1 Contracts, docs, and regression smokes
2. P5-M2 Policy profiles and error normalization
3. P5-M3 In-Houdini panel and operator UX
4. P5-M4 Event streaming and subscriptions
5. P5-M5 Worker-plane and runtime extensions

## P5-M1. Contracts, Docs, and Regression Smokes

Status: not started

Goal:

- reduce agent ambiguity and replace ad hoc validation with repeatable smoke coverage

Tasks:

- [ ] Publish a compatibility policy for Houdini `21.x`, MCP protocol assumptions, and breaking-change expectations.
- [ ] Add canonical workflow docs for common agent tasks such as scene inspection, graph planning, render validation, packaging, and PDG control.
- [ ] Normalize high-value tool contracts with explicit output schemas, examples, and failure notes where still missing.
- [ ] Add an end-to-end smoke harness for the Houdini-hosted server covering live mutation, tasks, graph reads, and exports.
- [ ] Document release validation gates so installed builds and committed builds stay aligned.

Done when:

- an agent or operator can understand the intended use of the main tools without reading implementation files
- live regression smoke results can be reproduced without manual improvisation
- compatibility expectations are explicit in the docs

Manual smoke:

- run the documented regression smoke against a live Houdini session
- verify the smoke report covers scene mutation, tasks, graph reads, packaging, Solaris, and PDG

## P5-M2. Policy Profiles and Error Normalization

Status: not started

Goal:

- make policy controls easier to use and failures easier to interpret programmatically

Tasks:

- [ ] Add named policy profiles such as `safe`, `local-dev`, and `pipeline`.
- [ ] Surface active policy profile and effective permissions through status and resource payloads.
- [ ] Normalize machine-readable error families for validation, policy, auth, runtime, and unsupported-operation failures.
- [ ] Ensure major tools return consistent error payload structure with stable fields.
- [ ] Improve operator-facing health or diagnostics output for policy and auth state.

Done when:

- a user can choose a policy mode without manually editing multiple low-level settings
- clients can distinguish policy failures from Houdini runtime failures reliably
- status payloads explain the current effective safety posture clearly

Manual smoke:

- switch between at least two policy profiles and verify effective behavior changes
- trigger validation, policy, and runtime failures and confirm normalized error categories

## P5-M3. In-Houdini Panel and Operator UX

Status: not started

Goal:

- make HocusPocus operable from inside Houdini without dropping to a shell

Tasks:

- [ ] Build a Python Panel or Qt panel that shows server status, endpoint, token, and health.
- [ ] Show recent tasks, recent events, and basic logs in the panel.
- [ ] Add quick actions for start, stop, restart, copy endpoint, and copy token.
- [ ] Add a lightweight agent-launch or terminal integration design, and implement it if feasible without destabilizing the core server.
- [ ] Document the panel workflow and default install experience.

Done when:

- a user can verify and operate the server entirely from inside Houdini
- recent activity is visible without opening log files
- the install experience feels one-click and self-explanatory

Manual smoke:

- launch Houdini, verify the panel shows a running server
- start or stop the server and confirm the panel updates correctly
- confirm task and event activity appears in-panel after a live tool call

## P5-M4. Event Streaming and Subscriptions

Status: not started

Goal:

- reduce polling and support more responsive agent and UI workflows

Tasks:

- [ ] Design and implement an event subscription transport compatible with the current server model.
- [ ] Stream scene, task, selection, and graph-invalidated events where practical.
- [ ] Add replay or since-revision semantics for reconnecting clients.
- [ ] Ensure event payloads are compact, typed, and consistent with existing resource summaries.
- [ ] Document when to use polling versus subscriptions.

Done when:

- a client can subscribe to live server events instead of polling most resources repeatedly
- reconnecting clients can catch up from a known point without full resync
- event traffic is predictable and useful for agent planning

Manual smoke:

- connect a subscriber and verify scene edit, task, and selection events arrive live
- disconnect and reconnect using replay or since-revision semantics and confirm missed events are recovered

## P5-M5. Worker-Plane and Runtime Extensions

Status: not started

Goal:

- improve runtime flexibility for workloads that should not depend entirely on the interactive Houdini UI lane

Tasks:

- [ ] Document worker-plane execution modes and selection rules.
- [ ] Add an experimental headless or HAPI-backed worker path for suitable operations.
- [ ] Surface worker selection and fallback behavior in task or status payloads.
- [ ] Add diagnostics for worker startup, failure, and recovery.
- [ ] Validate that worker-plane additions do not regress the current in-process HOM-first model.

Done when:

- suitable workloads can opt into or transparently use a non-UI worker path
- operators can see which execution lane handled a task
- fallback behavior is explicit and observable

Manual smoke:

- run at least one supported task through the worker lane and confirm results
- force a worker failure and verify fallback or recovery behavior is reported clearly

## 2. Immediate Next Actions

Recommended next implementation order:

1. P5-M1 contracts, docs, and regression smokes
2. P5-M2 policy profiles and error normalization
3. P5-M3 in-Houdini panel and operator UX

These are the highest-value usability and trust improvements after the completed platform and pipeline phases.

## 3. Session Log

### 2026-03-10

- Created the phase-five roadmap around productization, contracts, operator UX, event streaming, and runtime maturity.
- Explicitly deferred bespoke asset-building helpers and macros to phase 6 so phase 5 can stay focused on platform usability and trust.
- Created the phase-five engineering tracker with milestone-level tasks, done criteria, and manual smoke gates.
