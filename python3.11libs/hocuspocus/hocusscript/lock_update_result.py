"""Typed, host-path-free receipt for resolver-derived module lock publication."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .project import LockVerificationResult, ModuleLockRecord

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_UID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ModuleLockUpdateEntry:
    entry_uri: str
    source_digest: str

    def __post_init__(self) -> None:
        from .resolved_modules import canonical_module_uri
        identity = canonical_module_uri(self.entry_uri)
        if identity is None or identity[0] != "project" or _DIGEST.fullmatch(self.source_digest) is None:
            raise ValueError("Module lock update entry provenance is invalid")

    def to_dict(self) -> dict[str, str]:
        return {"entryUri": self.entry_uri, "sourceDigest": self.source_digest}


@dataclass(frozen=True, slots=True)
class ModuleLockUpdateResult:
    project_uid: str
    manifest_digest: str
    previous_lock_digest: str | None
    lock_digest: str
    catalog_content_digest: str
    catalog_fingerprint: str
    entries: tuple[ModuleLockUpdateEntry, ...]
    modules: tuple[ModuleLockRecord, ...]
    diff_available: bool
    added_uris: tuple[str, ...]
    removed_uris: tuple[str, ...]
    changed_uris: tuple[str, ...]

    def __post_init__(self) -> None:
        if _UID.fullmatch(self.project_uid) is None:
            raise ValueError("ModuleLockUpdateResult.project_uid is invalid")
        for value in (
            self.manifest_digest, self.lock_digest,
            self.catalog_content_digest, self.catalog_fingerprint,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("ModuleLockUpdateResult digests must be lowercase SHA-256 values")
        if self.previous_lock_digest is not None and _DIGEST.fullmatch(self.previous_lock_digest) is None:
            raise ValueError("ModuleLockUpdateResult.previous_lock_digest is invalid")
        uris = tuple(item.module_uri for item in self.modules)
        if uris != tuple(sorted(set(uris))):
            raise ValueError("ModuleLockUpdateResult.modules must be URI-sorted and unique")
        entry_uris = tuple(item.entry_uri for item in self.entries)
        if entry_uris != tuple(sorted(set(entry_uris))):
            raise ValueError("ModuleLockUpdateResult.entries must be URI-sorted and unique")
        from .resolved_modules import canonical_module_uri
        if any(canonical_module_uri(item.entry_uri)[:2] != ("project", self.project_uid) for item in self.entries):
            raise ValueError("Module lock update entries must belong to project_uid")
        if type(self.diff_available) is not bool:
            raise ValueError("ModuleLockUpdateResult.diff_available must be a boolean")
        for values in (self.added_uris, self.removed_uris, self.changed_uris):
            if values != tuple(sorted(set(values))):
                raise ValueError("Module lock diff URI sets must be sorted and unique")

    @property
    def changed(self) -> bool:
        return self.previous_lock_digest != self.lock_digest

    @property
    def verification(self) -> LockVerificationResult:
        return LockVerificationResult(
            self.project_uid, self.manifest_digest, self.lock_digest, self.modules,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": True,
            "kind": "hocus_module_lock_update",
            "schemaVersion": 1,
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "previousLockDigest": self.previous_lock_digest,
            "lockDigest": self.lock_digest,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "changed": self.changed,
            "entries": [item.to_dict() for item in self.entries],
            "moduleCount": len(self.modules),
            "modules": [item.to_dict() for item in self.modules],
            "diff": {
                "available": self.diff_available,
                "addedUris": list(self.added_uris),
                "removedUris": list(self.removed_uris),
                "changedUris": list(self.changed_uris),
            },
        }

    @classmethod
    def from_verifications(
        cls,
        before: LockVerificationResult | None,
        after: LockVerificationResult,
        *,
        catalog_content_digest: str,
        catalog_fingerprint: str,
        entries: tuple[ModuleLockUpdateEntry, ...],
        previous_lock_digest: str | None,
    ) -> "ModuleLockUpdateResult":
        if before is not None and (
            before.project_uid != after.project_uid or before.manifest_digest != after.manifest_digest
        ):
            raise ValueError("Module lock update changed project or manifest identity")
        if before is not None and previous_lock_digest != before.lock_digest:
            raise ValueError("previous_lock_digest conflicts with before verification")
        before_by_uri = {item.module_uri: item for item in before.modules} if before is not None else {}
        after_by_uri = {item.module_uri: item for item in after.modules}
        diff_available = before is not None or previous_lock_digest is None
        added = tuple(sorted(set(after_by_uri) - set(before_by_uri))) if diff_available else ()
        removed = tuple(sorted(set(before_by_uri) - set(after_by_uri))) if diff_available else ()
        changed = tuple(sorted(
            uri for uri in set(before_by_uri) & set(after_by_uri)
            if before_by_uri[uri] != after_by_uri[uri]
        )) if diff_available else ()
        return cls(
            after.project_uid,
            after.manifest_digest,
            previous_lock_digest,
            after.lock_digest,
            catalog_content_digest,
            catalog_fingerprint,
            tuple(sorted(entries, key=lambda item: item.entry_uri)),
            tuple(sorted(after.modules, key=lambda item: item.module_uri)),
            diff_available,
            added,
            removed,
            changed,
        )
