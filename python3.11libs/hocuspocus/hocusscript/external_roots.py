"""Explicit, read-only inspection of approved external HocusScript library roots."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import islice
from os import PathLike, fspath
from pathlib import Path
from typing import Any, Callable

from .module_paths import ALIAS_PATTERN, is_relative_hocus_path
from .modules import (
    MAX_MODULE_ENTRIES,
    MAX_MODULE_MANIFEST_BYTES,
    ModuleManifest,
    decode_module_manifest,
)
from .project import (
    DIGEST_PATTERN,
    MAX_EXTERNAL_ALIASES,
    PROJECT_UID_PATTERN,
    SEMANTIC_VERSION_PATTERN,
    ExternalLibraryAlias,
    ProjectContext,
    ProjectError,
    _is_contained,
    _read_bounded_stable,
)


EXTERNAL_ROOTS_INSPECTION_KIND = "hocus-external-module-roots-inspection-v1"
EXTERNAL_ROOTS_INSPECTION_SCHEMA_URI = (
    "hocuspocus://schemas/external-module-roots-inspection/v1"
)
MODULE_MANIFEST_NAME = "hocus.module.toml"
_WINDOWS_REPARSE_ATTRIBUTE = 0x400
_INSPECTION_DIGEST_DOMAIN = b"hocus-external-module-roots-inspection-v1\x00"


@dataclass(frozen=True, slots=True)
class ExternalLibraryRootPin:
    """Portable identity derived from one explicitly approved native root."""

    alias: str
    library_uid: str
    library_version: str
    module_manifest_digest: str
    entry_modules: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alias, str)
            or ALIAS_PATTERN.fullmatch(self.alias) is None
            or not isinstance(self.library_uid, str)
            or PROJECT_UID_PATTERN.fullmatch(self.library_uid) is None
            or not isinstance(self.library_version, str)
            or SEMANTIC_VERSION_PATTERN.fullmatch(self.library_version) is None
            or not isinstance(self.module_manifest_digest, str)
            or DIGEST_PATTERN.fullmatch(self.module_manifest_digest) is None
            or not isinstance(self.entry_modules, tuple)
            or not self.entry_modules
            or len(self.entry_modules) > MAX_MODULE_ENTRIES
            or any(not is_relative_hocus_path(item) for item in self.entry_modules)
            or self.entry_modules != tuple(sorted(set(self.entry_modules)))
        ):
            raise ProjectError("HOCUS458", "External library root pin is invalid.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "libraryUid": self.library_uid,
            "libraryVersion": self.library_version,
            "moduleManifestDigest": self.module_manifest_digest,
            "entryModules": list(self.entry_modules),
        }


@dataclass(frozen=True, slots=True)
class ExternalModuleRootsInspection:
    """Host-path-free receipt for one exact project/root inspection."""

    project_uid: str
    project_manifest_digest: str
    project_lock_digest: str
    catalog_content_digest: str
    catalog_fingerprint: str
    libraries: tuple[ExternalLibraryRootPin, ...]
    inspection_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.project_uid, str)
            or PROJECT_UID_PATTERN.fullmatch(self.project_uid) is None
            or any(
                not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None
                for value in (
                    self.project_manifest_digest,
                    self.project_lock_digest,
                    self.catalog_content_digest,
                    self.catalog_fingerprint,
                    self.inspection_digest,
                )
            )
            or not isinstance(self.libraries, tuple)
            or not self.libraries
            or len(self.libraries) > MAX_EXTERNAL_ALIASES
            or any(type(item) is not ExternalLibraryRootPin for item in self.libraries)
            or tuple(item.alias for item in self.libraries)
            != tuple(sorted(item.alias for item in self.libraries))
            or len({item.alias for item in self.libraries}) != len(self.libraries)
            or len({item.library_uid for item in self.libraries}) != len(self.libraries)
        ):
            raise ProjectError("HOCUS458", "External module roots inspection is invalid.")
        if self.inspection_digest != _inspection_digest(self._unsigned_dict()):
            raise ProjectError("HOCUS458", "External module roots inspection digest is invalid.")

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "kind": EXTERNAL_ROOTS_INSPECTION_KIND,
            "schemaVersion": 1,
            "projectUid": self.project_uid,
            "projectManifestDigest": self.project_manifest_digest,
            "projectLockDigest": self.project_lock_digest,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "libraries": [item.to_dict() for item in self.libraries],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "inspectionDigest": self.inspection_digest}


@dataclass(frozen=True, slots=True)
class _ValidatedExternalRoot:
    alias: str
    pin: ExternalLibraryRootPin
    root: Path = field(repr=False, compare=False)
    manifest_path: Path = field(repr=False, compare=False)
    manifest_bytes: bytes = field(repr=False, compare=False)
    manifest_was_pre_pinned: bool = field(repr=False, compare=False)
    root_identity: tuple[int, int, int] = field(repr=False, compare=False)
    manifest_identity: tuple[int, int, int] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _ValidatedExternalModuleRoots:
    """Private native-path session for later resolver/lock-planner reuse."""

    inspection: ExternalModuleRootsInspection
    roots: tuple[_ValidatedExternalRoot, ...] = field(repr=False, compare=False)
    lane: tuple[int, str, int] = field(repr=False)

    def root_for_alias(self, alias: str, *, require_manifest_pin: bool = True) -> Path:
        for item in self.roots:
            if item.alias == alias:
                if require_manifest_pin and not item.manifest_was_pre_pinned:
                    raise ProjectError(
                        "HOCUS458",
                        "External alias was inspected but its module manifest was not pre-pinned.",
                    )
                return item.root
        raise ProjectError("HOCUS458", "External module alias is not approved.")


def inspect_external_module_roots(
    project_directory: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ExternalModuleRootsInspection:
    """Inspect explicit alias roots without enabling resolution or writing state."""

    return _validate_external_module_roots(
        project_directory, module_roots, cancelled=cancelled,
    ).inspection


def inspect_control_external_module_roots(
    project_directory: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ExternalModuleRootsInspection:
    """Inspect exact module-manifest-v2 roots for one language-0.3 project."""

    return _validate_control_external_module_roots(
        project_directory,
        module_roots,
        cancelled=cancelled,
    ).inspection


def _validate_external_module_roots(
    project_directory: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> _ValidatedExternalModuleRoots:
    return _validate_external_module_roots_lane(
        project_directory,
        module_roots,
        project_manifest_version=3,
        language_version="0.2",
        module_manifest_version=1,
        cancelled=cancelled,
    )


def _validate_control_external_module_roots(
    project_directory: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> _ValidatedExternalModuleRoots:
    preview = ProjectContext.load(project_directory, validate_lock=False)
    lane = {
        (4, "0.3"): (4, "0.3", 2),
        (5, "0.4"): (5, "0.4", 3),
    }.get((preview.manifest_version, preview.language_version))
    if lane is None:
        raise ProjectError(
            "HOCUS458",
            "Control external roots require a schema-v4/v5 control project.",
        )
    return _validate_external_module_roots_lane(
        project_directory,
        module_roots,
        project_manifest_version=lane[0],
        language_version=lane[1],
        module_manifest_version=lane[2],
        cancelled=cancelled,
    )


def _validate_external_module_roots_lane(
    project_directory: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    project_manifest_version: int,
    language_version: str,
    module_manifest_version: int,
    cancelled: Callable[[], bool] | None,
) -> _ValidatedExternalModuleRoots:
    lane = (
        project_manifest_version,
        language_version,
        module_manifest_version,
    )
    authored_roots = _bounded_authored_roots(module_roots, cancelled)
    _cancel(cancelled)
    context = ProjectContext.load(project_directory, validate_lock=True)
    _cancel(cancelled)
    if (
        context.manifest_version != project_manifest_version
        or context.language_version != language_version
        or context.uid is None
        or context.manifest_digest is None
        or context.lock_digest is None
        or context.catalog_content_digest is None
        or context.catalog_fingerprint is None
    ):
        raise ProjectError(
            "HOCUS458",
            "External roots inspection requires the exact fully pinned project carrier lane.",
            details={
                "projectManifestVersion": project_manifest_version,
                "languageVersion": language_version,
                "moduleManifestVersion": module_manifest_version,
            },
        )
    aliases = {item.alias: item for item in context.external_aliases}
    if not aliases:
        raise ProjectError("HOCUS458", "Project declares no external aliases to inspect.")
    if set(authored_roots) != set(aliases):
        raise ProjectError(
            "HOCUS458",
            "module_roots must exactly cover the project's declared external aliases.",
            details={
                "missingAliases": sorted(set(aliases) - set(authored_roots)),
                "unknownAliases": sorted(set(authored_roots) - set(aliases)),
            },
        )
    library_uids = [item.library_uid for item in aliases.values()]
    if len(set(library_uids)) != len(library_uids):
        raise ProjectError(
            "HOCUS458",
            "Active external root approval requires one alias per library UID.",
        )

    project_root = context.root.resolve(strict=True)
    validated: list[_ValidatedExternalRoot] = []
    for alias in sorted(aliases):
        _cancel(cancelled)
        root, root_identity = _canonical_external_root(authored_roots[alias])
        if _is_contained(root, project_root) or _is_contained(project_root, root):
            raise ProjectError("HOCUS458", "External roots must not overlap the project root.")
        for prior in validated:
            if _is_contained(root, prior.root) or _is_contained(prior.root, root):
                raise ProjectError("HOCUS458", "External roots must not overlap each other.")
        manifest_path, manifest_bytes, manifest, manifest_identity = _read_module_manifest(
            root, cancelled,
        )
        _require_manifest_lane(manifest, lane)
        pin = _pin_from_manifest(alias, aliases[alias], manifest)
        validated.append(
            _ValidatedExternalRoot(
                alias, pin, root, manifest_path, manifest_bytes,
                aliases[alias].expected_module_manifest_digest is not None,
                root_identity,
                manifest_identity,
            )
        )

    _validate_locked_external_identities(context, tuple(validated))
    inspection = _inspection_from_context(context, tuple(item.pin for item in validated))
    session = _ValidatedExternalModuleRoots(inspection, tuple(validated), lane)
    _recheck(context, session, cancelled)
    return session


def _require_manifest_lane(
    manifest: ModuleManifest,
    lane: tuple[int, str, int],
) -> None:
    _, language_version, module_manifest_version = lane
    if (
        manifest.schema_version != module_manifest_version
        or manifest.language_version != language_version
    ):
        raise ProjectError(
            "HOCUS458",
            "External module manifest does not match the selected project carrier lane.",
        )


def _bounded_authored_roots(
    value: Mapping[str, str | PathLike[str]],
    cancelled: Callable[[], bool] | None,
) -> dict[str, Path]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        raise ProjectError("HOCUS458", "module_roots must be a bounded alias-to-path mapping.")
    _cancel(cancelled)
    try:
        items = list(islice(iter(value.items()), MAX_EXTERNAL_ALIASES + 1))
    except Exception as exc:
        raise ProjectError("HOCUS458", "module_roots could not be enumerated safely.") from exc
    if len(items) > MAX_EXTERNAL_ALIASES:
        raise ProjectError("HOCUS458", "module_roots exceeds the external alias limit.")
    output: dict[str, Path] = {}
    for alias, authored in items:
        _cancel(cancelled)
        if type(alias) is not str or ALIAS_PATTERN.fullmatch(alias) is None or alias in output:
            raise ProjectError("HOCUS458", "module_roots contains an invalid or duplicate alias.")
        output[alias] = _authored_root_path(authored)
    return output


def _authored_root_path(authored: str | PathLike[str]) -> Path:
    try:
        raw = fspath(authored)
    except Exception as exc:
        raise ProjectError("HOCUS458", "External root paths must be explicit strings.") from exc
    if (
        type(raw) is not str
        or not raw
        or "\x00" in raw
        or raw != raw.strip()
        or raw.startswith("~")
    ):
        raise ProjectError("HOCUS458", "External root paths must be explicit absolute paths.")
    if raw.startswith(("\\\\", "//")):
        raise ProjectError("HOCUS458", "UNC and device-namespace external roots are forbidden.")
    if raw.casefold().startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        raise ProjectError("HOCUS458", "Windows device-namespace external roots are forbidden.")
    if os.path.normpath(raw) != raw:
        raise ProjectError("HOCUS458", "External root paths must be lexically canonical.")
    path = Path(raw)
    _require_canonical_windows_drive(path)
    if not path.is_absolute() or path.drive and not path.root:
        raise ProjectError("HOCUS458", "External root paths must be absolute.")
    if Path(os.path.abspath(path)) != path:
        raise ProjectError("HOCUS458", "External root paths must be lexically canonical.")
    return path


def _canonical_external_root(authored: Path) -> tuple[Path, tuple[int, int, int]]:
    _reject_reparse_chain(authored)
    _require_exact_native_casing(authored)
    identity_before = _native_identity(authored, "external root")
    try:
        resolved = authored.resolve(strict=True)
    except OSError as exc:
        raise ProjectError("HOCUS458", "External root does not exist.") from exc
    if resolved != authored or not resolved.is_dir():
        raise ProjectError("HOCUS458", "External root must be one canonical directory.")
    _reject_reparse_chain(resolved)
    identity_after = _native_identity(resolved, "external root")
    if identity_before != identity_after:
        raise ProjectError("HOCUS458", "External root identity changed during inspection.")
    return resolved, identity_after


def _read_module_manifest(
    root: Path,
    cancelled: Callable[[], bool] | None,
) -> tuple[Path, bytes, ModuleManifest, tuple[int, int, int]]:
    _cancel(cancelled)
    path = root / MODULE_MANIFEST_NAME
    _reject_reparse_chain(path)
    _require_exact_native_casing(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProjectError("HOCUS458", "External root requires hocus.module.toml.") from exc
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse(path, metadata):
        raise ProjectError("HOCUS458", "hocus.module.toml must be a non-reparse regular file.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ProjectError("HOCUS458", "Could not resolve hocus.module.toml.") from exc
    if resolved != path or not _is_contained(resolved, root):
        raise ProjectError("HOCUS458", "hocus.module.toml escaped its approved root.")
    identity_before = _native_identity(path, "external module manifest")
    raw = _read_bounded_stable(
        path,
        MAX_MODULE_MANIFEST_BYTES,
        "HOCUS458",
        "External module manifest",
    )
    identity_after = _native_identity(path, "external module manifest")
    if identity_before != identity_after:
        raise ProjectError("HOCUS458", "External module manifest identity changed during inspection.")
    _cancel(cancelled)
    manifest = decode_module_manifest(raw)
    return path, raw, manifest, identity_after


def _pin_from_manifest(
    alias: str,
    declaration: ExternalLibraryAlias,
    manifest: ModuleManifest,
) -> ExternalLibraryRootPin:
    if (
        manifest.library_uid != declaration.library_uid
        or manifest.version != declaration.library_version
        or (
            declaration.expected_module_manifest_digest is not None
            and manifest.manifest_digest != declaration.expected_module_manifest_digest
        )
    ):
        raise ProjectError(
            "HOCUS458",
            "External module manifest identity does not match the project alias.",
            details={"alias": alias},
        )
    return ExternalLibraryRootPin(
        alias,
        manifest.library_uid,
        manifest.version,
        manifest.manifest_digest,
        manifest.entry_modules,
    )


def _validate_locked_external_identities(
    context: ProjectContext,
    roots: tuple[_ValidatedExternalRoot, ...],
) -> None:
    pins = {item.alias: item.pin for item in roots}
    for record in context.locked_modules:
        if record.external_alias is None:
            continue
        pin = pins.get(record.external_alias)
        if (
            pin is None
            or record.project_uid is not None
            or record.library_uid != pin.library_uid
            or record.library_version != pin.library_version
            or record.module_manifest_digest != pin.module_manifest_digest
        ):
            raise ProjectError(
                "HOCUS458",
                "Locked external module identity does not match its approved root.",
                details={"moduleUri": record.module_uri},
            )


def _inspection_from_context(
    context: ProjectContext,
    libraries: tuple[ExternalLibraryRootPin, ...],
) -> ExternalModuleRootsInspection:
    assert context.uid is not None
    assert context.manifest_digest is not None
    assert context.lock_digest is not None
    assert context.catalog_content_digest is not None
    assert context.catalog_fingerprint is not None
    unsigned = {
        "kind": EXTERNAL_ROOTS_INSPECTION_KIND,
        "schemaVersion": 1,
        "projectUid": context.uid,
        "projectManifestDigest": context.manifest_digest,
        "projectLockDigest": context.lock_digest,
        "catalogContentDigest": context.catalog_content_digest,
        "catalogFingerprint": context.catalog_fingerprint,
        "libraries": [item.to_dict() for item in libraries],
    }
    return ExternalModuleRootsInspection(
        context.uid,
        context.manifest_digest,
        context.lock_digest,
        context.catalog_content_digest,
        context.catalog_fingerprint,
        libraries,
        _inspection_digest(unsigned),
    )


def _recheck(
    original: ProjectContext,
    session: _ValidatedExternalModuleRoots,
    cancelled: Callable[[], bool] | None,
) -> None:
    _cancel(cancelled)
    refreshed = ProjectContext.load(original.root, validate_lock=True)
    if (
        (refreshed.manifest_version, refreshed.language_version) != session.lane[:2]
        or
        refreshed.uid != original.uid
        or refreshed.manifest_digest != original.manifest_digest
        or refreshed.lock_digest != original.lock_digest
        or refreshed.catalog_content_digest != original.catalog_content_digest
        or refreshed.catalog_fingerprint != original.catalog_fingerprint
        or refreshed.external_aliases != original.external_aliases
        or refreshed.locked_modules != original.locked_modules
    ):
        raise ProjectError("HOCUS458", "Project or lock pins changed during external root inspection.")
    for item in session.roots:
        current_root, current_root_identity = _canonical_external_root(item.root)
        if current_root != item.root or current_root_identity != item.root_identity:
            raise ProjectError("HOCUS458", "External root identity changed during inspection.")
        path, raw, manifest, manifest_identity = _read_module_manifest(item.root, None)
        _require_manifest_lane(manifest, session.lane)
        if (
            path != item.manifest_path
            or raw != item.manifest_bytes
            or manifest_identity != item.manifest_identity
            or manifest.manifest_digest != item.pin.module_manifest_digest
            or manifest.entry_modules != item.pin.entry_modules
        ):
            raise ProjectError("HOCUS458", "External module manifest changed during inspection.")
    _validate_locked_external_identities(refreshed, session.roots)
    if _inspection_from_context(
        refreshed, tuple(item.pin for item in session.roots),
    ) != session.inspection:
        raise ProjectError("HOCUS458", "External roots inspection changed during final verification.")


def _reject_reparse_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    anchor = Path(absolute.anchor)
    current = anchor
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ProjectError("HOCUS458", "Could not inspect an external root path component.") from exc
        if _is_reparse(current, metadata):
            raise ProjectError("HOCUS458", "External roots cannot contain symlink, junction, or reparse components.")


def _is_reparse(path: Path, metadata: os.stat_result) -> bool:
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _WINDOWS_REPARSE_ATTRIBUTE
    )


def _native_identity(path: Path, label: str) -> tuple[int, int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProjectError("HOCUS458", f"Could not inspect {label} identity.") from exc
    return int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_mode)


def _require_exact_native_casing(path: Path) -> None:
    if os.name != "nt":
        return
    _require_canonical_windows_drive(path)
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        try:
            names = [child.name for child in current.iterdir()]
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProjectError("HOCUS458", "Could not verify external root path casing.") from exc
        if part not in names:
            if any(item.casefold() == part.casefold() for item in names):
                raise ProjectError("HOCUS458", "External root path casing is not exact.")
            return
        current /= part


def _require_canonical_windows_drive(path: Path) -> None:
    drive = path.drive
    if (
        os.name == "nt"
        and len(drive) == 2
        and drive[1] == ":"
        and "a" <= drive[0] <= "z"
    ):
        raise ProjectError(
            "HOCUS458",
            "External root drive letters must use canonical uppercase spelling.",
        )


def _inspection_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(_INSPECTION_DIGEST_DOMAIN + raw).hexdigest()


def _cancel(callback: Callable[[], bool] | None) -> None:
    if callback is None:
        return
    try:
        value = callback()
    except Exception as exc:
        raise ProjectError(
            "HOCUS465",
            "External root inspection cancellation callback failed.",
            details={"errorType": type(exc).__name__},
        ) from exc
    if type(value) is not bool:
        raise ProjectError("HOCUS465", "External root inspection cancellation callback must return bool.")
    if value:
        raise ProjectError("HOCUS465", "External root inspection was cancelled.")
