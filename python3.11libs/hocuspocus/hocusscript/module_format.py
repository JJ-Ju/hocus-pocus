"""Native, read-only formatting for versioned HocusScript project files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from os import PathLike, fspath
from pathlib import Path
from typing import Any, Callable

from .compiler import MAX_SOURCE_BYTES
from .diagnostics import Diagnostic, HocusSourceError
from .formatter import format_syntax
from .parser import parse_syntax
from .project import (
    ProjectContext,
    ProjectError,
    _is_contained,
    _read_bounded_stable,
    _validate_relative_artifact_path,
)
from .resolver import (
    _canonical_file,
    _project_uri,
    _reject_reparse_components,
    _require_exact_windows_casing,
    _validate_project_directory,
)


class ModuleProjectFormatError(ValueError):
    """Typed failure at the native module-format integration boundary."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ModuleProjectFormatResult:
    """Host-path-free formatting result retaining a native path only for callers."""

    source_uri: str
    source_digest: str
    language_version: str
    root_kind: str | None
    changed: bool
    formatted_source: str | None
    diagnostics: tuple[Diagnostic, ...]
    native_source_path: str = field(repr=False, compare=False)

    @property
    def valid(self) -> bool:
        return self.formatted_source is not None and not any(
            item.severity == "error" for item in self.diagnostics
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "format",
            "valid": self.valid,
            "languageVersion": self.language_version,
            "sourceUri": self.source_uri,
            "sourceDigest": self.source_digest,
            "rootKind": self.root_kind,
            "changed": self.changed,
            "formattedSource": self.formatted_source,
            "diagnosticCount": len(self.diagnostics),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def format_project_module_path(
    project_directory: str | PathLike[str],
    source_path: str | PathLike[str],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleProjectFormatResult:
    """Canonically format one contained graph or module without reading its lock.

    This is a same-user native editor/CLI boundary. It rejects link/reparse paths
    and uses a bounded stat-read-stat snapshot, but it is not a privileged
    multi-user filesystem sandbox.
    """

    project_text = _validate_project_directory(project_directory)
    relative = _relative_source_path(source_path)
    _checkpoint(cancelled)
    project = ProjectContext.load(project_text, validate_lock=False)
    _checkpoint(cancelled)
    lane = (project.manifest_version, project.language_version)
    if lane not in {(3, "0.2"), (4, "0.3")} or project.uid is None:
        raise ProjectError(
            "HOCUS452",
            "Native formatting requires an explicit schema v3/0.2 or v4/0.3 project.",
        )

    root = project.root.resolve(strict=True)
    candidate = root / relative
    _reject_reparse_components(candidate, root)
    _require_exact_windows_casing(candidate, root)
    source = _canonical_file(candidate, root, "format source")
    allowed_directories = (*project.source_directories, *project.module_directories)
    if not any(_is_contained(source, directory.resolve(strict=True)) for directory in allowed_directories):
        raise ProjectError(
            "HOCUS460",
            "Format source must be contained by a configured source or module directory.",
        )
    canonical_relative = source.relative_to(root).as_posix()
    if canonical_relative != relative:
        raise ProjectError(
            "HOCUS460", "Format source path must use its canonical project-relative spelling."
        )

    _checkpoint(cancelled)
    raw = _read_bounded_stable(source, MAX_SOURCE_BYTES, "HOCUS461", "HocusScript source")
    _checkpoint(cancelled)
    # Do not retain a path that was redirected after the stable read.
    _reject_reparse_components(candidate, root)
    _require_exact_windows_casing(candidate, root)
    if _canonical_file(candidate, root, "format source") != source:
        raise ProjectError("HOCUS428", "Format source identity changed while it was being read.")

    source_uri = _project_uri(project.uid, canonical_relative)
    source_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS466",
            "Native HocusScript format source must be valid UTF-8.",
            details={"sourceUri": source_uri, "start": exc.start, "end": exc.end},
        ) from exc

    try:
        syntax = parse_syntax(text, source_uri)
    except HocusSourceError as exc:
        return ModuleProjectFormatResult(
            source_uri,
            source_digest,
            project.language_version,
            None,
            False,
            None,
            (exc.diagnostic,),
            str(source),
        )
    _checkpoint(cancelled)
    root_kind = "graph" if syntax.graph is not None and syntax.module is None else (
        "module" if syntax.module is not None and syntax.graph is None else None
    )
    if (
        syntax.version is None
        or syntax.version.value != project.language_version
        or root_kind is None
    ):
        diagnostic = Diagnostic(
            "error",
            "HOCUS466",
            "parse",
            f"Native formatting requires a hocus {project.language_version} graph or module source root.",
            syntax.span,
        )
        return ModuleProjectFormatResult(
            source_uri,
            source_digest,
            project.language_version,
            root_kind,
            False,
            None,
            (diagnostic,),
            str(source),
        )

    formatted = format_syntax(syntax)
    _checkpoint(cancelled)
    return ModuleProjectFormatResult(
        source_uri,
        source_digest,
        project.language_version,
        root_kind,
        formatted != text,
        formatted,
        (),
        str(source),
    )


def _relative_source_path(value: str | PathLike[str]) -> str:
    authored = value
    try:
        text = fspath(value)
    except TypeError as exc:
        raise ProjectError("HOCUS460", "source_path must be a relative string path.") from exc
    if not isinstance(text, str):
        raise ProjectError("HOCUS460", "source_path must be a relative string path.")
    if not isinstance(authored, str):
        path = Path(text)
        if path.is_absolute() or path.drive:
            raise ProjectError("HOCUS460", "source_path must be project-relative.")
        text = path.as_posix()
    _validate_relative_artifact_path(text, "source_path", code="HOCUS460")
    if not text.endswith(".hocus"):
        raise ProjectError("HOCUS460", "source_path must identify a .hocus file.")
    return text


def _checkpoint(callback: Callable[[], bool] | None) -> None:
    if callback is None:
        return
    try:
        value = callback()
    except Exception as exc:
        raise ModuleProjectFormatError(
            "HOCUS465",
            "Module formatting cancellation callback failed.",
            details={"errorType": type(exc).__name__},
        ) from exc
    if type(value) is not bool:
        raise ModuleProjectFormatError(
            "HOCUS465", "Module formatting cancellation callback must return bool."
        )
    if value:
        raise ModuleProjectFormatError("HOCUS465", "Native module formatting was cancelled.")
