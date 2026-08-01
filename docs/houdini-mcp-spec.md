# HocusPocus Houdini MCP Specification

Status: implemented V1 runtime contract

Supported host: Houdini `22.0.368`

Negotiated MCP revisions: `2025-06-18` and `2025-11-25`

This document describes the deployed architecture and the rules that public
operations must obey. The server's MCP discovery response and canonical schema
resources are the machine-readable authority for exact tool arguments and
response shapes. The [user manual](user-manual.md) explains installation and
the [agent workflows](agent-workflows.md) explain how to use the surface.

## 1. Product boundary

HocusPocus gives an authenticated agent structured control over the current
interactive Houdini scene. It is designed around four principles:

- Houdini Object Model (`hou`) is the authority for live scene state.
- A client-owned stdio broker survives Houdini process replacement.
- Documents and compiled HocusScript Bundles are the preferred multi-step
  authoring surfaces.
- Every mutation is capability-gated, serialized, auditable, and recoverable or
  explicitly quarantined.

Houdini `22.0.368` is the sole V1 release-qualifying runtime. H21 receipts are
historical migration evidence. HAPI/HARS workers, an HDK bridge, and a general
chat/terminal panel are not part of the V1 public runtime contract.

## 2. Deployed architecture

```text
Codex / Claude Code / MCP client
              |
              | long-lived stdio JSON-RPC
              v
      hocuspocus-mcp-stdio
              |
              | authenticated loopback Streamable HTTP
              v
  embedded Houdini 22 execution host
              |
              | serialized main-thread HOM dispatch
              v
 live scene + graph/source/plan/history stores
```

### 2.1 Client-facing broker

The governed `hocuspocus-mcp-stdio` launcher is started and supervised by the
MCP client. It owns the stable client connection, client identity, discovery
snapshot, host-generation mapping, credential resolution, and delivery
classification.

The broker:

- resolves the bearer credential from the verified active package;
- keeps running while Houdini is absent;
- returns typed `host_offline` state instead of raw connection failures;
- initializes a new upstream session when a new Houdini host appears;
- preserves eligible unexpired source-workspace grants across that replacement;
- never automatically replays an ambiguously delivered tool call; and
- bounds messages, cached discovery, timeouts, stdout, and stderr.

Canonical framing is one UTF-8 JSON-RPC message per line. `Content-Length`
input framing is accepted for compatibility. Standard output contains protocol
messages only.

### 2.2 Embedded host transport

The embedded server binds to numeric loopback and exposes:

- `POST /hocuspocus/mcp`
- `GET /hocuspocus/healthz`

This HTTP surface is the private broker-to-host hop and a diagnostic lane. A
client connected directly to it has the Houdini process lifetime and therefore
does not receive restart durability.

Each host process publishes a random `hostInstanceId` and opaque
`hostGeneration`. Expected-identity headers allow the broker to reject a stale
host before admission or dispatch. Bearer authentication is required by
default; the bearer secret does not belong in Codex or Claude configuration.

The complete lifecycle and no-replay rules are in the
[durable transport contract](durable-mcp-transport.md).

### 2.3 Live execution

Network threads never mutate Houdini directly. The dispatcher validates the
request, authenticates its session and principal, checks capabilities, then
marshals live work onto Houdini's main thread. Live mutation is a single-writer
domain.

Long cooks, renders, exports, and PDG work return task handles. Their resources
carry progress, bounded logs, result/error state, outcome details, and recovery
notes. Cancellation is cooperative and does not imply that partial output is
absent.

## 3. Authority model

### 3.1 Live capabilities

Tools declare required capabilities from this set:

- `observe`
- `edit_scene`
- `write_files`
- `run_code`
- `launch_processes`
- `use_network`
- `submit_farm_jobs`
- `review_production`

Shipped profiles are:

| Profile | Intent |
| --- | --- |
| `safe` | Read-only inspection. |
| `local-dev` | Local scene and file editing without arbitrary code execution. |
| `procedural-authoring` | Trusted local authoring with explicit `run_code`. |
| `pipeline` | Scene editing with writes restricted to managed output roots by default. |

`session.info` reports granted capabilities. Document validation and Bundle
preview report required, missing, and ready capability projections before
mutation. Authored code never acquires `run_code` merely by appearing in a
valid document.

File-producing operations are also constrained by `approved_roots`. HDA
definition-editing operations require both `edit_scene` and `write_files`;
external libraries must additionally be inside an approved write root. Editing
a public parameter on a locked HDA instance does not edit the definition file.

### 3.2 Source-workspace grants

Source authority is separate from live-scene capability. The host user approves
a project through the Source Workspaces panel or startup configuration. The
registry stores a random project ID, root/manifest identity, projection digest,
grant generation, expiry, persistence, and separately approved external aliases.

MCP sees only:

- opaque `projectId` values;
- portable relative paths and `hocus-source://` URIs;
- content and projection digests; and
- effective grant/expiry information.

