from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.operation_execution import _failure_commit_state
from hocuspocus.core.operation_history import (
    JOURNAL_MAX_BYTES,
    JOURNAL_SLOT_BYTES,
    SESSION_POLICY_PRINCIPAL,
    OperationHistory,
    argument_digest,
)


_OPERATION = "op:" + "a" * 32
_PENDING = "op:" + "b" * 32
_STALE = "op:" + "e" * 32
_RECOVERY = "op:" + "f" * 32
_NO_SLOT = "op:" + "9" * 32
_JOURNAL_FAILURE = "op:" + "8" * 32
_ALL_FAILURE = "op:" + "7" * 32


def _admit(
    history: OperationHistory,
    operation_id: str,
    *,
    principal: str = "principal-a",
    host: str = "host-a",
    generation: int = 1,
    arguments: dict | None = None,
) -> tuple[str, dict | None]:
    return history.admit(
        operation_id,
        "hda.promote_parameters",
        principal,
        "session-a",
        host,
        generation,
        argument_digest(arguments or {}),
        SESSION_POLICY_PRINCIPAL,
        True,
    )


def _assert_failure_commit_states(test: unittest.TestCase) -> None:
    unchanged = {"structuralChanged": False}
    changed = {"structuralChanged": True}
    rolled_back = JsonRpcError(
        -32009,
        "Apply aborted.",
        {
            "hocusCode": "HOCUS755",
            "failure": {"state": "aborted", "rolledBack": True},
        },
    )
    partial = JsonRpcError(
        -32009,
        "Apply outcome is unknown.",
        {"hocusCode": "HOCUS756", "failure": {"verified": False}},
    )
    test.assertEqual(_failure_commit_state(rolled_back, changed), "not_committed")
    test.assertEqual(_failure_commit_state(partial, unchanged), "partial_or_unknown")


