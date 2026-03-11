# HocusPocus

HocusPocus is a Houdini 21.x MCP server that runs inside Houdini and auto-starts with the application. It is designed to be a one-install, connect-your-agent workflow.

## Install

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

That installs the package into:

```text
%USERPROFILE%\Documents\houdini21.0\packages\
```

During install, the script also:

- provisions a stable HocusPocus bearer token into the installed config
- sets the user environment variable `HOCUSPOCUS_TOKEN`

So the normal local setup does not require copying tokens by hand after install.

## Verify

Launch Houdini. In Houdini's Python shell:

```python
import hocuspocus
print(hocuspocus.server_status())
```

Expected:

- `running: True`
- `serverVersion: 0.9.0`
- `mcpUrl: http://127.0.0.1:37219/hocuspocus/mcp`

## Connect Codex on Windows

Add a custom MCP server in the Codex app with:

- Transport: `Streamable HTTP`
- Name: `houdini`
- URL: `http://127.0.0.1:37219/hocuspocus/mcp`

If the app asks for an environment variable name, use:

```text
HOCUSPOCUS_TOKEN
```

If the app asks for headers instead of a token field, use:

```text
Authorization: Bearer <value of HOCUSPOCUS_TOKEN>
```

The health route is:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

This repo documents the Codex app connection settings, but the repository validation performed so far has only proven the Houdini-hosted MCP endpoint over its Streamable HTTP transport. It has not proven native Codex runtime tool exposure from inside this agent runtime.

## Included

Current server surface includes:

- live scene, node, parm, selection, playbar, camera, and viewport tools
- dynamic node and task resources
- non-blocking cook, render, and export tasks with polling and cancellation
- material creation and assignment tools
- higher-level tools such as batch graph edits, turntable camera creation, managed snapshots, geometry summaries, and a house blockout macro
- named policy profiles with effective-policy reporting in status and resources

## Docs

For the fuller manual, see [HocusPocus Manual](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\user-manual.md).

For compatibility and release rules, see [Compatibility Policy](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\compatibility-policy.md) and [Release Validation](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\release-validation.md).

For agent usage patterns, see [Agent Workflows](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\agent-workflows.md).

For engineering state, see [Improvement Tracker](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\improvement-task-tracker.md).

## License

MIT. See [LICENSE](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\LICENSE).
