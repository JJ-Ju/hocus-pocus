# Review 05: Tests, Scripts, Docs and Developer/User Experience

Reviewer scope: `tests/`, `scripts/`, `docs/`, in-Houdini UI, first-use path, repo layout, git history.
Machine: Windows 11, system Python 3.13.14, Houdini **22.0.466** (hython 3.13.10). Review date 2026-10-12.

## TL;DR

- The suite is 43 `unittest` "scenario" tests that are really ~2,400 assertions spread across 35 helper modules (23.6k lines). **None of it touches a real `hou`**. Real-Houdini coverage exists only in ~20 installed-package `smoke_*`/`qualify_*` scripts, and the docs don't point to the three most useful ones.
- No single interpreter runs the suite green. The system Python is missing `cryptography` and `pxr`. hython has both but breaks the HS8 subprocess checks. Even with both dependencies added, one timing-based PowerShell build-transaction test failed after a 180 s wait.
- **First use is broken on a current Houdini.** `startup.py` hard-gates on `22.0.368`, and this machine has `22.0.466`. On top of that, the documented path has about 9 manual steps and introduces about 14 concepts before the first successful call.
- About 60% of the scripts and 70% of the docs are release ceremony (HS8, RC1/RC2, attestation) or phase trackers. They should be archived, not carried into the redesign.
- The good news: `HocusPocusRuntime.handle_request()` can be driven **in-process from the source tree under hython in 0.3 s**. That is the basis for a fast, honest integration test tier.

---

## 1. Test suite assessment

### 1.1 How tests run today

- Framework: stdlib `unittest`. Each `tests/test_*.py` does `sys.path.insert(0, ROOT/"python3.11libs")`. The documented command is `python -m unittest discover -s tests -p "test_*.py"` (`docs/release-validation.md` §A1). pytest isn't used, and the doc says outright "Do not rerun the same suite under pytest".
- `scripts/lint.ps1` runs Ruff (`ruff.toml`: E9/F, mccabe 12, pylint size rules) and also enforces three repo policies: at most **50 `def test_`**, at most **1,200 physical lines per file**, and **no `noqa`**.
- `requirements-lint.txt` pins `ruff==0.15.12`. `requirements-release.txt` pins `cryptography==45.0.3`. Nothing declares that the test suite needs `cryptography`, and nothing at all declares `pxr` (USD).

### 1.2 Run log

All runs used `PYTHONDONTWRITEBYTECODE=1`. Dependencies went into a scratch `--target` directory, never into the repo or Houdini prefs.

| Run | Interpreter | Result | Wall time |
|---|---|---|---|
| `ruff check python3.11libs scripts tests` | ruff 0.15.12 | All checks passed | 1 s |
| authoring_scenarios | system py 3.13 | 8/8 OK | 1 s |
| control_scenarios | system py | 8/8 OK | 1 s |
| hs8_scenarios | system py | **import error**: `No module named 'cryptography'` | 1 s |
| project_scenarios | system py | 10/10 OK | 6 s |
| workspace_scenarios | system py | 6/6 OK, including `test_h6_installed_houdini_source_to_live_acceptance`, which needs no Houdini despite its name | 12 s |
| runtime_scenarios | system py | 8/8 OK | 4 s |
| hs8_scenarios + cryptography | system py | 2 OK, 1 ERROR: `No module named 'pxr'` | 1 s |
| all 6 files | hython 22.0.466 | 5 files OK. hs8: 5 subTest FAIL + 1 ERROR, because its subprocess (`sys.executable -I ...`) can't start ("Failed to import encodings") | 39 s total, hs8 12 s |
| full `discover` + cryptography + `usd-core` | system py | 42/43 OK, **1 FAIL**: `Transaction did not reach hostile boundary: install-snapshot-hook.entered` (`tests/hocusscript_hs8_build_transaction_helpers.py:514`, 180 s polling deadline) | **240 s** (~220 s in the HS8 test alone) |

Other observations from the runs:

