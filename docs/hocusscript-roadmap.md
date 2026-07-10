# HocusScript Delivery Roadmap

Status: active
Source contract: `docs/hocusscript-spec.md`

## 1. Outcome

Deliver a source-controlled `.hocus` authoring surface that compiles deterministically into HocusPocus network documents and immutable apply plans, while preserving Houdini fidelity, artist ownership, rollback safety, and production pipeline requirements.

This is an incremental extension of the document graph architecture, not a parallel mutation engine.

## 2. Delivery Principles

- Ship one vertical slice at a time.
- Keep the parser/compiler independent of `hou`.
- Do not expose source apply until document identity and verification are reliable.
- Default to merge and require ownership for reconcile.
- Preserve or reject unsupported constructs; never silently approximate them.
- Separate structural graph state from cooks, renders, exports, button presses, and publishing.
- Never infer a filesystem workspace from process CWD, the repository, `$HIP`, or user home; file-backed work uses an explicit user-selected project directory.
- Treat offline automated tests and live-Houdini tests as separate required gates.
- Mark code-only, live-validated, and production-validated states distinctly.

## 3. Phase Overview

| Phase | Name | Primary result |
| --- | --- | --- |
| HS0 | Contract and risk lock | Language, IR, safety, and production contracts agreed |
| HS1 | Offline language foundation | `.hocus` parses, validates, formats, and emits GraphSpec |
| HS1P | Project workspace and source I/O | Users select safe project roots; file compile has stable project-relative identity |
| HS2 | Catalog and semantic resolver | GraphSpec resolves against Houdini/HDA catalog snapshots |
| HS3 | Document lowering and preview | Source produces canonical document, diff, and deterministic preview plan |
| HS4 | Immutable plan and guarded apply | Compiled plans apply with revision, ownership, and policy checks |
| HS5 | Export, formatter, and editor loop | Live networks export to source; editor workflows become practical |
| HS6 | Modules and studio libraries | Typed reusable modules expand deterministically |
| HS7 | Network-family and value parity | SOP/MAT/LOP/TOP and complex values reach declared fidelity |
| HS8 | Production and AAA hardening | Deterministic asset fixtures, validation, review, CI, and publishing |

## 4. HS0: Contract and Risk Lock

Objectives:

- lock the TypeScript-shaped, non-executable language decision
- define source -> AST -> GraphSpec -> document -> plan boundaries
- define language/compiler/IR/catalog/plan/database versioning
- define diagnostics and source-map contracts
- define merge, reconcile, existing, adopt, ownership, and artist-override semantics
- define immutable compile/apply behavior and typed failures
- inventory existing document compiler blockers
- define production-quality and AAA acceptance boundaries

Exit criteria:

- specification, roadmap, and tracker agree on terminology and sequencing
- the initial grammar is implementable without unresolved syntax decisions
- persistent identity, port fidelity, sparse verification, code capability, live sync, and rollback appear as apply blockers
- source apply is explicitly forbidden before blocker closure

## 5. HS1: Offline Language Foundation

Objectives:

- create a standard-library-only `hocuspocus.hocusscript` package
- implement source positions, spans, diagnostics, lexer, parser, AST, structural validation, canonical GraphSpec serialization, and formatter
- support the complete `0.1` preview grammar
- reject executable TypeScript/JavaScript constructs
- enforce source, token, depth, node, code, and diagnostic limits
- add a `ProjectContext` contract with a user-configurable project root, relative source directories, opaque runtime IDs, stable manifest UIDs, and deterministic source URIs
- load named/default projects from configuration/environment while requests select an opaque `project_id`; raw runtime roots go through policy-gated `document.open_project`
- add canonical containment and symlink/junction escape checks without reading or writing project files yet
- add an offline command or import surface for agent/editor use

Supported syntax:

- `hocus 0.1;`
- one `graph`
- `target`, `category`, `mode`, `expect revision`, and `ownership`
- `existing`, `adopt`, and `node`
- indexed inputs with exact source output indexes
- string, number, boolean, null, array, and tagged-code values
- display/render/output selection and auto layout
- line and block comments

Testing:

- unit tests for every token and grammar production
- malformed-source recovery and span accuracy
- duplicate-symbol and unresolved-reference validation
- deterministic serialization and formatting goldens
- arbitrary-input smoke/fuzz budget tests

Exit criteria:

- the same valid source compiles to byte-identical normalized GraphSpec
- diagnostics contain stable codes and exact source spans
- no language package module imports `hou`
- unsupported language features fail explicitly
- inline compilation works without a project directory, while file-backed requests fail clearly when the directory is unset or unsafe
- project selection never falls back to CWD, `$HIP`, the repository, home, or another client's request-scoped selection
- no Houdini mutation is possible through this phase

## 5A. HS1P: Project Workspace and Source I/O

This is an early gate before catalog resolution or file-backed document lowering.

Objectives:

