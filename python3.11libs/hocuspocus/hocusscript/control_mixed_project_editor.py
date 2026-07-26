"""Project-local editor subjects backed by exact HocusScript 0.3 mixed roots."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .control_editor_scope import ImportedModuleView, definition_at
from .control_mixed_resolution import (
    _MixedControlSession,
    _control_mixed_resolver_policy,
    _digest_json,
)
from .control_project_editor import (
    _completion_prefix,
    _completion_values,
    _module_view,
    _parse_current,
)
from .control_resolver import ControlResolverLimits
from .control_semantic import ControlExpansionLimits
from .module_lock_plan import _Target
from .project import ProjectContext, ProjectError, _read_bounded_stable
from .project_editor import (
    MAX_PROJECT_EDITOR_ITEMS,
    ProjectCompletionItem,
    ProjectCompletionResult,
    ProjectDefinitionItem,
    ProjectDefinitionResult,
    ProjectEditorPins,
    _check_cancelled,
    _current_relative_path,
    _project_uri,
    _relative_path_text,
    _relative_specifier,
    _source_bytes,
    _span,
    _subject_path,
    _validate_request,
)
from .resolved_modules import module_source_digest
from .syntax import SyntaxSource


@dataclass(slots=True)
class _LoadedMixedControlEditorModule:
    specifier: str
    target: _Target
    uri: str
    raw: bytes
    digest: str
    syntax: SyntaxSource
    interface: dict[str, Any]

    @property
    def path(self) -> Path:
        return self.target.path


class _MixedControlProjectEditorSession:
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
        relative_input = _relative_path_text(current_path)
        self.limits = ControlResolverLimits()
        self.authority = _MixedControlSession.create(
            project_directory,
            (),
            module_roots,
            self.limits,
            ControlExpansionLimits(),
            cancelled,
            verify_lock=True,
        )
        self.context = self.authority.context
        self.root = self.authority.root
        self.relative = _current_relative_path(self.context, relative_input)
        self.current_path = _subject_path(
            self.context, self.relative, require_file=saved,
        )
        self.current_target = _Target(
            _project_uri(self.context.uid or "", self.relative),
            self.current_path,
            self.relative,
            "project",
            self.context.uid or "",
            None,
            self.root,
        )
        self.source_uri = self.current_target.uri
        self.raw = _source_bytes(source)
        self.source_digest = module_source_digest(self.raw)
        self.saved = saved
        self.initial_saved_digest = self.source_digest if saved else None
        if len(self.raw) > self.limits.aggregate_source_bytes:
            raise ProjectError(
                "HOCUS464",
                "Mixed control editor aggregateSourceBytes budget was exceeded.",
            )
        self.authority.aggregate_source_bytes = len(self.raw)
        locked = self.authority.lock_by_uri.get(self.source_uri)
        self.subject_lock_state = (
            "unlocked" if locked is None
            else "matching" if locked.content_digest == self.source_digest
            else "modified"
        )
        self.pins = ProjectEditorPins(
            self.context.uid or "",
            self.context.manifest_digest or "",
            self.context.lock_digest or "",
            self.context.catalog_content_digest or "",
            self.context.catalog_fingerprint or "",
            _digest_json(
                _control_mixed_resolver_policy(
                    self.context, self.authority.roots,
                )
            ),
        )
        self.loaded: dict[str, _LoadedMixedControlEditorModule] = {}
        self.loaded_by_uri: dict[str, _LoadedMixedControlEditorModule] = {}

    @property
    def catalog(self):
        assert self.context.catalog is not None
        return self.context.catalog

    def select_import(self, importer: Path, specifier: str) -> Path:
        owner = self._target_for_path(importer)
        return self.authority.select(owner, importer, specifier).path

    def load_import(self, specifier: str) -> _LoadedMixedControlEditorModule:
        cached = self.loaded.get(specifier)
        if cached is not None:
            return cached
        target = self.authority.select(
            None, self.current_path, specifier,
        )
        existing = self.loaded_by_uri.get(target.uri)
        if existing is not None:
            self.loaded[specifier] = existing
            return existing
        self.authority.visit(target, 1)
        self.authority._validate_imported_names()
        self.authority.derive_records()
        scanned = self.authority.scanned[target.uri]
        interface = _interface_for_scanned(scanned, self.limits)
        loaded = _LoadedMixedControlEditorModule(
            specifier,
            target,
            target.uri,
            scanned.source,
            module_source_digest(scanned.source),
            scanned.syntax,
            interface,
        )
        self.loaded[specifier] = loaded
        for uri, item in self.authority.scanned.items():
            self.loaded_by_uri.setdefault(
                uri,
                _LoadedMixedControlEditorModule(
                    item.target.relative,
                    item.target,
                    uri,
                    item.source,
                    module_source_digest(item.source),
                    item.syntax,
                    _interface_for_scanned(item, self.limits),
                ),
            )
        self.loaded_by_uri[target.uri] = loaded
        return loaded

    def import_views(
        self,
        syntax: SyntaxSource,
    ) -> dict[str, ImportedModuleView]:
        views: dict[str, ImportedModuleView] = {}
        for declaration in syntax.imports:
            loaded = self.load_import(declaration.specifier)
            root = loaded.syntax.module
            if root is None or root.name != declaration.imported_name:
                raise ProjectError(
                    "HOCUS462",
                    "Mixed editor import name conflicts with the verified module.",
                    details={"sourceUri": loaded.uri},
                )
            views[declaration.local_name] = _module_view(
                declaration.local_name, loaded,
            )
        return views

    def import_path_candidates(self):
        output = {}
        parent = PurePosixPath(self.relative).parent
        roots_by_alias = {
            item.alias: item for item in self.authority.roots.roots
        }
        for record in self.context.locked_modules:
            if record.external_alias is not None:
                approved = roots_by_alias.get(record.external_alias)
                if (
                    approved is None
                    or record.source_path not in approved.pin.entry_modules
                ):
                    continue
                specifier = f"@{record.external_alias}/{record.source_path}"
                target = self.authority.select(
                    None, self.current_path, specifier,
                )
                _require_candidate_identity(target, record.module_uri)
                output[specifier] = record
                continue
            path = PurePosixPath(record.source_path)
            self._add_local_candidates(output, record, path, parent)
        return sorted(output.items(), key=lambda item: (item[0].casefold(), item[0]))

    def digest_for_uri(self, uri: str) -> str | None:
        if uri == self.source_uri:
            return self.source_digest
        loaded = self.loaded_by_uri.get(uri)
        return loaded.digest if loaded is not None else None

    def finish(self) -> None:
        self.authority.recheck()
        if self.saved:
            self._recheck_saved_subject()
        else:
            _subject_path(self.context, self.relative, require_file=False)

    def _add_local_candidates(self, output, record, path, parent) -> None:
        for directory in self.context.module_directory_paths:
            try:
                bare = path.relative_to(PurePosixPath(directory)).as_posix()
            except ValueError:
                continue
            target = self.authority.select(None, self.current_path, bare)
            _require_candidate_identity(target, record.module_uri)
            output[bare] = record
            break
        relative = _relative_specifier(parent, path)
        target = self.authority.select(None, self.current_path, relative)
        _require_candidate_identity(target, record.module_uri)
        output.setdefault(relative, record)

    def _target_for_path(self, path: Path) -> _Target | None:
        if path == self.current_path:
            return None
        loaded = next(
            (item for item in self.loaded_by_uri.values() if item.path == path),
            None,
        )
        return loaded.target if loaded is not None else None

    def _recheck_saved_subject(self) -> None:
        if _subject_path(
            self.context, self.relative, require_file=True,
        ) != self.current_path:
            raise ProjectError(
                "HOCUS428",
                "Mixed control editor subject identity changed during the request.",
            )
        current = _read_bounded_stable(
            self.current_path,
            self.limits.source_bytes_per_file,
            "HOCUS461",
            "HocusScript mixed control editor subject",
        )
        if module_source_digest(current) != self.initial_saved_digest:
            raise ProjectError(
                "HOCUS428",
                "Mixed control editor subject changed during the request.",
            )


def complete_mixed_control_path(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _complete(
        project_directory,
        relative,
        source,
        offset,
        module_roots,
        limit=limit,
        cancelled=cancelled,
        saved=True,
    )


def complete_mixed_control_project_source(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    source: str,
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    return _complete(
        project_directory,
        current_path,
        source,
        offset,
        module_roots,
        limit=limit,
        cancelled=cancelled,
        saved=False,
    )


def definition_mixed_control_path(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _definition(
        project_directory,
        relative,
        source,
        offset,
        module_roots,
        cancelled=cancelled,
        saved=True,
    )


def definition_mixed_control_project_source(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
    source: str,
    offset: int,
    *,
    module_roots: Mapping[str, str | PathLike[str]],
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    return _definition(
        project_directory,
        current_path,
        source,
        offset,
        module_roots,
        cancelled=cancelled,
        saved=False,
    )


def _complete(
    project_directory,
    current_path,
    source,
    offset,
    module_roots,
    *,
    limit,
    cancelled,
    saved,
) -> ProjectCompletionResult:
    _validate_request(source, offset, limit)
    session = _MixedControlProjectEditorSession(
        project_directory,
        current_path,
        source,
        module_roots,
        cancelled=cancelled,
        saved=saved,
    )
    context, values = _completion_values(session, source, offset)
    values = list(dict.fromkeys(values))
    prefix, start = _completion_prefix(source, offset, context)
    replacement = _span(source, session.source_uri, start, offset)
    folded = prefix.casefold()
    filtered = [
        item for item in values
        if not folded or item[0].casefold().startswith(folded)
    ]
    filtered.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))
    incomplete = len(filtered) > limit
    items = tuple(
        ProjectCompletionItem(
            label, kind, insert, replacement, detail,
            required, type_name, default,
        )
        for label, kind, insert, detail, required, type_name, default
        in filtered[:limit]
    )
    session.finish()
    return ProjectCompletionResult(
        session.source_uri,
        session.source_digest,
        session.subject_lock_state,
        offset,
        context,
        items,
        session.pins,
        incomplete,
    )


def _definition(
    project_directory,
    current_path,
    source,
    offset,
    module_roots,
    *,
    cancelled,
    saved,
) -> ProjectDefinitionResult:
    _validate_request(source, offset, MAX_PROJECT_EDITOR_ITEMS)
    session = _MixedControlProjectEditorSession(
        project_directory,
        current_path,
        source,
        module_roots,
        cancelled=cancelled,
        saved=saved,
    )
    syntax = _parse_current(source, session.source_uri)
    items: tuple[ProjectDefinitionItem, ...] = ()
    if syntax is not None:
        views = session.import_views(syntax)
        target = definition_at(source, syntax, offset, views)
        if target is not None:
            digest = session.digest_for_uri(target.source_uri)
            if digest is not None:
                items = (
                    ProjectDefinitionItem(
                        target.name,
                        target.kind,
                        target.source_uri,
                        digest,
                        target.span,
                    ),
                )
    session.finish()
    return ProjectDefinitionResult(
        session.source_uri,
        session.source_digest,
        session.subject_lock_state,
        offset,
        items,
        session.pins,
    )


def _read_saved_subject(
    project_directory: str | PathLike[str],
    current_path: str | PathLike[str],
) -> tuple[str, str]:
    relative_input = _relative_path_text(current_path)
    context = ProjectContext.load(project_directory, validate_lock=True)
    relative = _current_relative_path(context, relative_input)
    path = _subject_path(context, relative, require_file=True)
    raw = _read_bounded_stable(
        path,
        ControlResolverLimits().source_bytes_per_file,
        "HOCUS461",
        "HocusScript mixed control editor subject",
    )
    try:
        return relative, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS466",
            "Mixed control editor subject must be valid UTF-8.",
        ) from exc


def _interface_for_scanned(item, limits: ControlResolverLimits):
    from .resolved_modules import _module_interface

    return _module_interface(
        item.syntax, limits.to_legacy_shape(), item.target.uri,
    )


def _require_candidate_identity(target: _Target, expected_uri: str) -> None:
    if target.uri != expected_uri:
        raise ProjectError(
            "HOCUS462",
            "Mixed control editor import candidate changed identity.",
        )


__all__ = [
    "complete_mixed_control_path",
    "complete_mixed_control_project_source",
    "definition_mixed_control_path",
    "definition_mixed_control_project_source",
]
