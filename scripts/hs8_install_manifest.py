"""Create and verify the complete governed HocusPocus install manifest."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from hs8_windows_manifest_cleanup import governed_cleanup, terminal_cleanup
except ModuleNotFoundError:
    _native_path = Path(__file__).resolve().with_name(
        "hs8_windows_manifest_cleanup.py",
    )
    _native_spec = importlib.util.spec_from_file_location(
        "hs8_windows_manifest_cleanup",
        _native_path,
    )
    if _native_spec is None or _native_spec.loader is None:
        raise
    _native_module = importlib.util.module_from_spec(_native_spec)
    _native_spec.loader.exec_module(_native_module)
    governed_cleanup = _native_module.governed_cleanup
    terminal_cleanup = _native_module.terminal_cleanup


SCHEMA = "hocuspocus://schemas/install-manifest/v1"
MANIFEST_RELATIVE_PATH = "package/install-manifest-v1.json"
GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES = 20_000
_TOKEN_LINE = re.compile(r'(?m)^token\s*=\s*"[^"]*"\s*$')


class InstallManifestError(ValueError):
    """Invalid or stale governed install tree."""


def create_manifest(root: Path) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    rows = list(_records(resolved))
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_install_manifest",
        "schemaVersion": 1,
        "governedRoots": list(GOVERNED_ROOTS),
        "files": rows,
    }
    return {**unsigned, "manifestDigest": _digest_json(unsigned)}


def write_manifest(root: Path) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    payload = create_manifest(resolved)
    target = resolved / MANIFEST_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def verify_manifest(root: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    _reject_unmanifested_runtime_artifacts(resolved)
    path = resolved / MANIFEST_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallManifestError("Install manifest is missing or invalid.") from exc
    _validate_envelope(value)
    actual = create_manifest(resolved)
    if value != actual:
        raise InstallManifestError("Install manifest does not match governed files.")
    if expected is not None:
        _validate_envelope(expected)
        if value != expected:
            raise InstallManifestError("Installed manifest differs from the source candidate.")
    return value


def cleanup_manifest(
    root: Path,
    expected_digest: str,
    output_root_identity: str,
) -> dict[str, Any]:
    return governed_cleanup(root, expected_digest, output_root_identity)


def complete_cleanup(
    root: Path,
    expected_digest: str,
    output_root_identity: str,
    root_identity: str,
    package_identity: str,
) -> dict[str, Any]:
    return terminal_cleanup(
        root,
        {
            "manifestDigest": expected_digest,
            "outputRootIdentity": output_root_identity,
            "rootIdentity": root_identity,
            "packageIdentity": package_identity,
        },
    )


def audit_loaded_modules(
    root: Path,
    modules: Mapping[str, Any],
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    resolved_root = root.resolve(strict=True)
    verified = verify_manifest(resolved_root) if manifest is None else manifest
    _validate_envelope(verified)
    _reject_ungoverned_bytecode_loader(modules)
    governed = {
        item["relativePath"]: item["contentDigest"]
        for item in verified["files"]
    }
    receipts = []
    for module_name, module in sorted(modules.items()):
        try:
            installed_path = Path(inspect.getfile(module)).resolve(strict=True)
        except (OSError, TypeError) as exc:
            raise InstallManifestError(
                f"Loaded governed module has no auditable file origin: {module_name}."
            ) from exc
        try:
            relative = installed_path.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise InstallManifestError(
                f"Loaded governed module escapes the install root: {module_name}."
            ) from exc
        installed_digest = "sha256:" + hashlib.sha256(
            installed_path.read_bytes(),
        ).hexdigest()
        if governed.get(relative) != installed_digest:
            raise InstallManifestError(
                f"Loaded governed module is absent or stale: {module_name}."
            )
        receipts.append({
            "module": module_name,
            "relativePath": relative,
            "digest": installed_digest,
        })
    return receipts


def _reject_ungoverned_bytecode_loader(modules: Mapping[str, Any]) -> None:
    if sys.pycache_prefix is not None or not sys.dont_write_bytecode:
        raise InstallManifestError(
            "Runtime Python bytecode caching is not governed by the install manifest."
        )
    for module_name, module in modules.items():
        cached = getattr(module, "__cached__", None)
        if not cached:
            continue
        try:
            exists = Path(cached).is_file()
        except (OSError, TypeError, ValueError) as exc:
            raise InstallManifestError(
                f"Loaded governed module has invalid bytecode origin: {module_name}."
            ) from exc
        if exists:
            raise InstallManifestError(
                f"Loaded governed module executed ungoverned bytecode: {module_name}."
            )


def _records(root: Path) -> Iterable[dict[str, Any]]:
    seen = 0
    for governed in GOVERNED_ROOTS:
        base = root / governed
        if not base.is_dir():
            raise InstallManifestError(f"Governed install root is missing: {governed}.")
        for path in sorted(base.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_symlink():
                raise InstallManifestError("Governed install tree contains a symlink.")
            if not path.is_file() or _excluded(path):
                continue
            resolved = path.resolve(strict=True)
            if root not in resolved.parents:
                raise InstallManifestError("Governed install file escapes its root.")
            relative = resolved.relative_to(root).as_posix()
            if relative == MANIFEST_RELATIVE_PATH:
                continue
            size = resolved.stat().st_size
            if size > MAX_FILE_BYTES:
                raise InstallManifestError(f"Governed file is too large: {relative}.")
            content = resolved.read_bytes()
            role = "generated_config" if relative == "config/default.toml" else "immutable"
            if role == "generated_config":
                content = _canonical_config(content)
                size = len(content)
            seen += 1
            if seen > MAX_FILES:
                raise InstallManifestError("Governed install contains too many files.")
            yield {
                "relativePath": relative,
                "role": role,
                "byteLength": size,
                "contentDigest": "sha256:" + hashlib.sha256(content).hexdigest(),
            }


def _excluded(path: Path) -> bool:
    return (
        path.suffix.casefold() in {".pyc", ".pyo"}
        or "__pycache__" in path.parts
    )


def _reject_unmanifested_runtime_artifacts(root: Path) -> None:
    for governed in GOVERNED_ROOTS:
        base = root / governed
        if not base.is_dir():
            raise InstallManifestError(f"Governed install root is missing: {governed}.")
        for path in base.rglob("*"):
            if path.is_symlink():
                raise InstallManifestError(
                    "Governed install tree contains a symlink."
                )
            if (
                path.name == "__pycache__"
                or path.suffix.casefold() in {".pyc", ".pyo"}
            ):
                raise InstallManifestError(
                    "Governed install tree contains unmanifested Python bytecode."
                )


def _canonical_config(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallManifestError("Installed config is not UTF-8.") from exc
    if _TOKEN_LINE.search(text) is None:
        raise InstallManifestError("Installed config has no canonical token field.")
    return _TOKEN_LINE.sub('token = "<redacted>"', text).encode("utf-8")


def _validate_envelope(value: Any) -> None:
    fields = {
        "$schema", "kind", "schemaVersion", "governedRoots", "files",
        "manifestDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise InstallManifestError("Install manifest has an invalid envelope.")
    if (
        value["$schema"] != SCHEMA
        or value["kind"] != "hocus_install_manifest"
        or value["schemaVersion"] != 1
        or value["governedRoots"] != list(GOVERNED_ROOTS)
        or not isinstance(value["files"], list)
        or len(value["files"]) > MAX_FILES
    ):
        raise InstallManifestError("Install manifest identity is invalid.")
    unsigned = {key: item for key, item in value.items() if key != "manifestDigest"}
    if value["manifestDigest"] != _digest_json(unsigned):
        raise InstallManifestError("Install manifest digest is invalid.")


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("cleanup-governed", "cleanup-terminal", "create", "verify"),
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-digest")
    parser.add_argument("--output-root-identity")
    parser.add_argument("--root-identity")
    parser.add_argument("--package-identity")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    if arguments.command == "create":
        payload = write_manifest(arguments.root)
    elif arguments.command == "verify":
        payload = verify_manifest(arguments.root)
    elif (
        not isinstance(arguments.expected_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", arguments.expected_digest)
        is None
    ):
        raise InstallManifestError(
            "Cleanup requires an exact expected manifest digest."
        )
    elif arguments.command == "cleanup-governed":
        payload = cleanup_manifest(
            arguments.root,
            arguments.expected_digest,
            arguments.output_root_identity,
        )
    elif (
        not isinstance(arguments.root_identity, str)
        or not isinstance(arguments.package_identity, str)
    ):
        raise InstallManifestError("Terminal cleanup requires exact file identities.")
    else:
        payload = complete_cleanup(
            arguments.root,
            arguments.expected_digest,
            arguments.output_root_identity,
            arguments.root_identity,
            arguments.package_identity,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GOVERNED_ROOTS",
    "InstallManifestError",
    "MANIFEST_RELATIVE_PATH",
    "audit_loaded_modules",
    "cleanup_manifest",
    "complete_cleanup",
    "create_manifest",
    "verify_manifest",
    "write_manifest",
]
