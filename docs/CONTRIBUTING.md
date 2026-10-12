# Contributing to HocusPocus

## Running tests

Three tiers (see `docs/BIBLE.md` §11). Tests never write into the repository or into
your real Houdini preferences, and never use port 37219.

### Lint and unit tests (system Python, no Houdini)

```bash
uv venv .venv
uv pip install -p .venv -e ".[dev]"
.venv/Scripts/python -m pytest tests/unit -q      # Linux/macOS: .venv/bin/python
.venv/Scripts/ruff check src tests
```

### Integration tests (inside `hython`)

The integration tier runs **inside** hython against a real Houdini session. It needs:

1. **pytest importable from hython.** Install it once into a scratch directory, outside
   the repository:

   ```bash
   "$HFS/bin/hython" -m pip install --target "$SCRATCH/hy-deps" pytest pytest-timeout
   ```

2. **An isolated Houdini pref dir.** `HOUDINI_USER_PREF_DIR` must contain the `__HVER__`
   token (Houdini ignores the variable otherwise) and must not be your real
   `~/houdini22.0`; the integration `conftest.py` refuses to run against the real one.

3. **A neutral working directory.** hython puts its cwd on `HOUDINI_PATH`, so starting it
   from the repository root would auto-run the repository's 0.9 `scripts/python/pythonrc.py`.

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

The session fixture starts one in-process host with isolated `HOCUSPOCUS_STATE_DIR` and
pref dirs, sends every call through the real HTTP server with the real token, and clears
the scene before each test. One test also launches `hython -m hocuspocus.host --port 0`
as a subprocess (from a temporary cwd) and shuts it down over HTTP.

Run with system Python instead, the integration modules skip themselves (`hou` is not
importable), and `houdini`/`e2e` tests skip when no hython can be found
(`HOUDINI_HYTHON`, `$HFS/bin`, or the newest `Side Effects Software/Houdini 22.*`).
