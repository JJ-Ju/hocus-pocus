"""Internal MCP type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hocuspocus.live.context import RequestContext

ToolHandler = Callable[[dict[str, Any], RequestContext], dict[str, Any]]
ResourceReader = Callable[[RequestContext], dict[str, Any]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]
    required_capabilities: tuple[str, ...]
    handler: ToolHandler

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
            "requiredCapabilities": list(self.required_capabilities),
        }


@dataclass(slots=True)
class ResourceDefinition:
    uri: str
    name: str
    description: str
    mime_type: str
    reader: ResourceReader

    def as_payload(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, tool: ToolDefinition) -> None:
        self.tools[tool.name] = tool

    def list_payload(self) -> list[dict[str, Any]]:
        return [tool.as_payload() for tool in self.tools.values()]

    def get(self, name: str) -> ToolDefinition | None:
        return self.tools.get(name)


@dataclass(slots=True)
class ResourceRegistry:
    resources: dict[str, ResourceDefinition] = field(default_factory=dict)

    def register(self, resource: ResourceDefinition) -> None:
        self.resources[resource.uri] = resource

    def list_payload(self) -> list[dict[str, Any]]:
        return [resource.as_payload() for resource in self.resources.values()]

    def get(self, uri: str) -> ResourceDefinition | None:
        return self.resources.get(uri)
