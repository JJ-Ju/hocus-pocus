from __future__ import annotations

import copy
import hashlib
import json
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.catalog import CategoryDefinition, FakeCatalogProvider
from hocuspocus.hocusscript import CompiledBundle, compile_source, resolve_graph
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.hocusscript import HocusScriptOperationsMixin
from test_hocusscript_document_lowering import _baseline, _bundle, _digest, _node, _provider


def _deferred_bundle(*, adopted: bool = False, mode: str = "merge") -> CompiledBundle:
    declaration = "adopt" if adopted else "existing"
    directives = "display = live; render = live; output = live;" if adopted else ""
    ownership = 'ownership "studio.rocks";' if adopted else ""
    source_uri = "hocus-project://city/assets/external.hocus"
    source = f'''hocus 0.1;
graph external_demo {{
  target "/obj/geo1"; category Sop; mode {mode}; {ownership}
  {declaration} live = "/obj/geo1/live";
  node sink: sink {{ input[0] = live.output[1]; }}
  {directives}
}}
'''
    provider = _provider()
    result = compile_source(source, "assets/external.hocus", source_uri=source_uri)
    assert result.graph_spec is not None
    result.semantic_result = resolve_graph(result.graph_spec, provider)
    assert result.semantic_result.valid and not result.semantic_result.ready_for_document_lowering
    result.source_kind = "project_file"
    result.project_uid = "city"
    result.project_manifest_digest = _digest("manifest")
    result.project_lock_digest = _digest("lock")
    result.catalog_fingerprint = provider.catalog.fingerprint
    result.catalog_content_digest = _digest(provider.catalog.to_json())
    return CompiledBundle.from_result(result)


class _Dispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _PreviewOperations(OperationBaseMixin, DocumentOperationsMixin, HocusScriptOperationsMixin):
    def __init__(self, *, baseline=None, catalog=None):
        self._dispatcher = _Dispatcher()
        self._documents = LiveDocumentService(logging.getLogger("test.preview"))
        self.baseline = copy.deepcopy(baseline or _baseline())
        self.catalog = catalog or _provider().catalog

    def _document_schema_path(self) -> Path:
        return ROOT / "docs" / "schemas" / "network-document-v1.schema.json"

    def _document_current_network_payload(self, root_path: str, **_kwargs):
        self.asserted_root_path = root_path
        return copy.deepcopy(self.baseline)

    def _document_preview_live_catalog(self):
        return self.catalog


