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
- Treat `.hocus` as ordinary code: native editor/agent filesystem tools own file I/O, while the offline compiler receives an explicit user-selected project directory.
- Keep Houdini MCP content-based; it consumes compiled bundles and never needs general project-file access.
- Treat offline automated tests and live-Houdini tests as separate required gates.
- Mark code-only, live-validated, and production-validated states distinctly.

## 3. Phase Overview

| Phase | Name | Primary result |
| --- | --- | --- |
| HS0 | Contract and risk lock | Language, IR, safety, and production contracts agreed |
| HS1 | Offline language foundation | `.hocus` parses, validates, formats, and emits GraphSpec |
| HS1P | Native project compiler and bundles | Native `.hocus` files compile from an explicit project root into deterministic portable bundles |
| HS2 | Catalog and semantic resolver | GraphSpec resolves against Houdini/HDA catalog snapshots |
| HS3 | Document lowering and preview | A compiled bundle produces a canonical document, diff, and deterministic preview plan |
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
- add an offline `ProjectContext` with an explicit user-configurable root, stable manifest UID, relative source directories, and deterministic source URIs
- add native `compile_path`/format/check library and CLI surfaces without importing `hou`
- add canonical project containment and bounded UTF-8 reads in the offline compiler
- serialize deterministic content-addressed structural bundles for later MCP preview/planning

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
- inline compilation works without a project directory, while native file compilation receives an explicit project root
- relocating a manifested project preserves canonical source identity
- no Houdini mutation is possible through this phase

## 5A. HS1P: Native Project Compiler and Bundles

This is an early gate before catalog resolution or file-backed document lowering.

Objectives:

- define and validate `hocus.project.toml` and `hocus.lock.json`
- implement offline `ProjectContext`, `compile_path`, check, format, and compile commands
- accept the project root explicitly from CLI/editor configuration; do not put project roots in Houdini MCP configuration
- implement canonical project/source URIs without absolute physical roots in portable provenance
- enforce bounded UTF-8 reads plus traversal, alternate-drive, UNC/device, case, symlink, and junction containment rules
- before privileged or service-hosted project reads, replace pathname check-then-open with descriptor/handle-based containment and file-identity verification on each supported platform
- define a canonical compiled-bundle schema with GraphSpec, source maps, source/dependency digests, manifest/lock/catalog constraints, capabilities, and version fields
- compute bundle identity over deterministic canonical JSON
- retain `document.compile_source` only as an unsaved-buffer compatibility endpoint
- define content-only `document.preview_bundle` and later `document.plan_bundle` MCP handoff contracts

Testing:

- explicit CLI/editor project selection and typed missing-project failures
- nested roots, traversal, conflicting project UIDs, invalid manifest, invalid UTF-8, and oversized source tests
- project relocation with stable source/entity identity
- deterministic bundle JSON/digest and changed-input tests
- CLI exit-code, stdout/stderr, format, and no-`hou` import tests
- unsaved memory source versus portable manifested-bundle behavior

Exit criteria:

- an agent edits `.hocus` with normal workspace tools and invokes the offline compiler with an explicit project directory
- native file compile reads only contained `.hocus` files and emits no machine-specific paths in portable output
- inline memory source and manifest-free checks remain preview-only
- Houdini MCP does not register project roots or read project files
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
- offline project manifest identity, compiled-bundle schema, and project-relative catalog/lock locations

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
- add `document.preview_bundle` for content-addressed offline compiler output
- retain the existing structural `document.compile_source` as a compatibility path for unsaved buffers only
- resolve bundle GraphSpec against the live catalog and produce document lowering plus candidate-plan preview
- report source/dependency/manifest/lock/catalog provenance without accepting filesystem paths
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
- bundle previews bind stable project-relative source URIs and manifest/lock digests rather than machine-specific absolute paths

