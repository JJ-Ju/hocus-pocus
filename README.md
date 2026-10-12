# HocusPocus

HocusPocus is an [MCP](https://modelcontextprotocol.io) server that lets AI agents
(Claude Code, Codex, any MCP client) drive a live SideFX Houdini session: create and
wire nodes, set parms, cook, inspect geometry, look at the viewport, and open, save and
merge hip files. It speaks Houdini's own vocabulary. Identity is node paths and parm
paths, graphs are read and written in Houdini's native `hou.data` format, and there is
a Python escape hatch for everything else.

It runs as two processes. A thin **bridge** (`hocuspocus-mcp`, standard CPython plus the
official `mcp` SDK) talks MCP over stdio to your client. A small stdlib-only **host**
runs inside Houdini, GUI or headless `hython`. The bridge finds or launches a Houdini
and forwards each tool call over an authenticated loopback HTTP channel. The host runs
every `hou` call on Houdini's main thread inside one named undo group and returns
compact JSON. Errors carry a stable `code`, a `hint` and, when a name was close,
`candidates`. The design is in [`docs/BIBLE.md`](docs/BIBLE.md).

## What it can do

In one test session an agent built a procedural building generator and a 191-building
city, then fractured 30 buildings and ran a 96-frame rigid-body simulation of meteors
hitting them, using two `houdini_python` calls (to add spare parms) and otherwise only
the typed tools. The logs are reviews [08](docs/redesign/review/08-city-build-log.md)
and [09](docs/redesign/review/09-city-destruction-log.md).

![City overview captured with viewport_capture](docs/redesign/evidence/city-destruction/02_city_overview.png)

![Simulation frames 1 to 96 and a district close-up](docs/redesign/evidence/city-destruction/20_contact_sheet.png)

## Requirements

- SideFX Houdini **22.0 or newer**. Tested on 22.0.466. Other 22.x builds work, and
  `hocuspocus doctor` prints a warning for them.
- [uv](https://docs.astral.sh/uv/). The bridge needs Python 3.11 or newer, and uv
  provides one.
- An MCP client such as Claude Code or Codex.

## Install

HocusPocus is not on PyPI yet, so install it from a checkout:

```bash
git clone https://github.com/JJ-Ju/hocus-pocus && cd hocus-pocus
uv tool install -e .                          # puts hocuspocus and hocuspocus-mcp on PATH
hocuspocus install-houdini                    # add --dev to load this checkout's src/
claude mcp add -s user hocuspocus -- hocuspocus-mcp
```

`-s user` registers the server for every directory. Without it, Claude Code registers it
for the current project only. Once HocusPocus is published, `uv tool install hocuspocus`
will replace the first two lines.

`hocuspocus install-houdini` finds your Houdini user pref dir in this order: `--prefs`,
`$HOUDINI_USER_PREF_DIR`, what `hython` reports for `hou.homeHoudiniDirectory()`, then
the platform default. Its first output line says which one it used and why, for example
`C:\Users\you\houdini22.0 (from hython (...))`. It copies the package and the Houdini
payload to `<prefs>/hocuspocus/<version>/`, writes `<prefs>/packages/hocuspocus.json`,
and records the pref dir in `<state dir>/install.json` so the bridge can find
`hocuspocus.toml`.

The command is idempotent and removes older versions. `--dev` points Houdini at the
checkout's `src/` and `houdini/` instead of copying, so edits take effect on the next
Houdini start. Use `--hfs` to say which Houdini install to ask.
`hocuspocus uninstall-houdini` removes the package, the JSON and the record.

For Codex, add this to `~/.codex/config.toml` (`hocuspocus client-config codex` prints
it):

```toml
[mcp_servers.hocuspocus]
command = "hocuspocus-mcp"
args = []
```

**Restart Houdini** after `install-houdini`. The package loads at startup. In a GUI
session, the host starts by itself once the UI is ready. The HocusPocus shelf has
HP Status, HP Start and HP Stop buttons.

Then check everything with `hocuspocus doctor`. It checks that Houdini is found and is
22.0 or newer, shows the pref dir and which `hocuspocus.toml` the bridge reads, checks
that the package JSON points at an installed `hocuspocus` whose version matches the
bridge, and asks each live instance for `/health`. It ends with `doctor: all checks passed` or `doctor: N problem(s)`. Each failure says
what to run. [`docs/quickstart.md`](docs/quickstart.md) has the full walkthrough and a
troubleshooting list.

## First session

You ask: *"Make a terrain from a grid with a mountain on it and show me."* The agent
then makes these calls:

```text
houdini_status   {}
  -> {"connected": {"pid": 18244, "houdini": "22.0.466", "ui": true,
       "hip": {"name": "untitled.hip", "dirty": false}, ...}, "instances": [...]}
node_create      {"items": [
                   {"parent": "/obj", "type": "geo", "name": "terrain"},
                   {"parent": "/obj/terrain", "type": "grid", "parms": {"size": [10, 10], "rows": 100, "cols": 100}},
                   {"parent": "/obj/terrain", "type": "mountain", "inputs": [{"index": 0, "from": "/obj/terrain/grid1"}],
                    "flags": {"display": true, "render": true}}]}
  -> {"results": [{"path": "/obj/terrain", ...}, {"path": "/obj/terrain/grid1", ...},
                  {"path": "/obj/terrain/mountain1", "errors": [], "warnings": []}]}
cook             {"paths": ["/obj/terrain/mountain1"]}
  -> {"ok": true, "results": [{"path": "/obj/terrain/mountain1", "errors": [], "cook_time_ms": 41}]}
viewport_capture {}
  -> [PNG image] + {"path": ".../captures/....png", "width": 1024, "height": 768, "camera_used": "..."}
```

The `node_create` call is one undo step. Ctrl+Z in Houdini, or the `undo` tool, takes it
back. The output above is shortened. [`docs/tools.md`](docs/tools.md) has the real
schemas and examples.

## Tools

There are 31 tools in the default `core` profile. The `full` profile adds 4 more. Every
tool is documented in [`docs/tools.md`](docs/tools.md), which is generated from the
catalogue.

| Group | Tools |
|---|---|
| Session and instances | `houdini_status`, `houdini_connect` |
| Hip file | `hip_new`, `hip_open`, `hip_save`, `hip_merge` |
| Nodes and networks | `node_find`, `node_info`, `node_create`, `node_delete`, `node_edit`, `node_copy`, `node_connect`, `node_layout`, `network_describe`, `network_build` |
| Parms | `parm_get`, `parm_set` |
| Cook, problems, geometry | `cook`, `problems`, `geo_info`, `geo_read` |
| Visual feedback | `viewport_capture`, `render` |
| Code | `houdini_python` |
| Node types | `node_type_search`, `node_type_info` |
| State and jobs | `undo`, `time`, `selection`, `job` |
| `full` profile only | `hda`, `usd_stage`, `pdg`, `events` |

The bridge also serves resources and prompts:

- **Resources:** `houdini://status`, `houdini://node/{path}`,
  `houdini://node/{path}/parms`, `houdini://node/{path}/geo`,
  `houdini://nodetype/{category}/{name}`, `houdini://job/{id}`, and the full operating
  manual at `hocuspocus://guide`.
- **Prompts:** `inspect_scene`, `build_sop_chain`, `debug_red_node`,
  `turntable_preview`.

`tools/list` works with no Houdini running.

In a GUI session, `viewport_capture` defaults to the Scene Viewer and captures the view
as it is: it does not frame the scene. Home the view first, or pass
`"source": "opengl_rop"`, which frames the scene with a temporary camera.

## Headless use and launching

An agent can start its own Houdini, GUI or headless:

```text
houdini_connect {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}}
```

Headless runs `hython -m hocuspocus.host` from the detected Houdini install; GUI runs
`houdinifx` (or `houdini`). Detection uses the `hfs` setting, then `HOCUSPOCUS_HFS`,
then `HFS`, then the newest `Side Effects Software/Houdini 22.*`. The bridge waits
until the new instance registers. A launched Houdini starts in `HOCUSPOCUS_WORK_DIR`
(default: your home directory), which is the `$HIP` of its untitled scene.

> **Launch lifetime.** A Houdini started with `houdini_connect {launch}` belongs to the
> bridge that launched it. When the client stops that bridge (the end of a Claude Code
> session, or a one-shot script exiting), that Houdini exits too and unsaved work is
> lost. Save with `hip_save` first, or start Houdini with `hocuspocus launch` (below) and
> let the bridge attach to it.

### Scripted clients: `hocuspocus launch`

One-shot scripts and short MCP sessions should not own the Houdini they drive. Start it
from a terminal instead, where it belongs to no MCP server and keeps running:

```bash
hocuspocus launch                      # GUI houdinifx with the package loaded
hocuspocus launch --headless --hip C:/work/shot.hip --wait 120
{"pid": 23310, "port": 53120, "label": "hython", "hip": "C:/work/shot.hip", ..., "mode": "headless"}
```

It uses the same Houdini detection and package path rules as `houdini_connect {launch}`,
waits up to `--wait` seconds (default 90; `0` returns at once) for the host to register,
prints the registry entry (never the token) as one JSON line, and exits. Any later
session attaches with `houdini_connect {"pid": 23310}`, or picks it automatically when it
is the only one running. Close a GUI one as usual; end a headless one's process (its pid
is in the JSON) once its work is saved.

You can also start the host yourself. Do it from a neutral working directory, because
hython puts its cwd on `HOUDINI_PATH`:

```bash
hython -m hocuspocus.host [--hip FILE] [--port N] [--state-dir DIR] [--label NAME] \
  [--read-only] [--no-python] [--work-dir DIR]
```

The host prints one JSON line (`{"pid", "port", "token_file"}`) and serves until it is
interrupted or shut down. The port defaults to 0, which picks a free ephemeral port.

Tools that need the UI return `ui_required` headless. `viewport_capture` still works
headless through an OpenGL ROP; each capture renders in a short-lived child hython and
takes about 3 s. Several Houdinis can run at once. Each one registers itself,
`houdini_status` lists them all, and `houdini_connect {"pid": N}` picks one.

## Configuration

Everything has a default, and no configuration file is required.

One optional file, `$HOUDINI_USER_PREF_DIR/hocuspocus.toml`, serves both the host
(inside Houdini) and the bridge (`hocuspocus-mcp`). Each key can be overridden by an
environment variable named `HOCUSPOCUS_<KEY>`, for example `HOCUSPOCUS_ALLOW_PYTHON=0`;
**the environment always wins over the file**. A `[hocuspocus]` table is also accepted.
Unknown or invalid keys are logged and ignored.

```toml
autostart = true            # host: GUI sessions start the host when the UI is ready
allow_python = true         # host: houdini_python escape hatch
read_only = false           # host: refuse all mutating tools
approved_roots = []         # host: if non-empty, hip/hda/render paths must be under these
max_response_bytes = 16384  # both: response budget
default_timeout_s = 30      # both: per-call timeout
job_threshold_s = 10        # host: cooks longer than this become jobs
profile = "core"            # bridge: "full" also lists hda, usd_stage, pdg, events
hfs = ""                    # bridge: Houdini install used by houdini_connect launch
result_content = "text"     # bridge: text | both | structured (see below)
log_level = "INFO"          # host
```

`result_content` decides where a tool result's JSON goes. `text` (the default) sends the
compact JSON in the text block only, with no `structuredContent` and no `outputSchema` in
`tools/list`: measured in 1.1, Claude Code shows the model only the text block, so a
structured copy only doubled every result on the wire. `both` restores the 1.0 shape (the
same JSON in both places) for clients that read `structuredContent`; `structured` keeps
the data in `structuredContent` and puts a one-line summary (`node_info: ok`, or
`<code>: <message>` for an error) in the text block. Images are image blocks in every mode.

Houdini resolves the pref dir itself. The bridge cannot ask Houdini, so it looks in
`HOUDINI_USER_PREF_DIR` (with `__HVER__` read as `22.0`), then in the pref dir that
`hocuspocus install-houdini` recorded in `<state dir>/install.json`, then in the default
locations (`%USERPROFILE%\houdini22.0` and `Documents\houdini22.0` on Windows).
`hocuspocus doctor` prints which file the bridge reads. Bridge settings can also be set
per client, for example
`claude mcp add -s user hocuspocus -e HOCUSPOCUS_PROFILE=full -- hocuspocus-mcp`.

| Bridge variable | Default | Meaning |
|---|---|---|
| `HOCUSPOCUS_PROFILE` | `core` | `full` also lists `hda`, `usd_stage`, `pdg`, `events` |
| `HOCUSPOCUS_MAX_RESPONSE_BYTES` | `16384` | response budget; lists are truncated with `truncated: true` |
| `HOCUSPOCUS_DEFAULT_TIMEOUT_S` | `30` | per-call timeout sent to the host |
| `HOCUSPOCUS_HFS` | auto | Houdini install used by `houdini_connect` launch |
| `HOCUSPOCUS_RESULT_CONTENT` | `text` | `text`, `both` or `structured`: where result JSON goes |
| `HOCUSPOCUS_WORK_DIR` | home | where a launched Houdini starts (environment only) |

`HOCUSPOCUS_STATE_DIR` moves the shared state directory. That directory holds the
instance registry, logs and captures. The default is `%LOCALAPPDATA%\HocusPocus` on
Windows and `$XDG_STATE_HOME/hocuspocus` (or `~/.local/state/hocuspocus`) elsewhere.

## Security model

HocusPocus is a localhost developer tool, and its protection is scoped to match:

- **Network.** The host binds only to `127.0.0.1`, on an ephemeral port.
- **Token.** Each instance has its own bearer token. It is stored in a registry file
  that only your user can read.
- **Browser requests.** Requests with a non-loopback `Origin` header are refused.
- **Settings.** `allow_python = false` disables the Python escape hatch,
  `read_only = true` refuses every mutation, and `approved_roots` restricts the file
  paths that hip, HDA and render tools may touch.
- **Undo and unsaved work.** Every mutating call is exactly one undo group. Hip tools
  never discard unsaved work unless told to with `on_unsaved`.

There are no integrity manifests or rate limits. Those would not stop an agent that
already has a shell on your machine.

## Status and versioning

1.0 was merged to `master` on 2026-10-12. The package version string is still
`1.0.0` (tag `v1.0.0`); it is not on PyPI yet. 1.0 is qualified on
Windows with Houdini 22.0.466. The code is not Windows-only, but 1.0 is not tested on
Linux or macOS. [`CHANGELOG.md`](CHANGELOG.md) lists known limitations.

The host/bridge protocol is versioned (`hp/v1`). A version mismatch returns
`version_mismatch`; run `hocuspocus install-houdini` and restart Houdini to fix it.

The 0.9 line (HocusScript, network documents, source workspaces) is preserved at the
`v0.9-archive` tag. The reviews and evaluations behind the rewrite are indexed in
[`docs/redesign/README.md`](docs/redesign/README.md). Contributing and release steps:
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## License

MIT. See [`LICENSE`](LICENSE).
