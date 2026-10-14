# Quickstart

This guide takes about five minutes. You start with nothing installed and finish with a
box sitting on a mountain, plus a picture your agent has looked at. The commands are
shown for Windows (PowerShell or Git Bash). On Linux, the paths differ but the commands
are the same.

This is HocusPocus 2.0: the agent changes the scene with `edit` (every change of a task in
one call and one undo step), reads it with `inspect` and `search`, and sees it with `look`.
Coming from 1.4? The install is the same; [`migration-2.0.md`](migration-2.0.md) maps the
old tool names, and `profile = "compat_1x"` keeps 1.4 scripts running for 2.0.x.

You need:

- Houdini 22.0 or newer, installed and licensed.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Claude Code (`claude`) or Codex.

## 1. Install the tool (1 minute)

HocusPocus is not on PyPI yet, so install it from a checkout:

```bash
git clone https://github.com/JJ-Ju/hocus-pocus
cd hocus-pocus
uv tool install -e .
```

Once it is published, `uv tool install hocuspocus` will do the same thing. Either way
you get two commands on your `PATH`: `hocuspocus` and `hocuspocus-mcp`.

```text
$ hocuspocus version
hocuspocus 2.0.0 (hp/v1, mcp 2.3.x, Python 3.12.x)
```

## 2. Install the Houdini package (1 minute)

```text
$ hocuspocus install-houdini
Houdini pref dir: C:\Users\you\Documents\houdini22.0 (from hython (C:\Program Files\Side Effects Software\Houdini 22.0.466), default location)
copied hocuspocus 2.0.0 to C:\Users\you\Documents\houdini22.0\hocuspocus\2.0.0\python\hocuspocus
copied the Houdini payload to C:\Users\you\Documents\houdini22.0\hocuspocus\2.0.0\houdini
wrote C:\Users\you\Documents\houdini22.0\packages\hocuspocus.json (template: ...\houdini\hocuspocus.json.template)
recorded the pref dirs in C:\Users\you\AppData\Local\HocusPocus\install.json (the bridge reads hocuspocus.toml from there)
Restart Houdini to load HocusPocus.
Then register the MCP server with your client, e.g.: claude mcp add -s user hocuspocus -- hocuspocus-mcp
```

The `Houdini pref dir:` lines tell you which pref dirs it found and why. On Windows
Houdini's pref dir depends on how it was started: from the Start menu (no `HOME`
variable) it is `C:\Users\you\Documents\houdini22.0`; from a shell that sets `HOME`
(Git Bash, some terminals) it is `%HOME%\houdini22.0`. When both exist, `install-houdini`
installs into both and lists each `wrote ...` line, so Houdini loads HocusPocus however
you start it. The candidates, deduplicated, are:

1. `--prefs` (created if missing).
2. `$HOUDINI_USER_PREF_DIR` (`__HVER__` expanded).
3. What `hython` reports for `hou.homeHoudiniDirectory()`, and on Windows what it
   reports with `HOME` removed. Asking hython takes a few seconds.
4. The existing default locations: `~/houdiniX.Y` and `~/Documents/houdiniX.Y`.

Only `--prefs` is ever created; a candidate that does not exist is shown as skipped. If
a directory is missing from the list, run the command again with `--prefs <dir>`. If several Houdinis are installed, `--hfs <install dir>` chooses which
one to ask. To develop HocusPocus itself, `hocuspocus install-houdini --dev` points
Houdini at the checkout's `src/` instead of copying it.

## 3. Register with your client (10 seconds)

```bash
claude mcp add -s user hocuspocus -- hocuspocus-mcp
```

`-s user` makes the server available in every directory. Without it, Claude Code
registers it only for the directory you ran the command in. (The hint that
`install-houdini` and `doctor` print omits `-s user`.)

For Codex, add the output of `hocuspocus client-config codex` to
`~/.codex/config.toml`:

```toml
[mcp_servers.hocuspocus]
command = "hocuspocus-mcp"
args = []
```

## 4. Start (or restart) Houdini and check (1 minute)

Houdini reads packages only at startup, so **restart it** if it was already open. Once
the UI is up, the host starts by itself. Then run:

```text
$ hocuspocus doctor
hocuspocus 2.0.0 (bridge, hp/v1)
[ok]   Houdini install: C:\Program Files\Side Effects Software\Houdini 22.0.466
[ok]   Houdini version: 22.0.466
[ok]   pref dir: C:\Users\you\Documents\houdini22.0 (from hython (...), default location): package JSON -> C:\Users\you\Documents\houdini22.0\hocuspocus\2.0.0\python (2.0.0)
[ok]   hocuspocus.toml: none (defaults)
[ok]   package JSON: C:\Users\you\Documents\houdini22.0\packages\hocuspocus.json -> C:\Users\you\Documents\houdini22.0\hocuspocus\2.0.0\python
[ok]   host/bridge version: 2.0.0
[ok]   instance /health: pid 18244 port 52311 GUI (untitled) Houdini 22.0.466

Register with Claude Code:
  claude mcp add -s user hocuspocus -- hocuspocus-mcp
Register with Codex (~/.codex/config.toml):
  [mcp_servers.hocuspocus]
  command = "hocuspocus-mcp"
  args = []

doctor: all checks passed
```

A tested Houdini build shows `[ok]` on the version line. Any other 22.x build shows
`[warn]`, and that is fine.

Opening Houdini yourself is right for an interactive session. If a script or a short
MCP session will drive it instead, start it with `hocuspocus launch` (see
[Scripted clients](#scripted-clients)) so that it outlives them.

## 5. Ask for a mountain (2 minutes)

Start `claude` in any directory and type:

> Put a box on top of a mountain in /obj, then show me a picture.

Expect a sequence close to this one:

1. `houdini_status`. Finds your Houdini, its pid, its role (`editor` for a GUI) and that
   the hip file is `untitled.hip`.
2. One `edit` call with a list of `create` ops: a `geo` node `/obj/scene`, a `grid` with
   more rows and columns, a `mountain` wired to it, a `box`, a `transform` that lifts the
   box and a `merge`, with the display flag on the last node. Each op can carry an `id`,
   and later ops wire to it as `$id`, so the whole build is one call and one undo step.
   Its `nodes` rows report each node's errors and cook state, so no separate cook is
   needed. If the agent is unsure of a type name it calls `search {"kind": "types"}`
   first, or sends the `edit` with `"dry_run": true`, which checks every op and changes
   nothing. If something is red, one more `edit` with `set` or `connect` ops fixes it.
3. `inspect {"what": "geo", "target": ...}` on the display node. Gives point counts and
   a bounding box, so the agent can check that the box sits above the terrain.
4. `look {"target": "/obj/scene"}`. Returns a PNG that the agent can see, plus the file
   path under `%LOCALAPPDATA%\HocusPocus\captures\`. It renders through a Flipbook ROP
   with a temporary camera framed on the target (`quality: "draft"`, the default), in
   the GUI and headless alike. Ask for `"quality": "lit"` to use the scene's lights,
   `"final"` for a Karma render, or `"source": "viewer"` to grab your Scene Viewer exactly
   as you see it (your view is put back afterwards).

To give a network control parms, ask for them: the agent adds spare parms to a `null`
with an `edit` `node` op (`spare_parms`) and links other parms with `ch()` in the same
call. A `menu` spare parm is a string menu by default (VEX reads the token with `chs()`);
with `value_type: "int"` it is an int parm whose value is the item index (`ch()` or
`chi()`). A graph rebuilt with a `build` op (Houdini's `hou.data`) sets parms without
running their callbacks; the result notes each one, and `press: {"geo1/src":
["initialize"]}` runs them after the build.

The nodes appear in your network editor as they are created. To revert the whole build,
press Ctrl+Z in Houdini once, or ask the agent to call `undo`. To keep the scene, ask it
to save. `hip_save` with a `path` saves as, and it creates missing directories.

That's it. [`tools.md`](tools.md) documents every tool with examples. The full design is
in [`BIBLE.md`](BIBLE.md).

## No GUI? Run it headless

The agent can start its own hython:

> Launch a headless Houdini and build the same thing.

That calls `houdini_connect {"launch": {"mode": "headless"}}`, which runs
`hython -m hocuspocus.host` and waits for it to register. The new Houdini starts in
`HOCUSPOCUS_WORK_DIR` (default: your home directory).

A Houdini launched this way, GUI or headless, belongs to the bridge that launched it.
When your client stops the bridge (for example when the Claude Code session ends), that
Houdini exits and its unsaved work is lost. Ask the agent to `hip_save` before you
finish, or start Houdini with `hocuspocus launch` (next section) and let the bridge
attach to it.

You can also start the host yourself from an empty directory:

```bash
mkdir -p /tmp/hp && cd /tmp/hp
hython -m hocuspocus.host --hip C:/work/shot.hip
{"pid": 23310, "port": 53120, "token_file": "..."}
```

## Scripted clients

`hocuspocus launch` is the recommended way to start Houdini for a one-shot script (or any
MCP session shorter than the work). Do not let the script launch it with
`houdini_connect {launch}`: that Houdini closes when the script's MCP server exits. A
Houdini started from a terminal with `hocuspocus launch` belongs to no server and keeps
running across sessions:

```bash
$ hocuspocus launch --headless --hip C:/work/shot.hip
{"pid": 23310, "port": 53120, "label": "hython", "hip": "C:/work/shot.hip", ..., "mode": "headless"}
```

Leave out `--headless` for a GUI Houdini. The command waits up to `--wait` seconds
(default 90) for the host to register, prints its registry entry and exits. Houdini starts
in the directory you ran the command from (or `--work-dir DIR`): that is `$HIP` and `$JOB`
until the first `hip_save`. `houdini_connect {launch}` starts in `HOCUSPOCUS_WORK_DIR`,
else your home directory. Each session
then attaches with `houdini_connect {"pid": 23310}` (or automatically, when it is the only
Houdini running), and `hip_save` keeps the work between sessions. When the work is done,
`houdini_connect {"quit": true, "on_unsaved": "save"}` saves and closes that Houdini.
`on_unsaved` defaults to `fail`, which refuses while there are unsaved changes, and
`discard` drops them.

## Solaris, PDG and assets

USD reads and looks work in the default `core` profile; PDG, `events` and HDAs need the
`full` profile (see [Configuration](#configuration)):

- **Look at a USD stage.** `look {"target": "/stage/OUT"}` renders the stage through a
  Flipbook ROP, framed on it; `"quality": "final"` renders it with Karma. `camera` also
  takes a LOP camera node or a camera prim path. `inspect {"what": "stage", "target":
  "/stage/OUT", "summary": true}` returns the prim count, the counts by type and the world
  bounding box in one small result. On LOP nodes, `set` ops and `parm_set` accept USD
  attribute names such as `inputs:intensity`.
- **Export USD and check it.** `render {"rop_path": "/stage/usd_rop1", "wait_s": 0}`
  renders the ROP's own frame range into its one layer in a single call, then reads the
  layer back: fewer time samples than frames fails with `cook_failed`. The result lists
  each file once, plus `layers` with every layer file the export wrote and its time
  samples. `inspect {"what": "stage"}` and `look` on a `usd_rop` or `usdrender_rop` read
  the stage it renders, and `render {"camera": "/cameras/cam"}` renders through another
  camera.
- **See why PDG work failed** (`full`). A failed work item in `pdg {"action":
  "workitems"}` carries `error` (the last error lines of its log), `log_path` and
  `exit_code`, and `"state": "failed"` lists only the failed items. A cook result lists
  the first five `failures`, and `inspect {"what": "problems"}` reports the TOP node.
  Graphs with ROP Fetch load the saved hip, so `pdg cook` refuses unsaved changes: run
  `hip_save` first, or pass `"save": true`.
- **Work next to a user.** Every `events` entry (`full`, or `inspect {"what": "events"}`)
  says `origin: agent` or `other` (`houdini` for parms Houdini wrote itself during an
  agent call). `undo` stops before a step the user made unless you pass
  `include_user_steps: true`. Your own edits count as unsaved changes; the agent's reads
  and looks never do.

## Caches, Copernicus and two Houdinis

These work in the default `core` profile:

- **Write a sim cache.** `cook` never writes files: cooking a File Cache passes the
  geometry through, and the result says so. To write the cache, `render` the File Cache
  SOP: `render {"rop_path": "/obj/pyro/cache", "wait_s": 0}` returns a `job_id` at once,
  writes the node's own frame range with per-frame progress, and turns on Load from Disk
  when it is done, as the Save to Disk button would. `job {"action": "cancel"}` stops it
  and keeps the frames already written. `inspect {"what": "geo", "frame": 24}` reads the
  cache at a frame without moving the playbar, and `houdini_status` reports Houdini's
  memory. The `cache_sim` prompt walks through all of it.
- **Look at a Copernicus image.** COP networks live in `/img` (an `edit` create op with
  `"parent": "/img", "type": "copnet"`), and their nodes are category `Cop`.
  `look {"target": "/img/copnet1/blend1"}` returns that node's image in about 0.2 s, and
  `inspect {"what": "image"}` on it returns its resolution and per-channel min/max/mean.
  To write the image to disk, `render` a `rop_image` wired to the node. A SOP reads a COP
  live through an `op:` path, for example `attribfrommap` with
  `filename: "op:/img/copnet1/blend1"`.
- **Drive two Houdinis.** Keep the GUI for editing and start a worker for renders with
  `hocuspocus launch --headless`. Every Houdini has a role: `editor` for a GUI, `worker`
  headless. With two running, ask the agent to pin one (`houdini_connect {"role":
  "editor"}`, or `{"pid": 3084, "name": "shots"}`); until then calls that change a scene
  refuse with `ambiguous_instance`, and reads go to the GUI. The usual hand-off is
  `hip_save` in the GUI, `hip_open` of the saved hip on the worker, then
  `render {"rop_path": "/out/karma1", "on": "worker", "wait_s": 0}` with the GUI still
  pinned: `on` runs `cook`, `render`, `look` and `job` on another Houdini without moving
  the pin. The `job_id` (`j3f9a1c`) is kept in the bridge's ledger, so `job` reaches the
  worker whichever Houdini is pinned, even after the MCP server restarts, and
  `job {"action": "list", "all": true}` lists every Houdini's jobs. If the pinned Houdini
  exits, every call returns `instance_lost` until you pin another; the bridge never
  switches on its own. The `two_houdinis` prompt and the `hocuspocus://guide` resource
  have this recipe.

## Configuration

Nothing needs configuring for this guide. Two settings in
`$HOUDINI_USER_PREF_DIR/hocuspocus.toml` (or `HOCUSPOCUS_*` environment variables, which
win) matter most for scripts and other clients:

```toml
profile = "full"            # also list and allow hda, pdg and events (default "core"; "minimal" lists 10 tools; "compat_1x" the 1.4 tools)
result_content = "both"     # also send structuredContent (default "text")
```

- `profile` is read by the bridge, which lists the tools, and by the host inside Houdini,
  which refuses the tools outside its profile. Restart Houdini after changing it.
  `minimal` lists 10 tools (`houdini_status`, `houdini_connect`, `hip_open`, `hip_save`,
  `inspect`, `search`, `edit`, `node_create`, `parm_set` and `look`) for clients with a
  small context; the argument detail they leave out is in `hocuspocus://tools`.
  `compat_1x` serves the 35 tools of 1.4 unchanged, for scripts written against 1.4,
  during the 2.0.x releases.
- `result_content` decides where a result's JSON goes. The default `text` sends it once,
  in the text block, which is what Claude Code shows the model. Use `both` for a client
  that reads `structuredContent` or `outputSchema`, or `structured` for structured data
  with a one-line text summary.

The README lists every key.

## Troubleshooting

Run `hocuspocus doctor` first. Every `[FAIL]` line says what to do. These are the common
problems:

**`[FAIL] package JSON: ...\packages\hocuspocus.json missing; run hocuspocus install-houdini`**

The package was never installed, or it went into a different pref dir than the one
Houdini uses. Run `hocuspocus install-houdini` again and read its `Houdini pref dir:`
lines. If Houdini uses a custom `HOUDINI_USER_PREF_DIR`, set that variable in the shell
that runs the command too, or pass `--prefs`. `__HVER__` in it is expanded the way
Houdini expands it.

**`[warn] pref dirs disagree: HocusPocus ... is installed in A but not in B`**

Houdini on Windows uses `%HOME%\houdini22.0` when started with `HOME` set (Git Bash) and
`Documents\houdini22.0` when started from the Start menu. The warning names the command
that installs into both; run it and restart Houdini.

**Houdini not restarted: `[warn] live instances: none in ...\instances`**

The package is in place, but no running Houdini has loaded it. Restart Houdini, since
packages load only at startup. If Houdini is already running, open the **HocusPocus**
shelf and press **HP Status**. If the host is stopped, press **HP Start**. If the status
bar shows `HocusPocus autostart failed: ...`, the reason is in the host log under
`%LOCALAPPDATA%\HocusPocus\logs\`. Also check `hocuspocus.toml` for `autostart = false`.

**No instance: tool calls return `houdini_offline`**

The bridge works without Houdini, so `tools/list` still answers, but no live instance is
registered. Start Houdini, or let the agent call
`houdini_connect {"launch": {"mode": "gui"}}` (or `"headless"`). The bridge picks the
new instance up by itself, with no client restart. If several instances are running,
`houdini_status` lists them and `houdini_connect {"pid": N}` pins one.

**`ambiguous_instance` or `instance_lost`**

Several Houdinis are running and none is pinned (`ambiguous_instance`), or the pinned one
has exited (`instance_lost`). The error lists the live instances as `candidates`. Pin one
with `houdini_connect {"pid": N}`; `houdini_connect {}` goes back to automatic selection.

**`invalid_argument`: "node_info is a 1.4 tool that the 2.0 core profile does not serve"**

A script or prompt written for 1.4 called a tool that 2.0 replaced. The `hint` names the
replacement (`inspect {"what": "node"}` here); [`migration-2.0.md`](migration-2.0.md) lists
them all. To run the script unchanged, set `profile = "compat_1x"` in `hocuspocus.toml`
(both the bridge and Houdini read it) and restart Houdini.

**`invalid_argument`: "hda is a full-profile tool, and this Houdini's host runs the core profile"**

The bridge lists the `full` tools but the host in Houdini still runs `core`. Put
`profile = "full"` in `hocuspocus.toml`, which both read (or set `HOCUSPOCUS_PROFILE=full`
in Houdini's environment), and restart Houdini. If `HOUDINI_USER_PREF_DIR` contains
`__HVER__`, the file goes in the expanded directory (`houdini22.0`), not in a literal
`houdini__HVER__` one; `hocuspocus doctor` prints which file the bridge reads.

**Version mismatch: `[FAIL] host/bridge version: Houdini has X, bridge is Y`, or a `version_mismatch` error**

You upgraded the tool but Houdini still loads the old host. Run
`hocuspocus install-houdini`, which replaces older versions, and then restart Houdini.

**Headless look: `look` returns `ui_required`, or the first look takes seconds**

hython has no Scene Viewer, so `"source": "viewer"` needs the GUI. Leave `source` out:
`look` renders through a temporary Flipbook ROP (falling back to the OpenGL ROP, then
Karma, with a note) and, without `camera`, a temporary camera framed on the target, and
that works headless. Headless, the Flipbook ROP renders a snapshot of the scene in a child
hython (a viewport render after a deleted ROP, or a second OpenGL render, crashes hython
22.0.466). The first look starts it, about 3 s; later looks reuse it, about 0.4 s each
(0.9 s for a stage), until it has been idle for 2 minutes. Nothing is left in your scene.
`backend_used` names what drew the picture (`flipbook`, `opengl`, `karma`, `viewer` or
`rop_image`). For a flipbook of many frames, ask for a Flipbook ROP (`/out`, type
`flipbook`) and `render`: Houdini 22 deprecates the OpenGL ROP.

**Other errors.** Every tool error has a `code` and a `hint`. Agents normally act on the
hint themselves. The full list of codes is in [`BIBLE.md`](BIBLE.md) §9.
