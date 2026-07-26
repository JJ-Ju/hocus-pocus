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
- Active development uses one relevant behavior smoke plus the correctness linter. Full-suite and adversarial qualification belong to H4, stabilized integration checkpoints, or release validation.
- The tests are `unittest`-native. Do not run the same suite again under pytest unless pytest compatibility itself is under test.
- The entire repository is capped at 50 tests. Tests must exercise public behavior or a complete user workflow; implementation helpers, schema field matrices, duplicated runner coverage, and assertion-count inflation are not accepted.
- Source, script, config, documentation, and fixture files are capped at 1,200 physical lines.
- Ruff enforces cyclomatic complexity 12, branches 15, returns 12, arguments 12, and statements 100 per function. No existing file is grandfathered and complexity suppressions do not count as compliance.

## 2. Current Slice

Current milestone: HS6 modules and studio libraries in progress; Batches A-G5 and H0-H2 are complete, with H3 native language-`0.3` integration next
Current scope: language `0.2` is frozen; language `0.3` has its exact frontend, strict v4/v2/`0.4` carriers, and isolated pure whole-body validator/selected expander. H3-H4 native integration and adversarial/full qualification remain pending; every project resolver/writer, compiler dispatcher, CLI/editor, document/live consumer stays disabled for `0.3`, and MCP remains content-only with no `.hocus` file/project/root surface
Live mutation: available only through the completed HS4 guarded `document.apply_plan` path; HS5 format/completion/export tools are observational
Current test catalogue: 34 public workflow scenarios in four files; lint enforces the repository-wide ceiling of 50
Current structural gate: every checked file is at or below 1,200 lines and every Python function passes the configured complexity limits

Active-development lint command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\lint.ps1
```

Run the narrowest relevant behavior smoke, for example:

```powershell
python .\tests\test_hocusscript_control_scenarios.py -q
```

Do not run broad discovery after every implementation edit. The full `unittest` discovery and compile/build gates in `docs/release-validation.md` are qualification gates for H4, stabilized integration checkpoints, and releases.

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

Status: complete

Dependencies: HS0 grammar and diagnostics contract
Houdini required: no

### Package and model

- [x] Add `python3.11libs/hocuspocus/hocusscript/` package.
- [x] Add one-based source positions and zero-based offsets.
- [x] Add source spans to implemented graph entities, references, assignments, and values.
- [x] Add stable structured diagnostic codes and deterministic sorting.
- [x] Add serializable GraphSpec model.
- [x] Retain decode-only GraphSpec v0.1 and publish current GraphSpec v0.2 schemas and MCP resources with an explicit compiler/version compatibility matrix.
- [x] Ensure the package never imports `hou`.
- [x] Split the parser-owned syntax AST from normalized GraphSpec before semantic resolution.
- [x] Retain and serialize individual spans for version, target, category, mode, revision, ownership, and flag/layout statements.
- [x] Retain and serialize embedded code body spans and compact escape-aware offset maps.

### Lexer

- [x] Lex identifiers, keywords, punctuation, strings, numbers, and raw code templates.
- [x] Support `//` and non-nested `/* ... */` comments.
- [x] Track exact line, column, and offset spans.
- [x] Reject unterminated comments, strings, and code templates with typed diagnostics.
- [x] Enforce source, token, and literal-size limits.
- [x] Enforce value-nesting depth.
- [x] Enforce diagnostic count and emit a truncation diagnostic.
- [x] Add scope-aware parser recovery for multiple independent syntax errors.

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

### Offline scenarios

- [x] Keep representative compile, format, diagnostic, module, editor, export, and artifact workflows in `tests/test_hocusscript_authoring_scenarios.py`.
- [x] Keep preview, guarded apply, typed-control validation, expansion, budget, and cancellation workflows in `tests/test_hocusscript_control_scenarios.py`.
- [x] Keep project, dependency, lock, relocation, and CLI workflows in `tests/test_hocusscript_project_scenarios.py`.
- [x] Keep document, graph-store, live-catalog, and event-monitor workflows in `tests/test_runtime_scenarios.py`.
- [x] Enforce the repository-wide 50-test ceiling from `scripts/lint.ps1`.

HS1 exit evidence:

- the consolidated authoring scenarios pass as one public-workflow suite
- repeated compiles produce byte-identical normalized GraphSpec
- static search confirms no `hou` import in the language package
- no MCP or local path can mutate Houdini through the HS1 code

HS1 exit evidence is complete for the offline `0.1` language foundation. Later semantic catalog, document, and live-Houdini behavior remains gated by HS2+.

## 4A. HS1P: Native Project Compiler and Bundles

Status: in progress

Dependencies: HS1 path/source identity contract
Houdini required: no

