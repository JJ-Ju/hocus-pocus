"""Read-only project editor support backed by exact published mixed roots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path, PurePosixPath
import re
from typing import Callable

from .external_roots import (
    _native_identity,
    _recheck as _recheck_external_roots,
    _validate_external_module_roots,
)
from .module_lock_plan import (
    _Target,
    _external_target,
    _mixed_resolver_policy,
    _read_target,
    _relative_external_path,
    _require_same_inspection,
)
from .module_paths import is_literal_import_specifier
from .mixed_resolution import _require_locked_target
from .project import ModuleLockRecord, ProjectContext, ProjectError, _read_bounded_stable
from .project_editor import (
    MAX_PROJECT_EDITOR_ITEMS,
    ProjectCompletionItem,
    ProjectCompletionResult,
    ProjectDefinitionResult,
    ProjectEditorPins,
    _check_cancelled,
    _completion_values,
    _context_prefix,
    _current_relative_path,
    _definition_values,
    _locked_by_uri,
    _project_uri,
    _relative_path_text,
    _relative_specifier,
    _source_bytes,
    _span,
    _subject_path,
    _validate_request,
)
from .resolved_modules import (
    ResolvedModuleLimits,
    _module_interface,
    module_interface_digest,
    module_source_digest,
)
from .resolver import _parse, _project_uri as _resolver_project_uri, _select_project_module_target


@dataclass(slots=True)
class _LoadedMixedEditorModule:
    specifier: str
    target: _Target
    uri: str
    raw: bytes
    digest: str
    syntax: object
    interface: dict
    identity: tuple[int, int, int]

    @property
    def path(self) -> Path:
        return self.target.path


class _MixedProjectEditorSession:
    """One retained, verify-only mixed-root editor authority."""

    def __init__(
        self,
        project_directory: str | PathLike[str],
        current_path: str | PathLike[str],
        source: str,
        module_roots: Mapping[str, str | PathLike[str]],
        *,
        cancelled: Callable[[], bool] | None,
        saved: bool,
    ) -> None:
        self.cancelled = cancelled
        self._cancel()
        relative_input = _relative_path_text(current_path)
        self.roots = _validate_external_module_roots(
            project_directory, module_roots, cancelled=cancelled,
        )
        if any(not item.manifest_was_pre_pinned for item in self.roots.roots):
            raise ProjectError(
                "HOCUS459",
                "Mixed project editor support requires every external manifest to be pre-pinned.",
            )
        self.context = ProjectContext.load(project_directory, validate_lock=True)
        _require_same_inspection(self.context, self.roots)
        if (
            self.context.manifest_version != 3
            or self.context.language_version != "0.2"
            or self.context.uid is None
            or self.context.manifest_digest is None
            or self.context.lock_digest is None
            or self.context.catalog_content_digest is None
            or self.context.catalog_fingerprint is None
        ):
            raise ProjectError(
                "HOCUS480",
                "Mixed project editor support requires one fully pinned schema v3 project.",
            )
        self.relative = _current_relative_path(self.context, relative_input)
        self.current_path = _subject_path(self.context, self.relative, require_file=saved)
        self.source_uri = _project_uri(self.context.uid, self.relative)
        self.raw = _source_bytes(source)
        self.source = source
        self.source_digest = module_source_digest(self.raw)
        self.saved = saved
        self.initial_saved_digest = self.source_digest if saved else None
        self.initial_saved_identity = (
            _native_identity(self.current_path, "mixed editor subject") if saved else None
        )
        policy = _mixed_resolver_policy(self.context, self.roots)
        self.pins = ProjectEditorPins(
            self.context.uid,
            self.context.manifest_digest,
            self.context.lock_digest,
            self.context.catalog_content_digest,
            self.context.catalog_fingerprint,
            module_interface_digest(policy),
        )
        self.lock_by_uri = _locked_by_uri(self.context)
        locked = self.lock_by_uri.get(self.source_uri)
        self.subject_lock_state = (
            "unlocked" if locked is None else
            "matching" if locked.content_digest == self.source_digest else
            "modified"
        )
        self.limits = ResolvedModuleLimits()
        self.aggregate_source_bytes = len(self.raw)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ProjectError("HOCUS464", "Mixed project editor aggregateSourceBytes budget was exceeded.")
        self.loaded: dict[str, _LoadedMixedEditorModule] = {}
        self.loaded_by_uri: dict[str, _LoadedMixedEditorModule] = {}
        self.targets_by_path: dict[Path, _Target] = {}
        self.decisions: list[tuple[_Target | None, Path, str, _Target]] = []
        self.by_alias = {item.alias: item for item in self.roots.roots}

    def _select(self, importer: _Target | None, importer_path: Path, specifier: str) -> _Target:
        if not is_literal_import_specifier(specifier):
            raise ProjectError("HOCUS460", "Mixed editor imports must be portable literal .hocus paths.")
        if specifier.startswith("@"):
            alias, separator, tail = specifier[1:].partition("/")
            external = self.by_alias.get(alias)
            if not separator or external is None:
                raise ProjectError("HOCUS460", "External import alias is not explicitly approved.")
            self.roots.root_for_alias(alias, require_manifest_pin=True)
            if importer is not None and importer.owner_kind == "library" and importer.alias == alias:
                raise ProjectError("HOCUS460", "Same-library alias imports are forbidden.")
            if tail not in external.pin.entry_modules:
                raise ProjectError("HOCUS462", "External alias imports may enter only manifest entries.")
            target = _external_target(external, tail)
        elif importer is not None and importer.owner_kind == "library":
            if not specifier.startswith(("./", "../")):
                raise ProjectError("HOCUS460", "Bare imports are disabled inside external libraries.")
            external = self.by_alias.get(importer.alias or "")
            if external is None:
                raise ProjectError("HOCUS460", "External importer alias is not approved.")
            target = _external_target(
                external,
                _relative_external_path(external.root, importer_path.parent / specifier),
            )
        else:
            selected = _select_project_module_target(
                self.context, importer_path, specifier, cancelled=self.cancelled,
            )
            relative = selected.relative_to(self.context.root).as_posix()
            target = _Target(
                _resolver_project_uri(self.context.uid or "", relative),
                selected,
                relative,
                "project",
                self.context.uid or "",
                None,
                self.context.root,
            )
        self._require_locked(target)
        self.decisions.append((importer, importer_path, specifier, target))
        return target

    def select_import(self, importer: Path, specifier: str) -> Path:
        owner = self.targets_by_path.get(importer)
        target = self._select(owner, importer, specifier)
        return target.path

    def load_import(self, specifier: str) -> _LoadedMixedEditorModule:
        cached = self.loaded.get(specifier)
        if cached is not None:
            return cached
        self._cancel()
        target = self._select(None, self.current_path, specifier)
        existing = self.loaded_by_uri.get(target.uri)
        if existing is not None:
            self.loaded[specifier] = existing
            return existing
        if len(self.loaded_by_uri) >= self.limits.module_files:
            raise ProjectError("HOCUS464", "Mixed project editor moduleFiles budget was exceeded.")
        locked = self._require_locked(target)
        raw, identity = _read_target(target, self.limits, self.cancelled)
        if self.aggregate_source_bytes + len(raw) > self.limits.aggregate_source_bytes:
            raise ProjectError("HOCUS464", "Mixed project editor aggregateSourceBytes budget was exceeded.")
        if module_source_digest(raw) != locked.content_digest:
            raise ProjectError(
                "HOCUS461", "Mixed editor module bytes do not match the verified lock.",
                details={"sourceUri": target.uri},
            )
        syntax = _parse(raw, target.uri, graph=False)
        interface = _module_interface(syntax, self.limits, target.uri)
        if module_interface_digest(interface) != locked.interface_digest:
            raise ProjectError(
                "HOCUS461", "Mixed editor module interface does not match the verified lock.",
                details={"sourceUri": target.uri},
            )
        dependencies: list[str] = []
        targets: set[str] = set()
        names: set[str] = set()
        specifiers: set[str] = set()
        for declaration in syntax.imports:
            dependency = self._select(target, target.path, declaration.specifier)
            if (
                declaration.local_name in names
                or declaration.specifier in specifiers
                or dependency.uri in targets
            ):
                raise ProjectError("HOCUS462", "Mixed editor module imports must be unique.")
            dependencies.append(dependency.uri)
            names.add(declaration.local_name)
            specifiers.add(declaration.specifier)
            targets.add(dependency.uri)
        if tuple(sorted(dependencies)) != locked.dependencies:
            raise ProjectError(
                "HOCUS462", "Mixed editor module declarations do not match locked dependencies.",
                details={"sourceUri": target.uri},
            )
        loaded = _LoadedMixedEditorModule(
            specifier, target, target.uri, raw, locked.content_digest,
            syntax, interface, identity,
        )
        self.aggregate_source_bytes += len(raw)
        self.loaded[specifier] = loaded
        self.loaded_by_uri[target.uri] = loaded
        self.targets_by_path[target.path] = target
        return loaded

    def import_path_candidates(self) -> list[tuple[str, ModuleLockRecord]]:
        output: dict[str, ModuleLockRecord] = {}
        importer_parent = PurePosixPath(self.relative).parent
        for record in self.context.locked_modules:
            if record.external_alias is not None:
                external = self.by_alias.get(record.external_alias)
                if external is None or record.source_path not in external.pin.entry_modules:
                    continue
                specifier = f"@{record.external_alias}/{record.source_path}"
                target = self._select(None, self.current_path, specifier)
                if target.uri != record.module_uri:
                    raise ProjectError("HOCUS462", "An external completion candidate changed identity.")
                output[specifier] = record
                continue
            path = PurePosixPath(record.source_path)
            for directory in self.context.module_directory_paths:
                directory_path = PurePosixPath(directory)
                try:
                    bare = path.relative_to(directory_path).as_posix()
                except ValueError:
                    continue
                target = self._select(None, self.current_path, bare)
                if target.uri != record.module_uri:
                    raise ProjectError(
                        "HOCUS462",
                        "A bare completion candidate is shadowed by a different first occupied module.",
                        details={"specifier": bare},
                    )
                output[bare] = record
                break
            relative = _relative_specifier(importer_parent, path)
            target = self._select(None, self.current_path, relative)
            if target.uri != record.module_uri:
                raise ProjectError("HOCUS462", "A relative completion candidate changed identity.")
            output.setdefault(relative, record)
        return sorted(output.items(), key=lambda item: (item[0].casefold(), item[0]))

    def _require_locked(self, target: _Target) -> ModuleLockRecord:
        return _require_locked_target(target, self.lock_by_uri, self.roots)

    def finish(self) -> None:
        self._cancel()
        refreshed = ProjectContext.load(self.context.root, validate_lock=True)
        if (
            refreshed.uid != self.context.uid
            or refreshed.manifest_digest != self.context.manifest_digest
            or refreshed.lock_digest != self.context.lock_digest
            or refreshed.catalog_content_digest != self.context.catalog_content_digest
            or refreshed.catalog_fingerprint != self.context.catalog_fingerprint
            or refreshed.module_directory_paths != self.context.module_directory_paths
            or refreshed.external_aliases != self.context.external_aliases
            or refreshed.locked_modules != self.context.locked_modules
        ):
            raise ProjectError("HOCUS428", "Mixed editor project, lock, catalog, or policy changed.")
        _recheck_external_roots(self.context, self.roots, self.cancelled)
        if self.saved:
            if _subject_path(refreshed, self.relative, require_file=True) != self.current_path:
                raise ProjectError("HOCUS428", "Mixed editor subject identity changed during the request.")
            if _native_identity(self.current_path, "mixed editor subject") != self.initial_saved_identity:
                raise ProjectError("HOCUS428", "Mixed editor subject object changed during the request.")
            current = _read_bounded_stable(
                self.current_path, self.limits.source_bytes_per_file,
                "HOCUS461", "HocusScript mixed editor subject",
            )
            if module_source_digest(current) != self.initial_saved_digest:
                raise ProjectError("HOCUS428", "Mixed editor subject changed during the request.")
        else:
            _subject_path(refreshed, self.relative, require_file=False)
        for loaded in self.loaded_by_uri.values():
            current, identity = _read_target(loaded.target, self.limits, self.cancelled)
            if identity != loaded.identity or current != loaded.raw:
                raise ProjectError(
                    "HOCUS428", "Mixed editor module changed during the request.",
                    details={"sourceUri": loaded.uri},
                )
            self._require_locked(loaded.target)
        initial_count = len(self.decisions)
        for importer, importer_path, specifier, expected in tuple(self.decisions):
            if self._select(importer, importer_path, specifier) != expected:
                raise ProjectError("HOCUS428", "Mixed editor import winner changed during the request.")
        del self.decisions[initial_count:]
        self._cancel()

    def _cancel(self) -> None:
        if self.cancelled is None:
            return
        try:
            value = self.cancelled()
        except Exception as exc:
            raise ProjectError(
                "HOCUS465", "Mixed project editor cancellation callback failed.",
                details={"errorType": type(exc).__name__},
            ) from exc
        if type(value) is not bool:
            raise ProjectError("HOCUS465", "Mixed project editor cancellation callback must return bool.")
        if value:
            raise ProjectError("HOCUS465", "Mixed project editor request was cancelled.")


def complete_mixed_path(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    """Complete a saved project-local source using mandatory per-call mixed roots."""

    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _complete_mixed(
        project_directory, relative, source, offset, module_roots,
        limit=limit, cancelled=cancelled, saved=True,
    )


def complete_mixed_project_source(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    source: str,
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    """Complete a dirty project-local source using mandatory per-call mixed roots."""

    return _complete_mixed(
        project_directory, current_path, source, offset, module_roots,
        limit=limit, cancelled=cancelled, saved=False,
    )


def definition_mixed_path(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    """Resolve definitions for a saved project-local source through exact mixed roots."""

    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _definition_mixed(
        project_directory, relative, source, offset, module_roots,
        cancelled=cancelled, saved=True,
    )


def definition_mixed_project_source(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    source: str,
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    """Resolve definitions for a dirty project-local source through exact mixed roots."""

    return _definition_mixed(
        project_directory, current_path, source, offset, module_roots,
        cancelled=cancelled, saved=False,
    )


def _read_saved_subject(project_directory, current_path) -> tuple[str, str]:
    relative_input = _relative_path_text(current_path)
    context = ProjectContext.load(project_directory, validate_lock=True)
    relative = _current_relative_path(context, relative_input)
    path = _subject_path(context, relative, require_file=True)
    raw = _read_bounded_stable(
        path, ResolvedModuleLimits().source_bytes_per_file,
        "HOCUS461", "HocusScript mixed editor subject",
    )
    try:
        return relative, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError("HOCUS466", "Mixed editor subject must be valid UTF-8.") from exc


def _complete_mixed(
    project_directory, current_path, source, offset, module_roots,
    *, limit, cancelled, saved,
) -> ProjectCompletionResult:
    _validate_request(source, offset, limit)
    session = _MixedProjectEditorSession(
        project_directory, current_path, source, module_roots,
        cancelled=cancelled, saved=saved,
    )
    context, values = _mixed_completion_values(session, source, offset)
    values = list(dict.fromkeys(values))
    prefix, start = _context_prefix(source, offset, context)
    replacement = _span(source, session.source_uri, start, offset)
    folded = prefix.casefold()
    filtered = [item for item in values if not folded or item[0].casefold().startswith(folded)]
    filtered.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))
    incomplete = len(filtered) > limit
    items = tuple(ProjectCompletionItem(
        label, kind, insert, replacement, detail, required, type_name, default,
    ) for label, kind, insert, detail, required, type_name, default in filtered[:limit])
    session.finish()
    return ProjectCompletionResult(
        session.source_uri, session.source_digest, session.subject_lock_state,
        offset, context, items, session.pins, incomplete,
    )


def _definition_mixed(
    project_directory, current_path, source, offset, module_roots,
    *, cancelled, saved,
) -> ProjectDefinitionResult:
    _validate_request(source, offset, MAX_PROJECT_EDITOR_ITEMS)
    session = _MixedProjectEditorSession(
        project_directory, current_path, source, module_roots,
        cancelled=cancelled, saved=saved,
    )
    items = tuple(_definition_values(session, source, offset))
    session.finish()
    return ProjectDefinitionResult(
        session.source_uri, session.source_digest, session.subject_lock_state,
        offset, items, session.pins,
    )


def _mixed_completion_values(session: _MixedProjectEditorSession, source: str, offset: int):
    masked_before = _mask_for_import_path(source[:offset])
    if re.search(
        r'\bimport\s*\{\s*[A-Za-z_][A-Za-z0-9_]*'
        r'(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\}\s*'
        r'from\s+"([^"\n]*)$',
        masked_before,
    ):
        return "import_path", [
            (value, "module_path", value, record.module_uri, None, None, None)
            for value, record in session.import_path_candidates()
        ]
    return _completion_values(session, source, offset)


def _mask_for_import_path(source: str) -> str:
    # The established editor scanner is intentionally private but stable within
    # this package; import lazily to keep the mixed surface small.
    from .project_editor import _mask_non_import_text

    return _mask_non_import_text(source)
