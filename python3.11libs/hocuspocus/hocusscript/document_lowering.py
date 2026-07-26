"""Pure HS3 lowering from a resolved bundle and baseline to document preview artifacts.

This module deliberately has no Houdini, filesystem, graph-store, or MCP dependency.  It
builds a candidate document and plan only; persistence and execution belong to HS4.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .bundle import BUNDLE_VERSION, CompiledBundle, decode_compiled_bundle
from .semantic import SemanticResult

DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/network-document/v1"
PREVIEW_VERSION = "0.1"


class DocumentLoweringError(ValueError):
    """Typed rejection when a bundle cannot safely become a document preview."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class DocumentPreview:
    """Detached, deterministic HS3 preview output."""

    document: dict[str, Any]
    diff: dict[str, Any]
    destructive_summary: dict[str, Any]
    candidate_plan: dict[str, Any] | None
    source_maps: dict[str, Any]
    provenance: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...]

    @property
    def valid(self) -> bool:
        return not any(item.get("severity") == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "stage": "document_preview",
            "previewVersion": PREVIEW_VERSION,
            "valid": self.valid,
            "readyForApply": False,
            "document": self.document,
            "diff": self.diff,
            "destructiveSummary": self.destructive_summary,
            "candidatePlan": self.candidate_plan,
            "sourceMaps": self.source_maps,
            "provenance": self.provenance,
            "diagnostics": list(self.diagnostics),
        })


def lower_bundle_to_document(
    bundle: CompiledBundle | dict[str, Any], baseline_document: dict[str, Any],
    *, _trusted_semantic_result: SemanticResult | None = None,
) -> DocumentPreview:
    """Lower a resolved semantic bundle over an explicit network-document baseline."""
    work = _prepare_lowering(bundle, baseline_document, _trusted_semantic_result)
    _reconcile_baseline(work)
    _lower_external_nodes(work)
    _lower_authored_nodes(work)
    _lower_display_render_and_layout(work)
    _lower_parameters(work)
    _lower_connections_and_output(work)
    _record_managed_fields(work)
    return _finish_lowering(work)


@dataclass(slots=True)
class _LoweringWork:
    payload: dict[str, Any]
    bundle_digest: str
    semantic: dict[str, Any]
    baseline: dict[str, Any]
    graph: dict[str, Any]
    target: str
    provenance: dict[str, Any]
    ownership: str | None
    diagnostics: list[dict[str, Any]]
    document: dict[str, Any]
    source_map_entities: dict[str, dict[str, Any]]
    adoption_source_maps: dict[str, dict[str, Any]]
    nodes_by_uid: dict[str, dict[str, Any]]
    nodes_by_path: dict[str, dict[str, Any]]
    external_by_symbol: dict[str, dict[str, Any]]
    generated_by_symbol: dict[str, dict[str, Any]]
    adopted_uids: set[str]
    provenance_update_uids: set[str]


def _prepare_lowering(
    bundle: CompiledBundle | dict[str, Any],
    baseline_document: dict[str, Any],
    trusted_semantic_result: SemanticResult | None,
) -> _LoweringWork:
    decoded = decode_compiled_bundle(bundle.to_dict() if isinstance(bundle, CompiledBundle) else bundle)
    payload = decoded.to_dict()
    if payload["bundleVersion"] != BUNDLE_VERSION or "semanticResolution" not in payload:
        raise DocumentLoweringError("HOCUS700", "Document lowering requires a resolved bundle v0.2.")
    semantic = (
        trusted_semantic_result.to_dict()
        if trusted_semantic_result is not None
        else payload["semanticResolution"]
    )
    if semantic.get("catalogFingerprint") != payload["catalogConstraints"]["fingerprint"]:
        raise DocumentLoweringError("HOCUS701", "Semantic resolution does not match the bundle catalog pin.")
    if not semantic.get("valid") or not semantic.get("readyForDocumentLowering"):
        raise DocumentLoweringError(
            "HOCUS701", "Semantic resolution is not ready for document lowering.",
            details={"deferredChecks": semantic.get("deferredChecks", [])},
        )
    if not payload.get("portable"):
        raise DocumentLoweringError("HOCUS702", "Document lowering requires portable project provenance.")
    baseline = _validate_and_copy_baseline(baseline_document)
    graph = payload["graphSpec"]
    target = graph["target"]
    if baseline["rootPath"] != target:
        raise DocumentLoweringError(
            "HOCUS703", "Baseline rootPath must exactly match the GraphSpec target.",
            details={"baselineRootPath": baseline["rootPath"], "target": target},
        )
    document = copy.deepcopy(baseline)
    document.setdefault("ports", [])
    document.setdefault("metadata", {})
    return _LoweringWork(
        payload, decoded.digest, semantic, baseline, graph, target,
        _provenance(payload, decoded.digest, baseline), graph.get("ownership"), [],
        document, {}, {}, _by_uid(document.get("nodes", [])),
        {item["path"]: item for item in document.get("nodes", [])},
        {}, {}, set(), set(),
    )


def _reconcile_baseline(work: _LoweringWork) -> None:
    expected_revision = work.graph.get("expectedRevision")
    if expected_revision is not None and expected_revision != work.baseline["documentRevision"]:
        work.diagnostics.append(_diagnostic(
            "HOCUS721", "The bundle expected document revision does not match the supplied baseline.",
            "/expectedRevision", work.target,
        ))
    mode = work.graph["mode"]
    if mode == "reconcile" and not work.ownership:
        raise DocumentLoweringError("HOCUS704", "Reconcile lowering requires an ownership namespace.")
    if mode != "reconcile":
        return
    preserved_paths = {item["path"] for item in work.graph["externalNodes"] if item["adopted"]}
    work.diagnostics.extend(
        _protected_owned_dependency_diagnostics(work.document, work.ownership, preserved_paths)
    )
    for entity_uid in _remove_owned_state(work.document, work.ownership, preserved_paths):
        work.diagnostics.append(_diagnostic(
            "HOCUS713", "Owned baseline state cannot be reconciled without durable source provenance.",
            "/baselineDocument", entity_uid=entity_uid,
        ))


