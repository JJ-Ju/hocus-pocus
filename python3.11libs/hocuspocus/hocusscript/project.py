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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .catalog import MAX_CATALOG_BYTES, CatalogSnapshot, CatalogValidationError, decode_catalog_snapshot
from .compiler import MAX_SOURCE_BYTES, SUPPORTED_LANGUAGE_VERSIONS, compile_source
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

        manifest_path = (root / PROJECT_MANIFEST_NAME).resolve(strict=False)
        uid: str | None = None
        name: str | None = None
        source_values = ["."]
        module_values: list[str] = []
        alias_values: dict[str, dict[str, Any]] = {}
        language_version = "0.1"
        lock_policy = "optional"
        manifest_version = 1
        lock_relative_path = PROJECT_LOCK_NAME
        catalog_relative_path: str | None = None
        manifest_digest: str | None = None
        if manifest_path.exists():
            _require_metadata_file(manifest_path, root, PROJECT_MANIFEST_NAME)
            manifest_bytes = _read_bounded(manifest_path, MAX_MANIFEST_BYTES, "HOCUS403", "Project manifest")
            manifest_digest = _digest(manifest_bytes)
            try:
                payload = tomllib.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise ProjectError("HOCUS404", f"Invalid {PROJECT_MANIFEST_NAME}: {exc}") from exc
            manifest_version, project, language, lock, catalog_config, alias_values = _validate_manifest(payload)
            uid = project["uid"]
            name = project.get("name")
            source_values = project.get("source_directories", ["."])
            module_values = project.get("module_directories", [])
            language_version = language.get("version", "0.1")
            lock_policy = lock.get("policy", "optional")
            lock_relative_path = lock.get("path", PROJECT_LOCK_NAME)
            if catalog_config is not None:
                catalog_relative_path = catalog_config["path"]

        source_directories = _resolve_source_directories(root, source_values)
        module_directories = _resolve_module_directories(root, module_values)
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
        external_aliases = tuple(
            ExternalLibraryAlias(
                alias,
                value["library_uid"],
                value["version"],
                value.get("module_manifest_digest"),
            )
            for alias, value in sorted(alias_values.items())
        )
        unresolved_lock_path = root / Path(lock_relative_path)
        if validate_lock and manifest_digest is None and unresolved_lock_path.exists():
            raise ProjectError("HOCUS423", f"{PROJECT_LOCK_NAME} requires {PROJECT_MANIFEST_NAME}.")
        lock_path = _resolve_project_artifact(root, lock_relative_path, "HOCUS419", "Project lock path")
        catalog_path = (
            _resolve_project_artifact(root, catalog_relative_path, "HOCUS430", "Catalog path")
            if catalog_relative_path is not None
            else None
        )
        catalog_content_digest: str | None = None
        catalog_fingerprint: str | None = None
        catalog_snapshot: CatalogSnapshot | None = None
        if validate_lock and lock_path.exists():
            if uid is None or manifest_digest is None:
                raise ProjectError("HOCUS423", f"{PROJECT_LOCK_NAME} requires {PROJECT_MANIFEST_NAME}.")
            _require_metadata_file(lock_path, root, PROJECT_LOCK_NAME)
            lock_digest, catalog_constraint, locked_modules = _load_lock(
                lock_path,
                project_uid=uid,
                manifest_digest=manifest_digest,
                language_version=language_version,
                manifest_version=manifest_version,
                catalog_relative_path=catalog_relative_path,
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
                            "path": catalog_relative_path,
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
                            "path": catalog_relative_path,
                        },
                    )
        else:
            if validate_lock and lock_policy == "required":
                raise ProjectError("HOCUS426", f"{PROJECT_LOCK_NAME} is required by the project manifest.")
            lock_digest = None
            locked_modules = ()
        return cls(
            root=root,
            uid=uid,
            name=name,
            source_directories=tuple(source_directories),
            language_version=language_version,
            lock_policy=lock_policy,
            manifest_digest=manifest_digest,
            lock_digest=lock_digest,
            manifest_version=manifest_version,
            lock_path=lock_path,
            catalog_path=catalog_path,
            catalog_relative_path=catalog_relative_path,
            catalog_content_digest=catalog_content_digest,
            catalog_fingerprint=catalog_fingerprint,
            catalog=catalog_snapshot,
            module_directories=tuple(module_directories),
            module_directory_paths=tuple(module_values),
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
    """Explicitly verify a v3 lock without changing project or lock files."""
    preview = ProjectContext.load(project_directory, validate_lock=False)
    if preview.manifest_version != 3:
        raise ProjectError("HOCUS452", "Module lock verification requires a schema v3 project.")
    project = ProjectContext.load(project_directory, validate_lock=True)
    if project.uid is None or project.manifest_digest is None or project.lock_digest is None:
        raise ProjectError("HOCUS452", "Schema v3 project lock verification is incomplete.")
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
    """Explicitly replace/create a v3 lock with optimistic concurrency.

    Loading, checking, formatting, and compiling never call this function. An
    existing lock always requires its current canonical digest.
    """
    if allow_write is not True:
        raise ProjectError("HOCUS455", "Lock update requires explicit allow_write=True authority.")
    _require_empty_module_scaffold(modules)
    initial_project = ProjectContext.load(project_directory, validate_lock=False)
    if (
        initial_project.manifest_version != 3
        or initial_project.uid is None
        or initial_project.manifest_digest is None
    ):
        raise ProjectError("HOCUS452", "Lock update requires a portable schema v3 project.")
    if (
        initial_project.lock_path is None
        or initial_project.catalog_path is None
        or initial_project.catalog_relative_path is None
    ):
        raise ProjectError("HOCUS452", "Schema v3 lock and catalog paths are required.")
    lock_path = initial_project.lock_path
    with _exclusive_update_lease(lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        if (
            project.manifest_version != 3
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
            "$schema": LOCK_SCHEMA_URI_V3,
            "kind": "hocus_project_lock",
            "schemaVersion": 3,
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
    if (
        initial.manifest_version != 3 or initial.uid is None or initial.manifest_digest is None
        or initial.lock_path is None or initial.catalog_path is None
        or initial.catalog_relative_path is None
    ):
        raise ProjectError("HOCUS452", "Derived module locks require a portable schema v3 project.")
    with _exclusive_update_lease(initial.lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        if (
            project.uid != initial.uid or project.manifest_digest != initial.manifest_digest
            or project.lock_path != initial.lock_path or project.catalog_path is None
            or project.catalog_relative_path is None
        ):
            raise ProjectError("HOCUS453", "Project configuration changed before lock update.")
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
        if not allow_external and any(
            item.external_alias is not None or item.project_uid != project.uid
            for item in modules
        ):
            raise ProjectError("HOCUS451", "Derived lock publication accepts same-project modules only.")
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


def _validate_manifest(
    payload: Any,
) -> tuple[
    int, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None,
    dict[str, dict[str, Any]],
]:
    if not isinstance(payload, dict):
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} has unknown top-level fields.")
    schema_version = payload.get("schema_version")
    allowed_top_level = {"schema_version", "project", "language", "lock"}
    if schema_version in {2, 3, 4}:
        allowed_top_level.add("catalog")
    if schema_version in {3, 4}:
        allowed_top_level.add("external_aliases")
    if set(payload) - allowed_top_level:
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} has unknown top-level fields.")
    if type(schema_version) is not int or schema_version not in {1, 2, 3, 4} or not isinstance(payload.get("project"), dict):
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} requires schema_version = 1, 2, 3, or 4 and a [project] table.")
    project = payload["project"]
    project_fields = {"uid", "name", "source_directories"}
    if schema_version in {3, 4}:
        project_fields.add("module_directories")
    _require_table_fields(project, project_fields, "project")
    uid = project.get("uid")
    if not isinstance(uid, str) or not PROJECT_UID_PATTERN.fullmatch(uid):
        raise ProjectError("HOCUS406", "Project uid must match ^[a-z0-9][a-z0-9.-]{0,127}$.", details={"uid": uid})
    name = project.get("name")
    if name is not None:
        if (
            not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or len(name) > 256
            or any(ord(char) < 32 for char in name)
        ):
            raise ProjectError("HOCUS407", "Project name must be a bounded non-empty string without control characters.")
    _validate_source_directory_values(project.get("source_directories", ["."]))
    if schema_version in {3, 4}:
        _validate_module_directory_values(project.get("module_directories", []))
    language = payload.get("language", {})
    lock = payload.get("lock", {})
    _require_table_fields(language, {"version"}, "language")
    _require_table_fields(lock, {"policy", "path"} if schema_version in {2, 3, 4} else {"policy"}, "lock")
    version = language.get("version", "0.1")
    if schema_version == 3:
        version_valid = version == "0.2"
    elif schema_version == 4:
        version_valid = version == "0.3"
    else:
        version_valid = isinstance(version, str) and version in SUPPORTED_LANGUAGE_VERSIONS
    if not version_valid:
        raise ProjectError("HOCUS421", "Project language version is unsupported.", details={"languageVersion": version})
    policy = lock.get("policy", "optional")
    if not isinstance(policy, str) or policy not in {"optional", "required"}:
        raise ProjectError("HOCUS405", "lock.policy must be optional or required.")
    if schema_version in {2, 3, 4} and policy != "required":
        raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires lock.policy = required.")
    if schema_version in {2, 3, 4} and "path" not in lock:
        raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires lock.path.")
    if "path" in lock:
        _validate_relative_artifact_path(lock["path"], "lock.path")
        if not lock["path"].endswith(".json"):
            raise ProjectError("HOCUS405", "lock.path must identify a .json file.")
    catalog: dict[str, Any] | None = None
    if schema_version in {2, 3, 4}:
        catalog = payload.get("catalog")
        _require_table_fields(catalog, {"path"}, "catalog")
        if "path" not in catalog:
            raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires catalog.path.")
        _validate_relative_artifact_path(catalog["path"], "catalog.path")
        if not catalog["path"].endswith(".json"):
            raise ProjectError("HOCUS405", "catalog.path must identify a .json file.")
        if catalog["path"].casefold() == lock.get("path", PROJECT_LOCK_NAME).casefold():
            raise ProjectError("HOCUS405", "catalog.path and lock.path must be different files.")
    aliases: dict[str, dict[str, Any]] = {}
    if schema_version in {3, 4}:
        raw_aliases = payload.get("external_aliases", {})
        if not isinstance(raw_aliases, dict) or len(raw_aliases) > MAX_EXTERNAL_ALIASES:
            raise ProjectError("HOCUS450", "external_aliases must be a bounded table.")
        folded: set[str] = set()
        library_identities: dict[str, tuple[str, str | None]] = {}
        for alias, alias_record in raw_aliases.items():
            if not isinstance(alias, str) or not EXTERNAL_ALIAS_PATTERN.fullmatch(alias):
                raise ProjectError("HOCUS450", "External alias names must be bounded identifiers.")
            if alias.casefold() in folded:
                raise ProjectError("HOCUS450", "External aliases must be unique after case normalization.")
            expected_fields = {"library_uid", "version", "module_manifest_digest"}
            if not isinstance(alias_record, dict) or set(alias_record) - expected_fields:
                raise ProjectError("HOCUS450", "External alias records have unknown fields.")
            library_uid = alias_record.get("library_uid")
            version = alias_record.get("version")
            manifest_pin = alias_record.get("module_manifest_digest")
            if not isinstance(library_uid, str) or not PROJECT_UID_PATTERN.fullmatch(library_uid):
                raise ProjectError("HOCUS450", "External alias library UIDs are invalid.")
            if not isinstance(version, str) or not SEMANTIC_VERSION_PATTERN.fullmatch(version):
                raise ProjectError("HOCUS450", "External alias versions must be semantic versions.")
            if manifest_pin is not None and (
                not isinstance(manifest_pin, str) or not DIGEST_PATTERN.fullmatch(manifest_pin)
            ):
                raise ProjectError("HOCUS450", "External alias module manifest digest is invalid.")
            identity = (version, manifest_pin)
            prior_identity = library_identities.get(library_uid)
            if prior_identity is not None and prior_identity != identity:
                raise ProjectError(
                    "HOCUS450",
                    "Aliases for one external library UID must use one version and manifest digest.",
                )
            library_identities[library_uid] = identity
            folded.add(alias.casefold())
            aliases[alias] = dict(alias_record)
    return schema_version, project, language, lock, catalog, aliases


def _require_table_fields(table: Any, allowed: set[str], name: str) -> None:
    if not isinstance(table, dict) or set(table) - allowed:
        raise ProjectError("HOCUS405", f"[{name}] has unknown fields or is not a table.")


def _validate_source_directory_values(values: Any) -> None:
    if not isinstance(values, list) or not values or len(values) > MAX_PROJECT_DIRECTORIES:
        raise ProjectError("HOCUS427", "project.source_directories must be a non-empty bounded array.")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise ProjectError("HOCUS427", "Source-directory entries must be bounded non-empty strings.")
        if value != value.strip() or "\\" in value or ":" in value or value.startswith("/"):
            raise ProjectError("HOCUS427", "Source directories must use normalized portable relative paths.", details={"path": value})
        parts = value.split("/")
        if value != "." and any(part in {"", ".", ".."} for part in parts):
            raise ProjectError("HOCUS427", "Source directories cannot contain empty, dot, or parent segments.", details={"path": value})
        if value != ".":
            _validate_relative_artifact_path(value, "Source directory", code="HOCUS427")
        normalized.append(_portable_path_key(value))
    if len(set(normalized)) != len(normalized):
        raise ProjectError("HOCUS427", "Source directories must be unique after portable case normalization.")


def _validate_module_directory_values(values: Any) -> None:
    if not isinstance(values, list) or len(values) > MAX_PROJECT_DIRECTORIES:
        raise ProjectError("HOCUS449", "project.module_directories must be a bounded array.")
    if not values:
        return
    try:
        _validate_source_directory_values(values)
    except ProjectError as exc:
        raise ProjectError(
            "HOCUS449",
            exc.message.replace("Source directories", "Module directories").replace(
                "project.source_directories", "project.module_directories"
            ),
            details=exc.details,
        ) from exc


def _validate_relative_artifact_path(value: Any, label: str, *, code: str = "HOCUS405") -> None:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProjectError(code, f"{label} must be a bounded portable relative path.")
    if value != value.strip() or "\\" in value or ":" in value or value.startswith("/"):
        raise ProjectError(code, f"{label} must be a normalized portable relative path.", details={"path": value})
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ProjectError(code, f"{label} cannot contain empty, dot, or parent segments.", details={"path": value})
    for part in value.split("/"):
        if (
            part != unicodedata.normalize("NFC", part)
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or ord(char) == 127 for char in part)
            or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_PATH_SEGMENTS
        ):
            raise ProjectError(
                code,
                f"{label} contains a nonportable or Windows-reserved path segment.",
                details={"path": value},
            )


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
        max_values=MAX_LOCK_METADATA_VALUES_V3 if manifest_version in {3, 4} else MAX_METADATA_VALUES,
    )
    expected_keys = {"$schema", "kind", "schemaVersion", "projectUid", "manifestDigest", "languageVersion", "catalog", "modules"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} has missing or unknown fields.")
    expected_lock_version = manifest_version if manifest_version in {2, 3, 4} else 1
    expected_schema_uri = {
        1: LOCK_SCHEMA_URI,
        2: LOCK_SCHEMA_URI_V2,
        3: LOCK_SCHEMA_URI_V3,
        4: LOCK_SCHEMA_URI_V4,
    }[expected_lock_version]
    if (
        payload["$schema"] != expected_schema_uri
        or payload["kind"] != "hocus_project_lock"
        or type(payload["schemaVersion"]) is not int
        or payload["schemaVersion"] != expected_lock_version
    ):
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} uses an unsupported schema or kind.")
    if not isinstance(payload["projectUid"], str) or not PROJECT_UID_PATTERN.fullmatch(payload["projectUid"]):
        raise ProjectError("HOCUS422", "Lock projectUid is invalid.")
    if not isinstance(payload["manifestDigest"], str) or not DIGEST_PATTERN.fullmatch(payload["manifestDigest"]):
        raise ProjectError("HOCUS422", "Lock manifestDigest must be a lowercase SHA-256 digest.")
    if expected_lock_version == 3:
        lock_language_valid = payload["languageVersion"] == "0.2"
    elif expected_lock_version == 4:
        lock_language_valid = payload["languageVersion"] == "0.3"
    else:
        lock_language_valid = (
            isinstance(payload["languageVersion"], str)
            and payload["languageVersion"] in SUPPORTED_LANGUAGE_VERSIONS
        )
    if not lock_language_valid:
        raise ProjectError("HOCUS422", "Lock languageVersion is unsupported.")
    stale: dict[str, Any] = {}
    for key, expected in (("projectUid", project_uid), ("manifestDigest", manifest_digest), ("languageVersion", language_version)):
        if payload[key] != expected:
            stale[key] = {"expected": expected, "actual": payload[key]}
    if stale:
        raise ProjectError("HOCUS424", f"{PROJECT_LOCK_NAME} is stale.", details=stale)
    catalog_constraint: dict[str, Any] | None = None
    modules: tuple[ModuleLockRecord, ...] = ()
    if expected_lock_version == 1:
        if payload["catalog"] is not None or payload["modules"] != []:
            raise ProjectError("HOCUS425", "Lock v1 reserves catalog as null and modules as empty until HS2/HS6.")
    elif expected_lock_version == 2:
        catalog_constraint = _validate_catalog_lock(payload["catalog"], catalog_relative_path)
        if payload["modules"] != []:
            raise ProjectError("HOCUS425", "Lock v2 reserves modules as empty until HS6.")
    else:
        catalog_constraint = _validate_catalog_lock(payload["catalog"], catalog_relative_path)
        modules = _validate_module_locks(
            payload["modules"],
            project_uid=project_uid,
            external_aliases=external_aliases,
            expected_language_version="0.3" if expected_lock_version == 4 else "0.2",
        )
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    return _digest(canonical), catalog_constraint, modules


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
            raise ProjectError("HOCUS425", f"Lock v2 catalog {key} must be a lowercase SHA-256 digest.")
    return dict(value)


