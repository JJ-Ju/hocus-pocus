# HocusPocus

HocusPocus is a Houdini 21.x MCP server that runs inside Houdini and exposes live scene automation to agent clients like Codex.

The intended experience is:

1. install it once
2. launch Houdini
3. the server auto-starts
4. connect your agent

## Install

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

That installs HocusPocus into the default Houdini 21.0 package directory:

```text
%USERPROFILE%\Documents\houdini21.0\packages\
```

Auto-start is enabled by default. After install, launching Houdini should also start the MCP server automatically.

## Verify in Houdini

In Houdini's Python shell:

```python
import hocuspocus
print(hocuspocus.server_status())
```

Expected:

- `running: True`
- `mcpUrl: http://127.0.0.1:37219/hocuspocus/mcp`

## Connect Codex on Windows

In the Codex app, add a custom MCP server with:

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

It is intentionally unauthenticated but only returns non-sensitive status. MCP method calls still require the bearer token unless auth is explicitly disabled in config.

## Houdini Conventions

HocusPocus exposes Houdini orientation notes so agents do not have to guess:

- `Y` is up
- `XZ` is the ground plane
- `X` is left-right
- `Z` is front-back / depth

These conventions are exposed in:

- `session.info`
- `scene.get_summary`
- `houdini://session/conventions`

## Agent Notes

Dynamic resources are available for stable scene inspection:

- `houdini://nodes/{path}`
- `houdini://nodes/{path}/parms`
- `houdini://nodes/{path}/geometry-summary`

Path forms:

- slash-separated: `houdini://nodes/obj/geo1`
- percent-encoded absolute path: `houdini://nodes/%2Fobj%2Fgeo1`

Safety controls in `config/default.toml`:

- `read_only = true` blocks scene edits and file writes
- `allow_scene_edit = false` blocks mutation tools
- `allow_file_write = false` blocks hip saves and viewport captures
- `approved_roots = [...]` restricts write paths to approved directories

## Snapshot Tools

Useful visual tools:

- `camera.get_active`
- `viewport.capture`
- `snapshot.capture_viewport`

Example snapshot path:

```text
C:/Users/<you>/Documents/houdini21.0/viewport_snapshot.png
```

## Current Scope

Implemented:

- live Houdini-hosted MCP server
- auto-start on Houdini launch
- scene, node, parm, selection, playbar, camera, and viewport tools
- viewport snapshot capture

Not implemented yet:

- HDK/native bridge
- Python Panel chat UI
- embedded terminal
- HAPI/HARS worker plane

## Troubleshooting

If `import hocuspocus` fails in Houdini:

- reinstall with the build script
- restart Houdini

If the server is not running on launch:

- run `import hocuspocus; print(hocuspocus.server_status())`
- confirm the installed config exists at:
  `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus\config\default.toml`

If Codex cannot connect:

- confirm Houdini reports `running: True`
- confirm the URL is `http://127.0.0.1:37219/hocuspocus/mcp`
- confirm the bearer token matches the token file

## License

MIT. See [LICENSE](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\LICENSE).
