# HocusScript Engineering Task Tracker

Status: active implementation
Specification: `docs/hocusscript-spec.md`
Roadmap: `docs/hocusscript-roadmap.md`

## 1. Tracking Rules

- A task is checked only when its named artifact exists and its acceptance command or manual procedure has passed.
- `implemented`, `offline validated`, `live validated`, and `production validated` are distinct states.
- Live-Houdini work is never marked complete from static compilation alone.
- Every milestone records dependencies, artifacts, acceptance evidence, and whether Houdini is required.
- Contract changes update the specification before or with implementation.
- Existing user changes in the dirty worktree are preserved.

## 2. Current Slice

Current milestone: HS1 offline language foundation
Current scope: preview-only parser/compiler frontend
Live mutation: prohibited

Initial implementation acceptance command:

```powershell
python -m unittest discover -s tests -p "test_hocusscript*.py"
```

Static validation command:

```powershell
python -m compileall python3.11libs\hocuspocus
```

## 3. HS0: Contract and Risk Lock

Status: completed and cross-reviewed

Dependencies: none
Houdini required: no

### Contract artifacts

- [x] Create the HocusScript language and compiler specification.
- [x] Create the phased delivery roadmap.
- [x] Create this task tracker.
- [x] Lock TypeScript-shaped syntax without TypeScript/JavaScript execution.
- [x] Separate source, AST, GraphSpec, network document, and apply-plan contracts.
- [x] Define source-span and structured-diagnostic requirements.
- [x] Define deterministic compilation inputs and version boundaries.
- [x] Define preview-only initial implementation scope.

### Safety and production decisions

- [x] Default source authoring to merge.
- [x] Require ownership for reconcile.
- [x] Define `existing` versus `adopt` semantics.
- [x] Separate structural graph apply from cooks, renders, exports, and publishing.
- [x] Require `run_code` for code installation.
- [x] Define immutable compile/apply separation.
- [x] Define rollback verification and partial-state quarantine requirements.
- [x] Define the AAA production asset and visual-review requirements.

### Existing blockers recorded

- [x] Record persistent UID stamping as an apply blocker.
- [x] Record exact source output and named-port fidelity as an apply blocker.
- [x] Record sparse authored-parameter verification as an apply blocker.
- [x] Record ramp/multiparm schema-runtime drift as an apply blocker.
- [x] Record ownership-blind reconcile deletion as an apply blocker.
- [x] Record node-level live-sync coverage as an apply blocker.
- [x] Record typed apply failure and code-capability enforcement as blockers.
- [x] Record real database migrations as distinct from schema bootstrap.

HS0 exit evidence:

- artifacts: `docs/hocusscript-spec.md`, `docs/hocusscript-roadmap.md`, `docs/hocusscript-task-tracker.md`
- acceptance: cross-document audit with no unresolved P0 omission

## 4. HS1: Offline Language Foundation

Status: in progress

Dependencies: HS0 grammar and diagnostics contract
Houdini required: no

### Package and model

- [x] Add `python3.11libs/hocuspocus/hocusscript/` package.
- [x] Add one-based source positions and zero-based offsets.
- [x] Add source spans to implemented graph entities, references, assignments, and values.
- [x] Add stable structured diagnostic codes and deterministic sorting.
- [x] Add serializable GraphSpec model.
- [x] Add machine-readable GraphSpec v0.1 schema and MCP schema resource.
- [x] Ensure the package never imports `hou`.
- [ ] Split the parser-owned syntax AST from normalized GraphSpec before semantic resolution.
- [ ] Retain individual spans for version, target, category, mode, revision, ownership, and flag/layout statements.
- [ ] Retain embedded code body-start and escape-aware offset maps.

### Lexer

