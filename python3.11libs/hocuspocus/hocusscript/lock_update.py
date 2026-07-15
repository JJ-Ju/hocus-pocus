"""Resolver-derived, explicit-authority HocusScript module lock updates."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from os import PathLike, fspath
from pathlib import Path
from typing import Callable, Iterable

from .lock_update_result import ModuleLockUpdateEntry, ModuleLockUpdateResult
from .expander import expand_resolved_module_dag
from .project import (
    LockVerificationResult, ModuleLockRecord, ProjectContext, ProjectError,
    _is_contained, _portable_path_key, _publish_derived_module_lock,
)
from .resolved_modules import (
    ModuleResolutionError, ModuleSourceEnvelope, ResolvedImport, ResolvedModuleLimits,
    _module_interface, _validate_limits, module_interface_digest, module_source_digest,
    module_transitive_digest, validate_resolved_module_dag,
)
from .resolver import (
    _cancel, _canonical_file, _lexically_occupied, _parse, _project_uri,
    _read_source, _reject_reparse_components, _require_exact_windows_casing,
    _validate_project_directory,
)


@dataclass(slots=True)
class _ScannedModule:
    uri: str
    path: Path
    relative: str
    source: bytes
    syntax: object
    imports: tuple[ResolvedImport, ...]
    dependencies: tuple[str, ...]


@dataclass(slots=True)
class _ScannedEntry:
    path: Path
    relative: str
    uri: str
    source: bytes
    imports: tuple[ResolvedImport, ...]
    closure: set[str]


def update_project_module_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    *,
    allow_write: bool = False,
    expected_lock_digest: str | None = None,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleLockUpdateResult:
    """Derive and atomically publish a same-project v3 module lock.

    The update lease covers the expected-digest check, all source resolution and
    derivation, final source/winner rechecks, and atomic publication.
    """
    if allow_write is not True:
        raise ProjectError("HOCUS455", "Module lock derivation requires explicit allow_write=True authority.")
    project_value = _validate_project_directory(project_directory)
    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    authored_entries = _bounded_entries(entry_source_paths, selected_limits.module_files, cancelled)
    scanned_entries: list[_ScannedEntry] = []

    def derive(project: ProjectContext):
        nonlocal scanned_entries
        modules, entries, envelopes, recheck = _derive_under_lease(
            project, authored_entries, selected_limits, cancelled,
        )
        scanned_entries = entries
        future = LockVerificationResult(
            project.uid or "", project.manifest_digest or "",
            "sha256:" + "0" * 64, modules,
        )
        by_uri = {item.uri: item for item in envelopes}
        policy = _resolver_policy(project)
        for entry in entries:
            _cancel(cancelled)
            dag = validate_resolved_module_dag(
                tuple(by_uri[uri] for uri in sorted(entry.closure)),
                lock_verification=future,
                entry_source_uri=entry.uri,
                entry_source=entry.source,
                entry_imports=entry.imports,
                resolver_policy=policy,
                resolver_policy_digest=module_interface_digest(policy),
                limits=selected_limits,
                cancelled=cancelled,
            )
            expand_resolved_module_dag(dag, cancellation=cancelled)
        return modules, recheck

    def build_result(previous, before, after, catalog_digest, catalog_fingerprint):
        return ModuleLockUpdateResult.from_verifications(
            before, after,
            previous_lock_digest=previous,
            catalog_content_digest=catalog_digest,
            catalog_fingerprint=catalog_fingerprint,
            entries=tuple(
                ModuleLockUpdateEntry(item.uri, module_source_digest(item.source))
                for item in scanned_entries
            ),
        )

    return _publish_derived_module_lock(
        project_value, expected_lock_digest=expected_lock_digest,
        derive=derive, build_result=build_result,
    )


def _derive_under_lease(project, entry_paths, limits, cancelled):
    if project.manifest_version != 3 or project.language_version != "0.2" or not project.uid:
        raise ProjectError("HOCUS452", "Module lock derivation requires a language 0.2 v3 project.")
    root = project.root.resolve(strict=True)
    module_roots = tuple(project.module_directories)
    if len(project.module_directory_paths) != len(module_roots):
        raise ProjectError("HOCUS452", "Project lost ordered module-directory provenance.")
    for authored_root in project.module_directory_paths:
        _reject_reparse_components(root / authored_root, root)
        _require_exact_windows_casing(root / authored_root, root)
    decisions: list[tuple[Path, str, Path]] = []
    source_evidence: dict[Path, bytes] = {}
    scanned: dict[str, _ScannedModule] = {}
    states: dict[str, str] = {}
    portable: dict[str, str] = {}
    aggregate = 0

    def select(importer: Path, specifier: str) -> Path:
        if specifier.startswith("@"):
            raise ProjectError("HOCUS460", "External aliases are disabled for derived module locks.")
        if specifier.startswith(("./", "../")):
            candidate = importer.parent / specifier
            _reject_reparse_components(candidate, root)
            _require_exact_windows_casing(candidate, root)
            return _canonical_file(candidate, root, "relative module import")
        for directory in module_roots:
            _cancel(cancelled)
            candidate = directory / specifier
            if _lexically_occupied(candidate):
                _reject_reparse_components(candidate, root)
                _require_exact_windows_casing(candidate, root)
                target = _canonical_file(candidate, root, "bare module import")
                if not _is_contained(target, directory.resolve(strict=True)):
                    raise ProjectError("HOCUS460", "Bare module import escapes its configured root.")
                return target
        raise ProjectError("HOCUS462", "Bare module import was not found in ordered module_directories.")

    def visit(path: Path, depth: int) -> str:
        nonlocal aggregate
        _cancel(cancelled)
        relative = path.relative_to(root).as_posix()
        uri = _project_uri(project.uid, relative)
        if states.get(uri) == "visiting":
            raise ModuleResolutionError("HOCUS463", "Derived module imports contain a cycle.")
        if states.get(uri) == "done":
            return uri
        if len(states) >= limits.module_files or depth > limits.import_depth:
            raise ModuleResolutionError("HOCUS464", "Derived module closure exceeds its limits.")
        key = _portable_path_key(relative)
        if key in portable and portable[key] != uri:
            raise ProjectError("HOCUS462", "Derived modules alias after portable normalization.")
        portable[key] = uri
        states[uri] = "visiting"
        source = _read_source(path, limits, cancelled)
        source_evidence[path] = source
        aggregate += len(source)
        if aggregate > limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Derived source closure exceeds aggregateSourceBytes.")
        syntax = _parse(source, uri, graph=False)
        imports: list[ResolvedImport] = []
        dependencies: list[str] = []
        for declaration in syntax.imports:
            target = select(path, declaration.specifier)
            decisions.append((path, declaration.specifier, target))
            target_uri = visit(target, depth + 1)
            imports.append(ResolvedImport(
                declaration.specifier, declaration.imported_name, declaration.local_name,
                target_uri, declaration.span,
            ))
            dependencies.append(target_uri)
        scanned[uri] = _ScannedModule(
            uri, path, relative, source, syntax, tuple(imports), tuple(sorted(set(dependencies))),
        )
        states[uri] = "done"
        return uri

    entries: list[_ScannedEntry] = []
    for authored in entry_paths:
        _cancel(cancelled)
        entry_path = _canonical_entry(project, authored)
        relative = entry_path.relative_to(root).as_posix()
        uri = _project_uri(project.uid, relative)
        entry_key = _portable_path_key(relative)
        if entry_key in portable:
            raise ProjectError("HOCUS462", "Entries and modules must be portably path-unique.")
        portable[entry_key] = uri
        source = _read_source(entry_path, limits, cancelled)
        source_evidence[entry_path] = source
        aggregate += len(source)
        if aggregate > limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Derived source closure exceeds aggregateSourceBytes.")
        syntax = _parse(source, uri, graph=True)
        imports: list[ResolvedImport] = []
        roots: list[str] = []
        for declaration in syntax.imports:
            target = select(entry_path, declaration.specifier)
            decisions.append((entry_path, declaration.specifier, target))
            target_uri = visit(target, 1)
            imports.append(ResolvedImport(
                declaration.specifier, declaration.imported_name, declaration.local_name,
                target_uri, declaration.span,
            ))
            roots.append(target_uri)
        closure: set[str] = set()
        pending = list(roots)
        while pending:
            current = pending.pop()
            if current not in closure:
                closure.add(current)
                pending.extend(scanned[current].dependencies)
        entries.append(_ScannedEntry(entry_path, relative, uri, source, tuple(imports), closure))

    records_by_uri: dict[str, ModuleLockRecord] = {}
    for uri in _dependency_order(scanned):
        item = scanned[uri]
        interface = _module_interface(item.syntax, limits, uri)
        source_digest = module_source_digest(item.source)
        interface_digest = module_interface_digest(interface)
        transitive = module_transitive_digest(
            uri=uri, source_digest=source_digest, interface_digest=interface_digest,
            dependencies=((child, records_by_uri[child].transitive_digest) for child in item.dependencies),
        )
        records_by_uri[uri] = ModuleLockRecord(
            uri, project.uid, None, None, None, "0.2", item.relative,
            source_digest, interface_digest, transitive, item.dependencies, None,
        )
    records = tuple(records_by_uri[uri] for uri in sorted(records_by_uri))
    envelopes = tuple(
        ModuleSourceEnvelope(item.uri, item.source, item.imports)
        for item in sorted(scanned.values(), key=lambda value: value.uri)
    )

    def recheck():
        _cancel(cancelled)
        refreshed = ProjectContext.load(project.root, validate_lock=False)
        if (
            refreshed.manifest_digest != project.manifest_digest
            or refreshed.module_directory_paths != project.module_directory_paths
            or refreshed.module_directories != project.module_directories
        ):
            raise ProjectError("HOCUS453", "Project resolver policy changed before publication.")
        for path, expected in source_evidence.items():
            _reject_reparse_components(path, root)
            _require_exact_windows_casing(path, root)
            if _canonical_file(path, root, "HocusScript source recheck") != path:
                raise ProjectError("HOCUS453", "HocusScript source identity changed before publication.")
            if _read_source(path, limits, cancelled) != expected:
                raise ProjectError("HOCUS453", "HocusScript source changed before publication.")
        for entry in entries:
            if _canonical_entry(refreshed, entry.relative) != entry.path:
                raise ProjectError("HOCUS453", "Entry source resolution changed before publication.")
        for importer, specifier, expected in decisions:
            if select(importer, specifier) != expected:
                raise ProjectError("HOCUS453", "Import resolution changed before publication.")

    return records, entries, envelopes, recheck


def _bounded_entries(values, maximum, cancelled) -> tuple[str, ...]:
    output: list[str] = []
    if isinstance(values, (str, bytes, bytearray)):
        raise ProjectError("HOCUS460", "entry_source_paths must be an iterable of paths, not text.")
    try:
        for value in islice(iter(values), maximum + 1):
            _cancel(cancelled)
            raw = fspath(value)
            if not isinstance(raw, str):
                raise TypeError
            path = Path(raw)
            if not isinstance(value, str):
                if path.is_absolute() or path.drive:
                    raise ValueError
                raw = path.as_posix()
            output.append(raw)
    except ModuleResolutionError:
        raise
    except Exception as exc:
        raise ProjectError("HOCUS460", "entry_source_paths must contain portable relative paths.") from exc
    portable = [_portable_path_key(item) for item in output]
    if not output or len(output) > maximum or len(set(portable)) != len(portable):
        raise ProjectError("HOCUS460", "entry_source_paths must be a nonempty bounded unique iterable.")
    return tuple(sorted(output))


def _canonical_entry(project: ProjectContext, authored: str) -> Path:
    from .project import _validate_relative_artifact_path
    _validate_relative_artifact_path(authored, "entry_source_path", code="HOCUS460")
    if not authored.endswith(".hocus"):
        raise ProjectError("HOCUS460", "Entry sources must use .hocus.")
    root = project.root.resolve(strict=True)
    _reject_reparse_components(root / authored, root)
    _require_exact_windows_casing(root / authored, root)
    path = _canonical_file(root / authored, root, "entry source")
    if path.relative_to(root).as_posix() != authored:
        raise ProjectError("HOCUS460", "Entry source path must use its canonical project spelling.")
    if not any(_is_contained(path, directory.resolve(strict=True)) for directory in project.source_directories):
        raise ProjectError("HOCUS460", "Entry source is outside configured source directories.")
    return path


def _dependency_order(scanned: dict[str, _ScannedModule]) -> tuple[str, ...]:
    remaining = {uri: len(item.dependencies) for uri, item in scanned.items()}
    parents = {uri: [] for uri in scanned}
    for uri, item in scanned.items():
        for child in item.dependencies:
            parents[child].append(uri)
    ready = sorted(uri for uri, count in remaining.items() if count == 0)
    output: list[str] = []
    while ready:
        uri = ready.pop(0)
        output.append(uri)
        for parent in sorted(parents[uri]):
            remaining[parent] -= 1
            if remaining[parent] == 0:
                ready.append(parent)
        ready.sort()
    if len(output) != len(scanned):
        raise ModuleResolutionError("HOCUS463", "Derived module imports contain a cycle.")
    return tuple(output)


def _resolver_policy(project: ProjectContext) -> dict:
    return {
        "schemaVersion": 1, "kind": "native_project_v1",
        "projectMode": "same_project_only",
        "relativeResolution": "importer_relative_project_contained",
        "moduleDirectories": list(project.module_directory_paths),
        "bareResolution": "ordered_first_occupied_fail_closed",
        "externalAliases": False, "casePolicy": "portable", "linkPolicy": "reject_reparse",
    }