It never receives a physical project root. Source-read, source-write,
generated-lock publication, and each external alias are independent grants.
Revocation, expiry, root replacement, manifest-authority changes, or registry
removal invalidate access.

The seven source operations are exactly:

- `source.project.describe`
- `source.file.search`
- `source.file.read`
- `source.file.apply_patch`
- `source.file.write_export`
- `source.project.build`
- `source.project.navigate`

These operations use descriptor-safe, identity-checked file providers and
exact-digest publication. They are not a general filesystem API. Source writes
are limited to authored `.hocus` files and projection-preserving manifest edits;
external roots and generated artifacts are not generic write targets.

### 3.3 Audit

Tool, task, source, and file activity is recorded in bounded host-state logs.
Audit records use operation/principal/session identities, portable target
identity, argument digest, outcome, and resulting digest. Source content,
search text, dirty buffers, bearer secrets, physical source roots, and
unsanitized exceptions must not enter the source audit trail.

## 4. Public authoring surfaces

Exact tool schemas are returned by MCP discovery. This section defines how the
surfaces compose; it is not a substitute for discovery.

### 4.1 Inspect and discover

Start with `session.info`, `scene.get_summary`, and the scene or network
document resources. Use `document.query`, `node.get`, `parm.list`, or
`geometry.get_summary` only for targeted detail.

Node types have stable category-qualified IDs such as `Sop/copytopoints`.
`node_types.get_info` accepts that `typeId` without forcing an ambiguous bare
name. `node_types.list_compatible` accepts exactly one canonical enum task or a
bounded natural-language intent and returns deterministic candidates when the
intent is ambiguous.

### 4.2 Bootstrap an empty OBJ scene

The document workflow intentionally does not make `/obj` a writable SOP
document. `object.create_geometry` is the narrow bootstrap operation: it creates
one Geometry object under `/obj` and returns the resolved SOP root plus checkout
delivery metadata. The working document is inline when it fits; otherwise its
durable checkout resource URI remains available.

Bootstrap admission, checkout, graph-store state, and live-node creation are
one recoverable operation. A cleanup failure returns typed retained-state
information instead of pretending the bootstrap never happened.

### 4.3 Network documents

The locked first-wave contract is
[network document v1](document-contract-v1.md). Current discovery also exposes
the strict typed-value v2 schema. Canonical resources are:

- `hocuspocus://schemas/network-document/v1`
- `hocuspocus://schemas/network-document/v2`

The `houdini://documents/schema/network-document/...` resources are
compatibility aliases. The ordinary workflow is:

1. `document.checkout`
2. edit the returned JSON document or read its checkout resource
3. `document.validate`
4. `document.diff`
5. `document.apply` with `validate_only`, `merge`, or `reconcile`
6. `document.discard_checkout` when finished

Checkout responses always include `documentDelivery` with content digest, UTF-8
byte length, inline limit, mode, and resource URI. Small working documents are
returned inline; large ones require the resource read.

`document.apply` is optimistic-concurrency guarded by the expected document
revision. `merge` changes represented entities while preserving unspecified
state where possible. `reconcile` treats compiler-managed state in the target
as desired truth without claiming artist-owned fields merely through omission.

### 4.4 HocusScript projects and Bundles

`.hocus` files are ordinary text files. An approved agent edits them through the
source workspace surface; a user or IDE may edit the same files directly. For
saved projects, use `source.project.build` for format, check, compile, and
authorized lock update. `document.compile_source`, `document.format_source`,
and `document.complete_source` are content-only unsaved-buffer conveniences and
never read project roots.

The live mutation path is:

1. compile an approved entry with `source.project.build`;
2. pass the exact versioned Bundle to `document.preview_bundle`;
3. persist an immutable plan with `document.plan_bundle`; and
4. apply that exact plan with `document.apply_plan`.

Preview is non-mutating. Planning revalidates carrier semantics, provenance,
catalog/HDA selections, capabilities, ownership, target, and revisions. Apply
checks the immutable plan and live drift guards; it does not reread or recompile
the source file.

`document.compile_source` is a structural compatibility lane, not a shortcut
to live apply. Bundle and schema versions remain explicit compatibility units.

### 4.5 HDA operations

Use `hda.set_instance_parms` for artist-facing controls on a locked asset. It
resolves only definition-interface parameters, preflights the complete batch,
and never unlocks or structurally edits the asset.

Use `hda.promote_parm` only on a locked instance that matches its current
definition. Static source values are preserved by default; explicit
`default_value` and `initial_value` can override that policy. Expressions and
keyframes are rejected rather than sampled destructively. Menu defaults use
canonical menu tokens. External-library mutation is file-authority gated.

### 4.6 Production qualification

`production.asset.qualify` is the only public production operation. It is
read-only and returns content-derived technical gates. Public MCP results are
`content_only`, so actionable packaging/publish readiness remains false.
Packaging and release authority belong to the installed private runner and
detached verifier, which decode the same strict schemas and bind evidence to
the exact installed payload and output digests.