- Every hython launched with the repo root as cwd prints `HOCUS998 HocusPocus startup blocked: invalid_install_root.` The repo's own `scripts/python/pythonrc.py` gets picked up, likely through the default `$HIP/scripts` search path. Package assets that live at the repo root auto-execute in any hython started there. The redesign should keep Houdini assets in a subfolder.
- The suite writes runtime state into the repo (`.hocuspocus/`, the `state_root()` fallback in `core/paths.py:33`). Subprocesses started with `-I` ignore `PYTHONDONTWRITEBYTECODE` and leave `__pycache__` in `python3.11libs`. I removed both after my runs.
- The HS8 test rewrites `scripts/build_transaction.ps1` with injected hooks (`_patched`, `hocusscript_hs8_build_transaction_helpers.py:493`). It works on a temp copy, which is fine. It also runs the real `build.ps1 -Clean -OutputDir <repo root>` and expects it to refuse (`hocusscript_hs8_clean_process_helpers.py:666`). If that guard ever regressed, the test would wipe the checkout.

### 1.3 Quality assessment

- **The 50-test cap pushed tests into helpers, it didn't remove them.** Commit `3ef74dc` deleted 57 focused test files (−14.9k lines) and folded them into 6 scenario files. The logic moved into `tests/hocusscript_*_helpers.py` and `tests/runtime_*.py`, which the cap doesn't count. The result is about 2,394 assert calls behind 43 test names.
- **Test names don't describe what they test.** For example, `test_document_validation_accepts_a_network_and_rejects_an_ambiguous_edge` also runs the HDA capability contract and the mutation-integrity contract (`test_runtime_scenarios.py:367-370`). The stdio broker contract is reached through `runtime_node_type_discovery.py:10`. When a test fails, you can't tell what broke, and the first failure hides everything after it.
- **Files are sized to the 1,200-line cap.** 35 tracked files are at or above 1,100 lines, and four sit at exactly 1,200 (`control_semantic.py`, `control_expander.py`, `_workspace_native.py`, `package_search_provenance.py`). Splits follow the line limit rather than cohesion.
- **Brittle assertions on source text.** 25 assertions grep script source for literals, for example `assertIn("CREATE_SUSPENDED", source)` in `hocusscript_hs8_clean_process_helpers.py:854`. There are also 145 source/`read_text` reads and ~306 fakes/mocks (`SimpleNamespace` hou, `_Hou`, `CatalogHou`).
- **What the tests cover:** about 35 of the 43 exercise HocusScript, release ceremony or workspace authority. 8 exercise the live MCP runtime, and those use fake `hou`. **None of the 103 MCP tools is exercised against a real Houdini by the automated suite.**
- **What's good:** the HocusScript compiler tests are deterministic, fast (under 1 s) and golden-based (`tests/fixtures/hocusscript/`), and the graph-store migration fixtures are valuable. Keep the fixture data even if HocusScript is cut back.

### 1.4 Feasibility probe for a real integration tier

A 30-line scratch script ran under hython with `sys.path` pointed at the source tree (no install, no HTTP listener). It built `HocusPocusRuntime(ServerSettings(token_mode="disabled", auto_start=False))` and called `handle_request` for `tools/list`, `object.create_geometry` and `scene.get_summary`.

- **Startup 0.23 s, all three calls 0.30 s total, all correct.**
- `tools/list` returned **103 tools and ~100 KB of JSON**, roughly 25k tokens of agent context before any work starts. That's a design concern in its own right.
- Exiting through `os._exit(0)` **segfaulted in `libPDGD` during exit handlers**. The harness has to shut down cleanly (stop the dispatcher and monitor, then use `hou.exit()` or a normal interpreter exit).

### 1.5 Recommended test strategy

**Harness:** use **pytest** everywhere, run by system Python for offline tests and by `hython -m pytest` for Houdini tests. Install pytest into a project-local `.venv`, and for hython expose it through a `--target` dependency directory (the cp313 wheels load in hython 3.13, as `cryptography` did here). Drop the 50-test cap and the 1,200-line cap. Replace them with Ruff complexity rules plus a pytest duration budget.

