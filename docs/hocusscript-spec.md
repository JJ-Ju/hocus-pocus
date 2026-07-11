# HocusScript Language and Compiler Specification

Status: experimental design contract
Language version: `0.1`
File extension: `.hocus`

## 1. Purpose

HocusScript is a deterministic, TypeScript-shaped source language for authoring Houdini node networks through HocusPocus.

It is a custom declarative language, not TypeScript or JavaScript. HocusScript source is parsed as inert data and never evaluated by a JavaScript runtime.

The normal authoring flow is:

```text
HocusScript source
  -> span-bearing syntax tree
  -> typed AST
  -> resolved GraphSpec
  -> canonical network-document IR
  -> immutable apply plan
  -> guarded HOM execution
  -> scoped reimport and verification
```

The existing network-document contract remains the canonical backend and interchange representation. HocusScript is the concise, source-controlled authoring surface above it.

The terms MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are normative.

## 2. Goals

HocusScript MUST:

- make Houdini graphs practical to author and review as text
- use symbolic names instead of repeated Houdini paths
- preserve source locations through compilation and application
- compile deterministically for fixed source, catalog, inputs, and compiler versions
- resolve operators, parameters, ports, HDAs, and code surfaces against a fingerprinted Houdini catalog
- coexist safely with artist-authored live nodes
- lower through the document compiler rather than bypassing it
- expose the expanded graph, diff, capabilities, and destructive effects before mutation
- support source control, formatting, offline syntax checks, and future editor integration
- remain network-family-neutral even though implementation begins with SOP networks

## 3. Non-Goals

HocusScript is not:

- a reimplementation of HOM, VEX, Python, HScript, USD, or PDG
- a general-purpose programming language
- an executable TypeScript or JavaScript dialect
- a replacement for Houdini's network editor or direct artist editing
- a mechanism for silently executing cooks, renders, button presses, filesystem writes, or publishing during graph apply
- a promise of immediate lossless support for every Houdini network family
- by itself a guarantee of artistic or AAA quality

Imperative actions such as cooking, rendering, exporting, caching, and publishing remain explicit task tools after structural graph application.

## 4. Contract Boundaries

### 4.1 Source

Human- and agent-authored `.hocus` text. Source formatting and comments are preserved by the concrete syntax representation where practical.

### 4.2 Typed AST

The parsed representation. Every declaration, statement, expression, and reference carries a source span.

### 4.3 GraphSpec

A compact, normalized, source-mapped graph intent model. It contains symbolic identities and authored values but not live Houdini mutation instructions.

GraphSpec preview version `0.1` uses schema URI `hocuspocus://schemas/graph-spec/v0.1` and this logical shape:

```json
{
  "$schema": "hocuspocus://schemas/graph-spec/v0.1",
  "kind": "graph_spec",
  "graphSpecVersion": "0.1",
  "languageVersion": "0.1",
  "name": "rocks",
  "target": "/obj/geo1",
  "category": "Sop",
  "mode": "merge",
  "expectedRevision": 42,
  "ownership": "studio.environment.rocks",
  "externalNodes": [],
  "nodes": [],
  "display": null,
  "render": null,
  "output": null,
  "layout": "auto",
  "span": {}
}
```

Nodes contain ordered `inputs` and `parms`; external nodes declare `symbol`, `path`, and `adopted`. The completed model carries spans on literals, arrays, code, references, statements, and entities. Preview `0.1` currently carries spans on graph entities, references, assignments, and values while a separate syntax AST and singleton-statement spans remain HS1 work.

Canonical GraphSpec serialization uses UTF-8, sorted object keys when hashed, source order for declaration arrays, explicit nulls, finite JSON numbers, and no insignificant whitespace in the hashed form. Compiler responses declare both `compilerVersion` and `graphSpecVersion`. Incompatible shape changes require a new GraphSpec version and schema URI.

### 4.4 Network Document

The canonical versioned graph IR defined by `hocuspocus://schemas/network-document/v1`. The compiler generates document IDs, entity IDs, paths, bindings, edges, code blobs, metadata, and defaults.

### 4.5 Apply Plan

