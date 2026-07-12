"""Pure network-document v1 to normalized HocusScript 0.1 export."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .catalog import CatalogProvider, CatalogSnapshot, SnapshotCatalogProvider
from .compiler import MAX_SOURCE_BYTES, compile_source
from .model import EXPLICIT_NODE_ID_PATTERN
from .semantic import CatalogConstraint, resolve_graph


_DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/network-document/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_CODE_LANGUAGES = frozenset({"vex", "python", "hscript"})
MAX_EXPORT_DIAGNOSTICS = 500
MAX_EXPORT_RESPONSE_BYTES = 16 * 1024 * 1024
_PROVENANCE_FIELDS = (
    "entityKind", "ownership", "projectUid", "sourceUri", "sourceDigest",
    "bundleDigest", "graphName", "symbol", "jsonPointer",
)


@dataclass(frozen=True, slots=True)
class ExportDiagnostic:
    code: str
    message: str
    json_pointer: str
    entity_uid: str | None = None
    details: dict[str, Any] | None = None
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity, "code": self.code,
            "message": self.message, "jsonPointer": self.json_pointer,
        }
        if self.entity_uid is not None:
            payload["entityUid"] = self.entity_uid
        if self.details:
            payload["details"] = copy.deepcopy(self.details)
        return payload


@dataclass(frozen=True, slots=True)
class NetworkDocumentExport:
    source: str | None
    diagnostics: tuple[ExportDiagnostic, ...]
    provenance: dict[str, Any]

    @property
    def valid(self) -> bool:
        return self.source is not None and not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "source_export", "exportVersion": "1.0", "languageVersion": "0.1", "valid": self.valid,
            "source": self.source,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "provenance": copy.deepcopy(self.provenance),
        }


def export_network_document(
    document: dict[str, Any], *, graph_name: str | None = None,
    catalog: CatalogProvider | CatalogSnapshot | None = None,
) -> NetworkDocumentExport:
    """Export a flat SOP document without host access or filesystem writes.

    Unsupported constructs produce bounded typed blockers and no source text.
    When the blocker manifest exceeds the public limit, a sentinel diagnostic
    reports the exact number of omitted blockers.
    Persistent node UIDs are emitted as explicit IDs. The provenance result also
    records every entity UID and the exact managed fields represented by source.
    """
    diagnostics: list[ExportDiagnostic] = []

    def block(code: str, message: str, pointer: str, uid: str | None = None, **details: Any) -> None:
        diagnostic = ExportDiagnostic(code, message, pointer, uid, details or None)
        if len(diagnostics) < MAX_EXPORT_DIAGNOSTICS - 1:
            diagnostics.append(diagnostic)
            return
        if len(diagnostics) == MAX_EXPORT_DIAGNOSTICS - 1:
            omitted_count = 1
            diagnostics.append(_truncated_export_diagnostic(omitted_count))
            return
        sentinel = diagnostics[-1]
        omitted_count = int((sentinel.details or {}).get("omittedCount", 0)) + 1
        diagnostics[-1] = _truncated_export_diagnostic(omitted_count)

    if not isinstance(document, dict):
        block("HOCUS800", "Network-document export requires an object.", "")
        return _result(None, diagnostics, _empty_provenance())
    if document.get("$schema") != _DOCUMENT_SCHEMA_URI or document.get("kind") != "network_document":
        block("HOCUS800", "Export requires the locked network-document v1 contract.", "")
    document_id = document.get("documentId")
    if not isinstance(document_id, str) or not document_id.startswith("network:"):
        block("HOCUS800", "documentId must be a network-document identity.", "/documentId")
    revision = document.get("documentRevision")
    if type(revision) is not int or revision < 0:
        block("HOCUS800", "documentRevision must be a non-negative integer.", "/documentRevision")
    document_diagnostics = document.get("diagnostics")
    if not isinstance(document_diagnostics, list):
        block("HOCUS800", "diagnostics must be an array.", "/diagnostics")
    else:
        for index, diagnostic in enumerate(document_diagnostics):
            if isinstance(diagnostic, dict) and diagnostic.get("severity") == "error":
                block("HOCUS800", "A document with blocking diagnostics cannot be exported.",
                      f"/diagnostics/{index}", diagnosticCode=diagnostic.get("code"))

    root_path = document.get("rootPath")
    if not isinstance(root_path, str) or not _canonical_path(root_path):
        block("HOCUS801", "rootPath must be a canonical absolute Houdini path.", "/rootPath")
        root_path = ""
    document_category = document.get("category")
    if document_category not in {"Sop", "Object"} or (
        document_category == "Object" and not str(root_path).startswith("/obj/")
    ):
        block("HOCUS802", "HocusScript 0.1 export requires a SOP network or an /obj SOP container.",
              "/category", received=document_category)

    collections: dict[str, list[Any]] = {}
    for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs"):
        value = document.get(field)
        if not isinstance(value, list):
            block("HOCUS800", f"{field} must be an array.", f"/{field}")
            collections[field] = []
        else:
            collections[field] = value

    identities: dict[str, dict[str, Any]] = {}
    seen_uids: set[str] = set()
    for field, kind in (
        ("nodes", "node"), ("ports", "port"), ("edges", "edge"),
        ("parameterBindings", "parameter_binding"), ("codeBlobs", "code_blob"),
    ):
        for index, item in enumerate(collections[field]):
            pointer = f"/{field}/{index}"
            if not isinstance(item, dict):
                block("HOCUS803", f"Each {field} entry must be an object.", pointer)
                continue
            uid = item.get("uid")
            if not isinstance(uid, str) or not uid:
                block("HOCUS803", f"Each {kind} requires a durable uid.", pointer + "/uid")
                continue
            if uid in seen_uids:
                block("HOCUS803", "Entity uids must be globally unique.", pointer + "/uid", uid)
                continue
            seen_uids.add(uid)
            identities[uid] = _identity_record(kind, item)

    nodes_by_uid: dict[str, dict[str, Any]] = {}
    root_nodes: list[dict[str, Any]] = []
    authored_nodes: list[dict[str, Any]] = []
    symbols: dict[str, str] = {}
    preserved_state: list[dict[str, Any]] = []
    for index, node in enumerate(collections["nodes"]):
        if not isinstance(node, dict):
            continue
        pointer = f"/nodes/{index}"
        uid = node.get("uid") if isinstance(node.get("uid"), str) else None
        if uid:
            nodes_by_uid[uid] = node
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        if metadata.get("identityMode") != "persistent_user_data":
            block(
                "HOCUS803",
                "Live export requires persistent_user_data identity for the root container and every exported node.",
                pointer + "/metadata/identityMode",
                uid,
                received=metadata.get("identityMode"),
                rootPolicy="root_is_not_emitted_but_its_persistent_uid_anchors_output_identity",
            )
        path = node.get("path")
        if path == root_path:
            root_nodes.append(node)
            if not bool(node.get("isNetwork")):
                block("HOCUS804", "The rootPath node must be a network container.", pointer + "/isNetwork", uid)
            continue
        name = node.get("name")
        if not isinstance(path, str) or not root_path or not path.startswith(root_path + "/"):
            block("HOCUS804", "Authored nodes must remain inside rootPath.", pointer + "/path", uid)
            continue
        if node.get("parentPath") != root_path or path.rsplit("/", 1)[-1] != name:
            block("HOCUS804", "HocusScript 0.1 exports only direct child nodes whose name matches their path.", pointer, uid)
            continue
        if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
            block("HOCUS804", "Node names must already be valid HocusScript identifiers.", pointer + "/name", uid)
            continue
        if not isinstance(uid, str) or EXPLICIT_NODE_ID_PATTERN.fullmatch(uid) is None:
            block("HOCUS803", "Exported nodes require a persistent UID valid for explicit @id syntax.", pointer + "/uid", uid)
            continue
        if name in symbols:
            block("HOCUS804", "Node symbols must be unique.", pointer + "/name", uid, firstUid=symbols[name])
            continue
        if bool(node.get("isNetwork")):
            block("HOCUS805", "Nested network containers are opaque in HocusScript 0.1 export.", pointer + "/isNetwork", uid)
            continue
        if node.get("category") != "Sop":
            block("HOCUS805", "Only SOP child operators can be exported.", pointer + "/category", uid)
            continue
        type_name = node.get("typeName")
        if not isinstance(type_name, str) or not type_name or not _is_utf8(type_name):
            block("HOCUS804", "Each exported node requires an exact operator typeName.", pointer + "/typeName", uid)
            continue
        flags = node.get("flags")
        if not isinstance(flags, dict):
            block("HOCUS804", "Each exported node requires flags.", pointer + "/flags", uid)
            continue
        if any(type(flags.get(name)) is not bool for name in ("display", "render", "bypass", "template")):
            block("HOCUS804", "Node flags must contain explicit boolean display/render/bypass/template values.",
                  pointer + "/flags", uid)
            continue
        if bool(flags.get("bypass")) or bool(flags.get("template")):
            block("HOCUS805", "Bypass and template flags have no HocusScript 0.1 source representation.",
                  pointer + "/flags", uid, bypass=bool(flags.get("bypass")),
                  template=bool(flags.get("template")))
        symbols[name] = uid
        authored_nodes.append(node)
    if len(root_nodes) != 1:
        block("HOCUS801", "The document must contain exactly one rootPath node.", "/nodes", count=len(root_nodes))
    root_uid = root_nodes[0].get("uid") if len(root_nodes) == 1 else None

    display_nodes = []
    render_nodes = []
    for node in authored_nodes:
        manifest = _node_managed_manifest(node)
        flags = node.get("flags") or {}
        for flag_name, target in (("display", display_nodes), ("render", render_nodes)):
            if manifest is None or flag_name in manifest["flags"]:
                if bool(flags.get(flag_name)):
                    target.append(node)
            else:
                preserved_state.append(_preserved("node_flag", node.get("uid"), node.get("uid"), flag_name,
                                                    "artist_or_default_not_source_managed"))
    if len(display_nodes) > 1:
        block("HOCUS806", "At most one exported node may carry the display flag.", "/nodes")
    if len(render_nodes) > 1:
        block("HOCUS806", "At most one exported node may carry the render flag.", "/nodes")

    for index, port in enumerate(collections["ports"]):
        if not isinstance(port, dict):
            continue
        uid = port.get("uid") if isinstance(port.get("uid"), str) else None
        if port.get("kind") != "data":
            block("HOCUS807", "Only data ports are representable in HocusScript 0.1.", f"/ports/{index}/kind", uid)
        if port.get("nodeUid") not in nodes_by_uid:
            block("HOCUS807", "Port references a missing nodeUid.", f"/ports/{index}/nodeUid", uid)
        direction, port_index = port.get("direction"), port.get("index")
        if (isinstance(uid, str) and direction in {"input", "output"}
                and type(port_index) is int and port_index >= 0):
            expected_uid = f"port:{port.get('nodeUid')}:{direction}:{port_index}"
            if uid != expected_uid:
                block("HOCUS803", "Port uid is not reproducible from persistent node identity.",
                      f"/ports/{index}/uid", uid, expectedUid=expected_uid)

    inputs_by_dest: dict[str, list[tuple[int, str, int]]] = {}
    occupied_inputs: set[tuple[str, int]] = set()
    output_nodes: list[dict[str, Any]] = []
    supported_edge_uids: set[str] = set()
    for index, edge in enumerate(collections["edges"]):
        if not isinstance(edge, dict):
            continue
        pointer = f"/edges/{index}"
        uid = edge.get("uid") if isinstance(edge.get("uid"), str) else None
        kind = edge.get("kind")
        source = edge.get("from") if isinstance(edge.get("from"), dict) else {}
        dest = edge.get("to") if isinstance(edge.get("to"), dict) else {}
        source_uid, dest_uid = source.get("nodeUid"), dest.get("nodeUid")
        if kind == "output_flag":
            source_node = nodes_by_uid.get(source_uid)
            if (source_node not in authored_nodes or dest_uid != root_uid
                    or set(source) != {"nodeUid"} or set(dest) != {"nodeUid"}):
                block("HOCUS806", "Output flag must reference an exported child node.", pointer + "/from/nodeUid", uid)
            else:
                manifest = _node_managed_manifest(source_node)
                if manifest is not None and "output" not in manifest["flags"]:
                    preserved_state.append(_preserved("edge", uid, source_uid, "output", "artist_or_default_not_source_managed"))
                    continue
                expected_uid = f"edge:output:{root_uid}"
                if uid != expected_uid:
                    block("HOCUS803", "Output-edge uid is not reproducible from persistent root identity.",
                          pointer + "/uid", uid, expectedUid=expected_uid)
                output_nodes.append(source_node)
                if uid:
                    supported_edge_uids.add(uid)
            continue
        if kind != "data":
            block("HOCUS807", "Edge kind has no HocusScript 0.1 representation.", pointer + "/kind", uid, kind=kind)
            continue
        source_node, dest_node = nodes_by_uid.get(source_uid), nodes_by_uid.get(dest_uid)
        if source_node not in authored_nodes or dest_node not in authored_nodes:
            block("HOCUS807", "Data edges must connect two exported child nodes.", pointer, uid)
            continue
        input_index, output_index = dest.get("portIndex"), source.get("portIndex", 0)
        if type(input_index) is not int or input_index < 0 or type(output_index) is not int or output_index < 0:
            block("HOCUS807", "Data edge port indices must be non-negative integers.", pointer, uid)
            continue
        manifest = _node_managed_manifest(dest_node)
        if manifest is not None and input_index not in manifest["inputs"]:
            preserved_state.append(_preserved("edge", uid, dest_uid, f"input[{input_index}]",
                                                "artist_or_default_not_source_managed"))
            continue
        slot = (str(dest_uid), input_index)
        if slot in occupied_inputs:
            block("HOCUS807", "Multiple edges target the same input slot.", pointer + "/to/portIndex", uid)
            continue
        occupied_inputs.add(slot)
        expected_uid = f"edge:data:{dest_uid}:{input_index}"
        if uid != expected_uid:
            block("HOCUS803", "Data-edge uid is not reproducible from persistent node identity.",
                  pointer + "/uid", uid, expectedUid=expected_uid)
        inputs_by_dest.setdefault(str(dest_uid), []).append((input_index, str(source_uid), output_index))
        if uid:
            supported_edge_uids.add(uid)
    if len(output_nodes) > 1:
        block("HOCUS806", "At most one output flag edge may be exported.", "/edges")

    code_by_uid = {str(item.get("uid")): item for item in collections["codeBlobs"]
                   if isinstance(item, dict) and isinstance(item.get("uid"), str)}
    used_code_uids: set[str] = set()
    parms_by_node: dict[str, list[tuple[str, str]]] = {}
    occupied_parms: set[tuple[str, str]] = set()
    supported_binding_uids: set[str] = set()
    for index, binding in enumerate(collections["parameterBindings"]):
        if not isinstance(binding, dict):
            continue
        pointer = f"/parameterBindings/{index}"
        uid = binding.get("uid") if isinstance(binding.get("uid"), str) else None
        node_uid = binding.get("nodeUid")
        node = nodes_by_uid.get(node_uid)
        if node in root_nodes:
            code_uid = binding.get("codeBlobUid")
            if isinstance(code_uid, str):
                used_code_uids.add(code_uid)
            preserved_state.append(_preserved("parameter_binding", uid, node_uid, str(binding.get("parmName", "")),
                                                "root_container_state"))
            continue
        if node not in authored_nodes:
            block("HOCUS808", "Parameter binding must reference an exported child node.", pointer + "/nodeUid", uid)
            continue
        parm_name = binding.get("parmName")
        if not isinstance(parm_name, str) or _IDENTIFIER.fullmatch(parm_name) is None:
            block("HOCUS808", "Parameter names must be HocusScript identifiers.", pointer + "/parmName", uid)
            continue
        manifest = _node_managed_manifest(node)
        if manifest is None or parm_name not in manifest["parameters"]:
            code_uid = binding.get("codeBlobUid")
            if isinstance(code_uid, str):
                used_code_uids.add(code_uid)
            preserved_state.append(_preserved("parameter_binding", uid, node_uid, parm_name,
                                                "artist_or_default_not_source_managed"))
            continue
        key = (str(node_uid), parm_name)
        if key in occupied_parms:
            block("HOCUS808", "A node parameter may be authored only once.", pointer + "/parmName", uid)
            continue
        occupied_parms.add(key)
        expected_binding_uid = f"binding:{node_uid}:{parm_name}"
        if uid != expected_binding_uid:
            block("HOCUS803", "Binding uid is not reproducible from persistent node identity.",
                  pointer + "/uid", uid, expectedUid=expected_binding_uid)
        mode, encoded = binding.get("valueMode"), None
        if mode == "literal":
            if "value" not in binding or not _is_scalar(binding.get("value")):
                block("HOCUS808", "Literal bindings must contain one finite scalar value.", pointer + "/value", uid)
            else:
                encoded = _format_scalar(binding.get("value"))
        elif mode == "code_reference":
            code_uid = binding.get("codeBlobUid")
            blob = code_by_uid.get(code_uid)
            if blob is None:
                block("HOCUS809", "Code binding references a missing code blob.", pointer + "/codeBlobUid", uid)
            else:
                language, body = blob.get("language"), blob.get("body")
                target = blob.get("target") if isinstance(blob.get("target"), dict) else {}
                expected_code_uid = f"code:{node_uid}:{parm_name}"
                if code_uid != expected_code_uid:
                    block("HOCUS803", "Code-blob uid is not reproducible from persistent node identity.",
                          pointer + "/codeBlobUid", str(code_uid) if code_uid is not None else None,
                          expectedUid=expected_code_uid)
                if language not in _SUPPORTED_CODE_LANGUAGES or not isinstance(body, str) or not _is_utf8(body):
                    block("HOCUS809", "Code blob language or body is unsupported.", pointer + "/codeBlobUid", uid)
                elif target.get("nodeUid") != node_uid or target.get("parmName") != parm_name:
                    block("HOCUS809", "Code blob target does not match its binding.", pointer + "/codeBlobUid", uid)
                elif target.get("bindingUid") not in {None, uid}:
                    block("HOCUS809", "Code blob target bindingUid does not match its binding.",
                          pointer + "/codeBlobUid", uid)
                else:
                    encoded = _format_code(str(language), body)
                    used_code_uids.add(str(code_uid))
        else:
            block("HOCUS808", "Expression, channel-reference, ramp, multiparm, and other compound bindings are unsupported in HocusScript 0.1 export.",
                  pointer + "/valueMode", uid, valueMode=mode)
        if encoded is not None:
            parms_by_node.setdefault(str(node_uid), []).append((parm_name, encoded))
            if uid:
                supported_binding_uids.add(uid)
    for index, blob in enumerate(collections["codeBlobs"]):
        if isinstance(blob, dict) and isinstance(blob.get("uid"), str) and blob["uid"] not in used_code_uids:
            block("HOCUS809", "Orphan code blobs are opaque and cannot be silently discarded.",
                  f"/codeBlobs/{index}", blob["uid"])

    managed_uids = {str(node["uid"]) for node in authored_nodes} | supported_edge_uids | supported_binding_uids | used_code_uids
    ownerships, ownership_complete = _managed_ownership(collections, managed_uids)
    if len(ownerships) > 1 or (ownerships and not ownership_complete):
        block("HOCUS810", "Owned export requires one identical ownership namespace on every managed entity; ownership is never broadened.",
              "/metadata", ownerships=sorted(ownerships), complete=ownership_complete)
    ownership = next(iter(ownerships), None) if ownership_complete else None
    if ownership is not None and not _is_utf8(ownership):
        block("HOCUS810", "Ownership namespace is not valid UTF-8 source text.", "/metadata")

    resolved_graph_name = graph_name or _normalized_graph_name(root_path)
    if not isinstance(resolved_graph_name, str) or _IDENTIFIER.fullmatch(resolved_graph_name) is None:
        block("HOCUS811", "graph_name must be a HocusScript identifier.", "/graphName")

    managed_fields = _managed_fields(authored_nodes, inputs_by_dest, parms_by_node,
                                     display_nodes, render_nodes, output_nodes)
    provenance = _provenance(document, identities, ownerships, managed_fields, preserved_state)
    provider: CatalogProvider | None = None
    if catalog is not None:
        try:
            provider = SnapshotCatalogProvider(catalog) if isinstance(catalog, CatalogSnapshot) else catalog
            snapshot = provider.get_catalog()
            provenance["catalogFingerprint"] = snapshot.fingerprint
        except Exception as exc:
            block("HOCUS813", "Catalog could not be read for semantic export validation.",
                  "/catalog", errorType=exc.__class__.__name__, error=str(exc))
    if diagnostics:
        return _result(None, diagnostics, provenance)

    lines = ["hocus 0.1;", "", f"graph {resolved_graph_name} {{",
             f"  target {_format_scalar(root_path)};", "  category Sop;", "  mode merge;"]
    if type(revision) is int and revision >= 0:
        lines.append(f"  expect revision {revision};")
    if ownership is not None:
        lines.append(f"  ownership {_format_scalar(ownership)};")
    for node in sorted(authored_nodes, key=lambda item: (str(item.get("path")), str(item.get("uid")))):
        uid = str(node["uid"])
        lines.extend(("", f"  node {node['name']} @id({_format_scalar(uid)}): {_format_scalar(node['typeName'])} {{"))
        for input_index, source_uid, output_index in sorted(inputs_by_dest.get(uid, [])):
            lines.append(f"    input[{input_index}] = {nodes_by_uid[source_uid]['name']}.output[{output_index}];")
        for parm_name, encoded in sorted(parms_by_node.get(uid, [])):
            lines.append(f"    {parm_name} = {encoded};")
        lines.append("  }")
    display = display_nodes[0]["name"] if display_nodes else None
    render = render_nodes[0]["name"] if render_nodes else None
    output = output_nodes[0]["name"] if output_nodes else None
    if any(item is not None for item in (display, render, output)):
        lines.append("")
    if display is not None:
        lines.append(f"  display = {display};")
    if render is not None:
        lines.append(f"  render = {render};")
    if output is not None:
        lines.append(f"  output = {output};")
    lines.append("}")
    source = "\n".join(lines) + "\n"
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        block("HOCUS812", "Normalized export exceeds the HocusScript source-size limit.", "")
        return _result(None, diagnostics, provenance)
    compiled = compile_source(source, f"{resolved_graph_name}.hocus",
                              source_uri=f"hocus-export://{resolved_graph_name}.hocus")
    if not compiled.valid or compiled.graph_spec is None:
        for item in compiled.diagnostics:
            block("HOCUS813", "Exporter output failed structural recompilation.",
                  item.json_pointer or "", originalCode=item.code, originalMessage=item.message)
    elif provider is not None:
        semantic = resolve_graph(
            compiled.graph_spec,
            provider,
            constraint=CatalogConstraint(provenance["catalogFingerprint"]),
        )
        if not semantic.valid or not semantic.ready_for_document_lowering:
            semantic_diagnostics = semantic.diagnostics or []
            for item in semantic_diagnostics:
                block("HOCUS813", "Exporter output failed exact-catalog semantic resolution.",
                      item.json_pointer or "", originalCode=item.code, originalMessage=item.message)
            if not semantic_diagnostics:
                block("HOCUS813", "Exporter output is not ready for document lowering.", "/catalog")
    if diagnostics:
        return _result(None, diagnostics, provenance)
    provenance["sourceDigest"] = "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
    return _result(source, diagnostics, provenance)


def _result(source: str | None, diagnostics: list[ExportDiagnostic], provenance: dict[str, Any]) -> NetworkDocumentExport:
    sentinels = [item for item in diagnostics if item.code == "HOCUS819"]
    ordered_items = sorted(
        (item for item in diagnostics if item.code != "HOCUS819"),
        key=lambda item: (item.json_pointer, item.code, item.entity_uid or ""),
    )
    if sentinels:
        ordered_items.append(sentinels[-1])
    result = NetworkDocumentExport(source, tuple(ordered_items), copy.deepcopy(provenance))
    encoded_size = len(json.dumps(
        result.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8"))
    if encoded_size <= MAX_EXPORT_RESPONSE_BYTES:
        return result

    bounded_provenance = _empty_provenance()
    for key in ("documentId", "documentRevision", "rootPath", "catalogFingerprint"):
        if key in provenance:
            bounded_provenance[key] = copy.deepcopy(provenance[key])
    return NetworkDocumentExport(
        None,
        (ExportDiagnostic(
            "HOCUS820",
            "Export response exceeds the native handoff budget; narrow the network scope.",
            "",
            details={"actualBytes": encoded_size, "limitBytes": MAX_EXPORT_RESPONSE_BYTES},
        ),),
        bounded_provenance,
    )


def _truncated_export_diagnostic(omitted_count: int) -> ExportDiagnostic:
    return ExportDiagnostic(
        "HOCUS819",
        f"Export blocker manifest truncated; {omitted_count} additional blocker(s) omitted.",
        "",
        details={"omittedCount": omitted_count, "limit": MAX_EXPORT_DIAGNOSTICS},
    )


def _empty_provenance() -> dict[str, Any]:
    return {"format": "hocus-export-provenance-v0.1", "identityMode": "explicit_id_and_sidecar",
            "inlineIdentitySyntaxAvailable": True, "entities": {}, "managedFields": {}, "preservedState": [],
            "ownershipNamespaces": [], "catalogFingerprint": None, "sourceDigest": None}


def _provenance(document: dict[str, Any], identities: dict[str, dict[str, Any]], ownerships: set[str],
                managed_fields: dict[str, dict[str, Any]], preserved_state: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _empty_provenance()
    payload.update({"documentId": document.get("documentId"),
                    "documentRevision": document.get("documentRevision"),
                    "rootPath": document.get("rootPath"),
                    "ownershipNamespaces": sorted(ownerships),
                    "entities": {uid: identities[uid] for uid in sorted(identities)},
                    "managedFields": {uid: managed_fields[uid] for uid in sorted(managed_fields)},
                    "preservedState": sorted(preserved_state, key=lambda item: (
                        str(item.get("kind")), str(item.get("nodeUid")), str(item.get("field")), str(item.get("uid"))
                    ))})
    return payload


def _preserved(kind: str, uid: Any, node_uid: Any, field: str, reason: str) -> dict[str, Any]:
    payload = {"kind": kind, "field": field, "reason": reason}
    if isinstance(uid, str) and uid:
        payload["uid"] = uid
    if isinstance(node_uid, str) and node_uid:
        payload["nodeUid"] = node_uid
    return payload


def _node_managed_manifest(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    metadata = node.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    manifest = hocus.get("managedFields") if isinstance(hocus, dict) else None
    if not isinstance(manifest, dict):
        return None
    inputs, parameters, flags = manifest.get("inputs"), manifest.get("parameters"), manifest.get("flags")
    if not isinstance(inputs, list) or not isinstance(parameters, list) or not isinstance(flags, dict):
        return None
    return manifest


def _identity_record(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {"kind": kind}
    for key in ("path", "name", "nodeUid", "parmName"):
        if item.get(key) is not None:
            record[key] = copy.deepcopy(item[key])
    metadata = item.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    if isinstance(hocus, dict):
        durable = {key: copy.deepcopy(hocus[key]) for key in _PROVENANCE_FIELDS if key in hocus}
        if durable:
            record["hocus"] = durable
    return record


def _managed_ownership(collections: dict[str, list[Any]], managed_uids: set[str]) -> tuple[set[str], bool]:
    ownerships: set[str] = set()
    covered = 0
    for items in collections.values():
        for item in items:
            if not isinstance(item, dict) or item.get("uid") not in managed_uids:
                continue
            metadata = item.get("metadata")
            hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
            ownership = hocus.get("ownership") if isinstance(hocus, dict) else None
            if isinstance(ownership, str) and ownership:
                ownerships.add(ownership)
                covered += 1
    return ownerships, covered == len(managed_uids)


def _managed_fields(nodes: list[dict[str, Any]], inputs: dict[str, list[tuple[int, str, int]]],
                    parms: dict[str, list[tuple[str, str]]], displays: list[dict[str, Any]],
                    renders: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    display_uids, render_uids, output_uids = ({str(item["uid"]) for item in group}
                                                  for group in (displays, renders, outputs))
    return {
        str(node["uid"]): {
            "symbol": node["name"], "type": True,
            "inputs": sorted(item[0] for item in inputs.get(str(node["uid"]), [])),
            "parameters": sorted(item[0] for item in parms.get(str(node["uid"]), [])),
            "flags": {
                **({"display": str(node["uid"]) in display_uids} if display_uids else {}),
                **({"render": str(node["uid"]) in render_uids} if render_uids else {}),
                **({"output": str(node["uid"]) in output_uids} if output_uids else {}),
            },
            "preservedFields": [
                name for name, present in (
                    ("position", node.get("position") is not None),
                    ("definitionRef", node.get("definitionRef") is not None),
                    ("tags", node.get("tags") is not None),
                ) if present
            ],
        }
        for node in nodes
    }


def _normalized_graph_name(root_path: str) -> str:
    basename = root_path.rstrip("/").rsplit("/", 1)[-1] if root_path else "network"
    value = re.sub(r"[^A-Za-z0-9_]", "_", basename) or "network"
    return "network_" + value if value[0].isdigit() else value


def _canonical_path(path: str) -> bool:
    if path == "/":
        return True
    return _is_utf8(path) and path.startswith("/") and not path.endswith("/") and all(
        segment not in {"", ".", ".."} for segment in path.split("/")[1:])


def _is_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return _is_utf8(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value.bit_length() <= 850
    return isinstance(value, float) and math.isfinite(value)


def _is_utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _format_code(language: str, body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").replace("`", "\\`")
    return f"{language}`{normalized}`"
