# HocusScript Delivery Roadmap

Status: V1 technical baseline complete; production-release closure active
Source contract: `docs/hocusscript-spec.md`
Completion plan: `docs/hocusscript-roadmap-completion-plan.md`

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
- Treat `.hocus` as ordinary code: native editor/agent filesystem tools remain the primary editing surface, while every compiler or workspace consumer receives an explicit user-selected project authority.
- Keep Houdini mutation content-based: the opt-in MCP workspace can access approved source projects, but preview/plan/apply consumes authenticated compiled bundles rather than mutating from file paths.
- Scope MCP filesystem access to user-approved HocusScript projects and separately approved read-only external roots; never expose a general host-filesystem tool.
- Treat offline automated tests and live-Houdini tests as separate required gates.
- Cap the complete repository catalogue at 50 public workflow scenarios; do not use implementation-detail test volume as delivery evidence.
- Cap every source, script, config, documentation, and fixture file at 1,200 physical lines.
- Enforce explicit function complexity ceilings in Ruff and require the whole repository to comply without grandfathered files or suppressions.
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
| HS6 | Modules and reusable source libraries | Typed local and approved external source modules expand deterministically |
| HS6-H5 | Module/control document-live bridge | Frozen Bundle `0.3` and Bundle `0.4` lower, preview, plan, and apply through exact-version guarded paths |
| HS6-H6 | Project-scoped MCP source workspace | Agents can read, edit, build, and navigate explicitly user-approved HocusScript projects |
| HS7 | Network-family and value parity | SOP/MAT/LOP/TOP and complex values reach declared fidelity |
| HS8 | Production and AAA hardening | Deterministic asset fixtures, validation, review, CI, and publishing |
| RC0-RC5 | V1 release closure | Complete mutable engineering, freeze once, bind external clean-image and human authority to that candidate, and publish |

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

- one representative authoring workflow covering parse, compile, format, and diagnostics
- deterministic serialization plus fail-closed export validation
- public failure scenarios for malformed source and unresolved references
- bounded-input and cancellation behavior at the public expansion boundary

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
- accept the project root explicitly from CLI/editor configuration; reserve MCP project configuration for the later opt-in H6 workspace rather than making it an HS1 dependency
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
- before H6, Houdini MCP does not register project roots or read project files
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
- supported live networks emit source that structurally recompiles and passes
  exact-catalog semantic and connector validation, without claiming network
  reconstruction
- unsupported constructs are explicit and lossless or block export
- agents can use a `.hocus` file without manually authoring network-document JSON
- editor diagnostics point to exact source spans

Delivered evidence:

- `document.format_source`, `document.complete_source`, and `document.export_source` are bounded observational MCP interfaces with strict versioned output schemas
- native `hocus write-export` requires the explicit project directory, creates exclusively by default, and replaces only against an expected digest
- `@id("...")` carries persistent network-document node identity across export destination and symbol changes; provenance records ownership and managed fields
- unsupported HocusScript 0.1 constructs block the entire export with typed diagnostics and no partial source
- offline editor/export/schema/compiler suites pass; the actual registered
  `document.export_source` H21.0.729 smoke used the unmodified force-synced
  network document and produced byte-identical repeated exports, structural
  recompilation plus exact-catalog semantic and connector validation, an
  explicit unsupported-state blocker, and no filesystem writes; it did not
  establish network-reconstruction equivalence
- TextMate syntax highlighting ships now; LSP remains intentionally deferred until these JSON contracts have downstream use and can be stabilized without premature protocol coupling

## 10. HS6: Modules and Reusable Source Libraries

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

External publication status (Batch G3, 2026-07-14): the separate native `update_project_mixed_module_lock` API now requires explicit write authority, one valid existing v3 lock, its exact current digest, nonempty project-relative entries, and the exact per-call alias-root mapping. It accepts no G2 plan, plan digest, prospective payload, or caller-authored records. The cooperating-writer lease encloses complete G1 validation, independent private G2 derivation and expansion checks, strict canonical record/payload/result validation, result construction, and final project/lock/catalog/root/manifest/source/winner rechecks before the atomic writer's immediate digest check. Repeated identical publication is a verified no-op without rewriting. The strict unregistered host-path-free receipt binds prior/new lock, catalog, root-inspection, resolver-policy, entry, module, and exact diff identities; private roots never persist. The same-user limitations remain under `HS-BLOCK-001`. At the G3 checkpoint external-alias compiler/editor/bundle use, CLI root flags, and Bundle `0.3` document/live consumption remained disabled pending their later gates; MCP remained content-only.

External consumer status (Batch G4, 2026-07-14): complete. Separate native `compile_project_mixed_module_graph`, `compile_project_mixed_module_semantic`, and `compile_project_mixed_module_bundle` APIs now consume the exact G3-published external records only when the caller supplies the complete exact alias-root mapping again for that call. The authority is retained through the requested compiler stage and finally rechecks project, lock, catalog, roots, module manifests, source identities, and every resolver winner before return. Separate saved-file and dirty-buffer `complete_mixed_*` and `definition_mixed_*` APIs require keyword-only `module_roots`; editor subjects remain project-relative while verified external dependencies can contribute completions and definition targets. All successful artifacts remain relocation-stable and host-path-free. The legacy same-project compiler/editor/bundle APIs remain unchanged and fail closed on external aliases. G4 added no CLI or MCP file/root surface; at that checkpoint G5 CLI flags and Bundle `0.3` document/live consumption remained pending.

External CLI status (Batch G5, 2026-07-14): complete. The native `check`, `compile`, and `lock --update` commands accept repeatable `--module-root ALIAS=ABSOLUTE_PATH`; supplying roots dispatches only to the separate G4 semantic/bundle consumers or G3 mixed lock publisher, while omission preserves the same-project paths. Each mixed invocation must supply the complete exact declared alias mapping again. Duplicate, malformed, relative, missing, or extra roots fail closed; roots are not sourced from environment variables, expanded, inferred from lock data, cached, persisted, or emitted. Mixed lock publication requires the exact current lock digest. Syntax-only `format` and language-`0.1` `write-export` do not accept module roots, and language `0.1` rejects rather than ignores the option. Mixed editor completion/navigation remains available only through native Python APIs and no CLI editor command was added. MCP remains content-only for project files. At the G5 checkpoint Bundle `0.3` document/live consumption remained pending H5; H5 now provides that content-based path. The consolidated project workflow covers the CLI and MCP boundary without retaining the former exhaustive regression matrix.

