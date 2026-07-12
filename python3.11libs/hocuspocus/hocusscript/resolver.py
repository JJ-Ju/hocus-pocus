"""Explicit-project, read-only native resolver for HocusScript 0.2 modules."""

from __future__ import annotations

from pathlib import Path
from os import PathLike, fspath
import os
from typing import Callable
from urllib.parse import quote

from .diagnostics import HocusSourceError
from .module_paths import is_literal_import_specifier
from .parser import parse_syntax
from .project import (
    LockVerificationResult,
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    _is_contained,
    _portable_path_key,
    _read_bounded_stable,
    _validate_relative_artifact_path,
    verify_project_lock,
)
from .resolved_modules import (
    ModuleResolutionError,
    ModuleSourceEnvelope,
    ResolvedImport,
    ResolvedModuleDag,
    ResolvedModuleLimits,
    module_interface_digest,
    _validate_limits,
    validate_resolved_module_dag,
)


def resolve_project_module_dag(
    project_directory: str | Path,
    entry_source_path: str | PathLike[str],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ResolvedModuleDag:
    """Resolve one explicit v3 project entry without ambient path fallback or writes.

    This same-user CLI/editor boundary uses bounded stat-read-stat file identity checks
    and rejects symlink/junction/reparse components; it is not a hostile multi-user
    filesystem sandbox.
    """
    project_text = _validate_project_directory(project_directory)
    authored_entry = entry_source_path
    try:
        entry_source_path = fspath(entry_source_path)
    except TypeError as exc:
        raise ProjectError("HOCUS460", "entry_source_path must be a relative string path.") from exc
    if not isinstance(entry_source_path, str):
        raise ProjectError("HOCUS460", "entry_source_path must be a relative string path.")
    if not isinstance(authored_entry, str):
        path_value = Path(entry_source_path)
        if path_value.is_absolute() or path_value.drive:
            raise ProjectError("HOCUS460", "entry_source_path must be project-relative.")
        entry_source_path = path_value.as_posix()
    try:
        _validate_relative_artifact_path(entry_source_path, "entry_source_path", code="HOCUS460")
    except ProjectError:
        raise
    if not entry_source_path.endswith(".hocus"):
        raise ProjectError("HOCUS460", "entry_source_path must identify a .hocus file.")
    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    _cancel(cancelled)
    context = ProjectContext.load(project_text, validate_lock=True)
    _cancel(cancelled)
    verification = verify_project_lock(project_text)
    _cancel(cancelled)
    if (
        context.manifest_version != 3 or context.language_version != "0.2"
        or context.uid != verification.project_uid
        or context.manifest_digest != verification.manifest_digest
        or context.lock_digest != verification.lock_digest
        or context.locked_modules != verification.modules
    ):
        raise ProjectError("HOCUS452", "Native module resolution requires one stable verified v3 lock.")
    root = context.root.resolve(strict=True)
    _reject_reparse_components(root / entry_source_path, root)
    _require_exact_windows_casing(root / entry_source_path, root)
    entry = _canonical_file(root / entry_source_path, root, "entry source")
    if not any(_is_contained(entry, directory.resolve(strict=True)) for directory in context.source_directories):
        raise ProjectError("HOCUS460", "Entry source must be contained by a configured source directory.")
    entry_relative = entry.relative_to(root).as_posix()
    if entry_relative != entry_source_path:
        raise ProjectError("HOCUS460", "Entry path must identify its canonical project-relative file.")
    entry_uri = _project_uri(verification.project_uid, entry_relative)
    entry_bytes = _read_source(entry, selected_limits, cancelled)
    entry_syntax = _parse(entry_bytes, entry_uri, graph=True)

    lock_by_uri = {record.module_uri: record for record in verification.modules}
    envelopes: dict[str, ModuleSourceEnvelope] = {}
    states: dict[str, str] = {}
    portable_paths = {_portable_path_key(entry_relative)}
    aggregate = len(entry_bytes)
    decisions: list[tuple[Path, str, Path]] = []
    if len(context.module_directory_paths) != len(context.module_directories):
        raise ProjectError("HOCUS452", "Verified project lost ordered module-directory provenance.")
    for authored_root in context.module_directory_paths:
        _reject_reparse_components(root / authored_root, root)
        _require_exact_windows_casing(root / authored_root, root)

    def select_target(importer: Path, specifier: str) -> Path:
        if specifier.startswith(("./", "../")):
            candidate = importer.parent / specifier
            _reject_reparse_components(candidate, root)
            _require_exact_windows_casing(candidate, root)
            target = _canonical_file(candidate, root, "relative module import")
            return target
        for directory in context.module_directories:
            _cancel(cancelled)
            candidate = directory / specifier
            if _lexically_occupied(candidate):
                _reject_reparse_components(candidate, root)
                _require_exact_windows_casing(candidate, root)
                target = _canonical_file(candidate, root, "bare module import")
                if not _is_contained(target, directory.resolve(strict=True)):
                    raise ProjectError("HOCUS460", "Bare module import escapes its configured module directory.")
                return target
        raise ProjectError("HOCUS462", "Bare module import was not found in ordered module_directories.",
                           details={"specifier": specifier})

    def resolve_import(importer: Path, declaration) -> tuple[ResolvedImport, ModuleLockRecord, Path]:
        specifier = declaration.specifier
        if not is_literal_import_specifier(specifier) or specifier.startswith("@"):
            raise ProjectError("HOCUS460", "External or nonportable imports are disabled in Batch C.")
        target = select_target(importer, specifier)
        decisions.append((importer, specifier, target))
        relative = target.relative_to(root).as_posix()
        uri = _project_uri(verification.project_uid, relative)
        locked = lock_by_uri.get(uri)
        if locked is None or locked.external_alias is not None:
            raise ProjectError("HOCUS462", "Resolved module does not match a same-project verified lock record.",
                               details={"moduleUri": uri})
        return (
            ResolvedImport(
                declaration.specifier, declaration.imported_name, declaration.local_name,
                uri, declaration.span,
            ),
            locked,
            target,
        )

    def visit(locked: ModuleLockRecord, path: Path, depth: int) -> None:
        nonlocal aggregate
        _cancel(cancelled)
        if depth > selected_limits.import_depth:
            raise ModuleResolutionError("HOCUS464", "Native module closure exceeds importDepth.")
        state = states.get(locked.module_uri)
        if state == "visiting":
            raise ModuleResolutionError("HOCUS463", "Native module imports contain a cycle.")
        if state == "done":
            return
        if len(envelopes) >= selected_limits.module_files:
            raise ModuleResolutionError("HOCUS464", "Native module closure exceeds moduleFiles.")
        states[locked.module_uri] = "visiting"
        relative = path.relative_to(root).as_posix()
        if locked.source_path != relative or locked.module_uri != _project_uri(verification.project_uid, relative):
            raise ProjectError("HOCUS462", "Resolved physical module conflicts with its verified lock identity.")
        key = _portable_path_key(relative)
        if key in portable_paths:
            raise ProjectError("HOCUS462", "Resolved files alias after portable path normalization.")
        portable_paths.add(key)
        source = _read_source(path, selected_limits, cancelled)
        aggregate += len(source)
        if aggregate > selected_limits.aggregate_source_bytes:
            raise ModuleResolutionError("HOCUS464", "Native source closure exceeds aggregateSourceBytes.")
        syntax = _parse(source, locked.module_uri, graph=False)
        imports: list[ResolvedImport] = []
        targets: list[tuple[ModuleLockRecord, Path]] = []
        for declaration in syntax.imports:
            _cancel(cancelled)
            resolved, target_lock, target_path = resolve_import(path, declaration)
            imports.append(resolved)
            targets.append((target_lock, target_path))
        envelope = ModuleSourceEnvelope(locked.module_uri, source, tuple(imports))
        envelopes[locked.module_uri] = envelope
        for target_lock, target_path in targets:
            visit(target_lock, target_path, depth + 1)
        states[locked.module_uri] = "done"

    entry_imports: list[ResolvedImport] = []
    entry_targets: list[tuple[ModuleLockRecord, Path]] = []
    for declaration in entry_syntax.imports:
        _cancel(cancelled)
        resolved, target_lock, target_path = resolve_import(entry, declaration)
        entry_imports.append(resolved)
        entry_targets.append((target_lock, target_path))
    for target_lock, target_path in entry_targets:
        visit(target_lock, target_path, 1)

    module_directories = list(context.module_directory_paths)
    policy = {
        "schemaVersion": 1,
        "kind": "native_project_v1",
        "projectMode": "same_project_only",
        "relativeResolution": "importer_relative_project_contained",
        "moduleDirectories": module_directories,
        "bareResolution": "ordered_first_occupied_fail_closed",
        "externalAliases": False,
        "casePolicy": "portable",
        "linkPolicy": "reject_reparse",
    }
    for importer, specifier, selected in decisions:
        _cancel(cancelled)
        if select_target(importer, specifier) != selected:
            raise ProjectError("HOCUS428", "Import resolution changed while sources were being read.",
                               details={"specifier": specifier})
    return validate_resolved_module_dag(
        tuple(envelopes.values()),
        lock_verification=LockVerificationResult(
            verification.project_uid, verification.manifest_digest,
            verification.lock_digest, verification.modules,
        ),
        entry_source_uri=entry_uri,
        entry_source=entry_bytes,
        entry_imports=tuple(entry_imports),
        resolver_policy=policy,
        resolver_policy_digest=module_interface_digest(policy),
        limits=selected_limits,
        cancelled=cancelled,
    )


def _canonical_file(path: Path, root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ProjectError("HOCUS462", f"Could not resolve {label}: {exc}", details={"path": str(path)}) from exc
    if not resolved.is_file() or not _is_contained(resolved, root):
        raise ProjectError("HOCUS460", f"{label.capitalize()} must be a contained regular file.",
                           details={"path": str(resolved)})
    return resolved


def _validate_project_directory(value: str | PathLike[str]) -> str:
    if value is None or isinstance(value, str) and not value.strip():
        raise ProjectError("HOCUS460", "An explicit project_directory is required.")
    try:
        text = fspath(value)
    except TypeError as exc:
        raise ProjectError("HOCUS460", "project_directory must be an explicit string path.") from exc
    if not isinstance(text, str) or not text.strip():
        raise ProjectError("HOCUS460", "project_directory must be an explicit string path.")
    if text.casefold().startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        raise ProjectError("HOCUS460", "Windows device-namespace project roots are forbidden.")
    return text


def _lexically_occupied(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ProjectError(
            "HOCUS460", "Could not inspect the first matching module candidate.",
            details={"path": str(path), "errorType": type(exc).__name__},
        ) from exc


def _lexical_parts(path: Path, root: Path) -> tuple[Path, tuple[str, ...]] | None:
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        return None
    return root, relative.parts


def _reject_reparse_components(path: Path, root: Path) -> None:
    lexical = _lexical_parts(path, root)
    if lexical is None:
        return
    current, parts = lexical
    for part in parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ProjectError("HOCUS460", "Could not inspect a source path component.",
                               details={"path": str(current)}) from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        if current.is_symlink() or attributes & 0x400:
            raise ProjectError("HOCUS460", "Symlink, junction, and reparse source paths are disabled.",
                               details={"path": str(current)})


def _require_exact_windows_casing(path: Path, root: Path) -> None:
    if os.name != "nt":
        return
    lexical = _lexical_parts(path, root)
    if lexical is None:
        return
    current, parts = lexical
    for part in parts:
        try:
            names = [child.name for child in current.iterdir()]
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProjectError("HOCUS460", "Could not verify exact source path casing.",
                               details={"path": str(current)}) from exc
        if part not in names:
            if any(name.casefold() == part.casefold() for name in names):
                raise ProjectError("HOCUS460", "Source path casing does not match the on-disk spelling.",
                                   details={"path": str(path)})
            if _lexically_occupied(current / part):
                raise ProjectError("HOCUS460", "Alternate on-disk path aliases are forbidden.",
                                   details={"path": str(path)})
            return
        current /= part


def _read_source(path: Path, limits: ResolvedModuleLimits, cancelled) -> bytes:
    _cancel(cancelled)
    raw = _read_bounded_stable(path, limits.source_bytes_per_file, "HOCUS461", "HocusScript source")
    _cancel(cancelled)
    return raw


def _parse(source: bytes, uri: str, *, graph: bool):
    try:
        syntax = parse_syntax(source.decode("utf-8"), uri)
    except (UnicodeDecodeError, HocusSourceError) as exc:
        raise ProjectError("HOCUS466", "Native HocusScript source failed strict 0.2 parsing.",
                           details={"sourceUri": uri}) from exc
    expected = syntax.graph is not None and syntax.module is None if graph else (
        syntax.module is not None and syntax.graph is None
    )
    if syntax.version is None or syntax.version.value != "0.2" or not expected:
        raise ProjectError("HOCUS466", "Native source has the wrong language version or root kind.")
    return syntax


def _project_uri(project_uid: str, relative: str) -> str:
    return f"hocus-project://{project_uid}/{quote(relative, safe='/-._~')}"


def _cancel(callback: Callable[[], bool] | None) -> None:
    if callback is None:
        return
    try:
        value = callback()
    except Exception as exc:
        raise ModuleResolutionError("HOCUS465", "Cancellation callback failed.",
                                    details={"errorType": type(exc).__name__}) from exc
    if type(value) is not bool:
        raise ModuleResolutionError("HOCUS465", "Cancellation callback must return bool.")
    if value:
        raise ModuleResolutionError("HOCUS465", "Native module resolution was cancelled.")