def _lower_external_nodes(work: _LoweringWork) -> None:
    identity_keys = ("entityKind", "projectUid", "sourceUri", "graphName", "symbol", "ownership")
    for index, external in enumerate(work.graph["externalNodes"]):
        node = work.nodes_by_path.get(external["path"])
        if node is None:
            work.diagnostics.append(_diagnostic(
                "HOCUS705", f"External node '{external['symbol']}' is absent from the baseline.",
                f"/graphSpec/externalNodes/{index}/path", external["path"],
            ))
            continue
        work.external_by_symbol[external["symbol"]] = node
        if not external["adopted"]:
            continue
        if not work.ownership:
            work.diagnostics.append(_diagnostic(
                "HOCUS712", f"Adopting external node '{external['symbol']}' requires an ownership namespace.",
                f"/graphSpec/externalNodes/{index}", external["path"], node.get("uid"),
            ))
            continue
        authored_metadata = _entity_metadata(
            work.payload, work.bundle_digest, work.graph, external["symbol"],
            f"/externalNodes/{index}", external.get("span"), work.ownership,
            entity_kind="adopted_node",
        )
        previous_metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        previous_hocus = previous_metadata.get("hocus") if isinstance(previous_metadata, dict) else None
        authored_hocus = authored_metadata["hocus"]
        same_adoption = isinstance(previous_hocus, dict) and all(
            previous_hocus.get(key) == authored_hocus.get(key) for key in identity_keys
        )
        if not same_adoption:
            work.adopted_uids.add(node["uid"])
        elif previous_hocus != authored_hocus:
            work.provenance_update_uids.add(node["uid"])
        node["metadata"] = _merged_metadata(node.get("metadata"), authored_metadata)
        source_map = _source_map(work.payload, f"/externalNodes/{index}", external.get("span"))
        work.source_map_entities[node["uid"]] = source_map
        work.adoption_source_maps[node["uid"]] = copy.deepcopy(source_map)


def _lower_authored_nodes(work: _LoweringWork) -> None:
    selections = {item["nodeSymbol"]: item for item in work.semantic["operatorSelections"]}
    for index, node_spec in enumerate(work.graph["nodes"]):
        symbol = node_spec["symbol"]
        uid = node_spec.get("explicitId") or _uid("node", work.payload, work.graph["name"], symbol)
        path = f"{work.target.rstrip('/')}/{symbol}"
        previous = work.nodes_by_uid.get(uid)
        old_path = _validate_node_destination(work, node_spec, index, uid, path, previous)
        if old_path is False:
            continue
        if isinstance(old_path, str):
            work.nodes_by_path.pop(old_path, None)
        generated = _authored_node(work, node_spec, index, uid, path, previous, selections[symbol])
        _upsert_by_uid(work.document["nodes"], generated)
        work.nodes_by_uid[uid] = generated
        work.nodes_by_path[path] = generated
        work.generated_by_symbol[symbol] = generated
        work.source_map_entities[uid] = _source_map(work.payload, f"/nodes/{index}", node_spec.get("span"))


def _validate_node_destination(
    work: _LoweringWork, node_spec: dict[str, Any], index: int, uid: str,
    path: str, previous: dict[str, Any] | None,
) -> str | bool | None:
    old_path: str | None = None
    if previous is not None and previous.get("path") != path:
        if node_spec.get("explicitId") is None or not _managed_explicit_rename_candidate(
            previous, work.payload, work.graph, work.ownership
        ):
            work.diagnostics.append(_diagnostic(
                "HOCUS706", f"Node ID '{uid}' belongs to a different path without matching managed provenance.",
                f"/graphSpec/nodes/{index}/explicitId", path, entity_uid=uid,
            ))
            return False
        old_path = str(previous.get("path", ""))
    collision = work.nodes_by_path.get(path)
    if collision is not None and collision.get("uid") != uid:
        work.diagnostics.append(_diagnostic(
            "HOCUS706", f"Authored path '{path}' collides with a differently-owned baseline node.",
            f"/graphSpec/nodes/{index}/symbol", path, entity_uid=collision.get("uid"),
        ))
        return False
    return old_path


def _authored_node(
    work: _LoweringWork, node_spec: dict[str, Any], index: int, uid: str, path: str,
    previous: dict[str, Any] | None, selection: dict[str, Any],
) -> dict[str, Any]:
    symbol = node_spec["symbol"]
    flags = copy.deepcopy(previous.get("flags")) if previous is not None else _default_flags()
    if work.graph.get("display") == symbol:
        flags["display"] = True
    if work.graph.get("render") == symbol:
        flags["render"] = True
    metadata = _entity_metadata(
        work.payload, work.bundle_digest, work.graph, symbol, f"/nodes/{index}",
        node_spec.get("span"), work.ownership, entity_kind="node",
    )
    if work.graph.get("output") == symbol:
        metadata["output"] = True
    return {
        "uid": uid, "name": symbol, "typeName": selection["qualifiedName"],
        "category": selection["category"], "path": path, "parentPath": work.target,
        "isNetwork": bool(previous.get("isNetwork", False)) if previous is not None else False,
        "position": copy.deepcopy(previous.get("position")) if previous is not None else None,
        "flags": flags,
        "definitionRef": {
            "qualifiedName": selection["qualifiedName"], "namespace": selection["namespace"],
            "version": selection["version"], "sourceKind": selection["sourceKind"],
            "definitionDigest": selection["definitionDigest"],
        },
        "metadata": _merged_metadata(previous.get("metadata") if previous else None, metadata),
    }


def _lower_display_render_and_layout(work: _LoweringWork) -> None:
    for flag_name in ("display", "render"):
        directive = work.graph.get(flag_name)
        selected = work.generated_by_symbol.get(directive) or work.external_by_symbol.get(directive)
        if directive is None or selected is None:
            continue
        span = work.graph.get("fieldSpans", {}).get(flag_name, work.graph.get("span"))
        selected_flags = selected.get("flags")
        if isinstance(selected_flags, dict):
            selected_flags[flag_name] = True
            work.source_map_entities[selected["uid"]] = _source_map(work.payload, f"/{flag_name}", span)
        for node in work.document["nodes"]:
            flags = node.get("flags")
            if isinstance(flags, dict) and node.get("uid") != selected.get("uid") and bool(flags.get(flag_name)):
                flags[flag_name] = False
                work.source_map_entities.setdefault(
                    node["uid"], _source_map(work.payload, f"/{flag_name}", span)
                )
    if work.graph.get("layout") == "auto":
        _lower_auto_layout(work)


