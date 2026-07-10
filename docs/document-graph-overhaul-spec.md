# HocusPocus Document Graph Overhaul Spec

Status: proposal

Scope:

- replace the current node-centric MCP authoring model with a document-centric graph architecture
- make subnetworks and networks the primary unit of authoring, validation, diffing, and apply
- keep live Houdini as the execution substrate while moving MCP-facing state into an intermediary graph layer

Targets:

- Houdini 21.x
- MCP protocol revision `2025-11-25`
- interactive Houdini session first
- `hython` compatibility second

Locked contract artifacts:

- `docs/document-contract-v1.md`
- `docs/schemas/network-document-v1.schema.json`

## 1. Problem Statement

The current server already has useful graph reads and grouped mutation helpers, but the core design is still wrong for agentic authoring:

- the public surface is still dominated by `node.*`, `parm.*`, and imperative batch operations
- `houdini://graph/*` resources are snapshots, not first-class editable documents
- `graph.apply_patch` is still a thin wrapper over imperative operations rather than a true document compiler
- the in-memory graph cache is an index over live state, not an authoritative intermediary model
- subnetworks are represented only as paths inside a flattened graph snapshot, not as independent editable documents
- Houdini-specific minutiae such as wiring, parm typing, expression handling, wrangle snippets, and network boundaries leak directly into the MCP contract

That forces agents to think like low-level Houdini operators instead of like editors working on structured source documents.

## 2. Design Goals

Primary goals:

- make network documents the canonical MCP authoring surface
- mirror Houdini hierarchy directly: scene -> network -> subnetwork -> node
- expose full graph documents as stable JSON so agents can read, diff, edit, and resend them like source code
- centralize Houdini-specific translation in the backend instead of the agent
- support document-level validation, diff, apply, and rollback
- support both pull-from-Houdini and push-to-Houdini synchronization
- preserve undo-friendly live edits in Houdini while giving agents a stronger authoring abstraction

Secondary goals:

- keep targeted graph queries fast without materializing the whole scene every time
- make large scenes practical by treating network documents as independently addressable units
- preserve compatibility long enough to migrate existing agent workflows and higher-level tools

## 3. Non-Goals

Not in scope for the first overhaul slice:

- a remote database service such as Neo4j, JanusGraph, or a separate persistence daemon
- realtime multi-user collaborative editing
- full HDA-definition authoring parity on day one
- perfect round-trip fidelity for every obscure HOM surface before the core document model exists
- replacing HOM as the live execution authority

## 4. Hard Design Decisions

### 4.1 The "graph database layer" is embedded, not external

The right design is an embedded graph store inside the Houdini-hosted server, not a separate graph database product.

Reason:

- the live Houdini session is already the hard state boundary
- adding a remote graph database would increase latency, deployment complexity, and failure modes without solving the actual authoring problem
- the server needs transactional locality with the live scene, not another distributed system

The intermediary layer should therefore be:

- embedded
- revisioned
- queryable like a graph store
- persisted locally
- projected into editable JSON documents

### 4.2 Network documents are the unit of authorship

The primary authoring unit is not a node and not the whole scene. It is a network document.

Examples:

- `/obj`
- `/obj/geo1`
- `/mat`
- `/stage`
- `/tasks/topnet1`
- any subnet, VOP network, LOP subnet, material builder, or similar nested network container

The scene document is a manifest over root networks. Each network can recursively reference child network documents.

### 4.3 JSON documents are the MCP contract

Agents should not need to construct imperative node calls for normal graph editing. They should:

1. read a document resource
2. edit the JSON
3. validate or diff it
4. apply it

Imperative node tools become migration shims, not the center of the design.

### 4.4 The graph store is authoritative for MCP authoring, but Houdini still matters

For MCP-driven workflows, the graph store is the canonical authoring model.

For runtime execution and external edits:

- Houdini remains the live execution substrate
- direct user edits in Houdini are observed and imported back into the graph store
- apply operations compile documents into live Houdini mutations and then verify the resulting live state

This is a bidirectional sync architecture with a clear authoring contract, not a one-way export step.

## 5. Target Architecture

```text
MCP Client
  -> Document Resources / Document Tools
    -> Document Service
      -> Embedded Graph Store
      -> Validation + Diff Engine
      -> Apply Compiler
      -> Live Sync Adapter
        -> Houdini HOM Session
```

## 5.1 Major Components

### A. Embedded Graph Store

Responsibilities:

