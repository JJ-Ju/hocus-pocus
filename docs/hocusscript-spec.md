# HocusScript Language and Compiler Specification

Status: implemented multi-version contract; V1 production-release closure active
Supported language versions: `0.1` through `0.4`
File extension: `.hocus`

Release-closure plan: `docs/hocusscript-roadmap-completion-plan.md`

The sole supported and release-qualifying live runtime for V1 is exact Houdini
`22.0.368`. Every other Houdini build, including Houdini `21.x`, is outside the
V1 support contract. H21 receipts retained below are historical migration
evidence only.

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

GraphSpec version `0.2` uses schema URI `hocuspocus://schemas/graph-spec/v0.2`. It is the first contract that can carry an optional durable managed-node `explicitId`:

```json
{
  "$schema": "hocuspocus://schemas/graph-spec/v0.2",
  "kind": "graph_spec",
  "graphSpecVersion": "0.2",
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
  "span": {},
  "fieldSpans": {"name": {}, "target": {}, "mode": {}, "layout": {}}
}
```

The source-faithful syntax AST is separate from normalized GraphSpec and preserves statement order, optional spellings, quoted forms, and trailing commas. Nodes contain ordered `inputs` and `parms`, plus optional `explicitId`; external nodes declare `symbol`, `path`, and `adopted`. GraphSpec carries entity/value spans plus `fieldSpans` for authored singleton scalars. Tagged code additionally carries its exact body span and a compact escape-aware offset map so later diagnostics can translate decoded code offsets back to `.hocus` source offsets.

GraphSpec `0.1` remains a decode-only legacy contract and MUST reject `explicitId`. Compiler `0.2.0` pairs only with GraphSpec `0.1`; compiler `0.3.0` pairs only with GraphSpec `0.2`. Bundle decoders may accept those explicit historical pairs, plus compiler `0.1.1`/GraphSpec `0.1` only in legacy structural bundle `0.1`; they MUST reject mixed pairs or an `explicitId` smuggled into a `0.1` payload.

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

HocusScript files are ordinary source-code files. Agents and users read, edit, search, diff, rename, and version `*.hocus`, `hocus.project.toml`, and `hocus.lock.json` through their native editor, workspace, and filesystem tools. Native tools remain the primary file surface. H6 additionally exposes approved authored files through an opt-in MCP project workspace; it does not expose a general host filesystem or make a parallel source store.

The user-selectable project directory belongs to the offline compiler/editor configuration. The native command accepts it explicitly through `--project`; editor settings and `HOCUS_PROJECT_DIRECTORY` MAY provide the same value. H6 adds an optional host-owned Houdini/MCP configuration that lets the user approve canonical project directories and separately approved read-only external roots. An agent request MUST NOT grant itself a root.

```text
native editor or agent filesystem
    -> offline HocusScript compiler/formatter
    -> content-addressed compiled bundle
    -> Houdini MCP preview/plan/apply

optional H6 MCP source workspace
    -> user-approved native project files
    -> the same offline compiler/formatter
    -> the same content-addressed bundle and guarded document pipeline
```

Project rules:

- The offline compiler receives an explicit project directory and resolves it to a canonical absolute directory. It does not infer a project from the Houdini hip file, `$HIP`, the package repository, or process CWD. H6 resolves only a host-approved opaque `projectId` to that directory; it does not accept a self-authorizing root from an MCP request.
- `hocus.project.toml` v1 defines `schema_version`, a stable project `uid`, an optional display `name`, normalized relative `source_directories`, language version, and whether the structural lock is optional or required. Unknown v1 fields are rejected. `source_directories` defaults to `["."]`.
- The project UID uses lowercase ASCII letters, digits, dots, and hyphens, starts with a letter or digit, and is at most 128 characters.
- `hocus.lock.json` v1 binds the project UID, exact manifest digest, and language version. Its `catalog` value is `null` and `modules` is empty until HS2/HS6 lock those formats; later schemas extend rather than silently reinterpret v1. Check/compile always validate existing locks, required missing locks fail, and stale locks block portable compilation. Pure formatting does not consume or rewrite the lock and remains available for repair workflows.
- `hocus.project.toml` v2 adds explicit project-relative JSON paths for the required lock and catalog snapshot and requires `lock.policy = "required"`. Both are resolved inside the user-selected project directory after canonical containment; neither is inferred from CWD, `$HIP`, Houdini packages, or an MCP registry. `validate_lock = false` remains a workspace-only formatting/repair path and cannot claim portable identity.
- `hocus.lock.json` v2 pins catalog schema version, project-relative path, exact content digest, and authenticated catalog fingerprint. Manifest v2 pairs only with lock v2; v1 remains immutable and continues to require `catalog: null`.
- Source paths and import paths are project-relative and contained after canonical resolution. The legacy `0.1` native lane MAY accept a contained absolute source path for compatibility; the portable `0.2` module lane requires normalized project-relative source and entry paths.
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
source_directories = ["hocus"]

[language]
version = "0.1"

[lock]
policy = "required"
```

Initial lock shape:

```json
{
  "$schema": "hocuspocus://schemas/hocus-lock/v1",
  "kind": "hocus_project_lock",
  "schemaVersion": 1,
  "projectUid": "city-environment",
  "manifestDigest": "sha256:...",
  "languageVersion": "0.1",
  "catalog": null,
  "modules": []
}
```

Catalog-pinned project shape:

```toml
schema_version = 2

[project]
uid = "city-environment"
source_directories = ["hocus"]

[language]
version = "0.1"

[lock]
policy = "required"
path = "pins/hocus.lock.json"