def _lower_auto_layout(work: _LoweringWork) -> None:
    span = work.graph.get("fieldSpans", {}).get("layout", work.graph.get("span"))
    layout_nodes = [
        work.generated_by_symbol[item["symbol"]]
        for item in work.graph["nodes"] if item["symbol"] in work.generated_by_symbol
    ]
    layout_uids = {node["uid"] for node in layout_nodes}
    occupied: set[tuple[int, int]] = set()
    for existing in work.document["nodes"]:
        position = existing.get("position")
        if existing.get("uid") in layout_uids or not isinstance(position, list) or len(position) != 2:
            continue
        column = int(round(float(position[0]) / 3.25))
        row = int(round(-float(position[1]) / 1.85))
        if 0 <= column < 12 and 0 <= row < 64:
            occupied.add((column, row))
    free_cells = [
        (column, row) for row in range(64) for column in range(12)
        if (column, row) not in occupied
    ]
    if len(layout_nodes) > len(free_cells):
        work.diagnostics.append(_diagnostic(
            "HOCUS714", "Automatic layout exceeds the bounded 12 by 64 managed network grid.", "/layout"
        ))
    for node, (column, row) in zip(layout_nodes, free_cells):
        node["position"] = [float(column * 3.25), float(-row * 1.85)]
        work.source_map_entities[node["uid"]] = _source_map(work.payload, "/layout", span)


def _lower_parameters(work: _LoweringWork) -> None:
    selections = {
        (item["nodeIndex"], item["parmIndex"]): item
        for item in work.semantic["parameterSelections"]
    }
    for node_index, node_spec in enumerate(work.graph["nodes"]):
        target_node = work.generated_by_symbol.get(node_spec["symbol"])
        if target_node is None:
            continue
        for parm_index, parm in enumerate(node_spec["parms"]):
            _lower_parameter(
                work, node_spec, target_node, parm, node_index, parm_index,
                selections[(node_index, parm_index)],
            )


def _lower_parameter(
    work: _LoweringWork, node_spec: dict[str, Any], target_node: dict[str, Any],
    parm: dict[str, Any], node_index: int, parm_index: int, selection: dict[str, Any],
) -> None:
    pointer = f"/nodes/{node_index}/parms/{parm_index}"
    parm_name = (
        selection["authoredToken"]
        if selection["componentIndex"] is not None else selection["parameterToken"]
    )
    value = parm["value"]
    binding_uid = _binding_uid(target_node["uid"], parm_name)
    metadata = _entity_metadata(
        work.payload, work.bundle_digest, work.graph, node_spec["symbol"], pointer,
        parm.get("span"), work.ownership, entity_kind="parameter_binding",
    )
    metadata["parameterSelection"] = {
        key: selection[key] for key in (
            "authoredToken", "parameterToken", "componentIndex", "valueType", "conversion", "menuToken"
        )
    }
    binding: dict[str, Any] = {
        "uid": binding_uid, "nodeUid": target_node["uid"], "parmName": parm_name,
        "valueMode": "literal", "metadata": metadata,
    }
    if value["kind"] == "code":
        if not _lower_code_parameter(work, node_spec, target_node, value, binding, pointer, parm_name):
            return
    elif value["kind"] == "array":
        work.diagnostics.append(_diagnostic(
            "HOCUS708",
            f"Whole-tuple parameter '{selection['parameterToken']}' cannot be lowered because "
            "the resolved bundle does not carry its component token mapping; author scalar "
            "components until that mapping is versioned.",
            f"/graphSpec{pointer}/value", target_node["path"], target_node["uid"],
        ))
        return
    else:
        binding["value"] = _literal_value(value)
    _replace_binding(work.document["parameterBindings"], binding)
    work.source_map_entities[binding_uid] = _source_map(work.payload, pointer, parm.get("span"))


def _lower_code_parameter(
    work: _LoweringWork, node_spec: dict[str, Any], target_node: dict[str, Any],
    value: dict[str, Any], binding: dict[str, Any], pointer: str, parm_name: str,
) -> bool:
    language = value["language"]
    if language not in {"vex", "python", "hscript"}:
        work.diagnostics.append(_diagnostic(
            "HOCUS707", f"Code language '{language}' has no network-document representation.",
            f"/graphSpec{pointer}/value/language", target_node["path"], target_node["uid"],
        ))
        return False
    blob_uid = _code_blob_uid(target_node["uid"], parm_name)
    binding["valueMode"] = "code_reference"
    binding["codeBlobUid"] = blob_uid
    blob = {
        "uid": blob_uid, "language": language,
        "target": {"nodeUid": target_node["uid"], "parmName": parm_name, "bindingUid": binding["uid"]},
        "body": value["body"],
        "metadata": _entity_metadata(
            work.payload, work.bundle_digest, work.graph, node_spec["symbol"], f"{pointer}/value",
            value.get("span"), work.ownership, entity_kind="code_blob",
        ),
    }
    _replace_code_blob(work.document["codeBlobs"], blob)
    work.source_map_entities[blob_uid] = _source_map(work.payload, f"{pointer}/value", value.get("span"))
    return True


def _lower_connections_and_output(work: _LoweringWork) -> None:
    selections = {
        (item["nodeIndex"], item["inputIndex"]): item
        for item in work.semantic["connectionSelections"]
    }
    for node_index, node_spec in enumerate(work.graph["nodes"]):
        dest = work.generated_by_symbol.get(node_spec["symbol"])
        if dest is None:
            continue
        for input_offset, input_spec in enumerate(node_spec["inputs"]):
            selection = selections[(node_index, input_spec["index"])]
            source = (
                work.generated_by_symbol.get(selection["sourceSymbol"])
                or work.external_by_symbol.get(selection["sourceSymbol"])
            )
            if source is not None:
                _lower_connection(work, node_spec, source, dest, input_spec, selection, node_index, input_offset)
    _lower_output(work)


