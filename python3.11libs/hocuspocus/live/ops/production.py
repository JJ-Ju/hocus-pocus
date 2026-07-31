"""High-level HS8 production qualification tool and schema resources."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.mcp_types import (
    ResourceDefinition,
    ResourceRegistry,
    ToolDefinition,
    ToolRegistry,
)
from hocuspocus.core.policy import OBSERVE
from hocuspocus.hocusscript.asset_contract import AssetContractError
from hocuspocus.hocusscript.build_comparison import BuildComparisonError
from hocuspocus.hocusscript.build_gates import BuildGateError
from hocuspocus.hocusscript.build_metrics import BuildMetricsError
from hocuspocus.hocusscript.build_provenance import BuildProvenanceError
from hocuspocus.hocusscript.build_provenance import canonical_digest
from hocuspocus.hocusscript.production_pipeline import (
    PRODUCTION_EVIDENCE_FIELDS,
    ProductionQualification,
    ProductionQualificationError,
    decode_production_qualification,
    qualify_production_asset_content,
)

from ..context import RequestContext
_SCHEMAS = (
    (
        "houdini://production/schema/asset-contract/v1",
        "hocuspocus://schemas/asset-contract/v1",
        "HS8 Asset Contract v1",
        "asset-contract-v1.schema.json",
    ),
    (
        "houdini://production/schema/build-provenance/v1",
        "hocuspocus://schemas/build-provenance-manifest/v1",
        "HS8 Build Provenance v1",
        "build-provenance-manifest-v1.schema.json",
    ),
    (
        "houdini://production/schema/build-report/v1",
        "hocuspocus://schemas/build-report/v1",
        "HS8 Build Report v1",
        "build-report-v1.schema.json",
    ),
    (
        "houdini://production/schema/publish-gate/v1",
        "hocuspocus://schemas/publish-gate-receipt/v1",
        "HS8 Publish Gate Receipt v1",
        "publish-gate-receipt-v1.schema.json",
    ),
    (
        "houdini://production/schema/qualification/v1",
        "hocuspocus://schemas/production-qualification/v1",
        "HS8 Production Qualification v1",
        "production-qualification-v1.schema.json",
    ),
)
_PRODUCTION_ERRORS = (
    AssetContractError,
    BuildComparisonError,
    BuildGateError,
    BuildMetricsError,
    BuildProvenanceError,
    ProductionQualificationError,
)


class ProductionOperationsMixin:
    """Register one cohesive production decision instead of low-level tool sprawl."""

    def register_production_surface(
        self,
        tools: ToolRegistry,
        resources: ResourceRegistry,
    ) -> None:
        tools.register(
            ToolDefinition(
                name="production.asset.qualify",
                title="Qualify Production Asset",
                description=(
                    "Bind an asset contract, exact observation, repeated-build "
                    "provenance, budgets, numeric/visual regressions, and artist "
                    "override plus explicit visual/version review evidence into "
                    "packaging and publish decisions."
                ),
                input_schema=_qualification_input_schema(),
                annotations={"readOnlyHint": True, "idempotentHint": False},
                required_capabilities=(OBSERVE,),
                handler=self.production_asset_qualify,
                output_summary=(
                    "Content-addressed contract report, build report, packaging "
                    "gate, publish gate, and complete qualification digest."
                ),
                execution_hint="blocking",
                failure_notes=[
                    "Every carrier is strict and content-addressed; malformed or "
                    "inconsistent evidence fails with its HOCUS diagnostic code.",
                    "Caller-supplied content is advisory and can never mint "
                    "actionable packaging, publishing, or release authority.",
                ],
                examples=[],
            )
        )
        for legacy_uri, canonical_uri, name, filename in _SCHEMAS:
            for uri, label in (
                (canonical_uri, name),
                (legacy_uri, f"{name} (legacy alias)"),
            ):
                resources.register(
                    ResourceDefinition(
                        uri=uri,
                        name=label,
                        description=f"Machine-readable {name} schema.",
                        mime_type="application/json",
                        reader=lambda context, uri=uri, filename=filename: (
                            self._read_production_schema(uri, filename, context)
                        ),
                        payload_summary=f"Strict machine-readable {name} contract.",
                    )
                )

    def production_asset_qualify(
        self,
        arguments: dict[str, Any],
        context: RequestContext,
    ) -> dict[str, Any]:
        context.raise_if_cancelled()
        try:
            evidence = _qualification_arguments(arguments)
            result = qualify_production_asset_content(evidence)
            payload = _public_qualification_payload(
                result,
                None,
                host_authorized=False,
            )
            payload = decode_production_qualification(payload).to_dict()
        except _PRODUCTION_ERRORS as exc:
            details = dict(getattr(exc, "details", {}) or {})
            details["diagnosticCode"] = getattr(exc, "code", "HOCUS990")
            pointer = getattr(exc, "pointer", "")
            if pointer:
                details["jsonPointer"] = pointer
            raise JsonRpcError(INVALID_PARAMS, str(exc), details) from exc
        context.raise_if_cancelled()
        return self._tool_response(
            "Production qualification returned an advisory publish-gate decision.",
            payload,
        )

    def _read_production_schema(
        self,
        uri: str,
        filename: str,
        context: RequestContext,
    ) -> dict[str, Any]:
        del context
        path = core_paths.package_root() / "docs" / "schemas" / filename
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return self._resource_response(uri, payload)


def _qualification_input_schema() -> dict[str, Any]:
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    metric_fields = (
        "cookDurationMs", "peakMemoryBytes", "polygonCount", "textureCount",
        "textureBytes", "outputBytes", "cookErrorCount", "cookWarningCount",
    )
    count = {"type": "integer", "minimum": 0, "maximum": (1 << 63) - 1}
    non_negative = {"type": "number", "minimum": 0}
    metrics = _closed_schema({
        "cookDurationMs": {
            "type": "number", "minimum": 0, "maximum": 31_536_000_000,
        },
        **{field: count for field in metric_fields if field != "cookDurationMs"},
    })
    budget = _closed_schema({
        "targetPlatform": {
            "type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$",
        },
        "maxCookDurationMs": {
            "type": "number", "minimum": 0, "maximum": 31_536_000_000,
        },
        **{
            field: count
            for field in (
                "maxPeakMemoryBytes", "maxPolygonCount", "maxTextureCount",
                "maxTextureBytes", "maxOutputBytes", "maxCookErrorCount",
                "maxCookWarningCount",
            )
        },
    })
    numeric_map = _closed_schema({
        field: non_negative for field in metric_fields
    })
    visual = _closed_schema({
        "outputUri": {
            "type": "string", "pattern": "^hocus-output://", "maxLength": 8192,
        },
        "baselineDigest": digest,
        "candidateDigest": digest,
        "algorithm": {
            "type": "string", "pattern": "^[a-z][a-z0-9._-]{0,63}$",
        },
        "difference": non_negative,
        "maximumDifference": non_negative,
    })
    artist = _closed_schema({
        "kind": {"const": "artist_override_evidence"},
        "protectedRegionCount": count,
        "beforeDigest": digest,
        "afterDigest": digest,
        "passed": {"type": "boolean"},
    })
    review_evidence = _review_evidence_schema(digest)
    return {
        "type": "object",
        "properties": {
            "contract": {"$ref": "hocuspocus://schemas/asset-contract/v1"},
            "observation": _observation_schema(digest, count),
            "baselineProvenance": {
                "$ref": "hocuspocus://schemas/build-provenance-manifest/v1",
            },
            "candidateProvenance": {
                "$ref": "hocuspocus://schemas/build-provenance-manifest/v1",
            },
            "metrics": metrics,
            "budget": budget,
            "numericBaseline": numeric_map,
            "numericCandidate": numeric_map,
            "numericTolerances": numeric_map,
            "visualComparisons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1024,
                "items": visual,
            },
            "artistOverrideEvidence": artist,
            "visualVersionReviewEvidence": {
                "oneOf": [review_evidence, {"type": "null"}],
            },
        },
        "required": sorted(PRODUCTION_EVIDENCE_FIELDS),
        "additionalProperties": False,
    }


def _closed_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _review_evidence_schema(digest: dict[str, Any]) -> dict[str, Any]:
    portable_id = {
        "type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$",
    }
    return _closed_schema({
        "kind": {"const": "hocus_visual_version_review_evidence"},
        "reviewVersion": {"const": 1},
        "assetUri": {
            "type": "string", "pattern": "^hocus-asset://", "maxLength": 8192,
        },
        "candidateProvenanceManifestDigest": digest,
        "candidateOutputSetDigest": digest,
        "visualComparisonDigest": digest,
        "candidateVersionId": portable_id,
        "reviewPolicyId": portable_id,
        "reviewerPrincipalId": {
            "type": "string",
            "pattern": (
                "^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
                "hprincipal_[0-9a-f]{32}|sha256:[0-9a-f]{64})$"
            ),
        },
        "decision": {"enum": ["approved", "rejected"]},
        "notesDigest": {"oneOf": [digest, {"type": "null"}]},
    })


def _observation_schema(
    digest: dict[str, Any],
    count: dict[str, Any],
) -> dict[str, Any]:
    name = {
        "type": "string",
        "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,127}$",
    }
    identifier = {
        "type": "string",
        "pattern": "^[A-Za-z][A-Za-z0-9_.:-]{0,127}$",
    }
    vector = {
        "type": "array", "minItems": 3, "maxItems": 3,
        "items": {"type": "number", "minimum": -1e12, "maximum": 1e12},
    }
    reason = {
        "enum": [
            "host_api_unavailable", "texture_resolution_unavailable",
            "runtime_camera_model_unavailable", "required_input_unavailable",
            "not_applicable",
        ],
    }
    measured_number = _closed_schema({
        "status": {"const": "measured"},
        "value": {"type": "number"},
    })
    measured_integer = _closed_schema({
        "status": {"const": "measured"},
        "value": count,
    })
    not_observed = _closed_schema({
        "status": {"const": "not_observed"},
        "reasonCode": reason,
    })
    measurement = {"oneOf": [measured_number, not_observed]}
    integer_measurement = {"oneOf": [measured_integer, not_observed]}
    density_measurement = {
        "oneOf": [
            _closed_schema({
                "status": {"const": "measured"},
                "value": {"type": "number", "minimum": 0},
                "unit": {"const": "px_per_scene_unit"},
            }),
            not_observed,
        ],
    }
    dependency = _closed_schema({
        "id": identifier,
        "kind": {"enum": ["asset", "hda", "module", "texture", "usd"]},
        "version": {
            "type": "string",
            "pattern": "^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$",
        },
        "digest": digest,
    })
    return _closed_schema({
        "assetId": identifier,
        "space": _closed_schema({
            "metersPerUnit": {"type": "number"},
            "upAxis": {"enum": ["X", "Y", "Z"]},
            "forwardAxis": {"enum": ["X", "Y", "Z", "-X", "-Y", "-Z"]},
            "handedness": {"enum": ["left", "right"]},
        }),
        "names": {
            "type": "array", "maxItems": 4096, "uniqueItems": True,
            "items": name,
        },
        "geometry": _closed_schema({
            "pivot": vector,
            "bounds": _closed_schema({"minimum": vector, "maximum": vector}),
            "topology": _closed_schema({
                "manifold": {"type": "boolean"},
                "watertight": {"type": "boolean"},
                "maxNgonSides": count,
                "degenerateCount": count,
            }),
            "normals": _closed_schema({
                "present": {"type": "boolean"},
                "consistent": {"type": "boolean"},
                "maxUnitLengthError": {"type": "number", "minimum": 0},
            }),
            "tangents": _closed_schema({
                "present": {"type": "boolean"},
                "orthogonal": {"type": "boolean"},
                "maxOrthogonalError": {"type": "number", "minimum": 0},
            }),
        }),
        "surface": _closed_schema({
            "uvSets": {
                "type": "array", "maxItems": 32,
                "items": _closed_schema({
                    "name": name,
                    "udimTiles": {
                        "type": "array", "maxItems": 256, "uniqueItems": True,
                        "items": count,
                    },
                    "duplicateUvTriangleCount": integer_measurement,
                    "texelDensity": density_measurement,
                }),
            },
            "materialSlots": {
                "type": "array", "maxItems": 256, "uniqueItems": True,
                "items": name,
            },
            "textureBytes": count,
        }),
        "delivery": _closed_schema({
            "lods": {
                "type": "array", "maxItems": 16,
                "items": _closed_schema({
                    "name": name,
                    "triangles": count,
                    "vertices": count,
                    "relativeTriangleReduction": measurement,
                }),
            },
            "collision": _closed_schema({
                "mode": {"enum": ["none", "simple", "convex", "mesh"]},
                "convex": {"type": "boolean"},
                "primitives": count,
                "triangles": count,
            }),
            "instancing": _closed_schema({
                "used": {"type": "boolean"},
                "prototypePrimPath": {
                    "type": "string",
                    "pattern": "^/[A-Za-z_][A-Za-z0-9_/]*$",
                    "maxLength": 512,
                },
                "representation": {
                    "enum": ["native_instance", "point_instancer"],
                },
                "uniqueMeshes": count,
                "unpackedInstances": count,
            }),
            "platformMetrics": {
                "type": "array", "maxItems": 64,
                "items": _closed_schema({
                    "platform": name,
                    "triangles": count,
                    "vertices": count,
                    "textureBytes": count,
                    "materialSlots": count,
                    "instances": count,
                }),
            },
        }),
        "usd": _closed_schema({
            "kind": {"enum": ["component", "assembly", "group"]},
            "purpose": {"enum": ["default", "proxy", "render", "guide"]},
            "variantSelections": {
                "type": "array", "maxItems": 64,
                "items": _closed_schema({"name": name, "value": name}),
            },
            "rootPrim": {
                "type": "string", "pattern": "^/[A-Za-z_][A-Za-z0-9_/]*$",
                "maxLength": 512,
            },
            "defaultPrim": {
                "type": "string", "pattern": "^/[A-Za-z_][A-Za-z0-9_/]*$",
                "maxLength": 512,
            },
            "payload": {"enum": ["inline", "payload", "reference"]},
            "primBindings": {
                "type": "array",
                "minItems": 1,
                "maxItems": 256,
                "items": _closed_schema({
                    "name": name,
                    "role": {"enum": ["render", "collision"]},
                    "primPath": {
                        "type": "string",
                        "pattern": "^/[A-Za-z_][A-Za-z0-9_/]*$",
                        "maxLength": 512,
                    },
                    "purpose": {
                        "enum": ["default", "proxy", "render", "guide"],
                    },
                    "visibility": {"enum": ["inherited", "invisible"]},
                    "materialPrimPath": {
                        "oneOf": [
                            {
                                "type": "string",
                                "pattern": "^/[A-Za-z_][A-Za-z0-9_/]*$",
                                "maxLength": 512,
                            },
                            {"type": "null"},
                        ],
                    },
                }),
            },
        }),
        "dependencies": {
            "type": "array", "maxItems": 256, "items": dependency,
        },
    })


def _qualification_arguments(
    arguments: Any,
) -> dict[str, Any]:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != set(PRODUCTION_EVIDENCE_FIELDS)
    ):
        raise ProductionQualificationError(
            "HOCUS990", "Production qualification input has an invalid envelope."
        )
    return dict(arguments)


def _public_qualification_payload(
    result: ProductionQualification,
    attestation_digest: str | None,
    *,
    host_authorized: bool,
) -> dict[str, Any]:
    payload = result.to_dict()
    eligible = payload["publishGate"]["decision"] == "pass"
    payload["authority"] = {
        "mode": "host_attested" if host_authorized else "content_only",
        "attestationDigest": attestation_digest,
    }
    payload["readyForPackaging"] = bool(
        host_authorized
        and payload["packagingGate"]["decision"] == "pass"
    )
    payload["readyForPublish"] = bool(
        payload["readyForPackaging"] and eligible
    )
    payload.pop("qualificationDigest", None)
    payload["qualificationDigest"] = canonical_digest(payload)
    return payload


__all__ = ["ProductionOperationsMixin"]