[catalog]
path = "catalogs/houdini-21.0.json"
```

```json
{
  "$schema": "hocuspocus://schemas/hocus-lock/v2",
  "kind": "hocus_project_lock",
  "schemaVersion": 2,
  "projectUid": "city-environment",
  "manifestDigest": "sha256:...",
  "languageVersion": "0.1",
  "catalog": {
    "schemaVersion": 1,
    "path": "catalogs/houdini-21.0.json",
    "contentDigest": "sha256:...",
    "fingerprint": "sha256:..."
  },
  "modules": []
}
```

The manifest digest covers the exact bounded manifest bytes. The lock digest covers canonical JSON with sorted keys, so lock whitespace and key order do not create false bundle drift. Lock updates are explicit write operations through `hocus lock --update` or the H6 `source.project.build` lock action; they are never implicit side effects of check, compile, format, document preview, or document apply.

The offline compiler emits deterministic, content-addressed bundles. Structural bundle v0.1 remains the compatibility format for unpinned v1 and memory/workspace results. Semantic bundle v0.2 additionally requires:

- an exact catalog schema/fingerprint/content-digest constraint
- deterministic operator, parameter, and connection selections keyed by GraphSpec JSON pointers
- deferred external-baseline checks and document-lowering readiness
- the catalog-verified capability manifest

Both formats contain at least:

- bundle, language, compiler, GraphSpec, and source-map versions
- stable project UID and manifest/lock digests when available
- entry source URI/digest and ordered dependency URIs/digests
- normalized GraphSpec and source maps
- catalog constraints and required capabilities
- a bundle digest computed over canonical serialized content

Absolute physical paths are excluded from portable bundle identity and payloads. Relocating a project preserves source and bundle identity when its manifest UID, relative paths, contents, compiler inputs, and locks are unchanged.

The Houdini mutation boundary is content-based. The exact standard-library trust boundaries use `decode_compiled_bundle()` for Bundles `0.1`-`0.3`, the control-carrier decoder for Bundle `0.4`, and the value-carrier decoder for Bundle `0.5`; each validates its own exact fields and version tuple, canonical digest, bounded complexity, finite values, portable provenance, source/dependency records, source maps, GraphSpec envelope consistency, and capabilities derived from graph content. They never read paths or Houdini state, and versions are never coerced. Even when H6 can access approved source files, document preview/plan/apply consumes only authenticated bundle content and stored plan identity. Source bytes are not embedded, so the decoder validates the integrity of source-digest claims, not their external authenticity.

MCP progression:

- `document.compile_source` remains an optional compatibility/convenience endpoint for unsaved source text. It never accepts a project directory or reads a path.
- `document.preview_bundle` accepts flat Bundle `0.2`, frozen module Bundle `0.3`, control Bundle `0.4`, or value Bundle `0.5` content through its version-specific decoder, freshly resolves it against the current Houdini catalog/baseline, and returns a non-mutating candidate document, diff, destructive summary, and preview plan.
- `document.plan_bundle` reruns the exact live validations and persists an immutable guarded plan only after all HS4 gates pass.
- `document.apply_plan` accepts only a stored plan identity, not source paths or arbitrary source text, and rechecks its live drift guards without rebuilding the plan.
- `document.export_source` returns source text plus provenance. The native editor/CLI owns writing it to a chosen `.hocus` file.
- At the historical H5 checkpoint, frozen Bundle `0.3` and strict Bundle `0.4` used the same content-only document operations with GraphSpec `0.4`, durable module/control provenance, fresh live semantics, exact pins, guarded apply, cancellation, verification, rollback, and recovery. HS7 subsequently added the exact Bundle `0.5` value lane without widening the frozen carriers.
- H6 adds a separate `source.*` namespace for approved-project describe/read/patch/build/navigation operations. It does not add path parameters to `document.*` or let source-file access bypass bundle planning.

There is no `document.compile_file`, path-taking `document.open_project`, or general filesystem operation. H6 registers a bounded source-workspace registry only from host-approved project configuration and identifies projects to clients by opaque `projectId`. The Houdini-local Source Workspaces UI manages approvals, access mode, persistence, external-root grants, expiry, audit viewing, and revocation; document mutation remains bundle/plan based.

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
- The graph `output` directive lowers to an explicit network-document `output_flag` edge and `set_output` candidate operation; it is not hidden in metadata. HS4 must provide a network-family adapter or block apply where Houdini exposes no safe setter.
- `layout = auto` uses the deterministic `hocus-grid-v1` document layout for authored mutable nodes, so previewed positions are explicit and verification does not depend on Houdini UI auto-layout behavior.

### 8.7 Parameters

- Parameter names resolve against exact catalog parameter tokens, not UI labels.
- Scalar-to-tuple coercion is forbidden unless the catalog explicitly declares it.
- Menu values use stable tokens rather than localized labels.
- Parameter defaults are distinct from explicit values.
- Button parameters, callbacks, and other actions are not ordinary assignments.

The AST and GraphSpec reserve first-class forms for tuples, ramps, multiparms, expressions, channel references, keyframes, time samples, units, and resets. Unsupported forms MUST produce diagnostics rather than be approximated or discarded.

Network-document v1 carries scalar literal bindings. In the frozen HocusScript
`0.1` / Bundle `0.2` lane, scalar component assignments lower directly while
whole-tuple assignments stop with `HOCUS708` because that carrier does not
retain the ordered component-token mapping required for safe expansion. Frozen
language `0.2` / Bundle `0.3` and language `0.3` / Bundle `0.4` gain no
whole-tuple syntax or carrier semantics. Language `0.4` / GraphSpec `0.5` /
Bundle `0.5` is the separate current lane that carries exact ordered component
tokens and safely lowers whole tuples. Ramp and multiparm rejection is likewise
a legacy-lane rule, not a limitation of the accepted language `0.4` surface.

### 8.8 Code Blocks

- `vex`, `python`, and `hscript` templates are inert text during parsing.
- Compilation MAY syntax-check code without executing it.
- Installing or changing code requires the `run_code` capability in addition to scene-edit capability.
- Code blocks retain their source offset so embedded diagnostics map to the `.hocus` file.
- Catalog code surfaces outside the language `0.1` tags, including OpenCL or unknown executable editors, are recorded as `code/unsupported`. They remain fingerprinted but reject assignment; they are never downgraded to ordinary strings or allowed to bypass `run_code`.

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

A catalog v1 snapshot is strict, bounded, canonical JSON. Its fingerprint is SHA-256 over the canonical payload with only `catalogFingerprint` omitted. Enumeration order does not affect identity; every resolution-affecting build, package, HDA, parameter, menu, code-surface, connector, and locked/editable field does. A catalog snapshot MUST include:

- Houdini product, build, platform, and relevant feature flags
- node category and exact opaque Houdini operator type name
- operator namespace and definition version
- HDA library identity and content digest
- parameter tokens, tuple shapes, types, defaults, ranges, menus, tags, and code-surface classification
- spare-parameter policy
- named and indexed input/output connectors and cardinality
- locked/editable state and supported network families
- installed package and Labs versions when relevant

Catalog resolution rules:

1. An exact Houdini operator type-name match wins inside the selected category.
2. An alias or unqualified name must resolve to one compatible definition.
3. Ambiguity is an error with ordered candidates and a fix-it.
4. Compilation records the selected definitions and catalog fingerprint.
5. Apply rechecks the fingerprint and refuses silent drift.
6. Offline compilation uses a pinned catalog snapshot and lockfile.

Category is a separate identity dimension: two definitions may both have the exact Houdini name `null` in different categories. A graph-level `category` constrains all node resolution. When no graph category is present, the explicit string selector `"Sop/null"` selects catalog category `Sop` plus exact Houdini type `null`; the selected definition still records `qualifiedName = "null"`. Category selectors never rewrite Houdini type names or create version fallback.

## 11. Identity and Ownership Metadata

Every compiler-managed entity MUST have a durable UID independent of Houdini session ID, name, and path.

- A managed node may carry an explicit durable ID as `node symbol @id("stable-uid"): "type" { ... }`. The ID must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, is unique inside the graph, survives export destination and symbol changes, and maps directly to the network-document node UID.
- Reusing an explicit ID at a new node path is a rename only when the baseline entity carries complete Hocus provenance matching the current project, graph, ownership namespace, entity kind, and prior symbol. Source URI and symbol may change after that proof. A destination occupied by another UID still blocks, and a UID-only artist entity is never implicitly adopted; it requires the explicit `adopt` workflow.
- Default IDs derive from ownership namespace, graph identity, module instance path, and local symbol.
- Managed Houdini nodes created by an apply, and live nodes explicitly adopted into compiler ownership, are stamped with at least `hpmcp.uid`, `hpmcp.owner`, source URI, graph/module identity, and compiler version. Read-only import and bundle preview never stamp artist nodes; they prefer an existing persistent UID and otherwise use a non-persistent session/path fallback until explicit adoption.
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

HS6 adds a new lane; it does not reinterpret any `0.1` artifact:

| Language | Compiler | GraphSpec | Compiled bundle | Meaning |
| --- | --- | --- | --- | --- |
| `0.1` | `0.3.0` | `0.2` | `0.1`/`0.2` | Existing single-file graph lane |
| `0.2` | `0.4.0` | `0.3` | `0.3` | Static modules, typed expansion, and transitive module provenance |
| `0.3` | `0.5.0` | `0.4` | `0.4` | Typed compile-time control with exact native and H5 document/live paths |
| `0.4` | `0.6.0` | `0.5` | `0.5` | HS7 named ports, typed values, graph-editor entities, managed instance spares, and numeric animation |

Compiler `0.4.0` MUST retain the existing `0.1` parser and emit GraphSpec `0.2`; it emits GraphSpec `0.3` and bundle `0.3` only for language `0.2`. Decoders reject mixed pairs rather than upgrading them implicitly. Portable language `0.2` compilation requires project manifest/lock v3; the implemented v1 and v2 contracts remain immutable.

Language `0.2` is frozen at the static module feature set in this table. Typed compile-time control belongs only to language `0.3`; it MUST NOT be accepted under a `hocus 0.2;` header or inserted into the `0.2` compiler, lock, resolved-set, expansion-map, GraphSpec, or bundle contracts. H1 assigns a parallel, exact compatibility row and provides strict carrier decoders and schemas; those decoders alone grant no execution authority. H3 composes the native compiler/resolver/CLI/editor lane and H5 composes the document/live lane through their named gates. Every decoder rejects mixed tuples rather than upgrading or inferring versions.

## 14. Compile and Apply Contract

### 14.1 `document.compile_source`

Input:

```json
{
  "source": "hocus 0.1; graph ...",
  "source_name": "rocks.hocus",
  "strict": true
}
```

The compatibility tool remains at `stage = structural`: syntax, structural diagnostics, canonical formatting, source digest, compiler/GraphSpec versions, and a span-bearing GraphSpec. `readyForDocumentLowering` and `readyForApply` remain false. HS3 and HS4 progression occurs through `document.preview_bundle` and `document.plan_bundle`, not by giving this tool filesystem responsibilities.

The live path is deliberately split across four authority boundaries:

- the `compile` action of `source.project.build` reads one approved ordinary
  project `.hocus` entry and returns the exact authenticated carrier for its
  lane: flat Bundle `0.2`, module Bundle `0.3`, control Bundle `0.4`, or value
  Bundle `0.5`;
- `document.preview_bundle` accepts that content, reruns its exact-version
  carrier, semantic, catalog/HDA, capability, ownership, target, revision, and
  provenance checks, lowers it over the current network-document baseline, and
  returns the canonical candidate document, deterministic diff, destructive
  summary, and a preview-only candidate plan;
- `document.plan_bundle` reruns those live checks and persists an immutable
  `planId`, `planHash`, expiry, baseline, inverse, and exact drift guards; and
- `document.apply_plan` consumes only that stored immutable plan identity,
  rechecks its live session, policy, catalog, capability, ownership, target,
  revision, confirmation, lease, idempotency, and cancellation guards, then
  applies and verifies it without rereading or recompiling source.

Source compilation and preview never mutate Houdini.

For `document.compile_source`, `source` is required and provenance is `hocus-memory://`; it cannot read a path or create an applyable plan. Durable project provenance comes from the offline compiler bundle.

### 14.2 `document.preview_bundle` and `document.plan_bundle`

`document.preview_bundle` accepts flat Bundle `0.2`, frozen module Bundle `0.3`,
control Bundle `0.4`, or value Bundle `0.5` content and dispatches only
through that carrier's exact strict decoder. It rehydrates the exact GraphSpec
version and freshly resolves the graph against the current live catalog. Each
authenticated carrier must match its applicable semantic selections, exact
catalog fingerprint/content and HDA/operator resolution, capability manifest,
project/lock/module identity, target constraints, and provenance pins; a
recomputed content hash does not make forged selections trustworthy. Bundle
`0.4` may conservatively retain hidden-body `run_code` authority, but selected
graph semantics must still match exactly. The operation overlays the complete
live network-document baseline, validates the resulting document, and returns a
deterministic diff, destructive summary, source maps, durable provenance, and a
non-applyable candidate plan.

This `document.*` operation accepts content, not paths. It never reads DSL/project source files and never mutates Houdini. The H6 `source.*` workspace is a separate authority and does not change this contract. Live catalog provenance may inspect the installed Houdini/HDA/package environment. Preview artifacts up to the configured memory limit are content-addressed at `houdini://documents/previews/{preview_id}`; payloads larger than the inline threshold are returned only through that resource. Per-artifact and aggregate byte budgets plus LRU/TTL eviction bound Houdini-process memory.

Bundle catalog/HDA drift, semantic-selection drift, project/lock/module drift, target-document or revision drift, schema errors, unsafe ownership/collision conditions, unsupported values, or missing source provenance produce blocking diagnostics and no candidate plan. Imports remain an offline compiler responsibility when the active language version supports them. Complete effective Houdini package-search provenance remains outside the claim while `HS-BLOCK-003` is open.

`document.plan_bundle` reruns the same exact-version live trust gates, normalizes
the verified target into executable operation groups for its supported network
family, rejects unknown or irreversible actions, captures the exact baseline
and inverse plan, and persists a `hocus_apply_plan` v1 envelope. The envelope
has an independent hash domain from the preview candidate plan and binds its
UUID, TTL, process/hip session epoch, source/bundle/compiler/GraphSpec/project
manifest and lock identities, catalog fingerprint/content digest, effective
policy fingerprint, capabilities, ownership, target scope, baseline
document/live revisions and digest, target document, provenance, confirmation
policy, normalized operations, and inverse plan. Generated expansion symbols
are mapped to deterministic legal Houdini node names without changing durable
entity IDs or provenance. The SQLite record is insert-only; mutable apply
lifecycle state is stored separately. A bundle containing preview-only
workspace provenance cannot produce a stored plan.

An existing authored node is reusable only when its complete managed Hocus identity matches the requested project, graph, entity kind, symbol, ownership, and `managedFields.nodeUid`. Exact UID/path coincidence is not adoption authority. Missing identity, UID-only artist state, or project/graph/ownership collision fails with `HOCUS706` before a candidate plan exists and leaves the baseline unchanged. Source, bundle, compiler, language, and expansion values may refresh as provenance, but every accepted existing-node refresh emits `update_node_provenance`. The only ownership-transfer lane is an authored external with `adopted = true`; it emits `adopt_node`, remains confirmation-requiring, and is never inferred. Before storage, normalized `identityUpdates` must correspond exactly to supported `adopt_node` or `update_node_provenance` candidate actions; hidden, missing, or unsupported identity transitions fail with `HOCUS740`.

