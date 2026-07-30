"""Private authenticated Bundle 0.3/0.4 adapter for pure document lowering."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from ._document_bundle_boundary import _DecodedDocumentBundle
from .contracts import CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION
from .control_artifact import rehydrate_control_graph
from .document_lowering import (
    DocumentLoweringError,
    DocumentPreview,
    _lower_prepared_work,
    _prepare_payload,
)
from .model import graph_spec_from_dict
from .semantic import SemanticResult


def _lower_decoded_document_bundle_to_document(
    bundle: _DecodedDocumentBundle,
    baseline_document: dict[str, Any],
    *,
    _trusted_semantic_result: SemanticResult | None = None,
) -> DocumentPreview:
    """Lower already-authenticated exact-version carrier content."""

    if type(bundle) is not _DecodedDocumentBundle:
        raise TypeError("H5 document lowering requires an authenticated bundle boundary value.")
    payload = bundle.payload
    if bundle.version in {CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION}:
        graph = rehydrate_control_graph(
            payload["graphSpec"],
            resolved_limits=payload["resolvedModuleSet"]["limits"],
        ).to_dict()
    else:
        graph = graph_spec_from_dict(payload["graphSpec"]).to_dict()
    if graph != payload["graphSpec"]:
        raise DocumentLoweringError("HOCUS700", "Authenticated graph rehydration changed content.")
    payload["graphSpec"] = graph
    preview = _lower_prepared_work(
        _prepare_payload(
            payload,
            bundle.digest,
            baseline_document,
            _trusted_semantic_result,
        )
    )
    _bind_candidate_plan_pins(bundle, preview.candidate_plan)
    return preview


def _document_bundle_plan_pins(bundle: _DecodedDocumentBundle) -> dict[str, Any]:
    """Return the exact new-lane pins shared by candidate and immutable plans."""

    if type(bundle) is not _DecodedDocumentBundle:
        raise TypeError("H5 plan pins require an authenticated bundle boundary value.")
    payload = bundle.payload
    return {
        "bundleVersion": bundle.version,
        "languageVersion": payload["languageVersion"],
        "resolverPolicyDigest": payload["resolvedModuleSet"]["resolverPolicyDigest"],
        "expansionMapDigest": payload["sourceMaps"]["expansionMapDigest"],
    }


def _bind_candidate_plan_pins(
    bundle: _DecodedDocumentBundle,
    candidate_plan: dict[str, Any] | None,
) -> None:
    if candidate_plan is None:
        return
    candidate_plan.update(_document_bundle_plan_pins(bundle))
    hashable = copy.deepcopy(candidate_plan)
    hashable.pop("planHash", None)
    encoded = json.dumps(
        hashable,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    candidate_plan["planHash"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