- add user-preference/config and environment support for named HocusScript projects and a configured default
- add a multi-project registry with `document.open_project`, `document.list_projects`, and `document.get_project`
- use opaque runtime project IDs plus stable manifest project UIDs; avoid a mutable process-global current project
- define and validate `hocus.project.toml` and `hocus.lock.json`
- implement canonical project/source URIs without absolute physical roots in portable provenance
- add a distinct project-source read capability and read-aware containment policy
- add `document.compile_file` for project-relative `.hocus` entry files
- allow `document.compile_source` to bind an unsaved buffer to `project_id` plus project-relative `source_path`
- enforce traversal, alternate-drive, UNC/device, case, symlink, and junction containment rules
- bind plans to project UID, source URI/digest, manifest/lock digests, catalog/compiler/module inputs, and policy

Testing:

- configuration/environment/default precedence and typed missing-project failures
- runtime registration policy and approved-root containment
- simultaneous projects and concurrent-client isolation
- nested/duplicate/conflicting roots and project UIDs
- project relocation with stable source/entity identity
- file-read denial, path traversal, symlink/junction escape, UNC/device, and case-normalization tests
- unsaved memory source versus project-bound buffer behavior

Exit criteria:

- a user can select one or more project directories without editing shipped package defaults
- file compile reads only contained `.hocus` files from an explicitly registered/selected project
- inline memory source remains non-file-backed and non-applyable unless bound to project-relative provenance
- no project selection broadens filesystem policy or leaks across clients
- moving a project root preserves stable project/source identity when manifest UID, relative paths, content, and locks are unchanged

## 6. HS2: Catalog and Semantic Resolver

Objectives:

- define a catalog provider protocol usable with fake, snapshot, and live providers
- generate fingerprinted catalog snapshots
- resolve categories, exact/versioned node types, HDAs, parameters, tuples, menus, ports, and code surfaces
- emit suggestions and fix-its for misspelled or ambiguous names
- compute a capability manifest
- support offline compilation against a pinned snapshot

Prerequisites:

- catalog schema and fingerprint algorithm
- versioned graph-store migrations rather than bootstrap-only `CREATE IF NOT EXISTS`
- approved-root policy for catalog and future module artifacts
- project-directory configuration, project manifest identity, and project-relative catalog/lock locations

Exit criteria:

- fake-catalog tests cover ambiguity, HDA versioning, menus, tuples, named/multi-output ports, and drift
- live snapshot fingerprints change for meaningful operator/HDA changes
- compiler never silently upgrades or guesses an ambiguous operator
- code surfaces add `run_code` to the capability manifest

## 7. HS3: Document Lowering and Preview

Objectives:

- lower resolved GraphSpec into the locked network-document IR
- overlay the full live baseline for merge semantics
- implement ownership metadata and durable source/entity mapping
- produce canonical document validation, diff, destructive summary, and deterministic ordered preview plan
- upgrade the existing structural `document.compile_source` preview to catalog-resolved document lowering and candidate-plan preview
- add `document.compile_file` for registered-project, project-relative `.hocus` files
- let `document.compile_source` optionally bind an unsaved buffer to `project_id` plus project-relative `source_path`
- add project list/get information for effective root, selection source, runtime ID, stable UID, source directories, manifest/lock state, and policy diagnostics
- return large artifacts through resource URIs when appropriate

Blocking document work:

- stamp and reimport persistent `hpmcp.uid` identities
- preserve exact source output index/name and destination input index/name
- align JSON Schema and runtime validation
- support sparse authored parameters without false verification differences
- define tuple/ramp/multiparm lowering or reject them with precise diagnostics
- prohibit ownership-blind reconcile deletion

Exit criteria:

- source compile never mutates live Houdini
- identical source, baseline, catalog, and versions produce identical document, diff, plan, and hash
- source spans map through every generated document entity and plan operation
- merge preserves unspecified live state
- reconcile affects only compiler-owned state
- compile produces no applyable plan while any blocking diagnostic exists
- file-backed previews bind stable project-relative source URIs and manifest/lock digests rather than machine-specific absolute paths

## 8. HS4: Immutable Plan and Guarded Apply

Objectives:

- persist immutable plans with TTL, plan hash, source digest, session, catalog, ownership, baseline revisions, capabilities, and ordered operations
- implement `document.apply_plan`
- acquire a network-scope write lease
- recheck plan/session/catalog/revisions/ownership/policy at apply time
- execute only reversible structural operations
- use idempotency keys and cancellation checkpoints
- verify intended effects and protected-state preservation
- implement inverse-plan or apply-owned rollback and crash recovery states

Exit criteria:

- apply never recompiles source
- tampered, expired, stale, wrong-session, or wrong-catalog plans fail before mutation
- failed apply returns a typed MCP failure, not `isError: false`
- rollback is reimported and verified
- partial or unknown state quarantines the scope
- code installation requires `run_code`
- live SOP tests cover success and failure after every execution stage

## 9. HS5: Export, Formatter, and Editor Loop

Objectives:

- expose canonical formatter and syntax/diagnostic JSON interfaces
- implement `document.export_source` for supported live networks
- let users choose an export path relative to the effective project directory and create directories only through explicit file-write operations
- add settings/UI support for selecting the session default project directory without changing request-scoped projects
- preserve durable IDs during export and recompile
- provide catalog-backed completion data
- add CLI/editor integration, with LSP as a later deliverable
- document the edit -> compile -> inspect diff -> apply -> cook -> capture -> revise loop after HS4 is available

