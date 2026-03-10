# HocusPocus Phase 3 Roadmap

Status: active roadmap

Branch: `codex/phase3`

Scope:

- make the live Houdini scene substantially more legible to agents
- reduce blind edit loops by adding graph-query and diff-first workflows
- expand into higher-value Houdini automation domains that benefit from richer scene understanding

This phase assumes the current `0.9.0` baseline plus completed phase-two work:

- richer MCP metadata
- material authoring
- exports
- improved task outcomes and recovery notes

## 1. Goals

Primary goals:

- let agents inspect the scene as a graph instead of only as isolated point reads
- add query tools that answer structural questions directly
- add diff and patch planning so edits can be previewed before mutation
- expand into PDG/TOPs and LOP/USD authoring where Houdini automation becomes materially more useful

Non-goals for this phase:

- external graph database deployment
- HDK/native acceleration work
- HAPI worker-plane work
- panel/chat UI work

## 2. Core Direction

The recommended implementation path is:

1. build a live in-memory indexed scene graph cache
2. expose query and snapshot resources on top of that cache
3. add diff and patch planning tools
4. expand into PDG and Solaris once the graph/query layer exists

Do not start with a persistent graph database.

Reason:

- the main value is queryability and structural visibility, not long-term storage
- a live cache tied to monitor revisions is much simpler to keep correct
- persistence can be added later if scene history, multi-session analysis, or scale makes it necessary

## 3. Priority Order

1. Scene graph index and query layer
2. Diff and patch workflows
3. Full-graph and dependency resources
4. PDG/TOPs support
5. LOP/USD authoring surface
6. Event subscriptions and richer validation

## 4. Phases

## Phase 3A. Live Scene Graph Index

Problem:

- agents can read nodes, parms, and geometry summaries, but they still have to reconstruct the scene graph manually

Deliver:

- an in-memory indexed scene graph cache keyed by Houdini path and revision
- node, parm, material, and connection indexes
- display/render/output-node relationships
- invalidation and refresh behavior tied to scene-monitor events

## Phase 3B. Query Tools and Graph Views

Problem:

- agents need direct answers such as “what is downstream of this node?” or “find all geometry nodes with a display SOP”

Deliver:

- `graph.query`
- `graph.find_nodes`
- `graph.find_upstream`
- `graph.find_downstream`
- `graph.find_by_type`
- `graph.find_by_flag`

## Phase 3C. Diff and Patch Planning

Problem:

- current workflows still mutate first and inspect after
- there is no native way to compare intended graph changes with current state

Deliver:

- `scene.diff`
- `graph.diff_subgraph`
- `graph.plan_edit`
- `graph.apply_patch`
- diff payloads that explain created, removed, rewired, and changed entities

## Phase 3D. Graph Resources and Snapshots

Problem:

- dynamic reads exist, but there is no whole-scene or whole-subgraph resource for agent context building

Deliver:

- graph snapshot resources
- dependency-edge resources
- expression/reference resources
- material-assignment resources
- render and export topology resources

## Phase 3E. PDG/TOPs Automation

Problem:

- Houdini automation is still missing one of the most valuable production orchestration surfaces

Deliver:

- `pdg.list_graphs`
- `pdg.cook`
- `pdg.get_workitems`
- `pdg.cancel`
- `pdg.get_results`

## Phase 3F. LOP/USD Authoring

Problem:

- USD export exists, but USD authoring is still too thin for real Solaris workflows

Deliver:

- `lop.create_node`
- `usd.assign_material`
- `usd.set_variant`
- `usd.add_reference`
- `usd.create_layer_break`

## Phase 3G. Event Streaming and Validation

Problem:

- clients still rely mostly on polling
- there are few tools that answer “is this graph healthy?” before edits or renders

Deliver:

- event/subscription support where the transport permits it
- `scene.validate`
- `graph.check_errors`
- `parm.find_broken_refs`
- stronger validation summaries for renders, exports, and USD graphs

## 5. Recommended Sequence

1. Live scene graph index
2. Query tools and graph views
3. Graph resources and snapshots
4. Diff and patch planning
5. PDG/TOPs support
6. LOP/USD authoring
7. Event streaming and validation

Note:

- steps 3 and 4 may overlap in implementation because both depend on the graph index
- PDG and LOP work should reuse the same graph-model patterns instead of inventing separate ad hoc representations

## 6. Success Criteria

This phase is successful when:

- an agent can reason about a scene from one or two graph reads instead of dozens of low-level calls
- structural questions can be answered through dedicated graph tools
- planned edits can be diffed before they are applied
- PDG and Solaris workflows become first-class automation targets
- validation and event feedback reduce failed edit/render/export loops