```
tests/
  unit/                # system python, no hou, <10 s total; pure logic only
    test_schema_*.py   # tool input/output schemas, JSON-RPC framing, settings, policy
    test_document_*.py # network-document validate/diff (pure)
  integration/         # hython -m pytest; real hou, in-process runtime; marker: houdini
    conftest.py        # session fixture: HocusPocusRuntime(auto_start=False), fresh hou.hipFile.clear() per test
    test_tools_<group>.py   # one file per tool group: node, parm, document, hda, scene...
  e2e/                 # marker: e2e; spawns `hython -m hocuspocus.host --port 0` (or 37900+)
    test_stdio_roundtrip.py # official `mcp` client SDK -> stdio server -> live hython -> assertions
  gui/ (optional)      # manual checklist + one scripted `houdini -foreground` launch that asserts the package loaded
  fixtures/            # keep hocusscript goldens + graph_store fixtures if those features survive
```

- `conftest.py` at the root finds hython through `HFS`, `HOUDINI_HYTHON`, or the default install path. It **auto-skips** the `houdini` and `e2e` markers when hython isn't available, so contributors without a licence still get a green offline run.
- One integration test per tool contract, with a cheap scene setup and assertions on `structuredContent`. Generate a parametrized "every tool has a schema and description, and validates its own example" test from the tool registry.
- Time budget: unit tests under 10 s, integration tests under 60 s (one hython process per session), e2e tests under 30 s.
- Move installer and build-transaction checks out of the unit tier into a separate `tests/install/` that runs only in CI release jobs.

---

## 2. Scripts classification (`scripts/`, 41 files, 18.7k lines)

| Script | Class | Verdict |
|---|---|---|
| `python/pythonrc.py` (265 lines, source-only import finder, admission checks) | core runtime | **Rewrite** as a ~10-line `import hocuspocus; hocuspocus.autostart()` |
| `python/456.py` (docstring only) | dead | Delete |
| `hocuspocus-mcp-stdio.py` (676 lines, hashes up to 20k governed files on launch) | core runtime (broker launcher) | Replace with a `hocuspocus-mcp` console entry point |
| `hocuspocus_stdio_bridge.py` (5 lines, unreferenced) | dead | Delete |
| `build.ps1` (577), `build_transaction.ps1` (1,190) | build/install | Delete; replace with `pip`/`uv` plus a ~50-line `hocuspocus install-houdini` |
| `install_hocuspocus_mcp_client.ps1` (609) | build/install | Delete; replace with `claude mcp add` |
| `hs8_install_manifest.py`, `hs8_package_pointer.py`, `hs8_windows_manifest_cleanup.py` (1,067), `hs8_output_guard.py`, `hs8_child_process.py`, `hs8_visual_review.py` | release ceremony | Delete |
| `manage_hocusscript_rc1_evidence.py`, `manage_hocusscript_release_candidate.py`, `verify_hocusscript_hs8_release_authority.py`, `release_evidence_support.py`, `qualify_hocusscript_hs8_clean_image.py`, `qualify_hocusscript_hs8_clean_process.py` (1,162) | release ceremony | Delete (archive in git history) |
| `benchmark_hocusscript_release.py`, `verify_hocusscript_compatibility.py`, `verify_graph_store_upgrades.py` | release ceremony / dev verification | Delete unless HocusScript or the graph store survives; then fold into pytest |
| `smoke_h22_first_use.py`, `smoke_h22_authoring_repair.py`, `smoke_durable_stdio_broker.py`, `durable_h22_host.py` | dev verification (real Houdini, highest value) | **Port to `tests/integration` and `tests/e2e`** |
| `smoke_scene_event_monitor.py` | dev verification | Port to integration |
| `smoke_hocusscript_{preview,apply,export,h5,h6,hs7,hs7_acceptance,hs8}.py` and `*_support.py` (~7k lines) | dev verification for HocusScript phases | Delete; keep one HocusScript e2e if the language stays |
| `export_houdini_catalog.py` | dev tool | Keep as a CLI subcommand if catalogs stay |
| `smoke_live_server.ps1` (hard-codes port 37219) | dev verification | Delete; superseded by e2e |
| `lint.ps1` | dev | Replace with `ruff check` and `ruff format --check` in `pyproject.toml`/CI |
| `fixtures/hs8/*`, `fixtures/release/*` | release ceremony | Delete; keep `rock-family*.hocus` only if HocusScript stays |

