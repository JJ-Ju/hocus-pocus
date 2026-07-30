"""Explicit-project native resolver for the HocusScript 0.3 control lane.

This module is deliberately parallel to :mod:`resolver`.  It enables no CLI,
editor, compiler, lock-writer, document, live, or MCP dispatch.  Callers must
select one schema-v4 project and one canonical project-relative entry path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .contracts import (
    CONTROL_RESOLVED_LIMIT_MAXIMA,
    CarrierContractError,
    decode_control_resolved_module_set_envelope,
    decode_value_resolved_module_set_envelope,
)
from .control_semantic import ControlExpansionLimits
from .diagnostics import HocusSourceError
from .expander import ResolvedModuleUnit
from .module_paths import is_literal_import_specifier
from .parser import parse_syntax
from .project import ModuleLockRecord, ProjectContext, ProjectError, _is_contained
from .resolved_modules import (
    ModuleDependency,
    ModuleResolutionError,
    ResolvedImport,
    ResolvedModuleLimits,
    _module_interface,
    module_interface_digest,
    module_source_digest,
    module_transitive_digest,
)
from .syntax import SyntaxSource
from .resolver import (
    _cancel,
    _canonical_file,
    _lexically_occupied,
    _project_uri,
    _read_source,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _validate_project_directory,
    _validated_entry_path_text,
)


@dataclass(frozen=True, slots=True)
class ControlResolverLimits:
    """Exact resolved-module-set v2 limits for one native control program."""

    source_bytes_per_file: int = 1_048_576
    aggregate_source_bytes: int = 8_388_608
    module_files: int = 4_096
    import_depth: int = 64
    instance_depth: int = 64
    instances: int = 4_096
    parameters_per_module: int = 256
    exports_per_module: int = 256
    expanded_nodes: int = 10_000
    aggregate_code_bytes: int = 4_194_304
    source_map_entries: int = 100_000
    diagnostics: int = 500
    per_fold_iterations: int = 4_096
    aggregate_iterations: int = 100_000

    def __post_init__(self) -> None:
        for name, maximum in _LIMIT_MAXIMA_BY_FIELD.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(
                    f"ControlResolverLimits.{name} must be an integer from 1 to {maximum}."
                )

    def to_dict(self) -> dict[str, int]:
        return {
            carrier_name: getattr(self, field_name)
            for field_name, carrier_name in _LIMIT_FIELDS
        }

    def to_legacy_shape(self) -> ResolvedModuleLimits:
        """Adapt the shared interface validator without changing its v1 carrier."""

        return ResolvedModuleLimits(
            source_bytes_per_file=self.source_bytes_per_file,
            aggregate_source_bytes=self.aggregate_source_bytes,
            module_files=self.module_files,
            import_depth=self.import_depth,
            instance_depth=self.instance_depth,
            instances=self.instances,
            parameters_per_module=self.parameters_per_module,
            exports_per_module=self.exports_per_module,
            expanded_nodes=self.expanded_nodes,
            aggregate_code_bytes=self.aggregate_code_bytes,
            source_map_entries=self.source_map_entries,
            diagnostics=self.diagnostics,
        )

    @classmethod
    def from_control_limits(
        cls,
        value: ControlExpansionLimits,
    ) -> "ControlResolverLimits":
        """Merge exact expansion limits with the fixed native source bounds."""

        if not isinstance(value, ControlExpansionLimits):
            raise TypeError("value must be a ControlExpansionLimits")
        return cls(
            import_depth=value.import_depth,
            instance_depth=value.instance_depth,
            instances=value.instances,
            parameters_per_module=value.parameters_per_module,
            exports_per_module=value.exports_per_module,
            expanded_nodes=value.expanded_nodes,
            aggregate_code_bytes=value.aggregate_code_bytes,
            source_map_entries=value.source_map_entries,
            diagnostics=value.diagnostics,
            per_fold_iterations=value.per_fold_iterations,
            aggregate_iterations=value.aggregate_iterations,
        )

    def to_control_limits(self) -> ControlExpansionLimits:
        return ControlExpansionLimits(
            import_depth=self.import_depth,
            instance_depth=self.instance_depth,
            instances=self.instances,
            parameters_per_module=self.parameters_per_module,
            exports_per_module=self.exports_per_module,
            expanded_nodes=self.expanded_nodes,
            aggregate_code_bytes=self.aggregate_code_bytes,
            source_map_entries=self.source_map_entries,
            diagnostics=self.diagnostics,
            per_fold_iterations=self.per_fold_iterations,
            aggregate_iterations=self.aggregate_iterations,
        )


_LIMIT_FIELDS = (
    ("source_bytes_per_file", "sourceBytesPerFile"),
    ("aggregate_source_bytes", "aggregateSourceBytes"),
    ("module_files", "moduleFiles"),
    ("import_depth", "importDepth"),
    ("instance_depth", "instanceDepth"),
    ("instances", "instances"),
    ("parameters_per_module", "parametersPerModule"),
    ("exports_per_module", "exportsPerModule"),
    ("expanded_nodes", "expandedNodes"),
    ("aggregate_code_bytes", "aggregateCodeBytes"),
    ("source_map_entries", "sourceMapEntries"),
    ("diagnostics", "diagnostics"),
    ("per_fold_iterations", "perFoldIterations"),
    ("aggregate_iterations", "aggregateIterations"),
)
_LIMIT_MAXIMA_BY_FIELD = MappingProxyType({
    field_name: CONTROL_RESOLVED_LIMIT_MAXIMA[carrier_name]
    for field_name, carrier_name in _LIMIT_FIELDS
})


@dataclass(frozen=True, slots=True)
class ResolvedControlProgram:
    """Immutable, portable v4 resolver output with retained native rechecks."""

    project_uid: str
    project_manifest_digest: str
    project_lock_digest: str
    catalog_content_digest: str
    catalog_fingerprint: str
    resolver_policy_digest: str
    entry_source_uri: str
    entry_source: bytes
    entry_source_digest: str
    entry_syntax: SyntaxSource
    entry_imports: Mapping[str, ResolvedImport]
    modules: Mapping[str, ResolvedModuleUnit]
    limits: ControlResolverLimits
    control_limits: ControlExpansionLimits
    resolved_module_set_json: str
    resolved_module_set_digest: str
    handoff_digest: str
    _project: ProjectContext = field(repr=False, compare=False)
    _recheck_callback: Callable[[], None] = field(repr=False, compare=False)

    @property
    def resolved_module_set(self) -> dict[str, Any]:
        """Return a detached decoded resolved-module-set v2 value."""

        return json.loads(self.resolved_module_set_json)

    def recheck(self) -> None:
        """Revalidate every retained project, catalog, source, and winner pin."""

        self._recheck_callback()


@dataclass(slots=True)
class _ScannedModule:
    path: Path
    relative_path: str
    lock: ModuleLockRecord
    source: bytes
    syntax: SyntaxSource
    imports: tuple[ResolvedImport, ...]
    dependency: ModuleDependency


@dataclass(slots=True)
class _ControlResolverSession:
    context: ProjectContext
    entry_path_text: str
    limits: ControlResolverLimits
    control_limits: ControlExpansionLimits
    cancelled: Callable[[], bool] | None
    root: Path
    lock_by_uri: dict[str, ModuleLockRecord]
    source_evidence: dict[Path, bytes] = field(default_factory=dict)
    decisions: list[tuple[Path, str, Path]] = field(default_factory=list)
    scanned: dict[str, _ScannedModule] = field(default_factory=dict)
    states: dict[str, str] = field(default_factory=dict)
    portable_paths: set[str] = field(default_factory=set)
    aggregate_source_bytes: int = 0
    entry_path: Path | None = None
    entry_source: bytes | None = None
    entry_syntax: SyntaxSource | None = None

    @classmethod
    def create(
        cls,
        project_directory: str | PathLike[str],
        entry_source_path: str | PathLike[str],
        limits: ControlResolverLimits,
        control_limits: ControlExpansionLimits,
        cancelled: Callable[[], bool] | None,
    ) -> "_ControlResolverSession":
        project_text = _validate_project_directory(project_directory)
        entry_text = _validated_entry_path_text(entry_source_path)
        _cancel(cancelled)
        context = ProjectContext.load(project_text, validate_lock=True)
        _require_control_project(context)
        root = context.root.resolve(strict=True)
        _validate_project_roots(context, root)
        return cls(
            context,
            entry_text,
            limits,
            control_limits,
            cancelled,
            root,
            {record.module_uri: record for record in context.locked_modules},
        )

    def resolve(self) -> ResolvedControlProgram:
        entry_path = self._resolve_entry()
        entry_uri = _project_uri(self.context.uid or "", self.entry_path_text)
        entry_source = self._read(entry_path)
        entry_syntax = _parse_control_source(
            entry_source,
            entry_uri,
            graph=True,
            language_version=self.context.language_version,
        )
        self.entry_path = entry_path
        self.entry_source = entry_source
        self.entry_syntax = entry_syntax
        entry_imports = self._resolve_imports(entry_path, entry_syntax, depth=0)
        ordered = tuple(self.scanned[uri] for uri in sorted(self.scanned))
        module_set_json, module_set_digest = self._resolved_set(entry_uri, ordered)
        modules = MappingProxyType({
            item.dependency.uri: ResolvedModuleUnit(
                item.dependency.uri,
                item.dependency.source_digest,
                item.syntax,
                MappingProxyType({
                    resolved.local_name: resolved for resolved in item.imports
                }),
            )
            for item in ordered
        })
        imports = MappingProxyType({
            item.local_name: item for item in entry_imports
        })
        handoff = _handoff_digest(
            entry_uri,
            module_source_digest(entry_source),
            entry_imports,
            module_set_digest,
            self.context,
        )
        return ResolvedControlProgram(
            self.context.uid or "",
            self.context.manifest_digest or "",
            self.context.lock_digest or "",
            self.context.catalog_content_digest or "",
            self.context.catalog_fingerprint or "",
            _resolver_policy_digest(self.context),
            entry_uri,
            entry_source,
            module_source_digest(entry_source),
            entry_syntax,
            imports,
            modules,
            self.limits,
            self.control_limits,
            module_set_json,
            module_set_digest,
            handoff,
            self.context,
            self.recheck,
        )

    def select_target(self, importer: Path, specifier: str) -> Path:
        if not is_literal_import_specifier(specifier) or specifier.startswith("@"):
            raise ProjectError(
                "HOCUS460",
                "Same-project control resolution requires literal non-alias imports.",
            )
        if specifier.startswith(("./", "../")):
            return self._contained_candidate(
                importer.parent / specifier, "relative module import",
            )
        return self._select_bare_target(specifier)

    def visit(self, lock: ModuleLockRecord, path: Path, depth: int) -> None:
        _cancel(self.cancelled)
        if depth > self.limits.import_depth:
            raise ModuleResolutionError(
                "HOCUS464", "Control module closure exceeds importDepth."
            )
        state = self.states.get(lock.module_uri)
        if state == "visiting":
            raise ModuleResolutionError(
                "HOCUS463", "Control module imports contain a cycle."
            )
        if state == "done":
            return
        if len(self.states) >= self.limits.module_files:
            raise ModuleResolutionError(
                "HOCUS464", "Control module closure exceeds moduleFiles."
            )
        self.states[lock.module_uri] = "visiting"
        relative = path.relative_to(self.root).as_posix()
        _require_local_lock(
            lock,
            self.context.uid or "",
            relative,
            self.context.language_version,
        )
        self._claim_portable_path(relative)
        source = self._read(path)
        syntax = _parse_control_source(
            source,
            lock.module_uri,
            graph=False,
            language_version=self.context.language_version,
        )
        imports, targets = self._scan_module_imports(path, syntax)
        dependency_uris = tuple(sorted({item.target_uri for item in imports}))
        if dependency_uris != lock.dependencies:
            raise ProjectError(
                "HOCUS462",
                "Resolved control imports do not match locked dependencies.",
                details={"moduleUri": lock.module_uri},
            )
        for target_lock, target_path in targets:
            self.visit(target_lock, target_path, depth + 1)
        dependency = self._validated_dependency(lock, relative, source, syntax)
        self.scanned[lock.module_uri] = _ScannedModule(
            path, relative, lock, source, syntax, imports, dependency,
        )
        self.states[lock.module_uri] = "done"

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
                "HOCUS428", "Control project, lock, or catalog pins changed after resolution."
            )
        _require_control_project(refreshed)
        _validate_project_roots(refreshed, self.root)
        self._recheck_sources()
        for importer, specifier, selected in self.decisions:
            if self.select_target(importer, specifier) != selected:
                raise ProjectError(
                    "HOCUS428", "Control import winner changed after resolution."
                )

    def _resolve_entry(self) -> Path:
        candidate = self.root / self.entry_path_text
        _reject_reparse_components(candidate, self.root)
        _require_exact_windows_casing(candidate, self.root)
        entry = _canonical_file(candidate, self.root, "control entry source")
        if not any(
            _is_contained(entry, directory.resolve(strict=True))
            for directory in self.context.source_directories
        ):
            raise ProjectError(
                "HOCUS460",
                "Control entry must be contained by a configured source directory.",
            )
        if entry.relative_to(self.root).as_posix() != self.entry_path_text:
            raise ProjectError(
                "HOCUS460", "Control entry path must use its canonical project-relative spelling."
            )
        self._claim_portable_path(self.entry_path_text)
        return entry

    def _resolve_imports(
        self,
        importer: Path,
        syntax: SyntaxSource,
        *,
        depth: int,
    ) -> tuple[ResolvedImport, ...]:
        imports: list[ResolvedImport] = []
        targets: list[tuple[ModuleLockRecord, Path]] = []
        for declaration in syntax.imports:
            _cancel(self.cancelled)
            target = self.select_target(importer, declaration.specifier)
            self.decisions.append((importer, declaration.specifier, target))
            lock = self._lock_for_target(target)
            imports.append(ResolvedImport(
                declaration.specifier,
                declaration.imported_name,
                declaration.local_name,
                lock.module_uri,
                declaration.span,
            ))
            targets.append((lock, target))
        for lock, target in targets:
            self.visit(lock, target, depth + 1)
        _require_unique_aliases(imports, syntax.span.source_name)
        return tuple(imports)

    def _scan_module_imports(
        self,
        path: Path,
        syntax: SyntaxSource,
    ) -> tuple[tuple[ResolvedImport, ...], tuple[tuple[ModuleLockRecord, Path], ...]]:
        imports: list[ResolvedImport] = []
        targets: list[tuple[ModuleLockRecord, Path]] = []
        for declaration in syntax.imports:
            _cancel(self.cancelled)
            target = self.select_target(path, declaration.specifier)
            self.decisions.append((path, declaration.specifier, target))
            lock = self._lock_for_target(target)
            imports.append(ResolvedImport(
                declaration.specifier,
                declaration.imported_name,
                declaration.local_name,
                lock.module_uri,
                declaration.span,
            ))
            targets.append((lock, target))
        _require_unique_aliases(imports, syntax.span.source_name)
        return tuple(imports), tuple(targets)

    def _validated_dependency(
        self,
        lock: ModuleLockRecord,
        relative: str,
        source: bytes,
        syntax: SyntaxSource,
    ) -> ModuleDependency:
        source_digest = module_source_digest(source)
        interface_digest = module_interface_digest(
            _module_interface(syntax, self.limits.to_legacy_shape(), lock.module_uri)
        )
        child_digests = (
            (uri, self.scanned[uri].dependency.transitive_digest)
            for uri in lock.dependencies
        )
        transitive_digest = module_transitive_digest(
            uri=lock.module_uri,
            source_digest=source_digest,
            interface_digest=interface_digest,
            dependencies=child_digests,
        )
        actual = (source_digest, interface_digest, transitive_digest)
        expected = (
            lock.content_digest, lock.interface_digest, lock.transitive_digest,
        )
        if actual != expected:
            raise ProjectError(
                "HOCUS461",
                "Control module content, interface, or transitive digest is stale.",
                details={"moduleUri": lock.module_uri},
            )
        assert syntax.module is not None
        return ModuleDependency(
            lock.module_uri,
            syntax.module.name,
            relative,
            "project",
            self.context.uid or "",
            None,
            None,
            None,
            source_digest,
            interface_digest,
            transitive_digest,
            lock.dependencies,
            self.context.language_version,
        )

    def _resolved_set(
        self,
        entry_uri: str,
        ordered: tuple[_ScannedModule, ...],
    ) -> tuple[str, str]:
        version = 3 if self.context.language_version == "0.4" else 2
        payload = {
            "$schema": f"hocuspocus://schemas/resolved-module-set/v{version}",
            "kind": "hocus_resolved_module_set",
            "schemaVersion": version,
            "languageVersion": self.context.language_version,
            "projectUid": self.context.uid,
            "entrySourceUri": entry_uri,
            "projectManifestDigest": self.context.manifest_digest,
            "projectLockDigest": self.context.lock_digest,
            "resolverPolicyDigest": _resolver_policy_digest(self.context),
            "limits": self.limits.to_dict(),
            "modules": [item.dependency.to_dict() for item in ordered],
        }
        try:
            decoder = (
                decode_value_resolved_module_set_envelope
                if version == 3
                else decode_control_resolved_module_set_envelope
            )
            decoded = decoder(payload)
        except CarrierContractError as exc:
            raise ModuleResolutionError(
                "HOCUS493",
                f"Resolved control module set failed its strict v{version} contract.",
                details={"validatorCode": exc.code},
            ) from exc
        encoded = _canonical_json(decoded)
        return encoded, _digest(encoded.encode("utf-8"))

    def _lock_for_target(self, target: Path) -> ModuleLockRecord:
        relative = target.relative_to(self.root).as_posix()
        uri = _project_uri(self.context.uid or "", relative)
        lock = self.lock_by_uri.get(uri)
        if lock is None:
            raise ProjectError(
                "HOCUS462",
                "Resolved control module is absent from the verified project lock.",
                details={"moduleUri": uri},
            )
        _require_local_lock(
            lock,
            self.context.uid or "",
            relative,
            self.context.language_version,
        )
        return lock

    def _contained_candidate(self, candidate: Path, label: str) -> Path:
        _reject_reparse_components(candidate, self.root)
        _require_exact_windows_casing(candidate, self.root)
        return _canonical_file(candidate, self.root, label)

    def _select_bare_target(self, specifier: str) -> Path:
        for directory in self.context.module_directories:
            _cancel(self.cancelled)
            candidate = directory / specifier
            if not _lexically_occupied(candidate):
                continue
            target = self._contained_candidate(candidate, "bare control module import")
            if not _is_contained(target, directory.resolve(strict=True)):
                raise ProjectError(
                    "HOCUS460",
                    "Bare control module import escapes its configured module directory.",
                )
            return target
        raise ProjectError(
            "HOCUS462",
            "Bare control module import was not found in ordered module_directories.",
            details={"specifier": specifier},
        )

    def _read(self, path: Path) -> bytes:
        raw = _read_source(path, self.limits.to_legacy_shape(), self.cancelled)
        self.aggregate_source_bytes += len(raw)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ModuleResolutionError(
                "HOCUS464", "Control source closure exceeds aggregateSourceBytes."
            )
        self.source_evidence[path] = raw
        return raw

    def _claim_portable_path(self, relative: str) -> None:
        from .project import _portable_path_key

        key = _portable_path_key(relative)
        if key in self.portable_paths:
            raise ProjectError(
                "HOCUS462", "Control sources alias after portable path normalization."
            )
        self.portable_paths.add(key)

    def _recheck_sources(self) -> None:
        for path, expected in self.source_evidence.items():
            _cancel(self.cancelled)
            _reject_reparse_components(path, self.root)
            _require_exact_windows_casing(path, self.root)
            if _canonical_file(path, self.root, "control source recheck") != path:
                raise ProjectError(
                    "HOCUS428", "Control source identity changed after resolution."
                )
            current = _read_source(
                path, self.limits.to_legacy_shape(), self.cancelled,
            )
            if current != expected:
                raise ProjectError(
                    "HOCUS428", "Control source bytes changed after resolution."
                )


def resolve_project_control_program(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    *,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ResolvedControlProgram:
    """Resolve one exact same-project schema-v4/language-0.3 program.

    The function performs bounded native reads but never discovers a project,
    resolves external aliases, writes a lock, consults Houdini, or registers an
    MCP surface.  The result retains a final native :meth:`recheck` boundary.
    """

    selected_limits, control_limits = _select_limits(limits)
    return _ControlResolverSession.create(
        project_directory,
        entry_source_path,
        selected_limits,
        control_limits,
        cancelled,
    ).resolve()


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
        "limits must be a ControlResolverLimits or ControlExpansionLimits"
    )


def _require_control_project(context: ProjectContext) -> None:
    required = (
        context.uid,
        context.manifest_digest,
        context.lock_digest,
        context.catalog_content_digest,
        context.catalog_fingerprint,
        context.catalog,
    )
    if (
        (context.manifest_version, context.language_version)
        not in {(4, "0.3"), (5, "0.4")}
        or any(value is None for value in required)
    ):
        raise ProjectError(
            "HOCUS452",
            "Control resolution requires one fully pinned schema-v4/v5 control project.",
        )
    if context.external_aliases:
        raise ProjectError(
            "HOCUS460",
            "External aliases remain disabled in the same-project H3 control resolver.",
        )
    if any(record.external_alias is not None for record in context.locked_modules):
        raise ProjectError(
            "HOCUS460", "The same-project H3 control resolver rejects external lock records."
        )


def _validate_project_roots(context: ProjectContext, root: Path) -> None:
    if len(context.module_directory_paths) != len(context.module_directories):
        raise ProjectError(
            "HOCUS452", "Control project lost ordered module-directory provenance."
        )
    for authored_root in context.module_directory_paths:
        _reject_reparse_components(root / authored_root, root)
        _require_exact_windows_casing(root / authored_root, root)


def _parse_control_source(
    source: bytes,
    uri: str,
    *,
    graph: bool,
    language_version: str,
) -> SyntaxSource:
    try:
        text = source.decode("utf-8", errors="strict")
        syntax = parse_syntax(text, uri)
    except (UnicodeDecodeError, HocusSourceError, TypeError, ValueError, RecursionError) as exc:
        raise ProjectError(
            "HOCUS466",
            f"Native HocusScript source failed strict language {language_version} parsing.",
            details={"sourceUri": uri},
        ) from exc
    valid_root = (
        syntax.graph is not None and syntax.module is None
        if graph
        else syntax.module is not None and syntax.graph is None
    )
    if syntax.version is None or syntax.version.value != language_version or not valid_root:
        kind = "graph" if graph else "module"
        raise ProjectError(
            "HOCUS466",
            f"Native control source must contain one language {language_version} {kind} root.",
            details={"sourceUri": uri},
        )
    return syntax


def _require_local_lock(
    lock: ModuleLockRecord,
    project_uid: str,
    relative: str,
    language_version: str,
) -> None:
    expected_uri = _project_uri(project_uid, relative)
    if (
        lock.module_uri != expected_uri
        or lock.project_uid != project_uid
        or lock.source_path != relative
        or lock.language_version != language_version
        or lock.external_alias is not None
        or any(value is not None for value in (
            lock.library_uid, lock.library_version, lock.module_manifest_digest,
        ))
    ):
        raise ProjectError(
            "HOCUS462",
            "Resolved control module conflicts with its verified local lock identity.",
            details={"moduleUri": expected_uri},
        )


def _require_unique_aliases(imports: list[ResolvedImport], uri: str) -> None:
    aliases = [item.local_name for item in imports]
    if len(set(aliases)) != len(aliases):
        raise ProjectError(
            "HOCUS463",
            "Resolved language 0.3 imports contain duplicate local aliases.",
            details={"sourceUri": uri},
        )


def _resolver_policy(context: ProjectContext) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": "native_project_v1",
        "projectMode": "same_project_only",
        "relativeResolution": "importer_relative_project_contained",
        "moduleDirectories": list(context.module_directory_paths),
        "bareResolution": "ordered_first_occupied_fail_closed",
        "externalAliases": False,
        "casePolicy": "portable",
        "linkPolicy": "reject_reparse",
    }


def _resolver_policy_digest(context: ProjectContext) -> str:
    return _digest(_canonical_json(_resolver_policy(context)).encode("utf-8"))


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


def _handoff_digest(
    entry_uri: str,
    entry_digest: str,
    entry_imports: tuple[ResolvedImport, ...],
    resolved_set_digest: str,
    context: ProjectContext,
) -> str:
    payload = {
        "domain": "hocus-control-resolved-program-v1",
        "projectUid": context.uid,
        "projectManifestDigest": context.manifest_digest,
        "projectLockDigest": context.lock_digest,
        "catalogContentDigest": context.catalog_content_digest,
        "catalogFingerprint": context.catalog_fingerprint,
        "entrySourceUri": entry_uri,
        "entrySourceDigest": entry_digest,
        "entryImports": [
            {
                "specifier": item.specifier,
                "importedName": item.imported_name,
                "localName": item.local_name,
                "targetUri": item.target_uri,
            }
            for item in entry_imports
        ],
        "resolvedModuleSetDigest": resolved_set_digest,
    }
    return _digest(_canonical_json(payload).encode("utf-8"))


def _canonical_json(value: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = [
    "ControlResolverLimits",
    "ResolvedControlProgram",
    "resolve_project_control_program",
]