An immutable, server-stored ordered plan derived from one source digest, GraphSpec, catalog fingerprint, baseline revision, policy decision, and compiler version.

No public source-authoring path may mutate Houdini without passing through all five boundaries.

## 5. Source Units

- Source encoding MUST be UTF-8.
- LF and CRLF input are accepted; canonical formatting emits LF.
- A strict source unit MUST contain one version declaration and exactly one graph in language version `0.1`.
- Canonical files begin with `hocus 0.1;`.
- `compile_source(strict = false)` MAY accept a missing header for interactive preview, but MUST emit warning `HOCUS101`, assume `0.1`, and format the result with an explicit header. Strict mode is the default for library and MCP compilation and treats `HOCUS101` as an error.
- Semicolons are required after simple statements in `0.1`.
- Identifiers are ASCII in `0.1`: `[A-Za-z_][A-Za-z0-9_]*`.
- Operator names that contain namespaces, versions, punctuation, or spaces MUST use strings.
- `//` line comments and non-nested `/* ... */` comments are supported.
- Numbers are finite decimal integers or floats. `NaN` and infinity are forbidden.
- Strings use JSON-compatible double-quoted escapes.

Default compiler limits:

| Limit | Default |
| --- | ---: |
| Source bytes | 1 MiB |
| Tokens | 250,000 |
| AST depth | 128 |
| Nodes per graph | 10,000 |
| Diagnostics | 500 |
| Embedded code block | 256 KiB |

The server MAY configure lower limits and MUST return a structured limit diagnostic.

### 5.1 Native Project and File Surface

HocusScript files are ordinary source-code files. Agents and users read, edit, search, diff, rename, and version `*.hocus`, `hocus.project.toml`, and `hocus.lock.json` through their native editor, workspace, and filesystem tools. The Houdini MCP server is not the primary file editor, project registry, or source-file reader.

The user-selectable project directory belongs to the offline compiler/editor configuration. The initial native command accepts it explicitly through `--project`; editor settings and `HOCUS_PROJECT_DIRECTORY` MAY provide the same value later. No Houdini MCP setting is required to edit or compile project files.

```text
native editor or agent filesystem
    -> offline HocusScript compiler/formatter
    -> content-addressed compiled bundle
    -> Houdini MCP preview/plan/apply
```

Project rules:

- The offline compiler receives an explicit project directory and resolves it to a canonical absolute directory. It does not infer a project from the Houdini hip file, `$HIP`, the package repository, or the Houdini MCP process.
- `hocus.project.toml` defines `schema_version`, a stable project `uid`, an optional display `name`, relative `source_directories`, catalog constraints, lock policy, formatting, and project metadata. `source_directories` defaults to `["."]`.
- The project UID uses lowercase ASCII letters, digits, dots, and hyphens, starts with a letter or digit, and is at most 128 characters.
- `hocus.lock.json` records schema/compiler constraints, catalog fingerprint, external module URI/version/digest, and transitive dependency digests without absolute machine paths or secrets.
- Source paths and import paths are project-relative and contained after canonical resolution. Absolute source paths MAY be accepted by a native CLI for ergonomics only after proving containment in the explicit project directory.
- Source and export-source files use the `.hocus` suffix. Manifest, lock, catalog, and compiled-bundle files use their own declared formats.
- The physical project root never participates in durable source or node identity. A canonical source URI uses the manifest UID plus percent-encoded project-relative path, for example `hocus-project://city-environment/hocus/rocks.hocus`.
- A missing manifest is allowed for parsing, checking, and formatting. Such output uses preview-only workspace provenance and cannot become an applyable plan. A valid stable manifest UID is required for a portable compiled bundle that can proceed to Houdini planning.
- Native file reads are bounded and UTF-8 only. Traversal, out-of-project paths, invalid manifests, oversized sources, invalid UTF-8, and changed inputs produce typed diagnostics.

Initial manifest shape:

```toml
schema_version = 1

[project]
uid = "city-environment"
name = "City Environment"
source_directories = ["hocus", "modules"]
```

The offline compiler emits a deterministic, content-addressed compiled bundle containing at least:

