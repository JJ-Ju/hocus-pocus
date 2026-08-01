# Live Brick HDA Authoring Findings (2026-07-31)

This note records reproducible MCP behavior observed while building a brick wall
generator in Houdini 22.0.368 with HocusPocus server 0.9.0. It separates product
limitations from transport, policy, validation, and transaction-integrity issues.

## Delivered workflow

- Live scene: `C:/Users/jujun/Documents/houdini22.0/brick_wall_generator_demo.hip`
- HDA: `C:/Users/jujun/Documents/houdini22.0/otls/soupsoak_brick_wall_generator.hda`
- HDA type: `soupsoak::brick_wall_generator`, version `1.0`
- Result: a 4.0 x 2.4 m running-bond wall with automatic course counts, beveled
  bricks, alternating course color, recessed mortar, an artist-facing interface,
  preview camera, lighting, and a preview material.

## 1. `document.apply` can fail without rolling back partial mutation

Severity: critical.

Reproduction:

1. Create an empty Geometry object with `object.create_geometry`.
2. Build a valid network document containing 16 stock SOP nodes, 14 data edges,
   and 64 bindings.
3. Encode numeric menu/toggle values as the same string-like values returned by
   document checkout, such as `"poly"`, `"points"`, `"on"`, and `"off"`.
4. `document.validate` reports `valid: true` with zero errors.
5. `document.apply` fails with `Cannot set a numeric parm to a non-numeric value`.

Observed:

- The tool result had `isError: false`, `applied: false`, and
  `apply.execution_failed`.
- The diagnostic did not identify the offending binding, parameter path, value,
  or expected type.
- `details.rolledBack` was `false`.
- All 16 nodes and their connections remained in the live scene with default
  values. The operation therefore mutated the scene despite reporting that apply
  failed before verification.

Expected:

- Validation must reject an incompatible literal before mutation, or normalize
  snapshot-compatible menu/toggle tokens consistently.
- Every execution failure must report the exact binding UID and parameter path.
- A failed atomic apply must roll back all created nodes, edges, flags, and values.
- A non-applied result should be an MCP error or use a clearly documented partial
  commit state rather than `isError: false`.

## 2. Verification can reject a successfully mutated scene

Severity: high.

After repairing literal values to native numbers and booleans, apply executed all
parameter and output-flag updates. Verification then failed because the supplied
document retained the old observational `output_flag` edge while the live output
flag correctly moved to `OUT_BRICK_WALL`.

Observed:

- `applied: false`, `valid: true`, and `details.rolledBack: false`.
- Verification reported one created and one deleted edge but no actionable edge
  identities in the top-level result.
- A subsequent live sync proved that the intended output node, expressions, and
  dimensions were already active.

Expected:

- Observational `output_flag` edges should be regenerated from node flags or
  excluded from exact structural verification when the document says only data
  edges participate in apply.
- Failed verification must either roll back or return a durable partial-commit
  receipt that callers can safely inspect and reconcile.

## 3. Code capability is discovered too late

Severity: high.

`session.info` reported the `local-dev` profile with `allowSceneEdit: true`,
`allowFileWrite: true`, and `enableExecTools: false`. A VEX-backed network document
validated successfully, but `document.apply` later failed with MCP `-32010` and
`missingCapabilities: ["run_code"]`.

Expected:

- `session.info` should expose explicit `grantedCapabilities` using the same names
  used by errors.
- Compile, preview, and validate should report `requiredCapabilities` and fail
  before an apply plan is attempted.
- A documented code-enabled local profile should exist for trusted procedural SOP
  authoring.

Workaround used here: replace the VEX layout with two expression-driven stock Grid
SOPs that interleave even and odd courses.

## 4. HDA promotion does not preserve source values as defaults

Severity: high.

`hda.promote_parm` cloned the source parameter template and created a reference,
but the promoted parameter received the stock template default instead of the
source parameter's current value. For example, promoted Box `size` controls became
`(1, 1, 1)` rather than the authored wall, brick, and joint sizes. The live HDA
recooked from 28,328 points to 56 points after promotion.

