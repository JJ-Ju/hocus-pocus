"""Private H5 carrier/provenance helpers for the consolidated test catalogue."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    lower_bundle_to_document,
    resolve_graph,
)
from hocuspocus.hocusscript.document_bundle_lowering import (
    _lower_decoded_document_bundle_to_document,
)
from hocuspocus.hocusscript.document_lowering import DocumentLoweringError


def _content_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tampered_control_bundle(
    payload: dict[str, Any],
    path: tuple[str | int, ...],
    value: Any,
) -> dict[str, Any]:
    tampered = copy.deepcopy(payload)
    cursor = tampered
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    unsigned = dict(tampered)
    unsigned.pop("bundleDigest")
    tampered["bundleDigest"] = _content_digest(unsigned)
    return tampered


def _assert_forged_document_stacks_rejected(
    test: unittest.TestCase,
    lowered: Any,
    authenticated: Any,
) -> None:
    tables = lowered.document["metadata"]["hocusExpansion"]
    for stack_field in ("moduleStacks", "controlStacks"):
        if not tables[stack_field]:
            continue
        forged_baseline = copy.deepcopy(lowered.document)
        forged_stack = forged_baseline["metadata"]["hocusExpansion"][
            stack_field
        ][0]
        forged_stack["frames"][0]["forged"] = True
        with test.assertRaises(DocumentLoweringError) as forged:
            _lower_decoded_document_bundle_to_document(
                authenticated, forged_baseline,
            )
        test.assertEqual(forged.exception.code, "HOCUS710")


def _retained_control_stack(stack: dict[str, Any]) -> dict[str, Any]:
    retained = copy.deepcopy(stack)
    retained["frames"][0]["durableSeed"] += "-retained"
    retained["controlStackId"] = _content_digest({
        "domain": "hocus-control-stack-v1",
        "frames": retained["frames"],
    })
    return retained


def _assert_adopted_external_lifecycle(
    test: unittest.TestCase,
    provider: Any,
    baseline: dict[str, Any],
    entry_uri: str,
) -> None:
    def bundle(source: str, source_uri: str) -> CompiledBundle:
        result = compile_source(
            source,
            "assets/adopted.hocus",
            source_uri=source_uri,
        )
        test.assertTrue(result.valid)
        result.semantic_result = resolve_graph(result.graph_spec, provider)
        test.assertTrue(result.semantic_result.valid)
        result.source_kind = "project_file"
        result.project_uid = "city"
        result.project_manifest_digest = "sha256:" + "1" * 64
        result.project_lock_digest = "sha256:" + "2" * 64
        result.catalog_fingerprint = provider.catalog.fingerprint
        result.catalog_content_digest = (
            "sha256:"
            + hashlib.sha256(
                provider.catalog.to_json().encode("utf-8")
            ).hexdigest()
        )
        return CompiledBundle.from_result(result)

    selected = """hocus 0.1;
graph adopted {
  target "/obj/geo1";
  category Sop;
  mode reconcile;
  ownership "studio.adopted";
  adopt artist = "/obj/geo1/artist";
  display = artist;
  render = artist;
  output = artist;
}
"""
    first = lower_bundle_to_document(
        bundle(selected, entry_uri),
        baseline,
    )
    test.assertTrue(first.valid, first.diagnostics)
    artist = next(
        node for node in first.document["nodes"]
        if node["uid"] == "artist-node"
    )
    test.assertTrue(artist["flags"]["display"])
    test.assertTrue(artist["flags"]["render"])
    test.assertEqual(
        artist["metadata"]["hocus"]["managedFields"]["flags"],
        {"display": True, "output": True, "render": True},
    )
    test.assertIn(
        "adopt_node",
        {item["action"] for item in first.candidate_plan["operations"]},
    )

    moved = lower_bundle_to_document(
        bundle(
            selected,
            "hocus-project://city/moved/adopted.hocus",
        ),
        first.document,
    )
    test.assertTrue(moved.valid, moved.diagnostics)
    actions = {
        item["action"] for item in moved.candidate_plan["operations"]
    }
    test.assertIn("update_node_provenance", actions)
    test.assertNotIn("adopt_node", actions)

    omitted = selected.replace(
        "  display = artist;\n"
        "  render = artist;\n"
        "  output = artist;\n",
        "",
    )
    cleared = lower_bundle_to_document(
        bundle(omitted, entry_uri),
        moved.document,
    )
    test.assertTrue(cleared.valid, cleared.diagnostics)
    artist = next(
        node for node in cleared.document["nodes"]
        if node["uid"] == "artist-node"
    )
    test.assertFalse(artist["flags"]["display"])
    test.assertFalse(artist["flags"]["render"])
    test.assertFalse(
        any(
            edge.get("kind") == "output_flag"
            for edge in cleared.document["edges"]
        )
    )
