"""Exact public-response boundary coverage for H6 source mutations."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.workspace_authority import WorkspaceAuthority
from hocuspocus.core.workspace_grants import (
    GENERATED_LOCK,
    SOURCE_READ,
    SOURCE_WRITE,
)
from hocuspocus.hocusscript.catalog import decode_catalog_snapshot
from hocuspocus.hocusscript.project_services import SourceWorkspaceService
from hocuspocus.hocusscript.workspace_io import WorkspaceIO
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.source_workspace import SourceWorkspaceOperationsMixin

from scripts.smoke_hocusscript_h6_support import write_export_project
from tests.hocusscript_h6_authority_helpers import (
    context as workspace_context,
    isolated_workspace_state,
)
from tests.test_hocusscript_project_scenarios import CATALOG, _native_project

_LOGGER = logging.getLogger("hocuspocus.tests.h6-response")


class _ProductionSourceHarness(SourceWorkspaceOperationsMixin, OperationBaseMixin):
    pass


def exercise_exact_mutation_response_preflight(case) -> None:
    """Prove wrapped-result limits reject before each filesystem commit."""

    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        state = base / "state"
        module_root = base / "module"
        export_root = base / "export"
        _native_project(module_root)
        catalog = decode_catalog_snapshot(CATALOG.read_bytes())
        write_export_project(
            export_root, catalog.to_json(), catalog.fingerprint,
        )
        with isolated_workspace_state(state):
            authority = WorkspaceAuthority(ServerSettings(), _LOGGER)
            try:
                context = workspace_context(authority, "h6-response-preflight")
                service = SourceWorkspaceService(authority)
                module_id = _register(
                    authority,
                    context,
                    module_root,
                    (SOURCE_READ, SOURCE_WRITE, GENERATED_LOCK),
                )
                export_id = _register(
                    authority,
                    context,
                    export_root,
                    (SOURCE_READ, SOURCE_WRITE),
                )
                harness = _ProductionSourceHarness()
                harness.bind_source_workspace(authority)
                harness._source_workspace_service = service
                lanes = _mutation_lanes(
                    service,
                    context,
                    module_id,
                    module_root,
                    export_id,
                    export_root,
                    catalog.fingerprint,
                    harness,
                )
                for name, invoke, request, code, unchanged in lanes:
                    _exercise_lane(
                        case, authority, context, name, invoke, request, code,
                        unchanged,
                    )
            finally:
                authority.close()


def _register(
    authority: WorkspaceAuthority,
    context: RequestContext,
    root: Path,
    grants: tuple[str, ...],
) -> str:
    project = authority.register_project(str(root))
    authority.host_grant(
        project.project_id,
        principal_id=context.principal_id,
        session_id=context.session_id,
        grants=grants,
    )
    return project.project_id


def _mutation_lanes(
    service: SourceWorkspaceService,
    context: RequestContext,
    module_id: str,
    module_root: Path,
    export_id: str,
    export_root: Path,
    catalog_fingerprint: str,
    harness: _ProductionSourceHarness,
) -> tuple[
    tuple[
        str,
        Callable[[Mapping[str, Any], RequestContext], dict[str, Any]],
        dict[str, Any],
        str,
        Callable[[], bool],
    ],
    ...,
]:
    module = service.describe(context, module_id)["projects"][0]
    exported_source = (
        'hocus 0.1;\ngraph ResponseBoundary {\n  target "/obj";\n'
        '  category Sop;\n  node out @id("out"): "null" {}\n'
        "  output = out;\n}\n"
    )
    provenance = {
        "format": "hocus-export-provenance-v0.1",
        "sourceDigest": _raw_digest(exported_source),
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
            "source": exported_source,
            "provenance": provenance,
        },
    )
    export_relative = "src/" + "response-" + "r" * 1000 + ".hocus"
    export_destination = export_root / export_relative
    patch_destination = module_root / "src/response-boundary.hocus"
    lock_path = module_root / "pins/hocus.lock.json"
    lock_before = lock_path.read_bytes()
    common = {
        "projectId": module_id,
        "authorityProjectionDigest": module["authorityProjectionDigest"],
    }
    return (
        (
            "apply",
            harness.source_file_apply_patch,
            {
                **common,
                "path": "src/response-boundary.hocus",
                "mode": "create",
                "content": (
                    'hocus 0.2;\ngraph ResponseBoundary { '
                    'target "/obj"; category Sop; }\n'
                ),
            },
            "HOCUS825",
            lambda: not patch_destination.exists(),
        ),
        (
            "export",
            harness.source_file_write_export,
            {
                "projectId": export_id,
                "destination": export_relative,
                "handoff": signed,
            },
            "HOCUS829",
            lambda: not export_destination.exists(),
        ),
        (
            "lock",
            harness.source_project_build,
            {
                **common,
                "action": "lock_update",
                "entryPaths": ["src/main.hocus"],
                "writeIntent": "update_generated_lock",
                "expectedLockState": "present",
                "expectedLockDigest": module["lockDigest"],
            },
            "HOCUS830",
            lambda: lock_path.read_bytes() == lock_before,
        ),
    )


def _exercise_lane(
    case,
    authority: WorkspaceAuthority,
    context: RequestContext,
    name: str,
    invoke: Callable[[Mapping[str, Any], RequestContext], dict[str, Any]],
    request: Mapping[str, Any],
    code: str,
    unchanged: Callable[[], bool],
) -> None:
    authority.settings.workspace_payload_bytes = 2 * 1024 * 1024
    with mock.patch.object(WorkspaceIO, "_commit_prepared") as commit:
        baseline = invoke(dict(request), context)
    commit.assert_called_once()
    inner_size = _encoded_size(baseline["structuredContent"])
    wrapped_size = _encoded_size(baseline)
    case.assertLess(inner_size, wrapped_size)
    authority.settings.workspace_payload_bytes = inner_size
    with mock.patch.object(
        WorkspaceIO, "_commit_prepared",
    ) as commit, case.assertRaises(JsonRpcError) as rejected:
        invoke(dict(request), context)
    with case.subTest(exact_wrapped_response_preflight=name):
        case.assertEqual(rejected.exception.data["hocusCode"], code)
        commit.assert_not_called()
        case.assertTrue(unchanged())
    authority.settings.workspace_payload_bytes = wrapped_size
    with mock.patch.object(WorkspaceIO, "_commit_prepared") as commit:
        accepted = invoke(dict(request), context)
    with case.subTest(exact_frozen_response_return=name):
        commit.assert_called_once()
        case.assertEqual(accepted, baseline)
        case.assertEqual(_canonical(accepted), _canonical(baseline))
        case.assertTrue(unchanged())


def _encoded_size(value: Any) -> int:
    return len(_canonical(value))


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _raw_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["exercise_exact_mutation_response_preflight"]
