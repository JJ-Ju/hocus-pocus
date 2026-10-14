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
and [09](docs/redesign/review/09-city-destruction-log.md). Since 1.1, `node_edit` adds
spare parms itself, `network_describe {format: "outline"}` shows a whole scene as a
compact tree, and `cook` profiles an input chain or steps a frame range.

1.2 put the `full` profile and the GUI paths to work: a Solaris lookdev rendered with
Karma ([13](docs/redesign/review/13-solaris-lookdev-eval.md)), a PDG wedge
([14](docs/redesign/review/14-pdg-wedge-eval.md)) and a GUI session next to a user
([15](docs/redesign/review/15-gui-session-eval.md)). `viewport_capture {lop_path}` captures a USD
stage, a failed PDG work item carries its log's `error`, and `undo` stops at the user's
own steps.

1.3 added an FX sim cached to disk ([17](docs/redesign/review/17-fx-sim-cache-eval.md)), a Copernicus
image network ([18](docs/redesign/review/18-copernicus-eval.md)) and a GUI Houdini plus a headless
worker in one session ([19](docs/redesign/review/19-two-instances-and-prompts-eval.md)). `render` on
a File Cache writes the cache as a job with progress and cancel, `viewport_capture
{cop_path}` and `geo_info` show a COP image, and with several Houdinis running the agent
pins one by pid or name, so no call lands in the wrong scene.

![City overview captured with viewport_capture](docs/redesign/evidence/city-destruction/02_city_overview.png)

![Simulation frames 1 to 96 and a district close-up](docs/redesign/evidence/city-destruction/20_contact_sheet.png)

- [Karma lookdev](docs/redesign/evidence/city-destruction/30_lookdev_karma.png): the city in `/stage` with MaterialX materials, a dome and a key light, Karma CPU at 640×360 (review 13).
- [PDG wedges](docs/redesign/evidence/city-destruction/40_pdg_wedges.png): eight building-generator wedges cooked through ROP Fetch TOPs, one OpenGL capture each (review 14).
- [GUI viewer](docs/redesign/evidence/city-destruction/50_gui_viewer.png): `viewport_capture` through `cam_district` at frame 72, `opengl_rop` source, in a live GUI Houdini (review 15).
- [Pyro cache](docs/redesign/evidence/city-destruction/60_pyro_frames.png): a smoke plume cached with a File Cache and flipbooked with an OpenGL ROP, frames 1 to 48 (review 17).
- [Copernicus city map](docs/redesign/evidence/city-destruction/70_copernicus_citymap.png): a COP network's image written by `rop_image`, and the SOP city that reads it through `op:` (review 18).
- [Two instances](docs/redesign/evidence/city-destruction/80_two_instance_render.png): frames of a render on a headless worker while the GUI Houdini kept editing (review 19).

## Requirements