- bundle, language, compiler, GraphSpec, and source-map versions
- stable project UID and manifest/lock digests when available
- entry source URI/digest and ordered dependency URIs/digests
- normalized GraphSpec and source maps
- catalog constraints and required capabilities
- a bundle digest computed over canonical serialized content

Absolute physical paths are excluded from portable bundle identity and payloads. Relocating a project preserves source and bundle identity when its manifest UID, relative paths, contents, compiler inputs, and locks are unchanged.

The Houdini boundary is content-based. The shared standard-library `decode_compiled_bundle()` trust boundary validates exact fields, supported versions, canonical digest, bounded complexity, finite values, portable provenance, source/dependency records, source maps, GraphSpec envelope consistency, and capabilities derived from graph content. It never reads paths or Houdini state. Source bytes are not embedded, so the decoder validates the integrity of source-digest claims, not their external authenticity.

MCP progression:

- `document.compile_source` remains an optional compatibility/convenience endpoint for unsaved source text. It never accepts a project directory or reads a path.
- HS3 `document.preview_bundle` will accept compiled bundle content through `decode_compiled_bundle()`, resolve it against the current Houdini catalog/baseline, and return a non-mutating diff and candidate plan.
- `document.plan_bundle` MAY persist an immutable guarded plan after all HS4 gates pass.
- `document.apply_plan` accepts only a stored plan identity, not source paths or arbitrary source text.
- `document.export_source` returns source text plus provenance. The native editor/CLI owns writing it to a chosen `.hocus` file.

There is no primary `document.compile_file`, `document.open_project`, MCP project registry, or general project-file read capability. A Houdini-local UI MAY later wrap the offline compiler as a convenience, but it must preserve this boundary.

## 6. Version 0.1 Grammar

The normative initial grammar is:

```ebnf
source          = versionDecl, graphDecl, EOF ;
versionDecl     = "hocus", version, ";" ;
version         = integer | float | string ;

graphDecl       = "graph", identifier, "{", { graphStatement }, "}" ;
graphStatement  = targetStmt
                | categoryStmt
                | modeStmt
                | revisionStmt
                | ownershipStmt
                | existingDecl
                | adoptDecl
                | nodeDecl
                | flagStmt
                | layoutStmt ;

targetStmt      = "target", [ "=" ], string, ";" ;
categoryStmt    = "category", [ "=" ], identifier, ";" ;
modeStmt        = "mode", [ "=" ], ( "merge" | "reconcile" ), ";" ;
revisionStmt    = "expect", [ "revision" ], [ "=" ], integer, ";" ;
ownershipStmt   = "ownership", [ "=" ], string, ";" ;

existingDecl    = "existing", identifier, "=", string, ";" ;
adoptDecl       = "adopt", identifier, "=", string, ";" ;

nodeDecl        = "node", identifier, ":", typeName,
                  "{", { nodeStatement }, "}" ;
typeName        = identifier | string ;
nodeStatement   = inputStmt | parmStmt ;
inputStmt       = "input", "[", integer, "]", "=", nodeOutput, ";" ;
parmStmt        = identifier, "=", value, ";" ;

nodeOutput      = identifier,
                  [ ".", ( "out" | "output" ), "[", integer, "]" ] ;
flagStmt        = ( "display" | "render" | "output" ), "=", identifier, ";" ;
layoutStmt      = "layout", "=", "auto", ";" ;

value           = string | integer | float | boolean | null
                | array | taggedCode ;
array           = "[", [ value, { ",", value }, [ "," ] ], "]" ;
taggedCode      = ( "vex" | "python" | "hscript" ), rawTemplate ;
```

`rawTemplate` begins with a backtick and ends at the next unescaped backtick. `\`` represents a literal backtick. All other characters are inert and retained. Canonical formatting normalizes line endings to LF and re-escapes literal backticks without evaluating or interpolating the body.

The parser MUST reject imports, functions, runtime loops, dynamic property access, arbitrary calls, JavaScript expressions, and executable host-language constructs in `0.1`.

## 7. Example

