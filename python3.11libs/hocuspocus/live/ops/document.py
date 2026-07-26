"""Document-oriented graph resources and tools built over the current graph snapshot."""

from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


class DocumentOperationsMixin:
    _DOCUMENT_NODE_UID_KEY = "hpmcp.uid"
    _DOCUMENT_NODE_OWNER_KEY = "hpmcp.owner"
    _DOCUMENT_NODE_SOURCE_KEY = "hpmcp.source_uri"
    _DOCUMENT_NODE_GRAPH_KEY = "hpmcp.graph"
    _DOCUMENT_NODE_COMPILER_KEY = "hpmcp.compiler_version"
    _DOCUMENT_NODE_PROVENANCE_KEY = "hpmcp.provenance"
    _DOCUMENT_NODE_PROVENANCE_DIGEST_KEY = "hpmcp.provenance_sha256"
    _MAX_NODE_PROVENANCE_BYTES = 16 * 1024
    _NETWORK_DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/network-document/v1"
    _SCENE_DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/scene-document/v1"
    _DOCUMENT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/network-document/v1"
    _CODE_LANGUAGE_ALIASES = {
        "python": "python",
        "py": "python",
        "hscript": "hscript",
        "script": "hscript",
        "vex": "vex",
    }
    _VEX_CODE_PARM_NAMES = {"snippet", "vex", "vexpression", "snippet1", "snippet2"}
    _PYTHON_CODE_PARM_NAMES = {"python", "pythoncode"}
    _SCRIPT_CODE_PARM_NAMES = {"script", "prescript", "postscript"}

    def _document_schema_path(self) -> Path:
        return core_paths.package_root() / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_schema_payload(self) -> dict[str, Any]:
        path = self._document_schema_path()
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _document_json_pointer(path: tuple[str | int, ...]) -> str:
        if not path:
            return ""
        return "/" + "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in path)

    @staticmethod
    def _document_schema_type_matches(value: Any, expected: str) -> bool:
        if expected == "null":
            return value is None
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "string":
            return isinstance(value, str)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return True

    def _document_schema_errors(
        self,
        value: Any,
        schema: dict[str, Any],
        root_schema: dict[str, Any],
        path: tuple[str | int, ...] = (),
    ) -> list[dict[str, Any]]:
        """Validate the locked document schema without a Houdini-side dependency.

        This intentionally implements only the Draft 2020-12 vocabulary used by
        the checked-in network-document schema. Keeping the schema authoritative
        prevents the hand-written semantic checks below from drifting on shape.
        """
        if "$ref" in schema:
            reference = schema["$ref"]
            if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
                return [{"path": path, "message": f"Unsupported schema reference: {reference}"}]
            resolved = root_schema.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
            if not isinstance(resolved, dict):
                return [{"path": path, "message": f"Unresolved schema reference: {reference}"}]
            return self._document_schema_errors(value, resolved, root_schema, path)

        errors: list[dict[str, Any]] = []
        for branch in schema.get("allOf", []):
            if isinstance(branch, dict):
                errors.extend(self._document_schema_errors(value, branch, root_schema, path))
        condition = schema.get("if")
        if isinstance(condition, dict):
            matches = not self._document_schema_errors(value, condition, root_schema, path)
            selected = schema.get("then" if matches else "else")
            if isinstance(selected, dict):
                errors.extend(self._document_schema_errors(value, selected, root_schema, path))
        if "const" in schema and value != schema["const"]:
            errors.append({"path": path, "message": f"must equal {schema['const']!r}"})
        if "enum" in schema and value not in schema["enum"]:
            errors.append({"path": path, "message": f"must be one of {schema['enum']!r}"})
        if "anyOf" in schema:
            branches = [
                self._document_schema_errors(value, branch, root_schema, path)
                for branch in schema["anyOf"]
                if isinstance(branch, dict)
            ]
            if not branches or all(branch for branch in branches):
                errors.append({"path": path, "message": "does not match any allowed schema form"})
                return errors

        expected_type = schema.get("type")
        if isinstance(expected_type, str) and not self._document_schema_type_matches(value, expected_type):
            errors.append({"path": path, "message": f"must be of type {expected_type}"})
            return errors

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for required in schema.get("required", []):
                if required not in value:
                    errors.append({"path": path + (required,), "message": "is required"})
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append({"path": path + (key,), "message": "is not an allowed property"})
            for key, child in value.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, dict):
                    errors.extend(self._document_schema_errors(child, child_schema, root_schema, path + (key,)))
        elif isinstance(value, list):
            minimum = schema.get("minItems")
            maximum = schema.get("maxItems")
            if isinstance(minimum, int) and len(value) < minimum:
                errors.append({"path": path, "message": f"must contain at least {minimum} items"})
            if isinstance(maximum, int) and len(value) > maximum:
                errors.append({"path": path, "message": f"must contain at most {maximum} items"})
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, child in enumerate(value):
                    errors.extend(self._document_schema_errors(child, item_schema, root_schema, path + (index,)))
        elif isinstance(value, str):
            minimum = schema.get("minLength")
            maximum = schema.get("maxLength")
            if isinstance(minimum, int) and len(value) < minimum:
                errors.append({"path": path, "message": f"must contain at least {minimum} characters"})
            if isinstance(maximum, int) and len(value) > maximum:
                errors.append({"path": path, "message": f"must contain at most {maximum} characters"})
            pattern = schema.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, value) is None:
                errors.append({"path": path, "message": f"must match pattern {pattern!r}"})
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                errors.append({"path": path, "message": f"must be at least {minimum}"})
            if isinstance(maximum, (int, float)) and value > maximum:
                errors.append({"path": path, "message": f"must be at most {maximum}"})
        return errors

    def _document_schema_diagnostics(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        schema = self._document_schema_payload()
        return [
            {
                "severity": "error",
                "code": "document.schema_violation",
                "message": error["message"],
                "jsonPointer": self._document_json_pointer(error["path"]),
            }
            for error in self._document_schema_errors(document, schema, schema)
        ]

    @staticmethod
    def _document_clean_diagnostics(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Omit absent optional fields so emitted diagnostics satisfy the schema."""
        return [
            {key: value for key, value in diagnostic.items() if value is not None}
            for diagnostic in diagnostics
        ]

    @staticmethod
    def _document_node_uid(path: str) -> str:
        return f"node:{path}"

    @staticmethod
    def _document_binding_uid(node_uid: str, parm_name: str) -> str:
        return f"binding:{node_uid}:{parm_name}"

    @staticmethod
    def _document_code_blob_uid(node_uid: str, parm_name: str) -> str:
        return f"code:{node_uid}:{parm_name}"

    @staticmethod
    def _document_port_uid(node_uid: str, direction: str, index: int) -> str:
        return f"port:{node_uid}:{direction}:{index}"

    def _document_live_node_identity(self, path: str) -> tuple[str, str]:
        path = str(path or "").strip()
        if not path:
            return "", "missing"
        try:
            hou_module = self._require_hou()
            node = hou_module.node(path)
            if node is not None:
                persistent_uid = str(
                    self._safe_value(lambda: node.userData(self._DOCUMENT_NODE_UID_KEY), "") or ""
                ).strip()
                if persistent_uid:
                    return persistent_uid, "persistent_user_data"
                session_id = self._safe_value(node.sessionId, None)
                if session_id is not None:
                    return f"node-session:{session_id}", "session_fallback"
        except Exception:
            pass
        return self._document_node_uid(path), "path_fallback"

    def _document_live_node_uid(self, path: str) -> str:
        return self._document_live_node_identity(path)[0]

    def _document_live_node_provenance(
        self,
        node: Any,
        persistent_uid: str,
        identity_mode: str,
    ) -> dict[str, Any] | None:
        if identity_mode != "persistent_user_data":
            return None
        raw = str(self._safe_value(lambda: node.userData(self._DOCUMENT_NODE_PROVENANCE_KEY), "") or "")
        declared = str(
            self._safe_value(lambda: node.userData(self._DOCUMENT_NODE_PROVENANCE_DIGEST_KEY), "") or ""
        ).strip()
        if not raw or len(raw.encode("utf-8")) > self._MAX_NODE_PROVENANCE_BYTES:
            return None
        actual = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if len(declared) != 64 or not hmac.compare_digest(declared, actual):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or set(payload) != {"version", "uid", "hocus"}:
            return None
        hocus = payload.get("hocus")
        if payload.get("version") != 1 or payload.get("uid") != persistent_uid or not isinstance(hocus, dict):
            return None
        source_uri = hocus.get("sourceUri")
        if not isinstance(source_uri, str) or not source_uri or not isinstance(hocus.get("jsonPointer"), str):
            return None
        if not self._document_provenance_span_valid(hocus.get("span"), source_uri):
            return None
        for key in ("projectUid", "sourceDigest", "bundleDigest", "compilerVersion", "graphName", "symbol"):
            if not isinstance(hocus.get(key), str) or not hocus[key] or len(hocus[key]) > 1024:
                return None
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hocus["sourceDigest"]):
            return None
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hocus["bundleDigest"]):
            return None
        if not self._document_managed_fields_valid(hocus.get("managedFields"), persistent_uid):
            return None
        mirrors = (
            (self._DOCUMENT_NODE_OWNER_KEY, hocus.get("ownership")),
            (self._DOCUMENT_NODE_SOURCE_KEY, hocus.get("sourceUri")),
            (self._DOCUMENT_NODE_GRAPH_KEY, hocus.get("graphName")),
            (self._DOCUMENT_NODE_COMPILER_KEY, hocus.get("compilerVersion")),
        )
        for key, expected in mirrors:
            normalized = str(expected or "").strip()
            stored = str(self._safe_value(lambda key=key: node.userData(key), "") or "").strip()
            if normalized and stored != normalized:
                return None
        return copy.deepcopy(hocus)

    @staticmethod
    def _document_managed_fields_valid(value: Any, persistent_uid: str) -> bool:
        if value is None:
            return True
        if not isinstance(value, dict) or set(value) != {"type", "inputs", "parameters", "flags", "nodeUid"}:
            return False
        if value.get("type") is not True or value.get("nodeUid") != persistent_uid:
            return False
        inputs, parameters, flags = value.get("inputs"), value.get("parameters"), value.get("flags")
        if not isinstance(inputs, list) or len(inputs) > 4096 or len(set(inputs)) != len(inputs):
            return False
        if any(type(item) is not int or item < 0 for item in inputs):
            return False
        if not isinstance(parameters, list) or len(parameters) > 65536 or len(set(parameters)) != len(parameters):
            return False
        if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) is None for item in parameters):
            return False
        if not isinstance(flags, dict) or not set(flags) <= {"display", "render", "output"}:
            return False
        return all(type(item) is bool for item in flags.values())

    @staticmethod
    def _document_provenance_span_valid(value: Any, source_uri: str) -> bool:
        if not isinstance(value, dict) or value.get("sourceUri") != source_uri:
            return False
        positions = []
        for key in ("start", "end"):
            position = value.get(key)
            if not isinstance(position, dict) or set(position) != {"line", "column", "offset"}:
                return False
            line, column, offset = position["line"], position["column"], position["offset"]
            if (
                type(line) is not int or line < 1
                or type(column) is not int or column < 1
                or type(offset) is not int or offset < 0
            ):
                return False
            positions.append((offset, line, column))
        return positions[0] <= positions[1]

    def _document_stamp_live_node_uid(self, path: str, uid: Any) -> None:
        persistent_uid = str(uid or "").strip()
        if not path or not persistent_uid:
            return
        self._require_node_by_path(path).setUserData(self._DOCUMENT_NODE_UID_KEY, persistent_uid)

    def _document_stamp_live_node_metadata(self, path: str, node_payload: dict[str, Any]) -> None:
        self._document_stamp_live_node_uid(path, node_payload.get("uid"))
        metadata = node_payload.get("metadata")
        hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
        if not isinstance(hocus, dict):
            return
        node = self._require_node_by_path(path)
        values = (
            (self._DOCUMENT_NODE_OWNER_KEY, hocus.get("ownership")),
            (self._DOCUMENT_NODE_SOURCE_KEY, hocus.get("sourceUri")),
            (self._DOCUMENT_NODE_GRAPH_KEY, hocus.get("graphName")),
            (self._DOCUMENT_NODE_COMPILER_KEY, hocus.get("compilerVersion")),
        )
        for key, value in values:
            normalized = str(value or "").strip()
            if normalized:
                node.setUserData(key, normalized)
        provenance = {
            "version": 1,
            "uid": str(node_payload.get("uid", "")).strip(),
            "hocus": copy.deepcopy(hocus),
        }
        encoded = json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode("utf-8")) > self._MAX_NODE_PROVENANCE_BYTES:
            raise JsonRpcError(INVALID_PARAMS, "Managed node provenance exceeds the bounded user-data limit.")
        node.setUserData(self._DOCUMENT_NODE_PROVENANCE_KEY, encoded)
        node.setUserData(
            self._DOCUMENT_NODE_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    def _document_clear_live_node_metadata(self, path: str) -> None:
        node = self._require_node_by_path(path)
        for key in (
            self._DOCUMENT_NODE_UID_KEY,
            self._DOCUMENT_NODE_OWNER_KEY,
            self._DOCUMENT_NODE_SOURCE_KEY,
            self._DOCUMENT_NODE_GRAPH_KEY,
            self._DOCUMENT_NODE_COMPILER_KEY,
            self._DOCUMENT_NODE_PROVENANCE_KEY,
            self._DOCUMENT_NODE_PROVENANCE_DIGEST_KEY,
        ):
            self._safe_value(lambda key=key: node.destroyUserData(key), None)

    def _document_live_input_connections(self, dest_path: str) -> list[dict[str, Any]]:
        """Read connection objects without reducing them to input-node paths."""
        try:
            node = self._require_hou().node(dest_path)
            if node is None:
                return []
            connections = self._safe_value(node.inputConnections, []) or []
        except Exception:
            return []
        payloads: list[dict[str, Any]] = []
        for ordinal, connection in enumerate(connections):
            source = self._safe_value(connection.inputNode, None)
            source_path = self._safe_value(source.path, None) if source is not None else None
            if not source_path:
                continue
            payloads.append(
                {
                    "sourcePath": str(source_path),
                    "destPath": dest_path,
                    "inputIndex": int(self._safe_value(connection.inputIndex, 0) or 0),
                    # HOM names these from the connection direction: inputName is
                    # the upstream node's output, outputName is the downstream input.
                    "inputName": self._safe_value(connection.outputName, None),
                    "outputIndex": int(self._safe_value(connection.outputIndex, 0) or 0),
                    "outputName": self._safe_value(connection.inputName, None),
                    "connectionOrder": ordinal,
                }
            )
        return sorted(payloads, key=lambda item: (item["inputIndex"], item["connectionOrder"]))

    @staticmethod
    def _document_metadata(document: dict[str, Any]) -> dict[str, Any]:
        metadata = document.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            document["metadata"] = metadata
        return metadata

    def _document_resource_response(self, uri: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._resource_response_text(uri, payload, indent=2, sort_keys=True)

    @staticmethod
    def _document_nodes_by_uid(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("uid")): node
            for node in document.get("nodes", [])
            if isinstance(node, dict) and str(node.get("uid", "")).strip()
        }

    @staticmethod
    def _document_normalize_language(language: Any) -> str:
        raw = str(language or "").strip().lower()
        return DocumentOperationsMixin._CODE_LANGUAGE_ALIASES.get(raw, raw or "hscript")

    @staticmethod
    def _document_network_family(root_path: str, category: Any = None) -> str:
        root = str(root_path or "").strip()
        if root.startswith("/obj/"):
            return "sop"
        if root == "/mat" or root.startswith("/mat/"):
            return "mat"
        if root == "/stage" or root.startswith("/stage/"):
            return "lop"
        if root == "/tasks" or root.startswith("/tasks/"):
            return "top"
        if root == "/out" or root.startswith("/out/"):
            return "rop"
        category_name = str(category or "").strip().lower()
        if category_name == "lop":
            return "lop"
        if category_name == "top":
            return "top"
        if category_name in {"vop", "shop"}:
            return "mat"
        return "generic"

    @staticmethod
    def _document_code_surface_kind(parm_name: Any) -> str | None:
        normalized = str(parm_name or "").strip().lower()
        if normalized in DocumentOperationsMixin._VEX_CODE_PARM_NAMES:
            return "vex"
        if normalized in DocumentOperationsMixin._PYTHON_CODE_PARM_NAMES:
            return "python"
        if normalized in DocumentOperationsMixin._SCRIPT_CODE_PARM_NAMES:
            return "script"
        return None

    def _document_code_adapter_for(self, node_type_name: Any, parm_name: Any, language: Any) -> str | None:
        surface_kind = self._document_code_surface_kind(parm_name)
        normalized_language = self._document_normalize_language(language)
        normalized_type_name = str(node_type_name or "").strip().lower()
        if surface_kind == "vex" and normalized_language == "vex":
            return "vex_parm"
        if surface_kind == "python" and normalized_language == "python":
            return "python_parm"
        if surface_kind == "script" and normalized_language in {"hscript", "python"}:
            return f"{normalized_language}_script_parm"
        if surface_kind is None and normalized_type_name.endswith("wrangle") and normalized_language == "vex":
            return "vex_parm"
        return None

    def _document_locked_hda_boundary(self, node: Any) -> str | None:
        if bool(self._safe_method_value(node, "isEditable", True)) and bool(
            self._safe_method_value(node, "isEditableInsideLockedHDA", True)
        ):
            return None
        current = node
        while current is not None:
            if bool(self._safe_method_value(current, "isLockedHDA", False)):
                return str(self._safe_value(current.path, None) or "")
            current = self._safe_value(current.parent, None)
        return str(self._safe_value(node.path, None) or "")

    def _document_compile_channel_reference(self, channel_reference: Any, metadata: dict[str, Any] | None) -> tuple[str, str]:
        reference_path = str(channel_reference or "").strip()
        if not reference_path:
            raise JsonRpcError(INVALID_PARAMS, "channelReference must resolve to a non-empty parm path.")
        template_type = str((metadata or {}).get("templateType", "")).strip().lower()
        if template_type in {"string"}:
            return (f'chs("{reference_path}")', "hscript")
        if template_type in {"int", "toggle", "menu"}:
            return (f'chi("{reference_path}")', "hscript")
        return (f'ch("{reference_path}")', "hscript")

    def _document_validate_python_source(self, source: str) -> str | None:
        try:
            ast.parse(source)
        except SyntaxError as exc:
            return f"{exc.msg} (line {exc.lineno}, column {exc.offset})"
        return None

    def _document_root_live_node(self, root_path: str) -> Any | None:
        try:
            hou_module = self._require_hou()
        except JsonRpcError:
            return None
        return self._safe_value(lambda: hou_module.node(root_path), None)

    def _document_value_mode_for_parm(self, parm: dict[str, Any]) -> str:
        parm_name = str(parm.get("name", "")).strip().lower()
        expression = parm.get("expression")
        reference_paths = parm.get("referencePaths") or []
        if parm_name in {"snippet", "python", "pythoncode", "script", "prescript", "postscript"}:
            return "code_reference"
        if expression and reference_paths:
            return "channel_reference"
        if expression:
            return "expression"
        return "literal"

    def _document_code_blob_for_parm(self, parm: dict[str, Any], node_uid: str) -> dict[str, Any] | None:
        value_mode = self._document_value_mode_for_parm(parm)
        if value_mode != "code_reference":
            return None
        parm_path = str(parm.get("path", "")).strip()
        if not parm_path:
            return None
        parm_name = str(parm.get("name", "")).strip().lower()
        language = "python" if "python" in parm_name else "vex"
        if parm_name in {"prescript", "postscript", "script"}:
            language = "hscript"
        body = parm.get("rawValue")
        if body is None:
            body = parm.get("value", "")
        return {
            "uid": self._document_code_blob_uid(node_uid, str(parm.get("name", ""))),
            "language": language,
            "target": {
                "nodeUid": node_uid,
                "parmName": parm.get("name"),
                "bindingUid": self._document_binding_uid(node_uid, str(parm.get("name", ""))),
            },
            "body": "" if body is None else str(body),
            "metadata": {"sourceParmPath": parm_path},
        }

    def _document_binding_for_parm(self, parm: dict[str, Any], node_uid: str, code_blob_uid: str | None) -> dict[str, Any]:
        value_mode = self._document_value_mode_for_parm(parm)
        payload = {
            "uid": self._document_binding_uid(node_uid, str(parm.get("name", ""))),
            "nodeUid": node_uid,
            "parmName": parm.get("name"),
            "valueMode": value_mode,
            "metadata": {
                "path": parm.get("path"),
                "label": parm.get("label"),
                "templateType": parm.get("templateType"),
            },
        }
        if value_mode == "literal":
            payload["value"] = parm.get("rawValue")
        elif value_mode in {"expression", "channel_reference"}:
            payload["expression"] = parm.get("expression")
            payload["expressionLanguage"] = parm.get("expressionLanguage")
            refs = parm.get("referencePaths") or []
            if refs:
                payload["channelReference"] = refs[0]
        elif value_mode == "code_reference":
            payload["codeBlobUid"] = code_blob_uid
        return payload

    def _document_live_network_payload(self, snapshot: dict[str, Any], root_path: str) -> dict[str, Any]:
        subgraph = self._graph_subgraph_payload(snapshot, root_path)
        nodes: list[dict[str, Any]] = []
        node_paths: set[str] = set()
        node_uid_by_path: dict[str, str] = {}
        paths_by_node_uid: dict[str, list[str]] = {}
        hocus_by_node_uid: dict[str, dict[str, Any]] = {}
        for node in subgraph.get("nodes", []):
            path = str(node.get("path", "")).strip()
            if not path:
                continue
            node_paths.add(path)
            node_uid, identity_mode = self._document_live_node_identity(path)
            paths_by_node_uid.setdefault(node_uid, []).append(path)
            live_node = self._safe_value(lambda path=path: self._require_hou().node(path), None)
            metadata = {
                "graphPath": path,
                "childCount": node.get("childCount", 0),
                "identityMode": identity_mode,
                "inputs": copy.deepcopy(node.get("inputs", [])),
                "displayNodePath": node.get("displayNodePath"),
                "renderNodePath": node.get("renderNodePath"),
                "outputNodePath": node.get("outputNodePath"),
                "outputNodePaths": copy.deepcopy(node.get("outputNodePaths", [])),
                "materialPath": node.get("materialPath"),
                "fileOutputs": copy.deepcopy(node.get("fileOutputs", [])),
            }
            if path == root_path:
                metadata["isDocumentRoot"] = True
            if live_node is not None:
                hocus_provenance = self._document_live_node_provenance(live_node, node_uid, identity_mode)
                if hocus_provenance is not None:
                    metadata["hocus"] = hocus_provenance
                    hocus_by_node_uid[node_uid] = hocus_provenance
            payload = {
                "uid": node_uid,
                "name": node.get("name"),
                "typeName": node.get("typeName"),
                "category": node.get("category"),
                "path": path,
                "parentPath": node.get("parentPath"),
                "isNetwork": bool(node.get("isNetwork", False)),
                "position": node.get("position"),
                "flags": {
                    "display": bool((node.get("flags") or {}).get("display", False)),
                    "render": bool((node.get("flags") or {}).get("render", False)),
                    "bypass": bool((node.get("flags") or {}).get("bypass", False)),
                    "template": bool((node.get("flags") or {}).get("template", False)),
                },
                "metadata": metadata,
            }
            if bool(node.get("isNetwork", False)) and path != root_path:
                payload["subnetworkDocumentId"] = f"network:{path}"
            nodes.append(payload)
            node_uid_by_path[path] = node_uid

        code_blobs: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []

        def derived_hocus(node_uid: str, entity_kind: str) -> dict[str, Any] | None:
            node_hocus = hocus_by_node_uid.get(node_uid)
            if not isinstance(node_hocus, dict):
                return None
            return {
                key: copy.deepcopy(value)
                for key, value in node_hocus.items()
                if key in {
                    "ownership", "projectUid", "sourceUri", "sourceDigest", "bundleDigest",
                    "compilerVersion", "graphName", "symbol",
                }
            } | {"entityKind": entity_kind}

        for parm in subgraph.get("parms", []):
            node_uid = node_uid_by_path.get(str(parm.get("nodePath", "")).strip(), self._document_node_uid(str(parm.get("nodePath", "")).strip()))
            code_blob = self._document_code_blob_for_parm(parm, node_uid)
            code_blob_uid = None
            if code_blob is not None:
                code_blobs.append(code_blob)
                code_blob_uid = code_blob["uid"]
            binding = self._document_binding_for_parm(parm, node_uid, code_blob_uid)
            manifest = hocus_by_node_uid.get(node_uid, {}).get("managedFields")
            managed_parameters = manifest.get("parameters", []) if isinstance(manifest, dict) else []
            if str(binding.get("parmName", "")) in managed_parameters:
                binding_hocus = derived_hocus(node_uid, "parameter_binding")
                if binding_hocus is not None:
                    binding["metadata"]["hocus"] = binding_hocus
                    if code_blob is not None:
                        code_blob["metadata"]["hocus"] = derived_hocus(node_uid, "code_blob")
            bindings.append(binding)

        edges: list[dict[str, Any]] = []
        ports_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
        for dest_path in sorted(node_paths):
            for connection in self._document_live_input_connections(dest_path):
                source_path = connection["sourcePath"]
                if source_path not in node_paths:
                    continue
                source_endpoint: dict[str, Any] = {
                    "nodeUid": node_uid_by_path[source_path],
                    "portIndex": connection["outputIndex"],
                }
                dest_endpoint: dict[str, Any] = {
                    "nodeUid": node_uid_by_path[dest_path],
                    "portIndex": connection["inputIndex"],
                }
                if connection.get("outputName") is not None:
                    source_endpoint["portName"] = str(connection["outputName"])
                if connection.get("inputName") is not None:
                    dest_endpoint["portName"] = str(connection["inputName"])
                edge = {
                        "uid": f"edge:data:{node_uid_by_path[dest_path]}:{connection['inputIndex']}",
                        "kind": "data",
                        "from": source_endpoint,
                        "to": dest_endpoint,
                        "metadata": {
                            "sourcePath": source_path,
                            "destPath": dest_path,
                            "connectionOrder": connection["connectionOrder"],
                        },
                    }
                dest_uid = node_uid_by_path[dest_path]
                manifest = hocus_by_node_uid.get(dest_uid, {}).get("managedFields")
                managed_inputs = manifest.get("inputs", []) if isinstance(manifest, dict) else []
                if connection["inputIndex"] in managed_inputs:
                    edge_hocus = derived_hocus(dest_uid, "edge")
                    if edge_hocus is not None:
                        edge["metadata"]["hocus"] = edge_hocus
                edges.append(edge)
                for direction, node_uid, index, name in (
                    ("output", node_uid_by_path[source_path], connection["outputIndex"], connection.get("outputName")),
                    ("input", node_uid_by_path[dest_path], connection["inputIndex"], connection.get("inputName")),
                ):
                    key = (node_uid, direction, index)
                    ports_by_key[key] = {
                        "uid": self._document_port_uid(node_uid, direction, index),
                        "nodeUid": node_uid,
                        "direction": direction,
                        "name": str(name or ""),
                        "index": index,
                        "kind": "data",
                        "metadata": {},
                    }

        root_snapshot = next(
            (item for item in subgraph.get("nodes", []) if str(item.get("path", "")).strip() == root_path),
            None,
        )
        output_path = str(
            (root_snapshot or {}).get("outputNodePath")
            or (root_snapshot or {}).get("displayNodePath")
            or ""
        ).strip()
        if output_path in node_uid_by_path:
            root_uid = node_uid_by_path[root_path]
            output_uid = node_uid_by_path[output_path]
            output_edge = {
                "uid": f"edge:output:{root_uid}",
                "kind": "output_flag",
                "from": {"nodeUid": output_uid},
                "to": {"nodeUid": root_uid},
                "metadata": {"sourcePath": output_path, "destPath": root_path},
            }
            manifest = hocus_by_node_uid.get(output_uid, {}).get("managedFields")
            managed_flags = manifest.get("flags", {}) if isinstance(manifest, dict) else {}
            if managed_flags.get("output") is True:
                output_hocus = derived_hocus(output_uid, "output_flag")
                if output_hocus is not None:
                    output_edge["metadata"]["hocus"] = output_hocus
            edges.append(output_edge)

        identity_diagnostics = [
            {
                "severity": "error",
                "code": "node.uid.live_duplicate",
                "message": f"Persistent node uid is present on multiple live nodes: {uid}",
                "entityUid": uid,
                "details": {"paths": sorted(paths)},
            }
            for uid, paths in sorted(paths_by_node_uid.items())
            if uid and len(paths) > 1
        ]

        document = {
            "$schema": self._NETWORK_DOCUMENT_SCHEMA_URI,
            "kind": "network_document",
            "documentId": f"network:{root_path}",
            "documentRevision": int(snapshot.get("revision") or 0),
            "baselineLiveRevision": int(snapshot.get("revision") or 0),
            "lastSyncedLiveRevision": int(snapshot.get("revision") or 0),
            "rootPath": root_path,
            "category": next((node.get("category") for node in subgraph.get("nodes", []) if node.get("path") == root_path), None) or "Unknown",
            "metadata": {
                "graphRevision": snapshot.get("revision"),
                "graphStats": subgraph.get("stats", {}),
                "identityMode": "persistent_user_data",
            },
            "nodes": sorted(nodes, key=lambda item: item["path"]),
            "ports": sorted(ports_by_key.values(), key=lambda item: item["uid"]),
            "edges": sorted(edges, key=lambda item: item["uid"]),
            "parameterBindings": sorted(bindings, key=lambda item: item["uid"]),
            "codeBlobs": sorted(code_blobs, key=lambda item: item["uid"]),
            "diagnostics": identity_diagnostics,
        }
        document["diagnostics"] = self._document_clean_diagnostics(
            document["diagnostics"] + self._document_validate_network_document(document)
        )
        return document

    def _document_live_scene_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        scene_summary = self._scene_summary_impl()
        root_networks: list[dict[str, Any]] = []
        for path in sorted(snapshot.get("topLevelPaths", [])):
            node = next((item for item in snapshot.get("nodes", []) if item.get("path") == path), None)
            if node is None or not bool(node.get("isNetwork", False)):
                continue
            encoded = path.strip("/")
            root_networks.append(
                {
                    "documentId": f"network:{path}",
                    "path": path,
                    "uri": f"houdini://documents/network/{encoded}",
                    "category": node.get("category"),
                    "typeName": node.get("typeName"),
                }
            )
        return {
            "$schema": self._SCENE_DOCUMENT_SCHEMA_URI,
            "kind": "scene_document",
            "documentId": "scene:/",
            "documentRevision": int(snapshot.get("revision") or 0),
            "rootNetworks": root_networks,
            "metadata": {
                "graphRevision": snapshot.get("revision"),
                "graphStats": snapshot.get("stats", {}),
                "hipFilePath": scene_summary.get("hipFilePath"),
                "hipDirty": scene_summary.get("hipDirty"),
                "selection": scene_summary.get("selection"),
            },
        }

    def _document_top_level_network_paths(self, snapshot: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        for path in sorted(snapshot.get("topLevelPaths", [])):
            node = next((item for item in snapshot.get("nodes", []) if item.get("path") == path), None)
            if node is None or not bool(node.get("isNetwork", False)):
                continue
            paths.append(path)
        return paths

    def _document_sync_scene_scope(self, *, force: bool = False, sync_root_networks: bool = False) -> dict[str, Any]:
        live_revision = int(self._monitor.snapshot()["revision"])
        existing = self._graph_store.get_document_by_id("scene:/")
        if existing is not None and not force and not sync_root_networks and not self._graph_store.sync_needed("scene:/", live_revision=live_revision):
            return existing
        snapshot = self._graph_snapshot()
        if force or existing is None or self._graph_store.sync_needed("scene:/", live_revision=live_revision):
            scene_document = self._document_live_scene_payload(snapshot)
            event_name = self._graph_store.last_scope_event(None) or "sync"
            stored_scene = self._graph_store.upsert_document_from_live(
                scene_document,
                live_revision=live_revision,
                source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
            )
        else:
            stored_scene = existing
        if sync_root_networks:
            for path in self._document_top_level_network_paths(snapshot):
                if force or self._graph_store.sync_needed(path, live_revision=live_revision):
                    network_document = self._document_live_network_payload(snapshot, path)
                    event_name = self._graph_store.last_scope_event(path) or "sync"
                    self._graph_store.upsert_document_from_live(
                        network_document,
                        live_revision=live_revision,
                        source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
                    )
                    self._monitor.clear_scope_dirty(path)
        self._monitor.clear_scope_dirty("scene:/")
        return stored_scene

    def _document_current_network_payload(self, root_path: str, *, force_sync: bool = False) -> dict[str, Any]:
        live_revision = int(self._monitor.snapshot()["revision"])
        existing = self._graph_store.get_document_by_root_path(root_path)
        if existing is not None and not force_sync and not self._graph_store.sync_needed(root_path, live_revision=live_revision):
            return existing
        snapshot = self._graph_snapshot()
        live_document = self._document_live_network_payload(snapshot, root_path)
        event_name = self._graph_store.last_scope_event(root_path) or "sync"
        stored = self._graph_store.upsert_document_from_live(
            live_document,
            live_revision=live_revision,
            source="external_live_edit" if not str(event_name).startswith("tool:") else "live_sync",
        )
        self._monitor.clear_scope_dirty(root_path)
        return stored

    def _document_checkout_target(self, arguments: dict[str, Any]) -> dict[str, Any]:
        checkout_id = str(arguments.get("checkout_id", "")).strip()
        supplied_document = arguments.get("document")
        if checkout_id:
            if supplied_document is not None:
                if not isinstance(supplied_document, dict):
                    raise JsonRpcError(INVALID_PARAMS, "document must be an object.")
                snapshot = self._documents.update_working_document(checkout_id, supplied_document)
                if snapshot is None:
                    raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
            working = self._documents.working_document(checkout_id)
            if working is None:
                raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
            return {
                "checkoutId": checkout_id,
                "document": working,
                "baseline": self._documents.baseline_document(checkout_id),
            }
        if supplied_document is None or not isinstance(supplied_document, dict):
            raise JsonRpcError(INVALID_PARAMS, "Provide either checkout_id or document.")
        return {"checkoutId": None, "document": supplied_document, "baseline": None}

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
        diagnostics: list[dict[str, Any]] = self._document_schema_diagnostics(document)
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

        if document.get("$schema") != self._NETWORK_DOCUMENT_SCHEMA_URI:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "document.schema.invalid",
                    "message": "Document $schema does not match the locked network-document v1 contract.",
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
        if network_family == "generic":
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "document.network_family.generic",
                    "message": "Document root does not resolve to a known first-class network family; apply will fall back to generic node operations.",
                    "jsonPointer": "/rootPath",
                    "path": root_path or None,
                }
            )

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
            uid = str(node.get("uid", "")).strip()
            path = str(node.get("path", "")).strip()
            parent_path = str(node.get("parentPath", "")).strip()
            node_name = str(node.get("name", "")).strip()
            if not uid:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.uid.missing",
                        "message": "Each node must include uid.",
                        "jsonPointer": f"/nodes/{index}/uid",
                    }
                )
            if uid in seen_uids:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.uid.duplicate",
                        "message": f"Duplicate node uid: {uid}",
                        "jsonPointer": f"/nodes/{index}/uid",
                        "entityUid": uid,
                    }
                )
            seen_uids.add(uid)
            if not path.startswith("/"):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.path.invalid",
                        "message": "Node path must be absolute.",
                        "jsonPointer": f"/nodes/{index}/path",
                        "entityUid": uid or None,
                    }
                )
            if path in seen_paths:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.path.duplicate",
                        "message": f"Duplicate node path: {path}",
                        "jsonPointer": f"/nodes/{index}/path",
                        "entityUid": uid or None,
                        "path": path if path.startswith("/") else None,
                    }
                )
            seen_paths.add(path)
            node_uid_to_path[uid] = path
            if uid:
                node_uid_to_node[uid] = node
            if path:
                node_path_to_uid[path] = uid
            if root_path and not (path == root_path or path.startswith(f"{root_path}/")):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.scope.invalid",
                        "message": "Node path is outside the document root scope.",
                        "jsonPointer": f"/nodes/{index}/path",
                        "entityUid": uid or None,
                        "path": path if path.startswith("/") else None,
                    }
                )
            if parent_path and not parent_path.startswith("/"):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.parent.invalid",
                        "message": "parentPath must be absolute when present.",
                        "jsonPointer": f"/nodes/{index}/parentPath",
                        "entityUid": uid or None,
                    }
                )
            if path and parent_path and path != root_path and path.rsplit("/", 1)[0] != parent_path:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "node.parent_path.mismatch",
                        "message": "Node parentPath must match the directory portion of path.",
                        "jsonPointer": f"/nodes/{index}/parentPath",
                        "entityUid": uid or None,
                        "path": path,
                    }
                )
            if node_name and path.startswith("/") and path.rsplit("/", 1)[-1] != node_name:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "node.name_path.mismatch",
                        "message": "Node name does not match the basename of node path.",
                        "jsonPointer": f"/nodes/{index}/name",
                        "entityUid": uid or None,
                        "path": path,
                    }
                )

        root_node = next((node for node in nodes if isinstance(node, dict) and str(node.get("path", "")).strip() == root_path), None)
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
        if live_root is not None:
            root_node_type = str((root_node or {}).get("typeName", "")).strip() if isinstance(root_node, dict) else ""
            live_root_type = str(self._safe_value(lambda: live_root.type().name(), "") or "")
            if root_node_type and live_root_type and root_node_type != live_root_type:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "document.root_node.retype_unsupported",
                        "message": "Retyping the document root network is not supported by document.apply.",
                        "jsonPointer": "/nodes",
                        "path": root_path,
                        "details": {"currentTypeName": live_root_type, "targetTypeName": root_node_type},
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

        binding_by_uid: dict[str, dict[str, Any]] = {}
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
            if value_mode not in {"literal", "expression", "channel_reference", "code_reference"}:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.value_mode.invalid",
                        "message": "valueMode must be literal, expression, channel_reference, or code_reference.",
                        "jsonPointer": f"/parameterBindings/{index}/valueMode",
                        "entityUid": binding_uid or None,
                        "details": {"received": binding.get("valueMode")},
                    }
                )
            if value_mode == "literal" and isinstance(binding.get("value"), (list, dict)):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.compound_value.unsupported",
                        "message": "Tuple, ramp, and multiparm values are not supported as a single network-document binding; bind tuple components separately using scalar literal bindings.",
                        "jsonPointer": f"/parameterBindings/{index}/value",
                        "entityUid": binding_uid or None,
                        "details": {
                            "policy": "scalar_component_bindings",
                            "receivedType": "array" if isinstance(binding.get("value"), list) else "object",
                        },
                    }
                )
            if value_mode == "expression" and not str(binding.get("expression") or "").strip():
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.expression.missing",
                        "message": "Expression bindings must include expression text.",
                        "jsonPointer": f"/parameterBindings/{index}/expression",
                        "entityUid": binding_uid or None,
                    }
                )
            if value_mode == "channel_reference" and not (
                str(binding.get("channelReference") or "").strip() or str(binding.get("expression") or "").strip()
            ):
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "binding.channel_reference.missing",
                        "message": "Channel-reference bindings must include channelReference or a compiled expression.",
                        "jsonPointer": f"/parameterBindings/{index}/channelReference",
                        "entityUid": binding_uid or None,
                    }
                )
            if value_mode == "code_reference":
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
                    continue
                node_payload = node_uid_to_node.get(node_uid, {})
                blob = code_blob_by_uid.get(code_blob_uid, {})
                adapter = self._document_code_adapter_for(node_payload.get("typeName"), parm_name, blob.get("language"))
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
                if str(target.get("nodeUid", "")).strip() and str(target.get("nodeUid", "")).strip() != node_uid:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "binding.code_blob_target_mismatch",
                            "message": "Code blob target nodeUid does not match the binding nodeUid.",
                            "jsonPointer": f"/parameterBindings/{index}/codeBlobUid",
                            "entityUid": binding_uid or None,
                        }
                    )
                target_parm_name = str(target.get("parmName", "")).strip()
                if target_parm_name and parm_name and target_parm_name != parm_name:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "binding.code_blob_parm_mismatch",
                            "message": "Code blob target parmName does not match the binding parmName.",
                            "jsonPointer": f"/parameterBindings/{index}/parmName",
                            "entityUid": binding_uid or None,
                        }
                    )
                target_binding_uid = str(target.get("bindingUid", "")).strip()
                if target_binding_uid and binding_uid and target_binding_uid != binding_uid:
                    diagnostics.append(
                        {
                            "severity": "error",
                            "code": "binding.code_blob_binding_mismatch",
                            "message": "Code blob target bindingUid does not match the owning parameter binding.",
                            "jsonPointer": f"/parameterBindings/{index}/uid",
                            "entityUid": binding_uid or None,
                        }
                    )

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

        return diagnostics

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

    @staticmethod
    def _document_nodes_by_path(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("path")): node
            for node in document.get("nodes", [])
            if isinstance(node, dict) and str(node.get("path", "")).startswith("/")
        }

    @staticmethod
    def _document_node_uid_by_path(document: dict[str, Any]) -> dict[str, str]:
        return {
            str(node.get("path")): str(node.get("uid"))
            for node in document.get("nodes", [])
            if isinstance(node, dict) and str(node.get("path", "")).startswith("/") and str(node.get("uid", "")).strip()
        }

    @staticmethod
    def _document_bindings_by_key(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        bindings: dict[tuple[str, str], dict[str, Any]] = {}
        for binding in document.get("parameterBindings", []):
            if not isinstance(binding, dict):
                continue
            key = (str(binding.get("nodeUid", "")).strip(), str(binding.get("parmName", "")).strip())
            bindings[key] = binding
        return bindings

    @staticmethod
    def _document_code_blobs_by_uid(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(blob.get("uid")): blob
            for blob in document.get("codeBlobs", [])
            if isinstance(blob, dict) and str(blob.get("uid", "")).strip()
        }

    @staticmethod
    def _document_path_is_within(path: str, root_path: str) -> bool:
        if path == root_path:
            return True
        return bool(root_path) and path.startswith(f"{root_path}/")

    @staticmethod
    def _document_prune_descendant_paths(paths: list[str]) -> list[str]:
        roots: list[str] = []
        for path in sorted({str(item).strip() for item in paths if str(item).strip()}, key=lambda item: item.count("/")):
            if any(path == root or path.startswith(f"{root}/") for root in roots):
                continue
            roots.append(path)
        return sorted(roots, key=lambda item: item.count("/"), reverse=True)

    @staticmethod
    def _document_data_edge_uid_map(document: dict[str, Any]) -> dict[str, dict[int, str | None]]:
        inputs: dict[str, dict[int, str | None]] = {}
        for edge in document.get("edges", []):
            if not isinstance(edge, dict) or str(edge.get("kind")) != "data":
                continue
            source_uid = str((edge.get("from") or {}).get("nodeUid", "")).strip()
            dest_uid = str((edge.get("to") or {}).get("nodeUid", "")).strip()
            dest_index = int((edge.get("to") or {}).get("portIndex", 0))
            if not dest_uid:
                continue
            inputs.setdefault(dest_uid, {})[dest_index] = source_uid or None
        return inputs

    @staticmethod
    def _document_data_connection_map(document: dict[str, Any]) -> dict[str, dict[int, dict[str, Any]]]:
        connections: dict[str, dict[int, dict[str, Any]]] = {}
        for edge in document.get("edges", []):
            if not isinstance(edge, dict) or str(edge.get("kind")) != "data":
                continue
            source = edge.get("from") or {}
            dest = edge.get("to") or {}
            dest_uid = str(dest.get("nodeUid", "")).strip()
            if not dest_uid:
                continue
            dest_index = int(dest.get("portIndex", 0))
            connections.setdefault(dest_uid, {})[dest_index] = {
                "sourceUid": str(source.get("nodeUid", "")).strip() or None,
                "sourceOutputIndex": int(source.get("portIndex", 0)),
                "sourceOutputName": source.get("portName"),
                "destInputName": dest.get("portName"),
                "connectionOrder": int((edge.get("metadata") or {}).get("connectionOrder", dest_index)),
            }
        return connections

    def _document_data_edge_map(self, document: dict[str, Any]) -> dict[str, dict[int, str | None]]:
        node_uid_to_path = {
            str(node.get("uid", "")).strip(): str(node.get("path", "")).strip()
            for node in document.get("nodes", [])
            if isinstance(node, dict)
        }
        inputs: dict[str, dict[int, str | None]] = {}
        for dest_uid, slots in self._document_data_edge_uid_map(document).items():
            dest_path = node_uid_to_path.get(dest_uid)
            if not dest_path:
                continue
            for dest_index, source_uid in slots.items():
                inputs.setdefault(dest_path, {})[dest_index] = node_uid_to_path.get(source_uid) if source_uid else None
        return inputs

    def _document_path_change_inherited_only(
        self,
        uid: str,
        before_nodes_by_uid: dict[str, dict[str, Any]],
        after_nodes_by_uid: dict[str, dict[str, Any]],
        before_path_to_uid: dict[str, str],
        after_path_to_uid: dict[str, str],
        structural_changed_uids: set[str],
    ) -> bool:
        before_node = before_nodes_by_uid.get(uid)
        after_node = after_nodes_by_uid.get(uid)
        if before_node is None or after_node is None:
            return False
        if str(before_node.get("name", "")).strip() != str(after_node.get("name", "")).strip():
            return False
        before_parent_uid = before_path_to_uid.get(str(before_node.get("parentPath", "")).strip())
        after_parent_uid = after_path_to_uid.get(str(after_node.get("parentPath", "")).strip())
        if not before_parent_uid or before_parent_uid != after_parent_uid:
            return False
        if before_parent_uid not in structural_changed_uids:
            return False
        before_parent = before_nodes_by_uid.get(before_parent_uid)
        after_parent = after_nodes_by_uid.get(after_parent_uid)
        if before_parent is None or after_parent is None:
            return False
        before_path = str(before_node.get("path", "")).strip()
        after_path = str(after_node.get("path", "")).strip()
        before_parent_path = str(before_parent.get("path", "")).strip()
        after_parent_path = str(after_parent.get("path", "")).strip()
        if not self._document_path_is_within(before_path, before_parent_path) or not self._document_path_is_within(after_path, after_parent_path):
            return False
        return before_path[len(before_parent_path):] == after_path[len(after_parent_path):]

    @staticmethod
    def _document_diff_is_clean(diff: dict[str, Any]) -> bool:
        summary = diff.get("summary") if isinstance(diff, dict) else {}
        if not isinstance(summary, dict):
            return False
        for key, value in summary.items():
            if key.endswith("Count") and int(value or 0) != 0:
                return False
        return True

    def _document_diff_payload(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_nodes = self._document_nodes_by_uid(before)
        after_nodes = self._document_nodes_by_uid(after)
        before_bindings = self._document_bindings_by_key(before)
        after_bindings = self._document_bindings_by_key(after)
        before_code_blobs = self._document_code_blobs_by_uid(before)
        after_code_blobs = self._document_code_blobs_by_uid(after)
        before_edges = {json.dumps(edge, sort_keys=True): edge for edge in before.get("edges", []) if isinstance(edge, dict)}
        after_edges = {json.dumps(edge, sort_keys=True): edge for edge in after.get("edges", []) if isinstance(edge, dict)}

        created_nodes = sorted(
            [after_nodes[uid] for uid in set(after_nodes) - set(before_nodes)],
            key=lambda item: str(item.get("path", "")),
        )
        deleted_nodes = sorted(
            [before_nodes[uid] for uid in set(before_nodes) - set(after_nodes)],
            key=lambda item: str(item.get("path", "")),
        )
        changed_nodes: list[dict[str, Any]] = []
        renamed_node_count = 0
        reparented_node_count = 0
        retyped_node_count = 0
        for uid in sorted(set(before_nodes) & set(after_nodes), key=lambda item: str(after_nodes[item].get("path", ""))):
            before_node = before_nodes[uid]
            after_node = after_nodes[uid]
            changes = {}
            for key in ("path", "name", "typeName", "parentPath", "position", "flags", "subnetworkDocumentId"):
                if before_node.get(key) != after_node.get(key):
                    changes[key] = {"before": before_node.get(key), "after": after_node.get(key)}
            if changes:
                if "name" in changes or ("path" in changes and "parentPath" not in changes):
                    renamed_node_count += 1
                if "parentPath" in changes:
                    reparented_node_count += 1
                if "typeName" in changes:
                    retyped_node_count += 1
                changed_nodes.append(
                    {
                        "uid": uid,
                        "beforePath": before_node.get("path"),
                        "afterPath": after_node.get("path"),
                        "changes": changes,
                    }
                )

        changed_bindings: list[dict[str, Any]] = []
        for key in sorted(set(before_bindings) | set(after_bindings)):
            before_binding = before_bindings.get(key)
            after_binding = after_bindings.get(key)
            if before_binding is None:
                changed_bindings.append({"changeType": "created", "after": after_binding})
                continue
            if after_binding is None:
                changed_bindings.append({"changeType": "deleted", "before": before_binding})
                continue
            changes = {}
            for field in ("valueMode", "value", "expression", "expressionLanguage", "channelReference", "codeBlobUid"):
                if before_binding.get(field) != after_binding.get(field):
                    changes[field] = {"before": before_binding.get(field), "after": after_binding.get(field)}
            if changes:
                changed_bindings.append({"changeType": "updated", "bindingUid": after_binding.get("uid"), "changes": changes})

        created_edges = [after_edges[key] for key in sorted(set(after_edges) - set(before_edges))]
        deleted_edges = [before_edges[key] for key in sorted(set(before_edges) - set(after_edges))]
        changed_code_blobs: list[dict[str, Any]] = []
        for uid in sorted(set(before_code_blobs) | set(after_code_blobs)):
            before_blob = before_code_blobs.get(uid)
            after_blob = after_code_blobs.get(uid)
            if before_blob is None:
                changed_code_blobs.append({"changeType": "created", "after": after_blob})
                continue
            if after_blob is None:
                changed_code_blobs.append({"changeType": "deleted", "before": before_blob})
                continue
            changes = {
                field: {"before": before_blob.get(field), "after": after_blob.get(field)}
                for field in ("language", "target", "body")
                if before_blob.get(field) != after_blob.get(field)
            }
            if changes:
                changed_code_blobs.append({"changeType": "updated", "codeBlobUid": uid, "changes": changes})
        return {
            "summary": {
                "createdNodeCount": len(created_nodes),
                "deletedNodeCount": len(deleted_nodes),
                "changedNodeCount": len(changed_nodes),
                "renamedNodeCount": renamed_node_count,
                "reparentedNodeCount": reparented_node_count,
                "retypedNodeCount": retyped_node_count,
                "changedBindingCount": len(changed_bindings),
                "changedCodeBlobCount": len(changed_code_blobs),
                "createdEdgeCount": len(created_edges),
                "deletedEdgeCount": len(deleted_edges),
            },
            "createdNodes": created_nodes,
            "deletedNodes": deleted_nodes,
            "changedNodes": changed_nodes,
            "changedParameterBindings": changed_bindings,
            "changedCodeBlobs": changed_code_blobs,
            "createdEdges": created_edges,
            "deletedEdges": deleted_edges,
        }

    def _document_verification_diff_payload(self, authored: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
        """Compare live state only against parameter values authored by the source.

        Network documents imported from Houdini contain every observed parameter,
        while a lowered source document intentionally contains only authored
        bindings. Unauthored live/default values are therefore outside the
        verification contract and must not appear as residual changes.
        """
        authored_keys = set(self._document_bindings_by_key(authored))
        authored_code_blob_uids = {
            str(binding.get("codeBlobUid", "")).strip()
            for binding in authored.get("parameterBindings", [])
            if isinstance(binding, dict) and str(binding.get("codeBlobUid", "")).strip()
        }
        projected_authored = copy.deepcopy(authored)
        projected_live = copy.deepcopy(live)
        projected_live["parameterBindings"] = [
            binding
            for binding in live.get("parameterBindings", [])
            if isinstance(binding, dict)
            and (str(binding.get("nodeUid", "")).strip(), str(binding.get("parmName", "")).strip()) in authored_keys
        ]
        projected_live["codeBlobs"] = [
            blob
            for blob in live.get("codeBlobs", [])
            if isinstance(blob, dict) and str(blob.get("uid", "")).strip() in authored_code_blob_uids
        ]

        def edge_contract(edge: dict[str, Any], template: dict[str, Any] | None = None) -> dict[str, Any]:
            reference = template or edge
            result: dict[str, Any] = {
                "uid": edge.get("uid"),
                "kind": edge.get("kind"),
                "from": {},
                "to": {},
                "metadata": {},
            }
            for endpoint_name in ("from", "to"):
                actual = edge.get(endpoint_name) if isinstance(edge.get(endpoint_name), dict) else {}
                expected = reference.get(endpoint_name) if isinstance(reference.get(endpoint_name), dict) else {}
                endpoint = result[endpoint_name]
                for field in ("nodeUid", "portIndex"):
                    if field in expected:
                        endpoint[field] = actual.get(field)
                if "portName" in expected:
                    endpoint["portName"] = actual.get("portName")
            expected_metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
            if "connectionOrder" in expected_metadata:
                actual_metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
                result["metadata"]["connectionOrder"] = actual_metadata.get("connectionOrder")
            return result

        authored_edges = {
            str(edge.get("uid", "")): edge
            for edge in authored.get("edges", [])
            if isinstance(edge, dict) and str(edge.get("uid", ""))
        }
        projected_authored["edges"] = [edge_contract(edge) for edge in authored_edges.values()]
        projected_live["edges"] = [
            edge_contract(edge, authored_edges.get(str(edge.get("uid", ""))))
            for edge in live.get("edges", [])
            if isinstance(edge, dict)
        ]
        diff = self._document_diff_payload(projected_authored, projected_live)
        live_nodes = self._document_nodes_by_uid(live)
        provenance_fields = (
            "version", "entityKind", "projectUid", "sourceUri", "sourceDigest",
            "bundleDigest", "compilerVersion", "languageVersion", "graphName",
            "symbol", "ownership", "jsonPointer", "span",
        )
        changed_by_uid = {item.get("uid"): item for item in diff["changedNodes"]}
        for uid, expected_node in self._document_nodes_by_uid(authored).items():
            expected_metadata = expected_node.get("metadata") if isinstance(expected_node.get("metadata"), dict) else {}
            expected_hocus = expected_metadata.get("hocus") if isinstance(expected_metadata.get("hocus"), dict) else None
            actual_node = live_nodes.get(uid, {})
            actual_metadata = actual_node.get("metadata") if isinstance(actual_node.get("metadata"), dict) else {}
            actual_hocus = actual_metadata.get("hocus") if isinstance(actual_metadata.get("hocus"), dict) else None
            if expected_hocus is None and actual_hocus is None:
                continue
            expected_contract = (
                {field: copy.deepcopy(expected_hocus.get(field)) for field in provenance_fields}
                if expected_hocus is not None else None
            )
            actual_contract = (
                {field: copy.deepcopy(actual_hocus.get(field)) for field in provenance_fields}
                if actual_hocus is not None else None
            )
            if expected_contract == actual_contract:
                continue
            change = {"before": expected_contract, "after": actual_contract}
            existing = changed_by_uid.get(uid)
            if existing is None:
                existing = {
                    "uid": uid,
                    "beforePath": expected_node.get("path"),
                    "afterPath": actual_node.get("path"),
                    "changes": {},
                }
                diff["changedNodes"].append(existing)
                changed_by_uid[uid] = existing
            existing["changes"]["hocusProvenance"] = change
        diff["changedNodes"].sort(key=lambda item: str(item.get("afterPath", "")))
        diff["summary"]["changedNodeCount"] = len(diff["changedNodes"])
        return diff

    def _document_diff_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        document = payload["document"]
        baseline = payload["baseline"]
        if baseline is None:
            root_path = str(document.get("rootPath", "")).strip()
            if document.get("kind") == "network_document" and root_path:
                baseline = self._document_current_network_payload(root_path)
            else:
                baseline = {}
        diff = self._document_diff_payload(baseline, document)
        return {
            "checkoutId": payload["checkoutId"],
            "documentId": document.get("documentId"),
            "rootPath": document.get("rootPath"),
            "baselineDocumentRevision": baseline.get("documentRevision"),
            "targetDocumentRevision": document.get("documentRevision"),
            "diff": diff,
        }

    def document_diff(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_diff_impl(arguments), context)
        return self._tool_response("Computed a document diff.", data)

    def _document_query_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip()
        if root_path:
            document = self._document_current_network_payload(root_path)
            document_revision = document.get("documentRevision")
        else:
            scene = self._document_sync_scene_scope(sync_root_networks=True)
            document_revision = scene.get("documentRevision")
        store_result = self._graph_store.query_nodes(arguments)
        matches: list[dict[str, Any]] = []
        for node in store_result.get("matches", []):
            path = str(node.get("path", "")).strip()
            if not path:
                continue
            node_root_path = str(node.get("rootPath", "")).strip() or path
            encoded_root = node_root_path.strip("/")
            matches.append(
                {
                    "node": {
                        **node,
                        "uid": str(node.get("uid", "")).strip() or self._document_node_uid(path),
                    },
                    "rootPath": node_root_path,
                    "documentUri": f"houdini://documents/network/{encoded_root}" if encoded_root else "houdini://documents/network/%2F",
                }
            )
        return {
            "count": len(matches),
            "documentRevision": document_revision,
            "matches": matches,
        }

    def document_query(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_query_impl(arguments), context)
        return self._tool_response(f"Matched {data['count']} document graph node(s).", data)

    def _document_apply_state(self, baseline: dict[str, Any]) -> dict[str, Any]:
        return {
            "uidToPath": {
                str(node.get("uid", "")).strip(): str(node.get("path", "")).strip()
                for node in baseline.get("nodes", [])
                if isinstance(node, dict) and str(node.get("uid", "")).strip() and str(node.get("path", "")).strip()
            }
        }

    @staticmethod
    def _document_apply_state_current_path(state: dict[str, Any], uid: str, fallback_path: str | None = None) -> str | None:
        return str((state.get("uidToPath", {}) or {}).get(uid) or fallback_path or "").strip() or None

    def _document_apply_state_register(self, state: dict[str, Any], uid: str, path: str) -> None:
        uid = str(uid or "").strip()
        path = str(path or "").strip()
        if uid and path:
            state.setdefault("uidToPath", {})[uid] = path

    def _document_apply_state_remove_prefix(self, state: dict[str, Any], path_prefix: str) -> None:
        prefix = str(path_prefix or "").strip()
        if not prefix:
            return
        uid_to_path = state.setdefault("uidToPath", {})
        for uid, path in list(uid_to_path.items()):
            if path == prefix or path.startswith(f"{prefix}/"):
                uid_to_path.pop(uid, None)

    def _document_apply_state_replace_prefix(self, state: dict[str, Any], old_prefix: str, new_prefix: str) -> None:
        old_prefix = str(old_prefix or "").strip()
        new_prefix = str(new_prefix or "").strip()
        if not old_prefix or not new_prefix or old_prefix == new_prefix:
            return
        uid_to_path = state.setdefault("uidToPath", {})
        for uid, path in list(uid_to_path.items()):
            if path == old_prefix:
                uid_to_path[uid] = new_prefix
            elif path.startswith(f"{old_prefix}/"):
                uid_to_path[uid] = f"{new_prefix}{path[len(old_prefix):]}"

    def _document_create_live_node(self, node: dict[str, Any]) -> dict[str, Any]:
        target_path = str(node.get("path", "")).strip()
        parent_path = str(node.get("parentPath", "")).strip()
        if not target_path or not parent_path:
            raise JsonRpcError(INVALID_PARAMS, "Document create operations require both path and parentPath.")
        node_name = str(node.get("name", "")).strip() or target_path.rsplit("/", 1)[-1]
        created = self._node_create_impl(
            {
                "parent_path": parent_path,
                "node_type_name": node.get("typeName"),
                "node_name": node_name,
            }
        )
        if created.get("path") != target_path:
            created = self._node_rename_impl({"path": created["path"], "new_name": node_name, "unique_name": False})
        self._document_stamp_live_node_metadata(str(created.get("path", "")).strip(), node)
        return created

    def _document_reparent_live_node(
        self,
        *,
        path: str,
        new_parent_path: str,
        new_name: str,
    ) -> dict[str, Any]:
        hou_module = self._require_hou()
        node = self._require_node_by_path(path)
        parent = self._require_node_by_path(new_parent_path, label="new_parent_path")
        mover = getattr(hou_module, "moveNodesTo", None)
        moved_node = None
        if callable(mover):
            moved = mover((node,), parent)
            if moved:
                moved_node = moved[0]
        if moved_node is None:
            copier = getattr(hou_module, "copyNodesTo", None)
            if not callable(copier):
                raise JsonRpcError(INVALID_PARAMS, "This Houdini session does not expose a node reparent helper.")
            copied = copier((node,), parent)
            if copied:
                moved_node = copied[0]
            if moved_node is None:
                raise JsonRpcError(INVALID_PARAMS, f"Failed to reparent node {path} to {new_parent_path}.")
            node.destroy()
        desired_name = str(new_name or "").strip()
        if desired_name and moved_node.name() != desired_name:
            moved_node.setName(desired_name, unique_name=False)
        return self._node_summary(moved_node)

    def _document_move_live_node(self, path: str, position: list[float]) -> None:
        """Set an authored document position without mutating global grid bookkeeping."""
        node = self._require_node_by_path(path)
        hou_module = self._require_hou()
        node.setPosition(hou_module.Vector2((float(position[0]), float(position[1]))))

    def _document_binding_parm_path(self, state: dict[str, Any], entry: dict[str, Any]) -> str:
        node_uid = str(entry.get("nodeUid", "")).strip()
        parm_name = str(entry.get("parmName", "")).strip()
        node_path = self._document_apply_state_current_path(state, node_uid, str(entry.get("nodePath", "")).strip())
        if not node_path or not parm_name:
            raise JsonRpcError(INVALID_PARAMS, "Could not resolve the live parm target for a document apply operation.")
        return f"{node_path}/{parm_name}"

    @staticmethod
    def _document_entity_ownership(entity: dict[str, Any]) -> str | None:
        metadata = entity.get("metadata")
        hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
        ownership = hocus.get("ownership") if isinstance(hocus, dict) else None
        normalized = str(ownership or "").strip()
        return normalized or None

    def _document_reconcile_ownerships(self, document: dict[str, Any]) -> set[str]:
        metadata = document.get("metadata")
        preview = metadata.get("hocusPreview") if isinstance(metadata, dict) else None
        preview_ownership = preview.get("ownership") if isinstance(preview, dict) else None
        explicit_ownership = metadata.get("reconcileOwnership") if isinstance(metadata, dict) else None
        requested = {
            str(value).strip()
            for value in (preview_ownership, explicit_ownership)
            if str(value or "").strip()
        }
        return requested if len(requested) == 1 else set()

    def _document_build_apply_plan(
        self,
        baseline: dict[str, Any],
        target: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        baseline_nodes_by_uid = self._document_nodes_by_uid(baseline)
        target_nodes_by_uid = self._document_nodes_by_uid(target)
        baseline_path_to_uid = self._document_node_uid_by_path(baseline)
        target_path_to_uid = self._document_node_uid_by_path(target)
        root_path = str(target.get("rootPath", "")).strip()
        root_uid = target_path_to_uid.get(root_path) or baseline_path_to_uid.get(root_path)
        intersection_uids = set(baseline_nodes_by_uid) & set(target_nodes_by_uid)
        structural_changed_uids = {
            uid
            for uid in intersection_uids
            if any(
                baseline_nodes_by_uid[uid].get(key) != target_nodes_by_uid[uid].get(key)
                for key in ("path", "name", "parentPath", "typeName")
            )
        }
        replace_root_uids = {
            uid
            for uid in intersection_uids
            if uid != root_uid and baseline_nodes_by_uid[uid].get("typeName") != target_nodes_by_uid[uid].get("typeName")
        }
        replace_before_paths = [str(baseline_nodes_by_uid[uid].get("path", "")).strip() for uid in replace_root_uids]
        recreated_descendant_uids = {
            uid
            for uid in intersection_uids
            if uid not in replace_root_uids
            and any(
                self._document_path_is_within(str(baseline_nodes_by_uid[uid].get("path", "")).strip(), prefix)
                and str(baseline_nodes_by_uid[uid].get("path", "")).strip() != prefix
                for prefix in replace_before_paths
            )
        }
        create_uids = ({uid for uid in target_nodes_by_uid if uid not in baseline_nodes_by_uid} | replace_root_uids | recreated_descendant_uids) - ({root_uid} if root_uid else set())
        target_created_nodes = [
            copy.deepcopy(target_nodes_by_uid[uid])
            for uid in create_uids
            if uid in target_nodes_by_uid and str(target_nodes_by_uid[uid].get("path", "")).strip() != root_path
        ]
        create_networks = sorted(
            [node for node in target_created_nodes if bool(node.get("isNetwork", False))],
            key=lambda item: str(item.get("path", "")).count("/"),
        )
        create_leaf_nodes = sorted(
            [node for node in target_created_nodes if not bool(node.get("isNetwork", False))],
            key=lambda item: str(item.get("path", "")).count("/"),
        )

        rename_nodes: list[dict[str, Any]] = []
        reparent_nodes: list[dict[str, Any]] = []
        for uid in sorted(intersection_uids, key=lambda item: str(baseline_nodes_by_uid[item].get("path", "")).count("/")):
            if uid == root_uid or uid in create_uids or uid in replace_root_uids:
                continue
            before_node = baseline_nodes_by_uid[uid]
            after_node = target_nodes_by_uid[uid]
            if self._document_path_change_inherited_only(
                uid,
                baseline_nodes_by_uid,
                target_nodes_by_uid,
                baseline_path_to_uid,
                target_path_to_uid,
                structural_changed_uids,
            ):
                continue
            before_path = str(before_node.get("path", "")).strip()
            after_path = str(after_node.get("path", "")).strip()
            before_parent_uid = baseline_path_to_uid.get(str(before_node.get("parentPath", "")).strip())
            after_parent_uid = target_path_to_uid.get(str(after_node.get("parentPath", "")).strip())
            target_name = str(after_node.get("name", "")).strip() or after_path.rsplit("/", 1)[-1]
            if before_parent_uid != after_parent_uid:
                reparent_nodes.append(
                    {
                        "uid": uid,
                        "currentPath": before_path,
                        "targetPath": after_path,
                        "targetParentPath": str(after_node.get("parentPath", "")).strip(),
                        "targetName": target_name,
                    }
                )
                continue
            if before_path != after_path or str(before_node.get("name", "")).strip() != target_name:
                rename_nodes.append(
                    {
                        "uid": uid,
                        "currentPath": before_path,
                        "targetPath": after_path,
                        "targetName": target_name,
                    }
                )

        baseline_inputs = self._document_data_connection_map(baseline)
        target_inputs = self._document_data_connection_map(target)
        baseline_code_blobs = self._document_code_blobs_by_uid(baseline)
        force_connection_dest_uids = {
            dest_uid
            for dest_uid, desired in target_inputs.items()
            if dest_uid in create_uids
            or dest_uid in structural_changed_uids
            or any(
                connection.get("sourceUid") in structural_changed_uids
                for connection in desired.values()
                if connection.get("sourceUid")
            )
        }
        connection_changes: list[dict[str, Any]] = []
        if mode == "reconcile":
            dest_uids = sorted(target_nodes_by_uid, key=lambda item: str(target_nodes_by_uid[item].get("path", "")))
        else:
            dest_uids = sorted(target_inputs, key=lambda item: str(target_nodes_by_uid.get(item, {}).get("path", "")))
        for dest_uid in dest_uids:
            current = baseline_inputs.get(dest_uid, {})
            desired = target_inputs.get(dest_uid, {})
            if mode == "merge":
                for index, connection in sorted(desired.items()):
                    if dest_uid in force_connection_dest_uids or current.get(index) != connection:
                        source_uid = connection.get("sourceUid")
                        connection_changes.append(
                            {
                                "destUid": dest_uid,
                                "destPath": str(target_nodes_by_uid.get(dest_uid, {}).get("path", "")).strip(),
                                "inputIndex": index,
                                "sourceUid": source_uid,
                                "sourcePath": str(target_nodes_by_uid.get(source_uid, {}).get("path", "")).strip() if source_uid else None,
                                **{key: connection.get(key) for key in ("sourceOutputIndex", "sourceOutputName", "destInputName", "connectionOrder")},
                            }
                        )
                continue
            max_index = max(list(current.keys()) + list(desired.keys()), default=-1)
            for index in range(max_index + 1):
                if dest_uid in force_connection_dest_uids or current.get(index) != desired.get(index):
                    connection = desired.get(index)
                    source_uid = connection.get("sourceUid") if connection else None
                    connection_changes.append(
                        {
                            "destUid": dest_uid,
                            "destPath": str(target_nodes_by_uid.get(dest_uid, {}).get("path", "")).strip(),
                            "inputIndex": index,
                            "sourceUid": source_uid,
                            "sourcePath": str(target_nodes_by_uid.get(source_uid, {}).get("path", "")).strip() if source_uid else None,
                            **(
                                {key: connection.get(key) for key in ("sourceOutputIndex", "sourceOutputName", "destInputName", "connectionOrder")}
                                if connection
                                else {"sourceOutputIndex": 0, "sourceOutputName": None, "destInputName": None, "connectionOrder": index}
                            ),
                        }
                    )

        baseline_bindings = self._document_bindings_by_key(baseline)
        target_bindings = self._document_bindings_by_key(target)
        code_blobs = self._document_code_blobs_by_uid(target)
        parameter_resets: list[dict[str, Any]] = []
        parameter_assignments: list[dict[str, Any]] = []
        expression_updates: list[dict[str, Any]] = []
        code_blob_installs: list[dict[str, Any]] = []
        forced_binding_uids = set(create_uids)

        identity_updates = [
            {
                "uid": uid,
                "path": str(target_node.get("path", "")).strip(),
                "metadata": copy.deepcopy(target_node.get("metadata", {})),
            }
            for uid, target_node in sorted(target_nodes_by_uid.items())
            if uid in baseline_nodes_by_uid
            and str(((target_node.get("metadata") or {}).get("hocus") or {}).get("entityKind", "")) == "adopted_node"
            and (
                str((baseline_nodes_by_uid[uid].get("metadata") or {}).get("identityMode", "")) != "persistent_user_data"
                or (baseline_nodes_by_uid[uid].get("metadata") or {}).get("hocus")
                != (target_node.get("metadata") or {}).get("hocus")
            )
        ]
        identity_clears = [
            {
                "uid": uid,
                "path": str(target_node.get("path", "")).strip(),
            }
            for uid, target_node in sorted(target_nodes_by_uid.items())
            if uid in baseline_nodes_by_uid
            and isinstance((baseline_nodes_by_uid[uid].get("metadata") or {}).get("hocus"), dict)
            and not isinstance((target_node.get("metadata") or {}).get("hocus"), dict)
        ]

        def _binding_sort_key(item: tuple[tuple[str, str], dict[str, Any]]) -> tuple[str, str]:
            node_uid, parm_name = item[0]
            return (str(target_nodes_by_uid.get(node_uid, {}).get("path", "")), parm_name)

        for key, binding in sorted(target_bindings.items(), key=_binding_sort_key):
            node_uid, parm_name = key
            node_payload = target_nodes_by_uid.get(node_uid)
            if node_payload is None:
                continue
            force_install = node_uid in forced_binding_uids
            entry = {
                "bindingUid": str(binding.get("uid", "")).strip(),
                "nodeUid": node_uid,
                "nodePath": str(node_payload.get("path", "")).strip(),
                "parmName": parm_name,
                "metadata": copy.deepcopy(binding.get("metadata", {})) if isinstance(binding.get("metadata"), dict) else {},
            }
            value_mode = str(binding.get("valueMode", "")).strip()
            binding_unchanged = baseline_bindings.get(key) == binding
            if value_mode == "code_reference":
                code_blob_uid = str(binding.get("codeBlobUid", "")).strip()
                blob = code_blobs.get(code_blob_uid, {})
                blob_changed = baseline_code_blobs.get(code_blob_uid) != blob
                if not force_install and binding_unchanged and not blob_changed:
                    continue
                language = self._document_normalize_language(blob.get("language"))
                code_blob_installs.append(
                    {
                        **entry,
                        "codeBlobUid": code_blob_uid,
                        "language": language,
                        "adapter": self._document_code_adapter_for(node_payload.get("typeName"), parm_name, language),
                        "body": blob.get("body", ""),
                    }
                )
                continue
            if not force_install and binding_unchanged:
                continue
            if value_mode == "literal":
                parameter_assignments.append({**entry, "value": binding.get("value")})
                continue
            if value_mode == "expression":
                expression_updates.append(
                    {
                        **entry,
                        "expression": binding.get("expression"),
                        "expressionLanguage": self._document_normalize_language(binding.get("expressionLanguage") or "hscript"),
                    }
                )
                continue
            if value_mode == "channel_reference":
                expression = str(binding.get("expression") or "").strip()
                language = self._document_normalize_language(binding.get("expressionLanguage") or "hscript")
                if not expression:
                    expression, language = self._document_compile_channel_reference(binding.get("channelReference"), entry["metadata"])
                expression_updates.append(
                    {
                        **entry,
                        "expression": expression,
                        "expressionLanguage": language,
                        "channelReference": binding.get("channelReference"),
                    }
                )
                continue

        # Parameter bindings are sparse authored intent in every apply mode.
        # Omission means preserve live/default state; a future explicit reset
        # value form may populate parameterResets without overloading omission.

        node_updates: list[dict[str, Any]] = []
        for uid, target_node in sorted(target_nodes_by_uid.items(), key=lambda item: str(item[1].get("path", ""))):
            if str(target_node.get("path", "")).strip() == root_path:
                continue
            baseline_node = baseline_nodes_by_uid.get(uid)
            force_update = uid in create_uids
            flags = copy.deepcopy(target_node.get("flags", {}))
            position = copy.deepcopy(target_node.get("position"))
            if force_update:
                if flags or position is not None:
                    node_updates.append({"uid": uid, "path": target_node.get("path"), "flags": flags, "position": position})
                continue
            if baseline_node is not None:
                update: dict[str, Any] = {"uid": uid, "path": target_node.get("path")}
                if baseline_node.get("flags") != target_node.get("flags"):
                    update["flags"] = flags
                if baseline_node.get("position") != target_node.get("position"):
                    update["position"] = position
                if len(update) > 2:
                    node_updates.append(update)

        def output_source_uid(document: dict[str, Any]) -> str | None:
            for edge in document.get("edges", []):
                if not isinstance(edge, dict) or edge.get("kind") != "output_flag":
                    continue
                destination = edge.get("to") if isinstance(edge.get("to"), dict) else {}
                if destination.get("nodeUid") == root_uid:
                    source = edge.get("from") if isinstance(edge.get("from"), dict) else {}
                    return str(source.get("nodeUid", "")).strip() or None
            return None

        baseline_output_uid = output_source_uid(baseline)
        target_output_uid = output_source_uid(target)
        target_display_uids = sorted(
            uid for uid, node in target_nodes_by_uid.items()
            if uid != root_uid and bool((node.get("flags") or {}).get("display", False))
        )
        output_guard = {
            "sourceUid": target_output_uid,
            "targetDisplayUids": target_display_uids,
        }
        output_change = None
        if baseline_output_uid != target_output_uid:
            output_change = {
                "rootUid": root_uid,
                "rootPath": root_path,
                "beforeSourceUid": baseline_output_uid,
                "sourceUid": target_output_uid,
                "sourcePath": (
                    str(target_nodes_by_uid.get(target_output_uid, {}).get("path", "")).strip()
                    if target_output_uid
                    else None
                ),
                "targetDisplayUids": target_display_uids,
            }

        replace_nodes = [
            {
                "uid": uid,
                "currentPath": str(baseline_nodes_by_uid[uid].get("path", "")).strip(),
                "target": copy.deepcopy(target_nodes_by_uid[uid]),
            }
            for uid in sorted(replace_root_uids, key=lambda item: str(baseline_nodes_by_uid[item].get("path", "")).count("/"), reverse=True)
        ]
        delete_nodes: list[dict[str, Any]] = []
        protected_delete_nodes: list[dict[str, Any]] = []
        if mode == "reconcile":
            omitted_candidates = [
                {"uid": uid, "currentPath": str(node.get("path", "")).strip()}
                for uid, node in baseline_nodes_by_uid.items()
                if uid != root_uid
                and uid not in target_nodes_by_uid
                and not any(
                    self._document_path_is_within(str(node.get("path", "")).strip(), prefix)
                    and str(node.get("path", "")).strip() != prefix
                    for prefix in replace_before_paths
                )
            ]
            reconcile_ownerships = self._document_reconcile_ownerships(target)
            delete_candidates = [
                item
                for item in omitted_candidates
                if self._document_entity_ownership(baseline_nodes_by_uid[item["uid"]]) in reconcile_ownerships
            ]
            protected_delete_nodes = [item for item in omitted_candidates if item not in delete_candidates]
            pruned_delete_paths = self._document_prune_descendant_paths([item["currentPath"] for item in delete_candidates])
            delete_nodes = [next(item for item in delete_candidates if item["currentPath"] == path) for path in pruned_delete_paths]

        return {
            "networkFamily": self._document_network_family(root_path, target.get("category")),
            "rootNodeGuard": (
                {
                    "uid": root_uid,
                    "path": root_path,
                    "flags": copy.deepcopy(target_nodes_by_uid[root_uid].get("flags", {})),
                }
                if root_uid in target_nodes_by_uid and any(update.get("flags") for update in node_updates)
                else None
            ),
            "replaceNodes": replace_nodes,
            "createNetworkContainers": create_networks,
            "createNodes": create_leaf_nodes,
            "renameNodes": rename_nodes,
            "reparentNodes": reparent_nodes,
            "connectionChanges": connection_changes,
            "parameterResets": parameter_resets,
            "parameterAssignments": parameter_assignments,
            "expressionUpdates": expression_updates,
            "codeBlobInstalls": code_blob_installs,
            "identityUpdates": identity_updates,
            "identityClears": identity_clears,
            "nodeUpdates": node_updates,
            "outputGuard": output_guard,
            "outputChange": output_change,
            "deleteNodes": delete_nodes,
            "protectedDeleteNodes": protected_delete_nodes,
            "summary": {
                "replaceNodeCount": len(replace_nodes),
                "createNetworkContainerCount": len(create_networks),
                "createNodeCount": len(create_leaf_nodes),
                "renameNodeCount": len(rename_nodes),
                "reparentNodeCount": len(reparent_nodes),
                "connectionChangeCount": len(connection_changes),
                "parameterResetCount": len(parameter_resets),
                "parameterAssignmentCount": len(parameter_assignments),
                "expressionUpdateCount": len(expression_updates),
                "codeBlobInstallCount": len(code_blob_installs),
                "identityUpdateCount": len(identity_updates),
                "identityClearCount": len(identity_clears),
                "nodeUpdateCount": len(node_updates),
                "outputChangeCount": 1 if output_change is not None else 0,
                "deleteNodeCount": len(delete_nodes),
                "protectedDeleteNodeCount": len(protected_delete_nodes),
            },
        }

    def _document_execute_apply_plan(
        self,
        plan: dict[str, Any],
        baseline: dict[str, Any],
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> list[dict[str, Any]]:
        state = self._document_apply_state(baseline)
        executed: list[dict[str, Any]] = []

        def check_cancelled() -> None:
            if checkpoint is not None:
                checkpoint()

        for update in plan.get("identityUpdates", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(
                state,
                str(update.get("uid", "")).strip(),
                str(update.get("path", "")).strip(),
            )
            if not current_path:
                continue
            self._document_stamp_live_node_metadata(current_path, update)
            executed.append({"type": "stamp_node_uid", "uid": update.get("uid"), "path": current_path})

        for update in plan.get("identityClears", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(
                state, str(update.get("uid", "")).strip(), str(update.get("path", "")).strip()
            )
            if not current_path:
                continue
            self._document_clear_live_node_metadata(current_path)
            executed.append({"type": "clear_node_identity", "uid": update.get("uid"), "path": current_path})

        for operation in plan.get("replaceNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if current_path:
                self._node_delete_impl({"path": current_path, "ignore_missing": True})
                self._document_apply_state_remove_prefix(state, current_path)
                executed.append({"type": "replace_delete_node", "uid": operation.get("uid"), "path": current_path})
            created = self._document_create_live_node(operation.get("target", {}))
            self._document_apply_state_register(state, str(operation.get("uid", "")).strip(), str(created.get("path", "")).strip())
            executed.append({"type": "replace_create_node", "uid": operation.get("uid"), "path": created.get("path"), "nodeTypeName": created.get("typeName")})

        for group_name in ("createNetworkContainers", "createNodes"):
            for node in plan.get(group_name, []):
                check_cancelled()
                created = self._document_create_live_node(node)
                self._document_apply_state_register(state, str(node.get("uid", "")).strip(), str(created.get("path", "")).strip())
                executed.append({"type": "create_node", "uid": node.get("uid"), "path": created.get("path"), "nodeTypeName": created.get("typeName")})

        for operation in plan.get("renameNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            renamed = self._node_rename_impl({"path": current_path, "new_name": operation.get("targetName"), "unique_name": False})
            new_path = str(renamed.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current_path, new_path)
            executed.append({"type": "rename_node", "uid": operation.get("uid"), "fromPath": current_path, "path": new_path})

        for operation in plan.get("reparentNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            moved = self._document_reparent_live_node(
                path=current_path,
                new_parent_path=str(operation.get("targetParentPath", "")).strip(),
                new_name=str(operation.get("targetName", "")).strip(),
            )
            new_path = str(moved.get("path", "")).strip()
            self._document_apply_state_replace_prefix(state, current_path, new_path)
            executed.append(
                {
                    "type": "reparent_node",
                    "uid": operation.get("uid"),
                    "fromPath": current_path,
                    "path": new_path,
                    "targetParentPath": operation.get("targetParentPath"),
                }
            )

        for change in plan.get("connectionChanges", []):
            check_cancelled()
            dest_path = self._document_apply_state_current_path(
                state,
                str(change.get("destUid", "")).strip(),
                str(change.get("destPath", "")).strip(),
            )
            if not dest_path:
                continue
            source_path = self._document_apply_state_current_path(
                state,
                str(change.get("sourceUid", "")).strip(),
                str(change.get("sourcePath", "")).strip() if change.get("sourcePath") else None,
            )
            if source_path:
                self._node_connect_impl(
                    {
                        "source_node_path": source_path,
                        "dest_node_path": dest_path,
                        "dest_input_index": change["inputIndex"],
                        "source_output_index": change.get("sourceOutputIndex", 0),
                    }
                )
                executed.append(
                    {
                        "type": "connect",
                        "sourceUid": change.get("sourceUid"),
                        "sourcePath": source_path,
                        "destUid": change.get("destUid"),
                        "destPath": dest_path,
                        "inputIndex": change["inputIndex"],
                        "inputName": change.get("destInputName"),
                        "outputIndex": change.get("sourceOutputIndex", 0),
                        "outputName": change.get("sourceOutputName"),
                        "connectionOrder": change.get("connectionOrder"),
                    }
                )
            else:
                self._node_disconnect_impl({"path": dest_path, "input_index": change["inputIndex"]})
                executed.append({"type": "disconnect", "destUid": change.get("destUid"), "destPath": dest_path, "inputIndex": change["inputIndex"]})

        for reset in plan.get("parameterResets", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, reset)
            self._parm_revert_to_default_impl({"parm_path": parm_path})
            executed.append({"type": "revert_parm", "bindingUid": reset.get("bindingUid"), "parmPath": parm_path})

        assignments = [
            {"parm_path": self._document_binding_parm_path(state, update), "value": update.get("value")}
            for update in plan.get("parameterAssignments", [])
        ]
        if assignments:
            check_cancelled()
            self._parm_set_many_impl({"assignments": assignments})
            executed.append({"type": "set_many_parms", "count": len(assignments)})

        for update in plan.get("expressionUpdates", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, update)
            self._parm_set_expression_impl(
                {
                    "parm_path": parm_path,
                    "expression": update["expression"],
                    "language": update.get("expressionLanguage", "hscript"),
                }
            )
            executed.append({"type": "set_expression", "bindingUid": update.get("bindingUid"), "parmPath": parm_path})

        for update in plan.get("codeBlobInstalls", []):
            check_cancelled()
            parm_path = self._document_binding_parm_path(state, update)
            self._parm_set_impl({"parm_path": parm_path, "value": update.get("body")})
            executed.append(
                {
                    "type": "install_code_blob",
                    "bindingUid": update.get("bindingUid"),
                    "codeBlobUid": update.get("codeBlobUid"),
                    "parmPath": parm_path,
                    "language": update.get("language"),
                    "adapter": update.get("adapter"),
                }
            )

        for update in plan.get("nodeUpdates", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(update.get("uid", "")).strip(), str(update.get("path", "")).strip())
            if not current_path:
                continue
            flags = update.get("flags") or {}
            if flags:
                self._node_set_flags_impl(
                    {
                        "path": current_path,
                        "bypass": bool(flags.get("bypass", False)),
                        "display": bool(flags.get("display", False)),
                        "render": bool(flags.get("render", False)),
                        "template": bool(flags.get("template", False)),
                    }
                )
                executed.append({"type": "set_flags", "uid": update.get("uid"), "path": current_path})
            position = update.get("position")
            if isinstance(position, list) and len(position) == 2:
                self._document_move_live_node(current_path, position)
                executed.append({"type": "move_node", "uid": update.get("uid"), "path": current_path})

        output_change = plan.get("outputChange")
        if isinstance(output_change, dict):
            check_cancelled()
            source_uid = str(output_change.get("sourceUid", "")).strip()
            source_path = self._document_apply_state_current_path(
                state, source_uid, output_change.get("sourcePath")
            ) if source_uid else None
            if source_path:
                self._node_set_flags_impl({"path": source_path, "display": True})
                executed.append({
                    "type": "set_output", "rootPath": output_change.get("rootPath"),
                    "sourceUid": source_uid, "sourcePath": source_path,
                })
            else:
                executed.append({"type": "clear_output", "rootPath": output_change.get("rootPath")})

        root_guard = plan.get("rootNodeGuard")
        if isinstance(root_guard, dict) and root_guard.get("path"):
            check_cancelled()
            flags = root_guard.get("flags") or {}
            self._node_set_flags_impl(
                {
                    "path": root_guard["path"],
                    "bypass": bool(flags.get("bypass", False)),
                    "display": bool(flags.get("display", False)),
                    "render": bool(flags.get("render", False)),
                    "template": bool(flags.get("template", False)),
                }
            )
            executed.append({"type": "restore_root_flags", "uid": root_guard.get("uid"), "path": root_guard["path"]})

        for operation in plan.get("deleteNodes", []):
            check_cancelled()
            current_path = self._document_apply_state_current_path(state, str(operation.get("uid", "")).strip(), str(operation.get("currentPath", "")).strip())
            if not current_path:
                continue
            self._node_delete_impl({"path": current_path, "ignore_missing": True})
            self._document_apply_state_remove_prefix(state, current_path)
            executed.append({"type": "delete_node", "uid": operation.get("uid"), "path": current_path})
        check_cancelled()
        return executed

    def _document_apply_impl(
        self,
        arguments: dict[str, Any],
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        payload = self._document_checkout_target(arguments)
        target_document = payload["document"]
        metadata = target_document.get("metadata")
        has_hocus_entities = any(
            isinstance(item, dict)
            and (
                isinstance((item.get("metadata") or {}).get("hocus"), dict)
                or str(item.get("uid", "")).startswith(("hocus-", "binding:hocus-", "code:hocus-"))
                or str(item.get("nodeUid", "")).startswith("hocus-")
                or str((item.get("from") or {}).get("nodeUid", "")).startswith("hocus-")
                or str((item.get("to") or {}).get("nodeUid", "")).startswith("hocus-")
            )
            for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs")
            for item in target_document.get(field, [])
        )
        if (
            isinstance(metadata, dict) and isinstance(metadata.get("hocusPreview"), dict)
        ) or has_hocus_entities:
            raise JsonRpcError(
                INVALID_PARAMS,
                "HocusScript-generated documents must be applied through document.plan_bundle and document.apply_plan.",
                {"diagnosticCode": "HOCUS758"},
            )
        diagnostics = self._document_validate_network_document(target_document)
        checkout_id = payload["checkoutId"]
        if checkout_id:
            self._documents.set_diagnostics(checkout_id, diagnostics)
        blocking = [item for item in diagnostics if item.get("severity") == "error"]
        if blocking:
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": str(arguments.get("mode", "reconcile")).strip() or "reconcile",
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "valid": False,
            }

        mode = str(arguments.get("mode", "reconcile")).strip() or "reconcile"
        if mode not in {"reconcile", "merge", "validate_only"}:
            raise JsonRpcError(INVALID_PARAMS, "mode must be reconcile, merge, or validate_only.")
        root_path = str(target_document.get("rootPath", "")).strip()
        if not root_path:
            raise JsonRpcError(INVALID_PARAMS, "target document must include rootPath.")
        assert_not_quarantined = getattr(self, "_hocus_assert_not_quarantined", None)
        if callable(assert_not_quarantined):
            assert_not_quarantined(root_path)
        baseline_document = self._document_current_network_payload(root_path)
        expected_revision = arguments.get("expected_document_revision", target_document.get("documentRevision"))
        if expected_revision is not None and int(expected_revision) != int(baseline_document.get("documentRevision", -1)):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Document revision mismatch.",
                {
                    "expectedDocumentRevision": int(expected_revision),
                    "currentDocumentRevision": int(baseline_document.get("documentRevision", -1)),
                    "rootPath": root_path,
                },
            )
        compile_started = time.time()
        diff = self._document_diff_payload(baseline_document, target_document)
        plan = self._document_build_apply_plan(baseline_document, target_document, mode=mode)
        if plan.get("codeBlobInstalls") and context is not None:
            from hocuspocus.core.policy import RUN_CODE, require_capabilities
            require_capabilities(context.permissions, (RUN_CODE,))
        compile_ms = round((time.time() - compile_started) * 1000.0, 3)
        if mode == "reconcile" and plan.get("protectedDeleteNodes"):
            protected = plan["protectedDeleteNodes"]
            diagnostics = diagnostics + [
                {
                    "severity": "error",
                    "code": "reconcile.delete_unowned",
                    "message": "Reconcile cannot delete nodes outside the target document's explicit ownership namespace.",
                    "path": root_path,
                    "details": {
                        "protectedNodeCount": len(protected),
                        "protectedNodes": protected,
                    },
                }
            ]
            diagnostics = self._document_clean_diagnostics(diagnostics)
            if checkout_id:
                self._documents.set_diagnostics(checkout_id, diagnostics)
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": mode,
                "valid": False,
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "targetDocumentRevision": target_document.get("documentRevision"),
                "diff": diff,
                "plan": plan,
                "timingsMs": {"compile": compile_ms, "execute": 0.0, "verify": 0.0, "rollback": 0.0},
            }
        if mode == "validate_only":
            return {
                "checkoutId": checkout_id,
                "applied": False,
                "mode": mode,
                "valid": True,
                "diagnostics": diagnostics,
                "diagnosticCount": len(diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "targetDocumentRevision": target_document.get("documentRevision"),
                "diff": diff,
                "plan": plan,
                "timingsMs": {"compile": compile_ms, "execute": 0.0, "verify": 0.0, "rollback": 0.0},
            }

        hou_module = self._require_hou()
        label = str(arguments.get("label", f"document apply {root_path}")).strip() or f"document apply {root_path}"
        apply_commit_id = str(uuid4())
        executed: list[dict[str, Any]] = []
        refreshed: dict[str, Any] | None = None
        verification: dict[str, Any] | None = None
        verified = False
        rolled_back = False
        execute_ms = 0.0
        verify_ms = 0.0
        rollback_ms = 0.0
        error_payload: dict[str, Any] | None = None
        try:
            execute_started = time.time()
            with hou_module.undos.group(f"HocusPocus: {label}"):
                executed = self._document_execute_apply_plan(plan, baseline_document)
            execute_ms = round((time.time() - execute_started) * 1000.0, 3)
            self._monitor.mark_dirty("tool:document.apply", scope_path=root_path)
            verify_started = time.time()
            refreshed = self._document_current_network_payload(root_path, force_sync=True)
            verification = self._document_verification_diff_payload(target_document, refreshed)
            verify_ms = round((time.time() - verify_started) * 1000.0, 3)
            verified = self._document_diff_is_clean(verification)
            if not verified:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Live apply verification mismatch.",
                    {"rootPath": root_path, "verificationSummary": verification.get("summary")},
                )
        except Exception as exc:
            error_payload = {"type": exc.__class__.__name__, "message": str(exc)}
            rollback_started = time.time()
            try:
                hou_module.undos.undo()
                rolled_back = True
            except Exception as rollback_exc:
                error_payload["rollbackError"] = str(rollback_exc)
            rollback_ms = round((time.time() - rollback_started) * 1000.0, 3)
            self._monitor.mark_dirty("tool:document.apply.rollback", scope_path=root_path)
            refreshed = self._document_current_network_payload(root_path, force_sync=True)
            failure_diagnostics = diagnostics + [
                {
                    "severity": "error",
                    "code": "apply.execution_failed",
                    "message": str(exc),
                    "path": root_path,
                    "details": {"rolledBack": rolled_back},
                }
            ]
            if checkout_id:
                self._documents.set_diagnostics(checkout_id, failure_diagnostics)
            if hasattr(self._graph_store, "record_apply_result"):
                self._graph_store.record_apply_result(
                    apply_commit_id=apply_commit_id,
                    document_id=str((refreshed or target_document).get("documentId")),
                    root_path=root_path,
                    baseline_document_revision=int(baseline_document.get("documentRevision", 0)),
                    applied_document_revision=int((refreshed or {}).get("documentRevision", 0)) if refreshed is not None else None,
                    mode=mode,
                    verified=False,
                    summary={
                        "verification": (verification or diff).get("summary"),
                        "plan": plan.get("summary"),
                        "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
                        "rolledBack": rolled_back,
                    },
                    operations=executed,
                    diagnostics=failure_diagnostics,
                    error=error_payload,
                )
            return {
                "checkoutId": checkout_id,
                "applyCommitId": apply_commit_id,
                "applied": False,
                "mode": mode,
                "valid": True,
                "diagnostics": failure_diagnostics,
                "diagnosticCount": len(failure_diagnostics),
                "baselineDocumentRevision": baseline_document.get("documentRevision"),
                "appliedDocumentRevision": (refreshed or {}).get("documentRevision") if refreshed is not None else None,
                "diff": diff,
                "plan": plan,
                "executedOperations": executed,
                "verification": verification,
                "verified": False,
                "rolledBack": rolled_back,
                "error": error_payload,
                "document": refreshed,
                "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
            }
        if checkout_id:
            self._documents.replace_with_applied_document(checkout_id, refreshed or target_document)
        if hasattr(self._graph_store, "record_apply_result"):
            self._graph_store.record_apply_result(
                apply_commit_id=apply_commit_id,
                document_id=str((refreshed or target_document).get("documentId")),
                root_path=root_path,
                baseline_document_revision=int(baseline_document.get("documentRevision", 0)),
                applied_document_revision=int((refreshed or target_document).get("documentRevision", 0)),
                mode=mode,
                verified=verified,
                summary={
                    "verification": (verification or {}).get("summary"),
                    "plan": plan.get("summary"),
                    "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
                    "rolledBack": False,
                },
                operations=executed,
                diagnostics=diagnostics,
                error=None,
            )
        return {
            "checkoutId": checkout_id,
            "applyCommitId": apply_commit_id,
            "applied": True,
            "mode": mode,
            "valid": True,
            "diagnostics": diagnostics,
            "diagnosticCount": len(diagnostics),
            "baselineDocumentRevision": baseline_document.get("documentRevision"),
            "appliedDocumentRevision": refreshed.get("documentRevision"),
            "diff": diff,
            "plan": plan,
            "executedOperations": executed,
            "verification": verification,
            "verified": verified,
            "rolledBack": False,
            "document": refreshed,
            "timingsMs": {"compile": compile_ms, "execute": execute_ms, "verify": verify_ms, "rollback": rollback_ms},
        }

    def document_apply(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_apply_impl(arguments, context), context)
        if not data.get("valid", False):
            return self._tool_response(f"Document apply blocked by {data['diagnosticCount']} diagnostic(s).", data)
        if data.get("error"):
            if data.get("rolledBack", False):
                return self._tool_response("Document apply failed and the live scene was rolled back to the previous state.", data)
            return self._tool_response("Document apply failed before verification completed.", data)
        if not data.get("applied", False):
            return self._tool_response("Computed a validate-only document apply plan.", data)
        if data.get("verified", False):
            return self._tool_response("Applied document changes and verified the resulting network document.", data)
        return self._tool_response("Applied document changes, but verification reported residual differences.", data)

    def _document_checkout_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scope = str(arguments.get("scope", "network")).strip().lower()
        if scope == "scene":
            document = self._document_sync_scene_scope(sync_root_networks=True)
            root_path = None
        else:
            root_path = str(arguments.get("root_path", "")).strip()
            if not root_path:
                raise JsonRpcError(INVALID_PARAMS, "root_path is required for network document checkouts.")
            document = self._document_current_network_payload(root_path)
        return self._documents.create_checkout(
            document_id=str(document.get("documentId")),
            document_kind=str(document.get("kind")),
            root_path=root_path,
            document=document,
        )

    def document_checkout(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_checkout_impl(arguments), context)
        return self._tool_response(f"Created document checkout {data['checkoutId']}.", data)

    def _document_discard_checkout_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        checkout_id = str(arguments.get("checkout_id", "")).strip()
        if not checkout_id:
            raise JsonRpcError(INVALID_PARAMS, "checkout_id is required.")
        discarded = self._documents.discard(checkout_id)
        if not discarded:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
        return {"checkoutId": checkout_id, "discarded": True}

    def document_discard_checkout(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_discard_checkout_impl(arguments), context)
        return self._tool_response(f"Discarded document checkout {data['checkoutId']}.", data)

    def _document_sync_from_houdini_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path", "")).strip()
        if root_path:
            return self._document_current_network_payload(root_path, force_sync=True)
        return self._document_sync_scene_scope(force=True, sync_root_networks=True)

    def document_sync_from_houdini(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_sync_from_houdini_impl(arguments), context)
        scope_label = data.get("rootPath") or "scene"
        return self._tool_response(f"Synchronized document scope {scope_label} from the live Houdini session.", data)

    def read_document_scene(self, context: RequestContext) -> dict[str, Any]:
        return self._document_resource_response(
            "houdini://documents/scene",
            self._call_live(lambda: self._document_sync_scene_scope(sync_root_networks=True), context),
        )

    def read_document_schema(self, context: RequestContext) -> dict[str, Any]:
        return self._document_resource_response(
            self._DOCUMENT_SCHEMA_RESOURCE_URI,
            self._document_schema_payload(),
        )

    def read_document_network(self, root_path: str, context: RequestContext) -> dict[str, Any]:
        uri = f"houdini://documents/network/{root_path.strip('/')}" if root_path != "/" else "houdini://documents/network/%2F"
        return self._document_resource_response(
            uri,
            self._call_live(lambda: self._document_current_network_payload(root_path), context),
        )

    def read_document_checkout(self, checkout_id: str, context: RequestContext) -> dict[str, Any]:
        document = self._documents.working_document(checkout_id)
        if document is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
        return self._document_resource_response(f"houdini://documents/checkouts/{checkout_id}", document)

    def read_document_diagnostics(self, checkout_id: str, context: RequestContext) -> dict[str, Any]:
        payload = self._documents.diagnostics_payload(checkout_id)
        if payload is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown checkout_id: {checkout_id}")
        return self._document_resource_response(f"houdini://documents/diagnostics/{checkout_id}", payload)