Typed-control status (Batch H0, 2026-07-15): complete for the isolated frontend and contract. Language `0.2` is frozen, while typed expression-producing conditionals and bounded fold iteration belong to language `0.3`. The exact `if ... outputs` and `for ... range(...) carry` grammar, exact typing, mandatory durable IDs, lexical yields, both-path/zero-body static validation, zero-count behavior, domain-separated branch/index identity, fixed iteration budgets, and continued prohibition on unbounded recursion are specified. The version-dispatched frozen AST, bounded parser with brace-aware recovery and aggregate control/node/use limits, and canonical formatter are implemented; forged `0.2` ASTs cannot emit `0.3` controls. No MCP file/project/root surface is introduced. Representative parsing, formatting, validation, and expansion remain covered by the consolidated control workflow.

Typed-control carrier status (Batch H1, 2026-07-15): complete. The new row is exactly language `0.3`, compiler `0.5.0`, project manifest/lock v4, external module manifest v2, unchanged resolver policy/module interface v1, resolved-module-set v2, expansion-map v2, GraphSpec `0.4`, and bundle `0.4`. Seven strict Draft 2020-12 schemas and bounded read-only decoders enforce the complete tuple, canonical ordering, authenticated interned module/control-stack/origin provenance, canonical URI and owner/path binding, transitive module DAGs, resolved budget usage, the full semantic/capability envelope, exact expansion coverage, and cross-carrier digests. Project/module manifests can be decoded for inspection, but every compiler, resolver, writer, CLI, editor, document, and live MCP consumer remains closed; this includes gating legacy `write-export` before it reads a handoff or resolves a destination for v4 projects. The schemas are deliberately offline and unregistered from the live resource surface. Carrier compatibility is retained through representative project and control workflows rather than a separate schema matrix. H2 semantics is delivered below.

Typed-control semantic status (Batch H2, 2026-07-15): complete for the isolated pure lane. The public `validate_control_program` and `expand_control_graph` APIs accept only caller-supplied language-`0.3` bytes, canonical source identities, exact resolved in-memory module units, explicit fixed limits, and an optional cancellation callback; they perform no filesystem, resolver, catalog, Houdini, clock, random, or network access. Whole-body admission validates both branches and every fold body before selected evaluation. Expansion implements exact typed results, half-open folds, zero-count pass-through, lexical hygiene, structurally ordered module/control durable identity, authenticated bounded module/control provenance, canonical GraphSpec `0.4`, cancellation, and iteration plus existing node/instance/code/source-map budgets. Frozen graph path/ownership/flag invariants and hostile input boundaries fail typed. H3 remains required for pinned whole-AST catalog capability validation and verified resolver/compiler/lock/CLI/editor dispatch; every document/live/MCP consumer remains closed. H2 behavior is retained in the eight-scenario control workflow suite; the implementation-detail catalogues and dual-runner count reporting were retired.

Typed-control native integration status (Batch H3, 2026-07-25): complete. Callers choose the directory containing their ordinary `*.hocus` editing surface through an explicit project-directory argument or the CLI `--project` option. The local lane derives and atomically publishes complete schema-v4 locks under explicit write authority, expected-digest and lease checks, whole-program H2 validation, pinned whole-AST catalog admission, and final project/lock/catalog/source/winner rechecks. The external lane additionally requires the complete exact `--module-root ALIAS=ABSOLUTE_PATH` mapping on every lock/check/compile call, accepts only pre-pinned module-manifest-v2 libraries, and never persists or emits host roots. Both lanes emit resolved-module-set v2, GraphSpec `0.4`, and authenticated portable Bundle `0.4`; syntax-only format remains lock-independent.

The native editor surface now provides saved-file and dirty-buffer completion and definition APIs for local and mixed projects. It models nested `if`/`for` lexical scopes, branch isolation, declaration order, iterator/carry/control results, imported module arguments/exports, yields, and pinned catalog operator/parameter names. Mixed definition targets use portable `hocus-module://` URIs while the edited subject remains project-relative. The combined real workflow published an external v4 lock, passed manifest-selected CLI check/compile, produced a host-path-free Bundle `0.4`, completed a control result, and navigated an imported export. No editor command or MCP filesystem capability was added in H3: `.hocus` stays code. H5 now provides exact document/live Bundle `0.4` consumption, and opt-in MCP workspace access is next in H6.

Objectives:

- typed module parameters and exports
- hygienic deterministic expansion
- offline, project-contained static imports
- resolve imports relative to the importing file and ordered project source/module directories
- transitive lockfiles and content hashes
- language-`0.3` typed expression-producing conditionals and bounded fold iteration under fixed limits
- expansion source maps and inspectable expanded graphs
- pinned local and separately approved external source-module provenance;
  consumption-only studio/HDA library productization is post-v1

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
7. enable external aliases only through staged gates: G1 explicit root/manifest inspection, G2 read-only complete mixed-root lock planning, G3 leased atomic external-record publication, G4 separate exact-root compiler/editor/bundle consumption, and G5 explicit repeatable CLI `--module-root ALIAS=ABSOLUTE_PATH` dispatch are complete; MCP remains content-only through H5, and H6 adds only the separately approved source workspace
8. deliver proposed language `0.3` control through separately reviewable H sub-batches:
   - H0 contract/frontend: freeze `0.2`; lock `if SYMBOL @id(...) (...) outputs (...) { ... yield ... } else { ... }` and `for SYMBOL @id(...) (ITERATOR in range(...)) carry (...) { ... yield ... }`; implement isolated AST/parser/formatter/recovery only, with completion dependent on focused frontend verification
   - H1 versioned carriers (complete): assign and scaffold compiler `0.5.0`, project/lock v4, external module manifest v2, resolved-set v2, expansion-map v2, GraphSpec `0.4`, bundle `0.4`, the exact compatibility matrix, strict decoders, and offline schemas; reject every mixed or unsupported pairing and keep compiler/resolver/writer/CLI/editor/document/live MCP dispatch disabled
   - H2 semantics (complete): add whole-body static validation, exact evaluation, fold expansion, lexical hygiene, domain-separated identity, bounded provenance, cancellation, and all iteration plus existing expansion budgets
   - H3 native integration (complete): enable verified local/mixed project resolver/compiler/lock, CLI check/format/compile, and control-aware editor completion/navigation only through the new version lane; retain explicit user-selected project/module roots and the content-only MCP boundary
   - H4 adversarial/full verification (complete): cover malformed/recovery, hidden-branch, zero-count, boundary/aggregate budget, cancellation, identity stability, nesting, provenance, relocation, hostile-root, artifact-tamper, legacy-isolation, and full repository gates before declaring `0.3` supported
   - H5 document/live integration: close the Bundle `0.3`/`0.4` diagnostic and URI blocker; lower GraphSpec `0.4` plus module/control provenance into canonical network documents; freshly re-resolve against the live catalog; enable preview, immutable plan, guarded apply, rollback, verification, and structural export recompilation with exact-catalog semantic/connector validation
   - H6 project-scoped MCP workspace: let the user approve and configure project directories and read-only external roots; expose bounded project-relative source read/edit/build/navigation operations; preserve exact-digest writes, native-file authority, bundle-based Houdini mutation, and explicit revocation