- [x] Add offline `ProjectContext` with stable manifest UID, canonical root, relative source directories, and project-relative source URIs.
- [x] Let native CLI/editor configuration select the project directory explicitly; keep it out of Houdini MCP settings and registries.
- [x] Add `compile_path()` with bounded UTF-8 reads and canonical project containment.
- [x] Add native `check`, `format`, and `compile` CLI commands.
- [x] Define and validate strict structural `hocus.project.toml` and `hocus.lock.json` v1 schemas.
- [x] Add stable `hocus-project://`, preview-only `hocus-workspace://`, and `hocus-memory://` URI generation.
- [ ] Eliminate path check/open TOCTOU with descriptor/handle-based reads; retain traversal, case, alternate-drive, UNC/device, symlink, and junction regression coverage.
- [x] Add canonical compiled-bundle model and deterministic JSON/digest serialization.
- [x] Include GraphSpec, embedded source-map contract, source/dependency digests, compiler/language/schema versions, manifest/lock/catalog constraint fields, and graph-derived capability requirements.
- [x] Keep `document.compile_source` as an unsaved-buffer convenience endpoint with no path-reading behavior.
- [x] Add strict external compiled-bundle decoding, validation, and content-boundary tests without filesystem access.
- [x] Ensure physical project roots do not participate in portable compiled-bundle provenance and identity.
- [x] Define the complete portable bundle provenance input fields: project/source/manifest/lock/compiler/catalog/module digests.
- [x] Add unit tests for project relocation, traversal, same-UID divergent provenance, invalid UTF-8, oversized source, deterministic bundle, and missing/stale locks.

## 5. HS2: Catalog and Semantic Resolver

Status: complete for the v1 catalog and HocusScript 0.1 semantic surface; named/typed live connector enrichment remains tracked as HS-BLOCK-002

Dependencies: HS1, versioned catalog schema
Houdini required: fake provider no; live provider yes

- [x] Add real graph-store schema versioning and migration fixtures.
- [x] Define catalog-provider protocol.
- [x] Add fake and snapshot catalog providers.
- [x] Add live Houdini catalog provider.
- [x] Record Houdini build, platform, categories, operators, HDAs, packages, and Labs data.
- [x] Record parm tokens, tuples, defaults, ranges, menus, tags, and code surfaces.
- [x] Record indexed/named input and output connectors, retaining null optional names/types when HOM does not expose them without instantiation.
- [x] Add canonical catalog fingerprint.
- [x] Resolve exact and fully qualified operator definitions.
- [x] Reject ambiguity and silent upgrades.
- [x] Add spelling suggestions and source fix-its.
- [x] Resolve scalar/tuple/menu/code parameter semantics.
- [x] Compute required capabilities, including `run_code`.
- [x] Add fake-catalog ambiguity, drift, HDA, tuple, menu, and port tests.
- [x] Add live catalog fingerprint smoke procedure.

HS2 exit evidence (2026-07-11):

- consolidated scenarios retain catalog, semantic, bundle, project-lock, migration, and live-provider workflows
- real Houdini: 21.0.729 on `windows-x86_64-cl19.42`
- unchanged full captures: 5,156 operators and byte-identical fingerprint `sha256:534a71cee3aa2bb35aeb804a62f4831f97a6433683ed7fc8fcaeea5780f6ca4d`
- meaningful live change: temporary `hocus::catalog_smoke::1.0` HDA with `smoke_scale` increased the catalog to 5,157 operators and changed the fingerprint to `sha256:c82d7f417f2a40a76349d25e7c6b1ce562364b5e8791245f66d64fce65ebfc05`
- live output remained project-contained through manifest v2 `catalog.path`; generated 44 MB smoke snapshots were not committed
- unsupported executable surfaces such as OpenCL remain cataloged as `code/unsupported` and cannot be silently authored by HocusScript 0.1
- procedure: `docs/hocusscript-live-catalog-smoke.md`

## 6. HS3: Document Lowering and Preview

Status: complete for SOP/network-document v1; guarded immutable SOP apply is complete in HS4 and broader family/value parity remains HS7

Dependencies: HS2 and DG corrective work
Houdini required: yes for live baseline tests

### Required document corrections

- [x] Stamp created/adopted nodes with persistent `hpmcp.uid` and ownership/source/compiler metadata only on explicit mutation paths; keep import/preview read-only.
- [x] Prefer persistent UID during import and detect duplicate copied UIDs.
- [x] Preserve exact source output index/name in import, plan, execute, and verify.
- [x] Preserve exact destination input index/name and variadic ordering; keep sparse unordered-input compaction policy in HS-BLOCK-004.
- [x] Align runtime validation with the published JSON Schema, including conditional binding payloads and data-edge indexes.
- [x] Define and implement sparse authored-parameter verification.
- [x] Support scalar component lowering and explicitly reject whole tuples (`HOCUS708`), ramps, and multiparms until HS-BLOCK-005 is resolved.
- [x] Make reconcile ownership-aware before any source-driven delete.
- [x] Add node-level live edit tracking and scope coalescing.

### Lowering and MCP preview

- [x] Lower resolved GraphSpec into canonical network-document v1.
- [x] Overlay complete baseline state for merge.
- [x] Generate deterministic UIDs and ownership/source metadata.
- [x] Carry source maps into nodes, bindings, edges, code blobs, and plan operations.
- [x] Produce document validation, diff, destructive summary, and preview plan.
- [x] Add `document.preview_bundle` for resolved document and candidate-plan preview; keep `document.compile_source` structural-only.
- [x] Bind bundle previews to stable project-relative source URIs and manifest/lock/source/dependency digests.
- [x] Add explicit input and output JSON Schemas and MCP schema resources.
- [x] Keep large artifacts in bounded content-addressed resources with stable URIs.
- [x] Verify compile/preview never mutates Houdini.
- [x] Add fake-baseline and live SOP preview tests.

