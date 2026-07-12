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

The manifest digest covers the exact bounded manifest bytes. The lock digest covers canonical JSON with sorted keys, so lock whitespace and key order do not create false bundle drift. Lock updates are explicit native operations through `hocus lock --update`; they are never performed by check, compile, format, or MCP.

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

The Houdini boundary is content-based. The shared standard-library `decode_compiled_bundle()` trust boundary validates exact fields, supported versions, canonical digest, bounded complexity, finite values, portable provenance, source/dependency records, source maps, GraphSpec envelope consistency, and capabilities derived from graph content. It never reads paths or Houdini state. Source bytes are not embedded, so the decoder validates the integrity of source-digest claims, not their external authenticity.

MCP progression:

- `document.compile_source` remains an optional compatibility/convenience endpoint for unsaved source text. It never accepts a project directory or reads a path.
- `document.preview_bundle` accepts compiled bundle content through `decode_compiled_bundle()`, resolves it against the current Houdini catalog/baseline, and returns a non-mutating diff and candidate plan.
- `document.plan_bundle` persists an immutable guarded plan only after all HS4 gates pass.
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
- The graph `output` directive lowers to an explicit network-document `output_flag` edge and `set_output` candidate operation; it is not hidden in metadata. HS4 must provide a network-family adapter or block apply where Houdini exposes no safe setter.
- `layout = auto` uses the deterministic `hocus-grid-v1` document layout for authored mutable nodes, so previewed positions are explicit and verification does not depend on Houdini UI auto-layout behavior.

### 8.7 Parameters

- Parameter names resolve against exact catalog parameter tokens, not UI labels.
- Scalar-to-tuple coercion is forbidden unless the catalog explicitly declares it.
- Menu values use stable tokens rather than localized labels.
- Parameter defaults are distinct from explicit values.
- Button parameters, callbacks, and other actions are not ordinary assignments.

The AST and GraphSpec reserve first-class forms for tuples, ramps, multiparms, expressions, channel references, keyframes, time samples, units, and resets. Unsupported forms MUST produce diagnostics rather than be approximated or discarded.

Network-document v1 carries scalar literal bindings. HocusScript `0.1` scalar component assignments lower directly. Whole-tuple assignments currently stop with `HOCUS708` because compiled-bundle v0.2 does not retain the ordered component-token mapping required for safe expansion. Ramp and multiparm assignments are rejected by both schema and runtime. A later compatible bundle/schema version must carry the missing structure before enabling those forms.

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

Compiler `0.4.0` MUST retain the existing `0.1` parser and emit GraphSpec `0.2`; it emits GraphSpec `0.3` and bundle `0.3` only for language `0.2`. Decoders reject mixed pairs rather than upgrading them implicitly. Portable language `0.2` compilation requires future project manifest/lock v3; v1 and v2 remain immutable.

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

### 14.2 `document.preview_bundle` and `document.plan_bundle`

HS3 `document.preview_bundle` accepts a canonical compiled-bundle v0.2 object, passes it through the shared strict decoder, rehydrates GraphSpec, and freshly re-resolves the graph against the current live catalog. The fresh semantic result must exactly match the bundle selections; a recomputed content hash does not make forged selections trustworthy. The operation then overlays the complete live network-document baseline, validates the resulting document, and returns a deterministic diff, destructive summary, source maps, and a non-applyable candidate plan.

The MCP operation accepts content, not paths. It never reads DSL/project source files and never mutates Houdini. Live catalog provenance may inspect the installed Houdini/HDA/package environment. Preview artifacts up to the configured memory limit are content-addressed at `houdini://documents/previews/{preview_id}`; payloads larger than the inline threshold are returned only through that resource. Per-artifact and aggregate byte budgets plus LRU/TTL eviction bound Houdini-process memory.

Bundle catalog drift, semantic-selection drift, document-revision drift, schema errors, unsafe ownership/collision conditions, unsupported values, or missing source provenance produce blocking diagnostics and no candidate plan. Imports remain an offline compiler responsibility when the active language version supports them.

