"""Run the installed H6 source-workspace workflow in Houdini 22.0.368.

This script is launched from the repository, but every ``hocuspocus`` import
must resolve from the clean installed Houdini package. It uses a disposable
scene and temporary local NTFS projects, performs no cooks, and cleans up all
live and filesystem state before exit.

Usage:
    "C:\\Program Files\\Side Effects Software\\Houdini 22.0.368\\bin\\hython.exe" ^
        scripts\\smoke_hocusscript_h6.py
"""

from __future__ import annotations

import json
import http.client
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import hou  # type: ignore

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.server import (
    HocusPocusRuntime,
    RuntimeHTTPServer,
    RuntimeRequestHandler,
)
from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.workspace_authority import WorkspaceAuthority
from hocuspocus.core.workspace_grants import (
    GENERATED_LOCK,
    SOURCE_READ,
    SOURCE_WRITE,
    principal_from_bearer,
)
from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.source_resources import SourceResourceOperationsMixin
from hocuspocus.live.ops.source_workspace import SourceWorkspaceOperationsMixin
from smoke_hocusscript_h5 import (
    COOK_OBSERVATIONS,
    _H5SmokeOperations,
    _apply_arguments,
    _assert_installed_alignment,
    _live_signature,
    _semantic_projection,
)
from smoke_hocusscript_h6_support import (
    CONTROL_SOURCE,
    SOURCE_TOOL_NAMES,
    TARGET_PATH,
    assert_no_physical_roots,
    digest_bytes,
    expect_failure,
    git_status,
    initialize_git_repository,
    invoke_source_tool,
    unified_replacement,
    validate_acceptance_result,
    verify_installed_modules,
    write_control_project,
    write_export_project,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "h6-installed-acceptance-bearer"
HTTP_HARD_PAYLOAD_BYTES = 8 * 1024 * 1024


class _H6SmokeOperations(
    SourceWorkspaceOperationsMixin,
    SourceResourceOperationsMixin,
    _H5SmokeOperations,
):
    """H5 live document pipeline plus the exact H6 source surface."""


def _progress(stage: str) -> None:
    print(f"H6_STAGE {stage}", file=sys.stderr, flush=True)


def _create_target(operations: _H6SmokeOperations) -> None:
    if hou.node(TARGET_PATH) is not None:
        raise RuntimeError(f"Refusing to reuse H6 smoke target {TARGET_PATH}.")
    parent = hou.node("/obj")
    if parent is None:
        raise RuntimeError("The /obj network is unavailable.")
    parent.createNode(
        "geo",
        node_name=TARGET_PATH.rsplit("/", 1)[-1],
        run_init_scripts=False,
        load_contents=False,
    )
    operations._document_stamp_live_node_uid(
        TARGET_PATH,
        "node:h6-installed-root",
    )
    operations._monitor.mark_dirty(
        "h6.target.created",
        scope_path=TARGET_PATH,
    )


def _registered_source_tools(
    runtime: HocusPocusRuntime,
    context: RequestContext,
    forbidden_roots: tuple[Path, ...],
) -> HocusPocusRuntime:
    discovered, response_session = _http_runtime_result(
        runtime, "tools/list", {}, session_id=context.session_id,
    )
    if response_session is not None:
        raise RuntimeError("H6 non-initialize response unexpectedly replaced its session.")
    tools = discovered.get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("H6 production tool discovery returned no tool list.")
    source_names = tuple(
        item.get("name")
        for item in tools
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].startswith("source.")
    )
    if source_names != SOURCE_TOOL_NAMES:
        raise RuntimeError(f"H6 registered source surface changed: {source_names!r}")
    resources, _ = _http_runtime_result(
        runtime, "resources/list", {}, session_id=context.session_id,
    )
    source_resources = [
        item for item in resources.get("resources", [])
        if isinstance(item, dict)
        and str(item.get("uri", "")).startswith("hocus-source://")
    ]
    if len(source_resources) < 2:
        raise RuntimeError("H6 HTTP resource discovery omitted approved projects.")
    described, _ = _http_runtime_result(
        runtime,
        "tools/call",
        {"name": "source.project.describe", "arguments": {}},
        session_id=context.session_id,
    )
    assert_no_physical_roots(described, forbidden_roots)
    return runtime


