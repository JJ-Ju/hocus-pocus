"""Native HocusScript project discovery and bounded file compilation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .catalog import MAX_CATALOG_BYTES, CatalogSnapshot, CatalogValidationError, decode_catalog_snapshot
from .compiler import MAX_SOURCE_BYTES, compile_source
from .diagnostics import sort_diagnostics
from .model import CompileResult
from .semantic import CatalogConstraint, resolve_graph

PROJECT_MANIFEST_NAME = "hocus.project.toml"
PROJECT_LOCK_NAME = "hocus.lock.json"
PROJECT_SCHEMA_URI = "hocuspocus://schemas/hocus-project/v1"
PROJECT_SCHEMA_URI_V2 = "hocuspocus://schemas/hocus-project/v2"
PROJECT_SCHEMA_URI_V3 = "hocuspocus://schemas/hocus-project/v3"
PROJECT_SCHEMA_URI_V4 = "hocuspocus://schemas/hocus-project/v4"
LOCK_SCHEMA_URI = "hocuspocus://schemas/hocus-lock/v1"
LOCK_SCHEMA_URI_V2 = "hocuspocus://schemas/hocus-lock/v2"
LOCK_SCHEMA_URI_V3 = "hocuspocus://schemas/hocus-lock/v3"
LOCK_SCHEMA_URI_V4 = "hocuspocus://schemas/hocus-lock/v4"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_LOCK_BYTES_V3 = 16 * 1024 * 1024
MAX_PROJECT_DIRECTORIES = 64
MAX_EXTERNAL_ALIASES = 64
MAX_LOCKED_MODULES = 4096
MAX_METADATA_DEPTH = 64
MAX_METADATA_VALUES = 50_000
MAX_LOCK_METADATA_VALUES_V3 = 250_000
PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EXTERNAL_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SEMANTIC_VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))"
    r"(?:\.(?:(?:0|[1-9][0-9]*)|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
WINDOWS_RESERVED_PATH_SEGMENTS = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class ExternalLibraryAlias:
    alias: str
    library_uid: str
    library_version: str
    expected_module_manifest_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "libraryUid": self.library_uid,
            "libraryVersion": self.library_version,
            "expectedModuleManifestDigest": self.expected_module_manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class ModuleLockRecord:
    module_uri: str
    project_uid: str | None
    library_uid: str | None
    library_version: str | None
    module_manifest_digest: str | None
    language_version: str
    source_path: str
    content_digest: str
    interface_digest: str
    transitive_digest: str
    dependencies: tuple[str, ...] = ()
    external_alias: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "moduleUri": self.module_uri,
            "projectUid": self.project_uid,
            "libraryUid": self.library_uid,
            "libraryVersion": self.library_version,
            "moduleManifestDigest": self.module_manifest_digest,
            "languageVersion": self.language_version,
            "sourcePath": self.source_path,
            "contentDigest": self.content_digest,
            "interfaceDigest": self.interface_digest,
            "transitiveDigest": self.transitive_digest,
            "dependencies": list(self.dependencies),
            "externalAlias": self.external_alias,
        }


@dataclass(frozen=True, slots=True)
class LockVerificationResult:
    project_uid: str
    manifest_digest: str
    lock_digest: str
    modules: tuple[ModuleLockRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": True,
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "lockDigest": self.lock_digest,
            "modules": [item.to_dict() for item in self.modules],
        }


class ProjectError(ValueError):
    """Typed native project/file error suitable for CLI and editor adapters."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": "error",
            "code": self.code,
            "phase": "project",
            "message": self.message,
            "details": self.details,
        }


from .project_manifest import (
    _validate_manifest,
    _validate_relative_artifact_path,
)


@dataclass(frozen=True, slots=True)
class _ManifestSettings:
    uid: str | None = None
    name: str | None = None
    source_values: list[str] = field(default_factory=lambda: ["."])
    module_values: list[str] = field(default_factory=list)
    alias_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    language_version: str = "0.1"
    lock_policy: str = "optional"
    manifest_version: int = 1
    lock_relative_path: str = PROJECT_LOCK_NAME
    catalog_relative_path: str | None = None
    manifest_digest: str | None = None