HS4 `document.plan_bundle` reruns the same strict live trust gates, normalizes the verified target into the executable SOP operation groups, rejects unknown or irreversible actions, captures the exact baseline and inverse plan, and persists a `hocus_apply_plan` v1 envelope. The envelope has an independent hash domain from the HS3 candidate plan and binds its UUID, TTL, process/hip session epoch, source/bundle/compiler/GraphSpec/project manifest and lock identities, catalog fingerprint/content digest, effective policy fingerprint, capabilities, ownership, target scope, baseline document/live revisions and digest, target document, confirmation policy, normalized operations, and inverse plan. The SQLite record is insert-only; mutable apply lifecycle state is stored separately. A bundle containing preview-only workspace provenance cannot produce a stored plan.

Plans are available at `houdini://documents/plans/{plan_id}` and are bounded by count, per-plan size, aggregate size, TTL, and LRU retention in the live cache. `document.discard_plan` removes the cache entry and durably claims the persisted plan as aborted so it cannot be applied after a restart.

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

The plan is never rebuilt from source. A freshly normalized operation set is computed only as a validation oracle and must byte-match the stored execution plan; the stored plan remains the sole execution authority. Hocus-generated preview documents are rejected by legacy `document.apply`, and any code-blob installation dynamically requires `run_code` in addition to `edit_scene`.

Large plans MAY become cancellable tasks.

### 14.4 HS5 editor and export interfaces

`document.format_source` and `document.complete_source` accept unsaved text only. They never accept or infer a project directory. Formatting returns canonical source only when parsing and structural validation succeed. Completion uses the current live catalog, is deterministically ordered and bounded to 200 items, and returns an exact replacement span. All source offsets in the HS5 JSON contracts are Unicode code-point offsets, matching Python string indexing; an LSP adapter must explicitly translate to and from UTF-16 positions.

`document.export_source` accepts a live `root_path` and optional graph identifier, never a physical destination. It force-refreshes the selected network document, preflights the entire supported projection, verifies emitted source by recompiling against the exact live catalog fingerprint, and returns either:

- canonical source plus source digest, persistent entity identities, managed fields, ownership namespaces, catalog fingerprint, root path, and document identity/revision; or
- `source = null` plus a deterministically ordered blocker list bounded to 500 entries; overflow retains 499 blockers and a final `HOCUS819` sentinel with the exact omitted count.

The serialized export result and native `write-export` handoff share a 16 MiB UTF-8 budget. An otherwise valid result that exceeds it fails closed with `HOCUS820`, minimal provenance, and no source; clients should narrow the network scope rather than bypass the handoff contract.

Exported source is a baseline-preserving merge projection, not an implicit claim over every representable Houdini value. The root container anchors target/output identity but is not emitted as a DSL node. The root and every exported child require persistent user-data identity. Only parameters, input slots, and flags named by valid signed node `managedFields` provenance are portable source-owned fields. Root, default, and artist-owned state is omitted from source and enumerated in `provenance.preservedState`; recompiling/lowering against the captured baseline preserves it exactly. Moving such source to a clean baseline does not recreate preserved state, and tooling must surface that provenance rather than imply clean-rebuild equivalence.

HS5 export is deliberately fail-closed. Its supported subset is one flat SOP network containing persistent unique node UIDs, exact catalog-resolvable operator types, indexed data connections, finite scalar/menu literals (including representable scalar tuple-component tokens), supported VEX/Python/HScript code bindings, and representable display/render/output state. It rejects nested networks, cross-network edges, unsupported edge/port kinds, bypass/template state, expressions and channel references, animation/keyframes, whole-tuple values, ramps, multiparms, spare parameters, unsupported code, invalid identifiers, orphan entities, mixed/incomplete ownership, duplicate/nonpersistent IDs, and any state it cannot reproduce exactly. HocusScript 0.1 has no opaque syntax, so nothing may be silently omitted or approximated.

The native `hocus write-export` command owns the filesystem handoff. It accepts the same bounded export response emitted by MCP, requires an explicit `--project` (or explicit editor setting/environment equivalent), resolves a project-contained `.hocus` destination through configured source directories, validates the handoff digest and recompiles before writing, creates exclusively by default, and permits replacement only with the destination's exact expected digest. Houdini MCP never reads or writes the DSL project.

