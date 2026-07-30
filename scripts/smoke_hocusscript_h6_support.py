"""Project, tool, Git, and receipt helpers for the installed H6 harness."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SOURCE_TOOL_NAMES = (
    "source.project.describe",
    "source.file.search",
    "source.file.read",
    "source.file.apply_patch",
    "source.file.write_export",
    "source.project.build",
    "source.project.navigate",
)

H6_CRITICAL_MODULES = (
    "hocuspocus.core.paths",
    "hocuspocus.core.server",
    "hocuspocus.core.settings",
    "hocuspocus.core.source_audit",
    "hocuspocus.core.workspace_authority",
    "hocuspocus.core.workspace_grants",
    "hocuspocus.core.workspace_rate",
    "hocuspocus.core.workspace_registry",
    "hocuspocus.hocusscript._workspace_boundary_types",
    "hocuspocus.hocusscript._workspace_linux",
    "hocuspocus.hocusscript._workspace_native",
    "hocuspocus.hocusscript._workspace_publication_lock",
    "hocuspocus.hocusscript._workspace_recovery_record",
    "hocuspocus.hocusscript._workspace_windows_rename",
    "hocuspocus.hocusscript.export_handoff",
    "hocuspocus.hocusscript.export_handoff_auth",
    "hocuspocus.hocusscript.project_description",
    "hocuspocus.hocusscript.project_build",
    "hocuspocus.hocusscript.project_manifest_guard",
    "hocuspocus.hocusscript.project_search",
    "hocuspocus.hocusscript.project_service_cursors",
    "hocuspocus.hocusscript.project_service_support",
    "hocuspocus.hocusscript.project_services",
    "hocuspocus.hocusscript.project_write_lifecycle",
    "hocuspocus.hocusscript.workspace_io",
    "hocuspocus.hocusscript.workspace_patch",
    "hocuspocus.hocusscript.workspace_snapshot",
    "hocuspocus.live.context",
    "hocuspocus.live.operations",
    "hocuspocus.live.ops.document_network_families",
    "hocuspocus.live.ops.hocusscript",
    "hocuspocus.live.ops.source_resources",
    "hocuspocus.live.ops.source_workspace",
    "hocuspocus.startup",
    "hocuspocus.ui.panel",
    "hocuspocus.ui.workspace_widget",
)
H6_CRITICAL_ARTIFACTS = (
    "config/default.toml",
    "python_panels/HocusPocus.pypanel",
)

TARGET_PATH = "/obj/h6_source_workspace"
PROJECT_UID = "h6-installed-workspace"

CONTROL_SOURCE = f"""hocus 0.3;
graph Main {{
  target "{TARGET_PATH}";
  category Sop;
  mode reconcile;
  ownership "studio.h6";
  node source @id("source"): "null" {{}}
  node out @id("out"): "null" {{ input[0] = source.output[0]; }}
  display = out;
  render = out;
  output = out;
}}
"""


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_control_project(root: Path, catalog_json: str) -> None:
    """Create a portable 0.3 project and its initial generated lock."""

    from hocuspocus.hocusscript import update_project_control_lock

    _project_directories(root)
    _write_text(root / "catalog/catalog.json", catalog_json + "\n")
    _write_text(
        root / "hocus.project.toml",
        f"""schema_version = 4
[project]
uid = "{PROJECT_UID}"
name = "H6 Installed Workspace"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "0.3"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
""",
    )
    _write_text(root / "src/main.hocus", CONTROL_SOURCE)
    update_project_control_lock(
        root,
        ("src/main.hocus",),
        allow_write=True,
    )


def write_export_project(root: Path, catalog_json: str, catalog_fingerprint: str) -> None:
    """Create the explicit flat 0.1 destination used by document export."""

    from hocuspocus.hocusscript.project import ProjectContext

    _project_directories(root)
    catalog_raw = (catalog_json + "\n").encode("utf-8")
    manifest = f"""schema_version = 2