Implementation status (2026-07-11): complete for the HS3 SOP/network-document v1 slice. The pure lowerer, live preview tool, schema resources, persistent identity path, exact connectors, sparse verification, ownership-safe reconcile, content-addressed artifacts, and node-level dirty-scope monitoring are implemented. Offline tests and the checked-in H21.0.729 live preview/monitor smokes are passing. Broader family/value parity remains HS7; immutable plan persistence/apply remains HS4.

## 8. HS4: Immutable Plan and Guarded Apply

Implementation status (2026-07-11): complete for the guarded SOP/network-document v1 slice. Immutable plan v1 schemas, bounded live retention, insert-only SQLite plan persistence, durable lifecycle/audit events, scope leases, dynamic capability and confirmation gates, idempotent replay, cancellation checkpoints, typed failures, apply-owned rollback, structural inverse capture/identity clearing, symmetric provenance verification, quarantine, and explicit baseline/target recovery classification are implemented. The H21.0.729 disposable live matrix passes real apply/verification plus rollback after all nine executor checkpoints and four lifecycle stages. Unsupported network families, opaque network-container replacement/deletion, and broader value parity remain explicitly blocked for HS7.

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

Status: complete (independent review fixes plus actual H21.0.729 registered-endpoint verification)

Objectives:

- expose canonical formatter and syntax/diagnostic JSON interfaces
- implement `document.export_source` for supported live networks
- return export source text plus durable provenance; native editor/CLI tooling chooses and writes the destination `.hocus` file
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

Delivered evidence:

- `document.format_source`, `document.complete_source`, and `document.export_source` are bounded observational MCP interfaces with strict versioned output schemas
- native `hocus write-export` requires the explicit project directory, creates exclusively by default, and replaces only against an expected digest
- `@id("...")` carries persistent network-document node identity across export destination and symbol changes; provenance records ownership and managed fields
- unsupported HocusScript 0.1 constructs block the entire export with typed diagnostics and no partial source
- offline editor/export/schema/compiler suites pass; the actual registered `document.export_source` H21.0.729 smoke used the unmodified force-synced network document and produced byte-identical repeated exports, exact-catalog compile/resolve/lower equivalence, an explicit unsupported-state blocker, and no filesystem writes
- TextMate syntax highlighting ships now; LSP remains intentionally deferred until these JSON contracts have downstream use and can be stabilized without premature protocol coupling

## 10. HS6: Modules and Studio Libraries

Contract status (Batch A, 2026-07-11): locked. HS6 uses language `0.2`, compiler `0.4.0`, GraphSpec `0.3`, and bundle `0.3`; `0.1` remains unchanged. The contract fixes one root graph/module per file, literal imports, `bool`/`int`/`float`/`string`/`node_output` parameters and exports, named `use` instances with mandatory durable `@id` seeds, namespaced module-local identity seeds, aggregate limits, interned expansion stacks, native-only resolution, and separately approved external aliases. `expansion-map-v1` and `resolved-module-set-v1` are standalone strict contracts; GraphSpec `0.3` embeds the exact expansion-map contract.

Safe Batch A scaffolds include strict v3 manifest/lock and module-manifest decoding, version-gated GraphSpec/bundle trust-boundary shapes, standalone schema resources, read-only lock verification, and empty-module lock create/update with explicit write authority. Language `0.2` parsing/compilation/live preview remain disabled. Nonempty lock updates remain disabled until the resolver derives and verifies module content, interfaces, transitive hashes, aliases, and approvals. Module versions use one strict SemVer 2.0 grammar including build metadata across all contracts.

