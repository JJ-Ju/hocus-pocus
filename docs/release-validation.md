# HocusPocus V1 Release Validation

Status: executable checklist for V1 release candidates

This is the minimum qualification sequence for calling a build aligned,
installable, or released. It is deliberately split into mutable pre-freeze
work, immutable-candidate qualification, and external release authority.
Passing repository or same-host gates proves technical readiness only. It does
not replace an externally authenticated clean-image/VM decision or independent
human visual approval.

The staged ownership and claim boundaries are defined in
`docs/hocusscript-roadmap-completion-plan.md`. During active implementation,
run Ruff plus the narrowest relevant workflow. Run this complete checklist only
at a stabilized candidate boundary.

Exact Houdini `22.0.368` is the sole supported and release-qualifying live
runtime for V1. A run under any other build, including Houdini `21.x`, cannot
produce current candidate evidence.

## 1. Current public workflow catalogue

The full suite is six files and 43 public workflows:

| File | Workflows |
| --- | ---: |
| `tests/test_hocusscript_authoring_scenarios.py` | 8 |
| `tests/test_hocusscript_control_scenarios.py` | 8 |
| `tests/test_hocusscript_hs8_scenarios.py` | 3 |
| `tests/test_hocusscript_project_scenarios.py` | 10 |
| `tests/test_hocusscript_workspace_scenarios.py` | 6 |
| `tests/test_runtime_scenarios.py` | 8 |

`scripts/lint.ps1` enforces the repository ceiling of 50 public workflows,
the 1,200-physical-line limit, Ruff, the configured complexity ceilings, and
the prohibition on complexity suppressions. Do not describe the suite as four
suites, 34 workflows, or 40 workflows.

Commands below use these operator-supplied values:

```powershell
$Hython = "<absolute-path-to-Houdini-22.0.368-hython.exe>"
$HoudiniUserPrefDir = "<isolated-or-release-houdini22.0-preferences>"
$EvidenceRoot = "<absolute-path-outside-the-repository>"
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null

& $Hython -c "import hou,sys; sys.exit(0 if hou.applicationVersionString() == '22.0.368' else 42)"
if ($LASTEXITCODE -ne 0) {
    throw "Release qualification requires exact Houdini 22.0.368."
}
```

Do not place release evidence inside the source tree. Offline receipt commands
require an existing external directory and publish each receipt exactly once;
they reject overwrite, symlink, and reparse-point output paths.

## 2. Phase A: mutable pre-freeze gates

Candidate freeze is blocked until every Phase A item passes or the release
claim is explicitly narrowed.

### A1. Diff, lint, compile, full workflows, and build/install

- [ ] Identify every intentional tracked and untracked input:

  ```powershell
  git status --short
  git diff --check
  git diff --cached --check
  ```

- [ ] Run repository policy and static checks:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\lint.ps1
  python -m compileall -q python3.11libs\hocuspocus
  ```

- [ ] Run the six-file, 43-workflow suite exactly once:

  ```powershell
  python -m unittest discover -s tests -p "test_*.py"
  ```

  Required result: 43 tests pass. Do not rerun the same suite under pytest.

- [ ] Build and install from the current source without rotating the token:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 `
    -Clean -Install -HoudiniUserPrefDir $HoudiniUserPrefDir
  ```

  Required result: staging compiles, the governed install manifest verifies,
  and the versioned package is selected by
  `$HoudiniUserPrefDir\packages\hocuspocus.json`.
  Compilation is a validation step only: the distributable and installed trees
  contain no `__pycache__`, `.pyc`, or `.pyo` artifacts, and manifest
  verification rejects any such undeclared executable bytes.

### A2. Performance evidence

- [ ] Record machine identity, OS, Python version, real `hython`-derived
  Houdini identity, cold/warm
  catalogue policy, repetition count, and raw bounded samples.
- [ ] Measure 100-node preview p50 and p95 against the 250 ms target.
- [ ] Measure a representative 1,000-node compile against the 2 second
  warm-catalogue target.
- [ ] Retain the fixture, raw samples, and canonical summary with content
  digests. V1 makes no 10,000-node performance claim.

Run the deterministic fixture recipe through the warm-catalogue compiler
pipeline and retain its external receipt:

```powershell
python .\scripts\benchmark_hocusscript_release.py `
  --hython $Hython `
  --output (Join-Path $EvidenceRoot "hocusscript-performance.json")
