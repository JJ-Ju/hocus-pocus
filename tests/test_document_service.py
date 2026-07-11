from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.live.document_service import LiveDocumentService, PreviewArtifactError


class LiveDocumentServicePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LiveDocumentService(logging.getLogger("test.documents"))

    def test_preview_artifacts_are_content_addressed_and_detached(self) -> None:
        payload = {"kind": "hocus_document_preview", "document": {"nodes": [{"uid": "node:a"}]}}
        first = self.service.store_preview_artifact(payload)
        second = self.service.store_preview_artifact(payload)

        self.assertEqual(first, second)
        self.assertEqual(first["contentDigest"], "sha256:" + first["previewId"])
        self.assertEqual(first["resourceUri"], f"houdini://documents/previews/{first['previewId']}")

        payload["document"]["nodes"][0]["uid"] = "mutated"
        stored = self.service.preview_artifact(first["previewId"])
        self.assertEqual(stored["document"]["nodes"][0]["uid"], "node:a")
        stored["document"]["nodes"].clear()
        self.assertEqual(len(self.service.preview_artifact(first["previewId"])["document"]["nodes"]), 1)

    def test_unknown_preview_is_absent(self) -> None:
        self.assertIsNone(self.service.preview_artifact("0" * 64))

    def test_oversized_preview_is_rejected_before_retention(self) -> None:
        self.service._MAX_PREVIEW_ARTIFACT_BYTES = 64
        with self.assertRaises(PreviewArtifactError):
            self.service.store_preview_artifact({"payload": "x" * 128})
        self.assertEqual(self.service.preview_artifact_stats()["count"], 0)

    def test_aggregate_budget_evicts_least_recently_used_artifact(self) -> None:
        payloads = [{"payload": character * 40} for character in ("a", "b", "c")]
        size = self.service._preview_encoding(payloads[0])[1]
        self.service._MAX_PREVIEW_ARTIFACT_BYTES = size
        self.service._MAX_PREVIEW_TOTAL_BYTES = size * 2
        first = self.service.store_preview_artifact(payloads[0])
        second = self.service.store_preview_artifact(payloads[1])
        self.service._previews[first["previewId"]].last_accessed_at -= 1.0
        self.assertIsNotNone(self.service.preview_artifact(second["previewId"]))
        third = self.service.store_preview_artifact(payloads[2])

        self.assertIsNone(self.service.preview_artifact(first["previewId"]))
        self.assertIsNotNone(self.service.preview_artifact(second["previewId"]))
        self.assertIsNotNone(self.service.preview_artifact(third["previewId"]))
        stats = self.service.preview_artifact_stats()
        self.assertEqual(stats["count"], 2)
        self.assertLessEqual(stats["totalBytes"], stats["maxTotalBytes"])


if __name__ == "__main__":
    unittest.main()
