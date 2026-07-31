"""Published HS7 fidelity policy.

The matrix is deliberately executable policy rather than marketing copy.  A
feature may be advertised as ``supported`` only when the corresponding source,
document, live, and round-trip gates are all true.
"""

from __future__ import annotations

import copy
from typing import Any


HS7_MATRIX_VERSION = 1
_STATUSES = {"supported", "preserved-opaque", "read-only", "rejected"}


_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "id": "sop",
        "label": "SOP and OBJ-contained SOP",
        "status": "supported",
        "apply": "structural-indexed",
        "outputPolicy": "sop_display",
        "constraints": ["editable network", "catalog-resolved operators"],
    },
    {
        "id": "mat",
        "label": "Material builders and fixed-port VOP networks",
        "status": "supported",
        "apply": "structural-indexed",
        "outputPolicy": "none",
        "constraints": [
            "editable network",
            "catalog-complete fixed connectors",
            "dynamic connectors rejected",
        ],
    },
    {
        "id": "lop",
        "label": "LOP/Solaris structural networks",
        "status": "supported",
        "apply": "structural-indexed",
        "outputPolicy": "none",
        "constraints": [
            "editable network",
            "USD relationships and variants remain read-only verification",
        ],
    },
    {
        "id": "top",
        "label": "TOP/PDG structural networks",
        "status": "supported",
        "apply": "structural-indexed",
        "outputPolicy": "none",
        "constraints": ["no cook", "work-item and scheduler state remain read-only"],
    },
    {
        "id": "rop",
        "label": "ROP networks",
        "status": "read-only",
        "apply": "rejected",
        "outputPolicy": "none",
        "constraints": ["render execution remains on the dedicated confirmed task surface"],
    },
    {
        "id": "dop",
        "label": "DOP networks",
        "status": "read-only",
        "apply": "rejected",
        "outputPolicy": "none",
        "constraints": ["simulation state is outside declarative apply"],
    },
    {
        "id": "cop",
        "label": "COP networks",
        "status": "read-only",
        "apply": "rejected",
        "outputPolicy": "none",
        "constraints": ["awaiting installed round-trip and rollback matrix"],
    },
    {
        "id": "chop",
        "label": "CHOP networks",
        "status": "read-only",
        "apply": "rejected",
        "outputPolicy": "none",
        "constraints": ["awaiting installed round-trip and rollback matrix"],
    },
    {
        "id": "hda_definition",
        "label": "HDA definition contents",
        "status": "rejected",
        "apply": "rejected",
        "outputPolicy": "none",
        "constraints": ["requires a separate definition-authoring contract"],
    },
)


_FEATURES: tuple[dict[str, Any], ...] = (
    {
        "id": "indexed_ports",
        "status": "supported",
        "lane": "0.1-0.4",
        "notes": "Input and nonzero output indexes are authoritative.",
    },
    {
        "id": "named_ports",
        "status": "supported",
        "lane": "0.4/0.5",
        "notes": "Exact unique fixed catalog names lower to authoritative indexes; ambiguous or dynamic names reject.",
    },
    {
        "id": "scalar_and_menu",
        "status": "supported",
        "lane": "0.1-0.4",
        "notes": "Menu tokens are supported; labels are not accepted as tokens.",
    },
    {
        "id": "whole_tuple",
        "status": "supported",
        "lane": "0.4/0.5",
        "notes": "Ordered components require exact catalog token evidence and lower to scalar live parameters.",
    },
    {
        "id": "units",
        "status": "supported",
        "lane": "0.4/catalog-v2",
        "notes": "Typed quantities require a catalog dimension and convert to its declared canonical unit.",
    },
    {
        "id": "raw_paths",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Explicit raw_path values remain distinct from portable node and parameter references.",
    },
    {
        "id": "managed_reset",
        "status": "supported",
        "lane": "0.1-0.4",
        "notes": "Omission in reconcile resets only previously compiler-managed fields.",
    },
    {
        "id": "explicit_reset",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "reset is a first-class typed value and verifies the Houdini parameter default.",
    },
    {
        "id": "ramps",
        "status": "supported",
        "lane": "0.4/catalog-v2/network-document-v2",
        "notes": "Float and color ramps preserve point order, positions, values, and supported bases.",
    },
    {
        "id": "multiparms",
        "status": "supported",
        "lane": "0.4/catalog-v2/network-document-v2",
        "notes": "Exact instance-start and child-token evidence drives bounded transactional grow and shrink.",
    },
    {
        "id": "expressions",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Exact HScript expression text and language round-trip on catalog-compatible parameters.",
    },
    {
        "id": "channel_references",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Structural channel references resolve through durable node identity instead of ambient paths.",
    },
    {
        "id": "code_blobs",
        "status": "supported",
        "lane": "0.1-0.4",
        "notes": "Only catalog-declared code surfaces and languages are accepted.",
    },
    {
        "id": "callbacks_and_buttons",
        "status": "rejected",
        "lane": "separate-action",
        "notes": "Callbacks are actions, never declarative values.",
    },
    {
        "id": "spare_parameters",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Managed instance spares support bounded float, int, string, toggle, and menu interfaces while artist spares remain protected.",
    },
    {
        "id": "numeric_keyframes",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Scalar float and int keys use canonical seconds with fixed interpolation and extrapolation enums.",
    },
    {
        "id": "usd_time_samples",
        "status": "rejected",
        "lane": "separate-contract",
        "notes": "USD time samples require stage-layer and authored-layer ownership semantics outside HS7.",
    },
    {
        "id": "graph_editor_annotations",
        "status": "supported",
        "lane": "0.4/network-document-v2",
        "notes": "Stable boxes, routed dots, stickies, comments, and deterministic layout constraints round-trip without cooks.",
    },
    {
        "id": "locked_hda_boundaries",
        "status": "rejected",
        "lane": "separate-contract",
        "notes": "Structural apply fails before mutation inside locked definitions.",
    },
)


def hs7_fidelity_matrix() -> dict[str, Any]:
    """Return a defensive copy of the published machine-readable matrix."""

    payload = {
        "kind": "hocus_fidelity_matrix",
        "matrixVersion": HS7_MATRIX_VERSION,
        "phase": "HS7",
        "statuses": sorted(_STATUSES),
        "families": _FAMILIES,
        "features": _FEATURES,
        "completionRule": (
            "supported requires source, document, live apply, save/reopen, "
            "rollback, and export/recompile evidence"
        ),
    }
    return copy.deepcopy(payload)
