# docs/redesign

This directory holds the record of the HocusPocus 1.0 redesign and the 1.x releases
after it: the reviews of 0.9 that motivated it, the evaluations of 1.0 that closed it,
the 1.1 and 1.2 plans and the evaluations behind them, a progress log, and image
evidence.
None of it is a living document. The design authority for 1.x is
[`docs/BIBLE.md`](../BIBLE.md); user documentation is [`README.md`](../../README.md),
[`docs/quickstart.md`](../quickstart.md) and [`docs/tools.md`](../tools.md).

## Reports

| File | What it is | What it reviewed | Date | Status |
|---|---|---|---|---|
| [`review/01-architecture-transport.md`](review/01-architecture-transport.md) | Architecture and transport review | 0.9 core, startup, live dispatcher, launcher/broker, build and install scripts | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/02-tool-surface.md`](review/02-tool-surface.md) | MCP tool surface audit and gap analysis | 0.9 tool and resource registries (`master` @ `cab2430`) | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/03-hocusscript.md`](review/03-hocusscript.md) | HocusScript and network-document review | 0.9 HocusScript compiler, document carriers, source workspaces (`cab2430`) | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/04-research-houdini-mcp.md`](review/04-research-houdini-mcp.md) | Research notes | Houdini 22.0.466 HOM behaviour, other Houdini MCP servers, MCP design practice | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/05-tests-scripts-docs-dx.md`](review/05-tests-scripts-docs-dx.md) | Tests, scripts, docs and developer experience review | 0.9 `tests/`, `scripts/`, `docs/`, first-use path | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/06-hands-on-friction-log.md`](review/06-hands-on-friction-log.md) | Hands-on friction log, an agent driving the server | 0.9.0 against headless hython, 98 round trips | 2026-10-12 | historical: describes 0.9, archived at tag `v0.9-archive` |
| [`review/07-friction-rerun-1.0.md`](review/07-friction-rerun-1.0.md) | Friction log re-run and M5 scorecard | 1.0 at `3a0df8a`, headless, 12 tasks, 102 round trips | 2026-10-12 | 1.0 evaluation evidence |
| [`review/08-city-build-log.md`](review/08-city-build-log.md) | Workload log: building and city generators | 1.0 at `b56666d`, GUI Houdini FX | 2026-10-12 | 1.0 evaluation evidence |
| [`review/09-city-destruction-log.md`](review/09-city-destruction-log.md) | Workload log: fracture and RBD simulation of the city | 1.0 at `d18a621`, GUI Houdini FX | 2026-10-12 | 1.0 evaluation evidence |
| [`review/13-solaris-lookdev-eval.md`](review/13-solaris-lookdev-eval.md) | Workload evaluation: the city in LOPs with MaterialX, lights and a Karma render (`usd_stage`, `render`, `full` profile) | 1.1 at `c812972` (`release/1.2`), headless hython | 2026-10-12 | 1.1 evaluation record; its papercuts were fixed in 1.2 |
| [`review/14-pdg-wedge-eval.md`](review/14-pdg-wedge-eval.md) | Workload evaluation: an eight-wedge TOP network driven through `pdg`, `job` and `events` | 1.1 at `c812972` (`release/1.2`), headless hython | 2026-10-12 | 1.1 evaluation record; its papercuts were fixed in 1.2 |
| [`review/15-gui-session-eval.md`](review/15-gui-session-eval.md) | Workload evaluation: a GUI session next to a user (captures, selection, events, undo) and an HDA round trip | 1.1 at `c812972` (`release/1.2`), GUI Houdini FX | 2026-10-12 | 1.1 evaluation record; its papercuts were fixed in 1.2 |

Reports 10 to 12 are the post-merge code review, the ergonomics review and the 1.1 city
rebuild; `plan-1.1.md` and `CHANGELOG.md` 1.1.0 cite them. Reports 13 to 15 are the 1.2
evaluation workloads (`plan-1.2.md` phase 1); each describes 1.1 as it stood at the
commit its banner names, and `CHANGELOG.md` 1.2.0 lists what was fixed.

## Other files

- [`progress.md`](progress.md): one line per milestone event of the redesign, M0 to the
  merge and after, through the 1.1 and 1.2 releases.
- [`plan-1.1.md`](plan-1.1.md), [`plan-1.2.md`](plan-1.2.md): the release plans.
- [`evidence/city-destruction/`](evidence/city-destruction/): captures and renders from
  reviews 08 and 09. Each report's evidence table says how each image was made.
  `01`–`03` are from review 08 (building, city overview, street); `10`–`21` are from
  review 09 (simulation frames, contact sheet, animated GIF); `02_city_overview_1.1.png`
  is from review 12; `30_lookdev_karma.png`, `40_pdg_wedges.png` and `50_gui_viewer.png`
  are from reviews 13, 14 and 15.

The 0.9 source, docs and scripts that reviews 01–06 describe are at the git tag
`v0.9-archive`. Line numbers and file paths quoted in those reports refer to that tree.
