# Contributing to HocusPocus

**[`docs/BIBLE.md`](BIBLE.md) is authoritative.** If the code and the bible disagree,
one of them is wrong. Fix the code, or change the bible in the same PR and say why. Do
not leave the two disagreeing. Adding a tool, an error code, a config key or a
dependency is a design change, so it goes in the bible first.

## Repository layout

```
pyproject.toml                 # hatchling; console scripts hocuspocus, hocuspocus-mcp; ruff + pytest config
src/hocuspocus/
  __init__.py  version.py
  cli.py                       # install-houdini, uninstall-houdini, launch, doctor, client-config, docs, version
  tools/                       # shared by host and bridge; stdlib only
    catalog.py                 #   the single source of truth for the tool surface
    errors.py                  #   error codes and ToolError
    docs.py                    #   renders docs/tools.md; tools/list size; example validator
    paths.py                   #   state dir (instances/, logs/, captures/)
    budget.py                  #   the response truncator (host and bridge)
  host/                        # INSIDE Houdini; stdlib only; imports hou lazily
    __init__.py                #   start(), stop(), status(), autostart()
    __main__.py                #   hython -m hocuspocus.host
    config.py executor.py server.py dispatch.py runtime.py registry.py jobs.py undo.py
    tools/                     #   one module per tool family, each registering with @tool
      registry.py _diag.py session.py hip.py code.py nodes.py network.py parms.py cook.py
      types.py geo.py visual.py state.py hda.py usd.py pdg.py events.py
  bridge/                      # OUTSIDE Houdini; official mcp SDK
    __main__.py server.py client.py instances.py launch.py local_tools.py
    validate.py budget.py config.py instructions.py
houdini/                       # Houdini package payload (hpath); deliberately NOT the repo root
  hocuspocus.json.template     #   rendered to <prefs>/packages/hocuspocus.json
  scripts/python/uiready.py    #   GUI autostart
  toolbar/hocuspocus.shelf     #   Status / Start / Stop
tests/
  conftest.py                  # finds hython; marks tiers; skips houdini/e2e without hython
  unit/  integration/  e2e/
docs/
  BIBLE.md  quickstart.md  tools.md (generated)  CONTRIBUTING.md
  redesign/README.md             # index of the reviews, evaluations and plans
  redesign/review/*.md  redesign/progress.md  redesign/evidence/
README.md  CHANGELOG.md  LICENSE
.github/workflows/ci.yml  houdini.yml
```

Three rules come with this layout:

- Code under `host/` and `tools/` must stay stdlib-only, because Houdini imports it.
- Only `bridge/` may import `mcp`.
- The repo root must never become a Houdini path. hython puts its cwd on `HOUDINI_PATH`,
  so a `scripts/` folder at the root would auto-run.

## Development setup

```bash
uv venv .venv
uv pip install -p .venv -e ".[dev]"
```

To make Houdini load your checkout instead of a copy, run
`.venv/Scripts/hocuspocus install-houdini --dev`, then restart Houdini. On Linux and
macOS the path is `.venv/bin/...`.

## How to add a tool

1. **Bible.** Add the tool to the right table in `docs/BIBLE.md` §4, and update the
   count in §4.7.
2. **Spec file.** Create `src/hocuspocus/tools/spec/<name>.py`, named after the tool,
   exporting `SPEC = ToolSpec(...)` built with the helpers in `spec/_helpers.py`
   (`from ._helpers import ToolSpec, _obj, _s, ...`; a helper that two tools share goes
   there too). Add the module name to `ORDER` in `spec/__init__.py` where the tool belongs:
   that list, not the directory, is the order of `tools/list`, `docs/tools.md` and
   `hocuspocus://tools`. `catalog.py` only loads the specs and owns the profile sets; do
   not define tools in it. The spec has:
   - `name`, in snake_case, equal to the module name.
   - A `description` of at most 60 words: what the tool does and what the model needs to
     choose it. Defaults belong in the schema (`default`), not the description.
   - `notes` for argument-level detail (shapes the schema cannot state, edge cases). They
     are rendered into `docs/tools.md` and `hocuspocus://tools` but not sent in
     `tools/list` (BIBLE §4.1).
   - `input_schema`, built with `_obj` / `_s` / `_enum` / ... from `spec/_helpers.py`,
     with `additionalProperties: false`.
   - An `output_schema` if the shape is stable. The bridge declares it only when
     `result_content` is `both` or `structured`; with the default `text` the model sees
     just the description and the result JSON in the text block (BIBLE §4.1), so put
     anything the model must know about the result in the description.
   - Argument `description`s of at most 12 words, checked by
     `test_argument_detail_lives_in_notes`. Say what the argument is in the schema, and
     put how it behaves (shapes, edge cases, interactions with other arguments) in
     `notes`. A new feature then adds only its name and type to `tools/list`, not its
     explanation.
   - `read_only` / `destructive` / `idempotent`, `profile`, and `headless_ok`. `profile`
     is `core` or `full`. The `minimal` profile (BIBLE §4.1) is the `MINIMAL_TOOLS` set in
     `catalog.py`. Add a tool to it only when a small-context client cannot work without
     it, and update BIBLE §4.1 and `test_profiles` in the same change.
   - At least one entry in `examples`.

   The bridge registers the tool from this spec, so it shows up in `tools/list`
   straight away.