See the [HS8 production workflow](hocusscript-hs8-production.md).

## 5. Mutation integrity

Document and HocusScript scene changes are preflighted before their undo group.
Document parameters are coerced and validated against live Houdini parameter
templates, including tuple size, numeric bounds, toggle/menu semantics, and
binding target. A stored immutable plan is never modified to make execution
convenient.

One logical MCP mutation produces one structural revision. Appearance,
position, selection, and playbar activity advances cosmetic state separately
and does not invalidate structural plans.

Node display/render/output flags are authored node state. Checkout
`output_flag` edges are regenerated observations, not a second competing
mutation instruction.

Failure behavior is typed:

- `HOCUS755` means the exact baseline was restored and verified.
- `HOCUS756` means restoration was not proven; the scope is quarantined until
  explicit recovery.

Houdini 22 undo and redo use `performUndo` and `performRedo`, guarded by the
expected stack label. A direct mutation keeps an inverse fallback so a failed
undo attempt does not immediately turn an otherwise recoverable operation into
unknown state.

## 6. Durable operation reconciliation

Each broker tool call receives a stable operation ID before host transport. Its
identity is bound to the authenticated principal, tool, and canonical argument
digest. Bounded terminal results/errors record host generation, delivery stage,
commit state, and reconciliation metadata.

After a timeout, disconnect, or ambiguous delivery, call
`session.get_operation` with the operation ID before issuing another mutation:

- a terminal result is returned without re-execution;
- an operation still owned by a live host lease remains pending;
- an orphaned old-host operation becomes `partial_or_unknown`; and
- incompatible tool/argument reuse is rejected.

Post-commit journal or housekeeping failure must not mask a confirmed scene
commit. The returned result identifies any loss of durable reconciliation
availability. The broker itself never guesses that a `tools/call` is safe to
replay from annotations.

## 7. Resources, tasks, and payloads

Prefer resources for reusable bounded snapshots:

- `houdini://documents/scene`
- `houdini://documents/network/{path}`
- `houdini://documents/checkouts/{checkout_id}`
- `houdini://documents/diagnostics/{checkout_id}`
- `houdini://nodes/{path}` and focused node subresources
- `houdini://tasks/{task_id}` and bounded task logs
- `hocus-source://{projectId}` and authorized project-relative files
- canonical `hocuspocus://schemas/...` resources

Large geometry, source trees, logs, images, and compiled carriers must not be
silently embedded into unbounded tool text. Operations either return bounded
summaries/resource links or fail with a typed payload-size error before a write
commit. Resource reads recheck applicable session, grant, projection, root, and
content identity.

## 8. Installation and update contract

Build/install creates a validated sibling candidate, installs it to a versioned
directory, and atomically replaces `packages/hocuspocus.json` last. The prior
complete installation remains available until activation succeeds. An
identical install is a verified no-op.

The install manifest governs every shipped file by portable path, role, byte
length, and SHA-256 digest. The generated token configuration is represented by
a normalized redacted row. Missing, changed, undeclared, reparse-aliased, or
bytecode-cache files fail verification.

Normal reinstall preserves the active token. `-RotateToken` is explicit, never
prints the secret, and rolls back environment/activation changes on failure.
After installation, the client launcher installer publishes a stable broker and
generated Codex/Claude snippets beside the active package pointer.

See the [release validation checklist](release-validation.md),
[compatibility policy](compatibility-policy.md), and
[durable transport contract](durable-mcp-transport.md).

## 9. Non-contractual extension points

HAPI/HARS worker routing, an optional HDK performance bridge, richer event
streaming, and a general in-Houdini chat/terminal shell remain possible future
extensions. They must not be inferred from this specification as shipped tools,
permissions, transports, or release claims. Any such surface requires explicit
implementation, discovery metadata, safety review, and versioned documentation.

The current product center is intentionally simpler: a durable client broker,
an authenticated in-process HOM host, document/HocusScript authoring, narrow
specialized operations, and fail-closed mutation/recovery semantics.

## 10. SideFX references

- [API overview](https://www.sidefx.com/docs/houdini/ref/api.html)
- [Houdini Object Model](https://www.sidefx.com/docs/houdini/hom/)
- [HOM command-line behavior](https://www.sidefx.com/docs/houdini/hom/commandline)
- [Houdini packages](https://www.sidefx.com/docs/houdini/ref/plugins.html)
- [`hwebserver`](https://www.sidefx.com/docs/houdini/hwebserver/index.html)
- [`hou.ui` event callbacks](https://www.sidefx.com/docs/houdini/hom/hou/ui.html)
- [HAPI](https://www.sidefx.com/docs/houdini/hapi/)
- [SessionSync](https://www.sidefx.com/docs/houdini/ref/henginesessionsync.html)
