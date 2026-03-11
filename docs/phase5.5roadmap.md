# HocusPocus Phase 5.5 Roadmap

Status: active roadmap

Branch: `codex/phase5.5`

Scope:

- remove or hide misleading canned macro tools from the default surface
- tighten the core toolkit around reliable helper behavior and better agent ergonomics
- improve relational modeling support so agents can assemble watertight procedural assets with less brittle absolute-value authoring

This phase assumes the current baseline from phases 1 through 5:

- strong live node, parm, graph, task, USD, PDG, render, dependency, packaging, and HDA support
- transport-level MCP fixes for Streamable HTTP
- low-level graph editing surface that is powerful but still awkward for architecture-style relational assembly

## 1. Goals

Primary goals:

- make helper tools scale-aware and internally consistent
- improve helper payloads so they are self-validating and easier to trust
- improve low-level node discovery and generic node authoring so agents can work in Houdini concepts directly
- reduce the number of low-level authoring calls needed for common repeated structures
- add relational modeling utilities so agents can place and validate parts relative to faces, planes, and bounds instead of raw absolute values

Non-goals for this phase:

- reintroducing canned building or house macros as the primary workflow
- full phase-6 asset-domain tooling
- replacing the low-level graph toolkit with opaque generators

## 2. Priority Order

1. helper correctness and shared targeting logic
2. helper output payload quality
3. generic node discovery and low-level authoring ergonomics
4. `parm.list` robustness and bounded responses
5. graph authoring ergonomics for repeated structures
6. relational modeling and assembly validation

## 3. Workstreams

## Phase 5.5A. Helper Correctness and Shared Inference

Problem:

- scene helpers that target geometry infer scale and target placement inconsistently
- light-rig defaults break down badly on building-scale assets
- helper tools do not reliably communicate whether they changed viewport state or not

Deliver:

- shared bbox/target-fit logic reused by:
  - `scene.create_turntable_camera`
  - `lookdev.create_three_point_light_rig`
  - future scene-targeting helpers
- scale-aware light defaults for small, medium, large, and exterior assets
- explicit viewport activation controls and reporting for camera helpers

Success looks like:

- helpers that target the same geometry agree on center and fit
- large exterior assets are not underlit by default
- users can tell from the response whether the viewport is actually looking through the created camera

## Phase 5.5B. Helper Payload Quality

Problem:

- helper outputs currently omit critical authored state, which makes validation harder than it should be

Deliver:

- authored-state summaries for helper tools, including:
  - inferred bounds
  - placement mode
  - authored light type or camera activation state
  - target position and fit distances
- warnings for suspicious authored states

Success looks like:

- a user or agent can tell whether a helper result is sane from the returned payload alone

## Phase 5.5C. Bounded Introspection

Problem:

- node-type discovery is weak and forces too much guessing around valid type names, labels, input counts, and parm surfaces
- agents know Houdini concepts such as wrangles, copy-to-points, booleans, and scatter, but the MCP does not yet provide a clean low-level discovery layer for what is actually available in this environment

Deliver:

- node-type discovery tools for SOP, OBJ, LOP, TOP, MAT, and DOP categories
- normalized node-type info for a given node type, including:
  - label
  - category
  - input count or input names where possible
  - common aliases
  - key parm info and defaults
- generic authoring improvements such as:
  - batch parm setting
  - simpler generic node creation flows
  - compatibility or category-based discovery such as “copying”, “attributes”, “instancing”, or “booleans”

Examples:

- `node_types.list`
- `node_types.get_info`
- `parm.set_many`
- `node.create` plus richer type discovery rather than many special wrappers

Success looks like:

- an agent can move from “I know the Houdini concept” to “I know the exact valid node type and key parms” without probing blindly
- serious procedural work relies on a stronger low-level graph API instead of many fragmented special-case tools

## Phase 5.5D. Bounded Introspection

Problem:

- some high-volume read tools are too fragile on large node types or large payloads

Deliver:

- pagination, filtering, or prefix/category filters for `parm.list`
- clearer bounded-response errors when payloads are too large
- documentation for the preferred fallback path when full listings are inappropriate

Success looks like:

- users do not need to fall back to many single-parm queries just to inspect a light or render node

## Phase 5.5E. Graph Authoring Ergonomics

Problem:

- repeated procedural structures still require too many low-level calls

Deliver:

- better `graph.batch_edit` ergonomics for common SOP authoring patterns
- convenience helpers for common wiring or flag-setting sequences
- lower-friction ways to instantiate repeated structural patterns without reintroducing misleading canned generators

Success looks like:

- procedural scene authoring requires materially fewer calls for repeated structures
- the result is still an inspectable Houdini graph, not an opaque macro

## Phase 5.5F. Relational Modeling and Assembly Validation

Problem:

- the toolkit is strong on low-level graph editing, but weak on relational modeling needed for watertight architectural assembly

Deliver:

- bbox- and face-relative placement helpers
- named reference-plane or driver helpers
- overlap- or tolerance-oriented assembly helpers
- validation tools for gaps, near-misses, and suspicious offsets

Examples:

- snap node A to the `+Z` face of node B with an offset
- place a part on the top face with overlap
- define and reuse planes like `wall_front_face` or `roof_underside`
- detect nearly-touching but non-overlapping surfaces

Success looks like:

- agents can author architectural assemblies with fewer raw absolute values
- watertight or intentionally overlapping contact between parts is easier to achieve and validate