3. **Host implementation.** In the family module under `src/hocuspocus/host/tools/`,
   write:

   ```python
   from .registry import tool

   @tool("my_tool")
   def my_tool(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
       ...
   ```

   - The function runs on Houdini's main thread, inside one undo group if the tool
     mutates.
   - Raise `ToolError(code, message, hint=..., candidates=...)` for user mistakes. Use
     only codes from `tools/errors.py` (BIBLE §9).
   - Register with `scene=False` when the dispatcher's undo group, read-only refusal or
     dirty marking would be wrong for the tool: `performUndo` raises inside an undo
     group (`undo`); reads must not dirty the scene (`time`, `selection`, `hda list`);
     cooks, work items, renders and jobs are not hip state (`cook`, `pdg`, `render`,
     `job`). Where such a tool changes the scene it does the dispatcher's work itself:
     the read-only refusal, its own `hou_undo_group`, and `ctx.scene.mark_dirty()`. Its catalogue entry stays
     `read_only=False`, with `idempotent=True` if repeating it is harmless (BIBLE §4.1).
     The `scene=False` set is pinned in `tests/unit/test_host_tools.py`.
   - Add `main_thread=False` only for tools that wait on jobs or never touch `hou`;
     they reach `hou` through `ctx.executor.run(...)`.
   - Tools that create or change nodes call `watch_nodes(...)` from `nodes.py` after
     their own changes, so `events` reports later edits to those nodes.
   - A new module must also be added to `TOOL_MODULES` in `host/tools/registry.py`.
   - Leave instance tagging to the bridge (BIBLE §3.3 rule 3). It adds
     `_meta.instance: {pid, label, name?}` to every result a host answers. When several
     Houdinis run and none is pinned, it refuses a call that changes a scene with
     `ambiguous_instance` and adds `_instance: {pid, label, ui, warning}` to the result
     of a read it sent to a guessed instance. A host tool never writes these keys, so
     do not name a result field `_instance`. A `read_only` tool always counts as a read.
     A `scene=False` tool with reading forms (an `action: list`, or no arguments) must
     add them to `READ_ACTIONS` or `READ_WITHOUT` in `bridge/server.py` and to
     `test_which_calls_count_as_changing_a_scene` in `tests/unit/test_bridge_multi.py`.
     Otherwise its reads are refused too. A tool that starts a job gets a
     `<pid>-<id>` job id from the job manager, which the bridge routes by pid (BIBLE §7).
4. **Integration test.** Add a test in `tests/integration/test_<family>.py` that calls
   the tool through the real host (see `tests/integration/conftest.py`) against real
   nodes. Cover the error path and any Houdini idiom from BIBLE §5 that the tool
   touches.
5. **Regenerate the docs and the budget report.** Run `.venv/Scripts/hocuspocus docs
   tools`, or `.venv/Scripts/python -m hocuspocus.tools.docs`, and commit `docs/tools.md`.
   Then run `.venv/Scripts/python -m hocuspocus.tools.docs --budget` and commit
   `docs/redesign/budget.md`: it measures the serialised `tools/list` for every profile ×
   `result_content` mode, appends a dated row to the history (keep the old rows) and
   rewrites the table of the ten largest tools. Say in the commit why any number went up
   (spec-2.0 principle 13). Never edit either file by hand; `hocuspocus://tools` is
   rendered from the same specs by `tools/docs.py` at run time.