```ts
hocus 0.1;

graph rocks {
  target "/obj/geo1";
  category Sop;
  mode merge;
  expect revision 42;
  ownership "studio.environment.rocks";

  existing ground = "/obj/geo1/OUT_GROUND";

  node scatter: "scatter" {
    input[0] = ground.output[0];
    npts = 2500;
    globalseed = 17;
  }

  node tint: "attribwrangle" {
    input[0] = scatter.output[0];
    snippet = vex`
      @Cd = rand(@ptnum);
    `;
  }

  display = tint;
  render = tint;
  layout = auto;
}
```

## 8. Graph Semantics

### 8.1 Target and Category

- `target` is required and MUST resolve to an absolute Houdini network path.
- `category` is optional in `0.1`; if present, it constrains catalog resolution.
- The root network is context, not an authored child node.

### 8.2 Modes

- `merge` is the default and preserves unspecified live entities.
- `reconcile` is forbidden without an explicit ownership namespace.
- Reconcile may delete or reset only entities carrying the exact matching ownership identity.
- Unowned nodes, artist-owned nodes, nodes owned by another source, locked HDA contents, and nodes outside the target scope MUST be preserved.
- A destructive summary and threshold decision MUST be produced before apply.

### 8.3 Existing and Adopt

- `existing` creates a read-only external graph reference. It never grants deletion or parameter ownership.
- In `0.1`, existing/adopt paths MUST be canonical paths inside the target network document. Cross-document references require a future explicit import/reference form.
- `display`, `render`, and `output` are managed mutations and MUST NOT target a read-only `existing` symbol. The node must be compiler-created or explicitly adopted.
- `adopt` requests ownership of an existing node. Adoption MUST be visible in the diff, policy-gated, and confirmed when required.
- Path collisions with live nodes that are neither declared `existing` nor `adopt` are compilation errors.
- Future versions will add `detach` and `relinquish` without deletion.

### 8.4 Artist Overrides and Conflicts

- Compiler-created nodes are entity-owned by their ownership namespace.
- In merge mode, only explicitly authored inputs, parameters, code surfaces, and flags are field-managed. Unauthored fields remain artist-managed.
- `existing` manages no fields. `adopt` transfers entity ownership but initially manages only fields explicitly authored in source.
- Removing a field assignment in merge mode relinquishes field management and preserves the current live value.
- Removing an owned field assignment in reconcile mode resets it only when stored ownership metadata proves that field was compiler-managed.
- A live edit to a managed field after the plan baseline is a conflict. The default policy is reject and recompile; source never silently wins.
- Future explicit annotations may request `preserve_live` or `source_wins` for selected fields, but no implicit overwrite policy is permitted.
- Protected artist nodes or fields are never deleted, reset, adopted, or overwritten without an explicit policy transition and visible confirmation.

### 8.5 Nodes

- A node symbol is unique within its graph and module expansion scope.
- The operator string is resolved against the catalog; it is not silently upgraded.
- Unqualified operator names compile only when resolution is unambiguous.
- Node paths are projections from target, requested name, and identity. Paths are not identity.

### 8.6 Inputs and Outputs

- Both destination input index and source output index are semantically significant.
- Named ports are reserved for the next compatible language minor.
- Variadic inputs preserve explicit ordering and gaps.
- A connection is legal only if the catalog declares compatible categories and ports.
- An implementation MUST NOT collapse nonzero source outputs to output zero.

### 8.7 Parameters

- Parameter names resolve against exact catalog parameter tokens, not UI labels.
- Scalar-to-tuple coercion is forbidden unless the catalog explicitly declares it.
- Menu values use stable tokens rather than localized labels.
- Parameter defaults are distinct from explicit values.
- Button parameters, callbacks, and other actions are not ordinary assignments.

The AST and GraphSpec reserve first-class forms for tuples, ramps, multiparms, expressions, channel references, keyframes, time samples, units, and resets. Unsupported forms MUST produce diagnostics rather than be approximated or discarded.

### 8.8 Code Blocks

- `vex`, `python`, and `hscript` templates are inert text during parsing.
- Compilation MAY syntax-check code without executing it.
- Installing or changing code requires the `run_code` capability in addition to scene-edit capability.
- Code blocks retain their source offset so embedded diagnostics map to the `.hocus` file.

## 9. Planned Type System

The planned complete language type model includes:

