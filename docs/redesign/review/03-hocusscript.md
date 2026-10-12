> **Status: historical.** Describes HocusPocus 0.9, archived at tag `v0.9-archive`. See [`../README.md`](../README.md).

# Review 03: HocusScript and the network-document carrier

Reviewer scope: `python3.11libs/hocuspocus/hocusscript/` (128 modules, 55,896 LOC), `live/ops/hocusscript*.py`, `live/ops/document*.py`, `live/ops/source_*.py`, `live/production_*.py`, the HS-series scripts, tests, docs and schemas. Measurements were taken from the `master` working tree at `cab2430`.

**Verdict:** the hypothesis holds. The idea underneath HocusScript is sound: an idempotent, ownership-aware graph reconcile with diff-before-apply and verify-after-apply. That idea takes perhaps 4-6K lines. Around it sit a custom language, four versioned carrier lanes, a module/lock/project system, a sandboxed filesystem workspace and a release-signing apparatus. Together these are about 100K lines of source, scripts and tests, and they cost agents more than they return. **Recommendation: option (b).** Keep a small JSON graph spec with validate/diff/apply that reuses the existing reconcile/apply engine. Remove the language from the MCP core and archive it at a tag.

---

## 1. What HocusScript actually is

### 1.1 The language

`.hocus` is a TypeScript-shaped declarative format that is never executed (`docs/hocusscript-spec.md` §1). A file declares one `graph` (or one `module`). The graph has a target network, a category, an apply mode (`merge`/`reconcile`), an ownership namespace, and nodes. Node bodies use **real Houdini type names and parm names**, so a file is mostly Houdini vocabulary in a new syntax.

Example 1, the language 0.1 conformance fixture (`tests/fixtures/hocusscript/v0.1/all_features.hocus`):

