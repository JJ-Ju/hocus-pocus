# HocusScript HS8 Production Workflow

Status: exact Houdini 22.0.368 two-process same-host technical qualification
passed for the active bootstrap-repaired manifest. RC1 clean-commit evidence
and the RC2 source freeze remain pending; production release authority still
requires the external gates in `docs/hocusscript-roadmap-completion-plan.md`.

Exact Houdini `22.0.368` is the sole supported and release-qualifying live
runtime for V1. H21 receipts retained below are historical pre-H22 migration
evidence only and cannot qualify the current payload.

HS8 keeps `.hocus` as the authored graph surface. Production qualification is
a separate, strict evidence layer around the graph: the source builds the
asset; an asset contract says what the result must be; a read-only observer
records what Houdini actually produced; and content-addressed gates decide
whether the result may be packaged or published.

## Workflow

1. Edit normal Git-visible `.hocus` source.
2. Compile, preview, plan, and apply through the existing source/document
   pipeline.
3. Explicitly authorize the production cook for the selected disposable or
   build root.
4. Observe the already-cooked geometry and USD stage. Observation refuses dirty
   nodes and proves that it caused no additional cooks.
5. Qualify the observation against the asset contract and the exact source,
   compiler, catalog, module, HDA, input, and output provenance.
6. Compare the clean rebuild, numeric metrics, and visual outputs with their
   baselines.
7. Package only on a packaging-gate pass. Publish only on the stronger publish
   gate, which also requires visual evidence.

The high-level MCP operation is `production.asset.qualify`. It is read-only and
non-idempotent. It consumes content, not paths, and returns one canonical
qualification containing the contract report, build report, packaging receipt,
publish receipt, and their digests. It does not cook, write, package, publish,
or mutate Houdini. The public result is permanently `content_only`: raw gate
decisions are advisory and both actionable readiness flags remain false,
including for callers with `review_production`. Only the installed private
runner and detached release verifier can establish downstream authority.

## Required evidence

The asset contract covers:

- units, axes, handedness, names, pivot, and bounds;
- manifold/watertight topology, degeneracy, normals, and tangents;
- UV sets, UDIMs, overlap policy, texel density, and material slots;
- LODs, collision, instancing, and platform budgets;
- USD kind, purpose, variants, root/default prim, payload policy, and exact
  dependencies.

The normalized USDA is reopened as a fresh USD stage before qualification.
Material, LOD, collision, and instancing requirements bind explicit delivered
USD prims. Intermediate SOP groups and parameter strings are cross-checks only;
they cannot fill a missing material binding, delivery prim, default prim, or
instance relationship. The observer enumerates the complete bounded reopened
composition and asset-dependency closure, resolves every item to local declared
bytes, and hashes those bytes into portable path-free receipts. Unresolved,
anonymous, ambient, or ambiguously declared dependencies fail closed. An
`inline` publish cannot contain external sublayers, references, or payloads.

The build report additionally binds:

- source, recipe, compiler, catalog, module, HDA, input, and output content;
- cook duration, peak memory, polygon, texture, warning, error, and output
  metrics;
- a repeated clean-build comparison;
- numeric and visual baseline comparisons;
- proof that artist-owned protected regions survived reconcile.

Packaging requires contract, artist-preservation, provenance, outputs, budget,
determinism, and the complete canonical `BuildMetrics` numeric comparison.
Publishing requires all packaging evidence plus the visual comparison and an
explicit versioned review carrier. Review binds the candidate provenance,
output set, visual comparison, reviewer principal, and configured review
policy. A failed upstream packaging decision cannot be replaced by a locally
passing publish payload. Content-only results expose those raw decisions but
always return both readiness flags false.

For V1 release, the review carrier and clean-image/VM attestation are detached
external evidence. They are not candidate source or installed payloads. Each
has its own authenticated identity and binds the frozen candidate manifest,
installed manifest, review request, output set, comparison, and policy. The
candidate contains the schemas, request generator, baseline, and verifiers;
adding an approval to that candidate would change the identity being approved
and is forbidden.

## Schemas and errors

The installed package exposes canonical schema resources at:

- `hocuspocus://schemas/asset-contract/v1`
- `hocuspocus://schemas/build-provenance-manifest/v1`
- `hocuspocus://schemas/build-report/v1`
- `hocuspocus://schemas/publish-gate-receipt/v1`
- `hocuspocus://schemas/production-qualification/v1`

It retains these byte-identical compatibility aliases:

- `houdini://production/schema/asset-contract/v1`
- `houdini://production/schema/build-provenance/v1`
- `houdini://production/schema/build-report/v1`
- `houdini://production/schema/publish-gate/v1`
- `houdini://production/schema/qualification/v1`

Typed HS8 failures use `HOCUS950`–`HOCUS959` for contracts and observations,
`HOCUS980`–`HOCUS989` for provenance, metrics, comparisons, and gates, and
`HOCUS990` for the complete qualification envelope. Startup fails with
`HOCUS998` before server construction unless the host is exact Houdini
`22.0.368` and governed Python bytecode caching is disabled.