Reconcile is field-selective. It deletes only matching-owned nodes omitted from the new graph; artist-owned dependants still block deletion with `HOCUS709`, and safely removable owned state without source provenance still fails with `HOCUS713`. On retained nodes, only fields named by the previously validated `managedFields` manifest may be reset when omitted: managed parameters and code return to Houdini defaults, managed input indices disconnect, managed display/render/output state clears, and compiler-owned ports are pruned only when unused. Unowned/default bindings, edges, code, flags, positions, and arbitrary metadata survive omission. A live parameter counts as an ignorable default observation only when HOM confirms the permanent default and compares expressions; temporary defaults, unsupported checks, and comparison errors fail closed as unowned state. Explicit source at the same parameter or input coordinate may replace prior state, but omission never claims an artist field.

Expansion provenance is materialized only after the final target document is complete. Every non-null module `stackId` and `controlStackId` referenced by final nodes, ports, edges, bindings, or code blobs must resolve through the authenticated incoming tables or a normalized baseline table. Duplicate IDs must have identical canonical content. Tables are ID-sorted, deduplicated, and pruned to referenced entries; the root table is absent when no reference remains. Forged frames, conflicting definitions, dangling references, more than 4,096 stacks of either kind, more than 64 frames per stack, or a provenance envelope above 4 MiB fail before planning with typed `HOCUS715`/document-provenance diagnostics. The same pure normalizer is used by lowering, document validation, and live save/reopen.

Plans are available at `houdini://documents/plans/{plan_id}` and are bounded by count, per-plan size, aggregate size, TTL, and LRU retention in the live cache. `document.discard_plan` removes the cache entry and durably claims the persisted plan as aborted so it cannot be applied after a restart. SQLite is authoritative for replay and recovery. Expired unclaimed plans are removed immediately; committed/aborted replay history is retained for at most the 24-hour idempotency window and is pressure-pruned to at most 256 terminal histories and 256 MiB of retained JSON. Pending and `partial_or_unknown` evidence is never automatically deleted. A 32 MiB terminal-transition allowance is reserved for each active history so finishing or recovering a commit cannot push protected storage beyond the 256 MiB ceiling; an oversized finish remains pending and an oversized recovery remains quarantined. If protected records alone exhaust capacity, new durable storage fails with `HOCUS759`. The graph-store boundary translates SQLite connect, PRAGMA, query/write, transaction, rollback, and close failures only after cleanup; persistence, replay, discard, quarantine hydration, and recovery expose those failures through typed `HOCUS759`, while cancellation, explicit schema errors, and apply-time `partial_or_unknown` quarantine retain their distinct contracts. Pruning is transactional after migrations, before insertion, and after terminal completion or recovery; it deletes events, then commits, then unreferenced plans and does not run automatic `VACUUM`.

### 14.3 `document.apply_plan`

Input contains only:

- plan ID and plan hash
- expected document/live revision
- optional confirmation token
- idempotency key

The implemented guarded apply:

1. acquire a target-network write lease
2. validate plan identity, TTL, session, catalog, revisions, ownership, policy, and capabilities
3. reject tampering or drift without recompiling
4. execute reversible structural operations in one guarded undo scope
5. reimport only the affected network scope
6. verify intended effects and protected-state preservation
7. commit the document/store revision and audit record
8. return a true success or true typed failure

The plan is never rebuilt from source. A freshly normalized operation set is computed only as a validation oracle and must byte-match the stored execution plan; the stored plan remains the sole execution authority. Bundle `0.3`/`0.4` node provenance is copied into signed live `managedFields` metadata, while exact non-node source provenance for managed ports, edges, bindings, code, and output state is stored in a bounded, canonical, digest-checked root carrier. Reimport reconstructs the exact `jsonPointer`, span, origin, and module/control stack references by entity UID and validates their node identity lane, so a newly compiled second reconcile remains source-resolvable after a live snapshot. Hocus-generated preview documents are rejected by legacy `document.apply`, and any code-blob installation dynamically requires `run_code` in addition to `edit_scene`.

Preview, planning, and guarded apply check request cancellation at bounded semantic, lowering, normalization, and operation-group checkpoints. Cancellation before mutation leaves the scene unchanged; cancellation during apply enters the same verified rollback/quarantine lifecycle as another apply failure.

`clear_output` performs the live display/output mutation rather than recording only an intent. Every omitted managed parameter returns to the permanent Houdini default through `revertToAndRestorePermanentDefaults()` and is verified with `parm.isAtDefault(compare_temporary_defaults = false, compare_expressions = true)`; temporary defaults, surviving expressions, unsupported checks, and errors fail closed. A failed reset, failed provenance write, or failed output mutation enters the same rollback/quarantine lifecycle as any other executor failure.

### 14.4 HS5 editor and export interfaces

`document.format_source` and `document.complete_source` accept unsaved text only. They never accept or infer a project directory. Formatting returns canonical source only when parsing and structural validation succeed. Completion uses the current live catalog, is deterministically ordered and bounded to 200 items, and returns an exact replacement span. All source offsets in the HS5 JSON contracts are Unicode code-point offsets, matching Python string indexing; an LSP adapter must explicitly translate to and from UTF-16 positions.

`document.export_source` accepts a live `root_path` and optional graph identifier, never a physical destination. It force-refreshes the selected network document, preflights the entire supported projection, verifies emitted source by recompiling against the exact live catalog fingerprint, and returns either:

- canonical source plus source digest, persistent entity identities, managed fields, ownership namespaces, catalog fingerprint, root path, and document identity/revision; or
- `source = null` plus a deterministically ordered blocker list bounded to 500 entries; overflow retains 499 blockers and a final `HOCUS819` sentinel with the exact omitted count.

The serialized export result and native `write-export` handoff share a 16 MiB UTF-8 budget. An otherwise valid result that exceeds it fails closed with `HOCUS820`, minimal provenance, and no source; clients should narrow the network scope rather than bypass the handoff contract.

Exported source is a baseline-preserving merge projection, not an implicit claim over every representable Houdini value. The root container anchors target/output identity but is not emitted as a DSL node. The root and every exported child require persistent user-data identity. Only parameters, input slots, and flags named by valid signed node `managedFields` provenance are portable source-owned fields. Root, default, and artist-owned state is omitted from source and enumerated in `provenance.preservedState`; recompiling/lowering against the captured baseline preserves it exactly. Moving such source to a clean baseline does not recreate preserved state, and tooling must surface that provenance rather than imply clean-rebuild equivalence.

HS5 export is deliberately fail-closed. Its supported subset is one flat SOP network containing persistent unique node UIDs, exact catalog-resolvable operator types, indexed data connections, finite scalar/menu literals (including representable scalar tuple-component tokens), supported VEX/Python/HScript code bindings, and representable display/render/output state. It rejects nested networks, cross-network edges, unsupported edge/port kinds, bypass/template state, expressions and channel references, animation/keyframes, whole-tuple values, ramps, multiparms, spare parameters, unsupported code, invalid identifiers, orphan entities, mixed/incomplete ownership, duplicate/nonpersistent IDs, and any state it cannot reproduce exactly. HocusScript 0.1 has no opaque syntax, so nothing may be silently omitted or approximated.

The native `hocus write-export` command owns the filesystem handoff through H5. It accepts the same bounded export response emitted by MCP, requires an explicit `--project` (or explicit editor setting/environment equivalent), resolves a project-contained `.hocus` destination through configured source directories, validates the handoff digest and recompiles before writing, creates exclusively by default, and permits replacement only with the destination's exact expected digest. H6 performs that same authenticated handoff only inside a user-approved source-write project through the distinct `source.file.write_export` operation, which reuses the native validation/recompile/publish path; generic `source.file.apply_patch` is not an export handoff. `document.export_source` itself never accepts a destination or writes a file.

For language `0.2`, the same native `hocus check`, `hocus format`, and `hocus compile` commands dispatch from the selected manifest rather than sniffing source headers. `check` verifies the complete locked module closure and pinned catalog semantics; `check --json` emits one portable JSON result even on syntax/project failure. `format` reads and formats exactly one contained graph or module file without consuming the lock, so it remains usable to repair stale projects. `compile` invokes the one-shot project-to-Bundle `0.3` producer and never accepts caller-supplied semantic selections. Bundle output creates exclusively by default and permits replacement only with `--expected-output-digest` equal to the current raw output-file digest. Text diagnostics use stderr; requested source/JSON/bundle content alone uses stdout. `--no-strict` remains a `0.1` compatibility option and is rejected for `0.2`, whose header is mandatory.

G5 adds repeatable `--module-root ALIAS=ABSOLUTE_PATH` only to `check`, `compile`, and `lock --update`. Supplying at least one root selects the separate mixed-root semantic, bundle, or lock-publication API respectively; omitting the option preserves the existing same-project path. The repeated options must form the complete exact mapping declared by the project, duplicate aliases are rejected before mapping construction, and the split occurs at the first `=` so an absolute path may itself contain `=`. Physical roots are never read from an environment variable, expanded from `~` or environment syntax, inferred from a lock, cached, persisted, or serialized. Language `0.1` rejects module-root options instead of ignoring them. `format` remains syntax-only and does not accept module roots; `write-export` remains a language-`0.1` content handoff and does not accept them either.

`hocus lock --update ENTRY...` is the sole `0.2` CLI write path for module records. The command itself is explicit write authority and delegates to resolver-derived lock construction. Same-project creation forbids a replacement digest and an existing same-project lock requires its exact digest. Mixed-root publication always requires one valid existing v3 lock plus its exact `--expected-lock-digest`; it cannot bootstrap or repair a structurally invalid lock. Every successful receipt is portable and host-path-free. The tested canonical executable surface is `python -m hocuspocus.hocusscript`; a separately packaged bare `hocus` console script is not implied by the Houdini package layout.

## 15. Rollback and Recovery

- Apply plans exclude irreversible actions.
- A pre-apply scoped snapshot and inverse plan are recorded.
- Failure first uses the uniquely labelled apply-owned Houdini undo record; the stored structural inverse is a secondary recovery attempt.
- Rollback is reimported and verified.
- A failed rollback returns `partial_or_unknown`, quarantines the scope, and requires explicit resync or recovery.
- Store commits use pending, committed, aborted, and `partial_or_unknown` states; the last state quarantines overlapping parent/child scopes.
- Startup/lazy recovery treats durable pending and `partial_or_unknown` commits as quarantined. `document.recover_scope` force-reimports under the same scope lease and releases quarantine only when live state classifies exactly as the stored baseline or verified target; any third state remains quarantined.
- A target-classified recovery becomes a normal successful terminal result with the original plan ID/hash, commit ID, `applied = true`, `verified = true`, committed state, recovered document/verification, and `recovered = true`; it does not invent lease, timing, or executed-operation fields.
- A baseline-classified recovery becomes an aborted `HOCUS755` result. When baseline and target are indistinguishable, classification remains conservatively aborted. A third state remains protected as `partial_or_unknown` with `HOCUS756`.
- Client timeout and retry behavior are controlled by idempotency keys. Replay of a recovered target returns the recovered committed result with `idempotentReplay = true`; `HOCUS760` is reserved for a genuinely pending recovery. Any surviving in-memory reservation is reconciled by idempotency key against authoritative SQLite state.
- The implementation MUST NOT claim general atomicity while relying only on an unqualified global undo.

