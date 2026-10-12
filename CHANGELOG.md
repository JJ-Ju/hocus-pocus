# Changelog

This project uses [Semantic Versioning](https://semver.org/). The 0.9 compatibility
policy does not apply to 1.0.

## 1.1.0 (2026-10-12)

1.1 acts on the post-1.0 code review and ergonomics review (`docs/redesign/review/10`,
`11`; plan in `docs/redesign/plan-1.1.md`). Results are smaller by default, a few
ambiguous fields and error shapes are settled, long cooks report progress, and
`hocuspocus launch` starts a Houdini that no MCP client owns. Some result shapes change,
so read **Upgrading from 1.0** if you have agent prompts or scripts written against 1.0.
Each contract change is recorded in `docs/BIBLE.md` (decisions D16 to D20).

### Contract changes

- **Summary results by default.** `node_create`, `node_copy` and `network_build` default
  to `return: "summary"`: per node `path`, `type`, `errors`, `warnings` and `cook_state`,
  with a repeated error list shortened to `errors_same_as`. `return: "full"` gives the
  1.0 blocks, but `node_create` now lists only the parms the call set (values a node's
  creation script set, such as a light's ramps, are no longer reported as edits) and
  elides strings over 200 characters as `{elided, head}`.
- **`locked` vs `hda_locked`.** `locked` is always a lock flag: the SOP hard-lock
  (`node_info` flags) or the parm lock (`parm_get`). Being a locked asset or inside one
  is `hda_locked`, in `node_info`, `network_describe` (locked children appear as
  `{type, hda_locked: true}`), `parm_get` and `hda`.
- **`node_type_search current_only`** defaults to true: every version of a type folds
  into its current version's row, which names the rest in `other_versions`.
  Descriptions are clipped to 120 characters. `current_only: false` lists each version.
- **`render` output lists.** Above 5 outputs only `outputs_summary`
  (`{count, first, last, pattern, missing_count}`) is inline; `job result` returns the
  full list. Without `wait_s` the call now waits `job_threshold_s` (default 10 s)
  instead of a fixed 20 s.
- **`houdini_python` exceptions are errors.** An uncaught exception (`SyntaxError` and
  `SystemExit` included) is an `isError` result with the new code `python_exception`:
  the message is `<type>: <text>`, `detail` carries `stdout`, `stderr`, `traceback` and
  `rolled_back`, and the code's scene changes are undone. In 1.0 this was a successful
  result with `ok: false`.
- **Results are sent once, as text.** The bridge setting `result_content` (toml key or
  `HOCUSPOCUS_RESULT_CONTENT`) defaults to `text`: compact JSON in the text block only,
  no `structuredContent`, and no `outputSchema` in `tools/list`. `both` is the 1.0
  shape; `structured` puts the data in `structuredContent` and a one-line summary in the
  text block. Errors follow the same setting; images are image blocks in every mode.
- **The host enforces `profile`.** A host running the `core` profile refuses `hda`,
  `usd_stage`, `pdg` and `events` with `invalid_argument` and a hint to set
  `profile = "full"`. In 1.0 only the bridge's tool listing depended on it.
- **One batch error shape.** `node_create`, `node_edit`, `node_connect` and `parm_set`
  errors (and each failed row's `error` with `partial`) read `items[i] (<path>): ...`
  with `detail: {item, path, rolled_back}`. `rolled_back` is true only when every change
  was actually undone; `parm_set` now restores earlier items itself.

### Added

- `cook {profile: true}` force-cooks the input chain in dependency order, one
  main-thread step per node, and returns the costliest ten as `chain` with
  `chain_total` and `total_ms`. A forced cook under 1 ms on a node with inputs hints at
  `profile`.
- `cook {frame_range: [start, end, step]}` cooks one frame per main-thread step (a sim
  advances, the GUI stays responsive, the current frame is restored) with progress and
  `message: "frame n/N"`; `summary: "bbox"` adds per-frame point and prim counts and
  bounding boxes.
- MCP progress notifications: when a client sends a `progressToken`, the bridge polls the
  jobs the call started (new host route `GET /hp/v1/calls/{request_id}/jobs`) every
  0.5 s and sends `notifications/progress`. Polling never fails the call.
- Job snapshots carry `current`, `total` and `message` next to `progress` (0..1);
  `cook` and `pdg` (finished work items) fill them.
- `node_edit` `spare_parms: {add: [...], remove: [...]}` adds float, int, string,
  toggle, menu, button, vector and color spare parms (label, default, size, range, menu
  items, folder, help) or removes spare parms, with rollback. `parm_not_found` on a
  `null`, `subnet` or `geo` points at it.
- `node_create` pairs a new `block_end` with its `block_begin` (the nearest one upstream,
  else the only unpaired one in the network) as the Tab menu does; the row carries
  `paired_with`.
- `network_describe {format: "outline"}`: a compact tree of path, name, type,
  `children_count`, display node, error count and `hda_locked`, two levels deep by
  default and paged at the response budget. The resource `houdini://outline` returns it
  for the whole scene.
- `hocuspocus launch [--headless] [--hip FILE] [--wait N] [--hfs DIR]` starts GUI
  Houdini or a headless hython host, waits for it to register, prints its registry entry
  as JSON (never the token) and exits. That Houdini belongs to no MCP server and outlives
  every client; attach with `houdini_connect {pid}`.
- `houdini_python` has a deadline: a `sys.settrace` hook stops Python code shortly
  before `timeout_s`, reported as `houdini_busy` with `detail.started` and `stopped`
  true, so `while True:` no longer wedges Houdini. A single long C call (a cook,
  `time.sleep`) still cannot be interrupted.
- `render` `notes` warn when the scene has no lights and when the thumbnail is nearly
  black. `node_type_not_found` candidates lead with known other names (`distantlight` is
  `hlight` in /obj).

### Fixed

From the code review (`docs/redesign/review/10-code-review.md`):

- Stale registry entries on pid or port reuse: an entry whose pid is alive but whose
  port refuses, rejects the token or answers `/health` with another pid is deleted, and
  the bridge selects again (`houdini_status`, `houdini_connect`, forwarded calls,
  `doctor`).
- Executor timeout race: work that finishes between the wait timing out and taking the
  lock returns its result instead of "still running".
- Host HTTP: idle connections time out after 60 s, and a non-loopback `Host` header is
  refused with 403 (DNS rebinding).
- Argument validator: `enum` and `const` compare JSON values (`true` is not `1`), and
  integral floats such as `50.0` are coerced to int where the schema says integer.
- Undo: labels are ASCII and at most 100 characters, and `rolled_back` reports whether
  the undo actually ran.
- Install and uninstall: `install-houdini --dev` removes earlier copied installs and
  `doctor` flags leftovers; `uninstall-houdini` reports a locked install instead of a
  traceback; the package JSON and install record are written atomically. A launch
  resolves a relative hip before starting Houdini, and a headless launch accepts only
  its own pid.
- `parm_set` and `parm_get` take an int menu parm's `menu_token` from its menu items
  rather than reporting its index.
- `geo_read` reads a page's rows on their own instead of building whole attribute
  columns (below a quarter of the class, without `stats`).
- `pdg` uses the dispatcher's timeout and the shared read-only refusal.
- Duplicated helpers are shared through `host/tools/_common.py`, the host and bridge
  response truncators are one module (`tools/budget.py`), and dead code is removed.
- Tests: the e2e bridges no longer read the user's real pref dir, and the executor
  timeout test no longer races the pump.

### Upgrading from 1.0

An agent prompt or script written for 1.0 must change:

- Pass `return: "full"` to `node_create`, `node_copy` or `network_build` where it read
  the 1.0 per-node echoes (flags, parms) from the result.
- Read `hda_locked`, not `locked`, to tell whether a node is or is inside a locked
  asset; in `parm_get`, `locked` is now only the parm lock.
- Expect `houdini_python` failures as `isError` results with `code: python_exception`
  (traceback in `detail.traceback`) instead of a successful result with `ok: false`.
- Pass `current_only: false` to `node_type_search` to get each version as its own row.
- Read `outputs_summary` (or `job result`) from a `render` with more than 5 outputs.
- Set `result_content = "both"` (or `HOCUSPOCUS_RESULT_CONTENT=both`) if a client reads
  `structuredContent` or relies on `outputSchema`.
- Set `profile = "full"` for the host as well as the bridge (in `hocuspocus.toml`, which
  both read, or in Houdini's environment) to use `pdg`, `hda`, `usd_stage` and `events`.
- Start the Houdini a one-shot script drives with `hocuspocus launch` rather than
  `houdini_connect {launch}`, which ends with the script's bridge.

## 1.0.0 (2026-10-12)

Merged to `master` in PR #7 on 2026-10-12 and tagged `v1.0.0` after the post-merge review.

### Summary

- A stdio MCP bridge (`hocuspocus-mcp`, official `mcp` SDK) outside Houdini and a
  stdlib-only host inside Houdini (GUI or `hython`), talking `hp/v1` over loopback HTTP
  with a token per instance.
- 35 tools in Houdini vocabulary, 31 in the default `core` profile, each mutating call
  one undo group, errors with a stable `code`, `hint` and `candidates`.
- Three-command install: `uv tool install -e .` (from a checkout; not on PyPI yet),
  `hocuspocus install-houdini [--dev]`, `claude mcp add -s user hocuspocus --
  hocuspocus-mcp`; `hocuspocus doctor` checks the result.
- Tested in three tiers: unit (system Python), integration (inside hython) and e2e
  (stdio bridge driving a hython host), plus a manual GUI smoke and three agent
  evaluations (`docs/redesign/review/07`–`09`).
- The 0.9 tree is removed and preserved at the git tag **`v0.9-archive`**.

### Post-merge review fixes (included in 1.0.0)

Two code reviews and an ergonomics review (`docs/redesign/review/10`, `11`) ran after the
merge; the fixes landed before tagging:

- `houdini_python` survives `sys.exit()`/`KeyboardInterrupt` and reports them; results carry `ok`.
- `pdg cook` never holds the main thread past its timeout (always a job); `pdg` respects `read_only`.
- `render` checks every output path against `approved_roots`; always returns `state`.
- Headless capture child sets fps before loading, carries hscript globals and `hou.session`.
- `viewport_capture` waits for the child off the main thread; `problems` has a time budget and cursor.
- `geo_info`/`geo_read` refresh stale node errors like `cook` does.
- `node_type_info` reports all outputs of multi-output HDAs, mutes its probe node, adds `parms` filter and `detail: folders`.
- `hip_merge`/`network_build` `dry_run` no longer dirty the scene; `approved_roots` expand `$VAR`/`~` and compare real paths.
- `node_find` refuses a locked-asset root, pages by path cursor; `node_info` lists multiparm counts and `hda_locked`.
- `node_create`/`node_copy`/`network_build` accept `return: summary`; long code strings are truncated in results.
- Launch lifetime is visible: `launched.outlives_server`, `launched_by` in the registry, and a named hint when a launched Houdini is gone.
- Headless launch never puts a site-packages dir on hython's `PYTHONPATH`.
- The bridge sends `max_response_bytes` to the host; paged results keep correct cursors.
- Registry writes retry on Windows share violations; stale pruning only on a provably dead pid.
- CLI snippets use `claude mcp add -s user`; budget test measures the real `tools/list` (44 KB cap).

### Known limitations

- **Launch lifetime.** A Houdini started by `houdini_connect {launch}` exits when the
  bridge that launched it exits (end of a client session, or a one-shot script). Save
  with `hip_save` first, or attach to a Houdini you started yourself.
- **Windows only qualified.** 1.0 is tested on Windows with Houdini 22.0.466. The code
  is not Windows-specific, but Linux and macOS are untested.
- **GUI viewer capture needs a homed view.** `viewport_capture` with `source: viewer`
  (the GUI default) captures the view as it is and ignores `fit`. Home the view first
  or use `source: opengl_rop`.
- **Headless OpenGL capture runs in a child hython**, about 3 s per capture or OpenGL
  render, because a second OpenGL render in one hython process crashes 22.0.466.
- **`node_type_info` is large for big HDAs.** The compact view of RBD and similar
  assets is 10 to 26 KB; filter with `folder`.

### Details

1.0 is a rewrite and a clean break from 0.9. Scenes made with 0.9 are ordinary Houdini
scenes and still open. Any `hpmcp.*` userData that 0.9 left in a scene is ignored. The
complete 0.9 tree is kept at the git tag **`v0.9-archive`**: HocusScript, network
documents, source workspaces, production qualification, and all of its docs and scripts.

### Why

The 0.9 reviews (`docs/redesign/review/01`–`06`) found that agents paid about 25k tokens for 103 listed tools before any work, and that the only listed way to change a parm was a network-document checkout that grew to megabytes.
HocusScript was 57% of the code and nobody used it outside fixtures, no tool was ever tested against a real Houdini, and first use failed on the installed Houdini after about nine manual steps.
1.0 therefore keeps a small surface of tools in Houdini's own vocabulary, runs the official MCP SDK outside Houdini, and tests every tool inside hython.

### Removed, and what replaces it

| Removed in 1.0 | Use instead |
|---|---|
| HocusScript, `.hocus` files, the HocusScript compiler, lock/project/bundle schemas | `network_build` with Houdini's native `hou.data` format (read it back with `network_describe`), or `houdini_python` |
| Network documents (checkout / validate / diff / apply) | Direct primitives: `node_create`, `node_edit`, `node_connect`, `parm_set`, `network_build` |
| Source workspaces, workspace grants, and the "Source Workspaces" Python panel | Nothing. Agents edit files with their own tools. |
| Production qualification: HS8/RC release ceremony, attestation, install manifests, the source-admission import finder | Normal pip/uv integrity plus `hocuspocus doctor` |
| `scripts/build.ps1`, `build_transaction.ps1`, `install_hocuspocus_mcp_client.ps1`, the 676-line governed stdio launcher | `uv tool install`, `hocuspocus install-houdini`, `claude mcp add -s user hocuspocus -- hocuspocus-mcp` |
| Hand-written MCP protocol code inside Houdini, and the fixed port 37219 with a shared token | `hocuspocus-mcp` bridge on the official `mcp` SDK; a stdlib-only host on an ephemeral loopback port with a token per instance |
| Exact pin to Houdini 22.0.368 | Houdini `>= 22.0`; untested builds get a warning, not a refusal |
| 103 listed tools with dotted names (`node.create`, `scene.get_summary`, …) | 31 `core` tools (35 in `full`) with snake_case names; see `docs/tools.md` |
| Result redaction (`"<redacted>"` in place of hip paths, save paths and long strings) | No redaction. Real paths are returned. |
| `python3.11libs/`, `package/`, `config/`, `python_panels/`, `editors/` (TextMate grammar), the old `toolbar/` | `src/hocuspocus/` plus the `houdini/` package payload, including a Status/Start/Stop shelf |
| The 0.9 `unittest` scenario suite and its helper modules, and `docs/schemas/` | pytest in three tiers: `tests/unit`, `tests/integration` (in hython) and `tests/e2e` |
| Roadmaps, trackers, the user manual and the 0.9 specs under `docs/` | `README.md`, `docs/quickstart.md`, the generated `docs/tools.md`, `docs/BIBLE.md`, `docs/CONTRIBUTING.md` |

### Added

- 35 tools in Houdini vocabulary across these areas: session and instances, hip
  lifecycle with safe handling of unsaved work, nodes and networks, parms (tuples,
  expressions, keyframes, menus, ramps), cook and problems, geometry reads with stats,
  viewport capture and render (returning an image), the `houdini_python` escape hatch,
  node type search and info, undo, time, selection, jobs, and in the `full` profile
  HDA, USD stage, PDG and events.
- One labelled undo group for each mutating call.
- Errors as `isError` results with a stable `code`, a `hint` and `candidates`.
- An instance registry. Several Houdinis can run at once, and the bridge can launch GUI
  or headless Houdinis. `tools/list` works with no Houdini running.
- MCP resources (`houdini://…`, `hocuspocus://guide`), prompts, and server
  instructions.
- `hocuspocus` CLI commands: `install-houdini`, `uninstall-houdini`, `doctor`,
  `client-config`, `docs tools`, `version`.