HS3 exit evidence (2026-07-11):

- consolidated scenarios retain document preview and schema-boundary behavior; the pure HocusScript package remains `hou`-free
- strict trust boundary: live GraphSpec re-resolution must exactly match bundled semantic selections; adversarial rehashed selection tests block with `HOCUS722`
- deterministic round trip: canonical node/binding/code/edge/port identities avoid duplicate bindings and destination edges after live reimport
- H21.0.729 live preview: actual live importer, integrity-checked persistent provenance, an imported SOP connection/ports, and a deferred adopted external resolved against full live catalog `sha256:b6743cfd1bfe24ce708deab89277eb7d4006669ea8294ba6d97cfc973b78ebca`; deterministic candidate plan `sha256:419f16f4ca47ff35826e1409e3111cca3d1f3536e8c549859eec70d40279b428`, eight operations, and verified `houdiniMutation=false`
- H21.0.729 live monitor: 12 observed nodes, seven node events coalesced to the disposable SOP network scope
- reproducible commands: `scripts/smoke_hocusscript_preview.py` and `scripts/smoke_scene_event_monitor.py`

## 7. HS4: Immutable Plan and Guarded Apply

Status: complete for the guarded SOP/network-document v1 slice; broader family/value parity remains HS7

Dependencies: HS3 live validation
Houdini required: yes

- [x] Add apply-plan schema and version.
- [x] Persist immutable plans with TTL and hash.
- [x] Bind plans to source, compiler, catalog, session, ownership, and baseline revisions.
- [x] Add plan resource and durably revoking discard operation.
- [x] Implement overlapping parent/child network-scope write leases.
- [x] Implement `document.apply_plan` without source recompilation.
- [x] Recheck plan hash, catalog, revisions/digest, ownership-normalized operations, policy, and capabilities.
- [x] Require `run_code` for code changes.
- [x] Add idempotency keys and cancellation checkpoints.
- [x] Exclude unknown, unsupported-family, opaque-container, and irreversible actions from structural apply.
- [x] Generate/store inverse plans and pre-apply scoped snapshots.
- [x] Verify apply and rollback outcomes against reimported network documents.
- [x] Add pending/committed/aborted/partial-or-unknown lifecycle states and overlapping-scope quarantine.
- [x] Return true typed failures for unsuccessful apply.
- [x] Test stale, expired, tampered, wrong-session, wrong-policy/capability, and wrong-catalog plans.
- [x] Test rollback after all nine executor checkpoints and after pending, execute, verify, and pre-commit lifecycle stages.

HS4 exit evidence (2026-07-11):

- the guarded-plan scenario retains tamper rejection, idempotency, and rollback at the public plan/apply boundary
- H21.0.729 live guarded apply: catalog `sha256:b6743cfd1bfe24ce708deab89277eb7d4006669ea8294ba6d97cfc973b78ebca`; nine executor checkpoints and four lifecycle-stage failures each restored the exact pre-apply SOP document; final plan `sha256:2f7c7212896a7c62c2bb7037fe11ffb8c2b2c41ddeedf65b1c01842aede7e5f6` applied, reimported, verified, and replayed idempotently
- reproducible command: `scripts/smoke_hocusscript_apply.py`

## 8. HS5: Export and Editor Workflow

Status: complete

Dependencies: HS4 for the full edit/apply/review loop; parse/format/export work may begin after HS3
Houdini required: yes for export

- [x] Add `document.format_source`.
- [x] Add `document.export_source`.
- [x] Return export source text and provenance without writing a project file from MCP.
- [x] Complete the native export/recompile round trip with no-overwrite and expected-digest replacement safeguards.
- [x] Export durable IDs and ownership metadata.
- [x] Define fail-closed rejection rules for unsupported constructs; HocusScript 0.1 has no opaque syntax.
- [x] Add semantic export/recompile golden and live tests.
- [x] Add catalog-backed completion endpoint.
- [x] Add local structural check/format/compile CLI workflow.
- [x] Add syntax highlighting/editor grammar.
- [x] Defer LSP until the versioned diagnostic and completion contracts have downstream use and stabilize.
- [x] Update manual and agent workflows to prefer `.hocus` source.

Verification:

- the consolidated authoring scenario retains the export/recompile workflow and fail-closed behavior
- schemas: all repository Draft 2020-12 schemas valid at the HS5 checkpoint, including legacy/current GraphSpec and strict format/completion/export outputs
- H21.0.729 actual registered endpoint over the unmodified force-synced document: repeated export byte-identical; exact-catalog compile/resolve/lower semantic equivalence; unsupported bypass blocked with `HOCUS805`; no filesystem writes
- reproducible command: `scripts/smoke_hocusscript_export.py`

## 9. HS6: Modules and Studio Libraries

Status: Batches A-G5 complete for the native `0.2` lane; H0-H2 complete the isolated language-`0.3` frontend, strict carrier family, and pure validator/expander. H3-H4 and document/live integration remain pending, while MCP remains content-only

Dependencies: HS5, import security design
Houdini required: module compiler no; live module fixtures yes

