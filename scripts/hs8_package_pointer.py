"""Validate the immutable HocusPocus package activation pointer."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VERSIONED_INSTALL = re.compile(r"HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}")
_MAX_POINTER_BYTES = 64 * 1024
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class PackagePointerError(ValueError):
    """The active package pointer is invalid, stale, or unsafe."""


def active_package_root(package_file: Path) -> Path:
    payload = _read_json(package_file, _MAX_POINTER_BYTES, "package pointer")
    if not isinstance(payload, dict) or set(payload) != {
        "env",
        "hpath",
        "hocuspocus",
    }:
        raise PackagePointerError("Active package pointer envelope is invalid.")
    env = payload.get("env")
    if not isinstance(env, list) or len(env) != 3:
        raise PackagePointerError("Active package environment is invalid.")
    root_name = _root_name(env[0])
    root = (package_file.parent / root_name).resolve(strict=True)
    if root.parent != package_file.parent.resolve():
        raise PackagePointerError("Active package root escapes its package directory.")
    config_digest = _file_digest(root / "config" / "default.toml")
    manifest = _read_json(
        root / "package" / "install-manifest-v1.json",
        _MAX_MANIFEST_BYTES,
        "install manifest",
    )
    if not isinstance(manifest, dict):
        raise PackagePointerError("Active install manifest is invalid.")
    manifest_digest = manifest.get("manifestDigest")
    authority = payload.get("hocuspocus")
    _validate_authority(authority, config_digest, manifest_digest)
    expected = _canonical_pointer(
        root_name,
        config_digest,
        str(manifest_digest),
    )
    if payload != expected:
        raise PackagePointerError("Active package pointer is not canonical.")
    return root


def _root_name(value: Any) -> str:
    prefix = "$HOUDINI_PACKAGE_PATH/"
    if (
        not isinstance(value, dict)
        or set(value) != {"HOCUSPOCUS_ROOT"}
        or not isinstance(value.get("HOCUSPOCUS_ROOT"), str)
        or not value["HOCUSPOCUS_ROOT"].startswith(prefix)
    ):
        raise PackagePointerError("Active package root selector is invalid.")
    root_name = value["HOCUSPOCUS_ROOT"][len(prefix) :]
    if _VERSIONED_INSTALL.fullmatch(root_name) is None:
        raise PackagePointerError("Active package root selector is unsafe.")
    return root_name


def _validate_authority(
    value: Any,
    config_digest: str,
    manifest_digest: Any,
) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schemaVersion",
            "activeConfigDigest",
            "installManifestDigest",
        }
        or value.get("schemaVersion") != 1
        or not isinstance(manifest_digest, str)
        or _DIGEST.fullmatch(manifest_digest) is None
        or value.get("activeConfigDigest") != config_digest
        or value.get("installManifestDigest") != manifest_digest
    ):
        raise PackagePointerError("Active package authority is stale.")


def _canonical_pointer(
    root_name: str,
    config_digest: str,
    manifest_digest: str,
) -> dict[str, Any]:
    return {
        "env": [
            {"HOCUSPOCUS_ROOT": "$HOUDINI_PACKAGE_PATH/" + root_name},
            {
                "PYTHONPATH": {
                    "method": "prepend",
                    "value": "$HOCUSPOCUS_ROOT/python3.11libs",
                }
            },
            {"PYTHONDONTWRITEBYTECODE": "1"},
        ],
        "hpath": "$HOCUSPOCUS_ROOT",
        "hocuspocus": {
            "schemaVersion": 1,
            "activeConfigDigest": config_digest,
            "installManifestDigest": manifest_digest,
        },
    }


def _read_json(path: Path, limit: int, label: str) -> Any:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > limit
        ):
            raise OSError("unsafe file")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagePointerError(f"Active {label} is invalid.") from exc


def _file_digest(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PackagePointerError("Active configuration is unavailable.") from exc
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = ["PackagePointerError", "active_package_root"]
