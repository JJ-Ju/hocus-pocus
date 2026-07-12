from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.lock_update_result import ModuleLockUpdateEntry, ModuleLockUpdateResult
from hocuspocus.hocusscript.project import LockVerificationResult, ModuleLockRecord

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
D4 = "sha256:" + "4" * 64
D5 = "sha256:" + "5" * 64


def _record(name: str, digest: str) -> ModuleLockRecord:
    uri = f"hocus-project://city/modules/{name}.hocus"
    return ModuleLockRecord(
        uri, "city", None, None, None, "0.2", f"modules/{name}.hocus",
        digest, D3, D4, (), None,
    )


class ModuleLockUpdateResultTests(unittest.TestCase):
    def test_create_and_replace_receipts_are_sorted_host_path_free_and_diff_exact(self) -> None:
        alpha = _record("alpha", D1)
        beta = _record("beta", D2)
        created_verification = LockVerificationResult("city", D3, D4, (beta, alpha))
        created = ModuleLockUpdateResult.from_verifications(
            None, created_verification,
            catalog_content_digest=D1, catalog_fingerprint=D2,
            entries=(ModuleLockUpdateEntry("hocus-project://city/src/main.hocus", D5),),
            previous_lock_digest=None,
        )
        self.assertTrue(created.changed)
        self.assertIsNone(created.previous_lock_digest)
        self.assertEqual(tuple(item.module_uri for item in created.modules),
                         (alpha.module_uri, beta.module_uri))
        self.assertEqual(created.added_uris, (alpha.module_uri, beta.module_uri))
        self.assertEqual(created.verification.modules, created.modules)
        self.assertNotIn("project_directory", created.to_dict())

        alpha_changed = _record("alpha", D5)
        after = LockVerificationResult("city", D3, D5, (alpha_changed,))
        replaced = ModuleLockUpdateResult.from_verifications(
            created.verification, after,
            catalog_content_digest=D1, catalog_fingerprint=D2,
            entries=created.entries,
            previous_lock_digest=D4,
        )
        self.assertEqual(replaced.added_uris, ())
        self.assertEqual(replaced.removed_uris, (beta.module_uri,))
        self.assertEqual(replaced.changed_uris, (alpha.module_uri,))
        self.assertEqual(replaced.to_dict()["previousLockDigest"], D4)

        repaired = ModuleLockUpdateResult.from_verifications(
            None, after, catalog_content_digest=D1, catalog_fingerprint=D2,
            entries=created.entries, previous_lock_digest=D4,
        )
        self.assertTrue(repaired.changed)
        self.assertFalse(repaired.diff_available)
        self.assertEqual(repaired.to_dict()["diff"], {
            "available": False, "addedUris": [], "removedUris": [], "changedUris": [],
        })

    def test_receipt_rejects_invalid_digest_and_unsorted_records(self) -> None:
        alpha, beta = _record("alpha", D1), _record("beta", D2)
        with self.assertRaises(ValueError):
            ModuleLockUpdateResult(
                "city", D3, D4, "bad", D1, D2, (), (alpha,), True, (), (), (),
            )
        with self.assertRaises(ValueError):
            ModuleLockUpdateResult(
                "city", D3, D4, D5, D1, D2, (), (beta, alpha), True, (), (), (),
            )


if __name__ == "__main__":
    unittest.main()
