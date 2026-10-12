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
hocuspocus 1.1.0 (hp/v1, mcp 2.3.x, Python 3.12.x)
```

## 2. Install the Houdini package (1 minute)

```text
$ hocuspocus install-houdini
Houdini pref dir: C:\Users\you\houdini22.0 (from hython (C:\Program Files\Side Effects Software\Houdini 22.0.466))
copied hocuspocus 1.1.0 to C:\Users\you\houdini22.0\hocuspocus\1.0.0\python\hocuspocus
copied the Houdini payload to C:\Users\you\houdini22.0\hocuspocus\1.0.0\houdini
wrote C:\Users\you\houdini22.0\packages\hocuspocus.json (template: ...\houdini\hocuspocus.json.template)
recorded the pref dir in C:\Users\you\AppData\Local\HocusPocus\install.json (the bridge reads hocuspocus.toml from there)
Restart Houdini to load HocusPocus.
Then register the MCP server with your client, e.g.: claude mcp add -s user hocuspocus -- hocuspocus-mcp
```

The first line tells you which pref dir it chose and why. Depending on how Houdini was
set up, hython may report `C:\Users\you\houdini22.0` or
`C:\Users\you\Documents\houdini22.0`; whatever it reports is the one Houdini uses. The
search order is:

1. `--prefs`.
2. `$HOUDINI_USER_PREF_DIR`.
3. What `hython` reports for `hou.homeHoudiniDirectory()`. Asking hython takes a few
   seconds.
4. The platform default.

If the first line shows the wrong directory, run the command again with
`--prefs <dir>`. If several Houdinis are installed, `--hfs <install dir>` chooses which
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
hocuspocus 1.1.0 (bridge, hp/v1)
[ok]   Houdini install: C:\Program Files\Side Effects Software\Houdini 22.0.466
[ok]   Houdini version: 22.0.466
[ok]   Houdini pref dir: C:\Users\you\houdini22.0 (from hython (...))
[ok]   hocuspocus.toml: none (defaults)
[ok]   package JSON: C:\Users\you\houdini22.0\packages\hocuspocus.json -> C:\Users\you\houdini22.0\hocuspocus\1.0.0\python
[ok]   host/bridge version: 1.1.0
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
   `%LOCALAPPDATA%\HocusPocus\captures\`. In the GUI it captures the Scene Viewer as it
   is, without framing, so if the picture shows an empty grid, home the view (press H
   over the viewer) or ask for `"source": "opengl_rop"`, which frames the
   scene with a temporary camera.

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
(default 90) for the host to register, prints its registry entry and exits. Each session
then attaches with `houdini_connect {"pid": 23310}` (or automatically, when it is the only
Houdini running), and `hip_save` keeps the work between sessions.

## Configuration

Nothing needs configuring for this guide. Two settings in
`$HOUDINI_USER_PREF_DIR/hocuspocus.toml` (or `HOCUSPOCUS_*` environment variables, which
win) matter most for scripts and other clients:

```toml
profile = "full"            # list and allow hda, usd_stage, pdg and events (default "core")
result_content = "both"     # also send structuredContent (default "text")
```

- `profile` is read by the bridge, which lists the tools, and by the host inside Houdini,
  which refuses the four `full` tools on `core`. Restart Houdini after changing it.
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
Houdini uses. Run `hocuspocus install-houdini` again and read its first line. If Houdini
uses a custom `HOUDINI_USER_PREF_DIR`, set that variable in the shell that runs the
command too, or pass `--prefs`. A `HOUDINI_USER_PREF_DIR` that contains `__HVER__` is
skipped, and hython is asked instead.

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
`houdini_status` lists them and `houdini_connect {"pid": N}` selects one.

**`invalid_argument`: "hda is a full-profile tool, and this Houdini's host runs the core profile"**

The bridge lists the `full` tools but the host in Houdini still runs `core`. Put
`profile = "full"` in `hocuspocus.toml`, which both read (or set `HOCUSPOCUS_PROFILE=full`
in Houdini's environment), and restart Houdini.

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
