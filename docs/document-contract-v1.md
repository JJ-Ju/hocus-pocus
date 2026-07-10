# HocusPocus Document Contract v1

Status: locked contract

Scope:

- first-wave MCP contract for document-centric graph authoring
- Workstream 1 deliverable
- authoritative until replaced by a versioned successor

Related artifacts:

- `docs/document-graph-overhaul-spec.md`
- `docs/schemas/network-document-v1.schema.json`

## 1. Purpose

This document locks the first implementation slice for the document-oriented MCP surface so downstream work does not drift.

It defines:

- the canonical schema id for network documents
- the first-wave resource URIs
- the first-wave tool names
- apply-mode semantics
- the legacy compatibility policy

## 2. Canonical Schema

Network document schema id:

- `hocuspocus://schemas/network-document/v1`

Schema file:

- `docs/schemas/network-document-v1.schema.json`

Schema resource URI:

- `houdini://documents/schema/network-document/v1`

Rules:

- every network document returned by MCP must set `$schema` to `hocuspocus://schemas/network-document/v1`
- the same JSON shape returned by `houdini://documents/network/{path}` is the accepted shape for `document.validate`, `document.diff`, and `document.apply`
- unknown top-level fields are not part of the locked contract unless the schema explicitly permits them

## 3. First-Wave Resources

These URIs are locked for the first document-centric slice:

| Resource URI | Purpose |
| --- | --- |
| `houdini://documents/scene` | Read the scene manifest over root networks. |
| `houdini://documents/network/{path}` | Read a canonical network document for a network or subnetwork. |
| `houdini://documents/schema/network-document/v1` | Read the locked machine-readable schema for network documents. |
| `houdini://documents/checkouts/{checkout_id}` | Read a working copy created by `document.checkout`. |
| `houdini://documents/diagnostics/{checkout_id}` | Read the latest validation or apply diagnostics for a checkout. |

Path rules for `{path}`:

- slash-separated absolute Houdini paths are preferred, for example `obj/geo1`
- percent-encoded absolute paths are also valid
- the resolved path always maps to a network scope, not an arbitrary non-network node

## 4. First-Wave Tools

These tool names are locked:

| Tool | Purpose |
| --- | --- |
| `document.checkout` | Create a working copy from a scene or network document. |
| `document.validate` | Validate a supplied document or an existing checkout. |
| `document.diff` | Diff baseline vs target document or checkout. |
| `document.apply` | Apply a document or checkout to Houdini and commit the resulting revision. |
| `document.discard_checkout` | Delete a working copy. |
| `document.query` | Query the embedded graph store without materializing a full document. |
| `document.sync_from_houdini` | Force a reimport of a scene or network scope after direct live edits. |

Optional later additions may exist, but they do not change this locked first-wave surface.

## 5. Apply Modes

`document.apply` mode semantics are locked as follows:

### `reconcile`

- the target document is the desired truth for the scoped network
- entities missing from the target may be removed from the live network
- this is the default for checkout-based apply flows unless overridden

### `merge`

- create or update only the entities represented in the target payload
- preserve unspecified live entities where possible
- use this when the client is intentionally editing only a subset of a larger network

### `validate_only`

- compile and validate the requested document change without mutating live Houdini
- return diagnostics and the planned diff or apply plan
- this is the required dry-run mode

## 6. Concurrency Contract

The first implementation slice must support optimistic concurrency.

Required fields and behavior:

- network documents include `documentRevision`
- `document.apply` accepts `expected_document_revision`
- apply fails fast when the supplied expected revision does not match the current stored revision for that scope
- direct live Houdini edits that reimport into the store advance the document revision

## 7. Compatibility Policy

The following policy is locked:

- `node.*` and `parm.*` remain temporarily available as compatibility tools
- `graph.query` may remain as a compatibility read facade
- `graph.apply_patch` and `graph.batch_edit` are compatibility shims, not the long-term authoring model
- new authoring features must land on the `document.*` surface first
- once document parity exists for a workflow, legacy graph mutation tools should be removed from default discovery before they are removed entirely

## 8. First-Wave Document Scope

The first implementation target is:

- SOP network documents

That includes:

- object-contained SOP networks such as `/obj/geo1`
- subnetworks inside SOP networks where the live node is a network container
- parameters, flags, layout, structural connections, and supported code blobs inside those scopes

This contract does not require immediate parity for:

- all MAT networks
- all LOP networks
- all TOP networks
- HDA definition editing

Those come later under the same versioned document model.
