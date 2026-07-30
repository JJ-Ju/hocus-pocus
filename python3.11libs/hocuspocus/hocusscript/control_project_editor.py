"""Read-only project editor APIs for the local HocusScript 0.3 lane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .catalog import CatalogSnapshot, ParameterDefinition
from .control_editor_scope import (
    EditorScopeMember,
    ImportedModuleView,
    definition_at,
    scope_at,
    yield_names_at,
)
from .control_resolver import (
    ControlResolverLimits,
    _parse_control_source,
    _project_pins,
    _require_control_project,
    _resolver_policy_digest,
    _validate_project_roots,
)
from .diagnostics import HocusSourceError
from .editor import (
    _active_node,
    _category,
    _mask_literals_and_comments,
    _operator_candidates,
)
from .module_paths import is_literal_import_specifier
from .parser import parse_syntax
from .project import ProjectContext, ProjectError, _read_bounded_stable
from .project_editor import (
    MAX_PROJECT_EDITOR_ITEMS,
    ProjectCompletionItem,
    ProjectCompletionResult,
    ProjectDefinitionItem,
    ProjectDefinitionResult,
    ProjectEditorPins,
    _active_import_clause,
    _active_use_call,
    _check_cancelled,
    _context_prefix,
    _current_relative_path,
    _import_for_local,
    _imports,
    _mask_non_import_text,
    _project_uri,
    _relative_path_text,
    _relative_specifier,
    _source_bytes,
    _span,
    _subject_path,
    _validate_request,
)
from .resolved_modules import (
    _module_interface,
    module_interface_digest,
    module_source_digest,
)
from .resolver import (
    _canonical_file,
    _lexically_occupied,
    _reject_reparse_components,
    _require_exact_windows_casing,
)
from .syntax import SyntaxSource


@dataclass(slots=True)
class _LoadedControlEditorModule:
    specifier: str
    path: Path
    relative: str
    uri: str
    raw: bytes
    digest: str
    syntax: SyntaxSource
    interface: dict[str, Any]


class _ControlProjectEditorSession:
    def __init__(
        self,
        project_directory: str | Path,
        current_path: str | Path,
        source: str,
        *,
        cancelled: Callable[[], bool] | None,
        saved: bool,
    ) -> None:
        self.cancelled = cancelled
        self._cancel()
        relative_input = _relative_path_text(current_path)
        self.context = ProjectContext.load(project_directory, validate_lock=True)
        _require_local_editor_project(self.context)
        self.root = self.context.root.resolve(strict=True)
        _validate_project_roots(self.context, self.root)
        self.relative = _current_relative_path(self.context, relative_input)
        self.current_path = _subject_path(
            self.context, self.relative, require_file=saved,
        )
        self.source_uri = _project_uri(self.context.uid or "", self.relative)
        self.raw = _source_bytes(source)
        self.source_digest = module_source_digest(self.raw)
        self.saved = saved
        self.initial_saved_digest = self.source_digest if saved else None
        self.pins = ProjectEditorPins(
            self.context.uid or "",
            self.context.manifest_digest or "",
            self.context.lock_digest or "",
            self.context.catalog_content_digest or "",
            self.context.catalog_fingerprint or "",
            _resolver_policy_digest(self.context),
        )
        self.lock_by_uri = {
            record.module_uri: record for record in self.context.locked_modules
        }
        locked = self.lock_by_uri.get(self.source_uri)
        self.subject_lock_state = (
            "unlocked" if locked is None
            else "matching" if locked.content_digest == self.source_digest
            else "modified"
        )
        self.limits = ControlResolverLimits()
        self.aggregate_source_bytes = len(self.raw)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ProjectError(
                "HOCUS464", "Control editor aggregateSourceBytes budget was exceeded.",
            )
        self.loaded: dict[str, _LoadedControlEditorModule] = {}
        self.loaded_by_uri: dict[str, _LoadedControlEditorModule] = {}
        self.decisions: list[tuple[Path, str, Path]] = []

    @property
    def catalog(self) -> CatalogSnapshot:
        assert self.context.catalog is not None
        return self.context.catalog

    def select_import(self, importer: Path, specifier: str) -> Path:
        self._cancel()
        if not is_literal_import_specifier(specifier) or specifier.startswith("@"):
            raise ProjectError(
                "HOCUS460",
                "Control editor imports must be literal same-project paths.",
            )
        if specifier.startswith(("./", "../")):
            selected = self._contained_candidate(
                importer.parent / specifier, "relative control editor import",
            )
        else:
            selected = self._select_bare(specifier)
        self.decisions.append((importer, specifier, selected))
        return selected

    def load_import(self, specifier: str) -> _LoadedControlEditorModule:
        cached = self.loaded.get(specifier)
        if cached is not None:
            return cached
        target = self.select_import(self.current_path, specifier)
        relative = target.relative_to(self.root).as_posix()
        uri = _project_uri(self.context.uid or "", relative)
        existing = self.loaded_by_uri.get(uri)
        if existing is not None:
            self.loaded[specifier] = existing
            return existing
        if len(self.loaded_by_uri) >= self.limits.module_files:
            raise ProjectError(
                "HOCUS464", "Control editor moduleFiles budget was exceeded.",
            )
        lock = self.lock_by_uri.get(uri)
        _require_editor_lock(
            lock,
            self.context.uid or "",
            relative,
            self.context.language_version,
        )
        raw = _read_bounded_stable(
            target, self.limits.source_bytes_per_file,
            "HOCUS461", "HocusScript control editor module",
        )
        if self.aggregate_source_bytes + len(raw) > self.limits.aggregate_source_bytes:
            raise ProjectError(
                "HOCUS464", "Control editor aggregateSourceBytes budget was exceeded.",
            )
        if module_source_digest(raw) != lock.content_digest:
            raise ProjectError(
                "HOCUS461", "Control editor module bytes do not match the v4 lock.",
                details={"sourceUri": uri},
            )
        syntax = _parse_control_source(
            raw,
            uri,
            graph=False,
            language_version=self.context.language_version,
        )
        interface = _module_interface(
            syntax, self.limits.to_legacy_shape(), uri,
        )
        if module_interface_digest(interface) != lock.interface_digest:
            raise ProjectError(
                "HOCUS461", "Control editor module interface is stale.",
                details={"sourceUri": uri},
            )
        self._validate_dependencies(target, syntax, lock.dependencies)
        loaded = _LoadedControlEditorModule(
            specifier, target, relative, uri, raw, lock.content_digest,
            syntax, interface,
        )
        self.aggregate_source_bytes += len(raw)
        self.loaded[specifier] = loaded
        self.loaded_by_uri[uri] = loaded
        return loaded

    def import_views(
        self,
        syntax: SyntaxSource,
    ) -> dict[str, ImportedModuleView]:
        views: dict[str, ImportedModuleView] = {}
        for declaration in syntax.imports:
            module = self.load_import(declaration.specifier)
            root = module.syntax.module
            assert root is not None
            if root.name != declaration.imported_name:
                raise ProjectError(
                    "HOCUS462",
                    "Imported module name does not match its locked declaration.",
                    details={"sourceUri": module.uri},
                )
            views[declaration.local_name] = _module_view(
                declaration.local_name, module,
            )
        return views

    def import_path_candidates(self):
        output = {}
        importer_parent = PurePosixPath(self.relative).parent
        for record in self.context.locked_modules:
            if record.external_alias is not None:
                raise ProjectError(
                    "HOCUS460", "Local control editor encountered an external lock record.",
                )
            path = PurePosixPath(record.source_path)
            for directory in self.context.module_directory_paths:
                try:
                    bare = path.relative_to(PurePosixPath(directory)).as_posix()
                except ValueError:
                    continue
                if self._selected_relative(bare) != record.source_path:
                    raise ProjectError(
                        "HOCUS462",
                        "A control editor bare candidate is shadowed.",
                        details={"specifier": bare},
                    )
                output[bare] = record
                break
            relative = _relative_specifier(importer_parent, path)
            if self._selected_relative(relative) != record.source_path:
                raise ProjectError(
                    "HOCUS462", "A control editor relative candidate changed identity.",
                )
            output.setdefault(relative, record)
        return sorted(output.items(), key=lambda item: (item[0].casefold(), item[0]))

    def digest_for_uri(self, uri: str) -> str | None:
        if uri == self.source_uri:
            return self.source_digest
        loaded = self.loaded_by_uri.get(uri)
        return loaded.digest if loaded is not None else None

    def finish(self) -> None:
        self._cancel()
        cancelled = self.cancelled
        self.cancelled = None
        try:
            self._finish_without_cancellation()
        finally:
            self.cancelled = cancelled

    def _finish_without_cancellation(self) -> None:
        refreshed = ProjectContext.load(self.root, validate_lock=True)
        _require_local_editor_project(refreshed)
        if _project_pins(refreshed) != _project_pins(self.context):
            raise ProjectError(
                "HOCUS428", "Control editor project, lock, catalog, or policy changed.",
            )
        _validate_project_roots(refreshed, self.root)
        self._recheck_subject(refreshed)
        for loaded in self.loaded_by_uri.values():
            current = _read_bounded_stable(
                loaded.path, self.limits.source_bytes_per_file,
                "HOCUS461", "HocusScript control editor module",
            )
            if current != loaded.raw:
                raise ProjectError(
                    "HOCUS428", "Control editor module changed during the request.",
                    details={"sourceUri": loaded.uri},
                )
        initial_decisions = len(self.decisions)
        for importer, specifier, expected in tuple(self.decisions):
            if self.select_import(importer, specifier) != expected:
                raise ProjectError(
                    "HOCUS428", "Control editor import winner changed during the request.",
                )
        del self.decisions[initial_decisions:]

    def _validate_dependencies(
        self,
        importer: Path,
        syntax: SyntaxSource,
        expected: tuple[str, ...],
    ) -> None:
        dependencies: list[str] = []
        for declaration in syntax.imports:
            target = self.select_import(importer, declaration.specifier)
            relative = target.relative_to(self.root).as_posix()
            uri = _project_uri(self.context.uid or "", relative)
            lock = self.lock_by_uri.get(uri)
            _require_editor_lock(
                lock,
                self.context.uid or "",
                relative,
                self.context.language_version,
            )
            dependencies.append(uri)
        if tuple(sorted(dependencies)) != expected or len(set(dependencies)) != len(dependencies):
            raise ProjectError(
                "HOCUS462",
                "Control editor module declarations do not match locked dependencies.",
            )

    def _selected_relative(self, specifier: str) -> str:
        return self.select_import(
            self.current_path, specifier,
        ).relative_to(self.root).as_posix()

    def _select_bare(self, specifier: str) -> Path:
        for directory in self.context.module_directories:
            candidate = directory / specifier
            if not _lexically_occupied(candidate):
                continue
            selected = self._contained_candidate(
                candidate, "bare control editor import",
            )
            try:
                selected.relative_to(directory.resolve(strict=True))
            except ValueError as exc:
                raise ProjectError(
                    "HOCUS460",
                    "Bare control editor import escaped its configured root.",
                ) from exc
            return selected
        raise ProjectError(
            "HOCUS462",
            "Bare control editor import was not found in module_directories.",
            details={"specifier": specifier},
        )

    def _contained_candidate(self, candidate: Path, label: str) -> Path:
        _reject_reparse_components(candidate, self.root)
        _require_exact_windows_casing(candidate, self.root)
        return _canonical_file(candidate, self.root, label)

    def _recheck_subject(self, refreshed: ProjectContext) -> None:
        if not self.saved:
            _subject_path(refreshed, self.relative, require_file=False)
            return
        if _subject_path(refreshed, self.relative, require_file=True) != self.current_path:
            raise ProjectError(
                "HOCUS428", "Control editor subject identity changed during the request.",
            )
        current = _read_bounded_stable(
            self.current_path, self.limits.source_bytes_per_file,
            "HOCUS461", "HocusScript control editor subject",
        )
        if module_source_digest(current) != self.initial_saved_digest:
            raise ProjectError(
                "HOCUS428", "Control editor subject changed during the request.",
            )

    def _cancel(self) -> None:
        if self.cancelled is None:
            return
        try:
            cancelled = self.cancelled()
        except Exception as exc:
            raise ProjectError(
                "HOCUS465", "Control editor cancellation callback failed.",
                details={"errorType": type(exc).__name__},
            ) from exc
        if type(cancelled) is not bool:
            raise ProjectError(
                "HOCUS465", "Control editor cancellation callback must return bool.",
            )
        if cancelled:
            raise ProjectError("HOCUS465", "Control editor request was cancelled.")


def complete_control_path(
    project_directory: str | Path,
    current_path: str | Path,
    offset: int,
    *,
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _complete(
        project_directory, relative, source, offset,
        limit=limit, cancelled=cancelled, saved=True,
    )


def complete_control_project_source(
    project_directory: str | Path,
    current_path: str | Path,
    source: str,
    offset: int,
    *,
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    return _complete(
        project_directory, current_path, source, offset,
        limit=limit, cancelled=cancelled, saved=False,
    )


def definition_control_path(
    project_directory: str | Path,
    current_path: str | Path,
    offset: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    _check_cancelled(cancelled)
    relative, source = _read_saved_subject(project_directory, current_path)
    return _definition(
        project_directory, relative, source, offset,
        cancelled=cancelled, saved=True,
    )


def definition_control_project_source(
    project_directory: str | Path,
    current_path: str | Path,
    source: str,
    offset: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    return _definition(
        project_directory, current_path, source, offset,
        cancelled=cancelled, saved=False,
    )


def _complete(
    project_directory,
    current_path,
    source,
    offset,
    *,
    limit,
    cancelled,
    saved,
) -> ProjectCompletionResult:
    _validate_request(source, offset, limit)
    session = _ControlProjectEditorSession(
        project_directory, current_path, source,
        cancelled=cancelled, saved=saved,
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
        session.source_uri, session.source_digest, session.subject_lock_state,
        offset, context, items, session.pins, incomplete,
    )


def _definition(
    project_directory,
    current_path,
    source,
    offset,
    *,
    cancelled,
    saved,
) -> ProjectDefinitionResult:
    _validate_request(source, offset, MAX_PROJECT_EDITOR_ITEMS)
    session = _ControlProjectEditorSession(
        project_directory, current_path, source,
        cancelled=cancelled, saved=saved,
    )
    syntax = _parse_current(
        source,
        session.source_uri,
        session.context.language_version,
    )
    items: tuple[ProjectDefinitionItem, ...] = ()
    if syntax is not None:
        views = session.import_views(syntax)
        target = definition_at(source, syntax, offset, views)
        if target is not None:
            digest = session.digest_for_uri(target.source_uri)
            if digest is not None:
                items = (
                    ProjectDefinitionItem(
                        target.name, target.kind, target.source_uri,
                        digest, target.span,
                    ),
                )
    session.finish()
    return ProjectDefinitionResult(
        session.source_uri, session.source_digest, session.subject_lock_state,
        offset, items, session.pins,
    )


def _completion_values(
    session: _ControlProjectEditorSession,
    source: str,
    offset: int,
):
    before = source[:offset]
    masked = _mask_non_import_text(before)
    if re.search(r"\bhocus\s+[0-9.]*$", masked):
        return "language_version", [
            (
                session.context.language_version,
                "value",
                session.context.language_version,
                "control language version",
                None,
                None,
                None,
            ),
        ]
    if _active_import_path(masked):
        return "import_path", [
            (value, "module_path", value, record.module_uri, None, None, None)
            for value, record in session.import_path_candidates()
        ]
    clause = _active_import_clause(source, offset)
    if clause is not None and offset <= clause[2]:
        module = _load_declared_import(session, clause[0], clause[1])
        assert module.syntax.module is not None
        name = module.syntax.module.name
        return "imported_module_name", [
            (name, "module", name, module.uri, None, None, None),
        ]
    if _active_use_module(masked):
        values = []
        for imported, local, specifier, *_ in _imports(source):
            module = _load_declared_import(session, imported, specifier)
            values.append(
                (local, "module", local, module.uri, None, None, None),
            )
        return "use_module", values
    call = _active_use_call(masked, len(masked))
    if call is not None:
        return "named_argument", _argument_completions(session, source, call)
    node_types = _node_type_completions(session.catalog, before)
    if node_types is not None:
        return "node_type", node_types
    parameters = _node_parameter_completions(session.catalog, before)
    if parameters is not None:
        return "parameter_name", parameters
    syntax = _parse_completion_source(
        source,
        offset,
        session.source_uri,
        session.context.language_version,
    )
    if syntax is None:
        return "none", []
    views = session.import_views(syntax)
    if re.search(
        r"\byield\s+(?:[A-Za-z_][A-Za-z0-9_]*)?$",
        masked,
    ):
        return "parameter_name", [
            _scope_member_item(item) for item in yield_names_at(
                source, syntax, offset, views,
            )
        ]
    member = re.search(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)?$",
        masked,
    )
    if member is not None:
        bindings = {
            item.name: item for item in scope_at(source, syntax, offset, views)
        }
        binding = bindings.get(member.group(1))
        return "instance_export", (
            [_scope_member_item(item) for item in binding.members]
            if binding is not None else []
        )
    return "none", []


def _argument_completions(session, source, call):
    local, existing = call
    imported = _import_for_local(source, local)
    if imported is None:
        return []
    module = _load_declared_import(session, imported[0], imported[2])
    root = module.syntax.module
    assert root is not None
    return [
        (
            item.name, "parameter", item.name + " = ",
            f"{item.type_name} {'required' if item.default is None else 'optional'}",
            item.default is None, item.type_name, _literal_default(item.default),
        )
        for item in root.parameters
        if item.name not in existing
    ]


def _node_type_completions(
    catalog: CatalogSnapshot,
    before: str,
):
    match = re.search(
        r"\bnode\s+[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\s*@id\s*\(\s*\"[^\"]+\"\s*\))?\s*:\s*"
        r"(\")?[A-Za-z0-9_:.-]*$",
        before,
    )
    if match is None:
        return None
    return [
        (label, kind, insert, detail, None, None, None)
        for label, kind, insert, detail, _documentation
        in _operator_candidates(
            catalog, _category(before), quoted=match.group(1) is not None,
        )
    ]


def _node_parameter_completions(
    catalog: CatalogSnapshot,
    before: str,
):
    active = _active_node(before, catalog)
    if active is None or not _parameter_name_position(before):
        return None
    _, operator = active
    body = _active_node_body(before)
    if body is None:
        return None
    authored = set(re.findall(
        r"(?:^|[;{}\n])\s*([A-Za-z_][A-Za-z0-9_]*)\s*=",
        body,
    ))
    values = []
    for parameter in operator.parameters:
        if not parameter.assignable:
            continue
        for token in (parameter.token, *parameter.tuple_names):
            if token in authored:
                continue
            values.append(_catalog_parameter_item(token, parameter))
    return values


def _catalog_parameter_item(
    token: str,
    parameter: ParameterDefinition,
):
    detail = f"{parameter.label}: {parameter.value_type}"
    return (
        token, "parameter", f"{token} = ", detail,
        None, parameter.value_type, None,
    )


def _scope_member_item(item: EditorScopeMember):
    return (
        item.name, item.kind, item.name, item.type_name,
        None, item.type_name, None,
    )


def _completion_prefix(source: str, offset: int, context: str):
    if context == "node_type":
        match = re.search(r"[A-Za-z0-9_:.-]*$", source[:offset])
        return (match.group(0), match.start()) if match else ("", offset)
    return _context_prefix(source, offset, context)


def _parse_current(
    source: str,
    uri: str,
    language_version: str,
) -> SyntaxSource | None:
    try:
        syntax = parse_syntax(source, uri)
    except (HocusSourceError, TypeError, ValueError, RecursionError):
        return None
    if (
        syntax.version is None
        or syntax.version.value != language_version
        or (syntax.graph is None) == (syntax.module is None)
    ):
        return None
    return syntax


def _parse_completion_source(
    source: str,
    offset: int,
    uri: str,
    language_version: str,
) -> SyntaxSource | None:
    syntax = _parse_current(source, uri, language_version)
    if syntax is not None:
        return syntax
    yield_match = re.search(
        r"\byield\s+([A-Za-z_][A-Za-z0-9_]*)?$",
        source[:offset],
    )
    if yield_match is not None:
        suffix = " = 0;" if yield_match.group(1) else "__cursor = 0;"
        syntax = _parse_current(
            source[:offset] + suffix + source[offset:],
            uri,
            language_version,
        )
        if syntax is not None:
            return syntax
    match = re.search(
        r"\b[A-Za-z_][A-Za-z0-9_]*\.(?:[A-Za-z_][A-Za-z0-9_]*)?$",
        source[:offset],
    )
    if match is None:
        return None
    length = offset - match.start()
    replacement = "false".rjust(length)
    repaired = source[:match.start()] + replacement + source[offset:]
    return _parse_current(repaired, uri, language_version)


def _module_view(
    local_name: str,
    loaded: _LoadedControlEditorModule,
) -> ImportedModuleView:
    root = loaded.syntax.module
    assert root is not None
    parameters = tuple(
        EditorScopeMember(
            item.name, "parameter", item.type_name,
            loaded.uri, item.name_span,
        )
        for item in root.parameters
    )
    exports = tuple(
        EditorScopeMember(
            item.name, "export", item.type_name,
            loaded.uri, item.name_span,
        )
        for item in root.exports
    )
    return ImportedModuleView(
        root.name, local_name, loaded.uri, loaded.digest,
        root.name_span, parameters, exports,
    )


def _load_declared_import(
    session: _ControlProjectEditorSession,
    imported_name: str,
    specifier: str,
) -> _LoadedControlEditorModule:
    loaded = session.load_import(specifier)
    root = loaded.syntax.module
    if root is None or root.name != imported_name:
        raise ProjectError(
            "HOCUS462",
            "Imported module name does not match the locked module declaration.",
            details={"sourceUri": loaded.uri},
        )
    return loaded


def _require_local_editor_project(context: ProjectContext) -> None:
    _require_control_project(context)
    if context.external_aliases or any(
        record.external_alias is not None for record in context.locked_modules
    ):
        raise ProjectError(
            "HOCUS460",
            "Local control editor rejects external aliases and lock records.",
        )


def _require_editor_lock(
    lock,
    project_uid: str,
    relative: str,
    language_version: str,
) -> None:
    expected_uri = _project_uri(project_uid, relative)
    if (
        lock is None
        or lock.module_uri != expected_uri
        or lock.project_uid != project_uid
        or lock.source_path != relative
        or lock.language_version != language_version
        or lock.external_alias is not None
    ):
        raise ProjectError(
            "HOCUS462",
            "Control editor import is not an exact local v4 lock record.",
            details={"moduleUri": expected_uri},
        )


def _read_saved_subject(
    project_directory: str | Path,
    current_path: str | Path,
) -> tuple[str, str]:
    relative_input = _relative_path_text(current_path)
    context = ProjectContext.load(project_directory, validate_lock=True)
    _require_local_editor_project(context)
    relative = _current_relative_path(context, relative_input)
    path = _subject_path(context, relative, require_file=True)
    raw = _read_bounded_stable(
        path, ControlResolverLimits().source_bytes_per_file,
        "HOCUS461", "HocusScript control editor subject",
    )
    try:
        return relative, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS466", "Control editor subject must be valid UTF-8.",
        ) from exc


def _active_import_path(masked: str) -> bool:
    return re.search(
        r'\bimport\s*\{\s*[A-Za-z_][A-Za-z0-9_]*'
        r'(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\}\s*'
        r'from\s+"([^"\n]*)$',
        masked,
    ) is not None


def _active_use_module(masked: str) -> bool:
    return re.search(
        r"\buse\s+[A-Za-z_][A-Za-z0-9_]*\s+"
        r"(?:@id\s*\([^)]*\)\s*)?=\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*)?$",
        masked,
    ) is not None


def _parameter_name_position(before: str) -> bool:
    boundary = max(before.rfind("\n"), before.rfind("{"), before.rfind(";"))
    tail = before[boundary + 1:]
    return re.fullmatch(
        r"\s*(?:[A-Za-z_][A-Za-z0-9_]*)?",
        tail,
    ) is not None


def _active_node_body(before: str) -> str | None:
    header = re.compile(
        r"\bnode\s+[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\s*@id\s*\(\s*\"[^\"]+\"\s*\))?\s*:\s*"
        r"(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_:]*)\s*\{",
    )
    for match in reversed(list(header.finditer(before))):
        body = before[match.end():]
        masked = _mask_literals_and_comments(body)
        if masked.count("}") <= masked.count("{"):
            return body
    return None


def _literal_default(value: Any) -> Any:
    return value.value if hasattr(value, "value") else None


__all__ = [
    "complete_control_path",
    "complete_control_project_source",
    "definition_control_path",
    "definition_control_project_source",
]