H4 qualification status (2026-07-26): complete after trust-boundary repair. The existing authoring, control, and project workflow scenarios now cover strict carrier tampering, malformed/recovered and forged ASTs, hidden invalid bodies, zero/boundary/aggregate folds, nesting/shadowing, late cancellation including large catalog scans and ambiguity materialization, durable identity/provenance, local/mixed relocation, hostile roots, stale authority, and frozen legacy behavior without increasing the 34-scenario catalogue. Qualification fixed GraphSpec `0.4` structural decoding, GraphSpec-derived minimum capabilities, declared-source span binding, exact bounded AST admission with a shared aggregate text budget, control admission/cancellation gaps, bounded cancellable ambiguity diagnostics, raw external-root canonicality, and Windows drive-anchor aliases. The clean build/install, 34-workflow suite, Ruff complexity, compileall, diff check, 50-scenario ceiling, and 1,200-line gate pass; the final independent P0/P1 repair review is clean.

### H5: Bundle 0.3/0.4 Document and Live Integration

Status: complete after repair, expanded installed H5E acceptance, and clean independent P0/P1 review

Dependencies: H4 qualification, HS3 document lowering, HS4 immutable plan/apply; the `HS-BLOCK-008` URI/fresh-semantic gate is resolved in code
Houdini required: yes

Implementation batches:

1. **H5A trust-boundary parity**
   - extend `HS-BLOCK-008` to Bundle `0.4`
   - unify canonical project/module URI validation with native portable-path rules
   - bind diagnostics to authenticated GraphSpec/source-map spans or explicitly classify them as untrusted display hints
   - strict-decode and enable both frozen Bundle `0.3` and Bundle `0.4` without cross-version coercion; the `0.3` path receives no new language behavior
   - register the exact GraphSpec `0.4`, expansion-map v2, resolved-module-set v2, and Bundle `0.4` live schema resources as one compatibility unit
2. **H5B control-aware document lowering**
   - lower GraphSpec `0.4`, expansion-map v2, module stacks, control stacks, selected branch/index provenance, and generated entity IDs into the canonical network document
   - preserve ownership, existing/adopt semantics, display/render/output selection, layout, and artist-owned state
   - map document diagnostics and diffs back to portable project/module URIs
3. **H5C fresh live semantics — complete**
   - re-resolve every operator, parameter, connector, capability, exact catalog/HDA fingerprint, and deferred baseline constraint against the running Houdini catalog
   - do not claim complete effective package-search provenance while `HS-BLOCK-003` remains open
   - reject catalog, lock, module, capability, or target-document drift before a plan exists
   - require the same live policy and capability gates already used by HS3/HS4
4. **H5D preview, plan, and guarded apply — complete**
   - at this historical H5D checkpoint, accept authenticated frozen Bundle `0.3` and Bundle `0.4` content through distinct exact-version paths in `document.preview_bundle` and `document.plan_bundle`; HS7 later adds Bundle `0.5`
   - produce deterministic diffs and immutable plans; apply only stored plan identities with revision, confirmation, ownership, and policy checks
   - verify the realized document, roll back failures, and preserve idempotent replay behavior
5. **H5E live workflow qualification — complete**
   - prove local and external-module projects containing nested `if`/`for` controls in a real Houdini session
   - cover preview-only, merge, reconcile, stale-plan, catalog-drift, rollback, save/reload, and structural export recompilation/validation cases
   - apply a newly compiled second merge and second reconcile rather than using idempotent replay; verify exact managed entity and expansion provenance after save/reopen
   - prove target/baseline/partial crash recovery replay and timestamp-controlled expiry/count/byte pruning against a reopened SQLite store
   - at the historical H5 checkpoint, treat live export as a normalized flat
     language-`0.1` semantic handoff; prove structural recompilation and
     exact-catalog semantic/connector validation without claiming network or
     authored module/control reconstruction
   - run any cook used by acceptance as a separately authorized post-apply action after structural apply verification
   - record installed-package/runtime alignment and keep Bundle `0.3`/`0.4` live acceptance fail-closed until the complete matrix passes
6. **H5F trust-boundary and lifecycle repair — complete**
   - reject implicit UID/path adoption and ownership transfer; require complete managed identity, explicit non-confirming provenance-refresh actions, explicit confirming adoption, and plan-time identity-transition cross-checks
   - make reconcile field-selective for retained nodes, execute/verify managed default resets and output clearing, and preserve every unowned field
   - compose only authenticated, referenced module/control expansion stacks after the final document exists; preserve exact non-node provenance through the bounded live root carrier
   - normalize target/baseline recovery replay and bound durable SQLite history to the 24-hour idempotency window, 256 terminal histories, and 256 MiB while preserving pending/partial evidence
   - keep public Bundle, GraphSpec, document, apply-plan, and MCP interfaces unchanged; retain the 34-workflow catalogue and repository linter limits

