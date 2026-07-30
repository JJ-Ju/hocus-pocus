"""Durable host-owned receipts for network-document-v2 authored value intent."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import struct
from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_value_validation import (
    DocumentValueValidationError,
    validate_v1_receipt_binding,
    validate_v2_binding,
)

_FORMAT = "network-document-typed-bindings-v0.1"


class DocumentTypedReceiptOperationsMixin:
    _DOCUMENT_TYPED_BINDINGS_KEY = "hpmcp.typed_bindings"
    _DOCUMENT_TYPED_BINDINGS_DIGEST_KEY = "hpmcp.typed_bindings_sha256"
    _MAX_DOCUMENT_TYPED_BINDINGS_BYTES = 4 * 1024 * 1024
    _MAX_DOCUMENT_TYPED_BINDINGS = 100_000

    def _document_typed_receipt_from_document(
        self, document: dict[str, Any],
    ) -> dict[str, Any] | None:
        if document.get("$schema") not in {
            self._NETWORK_DOCUMENT_SCHEMA_URI,
            self._NETWORK_DOCUMENT_SCHEMA_URI_V2,
        }:
            return None
        node_uids = sorted(
            str(item.get("uid", "")).strip()
            for item in document.get("nodes", [])
            if isinstance(item, dict) and str(item.get("uid", "")).strip()
        )
        known = set(node_uids)
        bindings = []
        for binding in document.get("parameterBindings", []):
            if (
                document["$schema"] == self._NETWORK_DOCUMENT_SCHEMA_URI
                and not _has_parameter_selection(binding)
            ):
                continue
            try:
                self._document_validate_receipt_binding(
                    binding, known, document["$schema"]
                )
            except DocumentValueValidationError as exc:
                raise JsonRpcError(
                    INVALID_PARAMS, f"Typed binding receipt is invalid: {exc}"
                ) from exc
            bindings.append(copy.deepcopy(binding))
        bindings.sort(key=lambda item: item["uid"])
        if (
            document["$schema"] == self._NETWORK_DOCUMENT_SCHEMA_URI
            and not bindings
        ):
            return None
        if len(bindings) > self._MAX_DOCUMENT_TYPED_BINDINGS:
            raise JsonRpcError(
                INVALID_PARAMS, "Typed binding receipt exceeds its entry limit."
            )
        return self._document_normalize_typed_receipt({
            "format": _FORMAT,
            "documentId": document["documentId"],
            "documentSchema": document["$schema"],
            "nodeUids": node_uids,
            "bindings": bindings,
        })

    def _document_plan_root_typed_receipt(
        self, baseline: dict[str, Any], target: dict[str, Any],
    ) -> dict[str, Any] | None:
        before = self._document_typed_receipt_from_document(baseline)
        after = self._document_typed_receipt_from_document(target)
        if before == after:
            return None
        return {
            "rootPath": str(target.get("rootPath", "")).strip(),
            "table": after,
        }

    def _document_execute_root_typed_receipt(
        self,
        plan: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        change = plan.get("rootTypedBindingChange")
        if not isinstance(change, dict):
            return
        checkpoint()
        root = self._require_node_by_path(str(change["rootPath"]))
        table = change.get("table")
        if table is None:
            for key in (
                self._DOCUMENT_TYPED_BINDINGS_KEY,
                self._DOCUMENT_TYPED_BINDINGS_DIGEST_KEY,
            ):
                self._safe_value(lambda key=key: root.destroyUserData(key), None)
            action = "clear_typed_binding_receipt"
        else:
            normalized = self._document_normalize_typed_receipt(table)
            if normalized["documentId"] != f"network:{change['rootPath']}":
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Typed binding receipt documentId does not match its root.",
                )
            encoded = json.dumps(
                {"version": 1, "table": normalized},
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            raw = encoded.encode("utf-8")
            root.setUserData(self._DOCUMENT_TYPED_BINDINGS_KEY, encoded)
            root.setUserData(
                self._DOCUMENT_TYPED_BINDINGS_DIGEST_KEY,
                hashlib.sha256(raw).hexdigest(),
            )
            action = "stamp_typed_binding_receipt"
        executed.append({"type": action, "rootPath": change["rootPath"]})

    def _document_live_typed_receipt(
        self, root_path: str,
    ) -> dict[str, dict[str, Any]]:
        table = self._document_live_typed_receipt_table(root_path)
        return (
            {item["uid"]: item for item in table["bindings"]}
            if table is not None else {}
        )

    def _document_live_typed_receipt_table(
        self, root_path: str,
    ) -> dict[str, Any] | None:
        root = self._safe_value(lambda: self._require_hou().node(root_path), None)
        if root is None:
            return None
        raw = str(self._safe_value(
            lambda: root.userData(self._DOCUMENT_TYPED_BINDINGS_KEY), ""
        ) or "")
        digest = str(self._safe_value(
            lambda: root.userData(self._DOCUMENT_TYPED_BINDINGS_DIGEST_KEY), ""
        ) or "")
        try:
            encoded = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return None
        if (
            not encoded
            or len(encoded) > self._MAX_DOCUMENT_TYPED_BINDINGS_BYTES
            or len(digest) != 64
            or not hmac.compare_digest(
                digest, hashlib.sha256(encoded).hexdigest()
            )
        ):
            return None
        try:
            envelope = json.loads(raw)
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"version", "table"}
                or envelope["version"] != 1
            ):
                return None
            table = self._document_normalize_typed_receipt(envelope["table"])
            if table["documentId"] != f"network:{root_path}":
                return None
        except (
            DocumentValueValidationError, JsonRpcError, RecursionError,
            UnicodeEncodeError, json.JSONDecodeError,
        ):
            return None
        return table

    def _document_restore_typed_binding(
        self, observed: dict[str, Any], parm: dict[str, Any],
        receipt: dict[str, Any] | None,
        node_uid_by_path: dict[str, str],
    ) -> dict[str, Any]:
        if not self._document_typed_receipt_matches_observation(
            observed, parm, receipt, node_uid_by_path
        ):
            return observed
        if receipt["valueMode"] == "reset":
            result = copy.deepcopy(observed)
            result["value"] = copy.deepcopy(parm.get("value"))
            return result
        result = copy.deepcopy(receipt)
        result["metadata"] = copy.deepcopy(observed.get("metadata", {}))
        hocus = (receipt.get("metadata") or {}).get("hocus")
        if isinstance(hocus, dict):
            result["metadata"]["hocus"] = copy.deepcopy(hocus)
        selection = (receipt.get("metadata") or {}).get("parameterSelection")
        if isinstance(selection, dict):
            result["metadata"]["parameterSelection"] = copy.deepcopy(selection)
        return result

    def _document_typed_receipt_matches_observation(
        self,
        observed: dict[str, Any],
        parm: dict[str, Any],
        receipt: dict[str, Any] | None,
        node_uid_by_path: dict[str, str],
    ) -> bool:
        if receipt is None or not self._document_receipt_identity_matches(
            observed, receipt
        ):
            return False
        if receipt["valueMode"] == "reset":
            return parm.get("isAtDefault") is True
        return self._document_typed_receipt_matches_live(
            receipt, parm, node_uid_by_path
        )

    def _document_typed_receipt_matches_live(
        self,
        receipt: dict[str, Any],
        parm: dict[str, Any],
        node_uid_by_path: dict[str, str],
    ) -> bool:
        mode = receipt["valueMode"]
        raw = parm.get("rawValue")
        evaluated = parm.get("value")
        if mode == "literal":
            return receipt.get("value") == evaluated
        if mode == "menu_token":
            return receipt.get("menuToken") == raw
        if mode == "raw_path":
            return receipt.get("raw") == raw
        if mode == "quantity":
            expected = receipt.get("canonicalMagnitude")
            return (
                isinstance(expected, (int, float))
                and not isinstance(expected, bool)
                and isinstance(evaluated, (int, float))
                and not isinstance(evaluated, bool)
                and math.isclose(
                    float(expected), float(evaluated),
                    rel_tol=0.0, abs_tol=0.0,
                )
            )
        if mode == "expression":
            return (
                receipt.get("expression") == parm.get("expression")
                and receipt.get("expressionLanguage")
                == parm.get("expressionLanguage")
            )
        if mode == "channel_reference":
            reference = receipt.get("channelReference")
            if isinstance(reference, str):
                referenced = self._safe_value(
                    lambda: self._require_hou().parm(
                        parm["path"]
                    ).getReferencedParm(),
                    None,
                )
                return self._safe_value(
                    lambda: referenced.path(), None
                ) == reference
            if isinstance(reference, dict):
                expected_node_path = next(
                    (
                        path for path, uid in node_uid_by_path.items()
                        if uid == reference["nodeUid"]
                    ),
                    None,
                )
                expected = (
                    f"{expected_node_path}/{reference['parmName']}"
                    if expected_node_path else None
                )
                return (parm.get("referencePaths") or []) == [expected]
            language = receipt.get("expressionLanguage")
            return (
                receipt.get("expression") == parm.get("expression")
                and (
                    language is None
                    or language == parm.get("expressionLanguage")
                )
            )
        if mode == "ramp":
            return self._document_live_ramp_matches(receipt, parm)
        if mode == "multiparm":
            return self._document_live_multiparm_matches(
                receipt, parm, node_uid_by_path
            )
        if mode == "code_reference":
            return True
        return False

    @staticmethod
    def _document_receipt_identity_matches(
        observed: dict[str, Any], receipt: dict[str, Any],
    ) -> bool:
        if any(
            observed.get(field) != receipt.get(field)
            for field in ("uid", "nodeUid", "parmName")
        ):
            return False
        observed_hocus = (observed.get("metadata") or {}).get("hocus")
        receipt_hocus = (receipt.get("metadata") or {}).get("hocus")
        return (
            isinstance(observed_hocus, dict)
            and isinstance(receipt_hocus, dict)
            and observed_hocus == receipt_hocus
            and observed_hocus.get("entityKind") == "parameter_binding"
        )

    def _document_live_ramp_matches(
        self, receipt: dict[str, Any], parm_summary: dict[str, Any],
    ) -> bool:
        parm = self._safe_value(
            lambda: self._require_hou().parm(parm_summary["path"]), None
        )
        ramp = self._safe_value(lambda: parm.evalAsRamp(), None)
        if ramp is None:
            return False
        keys = self._safe_value(lambda: list(ramp.keys()), None)
        values = self._safe_value(lambda: list(ramp.values()), None)
        bases = self._safe_value(lambda: list(ramp.basis()), None)
        if not all(isinstance(item, list) for item in (keys, values, bases)):
            return False
        expected_positions = [
            self._document_ramp_float32(item["position"])
            for item in receipt["points"]
        ]
        expected_values = [
            self._document_ramp_float32(item["value"])
            for item in receipt["points"]
        ]
        observed_values = [
            list(item.rgb()) if callable(getattr(item, "rgb", None)) else item
            for item in values
        ]
        expected_bases = [
            self._document_ramp_basis_value(item) for item in receipt["basis"]
        ]
        return (
            keys == expected_positions
            and observed_values == expected_values
            and bases == expected_bases
        )

    @classmethod
    def _document_ramp_float32(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._document_ramp_float32(item) for item in value]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return struct.unpack(">f", struct.pack(">f", float(value)))[0]
            except (OverflowError, struct.error, ValueError):
                return None
        return value

    def _document_ramp_basis_value(self, authored: str) -> Any:
        names = {
            "constant": "Constant", "linear": "Linear",
            "catmullrom": "CatmullRom", "monotonecubic": "MonotoneCubic",
            "bezier": "Bezier", "bspline": "BSpline", "hermite": "Hermite",
        }
        return getattr(self._require_hou().rampBasis, names[authored], None)

    def _document_live_multiparm_matches(
        self,
        receipt: dict[str, Any],
        parm_summary: dict[str, Any],
        node_uid_by_path: dict[str, str],
    ) -> bool:
        parm = self._safe_value(
            lambda: self._require_hou().parm(parm_summary["path"]), None
        )
        count = self._safe_value(lambda: parm.eval(), None)
        instance_start = self._safe_value(
            lambda: parm.multiParmStartOffset(), None
        )
        instances = receipt["instances"]
        if (
            type(count) is not int
            or count != len(instances)
            or type(instance_start) is not int
            or instance_start != receipt["instanceStart"]
        ):
            return False
        contracts = {item["name"]: item for item in receipt["fieldContract"]}
        node_path = str(parm_summary["path"]).rsplit("/", 1)[0]
        for ordinal, instance in enumerate(instances):
            token_index = instance_start + ordinal
            for field in instance["fields"]:
                token = contracts[field["name"]]["tokenTemplate"].replace(
                    "#", str(token_index)
                )
                live = self._safe_value(
                    lambda token=token: self._require_hou().parm(
                        f"{node_path}/{token}"
                    ),
                    None,
                )
                if not self._document_nested_value_matches(
                    field["value"], live, node_uid_by_path
                ):
                    return False
        return True

    def _document_nested_value_matches(
        self,
        value: dict[str, Any],
        parm: Any,
        node_uid_by_path: dict[str, str],
    ) -> bool:
        if parm is None:
            return False
        kind = value["kind"]
        if kind in {"literal", "array"}:
            return self._safe_value(lambda: parm.eval(), None) == value["value"]
        if kind == "raw_path":
            return self._safe_value(lambda: parm.rawValue(), None) == value["raw"]
        if kind == "expression":
            language = self._safe_value(
                lambda: parm.expressionLanguage(), None
            )
            language_name = self._safe_value(
                lambda: language.name(), None
            )
            return (
                self._safe_value(lambda: parm.expression(), None) == value["body"]
                and isinstance(language_name, str)
                and language_name.lower() == value["language"]
            )
        if kind == "channel_reference":
            expected_path = next(
                (
                    path for path, uid in node_uid_by_path.items()
                    if uid == value["nodeUid"]
                ),
                None,
            )
            referenced = self._safe_value(lambda: parm.getReferencedParm(), None)
            reference_path = self._safe_value(
                lambda: referenced.path(), None
            )
            return reference_path == f"{expected_path}/{value['parmName']}"
        return False

    def _document_normalize_typed_receipt(
        self, value: Any,
    ) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or set(value) not in ({
                "format", "documentId", "nodeUids", "bindings",
            }, {
                "format", "documentId", "documentSchema",
                "nodeUids", "bindings",
            })
            or value.get("format") != _FORMAT
            or not isinstance(value.get("documentId"), str)
            or (
                value.get("documentSchema", self._NETWORK_DOCUMENT_SCHEMA_URI_V2)
                not in {
                    self._NETWORK_DOCUMENT_SCHEMA_URI,
                    self._NETWORK_DOCUMENT_SCHEMA_URI_V2,
                }
            )
            or not isinstance(value.get("nodeUids"), list)
            or value["nodeUids"] != sorted(set(value["nodeUids"]))
            or not isinstance(value.get("bindings"), list)
            or len(value["bindings"]) > self._MAX_DOCUMENT_TYPED_BINDINGS
        ):
            raise JsonRpcError(INVALID_PARAMS, "Typed binding receipt is malformed.")
        known = set(value["nodeUids"])
        schema = value.get(
            "documentSchema", self._NETWORK_DOCUMENT_SCHEMA_URI_V2
        )
        identities = []
        for binding in value["bindings"]:
            self._document_validate_receipt_binding(
                binding, known, schema
            )
            identities.append(binding["uid"])
        if identities != sorted(set(identities)):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Typed binding receipt identities must be uniquely sorted.",
            )
        result = copy.deepcopy(value)
        encoded = json.dumps(
            result, allow_nan=False, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > self._MAX_DOCUMENT_TYPED_BINDINGS_BYTES:
            raise JsonRpcError(
                INVALID_PARAMS, "Typed binding receipt exceeds its byte limit."
            )
        return result

    def _document_validate_receipt_binding(
        self,
        binding: Any,
        node_uids: set[str],
        document_schema: str,
    ) -> None:
        if document_schema == self._NETWORK_DOCUMENT_SCHEMA_URI:
            validate_v1_receipt_binding(binding, node_uids)
        else:
            validate_v2_binding(binding, node_uids)


def _has_parameter_selection(binding: Any) -> bool:
    if not isinstance(binding, dict):
        return False
    metadata = binding.get("metadata")
    return (
        isinstance(metadata, dict)
        and "parameterSelection" in metadata
    )
