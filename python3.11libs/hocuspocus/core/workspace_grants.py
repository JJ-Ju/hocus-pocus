"""Server-side HocusScript workspace sessions and scoped grants."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hocuspocus.hocusscript._workspace_native import (
    NativeWorkspaceError,
    PinnedWorkspace,
)

from .paths import workspace_grants_path
from .workspace_registry import (
    AuthorizedWorkspace,
    WorkspaceProject,
    WorkspaceRegistry,
    WorkspaceRegistryError,
)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

SOURCE_READ = "source_read"
SOURCE_WRITE = "source_write"
GENERATED_LOCK = "generated_lock"
EXTERNAL_READ = "external_read"
SOURCE_NOTIFY = "source_notify"
WORKSPACE_GRANTS = frozenset(
    {SOURCE_READ, SOURCE_WRITE, GENERATED_LOCK, EXTERNAL_READ, SOURCE_NOTIFY}
)
_SESSION_ID = re.compile(r"^hws_[A-Za-z0-9_-]{24,96}$")
_GRANTS_VERSION = 3
_SUPPORTED_GRANTS_VERSIONS = frozenset({2, _GRANTS_VERSION})
_MAX_MODULE_MANIFEST_BYTES = 1024 * 1024


class WorkspaceGrantError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    session_id: str
    principal_id: str
    client_info: dict[str, str]
    created_at: float
    expires_at: float
    last_seen_at: float
    generation: int

    def host_payload(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "principalId": self.principal_id,
            "clientInfo": dict(self.client_info),
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "lastSeenAt": self.last_seen_at,
            "generation": self.generation,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceGrant:
    principal_id: str
    project_id: str
    session_id: str | None
    grants: tuple[str, ...]
    external_roots: tuple[tuple[str, Path], ...]
    external_root_identities: tuple[tuple[str, str], ...]
    authority_projection_digest: str
    persistent: bool
    created_at: float
    expires_at: float | None
    generation: int

    def host_payload(self, *, include_roots: bool) -> dict[str, Any]:
        payload = {
            "principalId": self.principal_id,
            "projectId": self.project_id,
            "sessionId": self.session_id,
            "grants": list(self.grants),
            "externalAliases": [alias for alias, _ in self.external_roots],
            "authorityProjectionDigest": self.authority_projection_digest,
            "persistent": self.persistent,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "untilRevoked": self.expires_at is None,
            "generation": self.generation,
        }
        if include_roots:
            payload["externalRoots"] = {
                alias: str(root) for alias, root in self.external_roots
            }
        return payload


class WorkspaceGrantStore:
    def __init__(
        self,
        *,
        path: Path | None = None,
        session_ttl_seconds: float = 8 * 60 * 60,
        session_grant_ttl_seconds: float = 8 * 60 * 60,
        persistent_grant_ttl_seconds: float = 30 * 24 * 60 * 60,
        on_change: Callable[[str, str], None] | None = None,
    ):
        self._path = path or workspace_grants_path()
        self._session_ttl = _positive_ttl(session_ttl_seconds, "session")
        self._session_grant_ttl = _positive_ttl(session_grant_ttl_seconds, "session grant")
        self._persistent_grant_ttl = _positive_ttl(
            persistent_grant_ttl_seconds, "persistent grant"
        )
        self._on_change = on_change
        self._lock = threading.RLock()
        self._sessions: dict[str, WorkspaceSession] = {}
        self._session_grants: dict[tuple[str, str], WorkspaceGrant] = {}
        self._persistent_grants: dict[tuple[str, str], WorkspaceGrant] = {}
        self._generations: dict[tuple[str, str], int] = {}
        self._load()

    def issue_session(
        self, principal_id: str, client_info: dict[str, Any] | None = None
    ) -> WorkspaceSession:
        principal = _principal(principal_id)
        now = time.time()
        session = WorkspaceSession(
            "hws_" + secrets.token_urlsafe(32),
            principal,
            _client_info(client_info),
            now,
            now + self._session_ttl,
            now,
            1,
        )
        with self._lock:
            self._prune(now)
            self._sessions[session.session_id] = session
        return session

    def session(
        self,
        session_id: str | None,
        *,
        principal_id: str | None = None,
        touch: bool = True,
    ) -> WorkspaceSession | None:
        if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
            return None
        now = time.time()
        with self._lock:
            self._prune(now)
            current = self._sessions.get(session_id)
            if current is None or (
                principal_id is not None and current.principal_id != principal_id
            ):
                return None
            if touch:
                current = WorkspaceSession(
                    current.session_id,
                    current.principal_id,
                    current.client_info,
                    current.created_at,
                    current.expires_at,
                    now,
                    current.generation,
                )
                self._sessions[session_id] = current
            return current

    def revoke_session(self, session_id: str) -> bool:
        changed_projects: set[str] = set()
        with self._lock:
            session = self._sessions.pop(session_id, None)
            removed = [
                key for key in self._session_grants if key[0] == session_id
            ]
            for key in removed:
                grant = self._session_grants.pop(key)
                self._bump(grant.principal_id, grant.project_id)
                changed_projects.add(grant.project_id)
        for project_id in changed_projects:
            self._changed(project_id, "session_revoke")
        return session is not None

    def revoke_project_all(self, project_id: str) -> int:
        removed: list[WorkspaceGrant] = []
        with self._lock:
            for mapping in (self._session_grants, self._persistent_grants):
                keys = [key for key, grant in mapping.items() if grant.project_id == project_id]
                for key in keys:
                    removed.append(mapping.pop(key))
            for grant in removed:
                self._bump(grant.principal_id, grant.project_id)
            if any(grant.persistent for grant in removed):
                self._save()
        if removed:
            self._changed(project_id, "project_remove")
        return len(removed)

    def grant(
        self,
        project: WorkspaceProject,
        *,
        principal_id: str,
        session_id: str | None = None,
        grants: tuple[str, ...] = (SOURCE_READ,),
        external_roots: dict[str, str | Path] | None = None,
        persistent: bool = False,
        expires_in_seconds: float | None = None,
        until_revoked: bool = False,
    ) -> WorkspaceGrant:
        principal = _principal(principal_id)
        selected = _grant_names(grants)
        roots, root_identities = _external_roots(project, selected, external_roots)
        if until_revoked and not persistent:
            raise WorkspaceGrantError(
                "HOCUS917", "Until-revoked grants must be persistent."
            )
        if until_revoked and expires_in_seconds is not None:
            raise WorkspaceGrantError(
                "HOCUS917",
                "Until-revoked grants cannot also declare a finite expiry.",
            )
        if not persistent:
            session = self.session(session_id, principal_id=principal)
            if session is None:
                raise WorkspaceGrantError(
                    "HOCUS910", "A live matching MCP session is required."
                )
        else:
            session_id = None
        default_ttl = (
            self._persistent_grant_ttl if persistent else self._session_grant_ttl
        )
        ttl = None
        if not until_revoked:
            ttl = _positive_ttl(
                default_ttl if expires_in_seconds is None else expires_in_seconds,
                "grant",
            )
        now = time.time()
        with self._lock:
            generation = self._bump(principal, project.project_id)
            grant = WorkspaceGrant(
                principal,
                project.project_id,
                session_id,
                selected,
                roots,
                root_identities,
                project.projection.digest,
                persistent,
                now,
                None if ttl is None else now + ttl,
                generation,
            )
            if persistent:
                self._persistent_grants[(principal, project.project_id)] = grant
                self._save()
            else:
                assert session_id is not None
                self._session_grants[(session_id, project.project_id)] = grant
        self._changed(project.project_id, "grant")
        return grant

    def revoke(
        self,
        project_id: str,
        *,
        principal_id: str,
        session_id: str | None = None,
        persistent: bool | None = None,
    ) -> bool:
        principal = _principal(principal_id)
        removed = False
        with self._lock:
            if persistent is not False:
                removed |= self._persistent_grants.pop((principal, project_id), None) is not None
            if persistent is not True:
                keys = [
                    key
                    for key, grant in self._session_grants.items()
                    if grant.project_id == project_id
                    and grant.principal_id == principal
                    and (session_id is None or grant.session_id == session_id)
                ]
                for key in keys:
                    self._session_grants.pop(key)
                    removed = True
            if removed:
                self._bump(principal, project_id)
                self._save()
        if removed:
            self._changed(project_id, "revoke")
        return removed

    def require(
        self,
        session_id: str,
        project: WorkspaceProject,
        required_grant: str,
        *,
        external_alias: str | None = None,
    ) -> AuthorizedWorkspace:
        if required_grant not in WORKSPACE_GRANTS:
            raise WorkspaceGrantError("HOCUS911", "Unknown workspace grant.")
        session = self.session(session_id)
        if session is None:
            raise WorkspaceGrantError(
                "HOCUS910", "The MCP workspace session is missing, expired, or revoked."
            )
        now = time.time()
        with self._lock:
            grants = self._active_grants(session, project.project_id, now)
        selected = _select_grant(grants, required_grant, external_alias)
        if selected is None:
            raise WorkspaceGrantError(
                "HOCUS911",
                "The workspace grant does not authorize this operation.",
                {
                    "projectId": project.project_id,
                    "requiredGrant": required_grant,
                    "externalAlias": external_alias,
                },
            )
        if not secrets.compare_digest(
            selected.authority_projection_digest, project.projection.digest
        ):
            raise WorkspaceGrantError(
                "HOCUS912",
                "The workspace grant is stale and requires host-user reapproval.",
                {"projectId": project.project_id},
            )
        merged_grants = tuple(sorted({item for grant in grants for item in grant.grants}))
        merged_roots = _merge_external_roots(grants)
        merged_root_identities = _merge_external_root_identities(grants)
        _require_external_root_authority(
            project,
            merged_roots,
            merged_root_identities,
        )
        generation = self._generations.get(
            (session.principal_id, project.project_id), selected.generation
        )
        return AuthorizedWorkspace(
            project.project_id,
            project.root,
            project.root_identity_digest,
            project.manifest_identity_digest,
            project.projection,
            generation,
            merged_grants,
            merged_roots,
            merged_root_identities,
            _effective_expiry(grants),
        )

    def list_authorized(
        self, session_id: str, registry: WorkspaceRegistry
    ) -> tuple[dict[str, Any], ...]:
        session = self.session(session_id)
        if session is None:
            return ()
        output: list[dict[str, Any]] = []
        for project in registry.list_projects():
            try:
                current = registry.require_current(project.project_id)
                authority = self.require(session_id, current, SOURCE_READ)
            except (WorkspaceRegistryError, WorkspaceGrantError):
                continue
            payload = current.client_payload()
            payload["grants"] = list(authority.grants)
            payload["grantGeneration"] = authority.grant_generation
            payload["grantExpiresAt"] = authority.expires_at
            payload["untilRevoked"] = authority.expires_at is None
            output.append(payload)
        return tuple(output)

    def host_snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._prune(now)
            sessions = [
                item.host_payload()
                for item in sorted(self._sessions.values(), key=lambda row: row.created_at)
            ]
            grants = [
                item.host_payload(include_roots=True)
                for item in sorted(
                    (*self._persistent_grants.values(), *self._session_grants.values()),
                    key=lambda row: (row.project_id, row.principal_id, row.session_id or ""),
                )
            ]
        return {"sessions": sessions, "grants": grants}

    def _active_grants(
        self, session: WorkspaceSession, project_id: str, now: float
    ) -> tuple[WorkspaceGrant, ...]:
        candidates = (
            self._session_grants.get((session.session_id, project_id)),
            self._persistent_grants.get((session.principal_id, project_id)),
        )
        return tuple(
            item
            for item in candidates
            if item is not None
            and (item.expires_at is None or item.expires_at > now)
        )

    def _prune(self, now: float) -> None:
        expired_sessions = [
            key for key, session in self._sessions.items() if session.expires_at <= now
        ]
        for session_id in expired_sessions:
            self._sessions.pop(session_id, None)
            for key in [key for key in self._session_grants if key[0] == session_id]:
                grant = self._session_grants.pop(key)
                self._bump(grant.principal_id, grant.project_id)
                self._changed(grant.project_id, "expiry")
        expired = [
            key
            for key, grant in self._persistent_grants.items()
            if grant.expires_at is not None and grant.expires_at <= now
        ]
        for key in expired:
            grant = self._persistent_grants.pop(key)
            self._bump(grant.principal_id, grant.project_id)
            self._changed(grant.project_id, "expiry")
        if expired:
            self._save()

    def _bump(self, principal_id: str, project_id: str) -> int:
        key = (principal_id, project_id)
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        return generation

    def _changed(self, project_id: str, action: str) -> None:
        if self._on_change is not None:
            self._on_change(project_id, action)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("grant store exceeds size limit")
            payload = json.loads(raw.decode("utf-8"))
            grants = _decode_grants(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise WorkspaceGrantError(
                "HOCUS913",
                "The persistent workspace grant store is malformed.",
                {"errorType": type(exc).__name__},
            ) from exc
        now = time.time()
        self._persistent_grants = {
            (item.principal_id, item.project_id): item
            for item in grants
            if item.expires_at is None or item.expires_at > now
        }
        for item in self._persistent_grants.values():
            self._generations[(item.principal_id, item.project_id)] = item.generation
        if payload.get("version") != _GRANTS_VERSION:
            self._save()

    def _save(self) -> None:
        payload = {
            "version": _GRANTS_VERSION,
            "grants": [
                _stored_grant(item)
                for item in sorted(
                    self._persistent_grants.values(),
                    key=lambda row: (row.principal_id, row.project_id),
                )
            ],
        }
        _atomic_json_write(self._path, payload)


def principal_from_bearer(header_value: str, *, token_mode: str) -> str:
    if token_mode == "disabled":
        material = b"hocus-local-unauthenticated-v1"
    else:
        scheme, separator, token = header_value.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise WorkspaceGrantError("HOCUS914", "A valid bearer credential is required.")
        material = b"hocus-bearer-principal-v1\0" + token.encode("utf-8")
    return "hprincipal_" + hashlib.sha256(material).hexdigest()[:32]


def _select_grant(
    grants: tuple[WorkspaceGrant, ...],
    required: str,
    external_alias: str | None,
) -> WorkspaceGrant | None:
    for grant in grants:
        if required not in grant.grants:
            continue
        if external_alias is not None and external_alias not in dict(grant.external_roots):
            continue
        return grant
    return None


def _effective_expiry(grants: tuple[WorkspaceGrant, ...]) -> float | None:
    expiries = tuple(grant.expires_at for grant in grants)
    if any(value is None for value in expiries):
        return None
    return max(value for value in expiries if value is not None)


def _merge_external_roots(
    grants: tuple[WorkspaceGrant, ...],
) -> tuple[tuple[str, Path], ...]:
    roots: dict[str, Path] = {}
    for grant in grants:
        for alias, root in grant.external_roots:
            existing = roots.get(alias)
            if existing is not None and os.path.normcase(str(existing)) != os.path.normcase(str(root)):
                raise WorkspaceGrantError(
                    "HOCUS915", "Conflicting approved external roots require reapproval."
                )
            roots[alias] = root
    return tuple(sorted(roots.items()))


def _merge_external_root_identities(
    grants: tuple[WorkspaceGrant, ...],
) -> tuple[tuple[str, str], ...]:
    identities: dict[str, str] = {}
    for grant in grants:
        for alias, identity in grant.external_root_identities:
            existing = identities.get(alias)
            if existing is not None and not secrets.compare_digest(existing, identity):
                raise WorkspaceGrantError(
                    "HOCUS915",
                    "Conflicting approved external-root identities require reapproval.",
                )
            identities[alias] = identity
    return tuple(sorted(identities.items()))


def _require_external_root_authority(
    project: WorkspaceProject,
    roots: tuple[tuple[str, Path], ...],
    identities: tuple[tuple[str, str], ...],
) -> None:
    expected = dict(identities)
    if set(expected) != {alias for alias, _ in roots}:
        raise WorkspaceGrantError(
            "HOCUS915", "Approved external-root identities are incomplete."
        )
    for alias, root in roots:
        try:
            current = _inspect_external_alias_root(
                project,
                alias,
                root,
                code="HOCUS915",
            )
        except WorkspaceGrantError:
            raise
        if not secrets.compare_digest(current, expected[alias]):
            raise WorkspaceGrantError(
                "HOCUS915",
                "Approved external-root identity changed and requires reapproval.",
                {"alias": alias},
            )


def _external_roots(
    project: WorkspaceProject,
    grants: tuple[str, ...],
    values: dict[str, str | Path] | None,
) -> tuple[tuple[tuple[str, Path], ...], tuple[tuple[str, str], ...]]:
    mapping = values or {}
    if mapping and EXTERNAL_READ not in grants:
        raise WorkspaceGrantError(
            "HOCUS911", "External roots require the separate external_read grant."
        )
    declared = {item[0] for item in project.projection.external_aliases}
    if set(mapping) - declared:
        raise WorkspaceGrantError(
            "HOCUS916", "External-root approval contains an undeclared alias."
        )
    roots: list[tuple[str, Path]] = []
    identities: list[tuple[str, str]] = []
    for alias, value in sorted(mapping.items()):
        try:
            root = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceGrantError(
                "HOCUS916", "Approved external root does not exist.", {"alias": alias}
            ) from exc
        if not root.is_dir():
            raise WorkspaceGrantError(
                "HOCUS916", "Approved external root is not a directory.", {"alias": alias}
            )
        roots.append((alias, root))
        try:
            identity = _inspect_external_alias_root(
                project,
                alias,
                root,
                code="HOCUS916",
            )
        except WorkspaceGrantError:
            raise
        identities.append((alias, identity))
    return tuple(roots), tuple(identities)


def _inspect_external_alias_root(
    project: WorkspaceProject,
    alias: str,
    root: Path,
    *,
    code: str,
) -> str:
    alias_record = _project_alias_record(project, alias, code)
    try:
        with PinnedWorkspace(root) as pinned:
            identity = pinned.root_info.identity_digest
            raw = pinned.read(("hocus.module.toml",), _MAX_MODULE_MANIFEST_BYTES)
            pinned.assert_current()
    except NativeWorkspaceError as exc:
        raise WorkspaceGrantError(
            code,
            "Approved external module root could not be inspected safely.",
            {"alias": alias, "nativeCode": exc.code},
        ) from exc
    _validate_external_module_manifest(project, alias_record, raw, code)
    return identity


def _project_alias_record(
    project: WorkspaceProject,
    alias: str,
    code: str,
) -> tuple[str, str, str, str | None]:
    for record in project.projection.external_aliases:
        if record[0] == alias:
            return record
    raise WorkspaceGrantError(
        code,
        "Approved external alias is absent from the project authority.",
        {"alias": alias},
    )


def _validate_external_module_manifest(
    project: WorkspaceProject,
    alias_record: tuple[str, str, str, str | None],
    raw: bytes,
    code: str,
) -> None:
    alias, expected_uid, expected_version, expected_digest = alias_record
    actual_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and not secrets.compare_digest(
        expected_digest,
        actual_digest,
    ):
        raise WorkspaceGrantError(
            code,
            "External module manifest digest does not match the project authority.",
            {"alias": alias},
        )
    try:
        payload = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise WorkspaceGrantError(
            code,
            "External module manifest is not valid UTF-8 TOML.",
            {"alias": alias},
        ) from exc
    library = payload.get("library")
    expected_schema = 2 if project.projection.language_version == "0.3" else 1
    if (
        not isinstance(library, dict)
        or payload.get("schema_version") != expected_schema
        or library.get("uid") != expected_uid
        or library.get("version") != expected_version
    ):
        raise WorkspaceGrantError(
            code,
            "External module manifest identity does not match the project authority.",
            {"alias": alias},
        )


def _grant_names(values: tuple[str, ...]) -> tuple[str, ...]:
    selected = tuple(sorted(set(values)))
    if not selected or any(item not in WORKSPACE_GRANTS for item in selected):
        raise WorkspaceGrantError("HOCUS911", "Workspace grant selection is invalid.")
    return selected


def _principal(value: str) -> str:
    principal = str(value).strip()
    if not principal or len(principal) > 128:
        raise WorkspaceGrantError("HOCUS914", "Workspace principal identity is invalid.")
    return principal


def _client_info(payload: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    output: dict[str, str] = {}
    for key in ("name", "version", "title"):
        value = payload.get(key)
        if isinstance(value, str) and 0 < len(value) <= 128:
            output[key] = value
    return output


def _positive_ttl(value: float, label: str) -> float:
    ttl = float(value)
    if not 1 <= ttl <= 365 * 24 * 60 * 60:
        raise WorkspaceGrantError("HOCUS917", f"{label} expiry is outside supported bounds.")
    return ttl


def _stored_grant(grant: WorkspaceGrant) -> dict[str, Any]:
    return {
        **grant.host_payload(include_roots=True),
        "externalRoots": {alias: str(root) for alias, root in grant.external_roots},
        "externalRootIdentities": dict(grant.external_root_identities),
    }


def _decode_grants(payload: Any) -> tuple[WorkspaceGrant, ...]:
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in _SUPPORTED_GRANTS_VERSIONS
    ):
        raise ValueError("unsupported grants version")
    rows = payload.get("grants")
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError("invalid grant list")
    grants = tuple(_decode_grant(item, payload["version"]) for item in rows)
    if len({(item.principal_id, item.project_id) for item in grants}) != len(grants):
        raise ValueError("duplicate persistent grant")
    return grants


def _decode_grant(payload: Any, version: int) -> WorkspaceGrant:
    if not isinstance(payload, dict) or payload.get("persistent") is not True:
        raise ValueError("invalid persistent grant")
    roots = payload.get("externalRoots", {})
    identities = payload.get("externalRootIdentities", {})
    if not isinstance(roots, dict) or not isinstance(identities, dict):
        raise ValueError("invalid external roots")
    if set(roots) != set(identities):
        raise ValueError("external root identities are incomplete")
    expires_at = payload.get("expiresAt")
    if version == 2 and expires_at is None:
        raise ValueError("legacy persistent grants require a finite expiry")
    if expires_at is not None:
        expires_at = float(expires_at)
    if version == _GRANTS_VERSION and payload.get("untilRevoked") is not (
        expires_at is None
    ):
        raise ValueError("persistent grant lifetime metadata is inconsistent")
    return WorkspaceGrant(
        _principal(payload.get("principalId")),
        str(payload.get("projectId")),
        None,
        _grant_names(tuple(payload.get("grants", ()))),
        tuple(
            (str(alias), _stored_root(root))
            for alias, root in sorted(roots.items())
        ),
        tuple(
            (str(alias), _stored_identity(identity))
            for alias, identity in sorted(identities.items())
        ),
        str(payload.get("authorityProjectionDigest")),
        True,
        float(payload.get("createdAt")),
        expires_at,
        int(payload.get("generation")),
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
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
        raise WorkspaceGrantError("HOCUS918", "Could not persist workspace grants.") from exc


def _stored_root(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid stored external root")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("stored external root must be absolute")
    return candidate.resolve(strict=False)


def _stored_identity(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError("invalid stored root identity")
    return value


__all__ = [
    "EXTERNAL_READ",
    "GENERATED_LOCK",
    "SOURCE_NOTIFY",
    "SOURCE_READ",
    "SOURCE_WRITE",
    "WORKSPACE_GRANTS",
    "WorkspaceGrant",
    "WorkspaceGrantError",
    "WorkspaceGrantStore",
    "WorkspaceSession",
    "principal_from_bearer",
]
