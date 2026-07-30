# HocusScript Roadmap Completion Plan

Status: same-host V1 technical qualification passed; RC1 clean-commit evidence
and external RC2-RC5 release authority remain open
Owner: HocusPocus engineering
Source contracts:

- `docs/hocusscript-spec.md`
- `docs/hocusscript-roadmap.md`
- `docs/hocusscript-task-tracker.md`
- `docs/hocusscript-hs8-production.md`

## 1. Purpose

This plan closes the active HocusScript roadmap without conflating three
different outcomes:

1. **V1 technical completion** — the implemented and installed product passes
   its declared supported surface and fails closed outside it.
2. **V1 production release** — an exact frozen candidate additionally passes
   externally authenticated clean-image qualification and human visual review.
3. **Post-v1 breadth** — optional fixtures, broader Houdini fidelity, scale,
   and new language syntax extend the product without blocking V1.

Unchecked historical tracker items do not automatically block V1. Each item
must be classified by the claims it affects and either completed, closed as
stale, or moved to the post-v1 queue.

## 2. Current Technical Baseline and Candidate State

The repaired governed payload passed a fresh two-process same-host technical
run on Houdini 21.0.729 and produced:

- installed two-process receipt:
  `sha256:5063c88c876822b595d44eafcb25cb43f6b04b78a59424d0a9ebc6f9b0a3a266`
- portable evidence:
  `sha256:9f2d771da3de3d136f6da60fb415a2886e6260384e41e639aa0f05f37bbf0683`
- installed manifest:
  `sha256:8a835f7af6275fe235aa9c01a418466a8d71fe21dbb5930268e1cbd6e239b703`
- normalized USDA:
  `sha256:15b2e0961ef43667707fabde87f6bb2517afd44c825818770476b7cfcc609149`

Both processes accepted with identical portable evidence and zero cook
warnings/errors. A consecutive identical install preserved the bearer token
and left the activation pointer, versioned root, and manifest unchanged. These
identities qualify the current governed same-host technical payload, but they
are not a frozen release candidate: RC1 clean-commit evidence and the RC2
source freeze remain pending. The current offline gates are 43 public
workflows, Ruff complexity `12`/`15`, the 1,200-line limit, compileall, and diff
hygiene. External clean-image and human-review authority remain open, so no
production release authority is claimed.

## 3. Closure Definitions

### 3.1 V1 technically complete

V1 is technically complete when:

- HS0 through HS8 supported behavior remains accepted;
- all supported/fail-closed boundaries are explicit in the specification and
  fidelity matrix;
- the roadmap and tracker contain no stale items that contradict accepted
  evidence;
- the exact source, build, install, runtime, fixture, and technical receipt
  identities are recorded.

The implementation meets these behavioral requirements. RC0 reconciles the
documents, RC1 completes every remaining mutable release-engineering task, and
RC2 freezes the corresponding source snapshot.

### 3.2 V1 release candidate

A release candidate is an immutable source snapshot with:

- commit and tree identity;
- source archive digest;
- dependency and runner identities;
- exact build/install manifest;
- active Houdini package pointer;
- exact fixture, USDA, report, contact-sheet, baseline, and review-request
  digests;
- passing pre-freeze internal release evidence from RC1.

Any source, schema, fixture, build-script, baseline, review-request, verifier,
or release-documentation change abandons the candidate and returns the program
to RC1 before a replacement is frozen. Externally issued clean-image
attestations, human approval carriers, and release receipts are detached
evidence: they live outside the source archive and installed manifest, carry
their own authenticated identities, and bind the frozen candidate without
changing it.

### 3.3 V1 production release

A production release is the same frozen candidate with:

- externally authenticated clean-image or VM qualification;
- external human approval of the exact visual evidence;
- release-mode qualification bound to both decisions;
- final source/install/runtime alignment;
- release notes, support matrix, signed/tagged candidate identity, and
  rollback instructions.

The local wrapper cannot self-authorize either external decision.

### 3.4 Post-v1 breadth

Post-v1 work may extend fidelity or coverage but is not required for the
current fail-closed V1 claim. It must not be silently pulled into V1 release
unless the release claim is expanded.

## 4. Remaining-Work Classification