- [x] Lex identifiers, keywords, punctuation, strings, numbers, and raw code templates.
- [x] Support `//` and non-nested `/* ... */` comments.
- [x] Track exact line, column, and offset spans.
- [x] Reject unterminated comments, strings, and code templates with typed diagnostics.
- [x] Enforce source, token, and literal-size limits.
- [x] Enforce value-nesting depth.
- [x] Enforce diagnostic count and emit a truncation diagnostic.
- [ ] Add parser recovery for multiple independent syntax errors.

### Parser

- [x] Parse optional preview and canonical `hocus 0.1;` headers.
- [x] Parse exactly one graph declaration.
- [x] Parse target, category, mode, expected revision, and ownership.
- [x] Parse existing and adopt declarations.
- [x] Parse node declarations, parameter assignments, and indexed inputs.
- [x] Parse source output indexes without collapsing them.
- [x] Parse scalar, null, array, and tagged-code values.
- [x] Parse display, render, output, and auto-layout directives.
- [x] Require semicolons after simple statements.
- [x] Reject executable TypeScript/JavaScript constructs explicitly.

### Structural compiler

- [x] Require an absolute target path.
- [x] Validate mode and nonnegative expected revision.
- [x] Detect duplicate symbols, parameters, and input indexes.
- [x] Resolve symbolic references within the graph.
- [x] Require ownership for reconcile.
- [x] Validate display/render/output symbols.
- [x] Validate supported embedded-code languages without executing code.
- [x] Serialize GraphSpec deterministically.
- [x] Compute a deterministic source digest.
- [x] Declare compiler and GraphSpec versions in preview output.
- [x] Reject non-finite and oversized numeric literals with diagnostics.
- [x] Reject noncanonical and traversal-containing Houdini paths.
- [x] Forbid display/render/output mutation through read-only `existing` symbols.

### Formatter and developer surface

- [x] Add canonical formatter.
- [x] Make formatting idempotent.
- [x] Preserve tagged code body semantics.
- [x] Add a pure Python `compile_source()` API.
- [x] Register preview-only `document.compile_source` with explicit structural-stage and non-apply readiness fields.
- [x] Add native `check`, `format`, and `compile` commands with explicit project selection.

### Offline tests

- [x] Add `tests/test_hocusscript_lexer.py`.
- [x] Add `tests/test_hocusscript_parser.py`.
- [x] Add `tests/test_hocusscript_compiler.py`.
- [x] Add `tests/test_hocusscript_operations.py`.
- [ ] Cover every `0.1` grammar production.
- [x] Cover comments, escapes, negative/exponent numbers, arrays, and tagged code.
- [x] Assert exact source spans.
- [x] Assert duplicate and missing-reference diagnostics.
- [x] Assert deterministic GraphSpec and source hashes.
- [x] Assert hostile text does not import or execute host code.
- [ ] Add golden source -> GraphSpec fixtures.

HS1 exit evidence:

- latest full acceptance command: 48 tests passed on 2026-07-11
- repeated compiles produce byte-identical normalized GraphSpec
- static search confirms no `hou` import in the language package
- no MCP or local path can mutate Houdini through the HS1 code

HS1 remains in progress until the unchecked parser-recovery, statement-span, code-offset, complete-coverage, and golden-fixture tasks pass.

## 4A. HS1P: Native Project Compiler and Bundles

Status: in progress

Dependencies: HS1 path/source identity contract
Houdini required: no