```

The checked-in `scripts/fixtures/release/performance-fixtures.json` recipe
generates the representative 100-node and 1,000-node linear graphs. The
100-node operation runs source compilation, semantic resolution, authenticated
Bundle construction, document lowering, and deterministic diff/candidate-plan
creation against a fixed baseline. The 1,000-node operation retains the
source-to-semantic-graph compile target. The receipt binds these pipeline
names, the exact fixed-baseline digest, fixture and generated source digests,
raw samples, p50/p95 summaries, catalogue fingerprint/policy, environment,
exact workspace snapshot, and target decisions. The benchmark pipeline is
offline; Houdini product/build identity is derived by executing the supplied
real `--hython`, not copied from caller text. Cook timings in
`scripts/smoke_hocusscript_hs8.py` remain separate asset-build evidence.

### A3. Compatibility goldens and mixed-version rejection

- [ ] Run the existing authoring/carrier compatibility coverage:

  ```powershell
  python .\tests\test_hocusscript_authoring_scenarios.py -q
  ```

  This includes the checked-in language `0.1` authoring golden and current
  strict carrier/mixed-version rejection behavior.

- [ ] Retain exact historical decoder fixtures for decoder-only rows and
  execute current native source-to-carrier producers for native rows.
- [ ] For every row, prove exact decoding remains accepted and that
  cross-row field mixing, silent upgrade, and historical-field smuggling
  reject.
- [ ] Bind the golden matrix and its fixture digests to the candidate.

Generate the candidate-bound compatibility receipt:

```powershell
python .\scripts\verify_hocusscript_compatibility.py `
  --output (Join-Path $EvidenceRoot "hocusscript-compatibility.json")
```

`scripts/fixtures/release/compatibility-goldens.json` binds eight supported
exact decoder tuples. Three historical `0.1` rows decode retained exact carrier
fixtures; five current native rows execute source-to-carrier production before
decoding. The runner authenticates each exact carrier and proves cross-row
mixing, silent version upgrade, and historical-field smuggling reject for every
row. This receipt does not claim historical source-to-carrier execution or
project-manifest/project-lock compatibility; those are separate project
workflow claims. The focused authoring scenarios remain current source behavior
coverage.

### A4. Graph-store upgrade compatibility

- [ ] Run the runtime scenarios:

  ```powershell
  python .\tests\test_runtime_scenarios.py -q
  ```

  `test_graph_store_upgrades_existing_documents_without_data_loss` upgrades
  `tests/fixtures/graph_store/v1.sql` and proves retained documents plus
  continued revision behavior.

- [ ] Enumerate every persisted graph-store version promised by V1.
- [ ] Prove a supported upgrade from each promised version to the current
  schema, preserving documents, revisions, plans, commits, and migration
  history as applicable.
- [ ] State that downgrade is unsupported unless a separately implemented
  downgrade contract is qualified.

Generate the supported-upgrade receipt:

```powershell
python .\scripts\verify_graph_store_upgrades.py `
  --output (Join-Path $EvidenceRoot "graph-store-upgrades.json")