- [x] Lock language `0.2` / compiler `0.4.0` / GraphSpec `0.3` / bundle `0.3` without reinterpreting `0.1`.
- [x] Define one root graph/module per file, literal imports, named `use` instances, and exact `bool`/`int`/`float`/`string`/`node_output` parameters and exports.
- [x] Require a durable `@id` seed on every `use`; define module-local node/use `@id` as namespaced seeds, durable nested instance-ID paths, reserved generated symbols, and rename-stable expanded identity.
- [x] Define `expansion-map-v1`, `resolved-module-set-v1`, digest-keyed interned expansion stacks shared by mappings/diagnostics, and aggregate limits.
- [x] Define same-project-first resolution plus manifest-declared, separately approved, transitively locked external aliases.
- [x] Add strict v3 manifest/lock and module-manifest structural decoders, version-gated GraphSpec/bundle scaffolds, and MCP resources for GraphSpec `0.3`, `expansion-map-v1`, and `resolved-module-set-v1` without enabling language `0.2` compilation or live preview.
- [x] Unify strict SemVer 2.0, including pre-release and build metadata, across module manifest, project alias, lock, resolved-set, and bundle schemas.
- [x] Add read-only v3 lock verification and explicit empty-module lock create/update scaffolding; reject nonempty updates until the resolver derives the records.
- [x] Implement typed module parameters and exports.
- [x] Implement hygienic deterministic expansion.
- [x] Implement offline project-contained static imports through an explicit native project compiler API.
- [x] Resolve imports relative to the importing file and ordered project module directories without implicit discovery.
- [x] Bind structurally validated project identity, source/module directories, catalog lock, and module-lock fields into the same-project native resolver; keep that legacy resolver isolated when separate mixed-root compiler/editor consumers are added.
- [x] Require manifest-declared, separately approved aliases with pre-pinned module-manifest digests and manifest entry gates for read-only mixed-root planning.
- [x] Enable resolver-derived nonempty same-project lock updates; retain atomic, expected-digest, explicit-write gates.
- [x] Add same-project module source/interface/transitive content hashes and resolver-derived lockfile records.
- [x] Derive exact, transitively complete prospective external-library records and an exact current-lock diff without writing.
- [x] Publish exact external-library records only after G3 independently rederives them under the writer lease; never trust a caller-supplied plan, plan digest, prospective payload, or module records as publication authority.
- [x] Require explicit write authority, one valid existing lock, and its exact digest; strict-validate the canonical payload and prebuild the portable receipt before atomic replacement, with verified no-op behavior when unchanged.
- [x] Add a strict unregistered `mixed-module-lock-update-v1` receipt schema binding prior/new lock, catalog, root-inspection, resolver-policy, entry, module, and exact diff identities without host paths.
- [x] Resolve published external records through separate compiler/semantic/bundle APIs from mandatory exact roots revalidated on every G4 call; retain final project/lock/catalog/root/manifest/source/winner rechecks and emit only portable host-path-free artifacts.
- [x] Add separate mixed saved-file/dirty-buffer completion and definition APIs with mandatory keyword-only `module_roots`, project-local subjects, verified external dependency completion/navigation, and unchanged fail-closed same-project editor behavior.
- [x] Add G5 repeatable CLI `--module-root ALIAS=ABSOLUTE_PATH` dispatch on `check`, `compile`, and `lock --update` only, without adding an MCP project/root/file surface.
- [x] Preserve bounded interned expansion stacks in expansion source maps.
- [x] Attach semantic compiler diagnostics to shared expansion origin/stack IDs without duplicating interned frames; require portable contained source locations in Bundle `0.3`.
- [x] Enforce import/instance depth, instance/node/source-map/interface limits, exact GraphSpec validation, and zero recursion in the pure content lane; aggregate source/code enforcement remains split between resolver and syntax contracts.
- [x] Reject dynamic imports and keep the parser/resolver/expander free of host, filesystem, environment, network, clock, and random access.
- [x] H0 contract: freeze language `0.2` and lock proposed `0.3` typed expression-producing `if ... outputs` and bounded `for ... range(...) carry` fold syntax, including exact yields/types, lexical scope, both-path and zero-body validation, mandatory durable IDs, domain-separated identity, fixed budgets, zero-count behavior, and no recursion.
- [x] H0 frontend: implement the isolated version-dispatched `0.3` frozen AST, bounded parser with brace-aware recovery and aggregate limits, canonical formatter with version/AST isolation, and focused frontend tests without enabling project compilation or any MCP file/root surface.
- [x] H1 versioned carriers: assign language `0.3` / compiler `0.5.0` / project-lock v4 / external-module v2 / resolved-set v2 / expansion-map v2 / GraphSpec `0.4` / bundle `0.4`; add the exact compatibility matrix, strict bounded decoders, and seven Draft 2020-12 schemas; reject unsupported/mixed pairs and keep compiler/resolver/writer/CLI/editor/document/live dispatch disabled.
- [x] H2 validator/expander: statically validate both conditional branches and every fold body including zero-count folds; implement exact evaluation, lexical hygiene, composable typed results, domain-separated branch/index identity, bounded provenance, cancellation, per-fold/aggregate iteration budgets, and all existing expansion budgets.
- [ ] H3 compiler/CLI/editor integration: enable the new version only through verified native project resolver/compiler/lock and manifest-selected check/format/compile plus project-aware completion/navigation; preserve explicit user-selected project/module roots, legacy isolation, and content-only MCP behavior; accept active batches with Ruff, focused regression coverage, and one real compiler/CLI/editor workflow smoke.
- [ ] H4 adversarial/full verification: cover malformed recovery, unreachable invalid branches, zero and boundary counts, aggregate exhaustion, nesting/shadowing, cancellation, rename/branch/index identity, provenance, relocation, hostile roots, artifact tampering, `0.1`/`0.2` isolation, full repository tests, and independent P0/P1 review.
- [ ] Keep unbounded recursion permanently forbidden; defer explicitly bounded deterministic compile-time recursion to a separately reviewed syntax, termination, identity, provenance, and budget contract outside H0-H4.
- [x] Expose deterministic expanded GraphSpec `0.3`, expansion maps, resolved sets, formatted sources, and digests through the native typed result before semantic/apply integration.
- [x] Seal exact catalog pins into the resolver/compiler handoff, run pinned GraphSpec `0.3` semantic resolution, and produce deterministic portable Bundle `0.3` through a one-shot native API and strict decoder.
- [x] Dispatch native `check`, lock-independent `format`, and one-shot `compile` for manifest-selected language `0.2`; expose resolver-derived `hocus lock --update` without adding an MCP file surface.
- [x] Add bounded guarded artifact output with exclusive create, exact raw-digest replacement, atomic publication, portable receipts, and typed stdout/stderr/exit behavior.
- [x] Add saved-file and unsaved-buffer native project-aware completion with exact lock/interface verification and portable pinned results.
- [x] Add native project-aware go-to-definition for module imports/aliases, parameters, local symbols, and instance exports.
- [x] Keep editor project/file access native-only; do not register project roots, editor schemas, or file-reading behavior in MCP.
- [x] Add explicit per-call external-root/module-manifest inspection with portable pins and no source reads, persistence, resolution authority, writes, CLI/MCP surface, or Houdini dependency.
- [ ] Close `HS-BLOCK-008` diagnostic/URI parity and fresh-live-semantic gates before enabling Bundle `0.3` document lowering or live preview.
- [ ] Add reviewed studio-module contract and provenance tests.

