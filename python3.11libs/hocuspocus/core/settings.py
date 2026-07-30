"""Settings loader for HocusPocus."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_POLICY_PROFILE = "local-dev"
DEFAULT_PRODUCTION_REVIEW_POLICY_ID = "production-review-v1"
_PORTABLE_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def available_policy_profiles() -> dict[str, dict[str, Any]]:
    output_root = str(paths.output_dir())
    return {
        "safe": {
            "description": "Read-only profile for cautious local inspection.",
            "read_only": True,
            "allow_scene_edit": False,
            "allow_file_write": False,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [],
        },
        "local-dev": {
            "description": "Default local development profile with scene and file edits enabled.",
            "read_only": False,
            "allow_scene_edit": True,
            "allow_file_write": True,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [],
        },
        "pipeline": {
            "description": "Pipeline-friendly profile with writes limited to managed output roots by default.",
            "read_only": False,
            "allow_scene_edit": True,
            "allow_file_write": True,
            "enable_exec_tools": False,
            "enable_stdio_bridge": True,
            "approved_roots": [output_root],
        },
    }


def resolve_policy_profile(name: str | None) -> tuple[str, dict[str, Any]]:
    profiles = available_policy_profiles()
    candidate = str(name or DEFAULT_POLICY_PROFILE).strip() or DEFAULT_POLICY_PROFILE
    if candidate not in profiles:
        candidate = DEFAULT_POLICY_PROFILE
    return candidate, dict(profiles[candidate])


@dataclass(slots=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 37219
    mcp_route: str = "/hocuspocus/mcp"
    health_route: str = "/hocuspocus/healthz"
    token_mode: str = "generated"
    token: str = ""
    auto_start: bool = False
    log_level: str = "INFO"
    request_timeout_seconds: float = 30.0
    policy_profile: str = DEFAULT_POLICY_PROFILE
    policy_profile_source: str = "default"
    read_only: bool = False
    allow_scene_edit: bool = True
    allow_file_write: bool = True
    approved_roots: list[str] = field(default_factory=list)
    enable_exec_tools: bool = False
    enable_stdio_bridge: bool = True
    allow_production_review: bool = False
    production_review_policy_id: str = DEFAULT_PRODUCTION_REVIEW_POLICY_ID
    feature_flags: dict[str, bool] = field(default_factory=dict)
    source_projects: list[dict[str, Any]] = field(default_factory=list)
    workspace_session_ttl_seconds: float = 28_800.0
    workspace_session_grant_ttl_seconds: float = 28_800.0
    workspace_persistent_grant_ttl_seconds: float = 2_592_000.0
    workspace_audit_events_per_project: int = 10_000
    workspace_projects_per_session: int = 16
    workspace_enumeration_limit: int = 1_000
    workspace_search_limit: int = 200
    workspace_read_batch_limit: int = 16
    workspace_patch_operation_limit: int = 64
    workspace_payload_bytes: int = 2 * 1024 * 1024
    workspace_builds_per_project: int = 1
    workspace_builds_per_session: int = 2
    workspace_rate_total_per_minute: int = 120
    workspace_rate_search_per_minute: int = 30
    workspace_rate_write_per_minute: int = 20
    workspace_rate_build_per_minute: int = 6
    config_path: str = ""

    def __post_init__(self) -> None:
        if type(self.allow_production_review) is not bool:
            raise ValueError("allow_production_review must be a boolean")
        self.production_review_policy_id = _production_review_policy_id(
            self.production_review_policy_id,
        )

    def resolved_token(self) -> str:
        if self.token_mode == "disabled":
            return ""
        if self.token:
            return self.token
        token_file = paths.runtime_token_path()
        if token_file.exists():
            return token_file.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(24)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
        return token

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}{self.normalized_mcp_route}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}{self.normalized_health_route}"

    @property
    def normalized_mcp_route(self) -> str:
        return _normalize_route(self.mcp_route, "/hocuspocus/mcp")

    @property
    def normalized_health_route(self) -> str:
        return _normalize_route(self.health_route, "/hocuspocus/healthz")

    def effective_policy_payload(self) -> dict[str, Any]:
        return {
            "profile": self.policy_profile,
            "profileSource": self.policy_profile_source,
            "readOnly": self.read_only,
            "allowSceneEdit": self.allow_scene_edit and not self.read_only,
            "allowFileWrite": self.allow_file_write and not self.read_only,
            "enableExecTools": self.enable_exec_tools,
            "enableStdioBridge": self.enable_stdio_bridge,
            "allowProductionReview": self.allow_production_review,
            "productionReviewPolicyId": self.production_review_policy_id,
            "approvedRoots": list(self.approved_roots),
        }

    def available_policy_profiles_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for name, profile in available_policy_profiles().items():
            payload.append(
                {
                    "name": name,
                    "description": profile["description"],
                    "effectivePolicy": {
                        "readOnly": bool(profile["read_only"]),
                        "allowSceneEdit": bool(profile["allow_scene_edit"] and not profile["read_only"]),
                        "allowFileWrite": bool(profile["allow_file_write"] and not profile["read_only"]),
                        "enableExecTools": bool(profile["enable_exec_tools"]),
                        "enableStdioBridge": bool(profile["enable_stdio_bridge"]),
                        "approvedRoots": list(profile["approved_roots"]),
                    },
                }
            )
        return payload


def _normalize_route(value: str, default: str) -> str:
    route = str(value or "").strip()
    if not route:
        route = default
    if not route.startswith("/"):
        route = "/" + route
    return route


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _coerce_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


_POLICY_FIELDS = (
    "read_only",
    "allow_scene_edit",
    "allow_file_write",
    "approved_roots",
    "enable_exec_tools",
    "enable_stdio_bridge",
    "allow_production_review",
)
_POLICY_TEXT_FIELDS = ("production_review_policy_id",)
_ENV_FIELDS = {
    "host": "HOCUSPOCUS_HOST",
    "port": "HOCUSPOCUS_PORT",
    "mcp_route": "HOCUSPOCUS_MCP_ROUTE",
    "health_route": "HOCUSPOCUS_HEALTH_ROUTE",
    "token_mode": "HOCUSPOCUS_TOKEN_MODE",
    "token": "HOCUSPOCUS_TOKEN",
    "auto_start": "HOCUSPOCUS_AUTO_START",
    "log_level": "HOCUSPOCUS_LOG_LEVEL",
    "request_timeout_seconds": "HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS",
    "read_only": "HOCUSPOCUS_READ_ONLY",
    "allow_scene_edit": "HOCUSPOCUS_ALLOW_SCENE_EDIT",
    "allow_file_write": "HOCUSPOCUS_ALLOW_FILE_WRITE",
    "enable_exec_tools": "HOCUSPOCUS_ENABLE_EXEC_TOOLS",
    "enable_stdio_bridge": "HOCUSPOCUS_ENABLE_STDIO_BRIDGE",
    "allow_production_review": "HOCUSPOCUS_ALLOW_PRODUCTION_REVIEW",
    "production_review_policy_id": "HOCUSPOCUS_PRODUCTION_REVIEW_POLICY_ID",
}
_BOOL_FIELDS = {
    "auto_start",
    "read_only",
    "allow_scene_edit",
    "allow_file_write",
    "enable_exec_tools",
    "enable_stdio_bridge",
    "allow_production_review",
}


def _apply_policy_values(settings: ServerSettings, values: dict[str, Any]) -> None:
    for key in _POLICY_FIELDS:
        if key not in values:
            continue
        value = values[key]
        if key == "approved_roots":
            value = [str(item) for item in value]
        else:
            value = bool(value)
        setattr(settings, key, value)
    for key in _POLICY_TEXT_FIELDS:
        if key in values:
            setattr(settings, key, _production_review_policy_id(values[key]))


def _apply_environment(settings: ServerSettings) -> None:
    for key, variable in _ENV_FIELDS.items():
        value = os.environ.get(variable)
        if value is None:
            continue
        if key == "port":
            resolved: Any = int(value)
        elif key == "request_timeout_seconds":
            resolved = float(value)
        elif key in _BOOL_FIELDS:
            resolved = _coerce_bool(value)
        else:
            resolved = value
        setattr(settings, key, resolved)


def load_settings(config_path: str | Path | None = None) -> ServerSettings:
    path = Path(config_path) if config_path else paths.config_path()
    payload = _load_toml(path)
    policy_overrides = payload.get("policy_overrides", {})
    if not isinstance(policy_overrides, dict):
        policy_overrides = {}
    env_profile = os.environ.get("HOCUSPOCUS_POLICY_PROFILE")
    profile_explicit = "policy_profile" in payload or env_profile is not None
    profile_name, profile_defaults = resolve_policy_profile(
        env_profile if env_profile is not None else payload.get("policy_profile")
    )

    feature_flags = {
        key: bool(value)
        for key, value in payload.get("feature_flags", {}).items()
    }
    workspace = _workspace_settings(payload.get("source_workspace", {}))

    settings = ServerSettings(
        host=str(payload.get("host", "127.0.0.1")),
        port=int(payload.get("port", 37219)),
        mcp_route=str(payload.get("mcp_route", "/hocuspocus/mcp")),
        health_route=str(payload.get("health_route", "/hocuspocus/healthz")),
        token_mode=str(payload.get("token_mode", "generated")),
        token=str(payload.get("token", "")),
        auto_start=bool(payload.get("auto_start", False)),
        log_level=str(payload.get("log_level", "INFO")),
        request_timeout_seconds=float(payload.get("request_timeout_seconds", 30.0)),
        policy_profile=profile_name,
        policy_profile_source="environment" if env_profile is not None else ("config" if profile_explicit else "default"),
        read_only=bool(profile_defaults["read_only"]),
        allow_scene_edit=bool(profile_defaults["allow_scene_edit"]),
        allow_file_write=bool(profile_defaults["allow_file_write"]),
        approved_roots=[str(item) for item in profile_defaults["approved_roots"]],
        enable_exec_tools=bool(profile_defaults["enable_exec_tools"]),
        enable_stdio_bridge=bool(profile_defaults["enable_stdio_bridge"]),
        allow_production_review=bool(
            payload.get("allow_production_review", False),
        ),
        production_review_policy_id=str(payload.get(
            "production_review_policy_id",
            DEFAULT_PRODUCTION_REVIEW_POLICY_ID,
        )),
        feature_flags=feature_flags,
        source_projects=workspace["projects"],
        workspace_session_ttl_seconds=workspace["session_ttl_seconds"],
        workspace_session_grant_ttl_seconds=workspace["session_grant_ttl_seconds"],
        workspace_persistent_grant_ttl_seconds=workspace["persistent_grant_ttl_seconds"],
        workspace_audit_events_per_project=workspace["audit_events_per_project"],
        workspace_projects_per_session=workspace["projects_per_session"],
        workspace_enumeration_limit=workspace["enumeration_limit"],
        workspace_search_limit=workspace["search_limit"],
        workspace_read_batch_limit=workspace["read_batch_limit"],
        workspace_patch_operation_limit=workspace["patch_operation_limit"],
        workspace_payload_bytes=workspace["payload_bytes"],
        workspace_builds_per_project=workspace["builds_per_project"],
        workspace_builds_per_session=workspace["builds_per_session"],
        workspace_rate_total_per_minute=workspace["rate_total_per_minute"],
        workspace_rate_search_per_minute=workspace["rate_search_per_minute"],
        workspace_rate_write_per_minute=workspace["rate_write_per_minute"],
        workspace_rate_build_per_minute=workspace["rate_build_per_minute"],
        config_path=str(path),
    )

    if not profile_explicit:
        _apply_policy_values(settings, payload)
    _apply_policy_values(settings, policy_overrides)
    _apply_environment(settings)
    settings.production_review_policy_id = _production_review_policy_id(
        settings.production_review_policy_id,
    )

    roots_override = os.environ.get("HOCUSPOCUS_APPROVED_ROOTS")
    if roots_override:
        settings.approved_roots = [
            item.strip()
            for item in roots_override.split(os.pathsep)
            if item.strip()
        ]

    return settings


def _production_review_policy_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _PORTABLE_POLICY_ID.fullmatch(value) is None
    ):
        raise ValueError(
            "production_review_policy_id must be a portable identifier"
        )
    return value


_WORKSPACE_DEFAULTS = {
    "session_ttl_seconds": 28_800.0,
    "session_grant_ttl_seconds": 28_800.0,
    "persistent_grant_ttl_seconds": 2_592_000.0,
    "audit_events_per_project": 10_000,
    "projects_per_session": 16,
    "enumeration_limit": 1_000,
    "search_limit": 200,
    "read_batch_limit": 16,
    "patch_operation_limit": 64,
    "payload_bytes": 2 * 1024 * 1024,
    "builds_per_project": 1,
    "builds_per_session": 2,
    "rate_total_per_minute": 120,
    "rate_search_per_minute": 30,
    "rate_write_per_minute": 20,
    "rate_build_per_minute": 6,
}
_WORKSPACE_CEILINGS = {
    "audit_events_per_project": 100_000,
    "projects_per_session": 64,
    "enumeration_limit": 4_096,
    "search_limit": 1_000,
    "read_batch_limit": 64,
    "patch_operation_limit": 256,
    "payload_bytes": 8 * 1024 * 1024,
    "builds_per_project": 1,
    "builds_per_session": 8,
    "rate_total_per_minute": 120,
    "rate_search_per_minute": 30,
    "rate_write_per_minute": 20,
    "rate_build_per_minute": 6,
}


def _workspace_settings(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    projects = payload.get("projects", [])
    if not isinstance(projects, list) or len(projects) > 64:
        raise ValueError("source_workspace.projects must be an array of at most 64 tables")
    result = dict(_WORKSPACE_DEFAULTS)
    for key, default in _WORKSPACE_DEFAULTS.items():
        candidate = payload.get(key, default)
        result[key] = float(candidate) if isinstance(default, float) else int(candidate)
    for key, ceiling in _WORKSPACE_CEILINGS.items():
        if not 1 <= result[key] <= ceiling:
            raise ValueError(f"source_workspace.{key} exceeds its supported bounds")
    for key in (
        "session_ttl_seconds",
        "session_grant_ttl_seconds",
        "persistent_grant_ttl_seconds",
    ):
        if not 1 <= result[key] <= 365 * 24 * 60 * 60:
            raise ValueError(f"source_workspace.{key} exceeds its supported bounds")
    result["projects"] = [_workspace_project(item) for item in projects]
    return result


def _workspace_project(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("root"), str):
        raise ValueError("each source_workspace.projects item requires a root")
    output = {"root": value["root"]}
    for key in ("project_id", "label"):
        if value.get(key) is not None:
            output[key] = str(value[key])
    grants = _workspace_project_grants(value.get("grants"))
    if grants is not None:
        output["grants"] = sorted(set(grants))
    external_roots = _workspace_external_roots(value.get("external_roots"), grants)
    if external_roots is not None:
        output["external_roots"] = dict(external_roots)
    output.update(_workspace_grant_lifetime(value, grants))
    return output


def _workspace_project_grants(value: Any) -> list[str] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or any(
            not isinstance(item, str) or item not in _WORKSPACE_GRANT_NAMES
            for item in value
        )
    ):
        raise ValueError("source workspace project grants are invalid")
    return value


def _workspace_external_roots(
    value: Any,
    grants: list[str] | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or any(
        not isinstance(alias, str) or not isinstance(root, str)
        for alias, root in value.items()
    ):
        raise ValueError("source workspace external_roots must be a string table")
    if value and (grants is None or "external_read" not in grants):
        raise ValueError("configured external_roots require external_read")
    return value


def _workspace_grant_lifetime(
    value: dict[str, Any],
    grants: list[str] | None,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    expires = value.get("grant_expires_in_seconds")
    until_revoked = value.get("grant_until_revoked", False)
    if not isinstance(until_revoked, bool):
        raise ValueError("configured grant_until_revoked must be a boolean")
    if until_revoked:
        if not grants:
            raise ValueError("configured until-revoked grant requires grants")
        if expires is not None:
            raise ValueError(
                "configured grant cannot combine expiry and until-revoked"
            )
        output["grant_until_revoked"] = True
    if expires is not None:
        if not grants:
            raise ValueError("configured grant expiry requires grants")
        expires = float(expires)
        if not 1 <= expires <= 365 * 24 * 60 * 60:
            raise ValueError("configured workspace grant expiry is outside supported bounds")
        output["grant_expires_in_seconds"] = expires
    return output


_WORKSPACE_GRANT_NAMES = {
    "source_read",
    "source_write",
    "generated_lock",
    "external_read",
    "source_notify",
}
