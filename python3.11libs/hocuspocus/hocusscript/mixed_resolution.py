"""Verify-only native resolution of G3-published mixed module closures."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Callable, Mapping

from .external_roots import (
    _ValidatedExternalModuleRoots,
    _native_identity,
    _recheck as _recheck_external_roots,
    _validate_external_module_roots,
)
from .lock_update import _bounded_entries, _canonical_entry
from .module_lock_plan import (
    _Target,
    _external_target,
    _mixed_resolver_policy,
    _read_target,
    _relative_external_path,
    _require_same_inspection,
)
from .module_paths import is_literal_import_specifier
from .project import LockVerificationResult, ModuleLockRecord, ProjectContext, ProjectError, _portable_path_key
from .resolved_modules import (
    ModuleResolutionError,
    ModuleSourceEnvelope,
    ResolvedImport,
    ResolvedModuleDag,
    ResolvedModuleLimits,
    _validate_limits,
    _validate_resolved_mixed_module_dag,
    module_interface_digest,
)
from .resolver import (
    _cancel,
    _parse,
    _project_uri,
    _read_source,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _select_project_module_target,
    _validate_project_directory,
)


@dataclass(slots=True)
class _LoadedMixedModule:
    target: _Target
    locked: ModuleLockRecord
    source: bytes
    syntax: object
    imports: tuple[ResolvedImport, ...]
    identity: tuple[int, int, int]


@dataclass(slots=True)
class _LoadedMixedEntry:
    path: Path
    relative: str
    uri: str
    source: bytes
    imports: tuple[ResolvedImport, ...]
    identity: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _MixedResolutionSession:
    dag: ResolvedModuleDag
    recheck: Callable[[], None]


def _resolve_project_mixed_module_session(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> _MixedResolutionSession:
    project_value = _validate_project_directory(project_directory)
    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    authored_entry = _bounded_entries(
        (entry_source_path,), selected_limits.module_files, cancelled,
    )[0]
    roots = _validate_external_module_roots(
        project_value, module_roots, cancelled=cancelled,
    )
    if any(not item.manifest_was_pre_pinned for item in roots.roots):
        raise ProjectError(
            "HOCUS459",
            "Mixed module consumption requires every external manifest to be pre-pinned.",
        )
    context = ProjectContext.load(project_value, validate_lock=True)
    _require_same_inspection(context, roots)
    if context.uid is None or context.lock_digest is None:
        raise ProjectError("HOCUS452", "Mixed module resolution requires a verified v3 lock.")
    root = context.root.resolve(strict=True)
    for authored_root in context.module_directory_paths:
        _reject_reparse_components(root / authored_root, root)
        _require_exact_windows_casing(root / authored_root, root)
    by_alias = {item.alias: item for item in roots.roots}
    lock_by_uri = {item.module_uri: item for item in context.locked_modules}
    loaded: dict[str, _LoadedMixedModule] = {}
    states: dict[str, str] = {}
    decisions: list[tuple[_Target | None, Path, str, _Target]] = []
    aggregate = 0
    portable: set[tuple[str, str]] = set()

    def select(importer: _Target | None, importer_path: Path, specifier: str) -> _Target:
        if not is_literal_import_specifier(specifier):
            raise ProjectError("HOCUS460", "Mixed imports must be portable literal .hocus paths.")
        if specifier.startswith("@"):
            alias, separator, tail = specifier[1:].partition("/")
            external = by_alias.get(alias)
            if not separator or external is None:
                raise ProjectError("HOCUS460", "External import alias is not explicitly approved.")
            roots.root_for_alias(alias, require_manifest_pin=True)
            if importer is not None and importer.owner_kind == "library" and importer.alias == alias:
                raise ProjectError("HOCUS460", "Same-library alias imports are forbidden.")
            if tail not in external.pin.entry_modules:
                raise ProjectError("HOCUS462", "External alias imports may enter only manifest entries.")
            target = _external_target(external, tail)
        elif importer is not None and importer.owner_kind == "library":
            if not specifier.startswith(("./", "../")):
                raise ProjectError("HOCUS460", "Bare imports are disabled inside external libraries.")
            external = by_alias[importer.alias or ""]
            target = _external_target(
                external,
                _relative_external_path(external.root, importer_path.parent / specifier),
            )
        else:
            selected = _select_project_module_target(
                context, importer_path, specifier, cancelled=cancelled,
            )
            relative = selected.relative_to(root).as_posix()
            target = _Target(
                _project_uri(context.uid or "", relative),
                selected,
                relative,
                "project",
                context.uid or "",
                None,
                root,
            )
        _require_locked_target(target, lock_by_uri, roots)
        decisions.append((importer, importer_path, specifier, target))
        return target

    def visit(target: _Target, depth: int) -> None:
        nonlocal aggregate
        _cancel(cancelled)
        if depth > selected_limits.import_depth:
            raise ModuleResolutionError("HOCUS464", "Mixed module closure exceeds importDepth.")
        state = states.get(target.uri)
        if state == "visiting":
            raise ModuleResolutionError("HOCUS463", "Mixed module imports contain a cycle.")
        if state == "done":
            return
        if len(states) >= selected_limits.module_files:
            raise ModuleResolutionError("HOCUS464", "Mixed module closure exceeds moduleFiles.")
        key = (f"{target.owner_kind}:{target.owner_uid}", _portable_path_key(target.relative))
        if key in portable:
            raise ProjectError("HOCUS462", "Mixed module paths alias after portable normalization.")
        portable.add(key)
        states[target.uri] = "visiting"
        locked = lock_by_uri[target.uri]
        source, identity = _read_target(target, selected_limits, cancelled)
        aggregate += len(source)
        if aggregate > selected_limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Mixed source closure exceeds aggregateSourceBytes.")
        syntax = _parse(source, target.uri, graph=False)
        imports: list[ResolvedImport] = []
        target_uris: set[str] = set()
        local_names: set[str] = set()
        specifiers: set[str] = set()
        for declaration in syntax.imports:
            _cancel(cancelled)
            selected = select(target, target.path, declaration.specifier)
            if (
                declaration.local_name in local_names
                or declaration.specifier in specifiers
                or selected.uri in target_uris
            ):
                raise ProjectError("HOCUS462", "Mixed module imports must be unique.")
            visit(selected, depth + 1)
            imports.append(ResolvedImport(
                declaration.specifier,
                declaration.imported_name,
                declaration.local_name,
                selected.uri,
                declaration.span,
            ))
            local_names.add(declaration.local_name)
            specifiers.add(declaration.specifier)
            target_uris.add(selected.uri)
        loaded[target.uri] = _LoadedMixedModule(
            target, locked, source, syntax, tuple(imports), identity,
        )
        states[target.uri] = "done"

    entry_path = _canonical_entry(context, authored_entry)
    entry_relative = entry_path.relative_to(root).as_posix()
    portable.add((f"project:{context.uid}", _portable_path_key(entry_relative)))
    entry_uri = _project_uri(context.uid, entry_relative)
    entry_source = _read_source(entry_path, selected_limits, cancelled)
    entry_identity = _native_identity(entry_path, "entry source")
    aggregate += len(entry_source)
    if aggregate > selected_limits.aggregate_source_bytes:
        raise ModuleResolutionError("HOCUS464", "Mixed source closure exceeds aggregateSourceBytes.")
    entry_syntax = _parse(entry_source, entry_uri, graph=True)
    entry_imports: list[ResolvedImport] = []
    target_uris: set[str] = set()
    local_names: set[str] = set()
    specifiers: set[str] = set()
    for declaration in entry_syntax.imports:
        selected = select(None, entry_path, declaration.specifier)
        if (
            declaration.local_name in local_names
            or declaration.specifier in specifiers
            or selected.uri in target_uris
        ):
            raise ProjectError("HOCUS462", "Mixed entry imports must be unique.")
        visit(selected, 1)
        entry_imports.append(ResolvedImport(
            declaration.specifier,
            declaration.imported_name,
            declaration.local_name,
            selected.uri,
            declaration.span,
        ))
        local_names.add(declaration.local_name)
        specifiers.add(declaration.specifier)
        target_uris.add(selected.uri)
    entry = _LoadedMixedEntry(
        entry_path,
        entry_relative,
        entry_uri,
        entry_source,
        tuple(entry_imports),
        entry_identity,
    )
    policy = _mixed_resolver_policy(context, roots)
    policy_digest = module_interface_digest(policy)
    dag = _validate_resolved_mixed_module_dag(
        tuple(
            ModuleSourceEnvelope(item.target.uri, item.source, item.imports)
            for item in loaded.values()
        ),
        lock_verification=LockVerificationResult(
            context.uid,
            context.manifest_digest or "",
            context.lock_digest,
            context.locked_modules,
        ),
        entry_source_uri=entry.uri,
        entry_source=entry.source,
        entry_imports=entry.imports,
        resolver_policy=policy,
        resolver_policy_digest=policy_digest,
        catalog_content_digest=context.catalog_content_digest,
        catalog_fingerprint=context.catalog_fingerprint,
        limits=selected_limits,
        cancelled=cancelled,
    )

    def recheck() -> None:
        _cancel(cancelled)
        refreshed = ProjectContext.load(context.root, validate_lock=True)
        if (
            refreshed.uid != context.uid
            or refreshed.manifest_digest != context.manifest_digest
            or refreshed.lock_digest != context.lock_digest
            or refreshed.catalog_content_digest != context.catalog_content_digest
            or refreshed.catalog_fingerprint != context.catalog_fingerprint
            or refreshed.module_directory_paths != context.module_directory_paths
            or refreshed.external_aliases != context.external_aliases
            or refreshed.locked_modules != context.locked_modules
        ):
            raise ProjectError("HOCUS428", "Mixed project, lock, catalog, or policy changed.")
        _recheck_external_roots(context, roots, cancelled)
        if _canonical_entry(refreshed, entry.relative) != entry.path:
            raise ProjectError("HOCUS428", "Mixed entry identity changed during resolution.")
        if _native_identity(entry.path, "entry source") != entry.identity:
            raise ProjectError("HOCUS428", "Mixed entry object changed during resolution.")
        if _read_source(entry.path, selected_limits, cancelled) != entry.source:
            raise ProjectError("HOCUS428", "Mixed entry bytes changed during resolution.")
        for item in loaded.values():
            current, identity = _read_target(item.target, selected_limits, cancelled)
            if identity != item.identity or current != item.source:
                raise ProjectError("HOCUS428", "Mixed module source changed during resolution.")
            _require_locked_target(item.target, lock_by_uri, roots)
        initial_count = len(decisions)
        for importer, importer_path, specifier, expected in tuple(decisions):
            if select(importer, importer_path, specifier) != expected:
                raise ProjectError("HOCUS428", "Mixed import winner changed during resolution.")
        del decisions[initial_count:]
        _cancel(cancelled)

    recheck()
    return _MixedResolutionSession(dag, recheck)


def _require_locked_target(
    target: _Target,
    lock_by_uri: Mapping[str, ModuleLockRecord],
    roots: _ValidatedExternalModuleRoots,
) -> ModuleLockRecord:
    locked = lock_by_uri.get(target.uri)
    if locked is None or locked.source_path != target.relative:
        raise ProjectError("HOCUS462", "Mixed target is absent from the published lock.")
    if target.owner_kind == "project":
        if (
            locked.external_alias is not None
            or locked.project_uid != target.owner_uid
            or any(value is not None for value in (
                locked.library_uid,
                locked.library_version,
                locked.module_manifest_digest,
            ))
        ):
            raise ProjectError("HOCUS462", "Published project module provenance is invalid.")
    else:
        approved = next((item for item in roots.roots if item.alias == target.alias), None)
        if (
            approved is None
            or locked.external_alias != approved.alias
            or locked.project_uid is not None
            or locked.library_uid != approved.pin.library_uid
            or locked.library_version != approved.pin.library_version
            or locked.module_manifest_digest != approved.pin.module_manifest_digest
        ):
            raise ProjectError("HOCUS462", "Published external module provenance is invalid.")
    return locked
