"""Serialization helpers for semantic result carriers."""

from __future__ import annotations

from typing import Any


def semantic_result_dict(result: Any) -> dict[str, Any]:
    payload = {
        "stage": "semantic", "valid": result.valid,
        "readyForDocumentLowering": result.ready_for_document_lowering,
        "catalogFingerprint": result.catalog_fingerprint,
        "diagnostics": [item.to_dict() for item in result.diagnostics],
        "operatorSelections": [
            item.to_dict() for item in result.operator_selections
        ],
        "parameterSelections": [
            item.to_dict() for item in result.parameter_selections
        ],
        "connectionSelections": [
            item.to_dict() for item in result.connection_selections
        ],
        "deferredChecks": [
            item.to_dict() for item in result.deferred_checks
        ],
        "requiredCapabilities": list(result.required_capabilities),
    }
    if result.runtime_selections is not None:
        payload["runtimeSelections"] = [
            dict(item) for item in result.runtime_selections
        ]
    return payload

