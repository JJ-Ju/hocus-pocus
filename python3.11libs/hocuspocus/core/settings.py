"""Settings loader for HocusPocus."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - local Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


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
    read_only: bool = False
    allow_scene_edit: bool = True
    allow_file_write: bool = True
    approved_roots: list[str] = field(default_factory=list)
    enable_exec_tools: bool = False
    enable_stdio_bridge: bool = True
    feature_flags: dict[str, bool] = field(default_factory=dict)
    config_path: str = ""

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


def load_settings(config_path: str | Path | None = None) -> ServerSettings:
    path = Path(config_path) if config_path else paths.config_path()
    payload = _load_toml(path)

    feature_flags = {
        key: bool(value)
        for key, value in payload.get("feature_flags", {}).items()
    }

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
        read_only=bool(payload.get("read_only", False)),
        allow_scene_edit=bool(payload.get("allow_scene_edit", True)),
        allow_file_write=bool(payload.get("allow_file_write", True)),
        approved_roots=[str(item) for item in payload.get("approved_roots", [])],
        enable_exec_tools=bool(payload.get("enable_exec_tools", False)),
        enable_stdio_bridge=bool(payload.get("enable_stdio_bridge", True)),
        feature_flags=feature_flags,
        config_path=str(path),
    )

    env_overrides: dict[str, Any] = {
        "host": os.environ.get("HOCUSPOCUS_HOST"),
        "port": os.environ.get("HOCUSPOCUS_PORT"),
        "mcp_route": os.environ.get("HOCUSPOCUS_MCP_ROUTE"),
        "health_route": os.environ.get("HOCUSPOCUS_HEALTH_ROUTE"),
        "token_mode": os.environ.get("HOCUSPOCUS_TOKEN_MODE"),
        "token": os.environ.get("HOCUSPOCUS_TOKEN"),
        "auto_start": os.environ.get("HOCUSPOCUS_AUTO_START"),
        "log_level": os.environ.get("HOCUSPOCUS_LOG_LEVEL"),
        "request_timeout_seconds": os.environ.get("HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS"),
        "read_only": os.environ.get("HOCUSPOCUS_READ_ONLY"),
        "allow_scene_edit": os.environ.get("HOCUSPOCUS_ALLOW_SCENE_EDIT"),
        "allow_file_write": os.environ.get("HOCUSPOCUS_ALLOW_FILE_WRITE"),
        "enable_exec_tools": os.environ.get("HOCUSPOCUS_ENABLE_EXEC_TOOLS"),
        "enable_stdio_bridge": os.environ.get("HOCUSPOCUS_ENABLE_STDIO_BRIDGE"),
    }

    for key, value in env_overrides.items():
        if value is None:
            continue
        if key == "port":
            setattr(settings, key, int(value))
        elif key == "request_timeout_seconds":
            setattr(settings, key, float(value))
        elif key in {
            "auto_start",
            "read_only",
            "allow_scene_edit",
            "allow_file_write",
            "enable_exec_tools",
            "enable_stdio_bridge",
        }:
            setattr(settings, key, _coerce_bool(value))
        else:
            setattr(settings, key, value)

    roots_override = os.environ.get("HOCUSPOCUS_APPROVED_ROOTS")
    if roots_override:
        settings.approved_roots = [
            item.strip()
            for item in roots_override.split(os.pathsep)
            if item.strip()
        ]

    return settings
