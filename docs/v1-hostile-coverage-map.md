# HocusPocus V1 Hostile and Live Coverage Map

Status: RC1 evidence map

This document maps V1 trust boundaries to the existing public workflow that
owns the assertion. It is an index, not a replacement for running the
43-workflow catalogue. A boundary is considered covered only when the named
workflow and its delegated helper assertions pass.

The catalogue remains six files and 43 public workflows. Adding rows here does
not create tests. A new public workflow is justified only when a concrete
user-visible boundary has no existing owner.

## 1. Source, parser, and carrier boundaries

| Boundary | Public workflow owner | Evidence |
| --- | --- | --- |
| Invalid UTF-8, malformed syntax, bounded recovery, and actionable diagnostics | `test_authoring_errors_are_actionable_and_do_not_crash_the_compiler` | Recovered parsing remains bounded; malformed input returns typed diagnostics rather than Python exceptions |
| Forged control AST field/container/span/index shapes | `test_semantics_validate_the_whole_control_program` | Iterative preflight rejects forged versions, names, tuples, indexes, spans, oversized text, and structurally unsupported lanes |
| Hidden-branch and zero-count-body semantic admission | `test_semantics_validate_the_whole_control_program` | Whole-program validation runs before selection or fold execution |
| Expansion depth, aggregate work, cancellation, catalog-scan cancellation | `test_expansion_stops_at_public_limits_or_cancellation` | Public limits and late cancellation return the declared typed boundary |
| Bundle version mixing, field smuggling, digest/capability/source-URI tampering | `test_authoring_errors_are_actionable_and_do_not_crash_the_compiler` | Strict carrier decoders reject cross-row and rehashed forged payloads |
| Catalog snapshot tampering | `test_catalog_snapshot_round_trips_and_rejects_tampering` | Content-bound catalog identity changes when governed Houdini facts change |
| Expansion provenance conflict, dangling reference, or forged live identity | `test_compiled_graph_lowers_and_exports_back_to_equivalent_source` | Authenticated stacks and managed identity are required before lowering/export |
| Unrepresentable managed state | `test_export_fails_closed_when_managed_state_cannot_be_represented` | Export rejects rather than approximating unsupported live state |

The `test_compiled_graph_lowers_and_exports_back_to_equivalent_source` name is
a historical test identifier. Its export assertion is structural
recompilation plus exact-catalog semantic/connector validation; it does not
guarantee network reconstruction.

## 2. Project, module, and native filesystem boundaries

| Boundary | Public workflow owner | Evidence |
| --- | --- | --- |
| Project relocation and portable identities | `test_native_bundle_is_deterministic_after_project_relocation` | Relocation with the same manifest UID, relative paths, lock, and bytes preserves the bundle |
| Stale local module bytes and lock repair | `test_changed_native_module_is_rejected_until_lock_update` | Compile rejects stale source/lock identity until an explicit lock update |
| Missing, extra, stale, or wrong external roots | `test_mixed_consumers_reject_missing_roots_and_stale_external_source` | Every mixed call supplies the complete exact alias mapping and current bytes |
| Lowercase Windows drive aliases, symlink roots, and external-root canonicality | `test_mixed_consumers_reject_missing_roots_and_stale_external_source` | Host roots fail closed on alias or link ambiguity |
| External alias shadowing, cancellation, and stale winner authority | `test_stale_lock_digest_never_overwrites_mixed_project_lock` | Final resolver winners and expected lock digest are rechecked under publication authority |
| Bundle dependency tampering and physical-root leakage | `test_external_manifest_inspection_and_bundle_tampering_fail_safely` | Inspection/receipts remain host-path-free and strict decoding rejects forged dependencies |
| Native generated-artifact replacement | `test_native_artifact_publication_requires_explicit_replace_authority` | Exclusive create or exact-digest replacement authority is required |

## 3. Hosted H6 filesystem and authority boundary

| Boundary | Public workflow owner | Evidence |
| --- | --- | --- |
| Session/principal grants, expiry, persistence, restart, and revocation | `test_h6_authority_registry_sessions_grants_and_restart` | Opaque selectors are non-authorizing; every operation rechecks current authority |
| Traversal, separator/case/Unicode/reserved-name aliases | `test_h6_descriptor_safe_enumeration_search_and_reads` | Descriptor-relative enumeration/read rejects non-portable or escaping selectors |
| Symlink, junction/reparse, hardlink, root swap, and component swap | `test_h6_descriptor_safe_enumeration_search_and_reads` | Pinned root/file identity and no-follow/beneath or Windows namespace guards fail closed |
| Stale digest, concurrent writer, atomic replacement, rollback, and durability | `test_h6_guarded_create_patch_publication_and_invalidation` | Publication keeps rollback authority until identity/content/namespace durability verification |
| Manifest projection widening and generated/external write denial | `test_h6_guarded_create_patch_publication_and_invalidation` | Authority-changing manifest results require reapproval; generated and external files remain outside generic patching |
| Handle-backed build/export/navigation and authenticated export handoff | `test_h6_native_source_project_operations_and_export_auth` | Hosted operations consume pinned provider state rather than reopening ambient paths |
| Pagination, payload limits, rate limits, audit redaction, cache invalidation | `test_h6_mcp_source_surface_limits_audit_and_revocation` | Limits are scoped and atomic; audit/resources expose no physical roots or source/query text |
| Installed source-to-live workflow and post-revoke denial | `test_h6_installed_houdini_source_to_live_acceptance` | Real Git-visible files complete the bundle/document pipeline and subsequent access fails after revoke |

