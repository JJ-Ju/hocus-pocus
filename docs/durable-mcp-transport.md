# Durable MCP transport

Status: implemented and validated against Houdini 22.0.368

## Product requirement

The MCP connection owned by Codex, Claude Code, or another agent client must
remain usable when Houdini exits, crashes, upgrades, or restarts. Houdini is a
replaceable execution host, not the owner of the client connection.

The canonical client transport is `hocuspocus-mcp-stdio`. The embedded
localhost HTTP endpoint remains a private host transport and a supported
diagnostic surface; clients should not bind their lifetime directly to it.

## Process model

```text
Codex / Claude Code
        |
        | one long-lived stdio MCP connection
        v
hocuspocus-mcp-stdio broker
        |
        | authenticated localhost HTTP, reconnectable
        v
current Houdini host generation
```

The broker is launched and supervised by the MCP client. It owns:

- the client-facing MCP initialization and lifetime;
- the stable client session identity;
- the last authenticated discovery snapshot;
- the mapping from the client session to the current host session; and
- host-offline and ambiguous-delivery classification.

The verified stable launcher resolves bearer authority from the active
installed package. Client configuration never contains the secret and does not
depend on a long-lived desktop process inheriting `HOCUSPOCUS_TOKEN`. A
nonempty installed credential also overrides a missing or stale host
environment value. Source-tree development launchers retain an explicit
environment-token lane.

Install or refresh the launcher and generated client snippets with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_hocuspocus_mcp_client.ps1
```

The generated Codex and Claude snippets use the MCP name `hocuspocus`, a
standalone Python runtime, and the stable launcher under the Houdini 22 package
directory. Copy the generated command, arguments, and environment exactly. Do
not replace this with a direct HTTP client and do not add the bearer token.

Each Houdini process publishes a random `hostInstanceId` and an opaque
`hostGeneration`. A new process is always a new generation. The broker
initializes a new host session when the identity changes and never presents the
host's ephemeral session identifier to the client.

## Restart behavior

When the host disappears, the broker stays alive. Discovery may use only the
last authenticated snapshot from that broker process. An operation requiring
the host returns a structured, retryable `host_offline` error without exposing
transport exceptions or local paths.

After Houdini returns, the next safe request:

1. reads and authenticates host health;
2. detects the new host generation;
3. initializes a fresh upstream MCP session with the original client identity;
4. refreshes discovery state; and
5. forwards the request under the new upstream session.

No client reconnect is required.

Restart behavior by component:

| Event | Required action |
| --- | --- |
| Houdini exits, crashes, or restarts | Keep the MCP client connected; retry after the broker reports the new host online. |
| The bearer credential is intentionally rotated | Restart Houdini; the broker re-resolves the active package after the host rejects the old credential. |
| The installed broker program itself changes | Restart or reload the MCP client once so it launches the new broker bytes. |
| A generation-scoped checkout was open | Create a new checkout; it is not portable across host generations. |

If an intentional credential rotation is observed as an authenticated-host
`401`, the broker re-resolves the verified active package. Initialization and
discovery may be retried once. A rejected `tools/call` is not replayed; the
broker first restores its upstream session so a subsequent operation can
proceed safely.

## Delivery safety

The broker may retry connection establishment, health, initialization,
discovery, and read-only resource operations.

It must never automatically replay `tools/call` after an ambiguous disconnect.
The client receives an `ambiguous_delivery` error and decides whether to
inspect, reconcile, or submit a new operation. This rule applies even when a
tool is described as read-only because the broker must not infer safety from
untrusted or stale metadata.

Requests rejected before a host accepted any bytes may return `host_offline`.
Requests whose delivery cannot be proven absent return
`ambiguous_delivery`. Both errors are typed and retry guidance is explicit.

Generation-scoped checkouts and transient resources remain invalid after a
restart. Durable plans, idempotency history, and recovery evidence retain their
existing store-defined lifetime and are not silently discarded merely because
the host generation changed.

## Protocol and compatibility

- Canonical stdio framing is one UTF-8 JSON-RPC message per line.
- The previous `Content-Length` framing is accepted as a compatibility input.
- Standard output contains protocol messages only; diagnostics use bounded,
  sanitized standard error.
- The seven `source.*` operations and all existing tool/resource schemas remain
  unchanged.
- Authentication to the embedded host remains bearer-based and loopback-only.
- The broker must bound message size, cached discovery size, timeouts, and
  diagnostic output.

## Acceptance

The durability gate keeps one broker process and one client-side stdio stream
open while a disposable Houdini 22 host is stopped and replaced. The same
client connection must observe:

1. a successful initialized call;
2. a typed offline result while no host exists; and
3. a successful call against a different `hostInstanceId` after restart.

The proof must not use or mutate the user's visible Houdini scene.

## Troubleshooting boundary

- `Unauthorized` during MCP startup usually means a stale direct-HTTP or
  environment-token configuration. Regenerate the stdio configuration and
  remove any client-side bearer token.
- `host_offline` means the broker is healthy but no authenticated Houdini host
  is currently available. It is retryable and does not require reconnecting the
  MCP client.
- `ambiguous_delivery` means the broker cannot prove whether a tool call reached
  the host. Reconcile its operation ID with `session.get_operation`; never
  blindly replay the mutation.
- The localhost health and MCP URLs diagnose the embedded host only. A healthy
  HTTP endpoint does not prove that a desktop client loaded its stdio config.

See the [user manual](user-manual.md#3-connecting-an-agent) for installation
and the [compatibility policy](compatibility-policy.md) for supported versions.