def _http_initialize_session(runtime: HocusPocusRuntime) -> str:
    initialized, session_id = _http_runtime_result(
        runtime,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "h6-installed-smoke", "version": "1.0"},
        },
        session_id=None,
    )
    if not isinstance(initialized.get("serverInfo"), dict):
        raise RuntimeError("H6 HTTP initialize dispatch failed.")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("H6 HTTP initialize omitted Mcp-Session-Id.")
    session = runtime.workspace_authority.grants.session(session_id, touch=False)
    if session is None or session.principal_id != runtime.host_principal_id:
        raise RuntimeError("H6 HTTP session was not bound to the bearer principal.")
    return session_id


def _http_transport_limit_probe(runtime: HocusPocusRuntime) -> None:
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeRequestHandler)
    server.runtime = runtime  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(
        str(server.server_address[0]), int(server.server_address[1]), timeout=10.0,
    )
    try:
        connection.putrequest("POST", runtime.settings.normalized_mcp_route)
        connection.putheader("Authorization", f"Bearer {TOKEN}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("MCP-Protocol-Version", "2025-06-18")
        connection.putheader("Content-Length", str(HTTP_HARD_PAYLOAD_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        error = payload.get("error") if isinstance(payload, dict) else None
        details = error.get("data") if isinstance(error, dict) else None
        if (
            response.status != 413
            or not isinstance(details, dict)
            or details.get("hocusCode") != "HOCUS830"
        ):
            raise RuntimeError("H6 HTTP transport accepted an oversized request.")
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _http_runtime_result(
    runtime: HocusPocusRuntime,
    method: str,
    params: dict[str, Any],
    *,
    session_id: str | None,
) -> tuple[dict[str, Any], str | None]:
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeRequestHandler)
    server.runtime = runtime  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(
        str(server.server_address[0]), int(server.server_address[1]), timeout=30.0,
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    request = {
        "jsonrpc": "2.0",
        "id": f"h6-http-{method}",
        "method": method,
        "params": params,
    }
    try:
        connection.request(
            "POST",
            runtime.settings.normalized_mcp_route,
            body=json.dumps(request, ensure_ascii=True).encode("utf-8"),
            headers=headers,
        )
        http_response = connection.getresponse()
        response_session = http_response.getheader("Mcp-Session-Id")
        raw = http_response.read()
        if http_response.status != 200:
            raise RuntimeError(
                f"H6 HTTP dispatch failed with {http_response.status}: {raw!r}"
            )
        response = json.loads(raw.decode("utf-8"))
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
    if isinstance(response, dict) and isinstance(response.get("error"), dict):
        error = response["error"]
        raise JsonRpcError(
            int(error.get("code", -32603)),
            str(error.get("message", "H6 production dispatch failed.")),
            error.get("data"),
        )
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"H6 production dispatch returned no result: {response!r}")
    return result, response_session


def _project_common(description: dict[str, Any]) -> dict[str, str]:
    project_id = description.get("projectId")
    projection = description.get("authorityProjectionDigest")
    if not isinstance(project_id, str) or not isinstance(projection, str):
        raise RuntimeError("H6 project description omitted portable authority pins.")
    return {
        "projectId": project_id,
        "authorityProjectionDigest": projection,
    }


def _plan_apply_verify(
    operations: _H6SmokeOperations,
    bundle: dict[str, Any],
    context: RequestContext,
    idempotency_key: str,
) -> dict[str, Any]:
    preview = operations.document_preview_bundle(
        {"bundle": bundle},
        context,
    )["structuredContent"]
    if (
        not preview.get("valid")
        or not preview.get("readyForPlan")
        or not isinstance(preview.get("preview"), dict)
    ):
        raise RuntimeError(f"H6 bundle preview failed: {preview!r}")
    plan = operations.document_plan_bundle(
        {"bundle": bundle},
        context,
    )["structuredContent"]
    if not plan.get("readyForApply"):
        raise RuntimeError(f"H6 bundle plan failed: {plan!r}")
    applied = operations.document_apply_plan(
        _apply_arguments(plan, idempotency_key),
        context,
    )["structuredContent"]
    if (
        applied.get("applied") is not True
        or applied.get("verified") is not True
        or applied.get("state") != "committed"
    ):
        raise RuntimeError(f"H6 bundle apply verification failed: {applied!r}")
    verification = applied.get("verification")
    if (
        not isinstance(verification, dict)
        or not operations._document_diff_is_clean(verification)
    ):
        raise RuntimeError(
            f"H6 applied document did not verify cleanly: {verification!r}"
        )
    return {
        "preview": preview,
        "plan": plan,
        "applied": applied,
    }


def _exercise_source_project(
    registry: Any,
    context: RequestContext,
    description: dict[str, Any],
    root: Path,
    forbidden_roots: tuple[Path, ...],
) -> tuple[dict[str, Any], str]:
    common = _project_common(description)
    searched = invoke_source_tool(
        registry,
        "source.file.search",
        {
            **common,
            "glob": "**/*.hocus",
            "query": "studio.h6",
            "caseSensitive": True,
            "limit": 20,
        },
        context,
        forbidden_roots=forbidden_roots,
    )
    if searched.get("matchCount") != 1:
        raise RuntimeError(f"H6 literal source search was not exact: {searched!r}")
    read = invoke_source_tool(
        registry,
        "source.file.read",
        {**common, "paths": ["src/main.hocus"]},
        context,
        forbidden_roots=forbidden_roots,
    )
    files = read.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise RuntimeError("H6 source read did not return the selected file.")
    source = files[0].get("content")
    raw_digest = files[0].get("rawDigest")
    if source != CONTROL_SOURCE or not isinstance(raw_digest, str):
        raise RuntimeError("H6 source read changed authored bytes or omitted its digest.")
    updated = source.replace(
        'ownership "studio.h6";',
        'ownership "studio.h6.accepted";',
    )
    patched = invoke_source_tool(
        registry,
        "source.file.apply_patch",
        {
            **common,
            "path": "src/main.hocus",
            "mode": "patch",
            "expectedDigest": raw_digest,
            "unifiedDiff": unified_replacement(
                "src/main.hocus",
                source,
                updated,
            ),
        },
        context,
        forbidden_roots=forbidden_roots,
    )
    if (root / "src/main.hocus").read_bytes() != updated.encode("utf-8"):
        raise RuntimeError("H6 patch is not visible to native editors.")
    checked = invoke_source_tool(
        registry,
        "source.project.build",
        {**common, "action": "check", "entryPath": "src/main.hocus"},
        context,
        forbidden_roots=forbidden_roots,
    )
    if checked.get("valid") is not True:
        raise RuntimeError(f"H6 project check failed: {checked!r}")
    compiled = invoke_source_tool(
        registry,
        "source.project.build",
        {**common, "action": "compile", "entryPath": "src/main.hocus"},
        context,
        forbidden_roots=forbidden_roots,
    )
    bundle = compiled.get("bundle")
    if compiled.get("valid") is not True or not isinstance(bundle, dict):
        raise RuntimeError(f"H6 project compile failed: {compiled!r}")
    navigated = invoke_source_tool(
        registry,
        "source.project.navigate",
        {
            **common,
            "operation": "completion",
            "path": "src/main.hocus",
            "offset": updated.find("graph") + 2,
            "source": updated,
            "limit": 20,
        },
        context,
        forbidden_roots=forbidden_roots,
    )
    if navigated.get("projectId") != common["projectId"]:
        raise RuntimeError("H6 native navigation lost portable project identity.")
    resulting_digest = patched.get("rawDigest") or patched.get("digest")
    if not isinstance(resulting_digest, str):
        raise RuntimeError("H6 patch publication omitted its resulting digest.")
    return bundle, resulting_digest


def _write_recompile_export(
    operations: _H6SmokeOperations,
    registry: Any,
    context: RequestContext,
    description: dict[str, Any],
    export_root: Path,
    forbidden_roots: tuple[Path, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    common = _project_common(description)
    handoff = operations.document_export_source(
        {"root_path": TARGET_PATH, "graph_name": "Main"},
        context,
    )["structuredContent"]
    handoff_source = handoff.get("source")
    provenance = handoff.get("provenance")
    if (
        handoff.get("valid") is not True
        or handoff.get("languageVersion") != "0.1"
        or not isinstance(handoff.get("handoffToken"), str)
        or not isinstance(handoff_source, str)
        or not isinstance(provenance, dict)
    ):
        raise RuntimeError(f"H6 document export handoff failed: {handoff!r}")
    written = invoke_source_tool(
        registry,
        "source.file.write_export",
        {
            **common,
            "destination": "src/reconciled.hocus",
            "handoff": handoff,
        },
        context,
        forbidden_roots=forbidden_roots,
    )
    exported_path = export_root / "src/reconciled.hocus"
    exported_bytes = exported_path.read_bytes()
    handoff_bytes = handoff_source.encode("utf-8")
    actual_digest = digest_bytes(exported_bytes)
    if exported_bytes != handoff_bytes:
        raise RuntimeError("H6 export publication changed authenticated handoff bytes.")
    if (
        written.get("rawDigest") != actual_digest
        or written.get("sourceDigest") != actual_digest
        or provenance.get("sourceDigest") != actual_digest
    ):
        raise RuntimeError("H6 export publication receipt did not prove its exact digest.")
    exported = exported_bytes.decode("utf-8")
    if (
        not exported.startswith("hocus 0.1;")
        or "\nimport " in exported
        or "\nif " in exported
        or "\nfor " in exported
    ):
        raise RuntimeError("H6 export implied reconstructed 0.3 authored structure.")
    read = invoke_source_tool(
        registry,
        "source.file.read",
        {**common, "paths": ["src/reconciled.hocus"]},
        context,
        forbidden_roots=forbidden_roots,
    )
    read_file = read["files"][0]
    raw_digest = read_file["rawDigest"]
    if (
        read_file.get("content") != handoff_source
        or raw_digest != actual_digest
    ):
        raise RuntimeError("H6 source read did not preserve the export handoff.")
    reconciled = exported.replace("  mode merge;", "  mode reconcile;")
    if reconciled == exported:
        raise RuntimeError("H6 flat export did not contain its explicit merge mode.")
    invoke_source_tool(
        registry,
        "source.file.apply_patch",
        {
            **common,
            "path": "src/reconciled.hocus",
            "mode": "patch",
            "expectedDigest": raw_digest,
            "unifiedDiff": unified_replacement(
                "src/reconciled.hocus",
                exported,
                reconciled,
            ),
        },
        context,
        forbidden_roots=forbidden_roots,
    )
    if exported_path.read_bytes() != reconciled.encode("utf-8"):
        raise RuntimeError("H6 export publication is not visible as exact native bytes.")
    checked = invoke_source_tool(
        registry,
        "source.project.build",
        {**common, "action": "check", "entryPath": "src/reconciled.hocus"},
        context,
        forbidden_roots=forbidden_roots,
    )
    compiled = invoke_source_tool(
        registry,
        "source.project.build",
        {**common, "action": "compile", "entryPath": "src/reconciled.hocus"},
        context,
        forbidden_roots=forbidden_roots,
    )
    bundle = compiled.get("bundle")
    if checked.get("valid") is not True or not isinstance(bundle, dict):
        raise RuntimeError("H6 exported source did not recompile through its workspace.")
    return bundle, {
        "receipt": written,
        "exactBytes": True,
        "digestVerified": True,
    }


def _assert_source_resource(
    runtime: HocusPocusRuntime,
    context: RequestContext,
    project_id: str,
    roots: tuple[Path, ...],
) -> None:
    uri = f"hocus-source://{project_id}/src/main.hocus"
    response, _ = _http_runtime_result(
        runtime,
        "resources/read",
        {"uri": uri},
        session_id=context.session_id,
    )
    if not isinstance(response, dict):
        raise RuntimeError("H6 dynamic source resource was not resolved.")
    assert_no_physical_roots(response, roots)
    content = response.get("contents")
    if (
        not isinstance(content, list)
        or content[0].get("mimeType") != "text/x-hocusscript"
        or 'ownership "studio.h6.accepted";' not in content[0].get("text", "")
    ):
        raise RuntimeError("H6 dynamic source resource returned invalid content.")


def _revocation_denial(
    authority: WorkspaceAuthority,
    runtime: HocusPocusRuntime,
    context: RequestContext,
    common: dict[str, str],
    relative_path: str,
) -> dict[str, Any]:
    if not authority.host_revoke(
        common["projectId"],
        principal_id=context.principal_id,
        session_id=context.session_id,
        persistent=False,
    ):
        raise RuntimeError("H6 source grant revocation did not change authority.")
    failure = expect_failure(
        lambda: invoke_source_tool(
            runtime,
            "source.file.read",
            {**common, "paths": [relative_path]},
            context,
        )
    )
    if not isinstance(failure, JsonRpcError):
        raise RuntimeError(f"H6 revoked source call failed unexpectedly: {failure}")
    code = (failure.data or {}).get("hocusCode")
    if code not in {"HOCUS822", "HOCUS823", "HOCUS824"}:
        raise RuntimeError(f"H6 revoked source denial was not typed: {failure!r}")
    uri = f"hocus-source://{common['projectId']}/{relative_path}"
    resource_failure = expect_failure(
        lambda: _http_runtime_result(
            runtime,
            "resources/read",
            {"uri": uri},
            session_id=context.session_id,
        )
    )
    if not isinstance(resource_failure, JsonRpcError):
        raise RuntimeError("H6 revoked source resource was not denied.")
    listed, _ = _http_runtime_result(
        runtime, "resources/list", {}, session_id=context.session_id,
    )
    if common["projectId"] in json.dumps(listed, ensure_ascii=True):
        raise RuntimeError("H6 revoked project remained in resource enumeration.")
    return {
        "code": str(code),
        "toolDenied": True,
        "resourceDenied": True,
        "listFiltered": True,
    }


def _run_installed_h6(temporary_root: Path) -> dict[str, Any]:
    _progress("alignment")
    base_alignment = _assert_installed_alignment()
    installed_root = Path(base_alignment["installedRoot"]).resolve()
    h6_modules = verify_installed_modules(
        REPOSITORY_ROOT,
        installed_root,
    )
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError("H6 installed acceptance requires Houdini 22.0.368.")
    if Path(hou.hipFile.path()).name.casefold() != "untitled.hip":
        raise RuntimeError("H6 installed acceptance requires a disposable scene.")

    _progress("catalog-projects")
    catalog = LiveHoudiniCatalogProvider(hou).get_catalog()
    git_root = temporary_root / "git-workspace"
    control_root = git_root / "control"
    export_root = git_root / "export"
    write_control_project(control_root, catalog.to_json())
    write_export_project(export_root, catalog.to_json(), catalog.fingerprint)
    baseline_commit = initialize_git_repository(git_root)

    state_root = temporary_root / "houdini-state"
    state_root.mkdir()
    previous_hou_pref = hou.getenv("HOUDINI_USER_PREF_DIR")
    previous_os_pref = os.environ.get("HOUDINI_USER_PREF_DIR")
    hou.putenv("HOUDINI_USER_PREF_DIR", str(state_root))
    os.environ["HOUDINI_USER_PREF_DIR"] = str(state_root)
    runtime: HocusPocusRuntime | None = None
    try:
        settings = ServerSettings(
            token_mode="static",
            token=TOKEN,
            approved_roots=[str(temporary_root)],
        )
        runtime = HocusPocusRuntime(settings, logging.getLogger("hocus.h6.smoke"))
        authority = runtime.workspace_authority
        _http_transport_limit_probe(runtime)
        principal = principal_from_bearer(
            f"Bearer {TOKEN}",
            token_mode="static",
        )
        session_id = _http_initialize_session(runtime)
        context = RequestContext(
            caller_id=principal,
            principal_id=principal,
            session_id=session_id,
            permissions=("observe", "edit_scene", "write_files"),
            timeout_seconds=300.0,
        )
        control = authority.register_project(str(control_root))
        export = authority.register_project(str(export_root))
        for project in (control, export):
            authority.host_grant(
                project.project_id,
                principal_id=principal,
                session_id=session_id,
                grants=(SOURCE_READ, SOURCE_WRITE, GENERATED_LOCK),
            )

        operations = _H6SmokeOperations(catalog, temporary_root)
        operations.bind_source_workspace(authority)
        operations._source_workspace_service = (
            runtime.operations._get_source_workspace_service()
        )
        _create_target(operations)
        forbidden_roots = (control_root, export_root)
        registry = _registered_source_tools(runtime, context, forbidden_roots)

        _progress("describe-discover")
        described = invoke_source_tool(
            registry,
            "source.project.describe",
            {},
            context,
            forbidden_roots=forbidden_roots,
        )
        descriptions = described.get("projects")
        if not isinstance(descriptions, list) or len(descriptions) != 2:
            raise RuntimeError("H6 source discovery did not return both approved projects.")
        descriptions_by_id = {
            item["projectId"]: item
            for item in descriptions
            if isinstance(item, dict) and isinstance(item.get("projectId"), str)
        }
        control_description = descriptions_by_id[control.project_id]
        export_description = descriptions_by_id[export.project_id]

        _progress("read-patch-check-compile")
        bundle, patched_digest = _exercise_source_project(
            registry,
            context,
            control_description,
            control_root,
            forbidden_roots,
        )
        _assert_source_resource(
            runtime,
            context,
            control.project_id,
            forbidden_roots,
        )

        _progress("preview-plan-apply-verify")
        first = _plan_apply_verify(
            operations,
            bundle,
            context,
            "h6-installed-initial",
        )
        before_export = _semantic_projection(first["applied"]["document"])
        _live_signature(TARGET_PATH)

        _progress("export-write-recompile-reconcile")
        export_bundle, write_receipt = _write_recompile_export(
            operations,
            registry,
            context,
            export_description,
            export_root,
            forbidden_roots,
        )
        second = _plan_apply_verify(
            operations,
            export_bundle,
            context,
            "h6-installed-export-reconcile",
        )
        after_export = _semantic_projection(second["applied"]["document"])
        if after_export != before_export:
            raise RuntimeError("H6 export/recompile/reconcile changed graph semantics.")
        _live_signature(TARGET_PATH)

        _progress("git-audit-revoke")
        status = git_status(git_root)
        expected_status = {
            " M control/src/main.hocus",
            "?? export/src/reconciled.hocus",
        }
        if set(status) != expected_status or len(status) != len(expected_status):
            raise RuntimeError(f"H6 native writes are not Git-visible: {status!r}")
        audit = authority.audit_logger.recent(limit=1000)
        assert_no_physical_roots(audit, forbidden_roots)
        control_common = _project_common(control_description)
        export_common = _project_common(export_description)
        control_denial = _revocation_denial(
            authority,
            runtime,
            context,
            control_common,
            "src/main.hocus",
        )
        export_denial = _revocation_denial(
            authority,
            runtime,
            context,
            export_common,
            "src/reconciled.hocus",
        )
        result = {
            "status": "passed",
            "alignment": {
                "houdini": base_alignment["houdini"],
                "installedRoot": base_alignment["installedRoot"],
                "h5ModuleCount": len(base_alignment["modules"]),
                "h6Modules": h6_modules,
            },
            "sourceTools": list(SOURCE_TOOL_NAMES),
            "project": {
                "controlProjectId": control.project_id,
                "exportProjectId": export.project_id,
                "patchedDigest": patched_digest,
                "bundleVersion": bundle["bundleVersion"],
                "resourceRead": True,
                "nativeEditorVisible": True,
            },
            "live": {
                "previewed": bool(first["preview"]["valid"]),
                "planned": bool(first["plan"]["readyForApply"]),
                "applied": bool(first["applied"]["applied"]),
                "verified": bool(first["applied"]["verified"]),
                "target": TARGET_PATH,
            },
            "export": {
                "written": bool(write_receipt["receipt"].get("valid")),
                "recompiled": isinstance(export_bundle, dict),
                "reconciled": bool(second["applied"]["verified"]),
                "semanticPreserved": after_export == before_export,
                "exactBytes": bool(write_receipt["exactBytes"]),
                "digestVerified": bool(write_receipt["digestVerified"]),
                "normalizedLanguageVersion": "0.1",
                "reconstructedAuthoredStructure": False,
            },
            "git": {
                "baselineCommit": baseline_commit,
                "status": list(status),
                "nativeBytesVisible": True,
            },
            "revocation": {
                "denied": True,
                "controlCode": control_denial["code"],
                "exportCode": export_denial["code"],
                "resourceDenied": bool(
                    control_denial["resourceDenied"]
                    and export_denial["resourceDenied"]
                ),
                "listFiltered": bool(
                    control_denial["listFiltered"]
                    and export_denial["listFiltered"]
                ),
            },
            "cookExecuted": COOK_OBSERVATIONS["cookCount"] != 0,
        }
        validate_acceptance_result(result)
        return result
    finally:
        if runtime is not None:
            runtime.stop()
        if previous_hou_pref:
            hou.putenv("HOUDINI_USER_PREF_DIR", previous_hou_pref)
        else:
            hou.putenv("HOUDINI_USER_PREF_DIR", "")
        if previous_os_pref is None:
            os.environ.pop("HOUDINI_USER_PREF_DIR", None)
        else:
            os.environ["HOUDINI_USER_PREF_DIR"] = previous_os_pref


def main() -> int:
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            "H6 installed acceptance requires Houdini 22.0.368, got "
            f"{hou.applicationVersionString()}."
        )
    logging.basicConfig(level=logging.INFO)
    COOK_OBSERVATIONS.update({"nodeChecks": 0, "cookCount": 0})
    temporary = tempfile.TemporaryDirectory(prefix="hocuspocus-h6-")
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        result = _run_installed_h6(Path(temporary.name).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        try:
            hou.hipFile.clear(suppress_save_prompt=True)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
