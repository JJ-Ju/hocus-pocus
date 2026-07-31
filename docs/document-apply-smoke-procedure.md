# Document Apply Smoke Procedure

Status: manual live-Houdini validation checklist

Purpose:

- verify the Workstream 3 document apply compiler against a real Houdini session
- confirm rollback, verification, and graph-store audit behavior beyond synthetic Python tests

## 1. SOP Rename, Reparent, and Code Blob

1. Open a scene with `/obj/geo1` containing:
   - a subnet
   - a child SOP inside that subnet
   - an Attribute Wrangle with a non-empty `snippet`
2. Create a checkout with `document.checkout`.
3. Edit the checkout document so that:
   - the subnet is renamed
   - the child SOP is reparented out of the subnet
   - the wrangle `code_blob` body changes
   - one literal parm changes
4. Run `document.validate`.
5. Run `document.apply` in `validate_only`.
6. Run `document.apply` in `reconcile`.

Expected result:

- the compiler returns rename, reparent, code-blob, parm, and node-update stages
- the live network matches the edited document after apply
- the refreshed document verifies cleanly

## 2. Rollback Verification

1. Create a checkout for a writable test network.
2. Edit the document into a state that will fail during apply or verification.
3. Run `document.apply`.

Expected result:

- the tool reports `rolledBack = true`
- the live network returns to the pre-apply state
- the checkout diagnostics include `apply.execution_failed`

## 3. Locked HDA Boundary

1. Open or create a locked HDA instance containing an internal network.
2. Attempt to validate or apply a document scoped to that internal locked network.

Expected result:

- validation reports `document.locked_hda_boundary`
- apply is blocked before live mutation

## 4. Audit and Store Checks

1. After a successful apply, inspect `houdini://session/health`.
2. Confirm `graphStore.applyCommitCount` and `graphStore.applyAuditRowCount` increased.

Expected result:

- each apply produces a commit row
- executed operations and failures are written to the SQLite audit table

## 5. Cross-Family Sanity

Repeat a minimal create-or-rename apply for:

- `/mat`
- `/stage`
- `/tasks`
- `/out`

Expected result:

- the same document contract applies without switching tool surfaces
- unsupported code surfaces fail with diagnostics rather than silent partial apply
