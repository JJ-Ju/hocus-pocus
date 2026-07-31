"""Private fresh live-semantic gate for authenticated document bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ._document_bundle_boundary import _DecodedDocumentBundle
from .bundle import MODULE_BUNDLE_VERSION
from .catalog import CatalogProvider, CatalogSnapshot
from .contracts import CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION
from .control_artifact import rehydrate_control_graph
from .model import GraphSpec, graph_spec_from_dict
from .semantic import (
    CatalogConstraint,
    ExternalNodeBinding,
    SemanticResult,
    resolve_graph,
)

_DIAGNOSTIC_CARRIER_HINTS = {
    "controlStackId",
    "originId",
    "sourceUri",
    "span",
    "stackId",
}
_SEMANTIC_FIELDS = (
    "stage",
    "valid",
    "readyForDocumentLowering",
    "catalogFingerprint",
    "operatorSelections",
    "parameterSelections",
    "connectionSelections",
    "deferredChecks",
    "diagnostics",
    "runtimeSelections",
)


class _FreshDocumentSemanticError(ValueError):
    """Typed private rejection when authenticated and live semantics diverge."""

    def __init__(
        self, message: str, *, field: str, expected: Any = None, actual: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = "HOCUS722"
        self.message = message
        self.field = field
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True, slots=True)
class _FreshDocumentBundleSemantics:
    """Fresh resolution plus the conservative authenticated plan manifest."""

    graph: GraphSpec
    semantic_result: SemanticResult
    required_capabilities: tuple[str, ...]


def _resolve_decoded_document_bundle_semantics(
    bundle: _DecodedDocumentBundle,
    catalog_provider: CatalogProvider,
    *,
    external_bindings: Mapping[str, ExternalNodeBinding] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> _FreshDocumentBundleSemantics:
    """Rehydrate and freshly validate exact Bundle 0.3/0.4 semantics.

    The catalog fingerprint identifies the live semantic snapshot. The
    carrier's catalog content digest remains authenticated metadata; this gate
    does not claim live file-byte verification or complete package-search
    provenance.
    """

    if type(bundle) is not _DecodedDocumentBundle:
        raise TypeError("Fresh document semantics require an authenticated bundle boundary value.")
    payload = bundle.payload
    graph = _rehydrate_exact_graph(bundle.version, payload)
    bundled = payload["semanticResolution"]
    manifest = payload["requiredCapabilities"]
    if bundled["requiredCapabilities"] != manifest:
        _drift(
            "requiredCapabilities",
            manifest,
            bundled["requiredCapabilities"],
            "The bundled semantic capability manifest conflicts with the bundle manifest.",
        )
    try:
        snapshot = catalog_provider.get_catalog()
    except Exception as exc:
        raise _FreshDocumentSemanticError(
            "The live catalog provider could not produce a semantic snapshot.",
            field="catalogProvider",
        ) from exc
    if not isinstance(snapshot, CatalogSnapshot):
        raise _FreshDocumentSemanticError(
            "The live catalog provider returned an invalid semantic snapshot.",
            field="catalogProvider",
            actual=type(snapshot).__name__,
        )
    fingerprint = payload["catalogConstraints"]["fingerprint"]
    if snapshot.fingerprint != fingerprint:
        _drift(
            "catalogFingerprint",
            fingerprint,
            snapshot.fingerprint,
            "The live catalog fingerprint differs from the authenticated bundle pin.",
        )
    fresh_result = resolve_graph(
        graph,
        snapshot,
        constraint=CatalogConstraint(fingerprint),
        external_bindings=external_bindings,
        checkpoint=checkpoint,
    )
    fresh = fresh_result.to_dict()
    _validate_capabilities(bundle.version, manifest, fresh["requiredCapabilities"])
    if external_bindings and not bundled["readyForDocumentLowering"]:
        unbound = resolve_graph(
            graph,
            snapshot,
            constraint=CatalogConstraint(fingerprint),
            checkpoint=checkpoint,
        ).to_dict()
        _validate_capabilities(
            bundle.version,
            manifest,
            unbound["requiredCapabilities"],
        )
        _validate_semantic_equivalence(
            bundled,
            unbound,
            allow_external_relaxation=False,
        )
    _validate_semantic_equivalence(bundled, fresh)
    return _FreshDocumentBundleSemantics(
        graph,
        fresh_result,
        tuple(manifest),
    )


def _rehydrate_exact_graph(version: str, payload: dict[str, Any]) -> GraphSpec:
    try:
        graph = (
            rehydrate_control_graph(
                payload["graphSpec"],
                resolved_limits=payload["resolvedModuleSet"]["limits"],
            )
            if version in {CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION}
            else graph_spec_from_dict(payload["graphSpec"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _FreshDocumentSemanticError(
            "The authenticated graph could not be rehydrated for fresh resolution.",
            field="graphSpec",
        ) from exc
    if version not in {
        MODULE_BUNDLE_VERSION, CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION,
    }:
        raise _FreshDocumentSemanticError(
            "Fresh semantics require exact Bundle 0.3 or Bundle 0.4.",
            field="bundleVersion",
            actual=version,
        )
    if graph.to_dict() != payload["graphSpec"]:
        _drift(
            "graphSpec",
            payload["graphSpec"],
            graph.to_dict(),
            "Authenticated graph rehydration changed carrier content.",
        )
    return graph


def _validate_capabilities(
    version: str,
    manifest: list[str],
    fresh: list[str],
) -> None:
    manifest_set, fresh_set = set(manifest), set(fresh)
    if version in {CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION}:
        valid = fresh_set <= manifest_set and manifest_set - fresh_set <= {"run_code"}
    else:
        valid = fresh == manifest
    if not valid:
        _drift(
            "requiredCapabilities",
            manifest,
            fresh,
            "Fresh graph capabilities conflict with the authenticated bundle manifest.",
        )


def _validate_semantic_equivalence(
    bundled: dict[str, Any],
    fresh: dict[str, Any],
    *,
    allow_external_relaxation: bool = True,
) -> None:
    normalized_bundled = {**bundled, "diagnostics": _semantic_diagnostics(bundled)}
    normalized_fresh = {**fresh, "diagnostics": _semantic_diagnostics(fresh)}
    if (
        allow_external_relaxation
        and _external_output_relaxation(normalized_bundled, normalized_fresh)
    ):
        return
    for field in _SEMANTIC_FIELDS:
        if normalized_bundled.get(field) != normalized_fresh.get(field):
            _drift(
                field,
                normalized_bundled.get(field),
                normalized_fresh.get(field),
                f"Fresh semantic {field} differs from the authenticated bundle.",
            )


def _semantic_diagnostics(semantic: dict[str, Any]) -> list[dict[str, Any]]:
    return [_without_carrier_hints(item) for item in semantic["diagnostics"]]


def _without_carrier_hints(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_carrier_hints(item)
            for key, item in value.items()
            if key not in _DIAGNOSTIC_CARRIER_HINTS
        }
    if isinstance(value, list):
        return [_without_carrier_hints(item) for item in value]
    return value


def _external_output_relaxation(
    bundled: dict[str, Any],
    fresh: dict[str, Any],
) -> bool:
    deferred = bundled["deferredChecks"]
    diagnostics = bundled["diagnostics"]
    if (
        bundled["readyForDocumentLowering"]
        or not deferred
        or any(item.get("kind") != "external_output" for item in deferred)
        or any(item.get("code") != "HOCUS643" for item in diagnostics)
    ):
        return False
    exact_fields = (
        "stage",
        "valid",
        "catalogFingerprint",
        "operatorSelections",
        "parameterSelections",
    )
    return bool(
        all(bundled[field] == fresh[field] for field in exact_fields)
        and bundled.get("runtimeSelections") == fresh.get("runtimeSelections")
        and all(item in fresh["connectionSelections"] for item in bundled["connectionSelections"])
        and fresh["valid"]
        and fresh["readyForDocumentLowering"]
        and not fresh["deferredChecks"]
        and not fresh["diagnostics"]
    )


def _drift(
    field: str,
    expected: Any,
    actual: Any,
    message: str,
) -> None:
    raise _FreshDocumentSemanticError(
        message,
        field=field,
        expected=expected,
        actual=actual,
    )