- [x] Add offline `ProjectContext` with stable manifest UID, canonical root, relative source/module directories, and project-relative source URIs.
- [x] Let native CLI/editor configuration select the project directory explicitly; keep it out of Houdini MCP settings and registries.
- [x] Add `compile_path()` with bounded UTF-8 reads and canonical project containment.
- [x] Add native `check`, `format`, and `compile` CLI commands.
- [ ] Define and validate `hocus.project.toml` and `hocus.lock.json` schemas.
- [x] Add stable `hocus-project://`, preview-only `hocus-workspace://`, and `hocus-memory://` URI generation.
- [ ] Add canonical containment with traversal, case, alternate-drive, UNC/device, symlink, and junction checks.
- [x] Add canonical compiled-bundle model and deterministic JSON/digest serialization.
- [x] Include GraphSpec, embedded source-map contract, source/dependency digests, compiler/language/schema versions, manifest/lock/catalog constraint fields, and graph-derived capability requirements.
- [x] Keep `document.compile_source` as an unsaved-buffer convenience endpoint with no path-reading behavior.
- [x] Add strict external compiled-bundle decoding, validation, and content-boundary tests without filesystem access.
- [x] Ensure physical project roots do not participate in portable compiled-bundle provenance and identity.
- [x] Define the complete portable bundle provenance input fields: project/source/manifest/lock/compiler/catalog/module digests.
- [ ] Add unit and cross-platform project relocation, traversal, conflicting UID, invalid UTF-8, oversized source, deterministic bundle, and missing/stale lock tests.

## 5. HS2: Catalog and Semantic Resolver

Status: pending

Dependencies: HS1, versioned catalog schema
Houdini required: fake provider no; live provider yes

- [ ] Add real graph-store schema versioning and migration fixtures.
- [ ] Define catalog-provider protocol.
- [ ] Add fake and snapshot catalog providers.
- [ ] Add live Houdini catalog provider.
- [ ] Record Houdini build, platform, categories, operators, HDAs, packages, and Labs data.
- [ ] Record parm tokens, tuples, defaults, ranges, menus, tags, and code surfaces.
- [ ] Record indexed/named input and output connectors.
- [ ] Add canonical catalog fingerprint.
- [ ] Resolve exact and fully qualified operator definitions.
- [ ] Reject ambiguity and silent upgrades.
- [ ] Add spelling suggestions and source fix-its.
- [ ] Resolve scalar/tuple/menu/code parameter semantics.
- [ ] Compute required capabilities, including `run_code`.
- [ ] Add fake-catalog ambiguity, drift, HDA, tuple, menu, and port tests.
- [ ] Add live catalog fingerprint smoke procedure.

## 6. HS3: Document Lowering and Preview

Status: blocked by document fidelity prerequisites

Dependencies: HS2 and DG corrective work
Houdini required: yes for live baseline tests

### Required document corrections

- [ ] Stamp created/adopted nodes with persistent `hpmcp.uid`.
- [ ] Prefer persistent UID during import and detect duplicate copied UIDs.
- [ ] Preserve exact source output index/name in import, plan, execute, and verify.
- [ ] Preserve exact destination input index/name and variadic ordering.
- [ ] Align runtime validation with the published JSON Schema.
- [ ] Define and implement sparse authored-parameter verification.
- [ ] Implement or explicitly reject tuple/ramp/multiparm lowering.
- [ ] Make reconcile ownership-aware before any source-driven delete.
- [ ] Add node-level live edit tracking and scope coalescing.

### Lowering and MCP preview

- [ ] Lower resolved GraphSpec into canonical network-document v1.
- [ ] Overlay complete baseline state for merge.
- [ ] Generate deterministic UIDs and ownership/source metadata.
- [ ] Carry source maps into nodes, bindings, edges, code blobs, and plan operations.
- [ ] Produce document validation, diff, destructive summary, and preview plan.
- [ ] Add `document.preview_bundle` for resolved document and candidate-plan preview; keep `document.compile_source` structural-only.
- [ ] Bind bundle previews to stable project-relative source URIs and manifest/lock/source/dependency digests.
- [ ] Add explicit input and output JSON Schemas.
- [ ] Keep large artifacts in resources with stable URIs.
- [ ] Verify compile never mutates Houdini.
- [ ] Add fake-baseline and live SOP preview tests.

## 7. HS4: Immutable Plan and Guarded Apply

Status: pending

Dependencies: HS3 live validation
Houdini required: yes

