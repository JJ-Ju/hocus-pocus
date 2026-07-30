"""Resolver-derived publication of same-project HocusScript 0.3 locks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable

from .catalog import (
    MAX_CATALOG_BYTES,
    CatalogSnapshot,
    CatalogValidationError,
    decode_catalog_snapshot,
)
from .control_catalog import validate_control_catalog_program
from .control_expander import expand_control_graph
from .control_resolver import ControlResolverLimits, _parse_control_source
from .control_semantic import ControlExpansionLimits
from .expander import ResolvedModuleUnit
from .lock_update import _bounded_entries, _canonical_entry, _dependency_order
from .lock_update_result import ModuleLockUpdateEntry, ModuleLockUpdateResult
from .module_paths import is_literal_import_specifier
from .project import (
    LOCK_SCHEMA_URI_V4,
    LOCK_SCHEMA_URI_V5,
    MAX_LOCK_BYTES_V3,
    LockVerificationResult,
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    _atomic_write_lock,
    _check_expected_lock,
    _digest,
    _exclusive_update_lease,
    _is_contained,
    _portable_path_key,
    _read_bounded_stable,
    _recheck_update_inputs,
    _require_metadata_file,
)
from .project_lock_validation import validate_module_locks
from .resolved_modules import (
    ModuleResolutionError,
    ResolvedImport,
    _module_interface,
    module_interface_digest,
    module_source_digest,
    module_transitive_digest,
)
from .resolver import (
    _cancel,
    _canonical_file,
    _lexically_occupied,
    _project_uri,
    _read_source,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _validate_project_directory,
)
from .syntax import SyntaxSource


@dataclass(slots=True)
class _ScannedControlModule:
    uri: str
    path: Path
    relative_path: str
    source: bytes
    syntax: SyntaxSource
    imports: tuple[ResolvedImport, ...]
    dependencies: tuple[str, ...]

    def resolved_unit(self) -> ResolvedModuleUnit:
        return ResolvedModuleUnit(
            self.uri,
            module_source_digest(self.source),
            self.syntax,
            MappingProxyType({
                item.local_name: item
                for item in self.imports
            }),
        )


@dataclass(slots=True)
class _ScannedControlEntry:
    uri: str
    path: Path
    relative_path: str
    source: bytes
    syntax: SyntaxSource
    imports: tuple[ResolvedImport, ...]
    closure: frozenset[str]


@dataclass(slots=True)
class _ControlLockDerivation:
    project: ProjectContext
    entry_paths: tuple[str, ...]
    limits: ControlResolverLimits
    control_limits: ControlExpansionLimits
    catalog: CatalogSnapshot
    cancelled: Callable[[], bool] | None
    root: Path
    module_roots: tuple[Path, ...]
    decisions: list[tuple[Path, str, Path]] = field(default_factory=list)
    source_evidence: dict[Path, bytes] = field(default_factory=dict)
    scanned: dict[str, _ScannedControlModule] = field(default_factory=dict)
    states: dict[str, str] = field(default_factory=dict)
    portable_paths: dict[str, str] = field(default_factory=dict)
    entries: list[_ScannedControlEntry] = field(default_factory=list)
    aggregate_source_bytes: int = 0

    @classmethod
    def create(
        cls,
        project: ProjectContext,
        entry_paths: tuple[str, ...],
        limits: ControlResolverLimits,
        control_limits: ControlExpansionLimits,
        catalog: CatalogSnapshot,
        cancelled: Callable[[], bool] | None,
    ) -> "_ControlLockDerivation":
        _require_control_project(project)
        root = project.root.resolve(strict=True)
        if len(project.module_directory_paths) != len(project.module_directories):
            raise ProjectError(
                "HOCUS452",
                "Control project lost ordered module-directory provenance.",
            )
        for authored_root in project.module_directory_paths:
            _reject_reparse_components(root / authored_root, root)
            _require_exact_windows_casing(root / authored_root, root)
        return cls(
            project,
            entry_paths,
            limits,
            control_limits,
            catalog,
            cancelled,
            root,
            tuple(project.module_directories),
        )

    def derive(
        self,
    ) -> tuple[
        tuple[ModuleLockRecord, ...],
        tuple[_ScannedControlEntry, ...],
        Callable[[], None],
    ]:
        self._scan_entries()
        records = self._records()
        self._validate_entries()
        return records, tuple(self.entries), self.recheck

    def select(self, importer: Path, specifier: str) -> Path:
        if not is_literal_import_specifier(specifier) or specifier.startswith("@"):
            raise ProjectError(
                "HOCUS460",
                "Language 0.3 lock derivation accepts literal local imports only.",
            )
        if specifier.startswith(("./", "../")):
            return self._contained_candidate(
                importer.parent / specifier,
                "relative control module import",
            )
        return self._select_bare(specifier)

    def visit(self, path: Path, depth: int) -> str:
        _cancel(self.cancelled)
        relative = path.relative_to(self.root).as_posix()
        uri = _project_uri(self.project.uid or "", relative)
        state = self.states.get(uri)
        if state == "visiting":
            raise ModuleResolutionError(
                "HOCUS463",
                "Derived control module imports contain a cycle.",
            )
        if state == "done":
            return uri
        if len(self.states) >= self.limits.module_files:
            raise ModuleResolutionError(
                "HOCUS464",
                "Derived control module closure exceeds moduleFiles.",
            )
        if depth > self.limits.import_depth:
            raise ModuleResolutionError(
                "HOCUS464",
                "Derived control module closure exceeds importDepth.",
            )
        self._claim_portable(relative, uri)
        self.states[uri] = "visiting"
        source = self._read(path)
        syntax = _parse_control_source(
            source,
            uri,
            graph=False,
            language_version=self.project.language_version,
        )
        imports, dependencies = self._scan_imports(path, syntax, depth)
        self.scanned[uri] = _ScannedControlModule(
            uri,
            path,
            relative,
            source,
            syntax,
            imports,
            dependencies,
        )
        self.states[uri] = "done"
        return uri

    def recheck(self) -> None:
        _cancel(self.cancelled)
        cancelled = self.cancelled
        self.cancelled = None
        try:
            self._recheck_without_cancellation()
        finally:
            self.cancelled = cancelled

    def _recheck_without_cancellation(self) -> None:
        refreshed = ProjectContext.load(self.root, validate_lock=False)
        if _resolver_pins(refreshed) != _resolver_pins(self.project):
            raise ProjectError(
                "HOCUS453",
                "Control project resolver policy changed before lock publication.",
            )
        _require_control_project(refreshed)
        for path, expected in self.source_evidence.items():
            self._recheck_source(path, expected)
        for entry in self.entries:
            if _canonical_entry(refreshed, entry.relative_path) != entry.path:
                raise ProjectError(
                    "HOCUS453",
                    "Control entry source resolution changed before lock publication.",
                )
        for importer, specifier, expected in self.decisions:
            if self.select(importer, specifier) != expected:
                raise ProjectError(
                    "HOCUS453",
                    "Control import winner changed before lock publication.",
                )

    def _scan_entries(self) -> None:
        for authored in self.entry_paths:
            _cancel(self.cancelled)
            path = _canonical_entry(self.project, authored)
            relative = path.relative_to(self.root).as_posix()
            uri = _project_uri(self.project.uid or "", relative)
            self._claim_portable(relative, uri)
            source = self._read(path)
            syntax = _parse_control_source(
                source,
                uri,
                graph=True,
                language_version=self.project.language_version,
            )
            imports, roots = self._scan_imports(path, syntax, 0)
            self.entries.append(_ScannedControlEntry(
                uri,
                path,
                relative,
                source,
                syntax,
                imports,
                self._closure(roots),
            ))

    def _scan_imports(
        self,
        importer: Path,
        syntax: SyntaxSource,
        depth: int,
    ) -> tuple[tuple[ResolvedImport, ...], tuple[str, ...]]:
        imports: list[ResolvedImport] = []
        roots: list[str] = []
        for declaration in syntax.imports:
            _cancel(self.cancelled)
            target = self.select(importer, declaration.specifier)
            self.decisions.append((importer, declaration.specifier, target))
            target_uri = self.visit(target, depth + 1)
            imports.append(ResolvedImport(
                declaration.specifier,
                declaration.imported_name,
                declaration.local_name,
                target_uri,
                declaration.span,
            ))
            roots.append(target_uri)
        aliases = [item.local_name for item in imports]
        if len(set(aliases)) != len(aliases):
            raise ProjectError(
                "HOCUS463",
                "Derived control imports contain duplicate local aliases.",
                details={"sourceUri": syntax.span.source_name},
            )
        return tuple(imports), tuple(sorted(set(roots)))

    def _records(self) -> tuple[ModuleLockRecord, ...]:
        by_uri: dict[str, ModuleLockRecord] = {}
        legacy_limits = self.limits.to_legacy_shape()
        for uri in _dependency_order(self.scanned):
            item = self.scanned[uri]
            source_digest = module_source_digest(item.source)
            interface_digest = module_interface_digest(
                _module_interface(item.syntax, legacy_limits, uri)
            )
            transitive_digest = module_transitive_digest(
                uri=uri,
                source_digest=source_digest,
                interface_digest=interface_digest,
                dependencies=(
                    (child, by_uri[child].transitive_digest)
                    for child in item.dependencies
                ),
            )
            by_uri[uri] = ModuleLockRecord(
                uri,
                self.project.uid,
                None,
                None,
                None,
                self.project.language_version,
                item.relative_path,
                source_digest,
                interface_digest,
                transitive_digest,
                item.dependencies,
                None,
            )
        return tuple(by_uri[uri] for uri in sorted(by_uri))

    def _validate_entries(self) -> None:
        for entry in self.entries:
            _cancel(self.cancelled)
            modules = MappingProxyType({
                uri: self.scanned[uri].resolved_unit()
                for uri in sorted(entry.closure)
            })
            imports = MappingProxyType({
                item.local_name: item
                for item in entry.imports
            })
            admission = validate_control_catalog_program(
                entry.syntax,
                imports,
                modules,
                self.catalog,
                expected_catalog_fingerprint=self.catalog.fingerprint,
                limits=self.control_limits,
                cancellation=self.cancelled,
            )
            if not admission.valid:
                primary = admission.diagnostics[0]
                raise ProjectError(
                    primary.code,
                    primary.message,
                    details={
                        "entrySourceUri": entry.uri,
                        "diagnostic": primary.to_dict(),
                        "diagnostics": [
                            item.to_dict()
                            for item in admission.diagnostics
                        ],
                    },
                )
            expand_control_graph(
                entry.source,
                entry.uri,
                imports,
                modules,
                limits=self.control_limits,
                cancellation=self.cancelled,
            )

    def _select_bare(self, specifier: str) -> Path:
        for directory in self.module_roots:
            _cancel(self.cancelled)
            candidate = directory / specifier
            if not _lexically_occupied(candidate):
                continue
            target = self._contained_candidate(
                candidate,
                "bare control module import",
            )
            if not _is_contained(target, directory.resolve(strict=True)):
                raise ProjectError(
                    "HOCUS460",
                    "Bare control module import escapes its configured root.",
                )
            return target
        raise ProjectError(
            "HOCUS462",
            "Bare control module import was not found in ordered module_directories.",
            details={"specifier": specifier},
        )

    def _contained_candidate(self, candidate: Path, label: str) -> Path:
        _reject_reparse_components(candidate, self.root)
        _require_exact_windows_casing(candidate, self.root)
        return _canonical_file(candidate, self.root, label)

    def _read(self, path: Path) -> bytes:
        source = _read_source(
            path,
            self.limits.to_legacy_shape(),
            self.cancelled,
        )
        self.aggregate_source_bytes += len(source)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ModuleResolutionError(
                "HOCUS464",
                "Derived control sources exceed aggregateSourceBytes.",
            )
        self.source_evidence[path] = source
        return source

    def _claim_portable(self, relative: str, uri: str) -> None:
        key = _portable_path_key(relative)
        previous = self.portable_paths.get(key)
        if previous is not None:
            raise ProjectError(
                "HOCUS462",
                "Control entries and modules must be portably path-unique.",
                details={"sourceUri": uri, "conflictsWith": previous},
            )
        self.portable_paths[key] = uri

    def _closure(self, roots: tuple[str, ...]) -> frozenset[str]:
        closure: set[str] = set()
        pending = list(roots)
        while pending:
            uri = pending.pop()
            if uri in closure:
                continue
            closure.add(uri)
            pending.extend(self.scanned[uri].dependencies)
        return frozenset(closure)

    def _recheck_source(self, path: Path, expected: bytes) -> None:
        _reject_reparse_components(path, self.root)
        _require_exact_windows_casing(path, self.root)
        if _canonical_file(path, self.root, "control source recheck") != path:
            raise ProjectError(
                "HOCUS453",
                "Control source identity changed before lock publication.",
            )
        current = _read_source(
            path,
            self.limits.to_legacy_shape(),
            self.cancelled,
        )
        if current != expected:
            raise ProjectError(
                "HOCUS453",
                "Control source changed before lock publication.",
            )


def update_project_control_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    *,
    allow_write: bool = False,
    expected_lock_digest: str | None = None,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleLockUpdateResult:
    """Derive, validate, and atomically publish one local v4 module lock."""

    if allow_write is not True:
        raise ProjectError(
            "HOCUS455",
            "Control lock derivation requires explicit allow_write=True authority.",
        )
    project_value = _validate_project_directory(project_directory)
    resolver_limits, control_limits = _select_limits(limits)
    entries = _bounded_entries(
        entry_source_paths,
        resolver_limits.module_files,
        cancelled,
    )
    return _publish_control_lock(
        project_value,
        entries,
        expected_lock_digest=expected_lock_digest,
        limits=resolver_limits,
        control_limits=control_limits,
        cancelled=cancelled,
    )


def _publish_control_lock(
    project_directory: str,
    entry_paths: tuple[str, ...],
    *,
    expected_lock_digest: str | None,
    limits: ControlResolverLimits,
    control_limits: ControlExpansionLimits,
    cancelled: Callable[[], bool] | None,
) -> ModuleLockUpdateResult:
    initial = ProjectContext.load(project_directory, validate_lock=False)
    _require_control_project(initial)
    assert initial.lock_path is not None
    with _exclusive_update_lease(initial.lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        _require_stable_project(initial, project)
        assert project.lock_path is not None
        prior_digest = _check_expected_lock(
            project.lock_path,
            project.root,
            expected_lock_digest,
        )
        before = _current_verification(project, prior_digest)
        catalog, catalog_digest = _load_catalog(project)
        derivation = _ControlLockDerivation.create(
            project,
            entry_paths,
            limits,
            control_limits,
            catalog,
            cancelled,
        )
        modules, scanned_entries, final_source_recheck = derivation.derive()
        modules = _strict_modules(modules, project)
        encoded, lock_digest = _lock_payload(
            project,
            modules,
            catalog,
            catalog_digest,
        )
        after = LockVerificationResult(
            project.uid or "",
            project.manifest_digest or "",
            lock_digest,
            modules,
        )
        result = ModuleLockUpdateResult.from_verifications(
            before,
            after,
            previous_lock_digest=prior_digest,
            catalog_content_digest=catalog_digest,
            catalog_fingerprint=catalog.fingerprint,
            entries=tuple(
                ModuleLockUpdateEntry(
                    entry.uri,
                    module_source_digest(entry.source),
                )
                for entry in scanned_entries
            ),
        )

        def before_publish() -> None:
            final_source_recheck()
            _recheck_update_inputs(
                project,
                catalog_digest=catalog_digest,
                initial_lock_digest=prior_digest,
            )

        _atomic_write_lock(
            project.lock_path,
            encoded,
            expected_lock_digest=expected_lock_digest,
            before_publish=before_publish,
        )
        return result


def _load_catalog(project: ProjectContext) -> tuple[CatalogSnapshot, str]:
    assert project.catalog_path is not None
    _require_metadata_file(project.catalog_path, project.root, "Catalog snapshot")
    raw = _read_bounded_stable(
        project.catalog_path,
        MAX_CATALOG_BYTES,
        "HOCUS432",
        "Catalog snapshot",
    )
    try:
        catalog = decode_catalog_snapshot(raw)
    except CatalogValidationError as exc:
        raise ProjectError(
            "HOCUS434",
            f"Invalid catalog snapshot: {exc.message}",
            details={"catalogCode": exc.code, "catalogPath": exc.path},
        ) from exc
    return catalog, _digest(raw)


def _lock_payload(
    project: ProjectContext,
    modules: tuple[ModuleLockRecord, ...],
    catalog: CatalogSnapshot,
    catalog_digest: str,
) -> tuple[bytes, str]:
    payload = {
        "$schema": (
            LOCK_SCHEMA_URI_V5
            if project.manifest_version == 5
            else LOCK_SCHEMA_URI_V4
        ),
        "kind": "hocus_project_lock",
        "schemaVersion": project.manifest_version,
        "projectUid": project.uid,
        "manifestDigest": project.manifest_digest,
        "languageVersion": project.language_version,
        "catalog": {
            "schemaVersion": catalog.catalog_version,
            "path": project.catalog_relative_path,
            "contentDigest": catalog_digest,
            "fingerprint": catalog.fingerprint,
        },
        "modules": [item.to_dict() for item in modules],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_LOCK_BYTES_V3:
        raise ProjectError(
            "HOCUS410",
            "Generated control project lock exceeds the lock byte limit.",
        )
    return encoded, _digest(canonical)


def _strict_modules(
    modules: tuple[ModuleLockRecord, ...],
    project: ProjectContext,
) -> tuple[ModuleLockRecord, ...]:
    if any(
        item.external_alias is not None
        or item.project_uid != project.uid
        for item in modules
    ):
        raise ProjectError(
            "HOCUS451",
            "Control lock publication accepts same-project modules only.",
        )
    validated = validate_module_locks(
        [item.to_dict() for item in modules],
        project_uid=project.uid or "",
        external_aliases=(),
        expected_language_version=project.language_version,
    )
    if validated != modules:
        raise ProjectError(
            "HOCUS451",
            "Derived control module records are not canonical.",
        )
    return validated


def _current_verification(
    project: ProjectContext,
    lock_digest: str | None,
) -> LockVerificationResult | None:
    if lock_digest is None:
        return None
    try:
        from .project import verify_project_lock

        return verify_project_lock(project.root)
    except ProjectError:
        return None


def _require_control_project(project: ProjectContext) -> None:
    if (
        (project.manifest_version, project.language_version)
        not in {(4, "0.3"), (5, "0.4")}
        or project.uid is None
        or project.manifest_digest is None
        or project.lock_path is None
        or project.catalog_path is None
        or project.catalog_relative_path is None
    ):
        raise ProjectError(
            "HOCUS452",
            "Control lock derivation requires a portable schema-v4/v5 control project.",
        )
    if project.external_aliases:
        raise ProjectError(
            "HOCUS460",
            "External aliases are disabled for same-project control lock derivation.",
        )


def _require_stable_project(
    initial: ProjectContext,
    project: ProjectContext,
) -> None:
    _require_control_project(project)
    if (
        project.root != initial.root
        or project.uid != initial.uid
        or project.manifest_digest != initial.manifest_digest
        or project.lock_path != initial.lock_path
        or project.catalog_path != initial.catalog_path
        or project.catalog_relative_path != initial.catalog_relative_path
    ):
        raise ProjectError(
            "HOCUS453",
            "Control project configuration changed before lock update.",
        )


def _resolver_pins(project: ProjectContext) -> tuple:
    return (
        project.root,
        project.uid,
        project.manifest_version,
        project.language_version,
        project.manifest_digest,
        project.lock_path,
        project.catalog_path,
        project.catalog_relative_path,
        project.module_directory_paths,
        project.module_directories,
        project.external_aliases,
    )


def _select_limits(
    value: ControlResolverLimits | ControlExpansionLimits | None,
) -> tuple[ControlResolverLimits, ControlExpansionLimits]:
    if value is None:
        control = ControlExpansionLimits()
        return ControlResolverLimits.from_control_limits(control), control
    if isinstance(value, ControlExpansionLimits):
        return ControlResolverLimits.from_control_limits(value), value
    if isinstance(value, ControlResolverLimits):
        return value, value.to_control_limits()
    raise TypeError(
        "limits must be a ControlResolverLimits or ControlExpansionLimits",
    )


__all__ = ["update_project_control_lock"]
