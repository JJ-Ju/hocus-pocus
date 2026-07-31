from __future__ import annotations

import hashlib
import json
import logging
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

from hocuspocus.core.server import HocusPocusRuntime
from hocuspocus.core.workspace_authority import (
    WorkspaceAuthority,
    WorkspaceAuthorityError,
)
from hocuspocus.core.workspace_grants import (
    EXTERNAL_READ,
    SOURCE_READ,
    WorkspaceGrantError,
    WorkspaceGrantStore,
)
from hocuspocus.live.context import RequestContext

LOGGER = logging.getLogger("hocuspocus.tests.workspace")
TOKEN = "h6-acceptance-bearer"
EXTERNAL_MANIFEST = b"""schema_version = 2
entry_modules = ["modules/main.hocus"]
[library]
uid = "studio-library"
version = "1.0.0"
[language]
version = "0.3"
"""
_ALIAS_DIGEST = "sha256:" + hashlib.sha256(EXTERNAL_MANIFEST).hexdigest()


class NoopLiveOperations:
    def __init__(self, *_args, **_kwargs):
        pass

    @staticmethod
    def register(_tools, _resources) -> None:
        return None


def write_project(root: Path, uid: str, *, expanded_sources: bool = False) -> None:
    source_directories = ["src", "alt"] if expanded_sources else ["src"]
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if expanded_sources:
        (root / "alt").mkdir(exist_ok=True)
    rendered_sources = json.dumps(source_directories)
    (root / "hocus.project.toml").write_text(
        f"""schema_version = 4
[project]
uid = "{uid}"
name = "H6 Acceptance"
source_directories = {rendered_sources}
module_directories = ["modules"]
[language]
version = "0.3"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
[external_aliases.studio]
library_uid = "studio-library"
version = "1.0.0"
module_manifest_digest = "{_ALIAS_DIGEST}"
""",
        encoding="utf-8",
    )
    (root / "src/main.hocus").write_text(
        'hocus 0.3;\ngraph Main { target "/obj"; category Sop; }\n',
        encoding="utf-8",
    )


@contextmanager
def isolated_workspace_state(state: Path):
    with ExitStack() as stack:
        stack.enter_context(
            mock.patch(
                "hocuspocus.core.workspace_registry.workspace_registry_path",
                return_value=state / "registry.json",
            )
        )
        stack.enter_context(
            mock.patch(
                "hocuspocus.core.workspace_grants.workspace_grants_path",
                return_value=state / "grants.json",
            )
        )
        stack.enter_context(
            mock.patch(
                "hocuspocus.core.source_audit.workspace_audit_path",
                return_value=state / "audit.sqlite3",
            )
        )
        stack.enter_context(
            mock.patch(
                "hocuspocus.core.audit.audit_log_path",
                return_value=state / "generic-audit.jsonl",
            )
        )
        yield


def context(authority: WorkspaceAuthority, principal: str) -> RequestContext:
    session = authority.issue_session(
        principal,
        {"name": "acceptance-client", "version": "1.0"},
    )
    return RequestContext(
        caller_id=principal,
        principal_id=principal,
        session_id=session.session_id,
    )