- [ ] Add apply-plan schema and version.
- [ ] Persist immutable plans with TTL and hash.
- [ ] Bind plans to source, compiler, catalog, session, ownership, and baseline revisions.
- [ ] Add plan resource and discard operation.
- [ ] Implement network-scope write leases.
- [ ] Implement `document.apply_plan` without recompilation.
- [ ] Recheck plan hash, catalog, revisions, ownership, policy, and capabilities.
- [ ] Require `run_code` for code changes.
- [ ] Add idempotency keys and cancellation checkpoints.
- [ ] Exclude irreversible actions from structural apply.
- [ ] Generate/store inverse plans and pre-apply scoped snapshots.
- [ ] Verify apply and rollback outcomes.
- [ ] Add pending/committed/aborted/quarantined commit states.
- [ ] Return true typed failures for unsuccessful apply.
- [ ] Test stale, expired, tampered, wrong-session, and wrong-catalog plans.
- [ ] Test failure and rollback after every apply stage.

## 8. HS5: Export and Editor Workflow

Status: pending

Dependencies: HS4 for the full edit/apply/review loop; parse/format/export work may begin after HS3
Houdini required: yes for export

- [ ] Add `document.format_source`.
- [ ] Add `document.export_source`.
- [ ] Return export source text and provenance without writing a project file from MCP.
- [ ] Complete the native export/recompile round trip with no-overwrite and expected-digest replacement safeguards.
- [ ] Export durable IDs and ownership metadata.
- [ ] Define opaque-preserve versus rejection rules for unsupported constructs.
- [ ] Add semantic export/recompile golden and live tests.
- [ ] Add catalog-backed completion endpoint.
- [x] Add local structural check/format/compile CLI workflow.
- [ ] Add syntax highlighting/editor grammar.
- [ ] Add LSP only after diagnostic and completion contracts stabilize.
- [ ] Update manual and agent workflows to prefer `.hocus` source.

## 9. HS6: Modules and Studio Libraries

Status: pending

Dependencies: HS5, import security design
Houdini required: module compiler no; live module fixtures yes

- [ ] Define typed module parameters and exports.
- [ ] Implement hygienic deterministic expansion.
- [ ] Implement offline project-contained static imports.
- [ ] Resolve imports relative to the importing file and ordered project source/module directories.
- [ ] Add project identity, source-directory, module-root, catalog-lock, and module-lock fields to `hocus.project.toml`, with canonical lock state in `hocus.lock.json`.
- [ ] Require manifest-declared, separately approved and locked aliases for cross-project imports.
- [ ] Add explicit lock verify/update modes; make lock writes atomic, diff-visible, and capability-gated.
- [ ] Add module manifests, versions, content hashes, and lockfile.
- [ ] Preserve expansion stacks in source maps and diagnostics.
- [ ] Enforce module depth, node count, code size, and recursion limits.
- [ ] Reject dynamic imports and implicit host/environment access.
- [ ] Add bounded conditionals/iteration only with deterministic semantics.
- [ ] Expose expanded graphs before apply.
- [ ] Add reviewed studio-module contract and provenance tests.

## 10. HS7: Fidelity Matrix

Status: pending

Dependencies: HS4
Houdini required: yes

- [ ] Publish supported/read-only/opaque/rejected feature matrix.
- [ ] Complete SOP and OBJ-contained SOP coverage.
- [ ] Add material builder and VOP coverage.
- [ ] Add LOP/Solaris and USD relationship/variant coverage.
- [ ] Add TOP/PDG structural coverage.
- [ ] Evaluate selected ROP, DOP, COP, and CHOP surfaces.
- [ ] Keep HDA definition editing under a stronger separate contract.
- [ ] Support tuples, menus, units, raw paths, and resets.
- [ ] Support ramps and multiparms.
- [ ] Support expressions and structural channel references.
- [ ] Support spare parameters, keyframes, and time samples.
- [ ] Support network boxes, dots, sticky notes, comments, and layout constraints.
- [ ] Add locked-HDA and cross-family live matrices.

