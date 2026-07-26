"""Deterministic structural bundles for the offline-to-Houdini boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .compiler import SUPPORTED_LANGUAGE_VERSIONS
from .model import (
    COMPILER_VERSION,
    GRAPH_SPEC_VERSION,
    MODULE_COMPILER_VERSION,
    MODULE_GRAPH_SPEC_VERSION,
    MODULE_LANGUAGE_VERSION,
    LEGACY_COMPILER_VERSION,
    LEGACY_GRAPH_SPEC_VERSION,
    CompileResult,
)

BUNDLE_VERSION = "0.2"
LEGACY_BUNDLE_VERSION = "0.1"
MODULE_BUNDLE_VERSION = "0.3"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_MODULE_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_DEPTH = 128
MAX_BUNDLE_VALUES = 250_000
MAX_MODULE_BUNDLE_VALUES = 2_000_000
MAX_DEPENDENCIES = 4096
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODULE_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))"
    r"(?:\.(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_MODULE_URI_PATTERN = re.compile(
    r"^hocus-(project|module)://([a-z0-9][a-z0-9.-]{0,127})/(.+)$"
)
_JSON_POINTER_PATTERN = re.compile(r"^(?:/(?:[^~/]|~0|~1)*)*$")
_TRANSITIVE_DIGEST_DOMAIN = "hocus-module-transitive-v1"
_EXPANSION_STACK_DIGEST_DOMAIN = "hocus-expansion-stack-v1"
_BUNDLE_KEYS_V01 = {
    "$schema",
    "kind",
    "bundleVersion",
    "bundleDigest",
    "compilerVersion",
    "graphSpecVersion",
    "languageVersion",
    "portable",
    "projectUid",
    "projectManifestDigest",
    "projectLockDigest",
    "entrySource",
    "dependencies",
    "catalogConstraints",
    "requiredCapabilities",
    "sourceMaps",
    "graphSpec",
}
_BUNDLE_KEYS_V02 = {*_BUNDLE_KEYS_V01, "semanticResolution"}
_BUNDLE_KEYS_V03 = {*_BUNDLE_KEYS_V02, "resolvedModuleSet"}
_GRAPH_KEYS = {
    "$schema", "kind", "graphSpecVersion", "languageVersion", "name", "target", "category", "mode",
    "expectedRevision", "ownership", "externalNodes", "nodes", "display", "render", "output", "layout", "span", "fieldSpans",
}


class BundleValidationError(ValueError):
    """Typed rejection of an external compiled bundle."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class CompiledBundle:
    _payload_json: str
    digest: str

    @classmethod
    def from_result(cls, result: CompileResult) -> "CompiledBundle":
        if not result.valid or result.graph_spec is None:
            raise ValueError("A compiled bundle requires a valid GraphSpec result.")
        if (result.project_uid is None) != (result.project_manifest_digest is None):
            raise ValueError("Portable project UID and manifest digest must be present together.")
        graph_spec = result.graph_spec.to_dict()
        entry_uri = result.source_uri or result.source_name
        semantic = result.semantic_result.to_dict() if result.semantic_result is not None else None
        if semantic is not None:
            if not semantic.get("valid"):
                raise ValueError("A semantic bundle requires a valid semantic resolution.")
            if not result.catalog_fingerprint or not result.catalog_content_digest:
                raise ValueError("A semantic bundle requires exact catalog fingerprint and content digest pins.")
            bundle_version = BUNDLE_VERSION
            schema_uri = "hocuspocus://schemas/compiled-bundle/v0.2"
            catalog_constraints = {
                "schemaVersion": 1,
                "fingerprint": result.catalog_fingerprint,
                "contentDigest": result.catalog_content_digest,
            }
            required_capabilities = list(semantic["requiredCapabilities"])
        else:
            bundle_version = LEGACY_BUNDLE_VERSION
            schema_uri = "hocuspocus://schemas/compiled-bundle/v0.1"
            catalog_constraints = {}
            required_capabilities = _required_capabilities(graph_spec)
        payload: dict[str, Any] = {
            "$schema": schema_uri,
            "kind": "hocus_compiled_bundle",
            "bundleVersion": bundle_version,
            "compilerVersion": COMPILER_VERSION,
            "graphSpecVersion": GRAPH_SPEC_VERSION,
            "languageVersion": result.language_version,
            "portable": result.project_uid is not None and result.project_manifest_digest is not None,
            "projectUid": result.project_uid,
            "projectManifestDigest": result.project_manifest_digest,
            "projectLockDigest": result.project_lock_digest,
            "entrySource": {
                "uri": entry_uri,
                "digest": result.source_digest,
                "kind": result.source_kind,
            },
            "dependencies": [],
            "catalogConstraints": catalog_constraints,
            "requiredCapabilities": required_capabilities,
            "sourceMaps": {
                "format": "graph-spec-spans-v0.1",
                "entrySourceUri": entry_uri,
                "embeddedInGraphSpec": True,
            },
            "graphSpec": graph_spec,
        }
        if semantic is not None:
            payload["semanticResolution"] = semantic
        canonical = _canonical_json(payload)
        digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        return decode_compiled_bundle({**payload, "bundleDigest": digest})

    @property
    def payload(self) -> dict[str, Any]:
        """Return a detached payload so callers cannot invalidate the digest."""

        return json.loads(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {**json.loads(self._payload_json), "bundleDigest": self.digest}

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return _canonical_json(self.to_dict())


def _bundle_from_module_semantic(result: Any) -> CompiledBundle:
    """Assemble Bundle v0.3 from the one-shot compiler's private handoff.

    The exact-type and digest checks are internal invariants against accidental
    integration drift. They are not an authorization or process trust boundary;
    the strict content decoder remains the final bundle authority.
    """

    from .module_semantic import ModuleSemanticCompileResult

    if type(result) is not ModuleSemanticCompileResult:
        raise TypeError("Bundle v0.3 requires an exact ModuleSemanticCompileResult.")
    compiled = result.compile_result
    graph_spec = json.loads(compiled.graph_spec_json)
    resolved_module_set = json.loads(compiled.resolved_module_set_json)
    semantic = json.loads(result.semantic_json)
    if not isinstance(semantic, dict):
        raise ValueError("Bundle v0.3 requires a canonical semantic resolution object.")
    canonical_semantic = _canonical_json(semantic)
    semantic_digest = "sha256:" + hashlib.sha256(canonical_semantic.encode("utf-8")).hexdigest()
    semantic_core = json.loads(result.semantic_json)
    for diagnostic in semantic_core.get("diagnostics", []):
        diagnostic.pop("originId", None)
        diagnostic.pop("stackId", None)
    graph_digest = "sha256:" + hashlib.sha256(_canonical_json(graph_spec).encode("utf-8")).hexdigest()
    resolved_set_digest = "sha256:" + hashlib.sha256(
        _canonical_json(resolved_module_set).encode("utf-8")
    ).hexdigest()
    expansion_digest = "sha256:" + hashlib.sha256(
        _canonical_json(graph_spec["expansionMap"]).encode("utf-8")
    ).hexdigest()
    if (
        not result.valid
        or result.semantic_json != canonical_semantic
        or not hmac.compare_digest(result.semantic_digest, semantic_digest)
        or semantic_core != result.semantic_result.to_dict()
        or compiled.graph_spec_json != _canonical_json(graph_spec)
        or not hmac.compare_digest(compiled.graph_spec_digest, graph_digest)
        or compiled.resolved_module_set_json != _canonical_json(resolved_module_set)
        or not hmac.compare_digest(compiled.resolved_module_set_digest, resolved_set_digest)
        or not hmac.compare_digest(compiled.expansion_map_digest, expansion_digest)
    ):
        raise ValueError("Bundle v0.3 requires a sealed canonical module-semantic result.")
    dependencies = [
        {"uri": item["uri"], "digest": item["sourceDigest"], "kind": "module"}
        for item in sorted(resolved_module_set["modules"], key=lambda item: item["uri"])
    ]
    payload: dict[str, Any] = {
        "$schema": "hocuspocus://schemas/compiled-bundle/v0.3",
        "kind": "hocus_compiled_bundle",
        "bundleVersion": MODULE_BUNDLE_VERSION,
        "compilerVersion": MODULE_COMPILER_VERSION,
        "graphSpecVersion": MODULE_GRAPH_SPEC_VERSION,
        "languageVersion": MODULE_LANGUAGE_VERSION,
        "portable": True,
        "projectUid": compiled.project_uid,
        "projectManifestDigest": compiled.project_manifest_digest,
        "projectLockDigest": compiled.project_lock_digest,
        "entrySource": {
            "uri": compiled.entry_source_uri,
            "digest": compiled.entry_source_digest,
            "kind": "project_file",
        },
        "dependencies": dependencies,
        "catalogConstraints": {
            "schemaVersion": 1,
            "fingerprint": compiled.catalog_fingerprint,
            "contentDigest": compiled.catalog_content_digest,
        },
        "requiredCapabilities": semantic.get("requiredCapabilities"),
        "sourceMaps": {
            "format": "graph-spec-expansion-v1",
            "entrySourceUri": compiled.entry_source_uri,
            "embeddedInGraphSpec": True,
            "expansionMapVersion": 1,
            "expansionMapDigest": expansion_digest,
        },
        "graphSpec": graph_spec,
        "semanticResolution": semantic,
        "resolvedModuleSet": resolved_module_set,
    }
    canonical = _canonical_json(payload)
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return decode_compiled_bundle({**payload, "bundleDigest": digest})


def decode_compiled_bundle(value: Any) -> CompiledBundle:
    """Validate untrusted bundle content without reading source files or Houdini state."""

    if not isinstance(value, dict):
        raise BundleValidationError("HOCUS500", "Compiled bundle must be a JSON object.")
    bundle_version = value.get("bundleVersion")
    _validate_bundle_envelope(value, bundle_version)
    declared_digest, payload, canonical = _validate_bundle_digest(value, bundle_version)
    graph_spec_version, language_version = _validate_bundle_contract(
        payload, bundle_version
    )
    (
        entry, dependency_uris, module_dependencies, module_limits,
    ) = _validate_bundle_provenance_and_sources(payload, bundle_version)
    catalog_constraints = _validate_bundle_catalog(payload, bundle_version)
    graph_spec = _validate_bundle_graph(
        payload, graph_spec_version, language_version, module_dependencies,
        entry, dependency_uris, module_limits,
    )
    capabilities = _validate_bundle_capabilities(graph_spec, payload)
    _validate_bundle_semantics(
        payload, bundle_version, catalog_constraints, graph_spec, capabilities, module_limits
    )
    _validate_bundle_source_maps(payload, bundle_version, graph_spec, entry)
    return CompiledBundle(canonical, declared_digest)


def _validate_bundle_envelope(value: dict[str, Any], bundle_version: Any) -> None:
    _validate_complexity(
        value,
        max_values=(MAX_MODULE_BUNDLE_VALUES if bundle_version == MODULE_BUNDLE_VERSION else MAX_BUNDLE_VALUES),
    )
    expected_keys = {
        LEGACY_BUNDLE_VERSION: _BUNDLE_KEYS_V01,
        BUNDLE_VERSION: _BUNDLE_KEYS_V02,
        MODULE_BUNDLE_VERSION: _BUNDLE_KEYS_V03,
    }.get(bundle_version, set())
    keys = set(value)
    if bundle_version not in {LEGACY_BUNDLE_VERSION, BUNDLE_VERSION, MODULE_BUNDLE_VERSION} or keys != expected_keys:
        raise BundleValidationError(
            "HOCUS501",
            "Compiled bundle has missing or unknown top-level fields.",
            details={"missing": sorted(expected_keys - keys), "unknown": sorted(keys - expected_keys)},
        )


def _validate_bundle_digest(
    value: dict[str, Any],
    bundle_version: str,
) -> tuple[str, dict[str, Any], str]:
    declared_digest = _require_digest(value.get("bundleDigest"), "bundleDigest", "HOCUS502")
    payload = dict(value)
    del payload["bundleDigest"]
    try:
        canonical = _canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise BundleValidationError("HOCUS503", f"Compiled bundle is not canonicalizable JSON: {exc}") from exc
    max_bundle_bytes = MAX_MODULE_BUNDLE_BYTES if bundle_version == MODULE_BUNDLE_VERSION else MAX_BUNDLE_BYTES
    if len(canonical.encode("utf-8")) > max_bundle_bytes:
        raise BundleValidationError("HOCUS504", f"Compiled bundle exceeds the {max_bundle_bytes}-byte limit.")
    actual_digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    if not hmac.compare_digest(declared_digest, actual_digest):
        raise BundleValidationError(
            "HOCUS505",
            "Compiled bundle digest does not match its canonical content.",
            details={"declaredDigest": declared_digest, "actualDigest": actual_digest},
        )
    return declared_digest, payload, canonical


def _validate_bundle_contract(
    payload: dict[str, Any],
    bundle_version: str,
) -> tuple[str, str]:
    expected_schema = f"hocuspocus://schemas/compiled-bundle/v{bundle_version}"
    _require_equal(payload, "$schema", expected_schema, "HOCUS506")
    _require_equal(payload, "kind", "hocus_compiled_bundle", "HOCUS506")
    compiler_version = payload.get("compilerVersion")
    graph_spec_version = payload.get("graphSpecVersion")
    compatible_contracts = {
        LEGACY_BUNDLE_VERSION: {
            ("0.1.1", LEGACY_GRAPH_SPEC_VERSION),
            (LEGACY_COMPILER_VERSION, LEGACY_GRAPH_SPEC_VERSION),
            (COMPILER_VERSION, GRAPH_SPEC_VERSION),
        },
        BUNDLE_VERSION: {
            (LEGACY_COMPILER_VERSION, LEGACY_GRAPH_SPEC_VERSION),
            (COMPILER_VERSION, GRAPH_SPEC_VERSION),
        },
        MODULE_BUNDLE_VERSION: {(MODULE_COMPILER_VERSION, MODULE_GRAPH_SPEC_VERSION)},
    }[bundle_version]
    if (compiler_version, graph_spec_version) not in compatible_contracts:
        raise BundleValidationError(
            "HOCUS507", "Compiled bundle compiler and GraphSpec versions are not a supported pair."
        )
    language_version = payload.get("languageVersion")
    expected_language_versions = (
        {MODULE_LANGUAGE_VERSION} if bundle_version == MODULE_BUNDLE_VERSION else SUPPORTED_LANGUAGE_VERSIONS
    )
    if language_version not in expected_language_versions:
        raise BundleValidationError("HOCUS507", "Compiled bundle language version is unsupported.")
    return graph_spec_version, language_version


def _validate_bundle_catalog(payload: dict[str, Any], bundle_version: str) -> dict[str, Any]:
    catalog_constraints = payload.get("catalogConstraints")
    if bundle_version == LEGACY_BUNDLE_VERSION:
        if catalog_constraints != {}:
            raise BundleValidationError("HOCUS513", "Bundle v0.1 catalogConstraints must be empty.")
    else:
        _validate_catalog_constraints(catalog_constraints)
    return catalog_constraints


def _validate_bundle_graph(
    payload: dict[str, Any],
    graph_spec_version: str,
    language_version: str,
    module_dependencies: list[dict[str, Any]],
    entry: dict[str, str],
    dependency_uris: set[str],
    module_limits: dict[str, int] | None,
) -> dict[str, Any]:
    graph_spec = payload.get("graphSpec")
    if not isinstance(graph_spec, dict):
        raise BundleValidationError("HOCUS514", "graphSpec must be an object.")
    _require_equal(
        graph_spec, "$schema", f"hocuspocus://schemas/graph-spec/v{graph_spec_version}", "HOCUS514"
    )
    _require_equal(graph_spec, "kind", "graph_spec", "HOCUS514")
    _require_equal(graph_spec, "graphSpecVersion", graph_spec_version, "HOCUS514")
    _require_equal(graph_spec, "languageVersion", language_version, "HOCUS514")
    nodes = graph_spec.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 10_000:
        raise BundleValidationError("HOCUS515", "graphSpec.nodes must be an array with at most 10000 entries.")
    _validate_graph_spec(
        graph_spec,
        graph_spec_version=graph_spec_version,
        module_dependencies={item["uri"]: item for item in module_dependencies},
        entry_source_uri=entry["uri"],
        module_limits=module_limits,
    )
    _validate_declared_source_uris(graph_spec, {entry["uri"], *dependency_uris})
    return graph_spec


def _validate_bundle_capabilities(
    graph_spec: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    capabilities = payload.get("requiredCapabilities")
    expected_capabilities = _required_capabilities(graph_spec)
    if capabilities != expected_capabilities:
        raise BundleValidationError(
            "HOCUS516",
            "requiredCapabilities does not match the GraphSpec content.",
            details={"expected": expected_capabilities, "actual": capabilities},
        )
    return capabilities


def _validate_bundle_semantics(
    payload: dict[str, Any],
    bundle_version: str,
    catalog_constraints: dict[str, Any],
    graph_spec: dict[str, Any],
    capabilities: list[str],
    module_limits: dict[str, int] | None,
) -> None:
    if bundle_version in {BUNDLE_VERSION, MODULE_BUNDLE_VERSION}:
        semantic = _validate_semantic_resolution(
            payload.get("semanticResolution"), catalog_constraints, graph_spec,
            require_module_provenance=bundle_version == MODULE_BUNDLE_VERSION,
        )
        if module_limits is not None and len(semantic["diagnostics"]) > module_limits["diagnostics"]:
            raise BundleValidationError("HOCUS521", "Semantic diagnostics exceed resolved module limits.")
        if semantic["requiredCapabilities"] != capabilities:
            raise BundleValidationError(
                "HOCUS516",
                "Semantic capability manifest does not match requiredCapabilities.",
            )


def _validate_bundle_source_maps(
    payload: dict[str, Any],
    bundle_version: str,
    graph_spec: dict[str, Any],
    entry: dict[str, str],
) -> None:
    source_maps = payload.get("sourceMaps")
    if bundle_version == MODULE_BUNDLE_VERSION:
        expansion_map = graph_spec["expansionMap"]
        expansion_digest = "sha256:" + hashlib.sha256(
            _canonical_json(expansion_map).encode("utf-8")
        ).hexdigest()
        expected_source_maps = {
            "format": "graph-spec-expansion-v1",
            "entrySourceUri": entry["uri"],
            "embeddedInGraphSpec": True,
            "expansionMapVersion": 1,
            "expansionMapDigest": expansion_digest,
        }
    else:
        expected_source_maps = {
            "format": "graph-spec-spans-v0.1",
            "entrySourceUri": entry["uri"],
            "embeddedInGraphSpec": True,
        }
    if not isinstance(source_maps, dict) or source_maps != expected_source_maps:
        raise BundleValidationError("HOCUS517", "sourceMaps is inconsistent with the bundle contract.")


def _validate_bundle_provenance_and_sources(
    payload: dict[str, Any], bundle_version: str,
) -> tuple[dict[str, str], set[str], list[dict[str, Any]], dict[str, int] | None]:
    portable = payload.get("portable")
    if not isinstance(portable, bool):
        raise BundleValidationError("HOCUS508", "portable must be a boolean.")
    project_uid = payload.get("projectUid")
    manifest_digest = payload.get("projectManifestDigest")
    lock_digest = payload.get("projectLockDigest")
    if portable:
        if not isinstance(project_uid, str) or not _PROJECT_UID_PATTERN.fullmatch(project_uid):
            raise BundleValidationError("HOCUS509", "Portable bundles require a valid stable projectUid.")
        _require_digest(manifest_digest, "projectManifestDigest", "HOCUS509")
    elif project_uid is not None or manifest_digest is not None:
        raise BundleValidationError(
            "HOCUS509", "Preview-only bundles cannot claim portable project identity."
        )
    if lock_digest is not None:
        _require_digest(lock_digest, "projectLockDigest", "HOCUS509")
    if bundle_version in {BUNDLE_VERSION, MODULE_BUNDLE_VERSION} and portable and lock_digest is None:
        raise BundleValidationError("HOCUS509", "Portable semantic bundles require projectLockDigest.")
    if bundle_version == MODULE_BUNDLE_VERSION and not portable:
        raise BundleValidationError("HOCUS509", "Bundle v0.3 module graphs must be portable.")
    if not portable and lock_digest is not None:
        raise BundleValidationError(
            "HOCUS509", "Preview-only bundles cannot claim a project lock digest."
        )
    entry = _validate_source(
        payload.get("entrySource"), "entrySource",
        allow_kinds={"project_file", "workspace_file", "memory"},
    )
    if portable and (
        entry["kind"] != "project_file"
        or not entry["uri"].startswith(f"hocus-project://{project_uid}/")
    ):
        raise BundleValidationError(
            "HOCUS510", "Portable entry source URI must match its project UID."
        )
    if not portable and entry["kind"] == "project_file":
        raise BundleValidationError(
            "HOCUS510", "Preview-only bundles cannot claim a project_file entry source."
        )
    dependencies = payload.get("dependencies")
    dependency_uris = _validate_dependency_sources(dependencies)
    if bundle_version != MODULE_BUNDLE_VERSION:
        return entry, dependency_uris, [], None
    module_dependencies, module_limits = _validate_resolved_module_set(
        payload.get("resolvedModuleSet"),
        sources=dependencies,
        project_uid=project_uid,
        entry_source_uri=entry["uri"],
        project_manifest_digest=manifest_digest,
        project_lock_digest=lock_digest,
    )
    return entry, dependency_uris, module_dependencies, module_limits


def _validate_dependency_sources(value: Any) -> set[str]:
    if not isinstance(value, list) or len(value) > MAX_DEPENDENCIES:
        raise BundleValidationError(
            "HOCUS511",
            f"dependencies must be an array with at most {MAX_DEPENDENCIES} entries.",
        )
    uris: set[str] = set()
    for index, dependency in enumerate(value):
        normalized = _validate_source(
            dependency, f"dependencies[{index}]", allow_kinds={"module"}
        )
        if normalized["uri"] in uris:
            raise BundleValidationError(
                "HOCUS512", "Dependency source URIs must be unique.",
                details={"uri": normalized["uri"]},
            )
        uris.add(normalized["uri"])
    return uris


def _validate_source(value: Any, label: str, *, allow_kinds: set[str]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"uri", "digest", "kind"}:
        raise BundleValidationError("HOCUS518", f"{label} has an invalid source-record shape.")
    uri = value.get("uri")
    kind = value.get("kind")
    if not isinstance(uri, str) or not uri or len(uri) > 4096 or "://" not in uri:
        raise BundleValidationError("HOCUS518", f"{label}.uri must be a bounded canonical URI.")
    if kind not in allow_kinds:
        raise BundleValidationError("HOCUS518", f"{label}.kind is invalid.")
    digest = _require_digest(value.get("digest"), f"{label}.digest", "HOCUS518")
    return {"uri": uri, "digest": digest, "kind": kind}


def _validate_resolved_module_set(
    value: Any,
    *,
    sources: list[Any],
    project_uid: str | None,
    entry_source_uri: str,
    project_manifest_digest: str | None,
    project_lock_digest: str | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    keys = {
        "$schema", "kind", "schemaVersion", "languageVersion", "projectUid",
        "entrySourceUri", "projectManifestDigest", "projectLockDigest",
        "resolverPolicyDigest", "limits", "modules",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleValidationError("HOCUS512", "resolvedModuleSet has an invalid shape.")
    if (
        value["$schema"] != "hocuspocus://schemas/resolved-module-set/v1"
        or value["kind"] != "hocus_resolved_module_set"
        or value["schemaVersion"] != 1
        or value["languageVersion"] != MODULE_LANGUAGE_VERSION
        or value["projectUid"] != project_uid
        or value["entrySourceUri"] != entry_source_uri
        or value["projectManifestDigest"] != project_manifest_digest
        or value["projectLockDigest"] != project_lock_digest
    ):
        raise BundleValidationError("HOCUS512", "resolvedModuleSet envelope conflicts with its bundle.")
    _require_digest(value["resolverPolicyDigest"], "resolvedModuleSet.resolverPolicyDigest", "HOCUS512")
    limits = _validate_resolved_limits(value["limits"])
    modules = _validate_module_dependencies(
        value["modules"], sources, project_uid=project_uid or "", import_depth=limits["importDepth"]
    )
    if len(modules) > limits["moduleFiles"]:
        raise BundleValidationError("HOCUS512", "Resolved modules exceed the declared moduleFiles limit.")
    return modules, limits


def _validate_resolved_limits(value: Any) -> dict[str, int]:
    maxima = {
        "sourceBytesPerFile": 1_048_576,
        "aggregateSourceBytes": 8_388_608,
        "moduleFiles": 4096,
        "importDepth": 64,
        "instanceDepth": 64,
        "instances": 4096,
        "parametersPerModule": 256,
        "exportsPerModule": 256,
        "expandedNodes": 10_000,
        "aggregateCodeBytes": 4_194_304,
        "sourceMapEntries": 100_000,
        "diagnostics": 500,
    }
    if not isinstance(value, dict) or set(value) != set(maxima):
        raise BundleValidationError("HOCUS512", "resolvedModuleSet.limits has an invalid shape.")
    if any(type(value[key]) is not int or not 1 <= value[key] <= maximum for key, maximum in maxima.items()):
        raise BundleValidationError("HOCUS512", "resolvedModuleSet.limits exceeds the v1 contract.")
    return dict(value)


def _validate_module_dependencies(
    value: Any, sources: list[Any], *, project_uid: str, import_depth: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_DEPENDENCIES:
        raise BundleValidationError("HOCUS512", "resolvedModuleSet.modules must be a bounded array.")
    source_pairs = [
        (item.get("uri"), item.get("digest"))
        for item in sources
        if isinstance(item, dict) and item.get("kind") == "module"
    ]
    if source_pairs != sorted(source_pairs):
        raise BundleValidationError("HOCUS512", "Module source dependencies must be sorted by URI.")
    decoded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        decoded.append(_validate_module_dependency(item, index, seen, project_uid))
    if [(item["uri"], item["sourceDigest"]) for item in decoded] != sorted(set(source_pairs)):
        raise BundleValidationError(
            "HOCUS512", "Resolved modules must exactly match sorted module source dependencies."
        )
    known_uris = {item["uri"] for item in decoded}
    if any(child not in known_uris for item in decoded for child in item["dependencies"]):
        raise BundleValidationError("HOCUS512", "Resolved modules contain an unresolved dependency URI.")
    _validate_module_dag_and_digests(decoded, max_depth=import_depth)
    return decoded


def _validate_module_dependency(
    item: Any,
    index: int,
    seen: set[str],
    project_uid: str,
) -> dict[str, Any]:
    label = f"moduleDependencies[{index}]"
    expected_keys = {
        "uri", "moduleName", "relativePath", "origin", "ownerUid", "alias", "version",
        "moduleManifestDigest", "sourceDigest", "interfaceDigest", "transitiveDigest",
        "dependencies", "languageVersion",
    }
    if not isinstance(item, dict) or set(item) != expected_keys:
        raise BundleValidationError("HOCUS512", f"{label} has an invalid shape.")
    uri, uri_match = _validate_module_dependency_identity(item, label, seen)
    relative_path = _validate_module_dependency_content(item, label)
    _validate_module_dependency_provenance(item, label, uri_match, relative_path, project_uid)
    _validate_module_dependency_children(item["dependencies"], label, uri)
    return dict(item)


def _validate_module_dependency_identity(
    item: dict[str, Any],
    label: str,
    seen: set[str],
) -> tuple[str, Any]:
    uri = item["uri"]
    if not isinstance(uri, str) or len(uri) > 4096 or uri in seen:
        raise BundleValidationError("HOCUS512", f"{label}.uri must be a unique canonical module URI.")
    uri_match = _MODULE_URI_PATTERN.fullmatch(uri)
    if uri_match is None:
        raise BundleValidationError("HOCUS512", f"{label}.uri must be a unique canonical module URI.")
    seen.add(uri)
    return uri, uri_match


def _validate_module_dependency_content(item: dict[str, Any], label: str) -> str:
    for field in ("sourceDigest", "interfaceDigest", "transitiveDigest"):
        _require_digest(item[field], f"{label}.{field}", "HOCUS512")
    if item["languageVersion"] != MODULE_LANGUAGE_VERSION:
        raise BundleValidationError("HOCUS512", f"{label}.languageVersion is unsupported.")
    if (
        not isinstance(item["moduleName"], str)
        or len(item["moduleName"]) > 128
        or not _IDENTIFIER_PATTERN.fullmatch(item["moduleName"])
    ):
        raise BundleValidationError("HOCUS512", f"{label}.moduleName is invalid.")
    relative_path = item["relativePath"]
    if (
        not isinstance(relative_path, str)
        or not relative_path.endswith(".hocus")
        or relative_path.startswith(("/", "\\"))
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
    ):
        raise BundleValidationError("HOCUS512", f"{label}.relativePath is invalid.")
    if not isinstance(item["ownerUid"], str) or not _PROJECT_UID_PATTERN.fullmatch(item["ownerUid"]):
        raise BundleValidationError("HOCUS512", f"{label}.ownerUid is invalid.")
    return relative_path


def _validate_module_dependency_provenance(
    item: dict[str, Any],
    label: str,
    uri_match: Any,
    relative_path: str,
    project_uid: str,
) -> None:
    scheme, authority, uri_path = uri_match.groups()
    if uri_path != quote(relative_path, safe="/-._~") or authority != item["ownerUid"]:
        raise BundleValidationError("HOCUS512", f"{label} URI does not match ownerUid/relativePath.")
    if item["origin"] == "project":
        if scheme != "project" or authority != project_uid or any(
            item[field] is not None for field in ("alias", "version", "moduleManifestDigest")
        ):
            raise BundleValidationError("HOCUS512", f"{label} has invalid project provenance.")
        return
    if item["origin"] != "external_library":
        raise BundleValidationError("HOCUS512", f"{label}.origin is invalid.")
    if (
        scheme != "module"
        or not isinstance(item["alias"], str)
        or not _MODULE_ALIAS_PATTERN.fullmatch(item["alias"])
        or not isinstance(item["version"], str)
        or not _SEMVER_PATTERN.fullmatch(item["version"])
    ):
        raise BundleValidationError("HOCUS512", f"{label} has invalid external provenance.")
    _require_digest(item["moduleManifestDigest"], f"{label}.moduleManifestDigest", "HOCUS512")


def _validate_module_dependency_children(child_uris: Any, label: str, uri: str) -> None:
    if (
        not isinstance(child_uris, list)
        or len(child_uris) > MAX_DEPENDENCIES
        or child_uris != sorted(set(child_uris))
        or any(
            not isinstance(child, str) or _MODULE_URI_PATTERN.fullmatch(child) is None
            for child in child_uris
        )
        or uri in child_uris
    ):
        raise BundleValidationError("HOCUS512", f"{label}.dependencies must be sorted unique URIs.")


def _module_transitive_digest(item: dict[str, Any], by_uri: dict[str, dict[str, Any]]) -> str:
    """Hash the locked bottom-up module closure in the hocus-module-transitive-v1 domain."""

    payload = {
        "domain": _TRANSITIVE_DIGEST_DOMAIN,
        "uri": item["uri"],
        "sourceDigest": item["sourceDigest"],
        "interfaceDigest": item["interfaceDigest"],
        "dependencies": [
            {"uri": uri, "transitiveDigest": by_uri[uri]["transitiveDigest"]}
            for uri in item["dependencies"]
        ],
    }
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_module_dag_and_digests(items: list[dict[str, Any]], *, max_depth: int) -> None:
    by_uri = {item["uri"]: item for item in items}
    unresolved = {uri: len(item["dependencies"]) for uri, item in by_uri.items()}
    parents: dict[str, list[str]] = {uri: [] for uri in by_uri}
    for uri, item in by_uri.items():
        for child in item["dependencies"]:
            parents[child].append(uri)
    ready = sorted(uri for uri, count in unresolved.items() if count == 0)
    depths: dict[str, int] = {}
    processed = 0
    while ready:
        uri = ready.pop(0)
        item = by_uri[uri]
        depth = 1 + max((depths[child] for child in item["dependencies"]), default=0)
        if depth > max_depth:
            raise BundleValidationError("HOCUS512", "Resolved module import depth exceeds its declared limit.")
        depths[uri] = depth
        expected = _module_transitive_digest(item, by_uri)
        if not hmac.compare_digest(item["transitiveDigest"], expected):
            raise BundleValidationError(
                "HOCUS512", f"Resolved module transitiveDigest is invalid for {uri}.",
                details={"uri": uri, "expectedDigest": expected},
            )
        processed += 1
        for parent in sorted(parents[uri]):
            unresolved[parent] -= 1
            if unresolved[parent] == 0:
                ready.append(parent)
        ready.sort()
    if processed != len(items):
        raise BundleValidationError("HOCUS512", "Resolved module dependency graph contains a cycle.")


def _validate_catalog_constraints(value: Any) -> dict[str, Any]:
    keys = {"schemaVersion", "fingerprint", "contentDigest"}
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleValidationError("HOCUS513", "Bundle v0.2 requires an exact catalog constraint.")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise BundleValidationError("HOCUS513", "Catalog constraint schemaVersion must be 1.")
    _require_digest(value["fingerprint"], "catalogConstraints.fingerprint", "HOCUS513")
    _require_digest(value["contentDigest"], "catalogConstraints.contentDigest", "HOCUS513")
    return value


def _validate_semantic_resolution(
    value: Any, constraint: dict[str, Any], graph: dict[str, Any],
    *, require_module_provenance: bool = False,
) -> dict[str, Any]:
    from .bundle_semantic_validation import _validate_semantic_resolution as validate

    return validate(
        value, constraint, graph,
        require_module_provenance=require_module_provenance,
    )


def _validate_expansion_map(
    value: Any, module_dependencies: dict[str, dict[str, Any]], entry_source_uri: str,
    graph: dict[str, Any], limits: dict[str, int],
) -> None:
    from .bundle_semantic_validation import _validate_expansion_map as validate

    validate(value, module_dependencies, entry_source_uri, graph, limits)


def _required_expansion_pointers(graph: dict[str, Any]) -> set[str]:
    from .bundle_graph_validation import required_expansion_pointers

    return required_expansion_pointers(graph)


def _validate_graph_spec(
    graph: dict[str, Any], *, graph_spec_version: str,
    module_dependencies: dict[str, dict[str, Any]] | None = None,
    entry_source_uri: str | None = None,
    module_limits: dict[str, int] | None = None,
) -> None:
    from .bundle_graph_validation import validate_graph_spec

    validate_graph_spec(
        graph, graph_spec_version=graph_spec_version,
        module_dependencies=module_dependencies, entry_source_uri=entry_source_uri,
        module_limits=module_limits,
    )


def _validate_span(value: Any, label: str) -> None:
    from .bundle_graph_validation import validate_span

    validate_span(value, label)


def _validate_declared_source_uris(value: Any, allowed: set[str]) -> None:
    from .bundle_graph_validation import validate_declared_source_uris

    validate_declared_source_uris(value, allowed)


def _required_capabilities(graph_spec: dict[str, Any]) -> list[str]:
    from .bundle_graph_validation import required_capabilities

    return required_capabilities(graph_spec)


def _validate_complexity(value: Any, *, max_values: int = MAX_BUNDLE_VALUES) -> None:
    from .bundle_graph_validation import validate_complexity

    validate_complexity(value, max_values=max_values)


def _require_digest(value: Any, label: str, code: str) -> str:
    from .bundle_graph_validation import require_digest

    return require_digest(value, label, code)


def _require_equal(payload: dict[str, Any], key: str, expected: Any, code: str) -> None:
    from .bundle_graph_validation import require_equal

    require_equal(payload, key, expected, code)


def _canonical_json(payload: dict[str, Any]) -> str:
    from .bundle_graph_validation import canonical_json

    return canonical_json(payload)