**Keep:** 4 smoke scripts, ported into pytest. **Delete:** everything else, about 36 files and ~16k lines.

---

## 3. Docs classification (`docs/`, 39 md files, 11.5k lines, plus 61 schemas)

| Doc | Class | Verdict |
|---|---|---|
| `phase2…phase7roadmap.md`, `phase2…phase6-engineering-tracker.md`, `phase5.5*`, `phase5.6*` (13 files) | historical tracker. Several still say "Status: active", which is wrong | Archive to a git tag; delete from tree |
| `engineering-task-tracker.md`, `improvement-roadmap.md`, `improvement-task-tracker.md`, `document-graph-overhaul-{roadmap,task-tracker}.md`, `hocusscript-roadmap.md`, `hocusscript-roadmap-completion-plan.md`, `hocusscript-task-tracker.md` (836 lines) | historical tracker | Archive |
| `live-brick-hda-authoring-{findings,repair-plan}-2026-07-31.md` | incident record | Archive. The findings are worth mining for the design bible: HDA parm authority, undo |
| `release-validation.md` (641), `v1-hostile-coverage-map.md`, `hocusscript-hs8-production.md`, `document-apply-smoke-procedure.md`, `hocusscript-live-catalog-smoke.md` | release ceremony / manual procedures | Delete or archive |
| `panel-terminal-design.md` ("initial design", never built) | stale proposal | Delete |
| `houdini-mcp-spec.md`, `durable-mcp-transport.md`, `compatibility-policy.md`, `document-contract-v1.md` | living spec | Fold the useful parts into a single `design.md` |
| `hocusscript-spec.md` (1,192), `hocusscript-hs7-support-matrix.md`, `document-graph-overhaul-spec.md` | living spec (HocusScript) | Keep only if HocusScript survives the redesign |
| `agent-workflows.md` | user doc (agent-facing) | Keep; rewrite as an MCP `instructions` / prompt resource |
| `user-manual.md` (597) | user doc | Replace with quickstart + generated tool reference |
| `docs/schemas/*.json` (61; 5 versions each of lock/project/bundle/graph-spec, 7 HS8 release schemas) | **runtime data, misfiled under docs**: loaded by `live/ops/hocusscript_resources.py:114`, `production.py:163`, `document_metadata.py` | Move into the package (`src/hocuspocus/schemas/`). Drop pre-1.0 versions; nothing shipped publicly needs migrating |

**Proposed new docs set:**

1. `README.md`: what it is, one GIF, a 3-command quickstart, links. Under 150 lines.
2. `docs/quickstart.md`: install, connect Claude Code/Codex, first prompt, troubleshooting top 5.
3. `docs/tools.md`: **generated** from the tool registry by `hocuspocus docs --tools`, with a CI check that the file is fresh.
4. `docs/design.md`: the design bible. Principles for idiomatic Houdini driving, error model, undo/transactions, security model, transport.
5. `CONTRIBUTING.md`: dev setup (`uv sync`), test tiers, how to run hython tests, release steps (one page).
6. `CHANGELOG.md`.

---

## 4. First-use friction

**Today**, following README.md, before the first successful agent call:

1. Install Houdini **22.0.368** exactly. Any other build is refused: `startup.py:20` `SUPPORTED_HOUDINI_VERSION = "22.0.368"`, and this machine has 22.0.466, so auto-start fails with `unsupported_houdini`.
2. Install a standalone Python 3.11+ for the broker.
3. Clone the repo.
4. `powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install` (a versioned install root, token generation, a `HOCUSPOCUS_TOKEN` user environment variable set by `build_transaction.ps1:618`).
5. `powershell ... install_hocuspocus_mcp_client.ps1`.
6. Find `Documents\houdini22.0\packages\hocuspocus-claude.json` and **hand-merge** it into the Claude Code MCP config. No `claude mcp add` line is given.
7. Restart Houdini.
8. Restart the MCP client.
9. Verify in Houdini's Python shell with `hocuspocus.server_status()`, then call `session.info`.

