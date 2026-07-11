"""Preview-only MCP operations for HocusScript source."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.hocusscript import (
    BUNDLE_VERSION,
    BundleValidationError,
    CatalogConstraint,
    DocumentLoweringError,
    ExternalNodeBinding,
    compile_source,
    decode_compiled_bundle,
    graph_spec_from_dict,
    lower_bundle_to_document,
    resolve_graph,
)

from ..catalog_provider import LiveHoudiniCatalogProvider
from ..document_service import PreviewArtifactError

from ..context import RequestContext


class HocusScriptOperationsMixin:
    _GRAPH_SPEC_SCHEMA_RESOURCE_URI = "houdini://documents/schema/graph-spec/v0.1"
    _PREVIEW_INPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/preview-bundle-input/v1"
    _PREVIEW_OUTPUT_SCHEMA_RESOURCE_URI = "houdini://documents/schema/preview-bundle-output/v1"
    _MAX_INLINE_PREVIEW_BYTES = 128 * 1024

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

    def read_graph_spec_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        path = core_paths.package_root() / "docs" / "schemas" / "graph-spec-v0.1.schema.json"
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return self._resource_response(self._GRAPH_SPEC_SCHEMA_RESOURCE_URI, payload)

    def _read_hocusscript_schema(self, filename: str, uri: str) -> dict[str, Any]:
        path = core_paths.package_root() / "docs" / "schemas" / filename
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return self._resource_response(uri, payload)

    def read_preview_bundle_input_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-preview-bundle-input-v1.schema.json",
            self._PREVIEW_INPUT_SCHEMA_RESOURCE_URI,
        )

    def read_preview_bundle_output_schema(self, context: RequestContext) -> dict[str, Any]:
        del context
        return self._read_hocusscript_schema(
            "document-preview-bundle-output-v1.schema.json",
            self._PREVIEW_OUTPUT_SCHEMA_RESOURCE_URI,
        )

    def read_document_preview(self, preview_id: str, context: RequestContext) -> dict[str, Any] | None:
        del context
        payload = self._documents.preview_artifact(preview_id)
        if payload is None:
            return None
        return self._resource_response(f"houdini://documents/previews/{preview_id}", payload)
