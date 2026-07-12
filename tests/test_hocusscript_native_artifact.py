from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

import hocuspocus.hocusscript.native_artifact as artifact_module
from hocuspocus.hocusscript.native_artifact import (
    NativeArtifactError, publish_text_artifact,
)


LIMIT = 4096


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _temps(root: Path) -> list[Path]:
    return list(root.glob(".*.tmp"))


class NativeArtifactTests(unittest.TestCase):
    def test_create_returns_frozen_host_path_free_receipt_and_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "bundle.json"
            receipt = publish_text_artifact(destination, "hello\n", max_bytes=LIMIT)
            self.assertEqual(destination.read_bytes(), b"hello\n")
            self.assertEqual(receipt.to_dict(), {
                "contentDigest": _digest(b"hello\n"),
                "byteLength": 6,
                "replaced": False,
            })
            self.assertNotIn(str(root), repr(receipt))
            with self.assertRaises(FrozenInstanceError):
                receipt.byte_length = 7
            with self.assertRaises(NativeArtifactError) as captured:
                publish_text_artifact(destination, "other", max_bytes=LIMIT)
            self.assertEqual(captured.exception.code, "HOCUS491")
            self.assertEqual(destination.read_bytes(), b"hello\n")
            self.assertEqual(_temps(root), [])

    def test_exact_replace_preserves_mode_and_missing_or_stale_authority_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "artifact.txt"
            destination.write_bytes(b"before")
            os.chmod(destination, 0o640)
            original_mode = stat.S_IMODE(destination.stat().st_mode)
            expected = _digest(b"before")
            receipt = publish_text_artifact(
                destination, "after", expected_digest=expected, max_bytes=LIMIT,
            )
            self.assertTrue(receipt.replaced)
            self.assertEqual(destination.read_bytes(), b"after")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), original_mode)
            with self.assertRaises(NativeArtifactError) as stale:
                publish_text_artifact(
                    destination, "wrong", expected_digest=expected, max_bytes=LIMIT,
                )
            self.assertEqual(stale.exception.code, "HOCUS491")
            self.assertEqual(destination.read_bytes(), b"after")
            with self.assertRaises(NativeArtifactError) as missing:
                publish_text_artifact(
                    root / "missing.txt", "new", expected_digest=_digest(b"missing"),
                    max_bytes=LIMIT,
                )
            self.assertEqual(missing.exception.code, "HOCUS491")
            self.assertEqual(_temps(root), [])

    def test_validation_encodes_and_bounds_before_filesystem_access(self) -> None:
        invalid = (
            {"text": "x", "expected_digest": "SHA256:" + "0" * 64, "max_bytes": LIMIT},
            {"text": "x", "expected_digest": "sha256:" + "A" * 64, "max_bytes": LIMIT},
            {"text": "\ud800", "expected_digest": None, "max_bytes": LIMIT},
            {"text": "too large", "expected_digest": None, "max_bytes": 1},
            {"text": "x", "expected_digest": None, "max_bytes": True},
        )
        with patch.object(Path, "mkdir") as mkdir:
            for values in invalid:
                with self.subTest(values=values), self.assertRaises(NativeArtifactError) as captured:
                    publish_text_artifact("never-created/out.txt", **values)
                self.assertEqual(captured.exception.code, "HOCUS490")
        mkdir.assert_not_called()

    def test_destination_appearance_and_change_races_preserve_competing_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            appeared = root / "appeared.txt"
            real_link = artifact_module.os.link

            def appear_then_link(source, destination):
                Path(destination).write_bytes(b"artist")
                return real_link(source, destination)

            with patch("hocuspocus.hocusscript.native_artifact.os.link", new=appear_then_link):
                with self.assertRaises(NativeArtifactError) as captured:
                    publish_text_artifact(appeared, "generated", max_bytes=LIMIT)
            self.assertEqual(captured.exception.code, "HOCUS491")
            self.assertEqual(appeared.read_bytes(), b"artist")
            self.assertEqual(_temps(root), [])

            changed = root / "changed.txt"
            changed.write_bytes(b"before")
            expected = _digest(b"before")
            real_read = artifact_module._read_digest
            destination_reads = 0

            def change_before_final_read(path, *, missing_is_conflict):
                nonlocal destination_reads
                if Path(path) == changed:
                    destination_reads += 1
                    if destination_reads == 2:
                        changed.write_bytes(b"artist")
                return real_read(path, missing_is_conflict=missing_is_conflict)

            with patch(
                "hocuspocus.hocusscript.native_artifact._read_digest",
                new=change_before_final_read,
            ):
                with self.assertRaises(NativeArtifactError) as captured:
                    publish_text_artifact(
                        changed, "generated", expected_digest=expected, max_bytes=LIMIT,
                    )
            self.assertEqual(captured.exception.code, "HOCUS491")
            self.assertEqual(changed.read_bytes(), b"artist")
            self.assertEqual(_temps(root), [])

    def test_temporary_content_is_digest_checked_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "artifact.txt"
            real_read = artifact_module._read_digest

            def corrupt_temp_digest(path, *, missing_is_conflict):
                if Path(path).suffix == ".tmp":
                    return _digest(b"corrupt")
                return real_read(path, missing_is_conflict=missing_is_conflict)

            with patch(
                "hocuspocus.hocusscript.native_artifact._read_digest",
                new=corrupt_temp_digest,
            ):
                with self.assertRaises(NativeArtifactError) as captured:
                    publish_text_artifact(destination, "generated", max_bytes=LIMIT)
            self.assertEqual(captured.exception.code, "HOCUS492")
            self.assertFalse(destination.exists())
            self.assertEqual(_temps(root), [])

    def test_link_replace_write_fsync_and_chmod_failures_are_non_destructive(self) -> None:
        cases = ("link", "replace", "write", "fsync", "chmod")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                destination = root / "artifact.txt"
                replacing = case in {"replace", "chmod"}
                if replacing:
                    destination.write_bytes(b"before")
                    expected = _digest(b"before")
                else:
                    expected = None

                if case == "link":
                    patcher = patch(
                        "hocuspocus.hocusscript.native_artifact.os.link",
                        side_effect=OSError("link failed"),
                    )
                elif case == "replace":
                    patcher = patch(
                        "hocuspocus.hocusscript.native_artifact.os.replace",
                        side_effect=OSError("replace failed"),
                    )
                elif case == "fsync":
                    patcher = patch(
                        "hocuspocus.hocusscript.native_artifact.os.fsync",
                        side_effect=OSError("fsync failed"),
                    )
                elif case == "chmod":
                    patcher = patch(
                        "hocuspocus.hocusscript.native_artifact.os.chmod",
                        side_effect=OSError("chmod failed"),
                    )
                else:
                    real_fdopen = artifact_module.os.fdopen

                    class FailingWriter:
                        def __init__(self, handle):
                            self.handle = handle

                        def __enter__(self):
                            self.handle.__enter__()
                            return self

                        def __exit__(self, *args):
                            return self.handle.__exit__(*args)

                        def write(self, _value):
                            raise OSError("write failed")

                        def flush(self):
                            return self.handle.flush()

                        def fileno(self):
                            return self.handle.fileno()

                    def failing_fdopen(*args, **kwargs):
                        return FailingWriter(real_fdopen(*args, **kwargs))

                    patcher = patch(
                        "hocuspocus.hocusscript.native_artifact.os.fdopen",
                        new=failing_fdopen,
                    )

                with patcher, self.assertRaises(NativeArtifactError) as captured:
                    publish_text_artifact(
                        destination, "generated", expected_digest=expected, max_bytes=LIMIT,
                    )
                self.assertEqual(captured.exception.code, "HOCUS492")
                if replacing:
                    self.assertEqual(destination.read_bytes(), b"before")
                else:
                    self.assertFalse(destination.exists())
                self.assertEqual(_temps(root), [])

    def test_cleanup_failure_after_publication_does_not_invalidate_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "artifact.txt"
            real_unlink = Path.unlink
            retained: list[Path] = []

            def fail_temp_cleanup(path, *args, **kwargs):
                if Path(path).suffix == ".tmp":
                    retained.append(Path(path))
                    raise OSError("cleanup failed")
                return real_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", new=fail_temp_cleanup):
                receipt = publish_text_artifact(destination, "published", max_bytes=LIMIT)
            self.assertEqual(receipt.content_digest, _digest(b"published"))
            self.assertEqual(destination.read_bytes(), b"published")
            self.assertTrue(retained)
            for path in retained:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