Language-core status (Batch B, 2026-07-11): complete and still offline-only. The version-dispatched parser and canonical formatter now support one `0.2` graph/module root, literal imports, exact typed interfaces, named arguments, mandatory instance IDs, module expressions, spans, recovery, and reserved-symbol enforcement while the `0.1` compile/format lane remains unchanged. A pure content validator derives interfaces from exact entry/module bytes, binds every supplied module to a verified v3 lock record, rejects modules outside the entry-import closure, validates canonical URI/import provenance and dependency-first transitive digests, retains the exact entry bytes/digest/AST/import envelope, and emits canonical `resolved-module-set-v1`. An internal `hocus-resolved-dag-handoff-v1` digest additionally seals the complete entry and nested alias-to-target edge set plus canonical resolved-set content/digest for the in-memory resolver-to-expander handoff; it is not part of the portable resolved-set schema. The lower-level exact-entry-bytes expansion API intentionally retains caller-owned import mappings, while the validated-DAG API requires and verifies the seal. External libraries remain fail-closed until separate physical-root approval lands. The pure expander consumes only that validated in-memory entry and module DAG, performs bounded exact-type/hygiene checks, emits rename-stable GraphSpec `0.3` identities and interned expansion stacks, and strict-validates every successful result. The end-to-end offline test covers that same exact entry and source-derived DAG through GraphSpec `0.3` round-trip. Native project-directory reads, ordered module-root search, lock updates, bundle `0.3` construction, CLI/editor navigation, and live acceptance remain disabled.

Native integration status (Batch C, 2026-07-11): the explicit read-only `resolve_project_module_dag` and `compile_project_module_graph` APIs now compose a user-selected v3 project directory, verified lock, same-project relative/ordered-module-root resolution, sealed expansion, canonical formatted entry/module inspection, and deterministic digest-bearing GraphSpec `0.3` output. The result retains portable URIs only and is ready for later catalog semantic resolution, not document lowering or apply. `compile_source` remains `0.1`-only; MCP remains content-only; external aliases, lock writes, bundle `0.3`, CLI version dispatch, editor navigation, catalog resolution, and live acceptance remain disabled.

Lock-update status (Batch D, 2026-07-11): the explicit native `update_project_module_lock` API now derives nonempty same-project v3 lock records from caller-selected entry files and their exact contained import closures. A cooperating-writer lease covers expected-digest authority, bounded resolution, source/interface/transitive digest derivation, sealed DAG validation and expansion, final source/root-winner/project/catalog rechecks, and atomic publication. Multi-entry updates are deterministic and union shared dependencies once; stale prior locks can be repaired without trusting their module records, and the host-path-free receipt reports exact entry and lock identities. The public caller-record `update_project_lock` API remains empty-only, compile remains verify-only, and MCP never reads or writes project files. External aliases remain disabled; crash-stale lease recovery, directory durability, noncooperating-writer CAS, and descriptor-safe privileged reads remain under `HS-BLOCK-001`.

Semantic bundle status (Batch E, 2026-07-11): the resolver handoff and native compile result now seal the exact verified catalog content digest and fingerprint alongside project/lock/module inputs. The one-shot `compile_project_module_bundle(project_directory, entry_source_path)` API internally performs sealed expansion, reloads and compares the exact v3 project/lock/catalog snapshot, resolves GraphSpec `0.3` against that catalog, maps diagnostics to interned expansion origin/stack IDs, and constructs a deterministic portable bundle `0.3` only through the strict external decoder. Bundle dependencies exactly mirror the URI-sorted resolved module set; source-map, graph, semantic, catalog, project, lock, and module identities are cross-validated. Diagnostic source locations must use canonical project/module URIs and contained origin spans, cannot duplicate expansion frames, and cannot claim live entity/Houdini paths. Relocation preserves bundle identity. This remains native/offline: bundle `0.3` document lowering, live preview/apply, CLI dispatch, project-aware editor navigation, and external aliases are still fail-closed.

Native CLI status (Batch F1, 2026-07-11): manifest-driven `check`, `format`, and `compile` dispatch now supports language `0.2` without altering the `0.1` compiler lane. Check performs locked semantic compilation and preserves machine-readable invalid results; format is a contained, stable, syntax-only graph/module operation that remains available with a stale lock; compile uses only the one-shot Bundle `0.3` producer. `hocus lock --update` exposes the resolver-derived multi-entry lock transaction with exact expected-lock authority. A shared guarded text publisher provides bounded UTF-8 encoding, exclusive create, raw-digest replacement, temporary-file verification/fsync, mode preservation, atomic link/replace, and non-masking cleanup. JSON/bundle/format stdout is uncontaminated, errors use typed stderr, receipts contain no host paths, and the staged `python -m hocuspocus.hocusscript` entrypoint runs without Houdini. MCP and live Bundle `0.3` behavior are unchanged; the next native editor slice is delivered by Batch F2 below.

