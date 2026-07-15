"""Portable, immutable result from read-only mixed-root lock planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .lock_update_result import ModuleLockUpdateEntry
from .project import (
    DIGEST_PATTERN,
    LOCK_SCHEMA_URI_V3,
    MAX_LOCKED_MODULES,
    PROJECT_UID_PATTERN,
    SEMANTIC_VERSION_PATTERN,
    ModuleLockRecord,
    ProjectError,
    _validate_relative_artifact_path,
)
from .resolved_modules import canonical_module_uri
from .module_paths import ALIAS_PATTERN, is_relative_hocus_path


MODULE_LOCK_PLAN_KIND = "hocus-module-lock-plan-v1"
MODULE_LOCK_PLAN_SCHEMA_URI = "hocuspocus://schemas/module-lock-plan/v1"
_PLAN_DOMAIN = b"hocus-module-lock-plan-v1\x00"


@dataclass(frozen=True, slots=True)
class ModuleLockPlanResult:
    project_uid: str
    manifest_digest: str
    current_lock_digest: str
    prospective_lock_digest: str
    catalog_path: str
    catalog_content_digest: str
    catalog_fingerprint: str
    external_roots_inspection_digest: str
    resolver_policy_digest: str
    entries: tuple[ModuleLockUpdateEntry, ...]
    modules: tuple[ModuleLockRecord, ...]
    diff_available: bool
    added_uris: tuple[str, ...]
    removed_uris: tuple[str, ...]
    changed_uris: tuple[str, ...]
    plan_digest: str
    def __post_init__(self) -> None:
        if not isinstance(self.project_uid, str) or PROJECT_UID_PATTERN.fullmatch(self.project_uid) is None:
            raise ProjectError("HOCUS459", "Module lock plan project UID is invalid.")
        for value in (
            self.manifest_digest, self.current_lock_digest, self.prospective_lock_digest,
            self.catalog_content_digest, self.catalog_fingerprint,
            self.external_roots_inspection_digest, self.resolver_policy_digest,
            self.plan_digest,
        ):
            if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
                raise ProjectError("HOCUS459", "Module lock plan contains an invalid digest.")
        _validate_relative_artifact_path(self.catalog_path, "catalogPath", code="HOCUS459")
        if not self.catalog_path.endswith(".json"):
            raise ProjectError("HOCUS459", "catalogPath must identify a JSON file.")
        if (
            not isinstance(self.entries, tuple)
            or not self.entries
            or len(self.entries) > MAX_LOCKED_MODULES
            or any(type(item) is not ModuleLockUpdateEntry for item in self.entries)
        ):
            raise ProjectError("HOCUS459", "Module lock plan entries are invalid.")
        entry_uris = tuple(item.entry_uri for item in self.entries)
        if entry_uris != tuple(sorted(set(entry_uris))) or any(
            canonical_module_uri(uri)[:2] != ("project", self.project_uid) for uri in entry_uris
        ):
            raise ProjectError("HOCUS459", "Module lock plan entries must be sorted project URIs.")
        if (
            not isinstance(self.modules, tuple)
            or len(self.modules) > MAX_LOCKED_MODULES
            or any(type(item) is not ModuleLockRecord for item in self.modules)
        ):
            raise ProjectError("HOCUS459", "Module lock plan modules are invalid.")
        module_uris = tuple(item.module_uri for item in self.modules)
        if module_uris != tuple(sorted(set(module_uris))):
            raise ProjectError("HOCUS459", "Module lock plan modules must be URI-sorted and unique.")
        module_uri_set = set(module_uris)
        for record in self.modules:
            identity = canonical_module_uri(record.module_uri)
            if (
                identity is None
                or record.language_version != "0.2"
                or not is_relative_hocus_path(record.source_path)
                or identity[2] != record.source_path
                or any(
                    not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None
                    for value in (
                        record.content_digest,
                        record.interface_digest,
                        record.transitive_digest,
                    )
                )
                or not isinstance(record.dependencies, tuple)
                or len(record.dependencies) > MAX_LOCKED_MODULES
                or record.dependencies != tuple(sorted(set(record.dependencies)))
                or record.module_uri in record.dependencies
                or any(canonical_module_uri(uri) is None for uri in record.dependencies)
            ):
                raise ProjectError("HOCUS459", "Module lock plan contains a noncanonical module URI.")
            if record.external_alias is None:
                if (
                    identity[:2] != ("project", self.project_uid)
                    or record.project_uid != self.project_uid
                    or any(value is not None for value in (
                        record.library_uid,
                        record.library_version,
                        record.module_manifest_digest,
                    ))
                ):
                    raise ProjectError("HOCUS459", "Local module plan provenance is invalid.")
            elif (
                identity[0] != "module"
                or record.project_uid is not None
                or identity[1] != record.library_uid
                or not isinstance(record.library_uid, str)
                or PROJECT_UID_PATTERN.fullmatch(record.library_uid) is None
                or not isinstance(record.library_version, str)
                or SEMANTIC_VERSION_PATTERN.fullmatch(record.library_version) is None
                or not isinstance(record.module_manifest_digest, str)
                or DIGEST_PATTERN.fullmatch(record.module_manifest_digest) is None
                or not isinstance(record.external_alias, str)
                or ALIAS_PATTERN.fullmatch(record.external_alias) is None
            ):
                raise ProjectError("HOCUS459", "External module plan provenance is invalid.")
        if any(
            dependency not in module_uri_set
            for record in self.modules
            for dependency in record.dependencies
        ):
            raise ProjectError("HOCUS459", "Module lock plan dependency closure is incomplete.")
        if self.diff_available is not True:
            raise ProjectError("HOCUS459", "G2 lock plans require an exact current-lock diff.")
        for values in (self.added_uris, self.removed_uris, self.changed_uris):
            if (
                not isinstance(values, tuple)
                or values != tuple(sorted(set(values)))
                or any(canonical_module_uri(uri) is None for uri in values)
            ):
                raise ProjectError("HOCUS459", "Module lock plan diff URIs are invalid.")
        prospective_uris = module_uri_set
        added, removed, changed = map(set, (
            self.added_uris, self.removed_uris, self.changed_uris,
        ))
        if (
            added & removed
            or added & changed
            or removed & changed
            or not added.issubset(prospective_uris)
            or not changed.issubset(prospective_uris)
            or removed & prospective_uris
            or self.changed != bool(added or removed or changed)
        ):
            raise ProjectError("HOCUS459", "Module lock plan diff is inconsistent.")
        if self.prospective_lock_digest != _prospective_lock_digest(self):
            raise ProjectError("HOCUS459", "Prospective lock digest is inconsistent with the plan.")
        if self.plan_digest != _plan_digest(self._unsigned_dict()):
            raise ProjectError("HOCUS459", "Module lock plan digest is inconsistent.")

    @property
    def changed(self) -> bool:
        return self.current_lock_digest != self.prospective_lock_digest

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "valid": True,
            "kind": MODULE_LOCK_PLAN_KIND,
            "schemaVersion": 1,
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "currentLockDigest": self.current_lock_digest,
            "prospectiveLockDigest": self.prospective_lock_digest,
            "catalogPath": self.catalog_path,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "externalRootsInspectionDigest": self.external_roots_inspection_digest,
            "resolverPolicyDigest": self.resolver_policy_digest,
            "changed": self.changed,
            "diffAvailable": self.diff_available,
            "entries": [item.to_dict() for item in self.entries],
            "moduleCount": len(self.modules),
            "modules": [item.to_dict() for item in self.modules],
            "diff": {
                "addedUris": list(self.added_uris),
                "removedUris": list(self.removed_uris),
                "changedUris": list(self.changed_uris),
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "planDigest": self.plan_digest}


def _prospective_lock_payload(result: ModuleLockPlanResult) -> dict[str, Any]:
    return {
        "$schema": LOCK_SCHEMA_URI_V3,
        "kind": "hocus_project_lock",
        "schemaVersion": 3,
        "projectUid": result.project_uid,
        "manifestDigest": result.manifest_digest,
        "languageVersion": "0.2",
        "catalog": {
            "schemaVersion": 1,
            "path": result.catalog_path,
            "contentDigest": result.catalog_content_digest,
            "fingerprint": result.catalog_fingerprint,
        },
        "modules": [item.to_dict() for item in result.modules],
    }


def _prospective_lock_digest(result: ModuleLockPlanResult) -> str:
    raw = json.dumps(
        _prospective_lock_payload(result), ensure_ascii=False,
        separators=(",", ":"), sort_keys=True, allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _plan_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
        sort_keys=True, allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(_PLAN_DOMAIN + raw).hexdigest()


def _build_module_lock_plan_result(
    *,
    project_uid: str,
    manifest_digest: str,
    current_lock_digest: str,
    catalog_path: str,
    catalog_content_digest: str,
    catalog_fingerprint: str,
    external_roots_inspection_digest: str,
    resolver_policy_digest: str,
    entries: tuple[ModuleLockUpdateEntry, ...],
    current_modules: tuple[ModuleLockRecord, ...],
    modules: tuple[ModuleLockRecord, ...],
) -> ModuleLockPlanResult:
    entries = tuple(sorted(entries, key=lambda item: item.entry_uri))
    modules = tuple(sorted(modules, key=lambda item: item.module_uri))
    current_by_uri = {item.module_uri: item for item in current_modules}
    future_by_uri = {item.module_uri: item for item in modules}
    added = tuple(sorted(set(future_by_uri) - set(current_by_uri)))
    removed = tuple(sorted(set(current_by_uri) - set(future_by_uri)))
    changed_uris = tuple(sorted(
        uri for uri in set(current_by_uri) & set(future_by_uri)
        if current_by_uri[uri] != future_by_uri[uri]
    ))
    lock_payload = {
        "$schema": LOCK_SCHEMA_URI_V3,
        "kind": "hocus_project_lock",
        "schemaVersion": 3,
        "projectUid": project_uid,
        "manifestDigest": manifest_digest,
        "languageVersion": "0.2",
        "catalog": {
            "schemaVersion": 1,
            "path": catalog_path,
            "contentDigest": catalog_content_digest,
            "fingerprint": catalog_fingerprint,
        },
        "modules": [item.to_dict() for item in modules],
    }
    prospective = "sha256:" + hashlib.sha256(json.dumps(
        lock_payload, ensure_ascii=False, separators=(",", ":"),
        sort_keys=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    unsigned = {
        "valid": True,
        "kind": MODULE_LOCK_PLAN_KIND,
        "schemaVersion": 1,
        "projectUid": project_uid,
        "manifestDigest": manifest_digest,
        "currentLockDigest": current_lock_digest,
        "prospectiveLockDigest": prospective,
        "catalogPath": catalog_path,
        "catalogContentDigest": catalog_content_digest,
        "catalogFingerprint": catalog_fingerprint,
        "externalRootsInspectionDigest": external_roots_inspection_digest,
        "resolverPolicyDigest": resolver_policy_digest,
        "changed": current_lock_digest != prospective,
        "diffAvailable": True,
        "entries": [item.to_dict() for item in entries],
        "moduleCount": len(modules),
        "modules": [item.to_dict() for item in modules],
        "diff": {
            "addedUris": list(added),
            "removedUris": list(removed),
            "changedUris": list(changed_uris),
        },
    }
    return ModuleLockPlanResult(
        project_uid, manifest_digest, current_lock_digest, prospective,
        catalog_path, catalog_content_digest, catalog_fingerprint,
        external_roots_inspection_digest, resolver_policy_digest,
        entries, modules, True, added, removed, changed_uris,
        _plan_digest(unsigned),
    )
