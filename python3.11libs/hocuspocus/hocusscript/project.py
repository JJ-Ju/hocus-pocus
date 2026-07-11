"""Native HocusScript project discovery and bounded file compilation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .compiler import MAX_SOURCE_BYTES, compile_source
from .model import CompileResult

PROJECT_MANIFEST_NAME = "hocus.project.toml"
PROJECT_LOCK_NAME = "hocus.lock.json"
MAX_MANIFEST_BYTES = 256 * 1024
PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")


class ProjectError(ValueError):
    """Typed native project/file error suitable for CLI and editor adapters."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": "error",
            "code": self.code,
            "phase": "project",
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ProjectContext:
    root: Path
    uid: str | None
    name: str | None
    source_directories: tuple[Path, ...]
    manifest_digest: str | None
    lock_digest: str | None

    @property
    def portable(self) -> bool:
        return self.uid is not None

    @classmethod
    def load(cls, project_directory: str | Path) -> "ProjectContext":
        root = Path(project_directory).expanduser().resolve(strict=False)
        if not root.exists():
            raise ProjectError("HOCUS401", "Project directory does not exist.", details={"projectDirectory": str(root)})
        if not root.is_dir():
            raise ProjectError("HOCUS402", "Project path is not a directory.", details={"projectDirectory": str(root)})

        manifest_path = (root / PROJECT_MANIFEST_NAME).resolve(strict=False)
        uid: str | None = None
        name: str | None = None
        source_values: list[str] = ["."]
        manifest_digest: str | None = None
        if manifest_path.exists():
            _require_metadata_file(manifest_path, root, PROJECT_MANIFEST_NAME)
            raw = _read_bounded(manifest_path, MAX_MANIFEST_BYTES, "HOCUS403", "Project manifest")
            manifest_digest = _digest(raw)
            try:
                payload = tomllib.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise ProjectError("HOCUS404", f"Invalid {PROJECT_MANIFEST_NAME}: {exc}") from exc
            schema_version = payload.get("schema_version")
            project = payload.get("project")
            if schema_version != 1 or not isinstance(project, dict):
                raise ProjectError(
                    "HOCUS405",
                    f"{PROJECT_MANIFEST_NAME} requires schema_version = 1 and a [project] table.",
                )
            uid_value = project.get("uid")
            if not isinstance(uid_value, str) or not PROJECT_UID_PATTERN.fullmatch(uid_value):
                raise ProjectError(
                    "HOCUS406",
                    "Project uid must match ^[a-z0-9][a-z0-9.-]{0,127}$.",
                    details={"uid": uid_value},
                )
            uid = uid_value
            name_value = project.get("name")
            if name_value is not None and (not isinstance(name_value, str) or not name_value.strip()):
                raise ProjectError("HOCUS407", "Project name must be a non-empty string when provided.")
            name = name_value.strip() if isinstance(name_value, str) else None
            configured_sources = project.get("source_directories", ["."])
            if not isinstance(configured_sources, list) or not configured_sources:
                raise ProjectError("HOCUS408", "project.source_directories must be a non-empty array of relative paths.")
            source_values = configured_sources

        source_directories: list[Path] = []
        for value in source_values:
            if not isinstance(value, str) or not value.strip():
                raise ProjectError("HOCUS408", "project.source_directories entries must be non-empty strings.")
            relative = Path(value)
            if relative.is_absolute():
                raise ProjectError("HOCUS409", "Project source directories must be relative.", details={"path": value})
            resolved = (root / relative).resolve(strict=False)
            _require_contained(resolved, root, "HOCUS409", "Project source directory escapes the project root.")
            source_directories.append(resolved)

        lock_path = (root / PROJECT_LOCK_NAME).resolve(strict=False)
        if lock_path.exists():
            _require_metadata_file(lock_path, root, PROJECT_LOCK_NAME)
            lock_digest = _digest(_read_bounded(lock_path, MAX_MANIFEST_BYTES, "HOCUS410", "Project lock"))
        else:
            lock_digest = None
        return cls(root, uid, name, tuple(source_directories), manifest_digest, lock_digest)

    def resolve_source(self, source_path: str | Path) -> Path:
        candidate = Path(source_path).expanduser()
        resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (self.root / candidate).resolve(strict=False)
        _require_contained(resolved, self.root, "HOCUS411", "Source path escapes the project root.")
        if resolved.suffix.lower() != ".hocus":
            raise ProjectError("HOCUS412", "HocusScript source files must use the .hocus suffix.", details={"path": str(source_path)})
        if not resolved.exists():
            raise ProjectError("HOCUS413", "HocusScript source file does not exist.", details={"path": str(source_path)})
        if not resolved.is_file():
            raise ProjectError("HOCUS414", "HocusScript source path is not a regular file.", details={"path": str(source_path)})
        if not any(_is_contained(resolved, source_root) for source_root in self.source_directories):
            raise ProjectError("HOCUS415", "Source file is outside the configured source directories.", details={"path": str(source_path)})
        return resolved

    def source_uri(self, source_path: str | Path) -> str:
        resolved = self.resolve_source(source_path)
        relative = resolved.relative_to(self.root).as_posix()
        encoded = quote(relative, safe="/-._~")
        if self.uid is not None:
            return f"hocus-project://{self.uid}/{encoded}"
        return f"hocus-workspace:///{encoded}"


def compile_path(
    source_path: str | Path,
    *,
    project_directory: str | Path,
    strict: bool = True,
) -> CompileResult:
    """Compile one native .hocus file inside an explicitly selected project."""

    project = ProjectContext.load(project_directory)
    resolved = project.resolve_source(source_path)
    source_uri = project.source_uri(resolved)
    raw = _read_bounded(resolved, MAX_SOURCE_BYTES, "HOCUS001", "HocusScript source")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS416",
            "HocusScript source must be valid UTF-8.",
            details={"start": exc.start, "end": exc.end, "sourceUri": source_uri},
        ) from exc
    result = compile_source(source, resolved.name, source_uri=source_uri, strict=strict)
    result.source_kind = "project_file" if project.portable else "workspace_file"
    result.project_uid = project.uid
    result.project_manifest_digest = project.manifest_digest
    result.project_lock_digest = project.lock_digest
    result.native_source_path = str(resolved)
    return result


def _read_bounded(path: Path, limit: int, code: str, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise ProjectError(code, f"Could not read {label.lower()}: {exc}", details={"path": str(path)}) from exc
    if len(raw) > limit:
        raise ProjectError(code, f"{label} exceeds the {limit}-byte limit.", details={"path": str(path), "limit": limit})
    return raw


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _require_contained(path: Path, root: Path, code: str, message: str) -> None:
    if not _is_contained(path, root):
        raise ProjectError(code, message, details={"path": str(path)})


def _require_metadata_file(path: Path, root: Path, name: str) -> None:
    _require_contained(path, root, "HOCUS419", f"{name} resolves outside the project root.")
    if not path.is_file():
        raise ProjectError("HOCUS420", f"{name} is not a regular file.", details={"path": str(path)})