Batch A delivered evidence:

- all 241 offline tests pass; language `0.2` source compilation, project compilation, nonempty lock updates, and live bundle preview remain explicitly blocked
- all 26 Draft 2020-12 schemas meta-validate; strict SemVer 2.0 positive/negative fixtures agree across five HS6 schemas
- registered GraphSpec `0.3`, `expansion-map-v1`, and `resolved-module-set-v1` resources return their canonical IDs, and GraphSpec's external `$ref` resolves to the registered expansion-map contract
- legacy v1/v2 project, lock, compiler, GraphSpec, and bundle tests remain green without migration writes

Batch B delivered evidence:

- version-dispatched `0.2` parsing and canonical formatting cover graph/module roots, literal imports, exact typed parameters/defaults/exports, named `use` arguments, mandatory durable instance IDs, source spans, recovery, and reserved generated symbols while `compile_source` remains gated with `HOCUS102`
- the pure content validator parses exact UTF-8 entry/module bytes, derives interfaces, binds imports to exact source spans, requires matching verified v3 lock records, rejects supplied modules outside the entry closure, enforces canonical portable project URIs and bounded DAGs, verifies bottom-up transitive digests, retains the immutable entry bytes/digest/AST/import envelope, seals all entry/nested import targets and canonical resolved-set content/digest with an internal `hocus-resolved-dag-handoff-v1` digest outside the portable schema, and emits canonical URI-sorted `resolved-module-set-v1`; external libraries remain fail-closed pending separate root approval
- the pure hygienic expander enforces exact types, shared symbol and identity-seed namespaces, bounded cancellation-safe expansion, rename-stable generated identities, strict origin coverage, interned stacks, and final GraphSpec `0.3` decoder/schema compatibility
- the end-to-end offline composition test validates source-derived records against a verified v3 lock and exact entry closure, expands only the immutable entry retained by that DAG, rejects mismatched same-URI entry bytes/AST, and round-trips strict GraphSpec `0.3`
- the resolver-to-expander handoff seal covers the entry, every ordered nested import target, and the canonical resolved-set limits/projection; target swaps, stale-seal limit widening, and module substitutions fail before expansion

Batch C delivered evidence:

- explicit read-only native resolution requires a caller-selected v3 project directory and entry path, verified lock records, contained stable files, and same-project literal imports; it never discovers projects, writes locks, resolves external aliases, or imports Houdini
- `compile_project_module_graph` deterministically composes that sealed DAG through expansion and returns dependency-first canonical module sources, formatted entry source, resolved set, GraphSpec `0.3`, expansion map, project/lock/policy/content digests, and bounded diagnostics without host paths
- empty verified module closures remain valid, `compile_source` remains `0.1`-only with `HOCUS102`, and the native result is ready only for later catalog semantic resolution—not bundle publication, document lowering, live preview, or apply
- the consolidated native-project scenario covers resolver, compiler, relocation, and CLI/editor behavior; `HS-BLOCK-001` continues to prohibit privileged, multi-user, or service-hosted pathname reads

