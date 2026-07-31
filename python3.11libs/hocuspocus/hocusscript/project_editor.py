"""Read-only project-aware completion and definition support for HocusScript 0.2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote

from .diagnostics import HocusSourceError, SourcePosition, SourceSpan
from .parser import parse_syntax
from .project import (
    ProjectContext,
    ProjectError,
    _read_bounded_stable,
    _validate_relative_artifact_path,
)
from .resolved_modules import (
    ResolvedModuleLimits,
    _module_interface,
    module_interface_digest,
    module_source_digest,
)
from .resolver import (
    _canonical_file,
    _project_module_resolver_policy,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _select_project_module_target,
)
from .syntax import NodeDecl, ParamRefExpr, SymbolRefExpr, UseDecl


PROJECT_EDITOR_INTERFACE_VERSION = "1.0"
MAX_PROJECT_EDITOR_ITEMS = 200


@dataclass(frozen=True, slots=True)
class ProjectEditorPins:
    project_uid: str
    manifest_digest: str
    lock_digest: str
    catalog_content_digest: str
    catalog_fingerprint: str
    resolver_policy_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "projectUid": self.project_uid,
            "manifestDigest": self.manifest_digest,
            "lockDigest": self.lock_digest,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "resolverPolicyDigest": self.resolver_policy_digest,
        }


@dataclass(frozen=True, slots=True)
class ProjectCompletionItem:
    label: str
    kind: str
    insert_text: str
    replacement_span: SourceSpan
    detail: str | None = None
    required: bool | None = None
    type_name: str | None = None
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "insertText": self.insert_text,
            "replacementSpan": self.replacement_span.to_dict(),
            "detail": self.detail,
            "required": self.required,
            "type": self.type_name,
            "default": self.default,
            "sortText": self.label.casefold(),
        }


@dataclass(frozen=True, slots=True)
class ProjectCompletionResult:
    source_uri: str
    source_digest: str
    subject_lock_state: str
    offset: int
    context: str
    items: tuple[ProjectCompletionItem, ...]
    pins: ProjectEditorPins
    is_incomplete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceVersion": PROJECT_EDITOR_INTERFACE_VERSION,
            "offsetEncoding": "unicode_code_points",
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "subjectLockState": self.subject_lock_state,
            "offset": self.offset,
            "context": self.context,
            "pins": self.pins.to_dict(),
            "isIncomplete": self.is_incomplete,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class ProjectDefinitionItem:
    name: str
    kind: str
    source_uri: str
    source_digest: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "span": self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProjectDefinitionResult:
    source_uri: str
    source_digest: str
    subject_lock_state: str
    offset: int
    items: tuple[ProjectDefinitionItem, ...]
    pins: ProjectEditorPins

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceVersion": PROJECT_EDITOR_INTERFACE_VERSION,
            "offsetEncoding": "unicode_code_points",
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "subjectLockState": self.subject_lock_state,
            "offset": self.offset,
            "pins": self.pins.to_dict(),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(slots=True)
class _LoadedModule:
    specifier: str
    path: Path
    uri: str
    raw: bytes
    digest: str
    syntax: Any
    interface: dict[str, Any]


class _ProjectEditorSession:
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
        if (
            self.context.manifest_version != 3
            or self.context.language_version != "0.2"
            or self.context.uid is None
            or self.context.manifest_digest is None
            or self.context.lock_digest is None
            or self.context.catalog_content_digest is None
            or self.context.catalog_fingerprint is None
        ):
            raise ProjectError("HOCUS480", "Project editor support requires one fully pinned schema v3 project.")
        self.relative = _current_relative_path(self.context, relative_input)
        self.current_path = _subject_path(self.context, self.relative, require_file=saved)
        self.source_uri = _project_uri(self.context.uid, self.relative)
        self.raw = _source_bytes(source)
        self.source = source
        self.source_digest = module_source_digest(self.raw)
        self.saved = saved
        self.initial_saved_digest = self.source_digest if saved else None
        self.pins = _pins(self.context)
        locked = _locked_by_uri(self.context).get(self.source_uri)
        self.subject_lock_state = (
            "unlocked" if locked is None else
            "matching" if locked.content_digest == self.source_digest else
            "modified"
        )
        self.limits = ResolvedModuleLimits()
        self.aggregate_source_bytes = len(self.raw)
        if self.aggregate_source_bytes > self.limits.aggregate_source_bytes:
            raise ProjectError("HOCUS464", "Project editor aggregateSourceBytes budget was exceeded.")
        self.loaded: dict[str, _LoadedModule] = {}
        self.loaded_by_uri: dict[str, _LoadedModule] = {}
        self.decisions: list[tuple[Path, str, Path]] = []

    def select_import(self, importer: Path, specifier: str) -> Path:
        selected = _select_project_module_target(
            self.context, importer, specifier, cancelled=self.cancelled,
        )
        self.decisions.append((importer, specifier, selected))
        return selected

    def load_import(self, specifier: str) -> _LoadedModule:
        cached = self.loaded.get(specifier)
        if cached is not None:
            return cached
        self._cancel()
        target = self.select_import(self.current_path, specifier)
        relative = target.relative_to(self.context.root).as_posix()
        uri = _project_uri(self.context.uid or "", relative)
        existing = self.loaded_by_uri.get(uri)
        if existing is not None:
            self.loaded[specifier] = existing
            return existing
        if len(self.loaded_by_uri) >= self.limits.module_files:
            raise ProjectError("HOCUS464", "Project editor moduleFiles budget was exceeded.")
        locked = _locked_by_uri(self.context).get(uri)
        raw, syntax = self._read_locked_module(target, relative, uri, locked)
        interface = _module_interface(syntax, ResolvedModuleLimits(), uri)
        if module_interface_digest(interface) != locked.interface_digest:
            raise ProjectError("HOCUS461", "Editor module interface does not match the verified lock.", details={"sourceUri": uri})
        self._validate_dependencies(syntax, target, uri, locked)
        loaded = _LoadedModule(specifier, target, uri, raw, locked.content_digest, syntax, interface)
        self.aggregate_source_bytes += len(raw)
        self.loaded[specifier] = loaded
        self.loaded_by_uri[uri] = loaded
        return loaded

    def _read_locked_module(self, target, relative, uri, locked):
        if locked is None or locked.external_alias is not None or locked.source_path != relative:
            raise ProjectError("HOCUS462", "Editor import is not a locked same-project module.")
        raw = _read_bounded_stable(
            target, self.limits.source_bytes_per_file, "HOCUS461", "HocusScript module",
        )
        if self.aggregate_source_bytes + len(raw) > self.limits.aggregate_source_bytes:
            raise ProjectError("HOCUS464", "Project editor aggregateSourceBytes budget was exceeded.")
        if module_source_digest(raw) != locked.content_digest:
            raise ProjectError("HOCUS461", "Editor module bytes do not match the verified lock.", details={"sourceUri": uri})
        try:
            syntax = parse_syntax(raw.decode("utf-8"), uri)
        except (UnicodeDecodeError, HocusSourceError) as exc:
            raise ProjectError("HOCUS466", "Editor module failed strict language 0.2 parsing.", details={"sourceUri": uri}) from exc
        if syntax.version is None or syntax.version.value != "0.2" or syntax.module is None or syntax.graph is not None:
            raise ProjectError("HOCUS466", "Editor import must contain one language 0.2 module.", details={"sourceUri": uri})
        return raw, syntax

    def _validate_dependencies(self, syntax, target, uri, locked):
        dependencies = []
        lock_by_uri = _locked_by_uri(self.context)
        for declaration in syntax.imports:
            dependency_path = self.select_import(target, declaration.specifier)
            dependency_relative = dependency_path.relative_to(self.context.root).as_posix()
            dependency_uri = _project_uri(self.context.uid or "", dependency_relative)
            dependency_lock = lock_by_uri.get(dependency_uri)
            if (
                dependency_lock is None
                or dependency_lock.external_alias is not None
                or dependency_lock.source_path != dependency_relative
            ):
                raise ProjectError("HOCUS462", "Editor module dependency is not a locked same-project module.")
            dependencies.append(dependency_uri)
        if tuple(sorted(dependencies)) != locked.dependencies or len(set(dependencies)) != len(dependencies):
            raise ProjectError("HOCUS462", "Editor module declarations do not match locked dependencies.", details={"sourceUri": uri})
        return dependencies

    def finish(self) -> None:
        self._cancel()
        if self.saved:
            if _subject_path(self.context, self.relative, require_file=True) != self.current_path:
                raise ProjectError("HOCUS428", "Editor subject identity changed during the request.")
            current = _read_bounded_stable(
                self.current_path, ResolvedModuleLimits().source_bytes_per_file,
                "HOCUS461", "HocusScript editor subject",
            )
            if module_source_digest(current) != self.initial_saved_digest:
                raise ProjectError("HOCUS428", "Editor subject changed during the request.")
        else:
            # A dirty buffer does not authorize disk content, but its selected
            # project-relative identity must remain non-reparse and contained.
            _subject_path(self.context, self.relative, require_file=False)
        for loaded in self.loaded.values():
            self._cancel()
            current = _read_bounded_stable(
                loaded.path, ResolvedModuleLimits().source_bytes_per_file,
                "HOCUS461", "HocusScript module",
            )
            if module_source_digest(current) != loaded.digest:
                raise ProjectError("HOCUS428", "Editor module changed during the request.", details={"sourceUri": loaded.uri})
        for importer, specifier, selected in self.decisions:
            self._cancel()
            if _select_project_module_target(
                self.context, importer, specifier, cancelled=self.cancelled,
            ) != selected:
                raise ProjectError("HOCUS428", "Editor import winner changed during the request.")
        if _pins(ProjectContext.load(self.context.root, validate_lock=True)) != self.pins:
            raise ProjectError("HOCUS428", "Project editor pins changed during the request.")
        self._cancel()

    def _cancel(self) -> None:
        if self.cancelled is None:
            return
        try:
            value = self.cancelled()
        except Exception as exc:
            raise ProjectError("HOCUS465", "Project editor cancellation callback failed.", details={"errorType": type(exc).__name__}) from exc
        if type(value) is not bool:
            raise ProjectError("HOCUS465", "Project editor cancellation callback must return bool.")
        if value:
            raise ProjectError("HOCUS465", "Project editor request was cancelled.")


def complete_path(
    project_directory: str | Path,
    current_path: str | Path,
    offset: int,
    *,
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    _check_cancelled(cancelled)
    relative_input = _relative_path_text(current_path)
    context = ProjectContext.load(project_directory, validate_lock=True)
    relative = _current_relative_path(context, relative_input)
    path = _subject_path(context, relative, require_file=True)
    raw = _read_bounded_stable(path, ResolvedModuleLimits().source_bytes_per_file, "HOCUS461", "HocusScript editor subject")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError("HOCUS466", "Editor subject must be valid UTF-8.") from exc
    return _complete(project_directory, relative, source, offset, limit=limit, cancelled=cancelled, saved=True)


def complete_project_source(
    project_directory: str | Path,
    current_path: str | Path,
    source: str,
    offset: int,
    *,
    limit: int = MAX_PROJECT_EDITOR_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectCompletionResult:
    return _complete(project_directory, current_path, source, offset, limit=limit, cancelled=cancelled, saved=False)


def definition_path(
    project_directory: str | Path,
    current_path: str | Path,
    offset: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    _check_cancelled(cancelled)
    relative_input = _relative_path_text(current_path)
    context = ProjectContext.load(project_directory, validate_lock=True)
    relative = _current_relative_path(context, relative_input)
    path = _subject_path(context, relative, require_file=True)
    raw = _read_bounded_stable(path, ResolvedModuleLimits().source_bytes_per_file, "HOCUS461", "HocusScript editor subject")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError("HOCUS466", "Editor subject must be valid UTF-8.") from exc
    return _definition(project_directory, relative, source, offset, cancelled=cancelled, saved=True)


def definition_project_source(
    project_directory: str | Path,
    current_path: str | Path,
    source: str,
    offset: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectDefinitionResult:
    return _definition(project_directory, current_path, source, offset, cancelled=cancelled, saved=False)


def _complete(project_directory, current_path, source, offset, *, limit, cancelled, saved):
    _validate_request(source, offset, limit)
    session = _ProjectEditorSession(project_directory, current_path, source, cancelled=cancelled, saved=saved)
    context, values = _completion_values(session, source, offset)
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


def _definition(project_directory, current_path, source, offset, *, cancelled, saved):
    _validate_request(source, offset, MAX_PROJECT_EDITOR_ITEMS)
    session = _ProjectEditorSession(project_directory, current_path, source, cancelled=cancelled, saved=saved)
    items = tuple(_definition_values(session, source, offset))
    session.finish()
    return ProjectDefinitionResult(
        session.source_uri, session.source_digest, session.subject_lock_state,
        offset, items, session.pins,
    )


def _completion_values(session: _ProjectEditorSession, source: str, offset: int):
    before = source[:offset]
    masked_before = _mask_non_import_text(before)
    if re.search(r"\bhocus\s+[0-9.]*$", masked_before):
        return "language_version", [("0.2", "value", "0.2", "module language version", None, None, None)]
    import_path = re.search(
        r'\bimport\s*\{\s*[A-Za-z_][A-Za-z0-9_]*'
        r'(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\}\s*'
        r'from\s+"([^"\n]*)$',
        masked_before,
    )
    if import_path:
        return "import_path", [
            (value, "module_path", value, record.module_uri, None, None, None)
            for value, record in _import_path_candidates(session)
        ]
    import_clause = _active_import_clause(source, offset)
    if import_clause is not None and offset <= import_clause[2]:
        module = _load_declared_import(session, import_clause[0], import_clause[1])
        name = module.syntax.module.name
        return "imported_module_name", [(name, "module", name, module.uri, None, None, None)]
    use_module = re.search(r"\buse\s+[A-Za-z_][A-Za-z0-9_]*\s+(?:@id\s*\([^)]*\)\s*)?=\s*[A-Za-z_][A-Za-z0-9_]*$", masked_before)
    if use_module:
        values = []
        for imported, local, specifier, *_ in _imports(source):
            module = _load_declared_import(session, imported, specifier)
            values.append((local, "module", local, module.uri, None, None, None))
        return "use_module", values
    call = _active_use_call(masked_before, len(masked_before))
    if call is not None:
        values = _argument_completions(session, source, call)
        if values is not None:
            return "named_argument", values
    member = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)?$", masked_before)
    if member:
        return _member_completions(session, source, member.group(1))
    return "none", []


def _argument_completions(session, source, call):
    local, existing = call
    imported = _import_for_local(source, local)
    if imported is None:
        return None
    module = _load_declared_import(session, imported[0], imported[2])
    values = []
    for parameter in module.interface["parameters"]:
        if parameter["name"] in existing:
            continue
        required = not parameter["hasDefault"]
        values.append((
            parameter["name"], "parameter", parameter["name"] + " = ",
            f"{parameter['type']} {'required' if required else 'optional'}",
            required, parameter["type"], parameter["default"],
        ))
    return values


def _member_completions(session, source, symbol):
    if symbol == "param":
        return "parameter_name", [
            (item.name, "parameter", item.name, item.type_name, item.default is None, item.type_name, None)
            for item in _current_parameters(source, session.source_uri)
        ]
    use = _use_for_symbol(source, session.source_uri, symbol)
    if use is None:
        return "none", []
    imported = _import_for_local(source, use.module_name)
    if imported is None:
        return "none", []
    module = _load_declared_import(session, imported[0], imported[2])
    return "instance_export", [
        (item["name"], "export", item["name"], item["type"], None, item["type"], None)
        for item in module.interface["exports"]
    ]


def _definition_values(session: _ProjectEditorSession, source: str, offset: int):
    syntax = _parse_current(source, session.source_uri)
    if syntax is None:
        return []
    for declaration in syntax.imports:
        result = _definition_for_import(session, declaration, offset)
        if result:
            return result
    statements = syntax.root.statements
    for statement in statements:
        result = _definition_for_statement(
            session, syntax, statements, statement, offset,
        )
        if result:
            return result
    return []


def _definition_for_import(session, declaration, offset):
    if not (
        _contains(declaration.specifier_span, offset)
        or _contains(declaration.imported_name_span, offset)
        or _contains(declaration.local_name_span, offset)
    ):
        return []
    module = _load_declared_import(
        session, declaration.imported_name, declaration.specifier,
    )
    return [_definition_item(
        module.syntax.module.name, "module", module.uri, module.digest,
        module.syntax.module.name_span,
    )]


def _definition_for_statement(session, syntax, statements, statement, offset):
    if isinstance(statement, UseDecl):
        result = _definition_for_use(session, syntax, statement, offset)
        if result:
            return result
    for expression in _statement_expressions(statement):
        result = _definition_for_expression(
            session, syntax, statements, expression, offset,
        )
        if result:
            return result
    return []


def _definition_for_use(session, syntax, statement, offset):
    declaration = next(
        (item for item in syntax.imports if item.local_name == statement.module_name),
        None,
    )
    if _contains(statement.module_name_span, offset) and declaration is not None:
        return [_definition_item(
            declaration.local_name, "import_alias", session.source_uri,
            session.source_digest, declaration.local_name_span,
        )]
    if declaration is None:
        return []
    module = _load_declared_import(
        session, declaration.imported_name, declaration.specifier,
    )
    for argument in statement.arguments:
        if not _contains(argument.name_span, offset):
            continue
        parameter = next(
            (item for item in module.syntax.module.parameters if item.name == argument.name),
            None,
        )
        if parameter is not None:
            return [_definition_item(
                parameter.name, "parameter", module.uri, module.digest,
                parameter.name_span,
            )]
    return []


def _statement_expressions(statement):
    if isinstance(statement, NodeDecl):
        sources = [
            item.source for item in statement.statements if hasattr(item, "source")
        ]
        values = [
            item.value for item in statement.statements if hasattr(item, "value")
        ]
        return sources + values
    if isinstance(statement, UseDecl):
        return [item.value for item in statement.arguments]
    return [statement.value] if hasattr(statement, "value") else []


def _definition_for_expression(session, syntax, statements, expression, offset):
    if isinstance(expression, ParamRefExpr):
        return _definition_for_parameter(session, syntax, expression, offset)
    if not isinstance(expression, SymbolRefExpr):
        return []
    declaration = next((
        item for item in statements
        if isinstance(item, (NodeDecl, UseDecl)) and item.symbol == expression.symbol
    ), None)
    if _contains(expression.symbol_span, offset) and declaration is not None:
        return [_definition_item(
            declaration.symbol, "symbol", session.source_uri,
            session.source_digest, declaration.symbol_span,
        )]
    if not _contains(expression.member_span, offset) or not isinstance(declaration, UseDecl):
        return []
    imported = next(
        (item for item in syntax.imports if item.local_name == declaration.module_name),
        None,
    )
    if imported is None:
        return []
    module = _load_declared_import(session, imported.imported_name, imported.specifier)
    exported = next(
        (item for item in module.syntax.module.exports if item.name == expression.member),
        None,
    )
    if exported is None:
        return []
    return [_definition_item(
        exported.name, "export", module.uri, module.digest, exported.name_span,
    )]


def _definition_for_parameter(session, syntax, expression, offset):
    if not _contains(expression.name_span, offset) or syntax.module is None:
        return []
    parameter = next(
        (item for item in syntax.module.parameters if item.name == expression.name),
        None,
    )
    if parameter is None:
        return []
    return [_definition_item(
        parameter.name, "parameter", session.source_uri, session.source_digest,
        parameter.name_span,
    )]


def _definition_item(name, kind, uri, digest, span):
    return ProjectDefinitionItem(name, kind, uri, digest, span)


def _load_declared_import(session: _ProjectEditorSession, imported_name: str, specifier: str) -> _LoadedModule:
    module = session.load_import(specifier)
    if module.syntax.module.name != imported_name:
        raise ProjectError(
            "HOCUS462",
            "Imported module name does not match the locked module declaration.",
            details={"sourceUri": module.uri},
        )
    return module


def _imports(source: str):
    """Recognize import declarations while excluding comments, code, and other strings."""
    pattern = re.compile(r'\bimport\s*\{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?\s*\}\s*from\s*"([^"\n]+)"')
    masked = _mask_non_import_text(source)
    imports = [
        (match.group(1), match.group(2) or match.group(1), match.group(3), match.start(), match.end())
        for match in pattern.finditer(masked)
    ]
    if len(imports) > ResolvedModuleLimits().module_files:
        raise ProjectError("HOCUS464", "Project editor import count exceeds moduleFiles.")
    return imports


def _mask_non_import_text(source: str) -> str:
    chars = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            chars[index:end] = " " * (end - index)
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end < 0 else end + 2
            for cursor in range(index, end):
                if source[cursor] != "\n":
                    chars[cursor] = " "
            index = end
            continue
        if source[index] in {'"', '`'}:
            cursor = _quoted_text_end(source, index)
            preserve = (
                source[index] == '"'
                and re.search(r"\bfrom\s*$", "".join(chars[:index])) is not None
            )
            if not preserve:
                for position in range(index, cursor):
                    if source[position] != "\n":
                        chars[position] = " "
            index = cursor
            continue
        index += 1
    return "".join(chars)


def _quoted_text_end(source: str, index: int) -> int:
    delimiter = source[index]
    cursor = index + 1
    escaped = False
    while cursor < len(source):
        char = source[cursor]
        if char == delimiter and not escaped:
            return cursor + 1
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
        cursor += 1
    return cursor


def _active_import_clause(source: str, offset: int):
    for imported, local, specifier, start, end in _imports(source):
        from_pos = source.find("from", start, end)
        if start <= offset <= from_pos:
            return imported, specifier, from_pos
    return None


def _import_for_local(source: str, local: str):
    return next((item for item in _imports(source) if item[1] == local), None)


def _active_use_call(source: str, offset: int):
    before = source[:offset]
    match = re.search(r"\buse\s+[A-Za-z_][A-Za-z0-9_]*\s+@id\s*\([^)]*\)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)$", before)
    if match is None:
        return None
    existing = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=", match.group(2)))
    return match.group(1), existing


def _use_for_symbol(source: str, uri: str, symbol: str):
    syntax = _parse_current(source, uri)
    if syntax is None:
        return None
    return next((item for item in syntax.root.statements if isinstance(item, UseDecl) and item.symbol == symbol), None)


def _current_parameters(source: str, uri: str):
    syntax = _parse_current(source, uri)
    return syntax.module.parameters if syntax is not None and syntax.module is not None else ()


def _parse_current(source: str, uri: str):
    try:
        syntax = parse_syntax(source, uri)
    except HocusSourceError:
        return None
    if syntax.version is None or syntax.version.value != "0.2" or (syntax.graph is None) == (syntax.module is None):
        return None
    return syntax


def _import_path_candidates(session: _ProjectEditorSession):
    output = {}
    importer_parent = PurePosixPath(session.relative).parent
    for record in session.context.locked_modules:
        if record.external_alias is not None:
            continue
        path = PurePosixPath(record.source_path)
        for directory in session.context.module_directory_paths:
            directory_path = PurePosixPath(directory)
            try:
                bare = path.relative_to(directory_path).as_posix()
            except ValueError:
                continue
            selected = session.select_import(session.current_path, bare)
            if selected.relative_to(session.context.root).as_posix() != record.source_path:
                raise ProjectError(
                    "HOCUS462",
                    "A bare completion candidate is shadowed by a different first occupied module.",
                    details={"specifier": bare},
                )
            output[bare] = record
            break
        relative = _relative_specifier(importer_parent, path)
        selected = session.select_import(session.current_path, relative)
        if selected.relative_to(session.context.root).as_posix() != record.source_path:
            raise ProjectError("HOCUS462", "A relative completion candidate changed identity.")
        output.setdefault(relative, record)
    return sorted(output.items(), key=lambda item: (item[0].casefold(), item[0]))


def _relative_specifier(parent: PurePosixPath, target: PurePosixPath) -> str:
    parent_parts, target_parts = parent.parts, target.parts
    common = 0
    while common < min(len(parent_parts), len(target_parts)) and parent_parts[common] == target_parts[common]:
        common += 1
    value = "/".join([".."] * (len(parent_parts) - common) + list(target_parts[common:]))
    return value if value.startswith("../") else "./" + value


def _relative_path_text(value: str | Path) -> str:
    text = value.as_posix() if isinstance(value, Path) else str(value)
    try:
        _validate_relative_artifact_path(text, "current_path", code="HOCUS460")
    except (TypeError, ValueError) as exc:
        raise ProjectError("HOCUS460", "current_path must be a normalized project-relative path.") from exc
    if not text.endswith(".hocus"):
        raise ProjectError("HOCUS460", "current_path must identify a .hocus file.")
    return text


def _current_relative_path(context: ProjectContext, value: str | Path) -> str:
    relative = _relative_path_text(value)
    roots = [item.relative_to(context.root).as_posix() for item in (*context.source_directories, *context.module_directories)]
    if not any(root == "." or relative == root or relative.startswith(root + "/") for root in roots):
        raise ProjectError("HOCUS460", "current_path is outside configured source and module directories.")
    return relative


def _subject_path(context: ProjectContext, relative: str, *, require_file: bool) -> Path:
    candidate = context.root / PurePosixPath(relative)
    _reject_reparse_components(candidate, context.root)
    _require_exact_windows_casing(candidate, context.root)
    if require_file:
        return _canonical_file(candidate, context.root, "editor subject")
    try:
        candidate.lstat()
    except FileNotFoundError:
        return candidate
    except OSError as exc:
        raise ProjectError("HOCUS460", "Could not inspect the dirty editor subject.") from exc
    # Dirty buffers may represent a new file, but an occupied subject identity
    # must still be the exact contained regular file selected by compilation.
    return _canonical_file(candidate, context.root, "editor subject")


def _pins(context: ProjectContext) -> ProjectEditorPins:
    if None in (context.uid, context.manifest_digest, context.lock_digest, context.catalog_content_digest, context.catalog_fingerprint):
        raise ProjectError("HOCUS480", "Project editor pins are incomplete.")
    return ProjectEditorPins(
        context.uid, context.manifest_digest, context.lock_digest,
        context.catalog_content_digest, context.catalog_fingerprint,
        module_interface_digest(_project_module_resolver_policy(context)),
    )


def _locked_by_uri(context: ProjectContext):
    return {item.module_uri: item for item in context.locked_modules}


def _project_uri(uid: str, relative: str) -> str:
    return f"hocus-project://{uid}/{quote(relative, safe='/-._~')}"


def _source_bytes(source: str) -> bytes:
    if not isinstance(source, str):
        raise ProjectError("HOCUS460", "source must be a string.")
    try:
        raw = source.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProjectError("HOCUS466", "source must be valid UTF-8.") from exc
    if len(raw) > ResolvedModuleLimits().source_bytes_per_file:
        raise ProjectError("HOCUS464", "Editor source exceeds sourceBytesPerFile.")
    return raw


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is None:
        return
    try:
        value = cancelled()
    except Exception as exc:
        raise ProjectError(
            "HOCUS465",
            "Project editor cancellation callback failed.",
            details={"errorType": type(exc).__name__},
        ) from exc
    if type(value) is not bool:
        raise ProjectError("HOCUS465", "Project editor cancellation callback must return bool.")
    if value:
        raise ProjectError("HOCUS465", "Project editor request was cancelled.")


def _validate_request(source: str, offset: int, limit: int) -> None:
    _source_bytes(source)
    if type(offset) is not int or not 0 <= offset <= len(source):
        raise ProjectError("HOCUS460", "offset must be within source.")
    if type(limit) is not int or not 1 <= limit <= MAX_PROJECT_EDITOR_ITEMS:
        raise ProjectError("HOCUS460", f"limit must be between 1 and {MAX_PROJECT_EDITOR_ITEMS}.")


def _prefix(source: str, offset: int) -> tuple[str, int]:
    match = re.search(r"[A-Za-z_][A-Za-z0-9_.:/-]*$", source[:offset])
    return (match.group(0), match.start()) if match else ("", offset)


def _context_prefix(source: str, offset: int, context: str) -> tuple[str, int]:
    before = source[:offset]
    if context == "language_version":
        match = re.search(r"[0-9.]*$", before)
        return (match.group(0), match.start()) if match else ("", offset)
    if context in {"parameter_name", "instance_export"}:
        match = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", before)
        return (match.group(0), match.start()) if match else ("", offset)
    if context == "import_path":
        match = re.search(r'[^"\n]*$', before)
        return (match.group(0), match.start()) if match else ("", offset)
    return _prefix(source, offset)


def _position(source: str, offset: int) -> SourcePosition:
    prefix = source[:offset]
    newline = prefix.rfind("\n")
    return SourcePosition(offset, prefix.count("\n") + 1, offset - newline)


def _span(source: str, uri: str, start: int, end: int) -> SourceSpan:
    return SourceSpan(uri, _position(source, start), _position(source, end))


def _contains(span: SourceSpan, offset: int) -> bool:
    return span.start.offset <= offset <= span.end.offset