## 16. Modules and Imports

Language `0.2` adds pure compile-time modules. A source file contains exactly one root `graph` or one root `module`, preceded by its `hocus 0.2;` header and zero or more literal imports. Imports, module declarations, and instances never execute host-language code.

```hocus
hocus 0.2;
import { Noise as StudioNoise } from "@studio/noise.hocus";

graph asset {
  target "/obj/asset";
  category Sop;
  mode merge;
  node source: "box" {}
  use noise @id("asset-noise") = StudioNoise(source = source.output[0], scale = 2.0);
  node result: "null" { input[0] = noise.result; }
  output = result;
}
```

```hocus
hocus 0.2;

module Noise(
  source: node_output,
  scale: float = 1.0,
) exports (
  result: node_output,
  effectiveScale: float,
) {
  node noise @id("noise-node"): "mountain" {
    input[0] = param.source;
    height = param.scale;
  }
  export result = noise.output[0];
  export effectiveScale = param.scale;
}
```

The `0.2` type set is exactly `bool`, `int`, `float`, `string`, and `node_output`. Parameters and exports use the same types. Arguments are named, required unless a literal default is declared, and must match exactly; there are no implicit numeric conversions, nullable values, spreads, overloads, generics, arrays, or parameterized code blocks in this lane. `node_output` is the only graph-handle type. Scalar references may appear only where a scalar value is legal. Export expressions are literals, `param.<name>`, a local node output, or a nested instance export of the declared type.

Imports have the single static form `import { ExportedName as LocalName } from "literal.hocus";`; `as LocalName` MAY be omitted. Specifiers require an exact `.hocus` suffix and never infer extensions or index files. `ExportedName` must equal the imported file's one module declaration. Every instance uses `use local @id("durable-seed") = ModuleName(name = value, ...);`; its bounded seed follows the node-ID lexical pattern and is unique within its enclosing graph/module. Nodes and instances share one local symbol namespace. Modules cannot declare a target, mode, ownership, external/adopt reference, or graph flag. A module-local node/use `@id` is only a namespaced identity seed, never a direct network-document UID; node seeds are optional and fall back to the local symbol, while every `use` seed is mandatory. Conditionals, iteration, and recursion are not part of language `0.2`, and that version is now frozen. Bounded deterministic conditionals and iteration use the proposed language `0.3` contract below. Unbounded recursion remains forbidden; explicitly bounded deterministic compile-time recursion is deferred until it has its own reviewed syntax, termination proof, identity rules, provenance, and expansion-budget contract.

Resolution is deterministic and native-only:

1. `./` and `../` specifiers resolve relative to the importing file after canonical containment checks.
2. Non-relative local specifiers search ordered manifest `module_directories`; the first match is selected and locked. Adding an earlier match makes verification stale and requires an explicit lock update.
3. `@alias/path.hocus` resolves only through a manifest-declared alias. The alias declares expected external library UID and version; its physical root comes from a separate explicit CLI/editor approval such as `--module-root alias=path`. Host paths never enter portable artifacts.
4. Every file remains inside the project or separately approved alias root after symlink/junction-aware canonicalization. Absolute imports, dynamic strings, environment lookup, network fetches, and implicit Houdini/package searches are rejected.

Local module files use `hocus-project://<project-uid>/<relative-path>`; approved external libraries use `hocus-module://<library-uid>/<relative-path>`. Lexical import aliases and instance symbols are not identity. Stable module identity is canonical URI plus declared name. Expanded identity derives from graph identity, the ordered nested instance-`@id` seed path, module URI, and the local node/use `@id` seed or symbol fallback. A `use` symbol may therefore be renamed without replacing its expanded entities when its seed is unchanged. Argument values do not change identity. Generated symbols use a reserved collision-proof GraphSpec encoding; authored `__hocus_` symbols are forbidden. H5 maps each generated symbol to a deterministic legal Houdini node name at plan time while retaining the generated symbol, durable entity UID, and expansion provenance as separate authoritative identities.

Expansion is pure, after import/interface validation and before catalog resolution. It produces flat GraphSpec `0.3`, strict `resolved-module-set-v1`, and strict `expansion-map-v1`. GraphSpec `0.3` embeds that exact standalone expansion-map object rather than defining a second projection. The expanded graph is inspectable as JSON or normalized generated source, but module files remain the editable authority; editing generated expansion is not a source round trip.

Every generated GraphSpec pointer has a primary source span and nullable `stackId`. `expansion-map-v1` interns ordered expansion stacks in one top-level `stacks` array; mappings never repeat frames. A stack ID is SHA-256 over domain `hocus-expansion-stack-v1` plus the canonical frame array. Stacks are sorted and unique by `stackId`; every non-null mapping reference resolves exactly once, and unreferenced stacks are forbidden. Each frame identifies module URI and source digest, module name, instance symbol, durable instance-ID path, import span when applicable, and `use` span. A null `stackId` means the entry source has no module-expansion frame. Substituted arguments point primarily to the call-site argument and retain the parameter declaration as related origin. Diagnostics resolve and reuse the same interned frames. Document lowering consumes per-entity module URI, source digest, durable instance-ID path, and origin rather than hardcoding the entry source.

Portable manifest/lock v3 is a new schema pair. Manifest v3 adds ordered `module_directories` and logical aliases without approved host roots. External roots contain `hocus.module.toml` v1 with stable library UID, strict SemVer 2.0 version (including optional pre-release and build metadata), supported language versions, and allowed entry modules. The same SemVer grammar applies to manifest aliases, lock records, resolved module sets, and bundle module dependencies. Lock v3 preserves the v2 catalog pin and records every transitive module by canonical URI, source and interface digests, project/library identity, version and module-manifest digest when applicable, resolved alias when applicable, and sorted dependency URIs. Ordering is by module URI. Compile is verify-only. `hocus lock --update` derives every same-project nonempty record from actual contained source, is explicit, expected-digest guarded, and atomic for cooperating writers; ordinary compile and every MCP operation through H5 never write locks. The separate native G3 publisher can atomically replace a valid current lock with independently derived mixed-root records, and the separate G4 consumers verify and consume those records only when the exact roots are supplied again. G5 exposes those native boundaries through explicit repeated CLI root options without granting ambient root authority. H6 invokes the same writer only through the explicit `source.project.build` `lock_update` action with the generated-lock grant and an explicit absent/exclusive-create or present/exact-digest-replace expectation.

Native external-root inspection accepts an explicit per-call `alias -> absolute local directory` mapping only after the v3 project declares every alias. The mapping must cover the declarations exactly, use one alias per library UID, and name distinct canonical local roots outside the project with no relative, home, environment, UNC, device, symlink, junction, reparse, casing-alias, or overlapping path. Inspection stable-reads exactly `hocus.module.toml`, checks its raw digest, UID, version, language, sorted entry-module list, optional project pin, and any existing lock identity, then final-rechecks project/lock/catalog/root/manifest identity. Its deterministic result and digest contain only portable pins; physical roots and file identities remain private and ephemeral. An alias whose project declaration omits `module_manifest_digest` may be inspected but is not resolution-ready. Inspection reads no module source, writes nothing, grants no persistent authority, and does not enable resolver, lock-writer, editor, CLI, MCP, bundle, document, or live support.

The native read-only `plan_project_module_lock(project_directory, entry_source_paths, module_roots)` API revalidates that exact external-root boundary, requires pre-pinned manifests, and derives a bounded, transitively complete prospective v3 closure from exact entry and module bytes. Project-to-library imports may enter only declared manifest entry modules; same-library imports are relative and contained; cross-library imports require a separately approved alias; library-to-project and external bare imports are rejected. Every entry must pass strict expansion validation before a plan can succeed; the expansion output is discarded and is not part of the plan. The host-path-free result binds project, manifest, current/prospective lock, catalog, root-inspection, resolver-policy, source/interface/transitive module, exact diff, and plan identities. Its unkeyed `planDigest` provides deterministic self-integrity only and is advisory, not an authorization or attestation. The API acquires no writer lease, writes and publishes nothing, and does not enable external modules in compiler, editor, CLI, MCP, bundle, document, or live paths. G3 independently rederives the closure under its own lease and never accepts a plan object, plan digest, JSON payload, prospective payload, or caller-authored module records as publication authority.

The native `update_project_mixed_module_lock(project_directory, entry_source_paths, module_roots, expected_lock_digest=..., allow_write=False)` API is the sole G3 mixed-root write surface and rejects unless the caller explicitly supplies `allow_write=True`. It requires one structurally valid existing language-0.2 v3 lock and its exact canonical digest; a missing, malformed, manifest/catalog-stale, or otherwise structurally invalid current lock fails without repair, while valid but source-outdated module records are independently rederived. Before the writer lease, it performs non-authoritative manifest/project-shape validation needed to locate the manifest-declared lock path; all lock/root/source authority is reloaded under lease. Under the lease it validates the exact current lock and per-call roots, independently runs the private G1/G2 derivation core from exact bytes, strictly expansion-validates every entry, constructs and strict-decodes the bounded canonical prospective lock, and prebuilds a frozen success receipt. Immediately before replacement it rechecks the project, current lock, catalog, root and manifest identities, all entry/module bytes and identities, and every resolver winner; the atomic writer then performs its final expected-digest check. An unchanged result is a verified no-op without a rewrite. Any failure leaves the active lock unchanged and attempts best-effort transaction-artifact cleanup without masking a successful commit. The strict unregistered `mixed-module-lock-update-v1` receipt contains only portable project, prior/new lock, catalog, root-inspection, resolver-policy, entry, module, and exact diff identities; physical roots and native identities are neither persisted nor returned. This remains a same-user cooperating-writer boundary under `HS-BLOCK-001`, not descriptor-safe privileged I/O or a filesystem-native compare-and-swap against noncooperating writers.

