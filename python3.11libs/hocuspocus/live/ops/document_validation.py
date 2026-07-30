"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

from typing import Any

from hocuspocus.hocusscript.document_provenance import (
    DocumentProvenanceError,
    validate_expansion_references,
)
from hocuspocus.hocusscript.document_value_validation import (
    DocumentValueValidationError,
    validate_v2_binding,
)
from hocuspocus.hocusscript.document_runtime_contract import (
    DocumentRuntimeContractError,
    validate_runtime_contract,
)
from hocuspocus.hocusscript.document_editor_entities import (
    DocumentEditorEntityError,
    editor_entities_from_document,
)
from .document_network_families import network_family_policy

from ..context import RequestContext


def _validate_v1_binding_value(
    binding: dict[str, Any],
    index: int,
    binding_uid: str,
    value_mode: str,
    diagnostics: list[dict[str, Any]],
) -> None:
    pointer = f"/parameterBindings/{index}"
    if value_mode not in {
        "literal", "expression", "channel_reference", "code_reference",
    }:
        diagnostics.append({
            "severity": "error",
            "code": "binding.value_mode.invalid",
            "message": (
                "valueMode must be literal, expression, "
                "channel_reference, or code_reference."
            ),
            "jsonPointer": pointer + "/valueMode",
            "entityUid": binding_uid or None,
            "details": {"received": binding.get("valueMode")},
        })
    if value_mode == "literal" and isinstance(
        binding.get("value"), (list, dict)
    ):
        diagnostics.append({
            "severity": "error",
            "code": "binding.compound_value.unsupported",
            "message": (
                "Network-document v1 compound values must use scalar "
                "component bindings."
            ),
            "jsonPointer": pointer + "/value",
            "entityUid": binding_uid or None,
        })
    if value_mode == "expression" and not str(
        binding.get("expression") or ""
    ).strip():
        diagnostics.append({
            "severity": "error",
            "code": "binding.expression.missing",
            "message": "Expression bindings must include expression text.",
            "jsonPointer": pointer + "/expression",
            "entityUid": binding_uid or None,
        })
    if value_mode == "channel_reference" and not (
        str(binding.get("channelReference") or "").strip()
        or str(binding.get("expression") or "").strip()
    ):
        diagnostics.append({
            "severity": "error",
            "code": "binding.channel_reference.missing",
            "message": (
                "Channel-reference bindings require a reference or "
                "compiled expression."
            ),
            "jsonPointer": pointer + "/channelReference",
            "entityUid": binding_uid or None,
        })


