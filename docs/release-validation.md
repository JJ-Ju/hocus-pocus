# HocusPocus Release Validation

This document defines the minimum validation gates for a build to be treated as aligned, installable, and releasable. These are qualification gates, not the normal active-development loop; during implementation, run Ruff plus the narrowest relevant behavior or user-workflow smoke. The complete repository catalogue must remain at or below 50 public scenarios.

## 1. Build Alignment Rule

Before claiming a slice is complete:

- the repo changes must be committed or clearly identified as uncommitted work
- the installed Houdini package must be rebuilt from the current repo state
- Houdini must be restarted if the running process had older Python modules loaded

## 2. Required Validation Gates

### Gate A. Build and Install

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Required result:

- staged package created successfully
- installed package updated successfully

### Gate B. Lint and Compile

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\lint.ps1
python -m compileall python3.11libs\hocuspocus
```

Required result:

- Ruff reports no correctness violations
- the test catalogue remains at or below the enforced 50-test ceiling
- no compile failures

### Gate C. Startup

Required result in a real Houdini `21.x` session:

- package loads
- server auto-starts
- `hocuspocus.server_status()` reports `running: True`

### Gate C1. Offline HocusScript Tests

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Required result:

- all four public scenario suites pass once
- preview compilation remains non-mutating and reports `readyForApply = false`
- authoring, project/module, control/apply, and runtime workflows remain intact

### Gate D. Live Smoke

Run the scripted smoke:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_live_server.ps1
```

Required result:

- health passes
- core discovery passes
- live mutation probe passes
- graph/resource probe passes
- task/export/packaging probes pass when their target fixtures are available

### Gate E. Installed/Committed Consistency

Required result:

- the installed package behavior matches the committed branch state
- no known stale in-memory module mismatch remains in the running Houdini session

## 3. Reporting Rule

Validation reports should clearly separate:

- compile/build checks
- local repo-only checks
- live Houdini checks
- installed-versus-committed caveats

## 4. Optional Domain Fixtures

Some smokes depend on disposable scene fixtures, for example:

- Solaris nodes under `/stage`
- PDG graphs under `/tasks`
- render/export/package probe nodes

These are optional unless the current slice changed those domains. If a slice changes one of those areas, its corresponding live smoke becomes required.
