# Changelog

This project uses [Semantic Versioning](https://semver.org/). The 0.9 compatibility
policy does not apply to 1.0.

## 1.0.0 (unreleased)

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
| `scripts/build.ps1`, `build_transaction.ps1`, `install_hocuspocus_mcp_client.ps1`, the 676-line governed stdio launcher | `uv tool install`, `hocuspocus install-houdini`, `claude mcp add hocuspocus -- hocuspocus-mcp` |
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
