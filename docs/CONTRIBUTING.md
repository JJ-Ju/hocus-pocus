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
  cli.py                       # install-houdini, uninstall-houdini, doctor, client-config, docs, version
  tools/                       # shared by host and bridge; stdlib only
    catalog.py                 #   the single source of truth for the tool surface
    errors.py                  #   error codes and ToolError
    docs.py                    #   renders docs/tools.md; tools/list size; example validator
    paths.py                   #   state dir (instances/, logs/, captures/)
  host/                        # INSIDE Houdini; stdlib only; imports hou lazily
    __init__.py                #   start(), stop(), status(), autostart()
    __main__.py                #   hython -m hocuspocus.host
    config.py executor.py server.py dispatch.py runtime.py registry.py jobs.py budget.py undo.py
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
  redesign/review/*.md  redesign/progress.md
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
2. **Catalogue entry.** Add a `ToolSpec` to `src/hocuspocus/tools/catalog.py` with:
   - `name`, in snake_case.
   - A `description` of at most 80 words, with defaults stated.
   - `input_schema`, built with `_obj` / `_s` / `_enum` / ... and
     `additionalProperties: false`.
   - An `output_schema` if the shape is stable.
   - `read_only` / `destructive` / `idempotent`, `profile`, and `headless_ok`.
   - At least one entry in `examples`.

   The bridge registers the tool from this entry, so it shows up in `tools/list`
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
   - Use `main_thread=False, scene=False` only for tools that never touch `hou`.
   - A new module must also be added to `TOOL_MODULES` in `host/tools/registry.py`.
4. **Integration test.** Add a test in `tests/integration/test_<family>.py` that calls
   the tool through the real host (see `tests/integration/conftest.py`) against real
   nodes. Cover the error path and any Houdini idiom from BIBLE §5 that the tool
   touches.
5. **Regenerate the docs.** Run `.venv/Scripts/hocuspocus docs tools`, or
   `.venv/Scripts/python -m hocuspocus.tools.docs`, and commit `docs/tools.md`. Never
   edit that file by hand.
6. **Unit guard.** Run `pytest tests/unit`. `tests/unit/test_catalog.py` checks the new
   entry:
   - The name is unique and snake_case.
   - The description stays under the word cap.
   - The schema shape and annotations are valid.
   - The examples validate.
   - Total `tools/list` text stays at 48 KB or less.
   - `docs/tools.md` is current.

   `tests/unit/test_host_tools.py` checks that every `@tool` name exists in the
   catalogue. If the tool should always be registered, add its name to the list in
   `test_registered_host_tools_exist_in_catalogue`.

## Running tests

There are three tiers (see `docs/BIBLE.md` §11). Tests never write into the repository
or into your real Houdini preferences, and they never use port 37219.

| Tier | Runs in | Command | Budget |
|---|---|---|---|
| `tests/unit` | system Python | `.venv/Scripts/python -m pytest tests/unit -q` | < 10 s |
| `tests/integration` | hython | see below | < 90 s |
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

### CI

- `.github/workflows/ci.yml` runs on every push and PR, on `windows-latest` and
  `ubuntu-latest`. It runs `ruff check`, `ruff format --check`, the unit tier, and a
  check that `docs/tools.md` is fresh. It does not need Houdini.
- `.github/workflows/houdini.yml` runs the integration and e2e tiers. It needs a
  **self-hosted runner labelled `houdini`** with a licensed Houdini 22. It runs nightly,
  on manual dispatch and on PRs labelled `houdini`.

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