Exit criteria:

- a native Bundle `0.4` from a user-selected project produces a source-mapped canonical document, preview, immutable plan, and verified Houdini result
- the frozen Bundle `0.3` path passes the same guarded live lifecycle without acquiring language-`0.3` behavior
- selected controls and expanded modules retain portable provenance through preview, apply, reimport, and diagnostics
- no file or project path becomes Houdini mutation authority; only the authenticated bundle and stored plan do
- failures before or during apply leave the live scene unchanged or verified rolled back

H5A status (2026-07-26): complete after independent P0/P1 review. Exact
content-only Bundle `0.3` and
Bundle `0.4` admission now uses distinct authenticated carrier decoders and
rejects legacy, unsupported, malformed, or mixed lanes with `HOCUS700`.
Bundle `0.3` project/module URIs now reuse the native canonical portable-path
contract, including Unicode NFC and Windows-reserved-name rules. Carrier-bound
locations are retained only as authenticated display hints because portable
bundles do not contain the source bytes needed to attest line/column/offset
relationships. The GraphSpec `0.4`, expansion-map v2, resolved-module-set v2,
and Bundle `0.4` schema resources are registered as one adjacent compatibility
unit. At the H5A checkpoint the new carriers remained disabled pending H5C/H5D;
those gates are now implemented below. Focused authoring/runtime workflows and
the independent review are clean.

H5B status (2026-07-26): the pure lowering slice is complete after independent
P0/P1 repair review. A private exact-type adapter accepts only
self-authenticating Bundle `0.3`/`0.4` boundary values, rehydrates the exact
graph version, and feeds the existing deterministic document lowerer. At the
H5B checkpoint this remained a pure lane without a live endpoint. Expanded
entities retain dependency source digests,
origin IDs, related spans, module/control stack references, selected branches
and iteration indexes; stack tables are interned once in document metadata.
Generated explicit identities remain stable, conservative carrier capabilities
remain on the candidate plan, public Bundle `0.2` behavior stays unchanged,
and ordinary public lowering still rejects `0.3`/`0.4`. Independent review
found and repaired direct-construction and subclass token-forgery seams before
qualification.

H5C status (2026-07-26): complete after independent P0/P1 review. Frozen Bundle
`0.3` and control Bundle `0.4` are freshly rehydrated and semantically resolved
against the running catalog through distinct exact-version paths. The live gate
compares operator, parameter, connector, diagnostic, capability, catalog
fingerprint, catalog-content, project, lock, module, and target identities
against the authenticated carrier and rejects drift before planning. Bundle
`0.4` retains conservative hidden-body capability authority while selected
graph semantics must match exactly. Cancellation reaches fresh semantic work
and document preparation. This closes the fresh-live-semantic portion of
`HS-BLOCK-008` in code; it does not claim complete effective package-search
provenance while `HS-BLOCK-003` remains open.

Historical H5D checkpoint status (2026-07-26): complete after independent P0/P1 repair review.
`document.preview_bundle` and `document.plan_bundle` admit Bundle `0.2`, frozen
Bundle `0.3`, and Bundle `0.4` only through their exact decoders; no carrier is
coerced into another lane. Plans pin the exact bundle, compiler/GraphSpec,
project manifest/lock, catalog fingerprint/content, policy, capabilities,
ownership, target document, baseline document/live revisions, and expansion
provenance. Generated expansion symbols receive deterministic legal Houdini
node names without replacing their durable entity IDs or module/control origin
records. `document.apply_plan` consumes only stored plan identity, preserves
signed `managedFields` and artist-owned state, observes cancellation, verifies
the realized document, and uses the existing rollback/quarantine/idempotency
lifecycle on failure. The build stages the exact H5 input/output/apply and
Bundle `0.4` compatibility schemas into the installed package.

Prior H5E status (2026-07-26): passed in installed Houdini 21.0.729 with exact
source/build/install/running-module alignment. The three targets used Bundle
versions `0.3`, `0.4`, and `0.4` in `merge`, `merge`, and `reconcile` modes.
Preview was deterministic; apply verified the realized document and idempotent
replay. Catalog drift failed with `HOCUS752` and succeeded after exact catalog
restore, stale plans failed with `HOCUS753`, and injected mid-executor failure
failed with `HOCUS755` after verified rollback. Save/reopen retained durable
module/control provenance and signed managed fields across all three targets.
All four staged H5 schema resources were available from the installed server.
At that historical H5E checkpoint, the normalized flat language-`0.1` export
structurally recompiled and passed exact-catalog semantic and connector
validation without claiming network or authored module/control reconstruction.
No acceptance cook ran (`cookExecuted = false`), and the final status was
`passed`.

Installed qualification discovered and fixed three core runtime issues before
the passing rerun: preview now force-syncs its live baseline and observes
cancellation; an unchanged graph-store baseline keeps a stable
`baselineLiveRevision`; and an unmanaged `None` position is a verification
wildcard while explicitly managed positions remain exact.

H5F repair status (2026-07-26): complete after implementation, offline
qualification, expanded installed H5E, and clean independent P0/P1 review. The repair closes implicit adoption and
identity-transition seams, makes reconcile selective down to previously
managed coordinates, authenticates and prunes the final expansion-provenance
closure, restores exact non-node source provenance after live snapshots, and
normalizes crash-recovery replay. Durable SQLite replay is now explicitly
24-hour and capacity bounded: at most 256 terminal histories and 256 MiB of
retained JSON, with reserved terminal-transition headroom and no automatic
deletion of pending or `partial_or_unknown` evidence. The offline 34-workflow,
Ruff complexity `12`/branch `15`, compileall, diff, 50-test, and 1,200-line
gates pass without adding a public test.

The repaired H5E run used the installed Houdini 21.0.729 package and hashed 37
critical source/install/runtime modules. It applied distinct newly compiled
second merge and reconcile plans, preserved exact node and non-node provenance
plus referenced expansion stacks after save/reopen, replayed a recovered target
through a reopened SQLite store, and proved expiry, age, count, byte, pending,
partial, and protected-capacity retention behavior including exact `HOCUS759`.
Sixty-seven live node observations recorded zero cooks, and the receipt status
was `passed`.

