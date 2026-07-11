"""Native HocusScript project discovery and bounded file compilation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from .compiler import MAX_SOURCE_BYTES, SUPPORTED_LANGUAGE_VERSIONS, compile_source
from .model import CompileResult

PROJECT_MANIFEST_NAME = "hocus.project.toml"
PROJECT_LOCK_NAME = "hocus.lock.json"
PROJECT_SCHEMA_URI = "hocuspocus://schemas/hocus-project/v1"
LOCK_SCHEMA_URI = "hocuspocus://schemas/hocus-lock/v1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PROJECT_DIRECTORIES = 64
MAX_METADATA_DEPTH = 64
MAX_METADATA_VALUES = 50_000
PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    language_version: str
    lock_policy: str
    manifest_digest: str | None
    lock_digest: str | None

    @property
    def portable(self) -> bool:
        return self.uid is not None and self.manifest_digest is not None

    @classmethod
    def load(cls, project_directory: str | Path, *, validate_lock: bool = True) -> "ProjectContext":
        root = Path(project_directory).expanduser().resolve(strict=False)
        if not root.exists():
            raise ProjectError("HOCUS401", "Project directory does not exist.", details={"projectDirectory": str(root)})
        if not root.is_dir():
            raise ProjectError("HOCUS402", "Project path is not a directory.", details={"projectDirectory": str(root)})

        manifest_path = (root / PROJECT_MANIFEST_NAME).resolve(strict=False)
        uid: str | None = None
        name: str | None = None
        source_values = ["."]
        language_version = "0.1"
        lock_policy = "optional"
        manifest_digest: str | None = None
        if manifest_path.exists():
            _require_metadata_file(manifest_path, root, PROJECT_MANIFEST_NAME)
            manifest_bytes = _read_bounded(manifest_path, MAX_MANIFEST_BYTES, "HOCUS403", "Project manifest")
            manifest_digest = _digest(manifest_bytes)
            try:
                payload = tomllib.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise ProjectError("HOCUS404", f"Invalid {PROJECT_MANIFEST_NAME}: {exc}") from exc
            project, language, lock = _validate_manifest(payload)
            uid = project["uid"]
            name = project.get("name")
            source_values = project.get("source_directories", ["."])
            language_version = language.get("version", "0.1")
            lock_policy = lock.get("policy", "optional")

        source_directories = _resolve_source_directories(root, source_values)
        lock_path = (root / PROJECT_LOCK_NAME).resolve(strict=False)
        if validate_lock and lock_path.exists():
            if uid is None or manifest_digest is None:
                raise ProjectError("HOCUS423", f"{PROJECT_LOCK_NAME} requires {PROJECT_MANIFEST_NAME}.")
            _require_metadata_file(lock_path, root, PROJECT_LOCK_NAME)
            lock_digest = _load_lock(
                lock_path,
                project_uid=uid,
                manifest_digest=manifest_digest,
                language_version=language_version,
            )
        else:
            if validate_lock and lock_policy == "required":
                raise ProjectError("HOCUS426", f"{PROJECT_LOCK_NAME} is required by the project manifest.")
            lock_digest = None
        return cls(
            root=root,
            uid=uid,
            name=name,
            source_directories=tuple(source_directories),
            language_version=language_version,
            lock_policy=lock_policy,
            manifest_digest=manifest_digest,
            lock_digest=lock_digest,
        )

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
        return self.source_uri_for_resolved(self.resolve_source(source_path))

    def source_uri_for_resolved(self, resolved: Path) -> str:
        _require_contained(resolved, self.root, "HOCUS411", "Source path escapes the project root.")
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
    validate_lock: bool = True,
) -> CompileResult:
    """Compile one native .hocus file inside an explicitly selected project."""

    project = ProjectContext.load(project_directory, validate_lock=validate_lock)
    resolved = project.resolve_source(source_path)
    if validate_lock:
        source_uri = project.source_uri_for_resolved(resolved)
    else:
        relative = resolved.relative_to(project.root).as_posix()
        source_uri = f"hocus-workspace:///{quote(relative, safe='/-._~')}"
    raw = _read_bounded_stable(resolved, MAX_SOURCE_BYTES, "HOCUS001", "HocusScript source")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectError(
            "HOCUS416",
            "HocusScript source must be valid UTF-8.",
            details={"start": exc.start, "end": exc.end, "sourceUri": source_uri},
        ) from exc
    result = compile_source(source, resolved.name, source_uri=source_uri, strict=strict)
    result.source_kind = "project_file" if validate_lock and project.portable else "workspace_file"
    result.project_uid = project.uid if validate_lock else None
    result.project_manifest_digest = project.manifest_digest if validate_lock else None
    result.project_lock_digest = project.lock_digest if validate_lock else None
    result.native_source_path = str(resolved)
    return result


def _validate_manifest(payload: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) - {"schema_version", "project", "language", "lock"}:
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} has unknown top-level fields.")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1 or not isinstance(payload.get("project"), dict):
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} requires schema_version = 1 and a [project] table.")
    project = payload["project"]
    _require_table_fields(project, {"uid", "name", "source_directories"}, "project")
    uid = project.get("uid")
    if not isinstance(uid, str) or not PROJECT_UID_PATTERN.fullmatch(uid):
        raise ProjectError("HOCUS406", "Project uid must match ^[a-z0-9][a-z0-9.-]{0,127}$.", details={"uid": uid})
    name = project.get("name")
    if name is not None:
        if not isinstance(name, str) or not name.strip() or len(name) > 256 or any(ord(char) < 32 for char in name):
            raise ProjectError("HOCUS407", "Project name must be a bounded non-empty string without control characters.")
        project["name"] = name.strip()
    _validate_source_directory_values(project.get("source_directories", ["."]))
    language = payload.get("language", {})
    lock = payload.get("lock", {})
    _require_table_fields(language, {"version"}, "language")
    _require_table_fields(lock, {"policy"}, "lock")
    version = language.get("version", "0.1")
    if not isinstance(version, str) or version not in SUPPORTED_LANGUAGE_VERSIONS:
        raise ProjectError("HOCUS421", "Project language version is unsupported.", details={"languageVersion": version})
    policy = lock.get("policy", "optional")
    if not isinstance(policy, str) or policy not in {"optional", "required"}:
        raise ProjectError("HOCUS405", "lock.policy must be optional or required.")
    return project, language, lock


def _require_table_fields(table: Any, allowed: set[str], name: str) -> None:
    if not isinstance(table, dict) or set(table) - allowed:
        raise ProjectError("HOCUS405", f"[{name}] has unknown fields or is not a table.")


def _validate_source_directory_values(values: Any) -> None:
    if not isinstance(values, list) or not values or len(values) > MAX_PROJECT_DIRECTORIES:
        raise ProjectError("HOCUS427", "project.source_directories must be a non-empty bounded array.")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise ProjectError("HOCUS427", "Source-directory entries must be bounded non-empty strings.")
        if value != value.strip() or "\\" in value or ":" in value or value.startswith("/"):
            raise ProjectError("HOCUS427", "Source directories must use normalized portable relative paths.", details={"path": value})
        parts = value.split("/")
        if value != "." and any(part in {"", ".", ".."} for part in parts):
            raise ProjectError("HOCUS427", "Source directories cannot contain empty, dot, or parent segments.", details={"path": value})
        normalized.append(value.casefold())
    if len(set(normalized)) != len(normalized):
        raise ProjectError("HOCUS427", "Source directories must be unique after portable case normalization.")


def _resolve_source_directories(root: Path, values: list[str]) -> list[Path]:
    output: list[Path] = []
    for value in values:
        resolved = (root / Path(value)).resolve(strict=False)
        _require_contained(resolved, root, "HOCUS409", "Project source directory escapes the project root.")
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectError("HOCUS427", "Configured source directory must exist and be a directory.", details={"path": value})
        output.append(resolved)
    return output


def _load_lock(path: Path, *, project_uid: str, manifest_digest: str, language_version: str) -> str:
    raw = _read_bounded(path, MAX_MANIFEST_BYTES, "HOCUS410", "Project lock")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProjectError, RecursionError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("HOCUS422", f"Invalid {PROJECT_LOCK_NAME}: {exc}") from exc
    _validate_json_complexity(payload)
    expected_keys = {"$schema", "kind", "schemaVersion", "projectUid", "manifestDigest", "languageVersion", "catalog", "modules"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} has missing or unknown fields.")
    if (
        payload["$schema"] != LOCK_SCHEMA_URI
        or payload["kind"] != "hocus_project_lock"
        or type(payload["schemaVersion"]) is not int
        or payload["schemaVersion"] != 1
    ):
        raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} uses an unsupported schema or kind.")
    if not isinstance(payload["projectUid"], str) or not PROJECT_UID_PATTERN.fullmatch(payload["projectUid"]):
        raise ProjectError("HOCUS422", "Lock projectUid is invalid.")
    if not isinstance(payload["manifestDigest"], str) or not DIGEST_PATTERN.fullmatch(payload["manifestDigest"]):
        raise ProjectError("HOCUS422", "Lock manifestDigest must be a lowercase SHA-256 digest.")
    if not isinstance(payload["languageVersion"], str) or payload["languageVersion"] not in SUPPORTED_LANGUAGE_VERSIONS:
        raise ProjectError("HOCUS422", "Lock languageVersion is unsupported.")
    stale: dict[str, Any] = {}
    for key, expected in (("projectUid", project_uid), ("manifestDigest", manifest_digest), ("languageVersion", language_version)):
        if payload[key] != expected:
            stale[key] = {"expected": expected, "actual": payload[key]}
    if stale:
        raise ProjectError("HOCUS424", f"{PROJECT_LOCK_NAME} is stale.", details=stale)
    if payload["catalog"] is not None or payload["modules"] != []:
        raise ProjectError("HOCUS425", "Lock v1 reserves catalog as null and modules as empty until HS2/HS6.")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    return _digest(canonical)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains duplicate key {key!r}.")
        output[key] = value
    return output


def _reject_json_constant(value: str) -> Any:
    raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains non-finite constant {value}.")


def _validate_json_complexity(value: Any) -> None:
    count = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_METADATA_VALUES or depth > MAX_METADATA_DEPTH:
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} exceeds structural complexity limits.")
        if isinstance(item, float) and not math.isfinite(item):
            raise ProjectError("HOCUS422", f"{PROJECT_LOCK_NAME} contains a non-finite number.")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _read_bounded(path: Path, limit: int, code: str, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise ProjectError(code, f"Could not read {label.lower()}: {exc}", details={"path": str(path)}) from exc
    if len(raw) > limit:
        raise ProjectError(code, f"{label} exceeds the {limit}-byte limit.", details={"path": str(path), "limit": limit})
    return raw


def _read_bounded_stable(path: Path, limit: int, code: str, label: str) -> bytes:
    try:
        before = path.stat()
        raw = _read_bounded(path, limit, code, label)
        after = path.stat()
    except OSError as exc:
        raise ProjectError(code, f"Could not inspect {label.lower()}: {exc}", details={"path": str(path)}) from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise ProjectError("HOCUS428", f"{label} changed while it was being read.", details={"path": str(path)})
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
