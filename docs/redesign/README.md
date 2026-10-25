# docs/redesign

This directory holds the record of the HocusPocus 1.0 redesign, the 1.x releases after
it and the 2.0 work: the reviews of 0.9 that motivated 1.0, the evaluations of 1.0 that
closed it, the 1.1 to 1.4 plans and the evaluations behind them, the 2.0 specification, a
progress log, the generated `tools/list` budget report, and image evidence.
None of it but `budget.md` is a living document. The design authority is
[`docs/BIBLE.md`](../BIBLE.md), rewritten for 2.0 (the 1.4 bible is at git tag `v1.4.0`);
user documentation is [`README.md`](../../README.md), [`docs/quickstart.md`](../quickstart.md),
[`docs/tools.md`](../tools.md) and, for upgrades, [`docs/migration-2.0.md`](../migration-2.0.md).

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
| [`review/17-fx-sim-cache-eval.md`](review/17-fx-sim-cache-eval.md) | Workload evaluation: a pyro sim cached with a File Cache, flipbooked with an OpenGL ROP, inspected across frames and stressed with cancels and bad cache paths | 1.2.1 at `88e654c` (`release/1.3`), headless hython | 2026-10-12 | 1.2.1 evaluation record; its papercuts were fixed in 1.3 |
| [`review/18-copernicus-eval.md`](review/18-copernicus-eval.md) | Workload evaluation: a Copernicus network generating and compositing a city map, written to disk and read back by SOPs | 1.2.1 at `88e654c` (`release/1.3`), headless hython | 2026-10-12 | 1.2.1 evaluation record; its papercuts were fixed in 1.3 |
| [`review/19-two-instances-and-prompts-eval.md`](review/19-two-instances-and-prompts-eval.md) | Workload evaluation: a GUI Houdini and a headless worker driven from one session, and the four shipped prompts followed as written | 1.2.1 at `88e654c` (`release/1.3`), GUI Houdini FX and headless hython | 2026-10-12 | 1.2.1 evaluation record; its papercuts were fixed in 1.3 |
| [`review/21-scorecard-1.3.md`](review/21-scorecard-1.3.md) | Friction scorecard re-run: the twelve review 07 tasks, 122 round trips, scored 4/5/5/5/5/5 | 1.3.0 at `32450ef` (`release/1.4`), headless hython | 2026-10-13 | 1.3.0 evaluation record; its papercuts were fixed in 1.4 |
| [`review/22-soak-1.3.md`](review/22-soak-1.3.md) | Soak test: 616 calls on one session (plus a 614-call pilot) against one headless host; latency drift, memory, leaks | 1.3.0 at `32450ef` (`release/1.4`), headless hython | 2026-10-13 | 1.3.0 evaluation record; its findings were fixed in 1.4 |
| [`review/23-vellum-usd-eval.md`](review/23-vellum-usd-eval.md) | Workload evaluation: a Vellum cloth cached, exported to USD, re-imported with `sublayer` and rendered with Karma | 1.3.0 at `32450ef` (`release/1.4`), headless hython | 2026-10-13 | 1.3.0 evaluation record; its papercuts were fixed in 1.4 |
| [`review/27-portability.md`](review/27-portability.md) | Linux and macOS portability audit: paths, pref dirs, install locations, process launch, signals, lifetime, registry, ledger, permissions; findings table and what qualification still needs | `release/2.1` at `b6a5b53` plus stream B, static read and unit tests with a faked `sys.platform` (no Linux or macOS Houdini) | 2026-10-24 | 2.1 audit record; three findings fixed in 2.1 |
| [`review/25-scorecard-2.0.md`](review/25-scorecard-2.0.md) | Friction scorecard on 2.0: the twelve review 07 tasks on the `core` profile | 2.0 release candidate, headless hython | 2026-10-14 | 2.0 evaluation record |
| [`review/26-neo-tower-dogfood.md`](review/26-neo-tower-dogfood.md) | Dogfood: a game-ready procedural skyscraper generator (`hp::neo_tower`) built through the MCP tools in three phases (massing, facade and interiors; UVs, textures, LODs, collision and export; silhouettes, grime and lookdev), with call tallies, escapes, friction and an overall assessment | 2.0.0 bridge on `release/2.1`, headless hython, Indie | 2026-10-24 | 2.1 evaluation record; its friction drove streams D1 to D5 |
| [`review/28-mini-tower-2.0-vs-2.1.md`](review/28-mini-tower-2.0-vs-2.1.md) | The same compact skyscraper-generator brief run by two fresh sessions, one on 2.0.0 and one on 2.1; escapes 7 to 1 | 2.0.0 and `release/2.1` at `c350194`, headless hython, Indie | 2026-10-24 | 2.1 re-run record (plan-2.1 stream D exit) |