def _lower_connection(
    work: _LoweringWork, node_spec: dict[str, Any], source: dict[str, Any],
    dest: dict[str, Any], input_spec: dict[str, Any], selection: dict[str, Any],
    node_index: int, input_offset: int,
) -> None:
    pointer = f"/nodes/{node_index}/inputs/{input_offset}"
    edge_uid = _edge_uid(dest["uid"], selection["inputIndex"])
    endpoint_from: dict[str, Any] = {"nodeUid": source["uid"], "portIndex": selection["outputIndex"]}
    endpoint_to: dict[str, Any] = {"nodeUid": dest["uid"], "portIndex": selection["inputIndex"]}
    if selection["outputName"] is not None:
        endpoint_from["portName"] = selection["outputName"]
    if selection["inputName"] is not None:
        endpoint_to["portName"] = selection["inputName"]
    metadata = _entity_metadata(
        work.payload, work.bundle_digest, work.graph, node_spec["symbol"], pointer,
        input_spec.get("span"), work.ownership, entity_kind="edge",
    )
    _replace_edge(work.document["edges"], {
        "uid": edge_uid, "kind": "data", "from": endpoint_from, "to": endpoint_to,
        "metadata": metadata,
    })
    work.source_map_entities[edge_uid] = _source_map(work.payload, pointer, input_spec.get("span"))
    for direction, endpoint, name, index in (
        ("output", source, selection["outputName"], selection["outputIndex"]),
        ("input", dest, selection["inputName"], selection["inputIndex"]),
    ):
        port_uid = _port_uid(endpoint["uid"], direction, index)
        _replace_port(work.document["ports"], {
            "uid": port_uid, "nodeUid": endpoint["uid"], "direction": direction,
            "name": name or "", "index": index, "kind": "data",
            "metadata": {**metadata, "hocus": {**metadata["hocus"], "entityKind": "port"}},
        })
        work.source_map_entities[port_uid] = _source_map(work.payload, pointer, input_spec.get("span"))


def _lower_output(work: _LoweringWork) -> None:
    output_symbol = work.graph.get("output")
    if output_symbol is None:
        return
    output_node = work.generated_by_symbol.get(output_symbol) or work.external_by_symbol.get(output_symbol)
    root_node = work.nodes_by_path.get(work.target)
    if output_node is None or root_node is None:
        return
    span = work.graph.get("fieldSpans", {}).get("output", work.graph.get("span"))
    output_uid = f"edge:output:{root_node['uid']}"
    _replace_edge(work.document["edges"], {
        "uid": output_uid, "kind": "output_flag",
        "from": {"nodeUid": output_node["uid"]}, "to": {"nodeUid": root_node["uid"]},
        "metadata": _entity_metadata(
            work.payload, work.bundle_digest, work.graph, output_symbol, "/output", span,
            work.ownership, entity_kind="output_flag",
        ),
    })
    work.source_map_entities[output_uid] = _source_map(work.payload, "/output", span)


def _record_managed_fields(work: _LoweringWork) -> None:
    parameters_by_node: dict[int, list[str]] = {}
    for selection in work.semantic["parameterSelections"]:
        token = (
            selection["authoredToken"]
            if selection["componentIndex"] is not None else selection["parameterToken"]
        )
        parameters_by_node.setdefault(selection["nodeIndex"], []).append(token)
    for node_index, node_spec in enumerate(work.graph["nodes"]):
        generated = work.generated_by_symbol.get(node_spec["symbol"])
        metadata = generated.get("metadata") if isinstance(generated, dict) else None
        hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
        if not isinstance(hocus, dict):
            continue
        hocus["managedFields"] = {
            "type": True, "inputs": sorted(item["index"] for item in node_spec["inputs"]),
            "parameters": sorted(parameters_by_node.get(node_index, [])),
            "flags": _managed_flags(work.graph, node_spec["symbol"]),
            "nodeUid": str(generated["uid"]),
        }


def _managed_flags(graph: dict[str, Any], symbol: str) -> dict[str, bool]:
    return {
        name: graph.get(name) == symbol
        for name in ("display", "render", "output")
        if graph.get(name) is not None
    }


def _finish_lowering(work: _LoweringWork) -> DocumentPreview:
    _canonicalize_document(work.document)
    preliminary_diff = _document_diff(work.baseline, work.document)
    work.document["documentRevision"] = work.baseline["documentRevision"] + int(
        bool(preliminary_diff["summary"]["totalChangeCount"])
    )
    work.document["baselineLiveRevision"] = int(
        work.baseline.get("lastSyncedLiveRevision", work.baseline.get("baselineLiveRevision", 0))
    )
    work.document["lastSyncedLiveRevision"] = int(work.baseline.get("lastSyncedLiveRevision", 0))
    work.document["metadata"] = _merged_metadata(
        work.document.get("metadata"), {"hocusPreview": work.provenance}
    )
    work.document["diagnostics"] = sorted(
        work.diagnostics, key=lambda item: (item.get("jsonPointer", ""), item["code"])
    )
    _canonicalize_document(work.document)
    _validate_and_copy_baseline(work.document)
    diff = _document_diff(work.baseline, work.document)
    destructive = _destructive_summary(diff, work.adopted_uids)
    source_maps = {
        "format": "document-entity-spans-v0.1",
        "entrySourceUri": work.payload["entrySource"]["uri"],
        "entities": {
            key: work.source_map_entities[key] for key in sorted(work.source_map_entities)
        },
        "adoptions": {
            key: work.adoption_source_maps[key] for key in sorted(work.adoption_source_maps)
        },
        "operations": {},
    }
    candidate_plan = None
    if not work.diagnostics:
        candidate_plan = _candidate_plan(
            work.payload, work.bundle_digest, work.baseline, work.document, diff,
            work.ownership, source_maps, work.adopted_uids, work.provenance_update_uids,
        )
    return DocumentPreview(
        work.document, diff, destructive, candidate_plan, source_maps,
        work.provenance, tuple(work.document["diagnostics"]),
    )


def _validate_and_copy_baseline(value: Any) -> dict[str, Any]:
    _validate_baseline_envelope(value)
    result = copy.deepcopy(value)
    result.setdefault("ports", [])
    result.setdefault("metadata", {})
    _validate_baseline_uids(result)
    _validate_baseline_entities(result)
    return result


