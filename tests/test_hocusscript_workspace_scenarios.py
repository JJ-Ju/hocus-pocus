from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.core.server import HocusPocusRuntime
from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.workspace_authority import WorkspaceAuthority
from hocuspocus.core.workspace_grants import (
    EXTERNAL_READ,
    GENERATED_LOCK,
    SOURCE_READ,
    SOURCE_WRITE,
    principal_from_bearer,
)
from hocuspocus.live.context import RequestContext

from tests.hocusscript_h6_authority_helpers import (
    LOGGER,
    TOKEN,
    EXTERNAL_MANIFEST,
    NoopLiveOperations,
    assert_denied,
    assert_private_authority_surfaces,
    assert_until_revoked_grant,
    context as context_for,
    create_acceptance_workspaces,
    exercise_authority_close,
    exercise_config_owned_project,
    exercise_external_manifest_pin,
    exercise_legacy_grant_migration,
    exercise_project_manifest_identity,
    isolated_workspace_state,
    write_project,
)


class HocusScriptWorkspaceScenarios(unittest.TestCase):
    def test_h6_authority_registry_sessions_grants_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (
                state,
                project_root,
                ungranted_root,
                repointed_root,
                external_root,
            ) = create_acceptance_workspaces(
                base,
            )
            settings = ServerSettings(
                token_mode="static",
                token=TOKEN,
                source_projects=[],
            )
            principal = principal_from_bearer(
                f"Bearer {TOKEN}",
                token_mode="static",
            )

            with isolated_workspace_state(state):
                authority = WorkspaceAuthority(settings, LOGGER)
                project = authority.register_project(str(project_root))
                project_id = project.project_id
                self.assertTrue(project_id.startswith("hproj_"))
                self.assertEqual(
                    principal,
                    principal_from_bearer(
                        f"Bearer {TOKEN}",
                        token_mode="static",
                    ),
                )

                context = context_for(authority, principal)
                default_grant = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    session_id=context.session_id,
                )
                self.assertEqual(default_grant.grants, (SOURCE_READ,))
                read_authority = authority.authorize(
                    context,
                    project_id,
                    SOURCE_READ,
                )
                self.assertEqual(read_authority.access_mode, "read_only")
                assert_denied(
                    self,
                    "HOCUS823",
                    lambda: authority.authorize(context, project_id, SOURCE_WRITE),
                )

                write_grant = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    session_id=context.session_id,
                    grants=(SOURCE_READ, SOURCE_WRITE),
                )
                write_authority = authority.authorize(
                    context,
                    project_id,
                    SOURCE_WRITE,
                )
                self.assertEqual(write_authority.access_mode, "read_write")
                assert_denied(
                    self,
                    "HOCUS823",
                    lambda: authority.authorize(context, project_id, GENERATED_LOCK),
                )

                specialized = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    session_id=context.session_id,
                    grants=(
                        SOURCE_READ,
                        SOURCE_WRITE,
                        GENERATED_LOCK,
                        EXTERNAL_READ,
                    ),
                    external_roots={"studio": external_root},
                )
                lock_authority = authority.authorize(
                    context,
                    project_id,
                    GENERATED_LOCK,
                )
                external_authority = authority.authorize(
                    context,
                    project_id,
                    EXTERNAL_READ,
                    external_alias="studio",
                )
                self.assertEqual(
                    dict(external_authority.external_roots)["studio"],
                    external_root.resolve(),
                )
                assert_denied(
                    self,
                    "HOCUS825",
                    lambda: authority.authorize(
                        context,
                        project_id,
                        EXTERNAL_READ,
                        external_alias="unapproved",
                    ),
                )
                with self.subTest(external_root_identity_replacement=True):
                    original_external = base / "original-studio-library"
                    approved_external_identity = dict(
                        specialized.external_root_identities
                    )["studio"]
                    external_root.rename(original_external)
                    external_root.mkdir()
                    (external_root / "hocus.module.toml").write_bytes(
                        EXTERNAL_MANIFEST
                    )
                    assert_denied(
                        self,
                        "HOCUS825",
                        lambda: authority.authorize(
                            context,
                            project_id,
                            EXTERNAL_READ,
                            external_alias="studio",
                        ),
                    )
                    specialized = authority.host_grant(
                        project_id,
                        principal_id=principal,
                        session_id=context.session_id,
                        grants=(
                            SOURCE_READ,
                            SOURCE_WRITE,
                            GENERATED_LOCK,
                            EXTERNAL_READ,
                        ),
                        external_roots={"studio": external_root},
                    )
                    self.assertNotEqual(
                        dict(specialized.external_root_identities)["studio"],
                        approved_external_identity,
                    )
                    authority.authorize(
                        context,
                        project_id,
                        EXTERNAL_READ,
                        external_alias="studio",
                    )

                exercise_external_manifest_pin(
                    self,
                    authority,
                    context,
                    project_id,
                    external_root,
                )
                exercise_project_manifest_identity(
                    self,
                    authority,
                    context,
                    project_id,
                    project_root,
                )

                with self.subTest(project_root_identity_replacement=True):
                    original_project = base / "original-project"
                    approved_project_identity = project.root_identity_digest
                    project_root.rename(original_project)
                    shutil.copytree(original_project, project_root)
                    assert_denied(
                        self,
                        "HOCUS824",
                        lambda: authority.authorize(
                            context,
                            project_id,
                            SOURCE_READ,
                        ),
                    )
                    root_reapproved = authority.register_project(
                        str(project_root),
                        reapprove=True,
                    )
                    self.assertEqual(root_reapproved.project_id, project_id)
                    self.assertNotEqual(
                        root_reapproved.root_identity_digest,
                        approved_project_identity,
                    )
                    revalidated = authority.authorize(
                        context,
                        project_id,
                        SOURCE_READ,
                    )
                    self.assertEqual(
                        revalidated.root_identity_digest,
                        root_reapproved.root_identity_digest,
                    )

                generation_before_revoke = lock_authority.generation
                self.assertTrue(
                    authority.host_revoke(
                        project_id,
                        principal_id=principal,
                        session_id=context.session_id,
                        persistent=False,
                    )
                )
                assert_denied(
                    self,
                    "HOCUS823",
                    lambda: authority.authorize(context, project_id, SOURCE_READ),
                )
                expiring = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    session_id=context.session_id,
                    grants=(SOURCE_READ,),
                    expires_in_seconds=1,
                )
                with mock.patch(
                    "hocuspocus.core.workspace_grants.time.time",
                    return_value=expiring.expires_at + 1,
                ):
                    assert_denied(
                        self,
                        "HOCUS823",
                        lambda: authority.authorize(
                            context,
                            project_id,
                            SOURCE_READ,
                        ),
                    )
                refreshed = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    session_id=context.session_id,
                    grants=(
                        SOURCE_READ,
                        SOURCE_WRITE,
                        GENERATED_LOCK,
                        EXTERNAL_READ,
                    ),
                    external_roots={"studio": external_root},
                )
                refreshed_authority = authority.authorize(
                    context,
                    project_id,
                    SOURCE_READ,
                )
                self.assertGreater(
                    refreshed_authority.generation,
                    generation_before_revoke,
                )
                self.assertGreater(refreshed.generation, specialized.generation)

                write_project(
                    project_root,
                    "h6-authority-project",
                    expanded_sources=True,
                )
                assert_denied(
                    self,
                    "HOCUS824",
                    lambda: authority.authorize(context, project_id, SOURCE_READ),
                )
                reapproved = authority.registry.reapprove(project_id)
                self.assertEqual(reapproved.project_id, project_id)
                assert_denied(
                    self,
                    "HOCUS824",
                    lambda: authority.authorize(context, project_id, SOURCE_READ),
                )
                exercise_legacy_grant_migration(
                    self,
                    authority=authority,
                    principal=principal,
                    project_id=project_id,
                    state=state,
                )
                persistent_grant = authority.host_grant(
                    project_id,
                    principal_id=principal,
                    grants=(SOURCE_READ, SOURCE_WRITE, GENERATED_LOCK, EXTERNAL_READ),
                    external_roots={"studio": external_root},
                    persistent=True,
                    until_revoked=True,
                )
                assert_until_revoked_grant(
                    self,
                    authority=authority,
                    request_context=context,
                    project_id=project_id,
                    grant=persistent_grant,
                    state=state,
                )

                restarted = WorkspaceAuthority(settings, LOGGER)
                self.assertEqual(
                    restarted.registry.require(project_id).project_id,
                    project_id,
                )
                restarted_context = context_for(restarted, principal)
                persistent_authority = restarted.authorize(
                    restarted_context,
                    project_id,
                    SOURCE_WRITE,
                )
                self.assertIn(SOURCE_WRITE, persistent_authority.grants)
                self.assertIsNone(persistent_authority.expires_at)
                self.assertTrue(persistent_authority.public_metadata["untilRevoked"])

                configured_settings = ServerSettings(
                    token_mode="static",
                    token=TOKEN,
                    source_projects=[
                        {
                            "root": str(project_root),
                            "project_id": project_id,
                            "grants": [
                                SOURCE_READ,
                                SOURCE_WRITE,
                                GENERATED_LOCK,
                                EXTERNAL_READ,
                            ],
                            "external_roots": {"studio": str(external_root)},
                            "grant_until_revoked": True,
                        },
                        {"root": str(ungranted_root)},
                    ],
                )
                with mock.patch(
                    "hocuspocus.core.server.LiveOperations",
                    NoopLiveOperations,
                ):
                    runtime = HocusPocusRuntime(configured_settings, LOGGER)
                    runtime_principal = runtime.principal_for_authorization(
                        f"Bearer {TOKEN}"
                    )
                    runtime_session = runtime.issue_session(
                        runtime_principal,
                        {"name": "restart-client", "version": "1.0"},
                    )
                    runtime_context = RequestContext(
                        caller_id=runtime_principal,
                        principal_id=runtime_principal,
                        session_id=runtime_session.session_id,
                    )
                    configured_projects = runtime.list_authorized_projects(
                        runtime_context
                    )
                    self.assertEqual(
                        [item["projectId"] for item in configured_projects],
                        [project_id],
                    )
                    runtime_authority = runtime.authorize_workspace(
                        runtime_context,
                        project_id,
                        EXTERNAL_READ,
                        external_alias="studio",
                    )
                    self.assertEqual(runtime_authority.project_id, project_id)
                    self.assertIsNone(runtime_authority.expires_at)
                    exercise_config_owned_project(
                        self,
                        runtime=runtime,
                        request_context=runtime_context,
                        project_id=project_id,
                        project_root=project_root,
                    )

                    repointed_settings = ServerSettings(
                        token_mode="static",
                        token=TOKEN,
                        source_projects=[
                            {
                                **configured_settings.source_projects[0],
                                "root": str(repointed_root),
                            },
                            configured_settings.source_projects[1],
                        ],
                    )
                    runtime_restart = HocusPocusRuntime(
                        repointed_settings,
                        LOGGER,
                    )
                    restarted_session = runtime_restart.issue_session(
                        runtime_principal,
                        {"name": "restart-client", "version": "1.0"},
                    )
                    restarted_runtime_context = RequestContext(
                        caller_id=runtime_principal,
                        principal_id=runtime_principal,
                        session_id=restarted_session.session_id,
                    )
                    self.assertEqual(
                        runtime_restart.authorize_workspace(
                            restarted_runtime_context,
                            project_id,
                            GENERATED_LOCK,
                        ).project_id,
                        project_id,
                    )
                    restarted_project = (
                        runtime_restart.workspace_authority.registry.require(project_id)
                    )
                    self.assertEqual(restarted_project.root, repointed_root.resolve())
                    self.assertTrue(
                        next(
                            item
                            for item in runtime_restart.workspace_snapshot()["projects"]
                            if item["projectId"] == project_id
                        )["configOwned"]
                    )

                assert_private_authority_surfaces(
                    self,
                    state=state,
                    project_root=project_root,
                    external_root=external_root,
                    project=project,
                    authorized=persistent_authority,
                    authority=restarted,
                    request_context=restarted_context,
                )
                self.assertEqual(write_grant.persistent, False)
                exercise_authority_close(
                    self,
                    state=state,
                    authority=authority,
                    restarted=restarted,
                    runtime=runtime,
                    runtime_restart=runtime_restart,
                )

    def test_h6_descriptor_safe_enumeration_search_and_reads(self) -> None:
        from tests.hocusscript_h6_io_helpers import exercise_descriptor_safe_reads

        exercise_descriptor_safe_reads(self)

    def test_h6_guarded_create_patch_publication_and_invalidation(self) -> None:
        from tests.hocusscript_h6_io_helpers import exercise_guarded_publication

        exercise_guarded_publication(self)

    def test_h6_native_source_project_operations_and_export_auth(self) -> None:
        from tests.hocusscript_h6_source_helpers import (
            exercise_h6_source_workflow_4,
        )

        exercise_h6_source_workflow_4(self)

    def test_h6_mcp_source_surface_limits_audit_and_revocation(self) -> None:
        from tests.hocusscript_h6_source_helpers import (
            exercise_h6_source_workflow_5,
        )

        exercise_h6_source_workflow_5(self)

    def test_h6_installed_houdini_source_to_live_acceptance(self) -> None:
        from tests.hocusscript_h6_installed_helpers import (
            exercise_h6_installed_workflow,
        )

        exercise_h6_installed_workflow(self)


if __name__ == "__main__":
    unittest.main()
