"""Stable launcher for the durable HocusPocus stdio MCP broker."""

from __future__ import annotations

import hashlib
import hmac
import importlib.abc
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VERSIONED_ROOT = re.compile(r"HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}")
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_FILES = 20_000
_MANIFEST_PATH = "package/install-manifest-v1.json"
_MANIFEST_SCHEMA = "hocuspocus://schemas/install-manifest/v1"
_GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)
_TOKEN_LINE = re.compile(rb'(?m)^token\s*=\s*"[^"]*"\s*$')


class _InstalledCredential:
    __slots__ = ("secret", "config_digest", "manifest_digest")

    def __init__(
        self,
        secret: str,
        config_digest: str,
        manifest_digest: str,
    ) -> None:
        object.__setattr__(self, "secret", secret)
        object.__setattr__(self, "config_digest", config_digest)
        object.__setattr__(self, "manifest_digest", manifest_digest)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("Installed credentials are immutable.")

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _InstalledCredential)
            and self.secret == other.secret
            and self.config_digest == other.config_digest
            and self.manifest_digest == other.manifest_digest
        )

    def __repr__(self) -> str:
        return "_InstalledCredential(<redacted>)"


class _FileAuthority(NamedTuple):
    content: bytes
    identity: tuple[int, int, int, int]


class _InstallSnapshot(NamedTuple):
    manifest: dict[str, Any]
    content: dict[str, bytes]
    manifest_content: bytes


class _TrustedModuleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, snapshot: _InstallSnapshot, root: Path) -> None:
        self._root = root
        self._sources = {
            _module_name(relative): (relative, content)
            for relative, content in snapshot.content.items()
            if relative.startswith("python3.11libs/hocuspocus/")
            and relative.endswith(".py")
        }
        self.loaded: dict[str, str] = {}

    def find_spec(
        self,
        fullname: str,
        _path: object = None,
        _target: object = None,
    ) -> Any:
        selected = self._sources.get(fullname)
        if selected is None:
            return None
        relative, _content = selected
        package = relative.endswith("/__init__.py")
        return importlib.util.spec_from_loader(fullname, self, is_package=package)

    def create_module(self, _spec: Any) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        relative, content = self._sources[module.__name__]
        origin = self._root / relative
        module.__file__ = os.fspath(origin)
        if relative.endswith("/__init__.py"):
            module.__path__ = [os.fspath(origin.parent)]
        exec(compile(content, os.fspath(origin), "exec"), module.__dict__)
        self.loaded[module.__name__] = relative


