# 15 — GUI session: working alongside a user in a live Houdini

**Seat:** an AI agent working as a Houdini FX TD. I used only the MCP tool surface, `docs/tools.md`, the README, the quickstart and reviews 09 and 12. I did not read the server source.
**Build:** `release/1.2` at `c812972`. The host was loaded by the dev-mode package (`houdini22.0/packages/hocuspocus.json` → checkout `src/`) and reported `host 1.1.0`. The bridge was installed into a scratch venv. Profile `full`: `HOCUSPOCUS_PROFILE=full` for the bridge, and a temporary `houdini22.0/hocuspocus.toml` (`profile = "full"`) for the host. That file did not exist before. I created it and removed it after the session.
**Host:** Houdini FX 22.0.466 GUI, pid **65108**, started with `hocuspocus launch --hip <scratch>/city/city_v02_destruction.hip --wait 240`. `HOCUSPOCUS_STATE_DIR` pointed at a private scratch state dir. Launch took about **40 s** to register, including loading the 1.47 MB hip. The host log reports it listening at 20:04:42 and stopped at 20:12:33, so the session lasted about 8 minutes.
**Client:** a one-shot `mcp.Client` over stdio (review 12's `hp.py`, extended with process wall time). For every call I logged tool, args bytes, result text bytes, isError, in-call seconds and wall seconds.
**Result:** I ran all seven workload steps. The session made **89 logged tool calls** with 62.3 KB of result text, plus 18 images. **12 calls returned isError.** Ten of those were deliberate probes or my own schema mistakes, and one was the close call. One more call never reached the tool: the bridge failed to import (§3.0). I used **6 `houdini_python` calls**: 5 were the simulated user edits and 1 closed Houdini, as the brief asked. **No agent work went through `houdini_python`.** The scene was saved as `<scratch>/g15/gui/city_v03_gui.hip` (1,450,918 bytes, `dirty: false`). The evidence image is `docs/redesign/evidence/city-destruction/50_gui_viewer.png`: `cam_district`, frame 72, 1024×768, palettised to 347 KB.

---

## 1. What I did

1. **Orientation.** `houdini_status` found the GUI instance, the hip and `HIP` = the hip's directory. Frame was 72 and the range 1–96. `network_describe {root:/obj, format:outline}` returned 72 nodes in 6.6 KB.
2. **Viewport captures, three ways.** I compared `source: viewer`, `source: opengl_rop, fit: all`, `camera: /obj/cam_district` with `auto` and with `opengl_rop`, and `source: viewer, fit: all`.
3. **A user working alongside.** Two agent edits (`parm_set` sun intensity; `node_create` a null `AGENT_REVIEW`), then four "manual" `houdini_python` edits with their own `undo_label`: rename `/obj/sky` → `sky_env`, move two nodes, change sun intensity and `cam_district` focal, delete `/obj/cam_street`. Because those are labelled `HocusPocus: houdini_python ...`, a fifth call only *scheduled* two edits via `hdefereval.executeDeferred` (rename `/obj/sun` → `sun_key`, change `/obj/cam_overview/focal`); they ran after the call returned, outside HocusPocus's undo group, and are indistinguishable from real user steps. Then `events`, `node_info`/`node_find`, `undo history`, undo/redo of an agent `node_edit`, and an undo across a user step.
4. **`selection`** set/get, then `viewport_capture fit: selected` (`auto` and `opengl_rop`).
5. **Playback.** `time {frame: 60}`, then `cam_district` captures at frames 1, 48, 96 through the ROP and the viewer.
6. **HDA round trip.** A SOP `subnet` `/obj/destruction/meteors` filled by `node_copy` of the six meteor nodes (display flag set inside, `geo_info` = 3 packed meteors); `hda create` (`hp::meteors`, "HP Meteors", 1.0, `<scratch>/g15/hda/meteors.hda`), `save`, `match`, `node_type_info`, `unlock`, `parm_set meteor_shape/freq 3`, `node_edit spare_parms` add `speed_scale`, `save`, `node_type_info`, `match`, `parm_get`, `hda list` (two pages of 5, then `library_path`), `node_type_search` ×2, plus `reload` and `install`.
7. **Deliberate errors**, then `problems`, `events`, `hip_save` and the close.

---

## 2. Measurements

### 2.1 Per tool (89 logged calls)

"in-call s" is the time spent inside `call_tool`. "wall s" is the whole one-shot process, including the bridge's start, which costs about 1.35 s per call.

| tool | calls | errors | args B avg | text B avg | text B total | avg in-call s | max s | avg wall s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| events | 6 | 0 | 8 | 4,072 | **24,433** | 0.01 | 0.0 | 1.43 |
| viewport_capture | 21 | 3 | 49 | 379 | 7,972 | 1.11 | 4.4 | 2.49 |
| network_describe | 1 | 0 | 34 | 6,613 | 6,613 | 0.03 | 0.0 | 1.23 |
| hda | 11 | 0 | 104 | 429 | 4,722 | 0.07 | 0.2 | 1.47 |
| node_info | 4 | 1 | 68 | 1,006 | 4,026 | 0.06 | 0.1 | 1.54 |
| undo | 7 | 0 | 21 | 265 | 1,861 | 0.04 | 0.1 | 1.53 |
| node_create | 5 | 3 | 80 | 306 | 1,533 | 0.04 | 0.1 | 1.45 |
| houdini_status | 2 | 0 | 2 | 706 | 1,413 | 0.80 | 1.6 | 2.49 |
| node_copy | 1 | 0 | 234 | 1,209 | 1,209 | 0.06 | 0.1 | 1.42 |
| node_edit | 3 | 0 | 124 | 373 | 1,121 | 0.08 | 0.1 | 1.60 |
| geo_info | 1 | 0 | 35 | 1,002 | 1,002 | 0.04 | 0.0 | 3.81 |
| hip_open | 2 | 2 | 101 | 465 | 931 | 0.06 | 0.1 | 1.67 |
| parm_set | 3 | 1 | 61 | 306 | 919 | 0.01 | 0.0 | 1.45 |
| node_type_info | 2 | 0 | 26 | 409 | 818 | 0.05 | 0.1 | 1.42 |
| houdini_python | 6 | 1 | 164 | 123 | 739 | 0.11 | 0.4 | 1.57 |
| problems | 1 | 0 | 15 | 629 | 629 | 0.06 | 0.1 | 1.47 |
| parm_get | 2 | 0 | 66 | 285 | 570 | 0.05 | 0.1 | 1.45 |
| node_find | 2 | 0 | 30 | 242 | 484 | 0.05 | 0.1 | 1.92 |
| hip_new | 1 | 1 | 2 | 396 | 396 | 0.06 | 0.1 | 1.97 |
| node_type_search | 2 | 0 | 29 | 186 | 372 | 0.14 | 0.2 | 1.52 |
| hip_save | 1 | 0 | 155 | 247 | 247 | 0.23 | 0.2 | 1.57 |
| time | 3 | 0 | 5 | 60 | 180 | 0.04 | 0.1 | 1.57 |
| selection | 2 | 0 | 20 | 41 | 82 | 0.04 | 0.1 | 1.40 |
| **total** | **89** | **12** | 63 | 700 | **62,272** | 0.32 | 4.4 | 1.79 |

- **Args:** 5,640 B in total.
- **Images:** 18 PNGs at 16.7 MB of base64 (about 930 KB each). The 1024×768 viewer and camera shots of the dense city are 1.0–1.15 MB each as PNG. The framed overview is 217–227 KB.
- **`events` took 39 % of all result text.** Two calls (7.3 KB and 16.4 KB) were mostly HDA-internal noise (§3.2).
- **In-call time was 28.8 s in total, and 21.6 s of it was captures.** Every non-capture call finished in ≤ 0.4 s.

### 2.2 Capture timing in the GUI (versus about 3 s per capture headless)

| capture | source_used | in-call s |
|---|---|---:|
| first viewer grab (cold) | viewer | **4.40** |
| later viewer grabs (f72, 1024×768) | viewer | 1.93, 1.70, 0.64 |
| `camera: cam_district`, `source: auto` | viewer | 2.84 |
| `camera: cam_district`, viewer, frames 1 / 48 / 96 | viewer | 1.44 / 1.32 / 1.24 |
| `opengl_rop`, `fit: all` | opengl_rop | **0.70** |
| `opengl_rop`, `cam_district` (f72, f72@960×540) | opengl_rop | 0.85, 0.88 |
| `opengl_rop`, `fit: selected` | opengl_rop | 0.79 |
| `opengl_rop`, `cam_district`, frames 1 / 48 / 96 | opengl_rop | 0.83 / 0.77 / 1.96 |
| viewer at 480×270 / through a light | viewer | 0.31–0.33 |

In the GUI, the OpenGL ROP path renders in-process and takes **0.7–2.0 s**. That is 1.5–4× faster than the 3 s child-hython path headless, and it is also faster than grabbing the viewer at full size. Frame 96 was the slowest at 1.96 s: it is the first visit to that frame, and the sim cache served it. `time` stayed at 60 after every `frame:` capture, so captures do not move the user's playbar.

### 2.3 `houdini_python` uses

| # | Purpose | Reason |
|---|---|---|
| 1–4 | rename sky, move 2 nodes, change sun and lens, delete `cam_street` | simulated user (brief) |
| 5 | schedule two deferred edits (rename sun, change `cam_overview` focal) | simulated user. This is the only way to create a genuinely *non*-HocusPocus undo step through MCP. |
| 6 | `hou.exit(suppress_save_prompt=True)` | the brief's close step. No tool quits Houdini. |

**The agent work used 0 `houdini_python` calls.** Two things would have needed it if I had insisted: homing the viewer (§3.1) and adding a parm to the HDA's *definition* interface (§3.4).

---

## 3. Friction log

### 3.0 Environment: the shared working tree broke the editable bridge
In the middle of the HDA step, the `hda match` call died before any request was sent. The bridge failed to import: `SyntaxError: unterminated string literal` at `src/hocuspocus/bridge/instructions.py` line 78. Another agent was editing the checkout's uncommitted working tree, and my venv had an *editable* install of it. I reinstalled the bridge non-editable from `git archive c812972` into scratch and carried on. The host was unaffected, because its modules had been imported at launch. This is not a product bug. It is a reason for evaluation seats to install from a commit snapshot instead of `-e`.

### 3.1 Viewport capture in the GUI
- **`source: viewer` shows the user's working context, not the scene.** When the hip opened, the viewer was not homed: the first grab showed the camera gizmos and one ground tile. Once it was pointed at the district, it showed the city with *ghosted* translucent towers and meteor. The ROP render of the same frame showed rubble. The saved network editor sat inside `/obj/city_gen`, so that object drew solid and `/obj/destruction` was ghosted as an "other object". Nothing in the result says so: `camera_used: "viewport"` and `fit_used: "none"` are all you get. After `selection {paths:[/obj/destruction/OUT_SIM]}`, the viewer showed the sim solid. Setting the selection evidently moved the user's network context as well, and the result did not mention that either.
- **The viewer cannot be homed.** `{"source":"viewer","fit":"all"}` returned `fit_used: "none"` with no note, and `fit: selected` under `auto` did the same. No tool homes or frames the viewer. The quickstart tells a *person* to press H. The workaround I found was a capture with `camera`, which leads to the next problem.
- **`camera` with `source: auto` or `viewer` permanently moves the user's viewer.** After `camera: /obj/cam_district`, the user's viewport stayed at the camera's view (badge "No cam", so it is a copy, not a lock). After `camera: /obj/sun_key` (a light, which the tool accepts), the user's viewer was left looking at empty sky. Nothing restores the previous view, and the result does not say the view changed. For a tool whose description says it "Leaves no nodes, undo step or dirty flag", this is the biggest GUI surprise of the session.
- **`opengl_rop` is the right agent default in a GUI:** fast, lit, framed, leaves the user's viewer alone, matches a render. `fit: all` framing is loose (the city fills the lower-middle third). Viewer grabs carry the HUD and this machine's "Indie Edition" watermark, which is why `50_gui_viewer.png` is the ROP shot through `cam_district`.

### 3.2 Events alongside a user
- `events {}` returned **nothing after the agent's own `parm_set` and `node_create`**. That is reasonable, since those nodes were not yet watched.
- After the four manual edits, `events` reported the sun intensity change (as three `ParmTupleChanged`: `l_dimmer`, `dimmer`, `light_intensity`) and `ChildDeleted /obj/cam_street`. It did **not** report the rename of `/obj/sky`, the `cam_district` focal change (although the agent had captured through that camera), or the node moves. The description promises "parms changed on nodes HocusPocus touched", so this is by design. In practice, though, an agent working alongside a user learns about a rename only when its next call fails. The deferred user rename of `/obj/sun` (a touched node) *was* reported, as `NameChanged` with `old_name`. The `cam_overview` focal change was not.
- **After the HDA step, `events` flooded.** `since: 5` returned 50 events and `more: true` in 7.3 KB. `since: 55, limit: 200` returned 104 more in 16.4 KB. Of the 177 events, about 150 were `ChildDeleted`/`BeingDeleted` of *internal* nodes of locked HDAs: `cfg_meteor/__dopnet`, `.../color_pinned`, `meteor_name/...` and so on, emitted when `hda create`/`match` rebuilt the subnet's contents. There were also a `ChildCreated`/`ChildDeleted` pair for a transient `/obj/geo1`, and five `FlagChanged` events on `AGENT_REVIEW` with no detail saying which flag. Events carry no origin, so the agent's own `node_copy` creations look the same as user edits.
- `node_not_found` on the stale path is excellent. `node_info /obj/sky` → `candidates: ["/obj/sky_env"]`. `node_find pattern: sky*` found it as well. `node_info` reflected the moves, the new focal length and the sun intensity correctly.

### 3.3 Undo alongside a user
- `undo history` interleaves correctly: `"Change Parameter focal", "Rename Node sun -> sun_key", "HocusPocus: houdini_python manual: delete cam_street", ..., "HocusPocus: node_create 1 node", "HocusPocus: parm_set 1 parm"`. The `note` explains the prefix, and captures add no undo steps.
- Undoing the agent's most recent `node_edit` worked. `performed`, `next_undo` and `next_redo` are clear, and `node_info` confirmed the comment went and came back with `redo`.
- **`undo {steps: 2}` silently undid the user's `Change Parameter focal`** along with the agent step. There was no warning and no flag in the result apart from the label in `performed`. In a shared session, "undo my last action" is unsafe once the user has touched anything since.
- `undo_label` on `houdini_python` is honoured as `HocusPocus: houdini_python <label>`. That is good for auditing, but it means `houdini_python` cannot imitate a user step. I needed the deferred trick to test real interleaving.

### 3.4 HDA round trip
- No tool collapses nodes into a subnet; `node_copy` into a new subnet kept the wiring (1.2 KB) and I set the inner display flag myself.
- `hda create` (0.25 s) explains the unlocked state in a `note`. `save`, `match`, `unlock`, `reload` and `install` all worked, and `freq: 3` persisted into the definition.
- **The spare parm did not reach the definition.** `node_edit spare_parms add speed_scale` on the unlocked HDA instance succeeded, and `hda save` reported `saved: true`. `node_type_info` still showed `"parms": {}`, and after `match` the parm survived only as an instance spare. There is no way to build an HDA's parameter interface through the typed tools.
- **Version metadata is inconsistent.** `create {version:"1.0"}` returns `version: "1.0"`, and `hda list library_path` shows `"version":"1.0"`. `node_type_info` and `node_type_search` show `version: ""` and `description: ""`, although the docs say `description` is the same as `label`. `node_type_info` reports `"type":"hp::Sop/meteors"`, which is Houdini's spelling but unlike every other type string the tools return.
- `matches_definition: false` right after `hda save` (unlocked instance) reads as "save failed". `hda list` puts the user library first and pages correctly, but shows built-ins as 8.3 short paths (`C:/PROGRA~1/SIDEEF~1/...`). `node_type_search "meteors"` found the type at once (186 B).

### 3.5 Deliberate errors
| Call | Exact message (abridged) | Hint helped? |
|---|---|---|
| `hip_new {}` dirty | `unsaved_changes`: "The scene ...city_v02_destruction.hip has unsaved changes; refusing to clear it." Hint: "Pass on_unsaved: 'save' ..., 'discard' ..., or call hip_save" | Yes |
| `hip_open` typo in an empty dir | `file_not_found`, hint "No similar hip files in <dir>." | Yes (accurate) |
| `hip_open $HIP/city_v02_destruction_v3.hip` | `file_not_found`, candidates `city_v02_destruction.hip`, `city_v01.hip` | Yes |
| `node_create` `rbdbulletsolver` in `/obj` | "rbdbulletsolver is a Sop node type, but /obj holds Object nodes. Create a geo object first and put SOPs inside it." `rolled_back: true` | Yes |
| `node_create` `camera` in `/obj` | "camera is a Cop/Lop/Sop node type ... Create a geo object first and put SOPs inside it." candidates `cam, vrcam, ...` | Candidates yes. The hint text points the wrong way. |
| `viewport_capture camera:/obj/cam_distrct` | `node_not_found`, candidates `/obj/cam_district, /obj/destruction, /obj/cam_overview` | Yes |
| `viewport_capture camera:/obj/destruction` | `invalid_argument`: "/obj/destruction (geo) is not a camera." Hint: "Pass an OBJ camera such as /obj/cam1, or omit camera" | Partly. It does not list the scene's two cameras. |
| `viewport_capture camera:/obj/sun_key` (a light) | **no error**; the viewer now looks through the light | — |
| my `parm_set {node, parms}` | `invalid_argument`: "items: required property is missing; node: unknown property ..." | Partly. The generic hint names `inputSchema` but gives no example. |
| my `node_create {parent, items[{input}]}` | "parent: unknown property; did you mean partial?; ... input: unknown property; did you mean inputs?" | Yes for `inputs`. "did you mean partial?" for `parent` is noise. |
| `houdini_python hou.exit(...)` | `python_exception` "SystemExit: 0", hint "Do not call exit() or sys.exit()...", `rolled_back: true` | No. Houdini did exit, and `houdini_status` next showed `connected: null`, `instances: []`. The expected `houdini_offline` never came. |

### 3.6 GUI responsiveness
I had no view of the desktop from this seat, so these notes come from latency and behaviour. Every non-capture call returned in ≤ 0.4 s inside the host. The longest main-thread call was the first cold viewer grab at 4.4 s. The heavy scene (1,354 RBD pieces plus 191 buildings) never needed a job, no call hit a timeout, and the host answered every one of the 89 calls. No call left a modal dialog. `hip_save` of the 1.45 MB hip took 0.23 s.

---

## 4. What worked well
- **`hocuspocus launch` for a GUI**: one command, a private `HOCUSPOCUS_STATE_DIR` hid other agents' instances, `houdini_status` auto-selected it, and `HIP` was the hip's directory.
- **GUI OpenGL ROP capture**: about 0.8 s, lit and side-effect free; frames 1/48/96 in under 4 s of tool time.
- **Stale-path recovery**: `node_not_found` and `hip_open` candidates found the user-renamed node and the real file.
- **Undo labels and history** mix agent and user steps faithfully; `undo`/`redo` report `performed` and `next_*`.
- **The HDA lifecycle** ran end to end in 11 small calls (avg 429 B).
- **Byte discipline outside `events`**: median result about 360 B.

---

## 5. Top 10 papercuts

| # | Pri | Tool | Argument | What happens (exact) | Proposed change |
|---|---|---|---|---|---|
| 1 | **P0** | `viewport_capture` | `camera` with `source: auto`/`viewer` in a GUI | The user's Scene Viewer is left at the camera's view, or at a light's view (empty sky for `/obj/sun_key`). The result says only `"source_used":"viewer","camera_used":"/obj/sun_key"`. | Save and restore the viewport camera around the grab. Or, when `camera` is given, make `auto` use `opengl_rop` (it is faster in the GUI anyway). Add `notes: ["viewer view changed"]` if it is ever left changed. Reject non-camera lights unless `allow_light: true`. |
| 2 | **P1** | `events` | `since` after `hda create`/`match` | 177 events. About 150 are `ChildDeleted .../cfg_meteor/__dopnet` and similar from locked-HDA internals: 23.7 KB, 39 % of the session's text. | Suppress events under locked HDAs and collapse them into one `{kind: "hda_contents_rebuilt", path}`. Name the flag in `FlagChanged`. Add `origin: "hocuspocus"|"user"`. |
| 3 | **P1** | `events` | watch scope | Renaming the untouched `/obj/sky`, the focal changes on cameras the agent captured through, and node moves are not reported. The agent finds out only when a call fails. | Watch name, child and parm changes for every node the agent has *read* or captured through, plus `NameChanged` for all children of networks it has described. Document the scope in the description. |
| 4 | **P1** | `undo` | `action: undo, steps: 2` | It undid `HocusPocus: node_edit 1 node` **and** the user's `Change Parameter focal` without warning. | By default, stop at the first non-`HocusPocus:` step: `code: user_step_in_range`, hint "pass include_user_steps: true". Return `crossed_user_steps: [...]`. |
| 5 | **P1** | `viewport_capture` | `source: viewer` + `fit: all`/`selected` | `"fit_used":"none"` with no note. No tool can home the viewer. | Implement fit on the viewer (frame all or selected, then restore), or add a note `fit is ignored for the viewer; use source opengl_rop`. With an explicit `fit`, `auto` should pick `opengl_rop`. |
| 6 | **P1** | `hda` | `save` after `node_edit spare_parms` on the instance | `saved: true`, but `node_type_info` → `"parms": {}`. The parm stays an instance spare. | Add `hda save {promote_spare_parms: true}` (default true), or `node_edit spare_parms {target: "definition"}`. Warn when adding spare parms to an HDA instance. |
| 7 | **P1** | `viewport_capture` / `selection` | `source: viewer`; `selection paths:[SOP]` | The viewer showed the user's network context (inside `/obj/city_gen`, with `/obj/destruction` ghosted), so it looked nothing like the ROP render. Selecting `/obj/destruction/OUT_SIM` changed that context, with no mention in either result. | Return `viewer: {context, camera, ghosting}` in `notes`. Make `selection` report `context_changed` (or leave the network editor's pwd alone unless asked). |
| 8 | **P2** | `hda` / `node_type_info` / `node_type_search` | `create version: "1.0"` | `hda list` → `"version":"1.0"`. `node_type_info` → `"version":""`, `"description":""`, `"type":"hp::Sop/meteors"`. | Report the definition's version everywhere. Set `description` from `label` as documented. Use the `Sop/hp::meteors` spelling. |
| 9 | **P2** | `houdini_python` | `hou.exit(suppress_save_prompt=True)` | `python_exception "SystemExit: 0"`, hint "Do not call exit() or sys.exit()", `rolled_back: true`, while Houdini actually quits. | Add a typed quit (`houdini_connect {quit: true, on_unsaved}`). Until then, detect `hou.exit` and return `{exiting: true}`. |
| 10 | **P2** | `viewport_capture` / `node_create` errors | `camera: /obj/destruction`; `type: camera` in `/obj` | "is not a camera ... such as /obj/cam1" without listing the scene's cameras. "camera is a Cop/Lop/Sop node type ... Create a geo object first and put SOPs inside it" when the right answer is `cam`. | Put the scene's cameras in `candidates`. When an Object-level candidate exists, the hint should say "did you mean cam?" instead of suggesting a geo container. |

**Honourable mentions:**
- `also_written` PNGs are still RGBA with a transparent background (review 12 leftover).
- `network_describe outline` expands every camera's `camOrigin`/`file1`/`xform1` (9 of 72 rows) and still has no wiring or flags.
- `hda list` shows 8.3 short paths for built-ins and has no `builtin: false` filter.
- `hda install` on an already-installed library says `"installed"`.
- `parm_set` still returns `raw: "2.5"` next to `value: 2.5`.
- `node_info` on lights lists ramp keys and `s`/`scale` as non-default (review 09 §5.5).
- The schema-violation hint for `parm_set` gives no example, and "did you mean partial?" for `parent` is noise.