- `Bool`, `Int`, `Float`, `String`, and `Null`
- typed arrays and records
- `Vec2`, `Vec3`, `Vec4`, colors, matrices, and quaternions
- enum/menu tokens
- distance, angle, time, and frame units
- `NodeRef<Category>`, `InputRef`, `OutputRef`, and `ParmRef<T>`
- Houdini node paths, parameter paths, filesystem paths, USD prim paths, and asset references as distinct types
- ramps and multiparms
- expressions and structural channel references

Language `0.1` exposes only scalars, arrays, node references, indexed ports, and tagged code. The richer types are reserved now so the GraphSpec does not need an incompatible redesign.

## 10. Catalog Contract

A catalog snapshot MUST include:

- Houdini product, build, platform, and relevant feature flags
- node category and fully qualified operator name
- operator namespace and definition version
- HDA library identity and content digest
- parameter tokens, tuple shapes, types, defaults, ranges, menus, tags, and code-surface classification
- spare-parameter policy
- named and indexed input/output connectors and cardinality
- locked/editable state and supported network families
- installed package and Labs versions when relevant

Catalog resolution rules:

1. An exact fully qualified match wins.
2. An alias or unqualified name must resolve to one compatible definition.
3. Ambiguity is an error with ordered candidates and a fix-it.
4. Compilation records the selected definitions and catalog fingerprint.
5. Apply rechecks the fingerprint and refuses silent drift.
6. Offline compilation uses a pinned catalog snapshot and lockfile.

## 11. Identity and Ownership Metadata

Every compiler-managed entity MUST have a durable UID independent of Houdini session ID, name, and path.

- Explicit IDs are reserved through future `@id("...")` syntax.
- Default IDs derive from ownership namespace, graph identity, module instance path, and local symbol.
- Managed Houdini nodes are stamped with at least `hpmcp.uid`, `hpmcp.owner`, source URI, graph/module identity, and compiler version.
- Duplicate UIDs caused by copy/paste are detected and repaired only through an explicit conflict policy.
- IDs survive rename, reparent, save/reload, and ordinary source formatting changes.

Source maps link:

```text
source span
  <-> AST node
  <-> GraphSpec pointer
  <-> network-document entity UID
  <-> apply operation
  <-> resulting Houdini path
```

## 12. Diagnostics

Every diagnostic has this stable logical shape. Later-phase locations are nullable until that phase creates them:

```json
{
  "severity": "error",
  "code": "HOCUS301",
  "phase": "semantic",
  "message": "Unknown symbol: groun",
  "sourceUri": "hocus-project://city-environment/hocus/rocks.hocus",
  "span": {
    "start": {"line": 12, "column": 16, "offset": 220},
    "end": {"line": 12, "column": 21, "offset": 225}
  },
  "related": [],
  "notes": [],
  "fixes": [],
  "expansionStack": [],
  "jsonPointer": null,
  "entityUid": null,
  "houdiniPath": null,
  "details": {"candidates": ["ground"]}
}
```

Rules:

- Lines and columns are one-based; offsets are zero-based Unicode code-point offsets in `0.1`.
- Codes are stable across compatible compiler releases.
- Diagnostics sort by source URI, start offset, severity, then code.
- Parser recovery SHOULD report multiple independent errors without cascading indefinitely.
- Safe fix-its use explicit source edits.
- Module expansion stacks and embedded-code offsets are preserved.
- Truncation emits a final diagnostic declaring how many were omitted.

## 13. Determinism and Versioning

Compilation is deterministic only when all inputs are pinned:

- HocusScript language and compiler versions
- GraphSpec and network-document schema versions
- catalog fingerprint and Houdini build
- HDA, package, Labs, and module versions
- source and transitive module digests
- input asset identities and relevant content digests
- explicit random seeds, frame/time, units, and environment inputs

For identical pinned inputs, canonical GraphSpec, document, plan, and hashes MUST be byte-identical.

Separate versions exist for the language, compiler, GraphSpec, document schema, apply-plan schema, catalog, modules, and graph-store database. Plans are not portable across mismatched session, catalog, compiler, or baseline revisions.