def _validate_baseline_envelope(value: Any) -> None:
    if not isinstance(value, dict):
        raise DocumentLoweringError("HOCUS710", "Baseline document must be an object.")
    required = {"$schema", "kind", "documentId", "documentRevision", "rootPath", "category",
                "nodes", "edges", "parameterBindings", "codeBlobs", "diagnostics"}
    missing = sorted(required - set(value))
    if missing:
        raise DocumentLoweringError("HOCUS710", "Baseline document is missing required fields.", details={"missing": missing})
    if value["$schema"] != DOCUMENT_SCHEMA_URI or value["kind"] != "network_document":
        raise DocumentLoweringError("HOCUS710", "Baseline must be a network-document v1 value.")
    if type(value["documentRevision"]) is not int or value["documentRevision"] < 0:
        raise DocumentLoweringError("HOCUS710", "Baseline documentRevision must be a non-negative integer.")
    if not isinstance(value["rootPath"], str) or not value["rootPath"].startswith("/"):
        raise DocumentLoweringError("HOCUS710", "Baseline rootPath must be absolute.")
    if not isinstance(value["documentId"], str) or not value["documentId"].startswith("network:"):
        raise DocumentLoweringError("HOCUS710", "Baseline documentId must use the network namespace.")
    if not isinstance(value["category"], str) or not value["category"]:
        raise DocumentLoweringError("HOCUS710", "Baseline category must be non-empty.")
    for field in ("nodes", "edges", "parameterBindings", "codeBlobs", "diagnostics"):
        if not isinstance(value[field], list):
            raise DocumentLoweringError("HOCUS710", f"Baseline {field} must be an array.")


def _validate_baseline_uids(result: dict[str, Any]) -> None:
    seen: set[str] = set()
    for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs"):
        for item in result[field]:
            uid = item.get("uid") if isinstance(item, dict) else None
            if not isinstance(uid, str) or not uid or uid in seen:
                raise DocumentLoweringError("HOCUS710", "Baseline entity UIDs must be present and globally unique.",
                                            details={"field": field, "uid": uid})
            seen.add(uid)


def _validate_baseline_entities(result: dict[str, Any]) -> None:
    node_uids = _validate_baseline_nodes(result["nodes"])
    _validate_baseline_ports(result["ports"], node_uids)
    _validate_baseline_edges(result["edges"], node_uids)
    binding_uids = _validate_baseline_bindings(result["parameterBindings"], node_uids)
    _validate_baseline_code(result["codeBlobs"], node_uids, binding_uids)


def _validate_baseline_nodes(nodes: list[dict[str, Any]]) -> set[str]:
    required_node = {
        "uid", "name", "typeName", "category", "path", "parentPath",
        "isNetwork", "flags", "metadata",
    }
    node_uids = {item["uid"] for item in nodes}
    node_paths: set[str] = set()
    for node in nodes:
        if not required_node.issubset(node) or not isinstance(node["path"], str) or not node["path"].startswith("/"):
            raise DocumentLoweringError("HOCUS710", "Baseline contains a malformed node.", details={"uid": node.get("uid")})
        if node["path"] in node_paths:
            raise DocumentLoweringError("HOCUS710", "Baseline node paths must be unique.", details={"path": node["path"]})
        node_paths.add(node["path"])
        flags = node["flags"]
        if not isinstance(flags, dict) or set(flags) != {"display", "render", "bypass", "template"} or any(type(v) is not bool for v in flags.values()):
            raise DocumentLoweringError("HOCUS710", "Baseline node flags are malformed.", details={"uid": node["uid"]})
    return node_uids


def _validate_baseline_ports(ports: list[dict[str, Any]], node_uids: set[str]) -> None:
    for port in ports:
        if port.get("nodeUid") not in node_uids or port.get("direction") not in {"input", "output"}:
            raise DocumentLoweringError("HOCUS710", "Baseline contains a dangling or malformed port.", details={"uid": port["uid"]})


def _validate_baseline_edges(edges: list[dict[str, Any]], node_uids: set[str]) -> None:
    for edge in edges:
        if edge.get("from", {}).get("nodeUid") not in node_uids or edge.get("to", {}).get("nodeUid") not in node_uids:
            raise DocumentLoweringError("HOCUS710", "Baseline contains a dangling edge.", details={"uid": edge["uid"]})


def _validate_baseline_bindings(
    bindings: list[dict[str, Any]],
    node_uids: set[str],
) -> set[str]:
    binding_uids = {item["uid"] for item in bindings}
    for binding in bindings:
        if binding.get("nodeUid") not in node_uids or binding.get("valueMode") not in {
            "literal", "expression", "channel_reference", "code_reference"
        }:
            raise DocumentLoweringError("HOCUS710", "Baseline contains a dangling or malformed parameter binding.",
                                        details={"uid": binding["uid"]})
        if binding.get("valueMode") == "literal" and isinstance(binding.get("value"), (list, dict)):
            raise DocumentLoweringError("HOCUS710", "Network-document v1 literal bindings must be scalar.",
                                        details={"uid": binding["uid"]})
    return binding_uids


def _validate_baseline_code(
    blobs: list[dict[str, Any]],
    node_uids: set[str],
    binding_uids: set[str],
) -> None:
    for blob in blobs:
        target = blob.get("target", {})
        if (target.get("nodeUid") not in node_uids
                or (target.get("bindingUid") is not None and target.get("bindingUid") not in binding_uids)):
            raise DocumentLoweringError("HOCUS710", "Baseline contains a dangling code blob.", details={"uid": blob["uid"]})