- persist document revisions
- store graph entities and relationships
- maintain path, uid, type, and dependency indexes
- track working copies and apply commits
- project canonical JSON documents on demand

Recommended implementation:

- SQLite with WAL mode for durability and crash safety
- relational indexes plus JSON payload columns
- in-memory projection cache for hot documents

### B. Document Service

Responsibilities:

- open scene or network documents
- create and manage working copies
- emit canonical JSON
- compute document diffs
- enforce optimistic concurrency using revisions

### C. Validation and Diff Engine

Responsibilities:

- schema validation
- referential integrity validation
- node-type and parm-surface validation
- edge and port validation
- code-blob validation
- policy validation
- structured diagnostics with JSON pointers and Houdini path context

### D. Apply Compiler

Responsibilities:

- compare baseline document vs target document
- build an ordered apply plan
- translate document fields into Houdini operations
- handle create, rename, delete, reparent, connect, disconnect, parm writes, expressions, flags, layout, and scripts
- verify post-apply live state

### E. Live Sync Adapter

Responsibilities:

- import live Houdini networks into the graph store
- observe dirty paths from the scene monitor
- reimport changed network scopes
- record external mutations as graph-store commits

## 5.2 Request Flow

Read flow:

1. Agent reads `houdini://documents/network/{path}`.
2. Document service checks whether that network scope is clean or needs sync from Houdini.
3. Graph store returns the latest canonical document projection.
4. Resource returns JSON plus document metadata and revision ids.

Edit flow:

1. Agent reads a network document.
2. Agent edits JSON locally or creates a server-side checkout.
3. Agent calls `document.validate` or `document.diff`.
4. Agent calls `document.apply`.
5. Apply compiler generates a live mutation plan for the target network scope.
6. Live mutation runs inside one Houdini undo group and one graph-store transaction.
7. Resulting live network is reimported and verified.
8. Updated document revision is returned.

## 6. Storage Model

## 6.1 Persistence Strategy

Recommended database file:

- under the HocusPocus state directory
- one database per live session or per open hip file lineage
- WAL enabled

Recommended core tables:

- `documents`
- `document_versions`
- `nodes`
- `edges`
- `ports`
- `parameter_bindings`
- `code_blobs`
- `diagnostics`
- `checkouts`
- `apply_commits`
- `live_sync_state`

Recommended index keys:

- document id
- root path
- node uid
- node path
- node type name
- edge endpoints
- owning document revision
- live revision

## 6.2 Revision Model

Each document revision tracks:

- `storeRevision`
- `documentRevision`
- `baselineLiveRevision`
- `lastSyncedLiveRevision`
- `applyCommitId`

Concurrency model:

- `document.apply` must accept `expected_document_revision`
- apply fails fast on mismatch unless explicit rebase behavior is requested

## 7. Canonical Document Model

## 7.1 Core Principle

The graph store does not expose arbitrary internal tables directly to agents. It exposes canonical document projections.

The primary document types are:

- `scene_document`
- `network_document`
- `checkout_document`
- `diagnostic_report`

## 7.2 Scene Document

The scene document is a manifest over root networks and scene-wide metadata.

It includes:

- hip file metadata
- scene revision metadata
- root network document references such as `/obj`, `/stage`, `/mat`, `/tasks`, `/out`
- optional scene-wide dependencies and diagnostics

## 7.3 Network Document

The network document is the main authoring unit.

It includes:

- root network identity and Houdini path
- node records
- port records
- structural edges
- parameter bindings
- code blobs
- layout metadata
- child network references for subnet-like nodes
- diagnostics

Every network-like node can own a child network document.

## 7.4 Entity Types

Required entity families:

- `node`
- `port`
- `edge`
- `parameter_binding`
- `code_blob`
- `asset_reference`
- `diagnostic`

### Node

Required fields:

- `uid`
- `name`
- `typeName`
- `category`
- `path`
- `parentPath`
- `isNetwork`
- `flags`
- `position`
- `metadata`

Optional fields:

- `subnetworkDocumentId`
- `definitionRef`
- `tags`
- `spareParms`

### Port

Required fields:

- `uid`
- `nodeUid`
- `direction`
- `name`
- `index`
- `kind`

### Edge

Required fields:

- `uid`
- `kind`
- `from`
- `to`

Supported edge kinds:

- `data`
- `parameter_reference`
- `material_binding`
- `display_flag`
- `render_flag`
- `output_flag`
- `dependency`

