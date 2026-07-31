"""Expansion helper for node-local managed runtime declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .runtime_carrier import encode_node_runtime
from .runtime_syntax import AnimationDecl, SpareParameterDecl
from .syntax import NodeDecl


@dataclass(frozen=True, slots=True)
class RuntimeExpansion:
    spares: list[dict[str, Any]]
    animations: list[dict[str, Any]]
    spare_declarations: tuple[SpareParameterDecl, ...]
    animation_declarations: tuple[AnimationDecl, ...]


def expand_node_runtime(
    node: NodeDecl, node_symbol: str, *, compose_identity: bool,
) -> RuntimeExpansion:
    spares, animations = encode_node_runtime(
        node,
        node_symbol=node_symbol,
        ownership="deferred",
        compose_identity=compose_identity,
    )
    return RuntimeExpansion(
        spares,
        animations,
        tuple(
            item for item in node.statements
            if isinstance(item, SpareParameterDecl)
        ),
        tuple(
            item for item in node.statements
            if isinstance(item, AnimationDecl)
        ),
    )


def integrate_runtime_state(
    node: NodeDecl,
    node_symbol: str,
    *,
    compose_identity: bool,
    state: Any,
    origin: Callable[[Any], Any],
) -> RuntimeExpansion:
    runtime = expand_node_runtime(
        node, node_symbol, compose_identity=compose_identity,
    )
    state.runtime_spares.extend(runtime.spares)
    state.runtime_animations.extend(runtime.animations)
    state.runtime_spare_origins.extend(
        origin(item) for item in runtime.spare_declarations
    )
    state.runtime_animation_origins.extend(
        origin(item) for item in runtime.animation_declarations
    )
    return runtime


def attach_graph_runtime(
    result: dict[str, Any], state: Any, *, language_version: str,
) -> None:
    if language_version == "0.4":
        result["spareParameters"] = state.runtime_spares
        result["animations"] = state.runtime_animations


def add_runtime_origins(add: Callable[[str, Any], None], state: Any) -> None:
    for table, origins in (
        ("spareParameters", state.runtime_spare_origins),
        ("animations", state.runtime_animation_origins),
    ):
        for index, origin in enumerate(origins):
            add(f"/{table}/{index}", origin)