def _load_manifest_settings(root: Path) -> _ManifestSettings:
    manifest_path = (root / PROJECT_MANIFEST_NAME).resolve(strict=False)
    if not manifest_path.exists():
        return _ManifestSettings(source_values=["."], module_values=[], alias_values={})
    _require_metadata_file(manifest_path, root, PROJECT_MANIFEST_NAME)
    manifest_bytes = _read_bounded(
        manifest_path, MAX_MANIFEST_BYTES, "HOCUS403", "Project manifest"
    )
    try:
        payload = tomllib.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError("HOCUS404", f"Invalid {PROJECT_MANIFEST_NAME}: {exc}") from exc
    version, project, language, lock, catalog, aliases = _validate_manifest(payload)
    return _ManifestSettings(
        uid=project["uid"],
        name=project.get("name"),
        source_values=project.get("source_directories", ["."]),
        module_values=project.get("module_directories", []),
        alias_values=aliases,
        language_version=language.get("version", "0.1"),
        lock_policy=lock.get("policy", "optional"),
        manifest_version=version,
        lock_relative_path=lock.get("path", PROJECT_LOCK_NAME),
        catalog_relative_path=catalog["path"] if catalog is not None else None,
        manifest_digest=_digest(manifest_bytes),
    )


@dataclass(frozen=True, slots=True)
class ProjectContext:
    root: Path
    uid: str | None
    name: str | None
    source_directories: tuple[Path, ...]
    language_version: str
    lock_policy: str
    manifest_digest: str | None
    lock_digest: str | None
    manifest_version: int = 1
    lock_path: Path | None = None
    catalog_path: Path | None = None
    catalog_relative_path: str | None = None
    catalog_content_digest: str | None = None
    catalog_fingerprint: str | None = None
    catalog: CatalogSnapshot | None = None
    module_directories: tuple[Path, ...] = ()
    module_directory_paths: tuple[str, ...] = ()
    external_aliases: tuple[ExternalLibraryAlias, ...] = ()
    locked_modules: tuple[ModuleLockRecord, ...] = ()

    @property
    def portable(self) -> bool:
        return self.uid is not None and self.manifest_digest is not None

    @classmethod
    def load(cls, project_directory: str | Path, *, validate_lock: bool = True) -> "ProjectContext":
        root = Path(project_directory).expanduser().resolve(strict=False)
        if not root.exists():
            raise ProjectError("HOCUS401", "Project directory does not exist.", details={"projectDirectory": str(root)})
        if not root.is_dir():
            raise ProjectError("HOCUS402", "Project path is not a directory.", details={"projectDirectory": str(root)})

        settings = _load_manifest_settings(root)

        source_directories = _resolve_source_directories(root, settings.source_values)
        module_directories = _resolve_module_directories(root, settings.module_values)
        _validate_directory_separation(source_directories, module_directories)
        external_aliases = tuple(
            ExternalLibraryAlias(
                alias,
                value["library_uid"],
                value["version"],
                value.get("module_manifest_digest"),
            )
            for alias, value in sorted(settings.alias_values.items())
        )
        unresolved_lock_path = root / Path(settings.lock_relative_path)
        if validate_lock and settings.manifest_digest is None and unresolved_lock_path.exists():
            raise ProjectError("HOCUS423", f"{PROJECT_LOCK_NAME} requires {PROJECT_MANIFEST_NAME}.")
        lock_path = _resolve_project_artifact(
            root, settings.lock_relative_path, "HOCUS419", "Project lock path"
        )
        catalog_path = (
            _resolve_project_artifact(
                root, settings.catalog_relative_path, "HOCUS430", "Catalog path"
            )
            if settings.catalog_relative_path is not None
            else None
        )
        catalog_content_digest: str | None = None
        catalog_fingerprint: str | None = None
        catalog_snapshot: CatalogSnapshot | None = None
        if validate_lock and lock_path.exists():
            if settings.uid is None or settings.manifest_digest is None:
                raise ProjectError("HOCUS423", f"{PROJECT_LOCK_NAME} requires {PROJECT_MANIFEST_NAME}.")
            _require_metadata_file(lock_path, root, PROJECT_LOCK_NAME)
            lock_digest, catalog_constraint, locked_modules = _load_lock(
                lock_path,
                project_uid=settings.uid,
                manifest_digest=settings.manifest_digest,
                language_version=settings.language_version,
                manifest_version=settings.manifest_version,
                catalog_relative_path=settings.catalog_relative_path,
                external_aliases=external_aliases,
            )
            if catalog_constraint is not None:
                if catalog_path is None:
                    raise ProjectError("HOCUS431", "Catalog lock exists without a manifest catalog path.")
                _require_metadata_file(catalog_path, root, "Catalog snapshot")
                raw_catalog = _read_bounded_stable(
                    catalog_path, MAX_CATALOG_BYTES, "HOCUS432", "Catalog snapshot"
                )
                catalog_content_digest = _digest(raw_catalog)
                if catalog_content_digest != catalog_constraint["contentDigest"]:
                    raise ProjectError(
                        "HOCUS433",
                        "Catalog snapshot content digest does not match the project lock.",
                        details={
                            "expected": catalog_constraint["contentDigest"],
                            "actual": catalog_content_digest,
                            "path": settings.catalog_relative_path,
                        },
                    )
                try:
                    catalog_snapshot = decode_catalog_snapshot(raw_catalog)
                except CatalogValidationError as exc:
                    raise ProjectError(
                        "HOCUS434",
                        f"Invalid catalog snapshot: {exc.message}",
                        details={"catalogCode": exc.code, "catalogPath": exc.path},
                    ) from exc
                catalog_fingerprint = catalog_snapshot.fingerprint
                if catalog_fingerprint != catalog_constraint["fingerprint"]:
                    raise ProjectError(
                        "HOCUS435",
                        "Catalog fingerprint does not match the project lock.",
                        details={
                            "expected": catalog_constraint["fingerprint"],
                            "actual": catalog_fingerprint,
                            "path": settings.catalog_relative_path,
                        },
                    )
        else:
            if validate_lock and settings.lock_policy == "required":
                raise ProjectError("HOCUS426", f"{PROJECT_LOCK_NAME} is required by the project manifest.")
            lock_digest = None
            locked_modules = ()
        return cls(
            root=root,
            uid=settings.uid,
            name=settings.name,
            source_directories=tuple(source_directories),
            language_version=settings.language_version,
            lock_policy=settings.lock_policy,
            manifest_digest=settings.manifest_digest,
            lock_digest=lock_digest,
            manifest_version=settings.manifest_version,
            lock_path=lock_path,
            catalog_path=catalog_path,
            catalog_relative_path=settings.catalog_relative_path,
            catalog_content_digest=catalog_content_digest,
            catalog_fingerprint=catalog_fingerprint,
            catalog=catalog_snapshot,
            module_directories=tuple(module_directories),
            module_directory_paths=tuple(settings.module_values),
            external_aliases=external_aliases,
            locked_modules=tuple(locked_modules),
        )

    def resolve_source(self, source_path: str | Path) -> Path:
        resolved = self.resolve_source_destination(source_path)
        if not resolved.exists():
            raise ProjectError("HOCUS413", "HocusScript source file does not exist.", details={"path": str(source_path)})
        if not resolved.is_file():
            raise ProjectError("HOCUS414", "HocusScript source path is not a regular file.", details={"path": str(source_path)})
        return resolved

    def resolve_source_destination(self, source_path: str | Path) -> Path:
        """Resolve an existing or new native source path inside configured project roots."""

        candidate = Path(source_path).expanduser()
        resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (self.root / candidate).resolve(strict=False)
        _require_contained(resolved, self.root, "HOCUS411", "Source path escapes the project root.")
        if resolved.suffix.lower() != ".hocus":
            raise ProjectError("HOCUS412", "HocusScript source files must use the .hocus suffix.", details={"path": str(source_path)})
        if not any(_is_contained(resolved, source_root) for source_root in self.source_directories):
            raise ProjectError("HOCUS415", "Source file is outside the configured source directories.", details={"path": str(source_path)})
        return resolved

    def source_uri(self, source_path: str | Path) -> str:
        return self.source_uri_for_resolved(self.resolve_source(source_path))

    def source_uri_for_resolved(self, resolved: Path) -> str:
        _require_contained(resolved, self.root, "HOCUS411", "Source path escapes the project root.")
        relative = resolved.relative_to(self.root).as_posix()
        encoded = quote(relative, safe="/-._~")
        if self.uid is not None:
            return f"hocus-project://{self.uid}/{encoded}"
        return f"hocus-workspace:///{encoded}"


