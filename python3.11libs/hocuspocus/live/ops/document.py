"""Document-oriented graph resources and tools built over the current graph snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from hocuspocus.core.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError

from ..context import RequestContext
from .document_apply import DocumentApplyOperationsMixin
from .document_diff import DocumentDiffOperationsMixin
from .document_editor_receipts import DocumentEditorReceiptOperationsMixin
from .document_entity_provenance import DocumentEntityProvenanceOperationsMixin
from .document_expansion_provenance import (
    DocumentExpansionProvenanceOperationsMixin,
)
from .document_metadata import DocumentMetadataOperationsMixin
from .document_snapshot import DocumentSnapshotOperationsMixin
from .document_typed_receipts import DocumentTypedReceiptOperationsMixin
from .document_validation import DocumentValidationOperationsMixin


class DocumentOperationsMixin(
    DocumentExpansionProvenanceOperationsMixin,
    DocumentEntityProvenanceOperationsMixin,
    DocumentMetadataOperationsMixin,
    DocumentTypedReceiptOperationsMixin,
    DocumentEditorReceiptOperationsMixin,
    DocumentSnapshotOperationsMixin,
    DocumentValidationOperationsMixin,
    DocumentDiffOperationsMixin,
    DocumentApplyOperationsMixin,
):
    _DOCUMENT_NODE_UID_KEY = "hpmcp.uid"
    _DOCUMENT_NODE_OWNER_KEY = "hpmcp.owner"
    _DOCUMENT_NODE_SOURCE_KEY = "hpmcp.source_uri"
    _DOCUMENT_NODE_GRAPH_KEY = "hpmcp.graph"
    _DOCUMENT_NODE_COMPILER_KEY = "hpmcp.compiler_version"
    _DOCUMENT_NODE_PROVENANCE_KEY = "hpmcp.provenance"
    _DOCUMENT_NODE_PROVENANCE_DIGEST_KEY = "hpmcp.provenance_sha256"
    _MAX_NODE_PROVENANCE_BYTES = 16 * 1024
    _NETWORK_DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/network-document/v1"
    _NETWORK_DOCUMENT_SCHEMA_URI_V2 = "hocuspocus://schemas/network-document/v2"
    _SCENE_DOCUMENT_SCHEMA_URI = "hocuspocus://schemas/scene-document/v1"
    _DOCUMENT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/network-document/v1"
    _DOCUMENT_SCHEMA_RESOURCE_URI_V2 = "houdini://documents/schema/network-document/v2"
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
    _MAX_INLINE_CHECKOUT_PAYLOAD_BYTES = 1024 * 1024

    @staticmethod
    def _canonical_checkout_json(payload: dict[str, Any]) -> bytes:
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(
                INTERNAL_ERROR,
                "The checkout document could not be represented as canonical JSON.",
            ) from exc

    def _document_checkout_delivery(
        self,
        checkout: dict[str, Any],
        *,
        additional_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checkout_id = str(checkout.get("checkoutId", ""))
        document = self._documents.working_document(checkout_id)
        if document is None:
            raise JsonRpcError(INTERNAL_ERROR, "The new document checkout is unavailable.")
        encoded_document = self._canonical_checkout_json(document)
        delivery = {
            "mode": "inline",
            "contentDigest": f"sha256:{hashlib.sha256(encoded_document).hexdigest()}",
            "byteLength": len(encoded_document),
            "inlinePayloadLimitBytes": self._MAX_INLINE_CHECKOUT_PAYLOAD_BYTES,
        }
        payload = dict(additional_payload or {})
        payload.update(checkout)
        payload["documentDelivery"] = delivery
        payload["document"] = document
        if len(self._canonical_checkout_json(payload)) <= self._MAX_INLINE_CHECKOUT_PAYLOAD_BYTES:
            return payload
        payload.pop("document")
        delivery["mode"] = "resource"
        delivery["reason"] = "document_exceeds_inline_limit"
        return payload

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
        checkout = self._documents.create_checkout(
            document_id=str(document.get("documentId")),
            document_kind=str(document.get("kind")),
            root_path=root_path,
            document=document,
        )
        return self._document_checkout_delivery(checkout)

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

    def read_document_schema_v2(self, context: RequestContext) -> dict[str, Any]:
        return self._document_resource_response(
            self._DOCUMENT_SCHEMA_RESOURCE_URI_V2,
            self._document_schema_payload(2),
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
