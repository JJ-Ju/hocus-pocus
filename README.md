# HocusPocus

HocusPocus is a durable Model Context Protocol (MCP) connection to a live
Houdini session. It gives Codex, Claude Code, and other MCP clients two useful
authoring surfaces:

- a document-centric API for inspecting and changing live Houdini networks;
- HocusScript (`.hocus`), a Git-visible text format for declarative procedural
  graphs and managed state.

The client talks over stdio to a stable local broker. Houdini hosts the
replaceable execution process behind that broker. Closing, restarting, or
upgrading the scene host therefore does not permanently break the MCP client
connection: while Houdini is offline, calls return typed `HOCUS999 host_offline`
status; after Houdini starts, the broker reconnects automatically.

Houdini **22.0.368** is the sole supported and release-qualified live runtime
for V1. Houdini 21 and other Houdini 22 builds are not supported by the V1
compatibility promise.

## Install

Prerequisites:

- Windows with Houdini 22.0.368 installed;
- PowerShell;
- a standalone Python 3.11 or newer runtime for the stdio broker. The launcher
  installer finds Houdini's compatible Python first and falls back to `python`.

From the repository root, build and install the Houdini package:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

The installer validates a versioned candidate before atomically switching
`%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus.json`. Reinstalling
preserves the active bearer credential. Use `-RotateToken` only when you
intentionally want to invalidate it.

Then install the stable client-facing broker and generate client configuration:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_hocuspocus_mcp_client.ps1
```

The command reports the launcher and these generated configuration files:

```text
%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus-codex.toml
%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus-claude.json
```

Merge the generated `[mcp_servers.hocuspocus]` block into Codex's
`%USERPROFILE%\.codex\config.toml`, or merge the generated `hocuspocus` entry
into Claude Code's MCP configuration. Keep the generated command, arguments,
and environment unchanged. The canonical MCP server name is `hocuspocus` and
the canonical client transport is **stdio**.

Finally:

1. Restart Houdini once so it loads the newly installed package.
2. Restart or reload the MCP client once so it starts the broker.

Subsequent Houdini restarts do not require reconnecting the MCP client. A
package reinstall requires a Houdini restart; also restart or reload the MCP
client when the installed broker or its configuration changed.

> The loopback HTTP URL is the private broker-to-Houdini transport and a
> diagnostic surface. Do not configure Codex or Claude to use it directly;
> direct HTTP clients are tied to one Houdini process and are not restart
> durable.

## Verify the connection

Launch Houdini and run this in its Python shell:

```python
import hocuspocus
print(hocuspocus.server_status())
```

The result should include `running: True`, `serverVersion: 0.9.0`, and:

```text
http://127.0.0.1:37219/hocuspocus/mcp
```

The health-only diagnostic route is:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

From the MCP client, call `session.info` first. It reports the live Houdini
version, coordinate conventions, policy profile, granted capabilities, and
host/session identity.

## Live document authoring

For multi-node work, use one network document instead of a long sequence of
fragile node edits:

1. Inspect `scene.get_summary` and the relevant
   `houdini://documents/network/{path}` resource.
2. If an empty scene has no SOP network, call `object.create_geometry`; `/obj`
   itself is not a writable SOP document.
3. Call `document.checkout`. The working document is returned inline when it
   fits the response limit; larger documents include a resource URI.
4. Edit the network-document JSON in the client.
5. Call `document.validate`, then `document.diff`.
6. Call `document.apply` with `mode = validate_only`, then apply the intended
   merge or reconcile operation.

The same JSON shape is used for reading, validation, diffing, and applying.
Apply preflights live Houdini parameter templates before mutation, groups a
logical change into one guarded undo step, and returns an operation ID. If a
call times out or delivery becomes ambiguous, query `session.get_operation`
with that ID before attempting another mutation.

Use low-level `node.*` and `parm.*` operations for focused edits. Use
`node_types.list_compatible` and `node_types.get_info` before inventing type or
parameter names. Artist-facing parameters on locked assets use
`hda.set_instance_parms`; HDA interface changes are separately authorized.

See [Agent Workflows](docs/agent-workflows.md) for practical tool-selection
patterns and [Network Document Contract](docs/document-contract-v1.md) for the
exact carrier.

## HocusScript source workspace

`.hocus` files are ordinary UTF-8 project files. They stay in the user's chosen
directory, are edited like code, and remain visible to Git and native editors.
HocusPocus does not expose a general filesystem tool or send physical project
roots to MCP clients.

To use a project through MCP:

1. Open Houdini's **HocusPocus Source Workspaces** Python Panel, also available
   in the server dialog.
2. Register the directory containing `hocus.project.toml`.
3. Select the active MCP client and grant only the required access.
4. In the client, call `source.project.describe` to receive the opaque
   `projectId`.
5. Use `source.file.search`, `source.file.read`, and
   `source.file.apply_patch` for bounded source editing.