The mixed-root resolver contract shared by G2 planning, G3 publication, G4 native consumers, and G5 CLI dispatch is fixed as follows: a project may enter a library only through `@alias/path.hocus`, and that first path must be one of the library manifest's `entry_modules`; a library may use relative imports only within the same library; cross-library imports require another explicit `@alias/...`; bare imports inside libraries and imports from a library back into the project are rejected. Mixed-root resolution uses a new versioned resolver policy rather than reinterpreting the same-project policy. External lock records remain resolver-derived and transitively complete; caller-authored nonempty records stay forbidden. Publishing those records does not make a project self-resolving: every mixed-root compiler, bundle, editor, or CLI call must receive and revalidate the exact complete alias-to-physical-root mapping again. No physical root is inferred from the lock, retained as ambient authority, or serialized into a result.

G4 exposes separate native `compile_project_mixed_module_graph`, `compile_project_mixed_module_semantic`, and `compile_project_mixed_module_bundle` APIs. Each requires an explicit project directory, a project-relative entry path, and the complete exact per-call `module_roots` mapping. The APIs verify the current G3-published lock records and mixed resolver policy, resolve only the permitted project/library edge forms, and retain the authority session through graph expansion, semantic resolution, or bundle construction. Immediately before a successful return, the retained session rechecks the project, lock, catalog, roots, module manifests, source bytes/native identities, and every resolver winner. Graph, semantic, and Bundle `0.3` results contain only canonical project/module URIs and portable digests/provenance; physical roots and native file identities never appear in artifacts or diagnostics. The existing same-project compiler, semantic, bundle, resolver, and editor APIs remain behaviorally isolated and fail closed on external aliases; G4 does not add a permissive mixed-mode flag to those legacy surfaces.

Bundle `0.3` embeds the resolved module set and expansion map, lists every module source in `dependencies`, and binds them into its hash. Native production and the H5 exact-version document/live path are implemented and accepted in installed Houdini. Frozen Bundle `0.3` and Bundle `0.4` use distinct strict decoders over the same guarded document pipeline; `0.3` receives no control-language or cross-version coercion. Unsupported, malformed, mixed, or drifted carriers remain fail-closed with typed diagnostics. The `document.*` consumer consumes only bundle content and never resolves project paths. H6 source-workspace access remains a separate optional authority.

The live schema resource surface registers GraphSpec `0.3`, `expansion-map-v1`, and `resolved-module-set-v1` separately. A client can therefore resolve GraphSpec's external expansion-map `$ref` without filesystem access; publishing GraphSpec `0.3` without its referenced standalone schema is invalid. H5 registers GraphSpec `0.4`, expansion-map v2, resolved-module-set v2, and Bundle `0.4` together as one exact compatibility unit. The build stages those resources plus the exact preview, plan, and apply schemas into the installed package; H5E proved exact running-package alignment and availability of the four installed H5 schema resources.

Native saved-file and unsaved-buffer editor APIs use the same explicit project directory, `ProjectContext`, resolver winner policy, catalog/manifest/lock pins, and exact locked module interfaces as compilation. Completion covers literal import paths, exported module names, imported aliases, parameter names/types/defaults, required arguments, and instance exports without executing or expanding modules. Go-to-definition covers imported modules and aliases, module parameters, local symbols, and instance exports. Results use only canonical project/module URIs and source digests, report whether the subject matches its lock, is modified, or is unlocked, enforce the HS6 read/aggregate/result budgets and cancellation, and recheck every selected identity before returning. These native APIs never write project state.

G4 adds separate `complete_mixed_path`, `complete_mixed_project_source`, `definition_mixed_path`, and `definition_mixed_project_source` native APIs. Their `module_roots` argument is mandatory and keyword-only on every request. The subject remains a project-relative `.hocus` file inside the selected project, including for an unsaved buffer; an external library file cannot become the editor subject. A project subject may nevertheless complete permitted external import paths/interfaces and navigate definitions into verified `hocus-module://` dependencies. The editor retains and finally rechecks the same exact mixed authority used to load those dependencies, and returns only portable URIs, spans, digests, pins, and lock-state metadata. The original same-project editor APIs remain unchanged and continue to reject external aliases. Through H5 these result schemas remain unregistered from MCP. H6 `source.project.navigate` MUST reuse these exact typed results and resolver authorities rather than defining weaker completion or definition semantics.

G5 adds the explicit repeatable CLI `--module-root ALIAS=ABSOLUTE_PATH` dispatch described above, but no editor command. Mixed saved-file and dirty-buffer completion/navigation remain Python APIs for native editor integrations, with mandatory keyword-only `module_roots`; they are not `hocus` subcommands. G5 itself adds no MCP project/root/file surface, document lowering, or live behavior. H5 provides exact bundle document/live consumption, and H6 adds the separately approved source-workspace surface without changing the frozen G5 CLI or `document.*` content contracts.

### Proposed language `0.3`: typed compile-time control

Language `0.3` source units use the exact `hocus 0.3;` header and otherwise retain the `0.2` root, type set, static import, exact typing, hygiene, capability, and host-isolation rules. They add two expression-producing control declarations. They do not add a general statement loop, a collection type, mutation, truthiness, arithmetic, comparison, callable code, or host-language execution.

The conditional form is exactly:

```hocus
if choice @id("lod-choice") (param.useDetailed) outputs (
  result: node_output,
  selectedScale: float,
) {
  node detailed @id("detailed"): "subdivide" {
    input[0] = param.source;
  }
  yield result = detailed.output[0];
  yield selectedScale = param.detailScale;
} else {
  node simple @id("simple"): "null" {
    input[0] = param.source;
  }
  yield result = simple.output[0];
  yield selectedScale = param.proxyScale;
}

node result: "null" { input[0] = choice.result; }
```

Its grammar is `if SYMBOL @id("SEED") (BOOL_EXPR) outputs (NAME: TYPE, ...) { BODY; yield ...; } else { BODY; yield ...; }`. The symbol and durable seed are mandatory. `BOOL_EXPR` is an existing scalar expression whose exact static type is `bool`; there is no truthiness conversion. `else` and a nonempty typed `outputs` list are mandatory. Each branch is a lexical child scope and MUST yield every declared output exactly once, with no undeclared or duplicate yield and with exact type equality. Both branches are parsed, name-resolved, type-checked, limit-checked, and capability-checked even when the condition is compile-time known. Only the selected branch expands, and the declaration exposes only its fixed typed members as `choice.<member>` after the declaration.

The iteration form is a bounded fold, exactly:

```hocus
for series @id("refine-series") (i in range(param.passes)) carry (
  result: node_output = param.source,
) {
  node step @id("step"): "subdivide" {
    input[0] = carry.result;
    iterations = iter.i;
  }
  yield result = step.output[0];
}

node result: "null" { input[0] = series.result; }
```

Its grammar is `for SYMBOL @id("SEED") (ITERATOR in range(COUNT_EXPR)) carry (NAME: TYPE = EXPR, ...) { BODY; yield ...; }`. The symbol, durable seed, iterator, `range(...)`, and nonempty typed `carry` list are mandatory. `COUNT_EXPR` is an existing scalar expression whose exact static type is `int`; its evaluated value MUST be an exact nonnegative integer, no greater than the fixed per-fold maximum of 4,096 and no greater than the remaining aggregate iteration budget. `range(n)` means the deterministic half-open sequence `0, 1, ..., n - 1`; no other range form, step, reverse order, break, continue, filtering, or parallel ordering exists.

Carry initializers are evaluated once in the enclosing lexical scope, in declaration order, before the first iteration; they cannot reference `iter`, `carry`, or the fold's result symbol. For iteration `i`, `iter.<iterator>` is the exact `int` index and `carry.<name>` is the previous iteration's value, or the initializer value for `i == 0`. The body is a lexical child scope and MUST yield every carry member exactly once with no undeclared or duplicate yield and exact type equality. The yielded values become the next iteration's carry. The body is parsed, name-resolved, type-checked, limit-checked, and capability-checked even when the count is zero. A zero-count fold expands no body entities and returns the initializer values unchanged. After the fold, only its fixed typed members are visible as `series.<member>`.

Control bodies accept `node`, `use`, nested `if`, and nested `for` declarations followed by their required yields. Imports, root metadata, `existing`, `adopt`, graph flags, layout/output selection, and module `export` statements cannot appear inside a control body; the enclosing root consumes the control result instead. Body-local symbols do not escape except through declared yields. `iter.<iterator>` and `carry.<name>` are legal only in the owning fold body, including its nested child control bodies; an inner fold shadows only its own distinct iterator and carry bindings. Existing expressions plus those two loop-qualified references are the complete new expression surface. In general, a control result is referenced as `SYMBOL.member`; it is an ordinary exactly typed expression and may feed a node, module argument, export, yield, or later control expression, so controls compose without widening the type system.

Every control `@id` seed shares the enclosing declaration identity-seed namespace and MUST be unique there. Selected conditional entities extend the enclosing durable identity path using the domain `hocus-control-if-branch-v1`, the control seed, and the selected branch tag; fold entities extend it using `hocus-control-for-index-v1`, the control seed, and the canonical nonnegative iteration index. These domains are distinct from module-instance and authored-node identity domains. A result-symbol, iterator, or body-local rename cannot change generated entity identity when the durable seeds and structural nesting are unchanged. Switching a branch or index necessarily selects a different domain-separated identity path. Every generated entity and substituted value retains the control declaration, selected branch or iteration index, yield, and enclosing module stack in bounded expansion provenance.

The construct is a fold rather than a collection because the language has no runtime collection value and GraphSpec has no collection carrier. A collection-producing loop would require a new list type, indexing and ordering semantics, retained values proportional to the count, and new module/bundle/GraphSpec contracts. A fold keeps a fixed statically typed result shape independent of count, gives zero iterations a total deterministic meaning, and permits each iteration's temporary lexical scope to be released after its carry and provenance are committed. It can still generate repeated graph structure while remaining chargeable to fixed expansion budgets.

The proposed `0.3` budgets add a 4,096-iteration hard maximum per fold and a 100,000 aggregate iteration-evaluation limit per compilation. Before entering a fold, expansion rejects a count exceeding either the per-fold maximum or the remaining aggregate iteration budget. Every branch evaluation, fold iteration, declaration, generated node, embedded-code byte, diagnostic, origin mapping, and nested module instance also consumes its existing applicable budget; passing the iteration admission check never reserves or bypasses those limits. Cancellation is checked before each condition, before fold admission, before each iteration, and before every yield commit.