```hocus
hocus "0.1";
graph all_features {
  target = "/obj/geo1"; category = Sop; mode = reconcile; expect = 7;
  ownership = "tests.all_features";
  existing readonly = "/obj/geo1/READ_ONLY";
  adopt managed = "/obj/geo1/MANAGED";
  node source: null { python_code = python`return 1`; }
  node sink: "attribwrangle" {
    input[0] = source; input[1] = source.out[2]; input[2] = managed.output[0];
    vex_code = vex`a\`b`;
  }
  display = sink; render = sink; output = sink; layout = auto;
}
```

Example 2, the HS8 production fixture (`scripts/fixtures/hs8/rock-family.hocus`, 20 nodes). This is plain SOP wiring with durable `@id`s:

```hocus
hocus 0.4;
graph HS8RockFamily {
  target "/obj/hs8_rock_family"; category Sop; ownership "hs8"; mode reconcile;
  node hero_seed @id("hs8.hero.seed"): "platonic" { type = "4"; radius = 1.8; }
  node hero_sculpt @id("hs8.hero.sculpt"): "mountain" {
    input[0] = hero_seed.output[0]; height = 0.55; }
  node hero_reduce @id("hs8.hero.reduce"): "polyreduce::2.0" {
    input[0] = hero_uv.output[0]; percentage = 62.0; }
  ...
}
```

Example 3, language 0.4 typed values (`scripts/fixtures/hs8/usd.hocus`). The 0.4 additions are `raw_path(kind, "...")`, `multiparm(instances=[instance("rock", {...})])`, ramps, tuples, quantities and `reset`. Language 0.2 adds `module`/`import`/`use`. Language 0.3 adds bounded compile-time `if … outputs(…)` and `for … (i in range(n)) carry(…)` folds (spec §16).

None of the 5 `.hocus` files in the repo uses modules or control flow. Those features are exercised only by inline test strings.

### 1.2 Compile pipeline

Text flows through these stages: `lexer.py` → `parser.py` (+ `parser_*` for tagged values, ports, editor and runtime entities) → `syntax.py` (source-faithful AST) → `lowering.lower_syntax` → normalized **GraphSpec** (`model.py`, schema v0.1-v0.5) → `semantic.resolve_graph`, which checks against a fingerprinted **catalog** (`catalog.py`, built live by `live/catalog_provider.LiveHoudiniCatalogProvider`; the H22 catalog is 44 MB over 5,566 operators per spec §16.8) → `expander.py` / `control_expander.py`, which expand modules and folds into an expansion map → `bundle.py`, a content-addressed **Compiled Bundle** 0.1-0.5 → over MCP, `document_lowering.lower_bundle_to_document`, which lowers the bundle onto the live **network document** baseline → `document.preview_bundle` (diff) → `document.plan_bundle` (an immutable plan stored in SQLite by `live/graph_store_plans.py`) → `document.apply_plan`. Apply checks plan hash, revision, idempotency and lease gates, then runs `_document_execute_apply_plan` inside `hou.undos.group`, verifies by re-diffing, and rolls back or quarantines on failure (`live/ops/hocusscript_apply.py:312-490`).

### 1.3 Modules, locks, projects

`hocus.project.toml` (project manifest v1-v5) and `hocus.lock.json` (lock v1-v5) pin module digests, the catalog and the language version. External libraries ("mixed roots", `@alias/path.hocus`) need module manifests v1-v3, resolved-module-set v1-v3, and a per-call `--module-root ALIAS=ABS_PATH` mapping. Each operation exists in up to four parallel lanes: {plain, `mixed_`, `control_`, `control_mixed_`} × {lock_update, project_editor, resolution}.

### 1.4 "Control", "editor", "runtime"

- **Control** (`control_*.py`, 5.7K LOC) is the language 0.3 `if`/`for` compile-time constructs, with budgets of 4,096 iterations per fold and 100K aggregate.
- **Editor entities** (`editor_*.py`, `document_editor_*`) are network boxes, sticky notes, node comments, dots and layout constraints. These are graph-editor cosmetics, not a code editor. `editor.py` also holds IDE completion and definition APIs.
- **Runtime entities** (`runtime_*.py`) are managed spare parms and scalar keyframe animation (GraphSpec 0.5 / network-document v2).

### 1.5 Workspace, production, release

- **H6 source workspace** (`_workspace_*.py`, `workspace_*.py`, `project_service*.py`; 8.9K LOC plus `core/workspace_*.py` 2.5K and `ui/workspace_widget.py`) is a sandboxed filesystem. It has seven `source.*` MCP tools, host-approved grants through a Houdini Python panel, NTFS handle-relative atomic rename (`_workspace_windows_rename.py`, 1,196 LOC, using `ctypes`/`msvcrt`) and a Linux equivalent (1,115 LOC).
- **HS8 production** (`asset_contract*`, `build_*`, `production_pipeline.py`, plus `live/production_*.py` 6.2K) checks a cooked asset against an asset contract: topology, UVs, LODs, USD kind/purpose, budgets, and visual baselines. The public MCP result of `production.asset.qualify` is "permanently `content_only`" and both readiness flags are always false (`docs/hocusscript-hs8-production.md`).
- **Release authority** (`release_authority.py`, `release_candidate.py`, `release_evidence.py`, plus `scripts/qualify_hocusscript_hs8_clean_image.py`, `manage_hocusscript_rc1_evidence.py`, …) does Ed25519-signed release decisions, clean-image attestation and RC1 evidence sets. The completion plan still lists these as "pending" or "blocked on external CI/image authority" and "blocked on authenticated human reviewer" (`docs/hocusscript-roadmap-completion-plan.md:232-368`).

---

## 2. What problem it solves (steelman)

These are the real problems HocusScript addresses, roughly from most to least valuable.

1. **Managed ownership coexisting with artist edits.** This is the most valuable capability, and plain `hou` scripting does not give it to you. Nodes are stamped with `hpmcp.uid`, `hpmcp.owner` and `hpmcp.provenance` user data (`live/ops/document.py:36-42`, `document_metadata._document_stamp_live_node_metadata`). `reconcile` mode deletes only omitted nodes **in the same ownership namespace**. It refuses to delete an owned node that an artist edge or binding still references (`hocusscript/document_reconcile.protected_owned_dependencies`, `reconcile_owned_state`). Artist parm overrides on managed nodes are tracked through per-node "managed fields" (`validated_managed_fields`), so a re-apply doesn't stomp them.
2. **Deterministic, idempotent re-apply.** Durable `@id` identities let an agent re-run the same spec and get "no changes", or a minimal diff, instead of duplicate `box1`/`box2` nodes. This matters a lot for agents, which tend to retry.
3. **Diff before mutation, verify after.** A preview shows creates, deletes, rewires and parm changes plus a destructive summary. After execution the live network is re-imported and diffed against the target (`_document_verification_diff_payload`), and a failure rolls back (`document_mutation_integrity._document_rollback_direct_apply`). That is safer than a fire-and-forget Python script.
4. **One undo group per logical change.** This is useful, but it is not unique: `graph.batch_edit` and every `node.*`/`parm.*` tool already wrap their work in `hou.undos.group` (`live/ops/node.py:61`, `parm.py:73`).
5. **Git-visible, reviewable graphs.** This is real, but any canonical text form gives it. A sorted JSON spec, or even a deterministic Python file, diffs well in Git. `.hocus` is a little more compact than JSON, mainly in edge syntax (`input[0] = a.output[0]`).
6. **Live → text export** (`document.export_source`). This is useful for compactly describing an existing network to an agent. A JSON export does the same job.
7. **Modules, locks, external libraries, control flow, signed releases.** These solve studio-pipeline problems: shared reviewed graph libraries and supply-chain provenance. Nobody in this repo has those problems yet; no fixture uses modules. Houdini already answers "reusable graph module" with HDAs, and the agent can produce repetition with a Python loop.

**What carries the value:** items 1-3. They live in the **network-document apply engine** (`live/ops/document_apply*.py`, `document_diff.py`, `document_mutation_integrity.py`, `document_snapshot.py`, `document_metadata.py`) and in `hocusscript/document_reconcile.py`, not in the language. The language is a front end to that engine. Its only unique contribution is that it is the place where `@id` and `ownership` get authored, and a JSON field does that equally well.

---

## 3. Complexity cost

### 3.1 Lines of code

| Area | LOC | Notes |
|---|---:|---|
| Core language (lexer, parser, syntax, semantic, resolver, lowering, compiler, formatter, model, catalog, expander, exporter, cli) | 9,842 | 17.6% of package |
| Document lowering/reconcile (`document_lowering`, `document_reconcile`, …) | 2,289 | 4.1% |
| Carrier/bundle version decoders (`contracts`, `_carrier_versions`, `bundle*`, `document_bundle_*`) | 4,284 | 7.7% |
| Modules / projects / locks / mixed+control lanes | 11,693 | 20.9% |
| Control language 0.3 | 5,681 | 10.2% |
| HS7 editor/runtime/typed-value entities | 7,875 | 14.1% |
| H6 sandboxed workspace | 8,928 | 16.0% |
| HS8 production + release authority | 5,304 | 9.5% |
| **hocusscript/ total** | **55,896** | 57% of the 98.4K-line `hocuspocus` package |
| live/ops HocusScript + `source_*` ops | 2,565 | |
| live production observers + `package_search_*` | 6,224 | |
| `core/workspace_*` + workspace UI widget | ~2,850 | |
| scripts (`*hocusscript*`, `hs8_*`) | 12,656 | 26 scripts |
| tests (`*hocusscript*`, `hs8_*`) | 18,900 | **80% of all 23,617 test lines** |
| **HocusScript-attributable total** | **~99,000** | |
| Network-document layer it lowers into (`live/ops/document*.py` + `document_service` + `graph_store*`) | ~11,800 | partly needed by any reconcile design |

**Split estimate for the 56K package:**
- Core language and lowering: ~12K (22%).
- Version-lane and carrier multiplexing: ~10.5K (19%). This is the 4.3K of carrier decoders plus ~6.2K of plain/mixed/control/control_mixed duplicates: `control_mixed_resolution` 960, `control_project_editor` 914, `project_editor` 918, `control_lock_update` 757, and others.
- Feature extensions an agent will rarely need (control, HS7 entities, module system core): ~19K (34%).
- Workspace sandbox: ~9K (16%).
- HS8 production/release ceremony: ~5.3K (9.5%). Adding the 6.2K of live observers and ~8.5K of qualification/RC/smoke scripts brings release and qualification ceremony to **~20K lines repo-wide**.

### 3.2 Schemas and versions

There are 61 JSON schemas in `docs/schemas` (369 KB). 14 are HS8, release, production or visual review. The carrier version matrix an implementer must keep straight:

- language 0.1-0.4
- compiler 0.1.1/0.2.0/0.3.0/0.5.0/0.6.0
- GraphSpec 0.1-0.5
- Bundle 0.1-0.5
- project manifest v1-v5
- lock v1-v5
- module manifest v1-v3
- resolved-module-set v1-v3
- expansion-map v1-v3
- catalog v1-v2
- network-document v1-v2

Every combination is "exact-pair, never upgraded" (spec §4.3, §16.8), so each old lane stays live code forever. There are **481 distinct `HOCUS###` diagnostic codes**. Network-document v2 alone has 24 top-level fields and a 26 KB schema.

