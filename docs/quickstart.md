# Quickstart

This guide takes about five minutes. You start with nothing installed and finish with a
box sitting on a mountain, plus a screenshot your agent has looked at. The commands are
shown for Windows (PowerShell or Git Bash). On Linux, the paths differ but the commands
are the same.

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
hocuspocus 1.2.1 (hp/v1, mcp 2.3.x, Python 3.12.x)
```

## 2. Install the Houdini package (1 minute)

```text
$ hocuspocus install-houdini
Houdini pref dir: C:\Users\you\Documents\houdini22.0 (from hython (C:\Program Files\Side Effects Software\Houdini 22.0.466), default location)
copied hocuspocus 1.2.1 to C:\Users\you\Documents\houdini22.0\hocuspocus\1.2.1\python\hocuspocus
copied the Houdini payload to C:\Users\you\Documents\houdini22.0\hocuspocus\1.2.1\houdini
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
hocuspocus 1.2.1 (bridge, hp/v1)
[ok]   Houdini install: C:\Program Files\Side Effects Software\Houdini 22.0.466
[ok]   Houdini version: 22.0.466
[ok]   pref dir: C:\Users\you\Documents\houdini22.0 (from hython (...), default location): package JSON -> C:\Users\you\Documents\houdini22.0\hocuspocus\1.2.1\python (1.2.1)
[ok]   hocuspocus.toml: none (defaults)
[ok]   package JSON: C:\Users\you\Documents\houdini22.0\packages\hocuspocus.json -> C:\Users\you\Documents\houdini22.0\hocuspocus\1.2.1\python
[ok]   host/bridge version: 1.2.1
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

> Put a box on top of a mountain in /obj, then show me a screenshot.

Expect a sequence close to this one:

1. `houdini_status`. Finds your Houdini, its pid and that the hip file is `untitled.hip`.
2. `node_create` with a batch of items: a `geo` node `/obj/scene`, a `grid` with more
   rows and columns, a `mountain` wired to it, a `box`, and a `merge` (or a `transform`)
   that lifts the box above the terrain, with the display flag on the last node. All of
   this is one call and one undo step.
3. `cook` on the display node. It returns `ok: true` and empty `errors`. If something is
   red, the agent reads `errors` and fixes it with `parm_set` or `node_connect`.
4. `geo_info` on the display node. Gives point counts and a bounding box, so the agent
   can check that the box sits above the terrain.