### H6: Opt-In Project-Scoped MCP Source Workspace

Status: complete and accepted after H6G trust-boundary repair, Windows/Linux publication acceptance, installed Houdini acceptance, the full 40-workflow gate, and clean independent P0/P1 closure review. `HS-BLOCK-001` and `HS-BLOCK-009` are closed for the approved local NTFS/Linux workspace boundary. All seven source operations and their public schemas remain unchanged.

Dependencies: H4, H5, descriptor-safe project access from `HS-BLOCK-001`, MCP permission/audit integration
Houdini required: installed-server validation yes; core path and edit logic no

Authority and configuration:

- the user selects one or more canonical HocusScript project directories in host configuration or an explicit Houdini UI; an MCP request cannot grant itself a new root
- approved projects receive stable opaque `projectId` selectors; a `projectId` is not a bearer capability, and every operation rechecks the current connection/session grant server-side
- MCP exposes only projects authorized to that connection and returns project-relative paths and portable URIs, never physical roots
- access mode is explicit per project (`read_only` or `read_write`), revocable, read-only by default, session-scoped by default, and optionally persisted only by an explicit user choice
- grants separate source read, source write, generated lock update, external-root read, and optional change-notification permissions; broad read-write approval does not silently imply every specialized permission
- external alias roots are separately approved and read-only by default; project approval never implicitly grants external-library access
- `.hocus` and `hocus.project.toml` are authored files; locks, catalog snapshots, compiled bundles, and receipts are generated or specialized-operation outputs rather than raw-edit targets
- host-owned configuration supports server startup/config-file registration and a Houdini approval UI over the same canonical registry; both show the physical root to the user while MCP receives only `projectId`

Minimal MCP surface:

1. `source.project.describe` — list only connection-authorized project identities, manifest/language status, access mode, configured source/module directories, and declared external aliases without returning host roots
2. `source.file.search` — bounded filename/glob and UTF-8 text search over authorized authored files with project-relative matches
3. `source.file.read` — read one or a bounded batch of exact project-relative authored files with raw content digests
4. `source.file.apply_patch` — create exclusively or atomically patch/replace against an exact expected digest; no blind overwrite, raw delete, recursive move, or external-root write in the initial slice
5. `source.file.write_export` — publish an authenticated `document.export_source` handoff through the existing native validation/recompile path with exclusive-create or exact-digest replacement
6. `source.project.build` — invoke one explicit `format`, `check`, `compile`, or `lock_update` action through the existing native APIs and return portable diagnostics, receipts, and exact flat Bundle `0.2`, module Bundle `0.3`, control Bundle `0.4`, or value Bundle `0.5` content for the selected frozen lane; `lock_update` additionally requires explicit write intent, selected entries, the generated-lock grant, approved complete external mapping, and an explicit expected lock state: absent uses exclusive creation without a prior digest, while present requires exact canonical-digest and descriptor-safe raw-digest CAS replacement
7. `source.project.navigate` — expose completion and definition over saved files or supplied dirty buffers, including explicit approved external roots

The current V1 mutation sequence is `source.project.build` with `compile`,
followed by `document.preview_bundle`, `document.plan_bundle`, and
`document.apply_plan`. Preview returns the candidate document, deterministic
diff, destructive summary, and preview-only plan. Planning reruns exact live
validation and persists immutable plan identity, hash, expiry, baseline,
inverse, and drift guards. Apply consumes only that stored plan and rechecks
session, policy, catalog, capabilities, ownership, target, revisions,
confirmation, lease, idempotency, and cancellation before executing and
verifying it across every family declared `supported` by the HS7 matrix.

Read-only MCP resources use `hocus-source://{projectId}` and `hocus-source://{projectId}/{relativePath}` for approved project metadata and authored files. Enumeration and every fetch recheck the current connection grant and authority-projection digest; file digests are cache validators, and revoke, expiry, or a successful write immediately invalidates server-side cached resources. Digest-only change notification is the named optional H6N follow-up after the H6 core exit; it may notify clients of invalidation but does not stream file contents, reveal physical paths, or replace exact-digest checks at write/build time.

Security and correctness batches:

- **H6A authority/configuration:** startup/config-file and Houdini approval surfaces, canonical registry, opaque non-authorizing IDs, server-side connection/session grants, separate read/write/lock/external permissions, revocation, restart behavior, expiry, audit records, and MCP annotations
- **H6B descriptor-safe reads:** handle-based containment/identity checks, file-type and byte limits, portable casing/Unicode/reserved-name policy, symlink/junction/reparse/hardlink escape rejection, and stable-read semantics
- **H6C guarded edits:** exact-digest optimistic concurrency, no-overwrite creation, atomic publication, newline/UTF-8 preservation, manifest-specific validation, recovery from partial client requests, grant binding to an authority-projection digest, mandatory reapproval instead of writing scope-changing manifests, and a distinct authenticated export-handoff path that validates and recompiles before publication
- **H6D compiler/editor composition:** project build, lock, completion, and definition reuse the existing resolver/compiler authorities without duplicating a weaker MCP resolver
- **H6E end-to-end agent loop:** configure project, discover/read resources, patch source, check/compile, preview, plan, apply, verify, export, and reconcile the same native files
- **H6F hostile and installed validation:** traversal, alternate drive, UNC/device, reparse/hardlink swaps, case/Unicode aliases, stale digests, oversized payloads, rate limits, grant expiry/revocation, concurrent edits, scope-widening manifest patches, external-root write attempts, restart, and live Houdini tests; add resource-invalidation tests only when optional notifications ship
- **H6G trust-boundary repair:** prepare, freeze, and size-check the exact public MCP mutation envelope before filesystem changes; establish one terminal commit point under the write-authority lease; bracket captured native identity/digest validation with matching opening/closing project/generated/external path sets; consume one shared 4,096-file/64 MiB budget before every retained read; exhaustively and strictly clean every snapshot resource without masking the primary error; keep create/replacement rollback authority through namespace, content, identity, and durability verification on Linux and Windows; serialize publication/recovery with process plus OS-wide root locks and durable clean/publishing/orphan/recovery states; preserve competing, displaced, and candidate evidence when rollback loses target ownership through one fail-closed root recovery sentinel bounded to one incident, two artifacts, and 24 MiB; durably flush Windows recovery namespaces; make post-commit descriptor cleanup and housekeeping non-masking; use lock-ordered atomic monotonic sliding-window quotas over authorized project scopes with one bounded invalid-selector scope; and advertise build plus `generated_lock` metadata conservatively
- **H6N optional change notification (post-core):** add a separately granted, rate-limited digest-only subscription after H6 exits; prove coalescing, overflow/resync, revoke/expiry shutdown, and no source/path leakage

