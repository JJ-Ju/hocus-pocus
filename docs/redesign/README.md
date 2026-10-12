# docs/redesign

This directory holds the record of the HocusPocus 1.0 redesign: the reviews of 0.9 that
motivated it, the evaluations of 1.0 that closed it, a progress log, and image evidence.
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

Reports 10 and later, when present, are reviews of the merged 1.0 and are listed by their
own authors.

## Other files

- [`progress.md`](progress.md): one line per milestone event of the redesign, M0 to the
  merge and after.
- [`evidence/city-destruction/`](evidence/city-destruction/): captures and renders from
  reviews 08 and 09. Each report's evidence table says how each image was made.
  `01`–`03` are from review 08 (building, city overview, street); `10`–`21` are from
  review 09 (simulation frames, contact sheet, animated GIF).

The 0.9 source, docs and scripts that reviews 01–06 describe are at the git tag
`v0.9-archive`. Line numbers and file paths quoted in those reports refer to that tree.
