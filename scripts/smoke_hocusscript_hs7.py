"""Run installed Houdini acceptance for the HS7 indexed family slice.

The harness mutates only a disposable untitled scene, performs no cooks, and
fails with explicit evidence when a required SOP/MAT/LOP/TOP fixture is absent.

Usage:
    "C:\\Program Files\\Side Effects Software\\Houdini 22.0.368\\bin\\hython.exe" ^
        scripts\\smoke_hocusscript_hs7.py
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

import hou  # type: ignore

from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from smoke_hocusscript_h5 import (
    _H5SmokeOperations,
    _apply_success,
    _assert_installed_alignment,
    _export_recompile,
    _flat_export_bundle,
    _rollback_gate,
)
from smoke_hocusscript_hs7_acceptance import run_installed_hs7_acceptance
from smoke_hocusscript_hs7_support import (
    SUPPORTED_ROOTS,
    FixtureUnavailable,
    assert_zero_cooks,
    fixture_source,
    installed_module_receipt,
    select_family_fixture,
    structural_signature,
    unsupported_policy_evidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HS7_RUNTIME_MODULES = (
    "hocuspocus.hocusscript._carrier_versions",
    "hocuspocus.hocusscript._control_ast_validation",
    "hocuspocus.hocusscript._document_bundle_boundary",
    "hocuspocus.hocusscript.bundle_graph_validation",
    "hocuspocus.hocusscript.bundle_semantic_validation",
    "hocuspocus.hocusscript.catalog",
    "hocuspocus.hocusscript.contracts",
    "hocuspocus.hocusscript.control_artifact",
    "hocuspocus.hocusscript.control_compiler",
    "hocuspocus.hocusscript.control_expander",
    "hocuspocus.hocusscript.control_limits",
    "hocuspocus.hocusscript.control_lock_update",
    "hocuspocus.hocusscript.control_mixed_lock_update",
    "hocuspocus.hocusscript.control_mixed_resolution",
    "hocuspocus.hocusscript.control_resolver",
    "hocuspocus.hocusscript.control_value_budget",
    "hocuspocus.hocusscript.document_baseline_entities",
    "hocuspocus.hocusscript.document_bundle_lowering",
    "hocuspocus.hocusscript.document_bundle_semantics",
    "hocuspocus.hocusscript.document_editor_lowering",
    "hocuspocus.hocusscript.document_editor_entities",
    "hocuspocus.hocusscript.document_lowering",
    "hocuspocus.hocusscript.document_runtime_contract",
    "hocuspocus.hocusscript.document_runtime_lowering",
    "hocuspocus.hocusscript.document_tuple_lowering",
    "hocuspocus.hocusscript.document_value_lowering",
    "hocuspocus.hocusscript.document_value_validation",
    "hocuspocus.hocusscript.editor_carrier",
    "hocuspocus.hocusscript.editor_expansion",
    "hocuspocus.hocusscript.editor_format",
    "hocuspocus.hocusscript.editor_semantic",
    "hocuspocus.hocusscript.editor_syntax",
    "hocuspocus.hocusscript.export_editor_entities",
    "hocuspocus.hocusscript.export_named_ports",
    "hocuspocus.hocusscript.export_network_shape",
    "hocuspocus.hocusscript.export_ownership",
    "hocuspocus.hocusscript.export_runtime_entities",
    "hocuspocus.hocusscript.export_tagged_values",
    "hocuspocus.hocusscript.exporter",
    "hocuspocus.hocusscript.fidelity",
    "hocuspocus.hocusscript.formatter",
    "hocuspocus.hocusscript.model",
    "hocuspocus.hocusscript.modules",
    "hocuspocus.hocusscript.parser",
    "hocuspocus.hocusscript.parser_api",
    "hocuspocus.hocusscript.parser_editor_entities",
    "hocuspocus.hocusscript.parser_port_selectors",
    "hocuspocus.hocusscript.parser_runtime_entities",
    "hocuspocus.hocusscript.parser_tagged_values",
    "hocuspocus.hocusscript.port_selectors",
    "hocuspocus.hocusscript.project_build",
    "hocuspocus.hocusscript.project_lock_validation",
    "hocuspocus.hocusscript.project_manifest",
    "hocuspocus.hocusscript.project_services",
    "hocuspocus.hocusscript.runtime_carrier",
    "hocuspocus.hocusscript.runtime_expansion",
    "hocuspocus.hocusscript.runtime_pointers",
    "hocuspocus.hocusscript.runtime_semantic",
    "hocuspocus.hocusscript.runtime_syntax",
    "hocuspocus.hocusscript.semantic",
    "hocuspocus.hocusscript.semantic_carrier",
    "hocuspocus.hocusscript.value_carrier_validation",
    "hocuspocus.hocusscript.value_catalog_semantics",
    "hocuspocus.hocusscript.value_semantic_validation",
    "hocuspocus.live.operations",
    "hocuspocus.live.catalog_provider",
    "hocuspocus.live.ops.document_apply",
    "hocuspocus.live.ops.document_apply_managed",
    "hocuspocus.live.ops.document_apply_editor",
    "hocuspocus.live.ops.document_editor_entities",
    "hocuspocus.live.ops.document_editor_receipts",
    "hocuspocus.live.ops.document_network_families",
    "hocuspocus.live.ops.document_runtime_contract",
    "hocuspocus.live.ops.document_snapshot",
    "hocuspocus.live.ops.document_typed_apply",
    "hocuspocus.live.ops.document_typed_receipts",
    "hocuspocus.live.ops.document_validation",
    "hocuspocus.live.ops.hocusscript",
    "hocuspocus.live.ops.hocusscript_resources",
)


def _progress(stage: str) -> None:
    print(f"HS7_STAGE {stage}", file=sys.stderr, flush=True)


def _prepare_sop_root() -> None:
    root_path = SUPPORTED_ROOTS["sop"]
    if hou.node(root_path) is not None:
        raise RuntimeError(f"Refusing to reuse HS7 fixture root {root_path}.")
    parent = hou.node("/obj")
    if parent is None:
        raise FixtureUnavailable("sop", "Houdini /obj root is unavailable")
    parent.createNode(
        "geo",
        node_name=root_path.rsplit("/", 1)[-1],
        run_init_scripts=False,
        load_contents=False,
    )


def _prepare_top_root() -> None:
    root_path = SUPPORTED_ROOTS["top"]
    if hou.node(root_path) is not None:
        raise RuntimeError(f"Refusing to reuse HS7 fixture root {root_path}.")
    parent = hou.node("/tasks")
    if parent is None:
        raise FixtureUnavailable("top", "Houdini /tasks root is unavailable")
    parent.createNode(
        "topnet",
        node_name=root_path.rsplit("/", 1)[-1],
        run_init_scripts=False,
        load_contents=False,
    )


def _prepare_roots(operations: Any) -> None:
    _prepare_sop_root()
    _prepare_top_root()
    for family, root_path in SUPPORTED_ROOTS.items():
        root = hou.node(root_path)
        if root is None:
            raise FixtureUnavailable(
                family, "required root is unavailable", rootPath=root_path,
            )
        operations._document_stamp_live_node_uid(
            root_path, f"node:hs7:root:{family}"
        )
    operations._monitor.mark_dirty("hs7.roots.created")


def _apply_fixture(
    operations: Any,
    fixture: Any,
    context: RequestContext,
    *,
    root_cook_baseline: int,
) -> dict[str, Any]:
    first_bundle = _flat_export_bundle(
        fixture_source(
            fixture, mode="merge", include_connection=True, include_parameter=True,
        ),
        f"hocus-project://hs7-{fixture.family}/fixture.hocus",
        f"hs7-{fixture.family}",
        operations._catalog,
    )
    first_apply = _apply_success(
        operations, first_bundle.to_dict(), f"hs7-{fixture.family}-first", context,
    )
    first_document = operations._document_current_network_payload(
        fixture.root_path, force_sync=True
    )
    _assert_fixture_parameter(fixture)
    export = _export_recompile(
        operations, f"hs7_{fixture.family}", first_document,
        operations._catalog, context,
    )
    artist = hou.node(fixture.root_path).createNode(
        fixture.source_type_name,
        node_name=f"hs7_{fixture.family}_artist",
        run_init_scripts=False,
        load_contents=False,
    )
    artist_path = artist.path()
    operations._document_stamp_live_node_uid(
        artist_path, f"node:hs7:{fixture.family}:artist"
    )
    second_bundle = _flat_export_bundle(
        fixture_source(
            fixture, mode="reconcile",
            include_connection=False, include_parameter=False,
        ),
        f"hocus-project://hs7-{fixture.family}/fixture-reconcile.hocus",
        f"hs7-{fixture.family}",
        operations._catalog,
    )
    second_apply = _apply_success(
        operations, second_bundle.to_dict(), f"hs7-{fixture.family}-reconcile",
        context,
    )
    if hou.node(artist_path) is None:
        raise FixtureUnavailable(
            fixture.family,
            "reconcile removed artist-owned state",
            artistPath=artist_path,
        )
    _assert_fixture_reset_and_disconnect(fixture)
    rollback = _rollback_gate(
        operations, first_bundle.to_dict(), fixture.root_path, context,
        root_cook_baseline=root_cook_baseline,
    )
    document = operations._document_current_network_payload(
        fixture.root_path, force_sync=True
    )
    rejection = _export_rejection_evidence(
        operations, first_document, fixture,
    )
    signature = structural_signature(document, fixture)
    if len(signature["nodes"]) != 2:
        raise FixtureUnavailable(
            fixture.family,
            "reimport did not retain both fixture nodes",
            signature=signature,
        )
    return {
        "fixture": fixture,
        "document": document,
        "signature": signature,
        "apply": {
            "applied": True,
            "verified": True,
            "first": first_apply,
            "reconcile": second_apply,
        },
        "rollback": rollback,
        "export": export,
        "rejections": rejection,
        "cookCounts": assert_zero_cooks(hou, fixture),
    }


def _assert_fixture_parameter(fixture: Any) -> None:
    parm = hou.node(fixture.destination_path).parm(fixture.parm_name)
    if parm is None or parm.eval() != fixture.parm_value:
        raise FixtureUnavailable(
            fixture.family,
            "managed parameter assignment did not reach the live node",
            parmName=fixture.parm_name,
            expected=fixture.parm_value,
            actual=parm.eval() if parm is not None else None,
        )


def _assert_fixture_reset_and_disconnect(fixture: Any) -> None:
    node = hou.node(fixture.destination_path)
    parm = node.parm(fixture.parm_name) if node is not None else None
    inputs = node.inputConnections() if node is not None else ()
    if parm is None or not parm.isAtDefault():
        raise FixtureUnavailable(
            fixture.family,
            "reconcile did not reset the omitted managed parameter",
            parmName=fixture.parm_name,
        )
    if any(item.inputIndex() == fixture.input_index for item in inputs):
        raise FixtureUnavailable(
            fixture.family,
            "reconcile did not disconnect the omitted managed input",
            inputIndex=fixture.input_index,
        )


def _export_rejection_evidence(
    operations: Any,
    first_document: dict[str, Any],
    fixture: Any,
) -> dict[str, Any]:
    nested = json.loads(json.dumps(first_document))
    nested["nodes"].append({
        "uid": f"node:hs7:{fixture.family}:nested",
        "name": "nested",
        "typeName": "subnet",
        "category": fixture.category,
        "path": f"{fixture.root_path}/nested",
        "parentPath": fixture.root_path,
        "isNetwork": True,
        "position": [0.0, 0.0],
        "flags": {
            "display": False, "render": False,
            "bypass": False, "template": False,
        },
        "metadata": {"identityMode": "persistent_user_data"},
    })
    dynamic = _dynamic_connector_document(
        first_document, fixture, operations._catalog,
    )
    from hocuspocus.hocusscript.exporter import export_network_document
    results = {
        "nested": export_network_document(
            nested, graph_name=f"hs7_{fixture.family}_nested",
            catalog=operations._catalog,
        ),
        "dynamic": export_network_document(
            dynamic, graph_name=f"hs7_{fixture.family}_dynamic",
            catalog=operations._catalog,
        ),
    }
    evidence = {}
    for name, result in results.items():
        if result.valid:
            raise FixtureUnavailable(
                fixture.family,
                f"{name} export rejection unexpectedly succeeded",
            )
        evidence[name] = sorted({item.code for item in result.diagnostics})
    return evidence


def _dynamic_connector_document(
    document: dict[str, Any],
    fixture: Any,
    catalog: Any,
) -> dict[str, Any]:
    result = json.loads(json.dumps(document))
    candidate = next(
        (
            item for item in catalog.operators
            if item.category == fixture.category
            and any(
                connector.index is None or connector.cardinality == "many"
                for connector in (*item.inputs, *item.outputs)
            )
            and any(
                connector.index == fixture.output_index
                and connector.cardinality in {"one", "optional"}
                for connector in item.outputs
            )
        ),
        None,
    )
    source_uid = f"node:hs7:{fixture.family}:source"
    if candidate is not None and fixture.family != "sop":
        source = next(
            node for node in result["nodes"] if node.get("uid") == source_uid
        )
        source["typeName"] = candidate.qualified_name
        return result

    # SOP already has a mature indexed variadic lane.  Its fail-closed fixture
    # instead proves that an indexed edge without its exact port record cannot
    # be exported as if the connector were known.
    result["ports"] = [
        port for port in result["ports"]
        if not (
            port.get("nodeUid") == source_uid
            and port.get("direction") == "output"
            and port.get("index") == fixture.output_index
        )
    ]
    return result


def _save_reopen(
    operations: Any,
    accepted: dict[str, dict[str, Any]],
    hip_path: Path,
    context: RequestContext,
) -> dict[str, Any]:
    operations.scene_save_hip(
        {"path": str(hip_path), "save_to_recent_files": False},
        context,
    )
    operations.scene_new({}, context)
    operations._monitor.mark_dirty("hs7.scene.new")
    if hou.node(SUPPORTED_ROOTS["sop"]) is not None:
        raise RuntimeError("Disposable SOP root survived scene.new.")
    operations.scene_open_hip(
        {
            "path": str(hip_path),
            "suppress_save_prompt": True,
            "ignore_load_warnings": False,
        },
        context,
    )
    operations._monitor.mark_dirty("hs7.scene.reload")
    receipts = {}
    for family, record in accepted.items():
        fixture = record["fixture"]
        document = operations._document_current_network_payload(
            fixture.root_path, force_sync=True
        )
        signature = structural_signature(document, fixture)
        if signature != record["signature"]:
            raise FixtureUnavailable(
                family,
                "save/reopen changed the structural document signature",
                before=record["signature"],
                after=signature,
            )
        receipts[family] = {
            "signature": signature,
            "cookCounts": assert_zero_cooks(hou, fixture),
        }
    return receipts


def _locked_boundary_rejection(
    operations: Any,
    temporary_root: Path,
) -> dict[str, Any]:
    parent = hou.node("/obj")
    if parent is None:
        raise FixtureUnavailable("locked", "Houdini /obj root is unavailable")
    subnet = parent.createNode(
        "subnet",
        node_name="hs7_locked_boundary",
        run_init_scripts=False,
        load_contents=False,
    )
    subnet.createNode(
        "null",
        node_name="inside",
        run_init_scripts=False,
        load_contents=False,
    )
    try:
        asset = subnet.createDigitalAsset(
            name="hocus::hs7_locked_boundary::1.0",
            hda_file_name=str(temporary_root / "hs7_locked_boundary.hda"),
            description="HS7 locked-boundary acceptance",
            min_num_inputs=0,
            max_num_inputs=0,
        )
        asset.matchCurrentDefinition()
    except Exception as exc:
        raise FixtureUnavailable(
            "locked",
            "could not construct a disposable locked HDA boundary",
            errorType=exc.__class__.__name__,
        ) from exc
    operations._document_stamp_live_node_uid(
        asset.path(), "node:hs7:locked:root"
    )
    document = operations._document_current_network_payload(
        asset.path(), force_sync=True
    )
    diagnostics = operations._document_validate_network_document(document)
    codes = sorted({
        item.get("code")
        for item in diagnostics
        if isinstance(item, dict) and item.get("severity") == "error"
    })
    if "document.locked_hda_boundary" not in codes:
        raise FixtureUnavailable(
            "locked",
            "locked HDA document validation did not fail closed",
            diagnosticCodes=codes,
        )
    return {"diagnosticCodes": codes, "rootPath": asset.path()}


def _run_installed_hs7(temporary_root: Path) -> dict[str, Any]:
    _progress("installed-alignment")
    alignment = _assert_installed_alignment()
    installed_root = Path(str(hou.getenv("HOCUSPOCUS_ROOT"))).resolve()
    runtime_receipts = [
        installed_module_receipt(REPOSITORY_ROOT, installed_root, module)
        for module in HS7_RUNTIME_MODULES
    ]
    policy_receipt = installed_module_receipt(
        REPOSITORY_ROOT, installed_root,
        "hocuspocus.live.ops.document_network_families",
    )
    catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
    operations = _H5SmokeOperations(catalog, temporary_root)
    context = RequestContext(
        caller_id="hs7-installed-smoke",
        permissions=("observe", "edit_scene", "write_files"),
        timeout_seconds=300.0,
    )
    _prepare_roots(operations)

    accepted: dict[str, dict[str, Any]] = {}
    unavailable: list[dict[str, Any]] = []
    _progress("family-apply")
    for family in ("sop", "mat", "lop", "top"):
        try:
            fixture = select_family_fixture(hou, operations, family)
            root = hou.node(fixture.root_path)
            if root is None:
                raise FixtureUnavailable(
                    family, "fixture root vanished before application",
                    rootPath=fixture.root_path,
                )
            accepted[family] = _apply_fixture(
                operations,
                fixture,
                context,
                root_cook_baseline=int(root.cookCount()),
            )
        except FixtureUnavailable as exc:
            unavailable.append(exc.evidence)

    _progress("unsupported-policy")
    rejected = unsupported_policy_evidence(operations)
    locked = _locked_boundary_rejection(operations, temporary_root)
    _progress("save-reopen")
    reopened = _save_reopen(
        operations,
        accepted,
        temporary_root / "hs7-family-acceptance.hip",
        context,
    )
    _progress("installed-acceptance-extension")
    installed_acceptance = run_installed_hs7_acceptance(temporary_root)
    result = {
        "accepted": not unavailable and set(accepted) == set(SUPPORTED_ROOTS),
        "houdiniVersion": hou.applicationVersionString(),
        "installedAlignmentModuleCount": len(alignment["modules"]),
        "policyModuleReceipt": policy_receipt,
        "runtimeModuleReceipts": runtime_receipts,
        "families": {
            family: {
                "rootPath": record["fixture"].root_path,
                "category": record["fixture"].category,
                "sourceNodeType": record["fixture"].source_type_name,
                "destinationNodeType": record["fixture"].destination_type_name,
                "inputIndex": record["fixture"].input_index,
                "outputIndex": record["fixture"].output_index,
                "inputName": record["fixture"].input_name,
                "outputName": record["fixture"].output_name,
                "parameter": {
                    "name": record["fixture"].parm_name,
                    "default": record["fixture"].parm_default,
                    "assigned": record["fixture"].parm_value,
                },
                "apply": record["apply"],
                "rollback": record["rollback"],
                "export": record["export"],
                "rejections": record["rejections"],
                "initialCookCounts": record["cookCounts"],
                "saveReopen": reopened.get(family),
            }
            for family, record in sorted(accepted.items())
        },
        "unsupportedPolicyRejections": rejected,
        "lockedBoundaryRejection": locked,
        "installedAcceptance": installed_acceptance,
        "unavailableFixtureEvidence": unavailable,
        "cookExecuted": any(
            count != 0
            for record in accepted.values()
            for count in record["cookCounts"].values()
        ) or any(
            count != 0
            for record in reopened.values()
            for count in record["cookCounts"].values()
        ) or installed_acceptance["cookExecuted"],
    }
    if not result["accepted"]:
        raise FixtureUnavailable(
            "hs7",
            "one or more required family fixtures were unavailable",
            result=result,
        )
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            "HS7 installed acceptance requires Houdini 22.0.368, got "
            f"{hou.applicationVersionString()}."
        )
    temporary = tempfile.TemporaryDirectory(prefix="hocuspocus-hs7-")
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        try:
            result = _run_installed_hs7(Path(temporary.name).resolve())
        except FixtureUnavailable as exc:
            print(json.dumps({
                "accepted": False,
                "unavailableFixtureEvidence": [exc.evidence],
            }, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        try:
            hou.hipFile.clear(suppress_save_prompt=True)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