class DocumentValidationOperationsMixin:
    def _document_validate_scene_document(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        if document.get("kind") != "scene_document":
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "scene.kind.invalid",
                    "message": "Scene documents must set kind = scene_document.",
                    "details": {"received": document.get("kind")},
                }
            )
        if not isinstance(document.get("rootNetworks"), list):
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "scene.root_networks.invalid",
                    "message": "Scene documents must include a rootNetworks array.",
                }
            )
        return diagnostics

    def _document_validate_network_document(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics = self._document_schema_diagnostics(document)
        root_path = self._document_validate_header(document, diagnostics)
        nodes = document.get("nodes", [])
        if not isinstance(nodes, list):
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.nodes.invalid",
                    "message": "nodes must be an array.",
                    "jsonPointer": "/nodes",
                }
            )
            return diagnostics
        node_uid_to_path, node_uid_to_node, node_path_to_uid = self._document_validate_nodes(
            nodes, root_path, diagnostics
        )
        self._document_validate_node_parents(nodes, root_path, node_path_to_uid, diagnostics)
        code_blob_uids, code_blob_by_uid = self._document_validate_code_blobs(
            document, node_uid_to_path, diagnostics
        )
        self._document_validate_bindings(
            document,
            node_uid_to_path,
            node_uid_to_node,
            code_blob_uids,
            code_blob_by_uid,
            diagnostics,
        )
        self._document_validate_runtime_contract(
            document, set(node_uid_to_path), diagnostics
        )
        self._document_validate_edges(document, node_uid_to_path, diagnostics)
        if document.get("$schema") == self._NETWORK_DOCUMENT_SCHEMA_URI_V2:
            try:
                editor_entities_from_document(
                    document, node_uids=node_uid_to_path,
                )
            except DocumentEditorEntityError as exc:
                diagnostics.append({
                    "severity": "error",
                    "code": "document.editor_entities.invalid",
                    "message": str(exc),
                    "jsonPointer": "/networkBoxes",
                    "details": {
                        "diagnosticCode": "HOCUS936",
                        **exc.details,
                    },
                })
        self._document_validate_expansion_references(document, diagnostics)
        return diagnostics

    @staticmethod
    def _document_validate_runtime_contract(
        document: dict[str, Any],
        node_uids: set[str],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        if document.get("$schema") != (
            "hocuspocus://schemas/network-document/v2"
        ):
            if any(
                field in document
                for field in ("spareParameters", "animations", "timeSamples")
            ):
                diagnostics.append({
                    "severity": "error",
                    "code": "runtime_contract.requires_v2",
                    "message": (
                        "Managed spares and animation require "
                        "network-document-v2."
                    ),
                })
            return
        try:
            validate_runtime_contract(document, node_uids)
        except DocumentRuntimeContractError as exc:
            code = (
                "animation.usd_time_samples.unsupported"
                if "USD time samples" in str(exc)
                else "runtime_contract.invalid"
            )
            diagnostics.append({
                "severity": "error",
                "code": code,
                "message": str(exc),
            })

    @staticmethod
    def _document_validate_expansion_references(
        document: dict[str, Any],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        try:
            validate_expansion_references(document)
        except DocumentProvenanceError as exc:
            diagnostics.append({
                "severity": "error",
                "code": "document.hocus_expansion.invalid",
                "message": str(exc),
                "jsonPointer": "/metadata/hocusExpansion",
            })

    def _document_validate_header(
        self,
        document: dict[str, Any],
        diagnostics: list[dict[str, Any]],
    ) -> str:
        required = (
            "$schema",
            "kind",
            "documentId",
            "documentRevision",
            "rootPath",
            "category",
            "nodes",
            "edges",
            "parameterBindings",
            "codeBlobs",
            "diagnostics",
        )
        for key in required:
            if key not in document:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "document.required_missing",
                        "message": f"Missing required field: {key}",
                        "jsonPointer": f"/{key}",
                    }
                )

        if document.get("$schema") not in {
            self._NETWORK_DOCUMENT_SCHEMA_URI,
            self._NETWORK_DOCUMENT_SCHEMA_URI_V2,
        }:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.schema.invalid",
                    "message": "Document $schema is not a supported network-document contract.",
                    "jsonPointer": "/$schema",
                    "details": {"received": document.get("$schema")},
                }
            )
        if document.get("kind") != "network_document":
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.kind.invalid",
                    "message": "Document kind must be network_document.",
                    "jsonPointer": "/kind",
                    "details": {"received": document.get("kind")},
                }
            )

        root_path = str(document.get("rootPath", "")).strip()
        if not root_path.startswith("/"):
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.root_path.invalid",
                    "message": "rootPath must be an absolute Houdini path.",
                    "jsonPointer": "/rootPath",
                }
            )

        network_family = self._document_network_family(root_path, document.get("category"))
        family_policy = network_family_policy(network_family)
        if not family_policy.structural_indexed_apply:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.network_family.unsupported",
                    "message": "This network family is read-only through the indexed structural document lane.",
                    "jsonPointer": "/rootPath",
                    "path": root_path or None,
                    "details": {
                        "networkFamily": network_family,
                        "supportedFamilies": ["lop", "mat", "sop", "top"],
                    },
                }
            )

        return root_path

    @staticmethod
    def _document_validate_node_entry(
        node: dict[str, Any],
        index: int,
        root_path: str,
        seen_uids: set[str],
        seen_paths: set[str],
        diagnostics: list[dict[str, Any]],
    ) -> tuple[str, str]:
        uid = str(node.get("uid", "")).strip()
        path = str(node.get("path", "")).strip()
        parent_path = str(node.get("parentPath", "")).strip()
        node_name = str(node.get("name", "")).strip()
        pointer = f"/nodes/{index}"
        checks = (
            (not uid, "node.uid.missing", "Each node must include uid.", f"{pointer}/uid"),
            (uid in seen_uids, "node.uid.duplicate", f"Duplicate node uid: {uid}", f"{pointer}/uid"),
            (not path.startswith("/"), "node.path.invalid", "Node path must be absolute.", f"{pointer}/path"),
            (path in seen_paths, "node.path.duplicate", f"Duplicate node path: {path}", f"{pointer}/path"),
            (
                bool(root_path) and not (path == root_path or path.startswith(f"{root_path}/")),
                "node.scope.invalid",
                "Node path is outside the document root scope.",
                f"{pointer}/path",
            ),
            (
                bool(parent_path) and not parent_path.startswith("/"),
                "node.parent.invalid",
                "parentPath must be absolute when present.",
                f"{pointer}/parentPath",
            ),
            (
                bool(path and parent_path and path != root_path)
                and path.rsplit("/", 1)[0] != parent_path,
                "node.parent_path.mismatch",
                "Node parentPath must match the directory portion of path.",
                f"{pointer}/parentPath",
            ),
        )
        for failed, code, message, json_pointer in checks:
            if failed:
                diagnostic = {
                    "severity": "error",
                    "code": code,
                    "message": message,
                    "jsonPointer": json_pointer,
                }
                if code != "node.uid.missing":
                    diagnostic["entityUid"] = (
                        uid if code == "node.uid.duplicate" else uid or None
                    )
                if code in {"node.path.duplicate", "node.scope.invalid", "node.parent_path.mismatch"}:
                    diagnostic["path"] = (
                        path
                        if code == "node.parent_path.mismatch"
                        else path if path.startswith("/") else None
                    )
                diagnostics.append(diagnostic)
        if node_name and path.startswith("/") and path.rsplit("/", 1)[-1] != node_name:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "node.name_path.mismatch",
                    "message": "Node name does not match the basename of node path.",
                    "jsonPointer": f"{pointer}/name",
                    "entityUid": uid or None,
                    "path": path,
                }
            )
        seen_uids.add(uid)
        seen_paths.add(path)
        return uid, path

    def _document_validate_root_node(
        self,
        nodes: list[Any],
        root_path: str,
        diagnostics: list[dict[str, Any]],
    ) -> None:
        root_node = next(
            (
                node for node in nodes
                if isinstance(node, dict) and str(node.get("path", "")).strip() == root_path
            ),
            None,
        )
        if root_path and root_node is None:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.root_node.missing",
                    "message": "The document must include a node entry for the rootPath network.",
                    "jsonPointer": "/nodes",
                    "path": root_path,
                }
            )
        elif root_node is not None and not bool(root_node.get("isNetwork", False)):
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.root_node.not_network",
                    "message": "The rootPath entry must refer to a network container.",
                    "jsonPointer": "/nodes",
                    "entityUid": str(root_node.get("uid", "")).strip() or None,
                    "path": root_path,
                }
            )
        live_root = self._document_root_live_node(root_path) if root_path.startswith("/") else None
        if live_root is None:
            return
        target_type = str((root_node or {}).get("typeName", "")).strip()
        live_type = str(self._safe_value(lambda: live_root.type().name(), "") or "")
        if target_type and live_type and target_type != live_type:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.root_node.retype_unsupported",
                    "message": "Retyping the document root network is not supported by document.apply.",
                    "jsonPointer": "/nodes",
                    "path": root_path,
                    "details": {"currentTypeName": live_type, "targetTypeName": target_type},
                }
            )
        locked_boundary = self._document_locked_hda_boundary(live_root)
        if locked_boundary:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.locked_hda_boundary",
                    "message": "This network is inside a locked HDA boundary and cannot be structurally applied through document.apply.",
                    "jsonPointer": "/rootPath",
                    "path": root_path,
                    "details": {"lockedBoundaryPath": locked_boundary},
                }
            )

    def _document_validate_nodes(
        self,
        nodes: list[Any],
        root_path: str,
        diagnostics: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
        seen_uids: set[str] = set()
        seen_paths: set[str] = set()
        node_uid_to_path: dict[str, str] = {}
        node_uid_to_node: dict[str, dict[str, Any]] = {}
        node_path_to_uid: dict[str, str] = {}
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.invalid",
                        "message": "Each node entry must be an object.",
                        "jsonPointer": f"/nodes/{index}",
                    }
                )
                continue
            uid, path = self._document_validate_node_entry(
                node, index, root_path, seen_uids, seen_paths, diagnostics
            )
            node_uid_to_path[uid] = path
            if uid:
                node_uid_to_node[uid] = node
            if path:
                node_path_to_uid[path] = uid
        self._document_validate_root_node(nodes, root_path, diagnostics)

        return node_uid_to_path, node_uid_to_node, node_path_to_uid

    @staticmethod
    def _document_validate_node_parents(
        nodes: list[Any],
        root_path: str,
        node_path_to_uid: dict[str, str],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            path = str(node.get("path", "")).strip()
            if not path or path == root_path:
                continue
            parent_path = str(node.get("parentPath", "")).strip()
            if not parent_path:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.parent.missing",
                        "message": "Non-root nodes must include parentPath.",
                        "jsonPointer": f"/nodes/{index}/parentPath",
                        "entityUid": str(node.get("uid", "")).strip() or None,
                        "path": path,
                    }
                )
                continue
            if parent_path.startswith(root_path) and parent_path not in node_path_to_uid:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.parent.missing_in_scope",
                        "message": "Node parentPath must resolve to another node in the same network document.",
                        "jsonPointer": f"/nodes/{index}/parentPath",
                        "entityUid": str(node.get("uid", "")).strip() or None,
                        "path": path,
                    }
                )


    def _document_validate_code_blobs(
        self,
        document: dict[str, Any],
        node_uid_to_path: dict[str, str],
        diagnostics: list[dict[str, Any]],
    ) -> tuple[set[str], dict[str, dict[str, Any]]]:
        code_blob_uids: set[str] = set()
        code_blob_by_uid: dict[str, dict[str, Any]] = {}
        for index, blob in enumerate(document.get("codeBlobs", [])):
            if not isinstance(blob, dict):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "code_blob.invalid",
                        "message": "Each code blob must be an object.",
                        "jsonPointer": f"/codeBlobs/{index}",
                    }
                )
                continue
            uid = str(blob.get("uid", "")).strip()
            code_blob_uids.add(uid)
            if uid:
                code_blob_by_uid[uid] = blob
            if not uid:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "code_blob.uid.missing",
                        "message": "Each code blob must include uid.",
                        "jsonPointer": f"/codeBlobs/{index}/uid",
                    }
                )
            body = blob.get("body")
            if body is not None and not isinstance(body, str):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "code_blob.body.invalid",
                        "message": "Code blob body must be a string.",
                        "jsonPointer": f"/codeBlobs/{index}/body",
                        "entityUid": uid or None,
                    }
                )
            target_node_uid = str((blob.get("target") or {}).get("nodeUid", "")).strip()
            if target_node_uid and target_node_uid not in node_uid_to_path:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "code_blob.target_missing",
                        "message": "Code blob target nodeUid does not exist in the document.",
                        "jsonPointer": f"/codeBlobs/{index}/target/nodeUid",
                        "entityUid": uid or None,
                    }
                )
            language = self._document_normalize_language(blob.get("language"))
            if language not in {"vex", "python", "hscript"}:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "code_blob.language.unsupported",
                        "message": "Code blob language must be one of vex, python, or hscript.",
                        "jsonPointer": f"/codeBlobs/{index}/language",
                        "entityUid": uid or None,
                        "details": {"received": blob.get("language")},
                    }
                )
            if language == "python" and isinstance(body, str):
                syntax_error = self._document_validate_python_source(body)
                if syntax_error:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "code_blob.python.invalid",
                            "message": f"Python code blob did not parse: {syntax_error}",
                            "jsonPointer": f"/codeBlobs/{index}/body",
                            "entityUid": uid or None,
                        }
                    )

        return code_blob_uids, code_blob_by_uid

    def _document_validate_code_binding(
        self,
        binding: dict[str, Any],
        index: int,
        binding_uid: str,
        node_uid: str,
        parm_name: str,
        node_uid_to_path: dict[str, str],
        node_uid_to_node: dict[str, dict[str, Any]],
        code_blob_uids: set[str],
        code_blob_by_uid: dict[str, dict[str, Any]],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        code_blob_uid = str(binding.get("codeBlobUid", "")).strip()
        if not code_blob_uid or code_blob_uid not in code_blob_uids:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "binding.code_blob_missing",
                    "message": "Code-reference bindings must reference an existing code blob.",
                    "jsonPointer": f"/parameterBindings/{index}/codeBlobUid",
                    "entityUid": binding_uid or None,
                }
            )
            return
        node_payload = node_uid_to_node.get(node_uid, {})
        blob = code_blob_by_uid.get(code_blob_uid, {})
        adapter = self._document_code_adapter_for(
            node_payload.get("typeName"), parm_name, blob.get("language")
        )
        if adapter is None:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "binding.code_blob_unsupported_target",
                    "message": "This code blob target is not supported by the current apply adapters.",
                    "jsonPointer": f"/parameterBindings/{index}/codeBlobUid",
                    "entityUid": binding_uid or None,
                    "path": node_uid_to_path.get(node_uid),
                    "details": {
                        "nodeTypeName": node_payload.get("typeName"),
                        "parmName": parm_name,
                        "language": blob.get("language"),
                    },
                }
            )
        target = blob.get("target") if isinstance(blob.get("target"), dict) else {}
        target_uid = str(target.get("nodeUid", "")).strip()
        if target_uid and target_uid != node_uid:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "binding.code_blob_target_mismatch",
                    "message": "Code blob target nodeUid does not match the binding nodeUid.",
                    "jsonPointer": f"/parameterBindings/{index}/codeBlobUid",
                    "entityUid": binding_uid or None,
                }
            )
        target_parm = str(target.get("parmName", "")).strip()
        if target_parm and parm_name and target_parm != parm_name:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "binding.code_blob_parm_mismatch",
                    "message": "Code blob target parmName does not match the binding parmName.",
                    "jsonPointer": f"/parameterBindings/{index}/parmName",
                    "entityUid": binding_uid or None,
                }
            )
        target_binding = str(target.get("bindingUid", "")).strip()
        if target_binding and binding_uid and target_binding != binding_uid:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "binding.code_blob_binding_mismatch",
                    "message": "Code blob target bindingUid does not match the owning parameter binding.",
                    "jsonPointer": f"/parameterBindings/{index}/uid",
                    "entityUid": binding_uid or None,
                }
            )

    def _document_validate_bindings(
        self,
        document: dict[str, Any],
        node_uid_to_path: dict[str, str],
        node_uid_to_node: dict[str, dict[str, Any]],
        code_blob_uids: set[str],
        code_blob_by_uid: dict[str, dict[str, Any]],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        binding_by_uid: dict[str, dict[str, Any]] = {}
        document_v2 = (
            document.get("$schema") == self._NETWORK_DOCUMENT_SCHEMA_URI_V2
        )
        node_uids = set(node_uid_to_path)
        for index, binding in enumerate(document.get("parameterBindings", [])):
            if not isinstance(binding, dict):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.invalid",
                        "message": "Each parameter binding must be an object.",
                        "jsonPointer": f"/parameterBindings/{index}",
                    }
                )
                continue
            binding_uid = str(binding.get("uid", "")).strip()
            node_uid = str(binding.get("nodeUid", "")).strip()
            value_mode = str(binding.get("valueMode", "")).strip()
            parm_name = str(binding.get("parmName", "")).strip()
            if document_v2:
                try:
                    validate_v2_binding(binding, node_uids)
                except DocumentValueValidationError as exc:
                    diagnostics.append({
                        "severity": "error",
                        "code": "binding.v2.invalid",
                        "message": str(exc),
                        "jsonPointer": f"/parameterBindings/{index}",
                        "entityUid": binding_uid or None,
                    })
                    continue
            if binding_uid:
                binding_by_uid[binding_uid] = binding
            else:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.uid.missing",
                        "message": "Each parameter binding must include uid.",
                        "jsonPointer": f"/parameterBindings/{index}/uid",
                    }
                )
            if node_uid not in node_uid_to_path:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.node_missing",
                        "message": "Parameter binding references a nodeUid that is not present in the document.",
                        "jsonPointer": f"/parameterBindings/{index}/nodeUid",
                        "entityUid": binding_uid or None,
                    }
                )
            if not parm_name:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.parm_name.missing",
                        "message": "Parameter bindings must include parmName.",
                        "jsonPointer": f"/parameterBindings/{index}/parmName",
                        "entityUid": binding_uid or None,
                    }
                )
            if not document_v2:
                _validate_v1_binding_value(
                    binding, index, binding_uid, value_mode, diagnostics
                )
            if value_mode == "code_reference":
                self._document_validate_code_binding(
                    binding,
                    index,
                    binding_uid,
                    node_uid,
                    parm_name,
                    node_uid_to_path,
                    node_uid_to_node,
                    code_blob_uids,
                    code_blob_by_uid,
                    diagnostics,
                )


    @staticmethod
    def _document_validate_edges(
        document: dict[str, Any],
        node_uid_to_path: dict[str, str],
        diagnostics: list[dict[str, Any]],
    ) -> None:
        data_destinations: set[tuple[str, int]] = set()
        for index, edge in enumerate(document.get("edges", [])):
            if not isinstance(edge, dict):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "edge.invalid",
                        "message": "Each edge must be an object.",
                        "jsonPointer": f"/edges/{index}",
                    }
                )
                continue
            for side in ("from", "to"):
                node_uid = str((edge.get(side) or {}).get("nodeUid", "")).strip()
                if node_uid not in node_uid_to_path:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "edge.endpoint_missing",
                            "message": f"Edge {side} endpoint references a missing nodeUid.",
                            "jsonPointer": f"/edges/{index}/{side}/nodeUid",
                            "entityUid": str(edge.get("uid", "")).strip() or None,
                        }
                    )
            kind = str(edge.get("kind", "")).strip()
            if kind == "data":
                for side in ("from", "to"):
                    endpoint = edge.get(side) or {}
                    if "portIndex" not in endpoint:
                        diagnostics.append(
                            {
                                "severity": "error",
                                "code": "edge.port_index.missing",
                                "message": "Data edge endpoints require an explicit portIndex.",
                                "jsonPointer": f"/edges/{index}/{side}/portIndex",
                                "entityUid": str(edge.get("uid", "")).strip() or None,
                            }
                        )
                dest = edge.get("to") or {}
                dest_uid = str(dest.get("nodeUid", "")).strip()
                if dest_uid and "portIndex" in dest:
                    destination = (dest_uid, int(dest["portIndex"]))
                    if destination in data_destinations:
                        diagnostics.append(
                            {
                                "severity": "error",
                                "code": "edge.destination.duplicate",
                                "message": "Only one data edge may target a destination input index.",
                                "jsonPointer": f"/edges/{index}/to/portIndex",
                                "entityUid": str(edge.get("uid", "")).strip() or None,
                                "details": {"nodeUid": dest_uid, "portIndex": destination[1]},
                            }
                        )
                    data_destinations.add(destination)
            if kind and kind != "data":
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "edge.kind.unspecialized",
                        "message": "Only data edges participate in document.apply today; other edge kinds are preserved for reads only.",
                        "jsonPointer": f"/edges/{index}/kind",
                        "entityUid": str(edge.get("uid", "")).strip() or None,
                        "details": {"received": kind},
                    }
                )


    def _document_validate_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        document = payload["document"]
        if document.get("kind") == "scene_document":
            diagnostics = self._document_validate_scene_document(document)
        else:
            diagnostics = self._document_validate_network_document(document)
        checkout_id = payload["checkoutId"]
        if checkout_id:
            self._documents.set_diagnostics(checkout_id, diagnostics)
        return {
            "checkoutId": checkout_id,
            "valid": not any(item.get("severity") == "error" for item in diagnostics),
            "diagnosticCount": len(diagnostics),
            "diagnostics": diagnostics,
            "documentKind": document.get("kind"),
            "documentId": document.get("documentId"),
            "rootPath": document.get("rootPath"),
            "documentRevision": document.get("documentRevision"),
        }

    def document_validate(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_validate_impl(arguments), context)
        if data["valid"]:
            return self._tool_response("Document validation passed.", data)
        return self._tool_response(f"Document validation reported {data['diagnosticCount']} diagnostic(s).", data)