Native editor status (Batch F2, 2026-07-12): saved-file and unsaved-buffer completion plus go-to-definition now use an explicit project directory, project-relative subject path, the shared resolver winner policy, and exact verified lock/module interfaces. Results bind manifest, lock, catalog, resolver-policy, subject-source, and portable URI identities; distinguish matching, modified, and unlocked subjects; and never write project state. Completion covers import paths/names, imported module aliases, named parameters, module parameters, and instance exports; definitions cover imported modules/aliases, parameters, local symbols, and exports. Requests enforce source/module/aggregate/result limits, cancellation before saved reads, canonical containment, stable subject/module bytes, final winner/project/catalog rechecks, and URI-based module deduplication. Strict unregistered native result schemas and hostile path/comment/string/race tests are included. The MCP completion endpoint remains content-only and unchanged; external aliases and live Bundle `0.3` acceptance remain disabled.

External authority status (Batch G1, 2026-07-12): the native `inspect_external_module_roots` API now validates a caller-supplied exact alias/root mapping against one pinned v3 project without enabling resolution. It rejects missing/unknown/duplicate-library approvals, noncanonical or network/device paths, project/root overlap, reparse components, casing aliases, nonregular manifests, identity races, malformed or mismatched module manifests, lock conflicts, and pin drift. The host-path-free result binds sorted library UID/version/raw-manifest/entry pins to the exact project, lock, and catalog, with a strict standalone schema and deterministic relocation-stable digest. Optional unpinned manifests remain inspection-only and private roots are never persisted or returned. At the G1 checkpoint, external source reads, lock derivation/publication, compilation, editor resolution, CLI flags, MCP, and live behavior remained disabled; G2 planning and G3 publication are delivered below, while G4-G5 remain pending.

Mixed-root planning status (Batch G2, 2026-07-14): the native read-only `plan_project_module_lock` API now revalidates the exact G1 project/root/manifest boundary, requires pre-pinned manifests, resolves caller-selected entries into a bounded and transitively complete mixed project/library closure, derives exact source/interface/transitive records, requires every entry to pass strict expansion validation while discarding the expansion output, and returns a deterministic host-path-free prospective-lock plan with an exact current-lock diff. Project entry gates, same-library containment, explicit cross-library aliases, canonical identities, relocation stability, cancellation, limits, and final source/root/winner/project/catalog rechecks are enforced. It acquires no writer lease, writes and publishes nothing, and does not enable external-alias use by the compiler, editor, CLI, MCP, bundle, document, or live paths. At the G2 checkpoint G3-G5 remained pending, with G3 required to independently rederive under its lease rather than trust the advisory plan; G3 is delivered below.

External publication status (Batch G3, 2026-07-14): the separate native `update_project_mixed_module_lock` API now requires explicit write authority, one valid existing v3 lock, its exact current digest, nonempty project-relative entries, and the exact per-call alias-root mapping. It accepts no G2 plan, plan digest, prospective payload, or caller-authored records. The cooperating-writer lease encloses complete G1 validation, independent private G2 derivation and expansion checks, strict canonical record/payload/result validation, result construction, and final project/lock/catalog/root/manifest/source/winner rechecks before the atomic writer's immediate digest check. Repeated identical publication is a verified no-op without rewriting. The strict unregistered host-path-free receipt binds prior/new lock, catalog, root-inspection, resolver-policy, entry, module, and exact diff identities; private roots never persist. The same-user limitations remain under `HS-BLOCK-001`. At the G3 checkpoint external-alias compiler/editor/bundle use remained disabled pending G4, CLI root flags remained disabled pending G5, and MCP remained content-only. Bundle `0.3` document lowering and live consumption remain disabled under `HS-BLOCK-008`.