```

V1 supports persisted starting versions 1 and 2 upgrading to current schema
version 3. The runner composes the canonical `v1.sql` and `v2.sql` fixtures,
proves preservation of documents, revisions, legacy commits, v2 audit
history, and the migration ledger, then reuses the existing public upgrade
and immutable plan/commit lifecycle scenarios. Graph-store downgrade is
explicitly unsupported in V1.

### A5. Hostile-boundary and live coverage mapping

- [ ] Review `docs/v1-hostile-coverage-map.md`, which maps each V1 boundary to
  its exact existing public workflow and delegated assertion:

  - hostile/recovered source and forged ASTs;
  - traversal, case, alternate-drive, UNC/device, reserved-name, and Unicode
    path handling;
  - symlink, junction/reparse, hardlink, root/component swap, and stale-content
    handling;
  - external-root alias/shadowing and relocation;
  - bundle/carrier tamper and mixed-version rejection;
  - stale plans, cancellation, rollback, restart, and installed live smokes.

- [ ] Run only the focused files needed to repair a demonstrated gap, then run
  the full 43 workflows at the stabilized checkpoint.
- [ ] Add a public workflow only for a distinct uncovered user-visible
  boundary and remain at or below 50.

The checked-in map is the RC1 ownership index. If a changed boundary is absent
or its named assertion no longer proves the claim, repair that precise gap
before candidate freeze.

### A6. Effective Houdini package-search provenance

- [ ] In the exact release Houdini environment, record:

  - every loaded, disabled, or skipped package file, its content digest,
    declared `process_order`, and evaluated condition;
  - expanded package, HDA, Python, and Houdini search paths;
  - the authoritative `HOUDINI_PACKAGE_VERBOSE=1` discovery/processing order,
    including package-path recursion, precedence, and shadowed candidates;
  - the winning internal, native-binary, or HDA identity for every operator;
  - Houdini product, version, build, platform, and feature flags.

- [ ] Bind every catalogue HDA/operator winner and installed HocusPocus root to
  that receipt.
- [ ] Fail on an unexplained loaded definition, ambiguous winner, repository
  import, shadow path, incomplete startup trace, or package file absent from
  that trace. When callable, `hou.ui.packageInfo()` cross-checks the loaded set
  and evaluated values; its dictionary order is never treated as evaluation
  order. Headless Hython may omit that callable: the verbose trace then remains
  authoritative and the receipt records a deterministic empty evaluation
  projection. A callable that throws, returns malformed data, or disagrees with
  the trace still fails closed. `hou.hda.loadedFiles()` entries for absent
  optional-package files or unexplained directory placeholders carry no
  executable byte identity and are ignored. A directory-format HDA is retained
  only when a live operator definition supplies its recursively hashed content
  identity; every byte-addressable loaded HDA must still match the receipt.

The installed HS8 harness calls the private live
`collect_effective_package_search` boundary, immediately re-derives and
verifies the strict receipt, and binds its digest into the technical
qualification. The full receipt is retained in the caller-owned evidence
directory. It is not an MCP filesystem or inspection operation.

## 3. Phase B: freeze the single immutable candidate

- [ ] Confirm Phase A is complete and the worktree contains only intended
  candidate inputs.
- [ ] Commit the exact candidate. Record identities without abbreviating them:

  ```powershell
  $Commit = git rev-parse "HEAD^{commit}"
  $Tree = git rev-parse "HEAD^{tree}"
  git status --short
  ```

  Required result: `$Commit` and `$Tree` are retained, and `git status --short`
  is empty. An uncommitted worktree is not a release candidate.

- [ ] Create and digest the source archive outside the repository:

  ```powershell
  New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
  git archive --format=tar --output "$EvidenceRoot\v1-source.tar" $Commit
  Get-FileHash -Algorithm SHA256 "$EvidenceRoot\v1-source.tar"
  ```

- [ ] Record the exact runner/dependency identities, including:

  ```powershell
  python --version
  powershell -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
  & $Hython -c "import hou; print(hou.applicationVersionString())"
  ```

- [ ] Retain explicit candidate-input JSON outside the repository. The final
  manifest is created after Phase D supplies its install/runtime/technical
  evidence.

Any source, schema, fixture, build script, baseline, review request, or
verification-tool change invalidates the candidate and restarts at Phase A.
Detached external evidence does not change candidate bytes.

## 4. Phase C: prove deterministic build and no-op activation

Run two consecutive installs from the same frozen commit, without
`-RotateToken`, into the same isolated preferences:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 `
  -Clean -Install -HoudiniUserPrefDir $HoudiniUserPrefDir

$PointerPath = Join-Path $HoudiniUserPrefDir "packages\hocuspocus.json"
$Pointer1 = [IO.File]::ReadAllBytes($PointerPath)
$RootName1 = [regex]::Match(
  [Text.Encoding]::UTF8.GetString($Pointer1),
  'HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}'
).Value
$InstalledRoot1 = Join-Path (Split-Path $PointerPath) $RootName1
$Manifest1 = (
  python .\scripts\hs8_install_manifest.py verify --root $InstalledRoot1 |
    ConvertFrom-Json
).manifestDigest
$Config1 = Get-Content (Join-Path $InstalledRoot1 "config\default.toml") -Raw
$Token1 = [regex]::Match(
  $Config1, '(?m)^token\s*=\s*"([A-Za-z0-9_-]{32,128})"\s*$'
).Groups[1].Value

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 `
  -Clean -Install -HoudiniUserPrefDir $HoudiniUserPrefDir

$Pointer2 = [IO.File]::ReadAllBytes($PointerPath)
$RootName2 = [regex]::Match(
  [Text.Encoding]::UTF8.GetString($Pointer2),
  'HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}'
).Value
$InstalledRoot2 = Join-Path (Split-Path $PointerPath) $RootName2
$Manifest2 = (
  python .\scripts\hs8_install_manifest.py verify --root $InstalledRoot2 |
    ConvertFrom-Json
).manifestDigest
$Config2 = Get-Content (Join-Path $InstalledRoot2 "config\default.toml") -Raw
$Token2 = [regex]::Match(
  $Config2, '(?m)^token\s*=\s*"([A-Za-z0-9_-]{32,128})"\s*$'
).Groups[1].Value

if (
  [Convert]::ToBase64String($Pointer1) -cne
  [Convert]::ToBase64String($Pointer2)
) {
  throw "Second install changed the active package pointer."
}
if ($RootName1 -cne $RootName2 -or $Manifest1 -cne $Manifest2) {
  throw "Two builds did not resolve to identical governed installation identity."
}
if (-not $Token1 -or $Token1 -cne $Token2) {
  throw "Second install did not preserve the bearer token."
}
Remove-Variable Config1, Config2, Token1, Token2
```