### 3.3 Agent-facing surface

There are **25 MCP tools**:

- 17 `document.*`. Of these, 10 are specific to HocusScript: compile/format/complete/export_source, preview/plan_bundle, apply_plan, discard_plan, apply_quarantines, recover_scope.
- 7 `source.*`.
- `production.asset.qualify`.

That is out of roughly 172 tools in total. HocusScript, document and source resources make up **26 of 41** registered resources (`live/operations.py`).

The minimum agent loop for a change is `source.project.describe` → `source.file.read` → `source.file.apply_patch` → `source.project.build` → `document.preview_bundle` → `document.plan_bundle` → `document.apply_plan`. The last call takes `planId`, `planHash`, `expectedDocumentRevision`, `expectedLiveRevision`, `idempotencyKey`, and `confirmationToken` when the change is destructive. It also needs a human to first approve the project directory in a Houdini Python panel (README §"HocusScript source workspace"). The equivalent `node.create`/`parm.set` or `graph.batch_edit` path takes 1-3 calls.

Concepts an agent must learn before its first successful apply: the language version header, the graph envelope, `@id`, ownership, merge vs reconcile, `existing`/`adopt`, the port syntax, the bundle, plan identity, two revision counters, the idempotency key, confirmation tokens, project grants and opaque `projectId`s. That is about 15 concepts, and none of them is Houdini vocabulary.