External consumer status (Batch G4, 2026-07-14): complete. Separate native `compile_project_mixed_module_graph`, `compile_project_mixed_module_semantic`, and `compile_project_mixed_module_bundle` APIs now consume the exact G3-published external records only when the caller supplies the complete exact alias-root mapping again for that call. The authority is retained through the requested compiler stage and finally rechecks project, lock, catalog, roots, module manifests, source identities, and every resolver winner before return. Separate saved-file and dirty-buffer `complete_mixed_*` and `definition_mixed_*` APIs require keyword-only `module_roots`; editor subjects remain project-relative while verified external dependencies can contribute completions and definition targets. All successful artifacts remain relocation-stable and host-path-free. The legacy same-project compiler/editor/bundle APIs remain unchanged and fail closed on external aliases. G4 adds no CLI or MCP file/root surface: G5 CLI flags remain pending, MCP remains content-only, and Bundle `0.3` document lowering/live consumption remain blocked under `HS-BLOCK-008`.

External CLI status (Batch G5, 2026-07-14): complete. The native `check`, `compile`, and `lock --update` commands accept repeatable `--module-root ALIAS=ABSOLUTE_PATH`; supplying roots dispatches only to the separate G4 semantic/bundle consumers or G3 mixed lock publisher, while omission preserves the same-project paths. Each mixed invocation must supply the complete exact declared alias mapping again. Duplicate, malformed, relative, missing, or extra roots fail closed; roots are not sourced from environment variables, expanded, inferred from lock data, cached, persisted, or emitted. Mixed lock publication requires the exact current lock digest. Syntax-only `format` and language-`0.1` `write-export` do not accept module roots, and language `0.1` rejects rather than ignores the option. Mixed editor completion/navigation remains available only through native Python APIs and no CLI editor command was added. MCP remains content-only, and Bundle `0.3` document lowering/live consumption remain blocked under `HS-BLOCK-008`. The focused CLI/MCP gate passes 23/23, the full suite passes 413/413 under both runners, the HocusScript-only gate passes 357/357, and independent P0/P1 review is clean after exact and abbreviated forbidden-option path-leak regressions were added.

Typed-control status (Batch H0, 2026-07-15): complete for the isolated frontend and contract. Language `0.2` is frozen, while typed expression-producing conditionals and bounded fold iteration belong to language `0.3`. The exact `if ... outputs` and `for ... range(...) carry` grammar, exact typing, mandatory durable IDs, lexical yields, both-path/zero-body static validation, zero-count behavior, domain-separated branch/index identity, fixed iteration budgets, and continued prohibition on unbounded recursion are specified. The version-dispatched frozen AST, bounded parser with brace-aware recovery and aggregate control/node/use limits, and canonical formatter are implemented; forged `0.2` ASTs cannot emit `0.3` controls. No MCP file/project/root surface is introduced. The focused frontend/legacy gate passes 48/48, the full repository passes 430/430 under both pytest and unittest discovery, and the post-fix P0/P1 review is clean.

Typed-control carrier status (Batch H1, 2026-07-15): complete. The new row is exactly language `0.3`, compiler `0.5.0`, project manifest/lock v4, external module manifest v2, unchanged resolver policy/module interface v1, resolved-module-set v2, expansion-map v2, GraphSpec `0.4`, and bundle `0.4`. Seven strict Draft 2020-12 schemas and bounded read-only decoders enforce the complete tuple, canonical ordering, authenticated interned module/control-stack/origin provenance, canonical URI and owner/path binding, transitive module DAGs, resolved budget usage, the full semantic/capability envelope, exact expansion coverage, and cross-carrier digests. Project/module manifests can be decoded for inspection, but every compiler, resolver, writer, CLI, editor, document, and live MCP consumer remains closed; this includes gating legacy `write-export` before it reads a handoff or resolves a destination for v4 projects. The schemas are deliberately offline and unregistered from the live resource surface. The focused H1 gate passes 15/15, the adjacent legacy isolation gate passes 76/76, the full repository passes 445/445 under both pytest and unittest discovery, all schemas meta-validate, compileall/diff/resource-boundary checks pass, and the final independent P0/P1 review is clean after its findings were fixed with regressions. H2 semantics is delivered below.