def _provenance(payload: dict[str, Any], bundle_digest: str, baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundleDigest": bundle_digest,
        "bundleVersion": payload["bundleVersion"],
        "compilerVersion": payload["compilerVersion"],
        "graphSpecVersion": payload["graphSpecVersion"],
        "languageVersion": payload["languageVersion"],
        "projectUid": payload["projectUid"],
        "projectManifestDigest": payload["projectManifestDigest"],
        "projectLockDigest": payload["projectLockDigest"],
        "entrySource": copy.deepcopy(payload["entrySource"]),
        "dependencies": copy.deepcopy(payload["dependencies"]),
        "catalog": copy.deepcopy(payload["catalogConstraints"]),
        "ownership": payload["graphSpec"].get("ownership"),
        "mode": payload["graphSpec"]["mode"],
        "baselineDocumentId": baseline["documentId"],
        "baselineDocumentRevision": baseline["documentRevision"],
        "baselineLiveRevision": int(baseline.get("lastSyncedLiveRevision", baseline.get("baselineLiveRevision", 0))),
        "baselineDigest": _digest(baseline),
    }


def _entity_metadata(payload: dict[str, Any], bundle_digest: str, graph: dict[str, Any], symbol: str,
                     pointer: str, span: Any, ownership: str | None, *, entity_kind: str) -> dict[str, Any]:
    return {"hocus": {
        "version": 1, "entityKind": entity_kind, "projectUid": payload["projectUid"],
        "sourceUri": payload["entrySource"]["uri"], "sourceDigest": payload["entrySource"]["digest"],
        "bundleDigest": bundle_digest, "compilerVersion": payload["compilerVersion"],
        "languageVersion": payload["languageVersion"], "graphName": graph["name"], "symbol": symbol,
        "ownership": ownership, "jsonPointer": pointer, "span": copy.deepcopy(span),
    }}


def _managed_explicit_rename_candidate(
    previous: dict[str, Any],
    payload: dict[str, Any],
    graph: dict[str, Any],
    ownership: str | None,
) -> bool:
    """Prove an explicit-ID path change is a managed rename, never adoption.

    Source URI and symbol deliberately may change.  Project, graph, ownership, entity
    kind, and complete compiler provenance must still identify the baseline node as a
    prior Hocus-authored revision of this graph.
    """

    metadata = previous.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    if not isinstance(hocus, dict):
        return False
    required_strings = (
        "sourceUri", "sourceDigest", "bundleDigest", "compilerVersion",
        "languageVersion", "graphName", "symbol", "jsonPointer",
    )
    if any(not isinstance(hocus.get(key), str) or not hocus.get(key) for key in required_strings):
        return False
    if not isinstance(hocus.get("span"), dict):
        return False
    if not str(hocus["sourceDigest"]).startswith("sha256:") or not str(hocus["bundleDigest"]).startswith("sha256:"):
        return False
    return (
        hocus.get("entityKind") == "node"
        and hocus.get("projectUid") == payload.get("projectUid")
        and hocus.get("graphName") == graph.get("name")
        and hocus.get("ownership") == ownership
        and hocus.get("symbol") == previous.get("name")
        and str(hocus.get("jsonPointer", "")).startswith("/nodes/")
    )


def _source_map(payload: dict[str, Any], pointer: str, span: Any) -> dict[str, Any]:
    return {"sourceUri": payload["entrySource"]["uri"], "jsonPointer": pointer, "span": copy.deepcopy(span)}


def _remove_owned_state(
    document: dict[str, Any],
    ownership: str,
    preserved_node_paths: set[str],
) -> list[str]:
    def owned(item: dict[str, Any]) -> bool:
        return ((item.get("metadata") or {}).get("hocus") or {}).get("ownership") == ownership
    removed_entities = [
        item
        for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs")
        for item in document.get(field, [])
        if isinstance(item, dict) and owned(item)
        and not (field == "nodes" and item.get("path") in preserved_node_paths)
    ]
    missing_provenance = sorted(
        str(item.get("uid", ""))
        for item in removed_entities
        if _source_map_from_entity(item) is None
    )
    removed_nodes = {
        item["uid"] for item in document["nodes"]
        if owned(item) and item.get("path") not in preserved_node_paths
    }
    document["nodes"] = [item for item in document["nodes"] if item["uid"] not in removed_nodes]
    document["ports"] = [item for item in document.get("ports", [])
                         if item.get("nodeUid") not in removed_nodes and not owned(item)]
    document["edges"] = [item for item in document["edges"]
                         if item.get("from", {}).get("nodeUid") not in removed_nodes
                         and item.get("to", {}).get("nodeUid") not in removed_nodes and not owned(item)]
    removed_bindings = {item["uid"] for item in document["parameterBindings"]
                        if item.get("nodeUid") in removed_nodes or owned(item)}
    document["parameterBindings"] = [item for item in document["parameterBindings"]
                                      if item["uid"] not in removed_bindings]
    document["codeBlobs"] = [item for item in document["codeBlobs"]
                              if item.get("target", {}).get("nodeUid") not in removed_nodes
                              and item.get("target", {}).get("bindingUid") not in removed_bindings and not owned(item)]
    return missing_provenance


def _protected_owned_dependency_diagnostics(
    document: dict[str, Any],
    ownership: str,
    preserved_node_paths: set[str],
) -> list[dict[str, Any]]:
    """Report artist-owned state that reconcile would necessarily disturb."""

    def owner(item: dict[str, Any]) -> Any:
        return ((item.get("metadata") or {}).get("hocus") or {}).get("ownership")

    removed_nodes = {
        item["uid"] for item in document["nodes"]
        if owner(item) == ownership and item.get("path") not in preserved_node_paths
    }
    diagnostics: list[dict[str, Any]] = []
    for field, items in (("edges", document["edges"]), ("parameterBindings", document["parameterBindings"]),
                         ("codeBlobs", document["codeBlobs"])):
        for index, item in enumerate(items):
            if owner(item) == ownership:
                continue
            references_removed = (
                item.get("nodeUid") in removed_nodes
                or item.get("from", {}).get("nodeUid") in removed_nodes
                or item.get("to", {}).get("nodeUid") in removed_nodes
                or item.get("target", {}).get("nodeUid") in removed_nodes
            )
            if references_removed:
                diagnostics.append(_diagnostic(
                    "HOCUS709",
                    "Reconcile would disturb baseline state outside the requested ownership namespace.",
                    f"/baselineDocument/{field}/{index}", entity_uid=item.get("uid"),
                ))
    return diagnostics


def _literal_value(value: dict[str, Any]) -> Any:
    if value["kind"] == "literal":
        return copy.deepcopy(value["value"])
    if value["kind"] == "array":
        return [_literal_value(item) for item in value["items"]]
    raise DocumentLoweringError("HOCUS711", "Unsupported value reached literal document lowering.")