### Parameter Binding

Required fields:

- `uid`
- `nodeUid`
- `parmName`
- `valueMode`

Supported value modes:

- `literal`
- `expression`
- `channel_reference`
- `code_reference`
- `ramp`
- `multiparm`

### Code Blob

Required fields:

- `uid`
- `language`
- `body`
- `target`

Supported languages initially:

- `vex`
- `python`
- `hscript`

Supported targets initially:

- wrangle snippet parms
- Python SOP or TOP script parms
- parameter callback scripts
- menu scripts
- node-embedded source parms where the node type supports them

## 7.5 Canonical JSON Shape

Illustrative network document:

```json
{
  "$schema": "hocuspocus://schemas/network-document/v1",
  "kind": "network_document",
  "documentId": "network:/obj/geo1",
  "documentRevision": 12,
  "baselineLiveRevision": 884,
  "rootPath": "/obj/geo1",
  "category": "Sop",
  "nodes": [
    {
      "uid": "node:box1",
      "name": "box1",
      "typeName": "box",
      "category": "Sop",
      "path": "/obj/geo1/box1",
      "parentPath": "/obj/geo1",
      "isNetwork": false,
      "position": [0.0, 0.0],
      "flags": {
        "display": false,
        "render": false,
        "bypass": false,
        "template": false
      },
      "metadata": {}
    },
    {
      "uid": "node:wrangle1",
      "name": "wrangle1",
      "typeName": "attribwrangle",
      "category": "Sop",
      "path": "/obj/geo1/wrangle1",
      "parentPath": "/obj/geo1",
      "isNetwork": false,
      "position": [2.0, 0.0],
      "flags": {
        "display": true,
        "render": true,
        "bypass": false,
        "template": false
      },
      "metadata": {}
    }
  ],
  "edges": [
    {
      "uid": "edge:data:1",
      "kind": "data",
      "from": {"nodeUid": "node:box1", "portIndex": 0},
      "to": {"nodeUid": "node:wrangle1", "portIndex": 0}
    }
  ],
  "parameterBindings": [
    {
      "uid": "parm:wrangle1/snippet",
      "nodeUid": "node:wrangle1",
      "parmName": "snippet",
      "valueMode": "code_reference",
      "codeBlobUid": "code:vex:wrangle1"
    }
  ],
  "codeBlobs": [
    {
      "uid": "code:vex:wrangle1",
      "language": "vex",
      "target": {
        "nodeUid": "node:wrangle1",
        "parmName": "snippet"
      },
      "body": "@Cd = {1,0,0};"
    }
  ],
  "diagnostics": []
}
```

## 7.6 Document Stability Rules

To make documents editable like source code, the server must emit them canonically:

- stable key ordering
- stable sorting for nodes, edges, and bindings
- explicit numeric indexes for ports
- stable `uid` values across renames and moves
- pretty-printed JSON output

Paths remain useful for humans, but internal references should prefer stable ids over raw paths.

## 8. MCP Surface

## 8.1 Resources

Primary read resources:

- `houdini://documents/scene`
- `houdini://documents/network/{path}`
- `houdini://documents/checkouts/{checkout_id}`
- `houdini://documents/diagnostics/{checkout_id}`
- `houdini://documents/schema/network-document/v1`

Rules:

- resources return canonical JSON documents
- the same document shape returned by resources is accepted by `document.apply`
- resources are scoped to scene or network boundaries, not individual node summaries

## 8.2 Tools

Required first-wave tools:

| Tool | Purpose |
| --- | --- |
| `document.checkout` | Create a working copy from a scene or network document. |
| `document.validate` | Validate a supplied document or a checkout. |
| `document.diff` | Diff baseline vs target document or checkout. |
| `document.apply` | Apply a full document or checkout to Houdini and commit the resulting revision. |
| `document.discard_checkout` | Delete a working copy. |
| `document.query` | Query the embedded graph store without materializing the full scene document. |
| `document.sync_from_houdini` | Force reimport of a scene or network scope after external live edits. |

Optional but recommended:

- `document.list_checkouts`
- `document.get_apply_commit`
- `document.export_json`

## 8.3 Apply Modes

`document.apply` must support explicit modes:

- `reconcile`
  - target document is the desired truth for the scoped network
  - missing nodes and edges may be deleted
- `merge`
  - only touched entities are created or updated
  - unspecified live entities are preserved
- `validate_only`
  - no live mutation
  - compile and diagnostics only

