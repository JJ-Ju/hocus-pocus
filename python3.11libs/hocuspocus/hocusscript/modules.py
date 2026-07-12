"""Pure external HocusScript module-library manifest contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .project import (
    DIGEST_PATTERN,
    PROJECT_UID_PATTERN,
    ProjectError,
    SEMANTIC_VERSION_PATTERN,
    _portable_path_key,
    _validate_relative_artifact_path,
)

MODULE_MANIFEST_SCHEMA_URI = "hocuspocus://schemas/hocus-module/v1"
MAX_MODULE_MANIFEST_BYTES = 256 * 1024
MAX_MODULE_ENTRIES = 4096


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    library_uid: str
    version: str
    language_version: str
    entry_modules: tuple[str, ...]
    manifest_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "library": {"uid": self.library_uid, "version": self.version},
            "language": {"version": self.language_version},
            "entry_modules": list(self.entry_modules),
        }


def decode_module_manifest(content: str | bytes | bytearray | Mapping[str, Any]) -> ModuleManifest:
    """Strictly decode hocus.module.toml v1 without resolving a filesystem root."""
    if isinstance(content, Mapping):
        payload = dict(content)
        try:
            raw = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ProjectError("HOCUS457", f"Module manifest is not canonical JSON data: {exc}") from exc
    elif isinstance(content, (str, bytes, bytearray)):
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(raw) > MAX_MODULE_MANIFEST_BYTES:
            raise ProjectError("HOCUS457", "Module manifest exceeds the byte limit.")
        try:
            payload = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ProjectError("HOCUS457", f"Invalid hocus.module.toml: {exc}") from exc
    else:
        raise TypeError("module manifest content must be TOML text, bytes, or a decoded mapping")
    if len(raw) > MAX_MODULE_MANIFEST_BYTES:
        raise ProjectError("HOCUS457", "Module manifest exceeds the byte limit.")
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "library", "language", "entry_modules"
    }:
        raise ProjectError("HOCUS457", "Module manifest has missing or unknown fields.")
    if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
        raise ProjectError("HOCUS457", "Module manifest schema_version must be 1.")
    library, language = payload["library"], payload["language"]
    if not isinstance(library, dict) or set(library) != {"uid", "version"}:
        raise ProjectError("HOCUS457", "Module manifest [library] is malformed.")
    if not isinstance(language, dict) or set(language) != {"version"}:
        raise ProjectError("HOCUS457", "Module manifest [language] is malformed.")
    uid, version, language_version = library["uid"], library["version"], language["version"]
    if not isinstance(uid, str) or not PROJECT_UID_PATTERN.fullmatch(uid):
        raise ProjectError("HOCUS457", "Module library uid is invalid.")
    if not isinstance(version, str) or not SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ProjectError("HOCUS457", "Module library version must be a semantic version.")
    if language_version != "0.2":
        raise ProjectError("HOCUS457", "Module manifest language version must be 0.2.")
    entries = payload["entry_modules"]
    if not isinstance(entries, list) or not entries or len(entries) > MAX_MODULE_ENTRIES:
        raise ProjectError("HOCUS457", "entry_modules must be a non-empty bounded array.")
    normalized: list[str] = []
    for path in entries:
        if not isinstance(path, str) or not _module_path(path):
            raise ProjectError("HOCUS457", "Entry modules must be portable relative .hocus paths.")
        normalized.append(_portable_path_key(path))
    if len(set(normalized)) != len(normalized) or entries != sorted(entries):
        raise ProjectError("HOCUS457", "Entry modules must be sorted and unique after case normalization.")
    return ModuleManifest(uid, version, language_version, tuple(entries), _digest(raw))


def _module_path(value: str) -> bool:
    if not value or len(value) > 1024 or value != value.strip() or not value.endswith(".hocus"):
        return False
    if value.startswith("/") or "\\" in value or ":" in value:
        return False
    if not all(part not in {"", ".", ".."} for part in value.split("/")):
        return False
    try:
        _validate_relative_artifact_path(value, "entry_modules", code="HOCUS457")
    except ProjectError:
        return False
    return True


def _digest(raw: bytes) -> str:
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert DIGEST_PATTERN.fullmatch(digest)
    return digest
