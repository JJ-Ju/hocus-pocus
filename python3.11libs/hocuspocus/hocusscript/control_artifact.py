"""Content-only semantic and Bundle 0.4 bridge for HocusScript 0.3."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .catalog import CatalogProvider, CatalogSnapshot
from .contracts import (
    CONTROL_BUNDLE_VERSION,
    CONTROL_COMPILER_VERSION,
    CONTROL_GRAPH_SPEC_VERSION,
    CONTROL_LANGUAGE_VERSION,
    decode_control_bundle_envelope,
    decode_control_graph_spec_envelope,
    decode_control_resolved_module_set_envelope,
)
from .model import GraphSpec, graph_spec_from_dict
from .semantic import CatalogConstraint, SemanticResult, resolve_graph


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CAPABILITIES = frozenset({"edit_scene", "run_code"})


class ControlArtifactError(ValueError):
    """Typed failure from the content-only HocusScript 0.3 artifact bridge."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ControlCompiledBundle:
    """Authenticated deterministic Bundle 0.4 content."""

    _payload_json: str
    digest: str

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self._payload_json)
            decoded = decode_control_bundle_envelope(
                {**payload, "bundleDigest": self.digest},
            )
        except Exception as exc:
            raise ValueError("ControlCompiledBundle content is invalid.") from exc
        unsigned = dict(decoded)
        declared = unsigned.pop("bundleDigest")
        if (
            declared != self.digest
            or _canonical_json(unsigned) != self._payload_json
        ):
            raise ValueError("ControlCompiledBundle content is noncanonical.")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "bundleDigest": self.digest}

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
        return _canonical_json(self.to_dict())


def rehydrate_control_graph(
    value: Any,
    *,
    resolved_limits: Mapping[str, int],
) -> GraphSpec:
    """Strict-decode GraphSpec 0.4 and expose its existing semantic model view."""

    decoded = decode_control_graph_spec_envelope(
        value,
        resolved_limits=resolved_limits,
    )
    try:
        graph = graph_spec_from_dict(decoded)
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlArtifactError(
            "HOCUS495",
            "Strict GraphSpec 0.4 could not be rehydrated for semantic resolution.",
        ) from exc
    if graph.to_dict() != decoded:
        raise ControlArtifactError(
            "HOCUS495",
            "Rehydrated GraphSpec 0.4 changed canonical carrier content.",
        )
    return graph


def _compile_control_bundle(
    graph_spec: Any,
    resolved_module_set: Any,
    *,
    entry_source_digest: str,
    catalog: CatalogSnapshot | CatalogProvider,
    catalog_content_digest: str,
    catalog_fingerprint: str,
    admitted_required_capabilities: Iterable[str],
) -> ControlCompiledBundle:
    """Resolve explicit canonical inputs and produce a self-authenticated Bundle 0.4."""

    resolved = decode_control_resolved_module_set_envelope(resolved_module_set)
    graph_payload = decode_control_graph_spec_envelope(
        graph_spec,
        resolved_limits=resolved["limits"],
    )
    graph = rehydrate_control_graph(
        graph_payload,
        resolved_limits=resolved["limits"],
    )
    _require_digest(entry_source_digest, "entry_source_digest")
    _require_digest(catalog_content_digest, "catalog_content_digest")
    _require_digest(catalog_fingerprint, "catalog_fingerprint")
    snapshot = _catalog_snapshot(catalog)
    if snapshot.fingerprint != catalog_fingerprint:
        raise ControlArtifactError(
            "HOCUS495",
            "Catalog snapshot fingerprint does not match the admitted catalog pin.",
            details={
                "expected": catalog_fingerprint,
                "actual": snapshot.fingerprint,
            },
        )
    semantic = resolve_graph(
        graph,
        snapshot,
        constraint=CatalogConstraint(catalog_fingerprint),
    )
    if not semantic.valid:
        errors = [item for item in semantic.diagnostics if item.severity == "error"]
        diagnostics = [item.to_dict() for item in semantic.diagnostics]
        error_diagnostics = [item.to_dict() for item in errors]
        raise ControlArtifactError(
            "HOCUS496",
            "Control graph semantic resolution is invalid; Bundle 0.4 creation is blocked.",
            details={
                "diagnosticCount": len(semantic.diagnostics),
                "errorCodes": sorted({item.code for item in errors}),
                "diagnostic": error_diagnostics[0],
                "diagnostics": diagnostics,
            },
        )
    capabilities = _required_capabilities(
        admitted_required_capabilities,
        semantic,
    )
    semantic_payload = _semantic_payload(
        semantic,
        graph_payload["expansionMap"]["mappings"],
        capabilities,
    )
    unsigned = _bundle_payload(
        graph_payload,
        resolved,
        semantic_payload,
        entry_source_digest,
        catalog_content_digest,
        catalog_fingerprint,
        capabilities,
    )
    digest = _digest_json(unsigned)
    decoded = decode_control_bundle_envelope(
        {**unsigned, "bundleDigest": digest},
    )
    authenticated = dict(decoded)
    authenticated.pop("bundleDigest")
    return ControlCompiledBundle(_canonical_json(authenticated), digest)