6. **Unit guard.** Run `pytest tests/unit`. `tests/unit/test_catalog.py` checks the new
   entry:
   - The name is unique and snake_case, the module is named after the tool, and `ORDER`
     lists every spec module once.
   - The description stays under the word cap, and every argument description is 12
     words or fewer.
   - The schema shape and annotations are valid.
   - The examples validate.
   - The serialised `tools/list` result of the full profile stays within two caps
     (`test_tools_list_budget`, BIBLE §4.1). What clients see by default,
     `result_content = "text"` (no output schemas), stays at 32,000 bytes or less. The
     `both` shape, with output schemas declared, stays at 44,000 bytes or less. The test
     prints all six sizes, the three profiles in each mode, even on success. When a new tool pushes either one over, move argument detail from the
     description into `notes` before cutting words the model needs to choose the tool.
     Never remove a tool or an argument to make room.
   - `docs/tools.md` is current, and the latest row of `docs/redesign/budget.md` is the
     current measurement.

   `tests/unit/test_catalog_goldens.py` compares the serialised `tools/list` of every
   profile × mode byte for byte with `tests/unit/goldens/`. A new tool changes them on
   purpose: rewrite them with `.venv/Scripts/python tests/unit/test_catalog_goldens.py
   --write` in the same commit and say why the bytes changed.

   `tests/unit/test_host_tools.py` checks that every `@tool` name exists in the
   catalogue. If the tool should always be registered, add its name to the list in
   `test_registered_host_tools_exist_in_catalogue`.

## Running tests

There are three tiers (see `docs/BIBLE.md` §11). Tests never write into the repository
or into your real Houdini preferences, and they never use port 37219.

| Tier | Runs in | Command | Budget |
|---|---|---|---|
| `tests/unit` | system Python | `.venv/Scripts/python -m pytest tests/unit -q` | about 10 s |
| `tests/integration` (fast, the default) | hython | see below | < 90 s |
| `tests/integration` (`slow`) | hython | the same command with `-m slow` (or `--runslow` for both) | about 3 min |
| `tests/integration/test_parity_gui.py` (`gui`, the GUI column of [`parity.md`](parity.md)) | system Python launching `houdinifx` (isolated prefs; a window opens and closes) | `.venv/Scripts/python -m pytest tests/integration/test_parity_gui.py --rungui -q` | about 30 s |
| `tests/e2e` | system Python spawning hython | `.venv/Scripts/python -m pytest tests/e2e -q` | < 60 s |

When no hython can be found, the `houdini` and `e2e` tests skip. hython is found through
`HOUDINI_HYTHON`, `$HFS/bin`, or the newest `Side Effects Software/Houdini 22.*`. This
lets contributors without a licence get a green run.

### Lint and unit tests (system Python, no Houdini)

```bash
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format src tests              # CI runs `ruff format --check src tests`
.venv/Scripts/python -m pytest tests/unit -q      # Linux/macOS: .venv/bin/python
```

### Integration tests (inside `hython`)

The integration tier runs **inside** hython against a real Houdini session. It needs
three things:

1. **pytest importable from hython.** Install it once into a scratch directory outside
   the repository:

   ```bash
   "$HFS/bin/hython" -m pip install --target "$SCRATCH/hy-deps" pytest pytest-timeout
   ```

2. **An isolated Houdini pref dir.** `HOUDINI_USER_PREF_DIR` must:
   - contain the `__HVER__` token, because Houdini ignores the variable otherwise;
   - not be your real `~/houdini22.0`. The integration `conftest.py` refuses to run
     against the real one.

   Houdini expands `__HVER__`, so files Houdini or the host read from that pref dir live
   in the expanded directory. To run a host with the `full` profile from such an
   isolated pref dir (an evaluation, or `hocuspocus launch` against it), put
   `hocuspocus.toml` with `profile = "full"` in `$SCRATCH/prefs/houdini22.0/`. A copy
   in a literal `houdini__HVER__/` directory is never read (review 13);
   `hocuspocus doctor` prints which file the bridge reads. The integration fixture
   passes `profile="full"` to its host itself and needs no toml.

3. **A neutral working directory.** hython puts its cwd on `HOUDINI_PATH`, so run it
   from an empty temporary directory, not from the repository.

Git Bash on Windows (`$SCRATCH` is any temporary directory):