6. Use `source.project.build` with `format`, `check`, or `compile`.
7. Send the compiled Bundle to `document.preview_bundle`, then
   `document.plan_bundle`, and finally `document.apply_plan`.

The full source surface is deliberately limited to seven operations:

- `source.project.describe`
- `source.file.search`
- `source.file.read`
- `source.file.apply_patch`
- `source.file.write_export`
- `source.project.build`
- `source.project.navigate`

The offline CLI uses the same native compiler without granting MCP access to a
project root:

```powershell
$env:PYTHONPATH = "python3.11libs"
python -m hocuspocus.hocusscript check hocus/asset.hocus --project D:/show/project
python -m hocuspocus.hocusscript format hocus/asset.hocus --project D:/show/project --write
python -m hocuspocus.hocusscript compile hocus/asset.hocus --project D:/show/project -o asset.bundle.json
```

See the [HocusScript Specification](docs/hocusscript-spec.md),
[HS7 Fidelity Matrix](docs/hocusscript-hs7-support-matrix.md), and
[HocusScript section of the manual](docs/user-manual.md#hocusscript-source-workflow)
for language versions, typed values, external modules, and export boundaries.

## Security and policy defaults

- The installed bearer credential stays in the active Houdini package. The
  governed broker launcher resolves it without copying it into Codex or Claude
  configuration and never prints it.
- The server binds to numeric loopback. Physical source roots and source
  contents are excluded from audit records and authorization responses.
- The default `local-dev` profile does not grant `run_code`. Select the
  explicit `procedural-authoring` profile only for trusted VEX or other authored
  code workflows, then confirm `grantedCapabilities` through `session.info`.
- Source-workspace grants default to read-only, current-session access with an
  eight-hour expiry. Source write, generated-lock update, persistence, and each
  external alias require distinct host approval.
- Source writes use exact content digests and descriptor-safe containment.
  Arbitrary files, external roots, generated bundles/catalogs, deletes, renames,
  and blind overwrites are not exposed.
- Scene and document mutations remain subject to policy, revision, ownership,
  capability, and live-drift checks. HocusScript never bypasses the guarded
  preview/plan/apply pipeline.

Read [Compatibility Policy](docs/compatibility-policy.md) and the
[Houdini MCP Specification](docs/houdini-mcp-spec.md) for the formal support
and trust boundaries.

## Troubleshooting

**`Unauthorized` during MCP startup**

Rerun `scripts\install_hocuspocus_mcp_client.ps1`, merge its newly generated
configuration, and restart the MCP client. Do not paste a token into the client
config or point the client directly at the HTTP endpoint. After an intentional
`-RotateToken`, restart Houdini; the durable broker refreshes its credential
from the active package.

**`HOCUS999 host_offline`**

The broker is healthy but no Houdini execution host is available. Start
Houdini and wait for package auto-start. The next request reconnects; do not
replace the stdio configuration with a direct HTTP connection.

**`import hocuspocus` fails or `running` is false**

Reinstall with `scripts\build.ps1 -Clean -Install`, restart Houdini, and inspect
`hocuspocus.server_status()`. Confirm the active package pointer exists at
`%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus.json`.

**A mutation timed out or the host restarted mid-call**

Use its operation ID with `session.get_operation`. A terminal result is
returned without re-execution. Treat `partial_or_unknown` as a reason to inspect
live state, not permission to retry blindly.

**A source project is missing or access is denied**

Open **Source Workspaces**, select the current MCP client, and inspect the
project grant, expiry, requested access, and external-alias approvals. Moving a
root or changing its authority-bearing manifest fields intentionally requires
reapproval.

The complete operational guide is in the
[HocusPocus Manual](docs/user-manual.md). Release and contributor checks are in
[Release Validation](docs/release-validation.md).

## Development

Use the fast gates while iterating:

```powershell
python -m pip install -r requirements-lint.txt
powershell -ExecutionPolicy Bypass -File .\scripts\lint.ps1
python .\tests\test_hocusscript_control_scenarios.py -q
```

The linter enforces a maximum of 50 public workflow tests, 1,200 physical lines
per governed file, cyclomatic complexity 12, and branch complexity 15. Run the
full release campaign only for a stabilized candidate; follow
[Release Validation](docs/release-validation.md).

## Documentation

- [User Manual](docs/user-manual.md)
- [Agent Workflows](docs/agent-workflows.md)
- [Durable MCP Transport](docs/durable-mcp-transport.md)
- [Network Document Contract](docs/document-contract-v1.md)
- [HocusScript Specification](docs/hocusscript-spec.md)
- [HS7 Fidelity Matrix](docs/hocusscript-hs7-support-matrix.md)
- [HS8 Production Qualification](docs/hocusscript-hs8-production.md)
- [Compatibility Policy](docs/compatibility-policy.md)
- [Release Validation](docs/release-validation.md)

## License

MIT. See [LICENSE](LICENSE).