def _read_file_authority(path: Path, limit: int) -> _FileAuthority:
    try:
        link = path.lstat()
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise RuntimeError("HocusPocus activation authority is unavailable.") from exc
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if (
        identity
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or stat.S_ISLNK(link.st_mode)
        or _is_reparse(link)
        or (link.st_dev, link.st_ino) != (before.st_dev, before.st_ino)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or len(content) > limit
    ):
        raise RuntimeError("HocusPocus activation authority is unsafe.")
    return _FileAuthority(content, identity)


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(
            "HocusPocus active-package identity is unavailable."
        ) from exc
    if not stat.S_ISDIR(value.st_mode) or _is_reparse(value):
        raise RuntimeError("HocusPocus active-package identity is unsafe.")
    return value.st_dev, value.st_ino


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _pointer_authority(
    launcher: Path,
) -> tuple[Path, _FileAuthority, str, str]:
    parent = launcher.parent.resolve()
    pointer = parent / "hocuspocus.json"
    authority = _read_file_authority(pointer, _MAX_CONFIG_BYTES)
    try:
        payload = json.loads(authority.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "HocusPocus active-package pointer is missing or invalid."
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "env",
        "hpath",
        "hocuspocus",
    }:
        raise RuntimeError("HocusPocus active-package pointer is not canonical.")
    env = payload.get("env")
    metadata = payload.get("hocuspocus")
    if (
        not isinstance(env, list)
        or len(env) != 3
        or not isinstance(metadata, dict)
        or set(metadata) != {
            "schemaVersion",
            "activeConfigDigest",
            "installManifestDigest",
        }
        or metadata.get("schemaVersion") != 1
        or _DIGEST.fullmatch(str(metadata.get("activeConfigDigest"))) is None
        or _DIGEST.fullmatch(str(metadata.get("installManifestDigest"))) is None
    ):
        raise RuntimeError("HocusPocus active-package authority is invalid.")
    expected_env = [
        env[0],
        {
            "PYTHONPATH": {
                "method": "prepend",
                "value": "$HOCUSPOCUS_ROOT/python3.11libs",
            }
        },
        {"PYTHONDONTWRITEBYTECODE": "1"},
    ]
    if env != expected_env or payload.get("hpath") != "$HOCUSPOCUS_ROOT":
        raise RuntimeError("HocusPocus active-package pointer is not canonical.")
    root_entry = env[0]
    if not isinstance(root_entry, dict) or set(root_entry) != {"HOCUSPOCUS_ROOT"}:
        raise RuntimeError("HocusPocus active-package root is invalid.")
    try:
        root_value = root_entry["HOCUSPOCUS_ROOT"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("HocusPocus active-package root is invalid.") from exc
    prefix = "$HOUDINI_PACKAGE_PATH/"
    if not isinstance(root_value, str) or not root_value.startswith(prefix):
        raise RuntimeError("HocusPocus active-package root is invalid.")
    root_name = root_value[len(prefix) :]
    if (
        not root_name
        or "/" in root_name
        or "\\" in root_name
        or root_name in {".", ".."}
        or _VERSIONED_ROOT.fullmatch(root_name) is None
    ):
        raise RuntimeError(
            "HocusPocus active-package root escapes its package directory."
        )
    root = (parent / root_name).resolve(strict=True)
    if root.parent != parent or not (root / "python3.11libs" / "hocuspocus").is_dir():
        raise RuntimeError("HocusPocus active-package root is unavailable.")
    return (
        root,
        authority,
        str(metadata["activeConfigDigest"]),
        str(metadata["installManifestDigest"]),
    )


def _active_root(launcher: Path) -> tuple[Path, bool]:
    parent = launcher.parent.resolve()
    if (parent / "python3.11libs" / "hocuspocus").is_dir():
        return parent, False
    if (
        parent.name == "scripts"
        and (parent.parent / "python3.11libs" / "hocuspocus").is_dir()
    ):
        return parent.parent, False
    root, _authority, _config_digest, _manifest_digest = _pointer_authority(launcher)
    return root, True


def _verify_install(
    root: Path,
    launcher: Path,
    stable_copy: bool,
) -> _InstallSnapshot:
    root_identity = _directory_identity(root)
    manifest_authority = _read_file_authority(
        root / _MANIFEST_PATH,
        _MAX_FILE_BYTES,
    )
    try:
        manifest = json.loads(manifest_authority.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("HocusPocus install manifest is invalid.") from exc
    content, rows = _collect_governed_content(root)
    unsigned = {
        "$schema": _MANIFEST_SCHEMA,
        "kind": "hocus_install_manifest",
        "schemaVersion": 1,
        "governedRoots": list(_GOVERNED_ROOTS),
        "files": rows,
    }
    expected = {**unsigned, "manifestDigest": _digest_json(unsigned)}
    if manifest != expected:
        raise RuntimeError("HocusPocus install manifest does not match its files.")
    governed_launcher = content.get("scripts/hocuspocus-mcp-stdio.py")
    if stable_copy and (
        governed_launcher is None
        or _read_file_authority(launcher, _MAX_FILE_BYTES).content
        != governed_launcher
    ):
        raise RuntimeError(
            "Stable HocusPocus launcher does not match the active package."
        )
    if (
        _directory_identity(root) != root_identity
        or _read_file_authority(root / _MANIFEST_PATH, _MAX_FILE_BYTES)
        != manifest_authority
    ):
        raise RuntimeError("HocusPocus install authority changed during verification.")
    return _InstallSnapshot(manifest, content, manifest_authority.content)


def _collect_governed_content(
    root: Path,
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    selected: list[Path] = []
    for governed in _GOVERNED_ROOTS:
        base = root / governed
        governed_files = _governed_files(base)
        selected.extend(sorted(
            governed_files,
            key=lambda value: value.as_posix().casefold(),
        ))
    content: dict[str, bytes] = {}
    portable_names: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in selected:
        relative = path.relative_to(root).as_posix()
        if relative == _MANIFEST_PATH:
            continue
        portable = relative.casefold()
        if portable in portable_names:
            raise RuntimeError("HocusPocus governed install has an ambiguous path.")
        portable_names.add(portable)
        if len(rows) >= _MAX_FILES:
            raise RuntimeError("HocusPocus governed install contains too many files.")
        raw = _read_file_authority(path, _MAX_FILE_BYTES).content
        normalized = _canonical_config(raw) if relative == "config/default.toml" else raw
        role = "generated_config" if relative == "config/default.toml" else "immutable"
        content[relative] = raw
        rows.append({
            "relativePath": relative,
            "role": role,
            "byteLength": len(normalized),
            "contentDigest": _digest(normalized),
        })
    return content, rows


def _governed_files(base: Path) -> list[Path]:
    try:
        metadata = base.lstat()
    except OSError as exc:
        raise RuntimeError("HocusPocus governed install root is unavailable.") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise RuntimeError("HocusPocus governed install root is unsafe.")
    governed_files = []
    for path in base.rglob("*"):
        try:
            item = path.lstat()
        except OSError as exc:
            raise RuntimeError("HocusPocus governed install tree changed.") from exc
        if stat.S_ISLNK(item.st_mode) or _is_reparse(item):
            raise RuntimeError("HocusPocus governed install tree contains a link.")
        if path.name == "__pycache__" or path.suffix.casefold() in {".pyc", ".pyo"}:
            raise RuntimeError("HocusPocus governed install contains bytecode.")
        if stat.S_ISREG(item.st_mode):
            governed_files.append(path)
        elif not stat.S_ISDIR(item.st_mode):
            raise RuntimeError("HocusPocus governed install contains a special file.")
    return governed_files


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & flag)


def _canonical_config(content: bytes) -> bytes:
    if _TOKEN_LINE.search(content) is None:
        raise RuntimeError("Installed HocusPocus configuration is not canonical.")
    return _TOKEN_LINE.sub(b'token = "<redacted>"', content)


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _digest(encoded)


def _module_name(relative: str) -> str:
    value = relative.removeprefix("python3.11libs/").removesuffix(".py")
    if value.endswith("/__init__"):
        value = value.removesuffix("/__init__")
    return value.replace("/", ".")


def _token_from_config(content: bytes) -> str:
    try:
        payload = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("Installed HocusPocus authentication is invalid.") from exc
    mode = payload.get("token_mode")
    token = payload.get("token")
    if mode == "disabled" and token == "":
        return ""
    if (
        mode not in {"generated", "static"}
        or not isinstance(token, str)
        or _TOKEN.fullmatch(token) is None
    ):
        raise RuntimeError("Installed HocusPocus authentication is invalid.")
    return token


def _installed_credential(
    launcher: Path,
    root: Path,
    manifest_digest: str,
) -> _InstalledCredential:
    (
        selected_root,
        pointer_before,
        expected_config_digest,
        expected_manifest_digest,
    ) = _pointer_authority(launcher)
    if selected_root != root or manifest_digest != expected_manifest_digest:
        raise RuntimeError("HocusPocus active-package authority is stale.")
    root_identity = _directory_identity(root)
    config_path = root / "config" / "default.toml"
    config_before = _read_file_authority(config_path, _MAX_CONFIG_BYTES)
    if _digest(config_before.content) != expected_config_digest:
        raise RuntimeError("HocusPocus active configuration is stale.")
    token = _token_from_config(config_before.content)
    selected_after, pointer_after, config_digest, selected_manifest = (
        _pointer_authority(launcher)
    )
    config_after = _read_file_authority(config_path, _MAX_CONFIG_BYTES)
    if (
        selected_after != root
        or _directory_identity(root) != root_identity
        or pointer_after != pointer_before
        or config_after != config_before
        or config_digest != expected_config_digest
        or selected_manifest != expected_manifest_digest
    ):
        raise RuntimeError(
            "HocusPocus active-package authority changed during admission."
        )
    return _InstalledCredential(token, expected_config_digest, manifest_digest)


def _refresh_installed_credential(launcher: Path) -> _InstalledCredential:
    root, stable_copy = _active_root(launcher)
    if not stable_copy:
        raise RuntimeError("Installed HocusPocus launcher authority is unavailable.")
    snapshot = _verify_install(root, launcher, stable_copy)
    manifest_digest = snapshot.manifest["manifestDigest"]
    return _installed_credential(launcher, root, manifest_digest)


def _reject_preloaded_runtime() -> None:
    if any(
        name == "hocuspocus" or name.startswith("hocuspocus.")
        for name in sys.modules
    ):
        raise RuntimeError("HocusPocus runtime was loaded before install admission.")


def _materialize_snapshot(snapshot: _InstallSnapshot, root: Path) -> None:
    for relative, content in {
        **snapshot.content,
        _MANIFEST_PATH: snapshot.manifest_content,
    }.items():
        if relative == "config/default.toml":
            content = _TOKEN_LINE.sub(b'token = "snapshot-redacted-token-00000000"', content)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except OSError as exc:
            raise RuntimeError("HocusPocus runtime snapshot could not be created.") from exc


def _audit_loaded_runtime(
    snapshot: _InstallSnapshot,
    finder: _TrustedModuleFinder | None,
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    governed = {
        row["relativePath"]: row["contentDigest"]
        for row in snapshot.manifest["files"]
    }
    receipts = []
    modules = sorted(
        name
        for name, module in sys.modules.items()
        if module is not None
        and (name == "hocuspocus" or name.startswith("hocuspocus."))
    )
    for name in modules:
        relative = (
            finder.loaded.get(name)
            if finder is not None
            else _loaded_module_relative(name, root)
        )
        if relative is None:
            raise RuntimeError("HocusPocus runtime bypassed trusted module admission.")
        content = snapshot.content.get(relative)
        digest = _digest(content) if content is not None else None
        if digest is None or governed.get(relative) != digest:
            raise RuntimeError("HocusPocus runtime module authority is stale.")
        receipts.append({
            "module": name,
            "relativePath": relative,
            "digest": digest,
        })
    return snapshot.manifest, receipts


def _loaded_module_relative(name: str, root: Path) -> str | None:
    module = sys.modules[name]
    origin = getattr(module, "__file__", None)
    try:
        return Path(origin).resolve(strict=True).relative_to(root).as_posix()
    except (OSError, TypeError, ValueError):
        return None


def _write_runtime_attestation(
    manifest: dict[str, Any],
    receipts: list[dict[str, str]],
) -> None:
    path_value = os.environ.get("HOCUSPOCUS_BROKER_ATTESTATION_PATH")
    nonce_value = os.environ.get("HOCUSPOCUS_BROKER_ATTESTATION_NONCE")
    if path_value is None and nonce_value is None:
        return
    if (
        not path_value
        or not nonce_value
        or len(nonce_value) != 64
        or any(character not in "0123456789abcdef" for character in nonce_value)
    ):
        raise RuntimeError("HocusPocus broker attestation configuration is invalid.")
    payload = {
        "schemaVersion": 1,
        "kind": "hocuspocus_broker_runtime_attestation",
        "pid": os.getpid(),
        "installManifestDigest": manifest["manifestDigest"],
        "moduleReceipts": receipts,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(
        bytes.fromhex(nonce_value), encoded, hashlib.sha256
    ).hexdigest()
    envelope = {**payload, "hmacSha256": signature}
    path = Path(path_value)
    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError("HocusPocus broker attestation destination is invalid.")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            envelope,
            stream,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        stream.write("\n")


def main() -> int:
    launcher = Path(__file__).resolve()
    try:
        _reject_preloaded_runtime()
        root, stable_copy = _active_root(launcher)
        snapshot = _verify_install(root, launcher, stable_copy)
        manifest_digest = snapshot.manifest["manifestDigest"]
        installed_credential = (
            _installed_credential(launcher, root, manifest_digest)
            if stable_copy
            else None
        )
    except Exception:
        print(
            "HocusPocus MCP broker launcher failed integrity verification.",
            file=sys.stderr,
        )
        return 1
    if not stable_copy:
        return _run_broker(
            launcher,
            root,
            snapshot,
            None,
            None,
        )
    assert installed_credential is not None
    with tempfile.TemporaryDirectory(prefix="hocuspocus-broker-") as directory:
        snapshot_root = Path(directory)
        try:
            _materialize_snapshot(snapshot, snapshot_root)
        except Exception:
            print(
                "HocusPocus MCP broker launcher failed runtime verification.",
                file=sys.stderr,
            )
            return 1
        finder = _TrustedModuleFinder(snapshot, snapshot_root)
        return _run_broker(
            launcher,
            snapshot_root,
            snapshot,
            finder,
            installed_credential,
        )


def _run_broker(
    launcher: Path,
    runtime_root: Path,
    snapshot: _InstallSnapshot,
    finder: _TrustedModuleFinder | None,
    installed_credential: _InstalledCredential | None,
) -> int:
    python_root = os.fspath(runtime_root / "python3.11libs")
    sys.path.insert(0, python_root)
    if finder is not None:
        sys.meta_path.insert(0, finder)
    try:
        from hocuspocus.core.stdio_bridge import _BrokerCredential
        from hocuspocus.core.stdio_bridge import main as broker_main

        manifest, receipts = _audit_loaded_runtime(snapshot, finder, runtime_root)
        if (
            installed_credential is not None
            and _refresh_installed_credential(launcher) != installed_credential
        ):
            raise RuntimeError("HocusPocus credential authority changed during import.")
        _write_runtime_attestation(manifest, receipts)
    except Exception:
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)
        if python_root in sys.path:
            sys.path.remove(python_root)
        print(
            "HocusPocus MCP broker launcher failed runtime verification.",
            file=sys.stderr,
        )
        return 1
    try:
        if installed_credential is None:
            return broker_main()
        credential = _BrokerCredential(
            installed_credential.secret,
            installed_credential.config_digest,
            installed_credential.manifest_digest,
        )

        def credential_provider() -> _BrokerCredential:
            refreshed = _refresh_installed_credential(launcher)
            return _BrokerCredential(
                refreshed.secret,
                refreshed.config_digest,
                refreshed.manifest_digest,
            )

        return broker_main(
            credential=credential,
            credential_provider=credential_provider,
        )
    finally:
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)
        if python_root in sys.path:
            sys.path.remove(python_root)


if __name__ == "__main__":
    raise SystemExit(main())
