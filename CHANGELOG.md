# Changelog

This project uses [Semantic Versioning](https://semver.org/). The 0.9 compatibility
policy does not apply to 1.0.

## Unreleased (1.0.1)

Nothing yet.

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
