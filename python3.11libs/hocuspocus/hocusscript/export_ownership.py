"""Ownership selection for the complete HS7 export surface."""

from __future__ import annotations

from typing import Any


_AUXILIARY_FIELDS = (
    "networkBoxes", "stickyNotes", "nodeComments", "networkDots",
    "layoutConstraints", "spareParameters", "animations",
)


def managed_export_ownership(
    document: dict[str, Any],
    collections: dict[str, list[Any]],
    managed_uids: set[str],
) -> tuple[set[str], bool]:
    """Return namespaces and completeness across core and auxiliary entities."""

    all_collections = dict(collections)
    for field in _AUXILIARY_FIELDS:
        value = document.get(field, [])
        all_collections[field] = value if isinstance(value, list) else []
        managed_uids.update(
            str(item["uid"])
            for item in all_collections[field]
            if isinstance(item, dict)
            and isinstance(item.get("uid"), str)
            and item["uid"]
        )
    ownerships: set[str] = set()
    covered = 0
    for items in all_collections.values():
        for item in items:
            if not isinstance(item, dict) or item.get("uid") not in managed_uids:
                continue
            metadata = item.get("metadata")
            hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
            ownership = hocus.get("ownership") if isinstance(hocus, dict) else None
            if isinstance(ownership, str) and ownership:
                ownerships.add(ownership)
                covered += 1
    return ownerships, covered == len(managed_uids)
