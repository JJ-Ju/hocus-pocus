# HocusPocus 1.3 plan

1.2 covered Solaris, PDG and GUI sessions. Still untested by a real workload: simulations with
caching (DOPs, `cook frame_range`, jobs under load), Copernicus image work, driving two Houdini
instances at once (GUI for editing, a headless worker for renders), and the shipped prompts.
1.3 evaluates those, fixes what they find plus the known items, and ships.

## Phase 1 — evaluation workloads (through the MCP tools only)
- **17 FX sim + cache:** a small pyro or FLIP sim on the destruction scene or a fresh one, cached
  with a File Cache SOP driven by `cook {frame_range}` as a job, flipbooked with `render`, inspected
  with `geo_info`/`geo_read` across frames; measures job progress, cancellation, memory, and what
  an FX TD reaches for that is missing.
- **18 Copernicus:** a COP network generating and compositing images (noise, blur, color, text),
  output to disk, previewed through `viewport_capture`/`render`; tests `Cop` discovery, parm
  idioms, and image return paths.
- **19 Two instances:** GUI Houdini (editing) plus a headless worker (`hocuspocus launch
  --headless`) rendering the GUI's saved hip; the agent switches with `houdini_connect {pid}`,
  checks `houdini_status.instances`, jobs per instance, and what breaks. Also evaluates the four
  shipped prompts and the `hocuspocus://guide` resource for usefulness.

## Phase 2 — fixes
- Every P0/P1 from 17–19.
- Known items: integration tier split into `fast` (< 90 s, default) and `slow` markers; script
  (dynamic) menus in `node_type_info`/`parm_get` evaluated or marked; keyed component names in
  `events`; a structural answer for the `tools/list` budget (a `minimal` profile and/or per-tool
  `notes` for every argument detail) so new features no longer fight the 40 KB cap.

## Phase 3 — release
CHANGELOG 1.3.0, BIBLE rows, docs, all tiers green, tag `v1.3.0`, GitHub release.

## Out of scope
Linux/macOS qualification; APEX; HocusScript; new transports; PyPI publishing (needs a token).