The HDA was then locked, and the default document workflow rejected even outer
instance parameter edits with `document.locked_hda_boundary`. No default-discovery
tool exposed a standard `parm.set` operation, so the promoted values could not be
repaired through the advertised surface.

Expected:

- Promotion should preserve the evaluated source value by default.
- Add explicit `initial_value`, `default_value`, and `preserve_source_value`
  arguments.
- Locked HDA instances must still allow edits to their public interface parameters.
- Expose a public value-setting tool for ordinary HDA parameters.

Workaround used here: update the promoted defaults in the HDA definition with
Houdini's headless API, retain
`soupsoak_brick_wall_generator.hda.pre-default-fix.bak`, and reload the library.

## 5. `ambiguous_delivery` can hide a successful mutation

Severity: high.

The second `hda.promote_parm` call returned `HOCUS999`,
`kind: "ambiguous_delivery"`, `retryable: false`. A follow-up interface read proved
that the promotion had succeeded and the HDA had become locked.

Other read-oriented calls during the same session, including HDA library discovery
and source export, also returned `ambiguous_delivery` after long waits. Operation
history preserved some underlying errors but identified every method only as
`tools/call`.

Expected:

- Every ambiguous result should include `operationId`, concrete tool name, host
  generation, and whether a commit boundary may have been crossed.
- Known terminal host errors should be propagated instead of replaced by delivery
  ambiguity.
- Read-only ambiguous calls should normally be retryable.

## 6. Authoring schema and catalog discoverability remain uneven

Severity: medium.

- `document.apply` exposes its document as an opaque object; constructing a valid
  candidate required repository-source inspection.
- The compatibility compile endpoint accepted language 0.1 while export advertises
  language 0.4, and a structurally valid compile did not provide a structured next
  action for guarded live application.
- `node_types.get_info` required `category` for common ambiguous names even though
  the field is optional.
- Searching `"poly bevel"` returned no result while `"bevel"` returned
  `polybevel`.
- `copytopoints` key parameters omitted the important `pack` control; it appeared
  only in full parameter detail.

Expected:

- Publish a machine-readable NetworkDocument schema resource and examples.
- Return structured `nextActions` from compile/preview.
- Align supported source versions or provide an explicit conversion path.
- Normalize catalog search tokens and return stable catalog IDs.
- Curate key parameter lists around actual procedural-authoring workflows.

## 7. Live revision churn is too granular

Severity: medium.

One graph construction burst generated roughly 100 monitor events, including many
repeated `AppearanceChanged` events, and advanced the scene revision from 157 to
256. This makes optimistic revision gates fragile during ordinary Houdini activity.

Expected:

- Coalesce callbacks into one logical transaction revision.
- Track structural and cosmetic revisions separately.
- Include the triggering tool and transaction ID in event/operation records.

## 8. `scene.undo` is incompatible with this Houdini build

Severity: high.

Three consecutive `scene.undo` calls in Houdini 22.0.368 failed with MCP
`-32603`, `errorFamily: "runtime"`, and the deterministic detail
`'undos' object has no attribute 'undo'`. The result was marked retryable even
though retrying did not change the failure.

Expected:

- Use the Houdini 22-supported undo API and cover it with installed-runtime tests.
- Mark deterministic API incompatibility as non-retryable.
- Return current undo-stack metadata so callers can confirm the intended operation
  before invoking undo or redo.

## Reliable caller practices until fixed

1. Treat `applied`, diagnostics, and a fresh live sync as authoritative; do not rely
   on top-level `isError` alone.
2. After any ambiguous mutating call, inspect live state before retrying.
3. Encode v1 numeric/toggle literals as native numbers/booleans, not checkout-style
   strings or menu labels.
4. Regenerate observational output-flag state from the live graph before exact
   verification.
5. Preflight `run_code` explicitly before choosing a wrangle-based architecture.
6. Verify HDA geometry again after every parameter promotion.
7. Do not depend on `scene.undo` for transactional recovery until the installed
   Houdini runtime path is fixed and qualified.