Typed-control semantic status (Batch H2, 2026-07-15): complete for the isolated pure lane. The public `validate_control_program` and `expand_control_graph` APIs accept only caller-supplied language-`0.3` bytes, canonical source identities, exact resolved in-memory module units, explicit fixed limits, and an optional cancellation callback; they perform no filesystem, resolver, catalog, Houdini, clock, random, or network access. Whole-body admission validates both branches and every fold body before selected evaluation. Expansion implements exact typed results, half-open folds, zero-count pass-through, lexical hygiene, structurally ordered module/control durable identity, authenticated bounded module/control provenance, canonical GraphSpec `0.4`, cancellation, and iteration plus existing node/instance/code/source-map budgets. Frozen graph path/ownership/flag invariants and hostile input boundaries fail typed. H3 remains required for pinned whole-AST catalog capability validation and verified resolver/compiler/lock/CLI/editor dispatch; every document/live/MCP consumer remains closed. The focused H2 plus adjacent isolation gate passes 73/73 and the full repository passes 480/480 under both pytest and unittest discovery; final independent P0/P1 review is clean after its findings were fixed with regressions.

Objectives:

- typed module parameters and exports
- hygienic deterministic expansion
- offline, project-contained static imports
- resolve imports relative to the importing file and ordered project source/module directories
- transitive lockfiles and content hashes
- language-`0.3` typed expression-producing conditionals and bounded fold iteration under fixed limits
- expansion source maps and inspectable expanded graphs
- reviewed studio module/HDA contracts and provenance

Exit criteria:

- builds pin complete transitive module and catalog inputs
- dynamic imports, implicit environment reads, network access, reflection, and unbounded expansion are impossible
- module upgrades are explicit and diff-visible
- the same project can be relocated without changing semantic IDs when its stable manifest UID, relative paths, content, and lockfiles are unchanged
- expanded graphs remain inspectable; original module files remain the editable authority

Implementation sequence:

1. preserve the `0.1` lane and add version-dispatched `0.2` source-unit parsing and formatting
2. implement same-project literal imports, ordered module roots, typed interfaces, cycle rejection, and a pure resolver session
3. implement hygienic expansion, shared budgets/cancellation, stable instance identity, `expansion-map-v1`, and expansion inspection
4. bind the manifest/lock v3 and bundle `0.3` scaffolds to resolver-derived `resolved-module-set-v1`; verified same-project nonempty lock updates and native semantic bundle production are complete
5. make document provenance and default UIDs consume the already-resolved module origins and instance paths
6. add native project-aware completion/navigation while keeping MCP content-only
7. enable external aliases only through staged gates: G1 explicit root/manifest inspection, G2 read-only complete mixed-root lock planning, G3 leased atomic external-record publication, G4 separate exact-root compiler/editor/bundle consumption, and G5 explicit repeatable CLI `--module-root ALIAS=ABSOLUTE_PATH` dispatch are complete, while MCP remains content-only
8. deliver proposed language `0.3` control through separately reviewable H sub-batches:
   - H0 contract/frontend: freeze `0.2`; lock `if SYMBOL @id(...) (...) outputs (...) { ... yield ... } else { ... }` and `for SYMBOL @id(...) (ITERATOR in range(...)) carry (...) { ... yield ... }`; implement isolated AST/parser/formatter/recovery only, with completion dependent on focused frontend verification
   - H1 versioned carriers (complete): assign and scaffold compiler `0.5.0`, project/lock v4, external module manifest v2, resolved-set v2, expansion-map v2, GraphSpec `0.4`, bundle `0.4`, the exact compatibility matrix, strict decoders, and offline schemas; reject every mixed or unsupported pairing and keep compiler/resolver/writer/CLI/editor/document/live MCP dispatch disabled
   - H2 semantics (complete): add whole-body static validation, exact evaluation, fold expansion, lexical hygiene, domain-separated identity, bounded provenance, cancellation, and all iteration plus existing expansion budgets
   - H3 native integration: enable verified project resolver/compiler/lock, CLI check/format/compile, and project-aware editor completion/navigation only through the new version lane; retain explicit user-selected project/module roots and the content-only MCP boundary
   - H4 adversarial/full verification: add malformed/recovery, hidden-branch, zero-count, boundary/aggregate budget, cancellation, identity stability, nesting, provenance, relocation, hostile-root, artifact-tamper, legacy-isolation, and full repository gates before declaring `0.3` supported