Exit criteria:

- formatting is idempotent
- supported live networks export and recompile to semantically equivalent documents
- unsupported constructs are explicit and lossless or block export
- agents can use a `.hocus` file without manually authoring network-document JSON
- editor diagnostics point to exact source spans

## 10. HS6: Modules and Studio Libraries

Objectives:

- typed module parameters and exports
- hygienic deterministic expansion
- approved-root static imports
- resolve imports relative to the importing file and ordered project source/module directories
- transitive lockfiles and content hashes
- bounded compile-time conditionals and iteration only after limits are proven
- expansion source maps and inspectable expanded graphs
- reviewed studio module/HDA contracts and provenance

Exit criteria:

- builds pin complete transitive module and catalog inputs
- dynamic imports, implicit environment reads, network access, reflection, and unbounded expansion are impossible
- module upgrades are explicit and diff-visible
- the same project can be relocated without changing semantic IDs when its stable manifest UID, relative paths, content, and lockfiles are unchanged
- expanded graphs remain inspectable and editable

## 11. HS7: Network-Family and Value Parity

Sequence:

1. SOP and OBJ-contained SOP networks
2. material builders and VOP-like networks
3. LOP/Solaris and USD relationships/variants
4. TOP/PDG structural graphs
5. selected ROP, DOP, COP, and CHOP surfaces
6. HDA definition authoring only through a separate, stronger contract

Value and graph parity includes:

- named and multi-output ports
- tuples, menu tokens, units, raw paths, and resets
- ramps and multiparms
- expressions and structural channel references
- spare parameters
- keyframes and time samples
- code blobs and callbacks with differentiated policy
- network boxes, dots, sticky notes, comments, and layout constraints
- locked HDA and definition boundaries

Exit criteria:

- a published support matrix labels every feature supported, preserved-opaque, read-only, or rejected
- no network family claims parity without a live test matrix
- export/recompile equivalence exists for every supported construct

## 12. HS8: Production and AAA Hardening

Objectives:

- define enforceable asset contracts
- add deterministic clean-machine rebuilds and provenance manifests
- add geometry, topology, UV, material, LOD, collision, USD, dependency, and platform-budget validation
- integrate viewport captures, turntables, contact sheets, render comparison, and version review
- record cook timing, memory, polygon, texture, and publish metrics
- protect artist-owned overrides and resolve live/source conflicts
- integrate CI, packaging, and publishing

Reference fixtures:

- one procedural environment kit
- one hard-surface or rock asset family
- one destruction or simulation setup
- one USD assembly with variants

Exit criteria:

- at least one substantial asset rebuilds deterministically on a clean machine
- generated LOD, collision, UV, material, and publish outputs meet declared contracts
- visual and numeric regression reports are produced
- a human artist can edit protected regions without source apply erasing them
- pipeline provenance identifies source, compiler, catalog, modules, HDAs, inputs, and outputs

## 13. Cross-Cutting Workstreams

### Testing

- offline unit, golden, property, fuzz, and security suites
- fake backend and fake catalog
- live Houdini GUI and headless matrices
- save/reload and external-edit races
- performance and payload budgets
- project-directory precedence, unset/default/request-scoped selection, multi-client isolation, relocation, traversal, symlink/junction escape, and approved-root tests

### Compatibility

- source migration tooling
- old compiler fixtures
- GraphSpec/document/plan schema migration
- database migration ledger and upgrade fixtures
- legacy node/graph tools retained only as debug/compatibility surfaces

### Documentation

- language reference
- formatter and CLI guide
- catalog and module authoring guide
- source/apply safety model
- project-directory configuration, `hocus.project.toml`, `hocus.lock.json`, source layout, and file-backed compile/export guide
- production asset examples
- support matrix and known limitations

### Observability

- parse, resolve, lower, diff, plan, apply, verify, and rollback timings
- source-to-operation audit linkage
- plan lifecycle and idempotency state
- conflict and catalog-drift diagnostics

## 14. Release Gates

No phase is release-complete until all applicable gates pass:

1. Python syntax/build validation
2. Offline automated tests
3. Golden determinism fixtures
4. Security and hostile-input tests
5. Live Houdini tests for affected network families
6. Installed-package validation after restart
7. Documentation and support-matrix update
8. Dirty-worktree and committed/install-state reporting

Code implemented but awaiting live Houdini validation remains explicitly `implemented; live validation pending`.

## 15. Success Metrics

- median source-to-valid-preview latency under 250 ms for 100-node offline graphs
- deterministic hash agreement across repeated clean compiles
- zero ownership-blind deletions
- zero silent unsupported-feature drops
- exact source diagnostic locations for all compiler phases
- less than ten default-discovery tools needed for normal source authoring
- 1k-node compile under 2 seconds against a warm catalog target
- documented performance targets before 10k-node claims
- reproducible production fixture with numeric and visual reports