### 3.4 Startup and maintenance

- `hocusscript/__init__.py` eagerly re-exports almost everything. Importing `hocuspocus.live.operations` pulls in **107 hocusscript modules**. The warm import measured 0.25 s for `hocuspocus.hocusscript` and 0.51 s for `live.operations` (CPython 3.13 on this machine). Cold imports were up to 0.68 s.
- The network-document layer (introduced together with HocusScript in `c5aaf94 Add document graph and HocusScript frontend`) now imports HocusScript internals in 12 `live/ops/document*.py` files. Examples are `document_editor_entities`, `document_runtime_contract` and `document_value_validation`. The two can't be separated without surgery.
- HocusScript accounts for 80% of test lines, 26 scripts, ~3,850 lines of HocusScript docs plus trackers, and an 836-line task tracker. It is the main driver of the "1,200-line file gate" and the "50-test ceiling" release gates cited in the spec.

---

## 4. Would an agent choose `.hocus` over creating nodes directly?

Mostly no.

- **Prior knowledge.** An LLM already writes `hou.node("/obj").createNode("geo")`, `node.setInput(0, other)` and `parm("radius").set(1.8)` fluently, and it knows SOP type and parm names. `.hocus` reuses those names, which is to its credit, but the envelope, the `@id` and ownership rules, the typed-value constructors (`raw_path(usd_prim, …)`, `multiparm(instances=[instance(…)])`), and the version-specific grammar are all things it has never seen. It will make mistakes on them, and it has 481 diagnostic codes to decode.
- **Round trips.** Seven calls with hash and revision bookkeeping, plus a human-granted workspace, against one `graph.batch_edit`. Agents optimise for fewer and simpler calls.
- **Iteration style.** Agents work incrementally: add a node, cook, inspect, tweak. HocusScript is whole-graph re-declaration, which pays off for big stable graphs and costs for exploration.
- **Where an agent *would* want it.** When it rebuilds the same 20-node graph repeatedly (retries, parameter sweeps) and needs re-runs to be idempotent and to avoid clobbering artist edits. That need is real, but it only requires a declarative **data** payload that the agent can emit as JSON, which LLMs produce reliably, with a dry-run diff. A new language adds nothing to that.
- **Agents already have files and Git.** The `source.*` sandbox duplicates the agent's own file tools behind a grant system. An agent that can edit files will just edit files.