Default mode:

- `reconcile` for checkout-based applies
- `validate_only` for explicit dry runs

## 8.4 Compatibility Surface

Legacy tools remain temporarily, but their role changes:

- `node.*` and `parm.*` become compatibility shims
- `graph.apply_patch` becomes a translator into document changes, not a direct executor
- `graph.query` can remain as a thin query facade over `document.query`

They should be hidden from default discovery once the document surface is stable.

## 9. Apply Compiler

## 9.1 Compilation Stages

1. Parse and normalize document input.
2. Validate schema and semantic constraints.
3. Resolve stable ids, paths, and network scopes.
4. Build a structural diff against the baseline document.
5. Build an ordered apply plan.
6. Execute the plan in Houdini inside one undo group.
7. Reimport the affected scope from Houdini.
8. Verify resulting store state against the applied target.

## 9.2 Ordered Apply Plan

The apply plan should be explicitly ordered:

1. create missing network containers
2. create nodes
3. rename or reparent nodes
4. create or reconcile ports if needed
5. wire structural edges
6. write parameters
7. install expressions and channel references
8. install code blobs
9. set flags and layout
10. delete removed edges and nodes
11. run final verification

This ordering keeps the backend responsible for Houdini's operational constraints.

## 9.3 Code and Script Handling

The backend must own code translation instead of forcing agents to know each node's storage quirks.

Examples:

- VEX snippets in wrangles are represented as `code_blob` entities and compiled into snippet parms
- Python SOP code is represented as a code blob and installed into the correct parm or section
- parameter callbacks are represented in document form and translated into Houdini callback script storage
- channel references are represented structurally and compiled into actual expression strings where required

This is one of the main reasons the intermediary layer exists.

## 10. Live Sync Model

## 10.1 Import From Houdini

The server needs a real importer, not only a snapshot builder.

Importer requirements:

- import one network scope at a time
- preserve stable ids where possible
- detect renames and moves without rewriting the entire identity graph
- map live HOM state into canonical document entities

## 10.2 Dirty Scope Tracking

The scene monitor should mark affected network scopes dirty when:

- nodes are added, removed, renamed, or reparented
- wires change
- parms change
- flags or layout change
- subnet contents change

A dirty scope should be reimported before the next read or apply involving that scope.

## 10.3 External Mutation Commits

When a user edits the scene directly in Houdini:

- the importer creates a new graph-store revision
- the commit is marked as `source = external_live_edit`
- existing checkout applies against stale revisions should fail with a clear rebase error

## 11. Diagnostics and Safety

Required diagnostic classes:

- schema
- invalid node type
- invalid port
- invalid parm
- broken reference
- code parse or compile error
- locked HDA boundary
- policy violation
- live apply verification mismatch

Every diagnostic should include:

- severity
- machine-readable code
- message
- JSON pointer into the document when applicable
- Houdini path when applicable

Safety rules:

- all document applies run through capability checks
- risky code surfaces still require explicit `run_code` style permission
- apply operations must be auditable at document and live-op levels

## 12. Migration Plan

The overhaul should not be a blind big-bang rewrite.

Recommended sequence:

1. build the embedded graph store and importer behind the current graph cache
2. expose document resources in parallel with current graph resources
3. ship `document.validate`, `document.diff`, and read-only query support
4. implement `document.apply` for a limited network scope first, ideally SOP networks
5. port higher-level tools onto the document pipeline
6. turn imperative graph tools into shims
7. deprecate direct low-level tools from default discovery

## 13. Success Criteria

This overhaul is successful when all of the following are true:

- an agent can read `/obj/geo1` as one canonical JSON network document
- the agent can edit that document offline and send it back unchanged except for intended edits
- the backend can validate, diff, and apply the edited document without the agent issuing node-by-node commands
- subnetworks are represented as nested or linked network documents rather than flattened path-only entries
- VEX and other scripted surfaces are represented structurally in the document model and compiled by the backend
- direct user edits in Houdini are imported back into the graph store with revision tracking
- existing higher-level tools can be reimplemented on top of the document pipeline instead of bypassing it

## 14. Immediate Implication For This Repo

The current indexed scene graph and `graph.batch_edit` path are useful migration assets, but they are not the target architecture.

The next implementation work should treat the current graph cache as a temporary read-model and replace the current authoring path with:

- embedded graph store
- network document projections
- document validation and diff
- document apply compiler
- legacy-tool compatibility shims
