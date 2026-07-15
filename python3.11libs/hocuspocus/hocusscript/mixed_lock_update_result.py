"""Portable receipt for leased mixed-root module lock publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lock_update_result import ModuleLockUpdateEntry
from .module_lock_plan_result import ModuleLockPlanResult, _plan_digest
from .project import MAX_LOCKED_MODULES, ModuleLockRecord, ProjectError


MIXED_MODULE_LOCK_UPDATE_KIND = "hocus-mixed-module-lock-update-v1"
MIXED_MODULE_LOCK_UPDATE_SCHEMA_URI = (
    "hocuspocus://schemas/mixed-module-lock-update/v1"
)


@dataclass(frozen=True, slots=True)
class MixedModuleLockUpdateResult:
    project_uid: str
    manifest_digest: str
    previous_lock_digest: str
    lock_digest: str
    catalog_path: str
    catalog_content_digest: str
    catalog_fingerprint: str
    external_roots_inspection_digest: str
    resolver_policy_digest: str
    entries: tuple[ModuleLockUpdateEntry, ...]
    modules: tuple[ModuleLockRecord, ...]
    added_uris: tuple[str, ...]
    removed_uris: tuple[str, ...]
    changed_uris: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.entries, tuple)
            or not self.entries
            or len(self.entries) > MAX_LOCKED_MODULES
            or any(type(item) is not ModuleLockUpdateEntry for item in self.entries)
            or not isinstance(self.modules, tuple)
            or len(self.modules) > MAX_LOCKED_MODULES
            or any(type(item) is not ModuleLockRecord for item in self.modules)
            or any(
                not isinstance(values, tuple) or len(values) > MAX_LOCKED_MODULES
                for values in (self.added_uris, self.removed_uris, self.changed_uris)
            )
        ):
            raise ProjectError("HOCUS459", "Mixed module lock update receipt is invalid.")
        unsigned_plan = {
            "valid": True,
            "kind": "hocus-module-lock-plan-v1",
            "schemaVersion": 1,
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "currentLockDigest": self.previous_lock_digest,
            "prospectiveLockDigest": self.lock_digest,
            "catalogPath": self.catalog_path,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "externalRootsInspectionDigest": self.external_roots_inspection_digest,
            "resolverPolicyDigest": self.resolver_policy_digest,
            "changed": self.changed,
            "diffAvailable": True,
            "entries": [item.to_dict() for item in self.entries],
            "moduleCount": len(self.modules),
            "modules": [item.to_dict() for item in self.modules],
            "diff": {
                "addedUris": list(self.added_uris),
                "removedUris": list(self.removed_uris),
                "changedUris": list(self.changed_uris),
            },
        }
        try:
            ModuleLockPlanResult(
                self.project_uid,
                self.manifest_digest,
                self.previous_lock_digest,
                self.lock_digest,
                self.catalog_path,
                self.catalog_content_digest,
                self.catalog_fingerprint,
                self.external_roots_inspection_digest,
                self.resolver_policy_digest,
                self.entries,
                self.modules,
                True,
                self.added_uris,
                self.removed_uris,
                self.changed_uris,
                _plan_digest(unsigned_plan),
            )
        except (ProjectError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ProjectError("HOCUS459", "Mixed module lock update receipt is invalid.") from exc

    @property
    def changed(self) -> bool:
        return self.previous_lock_digest != self.lock_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": True,
            "kind": MIXED_MODULE_LOCK_UPDATE_KIND,
            "schemaVersion": 1,
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "previousLockDigest": self.previous_lock_digest,
            "lockDigest": self.lock_digest,
            "catalogPath": self.catalog_path,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "externalRootsInspectionDigest": self.external_roots_inspection_digest,
            "resolverPolicyDigest": self.resolver_policy_digest,
            "changed": self.changed,
            "entries": [item.to_dict() for item in self.entries],
            "moduleCount": len(self.modules),
            "modules": [item.to_dict() for item in self.modules],
            "diff": {
                "available": True,
                "addedUris": list(self.added_uris),
                "removedUris": list(self.removed_uris),
                "changedUris": list(self.changed_uris),
            },
        }