## Visual review

The installed fixture creates a scale-aware turntable camera and a deterministic
four-view, asset-only contact sheet. A Houdini UI run additionally captures four
named real viewport frames; a headless run renders the front, side, top, and
isometric geometry projections without taking a desktop screenshot. Final
production review compares the image with an approved baseline using a named,
versioned algorithm and retains both content digests in the publish receipt.
This visual evidence complements rather than replaces human art direction.
The harness may generate the review request and images, but only the protected
external review workflow may author the production approval carrier. A
repository fixture can test decoding and rejection behavior; it is never human
release authority.

## Qualification modes

The default same-host gate is technical qualification. It launches the
installed harness twice in isolated Houdini processes, verifies installed
harness/support/fixture/module bytes against the source checkout, and requires
stable package evidence with `review_pending`. It never claims publish:

```powershell
python scripts/qualify_hocusscript_hs8_clean_process.py `
  --mode technical --hython <hython.exe> --installed-root <installed-root> `
  --evidence-root <caller-owned-evidence-directory>
```

The retained unique run directory contains the full verified
`effective-package-search.json` and startup trace. Portable comparison and
downstream qualification expose only the package-search receipt digest.

The technical-5 exact Houdini 22.0.368 campaign passed its two-process checks,
but is superseded diagnostic evidence for the pre-bootstrap installed manifest
`sha256:7035092a036ca51b9885981389c74fca773420f862c0f926580ce68c03300279`.
Its outer receipt is
`sha256:98fe1498faae2aa0e1b93d29c81cbe57890203d10a8dc286732132a5716ae82b`.
Both processes agreed on portable evidence
`sha256:dc2f1b425e4fa8e9d346555d2682af3b59cc1d2cd1c6b04c14ca7fe7cc2ab475`,
observation
`sha256:d439936c0922f3b34e1460c7372828b8bf168368b44f29436b0584e26fa9cc0b`,
and normalized USDA
`sha256:5bd91213d3cabd33299980ee07e2a043b3571de8239dc2292a4dd4427d2de20d`
at 35,588 bytes.
Each process audited 210 governed modules and reported zero authored cook
warnings/errors. `review_pending` remained explicit, and
`readyForPackaging=false`, `readyForPublish=false`, and
`releaseAuthorized=false`.

The active installed manifest is
`sha256:facf4f0b4dcf63737ebef615654f461446b321c7cce4a0365018d937e4769e4a`.
Its `pythonrc` installs source-only admission before any governed import and
derives the governed root from Houdini-compatible code filenames. Technical-6
passed exact Houdini 22.0.368 two-process same-host qualification with outer
receipt
`sha256:19bfd956b371a99437451d8736dd48e080e4335b73f304468884194dbfb35662`
and portable evidence
`sha256:cf9d1e14434a154ef885a5df0236476c13b8c38300a22703959d486ab22891d9`.
Both processes agreed on normalized USDA
`sha256:5bd91213d3cabd33299980ee07e2a043b3571de8239dc2292a4dd4427d2de20d`
at 35,588 bytes and observation
`sha256:d439936c0922f3b34e1460c7372828b8bf168368b44f29436b0584e26fa9cc0b`,
and each audited 210 governed modules. Run 1 qualification/package/publish
digests were
`sha256:b89a1b0294f501418bec8f8478567e078eb0c2e0f596a4fb23ffcf1ed462c5f7`,
`sha256:590699d0a3acef15cbc4f2e613ce2696ee57b8e82dede1a070b3358cd1382ac4`,
and
`sha256:c54e3d011e9108eee213cc0cfa69d52902fe94f06c1d75f1e5e6a2630fe4440d`.
Run 2 qualification/package/publish digests were
`sha256:69ab271f9fce8c85a928fe847eb2b5afb4f9c464d2f33a6c1ea22c976c4aad02`,
`sha256:82d8fa5f264fc55e9d29704183df431da42c4fac0d32ae97fdd8445812cc9008`,
and
`sha256:a80b635156330877f74dd98ce1e5d80f91d7adb76dfac2557d1aca95efacb6e1`.
Both runs returned `accepted=true` with `review_pending` and both actionable
readiness flags false. The outer receipt retains `releaseAuthorized=false` and
`visualApprovalDigest=null`. Host-retained evidence is at
`C:\Users\jujun\Documents\HocusPocus-V1-Evidence\2026-07-30-h22-technical-6`.
This is same-host technical evidence, not external clean-image/VM or human
authority, RC1 clean-commit evidence, or an RC2 freeze.