## 4. Document, apply, recovery, and live boundaries

| Boundary | Public workflow owner | Evidence |
| --- | --- | --- |
| Ambiguous or malformed document topology | `test_document_validation_accepts_a_network_and_rejects_an_ambiguous_edge` | Network-document validation rejects ambiguous edges before mutation |
| Content-addressed documents, bundles, and detached plans | `test_document_artifacts_and_apply_plans_are_content_addressed_and_detached` | Plans bind exact carrier, target, policy, capability, and baseline identity |
| Concurrent overlapping writes and idempotent replay | `test_document_apply_replays_results_and_excludes_overlapping_writes` | Scope leases exclude overlap and replay returns the committed result |
| Stale catalog and non-mutating preview | `test_preview_produces_a_read_only_plan_and_rejects_catalog_drift` | Preview never applies and fresh live semantics reject drift |
| Confirmation, ownership, stale-plan, and durable apply lifecycle | `test_plan_apply_is_guarded_durable_and_idempotent` | Stored plan identity is the only execution authority |
| Mid-apply failure and rollback | `test_failed_apply_rolls_back_the_scene_candidate` | Failure restores or quarantines verified state rather than returning partial success |
| Recovered target/baseline/partial states and bounded retention | `test_document_apply_replays_results_and_excludes_overlapping_writes` and `test_graph_store_persists_an_idempotent_plan_commit_lifecycle` | Recovery classification, terminal replay, and protected pending/partial evidence remain durable |
| Persisted graph-store upgrade | `test_graph_store_upgrades_existing_documents_without_data_loss` | Checked-in prior schema fixtures upgrade while retaining document/revision behavior |
| Live catalog stability and HDA mutation sensitivity | `test_live_catalog_is_portable_stable_and_changes_with_the_hda` | Catalog identity changes when the observed HDA definition changes |
| Live edit coalescing and child discovery | `test_scene_monitor_coalesces_network_edits_and_observes_new_children` | Monitoring coalesces changes without losing newly created network children |

## 5. HS7/HS8 production and installed boundaries

| Boundary | Public workflow owner | Evidence |
| --- | --- | --- |
| Typed values, named ports, editor entities, spares, animation, and fail-closed unsupported families | `test_hs8_qualification_surface_and_installed_fixture_are_cohesive` through the HS7/HS8 integrated helpers | Exact catalog evidence is required; unsupported constructs do not silently degrade |
| Invalid production geometry/USD/material/LOD/collision/instancing facts | `test_hs8_asset_contracts_reject_invalid_production_facts` | Asset contract validation rejects missing or contradictory delivered-stage truth |
| Deterministic build evidence and advisory packaging/publish gates | `test_hs8_build_evidence_is_deterministic_and_publish_gated` | Evidence digests and gate bindings are exact; visual approval remains separately authoritative |
| Installed source/install/runtime byte alignment, transactional activation, token preservation, child cleanup, and output bounds | `test_hs8_qualification_surface_and_installed_fixture_are_cohesive` | Clean-process/build helpers verify the complete governed manifest and running module origins |
| Reopened normalized USDA as canonical asset truth | `test_hs8_qualification_surface_and_installed_fixture_are_cohesive` | Material, LOD, collision, prototype/instance, purpose, visibility, topology, dependency, and metric facts come from the fresh stage |
| Caller self-digest versus external release authority | `test_hs8_qualification_surface_and_installed_fixture_are_cohesive` | Same-host and caller-declared clean-image receipts never authorize release; the detached release verifier requires role-separated external signatures and exact candidate bindings |

## 6. Release use

Before freezing a candidate:

1. run the focused owner of any changed boundary;
2. update this map if ownership moved or a real gap was discovered;
3. run the full 43 workflows once at the stabilized checkpoint;
4. retain the test output digest with the release-candidate evidence;
5. keep live, installed, clean-image, and human-authority evidence distinct.

The remaining external clean-image and human approval gates cannot be checked
off by this map or by repository-generated fixtures.