Unbounded recursion remains permanently forbidden. Explicitly bounded deterministic compile-time recursion is deferred to a separate reviewed contract covering syntax, termination, identity, provenance, and budgets; it is not part of H0-H4.

The historical safe `0.2` slice was same-project static imports with typed scalar/`node_output` parameters and exports; it is complete through G5 and remains frozen. The current safe H2 slice adds pure whole-body `0.3` validation and selected deterministic expansion to the H0 frontend and H1 strict carrier family. It excludes resolver/lock-writer/compiler/CLI/editor dispatch, pinned catalog capability authorization, live schema registration, MCP file access, document/live consumption, and recursion until their named gates close.

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
- explicit native project selection, relocation, traversal, symlink/junction escape, bundle portability, and offline/MCP boundary tests

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

## 16. Roadmap Backlog and Major Issues

### HS-BLOCK-001: Descriptor-Safe Native Project Reads

Status: open

Canonical path resolution blocks ordinary traversal and symlink/junction escapes, but pathname check-then-open still permits a narrow reparse-point swap race between validation and file open. Before project reads are used from a privileged, multi-user, or service-hosted process, implement descriptor/handle-based opens, verify the final object identity and containment from the opened handle, and add Windows junction plus POSIX symlink race tests. Native same-user CLI operation may continue while this remains explicitly gated; Houdini MCP still performs no project-file reads.

The v3 empty-lock and same-project writers use an exclusive sibling update lease, exact digest rechecks immediately before atomic publication, and no-overwrite creation. G3 external-record publication uses this same-user cooperating-writer boundary and independently rederives and revalidates the complete mixed-root closure under the lease; a G2 plan or caller-supplied plan JSON is advisory and never publication authority. This lease is not a filesystem-native compare-and-swap against an arbitrary non-cooperating writer in the final recheck/replace window. A process crash can also leave a stale lease requiring manual recovery. Platform handle-based locking, stale-lease ownership/recovery, directory-durability guarantees, descriptor-safe reads, and adversarial raw-writer race tests remain part of this blocker before multi-user/service-hosted lock updates are enabled.

### HS-BLOCK-002: Non-Mutating Live Named/Typed Connector Fidelity

Status: open

Catalog v1 records exact indexed connectors and preserves stable names/types when the provider supplies them. Generic `hou.NodeType` does not expose the instance-level input/output name, label, and VOP data-type APIs for many real definitions. The live provider therefore emits honest null/empty optional metadata rather than creating nodes or fabricating names. Before HS3/HS7 claims named-port or typed-port fidelity for those operators, implement an audited non-mutating metadata source or a disposable isolated-node introspection strategy with init scripts disabled, per-family tests, cleanup verification, and an explicit completeness marker. Indexed-port semantic resolution may continue; missing names/types are not treated as proof of compatibility.

### HS-BLOCK-003: Complete Houdini Package Search Provenance

Status: open