def create_acceptance_workspaces(
    base: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    state = base / "host-state"
    project_root = base / "project"
    ungranted_root = base / "ungranted-project"
    repointed_root = base / "repointed-project"
    external_root = base / "studio-library"
    external_root.mkdir()
    (external_root / "hocus.module.toml").write_bytes(EXTERNAL_MANIFEST)
    write_project(project_root, "h6-authority-project")
    write_project(ungranted_root, "h6-ungranted-project")
    write_project(
        repointed_root,
        "h6-authority-project",
        expanded_sources=True,
    )
    return state, project_root, ungranted_root, repointed_root, external_root


def assert_denied(
    case: unittest.TestCase,
    code: str,
    callback,
) -> None:
    with case.assertRaises(WorkspaceAuthorityError) as caught:
        callback()
    case.assertEqual(caught.exception.code, code)


def exercise_external_manifest_pin(
    case: unittest.TestCase,
    authority: WorkspaceAuthority,
    request_context: RequestContext,
    project_id: str,
    external_root: Path,
) -> None:
    with case.subTest(external_manifest_semantic_pin=True):
        hostile_manifest = EXTERNAL_MANIFEST.replace(
            b'version = "1.0.0"',
            b'version = "2.0.0"',
        )
        (external_root / "hocus.module.toml").write_bytes(hostile_manifest)
        with case.assertRaises(WorkspaceGrantError) as rejected_grant:
            authority.host_grant(
                project_id,
                principal_id=request_context.principal_id,
                session_id=request_context.session_id,
                grants=(SOURCE_READ, EXTERNAL_READ),
                external_roots={"studio": external_root},
            )
        case.assertEqual(rejected_grant.exception.code, "HOCUS916")
        assert_denied(
            case,
            "HOCUS825",
            lambda: authority.authorize(
                request_context,
                project_id,
                EXTERNAL_READ,
                external_alias="studio",
            ),
        )
        (external_root / "hocus.module.toml").write_bytes(EXTERNAL_MANIFEST)
        authority.authorize(
            request_context,
            project_id,
            EXTERNAL_READ,
            external_alias="studio",
        )


def exercise_project_manifest_identity(
    case: unittest.TestCase,
    authority: WorkspaceAuthority,
    request_context: RequestContext,
    project_id: str,
    project_root: Path,
) -> None:
    with case.subTest(project_manifest_identity=True):
        approved = authority.registry.require(project_id)
        manifest = project_root / "hocus.project.toml"
        replacement = project_root / "replacement.project.toml"
        replacement.write_bytes(manifest.read_bytes())
        replacement.replace(manifest)
        assert_denied(
            case,
            "HOCUS824",
            lambda: authority.authorize(request_context, project_id, SOURCE_READ),
        )
        with case.assertRaises(WorkspaceAuthorityError):
            authority.accept_current_manifest_identity(
                project_id,
                "sha256:" + ("0" * 64),
            )
        assert_denied(
            case,
            "HOCUS824",
            lambda: authority.authorize(request_context, project_id, SOURCE_READ),
        )
        accepted = authority.accept_current_manifest_identity(
            project_id,
            approved.projection.digest,
        )
        case.assertNotEqual(
            accepted.manifest_identity_digest,
            approved.manifest_identity_digest,
        )
        authority.authorize(request_context, project_id, SOURCE_READ)


def assert_until_revoked_grant(
    case: unittest.TestCase,
    *,
    authority: WorkspaceAuthority,
    request_context: RequestContext,
    project_id: str,
    grant,
    state: Path,
) -> None:
    with case.subTest(persistent_until_revoked=True):
        case.assertIsNone(grant.expires_at)
        case.assertTrue(grant.host_payload(include_roots=False)["untilRevoked"])
        stored = json.loads((state / "grants.json").read_text(encoding="utf-8"))
        case.assertEqual(stored["version"], 3)
        case.assertIsNone(stored["grants"][0]["expiresAt"])
        case.assertTrue(stored["grants"][0]["untilRevoked"])
        with case.assertRaises(WorkspaceGrantError):
            authority.host_grant(
                project_id,
                principal_id=request_context.principal_id,
                session_id=request_context.session_id,
                until_revoked=True,
            )
        with case.assertRaises(WorkspaceGrantError):
            authority.host_grant(
                project_id,
                principal_id=request_context.principal_id,
                session_id=request_context.session_id,
                expires_in_seconds=0,
            )


def exercise_legacy_grant_migration(
    case: unittest.TestCase,
    *,
    authority: WorkspaceAuthority,
    principal: str,
    project_id: str,
    state: Path,
) -> None:
    with case.subTest(legacy_finite_grant_migration=True):
        authority.host_grant(
            project_id,
            principal_id=principal,
            persistent=True,
            expires_in_seconds=3600,
        )
        path = state / "grants.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = 2
        for row in payload["grants"]:
            row.pop("untilRevoked", None)
        path.write_text(json.dumps(payload), encoding="utf-8")
        migrated = WorkspaceGrantStore(path=path)
        grant = migrated.host_snapshot()["grants"][0]
        case.assertIsNotNone(grant["expiresAt"])
        case.assertFalse(grant["untilRevoked"])
        case.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["version"],
            3,
        )


def exercise_config_owned_project(
    case: unittest.TestCase,
    *,
    runtime: HocusPocusRuntime,
    request_context: RequestContext,
    project_id: str,
    project_root: Path,
) -> None:
    with case.subTest(config_owned_project=True):
        snapshot = runtime.workspace_snapshot()
        configured = next(
            item for item in snapshot["projects"] if item["projectId"] == project_id
        )
        case.assertTrue(configured["configOwned"])
        assert_denied(
            case,
            "HOCUS826",
            lambda: runtime.workspace_authority.remove_project(project_id),
        )
        assert_denied(
            case,
            "HOCUS826",
            lambda: runtime.workspace_authority.register_project(
                str(project_root),
                reapprove=True,
            ),
        )
        listed = runtime.list_authorized_projects(request_context)
        case.assertNotIn("configOwned", listed[0])


def assert_private_authority_surfaces(
    case: unittest.TestCase,
    *,
    state: Path,
    project_root: Path,
    external_root: Path,
    project,
    authorized,
    authority: WorkspaceAuthority,
    request_context: RequestContext,
) -> None:
    client_surfaces = {
        "project": project.client_payload(),
        "authorized": authorized.public_metadata,
        "listed": authority.list_projects(request_context),
    }
    client_json = json.dumps(client_surfaces, sort_keys=True)
    case.assertNotIn(str(project_root), client_json)
    case.assertNotIn(str(external_root), client_json)
    case.assertNotIn(authorized.root_identity_digest, client_json)
    case.assertNotIn(authorized.manifest_identity_digest, client_json)
    case.assertNotIn(
        authority.registry.require(project.project_id).manifest_identity_digest,
        client_json,
    )
    for _, identity in authorized.external_root_identities:
        case.assertNotIn(identity, client_json)
    audit_rows = authority.audit_logger.recent(limit=1000)
    audit_json = json.dumps(audit_rows, sort_keys=True)
    case.assertNotIn(str(project_root), audit_json)
    case.assertNotIn(str(external_root), audit_json)
    case.assertNotIn(
        str(project_root).encode("utf-8"),
        (state / "audit.sqlite3").read_bytes(),
    )


def exercise_authority_close(
    case: unittest.TestCase,
    *,
    state: Path,
    authority: WorkspaceAuthority,
    restarted: WorkspaceAuthority,
    runtime: HocusPocusRuntime,
    runtime_restart: HocusPocusRuntime,
) -> None:
    with case.subTest(authority_lifecycle_close=True):
        runtime.stop()
        runtime.stop()
        runtime_restart.stop()
        restarted.close()
        restarted.close()
        authority.close()
        case.assertTrue(runtime.workspace_authority.closed)
        case.assertTrue(runtime_restart.workspace_authority.closed)
        case.assertTrue(restarted.closed)
        case.assertTrue(authority.closed)
        audit_path = state / "audit.sqlite3"
        released_path = state / "audit-released.sqlite3"
        audit_path.rename(released_path)
        released_path.rename(audit_path)
