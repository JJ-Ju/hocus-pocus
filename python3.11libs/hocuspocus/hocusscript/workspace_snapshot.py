"""Private temporary project closures for legacy path-based HocusScript consumers."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ._workspace_native import (
    NativeWorkspaceError,
    NativeWorkspaceMissing,
    PinnedWorkspace,
)
from .workspace_io import (
    GENERATED_KINDS,
    MAX_WORKSPACE_DEPTH,
    MAX_WORKSPACE_FILE_BYTES,
    MAX_WORKSPACE_FILES,
    WorkspaceIO,
    WorkspaceIOError,
    _generated_file_byte_limit,
    _portable_file_path,
    _raw_digest,
    _reject_portable_collisions,
    _strict_workspace_text,
    _workspace_error,
)

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_EXTERNAL_ROOTS = 32
_ALIAS = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Origin:
    workspace: WorkspaceIO
    relative_path: str
    raw_digest: str | None
    native_identity: str
    optional: bool
    max_bytes: int


@dataclass(frozen=True, slots=True)
class _SnapshotFile:
    relative_path: str
    content: bytes
    generated: bool


@dataclass(frozen=True, slots=True)
class _Enumeration:
    workspace: WorkspaceIO
    paths: frozenset[str]
    manifest_path: str
    generated_paths: tuple[str, ...] = ()


@dataclass(slots=True)
class _CollectionBudget:
    remaining_files: int = MAX_WORKSPACE_FILES
    remaining_bytes: int = MAX_SNAPSHOT_BYTES

    def read(
        self,
        workspace: WorkspaceIO,
        path: str,
        maximum: int,
    ) -> tuple[bytes, str]:
        if self.remaining_files <= 0 or self.remaining_bytes <= 0:
            raise WorkspaceIOError(
                "HOCUS825", "Workspace snapshot exceeds its collection budget."
            )
        available = self.remaining_bytes
        self.remaining_files -= 1
        raw, identity = _read_with_identity(
            workspace, path, min(maximum, available)
        )
        if len(raw) > available:
            raise WorkspaceIOError(
                "HOCUS825", "Workspace snapshot exceeds its collection budget."
            )
        self.remaining_bytes -= len(raw)
        return raw, identity


class WorkspaceNativeSnapshot:
    """Context-managed, private native closure; never serialize its paths."""

    project: None = None

    def __init__(
        self,
        owner: tempfile.TemporaryDirectory[str],
        *,
        root: Path,
        external_roots: Mapping[str, Path],
        snapshot_native: PinnedWorkspace,
        external_snapshot_natives: tuple[
            tuple[PinnedWorkspace, Mapping[str, str]], ...
        ],
        external_scopes: tuple[WorkspaceIO, ...],
        origins: tuple[_Origin, ...],
        enumerations: tuple[_Enumeration, ...],
        snapshot_digests: Mapping[str, str],
        generated_paths: frozenset[str],
        generated_limits: Mapping[str, int],
    ):
        self._owner = owner
        self.root = root
        self.external_roots = MappingProxyType(dict(external_roots))
        self._snapshot_native = snapshot_native
        self._external_snapshot_natives = external_snapshot_natives
        self._external_scopes = external_scopes
        self._origins = origins
        self._enumerations = enumerations
        self._snapshot_digests = dict(snapshot_digests)
        self._generated_paths = generated_paths
        self._generated_limits = dict(generated_limits)
        self._closed = False

    def recheck(self) -> None:
        """Fail if an authority input or immutable snapshot input changed."""

        self._require_open()
        opening = _observe_enumerations(self._enumerations)
        _recheck_enumerations(self._enumerations, opening)
        _recheck_origins(self._origins)
        _recheck_snapshot_files(
            self._snapshot_native,
            self._snapshot_digests,
            self._generated_limits,
        )
        _recheck_external_snapshot_files(self._external_snapshot_natives)
        closing = _observe_enumerations(self._enumerations)
        _recheck_enumerations(self._enumerations, closing)

    def read_generated(self, relative_path: str) -> bytes:
        """Read a generated snapshot artifact through the pinned snapshot root."""

        self._require_open()
        path = _portable_file_path(relative_path)
        if path not in self._generated_paths:
            raise WorkspaceIOError(
                "HOCUS823", "Snapshot path is not an admitted generated artifact."
            )
        try:
            raw = self._snapshot_native.read(
                tuple(path.split("/")), self._generated_limits[path]
            )
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, path) from exc
        _strict_workspace_text(raw)
        return raw

    def close(self) -> None:
        if self._closed:
            return
        failures = _cleanup_snapshot_resources(
            self._owner,
            snapshot_native=self._snapshot_native,
            external_snapshot_natives=self._external_snapshot_natives,
            external_scopes=self._external_scopes,
        )
        self._closed = True
        if failures:
            raise WorkspaceIOError(
                "HOCUS828",
                "Workspace snapshot cleanup failed.",
                {
                    "failureCount": len(failures),
                    "stages": sorted(set(failures)),
                },
            )

    def _require_open(self) -> None:
        if self._closed:
            raise WorkspaceIOError("HOCUS824", "Workspace snapshot is closed.")

    def __enter__(self) -> WorkspaceNativeSnapshot:
        self._require_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _observe_enumerations(
    enumerations: tuple[_Enumeration, ...],
) -> tuple[frozenset[str], ...]:
    return tuple(_current_paths(item) for item in enumerations)


def _recheck_enumerations(
    enumerations: tuple[_Enumeration, ...],
    observed: tuple[frozenset[str], ...],
) -> None:
    for enumeration, paths in zip(enumerations, observed, strict=True):
        if paths != enumeration.paths:
            raise WorkspaceIOError(
                "HOCUS824", "Workspace snapshot path set changed."
            )


def _recheck_origins(origins: tuple[_Origin, ...]) -> None:
    for origin in origins:
        try:
            raw, identity = _read_with_identity(
                origin.workspace,
                origin.relative_path, origin.max_bytes
            )
        except WorkspaceIOError as exc:
            raise WorkspaceIOError(
                "HOCUS824", "Workspace snapshot input identity changed."
            ) from exc
        if (
            identity != origin.native_identity
            or origin.raw_digest is None
            or _raw_digest(raw) != origin.raw_digest
        ):
            raise WorkspaceIOError(
                "HOCUS824", "Workspace snapshot input identity or bytes changed."
            )


def _read_with_identity(
    workspace: WorkspaceIO,
    path: str,
    maximum: int,
) -> tuple[bytes, str]:
    before = workspace._strict_identity(path)
    raw = workspace._read_raw(path, maximum)
    after = workspace._strict_identity(path)
    if before != after:
        raise WorkspaceIOError(
            "HOCUS824", "Workspace file identity changed during read."
        )
    return raw, after


def _recheck_snapshot_files(
    native: PinnedWorkspace,
    digests: Mapping[str, str],
    limits: Mapping[str, int],
) -> None:
    for path, digest in digests.items():
        try:
            raw = native.read(
                tuple(path.split("/")),
                limits.get(path, MAX_WORKSPACE_FILE_BYTES),
            )
        except NativeWorkspaceError as exc:
            raise _workspace_error(exc, path) from exc
        if _raw_digest(raw) != digest:
            raise WorkspaceIOError("HOCUS824", "Workspace snapshot bytes changed.")


def _recheck_external_snapshot_files(
    snapshots: tuple[tuple[PinnedWorkspace, Mapping[str, str]], ...],
) -> None:
    for native, digests in snapshots:
        _recheck_snapshot_files(native, digests, {})


def create_native_snapshot(
    workspace: WorkspaceIO,
    *,
    include_external_roots: Mapping[str, Path] | None,
    writable_generated: bool,
) -> WorkspaceNativeSnapshot:
    """Materialize one bounded closure exclusively from authenticated reads."""

    aliases = _validated_alias_roots(include_external_roots or {})
    try:
        owner = tempfile.TemporaryDirectory(prefix="hocus-workspace-")
    except OSError as exc:
        raise WorkspaceIOError(
            "HOCUS828", "Workspace snapshot allocation failed."
        ) from exc
    base = Path(owner.name)
    root = base / "project"
    external_base = base / "external"
    scopes: list[WorkspaceIO] = []
    external_snapshot_natives: list[tuple[PinnedWorkspace, Mapping[str, str]]] = []
    snapshot_native: PinnedWorkspace | None = None
    budget = _CollectionBudget()
    try:
        root.mkdir()
        external_base.mkdir()
        main_files, main_origins, main_enumeration = _collect_main_files(
            workspace, budget,
        )
        (
            external_files,
            external_origins,
            external_paths,
            external_enumerations,
        ) = _collect_external_files(
            aliases,
            external_base,
            scopes,
            budget,
            expected_identities=workspace._external_root_identities,
        )
        all_files = (*main_files, *external_files)
        _require_snapshot_bounds(all_files)
        _create_policy_directories(root, workspace)
        snapshot_digests = _materialize_files(
            root,
            main_files,
            writable_generated=writable_generated,
        )
        for alias, destination, files in external_paths:
            destination.mkdir(parents=True)
            digests = _materialize_files(
                destination, files, writable_generated=False
            )
            external_snapshot_natives.append(
                (PinnedWorkspace(destination), digests)
            )
        generated_paths = frozenset(
            path
            for path in (workspace.policy.lock_path, workspace.policy.catalog_path)
            if path is not None
        )
        generated_limits = {
            path: _generated_file_byte_limit(workspace.policy.classify(path))
            for path in generated_paths
        }
        _create_generated_parents(root, generated_paths)
        snapshot_native = PinnedWorkspace(root)
        return WorkspaceNativeSnapshot(
            owner,
            root=root,
            external_roots={alias: path for alias, path, _ in external_paths},
            snapshot_native=snapshot_native,
            external_snapshot_natives=tuple(external_snapshot_natives),
            external_scopes=tuple(scopes),
            origins=(*main_origins, *external_origins),
            enumerations=(main_enumeration, *external_enumerations),
            snapshot_digests=snapshot_digests,
            generated_paths=generated_paths,
            generated_limits=generated_limits,
        )
    except Exception as exc:
        failures = _cleanup_snapshot_resources(
            owner,
            snapshot_native=snapshot_native,
            external_snapshot_natives=tuple(external_snapshot_natives),
            external_scopes=tuple(scopes),
        )
        _record_suppressed_cleanup(failures)
        if isinstance(exc, OSError):
            raise WorkspaceIOError(
                "HOCUS828", "Workspace snapshot materialization failed."
            ) from exc
        raise


def _collect_main_files(
    workspace: WorkspaceIO,
    budget: _CollectionBudget,
) -> tuple[
    tuple[_SnapshotFile, ...],
    tuple[_Origin, ...],
    _Enumeration,
]:
    files: list[_SnapshotFile] = []
    origins: list[_Origin] = []
    generated_paths = _generated_paths(workspace)
    paths = _enumerate_workspace_paths(
        workspace,
        manifest_path=workspace.policy.manifest_path,
        generated_paths=generated_paths,
        maximum=budget.remaining_files,
    )
    for path in sorted(paths):
        kind = workspace.policy.classify(path)
        generated = kind in GENERATED_KINDS
        maximum = (
            _generated_file_byte_limit(kind)
            if generated
            else MAX_WORKSPACE_FILE_BYTES
        )
        raw, identity = budget.read(workspace, path, maximum)
        _strict_workspace_text(raw)
        digest = _raw_digest(raw)
        origins.append(
            _Origin(
                workspace,
                path,
                digest,
                identity,
                optional=False,
                max_bytes=maximum,
            )
        )
        files.append(_SnapshotFile(path, raw, generated=generated))
    enumeration = _Enumeration(
        workspace,
        frozenset(item.relative_path for item in files),
        workspace.policy.manifest_path,
        generated_paths,
    )
    return tuple(files), tuple(origins), enumeration


def _collect_external_files(
    aliases: tuple[tuple[str, Path], ...],
    external_base: Path,
    scopes: list[WorkspaceIO],
    budget: _CollectionBudget,
    *,
    expected_identities: Mapping[str, str],
) -> tuple[
    tuple[_SnapshotFile, ...],
    tuple[_Origin, ...],
    tuple[tuple[str, Path, tuple[_SnapshotFile, ...]], ...],
    tuple[_Enumeration, ...],
]:
    flattened: list[_SnapshotFile] = []
    origins: list[_Origin] = []
    outputs: list[tuple[str, Path, tuple[_SnapshotFile, ...]]] = []
    enumerations: list[_Enumeration] = []
    for index, (alias, native_root) in enumerate(aliases):
        expected = expected_identities.get(alias.casefold())
        if expected_identities and expected is None:
            raise WorkspaceIOError(
                "HOCUS824", "External root has no approved identity binding."
            )
        scope = WorkspaceIO.open_external(
            native_root, expected_identity=expected
        )
        scopes.append(scope)
        files: list[_SnapshotFile] = []
        paths = _enumerate_workspace_paths(
            scope,
            manifest_path=scope.policy.manifest_path,
            generated_paths=(),
            maximum=budget.remaining_files,
        )
        for path in sorted(paths):
            raw, identity = budget.read(
                scope, path, MAX_WORKSPACE_FILE_BYTES
            )
            _strict_workspace_text(raw)
            digest = _raw_digest(raw)
            item = _SnapshotFile(path, raw, generated=False)
            files.append(item)
            flattened.append(item)
            origins.append(
                _Origin(
                    scope,
                    path,
                    digest,
                    identity,
                    optional=False,
                    max_bytes=MAX_WORKSPACE_FILE_BYTES,
                )
            )
        destination = external_base / f"alias-{index:02d}-{_alias_token(alias)}"
        outputs.append((alias, destination, tuple(files)))
        enumerations.append(
            _Enumeration(
                scope,
                frozenset(item.relative_path for item in files),
                scope.policy.manifest_path,
            )
        )
    return (
        tuple(flattened),
        tuple(origins),
        tuple(outputs),
        tuple(enumerations),
    )


def _current_paths(enumeration: _Enumeration) -> frozenset[str]:
    return _enumerate_workspace_paths(
        enumeration.workspace,
        manifest_path=enumeration.manifest_path,
        generated_paths=enumeration.generated_paths,
        maximum=MAX_WORKSPACE_FILES,
    )


def _enumerate_workspace_paths(
    workspace: WorkspaceIO,
    *,
    manifest_path: str,
    generated_paths: tuple[str, ...],
    maximum: int,
) -> frozenset[str]:
    if maximum <= 0:
        raise WorkspaceIOError(
            "HOCUS825", "Workspace snapshot exceeds its collection budget."
        )
    paths = workspace._enumerated_authored_paths(
        max_files=min(maximum, MAX_WORKSPACE_FILES),
        max_depth=MAX_WORKSPACE_DEPTH,
    )
    if not _identity_exists(workspace, manifest_path):
        raise WorkspaceIOError(
            "HOCUS824", "Workspace snapshot manifest identity changed."
        )
    paths.add(manifest_path)
    paths.update(
        path for path in generated_paths if _identity_exists(workspace, path)
    )
    if len(paths) > maximum:
        raise WorkspaceIOError(
            "HOCUS825", "Workspace snapshot file count exceeds limit."
        )
    _reject_portable_collisions(paths)
    return frozenset(paths)


def _identity_exists(workspace: WorkspaceIO, path: str) -> bool:
    try:
        workspace._native.inspect_identity(tuple(path.split("/")))
    except NativeWorkspaceMissing:
        return False
    except NativeWorkspaceError as exc:
        raise _workspace_error(exc, path) from exc
    return True


def _validated_alias_roots(
    values: Mapping[str, Path],
) -> tuple[tuple[str, Path], ...]:
    if not isinstance(values, Mapping) or len(values) > MAX_EXTERNAL_ROOTS:
        raise WorkspaceIOError("HOCUS823", "External root mapping exceeds its bound.")
    rows: list[tuple[str, Path]] = []
    folded: set[str] = set()
    for alias, root in values.items():
        if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
            raise WorkspaceIOError("HOCUS823", "External root alias is malformed.")
        key = alias.casefold()
        if key in folded or not isinstance(root, Path):
            raise WorkspaceIOError("HOCUS823", "External root mapping is malformed.")
        folded.add(key)
        rows.append((alias, root))
    return tuple(sorted(rows, key=lambda item: item[0].casefold()))


def _require_snapshot_bounds(files: tuple[_SnapshotFile, ...]) -> None:
    if len(files) > MAX_WORKSPACE_FILES:
        raise WorkspaceIOError("HOCUS825", "Workspace snapshot file count exceeds limit.")
    if sum(len(item.content) for item in files) > MAX_SNAPSHOT_BYTES:
        raise WorkspaceIOError("HOCUS825", "Workspace snapshot byte count exceeds limit.")


def _materialize_files(
    root: Path,
    files: tuple[_SnapshotFile, ...],
    *,
    writable_generated: bool,
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for file in files:
        destination = root.joinpath(*file.relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _exclusive_write(destination, file.content)
        if not file.generated or not writable_generated:
            destination.chmod(0o444)
            digests[file.relative_path] = _raw_digest(file.content)
    return digests


def _exclusive_write(path: Path, content: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise OSError("short snapshot write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise WorkspaceIOError("HOCUS828", "Workspace snapshot materialization failed.") from exc


def _create_policy_directories(root: Path, workspace: WorkspaceIO) -> None:
    for value in workspace.policy.authored_directories:
        if value != ".":
            root.joinpath(*value.split("/")).mkdir(parents=True, exist_ok=True)


def _create_generated_parents(root: Path, paths: frozenset[str]) -> None:
    for relative in paths:
        root.joinpath(*relative.split("/")).parent.mkdir(parents=True, exist_ok=True)


def _generated_paths(workspace: WorkspaceIO) -> tuple[str, ...]:
    values = [workspace.policy.lock_path]
    if workspace.policy.catalog_path is not None:
        values.append(workspace.policy.catalog_path)
    for path in values:
        kind = workspace.policy.classify(path)
        if kind not in GENERATED_KINDS:
            raise WorkspaceIOError("HOCUS823", "Generated snapshot policy is malformed.")
    return tuple(values)


def _alias_token(alias: str) -> str:
    return hashlib.sha256(alias.encode("utf-8")).hexdigest()[:16]


def _cleanup_attempt(callback, stage: str, failures: list[str]) -> None:
    try:
        callback()
    except Exception:
        failures.append(stage)


def _cleanup_snapshot_resources(
    owner: tempfile.TemporaryDirectory[str],
    *,
    snapshot_native: PinnedWorkspace | None,
    external_snapshot_natives: tuple[
        tuple[PinnedWorkspace, Mapping[str, str]], ...
    ],
    external_scopes: tuple[WorkspaceIO, ...],
) -> tuple[str, ...]:
    failures: list[str] = []
    if snapshot_native is not None:
        _cleanup_attempt(snapshot_native.close, "snapshot_handle", failures)
    for native, _ in external_snapshot_natives:
        _cleanup_attempt(native.close, "external_handle", failures)
    for scope in external_scopes:
        _cleanup_attempt(scope._close_strict, "external_root", failures)
    _cleanup_attempt(
        lambda: _require_tree_cleanup(Path(owner.name)),
        "temporary_permissions",
        failures,
    )
    _cleanup_attempt(owner.cleanup, "temporary_tree", failures)
    return tuple(failures)


def _record_suppressed_cleanup(failures: tuple[str, ...]) -> None:
    if failures:
        _LOG.warning(
            "HOCUS828 snapshot cleanup failures suppressed: count=%d stages=%s",
            len(failures),
            ",".join(sorted(set(failures))),
        )


def _require_tree_cleanup(root: Path) -> None:
    if _make_tree_deletable(root):
        raise OSError("snapshot tree permission cleanup failed")


def _make_tree_deletable(root: Path) -> int:
    failures = 0
    if not root.exists():
        return failures
    for current, directories, files in os.walk(root):
        for name in files:
            try:
                (Path(current) / name).chmod(0o600)
            except OSError:
                failures += 1
        for name in directories:
            try:
                (Path(current) / name).chmod(0o700)
            except OSError:
                failures += 1
    try:
        root.chmod(0o700)
    except OSError:
        failures += 1
    return failures


__all__ = [
    "MAX_EXTERNAL_ROOTS",
    "MAX_SNAPSHOT_BYTES",
    "WorkspaceNativeSnapshot",
    "create_native_snapshot",
]