Default operational budgets are frozen before H6 implementation and may be configured lower, never above the hard ceilings:

| Budget | Default | Hard ceiling |
| --- | ---: | ---: |
| Approved projects per session | 16 | 64 |
| Files returned by enumeration | 1,000 | 4,096 |
| Search matches per request | 200 | 1,000 |
| Files per read batch | 16 | 64 |
| Patch operations per request | 64 | 256 |
| Request/response payload | 2 MiB | 8 MiB |
| Concurrent builds per project/session | 1 / 2 | 1 / 8 |
| Audit events retained per project | 10,000 | 100,000 |

Exit criteria:

- a user can choose the directory where DSL files live, grant scoped MCP access, and revoke it without editing server code
- an agent can complete the normal source-to-Houdini loop without copying entire files through chat or receiving arbitrary filesystem authority
- native editors, Git, and CLI remain fully interoperable because the MCP edits the same ordinary files with digest-guarded writes
- an unapproved path, stale digest, read-only project, external-library write, generated-file raw edit, or changed authority fails before filesystem mutation
- no approved physical root leaks into portable artifacts, diagnostics, plans, resources, logs returned to the client, or durable source identity

Final acceptance evidence (2026-07-27): six H6 public workflows remain inside the 40/50 catalogue and cover authority/restart, hostile descriptor-safe IO, guarded publication, native services, MCP/resources/limits/audit, and installed Houdini source-to-live behavior. H6G adds exact public-envelope preflight, terminal commit semantics, native-identity plus two-pass path-set snapshot authority, incremental closure budgets, exhaustive strict cleanup, bounded durable recovery, process and OS-wide account-scoped publication locks, hostile-environment cross-process contention, mandatory strong Linux root identity, Windows namespace durability, scoped sliding-window limits, and corrected MCP metadata. Windows and Ubuntu 24.04 WSL focused acceptance pass. Ruff with cyclomatic/branch limits 12/15, compileall, diff check, the 1,200-line gate, the full 40-workflow suite, and clean build/install pass. The installed Houdini 21.0.729 receipt proves the exact seven-tool surface, bounded HTTP rejection, Bundle `0.4` patch/build/apply, flat `0.1` export structural recompilation and exact-catalog semantic/connector validation followed by reconcile, native editor/Git visibility without project lock artifacts, revocation denial, source/install/running hash alignment including the publication-lock and recovery-record modules, and zero cooks; it does not establish export network-reconstruction equivalence. Final independent P0/P1 closure review is clean.

Unbounded recursion remains permanently forbidden. Explicitly bounded deterministic compile-time recursion is deferred to a separate reviewed contract covering syntax, termination, identity, provenance, and budgets; it is not part of H0-H6.

The historical safe `0.2` slice was same-project static imports with typed scalar/`node_output` parameters and exports; it is complete through G5 and remains frozen. The current H3 slice adds verified local/mixed resolver, lock-writer, compiler, CLI, whole-AST pinned catalog admission, and native editor dispatch to the H0-H2 language core. H4 qualifies it, H5 connects Bundle `0.4` to the guarded document/live pipeline, and H6 adds explicitly approved project-scoped MCP source access. Recursion remains outside these phases.

## 11. HS7: Network-Family and Value Parity

Status: complete and accepted after the clean installed Houdini family/value
matrix, full 40-workflow qualification, and final independent P0/P1 review

Exact carrier lane: language `0.4`, compiler `0.6.0`, catalog v2,
GraphSpec `0.5`, Bundle `0.5`, expansion-map/resolved-module-set v3, and
network-document v2. Older lanes remain frozen.

Delivered sequence:

1. SOP and OBJ-contained SOP structural networks
2. fixed-port material builders and VOP-like structural networks
3. LOP/Solaris structural networks, with direct USD layer/relationship/variant
   and time-sample authoring explicitly rejected
4. TOP/PDG structural graphs without scheduler/work-item execution
5. ROP, DOP, COP, and CHOP evaluated and retained as read-only
6. HDA definition authoring rejected pending a separate stronger contract

Value and graph parity includes:

- exact named and multi-output ports with index authority
- tuples, menu tokens, quantities, raw paths, and explicit/default resets
- float/color ramps and bounded multiparms
- fixed-language expressions and structural channel references
- ownership-scoped managed instance spare parameters
- seconds-based scalar numeric keyframes; USD time samples rejected
- catalog-declared code blobs; callbacks and buttons rejected as actions
- network boxes, routed dots, sticky notes, comments, and deterministic layout
  constraints
- locked-HDA internal and HDA-definition boundaries

Exit criteria:

- a published support matrix labels every feature supported, preserved-opaque, read-only, or rejected
- no network family claims parity without a live test matrix
- exported source structurally recompiles and passes exact-catalog semantic and
  connector validation for every supported construct, without a
  network-reconstruction guarantee

Final acceptance (2026-07-27): complete. The source, catalog, carrier,
semantic, document, guarded-plan/apply, reconcile, rollback, export, and
machine-readable matrix paths are implemented. The catalogue remains 40/50
public scenarios. The full 40-workflow run, Ruff cyclomatic/branch limits
`12`/`15`, compileall, all JSON schemas, diff check, clean build/install, and
the 1,200-line gate pass.

