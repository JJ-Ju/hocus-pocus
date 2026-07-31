# HocusPocus Phase 5.6 Roadmap

Status: active roadmap

Branch: `codex/phase5.6`

Scope:

- overhaul the public MCP surface so it is smaller, more generic, and easier for agents to reason about
- shift the center of gravity from fragmented helper tools to a stronger low-level authoring and discovery layer
- make the graph index a first-class reasoning layer
- add the relational modeling primitives needed for serious procedural architectural and hard-surface work

This phase assumes the current baseline from phases 1 through 5.5:

- strong live scene automation and graph-aware planning
- production-oriented HDA, dependency, render, packaging, Solaris, and PDG support
- transport-level MCP fixes for Streamable HTTP
- helper correctness work underway for camera, lookdev, and bounded parameter inspection

## 1. Goals

Primary goals:

- reduce the default public tool surface from the current fragmented shape toward a coherent, high-signal core
- make node discovery and low-level authoring strong enough that an agent can work directly in Houdini concepts without blind trial and error
- elevate the graph index or “graph database” layer into the main inspection and planning surface
- make relational modeling first-class so agents can assemble watertight systems with shared planes, face-relative placement, and validation
- keep higher-level helpers only where they provide real leverage without obscuring Houdini

Non-goals for this phase:

- reintroducing canned asset generators as the default workflow
- replacing Houdini with opaque abstractions
- removing advanced workflows like PDG, USD, HDA, or packaging from the server

## 2. Desired End State

The end state should look like:

- a smaller canonical public tool list, roughly `55-65` tools instead of the current `97`
- strong generic primitives:
  - node discovery
  - node creation
  - connection
  - parm inspection
  - batch parm setting
  - graph inspection and planning
  - relational placement and validation
- a graph-first inspection model where agents can answer many structural questions before mutating anything
- helper tools that are:
  - scale-aware
  - self-describing
  - minimal in number
  - clearly additive rather than misleadingly magical

## 3. Principles

1. Prefer generic low-level authoring tools over many thin wrappers.
2. Prefer graph-backed discovery over memorized node-type strings.
3. Prefer relational placement over raw absolute coordinates.
4. Prefer compact, inspectable procedural systems over hardcoded one-shot outputs.
5. Prefer explicit contracts and payloads over hidden assumptions.

## 4. Priority Order

1. public tool-surface audit and consolidation
2. generic node discovery and low-level authoring
3. graph-layer promotion and unified graph reasoning
4. relational modeling and assembly validation
5. documentation and migration for the new canonical surface

## 5. Workstreams

## Phase 5.6A. Public Tool-Surface Consolidation

Problem:

- the current tool list is too large and too fragmented
- too many domain- or helper-specific wrappers dilute the main authoring model

Deliver:

- a public tool audit with:
  - keep
  - merge
  - hide
  - deprecate
- a canonical public surface centered on:
  - session or scene
  - node
  - parm
  - graph
  - material
  - render/export
  - PDG/USD/HDA/dependency/package
  - relational modeling
- hidden or advanced-only status for thin wrappers that do not add enough leverage

Success looks like:

- the public surface is materially smaller and easier to scan
- most serious work can be explained in terms of a few generic authoring families rather than many one-off tools

## Phase 5.6B. Generic Node Discovery and Authoring

Problem:

- the server supports Houdini node creation broadly, but does not yet expose Houdini’s node universe in a discoverable, normalized way

Deliver:

- node type discovery tools such as:
  - `node_types.list`
  - `node_types.get_info`
  - `node_types.list_compatible`
- category- and task-based discovery for:
  - SOP
  - OBJ
  - LOP
  - TOP
  - MAT
  - DOP
- stronger low-level authoring tools such as:
  - `parm.set_many`
  - `parm.set_many_expressions`
- clear metadata for:
  - node labels
  - input counts
  - common aliases
  - key parms
  - defaults

Success looks like:

- an agent can move from “I want a wrangle” or “I need a copy-to-points node” to a valid type name and basic parm surface without trial and error

## Phase 5.6C. Graph-Layer Promotion

Problem:

- the graph index exists, but it is not yet the obvious first place to look for structural understanding

Deliver:

- make the graph layer a first-class public workflow for:
  - discovery
  - inspection
  - diff
  - planning
  - dependency reasoning
- add any missing graph reads needed to support system authoring, such as:
  - branch-level geometry or bbox reads
  - stronger reference and dependency views
  - graph health and refresh visibility

Success looks like:

- an agent reaches for graph tools and graph resources before falling back to many one-off structural reads

## Phase 5.6D. Relational Modeling and Assembly Validation

Problem:

- architectural and hard-surface procedural work still relies too much on raw absolute values and manual mental math

Deliver:

- relational modeling tools such as:
  - `model.get_bbox`
  - `model.get_planes`
  - `model.snap_to_face`
  - `model.align_to_plane`
  - `model.create_reference_plane`
  - `model.validate_contacts`
- overlap, offset, and tolerance-aware placement
- gap, near-miss, floating-piece, and penetration detection

Success looks like:

- agents can assemble parts relative to shared planes and faces instead of constant raw-number authoring
- non-watertight assemblies are easier to detect and correct

## Phase 5.6E. Documentation and Migration

Problem:

- a surface overhaul is risky if users cannot tell what changed or what the preferred workflows are

Deliver:

- updated README and manual that explain:
  - the canonical public tool families
  - deprecated or hidden tools
  - node discovery workflow
  - graph-first workflow
  - relational modeling workflow
- migration notes from the current fragmented surface

Success looks like:

- agents and human operators can adopt the new surface without reading source code

## 6. Success Criteria

This phase is successful when:

- the default public tool list is materially smaller and more coherent
- the low-level generic authoring flow is strong enough that advanced procedural work no longer feels blocked by discovery friction
- graph tools become the main structural reasoning path
- relational modeling tools materially reduce assembly drift and non-watertight procedural results