- SideFX Houdini **22.0 or newer**, tested on 22.0.466 (`doctor` warns on other 22.x).
- [uv](https://docs.astral.sh/uv/), which provides the Python 3.11+ the bridge needs.
- An MCP client such as Claude Code or Codex.

## Install

HocusPocus is not on PyPI yet, so install it from a checkout:

```bash
git clone https://github.com/JJ-Ju/hocus-pocus && cd hocus-pocus
uv tool install -e .                          # puts hocuspocus and hocuspocus-mcp on PATH
hocuspocus install-houdini                    # add --dev to load this checkout's src/
claude mcp add -s user hocuspocus -- hocuspocus-mcp
hocuspocus launch                             # scripted clients: a Houdini no client owns
```

`-s user` registers the server for every directory. Without it, Claude Code registers it
for the current project only. Once HocusPocus is published, `uv tool install hocuspocus`
will replace the first two lines. Interactive users can simply open Houdini; one-shot
scripts and short sessions should start it with `hocuspocus launch`
([below](#scripted-clients-hocuspocus-launch)), so it outlives them.

`hocuspocus install-houdini` installs into every user pref dir Houdini may use (on
Windows, `Documents\houdini22.0` from the Start menu and `%HOME%\houdini22.0` from a
shell that sets `HOME`), names each one, and records them for the bridge. It is
idempotent; `hocuspocus uninstall-houdini` undoes it. The quickstart lists the candidates.

For Codex, `hocuspocus client-config codex` prints the `~/.codex/config.toml` entry
(`[mcp_servers.hocuspocus]` with `command = "hocuspocus-mcp"`).

**Restart Houdini** after `install-houdini`. The package loads at startup. In a GUI
session, the host starts by itself once the UI is ready. The HocusPocus shelf has
HP Status, HP Start and HP Stop buttons.

Then run `hocuspocus doctor`. It checks the Houdini install and version, the pref dir
and `hocuspocus.toml` the bridge reads, that the package JSON points at a `hocuspocus`
matching the bridge, and each live instance's `/health`; every failure says what to run.
[`docs/quickstart.md`](docs/quickstart.md) has the full walkthrough and troubleshooting.

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

There are 31 tools in the default `core` profile, and the `full` profile adds 4. The
`minimal` profile lists 14 of them for clients with a small context. Each is documented
in [`docs/tools.md`](docs/tools.md) (and the `hocuspocus://tools` resource), generated
from the catalogue.

| Group | Tools |
|---|---|
| Session and instances | `houdini_status`, `houdini_connect` |
| Hip file | `hip_new`, `hip_open`, `hip_save`, `hip_merge` |
| Nodes and networks | `node_find`, `node_info`, `node_create`, `node_delete`, `node_edit` (incl. spare parms), `node_copy`, `node_connect`, `node_layout`, `network_describe` (`data`, `python` or `outline`), `network_build` |
| Parms | `parm_get`, `parm_set` |
| Cook, problems, geometry | `cook` (incl. `profile` and `frame_range`), `problems`, `geo_info`, `geo_read` |
| Visual feedback | `viewport_capture`, `render` |
| Code | `houdini_python` |
| Node types | `node_type_search`, `node_type_info` |
| State and jobs | `undo`, `time`, `selection`, `job` |
| `full` profile only | `hda`, `usd_stage`, `pdg`, `events` |

The bridge also serves resources and prompts:

- **Resources:** `houdini://status`, `houdini://outline` (the whole scene as a compact
  tree), `houdini://node/{path}`, `.../parms`, `.../geo`,
  `houdini://nodetype/{category}/{name}`, `houdini://job/{id}`, the operating manual
  and recipes at `hocuspocus://guide`, and the tool reference at `hocuspocus://tools`.
- **Prompts:** `inspect_scene`, `build_sop_chain`, `debug_red_node`,
  `turntable_preview`. `tools/list` works with no Houdini running.

In a GUI session, `viewport_capture` without `camera` or `fit` grabs the Scene Viewer as
it is; an explicit `fit` frames the grab, and the user's view is put back afterwards.
With a `camera` or `lop_path` (a LOP stage), or `"source": "flipbook_rop"`, it renders
through a Flipbook ROP, framed by a temporary camera when no `camera` is given.
`cop_path` shows a Copernicus node's image in about 0.2 s. To write a cache, `render` the
File Cache (`cook` never writes files): it runs as a job you can poll and cancel.

## Headless use and launching

An agent can start its own Houdini, GUI or headless:

```text
houdini_connect {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}}
```

Headless runs `hython -m hocuspocus.host`; GUI runs `houdinifx` (or `houdini`), found
through the `hfs` setting, `HOCUSPOCUS_HFS`, `HFS`, then the newest `Houdini 22.*`. The
bridge waits until the new instance registers. It starts in `HOCUSPOCUS_WORK_DIR`
(default: your home directory), the `$HIP` and `$JOB` of its untitled scene;
`hocuspocus launch` (below) starts in the directory you run it from instead.

> **Launch lifetime.** A Houdini started with `houdini_connect {launch}` exits with the
> bridge that launched it (the end of a session, or a one-shot script exiting), losing
> unsaved work. `hip_save` first, or start it with `hocuspocus launch` (below).

### Scripted clients: `hocuspocus launch`

This is the recommended way to start Houdini for one-shot scripts and short MCP
sessions. The Houdini it starts belongs to no MCP server and keeps running:

```bash
hocuspocus launch                      # GUI houdinifx with the package loaded
hocuspocus launch --headless --hip C:/work/shot.hip --wait 120
hocuspocus launch --headless --work-dir C:/work/shot010   # $HIP/$JOB of the untitled scene
{"pid": 23310, "port": 53120, "label": "hython", "hip": "C:/work/shot.hip", ..., "mode": "headless"}
```

It uses the same Houdini detection and package path rules as `houdini_connect {launch}`,
waits up to `--wait` seconds (default 90; `0` returns at once) for the host to register,
prints the registry entry (never the token) as one JSON line, and exits. Houdini starts
in the directory the command runs in (or `--work-dir DIR`), so the untitled scene's `$HIP`
and `$JOB` are where you expect. Later sessions attach with
`houdini_connect {"pid": 23310}`, or pick it automatically when it is the only one
running. Close it with `houdini_connect {"quit": true, "on_unsaved": "save"}` (1.2;
`fail`, the default, refuses with unsaved changes), or a GUI one as usual. To run the
host by hand instead, use `hython -m hocuspocus.host [--hip FILE] [--port N]
[--read-only] [--no-python] ...` from a neutral directory (hython puts its cwd on
`HOUDINI_PATH`); it prints `{"pid", "port", "token_file"}` and serves until stopped.
Tools that need the UI return `ui_required` headless; `viewport_capture` works through
a Flipbook ROP in a short-lived child hython (about 3 s).

**Two Houdinis.** Several can run at once, for example the GUI for editing and a
`hocuspocus launch --headless` worker for renders. `houdini_status` lists them (`busy`,
`jobs_running`, `selected`), and `houdini_connect {"pid": N, "name": "worker"}` pins one;
later `{"name": "worker"}` pins it again. Until one is pinned, calls that change a scene
refuse with `ambiguous_instance` (reads go to the GUI session). A pinned Houdini that
exits gives `instance_lost`, never a silent switch. Job ids carry their pid, so `job`
reaches the worker whichever Houdini is pinned, and `job {"action": "list", "all": true}`
lists every instance's jobs.

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
profile = "core"            # both: "minimal" is 14 tools for small contexts; "full" also lists (bridge) and allows (host) hda, usd_stage, pdg, events
hfs = ""                    # bridge: Houdini install used by houdini_connect launch
result_content = "text"     # bridge: text | both | structured (where result JSON goes)
log_level = "INFO"          # host
```

The bridge reads the file from `HOUDINI_USER_PREF_DIR` when it is set, else from the
first recorded or default pref dir that has one; `hocuspocus doctor` prints which file it
reads. Bridge settings can also be set per client, for example
`claude mcp add -s user hocuspocus -e HOCUSPOCUS_PROFILE=full -- hocuspocus-mcp`. Since
1.1 the host enforces `profile` too, refusing the `full` tools on `core` with
`invalid_argument`: set `profile = "full"` in `hocuspocus.toml`, which both read, or in
Houdini's environment (a launched Houdini inherits the launcher's), and restart Houdini.

| Bridge variable | Default | Meaning |
|---|---|---|
| `HOCUSPOCUS_PROFILE` | `core` | `minimal` lists 14 tools; `full` also lists `hda`, `usd_stage`, `pdg`, `events` |
| `HOCUSPOCUS_MAX_RESPONSE_BYTES` | `16384` | response budget; lists are truncated with `truncated: true` |
| `HOCUSPOCUS_DEFAULT_TIMEOUT_S` | `30` | per-call timeout sent to the host |
| `HOCUSPOCUS_HFS` | auto | Houdini install used by `houdini_connect` launch |
| `HOCUSPOCUS_RESULT_CONTENT` | `text` | where result JSON goes: `text` block only, `both` (adds `structuredContent`), or `structured` |
| `HOCUSPOCUS_WORK_DIR` | home | where `houdini_connect {launch}` starts Houdini (environment only; `hocuspocus launch` uses its cwd or `--work-dir`) |

`HOCUSPOCUS_STATE_DIR` moves the shared state directory. That directory holds the
instance registry, logs and captures. The default is `%LOCALAPPDATA%\HocusPocus` on
Windows and `$XDG_STATE_HOME/hocuspocus` (or `~/.local/state/hocuspocus`) elsewhere.

## Security model

HocusPocus is a localhost developer tool, and its protection is scoped to match:

- **Network.** The host binds only to `127.0.0.1`, on an ephemeral port.
- **Token.** Each instance has its own bearer token. It is stored in a registry file
  that only your user can read.
- **Browser requests.** Requests with a non-loopback `Origin` or `Host` header are
  refused, which also stops DNS rebinding.
- **Settings.** `allow_python = false` disables the Python escape hatch,
  `read_only = true` refuses every mutation, and `approved_roots` restricts the file
  paths that hip, HDA and render tools may touch.
- **Undo and unsaved work.** Every mutating call is exactly one undo group. Hip tools
  never discard unsaved work unless told to with `on_unsaved`.

There are no integrity manifests or rate limits. Those would not stop an agent that
already has a shell on your machine.

## Status and versioning

1.0 was merged to `master` on 2026-10-12 (tag `v1.0.0`). 1.1, 1.2 and 1.3 change some
result shapes and defaults; [`CHANGELOG.md`](CHANGELOG.md) lists them with upgrade notes and
known limitations. HocusPocus is not on PyPI yet. It is qualified on Windows with Houdini
22.0.466; the code is not Windows-only, but Linux and macOS are untested.

The host/bridge protocol is versioned (`hp/v1`). A version mismatch returns
`version_mismatch`; run `hocuspocus install-houdini` and restart Houdini to fix it.

The 0.9 line (HocusScript, network documents, source workspaces) is preserved at the
`v0.9-archive` tag. The reviews and evaluations behind the rewrite are indexed in
[`docs/redesign/README.md`](docs/redesign/README.md). Contributing and release steps:
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## License

MIT. See [`LICENSE`](LICENSE).