Installed Houdini 21.0.729 accepted SOP, fixed-port material/VOP, LOP, and TOP
create/reconcile/rollback/save-reopen/export flows; rejected nested/dynamic
ports, unsupported families, direct USD time samples, and a disposable locked
HDA boundary; and retained ROP/DOP/COP/CHOP as read-only. The extension matrix
accepted graph-editor entities, managed spares/keyframes, tagged values,
artist-state preservation, exact default reset, structural export recompilation
and exact-catalog semantic/connector validation, and injected rollback. All managed descendants
recorded zero cooks. Seventy-nine critical
runtime-module receipts matched the source, installed package, and running
modules.

Qualification found and repaired nonzero network-dot input decoding,
editor/runtime diff omissions, cross-ownership runtime reconcile, real HOM
extrapolation enum mapping, nested box membership flattening, HOM
editor-wrapper identity drift, language-`0.4` direct-root identity,
complete tagged-value export, managed runtime observation pruning,
float32-ramp overflow handling, and composite-child snapshot normalization.
Final independent P0/P1 closure review is clean.

## 12. HS8: Production and AAA Hardening

Implementation status: the repaired governed payload passes a fresh
two-process same-host technical qualification on Houdini 21.0.729. Its current
technical receipt is
`sha256:5063c88c876822b595d44eafcb25cb43f6b04b78a59424d0a9ebc6f9b0a3a266`,
with portable evidence
`sha256:9f2d771da3de3d136f6da60fb415a2886e6260384e41e639aa0f05f37bbf0683`,
installed manifest
`sha256:8a835f7af6275fe235aa9c01a418466a8d71fe21dbb5930268e1cbd6e239b703`,
and normalized USDA
`sha256:15b2e0961ef43667707fabde87f6bb2517afd44c825818770476b7cfcc609149`.
Both processes accepted with zero cook warnings/errors, and an identical
second install preserved the token and activation bytes. This is same-host
technical evidence only; RC1 clean-commit evidence and the RC2 source freeze
remain pending. The older same-host receipt
`sha256:e4e0f745421dabee7c4c9c576ee2df3390a19101a13422ee18e6afca87f73591`
is historical because its observer could accept fallback-derived USD,
material, delivery, dependency, and platform facts and its installed receipt
covered an incomplete runtime closure. The later repaired Houdini 21.0.729
two-process technical receipt, also historical, is
`sha256:c21b1a7b2f09fe8f95d72c84f1c2440bb2e2c4b7dd2852268df762d29259e698`,
with portable evidence
`sha256:a863daa8b159603470cc5fddee87dcb38feb1dce73eca51ea77ff162968041ee`
and installed manifest
`sha256:71b5817d66a13167e599beec921ba8696400d42900b9e006824d21b9333252b7`.
External human visual review and externally authenticated clean-image/VM
acceptance remain separate open gates, so release authority remains false.

### 12A. V1 release-closure program

The detailed closure sequence is
`docs/hocusscript-roadmap-completion-plan.md`. It separates the accepted
technical product from the external evidence needed for release:

1. RC0 reconciles stale roadmap/tracker state.
2. RC1 completes performance, compatibility, hostile-boundary, migration,
   effective package-search, and detached external-evidence tooling while the
   tree is still mutable.
3. RC2 freezes the exact source/install candidate once and binds final internal
   receipts to it.
4. RC3 obtains externally authenticated clean-image/VM qualification.
5. RC4 obtains a detached human visual approval and external release
   qualification for the unchanged RC2 candidate.
6. RC5 publishes the exact candidate and moves nonblocking work to post-v1.

Environment, multi-variant USD, destruction/simulation, 10k-node scale,
broader connector/variadic fidelity, conflict-policy annotations, and new
language syntax do not block the current fail-closed V1 claim.

Objectives:

- define enforceable asset contracts
- add deterministic clean-machine rebuilds and provenance manifests
- add geometry, topology, UV, material, LOD, collision, USD, dependency, and platform-budget validation
- integrate viewport captures, turntables, contact sheets, render comparison, and version review
- record cook timing, memory, polygon, texture, and publish metrics
- protect artist-owned overrides and resolve live/source conflicts
- integrate CI, packaging, and publishing

Reference fixtures:

- implemented: one material-aware procedural rock family with UVs, two LOD
  groups, collision, packed instancing, protected artist state, and a USD
  assembly
- future coverage reference: one procedural environment kit
- future coverage reference: one destruction or simulation setup
- future coverage reference: a multi-variant USD assembly

Exit criteria:

- at least one substantial asset rebuilds deterministically in same-host fresh
  processes and in an externally established clean image or VM
- generated LOD, collision, UV, material, and publish outputs meet declared contracts
- visual and numeric regression reports are produced
- a human artist can edit protected regions without source apply erasing them
- pipeline provenance identifies source, compiler, catalog, modules, HDAs, inputs, and outputs

Implemented HS8 boundaries:

- one strict content-addressed asset contract and exact live observation model
- deterministic recipe/source/compiler/catalog/module/HDA/input/output manifests
- canonical metrics, platform budgets, repeated-build/numeric/visual comparison,
  packaging receipts, and publish receipts
- one read-only, non-idempotent `production.asset.qualify` operation; content-only
  requests retain advisory raw gate decisions but both actionable readiness
  flags remain false even with `review_production`; only the private installed
  runner and detached verifier can establish authority
- deterministic headless four-view contact sheets plus a separate review-request
  carrier; the harness cannot create its own approval
- historically accepted installed-only same-host runner and an evidence-only clean-image/VM
  wrapper that cannot confer release authority; authenticated detached
  approval/attestation ingestion remains pre-freeze RC1 work
- 43 public scenario tests total, leaving seven slots below the 50-test ceiling

## 13. Cross-Cutting Workstreams

### Testing

- offline unit, golden, property, fuzz, and security suites
- fake backend and fake catalog
- live Houdini GUI and headless matrices
- save/reload and external-edit races
- performance and payload budgets
- explicit native project selection, relocation, traversal, symlink/junction escape, bundle portability, and offline/MCP boundary tests
- H5 local/mixed Bundle `0.4` control workflows across preview, immutable plan, apply, rollback, save/reload, export, and diagnostic provenance
- H6 approval, scope separation, revocation/expiry, descriptor-safe containment, hardlink/reparse races, optimistic concurrency, scope-widening manifest rejection, generated-file protection, audit, and rate-limit tests; resource-invalidation tests apply only if optional notifications ship

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
- H5 content-to-document/live workflow, compatibility matrix, provenance behavior, and recovery guide
- H6 host configuration and Houdini approval guide covering project roots, opaque identities, read/write/lock/external/watch grants, persistence, revocation, audit, and the edit-to-live agent workflow
- production asset examples
- support matrix and known limitations