def _catalog_snapshot(
    value: CatalogSnapshot | CatalogProvider,
) -> CatalogSnapshot:
    snapshot = value if isinstance(value, CatalogSnapshot) else value.get_catalog()
    if not isinstance(snapshot, CatalogSnapshot):
        raise ControlArtifactError(
            "HOCUS495",
            "Control artifact catalog provider returned an invalid snapshot.",
        )
    return snapshot


def _required_capabilities(
    admitted: Iterable[str],
    semantic: SemanticResult,
) -> tuple[str, ...]:
    if isinstance(admitted, (str, bytes, bytearray)):
        raise ControlArtifactError(
            "HOCUS495",
            "admitted_required_capabilities must be an iterable of capability names.",
        )
    try:
        values = tuple(admitted)
    except Exception as exc:
        raise ControlArtifactError(
            "HOCUS495",
            "admitted_required_capabilities could not be read.",
        ) from exc
    if (
        len(values) > len(_CAPABILITIES)
        or len(set(values)) != len(values)
        or any(not isinstance(item, str) or item not in _CAPABILITIES for item in values)
    ):
        raise ControlArtifactError(
            "HOCUS495",
            "Admitted control capabilities are invalid.",
        )
    return tuple(sorted(set(values) | set(semantic.required_capabilities)))


def _semantic_payload(
    semantic: SemanticResult,
    mappings: list[dict[str, Any]],
    capabilities: tuple[str, ...],
) -> dict[str, Any]:
    payload = semantic.to_dict()
    payload["requiredCapabilities"] = list(capabilities)
    for diagnostic in payload["diagnostics"]:
        mapping = _enclosing_mapping(diagnostic.get("jsonPointer"), mappings)
        diagnostic["originId"] = (
            mapping["originId"] if mapping is not None else None
        )
        diagnostic["stackId"] = (
            mapping["stackId"] if mapping is not None else None
        )
    return payload


def _enclosing_mapping(
    pointer: Any,
    mappings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(pointer, str):
        return None
    candidates = [
        item
        for item in mappings
        if pointer == item["generatedPointer"]
        or pointer.startswith(item["generatedPointer"] + "/")
        or item["generatedPointer"] == ""
    ]
    return max(
        candidates,
        key=lambda item: len(item["generatedPointer"]),
        default=None,
    )


def _bundle_payload(
    graph: dict[str, Any],
    resolved: dict[str, Any],
    semantic: dict[str, Any],
    entry_source_digest: str,
    catalog_content_digest: str,
    catalog_fingerprint: str,
    capabilities: tuple[str, ...],
) -> dict[str, Any]:
    entry_uri = resolved["entrySourceUri"]
    expansion = graph["expansionMap"]
    return {
        "$schema": "hocuspocus://schemas/compiled-bundle/v0.4",
        "kind": "hocus_compiled_bundle",
        "bundleVersion": CONTROL_BUNDLE_VERSION,
        "compilerVersion": CONTROL_COMPILER_VERSION,
        "graphSpecVersion": CONTROL_GRAPH_SPEC_VERSION,
        "languageVersion": CONTROL_LANGUAGE_VERSION,
        "portable": True,
        "projectUid": resolved["projectUid"],
        "projectManifestDigest": resolved["projectManifestDigest"],
        "projectLockDigest": resolved["projectLockDigest"],
        "entrySource": {
            "uri": entry_uri,
            "digest": entry_source_digest,
            "kind": "project_file",
        },
        "dependencies": [
            {
                "uri": item["uri"],
                "digest": item["sourceDigest"],
                "kind": "module",
            }
            for item in resolved["modules"]
        ],
        "catalogConstraints": {
            "schemaVersion": 1,
            "fingerprint": catalog_fingerprint,
            "contentDigest": catalog_content_digest,
        },
        "requiredCapabilities": list(capabilities),
        "sourceMaps": {
            "format": "graph-spec-expansion-v2",
            "entrySourceUri": entry_uri,
            "embeddedInGraphSpec": True,
            "expansionMapVersion": 2,
            "expansionMapDigest": _digest_json(expansion),
        },
        "graphSpec": graph,
        "semanticResolution": semantic,
        "resolvedModuleSet": resolved,
    }


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ControlArtifactError(
            "HOCUS495",
            f"{label} must be a lowercase SHA-256 digest.",
        )
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8"),
    ).hexdigest()