- [ ] The two governed manifest digests are identical.
- [ ] The versioned install root and active pointer bytes are identical.
- [ ] The bearer token is preserved, is not printed, and is absent from
  manifests/receipts.
- [ ] The second activation is a content no-op and leaves no candidate,
  backup, failed, or abandoned version directory.

The HS8 workflow tests also exercise this transaction in an isolated temporary
preferences directory. The commands above prove it for the actual frozen
candidate.

## 5. Phase D: installed/runtime technical qualification

- [ ] Confirm the exact Houdini `22.0.368` Hython preflight above passed. No
  historical H21 receipt or other Houdini build can satisfy this gate.
- [ ] Restart Houdini so no old Python modules remain loaded.
- [ ] Verify package startup in Houdini's Python shell:

  ```python
  import hocuspocus
  assert hocuspocus.server_status()["running"] is True
  ```

- [ ] Run the broad live server smoke:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\smoke_live_server.ps1
  ```

  Optional Solaris, PDG, render, export, and packaging probes become required
  when the candidate changes their domains and must use disposable fixtures.

- [ ] Run installed HS8 technical qualification twice in isolated Houdini
  processes:

  ```powershell
  python .\scripts\qualify_hocusscript_hs8_clean_process.py `
    --mode technical --hython $Hython --installed-root $InstalledRoot2 `
    --evidence-root $EvidenceRoot
  ```

  Required result: two portable projections are identical; packaging passes;
  review remains `review_pending`; `releaseAuthorized` is false; the active
  pointer selects the installed root; installed governed bytes match the
  source checkout; loaded governed modules match the installed manifest; and
  no repository HocusPocus module is imported.

  On Windows each Houdini child is created suspended, assigned to a
  kill-on-close Job Object, and only then resumed, so timeout and normal cleanup
  contain descendants without a pre-assignment escape window.

  The qualifier captures the verbose trace in a bounded preflight using the
  exact isolated environment, resets writable process state, then launches the
  qualifying process and cross-checks its live package state. With
  `--evidence-root`, the successful unique evidence directory retains
  `effective-package-search.json`; the portable qualification projects only
  its digest.

- [ ] Bind source commit/tree/archive, build manifest, installed manifest,
  active pointer, loaded-module receipts, runtime Houdini build, fixture/output
  digests, and the technical qualification receipt.

The same-host qualifier proves source/install/runtime alignment for its
governed HS8 surface. It is not clean-machine evidence or release authority.

### D2. Create and verify the detached candidate manifest

After Phase D, rerun the three offline receipts on the frozen clean worktree and
retain the exact package-search receipt from the installed qualification. Do
not edit the repository between these runs:

```powershell
python .\scripts\benchmark_hocusscript_release.py `
  --hython $Hython `
  --output "$EvidenceRoot\rc1-performance.json"
python .\scripts\verify_hocusscript_compatibility.py `
  --output "$EvidenceRoot\rc1-compatibility.json"
python .\scripts\verify_graph_store_upgrades.py `
  --output "$EvidenceRoot\rc1-graph-store.json"

