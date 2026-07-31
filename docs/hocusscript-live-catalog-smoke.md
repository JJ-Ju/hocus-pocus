# HocusScript Live Catalog Smoke

Run this gate under a fresh `hython` process, never through the Houdini MCP request path. The exporter accepts an explicit HocusScript project directory and writes only the project-contained catalog path declared by manifest v2.

```powershell
$hython = "C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe"
& $hython scripts/export_houdini_catalog.py --project tests/fixtures/hocusscript/live_project
```

## Stable-capture gate

1. Export once and retain the emitted fingerprint plus a temporary copy of the generated catalog.
2. Start a second fresh `hython` process and export the unchanged installation again.
3. Require the fingerprints and canonical catalog bytes to match.
4. Decode both through `decode_catalog_snapshot()`; a serializer-only hash is insufficient.
5. Remove generated smoke catalogs after recording counts, build, platform, elapsed time, and fingerprints.

## Meaningful-change gate

In a fresh headless scene:

1. Capture the baseline catalog.
2. Create a temporary SOP subnet HDA named `hocus::catalog_smoke::1.0` in a temporary library.
3. Add a strict float parameter token `smoke_scale`.
4. Capture again and require one additional exact operator, the authored parameter metadata, and a changed fingerprint.
5. Destroy the temporary host network, uninstall the temporary library, and delete the temporary directory.

## Recorded evidence: 2026-07-11

- Houdini `21.0.729`, platform `windows-x86_64-cl19.42`
- unchanged captures: 5,156 operators, fingerprint `sha256:534a71cee3aa2bb35aeb804a62f4831f97a6433683ed7fc8fcaeea5780f6ca4d`
- temporary-HDA capture: 5,157 operators, fingerprint `sha256:c82d7f417f2a40a76349d25e7c6b1ce562364b5e8791245f66d64fce65ebfc05`
- `hocus::catalog_smoke::1.0` appeared exactly once and retained `smoke_scale`
- generated snapshot size was approximately 44 MB and remained below the 64 MB catalog boundary

HOM may emit operator-definition warnings while enumerating installed COP assets. Warnings alone do not pass or fail the gate; strict extraction, canonical decoding, fingerprint equality/change, and cleanup determine the result.
