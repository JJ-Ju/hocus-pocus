"""Read-only mixed project/external HocusScript module lock planning."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import quote

from .external_roots import (
    _ValidatedExternalRoot,
    _native_identity,
    _recheck as _recheck_external_roots,
    _reject_reparse_chain,
    _require_exact_native_casing,
    _validate_external_module_roots,
)
from .expander import ExpansionLimits, ResolvedModuleUnit, expand_module_graph
from .lock_update import _bounded_entries, _canonical_entry
from .lock_update_result import ModuleLockUpdateEntry
from .module_lock_plan_result import ModuleLockPlanResult, _build_module_lock_plan_result
from .module_paths import is_literal_import_specifier
from .project import (
    MAX_LOCK_BYTES_V3,
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    _is_contained,
    _portable_path_key,
    _validate_module_locks,
)
from .resolved_modules import (
    ModuleResolutionError,
    ResolvedImport,
    ResolvedModuleLimits,
    _module_interface,
    _validate_limits,
    module_interface_digest,
    module_source_digest,
    module_transitive_digest,
)
from .resolver import (
    _cancel,
    _canonical_file,
    _parse,
    _project_module_resolver_policy,
    _project_uri,
    _read_source,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _select_project_module_target,
)


@dataclass(frozen=True, slots=True)
class _Target:
    uri: str
    path: Path
    relative: str
    owner_kind: str
    owner_uid: str
    alias: str | None
    root: Path


@dataclass(slots=True)
class _ScannedModule:
    target: _Target
    source: bytes
    syntax: object
    imports: tuple[ResolvedImport, ...]
    dependencies: tuple[str, ...]
    identity: tuple[int, int, int]


@dataclass(slots=True)
class _ScannedEntry:
    path: Path
    relative: str
    uri: str
    source: bytes
    syntax: object
    imports: tuple[ResolvedImport, ...]
    dependencies: tuple[str, ...]
    identity: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _Decision:
    importer: _Target | None
    importer_path: Path
    specifier: str
    selected: _Target


@dataclass(frozen=True, slots=True)
class _MixedModuleLockDerivation:
    project_uid: str
    manifest_digest: str
    current_lock_digest: str
    catalog_path: str
    catalog_content_digest: str
    catalog_fingerprint: str
    external_roots_inspection_digest: str
    resolver_policy_digest: str
    entries: tuple[ModuleLockUpdateEntry, ...]
    current_modules: tuple[ModuleLockRecord, ...]
    modules: tuple[ModuleLockRecord, ...]
    recheck: Callable[[], None]

    def plan_result(self) -> ModuleLockPlanResult:
        return _build_module_lock_plan_result(
            project_uid=self.project_uid,
            manifest_digest=self.manifest_digest,
            current_lock_digest=self.current_lock_digest,
            catalog_path=self.catalog_path,
            catalog_content_digest=self.catalog_content_digest,
            catalog_fingerprint=self.catalog_fingerprint,
            external_roots_inspection_digest=self.external_roots_inspection_digest,
            resolver_policy_digest=self.resolver_policy_digest,
            entries=self.entries,
            current_modules=self.current_modules,
            modules=self.modules,
        )


def plan_project_module_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleLockPlanResult:
    """Derive a prospective mixed-root lock without acquiring a lease or writing."""

    return _derive_mixed_module_lock(
        project_directory,
        entry_source_paths,
        module_roots,
        limits=limits,
        cancelled=cancelled,
    ).plan_result()


def _derive_mixed_module_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> _MixedModuleLockDerivation:
    """Retain one exact mixed-root derivation and its final recheck closure."""

    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    authored_entries = _bounded_entries(
        entry_source_paths, selected_limits.module_files, cancelled,
    )
    roots = _validate_external_module_roots(
        project_directory, module_roots, cancelled=cancelled,
    )
    if any(not item.manifest_was_pre_pinned for item in roots.roots):
        raise ProjectError(
            "HOCUS459",
            "Mixed-root lock planning requires every external module manifest to be pre-pinned.",
        )
    _cancel(cancelled)
    context = ProjectContext.load(project_directory, validate_lock=True)
    _require_same_inspection(context, roots)
    assert context.uid is not None
    assert context.lock_digest is not None
    assert context.catalog_relative_path is not None
    assert context.catalog_content_digest is not None
    assert context.catalog_fingerprint is not None
    root = context.root.resolve(strict=True)
    for authored_root in context.module_directory_paths:
        _reject_reparse_components(root / authored_root, root)
        _require_exact_windows_casing(root / authored_root, root)

    by_alias = {item.alias: item for item in roots.roots}
    scanned: dict[str, _ScannedModule] = {}
    states: dict[str, str] = {}
    decisions: list[_Decision] = []
    aggregate = 0
    portable: set[tuple[str, str]] = set()

    def select(importer: _Target | None, importer_path: Path, specifier: str) -> _Target:
        if not is_literal_import_specifier(specifier):
            raise ProjectError("HOCUS460", "Mixed-root imports must be portable literal .hocus paths.")
        if specifier.startswith("@"):
            alias, separator, tail = specifier[1:].partition("/")
            external = by_alias.get(alias)
            if not separator or external is None:
                raise ProjectError("HOCUS460", "External import alias is not explicitly approved.")
            roots.root_for_alias(alias, require_manifest_pin=True)
            if (
                importer is not None
                and importer.owner_kind == "library"
                and importer.alias == alias
            ):
                raise ProjectError(
                    "HOCUS460",
                    "Imports within one external library must use an explicit relative path.",
                )
            if tail not in external.pin.entry_modules:
                raise ProjectError("HOCUS462", "External alias imports may enter only manifest entry modules.")
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
                _project_uri(context.uid or "", relative), selected, relative,
                "project", context.uid or "", None, root,
            )
        decisions.append(_Decision(importer, importer_path, specifier, target))
        return target

    def visit(target: _Target, depth: int) -> str:
        nonlocal aggregate
        _cancel(cancelled)
        if depth > selected_limits.import_depth:
            raise ModuleResolutionError("HOCUS464", "Mixed module closure exceeds importDepth.")
        state = states.get(target.uri)
        if state == "visiting":
            raise ModuleResolutionError("HOCUS463", "Mixed module imports contain a cycle.")
        if state == "done":
            return target.uri
        if len(states) >= selected_limits.module_files:
            raise ModuleResolutionError("HOCUS464", "Mixed module closure exceeds moduleFiles.")
        key = (f"{target.owner_kind}:{target.owner_uid}", _portable_path_key(target.relative))
        if key in portable:
            raise ProjectError("HOCUS462", "Mixed module paths alias after portable normalization.")
        portable.add(key)
        states[target.uri] = "visiting"
        source, identity = _read_target(target, selected_limits, cancelled)
        aggregate += len(source)
        if aggregate > selected_limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Mixed source closure exceeds aggregateSourceBytes.")
        syntax = _parse(source, target.uri, graph=False)
        imports: list[ResolvedImport] = []
        dependencies: list[str] = []
        local_names: set[str] = set()
        specifiers: set[str] = set()
        targets: set[str] = set()
        for declaration in syntax.imports:
            _cancel(cancelled)
            if declaration.local_name in local_names or declaration.specifier in specifiers:
                raise ProjectError("HOCUS462", "Module import names and specifiers must be unique.")
            selected = select(target, target.path, declaration.specifier)
            if selected.uri in targets:
                raise ProjectError("HOCUS462", "Module imports cannot target one module more than once.")
            visit(selected, depth + 1)
            imports.append(ResolvedImport(
                declaration.specifier, declaration.imported_name,
                declaration.local_name, selected.uri, declaration.span,
            ))
            dependencies.append(selected.uri)
            local_names.add(declaration.local_name)
            specifiers.add(declaration.specifier)
            targets.add(selected.uri)
        scanned[target.uri] = _ScannedModule(
            target, source, syntax, tuple(imports), tuple(sorted(dependencies)), identity,
        )
        states[target.uri] = "done"
        return target.uri

    entries: list[_ScannedEntry] = []
    for authored in authored_entries:
        _cancel(cancelled)
        entry_path = _canonical_entry(context, authored)
        relative = entry_path.relative_to(root).as_posix()
        entry_key = (f"project:{context.uid}", _portable_path_key(relative))
        if entry_key in portable:
            raise ProjectError("HOCUS462", "Entries and modules must be portably path-unique.")
        portable.add(entry_key)
        source = _read_source(entry_path, selected_limits, cancelled)
        identity = _native_identity(entry_path, "entry source")
        aggregate += len(source)
        if aggregate > selected_limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Mixed source closure exceeds aggregateSourceBytes.")
        uri = _project_uri(context.uid, relative)
        syntax = _parse(source, uri, graph=True)
        imports: list[ResolvedImport] = []
        dependencies: list[str] = []
        names: set[str] = set()
        specifiers: set[str] = set()
        targets: set[str] = set()
        for declaration in syntax.imports:
            _cancel(cancelled)
            if declaration.local_name in names or declaration.specifier in specifiers:
                raise ProjectError("HOCUS462", "Entry import names and specifiers must be unique.")
            selected = select(None, entry_path, declaration.specifier)
            if selected.uri in targets:
                raise ProjectError("HOCUS462", "Entry imports cannot target one module more than once.")
            visit(selected, 1)
            imports.append(ResolvedImport(
                declaration.specifier, declaration.imported_name,
                declaration.local_name, selected.uri, declaration.span,
            ))
            dependencies.append(selected.uri)
            names.add(declaration.local_name)
            specifiers.add(declaration.specifier)
            targets.add(selected.uri)
        entries.append(_ScannedEntry(
            entry_path, relative, uri, source, syntax, tuple(imports),
            tuple(sorted(dependencies)), identity,
        ))

    _validate_imported_names(entries, scanned)
    records = _derive_records(context, roots, scanned, selected_limits, cancelled)
    strict_records = _validate_module_locks(
        [item.to_dict() for item in records],
        project_uid=context.uid,
        external_aliases=context.external_aliases,
    )
    if strict_records != records:
        raise ProjectError("HOCUS459", "Mixed-root plan records are not canonical.")
    _validate_entry_expansions(
        entries, scanned, records, selected_limits, cancelled,
    )
    def recheck() -> None:
        _recheck_plan_inputs(
            context,
            roots,
            entries,
            scanned,
            decisions,
            select,
            selected_limits,
            cancelled,
        )

    recheck()
    policy = _mixed_resolver_policy(context, roots)
    policy_digest = module_interface_digest(policy)
    derivation = _MixedModuleLockDerivation(
        context.uid,
        context.manifest_digest or "",
        context.lock_digest,
        context.catalog_relative_path,
        context.catalog_content_digest,
        context.catalog_fingerprint,
        roots.inspection.inspection_digest,
        policy_digest,
        tuple(
            ModuleLockUpdateEntry(item.uri, module_source_digest(item.source))
            for item in entries
        ),
        context.locked_modules,
        records,
        recheck,
    )
    result = derivation.plan_result()
    # Match the writer's bounded pretty-JSON lock limit without publishing it.
    import json
    from .module_lock_plan_result import _prospective_lock_payload
    encoded = (json.dumps(
        _prospective_lock_payload(result), ensure_ascii=False,
        indent=2, sort_keys=True, allow_nan=False,
    ) + "\n").encode("utf-8")
    if len(encoded) > MAX_LOCK_BYTES_V3:
        raise ProjectError("HOCUS410", "Prospective project lock exceeds the lock byte limit.")
    return derivation


def _external_target(root: _ValidatedExternalRoot, relative: str) -> _Target:
    candidate = root.root / relative
    _reject_reparse_chain(candidate)
    _require_exact_native_casing(candidate)
    path = _canonical_file(candidate, root.root, "external module")
    canonical = path.relative_to(root.root).as_posix()
    if canonical != relative:
        raise ProjectError("HOCUS460", "External module path is not canonical.")
    return _Target(
        f"hocus-module://{root.pin.library_uid}/{quote(relative, safe='/-._~')}",
        path, relative, "library", root.pin.library_uid, root.alias, root.root,
    )


def _relative_external_path(root: Path, candidate: Path) -> str:
    _reject_reparse_chain(candidate)
    _require_exact_native_casing(candidate)
    path = _canonical_file(candidate, root, "relative external module import")
    if not _is_contained(path, root):
        raise ProjectError("HOCUS460", "External relative import escaped its library root.")
    return path.relative_to(root).as_posix()


def _read_target(target, limits, cancelled):
    if target.owner_kind == "library":
        _reject_reparse_chain(target.path)
        _require_exact_native_casing(target.path)
    else:
        _reject_reparse_components(target.path, target.root)
        _require_exact_windows_casing(target.path, target.root)
    identity_before = _native_identity(target.path, "module source")
    source = _read_source(target.path, limits, cancelled)
    identity_after = _native_identity(target.path, "module source")
    if identity_before != identity_after:
        raise ProjectError("HOCUS428", "Module source identity changed while it was read.")
    return source, identity_after


def _validate_imported_names(entries, scanned):
    for owner in [*entries, *scanned.values()]:
        for item in owner.imports:
            target = scanned.get(item.target_uri)
            if target is None or target.syntax.module is None or item.imported_name != target.syntax.module.name:
                raise ProjectError("HOCUS462", "Imported name conflicts with the target module declaration.")


def _derive_records(context, roots, scanned, limits, cancelled):
    records: dict[str, ModuleLockRecord] = {}
    for uri in _dependency_order(scanned):
        _cancel(cancelled)
        item = scanned[uri]
        interface = _module_interface(item.syntax, limits, uri)
        source_digest = module_source_digest(item.source)
        interface_digest = module_interface_digest(interface)
        transitive = module_transitive_digest(
            uri=uri, source_digest=source_digest, interface_digest=interface_digest,
            dependencies=((child, records[child].transitive_digest) for child in item.dependencies),
        )
        if item.target.owner_kind == "project":
            record = ModuleLockRecord(
                uri, context.uid, None, None, None, "0.2", item.target.relative,
                source_digest, interface_digest, transitive, item.dependencies, None,
            )
        else:
            approved = next(root for root in roots.roots if root.alias == item.target.alias)
            record = ModuleLockRecord(
                uri, None, approved.pin.library_uid, approved.pin.library_version,
                approved.pin.module_manifest_digest, "0.2", item.target.relative,
                source_digest, interface_digest, transitive, item.dependencies, approved.alias,
            )
        records[uri] = record
    return tuple(records[uri] for uri in sorted(records))


def _validate_entry_expansions(entries, scanned, records, limits, cancelled):
    records_by_uri = {item.module_uri: item for item in records}
    units = {
        uri: ResolvedModuleUnit(
            uri,
            records_by_uri[uri].content_digest,
            item.syntax,
            {resolved.local_name: resolved for resolved in item.imports},
        )
        for uri, item in scanned.items()
    }
    expansion_limits = ExpansionLimits.from_resolved(limits)
    for entry in entries:
        _cancel(cancelled)
        closure = _entry_closure(entry.dependencies, scanned, cancelled)
        expand_module_graph(
            entry_source=entry.source,
            entry_uri=entry.uri,
            entry_imports={item.local_name: item for item in entry.imports},
            modules={uri: units[uri] for uri in sorted(closure)},
            limits=expansion_limits,
            cancellation=cancelled,
        )


def _entry_closure(roots, scanned, cancelled):
    closure: set[str] = set()
    pending = list(reversed(sorted(roots)))
    while pending:
        _cancel(cancelled)
        uri = pending.pop()
        if uri in closure:
            continue
        item = scanned.get(uri)
        if item is None:
            raise ProjectError("HOCUS462", "Entry dependency is missing from the planned closure.")
        closure.add(uri)
        pending.extend(reversed(item.dependencies))
    return closure


def _dependency_order(scanned):
    remaining = {uri: len(item.dependencies) for uri, item in scanned.items()}
    parents = {uri: [] for uri in scanned}
    for uri, item in scanned.items():
        for child in item.dependencies:
            if child not in scanned:
                raise ProjectError("HOCUS462", "Planned dependency is missing from the closure.")
            parents[child].append(uri)
    ready = sorted(uri for uri, count in remaining.items() if count == 0)
    output = []
    while ready:
        uri = ready.pop(0)
        output.append(uri)
        for parent in sorted(parents[uri]):
            remaining[parent] -= 1
            if remaining[parent] == 0:
                ready.append(parent)
        ready.sort()
    if len(output) != len(scanned):
        raise ModuleResolutionError("HOCUS463", "Mixed module dependency graph contains a cycle.")
    return tuple(output)


def _recheck_plan_inputs(context, roots, entries, scanned, decisions, select, limits, cancelled):
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
        raise ProjectError(
            "HOCUS428",
            "Project, lock, catalog, or resolver policy changed during mixed-root derivation.",
        )
    _recheck_external_roots(context, roots, cancelled)
    for entry in entries:
        _cancel(cancelled)
        if _canonical_entry(refreshed, entry.relative) != entry.path:
            raise ProjectError("HOCUS428", "Entry source identity changed during mixed-root derivation.")
        if _native_identity(entry.path, "entry source") != entry.identity:
            raise ProjectError("HOCUS428", "Entry source object changed during mixed-root derivation.")
        if _read_source(entry.path, limits, cancelled) != entry.source:
            raise ProjectError("HOCUS428", "Entry source bytes changed during mixed-root derivation.")
    for item in scanned.values():
        _cancel(cancelled)
        current, identity = _read_target(item.target, limits, cancelled)
        if identity != item.identity or current != item.source:
            raise ProjectError("HOCUS428", "Module source changed during mixed-root derivation.")
    initial_count = len(decisions)
    for decision in tuple(decisions):
        _cancel(cancelled)
        if select(decision.importer, decision.importer_path, decision.specifier) != decision.selected:
            raise ProjectError("HOCUS428", "Import winner changed during mixed-root derivation.")
    del decisions[initial_count:]


def _require_same_inspection(context, roots):
    inspection = roots.inspection
    if (
        context.uid != inspection.project_uid
        or context.manifest_digest != inspection.project_manifest_digest
        or context.lock_digest != inspection.project_lock_digest
        or context.catalog_content_digest != inspection.catalog_content_digest
        or context.catalog_fingerprint != inspection.catalog_fingerprint
    ):
        raise ProjectError("HOCUS459", "G1 inspection and project snapshot are inconsistent.")


def _mixed_resolver_policy(context, roots):
    return {
        "schemaVersion": 1,
        "kind": "native_mixed_roots_v1",
        "projectMode": "project_and_explicit_external_roots",
        "projectPolicy": _project_module_resolver_policy(context),
        "externalLibraries": [item.pin.to_dict() for item in roots.roots],
        "projectExternalResolution": "alias_entry_modules_only",
        "externalRelativeResolution": "same_library_only",
        "externalCrossLibraryResolution": "alias_entry_modules_only",
        "externalBareResolution": "disabled",
        "externalToProject": False,
        "casePolicy": "portable",
        "linkPolicy": "reject_reparse",
    }
