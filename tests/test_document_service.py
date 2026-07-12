from __future__ import annotations

import logging
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.live.document_service import ApplyPlanError, LiveDocumentService, PreviewArtifactError


def _apply_plan(marker: str = "a", *, plan_id: str | None = None) -> dict:
    plan = {
        "kind": "hocus_apply_plan",
        "planVersion": "1.0",
        "sessionId": "session:test",
        "scope": "/obj/geo1",
        "operations": [{"sequence": 0, "action": "create_node", "marker": marker}],
    }
    if plan_id is not None:
        plan["planId"] = plan_id
    encoded = json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    plan["planHash"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return plan


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


class LiveDocumentServiceApplyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LiveDocumentService(logging.getLogger("test.documents"))

    def test_apply_plan_is_verified_content_addressed_and_detached(self) -> None:
        plan = _apply_plan()
        stored = self.service.store_apply_plan(plan)
        self.assertEqual(stored["planHash"], plan["planHash"])
        self.assertEqual(stored["planId"], plan["planHash"].removeprefix("sha256:"))
        self.assertEqual(stored["resourceUri"], f"houdini://documents/plans/{stored['planId']}")

        plan["operations"].clear()
        loaded = self.service.apply_plan(stored["planId"], expected_hash=stored["planHash"])
        self.assertEqual(len(loaded["operations"]), 1)
        loaded["operations"].clear()
        self.assertEqual(len(self.service.apply_plan(stored["planId"])["operations"]), 1)
        resource = self.service.apply_plan_resource(stored["planId"])
        self.assertEqual(resource["planHash"], stored["planHash"])
        self.assertEqual(resource["plan"]["kind"], "hocus_apply_plan")

        declared = self.service.store_apply_plan(_apply_plan("declared", plan_id="plan:declared"))
        self.assertEqual(declared["planId"], "plan:declared")
        with self.assertRaises(ApplyPlanError) as raised:
            self.service.store_apply_plan(_apply_plan("collision", plan_id="plan:declared"))
        self.assertEqual(raised.exception.code, "HOCUS731")

    def test_plan_hash_tampering_is_rejected_on_store_and_read(self) -> None:
        plan = _apply_plan()
        plan["scope"] = "/obj/tampered"
        with self.assertRaisesRegex(ApplyPlanError, "hash mismatch") as raised:
            self.service.store_apply_plan(plan)
        self.assertEqual(raised.exception.code, "HOCUS731")

        stored = self.service.store_apply_plan(_apply_plan())
        self.service._apply_plans[stored["planId"]].payload["scope"] = "/obj/tampered"
        with self.assertRaises(ApplyPlanError) as raised:
            self.service.apply_plan(stored["planId"])
        self.assertEqual(raised.exception.code, "HOCUS731")

    def test_plan_expiry_lru_budget_and_discard(self) -> None:
        self.service._MAX_APPLY_PLANS = 2
        first = self.service.store_apply_plan(_apply_plan("a"))
        second = self.service.store_apply_plan(_apply_plan("b"))
        self.service._apply_plans[first["planId"]].last_accessed_at -= 1.0
        third = self.service.store_apply_plan(_apply_plan("c"))
        self.assertIsNone(self.service.apply_plan(first["planId"]))
        self.assertIsNotNone(self.service.apply_plan(second["planId"]))
        self.assertTrue(self.service.discard_apply_plan(third["planId"], expected_hash=third["planHash"]))
        self.assertFalse(self.service.discard_apply_plan(third["planId"]))

        expiring = self.service.store_apply_plan(_apply_plan("expires"), ttl_seconds=1)
        self.service._apply_plans[expiring["planId"]].expires_at = 0
        self.assertIsNone(self.service.apply_plan(expiring["planId"]))

    def test_idempotency_reservation_replays_detached_result_and_binds_plan(self) -> None:
        stored = self.service.store_apply_plan(_apply_plan())
        reserved = self.service.reserve_apply_result(
            "request-1", plan_id=stored["planId"], plan_hash=stored["planHash"]
        )
        pending = self.service.reserve_apply_result(
            "request-1", plan_id=stored["planId"], plan_hash=stored["planHash"]
        )
        self.assertEqual(pending["state"], "reserved")
        self.assertNotIn("reservationId", pending)

        result = {"status": "applied", "nodes": ["/obj/geo1/a"]}
        self.service.commit_apply_result(reserved["reservationId"], result)
        result["nodes"].clear()
        replay = self.service.reserve_apply_result(
            "request-1", plan_id=stored["planId"], plan_hash=stored["planHash"]
        )
        self.assertEqual(replay["state"], "committed")
        self.assertEqual(replay["result"]["nodes"], ["/obj/geo1/a"])
        replay["result"]["nodes"].clear()
        self.assertEqual(self.service.apply_result("request-1")["result"]["nodes"], ["/obj/geo1/a"])

        with self.assertRaises(ApplyPlanError) as raised:
            self.service.reserve_apply_result(
                "request-1", plan_id="different", plan_hash=stored["planHash"]
            )
        self.assertEqual(raised.exception.code, "HOCUS736")

    def test_aborting_reservation_allows_retry(self) -> None:
        stored = self.service.store_apply_plan(_apply_plan())
        first = self.service.reserve_apply_result(
            "request-2", plan_id=stored["planId"], plan_hash=stored["planHash"]
        )
        self.assertTrue(self.service.abort_apply_result(first["reservationId"]))
        second = self.service.reserve_apply_result(
            "request-2", plan_id=stored["planId"], plan_hash=stored["planHash"]
        )
        self.assertNotEqual(first["reservationId"], second["reservationId"])

    def test_scope_write_leases_reject_overlaps_and_release_on_context_exit(self) -> None:
        lease = self.service.acquire_scope_write_lease("/obj/geo1/", holder_id="apply:a")
        with self.assertRaises(ApplyPlanError) as raised:
            self.service.acquire_scope_write_lease("/obj/geo1/subnet")
        self.assertEqual(raised.exception.code, "HOCUS739")
        independent = self.service.acquire_scope_write_lease("/obj/geo2")
        self.assertTrue(self.service.release_scope_write_lease("/obj/geo2", independent["leaseId"]))
        self.assertTrue(self.service.release_scope_write_lease("/obj/geo1", lease["leaseId"]))

        with self.assertRaisesRegex(RuntimeError, "apply failed"):
            with self.service.scope_write_lease("/obj/geo1"):
                raise RuntimeError("apply failed")
        replacement = self.service.acquire_scope_write_lease("/obj/geo1")
        self.assertTrue(self.service.release_scope_write_lease("/obj/geo1", replacement["leaseId"]))


if __name__ == "__main__":
    unittest.main()
