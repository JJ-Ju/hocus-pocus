# HocusPocus Phase 5.5 Engineering Tracker

Status: active

Source roadmap: `docs/phase5.5roadmap.md`

Branch: `codex/phase5.5`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P5.5-M1 Helper correctness and shared inference
2. P5.5-M2 Helper payload quality
3. P5.5-M3 Generic node discovery and low-level authoring
4. P5.5-M4 Bounded introspection
5. P5.5-M5 Graph authoring ergonomics
6. P5.5-M6 Relational modeling and assembly validation

## P5.5-M1. Helper Correctness and Shared Inference

Status: not started

Goal:

- make scene helpers scale-aware, consistent, and trustworthy

Tasks:

- [ ] Centralize bbox/target-fit logic for geometry-targeting helpers.
- [ ] Reuse that logic in `scene.create_turntable_camera`.
- [ ] Reuse that logic in `lookdev.create_three_point_light_rig`.
- [ ] Make the light-rig helper scale-aware for small, medium, large, and exterior assets.
- [ ] Add an explicit viewport activation option and result reporting for the camera helper.

Done when:

- camera and light helpers infer the same target center for the same asset
- large exterior assets are not black silhouettes under the default light rig
- camera-helper payloads state whether the viewport is actually using the created camera

Manual smoke:

- target a tall tower or building asset with both helpers
- verify the target placement matches between them
- verify the light type and intensity are usable for a large exterior asset

## P5.5-M2. Helper Payload Quality

Status: not started

Goal:

- make helper outputs self-validating enough that users need fewer follow-up queries

Tasks:

- [ ] Return authored light type, target position, inferred bounds, and placement mode from the light-rig helper.
- [ ] Return camera activation state, target position, and fit summary from the turntable helper.
- [ ] Add warnings for suspicious helper results such as under-targeting or point lights on large assets.

Done when:

- helper payloads expose the key authored decisions that determine whether the result is sane

Manual smoke:

- run the helpers on both small and large assets
- verify the payload alone is enough to explain what was authored

## P5.5-M3. Generic Node Discovery and Low-Level Authoring

Status: not started

Goal:

- let agents discover valid node types, input shapes, and key parms without guessing

Tasks:

- [ ] Add node-type discovery by category, starting with SOP and OBJ node types.
- [ ] Add a node-type info read tool with label, category, and key parm metadata.
- [ ] Add at least one batching primitive for low-level authoring such as `parm.set_many`.
- [ ] Document the preferred low-level flow: discover type, inspect info, create node, set many parms, connect.

Done when:

- an agent can move from a Houdini concept like “wrangle” or “copy-to-points” to a valid node type and basic authoring surface without trial-and-error probing

Manual smoke:

- discover SOP node types
- inspect at least one specific node type such as wrangle, copy-to-points, or boolean
- create a node using the discovered type and set multiple parms in one call

## P5.5-M4. Bounded Introspection

Status: not started

Goal:

- make large parm or node introspection reads more robust

Tasks:

- [ ] Add filtering or pagination to `parm.list`.
- [ ] Support at least category or name-prefix filtering for parm listings.
- [ ] Improve bounded-response errors when payload size becomes excessive.

Done when:

- large light or render nodes can be inspected without transport failures or excessive fallback to many single-parm reads

Manual smoke:

- run `parm.list` on a light and render node
- verify large payloads either succeed through filtering or fail with a clear bounded-response error

## P5.5-M5. Graph Authoring Ergonomics

Status: not started

Goal:

- reduce friction when authoring repeated procedural structures

Tasks:

- [ ] Improve `graph.batch_edit` ergonomics for repeated SOP patterns.
- [ ] Add at least one low-friction convenience helper for common connect-and-flag or connect-and-output sequences.
- [ ] Document the preferred system-building workflow for repeated structures without reintroducing misleading canned macros.

Done when:

- authoring repeated structures requires materially fewer MCP calls while still producing an inspectable graph

Manual smoke:

- build a repeated façade or roof-detail structure
- compare required calls before and after the ergonomics improvements

## P5.5-M6. Relational Modeling and Assembly Validation

Status: not started

Goal:

- make procedural architectural assembly more relational and less absolute-value-driven

Tasks:

- [ ] Add face- or bbox-relative placement helpers.
- [ ] Add named reference-plane or driver helpers for later-node binding.
- [ ] Add overlap- or tolerance-oriented helpers for contact and watertight assembly.
- [ ] Add validation tools for gaps, near-misses, and suspicious offsets between assembled parts.

Done when:

- agents can place architectural parts relative to shared planes or faces without constantly hand-authoring raw offsets
- the toolkit can detect common non-watertight assembly mistakes

Manual smoke:

- assemble a façade or roof edge from multiple parts using reference planes and relative placement
- run validation and confirm gaps or suspicious near-misses are reported

## 2. Immediate Next Actions

Recommended next implementation order:

1. P5.5-M1 helper correctness and shared inference
2. P5.5-M2 helper payload quality
3. P5.5-M3 generic node discovery and low-level authoring
4. P5.5-M4 bounded introspection
5. P5.5-M5 graph authoring ergonomics
6. P5.5-M6 relational modeling and assembly validation

## 3. Session Log

### 2026-03-11

- Removed misleading canned macro tools from the default public surface so the toolkit emphasizes direct system-building rather than fixed generators.
- Logged helper and ergonomics feedback around:
  - scale-aware lighting
  - shared targeting inference
  - helper payload completeness
  - `parm.list` robustness
  - repeated-structure authoring friction
  - relational modeling and watertight assembly validation
- Added a new phase-5.5 workstream for generic node discovery and low-level authoring so agents can discover valid node types and key parms without blind trial and error.