H2 uses two pure phases. The isolated native surface is `validate_control_program` plus `expand_control_graph`; it accepts only caller-supplied entry bytes/identity, exact in-memory resolved module units, explicit limits, and an optional cancellation callback, and performs no project, filesystem, resolver, catalog, Houdini, clock, random, or network access. Whole-body validation runs first over the entry and every in-memory module, checks both conditional branches and every fold body regardless of selection/count, and emits no graph entities. Only after that succeeds does evaluation expand the selected branch and the ascending half-open fold iterations. Direct yields form one trailing contiguous block in each control body; a declaration after the first direct yield is invalid. Node declarations retain the existing forward-reference rule inside their lexical block, while module uses and control results become visible sequentially after their declarations. `param`, `iter`, and `carry` are reserved scope qualifiers and cannot be declaration symbols. Nested folds overlay only their own iterator/carry members; distinct outer members remain visible.

Each lexical declaration block has one effective durable-seed namespace shared by node seeds, module-use IDs, and control IDs. Mutually exclusive branch bodies are distinct child blocks, but both are validated. Runtime identity uses one structurally ordered durable path containing module-instance, selected-if, and fold-index domain steps; module and control paths are not concatenated in separate unordered identity inputs. The names of control results, iterators, and body-local declarations are excluded from identity when their explicit durable seeds are unchanged.

Control provenance is deliberately bounded. A mapping produced during control execution carries its current ordered lexical control stack. A yielded value retains its immediate producer frame plus direct `control_declaration`, `condition` or `fold_count`, `carry_initializer` when applicable, and `yield` origins; it does not accumulate every historical fold frame across thousands of carry commits. A zero-count result has no fabricated iteration frame: it retains declaration/count/initializer related origins and any enclosing control stack. For `if`, `selectionSpan` is the condition expression span; for `for`, it is the count expression span. Yield spans are the selected body's direct yields in source order.

H2 capability validation covers everything derivable without Houdini or a catalog, including hidden-body language/module/type rules, code-surface restrictions, and code/capability budgets. H3 MUST re-run whole-AST catalog/operator/parameter capability validation against the pinned immutable catalog, including unselected branches and zero-count bodies, before enabling native compiler/CLI/editor dispatch. Selected-only GraphSpec catalog resolution is insufficient for that gate.

H3A implements that admission boundary for the explicit same-project lane. A schema-v4/language-`0.3` native compile MUST resolve one caller-selected project-relative entry and its verified local lock closure into resolved-module-set v2, validate the complete authored AST against the exact pinned catalog before selected evaluation, expand to GraphSpec `0.4`, run selected graph semantic resolution, union capabilities from hidden and selected bodies, authenticate Bundle `0.4`, and finally recheck the project, lock, catalog, source identities, and resolver winners. Native format is lock-independent; check and compile never update the lock. External aliases, resolver-derived v4 lock publication, control-aware project editor behavior, document/live consumption, and MCP filesystem access remain outside H3A and fail closed.

H3B-H3C complete the native surface without changing the source authority: `*.hocus` files remain ordinary code under a user-selected project directory. Local v4 lock publication MUST accept explicit write authority and, when replacing a lock, its exact expected digest; it MUST independently derive the complete selected closure under a cooperating-writer lease, complete H2 and pinned whole-AST catalog validation before publication, recheck every authority input, and atomically publish only strict canonical v4 records. The CLI `--project DIRECTORY` selects the directory containing `hocus.project.toml`; `HOCUS_PROJECT_DIRECTORY` is only an explicit CLI default, never a compiler/resolver ambient input.

An external control project MUST declare each library alias and pin its raw module-manifest-v2 digest. Every mixed lock, check, compile, completion, or definition request MUST additionally receive the complete exact alias-to-absolute-root mapping for that call. Roots MUST NOT be inferred from the environment, lock, cache, or source, and MUST NOT appear in portable locks, receipts, resolved sets, bundles, completion results, or definitions. The resolver MUST retain root, manifest, source, and winner authority through the requested operation and recheck them before returning or publishing. Local-only APIs MUST reject projects with external aliases.

Native saved-file and dirty-buffer editor APIs MUST use project-relative subjects and the same verified local or mixed resolver authority as compilation. Completion and definition MUST honor nested conditional/fold lexical scopes, mutually exclusive branches, declaration order, block-forward node references, sequential module-use/control visibility, iterator/carry members, yields, imported module parameters/exports, and pinned catalog operator/parameter names. External definitions MAY return portable `hocus-module://` URIs; editor APIs MUST NOT write project state. These are native library APIs, not MCP tools or a separate editor CLI. H3 does not enable Bundle `0.4` document lowering, live Houdini mutation, or any MCP operation that reads, writes, lists, watches, resolves, completes, or navigates project files or roots.

H1 freezes the language-`0.3` carrier family as one indivisible tuple:

| Carrier | Exact H1 version |
| --- | --- |
| Language / compiler | `0.3` / `0.5.0` |
| Project manifest / project lock | v4 / v4 |
| External module manifest / module interface | v2 / unchanged v1 |
| Resolver policy / resolved module set | unchanged v1 / v2 |
| Expansion map / GraphSpec | v2 / `0.4` |
| Compiled bundle | `0.4` |

Project manifest/lock v4 and external module manifest v2 pair exactly with language `0.3`; the existing v1-v3 carriers remain immutable. Resolved-module-set v2 adds `perFoldIterations` with a maximum of 4,096 and `aggregateIterations` with a maximum of 100,000 to the existing bounded limit record. Expansion-map v2 adds an interned top-level `controlStacks` table. Every origin mapping has a nullable `controlStackId`; referenced stacks contain ordered `if` branch or `for` iteration frames carrying the durable control symbol/seed, declaration and selection spans, and yield spans. A control-stack ID is SHA-256 over domain `hocus-control-stack-v1` plus the canonical frame array; existing module-stack IDs retain domain `hocus-expansion-stack-v1`. Control-related origin roles are `control_declaration`, `condition`, `fold_count`, `carry_initializer`, and `yield`. GraphSpec `0.4` embeds that exact v2 expansion map. Bundle `0.4` binds the exact compiler/language/GraphSpec/resolved-set/expansion-map tuple and its digests.

All H1 carrier decoders are strict, bounded, duplicate-key/non-finite rejecting, and observational. They accept only the complete row above, validate canonical ordering, cross-carrier identities, source-map and bundle digests, and reject mixed or historical versions. Project/module file decoding is available only to inspect the new manifest and lock shapes; it does not authorize resolution, compilation, formatting, lock publication, editor services, document lowering, or live use. H1 schemas are offline files and are deliberately not registered as live MCP resources. H2 owns control semantic validation and expansion; H3 owns compiler/resolver/CLI/editor dispatch; H4 owns adversarial and full-support qualification.

H5 extends the existing guarded document pipeline rather than creating a control-specific mutation engine. Frozen Bundle `0.3` and strict Bundle `0.4` use distinct version paths without coercion, validate GraphSpec `0.4` and expansion-map v2, preserve authenticated module/control provenance, freshly re-resolve semantic selections against the live catalog, and lower to the canonical network document. Exact catalog operator and HDA fingerprints are authoritative; complete effective package-search provenance remains outside the claim while `HS-BLOCK-003` is open. GraphSpec `0.4`, expansion-map v2, resolved-module-set v2, Bundle `0.4`, and the H5 operation schemas are registered and staged as an exact installed compatibility unit. `document.preview_bundle`, `document.plan_bundle`, and `document.apply_plan` retain their content-only and stored-plan contracts. Plans pin exact bundle/compiler/GraphSpec, project/lock, catalog, target-document, policy, capability, ownership, revision, and expansion-provenance identities. Generated symbols map to deterministic legal live names without replacing durable IDs. Apply observes cancellation, preserves signed `managedFields` and artist-owned state, verifies realized state, and rolls back or quarantines failures through the existing lifecycle. The URI/fresh-semantic `HS-BLOCK-008` gate is resolved. Any cook acceptance step remains a separately authorized post-apply action after structural verification. At this historical H5 checkpoint, export remained a normalized flat language-`0.1` semantic handoff and did not claim to reconstruct authored module or control structure; HS7 later added the guarded language-`0.4` family/value export lane.

The historical pre-H22 repaired H5E run passed in installed Houdini 21.0.729 with exact source/build/install/running-module alignment across 37 critical modules. Three targets exercised Bundle `0.3`, `0.4`, and `0.4` in `merge`, `merge`, and `reconcile` modes. Preview was deterministic; first apply verified realized state, while newly compiled second merge and reconcile operations produced distinct non-replay plans and commits. Exact catalog drift failed with `HOCUS752` until exact restore, stale plans failed with `HOCUS753`, and an injected mid-executor failure returned `HOCUS755` after verified rollback. Target recovery through a reopened SQLite store returned committed idempotent replay. Save/reopen retained exact node, port, edge, binding, code, and referenced module/control expansion provenance across all three targets. Timestamp-controlled retention proved immediate expiry, age pruning, count pressure, byte pressure, preservation of pending and `partial_or_unknown` evidence, and exact mapped `HOCUS759` rejection when protected records exhausted capacity. The installed schema resources resolved; the normalized flat language-`0.1` export structurally recompiled and passed exact-catalog semantic and connector validation without claiming network or authored module/control reconstruction; and 67 live node observations recorded zero cooks. The historical status was `passed`, and its independent P0/P1 review was clean; it does not qualify the current H22 runtime.

H6 adds project filesystem access only through an opt-in `source.*` namespace. The host user MUST approve each canonical project root outside the request channel. The server startup/configuration surface and Houdini approval UI MUST use one canonical host-owned registry. Each approved entry receives a stable opaque `projectId` selector, but the ID is not a bearer capability: every operation and resource read MUST recheck server-side authorization for the current connection/session. Access MUST default to read-only and session-scoped. Optional persistence requires an explicit user choice. Source read, source write, generated-lock update, external-root read, and optional change notification are separate grants; selecting read-write mode MUST NOT silently grant lock updates, external access, or watching. Grants MUST support expiry and immediate revocation. Physical roots MUST NOT be returned to the client or participate in portable identities. External roots require separate grants and are read-only by default. No MCP argument may self-authorize an absolute root, infer one from `$HIP`, CWD, environment variables, lock records, or source text, or access outside an approved project.