def compile_path(
    source_path: str | Path,
    *,
    project_directory: str | Path,
    strict: bool = True,
    validate_lock: bool = True,
) -> CompileResult:
    """Compile one native .hocus file inside an explicitly selected project."""

    preview = ProjectContext.load(project_directory, validate_lock=False)
    if preview.manifest_version in {3, 4} or preview.language_version in {"0.2", "0.3"}:
        raise ProjectError(
            "HOCUS456",
            "HocusScript 0.2/0.3 project compilation remains disabled until a compatible resolver/compiler batch.",
        )
    project = ProjectContext.load(project_directory, validate_lock=validate_lock)
    if project.language_version in {"0.2", "0.3"}:
        raise ProjectError(
            "HOCUS456",
            "HocusScript 0.2/0.3 project compilation remains disabled until a compatible resolver/compiler batch.",
        )
    resolved = project.resolve_source(source_path)
    if validate_lock:
        source_uri = project.source_uri_for_resolved(resolved)
    else:
        relative = resolved.relative_to(project.root).as_posix()
        source_uri = f"hocus-workspace:///{quote(relative, safe='/-._~')}"
    raw = _read_bounded_stable(resolved, MAX_SOURCE_BYTES, "HOCUS001", "HocusScript source")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS416",
            "HocusScript source must be valid UTF-8.",
            details={"start": exc.start, "end": exc.end, "sourceUri": source_uri},
        ) from exc
    result = compile_source(source, resolved.name, source_uri=source_uri, strict=strict)
    result.source_kind = "project_file" if validate_lock and project.portable else "workspace_file"
    result.project_uid = project.uid if validate_lock else None
    result.project_manifest_digest = project.manifest_digest if validate_lock else None
    result.project_lock_digest = project.lock_digest if validate_lock else None
    if validate_lock and project.catalog is not None and result.valid and result.graph_spec is not None:
        semantic = resolve_graph(
            result.graph_spec,
            project.catalog,
            constraint=CatalogConstraint(project.catalog_fingerprint or project.catalog.fingerprint),
        )
        result.semantic_result = semantic
        result.catalog_content_digest = project.catalog_content_digest
        result.catalog_fingerprint = semantic.catalog_fingerprint
        result.diagnostics = sort_diagnostics([*result.diagnostics, *semantic.diagnostics])
        result.valid = result.valid and semantic.valid
    result.native_source_path = str(resolved)
    return result