5. `viewport_capture`. Returns a PNG that the agent can see, plus the file path under
   `%LOCALAPPDATA%\HocusPocus\captures\`. In the GUI, without `camera` or `fit`, it
   captures the Scene Viewer as it is, so if the picture shows an empty grid, ask for
   `"fit": "all"` (it frames the grab and then puts your view back) or for
   `"source": "opengl_rop"`, which frames the scene with a temporary camera.

To give a network control parms, ask for them: the agent adds spare parms to a `null`
with `node_edit` `spare_parms` and links other parms with `ch()`. A `menu` spare parm is
a string menu by default (VEX reads the token with `chs()`); with `value_type: "int"` it
is an int parm whose value is the item index (`ch()` or `chi()`).

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

These tools need the `full` profile (see [Configuration](#configuration)):

- **Look at a USD stage.** `viewport_capture {"lop_path": "/stage/OUT"}` renders the
  stage through an OpenGL ROP, framed on it. `camera` also takes a LOP camera node or a
  camera prim path. `usd_stage {"lop_path": "/stage/OUT", "summary": true}` returns the
  prim count, the counts by type and the world bounding box in one small result. On LOP
  nodes, the parm tools accept USD attribute names such as `inputs:intensity`.
- **See why PDG work failed.** A failed work item in `pdg {"action": "workitems"}`
  carries `error` (the last error lines of its log), `log_path` and `exit_code`, and
  `"state": "failed"` lists only the failed items. A cook result lists the first five
  `failures`, and `problems` reports the TOP node. Graphs with ROP Fetch load the saved
  hip, so `pdg cook` refuses unsaved changes: run `hip_save` first, or pass
  `"save": true`.
- **Work next to a user.** Every `events` entry says `origin: agent` or `other`. `undo`
  stops before a step the user made unless you pass `include_user_steps: true`.

## Caches, Copernicus and two Houdinis

These work in the default `core` profile:

- **Write a sim cache.** `cook` never writes files: cooking a File Cache passes the
  geometry through, and the result says so. To write the cache, `render` the File Cache
  SOP: `render {"rop_path": "/obj/pyro/cache", "wait_s": 0}` returns a `job_id` at once,
  writes the node's own frame range with per-frame progress, and turns on Load from Disk
  when it is done, as the Save to Disk button would. `job {"action": "cancel"}` stops it
  and keeps the frames already written. `geo_info` and `geo_read` take `frame` to inspect
  the cache without moving the playbar, and `houdini_status` reports Houdini's memory.
- **Look at a Copernicus image.** COP networks live in `/img` (`node_create {"parent":
  "/img", "type": "copnet"}`), and their nodes are category `Cop`.
  `viewport_capture {"cop_path": "/img/copnet1/blend1"}` returns that node's image in
  about 0.2 s, and `geo_info` on a Cop node returns its resolution and per-channel
  min/max/mean. To write the image to disk, `render` a `rop_image` wired to the node. A
  SOP reads a COP live through an `op:` path, for example `attribfrommap` with
  `filename: "op:/img/copnet1/blend1"`.
- **Drive two Houdinis.** Keep the GUI for editing and start a worker for renders with
  `hocuspocus launch --headless`. With two running, ask the agent to pin one:
  `houdini_connect {"pid": 3084, "name": "editor"}`, and later `{"name": "editor"}`.
  Until one is pinned, calls that change a scene refuse with `ambiguous_instance`, and
  reads go to the GUI. The usual hand-off is `hip_save` in the GUI, then pin the worker,
  `hip_open` the saved hip and `render {"wait_s": 0}`, then pin the GUI again. The job id
  (`61900-9c3e6f7ca53e`) carries the worker's pid, so `job` reaches the worker whichever
  Houdini is pinned, and `job {"action": "list", "all": true}` lists every Houdini's jobs.
  If the pinned Houdini exits, every call returns `instance_lost` until you pin another;
  the bridge never switches on its own. The `hocuspocus://guide` resource has this
  recipe, and `hocuspocus://tools` has every tool's notes.

## Configuration

Nothing needs configuring for this guide. Two settings in
`$HOUDINI_USER_PREF_DIR/hocuspocus.toml` (or `HOCUSPOCUS_*` environment variables, which
win) matter most for scripts and other clients:

```toml
profile = "full"            # list and allow hda, usd_stage, pdg and events (default "core"; "minimal" lists 14 tools)
result_content = "both"     # also send structuredContent (default "text")
```

- `profile` is read by the bridge, which lists the tools, and by the host inside Houdini,
  which refuses the tools outside its profile. Restart Houdini after changing it.
  `minimal` lists 14 tools (status, connect, hip open and save, the main node and parm
  tools, `cook`, `geo_info`, `viewport_capture` and `houdini_python`) for clients with a
  small context; the argument detail they leave out is in `hocuspocus://tools`.
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

**`invalid_argument`: "hda is a full-profile tool, and this Houdini's host runs the core profile"**

The bridge lists the `full` tools but the host in Houdini still runs `core`. Put
`profile = "full"` in `hocuspocus.toml`, which both read (or set `HOCUSPOCUS_PROFILE=full`
in Houdini's environment), and restart Houdini. If `HOUDINI_USER_PREF_DIR` contains
`__HVER__`, the file goes in the expanded directory (`houdini22.0`), not in a literal
`houdini__HVER__` one; `hocuspocus doctor` prints which file the bridge reads.

**Version mismatch: `[FAIL] host/bridge version: Houdini has X, bridge is Y`, or a `version_mismatch` error**

You upgraded the tool but Houdini still loads the old host. Run
`hocuspocus install-houdini`, which replaces older versions, and then restart Houdini.

**Headless capture: `viewport_capture` returns `ui_required`, or each capture takes seconds**

hython has no scene viewer, so `source: "viewer"` needs the GUI. Use the default
`source: "auto"` or `"opengl_rop"`. These render through a temporary OpenGL ROP and,
without `camera`, a temporary camera framed on the scene, and they work headless.
Headless, each capture renders in a short-lived child hython (a second OpenGL render in
one hython process crashes Houdini 22.0.466), so every capture takes about 3 s. Nothing
is left in your scene.

**Other errors.** Every tool error has a `code` and a `hint`. Agents normally act on the
hint themselves. The full list of codes is in [`BIBLE.md`](BIBLE.md) §9.