**Concepts introduced before success (about 14):** Houdini packages, versioned install root, package pointer, install manifest/digests, bearer token, token rotation, stdio broker vs. private HTTP host, durable host generations, `HOCUS999 host_offline`, operation IDs/`session.get_operation`, policy profiles/`run_code` capability, granted capabilities, checkouts, and (for HocusScript) source-workspace grants through a Qt panel.

**Ideal (target 3 steps, 2 concepts: "Houdini package" and "MCP server"):**

```powershell
uv tool install hocuspocus            # or: pipx install hocuspocus
hocuspocus install-houdini            # writes packages/hocuspocus.json -> auto-loads, any 22.x
claude mcp add hocuspocus -- hocuspocus-mcp
```

Then open Houdini and ask Claude to do something. Version handling becomes a minimum version plus a warning, not an exact-build gate. Token handling becomes automatic: a file in `$HOUDINI_USER_PREF_DIR` read by both sides, with no user action. `claude mcp add` (or a `.mcp.json` checked into the user's project) replaces config merging.

---

## 5. Repo layout, packaging, CI

**Python directory naming.** Houdini 22 runs Python 3.13, and the current `python3.11libs` only works because `package/hocuspocus.json` prepends it to `PYTHONPATH` explicitly. The name is misleading and gets hard-coded everywhere (`_GOVERNED_ROOTS`, the installer, tests). Recommended layout: a plain `src/hocuspocus/` added to `PYTHONPATH` by the package json, plus a small version-agnostic Houdini asset tree.

```
pyproject.toml          # hatchling; console scripts: hocuspocus, hocuspocus-mcp
src/hocuspocus/
  host/                 # runs INSIDE Houdini: stdlib only; hou-facing tools, local JSON-RPC listener
  mcp/                  # runs OUTSIDE Houdini: official `mcp` SDK server (stdio), forwards to host
  tools/                # tool definitions shared by both (schemas + docs source)
  schemas/
  cli.py                # install-houdini, doctor, docs --tools
houdini/                # the Houdini package payload (hpath); NOT at repo root (avoids $HIP/scripts autorun)
  hocuspocus.json.in
  scripts/python/pythonrc.py   # 5 lines: import hocuspocus.host; autostart
  toolbar/ python_panels/      # only if kept
tests/{unit,integration,e2e}
docs/
```

**Where the MCP SDK runs.** Don't vendor `mcp` (pydantic-core, anyio, starlette, httpx and more) into Houdini's interpreter. It risks clashing with SideFX's bundled packages and with studio pipelines. Keep the in-Houdini side stdlib-only, as it already is (`core/jsonrpc.py` is hand-rolled), and run the official SDK out of process through `uv tool`/`uvx`. That also removes the hand-written MCP protocol negotiation (`core/server.py:1138`, `core/stdio_bridge.py:405`), which otherwise has to keep pace with MCP spec revisions. The `install-houdini` command should point the package json only at the stdlib-only `host` path (or copy it to a stable location), never at the whole tool environment.

**Integrity and governance machinery.** `pythonrc.py`'s source-only import finder, bytecode bans, install manifests and the launcher that hashes every file are all oversized for a localhost dev tool. They are also the source of `HOCUS998`-type failures. Drop them, and rely on normal pip/uv integrity plus a `hocuspocus doctor` command.

**CI (GitHub Actions, Windows):**
- `windows-latest` and `ubuntu-latest`: `uv sync`, `ruff check`, `ruff format --check`, `pytest tests/unit`, and a check that `docs/tools.md` is fresh. Fast, needs no licence.
- Hosted runners can't run hython (licence). Use a **self-hosted Windows runner with Houdini 22** (labels `houdini`), running `hython -m pytest tests/integration tests/e2e` nightly and on labelled PRs. Use port 0 or the 37900+ range, an isolated `HOUDINI_USER_PREF_DIR` per run, and a temporary cwd outside the repo.
- Release: build the wheel, run a smoke test of `uv tool install dist/*.whl` and `hocuspocus install-houdini --prefs <tmp>`, publish to PyPI.

---

## 6. In-Houdini UI

- `python_panels/HocusPocus.pypanel` plus `ui/workspace_widget.py` (310 lines): the "Source Workspaces" approval UI for HocusScript project grants. It only matters if the source-workspace authority model survives. Recommend dropping it with that model.
- `ui/panel.py` plus `toolbar/hocuspocus.shelf` (Open/Start/Stop): an operator dialog with status, logs, and copy endpoint/token. Nice to have. Replace it with one shelf tool or status-bar indicator ("HocusPocus: connected, N calls"), plus `hocuspocus doctor` on the CLI. Remove "copy token" entirely.
- `editors/hocusscript.tmLanguage.json`: a TextMate grammar with no packaging around it (no VS Code extension manifest). Keep it only alongside HocusScript, in a separate `editors/vscode` package.
- `config/default.toml` has `feature_flags.python_panel = false` and `python3.11libs/hocuspocus/workers/` is a 1-line stub. Both are dead.

---

## 7. Git history and churn

75 commits. Phases 2–6 landed in **3 days** (2026-03-09 to 03-11, 35 commits). HocusScript V1 plus H22 qualification ran 2026-07-09 to 08-01 in very large agent-authored commits: `8a26ae7` (382 files, +138k lines), `6b0183c` (276 files, +83k), `3964ab7` (87 files, +16.6k). None of these is reviewable as a PR. Churn concentrates in `hocusscript/` (300 file-touches), `tests/` (200), `docs/` (193; the trackers are the most-edited files: `hocusscript-task-tracker.md` 35 times, `hocusscript-roadmap.md` 33 times) and `live/operations.py` (27). Current code size is HocusScript 56k LOC, live 33.5k, core 8k, UI 0.5k, plus scripts 18.7k and tests 23.6k. The product core (live tools plus transport) is about 30% of the repo.

---

## 8. Top 10 recommendations (ranked)

1. **Remove the exact-build gate** (`startup.py:20`). Support `>=22.0`, warn on untested builds, and add a CI matrix entry per tested build. Today the package refuses to start on the Houdini that is actually installed.
2. **Ship as a pip/uv package with `hocuspocus install-houdini` plus `claude mcp add hocuspocus -- hocuspocus-mcp`.** That is 3 commands, with no PowerShell, no config merging and no restart dance.
3. **Split the process boundary cleanly:** a stdlib-only `host` inside Houdini and the official `mcp` SDK server outside it. Delete the hand-rolled MCP negotiation and the 676-line governed launcher.
4. **Build the hython integration tier first** (`tests/integration`, in-process `handle_request`, about 0.3 s per scenario as measured). Port `smoke_h22_first_use.py`, `smoke_h22_authoring_repair.py` and `smoke_durable_stdio_broker.py` into it before deleting anything.
5. **Adopt pytest with `unit`/`integration`/`e2e` tiers and markers.** Drop the 50-test and 1,200-line caps, which produced mega-tests and line-count-shaped modules. Name tests by what they assert.
6. **Delete the release-ceremony layer**: HS8/RC1/RC2, attestation, clean-image, visual review, install manifests, the `build_transaction.ps1` journal, about 36 scripts, 7 schemas and the related tests. Tag the current master (`v0-archive`) first.
7. **Archive the 25+ roadmap/tracker docs.** Replace them with README, quickstart, a generated `tools.md`, `design.md` and CONTRIBUTING. Fix the stale "Status: active" headers by removing the files.
8. **Move `docs/schemas` into the package** and drop pre-1.0 schema versions. Runtime code must not load from `docs/`.
9. **Shrink the agent-facing surface.** 103 tools and a ~100 KB `tools/list` is too much context. Group the tools, or expose a small core set plus discoverable extensions, and generate the reference from the same registry.
10. **Test hygiene and CI:** never write state into the repo (`core/paths.py:33` fallback). Use an isolated `HOUDINI_USER_PREF_DIR` and a temp cwd for hython, use port 0 or the 37900+ range, and make the harness exit cleanly (the `os._exit` PDG segfault). Run hosted Windows/Linux CI for unit tests and lint, and a self-hosted Houdini runner for integration/e2e.

Decide early whether HocusScript, source-workspace grants and the graph store stay in V2; that decision changes about 60% of the cleanup scope above. Review 03 covers HocusScript in depth.