def assert_delivery_revision_contract(test: unittest.TestCase) -> None:
    _assert_failure_commit_states(test)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "operations.sqlite3"
        first = OperationHistory(
            path, host_instance_id="host-a", host_generation=1
        )
        test.assertEqual(_admit(first, _OPERATION)[0], "new")
        result = {
            "content": [{
                "type": "text",
                "text": "Promoted parameters on /obj/brick_asset1.",
            }],
            "structuredContent": {
                "instancePath": "/obj/brick_asset1",
                "sourceParmPath": "/obj/brick_asset1/box1/sizex",
                "promotedParmPath": "/obj/brick_asset1/brick_width",
                "libraryFilePath": r"C:\private\brick.hda",
                "source": "float secret_source = 42;",
                "receipt": {"definition": "brick::1.0"},
            }
        }
        initial = first.finish(
            _OPERATION,
            principal_id="principal-a",
            commit_state="committed",
            result=result,
        )
        test.assertEqual(_admit(first, _PENDING)[0], "new")

        parallel = OperationHistory(
            path, host_instance_id="host-b", host_generation=1
        )
        current = parallel.lookup(
            _PENDING,
            "principal-a",
            host_instance_id="host-a",
            host_generation=1,
        )
        test.assertEqual(current["state"], "pending")
        test.assertEqual(
            _admit(parallel, _PENDING, host="host-b")[0], "pending"
        )
        pending_result = {
            "content": [{"type": "text", "text": "Finished by host A."}],
            "structuredContent": {"instancePath": "/obj/asset_from_a"},
        }
        first.finish(
            _PENDING,
            principal_id="principal-a",
            commit_state="committed",
            result=pending_result,
        )
        test.assertEqual(
            parallel.lookup(_PENDING, "principal-a")["terminalResult"],
            pending_result,
        )
        test.assertEqual(_admit(first, _STALE)[0], "new")
        first.close()

        stale = parallel.lookup(
            _STALE,
            "principal-a",
            host_instance_id="host-b",
            host_generation=1,
        )
        test.assertEqual(stale["commitState"], "partial_or_unknown")
        parallel.close()

        reopened = OperationHistory(
            path, host_instance_id="host-after-restart", host_generation=9
        )
        with mock.patch.object(
            reopened,
            "_reserve_journal",
            side_effect=OSError("injected reservation failure"),
        ):
            test.assertEqual(_admit(reopened, _NO_SLOT)[0], "capacity")
        test.assertIsNone(reopened.lookup(_NO_SLOT, "principal-a"))
        status, terminal = _admit(
            reopened, _OPERATION, host="host-after-restart", generation=9
        )
        test.assertEqual(status, "terminal")
        test.assertEqual(terminal, initial)
        test.assertEqual(terminal["hostInstanceId"], "host-a")
        test.assertEqual(terminal["terminalResult"], initial["terminalResult"])
        test.assertEqual(
            terminal["terminalResult"]["content"][0]["type"], "text"
        )
        receipt = terminal["terminalResult"]["structuredContent"]
        test.assertEqual(receipt["instancePath"], "/obj/brick_asset1")
        test.assertEqual(
            receipt["sourceParmPath"], "/obj/brick_asset1/box1/sizex"
        )
        test.assertEqual(
            receipt["promotedParmPath"], "/obj/brick_asset1/brick_width"
        )
        test.assertEqual(receipt["receipt"]["definition"], "brick::1.0")
        test.assertEqual(receipt["libraryFilePath"], "<redacted>")
        test.assertEqual(receipt["source"], "<redacted>")
        test.assertNotIn(r"C:\private", str(terminal))
        test.assertNotIn("secret_source", str(terminal))
        test.assertIsNone(reopened.lookup(_OPERATION, "principal-b"))
        test.assertEqual(
            _admit(reopened, _OPERATION, arguments={"different": True})[0],
            "collision",
        )

        test.assertEqual(_admit(reopened, _RECOVERY)[0], "new")
        with reopened._lock:
            reserved_row = reopened._row("principal-a", _RECOVERY)
        reserved_path = reopened._journal_dir / reserved_row["journal_name"]
        reserved_status = reserved_path.stat()
        test.assertEqual(reserved_status.st_size, JOURNAL_SLOT_BYTES)
        test.assertEqual(reserved_status.st_nlink, 1)
        test.assertEqual(reserved_status.st_dev, reserved_row["journal_device"])
        test.assertEqual(reserved_status.st_ino, reserved_row["journal_inode"])
        recovered_result = {
            "content": [{"type": "text", "text": "Committed safely."}],
            "structuredContent": {"instancePath": "/obj/recovered_asset"},
        }
        with (
            mock.patch.object(
                reopened,
                "_write_terminal_locked",
                side_effect=sqlite3.OperationalError("injected primary failure"),
            ),
            mock.patch.object(
                reopened, "_fallback_write_terminal", return_value=False
            ),
        ):
            recovered = reopened.finish(
                _RECOVERY,
                principal_id="principal-a",
                commit_state="committed",
                result=recovered_result,
            )
        test.assertEqual(recovered["terminalResult"], recovered_result)
        test.assertEqual(recovered["deliveryStage"], "terminal_journaled")

        test.assertEqual(_admit(reopened, _JOURNAL_FAILURE)[0], "new")
        with mock.patch.object(
            reopened,
            "_write_journal",
            side_effect=OSError("injected journal fsync failure"),
        ):
            journal_failed = reopened.finish(
                _JOURNAL_FAILURE,
                principal_id="principal-a",
                commit_state="committed",
                result=recovered_result,
            )
        test.assertEqual(journal_failed["deliveryStage"], "terminal")
        test.assertEqual(journal_failed["terminalResult"], recovered_result)

        test.assertEqual(_admit(reopened, _ALL_FAILURE)[0], "new")
        with (
            mock.patch.object(
                reopened,
                "_write_journal",
                side_effect=OSError("injected journal fsync failure"),
            ),
            mock.patch.object(
                reopened,
                "_write_terminal_locked",
                side_effect=sqlite3.OperationalError("injected primary failure"),
            ),
            mock.patch.object(
                reopened, "_fallback_write_terminal", return_value=False
            ),
        ):
            unpersisted = reopened.finish(
                _ALL_FAILURE,
                principal_id="principal-a",
                commit_state="committed",
                result=recovered_result,
            )
        test.assertEqual(unpersisted["deliveryStage"], "terminal_unpersisted")
        reopened.close()

        final = OperationHistory(
            path, host_instance_id="host-final", host_generation=1
        )
        final_record = final.lookup(_RECOVERY, "principal-a")
        test.assertEqual(final_record, recovered)
        test.assertEqual(final_record["terminalResult"], recovered_result)
        journal_failure_record = final.lookup(
            _JOURNAL_FAILURE, "principal-a"
        )
        test.assertEqual(journal_failure_record, journal_failed)
        unknown = final.lookup(
            _ALL_FAILURE,
            "principal-a",
            host_instance_id="host-final",
            host_generation=1,
        )
        test.assertEqual(unknown["commitState"], "partial_or_unknown")
        final.close()

    _assert_journal_reclamation(test)
    _assert_journal_namespace_race(test)


