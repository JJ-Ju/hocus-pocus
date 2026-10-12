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

## Requirements

- SideFX Houdini **22.0 or newer**. Tested on 22.0.466. Other 22.x builds work, and
  `hocuspocus doctor` prints a warning for them.
- [uv](https://docs.astral.sh/uv/). The bridge needs Python 3.11 or newer, and uv
  provides one.
- An MCP client such as Claude Code or Codex.

## Install

```bash
uv tool install hocuspocus                    # not on PyPI yet: use the checkout form below
hocuspocus install-houdini
claude mcp add hocuspocus -- hocuspocus-mcp
```

HocusPocus is not on PyPI yet, so install it from a checkout:

```bash
git clone https://github.com/JJ-Ju/hocus-pocus && cd hocus-pocus
uv tool install -e .
```

`hocuspocus install-houdini` finds your Houdini user pref dir in this order: `--prefs`,
`$HOUDINI_USER_PREF_DIR`, what `hython` reports for `hou.homeHoudiniDirectory()`, then
the platform default. It then does two things:

1. Copies the package to `<prefs>/hocuspocus/<version>/`.
2. Writes `<prefs>/packages/hocuspocus.json`.

The command is idempotent and removes older versions. To develop against a checkout,
`--dev` points Houdini at the checkout's `src/` instead of copying. Use `--hfs` to say
which Houdini install to ask. `hocuspocus uninstall-houdini` removes both pieces.

For Codex, print the snippet and add it to `~/.codex/config.toml`:

```bash
hocuspocus client-config codex
```

```toml
[mcp_servers.hocuspocus]
command = "hocuspocus-mcp"
args = []
```

**Restart Houdini** after `install-houdini`. The package loads at startup. In a GUI
session, the host starts by itself once the UI is ready. The HocusPocus shelf has Status,
Start and Stop buttons.

Check everything with:

```bash
hocuspocus doctor
```

`doctor` checks that:

- Houdini is found and its version is 22.0 or newer.
- The package JSON exists and points at an installed `hocuspocus`.
- The host and bridge versions match.
- Live instances answer `/health`.

It ends with `doctor: all checks passed` or `doctor: N problem(s)`. Each failure says
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


> **Launch lifetime.** A Houdini started with `houdini_connect {launch}` is a child of the MCP server process. When the client stops that server (end of a Claude Code session, or a one-shot script exiting), Houdini closes with it. Save with `hip_save` first, or start Houdini yourself and let the bridge attach to it.

## Headless use

An agent can start its own headless Houdini:

```text
houdini_connect {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}}
```

That runs `hython -m hocuspocus.host` from the detected Houdini install. Detection uses
`HOCUSPOCUS_HFS`, then `HFS`, then the newest `Side Effects Software/Houdini 22.*`. The
bridge waits until the new instance registers.

You can also start the host yourself. Do it from a neutral working directory, because
hython puts its cwd on `HOUDINI_PATH`:

```bash
hython -m hocuspocus.host [--hip FILE] [--port N] [--state-dir DIR] [--label NAME] [--read-only] [--no-python]
```

The host prints one JSON line (`{"pid", "port", "token_file"}`) and serves until it is
interrupted or shut down. The port defaults to 0, which picks a free ephemeral port.

Tools that need the UI return `ui_required` headless. `viewport_capture` still works
headless through an OpenGL ROP. Several Houdinis can run at once. Each one registers
itself, `houdini_status` lists them all, and `houdini_connect {"pid": N}` picks one.

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
log_level = "INFO"          # host
```

Houdini resolves the pref dir itself. The bridge cannot ask Houdini, so it looks in
`HOUDINI_USER_PREF_DIR` (with `__HVER__` read as `22.0`), then in the pref dir that
`hocuspocus install-houdini` recorded in `<state dir>/install.json`, then in the default
locations (`%USERPROFILE%\houdini22.0` and `Documents\houdini22.0` on Windows).
`hocuspocus doctor` prints which file the bridge reads. Bridge settings can also be set
per client, for example
`claude mcp add hocuspocus -e HOCUSPOCUS_PROFILE=full -- hocuspocus-mcp`.

| Bridge variable | Default | Meaning |
|---|---|---|
| `HOCUSPOCUS_PROFILE` | `core` | `full` also lists `hda`, `usd_stage`, `pdg`, `events` |
| `HOCUSPOCUS_MAX_RESPONSE_BYTES` | `16384` | response budget; lists are truncated with `truncated: true` |
| `HOCUSPOCUS_DEFAULT_TIMEOUT_S` | `30` | per-call timeout sent to the host |
| `HOCUSPOCUS_HFS` | auto | Houdini install used by `houdini_connect` launch |

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

The current version is **1.0.0** (pre-release, `1.0.0a0` in `pyproject.toml`), developed
on the `redesign/v1` branch. 1.0 is qualified on Windows with Houdini 22.0.466. The code
is not Windows-only, but 1.0 is not tested on Linux or macOS.

The host/bridge protocol is versioned (`hp/v1`). A version mismatch returns
`version_mismatch`; run `hocuspocus install-houdini` and restart Houdini to fix it.

The 0.9 line (HocusScript, network documents, source workspaces) is preserved at the
`v0.9-archive` tag. [`CHANGELOG.md`](CHANGELOG.md) lists what changed.

Contributing: see [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## License

MIT. See [`LICENSE`](LICENSE).