For language `0.2`, the same native `hocus check`, `hocus format`, and `hocus compile` commands dispatch from the selected manifest rather than sniffing source headers. `check` verifies the complete locked module closure and pinned catalog semantics; `check --json` emits one portable JSON result even on syntax/project failure. `format` reads and formats exactly one contained graph or module file without consuming the lock, so it remains usable to repair stale projects. `compile` invokes the one-shot project-to-Bundle `0.3` producer and never accepts caller-supplied semantic selections. Bundle output creates exclusively by default and permits replacement only with `--expected-output-digest` equal to the current raw output-file digest. Text diagnostics use stderr; requested source/JSON/bundle content alone uses stdout. `--no-strict` remains a `0.1` compatibility option and is rejected for `0.2`, whose header is mandatory.

`hocus lock --update ENTRY...` is the sole `0.2` CLI write path for module records. The command itself is explicit write authority, delegates to resolver-derived lock construction, and requires `--expected-lock-digest` for an existing lock while forbidding a replacement digest for creation. Its receipt is portable and host-path-free. The tested canonical executable surface is `python -m hocuspocus.hocusscript`; a separately packaged bare `hocus` console script is not implied by the Houdini package layout.

## 15. Rollback and Recovery

- Apply plans exclude irreversible actions.
- A pre-apply scoped snapshot and inverse plan are recorded.
- Failure first uses the uniquely labelled apply-owned Houdini undo record; the stored structural inverse is a secondary recovery attempt.
- Rollback is reimported and verified.
- A failed rollback returns `partial_or_unknown`, quarantines the scope, and requires explicit resync or recovery.
- Store commits use pending, committed, aborted, and `partial_or_unknown` states; the last state quarantines overlapping parent/child scopes.
- Startup/lazy recovery treats durable pending and `partial_or_unknown` commits as quarantined. `document.recover_scope` force-reimports under the same scope lease and releases quarantine only when live state classifies exactly as the stored baseline or verified target; any third state remains quarantined.
- Client timeout and retry behavior are controlled by idempotency keys.
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

Imports have the single static form `import { ExportedName as LocalName } from "literal.hocus";`; `as LocalName` MAY be omitted. Specifiers require an exact `.hocus` suffix and never infer extensions or index files. `ExportedName` must equal the imported file's one module declaration. Every instance uses `use local @id("durable-seed") = ModuleName(name = value, ...);`; its bounded seed follows the node-ID lexical pattern and is unique within its enclosing graph/module. Nodes and instances share one local symbol namespace. Modules cannot declare a target, mode, ownership, external/adopt reference, or graph flag. A module-local node/use `@id` is only a namespaced identity seed, never a direct network-document UID; node seeds are optional and fall back to the local symbol, while every `use` seed is mandatory. Conditionals, iteration, and recursion are not part of the initial `0.2` core.

Resolution is deterministic and native-only:

1. `./` and `../` specifiers resolve relative to the importing file after canonical containment checks.
2. Non-relative local specifiers search ordered manifest `module_directories`; the first match is selected and locked. Adding an earlier match makes verification stale and requires an explicit lock update.
3. `@alias/path.hocus` resolves only through a manifest-declared alias. The alias declares expected external library UID and version; its physical root comes from a separate explicit CLI/editor approval such as `--module-root alias=path`. Host paths never enter portable artifacts.
4. Every file remains inside the project or separately approved alias root after symlink/junction-aware canonicalization. Absolute imports, dynamic strings, environment lookup, network fetches, and implicit Houdini/package searches are rejected.

Local module files use `hocus-project://<project-uid>/<relative-path>`; approved external libraries use `hocus-module://<library-uid>/<relative-path>`. Lexical import aliases and instance symbols are not identity. Stable module identity is canonical URI plus declared name. Expanded identity derives from graph identity, the ordered nested instance-`@id` seed path, module URI, and the local node/use `@id` seed or symbol fallback. A `use` symbol may therefore be renamed without replacing its expanded entities when its seed is unchanged. Argument values do not change identity. Generated symbols use a reserved collision-proof encoding; authored `__hocus_` symbols are forbidden.

Expansion is pure, after import/interface validation and before catalog resolution. It produces flat GraphSpec `0.3`, strict `resolved-module-set-v1`, and strict `expansion-map-v1`. GraphSpec `0.3` embeds that exact standalone expansion-map object rather than defining a second projection. The expanded graph is inspectable as JSON or normalized generated source, but module files remain the editable authority; editing generated expansion is not a source round trip.

