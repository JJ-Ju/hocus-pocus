# HocusPocus Phase 4 Roadmap

Status: active roadmap

Branch: `codex/phase4`

Scope:

- move from scene automation into practical pipeline automation
- add asset, dependency, render, cache, and production workflow coverage
- keep the agent-facing surface high-signal and production-safe

This phase assumes the current baseline from phases 2 and 3:

- strong live scene automation
- graph index, query, diff, and patch planning
- PDG and Solaris first-pass coverage
- validation and event-feed primitives

## 1. Goals

Primary goals:

- make the server useful for real asset and shot workflows, not just node graph editing
- improve production-readiness around dependencies, caches, renders, and publish/export safety
- add deeper coverage for the Houdini patterns that matter most in teams and pipelines

Non-goals for this phase:

- HDK/native acceleration
- HAPI worker-plane implementation
- panel/chat UI work
- cloud/farm submission infrastructure beyond local graph/orchestration awareness

## 2. Priority Order

1. HDA and asset-definition workflows
2. File, cache, and dependency discovery
3. Render graph and lookdev helpers
4. Scene/package/archive workflows
5. Deeper Solaris production tools
6. Deeper PDG orchestration tools

## 3. Phases

## Phase 4A. HDA and Asset Workflows

Problem:

- Houdini automation without HDA coverage is incomplete for real production work

Deliver:

- inspect HDA definitions, instances, versions, sections, and parm interfaces
- create/update HDAs where supported
- promote parms and inspect/promote spare parms
- install/uninstall asset libraries and resolve active definitions

## Phase 4B. Dependency and Cache Discovery

Problem:

- agents still lack a first-class view of textures, caches, references, and external file dependencies

Deliver:

- discover scene dependencies across file parms, USD references, render outputs, and cache outputs
- identify missing files and non-approved paths
- repath dependencies and caches safely
- summarize cache topology and cache health

## Phase 4C. Render Graph and Lookdev Helpers

Problem:

- render workflows still depend on low-level node knowledge and manual validation

Deliver:

- render graph inspection and dependency traversal
- camera/light/lookdev helper tools
- render product and AOV inspection
- preflight validation before render/export

## Phase 4D. Scene Packaging and Archival

Problem:

- practical handoff workflows still require manual collection of scene files and dependencies

Deliver:

- collect scene dependencies into a package or archive
- dry-run package previews
- dependency reports suitable for publish and review

## Phase 4E. Solaris Production Workflows

Problem:

- Solaris authoring exists, but production inspection of layers, prims, and bindings is still shallow

Deliver:

- stage and layer-stack summaries
- prim queries and binding inspection
- reference and variant diagnostics
- safer layer/save-path validation and authoring helpers

## Phase 4F. PDG Production Orchestration

Problem:

- PDG support exists, but scheduler, retry, log, and result-management workflows are still thin

Deliver:

- scheduler inspection
- work-item log access
- retry/requeue controls where APIs allow
- stronger node-level and graph-level cook inspection

## 4. Recommended Sequence

1. HDA and asset workflows
2. dependency and cache discovery
3. render graph and lookdev helpers
4. scene packaging and archival
5. deeper Solaris production workflows
6. deeper PDG orchestration

## 5. Success Criteria

This phase is successful when:

- an agent can inspect and manage HDAs and asset libraries
- external dependencies and caches can be discovered, validated, and repathed through MCP
- renders can be preflighted with fewer failed output attempts
- scenes can be packaged for handoff with dependency visibility
- Solaris and PDG workflows feel production-capable rather than exploratory