The live provider records package JSON and Labs evidence from explicit directories, `HOUDINI_PACKAGE_DIR`, user preferences, versioned `HSITE`, and `$HFS/packages`, and it rejects normalized package-ID collisions. Houdini can additionally compose dynamic package paths and precedence rules. Before package provenance is used as a production publish or clean-machine reproducibility gate, enumerate the complete effective search/load order, fingerprint precedence and shadowing, and add multi-root live fixtures. Operator/HDA fingerprints remain authoritative for semantic resolution while this provenance enrichment is open.

### HS-BLOCK-004: Unordered/Variadic Input Index Semantics

Status: open

Houdini may compact sparse requested indices on unordered inputs; for example, a request for Merge input 5 can reimport as physical input 0. HS3 preserves and verifies exact physical input/output indices and rejects drift rather than silently accepting a different graph. Before the language claims portable sparse variadic addressing, define whether DSL indices mean physical HOM slots or logical connection ordinals, version that rule in catalog connector metadata, and add live round-trip fixtures for unordered SOP/VOP inputs.

### HS-BLOCK-005: Whole-Tuple Component Mapping in Portable Bundles

Status: open

Catalog resolution knows tuple component tokens, but compiled-bundle v0.2 parameter selections do not retain the ordered component-token mapping required to expand a whole-tuple assignment into scalar network-document bindings. HS3 emits blocking `HOCUS708`; scalar component assignments work. Add the mapping in a compatible semantic/bundle version, bind it into the bundle hash/schema, and add relocation plus live round-trip tests before enabling whole-tuple lowering.

### HS-BLOCK-006: Explicit Source Entity IDs Across Symbol Renames

Status: resolved in HS5

Optional `@id("...")` source identity now maps directly to persistent network-document node UIDs and survives source-symbol and export-destination changes. Duplicate, invalid, or path-colliding explicit IDs block structurally; omitted IDs retain deterministic graph/source/local-symbol derivation. Compiler, bundle, schema, lowering, exporter, golden, symbol-rename, collision, and live round-trip coverage preserve the rule that path and session IDs are not substitutes for durable identity.

### HS-BLOCK-007: Real Live Export Identity and Managed-Field Reconstruction

Status: resolved in HS5 independent review

The first export smoke used a normalized projection and therefore did not prove the registered endpoint against actual root category/default parameter state. The corrected implementation accepts `/obj` as the SOP container while requiring `persistent_user_data` identity for the root anchor and every exported child. Signed per-node `managedFields` survive Houdini user data; live reimport reconstructs ownership on derived bindings, code blobs, data edges, and output edges. Root/default/artist-owned fields are omitted from source and enumerated as `preservedState`, so they remain baseline-preserved merge state rather than being silently promoted to portable source ownership. The final H21.0.729 smoke calls the registered handler over the unmodified force-synced document.

### HS-BLOCK-008: Bundle 0.3 Diagnostic and URI Parity Before Live Acceptance

Status: open; blocks Bundle `0.3` live preview/document lowering, not native offline production

The strict Bundle `0.3` decoder now rejects host-path diagnostic URIs, invalid or out-of-origin spans, duplicated expansion frames, and offline live-path/entity claims. It can authenticate that a diagnostic span is structurally coherent and contained by its expansion origin, but source bytes are intentionally absent from the content-only bundle, so it cannot reconstruct arbitrary interior multiline offset/line/column relationships from bytes. Its URI decoder also enforces canonical percent encoding and traversal/absolute-path rejection but does not yet share every native portability rule, including Unicode NFC and all Windows-reserved path segments. Before enabling live Bundle `0.3` acceptance, either bind diagnostics to exact GraphSpec field spans or explicitly treat their locations as untrusted display hints, unify URI validation with the native portable-path contract, add rehashed hostile fixtures, and freshly re-resolve all semantic selections against the live catalog. The current native one-shot producer already derives these fields from validated project sources, and live/document lowering remains fail-closed with `HOCUS700` while this gate is open.
