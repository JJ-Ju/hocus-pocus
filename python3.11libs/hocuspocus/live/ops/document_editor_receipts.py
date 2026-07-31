"""Durable identity receipts for managed network-editor entities."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from typing import Any, Callable, Mapping, Sequence

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_editor_entities import (
    DocumentEditorEntityError,
    editor_entities_from_document,
)

_FORMAT = "network-document-editor-entities-v1"


class DocumentEditorReceiptOperationsMixin:
    """Persist only the authority needed to re-identify non-node HOM items."""

    _DOCUMENT_EDITOR_ENTITIES_KEY = "hpmcp.editor_entities"
    _DOCUMENT_EDITOR_ENTITIES_DIGEST_KEY = "hpmcp.editor_entities_sha256"
    _MAX_DOCUMENT_EDITOR_ENTITIES_BYTES = 4 * 1024 * 1024

    def _document_editor_receipt_from_document(
        self,
        document: Mapping[str, Any],
        *,
        live_identities: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any] | None:
        if document.get("$schema") != self._NETWORK_DOCUMENT_SCHEMA_URI_V2:
            return None
        node_uids = {
            str(item.get("uid", "")).strip()
            for item in document.get("nodes", [])
            if isinstance(item, Mapping) and str(item.get("uid", "")).strip()
        }
        try:
            entities = editor_entities_from_document(
                document, node_uids=node_uids,
            )
        except DocumentEditorEntityError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Editor entity receipt is invalid: {exc}",
                {"diagnosticCode": "HOCUS936", **exc.details},
            ) from exc
        if not entities:
            return None
        names = {
            str(item.get("uid", "")): {
                "kind": str(item.get("kind", "")),
                "liveName": str(item.get("liveName", "")),
            }
            for item in live_identities
            if (
                isinstance(item, Mapping)
                and str(item.get("uid", ""))
                and str(item.get("kind", ""))
                and str(item.get("liveName", ""))
            )
        }
        prior = self._document_live_editor_receipt(
            str(document.get("rootPath", ""))
        )
        if not names and prior is not None:
            names = copy.deepcopy(prior["liveIdentities"])
        retained_uids = {
            item["uid"] for item in entities
            if item["kind"] != "layout_constraint"
        }
        names = {
            uid: value for uid, value in names.items()
            if uid in retained_uids
        }
        provenance = {}
        for item in entities:
            hocus = item.get("metadata", {}).get("hocus")
            if not isinstance(hocus, Mapping):
                continue
            record = copy.deepcopy(dict(hocus))
            if item["kind"] == "node_comment":
                record["nodeUid"] = item["nodeUid"]
            provenance[item["uid"]] = record
        constraints = [
            copy.deepcopy(item)
            for item in entities
            if item["kind"] == "layout_constraint"
        ]
        return self._document_normalize_editor_receipt({
            "format": _FORMAT,
            "documentId": str(document.get("documentId", "")),
            "liveIdentities": names,
            "provenance": provenance,
            "layoutConstraints": constraints,
        })

    def _document_plan_root_editor_receipt(
        self,
        baseline: Mapping[str, Any],
        target: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        before = self._document_editor_receipt_from_document(baseline)
        after = self._document_editor_receipt_from_document(target)
        if before == after:
            return None
        return {
            "rootPath": str(target.get("rootPath", "")).strip(),
            "targetDocument": copy.deepcopy(dict(target)),
        }

    def _document_execute_root_editor_receipt(
        self,
        change: Mapping[str, Any] | None,
        live_identities: Sequence[Mapping[str, Any]],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        if not isinstance(change, Mapping):
            return
        checkpoint()
        root = self._require_node_by_path(str(change["rootPath"]))
        table = self._document_editor_receipt_from_document(
            change["targetDocument"],
            live_identities=live_identities,
        )
        if table is None:
            for key in (
                self._DOCUMENT_EDITOR_ENTITIES_KEY,
                self._DOCUMENT_EDITOR_ENTITIES_DIGEST_KEY,
            ):
                self._safe_value(lambda key=key: root.destroyUserData(key), None)
            action = "clear_editor_entity_receipt"
        else:
            if table["documentId"] != f"network:{change['rootPath']}":
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Editor entity receipt documentId does not match its root.",
                )
            envelope = {"version": 1, "table": table}
            encoded = json.dumps(
                envelope,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            raw = encoded.encode("utf-8")
            if len(raw) > self._MAX_DOCUMENT_EDITOR_ENTITIES_BYTES:
                raise JsonRpcError(
                    INVALID_PARAMS, "Editor entity receipt exceeds its byte limit."
                )
            root.setUserData(self._DOCUMENT_EDITOR_ENTITIES_KEY, encoded)
            root.setUserData(
                self._DOCUMENT_EDITOR_ENTITIES_DIGEST_KEY,
                hashlib.sha256(raw).hexdigest(),
            )
            action = "stamp_editor_entity_receipt"
        executed.append({"type": action, "rootPath": change["rootPath"]})

    def _document_live_editor_receipt(
        self, root_path: str,
    ) -> dict[str, Any] | None:
        root = self._safe_value(lambda: self._require_hou().node(root_path), None)
        if root is None:
            return None
        raw = str(self._safe_value(
            lambda: root.userData(self._DOCUMENT_EDITOR_ENTITIES_KEY), ""
        ) or "")
        digest = str(self._safe_value(
            lambda: root.userData(self._DOCUMENT_EDITOR_ENTITIES_DIGEST_KEY), ""
        ) or "")
        try:
            encoded = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return None
        if (
            not encoded
            or len(encoded) > self._MAX_DOCUMENT_EDITOR_ENTITIES_BYTES
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
            table = self._document_normalize_editor_receipt(envelope["table"])
            if table["documentId"] != f"network:{root_path}":
                return None
            return table
        except (
            DocumentEditorEntityError,
            JsonRpcError,
            RecursionError,
            UnicodeEncodeError,
            json.JSONDecodeError,
        ):
            return None

    @staticmethod
    def _document_normalize_editor_receipt(value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, Mapping)
            or set(value) != {
                "format", "documentId", "liveIdentities",
                "provenance", "layoutConstraints",
            }
            or value.get("format") != _FORMAT
            or not isinstance(value.get("documentId"), str)
            or not isinstance(value.get("liveIdentities"), Mapping)
            or not isinstance(value.get("provenance"), Mapping)
            or not isinstance(value.get("layoutConstraints"), list)
        ):
            raise JsonRpcError(INVALID_PARAMS, "Editor entity receipt is malformed.")
        identities = {}
        for uid, record in value["liveIdentities"].items():
            if (
                not isinstance(uid, str)
                or not isinstance(record, Mapping)
                or set(record) != {"kind", "liveName"}
                or record.get("kind") not in {
                    "network_box", "sticky_note", "network_dot",
                }
                or not isinstance(record.get("liveName"), str)
                or not record["liveName"]
            ):
                raise JsonRpcError(
                    INVALID_PARAMS, "Editor live identity is malformed."
                )
            identities[uid] = dict(record)
        provenance = {
            str(uid): copy.deepcopy(dict(record))
            for uid, record in value["provenance"].items()
            if isinstance(uid, str) and isinstance(record, Mapping)
        }
        if len(provenance) != len(value["provenance"]):
            raise JsonRpcError(
                INVALID_PARAMS, "Editor provenance receipt is malformed."
            )
        constraints = editor_entities_from_document({
            "layoutConstraints": copy.deepcopy(value["layoutConstraints"]),
        })
        if any(item["kind"] != "layout_constraint" for item in constraints):
            raise JsonRpcError(
                INVALID_PARAMS, "Editor constraint receipt is malformed."
            )
        return {
            "format": _FORMAT,
            "documentId": value["documentId"],
            "liveIdentities": {
                uid: identities[uid] for uid in sorted(identities)
            },
            "provenance": {
                uid: provenance[uid] for uid in sorted(provenance)
            },
            "layoutConstraints": constraints,
        }
