"""Version-lane registry and decode-only HocusScript carrier scaffolds."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .resolved_modules import canonical_module_uri
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$"); _JSON_POINTER = re.compile(r"^(?:/(?:[^~/]|~0|~1)*)*$")
_SOURCE_URI = re.compile(r"^hocus-(?:project|module)://[^\s]+$"); _UID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"); _SEED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALIAS = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SEMVER = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))"
    r"(?:\.(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_MAX_JSON_BYTES = 64 * 1024 * 1024; _MAX_JSON_VALUES = 500_000; _MAX_JSON_DEPTH = 128
_EXPANSION_STACK_DIGEST_DOMAIN = "hocus-expansion-stack-v1"; _CONTROL_STACK_DIGEST_DOMAIN = "hocus-control-stack-v1"
_TRANSITIVE_DIGEST_DOMAIN = "hocus-module-transitive-v1"
class CarrierContractError(ValueError):
    """Raised when a carrier version or decode-only envelope is invalid."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class CarrierContract:
    """One exact, non-interchangeable HocusScript carrier compatibility row."""

    language_version: str
    compiler_version: str
    graph_spec_version: str
    expansion_map_version: int
    resolved_module_set_version: int
    project_manifest_version: int
    project_lock_version: int
    module_manifest_version: int
    bundle_version: str
    resolver_policy_version: int
    resolver_interface_version: int
    dispatch_enabled: bool


STATIC_CARRIER_CONTRACT = CarrierContract(
    language_version="0.2",
    compiler_version="0.4.0",
    graph_spec_version="0.3",
    expansion_map_version=1,
    resolved_module_set_version=1,
    project_manifest_version=3,
    project_lock_version=3,
    module_manifest_version=1,
    bundle_version="0.3",
    resolver_policy_version=1,
    resolver_interface_version=1,
    dispatch_enabled=False,
)

CONTROL_CARRIER_CONTRACT = CarrierContract(
    language_version="0.3",
    compiler_version="0.5.0",
    graph_spec_version="0.4",
    expansion_map_version=2,
    resolved_module_set_version=2,
    project_manifest_version=4,
    project_lock_version=4,
    module_manifest_version=2,
    bundle_version="0.4",
    resolver_policy_version=1,
    resolver_interface_version=1,
    dispatch_enabled=True,
)

CONTROL_LANGUAGE_VERSION = CONTROL_CARRIER_CONTRACT.language_version; CONTROL_COMPILER_VERSION = CONTROL_CARRIER_CONTRACT.compiler_version
CONTROL_GRAPH_SPEC_VERSION = CONTROL_CARRIER_CONTRACT.graph_spec_version; CONTROL_EXPANSION_MAP_VERSION = CONTROL_CARRIER_CONTRACT.expansion_map_version
CONTROL_RESOLVED_MODULE_SET_VERSION = CONTROL_CARRIER_CONTRACT.resolved_module_set_version; CONTROL_PROJECT_MANIFEST_VERSION = CONTROL_CARRIER_CONTRACT.project_manifest_version
CONTROL_PROJECT_LOCK_VERSION = CONTROL_CARRIER_CONTRACT.project_lock_version; CONTROL_MODULE_MANIFEST_VERSION = CONTROL_CARRIER_CONTRACT.module_manifest_version
CONTROL_BUNDLE_VERSION = CONTROL_CARRIER_CONTRACT.bundle_version

CARRIER_CONTRACTS = (STATIC_CARRIER_CONTRACT, CONTROL_CARRIER_CONTRACT)


def _index(attribute: str) -> Mapping[Any, CarrierContract]:
    return MappingProxyType({getattr(row, attribute): row for row in CARRIER_CONTRACTS})


CARRIER_CONTRACTS_BY_LANGUAGE = _index("language_version")
CARRIER_CONTRACTS_BY_COMPILER = _index("compiler_version")
CARRIER_CONTRACTS_BY_GRAPH_SPEC = _index("graph_spec_version")
CARRIER_CONTRACTS_BY_EXPANSION_MAP = _index("expansion_map_version")
CARRIER_CONTRACTS_BY_RESOLVED_MODULE_SET = _index("resolved_module_set_version")
CARRIER_CONTRACTS_BY_PROJECT_MANIFEST = _index("project_manifest_version")
CARRIER_CONTRACTS_BY_PROJECT_LOCK = _index("project_lock_version")
CARRIER_CONTRACTS_BY_MODULE_MANIFEST = _index("module_manifest_version")
CARRIER_CONTRACTS_BY_BUNDLE = _index("bundle_version")


def _lookup(index: Mapping[Any, CarrierContract], value: Any, label: str) -> CarrierContract:
    try:
        return index[value]
    except (KeyError, TypeError) as exc:
        raise CarrierContractError(
            "HOCUS490", f"Unsupported HocusScript {label}: {value!r}."
        ) from exc


def contract_for_language(version: str) -> CarrierContract:
    """Return the one exact carrier row for a language version."""

    return _lookup(CARRIER_CONTRACTS_BY_LANGUAGE, version, "language version")


def contract_for_compiler(version: str) -> CarrierContract:
    """Return the one exact carrier row for a compiler version."""

    return _lookup(CARRIER_CONTRACTS_BY_COMPILER, version, "compiler version")


def contract_for_graph_spec(version: str) -> CarrierContract:
    """Return the one exact carrier row for a GraphSpec version."""

    return _lookup(CARRIER_CONTRACTS_BY_GRAPH_SPEC, version, "GraphSpec version")


def contract_for_expansion_map(version: int) -> CarrierContract:
    """Return the one exact carrier row for an expansion-map version."""

    if type(version) is not int:
        raise CarrierContractError("HOCUS490", "Expansion-map version must be an integer.")
    return _lookup(CARRIER_CONTRACTS_BY_EXPANSION_MAP, version, "expansion-map version")


def contract_for_resolved_module_set(version: int) -> CarrierContract:
    """Return the one exact carrier row for a resolved-set version."""

    if type(version) is not int:
        raise CarrierContractError("HOCUS490", "Resolved-set version must be an integer.")
    return _lookup(CARRIER_CONTRACTS_BY_RESOLVED_MODULE_SET, version, "resolved-set version")


def contract_for_project_manifest(version: int) -> CarrierContract:
    """Return the one exact carrier row for a project-manifest version."""

    if type(version) is not int:
        raise CarrierContractError("HOCUS490", "Project-manifest version must be an integer.")
    return _lookup(CARRIER_CONTRACTS_BY_PROJECT_MANIFEST, version, "project-manifest version")