---

## 5. Recommendation: **(b) a minimal declarative graph spec (JSON) with validate/diff/apply**

Removing the language and keeping the engine keeps the benefits in §2 items 1-3 at about 5-10% of the cost.

- **(a) Cut entirely** throws away ownership-aware reconcile and verify/rollback. Those are the parts agents benefit from, and a plain `batch_edit` lacks them.
- **(c) Optional separate package/CLI** sounds cheap but isn't. Bundles lower into the core's network-document contract, and 12 core `document*` modules already import HocusScript internals, so an external package would pin and constrain the core's document format indefinitely. Nobody depends on it externally. The version is 0.9.0, HS8 RC1 was never released, and there is no `.hocus` usage outside fixtures.
- **(d) Keep as is** keeps 57% of the codebase and 80% of the tests for a front end agents won't use.

### 5.1 Proposed shape

There are one or two tools. The first is `graph.apply_spec {spec, mode: merge|reconcile, dry_run}`, which returns a diff and, when not a dry run, the executed result and verification. The second, `graph.export_spec {root_path}`, is optional. The spec is GraphSpec v0.2 minus spans and source maps:

`{target, category, ownership, mode, nodes:[{id, name, type, parms:{}, inputs:[{index, from, output}]}], external:[{id, path, adopt}], display, render, output}`

Expressions are a `{"expr": "...", "lang": "hscript|python"}` value. The spec keeps one version, with no module system, control flow or bundle. The agent writes Python loops when it needs repetition. Studios that need reusable modules use HDAs.

### 5.2 Kept (reused in the redesigned core)

| Capability | Modules / functions |
|---|---|
| Live network → canonical snapshot | `live/ops/document_snapshot.py`; `document_metadata._document_live_node_identity`, `_document_live_input_connections` |
| Ownership stamping | `document_metadata._document_stamp_live_node_metadata`, `_document_clear_live_node_metadata`, keys `hpmcp.uid`/`hpmcp.owner`/`hpmcp.provenance` (`live/ops/document.py:36-42`) |
| Reconcile/ownership engine | `hocusscript/document_reconcile.py` (`reconcile_owned_state`, `protected_owned_dependencies`, `removed_owned_node_uids`, `validated_managed_fields`); move it into `live/` |
| Spec → target document lowering | the core of `hocusscript/document_lowering.py` (`_reconcile_baseline`, `_lower_external_nodes`, `_lower_authored_nodes`, `_lower_parameters`, `_lower_connections_and_output`, `_record_managed_fields`), rewritten to take the JSON spec instead of a `CompiledBundle` |
| Plan build | `live/ops/document_apply.py` `_document_build_apply_plan`, `_document_plan_node_updates`, `_document_plan_deletions`; `document_apply_managed.plan_connection_changes`, `plan_binding_changes`, `identity_update_mismatches` |
| Undo-grouped execute | `document_apply._document_execute_apply_plan` and the `_document_execute_{identity_changes,node_updates,creates,moves,connections,finalizers}` helpers (wrapped in `hou.undos.group` at `document_apply.py:960`) |
| Preflight, rollback, quarantine | `document_mutation_integrity._document_preflight_apply_plan`, `_document_coerce_assignment`, `_document_prepare_direct_inverse`, `_document_rollback_direct_apply`, `_document_quarantine_direct_apply` |
| Diff and verification | `document_diff._document_diff_payload`, `_document_verification_diff_payload`, `_document_diff_is_clean` |
| Parm-template introspection | helper functions in `live/catalog_provider.py` (`_parameter`, `_parameter_menu`, `_parameter_range`, `_connectors`, `_multiparm_value_contract`), folded into `node_types.get_info`. Drop the 44 MB fingerprinted whole-catalog snapshot. |
| Idempotency | `document_service.reserve_apply_result`/`commit_apply_result`, if not already covered by `session.get_operation` |

Estimated retained size: about 5-7K lines, after the v2 editor, runtime and typed-value branches are stripped out of the reused functions.

### 5.3 Removed

