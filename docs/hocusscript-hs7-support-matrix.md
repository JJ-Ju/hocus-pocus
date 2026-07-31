# HocusScript HS7 Fidelity Matrix

This matrix is a contract, not a broad statement that every Houdini graph is
interchangeable. `supported` means source, catalog, carrier, network document,
guarded live apply, save/reopen, rollback, and structural export recompilation
plus exact-catalog semantic/connector validation have defined rules. It does
not mean exported source reconstructs an interchangeable network. Anything
without that evidence remains
`read-only`, `preserved-opaque`, or `rejected`.

The same runtime policy is available as the read-only MCP resource
`houdini://documents/hocusscript/fidelity/hs7`. It is enumerated with the
server's static resources after the configured transport authorization check,
requires no source-workspace grant, and contains no scene, project, source-file,
or physical-path state.

## Status meanings

| Status | Contract |
| --- | --- |
| supported | May be authored and guarded-applied within the stated constraints. |
| read-only | May be inspected, but source apply cannot claim or replace it. |
| preserved-opaque | Existing artist state is retained but cannot be authored by the DSL. |
| rejected | Admission fails before mutation. |

## Network families

| Family | Status | Authored surface | Explicit boundary |
| --- | --- | --- | --- |
| SOP and OBJ-contained SOP | supported | Catalog-resolved nodes, indexed inputs, nonzero indexed outputs, scalar/menu/code parameters, managed flags and positions | Editable networks only; no locked HDA contents |
| Material builders and fixed-port VOP | supported | Structural nodes, exact indexed or fixed-name connections, catalog-backed parameters | Dynamic or incomplete connector layouts reject; no HDA definition edits |
| LOP/Solaris | supported | Structural LOP nodes, exact connections, catalog-backed node parameters | Direct USD layer, relationship, variant, and time-sample authoring is rejected unless represented by a supported node parameter |
| TOP/PDG | supported | Structural TOP nodes, exact connections, catalog-backed node parameters | Schedulers, work items, cook state, and execution remain read-only |
| ROP | read-only | Inspection through the existing render surfaces | Declarative apply and render execution are rejected |
| DOP | read-only | Inspection | Simulation graph/state mutation is rejected |
| COP | read-only | Inspection | Declarative graph mutation is rejected; no round-trip claim is made |
| CHOP | read-only | Inspection | Declarative graph mutation is rejected; no round-trip claim is made |
| HDA definition contents | rejected | None | Requires a separate definition-authoring and library-publication contract |

## Values and graph-editor state

| Construct | Current status | Version lane and rule |
| --- | --- | --- |
| Indexed and multi-output connections | supported | Frozen lanes retain exact source/destination indexes; authenticated names are verification metadata |
| Authored named port selectors | supported | Language 0.4 / GraphSpec 0.5; exact unique fixed names lower to authoritative indexes, while ambiguous or dynamic names reject |
| Scalar values and menu tokens | supported | Menu tokens are accepted; display labels are not silently converted |
| Whole tuples | supported | Language 0.4 / GraphSpec 0.5 / Bundle 0.5 requires exact ordered component-token evidence and lowers to scalar document bindings |
| Units | supported | `quantity` requires catalog-v2 dimension evidence and converts to the declared canonical unit |
| Raw paths | supported | Explicit `raw_path` is distinct from portable node and parameter references |
| Managed reset by omission | supported | Reconcile resets only fields previously recorded as compiler-managed |
| Explicit reset | supported | `reset` is first-class and verifies `parm.isAtDefault()` after apply |
| Ramps | supported | Float/color points and basis enums use catalog v2 and network-document v2; generic-array approximation is rejected |
| Multiparms | supported | Exact start offset, child tokens, bounds, shrink semantics, rollback, and default restoration are required; live HOM child coordinates are nested/opaque rather than independent bindings |
| Expressions | supported | Exact fixed-language expression text round-trips on compatible catalog parameters |
| Structural channel references | supported | Authored references use durable node identity and resolve to the realized live path |
| Code blobs | supported | Only catalog-declared surfaces and languages; `run_code` capability is mandatory |
| Callbacks and buttons | rejected | Actions are never smuggled through declarative values; a separate confirmed action contract is required |
| Spare parameters | supported | Managed instance float/tuple, int, string, toggle, and menu interfaces are receipt-authenticated; artist spares survive reconcile |
| Numeric keyframes | supported | Scalar float/int keys use seconds plus fixed constant/linear/bezier interpolation and bounded extrapolation |
| USD time samples | rejected | Requires a separate authored-layer and stage-ownership contract |
| Node positions and automatic layout | supported | Positions and bounded deterministic auto-layout are managed selectively |
| Boxes, dots, stickies, comments, layout constraints | supported | Stable IDs and network-document v2 entities preserve exact membership, routed inputs, annotations, and deterministic constraints |
| Locked HDA boundaries | rejected | Validation fails before planning or mutation |

## Qualification gates

Every family promoted to `supported` needs a real installed-Houdini fixture
covering:

1. create, indexed connect with a nonzero output, disconnect, parameter update,
   and managed reset;
2. import/preview/plan/apply/reimport equivalence;
3. reconcile preservation of artist-owned state;
4. rollback injection at each executor phase;
5. save/reopen identity and provenance;
6. structural export recompilation and exact-catalog semantic/connector
   validation for every advertised value, without a network-reconstruction
   guarantee;
7. locked/nested/dynamic-port rejection;
8. zero cooks unless the contract explicitly authorizes a cook.

For values, equivalence is semantic and catalog-bound. It is never inferred by
stringifying an unsupported HOM object or by placing arbitrary JSON in
metadata.

## Final acceptance

Installed Houdini 22.0.368 accepted the SOP, fixed-port material/VOP, LOP, and
TOP family fixtures plus the graph-editor, runtime, and typed-value extension.
The matrix covered guarded create/reconcile, save/reopen, structural export
recompilation with exact-catalog semantic/connector validation, artist-state
preservation, exact default reset, locked/dynamic/nested
rejection, and injected rollback. All managed descendants recorded zero cooks,
37 acceptance-critical source/install/running module receipts aligned, no
fixture was unavailable, and all four unsupported family policies failed
closed. The complete H22 catalog measured 44,342,922 UTF-8 bytes across 5,566
operators, inside the 64 MiB admission bound.