class HocusScriptPreviewOperationTests(unittest.TestCase):
    @staticmethod
    def _rehash(bundle: dict) -> None:
        unsigned = dict(bundle)
        unsigned.pop("bundleDigest", None)
        canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        bundle["bundleDigest"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def test_preview_bundle_is_read_only_content_addressed_and_schema_valid(self) -> None:
        operations = _PreviewOperations()
        response = operations.document_preview_bundle({"bundle": _bundle().to_dict()}, RequestContext())

        self.assertFalse(response["isError"])
        payload = response["structuredContent"]
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["readyForPlan"])
        self.assertFalse(payload["readyForApply"])
        self.assertEqual(operations.asserted_root_path, "/obj/geo1")
        self.assertTrue(payload["catalogResolution"]["matched"])
        self.assertIn("preview", payload)

        preview_id = payload["artifact"]["previewId"]
        stored = operations.read_document_preview(preview_id, RequestContext())
        stored_payload = json.loads(stored["contents"][0]["text"])
        self.assertEqual(stored_payload, payload["preview"])

        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        schema = json.loads(
            (ROOT / "docs" / "schemas" / "document-preview-bundle-output-v1.schema.json").read_text("utf-8")
        )
        Draft202012Validator(schema).validate(payload)

    def test_catalog_drift_blocks_lowering_without_artifact(self) -> None:
        mismatched = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"),),
            operators=(),
        ).catalog
        operations = _PreviewOperations(catalog=mismatched)
        payload = operations.document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]

        self.assertFalse(payload["valid"])
        self.assertFalse(payload["readyForPlan"])
        self.assertIsNone(payload["artifact"])
        self.assertEqual(payload["diagnostics"][0]["code"], "HOCUS720")

    def test_expected_revision_drift_removes_candidate_plan(self) -> None:
        bundle = _bundle().to_dict()
        bundle["graphSpec"]["expectedRevision"] = 999
        # The strict bundle decoder must see the updated canonical digest.
        self._rehash(bundle)

        payload = _PreviewOperations().document_preview_bundle(
            {"bundle": bundle}, RequestContext()
        )["structuredContent"]
        self.assertFalse(payload["valid"])
        self.assertFalse(payload["readyForPlan"])
        self.assertEqual(payload["diagnostics"][0]["code"], "HOCUS721")
        self.assertIsNone(payload["preview"]["candidatePlan"])

    def test_rehashed_forged_semantic_selection_is_re_resolved_and_blocked(self) -> None:
        bundle = _bundle().to_dict()
        bundle["semanticResolution"]["operatorSelections"][0]["qualifiedName"] = "forged::missing::9.9"
        self._rehash(bundle)

        payload = _PreviewOperations().document_preview_bundle(
            {"bundle": bundle}, RequestContext()
        )["structuredContent"]
        self.assertFalse(payload["valid"])
        self.assertFalse(payload["readyForPlan"])
        self.assertEqual(payload["diagnostics"][0]["code"], "HOCUS722")
        self.assertIsNone(payload["artifact"])

    def test_artifact_memory_limit_blocks_undeliverable_preview(self) -> None:
        operations = _PreviewOperations()
        operations._documents._MAX_PREVIEW_ARTIFACT_BYTES = 1
        payload = operations.document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertFalse(payload["valid"])
        self.assertFalse(payload["readyForPlan"])
        self.assertEqual(payload["diagnostics"][0]["code"], "HOCUS723")
        self.assertIsNone(payload["artifact"])

    def test_deferred_external_binding_resolves_from_live_baseline(self) -> None:
        live = _node("live-uid", "live", "/obj/geo1/live")
        live["typeName"] = "acme::source::1.0"
        baseline = _baseline(extras=(live,))
        payload = _PreviewOperations(baseline=baseline).document_preview_bundle(
            {"bundle": _deferred_bundle().to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["readyForPlan"])
        edge = next(item for item in payload["preview"]["document"]["edges"] if item["kind"] == "data")
        self.assertEqual(edge["from"], {"nodeUid": "live-uid", "portIndex": 1, "portName": "points"})

        forged = _deferred_bundle().to_dict()
        forged["semanticResolution"]["operatorSelections"][0]["qualifiedName"] = "forged::sink"
        self._rehash(forged)
        blocked = _PreviewOperations(baseline=baseline).document_preview_bundle(
            {"bundle": forged}, RequestContext()
        )["structuredContent"]
        self.assertFalse(blocked["valid"])
        self.assertEqual(blocked["diagnostics"][0]["code"], "HOCUS722")

    def test_adopted_external_directives_set_selected_flags_and_displace_previous_flags(self) -> None:
        live = _node("live-uid", "live", "/obj/geo1/live")
        live["typeName"] = "acme::source::1.0"
        artist = _node("artist", "artist", "/obj/geo1/artist")
        artist["flags"]["display"] = True
        artist["flags"]["render"] = True
        baseline = _baseline(extras=(live, artist))
        payload = _PreviewOperations(baseline=baseline).document_preview_bundle(
            {"bundle": _deferred_bundle(adopted=True).to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertTrue(payload["valid"])
        nodes = {item["uid"]: item for item in payload["preview"]["document"]["nodes"]}
        self.assertTrue(nodes["live-uid"]["flags"]["display"])
        self.assertTrue(nodes["live-uid"]["flags"]["render"])
        self.assertFalse(nodes["artist"]["flags"]["display"])
        self.assertFalse(nodes["artist"]["flags"]["render"])
        actions = {item["action"] for item in payload["preview"]["candidatePlan"]["operations"]}
        self.assertIn("adopt_node", actions)
        self.assertIn("set_output", actions)

        second = _PreviewOperations(baseline=payload["preview"]["document"]).document_preview_bundle(
            {"bundle": _deferred_bundle(adopted=True).to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertTrue(second["valid"])
        self.assertEqual(second["preview"]["diff"]["summary"]["totalChangeCount"], 0)
        self.assertEqual(second["preview"]["candidatePlan"]["operations"], [])
        self.assertFalse(second["preview"]["destructiveSummary"]["ownershipTransfer"])

    def test_reconcile_preserves_still_declared_adopted_external(self) -> None:
        live = _node("live-uid", "live", "/obj/geo1/live")
        live["typeName"] = "acme::source::1.0"
        live["metadata"] = {"hocus": {
            "ownership": "studio.rocks",
            "sourceUri": "hocus-project://city/assets/previous.hocus",
            "jsonPointer": "/externalNodes/0",
            "span": {"sourceUri": "hocus-project://city/assets/previous.hocus", "start": {"line": 1, "column": 1, "offset": 0}, "end": {"line": 1, "column": 2, "offset": 1}},
        }}
        baseline = _baseline(extras=(live,))
        payload = _PreviewOperations(baseline=baseline).document_preview_bundle(
            {"bundle": _deferred_bundle(adopted=True, mode="reconcile").to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertTrue(payload["valid"])
        self.assertIn("live-uid", {item["uid"] for item in payload["preview"]["document"]["nodes"]})
        self.assertNotIn("live-uid", payload["preview"]["destructiveSummary"]["deletedNodeUids"])


if __name__ == "__main__":
    unittest.main()