Batch D delivered evidence:

- `update_project_module_lock` derives canonical same-project module records only from exact contained entry/import source bytes, exact typed interfaces, dependency-first transitive digests, and the same ordered-root resolver policy used by compilation; arbitrary public nonempty caller records remain rejected with `HOCUS456`
- an exclusive cooperating-writer lease encloses exact expected-lock authority, bounded multi-entry union derivation, sealed DAG validation and expansion for every entry, final source/root-winner/project/catalog/lock rechecks, and atomic no-overwrite/replace publication; no fallible read occurs after successful publication
- the immutable receipt is host-path-free and binds canonical entry URIs/source digests, prior/new lock digests, catalog identity, canonical modules, and structural diff availability; stale old locks can be repaired without trusting their records
- the consolidated project scenario covers stale-lock rejection and repair at the public boundary; remaining platform locking, durability, and descriptor-safe pathname limits stay recorded in `HS-BLOCK-001`

Batch E delivered evidence:

- exact catalog content/fingerprint pins are paired, digest-validated, sealed into `hocus-resolved-dag-handoff-v1`, reverified by expansion, exposed by the host-path-free native compile result, and included in its compile digest
- `compile_project_module_semantic` internally reloads the exact project/lock/catalog snapshot, supports only language `0.2` plus GraphSpec `0.3`, derives catalog selections without caller-supplied snapshots or selections, and maps every diagnostic to the exact/longest enclosing expansion origin and interned stack ID
- the public one-shot `compile_project_module_bundle` accepts only an explicit project directory and entry path; it emits portable Bundle `0.3` with exact URI-sorted dependency records, resolved module set, expansion source maps, semantic selections, catalog constraints, capabilities, and project/lock provenance, then self-validates through the content-only decoder
- the decoder and schema reject rehashed graph/resolved-set/selection/provenance tampering, host-path diagnostic URIs, incoherent or out-of-origin spans, duplicated expansion frames, and offline live entity/Houdini-path claims; relocation is byte-identical and document lowering remains explicitly blocked with `HOCUS700`
- the consolidated project scenario covers semantic bundle construction and live-boundary closure; live/MCP bundle acceptance remains disabled

Batch F1 delivered evidence:

- existing `check`, `format`, and `compile` dispatch by manifest version: the `0.1` path remains compatible, while `0.2` check uses exact locked semantic compilation, format handles one graph/module file without reading the lock, and compile emits the deterministic one-shot Bundle `0.3`
- `hocus lock --update` delegates directly to resolver-derived nonempty lock publication with explicit command authority and exact expected-lock replacement; compile/check/format never update locks and no MCP tool or project registry was added
- native artifact publication validates and bounds UTF-8 before filesystem access, preserves replacement mode, verifies/fsyncs a same-directory temporary, exclusively links creates or final-digest-checks replacements, and performs only best-effort non-masking cleanup after publication; the noncooperating-writer and directory-fsync limits remain under `HS-BLOCK-001`
- machine stdout contains only requested source/JSON/bundle/portable receipts, typed diagnostics use stderr, syntax-invalid `check --json` preserves parser spans without leaking host paths, and the staged `python -m hocuspocus.hocusscript` entrypoint runs without `hou`
- consolidated authoring and project scenarios cover CLI, formatting, artifact publication, and portable failures

Batch F2 delivered evidence:

- `complete_path`, `complete_project_source`, `definition_path`, and `definition_project_source` require an explicit project directory plus project-relative `.hocus` path and return host-path-free source, project, manifest, lock, catalog, and resolver-policy identities
- saved subjects and every imported module are bounded, canonical, stable, exact-lock/interface verified, and final-rechecked; dirty buffers remain read-only and explicitly report matching, modified, or unlocked lock state
- import-path/name, module-alias, argument, parameter, and export completion plus module/alias/parameter/symbol/export definitions share the compiler's first-winner resolution policy without executing or expanding modules
- module file/aggregate source/result limits, early cancellation, canonical-URI deduplication, lexical masking, hostile path/symlink/shadowing, dependency drift, and metadata race failures are covered; strict output schemas reject nonportable or noncanonical URIs and remain intentionally unregistered from MCP
- the consolidated project scenario covers editor completion/definition and portable compiler/CLI output

Batch G1 delivered evidence:

- `inspect_external_module_roots` requires one explicit pinned v3 project plus an exact per-call alias-to-absolute-root mapping; it performs no discovery, caching, persistence, source reads, lock writes, compilation, editor lookup, MCP registration, or Houdini import
- every root is canonical, local, distinct, outside the project, and free of symlink/junction/reparse components; root and manifest native identities, exact raw manifest bytes, project/lock/catalog pins, aliases, and existing external lock claims are final-rechecked before return
- module manifests are bounded stable reads and must match UID, strict SemVer, language `0.2`, sorted portable entry modules, and the optional declared raw digest; unpinned observations cannot be reused as resolution-ready private authority
- the strict host-path-free inspection schema and domain-separated digest bind only portable sorted project/library pins and remain relocation-stable; at the G1 checkpoint, resolver/compiler/editor/lock-update behavior rejected `@alias`, while G2 planning and G3 publication are delivered below
- the consolidated project scenario covers explicit external roots, manifest inspection, and safe failure on missing roots

