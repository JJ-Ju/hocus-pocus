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

## Develop

Use the fast correctness gate and the narrowest relevant behavior smoke while iterating:

```powershell
python -m pip install -r requirements-lint.txt
powershell -ExecutionPolicy Bypass -File .\scripts\lint.ps1
python .\tests\test_hocusscript_v03_expander.py -q
```

The full release suite is intentionally not the default inner loop. See `docs/release-validation.md` for qualification gates.

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
- graph, validation, dependency, PDG, Solaris, packaging, and HDA tools for building procedural Houdini systems directly
- higher-level utilities such as batch graph edits, turntable camera creation, managed snapshots, and geometry summaries
- named policy profiles with effective-policy reporting in status and resources

## HocusScript Native Workflow

Treat `.hocus` as ordinary source code: edit it with normal workspace tools, keep it in Git, and run the offline compiler outside Houdini.

```powershell
$env:PYTHONPATH = "python3.11libs"
python -m hocuspocus.hocusscript check assets/rocks.hocus --project D:/houdini-projects/city
python -m hocuspocus.hocusscript format assets/rocks.hocus --project D:/houdini-projects/city --write
python -m hocuspocus.hocusscript compile assets/rocks.hocus --project D:/houdini-projects/city -o rocks.bundle.json
python -m hocuspocus.hocusscript write-export export-response.json assets/exported.hocus --project D:/houdini-projects/city
```

Language-`0.2` external libraries use explicit per-call roots on `lock --update`, `check`, and `compile` only. Repeat the option for the complete manifest-declared mapping and quote values whose absolute paths contain spaces:

```powershell
$studio = "studio=D:/Studio Libraries/Hocus"
python -m hocuspocus.hocusscript lock assets/rocks.hocus --update --project D:/houdini-projects/city --expected-lock-digest "sha256:<exact-current-lock-digest>" --module-root $studio
python -m hocuspocus.hocusscript check assets/rocks.hocus --project D:/houdini-projects/city --module-root $studio
python -m hocuspocus.hocusscript compile assets/rocks.hocus --project D:/houdini-projects/city --module-root $studio -o rocks.bundle.json
```

Module roots are not inferred, persisted, environment-backed, or accepted by `format`/`write-export`. External-aware completion and definition remain native Python editor APIs rather than CLI or MCP commands.

The compiled bundle is the content-based handoff to Houdini MCP. `document.export_source` performs the reverse handoff by returning canonical source plus provenance; the native `write-export` command creates the chosen project file with no-overwrite safeguards. The MCP never reads or edits project files or external roots, and Bundle `0.3` document lowering/live consumption remain blocked under `HS-BLOCK-008`.

## Docs

For the fuller manual, see [HocusPocus Manual](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\user-manual.md).

For compatibility and release rules, see [Compatibility Policy](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\compatibility-policy.md) and [Release Validation](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\release-validation.md).

For agent usage patterns, see [Agent Workflows](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\agent-workflows.md).

For the experimental text authoring frontend, see [HocusScript Spec](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\hocusscript-spec.md), [Roadmap](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\hocusscript-roadmap.md), and [Task Tracker](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\hocusscript-task-tracker.md).

For engineering state, see [Improvement Tracker](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\improvement-task-tracker.md).

## License

MIT. See [LICENSE](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\LICENSE).