def _validate_module_locks(
    value: Any,
    *,
    project_uid: str,
    external_aliases: tuple[ExternalLibraryAlias, ...],
    expected_language_version: str = "0.2",
) -> tuple[ModuleLockRecord, ...]:
    if not isinstance(value, list) or len(value) > MAX_LOCKED_MODULES:
        raise ProjectError("HOCUS451", "Lock v3 modules must be a bounded array.")
    alias_map = {item.alias: item for item in external_aliases}
    expected_keys = {
        "moduleUri", "projectUid", "libraryUid", "libraryVersion", "moduleManifestDigest",
        "languageVersion", "sourcePath", "contentDigest", "interfaceDigest", "transitiveDigest",
        "dependencies", "externalAlias",
    }
    records: list[ModuleLockRecord] = []
    seen_uris: set[str] = set()
    seen_portable_paths: dict[tuple[str, str], str] = {}
    library_identities: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(value):
        pointer = f"modules[{index}]"
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ProjectError("HOCUS451", f"{pointer} has missing or unknown fields.")
        source_path = item["sourcePath"]
        _validate_relative_artifact_path(source_path, f"{pointer}.sourcePath", code="HOCUS451")
        if not source_path.endswith(".hocus"):
            raise ProjectError("HOCUS451", f"{pointer}.sourcePath must identify a .hocus file.")
        module_project_uid = item["projectUid"]
        alias = item["externalAlias"]
        if alias is None:
            if (
                module_project_uid != project_uid
                or any(item[key] is not None for key in (
                    "libraryUid", "libraryVersion", "moduleManifestDigest"
                ))
            ):
                raise ProjectError("HOCUS451", f"{pointer} has invalid local-project identity fields.")
            expected_uri = f"hocus-project://{project_uid}/{quote(source_path, safe='/-._~')}"
        else:
            alias_record = alias_map.get(alias) if isinstance(alias, str) else None
            if (
                alias_record is None
                or module_project_uid is not None
                or item["libraryUid"] != alias_record.library_uid
                or item["libraryVersion"] != alias_record.library_version
                or not isinstance(item["moduleManifestDigest"], str)
                or not DIGEST_PATTERN.fullmatch(item["moduleManifestDigest"])
                or (
                    alias_record.expected_module_manifest_digest is not None
                    and item["moduleManifestDigest"] != alias_record.expected_module_manifest_digest
                )
            ):
                raise ProjectError("HOCUS451", f"{pointer}.externalAlias identity does not match the manifest.")
            expected_uri = (
                f"hocus-module://{alias_record.library_uid}/"
                f"{quote(source_path, safe='/-._~')}"
            )
            library_identity = (item["libraryVersion"], item["moduleManifestDigest"])
            prior_library_identity = library_identities.get(alias_record.library_uid)
            if prior_library_identity is not None and prior_library_identity != library_identity:
                raise ProjectError(
                    "HOCUS451",
                    f"{pointer} conflicts with another version or manifest of the same library UID.",
                )
            library_identities[alias_record.library_uid] = library_identity
        if item["languageVersion"] != expected_language_version:
            raise ProjectError(
                "HOCUS451",
                f"{pointer}.languageVersion must be {expected_language_version}.",
            )
        if item["moduleUri"] != expected_uri or expected_uri in seen_uris:
            raise ProjectError("HOCUS451", f"{pointer}.moduleUri is noncanonical or duplicated.")
        owner = ("project", project_uid) if alias is None else ("library", item["libraryUid"])
        portable_key = (f"{owner[0]}:{owner[1]}", _portable_path_key(source_path))
        prior_uri = seen_portable_paths.get(portable_key)
        if prior_uri is not None:
            raise ProjectError(
                "HOCUS451",
                f"{pointer}.sourcePath aliases another portable module path.",
                details={"moduleUri": expected_uri, "conflictsWith": prior_uri},
            )
        seen_portable_paths[portable_key] = expected_uri
        seen_uris.add(expected_uri)
        for key in ("contentDigest", "interfaceDigest", "transitiveDigest"):
            if not isinstance(item[key], str) or not DIGEST_PATTERN.fullmatch(item[key]):
                raise ProjectError("HOCUS451", f"{pointer}.{key} must be a lowercase SHA-256 digest.")
        dependencies = item["dependencies"]
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > MAX_LOCKED_MODULES
            or any(not isinstance(dependency, str) or len(dependency) > 8192 for dependency in dependencies)
            or dependencies != sorted(set(dependencies))
            or expected_uri in dependencies
        ):
            raise ProjectError("HOCUS451", f"{pointer}.dependencies must be sorted, unique, and non-self-referential.")
        records.append(
            ModuleLockRecord(
                expected_uri,
                module_project_uid,
                item["libraryUid"],
                item["libraryVersion"],
                item["moduleManifestDigest"],
                item["languageVersion"],
                source_path,
                item["contentDigest"],
                item["interfaceDigest"],
                item["transitiveDigest"],
                tuple(dependencies),
                alias,
            )
        )
    if [item.module_uri for item in records] != sorted(seen_uris):
        raise ProjectError("HOCUS451", "Lock v3 modules must be sorted by moduleUri.")
    record_uris = set(seen_uris)
    for record in records:
        missing = set(record.dependencies) - record_uris
        if missing:
            raise ProjectError(
                "HOCUS451", "Module dependencies must reference records in the same lock.",
                details={"moduleUri": record.module_uri, "missing": sorted(missing)},
            )
    _reject_module_cycles(records)
    return tuple(records)


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