- The **whole `hocusscript/` package** except `document_reconcile.py` and a trimmed `document_lowering.py` (~54K).
- MCP tools: `document.compile_source`, `format_source`, `complete_source`, `export_source`, `preview_bundle`, `plan_bundle`, `apply_plan`, `discard_plan`, all 7 `source.*`, and `production.asset.qualify`. Also `document.checkout`/`validate`/`diff`/`apply`/`discard_checkout`, which are replaced by `graph.apply_spec`, with `apply_quarantines`/`recover_scope` folded in as an error-path field. That is 25 tools down to 2.
- `live/ops/hocusscript*.py`, `source_*.py`, `live/production_*.py`, `live/ops/production.py`, `package_search_*`, `core/workspace_*`, `ui/workspace_widget.py`, `graph_store_plans.py` (immutable plan store), and the 26 HocusScript/HS8 scripts and their fixtures.
- 55 of 61 schemas. Keep a single `graph-spec-v1.schema.json`, and possibly a slim snapshot schema.
- Docs: `hocusscript-*.md` (6 files), `document-graph-overhaul-*.md`, `document-contract-v1.md`, `v1-hostile-coverage-map.md` sections, and the HS trackers. Move them to an `archive/` tag rather than deleting them from history.
- Network-document v2 editor, runtime and time-sample entities (boxes, stickies, dots, spares, animation, USD time samples). If they are needed later, add them as plain tools (`node.add_spare_parm`, `parm.set_keyframes`) rather than as carrier fields.

---

## 6. Risks of cutting and the migration note

**User-facing promises that exist today:**
- `README.md:8` calls HocusScript one of "two useful authoring surfaces". `README.md:130-175` documents the source workspace, the seven `source.*` tools and the CLI. `README.md:100-125` covers the `document.checkout/validate/diff/apply` flow. `README.md:246,260-262` link the tests and docs.
- `docs/user-manual.md:304-445` has the HocusScript source workflow, grants config `[[source_workspace.projects]]`, and the CLI.
- `docs/agent-workflows.md:128-200` describes the native edit/apply loop and `production.asset.qualify`.
- `docs/compatibility-policy.md` §2 says tool names and resource URIs "should remain stable within a minor line unless clearly deprecated first". Removal therefore belongs in **0.10.0** with a release note. It must not land in a 0.9.x patch.
- The Houdini **Source Workspaces** Python panel and its persisted grant registry, and the `python -m hocuspocus.hocusscript` CLI entry point.

**Actual risk is low:**
- The version is 0.9.0.
- HS8 never reached a released RC: RC1 evidence and the RC2 freeze are pending, and the external attestation gates are open.
- The repo contains no `.hocus` content beyond 5 fixtures.
- Scenes may still contain nodes stamped with `hpmcp.*` user data from earlier applies.

**Migration note (draft for the 0.10.0 changelog):**

> HocusScript (`.hocus`), the `source.*` workspace tools, compiled Bundles, and `production.asset.qualify` are removed from the HocusPocus MCP server. The last release containing them is tagged `hocusscript-final` (0.9.x). Agents should create and edit nodes directly (`node.*`, `parm.*`, `graph.batch_edit`) or submit a declarative JSON graph spec to `graph.apply_spec` (`dry_run=true` returns the diff; `mode=reconcile` removes only nodes owned by the given `ownership`). Existing scenes keep working: nodes stamped with `hpmcp.uid`/`hpmcp.owner` by earlier HocusScript applies are recognized as owned by the same ownership namespace. To convert an existing `.hocus` file, run `python -m hocuspocus.hocusscript compile` from the `hocusscript-final` tag and convert the bundle's expanded GraphSpec with the provided one-shot `scripts/convert_bundle_to_graph_spec.py` (modules and control flow are flattened). `[[source_workspace.projects]]` entries in startup config are ignored with a warning; remove them. The Source Workspaces panel is gone.

**Requirements for the cut to be safe:**
1. `graph.apply_spec` must read the legacy `hpmcp.*` keys, so reconcile on old scenes doesn't orphan or duplicate nodes.
2. Startup must tolerate stale `source_workspace` config and grant files.
3. Ship the one-shot converter before the cut, while the compiler still exists.
4. Untangle the `live/ops/document*.py` → `hocusscript.*` imports first: `document_editor_entities`, `document_runtime_contract`, `document_value_validation`, `document_provenance`, `build_provenance.canonical_digest`, `catalog.CatalogSnapshot`. Otherwise deleting the package breaks the kept engine.