| Work | Classification | V1 disposition |
| --- | --- | --- |
| Descriptor-safe hosted project IO | Stale tracker item | Closed by accepted H6G; legacy same-user pathname APIs retain documented limitations |
| Whole tuples and units | Stale decision | Resolved by language `0.4` / Bundle `0.5` |
| Expressions and structural channels | Stale decision | Resolved by language `0.4` |
| Source-managed graph-editor artifacts | Stale decision | Resolved narrowly by HS7 support matrix |
| Whole-tuple component mapping blocker | Stale blocker | Resolved only for language `0.4` / Bundle `0.5`; every earlier frozen compatibility row remains unchanged and fail-closed |
| Unbounded recursion | Locked policy | Permanently forbidden; bounded recursion is a separately reviewed post-v1 language proposal |
| Effective Houdini package-search provenance | V1 release engineering | Complete in RC1 so package precedence and shadowing are reproducible before freeze |
| Parser/compiler budgets and 1k-node fixture | V1 release engineering | Complete in RC1 against the roadmap targets |
| Frozen-version goldens and rejection matrix | V1 release engineering | Complete in RC1 for every supported compatibility row |
| Graph-store compatibility | V1 release engineering | Prove supported upgrades in RC1; document downgrade as unsupported unless implemented |
| Hostile-source/path and live-smoke coverage | Evidence reconciliation | Map existing accepted scenarios first; add only a demonstrated missing public workflow |
| Detached approval and external-attestation ingestion | V1 release engineering | Implement and qualify authenticated detached inputs in RC1; never install or check the production approval into the candidate |
| Source/install/runtime alignment | V1 release evidence | Record in RC2 for the frozen candidate and verify again in both external runs |
| External clean-image/VM qualification | External V1 blocker | Complete in RC3 |
| Human visual approval and release qualification | External V1 blocker | Complete in RC4 |
| Connector completeness for arbitrary operators | Post-v1 fidelity | Current fixed, complete, unique catalog evidence remains supported; incomplete namespaces reject |
| Logical sparse variadic addressing | Post-v1 fidelity | Current physical-index lane remains exact and fails closed on compaction |
| Studio-library product contract | Post-v1 productization | Existing pinned local/external source modules remain supported |
| Record literals and quoted parameter tokens | Post-v1 syntax | Add only under a new compatibility row and concrete production use case |
| Per-field `preserve_live` / `source_wins` | Post-v1 conflict policy | Current reject-on-conflict behavior remains the V1 contract |
| Environment, multi-variant USD, destruction/simulation fixtures | Optional breadth | Do not block V1; schedule as separate production matrices |
| 10k-node fixture | Post-v1 scale | Define and publish a target before claiming 10k-node performance |

## 5. Execution Plan

### RC0 — Reconcile roadmap truth

Status: complete

Tasks:

- update the current milestone and test count;
- close stale H6/HS7 tracker items against their accepted evidence;
- reclassify HS-BLOCK-005 as resolved for the current compatibility row;
- separate V1 blockers from post-v1 fidelity and optional fixtures;
- record this completion plan from the roadmap and tracker;
- retain the final same-host technical receipt and its claim boundary.

Exit evidence:

- roadmap, tracker, specification, HS8 guide, and this plan agree;
- no unchecked item falsely represents already accepted behavior;
- post-v1 items are visibly non-blocking.

### RC1 — Complete mutable release engineering

Status: pending

Tasks:

1. **Performance**
   - define the measurement machine, Houdini build, warm/cold policy, and
     repetition count;
   - measure 100-node preview p50/p95 against the 250 ms target;
   - measure a representative 1k-node compile against the 2 second warm-catalog
     target;
   - retain raw bounded samples plus a canonical summary;
   - do not create a 10k claim in V1.
2. **Compatibility**
   - retain one canonical golden for each supported language/compiler/carrier
     row;
   - prove mixed-version and silent-upgrade rejection;
   - prove supported graph-store upgrades from every promised persisted
     version;
   - document downgrade as unsupported unless an explicit downgrade contract
     is implemented.
3. **Coverage reconciliation**
   - map existing hostile-source, traversal, alias, symlink/junction/hardlink,
     stale-content, bundle-tamper, and live-smoke scenarios to tracker items;
   - add a workflow only for a concrete uncovered public boundary;
   - remain at or below 50 public scenarios.
4. **Package provenance**
   - record evaluated package files and conditions, canonical effective load
     order, expanded search paths, precedence, shadowing, and content digests;
   - bind every loaded HDA/operator winner to the effective-search receipt;
   - fail closed on unexplained loaded definitions.
5. **Detached external evidence**
   - make the release runner accept externally authored visual approval and
     CI/image attestations as authenticated detached inputs;
   - bind both inputs to the candidate manifest, review request, output set,
     comparison, policy, and installed manifest;
   - reject development fixtures, caller self-attestation, identity mismatch,
     replay, and copying an approval into the governed install as authority.
6. **Candidate contents**
   - finalize schemas, fixtures, baselines, review-request generation,
     verification tooling, release notes, support matrix, and rollback guide;
   - run focused, full, lint, compile, file-size, build/install, and independent
     P0/P1 gates on the stabilized tree.

Exit evidence:

- performance targets pass or the release claim is narrowed;
- compatibility and migration matrix is complete;
- effective package search is reproducible;
- detached external evidence can be verified without changing candidate bytes;
- no known engineering, fixture, baseline, schema, script, or documentation
  change remains for V1.

### RC2 — Freeze the single release candidate

Status: pending

Tasks:

- review the complete dirty worktree and intentional generated artifacts;
- run staged whitespace and installed-manifest checks;
- commit and push the exact completed H4-HS8 source state;
- record commit/tree identity and produce its source archive digest and
  release-candidate manifest;
- build twice from the immutable inputs without token rotation and prove
  identical versioned activation;
