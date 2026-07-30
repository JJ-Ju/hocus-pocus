"""Versioned, deterministic Houdini catalog snapshots for offline compilation.

This module deliberately has no dependency on :mod:`hou`.  Live extraction is a
provider concern; the compiler and tests consume the same strict snapshot model.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

CATALOG_VERSION = 1
CATALOG_SCHEMA_URI = "hocuspocus://schemas/catalog/v1"
VALUE_CATALOG_VERSION = 2
VALUE_CATALOG_SCHEMA_URI = "hocuspocus://schemas/catalog/v2"
# A complete Houdini 21 catalog with full parameter metadata is currently about
# 43 MiB. Keep a bounded margin for package/HDA growth without filtering the
# semantic input and silently weakening its fingerprint.
MAX_CATALOG_BYTES = 64 * 1024 * 1024
MAX_CATALOG_DEPTH = 64
MAX_CATALOG_VALUES = 5_000_000

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_PARM_TYPES = {
    "bool", "int", "float", "string", "tuple", "menu", "code", "button",
    "node_path", "parm_path", "file_path", "usd_prim_path", "asset_reference",
    "ramp", "multiparm",
}
_CODE_SURFACES = {"none", "python", "vex", "hscript", "unsupported"}
_SOURCE_KINDS = {"builtin", "hda", "package", "labs"}
_PACKAGE_KINDS = {"package", "labs"}
_SPARE_POLICIES = {"forbidden", "declared_only", "allowed"}
_CARDINALITIES = {"one", "optional", "many"}

__all__ = [
    "CATALOG_SCHEMA_URI", "CATALOG_VERSION", "CatalogProvider", "CatalogSnapshot",
    "CatalogValidationError", "CategoryDefinition", "ConnectorDefinition", "DefinitionSource",
    "FakeCatalogProvider", "HdaLibrary", "HoudiniBuild", "MenuItem", "OperatorDefinition",
    "PackageDefinition", "ParameterDefinition", "ParmRange", "SnapshotCatalogProvider",
    "canonical_catalog_json", "decode_catalog_snapshot",
]


class CatalogValidationError(ValueError):
    """A typed rejection at the catalog trust boundary."""

    def __init__(self, code: str, message: str, *, path: str = "$"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


def _fail(code: str, message: str, path: str = "$") -> None:
    raise CatalogValidationError(code, message, path=path)


def _object(value: Any, path: str, keys: set[str], required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail("catalog.type", "Expected an object.", path)
    if not all(isinstance(key, str) for key in value):
        _fail("catalog.type", "Object keys must be strings.", path)
    unknown = set(value) - keys
    missing = required - set(value)
    if unknown:
        _fail("catalog.unknown_field", f"Unknown field: {sorted(unknown)[0]}.", path)
    if missing:
        _fail("catalog.missing_field", f"Missing field: {sorted(missing)[0]}.", path)
    return value


def _string(value: Any, path: str, *, nullable: bool = False, maximum: int = 4096) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("catalog.type", "Expected a non-empty bounded string.", path)
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("catalog.type", "Expected a boolean.", path)
    return value


def _integer(
    value: Any, path: str, *, nullable: bool = False, minimum: int = 0,
    maximum: int | None = None,
) -> int | None:
    if value is None and nullable:
        return None
    if (isinstance(value, bool) or not isinstance(value, int) or value < minimum
            or (maximum is not None and value > maximum)):
        suffix = f" and <= {maximum}" if maximum is not None else ""
        _fail("catalog.type", f"Expected an integer >= {minimum}{suffix}.", path)
    return value


def _number(value: Any, path: str, *, nullable: bool = False) -> int | float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("catalog.type", "Expected a finite number.", path)
    return value


def _strings(value: Any, path: str, *, unique: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail("catalog.type", "Expected an array.", path)
    if len(value) > 4096:
        _fail("catalog.limit", "String array exceeds the 4096-item limit.", path)
    result = tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if unique and len(set(result)) != len(result):
        _fail("catalog.duplicate", "Array values must be unique.", path)
    return result  # type: ignore[return-value]


def _enum(value: Any, choices: set[str], path: str) -> str:
    result = _string(value, path)
    if result not in choices:
        _fail("catalog.enum", f"Expected one of {sorted(choices)}.", path)
    return result


def _json_value(value: Any, path: str, depth: int = 0) -> Any:
    if depth > 16:
        _fail("catalog.limit", "Parameter value nesting is too deep.", path)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("catalog.type", "Non-finite numbers are forbidden.", path)
        return value
    if isinstance(value, list):
        return tuple(_json_value(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            _fail("catalog.type", "Object keys must be strings.", path)
        return MappingProxyType({key: _json_value(item, f"{path}.{key}", depth + 1) for key, item in value.items()})
    _fail("catalog.type", "Unsupported JSON value.", path)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class HoudiniBuild:
    product: str
    version: str
    build: str
    platform: str
    feature_flags: tuple[str, ...] = ()

    def to_dict(self, *, catalog_version: int = CATALOG_VERSION) -> dict[str, Any]:
        return {"product": self.product, "version": self.version, "build": self.build,
                "platform": self.platform, "featureFlags": sorted(self.feature_flags)}


@dataclass(frozen=True, slots=True)
class PackageDefinition:
    identifier: str
    name: str
    version: str
    kind: str = "package"
    content_digest: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.identifier, "name": self.name, "version": self.version, "kind": self.kind,
                "contentDigest": self.content_digest, "tags": dict(sorted(self.tags.items()))}


@dataclass(frozen=True, slots=True)
class HdaLibrary:
    identity: str
    content_digest: str
    asset_name: str
    asset_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"identity": self.identity, "contentDigest": self.content_digest,
                "assetName": self.asset_name, "assetVersion": self.asset_version}


@dataclass(frozen=True, slots=True)
class DefinitionSource:
    kind: str
    package_id: str | None = None
    hda_library: HdaLibrary | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "packageId": self.package_id,
                "hdaLibrary": self.hda_library.to_dict() if self.hda_library else None}


@dataclass(frozen=True, slots=True)
class MenuItem:
    token: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {"token": self.token, "label": self.label}


@dataclass(frozen=True, slots=True)
class ParmRange:
    minimum: int | float | None = None
    maximum: int | float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"min": self.minimum, "max": self.maximum, "minInclusive": self.minimum_inclusive,
                "maxInclusive": self.maximum_inclusive}


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    token: str
    label: str
    value_type: str
    tuple_size: int
    tuple_names: tuple[str, ...]
    default: Any
    range: ParmRange | None = None
    menu: tuple[MenuItem, ...] = ()
    tags: Mapping[str, str] = field(default_factory=dict)
    code_surface: str = "none"
    assignable: bool = True
    value_contract: Mapping[str, Any] | None = None

    def to_dict(self, *, catalog_version: int = CATALOG_VERSION) -> dict[str, Any]:
        payload = {"token": self.token, "label": self.label, "type": self.value_type,
                "tupleSize": self.tuple_size, "tupleNames": list(self.tuple_names),
                "default": _thaw(self.default), "range": self.range.to_dict() if self.range else None,
                "menu": [item.to_dict() for item in self.menu], "tags": dict(sorted(self.tags.items())),
                "codeSurface": self.code_surface, "assignable": self.assignable}
        if catalog_version == VALUE_CATALOG_VERSION:
            payload["valueContract"] = _thaw(self.value_contract)
        return payload


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    index: int | None
    name: str | None
    label: str
    cardinality: str = "one"
    data_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "name": self.name, "label": self.label,
                "cardinality": self.cardinality, "dataTypes": sorted(self.data_types),
                "categories": sorted(self.categories)}


@dataclass(frozen=True, slots=True)
class OperatorDefinition:
    qualified_name: str
    name: str
    namespace: str | None
    version: str | None
    category: str
    aliases: tuple[str, ...]
    source: DefinitionSource
    parameters: tuple[ParameterDefinition, ...]
    inputs: tuple[ConnectorDefinition, ...]
    outputs: tuple[ConnectorDefinition, ...]
    spare_parameter_policy: str = "forbidden"
    locked: bool = False
    editable: bool = True
    network_families: tuple[str, ...] = ()
    instance_network: bool | None = None

    def to_dict(self, *, catalog_version: int = CATALOG_VERSION) -> dict[str, Any]:
        payload = {"qualifiedName": self.qualified_name, "name": self.name, "namespace": self.namespace,
                "version": self.version, "category": self.category, "aliases": sorted(self.aliases),
                "source": self.source.to_dict(),
                "parameters": [
                    item.to_dict(catalog_version=catalog_version)
                    for item in sorted(self.parameters, key=lambda item: item.token)
                ],
                "inputs": [item.to_dict() for item in sorted(self.inputs, key=_connector_key)],
                "outputs": [item.to_dict() for item in sorted(self.outputs, key=_connector_key)],
                "spareParameterPolicy": self.spare_parameter_policy, "locked": self.locked,
                "editable": self.editable, "networkFamilies": sorted(self.network_families)}
        if catalog_version == VALUE_CATALOG_VERSION:
            payload["instanceNetwork"] = self.instance_network
        return payload


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    name: str
    label: str
    network_family: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "label": self.label, "networkFamily": self.network_family}


def _connector_key(item: ConnectorDefinition) -> tuple[int, int, str]:
    return (item.index is None, item.index if item.index is not None else 0, item.name or "")


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    houdini: HoudiniBuild
    categories: tuple[CategoryDefinition, ...]
    operators: tuple[OperatorDefinition, ...]
    packages: tuple[PackageDefinition, ...] = ()
    catalog_version: int = CATALOG_VERSION

    def unsigned_dict(self) -> dict[str, Any]:
        schema_uri = (
            VALUE_CATALOG_SCHEMA_URI
            if self.catalog_version == VALUE_CATALOG_VERSION
            else CATALOG_SCHEMA_URI
        )
        return {"$schema": schema_uri, "kind": "hocus_catalog", "catalogVersion": self.catalog_version,
                "houdini": self.houdini.to_dict(),
                "categories": [item.to_dict() for item in sorted(self.categories, key=lambda item: item.name)],
                "operators": [
                    item.to_dict(catalog_version=self.catalog_version)
                    for item in sorted(self.operators, key=lambda item: (item.category, item.qualified_name))
                ],
                "packages": [item.to_dict() for item in sorted(self.packages, key=lambda item: item.identifier)]}

    @property
    def fingerprint(self) -> str:
        encoded = canonical_catalog_json(self.unsigned_dict()).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.unsigned_dict()
        payload["catalogFingerprint"] = self.fingerprint
        return payload

    def to_json(self) -> str:
        return canonical_catalog_json(self.to_dict())


@runtime_checkable
class CatalogProvider(Protocol):
    """Common contract implemented by offline, test, and future live providers."""

    def get_catalog(self) -> CatalogSnapshot:
        """Return one immutable, internally consistent catalog snapshot."""


@dataclass(frozen=True, slots=True)
class SnapshotCatalogProvider:
    catalog: CatalogSnapshot

    @classmethod
    def decode(cls, content: str | bytes | bytearray | Mapping[str, Any]) -> "SnapshotCatalogProvider":
        return cls(decode_catalog_snapshot(content))

    def get_catalog(self) -> CatalogSnapshot:
        return self.catalog


@dataclass(frozen=True, slots=True)
class FakeCatalogProvider:
    """Small programmatic provider with the exact same contract as a snapshot."""

    catalog: CatalogSnapshot

    @classmethod
    def create(
        cls, *, operators: Sequence[OperatorDefinition], categories: Sequence[CategoryDefinition],
        packages: Sequence[PackageDefinition] = (), product: str = "Houdini",
        version: str = "test", build: str = "test", platform: str = "test",
        feature_flags: Sequence[str] = (),
        catalog_version: int = CATALOG_VERSION,
    ) -> "FakeCatalogProvider":
        catalog = CatalogSnapshot(
            HoudiniBuild(product, version, build, platform, tuple(feature_flags)),
            tuple(categories), tuple(operators), tuple(packages), catalog_version,
        )
        # Round-trip through strict validation so invalid fakes cannot bypass the boundary.
        return cls(decode_catalog_snapshot(catalog.to_dict()))

    def get_catalog(self) -> CatalogSnapshot:
        return self.catalog


def canonical_catalog_json(payload: Mapping[str, Any]) -> str:
    """Return canonical UTF-8 JSON; callers normalize catalog collection order first."""
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def decode_catalog_snapshot(content: str | bytes | bytearray | Mapping[str, Any]) -> CatalogSnapshot:
    """Strictly decode and authenticate an untrusted v1/v2 catalog snapshot."""
    payload = _load_catalog_payload(content)
    _enforce_limits(payload)
    root = _catalog_root(payload)
    fingerprint = _catalog_fingerprint(root)
    version = root["catalogVersion"]
    snapshot = CatalogSnapshot(
        _decode_houdini(root["houdini"], "$.houdini"),
        _decode_categories(root["categories"], "$.categories"),
        _decode_operators(root["operators"], "$.operators", version),
        _decode_packages(root["packages"], "$.packages"),
        version,
    )
    _validate_relations(snapshot)
    if not hmac.compare_digest(fingerprint, snapshot.fingerprint):
        _fail("catalog.fingerprint_mismatch", "Catalog fingerprint does not match canonical content.", "$.catalogFingerprint")
    return snapshot


def _load_catalog_payload(
    content: str | bytes | bytearray | Mapping[str, Any],
) -> Any:
    if isinstance(content, Mapping):
        return _catalog_mapping_payload(content)
    return _catalog_json_payload(content)


def _catalog_mapping_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(content)
    try:
        encoded_size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except RecursionError:
        _fail("catalog.limit", "Catalog object nesting exceeds the JSON encoder limit.")
    except (TypeError, ValueError) as error:
        _fail("catalog.type", f"Catalog object is not valid JSON data: {error}.")
    if encoded_size > MAX_CATALOG_BYTES:
        _fail("catalog.limit", "Catalog snapshot exceeds the byte limit.")
    return payload


def _catalog_json_payload(content: str | bytes | bytearray) -> Any:
    raw: Any = content
    if isinstance(content, (bytes, bytearray)):
        if len(content) > MAX_CATALOG_BYTES:
            _fail("catalog.limit", "Catalog snapshot exceeds the byte limit.")
        try:
            raw = bytes(content).decode("utf-8")
        except UnicodeDecodeError as error:
            _fail("catalog.encoding", f"Catalog snapshot is not valid UTF-8: {error}.")
    if not isinstance(raw, str):
        _fail("catalog.type", "Catalog content must be JSON text, bytes, or an object.")
    if len(raw.encode("utf-8")) > MAX_CATALOG_BYTES:
        _fail("catalog.limit", "Catalog snapshot exceeds the byte limit.")
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except CatalogValidationError:
        raise
    except RecursionError:
        _fail("catalog.limit", "Catalog JSON nesting exceeds the decoder limit.")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("catalog.json", f"Invalid catalog JSON: {error}.")


def _catalog_root(payload: Any) -> dict[str, Any]:
    root = _object(payload, "$", {
        "$schema", "kind", "catalogVersion", "catalogFingerprint", "houdini", "categories", "operators", "packages"
    }, {"$schema", "kind", "catalogVersion", "catalogFingerprint", "houdini", "categories", "operators", "packages"})
    version = root["catalogVersion"]
    expected_schema = {
        CATALOG_VERSION: CATALOG_SCHEMA_URI,
        VALUE_CATALOG_VERSION: VALUE_CATALOG_SCHEMA_URI,
    }.get(version)
    if (root["$schema"] != expected_schema or root["kind"] != "hocus_catalog"
            or isinstance(root["catalogVersion"], bool)
            or not isinstance(root["catalogVersion"], int)
            or version not in {CATALOG_VERSION, VALUE_CATALOG_VERSION}):
        _fail("catalog.version", "Unsupported catalog schema, kind, or version.")
    return root


def _catalog_fingerprint(root: Mapping[str, Any]) -> str:
    fingerprint = _string(root["catalogFingerprint"], "$.catalogFingerprint")
    if not _DIGEST.fullmatch(fingerprint or ""):
        _fail("catalog.digest", "Invalid catalog fingerprint.", "$.catalogFingerprint")
    return fingerprint


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("catalog.duplicate_key", f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    _fail("catalog.type", f"Non-finite number {value} is forbidden.")


def _enforce_limits(value: Any) -> None:
    count = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_CATALOG_VALUES or depth > MAX_CATALOG_DEPTH:
            _fail("catalog.limit", "Catalog structure exceeds resource limits.")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _decode_houdini(value: Any, path: str) -> HoudiniBuild:
    item = _object(value, path, {"product", "version", "build", "platform", "featureFlags"},
                   {"product", "version", "build", "platform", "featureFlags"})
    return HoudiniBuild(_string(item["product"], path + ".product"), _string(item["version"], path + ".version"),
                        _string(item["build"], path + ".build"), _string(item["platform"], path + ".platform"),
                        _strings(item["featureFlags"], path + ".featureFlags"))  # type: ignore[arg-type]


def _array(value: Any, path: str, maximum: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        _fail("catalog.type", "Expected an array.", path)
    if maximum is not None and len(value) > maximum:
        _fail("catalog.limit", f"Array exceeds the {maximum}-item limit.", path)
    return value


def _decode_categories(value: Any, path: str) -> tuple[CategoryDefinition, ...]:
    result = []
    for index, raw in enumerate(_array(value, path, 1024)):
        current = f"{path}[{index}]"
        item = _object(raw, current, {"name", "label", "networkFamily"}, {"name", "label", "networkFamily"})
        result.append(CategoryDefinition(_string(item["name"], current + ".name"),
                                         _string(item["label"], current + ".label"),
                                         _string(item["networkFamily"], current + ".networkFamily")))
    return tuple(result)  # type: ignore[arg-type]


def _decode_packages(value: Any, path: str) -> tuple[PackageDefinition, ...]:
    result = []
    for index, raw in enumerate(_array(value, path, 10000)):
        current = f"{path}[{index}]"
        item = _object(raw, current, {"id", "name", "version", "kind", "contentDigest", "tags"},
                       {"id", "name", "version", "kind", "contentDigest", "tags"})
        digest = _string(item["contentDigest"], current + ".contentDigest", nullable=True)
        if digest is not None and not _DIGEST.fullmatch(digest):
            _fail("catalog.digest", "Invalid content digest.", current + ".contentDigest")
        result.append(PackageDefinition(_string(item["id"], current + ".id"),
                                        _string(item["name"], current + ".name"),
                                        _string(item["version"], current + ".version"),
                                        _enum(item["kind"], _PACKAGE_KINDS, current + ".kind"), digest,
                                        _decode_tags(item["tags"], current + ".tags")))
    return tuple(result)  # type: ignore[arg-type]


def _decode_tags(value: Any, path: str) -> Mapping[str, str]:
    if not isinstance(value, dict) or len(value) > 256:
        _fail("catalog.type", "Expected a bounded string map.", path)
    return MappingProxyType({_string(key, path): _string(item, f"{path}.{key}") for key, item in value.items()})  # type: ignore[misc]


def _decode_operators(
    value: Any, path: str, catalog_version: int,
) -> tuple[OperatorDefinition, ...]:
    result = []
    keys = {"qualifiedName", "name", "namespace", "version", "category", "aliases", "source", "parameters",
            "inputs", "outputs", "spareParameterPolicy", "locked", "editable", "networkFamilies"}
    if catalog_version == VALUE_CATALOG_VERSION:
        keys.add("instanceNetwork")
    for index, raw in enumerate(_array(value, path, 100000)):
        current = f"{path}[{index}]"
        item = _object(raw, current, keys, keys)
        result.append(OperatorDefinition(
            _string(item["qualifiedName"], current + ".qualifiedName"), _string(item["name"], current + ".name"),
            _string(item["namespace"], current + ".namespace", nullable=True),
            _string(item["version"], current + ".version", nullable=True),
            _string(item["category"], current + ".category"), _strings(item["aliases"], current + ".aliases"),
            _decode_source(item["source"], current + ".source"),
            _decode_parameters(
                item["parameters"], current + ".parameters", catalog_version
            ),
            _decode_connectors(item["inputs"], current + ".inputs"),
            _decode_connectors(item["outputs"], current + ".outputs"),
            _enum(item["spareParameterPolicy"], _SPARE_POLICIES, current + ".spareParameterPolicy"),
            _boolean(item["locked"], current + ".locked"), _boolean(item["editable"], current + ".editable"),
            _strings(item["networkFamilies"], current + ".networkFamilies"),
            (
                _boolean(item["instanceNetwork"], current + ".instanceNetwork")
                if catalog_version == VALUE_CATALOG_VERSION else None
            ),
        ))
    return tuple(result)  # type: ignore[arg-type]


def _decode_source(value: Any, path: str) -> DefinitionSource:
    item = _object(value, path, {"kind", "packageId", "hdaLibrary"}, {"kind", "packageId", "hdaLibrary"})
    hda = None
    if item["hdaLibrary"] is not None:
        raw = _object(item["hdaLibrary"], path + ".hdaLibrary",
                      {"identity", "contentDigest", "assetName", "assetVersion"},
                      {"identity", "contentDigest", "assetName", "assetVersion"})
        digest = _string(raw["contentDigest"], path + ".hdaLibrary.contentDigest")
        if not _DIGEST.fullmatch(digest or ""):
            _fail("catalog.digest", "Invalid HDA content digest.", path + ".hdaLibrary.contentDigest")
        hda = HdaLibrary(_string(raw["identity"], path + ".hdaLibrary.identity"), digest,
                         _string(raw["assetName"], path + ".hdaLibrary.assetName"),
                         _string(raw["assetVersion"], path + ".hdaLibrary.assetVersion", nullable=True))  # type: ignore[arg-type]
    return DefinitionSource(_enum(item["kind"], _SOURCE_KINDS, path + ".kind"),
                            _string(item["packageId"], path + ".packageId", nullable=True), hda)


def _decode_parameters(
    value: Any, path: str, catalog_version: int,
) -> tuple[ParameterDefinition, ...]:
    result = []
    keys = {"token", "label", "type", "tupleSize", "tupleNames", "default", "range", "menu", "tags",
            "codeSurface", "assignable"}
    if catalog_version == VALUE_CATALOG_VERSION:
        keys.add("valueContract")
    for index, raw in enumerate(_array(value, path, 100000)):
        current = f"{path}[{index}]"
        item = _object(raw, current, keys, keys)
        tuple_size = _integer(item["tupleSize"], current + ".tupleSize", minimum=1, maximum=1024)
        tuple_names = _strings(item["tupleNames"], current + ".tupleNames")
        if tuple_names and len(tuple_names) != tuple_size:
            _fail("catalog.tuple_shape", "tupleNames must be empty or match tupleSize.", current + ".tupleNames")
        result.append(ParameterDefinition(
            _string(item["token"], current + ".token"), _string(item["label"], current + ".label"),
            _enum(item["type"], _PARM_TYPES, current + ".type"), tuple_size, tuple_names,
            _json_value(item["default"], current + ".default"),
            _decode_range(item["range"], current + ".range"), _decode_menu(item["menu"], current + ".menu"),
            _decode_tags(item["tags"], current + ".tags"),
            _enum(item["codeSurface"], _CODE_SURFACES, current + ".codeSurface"),
            _boolean(item["assignable"], current + ".assignable"),
            (
                _decode_value_contract(
                    item["valueContract"], current + ".valueContract"
                )
                if catalog_version == VALUE_CATALOG_VERSION else None
            ),
        ))
    return tuple(result)  # type: ignore[arg-type]


def _decode_value_contract(value: Any, path: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        _fail("catalog.type", "valueContract must be an object or null.", path)
    kind = value.get("kind")
    if kind == "quantity":
        result = _decode_quantity_contract(value, path)
    elif kind == "ramp":
        result = _decode_ramp_contract(value, path)
    elif kind == "multiparm":
        result = _decode_multiparm_contract(value, path)
    else:
        _fail("catalog.enum", "valueContract kind is unsupported.", path)
    return _json_value(result, path)


def _decode_quantity_contract(value: dict[str, Any], path: str) -> dict[str, Any]:
    item = _object(
        value, path,
        {"kind", "dimension", "canonicalUnit", "units"},
        {"kind", "dimension", "canonicalUnit", "units"},
    )
    units = []
    seen: set[str] = set()
    for index, raw in enumerate(_array(item["units"], path + ".units", 256)):
        current = f"{path}.units[{index}]"
        unit = _object(
            raw, current, {"unit", "scale", "offset"},
            {"unit", "scale", "offset"},
        )
        name = _string(unit["unit"], current + ".unit", maximum=128)
        if name in seen:
            _fail("catalog.duplicate", "Quantity units must be unique.", current)
        seen.add(name)
        scale = _number(unit["scale"], current + ".scale")
        if scale == 0:
            _fail("catalog.range", "Quantity unit scale cannot be zero.", current)
        units.append({
            "unit": name,
            "scale": scale,
            "offset": _number(unit["offset"], current + ".offset"),
        })
    canonical = _string(
        item["canonicalUnit"], path + ".canonicalUnit", maximum=128
    )
    if canonical not in seen:
        _fail(
            "catalog.reference",
            "canonicalUnit must appear in the quantity unit table.",
            path,
        )
    return {
        "kind": "quantity",
        "dimension": _string(item["dimension"], path + ".dimension"),
        "canonicalUnit": canonical,
        "units": units,
    }


def _decode_ramp_contract(value: dict[str, Any], path: str) -> dict[str, Any]:
    item = _object(
        value, path, {"kind", "rampKind", "allowedBases"},
        {"kind", "rampKind", "allowedBases"},
    )
    bases = _strings(item["allowedBases"], path + ".allowedBases")
    allowed = {
        "constant", "linear", "catmullrom", "monotonecubic", "bezier",
        "bspline", "hermite",
    }
    if not bases or any(basis not in allowed for basis in bases):
        _fail("catalog.enum", "Ramp basis contract is invalid.", path)
    return {
        "kind": "ramp",
        "rampKind": _enum(item["rampKind"], {"float", "color"}, path + ".rampKind"),
        "allowedBases": list(bases),
    }


def _decode_multiparm_contract(value: dict[str, Any], path: str) -> dict[str, Any]:
    item = _object(
        value, path,
        {"kind", "instanceStart", "minInstances", "maxInstances", "fields"},
        {"kind", "instanceStart", "minInstances", "maxInstances", "fields"},
    )
    instance_start = _integer(
        item["instanceStart"], path + ".instanceStart", maximum=4096
    )
    minimum = _integer(
        item["minInstances"], path + ".minInstances", maximum=4096
    )
    maximum = _integer(
        item["maxInstances"], path + ".maxInstances", maximum=4096
    )
    if minimum > maximum:
        _fail("catalog.range", "Multiparm instance bounds are inverted.", path)
    fields = []
    names: set[str] = set()
    templates: set[str] = set()
    for index, raw in enumerate(_array(item["fields"], path + ".fields", 256)):
        current = f"{path}.fields[{index}]"
        field_value = _object(
            raw, current,
            {"name", "tokenTemplate", "valueType", "tupleSize", "elementType"},
            {"name", "tokenTemplate", "valueType", "tupleSize", "elementType"},
        )
        name = _string(field_value["name"], current + ".name")
        template = _string(
            field_value["tokenTemplate"], current + ".tokenTemplate"
        )
        if (
            _IDENTIFIER.fullmatch(name) is None
            or template.count("#") != 1
            or name in names
            or template in templates
        ):
            _fail(
                "catalog.duplicate",
                "Multiparm field identities/templates are invalid.",
                current,
            )
        names.add(name)
        templates.add(template)
        fields.append({
            "name": name,
            "tokenTemplate": template,
            "valueType": _enum(
                field_value["valueType"],
                _PARM_TYPES - {"button", "ramp", "multiparm"},
                current + ".valueType",
            ),
            "tupleSize": _integer(
                field_value["tupleSize"], current + ".tupleSize",
                minimum=1, maximum=1024,
            ),
            "elementType": _string(
                field_value["elementType"],
                current + ".elementType",
                nullable=True,
            ),
        })
    return {
        "kind": "multiparm",
        "instanceStart": instance_start,
        "minInstances": minimum,
        "maxInstances": maximum,
        "fields": fields,
    }


def _decode_range(value: Any, path: str) -> ParmRange | None:
    if value is None:
        return None
    item = _object(value, path, {"min", "max", "minInclusive", "maxInclusive"},
                   {"min", "max", "minInclusive", "maxInclusive"})
    minimum = _number(item["min"], path + ".min", nullable=True)
    maximum = _number(item["max"], path + ".max", nullable=True)
    if minimum is not None and maximum is not None and minimum > maximum:
        _fail("catalog.range", "Range minimum exceeds maximum.", path)
    return ParmRange(minimum, maximum, _boolean(item["minInclusive"], path + ".minInclusive"),
                     _boolean(item["maxInclusive"], path + ".maxInclusive"))


def _decode_menu(value: Any, path: str) -> tuple[MenuItem, ...]:
    result = []
    for index, raw in enumerate(_array(value, path, 10000)):
        current = f"{path}[{index}]"
        item = _object(raw, current, {"token", "label"}, {"token", "label"})
        result.append(MenuItem(_string(item["token"], current + ".token"),
                               _string(item["label"], current + ".label")))
    if len({item.token for item in result}) != len(result):
        _fail("catalog.duplicate", "Menu tokens must be unique.", path)
    return tuple(result)  # type: ignore[arg-type]


def _decode_connectors(value: Any, path: str) -> tuple[ConnectorDefinition, ...]:
    result = []
    keys = {"index", "name", "label", "cardinality", "dataTypes", "categories"}
    for index, raw in enumerate(_array(value, path, 10000)):
        current = f"{path}[{index}]"
        item = _object(raw, current, keys, keys)
        port_index = _integer(item["index"], current + ".index", nullable=True)
        name = _string(item["name"], current + ".name", nullable=True)
        if port_index is None and name is None:
            _fail("catalog.connector_identity", "A connector requires an index or name.", current)
        result.append(ConnectorDefinition(port_index, name, _string(item["label"], current + ".label"),
                                          _enum(item["cardinality"], _CARDINALITIES, current + ".cardinality"),
                                          _strings(item["dataTypes"], current + ".dataTypes"),
                                          _strings(item["categories"], current + ".categories")))
    indexes = [item.index for item in result if item.index is not None]
    names = [item.name for item in result if item.name is not None]
    if len(set(indexes)) != len(indexes):
        _fail("catalog.duplicate", "Connector indexes must be unique.", path)
    if len(set(names)) != len(names):
        _fail("catalog.duplicate", "Connector names must be unique.", path)
    return tuple(result)  # type: ignore[arg-type]


def _validate_relations(snapshot: CatalogSnapshot) -> None:
    categories = {item.name for item in snapshot.categories}
    if len(categories) != len(snapshot.categories):
        _fail("catalog.duplicate", "Category names must be unique.", "$.categories")
    packages_by_id = {item.identifier: item for item in snapshot.packages}
    packages = set(packages_by_id)
    if len(packages) != len(snapshot.packages):
        _fail("catalog.duplicate", "Package IDs must be unique.", "$.packages")
    identities = {(item.category, item.qualified_name) for item in snapshot.operators}
    if len(identities) != len(snapshot.operators):
        _fail("catalog.duplicate", "Operator category/name identities must be unique.", "$.operators")
    for index, operator in enumerate(snapshot.operators):
        path = f"$.operators[{index}]"
        _validate_operator_source(operator, categories, packages_by_id, path)
        for parameter in operator.parameters:
            _validate_parameter_relation(parameter, path + ".parameters")
            _validate_value_contract_relation(parameter, path + ".parameters")
        for connector in (*operator.inputs, *operator.outputs):
            unknown_categories = set(connector.categories) - categories
            if unknown_categories:
                _fail("catalog.reference", f"Unknown connector category {sorted(unknown_categories)[0]}.", path)


def _validate_operator_source(
    operator: OperatorDefinition,
    categories: set[str],
    packages_by_id: dict[str, PackageDefinition],
    path: str,
) -> None:
    source = operator.source
    package_id = source.package_id
    if operator.category not in categories:
        _fail("catalog.reference", f"Unknown category {operator.category}.", path + ".category")
    if package_id is not None and package_id not in packages_by_id:
        _fail("catalog.reference", f"Unknown package {package_id}.", path + ".source.packageId")
    if source.kind in {"package", "labs"} and package_id is None:
        _fail("catalog.reference", "Package and Labs definitions require packageId.", path + ".source.packageId")
    if (
        source.kind in {"package", "labs"}
        and package_id is not None
        and packages_by_id[package_id].kind != source.kind
    ):
        _fail("catalog.reference", "Definition source kind must match its package kind.", path + ".source")
    if source.kind == "builtin" and package_id is not None:
        _fail("catalog.reference", "Builtin definitions cannot declare packageId.", path + ".source.packageId")
    if source.kind == "hda" and source.hda_library is None:
        _fail("catalog.hda", "HDA definitions require hdaLibrary metadata.", path + ".source")
    if source.kind != "hda" and source.hda_library is not None:
        _fail("catalog.hda", "Only HDA definitions may include hdaLibrary metadata.", path + ".source")


def _validate_parameter_relation(parameter: ParameterDefinition, path: str) -> None:
    value_type = parameter.value_type
    if parameter.tuple_size == 1 and parameter.tuple_names:
        _fail("catalog.tuple_shape", "Scalar parameters cannot declare tupleNames.", path)
    if value_type == "tuple" and parameter.tuple_size < 2:
        _fail("catalog.tuple_shape", "Tuple parameters require tupleSize >= 2.", path)
    if value_type in {"code", "button", "ramp", "multiparm"} and parameter.tuple_size != 1:
        _fail("catalog.tuple_shape", f"{value_type} parameters require tupleSize 1.", path)
    _validate_parameter_menu(parameter, path)
    if value_type in {"button", "ramp", "multiparm"} and parameter.assignable:
        _fail("catalog.action", f"{value_type} parameters cannot be ordinary assignments in HocusScript 0.1.", path)
    _validate_parameter_default(parameter, path)
    if parameter.code_surface != "none" and value_type != "code":
        _fail("catalog.code_surface", "Only code parameters may declare a code surface.", path)
    if value_type == "code" and parameter.code_surface == "none":
        _fail("catalog.code_surface", "Code parameters require a declared code surface.", path)


def _validate_value_contract_relation(
    parameter: ParameterDefinition, path: str,
) -> None:
    contract = parameter.value_contract
    if contract is None:
        return
    kind = contract["kind"]
    if kind == "quantity" and parameter.value_type not in {"int", "float", "tuple"}:
        _fail(
            "catalog.value_contract",
            "Quantity contracts require numeric parameters.",
            path,
        )
    if kind == "ramp" and parameter.value_type != "ramp":
        _fail(
            "catalog.value_contract", "Ramp contracts require ramp parameters.", path
        )
    if kind == "multiparm" and parameter.value_type != "multiparm":
        _fail(
            "catalog.value_contract",
            "Multiparm contracts require multiparm parameters.",
            path,
        )


def _validate_parameter_menu(parameter: ParameterDefinition, path: str) -> None:
    if parameter.value_type != "menu" and parameter.menu:
        _fail("catalog.menu", "Only menu parameters may declare menu items.", path)
    if parameter.value_type == "menu" and not parameter.menu:
        _fail("catalog.menu", "Menu parameters require menu items.", path)
    if parameter.value_type != "menu" or parameter.default is None:
        return
    menu_tokens = {item.token for item in parameter.menu}
    defaults = (
        parameter.default
        if parameter.tuple_size > 1 and isinstance(parameter.default, tuple)
        else (parameter.default,)
    )
    if any(item not in menu_tokens for item in defaults):
        _fail("catalog.menu", "Menu defaults must use a declared stable token.", path)


def _validate_parameter_default(parameter: ParameterDefinition, path: str) -> None:
    if parameter.tuple_size <= 1:
        if not _default_matches_type(parameter.value_type, parameter.default):
            _fail("catalog.default", "Parameter default does not match its declared type.", path)
        return
    default = parameter.default
    if default is not None and (not isinstance(default, tuple) or len(default) != parameter.tuple_size):
        _fail("catalog.tuple_shape", "Tuple defaults must match tupleSize.", path)
    if default is not None and any(not _is_catalog_scalar(item) for item in default):
        _fail("catalog.tuple_shape", "Tuple defaults must contain scalar values.", path)
    if (
        default is not None
        and parameter.value_type != "tuple"
        and any(not _default_matches_type(parameter.value_type, item) for item in default)
    ):
        _fail("catalog.default", "Tuple default components do not match the declared type.", path)


def _is_catalog_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int, float))


def _default_matches_type(value_type: str, value: Any) -> bool:
    if value is None:
        return True
    if value_type == "bool":
        return isinstance(value, bool)
    if value_type == "int":
        return type(value) is int
    if value_type == "float":
        return type(value) in {int, float}
    if value_type in {
        "string", "menu", "code", "node_path", "parm_path", "file_path", "usd_prim_path",
        "asset_reference",
    }:
        return isinstance(value, str)
    if value_type == "button":
        return value is None
    return True