Every generated GraphSpec pointer has a primary source span and nullable `stackId`. `expansion-map-v1` interns ordered expansion stacks in one top-level `stacks` array; mappings never repeat frames. A stack ID is SHA-256 over domain `hocus-expansion-stack-v1` plus the canonical frame array. Stacks are sorted and unique by `stackId`; every non-null mapping reference resolves exactly once, and unreferenced stacks are forbidden. Each frame identifies module URI and source digest, module name, instance symbol, durable instance-ID path, import span when applicable, and `use` span. A null `stackId` means the entry source has no module-expansion frame. Substituted arguments point primarily to the call-site argument and retain the parameter declaration as related origin. Diagnostics resolve and reuse the same interned frames. Document lowering consumes per-entity module URI, source digest, durable instance-ID path, and origin rather than hardcoding the entry source.

Portable manifest/lock v3 is a new schema pair. Manifest v3 adds ordered `module_directories` and logical aliases without approved host roots. External roots contain `hocus.module.toml` v1 with stable library UID, strict SemVer 2.0 version (including optional pre-release and build metadata), supported language versions, and allowed entry modules. The same SemVer grammar applies to manifest aliases, lock records, resolved module sets, and bundle module dependencies. Lock v3 preserves the v2 catalog pin and records every transitive module by canonical URI, source and interface digests, project/library identity, version and module-manifest digest when applicable, resolved alias when applicable, and sorted dependency URIs. Ordering is by module URI. Compile is verify-only. `hocus lock --update` derives every same-project nonempty record from actual contained source, is explicit, expected-digest guarded, and atomic for cooperating writers; compile and MCP never write locks. External-library records remain disabled until separately approved roots and module manifests land together.

Bundle `0.3` embeds the resolved module set and expansion map, lists every module source in `dependencies`, and binds them into its hash. Native production is implemented. Live consumption remains disabled by `HOCUS700` until `HS-BLOCK-008` and the fresh live-semantic gates close; when enabled, MCP will consume only bundle content and will never resolve project paths or read the project.

The live schema resource surface registers GraphSpec `0.3`, `expansion-map-v1`, and `resolved-module-set-v1` separately. A client can therefore resolve GraphSpec's external expansion-map `$ref` without filesystem access; publishing GraphSpec `0.3` without its referenced standalone schema is invalid.

Native saved-file and unsaved-buffer editor APIs use the same explicit project directory, `ProjectContext`, resolver winner policy, catalog/manifest/lock pins, and exact locked module interfaces as compilation. Completion covers literal import paths, exported module names, imported aliases, parameter names/types/defaults, required arguments, and instance exports without executing or expanding modules. Go-to-definition covers imported modules and aliases, module parameters, local symbols, and instance exports. Results use only canonical project/module URIs and source digests, report whether the subject matches its lock, is modified, or is unlocked, enforce the HS6 read/aggregate/result budgets and cancellation, and recheck every selected identity before returning. These native APIs never write project state. Their strict result schemas are deliberately not registered as MCP resources because `.hocus` files remain ordinary code and the Houdini MCP completion endpoint stays content-only and source-local unless a future call supplies a separate bounded module-interface snapshot.

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

Import and instantiation cycles are rejected; recursion has a limit of zero. Cancellation is checked between reads, interface validation, each instance, and GraphSpec emission. Implementations MAY configure lower limits but never higher limits at an untrusted live boundary.

Modules MUST NOT provide:

- dynamic imports
- filesystem, process, network, environment, clock, or random access
- reflection over the host process
- unbounded loops or recursion
- hidden mutation

Same-project modules are the first implementation slice. External aliases may be enabled only when separate approval, library manifest, transitive lock, containment, and hostile-path gates land together.

## 17. Formatting, Export, and Round-Trip

- The formatter emits canonical whitespace, ordering, quoting, and LF newlines.
- Language `0.1` accepts comments, but the canonical normalized formatter intentionally discards trivia and does not preserve comments. A distinct source-preserving formatter requires a trivia-preserving concrete syntax tree and is deferred beyond the HS5 canonical-format contract.
- Formatting is idempotent.
- Live graphs can be exported to normalized HocusScript when all relevant constructs are supported.
- HocusScript `0.1` has no opaque construct. Any unsupported entity blocks the whole export; blockers are reported deterministically up to the fixed limit, with exact overflow accounting, and unsupported state is never silently dropped.
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