def _candidate_plan(payload: dict[str, Any], bundle_digest: str, baseline: dict[str, Any],
                    document: dict[str, Any], diff: dict[str, Any], ownership: str | None,
                    source_maps: dict[str, Any], adopted_uids: set[str],
                    provenance_update_uids: set[str]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    sequence = _append_identity_operations(
        operations, source_maps, adopted_uids, provenance_update_uids
    )
    _append_diff_operations(operations, source_maps, diff, sequence)
    plan = {
        "kind": "hocus_candidate_plan", "planVersion": PREVIEW_VERSION, "applyable": False,
        "bundleDigest": bundle_digest, "sourceDigest": payload["entrySource"]["digest"],
        "catalogFingerprint": payload["catalogConstraints"]["fingerprint"],
        "catalogContentDigest": payload["catalogConstraints"]["contentDigest"],
        "ownership": ownership, "mode": payload["graphSpec"]["mode"],
        "requiredCapabilities": copy.deepcopy(payload["requiredCapabilities"]),
        "baselineDocumentId": baseline["documentId"],
        "baselineDocumentRevision": baseline["documentRevision"],
        "baselineLiveRevision": int(baseline.get("lastSyncedLiveRevision", baseline.get("baselineLiveRevision", 0))),
        "baselineDigest": _digest(baseline), "targetDocumentDigest": _digest(document),
        "operations": operations,
    }
    plan["planHash"] = _digest(plan)
    return plan


def _append_identity_operations(
    operations: list[dict[str, Any]],
    source_maps: dict[str, Any],
    adopted_uids: set[str],
    provenance_update_uids: set[str],
) -> int:
    sequence = 0
    groups = (
        ("adopt_node", adopted_uids),
        ("update_node_provenance", provenance_update_uids),
    )
    for action, uids in groups:
        for uid in sorted(uids):
            operation = {
                "operationId": f"op:{sequence:06d}", "sequence": sequence,
                "action": action, "entityKind": "node", "entityUid": uid,
                "change": {"uid": uid},
            }
            source = source_maps.get("adoptions", {}).get(uid) or source_maps["entities"].get(uid)
            _attach_operation_source(operation, source, source_maps)
            operations.append(operation)
            sequence += 1
    return sequence


def _append_diff_operations(
    operations: list[dict[str, Any]],
    source_maps: dict[str, Any],
    diff: dict[str, Any],
    sequence: int,
) -> int:
    # The order is directly executable in principle: detach references before
    # destructive removals, create structural targets before installing state,
    # and connect only after both endpoints exist.
    for entity_kind, action, field in (
        ("edge", "disconnect", "deletedEdges"),
        ("parameter_binding", "remove_binding", "deletedParameterBindings"),
        ("code_blob", "remove_code", "deletedCodeBlobs"),
        ("port", "delete_port", "deletedPorts"),
        ("node", "delete_node", "deletedNodes"),
        ("node", "create_node", "createdNodes"),
        ("node", "update_node", "changedNodes"),
        ("port", "create_port", "createdPorts"),
        ("parameter_binding", "set_binding", "createdParameterBindings"),
        ("parameter_binding", "set_binding", "changedParameterBindings"),
        ("code_blob", "install_code", "createdCodeBlobs"),
        ("code_blob", "install_code", "changedCodeBlobs"),
        ("edge", "connect", "changedEdges"),
        ("edge", "connect", "createdEdges"),
    ):
        for item in diff[field]:
            uid = item.get("uid") or item.get("after", {}).get("uid") or item.get("before", {}).get("uid")
            effective_action = _effective_operation_action(entity_kind, action, field, item)
            operation = {
                "operationId": f"op:{sequence:06d}", "sequence": sequence, "action": effective_action,
                "entityKind": entity_kind, "entityUid": uid, "change": copy.deepcopy(item),
            }
            source = source_maps["entities"].get(uid)
            if source is None:
                before = item.get("before") if isinstance(item, dict) else None
                source = _source_map_from_entity(before if isinstance(before, dict) else item)
            _attach_operation_source(operation, source, source_maps)
            operations.append(operation)
            sequence += 1
    return sequence


def _effective_operation_action(
    entity_kind: str,
    action: str,
    field: str,
    item: dict[str, Any],
) -> str:
    if field == "changedNodes":
        before_node, after_node = item["before"], item["after"]
        if before_node.get("typeName") != after_node.get("typeName"):
            return "replace_node"
        if before_node.get("parentPath") != after_node.get("parentPath"):
            return "reparent_node"
        if before_node.get("path") != after_node.get("path") or before_node.get("name") != after_node.get("name"):
            return "rename_node"
    if entity_kind == "edge":
        edge = item.get("after") if field == "changedEdges" else item
        if (edge or {}).get("kind") == "output_flag":
            return "clear_output" if field == "deletedEdges" else "set_output"
    return action


def _attach_operation_source(
    operation: dict[str, Any],
    source: Any,
    source_maps: dict[str, Any],
) -> None:
    if source is not None:
        operation["sourceMap"] = copy.deepcopy(source)
        source_maps["operations"][operation["operationId"]] = copy.deepcopy(source)


def _source_map_from_entity(entity: Any) -> dict[str, Any] | None:
    if not isinstance(entity, dict):
        return None
    metadata = entity.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    if not isinstance(hocus, dict):
        return None
    source_uri = hocus.get("sourceUri")
    pointer = hocus.get("jsonPointer")
    span = hocus.get("span")
    if not isinstance(source_uri, str) or not source_uri or not isinstance(pointer, str) or span is None:
        return None
    return {"sourceUri": source_uri, "jsonPointer": pointer, "span": copy.deepcopy(span)}


def _document_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total = 0
    specs = (
        ("Nodes", "nodes"), ("Ports", "ports"), ("Edges", "edges"),
        ("ParameterBindings", "parameterBindings"), ("CodeBlobs", "codeBlobs"),
    )
    summary: dict[str, int] = {}
    for label, field in specs:
        old = _by_uid(before.get(field, []))
        new = _by_uid(after.get(field, []))
        created = [copy.deepcopy(new[uid]) for uid in sorted(set(new) - set(old))]
        deleted = [copy.deepcopy(old[uid]) for uid in sorted(set(old) - set(new))]
        changed = [
            {"uid": uid, "before": copy.deepcopy(old[uid]), "after": copy.deepcopy(new[uid])}
            for uid in sorted(set(old) & set(new))
            if _operational_entity(old[uid]) != _operational_entity(new[uid])
        ]
        result[f"created{label}"] = created
        result[f"deleted{label}"] = deleted
        result[f"changed{label}"] = changed
        summary[f"created{label[:-1] if label.endswith('s') else label}Count"] = len(created)
        summary[f"deleted{label[:-1] if label.endswith('s') else label}Count"] = len(deleted)
        summary[f"changed{label[:-1] if label.endswith('s') else label}Count"] = len(changed)
        total += len(created) + len(deleted) + len(changed)
    summary["totalChangeCount"] = total
    result["summary"] = summary
    return {"summary": summary, **{key: result[key] for key in sorted(result) if key != "summary"}}


def _operational_entity(entity: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(entity)
    result.pop("metadata", None)
    result.pop("definitionRef", None)
    return result


def _destructive_summary(diff: dict[str, Any], adopted_uids: set[str]) -> dict[str, Any]:
    deleted_nodes = diff["deletedNodes"]
    retyped = [item["uid"] for item in diff["changedNodes"]
               if item["before"].get("typeName") != item["after"].get("typeName")]
    displaced_display = [
        item["uid"] for item in diff["changedNodes"]
        if bool((item["before"].get("flags") or {}).get("display"))
        and not bool((item["after"].get("flags") or {}).get("display"))
    ]
    displaced_render = [
        item["uid"] for item in diff["changedNodes"]
        if bool((item["before"].get("flags") or {}).get("render"))
        and not bool((item["after"].get("flags") or {}).get("render"))
    ]
    return {
        "destructive": bool(deleted_nodes or diff["deletedParameterBindings"] or diff["deletedCodeBlobs"]
                            or diff["deletedEdges"] or adopted_uids or retyped),
        "deletedNodeCount": len(deleted_nodes),
        "deletedParameterBindingCount": len(diff["deletedParameterBindings"]),
        "deletedCodeBlobCount": len(diff["deletedCodeBlobs"]),
        "disconnectedEdgeCount": len(diff["deletedEdges"]),
        "adoptedNodeCount": len(adopted_uids),
        "ownershipTransfer": bool(adopted_uids),
        "replacedNodeCount": len(retyped),
        "displacedDisplayNodeCount": len(displaced_display),
        "displacedRenderNodeCount": len(displaced_render),
        "deletedNodeUids": sorted(item["uid"] for item in deleted_nodes),
        "adoptedNodeUids": sorted(adopted_uids),
        "replacedNodeUids": sorted(retyped),
        "displacedDisplayNodeUids": sorted(displaced_display),
        "displacedRenderNodeUids": sorted(displaced_render),
    }


def _diagnostic(code: str, message: str, pointer: str, path: str | None = None,
                entity_uid: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"severity": "error", "code": code, "message": message, "jsonPointer": pointer}
    if path:
        result["path"] = path
    if entity_uid:
        result["entityUid"] = entity_uid
    return result


def _uid(kind: str, payload: dict[str, Any], *parts: str) -> str:
    identity = ["hocus-entity-v1", payload["projectUid"], payload["entrySource"]["uri"], *parts]
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"hocus-{kind}:{digest[:32]}"


def _binding_uid(node_uid: str, parm_name: str) -> str:
    return f"binding:{node_uid}:{parm_name}"


def _code_blob_uid(node_uid: str, parm_name: str) -> str:
    return f"code:{node_uid}:{parm_name}"


def _edge_uid(dest_uid: str, input_index: int) -> str:
    return f"edge:data:{dest_uid}:{input_index}"


def _port_uid(node_uid: str, direction: str, index: int) -> str:
    return f"port:{node_uid}:{direction}:{index}"


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _default_flags() -> dict[str, bool]:
    return {"display": False, "render": False, "bypass": False, "template": False}


def _merged_metadata(previous: Any, added: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(previous) if isinstance(previous, dict) else {}
    result.update(copy.deepcopy(added))
    return result


def _by_uid(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["uid"]: item for item in items if isinstance(item, dict) and isinstance(item.get("uid"), str)}


def _upsert_by_uid(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    items[:] = [existing for existing in items if existing.get("uid") != item["uid"]]
    items.append(item)


def _replace_binding(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    items[:] = [
        existing for existing in items
        if not (
            existing.get("nodeUid") == item["nodeUid"]
            and existing.get("parmName") == item["parmName"]
        )
    ]
    items.append(item)


def _replace_code_blob(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    target = item["target"]
    items[:] = [
        existing for existing in items
        if not (
            existing.get("target", {}).get("nodeUid") == target["nodeUid"]
            and existing.get("target", {}).get("parmName") == target.get("parmName")
        )
    ]
    items.append(item)


def _replace_edge(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    destination = item["to"]
    if item.get("kind") != "data":
        items[:] = [
            existing for existing in items
            if not (
                existing.get("kind") == item.get("kind")
                and existing.get("to", {}).get("nodeUid") == destination["nodeUid"]
            )
        ]
        items.append(item)
        return
    items[:] = [
        existing for existing in items
        if not (
            existing.get("kind") == "data"
            and existing.get("to", {}).get("nodeUid") == destination["nodeUid"]
            and existing.get("to", {}).get("portIndex") == destination["portIndex"]
        )
    ]
    items.append(item)


def _replace_port(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    items[:] = [
        existing for existing in items
        if not (
            existing.get("nodeUid") == item["nodeUid"]
            and existing.get("direction") == item["direction"]
            and existing.get("index") == item["index"]
        )
    ]
    items.append(item)


def _canonicalize_document(document: dict[str, Any]) -> None:
    for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs"):
        document[field] = sorted(document.get(field, []), key=lambda item: item["uid"])
    document["diagnostics"] = sorted(document.get("diagnostics", []),
                                     key=lambda item: (item.get("jsonPointer", ""), item.get("code", "")))
