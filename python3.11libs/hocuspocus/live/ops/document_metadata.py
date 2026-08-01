"""Internal mixin for document-oriented live operations."""

from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from .document_network_families import resolve_network_family



class DocumentMetadataOperationsMixin:
    def _document_schema_path(self, version: int = 1) -> Path:
        return (
            core_paths.package_root()
            / "docs"
            / "schemas"
            / f"network-document-v{version}.schema.json"
        )

    def _document_schema_payload(self, version: int = 1) -> dict[str, Any]:
        path = (
            self._document_schema_path()
            if version == 1
            else (
                core_paths.package_root()
                / "docs"
                / "schemas"
                / f"network-document-v{version}.schema.json"
            )
        )
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
            v1_prefix = (
                "hocuspocus://schemas/network-document/v1#/$defs/"
            )
            if isinstance(reference, str) and reference.startswith(v1_prefix):
                v1_schema = self._document_schema_payload(1)
                resolved = v1_schema.get("$defs", {}).get(
                    reference.removeprefix(v1_prefix)
                )
                if not isinstance(resolved, dict):
                    return [{
                        "path": path,
                        "message": f"Unresolved schema reference: {reference}",
                    }]
                return self._document_schema_errors(
                    value, resolved, v1_schema, path
                )
            if (
                not isinstance(reference, str)
                or not reference.startswith("#/$defs/")
            ):
                return [{"path": path, "message": f"Unsupported schema reference: {reference}"}]
            resolved = root_schema.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
            if not isinstance(resolved, dict):
                return [{"path": path, "message": f"Unresolved schema reference: {reference}"}]
            return self._document_schema_errors(value, resolved, root_schema, path)

        errors = self._document_schema_composition_errors(value, schema, root_schema, path)
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

        errors.extend(self._document_schema_value_errors(value, schema, root_schema, path))
        return errors

    def _document_schema_composition_errors(
        self,
        value: Any,
        schema: dict[str, Any],
        root_schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
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
        return errors

    def _document_schema_value_errors(
        self,
        value: Any,
        schema: dict[str, Any],
        root_schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return self._document_schema_object_errors(value, schema, root_schema, path)
        if isinstance(value, list):
            return self._document_schema_array_errors(value, schema, root_schema, path)
        if isinstance(value, str):
            return self._document_schema_string_errors(value, schema, path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return self._document_schema_number_errors(value, schema, path)
        return []

    def _document_schema_object_errors(
        self,
        value: dict[str, Any],
        schema: dict[str, Any],
        root_schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
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
        return errors

    def _document_schema_array_errors(
        self,
        value: list[Any],
        schema: dict[str, Any],
        root_schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        minimum, maximum = schema.get("minItems"), schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append({"path": path, "message": f"must contain at least {minimum} items"})
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append({"path": path, "message": f"must contain at most {maximum} items"})
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, child in enumerate(value):
                errors.extend(self._document_schema_errors(child, item_schema, root_schema, path + (index,)))
        return errors

    @staticmethod
    def _document_schema_string_errors(
        value: str,
        schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        minimum, maximum = schema.get("minLength"), schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append({"path": path, "message": f"must contain at least {minimum} characters"})
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append({"path": path, "message": f"must contain at most {maximum} characters"})
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append({"path": path, "message": f"must match pattern {pattern!r}"})
        return errors

    @staticmethod
    def _document_schema_number_errors(
        value: int | float,
        schema: dict[str, Any],
        path: tuple[str | int, ...],
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        minimum, maximum = schema.get("minimum"), schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append({"path": path, "message": f"must be at least {minimum}"})
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append({"path": path, "message": f"must be at most {maximum}"})
        return errors

    def _document_schema_diagnostics(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        version = (
            2
            if document.get("$schema") == self._NETWORK_DOCUMENT_SCHEMA_URI_V2
            else 1
        )
        schema = self._document_schema_payload(version)
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
        payload = self._document_decode_live_provenance(node, identity_mode)
        if payload is None:
            return None
        hocus = payload.get("hocus")
        if not isinstance(hocus, dict) or not self._document_provenance_valid(payload, hocus, persistent_uid):
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

    def _document_decode_live_provenance(self, node: Any, identity_mode: str) -> dict[str, Any] | None:
        if identity_mode != "persistent_user_data":
            return None
        raw = str(self._safe_value(lambda: node.userData(self._DOCUMENT_NODE_PROVENANCE_KEY), "") or "")
        declared = str(
            self._safe_value(lambda: node.userData(self._DOCUMENT_NODE_PROVENANCE_DIGEST_KEY), "") or ""
        ).strip()
        try:
            raw_bytes = raw.encode("utf-8")
        except UnicodeEncodeError:
            return None
        if not raw_bytes or len(raw_bytes) > self._MAX_NODE_PROVENANCE_BYTES:
            return None
        actual = hashlib.sha256(raw_bytes).hexdigest()
        if len(declared) != 64 or not hmac.compare_digest(declared, actual):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _document_provenance_valid(
        self,
        payload: dict[str, Any],
        hocus: dict[str, Any],
        persistent_uid: str,
    ) -> bool:
        if set(payload) != {"version", "uid", "hocus"}:
            return False
        if payload.get("version") != 1 or payload.get("uid") != persistent_uid:
            return False
        source_uri = hocus.get("sourceUri")
        if not isinstance(source_uri, str) or not source_uri or not isinstance(hocus.get("jsonPointer"), str):
            return False
        if not self._document_provenance_span_valid(hocus.get("span"), source_uri):
            return False
        for key in ("projectUid", "sourceDigest", "bundleDigest", "compilerVersion", "graphName", "symbol"):
            if not isinstance(hocus.get(key), str) or not hocus[key] or len(hocus[key]) > 1024:
                return False
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hocus["sourceDigest"]):
            return False
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", hocus["bundleDigest"]):
            return False
        return (
            self._document_managed_fields_valid(
                hocus.get("managedFields"), persistent_uid
            )
            and self._document_h5_entity_provenance_valid(hocus)
        )

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
        if not self._document_provenance_valid(
            provenance, provenance["hocus"], provenance["uid"]
        ):
            raise JsonRpcError(INVALID_PARAMS, "Managed node provenance is malformed.")
        encoded = json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        try:
            encoded_bytes = encoded.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise JsonRpcError(INVALID_PARAMS, "Managed node provenance contains invalid Unicode.") from exc
        if len(encoded_bytes) > self._MAX_NODE_PROVENANCE_BYTES:
            raise JsonRpcError(INVALID_PARAMS, "Managed node provenance exceeds the bounded user-data limit.")
        node.setUserData(self._DOCUMENT_NODE_PROVENANCE_KEY, encoded)
        node.setUserData(
            self._DOCUMENT_NODE_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(encoded_bytes).hexdigest(),
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

    def _document_live_input_connections(
        self,
        dest_path: str,
        *,
        ignored_input_item_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
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
            if ignored_input_item_names:
                input_item_method = getattr(connection, "inputItem", None)
                input_item = (
                    self._safe_value(input_item_method, None)
                    if callable(input_item_method) else None
                )
                input_item_name = (
                    self._safe_value(input_item.name, None)
                    if input_item is not None else None
                )
                if input_item_name in ignored_input_item_names:
                    continue
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

    @classmethod
    def _document_normalize_language(cls, language: Any) -> str:
        raw = str(language or "").strip().lower()
        return cls._CODE_LANGUAGE_ALIASES.get(raw, raw or "hscript")

    def _document_network_family(self, root_path: str, category: Any = None) -> str:
        hou_module = self._safe_value(self._require_hou, None)
        return resolve_network_family(hou_module, root_path, category)

    @classmethod
    def _document_code_surface_kind(cls, parm_name: Any) -> str | None:
        normalized = str(parm_name or "").strip().lower()
        if normalized in cls._VEX_CODE_PARM_NAMES:
            return "vex"
        if normalized in cls._PYTHON_CODE_PARM_NAMES:
            return "python"
        if normalized in cls._SCRIPT_CODE_PARM_NAMES:
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
            "metadata": {
                "sourceParmPath": parm_path,
                "isAtDefault": parm.get("isAtDefault") is True,
            },
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
                "isAtDefault": parm.get("isAtDefault") is True,
            },
        }
        if value_mode == "literal":
            template_type = str(parm.get("templateType", "")).strip().lower()
            evaluated = parm.get("value")
            payload["value"] = (
                evaluated
                if template_type in {"float", "int", "toggle", "menu"}
                and isinstance(evaluated, (int, float, bool))
                else parm.get("rawValue")
            )
        elif value_mode in {"expression", "channel_reference"}:
            payload["expression"] = parm.get("expression")
            payload["expressionLanguage"] = parm.get("expressionLanguage")
            refs = parm.get("referencePaths") or []
            if refs:
                payload["channelReference"] = refs[0]
        elif value_mode == "code_reference":
            payload["codeBlobUid"] = code_blob_uid
        return payload
