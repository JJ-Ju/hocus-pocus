"""Strict project-lock decoding and module-record validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .compiler import SUPPORTED_LANGUAGE_VERSIONS
from .project import (
    DIGEST_PATTERN,
    LOCK_SCHEMA_URI,
    LOCK_SCHEMA_URI_V2,
    LOCK_SCHEMA_URI_V3,
    LOCK_SCHEMA_URI_V4,
    MAX_LOCK_BYTES_V3,
    MAX_LOCKED_MODULES,
    MAX_LOCK_METADATA_VALUES_V3,
    MAX_MANIFEST_BYTES,
    MAX_METADATA_DEPTH,
    MAX_METADATA_VALUES,
    PROJECT_LOCK_NAME,
    PROJECT_UID_PATTERN,
    ExternalLibraryAlias,
    ModuleLockRecord,
    ProjectError,
    _digest,
    _portable_path_key,
    _read_bounded,
    _validate_json_complexity,
)
from .project_manifest import _validate_relative_artifact_path


def load_lock(
    path: Path,
    *,
    project_uid: str,
    manifest_digest: str,
    language_version: str,
    manifest_version: int,
    catalog_relative_path: str | None,
    external_aliases: tuple[ExternalLibraryAlias, ...] = (),
) -> tuple[str, dict[str, Any] | None, tuple[ModuleLockRecord, ...]]:
    payload = _decode_lock_payload(path, manifest_version)
    lock_version = _validate_lock_envelope(payload, manifest_version)
    _validate_lock_identity(
        payload, lock_version, project_uid, manifest_digest, language_version
    )
    catalog, modules = _validate_lock_contents(
        payload, lock_version, project_uid, catalog_relative_path, external_aliases
    )
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")
    return _digest(canonical), catalog, modules


def _decode_lock_payload(path: Path, manifest_version: int) -> Any:
    lock_limit = MAX_LOCK_BYTES_V3 if manifest_version in {3, 4} else MAX_MANIFEST_BYTES
    raw = _read_bounded(path, lock_limit, "HOCUS410", "Project lock")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProjectError, RecursionError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("HOCUS422", f"Invalid {PROJECT_LOCK_NAME}: {exc}") from exc
    _validate_json_complexity(
        payload,
        max_values=MAX_LOCK_METADATA_VALUES_V3
        if manifest_version in {3, 4}
        else MAX_METADATA_VALUES,
    )
    return payload


def _validate_lock_envelope(payload: Any, manifest_version: int) -> int:
    expected_keys = {
        "$schema", "kind", "schemaVersion", "projectUid", "manifestDigest",
        "languageVersion", "catalog", "modules",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} has missing or unknown fields.")
    lock_version = manifest_version if manifest_version in {2, 3, 4} else 1
    schema_uri = {
        1: LOCK_SCHEMA_URI,
        2: LOCK_SCHEMA_URI_V2,
        3: LOCK_SCHEMA_URI_V3,
        4: LOCK_SCHEMA_URI_V4,
    }[lock_version]
    if (
        payload["$schema"] != schema_uri
        or payload["kind"] != "hocus_project_lock"
        or type(payload["schemaVersion"]) is not int
        or payload["schemaVersion"] != lock_version
    ):
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} uses an unsupported schema or kind.")
    return lock_version


def _validate_lock_identity(
    payload: dict[str, Any],
    lock_version: int,
    project_uid: str,
    manifest_digest: str,
    language_version: str,
) -> None:
    if not isinstance(payload["projectUid"], str) or not PROJECT_UID_PATTERN.fullmatch(payload["projectUid"]):
        raise ProjectError("HOCUS422", "Lock projectUid is invalid.")
    if not isinstance(payload["manifestDigest"], str) or not DIGEST_PATTERN.fullmatch(payload["manifestDigest"]):
        raise ProjectError("HOCUS422", "Lock manifestDigest must be a lowercase SHA-256 digest.")
    if not _valid_lock_language(payload["languageVersion"], lock_version):
        raise ProjectError("HOCUS422", "Lock languageVersion is unsupported.")
    stale: dict[str, Any] = {}
    expected_values = (
        ("projectUid", project_uid),
        ("manifestDigest", manifest_digest),
        ("languageVersion", language_version),
    )
    for key, expected in expected_values:
        if payload[key] != expected:
            stale[key] = {"expected": expected, "actual": payload[key]}
    if stale:
        raise ProjectError("HOCUS424", f"{PROJECT_LOCK_NAME} is stale.", details=stale)


def _valid_lock_language(value: Any, lock_version: int) -> bool:
    if lock_version == 3:
        return value == "0.2"
    if lock_version == 4:
        return value == "0.3"
    return isinstance(value, str) and value in SUPPORTED_LANGUAGE_VERSIONS


def _validate_lock_contents(
    payload: dict[str, Any],
    lock_version: int,
    project_uid: str,
    catalog_relative_path: str | None,
    external_aliases: tuple[ExternalLibraryAlias, ...],
) -> tuple[dict[str, Any] | None, tuple[ModuleLockRecord, ...]]:
    if lock_version == 1:
        if payload["catalog"] is not None or payload["modules"] != []:
            raise ProjectError(
                "HOCUS425", "Lock v1 reserves catalog as null and modules as empty until HS2/HS6."
            )
        return None, ()
    catalog = _validate_catalog_lock(payload["catalog"], catalog_relative_path)
    if lock_version == 2:
        if payload["modules"] != []:
            raise ProjectError("HOCUS425", "Lock v2 reserves modules as empty until HS6.")
        return catalog, ()
    modules = validate_module_locks(
        payload["modules"],
        project_uid=project_uid,
        external_aliases=external_aliases,
        expected_language_version="0.3" if lock_version == 4 else "0.2",
    )
    return catalog, modules


def _validate_catalog_lock(value: Any, expected_path: str | None) -> dict[str, Any]:
    keys = {"schemaVersion", "path", "contentDigest", "fingerprint"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ProjectError("HOCUS425", "Lock v2 catalog pin has missing or unknown fields.")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ProjectError("HOCUS425", "Lock v2 catalog schemaVersion must be 1.")
    _validate_relative_artifact_path(value["path"], "catalog.path", code="HOCUS425")
    if expected_path is None or value["path"] != expected_path:
        raise ProjectError(
            "HOCUS425",
            "Lock v2 catalog path does not match the project manifest.",
            details={"expected": expected_path, "actual": value["path"]},
        )
    for key in ("contentDigest", "fingerprint"):
        if not isinstance(value[key], str) or not DIGEST_PATTERN.fullmatch(value[key]):
            raise ProjectError(
                "HOCUS425", f"Lock v2 catalog {key} must be a lowercase SHA-256 digest."
            )
    return dict(value)


def validate_module_locks(
    value: Any,
    *,
    project_uid: str,
    external_aliases: tuple[ExternalLibraryAlias, ...],
    expected_language_version: str = "0.2",
) -> tuple[ModuleLockRecord, ...]:
    if not isinstance(value, list) or len(value) > MAX_LOCKED_MODULES:
        raise ProjectError("HOCUS451", "Lock v3 modules must be a bounded array.")
    state = _ModuleValidationState(project_uid, external_aliases, expected_language_version)
    records = tuple(state.validate(item, index) for index, item in enumerate(value))
    state.validate_collection(records)
    return records


class _ModuleValidationState:
    def __init__(
        self,
        project_uid: str,
        external_aliases: tuple[ExternalLibraryAlias, ...],
        language_version: str,
    ):
        self.project_uid = project_uid
        self.alias_map = {item.alias: item for item in external_aliases}
        self.language_version = language_version
        self.seen_uris: set[str] = set()
        self.seen_paths: dict[tuple[str, str], str] = {}
        self.library_identities: dict[str, tuple[str, str]] = {}

    def validate(self, item: Any, index: int) -> ModuleLockRecord:
        pointer = f"modules[{index}]"
        expected_keys = {
            "moduleUri", "projectUid", "libraryUid", "libraryVersion",
            "moduleManifestDigest", "languageVersion", "sourcePath", "contentDigest",
            "interfaceDigest", "transitiveDigest", "dependencies", "externalAlias",
        }
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ProjectError("HOCUS451", f"{pointer} has missing or unknown fields.")
        source_path = _validate_module_path(item["sourcePath"], pointer)
        expected_uri = self._validate_identity(item, pointer, source_path)
        self._validate_language_and_uri(item, pointer, expected_uri, source_path)
        dependencies = _validate_module_fields(item, pointer, expected_uri)
        return ModuleLockRecord(
            expected_uri, item["projectUid"], item["libraryUid"], item["libraryVersion"],
            item["moduleManifestDigest"], item["languageVersion"], source_path,
            item["contentDigest"], item["interfaceDigest"], item["transitiveDigest"],
            tuple(dependencies), item["externalAlias"],
        )

    def _validate_identity(
        self,
        item: dict[str, Any],
        pointer: str,
        source_path: str,
    ) -> str:
        alias = item["externalAlias"]
        if alias is None:
            if (
                item["projectUid"] != self.project_uid
                or any(item[key] is not None for key in (
                    "libraryUid", "libraryVersion", "moduleManifestDigest"
                ))
            ):
                raise ProjectError(
                    "HOCUS451", f"{pointer} has invalid local-project identity fields."
                )
            return f"hocus-project://{self.project_uid}/{quote(source_path, safe='/-._~')}"
        return self._validate_external_identity(item, pointer, source_path, alias)

    def _validate_external_identity(
        self,
        item: dict[str, Any],
        pointer: str,
        source_path: str,
        alias: Any,
    ) -> str:
        alias_record = self.alias_map.get(alias) if isinstance(alias, str) else None
        if (
            alias_record is None
            or item["projectUid"] is not None
            or item["libraryUid"] != alias_record.library_uid
            or item["libraryVersion"] != alias_record.library_version
            or not isinstance(item["moduleManifestDigest"], str)
            or not DIGEST_PATTERN.fullmatch(item["moduleManifestDigest"])
            or (
                alias_record.expected_module_manifest_digest is not None
                and item["moduleManifestDigest"] != alias_record.expected_module_manifest_digest
            )
        ):
            raise ProjectError(
                "HOCUS451", f"{pointer}.externalAlias identity does not match the manifest."
            )
        identity = (item["libraryVersion"], item["moduleManifestDigest"])
        prior = self.library_identities.get(alias_record.library_uid)
        if prior is not None and prior != identity:
            raise ProjectError(
                "HOCUS451",
                f"{pointer} conflicts with another version or manifest of the same library UID.",
            )
        self.library_identities[alias_record.library_uid] = identity
        return f"hocus-module://{alias_record.library_uid}/{quote(source_path, safe='/-._~')}"

    def _validate_language_and_uri(
        self,
        item: dict[str, Any],
        pointer: str,
        expected_uri: str,
        source_path: str,
    ) -> None:
        if item["languageVersion"] != self.language_version:
            raise ProjectError(
                "HOCUS451", f"{pointer}.languageVersion must be {self.language_version}."
            )
        if item["moduleUri"] != expected_uri or expected_uri in self.seen_uris:
            raise ProjectError("HOCUS451", f"{pointer}.moduleUri is noncanonical or duplicated.")
        alias = item["externalAlias"]
        owner = ("project", self.project_uid) if alias is None else ("library", item["libraryUid"])
        portable_key = (f"{owner[0]}:{owner[1]}", _portable_path_key(source_path))
        prior_uri = self.seen_paths.get(portable_key)
        if prior_uri is not None:
            raise ProjectError(
                "HOCUS451",
                f"{pointer}.sourcePath aliases another portable module path.",
                details={"moduleUri": expected_uri, "conflictsWith": prior_uri},
            )
        self.seen_paths[portable_key] = expected_uri
        self.seen_uris.add(expected_uri)

    def validate_collection(self, records: tuple[ModuleLockRecord, ...]) -> None:
        if [item.module_uri for item in records] != sorted(self.seen_uris):
            raise ProjectError("HOCUS451", "Lock v3 modules must be sorted by moduleUri.")
        for record in records:
            missing = set(record.dependencies) - self.seen_uris
            if missing:
                raise ProjectError(
                    "HOCUS451", "Module dependencies must reference records in the same lock.",
                    details={"moduleUri": record.module_uri, "missing": sorted(missing)},
                )
        _reject_module_cycles(records)


def _validate_module_path(source_path: Any, pointer: str) -> str:
    _validate_relative_artifact_path(source_path, f"{pointer}.sourcePath", code="HOCUS451")
    if not source_path.endswith(".hocus"):
        raise ProjectError("HOCUS451", f"{pointer}.sourcePath must identify a .hocus file.")
    return source_path


def _validate_module_fields(
    item: dict[str, Any],
    pointer: str,
    expected_uri: str,
) -> list[str]:
    for key in ("contentDigest", "interfaceDigest", "transitiveDigest"):
        if not isinstance(item[key], str) or not DIGEST_PATTERN.fullmatch(item[key]):
            raise ProjectError(
                "HOCUS451", f"{pointer}.{key} must be a lowercase SHA-256 digest."
            )
    dependencies = item["dependencies"]
    if (
        not isinstance(dependencies, list)
        or len(dependencies) > MAX_LOCKED_MODULES
        or any(not isinstance(dependency, str) or len(dependency) > 8192 for dependency in dependencies)
        or dependencies != sorted(set(dependencies))
        or expected_uri in dependencies
    ):
        raise ProjectError(
            "HOCUS451",
            f"{pointer}.dependencies must be sorted, unique, and non-self-referential.",
        )
    return dependencies


def _reject_module_cycles(records: Iterable[ModuleLockRecord]) -> None:
    graph = {item.module_uri: item.dependencies for item in records}
    state: dict[str, int] = {uri: 0 for uri in graph}
    postorder: list[str] = []
    for root in sorted(graph):
        if state[root] != 0:
            continue
        state[root] = 1
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            uri, index = stack[-1]
            dependencies = graph[uri]
            if index >= len(dependencies):
                stack.pop()
                state[uri] = 2
                postorder.append(uri)
                continue
            dependency = dependencies[index]
            stack[-1] = (uri, index + 1)
            dependency_state = state[dependency]
            if dependency_state == 1:
                raise ProjectError("HOCUS451", "Module lock dependency graph contains a cycle.")
            if dependency_state == 0:
                state[dependency] = 1
                stack.append((dependency, 0))
    _validate_module_depths(graph, postorder)


def _validate_module_depths(
    graph: dict[str, tuple[str, ...]],
    postorder: list[str],
) -> None:
    depths: dict[str, int] = {}
    for uri in postorder:
        depth = 1 + max((depths[dependency] for dependency in graph[uri]), default=0)
        if depth > MAX_METADATA_DEPTH:
            raise ProjectError(
                "HOCUS451",
                f"Module lock dependency depth exceeds {MAX_METADATA_DEPTH}.",
                details={"moduleUri": uri, "depth": depth},
            )
        depths[uri] = depth


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ProjectError(
                "HOCUS422", f"{PROJECT_LOCK_NAME} contains duplicate key {key!r}."
            )
        output[key] = value
    return output


def _reject_json_constant(value: str) -> Any:
    raise ProjectError(
        "HOCUS422", f"{PROJECT_LOCK_NAME} contains non-finite constant {value}."
    )