def _assert_journal_reclamation(test: unittest.TestCase) -> None:
    with tempfile.TemporaryDirectory() as directory:
        flush_path = Path(directory) / "flush-operations.sqlite3"
        flush_calls = []

        def fail_directory_flush(path):
            flush_calls.append(path)
            raise OSError("injected Windows directory flush failure")

        flush_owner = OperationHistory(
            flush_path,
            host_instance_id="flush-owner",
            host_generation=1,
            journal_directory_flusher=fail_directory_flush,
        )
        flush_operation = "op:" + "3" * 32
        test.assertEqual(
            _admit(flush_owner, flush_operation, host="flush-owner")[0],
            "capacity",
        )
        flush_dir = flush_path.parent / f"{flush_path.name}.journal"
        test.assertTrue(flush_calls)
        test.assertEqual(len(list(flush_dir.glob("*.slot"))), 1)
        test.assertIsNone(flush_owner.lookup(flush_operation, "principal-a"))
        flush_owner._journal_platform._directory_flusher = lambda _path: None
        flush_owner.close()

        crash_path = Path(directory) / "crash-operations.sqlite3"
        crashed = OperationHistory(
            crash_path, host_instance_id="crashed-owner", host_generation=1
        )
        crash_operation = "op:" + "4" * 32
        crash_time = time.time()
        crash_slot = crashed._reserve_journal(
            "principal-a",
            crash_operation,
            "node.create",
            argument_digest({"crash": True}),
        )
        crashed._lease_stop.set()
        if crashed._lease_thread is not None:
            crashed._lease_thread.join(timeout=3)
        crashed._connection.close()
        crash_journal = (
            crash_path.parent / f"{crash_path.name}.journal" / crash_slot.name
        )
        test.assertTrue(crash_journal.exists())
        with mock.patch(
            "hocuspocus.core.operation_history.time.time",
            return_value=crash_time + 31,
        ):
            recovered_owner = OperationHistory(
                crash_path,
                host_instance_id="crash-reopen",
                host_generation=1,
            )
            test.assertFalse(crash_journal.exists())
            test.assertEqual(
                _admit(
                    recovered_owner,
                    crash_operation,
                    host="crash-reopen",
                )[0],
                "new",
            )
            recovered_owner.close()

        path = Path(directory) / "orphan-operations.sqlite3"
        owner = OperationHistory(
            path, host_instance_id="orphan-owner", host_generation=1
        )
        slots = []
        for index in range(JOURNAL_MAX_BYTES // JOURNAL_SLOT_BYTES):
            slots.append(owner._reserve_journal(
                "principal-a",
                f"op:{index + 20:032x}",
                "node.create",
                argument_digest({"index": index}),
            ))
        test.assertTrue(slots)
        status = (path.parent / f"{path.name}.journal" / slots[0].name).stat()
        test.assertEqual(status.st_size, JOURNAL_SLOT_BYTES)
        capacity_operation = "op:" + "6" * 32
        test.assertEqual(
            _admit(
                owner,
                capacity_operation,
                host="orphan-owner",
                arguments={"overflow": True},
            )[0],
            "capacity",
        )
        test.assertIsNone(owner.lookup(capacity_operation, "principal-a"))
        stale_operation = f"op:{20:032x}"
        owner.close()

        journal_dir = path.parent / f"{path.name}.journal"
        test.assertEqual(list(journal_dir.glob("*.slot")), [])
        for index in range(270):
            (journal_dir / f"invalid-{index:03d}.slot").write_bytes(b"invalid")
        reopened = OperationHistory(
            path, host_instance_id="orphan-reopen", host_generation=1
        )
        test.assertEqual(list(journal_dir.glob("*.slot")), [])
        test.assertEqual(
            _admit(reopened, stale_operation, host="orphan-reopen")[0],
            "new",
        )
        reopened.close()


def _assert_journal_namespace_race(test: unittest.TestCase) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "race-operations.sqlite3"
        writer = OperationHistory(
            path, host_instance_id="race-writer", host_generation=1
        )
        operation_id = "op:" + "2" * 32
        test.assertEqual(
            _admit(writer, operation_id, host="race-writer")[0], "new"
        )
        result = {
            "content": [{"type": "text", "text": "Race committed."}],
            "structuredContent": {"instancePath": "/obj/race_asset"},
        }
        publish_started = threading.Event()
        release_publish = threading.Event()
        reader_done = threading.Event()
        outcomes = {}
        original_publish = writer._journal_platform.publish

        def paused_publish(identity, payload):
            publish_started.set()
            release_publish.wait(timeout=5)
            return original_publish(identity, payload)

        def finish_writer():
            outcomes["writer"] = writer.finish(
                operation_id,
                principal_id="principal-a",
                commit_state="committed",
                result=result,
            )

        def open_reader():
            reader = OperationHistory(
                path, host_instance_id="race-reader", host_generation=1
            )
            outcomes["reader"] = reader.lookup(operation_id, "principal-a")
            reader.close()
            reader_done.set()

        with mock.patch.object(
            writer._journal_platform, "publish", side_effect=paused_publish
        ):
            writer_thread = threading.Thread(target=finish_writer)
            writer_thread.start()
            test.assertTrue(publish_started.wait(timeout=3))
            reader_thread = threading.Thread(target=open_reader)
            reader_thread.start()
            test.assertFalse(reader_done.wait(timeout=0.2))
            test.assertEqual(
                len(list(writer._journal_dir.glob("*.slot"))), 1
            )
            release_publish.set()
            writer_thread.join(timeout=5)
            reader_thread.join(timeout=5)
        test.assertFalse(writer_thread.is_alive())
        test.assertFalse(reader_thread.is_alive())
        test.assertEqual(outcomes["writer"], outcomes["reader"])
        test.assertEqual(outcomes["reader"]["terminalResult"], result)
        writer.close()


__all__ = ["assert_delivery_revision_contract"]
