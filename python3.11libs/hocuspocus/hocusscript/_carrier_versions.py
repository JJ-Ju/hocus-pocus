"""Exact HocusScript carrier compatibility rows.

Keeping the version registry separate lets the strict carrier decoders remain
focused and below the repository file-size gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class CarrierContractError(ValueError):
    """Raised when a carrier version or decode-only envelope is invalid."""

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
class CarrierContract:
    """One exact, non-interchangeable HocusScript compatibility row."""

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

VALUE_CARRIER_CONTRACT = CarrierContract(
    language_version="0.4",
    compiler_version="0.6.0",
    graph_spec_version="0.5",
    expansion_map_version=3,
    resolved_module_set_version=3,
    project_manifest_version=5,
    project_lock_version=5,
    module_manifest_version=3,
    bundle_version="0.5",
    resolver_policy_version=1,
    resolver_interface_version=1,
    dispatch_enabled=True,
)

CONTROL_LANGUAGE_VERSION = CONTROL_CARRIER_CONTRACT.language_version
CONTROL_COMPILER_VERSION = CONTROL_CARRIER_CONTRACT.compiler_version
CONTROL_GRAPH_SPEC_VERSION = CONTROL_CARRIER_CONTRACT.graph_spec_version
CONTROL_EXPANSION_MAP_VERSION = CONTROL_CARRIER_CONTRACT.expansion_map_version
CONTROL_RESOLVED_MODULE_SET_VERSION = (
    CONTROL_CARRIER_CONTRACT.resolved_module_set_version
)
CONTROL_PROJECT_MANIFEST_VERSION = CONTROL_CARRIER_CONTRACT.project_manifest_version
CONTROL_PROJECT_LOCK_VERSION = CONTROL_CARRIER_CONTRACT.project_lock_version
CONTROL_MODULE_MANIFEST_VERSION = CONTROL_CARRIER_CONTRACT.module_manifest_version
CONTROL_BUNDLE_VERSION = CONTROL_CARRIER_CONTRACT.bundle_version

VALUE_LANGUAGE_VERSION = VALUE_CARRIER_CONTRACT.language_version
VALUE_COMPILER_VERSION = VALUE_CARRIER_CONTRACT.compiler_version
VALUE_GRAPH_SPEC_VERSION = VALUE_CARRIER_CONTRACT.graph_spec_version
VALUE_EXPANSION_MAP_VERSION = VALUE_CARRIER_CONTRACT.expansion_map_version
VALUE_RESOLVED_MODULE_SET_VERSION = VALUE_CARRIER_CONTRACT.resolved_module_set_version
VALUE_PROJECT_MANIFEST_VERSION = VALUE_CARRIER_CONTRACT.project_manifest_version
VALUE_PROJECT_LOCK_VERSION = VALUE_CARRIER_CONTRACT.project_lock_version
VALUE_MODULE_MANIFEST_VERSION = VALUE_CARRIER_CONTRACT.module_manifest_version
VALUE_BUNDLE_VERSION = VALUE_CARRIER_CONTRACT.bundle_version

CARRIER_CONTRACTS = (
    STATIC_CARRIER_CONTRACT,
    CONTROL_CARRIER_CONTRACT,
    VALUE_CARRIER_CONTRACT,
)


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


def _lookup(
    index: Mapping[Any, CarrierContract], value: Any, label: str
) -> CarrierContract:
    try:
        return index[value]
    except (KeyError, TypeError) as exc:
        raise CarrierContractError(
            "HOCUS490", f"Unsupported HocusScript {label}: {value!r}."
        ) from exc


def contract_for_language(version: str) -> CarrierContract:
    return _lookup(CARRIER_CONTRACTS_BY_LANGUAGE, version, "language version")


def contract_for_compiler(version: str) -> CarrierContract:
    return _lookup(CARRIER_CONTRACTS_BY_COMPILER, version, "compiler version")


def contract_for_graph_spec(version: str) -> CarrierContract:
    return _lookup(CARRIER_CONTRACTS_BY_GRAPH_SPEC, version, "GraphSpec version")


def contract_for_expansion_map(version: int) -> CarrierContract:
    if type(version) is not int:
        raise CarrierContractError(
            "HOCUS490", "Expansion-map version must be an integer."
        )
    return _lookup(
        CARRIER_CONTRACTS_BY_EXPANSION_MAP, version, "expansion-map version"
    )


def contract_for_resolved_module_set(version: int) -> CarrierContract:
    if type(version) is not int:
        raise CarrierContractError(
            "HOCUS490", "Resolved-set version must be an integer."
        )
    return _lookup(
        CARRIER_CONTRACTS_BY_RESOLVED_MODULE_SET, version, "resolved-set version"
    )


def contract_for_project_manifest(version: int) -> CarrierContract:
    if type(version) is not int:
        raise CarrierContractError(
            "HOCUS490", "Project-manifest version must be an integer."
        )
    return _lookup(
        CARRIER_CONTRACTS_BY_PROJECT_MANIFEST, version, "project-manifest version"
    )


def contract_for_project_lock(version: int) -> CarrierContract:
    if type(version) is not int:
        raise CarrierContractError(
            "HOCUS490", "Project-lock version must be an integer."
        )
    return _lookup(CARRIER_CONTRACTS_BY_PROJECT_LOCK, version, "project-lock version")


def contract_for_module_manifest(version: int) -> CarrierContract:
    if type(version) is not int:
        raise CarrierContractError(
            "HOCUS490", "Module-manifest version must be an integer."
        )
    return _lookup(
        CARRIER_CONTRACTS_BY_MODULE_MANIFEST, version, "module-manifest version"
    )


def contract_for_bundle(version: str) -> CarrierContract:
    return _lookup(CARRIER_CONTRACTS_BY_BUNDLE, version, "compiled-bundle version")


def require_carrier_contract(
    *,
    language_version: str,
    compiler_version: str,
    graph_spec_version: str,
    expansion_map_version: int,
    resolved_module_set_version: int,
    project_manifest_version: int,
    project_lock_version: int,
    module_manifest_version: int,
    bundle_version: str,
    resolver_policy_version: int = 1,
    resolver_interface_version: int = 1,
) -> CarrierContract:
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
            "HOCUS490",
            "HocusScript carrier versions are mixed or unsupported.",
            details={"languageVersion": language_version},
        )
    return row


CONTROL_RESOLVED_LIMIT_MAXIMA = MappingProxyType(
    {
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
    }
)