def contract_for_project_lock(version: int) -> CarrierContract:
    """Return the one exact carrier row for a project-lock version."""

    if type(version) is not int:
        raise CarrierContractError("HOCUS490", "Project-lock version must be an integer.")
    return _lookup(CARRIER_CONTRACTS_BY_PROJECT_LOCK, version, "project-lock version")


def contract_for_module_manifest(version: int) -> CarrierContract:
    """Return the one exact carrier row for a module-manifest version."""

    if type(version) is not int:
        raise CarrierContractError("HOCUS490", "Module-manifest version must be an integer.")
    return _lookup(CARRIER_CONTRACTS_BY_MODULE_MANIFEST, version, "module-manifest version")


def contract_for_bundle(version: str) -> CarrierContract:
    """Return the one exact carrier row for a compiled-bundle version."""

    return _lookup(CARRIER_CONTRACTS_BY_BUNDLE, version, "compiled-bundle version")


def require_carrier_contract(
    *, language_version: str, compiler_version: str, graph_spec_version: str,
    expansion_map_version: int, resolved_module_set_version: int,
    project_manifest_version: int, project_lock_version: int,
    module_manifest_version: int, bundle_version: str,
    resolver_policy_version: int = 1, resolver_interface_version: int = 1,
) -> CarrierContract:
    """Require every supplied carrier version to identify the same exact row."""

    supplied = {
        "language_version": language_version,
        "compiler_version": compiler_version,
        "graph_spec_version": graph_spec_version,
        "expansion_map_version": expansion_map_version,
        "resolved_module_set_version": resolved_module_set_version,
        "project_manifest_version": project_manifest_version,
        "project_lock_version": project_lock_version,
        "module_manifest_version": module_manifest_version,
        "bundle_version": bundle_version,
        "resolver_policy_version": resolver_policy_version,
        "resolver_interface_version": resolver_interface_version,
    }
    row = contract_for_language(language_version)
    if any(getattr(row, name) != value for name, value in supplied.items()):
        raise CarrierContractError(
            "HOCUS490", "HocusScript carrier versions are mixed or unsupported.",
            details={"languageVersion": language_version},
        )
    return row


CONTROL_RESOLVED_LIMIT_MAXIMA = MappingProxyType({
    "sourceBytesPerFile": 1_048_576,
    "aggregateSourceBytes": 8_388_608,
    "moduleFiles": 4_096,
    "importDepth": 64,
    "instanceDepth": 64,
    "instances": 4_096,
    "parametersPerModule": 256,
    "exportsPerModule": 256,
    "expandedNodes": 10_000,
    "aggregateCodeBytes": 4_194_304,
    "sourceMapEntries": 100_000,
    "diagnostics": 500,
    "perFoldIterations": 4_096,
    "aggregateIterations": 100_000,
})


