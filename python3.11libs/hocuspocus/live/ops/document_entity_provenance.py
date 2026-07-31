"""Durable root-network storage for managed document entity provenance."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

_FORMAT = "document-entity-provenance-v0.1"
_ENTITY_KINDS = {
    "ports": "port",
    "parameterBindings": "parameter_binding",
    "codeBlobs": "code_blob",
}


class DocumentEntityProvenanceOperationsMixin:
    """Persist exact non-node Hocus provenance across a live snapshot."""

    _DOCUMENT_ENTITY_PROVENANCE_KEY = "hpmcp.hocus_entities"
    _DOCUMENT_ENTITY_PROVENANCE_DIGEST_KEY = "hpmcp.hocus_entities_sha256"
    _MAX_DOCUMENT_ENTITY_PROVENANCE_BYTES = 4 * 1024 * 1024
    _MAX_DOCUMENT_ENTITY_PROVENANCE_ENTRIES = 131_072

    def _document_entity_provenance_from_document(
        self, document: dict[str, Any],
    ) -> dict[str, Any] | None:
        entries: list[dict[str, Any]] = []
        for collection in ("ports", "edges", "parameterBindings", "codeBlobs"):
            for entity in document.get(collection, []):
                hocus = self._document_entity_hocus(entity)
                if hocus is None:
                    continue
                uid = str(entity.get("uid", "")).strip()
                expected_kind = self._document_entity_kind(collection, entity)
                self._document_require_entity_provenance(uid, hocus, expected_kind)
                entries.append({"uid": uid, "hocus": copy.deepcopy(hocus)})
        if not entries:
            return None
        entries.sort(key=lambda item: item["uid"])
        if (
            len(entries) > self._MAX_DOCUMENT_ENTITY_PROVENANCE_ENTRIES
            or len({item["uid"] for item in entries}) != len(entries)
        ):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Managed entity provenance has duplicate identities or exceeds its entry limit.",
            )
        table = {"format": _FORMAT, "entities": entries}
        self._document_require_entity_provenance_size(table)
        return table

    def _document_live_entity_provenance(
        self, root_path: str,
    ) -> dict[str, dict[str, Any]]:
        root = self._safe_value(lambda: self._require_hou().node(root_path), None)
        if root is None:
            return {}
        raw = str(
            self._safe_value(
                lambda: root.userData(self._DOCUMENT_ENTITY_PROVENANCE_KEY), ""
            )
            or ""
        )
        declared = str(
            self._safe_value(
                lambda: root.userData(
                    self._DOCUMENT_ENTITY_PROVENANCE_DIGEST_KEY
                ),
                "",
            )
            or ""
        ).strip()
        try:
            raw_bytes = raw.encode("utf-8")
        except UnicodeEncodeError:
            return {}
        if (
            not raw_bytes
            or len(raw_bytes) > self._MAX_DOCUMENT_ENTITY_PROVENANCE_BYTES
            or len(declared) != 64
            or not hmac.compare_digest(
                declared, hashlib.sha256(raw_bytes).hexdigest()
            )
        ):
            return {}
        try:
            envelope = json.loads(raw)
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"version", "table"}
                or envelope.get("version") != 1
            ):
                return {}
            table = self._document_normalize_entity_provenance(envelope["table"])
        except (JsonRpcError, RecursionError, json.JSONDecodeError):
            return {}
        return {
            item["uid"]: copy.deepcopy(item["hocus"])
            for item in table["entities"]
        }

    def _document_plan_root_entity_provenance(
        self, baseline: dict[str, Any], target: dict[str, Any],
    ) -> dict[str, Any] | None:
        before = self._document_entity_provenance_from_document(baseline)
        after = self._document_entity_provenance_from_document(target)
        if before == after:
            return None
        return {
            "rootPath": str(target.get("rootPath", "")).strip(),
            "table": after,
        }

    def _document_execute_root_entity_provenance(
        self,
        plan: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        change = plan.get("rootEntityProvenanceChange")
        if not isinstance(change, dict):
            return
        checkpoint()
        root_path = str(change.get("rootPath", "")).strip()
        table = change.get("table")
        if table is None:
            self._document_clear_live_entity_provenance(root_path)
            action = "clear_root_entity_provenance"
        else:
            self._document_stamp_live_entity_provenance(root_path, table)
            action = "stamp_root_entity_provenance"
        executed.append({"type": action, "rootPath": root_path})

    def _document_stamp_live_entity_provenance(
        self, root_path: str, value: Any,
    ) -> None:
        table = self._document_normalize_entity_provenance(value)
        encoded = json.dumps(
            {"version": 1, "table": table},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded_bytes = encoded.encode("utf-8")
        if len(encoded_bytes) > self._MAX_DOCUMENT_ENTITY_PROVENANCE_BYTES:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Managed entity provenance exceeds its bounded user-data limit.",
            )
        root = self._require_node_by_path(root_path)
        root.setUserData(self._DOCUMENT_ENTITY_PROVENANCE_KEY, encoded)
        root.setUserData(
            self._DOCUMENT_ENTITY_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(encoded_bytes).hexdigest(),
        )

    def _document_clear_live_entity_provenance(self, root_path: str) -> None:
        root = self._require_node_by_path(root_path)
        for key in (
            self._DOCUMENT_ENTITY_PROVENANCE_KEY,
            self._DOCUMENT_ENTITY_PROVENANCE_DIGEST_KEY,
        ):
            self._safe_value(lambda key=key: root.destroyUserData(key), None)

    def _document_normalize_entity_provenance(
        self, value: Any,
    ) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "entities"}
            or value.get("format") != _FORMAT
            or not isinstance(value.get("entities"), list)
            or len(value["entities"]) > self._MAX_DOCUMENT_ENTITY_PROVENANCE_ENTRIES
        ):
            raise JsonRpcError(INVALID_PARAMS, "Managed entity provenance is malformed.")
        normalized: list[dict[str, Any]] = []
        identities: list[str] = []
        for item in value["entities"]:
            if not isinstance(item, dict) or set(item) != {"uid", "hocus"}:
                raise JsonRpcError(INVALID_PARAMS, "Managed entity provenance is malformed.")
            uid, hocus = item["uid"], item["hocus"]
            expected_kind = hocus.get("entityKind") if isinstance(hocus, dict) else None
            self._document_require_entity_provenance(uid, hocus, expected_kind)
            identities.append(uid)
            normalized.append(copy.deepcopy(item))
        if identities != sorted(set(identities)):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Managed entity provenance identities must be uniquely sorted.",
            )
        table = {"format": _FORMAT, "entities": normalized}
        self._document_require_entity_provenance_size(table)
        return table

    def _document_require_entity_provenance(
        self, uid: Any, hocus: Any, expected_kind: Any,
    ) -> None:
        allowed_kinds = {"port", "edge", "output_flag", "parameter_binding", "code_blob"}
        if (
            not isinstance(uid, str)
            or not uid
            or not isinstance(hocus, dict)
            or expected_kind not in allowed_kinds
            or hocus.get("entityKind") != expected_kind
            or hocus.get("managedFields") is not None
            or not self._document_provenance_valid(
                {"version": 1, "uid": uid, "hocus": hocus},
                hocus,
                uid,
            )
        ):
            raise JsonRpcError(INVALID_PARAMS, "Managed entity provenance is malformed.")

    def _document_require_entity_provenance_size(
        self, table: dict[str, Any],
    ) -> None:
        try:
            encoded = json.dumps(
                table,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
            raise JsonRpcError(
                INVALID_PARAMS, "Managed entity provenance is not canonical JSON."
            ) from exc
        if len(encoded) > self._MAX_DOCUMENT_ENTITY_PROVENANCE_BYTES:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Managed entity provenance exceeds its bounded user-data limit.",
            )

    @staticmethod
    def _document_entity_hocus(entity: Any) -> dict[str, Any] | None:
        metadata = entity.get("metadata") if isinstance(entity, dict) else None
        hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
        return hocus if isinstance(hocus, dict) else None

    @staticmethod
    def _document_entity_kind(
        collection: str, entity: dict[str, Any],
    ) -> str:
        if collection == "edges":
            return "output_flag" if entity.get("kind") == "output_flag" else "edge"
        return _ENTITY_KINDS[collection]
