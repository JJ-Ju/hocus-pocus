"""Host-owned registry for approved HocusScript project directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hocuspocus.hocusscript._workspace_native import (
    NativeWorkspaceError,
    PinnedWorkspace,
)
from hocuspocus.hocusscript.project import ProjectContext, ProjectError

from .paths import workspace_registry_path

_PROJECT_ID = re.compile(r"^hproj_[a-f0-9]{32}$")
_REGISTRY_VERSION = 3
_SUPPORTED_REGISTRY_VERSIONS = frozenset({2, _REGISTRY_VERSION})
_PROJECT_MANIFEST = ("hocus.project.toml",)
_MAX_PROJECT_MANIFEST_BYTES = 1024 * 1024
MAX_REGISTERED_PROJECTS = 64


class WorkspaceRegistryError(ValueError):
    """Typed host-side workspace registry failure."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class WorkspaceProjection:
    project_uid: str | None
    project_name: str | None
    manifest_version: int
    language_version: str
    lock_policy: str
    source_directories: tuple[str, ...]
    module_directories: tuple[str, ...]
    external_aliases: tuple[tuple[str, str, str, str | None], ...]
    lock_path: str
    catalog_path: str | None
    digest: str

    def client_payload(self) -> dict[str, Any]:
        return {
            "projectUid": self.project_uid,
            "projectName": self.project_name,
            "manifestVersion": self.manifest_version,
            "languageVersion": self.language_version,
            "lockPolicy": self.lock_policy,
            "sourceDirectories": list(self.source_directories),
            "moduleDirectories": list(self.module_directories),
            "externalAliases": [
                {
                    "alias": alias,
                    "libraryUid": library_uid,
                    "libraryVersion": library_version,
                    "expectedModuleManifestDigest": manifest_digest,
                }
                for alias, library_uid, library_version, manifest_digest in self.external_aliases
            ],
            "lockPath": self.lock_path,
            "catalogPath": self.catalog_path,
            "authorityProjectionDigest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceProject:
    project_id: str
    root: Path
    root_identity_digest: str
    manifest_identity_digest: str
    label: str
    projection: WorkspaceProjection
    registered_at: float
    updated_at: float

    def client_payload(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "label": self.label,
            **self.projection.client_payload(),
        }

    def host_payload(self) -> dict[str, Any]:
        return {
            **self.client_payload(),
            "root": str(self.root),
            "registeredAt": self.registered_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedWorkspace:
    """Private runtime authority. Never serialize this object to MCP."""

    project_id: str
    approved_root: Path
    root_identity_digest: str
    manifest_identity_digest: str
    projection: WorkspaceProjection
    generation: int
    grants: tuple[str, ...]
    external_roots: tuple[tuple[str, Path], ...]
    external_root_identities: tuple[tuple[str, str], ...]
    expires_at: float | None

    @property
    def root(self) -> Path:
        return self.approved_root

    @property
    def projection_digest(self) -> str:
        return self.projection.digest

    @property
    def grant_generation(self) -> int:
        return self.generation

    @property
    def access_mode(self) -> str:
        return "read_write" if "source_write" in self.grants else "read_only"

    @property
    def public_metadata(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            **self.projection.client_payload(),
            "grants": list(self.grants),
            "accessMode": self.access_mode,
            "grantGeneration": self.generation,
            "grantExpiresAt": self.expires_at,
            "untilRevoked": self.expires_at is None,
            "externalAliasesApproved": [alias for alias, _ in self.external_roots],
        }


class WorkspaceRegistry:
    def __init__(self, path: Path | None = None):
        self._path = path or workspace_registry_path()
        self._lock = threading.RLock()
        self._projects: dict[str, WorkspaceProject] = {}
        self._load()

    def register(
        self,
        root: str | Path,
        *,
        label: str | None = None,
        project_id: str | None = None,
        reapprove: bool = False,
        allow_repoint: bool = False,
    ) -> WorkspaceProject:
        canonical = _canonical_root(root)
        identity_before = capture_workspace_approval_identity(canonical)
        projection = inspect_workspace_projection(canonical)
        identity = capture_workspace_approval_identity(canonical)
        if identity_before != identity:
            raise WorkspaceRegistryError(
                "HOCUS906",
                "Project root or manifest changed during host approval.",
            )
        with self._lock:
            existing = self._by_root(canonical)
            if existing is not None:
                if project_id is not None and existing.project_id != project_id:
                    raise WorkspaceRegistryError(
                        "HOCUS902",
                        "The configured project root is already bound to another project ID.",
                    )
                updated = existing
                if reapprove:
                    updated = replace(
                        existing,
                        root_identity_digest=identity[0],
                        manifest_identity_digest=identity[1],
                        projection=projection,
                        label=_label(label, projection, existing.label),
                        updated_at=time.time(),
                    )
                    self._projects[updated.project_id] = updated
                    self._save()
                return updated
            if len(self._projects) >= MAX_REGISTERED_PROJECTS:
                raise WorkspaceRegistryError(
                    "HOCUS901",
                    "The host workspace registry reached its project limit.",
                    {"limit": MAX_REGISTERED_PROJECTS},
                )
            opaque_id = _project_id(project_id)
            if opaque_id in self._projects:
                if not allow_repoint:
                    raise WorkspaceRegistryError(
                        "HOCUS902", "The requested opaque project ID already exists."
                    )
                previous = self._projects[opaque_id]
                updated = WorkspaceProject(
                    opaque_id,
                    canonical,
                    identity[0],
                    identity[1],
                    _label(label, projection, previous.label),
                    projection,
                    previous.registered_at,
                    time.time(),
                )
                self._projects[opaque_id] = updated
                self._save()
                return updated
            now = time.time()
            project = WorkspaceProject(
                opaque_id,
                canonical,
                identity[0],
                identity[1],
                _label(label, projection, canonical.name),
                projection,
                now,
                now,
            )
            self._projects[opaque_id] = project
            self._save()
            return project

    def reapprove(self, project_id: str) -> WorkspaceProject:
        project = self.require(project_id)
        return self.register(
            project.root,
            label=project.label,
            project_id=project.project_id,
            reapprove=True,
        )

    def remove(self, project_id: str) -> WorkspaceProject:
        with self._lock:
            project = self._projects.pop(project_id, None)
            if project is None:
                raise WorkspaceRegistryError(
                    "HOCUS903", "Unknown approved project.", {"projectId": project_id}
                )
            self._save()
            return project

    def require(self, project_id: str) -> WorkspaceProject:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None:
            raise WorkspaceRegistryError(
                "HOCUS903", "Unknown approved project.", {"projectId": project_id}
            )
        return project

    def inspect_current(self, project_id: str) -> WorkspaceProjection:
        return inspect_workspace_projection(self.require(project_id).root)

    def require_current(self, project_id: str) -> WorkspaceProject:
        project = self.require(project_id)
        current_identity = capture_workspace_approval_identity(project.root)
        if not secrets.compare_digest(
            current_identity[0], project.root_identity_digest
        ) or not secrets.compare_digest(
            current_identity[1], project.manifest_identity_digest
        ):
            raise WorkspaceRegistryError(
                "HOCUS904",
                "Approved project root or manifest identity changed and requires host-user reapproval.",
                {"projectId": project_id},
            )
        current = inspect_workspace_projection(project.root)
        final_identity = capture_workspace_approval_identity(project.root)
        if current_identity != final_identity:
            raise WorkspaceRegistryError(
                "HOCUS904",
                "Approved project root or manifest changed during authorization.",
                {"projectId": project_id},
            )
        if not secrets.compare_digest(current.digest, project.projection.digest):
            raise WorkspaceRegistryError(
                "HOCUS904",
                "Project authority changed and requires host-user reapproval.",
                {
                    "projectId": project_id,
                    "approvedProjectionDigest": project.projection.digest,
                    "currentProjectionDigest": current.digest,
                },
            )
        return project

    def accept_current_manifest_identity(
        self,
        project_id: str,
        expected_projection_digest: str,
    ) -> WorkspaceProject:
        project = self.require(project_id)
        identity_before = capture_workspace_approval_identity(project.root)
        if not secrets.compare_digest(
            identity_before[0], project.root_identity_digest
        ):
            raise WorkspaceRegistryError(
                "HOCUS904",
                "Approved project root identity changed during publication.",
                {"projectId": project_id},
            )
        current = inspect_workspace_projection(project.root)
        identity = capture_workspace_approval_identity(project.root)
        if identity_before != identity or not secrets.compare_digest(
            current.digest, expected_projection_digest
        ) or not secrets.compare_digest(
            project.projection.digest, expected_projection_digest
        ):
            raise WorkspaceRegistryError(
                "HOCUS904",
                "Published manifest authority does not match the approved projection.",
                {"projectId": project_id},
            )
        updated = replace(
            project,
            manifest_identity_digest=identity[1],
            updated_at=time.time(),
        )
        with self._lock:
            if self._projects.get(project_id) != project:
                raise WorkspaceRegistryError(
                    "HOCUS904",
                    "Project authority changed during manifest publication.",
                    {"projectId": project_id},
                )
            self._projects[project_id] = updated
            self._save()
        return updated

    def list_projects(self) -> tuple[WorkspaceProject, ...]:
        with self._lock:
            return tuple(sorted(self._projects.values(), key=lambda item: item.project_id))

    def find_by_root(self, root: str | Path) -> WorkspaceProject | None:
        canonical = _canonical_root(root)
        with self._lock:
            return self._by_root(canonical)

    def host_snapshot(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for project in self.list_projects():
            payload = project.host_payload()
            try:
                current = self.inspect_current(project.project_id)
                payload["currentProjectionDigest"] = current.digest
                self.require_current(project.project_id)
                payload["requiresReapproval"] = False
            except WorkspaceRegistryError as exc:
                payload["inspectionError"] = {"code": exc.code, "message": exc.message}
                payload["requiresReapproval"] = True
            output.append(payload)
        return output

    def _by_root(self, root: Path) -> WorkspaceProject | None:
        folded = os.path.normcase(str(root))
        for project in self._projects.values():
            if os.path.normcase(str(project.root)) == folded:
                return project
        return None

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("registry exceeds size limit")
            payload = json.loads(raw.decode("utf-8"))
            projects = _decode_registry(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise WorkspaceRegistryError(
                "HOCUS905",
                "The host workspace registry is malformed.",
                {"errorType": type(exc).__name__},
            ) from exc
        self._projects = {item.project_id: item for item in projects}
        if payload.get("version") != _REGISTRY_VERSION:
            self._save()

    def _save(self) -> None:
        payload = {
            "version": _REGISTRY_VERSION,
            "projects": [_stored_project(item) for item in self.list_projects()],
        }
        _atomic_json_write(self._path, payload)


def inspect_workspace_projection(root: Path) -> WorkspaceProjection:
    try:
        context = ProjectContext.load(root, validate_lock=False)
    except ProjectError as exc:
        raise WorkspaceRegistryError(
            "HOCUS906",
            "The selected directory is not an approvable HocusScript project.",
            {"projectCode": exc.code},
        ) from exc
    source_paths = tuple(_portable_relative(root, item) for item in context.source_directories)
    module_paths = tuple(_portable_relative(root, item) for item in context.module_directories)
    aliases = tuple(
        (
            item.alias,
            item.library_uid,
            item.library_version,
            item.expected_module_manifest_digest,
        )
        for item in sorted(context.external_aliases, key=lambda value: value.alias)
    )
    lock_path = _portable_relative(root, context.lock_path) if context.lock_path else "hocus.lock.json"
    catalog_path = (
        _portable_relative(root, context.catalog_path)
        if context.catalog_path is not None
        else None
    )
    unsigned = {
        "projectUid": context.uid,
        "manifestVersion": context.manifest_version,
        "languageVersion": context.language_version,
        "lockPolicy": context.lock_policy,
        "sourceDirectories": list(source_paths),
        "moduleDirectories": list(module_paths),
        "externalAliases": [
            {
                "alias": alias,
                "libraryUid": library_uid,
                "libraryVersion": library_version,
                "expectedModuleManifestDigest": manifest_digest,
            }
            for alias, library_uid, library_version, manifest_digest in aliases
        ],
        "lockPath": lock_path,
        "catalogPath": catalog_path,
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return WorkspaceProjection(
        context.uid,
        context.name,
        context.manifest_version,
        context.language_version,
        context.lock_policy,
        source_paths,
        module_paths,
        aliases,
        lock_path,
        catalog_path,
        digest,
    )


def capture_workspace_root_identity(root: Path) -> str:
    return capture_workspace_approval_identity(root)[0]


def capture_workspace_approval_identity(root: Path) -> tuple[str, str, str]:
    try:
        with PinnedWorkspace(root) as pinned:
            manifest_before = pinned.inspect_identity(_PROJECT_MANIFEST)
            raw = pinned.read(_PROJECT_MANIFEST, _MAX_PROJECT_MANIFEST_BYTES)
            manifest_identity = pinned.inspect_identity(_PROJECT_MANIFEST)
            pinned.assert_current()
            root_identity = pinned.root_info.identity_digest
    except NativeWorkspaceError as exc:
        raise WorkspaceRegistryError(
            "HOCUS906",
            "The selected project root and manifest could not be pinned safely.",
            {"nativeCode": exc.code},
        ) from exc
    if (
        not _valid_identity_digest(root_identity)
        or not _valid_identity_digest(manifest_identity)
        or not secrets.compare_digest(manifest_before, manifest_identity)
    ):
        raise WorkspaceRegistryError(
            "HOCUS906", "The selected project authority identity is malformed or unstable."
        )
    return (
        root_identity,
        manifest_identity,
        "sha256:" + hashlib.sha256(raw).hexdigest(),
    )


def _canonical_root(value: str | Path) -> Path:
    try:
        root = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceRegistryError(
            "HOCUS906", "The selected project directory does not exist."
        ) from exc
    if not root.is_dir():
        raise WorkspaceRegistryError("HOCUS906", "The selected project root is not a directory.")
    return root


def _portable_relative(root: Path, value: Path) -> str:
    try:
        return value.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkspaceRegistryError(
            "HOCUS906", "Project authority contains a path outside its root."
        ) from exc


def _project_id(value: str | None) -> str:
    if value is None:
        return "hproj_" + secrets.token_hex(16)
    if _PROJECT_ID.fullmatch(value) is None:
        raise WorkspaceRegistryError("HOCUS902", "Configured project ID is malformed.")
    return value


def _label(value: str | None, projection: WorkspaceProjection, fallback: str) -> str:
    label = str(value or projection.project_name or fallback).strip()
    if not label or len(label) > 128:
        raise WorkspaceRegistryError("HOCUS907", "Workspace label must contain 1 to 128 characters.")
    return label


def _stored_project(project: WorkspaceProject) -> dict[str, Any]:
    return {
        "projectId": project.project_id,
        "root": str(project.root),
        "rootIdentityDigest": project.root_identity_digest,
        "manifestIdentityDigest": project.manifest_identity_digest,
        "label": project.label,
        "projection": project.projection.client_payload(),
        "registeredAt": project.registered_at,
        "updatedAt": project.updated_at,
    }


def _decode_registry(payload: Any) -> tuple[WorkspaceProject, ...]:
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in _SUPPORTED_REGISTRY_VERSIONS
    ):
        raise ValueError("unsupported registry version")
    rows = payload.get("projects")
    if not isinstance(rows, list) or len(rows) > MAX_REGISTERED_PROJECTS:
        raise ValueError("invalid project list")
    projects = tuple(_decode_project(item, payload["version"]) for item in rows)
    if len({item.project_id for item in projects}) != len(projects):
        raise ValueError("duplicate project id")
    if len({os.path.normcase(str(item.root)) for item in projects}) != len(projects):
        raise ValueError("duplicate project root")
    return projects


def _decode_project(payload: Any, version: int) -> WorkspaceProject:
    if not isinstance(payload, dict):
        raise ValueError("invalid project")
    project_id = _project_id(payload.get("projectId"))
    root = _stored_root(payload.get("root"))
    root_identity = payload.get("rootIdentityDigest")
    if not isinstance(root_identity, str) or not _valid_identity_digest(root_identity):
        raise ValueError("invalid stored project root identity")
    manifest_identity = payload.get("manifestIdentityDigest")
    if version == 2:
        manifest_identity = capture_workspace_approval_identity(root)[1]
    if not isinstance(manifest_identity, str) or not _valid_identity_digest(
        manifest_identity
    ):
        raise ValueError("invalid stored project manifest identity")
    projection = _decode_projection(payload.get("projection"))
    registered = float(payload.get("registeredAt"))
    updated = float(payload.get("updatedAt"))
    return WorkspaceProject(
        project_id,
        root,
        root_identity,
        manifest_identity,
        _label(payload.get("label"), projection, root.name),
        projection,
        registered,
        updated,
    )


def _decode_projection(payload: Any) -> WorkspaceProjection:
    if not isinstance(payload, dict):
        raise ValueError("invalid projection")
    digest = payload.get("authorityProjectionDigest")
    sequences = ("sourceDirectories", "moduleDirectories", "externalAliases")
    if not isinstance(digest, str) or any(not isinstance(payload.get(key), list) for key in sequences):
        raise ValueError("invalid projection fields")
    aliases = tuple(_decode_alias(item) for item in payload["externalAliases"])
    return WorkspaceProjection(
        payload.get("projectUid"),
        payload.get("projectName"),
        int(payload.get("manifestVersion")),
        str(payload.get("languageVersion")),
        str(payload.get("lockPolicy")),
        tuple(str(item) for item in payload["sourceDirectories"]),
        tuple(str(item) for item in payload["moduleDirectories"]),
        aliases,
        str(payload.get("lockPath")),
        str(payload["catalogPath"]) if payload.get("catalogPath") is not None else None,
        digest,
    )


def _decode_alias(payload: Any) -> tuple[str, str, str, str | None]:
    if not isinstance(payload, dict):
        raise ValueError("invalid external alias")
    manifest_digest = payload.get("expectedModuleManifestDigest")
    if manifest_digest is not None and not isinstance(manifest_digest, str):
        raise ValueError("invalid external module-manifest pin")
    return (
        str(payload.get("alias")),
        str(payload.get("libraryUid")),
        str(payload.get("libraryVersion")),
        manifest_digest,
    )


def _stored_root(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid stored project root")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("stored project root must be absolute")
    return candidate.resolve(strict=False)


def _valid_identity_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise WorkspaceRegistryError(
            "HOCUS908", "Could not persist the host workspace registry."
        ) from exc


__all__ = [
    "AuthorizedWorkspace",
    "WorkspaceProject",
    "WorkspaceProjection",
    "WorkspaceRegistry",
    "WorkspaceRegistryError",
    "capture_workspace_root_identity",
    "inspect_workspace_projection",
]