Major language versions may break syntax or semantics. Minor versions are backward compatible. Unsupported newer syntax is rejected rather than guessed. A future `hocus migrate` command will perform explicit source upgrades.

## 14. Compile and Apply Contract

### 14.1 `document.compile_source`

Input:

```json
{
  "source": "hocus 0.1; graph ...",
  "source_name": "rocks.hocus",
  "strict": true,
  "expected_document_revision": 42,
  "catalog_fingerprint": "sha256:...",
  "warnings_as_errors": false
}
```

The compatibility tool remains at `stage = structural`: syntax, structural diagnostics, canonical formatting, source digest, compiler/GraphSpec versions, and a span-bearing GraphSpec. `readyForDocumentLowering` and `readyForApply` remain false. HS3 and HS4 progression occurs through `document.preview_bundle` and `document.plan_bundle`, not by giving this tool filesystem responsibilities.

The fully resolved compiler returns:

- language/compiler/IR versions
- source digest and formatted source
- diagnostics and validity
- normalized GraphSpec
- resolved catalog fingerprint and operator selections
- capability manifest
- baseline document/live revisions
- generated canonical document
- graph diff and destructive summary
- immutable `planId`, `planHash`, and expiry when all gates pass

Compilation never mutates Houdini.

For `document.compile_source`, `source` is required and provenance is `hocus-memory://`; it cannot read a path or create an applyable plan. Durable project provenance comes from the offline compiler bundle.

### 14.2 Future `document.preview_bundle` and `document.plan_bundle`

HS3 `document.preview_bundle` accepts a canonical compiled-bundle object, passes it through the shared strict decoder, then performs live catalog resolution and diff preview without filesystem access or mutation. It is not registered during HS1P because bundle integrity validation alone is not a Houdini-aware preview. Imports are resolved by the offline compiler when the active language version supports them.

`document.plan_bundle` stores an immutable plan only after catalog, ownership, policy, revision, and fidelity gates pass. A bundle containing preview-only workspace provenance cannot produce a stored plan.

### 14.3 `document.apply_plan`

Input contains only:

- plan ID and plan hash
- expected document/live revision
- optional confirmation token
- idempotency key

Apply MUST:

1. acquire a target-network write lease
2. validate plan identity, TTL, session, catalog, revisions, ownership, policy, and capabilities
3. reject tampering or drift without recompiling
4. execute reversible structural operations in one guarded undo scope
5. reimport only the affected network scope
6. verify intended effects and protected-state preservation
7. commit the document/store revision and audit record
8. return a true success or true typed failure

Large plans MAY become cancellable tasks.

## 15. Rollback and Recovery

- Apply plans exclude irreversible actions.
- A pre-apply scoped snapshot and inverse plan are recorded.
- Failure triggers guarded inverse execution or an apply-owned undo record.
- Rollback is reimported and verified.
- A failed rollback returns `partial_or_unknown`, quarantines the scope, and requires explicit resync or recovery.
- Store commits use pending, committed, and aborted states.
- Client timeout and retry behavior are controlled by idempotency keys.
- The implementation MUST NOT claim general atomicity while relying only on an unqualified global undo.

## 16. Modules and Imports

Modules are planned for a later language minor. They will provide typed parameters, hygienic local symbols, explicit exports, pure deterministic expansion, bounded expansion, source maps through expansion, and a transitive lockfile.

Modules MUST NOT provide:

- dynamic imports
- filesystem, process, network, environment, clock, or random access
- reflection over the host process
- unbounded loops or recursion
- hidden mutation

Imports first resolve relative to the importing source file, then through ordered project `source_directories`/module roots. Every native compiler result must remain inside the explicit project directory unless a manifest-declared external module is independently locked. Paths are canonicalized with symlink-aware containment checks. Module URIs, stable project UID, versions, and content hashes are recorded in the bundle and plan.

## 17. Formatting, Export, and Round-Trip

- The formatter emits canonical whitespace, ordering, quoting, and LF newlines.
- Language `0.1` accepts comments, but the initial token stream discards trivia and canonical formatting does not preserve comments. A comment-preserving concrete syntax tree is a later HS5 deliverable.
- Formatting is idempotent.
- Live graphs can be exported to normalized HocusScript when all relevant constructs are supported.
- Unsupported entities are rejected or represented explicitly as opaque preserved constructs; they are never silently dropped.
- The semantic guarantee is `compile(export(network))` equivalence for supported features.
- Exact preservation of arbitrary original formatting and comments is not required for initial live export.