python .\scripts\manage_hocusscript_rc1_evidence.py create `
  --performance "$EvidenceRoot\rc1-performance.json" `
  --compatibility "$EvidenceRoot\rc1-compatibility.json" `
  --graph-store "$EvidenceRoot\rc1-graph-store.json" `
  --package-search "$EvidenceRoot\effective-package-search.json" `
  --output "$EvidenceRoot\rc1-evidence-set.json"
python .\scripts\manage_hocusscript_rc1_evidence.py verify `
  --performance "$EvidenceRoot\rc1-performance.json" `
  --compatibility "$EvidenceRoot\rc1-compatibility.json" `
  --graph-store "$EvidenceRoot\rc1-graph-store.json" `
  --package-search "$EvidenceRoot\effective-package-search.json" `
  --evidence-set "$EvidenceRoot\rc1-evidence-set.json"
```

RC1 creation independently recomputes the governed manifest from the frozen
source checkout and requires exact manifest digest and artifact-count equality
with the installed payload recorded by package-search evidence. A structurally
valid receipt from another installed candidate is rejected.

The RC1 generator decodes all four receipts, requires successful internal
results, verifies self/file digests, and requires the three offline receipts to
share the current clean commit/tree and exact tracked-plus-untracked,
nonignored workspace snapshot.

Then place all 15 explicit identities required by
`release-candidate-manifest-v1` in
`$EvidenceRoot\release-candidate-inputs.json`, then run:

```powershell
python .\scripts\manage_hocusscript_release_candidate.py create `
  --inputs "$EvidenceRoot\release-candidate-inputs.json" `
  --rc1-evidence-set "$EvidenceRoot\rc1-evidence-set.json" `
  --output "$EvidenceRoot\release-candidate-manifest.json"

python .\scripts\manage_hocusscript_release_candidate.py verify `
  --manifest "$EvidenceRoot\release-candidate-manifest.json" `
  --expected-inputs "$EvidenceRoot\release-candidate-inputs.json" `
  --rc1-evidence-set "$EvidenceRoot\rc1-evidence-set.json"
```

The manifest binds commit/tree/source archive; runners and dependencies;
fixtures, baseline, review request, and schemas; install manifest, active
pointer, and runtime; and technical, package-provenance, and RC1 evidence.
The CLI refuses repository-local output and overwrite. Its canonical digest is
candidate identity, never release authority.
The candidate verifier decodes the retained RC1 set and cross-checks its
commit, tree, evidence-set digest, package receipt, installed manifest, and
runtime identities rather than accepting an opaque caller-supplied RC1 digest.

## 6. Phase E: external clean-image attestation

- [ ] Create an ephemeral Windows image or VM outside the repository/user
  session.
- [ ] Install the pinned Houdini build and the frozen candidate only from immutable
  inputs.
- [ ] Produce an
  `hs8-clean-image-environment-v1` receipt binding image, runner, source
  snapshot, dependencies, and installed manifest.
- [ ] Inside that boundary, collect technical evidence:

  ```powershell
  $env:HOCUSPOCUS_HS8_CLEAN_IMAGE = "1"
  python .\scripts\qualify_hocusscript_hs8_clean_image.py `
    --environment-receipt <environment-receipt.json> --mode technical `
    --hython $Hython --installed-root <clean-image-installed-root>
  ```

- [ ] Independently verify the external CI signature against a separately
  supplied trust policy and exact retained clean-image bindings:

  ```powershell
  python -m pip install -r .\requirements-release.txt
  python .\scripts\verify_hocusscript_hs8_release_authority.py clean-image `
    --attestation <signed-clean-image-attestation.json> `
    --trust-policy <external-trust-policy.json> `
    --expected-clean-bindings <exact-clean-bindings.json>
  ```

  The signed carrier binds the candidate, source snapshot, installed payload,
  runtime, environment, dependencies, and technical qualification.
- [ ] Recheck exact source/install/runtime identity and effective package-search
  provenance inside the external run.

**External blocker:** the verifier and carrier now exist, but the repository
does not possess an external CI private key or establish the clean image. A
caller-set environment variable, self-digest, or repository fixture still
cannot pass this gate.

## 7. Phase F: detached human visual approval

- [ ] Present the exact baseline, deterministic contact sheet, asset contract,
  numeric report, visual comparison, and relevant named viewport frames to an
  authenticated reviewer. Do not use a full desktop screenshot.
- [ ] Require an external protected workflow to produce a signed detached
  visual-approval carrier outside the repository and installed package,
  binding:

  - candidate provenance manifest digest;
  - output-set and visual-comparison digests;
  - candidate version and named review policy;
  - authenticated reviewer principal, decision, and notes digest;
  - exact frozen review-request and review-evidence digests.

