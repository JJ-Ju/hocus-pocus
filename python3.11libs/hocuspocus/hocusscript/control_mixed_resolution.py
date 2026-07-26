"""Explicit-root native resolution for mixed HocusScript 0.3 programs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .catalog import CatalogSnapshot
from .contracts import (
    CarrierContractError,
    decode_control_resolved_module_set_envelope,
)
from .control_catalog import validate_control_catalog_program
from .control_expander import expand_control_graph
from .control_resolver import (
    ControlResolverLimits,
    ResolvedControlProgram,
    _handoff_digest,
    _parse_control_source,
    _resolver_policy,
    _select_limits,
)
from .control_semantic import ControlExpansionLimits
from .expander import ResolvedModuleUnit
from .external_roots import (
    _ValidatedExternalModuleRoots,
    _recheck as _recheck_external_roots,
    _validate_control_external_module_roots,
)
from .lock_update import _canonical_entry, _dependency_order
from .module_lock_plan import (
    _Target,
    _external_target,
    _read_target,
    _relative_external_path,
    _require_same_inspection,
)
from .module_paths import is_literal_import_specifier
from .project import (
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    _is_contained,
    _portable_path_key,
)
from .resolved_modules import (
    ModuleDependency,
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
    _reject_reparse_components,
    _require_exact_windows_casing,
    _validate_project_directory,
    _validated_entry_path_text,
)
from .syntax import SyntaxSource


@dataclass(slots=True)
class _ScannedMixedControlModule:
    target: _Target
    source: bytes
    syntax: SyntaxSource
    imports: tuple[ResolvedImport, ...]
    dependencies: tuple[str, ...]
    identity: tuple[int, int, int]

    def resolved_unit(self) -> ResolvedModuleUnit:
        return ResolvedModuleUnit(
            self.target.uri,
            module_source_digest(self.source),
            self.syntax,
            MappingProxyType({
                item.local_name: item
                for item in self.imports
            }),
        )


@dataclass(slots=True)
class _ScannedMixedControlEntry:
    target: _Target
    source: bytes
    syntax: SyntaxSource
    imports: tuple[ResolvedImport, ...]
    roots: tuple[str, ...]
    identity: tuple[int, int, int]


@dataclass(slots=True)
class _MixedControlSession:
    context: ProjectContext
    roots: _ValidatedExternalModuleRoots
    entry_paths: tuple[str, ...]
    limits: ControlResolverLimits
    control_limits: ControlExpansionLimits
    cancelled: Callable[[], bool] | None
    root: Path
    by_alias: dict[str, Any]
    lock_by_uri: dict[str, ModuleLockRecord]
    verify_lock: bool
    scanned: dict[str, _ScannedMixedControlModule] = field(default_factory=dict)
    entries: list[_ScannedMixedControlEntry] = field(default_factory=list)
    states: dict[str, str] = field(default_factory=dict)
    decisions: list[tuple[_Target | None, Path, str, _Target]] = field(
        default_factory=list,
    )
    portable: set[tuple[str, str]] = field(default_factory=set)
    aggregate_source_bytes: int = 0

    @classmethod
    def create(
        cls,
        project_directory: str | PathLike[str],
        entry_paths: tuple[str, ...],
        module_roots: Mapping[str, str | PathLike[str]],
        limits: ControlResolverLimits,
        control_limits: ControlExpansionLimits,
        cancelled: Callable[[], bool] | None,
        *,
        verify_lock: bool,
    ) -> "_MixedControlSession":
        project_value = _validate_project_directory(project_directory)
        roots = _validate_control_external_module_roots(
            project_value,
            module_roots,
            cancelled=cancelled,
        )
        if any(not item.manifest_was_pre_pinned for item in roots.roots):
            raise ProjectError(
                "HOCUS459",
                "Mixed control use requires every module-manifest-v2 digest to be pinned.",
            )
        context = ProjectContext.load(project_value, validate_lock=True)
        _require_mixed_control_project(context)
        _require_same_inspection(context, roots)
        root = context.root.resolve(strict=True)
        _validate_project_roots(context, root)
        return cls(
            context,
            roots,
            entry_paths,
            limits,
            control_limits,
            cancelled,
            root,
            {item.alias: item for item in roots.roots},
            {item.module_uri: item for item in context.locked_modules},
            verify_lock,
        )

    def scan(self) -> None:
        for authored in self.entry_paths:
            _cancel(self.cancelled)
            path = _canonical_entry(self.context, authored)
            relative = path.relative_to(self.root).as_posix()
            target = _Target(
                _project_uri(self.context.uid or "", relative),
                path,
                relative,
                "project",
                self.context.uid or "",
                None,
                self.root,
            )
            self._claim(target)
            source, identity = self._read(target)
            syntax = _parse_control_source(source, target.uri, graph=True)
            imports, roots = self._scan_imports(None, target.path, syntax, 0)
            self.entries.append(
                _ScannedMixedControlEntry(
                    target,
                    source,
                    syntax,
                    imports,
                    roots,
                    identity,
                )
            )
        self._validate_imported_names()

    def select(
        self,
        importer: _Target | None,
        importer_path: Path,
        specifier: str,
    ) -> _Target:
        target = self._select_target(importer, importer_path, specifier)
        if self.verify_lock:
            _require_locked_target(target, self.lock_by_uri, self.roots)
        self.decisions.append((importer, importer_path, specifier, target))
        return target

    def visit(self, target: _Target, depth: int) -> str:
        _cancel(self.cancelled)
        state = self.states.get(target.uri)
        if state == "visiting":
            raise ModuleResolutionError(
                "HOCUS463",
                "Mixed control module imports contain a cycle.",
            )
        if state == "done":
            return target.uri
        if (
            len(self.states) >= self.limits.module_files
            or depth > self.limits.import_depth
        ):
            raise ModuleResolutionError(
                "HOCUS464",
                "Mixed control closure exceeds moduleFiles or importDepth.",
            )
        self._claim(target)
        self.states[target.uri] = "visiting"
        source, identity = self._read(target)
        syntax = _parse_control_source(source, target.uri, graph=False)
        imports, dependencies = self._scan_imports(
            target,
            target.path,
            syntax,
            depth,
        )
        self.scanned[target.uri] = _ScannedMixedControlModule(
            target,
            source,
            syntax,
            imports,
            dependencies,
            identity,
        )
        self.states[target.uri] = "done"
        return target.uri

    def derive_records(self) -> tuple[ModuleLockRecord, ...]:
        records: dict[str, ModuleLockRecord] = {}
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
                    (child, records[child].transitive_digest)
                    for child in item.dependencies
                ),
            )
            records[uri] = self._record(
                item,
                source_digest,
                interface_digest,
                transitive_digest,
            )
        ordered = tuple(records[uri] for uri in sorted(records))
        if self.verify_lock:
            self._verify_records(ordered)
        return ordered

    def validate_entries(self, catalog: CatalogSnapshot) -> None:
        for entry in self.entries:
            closure = self._closure(entry.roots)
            modules = MappingProxyType({
                uri: self.scanned[uri].resolved_unit()
                for uri in sorted(closure)
            })
            imports = MappingProxyType({
                item.local_name: item
                for item in entry.imports
            })
            admission = validate_control_catalog_program(
                entry.syntax,
                imports,
                modules,
                catalog,
                expected_catalog_fingerprint=catalog.fingerprint,
                limits=self.control_limits,
                cancellation=self.cancelled,
            )
            if not admission.valid:
                primary = admission.diagnostics[0]
                raise ProjectError(
                    primary.code,
                    primary.message,
                    details={
                        "entrySourceUri": entry.target.uri,
                        "diagnostic": primary.to_dict(),
                        "diagnostics": [
                            item.to_dict()
                            for item in admission.diagnostics
                        ],
                    },
                )
            expand_control_graph(
                entry.source,
                entry.target.uri,
                imports,
                modules,
                limits=self.control_limits,
                cancellation=self.cancelled,
            )

    def resolved_program(self) -> ResolvedControlProgram:
        if len(self.entries) != 1:
            raise RuntimeError("A resolved control program requires exactly one entry.")
        entry = self.entries[0]
        records = self.derive_records()
        dependencies = self._dependencies(records)
        resolved_json, resolved_digest = self._resolved_set(
            entry.target.uri,
            dependencies,
        )
        modules = MappingProxyType({
            uri: item.resolved_unit()
            for uri, item in sorted(self.scanned.items())
        })
        imports = MappingProxyType({
            item.local_name: item
            for item in entry.imports
        })
        handoff = _handoff_digest(
            entry.target.uri,
            module_source_digest(entry.source),
            entry.imports,
            resolved_digest,
            self.context,
        )
        self.recheck()
        return ResolvedControlProgram(
            self.context.uid or "",
            self.context.manifest_digest or "",
            self.context.lock_digest or "",
            self.context.catalog_content_digest or "",
            self.context.catalog_fingerprint or "",
            _digest_json(_control_mixed_resolver_policy(self.context, self.roots)),
            entry.target.uri,
            entry.source,
            module_source_digest(entry.source),
            entry.syntax,
            imports,
            modules,
            self.limits,
            self.control_limits,
            resolved_json,
            resolved_digest,
            handoff,
            self.context,
            self.recheck,
        )

    def recheck(self) -> None:
        _cancel(self.cancelled)
        cancelled = self.cancelled
        self.cancelled = None
        try:
            self._recheck_without_cancellation()
        finally:
            self.cancelled = cancelled

    def _recheck_without_cancellation(self) -> None:
        refreshed = ProjectContext.load(self.root, validate_lock=True)
        if _project_pins(refreshed) != _project_pins(self.context):
            raise ProjectError(
                "HOCUS428",
                "Mixed control project, lock, catalog, or policy changed.",
            )
        _require_mixed_control_project(refreshed)
        _validate_project_roots(refreshed, self.root)
        _recheck_external_roots(self.context, self.roots, self.cancelled)
        for entry in self.entries:
            self._recheck_target(
                entry.target,
                entry.source,
                entry.identity,
                require_locked=False,
            )
            if _canonical_entry(refreshed, entry.target.relative) != entry.target.path:
                raise ProjectError(
                    "HOCUS428",
                    "Mixed control entry resolution changed.",
                )
        for item in self.scanned.values():
            self._recheck_target(
                item.target,
                item.source,
                item.identity,
                require_locked=True,
            )
        initial_count = len(self.decisions)
        for importer, path, specifier, expected in tuple(self.decisions):
            if self._select_target(importer, path, specifier) != expected:
                raise ProjectError(
                    "HOCUS428",
                    "Mixed control import winner changed.",
                )
        del self.decisions[initial_count:]

    def _select_target(
        self,
        importer: _Target | None,
        importer_path: Path,
        specifier: str,
    ) -> _Target:
        if not is_literal_import_specifier(specifier):
            raise ProjectError(
                "HOCUS460",
                "Mixed control imports must be portable literal .hocus paths.",
            )
        if specifier.startswith("@"):
            return self._select_external_entry(importer, specifier)
        if importer is not None and importer.owner_kind == "library":
            return self._select_external_relative(importer, importer_path, specifier)
        return self._select_project(importer_path, specifier)

    def _select_external_entry(
        self,
        importer: _Target | None,
        specifier: str,
    ) -> _Target:
        alias, separator, relative = specifier[1:].partition("/")
        root = self.by_alias.get(alias)
        if not separator or root is None:
            raise ProjectError(
                "HOCUS460",
                "External import alias is not explicitly approved.",
            )
        self.roots.root_for_alias(alias, require_manifest_pin=True)
        if (
            importer is not None
            and importer.owner_kind == "library"
            and importer.alias == alias
        ):
            raise ProjectError(
                "HOCUS460",
                "Same-library imports must use an explicit relative path.",
            )
        if relative not in root.pin.entry_modules:
            raise ProjectError(
                "HOCUS462",
                "External alias imports may enter only manifest entry modules.",
            )
        return _external_target(root, relative)

    def _select_external_relative(
        self,
        importer: _Target,
        importer_path: Path,
        specifier: str,
    ) -> _Target:
        if not specifier.startswith(("./", "../")):
            raise ProjectError(
                "HOCUS460",
                "Bare imports and library-to-project edges are disabled in external libraries.",
            )
        root = self.by_alias[importer.alias or ""]
        relative = _relative_external_path(
            root.root,
            importer_path.parent / specifier,
        )
        return _external_target(root, relative)

    def _select_project(self, importer: Path, specifier: str) -> _Target:
        if specifier.startswith(("./", "../")):
            path = self._contained_project_candidate(
                importer.parent / specifier,
                "relative control module import",
            )
        else:
            path = self._select_bare_project(specifier)
        relative = path.relative_to(self.root).as_posix()
        return _Target(
            _project_uri(self.context.uid or "", relative),
            path,
            relative,
            "project",
            self.context.uid or "",
            None,
            self.root,
        )

    def _select_bare_project(self, specifier: str) -> Path:
        for directory in self.context.module_directories:
            _cancel(self.cancelled)
            candidate = directory / specifier
            if not _lexically_occupied(candidate):
                continue
            target = self._contained_project_candidate(
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
            "Bare control module import was not found in module_directories.",
            details={"specifier": specifier},
        )

    def _contained_project_candidate(self, candidate: Path, label: str) -> Path:
        _reject_reparse_components(candidate, self.root)
        _require_exact_windows_casing(candidate, self.root)
        return _canonical_file(candidate, self.root, label)

    def _scan_imports(
        self,
        importer: _Target | None,
        importer_path: Path,
        syntax: SyntaxSource,
        depth: int,
    ) -> tuple[tuple[ResolvedImport, ...], tuple[str, ...]]:
        imports: list[ResolvedImport] = []
        roots: list[str] = []
        local_names: set[str] = set()
        specifiers: set[str] = set()
        targets: set[str] = set()
        for declaration in syntax.imports:
            _cancel(self.cancelled)
            selected = self.select(importer, importer_path, declaration.specifier)
            if (
                declaration.local_name in local_names
                or declaration.specifier in specifiers
                or selected.uri in targets
            ):
                raise ProjectError(
                    "HOCUS462",
                    "Mixed control imports must have unique names, specifiers, and targets.",
                )
            self.visit(selected, depth + 1)
            imports.append(
                ResolvedImport(
                    declaration.specifier,
                    declaration.imported_name,
                    declaration.local_name,
                    selected.uri,
                    declaration.span,
                )
            )
            roots.append(selected.uri)
            local_names.add(declaration.local_name)
            specifiers.add(declaration.specifier)
            targets.add(selected.uri)
        return tuple(imports), tuple(sorted(roots))

    def _read(self, target: _Target) -> tuple[bytes, tuple[int, int, int]]:
        source, identity = _read_target(
            target,
            self.limits.to_legacy_shape(),
            self.cancelled,
        )
        self.aggregate_source_bytes += len(source)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ModuleResolutionError(
                "HOCUS464",
                "Mixed control sources exceed aggregateSourceBytes.",
            )
        return source, identity

    def _claim(self, target: _Target) -> None:
        key = (
            f"{target.owner_kind}:{target.owner_uid}",
            _portable_path_key(target.relative),
        )
        if key in self.portable:
            raise ProjectError(
                "HOCUS462",
                "Mixed control paths alias after portable normalization.",
            )
        self.portable.add(key)

    def _validate_imported_names(self) -> None:
        owners: Iterable[Any] = [*self.entries, *self.scanned.values()]
        for owner in owners:
            for imported in owner.imports:
                target = self.scanned.get(imported.target_uri)
                if (
                    target is None
                    or target.syntax.module is None
                    or target.syntax.module.name != imported.imported_name
                ):
                    raise ProjectError(
                        "HOCUS462",
                        "Imported name conflicts with the target module declaration.",
                    )

    def _record(
        self,
        item: _ScannedMixedControlModule,
        source_digest: str,
        interface_digest: str,
        transitive_digest: str,
    ) -> ModuleLockRecord:
        target = item.target
        if target.owner_kind == "project":
            return ModuleLockRecord(
                target.uri,
                self.context.uid,
                None,
                None,
                None,
                "0.3",
                target.relative,
                source_digest,
                interface_digest,
                transitive_digest,
                item.dependencies,
                None,
            )
        root = self.by_alias[target.alias or ""]
        return ModuleLockRecord(
            target.uri,
            None,
            root.pin.library_uid,
            root.pin.library_version,
            root.pin.module_manifest_digest,
            "0.3",
            target.relative,
            source_digest,
            interface_digest,
            transitive_digest,
            item.dependencies,
            root.alias,
        )

    def _verify_records(self, records: tuple[ModuleLockRecord, ...]) -> None:
        for record in records:
            locked = self.lock_by_uri.get(record.module_uri)
            if locked != record:
                raise ProjectError(
                    "HOCUS461",
                    "Mixed control module differs from its verified v4 lock record.",
                    details={"moduleUri": record.module_uri},
                )

    def _dependencies(
        self,
        records: tuple[ModuleLockRecord, ...],
    ) -> tuple[ModuleDependency, ...]:
        records_by_uri = {item.module_uri: item for item in records}
        output: list[ModuleDependency] = []
        for uri in sorted(self.scanned):
            item = self.scanned[uri]
            record = records_by_uri[uri]
            origin = (
                "project"
                if item.target.owner_kind == "project"
                else "external_library"
            )
            output.append(
                ModuleDependency(
                    uri,
                    item.syntax.module.name,
                    item.target.relative,
                    origin,
                    item.target.owner_uid,
                    record.external_alias,
                    record.library_version,
                    record.module_manifest_digest,
                    record.content_digest,
                    record.interface_digest,
                    record.transitive_digest,
                    record.dependencies,
                    "0.3",
                )
            )
        return tuple(output)

    def _resolved_set(
        self,
        entry_uri: str,
        dependencies: tuple[ModuleDependency, ...],
    ) -> tuple[str, str]:
        policy_digest = _digest_json(
            _control_mixed_resolver_policy(self.context, self.roots)
        )
        payload = {
            "$schema": "hocuspocus://schemas/resolved-module-set/v2",
            "kind": "hocus_resolved_module_set",
            "schemaVersion": 2,
            "languageVersion": "0.3",
            "projectUid": self.context.uid,
            "entrySourceUri": entry_uri,
            "projectManifestDigest": self.context.manifest_digest,
            "projectLockDigest": self.context.lock_digest,
            "resolverPolicyDigest": policy_digest,
            "limits": self.limits.to_dict(),
            "modules": [item.to_dict() for item in dependencies],
        }
        try:
            decoded = decode_control_resolved_module_set_envelope(payload)
        except CarrierContractError as exc:
            raise ModuleResolutionError(
                "HOCUS493",
                "Mixed control resolved set failed its strict v2 contract.",
                details={"validatorCode": exc.code},
            ) from exc
        encoded = _canonical_json(decoded)
        return encoded, _digest_bytes(encoded.encode("utf-8"))

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

    def _recheck_target(
        self,
        target: _Target,
        expected: bytes,
        expected_identity: tuple[int, int, int],
        *,
        require_locked: bool,
    ) -> None:
        current, identity = _read_target(
            target,
            self.limits.to_legacy_shape(),
            None,
        )
        if current != expected or identity != expected_identity:
            raise ProjectError(
                "HOCUS428",
                "Mixed control source changed during the retained authority session.",
            )
        if self.verify_lock and require_locked:
            _require_locked_target(target, self.lock_by_uri, self.roots)


def resolve_project_mixed_control_program(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ResolvedControlProgram:
    """Resolve one verified v4 program through exact per-call external roots."""

    selected_limits, control_limits = _select_limits(limits)
    entry = _validated_entry_path_text(entry_source_path)
    session = _MixedControlSession.create(
        project_directory,
        (entry,),
        module_roots,
        selected_limits,
        control_limits,
        cancelled,
        verify_lock=True,
    )
    session.scan()
    return session.resolved_program()


def _require_locked_target(
    target: _Target,
    lock_by_uri: Mapping[str, ModuleLockRecord],
    roots: _ValidatedExternalModuleRoots,
) -> ModuleLockRecord:
    locked = lock_by_uri.get(target.uri)
    if (
        locked is None
        or locked.source_path != target.relative
        or locked.language_version != "0.3"
    ):
        raise ProjectError(
            "HOCUS462",
            "Mixed control target is absent from the verified v4 lock.",
        )
    if target.owner_kind == "project":
        _require_locked_project_target(target, locked)
    else:
        _require_locked_external_target(target, locked, roots)
    return locked


def _require_locked_project_target(
    target: _Target,
    locked: ModuleLockRecord,
) -> None:
    if (
        locked.project_uid != target.owner_uid
        or locked.external_alias is not None
        or any(
            value is not None
            for value in (
                locked.library_uid,
                locked.library_version,
                locked.module_manifest_digest,
            )
        )
    ):
        raise ProjectError(
            "HOCUS462",
            "Mixed control project module provenance is invalid.",
        )


def _require_locked_external_target(
    target: _Target,
    locked: ModuleLockRecord,
    roots: _ValidatedExternalModuleRoots,
) -> None:
    approved = next(
        (item for item in roots.roots if item.alias == target.alias),
        None,
    )
    if (
        approved is None
        or locked.project_uid is not None
        or locked.external_alias != approved.alias
        or locked.library_uid != approved.pin.library_uid
        or locked.library_version != approved.pin.library_version
        or locked.module_manifest_digest != approved.pin.module_manifest_digest
    ):
        raise ProjectError(
            "HOCUS462",
            "Mixed control external module provenance is invalid.",
        )


def _require_mixed_control_project(context: ProjectContext) -> None:
    required = (
        context.uid,
        context.manifest_digest,
        context.lock_digest,
        context.catalog_content_digest,
        context.catalog_fingerprint,
        context.catalog,
    )
    if (
        context.manifest_version != 4
        or context.language_version != "0.3"
        or any(value is None for value in required)
        or not context.external_aliases
    ):
        raise ProjectError(
            "HOCUS452",
            "Mixed control resolution requires a fully pinned v4 project with aliases.",
        )


def _validate_project_roots(context: ProjectContext, root: Path) -> None:
    if len(context.module_directory_paths) != len(context.module_directories):
        raise ProjectError(
            "HOCUS452",
            "Mixed control project lost module-directory provenance.",
        )
    for authored in context.module_directory_paths:
        _reject_reparse_components(root / authored, root)
        _require_exact_windows_casing(root / authored, root)


def _control_mixed_resolver_policy(
    context: ProjectContext,
    roots: _ValidatedExternalModuleRoots,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": "native_mixed_roots_v1",
        "projectMode": "project_and_explicit_external_roots",
        "projectPolicy": _resolver_policy(context),
        "externalLibraries": [item.pin.to_dict() for item in roots.roots],
        "projectExternalResolution": "alias_entry_modules_only",
        "externalRelativeResolution": "same_library_only",
        "externalCrossLibraryResolution": "alias_entry_modules_only",
        "externalBareResolution": "disabled",
        "externalToProject": False,
        "casePolicy": "portable",
        "linkPolicy": "reject_reparse",
    }


def _project_pins(context: ProjectContext) -> tuple[Any, ...]:
    return (
        context.root,
        context.uid,
        context.manifest_version,
        context.language_version,
        context.manifest_digest,
        context.lock_digest,
        context.catalog_relative_path,
        context.catalog_content_digest,
        context.catalog_fingerprint,
        context.module_directory_paths,
        context.module_directories,
        context.external_aliases,
        context.locked_modules,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _digest_json(value: Any) -> str:
    return _digest_bytes(_canonical_json(value).encode("utf-8"))


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = ["resolve_project_mixed_control_program"]