## 18. Safety and Policy

- Parsing never requires Houdini or scene-edit capability.
- Live catalog reads require observation capability.
- Plan application requires scene-edit capability.
- Code installation requires `run_code`.
- Generic Houdini-side file outputs obey approved roots. HocusScript module reads are native compiler operations contained by the explicit project root.
- Project-directory selection is explicit, request-safe, and never grants access outside that directory or widens approved roots.
- Network module resolution, if ever supported, requires a distinct network capability and produces a locked local artifact.
- Compilation and expansion enforce resource limits and cancellation.
- Diagnostics, lockfiles, source maps, and audit logs must not contain secrets or bearer tokens.
- Confirmation policy considers delete count, adoption, ownership transfer, locked boundaries, code installation, and external dependencies.

## 19. Live Synchronization Requirements

Before source apply becomes supported, HocusPocus MUST observe or reliably reconcile:

- node create, delete, rename, reparent, and type/definition changes
- input and output rewiring
- parameter, expression, keyframe, and spare-parameter changes
- flag and network-position changes
- HDA definition and lock-state changes
- hip new/load/merge boundaries

Events are coalesced by network scope, compiler-originated events are suppressed from conflict detection, and source compile/apply performs a final dirty-scope checkpoint.

## 20. Production and AAA Asset Requirements

HocusScript can orchestrate AAA-quality procedural assets only when the surrounding pipeline provides:

- reviewed, versioned studio HDAs and modules
- asset contracts for scale, axes, naming, topology, manifold state, normals, tangents, UVs/UDIMs, texel density, materials, LODs, collision, pivots, bounds, instancing, USD kind/purpose/variants, and dependencies
- deterministic clean-machine rebuilds
- cook errors, timing, memory, polygon, texture, and platform-budget validation
- viewport captures, turntables, contact sheets, and render/version comparison
- provenance for sources, modules, HDAs, input assets, and publish outputs
- protected artist overrides and a clear generated-versus-authored boundary
- publish integration and CI validation

The language enables reproducible procedural art direction. It does not replace visual review or specialist sculpting, grooming, painting, rigging, or art direction.

## 21. Testing and Conformance

Required suites include:

- lexer/parser coverage, recovery, Unicode/escaping, and exact spans
- formatter idempotence
- deterministic AST/GraphSpec/document/plan golden fixtures
- fake-catalog resolution, ambiguity, drift, HDA, parm, and port tests
- property/fuzz tests for arbitrary and hostile source
- import traversal, symlink, expansion, resource-limit, and capability-escalation tests
- stable identity across rename, reparent, save, reload, and copy conflict
- indexed/named/multi-output port fidelity
- scalar, tuple, ramp, multiparm, menu, expression, channel-reference, spare-parm, animation, and code tests
- ownership-safe merge/reconcile/adopt/detach behavior
- stale plan, revision, catalog, hash, timeout, idempotency, and cancellation tests
- verified rollback after every execution phase
- SOP, MAT/VOP, LOP, TOP, ROP, and locked-HDA live matrices as support expands
- semantic export/recompile equivalence
- 1k/10k-node performance and payload budgets
- at least one production fixture covering geometry, materials, UVs, LODs, collision, USD/publish outputs, validation, and visual comparison

## 22. HS1 Target Boundary

The HS1 implementation target is intentionally preview-only:

- pure-Python lexer, source positions, parser, AST, structural compiler, and formatter
- version header, one graph, target, category, mode, revision, ownership, existing/adopt, nodes, indexed inputs, scalar/array values, tagged code, display/render/output, and auto layout
- deterministic GraphSpec serialization and structured diagnostics
- offline unit and golden tests

It does not lower to a live apply plan or mutate Houdini. Source application remains blocked until persistent UID stamping, sparse-document verification, exact source-output handling, ownership-safe reconcile, catalog resolution, and code-capability enforcement are complete.