Batch G2 delivered evidence:

- `plan_project_module_lock` accepts only an explicit project directory, nonempty project-relative entry paths, and an exact per-call alias-to-root mapping; all manifests must already be pinned by the project, and no private root or native identity enters the portable result
- mixed closure derivation enforces manifest entry gates, relative same-library containment, explicit separately approved cross-library aliases, no external bare imports or library-to-project edges, exact imported names, bounded cycles/depth/files/bytes, cancellation, and strict expansion validation for every entry
- prospective v3 records contain exact canonical source/interface/transitive digests and provenance, dependencies are complete, the current-lock diff is exact, and the strict result/schema bind project, manifest, lock, catalog, root-inspection, resolver-policy, plan, and prospective-lock identities without host paths
- source bytes, native identities, resolver winners, project/lock/catalog metadata, roots, and manifests are final-rechecked; planning acquires no lease, performs no write or publication, and leaves compiler, editor, CLI, MCP, bundle, document, and live behavior unchanged
- the consolidated mixed-project scenario covers planning, explicit roots, resolution, and portable lock output; G3 remains responsible for rederivation under its lease

Batch G3 delivered evidence:

- `update_project_mixed_module_lock` is a separate native-only API requiring exact `allow_write=True`, a valid existing language-0.2 v3 lock and its exact digest, nonempty project-relative entries, and the exact per-call alias-root mapping; it accepts no plan, plan digest, prospective payload, inspection session, or caller-authored module records, and neither CLI nor MCP exposes it
- after the exclusive sibling lease is held and the current lock digest is verified, the writer independently invokes the private mixed-root derivation core, reruns G1 root/manifest validation, derives the complete exact-byte closure, validates every entry through expansion, strict-decodes canonical records, enforces the lock byte bound, and constructs the frozen result before publication
- immediately before atomic replacement, retained evidence rechecks project/lock/catalog metadata, roots and module manifests, entry/module bytes and native identities, and every resolver winner; the atomic writer then performs its immediate expected-digest check, while a canonical unchanged result performs the same checks and returns without creating a temporary or rewriting the lock
- the strict unregistered `mixed-module-lock-update-v1` receipt and runtime invariants bind prior/new lock, catalog, root-inspection, resolver-policy, sorted entries/modules, exact provenance, complete dependencies, and exact added/removed/changed sets without native paths; relocation yields identical receipts and lock bytes
- default denial, malformed/stale/invalid locks, lease contention, semantic and limit failures, cancellation, source/root/manifest/project/catalog/lock/winner races, forced result-construction failure, replacement failure, no-op inode/mtime preservation, cleanup, advisory-planner isolation, and legacy resolver/writer isolation all preserve the active lock boundary; the older same-project writer also now rejects a deep chain at admission instead of over-reading past `moduleFiles`
- the consolidated mixed-project scenario covers publication authority and stale-lock protection; same-user locking limits, descriptor-safe reads, stale-lease recovery, directory durability, and noncooperating-writer limits remain under `HS-BLOCK-001`

Batch G4 delivered evidence:

- separate mixed graph, semantic, and Bundle `0.3` producers require the complete exact per-call alias-root mapping, verify only the current G3-published records, retain authority through construction, and perform final project/lock/catalog/root/manifest/source/winner rechecks before returning portable host-path-free results
- separate `complete_mixed_path`, `complete_mixed_project_source`, `definition_mixed_path`, and `definition_mixed_project_source` APIs require keyword-only `module_roots`; subjects remain project-local while verified external dependencies contribute completion and definition targets through portable module URIs
- legacy same-project compiler, semantic, bundle, resolver, and editor surfaces remain unchanged and fail closed on external aliases; G4 adds no CLI/MCP file surface, and document/live Bundle `0.3` consumption remains blocked under `HS-BLOCK-008`
- the consolidated mixed-project scenario covers compiler, bundle, editor, strict validation, and legacy isolation at the public boundary
- compileall, diff-check, no-`hou` import, relocation, and path-leak gates remain release checks; the same-user pathname/descriptor limits remain under `HS-BLOCK-001`

Batch G5 delivered evidence:

- repeatable `--module-root ALIAS=ABSOLUTE_PATH` is accepted only by `check`, `compile`, and `lock --update`; supplied roots dispatch to the separate mixed semantic, bundle, and guarded lock-publication APIs, while omission preserves all same-project behavior
- every mixed CLI invocation supplies the complete exact declared root mapping again; duplicate aliases are rejected before mapping construction, the first `=` separates alias from path, and malformed, relative, missing, or extra roots fail closed without inference from lock data
- roots are never loaded from an environment variable, home/environment-expanded, cached, persisted, or emitted in portable JSON, bundles, receipts, or typed diagnostics; paths containing spaces remain supported when the `ALIAS=ABSOLUTE_PATH` argument is quoted
- mixed lock publication requires one valid existing v3 lock and its exact `--expected-lock-digest`; syntax-only `format`, language-`0.1` `write-export`, and language `0.1` do not silently accept module roots
- mixed editor completion/navigation remains a native Python API surface rather than a CLI or MCP command; MCP remains content-only and document/live Bundle `0.3` consumption remains blocked under `HS-BLOCK-008`
- the consolidated project scenario covers mixed/legacy CLI and the content-only MCP boundary without exposing physical roots
- compileall, diff-check, no-`hou` import, guarded replacement, and path-free output remain release gates

