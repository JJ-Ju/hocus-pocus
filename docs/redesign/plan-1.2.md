# HocusPocus 1.2 plan

1.1 exercised the SOP authoring surface with two real workloads (reviews 08, 09, 12). The
`full` profile (`usd_stage`, `pdg`, `hda`, `events`) and the GUI-only paths (viewer capture,
selection, undo alongside a user) have had integration tests but no real workload. 1.2 starts
with three evaluation workloads, fixes what they find plus the review-12 leftovers, and ships.

## Phase 1 — evaluation workloads (headless unless stated; through the MCP tools only)
- **13 Solaris lookdev:** import the 1.0 city into LOPs, assign MaterialX materials, add a dome
  and key light, inspect with `usd_stage`, render a frame with Karma via `render`.
- **14 PDG wedge:** a TOP network that wedges a building-generator seed, cooks a ROP fetch per
  wedge, collects outputs; driven with `pdg`, `job`, `events`.
- **15 GUI session:** open the destruction hip in a GUI Houdini started with `hocuspocus launch`,
  work alongside a "user" (viewer captures, selection, undo/redo of agent steps, events after
  manual-style edits made via `houdini_python`), and an HDA round trip (`hda create/save/install`).

## Phase 2 — fixes
- Every P0/P1 papercut from 13–15.
- Review 12 leftovers: integer menus for spare parms; wiring and flags in the outline view;
  `cook profile` attribution inside for-each loops; `$HIP` after `hocuspocus launch` should be the
  launch directory, not home; captures written with an opaque background.
- `tools/list` budget headroom: move argument detail from descriptions into `docs/tools.md` and
  the guide so the catalogue sits ≤ 40 KB with the same information available on demand.

## Phase 3 — release
CHANGELOG 1.2.0, BIBLE rows, docs, all tiers green, tag `v1.2.0`, GitHub release.

## Out of scope
Linux/macOS qualification; APEX; HocusScript; new transports.