def decode_control_graph_spec_envelope(
    value: Any, *, resolved_limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Decode the strict GraphSpec 0.4 envelope without interpreting its graph."""

    required_limits = {
        "expandedNodes", "sourceMapEntries", "instances", "instanceDepth",
        "aggregateCodeBytes", "perFoldIterations", "aggregateIterations",
    }
    if resolved_limits is not None and (
        not isinstance(resolved_limits, Mapping)
        or not required_limits.issubset(resolved_limits)
        or any(type(resolved_limits[name]) is not int or resolved_limits[name] < 1 for name in required_limits)
    ):
        _fail("HOCUS491", "GraphSpec resolved limits are malformed.")

    graph = _decode_json_object(value, "GraphSpec 0.4", "HOCUS491")
    _exact_keys(graph, {
        "$schema", "kind", "graphSpecVersion", "languageVersion", "name", "target",
        "category", "mode", "expectedRevision", "ownership", "externalNodes", "nodes",
        "display", "render", "output", "layout", "span", "fieldSpans", "expansionMap",
    }, "GraphSpec 0.4", "HOCUS491")
    _equal(graph, "$schema", "hocuspocus://schemas/graph-spec/v0.4", "HOCUS491")
    _equal(graph, "kind", "graph_spec", "HOCUS491")
    _equal(graph, "graphSpecVersion", "0.4", "HOCUS491")
    _equal(graph, "languageVersion", "0.3", "HOCUS491")
    _string(graph["name"], "GraphSpec.name", "HOCUS491", pattern=_IDENTIFIER)
    _string(graph["target"], "GraphSpec.target", "HOCUS491", maximum=4096)
    _nullable_string(graph["category"], "GraphSpec.category", "HOCUS491")
    if graph["mode"] not in {"merge", "reconcile"}:
        _fail("HOCUS491", "GraphSpec.mode is invalid.")
    if graph["expectedRevision"] is not None and (
        type(graph["expectedRevision"]) is not int or graph["expectedRevision"] < 0
    ):
        _fail("HOCUS491", "GraphSpec.expectedRevision must be null or a nonnegative integer.")
    _nullable_string(graph["ownership"], "GraphSpec.ownership", "HOCUS491")
    expanded_nodes = (
        resolved_limits["expandedNodes"] if resolved_limits is not None else 10_000
    )
    _object_array(graph["externalNodes"], "GraphSpec.externalNodes", 10_000, "HOCUS491")
    _object_array(graph["nodes"], "GraphSpec.nodes", expanded_nodes, "HOCUS491")
    for field in ("display", "render", "output"):
        _nullable_string(graph[field], f"GraphSpec.{field}", "HOCUS491")
    if graph["layout"] not in {None, "auto"}:
        _fail("HOCUS491", "GraphSpec.layout is invalid.")
    if not isinstance(graph["span"], dict) or not isinstance(graph["fieldSpans"], dict):
        _fail("HOCUS491", "GraphSpec span carriers must be objects.")
    graph["expansionMap"] = decode_control_expansion_map_envelope(
        graph["expansionMap"],
        entry_source_uri=None,
        source_map_entries=(
            resolved_limits["sourceMapEntries"] if resolved_limits is not None else 100_000
        ),
        instances=(resolved_limits["instances"] if resolved_limits is not None else 10_000),
        instance_depth=(
            resolved_limits["instanceDepth"] if resolved_limits is not None else 64
        ),
        per_fold_iterations=(
            resolved_limits["perFoldIterations"] if resolved_limits is not None else 4_096
        ),
        aggregate_iterations=(
            resolved_limits["aggregateIterations"] if resolved_limits is not None else 100_000
        ),
    )
    _validate_expansion_surface(graph)
    if resolved_limits is not None:
        code_bytes = _graph_code_bytes(graph)
        if code_bytes > resolved_limits["aggregateCodeBytes"]:
            _fail("HOCUS491", "GraphSpec embedded code exceeds the resolved limit.")
    return graph


def decode_control_expansion_map_envelope(
    value: Any, *, entry_source_uri: str | None = None,
    source_map_entries: int = 100_000, instances: int = 10_000,
    instance_depth: int = 64, per_fold_iterations: int = 4_096,
    aggregate_iterations: int = 100_000,
) -> dict[str, Any]:
    """Decode expansion-map v2 and validate its stack/reference envelope."""

    expansion = _decode_json_object(value, "expansion-map v2", "HOCUS492")
    _exact_keys(expansion, {
        "$schema", "kind", "schemaVersion", "graphSpecVersion", "entrySourceUri",
        "stacks", "controlStacks", "mappings",
    }, "expansion-map v2", "HOCUS492")
    _equal(expansion, "$schema", "hocuspocus://schemas/expansion-map/v2", "HOCUS492")
    _equal(expansion, "kind", "hocus_expansion_map", "HOCUS492")
    _exact_int(expansion["schemaVersion"], 2, "expansionMap.schemaVersion", "HOCUS492")
    _equal(expansion, "graphSpecVersion", "0.4", "HOCUS492")
    uri = _source_uri(expansion["entrySourceUri"], "expansionMap.entrySourceUri", "HOCUS492")
    if entry_source_uri is not None and uri != entry_source_uri:
        _fail("HOCUS492", "Expansion-map entry source conflicts with its enclosing carrier.")
    _validate_expansion_bounds(
        source_map_entries, instances, instance_depth, per_fold_iterations,
        aggregate_iterations,
    )
    stack_ids = _validate_module_stacks(expansion["stacks"], instances, instance_depth)
    control_ids = _validate_control_stacks(
        expansion["controlStacks"], source_map_entries, instance_depth,
        per_fold_iterations, aggregate_iterations,
    )
    _validate_expansion_mappings(
        expansion["mappings"], source_map_entries, stack_ids, control_ids,
    )
    return expansion


def _validate_expansion_bounds(*bounds: int) -> None:
    labels = (
        "source_map_entries", "instances", "instance_depth",
        "per_fold_iterations", "aggregate_iterations",
    )
    for label, maximum in zip(labels, bounds):
        if type(maximum) is not int or maximum < 1:
            _fail("HOCUS492", f"{label} bound must be a positive integer.")


def _validate_expansion_mappings(
    mappings: Any,
    source_map_entries: int,
    stack_ids: list[str],
    control_ids: list[str],
) -> None:
    if not isinstance(mappings, list) or len(mappings) > source_map_entries:
        _fail("HOCUS492", "Expansion mappings exceed their declared bound.")
    pointers: list[str] = []
    origin_ids: set[str] = set()
    referenced_stacks: set[str] = set()
    referenced_controls: set[str] = set(); known_stacks, known_controls = set(stack_ids), set(control_ids)
    for index, mapping in enumerate(mappings):
        pointer, origin_id, stack_id, control_id = _validate_expansion_mapping(
            mapping, index, known_stacks, known_controls,
        )
        if origin_id in origin_ids:
            _fail(
                "HOCUS492",
                f"expansionMap.mappings[{index}].originId is invalid or duplicated.",
            )
        origin_ids.add(origin_id)
        pointers.append(pointer)
        if stack_id is not None:
            referenced_stacks.add(stack_id)
        if control_id is not None:
            referenced_controls.add(control_id)
    if pointers != sorted(set(pointers)):
        _fail("HOCUS492", "Expansion mappings must be uniquely sorted by generatedPointer.")
    if referenced_stacks != known_stacks or referenced_controls != known_controls:
        _fail("HOCUS492", "Expansion stacks and control stacks must all be referenced.")


def _validate_expansion_mapping(
    mapping: Any, index: int, stack_ids: set[str], control_ids: set[str],
) -> tuple[str, str, str | None, str | None]:
    label = f"expansionMap.mappings[{index}]"
    if not isinstance(mapping, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(mapping, {
        "originId", "generatedPointer", "originKind", "primarySpan", "relatedOrigins",
        "stackId", "controlStackId",
    }, label, "HOCUS492")
    origin_id = _digest(mapping["originId"], f"{label}.originId", "HOCUS492")
    pointer = _string(
        mapping["generatedPointer"], f"{label}.generatedPointer", "HOCUS492",
        maximum=8192, pattern=_JSON_POINTER, allow_empty=True,
    )
    if mapping["originKind"] not in {"definition", "argument", "export", "synthetic"}:
        _fail("HOCUS492", f"{label}.originKind is invalid.")
    _span(mapping["primarySpan"], f"{label}.primarySpan")
    _validate_related_origins(mapping["relatedOrigins"], label)
    stack_id = _nullable_digest(mapping["stackId"], f"{label}.stackId", "HOCUS492")
    control_id = _nullable_digest(
        mapping["controlStackId"], f"{label}.controlStackId", "HOCUS492"
    )
    if stack_id is not None and stack_id not in stack_ids:
        _fail("HOCUS492", f"{label}.stackId references an unknown stack.")
    if control_id is not None and control_id not in control_ids:
        _fail("HOCUS492", f"{label}.controlStackId references an unknown control stack.")
    expected_origin_id = _content_digest({
        key: mapping[key] for key in sorted(mapping) if key != "originId"
    })
    if not hmac.compare_digest(origin_id, expected_origin_id):
        _fail("HOCUS492", f"{label}.originId is invalid.")
    return pointer, origin_id, stack_id, control_id


def _validate_related_origins(value: Any, label: str) -> None:
    if not isinstance(value, list) or len(value) > 16:
        _fail("HOCUS492", f"{label}.relatedOrigins is invalid.")
    valid_roles = {
        "definition", "parameter_declaration", "argument", "export", "instance",
        "control_declaration", "condition", "fold_count", "carry_initializer", "yield",
    }
    for index, origin in enumerate(value):
        related_label = f"{label}.relatedOrigins[{index}]"
        if not isinstance(origin, dict):
            _fail("HOCUS492", f"{related_label} must be an object.")
        _exact_keys(origin, {"role", "span"}, related_label, "HOCUS492")
        if origin["role"] not in valid_roles:
            _fail("HOCUS492", f"{related_label}.role is invalid.")
        _span(origin["span"], f"{related_label}.span")


def decode_control_resolved_module_set_envelope(value: Any) -> dict[str, Any]:
    """Decode resolved-module-set v2 and validate ordering, limits, and identities."""

    resolved = _decode_json_object(value, "resolved-module-set v2", "HOCUS493")
    _exact_keys(resolved, {
        "$schema", "kind", "schemaVersion", "languageVersion", "projectUid",
        "entrySourceUri", "projectManifestDigest", "projectLockDigest",
        "resolverPolicyDigest", "limits", "modules",
    }, "resolved-module-set v2", "HOCUS493")
    _equal(resolved, "$schema", "hocuspocus://schemas/resolved-module-set/v2", "HOCUS493")
    _equal(resolved, "kind", "hocus_resolved_module_set", "HOCUS493")
    _exact_int(resolved["schemaVersion"], 2, "resolvedModuleSet.schemaVersion", "HOCUS493")
    _equal(resolved, "languageVersion", "0.3", "HOCUS493")
    uid = _string(resolved["projectUid"], "resolvedModuleSet.projectUid", "HOCUS493", pattern=_UID)
    entry_uri = _source_uri(resolved["entrySourceUri"], "resolvedModuleSet.entrySourceUri", "HOCUS493")
    if not entry_uri.startswith(f"hocus-project://{uid}/"):
        _fail("HOCUS493", "Resolved-set entrySourceUri conflicts with projectUid.")
    for field in ("projectManifestDigest", "projectLockDigest", "resolverPolicyDigest"):
        _digest(resolved[field], f"resolvedModuleSet.{field}", "HOCUS493")
    limits = _validate_resolved_limits(resolved["limits"])
    modules = resolved["modules"]
    if not isinstance(modules, list) or len(modules) > limits["moduleFiles"]:
        _fail("HOCUS493", "resolvedModuleSet.modules exceeds its declared bound.")
    uris: list[str] = []
    dependencies_by_uri: dict[str, list[str]] = {}
    for index, module in enumerate(modules):
        uri, normalized = _validate_resolved_module(
            module, index, uid, limits["moduleFiles"],
        )
        uris.append(uri)
        dependencies_by_uri[uri] = normalized
    if uris != sorted(set(uris)):
        _fail("HOCUS493", "Resolved modules must be uniquely sorted by URI.")
    known = set(uris)
    for uri, dependencies in dependencies_by_uri.items():
        unknown = set(dependencies) - known
        if unknown or uri in dependencies:
            _fail("HOCUS493", "Resolved module dependencies contain an invalid cross-link.")
    _validate_module_dag_and_digests(
        {item["uri"]: item for item in modules},
        max_depth=limits["importDepth"],
    )
    return resolved


def _validate_resolved_limits(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        _fail("HOCUS493", "resolvedModuleSet.limits must be an object.")
    _exact_keys(
        value, set(CONTROL_RESOLVED_LIMIT_MAXIMA),
        "resolvedModuleSet.limits", "HOCUS493",
    )
    for name, maximum in CONTROL_RESOLVED_LIMIT_MAXIMA.items():
        actual = value[name]
        if type(actual) is not int or not 1 <= actual <= maximum:
            _fail("HOCUS493", f"resolvedModuleSet.limits.{name} exceeds its fixed maximum.")
    return value


def _validate_resolved_module(
    module: Any, index: int, project_uid: str, module_limit: int,
) -> tuple[str, list[str]]:
    label = f"resolvedModuleSet.modules[{index}]"
    if not isinstance(module, dict):
        _fail("HOCUS493", f"{label} must be an object.")
    _exact_keys(module, {
        "uri", "moduleName", "relativePath", "origin", "ownerUid", "alias", "version",
        "moduleManifestDigest", "sourceDigest", "interfaceDigest", "transitiveDigest",
        "dependencies", "languageVersion",
    }, label, "HOCUS493")
    uri = _source_uri(module["uri"], f"{label}.uri", "HOCUS493")
    identity = canonical_module_uri(uri)
    if identity is None:
        _fail("HOCUS493", f"{label}.uri is not canonical.")
    scheme, authority, uri_path = identity
    _string(module["moduleName"], f"{label}.moduleName", "HOCUS493", pattern=_IDENTIFIER)
    relative_path = _string(
        module["relativePath"], f"{label}.relativePath", "HOCUS493", maximum=1024,
    )
    owner_uid = _string(module["ownerUid"], f"{label}.ownerUid", "HOCUS493", pattern=_UID)
    if uri_path != relative_path or authority != owner_uid:
        _fail("HOCUS493", f"{label}.uri conflicts with ownerUid or relativePath.")
    _validate_resolved_origin(module, label, scheme, owner_uid, project_uid)
    for field in ("sourceDigest", "interfaceDigest", "transitiveDigest"):
        _digest(module[field], f"{label}.{field}", "HOCUS493")
    _equal(module, "languageVersion", "0.3", "HOCUS493")
    dependencies = module["dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) > module_limit:
        _fail("HOCUS493", f"{label}.dependencies is invalid.")
    normalized = [
        _source_uri(item, f"{label}.dependencies", "HOCUS493") for item in dependencies
    ]
    if normalized != sorted(set(normalized)):
        _fail("HOCUS493", f"{label}.dependencies must be uniquely sorted by URI.")
    return uri, normalized


def _validate_resolved_origin(
    module: dict[str, Any], label: str, scheme: str, owner_uid: str, project_uid: str,
) -> None:
    if module["origin"] not in {"project", "external_library"}:
        _fail("HOCUS493", f"{label}.origin is invalid.")
    if module["origin"] == "project":
        if (
            scheme != "project" or owner_uid != project_uid
            or module["alias"] is not None or module["version"] is not None
            or module["moduleManifestDigest"] is not None
        ):
            _fail("HOCUS493", f"{label} has inconsistent project origin fields.")
        return
    if (
        scheme != "module"
        or type(module["alias"]) is not str
        or _ALIAS.fullmatch(module["alias"]) is None
        or type(module["version"]) is not str
        or _SEMVER.fullmatch(module["version"]) is None
    ):
        _fail("HOCUS493", f"{label} has inconsistent external origin fields.")
    _digest(module["moduleManifestDigest"], f"{label}.moduleManifestDigest", "HOCUS493")


def decode_control_bundle_envelope(value: Any) -> dict[str, Any]:
    """Decode and authenticate Bundle 0.4 without enabling its consumption."""

    bundle = _decode_json_object(value, "compiled bundle 0.4", "HOCUS494")
    _exact_keys(bundle, {
        "$schema", "kind", "bundleVersion", "bundleDigest", "compilerVersion",
        "graphSpecVersion", "languageVersion", "portable", "projectUid",
        "projectManifestDigest", "projectLockDigest", "entrySource", "dependencies",
        "catalogConstraints", "requiredCapabilities", "sourceMaps", "graphSpec",
        "semanticResolution", "resolvedModuleSet",
    }, "compiled bundle 0.4", "HOCUS494")
    _equal(bundle, "$schema", "hocuspocus://schemas/compiled-bundle/v0.4", "HOCUS494")
    _equal(bundle, "kind", "hocus_compiled_bundle", "HOCUS494")
    _equal(bundle, "bundleVersion", "0.4", "HOCUS494")
    _equal(bundle, "compilerVersion", "0.5.0", "HOCUS494")
    _equal(bundle, "graphSpecVersion", "0.4", "HOCUS494")
    _equal(bundle, "languageVersion", "0.3", "HOCUS494")
    if bundle["portable"] is not True:
        _fail("HOCUS494", "Bundle 0.4 portable must be the exact boolean true.")
    uid = _string(bundle["projectUid"], "bundle.projectUid", "HOCUS494", pattern=_UID)
    for field in ("projectManifestDigest", "projectLockDigest"):
        _digest(bundle[field], f"bundle.{field}", "HOCUS494")
    declared_digest = _digest(bundle["bundleDigest"], "bundle.bundleDigest", "HOCUS494")
    unsigned = dict(bundle)
    del unsigned["bundleDigest"]
    actual_digest = "sha256:" + hashlib.sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(declared_digest, actual_digest):
        _fail("HOCUS494", "Bundle digest does not match canonical Bundle 0.4 content.")
    entry, resolved = _validate_bundle_sources(bundle, uid)
    graph = _validate_bundle_graph(bundle, entry, resolved)
    catalog = _validate_bundle_catalog(bundle)
    capabilities = _validate_bundle_capabilities(bundle)
    semantic = _validate_bundle_semantic(bundle, catalog, graph)
    if semantic["requiredCapabilities"] != capabilities:
        _fail("HOCUS494", "Bundle capabilities conflict with semanticResolution.")
    if len(semantic["diagnostics"]) > resolved["limits"]["diagnostics"]:
        _fail("HOCUS494", "Bundle diagnostics exceed the resolved limit.")
    return bundle


def _validate_bundle_sources(
    bundle: dict[str, Any], uid: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = _source_record(bundle["entrySource"], "bundle.entrySource", {"project_file"})
    if not entry["uri"].startswith(f"hocus-project://{uid}/"):
        _fail("HOCUS494", "Bundle entrySource conflicts with projectUid.")
    dependencies_value = bundle["dependencies"]
    if not isinstance(dependencies_value, list) or len(dependencies_value) > 4_096:
        _fail("HOCUS494", "Bundle dependencies are invalid.")
    dependencies = [
        _source_record(item, f"bundle.dependencies[{index}]", {"module"})
        for index, item in enumerate(dependencies_value)
    ]
    dependency_uris = [item["uri"] for item in dependencies]
    if dependency_uris != sorted(set(dependency_uris)):
        _fail("HOCUS494", "Bundle dependencies must be uniquely sorted by URI.")

    resolved = decode_control_resolved_module_set_envelope(bundle["resolvedModuleSet"])
    if (
        resolved["projectUid"] != uid
        or resolved["entrySourceUri"] != entry["uri"]
        or resolved["projectManifestDigest"] != bundle["projectManifestDigest"]
        or resolved["projectLockDigest"] != bundle["projectLockDigest"]
    ):
        _fail("HOCUS494", "Bundle and resolved-set identities conflict.")
    expected_dependencies = [
        {"uri": item["uri"], "digest": item["sourceDigest"], "kind": "module"}
        for item in resolved["modules"]
    ]
    if dependencies != expected_dependencies:
        _fail("HOCUS494", "Bundle dependency sources conflict with the resolved set.")
    return entry, resolved


def _validate_bundle_graph(
    bundle: dict[str, Any], entry: dict[str, Any], resolved: dict[str, Any],
) -> dict[str, Any]:
    graph = decode_control_graph_spec_envelope(
        bundle["graphSpec"], resolved_limits=resolved["limits"],
    )
    expansion = graph["expansionMap"]
    if expansion["entrySourceUri"] != entry["uri"]:
        _fail("HOCUS494", "Bundle GraphSpec expansion entry conflicts with entrySource.")
    _validate_expansion_module_provenance(expansion, resolved)
    source_maps = bundle["sourceMaps"]
    if not isinstance(source_maps, dict):
        _fail("HOCUS494", "Bundle sourceMaps must be an object.")
    _exact_keys(source_maps, {
        "format", "entrySourceUri", "embeddedInGraphSpec", "expansionMapVersion",
        "expansionMapDigest",
    }, "bundle.sourceMaps", "HOCUS494")
    expected_expansion_digest = "sha256:" + hashlib.sha256(
        _canonical_json(expansion).encode("utf-8")
    ).hexdigest()
    expected_source_maps = {
        "format": "graph-spec-expansion-v2",
        "entrySourceUri": entry["uri"],
        "embeddedInGraphSpec": True,
        "expansionMapVersion": 2,
        "expansionMapDigest": expected_expansion_digest,
    }
    if source_maps != expected_source_maps:
        _fail("HOCUS494", "Bundle sourceMaps conflicts with its embedded expansion map.")
    return graph


def _validate_bundle_catalog(bundle: dict[str, Any]) -> dict[str, Any]:
    catalog = bundle["catalogConstraints"]
    if not isinstance(catalog, dict):
        _fail("HOCUS494", "Bundle catalogConstraints must be an object.")
    _exact_keys(catalog, {"schemaVersion", "fingerprint", "contentDigest"}, "bundle.catalogConstraints", "HOCUS494")
    _exact_int(catalog["schemaVersion"], 1, "catalogConstraints.schemaVersion", "HOCUS494")
    _digest(catalog["fingerprint"], "catalogConstraints.fingerprint", "HOCUS494")
    _digest(catalog["contentDigest"], "catalogConstraints.contentDigest", "HOCUS494")
    return catalog


def _validate_bundle_capabilities(bundle: dict[str, Any]) -> list[str]:
    capabilities = bundle["requiredCapabilities"]
    if (
        not isinstance(capabilities, list)
        or not 1 <= len(capabilities) <= 2
        or capabilities != sorted(set(capabilities))
        or any(item not in {"edit_scene", "run_code"} for item in capabilities)
    ):
        _fail("HOCUS494", "Bundle requiredCapabilities is invalid.")
    return capabilities


def _validate_bundle_semantic(
    bundle: dict[str, Any], catalog: dict[str, Any], graph: dict[str, Any],
) -> dict[str, Any]:
    try:
        from .bundle import BundleValidationError, _validate_semantic_resolution

        semantic = _validate_semantic_resolution(
            bundle["semanticResolution"], catalog, graph,
            require_module_provenance=True,
        )
    except (BundleValidationError, KeyError, IndexError, TypeError, ValueError) as exc:
        _fail("HOCUS494", f"Bundle semanticResolution is invalid: {exc}")
    return semantic


def _validate_module_stacks(value: Any, instances: int, depth: int) -> list[str]:
    if not isinstance(value, list) or len(value) > instances:
        _fail("HOCUS492", "Expansion stacks exceed their declared bound.")
    ids: list[str] = []
    instance_paths: set[tuple[str, ...]] = set()
    for index, stack in enumerate(value):
        ids.append(_validate_module_stack(stack, index, depth, instance_paths))
    if ids != sorted(set(ids)):
        _fail("HOCUS492", "Expansion stacks must be uniquely sorted by stackId.")
    if len(instance_paths) > instances:
        _fail("HOCUS492", "Expansion stacks exceed the declared module-instance limit.")
    return ids


def _validate_module_stack(
    stack: Any, index: int, depth: int, instance_paths: set[tuple[str, ...]],
) -> str:
    label = f"expansionMap.stacks[{index}]"
    if not isinstance(stack, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(stack, {"stackId", "frames"}, label, "HOCUS492")
    stack_id = _digest(stack["stackId"], f"{label}.stackId", "HOCUS492")
    frames = stack["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= depth:
        _fail("HOCUS492", f"{label}.frames exceeds its declared bound.")
    for frame_index, frame in enumerate(frames):
        _validate_module_frame(frame, f"{label}.frames[{frame_index}]", depth, instance_paths)
    expected_stack_id = _content_digest({
        "domain": _EXPANSION_STACK_DIGEST_DOMAIN, "frames": frames,
    })
    if not hmac.compare_digest(stack_id, expected_stack_id):
        _fail("HOCUS492", f"{label}.stackId does not match its frames.")
    return stack_id


def _validate_module_frame(
    frame: Any, label: str, depth: int, instance_paths: set[tuple[str, ...]],
) -> None:
    if not isinstance(frame, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(frame, {
        "moduleUri", "sourceDigest", "moduleName", "instanceSymbol", "instanceIdPath",
        "importSpan", "useSpan",
    }, label, "HOCUS492")
    _source_uri(frame["moduleUri"], f"{label}.moduleUri", "HOCUS492")
    _digest(frame["sourceDigest"], f"{label}.sourceDigest", "HOCUS492")
    _string(frame["moduleName"], f"{label}.moduleName", "HOCUS492", pattern=_IDENTIFIER)
    _string(frame["instanceSymbol"], f"{label}.instanceSymbol", "HOCUS492", pattern=_IDENTIFIER)
    path = frame["instanceIdPath"]
    if not isinstance(path, list) or len(path) > depth:
        _fail("HOCUS492", f"{label}.instanceIdPath is invalid.")
    for seed in path:
        _string(seed, f"{label}.instanceIdPath", "HOCUS492", pattern=_SEED)
    instance_paths.add(tuple(path))
    if frame["importSpan"] is not None:
        _span(frame["importSpan"], f"{label}.importSpan")
    _span(frame["useSpan"], f"{label}.useSpan")


def _validate_control_stacks(
    value: Any, instances: int, depth: int, per_fold_iterations: int,
    aggregate_iterations: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) > instances:
        _fail("HOCUS492", "Control stacks exceed their declared bound.")
    ids: list[str] = []
    iteration_frames: set[str] = set()
    for index, stack in enumerate(value):
        ids.append(_validate_control_stack(
            stack, index, depth, per_fold_iterations, iteration_frames,
        ))
    if ids != sorted(set(ids)):
        _fail("HOCUS492", "Control stacks must be uniquely sorted by controlStackId.")
    if len(iteration_frames) > aggregate_iterations:
        _fail("HOCUS492", "Control provenance exceeds the aggregate iteration limit.")
    return ids


def _validate_control_stack(
    stack: Any,
    index: int,
    depth: int,
    per_fold_iterations: int,
    iteration_frames: set[str],
) -> str:
    label = f"expansionMap.controlStacks[{index}]"
    if not isinstance(stack, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(stack, {"controlStackId", "frames"}, label, "HOCUS492")
    stack_id = _digest(stack["controlStackId"], f"{label}.controlStackId", "HOCUS492")
    frames = stack["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= depth:
        _fail("HOCUS492", f"{label}.frames exceeds its declared bound.")
    for frame_index, frame in enumerate(frames):
        _validate_control_frame(
            frame, f"{label}.frames[{frame_index}]",
            per_fold_iterations, iteration_frames,
        )
    expected_stack_id = _content_digest({
        "domain": _CONTROL_STACK_DIGEST_DOMAIN, "frames": frames,
    })
    if not hmac.compare_digest(stack_id, expected_stack_id):
        _fail("HOCUS492", f"{label}.controlStackId does not match its frames.")
    return stack_id


def _validate_control_frame(
    frame: Any, label: str, per_fold_iterations: int, iteration_frames: set[str],
) -> None:
    if not isinstance(frame, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    common = {
        "kind", "controlSymbol", "durableSeed", "declarationSpan", "selectionSpan",
        "yieldSpans",
    }
    kind = frame.get("kind")
    specific = {"branch"} if kind == "if" else {"iterator", "iterationIndex"} if kind == "for" else set()
    _exact_keys(frame, common | specific, label, "HOCUS492")
    _string(frame["controlSymbol"], f"{label}.controlSymbol", "HOCUS492", pattern=_IDENTIFIER)
    _string(frame["durableSeed"], f"{label}.durableSeed", "HOCUS492", pattern=_SEED)
    _span(frame["declarationSpan"], f"{label}.declarationSpan")
    _span(frame["selectionSpan"], f"{label}.selectionSpan")
    _validate_yield_spans(frame["yieldSpans"], label)
    if kind == "if":
        if frame["branch"] not in {"then", "else"}:
            _fail("HOCUS492", f"{label}.branch is invalid.")
    elif kind == "for":
        _validate_iteration_frame(frame, label, per_fold_iterations)
        iteration_frames.add(_canonical_json(frame))
    else:
        _fail("HOCUS492", f"{label}.kind is invalid.")


def _validate_yield_spans(value: Any, label: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 256:
        _fail("HOCUS492", f"{label}.yieldSpans is invalid.")
    for index, yield_span in enumerate(value):
        _span(yield_span, f"{label}.yieldSpans[{index}]")


def _validate_iteration_frame(frame: dict[str, Any], label: str, maximum: int) -> None:
    _string(frame["iterator"], f"{label}.iterator", "HOCUS492", pattern=_IDENTIFIER)
    iteration = frame["iterationIndex"]
    if type(iteration) is not int or iteration < 0 or iteration >= maximum:
        _fail("HOCUS492", f"{label}.iterationIndex is invalid.")


def _walk_graph_values(value: Any):
    pending = [value]
    while pending:
        item = pending.pop()
        yield item
        if isinstance(item, dict) and item.get("kind") == "array":
            values = item.get("items")
            if isinstance(values, list):
                pending.extend(values)


def _graph_code_bytes(graph: Mapping[str, Any]) -> int:
    total = 0
    for node_index, node in enumerate(graph["nodes"]):
        parms = node.get("parms")
        if not isinstance(parms, list):
            _fail("HOCUS491", f"GraphSpec.nodes[{node_index}].parms must be an array.")
        for parm_index, parm in enumerate(parms):
            if not isinstance(parm, dict) or "value" not in parm:
                _fail(
                    "HOCUS491",
                    f"GraphSpec.nodes[{node_index}].parms[{parm_index}] is malformed.",
                )
            for item in _walk_graph_values(parm["value"]):
                if isinstance(item, dict) and item.get("kind") == "code":
                    body = item.get("body")
                    if not isinstance(body, str):
                        _fail("HOCUS491", "GraphSpec embedded code body is malformed.")
                    total += len(body.encode("utf-8"))
    return total


def _validate_expansion_surface(graph: Mapping[str, Any]) -> None:
    required = {""}
    required.update(
        f"/externalNodes/{index}" for index, _ in enumerate(graph["externalNodes"])
    )
    for node_index, node in enumerate(graph["nodes"]):
        inputs, parms = node.get("inputs"), node.get("parms")
        if not isinstance(inputs, list) or not isinstance(parms, list):
            _fail("HOCUS491", f"GraphSpec.nodes[{node_index}] has malformed inputs or parms.")
        prefix = f"/nodes/{node_index}"
        required.add(prefix)
        required.update(f"{prefix}/inputs/{index}" for index, _ in enumerate(inputs))
        required.update(f"{prefix}/parms/{index}" for index, _ in enumerate(parms))
    for field in ("display", "render", "output", "layout"):
        if graph[field] is not None:
            required.add(f"/{field}")
    actual = {
        mapping["generatedPointer"] for mapping in graph["expansionMap"]["mappings"]
    }
    if actual != required or any(not _json_pointer_resolves(graph, pointer) for pointer in actual):
        _fail("HOCUS491", "Expansion mappings do not exactly cover the GraphSpec origin surface.")


def _json_pointer_resolves(value: Any, pointer: str) -> bool:
    current = value
    if pointer == "":
        return True
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (token != "0" and token.startswith("0")):
                return False
            index = int(token)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True


def _module_transitive_digest(
    item: Mapping[str, Any], by_uri: Mapping[str, Mapping[str, Any]],
) -> str:
    return _content_digest({
        "domain": _TRANSITIVE_DIGEST_DOMAIN,
        "uri": item["uri"],
        "sourceDigest": item["sourceDigest"],
        "interfaceDigest": item["interfaceDigest"],
        "dependencies": [
            {"uri": uri, "transitiveDigest": by_uri[uri]["transitiveDigest"]}
            for uri in item["dependencies"]
        ],
    })


def _validate_module_dag_and_digests(
    by_uri: Mapping[str, Mapping[str, Any]], *, max_depth: int,
) -> None:
    unresolved = {
        uri: len(item["dependencies"]) for uri, item in by_uri.items()
    }
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
            _fail("HOCUS493", "Resolved module import depth exceeds its declared limit.")
        depths[uri] = depth
        expected = _module_transitive_digest(item, by_uri)
        if not hmac.compare_digest(item["transitiveDigest"], expected):
            _fail("HOCUS493", f"Resolved module transitiveDigest is invalid for {uri}.")
        processed += 1
        for parent in sorted(parents[uri]):
            unresolved[parent] -= 1
            if unresolved[parent] == 0:
                ready.append(parent)
        ready.sort()
    if processed != len(by_uri):
        _fail("HOCUS493", "Resolved module dependency graph contains a cycle.")


def _validate_expansion_module_provenance(
    expansion: Mapping[str, Any], resolved: Mapping[str, Any],
) -> None:
    modules = {item["uri"]: item for item in resolved["modules"]}
    allowed_source_uris = {resolved["entrySourceUri"], *modules}
    for stack_index, stack in enumerate(expansion["stacks"]):
        for frame_index, frame in enumerate(stack["frames"]):
            label = f"expansionMap.stacks[{stack_index}].frames[{frame_index}]"
            module = modules.get(frame["moduleUri"])
            if (
                module is None
                or frame["sourceDigest"] != module["sourceDigest"]
                or frame["moduleName"] != module["moduleName"]
            ):
                _fail("HOCUS494", f"{label} conflicts with the resolved module set.")
            for span_name in ("importSpan", "useSpan"):
                span = frame[span_name]
                if span is not None and span["sourceUri"] not in allowed_source_uris:
                    _fail("HOCUS494", f"{label}.{span_name} has unknown source provenance.")
    for stack_index, stack in enumerate(expansion["controlStacks"]):
        for frame_index, frame in enumerate(stack["frames"]):
            label = f"expansionMap.controlStacks[{stack_index}].frames[{frame_index}]"
            spans = [frame["declarationSpan"], frame["selectionSpan"], *frame["yieldSpans"]]
            if any(span["sourceUri"] not in allowed_source_uris for span in spans):
                _fail("HOCUS494", f"{label} has unknown source provenance.")
    for mapping_index, mapping in enumerate(expansion["mappings"]):
        spans = [mapping["primarySpan"], *(item["span"] for item in mapping["relatedOrigins"])]
        if any(span["sourceUri"] not in allowed_source_uris for span in spans):
            _fail(
                "HOCUS494",
                f"expansionMap.mappings[{mapping_index}] has unknown source provenance.",
            )


def _decode_json_object(value: Any, label: str, code: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload: Any = dict(value)
        _validate_json(payload, label, code)
        return json.loads(_canonical_json(payload))
    if not isinstance(value, (str, bytes, bytearray)):
        _fail(code, f"{label} must be a JSON object, text, or bytes.")
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if len(raw) > _MAX_JSON_BYTES:
        _fail(code, f"{label} exceeds the {_MAX_JSON_BYTES}-byte decode limit.")
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_raise_json_constant(token)),
        )
    except (UnicodeDecodeError, ValueError, RecursionError, CarrierContractError) as exc:
        if isinstance(exc, CarrierContractError):
            raise
        raise CarrierContractError(code, f"{label} is invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        _fail(code, f"{label} must decode to an object.")
    _validate_json(payload, label, code)
    if text != _canonical_json(payload):
        _fail(code, f"{label} text must use exact canonical JSON encoding.")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CarrierContractError("HOCUS490", f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _raise_json_constant(token: str) -> Any:
    raise CarrierContractError("HOCUS490", f"Non-finite JSON number is forbidden: {token}.")


def _validate_json(value: Any, label: str, code: str) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    count = 0
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > _MAX_JSON_VALUES or depth > _MAX_JSON_DEPTH:
            _fail(code, f"{label} exceeds the JSON complexity limit.")
        if current is None or type(current) in {str, bool, int}:
            continue
        if type(current) is float:
            if not math.isfinite(current):
                _fail(code, f"{label} contains a non-finite number.")
            continue
        if isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
            continue
        if isinstance(current, dict):
            if any(type(key) is not str for key in current):
                _fail(code, f"{label} contains a non-string object key.")
            pending.extend((item, depth + 1) for item in current.values())
            continue
        _fail(code, f"{label} contains a non-JSON value of type {type(current).__name__}.")


def _canonical_json(value: Mapping[str, Any] | dict[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CarrierContractError("HOCUS490", f"Carrier is not canonical JSON: {exc}") from exc


def _content_digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str, code: str) -> None:
    actual = set(value)
    if actual != expected:
        _fail(code, f"{label} has missing or unknown fields.", details={
            "missing": sorted(expected - actual), "unknown": sorted(actual - expected),
        })


def _equal(value: Mapping[str, Any], key: str, expected: Any, code: str) -> None:
    if value.get(key) != expected or type(value.get(key)) is not type(expected):
        _fail(code, f"{key} does not match its carrier contract.")


def _exact_int(value: Any, expected: int, label: str, code: str) -> None:
    if type(value) is not int or value != expected:
        _fail(code, f"{label} must be the exact integer {expected}.")


def _string(
    value: Any, label: str, code: str, *, maximum: int = 8192,
    pattern: re.Pattern[str] | None = None, allow_empty: bool = False,
) -> str:
    if type(value) is not str or (not allow_empty and not value) or len(value) > maximum or (
        pattern is not None and pattern.fullmatch(value) is None
    ):
        _fail(code, f"{label} is invalid.")
    return value


def _nullable_string(value: Any, label: str, code: str) -> None:
    if value is not None:
        _string(value, label, code)


def _digest(value: Any, label: str, code: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        _fail(code, f"{label} must be a lowercase SHA-256 digest.")
    return value


def _nullable_digest(value: Any, label: str, code: str) -> str | None:
    return None if value is None else _digest(value, label, code)


def _source_uri(value: Any, label: str, code: str) -> str:
    if (
        type(value) is not str
        or len(value) > 8192
        or _SOURCE_URI.fullmatch(value) is None
        or canonical_module_uri(value) is None
    ):
        _fail(code, f"{label} must be a bounded canonical module/project URI.")
    return value


def _object_array(value: Any, label: str, maximum: int, code: str) -> None:
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(item, dict) for item in value):
        _fail(code, f"{label} must be a bounded array of objects.")


def _position(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(value, {"line", "column", "offset"}, label, "HOCUS492")
    for field, minimum in (("line", 1), ("column", 1), ("offset", 0)):
        if type(value[field]) is not int or value[field] < minimum:
            _fail("HOCUS492", f"{label}.{field} is invalid.")


def _span(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        _fail("HOCUS492", f"{label} must be an object.")
    _exact_keys(value, {"sourceUri", "start", "end"}, label, "HOCUS492")
    _source_uri(value["sourceUri"], f"{label}.sourceUri", "HOCUS492")
    _position(value["start"], f"{label}.start")
    _position(value["end"], f"{label}.end")
    start, end = value["start"], value["end"]
    if start["offset"] > end["offset"]:
        _fail("HOCUS492", f"{label} has an inverted offset range.")


def _source_record(value: Any, label: str, kinds: set[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        _fail("HOCUS494", f"{label} must be an object.")
    _exact_keys(value, {"uri", "digest", "kind"}, label, "HOCUS494")
    uri = _source_uri(value["uri"], f"{label}.uri", "HOCUS494")
    digest = _digest(value["digest"], f"{label}.digest", "HOCUS494")
    if value["kind"] not in kinds:
        _fail("HOCUS494", f"{label}.kind is invalid.")
    return {"uri": uri, "digest": digest, "kind": value["kind"]}


def _fail(
    code: str, message: str, *, details: Mapping[str, Any] | None = None,
) -> None:
    raise CarrierContractError(code, message, details=details)


__all__ = [
    "CARRIER_CONTRACTS", "CARRIER_CONTRACTS_BY_BUNDLE", "CARRIER_CONTRACTS_BY_COMPILER",
    "CARRIER_CONTRACTS_BY_EXPANSION_MAP", "CARRIER_CONTRACTS_BY_GRAPH_SPEC",
    "CARRIER_CONTRACTS_BY_LANGUAGE", "CARRIER_CONTRACTS_BY_MODULE_MANIFEST",
    "CARRIER_CONTRACTS_BY_PROJECT_LOCK", "CARRIER_CONTRACTS_BY_PROJECT_MANIFEST",
    "CARRIER_CONTRACTS_BY_RESOLVED_MODULE_SET", "CONTROL_CARRIER_CONTRACT",
    "CONTROL_BUNDLE_VERSION", "CONTROL_COMPILER_VERSION", "CONTROL_EXPANSION_MAP_VERSION",
    "CONTROL_GRAPH_SPEC_VERSION", "CONTROL_LANGUAGE_VERSION", "CONTROL_MODULE_MANIFEST_VERSION",
    "CONTROL_PROJECT_LOCK_VERSION", "CONTROL_PROJECT_MANIFEST_VERSION",
    "CONTROL_RESOLVED_MODULE_SET_VERSION", "CONTROL_RESOLVED_LIMIT_MAXIMA",
    "STATIC_CARRIER_CONTRACT", "CarrierContract", "CarrierContractError",
    "contract_for_bundle", "contract_for_compiler", "contract_for_expansion_map",
    "contract_for_graph_spec", "contract_for_language", "contract_for_module_manifest",
    "contract_for_project_lock", "contract_for_project_manifest",
    "contract_for_resolved_module_set", "decode_control_bundle_envelope",
    "decode_control_expansion_map_envelope", "decode_control_graph_spec_envelope",
    "decode_control_resolved_module_set_envelope", "require_carrier_contract",
]