The last repaired H21 same-host technical run is historical pre-H22 evidence.
It produced receipt
`sha256:5063c88c876822b595d44eafcb25cb43f6b04b78a59424d0a9ebc6f9b0a3a266`.
Its two isolated processes agreed on portable evidence
`sha256:9f2d771da3de3d136f6da60fb415a2886e6260384e41e639aa0f05f37bbf0683`,
runtime observation
`sha256:b7910d873329b3c8762ec756510a8f804623e44bdc10d4017bc7335571d06be4`,
normalized USDA
`sha256:15b2e0961ef43667707fabde87f6bb2517afd44c825818770476b7cfcc609149`,
and output set
`sha256:afe134cee33f67e615538048189f40c28cc27fe85c0a4afa87ad1b833f73ef8a`,
bound by installed manifest
`sha256:8a835f7af6275fe235aa9c01a418466a8d71fe21dbb5930268e1cbd6e239b703`.
Both runs reported zero cook warnings/errors. A consecutive identical install
preserved the bearer token and left the activation pointer, versioned root, and
manifest unchanged. `review_pending` remained explicit,
`releaseAuthorized=false`, and both actionable readiness flags remained false.
This historically qualified that governed H21 same-host technical payload, not
the current H22 payload, an external clean image, or a human visual decision.

The previous technical run produced historical receipt
`sha256:e4e0f745421dabee7c4c9c576ee2df3390a19101a13422ee18e6afca87f73591`.
Its two processes agreed on portable evidence
`sha256:e7197d7640942d7c6b5e377065e3d7abb345d2a44273f0df640e4ad98f692cf7`;
packaging passed, `review_pending` remained explicit, and
`releaseAuthorized` was false. That receipt does not qualify the current
implementation because the old observer and installed-module projection were
incomplete.

The same-host release-shaped test is explicit. It requires the Git-tracked
`scripts/fixtures/hs8/baseline-contact-sheet.png` and an independently supplied
detached visual approval outside both source and install. The runner verifies
the exact frozen request, baseline, candidate provenance, output, comparison,
version, and policy bindings without copying the approval:

```powershell
python scripts/qualify_hocusscript_hs8_clean_process.py `
  --mode release --visual-review <signed-visual-approval.json> `
  --trust-policy <external-trust-policy.json> `
  --hython <hython.exe> --installed-root <installed-root>
```

Both commands prove fresh processes on the same host, not a clean machine or
release authority. Consequently, the same-host receipt always reports
`releaseAuthorized: false`, including `--mode release`.

No production `scripts/fixtures/hs8/visual-review.json` is checked in. Tests
create bounded disposable review data, but repository fixtures cannot confer
authority. The portable receipt exposes only the verified approval digest, not
the path, content, reviewer, or notes. Until the external decisions below are
complete, no invocation shown here authorizes release.

The clean image/VM wrapper currently collects evidence from a caller-declared
ephemeral boundary:

```powershell
$env:HOCUSPOCUS_HS8_CLEAN_IMAGE = "1"
python scripts/qualify_hocusscript_hs8_clean_image.py `
  --environment-receipt <environment-receipt.json> --mode technical `
  --hython <hython.exe> --installed-root <installed-root>
```

The environment receipt contract is
`docs/schemas/hs8-clean-image-environment-v1.schema.json`. Its content digest
detects accidental mutation but is not a signature. Until CI injects and
verifies an external trust anchor, this wrapper is evidence-only, always
reports `isolationBoundary: caller_declared_clean_image_or_vm` and
`releaseAuthorized: false`, and does not certify a clean-image or clean-VM
boundary.

V1 external authority is verified separately from the runner. Install the
pinned release-verification dependency with
`python -m pip install -r requirements-release.txt`, then use
`scripts/verify_hocusscript_hs8_release_authority.py`. Its strict Ed25519
contracts are:

- `hs8-release-trust-policy-v1`
- `hs8-external-clean-image-attestation-v1`
- `hs8-signed-visual-approval-v1`
- `hs8-final-release-decision-v1`

The clean-image signature binds the frozen candidate, source, install,
runtime, environment, dependencies, and technical receipt. The visual-review
signature binds the exact request and evidence under the separate
`visualReviewer` role. The final decision binds that complete signed artifact,
requires a third release-authority principal, and may explicitly reject.
Digests alone never grant authority.

The production verifier also re-verifies the release-candidate manifest against
its exact retained inputs and RC1 evidence set. Its manifest must name the
canonical review-request digest, the request and signed evidence must agree on
candidate/output/review-policy fields, and the final `candidateDigest` must be
that manifest digest. Verification uses current UTC; the library's injected
verification time is reserved for deterministic tests. Every signer key must
be trusted both at the artifact's signed `issuedAt` and at verification time.

## Boundaries

- The observer is private live infrastructure, not a general filesystem or
  arbitrary-node inspection tool.
- It never returns physical HDA, file, USD-layer, or output paths in portable
  evidence.
- HocusScript apply remains ownership-safe. Production cooks occur only after
  apply and are explicit, measured build actions.
- HS8 proves whether a procedural result meets declared technical and visual
  gates. It does not itself provide sculpting, grooming, texture painting,
  rigging, or artistic approval, and therefore cannot guarantee AAA quality by
  itself.
