"""Portable, descriptor-safe project file I/O for HocusScript source services."""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from ._workspace_native import (
    NativeWorkspaceError,
    NativeWorkspaceMissing,
    PinnedWorkspace,
)
from .workspace_patch import WorkspacePatchError, apply_unified_patch
from .project_write_lifecycle import PreparedWorkspaceWrite as _PreparedWorkspaceWrite

_LOG = logging.getLogger(__name__)
if TYPE_CHECKING:
    from .workspace_snapshot import WorkspaceNativeSnapshot

MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_FILES = 4096
MAX_WORKSPACE_DEPTH = 64
MAX_SEARCH_RESULTS = 1000
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_WINDOWS_RESERVED = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_IGNORED_SOURCE_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}
)

class WorkspaceIOError(ValueError):
    """Typed, physical-path-free workspace operation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class WorkspaceFileKind(str, Enum):
    PROJECT_MANIFEST = "project_manifest"
    MODULE_MANIFEST = "module_manifest"
    AUTHORED_SOURCE = "authored_source"
    GENERATED_LOCK = "generated_lock"
    GENERATED_CATALOG = "generated_catalog"
    DENIED = "denied"


SOURCE_READABLE_KINDS = frozenset(
    {
        WorkspaceFileKind.PROJECT_MANIFEST,
        WorkspaceFileKind.AUTHORED_SOURCE,
    }
)
SOURCE_CREATABLE_KINDS = frozenset({WorkspaceFileKind.AUTHORED_SOURCE})
GENERATED_KINDS = frozenset(
    {WorkspaceFileKind.GENERATED_LOCK, WorkspaceFileKind.GENERATED_CATALOG}
)


@dataclass(frozen=True, slots=True)
class WorkspaceRootReceipt:
    project_id: str | None
    root_identity_digest: str
    platform: str
    filesystem: str
    writable: bool
    manifest_path: str
    source_directories: tuple[str, ...]
    module_directories: tuple[str, ...]
    lock_path: str
    catalog_path: str | None

    def client_payload(self) -> dict[str, object]:
        return {
            "projectId": self.project_id,
            "platform": self.platform,
            "filesystem": self.filesystem,
            "writable": self.writable,
            "manifestPath": self.manifest_path,
            "sourceDirectories": list(self.source_directories),
            "moduleDirectories": list(self.module_directories),
            "lockPath": self.lock_path,
            "catalogPath": self.catalog_path,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceFileInfo:
    relative_path: str
    kind: WorkspaceFileKind
    raw_digest: str
    byte_length: int
    newline_style: str

    def client_payload(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "kind": self.kind.value,
            "rawDigest": self.raw_digest,
            "byteLength": self.byte_length,
            "newlineStyle": self.newline_style,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceReadReceipt:
    file: WorkspaceFileInfo
    content: str

    def client_payload(self) -> dict[str, object]:
        return {**self.file.client_payload(), "content": self.content}


@dataclass(frozen=True, slots=True)
class WorkspaceWriteReceipt:
    file: WorkspaceFileInfo
    previous_raw_digest: str | None
    created: bool

    def client_payload(self) -> dict[str, object]:
        return {
            **self.file.client_payload(),
            "previousRawDigest": self.previous_raw_digest,
            "created": self.created,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceSearchMatch:
    relative_path: str
    line: int
    column: int
    preview: str
    raw_digest: str

    def client_payload(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "line": self.line,
            "column": self.column,
            "preview": self.preview,
            "rawDigest": self.raw_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceFilePage:
    files: tuple[WorkspaceFileInfo, ...]
    next_cursor: str | None

    def client_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "files": [item.client_payload() for item in self.files]
        }
        if self.next_cursor is not None:
            payload["nextCursor"] = self.next_cursor
        return payload


@dataclass(frozen=True, slots=True)
class WorkspaceFilePolicy:
    manifest_path: str
    manifest_kind: WorkspaceFileKind
    source_directories: tuple[str, ...]
    module_directories: tuple[str, ...]
    lock_path: str
    catalog_path: str | None

    @classmethod
    def create(
        cls,
        source_directories: Iterable[str],
        module_directories: Iterable[str],
        lock_path: str,
        catalog_path: str | None,
        *,
        manifest_path: str = "hocus.project.toml",
        manifest_kind: WorkspaceFileKind = WorkspaceFileKind.PROJECT_MANIFEST,
    ) -> WorkspaceFilePolicy:
        sources = _normalize_directories(source_directories, "source")
        modules = _normalize_directories(module_directories, "module")
        lock = _portable_file_path(lock_path)
        catalog = _portable_file_path(catalog_path) if catalog_path is not None else None
        manifest = _portable_file_path(manifest_path)
        return cls(manifest, manifest_kind, sources, modules, lock, catalog)

    @property
    def authored_directories(self) -> tuple[str, ...]:
        values = {*self.source_directories, *self.module_directories}
        return tuple(sorted(values, key=_portable_key))

    def classify(self, relative_path: str) -> WorkspaceFileKind:
        key = _portable_key(relative_path)
        if key == _portable_key(self.manifest_path):
            return self.manifest_kind
        if key == _portable_key(self.lock_path):
            return WorkspaceFileKind.GENERATED_LOCK
        if self.catalog_path is not None and key == _portable_key(self.catalog_path):
            return WorkspaceFileKind.GENERATED_CATALOG
        if relative_path.casefold().endswith(".hocus") and any(
            _path_is_within(relative_path, directory)
            for directory in self.authored_directories
        ):
            return WorkspaceFileKind.AUTHORED_SOURCE
        return WorkspaceFileKind.DENIED


class WorkspaceIO:
    """Pinned project I/O. Native paths never leave this object."""

    def __init__(
        self,
        native: PinnedWorkspace,
        policy: WorkspaceFilePolicy,
        *,
        project_id: str | None,
        writable: bool,
        external_root_identities: (
            Mapping[str, str] | Iterable[tuple[str, str]] | None
        ) = None,
    ):
        self._native = native
        self.policy = policy
        self.project_id = project_id
        self.writable = writable
        self._external_root_identities = _validated_identity_mapping(
            external_root_identities or {}
        )
        self._cursor_secret = hashlib.sha256(
            b"hocus.workspace.glob.cursor.v1\0"
            + native.root_info.identity_digest.encode("ascii")
        ).digest()

    @classmethod
    def open_project(
        cls,
        approved_root: object,
        *,
        source_directories: Iterable[str] | None = None,
        module_directories: Iterable[str] | None = None,
        lock_path: str | None = None,
        catalog_path: str | None = None,
        writable: bool = False,
    ) -> WorkspaceIO:
        """Pin an approved authority record or explicit native project root."""

        root, project_id, projection = _approved_root_parts(approved_root)
        sources = (
            source_directories
            if source_directories is not None
            else _projection_value(projection, "source_directories", ("source",))
        )
        modules = (
            module_directories
            if module_directories is not None
            else _projection_value(projection, "module_directories", ())
        )
        resolved_lock = (
            lock_path
            if lock_path is not None
            else _projection_value(projection, "lock_path", "hocus.lock.json")
        )
        resolved_catalog = (
            catalog_path
            if catalog_path is not None
            else _projection_value(projection, "catalog_path", None)
        )
        policy = WorkspaceFilePolicy.create(
            sources, modules, resolved_lock, resolved_catalog
        )
        external_identities = _validated_identity_mapping(
            getattr(approved_root, "external_root_identities", {})
        )
        try:
            native = PinnedWorkspace(root)
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc) from exc
        expected_identity = getattr(approved_root, "root_identity_digest", None)
        _require_expected_root_identity(native, expected_identity)
        expected_manifest_identity = getattr(
            approved_root, "manifest_identity_digest", None
        )
        _require_expected_manifest_identity(
            native,
            policy.manifest_path,
            expected_manifest_identity,
        )
        return cls(
            native,
            policy,
            project_id=project_id,
            writable=bool(writable),
            external_root_identities=external_identities,
        )

    @classmethod
    def open_external(
        cls,
        alias_root: object,
        *,
        expected_identity: str | None = None,
    ) -> WorkspaceIO:
        """Pin one approved external module root as a read-only source scope."""

        policy = WorkspaceFilePolicy.create(
            (".",),
            (),
            "hocus.lock.json",
            None,
            manifest_path="hocus.module.toml",
            manifest_kind=WorkspaceFileKind.MODULE_MANIFEST,
        )
        root, project_id, _ = _approved_root_parts(alias_root)
        if expected_identity is None:
            expected_identity = getattr(alias_root, "root_identity_digest", None)
        try:
            native = PinnedWorkspace(root)
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc) from exc
        _require_expected_root_identity(native, expected_identity)
        return cls(native, policy, project_id=project_id, writable=False)

    def close(self) -> None:
        try:
            self._close_strict()
        except Exception:
            _LOG.warning("HOCUS828 workspace handle cleanup deferred")

    def _close_strict(self) -> None:
        self._native.close()

    def inspect(self) -> WorkspaceRootReceipt:
        try:
            self._native.assert_current()
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc) from exc
        root = self._native.root_info
        return WorkspaceRootReceipt(
            project_id=self.project_id,
            root_identity_digest=root.identity_digest,
            platform=root.platform,
            filesystem=root.filesystem,
            writable=self.writable,
            manifest_path=self.policy.manifest_path,
            source_directories=self.policy.source_directories,
            module_directories=self.policy.module_directories,
            lock_path=self.policy.lock_path,
            catalog_path=self.policy.catalog_path,
        )

    def enumerate_files(
        self,
        *,
        include_manifest: bool = True,
        include_generated: bool = False,
        max_files: int = MAX_WORKSPACE_FILES,
        max_depth: int = MAX_WORKSPACE_DEPTH,
    ) -> tuple[WorkspaceFileInfo, ...]:
        _require_bound(max_files, 1, MAX_WORKSPACE_FILES, "file count")
        _require_bound(max_depth, 1, MAX_WORKSPACE_DEPTH, "directory depth")
        paths = self._enumerated_authored_paths(max_files=max_files, max_depth=max_depth)
        if (
            include_manifest
            and self.policy.manifest_kind is WorkspaceFileKind.PROJECT_MANIFEST
        ):
            paths.add(self.policy.manifest_path)
        if include_generated:
            paths.update(_generated_paths(self.policy))
        if len(paths) > max_files:
            raise WorkspaceIOError("HOCUS825", "Workspace file count exceeds limit.")
        _reject_portable_collisions(paths)
        kinds = SOURCE_READABLE_KINDS | (GENERATED_KINDS if include_generated else frozenset())
        return tuple(
            self._inspect_file(path, allowed_kinds=kinds)
            for path in sorted(paths, key=_portable_key)
        )

    def glob(
        self,
        pattern: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        case_sensitive: bool = True,
        include_generated: bool = False,
    ) -> WorkspaceFilePage:
        """Return a deterministic portable filename page with an authenticated cursor."""

        normalized_pattern = _portable_glob(pattern)
        _require_bound(limit, 1, 500, "glob result")
        after = self._decode_cursor(
            cursor,
            pattern=normalized_pattern,
            case_sensitive=case_sensitive,
            include_generated=include_generated,
        )
        files = self.enumerate_files(
            include_manifest=True,
            include_generated=include_generated,
        )
        matches = [
            item
            for item in files
            if _glob_matches(
                item.relative_path,
                normalized_pattern,
                case_sensitive=case_sensitive,
            )
            and (after is None or _portable_key(item.relative_path) > after)
        ]
        page = tuple(matches[:limit])
        next_cursor = None
        if len(matches) > limit:
            next_cursor = self._encode_cursor(
                pattern=normalized_pattern,
                case_sensitive=case_sensitive,
                include_generated=include_generated,
                after=_portable_key(page[-1].relative_path),
            )
        return WorkspaceFilePage(page, next_cursor)

    def read(
        self,
        relative_path: str,
        *,
        allowed_kinds: Iterable[WorkspaceFileKind] = SOURCE_READABLE_KINDS,
        max_bytes: int = MAX_WORKSPACE_FILE_BYTES,
    ) -> WorkspaceReadReceipt:
        path, kind = self._admit(relative_path, allowed_kinds)
        _require_bound(max_bytes, 1, MAX_WORKSPACE_FILE_BYTES, "read byte")
        raw = self._read_raw(path, max_bytes)
        text = _strict_workspace_text(raw)
        return WorkspaceReadReceipt(_file_info(path, kind, raw), text)

    def search(
        self,
        query: str,
        *,
        path_prefix: str | None = None,
        case_sensitive: bool = True,
        include_manifest: bool = True,
        max_results: int = 100,
    ) -> tuple[WorkspaceSearchMatch, ...]:
        if not isinstance(query, str) or not query or len(query) > 256:
            raise WorkspaceIOError("HOCUS825", "Search query must contain 1 to 256 characters.")
        _require_bound(max_results, 1, MAX_SEARCH_RESULTS, "search result")
        prefix = _portable_directory_path(path_prefix) if path_prefix is not None else None
        files = self.enumerate_files(
            include_manifest=include_manifest,
            include_generated=False,
        )
        matches: list[WorkspaceSearchMatch] = []
        needle = query if case_sensitive else query.casefold()
        for file in files:
            if prefix is not None and not _path_is_within(file.relative_path, prefix):
                continue
            receipt = self.read(file.relative_path)
            _append_search_matches(
                matches,
                receipt,
                needle,
                case_sensitive=case_sensitive,
                max_results=max_results,
            )
            if len(matches) >= max_results:
                break
        return tuple(matches)

    def read_generated(
        self,
        relative_path: str,
        *,
        allowed_kinds: Iterable[WorkspaceFileKind] = GENERATED_KINDS,
        max_bytes: int | None = None,
    ) -> WorkspaceReadReceipt:
        """Read an admitted generated artifact and retain its raw CAS digest."""

        path, kind = self._admit(relative_path, allowed_kinds)
        hard_limit = _generated_file_byte_limit(kind)
        read_limit = hard_limit if max_bytes is None else max_bytes
        _require_bound(read_limit, 1, hard_limit, "generated read byte")
        raw = self._read_raw(path, read_limit)
        text = _strict_workspace_text(raw)
        return WorkspaceReadReceipt(_file_info(path, kind, raw), text)

    def generated_digest(
        self,
        relative_path: str,
        *,
        allowed_kinds: Iterable[WorkspaceFileKind] = (
            WorkspaceFileKind.GENERATED_LOCK,
        ),
    ) -> str:
        """Return the raw byte digest required for generated-file CAS publication."""

        return self.read_generated(
            relative_path, allowed_kinds=allowed_kinds
        ).file.raw_digest

    def create(
        self,
        relative_path: str,
        content: str | bytes,
    ) -> WorkspaceWriteReceipt:
        prepared = self._prepare_create(relative_path, content)
        return self._commit_prepared(prepared)

    def apply_patch(
        self,
        relative_path: str,
        patch: str | bytes,
        *,
        expected_digest: str,
        max_operations: int = 64,
    ) -> WorkspaceWriteReceipt:
        prepared = self._prepare_patch(
            relative_path, patch,
            expected_digest=expected_digest,
            max_operations=max_operations,
        )
        return self._commit_prepared(prepared)

    def _prepare_create(
        self,
        relative_path: str,
        content: str | bytes,
    ) -> _PreparedWorkspaceWrite:
        return self._prepare_publish(
            relative_path, content,
            create=True,
            allowed_kinds=SOURCE_CREATABLE_KINDS,
        )

    def _prepare_patch(
        self,
        relative_path: str,
        patch: str | bytes,
        *,
        expected_digest: str,
        max_operations: int = 64,
    ) -> _PreparedWorkspaceWrite:
        path, kind = self._admit(relative_path, SOURCE_READABLE_KINDS)
        expected = _expected_digest(expected_digest)
        raw = self._read_raw(path, MAX_WORKSPACE_FILE_BYTES)
        if _raw_digest(raw) != expected:
            raise WorkspaceIOError("HOCUS826", "Workspace file digest conflict.", {"path": path})
        try:
            patched = apply_unified_patch(
                raw,
                patch,
                path,
                max_operations=max_operations,
            )
        except WorkspacePatchError as exc:
            raise WorkspaceIOError(exc.code, exc.message, {"path": path}) from exc
        return self._prepared_write(
            path,
            kind,
            patched.content,
            expected_digest=expected,
            create=False,
        )

    def publish(
        self,
        relative_path: str,
        content: str | bytes,
        *,
        expected_digest: str | None = None,
        create: bool = False,
        allowed_kinds: Iterable[WorkspaceFileKind] = SOURCE_READABLE_KINDS,
    ) -> WorkspaceWriteReceipt:
        prepared = self._prepare_publish(
            relative_path, content,
            expected_digest=expected_digest,
            create=create,
            allowed_kinds=allowed_kinds,
        )
        return self._commit_prepared(prepared)

    def _prepare_publish(
        self,
        relative_path: str,
        content: str | bytes,
        *,
        expected_digest: str | None = None,
        create: bool = False,
        allowed_kinds: Iterable[WorkspaceFileKind] = SOURCE_READABLE_KINDS,
    ) -> _PreparedWorkspaceWrite:
        path, kind = self._admit(relative_path, allowed_kinds)
        raw = _workspace_bytes(content)
        expected = None if create else _expected_digest(expected_digest)
        if create and expected_digest is not None:
            raise WorkspaceIOError("HOCUS826", "Create publication cannot carry a prior digest.")
        return self._prepared_write(
            path,
            kind,
            raw,
            expected_digest=expected,
            create=create,
        )

    def native_snapshot(
        self,
        include_external_roots: Mapping[str, Path] | None = None,
        writable_generated: bool = False,
    ) -> WorkspaceNativeSnapshot:
        """Build a private bounded closure for legacy native project consumers."""

        from .workspace_snapshot import create_native_snapshot

        return create_native_snapshot(
            self,
            include_external_roots=include_external_roots,
            writable_generated=writable_generated,
        )

    def _prepared_write(
        self,
        path: str,
        kind: WorkspaceFileKind,
        raw: bytes,
        *,
        expected_digest: str | None,
        create: bool,
    ) -> _PreparedWorkspaceWrite:
        if not self.writable:
            raise WorkspaceIOError("HOCUS828", "Workspace authority is read-only.")
        receipt = WorkspaceWriteReceipt(
            file=_file_info(path, kind, raw),
            previous_raw_digest=expected_digest,
            created=create,
        )
        return _PreparedWorkspaceWrite(
            self, path, kind, raw, expected_digest, create, receipt,
        )

    def _commit_prepared(
        self,
        prepared: _PreparedWorkspaceWrite,
    ) -> WorkspaceWriteReceipt:
        if (
            not isinstance(prepared, _PreparedWorkspaceWrite)
            or prepared.owner is not self
        ):
            raise WorkspaceIOError(
                "HOCUS828", "Prepared workspace publication is invalid."
            )
        try:
            self._native.publish(
                tuple(prepared.path.split("/")),
                prepared.raw,
                expected_digest=prepared.expected_digest,
                create=prepared.create,
            )
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, prepared.path) from exc
        return prepared.receipt

    def _enumerated_authored_paths(self, *, max_files: int, max_depth: int) -> set[str]:
        paths: set[str] = set()
        for directory in self.policy.authored_directories:
            parts = () if directory == "." else tuple(directory.split("/"))
            try:
                rows = self._native.enumerate_files(
                    parts,
                    max_files=max_files,
                    max_depth=max_depth,
                    file_suffix=".hocus",
                    excluded_directories=_IGNORED_SOURCE_DIRECTORIES,
                )
            except NativeWorkspaceError as exc:
                raise _workspace_error(exc) from exc
            paths.update(path for path in rows if self.policy.classify(path) is WorkspaceFileKind.AUTHORED_SOURCE)
            if len(paths) > max_files:
                raise WorkspaceIOError("HOCUS825", "Workspace file count exceeds limit.")
        return paths

    def _inspect_file(
        self,
        relative_path: str,
        *,
        allowed_kinds: Iterable[WorkspaceFileKind],
    ) -> WorkspaceFileInfo:
        path, kind = self._admit(relative_path, allowed_kinds)
        raw = self._read_raw(path, MAX_WORKSPACE_FILE_BYTES)
        _strict_workspace_text(raw)
        return _file_info(path, kind, raw)

    def _read_raw(self, path: str, max_bytes: int) -> bytes:
        try:
            return self._native.read(tuple(path.split("/")), max_bytes)
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, path) from exc

    def _strict_identity(self, path: str) -> str:
        try:
            return self._native.inspect_identity(tuple(path.split("/")))
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, path) from exc

    def _read_optional_raw(self, path: str, max_bytes: int) -> bytes | None:
        try:
            return self._native.read(tuple(path.split("/")), max_bytes)
        except NativeWorkspaceMissing:
            return None
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, path) from exc

    def _encode_cursor(
        self,
        *,
        pattern: str,
        case_sensitive: bool,
        include_generated: bool,
        after: str,
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "root": self._native.root_info.identity_digest,
                "pattern": pattern,
                "caseSensitive": case_sensitive,
                "includeGenerated": include_generated,
                "after": after,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.digest(self._cursor_secret, payload, "sha256")
        return _base64url(payload + signature)

    def _decode_cursor(
        self,
        cursor: str | None,
        *,
        pattern: str,
        case_sensitive: bool,
        include_generated: bool,
    ) -> str | None:
        if cursor is None:
            return None
        payload = _authenticated_cursor_payload(cursor, self._cursor_secret)
        expected = {
            "v": 1,
            "root": self._native.root_info.identity_digest,
            "pattern": pattern,
            "caseSensitive": case_sensitive,
            "includeGenerated": include_generated,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise WorkspaceIOError("HOCUS825", "Workspace glob cursor does not match the request.")
        after = payload.get("after")
        if not isinstance(after, str) or not after:
            raise WorkspaceIOError("HOCUS825", "Workspace glob cursor is malformed.")
        return after

    def _admit(
        self,
        relative_path: str,
        allowed_kinds: Iterable[WorkspaceFileKind],
    ) -> tuple[str, WorkspaceFileKind]:
        path = _portable_file_path(relative_path)
        kind = self.policy.classify(path)
        admitted = frozenset(allowed_kinds)
        if (
            kind is WorkspaceFileKind.DENIED
            or kind not in admitted
            or WorkspaceFileKind.DENIED in admitted
        ):
            raise WorkspaceIOError(
                "HOCUS823",
                "Workspace path is not admitted by this file operation.",
                {"path": path, "kind": kind.value},
            )
        return path, kind

    def __enter__(self) -> WorkspaceIO:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _approved_root_parts(value: object) -> tuple[Path, str | None, object | None]:
    if isinstance(value, (str, Path)):
        return Path(value), None, None
    root = getattr(value, "approved_root", None)
    if root is None:
        root = getattr(value, "root", None)
    if not isinstance(root, Path):
        raise WorkspaceIOError("HOCUS822", "Approved workspace authority has no native root.")
    project_id = getattr(value, "project_id", None)
    if project_id is not None and not isinstance(project_id, str):
        raise WorkspaceIOError("HOCUS822", "Approved workspace project identity is malformed.")
    return root, project_id, getattr(value, "projection", None)


def _require_expected_root_identity(
    native: PinnedWorkspace,
    expected: object,
) -> None:
    if expected is None:
        return
    if (
        not isinstance(expected, str)
        or _DIGEST.fullmatch(expected) is None
        or not hmac.compare_digest(native.root_info.identity_digest, expected)
    ):
        native.close()
        raise WorkspaceIOError(
            "HOCUS824", "Pinned workspace root does not match approved root identity."
        )


def _require_expected_manifest_identity(
    native: PinnedWorkspace,
    manifest_path: str,
    expected: object,
) -> None:
    if expected is None:
        return
    try:
        actual = native.inspect_identity(tuple(manifest_path.split("/")))
    except NativeWorkspaceError as exc:
        native.close()
        raise _workspace_error(exc) from exc
    if (
        not isinstance(expected, str)
        or _DIGEST.fullmatch(expected) is None
        or not hmac.compare_digest(actual, expected)
    ):
        native.close()
        raise WorkspaceIOError(
            "HOCUS824",
            "Pinned project manifest does not match approved object identity.",
        )


def _validated_identity_mapping(
    values: Mapping[str, str] | Iterable[tuple[str, str]],
) -> dict[str, str]:
    try:
        rows = tuple(values.items()) if isinstance(values, Mapping) else tuple(values)
    except TypeError as exc:
        raise WorkspaceIOError(
            "HOCUS824", "External root identity mapping is malformed."
        ) from exc
    if len(rows) > 64:
        raise WorkspaceIOError("HOCUS824", "External root identity mapping is malformed.")
    output: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 2:
            raise WorkspaceIOError("HOCUS824", "External root identity mapping is malformed.")
        alias, digest = row
        if (
            not isinstance(alias, str)
            or not alias
            or len(alias) > 128
            or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None
            or alias.casefold() in output
        ):
            raise WorkspaceIOError("HOCUS824", "External root identity mapping is malformed.")
        output[alias.casefold()] = digest
    return output


def _projection_value(projection: object | None, field: str, default: Any) -> Any:
    if projection is None:
        return default
    if isinstance(projection, dict):
        return projection.get(field, projection.get(_camel_case(field), default))
    return getattr(projection, field, default)


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


def _normalize_directories(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise WorkspaceIOError("HOCUS823", f"Workspace {label} directories must be an array.")
    try:
        paths = tuple(_portable_directory_path(value) for value in values)
    except TypeError as exc:
        raise WorkspaceIOError(
            "HOCUS823", f"Workspace {label} directories must be an array."
        ) from exc
    if len(paths) > 64:
        raise WorkspaceIOError("HOCUS823", f"Workspace {label} directory count exceeds limit.")
    keys = [_portable_key(path) for path in paths]
    if len(set(keys)) != len(keys):
        raise WorkspaceIOError(
            "HOCUS823", f"Workspace {label} directories contain portable aliases."
        )
    return paths


def _portable_directory_path(value: object) -> str:
    if value == ".":
        return "."
    return _portable_file_path(value)


def _portable_file_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise WorkspaceIOError("HOCUS823", "Workspace path must be a bounded relative path.")
    if (
        value != value.strip()
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise WorkspaceIOError("HOCUS823", "Workspace path is not portable.", {"path": value})
    for part in value.split("/"):
        _validate_portable_segment(part, value)
    return value


def _portable_glob(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise WorkspaceIOError("HOCUS823", "Workspace glob must be a bounded pattern.")
    if (
        value != value.strip()
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or value != unicodedata.normalize("NFC", value)
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise WorkspaceIOError("HOCUS823", "Workspace glob pattern is not portable.")
    return value


def _glob_matches(path: str, pattern: str, *, case_sensitive: bool) -> bool:
    if "/" not in pattern:
        name = path.rsplit("/", 1)[-1]
        if not case_sensitive:
            name, pattern = name.casefold(), pattern.casefold()
        return fnmatch.fnmatchcase(name, pattern)
    path_parts = path.split("/")
    pattern_parts = pattern.split("/")
    if not case_sensitive:
        path_parts = [part.casefold() for part in path_parts]
        pattern_parts = [part.casefold() for part in pattern_parts]
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending:
        pattern_index, path_index = pending.pop()
        state = pattern_index, path_index
        if state in visited:
            continue
        visited.add(state)
        if pattern_index == len(pattern_parts):
            if path_index == len(path_parts):
                return True
            continue
        segment = pattern_parts[pattern_index]
        if segment == "**":
            pending.append((pattern_index + 1, path_index))
            if path_index < len(path_parts):
                pending.append((pattern_index, path_index + 1))
        elif path_index < len(path_parts) and fnmatch.fnmatchcase(
            path_parts[path_index], segment
        ):
            pending.append((pattern_index + 1, path_index + 1))
    return False


def _validate_portable_segment(part: str, path: str) -> None:
    if (
        part != unicodedata.normalize("NFC", part)
        or part.endswith((" ", "."))
        or any(ord(char) < 32 or ord(char) == 127 for char in part)
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
    ):
        raise WorkspaceIOError(
            "HOCUS823", "Workspace path contains a nonportable segment.", {"path": path}
        )


def _path_is_within(path: str, directory: str) -> bool:
    if directory == ".":
        return True
    path_key = _portable_key(path)
    directory_key = _portable_key(directory)
    return path_key == directory_key or path_key.startswith(directory_key + "/")


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _generated_paths(policy: WorkspaceFilePolicy) -> set[str]:
    output = {policy.lock_path}
    if policy.catalog_path is not None:
        output.add(policy.catalog_path)
    return output


def _generated_file_byte_limit(kind: WorkspaceFileKind) -> int:
    if kind is WorkspaceFileKind.GENERATED_CATALOG:
        from .catalog import MAX_CATALOG_BYTES

        return MAX_CATALOG_BYTES
    if kind is WorkspaceFileKind.GENERATED_LOCK:
        from .project import MAX_LOCK_BYTES_V3

        return MAX_LOCK_BYTES_V3
    raise WorkspaceIOError("HOCUS823", "Generated file kind is not admitted.")


def _reject_portable_collisions(paths: Iterable[str]) -> None:
    seen: dict[str, str] = {}
    for path in paths:
        key = _portable_key(path)
        previous = seen.get(key)
        if previous is not None and previous != path:
            raise WorkspaceIOError(
                "HOCUS824", "Workspace contains portable path aliases."
            )
        seen[key] = path


def _strict_workspace_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise WorkspaceIOError("HOCUS825", "Workspace text cannot contain a UTF-8 byte-order mark.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceIOError("HOCUS825", "Workspace text must be strict UTF-8.") from exc
    _newline_style(raw)
    if "\x00" in text:
        raise WorkspaceIOError("HOCUS825", "Workspace text cannot contain NUL characters.")
    return text


def _workspace_bytes(content: str | bytes) -> bytes:
    if isinstance(content, str):
        try:
            raw = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise WorkspaceIOError("HOCUS825", "Workspace text must be valid Unicode.") from exc
    elif isinstance(content, bytes):
        raw = content
    else:
        raise WorkspaceIOError("HOCUS825", "Workspace publication requires UTF-8 text.")
    if len(raw) > MAX_WORKSPACE_FILE_BYTES:
        raise WorkspaceIOError("HOCUS825", "Workspace publication exceeds the byte limit.")
    _strict_workspace_text(raw)
    return raw


def _file_info(path: str, kind: WorkspaceFileKind, raw: bytes) -> WorkspaceFileInfo:
    return WorkspaceFileInfo(
        relative_path=path,
        kind=kind,
        raw_digest=_raw_digest(raw),
        byte_length=len(raw),
        newline_style=_newline_style(raw),
    )


def _raw_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _newline_style(raw: bytes) -> str:
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\r" in without_crlf:
        raise WorkspaceIOError("HOCUS825", "Workspace text contains a lone carriage return.")
    has_crlf = b"\r\n" in raw
    has_lf = b"\n" in without_crlf
    if has_crlf and has_lf:
        raise WorkspaceIOError("HOCUS825", "Workspace text mixes LF and CRLF newlines.")
    if has_crlf:
        return "crlf"
    if has_lf:
        return "lf"
    return "none"


def _expected_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise WorkspaceIOError("HOCUS826", "Expected raw digest is malformed.")
    return value


def _require_bound(value: object, minimum: int, maximum: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise WorkspaceIOError("HOCUS825", f"Workspace {label} limit is malformed.")


def _append_search_matches(
    output: list[WorkspaceSearchMatch],
    receipt: WorkspaceReadReceipt,
    needle: str,
    *,
    case_sensitive: bool,
    max_results: int,
) -> None:
    for line_number, line in enumerate(receipt.content.splitlines(), start=1):
        candidate = line if case_sensitive else line.casefold()
        start = 0
        while len(output) < max_results:
            index = candidate.find(needle, start)
            if index < 0:
                break
            output.append(
                WorkspaceSearchMatch(
                    relative_path=receipt.file.relative_path,
                    line=line_number,
                    column=index + 1,
                    preview=_search_preview(line),
                    raw_digest=receipt.file.raw_digest,
                )
            )
            start = index + max(len(needle), 1)
        if len(output) >= max_results:
            return


def _search_preview(line: str) -> str:
    clean = "".join(char if char == "\t" or ord(char) >= 32 else "\ufffd" for char in line)
    return clean if len(clean) <= 240 else clean[:239] + "\u2026"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _authenticated_cursor_payload(
    cursor: object,
    secret: bytes,
) -> dict[str, object]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
        raise WorkspaceIOError("HOCUS825", "Workspace glob cursor is malformed.")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload, signature = raw[:-32], raw[-32:]
        if len(raw) <= 32 or not hmac.compare_digest(
            signature, hmac.digest(secret, payload, "sha256")
        ):
            raise ValueError("cursor signature")
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceIOError("HOCUS825", "Workspace glob cursor is malformed.") from exc
    if not isinstance(decoded, dict):
        raise WorkspaceIOError("HOCUS825", "Workspace glob cursor is malformed.")
    return decoded


def _workspace_error(
    error: NativeWorkspaceError,
    relative_path: str | None = None,
) -> WorkspaceIOError:
    details = {"path": relative_path} if relative_path is not None else None
    return WorkspaceIOError(error.code, error.message, details)


__all__ = [
    "GENERATED_KINDS", "MAX_SEARCH_RESULTS", "MAX_WORKSPACE_DEPTH",
    "MAX_WORKSPACE_FILE_BYTES", "MAX_WORKSPACE_FILES", "SOURCE_CREATABLE_KINDS",
    "SOURCE_READABLE_KINDS", "WorkspaceFileInfo", "WorkspaceFileKind",
    "WorkspaceFilePage", "WorkspaceFilePolicy", "WorkspaceIO", "WorkspaceIOError",
    "WorkspaceReadReceipt", "WorkspaceRootReceipt", "WorkspaceSearchMatch",
    "WorkspaceWriteReceipt",
]