- [ ] Verify the approval against the exact frozen
  `scripts/fixtures/hs8/visual-review-request.json`, output evidence, and
  trusted reviewer policy.
- [ ] Prove the candidate source archive, installed manifest, fixture,
  baseline, and review-request identities remain unchanged.

**External blocker:** the repository contains the baseline and review request,
but no production approval or protected human-approval workflow. Development
fixtures and hand-authored approval JSON do not pass this gate.

## 8. Phase G: release-mode qualification and final decision

- [ ] Run release-mode qualification for the unchanged candidate inside the externally
  authenticated clean image:

  ```powershell
  $env:HOCUSPOCUS_HS8_CLEAN_IMAGE = "1"
  python .\scripts\qualify_hocusscript_hs8_clean_image.py `
    --environment-receipt <environment-receipt.json> --mode release `
    --visual-review <signed-visual-approval.json> `
    --trust-policy <external-trust-policy.json> `
    --hython $Hython --installed-root <installed-root>
  ```

- [ ] Verify that clean-image, human-review, packaging, and publish decisions
  bind the same frozen candidate and exact output evidence.
- [ ] Obtain the final signed release decision from the trusted external
  authority.
- [ ] Verify it with the exact final bindings, which repeat the seven
  clean-image bindings and add the detached visual-approval digest:

  ```powershell
  python .\scripts\verify_hocusscript_hs8_release_authority.py release `
    --clean-image-attestation <signed-clean-image-attestation.json> `
    --visual-approval <signed-visual-approval.json> `
    --final-decision <signed-final-release-decision.json> `
    --trust-policy <external-trust-policy.json> `
    --expected-final-bindings <exact-final-bindings.json> `
    --expected-review-request <exact-review-request.json> `
    --expected-review-evidence <exact-review-evidence.json> `
    --release-candidate-manifest "$EvidenceRoot\release-candidate-manifest.json" `
    --expected-candidate-inputs "$EvidenceRoot\release-candidate-inputs.json" `
    --rc1-evidence-set "$EvidenceRoot\rc1-evidence-set.json" `
    --release-channel v1-production
  ```
- [ ] Confirm the verifier rejects any review request not named by the verified
  release-candidate manifest and any request/evidence candidate, output, or
  review-policy mismatch. Production verification always uses current UTC;
  deterministic time injection exists only in library-level tests.
- [ ] Confirm the final candidate, source archive/snapshot, dependency set,
  installed manifest, runtime, and technical-qualification identities are exact
  projections of the independently verified release-candidate manifest. A
  separately signed but internally consistent set of replacement digests must
  fail.
- [ ] Confirm tag, commit, tree, source archive, install manifest, runtime
  modules, package-search receipt, clean-image attestation, human review, and
  final release receipt all agree.

**External blocker:** the repository verifier never issues signatures. An
approved result requires role-separated, valid Ed25519 signatures from the
externally supplied trust policy. Same-host qualification always remains
non-authoritative.

## 9. Phase H: RC final review and release

- [ ] Rerun `git diff --check`, staged diff check, lint, compileall, the exact
  43 workflows, clean build/install, live smoke, and external release-mode
  qualification on the final release commit.
- [ ] Perform an independent P0/P1 review of the complete RC diff and evidence.
  Fix findings; do not waive them because tests pass.
- [ ] Publish release notes, the exact compatibility matrix, support matrix,
  known limitations, rollback instructions, and all authoritative receipt
  identities.
- [ ] Create and verify the release tag only after the external release
  decision is valid.
- [ ] Confirm the release branch, tag, and published artifacts are synchronized
  and no required V1 item remains open.

**Missing automation:** there is no single RC orchestrator or evidence-ledger
verifier. Until one exists, the release operator must retain the outputs of
each executable command and explicitly verify every cross-artifact identity.

## 10. Release decision

Use exactly one outcome:

- **BLOCKED** — any internal, package-provenance, external-attestation, visual,
  alignment, or final-review item is missing or failed.
- **V1 TECHNICALLY QUALIFIED** — all internal and same-host gates pass for an
  immutable candidate, but external clean-image authority and/or human approval
  is absent.
- **V1 PRODUCTION RELEASED** — every gate passes for the same final candidate
  and a trusted external authority issued the verified release decision.

Never infer a production release from passing unit tests, a same-host receipt,
a caller-declared clean image, a content digest, or an unauthenticated review
file.
