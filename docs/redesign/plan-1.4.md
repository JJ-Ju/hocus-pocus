# HocusPocus 1.4 plan

1.3 closed the multi-instance and caching gaps. 1.4 re-baselines the surface against the
original scorecard, stress-tests a long session, covers Vellum and USD round trips, and
migrates captures off the OpenGL ROP that Houdini 22 deprecates.

## Phase 1 — evaluation workloads (through the MCP tools only)
- **21 Scorecard re-run:** a fresh agent repeats the twelve review-07 tasks on 1.3.0 and scores
  the six dimensions again (last scored on 1.0: 4/5/4/4/5/5).
- **22 Soak:** a scripted ~600-call session (create, edit, wire, cook, capture, undo, hip save,
  events, type lookups) against a headless host; measures latency drift, host memory, registry
  and log growth, leaked nodes/jobs/files, and any failure under sustained use.
- **23 Vellum + USD round trip:** a Vellum cloth or grains sim over the destruction scene's
  district, cached, exported to USD with a `usd_rop`/`usdexport`, re-imported with `sublayer`
  and rendered with Karma; exercises DOPs through SOP solvers, USD IO and layer inspection.

## Phase 2 — fixes
- Every P0/P1 from 21–23.
- Known items: captures and flipbooks through the Flipbook ROP (`flipbook` ROP in 22; keep the
  OpenGL ROP as fallback where the new ROP cannot run headless) with the deprecation note
  gone; `network_build` parm callback notes like `node_create`; budget policy: cap what
  clients see by default (text mode) at 32 KB and `both` mode at 44 KB, measured per profile.

## Phase 3 — release
CHANGELOG 1.4.0, BIBLE rows, docs, all tiers green, tag `v1.4.0`, GitHub release.

## Out of scope
Linux/macOS qualification; APEX; HocusScript; new transports; PyPI publishing (needs a token).