```bash
mkdir -p "$SCRATCH/cwd" && cd "$SCRATCH/cwd"
HOUDINI_USER_PREF_DIR="$(cygpath -m "$SCRATCH")/prefs/houdini__HVER__" \
PYTHONPATH="$(cygpath -m "$SCRATCH")/hy-deps;C:/path/to/hocus-pocus/src" \
PYTHONDONTWRITEBYTECODE=1 \
"/c/Program Files/Side Effects Software/Houdini 22.0.466/bin/hython.exe" \
  -m pytest C:/path/to/hocus-pocus/tests/integration -q -p no:cacheprovider \
  --rootdir C:/path/to/hocus-pocus
```

PowerShell equivalent:

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\hp-it\cwd" | Out-Null
Set-Location "$env:TEMP\hp-it\cwd"
$env:HOUDINI_USER_PREF_DIR = "$env:TEMP\hp-it\prefs\houdini__HVER__"
$env:PYTHONPATH = "$env:TEMP\hp-it\hy-deps;C:\path\to\hocus-pocus\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& "C:\Program Files\Side Effects Software\Houdini 22.0.466\bin\hython.exe" `
  -m pytest C:\path\to\hocus-pocus\tests\integration -q -p no:cacheprovider `
  --rootdir C:\path\to\hocus-pocus
```

#### Fast and slow

A plain run is the **fast** set. On the 1.3 release machine it is 386 tests in about 50 s,
under the 90 s budget. `tests/conftest.py` deselects tests marked `@pytest.mark.slow`
unless you ask for them. The slow set is 60 tests and about 3 minutes:

- visual child renders and `render` tests;
- LOP and stage captures, and Karma;
- PDG cooks (all of `test_pdg.py`);
- the 1M-point geometry tests;
- tests that wait out a timeout on purpose.

To choose a set, add one of these to the command above:

- `-m slow` runs only the slow set.
- `--runslow` runs both sets.
- Any `-m` expression that names `slow`, such as `-m "not slow"`, decides on its own.

Mark a new test `@pytest.mark.slow` when it takes over about 1.5 s. Measure with
`--durations=30`. Keep the fast set under 90 s, because it is the run before every commit
that touches `host/`. Run `--runslow` before you merge, and always after changing
rendering, capture, PDG or job code. CI runs the two sets as separate steps of
`houdini.yml`.

How the session fixture works:

- It starts one in-process host with isolated `HOCUSPOCUS_STATE_DIR` and pref dirs.
- Every call goes through the real HTTP server with the real token.
- The scene is cleared before each test.
- One test also launches `hython -m hocuspocus.host --port 0` as a subprocess, from a
  temporary cwd, and shuts it down over HTTP.

If you run the integration modules with system Python instead, they skip themselves,
because `hou` is not importable.

### End-to-end tests

The e2e tier runs in the dev venv. It does the following:

1. Spawns `hython -m hocuspocus.host` with an isolated `HOCUSPOCUS_STATE_DIR` and
   `HOUDINI_USER_PREF_DIR` from a temporary cwd.
2. Starts `hocuspocus-mcp` over stdio.
3. Drives the bridge with the official `mcp` client.

Point it at hython if it is not auto-detected:

```bash
HOUDINI_HYTHON="C:/Program Files/Side Effects Software/Houdini 22.0.466/bin/hython.exe" \
  .venv/Scripts/python -m pytest tests/e2e -q -p no:cacheprovider
```

### Workloads tier

`tests/workloads/` scripts the evaluation workloads as tests (spec-2.0 §5.2) and measures
what an agent pays for them. It is deselected by default; run it in the dev venv with:

```bash
.venv/Scripts/python -m pytest tests/workloads --runworkloads -q -s -p no:cacheprovider
```

(`-m workload` also selects it.) Like e2e, it needs hython and skips without one. One
session fixture starts one headless host (`hython -m hocuspocus.host`) with isolated
`HOCUSPOCUS_STATE_DIR`, `HOUDINI_USER_PREF_DIR` (`prefs/houdini__HVER__`, with
`profile = "full"` in `prefs/houdini22.0/hocuspocus.toml`), work and temp dirs and a
neutral cwd, all under pytest's temporary directory, and keeps one official `mcp` client
session to the stdio bridge open for all five workloads. Between workloads it re-pins the
host, cancels running jobs, runs `hip_new {on_unsaved: discard}` and deletes the
workload's files (caches stay under 300 MB each).

