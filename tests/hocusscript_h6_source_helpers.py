"""Private H6 source-service acceptance workflows for the consolidated catalogue."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.workspace_authority import WorkspaceAuthority
from hocuspocus.core.workspace_rate import WorkspaceRateLimiter
from hocuspocus.core.workspace_grants import (
    EXTERNAL_READ,
    GENERATED_LOCK,
    SOURCE_READ,
    SOURCE_WRITE,
)
from hocuspocus.hocusscript.project_services import (
    SourceServiceError,
    SourceWorkspaceService,
)
from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.ops.source_resources import _source_resource_templates
from hocuspocus.live.ops.source_workspace import (
    SourceWorkspaceOperationsMixin,
    _source_tool_definitions,
)

from tests.hocusscript_h6_authority_helpers import (
    context as workspace_context,
    isolated_workspace_state,
    write_project,
)

_LOGGER = logging.getLogger("hocuspocus.tests.h6-source")
_SOURCE_TOOLS = [
    "source.project.describe",
    "source.file.search",
    "source.file.read",
    "source.file.apply_patch",
    "source.file.write_export",
    "source.project.build",
    "source.project.navigate",
]


class _SourceHarness(SourceWorkspaceOperationsMixin):
    pass


class _ToolOwner:
    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: None


class _GateLock:
    def __init__(self, waiting: threading.Event, release: threading.Event):
        self._waiting = waiting
        self._release = release

    def __enter__(self):
        self._waiting.set()
        if not self._release.wait(2):
            raise TimeoutError("rate-limit lock gate timed out")
        return self

    def __exit__(self, *_args):
        return False


def exercise_h6_source_workflow_4(case) -> None:
    """Exercise native project operations and hostile export authentication."""

    from tests.test_hocusscript_project_scenarios import (
        CATALOG,
        _control_mixed_project,
        _control_native_project,
        _mixed_project,
        _native_project,
    )
    from hocuspocus.hocusscript.catalog import decode_catalog_snapshot
    from scripts.smoke_hocusscript_h6_support import write_export_project

    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        state = base / "state"
        local_module = base / "local-module"
        bootstrap_module = base / "bootstrap-module"
        local_control = base / "local-control"
        _native_project(local_module)
        _native_project(bootstrap_module)
        (bootstrap_module / "pins/hocus.lock.json").unlink()
        _control_native_project(local_control)
        mixed_module, module_library = _mixed_project(base / "mixed-module")
        mixed_control, control_library = _control_mixed_project(
            base / "mixed-control",
        )
        flat = base / "flat-export"
        catalog = decode_catalog_snapshot(CATALOG.read_bytes())
        write_export_project(flat, catalog.to_json(), catalog.fingerprint)
        (flat / "src/reconciled.hocus").write_text(
            'hocus 0.1;\ngraph Main {\n  target "/obj/geo1";\n'
            '  category Sop;\n  mode reconcile;\n  ownership "h6.flat";\n'
            '  node out @id("out"): "null" {}\n  output = out;\n}\n',
            encoding="utf-8",
        )
        projects = (
            ("module-local", local_module, None),
            ("module-bootstrap", bootstrap_module, None),
            ("module-mixed", mixed_module, module_library),
            ("control-local", local_control, None),
            ("control-mixed", mixed_control, control_library),
        )
        with isolated_workspace_state(state):
            authority = WorkspaceAuthority(ServerSettings(), _LOGGER)
            try:
                context = workspace_context(authority, "h6-source-workflow-4")
                service = SourceWorkspaceService(authority)
                registered: dict[str, str] = {}
                for label, root, external in projects:
                    project = authority.register_project(str(root), label=label)
                    grants = [
                        SOURCE_READ,
                        SOURCE_WRITE,
                        GENERATED_LOCK,
                    ]
                    roots = None
                    if external is not None:
                        grants.append(EXTERNAL_READ)
                        roots = {"terrain": str(external)}
                    authority.host_grant(
                        project.project_id,
                        principal_id=context.principal_id,
                        session_id=context.session_id,
                        grants=tuple(grants),
                        external_roots=roots,
                    )
                    registered[label] = project.project_id
                flat_project = authority.register_project(
                    str(flat),
                    label="flat-export",
                )
                authority.host_grant(
                    flat_project.project_id,
                    principal_id=context.principal_id,
                    session_id=context.session_id,
                    grants=(SOURCE_READ, SOURCE_WRITE),
                )
                for label, root, external in projects:
                    if label == "module-bootstrap":
                        _exercise_lock_bootstrap(
                            case,
                            service,
                            context,
                            registered[label],
                            root,
                        )
                        continue
                    with case.subTest(h6_source_native_operation=label):
                        _exercise_project_operation_lane(
                            case,
                            service,
                            context,
                            registered[label],
                            root,
                            mixed=external is not None,
                        )
                _exercise_flat_project_build(
                    case,
                    service,
                    context,
                    flat_project.project_id,
                )
                _exercise_export_replacement(
                    case,
                    service,
                    context,
                    flat_project.project_id,
                    flat,
                    catalog.fingerprint,
                )
                _exercise_export_authentication(
                    case,
                    authority,
                    service,
                    context,
                    registered["module-local"],
                )
                _exercise_build_error_boundary(
                    case,
                    authority,
                    service,
                    context,
                    registered["module-local"],
                )
                _exercise_commit_aware_source_cancellation(
                    case, authority, service, registered["module-local"],
                )
                _exercise_write_authority_races(
                    case,
                    authority,
                    service,
                    registered["module-local"],
                    local_module,
                )
                _exercise_terminal_write_lifecycle(
                    case,
                    authority,
                    service,
                    registered["module-local"],
                    local_module,
                )
                from tests.hocusscript_h6_response_helpers import (
                    exercise_exact_mutation_response_preflight,
                )
                exercise_exact_mutation_response_preflight(case)
            finally:
                authority.close()


def _exercise_flat_project_build(
    case,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
) -> None:
    common = {"projectId": project_id}
    checked = service.build(
        context,
        {**common, "action": "check", "entryPath": "src/reconciled.hocus"},
    )
    compiled = service.build(
        context,
        {**common, "action": "compile", "entryPath": "src/reconciled.hocus"},
    )
    case.assertTrue(checked["valid"])
    case.assertTrue(compiled["valid"])
    case.assertEqual(compiled["bundle"]["bundleVersion"], "0.2")
    case.assertEqual(compiled["bundle"]["languageVersion"], "0.1")
    case.assertTrue(compiled["bundle"]["portable"])


def _exercise_export_replacement(
    case,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
    root: Path,
    catalog_fingerprint: str,
) -> None:
    from hocuspocus.hocusscript.workspace_io import WorkspaceIO
    from hocuspocus.hocusscript.workspace_snapshot import WorkspaceNativeSnapshot

    path = root / "src/reconciled.hocus"
    previous = path.read_bytes().decode("utf-8")
    source = previous.replace("graph Main", "graph ExportReplacement")
    provenance = {
        "format": "hocus-export-provenance-v0.1",
        "sourceDigest": _raw_digest(source),
        "catalogFingerprint": catalog_fingerprint,
        "entities": {},
    }
    signed = service.issue_export_handoff(
        context,
        {
            "stage": "source_export",
            "exportVersion": "1.0",
            "languageVersion": "0.1",
            "valid": True,
            "source": source,
            "provenance": provenance,
        },
    )
    cleanup_complete = threading.Event()
    close_snapshot = WorkspaceNativeSnapshot.close
    commit_write = WorkspaceIO._commit_prepared

    def close_before_commit(snapshot):
        close_snapshot(snapshot)
        cleanup_complete.set()

    def commit_after_cleanup(workspace, prepared):
        case.assertTrue(cleanup_complete.is_set())
        return commit_write(workspace, prepared)

    with mock.patch.object(
        WorkspaceNativeSnapshot, "close", close_before_commit,
    ), mock.patch.object(
        WorkspaceIO, "_commit_prepared", commit_after_cleanup,
    ):
        result = service.write_export(
            context,
            {
                "projectId": project_id,
                "destination": "src/reconciled.hocus",
                "expectedDigest": _raw_digest(previous),
                "handoff": signed,
            },
        )
    with case.subTest(export_replace_self_drift=True):
        case.assertEqual(path.read_bytes().decode("utf-8"), source)
        case.assertFalse(result["created"])
        case.assertEqual(result["rawDigest"], _raw_digest(source))


def _exercise_project_operation_lane(
    case,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
    root: Path,
    *,
    mixed: bool,
) -> None:
    described = service.describe(context, project_id)["projects"][0]
    case.assertEqual(described["manifestStatus"], "current")
    case.assertEqual(described["lockStatus"], "current")
    projection = described["authorityProjectionDigest"]
    common = {
        "projectId": project_id,
        "authorityProjectionDigest": projection,
    }
    formatted = service.build(
        context,
        {**common, "action": "format", "sourcePath": "src/main.hocus"},
    )
    case.assertEqual(formatted["projectId"], project_id)
    checked = service.build(
        context,
        {**common, "action": "check", "entryPath": "src/main.hocus"},
    )
    case.assertTrue(checked["valid"])
    compiled = service.build(
        context,
        {**common, "action": "compile", "entryPath": "src/main.hocus"},
    )
    case.assertTrue(compiled["valid"])
    source = (root / "src/main.hocus").read_text(encoding="utf-8")
    completion = service.navigate(
        context,
        {
            **common,
            "operation": "completion",
            "path": "src/main.hocus",
            "offset": min(len(source), source.find("graph") + 2),
            "limit": 20,
        },
    )
    case.assertEqual(completion["projectId"], project_id)
    dirty = service.navigate(
        context,
        {
            **common,
            "operation": "definition",
            "path": "src/main.hocus",
            "source": source,
            "offset": max(0, source.find("Terrain") + 2),
            "limit": 20,
        },
    )
    case.assertEqual(dirty["projectId"], project_id)
    if not mixed:
        module = root / "modules/root.hocus"
        module.write_text(
            module.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
    updated = service.build(
        context,
        {
            **common,
            "action": "lock_update",
            "entryPaths": ["src/main.hocus"],
            "writeIntent": "update_generated_lock",
            "expectedLockState": "present",
            "expectedLockDigest": described["lockDigest"],
        },
    )
    case.assertTrue(updated["valid"])
    case.assertFalse(updated["publication"]["created"])
    if not mixed:
        case.assertTrue(updated["derivation"]["changed"])
        case.assertNotEqual(
            updated["publication"]["previousRawDigest"],
            updated["publication"]["rawDigest"],
        )
    _assert_no_native_path(case, formatted, root)
    _assert_no_native_path(case, checked, root)
    _assert_no_native_path(case, compiled, root)
    _assert_no_native_path(case, completion, root)
    _assert_no_native_path(case, dirty, root)
    case.assertEqual(bool(mixed), bool(described["externalAliases"]))


def _exercise_lock_bootstrap(
    case,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
    root: Path,
) -> None:
    described = service.describe(context, project_id)["projects"][0]
    case.assertEqual(described["lockStatus"], "missing")
    common = {
        "projectId": project_id,
        "authorityProjectionDigest": described["authorityProjectionDigest"],
        "action": "lock_update",
        "entryPaths": ["src/main.hocus"],
        "writeIntent": "update_generated_lock",
    }
    created = service.build(
        context, {**common, "expectedLockState": "absent"},
    )
    case.assertTrue(created["valid"])
    case.assertTrue(created["publication"]["created"])
    lock_path = root / "pins/hocus.lock.json"
    generated = lock_path.read_bytes()
    with case.assertRaises(SourceServiceError) as stale_create:
        service.build(context, {**common, "expectedLockState": "absent"})
    case.assertEqual(stale_create.exception.code, "HOCUS826")

    lock_path.unlink()
    from hocuspocus.hocusscript.workspace_io import WorkspaceIO

    original_commit = WorkspaceIO._commit_prepared

    def concurrent_publish(workspace, prepared):
        if prepared.create:
            lock_path.write_bytes(generated)
        return original_commit(workspace, prepared)

    with mock.patch.object(WorkspaceIO, "_commit_prepared", concurrent_publish):
        with case.assertRaises(SourceServiceError) as concurrent:
            service.build(context, {**common, "expectedLockState": "absent"})
    case.assertEqual(concurrent.exception.code, "HOCUS826")
    case.assertEqual(lock_path.read_bytes(), generated)

    current = service.describe(context, project_id)["projects"][0]
    with case.assertRaises(SourceServiceError) as stale_replace:
        service.build(
            context,
            {
                **common,
                "expectedLockState": "present",
                "expectedLockDigest": "sha256:" + "0" * 64,
            },
        )
    case.assertEqual(stale_replace.exception.code, "HOCUS830")
    case.assertEqual(
        service.describe(context, project_id)["projects"][0]["lockDigest"],
        current["lockDigest"],
    )


def _exercise_build_error_boundary(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
) -> None:
    projection = service.describe(
        context, project_id,
    )["projects"][0]["authorityProjectionDigest"]
    harness = _SourceHarness()
    harness.bind_source_workspace(authority)
    harness._source_workspace_service = service
    with mock.patch(
        "hocuspocus.hocusscript.project_services.SourceWorkspaceService._run_build",
        side_effect=RuntimeError("compiler boundary failure"),
    ), case.assertRaises(JsonRpcError) as rejected:
        harness.source_project_build(
            {
                "projectId": project_id,
                "authorityProjectionDigest": projection,
                "action": "compile",
                "entryPath": "src/main.hocus",
            },
            context,
        )
    case.assertEqual(rejected.exception.code, INVALID_PARAMS)
    case.assertEqual(rejected.exception.data, {"hocusCode": "HOCUS830"})
    with service.build_slot(context, project_id):
        with case.assertRaises(SourceServiceError) as busy:
            with service.build_slot(context, project_id):
                case.fail("concurrent project build slot was admitted")
    case.assertEqual(busy.exception.code, "HOCUS825")


def _exercise_export_authentication(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
) -> None:
    handoff = {
        "stage": "source_export",
        "exportVersion": "1.0",
        "languageVersion": "0.1",
        "valid": True,
        "source": 'hocus 0.1;\ngraph Export { target "/obj"; category Sop; }\n',
        "provenance": {
            "format": "hocus-export-provenance-v0.1",
            "sourceDigest": "sha256:" + "0" * 64,
            "entities": {},
        },
    }
    signed = service.issue_export_handoff(context, handoff)
    service.verify_export_handoff(context, signed)
    other = workspace_context(authority, context.principal_id)
    authority.host_grant(
        project_id,
        principal_id=other.principal_id,
        session_id=other.session_id,
        grants=(SOURCE_READ, SOURCE_WRITE),
    )
    candidates = (
        ("unsigned", handoff, context),
        ("altered", {**signed, "source": signed["source"] + " "}, context),
        ("cross-session", signed, other),
    )
    for label, candidate, request_context in candidates:
        with case.subTest(export_token_hostile=label):
            with case.assertRaises(SourceServiceError) as rejected:
                service.write_export(
                    request_context,
                    {
                        "projectId": project_id,
                        "destination": "src/exported.hocus",
                        "handoff": candidate,
                    },
                )
            case.assertEqual(rejected.exception.code, "HOCUS829")
    with mock.patch(
        "hocuspocus.hocusscript.export_handoff_auth.time.time",
        return_value=100.0,
    ):
        expired = service.issue_export_handoff(context, handoff)
    with mock.patch(
        "hocuspocus.hocusscript.export_handoff_auth.time.time",
        return_value=401.0,
    ), case.assertRaises(SourceServiceError) as rejected:
        service.write_export(
            context,
            {
                "projectId": project_id,
                "destination": "src/exported.hocus",
                "handoff": expired,
            },
        )
    case.assertEqual(rejected.exception.code, "HOCUS829")


def _exercise_commit_aware_source_cancellation(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    project_id: str,
) -> None:
    harness = _SourceHarness()
    harness.bind_source_workspace(authority)
    harness._source_workspace_service = service
    calls = (
        (
            "patch",
            "apply_patch",
            harness.source_file_apply_patch,
            {"projectId": project_id, "mode": "create"},
        ),
        (
            "export",
            "write_export",
            harness.source_file_write_export,
            {"projectId": project_id},
        ),
        (
            "lock",
            "build",
            harness.source_project_build,
            {"projectId": project_id, "action": "lock_update"},
        ),
    )
    for label, method, invoke, arguments in calls:
        context = workspace_context(authority, f"h6-postcommit-{label}")

        def committed(*_args, **_kwargs):
            context.cancel()
            return {"valid": True, "commit": label}

        with case.subTest(postcommit_cancellation=label), mock.patch.object(
            service, method, side_effect=committed,
        ), mock.patch.object(
            service,
            "ensure_response",
            side_effect=AssertionError("postcommit response check"),
        ) as response_check:
            response = invoke(arguments, context)
            case.assertEqual(response["structuredContent"]["commit"], label)
            response_check.assert_not_called()
    audit_context = workspace_context(authority, "h6-postcommit-audit")
    with case.subTest(postcommit_audit_nonmasking=True), mock.patch.object(
        service,
        "apply_patch",
        return_value={"valid": True, "commit": "audit"},
    ), mock.patch.object(
        authority, "audit", side_effect=OSError("private-audit-state"),
    ):
        response = harness.source_file_apply_patch(
            {"projectId": project_id, "mode": "create"},
            audit_context,
        )
        case.assertEqual(response["structuredContent"]["commit"], "audit")
    cancelled = workspace_context(authority, "h6-precommit-cancel")
    cancelled.cancel()
    with case.subTest(precommit_cancellation=True), mock.patch.object(
        service, "apply_patch",
    ) as callback, case.assertRaises(OperationCancelledError):
        harness.source_file_apply_patch(
            {"projectId": project_id, "mode": "create"},
            cancelled,
        )
    callback.assert_not_called()


def _exercise_write_authority_races(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    project_id: str,
    root: Path,
) -> None:
    _exercise_revoke_waits_for_publication(
        case, authority, service, project_id, root,
    )
    _exercise_expiry_prevents_publication(
        case, authority, service, project_id, root,
    )


def _exercise_revoke_waits_for_publication(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    project_id: str,
    root: Path,
) -> None:
    from hocuspocus.hocusscript.workspace_io import WorkspaceIO

    context = workspace_context(authority, "h6-write-revoke-race")
    authority.host_grant(
        project_id,
        principal_id=context.principal_id,
        session_id=context.session_id,
        grants=(SOURCE_READ, SOURCE_WRITE),
    )
    entered = threading.Event()
    release = threading.Event()
    revoke_started = threading.Event()
    revoke_finished = threading.Event()
    original_commit = WorkspaceIO._commit_prepared

    def blocking_create(workspace, prepared):
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("write lease publication was not released")
        return original_commit(workspace, prepared)

    def revoke():
        revoke_started.set()
        try:
            return authority.host_revoke(
                project_id,
                principal_id=context.principal_id,
                session_id=context.session_id,
            )
        finally:
            revoke_finished.set()

    request = {
        "projectId": project_id,
        "mode": "create",
        "path": "src/revoke-race.hocus",
        "content": (
            'hocus 0.2;\ngraph RevokeRace { target "/obj"; category Sop; }\n'
        ),
    }
    with mock.patch.object(WorkspaceIO, "_commit_prepared", blocking_create), (
        ThreadPoolExecutor(max_workers=2)
    ) as pool:
        publication = pool.submit(service.apply_patch, context, request)
        case.assertTrue(entered.wait(timeout=10))
        revocation = pool.submit(revoke)
        case.assertTrue(revoke_started.wait(timeout=10))
        with case.subTest(revocation_waits_for_admitted_commit=True):
            case.assertFalse(revoke_finished.wait(timeout=0.1))
        release.set()
        result = publication.result(timeout=10)
        case.assertTrue(revocation.result(timeout=10))
    case.assertEqual(result["path"], "src/revoke-race.hocus")
    case.assertTrue((root / "src/revoke-race.hocus").is_file())
    with case.assertRaises(SourceServiceError) as denied:
        service.apply_patch(
            context,
            {
                **request,
                "path": "src/revoked-write.hocus",
            },
        )
    case.assertEqual(denied.exception.code, "HOCUS823")


def _exercise_expiry_prevents_publication(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    project_id: str,
    root: Path,
) -> None:
    from hocuspocus.hocusscript.project_manifest_guard import (
        validate_manifest_patch as validate,
    )
    from hocuspocus.hocusscript.workspace_io import WorkspaceIO
    from scripts.smoke_hocusscript_h6_support import unified_replacement

    context = workspace_context(authority, "h6-expiring-writer")
    clock = {"now": 100.0}
    with mock.patch(
        "hocuspocus.core.workspace_grants.time.time",
        side_effect=lambda: clock["now"],
    ):
        authority.host_grant(
            project_id,
            principal_id=context.principal_id,
            session_id=context.session_id,
            grants=(SOURCE_READ, SOURCE_WRITE),
            expires_in_seconds=1.0,
        )
        source = (root / "src/main.hocus").read_bytes().decode("utf-8")
        updated = source.replace("graph ", "graph Expiry", 1)
        case.assertNotEqual(updated, source)
        patch = unified_replacement("src/main.hocus", source, updated)
        if "\r\n" in source:
            patch = patch.replace("\r\n", "\n").replace("\n", "\r\n")

        def expire_after_preflight(*args, **kwargs):
            validate(*args, **kwargs)
            clock["now"] = 102.0

        with mock.patch(
            "hocuspocus.hocusscript.project_manifest_guard.validate_manifest_patch",
            side_effect=expire_after_preflight,
        ), mock.patch.object(
            WorkspaceIO,
            "_commit_prepared",
            side_effect=AssertionError("expired publication started"),
        ) as publication, case.assertRaises(SourceServiceError) as denied:
            service.apply_patch(
                context,
                {
                    "projectId": project_id,
                    "mode": "patch",
                    "path": "src/main.hocus",
                    "expectedDigest": _raw_digest(source),
                    "unifiedDiff": patch,
                },
            )
        with case.subTest(expiry_before_commit_denies_publication=True):
            case.assertEqual(denied.exception.code, "HOCUS823")
            publication.assert_not_called()


def _exercise_terminal_write_lifecycle(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    project_id: str,
    root: Path,
) -> None:
    from hocuspocus.hocusscript.workspace_io import WorkspaceIO
    from scripts.smoke_hocusscript_h6_support import unified_replacement

    context = workspace_context(authority, "h6-terminal-writes")
    authority.host_grant(
        project_id,
        principal_id=context.principal_id,
        session_id=context.session_id,
        grants=(SOURCE_READ, SOURCE_WRITE),
    )
    destination = root / "src/preflight-denied.hocus"
    with mock.patch.object(
        service,
        "prepare_tool_response",
        side_effect=SourceServiceError("HOCUS825", "Prepared response rejected."),
    ), mock.patch.object(
        WorkspaceIO, "_commit_prepared",
    ) as commit, case.assertRaises(SourceServiceError) as rejected:
        service.apply_patch(
            context,
            {
                "projectId": project_id,
                "mode": "create",
                "path": "src/preflight-denied.hocus",
                "content": (
                    'hocus 0.2;\ngraph Preflight { target "/obj"; category Sop; }\n'
                ),
            },
        )
    with case.subTest(response_preflight_precedes_mutation=True):
        case.assertEqual(rejected.exception.code, "HOCUS825")
        commit.assert_not_called()
        case.assertFalse(destination.exists())

    original_invalidate = authority.invalidate

    def fail_source_invalidation(candidate, reason="change"):
        if reason == "source_write":
            raise OSError("private-root-invalidation")
        return original_invalidate(candidate, reason)

    with mock.patch.object(
        authority, "invalidate", side_effect=fail_source_invalidation,
    ):
        housekeeping_receipt = service.apply_patch(
            context,
            {
                "projectId": project_id,
                "mode": "create",
                "path": "src/housekeeping-committed.hocus",
                "content": (
                    'hocus 0.2;\ngraph Housekeeping { target "/obj"; category Sop; }\n'
                ),
            },
        )
    with case.subTest(cache_housekeeping_cannot_mask_commit=True):
        case.assertEqual(
            housekeeping_receipt["path"], "src/housekeeping-committed.hocus",
        )
        case.assertTrue((root / "src/housekeeping-committed.hocus").is_file())
        with case.assertRaises(SourceServiceError):
            service.read(
                context,
                {"projectId": project_id, "paths": ["src/main.hocus"]},
            )
        case.assertNotIn(
            "private-root-invalidation",
            json.dumps(
                authority.audit_logger.recent(project_id=project_id),
                ensure_ascii=True,
            ),
        )
    authority.host_grant(
        project_id,
        principal_id=context.principal_id,
        session_id=context.session_id,
        grants=(SOURCE_READ, SOURCE_WRITE),
    )

    manifest = root / "hocus.project.toml"
    current = manifest.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in current else "\n"
    updated = current.replace(
        f"[project]{newline}",
        f'[project]{newline}name = "Native Refreshed"{newline}',
        1,
    )
    case.assertNotEqual(updated, current)
    patch = unified_replacement("hocus.project.toml", current, updated)
    if newline == "\r\n":
        patch = patch.replace("\r\n", "\n").replace("\n", "\r\n")
    with mock.patch.object(
        authority,
        "accept_current_manifest_identity",
        side_effect=OSError("private-root-housekeeping"),
    ):
        receipt = service.apply_patch(
            context,
            {
                "projectId": project_id,
                "mode": "patch",
                "path": "hocus.project.toml",
                "expectedDigest": _raw_digest(current),
                "unifiedDiff": patch,
            },
        )
    with case.subTest(manifest_housekeeping_cannot_mask_commit=True):
        case.assertEqual(manifest.read_bytes().decode("utf-8"), updated)
        case.assertEqual(receipt["rawDigest"], _raw_digest(updated))
        with case.assertRaises(SourceServiceError):
            service.read(
                context,
                {"projectId": project_id, "paths": ["src/main.hocus"]},
            )
        audit = json.dumps(
            authority.audit_logger.recent(project_id=project_id),
            ensure_ascii=True,
        )
        case.assertIn("project.manifest.refresh_failed", audit)
        case.assertNotIn("private-root-housekeeping", audit)


def exercise_h6_source_workflow_5(case) -> None:
    """Exercise MCP discovery, resources, limits, audit privacy, and revocation."""

    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        state = base / "state"
        project_root = base / "project"
        ungranted_root = base / "ungranted"
        write_project(project_root, "h6-source-surface")
        write_project(ungranted_root, "h6-source-hidden")
        for index in range(205):
            (project_root / f"src/item-{index:03d}.hocus").write_text(
                f'hocus 0.3;\ngraph Item{index} {{ target "/obj"; category Sop; }}\n',
                encoding="utf-8",
            )
        settings = ServerSettings(
            workspace_search_limit=2,
            workspace_read_batch_limit=1,
            workspace_enumeration_limit=300,
            workspace_rate_total_per_minute=3,
            workspace_rate_search_per_minute=2,
        )
        with isolated_workspace_state(state):
            authority = WorkspaceAuthority(settings, _LOGGER)
            try:
                project = authority.register_project(str(project_root))
                hidden = authority.register_project(str(ungranted_root))
                context = workspace_context(authority, "h6-source-workflow-5")
                authority.host_grant(
                    project.project_id,
                    principal_id=context.principal_id,
                    session_id=context.session_id,
                    grants=(SOURCE_READ,),
                )
                service = SourceWorkspaceService(authority)
                _exercise_discovery_and_resources(
                    case, service, context, project.project_id, hidden.project_id,
                )
                _exercise_limits_audit_and_revocation(
                    case,
                    authority,
                    service,
                    context,
                    project.project_id,
                    hidden.project_id,
                    project_root,
                )
            finally:
                authority.close()


def _exercise_discovery_and_resources(
    case,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
    hidden_project_id: str,
) -> None:
    definitions = _source_tool_definitions(_ToolOwner())
    case.assertEqual([item.name for item in definitions], _SOURCE_TOOLS)
    build_annotations = next(
        item.annotations for item in definitions
        if item.name == "source.project.build"
    )
    case.assertFalse(build_annotations["readOnlyHint"])
    case.assertTrue(build_annotations["destructiveHint"])
    case.assertFalse(build_annotations["idempotentHint"])
    case.assertEqual(
        build_annotations["sourceGrantByAction"]["lock_update"],
        "generated_lock",
    )
    case.assertEqual(
        {item["uriTemplate"] for item in _source_resource_templates()},
        {
            "hocus-source://{projectId}",
            "hocus-source://{projectId}/{relativePath}",
        },
    )
    described = service.describe(context)
    case.assertEqual([item["projectId"] for item in described["projects"]], [project_id])
    case.assertNotIn(hidden_project_id, json.dumps(described))
    page = service.list_resources(context, None)
    case.assertEqual(len(page["resources"]), 200)
    case.assertIn("nextCursor", page)
    second = service.list_resources(context, page["nextCursor"])
    case.assertTrue(second["resources"])
    serialized = json.dumps([page, second], ensure_ascii=True)
    case.assertNotIn("approvedRoot", serialized)
    case.assertNotIn("rootIdentityDigest", serialized)
    sessionless = RequestContext(principal_id=context.principal_id)
    case.assertEqual(service.list_resources(sessionless, None), {"resources": []})
    templates = _source_resource_templates()
    case.assertEqual(len(templates), 2)


def _exercise_limits_audit_and_revocation(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    context: RequestContext,
    project_id: str,
    hidden_project_id: str,
    project_root: Path,
) -> None:
    with case.assertRaises(SourceServiceError) as limited:
        service.search(
            context,
            {"projectId": project_id, "glob": "*", "limit": 3},
        )
    case.assertEqual(limited.exception.code, "HOCUS821")
    with case.assertRaises(SourceServiceError):
        service.read(
            context,
            {
                "projectId": project_id,
                "paths": ["src/main.hocus", "hocus.project.toml"],
            },
        )
    harness = _SourceHarness()
    harness.bind_source_workspace(authority)
    secret = "audit-secret-query"
    response = harness.source_file_search(
        {"projectId": project_id, "query": secret, "limit": 1},
        context,
    )
    payload = response["structuredContent"]
    _assert_no_native_path(case, payload, project_root)
    recent = authority.audit_logger.recent(project_id=project_id)
    audit_json = json.dumps(recent, ensure_ascii=True)
    case.assertNotIn(secret, audit_json)
    case.assertNotIn(str(project_root), audit_json)
    case.assertIn("argumentDigest", audit_json)
    cursor_page = service.search(
        context,
        {"projectId": project_id, "glob": "*", "limit": 1},
    )
    cursor = cursor_page["nextCursor"]
    claims = _decode_opaque_cursor(cursor)
    case.assertNotIn("glob", claims)
    case.assertNotIn("query", claims)
    case.assertIn("selectionDigest", claims)
    _exercise_rate_limits(
        case, authority, service, context.principal_id, project_id, hidden_project_id,
    )
    authority.host_revoke(
        project_id,
        principal_id=context.principal_id,
        session_id=context.session_id,
    )
    with case.assertRaises(SourceServiceError) as revoked:
        service.read(
            context,
            {"projectId": project_id, "paths": ["src/main.hocus"]},
        )
    case.assertIn(revoked.exception.code, {"HOCUS822", "HOCUS823", "HOCUS824"})


def _exercise_rate_limits(
    case,
    authority: WorkspaceAuthority,
    service: SourceWorkspaceService,
    principal_id: str,
    project_id: str,
    other_project_id: str,
) -> None:
    clock = {"now": 100.0}

    def monotonic() -> float:
        return clock["now"]

    def grant(candidate) -> None:
        authority.host_grant(
            project_id, principal_id=candidate.principal_id,
            session_id=candidate.session_id, grants=(SOURCE_READ,),
        )

    with mock.patch(
        "hocuspocus.core.workspace_rate.time.monotonic", side_effect=monotonic,
    ):
        rate_context = workspace_context(authority, principal_id)
        grant(rate_context)
        service.rate(rate_context, "file.search", project_id)
        service.rate(rate_context, "file.search", project_id)
        with case.assertRaises(SourceServiceError) as category_limited:
            service.rate(rate_context, "file.search", project_id)
        case.assertEqual(category_limited.exception.code, "HOCUS825")

        service.rate(rate_context, "file.read", project_id)
        with case.assertRaises(SourceServiceError) as total_limited:
            service.rate(rate_context, "file.read", project_id)
        case.assertEqual(total_limited.exception.code, "HOCUS825")

        for _ in range(3):
            service.rate(rate_context, "file.read", other_project_id)
        resource_context = workspace_context(authority, principal_id)
        for _ in range(3):
            service.rate(resource_context, "file.read", None)
        with case.assertRaises(SourceServiceError):
            service.rate(resource_context, "file.read", None)
        for _ in range(3):
            service.rate(resource_context, "file.read", "__resource_scope__")

        invalid_context = workspace_context(authority, principal_id)
        bucket_count = len(authority.rate._windows)
        for index in range(3):
            service.rate(
                invalid_context, "file.read", f"hproj_invalid_selector_{index}",
            )
        with case.assertRaises(SourceServiceError):
            service.rate(
                invalid_context, "file.read", "hproj_invalid_selector_limited",
            )
        case.assertLessEqual(len(authority.rate._windows), bucket_count + 1)

        isolated_session = workspace_context(authority, principal_id)
        grant(isolated_session)
        service.rate(isolated_session, "file.read", project_id)

        sliding_context = workspace_context(authority, principal_id)
        grant(sliding_context)
        for _ in range(3):
            service.rate(sliding_context, "file.read", project_id)
        clock["now"] = 159.999
        with case.assertRaises(SourceServiceError):
            service.rate(sliding_context, "file.read", project_id)
        clock["now"] = 160.0
        service.rate(sliding_context, "file.read", project_id)

        limiter = WorkspaceRateLimiter()
        limiter.require_scoped(
            "principal", "session", "old-project",
            total_limit=1, window_seconds=60.0,
        )
        case.assertEqual(len(limiter._windows), 1)
        clock["now"] = 220.0
        limiter.require_scoped(
            "principal", "session", "new-project",
            total_limit=1, window_seconds=60.0,
        )
        case.assertEqual(len(limiter._windows), 1)
    _exercise_rate_lock_order(case)


def _exercise_rate_lock_order(case) -> None:
    waiting = threading.Event()
    release = threading.Event()
    sampled = threading.Event()
    limiter = WorkspaceRateLimiter()
    limiter._lock = _GateLock(waiting, release)

    def monotonic() -> float:
        sampled.set()
        return 100.0

    with mock.patch(
        "hocuspocus.core.workspace_rate.time.monotonic", side_effect=monotonic,
    ), ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            limiter.require_scoped, "principal", "session", "project",
            total_limit=1, window_seconds=60.0,
        )
        try:
            case.assertTrue(waiting.wait(2))
            case.assertFalse(sampled.is_set())
        finally:
            release.set()
        future.result(timeout=2)
    case.assertTrue(sampled.is_set())


def _decode_opaque_cursor(value: str) -> dict[str, Any]:
    encoded = value.split(".", 1)[0]
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    return json.loads(raw)


def _raw_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _assert_no_native_path(case, value: Any, root: Path) -> None:
    rendered = json.dumps(value, ensure_ascii=True, default=str)
    case.assertNotIn(str(root), rendered)
    case.assertNotIn(str(root).replace("\\", "/"), rendered)


__all__ = [
    "exercise_h6_source_workflow_4",
    "exercise_h6_source_workflow_5",
]