## 11. HS8: Production and AAA Validation

Status: pending

Dependencies: HS6 and relevant HS7 coverage
Houdini required: yes

- [ ] Define asset-contract schema.
- [ ] Validate units, axes, naming, pivots, bounds, and dependencies.
- [ ] Validate topology, manifold state, normals, and tangents.
- [ ] Validate UV sets, UDIMs, texel density, and material slots.
- [ ] Validate LODs, collision, instancing/packing, and platform budgets.
- [ ] Validate USD kind, purpose, variants, and publish structure.
- [ ] Record source/module/HDA/input/output provenance.
- [ ] Add deterministic clean-machine rebuild test.
- [ ] Add viewport, turntable, contact-sheet, and render comparison loop.
- [ ] Record cook timing, memory, polygon, and texture metrics.
- [ ] Protect artist overrides and test source/live conflicts.
- [ ] Build procedural environment fixture.
- [ ] Build hard-surface or rock-family fixture.
- [ ] Build destruction/simulation fixture.
- [ ] Build USD variant assembly fixture.
- [ ] Integrate CI and publishing gates.

## 12. Release and Regression Work

- [x] Add offline tests to `docs/release-validation.md`.
- [ ] Fix the current live-smoke discovery expectations after legacy tool hiding.
- [ ] Add parser/compiler performance budgets.
- [ ] Add 1k-node and 10k-node fixtures.
- [ ] Add hostile-source and import-security tests.
- [ ] Add explicit project selection, relocation, traversal, case, alternate-drive, UNC/device, symlink/junction, bundle portability, and offline/MCP boundary tests.
- [ ] Add previous-language/compiler-version golden fixtures.
- [ ] Add graph-store upgrade/downgrade fixtures.
- [ ] Report committed, installed, and running-module alignment for each live validation.

## 13. Open Decisions

- [ ] Decide the final explicit-ID syntax before language `0.2`.
- [ ] Decide canonical tuple and unit syntax.
- [ ] Decide record/object literal syntax.
- [ ] Decide channel-reference and expression syntax.
- [ ] Decide module package URI and lockfile formats.
- [x] Keep project-directory selection in native compiler/editor configuration; do not expose an MCP project registry.
- [ ] Decide syntax for explicit per-field `preserve_live` and `source_wins` annotations; the default reject-on-conflict policy is locked.
- [ ] Decide quoted/reserved parameter-token syntax such as `parm["input"]`.
- [ ] Decide confirmation thresholds for destructive plans.
- [ ] Decide which graph-editor-only artifacts are source-managed.

## 14. Cross-Review Record

Review date: 2026-07-09
Review result: no unrecorded P0 architecture omission found; implementation remains deliberately preview-only

The specification, roadmap, tracker, and initial slice were checked together for:

- [x] source -> AST -> GraphSpec -> document -> immutable-plan boundaries
- [x] source spans, source maps, stable diagnostics, and future expansion stacks
- [x] deterministic formatting, hashes, versions, catalogs, modules, inputs, and seeds
- [x] merge, ownership-safe reconcile, existing/adopt, artist protection, and conflict policy
- [x] persistent identity and exact input/output port requirements
- [x] tuple, ramp, multiparm, expression, channel, spare-parm, animation, and code fidelity
- [x] catalog snapshots, HDA/operator pinning, ambiguity, and drift
- [x] code capability, limits, import roots, secrets, and typed error behavior
- [x] immutable apply, scope leases, idempotency, rollback, crash recovery, and quarantine
- [x] node-level live sync and scoped reimport requirements
- [x] language, compiler, IR, plan, module, catalog, and database migrations
- [x] offline unit/golden/fuzz/security and live network-family test matrices
- [x] formatter, export, editor, module, and studio-library workflows
- [x] AAA asset contracts, deterministic builds, visual review, metrics, provenance, and publishing
- [x] current implementation limitations and gates before source-driven mutation