| Workload | Source | What it does | Time here |
|---|---|---|---:|
| `test_city_build` | review 12 | building generator with `node_edit spare_parms`, the city's for-each loop in one `node_create`, `OUT_CITY`, `cook profile`, one capture | ~5 s |
| `test_scorecard_twelve` | review 21 | the twelve tasks: 2.4 at frame 24, three mistakes with candidates, `unsaved_changes`, `instance_lost` after a kill and a relaunch | ~8 s |
| `test_soak_200` | review 22 | 200 calls from seed 22: the weighted mix, scheduled samples, saves, captures, canary cooks, a cancelled and a finished cook job, a `hip_open`, one-shot bridges; no leaked nodes or jobs, read p95 < 250 ms | ~20 s |
| `test_fx_cache` | review 20 | a small pyro sim cached by `render` on `filecache::2.0` (24 frames, polled job), volumes read back, one capture | ~3 s |
| `test_vellum_usd` | review 24 | Vellum cloth cached for 24 frames, `usd_rop` export by `render`, `sublayer` read-back with 24 time samples, a 320×180 Karma frame | ~17 s |

The whole tier takes about a minute on the 1.4 release machine (budget: 12 minutes).

Each test wraps `call_tool` in a `Recorder` that keeps, per call, the tool, args bytes,
text bytes (the JSON text block the model reads; images are counted apart), elapsed time
and `isError`, and per workload the calls, text bytes, largest call, wall time and time to
the first image. Text bytes are counted with the session's temporary root replaced by
`<tmp>`, so budgets do not depend on the temp path. Job polls are not recorded (only the
final `job status`), so call counts do not depend on machine speed.

**Budgets.** `tests/workloads/budgets.json` holds `calls`, `text_bytes`, `max_call_bytes`
and `wall_s` per workload, recorded from 1.4 (the larger of two runs). A workload fails
when any of them is more than 15 % over its budget, or on any error it did not expect.
Every run writes its measurements, per tool as well, to `tests/workloads/last_run.json`
(not committed). A change that raises bytes or calls per workload must say why (spec-2.0
principle 13); when the rise is intended, re-record with
`--update-budgets` (it rewrites the entries of the workloads that ran) and commit the new
`budgets.json` with the change. Record wall time from a full-tier run: run alone, a
workload can pay the capture child's 3 s start that the full run spreads differently.

To add a workload, write `tests/workloads/test_<name>.py` that takes the `workload`
fixture, drives tools only through it (`rec.ok`, `rec.error(code=...)`, `rec.wait_job`,
`rec.path(...)` for files), asserts the outcomes the evaluation verified, and ends with
`rec.finish()`; then record its budget.

`.github/workflows/houdini.yml` runs the tier nightly and on manual dispatch (not on
labelled PRs) and uploads `last_run.json`. Run it yourself before every tag.

### CI

- `.github/workflows/ci.yml` runs on every push and PR, on `windows-latest` and
  `ubuntu-latest`. It runs `ruff check`, `ruff format --check`, the unit tier, and a
  check that `docs/tools.md` is fresh. It does not need Houdini.
- `.github/workflows/houdini.yml` runs the integration tier twice (the fast set, then
  `-m slow`) and the e2e tier. It needs a
  **self-hosted runner labelled `houdini`** with a licensed Houdini 22. It runs nightly,
  on manual dispatch and on PRs labelled `houdini`.

## Debugging the host

**The host log.** Each host writes `<state_dir>/logs/host-<pid>.log` (rotating, 5 MB, two
backups; `<state_dir>` is `%LOCALAPPDATA%\HocusPocus` on Windows unless
`HOCUSPOCUS_STATE_DIR` says otherwise). Since 1.4 every tool call adds one INFO line
(BIBLE §3.2):

```text
2026-10-13 22:24:01,512 INFO hocuspocus.host: call node_create 231 ms main 228.4 ms ok pid 60396
```

The fields are the tool, the elapsed ms, the ms on Houdini's main thread, `ok` or the
error `code`, and the host pid. The same split is in every result's `_meta.timing`
(`main_thread_ms`, `queue_ms`), and mutation rows carry `cook_ms`: a slow call whose
`main_thread_ms` is mostly `cook_ms` is Houdini cooking, not HocusPocus. Failures that
reach `internal` also log their traceback at ERROR.

