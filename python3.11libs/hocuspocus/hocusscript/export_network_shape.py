"""Exact catalog network-shape checks for normalized source export."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def validate_exported_network_nodes(
    nodes: list[dict[str, Any]],
    selected: dict[str, Any],
    block: Callable[..., None],
) -> None:
    """Reject missing or conflicting instance-network evidence."""

    for node in nodes:
        uid = str(node.get("uid", ""))
        operator = selected.get(uid)
        if operator is None:
            block(
                "HOCUS813",
                "Node lacks exact catalog operator evidence after recompilation.",
                "/nodes",
                uid or None,
            )
            continue
        catalog_hda = (
            getattr(getattr(operator, "source", None), "kind", None) == "hda"
        )
        document_network = bool(node.get("isNetwork"))
        exact_network = getattr(operator, "instance_network", None)
        mismatch = (
            exact_network != document_network
            if exact_network is not None
            else document_network and not catalog_hda
        )
        if not mismatch:
            continue
        block(
            "HOCUS813",
            "Subnetwork identity conflicts with exact catalog evidence.",
            "/nodes",
            uid or None,
            documentIsNetwork=document_network,
            catalogSourceKind=getattr(
                getattr(operator, "source", None), "kind", None
            ),
            catalogInstanceNetwork=exact_network,
        )
