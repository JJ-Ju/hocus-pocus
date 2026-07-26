"""Preview-only MCP operations for HocusScript source."""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
import time
from typing import Any
from uuid import uuid4

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import require_capabilities
from hocuspocus.hocusscript import (
    BUNDLE_VERSION,
    BundleValidationError,
    CatalogConstraint,
    DocumentLoweringError,
    ExternalNodeBinding,
    compile_source,
    complete_source,
    decode_compiled_bundle,
    export_network_document,
    format_source as editor_format_source,
    graph_spec_from_dict,
    lower_bundle_to_document,
    resolve_graph,
)
from hocuspocus.hocusscript.compiler import MAX_SOURCE_BYTES

from ..catalog_provider import LiveHoudiniCatalogProvider
from ..document_service import ApplyPlanError, PreviewArtifactError
from ..graph_store import GraphStorePlanError

from ..context import RequestContext
from .hocusscript_apply import HocusScriptApplyOperationsMixin
from .hocusscript_resources import HocusScriptResourceOperationsMixin


class HocusScriptOperationsMixin(HocusScriptApplyOperationsMixin, HocusScriptResourceOperationsMixin):
    _GRAPH_SPEC_SCHEMA_RESOURCE_URI = "houdini://documents/schema/graph-spec/v0.2"
    _MODULE_GRAPH_SPEC_SCHEMA_RESOURCE_URI = "houdini://documents/schema/graph-spec/v0.3"
    _EXPANSION_MAP_SCHEMA_RESOURCE_URI = "houdini://documents/schema/expansion-map/v1"
    _RESOLVED_MODULE_SET_SCHEMA_RESOURCE_URI = "houdini://documents/schema/resolved-module-set/v1"
    _LEGACY_GRAPH_SPEC_SCHEMA_RESOURCE_URI = "houdini://documents/schema/graph-spec/v0.1"
    _FORMAT_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/format-source-output/v1"
    _COMPLETE_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/complete-source-output/v1"
    _EXPORT_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/export-source-output/v1"
    _PREVIEW_INPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/preview-bundle-input/v1"
    _PREVIEW_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/preview-bundle-output/v1"
    _PLAN_INPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/plan-bundle-input/v1"
    _PLAN_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/plan-bundle-output/v1"
    _APPLY_PLAN_SCHEMA_RESOURCE_URI = "houdini://documents/schema/apply-plan/v1"
    _APPLY_INPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/apply-plan-input/v1"
    _MAX_INLINE_PREVIEW_BYTES = 128 * 1024
    _APPLY_PLAN_VERSION = "1.0"
    _APPLY_ERROR = -32040

    @staticmethod
    def _validate_editor_source_bytes(source: str) -> None:
        try:
            byte_length = len(source.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise JsonRpcError(
                INVALID_PARAMS, "source must contain only valid Unicode scalar values."
            ) from exc
        if byte_length > MAX_SOURCE_BYTES:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"source must not exceed {MAX_SOURCE_BYTES} UTF-8 bytes.",
            )

    def document_compile_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        del context
        source = arguments.get("source")
        source_name = arguments.get("source_name", "<mcp-source>")
        strict = arguments.get("strict", True)
        if not isinstance(source, str):
            raise JsonRpcError(INVALID_PARAMS, "source must be a string.")
        if not isinstance(source_name, str) or not source_name.strip():
            raise JsonRpcError(INVALID_PARAMS, "source_name must be a non-empty string when provided.")
        if len(source_name) > 1024:
            raise JsonRpcError(INVALID_PARAMS, "source_name must not exceed 1024 characters.")
        if not isinstance(strict, bool):
            raise JsonRpcError(INVALID_PARAMS, "strict must be a boolean when provided.")
        result = compile_source(source, source_name.strip(), strict=strict).to_dict()
        if result["valid"]:
            summary = "Compiled HocusScript through the structural preview stage without mutating Houdini."
        else:
            summary = f"HocusScript structural compilation reported {result['diagnosticCount']} diagnostic(s)."
        return self._tool_response(summary, result)

    def document_format_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        del context
        source = arguments.get("source")
        source_name = arguments.get("source_name", "<mcp-source>")
        strict = arguments.get("strict", True)
        if not isinstance(source, str):
            raise JsonRpcError(INVALID_PARAMS, "source must be a string.")
        self._validate_editor_source_bytes(source)
        if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 1024:
            raise JsonRpcError(INVALID_PARAMS, "source_name must be a non-empty string of at most 1024 characters.")
        if not isinstance(strict, bool):
            raise JsonRpcError(INVALID_PARAMS, "strict must be a boolean when provided.")
        try:
            result = editor_format_source(source, source_name.strip(), strict=strict).to_dict()
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(INVALID_PARAMS, str(exc)) from exc
        summary = (
            "Formatted valid HocusScript source without filesystem or Houdini mutation."
            if result["valid"]
            else f"HocusScript formatting blocked on {result['diagnosticCount']} diagnostic(s)."
        )
        return self._tool_response(summary, result)

    def document_complete_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        del context
        source = arguments.get("source")
        offset = arguments.get("offset")
        source_name = arguments.get("source_name", "<mcp-source>")
        limit = arguments.get("limit", 100)
        if not isinstance(source, str):
            raise JsonRpcError(INVALID_PARAMS, "source must be a string.")
        self._validate_editor_source_bytes(source)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= len(source):
            raise JsonRpcError(INVALID_PARAMS, "offset must be a Python/Unicode source offset within source.")
        if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 1024:
            raise JsonRpcError(INVALID_PARAMS, "source_name must be a non-empty string of at most 1024 characters.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise JsonRpcError(INVALID_PARAMS, "limit must be an integer between 1 and 200.")
        catalog = self._document_preview_live_catalog()
        try:
            result = complete_source(
                source,
                offset,
                catalog,
                source_name=source_name.strip(),
                limit=limit,
            ).to_dict()
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(INVALID_PARAMS, str(exc)) from exc
        return self._tool_response(
            f"Returned {len(result['items'])} deterministic catalog-backed completion item(s).",
            result,
        )

    def document_export_source(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        root_path = arguments.get("root_path")
        graph_name = arguments.get("graph_name")
        if not isinstance(root_path, str) or not root_path.startswith("/"):
            raise JsonRpcError(INVALID_PARAMS, "root_path must be an absolute Houdini node path.")
        if graph_name is not None and (not isinstance(graph_name, str) or not graph_name.strip()):
            raise JsonRpcError(INVALID_PARAMS, "graph_name must be a non-empty identifier when provided.")

        def export() -> dict[str, Any]:
            document = self._document_current_network_payload(root_path, force_sync=True)
            catalog = self._document_preview_live_catalog()
            return export_network_document(
                document,
                graph_name=graph_name.strip() if isinstance(graph_name, str) else None,
                catalog=catalog,
            ).to_dict()

        result = self._call_live(export, context)
        summary = (
            "Exported a complete, exact-catalog HocusScript source handoff without writing project files."
            if result["valid"]
            else f"HocusScript export blocked on {len(result['diagnostics'])} unsupported or unsafe construct(s)."
        )
        return self._tool_response(summary, result)

    def _document_preview_live_catalog(self):
        return LiveHoudiniCatalogProvider(self._require_hou()).get_catalog()

    @staticmethod
    def _preview_diagnostic(code: str, message: str, **details: Any) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {"severity": "error", "code": code, "message": message}
        if details:
            diagnostic["details"] = details
        return diagnostic

    @staticmethod
    def _document_preview_semantics_match(
        bundled: dict[str, Any],
        live: dict[str, Any],
    ) -> bool:
        if bundled.get("readyForDocumentLowering"):
            return bundled == live
        deferred = bundled.get("deferredChecks")
        if not isinstance(deferred, list) or not deferred or any(
            item.get("kind") != "external_output" for item in deferred if isinstance(item, dict)
        ):
            return False
        diagnostics = bundled.get("diagnostics")
        if not isinstance(diagnostics, list) or any(item.get("code") != "HOCUS643" for item in diagnostics):
            return False
        for key in (
            "catalogFingerprint",
            "operatorSelections",
            "parameterSelections",
            "requiredCapabilities",
        ):
            if bundled.get(key) != live.get(key):
                return False
        bundled_connections = bundled.get("connectionSelections", [])
        live_connections = live.get("connectionSelections", [])
        if any(item not in live_connections for item in bundled_connections):
            return False
        return bool(
            live.get("valid")
            and live.get("readyForDocumentLowering")
            and not live.get("deferredChecks")
            and not live.get("diagnostics")
        )

    def _document_preview_bundle_impl(self, bundle_value: dict[str, Any]) -> dict[str, Any]:
        bundle = self._document_decode_preview_bundle(bundle_value)
        payload = bundle.payload
        target = payload["graphSpec"]["target"]
        baseline = self._document_current_network_payload(target)
        baseline_diagnostics = self._document_validate_network_document(baseline)
        baseline_blocking = [item for item in baseline_diagnostics if item.get("severity") == "error"]
        if baseline_blocking:
            return {
                "stage": "document_preview",
                "previewVersion": "0.1",
                "valid": False,
                "readyForPlan": False,
                "readyForApply": False,
                "bundleDigest": bundle.digest,
                "target": target,
                "diagnostics": baseline_blocking,
                "diagnosticCount": len(baseline_blocking),
                "artifact": None,
            }

        live_catalog = self._document_preview_live_catalog()
        expected_fingerprint = payload["catalogConstraints"]["fingerprint"]
        if live_catalog.fingerprint != expected_fingerprint:
            diagnostic = self._preview_diagnostic(
                "HOCUS720",
                "The live Houdini catalog does not match the bundle catalog pin.",
                expectedFingerprint=expected_fingerprint,
                liveFingerprint=live_catalog.fingerprint,
            )
            return {
                "stage": "document_preview",
                "previewVersion": "0.1",
                "valid": False,
                "readyForPlan": False,
                "readyForApply": False,
                "bundleDigest": bundle.digest,
                "target": target,
                "catalogResolution": {
                    "matched": False,
                    "expectedFingerprint": expected_fingerprint,
                    "liveFingerprint": live_catalog.fingerprint,
                },
                "diagnostics": [diagnostic],
                "diagnosticCount": 1,
                "artifact": None,
            }

        graph = graph_spec_from_dict(payload["graphSpec"])
        baseline_nodes_by_path = {
            str(node.get("path", "")): node
            for node in baseline.get("nodes", [])
            if isinstance(node, dict) and str(node.get("path", ""))
        }
        external_bindings: dict[str, ExternalNodeBinding] = {}
        for external in graph.external_nodes:
            live_node = baseline_nodes_by_path.get(external.path)
            if live_node is None:
                continue
            qualified_name = str(live_node.get("typeName", "")).strip()
            if qualified_name:
                external_bindings[external.symbol] = ExternalNodeBinding(
                    qualified_name,
                    live_catalog.fingerprint,
                    str(live_node.get("category", "")).strip() or None,
                )
        live_semantic_result = resolve_graph(
            graph,
            live_catalog,
            constraint=CatalogConstraint(expected_fingerprint),
            external_bindings=external_bindings,
        )
        live_semantic = live_semantic_result.to_dict()
        if not self._document_preview_semantics_match(payload["semanticResolution"], live_semantic):
            diagnostic = self._preview_diagnostic(
                "HOCUS722",
                "Bundle semantic selections do not match fresh resolution against the live catalog.",
                liveSemanticResolution=live_semantic,
            )
            return {
                "stage": "document_preview",
                "previewVersion": "0.1",
                "valid": False,
                "readyForPlan": False,
                "readyForApply": False,
                "bundleDigest": bundle.digest,
                "target": target,
                "catalogResolution": {
                    "matched": True,
                    "expectedFingerprint": expected_fingerprint,
                    "liveFingerprint": live_catalog.fingerprint,
                },
                "diagnostics": [diagnostic],
                "diagnosticCount": 1,
                "artifact": None,
            }

        try:
            preview = lower_bundle_to_document(
                bundle,
                baseline,
                _trusted_semantic_result=live_semantic_result,
            )
        except DocumentLoweringError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                exc.message,
                {"diagnosticCode": exc.code, **exc.details},
            ) from exc
        artifact = preview.to_dict()
        diagnostics = list(artifact["diagnostics"])
        runtime_diagnostics = self._document_validate_network_document(artifact["document"])
        known = {(item.get("code"), item.get("jsonPointer"), item.get("message")) for item in diagnostics}
        diagnostics.extend(
            item for item in runtime_diagnostics
            if (item.get("code"), item.get("jsonPointer"), item.get("message")) not in known
        )
        diagnostics = self._document_clean_diagnostics(diagnostics)
        blocking = any(item.get("severity") == "error" for item in diagnostics)
        artifact["diagnostics"] = diagnostics
        artifact["valid"] = not blocking
        if blocking:
            artifact["candidatePlan"] = None
        artifact["catalogResolution"] = {
            "matched": True,
            "expectedFingerprint": expected_fingerprint,
            "liveFingerprint": live_catalog.fingerprint,
        }
        encoded = json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        try:
            artifact_ref = self._documents.store_preview_artifact(artifact)
        except PreviewArtifactError as exc:
            diagnostic = self._preview_diagnostic("HOCUS723", str(exc), byteLength=len(encoded))
            return {
                "stage": "document_preview",
                "previewVersion": artifact["previewVersion"],
                "valid": False,
                "readyForPlan": False,
                "readyForApply": False,
                "bundleDigest": bundle.digest,
                "target": target,
                "catalogResolution": artifact["catalogResolution"],
                "diagnostics": [diagnostic],
                "diagnosticCount": 1,
                "artifact": None,
            }
        response = {
            "stage": "document_preview",
            "previewVersion": artifact["previewVersion"],
            "valid": artifact["valid"],
            "readyForPlan": artifact["valid"] and artifact["candidatePlan"] is not None,
            "readyForApply": False,
            "bundleDigest": bundle.digest,
            "target": target,
            "catalogResolution": artifact["catalogResolution"],
            "baseline": {
                "documentId": baseline["documentId"],
                "documentRevision": baseline["documentRevision"],
                "liveRevision": baseline.get("lastSyncedLiveRevision", baseline.get("baselineLiveRevision", 0)),
            },
            "summary": {
                "diff": artifact["diff"]["summary"],
                "destructive": artifact["destructiveSummary"],
                "operationCount": len((artifact.get("candidatePlan") or {}).get("operations", [])),
            },
            "diagnostics": diagnostics,
            "diagnosticCount": len(diagnostics),
            "artifact": {**artifact_ref, "inline": len(encoded) <= self._MAX_INLINE_PREVIEW_BYTES},
        }
        if len(encoded) <= self._MAX_INLINE_PREVIEW_BYTES:
            response["preview"] = artifact
        return response

    @staticmethod
    def _document_decode_preview_bundle(bundle_value: dict[str, Any]):
        try:
            bundle = decode_compiled_bundle(bundle_value)
        except BundleValidationError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                exc.message,
                {"diagnosticCode": exc.code, **exc.details},
            ) from exc
        payload = bundle.payload
        if payload.get("bundleVersion") != BUNDLE_VERSION or "semanticResolution" not in payload:
            raise JsonRpcError(
                INVALID_PARAMS,
                "document.preview_bundle requires a resolved compiled bundle v0.2.",
                {"diagnosticCode": "HOCUS700"},
            )
        return bundle

    def document_preview_bundle(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        bundle = arguments.get("bundle")
        if not isinstance(bundle, dict):
            raise JsonRpcError(INVALID_PARAMS, "bundle must be a compiled-bundle JSON object.")
        data = self._call_live(lambda: self._document_preview_bundle_impl(bundle), context)
        if not data["valid"]:
            return self._tool_response(
                f"Bundle preview blocked by {data['diagnosticCount']} diagnostic(s) without mutating Houdini.",
                data,
            )
        return self._tool_response(
            "Lowered the compiled bundle against the live baseline without mutating Houdini.",
            data,
        )

    @staticmethod
    def _hocus_canonical_digest(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _hocus_session_id(self) -> str:
        signature: tuple[Any, ...] = ("process",)
        try:
            hou_module = self._require_hou()
            hip_file = getattr(hou_module, "hipFile", None)
            root = hou_module.node("/") if callable(getattr(hou_module, "node", None)) else None
            signature = (
                str(hip_file.path()) if hip_file is not None else "",
                int(root.sessionId()) if root is not None else None,
            )
        except Exception:
            pass
        value = getattr(self, "_hocus_apply_session_id", None)
        if not isinstance(value, str) or getattr(self, "_hocus_apply_session_signature", None) != signature:
            value = str(uuid4())
            self._hocus_apply_session_id = value
            self._hocus_apply_session_signature = signature
        return value

    def _hocus_policy_fingerprint(self) -> str:
        return self._hocus_canonical_digest(self._settings.effective_policy_payload())

    @classmethod
    def _hocus_fail(
        cls,
        code: str,
        message: str,
        *,
        family: str = "validation",
        retryable: bool = False,
        **details: Any,
    ) -> None:
        raise JsonRpcError(
            cls._APPLY_ERROR,
            message,
            {"diagnosticCode": code, **details},
            family=family,
            retryable=retryable,
        )

    def _hocus_service_call(self, callback):
        try:
            return callback()
        except ApplyPlanError as exc:
            self._hocus_fail(exc.code, str(exc), family="conflict" if exc.code in {"HOCUS736", "HOCUS739"} else "validation")

    def _hocus_store_call(self, callback):
        try:
            return callback()
        except GraphStorePlanError as exc:
            self._hocus_fail("HOCUS759", str(exc), family="conflict")

    @staticmethod
    def _hocus_confirmation_required(
        candidate: dict[str, Any], execution_plan: dict[str, Any]
    ) -> bool:
        destructive_actions = {
            "adopt_node", "delete_node", "replace_node", "install_code",
            "disconnect", "clear_output",
        }
        return bool(
            any(item.get("action") in destructive_actions for item in candidate.get("operations", []))
            or execution_plan.get("codeBlobInstalls")
            or execution_plan.get("replaceNodes")
            or execution_plan.get("deleteNodes")
        )

    def _hocus_validate_reversible_plan(
        self,
        candidate: dict[str, Any],
        execution_plan: dict[str, Any],
    ) -> None:
        allowed_actions = {
            "adopt_node", "update_node_provenance", "create_node", "replace_node",
            "rename_node", "reparent_node", "update_node", "delete_node", "create_port",
            "delete_port", "set_binding", "remove_binding", "install_code", "remove_code", "connect", "disconnect",
            "set_output", "clear_output",
        }
        operations = candidate.get("operations")
        if not isinstance(operations, list):
            self._hocus_fail("HOCUS740", "Candidate plan operations are absent or invalid.")
        operation_ids: set[str] = set()
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                self._hocus_fail("HOCUS740", "Candidate plan contains a non-object operation.")
            operation_id = operation.get("operationId")
            if operation_id in operation_ids or operation.get("sequence") != index:
                self._hocus_fail("HOCUS740", "Candidate plan operation identity or sequence is invalid.")
            operation_ids.add(operation_id)
            if operation.get("action") not in allowed_actions:
                self._hocus_fail(
                    "HOCUS741", "Candidate plan contains an unsupported or irreversible action.",
                    action=operation.get("action"), operationId=operation_id,
                )
        if execution_plan.get("networkFamily") != "sop":
            self._hocus_fail(
                "HOCUS741", "HS4 guarded apply currently supports only SOP network documents.",
                networkFamily=execution_plan.get("networkFamily"),
            )
        if execution_plan.get("protectedDeleteNodes"):
            self._hocus_fail(
                "HOCUS742", "The normalized plan would delete state outside its ownership namespace.",
                protectedNodes=execution_plan["protectedDeleteNodes"],
            )
        output_guard = execution_plan.get("outputGuard")
        if isinstance(output_guard, dict):
            output_uid = output_guard.get("sourceUid")
            display_uids = output_guard.get("targetDisplayUids") or []
            if (output_uid is not None and output_uid not in display_uids) or (
                output_uid is None and display_uids
            ):
                self._hocus_fail(
                    "HOCUS761",
                    "SOP output must match the safely executable display-node selection.",
                    outputNodeUid=output_uid,
                    displayNodeUids=display_uids,
                )
        opaque = [
            item for item in (*execution_plan.get("replaceNodes", []), *execution_plan.get("deleteNodes", []))
            if bool((item.get("target") or {}).get("isNetwork", False))
        ]
        opaque.extend(
            operation
            for operation in operations
            if operation.get("action") in {"delete_node", "replace_node"}
            and bool(
                (
                    (operation.get("change") or {}).get("before")
                    if isinstance((operation.get("change") or {}).get("before"), dict)
                    else operation.get("change")
                ).get("isNetwork", False)
            )
        )
        if opaque:
            self._hocus_fail(
                "HOCUS743", "Opaque network-container replacement/deletion is not reversibly supported.",
                operationCount=len(opaque),
            )

    @staticmethod
    def _document_plan_bundle_input(
        arguments: dict[str, Any],
    ):
        bundle_value = arguments.get("bundle")
        if not isinstance(bundle_value, dict):
            raise JsonRpcError(INVALID_PARAMS, "bundle must be a compiled-bundle JSON object.")
        ttl_seconds = arguments.get("ttlSeconds", 900)
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or not 30 <= ttl_seconds <= 1800
        ):
            raise JsonRpcError(
                INVALID_PARAMS, "ttlSeconds must be an integer from 30 through 1800."
            )
        try:
            decoded = decode_compiled_bundle(bundle_value)
        except BundleValidationError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                exc.message,
                {"diagnosticCode": exc.code, **exc.details},
            ) from exc
        return bundle_value, ttl_seconds, decoded

    def _document_plan_bundle_impl(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        bundle_value, ttl_seconds, decoded = self._document_plan_bundle_input(arguments)
        payload = decoded.payload
        preview_response = self._document_preview_bundle_impl(bundle_value)
        if not preview_response.get("valid") or not preview_response.get("readyForPlan"):
            self._hocus_fail(
                "HOCUS744", "Bundle cannot produce an immutable apply plan.",
                diagnostics=preview_response.get("diagnostics", []),
            )
        preview = preview_response.get("preview")
        if not isinstance(preview, dict):
            artifact = preview_response.get("artifact") or {}
            preview = self._documents.preview_artifact(str(artifact.get("previewId", "")))
        if not isinstance(preview, dict):
            self._hocus_fail("HOCUS744", "The verified preview artifact is unavailable.")
        candidate = preview.get("candidatePlan")
        target_document = preview.get("document")
        if not isinstance(candidate, dict) or not isinstance(target_document, dict):
            self._hocus_fail("HOCUS744", "The preview has no complete candidate plan and target document.")
        root_path = str(target_document.get("rootPath", "")).strip()
        baseline = self._document_current_network_payload(root_path, force_sync=True)
        if self._hocus_canonical_digest(baseline) != candidate.get("baselineDigest"):
            self._hocus_fail(
                "HOCUS745", "The live network changed between preview and plan persistence.",
                expectedBaselineDigest=candidate.get("baselineDigest"),
                currentBaselineDigest=self._hocus_canonical_digest(baseline),
            )
        required = tuple(payload["requiredCapabilities"])
        require_capabilities(context.permissions, required)
        execution_plan = self._document_build_apply_plan(
            baseline, target_document, mode=str(candidate.get("mode", "merge"))
        )
        self._hocus_validate_reversible_plan(candidate, execution_plan)
        rollback_owner = f"hocus.rollback.{uuid4()}"
        inverse_source = copy.deepcopy(target_document)
        created_uids = {
            item.get("uid") for item in preview.get("diff", {}).get("createdNodes", [])
            if isinstance(item, dict)
        }
        for node in inverse_source.get("nodes", []):
            if node.get("uid") in created_uids:
                metadata = node.setdefault("metadata", {})
                metadata.setdefault("hocus", {})["ownership"] = rollback_owner
        inverse_target = copy.deepcopy(baseline)
        inverse_target.setdefault("metadata", {})["reconcileOwnership"] = rollback_owner
        inverse_plan = self._document_build_apply_plan(inverse_source, inverse_target, mode="reconcile")
        confirmation_required = self._hocus_confirmation_required(candidate, execution_plan)
        confirmation_token = secrets.token_urlsafe(32) if confirmation_required else ""
        now = time.time()
        plan = {
            "kind": "hocus_apply_plan",
            "planVersion": self._APPLY_PLAN_VERSION,
            "planId": str(uuid4()),
            "sessionId": self._hocus_session_id(),
            "createdAt": now,
            "expiresAt": now + ttl_seconds,
            "bundleDigest": decoded.digest,
            "sourceDigest": payload["entrySource"]["digest"],
            "compilerVersion": payload["compilerVersion"],
            "graphSpecVersion": payload["graphSpecVersion"],
            "projectUid": payload["projectUid"],
            "projectManifestDigest": payload["projectManifestDigest"],
            "projectLockDigest": payload["projectLockDigest"],
            "catalogFingerprint": payload["catalogConstraints"]["fingerprint"],
            "catalogContentDigest": payload["catalogConstraints"]["contentDigest"],
            "policyFingerprint": self._hocus_policy_fingerprint(),
            "requiredCapabilities": list(required),
            "ownership": candidate.get("ownership"),
            "mode": candidate.get("mode"),
            "rootPath": root_path,
            "baseline": {
                "documentId": baseline["documentId"],
                "documentRevision": baseline["documentRevision"],
                "liveRevision": int(baseline.get("lastSyncedLiveRevision", baseline.get("baselineLiveRevision", 0))),
                "digest": self._hocus_canonical_digest(baseline),
                "document": baseline,
            },
            "targetDocument": target_document,
            "executionPlan": execution_plan,
            "inversePlan": inverse_plan,
            "candidatePlanHash": candidate["planHash"],
            "confirmationRequired": confirmation_required,
            "confirmationTokenDigest": self._hocus_canonical_digest(confirmation_token),
        }
        plan["planHash"] = self._hocus_canonical_digest(plan)
        stored = self._hocus_service_call(
            lambda: self._documents.store_apply_plan(plan, ttl_seconds=ttl_seconds)
        )
        try:
            self._graph_store.store_immutable_plan(payload=plan)
        except GraphStorePlanError as exc:
            self._documents.discard_apply_plan(plan["planId"], expected_hash=plan["planHash"])
            self._hocus_fail("HOCUS759", f"Could not durably persist the immutable plan: {exc}")
        response = {
            "stage": "document_plan",
            "planVersion": self._APPLY_PLAN_VERSION,
            "readyForApply": True,
            "planId": stored["planId"],
            "planHash": stored["planHash"],
            "expiresAt": stored["expiresAt"],
            "resourceUri": stored["resourceUri"],
            "confirmationRequired": confirmation_required,
            "baseline": {
                "documentRevision": baseline["documentRevision"],
                "liveRevision": int(baseline.get("lastSyncedLiveRevision", baseline.get("baselineLiveRevision", 0))),
            },
            "summary": {
                "rootPath": root_path,
                "operationCount": len(candidate["operations"]),
                "destructive": preview.get("destructiveSummary", {}),
                "requiredCapabilities": list(required),
            },
        }
        if confirmation_required:
            response["confirmationToken"] = confirmation_token
        return response

    def document_plan_bundle(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._document_plan_bundle_impl(arguments, context), context)
        return self._tool_response("Persisted an immutable guarded HocusScript apply plan.", data)

    def document_discard_plan(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        del context
        plan_id = arguments.get("planId")
        plan_hash = arguments.get("planHash")
        if not isinstance(plan_id, str) or not isinstance(plan_hash, str):
            raise JsonRpcError(INVALID_PARAMS, "planId and planHash are required strings.")
        discarded = self._hocus_service_call(
            lambda: self._documents.discard_apply_plan(plan_id, expected_hash=plan_hash)
        )
        durable_record = self._hocus_store_call(lambda: self._graph_store.load_immutable_plan(plan_id))
        durable_revoked = False
        if isinstance(durable_record, dict):
            durable_plan = durable_record["payload"]
            if durable_plan.get("planHash") != plan_hash:
                self._hocus_fail("HOCUS731", "Requested plan hash does not match the durable plan.")
            revoke_commit_id = str(uuid4())
            try:
                self._graph_store.begin_plan_commit(
                    plan_commit_id=revoke_commit_id,
                    plan_id=plan_id,
                    plan_hash=plan_hash,
                    session_id=durable_plan["sessionId"],
                    idempotency_key=f"discard:{plan_id}",
                    pre_apply_snapshot=durable_plan["baseline"]["document"],
                    inverse_plan=durable_plan["inversePlan"],
                )
                self._graph_store.finish_plan_commit(
                    plan_commit_id=revoke_commit_id,
                    state="aborted",
                    result={"discarded": True, "planId": plan_id, "planHash": plan_hash},
                    error=None,
                )
                durable_revoked = True
            except GraphStorePlanError as exc:
                existing = self._graph_store.load_plan_commit(idempotency_key=f"discard:{plan_id}")
                if existing is None or existing.get("state") != "aborted":
                    self._hocus_fail("HOCUS759", f"Could not durably revoke the plan: {exc}", family="conflict")
                durable_revoked = True
        return self._tool_response(
            "Discarded the immutable apply plan." if (discarded or durable_revoked) else "The apply plan was already absent.",
            {"planId": plan_id, "planHash": plan_hash, "discarded": bool(discarded or durable_revoked), "durableRevocation": durable_revoked},
        )

    def document_apply_quarantines(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        del arguments, context
        quarantines = [
            {"scope": scope, **copy.deepcopy(details)}
            for scope, details in sorted(self._hocus_quarantine_map().items())
        ]
        return self._tool_response(
            f"Found {len(quarantines)} quarantined apply scope(s).",
            {"quarantines": quarantines, "count": len(quarantines)},
        )

    def document_recover_scope(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        scope = arguments.get("rootPath")
        if not isinstance(scope, str) or not scope.startswith("/"):
            raise JsonRpcError(INVALID_PARAMS, "rootPath must be an absolute Houdini network path.")
        with self._hocus_service_call(
            lambda: self._documents.scope_write_lease(scope, holder_id=context.operation_id)
        ):
            document = self._document_current_network_payload(scope, force_sync=True)
            diagnostics = self._document_validate_network_document(document)
            blocking = [item for item in diagnostics if item.get("severity") == "error"]
            if blocking:
                self._hocus_fail(
                    "HOCUS757", "Scope recovery could not prove a valid network document.",
                    diagnostics=blocking,
                )
            recovered_commits: list[dict[str, Any]] = []
            unresolved: list[dict[str, Any]] = []
            for commit in self._graph_store.recoverable_plan_commits():
                stored = self._graph_store.load_immutable_plan(commit["plan_id"])
                plan = stored.get("payload") if isinstance(stored, dict) else None
                if not isinstance(plan, dict) or not self._hocus_scopes_overlap(scope, str(plan.get("rootPath", "/"))):
                    continue
                baseline_match = self._hocus_canonical_digest(document) == plan["baseline"]["digest"]
                target_verification = self._document_verification_diff_payload(plan["targetDocument"], document)
                target_match = self._document_diff_is_clean(target_verification)
                if not baseline_match and not target_match:
                    unresolved.append({"planId": commit["plan_id"], "state": commit["state"]})
                    continue
                resolved_state = "committed" if target_match and not baseline_match else "aborted"
                recovery_result = {
                    "stage": "document_apply_recovery",
                    "planId": commit["plan_id"],
                    "applyCommitId": commit["plan_commit_id"],
                    "state": resolved_state,
                    "recovered": True,
                    "rootPath": plan["rootPath"],
                    "classification": "target" if resolved_state == "committed" else "baseline",
                }
                if commit["state"] == "pending":
                    self._graph_store.finish_plan_commit(
                        plan_commit_id=commit["plan_commit_id"],
                        state=resolved_state,
                        result=recovery_result,
                        error=None,
                    )
                else:
                    self._graph_store.resolve_plan_commit_recovery(
                        plan_commit_id=commit["plan_commit_id"],
                        state=resolved_state,
                        result=recovery_result,
                    )
                recovered_commits.append(recovery_result)
            if unresolved:
                self._hocus_fail(
                    "HOCUS757", "Scope state matches neither the stored baseline nor target; quarantine remains.",
                    family="conflict", unresolvedCommits=unresolved,
                )
            removed = [
                key for key in list(self._hocus_quarantine_map())
                if self._hocus_scopes_overlap(scope, key)
            ]
            for key in removed:
                self._hocus_quarantine_map().pop(key, None)
        return self._tool_response(
            "Reimported and released the validated quarantined scope.",
            {"rootPath": scope, "releasedScopes": removed, "recoveredCommits": recovered_commits, "document": document},
        )