**The kept capture child.** Headless, the first Flipbook `viewport_capture` starts a child
hython that stays up and renders every later capture (about 0.4 s instead of 3 s; BIBLE §8,
D33). Its work dir is a `hp-warm-*` directory under the system temp dir, with its log in
`child.log` there. It is replaced when the child script, the hython or an installed HDA
library changes, after 200 captures (`WARM_MAX_USES`) or 110 s idle, and it exits by
itself after 120 s idle (`WARM_IDLE_S`) or when the host goes away. When you debug a
capture, remember that a later capture runs in that kept process, not in a fresh one:

- There is no config key or environment variable for it. To send every capture to a fresh
  child, set the module constant in the host process, for example through
  `houdini_python`: `import hocuspocus.host.tools.visual as v; v.WARM_CAPTURES = False`.
  Set it back to `True` to re-enable it.
- `v.close_warm_capture()` stops the kept child; the next capture starts a new one. The
  integration tests call it before they time a cold capture.
- If a kept child that had already rendered crashes, the capture is retried in a fresh
  child with a note, and kept children stay off for the rest of that host session.
- `render` of a user's Flipbook or OpenGL ROP, the OpenGL step of the capture chain and a
  capture while the kept child is busy always use a fresh child; the Karma step renders in
  the host itself.

## Release

1. Bump the version in both `pyproject.toml` (`[project] version`) and
   `src/hocuspocus/version.py` (`__version__`). They must match: `doctor` compares the
   host's `version.py` with the bridge's, and `install-houdini` installs into
   `<prefs>/hocuspocus/<version>/`.
2. In `CHANGELOG.md`, turn the `Unreleased` section into `## X.Y.Z (YYYY-MM-DD)` and add
   a new empty `Unreleased` section above it.
3. Run the unit tier, and the integration and e2e tiers on a machine with Houdini.
   Regenerate `docs/tools.md` if the catalogue changed.
4. Commit, then tag and push the tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. Build the sdist and wheel into `dist/`. The wheel includes the `houdini/` payload as
   `hocuspocus/_houdini`.

   ```bash
   uv build
   ```

6. Publish to PyPI. This needs a PyPI API token in `UV_PUBLISH_TOKEN`:

   ```bash
   UV_PUBLISH_TOKEN=pypi-... uv publish
   ```

7. Create a GitHub release for the tag with the changelog section as notes and the wheel
   attached, for example
   `gh release create vX.Y.Z dist/hocuspocus-X.Y.Z-py3-none-any.whl --notes-file <notes>`.

After the first PyPI release, update the install instructions in `README.md`,
`docs/quickstart.md` and BIBLE §10.2 to `uv tool install hocuspocus`.

## Commit conventions

- Use an imperative, sentence-case subject of 72 characters or less, with no trailing
  period. Examples: "Implement cook and problems", "Delete the 0.9 tree".
- In the body, explain *why*, and reference BIBLE sections where relevant.
- Keep each commit to one logical change. Don't mix generated `docs/tools.md` churn with
  unrelated edits.
- `ruff check src tests`, `ruff format --check src tests` and `pytest tests/unit` must
  pass at every commit. Run the
  integration tier before you merge anything that touches `host/`.
- Never commit test or runtime state (`.hocuspocus/`, captures, `__pycache__`).
- When a milestone from BIBLE §14 lands, add a line to `docs/redesign/progress.md`.

### Several people, one checkout

When several people or agents commit from the same working tree (as the 1.1 streams
did), the index is shared and a commit takes whatever is staged, including someone
else's half-finished files or an index read before their last commit:

- Stage only your own changes, by explicit path (`git add docs/BIBLE.md src/...`) or
  hunk by hunk with `git add -p`. Never `git add -A`, `git add .` or `git commit -a`.
- Run `git status` and `git diff --cached` right before committing, and never commit
  from a stale index: if a file you edited was committed or changed by someone else
  since you read it, re-read it and reapply your edit on top. Committing an old copy
  silently reverts their commit (1.1 needed `1d21a40` and `51500d8` to restore such
  reverts).
- Keep shared files such as `docs/BIBLE.md` and `docs/tools.md` to small, separate
  commits, and regenerate `docs/tools.md` from the current catalogue just before
  committing it.