Batch H0 delivered evidence:

- `0.2` is frozen, proposed `0.3` owns typed conditional/fold syntax, fold rather than collection semantics is explicit, and unbounded recursion remains forbidden
- version-dispatched `0.3` AST/parser/recovery/formatter tests cover module and graph controls, valid nesting, exact canonical formatting, malformed yields/headers, empty interfaces, aggregate node/use/control limits, and unchanged `0.1`/`0.2` behavior
- a forged `0.2` AST cannot format `0.3` controls; valid `0.3` parses and formats but `compile_source` remains closed with `HOCUS102`
- the consolidated control scenario covers representative frontend formatting, legacy isolation, validation, and expansion
- H0 success must remain syntax-only: project/lock/resolved-set/bundle/schema version enablement belongs to H1, semantic validation/expansion belongs to H2, compiler/CLI/editor integration belongs to H3, and adversarial/full verification belongs to H4
- no H batch may add an MCP command or resource that reads, writes, lists, watches, resolves, completes, or registers `.hocus` files, projects, or roots

Batch H1 delivered evidence:

- the compatibility registry contains two disjoint, exact rows: the frozen language-`0.2` production lane and the language-`0.3` / compiler-`0.5.0` observational lane; a mixed field from either row rejects rather than upgrading
- strict v4 project/lock and v2 external-module manifest decoding pairs only with language `0.3`; production lock writers, resolver verification, and native project compilation reject v4 before lock access or mutation
- seven new Draft 2020-12 schemas cover project v4, lock v4, external module v2, resolved-module-set v2, expansion-map v2, GraphSpec `0.4`, and bundle `0.4`; the schemas meta-validate and accept only the exact new carriers
- the content-only decoders enforce duplicate/non-finite rejection, canonical ordering, bounded iteration limits, control-stack references/provenance, complete version identities, and cross-carrier digests while returning no execution authority
- representative carrier, legacy isolation, compiler/project/module/CLI/editor, schema, and live-resource boundaries remain covered by the four public scenario suites and release gates
- no new live schema resource or MCP project/file/root operation is registered; H1 does not enable semantic expansion, compiler/resolver dispatch, CLI/editor use, document lowering, or live Houdini consumption
- independent review found and verified fixes for legacy `write-export` bypassing manifest routing, incomplete semantic/capability validation, noncanonical and unbound provenance, unauthenticated stack/origin/DAG identities, underdeclared resolved budgets, distinct-instance counting, and hostile JSON exception escapes; the final P0/P1 re-review is clean

Batch H2 delivered evidence:

- `ControlExpansionLimits`, `validate_control_program`, and `expand_control_graph` form a public, pure native API over caller-supplied bytes and exact in-memory resolved units; no project resolver, lock writer, compiler dispatcher, CLI/editor, document/live, or MCP path imports or invokes it
- whole-body admission validates both conditional branches, every fold body including zero-count bodies, exact interfaces/yields/types, frozen graph directives and paths, sequential uses/control results, forward node references, nested iterator/carry scope, one lexical durable-seed namespace, complete import closure/DAGs, code shape, cancellation, and hostile mapping boundaries
- selected expansion implements exact conditionals, ascending half-open folds, composable scalar and `node_output` results, zero-count initializer pass-through, structurally ordered module/control durable identity, rename stability, authenticated interned module/control stacks, bounded direct related origins, and canonical GraphSpec `0.4` plus expansion-map v2 output
- per-fold and aggregate iteration admission, a per-iteration nested-fold guard, expanded node/instance/depth/code/source-map limits, and cancellation before conditions, fold admission, iterations, declarations, and yield commits fail closed with typed HocusScript errors
- H2 behavior now lives in the eight-scenario control suite alongside its actual preview/plan/apply boundary; the separate implementation-detail catalogues were deleted
- active development uses Ruff and one relevant scenario file; the repository-wide ceiling is 50 tests and duplicate runner execution is prohibited

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

- [x] Use optional `node symbol @id("stable-uid"): type` syntax with bounded unique IDs; retain deterministic defaults when omitted.
- [ ] Decide canonical tuple and unit syntax.
- [ ] Decide record/object literal syntax.
- [ ] Decide channel-reference and expression syntax.
- [x] Use `hocus-project://<project-uid>/<path>` for local modules and `hocus-module://<library-uid>/<path>` for approved external libraries; add manifest/lock v3 rather than reinterpreting v1/v2.
- [x] Keep project-directory selection in native compiler/editor configuration; do not expose an MCP project registry.
- [ ] Decide syntax for explicit per-field `preserve_live` and `source_wins` annotations; the default reject-on-conflict policy is locked.
- [ ] Decide quoted/reserved parameter-token syntax such as `parm["input"]`.
- [x] Use confirmation for adoption/ownership transfer, deletion/replacement, disconnect/output clearing, and code installation; retain future studio-policy threshold tuning as configuration work.
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