- rerun the internal qualification against the frozen source archive without
  modifying source, fixtures, baselines, tooling, or documentation;
- abandon this identity and return to RC1 if any finding requires a governed
  byte to change.

Exit evidence:

- one commit/tree/source digest maps exactly to the installed manifest;
- active pointer selects the expected versioned installation;
- no governed installed or runtime module is absent, extra, or stale;
- token identity is preserved without appearing in logs or manifests;
- internal receipts bind that exact immutable candidate.

### RC3 — Externally authenticated clean-image qualification

Status: blocked on external CI/image authority

Tasks:

- create an ephemeral Windows image or VM outside the repository/user session;
- install the pinned Houdini build and the RC2 candidate from immutable inputs;
- generate `hs8-clean-image-environment-v1` evidence binding image, runner,
  source snapshot, dependency, and installed-manifest identities;
- run the two-process technical qualification inside the clean boundary;
- prove active-pointer resolution, no repository import, runtime-module
  alignment, save/reopen determinism, descendant cleanup, and retained failure
  evidence;
- have the external CI authority sign a statement binding workflow/run,
  candidate, image, environment receipt, and technical receipt.

Exit evidence:

- an externally verifiable signature or attestation chain;
- exact RC2 candidate and installed-manifest match;
- clean-image technical receipt passes;
- the local wrapper still reports no independent release authority.

### RC4 — Human approval and release qualification

Status: blocked on authenticated human reviewer

Tasks:

- use the frozen review request and visual outputs generated by the RC2
  candidate;
- present the exact baseline, deterministic contact sheet, asset contract,
  numeric report, and relevant viewport evidence;
- collect approval through a protected external workflow;
- have the protected workflow issue an authenticated detached approval carrier
  containing the exact candidate provenance, output set, comparison, version,
  policy, reviewer principal, decision, and notes digest;
- keep that carrier outside the candidate source archive and installed
  manifest, and pass it to the frozen candidate's verifier as external
  evidence;
- run external clean-image release-mode qualification on the unchanged RC2
  candidate;
- have the trusted external authority issue the final release decision.

Exit evidence:

- authenticated reviewer and policy match;
- approval binds the exact asset evidence;
- clean-image and review decisions bind the same release candidate;
- candidate source, install, fixture, and review-request identities remain
  unchanged after approval;
- packaging and publish gates pass;
- no content-only or same-host wrapper result is presented as release
  authority.

### RC5 — Release and close the roadmap

Status: pending RC1-RC4

Tasks:

- verify the completed qualification and independent-review receipts for the
  exact release commit;
- publish release notes, compatibility matrix, known limitations, operational
  rollback instructions, and all authoritative receipt identities;
- tag and publish the candidate through the approved release mechanism;
- publish a detached release record and tag without changing candidate bytes;
- record `V1 production released` in the successor development state after the
  candidate is published;
- move every nonblocking item below into a separately prioritized post-v1
  roadmap.

Exit evidence:

- release tag, commit, tree, source archive, install manifest, runtime manifest,
  clean-image attestation, human review, and release receipt all agree;
- branch and release artifacts are synchronized;
- no required V1 task remains open.

## 6. Post-v1 Work Queue

Priority is product-driven rather than inherited from historical numbering:

1. **Studio library productization** — consumption-only manifest, compatibility
   policy, upgrade diff, exact HDA/catalog pins, and fresh-install consumer
   proof.
2. **Connector completeness** — audited family-by-family completeness metadata
   without active-scene mutation or cooks.
3. **Logical variadic addressing** — a new versioned selector distinct from
   frozen physical indexes.
4. **Conflict policy annotations** — explicit, policy-bound
   `preserve_live`/`source_wins`.
5. **Expanded addressability** — closed record values and quoted catalog
   parameter tokens.
6. **AAA breadth fixtures** — environment first, multi-variant USD second, and
   simulation/destruction only after a separately supported semantic/cache
   lane exists.
7. **Scale** — define and then qualify a 10k-node target.
8. **Bounded recursion RFC** — only with termination, identity, provenance,
   cancellation, and aggregate-work proofs; unbounded recursion stays
   forbidden.

## 7. Validation Discipline

- Use the smallest focused check while implementing one RC task.
- Batch related fixes before broad validation.
- Run the complete 43-workflow suite on the stabilized RC1 tree, the frozen RC2
  candidate, and the final release qualification.
- Prefer benchmark scripts and retained evidence over spending public workflow
  slots on timing assertions.
- Add a public workflow only for a distinct user-visible boundary.
- Never waive an independent P0/P1 finding solely because tests pass.
- Do not mark an external or human gate complete from repository-generated
  self-attestation.

## 8. Immediate Next Action

RC1 remains active: finish the current P1 repair batch, revalidate it, and
produce clean-commit internal evidence before completing package-provenance,
compatibility, and detached external-evidence tooling. Only after those tasks
and their findings are closed does RC2 commit, push, and freeze the single
candidate. The historical same-host receipt above is not freeze evidence.
Commit and push require explicit user authorization and are not performed by
this planning update.