def verify_project_lock(project_directory: str | Path) -> LockVerificationResult:
    """Explicitly verify a portable module lock without changing project files."""
    preview = ProjectContext.load(project_directory, validate_lock=False)
    if preview.manifest_version not in {3, 4}:
        raise ProjectError("HOCUS452", "Module lock verification requires a schema v3 or v4 project.")
    project = ProjectContext.load(project_directory, validate_lock=True)
    if project.uid is None or project.manifest_digest is None or project.lock_digest is None:
        raise ProjectError("HOCUS452", "Portable project lock verification is incomplete.")
    return LockVerificationResult(
        project.uid, project.manifest_digest, project.lock_digest, project.locked_modules
    )


def update_project_lock(
    project_directory: str | Path,
    modules: Iterable[ModuleLockRecord | dict[str, Any]],
    *,
    expected_lock_digest: str | None = None,
    allow_write: bool = False,
) -> LockVerificationResult:
    """Explicitly replace/create an empty portable lock with optimistic concurrency.

    Loading, checking, formatting, and compiling never call this function. An
    existing lock always requires its current canonical digest.
    """
    if allow_write is not True:
        raise ProjectError("HOCUS455", "Lock update requires explicit allow_write=True authority.")
    _require_empty_module_scaffold(modules)
    initial_project = ProjectContext.load(project_directory, validate_lock=False)
    if (
        initial_project.manifest_version not in {3, 4}
        or initial_project.uid is None
        or initial_project.manifest_digest is None
    ):
        raise ProjectError("HOCUS452", "Lock update requires a portable schema v3 or v4 project.")
    if (
        initial_project.lock_path is None
        or initial_project.catalog_path is None
        or initial_project.catalog_relative_path is None
    ):
        raise ProjectError("HOCUS452", "Portable lock and catalog paths are required.")
    lock_path = initial_project.lock_path
    with _exclusive_update_lease(lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        if (
            project.manifest_version != initial_project.manifest_version
            or project.uid is None
            or project.manifest_digest is None
            or project.lock_path != lock_path
            or project.catalog_path is None
            or project.catalog_relative_path is None
        ):
            raise ProjectError("HOCUS453", "Project configuration changed before lock update.")
        initial_lock_digest = _check_expected_lock(lock_path, project.root, expected_lock_digest)
        _require_metadata_file(project.catalog_path, project.root, "Catalog snapshot")
        catalog_raw = _read_bounded_stable(
            project.catalog_path, MAX_CATALOG_BYTES, "HOCUS432", "Catalog snapshot"
        )
        catalog_digest = _digest(catalog_raw)
        try:
            catalog = decode_catalog_snapshot(catalog_raw)
        except CatalogValidationError as exc:
            raise ProjectError(
                "HOCUS434", f"Invalid catalog snapshot: {exc.message}",
                details={"catalogCode": exc.code, "catalogPath": exc.path},
            ) from exc
        payload = {
            "$schema": (
                LOCK_SCHEMA_URI_V4
                if project.manifest_version == 4
                else LOCK_SCHEMA_URI_V3
            ),
            "kind": "hocus_project_lock",
            "schemaVersion": project.manifest_version,
            "projectUid": project.uid,
            "manifestDigest": project.manifest_digest,
            "languageVersion": project.language_version,
            "catalog": {
                "schemaVersion": 1,
                "path": project.catalog_relative_path,
                "contentDigest": catalog_digest,
                "fingerprint": catalog.fingerprint,
            },
            "modules": [],
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode("utf-8")
        lock_digest = _digest(canonical)
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_LOCK_BYTES_V3:
            raise ProjectError("HOCUS410", "Generated project lock exceeds the lock byte limit.")
        _atomic_write_lock(
            lock_path,
            encoded,
            expected_lock_digest=expected_lock_digest,
            before_publish=lambda: _recheck_update_inputs(
                project,
                catalog_digest=catalog_digest,
                initial_lock_digest=initial_lock_digest,
            ),
        )
        return LockVerificationResult(project.uid, project.manifest_digest, lock_digest, ())


def _require_empty_module_scaffold(modules: Iterable[ModuleLockRecord | dict[str, Any]]) -> None:
    sentinel = object()
    try:
        iterator = iter(modules)
        first = next(iterator, sentinel)
    except Exception as exc:
        raise ProjectError("HOCUS451", "Lock module records must be a bounded iterable.") from exc
    if first is not sentinel:
        raise ProjectError(
            "HOCUS456",
            "Nonempty module lock updates remain disabled until resolver integration.",
        )


def _publish_derived_module_lock(
    project_directory: str | Path,
    *,
    expected_lock_digest: str | None,
    derive: Callable[[ProjectContext], tuple[tuple[ModuleLockRecord, ...], Callable[[], None]]],
    build_result: Callable[[str | None, LockVerificationResult | None, LockVerificationResult, str, str], Any],
) -> Any:
    """Publish internally derived same-project records through the guarded path."""

    return _publish_derived_lock(
        project_directory,
        expected_lock_digest=expected_lock_digest,
        derive=derive,
        build_result=build_result,
        allow_external=False,
        require_valid_current=False,
        skip_unchanged=False,
    )


def _publish_derived_mixed_module_lock(
    project_directory: str | Path,
    *,
    expected_lock_digest: str,
    derive: Callable[[ProjectContext], tuple[tuple[ModuleLockRecord, ...], Callable[[], None]]],
    build_result: Callable[[str, LockVerificationResult, LockVerificationResult, str, str], Any],
) -> Any:
    """Publish independently derived mixed-root records under the guarded lease."""

    return _publish_derived_lock(
        project_directory,
        expected_lock_digest=expected_lock_digest,
        derive=derive,
        build_result=build_result,
        allow_external=True,
        require_valid_current=True,
        skip_unchanged=True,
    )


def _publish_derived_lock(
    project_directory: str | Path,
    *,
    expected_lock_digest: str | None,
    derive: Callable[[ProjectContext], tuple[tuple[ModuleLockRecord, ...], Callable[[], None]]],
    build_result: Callable[[str | None, LockVerificationResult | None, LockVerificationResult, str, str], Any],
    allow_external: bool,
    require_valid_current: bool,
    skip_unchanged: bool,
) -> Any:
    """Common private publisher with a fixed caller-selected record policy."""
    policy = (allow_external, require_valid_current, skip_unchanged)
    if policy not in ((False, False, False), (True, True, True)):
        raise RuntimeError("Unsupported derived-lock publication policy")
    initial = ProjectContext.load(project_directory, validate_lock=False)
    _require_publishable_project(initial)
    with _exclusive_update_lease(initial.lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        _require_stable_publish_project(initial, project)
        initial_lock_digest = _check_expected_lock(
            project.lock_path, project.root, expected_lock_digest
        )
        if initial_lock_digest is None:
            before = None
        else:
            try:
                before = verify_project_lock(project.root)
            except ProjectError:
                if require_valid_current:
                    raise
                # Exact expected-digest authority may repair a stale prior lock;
                # the receipt marks its structural diff unavailable.
                before = None
        if require_valid_current and (initial_lock_digest is None or before is None):
            raise ProjectError("HOCUS453", "Mixed module lock publication requires a valid current lock.")
        modules, before_publish = derive(project)
        _validate_publish_modules(modules, project.uid, allow_external)
        _require_metadata_file(project.catalog_path, project.root, "Catalog snapshot")
        catalog_raw = _read_bounded_stable(
            project.catalog_path, MAX_CATALOG_BYTES, "HOCUS432", "Catalog snapshot"
        )
        catalog_digest = _digest(catalog_raw)
        try:
            catalog = decode_catalog_snapshot(catalog_raw)
        except CatalogValidationError as exc:
            raise ProjectError("HOCUS434", f"Invalid catalog snapshot: {exc.message}") from exc
        payload_modules = [item.to_dict() for item in modules]
        # Reuse the strict lock decoder before anything can be published.
        validated = _validate_module_locks(
            payload_modules, project_uid=project.uid, external_aliases=project.external_aliases
        )
        if validated != modules:
            raise ProjectError("HOCUS451", "Derived module records are not canonical.")
        payload = {
            "$schema": LOCK_SCHEMA_URI_V3, "kind": "hocus_project_lock", "schemaVersion": 3,
            "projectUid": project.uid, "manifestDigest": project.manifest_digest,
            "languageVersion": "0.2",
            "catalog": {
                "schemaVersion": 1, "path": project.catalog_relative_path,
                "contentDigest": catalog_digest, "fingerprint": catalog.fingerprint,
            },
            "modules": payload_modules,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode("utf-8")
        encoded = (json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        ) + "\n").encode("utf-8")
        if len(encoded) > MAX_LOCK_BYTES_V3:
            raise ProjectError("HOCUS410", "Generated project lock exceeds the lock byte limit.")
        lock_digest = _digest(canonical)
        verified = LockVerificationResult(
            project.uid, project.manifest_digest, lock_digest, modules,
        )
        result = build_result(
            initial_lock_digest, before, verified, catalog_digest, catalog.fingerprint,
        )

        def final_recheck() -> None:
            before_publish()
            _recheck_update_inputs(
                project,
                catalog_digest=catalog_digest,
                initial_lock_digest=initial_lock_digest,
            )

        if skip_unchanged and initial_lock_digest == lock_digest:
            final_recheck()
        else:
            _atomic_write_lock(
                project.lock_path,
                encoded,
                expected_lock_digest=expected_lock_digest,
                before_publish=final_recheck,
            )
        return result


def _require_publishable_project(project: ProjectContext) -> None:
    if (
        project.manifest_version != 3
        or project.uid is None
        or project.manifest_digest is None
        or project.lock_path is None
        or project.catalog_path is None
        or project.catalog_relative_path is None
    ):
        raise ProjectError("HOCUS452", "Derived module locks require a portable schema v3 project.")


def _require_stable_publish_project(
    initial: ProjectContext,
    project: ProjectContext,
) -> None:
    if (
        project.uid != initial.uid
        or project.manifest_digest != initial.manifest_digest
        or project.lock_path != initial.lock_path
        or project.catalog_path is None
        or project.catalog_relative_path is None
    ):
        raise ProjectError("HOCUS453", "Project configuration changed before lock update.")


def _validate_publish_modules(
    modules: tuple[ModuleLockRecord, ...],
    project_uid: str,
    allow_external: bool,
) -> None:
    if not allow_external and any(
        item.external_alias is not None or item.project_uid != project_uid
        for item in modules
    ):
        raise ProjectError(
            "HOCUS451", "Derived lock publication accepts same-project modules only."
        )


@contextmanager
def _exclusive_update_lease(lock_path: Path) -> Iterable[None]:
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError("HOCUS454", f"Could not prepare project lock directory: {exc}") from exc
    lease_path = lock_path.with_name(f".{lock_path.name}.update-lease")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lease_path, flags, 0o600)
    except FileExistsError as exc:
        raise ProjectError("HOCUS453", "Another lock update already holds the project lease.") from exc
    except OSError as exc:
        raise ProjectError("HOCUS454", f"Could not acquire project lock update lease: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(f"pid={os.getpid()}\n".encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lease_path.unlink(missing_ok=True)
        except OSError:
            # Never turn a successfully published lock into a reported failure.
            pass


def _check_expected_lock(lock_path: Path, root: Path, expected_lock_digest: str | None) -> str | None:
    if lock_path.exists():
        _require_metadata_file(lock_path, root, PROJECT_LOCK_NAME)
        actual = _canonical_lock_file_digest(lock_path)
        if expected_lock_digest is None or expected_lock_digest != actual:
            raise ProjectError(
                "HOCUS453", "Existing lock update requires its exact current canonical digest.",
                details={"expected": expected_lock_digest, "actual": actual},
            )
        return actual
    if expected_lock_digest is not None:
        raise ProjectError("HOCUS453", "Cannot use expected_lock_digest when creating a new lock.")
    return None


def _recheck_update_inputs(
    project: ProjectContext,
    *,
    catalog_digest: str,
    initial_lock_digest: str | None,
) -> None:
    manifest_path = (project.root / PROJECT_MANIFEST_NAME).resolve(strict=False)
    _require_metadata_file(manifest_path, project.root, PROJECT_MANIFEST_NAME)
    manifest_raw = _read_bounded_stable(
        manifest_path, MAX_MANIFEST_BYTES, "HOCUS403", "Project manifest"
    )
    if _digest(manifest_raw) != project.manifest_digest:
        raise ProjectError("HOCUS453", "Project manifest changed before lock publication.")
    assert project.catalog_path is not None
    _require_metadata_file(project.catalog_path, project.root, "Catalog snapshot")
    current_catalog = _read_bounded_stable(
        project.catalog_path, MAX_CATALOG_BYTES, "HOCUS432", "Catalog snapshot"
    )
    if _digest(current_catalog) != catalog_digest:
        raise ProjectError("HOCUS453", "Catalog snapshot changed before lock publication.")
    if initial_lock_digest is None:
        if project.lock_path is not None and project.lock_path.exists():
            raise ProjectError("HOCUS453", "Lock appeared before publication.")
    else:
        assert project.lock_path is not None
        if not project.lock_path.exists() or _canonical_lock_file_digest(project.lock_path) != initial_lock_digest:
            raise ProjectError("HOCUS453", "Lock changed before publication.")


def _canonical_lock_file_digest(
    path: Path,
    *,
    limit: int = MAX_LOCK_BYTES_V3,
    max_values: int = MAX_LOCK_METADATA_VALUES_V3,
) -> str:
    raw = _read_bounded(path, limit, "HOCUS410", "Project lock")
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProjectError, RecursionError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("HOCUS422", f"Invalid {PROJECT_LOCK_NAME}: {exc}") from exc
    _validate_json_complexity(payload, max_values=max_values)
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return _digest(canonical.encode("utf-8"))


def _atomic_write_lock(
    path: Path,
    content: bytes,
    *,
    expected_lock_digest: str | None,
    before_publish: Callable[[], None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if before_publish is not None:
            before_publish()
        if expected_lock_digest is None:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ProjectError(
                    "HOCUS453", "Lock appeared concurrently; refusing to overwrite it."
                ) from exc
        else:
            actual = _canonical_lock_file_digest(path)
            if actual != expected_lock_digest:
                raise ProjectError(
                    "HOCUS453", "Lock changed immediately before replacement.",
                    details={"expected": expected_lock_digest, "actual": actual},
                )
            os.replace(temporary, path)
    except OSError as exc:
        raise ProjectError("HOCUS454", f"Could not atomically update project lock: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Cleanup cannot invalidate an already successful atomic publish.
            pass


def _portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _resolve_project_artifact(root: Path, relative: str, code: str, label: str) -> Path:
    _validate_relative_artifact_path(relative, label)
    resolved = (root / Path(relative)).resolve(strict=False)
    _require_contained(resolved, root, code, f"{label} escapes the project root.")
    return resolved


def _resolve_source_directories(root: Path, values: list[str]) -> list[Path]:
    output: list[Path] = []
    for value in values:
        resolved = (root / Path(value)).resolve(strict=False)
        _require_contained(resolved, root, "HOCUS409", "Project source directory escapes the project root.")
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectError("HOCUS427", "Configured source directory must exist and be a directory.", details={"path": value})
        output.append(resolved)
    return output


def _validate_directory_separation(
    source_directories: list[Path],
    module_directories: list[Path],
) -> None:
    overlap = {
        str(source)
        for source in source_directories
        for module in module_directories
        if _is_contained(source, module) or _is_contained(module, source)
    }
    if overlap:
        raise ProjectError(
            "HOCUS449", "Source and module directories must not overlap.",
            details={"paths": sorted(overlap)},
        )


def _resolve_module_directories(root: Path, values: list[str]) -> list[Path]:
    output: list[Path] = []
    for value in values:
        resolved = (root / Path(value)).resolve(strict=False)
        _require_contained(resolved, root, "HOCUS449", "Project module directory escapes the project root.")
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectError(
                "HOCUS449", "Configured module directory must exist and be a directory.",
                details={"path": value},
            )
        output.append(resolved)
    return output


def _load_lock(
    path: Path,
    *,
    project_uid: str,
    manifest_digest: str,
    language_version: str,
    manifest_version: int,
    catalog_relative_path: str | None,
    external_aliases: tuple[ExternalLibraryAlias, ...] = (),
) -> tuple[str, dict[str, Any] | None, tuple[ModuleLockRecord, ...]]:
    from .project_lock_validation import load_lock

    return load_lock(
        path,
        project_uid=project_uid,
        manifest_digest=manifest_digest,
        language_version=language_version,
        manifest_version=manifest_version,
        catalog_relative_path=catalog_relative_path,
        external_aliases=external_aliases,
    )


def _validate_module_locks(
    value: Any,
    *,
    project_uid: str,
    external_aliases: tuple[ExternalLibraryAlias, ...],
    expected_language_version: str = "0.2",
) -> tuple[ModuleLockRecord, ...]:
    from .project_lock_validation import validate_module_locks

    return validate_module_locks(
        value,
        project_uid=project_uid,
        external_aliases=external_aliases,
        expected_language_version=expected_language_version,
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains duplicate key {key!r}.")
        output[key] = value
    return output


def _reject_json_constant(value: str) -> Any:
    raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains non-finite constant {value}.")


def _validate_json_complexity(value: Any, *, max_values: int = MAX_METADATA_VALUES) -> None:
    count = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > max_values or depth > MAX_METADATA_DEPTH:
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} exceeds structural complexity limits.")
        if isinstance(item, float) and not math.isfinite(item):
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains a non-finite number.")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _read_bounded(path: Path, limit: int, code: str, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise ProjectError(code, f"Could not read {label.lower()}: {exc}", details={"path": str(path)}) from exc
    if len(raw) > limit:
        raise ProjectError(code, f"{label} exceeds the {limit}-byte limit.", details={"path": str(path), "limit": limit})
    return raw


def _read_bounded_stable(path: Path, limit: int, code: str, label: str) -> bytes:
    try:
        before = path.stat()
        raw = _read_bounded(path, limit, code, label)
        after = path.stat()
    except OSError as exc:
        raise ProjectError(code, f"Could not inspect {label.lower()}: {exc}", details={"path": str(path)}) from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise ProjectError("HOCUS428", f"{label} changed while it was being read.", details={"path": str(path)})
    return raw


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _require_contained(path: Path, root: Path, code: str, message: str) -> None:
    if not _is_contained(path, root):
        raise ProjectError(code, message, details={"path": str(path)})


def _require_metadata_file(path: Path, root: Path, name: str) -> None:
    _require_contained(path, root, "HOCUS419", f"{name} resolves outside the project root.")
    if not path.is_file():
        raise ProjectError("HOCUS420", f"{name} is not a regular file.", details={"path": str(path)})