Reports 10 to 12 are the post-merge code review, the ergonomics review and the 1.1 city
rebuild; `plan-1.1.md` and `CHANGELOG.md` 1.1.0 cite them. Reports 13 to 15 are the 1.2
evaluation workloads (`plan-1.2.md` phase 1); each describes 1.1 as it stood at the
commit its banner names, and `CHANGELOG.md` 1.2.0 lists what was fixed. Report 16 is the
Solaris re-run on 1.2 (`CHANGELOG.md` 1.2.0 cites its N-numbered findings). Reports 17 to 19
are the 1.3 evaluation workloads (`plan-1.3.md` phase 1); each describes 1.2.1 at
`88e654c`, the commit its banner names, and `CHANGELOG.md` 1.3.0 lists what was fixed.
Report 20 is the FX re-run on 1.3 (`CHANGELOG.md` 1.3.0 cites its N-numbered findings).
Reports 21 to 23 are the 1.4 evaluations (`plan-1.4.md` phase 1); each describes 1.3.0 at
`32450ef`, the commit its banner names, and `CHANGELOG.md` 1.4.0 lists what was fixed.
Report 24 is the Vellum and USD re-run on 1.4 (`CHANGELOG.md` 1.4.0 cites its N-numbered
findings). Reports 07 to 24 are also the evidence for 2.0: `spec-2.0.md` §0 summarises what
they measured, and five of them are scripted as the workloads tier (`tests/workloads/`).
Report 25 is the 2.0 scorecard (`CHANGELOG.md` 2.0.0). Reports 26 to 28 are the 2.1
evaluations (`plan-2.1.md`): the neo_tower dogfood, the portability audit and the same
generator brief run on 2.0.0 and on 2.1; `CHANGELOG.md` 2.1.0 lists what was fixed.
Their images are in `evidence/neo-tower/` and `evidence/mini-tower/`.

## Other files

- [`spec-2.0.md`](spec-2.0.md): the 2.0 specification (2026-10-13), the plan for the
  four contract changes (`edit`, `inspect`/`search` and resources, the bridge ledger,
  `look`), the four refactors (spec files, workloads tier, parity matrix, platform), the
  profiles and milestones M0 to M4. It was authoritative for the 2.0 work until M3, when
  `docs/BIBLE.md` was rewritten from it; where they differ, the bible wins.
- [`budget.md`](budget.md): the `tools/list` size of every profile × `result_content`
  mode, one dated row per measurement, and the largest tools of the latest run.
  Generated by `python -m hocuspocus.tools.docs --budget`; do not edit by hand.
- [`progress.md`](progress.md): one line per milestone event of the redesign, M0 to the
  merge and after, through the 1.1 to 1.4 releases and the 2.0 milestones.
- [`plan-1.1.md`](plan-1.1.md), [`plan-1.2.md`](plan-1.2.md), [`plan-1.3.md`](plan-1.3.md),
  [`plan-1.4.md`](plan-1.4.md), [`plan-2.1.md`](plan-2.1.md): the release plans.
- [`evidence/city-destruction/`](evidence/city-destruction/): captures and renders from
  reviews 08 and 09. Each report's evidence table says how each image was made.
  `01`–`03` are from review 08 (building, city overview, street); `10`–`21` are from
  review 09 (simulation frames, contact sheet, animated GIF); `02_city_overview_1.1.png`
  is from review 12; `30_lookdev_karma.png`, `40_pdg_wedges.png` and `50_gui_viewer.png`
  are from reviews 13, 14 and 15; `60_pyro_frames.png`, `70_copernicus_citymap.png` and
  `80_two_instance_render.png` are from reviews 17, 18 and 19;
  `90_soak_latency.png` and `100_vellum_usd_karma.png` are from reviews 22 and 23.

The 0.9 source, docs and scripts that reviews 01–06 describe are at the git tag
`v0.9-archive`. Line numbers and file paths quoted in those reports refer to that tree.
