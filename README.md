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

Use the bearer token from:

```text
%USERPROFILE%\Documents\houdini21.0\hocuspocus\runtime\token.txt
```

If the app asks for headers instead of a token field:

```text
Authorization: Bearer <your-token>
```

The health route is:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

## Included

Current server surface includes:

- live scene, node, parm, selection, playbar, camera, and viewport tools
- dynamic node and task resources
- non-blocking cook, render, and export tasks with polling and cancellation
- material creation and assignment tools
- higher-level tools such as batch graph edits, turntable camera creation, managed snapshots, geometry summaries, and a house blockout macro

## Docs

For the fuller manual, see [HocusPocus Manual](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\user-manual.md).

For engineering state, see [Improvement Tracker](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\improvement-task-tracker.md).

## License

MIT. See [LICENSE](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\LICENSE).