The initial H6 operations are exactly `source.project.describe`, `source.file.search`, `source.file.read`, `source.file.apply_patch`, `source.file.write_export`, `source.project.build`, and `source.project.navigate`. `source.project.describe`, resource enumeration, and search MUST reveal only projects/files authorized to the current connection. Approved project metadata and authored files MAY also be exposed as read-only `hocus-source://{projectId}` and `hocus-source://{projectId}/{relativePath}` MCP resources. Every enumeration/fetch MUST recheck the current grant and authority-projection digest; the raw file digest is the cache validator, and revocation, expiry, or successful write immediately invalidates server-side cache entries. Digest-only change notification is optional H6N follow-up work after the H6 core; if implemented, it MUST emit only project-relative identity and digest invalidation, never source bytes or physical paths. Read operations MUST use descriptor/handle-based containment and identity verification after `HS-BLOCK-001` closes, including defenses against symlink, junction, reparse-point, and hardlink escape or swap. `source.file.apply_patch` MAY edit only authored `.hocus` files and validated project manifests inside a source-write project; it MUST create exclusively or atomically replace against an exact raw content digest. It MUST reject raw lock/catalog/bundle edits, blind overwrite, delete, recursive move, external-root write, stale authority, and stale content. A grant MUST bind an authority-projection digest covering project UID, source/module directories, alias declarations, and catalog/lock locations; a prospective manifest change to that projection MUST fail without writing and require host-user reapproval. `source.file.write_export` MUST accept only the bounded authenticated export handoff, validate its digest, resolve an authorized project-contained destination, recompile before publication, and create exclusively or replace only against the exact current destination digest. `source.project.build` MUST select exactly one action from `format`, `check`, `compile`, or `lock_update`; format/check/compile MUST NOT publish a lock. `lock_update` additionally requires explicit write intent, selected project-relative entries, the generated-lock grant, the approved complete external-root mapping retained server-side, and `expectedLockState`. The `absent` state forbids `expectedLockDigest` and publishes exclusively; the `present` state requires the exact current canonical lock digest and descriptor-safe raw-digest CAS replacement. Build and navigation MUST compose the existing native resolver/compiler/lock/editor APIs and their limits, final rechecks, portable results, and exact-root rules. Every operation and resource MUST be permission-annotated, bounded, rate-limited, and auditable without recording returned source content. Expiry or revocation MUST prevent new reads, writes, builds, navigation, and notifications immediately.

H6 freezes these operational budgets; deployments MAY configure lower values but MUST NOT exceed the hard ceilings:

| H6 workspace budget | Default | Hard ceiling |
| --- | ---: | ---: |
| Approved projects per session | 16 | 64 |
| Files returned by enumeration | 1,000 | 4,096 |
| Search matches per request | 200 | 1,000 |
| Files per read batch | 16 | 64 |
| Patch operations per request | 64 | 256 |
| Request or response payload | 2 MiB | 8 MiB |
| Concurrent builds per project / session | 1 / 2 | 1 / 8 |
| Audit events retained per project | 10,000 | 100,000 |

Every H6 mutating operation MUST establish a terminal commit boundary. Patch, export, and lock publication first prepare the exact content, compare-and-swap authority, portable receipt, and serialized response and reject an oversized response before mutation. After compilation and snapshot validation, the operation acquires the project write lease, performs its final authority/source recheck, commits once, and returns the frozen receipt. Cancellation, expiry, revocation, serialization, response-size enforcement, snapshot cleanup, registry persistence, cache invalidation, audit, and other housekeeping MUST NOT turn a confirmed commit into an error response. A projection-preserving manifest identity refresh occurs under the same lease; failure after commit invalidates project authority and requires reapproval while retaining the immutable success receipt.

Writable compilation uses a temporary compiler closure plus retained descriptor/handle-backed authority state. The temporary closure MUST be verified and removed before publication, while the retained state performs the final source and external-root recheck under the lease. That recheck binds every captured native object identity and digest and brackets their validation with matching opening and closing enumerations of the exact authored, generated, external, and external-manifest path sets so same-byte replacement or a phase-boundary resolver winner cannot be omitted. One shared 4,096-file/64 MiB snapshot budget is consumed before each project or external read and retention, not after materializing the closure. Snapshot construction and close MUST attempt every strict handle close and temporary-tree cleanup, preserve the primary typed error, report only aggregated sanitized failure stages, and become terminal only after every cleanup attempt. Native create and replacement keep rollback authority until target identity/content verification, root and parent-chain verification, and file/parent durability checks succeed. Any failure before that commit point restores the displaced object or removes the create through the retained parent descriptor and durably records the rollback. Rollback MUST first prove that the active target is still the published candidate; loss of authority during the rollback syscall itself also enters recovery. If a noncooperating writer replaced or removed the target, the implementation MUST preserve the competing target plus displaced/candidate evidence rather than overwrite or silently orphan either. Recovery/publication admission is serialized by a process lock plus an OS-wide root lock and durable `clean`, `publishing`, `orphan`, and `recovery` states. One root sentinel permits at most one unresolved incident, two digest-described artifacts, and 24 MiB, contains only portable relative identities/roles/sizes/digests, and blocks further writes across reopen even when final marker creation fails. Windows MUST durably flush evidence parent and root namespaces. Cleanup after the commit point, including descriptor closure, is best effort, sanitized, and non-masking. These phases apply on both supported Linux and Windows filesystems.

H6 rate limits use atomic monotonic sliding windows keyed by authenticated principal, session, authorized project, and category. The monotonic timestamp is sampled while holding the limiter lock so each queue remains ordered. Total and category windows are checked before either is charged; expired empty buckets are pruned with bounded work, resource enumeration uses a reserved session-resource scope, and invalid or unauthorized caller selectors share one bounded denial scope instead of allocating caller-controlled project buckets. Because `source.project.build` includes `lock_update`, its MCP metadata is conservatively mutating and non-idempotent. Its action metadata names the implemented `generated_lock` grant, while the runtime grant check remains authoritative.

H6 implementation is complete after H6G trust-boundary repair. `HS-BLOCK-001` and `HS-BLOCK-009` are closed for the approved local NTFS/Linux source-workspace lane. The six focused H6 workflows and full 40-workflow catalogue pass, as do Ruff cyclomatic/branch limits `12`/`15`, compileall, diff check, the 50-test ceiling, and the 1,200-line gate. Windows and Ubuntu 24.04 WSL acceptance cover descriptor-safe publication, rollback races, bounded durable recovery, hostile-environment cross-process lock contention, legacy-lock denial, mandatory strong Linux root identity, and project-artifact absence. Historical pre-H22 acceptance in installed Houdini 21.0.729 verified source/build/install/running hash alignment including the publication-lock and recovery-record modules, the exact seven-tool surface, source-to-live apply, flat export structural recompilation and exact-catalog semantic/connector validation followed by reconcile, Git/native-editor visibility, revocation, and zero cooks. It did not establish export network-reconstruction equivalence and does not qualify the current H22 runtime. Its independent P0/P1 closure review was clean.

H6 changes the transport available to an agent, not the source or mutation authority: `.hocus` remains ordinary Git-visible code, native editors and CLI remain fully interoperable, and only authenticated bundles plus stored plans can mutate Houdini. Unbounded loops and recursion remain forbidden. Explicitly bounded deterministic compile-time recursion remains deferred to a separate reviewed syntax, termination, identity, provenance, and budget contract and is not part of language `0.3`.

## 16.8 HS7 Fidelity Carrier and Live Contract

HS7 assigns the exact compatibility row language `0.4`, compiler `0.6.0`, GraphSpec `0.5`, Bundle `0.5`, catalog v2, expansion-map v3, resolved-module-set v3, project/lock v5, and network-document v2. Frozen `0.1`-`0.3` source and Bundle `0.2`-`0.4` lanes are never inferred, upgraded, or widened. Bundle `0.5` binds closed typed-value, named-port, graph-editor, spare-parameter, and animation semantic selections to the authenticated catalog and expansion provenance. Any cross-carrier disagreement rejects before document lowering.

At a language-`0.4` root graph, an explicit authored `@id` is the durable
entity identity and authored symbol used by export and structural recompilation. It is not hashed
a second time. Frozen language-`0.3` behavior and module/control descendant
identity domains remain unchanged, so the new rule cannot silently rewrite a
legacy project or collapse expansion-instance identity.

SOP, fixed-port material/VOP, LOP, and TOP networks use the same guarded preview, immutable-plan, apply, verify, rollback, save/reopen, reconcile, and export pipeline. Source and destination indexes remain authoritative. Language `0.4` MAY author `input["name"] = source.output["name"]` only when catalog v2 proves a complete, fixed, unique namespace and resolves both names to exact indexes; ambiguity, dynamic connectors, or incomplete evidence rejects. ROP, DOP, COP, and CHOP remain read-only, and HDA definition mutation remains rejected. Structural LOP support does not authorize direct USD layer, relationship, variant, or time-sample editing.

Typed parameter values include exact whole tuples, menu tokens, dimensioned quantities, intentionally raw paths, explicit reset, float/color ramps, bounded multiparms, fixed-language expressions, and structural channel references. Tuple components and multiparm child tokens require exact catalog evidence. Ramp kind comes from `RampParmTemplate.parmType()` and supports only declared basis enums. Multiparm instance count comes from the root parameter value, while the exact start offset comes from `multiParmStartOffset()` or matching catalog evidence; flattened child counts MUST NOT substitute for instance count. Reset verifies `parm.isAtDefault()`. Callbacks and buttons remain actions and are rejected from declarative values.

Houdini parameters whose exact live `parentMultiParm()` is non-null are nested
ramp/multiparm implementation coordinates, not independent top-level
`parameterBindings`. Live snapshots omit those coordinates before binding or
code-blob construction. Lookup/API failure retains the observation, and names
are never used to infer nesting. Artist values remain untouched live and
opaque; only an authenticated managed parent composite may create, replace, or
reset them. Canonical language-`0.4` export renders every supported tagged
value, including nested multiparm values, and recompilation must reproduce the
same authenticated value carrier.

Language `0.4` graph bodies MAY contain stable-ID `network_box`, `sticky_note`, `node_comment`, `network_dot`, and `layout_constraint` declarations. GraphSpec and network-document v2 carry these as closed entity tables. Dots preserve one exact upstream output and every exact downstream input coordinate. Network boxes preserve direct membership rather than recursive flattened membership. Layout is deterministic compiler-time positioning: automatic layout runs first and declared constraints resolve afterward. Live receipts authenticate durable IDs to current Houdini names without treating auto-suffixed names as success.

Node bodies MAY declare managed instance spares with `spare <name> @id("...")` and bounded closed properties for float/tuple, int, string, toggle, or menu interfaces. They MAY declare scalar float or int animation with `animate <parm-or-component> @id("...")`, canonical seconds, explicit authored/display FPS, fixed constant/linear/bezier key functions, optional numeric tangent fields, and bounded constant/linear/cycle/cycle-offset/oscillate extrapolation. Carrier `linear` extrapolation maps to Houdini `parmExtrapolate.Slope`. String keyframes, Python or arbitrary HScript functions, callbacks, locked HDA internals, HDA-definition edits, and USD time samples reject before mutation.

