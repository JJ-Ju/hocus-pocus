"""Durable root-network storage for interned HocusScript expansion tables."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript.document_provenance import (
    MAX_DOCUMENT_EXPANSION_BYTES,
    MAX_DOCUMENT_EXPANSION_FRAMES,
    MAX_DOCUMENT_EXPANSION_STACKS,
    DocumentProvenanceError,
    normalize_expansion_tables,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_H5_ENTITY_FIELDS = {
    "originId",
    "originKind",
    "relatedOrigins",
    "stackId",
    "controlStackId",
}


class DocumentExpansionProvenanceOperationsMixin:
    _DOCUMENT_EXPANSION_PROVENANCE_KEY = "hpmcp.hocus_expansion"
    _DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY = "hpmcp.hocus_expansion_sha256"
    _MAX_DOCUMENT_EXPANSION_PROVENANCE_BYTES = MAX_DOCUMENT_EXPANSION_BYTES
    _MAX_DOCUMENT_EXPANSION_STACKS = MAX_DOCUMENT_EXPANSION_STACKS
    _MAX_DOCUMENT_EXPANSION_FRAMES = MAX_DOCUMENT_EXPANSION_FRAMES

    def _document_normalize_expansion_provenance(
        self, value: Any,
    ) -> dict[str, Any]:
        try:
            return normalize_expansion_tables(value)
        except DocumentProvenanceError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Document expansion provenance is malformed or exceeds its structural bounds.",
            ) from exc

    def _document_expansion_stacks_valid(
        self, value: Any, identity_key: str,
    ) -> bool:
        if (
            not isinstance(value, list)
            or len(value) > self._MAX_DOCUMENT_EXPANSION_STACKS
        ):
            return False
        identities: list[str] = []
        for stack in value:
            if not isinstance(stack, dict) or set(stack) != {identity_key, "frames"}:
                return False
            identity, frames = stack.get(identity_key), stack.get("frames")
            if (
                not isinstance(identity, str)
                or _DIGEST.fullmatch(identity) is None
                or not isinstance(frames, list)
                or not 1 <= len(frames) <= self._MAX_DOCUMENT_EXPANSION_FRAMES
                or any(
                    not isinstance(frame, dict) or not frame or len(frame) > 24
                    for frame in frames
                )
            ):
                return False
            identities.append(identity)
        return identities == sorted(set(identities))

    def _document_live_expansion_provenance(
        self, root_path: str,
    ) -> dict[str, Any] | None:
        root = self._safe_value(lambda: self._require_hou().node(root_path), None)
        if root is None:
            return None
        raw = str(
            self._safe_value(
                lambda: root.userData(self._DOCUMENT_EXPANSION_PROVENANCE_KEY), ""
            )
            or ""
        )
        declared = str(
            self._safe_value(
                lambda: root.userData(
                    self._DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY
                ),
                "",
            )
            or ""
        ).strip()
        try:
            raw_bytes = raw.encode("utf-8")
        except UnicodeEncodeError:
            return None
        if (
            not raw_bytes
            or len(raw_bytes) > self._MAX_DOCUMENT_EXPANSION_PROVENANCE_BYTES
            or len(declared) != 64
            or not hmac.compare_digest(
                declared, hashlib.sha256(raw_bytes).hexdigest()
            )
        ):
            return None
        try:
            envelope = json.loads(raw)
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"version", "hocusExpansion"}
                or envelope.get("version") != 1
            ):
                return None
            return self._document_normalize_expansion_provenance(
                envelope["hocusExpansion"]
            )
        except (JsonRpcError, RecursionError, json.JSONDecodeError):
            return None

    def _document_stamp_live_expansion_provenance(
        self, root_path: str, value: Any,
    ) -> None:
        normalized = self._document_normalize_expansion_provenance(value)
        encoded = json.dumps(
            {"version": 1, "hocusExpansion": normalized},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > self._MAX_DOCUMENT_EXPANSION_PROVENANCE_BYTES:
            raise JsonRpcError(
                INVALID_PARAMS, "Document expansion provenance exceeds its bounded user-data limit."
            )
        root = self._require_node_by_path(root_path)
        root.setUserData(self._DOCUMENT_EXPANSION_PROVENANCE_KEY, encoded)
        root.setUserData(
            self._DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    def _document_clear_live_expansion_provenance(self, root_path: str) -> None:
        root = self._require_node_by_path(root_path)
        for key in (
            self._DOCUMENT_EXPANSION_PROVENANCE_KEY,
            self._DOCUMENT_EXPANSION_PROVENANCE_DIGEST_KEY,
        ):
            self._safe_value(lambda key=key: root.destroyUserData(key), None)

    def _document_plan_root_expansion_provenance(
        self, baseline: dict[str, Any], target: dict[str, Any],
    ) -> dict[str, Any] | None:
        before = self._document_expansion_from_metadata(baseline)
        after = self._document_expansion_from_metadata(target)
        if before == after:
            return None
        normalized = (
            self._document_normalize_expansion_provenance(after)
            if after is not None
            else None
        )
        return {
            "rootPath": str(target.get("rootPath", "")).strip(),
            "hocusExpansion": normalized,
        }

    @staticmethod
    def _document_expansion_from_metadata(
        document: dict[str, Any],
    ) -> Any:
        metadata = document.get("metadata")
        return metadata.get("hocusExpansion") if isinstance(metadata, dict) else None

    def _document_execute_root_expansion_provenance(
        self,
        plan: dict[str, Any],
        executed: list[dict[str, Any]],
        checkpoint: Callable[[], None],
    ) -> None:
        change = plan.get("rootProvenanceChange")
        if not isinstance(change, dict):
            return
        checkpoint()
        root_path = str(change.get("rootPath", "")).strip()
        value = change.get("hocusExpansion")
        if value is None:
            self._document_clear_live_expansion_provenance(root_path)
            action = "clear_root_expansion_provenance"
        else:
            self._document_stamp_live_expansion_provenance(root_path, value)
            action = "stamp_root_expansion_provenance"
        executed.append({"type": action, "rootPath": root_path})

    def _document_h5_entity_provenance_valid(
        self, hocus: dict[str, Any],
    ) -> bool:
        present = _H5_ENTITY_FIELDS & set(hocus)
        if not present:
            return True
        if present != _H5_ENTITY_FIELDS:
            return False
        if (
            not isinstance(hocus.get("originId"), str)
            or _DIGEST.fullmatch(hocus["originId"]) is None
            or hocus.get("originKind")
            not in {"definition", "argument", "export", "synthetic"}
        ):
            return False
        for field in ("stackId", "controlStackId"):
            value = hocus.get(field)
            if value is not None and (
                not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            ):
                return False
        related = hocus.get("relatedOrigins")
        if not isinstance(related, list) or len(related) > 16:
            return False
        return all(self._document_related_origin_valid(item) for item in related)

    def _document_related_origin_valid(self, value: Any) -> bool:
        if (
            not isinstance(value, dict)
            or set(value) != {"role", "span"}
            or not isinstance(value.get("role"), str)
            or not value["role"]
            or len(value["role"]) > 128
        ):
            return False
        span = value.get("span")
        source_uri = span.get("sourceUri") if isinstance(span, dict) else None
        return (
            isinstance(source_uri, str)
            and bool(source_uri)
            and self._document_provenance_span_valid(span, source_uri)
        )
