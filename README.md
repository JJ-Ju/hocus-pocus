# HocusPocus for Houdini 21.x

HocusPocus is a Houdini-hosted MCP server plugin. The current build is Python-only: it runs inside Houdini, serves a localhost MCP endpoint, and exposes live-scene automation through HOM (`hou`).

Status:

- live Houdini-hosted MCP server works
- Codex can connect to it over Streamable HTTP
- core scene/node/parm/viewport automation is implemented
- worker-plane, panel UI, and native bridge are still pending

This repository does not yet contain an HDK/C++ module, so "build" currently means:

- stage an installable Houdini package layout
- byte-compile the Python modules
- optionally install the package into your Houdini user packages directory

## Requirements

- Houdini 21.x
- Windows with PowerShell
- Python available on `PATH`
  - Houdini 21 uses Python 3.11, but the build script only needs a Python that can run `compileall`

## Repo Layout

- [python3.11libs/hocuspocus](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\python3.11libs\hocuspocus): main plugin code
- [config/default.toml](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\config\default.toml): default server settings
- [toolbar/hocuspocus.shelf](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\toolbar\hocuspocus.shelf): shelf buttons for start/stop
- [scripts/build.ps1](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\scripts\build.ps1): stage/install script

## Quick Start

Build and install into the default Houdini 21.0 package directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Then launch Houdini and verify:

```python
import hocuspocus
print(hocuspocus.server_status())
```

## Build the Houdini Package

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean
```

That produces:

- `dist\houdini-package\HocusPocus\`
- `dist\houdini-package\hocuspocus.json`

The script copies the runtime files into a Houdini-friendly layout and runs `compileall` over `python3.11libs`.

## Install Into Houdini Automatically

To stage and install directly into the default Houdini 21.0 user package location:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Default install target:

```text
%USERPROFILE%\Documents\houdini21.0\packages\
```

This creates:

- `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus\`
- `%USERPROFILE%\Documents\houdini21.0\packages\hocuspocus.json`

If your Houdini user prefs live somewhere else:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install -HoudiniUserPrefDir "D:\houdini21.0"
```

## Install Manually

If you do not want the script to copy files into your Houdini prefs:

1. Run the build script without `-Install`.
2. Copy `dist\houdini-package\HocusPocus\` into your Houdini `packages` directory.
3. Copy `dist\houdini-package\hocuspocus.json` into the same `packages` directory.

Final layout should look like:

```text
%USERPROFILE%\Documents\houdini21.0\packages\
  hocuspocus.json
  HocusPocus\
    config\
    python3.11libs\
    scripts\
    toolbar\
    package\
```

## Start the Server in Houdini

After installation:

1. Launch Houdini 21.x.
2. Confirm the `HocusPocus` shelf appears.
3. Click `Start HocusPocus`.

You can also start it from the Python shell:

```python
import hocuspocus
hocuspocus.start_server()
```

To inspect status:

```python
import hocuspocus
hocuspocus.server_status()
```

To stop it:

```python
import hocuspocus
hocuspocus.stop_server()
```

## Enable Auto-Start

Auto-start is supported through Houdini's startup `pythonrc.py`.

Edit [config/default.toml](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\config\default.toml) and set:

```toml
auto_start = true
```

Then rebuild/install and restart Houdini:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

On the next Houdini launch, HocusPocus will start automatically.

## Runtime Defaults

Defaults come from [config/default.toml](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\config\default.toml):

- host: `127.0.0.1`
- port: `37219`
- MCP route: `/hocuspocus/mcp`
- health route: `/hocuspocus/healthz`
- auth token: generated at first start

At runtime, the generated token and logs are written under Houdini's user pref area when available. Outside Houdini they fall back to a local `.hocuspocus` directory in the repo.

## Connect an MCP Client

HTTP endpoint:

```text
http://127.0.0.1:37219/hocuspocus/mcp
```

Health endpoint:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

## Orientation and Snapshot Notes

The server now exposes Houdini coordinate-system conventions in `session.info`, `scene.get_summary`, and the `houdini://session/conventions` resource.

The conventions used by this server are:

- `Y` is up
- `XZ` is the ground plane
- `X` is left-right
- `Z` is depth / front-back

For geometry placement through MCP:

- raise objects on `Y` by half their height to sit them on the ground
- use `Z` for front-facing placement in the example house and other generated geometry

Snapshot-related tools:

- `viewport.capture`
- `snapshot.capture_viewport`
- `camera.get_active`

The default auth mode is bearer token. Read the token from:

```text
<HOUDINI_USER_PREF_DIR>\hocuspocus\runtime\token.txt
```

Or query it inside Houdini:

```python
import hocuspocus
print(hocuspocus.server_status())
```

## Current Scope

Implemented now:

- localhost MCP-compatible HTTP runtime
- stdio bridge
- serialized live execution dispatcher
- scene, node, parm, selection, playbar, and basic viewport tools

Not implemented yet:

- HDK/native bridge
- Python Panel chat UI
- embedded terminal
- HAPI/HARS worker plane

## Troubleshooting

If the shelf does not appear:

- make sure both `hocuspocus.json` and the `HocusPocus` folder are in your Houdini `packages` directory
- restart Houdini after installation

If `import hocuspocus` fails inside Houdini:

- confirm `python3.11libs\hocuspocus` exists under the installed `HocusPocus` folder
- confirm `hocuspocus.json` is in the scanned `packages` directory, not nested below it

If the server starts but a client cannot connect:

- verify Houdini shows the server as running with `hocuspocus.server_status()`
- check whether port `37219` is already in use
- verify the client is sending the bearer token

If you want a clean reinstall:

1. Close Houdini.
2. Delete `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus`
3. Delete `%USERPROFILE%\Documents\houdini21.0\packages\hocuspocus.json`
4. Run the build script again with `-Clean -Install`

## License

This repository is licensed under MIT. See [LICENSE](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\LICENSE).
