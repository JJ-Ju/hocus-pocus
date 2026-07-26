"""Manifest and portable project-path validation."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from .compiler import SUPPORTED_LANGUAGE_VERSIONS
from .project import (
    DIGEST_PATTERN,
    EXTERNAL_ALIAS_PATTERN,
    MAX_EXTERNAL_ALIASES,
    MAX_PROJECT_DIRECTORIES,
    PROJECT_LOCK_NAME,
    PROJECT_MANIFEST_NAME,
    PROJECT_UID_PATTERN,
    SEMANTIC_VERSION_PATTERN,
    WINDOWS_RESERVED_PATH_SEGMENTS,
    ProjectError,
)


def _validate_manifest(
    payload: Any,
) -> tuple[
    int, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None,
    dict[str, dict[str, Any]],
]:
    schema_version = _validate_manifest_envelope(payload)
    project = payload["project"]
    _validate_project_table(project, schema_version)
    language = payload.get("language", {})
    lock = payload.get("lock", {})
    _validate_language_and_lock(language, lock, schema_version)
    catalog = _validate_catalog(payload, lock, schema_version)
    aliases = _validate_aliases(payload, schema_version)
    return schema_version, project, language, lock, catalog, aliases


def _validate_manifest_envelope(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} has unknown top-level fields.")
    schema_version = payload.get("schema_version")
    allowed = {"schema_version", "project", "language", "lock"}
    if schema_version in {2, 3, 4}:
        allowed.add("catalog")
    if schema_version in {3, 4}:
        allowed.add("external_aliases")
    if set(payload) - allowed:
        raise ProjectError("HOCUS405", f"{PROJECT_MANIFEST_NAME} has unknown top-level fields.")
    if (
        type(schema_version) is not int
        or schema_version not in {1, 2, 3, 4}
        or not isinstance(payload.get("project"), dict)
    ):
        raise ProjectError(
            "HOCUS405",
            f"{PROJECT_MANIFEST_NAME} requires schema_version = 1, 2, 3, or 4 and a [project] table.",
        )
    return schema_version


def _validate_project_table(project: dict[str, Any], schema_version: int) -> None:
    fields = {"uid", "name", "source_directories"}
    if schema_version in {3, 4}:
        fields.add("module_directories")
    _require_table_fields(project, fields, "project")
    uid = project.get("uid")
    if not isinstance(uid, str) or not PROJECT_UID_PATTERN.fullmatch(uid):
        raise ProjectError(
            "HOCUS406",
            "Project uid must match ^[a-z0-9][a-z0-9.-]{0,127}$.",
            details={"uid": uid},
        )
    name = project.get("name")
    if name is not None and (
        not isinstance(name, str)
        or not name.strip()
        or name != name.strip()
        or len(name) > 256
        or any(ord(char) < 32 for char in name)
    ):
        raise ProjectError(
            "HOCUS407",
            "Project name must be a bounded non-empty string without control characters.",
        )
    _validate_source_directory_values(project.get("source_directories", ["."]))
    if schema_version in {3, 4}:
        _validate_module_directory_values(project.get("module_directories", []))


def _validate_language_and_lock(
    language: Any,
    lock: Any,
    schema_version: int,
) -> None:
    _require_table_fields(language, {"version"}, "language")
    _require_table_fields(
        lock,
        {"policy", "path"} if schema_version in {2, 3, 4} else {"policy"},
        "lock",
    )
    version = language.get("version", "0.1")
    if schema_version == 3:
        valid = version == "0.2"
    elif schema_version == 4:
        valid = version == "0.3"
    else:
        valid = isinstance(version, str) and version in SUPPORTED_LANGUAGE_VERSIONS
    if not valid:
        raise ProjectError(
            "HOCUS421",
            "Project language version is unsupported.",
            details={"languageVersion": version},
        )
    policy = lock.get("policy", "optional")
    if not isinstance(policy, str) or policy not in {"optional", "required"}:
        raise ProjectError("HOCUS405", "lock.policy must be optional or required.")
    if schema_version in {2, 3, 4} and policy != "required":
        raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires lock.policy = required.")
    if schema_version in {2, 3, 4} and "path" not in lock:
        raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires lock.path.")
    if "path" in lock:
        _validate_relative_artifact_path(lock["path"], "lock.path")
        if not lock["path"].endswith(".json"):
            raise ProjectError("HOCUS405", "lock.path must identify a .json file.")


def _validate_catalog(
    payload: dict[str, Any],
    lock: dict[str, Any],
    schema_version: int,
) -> dict[str, Any] | None:
    if schema_version not in {2, 3, 4}:
        return None
    catalog = payload.get("catalog")
    _require_table_fields(catalog, {"path"}, "catalog")
    if "path" not in catalog:
        raise ProjectError("HOCUS405", f"Manifest schema v{schema_version} requires catalog.path.")
    _validate_relative_artifact_path(catalog["path"], "catalog.path")
    if not catalog["path"].endswith(".json"):
        raise ProjectError("HOCUS405", "catalog.path must identify a .json file.")
    if catalog["path"].casefold() == lock.get("path", PROJECT_LOCK_NAME).casefold():
        raise ProjectError("HOCUS405", "catalog.path and lock.path must be different files.")
    return catalog


def _validate_aliases(
    payload: dict[str, Any],
    schema_version: int,
) -> dict[str, dict[str, Any]]:
    if schema_version not in {3, 4}:
        return {}
    raw_aliases = payload.get("external_aliases", {})
    if not isinstance(raw_aliases, dict) or len(raw_aliases) > MAX_EXTERNAL_ALIASES:
        raise ProjectError("HOCUS450", "external_aliases must be a bounded table.")
    aliases: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    identities: dict[str, tuple[str, str | None]] = {}
    for alias, record in raw_aliases.items():
        _validate_alias(alias, record, folded, identities)
        aliases[alias] = dict(record)
    return aliases


def _validate_alias(
    alias: Any,
    record: Any,
    folded: set[str],
    identities: dict[str, tuple[str, str | None]],
) -> None:
    if not isinstance(alias, str) or not EXTERNAL_ALIAS_PATTERN.fullmatch(alias):
        raise ProjectError("HOCUS450", "External alias names must be bounded identifiers.")
    if alias.casefold() in folded:
        raise ProjectError("HOCUS450", "External aliases must be unique after case normalization.")
    expected_fields = {"library_uid", "version", "module_manifest_digest"}
    if not isinstance(record, dict) or set(record) - expected_fields:
        raise ProjectError("HOCUS450", "External alias records have unknown fields.")
    library_uid = record.get("library_uid")
    version = record.get("version")
    manifest_pin = record.get("module_manifest_digest")
    if not isinstance(library_uid, str) or not PROJECT_UID_PATTERN.fullmatch(library_uid):
        raise ProjectError("HOCUS450", "External alias library UIDs are invalid.")
    if not isinstance(version, str) or not SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ProjectError("HOCUS450", "External alias versions must be semantic versions.")
    if manifest_pin is not None and (
        not isinstance(manifest_pin, str) or not DIGEST_PATTERN.fullmatch(manifest_pin)
    ):
        raise ProjectError("HOCUS450", "External alias module manifest digest is invalid.")
    identity = (version, manifest_pin)
    prior = identities.get(library_uid)
    if prior is not None and prior != identity:
        raise ProjectError(
            "HOCUS450",
            "Aliases for one external library UID must use one version and manifest digest.",
        )
    identities[library_uid] = identity
    folded.add(alias.casefold())


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
            raise ProjectError(
                "HOCUS427",
                "Source directories must use normalized portable relative paths.",
                details={"path": value},
            )
        parts = value.split("/")
        if value != "." and any(part in {"", ".", ".."} for part in parts):
            raise ProjectError(
                "HOCUS427",
                "Source directories cannot contain empty, dot, or parent segments.",
                details={"path": value},
            )
        if value != ".":
            _validate_relative_artifact_path(value, "Source directory", code="HOCUS427")
        normalized.append(_portable_path_key(value))
    if len(set(normalized)) != len(normalized):
        raise ProjectError("HOCUS427", "Source directories must be unique after portable case normalization.")


def _validate_module_directory_values(values: Any) -> None:
    if not isinstance(values, list) or len(values) > MAX_PROJECT_DIRECTORIES:
        raise ProjectError("HOCUS449", "project.module_directories must be a bounded array.")
    if not values:
        return
    try:
        _validate_source_directory_values(values)
    except ProjectError as exc:
        raise ProjectError(
            "HOCUS449",
            exc.message.replace("Source directories", "Module directories").replace(
                "project.source_directories", "project.module_directories",
            ),
            details=exc.details,
        ) from exc


def _validate_relative_artifact_path(value: Any, label: str, *, code: str = "HOCUS405") -> None:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProjectError(code, f"{label} must be a bounded portable relative path.")
    if value != value.strip() or "\\" in value or ":" in value or value.startswith("/"):
        raise ProjectError(
            code, f"{label} must be a normalized portable relative path.",
            details={"path": value},
        )
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ProjectError(
            code, f"{label} cannot contain empty, dot, or parent segments.",
            details={"path": value},
        )
    for part in value.split("/"):
        if (
            part != unicodedata.normalize("NFC", part)
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or ord(char) == 127 for char in part)
            or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_PATH_SEGMENTS
        ):
            raise ProjectError(
                code,
                f"{label} contains a nonportable or Windows-reserved path segment.",
                details={"path": value},
            )


def _portable_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _resolve_project_artifact(root: Path, relative: str, code: str, label: str) -> Path:
    _validate_relative_artifact_path(relative, label)
    resolved = (root / Path(relative)).resolve(strict=False)
    _require_contained(resolved, root, code, f"{label} escapes the project root.")
    return resolved


def _resolve_source_directories(root: Path, values: list[str]) -> list[Path]:
    return _resolve_directories(
        root, values, "HOCUS409", "Project source directory escapes the project root.",
        "HOCUS427", "Configured source directory must exist and be a directory.",
    )


def _resolve_module_directories(root: Path, values: list[str]) -> list[Path]:
    return _resolve_directories(
        root, values, "HOCUS449", "Project module directory escapes the project root.",
        "HOCUS449", "Configured module directory must exist and be a directory.",
    )


def _resolve_directories(
    root: Path,
    values: list[str],
    containment_code: str,
    containment_message: str,
    existence_code: str,
    existence_message: str,
) -> list[Path]:
    output: list[Path] = []
    for value in values:
        resolved = (root / Path(value)).resolve(strict=False)
        _require_contained(resolved, root, containment_code, containment_message)
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectError(existence_code, existence_message, details={"path": value})
        output.append(resolved)
    return output


def _require_contained(path: Path, root: Path, code: str, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProjectError(code, message, details={"path": str(path)}) from exc