[project]
uid = "{PROJECT_UID}"
name = "H6 Flat Export"
source_directories = ["src"]
[language]
version = "0.1"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
"""
    manifest_raw = manifest.encode("utf-8")
    (root / "catalog/catalog.json").write_bytes(catalog_raw)
    (root / "hocus.project.toml").write_bytes(manifest_raw)
    lock = {
        "$schema": "hocuspocus://schemas/hocus-lock/v2",
        "kind": "hocus_project_lock",
        "schemaVersion": 2,
        "projectUid": PROJECT_UID,
        "manifestDigest": digest_bytes(manifest_raw),
        "languageVersion": "0.1",
        "catalog": {
            "schemaVersion": 1,
            "path": "catalog/catalog.json",
            "contentDigest": digest_bytes(catalog_raw),
            "fingerprint": catalog_fingerprint,
        },
        "modules": [],
    }
    _write_text(
        root / "pins/hocus.lock.json",
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    validated = ProjectContext.load(root, validate_lock=True)
    if (
        validated.manifest_version != 2
        or validated.language_version != "0.1"
        or validated.catalog_fingerprint != catalog_fingerprint
        or validated.lock_digest is None
    ):
        raise RuntimeError("Native validation rejected the H6 flat-export project lock.")


def unified_replacement(
    relative_path: str,
    original: str,
    updated: str,
) -> str:
    """Build one strict, single-file unified diff."""

    if original == updated:
        raise RuntimeError("H6 smoke replacement did not change source text.")
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )


def invoke_source_tool(
    endpoint: Any,
    name: str,
    arguments: dict[str, Any],
    context: Any,
    *,
    forbidden_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Invoke one source tool through production JSON-RPC when available."""

    runtime_call = getattr(endpoint, "handle_request", None)
    if callable(runtime_call):
        response = runtime_call(
            {
                "jsonrpc": "2.0",
                "id": f"h6-{name}",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            principal_id=context.principal_id,
            session_id=context.session_id,
        )
        if isinstance(response, Mapping) and isinstance(response.get("error"), Mapping):
            error = response["error"]
            from hocuspocus.core.jsonrpc import JsonRpcError

            raise JsonRpcError(
                int(error.get("code", -32603)),
                str(error.get("message", "Source tool request failed.")),
                error.get("data"),
            )
        result = response.get("result") if isinstance(response, Mapping) else None
        if not isinstance(result, Mapping):
            raise RuntimeError(f"Production source dispatch failed: {name}: {response!r}")
        response = result
    else:
        definition = endpoint.get(name)
        if definition is None:
            raise RuntimeError(f"Registered source tool is absent: {name}")
        response = definition.handler(arguments, context)
    if response.get("isError") is not False:
        raise RuntimeError(f"Registered source tool failed: {name}: {response!r}")
    payload = response.get("structuredContent")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Registered source tool returned no structured payload: {name}")
    assert_no_physical_roots(payload, forbidden_roots)
    return payload


def assert_no_physical_roots(value: Any, roots: tuple[Path, ...]) -> None:
    rendered = json.dumps(value, ensure_ascii=True, default=str)
    for root in roots:
        spellings = {str(root), str(root).replace("\\", "/")}
        if any(spelling and spelling in rendered for spelling in spellings):
            raise RuntimeError("H6 MCP payload exposed a physical workspace root.")


def initialize_git_repository(root: Path) -> str:
    """Commit the initial workspace so later native writes are Git-visible."""

    _git(root, "init", "--quiet")
    hooks = root / ".git/h6-empty-hooks"
    hooks.mkdir()
    for arguments in (
        ("config", "user.name", "HocusPocus H6 Smoke"),
        ("config", "user.email", "h6-smoke@example.invalid"),
        ("config", "commit.gpgSign", "false"),
        ("config", "core.hooksPath", str(hooks)),
        ("add", "--all"),
        (
            "commit",
            "--quiet",
            "--no-verify",
            "--no-gpg-sign",
            "-m",
            "H6 installed acceptance baseline",
        ),
    ):
        _git(root, *arguments)
    return _git(root, "rev-parse", "HEAD").strip()


def git_status(root: Path) -> tuple[str, ...]:
    output = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return tuple(line for line in output.splitlines() if line)


def verify_installed_modules(
    repository_root: Path,
    installed_root: Path,
) -> dict[str, dict[str, str]]:
    """Hash every H6 runtime file in the installed tree against this checkout."""

    records: dict[str, dict[str, str]] = {}
    for module_name in H6_CRITICAL_MODULES:
        relative = Path("python3.11libs", *module_name.split(".")).with_suffix(".py")
        records[module_name] = _alignment_record(
            repository_root,
            installed_root,
            relative,
            module_name,
        )
    for authored in H6_CRITICAL_ARTIFACTS:
        relative = Path(authored)
        if authored == "config/default.toml":
            record = _config_alignment_record(
                repository_root / relative,
                installed_root / relative,
            )
        else:
            record = _alignment_record(
                repository_root,
                installed_root,
                relative,
                authored,
            )
        records[f"artifact:{authored}"] = record
    return records


def validate_acceptance_result(result: Mapping[str, Any]) -> None:
    """Validate the final machine-readable H6 installed receipt."""

    required = {
        "status",
        "alignment",
        "sourceTools",
        "project",
        "live",
        "export",
        "git",
        "revocation",
        "cookExecuted",
    }
    if set(result) != required:
        raise RuntimeError("H6 installed receipt has missing or unknown fields.")
    if result.get("status") != "passed" or result.get("cookExecuted") is not False:
        raise RuntimeError("H6 installed workflow did not finish cleanly without cooks.")
    if tuple(result.get("sourceTools", ())) != SOURCE_TOOL_NAMES:
        raise RuntimeError("H6 installed receipt did not exercise the exact source surface.")
    live = result.get("live")
    export = result.get("export")
    revocation = result.get("revocation")
    if not isinstance(live, Mapping) or not all(
        live.get(key) is True for key in ("previewed", "planned", "applied", "verified")
    ):
        raise RuntimeError("H6 installed live document pipeline is incomplete.")
    if not isinstance(export, Mapping) or not all(
        export.get(key) is True
        for key in (
            "written",
            "recompiled",
            "reconciled",
            "semanticPreserved",
            "exactBytes",
            "digestVerified",
        )
    ):
        raise RuntimeError("H6 installed export round trip is incomplete.")
    if not isinstance(revocation, Mapping) or not all(
        revocation.get(key) is True
        for key in ("denied", "resourceDenied", "listFiltered")
    ):
        raise RuntimeError("H6 installed revocation denial was not proven.")


def _project_directories(root: Path) -> None:
    for relative in ("src", "modules", "pins", "catalog"):
        (root / relative).mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _alignment_record(
    repository_root: Path,
    installed_root: Path,
    relative: Path,
    label: str,
) -> dict[str, str]:
    repository_path = repository_root / relative
    installed_path = installed_root / relative
    if not repository_path.is_file() or not installed_path.is_file():
        raise RuntimeError(f"H6 installed receipt is incomplete: {label}")
    repository_digest = digest_bytes(repository_path.read_bytes())
    installed_digest = digest_bytes(installed_path.read_bytes())
    if repository_digest != installed_digest:
        raise RuntimeError(
            f"Installed H6 artifact is stale: {label} "
            f"installed={installed_digest} repository={repository_digest}"
        )
    return {
        "relativePath": relative.as_posix(),
        "sha256": installed_digest,
    }


def _config_alignment_record(
    repository_path: Path,
    installed_path: Path,
) -> dict[str, str]:
    if not repository_path.is_file() or not installed_path.is_file():
        raise RuntimeError("H6 installed receipt is incomplete: config/default.toml")
    repository_raw = repository_path.read_bytes()
    installed_raw = installed_path.read_bytes()
    normalized = normalize_installed_config(repository_raw, installed_raw)
    if normalized != repository_raw:
        raise RuntimeError(
            "Installed H6 config differs outside installer-owned token fields."
        )
    return {
        "relativePath": "config/default.toml",
        "sha256": digest_bytes(installed_raw),
        "normalizedSha256": digest_bytes(normalized),
        "alignment": "installer-token-normalized",
    }


def normalize_installed_config(
    repository_raw: bytes,
    installed_raw: bytes,
) -> bytes:
    """Reverse only the build installer's generated-token substitutions."""

    try:
        repository = repository_raw.decode("utf-8")
        installed = installed_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("H6 config alignment requires exact UTF-8.") from exc
    _require_single_config_field(repository, "token_mode")
    _require_single_config_field(repository, "token")
    _require_single_config_field(installed, "token_mode")
    _require_single_config_field(installed, "token")
    if len(re.findall(r'(?m)^token_mode = "generated"(?=\r?$)', repository)) != 1:
        raise RuntimeError("Repository token_mode is not the installer input.")
    if len(re.findall(r'(?m)^token = ""(?=\r?$)', repository)) != 1:
        raise RuntimeError("Repository token is not the installer input.")
    normalized, mode_count = re.subn(
        r'(?m)^token_mode = "static"(?=\r?$)',
        'token_mode = "generated"',
        installed,
    )
    normalized, token_count = re.subn(
        r'(?m)^token = "[A-Za-z0-9_-]{32}"(?=\r?$)',
        'token = ""',
        normalized,
    )
    if mode_count != 1 or token_count != 1:
        raise RuntimeError(
            "Installed config does not contain the exact generated-token rewrite."
        )
    normalized_raw = normalized.encode("utf-8")
    if normalized_raw != repository_raw:
        raise RuntimeError(
            "Installed H6 config differs outside installer-owned token fields."
        )
    return normalized_raw


def _require_single_config_field(value: str, field: str) -> None:
    if len(re.findall(rf"(?m)^{re.escape(field)}\s*=", value)) != 1:
        raise RuntimeError(f"H6 config requires exactly one {field} field.")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    return completed.stdout


def expect_failure(callback: Callable[[], Any]) -> Exception:
    try:
        callback()
    except Exception as exc:
        return exc
    raise RuntimeError("Expected the H6 source operation to be denied.")


__all__ = [
    "CONTROL_SOURCE",
    "H6_CRITICAL_ARTIFACTS",
    "H6_CRITICAL_MODULES",
    "PROJECT_UID",
    "SOURCE_TOOL_NAMES",
    "TARGET_PATH",
    "assert_no_physical_roots",
    "digest_bytes",
    "expect_failure",
    "git_status",
    "initialize_git_repository",
    "invoke_source_tool",
    "normalize_installed_config",
    "unified_replacement",
    "validate_acceptance_result",
    "verify_installed_modules",
    "write_control_project",
    "write_export_project",
]