Managed spares and animation are ownership-scoped entities. Stable tag text alone never proves ownership: live mutation requires the authenticated per-node runtime receipt, exact UID/name or UID/parameter target, and matching Hocus ownership. Reconcile removes only omitted runtime entities in the target ownership namespace and preserves artist-owned or differently owned state. Apply orders spare creation before animation/bindings and spare removal afterward, verifies the realized interface and animation, and includes runtime state in inverse receipts so rollback cannot silently flatten or discard artist state.

The machine-readable matrix at `houdini://documents/hocusscript/fidelity/hs7`
and `docs/hocusscript-hs7-support-matrix.md` is authoritative. `supported`
requires source, catalog, carrier, document, live apply, save/reopen, rollback,
zero cooks, and exported source that structurally recompiles and passes
exact-catalog semantic and connector validation. That export validation is not
a network-reconstruction guarantee. Constructs without the required evidence
remain `read-only`, `preserved-opaque`, or `rejected`; no generic metadata
escape hatch changes their classification.

HS7 live acceptance passed in installed Houdini 22.0.368. SOP,
fixed-port material/VOP, LOP, and TOP fixtures completed guarded create,
reconcile, injected rollback, save/reopen, and structural export recompilation
with exact-catalog semantic/connector validation. This did not establish export
network-reconstruction equivalence. A disposable
locked HDA rejected with `document.locked_hda_boundary`; unsupported
ROP/DOP/COP/CHOP mutation and direct USD time samples failed closed. The
editor/runtime/typed extension preserved artist spare and sticky state,
restored ramp and multiparm parents to exact Houdini defaults, and completed
rollback at editor, runtime, and typed executor checkpoints. All managed
descendants recorded zero cooks. The receipt authenticated 79 critical
source/install/running modules in the historical H21 campaign; the H22
migration receipt aligned its 37 acceptance-critical modules, reported no
unavailable fixture, and rejected all four unsupported family policies. The
complete H22 catalog measured 44,342,922 UTF-8 bytes across 5,566 operators,
inside the 64 MiB admission bound. The full 40-workflow catalogue, Ruff
complexity `12`/branch `15`, compileall, schema parsing, diff check, clean
build/install, 50-test ceiling, and 1,200-line gate remain release gates for
the migrated payload.

| HS6 limit | Default |
| --- | ---: |
| Source bytes per file | 1 MiB |
| Aggregate transitive source bytes | 8 MiB |
| Resolved module files | 4,096 |
| Import depth | 64 |
| Module-instance depth | 64 |
| Module instances | 4,096 |
| Parameters or exports per module | 256 each |
| Expanded nodes | 10,000 |
| Aggregate embedded code | 4 MiB |
| Expansion/source-map entries | 100,000 |
| Diagnostics | 500 |

Import cycles are rejected. The current `0.2` implementation also rejects instantiation cycles, so recursive expansion remains unavailable in this version. Any future recursive construct must be explicitly compile-time bounded, deterministically terminating, identity-stable, and charged against instance-depth, instance, expanded-node, aggregate-code, and source-map budgets; unbounded recursion remains permanently forbidden. Cancellation is checked between reads, interface validation, each instance, and GraphSpec emission. Implementations MAY configure lower limits but never higher limits at an untrusted live boundary.

Modules MUST NOT provide:

- dynamic imports
- filesystem, process, network, environment, clock, or random access
- reflection over the host process
- unbounded loops or recursion
- hidden mutation

Same-project modules remain the default and legacy implementation lane. External aliases are available only through the separate G4 native consumers after explicit per-call root approval, library-manifest verification, transitive lock verification, containment, and hostile-path gates succeed together; CLI, MCP, document, and live enablement do not follow implicitly.

## 17. Formatting and Export Validation

- The formatter emits canonical whitespace, ordering, quoting, and LF newlines.
- Language `0.1` accepts comments, but the canonical normalized formatter intentionally discards trivia and does not preserve comments. A distinct source-preserving formatter requires a trivia-preserving concrete syntax tree and is deferred beyond the HS5 canonical-format contract.
- Formatting is idempotent.
- Live graphs can be exported to normalized HocusScript when all relevant constructs are supported.
- HocusScript `0.1` has no opaque construct. Any unsupported entity blocks the whole export; blockers are reported deterministically up to the fixed limit, with exact overflow accounting, and unsupported state is never silently dropped.
- Emitted source is structurally recompiled and checked through exact-catalog
  semantic and connector validation. This proves that the export is an
  admissible source handoff; it does not prove reconstruction or equivalence of
  the input network.
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

### 20.1 HS8 production qualification contract

HS8 retains `.hocus` as the authored graph surface and adds a separate strict
evidence layer. `asset-contract/v1` declares units, coordinate conventions,
naming, pivots, bounds, topology, normals/tangents, UV/UDIM and texel-density
requirements, material slots, LODs, collision, instancing, target-platform
budgets, USD composition, and exact dependencies. Material, LOD, collision,
and instancing requirements bind explicit delivered USD prims so intermediate
SOP labels cannot satisfy the contract. Instancing additionally binds the
serialized prototype prim path and exact representation (`native_instance` or
`point_instancer`); effective instance visibility drives rendered counts while
the delivered mesh binding retains its authored purpose and visibility.
Contract and observation decoding is bounded, path-free, finite-JSON-only,
and content-addressed.

The live production observer MUST inspect only explicitly authorized Houdini
roots, MUST reject dirty geometry or stages rather than implicitly cooking, and
MUST compare the complete authorized-root cook-count set before and after
observation. Portable evidence MUST NOT contain physical HDA, file, USD-layer,
or output paths. Production cooks are explicit measured build actions after
guarded apply; they are not hidden inside validation. Acceptance facts MUST be
derived from normalized USDA reopened as a fresh USD stage. SOP facts MAY be
cross-checked against that product but MUST NOT fill a missing default prim,
composition policy, material binding, LOD, collision, instancing, dependency,
or platform metric.

The reopened USD dependency observation MUST enumerate a complete bounded
closure of root sublayers, reference and payload arcs, used composition layers,
and authored asset dependencies. Every dependency MUST resolve to a regular
local file within the authorized output root, match exactly one declared
contract dependency by kind and digest, and be hashed from stable bytes.
Anonymous, unresolved, ambient, escaping, or ambiguous dependencies MUST fail
closed. Portable observation exposes only contract identity, digest, byte
length, and role; it MUST NOT expose resolved paths. An `inline` publish MUST
have no external composition dependency.

`build-provenance-manifest/v1` binds one portable asset and target platform to
the exact recipe, sources, compiler, catalog, modules, HDAs, inputs, and
outputs. `build-report/v1` additionally binds a valid asset-contract report,
artist-override preservation, production metrics, the selected platform budget,
a repeated clean-build comparison, a numeric comparison, and a visual
comparison. Packaging requires every check except visual comparison. Publishing
requires a matching passing packaging receipt and every check including visual
comparison. Upstream decisions and all evidence digests are authenticated;
callers cannot replace a failed packaging decision with a locally passing
publish envelope.

The single high-level MCP operation is `production.asset.qualify`. It is
read-only and non-idempotent. It performs no cook, Houdini mutation, filesystem
write, packaging, or publication and returns the strict
`production-qualification/v1` carrier. Raw packaging and publish gate decisions
are advisory technical facts. Every public caller receives
`attestationMode=content_only`, `readyForPackaging=false`, and
`readyForPublish=false`, including an authenticated context with
`review_production`; caller facts can never mint host attestation or actionable
readiness. The installed runner and detached verifier remain private authority
boundaries rather than general graph or filesystem tools. HS8 errors use
`HOCUS950`-`HOCUS959` for
contract/observation failures, `HOCUS980`-`HOCUS989` for build evidence and
gates, and `HOCUS990` for the complete qualification boundary. `HOCUS991`
remains reserved for private attestation rejection. `HOCUS998` rejects an
unsupported Houdini host or ungoverned Python loader before server construction.

Numeric comparison MUST contain exactly the canonical build-metric fields and
its candidate values MUST equal the measured metrics. Every visual comparison
MUST bind an exact candidate provenance output URI and digest. Technical
qualification may generate a deterministic contact sheet and review request,
but MUST NOT generate its own approval carrier. Release qualification requires
an externally authored and authenticated approval carrier plus an externally
authenticated clean-image/VM decision and detached-verifier pass. The approval is a
detached input with its own content identity and trust chain; it MUST bind the
exact frozen source candidate, installed manifest, review request, provenance,
output set, comparison, version, and policy. It MUST NOT be copied into the
candidate source archive or governed installation, because doing so would
change the identity it approves. A checked-in development review fixture is
non-authoritative. The candidate MUST freeze only after its approval schema,
request generator, verifier, baseline, and detached-input plumbing are final.

The same-host two-process runner verifies installed harness, fixture, complete
governed module bytes, effective package-search provenance, and source/install
alignment, and proves only fresh-process determinism on that host. The
`hs8-clean-image-environment/v1` carrier retains an integrity digest but no
authority; its wrapper is therefore evidence-only and always
non-authoritative. External authority uses the separately supplied strict
`hs8-release-trust-policy/v1`,
`hs8-external-clean-image-attestation/v1`,
`hs8-signed-visual-approval/v1`, and
`hs8-final-release-decision/v1` carriers. The offline verifier requires
role-separated Ed25519 principals, validity windows, exact policy identity,
and exact independently supplied candidate/source/install/runtime/environment/
dependency/technical bindings. The final decision additionally binds the
exact signed visual approval after clean-image/visual/decision chronology
checks. No private key or trust policy is generated by the
repository. A clean-image or release claim remains unavailable until external
CI and the release authority issue those signed carriers; local execution
cannot satisfy that boundary.

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
- structural export recompilation plus exact-catalog semantic and connector
  validation, without a network-reconstruction guarantee
- required 1k-node performance and payload budgets; 10k-node scale remains a
  separately defined post-v1 target
- at least one production fixture covering geometry, materials, UVs, LODs, collision, USD/publish outputs, validation, and visual comparison

## 22. HS1 Target Boundary

The historical HS1 implementation target was intentionally preview-only:

- pure-Python lexer, source positions, parser, AST, structural compiler, and formatter
- version header, one graph, target, category, mode, revision, ownership, existing/adopt, nodes, indexed inputs, scalar/array values, tagged code, display/render/output, and auto layout
- deterministic GraphSpec serialization and structured diagnostics
- offline unit and golden tests

At HS1 this target did not lower to a live apply plan or mutate Houdini. Those
later gates are now implemented through the exact Bundle `0.2`/`0.3`/`0.4`/`0.5`
preview, immutable-plan, and guarded-apply path described in section 14; the
structural `document.compile_source` compatibility endpoint itself remains
non-applyable.