### Observability

- parse, resolve, lower, diff, plan, apply, verify, and rollback timings
- source-to-operation audit linkage
- plan lifecycle and idempotency state
- conflict and catalog-drift diagnostics
- H6 authority grant/revoke/expiry events plus project-scoped read, patch, build, navigation, resource-invalidation, and denial telemetry without physical paths or source contents

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

Status: resolved and accepted by H6G plus clean independent closure review

H6 uses pinned root and contained-file handles on supported local NTFS/Linux filesystems, rejects unsupported/network/removable/reparse/link-count states, and verifies containment, final identity, casing, Unicode, and raw digests. Linux uses beneath/no-follow descriptor-relative operations, mandatory nonzero inode generation, and atomic exchange rollback. Windows holds reparse-inspected, no-delete-sharing guards over every namespace component during publication, uses atomic displaced-object backup semantics, validates the object actually replaced, and restores that exact object on conflict. Deterministic root/component/target swap, reparse/symlink, hardlink, stale-content, rollback, recovery, cross-process contention, and project-artifact scenarios pass on Windows and Ubuntu 24.04 WSL. Operations fail closed when the platform cannot provide the required semantics.

The older pathname-based native CLI APIs retain their same-user compatibility signatures and limitations. H6 does not route trusted workspace operations through them: its internal file-provider and safe publisher abstractions own the stronger hosted boundary.

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

Status: resolved for language `0.4`, GraphSpec `0.5`, and Bundle `0.5` by HS7;
all earlier compatibility rows remain frozen and fail-closed

Catalog v2 and Bundle `0.5` retain the exact ordered component-token mapping
required to lower whole tuples into scalar document bindings. Relocation,
live reimport, reset, rollback, and structural export recompilation plus
exact-catalog semantic/connector validation evidence is accepted in
HS7. Language `0.1` / Bundle `0.2` continues to reject whole tuples with
`HOCUS708`; the frozen language `0.2` / Bundle `0.3` and language `0.3` /
Bundle `0.4` rows likewise gain no whole-tuple syntax or carrier semantics.

### HS-BLOCK-006: Explicit Source Entity IDs Across Symbol Renames

Status: resolved in HS5

Optional `@id("...")` source identity now maps directly to persistent network-document node UIDs and survives source-symbol and export-destination changes. Duplicate, invalid, or path-colliding explicit IDs block structurally; omitted IDs retain deterministic graph/source/local-symbol derivation. Compiler, bundle, schema, lowering, exporter, golden, symbol-rename, collision, and live round-trip coverage preserve the rule that path and session IDs are not substitutes for durable identity.

### HS-BLOCK-007: Real Live Export Identity and Managed-Field Reconstruction

Status: resolved in HS5 independent review

The first export smoke used a normalized projection and therefore did not prove the registered endpoint against actual root category/default parameter state. The corrected implementation accepts `/obj` as the SOP container while requiring `persistent_user_data` identity for the root anchor and every exported child. Signed per-node `managedFields` survive Houdini user data; live reimport reconstructs ownership on derived bindings, code blobs, data edges, and output edges. Root/default/artist-owned fields are omitted from source and enumerated as `preservedState`, so they remain baseline-preserved merge state rather than being silently promoted to portable source ownership. The final H21.0.729 smoke calls the registered handler over the unmodified force-synced document.

### HS-BLOCK-008: Bundle 0.3/0.4 Diagnostic and URI Parity Before Live Acceptance

Status: resolved and accepted by repaired installed H5E plus clean independent review

The strict Bundle `0.3` decoder rejects host-path diagnostic URIs, invalid or
out-of-origin spans, duplicated expansion frames, and offline
live-path/entity claims. Bundle `0.4` additionally authenticates
module/control provenance and GraphSpec `0.4`; its decoder rejects every
GraphSpec span whose source URI is absent from the authenticated
entry/dependency set and enforces the GraphSpec-derived minimum capability
set. H5A closed the carrier-side gaps: both lanes now use exact-version
admission, Bundle `0.3` uses the native Unicode NFC/Windows-reserved portable
URI rules throughout, module/control stack references remain carrier
validated, and source positions are explicitly classified as authenticated
display hints rather than source-byte-attested coordinates. H5C now freshly
re-resolves semantic selections, capabilities, and exact catalog identities
against the running Houdini catalog while preserving the authenticated
carrier's conservative capability manifest. H5D composes that gate into the
exact-version preview/plan/apply paths with durable module/control provenance,
exact pins, cancellation, verification, and rollback. Unsupported, malformed,
mixed, or drifted artifacts remain fail-closed with typed diagnostics. The
repaired installed H5E proved the exact-version local/mixed workflow matrix,
diagnostic locations, fresh live semantics, distinct second reconcile,
durable provenance, and reopened-store recovery; final independent review was
clean, so the blocker is accepted. Complete effective Houdini
package-search provenance remains separately excluded under `HS-BLOCK-003`.

### HS-BLOCK-009: MCP Project Workspace Authority

Status: resolved and accepted by H6G plus clean independent closure review

One canonical host-owned registry now serves startup configuration and the Houdini Source Workspaces UI. Random stable `projectId` selectors are non-authorizing; authenticated `Mcp-Session-Id` sessions, principal-bound persistence, projection-bound grants, expiry, revocation, generation invalidation, separate read/write/generated-lock/external permissions, path-free audit, and context-filtered resources are enforced on every source operation. Manifest/root identity drift requires reapproval, and publication holds a linearizable authority lease through the terminal commit. Final installed Houdini acceptance proves restart, limits, exact path-free responses, cache invalidation, revocation denial, Git-visible source edits without project lock artifacts, and the complete source-to-live loop. No general filesystem operation or self-authorizing root parameter exists. Optional digest-only notifications remain H6N follow-up work.
